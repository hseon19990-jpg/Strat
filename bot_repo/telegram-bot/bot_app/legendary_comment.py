"""Owner-only, single-account comment test for Legendary Services.

This flow is intentionally constrained:
* only the owner can open it;
* only one authorized account session is selected;
* only one comment can be sent per request;
* the optional channel link costs an additional 30 points;
* points are refunded when the Telegram operation fails.
"""

from . import shared as _shared

globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

from urllib.parse import urlparse


LEGENDARY_COMMENT_COST = 30
LEGENDARY_CHANNEL_COST = 30
LEGENDARY_COMMENT_MAX_QUANTITY = 1


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

    # A public channel link is the first path segment. Post IDs are ignored.
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


def _single_active_session() -> dict | None:
    """Load one existing, non-deleted session; never scans or creates sessions."""
    with db_conn() as c:
        row = c.execute(
            "SELECT id, phone_number, session_string "
            "FROM number_stock "
            "WHERE session_string IS NOT NULL AND BTRIM(session_string) <> '' "
            "AND deleted_at IS NULL AND last_authorized IS NOT FALSE "
            "AND forced_ref_excluded IS NOT TRUE "
            "ORDER BY id ASC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


async def _join_optional_channel(client, channel_ref: str) -> None:
    if channel_ref.startswith("invite:"):
        await client(functions.messages.ImportChatInviteRequest(channel_ref.split(":", 1)[1]))
        return
    entity = await client.get_entity(channel_ref)
    try:
        await client(functions.channels.JoinChannelRequest(entity))
    except Exception as exc:
        # Already-joined channels commonly raise a Telegram RPC error. Resolve
        # the entity again so the requested channel is still validated.
        if "USER_ALREADY_PARTICIPANT" not in str(exc).upper():
            raise
        await client.get_entity(channel_ref)


async def _join_discussion_group(client, discussion) -> None:
    """Join the linked discussion group before replying to a channel post."""
    messages = getattr(discussion, "messages", None) or []
    if not messages:
        raise RuntimeError("المنشور لا يملك نقاشاً متاحاً للتعليق.")

    discussion_message = messages[0]
    peer = getattr(discussion_message, "peer_id", None)
    channel_id = getattr(peer, "channel_id", None)
    chats = getattr(discussion, "chats", None) or []

    # GetDiscussionMessage returns the linked discussion chat in `chats`.
    # Match by the peer ID so we do not accidentally join the source channel.
    discussion_chat = next(
        (chat for chat in chats if getattr(chat, "id", None) == channel_id),
        None,
    )
    if discussion_chat is None:
        raise RuntimeError("تعذر تحديد مجموعة النقاش المرتبطة بالمنشور.")

    try:
        await client(functions.channels.JoinChannelRequest(discussion_chat))
    except Exception as exc:
        # Telegram raises this when the session is already a participant.
        if "USER_ALREADY_PARTICIPANT" not in str(exc).upper():
            raise


async def _send_single_comment(post_ref: str | int, post_id: int, comment_text: str) -> None:
    session = _single_active_session()
    if not session:
        raise RuntimeError("لا توجد جلسة نشطة متاحة في الحسابات المضافة.")
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise RuntimeError("بيانات Telegram API غير مهيأة.")

    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    await asyncio.wait_for(client.connect(), timeout=20)
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            raise RuntimeError("الجلسة المختارة لم تعد مصرحاً بها.")

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
    finally:
        await client.disconnect()


def legendary_comment_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 رجوع للخدمات الأسطورية", callback_data="legendary_services")]]
    )


