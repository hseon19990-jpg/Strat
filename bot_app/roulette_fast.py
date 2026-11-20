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

تنبيه: الحسابات داخل المجمّع محجوزة للروليت ما دام الوضع السريع مفعّلاً (قفل الجلسة بيد المجمّع)،
لذلك لا تستعملها خدمات أخرى في الوقت نفسه. التحكم: زر «⚡ تشغيل/إيقاف السريع» في /roulette.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Dict, List, Optional, Tuple

from telethon import events, functions
from telethon.tl.types import PeerChannel

from . import roulette_watch as rw

MAX_ACCOUNTS = int(os.environ.get("ROULETTE_FAST_MAX_ACCOUNTS", "50") or 50)  # كل حساب متصل يستهلك ذاكرة
LISTENERS = int(os.environ.get("ROULETTE_FAST_LISTENERS", "2") or 2)
CLICK_TIMEOUT = float(os.environ.get("ROULETTE_FAST_CLICK_TIMEOUT", "8") or 8)
RETRY_CONCURRENCY = 10
MAX_POST_AGE_SECONDS = 90  # نتجاهل تعديلات منشورات قديمة (السحب المفتوح يُعدَّل مع كل منضم)
WARM_BATCH = 5

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
_keeper_lock = asyncio.Lock()


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
            return retry

    return list(await asyncio.gather(*[one(r) for r in flagged]))


async def fire_fast(message, channel_id: int, label: str, data: bytes, received: float) -> None:
    entries = list(rw._POOL.values())
    if not entries:
        return
    results = await asyncio.gather(
        *[_click(e, channel_id, message.id, data, received) for e in entries]
    )
    first_burst = list(results)
    results = list(results)
    flagged = [r for r in results if r["status"] == "need_join"]
    retried = 0
    if flagged:
        retried = len(flagged)
        retry_results = await _retry_after_join(message, channel_id, data, flagged)
        results = [r for r in results if r["status"] != "need_join"] + retry_results
    await _report(channel_id, label, results, retried, first_burst)


async def _report(channel_id: int, label: str, results: List[Dict], retried: int, first_burst: List[Dict]) -> None:
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
    if retried:
        lines.append(f"🔁 أُعيد الضغط بعد الاشتراك لـ {retried} حساب")
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
    for cid in [c for c in entry["entities"] if _REF_BY_ID.get(c) not in refs]:
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
    rw._FAST_LISTENING = False


async def sync_pool(sessions: List[Dict], refs: List[str]) -> None:
    wanted = {rw._session_fp(s): s for s in sessions[:MAX_ACCOUNTS]}
    for key in list(rw._POOL):
        if key not in wanted:
            await _drop(key)
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
            await sync_pool(sessions, refs)
            sync_listeners()
        except Exception:
            rw.logger.exception("فشل مهمة الروليت السريع")
