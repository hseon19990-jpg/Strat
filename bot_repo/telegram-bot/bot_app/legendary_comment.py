"""Legendary Services - Complete module for all legendary services.

Services included:
1. Comment - Multi-comment with channel option
2. Poll - Vote on polls
3. Story Views + Reactions - View stories and react with emojis
4. Votes - Regular voting
5. Votes with AI - Voting with captcha solving (Groq/DeepSeek)
6. Premium Reaction - Special reactions on posts (with random or same emoji)
7. Forced Referral with AI verification (NEW)

All services support:
- Payment by points or stars
- Channel join (optional, with skip)
- Random delay between accounts (1-8 min default, owner can customize)
- Fallback accounts on failure
- No duplicate accounts
- Owner can customize welcome message, prices, delays
"""

from . import shared as _shared

globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

from urllib.parse import urlparse
import asyncio
import time
import random
import re
import json


# ==================== CONSTANTS ====================
LEGENDARY_STAY_HOURS = 24
MIN_DELAY_MINUTES = 1
MAX_DELAY_MINUTES = 8
MAX_QUANTITY = 50
MAX_FALLBACK_ATTEMPTS = 5

# ==================== SETTINGS KEYS ====================
LEGENDARY_SETTINGS_KEYS = {
    "welcome_message": "legendary_welcome_message",
    "comment_price_points": "legendary_price_comment_points",
    "comment_price_stars": "legendary_price_comment_stars",
    "poll_price_points": "legendary_price_poll_points",
    "poll_price_stars": "legendary_price_poll_stars",
    "story_price_points": "legendary_price_story_points",
    "story_price_stars": "legendary_price_story_stars",
    "votes_price_points": "legendary_price_votes_points",
    "votes_price_stars": "legendary_price_votes_stars",
    "votes_ai_price_points": "legendary_price_votes_ai_points",
    "votes_ai_price_stars": "legendary_price_votes_ai_stars",
    "premium_reaction_price_points": "legendary_price_premium_reaction_points",
    "premium_reaction_price_stars": "legendary_price_premium_reaction_stars",
    "forced_ref_ai_price_points": "legendary_price_forced_ref_ai_points",
    "forced_ref_ai_price_stars": "legendary_price_forced_ref_ai_stars",
    "comment_enabled": "legendary_comment_enabled",
    "poll_enabled": "legendary_poll_enabled",
    "story_enabled": "legendary_story_enabled",
    "votes_enabled": "legendary_votes_enabled",
    "votes_ai_enabled": "legendary_votes_ai_enabled",
    "premium_reaction_enabled": "legendary_premium_reaction_enabled",
    "forced_ref_ai_enabled": "legendary_forced_ref_ai_enabled",
}

# ==================== DEFAULT PRICES ====================
DEFAULT_PRICES = {
    "comment": {"points": 30, "stars": 5, "channel_points": 30},
    "poll": {"points": 30, "stars": 5, "channel_points": 30},
    "story": {"points": 30, "stars": 10, "channel_points": 30},
    "votes": {"points": 20, "stars": 10, "channel_points": 25},
    "votes_ai": {"points": 50, "stars": 4, "channel_points": 25},
    "premium_reaction": {"points": 10, "stars": 25, "channel_points": 0},
    "forced_ref_ai": {"points": 300, "stars": 3, "channel_points": 25},  # 1.5 star/acc requires even numbers for payment
}

DEFAULT_WELCOME_MESSAGE = (
    "👑 أهلاً بك في أفضل قسم للرشق!\n\n"
    "يمكنك الحصول على رشق بحسابات حقيقية\n"
    "تحتوي أسماء عربية، بايو، ستوري، وأفتار نشطة.\n"
    "اختر الخدمة المناسبة لك:"
)


# ==================== HELPERS ====================

def get_legendary_welcome() -> str:
    """Get the welcome message for legendary services."""
    return get_setting("legendary_welcome_message") or DEFAULT_WELCOME_MESSAGE


def set_legendary_welcome(message: str):
    """Set the welcome message for legendary services."""
    set_setting("legendary_welcome_message", message)


def is_service_enabled(service_type: str) -> bool:
    """Check if a legendary service is enabled."""
    key = LEGENDARY_SETTINGS_KEYS.get(f"{service_type}_enabled")
    if key:
        return get_setting(key) != "0"
    return True


def get_service_price_points(service_type: str, include_channel: bool = False) -> int:
    """Get current price for a service in points."""
    key = LEGENDARY_SETTINGS_KEYS.get(f"{service_type}_price_points")
    if key:
        saved = get_setting(key)
        if saved:
            try:
                return int(saved)
            except ValueError:
                pass
    base = DEFAULT_PRICES.get(service_type, {}).get("points", 30)
    channel = DEFAULT_PRICES.get(service_type, {}).get("channel_points", 0)
    return base + (channel if include_channel else 0)


def get_service_price_stars(service_type: str) -> int:
    """Get current price for a service in stars (per unit)."""
    key = LEGENDARY_SETTINGS_KEYS.get(f"{service_type}_price_stars")
    if key:
        saved = get_setting(key)
        if saved:
            try:
                return int(saved)
            except ValueError:
                pass
    return DEFAULT_PRICES.get(service_type, {}).get("stars", 5)


def get_service_channel_price(service_type: str) -> int:
    """Get channel price for a service in points."""
    return DEFAULT_PRICES.get(service_type, {}).get("channel_points", 0)


def get_service_display_name(service_type: str) -> str:
    """Get display name for a service type."""
    names = {
        "comment": "رشق تعليق",
        "poll": "رشق استفتاء",
        "story": "رشق مشاهدة وتفاعل ستوري",
        "votes": "رشق أصوات",
        "votes_ai": "رشق تصويت بتحقق",
        "premium_reaction": "رشق تفاعل مميز",
        "forced_ref_ai": "إحالة بوت إجباري تحتوي تحقق",
    }
    return names.get(service_type, service_type)


def get_service_description(service_type: str) -> str:
    """Get service description for display."""
    descriptions = {
        "comment": "📝 إضافة تعليقات على منشورك",
        "poll": "📊 التصويت في استفتاءاتك",
        "story": "👁 مشاهدة وتفاعل مع ستورياتك",
        "votes": "🗳 تصويت على استفتاءاتك",
        "votes_ai": "🤖 تصويت مع حل تحقق تلقائي",
        "premium_reaction": "✨ تفاعلات مميزة على منشورك",
        "forced_ref_ai": "🤖 إحالة إجبارية مع حل تحقق تلقائي للبوت المستهدف",
    }
    return descriptions.get(service_type, "")


