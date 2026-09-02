"""
نظام الرشق المتقدم - منفصل تماماً عن بقية البوت
✅ كل خدمة رشق في مكان واحد (الخدمة + معالجها + طريقة عملها)
✅ تعديل أي خدمة = تعديل كلاس واحد فقط
"""

from ..shared import *
from ..accounts import get_forced_ref_account_count
from ..database import db_conn
from ..security import add_points, deduct_points, get_user, is_user_banned
from ..services import get_raksh_accounts_label, md_escape
from ..users import get_setting, set_setting
from ..ui import main_menu_kb
from telethon import TelegramClient, functions
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.functions.messages import (
    ImportChatInviteRequest, 
    SendVoteRequest, 
    StartBotRequest,
    SendMessageRequest,
    SendMediaRequest
)
from telethon.tl.functions.contacts import ResolveUsernameRequest
from telethon.tl.functions.stories import IncrementStoryViewsRequest, SendReactionRequest
from telethon.tl.types import ReactionEmoji, InputMediaContact
from urllib.parse import parse_qs, urlparse
import random
import asyncio
import re
import time
from typing import Optional, List, Dict, Tuple, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

# ════════════════════════════════════════════════════════
# ═══ 1. الثوابت العامة ═══
# ════════════════════════════════════════════════════════

RAKSH_PAID_REACTION = "__raksh_paid_reaction__"
RAKSH_PAID_REACTION_LABEL = "⭐ تفاعل مدفوع"
RAKSH_CUSTOM_REACTION_PREFIX = "__raksh_custom_reaction__:"
RAKSH_REACTION_LOOKUP_MAX_SESSIONS = 3
RAKSH_REACTION_LOOKUP_TIMEOUT_SECONDS = 5
RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS = 4
RAKSH_MIN_DELAY_SECONDS = 60
RAKSH_MAX_DELAY_SECONDS = 180
RAKSH_VOTE_DELAY_SECONDS = 3
RAKSH_MAX_EXECUTIONS_PER_DAY = 1000
RAKSH_MAX_EXECUTIONS_PER_HOUR = 100
RAKSH_NO_VERIFICATION_MESSAGE = "بدون زر تحقق"

# ════════════════════════════════════════════════════════
# ═══ 2. إدارة الجلسات والذاكرة ═══
# ════════════════════════════════════════════════════════

_RAKSH_SESSION_LOCKS: Dict[str, asyncio.Lock] = {}
_RAKSH_VOTE_FLOW_LOCK = asyncio.Lock()
_RAKSH_SESSION_CACHE: Dict[str, Dict] = {}
_RAKSH_SESSION_CACHE_TIME: Dict[str, float] = {}
_RAKSH_SESSION_CACHE_TTL = 60

def _get_raksh_session_lock(phone_number: str) -> asyncio.Lock:
    """الحصول على قفل جلسة مع إدارة الذاكرة"""
    key = str(phone_number or "").strip()
    if key not in _RAKSH_SESSION_LOCKS:
        _RAKSH_SESSION_LOCKS[key] = asyncio.Lock()
    return _RAKSH_SESSION_LOCKS[key]

def _positive_setting(key: str, fallback: int) -> int:
    """قراءة إعداد مع التحقق من الصحة"""
    try:
        value = int(get_setting(key) or fallback)
        return max(1, value) if value > 0 else fallback
    except (TypeError, ValueError):
        return fallback

def _clear_raksh_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """تنظيف حالة المستخدم بشكل آمن"""
    keys_to_clear = [
        "raksh_service",
        "raksh_step",
        "raksh_channels",
        "raksh_link",
        "raksh_reaction",
        "raksh_available_reactions",
        "raksh_comment",
        "raksh_poll_option",
        "raksh_delay_seconds",
        "raksh_quantity",
        "raksh_payment_method",
        "raksh_price_edit_service",
        "raksh_temp_data",
    ]
    for key in keys_to_clear:
        context.user_data.pop(key, None)
    context.user_data["state"] = "main_menu"

def _get_sessions_for_service(service_type: str) -> List[Dict]:
    """جلب الجلسات المناسبة لنوع الخدمة مع التخزين المؤقت"""
    cache_key = f"sessions_{service_type}"
    if cache_key in _RAKSH_SESSION_CACHE:
        cache_time = _RAKSH_SESSION_CACHE_TIME.get(cache_key, 0)
        if time.time() - cache_time < _RAKSH_SESSION_CACHE_TTL:
            return _RAKSH_SESSION_CACHE[cache_key].copy()
    
    with db_conn() as c:
        query = """
            SELECT id, phone_number, session_string, raksh_only, last_authorized
            FROM number_stock
            WHERE session_string IS NOT NULL
              AND BTRIM(session_string) <> ''
              AND deleted_at IS NULL
              AND forced_ref_excluded IS NOT TRUE
            ORDER BY last_authorized DESC NULLS LAST, id ASC
        """
        rows = c.execute(query).fetchall()
        sessions = [dict(row) for row in rows]
        
        _RAKSH_SESSION_CACHE[cache_key] = sessions
        _RAKSH_SESSION_CACHE_TIME[cache_key] = time.time()
        
        return sessions

def get_available_sessions_count(service_type: str = None) -> int:
    """عدد الجلسات المتاحة للخدمة"""
    if service_type:
        return len(_get_sessions_for_service(service_type))
    return len(_get_sessions_for_service("story"))

def _mark_raksh_session_unauthorized(phone_number: str) -> None:
    """تعليم جلسة غير مصرح بها"""
    if not phone_number:
        return
    try:
        with db_conn() as c:
            c.execute(
                "UPDATE number_stock SET last_authorized=FALSE "
                "WHERE phone_number=%s AND deleted_at IS NULL",
                (phone_number,)
            )
        logger.warning(f"🔒 جلسة غير مصرح بها: {phone_number}")
        _RAKSH_SESSION_CACHE.clear()
        _RAKSH_SESSION_CACHE_TIME.clear()
    except Exception as exc:
        logger.warning(f"تعذر تحديث حالة الجلسة {phone_number}: {exc}")

async def _remove_invalid_raksh_sessions(failed_phones: List[str]) -> None:
    """إزالة الجلسات غير الصالحة"""
    if not failed_phones:
        return
    
    removed = 0
    for phone in failed_phones:
        try:
            with db_conn() as c:
                row = c.execute(
                    "SELECT session_string, id FROM number_stock WHERE phone_number=%s",
                    (phone,)
                ).fetchone()
                if row and not row["session_string"]:
                    c.execute(
                        "UPDATE number_stock SET forced_ref_excluded=TRUE WHERE id=%s",
                        (row["id"],)
                    )
                    removed += 1
                    logger.info(f"🗑️ إزالة {phone} من الرشق")
        except Exception as e:
            logger.warning(f"فشل إزالة {phone}: {e}")
    
    if removed:
        _RAKSH_SESSION_CACHE.clear()
        _RAKSH_SESSION_CACHE_TIME.clear()
        
        if OWNER_ID:
            try:
                await bot.send_message(
                    OWNER_ID,
                    f"🧹 تمت إزالة {removed} حساب غير صالح من الرشق"
                )
            except Exception:
                pass

# ════════════════════════════════════════════════════════
# ═══ 3. أدوات تحليل الروابط ═══
# ════════════════════════════════════════════════════════

def _parse_story_link(value: str) -> Tuple[Optional[str], Optional[int]]:
    """تحليل روابط الستوري"""
    value = (value or "").strip().strip("<>")
    try:
        parsed = urlparse(value if "://" in value else f"https://{value}")
        if parsed.netloc.lower() not in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}:
            return None, None
        
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) == 3 and parts[1] in {"s", "story"} and parts[2].isdigit():
            return f"@{parts[0].lstrip('@')}", int(parts[2])
        if (
            len(parts) == 4
            and parts[0] == "c"
            and parts[1].isdigit()
            and parts[2] in {"s", "story"}
            and parts[3].isdigit()
        ):
            return f"-100{parts[1]}", int(parts[3])
    except Exception:
        pass
    return None, None

def _parse_post_link(value: str) -> Tuple[Optional[str], Optional[int]]:
    """تحليل رابط منشور"""
    value = (value or "").strip().strip("<>")
    if not value.startswith("http"):
        value = "https://" + value
    
    try:
        parsed = urlparse(value)
        netloc = parsed.netloc.lower().replace("www.", "")
        if netloc not in {"t.me", "telegram.me"}:
            return None, None
        
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if parts and parts[0] == "s":
            parts = parts[1:]
        
        if len(parts) < 2 or len(parts) > 3 or not parts[-1].isdigit():
            return None, None
        
        if parts[0] == "c":
            if len(parts) != 3 or not parts[1].isdigit():
                return None, None
            return f"-100{parts[1]}", int(parts[2])
        
        if len(parts) != 2:
            return None, None
        return f"@{parts[0].lstrip('@')}", int(parts[1])
    except Exception:
        return None, None

def _parse_bot_link(value: str) -> Tuple[Optional[str], Optional[str]]:
    """تحليل رابط بوت"""
    value = (value or "").strip()
    if not value:
        return None, None
    
    try:
        if "t.me/" in value or "telegram.me/" in value:
            parsed = urlparse(value if "://" in value else f"https://{value}")
            path = parsed.path.strip("/")
            if path:
                bot_username = path.split("/")[0]
                query = parse_qs(parsed.query)
                start_param = (
                    query.get("start", [""])[0]
                    or query.get("startapp", [""])[0]
                    or query.get("startgroup", [""])[0]
                )
                return bot_username, start_param
        else:
            parts = value.split()
            if parts:
                bot_username = parts[0].lstrip("@")
                start_param = parts[1] if len(parts) > 1 else ""
                return bot_username, start_param
    except Exception:
        pass
    return None, None

def _parse_channel_refs(value: str) -> List[str]:
    """تحويل المدخلات إلى مراجع قنوات"""
    refs = []
    if not value:
        return refs
    
    tokens = re.split(r"[\s,،\n]+", value.strip())
    for token in tokens:
        if not token:
            continue
        token = token.strip("<>")
        try:
            if token.startswith("@"):
                refs.append(token)
            elif "t.me/" in token or "telegram.me/" in token:
                parsed = urlparse(token if "://" in token else f"https://{token}")
                path = parsed.path.strip("/")
                if path.startswith(("joinchat/", "+")):
                    token = path.removeprefix("joinchat/").removeprefix("+")
                    refs.append(f"invite:{token}")
                elif path:
                    parts = [p for p in path.split("/") if p]
                    if len(parts) >= 2 and parts[0] == "c" and parts[1].isdigit():
                        refs.append(f"-100{parts[1]}")
                    elif parts[0] not in {"c", "joinchat"}:
                        refs.append(f"@{parts[0].lstrip('@')}")
        except Exception:
            continue
    
    return list(dict.fromkeys(refs))

# ════════════════════════════════════════════════════════
# ═══ 4. أدوات التفاعل ═══
# ════════════════════════════════════════════════════════

RAKSH_REACTIONS = {
    "heart": "❤️",
    "fire": "🔥",
    "like": "👍",
    "love": "😍",
    "starstruck": "🤩",
    "sparkles": "✨",
    "hundred": "💯",
    "clap": "👏",
    "thumbsup": "👍",
    "thumbsdown": "👎",
    "laugh": "😂",
    "wow": "😮",
    "sad": "😢",
    "angry": "😡",
}

def _reaction_emoticons(reactions) -> List[str]:
    """تحويل التفاعلات إلى قائمة إيموجيات"""
    result = []
    if not reactions:
        return result
    
    for reaction in reactions:
        try:
            reaction_type = reaction.__class__.__name__
            if reaction_type == "ReactionPaid":
                if RAKSH_PAID_REACTION not in result:
                    result.append(RAKSH_PAID_REACTION)
            elif reaction_type == "ReactionCustomEmoji":
                document_id = getattr(reaction, "document_id", None)
                if document_id is not None:
                    custom_key = f"{RAKSH_CUSTOM_REACTION_PREFIX}{document_id}"
                    if custom_key not in result:
                        result.append(custom_key)
            else:
                emoticon = getattr(reaction, "emoticon", None)
                if emoticon and emoticon not in result:
                    result.append(emoticon)
        except Exception:
            continue
    return result

