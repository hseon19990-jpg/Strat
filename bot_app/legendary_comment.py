"""Legendary Services - Complete module for all legendary services.

Services included:
1. Comment - Multi-comment with channel option
2. Poll - Vote on polls
3. Story Views + Reactions - View stories and react with emojis
4. Votes - Regular voting
5. Votes with AI - Voting with captcha solving
6. Premium Reaction - Special reactions on posts

All services support:
- Payment by points or stars
- Channel join (optional, with skip)
- Random delay between accounts (1-8 min default, owner can customize)
- No duplicate accounts
"""

from . import shared as _shared

globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

from urllib.parse import urlparse
import asyncio
import time
import random
import re
import json


# ==================== PRICES (Points) ====================
PRICES = {
    "comment": {"per_unit": 30, "channel": 30},
    "poll": {"per_unit": 30, "channel": 30},
    "story": {"per_unit": 30, "channel": 30},
    "votes": {"per_unit": 20, "channel": 25},
    "votes_ai": {"per_unit": 50, "channel": 25},
    "premium_reaction": {"per_unit": 10, "channel": 0},
}

# ==================== PRICES (Stars) ====================
STARS_PRICES = {
    "comment": {"per_units": 5, "stars": 1},
    "poll": {"per_units": 5, "stars": 1},
    "story": {"per_units": 10, "stars": 1},
    "votes": {"per_units": 10, "stars": 1},
    "votes_ai": {"per_units": 4, "stars": 1},
    "premium_reaction": {"per_units": 25, "stars": 1},
}

# ==================== CONSTANTS ====================
LEGENDARY_STAY_HOURS = 24
MIN_DELAY_MINUTES = 1
MAX_DELAY_MINUTES = 8

# ==================== LEGENDARY SERVICES MESSAGE ====================
LEGENDARY_SERVICES_MESSAGE = (
    "👑 *أهلاً بك في أفضل قسم للرشق!*\n\n"
    "يمكنك الحصول على رشق بحسابات حقيقية\n"
    "تحتوي أسماء عربية، بايو، ستوري، وأفتار نشطة.\n"
    "اختر الخدمة المناسبة لك:\n\n"
    "💰 *أسعار الخدمات:*\n"
    "• 💬 تعليق: 30 نقطة/وحدة + 30 قناة | ⭐ 1 نجمة لكل 5\n"
    "• 📊 استفتاء: 30 نقطة/وحدة + 30 قناة | ⭐ 1 نجمة لكل 5\n"
    "• 👁 ستوري: 30 نقطة/وحدة + 30 قناة | ⭐ 1 نجمة لكل 10\n"
    "• 🗳 أصوات: 20 نقطة/وحدة + 25 قناة | ⭐ 1 نجمة لكل 10\n"
    "• 🤖 تصويت بتحقق: 50 نقطة/وحدة + 25 قناة | ⭐ 1 نجمة لكل 4\n"
    "• ✨ تفاعل مميز: 10 نقاط/وحدة + 0 قناة | ⭐ 1 نجمة لكل 25\n\n"
    "اختر الخدمة: 👇"
)

# ==================== SETTINGS KEYS ====================
PRICE_SETTINGS_KEYS = {
    "comment": "legendary_price_comment",
    "poll": "legendary_price_poll",
    "story": "legendary_price_story",
    "votes": "legendary_price_votes",
    "votes_ai": "legendary_price_votes_ai",
    "premium_reaction": "legendary_price_premium_reaction",
}

# ==================== VISIBILITY SETTINGS ====================
LEGENDARY_VISIBILITY_KEYS = {
    "comment": "legendary_visible_comment",
    "poll": "legendary_visible_poll",
    "story": "legendary_visible_story",
    "votes": "legendary_visible_votes",
    "votes_ai": "legendary_visible_votes_ai",
    "premium_reaction": "legendary_visible_premium_reaction",
}


def get_service_price(service_type: str, include_channel: bool = True) -> int:
    """Get current price for a service (points)."""
    key = PRICE_SETTINGS_KEYS.get(service_type)
    if key:
        saved = get_setting(key)
        if saved:
            try:
                return int(saved)
            except ValueError:
                pass
    base = PRICES.get(service_type, {}).get("per_unit", 30)
    channel = PRICES.get(service_type, {}).get("channel", 0)
    return base + (channel if include_channel else 0)


def get_service_channel_price(service_type: str) -> int:
    """Get channel price for a service (points)."""
    return PRICES.get(service_type, {}).get("channel", 0)


def get_stars_price(service_type: str, quantity: int) -> int:
    """Calculate stars needed for a given quantity."""
    stars_info = STARS_PRICES.get(service_type, {"per_units": 5, "stars": 1})
    per_units = stars_info["per_units"]
    stars_per = stars_info["stars"]
    return ((quantity + per_units - 1) // per_units) * stars_per


async def legendary_payment_choice(update, context, q, is_own: bool, service_type: str, payment_method: str):
    """Handle legacy payment callback data emitted by older keyboards."""
    context.user_data["legendary_service_type"] = service_type
    await legendary_payment_callback(update, context, q, is_own, payment_method)


def is_legendary_service_visible(service_type: str) -> bool:
    """Check if a specific legendary service is visible to non-owners."""
    key = LEGENDARY_VISIBILITY_KEYS.get(service_type)
    if key:
        return get_setting(key) != "0"
    return True  # Default: visible


def toggle_legendary_service_visibility(service_type: str) -> bool:
    """Toggle visibility of a legendary service. Returns new state (True=visible)."""
    key = LEGENDARY_VISIBILITY_KEYS.get(service_type)
    if not key:
        return True
    current = get_setting(key)
    new_val = "0" if current == "1" else "1"
    set_setting(key, new_val)
    return new_val == "1"


# ==================== HELPERS ====================
def _clean_link(value: str) -> str:
    return (value or "").strip().strip("<>")


def _parse_channel_reference(value: str) -> tuple[str | None, str | None]:
    """Return a Telethon entity reference and a display value for a channel link."""
    value = _clean_link(value)
    if not value:
        return None, None
    if value.startswith("@"):
        return value, value

    parsed = urlparse(value if "://" in value else f"https://{value}")
    if parsed.netloc.lower() not in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}:
        if value.startswith("@"):
            return value, value
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


def _parse_post_link_parts(value: str) -> tuple[str | int | None, int | None]:
    value = _clean_link(value)
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


def _get_all_active_sessions() -> list[dict]:
    """Load all owner-provided sessions eligible for operations.

    The operation pool is intentionally sourced only from number_stock and
    excludes deleted, unauthorized, sold, or buyer-assigned accounts. The
    number of eligible rows is the natural request limit.
    """
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, phone_number, session_string "
            "FROM number_stock "
            "WHERE session_string IS NOT NULL AND BTRIM(session_string) <> '' "
            "AND deleted_at IS NULL AND last_authorized IS NOT FALSE "
            "AND forced_ref_excluded IS NOT TRUE "
            "AND ever_sold IS NOT TRUE AND assigned_to IS NULL "
            "ORDER BY id ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_available_sessions_count() -> int:
    """Return the number of available sessions."""
    return len(_get_all_active_sessions())


