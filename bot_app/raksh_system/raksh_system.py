"""
نظام الرشق الجديد - منفصل تماماً عن بقية البوت

الخدمات المتوفرة:
1. رشق مشاهدة ستوري وتفاعل
2. إحالة بوت إجباري
3. إحالة بوت إجباري مع تحقق
4. رشق تعليق
5. رشق استفتاء
6. رشق أصوات
7. رشق تصويت مع تحقق
8. رشق تفاعل مميز
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
from telethon.tl.functions.messages import ImportChatInviteRequest, SendVoteRequest, StartBotRequest, GetBotCallbackAnswerRequest
from telethon.tl.functions.contacts import ResolveUsernameRequest
from telethon.tl.functions.stories import IncrementStoryViewsRequest, SendReactionRequest
from telethon.tl.types import ReactionEmoji
from urllib.parse import parse_qs, urlparse
import random
import asyncio
import re

RAKSH_PAID_REACTION = "__raksh_paid_reaction__"
RAKSH_PAID_REACTION_LABEL = "⭐ تفاعل مدفوع"
RAKSH_CUSTOM_REACTION_PREFIX = "__raksh_custom_reaction__:"
RAKSH_REACTION_LOOKUP_MAX_SESSIONS = 3
RAKSH_REACTION_LOOKUP_TIMEOUT_SECONDS = 5
RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS = 4

# يمنع تشغيل نفس جلسة Telegram بالتوازي داخل نفس العملية. لا يغني هذا
# عن إيقاف نسخة قديمة من التطبيق على خادم آخر؛ Telegram لا يسمح باستخدام
# authorization key نفسه من عمليتين/عنواني IP مختلفين.
_RAKSH_SESSION_LOCKS: dict[str, asyncio.Lock] = {}

# عدد الحسابات التي ستعمل بالتوازي في قسم "تصويت يحتوي تحقق"
RAKSH_VOTE_CONCURRENT = 5  # تم تقليله من 10 إلى 5 لتجنب Rate Limit

def _get_raksh_session_lock(phone_number: str) -> asyncio.Lock:
    key = str(phone_number or "").strip()
    lock = _RAKSH_SESSION_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _RAKSH_SESSION_LOCKS[key] = lock
    return lock

# ════════════════════════════════════════════════════════════
# ═══ 1. ثوابت الخدمات ═══
# ════════════════════════════════════════════════════════════

RAKSH_SERVICES = {
    "story": {
        "name": "📱 رشق مشاهدة ستوري وتفاعل",
        "price_points": 30,
        "points_quantity": 1,
        "price_stars": 1,
        "stars_quantity": 10,
        "has_channel": True,
        "has_reaction": True,
        "has_ai": False,
        "needs_link": True,
    },
    "forced_ref": {
        "name": "🔑 إحالة بوت إجباري",
        "price_points": 250,
        "points_quantity": 1,
        "price_stars": 10,
        "stars_quantity": 1,
        "has_channel": True,
        "has_reaction": False,
        "has_ai": False,
        "needs_link": True,
    },
    "forced_ref_ai": {
        "name": "🤖 إحالة بوت إجباري مع تحقق",
        "price_points": 300,
        "points_quantity": 1,
        "price_stars": 15,
        "stars_quantity": 1,
        "has_channel": True,
        "has_reaction": False,
        "has_ai": True,
        "needs_link": True,
    },
    "comment": {
        "name": "💬 رشق تعليق",
        "price_points": 30,
        "points_quantity": 1,
        "price_stars": 5,
        "stars_quantity": 1,
        "has_channel": True,
        "has_reaction": False,
        "has_ai": False,
        "needs_link": True,
    },
    "poll": {
        "name": "📊 رشق استفتاء",
        "price_points": 30,
        "points_quantity": 1,
        "price_stars": 5,
        "stars_quantity": 1,
        "has_channel": True,
        "has_reaction": False,
        "has_ai": False,
        "needs_link": True,
    },
    "votes": {
        "name": "🗳 رشق أصوات",
        "price_points": 20,
        "points_quantity": 1,
        "price_stars": 4,
        "stars_quantity": 1,
        "has_channel": True,
        "has_reaction": False,
        "has_ai": False,
        "needs_link": True,
    },
    "votes_ai": {
        "name": "🛡 رشق تصويت مع تحقق",
        "price_points": 50,
        "points_quantity": 1,
        "price_stars": 10,
        "stars_quantity": 1,
        "has_channel": True,
        "has_reaction": False,
        "has_ai": True,
        "needs_link": True,
    },
    "premium_reaction": {
        "name": "✨ رشق تفاعل مميز",
        "price_points": 10,
        "points_quantity": 1,
        "price_stars": 2,
        "stars_quantity": 1,
        "has_channel": True,
        "has_reaction": True,
        "has_ai": False,
        "needs_link": True,
    },
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

def _positive_setting(key: str, fallback: int) -> int:
    try:
        value = int(get_setting(key) or fallback)
        return value if value > 0 else fallback
    except (TypeError, ValueError):
        return fallback

def get_raksh_price_config(service_type: str) -> dict[str, int]:
    """إرجاع سعر كل باقة وعدد الوحدات التي تغطيها، مع دعم الإعدادات القديمة."""
    svc = RAKSH_SERVICES[service_type]
    keys = RAKSH_PRICE_KEYS[service_type]
    return {
        "points_price": _positive_setting(keys["points_price"], svc["price_points"]),
        "points_quantity": _positive_setting(keys["points_quantity"], svc["points_quantity"]),
        "stars_price": _positive_setting(keys["stars_price"], svc["price_stars"]),
        "stars_quantity": _positive_setting(keys["stars_quantity"], svc["stars_quantity"]),
    }

def get_raksh_total(service_type: str, quantity: int, payment_method: str) -> int:
    """حساب السعر بالتقريب للأعلى حسب صيغة «السعر لكل عدد»."""
    if quantity <= 0:
        return 0
    config = get_raksh_price_config(service_type)
    price_key = "stars_price" if payment_method == "stars" else "points_price"
    quantity_key = "stars_quantity" if payment_method == "stars" else "points_quantity"
    price = config[price_key]
    bundle_quantity = config[quantity_key]
    return ((max(1, quantity) + bundle_quantity - 1) // bundle_quantity) * price

def _raksh_rate_text(service_type: str, payment_method: str) -> str:
    config = get_raksh_price_config(service_type)
    if payment_method == "stars":
        return f"{config['stars_price']} نجمة لكل {config['stars_quantity']}"
    return f"{config['points_price']} نقطة لكل {config['points_quantity']}"

def _clear_raksh_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """إلغاء الطلب الحالي ومنع الرسالة التالية من متابعة خطوة قديمة."""
    for key in (
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
    ):
        context.user_data.pop(key, None)
    context.user_data["state"] = "main_menu"

# ════════════════════════════════════════════════════════════
# ═══ 2. دوال مساعدة ═══
# ════════════════════════════════════════════════════════════

RAKSH_MIN_DELAY_SECONDS = 60
RAKSH_MAX_DELAY_SECONDS = 3 * 60
RAKSH_VOTE_DELAY_SECONDS = 3
try:
    RAKSH_MAX_EXECUTIONS_PER_HOUR = int(
        os.getenv("RAKSH_MAX_EXECUTIONS_PER_HOUR", "0")
    )
except ValueError:
    RAKSH_MAX_EXECUTIONS_PER_HOUR = 0

def _get_delay_seconds(service_type: str | None = None, custom_delay: int | None = None) -> int:
    """إرجاع الفاصل بين الحسابات حسب نوع الخدمة والمالك."""
    if service_type in {"forced_ref", "forced_ref_ai"}:
        if custom_delay is not None:
            return custom_delay
        return 180
    if service_type == "votes_ai":
        return 0
    if service_type == "votes":
        return RAKSH_VOTE_DELAY_SECONDS
    return random.randint(RAKSH_MIN_DELAY_SECONDS, RAKSH_MAX_DELAY_SECONDS)

def get_raksh_hourly_remaining(user_id: int) -> int:
    """عدد التنفيذات المتبقية للمستخدم خلال آخر ساعة متحركة."""
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
        logger.exception("فشل قراءة حد تنفيذات الرشق للمستخدم %s", user_id)
        return 0

def _reserve_raksh_execution_slot(user_id: int, service_type: str, phone_number: str) -> bool:
    """حجز تنفيذ واحد بشكل ذري حتى لا تتجاوز الطلبات المتزامنة حد الساعة."""
    if RAKSH_MAX_EXECUTIONS_PER_HOUR <= 0:
        return True
    try:
        with db_conn() as c:
            c.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"raksh-hourly:{user_id}",),
            )
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
        logger.exception(
            "فشل حجز تنفيذ رشق للمستخدم %s والخدمة %s",
            user_id,
            service_type,
        )
        return False

def _get_all_active_sessions(service_type: str | None = None) -> list[dict]:
    """جلب كل الجلسات المخزنة التي يمكن استخدامها لخدمات الرشق."""
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, phone_number, session_string, raksh_only "
            "FROM number_stock "
            "WHERE session_string IS NOT NULL "
            "AND BTRIM(session_string) <> '' "
            "AND deleted_at IS NULL "
            "AND forced_ref_excluded IS NOT TRUE "
            "ORDER BY raksh_only DESC, id ASC"
        ).fetchall()
    return [dict(row) for row in rows]

def get_available_sessions_count(service_type: str | None = None) -> int:
    return len(_get_all_active_sessions(service_type))

def _parse_channel_ref(value: str) -> tuple[str | None, str | None]:
    """تحويل رابط قناة إلى مرجع Telethon"""
    value = (value or "").strip().strip("<>")
    if not value:
        return None, None
    if value.startswith("@"):
        return value, value
    parsed = urlparse(value if "://" in value else f"https://{value}")
    if parsed.netloc.lower() not in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}:
        return None, None
    path = parsed.path.strip("/")
    if not path:
        return None, None
    if path.startswith(("joinchat/", "+")):
        token = path.removeprefix("joinchat/").removeprefix("+")
        return f"invite:{token}", value
    path_parts = [part for part in path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] == "c" and path_parts[1].isdigit():
        return f"-100{path_parts[1]}", value
    username = path_parts[1] if path_parts and path_parts[0] == "s" and len(path_parts) > 1 else (path_parts[0] if path_parts else "")
    if username and username not in {"c", "joinchat"}:
        return f"@{username.lstrip('@')}", value
    return None, None

def _parse_channel_refs(value: str) -> list[str]:
    """تحويل إدخال القنوات المتعدد إلى مراجع Telethon صالحة."""
    refs: list[str] = []
    for token in re.split(r"[\s,،]+", (value or "").strip()):
        if not token:
            continue
        channel_ref, _ = _parse_channel_ref(token)
        if channel_ref and channel_ref not in refs:
            refs.append(channel_ref)
    return refs

def _parse_post_link(value: str) -> tuple[str | None, int | None]:
    """تحليل رابط منشور - دعم صيغ متعددة"""
    value = (value or "").strip().strip("<>")
    
    if not value.startswith("http"):
        value = "https://" + value
    
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


def _as_message_list(value) -> list:
    """توحيد نتيجة Telethon عند طلب رسالة واحدة أو عدة رسائل."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _latest_message_id(messages) -> int:
    """إرجاع آخر رقم رسالة مع تجاهل الكائنات غير المكتملة."""
    ids = [
        int(getattr(message, "id", 0) or 0)
        for message in messages or []
        if getattr(message, "id", None) is not None
    ]
    return max(ids, default=0)