def _custom_reaction_document_id(value: str) -> Optional[int]:
    """استخراج معرف الإيموجي المخصص"""
    if not isinstance(value, str) or not value.startswith(RAKSH_CUSTOM_REACTION_PREFIX):
        return None
    raw_id = value[len(RAKSH_CUSTOM_REACTION_PREFIX):]
    return int(raw_id) if raw_id.isdigit() else None

async def _fetch_raksh_reactions(session: Dict, post_ref: str, post_id: int) -> List[str]:
    """جلب التفاعلات المتاحة من جلسة واحدة"""
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    try:
        await asyncio.wait_for(client.connect(), timeout=RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS):
            return []
        
        post_entity = await asyncio.wait_for(client.get_entity(post_ref), timeout=RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS)
        message = await asyncio.wait_for(client.get_messages(post_entity, ids=post_id), timeout=RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS)
        if isinstance(message, (list, tuple)):
            message = message[0] if message else None
        
        if message:
            message_reactions = getattr(getattr(message, "reactions", None), "results", [])
            reactions = _reaction_emoticons(getattr(item, "reaction", None) for item in message_reactions)
            if reactions:
                return reactions
        
        full_channel = await asyncio.wait_for(client(functions.channels.GetFullChannelRequest(channel=post_entity)), timeout=RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS)
        full_chat = getattr(full_channel, "full_chat", None)
        
        if getattr(full_chat, "paid_reactions_available", False):
            return [RAKSH_PAID_REACTION]
        
        available = getattr(full_chat, "available_reactions", None)
        configured = getattr(available, "reactions", None)
        reactions = _reaction_emoticons(configured)
        if reactions:
            return reactions
        
        if available is not None and available.__class__.__name__ == "ChatReactionsAll":
            return list(RAKSH_REACTIONS.values())
        
        return []
    except Exception as e:
        logger.warning(f"تعذر جلب التفاعلات: {e}")
        return []
    finally:
        await client.disconnect()

async def _fetch_raksh_reactions_from_pool(sessions: List[Dict], post_ref: str, post_id: int) -> List[str]:
    """جلب التفاعلات من مجموعة جلسات"""
    if not sessions:
        return []
    
    max_samples = min(RAKSH_REACTION_LOOKUP_MAX_SESSIONS, len(sessions))
    candidates = random.sample(sessions, max_samples) if max_samples > 0 else []
    
    async def lookup(session: Dict) -> List[str]:
        try:
            return await asyncio.wait_for(_fetch_raksh_reactions(session, post_ref, post_id), timeout=RAKSH_REACTION_LOOKUP_TIMEOUT_SECONDS)
        except Exception:
            return []
    
    tasks = [asyncio.create_task(lookup(session)) for session in candidates]
    try:
        for completed in asyncio.as_completed(tasks):
            try:
                reactions = await completed
                if reactions:
                    return reactions
            except Exception:
                continue
        return []
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

# ════════════════════════════════════════════════════════
# ═══ 5. دوال استخراج الكود من النص ═══
# ════════════════════════════════════════════════════════

def _extract_code_from_text(text: str) -> Optional[str]:
    """استخراج الكود المطلوب من النص"""
    if not text:
        return None
    
    if text.strip().startswith("/"):
        return None
    if text.strip().lower() in {"start", "/start", "بدء"}:
        return None
    
    common_words = {
        "الآن", "أرسل", "النص", "التالي", "المرحلة", "الأولى", "بالضبط", "اكتب", "retype", 
        "type", "أدخل", "enter", "التحقق", "رابط", "الإحالة", "start", "ref", "https", "t.me",
        "مرحباً", "يجب", "إكمال", "المتابعة", "حل", "العملية", "الحسابية", "مشاركة", "جهة",
        "اتصال", "هاتف", "رقم", "الموبايل", "mobile", "phone", "contact", "share"
    }
    
    patterns = [
        r'(?:الآن\s*أرسل\s*النص\s*التالي|المرحلة\s*الأولى:\s*أرسل\s*النص\s*التالي\s*بالضبط|أرسل\s*النص\s*التالي|اكتب|retype|type|أدخل|enter)\s*[:\-]?\s*([A-Za-z0-9]{3,50})',
        r'النص\s*التالي\s*[:\-]?\s*([A-Za-z0-9]{3,50})',
        r'([A-Za-z0-9]{3,50})\s*$',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            code = match.group(1).strip()
            if code and len(code) >= 3 and code not in common_words:
                return code
    
    words = re.findall(r'\b[A-Za-z0-9]{3,50}\b', text)
    if words:
        filtered = [w for w in words if w not in common_words]
        if filtered:
            return filtered[-1]
        else:
            return words[-1]
    
    quote_match = re.search(r'["\']([A-Za-z0-9]{3,50})["\']', text)
    if quote_match:
        return quote_match.group(1).strip()
    
    lines = text.splitlines()
    for line in lines:
        line = line.strip()
        if 3 <= len(line) <= 50 and re.match(r'^[A-Za-z0-9]+$', line):
            if line not in common_words:
                return line
    
    raw_matches = re.findall(r'[A-Za-z0-9]{3,50}', text)
    if raw_matches:
        filtered = [m for m in raw_matches if m not in common_words]
        if filtered:
            return filtered[-1]
        else:
            return raw_matches[-1]
    
    return None

async def _solve_forced_ref_verification(client, bot_entity, phone_number: str) -> bool:
    """حل التحقق المضمون"""
    max_attempts = 20
    base_id = 0

    try:
        out_messages = await client.get_messages(bot_entity, limit=10)
        for msg in out_messages:
            if msg.out:
                base_id = msg.id
                logger.info(f"🔑 نقطة البداية هي رسالة الحساب رقم: {base_id}")
                break
    except Exception as e:
        logger.warning(f"تعذر تحديد الرسالة المرجعية: {e}")

    for attempt in range(max_attempts):
        try:
            messages = await client.get_messages(bot_entity, limit=20)
        except Exception as exc:
            await asyncio.sleep(1.0)
            continue
        
        incoming_messages = [msg for msg in messages if not msg.out]
        incoming_messages.sort(key=lambda m: m.id)
        
        new_messages = [msg for msg in incoming_messages if msg.id > base_id]
        
        if not new_messages:
            await asyncio.sleep(1.0)
            continue
        
        verification_message = None
        for msg in new_messages:
            msg_text = getattr(msg, 'message', '') or ''
            if msg_text.strip().startswith("/"):
                continue
            if any(kw in msg_text for kw in ["أرسل", "التالي", "بالضبط", "اكتب", "retype", "type", "اضغط", "اختر", "انقر"]):
                verification_message = msg
                break
        
        if verification_message is None:
            verification_message = next(
                (msg for msg in reversed(new_messages) if not getattr(msg, 'message', '').strip().startswith("/")), 
                None
            )
        
        if verification_message is None:
            await asyncio.sleep(1.0)
            continue
        
        text = getattr(verification_message, 'message', '') or ''
        
        send_text = _extract_code_from_text(text)
        if send_text:
            try:
                await client.send_message(bot_entity, send_text)
                logger.info(f"✅ تم إرسال الكود: {send_text}")
                return True
            except Exception:
                return False
        
        math_patterns = [
            (r'(\d+)\s*([+\-*/])\s*(\d+)\s*=\s*\?', 1, 2, 3),
            (r'(\d+)\s*([+\-*/])\s*(\d+)\s*=', 1, 2, 3),
            (r'(\d+)\s*\+\s*(\d+)\s*=', 1, 2),
            (r'(\d+)\s*\-\s*(\d+)\s*=', 1, 2),
            (r'(\d+)\s*\*\s*(\d+)\s*=', 1, 2),
            (r'(\d+)\s*\/\s*(\d+)\s*=', 1, 2),
        ]
        for pattern, *groups in math_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    if len(groups) == 3:
                        a, op, b = int(match.group(groups[0])), match.group(groups[1]), int(match.group(groups[2]))
                    else:
                        a, b = int(match.group(groups[0])), int(match.group(groups[1]))
                        op = '+'
                    
                    if op == '+': result = str(a + b)
                    elif op == '-': result = str(a - b)
                    elif op == '*': result = str(a * b)
                    elif op == '/': result = str(a / b) if b != 0 else None
                    else: result = None
                    
                    if result is not None:
                        await client.send_message(bot_entity, result)
                        logger.info(f"✅ تم حل المسألة: {a} {op} {b} = {result}")
                        return True
                except Exception:
                    continue
        
        buttons = []
        for row in getattr(verification_message, 'buttons', None) or []:
            for btn in row:
                if not getattr(btn, 'url', None):
                    buttons.append(btn)
        
        if buttons:
            for btn in buttons:
                btn_text = (getattr(btn, 'text', '') or '').lower()
                try:
                    await btn.click()
                    logger.info(f"✅ تم الضغط على الزر: {getattr(btn, 'text', '')}")
                    return True
                except Exception:
                    continue
        
        await asyncio.sleep(2.0)
    
    return False

async def _join_channel_and_schedule_leave(client, channel_ref: str):
    """الانضمام للقناة وجدولة المغادرة"""
    try:
        if channel_ref.startswith("invite:"):
            invite_hash = channel_ref[7:]
            await client(ImportChatInviteRequest(invite_hash))
        else:
            entity = await client.get_entity(channel_ref)
            await client(JoinChannelRequest(entity))
        
        async def _leave_later():
            await asyncio.sleep(random.randint(600, 1800))
            try:
                if channel_ref.startswith("invite:"):
                    pass
                else:
                    entity = await client.get_entity(channel_ref)
                    await client(LeaveChannelRequest(entity))
            except Exception:
                pass
        
        asyncio.create_task(_leave_later())
    except Exception as e:
        logger.warning(f"تعذر الانضمام للقناة {channel_ref}: {e}")

def _find_bot_start_link(message) -> Tuple[Optional[str], Optional[str]]:
    """استخراج رابط البوت من أزرار المنشور"""
    for row in getattr(message, "buttons", None) or []:
        for btn in row:
            url = getattr(btn, "url", None)
            if url and ("t.me/" in url or "telegram.me/" in url):
                bot_username, start_param = _parse_bot_link(url)
                if bot_username and start_param:
                    return bot_username, start_param
    return None, None

def _normalize_digits(value: str) -> str:
    """توحيد الأرقام"""
    return (value or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))

def _select_poll_option(options, requested: str):
    """اختيار خيار الاستفتاء"""
    requested = (requested or "").strip()
    normalized = _normalize_digits(requested)
    if normalized.isdigit():
        index = int(normalized) - 1
        return options[index] if 0 <= index < len(options) else None
    
    requested_folded = requested.casefold()
    return next(
        (
            option
            for option in options
            if str(getattr(option, "text", "")).strip().casefold() == requested_folded
        ),
        None,
    )

async def _send_vote_and_check(client, peer, msg_id: int, option) -> bool:
    """إرسال تصويت والتحقق منه"""
    await client(SendVoteRequest(peer=peer, msg_id=msg_id, options=[option]))
    
    for delay in (0.0, 0.3, 0.5):
        if delay:
            await asyncio.sleep(delay)
        refreshed = await client.get_messages(peer, ids=msg_id)
        if not refreshed:
            continue
        refreshed_message = refreshed[0] if isinstance(refreshed, (list, tuple)) else refreshed
        poll_media = getattr(refreshed_message, "poll", None)
        results = getattr(poll_media, "results", None)
        result_items = getattr(results, "results", None) or []
        if any(
            getattr(result, "chosen", False)
            for result in result_items
        ):
            return True
    return False

# ════════════════════════════════════════════════════════
# ═══ 6. ServiceConfig ═══
# ════════════════════════════════════════════════════════

@dataclass
class ServiceConfig:
    name: str
    price_points: int
    points_quantity: int
    price_stars: int
    stars_quantity: int
    has_channel: bool
    has_reaction: bool
    has_ai: bool
    needs_link: bool
    min_delay: int = 60
    max_delay: int = 180
    max_concurrent: int = 1

