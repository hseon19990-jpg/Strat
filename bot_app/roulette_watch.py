"""مراقبة قنوات الروليت والمشاركة التلقائية بحسابات المالك فقط.

الفكرة:
1. المالك يضيف قنوات من /roulette.
2. مهمة دورية تراقب هذه القنوات بحساب مالك واحد (ينضم لها أولاً).
3. عند ظهور منشور سحب (زر رابط بوت فيه start مثل «المشاركة في السحب»)
   تبدأ كل حسابات المالك معاً: تنضم لقناة المنشور، تفتح البوت، ثم تنفذ
   الشروط الظاهرة (انضمام لقناة، تعليق على منشور) وتضغط زر التحقق.
4. يصل المالك ملخص بالنتيجة مع آخر رسالة من البوت لكل فشل، لتسهيل الضبط.

الحسابات المستخدمة: كل حسابات الرشق التي أضافها المالك بأي طريقة (contributed_by فارغ أو OWNER_ID)، دون حسابات الأعضاء.
شروط التصويت لمتسابق غير مدعومة بعد؛ تُسجَّل وتُبلَّغ للمالك.
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import re
from io import BytesIO
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from telethon import TelegramClient, functions
from telethon.sessions import StringSession
from telethon.tl.types import PeerChannel

from . import shared as _shared
from .users import get_setting, set_setting
from .raksh_system.common import (
    _get_raksh_session_lock,
    _get_sessions_for_service,
    _join_channel_and_schedule_leave,
    _parse_bot_link,
    _parse_channel_refs,
    _parse_post_link,
)

globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

KEY_CHANNELS = "roulette_channels"
KEY_STATE = "roulette_state"
KEY_ENABLED = "roulette_enabled"
KEY_COMMENTS = "roulette_comment_texts"

POLL_MESSAGES_LIMIT = 6
MAX_CONCURRENCY = 40
MAX_ROUNDS = 6
MONITOR_LEAVE_SECONDS = 60 * 60 * 24 * 365
LOCK_WAIT_SECONDS = 25
ROULETTE_LEAVE_SECONDS = 60 * 60 * 24 * 7  # لا يغادر الحساب قنوات السحب/الشروط قبل نهاية السحب
ACCOUNT_GAP_SECONDS = 10  # فاصل بدء كل حساب عن الذي قبله

PARTICIPATE_WORDS = (
    "المشاركة في السحب", "مشاركة السحب", "شارك في السحب",
    "المشاركة في المسابقة", "مشاركة المسابقة", "شارك في المسابقة", "participate", "giveaway",
)
VERIFY_WORDS = ("تحقق", "تأكيد", "check", "verify", "confirm", "تم", "انتهيت", "done", "شارك", "مشاركة")
BACK_WORDS = ("رجوع", "back", "استبعاد", "إلغاء", "الغاء", "cancel", "تخطي", "skip")
SUCCESS_WORDS = (
    "تم تسجيلك", "تمت مشاركتك", "تمت المشاركة", "تم المشاركة", "تم الاشتراك في السحب",
    "أنت مشارك", "انت مشارك", "مشارك بالفعل", "you are participating", "successfully registered",
    "تم تسجيل مشاركتك",
)
READY_WORDS = (
    "يمكنك مشاركة السحب", "يمكنك المشاركة في السحب", "you can now participate",
    "you can participate", "can now join",
)
# زر المشاركة الفعلي تحت منشور القناة (زر Callback وليس رابطاً)
CHANNEL_JOIN_WORDS = ("المشاركة في السحب", "المشاركة بالسحب", "شارك في السحب", "participate", "join giveaway")
FAIL_ANSWER_WORDS = ("خطأ", "فشل", "غير مسموح", "لا يمكن", "error", "failed", "not allowed")
# شرط الاشتراك داخل نص المنشور: روابط مخفية تحت كلمة «الشرط»
CONDITION_MARKERS = ("الشرط", "الشروط", "condition")
IGNORE_ANCHOR_WORDS = ("جميع السحوبات", "السحوبات", "روليت سراب")
VOTE_WORDS = ("تصويت", "التصويت", "صوت", "vote")
VOTE_SUCCESS_WORDS = (
    "تم التصويت", "تم تسجيل صوتك", "تم احتساب صوتك", "شكرا لتصويتك", "شكراً لتصويتك",
    "صوّتت لهذا الشخص", "سبق وصوت", "already voted", "vote counted", "thank you for voting",
)
CAPTCHA_MARKERS = (
    "كابتشا", "captcha", "تحقق", "verify", "robot", "روبوت", "بشر", "human",
    "أدخل", "ادخل", "اكتب", "أجب", "retype", "send the text", "type the text",
)
VOTE_POST_SKIP_WORDS = ("نسخ", "copy", "احصائيات", "إحصائيات", "statistics", "stats", "إعادة النشر")
VOTE_MAX_ATTEMPTS = 8      # أقصى عدد مرات إعادة التصويت (كل مرة بعد انضمام جديد)
VOTE_MAX_CAPTCHA_TRIES = 2
AI_CAPTCHA_MAX_CLICKS = 2   # أقصى ضغطات بالذكاء لكل حساب قبل التحويل لك يدوياً
VOTE_SOLVE_TIMEOUT = 900  # أقصى مدة لحل الكابتشا لكل محاولة (ثانية)، تتسع لحل المالك اليدوي
IGNORABLE_URL_NOTES = {"رابط بوت", "رابط خارجي", "رابط فارغ"}
DEFAULT_COMMENTS = ["👍", "🔥", "❤️", "👏", "شكراً", "موفقين", "تمام"]

_job_lock = asyncio.Lock()
_handled: set = set()


# ─────────────────────────── التخزين ───────────────────────────

def _load_json(key: str, default):
    try:
        value = json.loads(get_setting(key) or "")
        return value if isinstance(value, type(default)) else default
    except Exception:
        return default


def _load_channels() -> List[str]:
    return [str(x) for x in _load_json(KEY_CHANNELS, [])]


def _save_channels(channels: List[str]) -> None:
    set_setting(KEY_CHANNELS, json.dumps(list(dict.fromkeys(channels)), ensure_ascii=False))


def _load_state() -> Dict:
    return _load_json(KEY_STATE, {})


def _save_state(state: Dict) -> None:
    set_setting(KEY_STATE, json.dumps(state, ensure_ascii=False))


def _is_enabled() -> bool:
    return get_setting(KEY_ENABLED) == "1"


def _comment_texts() -> List[str]:
    lines = [line.strip() for line in (get_setting(KEY_COMMENTS) or "").splitlines() if line.strip()]
    return lines or DEFAULT_COMMENTS


def _owner_sessions() -> List[Dict]:
    """حسابات المالك حصراً: كل حساب أضافه المالك لمخزون الرشق بأي طريقة
    (أزرار، ملف، جلسة، تسجيل دخول...). هذه الحسابات تُحفظ بدون contributed_by،
    أو بـ contributed_by=OWNER_ID إن أُضيفت عبر مسار المساهم. أما حسابات
    الأعضاء (contributed_by لمستخدم آخر) فمستثناة.
    """
    sessions = _get_sessions_for_service("roulette", is_owner=True)
    owner_id = int(OWNER_ID)
    result = []
    for s in sessions:
        if not str(s.get("session_string") or "").strip():
            continue
        contributor = s.get("contributed_by")
        if contributor is None or int(contributor) == owner_id:
            result.append(s)
    return result


def _new_client(session: Dict) -> TelegramClient:
    return TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
        flood_sleep_threshold=10,
        connection_retries=2,
        retry_delay=1,
        request_retries=2,
    )


# ─────────────────────────── أدوات الرسائل ───────────────────────────

def _btn_text(btn) -> str:
    for candidate in (btn, getattr(btn, "button", None)):
        text = getattr(candidate, "text", None) if candidate is not None else None
        if text:
            return str(text)
    return ""


def _flatten_buttons(message) -> List[Tuple[int, int, object]]:
    result = []
    for i, row in enumerate(getattr(message, "buttons", None) or []):
        for j, btn in enumerate(row):
            result.append((i, j, btn))
    return result


def _extract_trigger_base(message) -> Optional[Dict]:
    """يلتقط زر المشاركة في منشور سحب: زر رابط بوت مع start."""
    text = (getattr(message, "message", "") or "")
    fallback = None
    for _i, _j, btn in _flatten_buttons(message):
        url = getattr(btn, "url", None)
        if not url:
            continue
        bot_username, start_param = _parse_bot_link(url)
        if not bot_username or not start_param:
            continue
        label = _btn_text(btn)
        if any(word in label.lower() for word in PARTICIPATE_WORDS):
            return {"bot": bot_username, "param": start_param, "label": label}
        fallback = fallback or {"bot": bot_username, "param": start_param, "label": label}
    if fallback and ("سحب" in text or "روليت" in text or "giveaway" in text.lower()):
        return fallback
    return None


def _extract_conditions(message) -> List[Dict]:
    """روابط قنوات الاشتراك الموجودة داخل نص المنشور نفسه (روابط مخفية تحت «الشرط»)."""
    text = getattr(message, "message", "") or ""
    try:
        pairs = message.get_entities_text() or []
    except Exception:
        pairs = []
    utf16 = text.encode("utf-16-le")
    marker_at = None
    for word in CONDITION_MARKERS:
        idx = text.lower().find(word)
        if idx != -1 and (marker_at is None or idx < marker_at):
            marker_at = idx
    result: List[Dict] = []
    seen = set()
    for ent, label in pairs:
        url = getattr(ent, "url", None)
        if not url and label.lower().startswith(("http", "t.me")):
            url = label
        if not url or url in seen:
            continue
        start = len(utf16[: ent.offset * 2].decode("utf-16-le", errors="ignore"))
        if marker_at is not None and start < marker_at:
            continue
        if any(word in label for word in IGNORE_ANCHOR_WORDS):
            continue
        parsed = urlparse(url if "://" in url else f"https://{url}")
        if parsed.netloc.lower().removeprefix("www.") not in {"t.me", "telegram.me"}:
            continue
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if not parts:
            continue
        if len(parts) == 1 and parts[0].lower().endswith("bot"):
            # رابط بوت: شرط تصويت فقط إذا كان السطر يتكلم عن التصويت
            line_start = text.rfind("\n", 0, start) + 1
            line = re.sub("[\u0640\u064B-\u0652]", "", text[line_start:start] + " " + label).lower()
            if any(word in line for word in VOTE_WORDS):
                seen.add(url)
                result.append({"url": url, "label": label, "kind": "vote"})
            continue
        # رابط منشور في سطر التصويت: المنشور فيه زر التصويت (أو زر يفتح بوت التصويت)
        post_ref, post_id = _parse_post_link(url)
        if post_ref and post_id:
            line_start = text.rfind("\n", 0, start) + 1
            line = re.sub("[\u0640\u064B-\u0652]", "", text[line_start:start] + " " + label).lower()
            if any(word in line for word in VOTE_WORDS):
                seen.add(url)
                result.append({"url": url, "label": label, "kind": "vote_post"})
                continue
        seen.add(url)
        result.append({"url": url, "label": label, "kind": "channel"})
    return result


def _extract_trigger(message) -> Optional[Dict]:
    trig = _extract_trigger_base(message)
    if trig is not None:
        trig["conditions"] = _extract_conditions(message)
    return trig


def _is_success(text: str) -> bool:
    lowered = (text or "").lower()
    return any(word in lowered for word in SUCCESS_WORDS)


# ─────────────────────────── تنفيذ الشروط ───────────────────────────

async def _entity_for(client, ref: str):
    """كيان قناة من @username أو معرف خاص -100..."""
    if ref.startswith("@"):
        return await client.get_entity(ref)
    peer = PeerChannel(int(ref[4:]))
    try:
        return await client.get_entity(peer)
    except Exception:
        await client.get_dialogs()
        return await client.get_entity(peer)


async def _join_discussion_and_comment(client, entity, msg_id: int, text: str) -> None:
    try:
        await client.send_message(entity, text, comment_to=msg_id)
        return
    except Exception as first_error:
        # قد يحتاج الحساب للانضمام لمجموعة النقاش المرتبطة قبل التعليق.
        try:
            discussion = await client(functions.messages.GetDiscussionMessageRequest(peer=entity, msg_id=msg_id))
            chats = getattr(discussion, "chats", None) or []
            for chat in chats:
                if getattr(chat, "id", None) != getattr(entity, "id", None):
                    await client(functions.channels.JoinChannelRequest(chat))
            await client.send_message(entity, text, comment_to=msg_id)
        except Exception:
            raise first_error


async def _handle_url(client, url: str, label: str, phone: str) -> Tuple[bool, str]:
    """ينفذ شرطاً واحداً من رابط. يعيد (تم_التنفيذ, ملاحظة)."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    if parsed.netloc.lower().removeprefix("www.") not in {"t.me", "telegram.me"}:
        return False, "رابط خارجي"
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    query = parse_qs(parsed.query)
    if not parts:
        return False, "رابط فارغ"
    lowered_label = label.lower()

    # قناة بدعوة
    if parts[0].startswith("+") or parts[0] == "joinchat":
        invite = parts[-1].lstrip("+")
        joined = await _join_channel_and_schedule_leave(
            client, f"invite:{invite}", phone, leave_after_seconds=ROULETTE_LEAVE_SECONDS
        )
        if joined is False or joined is None:
            return False, "تعذر الانضمام بالدعوة"
        return True, "انضمام بدعوة"

    # بوت: ليس شرطاً ننفذه
    if len(parts) == 1 and parts[0].lower().endswith("bot"):
        return False, "رابط بوت"

    # قناة عامة
    if len(parts) == 1:
        joined = await _join_channel_and_schedule_leave(
            client, f"@{parts[0]}", phone, leave_after_seconds=ROULETTE_LEAVE_SECONDS
        )
        if joined is False or joined is None:
            return False, f"تعذر الانضمام لـ @{parts[0]}"
        return True, "انضمام لقناة"

    # رابط منشور
    ref, msg_id = _parse_post_link(url)
    if not ref or not msg_id:
        return False, "رابط منشور غير مفهوم"
    if "تصويت" in lowered_label or "vote" in lowered_label or "متسابق" in lowered_label:
        return False, "شرط تصويت غير مدعوم بعد"
    joined = await _join_channel_and_schedule_leave(
        client, ref, phone, leave_after_seconds=ROULETTE_LEAVE_SECONDS
    )
    if joined is False or joined is None:
        return False, f"تعذر الانضمام لـ {ref}"
    entity = await _entity_for(client, ref)
    if "comment" in query or "تعليق" in lowered_label or "comment" in lowered_label:
        await _join_discussion_and_comment(client, entity, msg_id, random.choice(_comment_texts()))
        return True, "تعليق"
    return True, "فتح المنشور"


