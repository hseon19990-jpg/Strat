"""Owner-only, multi-account comment service for Legendary Services.

This flow is designed for the owner:
* Only the owner can open it.
* Uses ALL available active sessions for batch commenting.
* Optional channel link costs 30 points.
* The bot stays in the channel for 24 hours then leaves automatically.
* Points are refunded pro-rata for failed comments.
* Maximum comments = number of available sessions.
"""

from . import shared as _shared

globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

from urllib.parse import urlparse
import asyncio
import time


LEGENDARY_COMMENT_COST = 30
LEGENDARY_CHANNEL_COST = 30
LEGENDARY_STAY_HOURS = 24  # Stay in channel for 24 hours before leaving


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
        return None, None
    path = parsed.path.strip("/")
    if not path:
        return None, None

    if path.startswith(("joinchat/", "+")):
        token = path.removeprefix("joinchat/").removeprefix("+")
        return f"invite:{token}", value

    username = path.split("/", 1)[0]
    if username and username not in {"c", "joinchat"}:
        return f"@{username.lstrip('@')}", value
    return None, None


def _parse_post_link_parts(value: str) -> tuple[str | int | None, int | None]:
    value = _clean_link(value)
    parsed = urlparse(value if "://" in value else f"https://{value}")
    if parsed.netloc.lower() not in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}:
        return None, None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
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
    """Load ALL active sessions from the stock."""
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


def get_available_comments_count() -> int:
    """Return the number of available sessions (maximum comments)."""
    return len(_get_all_active_sessions())


async def _join_optional_channel(client, channel_ref: str) -> None:
    """Join a channel using either username or invite link."""
    if channel_ref.startswith("invite:"):
        await client(functions.messages.ImportChatInviteRequest(channel_ref.split(":", 1)[1]))
        return
    entity = await client.get_entity(channel_ref)
    try:
        await client(functions.channels.JoinChannelRequest(entity))
    except Exception as exc:
        if "USER_ALREADY_PARTICIPANT" not in str(exc).upper():
            raise
        await client.get_entity(channel_ref)


async def _leave_channel_after_delay(client, channel_ref: str, delay_hours: int = 24):
    """Leave the channel after a specified delay (default: 24 hours)."""
    await asyncio.sleep(delay_hours * 3600)
    try:
        entity = await client.get_entity(channel_ref)
        await client(functions.channels.LeaveChannelRequest(entity))
        logger.info(f"✅ Left channel {channel_ref} after {delay_hours} hours.")
    except Exception as exc:
        logger.warning(f"⚠️ Failed to leave channel {channel_ref}: {exc}")


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