# ════════════════════════════════════════════════════════
# ═══ 7. RakshService - الفئة الأساسية ═══
# ════════════════════════════════════════════════════════

class RakshService:
    """الفئة الأساسية - كل منطق الخدمة في مكان واحد"""
    
    service_type: str = ""
    config: ServiceConfig = None
    label: str = ""
    
    def __init__(self):
        if not self.service_type or not self.config:
            raise ValueError("يجب تحديد service_type و config")
    
    # ─── الإعدادات ───
    
    def get_price_keys(self) -> Dict[str, str]:
        return {
            "points_price": f"raksh_{self.service_type}_points_price",
            "points_quantity": f"raksh_{self.service_type}_points_quantity",
            "stars_price": f"raksh_{self.service_type}_stars_price",
            "stars_quantity": f"raksh_{self.service_type}_stars_quantity",
        }
    
    def get_price_config(self) -> Dict[str, int]:
        keys = self.get_price_keys()
        return {
            "points_price": _positive_setting(keys["points_price"], self.config.price_points),
            "points_quantity": _positive_setting(keys["points_quantity"], self.config.points_quantity),
            "stars_price": _positive_setting(keys["stars_price"], self.config.price_stars),
            "stars_quantity": _positive_setting(keys["stars_quantity"], self.config.stars_quantity),
        }
    
    def get_total(self, quantity: int, payment_method: str) -> int:
        if quantity <= 0:
            return 0
        config = self.get_price_config()
        price_key = "stars_price" if payment_method == "stars" else "points_price"
        quantity_key = "stars_quantity" if payment_method == "stars" else "points_quantity"
        price = config[price_key]
        bundle_quantity = config[quantity_key]
        return ((quantity + bundle_quantity - 1) // bundle_quantity) * price
    
    def get_rate_text(self, payment_method: str) -> str:
        config = self.get_price_config()
        if payment_method == "stars":
            return f"{config['stars_price']} نجمة لكل {config['stars_quantity']}"
        return f"{config['points_price']} نقطة لكل {config['points_quantity']}"
    
    def is_enabled(self) -> bool:
        return get_setting(f"raksh_service_enabled_{self.service_type}").strip().lower() not in {
            "0", "false", "off", "hidden", "disabled"
        }
    
    def set_enabled(self, enabled: bool) -> None:
        set_setting(f"raksh_service_enabled_{self.service_type}", "1" if enabled else "0")
    
    # ─── الرابط ───
    
    def get_link_instruction(self) -> str:
        return "أرسل الرابط المطلوب"
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        return None
    
    # ─── الجلسات ───
    
    def get_sessions(self) -> List[Dict]:
        return _get_sessions_for_service(self.service_type)
    
    def get_max_quantity(self) -> int:
        return len(self.get_sessions())
    
    def get_request_limit(self, user_id: int) -> int:
        return min(
            self.get_max_quantity(),
            get_raksh_hourly_remaining(user_id),
            get_raksh_daily_remaining(user_id),
        )
    
    # ─── التنفيذ ───
    
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        raise NotImplementedError(f"يجب تنفيذ execute في {self.__class__.__name__}")
    
    # ─── تدفق المستخدم ───
    
    def get_initial_state(self) -> str:
        return "link"
    
    def get_start_message(self) -> str:
        return (
            f"{self.config.name}\n\n"
            f"💰 السعر: {self.get_rate_text('points')}\n"
            f"⭐ السعر: {self.get_rate_text('stars')}\n\n"
            f"🔗 *أرسل الرابط المطلوب:*\n"
            f"{self.get_link_instruction()}"
        )
    
    def get_start_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
        ])
    
    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        """معالجة النص - يجب تجاوزها في الخدمات"""
        return False
    
    async def handle_callback(self, update, context, query, data_parts, user, is_own) -> bool:
        """معالجة الأزرار - يجب تجاوزها في الخدمات"""
        return False
    
    # ─── أدوات ───
    
    def get_delay_seconds(self, custom_delay: Optional[int] = None) -> int:
        if custom_delay is not None:
            return max(0, min(custom_delay, 86400))
        if self.config.min_delay == self.config.max_delay:
            return self.config.min_delay
        return random.randint(self.config.min_delay, self.config.max_delay)
    
    def get_execution_params(self, context) -> Dict:
        return {
            "channel_ref": context.user_data.get("raksh_channels"),
            "reaction": context.user_data.get("raksh_reaction"),
            "available_reactions": context.user_data.get("raksh_available_reactions"),
            "link": context.user_data.get("raksh_link"),
            "comment_text": context.user_data.get("raksh_comment"),
            "poll_option": context.user_data.get("raksh_poll_option"),
            "delay_seconds": context.user_data.get("raksh_delay_seconds"),
        }

# ════════════════════════════════════════════════════════
# ═══ 8. الخدمات - كل خدمة في كلاس واحد ═══
# ════════════════════════════════════════════════════════



