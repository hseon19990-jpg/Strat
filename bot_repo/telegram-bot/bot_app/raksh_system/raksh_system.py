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

ملاحظة: قد يحدث تأخير ملحوظ في التنفيذ بسبب:
- إزالة شك الرشق (Anti-Spam)
- الحسابات تحتوي على ستوري، افتار، اسم عربي، يوزر وبايو
- التأخير طبيعي لضمان جودة الخدمة
"""

from ..shared import *
from ..accounts import get_forced_ref_account_count
from ..database import db_conn
from ..security import add_points, deduct_points, get_user, is_user_banned
from ..users import get_setting, set_setting
from ..ui import main_menu_kb
from telethon import TelegramClient, functions
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, SendVoteRequest, StartBotRequest
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
RAKSH_REACTION_LOOKUP_TIMEOUT_SECONDS = 8
RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS = 5

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
        "channel_price_points": 30,
        "channel_price_stars": 3,
        "description": "مشاهدة ستوري وتفاعل معه بحسابات حقيقية تحتوي على ستوري، افتار، اسم عربي، يوزر وبايو"
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
        "channel_price_points": 25,
        "channel_price_stars": 2,
        "description": "إحالة بوت إجباري بحسابات حقيقية"
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
        "channel_price_points": 35,
        "channel_price_stars": 3,
        "description": "إحالة بوت إجباري مع تحقق ذكي"
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
        "channel_price_points": 30,
        "channel_price_stars": 3,
        "description": "رشق تعليقات بحسابات حقيقية"
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
        "channel_price_points": 30,
        "channel_price_stars": 3,
        "description": "رشق استفتاءات بحسابات حقيقية"
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
        "channel_price_points": 25,
        "channel_price_stars": 2,
        "description": "رشق أصوات بحسابات حقيقية"
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
        "channel_price_points": 25,
        "channel_price_stars": 2,
        "description": "رشق تصويت مع تحقق ذكي"
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
        "channel_price_points": 0,
        "channel_price_stars": 0,
        "description": "رشق تفاعلات مميزة (مدفوعة)"
    },
}

RAKSH_PRICE_KEYS = {
    service_type: {
        "points_price": f"raksh_{service_type}_points_price",
        "points_quantity": f"raksh_{service_type}_points_quantity",
        "stars_price": f"raksh_{service_type}_stars_price",
        "stars_quantity": f"raksh_{service_type}_stars_quantity",
        "channel_points_price": f"raksh_{service_type}_channel_points_price",
        "channel_stars_price": f"raksh_{service_type}_channel_stars_price",
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
        "channel_points_price": _positive_setting(keys["channel_points_price"], svc.get("channel_price_points", 30)),
        "channel_stars_price": _positive_setting(keys["channel_stars_price"], svc.get("channel_price_stars", 3)),
    }

def get_raksh_total(service_type: str, quantity: int, payment_method: str, channel_count: int = 0) -> int:
    """حساب السعر بالتقريب للأعلى مع احتساب القنوات."""
    if quantity <= 0:
        return 0
    config = get_raksh_price_config(service_type)
    price_key = "stars_price" if payment_method == "stars" else "points_price"
    quantity_key = "stars_quantity" if payment_method == "stars" else "points_quantity"
    channel_price_key = "channel_stars_price" if payment_method == "stars" else "channel_points_price"
    
    price = config[price_key]
    bundle_quantity = config[quantity_key]
    channel_price = config[channel_price_key]
    
    total = ((max(1, quantity) + bundle_quantity - 1) // bundle_quantity) * price
    total += channel_count * channel_price
    return total

def _raksh_rate_text(service_type: str, payment_method: str) -> str:
    config = get_raksh_price_config(service_type)
    channel_price_key = "channel_stars_price" if payment_method == "stars" else "channel_points_price"
    if payment_method == "stars":
        return f"{config['stars_price']} نجمة لكل {config['stars_quantity']} (القناة: {config[channel_price_key]} نجمة)"
    return f"{config['points_price']} نقطة لكل {config['points_quantity']} (القناة: {config[channel_price_key]} نقطة)"

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
        "raksh_quantity",
        "raksh_payment_method",
        "raksh_price_edit_service",
        "raksh_failed_phones",
        "raksh_success_phones",
        "raksh_processed_count",
        "raksh_total_quantity",
    ):
        context.user_data.pop(key, None)
    context.user_data["state"] = "main_menu"

# ════════════════════════════════════════════════════════════
# ═══ 2. دوال مساعدة ═══
# ════════════════════════════════════════════════════════════

RAKSH_MIN_DELAY_SECONDS = 60
RAKSH_MAX_DELAY_SECONDS = 3 * 60
RAKSH_VOTE_DELAY_SECONDS = 3
RAKSH_AUTO_RETRY_LIMIT = 3

try:
    RAKSH_MAX_EXECUTIONS_PER_HOUR = int(
        os.getenv("RAKSH_MAX_EXECUTIONS_PER_HOUR", "0")
    )
except ValueError:
    RAKSH_MAX_EXECUTIONS_PER_HOUR = 0

def _get_delay_seconds(service_type: str | None = None) -> int:
    """إرجاع الفاصل بين الحسابات حسب نوع الخدمة."""
    if service_type in {"votes", "votes_ai"}:
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
            "SELECT id, phone_number, session_string "
            "FROM number_stock "
            "WHERE session_string IS NOT NULL "
            "AND BTRIM(session_string) <> '' "
            "AND deleted_at IS NULL "
            "AND forced_ref_excluded IS NOT TRUE "
            "ORDER BY id ASC"
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
    """تحليل رابط منشور"""
    value = (value or "").strip().strip("<>")
    parsed = urlparse(value if "://" in value else f"https://{value}")
    if parsed.netloc.lower() not in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}:
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

async def _fetch_raksh_reactions(session: dict, post_ref: str, post_id: int) -> list[str]:
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
    
    # ── الحالة 1: رابط t.me كامل ──
    if "t.me/" in value or "telegram.me/" in value:
        parsed = urlparse(value if "://" in value else f"https://{value}")
        path = parsed.path.strip("/")
        if path:
            bot_username = path.split("/")[0].lstrip("@")
            query = parse_qs(parsed.query)
            start_param = (
                query.get("start", [""])[0]
                or query.get("startapp", [""])[0]
                or query.get("startgroup", [""])[0]
            )
            return bot_username, start_param
    
    # ── الحالة 2: @BotUsername start123 (مفصول بمسافة) ──
    elif value.startswith("@"):
        parts = value.split()
        if len(parts) >= 1:
            bot_username = parts[0].lstrip("@")
            start_param = parts[1] if len(parts) > 1 else ""
            return bot_username, start_param
    
    # ── الحالة 3: BotUsername start123 (بدون @) ──
    else:
        parts = value.split()
        if len(parts) >= 1:
            bot_username = parts[0]
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
    await asyncio.sleep(random.uniform(1.5, 2.5))
    return bot_entity

def _find_contest_vote_button(message):
    """العثور على زر التصويت، مثل «❤️ 0»، مع تجاهل أزرار الروابط."""
    candidates = []
    for row in getattr(message, "buttons", None) or []:
        for button in row:
            label = (getattr(button, "text", None) or "").strip()
            if not label or getattr(button, "url", None):
                continue
            folded = label.casefold()
            if any(word in folded for word in ("تصويت", "صوت", "vote", "voting")):
                return button
            if re.search(r"\d+", label) and any(
                0x1F300 <= ord(char) <= 0x1FAFF or 0x2600 <= ord(char) <= 0x27BF
                for char in label
            ):
                candidates.append(button)
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
                f"💰 {config['points_price']}/{config['points_quantity']} | "
                f"📺 قناة: ⭐{config['channel_stars_price']}/💰{config['channel_points_price']}",
                callback_data=f"raksh:price:{service_type}",
            )
        ])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
    return InlineKeyboardMarkup(rows)

def raksh_payment_kb(service_type: str, quantity: int, points_cost: int, stars_cost: int, channel_count: int = 0):
    """أزرار اختيار طريقة الدفع مع عرض تكلفة القنوات"""
    channel_info = f" (📺 {channel_count} قناة)" if channel_count > 0 else ""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⭐ دفع بالنجوم ({stars_cost} نجمة){channel_info}", callback_data=f"raksh:pay:stars:{service_type}:{quantity}:{channel_count}")],
        [InlineKeyboardButton(f"💰 دفع بالنقاط ({points_cost} نقطة){channel_info}", callback_data=f"raksh:pay:points:{service_type}:{quantity}:{channel_count}")],
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

def raksh_confirm_kb(service_type: str, quantity: int, total_cost: int, payment_method: str, channel_count: int = 0):
    """أزرار تأكيد الطلب"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأكيد الطلب", callback_data=f"raksh:confirm:{service_type}:{quantity}:{total_cost}:{payment_method}:{channel_count}")],
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

    for delay in (0.0, 0.5, 1.0):
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
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            with db_conn() as c:
                c.execute("DELETE FROM number_stock WHERE phone_number=%s AND ever_sold IS NOT TRUE", (session["phone_number"],))
            return False, "الجلسة غير مصرح بها - تم طرد الحساب."
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
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            with db_conn() as c:
                c.execute("DELETE FROM number_stock WHERE phone_number=%s AND ever_sold IS NOT TRUE", (session["phone_number"],))
            return False, "الجلسة غير مصرح بها - تم طرد الحساب."
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        bot_username, start_param = _parse_bot_link(params["link"])
        if not bot_username:
            return False, "رابط البوت غير صحيح."
        clean_username = bot_username.lstrip("@").strip()
        resolved = await client(ResolveUsernameRequest(clean_username))
        bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]
        await client(StartBotRequest(bot=bot_entity, peer=bot_entity, start_param=start_param or ""))
        await asyncio.sleep(3)
        return True, f"✅ تمت الإحالة من {session['phone_number']}"
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_forced_ref_ai(session, params, is_first):
    """تنفيذ إحالة بوت إجباري مع حل الكابتشا المتقدم."""
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            with db_conn() as c:
                c.execute("DELETE FROM number_stock WHERE phone_number=%s AND ever_sold IS NOT TRUE", (session["phone_number"],))
            return False, "الجلسة غير مصرح بها - تم طرد الحساب."

        parsed_link = _parse_bot_link(params["link"])
        if parsed_link is None or parsed_link[0] is None:
            return False, "رابط البوت غير صالح"
        bot_username, start_param = parsed_link
        bot_entity = await client.get_entity(bot_username)
        
        if is_first and params.get("channel_ref"):
            try:
                await _join_channel_and_schedule_leave(client, params["channel_ref"])
                await asyncio.sleep(random.uniform(1, 2))
            except Exception as e:
                logger.warning(f"فشل انضمام القناة للحساب {session['phone_number']}: {e}")

        # ── إرسال /start مع الكود ──
        await client(
            StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param or "",
            )
        )
        
        # ── انتظار وقراءة الرسائل (5 محاولات) ──
        for _ in range(5):
            await asyncio.sleep(2)
            messages = _as_message_list(await client.get_messages(bot_entity, limit=10))
            if messages:
                break
        
        if not messages:
            return False, "لم تصل أي رسالة من البوت بعد /start"
        
        # ── حل الكابتشا المتقدم ──
        solved, detail = await _solve_captcha_smart_with_buttons(
            client,
            bot_entity,
            session["phone_number"],
            max_attempts=RAKSH_CAPTCHA_MAX_ATTEMPTS,
        )
        if not solved:
            return False, f"فشل حل الكابتشا: {detail}"

        # ── التحقق من نجاح الإحالة ──
        messages = _as_message_list(await client.get_messages(bot_entity, limit=5))
        for msg in messages:
            msg_text = msg.text or msg.caption or ""
            if any(keyword in msg_text for keyword in ["أهلاً", "مرحباً", "تم", "success", "✅", "مبروك"]):
                return True, f"✅ تمت الإحالة والتحقق من {session['phone_number']}"

        return True, f"✅ تمت الإحالة من {session['phone_number']}"
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_comment(session, params, is_first):
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            with db_conn() as c:
                c.execute("DELETE FROM number_stock WHERE phone_number=%s AND ever_sold IS NOT TRUE", (session["phone_number"],))
            return False, "الجلسة غير مصرح بها - تم طرد الحساب."
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
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            with db_conn() as c:
                c.execute("DELETE FROM number_stock WHERE phone_number=%s AND ever_sold IS NOT TRUE", (session["phone_number"],))
            return False, "الجلسة غير مصرح بها - تم طرد الحساب."
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
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            with db_conn() as c:
                c.execute("DELETE FROM number_stock WHERE phone_number=%s AND ever_sold IS NOT TRUE", (session["phone_number"],))
            return False, "الجلسة غير مصرح بها - تم طرد الحساب."
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
        verified = await _send_vote_and_check(client, post_entity, post_id, chosen.option)
        verification = " وتم التحقق من تسجيله" if verified else " وتم إرسال الطلب إلى Telegram"
        return True, f"✅ تم التصويت{verification} من {session['phone_number']}"
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_votes_ai(session, params, is_first):
    """تنفيذ تصويت مع حل الكابتشا المتقدم - سيناريو بوت المسابقة"""
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            with db_conn() as c:
                c.execute("DELETE FROM number_stock WHERE phone_number=%s AND ever_sold IS NOT TRUE", (session["phone_number"],))
            return False, "الجلسة غير مصرح بها - تم طرد الحساب."

        parsed_link = _parse_post_link(params["link"])
        if parsed_link is None or parsed_link[0] is None or parsed_link[1] is None:
            return False, "رابط المنشور غير صالح"
        post_ref, post_id = parsed_link

        post_entity = None
        try:
            post_entity = await client.get_entity(post_ref)
        except Exception as exc:
            if "No user has" in str(exc):
                try:
                    channel_link = post_ref.replace("@", "")
                    await client.join_chat(channel_link)
                    await asyncio.sleep(1)
                    post_entity = await client.get_entity(post_ref)
                except Exception as join_exc:
                    return False, "رابط المنشور غير صالح أو القناة غير متاحة للحساب"
            else:
                return False, "رابط المنشور غير صالح أو القناة غير متاحة للحساب"

        messages = _as_message_list(await client.get_messages(post_entity, ids=post_id))
        if not messages:
            return False, "المنشور غير موجود"
        msg = messages[0]

        # الضغط على زر "المشاركة في المسابقة" في المنشور
        bot_entity = None
        if msg.buttons:
            for row in msg.buttons:
                for btn in row:
                    btn_text = (btn.text or "").strip()
                    if "مشاركة" in btn_text or "اشتراك" in btn_text or "join" in btn_text.lower():
                        try:
                            await btn.click()
                            await asyncio.sleep(2)
                            break
                        except Exception:
                            pass
            try:
                bot_entity = await _start_contest_bot_from_post(client, msg)
                logger.info("✅ الحساب %s فتح بوت المسابقة", session["phone_number"])
            except Exception:
                bot_entity = None

        # إذا كان هناك بوت مسابقة → الضغط على زر "انضمام" ثم حل الكابتشا
        if bot_entity is not None:
            for _ in range(5):
                bot_messages = _as_message_list(await client.get_messages(bot_entity, limit=5))
                for b_msg in bot_messages:
                    if b_msg.buttons:
                        for row in b_msg.buttons:
                            for btn in row:
                                btn_text = btn.text or ""
                                if "انضمام" in btn_text or "join" in btn_text.lower():
                                    try:
                                        await btn.click()
                                        await asyncio.sleep(1)
                                        break
                                    except:
                                        pass
                solved, detail = await _solve_captcha_smart_with_buttons(client, bot_entity, session["phone_number"])
                if solved:
                    break

        # الضغط على زر التصويت في المنشور
        try:
            messages = _as_message_list(await client.get_messages(post_entity, ids=post_id))
            if messages:
                msg = messages[0]
                vote_button = _find_contest_vote_button(msg)
                if vote_button is not None:
                    await vote_button.click()
                    await asyncio.sleep(random.uniform(1, 2))
                    return True, f"✅ تم التصويت مع التحقق من {session['phone_number']}"
        except Exception as e:
            logger.warning(f"فشل الضغط على زر التصويت للحساب {session['phone_number']}: {e}")

        # الضغط على زر التصويت في البوت إذا لم نجده في المنشور
        if bot_entity is not None:
            bot_messages = _as_message_list(await client.get_messages(bot_entity, limit=10))
            for b_msg in bot_messages:
                vote_button = _find_contest_vote_button(b_msg)
                if vote_button is not None:
                    await vote_button.click()
                    await asyncio.sleep(1)
                    return True, f"✅ تم التصويت مع التحقق من {session['phone_number']}"

        return False, "لم يُعثر على زر التصويت في منشور المسابقة."
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_premium_reaction(session, params, is_first):
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            with db_conn() as c:
                c.execute("DELETE FROM number_stock WHERE phone_number=%s AND ever_sold IS NOT TRUE", (session["phone_number"],))
            return False, "الجلسة غير مصرح بها - تم طرد الحساب."
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

