"""مراقبة قنوات الروليت والمشاركة التلقائية بحسابات المالك فقط.

الفكرة:
1. المالك يضيف قنوات من /roulette.
2. مهمة دورية تراقب هذه القنوات بحساب مالك واحد (ينضم لها أولاً).
3. عند ظهور منشور سحب (زر رابط بوت فيه start مثل «المشاركة في السحب»)
   تبدأ كل حسابات المالك معاً: تنضم لقناة المنشور، تفتح البوت، ثم تنفذ
   الشروط الظاهرة (انضمام لقناة، تعليق على منشور) وتضغط زر التحقق.
4. يصل المالك ملخص بالنتيجة مع آخر رسالة من البوت لكل فشل، لتسهيل الضبط.

الحسابات المستخدمة: الحسابات المضافة بواسطة المالك فقط (contributed_by=OWNER_ID).
شروط التصويت لمتسابق غير مدعومة بعد؛ تُسجَّل وتُبلَّغ للمالك.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
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

PARTICIPATE_WORDS = ("المشاركة في السحب", "مشاركة السحب", "شارك في السحب", "participate", "giveaway")
VERIFY_WORDS = ("تحقق", "تأكيد", "check", "verify", "confirm", "تم", "انتهيت", "done", "شارك", "مشاركة")
BACK_WORDS = ("رجوع", "back", "استبعاد", "إلغاء", "الغاء", "cancel", "تخطي", "skip")
SUCCESS_WORDS = (
    "تم تسجيلك", "تمت مشاركتك", "تمت المشاركة", "تم المشاركة", "تم الاشتراك في السحب",
    "أنت مشارك", "انت مشارك", "مشارك بالفعل", "you are participating", "successfully registered",
    "تم تسجيل مشاركتك",
)
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
    """حسابات المالك حصراً: المضافة بواسطته."""
    sessions = _get_sessions_for_service("roulette", is_owner=True, contributor_id=int(OWNER_ID))
    return [s for s in sessions if str(s.get("session_string") or "").strip()]


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


def _extract_trigger(message) -> Optional[Dict]:
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
        await _join_channel_and_schedule_leave(client, f"invite:{invite}", phone)
        return True, "انضمام بدعوة"

    # بوت: ليس شرطاً ننفذه
    if len(parts) == 1 and parts[0].lower().endswith("bot"):
        return False, "رابط بوت"

    # قناة عامة
    if len(parts) == 1:
        await _join_channel_and_schedule_leave(client, f"@{parts[0]}", phone)
        return True, "انضمام لقناة"

    # رابط منشور
    ref, msg_id = _parse_post_link(url)
    if not ref or not msg_id:
        return False, "رابط منشور غير مفهوم"
    if "تصويت" in lowered_label or "vote" in lowered_label or "متسابق" in lowered_label:
        return False, "شرط تصويت غير مدعوم بعد"
    await _join_channel_and_schedule_leave(client, ref, phone)
    entity = await _entity_for(client, ref)
    if "comment" in query or "تعليق" in lowered_label or "comment" in lowered_label:
        await _join_discussion_and_comment(client, entity, msg_id, random.choice(_comment_texts()))
        return True, "تعليق"
    return True, "فتح المنشور"


async def _participate(session: Dict, trig: Dict, semaphore: asyncio.Semaphore) -> Tuple[bool, str]:
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
            await _join_channel_and_schedule_leave(client, trig["ref"], phone)

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
    results = await asyncio.gather(
        *[_participate(session, trig, semaphore) for session in sessions],
        return_exceptions=True,
    )
    ok = 0
    failures: Dict[str, int] = {}
    for result in results:
        if isinstance(result, BaseException):
            reason = f"خطأ: {str(result)[:80]}"
            failures[reason] = failures.get(reason, 0) + 1
            continue
        success, note = result
        if success:
            ok += 1
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
                        last = info.get("last")
                        info["last"] = newest
                        if last is None:
                            continue  # أول مرة: لا نعالج المنشورات القديمة
                        for message in sorted((m for m in messages if m.id > last), key=lambda m: m.id):
                            key = (ref, message.id)
                            if key in _handled:
                                continue
                            trig = _extract_trigger(message)
                            if trig:
                                _handled.add(key)
                                trig["ref"] = ref
                                trig["msg_id"] = message.id
                                triggers.append(trig)
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
        _save_channels(_load_channels() + refs)
        context.user_data.pop("roulette_step", None)
        await update.message.reply_text(
            f"✅ أُضيفت {len(refs)} قناة. سينضم لها حساب المراقبة تلقائياً خلال لحظات.",
            reply_markup=_panel_kb(),
        )
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
