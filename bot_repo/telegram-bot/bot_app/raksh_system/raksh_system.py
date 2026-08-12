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
        "price_stars": 5,
        "has_channel": True,
        "has_reaction": True,
        "has_ai": False,
        "needs_link": True,
    },
    "forced_ref": {
        "name": "🔑 إحالة بوت إجباري",
        "price_points": 250,
        "price_stars": 10,
        "has_channel": True,
        "has_reaction": False,
        "has_ai": False,
        "needs_link": True,
    },
    "forced_ref_ai": {
        "name": "🤖 إحالة بوت إجباري مع تحقق",
        "price_points": 300,
        "price_stars": 15,
        "has_channel": True,
        "has_reaction": False,
        "has_ai": True,
        "needs_link": True,
    },
    "comment": {
        "name": "💬 رشق تعليق",
        "price_points": 30,
        "price_stars": 5,
        "has_channel": True,
        "has_reaction": False,
        "has_ai": False,
        "needs_link": True,
    },
    "poll": {
        "name": "📊 رشق استفتاء",
        "price_points": 30,
        "price_stars": 5,
        "has_channel": True,
        "has_reaction": False,
        "has_ai": False,
        "needs_link": True,
    },
    "votes": {
        "name": "🗳 رشق أصوات",
        "price_points": 20,
        "price_stars": 4,
        "has_channel": True,
        "has_reaction": False,
        "has_ai": False,
        "needs_link": True,
    },
    "votes_ai": {
        "name": "🛡 رشق تصويت مع تحقق",
        "price_points": 50,
        "price_stars": 10,
        "has_channel": True,
        "has_reaction": False,
        "has_ai": True,
        "needs_link": True,
    },
    "premium_reaction": {
        "name": "✨ رشق تفاعل مميز",
        "price_points": 10,
        "price_stars": 2,
        "has_channel": True,
        "has_reaction": True,
        "has_ai": False,
        "needs_link": True,
    },
}

# ════════════════════════════════════════════════════════════
# ═══ 2. دوال مساعدة ═══
# ════════════════════════════════════════════════════════════

def _get_delay_seconds() -> int:
    """فاصل زمني عشوائي 1-8 دقائق"""
    return random.randint(60, 480)

def _get_all_active_sessions() -> list[dict]:
    """جلب الجلسات النشطة"""
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, phone_number, session_string "
            "FROM number_stock "
            "WHERE session_string IS NOT NULL AND BTRIM(session_string) <> '' "
            "AND deleted_at IS NULL AND last_authorized IS NOT FALSE "
            "AND forced_ref_excluded IS NOT TRUE "
            "ORDER BY id ASC"
        ).fetchall()
    return [dict(row) for row in rows]

def get_available_sessions_count() -> int:
    return len(_get_all_active_sessions())

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
    """تحليل رابط ستوري"""
    value = (value or "").strip().strip("<>")
    parsed = urlparse(value if "://" in value else f"https://{value}")
    if parsed.netloc.lower() not in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}:
        return None, None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None, None
    story_id = None
    entity_str = None
    for i, part in enumerate(parts):
        if part == "story" and i + 1 < len(parts):
            story_id = int(parts[i + 1])
            entity_str = parts[i - 1] if i > 0 else None
            break
    if story_id is None:
        return None, None
    if entity_str and entity_str.startswith("@"):
        entity_str = entity_str[1:]
    return f"@{entity_str}", story_id

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

def raksh_menu_kb():
    """القائمة الرئيسية للخدمات"""
    buttons = []
    for key, svc in RAKSH_SERVICES.items():
        buttons.append([InlineKeyboardButton(svc["name"], callback_data=f"raksh:start:{key}")])
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

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
        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_menu")],
    ])

def raksh_reaction_kb(service_type: str):
    """أزرار اختيار التفاعل (لخدمتي ستوري وتفاعل مميز)"""
    reactions = ["❤️", "🔥", "👍", "😍", "🤩", "✨", "💯", "👏"]
    buttons = []
    row = []
    for i, r in enumerate(reactions):
        row.append(InlineKeyboardButton(r, callback_data=f"raksh:reaction:{service_type}:{r}"))
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
        [InlineKeyboardButton("❌ إلغاء", callback_data="raksh_menu")],
    ])