def _get_all_active_sessions() -> list[dict]:
    """Load ALL active sessions from the stock (including sold accounts)."""
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, phone_number, session_string "
            "FROM number_stock "
            "WHERE session_string IS NOT NULL AND BTRIM(session_string) <> '' "
            "AND deleted_at IS NULL AND last_authorized IS NOT FALSE "
            "ORDER BY id ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_available_sessions_count() -> int:
    """Return the number of available sessions."""
    return len(_get_all_active_sessions())


def _parse_channel_reference(value: str) -> tuple[str | None, str | None]:
    """Parse a channel reference from various formats."""
    value = (value or "").strip().strip("<>")
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
    """Parse a post link into entity and message ID."""
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


def _clean_link(value: str) -> str:
    return (value or "").strip().strip("<>")


def _extract_emojis_from_text(text: str) -> list:
    """Extract all emojis from text."""
    result = []
    for ch in text:
        cp = ord(ch)
        if (0x1F300 <= cp <= 0x1FFFF or
            0x2600 <= cp <= 0x27BF or
            0x1F900 <= cp <= 0x1F9FF or
            0x1FA00 <= cp <= 0x1FAFF):
            result.append(ch)
    return result


def get_delay_seconds(is_owner: bool, custom_delay: str = None) -> int:
    """Get delay between accounts. Owner can customize."""
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
    if not channel_ref:
        return
    try:
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
    except Exception as e:
        logger.warning(f"⚠️ Failed to join channel {channel_ref}: {e}")


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


# ==================== CAPTCHA SOLVING ====================