def get_delay_seconds(is_owner: bool, custom_delay: str = None) -> int:
    """
    Get delay between accounts.
    - Owner: can set custom delay (e.g., "5", "30-60")
    - Non-owner: 1-8 minutes random
    """
    if is_owner and custom_delay:
        try:
            if "-" in custom_delay:
                parts = custom_delay.split("-")
                min_d = int(parts[0].strip())
                max_d = int(parts[1].strip())
                return random.randint(min_d, max_d)
            else:
                return int(custom_delay.strip())
        except (ValueError, TypeError):
            pass
    
    # Default: 1-8 minutes
    return random.randint(MIN_DELAY_MINUTES * 60, MAX_DELAY_MINUTES * 60)


# ==================== CHANNEL & DISCUSSION HELPERS ====================

async def _join_channel_and_schedule_leave(client, channel_ref: str, delay_hours: int = LEGENDARY_STAY_HOURS):
    """Join channel and schedule leaving after specified hours."""
    if channel_ref.startswith("invite:"):
        await client(functions.messages.ImportChatInviteRequest(channel_ref.split(":", 1)[1]))
    else:
        entity = await client.get_entity(channel_ref)
        try:
            await client(functions.channels.JoinChannelRequest(entity))
        except Exception as exc:
            if "USER_ALREADY_PARTICIPANT" not in str(exc).upper():
                raise
    
    # Schedule leave
    async def _leave():
        await asyncio.sleep(delay_hours * 3600)
        try:
            entity = await client.get_entity(channel_ref)
            await client(functions.channels.LeaveChannelRequest(entity))
            logger.info(f"✅ Left channel {channel_ref} after {delay_hours} hours.")
        except Exception as exc:
            logger.warning(f"⚠️ Failed to leave channel {channel_ref}: {exc}")
    
    asyncio.create_task(_leave())


async def _join_discussion_group(client, discussion) -> None:
    """Join the linked discussion group before replying to a channel post."""
    messages = getattr(discussion, "messages", None) or []
    if not messages:
        raise RuntimeError("المنشور لا يملك نقاشاً متاحاً للتعليق.")

    discussion_message = messages[0]
    peer = getattr(discussion_message, "peer_id", None)
    channel_id = getattr(peer, "channel_id", None)
    chats = getattr(discussion, "chats", None) or []

    discussion_chat = next(
        (chat for chat in chats if getattr(chat, "id", None) == channel_id),
        None,
    )
    if discussion_chat is None:
        raise RuntimeError("تعذر تحديد مجموعة النقاش المرتبطة بالمنشور.")

    try:
        await client(functions.channels.JoinChannelRequest(discussion_chat))
    except Exception as exc:
        if "USER_ALREADY_PARTICIPANT" not in str(exc).upper():
            raise


# ==================== FETCH PREMIUM REACTIONS ====================

async def _fetch_premium_reactions(client, post_ref: str, post_id: int) -> list[str]:
    """
    Fetch available premium reactions from a post.
    Returns a list of emoji strings.
    """
    try:
        post_entity = await client.get_entity(post_ref)
        messages = await client.get_messages(post_entity, ids=post_id)
        if not messages:
            return []
        
        msg = messages[0]
        # Get available reactions from the message
        if hasattr(msg, "reactions") and msg.reactions:
            reactions = getattr(msg.reactions, "results", [])
            premium_emojis = []
            for r in reactions:
                if hasattr(r, "reaction") and hasattr(r.reaction, "emoticon"):
                    premium_emojis.append(r.reaction.emoticon)
            return premium_emojis
        
        # Fallback: common premium reactions
        return ["❤️", "🔥", "👍", "😍", "🤩", "✨", "💯", "👏"]
    except Exception as e:
        logger.warning(f"⚠️ Failed to fetch premium reactions: {e}")
        return ["❤️", "🔥", "👍", "😍", "🤩", "✨", "💯", "👏"]


# ==================== SERVICE EXECUTORS ====================

async def _execute_comment(
    session: dict,
    post_ref: str,
    post_id: int,
    comment_text: str,
    channel_ref: str = None,
    is_first: bool = False,
) -> tuple[bool, str]:
    """Execute a single comment."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return False, "بيانات Telegram API غير مهيأة."

    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return False, "الجلسة غير مصرح بها."

        if is_first and channel_ref:
            await _join_channel_and_schedule_leave(client, channel_ref)

        post_entity = await client.get_entity(post_ref)
        discussion = await client(
            functions.messages.GetDiscussionMessageRequest(
                peer=post_entity,
                msg_id=post_id,
            )
        )
        if not getattr(discussion, "messages", None):
            return False, "المنشور لا يملك نقاشاً."
        
        discussion_message = discussion.messages[0]
        discussion_peer = getattr(discussion_message, "peer_id", None)
        if discussion_peer is None:
            return False, "تعذر تحديد مساحة التعليقات."
        
        await _join_discussion_group(client, discussion)
        await client.send_message(
            discussion_peer,
            comment_text,
            reply_to=discussion_message.id,
        )
        return True, f"✅ تم التعليق من {session['phone_number']}"
    except Exception as exc:
        return False, f"❌ فشل من {session['phone_number']}: {str(exc)[:80]}"
    finally:
        await client.disconnect()


async def _execute_poll_vote(
    session: dict,
    poll_link: str,
    poll_option: str,
    channel_ref: str = None,
    is_first: bool = False,
) -> tuple[bool, str]:
    """Execute a single poll vote."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return False, "بيانات Telegram API غير مهيأة."

    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return False, "الجلسة غير مصرح بها."

        if is_first and channel_ref:
            await _join_channel_and_schedule_leave(client, channel_ref)

        parts = poll_link.split("/")
        if len(parts) < 3:
            return False, "رابط الاستفتاء غير صحيح."
        
        entity_str = parts[-2] if parts[-2].startswith("@") else parts[-2]
        msg_id = int(parts[-1].split("?")[0])
        
        try:
            entity = await client.get_entity(entity_str)
        except Exception:
            return False, f"تعذر العثور على {entity_str}"
        
        messages = await client.get_messages(entity, ids=msg_id)
        if not messages:
            return False, "المنشور غير موجود."
        msg = messages[0]
        
        if not hasattr(msg, "poll") or not msg.poll:
            return False, "هذا المنشور ليس استفتاءً."
        
        poll = msg.poll.poll
        options = getattr(poll, "answers", [])
        chosen_index = -1
        
        try:
            chosen_index = int(poll_option) - 1
        except ValueError:
            for i, opt in enumerate(options):
                if opt.text.lower() == poll_option.lower():
                    chosen_index = i
                    break
        
        if chosen_index < 0 or chosen_index >= len(options):
            return False, "الخيار المطلوب غير موجود."
        
        await client(functions.messages.SendVoteRequest(
            peer=entity,
            msg_id=msg_id,
            options=[options[chosen_index].option]
        ))
        
        return True, f"✅ تم التصويت من {session['phone_number']}"
    except Exception as exc:
        return False, f"❌ فشل من {session['phone_number']}: {str(exc)[:80]}"
    finally:
        await client.disconnect()