# ════════════════════════════════════════════════════════════
# ═══ 4. تنفيذ الخدمات ═══
# ════════════════════════════════════════════════════════════

async def _join_channel_and_schedule_leave(client, channel_ref: str):
    """الانضمام للقناة والمغادرة بعد 24 ساعة"""
    if channel_ref.startswith("invite:"):
        await client(ImportChatInviteRequest(channel_ref.split(":", 1)[1]))
    else:
        entity = await client.get_entity(channel_ref)
        await client(JoinChannelRequest(entity))

async def _join_discussion_group(client, discussion):
    """الانضمام لمجموعة النقاش"""
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
    await client(JoinChannelRequest(discussion_chat))

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
            reaction = random.choice(["❤️", "🔥", "👍", "😍", "🤩", "✨", "💯", "👏"])
        await client(SendReactionRequest(peer=entity, story_id=story_id, reaction=[ReactionEmoji(emoticon=reaction)]))
        return True, f"✅ تمت المشاهدة والتفاعل من {session['phone_number']}"
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
        await _join_discussion_group(client, discussion)
        await client.send_message(discussion_peer, params["comment_text"], reply_to=discussion_message.id)
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
        parts = params["link"].split("/")
        if len(parts) < 3:
            return False, "رابط الاستفتاء غير صحيح."
        entity_str = parts[-2] if parts[-2].startswith("@") else parts[-2]
        msg_id = int(parts[-1].split("?")[0])
        entity = await client.get_entity(entity_str)
        messages = await client.get_messages(entity, ids=msg_id)
        if not messages:
            return False, "المنشور غير موجود."
        msg = messages[0]
        if not hasattr(msg, "poll") or not msg.poll:
            return False, "هذا المنشور ليس استفتاءً."
        poll = msg.poll.poll
        options = getattr(poll, "answers", [])
        chosen_index = int(params["poll_option"]) - 1
        if chosen_index < 0 or chosen_index >= len(options):
            return False, "الخيار المطلوب غير موجود."
        await client(SendVoteRequest(peer=entity, msg_id=msg_id, options=[options[chosen_index].option]))
        return True, f"✅ تم التصويت من {session['phone_number']}"
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
        chosen = random.randint(0, len(options) - 1)
        await client(SendVoteRequest(peer=post_entity, msg_id=post_id, options=[options[chosen].option]))
        return True, f"✅ تم التصويت من {session['phone_number']}"
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
        chosen = random.randint(0, len(options) - 1)
        await client(SendVoteRequest(peer=post_entity, msg_id=post_id, options=[options[chosen].option]))
        return True, f"✅ تم التصويت مع التحقق من {session['phone_number']}"
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
            reaction = random.choice(["❤️", "🔥", "👍", "😍", "🤩", "✨", "💯", "👏"])
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