class StoryService(RakshService):
    """خدمة مشاهدة ستوري وتفاعل - كل شيء في مكان واحد"""
    
    service_type = "story"
    label = "📱 مشاهدة ستوري وتفاعل"
    config = ServiceConfig(
        name=label,
        price_points=30,
        points_quantity=1,
        price_stars=1,
        stars_quantity=10,
        has_channel=False,
        has_reaction=True,
        has_ai=False,
        needs_link=True,
        min_delay=60,
        max_delay=180
    )
    
    def get_link_instruction(self) -> str:
        return (
            "أرسل رابط الستوري بأحد هذه الصيغ:\n"
            "• https://t.me/username/s/123\n"
            "• https://t.me/username/story/123\n"
            "• https://t.me/c/123456789/123"
        )
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        
        entity_ref, story_id = _parse_story_link(value)
        if not entity_ref or not story_id:
            return (
                "⚠️ رابط الستوري غير صحيح.\n\n"
                "أرسله بهذا الشكل:\n"
                "https://t.me/username/s/123\n"
                "أو: https://t.me/username/story/123\n"
                "أو: https://t.me/c/123456789/123"
            )
        return None
    
    def get_start_message(self) -> str:
        return (
            f"{self.config.name}\n\n"
            f"💰 السعر: {self.get_rate_text('points')}\n"
            f"⭐ السعر: {self.get_rate_text('stars')}\n\n"
            f"🔗 *أرسل رابط الستوري:*\n"
            f"{self.get_link_instruction()}"
        )
    
    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        """معالجة النص لخدمة الستوري"""
        
        if state == "link":
            link_error = self.validate_link(text)
            if link_error:
                await update.message.reply_text(
                    link_error,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True
            
            context.user_data["raksh_link"] = text
            context.user_data["raksh_step"] = "quantity"
            
            max_qty = self.get_request_limit(user.id)
            if max_qty < 1:
                await update.message.reply_text(
                    "⚠️ لا توجد حسابات متاحة حالياً.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True
            
            await update.message.reply_text(
                f"✅ تم حفظ رابط الستوري.\n\n"
                f"🔢 *أرسل عدد المشاهدات المطلوبة:*\n"
                f"(الحد الأقصى: {max_qty})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        if state == "quantity":
            try:
                quantity = int(text)
            except ValueError:
                await update.message.reply_text(
                    "⚠️ أرسل رقماً صحيحاً.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True
            
            max_qty = self.get_request_limit(user.id)
            if max_qty < 1:
                await update.message.reply_text(
                    "⚠️ لا توجد حسابات متاحة حالياً.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True
            
            if quantity < 1 or quantity > max_qty:
                await update.message.reply_text(
                    f"⚠️ العدد المسموح بين 1 و {max_qty}.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True
            
            context.user_data["raksh_quantity"] = quantity
            context.user_data["raksh_step"] = "confirm"
            
            points_cost = self.get_total(quantity, "points")
            stars_cost = self.get_total(quantity, "stars")
            
            await update.message.reply_text(
                f"📋 *مراجعة طلب مشاهدة الستوري*\n\n"
                f"🔗 الرابط: `{context.user_data['raksh_link']}`\n"
                f"🔢 العدد: {quantity}\n"
                f"💰 السعر بالنقاط: {points_cost} نقطة\n"
                f"⭐ السعر بالنجوم: {stars_cost} نجمة\n\n"
                f"اختر طريقة الدفع:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"💰 دفع بالنقاط ({points_cost} نقطة)",
                            callback_data=f"raksh_story:confirm:points:{quantity}:{points_cost}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                            callback_data=f"raksh_story:confirm:stars:{quantity}:{stars_cost}"
                        )
                    ],
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        if state == "confirm":
            await update.message.reply_text(
                "⚠️ استخدم الأزرار للتأكيد.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        return False
    
    async def handle_callback(self, update, context, query, data_parts, user, is_own) -> bool:
        """معالجة الأزرار لخدمة الستوري"""
        
        if data_parts[0] == "confirm" and len(data_parts) >= 4:
            payment_method = data_parts[1]
            try:
                quantity = int(data_parts[2])
                button_total = int(data_parts[3])
            except ValueError:
                await query.answer("⚠️ العدد أو السعر غير صالح.", show_alert=True)
                return True
            
            if payment_method not in {"points", "stars"}:
                await query.answer("⚠️ طريقة الدفع غير صالحة.", show_alert=True)
                return True
            
            if quantity > self.get_request_limit(user.id):
                await query.edit_message_text(
                    "⚠️ لا يمكن قبول هذا الطلب حالياً. حاول لاحقاً.",
                    reply_markup=raksh_menu_kb(is_own),
                )
                return True
            
            total_cost = self.get_total(quantity, payment_method)
            
            if payment_method == "points":
                if not deduct_points(user.id, total_cost):
                    await query.edit_message_text(
                        "❌ *نقاطك غير كافية!*\n"
                        f"التكلفة المطلوبة: {total_cost} نقطة",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=raksh_menu_kb(is_own)
                    )
                    return True
                
                await query.edit_message_text(
                    "✅ *تم تأكيد الطلب وخصم النقاط!*\n\n"
                    f"📋 تفاصيل الطلب:\n"
                    f"🔗 الرابط: `{context.user_data.get('raksh_link', '')}`\n"
                    f"🔢 العدد: {quantity}\n"
                    f"💰 تم خصم: {total_cost} نقطة\n\n"
                    f"⏳ جاري بدء التنفيذ...",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                await _start_raksh_execution(
                    update, context, query, "story", quantity, "points", total_cost
                )
                return True
            
            else:
                await query.edit_message_text(
                    "⭐ *جاري تجهيز فاتورة الدفع بالنجوم...*",
                    parse_mode=ParseMode.MARKDOWN,
                )
                await context.bot.send_invoice(
                    chat_id=user.id,
                    title=self.config.name,
                    description=f"{quantity} مشاهدة ستوري | {total_cost} نجمة",
                    payload=f"raksh_stars:{user.id}:{self.service_type}:{quantity}:{total_cost}",
                    provider_token="",
                    currency="XTR",
                    prices=[LabeledPrice("مشاهدة ستوري", total_cost)],
                )
                return True
        
        return False
    
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
    """تنفيذ مشاهدة ستوري وتفاعل"""
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            _mark_raksh_session_unauthorized(session.get("phone_number"))
            return False, "الجلسة غير مصرح بها"
        
        entity_ref, story_id = _parse_story_link(params["link"])
        if not entity_ref or not story_id:
            return False, "رابط الستوري غير صحيح"
        
        try:
            entity = await client.get_entity(entity_ref)
        except Exception as e:
            return False, f"تعذر الوصول للكيان: {str(e)[:80]}"
        
        # ✅ محاولة مشاهدة الستوري بعدة طرق
        view_success = False
        
        # الطريقة 1: IncrementStoryViewsRequest
        try:
            await client(IncrementStoryViewsRequest(peer=entity, id=story_id))
            view_success = True
            logger.info(f"👁️ تمت مشاهدة الستوري {story_id} من {session['phone_number']}")
        except Exception:
            pass
        
        # الطريقة 2: SendReactionRequest (تعتبر مشاهدة)
        if not view_success:
            try:
                await client(SendReactionRequest(
                    peer=entity,
                    story_id=story_id,
                    reaction=ReactionEmoji(emoticon="❤️")
                ))
                view_success = True
                logger.info(f"👁️ تمت مشاهدة الستوري {story_id} من {session['phone_number']}")
            except Exception:
                pass
        
        # الطريقة 3: get_messages
        if not view_success:
            try:
                await client.get_messages(entity, ids=story_id)
                view_success = True
                logger.info(f"👁️ تم الوصول للستوري {story_id} من {session['phone_number']}")
            except Exception:
                pass
        
        if not view_success:
            return False, "تعذر مشاهدة الستوري"
        
        # ✅ إضافة تفاعل تلقائي
        try:
            reaction = params.get("reaction") or "❤️"
            if reaction == "random":
                reaction = random.choice(["❤️", "🔥", "👍", "😍", "🤩", "✨", "💯", "👏", "😂", "😮"])
            
            await client(
                SendReactionRequest(
                    peer=entity,
                    story_id=story_id,
                    reaction=ReactionEmoji(emoticon=reaction),
                )
            )
            return True, f"✅ تمت المشاهدة والتفاعل من {session['phone_number']}"
        except Exception as reaction_error:
            logger.warning(f"تفاعل فاشل للستوري {session['phone_number']}: {reaction_error}")
            return True, f"✅ تمت المشاهدة من {session['phone_number']}"
            
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()
class ForcedRefService(RakshService):
    """خدمة إحالة بوت إجباري - كل شيء في مكان واحد"""
    
    service_type = "forced_ref"
    label = "🔑 إحالة بوت إجباري"
    config = ServiceConfig(
        name=label,
        price_points=250,
        points_quantity=1,
        price_stars=10,
        stars_quantity=1,
        has_channel=True,
        has_reaction=False,
        has_ai=False,
        needs_link=True,
        min_delay=180,
        max_delay=180
    )
    
    def get_link_instruction(self) -> str:
        return "@BotUsername start123  أو  t.me/BotUsername?start=123"
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        bot_username, _ = _parse_bot_link(value)
        if not bot_username:
            return (
                "⚠️ رابط البوت غير صحيح.\n\n"
                "أرسله بهذا الشكل:\n"
                "@BotUsername start123\n"
                "أو: t.me/BotUsername?start=123"
            )
        return None
    
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ إحالة بوت إجباري"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"
            
            if is_first and params.get("channel_ref"):
                await _join_channel_and_schedule_leave(client, params["channel_ref"])
            
            bot_username, start_param = _parse_bot_link(params["link"])
            if not bot_username:
                return False, "رابط البوت غير صحيح"
            
            clean_username = bot_username.lstrip("@").strip()
            resolved = await client(ResolveUsernameRequest(clean_username))
            bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]
            
            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param or ""
            ))
            await asyncio.sleep(1.5)
            
            return True, f"✅ تمت الإحالة من {session['phone_number']}"
        except Exception as e:
            return False, f"❌ فشل: {str(e)}"
        finally:
            await client.disconnect()

class ForcedRefAIService(ForcedRefService):
    """خدمة إحالة بوت إجباري مع تحقق - كل شيء في مكان واحد"""
    
    service_type = "forced_ref_ai"
    label = "🤖 إحالة بوت إجباري مع تحقق"
    config = ServiceConfig(
        name=label,
        price_points=300,
        points_quantity=1,
        price_stars=15,
        stars_quantity=1,
        has_channel=True,
        has_reaction=False,
        has_ai=True,
        needs_link=True,
        min_delay=180,
        max_delay=180
    )
    
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ إحالة بوت إجباري مع تحقق شامل"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=20)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"
            
            if is_first and params.get("channel_ref"):
                await _join_channel_and_schedule_leave(client, params["channel_ref"])
            
            bot_username, start_param = _parse_bot_link(params["link"])
            if not bot_username:
                return False, "رابط البوت غير صحيح"
            
            clean_username = bot_username.lstrip("@").strip()
            resolved = await client(ResolveUsernameRequest(clean_username))
            bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]
            
            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param or ""
            ))
            await asyncio.sleep(2.0)
            
            success = await _solve_forced_ref_verification(client, bot_entity, session.get("phone_number"))
            
            if success:
                return True, f"✅ تمت الإحالة مع التحقق من {session['phone_number']}"
            else:
                return False, "فشل التحقق بعد محاولات متعددة"
        except Exception as e:
            return False, f"❌ فشل: {str(e)}"
        finally:
            await client.disconnect()

class CommentService(RakshService):
    """خدمة رشق تعليق - كل شيء في مكان واحد"""
    
    service_type = "comment"
    label = "💬 رشق تعليق"
    config = ServiceConfig(
        name=label,
        price_points=30,
        points_quantity=1,
        price_stars=5,
        stars_quantity=1,
        has_channel=True,
        has_reaction=False,
        has_ai=False,
        needs_link=True,
        min_delay=60,
        max_delay=120
    )
    
    def get_link_instruction(self) -> str:
        return "https://t.me/channel/123"
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        if not all(_parse_post_link(value)):
            return "⚠️ الرابط غير صحيح لهذه الخدمة.\n\nأرسل: https://t.me/channel/123"
        return None
    
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ رشق تعليق"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"
            
            if is_first and params.get("channel_ref"):
                await _join_channel_and_schedule_leave(client, params["channel_ref"])
            
            channel_ref, msg_id = _parse_post_link(params["link"])
            if not channel_ref:
                return False, "رابط المنشور غير صحيح"
            
            entity = await client.get_entity(channel_ref)
            comment_text = params.get("comment_text", "")
            if not comment_text:
                return False, "نص التعليق فارغ"
            
            await client.send_message(entity, comment_text, reply_to=msg_id)
            return True, f"✅ تم التعليق من {session['phone_number']}"
        except Exception as e:
            return False, f"❌ فشل التعليق: {str(e)}"
        finally:
            await client.disconnect()

class PollService(RakshService):
    """خدمة رشق استفتاء - كل شيء في مكان واحد"""
    
    service_type = "poll"
    label = "📊 رشق استفتاء"
    config = ServiceConfig(
        name=label,
        price_points=30,
        points_quantity=1,
        price_stars=5,
        stars_quantity=1,
        has_channel=True,
        has_reaction=False,
        has_ai=False,
        needs_link=True,
        min_delay=60,
        max_delay=120
    )
    
    def get_link_instruction(self) -> str:
        return "https://t.me/channel/123"
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        if not all(_parse_post_link(value)):
            return "⚠️ الرابط غير صحيح لهذه الخدمة.\n\nأرسل: https://t.me/channel/123"
        return None
    
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ رشق استفتاء"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"
            
            if is_first and params.get("channel_ref"):
                await _join_channel_and_schedule_leave(client, params["channel_ref"])
            
            channel_ref, msg_id = _parse_post_link(params["link"])
            if not channel_ref:
                return False, "رابط المنشور غير صحيح"
            
            entity = await client.get_entity(channel_ref)
            message = await client.get_messages(entity, ids=msg_id)
            if not message:
                return False, "المنشور غير موجود"
            
            poll = getattr(message, "poll", None)
            if not poll:
                return False, "هذا المنشور ليس استفتاءً"
            
            options = getattr(poll, "answers", [])
            if not options:
                return False, "الاستفتاء ليس له خيارات"
            
            option_request = params.get("poll_option", "1")
            option = _select_poll_option(options, option_request)
            if not option:
                return False, f"الخيار {option_request} غير موجود"
            
            success = await _send_vote_and_check(client, entity, msg_id, option)
            if not success:
                return False, "تعذر تأكيد التصويت"
            
            return True, f"✅ تم التصويت من {session['phone_number']}"
        except Exception as e:
            return False, f"❌ فشل التصويت: {str(e)}"
        finally:
            await client.disconnect()

class VotesService(RakshService):
    """خدمة رشق أصوات - كل شيء في مكان واحد"""
    
    service_type = "votes"
    label = "🗳 رشق أصوات"
    config = ServiceConfig(
        name=label,
        price_points=20,
        points_quantity=1,
        price_stars=4,
        stars_quantity=1,
        has_channel=True,
        has_reaction=False,
        has_ai=False,
        needs_link=True,
        min_delay=3,
        max_delay=3
    )
    
    def get_link_instruction(self) -> str:
        return "https://t.me/channel/123 أو رابط بوت تصويت"
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        return None
    
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ رشق أصوات"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"
            
            if is_first and params.get("channel_ref"):
                await _join_channel_and_schedule_leave(client, params["channel_ref"])
            
            link = params["link"]
            channel_ref, msg_id = _parse_post_link(link)
            if not channel_ref:
                bot_username, start_param = _parse_bot_link(link)
                if bot_username:
                    clean_username = bot_username.lstrip("@").strip()
                    resolved = await client(ResolveUsernameRequest(clean_username))
                    bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]
                    await client(StartBotRequest(
                        bot=bot_entity,
                        peer=bot_entity,
                        start_param=start_param or ""
                    ))
                    await asyncio.sleep(1.5)
                    return True, f"✅ تم التصويت من {session['phone_number']}"
                return False, "الرابط غير صحيح لهذه الخدمة"
            
            entity = await client.get_entity(channel_ref)
            message = await client.get_messages(entity, ids=msg_id)
            if not message:
                return False, "المنشور غير موجود"
            
            vote_button = None
            for row in getattr(message, "buttons", None) or []:
                for btn in row:
                    if getattr(btn, "url", None):
                        continue
                    btn_text = (getattr(btn, "text", None) or "").lower()
                    if any(word in btn_text for word in ["تصويت", "صوت", "vote", "voting"]):
                        vote_button = btn
                        break
                if vote_button:
                    break
            
            if vote_button:
                await vote_button.click()
                await asyncio.sleep(1.0)
                return True, f"✅ تم التصويت من {session['phone_number']}"
            else:
                return False, "لم يتم العثور على زر التصويت"
        except Exception as e:
            return False, f"❌ فشل التصويت: {str(e)}"
        finally:
            await client.disconnect()

