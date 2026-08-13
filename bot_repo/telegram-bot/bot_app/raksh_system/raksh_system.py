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
from ..users import get_setting, set_setting
from ..ui import main_menu_kb
from telethon import TelegramClient, functions
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, SendVoteRequest, StartBotRequest
from telethon.tl.functions.contacts import ResolveUsernameRequest
from telethon.tl.functions.stories import IncrementStoryViewsRequest, SendReactionRequest
from telethon.tl.types import ReactionEmoji
from urllib.parse import urlparse
import random
import asyncio
import re

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
        "raksh_comment",
        "raksh_poll_option",
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
RAKSH_MAX_DELAY_SECONDS = 8 * 60
RAKSH_MAX_EXECUTIONS_PER_HOUR = 12

def _get_delay_seconds(service_type: str | None = None) -> int:
    """فاصل عشوائي بين كل حساب والذي يليه لجميع خدمات الرشق."""
    return random.randint(RAKSH_MIN_DELAY_SECONDS, RAKSH_MAX_DELAY_SECONDS)

def get_raksh_hourly_remaining(user_id: int) -> int:
    """عدد التنفيذات المتبقية للمستخدم خلال آخر ساعة متحركة."""
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
    try:
        with db_conn() as c:
            # قفل خاص بالمستخدم داخل المعاملة الحالية لمنع سباق طلبين متزامنين.
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
    """جلب كل الجلسات المخزنة التي يمكن استخدامها لخدمات الرشق.

    يستخدم نفس شروط مخزون «إحالة بوت إجباري» حتى يطابق العدد المعروض
    عدد الجلسات التي سيحاول نظام الرشق استخدامها فعلياً.
    """
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
        query = parsed.query
        if path:
            bot_username = path.split("/")[0]
            start_param = ""
            if query.startswith("start="):
                start_param = query.split("=")[1]
            return bot_username, start_param
    else:
        parts = value.split()
        if len(parts) >= 1:
            bot_username = parts[0].lstrip("@")
            start_param = parts[1] if len(parts) > 1 else ""
            return bot_username, start_param
    return None, None

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

def raksh_reaction_kb(service_type: str):
    """أزرار اختيار التفاعل (لخدمتي ستوري وتفاعل مميز)"""
    buttons = []
    row = []
    for reaction_key, reaction in RAKSH_REACTIONS.items():
        row.append(InlineKeyboardButton(reaction, callback_data=f"raksh:reaction:{service_type}:{reaction_key}"))
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
        if ref.startswith("invite:"):
            await client(ImportChatInviteRequest(ref.split(":", 1)[1]))
        else:
            entity = await client.get_entity(ref)
            await client(JoinChannelRequest(entity))

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

    # Telegram can accept the request while omitting `chosen` in the
    # response, so the caller still counts the successful API request.
    return False

# ─── تنفيذ كل خدمة ───

async def _execute_story(session, params, is_first):
    from telethon.tl.functions.stories import IncrementStoryViewsRequest, SendReactionRequest
    from telethon.tl.types import ReactionEmoji
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
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
            # نجاح المشاهدة لا ينبغي أن يتحول إلى فشل كامل إذا كانت
            # التفاعلات معطلة على الستوري أو رفضها Telegram لهذا الحساب.
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
            return False, "الجلسة غير مصرح بها."
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
    from telethon.tl.functions.contacts import ResolveUsernameRequest
    from telethon.tl.functions.messages import StartBotRequest
    try:
        from referrals import solve_captcha_with_ai
    except ImportError:
        return False, "لا يمكن استيراد solve_captcha_with_ai"
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return False, "الجلسة غير مصرح بها."
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        bot_username, start_param = _parse_bot_link(params["link"])
        if not bot_username:
            return False, "رابط البوت غير صحيح."
        clean_username = bot_username.lstrip("@").strip()
        resolved = await client(ResolveUsernameRequest(clean_username))
        bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]
        await client(StartBotRequest(bot=bot_entity, peer=bot_entity, start_param=start_param or ""))
        await asyncio.sleep(5)
        msgs = await client.get_messages(bot_entity, limit=15)
        solved, detail = await solve_captcha_with_ai(client, bot_entity, msgs, session["phone_number"], max_attempts=3)
        if not solved:
            return False, f"فشل التحقق: {detail}"
        return True, f"✅ تمت الإحالة مع التحقق من {session['phone_number']}"
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_comment(session, params, is_first):
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return False, "الجلسة غير مصرح بها."
        comment_text = (params.get("comment_text") or "").strip()
        if not comment_text:
            return False, "نص التعليق فارغ."
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
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
            return False, "الجلسة غير مصرح بها."
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        entity_ref, msg_id = _parse_post_link(params["link"])
        if not entity_ref or not msg_id:
            return False, "رابط الاستفتاء غير صحيح."
        entity = await client.get_entity(entity_ref)
        messages = await client.get_messages(entity, ids=msg_id)
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
            return False, "الجلسة غير مصرح بها."
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        post_ref, post_id = _parse_post_link(params["link"])
        if not post_ref or not post_id:
            return False, "رابط المنشور غير صحيح."
        post_entity = await client.get_entity(post_ref)
        messages = await client.get_messages(post_entity, ids=post_id)
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
    try:
        from referrals import solve_captcha_with_ai
    except ImportError:
        return False, "لا يمكن استيراد solve_captcha_with_ai"
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return False, "الجلسة غير مصرح بها."
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        post_ref, post_id = _parse_post_link(params["link"])
        if not post_ref or not post_id:
            return False, "رابط المنشور غير صحيح."
        post_entity = await client.get_entity(post_ref)
        messages = await client.get_messages(post_entity, ids=post_id)
        if not messages:
            return False, "المنشور غير موجود."
        solved, detail = await solve_captcha_with_ai(client, post_entity, messages, session["phone_number"], max_attempts=3)
        if not solved:
            return False, f"فشل التحقق: {detail}"
        messages = await client.get_messages(post_entity, ids=post_id)
        if not messages:
            return False, "المنشور غير موجود بعد التحقق."
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
        return True, f"✅ تم التصويت مع التحقق{verification} من {session['phone_number']}"
    except Exception as e:
        return False, f"❌ فشل: {str(e)[:80]}"
    finally:
        await client.disconnect()