def _raksh_retry_failed_accounts(
    failed_phones: list,
    sessions: list,
    service_type: str,
    params: dict,
    user_id: int,
) -> tuple[list, list, list]:
    """إعادة محاولة الحسابات الفاشلة مع حسابات بديلة."""
    retry_phones = []
    retry_reasons = []
    
    for phone in failed_phones:
        for detail in failed_details:
            if phone in detail:
                if "الجلسة غير مصرح بها" in detail or "تم طرد الحساب" in detail:
                    retry_phones.append(phone)
                    retry_reasons.append(detail)
                break
    
    available_sessions = [s for s in sessions if s["phone_number"] not in used_phones]
    
    return retry_phones, retry_reasons, available_sessions

async def execute_raksh_service(
    service_type: str,
    quantity: int,
    sessions: list,
    params: dict,
    user_id: int,
    progress_callback=None,
):
    """تنفيذ طلب رشق بعدد محدد من الحسابات مع إعادة المحاولة التلقائية - نسخة سريعة جداً."""
    if not sessions:
        raise RuntimeError("لا توجد جلسات نشطة متاحة.")
    executor = EXECUTORS.get(service_type)
    if not executor:
        raise RuntimeError(f"خدمة غير معروفة: {service_type}")
    
    shuffled = sessions.copy()
    random.shuffle(shuffled)
    success_count = 0
    success_phones = []
    failed_phones = []
    failed_details = []
    used_phones = set()
    
    batch_size = 10
    tasks = []
    
    async def run_single(session):
        nonlocal success_count, failed_phones, failed_details, used_phones
        phone = session["phone_number"]
        if phone in used_phones:
            return
        used_phones.add(phone)
        
        try:
            ok, msg = await executor(session=session, params=params, is_first=(success_count == 0))
        except Exception as e:
            ok = False
            msg = f"❌ خطأ: {str(e)[:80]}"
            
        if ok:
            success_count += 1
            success_phones.append(phone)
        else:
            is_session_error = any(keyword in msg for keyword in [
                "الجلسة غير مصرح بها",
                "تم طرد الحساب",
                "session expired",
                "AuthKeyUnregistered",
                "SessionRevoked",
                "UserDeactivated",
                "AccountBanned",
            ])
            
            if is_session_error:
                with db_conn() as c:
                    c.execute("DELETE FROM number_stock WHERE phone_number=%s AND ever_sold IS NOT TRUE", (phone,))
                failed_phones.append(phone)
                failed_details.append(f"🗑 {msg} — تم طرد الحساب")
            else:
                failed_phones.append(phone)
                failed_details.append(f"🔄 {msg}")
        
        if progress_callback:
            await progress_callback(success_count + len(failed_phones), quantity, success_count, len(failed_phones))
    
    for i in range(0, min(quantity, len(shuffled)), batch_size):
        batch = shuffled[i:i + batch_size]
        tasks = [asyncio.create_task(run_single(session)) for session in batch]
        await asyncio.gather(*tasks)
        
        await asyncio.sleep(0.1)
    
    return success_count, success_phones, failed_phones, failed_details

