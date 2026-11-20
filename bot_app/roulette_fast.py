"""الروليت السريع: مراقبة لحظية + ضغط الزر بكل حسابات المالك في وقت واحد.

لماذا نوع مختلف؟ هذه السحوبات (مثل «انضم ✅» أو «الإنضمام إلى السحب») تُغلق خلال أجزاء من الثانية،
فلا يصلح معها الفحص الدوري ولا فتح اتصال جديد لكل حساب. الفكرة:

1. مجمّع اتصالات: كل حساب مالك (حتى ROULETTE_FAST_MAX_ACCOUNTS) يبقى متصلاً، وقد حلّ كيان كل قناة
   مراقبة مسبقاً، فلا يبقى وقت الضغط إلا طلب واحد.
2. مراقبة لحظية: حسابان (ROULETTE_FAST_LISTENERS) يستقبلان منشورات القنوات وتعديلاتها فور صدورها.
3. عند ظهور زر انضمام (Callback) تُرسل كل الحسابات طلب الضغط معاً (asyncio.gather) بلا فواصل ولا طوابير.
4. بعدها فقط: ملخص للمالك مع زمن بدء الطلبات وزمن رد البوت، وإعادة محاولة واحدة لمن طُلب منه الاشتراك.

السحوبات البطيئة (زر رابط بوت + شروط) تُكتشف من نفس المراقبة اللحظية وتُنفَّذ بالمسار القديم
(فاصل 10 ثوانٍ بين الحسابات)، لكن بلا انتظار الفحص الدوري.

النوم واليقظة: حساب واحد فقط (ROULETTE_FAST_HOT=1) متصل دائماً ويراقب كل القنوات. عند ظهور أول سحب سريع تتصل بقية الحسابات
دفعة واحدة وتضغط (قد يتأخر السحب الأول عدة ثوانٍ لأن الحسابات نائمة)، ثم تبقى متصلة فتضغط السحوبات التالية كلها معاً خلال أجزاء من الثانية.
بعد ROULETTE_FAST_IDLE_MINUTES (15) دقيقة بلا سحب سريع تنام كل الحسابات ويبقى المراقب وحده. عنوان القنوات محفوظ مسبقاً لكل حساب.

تنبيه: الحسابات داخل المجمّع محجوزة للروليت ما دام الوضع السريع مفعّلاً (قفل الجلسة بيد المجمّع)،
لذلك لا تستعملها خدمات أخرى في الوقت نفسه. التحكم: زر «⚡ تشغيل/إيقاف السريع» في /roulette.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import random
import re
import time
from typing import Dict, List, Optional, Tuple

from telethon import events, functions
from telethon.tl.types import PeerChannel, ReactionCustomEmoji, ReactionEmoji

from . import roulette_watch as rw

MAX_ACCOUNTS = int(os.environ.get("ROULETTE_FAST_MAX_ACCOUNTS", "50") or 50)  # كل حساب متصل يستهلك ذاكرة
LISTENERS = int(os.environ.get("ROULETTE_FAST_LISTENERS", "1") or 1)
CLICK_TIMEOUT = float(os.environ.get("ROULETTE_FAST_CLICK_TIMEOUT", "8") or 8)
RETRY_CONCURRENCY = 10
MAX_POST_AGE_SECONDS = 90  # نتجاهل تعديلات منشورات قديمة (السحب المفتوح يُعدَّل مع كل منضم)
WARM_BATCH = 5
# طبقتان: «ساخنة» تبقى متصلة دائماً (تضغط خلال ~1.2 ثانية)، و«باردة» غير متصلة تتصل لحظة ظهور الزر (~2.2 ثانية)
HOT_ACCOUNTS = int(os.environ.get("ROULETTE_FAST_HOT", "1") or 1)  # الحساب المراقب فقط يبقى متصلاً دائماً
COLD_TIMEOUT = float(os.environ.get("ROULETTE_FAST_COLD_CONNECT_TIMEOUT", "10") or 10)
IDLE_SECONDS = float(os.environ.get("ROULETTE_FAST_IDLE_MINUTES", "15") or 15) * 60  # بلا سحب سريع هذه المدة: تنام كل الحسابات
TARGET_HOT_MS = 1200.0
TARGET_COLD_MS = 2200.0

_AR_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})


def _norm(text: str) -> str:
    text = re.sub("[\u0640\u064B-\u0652]", "", text or "")
    return text.translate(_AR_MAP).lower()


# زر الانضمام: يجب أن يطابق كلمة انضمام ولا يطابق أي كلمة من القائمة المحظورة
# (انسحب / اسحب فائز / اختيار الفائز / للمسؤول ...) حتى لا يضغط الحساب زر إدارة بالخطأ.
JOIN_WORDS = tuple(_norm(w) for w in ("انضم", "الانضمام", "انضمام", "شارك", "مشاركة", "join", "participate", "enter"))
SKIP_WORDS = tuple(_norm(w) for w in (
    "انسحب", "اسحب", "فائز", "للمسؤول", "winner", "draw", "leave", "withdraw", "quit",
    "stat", "احصائ", "نسخ", "copy", "اعادة النشر", "repost", "رجوع", "back", "cancel",
    "الغاء", "حذف", "delete", "انهاء", "end",
))
NEED_JOIN_WORDS = tuple(_norm(w) for w in (
    "اشترك", "اشتراك", "subscribe", "not a member", "غير مشترك", "انضم للقناة", "join the channel",
))

_REF_BY_ID: Dict[int, str] = {}      # معرف القناة ← المرجع كما أدخله المالك (@name أو -100...)
_seen: Dict[Tuple[int, int], float] = {}
# ── سقف الفاتورة الأسبوعية لليقظة ──
# تقدير داخلي: كلفة الحسابات المستيقظة فوق حساب المراقب (ذاكرة كل حساب متصل × سعر الذاكرة). عند بلوغ السقف
# تنام الحسابات ويصلك إنذار بزر «رفع الحد +1$ وفتح». لا يقيس فاتورة ريلواي الحقيقية، لذلك اضبط
# ROULETTE_FAST_MB_PER_ACCOUNT بعد قياسه من Metrics.
WEEKLY_BUDGET_USD = float(os.environ.get("ROULETTE_FAST_WEEKLY_BUDGET_USD", "1") or 1)
MB_PER_ACCOUNT = float(os.environ.get("ROULETTE_FAST_MB_PER_ACCOUNT", "45") or 45)
GB_MONTH_USD = float(os.environ.get("ROULETTE_FAST_GB_MONTH_USD", "10") or 10)
KEY_BUDGET = "roulette_fast_budget"
_USD_PER_ACCOUNT_SEC = (MB_PER_ACCOUNT / 1024.0) * GB_MONTH_USD / (30 * 86400)
_budget: Optional[Dict] = None
_last_tick = 0.0

_last_fast = 0.0                     # آخر مرة ظهر فيها سحب سريع (time.monotonic)
# ── تفاعل نصف الحسابات مع منشور السحب ──
# عندما تعمل عدة حسابات معاً يتفاعل نصفها (عشوائياً) على المنشور بتفاعل عادي أو مميز (مخصص يُفتح للقنوات المعززة)،
# ولا يُرسَل التفاعل المدفوع بالنجوم أبداً (يُستبعد ReactionPaid والنجمة ⭐ من القائمة قبل أي إرسال).
REACT_ENABLED = os.environ.get("ROULETTE_FAST_REACT", "1") != "0"
REACT_FRACTION = float(os.environ.get("ROULETTE_FAST_REACT_FRACTION", "0.5") or 0.5)
REACT_MIN_ACCOUNTS = int(os.environ.get("ROULETTE_FAST_REACT_MIN_ACCOUNTS", "10") or 10)
REACT_JITTER = float(os.environ.get("ROULETTE_FAST_REACT_JITTER", "2") or 2)  # ثوانٍ عشوائية بين التفاعلات
DEFAULT_REACTIONS = ("👍", "❤", "🔥", "🎉", "😁", "👏")
_REACTIONS_CACHE: Dict[int, Tuple[float, List[str], List[int]]] = {}  # channel_id -> (وقت الجلب، عادية، مخصصة)
# ── إشعار فوز أحد الحسابات ──
# أي منشور/تعديل في القنوات المراقبة فيه كلمة فوز وذكر لأحد حساباتنا (ID أو يوزر أو رابط منشن؛ أو اسم كتطابق ضعيف)
# يرسل للمالك إشعاراً. الهويات تُجلب مرة واحدة عند تجهيز كل حساب (get_me).
WINNER_ALERT = os.environ.get("ROULETTE_FAST_WINNER_ALERT", "1") != "0"
_IDENTITY: Dict[str, Dict] = {}      # بصمة الجلسة -> {id, username, name, phone}
_won_seen: set = set()               # (channel_id, message_id, بصمة الجلسة): إشعار واحد لكل منشور وحساب
_COLD: Dict[str, Dict] = {}          # الحسابات الباردة: {"session", "peers", "refs"} بلا اتصال مفتوح
_keeper_lock = asyncio.Lock()


def _week_id() -> str:
    iso = datetime.datetime.utcnow().isocalendar()
    return f"{iso[0]}-{iso[1]}"


def _budget_state() -> Dict:
    """حالة الأسبوع الحالي (تُحفظ في الإعدادات فلا تضيع مع إعادة تشغيل ريلواي)."""
    global _budget
    if _budget is None:
        try:
            _budget = json.loads(rw.get_setting(KEY_BUDGET) or "{}")
        except Exception:
            _budget = {}
    if _budget.get("week") != _week_id():  # أسبوع جديد: يبدأ العدّاد من الصفر
        _budget = {"week": _week_id(), "spent": 0.0, "extra": 0.0, "blocked": False, "alerted": False}
    return _budget


def _budget_save() -> None:
    try:
        rw.set_setting(KEY_BUDGET, json.dumps(_budget_state()))
    except Exception:
        rw.logger.warning("تعذر حفظ حالة سقف الروليت السريع")


def _budget_limit(b: Dict) -> float:
    return WEEKLY_BUDGET_USD + float(b.get("extra") or 0)


def budget_decision(raise_limit: bool) -> str:
    """يُستدعى من زر الإنذار: رفع الحد 1$ وفتح اليقظة، أو إبقاء الإيقاف."""
    b = _budget_state()
    if raise_limit:
        b["extra"] = float(b.get("extra") or 0) + 1.0
        b["blocked"], b["alerted"] = False, False
        _budget_save()
        return f"✅ رُفع الحد الأسبوعي إلى ${_budget_limit(b):.2f} وفُتحت اليقظة (المستهلك ${b['spent']:.2f})."
    return "👌 بقيت اليقظة موقوفة حتى بداية الأسبوع القادم؛ يبقى حساب المراقبة وحده."


async def _alert_budget(b: Dict) -> None:
    bot = rw._FAST_BOT
    if bot is None:
        return
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    text = (
        f"⚠️ وصلت فاتورة الروليت السريع الأسبوعية إلى ${b['spent']:.2f} من ${_budget_limit(b):.2f}.\n"
        "أُوقفت يقظة الحسابات (يبقى حساب المراقبة وحده). هل ترفع الحد بمقدار 1$ وتفتحها؟"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ رفع الحد +1$ وفتح", callback_data="roulette:budget_raise")],
        [InlineKeyboardButton("إبقاء الإيقاف", callback_data="roulette:budget_keep")],
    ])
    try:
        await bot.send_message(rw.OWNER_ID, text, reply_markup=kb)
    except Exception:
        rw.logger.warning("تعذر إرسال إنذار سقف الروليت السريع")


async def _accrue_and_check() -> None:
    """كل دورة (30 ثانية): يضيف كلفة الحسابات المستيقظة، فإن بلغ السقف يوقف اليقظة ويرسل الإنذار مرة واحدة."""
    global _last_tick
    now = time.monotonic()
    b = _budget_state()
    if _last_tick:
        awake_extra = max(0, len(rw._POOL) - HOT_ACCOUNTS)
        b["spent"] = float(b.get("spent") or 0) + awake_extra * min(now - _last_tick, 120) * _USD_PER_ACCOUNT_SEC
    _last_tick = now
    if not b.get("blocked") and b["spent"] >= _budget_limit(b):
        b["blocked"], b["alerted"] = True, False
    _budget_save()
    if b.get("blocked") and not b.get("alerted"):
        b["alerted"] = True
        _budget_save()
        await _alert_budget(b)


def _awake() -> bool:
    """الحسابات مستيقظة (متصلة) ما دام آخر سحب سريع أحدث من IDLE_SECONDS."""
    if _budget_state().get("blocked"):
        return False
    return _last_fast > 0 and (time.monotonic() - _last_fast) < IDLE_SECONDS


WINNER_WORDS = tuple(_norm(w) for w in ("فائز", "الفائز", "فاز", "فازت", "الفائزين", "الفائزون", "مبروك", "winner", "winners", "won", "congrat", "🏆"))


async def _remember_identity(session: Dict, client) -> None:
    try:
        me = await asyncio.wait_for(client.get_me(), timeout=8)
        full_name = " ".join(x for x in (getattr(me, "first_name", None), getattr(me, "last_name", None)) if x)
        _IDENTITY[rw._session_fp(session)] = {
            "id": me.id, "username": (getattr(me, "username", None) or "").lower(),
            "name": _norm(full_name), "phone": session.get("phone_number"), "display": full_name,
        }
    except Exception as exc:
        rw.logger.debug("تعذر جلب هوية الحساب %s: %s", session.get("phone_number"), exc)


def _mentioned_user_ids(message) -> set:
    ids = set()
    for ent in getattr(message, "entities", None) or []:
        uid = getattr(ent, "user_id", None)
        if uid:
            ids.add(int(uid))
        url = getattr(ent, "url", None) or ""
        for found in re.findall(r"(?:[?&]|^)(?:id|user_id)=(\d+)", url):
            ids.add(int(found))
    return ids


def _post_link(channel_id: int, msg_id: int) -> str:
    ref = _REF_BY_ID.get(channel_id) or ""
    return f"https://t.me/{ref[1:]}/{msg_id}" if ref.startswith("@") else f"https://t.me/c/{channel_id}/{msg_id}"


async def _check_winners(message, channel_id: int) -> None:
    """يُنادى على كل منشور أو تعديل (حتى القديم): السحب قد ينتهي بعد دقائق أو ساعات من نشره."""
    if not WINNER_ALERT or not _IDENTITY:
        return
    text = getattr(message, "raw_text", None) or getattr(message, "message", None) or ""
    low = _norm(text)
    if not text or not any(word in low for word in WINNER_WORDS):
        return
    ids = _mentioned_user_ids(message)
    for key, ident in list(_IDENTITY.items()):
        strong = ident["id"] in ids or (ident["username"] and re.search(rf"@{re.escape(ident['username'])}(?![A-Za-z0-9_])", text, re.I) is not None) \
            or re.search(rf"(?<!\d){ident['id']}(?!\d)", text) is not None
        weak = (not strong) and len(ident["name"]) >= 4 and ident["name"] in low
        if not (strong or weak):
            continue
        marker = (channel_id, message.id, key)
        if marker in _won_seen:
            continue
        _won_seen.add(marker)
        lines = [
            "🏆 فاز أحد حساباتك!" if strong else "🏆 احتمال فوز أحد حساباتك (تطابق اسم فقط — تحقق)",
            f"👤 الحساب: {ident['phone'] or ident['id']}",
            f"🆔 {ident['id']}" + (f" • @{ident['username']}" if ident["username"] else ""),
            f"📢 القناة: {_REF_BY_ID.get(channel_id) or channel_id}",
            f"🔗 {_post_link(channel_id, message.id)}",
            "", text[:300],
        ]
        out = "\n".join(lines)
        rw.logger.info("🏆 %s", out.replace("\n", " | "))
        if rw._FAST_BOT is not None:
            try:
                await rw._FAST_BOT.send_message(rw.OWNER_ID, out)
            except Exception:
                rw.logger.warning("تعذر إرسال إشعار الفوز للمالك")
    if len(_won_seen) > 2000:
        _won_seen.clear()


# ─────────────────────────── كشف المنشور ───────────────────────────

def _find_join_button(message) -> Optional[Tuple[str, bytes]]:
    markup = getattr(message, "reply_markup", None)
    for row in getattr(markup, "rows", None) or []:
        for btn in getattr(row, "buttons", None) or []:
            data = getattr(btn, "data", None)
            if data is None or getattr(btn, "url", None):
                continue
            label = _norm(getattr(btn, "text", "") or "")
            if any(word in label for word in SKIP_WORDS):
                continue
            if any(word in label for word in JOIN_WORDS):
                return str(btn.text), data
    return None


def _is_slow_trigger(message) -> bool:
    try:
        return rw._extract_trigger_base(message) is not None
    except Exception:
        return False


def _channel_id(message) -> Optional[int]:
    return getattr(getattr(message, "peer_id", None), "channel_id", None)


def _message_links(message) -> List[Tuple[str, str]]:
    """روابط t.me داخل نص المنشور وأزرار الروابط (بلا روابط البوتات): قنوات الاشتراك المطلوبة."""
    found: List[Tuple[str, str]] = []
    try:
        for ent, label in message.get_entities_text() or []:
            url = getattr(ent, "url", None) or (label if label.lower().startswith(("http", "t.me")) else None)
            if url:
                found.append((url, label))
    except Exception:
        pass
    markup = getattr(message, "reply_markup", None)
    for row in getattr(markup, "rows", None) or []:
        for btn in getattr(row, "buttons", None) or []:
            url = getattr(btn, "url", None)
            if url:
                found.append((url, str(getattr(btn, "text", "") or "")))
    result, seen_urls = [], set()
    for url, label in found:
        low = url.lower()
        if url in seen_urls or not any(host in low for host in ("t.me/", "telegram.me/")):
            continue
        path = low.split("t.me/")[-1].split("telegram.me/")[-1].split("?")[0].strip("/")
        if path.endswith("bot") and "/" not in path:
            continue
        seen_urls.add(url)
        result.append((url, label))
    return result


# ─────────────────────────── الضغط المتزامن ───────────────────────────

async def _click(entry: Dict, channel_id: int, msg_id: int, data: bytes, t0: float) -> Dict:
    client = entry["client"]
    started = time.monotonic()
    result = {"entry": entry, "status": "fail", "note": "", "start_ms": (started - t0) * 1000, "done_ms": 0.0}
    try:
        peer = entry["peers"].get(channel_id)
        if peer is None:
            peer = await client.get_input_entity(PeerChannel(channel_id))
        answer = await asyncio.wait_for(
            client(functions.messages.GetBotCallbackAnswerRequest(peer=peer, msg_id=msg_id, data=data)),
            timeout=CLICK_TIMEOUT,
        )
        text = (getattr(answer, "message", "") or "").strip()
        low = _norm(text)
        if text and any(word in low for word in NEED_JOIN_WORDS):
            result.update(status="need_join", note=f"طُلب اشتراك: {text[:60]}")
        elif text and any(word in text.lower() for word in rw.FAIL_ANSWER_WORDS):
            result.update(status="fail", note=f"رد الزر: {text[:60]}")
        else:
            result.update(status="ok", note=text[:40])
    except asyncio.TimeoutError:
        # الطلب وصل لتيليجرام لكن البوت لم يجب على الضغطة؛ كثير من بوتات السحب لا تجيب
        result.update(status="unconfirmed", note="بلا رد من البوت")
    except Exception as exc:
        if "BotResponseTimeout" in type(exc).__name__ or "BOT_RESPONSE_TIMEOUT" in str(exc):
            result.update(status="unconfirmed", note="بلا رد من البوت")
        else:
            if rw._is_lost_session_error(exc):
                rw._record_session_failure(entry["session"])
            result.update(status="fail", note=f"{type(exc).__name__}: {str(exc)[:50]}")
    result["done_ms"] = (time.monotonic() - t0) * 1000
    return result


async def _retry_after_join(message, channel_id: int, data: bytes, flagged: List[Dict]) -> List[Dict]:
    """من طُلب منه الاشتراك: ينضم لروابط المنشور ثم يعيد الضغط مرة واحدة."""
    links = _message_links(message)
    if not links:
        return flagged
    semaphore = asyncio.Semaphore(RETRY_CONCURRENCY)

    async def one(res: Dict) -> Dict:
        async with semaphore:
            entry = res["entry"]
            phone = entry["session"].get("phone_number")
            for url, label in links:
                try:
                    await rw._handle_url(entry["client"], url, label, phone)
                except Exception as exc:
                    rw.logger.debug("[%s] انضمام شرط الروليت السريع: %s", phone, exc)
            retry = await _click(entry, channel_id, message.id, data, time.monotonic())
            retry["note"] = "بعد الاشتراك: " + retry["note"]
            retry["tier"] = res.get("tier")
            return retry

    return list(await asyncio.gather(*[one(r) for r in flagged]))


async def _cold_click(info: Dict, channel_id: int, msg_id: int, data: bytes, t0: float, live: List[Dict]) -> Dict:
    """حساب بارد: يتصل الآن (الجلسة وعنوان القناة محفوظان مسبقاً فلا بحث) ثم يضغط مباشرة."""
    session = info["session"]
    started = time.monotonic()
    lock = rw._get_raksh_session_lock(session)
    entry = {"client": None, "session": session}
    fail = {"entry": entry, "status": "fail", "start_ms": (started - t0) * 1000, "done_ms": 0.0, "tier": "cold"}
    if lock.locked():
        fail.update(note="الحساب مستعمل في خدمة أخرى", done_ms=(time.monotonic() - t0) * 1000)
        return fail
    await lock.acquire()
    client = rw._new_client(session)
    entry = {"client": client, "session": session, "peers": info["peers"], "lock": lock}
    fail["entry"] = entry
    live.append(entry)  # يُغلق الاتصال ويُحرَّر القفل في النهاية مهما كانت النتيجة
    try:
        await asyncio.wait_for(client.connect(), timeout=COLD_TIMEOUT)
    except Exception as exc:
        if rw._is_lost_session_error(exc):
            rw._record_session_failure(session)
        fail.update(note=f"تعذر الاتصال: {type(exc).__name__}", done_ms=(time.monotonic() - t0) * 1000)
        return fail
    res = await _click(entry, channel_id, msg_id, data, t0)
    res["start_ms"] = (started - t0) * 1000  # بدء الاتصال لا بدء الضغط
    res["tier"] = "cold"
    return res


async def _release_cold(live: List[Dict]) -> None:
    async def one(entry: Dict) -> None:
        try:
            await entry["client"].disconnect()
        except Exception:
            pass
        try:
            entry["lock"].release()
        except RuntimeError:
            pass

    if live:
        await asyncio.gather(*[one(e) for e in live])


async def _allowed_reactions(entry: Dict, channel_id: int) -> Tuple[List[str], List[int]]:
    """التفاعلات المسموحة في القناة: (إيموجي عادية، معرفات مخصصة/مميزة). بلا أي تفاعل مدفوع."""
    cached = _REACTIONS_CACHE.get(channel_id)
    if cached and time.time() - cached[0] < 3600:
        return cached[1], cached[2]
    regular: List[str] = []
    custom: List[int] = []
    try:
        peer = entry["peers"].get(channel_id)
        full = await asyncio.wait_for(entry["client"](functions.channels.GetFullChannelRequest(channel=peer)), timeout=8)
        available = getattr(getattr(full, "full_chat", None), "available_reactions", None)
        kind = available.__class__.__name__
        if kind == "ChatReactionsSome":
            for reaction in getattr(available, "reactions", None) or []:
                rtype = reaction.__class__.__name__
                if rtype == "ReactionCustomEmoji":
                    custom.append(reaction.document_id)
                elif rtype == "ReactionEmoji" and reaction.emoticon != "⭐":
                    regular.append(reaction.emoticon)
                # ReactionPaid وأي نوع آخر: يُتجاهل
        elif kind == "ChatReactionsAll":
            regular = list(DEFAULT_REACTIONS)
    except Exception as exc:
        rw.logger.debug("تعذر جلب تفاعلات القناة %s: %s", channel_id, exc)
        return [], []
    _REACTIONS_CACHE[channel_id] = (time.time(), regular, custom)
    return regular, custom


async def _react_one(entry: Dict, channel_id: int, msg_id: int, regular: List[str], custom: List[int]) -> str:
    """يعيد: 'regular' أو 'custom' أو 'fail'. المخصص (المميز) يُجرَّب أولاً إن اختير، ثم يُعاد إلى العادي عند رفض الحساب له."""
    await asyncio.sleep(random.uniform(0, REACT_JITTER))
    peer = entry["peers"].get(channel_id)
    client = entry["client"]

    async def send(reaction) -> None:
        await asyncio.wait_for(
            client(functions.messages.SendReactionRequest(peer=peer, msg_id=msg_id, reaction=[reaction])),
            timeout=8,
        )

    use_custom = bool(custom) and (not regular or random.random() < 0.5)
    try:
        if use_custom:
            try:
                await send(ReactionCustomEmoji(document_id=random.choice(custom)))
                return "custom"
            except Exception:
                if not regular:
                    return "fail"  # الحساب بلا Premium ولا تفاعل عادي متاح
        await send(ReactionEmoji(emoticon=random.choice(regular)))
        return "regular"
    except Exception:
        return "fail"


async def _react_half(message, channel_id: int, results: List[Dict]) -> None:
    if not REACT_ENABLED:
        return
    live = [r["entry"] for r in results
            if r["status"] in ("ok", "unconfirmed") and r["entry"].get("client") is not None
            and r["entry"].get("peers", {}).get(channel_id) is not None]
    if len(live) < REACT_MIN_ACCOUNTS:
        return
    regular, custom = await _allowed_reactions(live[0], channel_id)
    if not regular and not custom:
        return  # القناة لا تسمح بتفاعلات
    chosen = random.sample(live, max(1, int(len(live) * REACT_FRACTION)))
    outcomes = await asyncio.gather(*[_react_one(e, channel_id, message.id, regular, custom) for e in chosen])
    text = (
        f"💬 تفاعل {sum(o != 'fail' for o in outcomes)} من {len(chosen)} حساب على المنشور "
        f"(عادي {outcomes.count('regular')} • مميز {outcomes.count('custom')} • فشل {outcomes.count('fail')}) — بلا تفاعل مدفوع"
    )
    rw.logger.info(text)
    if rw._FAST_BOT is not None:
        try:
            await rw._FAST_BOT.send_message(rw.OWNER_ID, text)
        except Exception:
            pass


def _promote(live: List[Dict]) -> int:
    """بعد أول سحب سريع: الحسابات التي اتصلت تبقى متصلة (ساخنة) للسحوبات التالية بدل قطعها."""
    kept = 0
    for entry in list(live):
        client = entry.get("client")
        if client is None or not client.is_connected():
            continue
        key = rw._session_fp(entry["session"])
        info = _COLD.get(key)
        rw._POOL[key] = {
            "client": client, "session": entry["session"], "lock": entry["lock"],
            "peers": entry["peers"], "entities": {}, "refs": set(info["refs"]) if info else set(),
            "listening_on": None,
        }
        live.remove(entry)
        kept += 1
    return kept


async def fire_fast(message, channel_id: int, label: str, data: bytes, received: float) -> None:
    global _last_fast
    _last_fast = time.monotonic()  # يمدّد فترة اليقظة
    hot = list(rw._POOL.values())
    blocked = bool(_budget_state().get("blocked"))
    cold = [] if blocked else [info for key, info in _COLD.items() if key not in rw._POOL]
    if not hot and not cold:
        return
    live: List[Dict] = []
    try:
        # الطبقتان تنطلقان في اللحظة نفسها: المتصلة تضغط فوراً، والنائمة تتصل ثم تضغط
        hot_task = asyncio.gather(*[_click(e, channel_id, message.id, data, received) for e in hot])
        cold_task = asyncio.gather(*[_cold_click(c, channel_id, message.id, data, received, live) for c in cold])
        hot_results, cold_results = await asyncio.gather(hot_task, cold_task)
        for r in hot_results:
            r["tier"] = "hot"
        results = list(hot_results) + list(cold_results)
        first_burst = list(results)
        flagged = [r for r in results if r["status"] == "need_join" and r["entry"].get("client") is not None]
        retried = 0
        if flagged:
            retried = len(flagged)
            retry_results = await _retry_after_join(message, channel_id, data, flagged)
            results = [r for r in results if r not in flagged] + retry_results
        woken = 0 if blocked else _promote(live)
        await _report(channel_id, label, results, retried, first_burst, woken)
        await _react_half(message, channel_id, results)
    finally:
        await _release_cold(live)


async def _report(channel_id: int, label: str, results: List[Dict], retried: int, first_burst: List[Dict], woken: int = 0) -> None:
    ok = sum(1 for r in results if r["status"] == "ok")
    unconfirmed = sum(1 for r in results if r["status"] == "unconfirmed")
    still_need = sum(1 for r in results if r["status"] == "need_join")
    failed = [r for r in results if r["status"] == "fail"]
    starts = sorted(r["start_ms"] for r in first_burst)
    dones = [r["done_ms"] for r in first_burst if r["status"] in ("ok", "unconfirmed")]
    lines = [
        "⚡ روليت سريع",
        f"📢 القناة: {_REF_BY_ID.get(channel_id) or channel_id}",
        f"🔘 الزر: {label}",
        f"👥 الحسابات: {len(results)}",
        f"✅ ضغط وردّ البوت: {ok}",
        f"❔ ضغط بلا رد من البوت: {unconfirmed}",
        f"❌ فشل: {len(failed) + still_need}",
        f"⏱ بدء أول طلب بعد {starts[0]:.0f}ms وآخر طلب بعد {starts[-1]:.0f}ms من وصول المنشور",
    ]
    if dones:
        lines.append(f"⏱ أبطأ ضغطة اكتملت بعد {max(dones):.0f}ms")
    for tier, name, target in (("hot", "🔥 ساخنة", TARGET_HOT_MS), ("cold", "❄️ باردة", TARGET_COLD_MS)):
        group = [r for r in first_burst if r.get("tier") == tier]
        if group:
            times = [r["done_ms"] for r in group if r["status"] in ("ok", "unconfirmed")]
            inside = sum(1 for t in times if t <= target)
            worst = f"{max(times):.0f}ms" if times else "—"
            lines.append(f"{name}: {len(times)}/{len(group)} ضغطت، {inside} خلال {target:.0f}ms، أبطأ {worst}")
    if retried:
        lines.append(f"🔁 أُعيد الضغط بعد الاشتراك لـ {retried} حساب")
    b = _budget_state()
    lines.append(f"💰 كلفة اليقظة هذا الأسبوع (تقديرية): ${b['spent']:.2f} من ${_budget_limit(b):.2f}" + (" — اليقظة موقوفة" if b.get("blocked") else ""))
    if woken:
        lines.append(f"🌅 استيقظ {woken} حساب وبقوا متصلين للسحوبات التالية (ينامون بعد {IDLE_SECONDS / 60:.0f} دقيقة بلا سحب سريع)")
    reasons: Dict[str, int] = {}
    for r in failed:
        reasons[r["note"]] = reasons.get(r["note"], 0) + 1
    if reasons:
        lines.append("\nأسباب الفشل:")
        lines.extend(f"• ({n}) {why}" for why, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:5])
    text = "\n".join(lines)
    rw.logger.info("⚡ %s", text.replace("\n", " | "))
    bot = rw._FAST_BOT
    if bot is not None:
        try:
            await bot.send_message(rw.OWNER_ID, text)
        except Exception:
            rw.logger.warning("تعذر إرسال ملخص الروليت السريع للمالك")


# ─────────────────────────── معالجة الأحداث ───────────────────────────

def _prune_seen(now: float) -> None:
    if len(_seen) > 500:
        for key in [k for k, ts in _seen.items() if now - ts > 600]:
            _seen.pop(key, None)


async def handle_message(message, received: Optional[float] = None) -> None:
    received = received if received is not None else time.monotonic()
    channel_id = _channel_id(message)
    if channel_id is None:
        return
    try:
        await _check_winners(message, channel_id)  # قبل فحص العمر والتكرار: إعلان الفائز يأتي متأخراً أو كتعديل
    except Exception:
        rw.logger.exception("خطأ في فحص الفائزين")
    key = (channel_id, message.id)
    if key in _seen:
        return
    date = getattr(message, "date", None)
    if date is not None and time.time() - date.timestamp() > MAX_POST_AGE_SECONDS:
        return

    if _is_slow_trigger(message):
        trig = rw._extract_trigger(message)
        if not trig:
            return
        _seen[key] = time.time()
        ref = _REF_BY_ID.get(channel_id) or f"-100{channel_id}"
        trig["ref"], trig["msg_id"] = ref, message.id
        rw._handled.add((ref, message.id))
        rw.logger.info("🎰 سحب جديد (مراقبة لحظية) في %s منشور %s عبر @%s", ref, message.id, trig["bot"])
        if rw._FAST_BOT is not None:
            asyncio.create_task(rw._run_roulette(rw._FAST_BOT, trig, rw._owner_sessions()))
        return

    found = _find_join_button(message)
    if not found:
        return
    label, data = found
    _seen[key] = time.time()  # قبل أي await: الحسابان المراقبان قد يصلهما الحدث معاً
    _prune_seen(_seen[key])
    await fire_fast(message, channel_id, label, data, received)


_tasks: set = set()


async def _safe_handle(message, received: float) -> None:
    try:
        await handle_message(message, received)
    except Exception:
        rw.logger.exception("خطأ في معالجة منشور الروليت السريع")


async def _on_event(event) -> None:
    received = time.monotonic()
    task = asyncio.create_task(_safe_handle(event.message, received))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# ─────────────────────────── المجمّع والمراقبة ───────────────────────────

def _attach(entry: Dict) -> None:
    chats = list(entry["entities"].values())
    client = entry["client"]
    client.add_event_handler(_on_event, events.NewMessage(chats=chats))
    client.add_event_handler(_on_event, events.MessageEdited(chats=chats))
    entry["listening_on"] = tuple(sorted(entry["entities"]))


def _detach(entry: Dict) -> None:
    try:
        entry["client"].remove_event_handler(_on_event)
    except Exception:
        pass
    entry["listening_on"] = None


async def _resolve_peers(entry: Dict, refs: List[str]) -> None:
    client = entry["client"]
    for ref in refs:
        if ref in entry["refs"]:
            continue
        try:
            entity = await rw._entity_for(client, ref)
            entry["peers"][entity.id] = await client.get_input_entity(entity)
            entry["entities"][entity.id] = entity
            await asyncio.wait_for(client.get_messages(entity, limit=1), timeout=15)  # يفعّل تحديثات القناة
            entry["refs"].add(ref)
            _REF_BY_ID[entity.id] = ref
        except Exception as exc:
            if rw._is_lost_session_error(exc):
                rw._record_session_failure(entry["session"])
            rw.logger.warning("تعذر تجهيز القناة %s للحساب %s: %s", ref, entry["session"].get("phone_number"), exc)


def _prune_removed(entry: Dict, refs: List[str]) -> None:
    """يحذف من الحساب القنوات التي أزالها المالك من القائمة حتى لا يستمر الضغط فيها."""
    for cid in [c for c in entry["peers"] if _REF_BY_ID.get(c) not in refs]:
        ref = _REF_BY_ID.get(cid)
        entry["entities"].pop(cid, None)
        entry["peers"].pop(cid, None)
        entry["refs"].discard(ref)


async def _warm_account(session: Dict, refs: List[str]) -> Optional[Dict]:
    lock = rw._get_raksh_session_lock(session)
    if lock.locked():
        return None  # الحساب مستعمل في خدمة أخرى الآن؛ نعيد المحاولة في الدورة القادمة
    await lock.acquire()
    client = rw._new_client(session)
    ready = False
    try:
        await asyncio.wait_for(client.connect(), timeout=15)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            rw._record_session_failure(session)
            return None
        rw._record_session_ok(session)
        await _remember_identity(session, client)
        entry = {
            "client": client, "session": session, "lock": lock,
            "peers": {}, "entities": {}, "refs": set(), "listening_on": None,
        }
        await _resolve_peers(entry, refs)
        ready = True
        return entry
    except Exception as exc:
        if rw._is_lost_session_error(exc):
            rw._record_session_failure(session)
        rw.logger.warning("تعذر تجهيز حساب الروليت السريع %s: %s", session.get("phone_number"), exc)
        return None
    finally:
        if not ready:
            try:
                await client.disconnect()
            except Exception:
                pass
            lock.release()


async def _drop(key: str) -> None:
    entry = rw._POOL.pop(key, None)
    if not entry:
        return
    _detach(entry)
    try:
        await entry["client"].disconnect()
    except Exception:
        pass
    try:
        entry["lock"].release()
    except RuntimeError:
        pass


async def shutdown_pool() -> None:
    for key in list(rw._POOL):
        await _drop(key)
    _COLD.clear()
    global _last_fast
    _last_fast = 0.0
    rw._FAST_LISTENING = False


async def _prime_cold(key: str, session: Dict, refs: List[str]) -> None:
    """يتصل بالحساب البارد مرة واحدة ليحفظ عنوان كل قناة (access_hash خاص بكل حساب) ثم يقطع الاتصال."""
    info = _COLD.get(key)
    if info and all(ref in info["refs"] for ref in refs):
        return
    lock = rw._get_raksh_session_lock(session)
    if lock.locked():
        return
    await lock.acquire()
    client = rw._new_client(session)
    try:
        await asyncio.wait_for(client.connect(), timeout=15)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            rw._record_session_failure(session)
            return
        rw._record_session_ok(session)
        await _remember_identity(session, client)
        entry = {
            "client": client, "session": session, "peers": dict(info["peers"]) if info else {},
            "entities": {}, "refs": set(info["refs"]) if info else set(), "listening_on": None,
        }
        await _resolve_peers(entry, refs)
        _COLD[key] = {"session": session, "peers": entry["peers"], "refs": entry["refs"]}
    except Exception as exc:
        if rw._is_lost_session_error(exc):
            rw._record_session_failure(session)
        rw.logger.warning("تعذر تجهيز الحساب البارد %s: %s", session.get("phone_number"), exc)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        lock.release()


async def sync_pool(sessions: List[Dict], refs: List[str]) -> None:
    items = [(rw._session_fp(s), s) for s in sessions[:MAX_ACCOUNTS]]
    for key in [k for k in _IDENTITY if k not in {k2 for k2, _s in items}]:
        _IDENTITY.pop(key, None)
    awake = _awake()
    wanted = dict(items) if awake else dict(items[:HOT_ACCOUNTS])  # مستيقظة: الكل متصل؛ نائمة: المراقب فقط
    cold_wanted = dict(items[HOT_ACCOUNTS:])     # باردة: تتصل عند ظهور الزر فقط
    for key in list(rw._POOL):
        if key not in wanted:
            await _drop(key)
    for key in list(_COLD):
        if key not in cold_wanted:
            _COLD.pop(key, None)  # لم يعد الحساب بارداً أو حُذف
    for info in _COLD.values():
        for cid in [c for c in info["peers"] if _REF_BY_ID.get(c) not in refs]:
            info["refs"].discard(_REF_BY_ID.get(cid))
            info["peers"].pop(cid, None)
    for key, entry in list(rw._POOL.items()):
        if not entry["client"].is_connected():
            try:
                await asyncio.wait_for(entry["client"].connect(), timeout=15)
            except Exception:
                await _drop(key)
                continue
        _prune_removed(entry, refs)
        await _resolve_peers(entry, refs)
    todo = [(k, s) for k, s in wanted.items() if k not in rw._POOL]
    for i in range(0, len(todo), WARM_BATCH):
        batch = todo[i:i + WARM_BATCH]
        warmed = await asyncio.gather(*[_warm_account(s, refs) for _k, s in batch])
        for (key, _s), entry in zip(batch, warmed):
            if entry:
                rw._POOL[key] = entry
        await asyncio.sleep(1)
    cold_todo = [(k, s) for k, s in cold_wanted.items()
                 if k not in rw._POOL and (k not in _COLD or not all(ref in _COLD[k]["refs"] for ref in refs))]
    for i in range(0, len(cold_todo), WARM_BATCH):
        await asyncio.gather(*[_prime_cold(k, s, refs) for k, s in cold_todo[i:i + WARM_BATCH]])
        await asyncio.sleep(1)


def sync_listeners() -> None:
    entries = [e for e in rw._POOL.values() if e["client"].is_connected()]
    for entry in entries:
        if entry["listening_on"] is not None and entry["listening_on"] != tuple(sorted(entry["entities"])):
            _detach(entry)  # تغيّرت القنوات: نعيد الربط
    active = [e for e in entries if e["listening_on"] is not None]
    for entry in entries:
        if len(active) >= LISTENERS:
            break
        if entry["listening_on"] is None and entry["entities"]:
            _attach(entry)
            active.append(entry)
    rw._FAST_LISTENING = bool(active)


async def run_roulette_fast_keeper(context) -> None:
    """مهمة دورية (كل 30 ثانية): تجهّز الحسابات، تعيد الاتصال، وتربط المراقبة اللحظية."""
    rw._FAST_BOT = context.bot
    if _keeper_lock.locked():
        return
    async with _keeper_lock:
        try:
            if not (rw._is_enabled() and rw._fast_enabled()):
                if rw._POOL:
                    await shutdown_pool()
                return
            refs = rw._load_channels()
            sessions = rw._owner_sessions()
            if not refs or not sessions:
                return
            await _accrue_and_check()
            await sync_pool(sessions, refs)
            sync_listeners()
        except Exception:
            rw.logger.exception("فشل مهمة الروليت السريع")