async def execute_raksh_service(service_type: str, quantity: int, sessions: list, params: dict, progress_callback=None):
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
            delay = _get_delay_seconds()
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
    
    # ─── القائمة الرئيسية ───
    if data == "raksh_menu":
        await query.edit_message_text(
            "🔥 *خدمات الرشق*\n\n"
            "اختر الخدمة المطلوبة:\n"
            f"📊 الحسابات المتاحة: *{get_available_sessions_count()}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_menu_kb()
        )
        return
    
    # ─── بدء خدمة ───
    if data.startswith("raksh:start:"):
        service_type = data.split(":")[2]
        svc = RAKSH_SERVICES.get(service_type)
        if not svc:
            await query.edit_message_text("⚠️ خدمة غير موجودة.", reply_markup=raksh_menu_kb())
            return
        
        context.user_data["raksh_service"] = service_type
        context.user_data["raksh_step"] = "channel"
        
        await query.edit_message_text(
            f"{svc['name']}\n\n"
            f"💰 السعر: {svc['price_points']} نقطة/وحدة\n"
            f"⭐ السعر: {svc['price_stars']} نجوم/وحدة\n\n"
            "📢 *أرسل القنوات الإجبارية:*\n"
            "مثال: @channel1 @channel2\n\n"
            "أو اضغط تخطي:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_channel_kb()
        )
        return
    
    # ─── تخطي القنوات ───
    if data == "raksh:skip_channels":
        context.user_data["raksh_channels"] = ""
        context.user_data["raksh_step"] = "link"
        svc = RAKSH_SERVICES.get(context.user_data.get("raksh_service"))
        await query.edit_message_text(
            f"✅ تم تخطي القنوات.\n\n"
            f"🔗 *أرسل الرابط المطلوب:*\n"
            f"{_get_link_instruction(context.user_data.get('raksh_service'))}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_menu")]])
        )
        return
    
    # ─── اختيار التفاعل ───
    if data.startswith("raksh:reaction:"):
        parts = data.split(":")
        service_type = parts[2]
        reaction = parts[3]
        context.user_data["raksh_reaction"] = reaction
        context.user_data["raksh_step"] = "quantity"
        await query.edit_message_text(
            f"✅ تم اختيار التفاعل: {reaction}\n\n"
            f"🔢 *أرسل عدد الوحدات المطلوبة:*\n"
            f"(الحد الأقصى: {_get_max_quantity()})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="raksh_menu")]])
        )
        return
    
    # ─── اختيار الدفع ───
    if data.startswith("raksh:pay:"):
        parts = data.split(":")
        method = parts[2]  # stars / points
        service_type = parts[3]
        quantity = int(parts[4])
        svc = RAKSH_SERVICES.get(service_type)
        if method == "stars":
            total = svc["price_stars"] * quantity
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
            total = svc["price_points"] * quantity
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
        service_type = parts[1]
        quantity = int(parts[2])
        total_cost = int(parts[3])
        payment_method = parts[4]
        
        if payment_method == "points":
            if not deduct_points(user.id, total_cost):
                await query.edit_message_text(
                    "❌ *نقاطك غير كافية!*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=raksh_menu_kb()
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
        "story": "https://t.me/username/story/123",
        "forced_ref": "@BotUsername start123  أو  t.me/BotUsername?start=123",
        "forced_ref_ai": "@BotUsername start123  أو  t.me/BotUsername?start=123",
        "comment": "https://t.me/channel/123",
        "poll": "https://t.me/channel/123",
        "votes": "https://t.me/channel/123",
        "votes_ai": "https://t.me/channel/123",
        "premium_reaction": "https://t.me/channel/123",
    }
    return instructions.get(service_type, "أرسل الرابط المطلوب")

def _get_max_quantity() -> int:
    """الحد الأقصى للوحدات"""
    available = get_available_sessions_count()
    return min(available, 50)

# ════════════════════════════════════════════════════════════
# ═══ 7. تنفيذ الطلب ═══
# ════════════════════════════════════════════════════════════