async def _get_fresh_bot_messages(
    client,
    bot_entity,
    *,
    after_id: int = 0,
    limit: int = 30,
    attempts: int = 3,
    delay: float = 0.5,
) -> list:
    """قراءة ردود بوت المسابقة من الشبكة بعد تنفيذ خطوة تفاعلية."""
    latest = []
    for attempt in range(max(1, attempts)):
        try:
            latest = _as_message_list(
                await client.get_messages(bot_entity, limit=limit)
            )
        except Exception as exc:
            logger.warning(
                "تعذر تحديث رسائل بوت المسابقة (محاولة %s/%s): %s",
                attempt + 1,
                attempts,
                str(exc)[:120],
            )
            latest = []

        if latest and _latest_message_id(latest) > int(after_id or 0):
            return latest
        if attempt < attempts - 1:
            await asyncio.sleep(delay)
    return latest


def _reaction_emoticons(reactions) -> list[str]:
    """تحويل نتائج Telethon إلى قيم قابلة للاختيار والإرسال بدون تكرار."""
    result = []
    for reaction in reactions or []:
        reaction_type = reaction.__class__.__name__
        if reaction_type == "ReactionPaid":
            if RAKSH_PAID_REACTION not in result:
                result.append(RAKSH_PAID_REACTION)
            continue
        if reaction_type == "ReactionCustomEmoji":
            document_id = getattr(reaction, "document_id", None)
            if document_id is not None:
                custom_key = f"{RAKSH_CUSTOM_REACTION_PREFIX}{document_id}"
                if custom_key not in result:
                    result.append(custom_key)
            continue
        emoticon = getattr(reaction, "emoticon", None)
        if emoticon and emoticon not in result:
            result.append(emoticon)
    return result


def _custom_reaction_document_id(value: str) -> int | None:
    """Extract the Telegram custom-emoji document id from our safe UI value."""
    if not isinstance(value, str) or not value.startswith(RAKSH_CUSTOM_REACTION_PREFIX):
        return None
    raw_id = value[len(RAKSH_CUSTOM_REACTION_PREFIX):]
    return int(raw_id) if raw_id.isdigit() else None


async def _fetch_raksh_reactions(
    session: dict, post_ref: str, post_id: int
) -> list[str]:
    """قراءة التفاعلات المسموحة فعلياً في قناة المنشور."""
    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    await asyncio.wait_for(client.connect(), timeout=RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS)
    try:
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

        full_channel = await asyncio.wait_for(
            client(functions.channels.GetFullChannelRequest(channel=post_entity)),
            timeout=RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS,
        )
        full_chat = getattr(full_channel, "full_chat", None)
        available = getattr(full_chat, "available_reactions", None)
        if getattr(full_chat, "paid_reactions_available", False):
            return [RAKSH_PAID_REACTION]

        configured = getattr(available, "reactions", None)
        reactions = _reaction_emoticons(configured)
        if reactions:
            return reactions

        if available is not None and available.__class__.__name__ == "ChatReactionsAll":
            return list(RAKSH_REACTIONS.values())
        return []
    except Exception:
        logger.exception(
            "تعذر قراءة التفاعلات المسموحة للمنشور %s/%s",
            post_ref,
            post_id,
        )
        return []
    finally:
        await client.disconnect()


async def _fetch_raksh_reactions_from_pool(
    sessions: list[dict], post_ref: str, post_id: int
) -> list[str]:
    """قراءة التفاعلات بسرعة من عدد محدود من الجلسات بالتوازي."""
    if len(sessions) > RAKSH_REACTION_LOOKUP_MAX_SESSIONS:
        candidates = random.sample(sessions, RAKSH_REACTION_LOOKUP_MAX_SESSIONS)
    else:
        candidates = list(sessions)
    if not candidates:
        return []

    async def lookup(session: dict) -> list[str]:
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
            except Exception:
                continue
            if reactions:
                return reactions
        return []
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _parse_story_link(value: str) -> tuple[str | None, int | None]:
    """تحليل روابط الستوري العامة والخاصة بصيغتي /s/ و /story/."""
    value = (value or "").strip().strip("<>")
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
    return None, None

def _parse_bot_link(value: str) -> tuple[str | None, str | None]:
    """تحليل رابط بوت إحالة"""
    value = (value or "").strip()
    if not value:
        return None, None
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
        if len(parts) >= 1:
            bot_username = parts[0].lstrip("@")
            start_param = parts[1] if len(parts) > 1 else ""
            return bot_username, start_param
    return None, None