# ════════════════════════════════════════════════════════════
# ═══ 5. نظام حل الكابتشا المتقدم (يعتمد على الأزرار فقط بدون AI) ═══
# ════════════════════════════════════════════════════════════

RAKSH_CAPTCHA_SOLVE_TIMEOUT = 20
RAKSH_CAPTCHA_MAX_ATTEMPTS = 5
RAKSH_CAPTCHA_BUTTON_WAIT = 0.7

RAKSH_CAPTCHA_PATTERNS = {
    "math": [
        r'كم ناتج[:\s]*(\d+)\s*([+\-*x×])\s*(\d+)',
        r'حل المسألة[:\s]*(\d+)\s*([+\-*x×])\s*(\d+)',
        r'حل المسأله[:\s]*(\d+)\s*([+\-*x×])\s*(\d+)',
        r'المعادلة[:\s]*(\d+)\s*([+\-*x×])\s*(\d+)',
        r'المعادله[:\s]*(\d+)\s*([+\-*x×])\s*(\d+)',
        r'(\d+)\s*([+\-*x×])\s*(\d+)\s*=\s*\?',
        r'(\d+)\s*([+\-*x×])\s*(\d+)\s*=\s*_',
    ],
    "emoji": [
        r'اضغط على\s*\(([^\w\s]{1,5})\)',
        r'انقر على\s*\(([^\w\s]{1,5})\)',
        r'اختر\s*\(([^\w\s]{1,5})\)',
        r'هذا الإيموجي\s*\(([^\w\s]{1,5})\)',
        r'يشبه\s*\(([^\w\s]{1,5})\)',
        r'الرمز هو\s*\(([^\w\s]{1,5})\)',
    ],
    "number": [
        r'أرسل الرقم[:\s]*(\d{4,6})',
        r'ارسل الرقم[:\s]*(\d{4,6})',
        r'الرقم التالي[:\s]*(\d{4,6})',
        r'كود التحقق[:\s]*(\d{4,6})',
        r'الكود هو[:\s]*(\d{4,6})',
    ],
    "rewrite": [
        r'أعد كتابة[:\s]*["\']([^"\']+)["\']',
        r'اكتب[:\s]*["\']([^"\']+)["\']',
        r'أرسل هذا النص[:\s]*["\']([^"\']+)["\']',
        r'انسخ النص[:\s]*["\']([^"\']+)["\']',
    ],
}