class VotesAIService(RakshService):
    """خدمة رشق تصويت مع تحقق - كل شيء في مكان واحد"""
    
    service_type = "votes_ai"
    label = "🛡 رشق تصويت مع تحقق"
    config = ServiceConfig(
        name=label,
        price_points=50,
        points_quantity=1,
        price_stars=10,
        stars_quantity=1,
        has_channel=True,
        has_reaction=False,
        has_ai=True,
        needs_link=True,
        min_delay=3,
        max_delay=3,
        max_concurrent=1
    )
    
    def get_link_instruction(self) -> str:
        return "https://t.me/i8YYBot?start=compvote_xxx"
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        if not ("@" in value or "t.me/" in value):
            return "⚠️ الرابط يجب أن يحتوي على @username أو t.me/"
        return None
    
    async def execute(self, session, params, is_first):
        """تنفيذ تصويت مع تحقق"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها."

            bot_username, bot_start_param = _parse_bot_link(params.get("link", ""))
            bot_entity = None

            if bot_username and bot_start_param:
                try:
                    resolved = await client(ResolveUsernameRequest(bot_username))
                    if resolved.users:
                        bot_entity = resolved.users[0]
                    elif resolved.chats:
                        bot_entity = resolved.chats[0]
                except Exception:
                    try:
                        bot_entity = await client.get_entity(bot_username)
                    except Exception:
                        try:
                            bot_entity = await client.get_entity(f"@{bot_username}")
                        except Exception as e3:
                            return False, f"فشل العثور على البوت {bot_username}: {str(e3)[:80]}"
            else:
                post_ref, post_id = _parse_post_link(params.get("link", ""))
                if not post_ref or not post_id:
                    return False, "الرابط غير صالح (ليس بوتًا ولا بوستًا)."

                try:
                    post_entity = await client.get_entity(post_ref)
                except Exception:
                    return False, "تعذر الوصول إلى القناة/المنشور."

                try:
                    messages = await client.get_messages(post_entity, ids=post_id)
                    if isinstance(messages, (list, tuple)):
                        messages = messages[0] if messages else None
                    else:
                        messages = messages
                    if not messages:
                        return False, "المنشور غير موجود."
                    post_message = messages
                except Exception:
                    return False, "تعذر جلب المنشور."

                bot_username, bot_start_param = _find_bot_start_link(post_message)
                if not bot_username or not bot_start_param:
                    return False, "المنشور لا يحتوي على زر بوت صالح."

                try:
                    bot_entity = await client.get_entity(bot_username)
                except Exception:
                    try:
                        bot_entity = await client.get_entity(f"@{bot_username}")
                    except Exception as e3:
                        return False, f"تعذر العثور على بوت الزر: {str(e3)[:80]}"

            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=bot_start_param
            ))

            await asyncio.sleep(1.0)
            verification_message_id = None
            verification_message = None
            for attempt in range(5):
                msgs = await client.get_messages(bot_entity, limit=50)
                if isinstance(msgs, (list, tuple)):
                    for m in msgs:
                        if getattr(m, "buttons", None) and not getattr(m, "url", None):
                            verification_message = m
                            verification_message_id = m.id
                            break
                    if verification_message:
                        break
                await asyncio.sleep(1.0)

            if verification_message is None or verification_message_id is None:
                logger.info(f"لم يظهر زر تحقق بعد فتح البوت، تعتبر العملية ناجحة (بدون تحقق) للحساب {session['phone_number']}")
                return True, RAKSH_NO_VERIFICATION_MESSAGE

            verification_text = getattr(verification_message, "message", "") or getattr(verification_message, "text", "") or ""
            
            target_emoji = None
            emoji_pattern = re.compile(
                "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E0-\U0001F1FF]"
            )
            found_emojis = emoji_pattern.findall(verification_text)
            if found_emojis:
                target_emoji = found_emojis[-1]
                logger.info(f"✅ تم استخراج الإيموجي المطلوب: {target_emoji}")

            all_buttons = []
            for row in (getattr(verification_message, "buttons", None) or []):
                for btn in row:
                    if not getattr(btn, "url", None):
                        all_buttons.append(btn)

            if not all_buttons:
                logger.info(f"رسالة التحقق لا تحتوي أزرار قابلة للضغط، تعتبر العملية ناجحة (بدون تحقق) للحساب {session['phone_number']}")
                return True, RAKSH_NO_VERIFICATION_MESSAGE

            buttons_to_try = []
            if target_emoji:
                exact = [b for b in all_buttons if getattr(b, "text", "") == target_emoji]
                buttons_to_try.extend(exact)
                partial = [b for b in all_buttons if target_emoji in (getattr(b, "text", "") or "")]
                buttons_to_try.extend(partial)
            verify = [b for b in all_buttons if any(w in (getattr(b, "text", "") or "").lower() for w in ['تحقق', 'verify', 'اضغط هنا', 'continue', 'التالي'])]
            buttons_to_try.extend(verify)
            emojis = [b for b in all_buttons if any(0x1F300 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF for c in (getattr(b, "text", "") or ""))]
            buttons_to_try.extend(emojis)
            buttons_to_try.extend([b for b in all_buttons if b not in buttons_to_try])

            seen = set()
            unique_buttons = []
            for b in buttons_to_try:
                if id(b) not in seen:
                    seen.add(id(b))
                    unique_buttons.append(b)

            max_attempts = 30
            pressed_ids = set()
            current_index = 0
            for attempt in range(max_attempts):
                try:
                    target_message = await client.get_messages(bot_entity, ids=verification_message_id)
                    if isinstance(target_message, (list, tuple)):
                        target_message = target_message[0] if target_message else None
                except Exception:
                    target_message = None

                if target_message is None:
                    logger.info(f"✅ رسالة التحقق اختفت تماماً – تم تأكيد التحقق للحساب {session['phone_number']}")
                    return True, f"✅ تم تسجيل التصويت من {session['phone_number']}"

                if not getattr(target_message, "buttons", None):
                    logger.info(f"✅ اختفت أزرار رسالة التحقق – تم تأكيد التحقق للحساب {session['phone_number']}")
                    return True, f"✅ تم تسجيل التصويت من {session['phone_number']}"

                button = None
                if target_emoji:
                    for row in (getattr(target_message, "buttons", None) or []):
                        for b in row:
                            if not getattr(b, "url", None) and (getattr(b, "text", "") == target_emoji or target_emoji in (getattr(b, "text", "") or "")) and id(b) not in pressed_ids:
                                button = b
                                break
                        if button:
                            break

                if button is None:
                    while current_index < len(unique_buttons) and id(unique_buttons[current_index]) in pressed_ids:
                        current_index += 1
                    if current_index < len(unique_buttons):
                        button = unique_buttons[current_index]
                        current_index += 1
                    else:
                        pressed_ids.clear()
                        current_index = 0
                        if unique_buttons:
                            button = unique_buttons[current_index]
                            current_index += 1
                        else:
                            break

                if button is None:
                    break

                button_text = getattr(button, "text", "") or ""
                logger.info(f"🖱️ الحساب {session['phone_number']} – محاولة {attempt+1}: الضغط على '{button_text}'")
                try:
                    await button.click()
                except Exception as e:
                    logger.warning(f"⚠️ فشل الضغط على الزر '{button_text}': {e}")
                    continue

                pressed_ids.add(id(button))
                await asyncio.sleep(2.0)

            try:
                final_message = await client.get_messages(bot_entity, ids=verification_message_id)
                if isinstance(final_message, (list, tuple)):
                    final_message = final_message[0] if final_message else None
            except Exception:
                final_message = None

            if final_message is None or not getattr(final_message, "buttons", None):
                logger.info(f"✅ اختفت الأزرار في الفحص النهائي – تم تأكيد التحقق للحساب {session['phone_number']}")
                return True, f"✅ تم تسجيل التصويت من {session['phone_number']}"
            else:
                logger.warning(f"⚠️ لم تختفِ أزرار رسالة التحقق بعد {max_attempts} محاولة للحساب {session['phone_number']}")
                return False, "لم تختفِ أزرار التحقق – فشل"

        except Exception as e:
            return False, f"❌ فشل: {str(e)[:80]}"
        finally:
            await client.disconnect()

class PremiumReactionService(RakshService):
    """خدمة رشق تفاعل مميز - كل شيء في مكان واحد"""
    
    service_type = "premium_reaction"
    label = "✨ رشق تفاعل مميز"
    config = ServiceConfig(
        name=label,
        price_points=10,
        points_quantity=1,
        price_stars=2,
        stars_quantity=1,
        has_channel=True,
        has_reaction=True,
        has_ai=False,
        needs_link=True,
        min_delay=30,
        max_delay=60
    )
    
    def get_link_instruction(self) -> str:
        return "https://t.me/channel/123"
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        if not all(_parse_post_link(value)):
            return "⚠️ الرابط غير صحيح لهذه الخدمة.\n\nأرسل: https://t.me/channel/123"
        return None
    
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ رشق تفاعل مميز"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"
            
            if is_first and params.get("channel_ref"):
                await _join_channel_and_schedule_leave(client, params["channel_ref"])
            
            channel_ref, msg_id = _parse_post_link(params["link"])
            if not channel_ref:
                return False, "رابط المنشور غير صحيح"
            
            entity = await client.get_entity(channel_ref)
            
            reaction = params.get("reaction")
            if not reaction or reaction == "random":
                available = params.get("available_reactions") or list(RAKSH_REACTIONS.values())
                reaction = random.choice(available)
            
            if reaction == RAKSH_PAID_REACTION:
                try:
                    await client(
                        SendReactionRequest(
                            peer=entity,
                            msg_id=msg_id,
                            reaction=ReactionEmoji(emoticon="⭐"),
                            big=True,
                        )
                    )
                    return True, f"✅ تم التفاعل المدفوع من {session['phone_number']}"
                except Exception as e:
                    logger.warning(f"فشل التفاعل المدفوع: {e}")
                    return False, f"فشل التفاعل المدفوع: {str(e)}"
            else:
                try:
                    await client(
                        SendReactionRequest(
                            peer=entity,
                            msg_id=msg_id,
                            reaction=ReactionEmoji(emoticon=reaction),
                        )
                    )
                    return True, f"✅ تم التفاعل من {session['phone_number']}"
                except Exception as e:
                    return False, f"فشل التفاعل: {str(e)}"
        except Exception as e:
            return False, f"❌ فشل: {str(e)}"
        finally:
            await client.disconnect()

# ════════════════════════════════════════════════════════
# ═══ 9. تسجيل الخدمات ═══
# ════════════════════════════════════════════════════════

RAKSH_SERVICES: Dict[str, RakshService] = {
    StoryService.service_type: StoryService(),
    ForcedRefService.service_type: ForcedRefService(),
    ForcedRefAIService.service_type: ForcedRefAIService(),
    CommentService.service_type: CommentService(),
    PollService.service_type: PollService(),
    VotesService.service_type: VotesService(),
    VotesAIService.service_type: VotesAIService(),
    PremiumReactionService.service_type: PremiumReactionService(),
}

RAKSH_SERVICE_LABELS = {
    svc_type: svc.label for svc_type, svc in RAKSH_SERVICES.items()
}

# ════════════════════════════════════════════════════════
# ═══ 10. دوال مساعدة عامة ═══
# ════════════════════════════════════════════════════════

def get_raksh_service(service_type: str) -> Optional[RakshService]:
    """الحصول على الخدمة"""
    return RAKSH_SERVICES.get(service_type)

def get_raksh_price_config(service_type: str) -> Dict[str, int]:
    """إرجاع إعدادات الأسعار"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.get_price_config()
    return {}

def get_raksh_total(service_type: str, quantity: int, payment_method: str) -> int:
    """حساب السعر"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.get_total(quantity, payment_method)
    return 0

def _raksh_rate_text(service_type: str, payment_method: str) -> str:
    """نص عرض السعر"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.get_rate_text(payment_method)
    return ""

def _raksh_order_label(service_type: str) -> str:
    """اسم مختصر للطلب"""
    svc = get_raksh_service(service_type)
    return svc.label if svc else service_type