async def _execute_premium_reaction(session, params, is_first):
    client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return False, "الجلسة غير مصرح بها."
        if is_first and params.get("channel_ref"):
            await _join_channel_and_schedule_leave(client, params["channel_ref"])
        post_ref, post_id = _parse_post_link(params["link"])
        if not post_ref or not post_id:
            return False, "رابط المنشور غير صحيح."
        post_entity = await client.get_entity(post_ref)
        reaction = params.get("reaction")
        if not reaction or reaction == "random":
            reaction = random.choice(list(RAKSH_REACTIONS.values()))
        await client(functions.messages.SendReactionRequest(peer=post_entity, msg_id=post_id, reaction=[ReactionEmoji(emoticon=reaction)]))
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
    shuffled = sessions.copy()
    random.shuffle(shuffled)
    success_count = 0
    success_phones = []
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
        try:
            ok, msg = await executor(session=session, params=params, is_first=(i == 0))
        except Exception as e:
            ok = False
            msg = f"❌ خطأ: {str(e)[:80]}"
        if ok:
            success_count += 1
            success_phones.append(phone)
        else:
            failed_details.append(msg)
        if progress_callback:
            await progress_callback(i + 1, quantity, success_count, len(failed_details))
        if i < quantity - 1 and shuffled:
            delay = _get_delay_seconds(service_type)
            await asyncio.sleep(delay)
    return success_count, success_phones, failed_details

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
    # The application registers this function as a dedicated callback handler,
    # while the modular callback router may also delegate `raksh_menu` here.
    # Supporting both call shapes keeps the menu functional in either route.
    query = query or update.callback_query
    data = query.data if data is None else data
    user = user or query.from_user
    is_own = (user.id == OWNER_ID) if is_own is None else is_own
    
    await query.answer()

    # ─── إظهار/إخفاء خدمة من قائمة الأعضاء (للمالك فقط) ───
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
            "🔥 *إدارة خدمات الرشق*\n\n"
            "✅ مفعلة: تظهر للأعضاء\n"
            "🚫 مخفية: لا تظهر للأعضاء\n\n"
            f"📊 الحسابات المتاحة: *{get_available_sessions_count()}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_menu_kb(True),
        )
        return

    # ─── إعداد أسعار الرشق (للمالك فقط) ───
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
    
    # ─── إلغاء الطلب أو العودة إلى قائمة الرشق ───
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
            "🔥 *خدمات الرشق*\n\n"
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
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
        )
        return
    
    # ─── اختيار التفاعل ───
    if data.startswith("raksh:reaction:"):
        parts = data.split(":")
        service_type = parts[2]
        reaction = RAKSH_REACTIONS.get(parts[3], parts[3])
        context.user_data["raksh_reaction"] = reaction
        context.user_data["raksh_step"] = "quantity"
        await query.edit_message_text(
            f"✅ تم اختيار التفاعل: {reaction}\n\n"
            f"🔢 *أرسل عدد الوحدات المطلوبة:*\n"
            f"(الحد الأقصى: {_get_max_quantity(service_type)})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="raksh_menu")]])
        )
        return
    
    # ─── اختيار الدفع ───
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
    
    # ─── تأكيد الطلب ───
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
        # لا نثق بالسعر القادم من الزر؛ أعد حسابه من الإعداد الحالي حتى لا
        # يفشل الطلب بعد تغيير السعر أو يمكن التلاعب بالتكلفة.
        total_cost = get_raksh_total(service_type, quantity, payment_method)
        if button_total != total_cost:
            logger.info(
                "Raksh price refreshed before confirmation: service=%s quantity=%s",
                service_type,
                quantity,
            )
        
        if payment_method == "points":
            if not deduct_points(user.id, total_cost):
                await query.edit_message_text(
                    "❌ *نقاطك غير كافية!*",
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
        
        # بدء التنفيذ
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
    
    # بناء رسالة التقدم
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
    
    # جلب الجلسات
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
    
    # تجهيز المعاملات
    params = {
        "channel_ref": context.user_data.get("raksh_channels"),
        "reaction": context.user_data.get("raksh_reaction"),
        "link": context.user_data.get("raksh_link"),
        "comment_text": context.user_data.get("raksh_comment"),
        "poll_option": context.user_data.get("raksh_poll_option"),
    }
    
    # دالة تحديث التقدم
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
    
    # التنفيذ
    success_count, success_phones, failed_details = await execute_raksh_service(
        service_type=service_type,
        quantity=quantity,
        sessions=sessions,
        params=params,
        user_id=user.id,
        progress_callback=update_progress
    )
    
    # تعويض الفاشل
    failed_count = quantity - success_count
    refund = 0
    if failed_count > 0 and payment_method == "points":
        refund = max(
            0,
            total_cost - get_raksh_total(service_type, success_count, "points"),
        )
        add_points(user.id, refund)
    
    # بناء رسالة النتيجة
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

    # ─── تعديل أسعار الرشق للمالك ───
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
    
    # ─── خطوة القنوات ───
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

    # ─── اختيار الدفع كتابةً ───
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
    
    # ─── خطوة الرابط ───
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
        
        # إذا كانت الخدمة تحتاج تفاعل
        if svc.get("has_reaction"):
            context.user_data["raksh_step"] = "reaction"
            await update.message.reply_text(
                f"✅ تم حفظ الرابط.\n\n"
                f"😊 *اختر التفاعل المطلوب:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=raksh_reaction_kb(service_type)
            )
            return True
        
        # خدمات التعليق
        if service_type == "comment":
            context.user_data["raksh_step"] = "comment_text"
            await update.message.reply_text(
                f"✅ تم حفظ الرابط.\n\n"
                f"💬 *أرسل نص التعليق:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
            )
            return True
        
        # خدمات الاستفتاء
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
        
        # باقي الخدمات → انتقل مباشرة للعدد
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
    
    # ─── خطوة نص التعليق ───
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
    
    # ─── خطوة خيار الاستفتاء ───
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
    
    # ─── خطوة العدد ───
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

        # قد يكون مستخدم آخر قد استهلك الحصة بين الفاتورة والدفع؛
        # أعد النجوم تلقائياً ولا تبدأ التنفيذ خارج الحد.
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
        
        # حفظ البيانات
        context.user_data["raksh_service"] = service_type
        context.user_data["raksh_quantity"] = quantity
        context.user_data["raksh_payment_method"] = "stars"
        
        # بدء التنفيذ
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
    
    # التحقق من الحظر
    if not (user.id == OWNER_ID) and is_user_banned(user.id):
        await update.message.reply_text("🚫 تم حظرك من استخدام هذا البوت.")
        return

    # لا تجعل تعطل استعلام قاعدة البيانات يمنع البوت من الرد على الأمر.
    # عرض القائمة لا يعتمد على معرفة العدد، لذلك نستخدم قيمة توضيحية عند الفشل
    # مع تسجيل الخطأ لمراجعته من سجلات التشغيل.
    try:
        available_sessions = get_available_sessions_count()
    except Exception:
        logger.exception("فشل جلب عدد الحسابات عند تنفيذ /raksh")
        available_sessions = 0
    
    await update.message.reply_text(
        "🔥 *خدمات الرشق*\n\n"
        "اختر الخدمة المطلوبة:\n"
        f"📊 الحسابات المتاحة: *{available_sessions}*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=raksh_menu_kb(user.id == OWNER_ID)
    )