def _latest_incoming(messages, base_id: int):
    return [m for m in messages if not getattr(m, "out", False) and (getattr(m, "id", 0) or 0) > base_id]


def _looks_like_captcha(message) -> bool:
    """كابتشا محتملة: صورة، أو كلمات تحقق، أو سؤال حسابي (لا نستدعي الحل بدونها)."""
    from .raksh_system.forced_ref_ai import ForcedRefAIService as _S  # استيراد متأخر

    text = (getattr(message, "message", "") or "").lower()
    if _S._has_image_media(message):
        return True
    if any(word in text for word in CAPTCHA_MARKERS):
        return True
    return _S._extract_math_answer(text) is not None


async def _wait_incoming(client, bot_entity, base_id: int, seconds: float = 9.0):
    """ينتظر رد البوت الجديد (وما يتبعه من رسائل) بعد Start."""
    waited = 0.0
    while waited < seconds:
        await asyncio.sleep(1.5)
        waited += 1.5
        if _latest_incoming(await client.get_messages(bot_entity, limit=6), base_id):
            await asyncio.sleep(1.5)
            return _latest_incoming(await client.get_messages(bot_entity, limit=6), base_id)
    return []


async def _join_requested(client, messages, phone: str, joined_urls: set) -> Tuple[int, str]:
    """ينضم لكل قناة/مجموعة جديدة يطلبها بوت التصويت (أزرار روابط). يعيد (عدد ما انضم له، خطأ)."""
    joined = 0
    for message in messages[:3]:
        for _i, _j, btn in _flatten_buttons(message):
            url = getattr(btn, "url", None)
            if not url or url in joined_urls:
                continue
            joined_urls.add(url)
            try:
                done, note = await _handle_url(client, url, _btn_text(btn), phone)
            except Exception as exc:
                return joined, f"فشل انضمام شرط التصويت: {str(exc)[:70]}"
            if done:
                joined += 1
            elif note not in IGNORABLE_URL_NOTES:
                return joined, f"تعذر شرط التصويت: {note}"
            await asyncio.sleep(1)
    return joined, ""