def _get_delay_seconds(service_type: str, custom_delay: Optional[int] = None) -> int:
    """حساب الفاصل الزمني بين التنفيذات"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.get_delay_seconds(custom_delay)
    return random.randint(RAKSH_MIN_DELAY_SECONDS, RAKSH_MAX_DELAY_SECONDS)

def get_raksh_hourly_remaining(user_id: int) -> int:
    """عدد التنفيذات المتبقية خلال الساعة"""
    if RAKSH_MAX_EXECUTIONS_PER_HOUR <= 0:
        return 2_147_483_647
    try:
        with db_conn() as c:
            row = c.execute(
                """
                SELECT COUNT(*) AS used
                FROM raksh_execution_usage
                WHERE user_id=%s
                  AND executed_at >= NOW() - INTERVAL '1 hour'
                """,
                (user_id,),
            ).fetchone()
        used = int(row["used"] or 0) if row else 0
        return max(0, RAKSH_MAX_EXECUTIONS_PER_HOUR - used)
    except Exception:
        logger.exception(f"فشل قراءة حد التنفيذ للمستخدم {user_id}")
        return 0

def get_raksh_daily_remaining(user_id: int) -> int:
    """عدد التنفيذات المتبقية خلال اليوم"""
    try:
        with db_conn() as c:
            row = c.execute(
                """
                SELECT COUNT(*) AS used
                FROM raksh_execution_usage
                WHERE user_id=%s
                  AND executed_at >= NOW() - INTERVAL '1 day'
                """,
                (user_id,),
            ).fetchone()
        used = int(row["used"] or 0) if row else 0
        return max(0, RAKSH_MAX_EXECUTIONS_PER_DAY - used)
    except Exception:
        return RAKSH_MAX_EXECUTIONS_PER_DAY

def _reserve_raksh_execution_slot(user_id: int, service_type: str, phone_number: str) -> bool:
    """حجز تنفيذ واحد"""
    if RAKSH_MAX_EXECUTIONS_PER_HOUR <= 0 and RAKSH_MAX_EXECUTIONS_PER_DAY <= 0:
        return True
    try:
        with db_conn() as c:
            c.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"raksh-hourly:{user_id}",),
            )
            
            if RAKSH_MAX_EXECUTIONS_PER_DAY > 0:
                row = c.execute(
                    """
                    SELECT COUNT(*) AS used
                    FROM raksh_execution_usage
                    WHERE user_id=%s
                      AND executed_at >= NOW() - INTERVAL '1 day'
                    """,
                    (user_id,),
                ).fetchone()
                if row and int(row["used"] or 0) >= RAKSH_MAX_EXECUTIONS_PER_DAY:
                    return False
            
            if RAKSH_MAX_EXECUTIONS_PER_HOUR > 0:
                row = c.execute(
                    """
                    SELECT COUNT(*) AS used
                    FROM raksh_execution_usage
                    WHERE user_id=%s
                      AND executed_at >= NOW() - INTERVAL '1 hour'
                    """,
                    (user_id,),
                ).fetchone()
                if row and int(row["used"] or 0) >= RAKSH_MAX_EXECUTIONS_PER_HOUR:
                    return False
            
            c.execute(
                """
                INSERT INTO raksh_execution_usage
                    (user_id, service_type, phone_number)
                VALUES (%s, %s, %s)
                """,
                (user_id, service_type, phone_number),
            )
        return True
    except Exception:
        logger.exception(f"فشل حجز تنفيذ للمستخدم {user_id}")
        return False

# ════════════════════════════════════════════════════════
# ═══ 11. مدير التنفيذ ═══
# ════════════════════════════════════════════════════════

async def execute_raksh_service(
    service_type: str,
    quantity: int,
    sessions: List[Dict],
    params: Dict,
    user_id: int,
    progress_callback=None,
) -> Tuple[int, List[str], List[str], List[str], List[str]]:
    """تنفيذ طلب رشق"""
    if not sessions:
        raise RuntimeError("لا توجد جلسات نشطة متاحة")
    
    svc = get_raksh_service(service_type)
    if not svc:
        raise RuntimeError(f"خدمة غير معروفة: {service_type}")
    
    max_concurrent = svc.config.max_concurrent
    
    shuffled = sessions.copy()
    random.shuffle(shuffled)
    
    success_count = 0
    success_phones = []
    success_details = []
    failed_phones = []
    failed_details = []
    used_phones = set()
    
    if max_concurrent == 1 or service_type in {"votes_ai", "forced_ref", "forced_ref_ai"}:
        if service_type == "votes_ai":
            async with _RAKSH_VOTE_FLOW_LOCK:
                return await _execute_raksh_sequential(
                    svc, shuffled, params, user_id,
                    quantity, progress_callback, service_type
                )
        
        return await _execute_raksh_sequential(
            svc, shuffled, params, user_id,
            quantity, progress_callback, service_type
        )
    
    return await _execute_raksh_parallel(
        svc, shuffled, params, user_id,
        quantity, progress_callback, service_type, max_concurrent
    )

async def _execute_raksh_sequential(
    svc: RakshService,
    sessions: List[Dict],
    params: Dict,
    user_id: int,
    quantity: int,
    progress_callback,
    service_type: str,
) -> Tuple[int, List[str], List[str], List[str], List[str]]:
    """تنفيذ الخدمات بشكل تسلسلي"""
    success_count = 0
    success_phones = []
    success_details = []
    failed_phones = []
    failed_details = []
    used_phones = set()
    
    for i in range(quantity):
        if not sessions:
            break
        session = sessions.pop(0)
        phone = session["phone_number"]
        if phone in used_phones:
            continue
        used_phones.add(phone)
        
        if not _reserve_raksh_execution_slot(user_id, service_type, phone):
            failed_phones.append(phone)
            failed_details.append("تم تجاوز حد التنفيذ")
            continue
        
        session_lock = _get_raksh_session_lock(phone)
        if session_lock.locked():
            failed_phones.append(phone)
            failed_details.append("الجلسة قيد الاستخدام")
            continue
        
        async with session_lock:
            try:
                ok, msg = await svc.execute(
                    session=session,
                    params=params,
                    is_first=(i == 0),
                )
            except Exception as e:
                ok = False
                msg = f"❌ خطأ: {str(e)}"
        
        if ok:
            success_count += 1
            success_phones.append(phone)
            success_details.append(msg)
        else:
            failed_phones.append(phone)
            failed_details.append(msg)
        
        if progress_callback:
            await progress_callback(i + 1, quantity, success_count, len(failed_details))
        
        if i < quantity - 1 and sessions:
            delay = svc.get_delay_seconds(params.get("delay_seconds"))
            await asyncio.sleep(delay)
    
    await _remove_invalid_raksh_sessions(failed_phones)
    return success_count, success_phones, success_details, failed_phones, failed_details

async def _execute_raksh_parallel(
    svc: RakshService,
    sessions: List[Dict],
    params: Dict,
    user_id: int,
    quantity: int,
    progress_callback,
    service_type: str,
    max_concurrent: int,
) -> Tuple[int, List[str], List[str], List[str], List[str]]:
    """تنفيذ الخدمات بشكل متوازي"""
    success_count = 0
    success_phones = []
    success_details = []
    failed_phones = []
    failed_details = []
    used_phones = set()
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def execute_one(session, index):
        nonlocal success_count
        phone = session["phone_number"]
        if phone in used_phones:
            return
        used_phones.add(phone)
        
        if not _reserve_raksh_execution_slot(user_id, service_type, phone):
            failed_phones.append(phone)
            failed_details.append("تم تجاوز حد التنفيذ")
            return
        
        session_lock = _get_raksh_session_lock(phone)
        if session_lock.locked():
            failed_phones.append(phone)
            failed_details.append("الجلسة قيد الاستخدام")
            return
        
        async with session_lock:
            try:
                ok, msg = await svc.execute(
                    session=session,
                    params=params,
                    is_first=(index == 0),
                )
            except Exception as e:
                ok = False
                msg = f"❌ خطأ: {str(e)}"
        
        if ok:
            success_count += 1
            success_phones.append(phone)
            success_details.append(msg)
        else:
            failed_phones.append(phone)
            failed_details.append(msg)
        
        if progress_callback:
            await progress_callback(index + 1, quantity, success_count, len(failed_details))
    
    tasks = []
    for i, session in enumerate(sessions[:quantity]):
        if session["phone_number"] in used_phones:
            continue
        tasks.append(execute_one(session, i))
    
    await asyncio.gather(*tasks)
    await _remove_invalid_raksh_sessions(failed_phones)
    return success_count, success_phones, success_details, failed_phones, failed_details

# ════════════════════════════════════════════════════════
# ═══ 12. واجهات المستخدم ═══
# ════════════════════════════════════════════════════════

def _is_raksh_service_enabled(service_type: str) -> bool:
    """التحقق من تفعيل الخدمة"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.is_enabled()
    return False

def _set_raksh_service_enabled(service_type: str, enabled: bool) -> None:
    """تفعيل/إخفاء خدمة"""
    svc = get_raksh_service(service_type)
    if svc:
        svc.set_enabled(enabled)

def raksh_menu_kb(is_owner: bool = False):
    """قائمة الخدمات"""
    buttons = []
    for key, svc in RAKSH_SERVICES.items():
        if not is_owner and not svc.is_enabled():
            continue
        service_button = InlineKeyboardButton(
            svc.config.name, callback_data=f"raksh:start:{key}"
        )
        if is_owner:
            enabled = svc.is_enabled()
            buttons.append([
                service_button,
                InlineKeyboardButton(
                    "✅ مفعلة" if enabled else "🚫 مخفية",
                    callback_data=f"raksh:toggle:{key}",
                ),
            ])
        else:
            buttons.append([service_button])
    
    if is_owner:
        buttons.append([
            InlineKeyboardButton(
                f"🔥 إدارة {get_raksh_accounts_label()}",
                callback_data="os:raksh_accounts",
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                "⚙️ إدارة الأسعار",
                callback_data="raksh:settings",
            )
        ])
    
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def raksh_price_settings_kb():
    """أزرار إدارة الأسعار"""
    rows = []
    for service_type, svc in RAKSH_SERVICES.items():
        config = svc.get_price_config()
        rows.append([
            InlineKeyboardButton(
                f"{svc.label}: ⭐ {config['stars_price']}/{config['stars_quantity']} | "
                f"💰 {config['points_price']}/{config['points_quantity']}",
                callback_data=f"raksh:price:{service_type}",
            )
        ])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
    return InlineKeyboardMarkup(rows)

def raksh_payment_kb(service_type: str, quantity: int, points_cost: int, stars_cost: int):
    """أزرار الدفع"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                callback_data=f"raksh:pay:stars:{service_type}:{quantity}"
            )
        ],
        [
            InlineKeyboardButton(
                f"💰 دفع بالنقاط ({points_cost} نقطة)",
                callback_data=f"raksh:pay:points:{service_type}:{quantity}"
            )
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data="raksh_menu")],
    ])

def raksh_channel_kb():
    """أزرار تخطي القنوات"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭️ تخطي (بدون قنوات)", callback_data="raksh:skip_channels")],
        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")],
    ])

def raksh_reaction_kb(service_type: str, reactions: Optional[List[str]] = None):
    """أزرار التفاعلات"""
    buttons = []
    row = []
    
    if reactions:
        reaction_items = [(r, r) for r in reactions]
    else:
        reaction_items = list(RAKSH_REACTIONS.items())
    
    for index, (reaction_key, reaction) in enumerate(reaction_items, start=1):
        if reaction == RAKSH_PAID_REACTION:
            callback_key = "paid"
            reaction_label = RAKSH_PAID_REACTION_LABEL
        elif _custom_reaction_document_id(reaction) is not None:
            callback_key = f"custom_{_custom_reaction_document_id(reaction)}"
            reaction_label = f"🎨 تفاعل مميز {index}"
        else:
            callback_key = reaction_key if reaction_key in RAKSH_REACTIONS else str(index)
            reaction_label = reaction
        
        row.append(
            InlineKeyboardButton(
                reaction_label,
                callback_data=f"raksh:reaction:{service_type}:{callback_key}",
            )
        )
        if len(row) == 4:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    buttons.append([
        InlineKeyboardButton(
            "🎲 عشوائي",
            callback_data=f"raksh:reaction:{service_type}:random"
        )
    ])
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="raksh_menu")])
    return InlineKeyboardMarkup(buttons)

def raksh_confirm_kb(service_type: str, quantity: int, total_cost: int, payment_method: str):
    """أزرار تأكيد الطلب"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ تأكيد الطلب",
                callback_data=f"raksh:confirm:{service_type}:{quantity}:{total_cost}:{payment_method}"
            )
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data="raksh_cancel")],
    ])

def _get_link_instruction(service_type: str) -> str:
    """تعليمات الرابط حسب الخدمة"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.get_link_instruction()
    return "أرسل الرابط المطلوب"

def _parse_raksh_rate_updates(text: str) -> Dict[str, Tuple[int, int]]:
    """قراءة تحديثات الأسعار"""
    updates = {}
    for line in (text or "").splitlines():
        normalized = line.casefold().strip()
        numbers = re.findall(r"\d+", normalized)
        if len(numbers) < 2:
            continue
        price, bundle_quantity = int(numbers[0]), int(numbers[1])
        if price < 1 or bundle_quantity < 1:
            continue
        if "نج" in normalized or "star" in normalized:
            updates["stars"] = (price, bundle_quantity)
        elif "نق" in normalized or "point" in normalized:
            updates["points"] = (price, bundle_quantity)
    return updates

def _raksh_link_error(service_type: str, value: str) -> Optional[str]:
    """التحقق من صحة الرابط"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.validate_link(value)
    return "⚠️ خدمة غير معروفة"

def _get_max_quantity(service_type: str) -> int:
    """الحد الأقصى للكمية"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.get_max_quantity()
    return 0