async def _solve_captcha_with_ai(client, bot_entity, msgs: list, phone: str = "", max_attempts: int = 3) -> tuple:
    """
    Solve captcha using Groq or DeepSeek.
    Returns (solved: bool, detail: str).
    """
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

    if not GROQ_API_KEY and not DEEPSEEK_API_KEY:
        return False, "لا يوجد مفتاح API للتحقق (Groq أو DeepSeek)"

    # ── كلمات دلالية ──────────────────────────────────────────
    SUCCESS_KW = [
        "✅", "تم", "نجح", "مبروك", "أهلاً", "مرحباً", "welcome", "success",
        "تم التحقق", "مقبول", "accepted", "verified", "شكراً", "برافو",
        "اشتركت", "سجلت", "تسجيل", "دخلت", "ترحيب", "congratulations",
        "passed", "اجتزت", "صحيح", "correct", "ممتاز", "👍", "تم قبولك",
        "تم التسجيل", "انتهت عملية", "تم التفعيل", "بنجاح",
    ]
    FAIL_KW = [
        "خطأ", "غلط", "wrong", "incorrect", "فشل", "error", "❌",
        "حاول مجدداً", "try again", "retry", "invalid", "غير صحيح",
        "أعد", "مجدداً", "again", "حاول ثانية", "إجابة خاطئة",
    ]
    CAPTCHA_KW = [
        "تحقق", "verify", "captcha", "اضغط", "ادخل", "أجب", "اختر",
        "robot", "بشر", "human", "confirm", "verification", "كابتشا",
        "لست روبوت", "لست بوت", "not a robot", "prove", "إثبت",
    ]
    MATH_KW = ["=", "؟", "?", "كم", "احسب", "حل", "اكتب", "أدخل", "اجمع", "اطرح", "اضرب", "اقسم", "ناتج", "حاصل", "result", "calculate", "solve", "answer", "الإجابة", "الجواب", "الرقم"]
    FORWARD_KW = ["شارك", "أرسل ملف", "ارسل ملف", "forward", "ملفك الشخصي", "profile", "بروفايل", "contact", "جهة اتصال", "رقمك", "رقم هاتفك", "شارك ملفك", "ارسل بياناتك", "بياناتك الشخصية"]
    REACTION_KW = ["تفاعل", "react", "reaction", "اضغط على", "ارسل إيموجي", "أرسل إيموجي", "انقر", "إيموجي", "emoji", "رد بـ", "reply with", "أرسل رد", "ارسل رد"]

    async def _chat_request(api_key: str, url: str, model: str, prompt: str) -> str | None:
        if not api_key:
            return None
        def _do_request():
            try:
                r = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 50, "temperature": 0},
                    timeout=30,
                )
                if r.status_code == 200:
                    data = r.json()
                    if data.get("choices"):
                        return data["choices"][0]["message"]["content"].strip()
            except Exception:
                pass
            return None
        try:
            return await asyncio.to_thread(_do_request)
        except Exception:
            return None

    def _is_success(text: str) -> bool:
        t = (text or "").lower()
        return any(k.lower() in t for k in SUCCESS_KW)

    def _is_fail(text: str) -> bool:
        t = (text or "").lower()
        return any(k.lower() in t for k in FAIL_KW)

    def _extract_emojis(text: str) -> list:
        result = []
        for ch in text:
            cp = ord(ch)
            if (0x1F300 <= cp <= 0x1FFFF or 0x2600 <= cp <= 0x27BF or 0x1F900 <= cp <= 0x1F9FF or 0x1FA00 <= cp <= 0x1FAFF):
                result.append(ch)
        return result

    async def _wait_and_check(limit: int = 5) -> tuple:
        await asyncio.sleep(3)
        new_msgs = await client.get_messages(bot_entity, limit=limit)
        for m in new_msgs:
            t = getattr(m, "message", "") or ""
            if _is_success(t):
                return "success", new_msgs
            if _is_fail(t):
                return "fail", new_msgs
        return "unknown", new_msgs

    async def _solve_text(prompt: str) -> str | None:
        result = await _chat_request(
            GROQ_API_KEY,
            "https://api.groq.com/openai/v1/chat/completions",
            "llama-3.3-70b-versatile",
            prompt,
        )
        if result:
            return result
        return await _chat_request(
            DEEPSEEK_API_KEY,
            "https://api.deepseek.com/chat/completions",
            "deepseek-chat",
            prompt,
        )

    async def _solve_image(prompt: str, img_bytes: bytes) -> str | None:
        if GROQ_API_KEY:
            def _do_vision_request():
                try:
                    img_b64 = base64.b64encode(img_bytes).decode()
                    r = requests.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                        json={"model": "meta-llama/llama-4-scout-17b-16e-instruct", "messages": [{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                            ],
                        }], "max_tokens": 50, "temperature": 0},
                        timeout=35,
                    )
                    if r.status_code == 200:
                        data = r.json()
                        if data.get("choices"):
                            return data["choices"][0]["message"]["content"].strip()
                except Exception:
                    pass
                return None
            try:
                return await asyncio.to_thread(_do_vision_request)
            except Exception:
                return None
        return None

    all_details: list[str] = []
    processed_ids: set[int] = set()

    for _round in range(max_attempts):
        if _round > 0:
            await asyncio.sleep(4)
            msgs = await client.get_messages(bot_entity, limit=15)

        for msg in msgs:
            msg_id = getattr(msg, "id", 0)
            if msg_id in processed_ids:
                continue

            msg_text = getattr(msg, "message", "") or getattr(msg, "text", "") or ""
            msg_text_lower = msg_text.lower()
            has_photo = bool(getattr(msg, "photo", None))
            has_doc = bool(getattr(msg, "document", None))
            has_media = has_photo or has_doc
            has_btns = bool(msg.buttons)
            has_poll = bool(getattr(msg, "poll", None))

            if _is_success(msg_text) and all_details:
                return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"

            # ── Image CAPTCHA ──
            if has_media:
                try:
                    img_bytes = await client.download_media(msg, bytes)
                    if not img_bytes:
                        continue
                    prompt = (
                        "هذه صورة كابتشا (CAPTCHA) من بوت تيليغرام.\n"
                        f"النص المرافق للصورة: {msg_text or '(لا يوجد)'}\n\n"
                        "اقرأ بدقة النص أو الأرقام الظاهرة في الصورة وأجب بها فقط "
                        "بدون أي شرح أو مسافات إضافية."
                    )
                    answer = await _solve_image(prompt, img_bytes)
                    if answer:
                        logger.info(f"🤖 AI كابتشا صورة → '{answer}' ({phone})")
                        processed_ids.add(msg_id)
                        await asyncio.sleep(1)
                        await client.send_message(bot_entity, answer)
                        result, msgs = await _wait_and_check()
                        all_details.append(f"كابتشا صورة: {answer}")
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result == "fail":
                            break
                        else:
                            return True, f"أُرسلت إجابة الصورة | {' | '.join(all_details)}"
                except Exception as _e:
                    logger.warning(f"⚠️ AI image captcha ({phone}): {_e}")
                continue

            # ── Forward Profile ──
            if any(k in msg_text_lower for k in FORWARD_KW):
                try:
                    from telethon.tl.types import InputMediaContact
                    me = await client.get_me()
                    first = getattr(me, "first_name", "") or ""
                    last = getattr(me, "last_name", "") or ""
                    ph = getattr(me, "phone", "") or phone.lstrip("+")
                    if not ph.startswith("+"):
                        ph = "+" + ph
                    processed_ids.add(msg_id)
                    await client.send_file(
                        bot_entity,
                        InputMediaContact(phone_number=ph, first_name=first, last_name=last, vcard=""),
                    )
                    result, msgs = await _wait_and_check()
                    all_details.append("شارك ملفه الشخصي (Contact)")
                    if result == "success":
                        return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                    elif result == "fail":
                        break
                    else:
                        return True, f"أُرسل الملف الشخصي | {' | '.join(all_details)}"
                    continue
                except Exception as _e:
                    logger.warning(f"⚠️ AI forward profile ({phone}): {_e}")

            # ── Poll / Quiz ──
            if has_poll:
                try:
                    poll_obj = msg.poll.poll
                    question = getattr(poll_obj, "question", "") or ""
                    answers = [getattr(a, "text", "") for a in (getattr(poll_obj, "answers", []) or [])]
                    if question and answers:
                        prompt = (
                            f"بوت تيليغرام يطرح اختباراً:\nالسؤال: {question}\n"
                            "الخيارات:\n" + "\n".join(f"{i+1}. {a}" for i, a in enumerate(answers)) + "\n\n"
                            "أي خيار هو الصحيح؟ أجب برقم الخيار فقط (1، 2، 3...)."
                        )
                        ai_ans = await _solve_text(prompt)
                        chosen_idx = 0
                        if ai_ans:
                            nums = re.findall(r"\d+", ai_ans)
                            if nums:
                                chosen_idx = max(0, int(nums[0]) - 1)
                            else:
                                for i, a in enumerate(answers):
                                    if ai_ans.strip().lower() in a.lower():
                                        chosen_idx = i
                                        break
                        chosen_idx = min(chosen_idx, len(answers) - 1)
                        processed_ids.add(msg_id)
                        await msg.click(chosen_idx)
                        result, msgs = await _wait_and_check()
                        all_details.append(f"أجاب Poll: {answers[chosen_idx]}")
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result == "fail":
                            break
                        else:
                            return True, f"أجاب على اختبار | {' | '.join(all_details)}"
                        continue
                except Exception as _e:
                    logger.warning(f"⚠️ AI poll captcha ({phone}): {_e}")

            # ── Buttons ──
            if has_btns and msg_text:
                try:
                    btn_labels = []
                    btn_objects = {}
                    for row in msg.buttons:
                        for btn in row:
                            label = getattr(btn, "text", "") or ""
                            url = getattr(btn, "url", None) or ""
                            if url and ("t.me/" in url or "telegram.me/" in url):
                                continue
                            if label:
                                btn_labels.append(label)
                                btn_objects[label] = btn
                    if not btn_labels:
                        continue

                    is_verif = (
                        any(k in msg_text_lower for k in CAPTCHA_KW)
                        or any(k in msg_text_lower for k in MATH_KW)
                        or any(k in msg_text_lower for k in REACTION_KW)
                        or "select" in msg_text_lower or "choose" in msg_text_lower
                        or "click" in msg_text_lower or "press" in msg_text_lower or "pick" in msg_text_lower
                    )
                    if not is_verif:
                        continue

                    # Direct emoji detection
                    direct_chosen = None
                    is_emoji_select = (
                        "correct emoji" in msg_text_lower or "select emoji" in msg_text_lower
                        or "choose emoji" in msg_text_lower or "pick emoji" in msg_text_lower
                        or "اختر الإيموجي" in msg_text or "الإيموجي الصحيح" in msg_text
                    )
                    if is_emoji_select:
                        msg_emojis = _extract_emojis_from_text(msg_text)
                        if msg_emojis:
                            target_emoji = msg_emojis[0]
                            for lbl, btn in btn_objects.items():
                                if target_emoji in lbl:
                                    direct_chosen = btn
                                    break
                            if not direct_chosen:
                                for lbl, btn in btn_objects.items():
                                    btn_emojis = _extract_emojis_from_text(lbl)
                                    if btn_emojis and btn_emojis[0] == target_emoji:
                                        direct_chosen = btn
                                        break

                    if direct_chosen:
                        processed_ids.add(msg_id)
                        await direct_chosen.click()
                        result, msgs = await _wait_and_check()
                        all_details.append(f"ضغط إيموجي مباشر: {getattr(direct_chosen, 'text', '')}")
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result == "fail":
                            break
                        else:
                            return True, f"ضغط الإيموجي | {' | '.join(all_details)}"
                    else:
                        all_emoji_btns = all(bool(_extract_emojis_from_text(lbl)) for lbl in btn_labels)
                        if all_emoji_btns:
                            prompt = (
                                f"Telegram bot verification:\n{msg_text}\n\n"
                                "Available emoji buttons:\n" + "\n".join(f"- {b}" for b in btn_labels) +
                                "\n\nWhich emoji button should be clicked? Reply with ONLY the exact emoji character, nothing else."
                            )
                        else:
                            prompt = (
                                f"بوت تيليغرام يطلب التحقق:\n{msg_text}\n\n"
                                "الأزرار المتاحة:\n" + "\n".join(f"- {b}" for b in btn_labels) +
                                "\n\nأي زر يجب الضغط عليه؟ أجب بنص الزر فقط كما هو بالضبط."
                            )
                        answer = await _solve_text(prompt)
                        if answer:
                            chosen = None
                            a_clean = answer.strip()
                            a_lower = a_clean.lower()
                            for label, btn in btn_objects.items():
                                if label.strip() == a_clean:
                                    chosen = btn
                                    break
                            if not chosen:
                                ans_emojis = _extract_emojis_from_text(a_clean)
                                if ans_emojis:
                                    for label, btn in btn_objects.items():
                                        if ans_emojis[0] in label:
                                            chosen = btn
                                            break
                            if not chosen:
                                for label, btn in btn_objects.items():
                                    if a_lower in label.lower() or label.lower() in a_lower:
                                        chosen = btn
                                        break
                            if not chosen:
                                chosen = list(btn_objects.values())[0]
                            processed_ids.add(msg_id)
                            await chosen.click()
                            result, msgs = await _wait_and_check()
                            all_details.append(f"ضغط زر: {getattr(chosen, 'text', '')}")
                            if result == "success":
                                return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                            elif result == "fail":
                                break
                            else:
                                return True, f"ضغط الزر | {' | '.join(all_details)}"
                except Exception as _e:
                    logger.warning(f"⚠️ AI button captcha ({phone}): {_e}")
                continue

            # ── Text Question ──
            if msg_text and not has_btns and not has_media and not has_poll:
                is_captcha_q = any(k in msg_text_lower for k in CAPTCHA_KW)
                is_math_q = any(k in msg_text_lower for k in MATH_KW)
                is_react_q = any(k in msg_text_lower for k in REACTION_KW)
                if not (is_captcha_q or is_math_q or is_react_q):
                    continue
                try:
                    prompt = (
                        f"بوت تيليغرام يطرح هذا السؤال للتحقق:\n{msg_text}\n\n"
                        "أجب بالرقم أو النص أو الإيموجي المطلوب فقط "
                        "بدون أي شرح أو رموز إضافية. إذا كان السؤال رياضياً أجب بالرقم فقط."
                    )
                    answer = await _solve_text(prompt)
                    if answer:
                        processed_ids.add(msg_id)
                        await asyncio.sleep(1)
                        await client.send_message(bot_entity, answer)
                        result, msgs = await _wait_and_check()
                        all_details.append(f"أجاب: {answer}")
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result == "fail":
                            break
                        else:
                            return True, f"أُرسلت الإجابة | {' | '.join(all_details)}"
                except Exception as _e:
                    logger.warning(f"⚠️ AI text captcha ({phone}): {_e}")

            # ── Reaction ──
            if any(k in msg_text_lower for k in REACTION_KW):
                try:
                    from telethon.tl.functions.messages import SendReactionRequest
                    from telethon.tl.types import ReactionEmoji
                    prompt = (
                        f"بوت تيليغرام يطلب منك التفاعل:\n{msg_text}\n\n"
                        "ما هو الإيموجي أو التفاعل المطلوب؟ أجب بالإيموجي فقط (مثال: 👍 أو ❤️ أو 🔥)."
                    )
                    emoji_answer = await _solve_text(prompt)
                    if emoji_answer:
                        emoji_clean = emoji_answer.strip().split()[0]
                        processed_ids.add(msg_id)
                        await client(SendReactionRequest(
                            peer=bot_entity,
                            msg_id=msg_id,
                            reaction=[ReactionEmoji(emoticon=emoji_clean)],
                        ))
                        result, msgs = await _wait_and_check()
                        all_details.append(f"تفاعل: {emoji_clean}")
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result != "fail":
                            return True, f"أُرسل التفاعل | {' | '.join(all_details)}"
                except Exception as _e:
                    logger.warning(f"⚠️ AI reaction ({phone}): {_e}")

    if all_details:
        return True, f"حُلّ جزئياً | {' | '.join(all_details)}"
    return False, "لم يُكتشف تحقق"


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
            # Check if there's a captcha
            await asyncio.sleep(2)
            check_msgs = await client.get_messages(post_entity, limit=5)
            has_captcha = False
            for m in check_msgs:
                text = (m.text or "").lower()
                if any(k in text for k in ["captcha", "تحقق", "verify", "robot"]):
                    has_captcha = True
                    break

            if has_captcha:
                solved, detail = await _solve_captcha_with_ai(
                    client, post_entity, check_msgs, session["phone_number"]
                )
                if not solved:
                    return False, f"فشل حل التحقق: {detail}"
                # Refresh messages after solving
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
    Execute a batch of operations across sessions with fallback support.
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
    fallback_attempts = 0

    # Define executors for Legendary services
    executors = {
        "comment": _execute_comment,
        "poll": _execute_poll_vote,
        "story": _execute_story_reaction,
        "votes": _execute_vote,
        "votes_ai": _execute_vote,
        "premium_reaction": _execute_premium_reaction,
    }

    executor = executors.get(service_type)
    
    # For Forced Ref AI, we use the specific referral logic, not the vote logic
    if service_type == "forced_ref_ai":
        # This function is replaced by the custom execution loop below
        pass

    # If it's a standard legendary service
    if service_type != "forced_ref_ai" and executor is None:
        raise RuntimeError(f"خدمة غير معروفة: {service_type}")

    if service_type == "forced_ref_ai":
        # Custom execution for Forced Ref AI
        bot_user = params.get("bot_user")
        start_p = params.get("start_p", "")
        channels = params.get("channels", "")
        leave_after = params.get("leave_after", True)

        if not bot_user:
            raise RuntimeError("اسم البوت غير مكتمل في المعاملات.")

        for i in range(quantity):
            if not fallback_pool:
                break

            session = fallback_pool.pop(0)
            phone = session["phone_number"]

            if phone in used_phones:
                continue
            used_phones.add(phone)

            # Execute the referral
            try:
                # Check environment variables required for AI
                if not is_ai_available():
                    ok, detail = False, "لا يوجد مفتاح AI (Groq أو DeepSeek) للتحقق"
                else:
                    # Here we use the core referral function directly
                    ok, reactiv, detail = await do_referral_for_number(
                        phone, session["session_string"],
                        bot_user, start_p,
                        mandatory_channels=channels,
                        use_ai=True,
                        leave_channels_after=leave_after,
                        stock_id=session.get("id", 0),
                    )

                if ok:
                    success_count += 1
                    success_phones.append(phone)
                else:
                    failed_details.append(detail)
                    # Attempt fallback
                    if fallback_pool and fallback_attempts < MAX_FALLBACK_ATTEMPTS:
                        fallback = fallback_pool.pop(0) if fallback_pool else None
                        if fallback and fallback["phone_number"] not in used_phones:
                            fallback_pool.append(session)
                            fallback_pool.append(fallback)
                            fallback_attempts += 1
                            continue
            except Exception as exc:
                failed_details.append(f"❌ خطأ: {str(exc)[:80]}")
                continue

            if progress_callback:
                await progress_callback(i + 1, quantity, success_count, len(failed_details))

            if i < quantity - 1 and fallback_pool:
                delay = get_delay_seconds(is_owner, custom_delay)
                await asyncio.sleep(delay)

    else:
        # Standard execution for other legendary services
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
                    # Try to get a fallback account
                    if fallback_pool and fallback_attempts < MAX_FALLBACK_ATTEMPTS:
                        fallback = fallback_pool.pop(0) if fallback_pool else None
                        if fallback and fallback["phone_number"] not in used_phones:
                            fallback_pool.append(session)
                            fallback_pool.append(fallback)
                            fallback_attempts += 1
                            continue
            except Exception as exc:
                failed_details.append(f"❌ خطأ: {str(exc)[:80]}")
                continue

            if progress_callback:
                await progress_callback(i + 1, quantity, success_count, len(failed_details))

            if i < quantity - 1 and fallback_pool:
                delay = get_delay_seconds(is_owner, custom_delay)
                await asyncio.sleep(delay)

    return success_count, success_phones, failed_details