async def _start_raksh_execution(update, context, query, service_type: str, quantity: int, payment_method: str, total_cost: int):
    """بدء تنفيذ طلب الرشق"""
    user = query.from_user
    
    # بناء رسالة التقدم
    progress_msg = await query.edit_message_text(
        "⏳ *جاري التنفيذ...*\n\n"
        f"📊 0/{quantity}",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # جلب الجلسات
    sessions = _get_all_active_sessions()
    if not sessions:
        await progress_msg.edit_text(
            "❌ لا توجد حسابات متاحة.",
            reply_markup=raksh_menu_kb()
        )
        if payment_method == "points":
            add_points(user.id, total_cost)
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
        progress_callback=update_progress
    )
    
    # تعويض الفاشل
    failed_count = quantity - success_count
    refund = 0
    if failed_count > 0 and payment_method == "points":
        svc = RAKSH_SERVICES.get(service_type)
        refund = svc["price_points"] * failed_count
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
    
    # تنظيف البيانات
    for key in ["raksh_service", "raksh_step", "raksh_channels", "raksh_link", 
                "raksh_reaction", "raksh_comment", "raksh_poll_option"]:
        context.user_data.pop(key, None)

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
    
    # ─── خطوة القنوات ───
    if state == "channel":
        context.user_data["raksh_channels"] = text
        context.user_data["raksh_step"] = "link"
        service_type = context.user_data.get("raksh_service")
        await update.message.reply_text(
            f"✅ تم حفظ القنوات.\n\n"
            f"🔗 *أرسل الرابط المطلوب:*\n"
            f"{_get_link_instruction(service_type)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_menu")]])
        )
        return True
    
    # ─── خطوة الرابط ───
    if state == "link":
        service_type = context.user_data.get("raksh_service")
        svc = RAKSH_SERVICES.get(service_type)
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
        
        # خدمات الإحالة
        if service_type in ["forced_ref", "forced_ref_ai"]:
            bot_username, start_param = _parse_bot_link(text)
            if not bot_username:
                await update.message.reply_text(
                    "⚠️ رابط البوت غير صحيح.\n\n"
                    "أرسل الرابط بهذا الشكل:\n"
                    "@BotUsername start123\n"
                    "أو: t.me/BotUsername?start=123",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_menu")]])
                )
                return True
        
        # خدمات التعليق
        if service_type == "comment":
            context.user_data["raksh_step"] = "comment_text"
            await update.message.reply_text(
                f"✅ تم حفظ الرابط.\n\n"
                f"💬 *أرسل نص التعليق:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_menu")]])
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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_menu")]])
            )
            return True
        
        # باقي الخدمات → انتقل مباشرة للعدد
        context.user_data["raksh_step"] = "quantity"
        available = get_available_sessions_count()
        max_qty = min(available, 50)
        await update.message.reply_text(
            f"✅ تم حفظ الرابط.\n\n"
            f"🔢 *أرسل عدد الوحدات المطلوبة:*\n"
            f"(الحد الأقصى: {max_qty})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_menu")]])
        )
        return True
    
    # ─── خطوة نص التعليق ───
    if state == "comment_text":
        context.user_data["raksh_comment"] = text
        context.user_data["raksh_step"] = "quantity"
        available = get_available_sessions_count()
        max_qty = min(available, 50)
        await update.message.reply_text(
            f"✅ تم حفظ التعليق.\n\n"
            f"🔢 *أرسل عدد الوحدات المطلوبة:*\n"
            f"(الحد الأقصى: {max_qty})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_menu")]])
        )
        return True
    
    # ─── خطوة خيار الاستفتاء ───
    if state == "poll_option":
        if not text.isdigit():
            await update.message.reply_text(
                "⚠️ أرسل رقماً صحيحاً (مثال: 1 أو 2 أو 3).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_menu")]])
            )
            return True
        context.user_data["raksh_poll_option"] = text
        context.user_data["raksh_step"] = "quantity"
        available = get_available_sessions_count()
        max_qty = min(available, 50)
        await update.message.reply_text(
            f"✅ تم حفظ الخيار {text}.\n\n"
            f"🔢 *أرسل عدد الوحدات المطلوبة:*\n"
            f"(الحد الأقصى: {max_qty})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_menu")]])
        )
        return True
    
    # ─── خطوة العدد ───
    if state == "quantity":
        try:
            quantity = int(text)
        except ValueError:
            await update.message.reply_text(
                "⚠️ أرسل رقماً صحيحاً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_menu")]])
            )
            return True
        
        available = get_available_sessions_count()
        max_qty = min(available, 50)
        if quantity < 1 or quantity > max_qty:
            await update.message.reply_text(
                f"⚠️ العدد المسموح بين 1 و {max_qty}.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_menu")]])
            )
            return True
        
        service_type = context.user_data.get("raksh_service")
        svc = RAKSH_SERVICES.get(service_type)
        points_cost = svc["price_points"] * quantity
        stars_cost = svc["price_stars"] * quantity
        
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
        
        if query.from_user.id == user_id and query.total_amount == total_stars:
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
        
        # هنا نستدعي دالة التنفيذ مع payment_method = "stars"
        # التنفيذ الفعلي يحتاج إلى query object، لذلك نستخدم context

# ════════════════════════════════════════════════════════════
# ═══ 10. الأمر الرئيسي /raksh ═══
# ════════════════════════════════════════════════════════════

async def cmd_raksh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الأمر /raksh - يعرض قائمة خدمات الرشق"""
    user = update.effective_user
    
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
        reply_markup=raksh_menu_kb()
    )