def _normalize_captcha_text(value: str) -> str:
    if not value:
        return ""
    return (
        value.replace("\ufe0f", "")
        .replace("\u200d", "")
        .replace("\u200c", "")
        .replace("\u200b", "")
        .strip()
        .lower()
    )

def _extract_emoji_from_captcha(text: str) -> str | None:
    if not text:
        return None
    for pattern in RAKSH_CAPTCHA_PATTERNS["emoji"]:
        match = re.search(pattern, text)
        if match:
            emoji = match.group(1).strip()
            if any('\U0001F000' <= char <= '\U0001FAFF' or '\u2600' <= char <= '\u27BF' or '\u2B00' <= char <= '\u2BFF' for char in emoji):
                return emoji
    return None

def _solve_math_captcha(text: str) -> str | None:
    if not text:
        return None
    for pattern in RAKSH_CAPTCHA_PATTERNS["math"]:
        match = re.search(pattern, text)
        if match:
            try:
                n1 = int(match.group(1))
                op = match.group(2)
                n2 = int(match.group(3))
                if op in ('+', 'x', '×'):
                    return str(n1 + n2 if op == '+' else n1 * n2)
                elif op == '-':
                    return str(n1 - n2)
            except (ValueError, TypeError):
                continue
    return None

def _extract_number_captcha(text: str) -> str | None:
    if not text:
        return None
    for pattern in RAKSH_CAPTCHA_PATTERNS["number"]:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None