def _find_bot_start_link(message) -> tuple[str | None, str | None]:
    """استخراج رابط البوت ذي التوكن من زر منشور المسابقة."""
    fallback = None
    for row in getattr(message, "buttons", None) or []:
        for button in row:
            url = (getattr(button, "url", None) or "").strip()
            if not url:
                continue
            bot_username, start_param = _parse_bot_link(url)
            if bot_username:
                if start_param:
                    return bot_username, start_param
                fallback = fallback or (bot_username, start_param)
    return fallback or (None, None)


async def _start_contest_bot_from_post(client, post_message):
    """يفتح بوت المسابقة من زر المنشور باستخدام رابط البدء الموقّع."""
    bot_username, start_param = _find_bot_start_link(post_message)
    if not bot_username:
        raise RuntimeError("لم يُعثر على رابط بوت المسابقة داخل زر المنشور.")
    if not start_param:
        raise RuntimeError("رابط بوت المسابقة لا يحتوي على توكن start.")

    bot_entity = await client.get_entity(bot_username)
    await client(
        StartBotRequest(
            bot=bot_entity,
            peer=bot_entity,
            start_param=start_param,
        )
    )
    await asyncio.sleep(random.uniform(0.5, 1.0))
    return bot_entity


def _find_contest_vote_button(message):
    """العثور على زر التصويت، مثل «❤️ 0»، مع تجاهل أزرار الروابط."""
    candidates = []
    callback_candidates = []
    for row in getattr(message, "buttons", None) or []:
        for button in row:
            label = (getattr(button, "text", None) or "").strip()
            callback_data = str(getattr(button, "data", None) or "").casefold()
            if getattr(button, "url", None):
                continue
            if callback_data and any(
                word in callback_data
                for word in ("vote", "voting", "poll", "option", "contest", "صوت", "تصويت")
            ):
                callback_candidates.append(button)
            if not label:
                continue
            folded = label.casefold()
            if any(word in folded for word in ("تصويت", "صوت", "vote", "voting")):
                return button
            if any(
                0x1F300 <= ord(char) <= 0x1FAFF or 0x2600 <= ord(char) <= 0x27BF
                for char in label
            ):
                candidates.append(button)
    if callback_candidates:
        return callback_candidates[0]
    return candidates[0] if candidates else None


def _callback_answer_text(answer) -> str:
    """قراءة رسالة جواب callback إن أعادها Telegram."""
    return (
        getattr(answer, "message", None)
        or getattr(answer, "alert", None)
        or getattr(answer, "text", None)
        or ""
    )

# ════════════════════════════════════════════════════════════
# ═══ 3. أزرار الواجهة ═══
# ════════════════════════════════════════════════════════════

def _raksh_setting_key(service_type: str) -> str:
    return f"raksh_service_enabled_{service_type}"


def _is_raksh_service_enabled(service_type: str) -> bool:
    """الخدمات مفعلة افتراضياً حتى لا يتغير السلوك الحالي بعد التحديث."""
    return get_setting(_raksh_setting_key(service_type)).strip().lower() not in {
        "0", "false", "off", "hidden", "disabled"
    }


def _set_raksh_service_enabled(service_type: str, enabled: bool) -> None:
    set_setting(_raksh_setting_key(service_type), "1" if enabled else "0")


def raksh_menu_kb(is_owner: bool = False):
    """قائمة الخدمات؛ المالك يرى زر التحكم، والأعضاء يرون المفعّل فقط."""
    buttons = []
    for key, svc in RAKSH_SERVICES.items():
        if not is_owner and not _is_raksh_service_enabled(key):
            continue
        service_button = InlineKeyboardButton(
            svc["name"], callback_data=f"raksh:start:{key}"
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
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def raksh_price_settings_kb():
    """أزرار إعداد أسعار نظام الرشق للمالك."""
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
    """أزرار اختيار طريقة الدفع"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⭐ دفع بالنجوم ({stars_cost} نجمة)", callback_data=f"raksh:pay:stars:{service_type}:{quantity}")],
        [InlineKeyboardButton(f"💰 دفع بالنقاط ({points_cost} نقطة)", callback_data=f"raksh:pay:points:{service_type}:{quantity}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="raksh_menu")],
    ])

def raksh_channel_kb():
    """أزرار تخطي القنوات"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭️ تخطي (بدون قنوات)", callback_data="raksh:skip_channels")],
        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")],
    ])

RAKSH_REACTIONS = {
    "heart": "❤️",
    "fire": "🔥",
    "like": "👍",
    "love": "😍",
    "starstruck": "🤩",
    "sparkles": "✨",
    "hundred": "💯",
    "clap": "👏",
}

def raksh_reaction_kb(service_type: str, reactions=None):
    """أزرار اختيار التفاعل (لخدمتي ستوري وتفاعل مميز)"""
    buttons = []
    row = []
    reaction_items = (
        list(RAKSH_REACTIONS.items())
        if reactions is None
        else [(reaction, reaction) for reaction in reactions]
    )
    for index, (reaction_key, reaction) in enumerate(reaction_items, start=1):
        if reaction == RAKSH_PAID_REACTION:
            callback_key = "paid"
            reaction_label = RAKSH_PAID_REACTION_LABEL
        elif _custom_reaction_document_id(reaction) is not None:
            callback_key = f"custom_{_custom_reaction_document_id(reaction)}"
            reaction_label = f"🎨 تفاعل مميز {index}"
        else:
            callback_key = reaction_key
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
    buttons.append([InlineKeyboardButton("🎲 عشوائي", callback_data=f"raksh:reaction:{service_type}:random")])
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="raksh_menu")])
    return InlineKeyboardMarkup(buttons)