# ==================== UI HELPERS ====================

def legendary_services_back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع للخدمات الأسطورية", callback_data="legendary_services")]
    ])


# ==================== LEGENDARY SERVICES START ====================

async def legendary_service_start(update, context, q, is_own: bool, service_type: str):
    """Start the flow for any legendary service."""
    # Check if service is enabled
    if not is_own and not is_service_enabled(service_type):
        await q.answer("⚠️ هذه الخدمة غير متاحة حالياً.", show_alert=True)
        return

    available = get_available_sessions_count()

    if available == 0:
        await q.edit_message_text(
            "❌ لا توجد حسابات متاحة حالياً. حاول لاحقاً.",
            reply_markup=legendary_services_back_kb()
        )
        return

    context.user_data["legendary_service_type"] = service_type
    context.user_data["legendary_user_id"] = q.from_user.id
    context.user_data["legendary_step"] = "welcome"

    # Show welcome message with service info
    service_name = get_service_display_name(service_type)
    price_points = get_service_price_points(service_type, include_channel=False)
    price_stars = get_service_price_stars(service_type)
    channel_price = get_service_channel_price(service_type)
    channel_text = f" + {channel_price} نقطة للقناة" if channel_price > 0 else ""

    welcome = get_legendary_welcome()
    kb = [
        [InlineKeyboardButton("⭐ الدفع بالنجوم", callback_data=f"legendary:pay_stars:{service_type}")],
        [InlineKeyboardButton("💰 الدفع بالنقاط", callback_data=f"legendary:pay_points:{service_type}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="legendary_services")],
    ]

    # Add owner settings button
    if is_own:
        kb.insert(0, [InlineKeyboardButton("⚙️ إعدادات الخدمات الأسطورية", callback_data="legendary:settings")])

    await q.edit_message_text(
        f"{welcome}\n\n"
        f"📌 *الخدمة:* {service_name}\n"
        f"📝 {get_service_description(service_type)}\n\n"
        f"💰 *السعر:*\n"
        f"• {price_points} نقطة للوحدة{channel_text}\n"
        f"• {price_stars} نجمة للوحدة (القناة مجانية)\n\n"
        f"اختر طريقة الدفع:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb)
    )
    context.user_data["state"] = "legendary_payment_choice"


async def legendary_payment_choice(update, context, q, is_own: bool, service_type: str, method: str):
    """Handle payment method selection - then ask for channel and details."""
    context.user_data["legendary_payment_method"] = method
    context.user_data["legendary_step"] = "channel"

    await q.edit_message_text(
        "📢 *القنوات الإجبارية (اختياري)*\n\n"
        "أرسل رابط القناة أو معرفها (مثال: @channel أو t.me/channel)\n"
        "يمكنك التخطي إذا لا توجد قنوات إجبارية.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭ تخطي القناة", callback_data=f"legendary:skip_channel:{service_type}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="legendary_services")],
        ])
    )
    context.user_data["state"] = "legendary_channel_input"