async def _execute_story_reaction(
    session: dict,
    story_link: str,
    emojis: list[str],
    channel_ref: str = None,
    is_first: bool = False,
) -> tuple[bool, str]:
    """Execute a single story view + reaction."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return False, "بيانات Telegram API غير مهيأة."

    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return False, "الجلسة غير مصرح بها."

        if is_first and channel_ref:
            await _join_channel_and_schedule_leave(client, channel_ref)

        parts = story_link.split("/")
        if len(parts) < 3:
            return False, "رابط الستوري غير صحيح."
        
        story_id = None
        for i, part in enumerate(parts):
            if part == "story" and i + 1 < len(parts):
                story_id = int(parts[i + 1])
                break
        
        if story_id is None:
            return False, "تعذر العثور على معرف الستوري."
        
        entity_str = parts[-3] if len(parts) >= 3 else parts[-2]
        if entity_str.startswith("@"):
            entity_str = entity_str[1:]
        if entity_str.isdigit():
            entity_str = int(entity_str)
        
        entity = await client.get_entity(entity_str)
        
        await client(functions.stories.IncrementStoryViewsRequest(
            peer=entity,
            id=story_id
        ))
        
        if emojis:
            from telethon.tl.types import ReactionEmoji
            reaction_emoji = random.choice(emojis)
            await client(functions.stories.SendReactionRequest(
                peer=entity,
                story_id=story_id,
                reaction=ReactionEmoji(emoticon=reaction_emoji)
            ))
        
        return True, f"✅ تمت مشاهدة وتفاعل الستوري من {session['phone_number']}"
    except Exception as exc:
        return False, f"❌ فشل من {session['phone_number']}: {str(exc)[:80]}"
    finally:
        await client.disconnect()


async def _execute_vote(
    session: dict,
    post_ref: str,
    post_id: int,
    channel_ref: str = None,
    is_first: bool = False,
    use_ai: bool = False,
) -> tuple[bool, str]:
    """Execute a single vote (with or without AI captcha)."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return False, "بيانات Telegram API غير مهيأة."

    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return False, "الجلسة غير مصرح بها."

        if is_first and channel_ref:
            await _join_channel_and_schedule_leave(client, channel_ref)

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
            return False, "لا توجد خيارات للتصويت."
        
        if use_ai:
            from .referrals import solve_captcha_with_ai
            solved, detail = await solve_captcha_with_ai(
                client,
                post_entity,
                [msg],
                session["phone_number"]
            )
            if not solved:
                return False, f"فشل حل التحقق: {detail}"
            messages = await client.get_messages(post_entity, ids=post_id)
            if not messages:
                return False, "المنشور غير موجود بعد التحقق."
            msg = messages[0]
            if not hasattr(msg, "poll") or not msg.poll:
                return False, "المنشور ليس استفتاءً بعد التحقق."
            poll = msg.poll.poll
            options = getattr(poll, "answers", [])
            if not options:
                return False, "لا توجد خيارات بعد التحقق."
        
        chosen = random.randint(0, len(options) - 1)
        await client(functions.messages.SendVoteRequest(
            peer=post_entity,
            msg_id=post_id,
            options=[options[chosen].option]
        ))
        
        return True, f"✅ تم التصويت من {session['phone_number']}"
    except Exception as exc:
        return False, f"❌ فشل من {session['phone_number']}: {str(exc)[:80]}"
    finally:
        await client.disconnect()