def raksh_confirm_kb(service_type: str, quantity: int, total_cost: int, payment_method: str):
    """أزرار تأكيد الطلب"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأكيد الطلب", callback_data=f"raksh:confirm:{service_type}:{quantity}:{total_cost}:{payment_method}")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="raksh_cancel")],
    ])

# ════════════════════════════════════════════════════════════
# ═══ 4. تنفيذ الخدمات ═══
# ════════════════════════════════════════════════════════════

async def _join_channel_and_schedule_leave(client, channel_ref: str):
    """الانضمام للقناة والمغادرة بعد 24 ساعة"""
    refs = channel_ref if isinstance(channel_ref, (list, tuple)) else _parse_channel_refs(channel_ref)
    if not refs:
        return
    for ref in refs:
        try:
            if ref.startswith("invite:"):
                await client(ImportChatInviteRequest(ref.split(":", 1)[1]))
            else:
                entity = await client.get_entity(ref)
                await client(JoinChannelRequest(entity))
        except Exception as exc:
            logger.warning(
                "تعذر الانضمام للقناة الاختيارية %s: %s",
                ref,
                str(exc)[:120],
            )

async def _join_discussion_group(client, discussion):
    """الانضمام لمجموعة النقاش وإرجاع الكيان الصحيح لإرسال الرد."""
    messages = getattr(discussion, "messages", None) or []
    if not messages:
        raise RuntimeError("المنشور لا يملك نقاشاً.")
    discussion_message = messages[0]
    peer = getattr(discussion_message, "peer_id", None)
    channel_id = getattr(peer, "channel_id", None)
    chats = getattr(discussion, "chats", None) or []
    discussion_chat = next(
        (chat for chat in chats if getattr(chat, "id", None) == channel_id),
        None,
    )
    if discussion_chat is None:
        raise RuntimeError("تعذر تحديد مجموعة النقاش.")
    try:
        await client(JoinChannelRequest(discussion_chat))
    except Exception as exc:
        if "USER_ALREADY_PARTICIPANT" not in str(exc).upper():
            raise
    return discussion_chat


def _normalize_digits(value: str) -> str:
    """توحيد الأرقام العربية قبل تحليل أرقام خيارات الاستفتاء."""
    return (value or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))


def _select_poll_option(options, requested: str):
    """اختيار خيار الاستفتاء بالرقم أو بالنص."""
    requested = (requested or "").strip()
    normalized_requested = _normalize_digits(requested)
    if normalized_requested.isdigit():
        index = int(normalized_requested) - 1
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


def _same_poll_option(left, right) -> bool:
    """مقارنة خيارات Telethon سواء كانت bytes أو كائنات قابلة للمقارنة."""
    if left is None or right is None:
        return False
    try:
        return bytes(left) == bytes(right)
    except (TypeError, ValueError):
        return left == right


async def _send_vote_and_check(client, peer, msg_id: int, option) -> bool:
    """إرسال التصويت ثم محاولة التأكد من ظهور علامة chosen في النتائج."""
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
            _same_poll_option(getattr(result, "option", None), option)
            and bool(getattr(result, "chosen", False))
            for result in result_items
        ):
            return True

    return False

# ─── تنفيذ كل خدمة ───

async def _execute_story(session, params, is_first):
    from telethon.tl.functions.stories import IncrementStoryViewsRequest, SendReactionRequest
    from telethon.tl.types import ReactionEmoji
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            return False, "الجلسة غير مصرح بها."
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        entity_ref, story_id = _parse_story_link(params["link"])
        if not entity_ref or not story_id:
            return False, "رابط الستوري غير صحيح."
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
            logger.warning(
                "Story view succeeded but reaction failed for %s: %s",
                session["phone_number"],
                str(reaction_error)[:120],
            )
            return True, f"✅ تمت المشاهدة من {session['phone_number']} (تعذر التفاعل)"
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_forced_ref(session, params, is_first):
    from telethon.tl.functions.contacts import ResolveUsernameRequest
    from telethon.tl.functions.messages import StartBotRequest
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            return False, "الجلسة غير مصرح بها."
        if params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        bot_username, start_param = _parse_bot_link(params["link"])
        if not bot_username:
            return False, "رابط البوت غير صحيح."
        clean_username = bot_username.lstrip("@").strip()
        resolved = await client(ResolveUsernameRequest(clean_username))
        bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]
        await client(StartBotRequest(bot=bot_entity, peer=bot_entity, start_param=start_param or ""))
        await asyncio.sleep(1.5)
        return True, f"✅ تمت الإحالة من {session['phone_number']}"
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_forced_ref_ai(session, params, is_first):
    from telethon.tl.functions.contacts import ResolveUsernameRequest
    from telethon.tl.functions.messages import StartBotRequest
    try:
        from ..referrals import solve_captcha_with_ai
    except ImportError:
        return False, "لا يمكن استيراد solve_captcha_with_ai"
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            return False, "الجلسة غير مصرح بها."
        if params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        bot_username, start_param = _parse_bot_link(params["link"])
        if not bot_username:
            return False, "رابط البوت غير صحيح."
        clean_username = bot_username.lstrip("@").strip()
        resolved = await client(ResolveUsernameRequest(clean_username))
        bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]
        await client(StartBotRequest(bot=bot_entity, peer=bot_entity, start_param=start_param or ""))
        await asyncio.sleep(1.5)
        msgs = await client.get_messages(bot_entity, limit=15)
        solved, detail = await solve_captcha_with_ai(client, bot_entity, msgs, session["phone_number"], max_attempts=1)
        if not solved:
            return False, f"فشل التحقق: {detail}"
        return True, f"✅ تمت الإحالة مع التحقق من {session['phone_number']}"
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_comment(session, params, is_first):
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            return False, "الجلسة غير مصرح بها."
        comment_text = (params.get("comment_text") or "").strip()
        if not comment_text:
            return False, "نص التعليق فارغ."
        if is_first and params.get("channel_ref"):
            try:
                await _join_channel_and_schedule_leave(client, params["channel_ref"])
            except Exception as channel_error:
                logger.warning(
                    "تعذر انضمام أول حساب لقنوات الطلب %s: %s",
                    session["phone_number"],
                    str(channel_error)[:120],
                )
        post_ref, post_id = _parse_post_link(params["link"])
        if not post_ref or not post_id:
            return False, "رابط المنشور غير صحيح."
        post_entity = await client.get_entity(post_ref)
        discussion = await client(functions.messages.GetDiscussionMessageRequest(peer=post_entity, msg_id=post_id))
        if not getattr(discussion, "messages", None):
            return False, "المنشور لا يملك نقاشاً."
        discussion_message = discussion.messages[0]
        discussion_peer = getattr(discussion_message, "peer_id", None)
        if discussion_peer is None:
            return False, "تعذر تحديد مساحة التعليقات."
        discussion_chat = await _join_discussion_group(client, discussion)
        sent_message = await client.send_message(
            discussion_chat,
            comment_text,
            reply_to=discussion_message.id,
        )
        if not getattr(sent_message, "id", None):
            return False, "تعذر تأكيد إرسال التعليق."
        return True, f"✅ تم التعليق من {session['phone_number']}"
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_poll(session, params, is_first):
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            return False, "الجلسة غير مصرح بها."
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        entity_ref, msg_id = _parse_post_link(params["link"])
        if not entity_ref or not msg_id:
            return False, "رابط الاستفتاء غير صحيح."
        entity = await client.get_entity(entity_ref)
        messages = _as_message_list(await client.get_messages(entity, ids=msg_id))
        if not messages:
            return False, "المنشور غير موجود."
        msg = messages[0]
        if not hasattr(msg, "poll") or not msg.poll:
            return False, "هذا المنشور ليس استفتاءً."
        poll = msg.poll.poll
        options = getattr(poll, "answers", [])
        chosen_option = _select_poll_option(options, params.get("poll_option"))
        if chosen_option is None:
            return False, "الخيار المطلوب غير موجود."
        verified = await _send_vote_and_check(client, entity, msg_id, chosen_option.option)
        verification = " وتم التحقق من تسجيله" if verified else " وتم إرسال الطلب إلى Telegram"
        return True, f"✅ تم التصويت{verification} من {session['phone_number']}"
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_votes(session, params, is_first):
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            return False, "الجلسة غير مصرح بها."
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        post_ref, post_id = _parse_post_link(params["link"])
        if not post_ref or not post_id:
            return False, "رابط المنشور غير صحيح."
        post_entity = await client.get_entity(post_ref)
        messages = _as_message_list(await client.get_messages(post_entity, ids=post_id))
        if not messages:
            return False, "المنشور غير موجود."
        msg = messages[0]
        if not hasattr(msg, "poll") or not msg.poll:
            return False, "هذا المنشور ليس استفتاءً."
        poll = msg.poll.poll
        options = getattr(poll, "answers", [])
        if not options:
            return False, "لا توجد خيارات."
        chosen = random.choice(options)
        verified = await _send_vote_and_check(
            client,
            post_entity,
            post_id,
            chosen.option,
        )
        verification = " وتم التحقق من تسجيله" if verified else " وتم إرسال الطلب إلى Telegram"
        return True, f"✅ تم التصويت{verification} من {session['phone_number']}"
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_votes_ai(session, params, is_first):
    """تنفيذ تصويت مع تحقق - الضغط على زر الإيموجي في المنشور ثم اختيار المشابه"""
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=10)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=5):
            return False, "الجلسة غير مصرح بها."

        # ═══════════════════════════════════════════════════════════
        # ═══ 1. تحليل رابط المنشور ═══
        # ═══════════════════════════════════════════════════════════
        parsed_link = _parse_post_link(params["link"])
        if parsed_link is None or parsed_link[0] is None or parsed_link[1] is None:
            return False, "رابط المنشور غير صالح"
        post_ref, post_id = parsed_link

        try:
            post_entity = await client.get_entity(post_ref)
        except Exception as exc:
            if "No user has" in str(exc):
                return False, "رابط المنشور غير صالح أو القناة غير متاحة للحساب."
            raise

        # ═══════════════════════════════════════════════════════════
        # ═══ 2. الانضمام للقناة الإجبارية ═══
        # ═══════════════════════════════════════════════════════════
        if params.get("channel_ref"):
            try:
                await _join_channel_and_schedule_leave(client, params["channel_ref"])
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.warning(f"فشل انضمام القناة للحساب {session['phone_number']}: {e}")

        # ═══════════════════════════════════════════════════════════
        # ═══ 3. قراءة المنشور والعثور على زر الإيموجي/القلب ═══
        # ═══════════════════════════════════════════════════════════
        messages = _as_message_list(await client.get_messages(post_entity, ids=post_id))
        if not messages:
            return False, "المنشور غير موجود."
        post_message = messages[0]

        # البحث عن زر يحتوي إيموجي أو قلب في المنشور
        emoji_button = None
        for row in getattr(post_message, "buttons", None) or []:
            for button in row:
                button_text = getattr(button, "text", "") or ""
                # البحث عن زر يحتوي إيموجي/قلب
                if button_text and any(
                    0x1F300 <= ord(char) <= 0x1FAFF or 0x2600 <= ord(char) <= 0x27BF
                    for char in button_text
                ):
                    emoji_button = button
                    break
                # البحث عن زر فيه نص "تصويت" أو "❤️"
                if any(word in button_text for word in ("تصويت", "صوت", "❤️", "💙", "💚", "💛", "💜", "🧡")):
                    emoji_button = button
                    break
            if emoji_button:
                break

        if emoji_button is not None:
            try:
                await emoji_button.click()
                logger.info(f"✅ الحساب {session['phone_number']} ضغط على زر الإيموجي: {getattr(emoji_button, 'text', '')}")
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"فشل الضغط على زر الإيموجي للحساب {session['phone_number']}: {e}")
                return False, f"فشل الضغط على زر الإيموجي: {str(e)[:80]}"
        else:
            return False, "لم يُعثر على زر الإيموجي في المنشور"

        # ═══════════════════════════════════════════════════════════
        # ═══ 4. البحث عن البوت في المحادثات ═══
        # ═══════════════════════════════════════════════════════════
        # بعد الضغط على زر الإيموجي، يفتح البوت محادثة
        await asyncio.sleep(1.5)  # انتظار وصول رسالة البوت

        # البحث عن بوت في المحادثات الأخيرة
        bot_entity = None
        async for dialog in client.iter_dialogs(limit=10):
            if dialog.is_user and dialog.entity.bot:
                bot_entity = dialog.entity
                break

        if bot_entity is None:
            return False, "لم يتم العثور على البوت في المحادثات"

        # ═══════════════════════════════════════════════════════════
        # ═══ 5. حل التحقق: اختيار الإيموجي المشابه ═══
        # ═══════════════════════════════════════════════════════════
        bot_messages = _as_message_list(await client.get_messages(bot_entity, limit=10))

        # البحث عن رسالة "اضغط على الرمز" أو "اختر الإيموجي"
        for msg in bot_messages:
            text = getattr(msg, "message", "") or getattr(msg, "text", "") or ""
            
            if "اضغط على الرمز" in text or "اختر" in text or "لست روبوت" in text or "التحقق" in text:
                # البحث عن أزرار تحتوي إيموجيات
                for row in getattr(msg, "buttons", None) or []:
                    for button in row:
                        button_text = getattr(button, "text", "") or ""
                        if button_text and any(
                            0x1F300 <= ord(char) <= 0x1FAFF or 0x2600 <= ord(char) <= 0x27BF
                            for char in button_text
                        ):
                            # الضغط على أول زر يحتوي إيموجي
                            try:
                                await button.click()
                                logger.info(f"✅ الحساب {session['phone_number']} اختار الإيموجي: {button_text}")
                                await asyncio.sleep(0.5)
                                break
                            except Exception as e:
                                logger.warning(f"فشل الضغط على إيموجي {button_text}: {e}")
                    else:
                        continue
                    break
                break

        # ═══════════════════════════════════════════════════════════
        # ═══ 6. انتظار رسالة "تم التصويت بنجاح" ═══
        # ═══════════════════════════════════════════════════════════
        success_keywords = (
            "تم التصويت", "تم تسجيل التصويت", "صوتك مسجل",
            "تم التصويت بنجاح", "vote submitted", "vote recorded",
            "voted successfully", "your vote", "تم قبول التصويت",
            "شكراً لتصويتك", "شكرا لتصويتك", "تم الادلاء بصوتك",
            "تم الإدلاء بصوتك", "سجلنا تصويتك", "تم تسجيل صوتك"
        )
        
        for attempt in range(5):
            await asyncio.sleep(1)
            bot_messages = _as_message_list(await client.get_messages(bot_entity, limit=10))
            
            for msg in bot_messages:
                text = getattr(msg, "message", "") or getattr(msg, "text", "") or ""
                if any(word in text.casefold() for word in success_keywords):
                    return True, f"✅ تم التصويت مع التحقق من {session['phone_number']}"

        return False, "لم تصل رسالة تأكيد التصويت بعد التحقق"

    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_premium_reaction(session, params, is_first):
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            return False, "الجلسة غير مصرح بها."
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        post_ref, post_id = _parse_post_link(params["link"])
        if not post_ref or not post_id:
            return False, "رابط المنشور غير صحيح."
        post_entity = await client.get_entity(post_ref)
        reaction = params.get("reaction")
        if not reaction or reaction == "random":
            available_reactions = params.get("available_reactions") or []
            reaction_pool = available_reactions or list(RAKSH_REACTIONS.values())
            reaction = random.choice(reaction_pool)
        if reaction == RAKSH_PAID_REACTION:
            try:
                from telethon.tl.types import ReactionPaid
            except ImportError:
                return False, "إصدار Telethon الحالي لا يدعم التفاعل المدفوع."
            reaction_value = ReactionPaid()
        elif (custom_document_id := _custom_reaction_document_id(reaction)) is not None:
            try:
                from telethon.tl.types import ReactionCustomEmoji
            except ImportError:
                return False, "إصدار Telethon الحالي لا يدعم التفاعلات المميزة."
            reaction_value = ReactionCustomEmoji(document_id=custom_document_id)
        else:
            reaction_value = ReactionEmoji(emoticon=reaction)
        await client(functions.messages.SendReactionRequest(
            peer=post_entity,
            msg_id=post_id,
            reaction=[reaction_value],
        ))
        return True, f"✅ تم التفاعل المميز من {session['phone_number']}"
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

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
    """اسم مختصر مناسب لإشعارات الطلبات."""
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

async def execute_raksh_service(
    service_type: str,
    quantity: int,
    sessions: list,
    params: dict,
    user_id: int,
    progress_callback=None,
):
    """تنفيذ طلب رشق بعدد محدد من الحسابات"""
    if not sessions:
        raise RuntimeError("لا توجد جلسات نشطة متاحة.")
    executor = EXECUTORS.get(service_type)
    if not executor:
        raise RuntimeError(f"خدمة غير معروفة: {service_type}")

    # ⚡ قسم "تصويت يحتوي تحقق" يعمل بالتوازي (دفعات كبيرة) ليكون أسرع
    if service_type == "votes_ai":
        shuffled = sessions.copy()
        random.shuffle(shuffled)
        success_count = 0
        success_phones = []
        failed_phones = []
        failed_details = []

        # تقسيم الجلسات إلى دفعات كبيرة متوازية
        for batch_start in range(0, min(quantity, len(shuffled)), RAKSH_VOTE_CONCURRENT):
            batch = shuffled[batch_start:batch_start + RAKSH_VOTE_CONCURRENT]
            tasks = []
            for session in batch:
                phone = session["phone_number"]
                if phone in success_phones or phone in failed_phones:
                    continue
                # حجز مقعد التنفيذ
                if not _reserve_raksh_execution_slot(user_id, service_type, phone):
                    continue

                session_lock = _get_raksh_session_lock(phone)
                if session_lock.locked():
                    continue

                async def _run_one(session=session, session_lock=session_lock):
                    async with session_lock:
                        try:
                            return await executor(session=session, params=params, is_first=True)
                        except Exception as e:
                            return False, f"❌ خطأ: {str(e)[:80]}"
                tasks.append(asyncio.create_task(_run_one()))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for session, result in zip(batch, results):
                phone = session["phone_number"]
                if isinstance(result, BaseException):
                    ok, msg = False, f"❌ فشل: {str(result)[:80]}"
                else:
                    ok, msg = result
                if ok:
                    success_count += 1
                    success_phones.append(phone)
                else:
                    failed_phones.append(phone)
                    failed_details.append(msg)

            if progress_callback:
                await progress_callback(min(batch_start + RAKSH_VOTE_CONCURRENT, quantity),
                                        quantity,
                                        success_count,
                                        len(failed_details))
            # بدون انتظار طويل بين الدفعات - فوري
            await asyncio.sleep(0.05)

        return success_count, success_phones, failed_phones, failed_details

    # باقي الخدمات تعمل بالتسلسل كما هو
    shuffled = sessions.copy()
    random.shuffle(shuffled)
    success_count = 0
    success_phones = []
    failed_phones = []
    failed_details = []
    used_phones = set()
    for i in range(quantity):
        if not shuffled:
            break
        session = shuffled.pop(0)
        phone = session["phone_number"]
        if phone in used_phones:
            continue
        used_phones.add(phone)
        if not _reserve_raksh_execution_slot(user_id, service_type, phone):
            remaining = quantity - i
            failed_phones.append(phone)
            failed_phones.extend(
                candidate["phone_number"]
                for candidate in shuffled[:remaining - 1]
                if candidate["phone_number"] not in used_phones
            )
            failed_details.extend(
                ["⏳ تم إيقاف بقية التنفيذ مؤقتاً."] * remaining
            )
            if progress_callback:
                await progress_callback(
                    quantity,
                    quantity,
                    success_count,
                    len(failed_details),
                )
            break
        session_lock = _get_raksh_session_lock(phone)
        if session_lock.locked():
            ok = False
            msg = "الجلسة قيد الاستخدام من تنفيذ آخر؛ لم يتم تشغيلها بالتوازي"
        else:
            async with session_lock:
                try:
                    ok, msg = await executor(
                        session=session, params=params, is_first=(i == 0)
                    )
                except Exception as e:
                    ok = False
                    msg = f"❌ خطأ: {str(e)[:80]}"
        if ok:
            success_count += 1
            success_phones.append(phone)
        else:
            failed_phones.append(phone)
            failed_details.append(msg)
        if progress_callback:
            await progress_callback(i + 1, quantity, success_count, len(failed_details))
        if i < quantity - 1 and shuffled:
            delay = _get_delay_seconds(service_type, params.get("delay_seconds"))
            await asyncio.sleep(delay)
    return success_count, success_phones, failed_phones, failed_details

# ════════════════════════════════════════════════════════════
# ═══ 5. معالج الأزرار الرئيسي ═══
# ════════════════════════════════════════════════════════════

async def handle_raksh_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query=None,
    data=None,
    user=None,
    is_own=None,
):
    """معالج جميع أزرار نظام الرشق"""
    query = query or update.callback_query
    data = query.data if data is None else data
    user = user or query.from_user
    is_own = (user.id == OWNER_ID) if is_own is None else is_own

    await query.answer()

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
            f"{svc['name']}\n\n"
            f"💰 السعر: {_raksh_rate_text(service_type, 'points')}\n"
            f"⭐ السعر: {_raksh_rate_text(service_type, 'stars')}\n\n"
            "📢 *أرسل القنوات الإجبارية:*\n"
            "مثال: @channel1 @channel2\n\n"
            "أو اضغط تخطي:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_channel_kb()
        )
        return
    
    if data == "raksh:skip_channels":
        context.user_data["raksh_channels"] = []
        context.user_data["raksh_step"] = "link"
        svc = RAKSH_SERVICES.get(context.user_data.get("raksh_service"))
        await query.edit_message_text(
            f"✅ تم تخطي القنوات.\n\n"
            f"🔗 *أرسل الرابط المطلوب:*\n"
            f"{_get_link_instruction(context.user_data.get('raksh_service'))}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
        )
        return
    
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
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="raksh_menu")]])
        )
        return
    
    if data.startswith("raksh:pay:"):
        parts = data.split(":")
        if len(parts) != 5 or parts[2] not in {"stars", "points"}:
            await query.answer("⚠️ بيانات الدفع غير صالحة.", show_alert=True)
            return
        method = parts[2]  # stars / points
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
        request_limit = min(
            _get_max_quantity(service_type),
            get_raksh_hourly_remaining(user.id),
        )
        if quantity > request_limit:
            await query.answer(
                "⚠️ لا يمكن قبول هذا العدد حالياً. خفّض العدد أو حاول لاحقاً.",
                show_alert=True,
            )
            return
        context.user_data["raksh_payment_method"] = method
        context.user_data["raksh_step"] = "payment_confirm"
        if method == "stars":
            total = get_raksh_total(service_type, quantity, "stars")
            await query.edit_message_text(
                f"⭐ *الدفع بالنجوم*\n\n"
                f"الخدمة: {svc['name']}\n"
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
                f"الخدمة: {svc['name']}\n"
                f"العدد: {quantity}\n"
                f"التكلفة: *{total} نقطة*\n"
                f"رصيدك: *{points} نقطة*\n\n"
                "اضغط تأكيد للمتابعة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=raksh_confirm_kb(service_type, quantity, total, "points")
            )
        return
    
    if data.startswith("raksh:confirm:"):
        parts = data.split(":")
        if len(parts) != 6 or parts[1] != "confirm":
            await query.answer("⚠️ بيانات تأكيد الطلب غير صالحة.", show_alert=True)
            return
        service_type = parts[2]
        try:
            quantity = int(parts[3])
            button_total = int(parts[4])
        except ValueError:
            await query.answer("⚠️ العدد أو السعر غير صالح.", show_alert=True)
            return
        payment_method = parts[5]
        if service_type not in RAKSH_SERVICES or payment_method not in {"points", "stars"} or quantity < 1:
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
            logger.info(
                "Raksh price refreshed before confirmation: service=%s quantity=%s",
                service_type,
                quantity,
            )
        
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
            svc = RAKSH_SERVICES.get(service_type)
            total_stars = get_raksh_total(service_type, quantity, "stars")
            await query.edit_message_text(
                "⭐ *جاري تجهيز فاتورة الدفع بالنجوم...*",
                parse_mode=ParseMode.MARKDOWN,
            )
            await context.bot.send_invoice(
                chat_id=user.id,
                title=svc["name"],
                description=f"{quantity} وحدة | {total_stars} نجمة",
                payload=f"raksh_stars:{user.id}:{service_type}:{quantity}:{total_stars}",
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice("خدمة الرشق", total_stars)],
            )
            return
        
        await _start_raksh_execution(update, context, query, service_type, quantity, payment_method, total_cost)
        return

# ════════════════════════════════════════════════════════════
# ═══ 6. دوال مساعدة للمعالجات ═══
# ════════════════════════════════════════════════════════════

def _get_link_instruction(service_type: str) -> str:
    """نص تعليمات الرابط حسب الخدمة"""
    instructions = {
        "story": "https://t.me/username/s/123 أو https://t.me/username/story/123",
        "forced_ref": "@BotUsername start123  أو  t.me/BotUsername?start=123",
        "forced_ref_ai": "@BotUsername start123  أو  t.me/BotUsername?start=123",
        "comment": "https://t.me/channel/123",
        "poll": "https://t.me/channel/123",
        "votes": "https://t.me/channel/123",
        "votes_ai": "https://t.me/channel/123",
        "premium_reaction": "https://t.me/channel/123",
    }
    return instructions.get(service_type, "أرسل الرابط المطلوب")

def _parse_raksh_rate_updates(text: str) -> dict[str, tuple[int, int]]:
    """قراءة أسطر مثل «نجوم 1 لكل 10» و«نقاط 30 لكل 1»."""
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

def _raksh_link_error(service_type: str, value: str) -> str | None:
    """إرجاع رسالة واضحة قبل حفظ رابط لا يناسب الخدمة."""
    if service_type in {"forced_ref", "forced_ref_ai"}:
        valid = _parse_bot_link(value)[0] is not None
        if not valid:
            return (
                "⚠️ رابط البوت غير صحيح.\n\n"
                "أرسله بهذا الشكل:\n"
                "@BotUsername start123\n"
                "أو: t.me/BotUsername?start=123"
            )
        return None

    if service_type == "story":
        valid = all(_parse_story_link(value))
    else:
        valid = all(_parse_post_link(value))
    if not valid:
        return (
            "⚠️ الرابط غير صحيح لهذه الخدمة.\n\n"
            f"أرسل الرابط بهذا الشكل:\n{_get_link_instruction(service_type)}"
        )
    return None

def _get_max_quantity(service_type: str | None = None) -> int:
    """عدد الوحدات الأقصى حسب الجلسات المؤهلة المتاحة حالياً."""
    return get_available_sessions_count(service_type)

def _get_request_limit(user_id: int, service_type: str | None = None) -> int:
    """الحد الفعلي للطلب: الحسابات المتاحة أو رصيد الساعة، أيهما أقل."""
    return min(
        _get_max_quantity(service_type),
        get_raksh_hourly_remaining(user_id),
    )

def _chunk_lines(lines: list[str], max_chars: int = 3500) -> list[str]:
    """تقسيم قوائم الحسابات حتى تبقى رسائل تيليجرام ضمن الحجم المسموح."""
    chunks: list[str] = []
    current: list[str] = []
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

async def _send_raksh_order_to_group(bot, user_id: int, quantity: int, payment_method: str, service_type: str) -> None:
    """إرسال إشعار بدء الطلب إلى كروب الطلبات."""
    if not ADMIN_GROUP_ID:
        return
    try:
        await bot.send_message(
            ADMIN_GROUP_ID,
            f"طلب {_raksh_order_label(service_type)} العدد: {quantity}\n"
            f"المستخدم: {user_id}\n"
            f"طريقة الدفع: {payment_method}",
        )
    except Exception:
        logger.exception("فشل إرسال طلب الرشق إلى كروب الطلبات")

async def _send_raksh_owner_result(
    bot,
    service_type: str,
    quantity: int,
    success_phones: list[str],
    failed_phones: list[str],
    failed_details: list[str],
) -> None:
    """إرسال الحسابات الناجحة والفاشلة للمالك بعد اكتمال الطلب."""
    if not OWNER_ID:
        return
    try:
        failed_count = len(failed_phones)
        lines = [
            f"نتيجة طلب {_raksh_order_label(service_type)} العدد: {quantity}",
            f"✅ المنفذة: {len(success_phones)}",
            f"❌ الفاشلة: {failed_count}",
            "",
            "✅ الحسابات المنفذة:",
        ]
        lines.extend(f"• {phone}" for phone in success_phones)
        lines.extend(["", "❌ الحسابات الفاشلة:"])
        if failed_phones:
            for index, phone in enumerate(failed_phones):
                detail = failed_details[index] if index < len(failed_details) else "فشل التنفيذ"
                lines.append(f"• {phone} — {detail}")
        else:
            lines.append("• لا يوجد")

        for chunk in _chunk_lines(lines):
            await bot.send_message(OWNER_ID, chunk)
    except Exception:
        logger.exception("فشل إرسال نتيجة حسابات طلب الرشق إلى المالك")

# ════════════════════════════════════════════════════════════
# ═══ 7. تنفيذ الطلب ═══
# ════════════════════════════════════════════════════════════

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
    """بدء تنفيذ طلب الرشق"""
    user = query.from_user if query is not None else update.effective_user
    
    if progress_message is None:
        progress_msg = await query.edit_message_text(
            "✅ *بدأ التنفيذ الآن باستخدام الحسابات النشطة...*\n\n"
            f"📊 0/{quantity}",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        progress_msg = progress_message
        await progress_msg.edit_text(
            "✅ *بدأ التنفيذ الآن باستخدام الحسابات النشطة...*\n\n"
            f"📊 0/{quantity}",
            parse_mode=ParseMode.MARKDOWN,
        )
    
    sessions = _get_all_active_sessions(service_type)
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
    
    success_count, success_phones, failed_phones, failed_details = await execute_raksh_service(
        service_type=service_type,
        quantity=quantity,
        sessions=sessions,
        params=params,
        user_id=user.id,
        progress_callback=update_progress
    )
    
    failed_count = quantity - success_count
    refund = 0
    if failed_count > 0 and payment_method == "points":
        refund = max(
            0,
            total_cost - get_raksh_total(service_type, success_count, "points"),
        )
        add_points(user.id, refund)
    
    result_text = f"✅ *اكتمل الطلب!*\n\n"
    result_text += f"الخدمة: {RAKSH_SERVICES[service_type]['name']}\n"
    result_text += f"المطلوب: {quantity}\n"
    result_text += f"✅ المنجز: {success_count}\n"
    result_text += f"❌ الفاشل: {failed_count}\n"
    if refund > 0:
        result_text += f"💰 تم تعويضك: {refund} نقطة\n"
    
    if success_phones:
        result_text += f"\n✅ *الحسابات الناجحة:*\n"
        result_text += "\n".join(f"• `{p}`" for p in success_phones[:10])
        if len(success_phones) > 10:
            result_text += f"\n... و{len(success_phones)-10} أخرى"
    
    if failed_details:
        result_text += f"\n\n❌ *الفاشلة:*\n"
        result_text += "\n".join(f"• {d}" for d in failed_details[:5])
        if len(failed_details) > 5:
            result_text += f"\n... و{len(failed_details)-5} أخرى"

    await _send_raksh_owner_result(
        context.bot,
        service_type,
        quantity,
        success_phones,
        failed_phones,
        failed_details,
    )
    
    await progress_msg.edit_text(
        result_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb()
    )
    
    _clear_raksh_state(context)

# ════════════════════════════════════════════════════════════
# ═══ 8. معالج النصوص ═══
# ════════════════════════════════════════════════════════════

async def handle_raksh_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج النصوص لنظام الرشق"""
    user = update.effective_user
    text = update.message.text
    state = context.user_data.get("raksh_step")
    
    if not state:
        return False

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
    
    if state == "channel":
        channel_refs = _parse_channel_refs(text)
        if text.strip() and not channel_refs:
            await update.message.reply_text(
                "⚠️ لم أتعرف على أي قناة.\n"
                "أرسل @username أو رابط t.me للقناة، ويمكنك إرسال أكثر من قناة مفصولة بمسافة.",
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
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
        )
        return True

    if state in {"payment", "payment_confirm"}:
        normalized = re.sub(r"[\s_\-]+", "", (text or "").casefold())
        if normalized in {"نقاط", "النقاط", "بالنقاط", "points", "point"}:
            method = "points"
            method_label = "النقاط"
        elif normalized in {"نجوم", "النجوم", "بالنجوم", "stars", "star"}:
            method = "stars"
            method_label = "النجوم"
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
                    f"❌ نقاطك غير كافية لإتمام الطلب.\n"
                    f"التكلفة المطلوبة: {total} نقطة.",
                    reply_markup=raksh_menu_kb(user.id == OWNER_ID),
                )
                _clear_raksh_state(context)
                return True

            progress_message = await update.message.reply_text(
                f"✅ تم الدفع بالنقاط وخصم {total} نقطة.\n"
                "✅ بدأ التنفيذ الآن باستخدام الحسابات النشطة..."
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
            f"✅ تم اختيار الدفع بـ{method_label}.\n\n"
            f"الخدمة: {svc['name']}\n"
            f"العدد: {quantity}\n"
            f"التكلفة: {total} {'نقطة' if method == 'points' else 'نجمة'}\n\n"
            "اضغط «تأكيد الطلب» للبدء.",
            reply_markup=raksh_confirm_kb(service_type, quantity, total, method),
        )
        return True
    
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
        
        if svc.get("has_reaction"):
            reaction_options = None
            if service_type == "premium_reaction":
                post_ref, post_id = _parse_post_link(text)
                if not post_ref or post_id is None:
                    await update.message.reply_text(
                        "⚠️ تعذر تحليل رابط المنشور. أرسل رابط منشور قناة صالحاً ثم أعد المحاولة."
                    )
                    return True
                reaction_options = await _fetch_raksh_reactions_from_pool(
                    _get_all_active_sessions(service_type),
                    post_ref,
                    post_id,
                )
                if not reaction_options:
                    await update.message.reply_text(
                        "⚠️ تعذر قراءة التفاعل المفعّل في هذا المنشور.\n"
                        "تأكد أن الرابط لمنشور قناة وأن إحدى جلسات البوت تملك صلاحية الوصول إليه، ثم أعد المحاولة."
                    )
                    return True
                context.user_data["raksh_available_reactions"] = reaction_options

            context.user_data["raksh_step"] = "reaction"
            await update.message.reply_text(
                f"✅ تم حفظ الرابط.\n\n"
                f"😊 *اختر التفاعل المطلوب:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=raksh_reaction_kb(service_type, reaction_options)
            )
            return True
        
        if service_type == "comment":
            context.user_data["raksh_step"] = "comment_text"
            await update.message.reply_text(
                f"✅ تم حفظ الرابط.\n\n"
                f"💬 *أرسل نص التعليق:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
            )
            return True
        
        if service_type == "poll":
            context.user_data["raksh_step"] = "poll_option"
            await update.message.reply_text(
                f"✅ تم حفظ الرابط.\n\n"
                f"🔢 *أرسل رقم الخيار المطلوب:*\n"
                f"(مثال: 1 أو 2 أو 3)",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
            )
            return True
        
        context.user_data["raksh_step"] = "quantity"
        service_type = context.user_data.get("raksh_service")
        max_qty = _get_request_limit(user.id, service_type)
        if max_qty < 1:
            await update.message.reply_text(
                "⚠️ لا توجد حسابات ذات جلسات متاحة حالياً لتنفيذ هذه الخدمة.",
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
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
        )
        return True
    
    if state == "comment_text":
        context.user_data["raksh_comment"] = text
        context.user_data["raksh_step"] = "quantity"
        service_type = context.user_data.get("raksh_service")
        max_qty = _get_request_limit(user.id, service_type)
        if max_qty < 1:
            await update.message.reply_text(
                "⚠️ لا توجد حسابات ذات جلسات متاحة حالياً لتنفيذ هذه الخدمة.",
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
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
        )
        return True
    
    if state == "poll_option":
        normalized_option = _normalize_digits(text.strip())
        if not normalized_option.isdigit():
            await update.message.reply_text(
                "⚠️ أرسل رقماً صحيحاً (مثال: 1 أو 2 أو 3).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ]),
            )
            return True
        context.user_data["raksh_poll_option"] = normalized_option
        context.user_data["raksh_step"] = "quantity"
        service_type = context.user_data.get("raksh_service")
        max_qty = _get_request_limit(user.id, service_type)
        if max_qty < 1:
            await update.message.reply_text(
                "⚠️ لا توجد حسابات ذات جلسات متاحة حالياً لتنفيذ هذه الخدمة.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ]),
            )
            return True
        await update.message.reply_text(
            f"✅ تم حفظ الخيار {normalized_option}.\n\n"
            f"🔢 *أرسل عدد الوحدات المطلوبة:*\n"
            f"(الحد الأقصى: {max_qty})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
        )
        return True
    
    if state == "delay":
        service_type = context.user_data.get("raksh_service")
        if service_type not in {"forced_ref", "forced_ref_ai", "votes_ai"} or user.id != OWNER_ID:
            context.user_data["raksh_step"] = "quantity"
            return True
        try:
            delay_seconds = int(text.strip())
        except (TypeError, ValueError):
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
            f"✅ تم ضبط الفاصل بين الحسابات: {delay_seconds} ثانية.\n\n"
            f"📋 *مراجعة الطلب*\n\n"
            f"الخدمة: {svc['name']}\n"
            f"العدد: {quantity}\n"
            f"💰 السعر بالنقاط: {points_cost} نقطة\n"
            f"⭐ السعر بالنجوم: {stars_cost} نجمة\n\n"
            f"اختر طريقة الدفع:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_payment_kb(service_type, quantity, points_cost, stars_cost)
        )
        return True

    if state == "quantity":
        try:
            quantity = int(text)
        except ValueError:
            await update.message.reply_text(
                "⚠️ أرسل رقماً صحيحاً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
            )
            return True
        
        service_type = context.user_data.get("raksh_service")
        max_qty = _get_request_limit(user.id, service_type)
        if max_qty < 1:
            await update.message.reply_text(
                "⚠️ لا توجد حسابات ذات جلسات متاحة حالياً لتنفيذ هذه الخدمة.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ]),
            )
            return True
        if quantity < 1 or quantity > max_qty:
            await update.message.reply_text(
                f"⚠️ العدد المسموح بين 1 و {max_qty}.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
            )
            return True
        
        service_type = context.user_data.get("raksh_service")
        svc = RAKSH_SERVICES.get(service_type)
        points_cost = get_raksh_total(service_type, quantity, "points")
        stars_cost = get_raksh_total(service_type, quantity, "stars")
        
        context.user_data["raksh_quantity"] = quantity
        if user.id == OWNER_ID and service_type in {"forced_ref", "forced_ref_ai", "votes_ai"}:
            context.user_data["raksh_step"] = "delay"
            delay_hint = (
                "للأعضاء يُطبّق فاصل تلقائي عشوائي بين 60 و180 ثانية."
                if service_type == "votes_ai"
                else "للأعضاء يبقى الوقت ثابتاً: 180 ثانية (3 دقائق)."
            )
            await update.message.reply_text(
                "⏱️ *إعداد الفاصل الزمني للمالك*\n\n"
                "أرسل عدد الثواني بين تفعيل حساب وآخر.\n"
                "مثال: 3\n"
                f"{delay_hint}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
            )
            return True
        context.user_data["raksh_step"] = "payment"
        
        await update.message.reply_text(
            f"📋 *مراجعة الطلب*\n\n"
            f"الخدمة: {svc['name']}\n"
            f"العدد: {quantity}\n"
            f"💰 السعر بالنقاط: {points_cost} نقطة\n"
            f"⭐ السعر بالنجوم: {stars_cost} نجمة\n\n"
            f"اختر طريقة الدفع:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_payment_kb(service_type, quantity, points_cost, stars_cost)
        )
        return True
    
    return False

# ════════════════════════════════════════════════════════════
# ═══ 9. معالج الدفع بالنجوم ═══
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
    """معالج الدفع الناجح بالنجوم"""
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
                logger.exception("فشل إعادة دفع النجوم لطلب رشق المستخدم %s", user_id)
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
# ═══ 10. الأمر الرئيسي /raksh ═══
# ════════════════════════════════════════════════════════════

async def cmd_raksh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الأمر /raksh - يعرض قائمة خدمات الرشق"""
    user = update.effective_user
    _clear_raksh_state(context)
    
    if not (user.id == OWNER_ID) and is_user_banned(user.id):
        await update.message.reply_text("🚫 تم حظرك من استخدام هذا البوت.")
        return

    try:
        available_sessions = get_available_sessions_count()
    except Exception:
        logger.exception("فشل جلب عدد الحسابات عند تنفيذ /raksh")
        available_sessions = 0
    
    await update.message.reply_text(
        f"🔥 *{md_escape(get_raksh_accounts_label())}*\n\n"
        "اختر الخدمة المطلوبة:\n"
        f"📊 الحسابات المتاحة: *{available_sessions}*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=raksh_menu_kb(user.id == OWNER_ID)
    )