async def _click_verify(message, phone: str) -> None:
    """زر «تحقق/تم الاشتراك» إن وُجد (Callback)."""
    for i, j, btn in _flatten_buttons(message):
        label = _btn_text(btn).lower()
        if getattr(btn, "url", None) or not label or any(w in label for w in BACK_WORDS):
            continue
        if any(w in label for w in VERIFY_WORDS):
            try:
                await message.click(i, j)
            except Exception as exc:
                logger.debug("[%s] ضغط زر تحقق التصويت: %s", phone, exc)
            return


# ─────────────────────── حل كابتشا الإيموجي بالذكاء ───────────────────────

def _image_mime(data: bytes) -> str:
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _ai_ask_once(keys: List[str], image_b64: str, mime: str, labels: List[str], order: List[int], key_offset: int, models: Optional[List[str]] = None) -> Optional[int]:
    """سؤال واحد لـ Gemini: أي زر يطابق الصورة؟ الأزرار تُعرض بالترتيب order.
    يعيد فهرس الزر الأصلي (من 0) أو None إن لم يكن متأكداً أو فشل الطلب."""
    from . import ai_help as _ai  # استيراد متأخر

    numbered = "\n".join(f"{n + 1}: {labels[idx]}" for n, idx in enumerate(order))
    prompt = (
        "الصورة المرفقة فيها رمز إيموجي واحد (قد تكون مشوشة بخطوط ونقاط). "
        "اختر الخيار الذي يطابق الإيموجي في الصورة تماماً من القائمة التالية:\n"
        f"{numbered}\n"
        'أجب JSON فقط بهذا الشكل: {"choice": رقم_الخيار, "sure": true أو false}. '
        "اجعل sure=false إن لم تكن متأكداً تماماً أو إن تشابه خياران."
    )
    body = {
        "contents": [{"role": "user", "parts": [
            {"inlineData": {"mimeType": mime, "data": image_b64}},
            {"text": prompt},
        ]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 700, "responseMimeType": "application/json"},
    }
    models = list(models or _ai._aih_order_models(_ai._aih_model_list()))
    for step in range(len(keys)):
        key = keys[(key_offset + step) % len(keys)]
        for model in models:
            try:
                response = _ai._aih_gemini_post(_ai.AIH_GEMINI_URL, model, key, body)
            except Exception:
                continue
            code = response.status_code
            if code == 200:
                try:
                    data = response.json()
                    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
                    text = re.sub(r"```(?:json)?", "", text).strip()
                    result = json.loads(text)
                    choice = int(result.get("choice"))
                    sure = result.get("sure") is True
                except Exception:
                    continue
                if not sure or not 1 <= choice <= len(order):
                    return None
                return order[choice - 1]
            if code in (401, 403, 429):
                break  # مفتاح مرفوض أو حصته انتهت: جرّب المفتاح التالي
    return None


def _captcha_model_tiers() -> Tuple[List[str], List[str]]:
    """(نماذج سريعة رخيصة، نماذج أقوى كحَكَم). تُضبط من متغيرات البيئة بدون تعديل الكود:
    ROULETTE_CAPTCHA_MODEL_FAST و ROULETTE_CAPTCHA_MODEL_STRONG (يقبل كل منهما عدة نماذج بفواصل)."""
    import os
    from . import ai_help as _ai  # استيراد متأخر

    def _split(raw: str) -> List[str]:
        return [m.strip() for m in (raw or "").split(",") if m.strip()]

    fast = _split(os.environ.get("ROULETTE_CAPTCHA_MODEL_FAST", "")) or ["gemini-3.5-flash-lite"]
    strong = _split(os.environ.get("ROULETTE_CAPTCHA_MODEL_STRONG", "")) or ["gemini-3.8-flash"]
    # احتياط: نماذج المساعد الحالية بعد الأقوى إن لم يتوفر النموذج المضبوط
    strong = list(dict.fromkeys(strong + list(_ai._aih_order_models(_ai._aih_model_list()))))
    return list(dict.fromkeys(fast)), strong


def _ai_pick_sync(image_bytes: bytes, labels: List[str]) -> Optional[int]:
    """مرحلتان: النموذج السريع أولاً، وإن لم يتفق جوابا ترتيبين مختلفين للأزرار ينتقل للأقوى.
    لا نضغط إلا إذا اتفق جوابان على نفس الزر في مرحلة واحدة، وإلا تُرحَّل الكابتشا للمالك."""
    keys = [k for k in (_shared.get_ai_api_keys() or []) if k]
    if not keys or len(set(labels)) != len(labels) or any(not l for l in labels):
        return None
    image_b64 = base64.b64encode(image_bytes).decode()
    mime = _image_mime(image_bytes)
    straight = list(range(len(labels)))
    fast, strong = _captcha_model_tiers()
    for tier, models in (("fast", fast), ("strong", strong)):
        first = _ai_ask_once(keys, image_b64, mime, labels, straight, 0, models)
        if first is None:
            continue
        second = _ai_ask_once(keys, image_b64, mime, labels, list(reversed(straight)), 1, models)
        if second == first:
            logger.info("🤖 اتفق جوابا النموذج (%s) على الزر %s", tier, first + 1)
            return first
    return None


async def _try_ai_emoji_captcha(client, incoming, phone: str) -> bool:
    """كابتشا صورة + أزرار إيموجي: يختار Gemini الزر ويضغطه. يعيد True إن ضغط زراً."""
    from .raksh_system.forced_ref_ai import ForcedRefAIService as _S  # استيراد متأخر

    for message in incoming:
        flat = [(i, j, b) for i, j, b in _flatten_buttons(message) if not _S._is_invitation_link_button(b)]
        buttons = [b for _i, _j, b in flat]
        if not _S._is_manual_image_captcha(message, getattr(message, "message", "") or "", buttons):
            continue
        labels = [(_S._button_label(b) or "").strip() for b in buttons]
        try:
            buffer = BytesIO()
            await client.download_media(message, file=buffer)
            image_bytes = buffer.getvalue()
            if not image_bytes:
                return False
            index = await asyncio.wait_for(asyncio.to_thread(_ai_pick_sync, image_bytes, labels), timeout=60)
        except Exception as exc:
            logger.info("[%s] تعذر حل كابتشا الإيموجي بالذكاء: %s", phone, exc)
            return False
        if index is None:
            logger.info("[%s] الذكاء غير متأكد من كابتشا الإيموجي؛ تُرحَّل للمالك", phone)
            return False
        i, j, _btn = flat[index]
        try:
            await asyncio.wait_for(message.click(i, j), timeout=20)
        except asyncio.TimeoutError:
            pass
        except Exception as exc:
            logger.info("[%s] ضغط زر الكابتشا بالذكاء: %s", phone, exc)
            return False
        logger.info("🤖 [%s] اختار الذكاء الزر %s (%s) للكابتشا", phone, index + 1, labels[index])
        return True
    return False


async def _do_vote(client, phone: str, cond: Dict, bot=None) -> Tuple[bool, str]:
    """شرط تصويت عبر بوت.

    كل محاولة = ضغط رابط التصويت (Start). إن طلب البوت قناة/مجموعة ينضم لها الحساب
    ثم يعيد التصويت من جديد؛ يتكرر هذا حتى تنتهي كل القنوات الإجبارية. بعدها إما
    يظهر كابتشا فيُحَل، أو لا يطلب البوت كابتشا ويُحتسب الصوت.
    """
    from .raksh_system.forced_ref_ai import ForcedRefAIService  # استيراد متأخر لتفادي الدوران

    bot_username, start_param = _parse_bot_link(cond["url"])
    if not bot_username:
        return False, "رابط التصويت غير مفهوم"
    bot_entity = await client.get_entity(f"@{bot_username}")
    solver = ForcedRefAIService()

    joined_urls: set = set()
    total_joined = 0
    captcha_tries = 0
    ai_clicks = 0
    ai_solved = 0
    solved = False
    last = "لا رد من بوت التصويت"
    for _attempt in range(VOTE_MAX_ATTEMPTS):
        latest = await client.get_messages(bot_entity, limit=1)
        base_id = (latest[0].id if latest else 0) or 0
        await client(functions.messages.StartBotRequest(bot=bot_entity, peer=bot_entity, start_param=start_param or ""))
        incoming = await _wait_incoming(client, bot_entity, base_id)
        if not incoming:
            continue
        texts = " ".join((m.message or "") for m in incoming[:3]).lower()
        last = ((incoming[0].message or "").replace("\n", " ")[:70]) or last
        if any(word in texts for word in VOTE_SUCCESS_WORDS):
            return True, f"صوّت (انضم لـ {total_joined} قناة/مجموعة)"

        # 1) قنوات/مجموعات إجبارية جديدة: انضم ثم أعد التصويت
        joined, error = await _join_requested(client, incoming, phone, joined_urls)
        if error:
            return False, error
        if joined:
            total_joined += joined
            await _click_verify(incoming[0], phone)
            continue

        # 2) لا قنوات جديدة: كابتشا؟
        if any(_looks_like_captcha(m) for m in incoming):
            # كابتشا صورة + أزرار إيموجي: نجرب الذكاء أولاً، وإن لم ينجح تصلك أنت
            if ai_clicks < AI_CAPTCHA_MAX_CLICKS and await _try_ai_emoji_captcha(client, incoming, phone):
                ai_clicks += 1
                await asyncio.sleep(2)
                after = _latest_incoming(await client.get_messages(bot_entity, limit=6), base_id)
                after_texts = " ".join((m.message or "") for m in after[:3]).lower()
                if any(word in after_texts for word in VOTE_SUCCESS_WORDS):
                    return True, f"صوّت (انضم لـ {total_joined}، حلّ الكابتشا بالذكاء)"
                ai_solved += 1
                continue  # يعيد Start: إما يكتمل التصويت أو تظهر كابتشا جديدة
            if captcha_tries >= VOTE_MAX_CAPTCHA_TRIES:
                break
            captcha_tries += 1
            try:
                solved = bool(await asyncio.wait_for(
                    solver._solve_verification(
                        client, bot_entity, phone, base_id=base_id,
                        # كابتشا الصورة والإيموجي تُرحَّل للمالك ليحلها بنفسه
                        params={"_runtime_bot": bot, "requester_id": int(OWNER_ID)},
                    ),
                    timeout=VOTE_SOLVE_TIMEOUT,
                ))
            except asyncio.TimeoutError:
                logger.info("[%s] انتهت مهلة كابتشا التصويت", phone)
            except Exception as exc:
                logger.warning("[%s] كابتشا التصويت: %s", phone, exc)
            await asyncio.sleep(2)
            after = _latest_incoming(await client.get_messages(bot_entity, limit=6), base_id)
            after_texts = " ".join((m.message or "") for m in after[:3]).lower()
            if after:
                last = ((after[0].message or "").replace("\n", " ")[:70]) or last
            if solved or any(word in after_texts for word in VOTE_SUCCESS_WORDS):
                return True, f"صوّت (انضم لـ {total_joined}، حلّ الكابتشا)"
            continue  # قد تظهر قناة جديدة بعد الكابتشا

        break  # لا قنوات ولا كابتشا ولا رسالة نجاح معروفة
    return False, f"لم يكتمل التصويت: {last}"


def _label_number(label: str) -> Optional[int]:
    digits = re.sub(r"\D+", "", label or "")
    return int(digits) if digits else None


def _requested_channels(text: str) -> List[str]:
    """قنوات/مجموعات مذكورة في نص رد الزر (@username أو رابط t.me)."""
    found: List[str] = []
    for match in re.findall(r"(?:https?://)?t\.me/[A-Za-z0-9_+/]+|@[A-Za-z0-9_]{4,}", text or ""):
        found.append(match if not match.startswith("@") else f"https://t.me/{match[1:]}")
    return list(dict.fromkeys(found))


async def _do_vote_post(client, phone: str, cond: Dict, bot=None) -> Tuple[bool, str]:
    """الرابط يؤدي إلى منشور في قناة: فيه زر تصويت مباشر (Callback) أو زر يفتح بوت التصويت."""
    ref, msg_id = _parse_post_link(cond["url"])
    if not ref or not msg_id:
        return False, "رابط منشور التصويت غير مفهوم"
    joined = await _join_channel_and_schedule_leave(
        client, ref, phone, leave_after_seconds=ROULETTE_LEAVE_SECONDS
    )
    if joined is False or joined is None:
        return False, f"تعذر الانضمام لقناة منشور التصويت {ref}"
    entity = await _entity_for(client, ref)
    message = await client.get_messages(entity, ids=msg_id)
    if not message:
        return False, "منشور التصويت غير موجود"
    buttons = _flatten_buttons(message)

    # 1) زر رابط يفتح بوت التصويت
    for _i, _j, btn in buttons:
        url = getattr(btn, "url", None)
        if url and _parse_bot_link(url)[0]:
            return await _do_vote(client, phone, {"url": url, "label": _btn_text(btn)}, bot=bot)

    # 2) زر تصويت مباشر (Callback): الضغط، وإن طلب الرد قناة ينضم لها ويعيد الضغط
    target = None
    for i, j, btn in buttons:
        label = _btn_text(btn)
        if getattr(btn, "url", None) or not getattr(btn, "data", None):
            continue
        if any(word in label.lower() for word in VOTE_POST_SKIP_WORDS):
            continue
        target = (i, j, label)
        break
    if not target:
        labels = " / ".join(_btn_text(b) for _i, _j, b in buttons)
        return False, "لم أجد زر تصويت في المنشور: " + labels[:70]

    before = _label_number(target[2])
    joined_urls: set = set()
    total_joined = 0
    last = "بدون رد ظاهر"
    for _attempt in range(VOTE_MAX_ATTEMPTS):
        try:
            answer = await asyncio.wait_for(message.click(target[0], target[1]), timeout=20)
        except asyncio.TimeoutError:
            answer = None
        text = (getattr(answer, "message", "") or "").strip()
        if text:
            last = text.replace("\n", " ")[:70]
        if any(word in text.lower() for word in VOTE_SUCCESS_WORDS):
            return True, f"صوّت من المنشور (انضم لـ {total_joined})"
        # رد يطلب قناة/مجموعة: انضم ثم أعد الضغط
        new_urls = [u for u in _requested_channels(text) if u not in joined_urls]
        if not new_urls:
            break
        for url in new_urls:
            joined_urls.add(url)
            try:
                done, note = await _handle_url(client, url, "", phone)
            except Exception as exc:
                return False, f"فشل انضمام شرط التصويت: {str(exc)[:70]}"
            if done:
                total_joined += 1
            elif note not in IGNORABLE_URL_NOTES:
                return False, f"تعذر شرط التصويت: {note}"
            await asyncio.sleep(1)
        await asyncio.sleep(1)

    # لا رد نصي: تحقق من زيادة العداد على الزر
    try:
        fresh = await client.get_messages(entity, ids=msg_id)
        after = None
        for i, j, btn in _flatten_buttons(fresh):
            if (i, j) == (target[0], target[1]):
                after = _label_number(_btn_text(btn))
        if before is not None and after is not None and after > before:
            return True, f"صوّت من المنشور (العداد {before}→{after})"
    except Exception:
        pass
    if last == "بدون رد ظاهر":
        return True, "ضغط زر التصويت (بدون رد ظاهر)"
    return False, f"لم يكتمل التصويت: {last}"


async def _press_channel_button(client, trig: Dict) -> Tuple[bool, str]:
    """بعد أن يقول البوت «يمكنك مشاركة السحب الآن»: يرجع الحساب لمنشور القناة
    ويضغط زر «المشاركة في السحب [N]» (زر Callback) لتسجيل المشاركة فعلياً."""
    entity = await _entity_for(client, trig["ref"])
    message = await client.get_messages(entity, ids=trig["msg_id"])
    if not message:
        return False, "منشور السحب غير موجود"
    target = None
    for i, j, btn in _flatten_buttons(message):
        if getattr(btn, "url", None):
            continue  # زر الرابط (مشاركة السحب ↗) ليس المقصود هنا
        label = _btn_text(btn).lower()
        if any(word in label for word in CHANNEL_JOIN_WORDS):
            target = (i, j, _btn_text(btn))
            break
    if not target:
        labels = [_btn_text(b) for _i, _j, b in _flatten_buttons(message)]
        return False, "لم أجد زر المشاركة تحت المنشور: " + " / ".join(labels)[:80]
    try:
        answer = await asyncio.wait_for(message.click(target[0], target[1]), timeout=20)
    except asyncio.TimeoutError:
        return False, "ضغط زر المشاركة بلا رد من البوت"
    text = (getattr(answer, "message", "") or "").strip()
    if text and any(word in text.lower() for word in FAIL_ANSWER_WORDS):
        return False, f"رد الزر: {text[:80]}"
    return True, f"ضغط زر المشاركة" + (f" — رد: {text[:60]}" if text else " (بدون رد ظاهر)")


async def _participate(session: Dict, trig: Dict, semaphore: asyncio.Semaphore, runtime_bot=None) -> Tuple[bool, str]:
    phone = session.get("phone_number")
    async with semaphore:
        lock = _get_raksh_session_lock(session)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=LOCK_WAIT_SECONDS)
        except asyncio.TimeoutError:
            return False, "الحساب مشغول بخدمة أخرى"
        client = _new_client(session)
        try:
            await asyncio.wait_for(client.connect(), timeout=15)
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                return False, "الجلسة غير مصرح بها"

            # كل قناة تراقب يجب أن ينضم لها الحساب أولاً
            joined = await _join_channel_and_schedule_leave(
                client, trig["ref"], phone, leave_after_seconds=ROULETTE_LEAVE_SECONDS
            )
            if joined is False or joined is None:
                return False, "تعذر الانضمام لقناة السحب"

            # شرط الاشتراك الموجود داخل نص المنشور: يجب الانضمام لكل قناة مشروطة
            cond_done = 0
            vote_conds = [c for c in (trig.get("conditions") or []) if c.get("kind") in ("vote", "vote_post")]
            for cond in [c for c in (trig.get("conditions") or []) if c.get("kind") not in ("vote", "vote_post")]:
                try:
                    done, note = await _handle_url(client, cond["url"], cond["label"], phone)
                except Exception as exc:
                    return False, f"فشل شرط الاشتراك: {str(exc)[:80]}"
                if not done:
                    return False, f"تعذر شرط الاشتراك: {note}"
                cond_done += 1
                await asyncio.sleep(1)

            vote_note = ""
            for cond in vote_conds:
                try:
                    if cond.get("kind") == "vote_post":
                        voted, vnote = await _do_vote_post(client, phone, cond, bot=runtime_bot)
                    else:
                        voted, vnote = await _do_vote(client, phone, cond, bot=runtime_bot)
                except Exception as exc:
                    return False, f"فشل شرط التصويت: {str(exc)[:80]}"
                if not voted:
                    return False, vnote
                vote_note = vnote

            bot = await client.get_entity(f"@{trig['bot']}")
            await client(functions.messages.StartBotRequest(bot=bot, peer=bot, start_param=trig["param"]))

            handled_urls = set()
            notes: List[str] = []
            last_text = ""
            for round_no in range(MAX_ROUNDS):
                await asyncio.sleep(3 if round_no == 0 else 2)
                messages = await client.get_messages(bot, limit=3)
                message = next((m for m in messages if not getattr(m, "out", False)), None)
                if not message:
                    continue
                last_text = (message.message or "")[:200]
                logger.info("🎰 [%s] رد البوت (جولة %s): %s", phone, round_no + 1, last_text.replace("\n", " "))
                if _is_success(last_text):
                    return True, last_text[:80]
                if any(word in last_text.lower() for word in READY_WORDS):
                    # البوت جهّز الحساب؛ المشاركة الفعلية بزر تحت منشور القناة
                    try:
                        pressed, pnote = await _press_channel_button(client, trig)
                        if pressed and vote_note:
                            pnote = vote_note + " + " + pnote
                        elif pressed and cond_done:
                            pnote = f"انضم لـ {cond_done} قناة شرط + " + pnote
                        return pressed, pnote
                    except Exception as exc:
                        return False, f"فشل ضغط زر القناة: {str(exc)[:80]}"

                acted = False
                buttons = _flatten_buttons(message)
                for _i, _j, btn in buttons:
                    url = getattr(btn, "url", None)
                    if not url or url in handled_urls:
                        continue
                    handled_urls.add(url)
                    try:
                        done, note = await _handle_url(client, url, _btn_text(btn), phone)
                    except Exception as exc:
                        done, note = False, f"فشل شرط: {str(exc)[:60]}"
                    notes.append(note)
                    acted = acted or done

                await asyncio.sleep(1.5)
                for i, j, btn in buttons:
                    label = _btn_text(btn).lower()
                    if getattr(btn, "url", None) or not label:
                        continue
                    if any(w in label for w in BACK_WORDS):
                        continue
                    if any(w in label for w in VERIFY_WORDS):
                        try:
                            await message.click(i, j)
                        except Exception as exc:
                            logger.debug("[%s] ضغط زر التحقق: %s", phone, exc)
                        acted = True
                        break
                if not acted:
                    break

            messages = await client.get_messages(bot, limit=3)
            message = next((m for m in messages if not getattr(m, "out", False)), None)
            last_text = ((message.message if message else "") or last_text)[:200]
            if _is_success(last_text):
                return True, last_text[:80]
            return False, ("؛ ".join(notes) + " | " if notes else "") + (last_text[:100] or "لا رد من البوت")
        except Exception as exc:
            return False, f"خطأ: {str(exc)[:100]}"
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
            lock.release()