def _get_request_limit(user_id: int, service_type: str) -> int:
    """الحد الفعلي للطلب"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.get_request_limit(user_id)
    return 0

def _chunk_lines(lines: List[str], max_chars: int = 3500) -> List[str]:
    """تقسيم القوائم الطويلة"""
    chunks = []
    current = []
    current_length = 0
    for line in lines:
        line_length = len(line) + 1
        if current and current_length + line_length > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_length = 0
        current.append(line)
        current_length += line_length
    if current:
        chunks.append("\n".join(current))
    return chunks

# ════════════════════════════════════════════════════════
# ═══ 13. المعالج الرئيسي للأزرار ═══
# ════════════════════════════════════════════════════════

async def handle_raksh_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query=None,
    data=None,
    user=None,
    is_own=None,
):
    """معالج أزرار الرشق الرئيسي"""
    query = query or update.callback_query
    data = query.data if data is None else data
    user = user or query.from_user
    is_own = (user.id == OWNER_ID) if is_own is None else is_own
    
    await query.answer()
    
    # ─── تفعيل/إخفاء خدمة ───
    if data.startswith("raksh:toggle:"):
        if not is_own:
            await query.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
            return
        service_type = data.split(":", 2)[2]
        if service_type not in RAKSH_SERVICES:
            await query.answer("⚠️ الخدمة غير موجودة.", show_alert=True)
            return
        svc = RAKSH_SERVICES[service_type]
        enabled = not svc.is_enabled()
        svc.set_enabled(enabled)
        await query.edit_message_text(
            f"🔥 *إدارة {md_escape(get_raksh_accounts_label())}*\n\n"
            "✅ مفعلة: تظهر للأعضاء\n"
            "🚫 مخفية: لا تظهر للأعضاء\n\n"
            f"📊 الحسابات المتاحة: *{get_available_sessions_count()}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_menu_kb(True),
        )
        return
    
    # ─── إدارة الأسعار ───
    if data == "raksh:settings":
        if not is_own:
            await query.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
            return
        await query.edit_message_text(
            "⚙️ *إعدادات أسعار خدمات الرشق*\n\n"
            "اضغط على الخدمة، ثم أرسل السعرين بصيغة:\n"
            "⭐ `نجوم 1 لكل 10`\n"
            "💰 `نقاط 30 لكل 1`\n\n"
            "أي سطر ترسله سيحدّث الطريقة المذكورة فيه.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_price_settings_kb(),
        )
        return
    
    # ─── تعديل سعر خدمة ───
    if data.startswith("raksh:price:"):
        if not is_own:
            await query.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
            return
        service_type = data.split(":")[2]
        if service_type not in RAKSH_SERVICES:
            await query.answer("⚠️ الخدمة غير موجودة.", show_alert=True)
            return
        svc = RAKSH_SERVICES[service_type]
        config = svc.get_price_config()
        context.user_data["raksh_price_edit_service"] = service_type
        context.user_data["raksh_step"] = "admin_price"
        await query.edit_message_text(
            f"✏️ *تعديل سعر {svc.label}*\n\n"
            f"⭐ الحالي: {config['stars_price']} نجمة لكل {config['stars_quantity']}\n"
            f"💰 الحالي: {config['points_price']} نقطة لكل {config['points_quantity']}\n\n"
            "أرسل سطراً أو سطرين بهذا الشكل:\n"
            "`نجوم 1 لكل 10`\n"
            "`نقاط 30 لكل 1`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع للأسعار", callback_data="raksh:settings")]
            ]),
        )
        return
    
    # ─── القائمة الرئيسية ───
    if data in {"raksh_menu", "raksh_cancel"}:
        _clear_raksh_state(context)
        if data == "raksh_cancel":
            await query.edit_message_text(
                "🏠 *القائمة الرئيسية*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own),
            )
            return
        await query.edit_message_text(
            f"🔥 *{md_escape(get_raksh_accounts_label())}*\n\n"
            "اختر الخدمة المطلوبة:\n"
            f"📊 الحسابات المتاحة: *{get_available_sessions_count()}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_menu_kb(is_own)
        )
        return
    
    # ─── بدء خدمة ───
    if data.startswith("raksh:start:"):
        service_type = data.split(":")[2]
        svc = RAKSH_SERVICES.get(service_type)
        if not svc:
            await query.edit_message_text(
                "⚠️ خدمة غير موجودة.",
                reply_markup=raksh_menu_kb(is_own),
            )
            return
        if not is_own and not svc.is_enabled():
            await query.edit_message_text(
                "⚠️ هذه الخدمة مخفية حالياً.",
                reply_markup=raksh_menu_kb(False),
            )
            return
        
        _clear_raksh_state(context)
        context.user_data["raksh_service"] = service_type
        context.user_data["raksh_step"] = svc.get_initial_state()
        
        await query.edit_message_text(
            svc.get_start_message(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=svc.get_start_keyboard()
        )
        return
    
    # ─── تخطي القنوات ───
    if data == "raksh:skip_channels":
        context.user_data["raksh_channels"] = []
        context.user_data["raksh_step"] = "link"
        svc = RAKSH_SERVICES.get(context.user_data.get("raksh_service"))
        await query.edit_message_text(
            f"✅ تم تخطي القنوات.\n\n"
            f"🔗 *أرسل الرابط المطلوب:*\n"
            f"{_get_link_instruction(context.user_data.get('raksh_service'))}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
            ])
        )
        return
    
    # ─── اختيار تفاعل ───
    if data.startswith("raksh:reaction:"):
        parts = data.split(":")
        service_type = parts[2]
        reaction_key = parts[3]
        
        if reaction_key == "paid":
            reaction = RAKSH_PAID_REACTION
        elif reaction_key.startswith("custom_") and reaction_key[7:].isdigit():
            reaction = f"{RAKSH_CUSTOM_REACTION_PREFIX}{reaction_key[7:]}"
        else:
            reaction = RAKSH_REACTIONS.get(reaction_key, reaction_key)
        
        if service_type == "premium_reaction":
            available_reactions = context.user_data.get("raksh_available_reactions") or []
            if reaction_key == "random":
                reaction = "random"
            elif available_reactions and reaction not in available_reactions:
                await query.answer("⚠️ هذا التفاعل غير متاح في المنشور.", show_alert=True)
                return
        
        context.user_data["raksh_reaction"] = reaction
        context.user_data["raksh_step"] = "quantity"
        
        reaction_label = (
            RAKSH_PAID_REACTION_LABEL
            if reaction == RAKSH_PAID_REACTION
            else reaction
        )
        
        await query.edit_message_text(
            f"✅ تم اختيار التفاعل: {reaction_label}\n\n"
            f"🔢 *أرسل عدد الوحدات المطلوبة:*\n"
            f"(الحد الأقصى: {_get_max_quantity(service_type)})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="raksh_menu")]
            ])
        )
        return
    
    # ─── تمرير للخدمة المحددة ───
    # كل خدمة تفحص إذا كانت الأزرار تخصها
    for service_type, svc in RAKSH_SERVICES.items():
        prefix = f"raksh_{service_type}:"
        if data.startswith(prefix):
            parts = data[len(prefix):].split(":")
            handled = await svc.handle_callback(update, context, query, parts, user, is_own)
            if handled:
                return
    
    # ─── اختيار طريقة الدفع (الافتراضي) ───
    if data.startswith("raksh:pay:"):
        parts = data.split(":")
        if len(parts) != 5 or parts[2] not in {"stars", "points"}:
            await query.answer("⚠️ بيانات الدفع غير صالحة.", show_alert=True)
            return
        method = parts[2]
        service_type = parts[3]
        try:
            quantity = int(parts[4])
        except ValueError:
            await query.answer("⚠️ العدد غير صالح.", show_alert=True)
            return
        
        svc = RAKSH_SERVICES.get(service_type)
        if not svc or quantity < 1:
            await query.answer("⚠️ الخدمة أو العدد غير صالح.", show_alert=True)
            return
        
        request_limit = _get_request_limit(user.id, service_type)
        if quantity > request_limit:
            await query.answer(
                "⚠️ لا يمكن قبول هذا العدد حالياً. الحد المتاح: "
                f"{request_limit} وحدة.",
                show_alert=True,
            )
            return
        
        context.user_data["raksh_payment_method"] = method
        context.user_data["raksh_step"] = "payment_confirm"
        
        if method == "stars":
            total = svc.get_total(quantity, "stars")
            await query.edit_message_text(
                f"⭐ *الدفع بالنجوم*\n\n"
                f"الخدمة: {svc.config.name}\n"
                f"العدد: {quantity}\n"
                f"التكلفة: *{total} نجمة*\n\n"
                "اضغط تأكيد للمتابعة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=raksh_confirm_kb(service_type, quantity, total, "stars")
            )
        else:
            total = svc.get_total(quantity, "points")
            db_user = get_user(user.id)
            points = db_user["points"] if db_user else 0
            await query.edit_message_text(
                f"💰 *الدفع بالنقاط*\n\n"
                f"الخدمة: {svc.config.name}\n"
                f"العدد: {quantity}\n"
                f"التكلفة: *{total} نقطة*\n"
                f"رصيدك: *{points} نقطة*\n\n"
                "اضغط تأكيد للمتابعة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=raksh_confirm_kb(service_type, quantity, total, "points")
            )
        return
    
    # ─── تأكيد الطلب (الافتراضي) ───
    if data.startswith("raksh:confirm:"):
        parts = data.split(":")
        if len(parts) != 6:
            await query.answer("⚠️ بيانات التأكيد غير صالحة.", show_alert=True)
            return
        service_type = parts[2]
        try:
            quantity = int(parts[3])
            button_total = int(parts[4])
        except ValueError:
            await query.answer("⚠️ العدد أو السعر غير صالح.", show_alert=True)
            return
        payment_method = parts[5]
        
        if service_type not in RAKSH_SERVICES or payment_method not in {"points", "stars"}:
            await query.answer("⚠️ بيانات الطلب غير صالحة.", show_alert=True)
            return
        
        if quantity > _get_request_limit(user.id, service_type):
            await query.edit_message_text(
                "⚠️ لا يمكن قبول هذا الطلب حالياً. حاول لاحقاً.",
                reply_markup=raksh_menu_kb(is_own),
            )
            return
        
        total_cost = get_raksh_total(service_type, quantity, payment_method)
        if button_total != total_cost:
            logger.info(f"تحديث سعر الرشق: {service_type} {quantity}")
        
        if payment_method == "points":
            if not deduct_points(user.id, total_cost):
                current_user = get_user(user.id)
                if current_user and current_user.get("referral_points_blocked"):
                    error_text = (
                        "🔒 *تم إيقاف استخدام النقاط في حسابك مؤقتاً.*\n\n"
                        "تواصل مع الدعم لمراجعة حالة الإحالات وإعادة تفعيل الرصيد."
                    )
                else:
                    error_text = "❌ *نقاطك غير كافية!*"
                await query.edit_message_text(
                    error_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=raksh_menu_kb(is_own)
                )
                return
        else:
            # الدفع بالنجوم
            svc = RAKSH_SERVICES.get(service_type)
            total_stars = get_raksh_total(service_type, quantity, "stars")
            await query.edit_message_text(
                "⭐ *جاري تجهيز فاتورة الدفع بالنجوم...*",
                parse_mode=ParseMode.MARKDOWN,
            )
            await context.bot.send_invoice(
                chat_id=user.id,
                title=svc.config.name,
                description=f"{quantity} وحدة | {total_stars} نجمة",
                payload=f"raksh_stars:{user.id}:{service_type}:{quantity}:{total_stars}",
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice("خدمة الرشق", total_stars)],
            )
            return
        
        await _start_raksh_execution(
            update, context, query, service_type, quantity, payment_method, total_cost
        )
        return

# ════════════════════════════════════════════════════════
# ═══ 14. المعالج الرئيسي للنصوص ═══
# ════════════════════════════════════════════════════════

async def handle_raksh_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج النصوص للرشق الرئيسي"""
    user = update.effective_user
    text = update.message.text
    state = context.user_data.get("raksh_step")
    service_type = context.user_data.get("raksh_service")
    
    if not state:
        return False
    
    # ─── تعديل الأسعار (للمالك) ───
    if state == "admin_price":
        if user.id != OWNER_ID:
            _clear_raksh_state(context)
            return False
        service_type = context.user_data.get("raksh_price_edit_service")
        if service_type not in RAKSH_SERVICES:
            _clear_raksh_state(context)
            await update.message.reply_text("⚠️ انتهت جلسة تعديل الأسعار.")
            return True
        
        updates = _parse_raksh_rate_updates(text)
        if not updates:
            await update.message.reply_text(
                "⚠️ لم أفهم الصيغة.\n"
                "استخدم مثلاً:\n"
                "⭐ نجوم 1 لكل 10\n"
                "💰 نقاط 30 لكل 1",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع للأسعار", callback_data="raksh:settings")]
                ]),
            )
            return True
        
        svc = RAKSH_SERVICES[service_type]
        keys = svc.get_price_keys()
        if "stars" in updates:
            price, bundle_quantity = updates["stars"]
            set_setting(keys["stars_price"], str(price))
            set_setting(keys["stars_quantity"], str(bundle_quantity))
        if "points" in updates:
            price, bundle_quantity = updates["points"]
            set_setting(keys["points_price"], str(price))
            set_setting(keys["points_quantity"], str(bundle_quantity))
        
        config = svc.get_price_config()
        await update.message.reply_text(
            f"✅ تم حفظ أسعار {svc.label}.\n\n"
            f"⭐ {config['stars_price']} نجمة لكل {config['stars_quantity']}\n"
            f"💰 {config['points_price']} نقطة لكل {config['points_quantity']}\n\n"
            "يمكنك إرسال تعديل آخر أو اختيار خدمة أخرى.",
            reply_markup=raksh_price_settings_kb(),
        )
        return True
    
    # ─── القنوات ───
    if state == "channel":
        channel_refs = _parse_channel_refs(text)
        if text.strip() and not channel_refs:
            await update.message.reply_text(
                "⚠️ لم أتعرف على أي قناة.\n"
                "أرسل @username أو رابط t.me للقناة، ويمكنك إرسال أكثر من قناة مفصولة بمسافة أو سطر.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ]),
            )
            return True
        
        context.user_data["raksh_channels"] = channel_refs
        context.user_data["raksh_step"] = "link"
        service_type = context.user_data.get("raksh_service")
        
        await update.message.reply_text(
            f"✅ تم حفظ القنوات.\n\n"
            f"🔗 *أرسل الرابط المطلوب:*\n"
            f"{_get_link_instruction(service_type)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
            ])
        )
        return True
    
    # ─── الرابط (الافتراضي لجميع الخدمات) ───
    if state == "link":
        svc = RAKSH_SERVICES.get(service_type)
        if not svc:
            return False
        
        # تمرير للخدمة المحددة
        handled = await svc.handle_text(update, context, text, user, state, user.id == OWNER_ID)
        if handled:
            return True
        
        return False
    
    # ─── تمرير لبقية الحالات للخدمة المحددة ───
    if service_type and service_type in RAKSH_SERVICES:
        svc = RAKSH_SERVICES[service_type]
        handled = await svc.handle_text(update, context, text, user, state, user.id == OWNER_ID)
        if handled:
            return True
    
    return False