def _extract_rewrite_text(text: str) -> str | None:
    if not text:
        return None
    for pattern in RAKSH_CAPTCHA_PATTERNS["rewrite"]:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None

def _button_matches_target(button_text: str, target: str) -> bool:
    if not button_text or not target:
        return False
    clean_button = _normalize_captcha_text(button_text)
    clean_target = _normalize_captcha_text(target)
    return clean_target in clean_button or clean_button in clean_target

def _get_all_button_texts(message) -> list[str]:
    buttons = []
    for row in getattr(message, "buttons", None) or []:
        for button in row:
            text = getattr(button, "text", "")
            if text and not getattr(button, "url", None):
                buttons.append(text)
    return buttons

async def _click_button_by_text(client, message, target_text: str) -> bool:
    if not message or not message.buttons:
        return False
    for row in message.buttons:
        for button in row:
            if _button_matches_target(getattr(button, "text", ""), target_text):
                try:
                    await button.click()
                    await asyncio.sleep(RAKSH_CAPTCHA_BUTTON_WAIT)
                    return True
                except Exception as e:
                    logger.warning(f"فشل الضغط على الزر {button.text}: {e}")
    return False

# ─── استخراج الإيموجي المطلوب من الرسالة ───
def _extract_target_emoji_from_message(text: str) -> str | None:
    if not text:
        return None
    emojis_in_text = re.findall(r'[\U0001F000-\U0001FAFF\u2600-\u27BF]', text)
    if len(emojis_in_text) == 1:
        return emojis_in_text[0]
    if emojis_in_text:
        match = re.search(r'[؟?]\s*([\U0001F000-\U0001FAFF\u2600-\u27BF])', text)
        if match:
            return match.group(1)
        return emojis_in_text[0]
    return None