async def legendary_comment_start(update, context, q, is_own: bool) -> None:
    if not is_own:
        await q.answer("⛔ هذه الخدمة متاحة للمالك فقط.", show_alert=True)
        return
    context.user_data["state"] = "legendary_comment_channel"
    for key in (
        "legendary_comment_channel",
        "legendary_comment_post",
        "legendary_comment_text",
        "legendary_comment_quantity",
    ):
        context.user_data.pop(key, None)
    await q.edit_message_text(
        "💬 *رشق تعليق — اختبار حساب واحد*\n\n"
        "سعر التعليق: *30 نقطة*.\n"
        "سيُنفّذ تعليق واحد فقط من جلسة نشطة واحدة.\n\n"
        "أرسل رابط القناة التي تريد للحساب الانضمام إليها، "
        "أو اضغط تخطي إذا لم توجد قناة:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⏭ تخطي القناة", callback_data="legendary_comment:skip_channel")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="legendary_services")],
            ]
        ),
    )


async def legendary_comment_skip_channel(update, context, q, is_own: bool) -> None:
    if not is_own:
        await q.answer("⛔ هذه الخدمة متاحة للمالك فقط.", show_alert=True)
        return
    context.user_data.pop("legendary_comment_channel", None)
    context.user_data["state"] = "legendary_comment_post"
    await q.edit_message_text(
        "تم تخطي القناة.\n\nأرسل رابط المنشور الذي سيُكتب تحته التعليق:",
        reply_markup=legendary_comment_start_keyboard(),
    )


async def _show_comment_text_prompt(update, context) -> None:
    context.user_data["state"] = "legendary_comment_text"
    await update.message.reply_text("أرسل نص التعليق المطلوب نشره:")


async def legendary_comment_handle_text(update, context, text: str) -> bool:
    """Handle owner-only text states. Return True when this flow consumed input."""
    if update.effective_user.id != OWNER_ID:
        return False
    state = context.user_data.get("state", "")
    if state not in {
        "legendary_comment_channel",
        "legendary_comment_post",
        "legendary_comment_text",
        "legendary_comment_quantity",
    }:
        return False

    if state == "legendary_comment_channel":
        ref, display = _parse_channel_reference(text)
        if not ref:
            await update.message.reply_text("⚠️ أرسل رابط قناة صحيحاً أو اضغط زر التخطي.")
            return True
        context.user_data["legendary_comment_channel"] = display
        context.user_data["legendary_comment_channel_ref"] = ref
        context.user_data["state"] = "legendary_comment_post"
        await update.message.reply_text(
            "✅ تم حفظ القناة (+30 نقطة).\n\nأرسل رابط المنشور المطلوب التعليق عليه:"
        )
        return True

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
        await _show_comment_text_prompt(update, context)
        return True

    if state == "legendary_comment_text":
        if not text or len(text) > 4096:
            await update.message.reply_text("⚠️ أرسل نصاً بين حرف واحد و4096 حرفاً.")
            return True
        context.user_data["legendary_comment_text"] = text
        context.user_data["state"] = "legendary_comment_quantity"
        await update.message.reply_text(
            "أرسل العدد المطلوب.\n\nللحماية، هذا الاختبار يقبل العدد *1 فقط*.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return True

    quantity_text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    if not quantity_text.isdigit() or int(quantity_text) != LEGENDARY_COMMENT_MAX_QUANTITY:
        await update.message.reply_text("⚠️ العدد المسموح في اختبار الحساب الواحد هو 1 فقط.")
        return True

    channel_cost = LEGENDARY_CHANNEL_COST if context.user_data.get("legendary_comment_channel_ref") else 0
    total_cost = LEGENDARY_COMMENT_COST + channel_cost
    db_user = get_user(OWNER_ID)
    if not db_user or int(db_user.get("points") or 0) < total_cost:
        await update.message.reply_text(
            f"❌ رصيدك غير كافٍ. التكلفة الإجمالية: {total_cost} نقطة."
        )
        context.user_data["state"] = "main_menu"
        return True

    context.user_data["legendary_comment_quantity"] = 1
    await update.message.reply_text(
        f"راجع الطلب:\n\n"
        f"💬 تعليق واحد: {LEGENDARY_COMMENT_COST} نقطة\n"
        f"📺 القناة: {'نعم (+30)' if channel_cost else 'لا'}\n"
        f"💰 الإجمالي: {total_cost} نقطة\n\n"
        "اضغط تأكيد للتنفيذ من جلسة نشطة واحدة.",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ تأكيد التنفيذ", callback_data="legendary_comment:confirm")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="main_menu")],
            ]
        ),
    )
    return True