async def _send_comment_with_session(
    session_string: str,
    phone: str,
    post_ref: str | int,
    post_id: int,
    comment_text: str,
    channel_ref: str | None = None,
) -> tuple[bool, str]:
    """Send a comment using a specific session."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise RuntimeError("بيانات Telegram API غير مهيأة.")

    client = TelegramClient(
        StringSession(session_string),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            raise RuntimeError("الجلسة لم تعد مصرحاً بها.")

        # Join channel if provided (only for the first session that needs it)
        if channel_ref:
            await _join_optional_channel(client, channel_ref)
            # Schedule leaving after 24 hours
            asyncio.create_task(_leave_channel_after_delay(client, channel_ref, LEGENDARY_STAY_HOURS))

        post_entity = await client.get_entity(post_ref)
        discussion = await client(
            functions.messages.GetDiscussionMessageRequest(
                peer=post_entity,
                msg_id=post_id,
            )
        )
        if not getattr(discussion, "messages", None):
            raise RuntimeError("المنشور لا يملك نقاشاً متاحاً للتعليق.")

        discussion_message = discussion.messages[0]
        discussion_peer = getattr(discussion_message, "peer_id", None)
        if discussion_peer is None:
            raise RuntimeError("تعذر تحديد مساحة التعليقات للمنشور.")
        await _join_discussion_group(client, discussion)

        await client.send_message(
            discussion_peer,
            comment_text,
            reply_to=discussion_message.id,
        )
        return True, f"✅ تم التعليق بنجاح من الرقم {phone}"
    except Exception as exc:
        return False, f"❌ فشل التعليق من الرقم {phone}: {str(exc)[:100]}"
    finally:
        await client.disconnect()


async def _send_batch_comments(
    sessions: list[dict],
    post_ref: str | int,
    post_id: int,
    comment_text: str,
    channel_ref: str | None = None,
) -> tuple[int, list[str]]:
    """Send comments using ALL available sessions."""
    if not sessions:
        raise RuntimeError("لا توجد جلسات نشطة متاحة.")

    success_count = 0
    failed_details = []

    # Only the first session joins the channel (if provided)
    # Other sessions just comment without joining (they may already be members)
    for i, session in enumerate(sessions):
        try:
            ch_ref = channel_ref if i == 0 else None
            ok, msg = await _send_comment_with_session(
                session["session_string"],
                session["phone_number"],
                post_ref,
                post_id,
                comment_text,
                ch_ref,
            )
            if ok:
                success_count += 1
            else:
                failed_details.append(msg)
        except Exception as exc:
            failed_details.append(f"❌ خطأ في الجلسة {i+1}: {str(exc)[:80]}")
            continue

    return success_count, failed_details


def legendary_comment_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 رجوع للخدمات الأسطورية", callback_data="legendary_services")]]
    )


async def legendary_comment_start(update, context, q, is_own: bool) -> None:
    """Start the legendary comment flow - show pricing and ask for channel link."""
    if not is_own:
        await q.answer("⛔ هذه الخدمة متاحة للمالك فقط.", show_alert=True)
        return

    # Get available sessions count
    available = get_available_comments_count()

    # Clear any previous data
    context.user_data["state"] = "legendary_comment_channel"
    for key in (
        "legendary_comment_channel",
        "legendary_comment_channel_ref",
        "legendary_comment_post",
        "legendary_comment_post_ref",
        "legendary_comment_post_id",
        "legendary_comment_text",
    ):
        context.user_data.pop(key, None)

    await q.edit_message_text(
        "💬 *رشق تعليق — خدمة أسطورية*\n\n"
        f"💰 *سعر التعليق الواحد:* {LEGENDARY_COMMENT_COST} نقطة\n"
        f"💰 *سعر القناة الإضافية:* {LEGENDARY_CHANNEL_COST} نقطة (إذا أضفت قناة)\n"
        f"📊 *الحسابات المتاحة للتعليق:* {available} حساب\n"
        f"📊 *الحد الأقصى للتعليقات:* {available} تعليق (حساب واحد لكل تعليق)\n\n"
        "📝 *الخطوات:*\n"
        "1️⃣ أرسل رابط القناة (اختياري، مع زر تخطي)\n"
        "2️⃣ أرسل رابط المنشور المطلوب التعليق عليه\n"
        "3️⃣ أرسل نص التعليق\n\n"
        "🔹 *ملاحظة:* سيظل البوت مشتركاً في القناة لمدة 24 ساعة ثم يغادر تلقائياً.\n"
        "🔹 *ملاحظة:* عدد التعليقات = عدد الحسابات المتاحة (جميع الحسابات ستعلق).\n\n"
        "📎 *الخطوة الأولى:* أرسل رابط القناة (أو اضغط تخطي):",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⏭ تخطي القناة (+0 نقطة)", callback_data="legendary_comment:skip_channel")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="legendary_services")],
            ]
        ),
    )


async def legendary_comment_skip_channel(update, context, q, is_own: bool) -> None:
    """Skip the channel step and proceed to post link."""
    if not is_own:
        await q.answer("⛔ هذه الخدمة متاحة للمالك فقط.", show_alert=True)
        return

    context.user_data.pop("legendary_comment_channel", None)
    context.user_data.pop("legendary_comment_channel_ref", None)
    context.user_data["state"] = "legendary_comment_post"

    await q.edit_message_text(
        "⏭ تم تخطي القناة.\n\n"
        "📎 *الخطوة الثانية:* أرسل رابط المنشور المطلوب التعليق عليه:",
        reply_markup=legendary_comment_start_keyboard(),
    )


async def legendary_comment_handle_text(update, context, text: str) -> bool:
    """Handle owner-only text states for the legendary comment flow."""
    if update.effective_user.id != OWNER_ID:
        return False

    state = context.user_data.get("state", "")
    
    # --- Step 1: Channel Link ---
    if state == "legendary_comment_channel":
        ref, display = _parse_channel_reference(text)
        if not ref:
            await update.message.reply_text("⚠️ أرسل رابط قناة صحيحاً أو اضغط زر التخطي.")
            return True

        context.user_data["legendary_comment_channel"] = display
        context.user_data["legendary_comment_channel_ref"] = ref
        context.user_data["state"] = "legendary_comment_post"

        await update.message.reply_text(
            f"✅ تم حفظ القناة (+{LEGENDARY_CHANNEL_COST} نقطة).\n\n"
            "📎 *الخطوة الثانية:* أرسل رابط المنشور المطلوب التعليق عليه:"
        )
        return True

    # --- Step 2: Post Link ---
    if state == "legendary_comment_post":
        post_ref, post_id = _parse_post_link_parts(text)
        if post_ref is None or post_id is None:
            await update.message.reply_text(
                "⚠️ أرسل رابط منشور تيليجرام صحيحاً، مثال:\nhttps://t.me/channel/123"
            )
            return True

        context.user_data["legendary_comment_post"] = text
        context.user_data["legendary_comment_post_ref"] = post_ref
        context.user_data["legendary_comment_post_id"] = post_id
        context.user_data["state"] = "legendary_comment_text"

        available = get_available_comments_count()
        await update.message.reply_text(
            f"💬 *الخطوة الثالثة:* أرسل نص التعليق المطلوب نشره.\n\n"
            f"📊 سيتم نشر التعليق على جميع الحسابات المتاحة ({available} تعليق).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return True

    # --- Step 3: Comment Text (and show confirmation) ---
    if state == "legendary_comment_text":
        if not text or len(text) > 4096:
            await update.message.reply_text("⚠️ أرسل نصاً بين حرف واحد و4096 حرفاً.")
            return True

        context.user_data["legendary_comment_text"] = text

        # Get available sessions count
        available = get_available_comments_count()
        channel_cost = LEGENDARY_CHANNEL_COST if context.user_data.get("legendary_comment_channel_ref") else 0
        total_cost = (LEGENDARY_COMMENT_COST * available) + channel_cost
        channel_display = "نعم (+30)" if channel_cost else "لا"

        # IMPORTANT: Set state to confirm so the callback works
        context.user_data["state"] = "legendary_comment_confirm"

        await update.message.reply_text(
            f"📋 *مراجعة الطلب:*\n\n"
            f"📺 القناة: {channel_display}\n"
            f"🔢 عدد التعليقات: {available} (جميع الحسابات المتاحة)\n"
            f"💬 السعر/تعليق: {LEGENDARY_COMMENT_COST} نقطة\n"
            f"💰 إجمالي التعليقات: {LEGENDARY_COMMENT_COST * available} نقطة\n"
            f"💰 رسوم القناة: {channel_cost} نقطة\n"
            f"💎 *الإجمالي الكلي:* {total_cost} نقطة\n\n"
            f"🕒 سيغادر البوت القناة تلقائياً بعد {LEGENDARY_STAY_HOURS} ساعة.\n\n"
            f"📝 *نص التعليق:*\n`{text[:200]}{'...' if len(text) > 200 else ''}`\n\n"
            "اضغط تأكيد للتنفيذ:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✅ تأكيد التنفيذ", callback_data="legendary_comment:confirm")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data="main_menu")],
                ]
            ),
        )
        return True

    return False


_legendary_comment_lock = asyncio.Lock()


async def legendary_comment_confirm(update, context, q, is_own: bool) -> None:
    """Confirm and execute the legendary comment batch using all available sessions."""
    if not is_own:
        await q.answer("⛔ هذه الخدمة متاحة للمالك فقط.", show_alert=True)
        return

    # Check state - allow both states for flexibility
    current_state = context.user_data.get("state", "")
    if current_state not in ("legendary_comment_confirm", "legendary_comment_quantity"):
        await q.answer("⚠️ انتهت صلاحية الطلب، ابدأ من جديد.", show_alert=True)
        return

    # Get all required data
    channel_ref = context.user_data.get("legendary_comment_channel_ref")
    post_ref = context.user_data.get("legendary_comment_post_ref")
    post_id = context.user_data.get("legendary_comment_post_id")
    comment_text = context.user_data.get("legendary_comment_text")

    if not post_ref or not post_id or not comment_text:
        await q.edit_message_text(
            "⚠️ بيانات الطلب غير مكتملة.",
            reply_markup=legendary_comment_start_keyboard()
        )
        context.user_data["state"] = "main_menu"
        return

    # Get available sessions
    sessions = _get_all_active_sessions()
    available = len(sessions)

    if available == 0:
        await q.edit_message_text(
            "❌ لا توجد حسابات متاحة للتعليق. تأكد من وجود جلسات نشطة.",
            reply_markup=legendary_comment_start_keyboard()
        )
        context.user_data["state"] = "main_menu"
        return

    # Calculate costs
    channel_cost = LEGENDARY_CHANNEL_COST if channel_ref else 0
    total_cost = (LEGENDARY_COMMENT_COST * available) + channel_cost

    # Check balance
    db_user = get_user(OWNER_ID)
    if not db_user or int(db_user.get("points") or 0) < total_cost:
        await q.edit_message_text(
            f"❌ رصيدك غير كافٍ. التكلفة الإجمالية: {total_cost} نقطة.\n"
            f"💰 رصيدك الحالي: {db_user['points'] if db_user else 0} نقطة",
            reply_markup=legendary_comment_start_keyboard(),
        )
        context.user_data["state"] = "main_menu"
        return

    async with _legendary_comment_lock:
        # Deduct points
        if not deduct_points(OWNER_ID, total_cost):
            await q.edit_message_text("❌ لم يعد رصيدك كافياً لتنفيذ الطلب.")
            context.user_data["state"] = "main_menu"
            return

        try:
            # If channel is provided, join it using the first session
            if channel_ref:
                first_session = sessions[0]
                client = TelegramClient(
                    StringSession(first_session["session_string"]),
                    int(TELEGRAM_API_ID),
                    TELEGRAM_API_HASH,
                )
                await asyncio.wait_for(client.connect(), timeout=20)
                try:
                    if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                        raise RuntimeError("الجلسة الأولى غير مصرح بها.")

                    await _join_optional_channel(client, channel_ref)
                    # Schedule leaving after 24 hours
                    asyncio.create_task(_leave_channel_after_delay(client, channel_ref, LEGENDARY_STAY_HOURS))
                finally:
                    await client.disconnect()

            # Send comments using ALL available sessions
            success_count, failed_details = await _send_batch_comments(
                sessions,
                post_ref,
                post_id,
                comment_text,
                channel_ref=channel_ref,
            )

            # Handle results
            if success_count == 0:
                # Refund all points if no comments were sent
                add_points(OWNER_ID, total_cost)
                raise RuntimeError("فشل إرسال جميع التعليقات.")

            # Refund points for failed comments (pro-rata)
            failed_count = available - success_count
            if failed_count > 0:
                refund_amount = failed_count * LEGENDARY_COMMENT_COST
                add_points(OWNER_ID, refund_amount)

            # Build result message
            result_msg = f"✅ *تم نشر {success_count} من أصل {available} تعليق بنجاح!*\n\n"
            result_msg += f"💰 تم خصم {(LEGENDARY_COMMENT_COST * success_count) + channel_cost} نقطة.\n"

            if failed_count > 0:
                result_msg += f"💰 تم إعادة {failed_count * LEGENDARY_COMMENT_COST} نقطة للتعليقات الفاشلة.\n\n"

            if failed_details:
                result_msg += "❌ *التفاصيل الفاشلة:*\n" + "\n".join(f"• {d}" for d in failed_details[:5])
                if len(failed_details) > 5:
                    result_msg += f"\n... و{len(failed_details) - 5} محاولات أخرى."

            await q.edit_message_text(
                result_msg,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(True),
            )

        except Exception as exc:
            add_points(OWNER_ID, total_cost)
            logger.warning("Legendary comment batch failed: %s", exc)
            await q.edit_message_text(
                f"❌ فشل الاختبار وتمت إعادة {total_cost} نقطة.\n\nالسبب: {str(exc)[:240]}",
                reply_markup=legendary_comment_start_keyboard(),
            )

    context.user_data["state"] = "main_menu"
