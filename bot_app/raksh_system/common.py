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
RAKSH_MIN_DELAY_SECONDS = 3
RAKSH_MAX_DELAY_SECONDS = 3
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
        logger.exception(f"فشل قراءة الحد اليومي للمستخدم {user_id}")
        return RAKSH_MAX_EXECUTIONS_PER_DAY

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
    min_delay: int = 3
    max_delay: int = 3
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

__all__ = [name for name in globals() if not name.startswith("__")]