async def legendary_skip_channel(update, context, q, service_type: str):
    """Skip channel step and go to main input."""
    context.user_data.pop("legendary_channel_ref", None)
    context.user_data["legendary_step"] = "main_input"

    prompts = {
        "comment": "📎 أرسل رابط المنشور المطلوب التعليق عليه:",
        "poll": "📎 أرسل رابط الاستفتاء المطلوب التصويت عليه:",
        "story": "📎 أرسل رابط الستوري المطلوب مشاهدته:",
        "votes": "📎 أرسل رابط الاستفتاء المطلوب التصويت عليه:",
        "votes_ai": "📎 أرسل رابط الاستفتاء المطلوب التصويت عليه (مع تحقق):",
        "premium_reaction": "📎 أرسل رابط المنشور المطلوب التفاعل عليه:",
        "forced_ref_ai": "📎 أرسل رابط البوت المطلوب الإحالة عليه:\n`t.me/BotUsername?start=CODE`\nأو: `@BotUsername CODE`",
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

    # --- Channel input ---
    if state == "legendary_channel_input":
        ref, display = _parse_channel_reference(text)

        if ref:
            context.user_data["legendary_channel_ref"] = ref
            channel_status = "حفظ"
        else:
            context.user_data.pop("legendary_channel_ref", None)
            channel_status = "تخطي"

        context.user_data["legendary_step"] = "main_input"
        context.user_data["state"] = "legendary_main_input"

        prompts = {
            "comment": "📎 أرسل رابط المنشور المطلوب التعليق عليه:",
            "poll": "📎 أرسل رابط الاستفتاء المطلوب التصويت عليه:",
            "story": "📎 أرسل رابط الستوري المطلوب مشاهدته:",
            "votes": "📎 أرسل رابط الاستفتاء المطلوب التصويت عليه:",
            "votes_ai": "📎 أرسل رابط الاستفتاء المطلوب التصويت عليه (مع تحقق):",
            "premium_reaction": "📎 أرسل رابط المنشور المطلوب التفاعل عليه:",
            "forced_ref_ai": "📎 أرسل رابط البوت المطلوب الإحالة عليه:\n`t.me/BotUsername?start=CODE`\nأو: `@BotUsername CODE`",
        }

        await update.message.reply_text(
            f"✅ تم {channel_status} القناة.\n\n{prompts.get(service_type, 'أرسل الرابط المطلوب:')}",
            reply_markup=legendary_services_back_kb()
        )
        return True

    # --- Main input ---
    if state == "legendary_main_input":
        if service_type == "forced_ref_ai":
            # Forced Ref AI receives a link directly
            context.user_data["legendary_forced_ref_link"] = text
            return await _legendary_ask_quantity(update, context)

        elif service_type in ["comment", "votes", "votes_ai", "premium_reaction"]:
            post_ref, post_id = _parse_post_link_parts(text)
            if post_ref is None or post_id is None:
                await update.message.reply_text(
                    "⚠️ أرسل رابط منشور تيليجرام صحيحاً، مثال:\nhttps://t.me/channel/123"
                )
                return True
            context.user_data["legendary_post_ref"] = post_ref
            context.user_data["legendary_post_id"] = post_id
            context.user_data["legendary_step"] = "extra_input"
            context.user_data["state"] = "legendary_extra_input"

            if service_type == "comment":
                await update.message.reply_text(
                    "✏️ أرسل نص التعليق الذي تريد نشره:"
                )
            elif service_type == "premium_reaction":
                await update.message.reply_text(
                    "😊 أرسل الإيموجي للتفاعل المميز (مثال: ❤️، 🔥، 🎉)\n"
                    "أو أرسل `عشوائي` لتوزيع تفاعلات عشوائية."
                )
            else:  # votes or votes_ai
                return await _legendary_ask_quantity(update, context)

            return True

        elif service_type == "poll":
            context.user_data["legendary_poll_link"] = text
            context.user_data["legendary_step"] = "poll_option"
            context.user_data["state"] = "legendary_poll_option_input"

            await update.message.reply_text(
                "🔢 أرسل رقم الخيار المطلوب للتصويت (مثال: 1، 2، 3):"
            )
            return True

        elif service_type == "story":
            context.user_data["legendary_story_link"] = text
            context.user_data["legendary_step"] = "story_emojis"
            context.user_data["state"] = "legendary_emojis_input"

            await update.message.reply_text(
                "😊 أرسل الإيموجيات المطلوبة للتفاعل (كل إيموجي في سطر):\nمثال:\n😁\n😝\n😂\nأو أرسل `عشوائي` لاختيار عشوائي."
            )
            return True

    # --- Poll option input ---
    if state == "legendary_poll_option_input":
        context.user_data["legendary_poll_option"] = text.strip()
        return await _legendary_ask_quantity(update, context)

    # --- Emojis input ---
    if state == "legendary_emojis_input":
        if text.strip().lower() in ("عشوائي", "random"):
            context.user_data["legendary_emojis"] = ["random"]
        else:
            emojis = [line.strip() for line in text.splitlines() if line.strip()]
            if not emojis:
                await update.message.reply_text("⚠️ أرسل إيموجي واحد على الأقل.")
                return True
            context.user_data["legendary_emojis"] = emojis
        return await _legendary_ask_quantity(update, context)

    # --- Extra input (comment text or reaction emoji) ---
    if state == "legendary_extra_input":
        if service_type == "comment":
            context.user_data["legendary_comment_text"] = text
        elif service_type == "premium_reaction":
            if text.strip().lower() in ("عشوائي", "random"):
                context.user_data["legendary_reaction_mode"] = "random"
            else:
                context.user_data["legendary_reaction_text"] = text.strip()
                context.user_data["legendary_reaction_mode"] = "fixed"
        return await _legendary_ask_quantity(update, context)

    # --- Quantity input ---
    if state == "legendary_quantity_input":
        qty_text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
        if not qty_text.isdigit():
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return True

        quantity = int(qty_text)
        available = get_available_sessions_count()

        if quantity < 1 or quantity > min(available, MAX_QUANTITY):
            await update.message.reply_text(
                f"⚠️ العدد المسموح بين 1 و {min(available, MAX_QUANTITY)} فقط."
            )
            return True
        
        # Check for even number in AI Forced Ref
        if service_type == "forced_ref_ai":
            if quantity % 2 != 0:
                await update.message.reply_text(
                    "⚠️ في وضع *إحالة بوت إجباري تحتوي تحقق* يُقبل فقط *أعداد زوجية* (٢، ٤، ٦...)\n"
                    "السبب: سعر الحساب ١.٥ نجمة ولا يمكن كسر النجمة في تيليغرام.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return True

        context.user_data["legendary_quantity"] = quantity
        context.user_data["state"] = "legendary_confirm"
        context.user_data["legendary_step"] = "confirm"

        # Build confirmation message
        service_name = get_service_display_name(service_type)
        payment_method = context.user_data.get("legendary_payment_method", "points")
        channel_ref = context.user_data.get("legendary_channel_ref")

        if payment_method == "stars":
            price_per = get_service_price_stars(service_type)
            total_cost = price_per * quantity
            currency = "نجمة"
        else:
            price_per = get_service_price_points(service_type, include_channel=False)
            total_cost = price_per * quantity
            if channel_ref:
                total_cost += get_service_channel_price(service_type)
            currency = "نقطة"

        channel_text = "✅ مع قناة" if channel_ref else "❌ بدون قناة"

        await update.message.reply_text(
            f"📋 *تأكيد الطلب*\n\n"
            f"📌 الخدمة: {service_name}\n"
            f"🔢 العدد: {quantity}\n"
            f"📺 القناة: {channel_text}\n"
            f"💰 التكلفة الإجمالية: {total_cost} {currency}\n\n"
            f"اضغط تأكيد لبدء التنفيذ:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأكيد", callback_data="legendary:confirm")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="legendary_services")],
            ])
        )
        return True

    # --- Owner delay input ---
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
        context.user_data["state"] = "legendary_quantity_input"
        context.user_data["legendary_step"] = "quantity"

        available = get_available_sessions_count()
        await update.message.reply_text(
            f"✅ تم ضبط الفاصل.\n\n🔢 أرسل عدد الوحدات المطلوبة (1-{min(available, MAX_QUANTITY)}):"
        )
        return True

    return False


