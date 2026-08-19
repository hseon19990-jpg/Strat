
# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
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

        # ─── الاشتراك الإجباري بالنجوم ───
        if payload.startswith("fund_mandatory:"):
            parts = payload.split(":")
            if len(parts) == 5 and parts[1].isdigit() and parts[4].isdigit():
                uid_in_payload = int(parts[1])
                expected_stars = int(parts[4])
                if query.from_user.id == uid_in_payload and query.total_amount == expected_stars:
                    valid = True

        # ─── إحالة بوت إجبارية بالنجوم ───
        # payload: forced_ref_stars:{user_id}:{qty}:{total_stars}:{use_ai}:{cost_pts_channels}
        if payload.startswith("forced_ref_stars:"):
            parts = payload.split(":")
            if len(parts) >= 5 and parts[1].isdigit() and parts[3].isdigit():
                uid_in_payload = int(parts[1])
                expected_stars = int(parts[3])
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

    # ─── إحالة بوت إجبارية بالنجوم ───
    # payload: forced_ref_stars:{user_id}:{qty}:{total_stars}:{use_ai}:{cost_pts_channels}
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
            use_ai=use_ai, payment_method='stars', cost_stars=total_stars
        ))

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

def main():
    # ── إنشاء event loop جديد في كل تشغيل لتفادي RuntimeError: Event loop is closed ──
    import asyncio as _asyncio
    _loop = _asyncio.new_event_loop()
    _asyncio.set_event_loop(_loop)

    # ── التحقق من المتغيرات البيئية الضرورية عند الإطلاق ──────────────────
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not DATABASE_URL:
        missing.append("DATABASE_URL")
    if not OWNER_ID:
        missing.append("OWNER_ID")
    if missing:
        logger.critical(f"❌ متغيرات بيئية مفقودة: {', '.join(missing)}")
        logger.critical("❌ أضفها في إعدادات Railway ثم أعد التشغيل.")
        raise SystemExit(1)

    init_db()
    start_health_server()

    from telegram.request import HTTPXRequest
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .get_updates_request(HTTPXRequest(
            connection_pool_size=1,
            read_timeout=60,
            connect_timeout=30,
            write_timeout=30,
        ))
        .build()
    )

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("admin",     cmd_admin))
    app.add_handler(CommandHandler("addpoints", cmd_addpoints))
    app.add_handler(CommandHandler("grant_ref", cmd_grant_ref))
    app.add_handler(CommandHandler("broadcast",           cmd_broadcast))
    app.add_handler(CommandHandler("status",              cmd_status_order))
    app.add_handler(CommandHandler("compensate_partial",  cmd_compensate_partial))
    app.add_handler(CommandHandler("refund_mandatory",    cmd_refund_mandatory))
    app.add_handler(CommandHandler("cancel",              cmd_cancel))
    app.add_handler(CommandHandler("import_session",      cmd_import_session))
    app.add_handler(CommandHandler("import_sessions",     cmd_import_sessions))
    app.add_handler(CommandHandler("import_hex",          cmd_import_hex))
    app.add_handler(CommandHandler("mass_reset",          cmd_mass_reset))
    app.add_handler(CommandHandler("rotate_sessions",     cmd_rotate_sessions))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.CAPTION) & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_text
    ))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.Document.MimeType("application/json"),
        handle_json_file
    ))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.Document.FileExtension("session"),
        handle_session_file
    ))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.Document.FileExtension("zip"),
        handle_zip_file
    ))
    # ── معالج مشاركة رقم الهاتف لنظام الإحالة ──────────────────
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.CONTACT,
        handle_contact_share
    ))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.SUCCESSFUL_PAYMENT,
        handle_unsupported_message
    ))
    app.add_handler(ChatMemberHandler(handle_member_leave, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(handle_bot_removed_from_channel, ChatMemberHandler.MY_CHAT_MEMBER))
    if ADMIN_GROUP_ID:
        app.add_handler(MessageHandler(
            filters.Chat(ADMIN_GROUP_ID) &
            (filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER),
            delete_group_service_messages
        ))

    async def post_init(application):
        # ─── معالج عالمي للاستثناءات غير المعالجة في asyncio tasks ────────
        def _handle_asyncio_exception(loop, context):
            exc = context.get("exception")
            msg = context.get("message", "")
            if exc is None:
                logger.warning(f"⚠️ asyncio unhandled: {msg}")
            elif isinstance(exc, asyncio.CancelledError):
                pass  # طبيعي عند إغلاق البوت
            else:
                logger.error(f"❌ asyncio task exception: {exc!r} | {msg}")
        try:
            asyncio.get_event_loop().set_exception_handler(_handle_asyncio_exception)
        except Exception:
            pass

        # ─── حذف أي webhook مسجّل مسبقاً حتى يعمل long polling بشكل صحيح ───
        try:
            await application.bot.delete_webhook(drop_pending_updates=True)
            logger.info("✅ Webhook deleted — polling mode active")
        except Exception as _wh_err:
            logger.warning(f"⚠️ تعذّر حذف webhook: {_wh_err}")

        await application.bot.set_my_commands([
            BotCommand("start", "🏠 القائمة الرئيسية"),
        ])
        if OWNER_ID:
            try:
                await application.bot.set_my_commands(
                    [
                        BotCommand("start",     "🏠 القائمة الرئيسية"),
                        BotCommand("admin",     "⚙️ لوحة المالك"),
                        BotCommand("addpoints", "💰 إضافة/خصم نقاط لمستخدم"),
                        BotCommand("broadcast",          "📢 إرسال رسالة جماعية"),
                        BotCommand("status",             "🔍 فحص حالة طلب"),
                        BotCommand("compensate_partial", "💰 تعويض أصحاب الطلبات الجزئية"),
                        BotCommand("refund_mandatory", "🔁 استرجاع تمويلات الاشتراك الإجباري"),
                    ],
                    scope=BotCommandScopeChat(chat_id=OWNER_ID)
                )
            except Exception as e:
                logger.warning(f"⚠️ تعذّر تعيين أوامر المالك الخاصة (ربما لم يبدأ المالك محادثة مع البوت بعد): {e}")
        logger.info("✅ Bot commands set")
        # حفظ اسم المستخدم الخاص بهذا البوت لاستخدامه في تخطي الإحالة الذاتية
        global _OWN_BOT_USERNAME
        try:
            _me = await application.bot.get_me()
            _OWN_BOT_USERNAME = (_me.username or "").lower().strip()
            logger.info(f"✅ _OWN_BOT_USERNAME = @{_OWN_BOT_USERNAME}")
        except Exception as _e:
            logger.warning(f"⚠️ تعذّر جلب username البوت: {_e}")
        # ─── تعويض المبيعات المكررة عند الإقلاع ────
        async def _bg_startup():
            try:
                await compensate_duplicate_sales_job(
                    type("_ctx", (), {"bot": application.bot})()
                )
            except Exception as e:
                logger.warning(f"⚠️ compensate_duplicate_sales (startup): {e}")
        asyncio.create_task(_bg_startup())
        try:
            with db_conn() as _mc:
                _mc.execute(
                    "UPDATE number_stock SET deleted_at=NOW() "
                    "WHERE session_string IS NULL AND deleted_at IS NULL"
                )
                _deleted_manual = _mc.rowcount
            if _deleted_manual:
                logger.warning(f"🗑 حُذفت {_deleted_manual} أرقام يدوية (بلا جلسة) عند الإقلاع.")
        except Exception as e:
            logger.warning(f"⚠️ تنظيف الأرقام اليدوية (startup): {e}")
        # ─── حذف الأرقام المجمّدة المكتشفة مسبقاً (frozen_at IS NOT NULL) ────
        try:
            with db_conn() as _fzc:
                _fzc.execute(
                    "DELETE FROM number_stock "
                    "WHERE frozen_at IS NOT NULL AND ever_sold IS NOT TRUE AND assigned_to IS NULL"
                )
                _frz_deleted = _fzc.rowcount
            if _frz_deleted:
                logger.warning(f"🧊 حُذفت {_frz_deleted} أرقام مجمّدة تلقائياً عند الإقلاع.")
        except Exception as e:
            logger.warning(f"⚠️ تنظيف الأرقام المجمّدة (startup): {e}")
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        err = context.error
        if isinstance(err, RetryAfter):
            logger.warning(f"⚠️ RetryAfter: {err.retry_after}s")
            return
        if isinstance(err, (NetworkError, TimedOut)):
            logger.warning(f"⚠️ خطأ شبكي مؤقت: {err}")
            return
        if isinstance(err, Conflict):
            # نسختان تعملان في نفس الوقت — طبيعي عند redeploy، سيختفي خلال ثوانٍ
            logger.warning("⚠️ Conflict: نسخة أخرى من البوت تعمل — جاري الانتظار حتى تنتهي...")
            return
        # أخطاء Forbidden/BadRequest من handlers — لا تُوقف البوت
        from telegram.error import Forbidden, BadRequest
        if isinstance(err, (Forbidden, BadRequest)):
            logger.warning(f"⚠️ Telegram API error (ignored): {err}")
            return
        logger.error(f"❌ خطأ غير متوقع:\n{traceback.format_exc()}")

    app.add_error_handler(error_handler)
    app.post_init = post_init

    if app.job_queue:
        app.job_queue.run_repeating(check_pending_orders_job, interval=300, first=30)
        logger.info("⏱️ تم تفعيل الفحص الدوري لحالة الطلبات (كل 5 دقائق)")
        app.job_queue.run_repeating(retry_pending_session_resets, interval=600, first=90)
        logger.info("🔒 تم تفعيل إعادة المحاولة الدورية لطرد جلسات الأرقام (كل 10 دقائق)")
        app.job_queue.run_repeating(run_referral_tasks_job, interval=3600, first=120)
        logger.info("🤝 تم تفعيل مهام الإحالة التلقائية (كل ساعة)")
        app.job_queue.run_repeating(compensate_duplicate_sales_job, interval=21600, first=300)
        logger.info("🔁 تم تفعيل فحص البيع المكرر وتعويض المتضررين (كل 6 ساعات)")
        app.job_queue.run_repeating(check_twofa_reset_job, interval=3600, first=60)
        logger.info("🔐 تم تفعيل فحص إكمال إعادة تعيين 2FA (كل ساعة)")
        app.job_queue.run_repeating(_account_fixup_job, interval=30, first=15)
        logger.info("🔧 تم تفعيل حلقة الإصلاح التلقائي للحسابات (كل 30 ثانية)")

    logger.info("🤖 Bot started!")
    app.run_polling(
        drop_pending_updates=True,
        read_timeout=45,
        write_timeout=45,
        connect_timeout=45,
        pool_timeout=45,
        allowed_updates=["message", "callback_query", "pre_checkout_query", "successful_payment", "chat_member", "my_chat_member"],
    )