_legendary_comment_lock = asyncio.Lock()


async def legendary_comment_confirm(update, context, q, is_own: bool) -> None:
    if not is_own:
        await q.answer("⛔ هذه الخدمة متاحة للمالك فقط.", show_alert=True)
        return
    if context.user_data.get("state") != "legendary_comment_quantity":
        await q.answer("⚠️ انتهت صلاحية الطلب، ابدأ من جديد.", show_alert=True)
        return

    channel_ref = context.user_data.get("legendary_comment_channel_ref")
    post_ref = context.user_data.get("legendary_comment_post_ref")
    post_id = context.user_data.get("legendary_comment_post_id")
    comment_text = context.user_data.get("legendary_comment_text")
    total_cost = LEGENDARY_COMMENT_COST + (LEGENDARY_CHANNEL_COST if channel_ref else 0)
    if not post_ref or not post_id or not comment_text:
        await q.edit_message_text("⚠️ بيانات الطلب غير مكتملة.", reply_markup=legendary_comment_start_keyboard())
        context.user_data["state"] = "main_menu"
        return

    async with _legendary_comment_lock:
        if not deduct_points(OWNER_ID, total_cost):
            await q.edit_message_text("❌ لم يعد رصيدك كافياً لتنفيذ الطلب.")
            context.user_data["state"] = "main_menu"
            return
        try:
            session = _single_active_session()
            if not session:
                raise RuntimeError("لا توجد جلسة نشطة متاحة.")
            if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
                raise RuntimeError("بيانات Telegram API غير مهيأة.")

            client = TelegramClient(
                StringSession(session["session_string"]),
                int(TELEGRAM_API_ID),
                TELEGRAM_API_HASH,
            )
            await asyncio.wait_for(client.connect(), timeout=20)
            try:
                if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                    raise RuntimeError("الجلسة المختارة غير مصرح بها.")
                if channel_ref:
                    await _join_optional_channel(client, channel_ref)
                post_entity = await client.get_entity(post_ref)
                discussion = await client(
                    functions.messages.GetDiscussionMessageRequest(
                        peer=post_entity,
                        msg_id=int(post_id),
                    )
                )
                if not getattr(discussion, "messages", None):
                    raise RuntimeError("المنشور لا يملك نقاشاً متاحاً للتعليق.")
                discussion_message = discussion.messages[0]
                discussion_peer = getattr(discussion_message, "peer_id", None)
                if discussion_peer is None:
                    raise RuntimeError("تعذر تحديد مساحة التعليقات.")
                await _join_discussion_group(client, discussion)
                await client.send_message(
                    discussion_peer,
                    comment_text,
                    reply_to=discussion_message.id,
                )
            finally:
                await client.disconnect()
        except Exception as exc:
            add_points(OWNER_ID, total_cost)
            logger.warning("Legendary single-comment test failed: %s", exc)
            await q.edit_message_text(
                f"❌ فشل الاختبار وتمت إعادة {total_cost} نقطة.\n\nالسبب: {str(exc)[:240]}",
                reply_markup=legendary_comment_start_keyboard(),
            )
            context.user_data["state"] = "main_menu"
            return

    await q.edit_message_text(
        "✅ تم نشر تعليق واحد بنجاح من جلسة نشطة واحدة.\n"
        f"💰 تم خصم {total_cost} نقطة.",
        reply_markup=main_menu_kb(True),
    )
    context.user_data["state"] = "main_menu"