async def _legendary_ask_quantity(update, context) -> bool:
    """Ask for quantity."""
    available = get_available_sessions_count()
    context.user_data["legendary_step"] = "quantity"
    context.user_data["state"] = "legendary_quantity_input"

    is_own = (update.effective_user.id == OWNER_ID)
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="legendary_services")]]

    if is_own:
        kb.insert(0, [InlineKeyboardButton("⏱️ تخصيص الفاصل (اختياري)", callback_data="legendary:set_delay")])

    await update.message.reply_text(
        f"🔢 أرسل عدد الوحدات المطلوبة (1-{min(available, MAX_QUANTITY)}):",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return True


# ==================== CONFIRM AND EXECUTE ====================

async def legendary_confirm(update, context, q, is_own: bool):
    """Confirm and execute the legendary order."""
    if context.user_data.get("state") != "legendary_confirm":
        await q.answer("⚠️ انتهت صلاحية الطلب، ابدأ من جديد.", show_alert=True)
        return

    service_type = context.user_data.get("legendary_service_type", "comment")
    quantity = context.user_data.get("legendary_quantity", 1)
    payment_method = context.user_data.get("legendary_payment_method", "points")
    channel_ref = context.user_data.get("legendary_channel_ref")
    custom_delay = context.user_data.get("legendary_custom_delay")
    requester_id = q.from_user.id

    # Calculate cost
    if payment_method == "stars":
        price_per = get_service_price_stars(service_type)
        total_cost = price_per * quantity
        currency = "نجمة"
    else:
        price_per = get_service_price_points(service_type, include_channel=False)
        total_cost = price_per * quantity
        if channel_ref:
            total_cost += get_service_channel_price(service_type)
        currency = "نقطة"

    # Check points balance
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

    # Execute
    if payment_method == "stars":
        await q.delete_message()
        await context.bot.send_invoice(
            chat_id=requester_id,
            title=f"{get_service_display_name(service_type)}",
            description=f"{quantity} وحدة | {total_cost} نجمة",
            payload=f"legendary_stars:{requester_id}:{service_type}:{quantity}:{total_cost}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice("خدمة أسطورية", total_cost)],
        )
        return

    # Payment by points - deduct and execute
    if not deduct_points(requester_id, total_cost):
        await q.edit_message_text("❌ لم يعد رصيدك كافياً.")
        context.user_data["state"] = "main_menu"
        return

    await _execute_legendary_order(update, context, q, is_own, payment_method, total_cost)


async def _execute_legendary_order(update, context, q, is_own: bool, payment_method: str, total_cost: int):
    """Execute the legendary order."""
    service_type = context.user_data.get("legendary_service_type", "comment")
    quantity = context.user_data.get("legendary_quantity", 1)
    channel_ref = context.user_data.get("legendary_channel_ref")
    custom_delay = context.user_data.get("legendary_custom_delay")
    requester_id = (
        context.user_data.get("legendary_user_id")
        or getattr(update.effective_user, "id", None)
        or OWNER_ID
    )

    sessions = _get_all_active_sessions()
    if not sessions:
        if payment_method == "points":
            add_points(requester_id, total_cost)
        await q.edit_message_text(
            "❌ لا توجد حسابات متاحة حالياً. تم تعويض نقاطك.",
            reply_markup=legendary_services_back_kb(),
        )
        context.user_data["state"] = "main_menu"
        return

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
        emojis = context.user_data.get("legendary_emojis", ["❤️"])
        if emojis == ["random"]:
            # Use random emojis from a default list
            default_emojis = ["❤️", "🔥", "🎉", "💯", "🤩", "😍", "👍", "👏"]
            params["emojis"] = [random.choice(default_emojis) for _ in range(quantity)]
        else:
            params["emojis"] = emojis
    elif service_type in ["votes", "votes_ai"]:
        params["post_ref"] = context.user_data.get("legendary_post_ref")
        params["post_id"] = context.user_data.get("legendary_post_id")
    elif service_type == "premium_reaction":
        params["post_ref"] = context.user_data.get("legendary_post_ref")
        params["post_id"] = context.user_data.get("legendary_post_id")
        mode = context.user_data.get("legendary_reaction_mode", "fixed")
        if mode == "random":
            default_emojis = ["❤️", "🔥", "🎉", "💯", "🤩", "😍", "👍", "👏"]
            params["reaction_text"] = random.choice(default_emojis)
        else:
            params["reaction_text"] = context.user_data.get("legendary_reaction_text", "❤️")

    # Special preparation for Forced Ref AI
    if service_type == "forced_ref_ai":
        params["bot_user"] = context.user_data.get("legendary_forced_ref_link")
        params["start_p"] = ""
        params["channels"] = channel_ref or ""
        params["leave_after"] = True
        # For forced ref, we need to parse the bot link correctly
        bot_link = params["bot_user"]
        if bot_link:
            try:
                if "t.me/" in bot_link or "telegram.me/" in bot_link:
                    from urllib.parse import urlparse, parse_qs
                    parsed = urlparse(bot_link if bot_link.startswith("http") else "https://" + bot_link)
                    bot_user = parsed.path.strip("/")
                    qs = parse_qs(parsed.query)
                    start_p = qs.get("start", [""])[0]
                else:
                    parts = bot_link.split(None, 1)
                    bot_user = parts[0].lstrip("@")
                    start_p = parts[1] if len(parts) > 1 else ""
                
                params["bot_user"] = bot_user
                params["start_p"] = start_p
            except Exception as _e:
                logger.warning(f"⚠️ Error parsing forced ref link: {_e}")

    progress_msg = await q.edit_message_text(
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
        price_per = get_service_price_points(service_type, include_channel=False)
        refund_points = failed_count * price_per
        if refund_points > 0:
            add_points(requester_id, refund_points)

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

    if failed_details:
        result += "\n❌ *التفاصيل:*\n" + "\n".join(f"• {d}" for d in failed_details[:3])
        if len(failed_details) > 3:
            result += f"\n... و{len(failed_details) - 3} أخرى"

    await q.edit_message_text(
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
    """Send group notification (only positive info)."""
    if not ADMIN_GROUP_ID:
        return

    try:
        text = (
            f"📢 *تم إنجاز طلب {get_service_display_name(service_type)}!*\n\n"
            f"👤 المستخدم: <code>{user_id}</code>\n"
            f"📊 المطلوب: {quantity}\n"
            f"✅ المنجز: {success_count}\n"
            f"💰 طريقة الدفع: {payment_method}\n"
        )
        if refund_points > 0:
            text += f"💰 تم تعويض: {refund_points} نقطة\n"
        await bot.send_message(ADMIN_GROUP_ID, text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass


# ==================== OWNER SETTINGS ====================

async def legendary_show_settings(update, context, q, is_own: bool):
    """Show legendary services settings for owner."""
    if not is_own:
        await q.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
        return

    services = [
        ("comment", "💬 تعليق"),
        ("poll", "📊 استفتاء"),
        ("story", "👁 ستوري"),
        ("votes", "🗳 أصوات"),
        ("votes_ai", "🤖 تصويت بتحقق"),
        ("premium_reaction", "✨ تفاعل مميز"),
        ("forced_ref_ai", "🔑 إحالة إجباري بتحقق"),
    ]

    rows = []
    for key, label in services:
        enabled = "✅" if is_service_enabled(key) else "❌"
        points = get_service_price_points(key, include_channel=False)
        stars = get_service_price_stars(key)
        channel = get_service_channel_price(key)
        rows.append([
            InlineKeyboardButton(
                f"{enabled} {label} | {points}ن | {stars}⭐ | +{channel}قناة",
                callback_data=f"legendary:edit_service:{key}"
            )
        ])

    rows.append([
        InlineKeyboardButton("✏️ تعديل رسالة الترحيب", callback_data="legendary:edit_welcome")
    ])
    rows.append([
        InlineKeyboardButton("🔙 رجوع", callback_data="legendary_services")
    ])

    current_welcome = get_legendary_welcome()
    await q.edit_message_text(
        f"⚙️ *إعدادات الخدمات الأسطورية*\n\n"
        f"📝 *رسالة الترحيب الحالية:*\n{current_welcome[:200]}{'...' if len(current_welcome) > 200 else ''}\n\n"
        f"اختر الخدمة لتعديل سعرها أو تفعيلها/تعطيلها:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows)
    )


async def legendary_edit_service(update, context, q, is_own: bool, service_type: str):
    """Edit a specific service settings."""
    if not is_own:
        await q.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
        return

    context.user_data["legendary_edit_service"] = service_type
    context.user_data["state"] = "legendary_edit_service"

    current_points = get_service_price_points(service_type, include_channel=False)
    current_stars = get_service_price_stars(service_type)
    channel_price = get_service_channel_price(service_type)
    enabled = is_service_enabled(service_type)

    await q.edit_message_text(
        f"✏️ *تعديل {get_service_display_name(service_type)}*\n\n"
        f"📊 الحالة: {'✅ مفعّلة' if enabled else '❌ معطّلة'}\n"
        f"💰 السعر بالنقاط: {current_points} نقطة/وحدة\n"
        f"⭐ السعر بالنجوم: {current_stars} نجمة/وحدة\n"
        f"📺 سعر القناة: {channel_price} نقطة\n\n"
        f"اختر ما تريد تعديله:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تبديل التفعيل", callback_data=f"legendary:toggle_service:{service_type}")],
            [InlineKeyboardButton("💰 تعديل سعر النقاط", callback_data=f"legendary:edit_price_points:{service_type}")],
            [InlineKeyboardButton("⭐ تعديل سعر النجوم", callback_data=f"legendary:edit_price_stars:{service_type}")],
            [InlineKeyboardButton("🔙 رجوع للإعدادات", callback_data="legendary:settings")],
        ])
    )