async def _execute_premium_reaction(
    session: dict,
    post_ref: str,
    post_id: int,
    reaction_text: str,
    channel_ref: str = None,
    is_first: bool = False,
) -> tuple[bool, str]:
    """Execute a single premium reaction."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return False, "بيانات Telegram API غير مهيأة."

    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return False, "الجلسة غير مصرح بها."

        if is_first and channel_ref:
            await _join_channel_and_schedule_leave(client, channel_ref)

        post_entity = await client.get_entity(post_ref)
        
        from telethon.tl.types import ReactionEmoji
        await client(functions.messages.SendReactionRequest(
            peer=post_entity,
            msg_id=post_id,
            reaction=[ReactionEmoji(emoticon=reaction_text)]
        ))
        
        return True, f"✅ تم التفاعل من {session['phone_number']}"
    except Exception as exc:
        return False, f"❌ فشل من {session['phone_number']}: {str(exc)[:80]}"
    finally:
        await client.disconnect()


# ==================== BATCH EXECUTOR ====================

async def execute_batch(
    service_type: str,
    quantity: int,
    sessions: list,
    params: dict,
    is_owner: bool = False,
    custom_delay: str = None,
    progress_callback=None,
) -> tuple[int, list[str], list[str]]:
    """
    Execute a batch of operations across sessions.
    
    service_type: 'comment', 'poll', 'story', 'votes', 'votes_ai', 'premium_reaction'
    params: dict with service-specific parameters
    Returns: (success_count, success_phones, failed_details)
    """
    if not sessions:
        raise RuntimeError("لا توجد جلسات نشطة متاحة.")
    
    shuffled = sessions.copy()
    random.shuffle(shuffled)
    
    success_count = 0
    success_phones = []
    failed_details = []
    used_phones = set()
    fallback_pool = shuffled.copy()
    
    executors = {
        "comment": _execute_comment,
        "poll": _execute_poll_vote,
        "story": _execute_story_reaction,
        "votes": _execute_vote,
        "votes_ai": _execute_vote,
        "premium_reaction": _execute_premium_reaction,
    }
    
    executor = executors.get(service_type)
    if not executor:
        raise RuntimeError(f"خدمة غير معروفة: {service_type}")
    
    for i in range(quantity):
        if not fallback_pool:
            break
        
        session = fallback_pool.pop(0)
        phone = session["phone_number"]
        
        if phone in used_phones:
            continue
        used_phones.add(phone)
        
        is_first = (i == 0)
        
        exec_params = {
            "session": session,
            "channel_ref": params.get("channel_ref"),
            "is_first": is_first,
        }
        
        if service_type == "comment":
            exec_params["post_ref"] = params["post_ref"]
            exec_params["post_id"] = params["post_id"]
            exec_params["comment_text"] = params["comment_text"]
        elif service_type == "poll":
            exec_params["poll_link"] = params["poll_link"]
            exec_params["poll_option"] = params["poll_option"]
        elif service_type == "story":
            exec_params["story_link"] = params["story_link"]
            exec_params["emojis"] = params["emojis"]
        elif service_type in ["votes", "votes_ai"]:
            exec_params["post_ref"] = params["post_ref"]
            exec_params["post_id"] = params["post_id"]
            exec_params["use_ai"] = (service_type == "votes_ai")
        elif service_type == "premium_reaction":
            exec_params["post_ref"] = params["post_ref"]
            exec_params["post_id"] = params["post_id"]
            exec_params["reaction_text"] = params["reaction_text"]
        
        try:
            ok, msg = await executor(**exec_params)
            if ok:
                success_count += 1
                success_phones.append(phone)
            else:
                failed_details.append(msg)
                if fallback_pool and i < quantity - 1:
                    fallback = fallback_pool.pop(0) if fallback_pool else None
                    if fallback and fallback["phone_number"] not in used_phones:
                        fallback_pool.append(session)
                        fallback_pool.append(fallback)
                        continue
        except Exception as exc:
            failed_details.append(f"❌ خطأ: {str(exc)[:80]}")
            continue
        
        if progress_callback:
            await progress_callback(i + 1, quantity, success_count, len(failed_details))
        
        if i < quantity - 1 and fallback_pool:
            delay = get_delay_seconds(is_owner, custom_delay)
            logger.info(f"⏳ انتظار {delay} ثانية قبل التالي...")
            await asyncio.sleep(delay)
    
    return success_count, success_phones, failed_details


# ==================== UI HELPERS ====================

def get_service_display_name(service_type: str) -> str:
    """Get display name for a service type."""
    names = {
        "comment": "رشق تعليق",
        "poll": "رشق استفتاء",
        "story": "رشق مشاهدات وتفاعل ستوري",
        "votes": "رشق أصوات",
        "votes_ai": "رشق تصويت بتحقق",
        "premium_reaction": "رشق تفاعل مميز",
    }
    return names.get(service_type, service_type)


def get_service_price_display(service_type: str) -> str:
    """Get price display for a service."""
    per_unit = get_service_price(service_type, include_channel=False)
    channel = get_service_channel_price(service_type)
    stars_info = STARS_PRICES.get(service_type, {"per_units": 5, "stars": 1})
    
    # Fix display text based on service type
    if service_type == "poll":
        unit_label = "استفتاء"
    elif service_type == "story":
        unit_label = "مشاهدة/تفاعل"
    elif service_type == "premium_reaction":
        unit_label = "وحدة"
    else:
        unit_label = "وحدة"
    
    if channel > 0:
        return f"{per_unit} نقطة/{unit_label} + {channel} نقطة قناة | ⭐ {stars_info['stars']} نجمة لكل {stars_info['per_units']} {unit_label}"
    else:
        return f"{per_unit} نقطة/{unit_label} | ⭐ {stars_info['stars']} نجمة لكل {stars_info['per_units']} {unit_label}"


def legendary_services_back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع للخدمات الأسطورية", callback_data="legendary_services")]
    ])


def get_legendary_visibility_kb() -> InlineKeyboardMarkup:
    """Generate keyboard for toggling legendary service visibility."""
    buttons = []
    for key, display in [
        ("comment", "💬 تعليق"),
        ("poll", "📊 استفتاء"),
        ("story", "👁 ستوري"),
        ("votes", "🗳 أصوات"),
        ("votes_ai", "🤖 تصويت بتحقق"),
        ("premium_reaction", "✨ تفاعل مميز"),
    ]:
        visible = is_legendary_service_visible(key)
        status = "✅ ظاهر" if visible else "🔒 مخفي"
        buttons.append([
            InlineKeyboardButton(
                f"{display}: {status}",
                callback_data=f"legendary:toggle_visibility:{key}"
            )
        ])
    
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
    return InlineKeyboardMarkup(buttons)


async def legendary_show_settings(update, context, q, is_own: bool):
    """Show the settings supported by the current legendary flow."""
    if not is_own:
        await q.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
        return

    await q.edit_message_text(
        "⚙️ *إعدادات الخدمات الأسطورية*\n\n"
        "اختر خدمة لتغيير ظهورها للأعضاء:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_legendary_visibility_kb(),
    )


# ==================== LEGENDARY SERVICES START ====================

async def legendary_service_start(update, context, q, is_own: bool, service_type: str):
    """Start the flow for any legendary service."""
    # Check visibility for non-owners
    if not is_own and not is_legendary_service_visible(service_type):
        await q.answer("⚠️ هذه الخدمة مخفية حالياً من قبل المالك.", show_alert=True)
        return
    
    try:
        available = get_available_sessions_count()
    except Exception:
        logger.exception("❌ تعذر فحص الحسابات المتاحة للخدمة الأسطورية: %s", service_type)
        await q.answer(
            "⚠️ تعذر التحقق من الحسابات المتاحة حالياً. حاول مرة أخرى بعد قليل.",
            show_alert=True,
        )
        return
    
    if available == 0:
        await q.edit_message_text(
            "❌ لا توجد حسابات متاحة. تأكد من وجود جلسات نشطة.",
            reply_markup=legendary_services_back_kb()
        )
        return
    
    context.user_data["legendary_service_type"] = service_type
    context.user_data["legendary_user_id"] = q.from_user.id
    context.user_data["legendary_step"] = "payment_selection"
    
    for key in (
        "legendary_channel_ref",
        "legendary_post_ref",
        "legendary_post_id",
        "legendary_comment_text",
        "legendary_quantity",
        "legendary_payment_method",
        "legendary_poll_link",
        "legendary_poll_option",
        "legendary_story_link",
        "legendary_emojis",
        "legendary_reaction_text",
        "legendary_custom_delay",
        "legendary_premium_reactions",
        "legendary_random_reaction",
    ):
        context.user_data.pop(key, None)
    
    service_name = get_service_display_name(service_type)
    points_cost = get_service_price(service_type, include_channel=False)
    channel_cost = get_service_channel_price(service_type)
    stars_info = STARS_PRICES.get(service_type, {"per_units": 5, "stars": 1})
    
    # Custom description for each service
    if service_type == "poll":
        description = "📝 *التصويت في استفتاءك*"
    elif service_type == "story":
        description = "👁 *مشاهدة وتفاعل ستوري*"
    elif service_type == "premium_reaction":
        description = "✨ *تفاعل مميز (مدفوع)*"
    else:
        description = ""
    
    message_text = (
        f"👑 *أهلاً بك في أفضل قسم للرشق!*\n\n"
        f"يمكنك الحصول على رشق بحسابات حقيقية\n"
        f"تحتوي أسماء عربية، بايو، ستوري، وأفتار نشطة.\n"
        f"اختر الخدمة المناسبة لك:\n\n"
        f"📌 *الخدمة:* {service_name}\n"
        f"{description}\n\n"
        f"💰 *السعر:*\n"
        f"• {points_cost} نقطة لكل {service_name.replace('رشق ', '')}\n"
        f"• {stars_info['stars']} نجمة لكل {stars_info['per_units']} {service_name.replace('رشق ', '')}\n"
        + (f"• القناة الإجبارية: +{channel_cost} نقطة (تُخصم مرة واحدة)\n" if channel_cost > 0 else "")
        + f"\nاختر طريقة الدفع:"
    )
    payment_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⭐ دفع بالنجوم", callback_data=f"legendary:pay:stars")],
        [InlineKeyboardButton(f"💰 دفع بالنقاط", callback_data=f"legendary:pay:points")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="legendary_services")],
    ])
    try:
        await q.edit_message_text(
            message_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=payment_markup,
        )
    except Exception:
        logger.warning("⚠️ تعذر عرض تنسيق Markdown لخدمة %s، سيتم العرض كنص عادي.", service_type)
        await q.edit_message_text(
            message_text.replace("*", ""),
            reply_markup=payment_markup,
        )
    context.user_data["state"] = "legendary_payment_selection"


async def legendary_skip_channel(update, context, q, is_own: bool):
    """Skip channel step."""
    context.user_data.pop("legendary_channel_ref", None)
    context.user_data["legendary_step"] = "main_input"
    
    service_type = context.user_data.get("legendary_service_type", "comment")
    service_name = get_service_display_name(service_type)
    
    prompts = {
        "comment": "📎 أرسل رابط المنشور المطلوب التعليق عليه:",
        "poll": "📎 أرسل رابط الاستفتاء المطلوب التصويت عليه:",
        "story": "📎 أرسل رابط الستوري المطلوب مشاهدته:",
        "votes": "📎 أرسل رابط الاستفتاء المطلوب التصويت عليه:",
        "votes_ai": "📎 أرسل رابط الاستفتاء المطلوب التصويت عليه (مع تحقق):",
        "premium_reaction": "📎 أرسل رابط المنشور المطلوب التفاعل عليه:",
    }
    
    await q.edit_message_text(
        f"⏭ تم تخطي القناة.\n\n{prompts.get(service_type, 'أرسل الرابط المطلوب:')}",
        reply_markup=legendary_services_back_kb()
    )
    context.user_data["state"] = "legendary_main_input"


# ==================== TEXT HANDLER ====================

async def legendary_handle_text(update, context, text: str) -> bool:
    """Handle text input for legendary services."""
    user = update.effective_user
    state = context.user_data.get("state", "")
    if not state:
        return False
    
    service_type = context.user_data.get("legendary_service_type", "comment")
    
    # --- Payment selection is now handled by callbacks ---
    
    # --- Channel input ---
    if state == "legendary_channel_input":
        # Try to parse the channel link
        ref, display = _parse_channel_reference(text)
        
        # If parsing fails, treat it as a skip or invalid
        if not ref:
            # Check if it's a valid Telegram channel format
            if text.startswith("@") or "t.me/" in text or "telegram.me/" in text:
                # It looks like a channel link but couldn't parse - try to extract username
                clean = text.strip()
                if clean.startswith("@"):
                    ref = clean
                    display = clean
                elif "t.me/" in clean:
                    parts = clean.split("/")
                    if len(parts) >= 3:
                        username = parts[-1].split("?")[0]
                        if username:
                            ref = f"@{username}"
                            display = f"@{username}"
                elif "telegram.me/" in clean:
                    parts = clean.split("/")
                    if len(parts) >= 3:
                        username = parts[-1].split("?")[0]
                        if username:
                            ref = f"@{username}"
                            display = f"@{username}"
        
        # Store or skip
        if ref:
            context.user_data["legendary_channel_ref"] = ref
            channel_status = "حفظ"
        else:
            context.user_data.pop("legendary_channel_ref", None)
            channel_status = "تخطي"
        
        context.user_data["legendary_step"] = "main_input"
        context.user_data["state"] = "legendary_main_input"
        
        prompts = {
            "comment": "💬 *أرسل رابط المنشور المطلوب التعليق عليه:*",
            "poll": "📊 *أرسل رابط الاستفتاء المطلوب التصويت عليه:*",
            "story": "👁 *أرسل رابط الستوري المطلوب مشاهدته:*",
            "votes": "🗳 *أرسل رابط الاستفتاء المطلوب التصويت عليه:*",
            "votes_ai": "🤖 *أرسل رابط الاستفتاء المطلوب التصويت عليه (مع تحقق):*",
            "premium_reaction": "✨ *أرسل رابط المنشور المطلوب التفاعل عليه:*",
        }
        
        await update.message.reply_text(
            f"✅ تم {channel_status} القناة.\n\n{prompts.get(service_type, 'أرسل الرابط المطلوب:')}",
            reply_markup=legendary_services_back_kb()
        )
        return True
    
    # --- Main input ---
    if state == "legendary_main_input":
        if service_type in ["comment", "votes", "votes_ai"]:
            post_ref, post_id = _parse_post_link_parts(text)
            if post_ref is None or post_id is None:
                await update.message.reply_text(
                    "⚠️ أرسل رابط منشور تيليجرام صحيحاً، مثال:\nhttps://t.me/channel/123"
                )
                return True
            context.user_data["legendary_post_ref"] = post_ref
            context.user_data["legendary_post_id"] = post_id
            context.user_data["legendary_step"] = "quantity"
            context.user_data["state"] = "legendary_quantity_input"
            
            available = get_available_sessions_count()
            await update.message.reply_text(
                f"✅ تم حفظ الرابط.\n\n🔢 أرسل عدد الوحدات المطلوبة (1-{available}):",
                parse_mode=ParseMode.MARKDOWN
            )
            return True
        
        elif service_type == "poll":
            context.user_data["legendary_poll_link"] = text
            context.user_data["legendary_step"] = "poll_option"
            context.user_data["state"] = "legendary_poll_option_input"
            
            await update.message.reply_text(
                "✅ تم حفظ رابط الاستفتاء.\n\n🔢 أرسل رقم الخيار المطلوب (مثال: 1 أو 2 أو 3):"
            )
            return True
        
        elif service_type == "story":
            context.user_data["legendary_story_link"] = text
            context.user_data["legendary_step"] = "story_emojis"
            context.user_data["state"] = "legendary_emojis_input"
            
            await update.message.reply_text(
                "✅ تم حفظ رابط الستوري.\n\n😊 أرسل الإيموجيات المطلوبة للتفاعل (كل إيموجي في سطر):\nمثال:\n😁\n😝\n😂"
            )
            return True
        
        elif service_type == "premium_reaction":
            # For premium reaction, we need to fetch available reactions first
            post_ref, post_id = _parse_post_link_parts(text)
            if post_ref is None or post_id is None:
                await update.message.reply_text(
                    "⚠️ أرسل رابط منشور تيليجرام صحيحاً، مثال:\nhttps://t.me/channel/123"
                )
                return True
            context.user_data["legendary_post_ref"] = post_ref
            context.user_data["legendary_post_id"] = post_id
            
            # Fetch premium reactions from the post
            if TELEGRAM_API_ID and TELEGRAM_API_HASH:
                try:
                    # Use a temporary session to fetch reactions
                    temp_session = StringSession()
                    client = TelegramClient(temp_session, int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                    await client.connect()
                    reactions = await _fetch_premium_reactions(client, post_ref, post_id)
                    await client.disconnect()
                    
                    if reactions:
                        context.user_data["legendary_premium_reactions"] = reactions
                        context.user_data["legendary_step"] = "premium_reaction_select"
                        context.user_data["state"] = "legendary_premium_reaction_select"
                        
                        kb_rows = []
                        for i, r in enumerate(reactions[:20]):  # Limit to 20 reactions
                            kb_rows.append([InlineKeyboardButton(r, callback_data=f"legendary:reaction:{i}")])
                        kb_rows.append([InlineKeyboardButton("🎲 عشوائي", callback_data="legendary:reaction:random")])
                        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="legendary_services")])
                        
                        await update.message.reply_text(
                            f"✨ *اختر التفاعل المميز:*\n\n"
                            f"التفاعلات المتاحة على هذا البوست:\n"
                            f"{' '.join(reactions[:20])}\n\n"
                            f"اختر الإيموجي المطلوب من القائمة أدناه، أو اضغط عشوائي:",
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=InlineKeyboardMarkup(kb_rows)
                        )
                        return True
                except Exception as e:
                    logger.warning(f"⚠️ Failed to fetch premium reactions: {e}")
            
            # Fallback: use default premium reactions
            default_reactions = ["❤️", "🔥", "👍", "😍", "🤩", "✨", "💯", "👏"]
            context.user_data["legendary_premium_reactions"] = default_reactions
            context.user_data["legendary_step"] = "premium_reaction_select"
            context.user_data["state"] = "legendary_premium_reaction_select"
            
            kb_rows = []
            for i, r in enumerate(default_reactions):
                kb_rows.append([InlineKeyboardButton(r, callback_data=f"legendary:reaction:{i}")])
            kb_rows.append([InlineKeyboardButton("🎲 عشوائي", callback_data="legendary:reaction:random")])
            kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="legendary_services")])
            
            await update.message.reply_text(
                f"✨ *اختر التفاعل المميز:*\n\n"
                f"اختر الإيموجي المطلوب من القائمة أدناه، أو اضغط عشوائي:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
            return True
    
    # --- Poll option input ---
    if state == "legendary_poll_option_input":
        context.user_data["legendary_poll_option"] = text.strip()
        context.user_data["legendary_step"] = "quantity"
        context.user_data["state"] = "legendary_quantity_input"
        
        available = get_available_sessions_count()
        await update.message.reply_text(
            f"✅ الخيار: {text}\n\n🔢 أرسل عدد التصويتات المطلوبة (1-{available}):",
            parse_mode=ParseMode.MARKDOWN
        )
        return True
    
    # --- Emojis input ---
    if state == "legendary_emojis_input":
        emojis = [line.strip() for line in text.splitlines() if line.strip()]
        if not emojis:
            await update.message.reply_text("⚠️ أرسل إيموجي واحد على الأقل.")
            return True
        
        context.user_data["legendary_emojis"] = emojis
        context.user_data["legendary_step"] = "quantity"
        context.user_data["state"] = "legendary_quantity_input"
        
        available = get_available_sessions_count()
        await update.message.reply_text(
            f"✅ تم حفظ {len(emojis)} إيموجي.\n\n🔢 أرسل عدد المشاهدات المطلوبة (1-{available}):",
            parse_mode=ParseMode.MARKDOWN
        )
        return True
    
    # --- Quantity input ---
    if state == "legendary_quantity_input":
        qty_text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
        if not qty_text.isdigit():
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return True
        
        quantity = int(qty_text)
        available = get_available_sessions_count()
        
        if quantity < 1 or quantity > available:
            await update.message.reply_text(
                f"⚠️ العدد المسموح بين 1 و {available} فقط."
            )
            return True
        
        context.user_data["legendary_quantity"] = quantity
        context.user_data["legendary_step"] = "payment"
        context.user_data["state"] = "legendary_payment_input"
        
        service_name = get_service_display_name(service_type)
        stars_cost = get_stars_price(service_type, quantity)
        points_cost = get_service_price(service_type, include_channel=False) * quantity
        channel_cost = get_service_channel_price(service_type)
        has_channel = bool(context.user_data.get("legendary_channel_ref"))
        if has_channel:
            points_cost += channel_cost
        channel_display = f"+{channel_cost} نقطة" if has_channel and channel_cost > 0 else "مجانية"
        
        # Fix description based on service type
        if service_type == "poll":
            unit_label = "استفتاء"
        elif service_type == "story":
            unit_label = "مشاهدة"
        elif service_type == "premium_reaction":
            unit_label = "تفاعل"
        else:
            unit_label = "وحدة"
        
        await show_payment_options(update, context, service_type, quantity, stars_cost, points_cost, has_channel)
        return True
    
    # --- Delay input (owner only) ---
    if state == "legendary_delay_input" and user.id == OWNER_ID:
        custom_delay = None
        if text.strip().lower() not in ("تخطي", "skip", "-"):
            custom_delay = text.strip()
            try:
                if "-" in custom_delay:
                    parts = custom_delay.split("-")
                    int(parts[0].strip())
                    int(parts[1].strip())
                else:
                    int(custom_delay.strip())
            except ValueError:
                await update.message.reply_text("⚠️ صيغة غير صحيحة. استخدم رقم مثل `5` أو نطاق مثل `30-60`")
                return True
        
        context.user_data["legendary_custom_delay"] = custom_delay
        context.user_data["state"] = "legendary_payment_input"
        
        service_type = context.user_data.get("legendary_service_type", "comment")
        quantity = context.user_data.get("legendary_quantity", 1)
        stars_cost = get_stars_price(service_type, quantity)
        points_cost = get_service_price(service_type, include_channel=False) * quantity
        has_channel = bool(context.user_data.get("legendary_channel_ref"))
        if has_channel:
            points_cost += get_service_channel_price(service_type)
        
        await show_payment_options(update, context, service_type, quantity, stars_cost, points_cost, has_channel)
        return True
    
    # --- Premium reaction: get reactions from post ---
    if state == "legendary_premium_reactions_input":
        # Here we would fetch reactions from the post
        # For now, we'll use a default list
        default_reactions = ["❤️", "🔥", "👍", "😍", "🤩", "✨", "💯", "👏"]
        context.user_data["legendary_premium_reactions"] = default_reactions
        context.user_data["legendary_step"] = "premium_reaction_select"
        context.user_data["state"] = "legendary_premium_reaction_select"
        
        kb_rows = []
        for i, r in enumerate(default_reactions):
            kb_rows.append([InlineKeyboardButton(r, callback_data=f"legendary:reaction:{i}")])
        kb_rows.append([InlineKeyboardButton("🎲 عشوائي", callback_data="legendary:reaction:random")])
        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="legendary_services")])
        
        await update.message.reply_text(
            f"✨ *اختر التفاعل المميز:*\n\n"
            f"اختر الإيموجي المطلوب من القائمة أدناه، أو اضغط عشوائي:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb_rows)
        )
        return True
    
    return False


async def show_payment_options(update, context, service_type, quantity, stars_cost, points_cost, has_channel):
    """Show payment options to user."""
    actor = getattr(update, "effective_user", None)
    if actor is None and getattr(update, "callback_query", None):
        actor = update.callback_query.from_user
    is_owner = bool(actor and actor.id == OWNER_ID)
    
    # Fix labels based on service type
    if service_type == "poll":
        unit_label = "استفتاء"
    elif service_type == "story":
        unit_label = "مشاهدة"
    elif service_type == "premium_reaction":
        unit_label = "تفاعل"
    else:
        unit_label = "وحدة"
    
    payment_rows = [
        [InlineKeyboardButton(f"⭐ دفع بالنجوم ({stars_cost} نجمة)", callback_data="legendary:pay:stars")],
        [InlineKeyboardButton(f"💰 دفع بالنقاط ({points_cost} نقطة)", callback_data="legendary:pay:points")],
    ]
    if is_owner:
        payment_rows.append([
            InlineKeyboardButton("⏱️ تخصيص الفاصل (اختياري)", callback_data="legendary:set_delay")
        ])
    payment_rows.append([InlineKeyboardButton("❌ إلغاء", callback_data="main_menu")])

    await update.message.reply_text(
        f"💎 *اختر طريقة الدفع:*\n\n"
        f"🔢 العدد: {quantity} {unit_label}\n"
        f"📺 القناة: {'مضافة' if has_channel else 'لا'}\n\n"
        f"⭐ *بالنجوم:* {stars_cost} نجمة (القناة مجانية!)\n"
        f"💰 *بالنقاط:* {points_cost} نقطة\n\n"
        f"اختر طريقة الدفع:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(payment_rows)
    )
    context.user_data["legendary_stars_cost"] = stars_cost
    context.user_data["legendary_points_cost"] = points_cost
    context.user_data["state"] = "legendary_payment_confirm"


async def legendary_set_delay(update, context, q, is_own: bool):
    """Open the optional owner-only delay editor without blocking payment choice."""
    if not is_own:
        await q.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
        return
    if context.user_data.get("state") != "legendary_payment_confirm":
        await q.answer("⚠️ انتهت صلاحية الطلب، ابدأ من جديد.", show_alert=True)
        return
    context.user_data["state"] = "legendary_delay_input"
    await q.edit_message_text(
        "⏱️ *تخصيص الفاصل بين الحسابات*\n\n"
        "أرسل رقماً بالثواني مثل `5`، أو نطاقاً مثل `30-60`.\n"
        "اكتب `تخطي` للعودة للفاصل التلقائي (1-8 دقائق).",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=legendary_services_back_kb(),
    )


# ==================== PAYMENT HANDLER ====================

async def legendary_payment_callback(update, context, q, is_own: bool, payment_method: str):
    """Handle payment selection."""
    if context.user_data.get("state") not in ("legendary_payment_confirm", "legendary_payment_input"):
        await q.answer("⚠️ انتهت صلاحية الطلب، ابدأ من جديد.", show_alert=True)
        return
    
    service_type = context.user_data.get("legendary_service_type", "comment")
    quantity = context.user_data.get("legendary_quantity", 1)
    channel_ref = context.user_data.get("legendary_channel_ref")
    custom_delay = context.user_data.get("legendary_custom_delay")
    
    stars_cost = context.user_data.get("legendary_stars_cost", 0)
    points_cost = context.user_data.get("legendary_points_cost", 0)
    
    if payment_method == "stars":
        total_cost = stars_cost
        payment_label = f"{stars_cost} نجمة"
    else:
        total_cost = points_cost
        payment_label = f"{points_cost} نقطة"
    
    requester_id = q.from_user.id

    if payment_method == "points":
        db_user = get_user(requester_id)
        if not db_user or int(db_user.get("points") or 0) < total_cost:
            await q.edit_message_text(
                f"❌ رصيدك غير كافٍ. التكلفة: {total_cost} نقطة.\n"
                f"💰 رصيدك الحالي: {db_user['points'] if db_user else 0} نقطة",
                reply_markup=legendary_services_back_kb()
            )
            context.user_data["state"] = "main_menu"
            return
    
    if payment_method == "stars":
        await q.delete_message()
        await context.bot.send_invoice(
            chat_id=requester_id,
            title=f"{get_service_display_name(service_type)}",
            description=f"{quantity} وحدة | {payment_label}",
            payload=f"legendary_stars:{requester_id}:{service_type}:{quantity}:{stars_cost}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice("خدمة أسطورية", stars_cost)],
        )
        return
    
    await execute_legendary_order(update, context, q, is_own, payment_method)


async def execute_legendary_order(update, context, q, is_own: bool, payment_method: str):
    """Execute the legendary order."""
    service_type = context.user_data.get("legendary_service_type", "comment")
    quantity = context.user_data.get("legendary_quantity", 1)
    channel_ref = context.user_data.get("legendary_channel_ref")
    custom_delay = context.user_data.get("legendary_custom_delay")
    stars_cost = context.user_data.get("legendary_stars_cost", 0)
    points_cost = context.user_data.get("legendary_points_cost", 0)
    requester_id = (
        context.user_data.get("legendary_user_id")
        or getattr(update.effective_user, "id", None)
        or OWNER_ID
    )

    async def edit_order_message(text, **kwargs):
        if hasattr(q, "edit_message_text"):
            return await q.edit_message_text(text, **kwargs)
        return await q.edit_text(text, **kwargs)
    
    if payment_method == "points":
        if not deduct_points(requester_id, points_cost):
            await edit_order_message("❌ لم يعد رصيدك كافياً.")
            context.user_data["state"] = "main_menu"
            return
    
    sessions = _get_all_active_sessions()
    if not sessions:
        if payment_method == "points":
            add_points(requester_id, points_cost)
        await edit_order_message(
            "❌ لا توجد حسابات متاحة.",
            reply_markup=legendary_services_back_kb(),
        )
        context.user_data["state"] = "main_menu"
        return
    
    # Only send start message if not owner (owner doesn't get group notifications)
    if requester_id != OWNER_ID:
        await _send_start_message(context.bot, requester_id, quantity, payment_method, service_type)
    
    params = {"channel_ref": channel_ref}
    
    if service_type == "comment":
        params["post_ref"] = context.user_data.get("legendary_post_ref")
        params["post_id"] = context.user_data.get("legendary_post_id")
        params["comment_text"] = context.user_data.get("legendary_comment_text", "")
    elif service_type == "poll":
        params["poll_link"] = context.user_data.get("legendary_poll_link")
        params["poll_option"] = context.user_data.get("legendary_poll_option", "1")
    elif service_type == "story":
        params["story_link"] = context.user_data.get("legendary_story_link")
        params["emojis"] = context.user_data.get("legendary_emojis", ["❤️"])
    elif service_type in ["votes", "votes_ai"]:
        params["post_ref"] = context.user_data.get("legendary_post_ref")
        params["post_id"] = context.user_data.get("legendary_post_id")
    elif service_type == "premium_reaction":
        params["post_ref"] = context.user_data.get("legendary_post_ref")
        params["post_id"] = context.user_data.get("legendary_post_id")
        params["reaction_text"] = context.user_data.get("legendary_reaction_text", "❤️")
    
    progress_msg = await edit_order_message(
        f"⏳ *جاري التنفيذ...*\n\n📊 0/{quantity}",
        parse_mode=ParseMode.MARKDOWN,
    )
    
    async def update_progress(current, total, success, failed):
        try:
            await progress_msg.edit_text(
                f"⏳ *جاري التنفيذ...*\n\n"
                f"📊 {current}/{total}\n"
                f"✅ {success} نجح | ❌ {failed} فشل",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
    
    success_count, success_phones, failed_details = await execute_batch(
        service_type=service_type,
        quantity=quantity,
        sessions=sessions,
        params=params,
        is_owner=is_own,
        custom_delay=custom_delay,
        progress_callback=update_progress,
    )
    
    failed_count = quantity - success_count
    refund_points = 0
    
    if failed_count > 0 and payment_method == "points":
        refund_points = failed_count * get_service_price(service_type, include_channel=False)
        if refund_points > 0:
            add_points(requester_id, refund_points)
    
    # Send group notification only if requester is not owner
    if requester_id != OWNER_ID:
        await _send_group_notification(
            context.bot,
            requester_id,
            quantity,
            success_count,
            failed_count,
            refund_points,
            "نجوم" if payment_method == "stars" else "نقاط",
            service_type
        )
    
    # Always send completion message to requester
    await _send_completion_message(
        context.bot,
        requester_id,
        quantity,
        success_count,
        failed_count,
        refund_points,
        "نجوم" if payment_method == "stars" else "نقاط",
        service_type
    )
    
    result = f"✅ *اكتمل طلب {get_service_display_name(service_type)}!*\n\n"
    result += f"📊 المطلوب: {quantity}\n"
    result += f"✅ المنجز: {success_count}\n"
    result += f"❌ الفاشل: {failed_count}\n"
    result += f"💰 طريقة الدفع: {'نجوم' if payment_method == 'stars' else 'نقاط'}\n"
    
    if refund_points > 0:
        result += f"💰 تم تعويضك: {refund_points} نقطة\n"
    
    # Add success and failed phone lists
    if success_phones:
        result += f"\n✅ *الحسابات الناجحة:*\n"
        result += "\n".join(f"• `{p}`" for p in success_phones[:20])
        if len(success_phones) > 20:
            result += f"\n... و{len(success_phones)-20} أخرى"
    
    if failed_details:
        result += f"\n\n❌ *الفاشلة:*\n"
        result += "\n".join(f"• {d}" for d in failed_details[:10])
        if len(failed_details) > 10:
            result += f"\n... و{len(failed_details)-10} أخرى"
    
    await edit_order_message(
        result,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb(is_own),
    )
    context.user_data["state"] = "main_menu"


# ==================== NOTIFICATIONS ====================

async def _send_start_message(bot, user_id, quantity, payment_method, service_type):
    """Send start message."""
    try:
        text = (
            f"⏳ *بدأ تنفيذ طلب {get_service_display_name(service_type)}!*\n\n"
            f"📊 المطلوب: {quantity}\n"
            f"💰 طريقة الدفع: {payment_method}\n\n"
            f"سيتم إعلامك عند الاكتمال."
        )
        await bot.send_message(user_id, text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass


async def _send_completion_message(bot, user_id, quantity, success_count, failed_count, refund_points, payment_method, service_type):
    """Send completion message."""
    try:
        text = (
            f"✅ *اكتمل طلب {get_service_display_name(service_type)}!*\n\n"
            f"📊 المطلوب: {quantity}\n"
            f"✅ المنجز: {success_count}\n"
            f"❌ الفاشل: {failed_count}\n"
            f"💰 طريقة الدفع: {payment_method}\n"
        )
        if refund_points > 0:
            text += f"💰 تم تعويضك: {refund_points} نقطة\n"
        await bot.send_message(user_id, text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass


async def _send_group_notification(bot, user_id, quantity, success_count, failed_count, refund_points, payment_method, service_type):
    """Send group notification - only for non-owner requests."""
    if not ADMIN_GROUP_ID:
        return
    # Don't send to group if the requester is the owner
    if user_id == OWNER_ID:
        return
    
    try:
        text = (
            f"📢 *تم إنجاز طلب {get_service_display_name(service_type)}!*\n\n"
            f"👤 المستخدم: <code>{user_id}</code>\n"
            f"📊 المطلوب: {quantity}\n"
            f"✅ المنجز: {success_count}\n"
            f"❌ الفاشل: {failed_count}\n"
            f"💰 طريقة الدفع: {payment_method}\n"
        )
        if refund_points > 0:
            text += f"💰 تم تعويض: {refund_points} نقطة\n"
        await bot.send_message(ADMIN_GROUP_ID, text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass


# ==================== ADMIN PRICE SETTINGS ====================

def get_price_settings_kb() -> InlineKeyboardMarkup:
    """Generate keyboard for price settings."""
    buttons = []
    for key, display in [
        ("comment", "💬 تعليق"),
        ("poll", "📊 استفتاء"),
        ("story", "👁 ستوري"),
        ("votes", "🗳 أصوات"),
        ("votes_ai", "🤖 تصويت بتحقق"),
        ("premium_reaction", "✨ تفاعل مميز"),
    ]:
        current = get_service_price(key, include_channel=False)
        channel = get_service_channel_price(key)
        buttons.append([
            InlineKeyboardButton(
                f"{display}: {current} نقطة (+{channel} قناة)",
                callback_data=f"legendary:edit_price:{key}"
            )
        ])
    
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
    return InlineKeyboardMarkup(buttons)


async def legendary_edit_price(update, context, q, is_own: bool, service_type: str):
    """Start price editing for a service."""
    if not is_own:
        await q.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
        return
    
    context.user_data["legendary_edit_price_service"] = service_type
    context.user_data["state"] = "legendary_edit_price_input"
    
    current = get_service_price(service_type, include_channel=False)
    channel = get_service_channel_price(service_type)
    
    await q.edit_message_text(
        f"✏️ *تعديل سعر {get_service_display_name(service_type)}*\n\n"
        f"💰 السعر الحالي: {current} نقطة/وحدة\n"
        f"📺 سعر القناة: {channel} نقطة\n\n"
        f"أرسل السعر الجديد للوحدة (بدون القناة):",
        parse_mode=ParseMode.MARKDOWN
    )


async def legendary_handle_price_edit(update, context, text: str) -> bool:
    """Handle price edit text input."""
    user = update.effective_user
    if user.id != OWNER_ID:
        return False
    
    if context.user_data.get("state") != "legendary_edit_price_input":
        return False
    
    service_type = context.user_data.get("legendary_edit_price_service")
    if not service_type:
        return False
    
    try:
        new_price = int(text.strip())
        if new_price < 1:
            await update.message.reply_text("⚠️ السعر يجب أن يكون أكبر من 0.")
            return True
    except ValueError:
        await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
        return True
    
    key = PRICE_SETTINGS_KEYS.get(service_type)
    if key:
        set_setting(key, str(new_price))
    
    context.user_data["state"] = "main_menu"
    context.user_data.pop("legendary_edit_price_service", None)
    
    await update.message.reply_text(
        f"✅ تم تحديث سعر {get_service_display_name(service_type)} إلى {new_price} نقطة.",
        reply_markup=get_price_settings_kb()
    )
    return True


# ==================== PREMIUM REACTION HANDLER ====================

async def legendary_premium_reaction_callback(update, context, q, is_own: bool, data: str):
    """Handle premium reaction selection including random."""
    if context.user_data.get("state") != "legendary_premium_reaction_select":
        await q.answer("⚠️ انتهت صلاحية الطلب، ابدأ من جديد.", show_alert=True)
        return
    
    if data == "legendary:reaction:random":
        reactions = context.user_data.get("legendary_premium_reactions", ["❤️", "🔥", "👍", "😍", "🤩", "✨", "💯", "👏"])
        reaction = random.choice(reactions)
        context.user_data["legendary_reaction_text"] = reaction
        await q.answer(f"🎲 تم اختيار: {reaction}", show_alert=True)
        
        # Proceed to quantity
        context.user_data["legendary_step"] = "quantity"
        context.user_data["state"] = "legendary_quantity_input"
        available = get_available_sessions_count()
        await q.edit_message_text(
            f"✅ تم اختيار التفاعل: {reaction}\n\n🔢 أرسل عدد الوحدات المطلوبة (1-{available}):",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Parse reaction index
    try:
        idx = int(data.split(":")[2])
        reactions = context.user_data.get("legendary_premium_reactions", ["❤️", "🔥", "👍", "😍", "🤩", "✨", "💯", "👏"])
        if idx < 0 or idx >= len(reactions):
            raise ValueError
        reaction = reactions[idx]
    except (IndexError, ValueError):
        await q.answer("⚠️ اختيار غير صالح.", show_alert=True)
        return
    
    context.user_data["legendary_reaction_text"] = reaction
    await q.answer(f"✅ تم اختيار: {reaction}", show_alert=False)
    
    # Proceed to quantity
    context.user_data["legendary_step"] = "quantity"
    context.user_data["state"] = "legendary_quantity_input"
    available = get_available_sessions_count()
    await q.edit_message_text(
        f"✅ تم اختيار التفاعل: {reaction}\n\n🔢 أرسل عدد الوحدات المطلوبة (1-{available}):",
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== VISIBILITY TOGGLE HANDLER ====================

async def legendary_toggle_visibility(update, context, q, is_own: bool, data: str):
    """Toggle visibility of a legendary service."""
    if not is_own:
        await q.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
        return
    
    service_type = data.split(":")[2]
    new_state = toggle_legendary_service_visibility(service_type)
    status = "ظاهر ✅" if new_state else "مخفي 🔒"
    
    await q.answer(f"🔘 الخدمة الآن: {status}", show_alert=True)
    
    # Refresh the visibility settings screen
    await q.edit_message_reply_markup(reply_markup=get_legendary_visibility_kb())