async def _run_roulette(bot, trig: Dict, sessions: List[Dict]) -> None:
    """يشغّل كل حسابات المالك معاً على سحب واحد ويرسل ملخصاً."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def _staggered(index: int, session: Dict):
        # حساب واحد كل ACCOUNT_GAP_SECONDS ثوانٍ: الأول فوراً، الثاني بعد 10ث، وهكذا
        if index:
            await asyncio.sleep(index * ACCOUNT_GAP_SECONDS)
        return await _participate(session, trig, semaphore, runtime_bot=bot)

    if sessions:
        minutes = max(1, round((len(sessions) - 1) * ACCOUNT_GAP_SECONDS / 60))
        try:
            await bot.send_message(
                OWNER_ID,
                f"🚀 بدأ الروليت على {trig['ref']}: {len(sessions)} حساب، "
                f"فاصل {ACCOUNT_GAP_SECONDS} ثوانٍ بين كل حساب (≈ {minutes} دقيقة). سيصلك الملخص عند الانتهاء.",
            )
        except Exception:
            pass
    results = await asyncio.gather(
        *[_staggered(index, session) for index, session in enumerate(sessions)],
        return_exceptions=True,
    )
    ok = 0
    failures: Dict[str, int] = {}
    successes: Dict[str, int] = {}
    for result in results:
        if isinstance(result, BaseException):
            reason = f"خطأ: {str(result)[:80]}"
            failures[reason] = failures.get(reason, 0) + 1
            continue
        success, note = result
        if success:
            ok += 1
            successes[note] = successes.get(note, 0) + 1
        else:
            failures[note] = failures.get(note, 0) + 1
    lines = [
        "🎰 روليت جديد",
        f"📢 القناة: {trig['ref']}",
        f"🤖 البوت: @{trig['bot']}",
        f"👥 الحسابات: {len(sessions)}",
        f"✅ نجح: {ok}",
        f"❌ فشل: {len(sessions) - ok}",
    ]
    if successes:
        lines.append("\nتفاصيل النجاح:")
        for reason, count in sorted(successes.items(), key=lambda kv: -kv[1])[:3]:
            lines.append(f"• ({count}) {reason}")
    if failures:
        lines.append("\nأسباب الفشل:")
        for reason, count in sorted(failures.items(), key=lambda kv: -kv[1])[:6]:
            lines.append(f"• ({count}) {reason}")
    try:
        await bot.send_message(OWNER_ID, "\n".join(lines))
    except Exception:
        logger.warning("تعذر إرسال ملخص الروليت للمالك")


# ─────────────────────────── المراقبة ───────────────────────────

async def _resolve_channel(client, ref: str, state: Dict, phone: str):
    info = state.get(ref) or {}
    cid = info.get("id")
    if cid:
        try:
            return await client.get_entity(PeerChannel(int(cid)))
        except Exception:
            try:
                await client.get_dialogs()
                return await client.get_entity(PeerChannel(int(cid)))
            except Exception:
                pass
    entity = await _join_channel_and_schedule_leave(
        client, ref, phone, return_entity=True, leave_after_seconds=MONITOR_LEAVE_SECONDS
    )
    if entity is None or isinstance(entity, bool):
        return None
    state.setdefault(ref, {})["id"] = entity.id
    return entity


async def _poll_channels(bot, channels: List[str], sessions: List[Dict]) -> None:
    triggers: List[Dict] = []
    state = _load_state()
    for session in sessions[:5]:
        lock = _get_raksh_session_lock(session)
        if lock.locked():
            continue
        async with lock:
            client = _new_client(session)
            try:
                await asyncio.wait_for(client.connect(), timeout=15)
                if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                    continue
                phone = session.get("phone_number")
                for ref in channels:
                    try:
                        entity = await _resolve_channel(client, ref, state, phone)
                        if entity is None:
                            continue
                        messages = await asyncio.wait_for(
                            client.get_messages(entity, limit=POLL_MESSAGES_LIMIT), timeout=20
                        )
                        if not messages:
                            continue
                        newest = max(m.id for m in messages)
                        info = state.setdefault(ref, {})
                        if info.get("baseline") is None:
                            # أول مرة: لا نعالج المنشورات القديمة
                            info["baseline"] = info.get("last") or newest
                            info["last"] = newest
                            continue
                        info["last"] = newest
                        done_ids = set(info.get("handled") or [])
                        # نفحص كل المنشورات الحديثة (حتى التي أُضيف زرها بالتعديل بعد النشر)
                        for message in sorted((m for m in messages if m.id > info["baseline"]), key=lambda m: m.id):
                            key = (ref, message.id)
                            if key in _handled or message.id in done_ids:
                                continue
                            trig = _extract_trigger(message)
                            if trig:
                                _handled.add(key)
                                done_ids.add(message.id)
                                trig["ref"] = ref
                                trig["msg_id"] = message.id
                                triggers.append(trig)
                        info["handled"] = sorted(done_ids)[-50:]
                    except Exception as exc:
                        logger.warning("تعذرت مراقبة القناة %s: %s", ref, exc)
                _save_state(state)
                break  # حساب مراقبة واحد يكفي
            except Exception as exc:
                logger.warning("تعذر تشغيل حساب مراقبة الروليت: %s", exc)
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass
    for trig in triggers:
        logger.info("🎰 سحب جديد في %s (منشور %s) عبر @%s", trig["ref"], trig["msg_id"], trig["bot"])
        asyncio.create_task(_run_roulette(bot, trig, _owner_sessions()))


async def _join_monitor_channels(refs: List[str]) -> Tuple[List[str], List[str]]:
    """ينضم حساب مالك فوراً لكل قناة مضافة. يعيد (انضم، لم ينضم)."""
    state = _load_state()
    for session in _owner_sessions()[:5]:
        lock = _get_raksh_session_lock(session)
        if lock.locked():
            continue
        async with lock:
            client = _new_client(session)
            try:
                await asyncio.wait_for(client.connect(), timeout=15)
                if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                    continue
                phone = session.get("phone_number")
                joined: List[str] = []
                failed: List[str] = []
                for ref in refs:
                    try:
                        entity = await asyncio.wait_for(_resolve_channel(client, ref, state, phone), timeout=40)
                    except Exception as exc:
                        logger.warning("انضمام قناة الروليت %s: %s", ref, exc)
                        entity = None
                    (joined if entity else failed).append(ref)
                _save_state(state)
                return joined, failed
            except Exception as exc:
                logger.warning("تعذر تشغيل حساب انضمام الروليت: %s", exc)
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass
    return [], list(refs)


async def _join_one_account(session: Dict, refs: List[str], delay: int, semaphore: asyncio.Semaphore) -> Tuple[int, str]:
    """ينضم حساب واحد لكل القنوات. يعيد (عدد القنوات التي انضم لها، سبب الفشل إن وُجد)."""
    if delay:
        await asyncio.sleep(delay)
    phone = session.get("phone_number")
    async with semaphore:
        lock = _get_raksh_session_lock(session)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=LOCK_WAIT_SECONDS)
        except asyncio.TimeoutError:
            return 0, "الحساب مشغول بخدمة أخرى"
        client = _new_client(session)
        try:
            await asyncio.wait_for(client.connect(), timeout=15)
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                return 0, "الجلسة غير مصرح بها"
            done = 0
            for ref in refs:
                result = await _join_channel_and_schedule_leave(
                    client, ref, phone, leave_after_seconds=MONITOR_LEAVE_SECONDS
                )
                if result is not False and result is not None:
                    done += 1
            return done, "" if done == len(refs) else "تعذر الانضمام لبعض القنوات"
        except Exception as exc:
            return 0, f"خطأ: {str(exc)[:80]}"
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
            lock.release()


async def _join_all_owner_accounts(bot, refs: List[str]) -> None:
    """كل حسابات المالك تنضم للقنوات الجديدة، حساب كل ACCOUNT_GAP_SECONDS ثوانٍ."""
    sessions = _owner_sessions()
    if not sessions or not refs:
        return
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    results = await asyncio.gather(
        *[
            _join_one_account(session, refs, index * ACCOUNT_GAP_SECONDS, semaphore)
            for index, session in enumerate(sessions)
        ],
        return_exceptions=True,
    )
    ok = 0
    failures: Dict[str, int] = {}
    for result in results:
        if isinstance(result, BaseException):
            reason = f"خطأ: {str(result)[:80]}"
        else:
            done, reason = result
            if done == len(refs):
                ok += 1
                continue
        failures[reason] = failures.get(reason, 0) + 1
    lines = [
        "📥 انضمام حسابات المالك للقنوات الجديدة",
        "📢 " + "، ".join(refs[:5]) + (f" (+{len(refs) - 5})" if len(refs) > 5 else ""),
        f"👥 الحسابات: {len(sessions)}",
        f"✅ انضم: {ok}",
        f"❌ فشل: {len(sessions) - ok}",
    ]
    if failures:
        lines.append("\nأسباب الفشل:")
        for reason, count in sorted(failures.items(), key=lambda kv: -kv[1])[:6]:
            lines.append(f"• ({count}) {reason}")
    try:
        await bot.send_message(OWNER_ID, "\n".join(lines))
    except Exception:
        logger.warning("تعذر إرسال ملخص انضمام الروليت للمالك")


async def run_roulette_watch_job(context) -> None:
    if _job_lock.locked() or not _is_enabled():
        return
    async with _job_lock:
        try:
            channels = _load_channels()
            sessions = _owner_sessions()
            if channels and sessions:
                await _poll_channels(context.bot, channels, sessions)
        except Exception:
            logger.exception("فشل مهمة مراقبة الروليت")


# ─────────────────────────── لوحة المالك ───────────────────────────

def _panel_text() -> str:
    channels = _load_channels()
    return (
        "🎰 مراقبة الروليت\n\n"
        f"الحالة: {'✅ مفعّلة' if _is_enabled() else '⛔ متوقفة'}\n"
        f"📢 القنوات المراقبة: {len(channels)}\n"
        f"👥 حسابات المالك: {len(_owner_sessions())}\n"
        f"💬 نصوص التعليق: {len(_comment_texts())}"
    )


def _panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⛔ إيقاف" if _is_enabled() else "✅ تشغيل", callback_data="roulette:toggle")],
        [
            InlineKeyboardButton("➕ إضافة قنوات", callback_data="roulette:add"),
            InlineKeyboardButton("📋 القنوات", callback_data="roulette:list"),
        ],
        [
            InlineKeyboardButton("✍️ نصوص التعليق", callback_data="roulette:comments"),
            InlineKeyboardButton("▶️ تنفيذ يدوي", callback_data="roulette:manual"),
        ],
    ])


def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="roulette:menu")]])


async def cmd_roulette(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    context.user_data.pop("roulette_step", None)
    await update.message.reply_text(_panel_text(), reply_markup=_panel_kb())


async def handle_roulette_callback(update, context):
    query = update.callback_query
    if query.from_user.id != OWNER_ID:
        await query.answer("للمالك فقط", show_alert=True)
        return
    await query.answer()
    data = query.data or ""
    action = data.split(":", 1)[1] if ":" in data else "menu"

    if action == "menu":
        context.user_data.pop("roulette_step", None)
        await query.edit_message_text(_panel_text(), reply_markup=_panel_kb())
    elif action == "toggle":
        set_setting(KEY_ENABLED, "0" if _is_enabled() else "1")
        await query.edit_message_text(_panel_text(), reply_markup=_panel_kb())
    elif action == "add":
        context.user_data["roulette_step"] = "add_channels"
        await query.edit_message_text(
            "📢 أرسل القنوات (@username أو رابط t.me أو رابط دعوة)، كل قناة في سطر.",
            reply_markup=_back_kb(),
        )
    elif action == "list":
        channels = _load_channels()
        if not channels:
            await query.edit_message_text("لا توجد قنوات مضافة.", reply_markup=_back_kb())
            return
        rows = [
            [InlineKeyboardButton(f"🗑 {ref[:40]}", callback_data=f"roulette:del:{index}")]
            for index, ref in enumerate(channels)
        ]
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="roulette:menu")])
        await query.edit_message_text("اضغط على قناة لحذفها:", reply_markup=InlineKeyboardMarkup(rows))
    elif action.startswith("del:"):
        channels = _load_channels()
        try:
            removed = channels.pop(int(action[4:]))
        except (ValueError, IndexError):
            removed = None
        _save_channels(channels)
        if removed:
            state = _load_state()
            state.pop(removed, None)
            _save_state(state)
        await query.edit_message_text(_panel_text(), reply_markup=_panel_kb())
    elif action == "comments":
        context.user_data["roulette_step"] = "comments"
        await query.edit_message_text(
            "✍️ أرسل نصوص التعليق، كل نص في سطر (يُختار واحد عشوائياً لكل حساب).\n"
            "أرسل «افتراضي» للعودة للنصوص الافتراضية.",
            reply_markup=_back_kb(),
        )
    elif action == "manual":
        context.user_data["roulette_step"] = "manual"
        await query.edit_message_text(
            "▶️ أرسل رابط منشور السحب (https://t.me/channel/123) لتشغيل المشاركة عليه الآن.",
            reply_markup=_back_kb(),
        )


async def handle_roulette_text(update, context) -> bool:
    step = context.user_data.get("roulette_step")
    if not step or update.effective_user.id != OWNER_ID:
        return False
    text = (update.message.text or "").strip()

    if step == "add_channels":
        refs = _parse_channel_refs(text)
        if not refs:
            await update.message.reply_text("⚠️ لم أتعرف على أي قناة. أعد الإرسال.", reply_markup=_back_kb())
            return True
        context.user_data.pop("roulette_step", None)
        wait_msg = await update.message.reply_text("⏳ جاري انضمام حساب المراقبة للقنوات...")
        joined, failed = await _join_monitor_channels(refs)
        # لا تُحفظ القناة إلا إذا انضم لها حساب فعلاً
        if joined:
            _save_channels(_load_channels() + joined)
        lines = []
        if joined:
            total = len(_owner_sessions())
            minutes = max(1, round((total - 1) * ACCOUNT_GAP_SECONDS / 60))
            lines.append(
                f"✅ أُضيفت {len(joined)} قناة. جميع حساباتك ({total}) ستنضم لها الآن، "
                f"حساب كل {ACCOUNT_GAP_SECONDS} ثوانٍ (≈ {minutes} دقيقة)، وسيصلك ملخص."
            )
            asyncio.create_task(_join_all_owner_accounts(context.bot, joined))
        if failed:
            lines.append(
                f"⚠️ تعذر الانضمام ولم تُضف ({len(failed)}):\n" + "\n".join(f"• {r}" for r in failed[:10])
                + "\nتأكد أن القناة موجودة وأن لديك حسابات مالك سليمة."
            )
        try:
            await wait_msg.delete()
        except Exception:
            pass
        await update.message.reply_text("\n\n".join(lines), reply_markup=_panel_kb())
        return True

    if step == "comments":
        set_setting(KEY_COMMENTS, "" if text == "افتراضي" else text)
        context.user_data.pop("roulette_step", None)
        await update.message.reply_text("✅ تم حفظ نصوص التعليق.", reply_markup=_panel_kb())
        return True

    if step == "manual":
        ref, msg_id = _parse_post_link(text)
        context.user_data.pop("roulette_step", None)
        sessions = _owner_sessions()
        if not ref or not msg_id or not sessions:
            await update.message.reply_text("⚠️ رابط غير صحيح أو لا توجد حسابات مالك.", reply_markup=_panel_kb())
            return True
        await update.message.reply_text("⏳ جاري قراءة المنشور...")
        trig = None
        for session in sessions[:3]:
            lock = _get_raksh_session_lock(session)
            if lock.locked():
                continue
            async with lock:
                client = _new_client(session)
                try:
                    await asyncio.wait_for(client.connect(), timeout=15)
                    entity = await _entity_for(client, ref)
                    message = await client.get_messages(entity, ids=msg_id)
                    if message:
                        trig = _extract_trigger(message)
                except Exception as exc:
                    logger.warning("قراءة منشور الروليت اليدوي: %s", exc)
                finally:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
            if trig:
                break
        if not trig:
            await update.message.reply_text("⚠️ لم أجد زر مشاركة في هذا المنشور.", reply_markup=_panel_kb())
            return True
        trig["ref"] = ref
        trig["msg_id"] = msg_id
        await update.message.reply_text(
            f"🚀 بدأت {len(sessions)} حساب بالمشاركة عبر @{trig['bot']}. سيصلك ملخص."
        )
        asyncio.create_task(_run_roulette(context.bot, trig, sessions))
        return True

    return False
