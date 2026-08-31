"""
نظام الرشق المتقدم - منفصل تماماً عن بقية البوت
نسخة محسّنة مع دالة تحقق شاملة تستخدم تقنيات متعددة لاستخراج النص المطلوب (الكود)
مع دعم قراءة الرسائل بذكاء وإرسال الكود المكتشف
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
from typing import Optional, List, Dict, Tuple, Any
from dataclasses import dataclass
from enum import Enum

# ════════════════════════════════════════════════════════════
# ═══ 1. الثوابت والإعدادات المتقدمة ═══
# ════════════════════════════════════════════════════════════

class ServiceType(Enum):
    STORY = "story"
    FORCED_REF = "forced_ref"
    FORCED_REF_AI = "forced_ref_ai"
    COMMENT = "comment"
    POLL = "poll"
    VOTES = "votes"
    VOTES_AI = "votes_ai"
    PREMIUM_REACTION = "premium_reaction"

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

RAKSH_SERVICES: Dict[str, ServiceConfig] = {
    "story": ServiceConfig(
        name="📱 رشق مشاهدة ستوري وتفاعل",
        price_points=30,
        points_quantity=1,
        price_stars=1,
        stars_quantity=10,
        has_channel=True,
        has_reaction=True,
        has_ai=False,
        needs_link=True,
        min_delay=60,
        max_delay=180
    ),
    "forced_ref": ServiceConfig(
        name="🔑 إحالة بوت إجباري",
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
    ),
    "forced_ref_ai": ServiceConfig(
        name="🤖 إحالة بوت إجباري مع تحقق",
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
    ),
    "comment": ServiceConfig(
        name="💬 رشق تعليق",
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
    ),
    "poll": ServiceConfig(
        name="📊 رشق استفتاء",
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
    ),
    "votes": ServiceConfig(
        name="🗳 رشق أصوات",
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
    ),
    "votes_ai": ServiceConfig(
        name="🛡 رشق تصويت مع تحقق",
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
    ),
    "premium_reaction": ServiceConfig(
        name="✨ رشق تفاعل مميز",
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
    ),
}

RAKSH_SERVICE_LABELS = {
    "story": "📱 مشاهدة ستوري وتفاعل",
    "forced_ref": "🔑 إحالة بوت إجباري",
    "forced_ref_ai": "🤖 إحالة بوت إجباري مع تحقق",
    "comment": "💬 تعليق",
    "poll": "📊 استفتاء",
    "votes": "🗳 أصوات",
    "votes_ai": "🛡 تصويت مع تحقق",
    "premium_reaction": "✨ تفاعل مميز",
}

RAKSH_PRICE_KEYS = {
    service_type: {
        "points_price": f"raksh_{service_type}_points_price",
        "points_quantity": f"raksh_{service_type}_points_quantity",
        "stars_price": f"raksh_{service_type}_stars_price",
        "stars_quantity": f"raksh_{service_type}_stars_quantity",
    }
    for service_type in RAKSH_SERVICES
}

# ════════════════════════════════════════════════════════════
# ═══ 2. إدارة الجلسات والذاكرة ═══
# ════════════════════════════════════════════════════════════

_RAKSH_SESSION_LOCKS: Dict[str, asyncio.Lock] = {}
_RAKSH_VOTE_FLOW_LOCK = asyncio.Lock()
_RAKSH_SESSION_CACHE: Dict[str, Dict] = {}
_RAKSH_SESSION_CACHE_TIME: Dict[str, float] = {}
_RAKSH_SESSION_CACHE_TTL = 60  # ثانية

def _get_raksh_session_lock(phone_number: str) -> asyncio.Lock:
    """الحصول على قفل جلسة مع إدارة الذاكرة"""
    key = str(phone_number or "").strip()
    if key not in _RAKSH_SESSION_LOCKS:
        _RAKSH_SESSION_LOCKS[key] = asyncio.Lock()
    return _RAKSH_SESSION_LOCKS[key]

# ════════════════════════════════════════════════════════════
# ═══ 3. إدارة الإعدادات المحسّنة ═══
# ════════════════════════════════════════════════════════════

def _positive_setting(key: str, fallback: int) -> int:
    """قراءة إعداد مع التحقق من الصحة"""
    try:
        value = int(get_setting(key) or fallback)
        return max(1, value) if value > 0 else fallback
    except (TypeError, ValueError):
        return fallback

def get_raksh_price_config(service_type: str) -> Dict[str, int]:
    """إرجاع إعدادات الأسعار مع دعم القيم الافتراضية"""
    svc = RAKSH_SERVICES[service_type]
    keys = RAKSH_PRICE_KEYS[service_type]
    return {
        "points_price": _positive_setting(keys["points_price"], svc.price_points),
        "points_quantity": _positive_setting(keys["points_quantity"], svc.points_quantity),
        "stars_price": _positive_setting(keys["stars_price"], svc.price_stars),
        "stars_quantity": _positive_setting(keys["stars_quantity"], svc.stars_quantity),
    }

def get_raksh_total(service_type: str, quantity: int, payment_method: str) -> int:
    """حساب السعر مع التقريب للأعلى"""
    if quantity <= 0:
        return 0
    config = get_raksh_price_config(service_type)
    price_key = "stars_price" if payment_method == "stars" else "points_price"
    quantity_key = "stars_quantity" if payment_method == "stars" else "points_quantity"
    price = config[price_key]
    bundle_quantity = config[quantity_key]
    return ((quantity + bundle_quantity - 1) // bundle_quantity) * price

def _raksh_rate_text(service_type: str, payment_method: str) -> str:
    """نص عرض السعر"""
    config = get_raksh_price_config(service_type)
    if payment_method == "stars":
        return f"{config['stars_price']} نجمة لكل {config['stars_quantity']}"
    return f"{config['points_price']} نقطة لكل {config['points_quantity']}"

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

# ════════════════════════════════════════════════════════════
# ═══ 4. إدارة الحسابات المحسّنة ═══
# ════════════════════════════════════════════════════════════

def _get_sessions_for_service(service_type: str) -> List[Dict]:
    """
    جلب الجلسات المناسبة لنوع الخدمة مع التخزين المؤقت
    تم إزالة شرط raksh_only لجلب جميع الحسابات المؤهلة
    """
    # التحقق من التخزين المؤقت
    cache_key = f"sessions_{service_type}"
    if cache_key in _RAKSH_SESSION_CACHE:
        cache_time = _RAKSH_SESSION_CACHE_TIME.get(cache_key, 0)
        if time.time() - cache_time < _RAKSH_SESSION_CACHE_TTL:
            return _RAKSH_SESSION_CACHE[cache_key].copy()
    
    with db_conn() as c:
        # بناء الاستعلام بدون شرط raksh_only
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
        
        # تحديث التخزين المؤقت
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
        # مسح التخزين المؤقت
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
        # مسح التخزين المؤقت
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

# ════════════════════════════════════════════════════════════
# ═══ 5. دوال التحليل المتقدمة ═══
# ════════════════════════════════════════════════════════════

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
    
    # تقسيم النص
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
    
    # إزالة التكرار
    return list(dict.fromkeys(refs))

# ════════════════════════════════════════════════════════════
# ═══ 6. دوال التفاعل ═══
# ════════════════════════════════════════════════════════════

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

async def _fetch_raksh_reactions(
    session: Dict, post_ref: str, post_id: int
) -> List[str]:
    """جلب التفاعلات المتاحة من جلسة واحدة"""
    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS)
        if not await asyncio.wait_for(
            client.is_user_authorized(),
            timeout=RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS,
        ):
            return []
        
        post_entity = await asyncio.wait_for(
            client.get_entity(post_ref),
            timeout=RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS,
        )
        message = await asyncio.wait_for(
            client.get_messages(post_entity, ids=post_id),
            timeout=RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS,
        )
        if isinstance(message, (list, tuple)):
            message = message[0] if message else None
        
        if message:
            message_reactions = getattr(
                getattr(message, "reactions", None),
                "results",
                [],
            )
            reactions = _reaction_emoticons(
                getattr(item, "reaction", None) for item in message_reactions
            )
            if reactions:
                return reactions
        
        # محاولة جلب من إعدادات القناة
        full_channel = await asyncio.wait_for(
            client(functions.channels.GetFullChannelRequest(channel=post_entity)),
            timeout=RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS,
        )
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

async def _fetch_raksh_reactions_from_pool(
    sessions: List[Dict], post_ref: str, post_id: int
) -> List[str]:
    """جلب التفاعلات من مجموعة جلسات"""
    if not sessions:
        return []
    
    # اختيار عينة من الجلسات
    max_samples = min(RAKSH_REACTION_LOOKUP_MAX_SESSIONS, len(sessions))
    candidates = random.sample(sessions, max_samples) if max_samples > 0 else []
    
    async def lookup(session: Dict) -> List[str]:
        try:
            return await asyncio.wait_for(
                _fetch_raksh_reactions(session, post_ref, post_id),
                timeout=RAKSH_REACTION_LOOKUP_TIMEOUT_SECONDS,
            )
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

# ════════════════════════════════════════════════════════════
# ═══ 7. دوال استخراج الكود من النص (ذكاء اصطناعي مقلد) ═══
# ════════════════════════════════════════════════════════════

def _extract_code_from_text(text: str) -> Optional[str]:
    """
    استخراج الكود المطلوب من النص باستخدام عدة تقنيات:
    - البحث عن أنماط محددة (أرسل النص التالي: XXXX)
    - البحث عن كلمات مكونة من أحرف وأرقام بطول 3-50
    - تحليل السياق (تجاهل الكلمات الشائعة)
    - إرجاع الكود الأنسب
    """
    if not text:
        return None
    
    # ⚡️ تعديل: تجاهل الرسائل التي تبدأ بـ "/" أو تساوي "start"
    if text.strip().startswith("/"):
        return None
    if text.strip().lower() in {"start", "/start", "بدء"}:
        return None
    
    # قائمة الكلمات الشائعة التي يجب تجاهلها
    common_words = {
        "الآن", "أرسل", "النص", "التالي", "المرحلة", "الأولى", "بالضبط", "اكتب", "retype", 
        "type", "أدخل", "enter", "التحقق", "رابط", "الإحالة", "start", "ref", "https", "t.me",
        "مرحباً", "يجب", "إكمال", "المتابعة", "حل", "العملية", "الحسابية", "مشاركة", "جهة",
        "اتصال", "هاتف", "رقم", "الموبايل", "mobile", "phone", "contact", "share"
    }
    
    # 1. البحث عن أنماط محددة (أرسل النص التالي: XXXX)
    patterns = [
        r'(?:الآن\s*أرسل\s*النص\s*التالي|المرحلة\s*الأولى:\s*أرسل\s*النص\s*التالي\s*بالضبط|أرسل\s*النص\s*التالي|اكتب|retype|type|أدخل|enter)\s*[:\-]?\s*([A-Za-z0-9]{3,50})',
        r'النص\s*التالي\s*[:\-]?\s*([A-Za-z0-9]{3,50})',
        r'([A-Za-z0-9]{3,50})\s*$',  # نص منفصل في نهاية الرسالة
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            code = match.group(1).strip()
            if code and len(code) >= 3 and code not in common_words:
                return code
    
    # 2. البحث عن كلمات مكونة من أحرف وأرقام بطول 3-50 مع تجاهل الكلمات الشائعة
    words = re.findall(r'\b[A-Za-z0-9]{3,50}\b', text)
    if words:
        # فلترة الكلمات الشائعة
        filtered = [w for w in words if w not in common_words]
        if filtered:
            # إرجاع آخر كلمة (غالباً هي المطلوبة)
            return filtered[-1]
        else:
            # إذا كانت جميع الكلمات شائعة، نأخذ آخر كلمة
            return words[-1]
    
    # 3. البحث عن نص محاط بعلامات تنصيص أو أقواس
    quote_match = re.search(r'["\']([A-Za-z0-9]{3,50})["\']', text)
    if quote_match:
        return quote_match.group(1).strip()
    
    # 4. البحث عن سطور منفصلة تحتوي على أحرف وأرقام فقط
    lines = text.splitlines()
    for line in lines:
        line = line.strip()
        if 3 <= len(line) <= 50 and re.match(r'^[A-Za-z0-9]+$', line):
            if line not in common_words:
                return line
    
    # 5. البحث عن أي مجموعة من الأحرف والأرقام بجانب بعضها (بدون حدود كلمات)
    # قد يكون الكود ملتصقاً بكلمات أخرى
    raw_matches = re.findall(r'[A-Za-z0-9]{3,50}', text)
    if raw_matches:
        # فلترة الكلمات الشائعة
        filtered = [m for m in raw_matches if m not in common_words]
        if filtered:
            return filtered[-1]
        else:
            return raw_matches[-1]
    
    return None

# ════════════════════════════════════════════════════════════
# ═══ 8. حل التحقق الشامل - قراءة كل الرسائل بعد /start ═══
# ════════════════════════════════════════════════════════════
async def _solve_forced_ref_verification(client, bot_entity, phone_number: str) -> bool:
    """
    حل التحقق الشامل:
    - يقرأ فقط الرسائل الجديدة التي تأتي بعد آخر رسالة أرسلها الحساب (/start)
    - يستخرج الكود ويرسله
    - يحل مسألة رياضية
    - يضغط زر إيموجي
    - يشارك جهة اتصال
    - يضغط زر تحقق / متابعة
    """
    emoji_pattern = re.compile(
        "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E0-\U0001F1FF]"
    )
    
    success_keywords = ["تم", "success", "نجاح", "مبروك", "أحسنت", "تمت الإحالة", "✅", "تم التحقق", "انضممت", "اكتمل", "تم التحقق بنجاح"]
    failure_keywords = ["فشل", "خطأ", "error", "failed", "غير صحيح", "محاولة", "انتهت", "مرفوض", "invalid", "expired"]
    
    max_attempts = 50
    no_progress_count = 0
    base_id = 0

    # الخطوة 0: تحديد آخر رسالة أرسلها الحساب (لنتجاهل كل ما قبلها)
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
            logger.warning(f"تعذر قراءة رسائل البوت: {exc}")
            await asyncio.sleep(1.0)
            continue
        
        # تصفية الرسائل: نأخذ فقط الرسائل الواردة (من البوت)
        incoming_messages = [msg for msg in messages if not msg.out]
        
        if not incoming_messages:
            await asyncio.sleep(1.0)
            continue
        
        # ترتيب الرسائل
        incoming_messages.sort(key=lambda m: m.id)
        
        # ⚡️ تجاهل أي رسالة قديمة قبل /start
        new_messages = [msg for msg in incoming_messages if msg.id > base_id]
        
        if not new_messages:
            no_progress_count += 1
            if no_progress_count > 20:
                return False
            await asyncio.sleep(1.0)
            continue
        
        no_progress_count = 0
        
        # البحث عن رسالة تحتوي على طلب كود أو زر
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
        
        # فحص النجاح / الفشل
        if any(kw in text.lower() for kw in failure_keywords):
            logger.warning(f"❌ رسالة فشل ظهرت: {text[:50]}")
            return False
        if any(kw in text.lower() for kw in success_keywords) and not getattr(verification_message, 'buttons', None):
            logger.info("✅ تم التحقق بنجاح")
            return True
        
        # 1️⃣ إرسال النص المطلوب
        send_text = _extract_code_from_text(text)
        if send_text:
            logger.info(f"✅ تم إرسال النص: {send_text}")
            try:
                await client.send_message(bot_entity, send_text)
                await asyncio.sleep(1.5)
                continue
            except Exception as e:
                logger.warning(f"فشل إرسال النص: {e}")
                await asyncio.sleep(1.0)
                continue
        
        # 2️⃣ حل مسألة رياضية
        math_patterns = [
            (r'(\d+)\s*([+\-*/])\s*(\d+)\s*=\s*\?', 1, 2, 3),
            (r'(\d+)\s*([+\-*/])\s*(\d+)\s*=', 1, 2, 3),
            (r'(\d+)\s*\+\s*(\d+)\s*=', 1, 2),
            (r'(\d+)\s*\-\s*(\d+)\s*=', 1, 2),
            (r'(\d+)\s*\*\s*(\d+)\s*=', 1, 2),
            (r'(\d+)\s*\/\s*(\d+)\s*=', 1, 2),
        ]
        math_solved = False
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
                        math_solved = True
                        await asyncio.sleep(1.5)
                        break
                except Exception:
                    continue
        if math_solved:
            continue
        
        # 3️⃣ مشاركة جهة اتصال
        buttons = []
        for row in getattr(verification_message, 'buttons', None) or []:
            for btn in row:
                if not getattr(btn, 'url', None):
                    buttons.append(btn)
        
        contact_keywords = ['share', 'contact', 'هاتف', 'جهة', 'اتصال', 'مشاركة', 'mobile', 'phone', 'رقم']
        contact_btn = None
        for btn in buttons:
            btn_text = (getattr(btn, 'text', '') or '').lower()
            if any(kw in btn_text for kw in contact_keywords):
                contact_btn = btn
                break
        
        if contact_btn:
            try:
                phone = phone_number if phone_number else '1234567890'
                if not phone.startswith('+'):
                    phone = f'+{phone}'
                await client(SendMediaRequest(
                    peer=bot_entity,
                    media=InputMediaContact(
                        phone_number=phone,
                        first_name='User',
                        last_name='',
                        vcard=''
                    ),
                    message='',
                    random_id=random.randint(1, 2**31)
                ))
                logger.info(f"✅ تم مشاركة جهة الاتصال: {phone}")
            except Exception:
                try:
                    await contact_btn.click()
                except Exception:
                    pass
            await asyncio.sleep(1.0)
            continue
        
        # 4️⃣ اختيار الإيموجي الصحيح
        emoji_matches = emoji_pattern.findall(text)
        if emoji_matches:
            required_emoji = emoji_matches[-1]
            emoji_btn = None
            for btn in buttons:
                btn_text = getattr(btn, 'text', '') or ''
                if required_emoji in btn_text:
                    emoji_btn = btn
                    break
            
            if emoji_btn:
                try:
                    await emoji_btn.click()
                    logger.info(f"✅ تم اختيار الإيموجي: {required_emoji}")
                except Exception:
                    pass
                await asyncio.sleep(1.0)
                continue
            else:
                for btn in buttons:
                    btn_text = getattr(btn, 'text', '') or ''
                    if emoji_pattern.search(btn_text):
                        try:
                            await btn.click()
                        except Exception:
                            pass
                        await asyncio.sleep(1.0)
                        break
                continue
        
        # 5️⃣ ضغط زر تحقق / متابعة
        verify_keywords = ['تحقق', 'verify', 'متابعة', 'continue', 'التالي', 'next', 'تأكيد', 'confirm', 'ok', 'تم', 'done']
        verify_btn = None
        for btn in buttons:
            btn_text = (getattr(btn, 'text', '') or '').lower()
            if any(kw in btn_text for kw in verify_keywords):
                verify_btn = btn
                break
        
        if verify_btn:
            try:
                await verify_btn.click()
                logger.info(f"✅ تم الضغط على زر التحقق: {getattr(verify_btn, 'text', '')}")
            except Exception:
                pass
            await asyncio.sleep(1.0)
            continue
        
        # إذا لم نفهم شيئاً، ننتظر
        await asyncio.sleep(2.0)
    
    return False

async def _join_discussion_group(client, discussion):
    """الانضمام لمجموعة النقاش"""
    messages = getattr(discussion, "messages", None) or []
    if not messages:
        raise RuntimeError("المنشور لا يملك نقاشاً")
    
    discussion_message = messages[0]
    peer = getattr(discussion_message, "peer_id", None)
    channel_id = getattr(peer, "channel_id", None)
    chats = getattr(discussion, "chats", None) or []
    discussion_chat = next(
        (chat for chat in chats if getattr(chat, "id", None) == channel_id),
        None,
    )
    if discussion_chat is None:
        raise RuntimeError("تعذر تحديد مجموعة النقاش")
    
    try:
        await client(JoinChannelRequest(discussion_chat))
    except Exception as exc:
        if "USER_ALREADY_PARTICIPANT" not in str(exc).upper():
            raise
    return discussion_chat

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

# ─── تنفيذ خدمات محددة ───

async def _execute_story(session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
    """تنفيذ رشق ستوري"""
    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            _mark_raksh_session_unauthorized(session.get("phone_number"))
            return False, "الجلسة غير مصرح بها"
        
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        
        entity_ref, story_id = _parse_story_link(params["link"])
        if not entity_ref or not story_id:
            return False, "رابط الستوري غير صحيح"
        
        entity = await client.get_entity(entity_ref)
        await client(IncrementStoryViewsRequest(peer=entity, id=story_id))
        
        reaction = params.get("reaction")
        if not reaction or reaction == "random":
            reaction = random.choice(list(RAKSH_REACTIONS.values()))
        
        try:
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
            return True, f"✅ تمت المشاهدة من {session['phone_number']} (تعذر التفاعل)"
    except Exception as e:
        return False, f"❌ فشل: {str(e)}"
    finally:
        await client.disconnect()

async def _execute_forced_ref(session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
    """تنفيذ إحالة بوت إجباري (بدون تحقق)"""
    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
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

async def _execute_forced_ref_ai(session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
    """
    تنفيذ إحالة بوت إجباري مع تحقق شامل.
    - ينضم للقنوات الإجبارية
    - يضغط رابط البوت (مرة واحدة فقط)
    - يحل جميع أنواع التحقق
    - يعتبر النجاح عند اختفاء الأزرار وظهور رسالة نجاح
    """
    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            _mark_raksh_session_unauthorized(session.get("phone_number"))
            return False, "الجلسة غير مصرح بها"
        
        # 1. الانضمام للقنوات الإجبارية
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        
        # 2. تحليل رابط البوت
        bot_username, start_param = _parse_bot_link(params["link"])
        if not bot_username:
            return False, "رابط البوت غير صحيح"
        
        clean_username = bot_username.lstrip("@").strip()
        resolved = await client(ResolveUsernameRequest(clean_username))
        bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]
        
        # 3. الضغط على رابط البوت (مرة واحدة فقط)
        await client(StartBotRequest(
            bot=bot_entity,
            peer=bot_entity,
            start_param=start_param or ""
        ))
        await asyncio.sleep(2.0)  # انتظار وصول الرسائل
        
        # 4. حل التحقق الشامل
        success = await _solve_forced_ref_verification(client, bot_entity, session.get("phone_number"))
        
        if success:
            return True, f"✅ تمت الإحالة مع التحقق من {session['phone_number']}"
        else:
            return False, "فشل التحقق بعد محاولات متعددة"
    except Exception as e:
        return False, f"❌ فشل: {str(e)}"
    finally:
        await client.disconnect()

async def _execute_comment(session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
    """تنفيذ رشق تعليق"""
    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
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

async def _execute_poll(session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
    """تنفيذ رشق استفتاء"""
    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
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

async def _execute_votes(session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
    """تنفيذ رشق أصوات"""
    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            _mark_raksh_session_unauthorized(session.get("phone_number"))
            return False, "الجلسة غير مصرح بها"
        
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        
        # التحليل المخصص لروابط التصويت
        link = params["link"]
        # محاولة تحليل كرابط منشور عادي
        channel_ref, msg_id = _parse_post_link(link)
        if not channel_ref:
            # محاولة تحليل كرابط بوت
            bot_username, start_param = _parse_bot_link(link)
            if bot_username:
                # معالجة خاصة لروابط التصويت عبر البوتات
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
        
        # العثور على زر التصويت
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

async def _execute_votes_ai(session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
    """تنفيذ رشق تصويت مع تحقق شامل"""
    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            _mark_raksh_session_unauthorized(session.get("phone_number"))
            return False, "الجلسة غير مصرح بها"
        
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        
        link = params["link"]
        # محاولة تحليل كرابط بوت
        bot_username, start_param = _parse_bot_link(link)
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
        
        # حل التحقق الشامل
        success = await _solve_forced_ref_verification(client, bot_entity, session.get("phone_number"))
        
        if success:
            return True, f"✅ تم التصويت مع التحقق من {session['phone_number']}"
        else:
            return False, "فشل التحقق"
    except Exception as e:
        return False, f"❌ فشل التصويت: {str(e)}"
    finally:
        await client.disconnect()

async def _execute_premium_reaction(session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
    """تنفيذ رشق تفاعل مميز"""
    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
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
        
        # التحقق من أن التفاعل مسموح
        if reaction == RAKSH_PAID_REACTION:
            # تفاعل مدفوع
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
            # تفاعل عادي
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

# ════════════════════════════════════════════════════════════
# ═══ 10. مدير التنفيذ الرئيسي ═══
# ════════════════════════════════════════════════════════════

EXECUTORS = {
    "story": _execute_story,
    "forced_ref": _execute_forced_ref,
    "forced_ref_ai": _execute_forced_ref_ai,
    "comment": _execute_comment,
    "poll": _execute_poll,
    "votes": _execute_votes,
    "votes_ai": _execute_votes_ai,
    "premium_reaction": _execute_premium_reaction,
}

def _raksh_order_label(service_type: str) -> str:
    """اسم مختصر للطلب"""
    labels = {
        "comment": "تعليقات",
        "poll": "استفتاء",
        "story": "مشاهدات ستوري",
        "forced_ref": "إحالات",
        "forced_ref_ai": "إحالات بتحقق",
        "votes": "أصوات",
        "votes_ai": "أصوات بتحقق",
        "premium_reaction": "تفاعلات مميزة",
    }
    return labels.get(service_type, service_type)

def _get_delay_seconds(service_type: str, custom_delay: Optional[int] = None) -> int:
    """حساب الفاصل الزمني بين التنفيذات"""
    svc = RAKSH_SERVICES.get(service_type)
    if not svc:
        return random.randint(RAKSH_MIN_DELAY_SECONDS, RAKSH_MAX_DELAY_SECONDS)
    
    if custom_delay is not None:
        return max(0, min(custom_delay, 86400))
    
    if svc.min_delay == svc.max_delay:
        return svc.min_delay
    return random.randint(svc.min_delay, svc.max_delay)

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
            
            # التحقق من الحد اليومي
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
            
            # التحقق من الحد الساعي
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

async def execute_raksh_service(
    service_type: str,
    quantity: int,
    sessions: List[Dict],
    params: Dict,
    user_id: int,
    progress_callback=None,
) -> Tuple[int, List[str], List[str], List[str], List[str]]:
    """
    تنفيذ طلب رشق
    
    Returns:
        success_count, success_phones, success_details, failed_phones, failed_details
    """
    if not sessions:
        raise RuntimeError("لا توجد جلسات نشطة متاحة")
    
    executor = EXECUTORS.get(service_type)
    if not executor:
        raise RuntimeError(f"خدمة غير معروفة: {service_type}")
    
    svc = RAKSH_SERVICES.get(service_type)
    max_concurrent = svc.max_concurrent if svc else 1
    
    shuffled = sessions.copy()
    random.shuffle(shuffled)
    
    success_count = 0
    success_phones = []
    success_details = []
    failed_phones = []
    failed_details = []
    used_phones = set()
    
    # معالجة الخدمات المتسلسلة
    if max_concurrent == 1 or service_type in {"votes_ai", "forced_ref", "forced_ref_ai"}:
        if service_type == "votes_ai":
            async with _RAKSH_VOTE_FLOW_LOCK:
                return await _execute_raksh_sequential(
                    executor, shuffled, params, user_id,
                    quantity, progress_callback, service_type
                )
        
        return await _execute_raksh_sequential(
            executor, shuffled, params, user_id,
            quantity, progress_callback, service_type
        )
    
    # معالجة الخدمات المتوازية
    return await _execute_raksh_parallel(
        executor, shuffled, params, user_id,
        quantity, progress_callback, service_type, max_concurrent
    )

async def _execute_raksh_sequential(
    executor,
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
                ok, msg = await executor(
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
            delay = _get_delay_seconds(service_type, params.get("delay_seconds"))
            await asyncio.sleep(delay)
    
    await _remove_invalid_raksh_sessions(failed_phones)
    return success_count, success_phones, success_details, failed_phones, failed_details

async def _execute_raksh_parallel(
    executor,
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
                ok, msg = await executor(
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

# ════════════════════════════════════════════════════════════
# ═══ 11. واجهات المستخدم ═══
# ════════════════════════════════════════════════════════════

def _is_raksh_service_enabled(service_type: str) -> bool:
    """التحقق من تفعيل الخدمة"""
    return get_setting(f"raksh_service_enabled_{service_type}").strip().lower() not in {
        "0", "false", "off", "hidden", "disabled"
    }

def _set_raksh_service_enabled(service_type: str, enabled: bool) -> None:
    """تفعيل/إخفاء خدمة"""
    set_setting(f"raksh_service_enabled_{service_type}", "1" if enabled else "0")

def raksh_menu_kb(is_owner: bool = False):
    """قائمة الخدمات"""
    buttons = []
    for key, svc in RAKSH_SERVICES.items():
        if not is_owner and not _is_raksh_service_enabled(key):
            continue
        service_button = InlineKeyboardButton(
            svc.name, callback_data=f"raksh:start:{key}"
        )
        if is_owner:
            enabled = _is_raksh_service_enabled(key)
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
    for service_type, label in RAKSH_SERVICE_LABELS.items():
        config = get_raksh_price_config(service_type)
        rows.append([
            InlineKeyboardButton(
                f"{label}: ⭐ {config['stars_price']}/{config['stars_quantity']} | "
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

# ════════════════════════════════════════════════════════════
# ═══ 12. دوال مساعدة للواجهة ═══
# ════════════════════════════════════════════════════════════

def _get_link_instruction(service_type: str) -> str:
    """تعليمات الرابط حسب الخدمة"""
    instructions = {
        "story": "https://t.me/username/s/123 أو https://t.me/username/story/123",
        "forced_ref": "@BotUsername start123  أو  t.me/BotUsername?start=123",
        "forced_ref_ai": "@BotUsername start123  أو  t.me/BotUsername?start=123",
        "comment": "https://t.me/channel/123",
        "poll": "https://t.me/channel/123",
        "votes": "https://t.me/channel/123 أو رابط بوت تصويت",
        "votes_ai": "https://t.me/i8YYBot?start=compvote_xxx",
        "premium_reaction": "https://t.me/channel/123",
    }
    return instructions.get(service_type, "أرسل الرابط المطلوب")

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
    if not value.strip():
        return "⚠️ الرابط لا يمكن أن يكون فارغاً"
    
    if service_type in {"forced_ref", "forced_ref_ai"}:
        bot_username, _ = _parse_bot_link(value)
        if not bot_username:
            return (
                "⚠️ رابط البوت غير صحيح.\n\n"
                "أرسله بهذا الشكل:\n"
                "@BotUsername start123\n"
                "أو: t.me/BotUsername?start=123"
            )
        return None
    
    if service_type == "story":
        if not all(_parse_story_link(value)):
            return (
                "⚠️ رابط الستوري غير صحيح.\n\n"
                "أرسله بهذا الشكل:\n"
                "https://t.me/username/s/123"
            )
        return None
    
    if service_type == "votes_ai":
        # التحقق من وجود @ أو t.me
        if not ("@" in value or "t.me/" in value):
            return "⚠️ الرابط يجب أن يحتوي على @username أو t.me/"
        return None
    
    # الخدمات العادية
    if not all(_parse_post_link(value)):
        return (
            "⚠️ الرابط غير صحيح لهذه الخدمة.\n\n"
            f"أرسل الرابط بهذا الشكل:\n{_get_link_instruction(service_type)}"
        )
    return None

def _get_max_quantity(service_type: str) -> int:
    """الحد الأقصى للكمية"""
    return get_available_sessions_count(service_type)

def _get_request_limit(user_id: int, service_type: str) -> int:
    """الحد الفعلي للطلب"""
    return min(
        _get_max_quantity(service_type),
        get_raksh_hourly_remaining(user_id),
        get_raksh_daily_remaining(user_id),
    )

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

# ════════════════════════════════════════════════════════════
# ═══ 13. معالج الأزرار الرئيسي ═══
# ════════════════════════════════════════════════════════════

async def handle_raksh_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query=None,
    data=None,
    user=None,
    is_own=None,
):
    """معالج أزرار الرشق"""
    query = query or update.callback_query
    data = query.data if data is None else data
    user = user or query.from_user
    is_own = (user.id == OWNER_ID) if is_own is None else is_own
    
    await query.answer()
    
    # تفعيل/إخفاء خدمة
    if data.startswith("raksh:toggle:"):
        if not is_own:
            await query.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
            return
        service_type = data.split(":", 2)[2]
        if service_type not in RAKSH_SERVICES:
            await query.answer("⚠️ الخدمة غير موجودة.", show_alert=True)
            return
        enabled = not _is_raksh_service_enabled(service_type)
        _set_raksh_service_enabled(service_type, enabled)
        await query.edit_message_text(
            f"🔥 *إدارة {md_escape(get_raksh_accounts_label())}*\n\n"
            "✅ مفعلة: تظهر للأعضاء\n"
            "🚫 مخفية: لا تظهر للأعضاء\n\n"
            f"📊 الحسابات المتاحة: *{get_available_sessions_count()}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_menu_kb(True),
        )
        return
    
    # إدارة الأسعار
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
    
    # تعديل سعر خدمة
    if data.startswith("raksh:price:"):
        if not is_own:
            await query.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
            return
        service_type = data.split(":")[2]
        if service_type not in RAKSH_SERVICES:
            await query.answer("⚠️ الخدمة غير موجودة.", show_alert=True)
            return
        config = get_raksh_price_config(service_type)
        context.user_data["raksh_price_edit_service"] = service_type
        context.user_data["raksh_step"] = "admin_price"
        await query.edit_message_text(
            f"✏️ *تعديل سعر {RAKSH_SERVICE_LABELS[service_type]}*\n\n"
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
    
    # القائمة الرئيسية
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
    
    # بدء خدمة
    if data.startswith("raksh:start:"):
        service_type = data.split(":")[2]
        svc = RAKSH_SERVICES.get(service_type)
        if not svc:
            await query.edit_message_text(
                "⚠️ خدمة غير موجودة.",
                reply_markup=raksh_menu_kb(is_own),
            )
            return
        if not is_own and not _is_raksh_service_enabled(service_type):
            await query.edit_message_text(
                "⚠️ هذه الخدمة مخفية حالياً.",
                reply_markup=raksh_menu_kb(False),
            )
            return
        
        _clear_raksh_state(context)
        context.user_data["raksh_service"] = service_type
        context.user_data["raksh_step"] = "channel"
        
        await query.edit_message_text(
            f"{svc.name}\n\n"
            f"💰 السعر: {_raksh_rate_text(service_type, 'points')}\n"
            f"⭐ السعر: {_raksh_rate_text(service_type, 'stars')}\n\n"
            "📢 *أرسل القنوات الإجبارية:*\n"
            "يمكنك إرسال أكثر من قناة، كل قناة في سطر أو مفصولة بمسافة\n"
            "مثال: @channel1\n@channel2\n\n"
            "أو اضغط تخطي:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_channel_kb()
        )
        return
    
    # تخطي القنوات
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
    
    # اختيار تفاعل
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
    
    # اختيار طريقة الدفع
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
            total = get_raksh_total(service_type, quantity, "stars")
            await query.edit_message_text(
                f"⭐ *الدفع بالنجوم*\n\n"
                f"الخدمة: {svc.name}\n"
                f"العدد: {quantity}\n"
                f"التكلفة: *{total} نجمة*\n\n"
                "اضغط تأكيد للمتابعة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=raksh_confirm_kb(service_type, quantity, total, "stars")
            )
        else:
            total = get_raksh_total(service_type, quantity, "points")
            db_user = get_user(user.id)
            points = db_user["points"] if db_user else 0
            await query.edit_message_text(
                f"💰 *الدفع بالنقاط*\n\n"
                f"الخدمة: {svc.name}\n"
                f"العدد: {quantity}\n"
                f"التكلفة: *{total} نقطة*\n"
                f"رصيدك: *{points} نقطة*\n\n"
                "اضغط تأكيد للمتابعة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=raksh_confirm_kb(service_type, quantity, total, "points")
            )
        return
    
    # تأكيد الطلب
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
                title=svc.name,
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

# ════════════════════════════════════════════════════════════
# ═══ 14. معالج النصوص ═══
# ════════════════════════════════════════════════════════════

async def handle_raksh_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج النصوص للرشق"""
    user = update.effective_user
    text = update.message.text
    state = context.user_data.get("raksh_step")
    
    if not state:
        return False
    
    # تعديل الأسعار
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
        
        keys = RAKSH_PRICE_KEYS[service_type]
        if "stars" in updates:
            price, bundle_quantity = updates["stars"]
            set_setting(keys["stars_price"], str(price))
            set_setting(keys["stars_quantity"], str(bundle_quantity))
        if "points" in updates:
            price, bundle_quantity = updates["points"]
            set_setting(keys["points_price"], str(price))
            set_setting(keys["points_quantity"], str(bundle_quantity))
        
        config = get_raksh_price_config(service_type)
        await update.message.reply_text(
            f"✅ تم حفظ أسعار {RAKSH_SERVICE_LABELS[service_type]}.\n\n"
            f"⭐ {config['stars_price']} نجمة لكل {config['stars_quantity']}\n"
            f"💰 {config['points_price']} نقطة لكل {config['points_quantity']}\n\n"
            "يمكنك إرسال تعديل آخر أو اختيار خدمة أخرى.",
            reply_markup=raksh_price_settings_kb(),
        )
        return True
    
    # القنوات
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
    
    # الرابط
    if state == "link":
        service_type = context.user_data.get("raksh_service")
        svc = RAKSH_SERVICES.get(service_type)
        
        link_error = _raksh_link_error(service_type, text)
        if link_error:
            await update.message.reply_text(
                link_error,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ]),
            )
            return True
        
        context.user_data["raksh_link"] = text
        
        # خدمات خاصة
        if service_type in {"votes_ai", "forced_ref_ai"}:
            context.user_data["raksh_step"] = "quantity"
            max_qty = _get_request_limit(user.id, service_type)
            if max_qty < 1:
                await update.message.reply_text(
                    "⚠️ لا توجد حسابات متاحة حالياً.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True
            await update.message.reply_text(
                f"✅ تم حفظ الرابط.\n\n"
                f"🔢 *أرسل عدد الوحدات المطلوبة:*\n"
                f"(الحد الأقصى: {max_qty})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        # خدمات تحتاج تفاعل
        if svc and svc.has_reaction:
            if service_type == "premium_reaction":
                post_ref, post_id = _parse_post_link(text)
                if not post_ref or post_id is None:
                    await update.message.reply_text(
                        "⚠️ تعذر تحليل رابط المنشور."
                    )
                    return True
                reaction_options = await _fetch_raksh_reactions_from_pool(
                    _get_sessions_for_service(service_type),
                    post_ref,
                    post_id,
                )
                if not reaction_options:
                    await update.message.reply_text(
                        "⚠️ تعذر قراءة التفاعلات المتاحة في هذا المنشور."
                    )
                    return True
                context.user_data["raksh_available_reactions"] = reaction_options
            
            context.user_data["raksh_step"] = "reaction"
            await update.message.reply_text(
                f"✅ تم حفظ الرابط.\n\n"
                f"😊 *اختر التفاعل المطلوب:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=raksh_reaction_kb(
                    service_type,
                    context.user_data.get("raksh_available_reactions")
                )
            )
            return True
        
        # خدمات تحتاج تعليق
        if service_type == "comment":
            context.user_data["raksh_step"] = "comment_text"
            await update.message.reply_text(
                f"✅ تم حفظ الرابط.\n\n"
                f"💬 *أرسل نص التعليق:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        # خدمات تحتاج خيار استفتاء
        if service_type == "poll":
            context.user_data["raksh_step"] = "poll_option"
            await update.message.reply_text(
                f"✅ تم حفظ الرابط.\n\n"
                f"🔢 *أرسل رقم الخيار المطلوب:*\n"
                f"(مثال: 1 أو 2 أو 3)",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        # خدمات عادية
        context.user_data["raksh_step"] = "quantity"
        max_qty = _get_request_limit(user.id, service_type)
        if max_qty < 1:
            await update.message.reply_text(
                "⚠️ لا توجد حسابات متاحة حالياً.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ]),
            )
            return True
        await update.message.reply_text(
            f"✅ تم حفظ الرابط.\n\n"
            f"🔢 *أرسل عدد الوحدات المطلوبة:*\n"
            f"(الحد الأقصى: {max_qty})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
            ])
        )
        return True
    
    # تعليق
    if state == "comment_text":
        context.user_data["raksh_comment"] = text
        context.user_data["raksh_step"] = "quantity"
        service_type = context.user_data.get("raksh_service")
        max_qty = _get_request_limit(user.id, service_type)
        if max_qty < 1:
            await update.message.reply_text(
                "⚠️ لا توجد حسابات متاحة حالياً.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ]),
            )
            return True
        await update.message.reply_text(
            f"✅ تم حفظ التعليق.\n\n"
            f"🔢 *أرسل عدد الوحدات المطلوبة:*\n"
            f"(الحد الأقصى: {max_qty})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
            ])
        )
        return True
    
    # خيار الاستفتاء
    if state == "poll_option":
        normalized = _normalize_digits(text.strip())
        if not normalized.isdigit():
            await update.message.reply_text(
                "⚠️ أرسل رقماً صحيحاً (مثال: 1 أو 2 أو 3).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ]),
            )
            return True
        context.user_data["raksh_poll_option"] = normalized
        context.user_data["raksh_step"] = "quantity"
        service_type = context.user_data.get("raksh_service")
        max_qty = _get_request_limit(user.id, service_type)
        if max_qty < 1:
            await update.message.reply_text(
                "⚠️ لا توجد حسابات متاحة حالياً.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ]),
            )
            return True
        await update.message.reply_text(
            f"✅ تم حفظ الخيار {normalized}.\n\n"
            f"🔢 *أرسل عدد الوحدات المطلوبة:*\n"
            f"(الحد الأقصى: {max_qty})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
            ])
        )
        return True
    
    # الفاصل الزمني
    if state == "delay":
        service_type = context.user_data.get("raksh_service")
        if service_type not in {"forced_ref", "forced_ref_ai", "votes_ai"} or user.id != OWNER_ID:
            context.user_data["raksh_step"] = "quantity"
            return True
        try:
            delay_seconds = int(text.strip())
        except ValueError:
            await update.message.reply_text("⚠️ أرسل عدد الثواني كرقم صحيح، مثل 3")
            return True
        if delay_seconds < 0 or delay_seconds > 86400:
            await update.message.reply_text("⚠️ أدخل رقماً بين 0 و 86400 ثانية.")
            return True
        context.user_data["raksh_delay_seconds"] = delay_seconds
        quantity = int(context.user_data.get("raksh_quantity", 1))
        svc = RAKSH_SERVICES.get(service_type)
        points_cost = get_raksh_total(service_type, quantity, "points")
        stars_cost = get_raksh_total(service_type, quantity, "stars")
        context.user_data["raksh_step"] = "payment"
        await update.message.reply_text(
            f"✅ تم ضبط الفاصل: {delay_seconds} ثانية.\n\n"
            f"📋 *مراجعة الطلب*\n\n"
            f"الخدمة: {svc.name}\n"
            f"العدد: {quantity}\n"
            f"💰 السعر بالنقاط: {points_cost} نقطة\n"
            f"⭐ السعر بالنجوم: {stars_cost} نجمة\n\n"
            f"اختر طريقة الدفع:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_payment_kb(service_type, quantity, points_cost, stars_cost)
        )
        return True
    
    # الكمية
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
        
        service_type = context.user_data.get("raksh_service")
        max_qty = _get_request_limit(user.id, service_type)
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
        
        service_type = context.user_data.get("raksh_service")
        svc = RAKSH_SERVICES.get(service_type)
        points_cost = get_raksh_total(service_type, quantity, "points")
        stars_cost = get_raksh_total(service_type, quantity, "stars")
        
        context.user_data["raksh_quantity"] = quantity
        
        # المالك يضبط الفاصل
        if user.id == OWNER_ID and service_type in {"forced_ref", "forced_ref_ai", "votes_ai"}:
            context.user_data["raksh_step"] = "delay"
            delay_hint = (
                "للأعضاء يُطبّق فاصل تلقائي عشوائي بين 60 و180 ثانية."
                if service_type == "votes_ai"
                else "للأعضاء يبقى الوقت ثابتاً: 180 ثانية."
            )
            await update.message.reply_text(
                "⏱️ *إعداد الفاصل الزمني*\n\n"
                "أرسل عدد الثواني بين تفعيل حساب وآخر.\n"
                f"{delay_hint}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        context.user_data["raksh_step"] = "payment"
        await update.message.reply_text(
            f"📋 *مراجعة الطلب*\n\n"
            f"الخدمة: {svc.name}\n"
            f"العدد: {quantity}\n"
            f"💰 السعر بالنقاط: {points_cost} نقطة\n"
            f"⭐ السعر بالنجوم: {stars_cost} نجمة\n\n"
            f"اختر طريقة الدفع:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_payment_kb(service_type, quantity, points_cost, stars_cost)
        )
        return True
    
    # الدفع
    if state in {"payment", "payment_confirm"}:
        normalized = re.sub(r"[\s_\-]+", "", (text or "").casefold())
        if normalized in {"نقاط", "النقاط", "بالنقاط", "points", "point"}:
            method = "points"
        elif normalized in {"نجوم", "النجوم", "بالنجوم", "stars", "star"}:
            method = "stars"
        else:
            await update.message.reply_text(
                "⚠️ اكتب «نقاط» أو «نجوم»، أو اختر أحد الزرين الظاهرين.",
                reply_markup=raksh_payment_kb(
                    context.user_data.get("raksh_service"),
                    context.user_data.get("raksh_quantity", 1),
                    get_raksh_total(
                        context.user_data.get("raksh_service"),
                        context.user_data.get("raksh_quantity", 1),
                        "points",
                    ),
                    get_raksh_total(
                        context.user_data.get("raksh_service"),
                        context.user_data.get("raksh_quantity", 1),
                        "stars",
                    ),
                ),
            )
            return True
        
        service_type = context.user_data.get("raksh_service")
        quantity = int(context.user_data.get("raksh_quantity", 1))
        svc = RAKSH_SERVICES[service_type]
        total = get_raksh_total(service_type, quantity, method)
        context.user_data["raksh_payment_method"] = method
        
        if method == "points":
            if not deduct_points(user.id, total):
                await update.message.reply_text(
                    f"❌ نقاطك غير كافية.\nالتكلفة: {total} نقطة.",
                    reply_markup=raksh_menu_kb(user.id == OWNER_ID),
                )
                _clear_raksh_state(context)
                return True
            
            progress_message = await update.message.reply_text(
                f"✅ تم الدفع بالنقاط وخصم {total} نقطة.\n"
                "⏳ جاري التنفيذ..."
            )
            await _start_raksh_execution(
                update,
                context,
                query=None,
                service_type=service_type,
                quantity=quantity,
                payment_method="points",
                total_cost=total,
                progress_message=progress_message,
            )
            return True
        
        context.user_data["raksh_step"] = "payment_confirm"
        await update.message.reply_text(
            f"✅ تم اختيار الدفع بالنجوم.\n\n"
            f"الخدمة: {svc.name}\n"
            f"العدد: {quantity}\n"
            f"التكلفة: {total} نجمة\n\n"
            "اضغط «تأكيد الطلب» للبدء.",
            reply_markup=raksh_confirm_kb(service_type, quantity, total, method),
        )
        return True
    
    return False

# ════════════════════════════════════════════════════════════
# ═══ 15. معالجات الدفع ═══
# ════════════════════════════════════════════════════════════

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

# ════════════════════════════════════════════════════════════
# ═══ 16. تنفيذ الطلب ═══
# ════════════════════════════════════════════════════════════

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
    
    sessions = _get_sessions_for_service(service_type)
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
    
    params = {
        "channel_ref": context.user_data.get("raksh_channels"),
        "reaction": context.user_data.get("raksh_reaction"),
        "available_reactions": context.user_data.get("raksh_available_reactions"),
        "link": context.user_data.get("raksh_link"),
        "comment_text": context.user_data.get("raksh_comment"),
        "poll_option": context.user_data.get("raksh_poll_option"),
        "delay_seconds": context.user_data.get("raksh_delay_seconds"),
    }
    
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
    result_text += f"الخدمة: {RAKSH_SERVICES[service_type].name}\n"
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

# ════════════════════════════════════════════════════════════
# ═══ 17. الأمر الرئيسي ═══
# ════════════════════════════════════════════════════════════

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
