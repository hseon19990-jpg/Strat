"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.pre_checkout_query
    payload = query.invoice_payload

    try:
        valid = False
        if payload.startswith("charge_stars:"):
            parts = payload.split(":")
            if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                expected_stars = int(parts[1])
                uid_in_payload = int(parts[2])
                actual_stars   = query.total_amount
                if query.from_user.id == uid_in_payload and actual_stars == expected_stars:
                    valid = True

        if payload.startswith("number_stars:"):
            parts = payload.split(":")
            if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                uid_in_payload = int(parts[1])
                expected_stars = int(parts[2])
                if query.from_user.id == uid_in_payload and query.total_amount == expected_stars:
                    valid = True

        # ─── الاشتراك الإجباري بالنجوم ───
        if payload.startswith("fund_mandatory:"):
            parts = payload.split(":")
            if len(parts) == 5 and parts[1].isdigit() and parts[4].isdigit():
                uid_in_payload = int(parts[1])
                expected_stars = int(parts[4])
                if query.from_user.id == uid_in_payload and query.total_amount == expected_stars:
                    valid = True

        # ─── إحالة بوت إجبارية بالنجوم ───
        if payload.startswith("forced_ref_stars:"):
            parts = payload.split(":")
            if len(parts) >= 5 and parts[1].isdigit() and parts[3].isdigit():
                uid_in_payload = int(parts[1])
                expected_stars = int(parts[3])
                if query.from_user.id == uid_in_payload and query.total_amount == expected_stars:
                    valid = True

        # الخدمات الأسطورية بالنجوم
        if payload.startswith("legendary_stars:"):
            parts = payload.split(":")
            if (
                len(parts) == 5
                and parts[1].isdigit()
                and parts[3].isdigit()
                and parts[4].isdigit()
            ):
                uid_in_payload = int(parts[1])
                expected_stars = int(parts[4])
                if query.from_user.id == uid_in_payload and query.total_amount == expected_stars:
                    valid = True

        if valid:
            await query.answer(ok=True)
        else:
            await query.answer(ok=False, error_message="حدث خطأ في التحقق من الدفع.")
    except Exception as _pce:
        logger.error(f"❌ خطأ في pre_checkout: {_pce}")
        try:
            await query.answer(ok=False, error_message="خطأ داخلي، حاول مجدداً.")
        except Exception:
            pass

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    user    = update.effective_user
    is_own  = (user.id == OWNER_ID)

    if payload.startswith("charge_stars:"):
        parts = payload.split(":")
        stars = int(parts[1])
        rate  = int(get_setting("star_to_points") or "250")
        pts   = stars * rate
        add_points(user.id, pts)
        with db_conn() as c:
            c.execute(
                "INSERT INTO star_transactions (user_id,stars,points_given,telegram_payment_id) VALUES (?,?,?,?)",
                (user.id, stars, pts, payment.telegram_payment_charge_id)
            )
        db_user = get_user(user.id)
        await update.message.reply_text(
            f"✅ *تم الشحن بنجاح!*\n\n"
            f"⭐ النجوم: {stars}\n"
            f"✨ النقاط المضافة: {pts}\n"
            f"💰 رصيدك الآن: {db_user['points']} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )

    # ─── الخدمات الأسطورية بالنجوم ───
    elif payload.startswith("legendary_stars:"):
        from .legendary_comment import execute_legendary_order, get_service_display_name

        parts = payload.split(":")
        if (
            len(parts) != 5
            or not parts[1].isdigit()
            or not parts[3].isdigit()
            or not parts[4].isdigit()
        ):
            await update.message.reply_text(
                "⚠️ بيانات دفع الخدمة الأسطورية غير صالحة.",
                reply_markup=main_menu_kb(is_own),
            )
            return

        payload_user_id = int(parts[1])
        service_type = parts[2]
        quantity = int(parts[3])
        expected_stars = int(parts[4])
        allowed_services = {
            "comment", "poll", "story", "votes", "votes_ai", "premium_reaction"
        }
        if (
            payload_user_id != user.id
            or service_type not in allowed_services
            or quantity < 1
            or expected_stars < 1
            or payment.total_amount != expected_stars
        ):
            logger.error(
                "❌ بيانات دفع الخدمة الأسطورية غير متطابقة: "
                f"user={user.id}, payload_user={payload_user_id}, "
                f"service={service_type}, paid={payment.total_amount}, expected={expected_stars}"
            )
            await update.message.reply_text(
                "⚠️ تعذّر التحقق من عملية الدفع.",
                reply_markup=main_menu_kb(is_own),
            )
            return

        # يمنع تنفيذ الطلب مرة أخرى إذا أعاد تيليغرام إشعار الدفع.
        if context.user_data.get("legendary_payment_charge_id") == payment.telegram_payment_charge_id:
            return
        context.user_data["legendary_payment_charge_id"] = payment.telegram_payment_charge_id

        if (
            context.user_data.get("legendary_service_type") != service_type
            or context.user_data.get("legendary_quantity") != quantity
        ):
            await update.message.reply_text(
                "⚠️ انتهت جلسة الطلب قبل تأكيد الدفع. تواصل مع المالك لمراجعة العملية.",
                reply_markup=main_menu_kb(is_own),
            )
            return

        context.user_data["legendary_stars_cost"] = expected_stars

        # Create progress message
        progress_message = await update.message.reply_text(
            f"⏳ تم تأكيد الدفع بالنجوم، جاري بدء تنفيذ خدمة {get_service_display_name(service_type)}..."
        )

        # We need to create a dummy callback query object for execute_legendary_order
        class DummyQ:
            def __init__(self, msg):
                self.message = msg
                self.from_user = update.effective_user
            async def edit_message_text(self, text, **kwargs):
                return await progress_message.edit_text(text, **kwargs)
            async def delete_message(self):
                return await progress_message.delete()

        dummy_q = DummyQ(progress_message)

        await execute_legendary_order(
            update,
            context,
            dummy_q,
            is_own,
            "stars",
        )

    # ─── إحالة بوت إجبارية بالنجوم ───
    elif payload.startswith("forced_ref_stars:"):
        parts           = payload.split(":")
        _uid            = int(parts[1])
        qty             = int(parts[2])
        total_stars     = int(parts[3])
        use_ai          = parts[4] == '1'
        cost_pts_ch     = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 0
        avail = get_forced_ref_account_count()
        if qty < 1 or qty > avail:
            await update.message.reply_text(
                f'⚠️ تعذّر تنفيذ الطلب: الحسابات المتاحة الآن {avail}.',
                reply_markup=main_menu_kb(is_own)
            )
            return
        # استرجاع بيانات البوت من السياق
        _draft = context.user_data.get('forced_ref_draft', {})
        bot_user = _draft.get('bot_user', '')
        start_p  = _draft.get('start_p', '')
        channels = _draft.get('channels', '')
        delay_seconds = _draft.get('delay_seconds') if user.id == OWNER_ID else None
        if not bot_user:
            await update.message.reply_text(
                '⚠️ تعذّر استرجاع بيانات الطلب. ابدأ من جديد.',
                reply_markup=main_menu_kb(is_own)
            )
            return
        code = next_order_code(user.id)
        with db_conn() as c:
            row = c.execute(
                'INSERT INTO forced_ref_orders '
                '(user_id,bot_username,start_param,channels,quantity,cost_points,cost_stars,payment_method,status,order_code) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
                (user.id, bot_user, start_p, channels, qty, cost_pts_ch, total_stars, 'stars', 'pending', code)
            ).fetchone()
            order_id = row['id']
        context.user_data.pop('forced_ref_draft', None)
        _code_fr = f'`{start_p}`' if start_p else 'بدون كود'
        ch_line  = f'\n📢 القنوات: `{channels}`' if channels else ''
        ch_pts_line = f'\n💎 نقاط القنوات المخصومة: {cost_pts_ch:,}' if cost_pts_ch > 0 else ''
        await update.message.reply_text(
            f'✅ *تم استلام طلبك!*\n\n'
            f'📌 `@{bot_user}` | كود: {_code_fr}{ch_line}\n'
            f'🔢 {qty} حساب | ⭐ {total_stars:,} نجمة{ch_pts_line}\n'
            f'🎫 كود: `{code}`\n\n'
            f'⏳ سيبدأ التنفيذ قريباً وستصلك إشعار عند الانتهاء.',
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )
        await _maybe_send_to_group(
            context.application.bot, user.id,
            f'تم إحالة بوت إجباري العدد {qty}',
            parse_mode='Markdown'
        )
        import asyncio as _aio_fr
        _aio_fr.create_task(_run_forced_ref_order(
            order_id, bot_user, start_p, channels, qty, user.id, context,
            use_ai=use_ai, payment_method='stars', cost_stars=total_stars,
            delay_seconds=delay_seconds
        ))

    # ─── شراء رقم تيلغرام بالنجوم ───
    elif payload.startswith("number_stars:"):
        parts = payload.split(":")
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            await update.message.reply_text("⚠️ بيانات الدفع غير صالحة.", reply_markup=main_menu_kb(is_own))
            return

        payload_user_id = int(parts[1])
        stars = int(parts[2])
        charge_id = payment.telegram_payment_charge_id
        if payload_user_id != user.id or payment.total_amount != stars:
            logger.error(
                f"❌ بيانات شراء رقم بالنجوم غير متطابقة: user={user.id}, "
                f"payload_user={payload_user_id}, paid={payment.total_amount}, expected={stars}"
            )
            await update.message.reply_text("⚠️ تعذّر التحقق من عملية الدفع.", reply_markup=main_menu_kb(is_own))
            return

        # يمنع تسليم رقمين إذا أعاد تيليغرام إرسال إشعار الدفع.
        with db_conn() as c:
            c.execute(
                "INSERT INTO number_star_purchases "
                "(telegram_payment_id,user_id,stars,status) VALUES (%s,%s,%s,'pending') "
                "ON CONFLICT (telegram_payment_id) DO NOTHING",
                (charge_id, user.id, stars)
            )
            claim = c.execute(
                "UPDATE number_star_purchases SET status='processing' "
                "WHERE telegram_payment_id=%s AND status='pending' RETURNING telegram_payment_id",
                (charge_id,)
            ).fetchone()
            existing = c.execute(
                "SELECT status, phone_number FROM number_star_purchases WHERE telegram_payment_id=%s",
                (charge_id,)
            ).fetchone()
        if not claim:
            if existing and existing["status"] == "completed":
                await update.message.reply_text(
                    f"✅ تم تسجيل عملية شراء هذا الرقم مسبقاً: `{existing['phone_number']}`",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=main_menu_kb(is_own)
                )
            elif existing and existing["status"] == "refunded":
                await update.message.reply_text(
                    "ℹ️ تمت إعادة قيمة هذه العملية لأن المخزون لم يكن متاحاً.",
                    reply_markup=main_menu_kb(is_own)
                )
            else:
                await update.message.reply_text("⏳ تتم معالجة عملية الدفع حالياً، يرجى الانتظار.")
            return

        auto = await assign_verified_number(user.id, bot=context.bot)
        if not auto:
            refunded = False
            try:
                await context.bot.refund_star_payment(
                    user_id=user.id,
                    telegram_payment_charge_id=charge_id
                )
                refunded = True
            except Exception as refund_err:
                logger.error(f"❌ تعذّر إعادة نجوم شراء الرقم {charge_id}: {refund_err}")
            with db_conn() as c:
                c.execute(
                    "UPDATE number_star_purchases SET status=%s WHERE telegram_payment_id=%s",
                    ("refunded" if refunded else "refund_failed", charge_id)
                )
            await update.message.reply_text(
                "😔 لا يتوفر حالياً رقم صالح في المخزون.\n"
                + ("✅ تمت إعادة النجوم إلى حسابك." if refunded
                   else "⚠️ تعذّرت الإعادة التلقائية، يرجى التواصل مع المالك فوراً."),
                reply_markup=main_menu_kb(is_own)
            )
            return

        auto_number = auto["phone_number"]
        code = next_order_code(user.id)
        with db_conn() as c:
            pe = c.execute(
                "INSERT INTO prize_exchanges "
                "(user_id,prize_type,prize_value,points_cost,status,order_code) "
                "VALUES (%s,%s,%s,0,'completed',%s) RETURNING id",
                (user.id, "telegram_number_stars", auto_number, code)
            ).fetchone()
            c.execute(
                "UPDATE number_star_purchases SET phone_number=%s,status='completed' "
                "WHERE telegram_payment_id=%s",
                (auto_number, charge_id)
            )

        display_number = auto_number.lstrip("+")
        result_kb = [
            [
                InlineKeyboardButton("🔐 رمز التحقق (2FA)", callback_data=f"buyer:show_twofa:{auto_number}"),
                InlineKeyboardButton("🔑 كود الدخول", callback_data=f"buyer:request_code:{auto_number}"),
            ],
            [InlineKeyboardButton("📷 باركود الرقم", callback_data=f"buyer:barcode:{auto_number}")],
            [InlineKeyboardButton("🚪 مغادرة البوت", callback_data=f"buyer:leave_account:{auto_number}")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
        ]
        await update.message.reply_text(
            f"✅ *تم شراء رقمك بالنجوم بنجاح!*\n\n"
            f"📱 *الرقم:*\n`{display_number}`\n"
            f"⭐ المدفوع: {stars} نجمة\n\n"
            "اضغط على الأزرار أدناه للحصول على رمز التحقق وكود الدخول عند الحاجة.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(result_kb)
        )
        try:
            await context.bot.send_message(
                user.id,
                "📋 *إشعار تبرئة ذمة — يُرجى القراءة بعناية*\n\n"
                "بإتمامك عملية الشراء فإنك تُقرّ بأن الحساب والرقم أصبحا مسؤوليتك الكاملة "
                "من لحظة الاستلام، ولا يحق المطالبة باسترداد بعد استلام بيانات الدخول.\n\n"
                "شكراً لثقتك 🤍",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        if pe:
            await notify_prize_exchange_owner(
                context, pe["id"],
                text_html=(
                    f"📱 <b>شراء رقم تيلغرام بالنجوم — تسليم تلقائي ✅</b>\n"
                    f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                    f"📱 الرقم: <code>{auto_number}</code>\n"
                    f"⭐ {stars} نجمة\n"
                    f"📌 {code}"
                ),
                group_text_html=(
                    f"📱 <b>شراء رقم تيلغرام بالنجوم — تسليم تلقائي ✅</b>\n"
                    f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                    f"⭐ {stars} نجمة\n"
                    f"📌 {code}"
                )
            )

    # ─── تمويل الاشتراك الإجباري بالنجوم ───
    elif payload.startswith("fund_mandatory:"):
        parts        = payload.split(":")
        _uid         = int(parts[1])
        member_count = int(parts[2])
        channel      = parts[3]
        total_stars  = int(parts[4])
        channel_md   = md_escape(channel)

        is_queued = False
        if count_active_mandatory_channels() >= MANDATORY_MAX_ACTIVE:
            is_queued = True

        code = next_order_code(user.id)
        with db_conn() as c:
            c.execute(
                "INSERT INTO channel_funding (user_id,channel_username,funding_type,cost_points,target_members,current_members,status) "
                "VALUES (%s,%s,'mandatory',0,%s,0,'active')",
                (user.id, channel, member_count)
            )
            c.execute(
                "INSERT INTO mandatory_channels (channel_username,owner_user_id,funding_type,active,queued) "
                "VALUES (%s,%s,'mandatory',%s,%s) "
                "ON CONFLICT (channel_username) DO UPDATE SET funding_type=EXCLUDED.funding_type, owner_user_id=EXCLUDED.owner_user_id, "
                "active=EXCLUDED.active, queued=EXCLUDED.queued",
                (channel, user.id, 0 if is_queued else 1, 1 if is_queued else 0)
            )

        if is_queued:
            await update.message.reply_text(
                f"⏳ *تم استلام تمويل قناتك بنجاح — في قائمة الانتظار!*\n\n"
                f"📢 القناة: @{channel_md}\n"
                f"👥 عدد الأعضاء: {member_count:,}\n"
                f"⭐ دفعت: {total_stars} نجمة\n\n"
                f"⚠️ عدد القنوات الإجبارية النشطة بلغ الحد الأقصى ({MANDATORY_MAX_ACTIVE}).\n"
                f"✅ ستُفعَّل قناتك تلقائياً فور تحرّر أحد الأماكن.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
        else:
            await update.message.reply_text(
                f"✅ *تم تفعيل قناتك الإجبارية بنجاح!*\n\n"
                f"📢 القناة: @{channel_md}\n"
                f"👥 عدد الأعضاء: {member_count:,}\n"
                f"⭐ دفعت: {total_stars} نجمة\n"
                f"📌 كود العملية: `{code}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )

        _queue_note = "\n⏳ <b>ملاحظة:</b> دخلت قائمة الانتظار وستُفعَّل عند توفر مكان." if is_queued else ""
        _terms = mandatory_terms_text_html()
        try:
            await context.application.bot.send_message(
                ADMIN_GROUP_ID,
                f"📢 <b>تمويل قناة إجباري — نجوم</b>\n"
                f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                f"📡 القناة: @{channel}\n"
                f"👥 {member_count:,} عضو\n"
                f"⭐ {total_stars} نجمة\n"
                f"📌 {code}"
                f"{_queue_note}\n"
                f"{_terms}",
                parse_mode="HTML"
            )
        except Exception:
            pass

async def delete_group_service_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"⚠️ فشل حذف رسالة انضمام/مغادرة في كروب الإشعارات: {e}")

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
async def handle_bot_removed_from_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عندما يُزال البوت من قناة:
    1. احذف القناة من طلبات الاشتراك الإجباري النشطة (mandatory_sub_orders).
    2. أوقف القناة في جدول mandatory_channels (الاشتراك الإجباري الرئيسي والداخلي).
    """
    cmu = update.my_chat_member
    if not cmu:
        return
    new_status = cmu.new_chat_member.status
    if new_status not in ("left", "kicked", "banned"):
        return
    chat = cmu.chat
    username = (chat.username or "").lstrip("@").lower()
    if not username:
        return
    try:
        # ── 1. حذف القناة من طلبات mandatory_sub_orders النشطة ──
        with db_conn() as c:
            orders = c.execute(
                "SELECT id, channels FROM mandatory_sub_orders "
                "WHERE status IN ('pending','running') AND channels != '' AND channels IS NOT NULL"
            ).fetchall()
        updated = 0
        for o in orders:
            raw = o["channels"] or ""
            tokens = raw.split()
            new_tokens = [
                t for t in tokens
                if t.lstrip("@").lower().split("?")[0].rstrip("/") != username
                and t.lower().replace("https://t.me/","").replace("https://telegram.me/","").lstrip("+").rstrip("/") != username
            ]
            if len(new_tokens) != len(tokens):
                new_channels = " ".join(new_tokens)
                with db_conn() as c:
                    c.execute(
                        "UPDATE mandatory_sub_orders SET channels=%s WHERE id=%s",
                        (new_channels, o["id"])
                    )
                updated += 1
        if updated:
            logger.info(f"🔕 البوت أُزيل من @{username} — حُذفت من {updated} طلب اشتراك إجباري")

        # ── 2. إيقاف القناة من mandatory_channels (رئيسي وداخلي) ──
        with db_conn() as c:
            deactivated = c.execute(
                "UPDATE mandatory_channels SET active=0, queued=0 "
                "WHERE lower(channel_username)=%s AND (active=1 OR queued=1)",
                (username,)
            ).rowcount
        if deactivated:
            logger.info(f"🔕 تم إيقاف القناة @{username} من mandatory_channels ({deactivated} صف)")
            # تفعيل القناة التالية في قائمة الانتظار (إن وُجدت) لملء الفراغ
            try:
                await promote_queued_mandatory_channel(context)
            except Exception as _pe:
                logger.warning(f"promote_queued_mandatory_channel error: {_pe}")

    except Exception as _e:
        logger.warning(f"handle_bot_removed_from_channel error: {_e}")


async def handle_member_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmu = update.chat_member
    if not cmu:
        return
    old_status = cmu.old_chat_member.status
    new_status = cmu.new_chat_member.status
    member_user = cmu.new_chat_member.user
    if member_user.is_bot:
        return
    was_in = old_status in ("member", "administrator", "creator", "restricted")
    now_out = new_status in ("left", "kicked")
    if not (was_in and now_out):
        return
    username = (cmu.chat.username or "").lstrip("@")
    if not username:
        return
    with db_conn() as c:
        ch = c.execute(
            "SELECT * FROM mandatory_channels WHERE channel_username=? AND funding_type='internal' AND active=1",
            (username,)
        ).fetchone()
    if not ch:
        return
    with db_conn() as c:
        claimed = c.execute(
            "SELECT joined_at FROM channel_join_rewards WHERE user_id=? AND channel_id=?",
            (member_user.id, ch["id"])
        ).fetchone()
        if not claimed:
            return
        # ─── فحص مهلة المغادرة الآمنة (24 ساعة افتراضياً) ───
        grace_hours = int(get_setting("internal_leave_grace_hours") or "24")
        joined_at = claimed["joined_at"]
        if joined_at:
            import datetime as _dt_grace
            now_utc = _dt_grace.datetime.now(_dt_grace.timezone.utc)
            if hasattr(joined_at, "tzinfo") and joined_at.tzinfo is None:
                joined_at = joined_at.replace(tzinfo=_dt_grace.timezone.utc)
            time_passed = now_utc - joined_at
            if time_passed.total_seconds() >= grace_hours * 3600:
                c.execute(
                    "DELETE FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                    (member_user.id, ch["id"])
                )
                return
        c.execute(
            "DELETE FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
            (member_user.id, ch["id"])
        )
    # ─── خصم النقاط — يُسمح بالرصيد السالب ───
    penalty = int(get_setting("channel_leave_penalty") or "75")
    with db_conn() as _pc:
        _pc.execute("UPDATE users SET points=points-%s WHERE user_id=%s", (penalty, member_user.id))
    db_u = get_user(member_user.id)
    balance_after = db_u["points"] if db_u else 0
    try:
        await context.bot.send_message(
            member_user.id,
            f"⚠️ *تنبيه خصم نقاط*\n\n"
            f"لاحظنا أنك غادرت القناة @{username} خلال مهلة {grace_hours} ساعة من انضمامك.\n"
            f"💸 تم خصم *{penalty} نقطة* من رصيدك.\n"
            f"💰 رصيدك الآن: *{balance_after} نقطة*\n\n"
            f"يمكنك الانضمام للقناة مجدداً من قسم 💰 تجميع النقاط لكسب النقاط من جديد.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        pass

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /broadcast <رسالة> — يبث رسالة HTML لجميع المستخدمين."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    if not context.args:
        await update.message.reply_text("الاستخدام:\n/broadcast <نص الرسالة>")
        return
    broadcast_text = " ".join(context.args)
    with db_conn() as c:
        users_list = c.execute("SELECT user_id FROM users").fetchall()
    sent, failed = 0, 0
    for u_row in users_list:
        try:
            await context.bot.send_message(u_row["user_id"], broadcast_text, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"✅ أُرسلت: {sent} | ❌ فشل: {failed}")

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر عام: /cancel — يوقف أي عملية إدخال نصي معلّقة (مثل حلقة إضافة أرقام متتالية) ويرجع للقائمة."""
    user = update.effective_user
    if user and user.id == OWNER_ID:
        await _cleanup_pending_login(user.id)
    if user:
        _pending_supervisor_logins.pop(user.id, None)
    context.user_data["state"] = "main_menu"
    _is_sv = user and is_supervisor(user.id) and (user.id != OWNER_ID)
    if user and user.id == OWNER_ID:
        kb = owner_settings_kb()
    elif _is_sv:
        kb = supervisor_panel_kb()
    else:
        kb = main_menu_kb()
    await update.message.reply_text("🔙 تم التوقف والرجوع للقائمة الرئيسية.", reply_markup=kb)

async def cmd_status_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /status <كود_الطلب> — يعرض تفاصيل طلب بكوده."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    if not context.args:
        await update.message.reply_text("الاستخدام:\n/status <كود_الطلب>")
        return
    code = context.args[0].strip()
    with db_conn() as c:
        order = c.execute(
            "SELECT o.*, s.name_ar FROM orders o LEFT JOIN services s ON s.id=o.service_id WHERE o.order_code=?",
            (code,)
        ).fetchone()
    if not order:
        await update.message.reply_text(f"⚠️ لا يوجد طلب بالكود: {code}")
        return
    status_map = {"pending": "⏳ قيد الانتظار", "completed": "✅ مكتمل", "cancelled": "❌ ملغى"}
    status_label = status_map.get(order["status"], order["status"])
    await update.message.reply_text(
        f"📋 *تفاصيل الطلب*\n\n"
        f"📌 الكود: `{order['order_code']}`\n"
        f"👤 المستخدم: {order['user_id']}\n"
        f"🔹 الخدمة: {order['name_ar'] or '—'}\n"
        f"🔗 الرابط: {order['link']}\n"
        f"🔢 الكمية: {order['quantity']}\n"
        f"💰 التكلفة: {order['cost_points']} نقطة\n"
        f"📊 الحالة: {status_label}\n"
        f"🆔 كود API: {order['api_order_id'] or '—'}\n"
        f"🕐 التاريخ: {order['created_at']}",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_compensate_partial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /compensate_partial
    يفحص جميع طلبات SMMMAIN المكتملة التي لم تحصل على تعويض جزئي بعد،
    يسأل موقع الرشق عن حالتها، وإن كانت Partial يحسب النقاط ويُعيدها لأصحابها.
    مفيد لتعويض المستخدمين الذين خسروا نقاطاً قبل تفعيل هذه الميزة."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return

    await update.message.reply_text(
        "🔍 جاري فحص الطلبات المكتملة للبحث عن طلبات جزئية غير معوَّضة...\n"
        "⏳ قد يستغرق هذا بعض الوقت حسب عدد الطلبات."
    )

    try:
        with db_conn() as c:
            candidates = c.execute(
                "SELECT o.*, s.panel AS svc_panel, s.api_service_id AS svc_api_id "
                "FROM orders o "
                "LEFT JOIN services s ON s.id = o.service_id "
                "WHERE o.status='completed' "
                "  AND (o.partial_refund_pts IS NULL OR o.partial_refund_pts = 0) "
                "  AND o.api_order_id IS NOT NULL AND o.api_order_id != '' "
                "  AND (s.panel = 1 OR s.panel IS NULL)"   # فقط SMMMAIN
            ).fetchall()
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في جلب الطلبات: {e}")
        return

    if not candidates:
        await update.message.reply_text("✅ لا توجد طلبات تحتاج فحصاً.")
        return

    await update.message.reply_text(f"📋 عدد الطلبات المراد فحصها: {len(candidates):,}")

    compensated, skipped, errors = 0, 0, 0
    total_pts_given = 0

    for o in candidates:
        try:
            res = await asyncio.to_thread(smm_order_status, o["api_order_id"], panel=1)
        except Exception:
            errors += 1
            continue

        if not isinstance(res, dict) or "error" in res:
            skipped += 1
            continue

        panel_status = str(res.get("status", "")).strip().lower()

        if panel_status != "partial":
            skipped += 1
            continue

        remains = int(res.get("remains", 0) or 0)
        if remains <= 0 or not o.get("svc_api_id"):
            skipped += 1
            continue

        refund_pts = _calc_partial_refund_pts(o["svc_api_id"], remains)
        if refund_pts <= 0:
            skipped += 1
            continue

        add_points(o["user_id"], refund_pts)
        with db_conn() as c:
            c.execute(
                "UPDATE orders SET partial_refund_pts=%s WHERE id=%s",
                (refund_pts, o["id"])
            )

        try:
            await context.bot.send_message(
                o["user_id"],
                f"💰 *تعويض طلب جزئي*\n\n"
                f"📌 كود الطلب: `{o['order_code']}`\n"
                f"📦 الوحدات غير المنفذة: {remains:,}\n"
                f"✅ تم إضافة *{refund_pts:,}* نقطة إلى رصيدك تعويضاً.\n\n"
                f"نعتذر عن التأخير في هذا التعويض.",
                parse_mode="Markdown"
            )
        except Exception:
            pass

        compensated += 1
        total_pts_given += refund_pts
        logger.info(f"✅ تعويض جزئي: طلب {o['order_code']} — {refund_pts:,} نقطة → {o['user_id']}")

    await update.message.reply_text(
        f"✅ *انتهى فحص التعويضات*\n\n"
        f"💚 طلبات عُوِّضت: {compensated}\n"
        f"💰 إجمالي النقاط الموزّعة: {total_pts_given:,}\n"
        f"⏭ طلبات تخطّيها (غير جزئية): {skipped}\n"
        f"❌ أخطاء API: {errors}",
        parse_mode="Markdown"
    )

async def cmd_refund_mandatory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /refund_mandatory
    كان هنالك خلل في تفعيل الاشتراك الإجباري يجعل المستخدمين القدامى لا يُطالَبون
    بالانضمام للقنوات الإجبارية الجديدة (تم إصلاحه الآن). هذا الأمر يعيد نقاط كل من
    دفع لتفعيل «تمويل قناة إجباري سريع» ولم يُسترجع له ماله بعد، ويرسل له اعتذاراً
    مع طلب إعادة تفعيل تمويل قناته من جديد بعد الإصلاح."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return

    with db_conn() as c:
        fundings = c.execute(
            "SELECT * FROM channel_funding WHERE funding_type='mandatory' AND status != 'refunded'"
        ).fetchall()

    if not fundings:
        await update.message.reply_text("✅ لا توجد تمويلات إجبارية بحاجة لاسترجاع.")
        return

    await update.message.reply_text(
        f"🔍 تم العثور على {len(fundings):,} تمويل إجباري. جاري إعادة النقاط والاعتذار لأصحابها..."
    )

    refunded, errors, total_pts = 0, 0, 0
    for f in fundings:
        pts = f.get("cost_points", 0) or 0
        try:
            if pts:
                add_points(f["user_id"], pts)
            with db_conn() as c:
                c.execute("UPDATE channel_funding SET status='refunded' WHERE id=?", (f["id"],))
                c.execute(
                    "UPDATE mandatory_channels SET active=0, queued=0 WHERE channel_username=? AND funding_type='mandatory'",
                    (f["channel_username"],)
                )
        except Exception as e:
            logger.warning(f"⚠️ فشل استرجاع تمويل القناة @{f.get('channel_username')}: {e}")
            errors += 1
            continue

        try:
            await context.bot.send_message(
                f["user_id"],
                f"🙏 *اعتذار بخصوص تمويل قناتك @{f['channel_username']}*\n\n"
                f"اكتشفنا خللاً فنياً كان يمنع القناة الإجبارية من الظهور لبعض\n"
                f"المستخدمين القدامى في البوت، ما أثّر على نتيجة تمويلك.\n\n"
                f"✅ تم إعادة *{pts:,}* نقطة كاملة إلى رصيدك تعويضاً عن ذلك.\n"
                f"🛠 تم إصلاح الخلل الآن بالكامل، وأصبحت القنوات الإجبارية تظهر لجميع\n"
                f"المستخدمين (القدامى والجدد) في كل مرة يستخدمون فيها البوت.\n\n"
                f"🔁 يمكنك الآن إعادة طلب «📺 تمويل قناتك حقيقي ← تمويل قناة إجباري سريع»\n"
                f"من القائمة الرئيسية لتفعيل تمويل قناتك من جديد والاستفادة الكاملة منه.\n\n"
                f"نعتذر عن الإزعاج ونشكر تفهمك 🌹",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

        refunded += 1
        total_pts += pts
        logger.info(f"✅ استرجاع تمويل إجباري: @{f['channel_username']} — {pts:,} نقطة → {f['user_id']}")

    await promote_queued_mandatory_channel(context, app=context.application)

    await update.message.reply_text(
        f"✅ *انتهى استرجاع تمويلات الاشتراك الإجباري*\n\n"
        f"💚 عدد من تم استرجاع تمويله: {refunded}\n"
        f"💰 إجمالي النقاط المُعادة: {total_pts:,}\n"
        f"❌ أخطاء: {errors}",
        parse_mode=ParseMode.MARKDOWN
    )