async def legendary_toggle_service(update, context, q, is_own: bool, service_type: str):
    """Toggle a service on/off."""
    if not is_own:
        await q.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
        return

    key = LEGENDARY_SETTINGS_KEYS.get(f"{service_type}_enabled")
    if key:
        current = get_setting(key) != "0"
        set_setting(key, "0" if current else "1")
        await q.answer(f"✅ تم {'تعطيل' if current else 'تفعيل'} الخدمة", show_alert=True)
        await legendary_edit_service(update, context, q, is_own, service_type)
    else:
        await q.answer("⚠️ لم يتم العثور على إعداد هذه الخدمة.", show_alert=True)


async def legendary_edit_price_points(update, context, q, is_own: bool, service_type: str):
    """Edit points price for a service."""
    if not is_own:
        await q.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
        return

    context.user_data["legendary_edit_service"] = service_type
    context.user_data["legendary_edit_type"] = "points"
    context.user_data["state"] = "legendary_edit_price_input"

    current = get_service_price_points(service_type, include_channel=False)
    await q.edit_message_text(
        f"💰 *تعديل سعر {get_service_display_name(service_type)} بالنقاط*\n\n"
        f"السعر الحالي: {current} نقطة/وحدة\n\n"
        f"أرسل السعر الجديد:",
        parse_mode=ParseMode.MARKDOWN
    )