# ─── الضغط على الزر الذي يحتوي على الإيموجي المطلوب ───
async def _click_button_with_emoji(client, message, target_emoji: str) -> bool:
    if not message or not message.buttons:
        return False
    for row in message.buttons:
        for button in row:
            button_text = getattr(button, "text", "") or ""
            if target_emoji in button_text:
                try:
                    await button.click()
                    await asyncio.sleep(RAKSH_CAPTCHA_BUTTON_WAIT)
                    return True
                except Exception as e:
                    logger.warning(f"فشل الضغط على الزر {button_text}: {e}")
    return False

# ─── الحل الذكي الجديد المعتمد على الأزرار فقط (بدون AI) ───
async def _solve_captcha_smart_with_buttons(client, bot_entity, phone: str = "", max_attempts: int = 3) -> tuple[bool, str]:
    """حل كابتشا 'اضغط على الرمز' عن طريق الضغط على الزر الحقيقي."""
    for attempt in range(max_attempts):
        if attempt > 0:
            await asyncio.sleep(2)
        messages = _as_message_list(await client.get_messages(bot_entity, limit=10))
        for msg in messages:
            text = msg.text or msg.caption or ""
            if not text:
                continue
            
            target_emoji = _extract_target_emoji_from_message(text)
            if target_emoji:
                if await _click_button_with_emoji(client, msg, target_emoji):
                    return True, f"✅ ضغطنا على الزر {target_emoji}"
            
            if msg.buttons:
                flat_buttons = [btn for row in msg.buttons for btn in row]
                for btn in flat_buttons:
                    btn_lower = (btn.text or "").lower()
                    if any(word in btn_lower for word in ['انضمام', 'join', 'تحقق', 'verify', 'التالي', 'تخطي', 'استمرار']):
                        try:
                            await btn.click()
                            await asyncio.sleep(1)
                            break
                        except:
                            pass
                
                if len(flat_buttons) == 1:
                    try:
                        await flat_buttons[0].click()
                        await asyncio.sleep(1)
                        return True, f"✅ ضغطنا على الزر الوحيد: {flat_buttons[0].text}"
                    except:
                        pass
        await asyncio.sleep(1)
    return False, "فشل: لم نعثر على زر الإيموجي المطلوب"