# ════════════════════════════════════════════════════════
# ═══ 15. معالجات الدفع ═══
# ════════════════════════════════════════════════════════

async def raksh_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التحقق من الدفع بالنجوم"""
    query = update.pre_checkout_query
    payload = query.invoice_payload
    
    if payload.startswith("raksh_stars:"):
        parts = payload.split(":")
        user_id = int(parts[1])
        service_type = parts[2]
        quantity = int(parts[3])
        total_stars = int(parts[4])
        
        if (
            query.from_user.id == user_id
            and query.total_amount == total_stars
            and quantity <= _get_request_limit(user_id, service_type)
        ):
            await query.answer(ok=True)
            return
    
    await query.answer(ok=False, error_message="حدث خطأ في التحقق من الدفع.")

async def raksh_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الدفع الناجح"""
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    
    if payload.startswith("raksh_stars:"):
        parts = payload.split(":")
        user_id = int(parts[1])
        service_type = parts[2]
        quantity = int(parts[3])
        total_stars = int(parts[4])
        
        if update.effective_user.id != user_id:
            return
        
        if quantity > _get_request_limit(user_id, service_type):
            try:
                await context.bot.refund_star_payment(
                    user_id=user_id,
                    telegram_payment_charge_id=payment.telegram_payment_charge_id,
                )
                await update.message.reply_text(
                    "⚠️ تعذر بدء الطلب حالياً، وتمت إعادة قيمة الدفع.",
                    reply_markup=raksh_menu_kb(user_id == OWNER_ID),
                )
            except Exception:
                logger.exception(f"فشل إعادة دفع النجوم للمستخدم {user_id}")
                await update.message.reply_text(
                    "⚠️ تعذر بدء الطلب حالياً. تواصل مع المالك.",
                    reply_markup=raksh_menu_kb(user_id == OWNER_ID),
                )
            return
        
        context.user_data["raksh_service"] = service_type
        context.user_data["raksh_quantity"] = quantity
        context.user_data["raksh_payment_method"] = "stars"
        
        await update.message.reply_text(
            "✅ *تم تأكيد الدفع بالنجوم!*\n\n"
            "⏳ جاري بدء التنفيذ...",
            parse_mode=ParseMode.MARKDOWN
        )
        await _start_raksh_execution(
            update,
            context,
            query=None,
            service_type=service_type,
            quantity=quantity,
            payment_method="stars",
            total_cost=total_stars,
            progress_message=await update.message.reply_text(
                "⏳ *يتم تشغيل الحسابات النشطة الآن...*",
                parse_mode=ParseMode.MARKDOWN,
            ),
        )

# ════════════════════════════════════════════════════════
# ═══ 16. تنفيذ الطلب ═══
# ════════════════════════════════════════════════════════

async def _send_raksh_order_to_group(bot, user_id: int, quantity: int, payment_method: str, service_type: str):
    """إرسال إشعار الطلب إلى المجموعة"""
    if not ADMIN_GROUP_ID:
        return
    try:
        await bot.send_message(
            ADMIN_GROUP_ID,
            f"📋 طلب {_raksh_order_label(service_type)}\n"
            f"👤 المستخدم: {user_id}\n"
            f"📦 العدد: {quantity}\n"
            f"💳 طريقة الدفع: {payment_method}",
        )
    except Exception:
        logger.exception("فشل إرسال إشعار الطلب")

async def _send_raksh_owner_result(
    bot,
    service_type: str,
    quantity: int,
    success_phones: List[str],
    failed_phones: List[str],
    failed_details: List[str],
):
    """إرسال النتيجة للمالك"""
    if not OWNER_ID:
        return
    try:
        lines = [
            f"📊 نتيجة {_raksh_order_label(service_type)}",
            f"📦 المطلوب: {quantity}",
            f"✅ الناجح: {len(success_phones)}",
            f"❌ الفاشل: {len(failed_phones)}",
            "",
        ]
        
        if success_phones:
            lines.append("✅ الناجحين:")
            lines.extend(f"• {p}" for p in success_phones[:20])
            if len(success_phones) > 20:
                lines.append(f"... و{len(success_phones)-20} أخرى")
        
        if failed_phones:
            lines.append("")
            lines.append("❌ الفاشلين:")
            for idx, phone in enumerate(failed_phones[:10]):
                detail = failed_details[idx] if idx < len(failed_details) else "فشل"
                lines.append(f"• {phone} — {detail[:50]}")
            if len(failed_phones) > 10:
                lines.append(f"... و{len(failed_phones)-10} أخرى")
        
        for chunk in _chunk_lines(lines):
            await bot.send_message(OWNER_ID, chunk)
    except Exception as e:
        logger.exception(f"فشل إرسال النتيجة للمالك: {e}")

async def _start_raksh_execution(
    update,
    context,
    query,
    service_type: str,
    quantity: int,
    payment_method: str,
    total_cost: int,
    progress_message=None,
):
    """بدء تنفيذ الرشق"""
    user = update.effective_user if update else query.from_user
    
    if progress_message is None:
        progress_msg = await query.edit_message_text(
            "✅ *بدأ التنفيذ...*\n\n"
            f"📊 0/{quantity}",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        progress_msg = progress_message
        await progress_msg.edit_text(
            "✅ *بدأ التنفيذ...*\n\n"
            f"📊 0/{quantity}",
            parse_mode=ParseMode.MARKDOWN,
        )
    
    svc = get_raksh_service(service_type)
    sessions = svc.get_sessions() if svc else []
    if not sessions:
        await progress_msg.edit_text(
            "❌ لا توجد حسابات متاحة.",
            reply_markup=raksh_menu_kb(user.id == OWNER_ID)
        )
        if payment_method == "points":
            add_points(user.id, total_cost)
        _clear_raksh_state(context)
        return
    
    await _send_raksh_order_to_group(
        context.bot,
        user.id,
        quantity,
        payment_method,
        service_type,
    )
    
    params = svc.get_execution_params(context) if svc else {}
    
    async def update_progress(current, total, success, failed):
        try:
            await progress_msg.edit_text(
                f"⏳ *جاري التنفيذ...*\n\n"
                f"📊 {current}/{total}\n"
                f"✅ نجح: {success}\n"
                f"❌ فشل: {failed}",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
    
    success_count, success_phones, success_details, failed_phones, failed_details = await execute_raksh_service(
        service_type=service_type,
        quantity=quantity,
        sessions=sessions,
        params=params,
        user_id=user.id,
        progress_callback=update_progress
    )
    
    await _send_raksh_owner_result(
        context.bot,
        service_type,
        quantity,
        success_phones,
        failed_phones,
        failed_details,
    )
    
    # حساب التعويض
    refund = 0
    special_count = 0
    if payment_method == "points":
        failed_refund = max(0, total_cost - get_raksh_total(service_type, success_count, "points"))
        special_count = sum(1 for msg in success_details if "بدون زر تحقق" in msg or RAKSH_NO_VERIFICATION_MESSAGE in msg)
        if special_count > 0:
            special_refund = int(get_raksh_total(service_type, special_count, "points") / 2)
            refund = failed_refund + special_refund
            if refund > 0:
                add_points(user.id, refund)
    
    # عرض النتيجة
    failed_count = quantity - success_count
    result_text = f"✅ *اكتمل الطلب!*\n\n"
    result_text += f"الخدمة: {svc.config.name if svc else service_type}\n"
    result_text += f"المطلوب: {quantity}\n"
    result_text += f"✅ المنجز: {success_count}\n"
    result_text += f"❌ الفاشل: {failed_count}\n"
    if refund > 0:
        result_text += f"💰 تم تعويضك: {refund} نقطة\n"
    if special_count > 0:
        result_text += f"🔁 استرداد نصف المبلغ لـ {special_count} حساب (بدون زر تحقق)\n"
    
    if success_phones:
        result_text += f"\n✅ *الحسابات الناجحة ({len(success_phones)}):*\n"
        result_text += "\n".join(f"• `{p}`" for p in success_phones[:10])
        if len(success_phones) > 10:
            result_text += f"\n... و{len(success_phones)-10} أخرى"
    
    if failed_details:
        result_text += f"\n\n❌ *الفاشلة ({len(failed_details)}):*\n"
        result_text += "\n".join(f"• {d[:80]}" for d in failed_details[:5])
        if len(failed_details) > 5:
            result_text += f"\n... و{len(failed_details)-5} أخرى"
    
    await progress_msg.edit_text(
        result_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb()
    )
    
    _clear_raksh_state(context)

# ════════════════════════════════════════════════════════
# ═══ 17. الأمر الرئيسي ═══
# ════════════════════════════════════════════════════════

async def cmd_raksh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الأمر /raksh"""
    user = update.effective_user
    _clear_raksh_state(context)
    
    if not (user.id == OWNER_ID) and is_user_banned(user.id):
        await update.message.reply_text("🚫 تم حظرك من استخدام هذا البوت.")
        return
    
    available_sessions = get_available_sessions_count()
    
    await update.message.reply_text(
        f"🔥 *{md_escape(get_raksh_accounts_label())}*\n\n"
        "اختر الخدمة المطلوبة:\n"
        f"📊 الحسابات المتاحة: *{available_sessions}*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=raksh_menu_kb(user.id == OWNER_ID)
    )
