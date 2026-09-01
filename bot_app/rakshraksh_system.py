"""
نظام الرشق المتقدم - منفصل تماماً عن بقية البوت
نسخة محسّنة مع دالة تحقق شاملة
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
)
from telethon.tl.functions.contacts import ResolveUsernameRequest
from telethon.tl.functions.stories import IncrementStoryViewsRequest, SendReactionRequest
from telethon.tl.types import ReactionEmoji, InputMediaContact
from urllib.parse import parse_qs, urlparse
import random
import asyncio
import re
import time

# ════════════════════════════════════════════════════════════
# ═══ 1. الثوابت والإعدادات ═══
# ════════════════════════════════════════════════════════════

RAKSH_PAID_REACTION = "__raksh_paid_reaction__"
RAKSH_PAID_REACTION_LABEL = "⭐ تفاعل مدفوع"
RAKSH_CUSTOM_REACTION_PREFIX = "__raksh_custom_reaction__:"
RAKSH_REACTION_LOOKUP_MAX_SESSIONS = 3
RAKSH_REACTION_LOOKUP_TIMEOUT_SECONDS = 5
RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS = 4
RAKSH_MIN_DELAY_SECONDS = 60
RAKSH_MAX_DELAY_SECONDS = 180
RAKSH_VOTE_DELAY_SECONDS = 3
RAKSH_MAX_EXECUTIONS_PER_HOUR = 100

RAKSH_SERVICES = {
    "story": {
        "name": "📱 رشق مشاهدة ستوري وتفاعل",
        "price_points": 30,
        "points_quantity": 1,
        "price_stars": 1,
        "stars_quantity": 10,
        "has_channel": True,
        "has_reaction": False,  # تفاعل تلقائي بدون طلب
        "has_ai": False,
        "needs_link": True,
        "max_quantity": 999,
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
        "max_quantity": 999,
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
        "max_quantity": 999,
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
        "max_quantity": 999,
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
        "max_quantity": 999,
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
        "max_quantity": 999,
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
        "max_quantity": 999,
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
        "max_quantity": 999,
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

# ════════════════════════════════════════════════════════════
# ═══ 2. إدارة الجلسات ═══
# ════════════════════════════════════════════════════════════

_RAKSH_SESSION_LOCKS: dict[str, asyncio.Lock] = {}
_RAKSH_SESSION_CACHE: dict[str, list] = {}
_RAKSH_SESSION_CACHE_TIME: dict[str, float] = {}
_RAKSH_SESSION_CACHE_TTL = 60

def _get_raksh_session_lock(phone_number: str) -> asyncio.Lock:
    key = str(phone_number or "").strip()
    if key not in _RAKSH_SESSION_LOCKS:
        _RAKSH_SESSION_LOCKS[key] = asyncio.Lock()
    return _RAKSH_SESSION_LOCKS[key]

def _positive_setting(key: str, fallback: int) -> int:
    try:
        value = int(get_setting(key) or fallback)
        return value if value > 0 else fallback
    except (TypeError, ValueError):
        return fallback

def get_raksh_price_config(service_type: str) -> dict[str, int]:
    svc = RAKSH_SERVICES[service_type]
    keys = RAKSH_PRICE_KEYS[service_type]
    return {
        "points_price": _positive_setting(keys["points_price"], svc["price_points"]),
        "points_quantity": _positive_setting(keys["points_quantity"], svc["points_quantity"]),
        "stars_price": _positive_setting(keys["stars_price"], svc["price_stars"]),
        "stars_quantity": _positive_setting(keys["stars_quantity"], svc["stars_quantity"]),
    }

def get_raksh_total(service_type: str, quantity: int, payment_method: str) -> int:
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
    keys_to_clear = [
        "raksh_service", "raksh_step", "raksh_channels", "raksh_link",
        "raksh_reaction", "raksh_available_reactions", "raksh_comment",
        "raksh_poll_option", "raksh_delay_seconds", "raksh_quantity",
        "raksh_payment_method", "raksh_price_edit_service",
    ]
    for key in keys_to_clear:
        context.user_data.pop(key, None)
    context.user_data["state"] = "main_menu"

def _get_all_active_sessions(service_type: str | None = None) -> list[dict]:
    cache_key = f"sessions_{service_type or 'all'}"
    if cache_key in _RAKSH_SESSION_CACHE:
        cache_time = _RAKSH_SESSION_CACHE_TIME.get(cache_key, 0)
        if time.time() - cache_time < _RAKSH_SESSION_CACHE_TTL:
            return _RAKSH_SESSION_CACHE[cache_key].copy()

    with db_conn() as c:
        rows = c.execute(
            """
            SELECT id, phone_number, session_string, raksh_only, last_authorized
            FROM number_stock
            WHERE session_string IS NOT NULL
              AND BTRIM(session_string) <> ''
              AND deleted_at IS NULL
              AND forced_ref_excluded IS NOT TRUE
            ORDER BY last_authorized DESC NULLS LAST, id ASC
            """
        ).fetchall()
        sessions = [dict(row) for row in rows]
        _RAKSH_SESSION_CACHE[cache_key] = sessions
        _RAKSH_SESSION_CACHE_TIME[cache_key] = time.time()
        return sessions

def get_available_sessions_count(service_type: str = None) -> int:
    return len(_get_all_active_sessions(service_type))

def _mark_raksh_session_unauthorized(phone_number: str) -> None:
    if not phone_number:
        return
    try:
        with db_conn() as c:
            c.execute(
                "UPDATE number_stock SET last_authorized=FALSE "
                "WHERE phone_number=%s AND deleted_at IS NULL",
                (phone_number,)
            )
        _RAKSH_SESSION_CACHE.clear()
        _RAKSH_SESSION_CACHE_TIME.clear()
    except Exception:
        pass

def _get_delay_seconds(service_type: str | None = None, custom_delay: int | None = None) -> int:
    if service_type in {"forced_ref", "forced_ref_ai"}:
        if custom_delay is not None:
            return custom_delay
        return 180
    if service_type == "votes_ai":
        return 0
    if service_type == "votes":
        return RAKSH_VOTE_DELAY_SECONDS
    return random.randint(RAKSH_MIN_DELAY_SECONDS, RAKSH_MAX_DELAY_SECONDS)

def _reserve_raksh_execution_slot(user_id: int, service_type: str, phone_number: str) -> bool:
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
        logger.exception(f"فشل حجز تنفيذ للمستخدم {user_id}")
        return False

# ════════════════════════════════════════════════════════════
# ═══ 3. دوال التحليل ═══
# ════════════════════════════════════════════════════════════

def _parse_story_link(value: str) -> tuple[str | None, int | None]:
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

def _parse_post_link(value: str) -> tuple[str | None, int | None]:
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

def _parse_bot_link(value: str) -> tuple[str | None, str | None]:
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

def _parse_channel_refs(value: str) -> list[str]:
    if not value:
        return []
    refs = []
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

def _find_bot_start_link(message) -> tuple[str | None, str | None]:
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

def _extract_code_from_text(text: str) -> str | None:
    if not text:
        return None
    if text.strip().startswith("/"):
        return None
    if text.strip().lower() in {"start", "/start", "بدء"}:
        return None

    common_words = {
        "الآن", "أرسل", "النص", "التالي", "المرحلة", "الأولى", "بالضبط", "اكتب",
        "type", "أدخل", "enter", "التحقق", "رابط", "الإحالة", "start", "ref",
        "مرحباً", "يجب", "إكمال", "المتابعة", "حل", "العملية", "الحسابية",
        "مشاركة", "جهة", "اتصال", "هاتف", "رقم", "الموبايل", "mobile", "phone",
        "contact", "share"
    }

    patterns = [
        r'(?:الآن\s*أرسل\s*النص\s*التالي|أرسل\s*النص\s*التالي|اكتب|type|أدخل|enter)\s*[:\-]?\s*([A-Za-z0-9]{3,50})',
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
        return raw_matches[-1]

    return None

# ════════════════════════════════════════════════════════════
# ═══ 4. دوال الانضمام للقنوات ═══
# ════════════════════════════════════════════════════════════

async def _join_channel_and_schedule_leave(client, channel_refs):
    """الانضمام للقنوات الإجبارية في جميع الخدمات"""
    if isinstance(channel_refs, str):
        channel_refs = _parse_channel_refs(channel_refs)
    if not channel_refs:
        return

    for ref in channel_refs:
        try:
            if ref.startswith("invite:"):
                await client(ImportChatInviteRequest(ref.split(":", 1)[1]))
            else:
                entity = await client.get_entity(ref)
                await client(JoinChannelRequest(entity))
            logger.info(f"✅ تم الانضمام للقناة: {ref}")
        except Exception as exc:
            if "USER_ALREADY_PARTICIPANT" not in str(exc).upper():
                logger.warning(f"تعذر الانضمام للقناة {ref}: {exc}")

async def _join_discussion_group(client, discussion):
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

# ════════════════════════════════════════════════════════════
# ═══ 5. دوال التصويت ═══
# ════════════════════════════════════════════════════════════

def _normalize_digits(value: str) -> str:
    return (value or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))

def _select_poll_option(options, requested: str):
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

# ════════════════════════════════════════════════════════════
# ═══ 6. حل التحقق الشامل للإحالة ═══
# ════════════════════════════════════════════════════════════

async def _solve_forced_ref_verification(client, bot_entity, phone_number: str) -> bool:
    """
    حل التحقق للإحالة البوتية - يدعم:
    1. إرسال كود نصي
    2. حل مسائل رياضية
    3. الضغط على أزرار التحقق
    4. مشاركة جهة الاتصال
    """
    max_attempts = 20
    base_id = 0

    try:
        out_messages = await client.get_messages(bot_entity, limit=10)
        for msg in out_messages:
            if msg.out:
                base_id = msg.id
                break
    except Exception:
        pass

    for attempt in range(max_attempts):
        try:
            messages = await client.get_messages(bot_entity, limit=20)
        except Exception:
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
            if any(kw in msg_text for kw in ["أرسل", "التالي", "اكتب", "type", "اضغط", "اختر"]):
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

        # 1️⃣ إرسال الكود المطلوب
        send_text = _extract_code_from_text(text)
        if send_text:
            try:
                await client.send_message(bot_entity, send_text)
                logger.info(f"✅ تم إرسال الكود: {send_text}")
                return True
            except Exception:
                return False

        # 2️⃣ حل مسألة رياضية
        math_patterns = [
            (r'(\d+)\s*([+\-*/])\s*(\d+)\s*=\s*\?', 1, 2, 3),
            (r'(\d+)\s*([+\-*/])\s*(\d+)\s*=', 1, 2, 3),
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

        # 3️⃣ مشاركة جهة الاتصال
        if any(kw in text.lower() for kw in ["مشاركة", "جهة اتصال", "شارك", "contact", "share"]):
            try:
                me = await client.get_me()
                await client.send_file(
                    bot_entity,
                    InputMediaContact(
                        phone_number=me.phone,
                        first_name=me.first_name or "",
                        last_name=me.last_name or "",
                        vcard="",
                    ),
                )
                logger.info(f"✅ تم مشاركة جهة الاتصال من {phone_number}")
                return True
            except Exception as e:
                logger.warning(f"فشل مشاركة جهة الاتصال: {e}")

        # 4️⃣ الضغط على أزرار التحقق
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

# ════════════════════════════════════════════════════════════
# ═══ 7. تنفيذ مشاهدة ستوري (تفاعل تلقائي) ═══
# ════════════════════════════════════════════════════════════

async def _execute_story(session, params, is_first):
    """تنفيذ رشق مشاهدة ستوري مع تفاعل تلقائي"""
    from telethon.tl.functions.stories import IncrementStoryViewsRequest, SendReactionRequest
    from telethon.tl.types import ReactionEmoji

    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            _mark_raksh_session_unauthorized(session.get("phone_number"))
            return False, "الجلسة غير مصرح بها"

        # الانضمام للقنوات الإجبارية
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])

        entity_ref, story_id = _parse_story_link(params["link"])
        if not entity_ref or not story_id:
            return False, "رابط الستوري غير صحيح"

        entity = await client.get_entity(entity_ref)

        # مشاهدة الستوري
        await client(IncrementStoryViewsRequest(peer=entity, id=story_id))

        # تفاعل تلقائي (اختيار عشوائي من الإيموجيات المتاحة)
        try:
            reaction = random.choice(list(RAKSH_REACTIONS.values()))
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
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

# ════════════════════════════════════════════════════════════
# ═══ 8. تنفيذ إحالة بوت إجباري مع تحقق ═══
# ════════════════════════════════════════════════════════════

async def _execute_forced_ref_ai(session, params, is_first):
    """تنفيذ إحالة بوت إجباري مع تحقق شامل"""
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            _mark_raksh_session_unauthorized(session.get("phone_number"))
            return False, "الجلسة غير مصرح بها"

        # الانضمام للقنوات الإجبارية
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])

        # تحليل رابط البوت
        bot_username, start_param = _parse_bot_link(params["link"])
        if not bot_username:
            return False, "رابط البوت غير صحيح"

        clean_username = bot_username.lstrip("@").strip()
        resolved = await client(ResolveUsernameRequest(clean_username))
        bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]

        # الضغط على رابط البوت
        await client(StartBotRequest(
            bot=bot_entity,
            peer=bot_entity,
            start_param=start_param or ""
        ))
        await asyncio.sleep(2.0)

        # حل التحقق الشامل
        success = await _solve_forced_ref_verification(client, bot_entity, session.get("phone_number"))

        if success:
            return True, f"✅ تمت الإحالة مع التحقق من {session['phone_number']}"
        else:
            return False, "فشل التحقق بعد محاولات متعددة"

    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

# ════════════════════════════════════════════════════════════
# ═══ 9. تنفيذ تصويت مع تحقق (رابط بوت مباشر أو رابط بوست) ═══
# ════════════════════════════════════════════════════════════

async def _execute_votes_ai(session, params, is_first):
    """
    تنفيذ تصويت مع تحقق - يدعم:
    1. رابط بوت مباشر (t.me/Bot?start=xxx)
    2. رابط بوست يحتوي على زر بوت
    3. الانضمام للقنوات الإجبارية
    """
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            _mark_raksh_session_unauthorized(session.get("phone_number"))
            return False, "الجلسة غير مصرح بها"

        # الانضمام للقنوات الإجبارية
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])

        # تحليل الرابط
        bot_username = None
        bot_start_param = None
        link = params.get("link", "")

        # 1. محاولة تحليل كرابط بوت مباشر
        parsed_bot = _parse_bot_link(link)
        if parsed_bot[0]:
            bot_username = parsed_bot[0]
            bot_start_param = parsed_bot[1] or ""
            logger.info(f"✅ رابط بوت مباشر: @{bot_username}")
        else:
            # 2. محاولة تحليل كرابط بوست
            post_ref, post_id = _parse_post_link(link)
            if not post_ref or not post_id:
                return False, "الرابط غير صالح (ليس بوتاً ولا بوستاً)"

            try:
                post_entity = await client.get_entity(post_ref)
                messages = await client.get_messages(post_entity, ids=post_id)
                if isinstance(messages, (list, tuple)):
                    post_message = messages[0] if messages else None
                else:
                    post_message = messages

                if not post_message:
                    return False, "المنشور غير موجود"

                bot_username, bot_start_param = _find_bot_start_link(post_message)

                if not bot_username or not bot_start_param:
                    # محاولة استخراج من نص المنشور
                    post_text = getattr(post_message, "message", "") or ""
                    bot_match = re.search(r't\.me/([A-Za-z0-9_]+bot)\?start=([A-Za-z0-9_]+)', post_text)
                    if bot_match:
                        bot_username = bot_match.group(1)
                        bot_start_param = bot_match.group(2)

                if not bot_username:
                    return False, "المنشور لا يحتوي على رابط بوت صالح"

                logger.info(f"✅ تم استخراج بوت من المنشور: @{bot_username}")

            except Exception as e:
                return False, f"تعذر الوصول إلى المنشور: {str(e)[:80]}"

        if not bot_username:
            return False, "لم يتم العثور على بوت صالح"

        # الدخول إلى البوت
        try:
            bot_entity = await client.get_entity(bot_username)
        except Exception:
            try:
                bot_entity = await client.get_entity(f"@{bot_username}")
            except Exception as e:
                return False, f"تعذر العثور على البوت @{bot_username}: {str(e)[:80]}"

        await client(StartBotRequest(
            bot=bot_entity,
            peer=bot_entity,
            start_param=bot_start_param or ""
        ))
        await asyncio.sleep(2.0)

        # البحث عن رسالة التحقق
        verification_message = None
        for attempt in range(5):
            msgs = await client.get_messages(bot_entity, limit=30)
            if isinstance(msgs, (list, tuple)):
                for msg in msgs:
                    if getattr(msg, "buttons", None):
                        has_callback = False
                        for row in msg.buttons:
                            for btn in row:
                                if not getattr(btn, "url", None):
                                    has_callback = True
                                    break
                            if has_callback:
                                break
                        if has_callback:
                            verification_message = msg
                            break
                if verification_message:
                    break
            await asyncio.sleep(1.0)

        if not verification_message:
            return True, f"✅ تم التصويت من {session['phone_number']} (بدون تحقق)"

        # استخراج الإيموجي المطلوب
        verification_text = getattr(verification_message, "message", "") or ""
        target_emoji = None
        emoji_pattern = re.compile(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]")
        found_emojis = emoji_pattern.findall(verification_text)
        if found_emojis:
            target_emoji = found_emojis[-1]

        # جمع الأزرار
        all_buttons = []
        for row in (getattr(verification_message, "buttons", None) or []):
            for btn in row:
                if not getattr(btn, "url", None):
                    all_buttons.append(btn)

        if not all_buttons:
            return True, f"✅ تم التصويت من {session['phone_number']}"

        # اختيار الزر المناسب
        chosen_button = None

        # 1. زر يطابق الإيموجي
        if target_emoji:
            for btn in all_buttons:
                btn_text = getattr(btn, "text", "") or ""
                if target_emoji in btn_text or btn_text == target_emoji:
                    chosen_button = btn
                    break

        # 2. زر تحقق/متابعة
        if not chosen_button:
            verify_keywords = ["تحقق", "verify", "اضغط هنا", "continue", "التالي", "تأكيد"]
            for btn in all_buttons:
                btn_text = (getattr(btn, "text", "") or "").lower()
                if any(kw in btn_text for kw in verify_keywords):
                    chosen_button = btn
                    break

        # 3. أي زر إيموجي
        if not chosen_button:
            for btn in all_buttons:
                btn_text = getattr(btn, "text", "") or ""
                if emoji_pattern.search(btn_text):
                    chosen_button = btn
                    break

        # 4. أي زر
        if not chosen_button and all_buttons:
            chosen_button = all_buttons[0]

        if not chosen_button:
            return False, "لم يتم العثور على زر مناسب"

        try:
            await chosen_button.click()
            await asyncio.sleep(2.0)

            success_keywords = [
                "تم التصويت", "صوتك مسجل", "vote recorded",
                "شكراً لتصويتك", "تم تسجيل تصويتك"
            ]

            final_msgs = await client.get_messages(bot_entity, limit=5)
            for msg in final_msgs:
                msg_text = getattr(msg, "message", "") or ""
                if any(kw in msg_text for kw in success_keywords):
                    return True, f"✅ تم التصويت مع التحقق من {session['phone_number']}"

            return True, f"✅ تم تنفيذ التصويت من {session['phone_number']}"

        except Exception as e:
            return False, f"فشل الضغط على الزر: {str(e)[:80]}"

    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

# ════════════════════════════════════════════════════════════
# ═══ 10. دوال الخدمات الأخرى ═══
# ════════════════════════════════════════════════════════════

async def _execute_forced_ref(session, params, is_first):
    """تنفيذ إحالة بوت إجباري (بدون تحقق)"""
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
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_comment(session, params, is_first):
    """تنفيذ رشق تعليق"""
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            _mark_raksh_session_unauthorized(session.get("phone_number"))
            return False, "الجلسة غير مصرح بها"

        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])

        comment_text = (params.get("comment_text") or "").strip()
        if not comment_text:
            return False, "نص التعليق فارغ"

        post_ref, post_id = _parse_post_link(params["link"])
        if not post_ref or not post_id:
            return False, "رابط المنشور غير صحيح"

        post_entity = await client.get_entity(post_ref)
        discussion = await client(functions.messages.GetDiscussionMessageRequest(peer=post_entity, msg_id=post_id))

        if not getattr(discussion, "messages", None):
            return False, "المنشور لا يملك نقاشاً"

        discussion_message = discussion.messages[0]
        discussion_peer = getattr(discussion_message, "peer_id", None)
        if discussion_peer is None:
            return False, "تعذر تحديد مساحة التعليقات"

        discussion_chat = await _join_discussion_group(client, discussion)
        sent_message = await client.send_message(
            discussion_chat,
            comment_text,
            reply_to=discussion_message.id,
        )

        if not getattr(sent_message, "id", None):
            return False, "تعذر تأكيد إرسال التعليق"

        return True, f"✅ تم التعليق من {session['phone_number']}"
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_poll(session, params, is_first):
    """تنفيذ رشق استفتاء"""
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            _mark_raksh_session_unauthorized(session.get("phone_number"))
            return False, "الجلسة غير مصرح بها"

        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])

        entity_ref, msg_id = _parse_post_link(params["link"])
        if not entity_ref or not msg_id:
            return False, "رابط الاستفتاء غير صحيح"

        entity = await client.get_entity(entity_ref)
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
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_votes(session, params, is_first):
    """تنفيذ رشق أصوات"""
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

        vote_button = None
        for row in getattr(message, "buttons", None) or []:
            for btn in row:
                if getattr(btn, "url", None):
                    continue
                btn_text = (getattr(btn, "text", None) or "").lower()
                if any(word in btn_text for word in ["تصويت", "صوت", "vote"]):
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
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_premium_reaction(session, params, is_first):
    """تنفيذ رشق تفاعل مميز"""
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=15)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            _mark_raksh_session_unauthorized(session.get("phone_number"))
            return False, "الجلسة غير مصرح بها"

        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])

        post_ref, post_id = _parse_post_link(params["link"])
        if not post_ref or not post_id:
            return False, "رابط المنشور غير صحيح"

        post_entity = await client.get_entity(post_ref)

        reaction = params.get("reaction")
        if not reaction or reaction == "random":
            available_reactions = params.get("available_reactions") or list(RAKSH_REACTIONS.values())
            reaction = random.choice(available_reactions)

        if reaction == RAKSH_PAID_REACTION:
            try:
                from telethon.tl.types import ReactionPaid
                reaction_value = ReactionPaid()
            except ImportError:
                return False, "التفاعل المدفوع غير مدعوم"
        elif (custom_document_id := _custom_reaction_document_id(reaction)) is not None:
            try:
                from telethon.tl.types import ReactionCustomEmoji
                reaction_value = ReactionCustomEmoji(document_id=custom_document_id)
            except ImportError:
                return False, "التفاعلات المميزة غير مدعومة"
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

# ════════════════════════════════════════════════════════════
# ═══ 11. دوال مساعدة للتفاعلات ═══
# ════════════════════════════════════════════════════════════

def _reaction_emoticons(reactions) -> list[str]:
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

def _custom_reaction_document_id(value: str) -> int | None:
    if not isinstance(value, str) or not value.startswith(RAKSH_CUSTOM_REACTION_PREFIX):
        return None
    raw_id = value[len(RAKSH_CUSTOM_REACTION_PREFIX):]
    return int(raw_id) if raw_id.isdigit() else None

async def _fetch_raksh_reactions(session: dict, post_ref: str, post_id: int) -> list[str]:
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

        full_channel = await asyncio.wait_for(
            client(functions.channels.GetFullChannelRequest(channel=post_entity)),
            timeout=RAKSH_REACTION_OPERATION_TIMEOUT_SECONDS
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
    except Exception:
        return []
    finally:
        await client.disconnect()

async def _fetch_raksh_reactions_from_pool(sessions: list[dict], post_ref: str, post_id: int) -> list[str]:
    if not sessions:
        return []

    max_samples = min(RAKSH_REACTION_LOOKUP_MAX_SESSIONS, len(sessions))
    candidates = random.sample(sessions, max_samples) if max_samples > 0 else []

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
# ═══ 12. دوال التنفيذ الرئيسية ═══
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
    if not sessions:
        raise RuntimeError("لا توجد جلسات نشطة متاحة")

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

    for i in range(quantity):
        if not shuffled:
            break

        session = shuffled.pop(0)
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
# ═══ 13. دوال الواجهة والأزرار ═══
# ════════════════════════════════════════════════════════════

def _is_raksh_service_enabled(service_type: str) -> bool:
    return get_setting(f"raksh_service_enabled_{service_type}").strip().lower() not in {
        "0", "false", "off", "hidden", "disabled"
    }

def _set_raksh_service_enabled(service_type: str, enabled: bool) -> None:
    set_setting(f"raksh_service_enabled_{service_type}", "1" if enabled else "0")

def _get_max_quantity(service_type: str | None = None) -> int:
    available = get_available_sessions_count(service_type)
    if service_type and service_type in RAKSH_SERVICES:
        max_q = RAKSH_SERVICES[service_type].get("max_quantity", 999)
        return min(available, max_q)
    return available

def _get_request_limit(user_id: int, service_type: str | None = None) -> int:
    return min(
        _get_max_quantity(service_type),
        get_raksh_hourly_remaining(user_id),
    )

def get_raksh_hourly_remaining(user_id: int) -> int:
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
        return 0

def _chunk_lines(lines: list[str], max_chars: int = 3500) -> list[str]:
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

def _raksh_link_error(service_type: str, value: str) -> str | None:
    if not value.strip():
        return "⚠️ الرابط لا يمكن أن يكون فارغاً"

    if service_type in {"forced_ref", "forced_ref_ai"}:
        bot_username, _ = _parse_bot_link(value)
        if not bot_username:
            return "⚠️ رابط البوت غير صحيح.\nأرسله بهذا الشكل:\n@BotUsername start123\nأو: t.me/BotUsername?start=123"
        return None

    if service_type == "story":
        if not all(_parse_story_link(value)):
            return "⚠️ رابط الستوري غير صحيح.\nأرسله بهذا الشكل:\nhttps://t.me/username/s/123"
        return None

    if service_type in {"votes_ai", "votes"}:
        if not ("@" in value or "t.me/" in value):
            return "⚠️ الرابط يجب أن يحتوي على @username أو t.me/"
        return None

    if not all(_parse_post_link(value)):
        return "⚠️ الرابط غير صحيح لهذه الخدمة."
    return None

def _get_link_instruction(service_type: str) -> str:
    instructions = {
        "story": "https://t.me/username/s/123 أو https://t.me/username/story/123",
        "forced_ref": "@BotUsername start123  أو  t.me/BotUsername?start=123",
        "forced_ref_ai": "@BotUsername start123  أو  t.me/BotUsername?start=123",
        "comment": "https://t.me/channel/123",
        "poll": "https://t.me/channel/123",
        "votes": "https://t.me/channel/123",
        "votes_ai": "رابط بوت مباشر أو رابط بوست يحتوي زر بوت",
        "premium_reaction": "https://t.me/channel/123",
    }
    return instructions.get(service_type, "أرسل الرابط المطلوب")

def _parse_raksh_rate_updates(text: str) -> dict[str, tuple[int, int]]:
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

# ════════════════════════════════════════════════════════════
# ═══ 14. أزرار الواجهة ═══
# ════════════════════════════════════════════════════════════

def raksh_menu_kb(is_owner: bool = False):
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
        buttons.append([
            InlineKeyboardButton(
                "⚙️ إدارة الأسعار",
                callback_data="raksh:settings",
            )
        ])

    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def raksh_price_settings_kb():
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭️ تخطي (بدون قنوات)", callback_data="raksh:skip_channels")],
        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")],
    ])

def raksh_reaction_kb(service_type: str, reactions: list = None):
    buttons = []
    row = []

    if reactions:
        reaction_items = reactions
    else:
        reaction_items = list(RAKSH_REACTIONS.values())

    for item in reaction_items:
        if isinstance(item, dict):
            reaction_label = item.get("label", "")
            callback_key = item.get("callback", reaction_label)
        else:
            reaction_label = item
            callback_key = item

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
# ═══ 15. معالج الأزرار الرئيسي ═══
# ════════════════════════════════════════════════════════════

async def handle_raksh_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query=None,
    data=None,
    user=None,
    is_own=None,
):
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
            "يمكنك إرسال أكثر من قناة، كل قناة في سطر أو مفصولة بمسافة\n"
            "مثال: @channel1\n@channel2\n\n"
            "أو اضغط تخطي:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_channel_kb()
        )
        return

    if data == "raksh:skip_channels":
        context.user_data["raksh_channels"] = []
        context.user_data["raksh_step"] = "link"
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
                f"⚠️ لا يمكن قبول هذا العدد حالياً. الحد المتاح: {request_limit} وحدة.",
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

        await _start_raksh_execution(
            update, context, query, service_type, quantity, payment_method, total_cost
        )
        return

# ════════════════════════════════════════════════════════════
# ═══ 16. معالج النصوص ═══
# ════════════════════════════════════════════════════════════

async def handle_raksh_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                "⚠️ لم أفهم الصيغة.\nاستخدم مثلاً:\n⭐ نجوم 1 لكل 10\n💰 نقاط 30 لكل 1",
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
                "⚠️ لم أتعرف على أي قناة.\nأرسل @username أو رابط t.me للقناة.",
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

    if state == "link":
        service_type = context.user_data.get("raksh_service")

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
        if service_type in {"votes_ai"}:
            context.user_data["raksh_step"] = "quantity"
            max_qty = _get_request_limit(user.id, service_type)
            if max_qty < 1:
                await update.message.reply_text("⚠️ لا توجد حسابات متاحة حالياً.")
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
        if service_type == "premium_reaction":
            post_ref, post_id = _parse_post_link(text)
            if not post_ref or post_id is None:
                await update.message.reply_text("⚠️ تعذر تحليل رابط المنشور.")
                return True

            sessions = _get_all_active_sessions(service_type)
            if not sessions:
                await update.message.reply_text("⚠️ لا توجد حسابات متاحة حالياً.")
                return True

            reaction_options = await _fetch_raksh_reactions_from_pool(
                sessions, post_ref, post_id
            )

            if not reaction_options:
                reaction_options = list(RAKSH_REACTIONS.values())

            # تحويل القائمة
            formatted_reactions = []
            for r in reaction_options:
                if r == RAKSH_PAID_REACTION:
                    formatted_reactions.append({"label": "⭐ تفاعل مدفوع", "callback": "paid"})
                else:
                    formatted_reactions.append({"label": r, "callback": r})

            formatted_reactions.append({"label": "🎲 عشوائي", "callback": "random"})

            context.user_data["raksh_available_reactions"] = formatted_reactions
            context.user_data["raksh_step"] = "reaction"
            await update.message.reply_text(
                f"✅ تم حفظ الرابط.\n\n"
                f"✨ *اختر التفاعل المطلوب من المنشور:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=raksh_reaction_kb(
                    service_type,
                    context.user_data.get("raksh_available_reactions")
                )
            )
            return True

        if service_type == "story":
            # ستوري - تفاعل تلقائي، لا نطلب من المستخدم اختيار
            context.user_data["raksh_step"] = "quantity"
            max_qty = _get_request_limit(user.id, service_type)
            if max_qty < 1:
                await update.message.reply_text("⚠️ لا توجد حسابات متاحة حالياً.")
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

        context.user_data["raksh_step"] = "quantity"
        max_qty = _get_request_limit(user.id, service_type)
        if max_qty < 1:
            await update.message.reply_text("⚠️ لا توجد حسابات متاحة حالياً.")
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

    if state == "comment_text":
        context.user_data["raksh_comment"] = text
        context.user_data["raksh_step"] = "quantity"
        service_type = context.user_data.get("raksh_service")
        max_qty = _get_request_limit(user.id, service_type)
        if max_qty < 1:
            await update.message.reply_text("⚠️ لا توجد حسابات متاحة حالياً.")
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
            await update.message.reply_text("⚠️ لا توجد حسابات متاحة حالياً.")
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
            await update.message.reply_text("⚠️ لا توجد حسابات متاحة حالياً.")
            return True

        if quantity < 1 or quantity > max_qty:
            await update.message.reply_text(
                f"⚠️ العدد المسموح بين 1 و {max_qty}.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ]),
            )
            return True

        svc = RAKSH_SERVICES.get(service_type)
        points_cost = get_raksh_total(service_type, quantity, "points")
        stars_cost = get_raksh_total(service_type, quantity, "stars")

        context.user_data["raksh_quantity"] = quantity

        if user.id == OWNER_ID and service_type in {"forced_ref", "forced_ref_ai"}:
            context.user_data["raksh_step"] = "delay"
            await update.message.reply_text(
                "⏱️ *إعداد الفاصل الزمني*\n\n"
                "أرسل عدد الثواني بين تفعيل حساب وآخر.\n"
                "للأعضاء يبقى الوقت ثابتاً: 180 ثانية.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
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

    if state == "delay":
        service_type = context.user_data.get("raksh_service")
        if service_type not in {"forced_ref", "forced_ref_ai"} or user.id != OWNER_ID:
            context.user_data["raksh_step"] = "quantity"
            return True
        try:
            delay_seconds = int(text.strip())
        except ValueError:
            await update.message.reply_text("⚠️ أرسل عدد الثواني كرقم صحيح.")
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
            f"الخدمة: {svc['name']}\n"
            f"العدد: {quantity}\n"
            f"💰 السعر بالنقاط: {points_cost} نقطة\n"
            f"⭐ السعر بالنجوم: {stars_cost} نجمة\n\n"
            f"اختر طريقة الدفع:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_payment_kb(service_type, quantity, points_cost, stars_cost)
        )
        return True

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
            f"الخدمة: {svc['name']}\n"
            f"العدد: {quantity}\n"
            f"التكلفة: {total} نجمة\n\n"
            "اضغط «تأكيد الطلب» للبدء.",
            reply_markup=raksh_confirm_kb(service_type, quantity, total, method),
        )
        return True

    return False

# ════════════════════════════════════════════════════════════
# ═══ 17. معالجات الدفع ═══
# ════════════════════════════════════════════════════════════

async def raksh_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
# ═══ 18. تنفيذ الطلب ═══
# ════════════════════════════════════════════════════════════

async def _send_raksh_order_to_group(bot, user_id: int, quantity: int, payment_method: str, service_type: str):
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
    success_phones: list[str],
    failed_phones: list[str],
    failed_details: list[str],
):
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

        # أزرار الطرد للحسابات الفاشلة
        kick_buttons = []
        with db_conn() as c:
            for phone in failed_phones:
                row = c.execute(
                    "SELECT session_string, id FROM number_stock WHERE phone_number=%s",
                    (phone,)
                ).fetchone()
                if not row or not row["session_string"]:
                    if row:
                        kick_buttons.append([
                            InlineKeyboardButton(
                                f"🚫 طرد {phone}",
                                callback_data=f"fref_kick:{row['id']}:{phone}"
                            )
                        ])

        for chunk in _chunk_lines(lines):
            await bot.send_message(OWNER_ID, chunk)

        if kick_buttons:
            await bot.send_message(
                OWNER_ID,
                "⚠️ الحسابات الفاشلة التي ليس لها جلسة (يمكنك طردها):",
                reply_markup=InlineKeyboardMarkup(kick_buttons)
            )

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

    await _send_raksh_owner_result(
        context.bot,
        service_type,
        quantity,
        success_phones,
        failed_phones,
        failed_details,
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
# ═══ 19. الأمر الرئيسي ═══
# ════════════════════════════════════════════════════════════

async def cmd_raksh(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