async def legendary_edit_price_stars(update, context, q, is_own: bool, service_type: str):
    """Edit stars price for a service."""
    if not is_own:
        await q.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
        return

    context.user_data["legendary_edit_service"] = service_type
    context.user_data["legendary_edit_type"] = "stars"
    context.user_data["state"] = "legendary_edit_price_input"

    current = get_service_price_stars(service_type)
    await q.edit_message_text(
        f"⭐ *تعديل سعر {get_service_display_name(service_type)} بالنجوم*\n\n"
        f"السعر الحالي: {current} نجمة/وحدة\n\n"
        f"أرسل السعر الجديد:",
        parse_mode=ParseMode.MARKDOWN
    )


async def legendary_edit_welcome(update, context, q, is_own: bool):
    """Edit the welcome message."""
    if not is_own:
        await q.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
        return

    context.user_data["state"] = "legendary_edit_welcome_input"
    current = get_legendary_welcome()

    await q.edit_message_text(
        f"✏️ *تعديل رسالة الترحيب للخدمات الأسطورية*\n\n"
        f"الرسالة الحالية:\n{current}\n\n"
        f"أرسل الرسالة الجديدة:",
        parse_mode=ParseMode.MARKDOWN
    )


async def legendary_handle_edit_price(update, context, text: str) -> bool:
    """Handle price edit text input."""
    user = update.effective_user
    if user.id != OWNER_ID:
        return False

    if context.user_data.get("state") != "legendary_edit_price_input":
        return False

    service_type = context.user_data.get("legendary_edit_service")
    edit_type = context.user_data.get("legendary_edit_type")
    if not service_type or not edit_type:
        return False

    try:
        new_price = int(text.strip())
        if new_price < 1:
            await update.message.reply_text("⚠️ السعر يجب أن يكون أكبر من 0.")
            return True
    except ValueError:
        await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
        return True

    key = LEGENDARY_SETTINGS_KEYS.get(f"{service_type}_price_{edit_type}")
    if key:
        set_setting(key, str(new_price))

    context.user_data["state"] = "main_menu"
    context.user_data.pop("legendary_edit_service", None)
    context.user_data.pop("legendary_edit_type", None)

    await update.message.reply_text(
        f"✅ تم تحديث سعر {get_service_display_name(service_type)} "
        f"ب{'النقاط' if edit_type == 'points' else 'النجوم'} إلى {new_price}.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع للإعدادات", callback_data="legendary:settings")]
        ])
    )
    return True


async def legendary_handle_edit_welcome(update, context, text: str) -> bool:
    """Handle welcome message edit."""
    user = update.effective_user
    if user.id != OWNER_ID:
        return False

    if context.user_data.get("state") != "legendary_edit_welcome_input":
        return False

    if not text.strip():
        await update.message.reply_text("⚠️ الرسالة لا يمكن أن تكون فارغة.")
        return True

    set_legendary_welcome(text.strip())
    context.user_data["state"] = "main_menu"

    await update.message.reply_text(
        "✅ تم تحديث رسالة الترحيب.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع للإعدادات", callback_data="legendary:settings")]
        ])
    )
    return True
