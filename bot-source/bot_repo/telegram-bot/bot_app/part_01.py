
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════

async def _mansub_start(update, context, user, q, is_own):
    avail = get_available_number_count()
    bp = int(get_setting('mansub_base_price') or '250')
    cp = int(get_setting('mansub_channel_price') or '50')
    vis = get_setting('mansub_visible') == '1'
    tgl = '🔒 إخفاء من الأعضاء' if vis else '🔓 إظهار للأعضاء'
    visnote = '👁 مرئية للأعضاء' if vis else '🔒 مخفية (مالك فقط)'
    context.user_data['state'] = 'await_mansub_link'
    context.user_data['mansub_draft'] = {}
    own_row = [[InlineKeyboardButton(tgl, callback_data='os:toggle_mansub_visible')]] if user.id == OWNER_ID else []
    await q.edit_message_text(
        f'🔑 *الاشتراك الإجباري*\n\n'
        f'📊 الحسابات المتاحة: *{avail}*\n'
        f'💰 {bp} نقطة/حساب + {cp} نقطة/قناة\n'
        f'📌 {visnote}\n\n'
        f'📎 *خطوة 1/3* — أرسل رابط إحالة بوتك:\n'
        f'`t.me/BotUsername?start=CODE`\n'
        f'أو: `@BotUsername CODE`',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(own_row + [
            [InlineKeyboardButton('🔙 رجوع', callback_data='cat:start_bot')]
        ])
    )

async def _mansub_handle_link(update, context):
    raw = update.message.text.strip()
    bot_user = start_p = ''
    try:
        if 't.me/' in raw or 'telegram.me/' in raw:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(raw if raw.startswith('http') else 'https://' + raw)
            bot_user = parsed.path.strip('/')
            start_p = parse_qs(parsed.query).get('start', [''])[0]
        else:
            parts = raw.split(None, 1)
            bot_user = parts[0].lstrip('@')
            start_p = parts[1] if len(parts) > 1 else ''
        # الكود اختياري — المهم أن يكون اسم البوت موجوداً
        if not bot_user:
            raise ValueError('اسم البوت فارغ')
        draft = context.user_data.setdefault('mansub_draft', {})
        draft['bot_user'] = bot_user
        draft['start_p'] = start_p
        context.user_data['state'] = 'await_mansub_channels'
        code_info = f'`{start_p}`' if start_p else 'بدون كود'
        bot_display = '`@' + bot_user + '`'
        await update.message.reply_text(
            f'✅ البوت: {bot_display} | {code_info}\n\n'
            f'📢 *خطوة 2/3 — القنوات الإجبارية:*\n'
            f'أرسل يوزرات القنوات مفصولة بمسافة.\n'
            f'مثال: `@chan1 @chan2`\n\n'
            f'أو اضغط تخطي إذا لا توجد قنوات.',
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('⏭️ تخطي (بدون قنوات)', callback_data='mansub_skip_channels')],
                [InlineKeyboardButton('🔙 إلغاء', callback_data='cat:start_bot')]
            ])
        )
    except Exception as _pe:
        import logging as _lg
        _lg.getLogger(__name__).warning(f'mansub_handle_link error: {_pe}')
        await update.message.reply_text(
            f'⚠️ تعذّر قراءة الرابط.\nأرسل اسم البوت هكذا:\n`@BotUsername` أو `t.me/BotUsername`',
            parse_mode=ParseMode.MARKDOWN
        )

async def _mansub_handle_channels(update, context):
    raw = update.message.text.strip()
    draft = context.user_data.setdefault('mansub_draft', {})
    draft['channels'] = '' if raw.lower() in ('تخطي', 'skip', '-') else raw
    context.user_data['state'] = 'await_mansub_qty'
    avail = get_available_number_count()
    ch_count = len([t for t in raw.split() if t.strip()]) if draft['channels'] else 0
    bp = int(get_setting('mansub_base_price') or '250')
    cp = int(get_setting('mansub_channel_price') or '50')
    cost_each = bp + ch_count * cp
    await update.message.reply_text(
        f'✅ القنوات: `{draft["channels"] or "لا يوجد"}`\n\n'
        f'📊 المتاح: *{avail}* حساب\n'
        f'💰 سعر/حساب: *{cost_each}* نقطة\n\n'
        f'🔢 *خطوة 3/3* — أرسل عدد الحسابات (1 – {avail}):',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 إلغاء', callback_data='cat:start_bot')]])
    )

async def _mansub_handle_qty(update, context, user):
    try:
        qty = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text('⚠️ أرسل رقماً صحيحاً.')
        return
    avail = get_available_number_count()
    if qty < 1 or qty > avail:
        await update.message.reply_text(f'⚠️ الكمية خارج النطاق (1 – {avail}).')
        return
    draft = context.user_data.setdefault('mansub_draft', {})
    channels = draft.get('channels', '')
    ch_count = len([t for t in channels.split() if t.strip()]) if channels else 0
    bp = int(get_setting('mansub_base_price') or '250')
    cp = int(get_setting('mansub_channel_price') or '50')
    cost_each = bp + ch_count * cp
    total = cost_each * qty
    draft['qty'] = qty
    draft['cost'] = total
    db_user = get_user(user.id)
    pts = db_user['points'] if db_user else 0
    context.user_data['state'] = 'confirm_mansub'
    ch_line = f'\n📢 القنوات: `{channels}`' if channels else ''
    _bu_m = draft.get('bot_user', '')
    _sp_m = draft.get('start_p', '')
    _code_m = f'`{_sp_m}`' if _sp_m else 'بدون كود'
    await update.message.reply_text(
        f'📋 *تأكيد الاشتراك الإجباري:*\n\n'
        f'📌 `@{_bu_m}` | كود: {_code_m}{ch_line}\n'
        f'🔢 {qty} حساب × {cost_each} نقطة = *{total}* نقطة\n'
        f'💎 رصيدك: {pts} نقطة\n\n'
        f'⚡ الحسابات تعمل بترتيب عشوائي\n'
        f'💡 الفاشلة: تُستردّ نقاطها تلقائياً | إعادة التفعيل: لا تعويض',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('✅ تأكيد', callback_data='confirm_mansub:yes'),
             InlineKeyboardButton('❌ إلغاء', callback_data='confirm_mansub:no')]
        ])
    )

async def _handle_confirm_mansub(update, context, user, q, is_own, data):
    action = data.split(':')[1]
    if context.user_data.get('state') != 'confirm_mansub':
        await q.edit_message_text('⚠️ انتهت صلاحية الطلب.', reply_markup=main_menu_kb(is_own))
        return
    draft = context.user_data.get('mansub_draft', {})
    if action == 'no':
        context.user_data['state'] = 'main_menu'
        await q.edit_message_text('❌ تم إلغاء الطلب.', reply_markup=main_menu_kb(is_own))
        return
    bot_user = draft.get('bot_user', '')
    start_p  = draft.get('start_p', '')
    channels = draft.get('channels', '')
    qty      = draft.get('qty', 0)
    total    = draft.get('cost', 0)
    if not bot_user or qty < 1:
        context.user_data['state'] = 'main_menu'
        await q.edit_message_text('⚠️ بيانات غير مكتملة.', reply_markup=main_menu_kb(is_own))
        return
    _dbu = get_user(user.id)
    if _dbu and _dbu.get('referral_points_blocked'):
        await q.edit_message_text('🔒 حسابك موقوف. تواصل مع المالك.', reply_markup=main_menu_kb(is_own))
        return
    if not deduct_points(user.id, total):
        await q.edit_message_text('❌ نقاطك غير كافية.', reply_markup=main_menu_kb(is_own))
        context.user_data['state'] = 'main_menu'
        return
    code = next_order_code(user.id)
    with db_conn() as c:
        row = c.execute(
            'INSERT INTO mandatory_sub_orders '
            '(user_id,bot_username,start_param,channels,quantity,cost_points,status,order_code) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
            (user.id, bot_user, start_p, channels, qty, total, 'pending', code)
        ).fetchone()
        order_id = row['id']
    context.user_data['state'] = 'main_menu'
    context.user_data.pop('mansub_draft', None)
    _code_ms = f'`{start_p}`' if start_p else 'بدون كود'
    ch_line = f'\n📢 القنوات: `{channels}`' if channels else ''
    await q.edit_message_text(
        f'✅ *تم استلام طلبك!*\n\n'
        f'📌 `@{bot_user}` | كود: {_code_ms}{ch_line}\n'
        f'🔢 {qty} حساب | 💰 {total} نقطة\n'
        f'🎫 كود: `{code}`\n\n'
        f'⏳ سيبدأ التنفيذ قريباً وستصلك إشعار عند الانتهاء.',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb(is_own)
    )
    await _maybe_send_to_group(
        context.bot, user.id,
        f'🔑 *طلب اشتراك إجباري*\n👤 {user.id}\n📌 `@{bot_user}` | `{start_p if start_p else "بدون كود"}`\n🔢 {qty} | 💰 {total}\n🎫 `{code}`',
        parse_mode='Markdown'
    )
    import asyncio as _aio
    _aio.create_task(_run_mansub_order(order_id, bot_user, start_p, channels, qty, user.id, context))

async def _run_mansub_order(order_id, bot_user, start_p, channels, quantity, requester_id, context):
    import random as _rnd
    import time as _time
    with db_conn() as c:
        c.execute("UPDATE mandatory_sub_orders SET status='running' WHERE id=%s", (order_id,))
        rows = c.execute(
            "SELECT id,phone_number,session_string FROM number_stock"
            " WHERE session_string IS NOT NULL AND deleted_at IS NULL AND assigned_to IS NULL"
            " AND ever_sold IS NOT TRUE AND can_send_code IS TRUE AND last_authorized IS NOT FALSE"
            " AND force_listed IS NOT TRUE AND forced_ref_excluded IS NOT TRUE"
            f" AND NOT ({_sellable_filter_sql()})"
            " ORDER BY id"
        ).fetchall()
    with db_conn() as _cm:
        _order_meta = _cm.execute(
            "SELECT cost_points, quantity FROM mandatory_sub_orders WHERE id=%s", (order_id,)
        ).fetchone()
    _total_cost = int(_order_meta["cost_points"] or 0) if _order_meta else 0
    _qty_total  = int(_order_meta["quantity"] or 1) if _order_meta else max(1, quantity)
    _cost_each  = round(_total_cost / _qty_total) if _qty_total else 0

    nums = [dict(r) for r in rows]
    _rnd.shuffle(nums)
    pool_ms     = list(nums)    # كامل المخزون المتاح بترتيب عشوائي
    pool_ms_idx = quantity      # أول حساب بديل بعد الدفعة الأولى
    done = failed = reactivated = 0
    replaced_ms = 0             # عدد الحسابات البديلة المستخدمة
    refunded_pts = 0

    # ─── رسالة التقدم الحي ───
    _live_msg        = None
    _last_edit_time  = 0.0
    _EDIT_INTERVAL   = 3.0   # ثوانٍ بين كل تحديث للرسالة (تجنّب Rate-Limit)

    def _mansub_progress_text(idx: int) -> str:
        parts = []
        if done > 0:        parts.append(f'{done} ✅ تم')
        if failed > 0:      parts.append(f'{failed} ❌ فشل')
        if reactivated > 0: parts.append(f'{reactivated} 🔄 مكرر')
        if replaced_ms > 0: parts.append(f'{replaced_ms} 🔁 بديل')
        status = '  |  '.join(parts) if parts else '⏳ جاري...'
        return (
            f'⏳ <b>جاري تنفيذ الاشتراك الإجباري...</b>\n'
            f'📌 @{bot_user} | {quantity} حساب\n\n'
            f'<b>حساب {idx}/{quantity}</b> — {status}'
        )

    try:
        _live_msg = await context.bot.send_message(
            requester_id,
            f'⏳ <b>جاري تنفيذ الاشتراك الإجباري...</b>\n📌 @{bot_user} | {quantity} حساب\n\nحساب 0/{quantity} — ⏳ جاري...',
            parse_mode='HTML'
        )
        _last_edit_time = _time.monotonic()
    except Exception:
        pass

    import asyncio as _aio2

    # ── معالجة الحسابات مع دعم الاستبدال التلقائي ──
    # عند فشل أي حساب يُستبدل بآخر من المخزون حتى يكتمل العدد المطلوب
    _ms_pending = pool_ms[:quantity]

    while _ms_pending and done + reactivated < quantity:
        _ms_cycle = list(_ms_pending)
        _ms_pending = []            # ستُملأ بالحسابات البديلة

        for _idx, num in enumerate(_ms_cycle, 1):
            if done + reactivated >= quantity:
                break               # ✅ اكتمل الهدف

            try:
                ok, reactiv, _ = await do_referral_for_number(
                    num['phone_number'], num['session_string'],
                    bot_user, start_p,
                    mandatory_channels=channels or '',
                    folder_link='',
                    leave_channels_after=True,
                    stock_id=num.get('id', 0),
                )
            except Exception as _e:
                ok = False; reactiv = False

            with db_conn() as c:
                if ok and reactiv:
                    c.execute("UPDATE mandatory_sub_orders SET reactivated_count=reactivated_count+1 WHERE id=%s", (order_id,))
                    reactivated += 1
                elif ok:
                    c.execute("UPDATE mandatory_sub_orders SET done_count=done_count+1 WHERE id=%s", (order_id,))
                    done += 1
                else:
                    c.execute("UPDATE mandatory_sub_orders SET failed_count=failed_count+1 WHERE id=%s", (order_id,))
                    failed += 1
                    # ── سحب حساب بديل إذا لم يكتمل الهدف ──
                    if done + reactivated < quantity and pool_ms_idx < len(pool_ms):
                        _ms_pending.append(pool_ms[pool_ms_idx])
                        pool_ms_idx += 1
                        replaced_ms += 1

            # ─── تحديث رسالة التقدم الحي (كل 3 ثوانٍ) ───
            _now = _time.monotonic()
            _ms_total = done + failed + reactivated
            if _live_msg and (_now - _last_edit_time >= _EDIT_INTERVAL or _ms_total == quantity):
                try:
                    await context.bot.edit_message_text(
                        _mansub_progress_text(_ms_total),
                        chat_id=requester_id,
                        message_id=_live_msg.message_id,
                        parse_mode='HTML'
                    )
                    _last_edit_time = _now
                except Exception:
                    pass

            await _aio2.sleep(2)

        # إشعار المستخدم بوجود حسابات بديلة
        if _ms_pending and _live_msg:
            try:
                await context.bot.edit_message_text(
                    _mansub_progress_text(done + failed + reactivated) +
                    f'\n🔁 جاري تجربة {len(_ms_pending)} حساب بديل...',
                    chat_id=requester_id,
                    message_id=_live_msg.message_id,
                    parse_mode='HTML'
                )
            except Exception:
                pass

    # ─── استرداد نقاط الكميات غير المكتملة (التي نفد بديلها من المخزون) ───
    unfulfilled_ms = max(0, quantity - done - reactivated)
    if unfulfilled_ms > 0 and _cost_each > 0:
        refunded_pts = unfulfilled_ms * _cost_each
        add_points(requester_id, refunded_pts)

    with db_conn() as c:
        c.execute("UPDATE mandatory_sub_orders SET status='done' WHERE id=%s", (order_id,))

    _refund_line  = f'\n💰 <b>استرداد تلقائي:</b> {refunded_pts:,} نقطة (عن {unfulfilled_ms} حساب لم يُكتمل)' if refunded_pts > 0 else ''
    _replaced_line = f'\n🔁 <i>استُبدل {replaced_ms} حساب فاشل بحسابات أخرى</i>' if replaced_ms > 0 else ''
    _reactiv_note = f'\n⚠️ <i>الحسابات التي كان البوت مفعّلاً بها مسبقاً لا تستحق تعويضاً</i>' if reactivated > 0 else ''
    _final_text = (
        f'✅ <b>اكتمل طلب الاشتراك الإجباري!</b>\n'
        f'📌 @{bot_user}\n\n'
        f'✅ المنجز: {done}\n'
        f'🔄 المكرر (مفعّل مسبقاً): {reactivated}\n'
        f'❌ الملغي (إجمالي): {failed}'
        f'{_replaced_line}{_refund_line}{_reactiv_note}'
    )
    # تحديث نفس رسالة التقدم بالنتيجة النهائية، أو إرسال رسالة جديدة إن تعذّر التحديث
    if _live_msg:
        try:
            await context.bot.edit_message_text(
                _final_text,
                chat_id=requester_id,
                message_id=_live_msg.message_id,
                parse_mode='HTML'
            )
        except Exception:
            try:
                await context.bot.send_message(requester_id, _final_text, parse_mode='HTML')
            except Exception:
                pass
    else:
        try:
            await context.bot.send_message(requester_id, _final_text, parse_mode='HTML')
        except Exception:
            pass
    await _maybe_send_to_group(
        context.bot, requester_id,
        f'🔑 اشتراك إجباري اكتمل | 👤 {requester_id} | @{bot_user} | ✅{done} ❌{failed} 🔄{reactivated} 🔁{replaced_ms} | استرداد {refunded_pts:,}نقطة',
        parse_mode='Markdown'
    )
    # ─── إشعار المالك بالتفاصيل الكاملة (فاشل/مكمل/مكرر/بديل) مع المصدر ───
    if OWNER_ID and requester_id != OWNER_ID:
        try:
            _src_lbl = '👤 من عضو — بوت اجباري'
            await context.bot.send_message(
                OWNER_ID,
                f'📊 <b>تقرير الاشتراك الإجباري</b>\n'
                f'📌 {_src_lbl}\n'
                f'🆔 طلب المستخدم: <code>{requester_id}</code> | @{bot_user}\n\n'
                f'✅ <b>المنجز:</b> {done}\n'
                f'🔄 <b>المكرر (مفعّل مسبقاً):</b> {reactivated}\n'
                f'❌ <b>الملغي (إجمالي):</b> {failed}\n'
                f'🔁 <b>الحسابات البديلة المستخدمة:</b> {replaced_ms}'
                + (f'\n💰 استرداد تلقائي: {refunded_pts:,} نقطة' if refunded_pts > 0 else ''),
                parse_mode='HTML'
            )
        except Exception:
            pass

# ══════════════════════════════════════════════════════════
# إحالة بوت اجباري — الدوال الكاملة
# ══════════════════════════════════════════════════════════

async def _forced_ref_start(update, context, user, q, is_own, with_ai: bool = False):
    """الشاشة الأولى — يختار المستخدم طريقة الدفع (نجوم أو نقاط)."""
    if with_ai:
        vis     = get_setting('forced_ref_ai_visible') == '1'
        tgl     = '🔒 إخفاء من الأعضاء' if vis else '🔓 إظهار للأعضاء'
        visnote = '👁 مرئية للأعضاء' if vis else '🔒 مخفية (مالك فقط)'
        title   = '🤖 إحالة بميزة تحقق'
        tgl_cb  = 'os:toggle_forced_ref_ai_visible'
        ai_flag = '1'
    else:
        vis     = get_setting('forced_ref_visible') == '1'
        tgl     = '🔒 إخفاء من الأعضاء' if vis else '🔓 إظهار للأعضاء'
        visnote = '👁 مرئية للأعضاء' if vis else '🔒 مخفية (مالك فقط)'
        title   = '🔑 إحالة بوت فقط'
        tgl_cb  = 'os:toggle_forced_ref_visible'
        ai_flag = '0'
    context.user_data['forced_ref_draft'] = {'use_ai': with_ai, 'payment_method': None}
    own_row = [[InlineKeyboardButton(tgl, callback_data=tgl_cb)]] if user.id == OWNER_ID else []
    await q.edit_message_text(
        f'*{title}*\n\n'
        f'📌 {visnote}\n\n'
        f'اختر طريقة الدفع:',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(own_row + [
            [InlineKeyboardButton('⭐ بنجوم', callback_data=f'forced_ref_pm:stars:{ai_flag}')],
            [InlineKeyboardButton('💎 بنقاط', callback_data=f'forced_ref_pm:points:{ai_flag}')],
            [InlineKeyboardButton('🔙 رجوع', callback_data='main_menu')],
        ])
    )

async def _forced_ref_go_channels(q_or_msg, context, draft, *, edit: bool):
    """بعد اختيار طريقة الدفع — يعرض تفاصيل السعر والعدد الأعلى، ثم يطلب القنوات."""
    use_ai  = draft.get('use_ai', False)
    pm      = draft.get('payment_method', 'points')
    avail   = get_forced_ref_account_count()

    if pm == 'stars':
        cp_ch        = int(get_setting('forced_ref_channel_stars_ai' if use_ai else 'forced_ref_channel_stars_no_ai') or ('35' if use_ai else '25'))
        max_qty      = (avail // 2) * 2 if use_ai else avail  # زوجي فقط عند AI
        stars_label  = '1.5 نجمة/حساب' if use_ai else '1 نجمة/حساب'
        even_note    = '\n⚠️ يُقبل فقط أعداد زوجية (٢ ، ٤ ، ٦ ...)' if use_ai else ''
        price_block  = (
            f'┌─────────────────────\n'
            f'│ ⭐ *سعر الإحالة الوحدة:* {stars_label}\n'
            f'│ 💎 *أسعار القناة الإجبارية المضافة:* {cp_ch} نقطة لكل قناة\n'
            f'│ 📊 *الحد الأعلى:* {max_qty} حساب{even_note}\n'
            f'└─────────────────────'
        )
    else:
        bp      = int(get_setting('forced_ref_ai_base_price' if use_ai else 'forced_ref_base_price') or ('300' if use_ai else '250'))
        cp      = int(get_setting('forced_ref_channel_price') or '25')
        max_qty = avail
        price_block = (
            f'┌─────────────────────\n'
            f'│ 💎 *سعر الإحالة الوحدة:* {bp} نقطة\n'
            f'│ 💎 *أسعار القناة الإجبارية المضافة:* {cp} نقطة لكل قناة\n'
            f'│ 📊 *الحد الأعلى:* {max_qty} حساب\n'
            f'└─────────────────────'
        )

    txt = (
        f'{price_block}\n\n'
        f'📢 *أرسل معرفات القنوات الإجبارية:*\n'
        f'مثال: `@chan1 @chan2`\n\n'
        f'أو اضغط تخطي إن لم توجد قنوات.'
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('⏭️ تخطي (بدون قنوات)', callback_data='forced_ref_skip_channels')],
        [InlineKeyboardButton('🔙 إلغاء', callback_data='main_menu')],
    ])
    if edit:
        await q_or_msg.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    else:
        await q_or_msg.reply_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

async def _forced_ref_handle_channels(update, context):
    raw   = update.message.text.strip()
    draft = context.user_data.setdefault('forced_ref_draft', {})
    draft['channels'] = '' if raw.lower() in ('تخطي', 'skip', '-') else raw
    context.user_data['state'] = 'await_forced_ref_link'
    chs_preview = draft['channels'] or 'لا يوجد'
    await update.message.reply_text(
        f'✅ القنوات: `{chs_preview}`\n\n'
        f'📎 *أرسل رابط البوت:*\n'
        f'`t.me/BotUsername?start=CODE`\n'
        f'أو: `@BotUsername CODE`',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 إلغاء', callback_data='main_menu')]])
    )

async def _forced_ref_handle_link(update, context):
    raw = update.message.text.strip()
    try:
        if 't.me/' in raw or 'telegram.me/' in raw:
            from urllib.parse import urlparse, parse_qs
            parsed  = urlparse(raw if raw.startswith('http') else 'https://' + raw)
            bot_user = parsed.path.strip('/')
            start_p  = parse_qs(parsed.query).get('start', [''])[0]
        else:
            parts    = raw.split(None, 1)
            bot_user = parts[0].lstrip('@')
            start_p  = parts[1] if len(parts) > 1 else ''
        if not bot_user:
            raise ValueError('اسم البوت فارغ')
        draft = context.user_data.setdefault('forced_ref_draft', {})
        draft['bot_user'] = bot_user
        draft['start_p']  = start_p
        context.user_data['state'] = 'await_forced_ref_qty'
        avail = get_forced_ref_account_count()
        _draft_link = context.user_data.get('forced_ref_draft', {})
        _use_ai_link = _draft_link.get('use_ai', False)
        _pm_link     = _draft_link.get('payment_method', 'points')
        _even_note   = '\n⚠️ *يُقبل فقط أعداد زوجية* (بسبب سعر 1.5 نجمة/حساب)' if (_use_ai_link and _pm_link == 'stars') else ''
        _max_note    = avail if not (_use_ai_link and _pm_link == 'stars') else (avail // 2) * 2
        await update.message.reply_text(
            f'✅ البوت: `@{bot_user}`\n\n'
            f'📊 المتاح: *{avail}* حساب\n\n'
            f'🔢 *أرسل عدد الحسابات (1 – {_max_note}):*{_even_note}',
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 إلغاء', callback_data='main_menu')]])
        )
    except Exception as _e:
        import logging as _lg
        _lg.getLogger(__name__).warning(f'forced_ref_handle_link error: {_e}')
        await update.message.reply_text(
            '⚠️ تعذّر قراءة الرابط. أرسل اسم البوت هكذا:\n`@BotUsername` أو `t.me/BotUsername`',
            parse_mode=ParseMode.MARKDOWN
        )

async def _forced_ref_handle_qty(update, context, user):
    try:
        qty = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text('⚠️ أرسل رقماً صحيحاً.')
        return
    avail = get_forced_ref_account_count()
    draft    = context.user_data.setdefault('forced_ref_draft', {})
    use_ai   = draft.get('use_ai', False)
    pm       = draft.get('payment_method', 'points')
    # بتحقق + نجوم: يُقبل فقط أعداد زوجية (لأن السعر 1.5 نجمة/حساب)
    if use_ai and pm == 'stars' and qty % 2 != 0:
        await update.message.reply_text(
            '⚠️ في وضع *التحقق بالنجوم* يُقبل فقط *أعداد زوجية* (٢، ٤، ٦...)\n'
            'السبب: سعر الحساب ١.٥ نجمة ولا يمكن كسر النجمة في تيليغرام.',
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if qty < 1 or qty > avail:
        await update.message.reply_text(f'⚠️ الكمية خارج النطاق (1 – {avail}).')
        return
    channels = draft.get('channels', '')
    ch_count = len([t for t in channels.split() if t.strip()]) if channels else 0
    bp  = int(get_setting('forced_ref_ai_base_price' if use_ai else 'forced_ref_base_price') or ('300' if use_ai else '250'))
    cp  = int(get_setting('forced_ref_channel_price') or '25')
    # القنوات دائماً بالنقاط بغض النظر عن طريقة الدفع
    cp_ch_key = 'forced_ref_channel_stars_ai' if use_ai else 'forced_ref_channel_stars_no_ai'
    cp_ch = int(get_setting(cp_ch_key) or ('35' if use_ai else '25'))  # نقاط/قناة
    cost_pts_channels = ch_count * cp_ch   # تكلفة القنوات بالنقاط دائماً
    cost_pts_each = bp + (ch_count * cp / qty if qty else 0)  # متوسط تكلفة الحساب مع توزيع رسوم القنوات
    # النجوم للحسابات فقط — القنوات تُخصم من النقاط
    if use_ai:
        # 1.5 نجمة/حساب → لكل حسابين = 3 نجوم (أعداد زوجية مضمونة)
        total_stars = qty * 3 // 2
    else:
        total_stars = qty  # 1 نجمة/حساب
    total_pts = (bp * qty) + (ch_count * cp)  # الحسابات × العدد + القنوات مرة واحدة لكل قناة
    draft['qty']              = qty
    draft['cost']             = total_pts
    draft['cost_stars']       = total_stars
    draft['cost_pts_channels'] = cost_pts_channels  # نقاط القنوات عند الدفع بالنجوم
    db_user = get_user(user.id)
    pts     = db_user['points'] if db_user else 0
    context.user_data['state'] = 'confirm_forced_ref'
    _bu_f   = draft.get('bot_user', '')
    _sp_f   = draft.get('start_p', '')
    _code_f = f'`{_sp_f}`' if _sp_f else 'بدون كود'
    ch_line = f'\n📢 القنوات: `{channels}`' if channels else ''
    _title_conf = '🤖 تأكيد إحالة بميزة تحقق:' if use_ai else '🔑 تأكيد إحالة بوت فقط:'
    if pm == 'stars':
        if ch_count > 0:
            cost_line = (f'⭐ التكلفة: *{total_stars:,} نجمة* (للحسابات)\n'
                         f'💎 نقاط القنوات: *{cost_pts_channels:,} نقطة* تُخصم من رصيدك (رصيدك: {pts:,})')
            lbl_confirm = f'✅ تأكيد ({total_stars:,}⭐ + {cost_pts_channels:,}💎)'
        else:
            cost_line = f'⭐ التكلفة الإجمالية: *{total_stars:,} نجمة*'
            lbl_confirm = f'✅ تأكيد ({total_stars:,} نجمة)'
        btn_confirm = InlineKeyboardButton(lbl_confirm, callback_data='confirm_forced_ref:stars')
    else:
        cost_line = f'💎 التكلفة الإجمالية: *{total_pts:,} نقطة* (رصيدك: {pts:,})'
        btn_confirm = InlineKeyboardButton(f'✅ تأكيد ({total_pts:,} نقطة)', callback_data='confirm_forced_ref:yes')
    await update.message.reply_text(
        f'📋 *{_title_conf}*\n\n'
        f'📌 `@{_bu_f}` | كود: {_code_f}{ch_line}\n'
        f'🔢 {qty} حساب\n'
        f'{cost_line}\n\n'
        f'⚡ الحسابات المستخدمة: غير معروضة وغير مباعة فقط\n'
        f'💡 الفاشلة: تُعوَّض دائماً | المكررة: تُعوَّض بالنجوم فقط',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [btn_confirm],
            [InlineKeyboardButton('❌ إلغاء', callback_data='confirm_forced_ref:no')],
        ])
    )

async def _handle_confirm_forced_ref(update, context, user, q, is_own, data):
    action = data.split(':')[1]
    if context.user_data.get('state') != 'confirm_forced_ref':
        await q.edit_message_text('⚠️ انتهت صلاحية الطلب.', reply_markup=main_menu_kb(is_own))
        return
    draft = context.user_data.get('forced_ref_draft', {})
    if action == 'no':
        context.user_data['state'] = 'main_menu'
        await q.edit_message_text('❌ تم إلغاء الطلب.', reply_markup=main_menu_kb(is_own))
        return
    bot_user    = draft.get('bot_user', '')
    start_p     = draft.get('start_p', '')
    channels    = draft.get('channels', '')
    qty         = draft.get('qty', 0)
    total       = draft.get('cost', 0)
    total_stars = draft.get('cost_stars', 0)
    if not bot_user or qty < 1:
        context.user_data['state'] = 'main_menu'
        await q.edit_message_text('⚠️ بيانات غير مكتملة.', reply_markup=main_menu_kb(is_own))
        return
    _dbu = get_user(user.id)
    if _dbu and _dbu.get('referral_points_blocked'):
        await q.edit_message_text('🔒 حسابك موقوف. تواصل مع المالك.', reply_markup=main_menu_kb(is_own))
        return

    # ─── دفع بالنجوم ───
    if action == 'stars':
        if total_stars < 1:
            await q.edit_message_text('⚠️ تعذّر حساب تكلفة النجوم.', reply_markup=main_menu_kb(is_own))
            return
        _use_ai_s = draft.get('use_ai', False)
        cost_pts_ch = draft.get('cost_pts_channels', 0)
        # إذا كانت هناك قنوات → اخصم نقاطها مسبقاً من رصيد المستخدم
        if cost_pts_ch > 0:
            if not deduct_points(user.id, cost_pts_ch):
                await q.edit_message_text(
                    f'❌ نقاطك غير كافية لتغطية تكلفة القنوات ({cost_pts_ch:,} نقطة).',
                    reply_markup=main_menu_kb(is_own)
                )
                return
        _code_fr  = f'`{start_p}`' if start_p else 'بدون كود'
        _title_s  = '🤖 إحالة بتحقق' if _use_ai_s else '🔑 إحالة بدون تحقق'
        # payload: forced_ref_stars:{user_id}:{qty}:{total_stars}:{use_ai}:{cost_pts_channels}
        payload   = f'forced_ref_stars:{user.id}:{qty}:{total_stars}:{int(_use_ai_s)}:{cost_pts_ch}'
        await q.delete_message()
        await context.bot.send_invoice(
            chat_id=user.id,
            title=_title_s,
            description=f'{qty} حساب | @{bot_user} {_code_fr} | {channels or "بدون قنوات"}',
            payload=payload,
            provider_token='',
            currency='XTR',
            prices=[LabeledPrice(f'إحالة {qty} حساب', total_stars)],
        )
        return

    # ─── دفع بالنقاط ───
    if not deduct_points(user.id, total):
        await q.edit_message_text('❌ نقاطك غير كافية.', reply_markup=main_menu_kb(is_own))
        context.user_data['state'] = 'main_menu'
        return
    code = next_order_code(user.id)
    with db_conn() as c:
        row = c.execute(
            'INSERT INTO forced_ref_orders '
            '(user_id,bot_username,start_param,channels,quantity,cost_points,cost_stars,payment_method,status,order_code) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
            (user.id, bot_user, start_p, channels, qty, total, 0, 'points', 'pending', code)
        ).fetchone()
        order_id = row['id']
    context.user_data['state'] = 'main_menu'
    context.user_data.pop('forced_ref_draft', None)
    _code_fr = f'`{start_p}`' if start_p else 'بدون كود'
    ch_line  = f'\n📢 القنوات: `{channels}`' if channels else ''
    await q.edit_message_text(
        f'✅ *تم استلام طلبك!*\n\n'
        f'📌 `@{bot_user}` | كود: {_code_fr}{ch_line}\n'
        f'🔢 {qty} حساب | 💎 {total:,} نقطة\n'
        f'🎫 كود: `{code}`\n\n'
        f'⏳ سيبدأ التنفيذ قريباً وستصلك إشعار عند الانتهاء.',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb(is_own)
    )
    await _maybe_send_to_group(
        context.bot, user.id,
        f'تم إحالة بوت إجباري العدد {qty}',
        parse_mode='Markdown'
    )
    import asyncio as _aio
    _use_ai = draft.get('use_ai', False)
    _aio.create_task(_run_forced_ref_order(order_id, bot_user, start_p, channels, qty, user.id, context, use_ai=_use_ai, payment_method='points', cost_stars=0))

# ═══════════════════════════════════════════════════════════════════════════
# ══ إحالة إجبارية للمشرف — يستخدم حساباته الخاصة فقط، بدون تكلفة ══
# ═══════════════════════════════════════════════════════════════════════════

async def _sv_forced_ref_start(update, context, user, q, with_ai: bool = False):
    """الشاشة الأولى للمشرف — يختار نوع الإحالة (تحقق أم بدون)."""
    sv_accounts = get_supervisor_available_accounts(user.id)
    avail = len(sv_accounts)
    if avail == 0:
        await q.edit_message_text(
            "⚠️ *لا توجد حسابات متاحة*\n\n"
            "أضف حسابات أولاً من قسم ➕ إضافة حساب جديد.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة المشرف", callback_data="sv:panel")]])
        )
        return
    context.user_data['sv_forced_ref_draft'] = {'use_ai': with_ai}
    title = '🤖 إحالة بميزة تحقق' if with_ai else '🔑 إحالة بوت فقط'
    await q.edit_message_text(
        f'*{title}*\n\n'
        f'📊 حساباتك المتاحة: *{avail}*\n\n'
        f'📢 *أرسل معرفات القنوات الإجبارية:*\n'
        f'مثال: `@chan1 @chan2`\n\n'
        f'أو اضغط تخطي إن لم توجد قنوات.',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('⏭️ تخطي (بدون قنوات)', callback_data='sv_forced_ref_skip_channels')],
            [InlineKeyboardButton('🔙 رجوع', callback_data='sv:forced_ref')],
        ])
    )
    context.user_data['state'] = 'sv_await_forced_ref_channels'

async def _sv_forced_ref_handle_channels(update, context):
    raw   = update.message.text.strip()
    draft = context.user_data.setdefault('sv_forced_ref_draft', {})
    draft['channels'] = '' if raw.lower() in ('تخطي', 'skip', '-') else raw
    sv_accounts = get_supervisor_available_accounts(update.effective_user.id)
    avail = len(sv_accounts)
    use_ai = draft.get('use_ai', False)
    even_note = '\n⚠️ يُقبل فقط أعداد زوجية (٢، ٤، ٦ ...)' if use_ai else ''
    context.user_data['state'] = 'sv_await_forced_ref_link'
    await update.message.reply_text(
        f'✅ تم تسجيل القنوات.\n\n'
        f'📊 المتاح: *{avail}* حساب{even_note}\n\n'
        f'📎 *أرسل رابط البوت:*\n'
        f'`t.me/BotUsername?start=CODE`\n'
        f'أو: `@BotUsername CODE`',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 إلغاء', callback_data='sv:panel')]])
    )

async def _sv_forced_ref_handle_link(update, context):
    text  = update.message.text.strip()
    draft = context.user_data.setdefault('sv_forced_ref_draft', {})
    import re as _re
    m = _re.search(r't\.me/([A-Za-z0-9_]+)\?start=(\S+)', text)
    if m:
        draft['bot_user'] = m.group(1)
        draft['start_p']  = m.group(2)
    else:
        parts = text.lstrip('@').split()
        draft['bot_user'] = parts[0] if parts else ''
        draft['start_p']  = parts[1] if len(parts) > 1 else ''
    if not draft.get('bot_user'):
        await update.message.reply_text('⚠️ لم أتمكن من قراءة رابط البوت. أعد المحاولة.')
        return
    sv_accounts = get_supervisor_available_accounts(update.effective_user.id)
    avail = len(sv_accounts)
    use_ai = draft.get('use_ai', False)
    even_note = '\n⚠️ يُقبل فقط أعداد زوجية (٢، ٤، ٦ ...)' if use_ai else ''
    context.user_data['state'] = 'sv_await_forced_ref_qty'
    _bu = draft['bot_user']
    _sp = draft.get('start_p', '')
    _code_lbl = f'`{_sp}`' if _sp else 'بدون كود'
    await update.message.reply_text(
        f'✅ البوت: `@{_bu}` | كود: {_code_lbl}\n\n'
        f'📊 المتاح: *{avail}* حساب{even_note}\n\n'
        f'🔢 *أرسل عدد الحسابات (1 – {avail}):*',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 إلغاء', callback_data='sv:panel')]])
    )

async def _sv_forced_ref_handle_qty(update, context, user):
    try:
        qty = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text('⚠️ أرسل رقماً صحيحاً.')
        return
    draft    = context.user_data.setdefault('sv_forced_ref_draft', {})
    use_ai   = draft.get('use_ai', False)
    sv_accounts = get_supervisor_available_accounts(user.id)
    avail = len(sv_accounts)
    if use_ai and qty % 2 != 0:
        await update.message.reply_text(
            '⚠️ في وضع *التحقق* يُقبل فقط *أعداد زوجية* (٢، ٤، ٦...).',
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if qty < 1 or qty > avail:
        await update.message.reply_text(f'⚠️ الكمية خارج النطاق (1 – {avail}).')
        return
    draft['qty'] = qty
    channels = draft.get('channels', '')
    ch_count = len([t for t in channels.split() if t.strip()]) if channels else 0
    _bu   = draft.get('bot_user', '')
    _sp   = draft.get('start_p', '')
    _code_lbl = f'`{_sp}`' if _sp else 'بدون كود'
    ch_line   = f'\n📢 القنوات: `{channels}`' if channels else ''
    _title    = '🤖 تأكيد إحالة بميزة تحقق:' if use_ai else '🔑 تأكيد إحالة بوت فقط:'
    context.user_data['state'] = 'sv_confirm_forced_ref'
    await update.message.reply_text(
        f'📋 *{_title}*\n\n'
        f'📌 `@{_bu}` | كود: {_code_lbl}{ch_line}\n'
        f'🔢 {qty} حساب من حساباتك الخاصة\n'
        f'💡 مجاني — يستخدم حساباتك أنت فقط\n\n'
        f'⚡ الفاشلة: تُتجاوز تلقائياً',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('✅ تأكيد وتشغيل', callback_data='sv_forced_ref_confirm:yes')],
            [InlineKeyboardButton('❌ إلغاء',         callback_data='sv_forced_ref_confirm:no')],
        ])
    )

async def _run_sv_forced_ref_order(bot_user, start_p, channels, quantity, supervisor_id, context, use_ai: bool = False):
    """تنفيذ الإحالة الإجبارية باستخدام حسابات المشرف الخاصة فقط."""
    import random as _rnd
    import asyncio as _aio_sv

    sv_accounts = get_supervisor_available_accounts(supervisor_id)
    pool = sv_accounts[:quantity]

    done = 0
    failed = 0
    reactivated = 0
    _done_phones    = []
    _reactiv_phones = []
    _fail_reasons   = []

    _all_channels = channels or ''
    _ai_label     = ' 🤖' if use_ai else ''

    # رسالة البداية
    try:
        msg = await context.bot.send_message(
            chat_id=supervisor_id,
            text=f'⏳ *بدأت الإحالة الإجبارية{_ai_label}*\n\n'
                 f'📌 `@{bot_user}` | كود: `{start_p or "بدون"}`\n'
                 f'🔢 {quantity} حساب | 0/{quantity} منجز...',
            parse_mode=ParseMode.MARKDOWN
        )
        progress_msg_id = msg.message_id
    except Exception:
        progress_msg_id = None

    def _progress_text(idx: int) -> str:
        return (
            f'⏳ *جارية الإحالة الإجبارية{_ai_label}*\n\n'
            f'📌 `@{bot_user}`\n'
            f'🔢 {idx}/{quantity} منجز | ✅ {done} | 🔁 {reactivated} | ❌ {failed}'
        )

    for idx, num in enumerate(pool, 1):
        if done + reactivated >= quantity:
            break
        try:
            ok, reactiv, detail = await do_referral_for_number(
                num['phone_number'], num['session_string'],
                bot_user, start_p,
                mandatory_channels=_all_channels,
                folder_link='',
                use_ai=use_ai,
                leave_channels_after=True,
                stock_id=0,
            )
        except Exception as _ex:
            ok = False; reactiv = False
            detail = f'[{type(_ex).__name__}] {str(_ex)[:80]}'

        if ok and reactiv:
            reactivated += 1
            _reactiv_phones.append(num['phone_number'])
        elif ok:
            done += 1
            _done_phones.append(num['phone_number'])
        else:
            failed += 1
            _fail_reasons.append(f"`{num['phone_number']}`: {detail[:60]}")

        # تحديث رسالة التقدم كل 3 حسابات
        if progress_msg_id and idx % 3 == 0:
            try:
                await context.bot.edit_message_text(
                    chat_id=supervisor_id,
                    message_id=progress_msg_id,
                    text=_progress_text(idx),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

        # تأخير عشوائي بين الحسابات
        await _aio_sv.sleep(_rnd.uniform(5, 15))

    # ── رسالة النهاية ──
    fail_lines = '\n'.join(_fail_reasons[:10]) if _fail_reasons else ''
    fail_block = f'\n\n❌ *أسباب الفشل:*\n{fail_lines}' if fail_lines else ''
    final_text = (
        f'✅ *اكتملت الإحالة الإجبارية{_ai_label}*\n\n'
        f'📌 `@{bot_user}` | كود: `{start_p or "بدون"}`\n'
        f'🔢 المطلوب: {quantity}\n'
        f'✅ منجز: {done}\n'
        f'🔁 مكرر (كان مفعّلاً): {reactivated}\n'
        f'❌ فاشل: {failed}'
        f'{fail_block}'
    )
    try:
        if progress_msg_id:
            await context.bot.edit_message_text(
                chat_id=supervisor_id,
                message_id=progress_msg_id,
                text=final_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة المشرف", callback_data="sv:panel")]])
            )
        else:
            await context.bot.send_message(
                chat_id=supervisor_id,
                text=final_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة المشرف", callback_data="sv:panel")]])
            )
    except Exception:
        pass

async def _run_forced_ref_order(order_id, bot_user, start_p, channels, quantity, requester_id, context,
                               use_ai: bool = False, payment_method: str = 'points', cost_stars: int = 0):
    import random as _rnd
    import time as _time

    # ── حماية: إذا استهدف المستخدم (غير المالك) البوت نفسه → طلب وهمي مكتمل بدون تعويض ──
    _clean_bot_target = bot_user.lower().lstrip("@").strip()
    if _OWN_BOT_USERNAME and _clean_bot_target == _OWN_BOT_USERNAME and requester_id != OWNER_ID:
        with db_conn() as _sc:
            _sc.execute(
                "UPDATE forced_ref_orders SET status='done', done_count=%s WHERE id=%s",
                (quantity, order_id)
            )
        _ai_label_s = ' 🤖' if use_ai else ''
        try:
            await context.bot.send_message(
                requester_id,
                f'✅ <b>اكتملت إحالة البوت الإجبارية{_ai_label_s}!</b>\n'
                f'📌 @{bot_user}\n\n'
                f'✅ تم: <b>{quantity}</b>  |  ❌ فشل: <b>0</b>',
                parse_mode='HTML'
            )
        except Exception:
            pass
        return

    with db_conn() as c:
        c.execute("UPDATE forced_ref_orders SET status='running' WHERE id=%s", (order_id,))
        rows = c.execute(
            "SELECT id,phone_number,session_string FROM number_stock"
            " WHERE session_string IS NOT NULL AND deleted_at IS NULL AND assigned_to IS NULL"
            " AND ever_sold IS NOT TRUE AND can_send_code IS TRUE AND last_authorized IS NOT FALSE"
            " AND frozen_at IS NULL AND forced_ref_excluded IS NOT TRUE"
            " ORDER BY id"
        ).fetchall()
        # جلب القنوات الإجبارية العامة للبوت — الحسابات تنضم إليها أولاً قبل الضغط على الرابط
        _global_ch_rows = c.execute(
            "SELECT channel_username FROM mandatory_channels WHERE active=1 AND funding_type='mandatory'"
        ).fetchall()
    _global_ch_str = ' '.join(
        ('@' + r['channel_username'].lstrip('@')) for r in _global_ch_rows if r.get('channel_username')
    )
    with db_conn() as _cfm:
        _order_meta_f = _cfm.execute(
            "SELECT cost_points, cost_stars, quantity FROM forced_ref_orders WHERE id=%s", (order_id,)
        ).fetchone()
    _total_cost_pts   = int(_order_meta_f["cost_points"] or 0) if _order_meta_f else 0
    _total_cost_stars = int(_order_meta_f["cost_stars"]  or cost_stars) if _order_meta_f else cost_stars
    _qty_total_f      = int(_order_meta_f["quantity"]    or 1) if _order_meta_f else max(1, quantity)
    _cost_pts_each    = round(_total_cost_pts   / _qty_total_f) if _qty_total_f else 0
    _cost_stars_each  = round(_total_cost_stars / _qty_total_f) if _qty_total_f else 0

    # سعر النجمة بالنقاط (للتعويض عند الدفع بنجوم — كل النجوم المدفوعة تُحوَّل نقاطاً)
    _star_rate = int(get_setting('star_to_points') or '250')

    # دمج القنوات الإجبارية العامة + قنوات المستخدم المحددة في الطلب
    _all_channels = ' '.join(filter(None, [_global_ch_str, channels or ''])).strip()
    nums = [dict(r) for r in rows]
    _rnd.shuffle(nums)
    pool     = list(nums)      # كامل المخزون المتاح بترتيب عشوائي
    pool_idx = quantity        # أول حساب بديل يبدأ بعد الدفعة الأولى
    done = failed = reactivated = 0
    replaced = 0               # عدد الحسابات البديلة التي استُخدمت
    refunded_pts = 0
    _fail_reasons: list = []   # أسباب الفشل — تُعرض في الرسالة النهائية
    _done_phones:   list = []  # أرقام الحسابات الناجحة
    _reactiv_phones: list = [] # أرقام الحسابات المكررة
    _fail_phones:   list = []  # (phone, stock_id, سبب) الحسابات الفاشلة

    # ─── رسالة التقدم الحي ───
    _live_msg_f       = None
    _last_edit_time_f = 0.0
    _EDIT_INTERVAL_F  = 3.0   # ثوانٍ بين كل تحديث للرسالة (تجنّب Rate-Limit)
    _ai_label = ' 🤖' if use_ai else ''

    def _forced_ref_progress_text(idx: int) -> str:
        parts = []
        if done > 0:        parts.append(f'{done} ✅ تم')
        if failed > 0:      parts.append(f'{failed} ❌ فشل')
        if reactivated > 0: parts.append(f'{reactivated} 🔄 مكرر')
        status = '  |  '.join(parts) if parts else '⏳ جاري...'
        return (
            f'⏳ <b>جاري تنفيذ الإحالة الإجبارية{_ai_label}...</b>\n'
            f'📌 @{bot_user} | {quantity} حساب\n\n'
            f'<b>حساب {idx}/{quantity}</b> — {status}'
        )

    try:
        _live_msg_f = await context.bot.send_message(
            requester_id,
            f'⏳ <b>جاري تنفيذ الإحالة الإجبارية{_ai_label}...</b>\n📌 @{bot_user} | {quantity} حساب\n\nحساب 0/{quantity} — ⏳ جاري...',
            parse_mode='HTML'
        )
        _last_edit_time_f = _time.monotonic()
    except Exception:
        pass

    import asyncio as _aio2
    import random as _rnd2

    # الأخطاء الدائمة — لا فائدة من إعادة المحاولة
    _PERM_ERRORS = (
        "AuthKeyUnregistered", "SessionRevoked", "SessionExpired",
        "UserDeactivated", "AccountBanned", "PhoneNumberBanned",
        "AuthKeyDuplicated", "جلسة منتهية",
    )

    def _is_permanent(detail: str) -> bool:
        return any(k in detail for k in _PERM_ERRORS)

    # ── معالجة الحسابات مع دعم الاستبدال التلقائي الفوري ──
    # عند فشل أي حساب (لأي سبب) يُستبدل فوراً بحساب بديل من المخزون
    # يستمر حتى يكتمل العدد المطلوب أو ينفد المخزون
    _pending = pool[:quantity]   # الدفعة الأولى

    while _pending and done + reactivated < quantity:
        _cycle = list(_pending)
        _pending = []            # ستُملأ بالحسابات البديلة عند الحاجة

        for _idx_f, num in enumerate(_cycle, 1):
            if done + reactivated >= quantity:
                break        # ✅ اكتمل الهدف — لا حاجة لمزيد من المعالجة

            try:
                ok, reactiv, _detail = await do_referral_for_number(
                    num['phone_number'], num['session_string'],
                    bot_user, start_p,
                    mandatory_channels=_all_channels,
                    folder_link='',
                    use_ai=use_ai,
                    leave_channels_after=True,
                    stock_id=num.get('id', 0),
                )
            except Exception as _ex:
                ok = False; reactiv = False
                _detail = f'[{type(_ex).__name__}] {str(_ex)[:80]}'

            if ok and reactiv:
                with db_conn() as c:
                    c.execute("UPDATE forced_ref_orders SET reactivated_count=reactivated_count+1 WHERE id=%s", (order_id,))
                reactivated += 1
                _reactiv_phones.append(num['phone_number'])
            elif ok:
                with db_conn() as c:
                    c.execute("UPDATE forced_ref_orders SET done_count=done_count+1 WHERE id=%s", (order_id,))
                done += 1
                _done_phones.append(num['phone_number'])
            else:
                # فشل فوري — تخطّ واسحب حساباً بديلاً مباشرةً
                with db_conn() as c:
                    c.execute("UPDATE forced_ref_orders SET failed_count=failed_count+1 WHERE id=%s", (order_id,))
                failed += 1
                _fail_reasons.append(f"{num['phone_number']}: {_detail}")
                _fail_phones.append((num['phone_number'], num.get('id', 0), _detail))
                # ── سحب حساب بديل إذا لم يكتمل الهدف بعد ──
                if done + reactivated < quantity and pool_idx < len(pool):
                    _pending.append(pool[pool_idx])
                    pool_idx += 1
                    replaced += 1

            # ─── تحديث رسالة التقدم الحي ───
            _now_f = _time.monotonic()
            _total_done = done + failed + reactivated
            if _live_msg_f and (_now_f - _last_edit_time_f >= _EDIT_INTERVAL_F or _total_done == quantity):
                try:
                    _repl_note  = f' | 🔁 بديل: {replaced}' if replaced > 0 else ''
                    await context.bot.edit_message_text(
                        _forced_ref_progress_text(_total_done) + _repl_note,
                        chat_id=requester_id,
                        message_id=_live_msg_f.message_id,
                        parse_mode='HTML'
                    )
                    _last_edit_time_f = _now_f
                except Exception:
                    pass

            # تأخير بين الحسابات (٤٥-٩٠ ثانية لتفريق الحسابات بأمان)
            if _idx_f < len(_cycle):
                await _aio2.sleep(_rnd2.uniform(45, 90))

        # إشعار المستخدم بوجود حسابات بديلة قيد التنفيذ
        if _pending and _live_msg_f:
            try:
                await context.bot.edit_message_text(
                    _forced_ref_progress_text(done + failed + reactivated) +
                    f'\n🔁 جاري تجربة {len(_pending)} حساب بديل...',
                    chat_id=requester_id,
                    message_id=_live_msg_f.message_id,
                    parse_mode='HTML'
                )
            except Exception:
                pass

    # ─── حساب التعويضات ───
    # الكميات غير المكتملة (لم يُجد لها بديل): تُعوَّض دائماً
    unfulfilled = max(0, quantity - done - reactivated)
    if unfulfilled > 0:
        if payment_method == 'stars' and _cost_stars_each > 0:
            refunded_pts = unfulfilled * (_cost_stars_each * _star_rate)
        elif _cost_pts_each > 0:
            refunded_pts = unfulfilled * _cost_pts_each
        if refunded_pts > 0:
            add_points(requester_id, refunded_pts)

    # المكررة (إعادة تفعيل): تُعوَّض فقط عند الدفع بنجوم
    reactiv_refunded_pts = 0
    if reactivated > 0 and payment_method == 'stars' and _cost_stars_each > 0:
        reactiv_refunded_pts = reactivated * (_cost_stars_each * _star_rate)
        add_points(requester_id, reactiv_refunded_pts)

    with db_conn() as c:
        c.execute("UPDATE forced_ref_orders SET status='done' WHERE id=%s", (order_id,))

    # ─── رسالة الإشعار النهائية ───
    _refund_parts = []
    if refunded_pts > 0:
        _refund_parts.append(f'غير مكتمل: {refunded_pts:,} نقطة ({unfulfilled} حساب)')
    if reactiv_refunded_pts > 0:
        _refund_parts.append(f'المكررة: {reactiv_refunded_pts:,} نقطة ({reactivated} حساب)')
    _refund_line = '\n💰 <b>التعويض:</b> ' + ' | '.join(_refund_parts) if _refund_parts else ''

    _stars_note = ''
    if payment_method == 'stars' and reactivated > 0:
        _stars_note = '\n✅ <i>لأنك دفعت بالنجوم، تم تعويض المكررة أيضاً (250 نقطة لكل نجمة مدفوعة)</i>'
    elif payment_method != 'stars' and reactivated > 0:
        _stars_note = '\n⚠️ <i>الإحالات المكررة لا تُعوَّض عند الدفع بالنقاط</i>'

    _replaced_note = f'\n🔁 <i>استُبدل {replaced} حساب فاشل بحسابات أخرى</i>' if replaced > 0 else ''

    # ─── بناء قوائم الأرقام لكل فئة ───
    def _phones_block(phones: list, limit: int = 30) -> str:
        if not phones:
            return ''
        lines = '\n'.join(f'  • <code>{p}</code>' for p in phones[:limit])
        if len(phones) > limit:
            lines += f'\n  ... و{len(phones)-limit} آخرين'
        return lines

    # ══ رسالة العضو: مبسّطة بدون أرقام ══
    _member_text = (
        f'✅ <b>تم اكتمال طلبك{_ai_label}!</b>\n'
        f'📌 @{bot_user}\n\n'
        f'✅ المنجز: <b>{done}</b>'
    )
    if reactivated > 0:
        _member_text += f'  |  🔄 المكرر: <b>{reactivated}</b>'
    if failed > 0:
        _member_text += f'  |  ❌ الفاشل: <b>{failed}</b>'
    _member_text += _refund_line + _stars_note

    # ══ رسالة المالك: تفاصيل كاملة + أزرار طرد ══
    _done_block    = _phones_block(_done_phones)
    _reactiv_block = _phones_block(_reactiv_phones)
    _fail_block    = ''
    if _fail_phones:
        _fail_lines = []
        for _fp, _fid, _fd in _fail_phones[:20]:
            _short_reason = _fd[:50] if _fd else '—'
            _fail_lines.append(f'  • <code>{_fp}</code> — {_short_reason}')
        _fail_block = '\n'.join(_fail_lines)
        if len(_fail_phones) > 20:
            _fail_block += f'\n  ... و{len(_fail_phones)-20} آخرين'

    _owner_text = (
        f'📊 <b>تقرير إحالة بوت إجباري{_ai_label}</b>\n'
        f'📌 @{bot_user}'
        + (f' | 👤 <code>{requester_id}</code>' if requester_id != OWNER_ID else '')
        + f'\n💳 {"⭐ نجوم" if payment_method == "stars" else "💎 نقاط"}\n\n'
        f'✅ المنجز: <b>{done}</b>  |  🔄 المكرر: <b>{reactivated}</b>  |  ❌ الفاشل: <b>{failed}</b>'
        + (_replaced_note or '')
        + (_refund_line or '')
    )
    if _done_block:
        _owner_text += f'\n\n✅ <b>الحسابات المنجزة:</b>\n{_done_block}'
    if _reactiv_block:
        _owner_text += f'\n\n🔄 <b>الحسابات المكررة:</b>\n{_reactiv_block}'
    if _fail_block:
        _owner_text += f'\n\n❌ <b>الحسابات الفاشلة:</b>\n{_fail_block}'

    _kick_kb = []
    if _fail_phones:
        for _fp, _fid, _ in _fail_phones[:10]:
            _kick_kb.append([InlineKeyboardButton(f'⚡ طرد {_fp}', callback_data=f'fref_kick:{_fid}:{_fp}')])
        if len(_fail_phones) > 10:
            _owner_text += f'\n\n<i>⚠️ يظهر زر الطرد لأول 10 حسابات فاشلة فقط</i>'
    _kick_markup = InlineKeyboardMarkup(_kick_kb) if _kick_kb else None

    # ── إرسال الرسائل ──
    async def _send_msg(chat_id, txt, markup=None):
        try:
            await context.bot.send_message(chat_id, txt, parse_mode='HTML', reply_markup=markup)
        except Exception:
            pass

    if requester_id == OWNER_ID:
        # المالك يرى التقرير الكامل مباشرةً
        if _live_msg_f:
            try:
                await context.bot.edit_message_text(
                    _owner_text, chat_id=requester_id,
                    message_id=_live_msg_f.message_id,
                    parse_mode='HTML', reply_markup=_kick_markup
                )
            except Exception:
                await _send_msg(requester_id, _owner_text, _kick_markup)
        else:
            await _send_msg(requester_id, _owner_text, _kick_markup)
    else:
        # العضو يرى الملخص المبسط فقط
        if _live_msg_f:
            try:
                await context.bot.edit_message_text(
                    _member_text, chat_id=requester_id,
                    message_id=_live_msg_f.message_id,
                    parse_mode='HTML'
                )
            except Exception:
                await _send_msg(requester_id, _member_text)
        else:
            await _send_msg(requester_id, _member_text)
        # المالك يتلقى التقرير الكامل منفصلاً
        if OWNER_ID:
            await _send_msg(OWNER_ID, _owner_text, _kick_markup)

    await _maybe_send_to_group(
        context.bot, requester_id,
        f'🔑 إحالة بوت اجباري اكتملت | 👤 {requester_id} | @{bot_user} | ✅{done} ❌{failed} 🔄{reactivated} | تعويض {refunded_pts + reactiv_refunded_pts:,}نقطة | {payment_method}',
        parse_mode='Markdown'
    )

async def _run_referral_for_new_number(phone: str, session_str: str, stock_id: int):
    """يُشغَّل فور إضافة رقم جديد: ينفّذ جميع مهام الإحالة التلقائية النشطة لهذا الرقم مباشرةً،
    دون انتظار الدورة الساعية. يتجاهل المهام التي أكملها الرقم مسبقاً."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    if not session_str:
        return
    tasks = get_referral_tasks(only_active=True)
    if not tasks:
        return
    # ── تأخير عشوائي عند البداية لتفريق الأرقام المُضافة دفعةً واحدة ──
    # عند إضافة ١٠ أرقام في آنٍ واحد، كل رقم ينتظر وقتاً مختلفاً (١-٨ دقائق)
    # فتصبح الأرقام موزّعة على ~٨ دقائق بدلاً من الانطلاق في نفس الثانية
    import random as _rand_rfn
    _jitter = _rand_rfn.uniform(60, 480)
    logger.info(f"🤝 الرقم الجديد {phone}: انتظار {_jitter:.0f}ث قبل بدء الإحالة التلقائية")
    await asyncio.sleep(_jitter)
    logger.info(f"🤝 تشغيل مهام الإحالة الفورية للرقم الجديد {phone} ({len(tasks)} مهمة)")
    for task in tasks:
        # تخطي إذا كان الرقم أنجز هذه المهمة بالفعل
        with db_conn() as _c:
            _done = _c.execute(
                "SELECT 1 FROM referral_completions WHERE task_id=%s AND stock_id=%s AND status='done'",
                (task["id"], stock_id)
            ).fetchone()
        if _done:
            continue
        # تخطي فوري إذا كان البوت المستهدف هو البوت نفسه
        if _OWN_BOT_USERNAME and task["bot_username"].lower().lstrip("@") == _OWN_BOT_USERNAME:
            mark_referral_completion(task["id"], stock_id, "done", "البوت المستهدف هو البوت نفسه")
            continue
        success, _reactiv, detail = await do_referral_for_number(
            phone, session_str,
            task["bot_username"], task.get("start_param", "") or "",
            mandatory_channels=task.get("mandatory_channels", "") or "",
            folder_link=task.get("folder_link", "") or "",
            stock_id=stock_id,
        )
        status = "done" if success else "failed"
        mark_referral_completion(task["id"], stock_id, status, None if success else detail)
        logger.info(f"🤝 مهمة [{task['label']}] ← {phone}: {'✅ نجح' if success else '❌ فشل'}")
        # تأخير بين كل مهمة إحالة لنفس الرقم — قابل للضبط
        _task_delay = float(get_setting("referral_task_delay") or "30")
        await asyncio.sleep(max(0.00001, _task_delay))


async def run_referral_tasks_job(context: ContextTypes.DEFAULT_TYPE):
    """تُشغَّل كل ساعة: تُكمل الإحالات لكل الأرقام التي لم تُنفّذها بعد."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    tasks = get_referral_tasks(only_active=True)
    if not tasks:
        return
    for task in tasks:
        # تخطي فوري إذا كان البوت المستهدف هو البوت نفسه (ارشقلي)
        if _OWN_BOT_USERNAME and task["bot_username"].lower().lstrip("@") == _OWN_BOT_USERNAME:
            logger.info(f"🤝 مهمة [{task['label']}]: البوت المستهدف هو البوت نفسه — تم التخطي")
            continue
        pending = get_pending_numbers_for_task(task["id"])
        if not pending:
            continue
        logger.info(f"🤝 مهمة إحالة [{task['label']}]: {len(pending)} رقم معلّق")
        done = failed = reactivated_auto = 0
        for num in pending:
            # تخطي الأرقام التي لم تحصل على جلسة بعد (ستُشمل تلقائياً في الدورة القادمة)
            if not num.get("session_string"):
                continue
            success, _reactiv_t, detail = await do_referral_for_number(
                num["phone_number"], num["session_string"],
                task["bot_username"], task["start_param"],
                mandatory_channels=task.get("mandatory_channels", "") or "",
                folder_link=task.get("folder_link", "") or "",
                stock_id=num.get("id", 0),
            )
            status = "done" if success else "failed"
            mark_referral_completion(task["id"], num["id"], status,
                                     None if success else detail)
            if success and _reactiv_t:
                reactivated_auto += 1
                done += 1
            elif success:
                done += 1
            else:
                failed += 1
            _ref_delay = float(get_setting("referral_task_delay") or "30")
            await asyncio.sleep(max(0.00001, _ref_delay))   # فاصل بين أرقام — قابل للضبط
        logger.info(f"✅ مهمة [{task['label']}]: {done} نجحت، {failed} فشلت، {reactivated_auto} مكرر")
        if OWNER_ID:
            try:
                await context.bot.send_message(
                    OWNER_ID,
                    f'📊 <b>تقرير الإحالة التلقائية</b>\n'
                    f'📌 🤖 من المالك — الإحالة التلقائية\n'
                    f'🏷 المهمة: {task["label"]} | @{task["bot_username"]}\n\n'
                    f'✅ <b>الحسابات المكملة:</b> {done - reactivated_auto}\n'
                    f'❌ <b>الحسابات الفاشلة:</b> {failed}\n'
                    f'🔄 <b>الحسابات المكررة (مفعّل مسبقاً):</b> {reactivated_auto}',
                    parse_mode='HTML'
                )
            except Exception:
                pass

# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

OWNER_FIXED_2FA_PASSWORD = os.getenv("TWOFA_PASSWORD", "محمد")

def generate_2fa_password() -> str:
    """يُرجع كلمة مرور 2FA الثابتة الموحّدة لجميع الحسابات (بدل توليد كلمة عشوائية)."""
    return OWNER_FIXED_2FA_PASSWORD

async def verify_current_2fa_password(client: TelegramClient, password: str, phone: str | None = None) -> bool | None:
    """يتحقّق فعلياً إن كانت كلمة المرور المُعطاة هي كلمة تحقق بخطوتين الحالية للحساب،
    عبر CheckPasswordRequest (SRP) — يتحقق فقط ولا يُعدّل الكلمة أبداً.
    يُرجع True لو صحيحة، False لو خاطئة بالتأكيد، أو None لو تعذّر التأكد (خطأ شبكي مثلاً)."""
    try:
        pwd_state = await client(GetPasswordRequest())
        if not pwd_state.has_password:
            return True
        pwd_check = compute_check(pwd_state, password)
        await client(CheckPasswordRequest(password=pwd_check))
        return True
    except Exception as e:
        err = str(e).upper()
        if "PASSWORD_HASH_INVALID" in err or "SRP_ID_INVALID" in err:
            return False
        logger.warning(f"⚠️ تعذّر التحقق من كلمة مرور 2FA الحالية: {e}")
        return None

async def enable_2fa_for_number(phone: str, session_str: str, stock_id: int, bot=None) -> tuple:
    """
    يُفعّل التحقق بخطوتين (كلمة مرور السحابة Cloud Password) لحساب تيليجرام.
    — إذا لم تكن هناك كلمة مرور مسبقاً: يُفعّل الكلمة الثابتة المعتمدة (محمد).
    — إذا كانت مفعّلة مسبقاً وعندنا كلمتها: لا يفعل شيئاً (بالفعل آمن).
    — إذا كانت مفعّلة مسبقاً وليس عندنا كلمتها: يتحقق فعلياً من الكلمة الثابتة (محمد)؛
      لو صحيحة يحفظها، لو خاطئة يُبلّغ المالك (إن أُعطي `bot`) ويطلب الكلمة الصحيحة، ولا يخزّن شيئاً خاطئاً.
    يُرجع (success: bool, message: str, password: str|None).
    """
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return False, "TELEGRAM_API_ID/HASH غير مضبوط", None

    client = TelegramClient(
        StringSession(session_str),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return False, "الجلسة منتهية أو مُلغاة", None

        # ─── فحص هل 2FA مفعّل مسبقاً ───────────────────────────────
        pwd_state = await client(GetPasswordRequest())
        if pwd_state.has_password:
            with db_conn() as c:
                row = c.execute(
                    "SELECT twofa_password FROM number_stock WHERE id=%s", (stock_id,)
                ).fetchone()
            saved_pwd = row["twofa_password"] if row else None

            if saved_pwd:
                if saved_pwd == OWNER_FIXED_2FA_PASSWORD:
                    return True, "2FA مفعّل مسبقاً وكلمة المرور محفوظة", saved_pwd
                else:
                    # ─── كلمة المرور المخزّنة ≠ "محمد" → نغيّرها الآن ───
                    try:
                        _expected_2fa_change[phone] = time.time()
                        await client.edit_2fa(
                            current_password=saved_pwd,
                            new_password=OWNER_FIXED_2FA_PASSWORD,
                        )
                        with db_conn() as _uc:
                            _uc.execute(
                                "UPDATE number_stock SET twofa_password=%s, auto_2fa_enabled=TRUE WHERE id=%s",
                                (OWNER_FIXED_2FA_PASSWORD, stock_id)
                            )
                        logger.info(f"🔐 تم تغيير 2FA للرقم {phone} إلى الكلمة الثابتة")
                        return True, "تم تغيير 2FA إلى الكلمة الثابتة بنجاح", OWNER_FIXED_2FA_PASSWORD
                    except Exception as _ch_e:
                        logger.warning(f"⚠️ فشل تغيير 2FA للرقم {phone}: {_ch_e}")
                        return False, f"فشل تغيير 2FA: {str(_ch_e)[:80]}", None

            # ─── لا نعرف كلمة المرور بعد: نتحقق فعلياً من الكلمة الثابتة "محمد" ───
            verified = await verify_current_2fa_password(client, OWNER_FIXED_2FA_PASSWORD, phone=phone)
            if verified is True:
                with db_conn() as c:
                    c.execute(
                        "UPDATE number_stock SET twofa_password=%s WHERE id=%s",
                        (OWNER_FIXED_2FA_PASSWORD, stock_id)
                    )
                return True, "2FA مفعّل مسبقاً — تم التحقق من الكلمة الثابتة وحفظها", OWNER_FIXED_2FA_PASSWORD
            elif verified is False:
                # ─── كلمة المرور غير معروفة وليست الكلمة الثابتة → إشعار المالك فقط، بدون إعادة تعيين تلقائية ───
                logger.warning(f"⚠️ enable_2fa: كلمة مرور {phone} مجهولة — إشعار المالك بدون auto-reset")
                if bot is not None:
                    try:
                        await bot.send_message(
                            NUMBERS_GROUP_ID or OWNER_ID,
                            f"🔐 *تنبيه: كلمة مرور 2FA غير معروفة*\n\n"
                            f"📱 الرقم: `{phone}`\n"
                            f"❌ الكلمة الثابتة \"{OWNER_FIXED_2FA_PASSWORD}\" غير صحيحة على هذا الحساب.\n"
                            f"⛔️ *لم يتم* إجراء إعادة تعيين تلقائية.\n\n"
                            f"👤 يرجى التدخل يدوياً وإدخال كلمة المرور الصحيحة.",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass
                try:
                    await request_manual_2fa_password(bot, phone, stock_id)
                except Exception:
                    pass
                return False, f"كلمة المرور الثابتة \"{OWNER_FIXED_2FA_PASSWORD}\" غير صحيحة — تم إشعار المالك للتدخل يدوياً", None
            else:
                return False, "2FA مفعّل مسبقاً، تعذّر التحقق من الكلمة الثابتة الآن (سيُعاد المحاولة لاحقاً)", None

        # ─── توليد كلمة مرور جديدة وتفعيل 2FA ──────────────────────
        new_pwd = generate_2fa_password()
        _expected_2fa_change[phone] = time.time()
        await client.edit_2fa(
            new_password=new_pwd,
            hint="Auto",     # تلميح محايد لا يكشف شيئاً
        )

        # ─── حفظ كلمة المرور وتعليم الحساب بأن البوت فعّل 2FA تلقائياً ───
        with db_conn() as c:
            c.execute(
                "UPDATE number_stock SET twofa_password=%s, auto_2fa_enabled=TRUE WHERE id=%s",
                (new_pwd, stock_id)
            )

        logger.info(f"🔐 تم تفعيل 2FA للرقم {phone} بنجاح (تلقائياً)")
        return True, "تم تفعيل التحقق بخطوتين بنجاح", new_pwd

    except Exception as e:
        err = str(e)
        logger.error(f"❌ فشل تفعيل 2FA للرقم {phone}: {err}")
        return False, err[:120], None
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

async def check_twofa_reset_job(context: ContextTypes.DEFAULT_TYPE):
    """مهمة دورية: تُكمل إعادة تعيين 2FA للحسابات التي انتهت مهلة 7 أيام."""
    import datetime as _dt
    _now = _dt.datetime.now(_dt.timezone.utc)
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, phone_number, session_string FROM number_stock "
            "WHERE twofa_reset_date IS NOT NULL AND twofa_reset_date <= %s "
            "AND session_string IS NOT NULL",
            (_now,)
        ).fetchall()
    if not rows:
        return
    logger.info(f"🔐 check_twofa_reset_job: {len(rows)} حساب جاهز لإكمال إعادة تعيين 2FA")
    for rec in rows:
        phone = rec["phone_number"]
        try:
            _cl = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await _cl.connect()
            if not await _cl.is_user_authorized():
                await _cl.disconnect()
                continue
            _res = await _cl(ResetPasswordRequest())
            await _cl.edit_2fa(new_password=OWNER_FIXED_2FA_PASSWORD)
            with db_conn() as _uc:
                _uc.execute(
                    "UPDATE number_stock SET twofa_password=%s, twofa_reset_date=NULL, auto_2fa_enabled=TRUE WHERE id=%s",
                    (OWNER_FIXED_2FA_PASSWORD, rec["id"])
                )
            logger.info(f"✅ check_twofa_reset_job: تم تعيين 2FA={OWNER_FIXED_2FA_PASSWORD} للرقم {phone}")
            _n_target = NUMBERS_GROUP_ID or OWNER_ID
            if _n_target and context.bot:
                try:
                    await context.bot.send_message(
                        _n_target,
                        f"✅ *اكتمل إعادة تعيين 2FA*\n\n"
                        f"📱 الرقم: `{phone}`\n"
                        f"🔐 كلمة المرور الجديدة: `{OWNER_FIXED_2FA_PASSWORD}`",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass
            await _cl.disconnect()
        except Exception as _e:
            logger.warning(f"⚠️ check_twofa_reset_job: فشل إكمال reset للرقم {phone}: {_e}")
            try:
                await _cl.disconnect()
            except Exception:
                pass
        await asyncio.sleep(3)

async def enable_pending_2fa_job(context: ContextTypes.DEFAULT_TYPE):
    """مهمة دورية: تُفعّل 2FA على كل الأرقام التي ليس عندها كلمة مرور محفوظة بعد."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, phone_number, session_string FROM number_stock "
            "WHERE session_string IS NOT NULL AND (twofa_password IS NULL OR twofa_password = '')"
        ).fetchall()
    if not rows:
        return
    logger.info(f"🔐 مهمة 2FA: {len(rows)} رقم بحاجة لتفعيل التحقق بخطوتين")
    done = failed = skipped = 0
    for rec in rows:
        success, msg, pwd = await enable_2fa_for_number(
            rec["phone_number"], rec["session_string"], rec["id"], bot=context.bot
        )
        if success:
            done += 1
        elif "مسبقاً بكلمة مرور غير معروفة" in msg:
            skipped += 1
        else:
            failed += 1
        await asyncio.sleep(3)
    # ─── هذه المهمة الدورية صامتة: لا تُرسل تقريراً للمالك في كل دورة (بناءً على طلبه)،
    # يحتاج تدخله (مثل طلب كلمة 2FA اليدوية عبر request_manual_2fa_password) ───
    logger.info(f"✅ مهمة 2FA: {done} نجحت | {skipped} مُتجاوزة | {failed} فشلت")

async def _cleanup_pending_login(owner_id: int):
    pending = _pending_number_logins.pop(owner_id, None)
    if pending:
        try:
            await pending["client"].disconnect()
        except Exception:
            pass

# ────────────────────────────────────────────────────────────
# تدوير الجلسة عبر QR Code — لا يحتاج لـ 2FA
# ────────────────────────────────────────────────────────────
async def _rotate_via_qr(phone: str, old_session_str: str, old_client=None) -> tuple[bool, str]:
    """
    تدوير الجلسة عبر QR Code بدون الحاجة لكلمة مرور 2FA:
    1. الجلسة الجديدة تطلب QR token عبر ExportLoginTokenRequest
    2. الجلسة القديمة تقبله عبر AcceptLoginTokenRequest
    3. الجلسة الجديدة تصبح مفعّلة بدون طلب 2FA
    4. نُلغي الجلسة القديمة بـ log_out()
    5. ResetAuthorizationsRequest لطرد أي جلسات أخرى متبقية
    """
    _own_old = old_client is None
    new_client = None
    try:
        if _own_old:
            old_client = TelegramClient(StringSession(old_session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await asyncio.wait_for(old_client.connect(), timeout=20)
            if not await asyncio.wait_for(old_client.is_user_authorized(), timeout=10):
                return False, "الجلسة القديمة منتهية الصلاحية"

        new_client = TelegramClient(StringSession(), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(new_client.connect(), timeout=20)

        # ── طلب QR token من الجلسة الجديدة ─────────────────────────────
        qr = await asyncio.wait_for(
            new_client(ExportLoginTokenRequest(
                api_id=int(TELEGRAM_API_ID),
                api_hash=TELEGRAM_API_HASH,
                except_ids=[]
            )),
            timeout=15
        )
        logger.info(f"rotate-qr: ✅ طُلب QR token للرقم {phone}")

        # ── الجلسة القديمة تقبل الـ token ────────────────────────────────
        await asyncio.wait_for(
            old_client(AcceptLoginTokenRequest(token=qr.token)),
            timeout=15
        )
        logger.info(f"rotate-qr: ✅ قُبِل QR token للرقم {phone}")

        # ── انتظار تفعيل الجلسة الجديدة (حتى 20 ثانية) ─────────────────
        authorized = False
        for _ in range(10):
            await asyncio.sleep(2)
            try:
                if await asyncio.wait_for(new_client.is_user_authorized(), timeout=5):
                    authorized = True
                    break
            except Exception:
                pass

        if not authorized:
            return False, "الجلسة الجديدة لم تتفعل بعد قبول QR"

        new_session_str = new_client.session.save()
        logger.info(f"rotate-qr: ✅ جلسة جديدة بـ auth_key مختلف للرقم {phone}")

        # ── إلغاء الجلسة القديمة صراحةً ──────────────────────────────────
        try:
            await asyncio.wait_for(old_client.log_out(), timeout=10)
            logger.info(f"rotate-qr: ✅ الجلسة القديمة أُلغيت للرقم {phone}")
        except Exception as _lo_e:
            logger.warning(f"rotate-qr: ⚠️ تعذّر log_out القديمة للرقم {phone}: {_lo_e}")

        # ── تفعيل 2FA تلقائياً بالكلمة الثابتة ──────────────────────────
        try:
            _expected_2fa_change[phone] = time.time()
            await asyncio.wait_for(
                new_client.edit_2fa(new_password=OWNER_FIXED_2FA_PASSWORD, hint="Auto"),
                timeout=20
            )
            with db_conn() as _c2fa:
                _c2fa.execute(
                    "UPDATE number_stock SET twofa_password=%s, auto_2fa_enabled=TRUE WHERE phone_number=%s",
                    (OWNER_FIXED_2FA_PASSWORD, phone)
                )
            logger.info(f"rotate-qr: ✅ تم تفعيل 2FA بالكلمة الثابتة للرقم {phone}")
        except Exception as _2fa_e:
            logger.warning(f"rotate-qr: ⚠️ تعذّر تفعيل 2FA للرقم {phone}: {_2fa_e}")

        # ── طرد أي جلسات متبقية ──────────────────────────────────────────
        for _attempt in range(10):
            try:
                await asyncio.wait_for(new_client(ResetAuthorizationsRequest()), timeout=15)
                logger.info(f"rotate-qr: ✅ طُردت كل الجلسات المتبقية للرقم {phone}")
                break
            except Exception as _ke:
                _ke_str = str(_ke)
                if "too new" in _ke_str or "cannot be used to reset" in _ke_str:
                    await asyncio.sleep(10)
                else:
                    logger.warning(f"rotate-qr: ⚠️ ResetAuth: {_ke_str[:60]}")
                    break

        return True, new_session_str

    except Exception as e:
        logger.error(f"rotate-qr: خطأ على الرقم {phone}: {e}")
        return False, str(e)[:120]
    finally:
        if new_client:
            try:
                await new_client.disconnect()
            except Exception:
                pass
        if _own_old and old_client:
            try:
                await old_client.disconnect()
            except Exception:
                pass


# تدوير الجلسة: ينشئ جلسة جديدة عبر OTP يستقبله البوت تلقائياً من 777000
# ────────────────────────────────────────────────────────────
async def _rotate_one_session(phone: str, old_session_str: str) -> tuple[bool, str]:
    """
    يُلغي الملف الأصلي للجلسة نهائياً وينشئ مفتاحاً جديداً كلياً:
    1. يتصل بالجلسة القديمة ويجلب رقم الهاتف
    2. يطلب كود OTP لرقم الهاتف عبر عميل جديد
    3. يستقبل الكود تلقائياً من رسائل 777000 عبر الجلسة القديمة
    4. يُكمل تسجيل الدخول → جلسة جديدة بـ auth_key مختلف كلياً
    5. يطرد كل الجلسات الأخرى (بما فيها الملف الأصلي) → تالف نهائياً
    يُرجع (True, new_session_str) أو (False, رسالة_خطأ)
    """
    import datetime as _dt
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return False, "لا توجد API_ID / API_HASH"

    old_client = None
    new_client = None
    try:
        # ── الاتصال بالجلسة القديمة والتحقق منها ────────────────────────
        old_client = TelegramClient(StringSession(old_session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(old_client.connect(), timeout=20)
        if not await asyncio.wait_for(old_client.is_user_authorized(), timeout=10):
            return False, "الجلسة منتهية الصلاحية"

        me = await asyncio.wait_for(old_client.get_me(), timeout=10)
        phone_clean = me.phone if me.phone.startswith("+") else f"+{me.phone}"

        # ── فحص 2FA وإزالته مؤقتاً قبل التدوير ─────────────────────────
        # البوت يملك الجلسة القديمة بشكل كامل — يستخدمها لإزالة 2FA الآن
        # ثم يُعيد تفعيله على الجلسة الجديدة بعد التدوير
        twofa_was_active = False
        try:
            pwd_state = await asyncio.wait_for(old_client(GetPasswordRequest()), timeout=10)
            if pwd_state.has_password:
                twofa_was_active = True
                # جلب كلمة المرور المحفوظة
                with db_conn() as _c2fa_chk:
                    _r2fa = _c2fa_chk.execute(
                        "SELECT twofa_password FROM number_stock WHERE phone_number=%s", (phone,)
                    ).fetchone()
                saved_pwd = (_r2fa["twofa_password"] if _r2fa else None) or OWNER_FIXED_2FA_PASSWORD
                # إزالة 2FA مؤقتاً عبر الجلسة القديمة
                _expected_2fa_change[phone] = time.time()
                await asyncio.wait_for(
                    old_client.edit_2fa(current_password=saved_pwd, new_password=""),
                    timeout=20
                )
                logger.info(f"rotate-otp: ✅ تم إزالة 2FA مؤقتاً للرقم {phone_clean}")
        except Exception as _2fa_rm_e:
            # لو فشل إزالة 2FA نكمل على أي حال — sign_in سيحاول كلمة المرور
            logger.warning(f"rotate-otp: ⚠️ تعذّر إزالة 2FA للرقم {phone_clean}: {_2fa_rm_e}")
            twofa_was_active = False  # نعامله كأن ما فيه 2FA ونحاول

        # ── طلب كود OTP عبر العميل الجديد ───────────────────────────────
        new_client = TelegramClient(StringSession(), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(new_client.connect(), timeout=20)

        request_time = _dt.datetime.now(_dt.timezone.utc)
        try:
            sent = await asyncio.wait_for(new_client.send_code_request(phone_clean), timeout=20)
        except FloodWaitError as _fw_otp:
            await new_client.disconnect()
            _fw_secs = _fw_otp.seconds
            _fw_hrs  = _fw_secs // 3600
            _fw_mins = (_fw_secs % 3600) // 60
            logger.warning(f"rotate-otp: ⏳ FloodWait {phone_clean}: {_fw_secs}ث")
            return False, f"FloodWait {_fw_hrs}س {_fw_mins}د — تيليجرام يطلب الانتظار قبل طلب كود جديد"
        logger.info(f"rotate-otp: ✅ طُلب كود OTP للرقم {phone_clean}")

        # ── انتظار وصول الكود عبر 777000 على الجلسة القديمة ────────────
        code = None
        for _attempt in range(15):   # حتى 30 ثانية
            await asyncio.sleep(2)
            try:
                raw_msg, msg_date = await fetch_last_login_code(old_client, after_date=request_time)
                if raw_msg:
                    m = re.search(r'(\d{4,7})', raw_msg)
                    if m:
                        code = m.group(1)
                        logger.info(f"rotate-otp: ✅ استُقبل الكود للرقم {phone_clean} بعد {(_attempt+1)*2} ث")
                        break
            except Exception as _fe:
                logger.debug(f"rotate-otp: فشل قراءة 777000 ({_attempt+1}/15): {_fe}")

        if not code:
            # لو ما وصل الكود — نُعيد 2FA للحالة الأصلية
            if twofa_was_active:
                try:
                    _expected_2fa_change[phone] = time.time()
                    await asyncio.wait_for(
                        old_client.edit_2fa(new_password=OWNER_FIXED_2FA_PASSWORD, hint="Auto"),
                        timeout=20
                    )
                except Exception:
                    pass
            return False, "لم يصل كود OTP خلال 30 ثانية — تأكد أن الجلسة تستطيع استقبال رسائل 777000"

        # ── إكمال تسجيل الدخول بالكود (بدون 2FA الآن) ──────────────────
        try:
            await asyncio.wait_for(
                new_client.sign_in(phone_clean, code, phone_code_hash=sent.phone_code_hash),
                timeout=15
            )
        except SessionPasswordNeededError:
            # أولاً: نجرب الكلمة المحفوظة
            _pw_ok = False
            try:
                with db_conn() as _c2fa:
                    _row = _c2fa.execute(
                        "SELECT twofa_password FROM number_stock WHERE phone_number=%s", (phone,)
                    ).fetchone()
                pwd = (_row["twofa_password"] if _row else None) or OWNER_FIXED_2FA_PASSWORD
                if pwd:
                    await asyncio.wait_for(new_client.sign_in(password=pwd), timeout=15)
                    logger.info(f"rotate-otp: ✅ تخطي 2FA (fallback) للرقم {phone_clean}")
                    _pw_ok = True
            except Exception:
                pass

            if not _pw_ok:
                # الكلمة مجهولة — نُغلق الـ new_client ونتحول لطريقة QR
                logger.info(f"rotate-otp: 2FA مجهول للرقم {phone_clean} — تحويل لتدوير QR")
                try:
                    await new_client.disconnect()
                except Exception:
                    pass
                qr_ok, qr_res = await _rotate_via_qr(phone, old_session_str, old_client)
                return qr_ok, qr_res
        except Exception as _se:
            return False, f"فشل sign_in: {str(_se)[:80]}"

        if not await asyncio.wait_for(new_client.is_user_authorized(), timeout=10):
            return False, "الجلسة الجديدة غير مفعّلة بعد sign_in"

        new_session_str = new_client.session.save()
        logger.info(f"rotate-otp: ✅ جلسة جديدة بـ auth_key مختلف للرقم {phone_clean}")

        # ── إلغاء الجلسة القديمة صراحةً (log_out) قبل ResetAuth ────────
        # الجلسة الجديدة قد تكون "جديدة جداً" لـ ResetAuth، لذا نُلغي القديمة
        # من طرفها مباشرةً لضمان إبطالها حتى لو فشل ResetAuth لاحقاً.
        try:
            await asyncio.wait_for(old_client.log_out(), timeout=10)
            logger.info(f"rotate-otp: ✅ الجلسة القديمة أُلغيت صراحةً للرقم {phone_clean}")
        except Exception as _lo_e:
            logger.warning(f"rotate-otp: ⚠️ تعذّر log_out للجلسة القديمة للرقم {phone_clean}: {_lo_e}")

        # ── إعادة تفعيل 2FA على الجلسة الجديدة بكلمة البوت الثابتة ─────
        try:
            _expected_2fa_change[phone] = time.time()
            await asyncio.wait_for(
                new_client.edit_2fa(new_password=OWNER_FIXED_2FA_PASSWORD, hint="Auto"),
                timeout=20
            )
            with db_conn() as _c2fa_set:
                _c2fa_set.execute(
                    "UPDATE number_stock SET twofa_password=%s, auto_2fa_enabled=TRUE WHERE phone_number=%s",
                    (OWNER_FIXED_2FA_PASSWORD, phone)
                )
            logger.info(f"rotate-otp: ✅ تم تفعيل 2FA بالكلمة الثابتة للرقم {phone_clean}")
        except Exception as _2fa_set_e:
            logger.warning(f"rotate-otp: ⚠️ تعذّر إعادة تفعيل 2FA للرقم {phone_clean}: {_2fa_set_e}")

        # ── طرد كل الجلسات الأخرى (بما فيها الملف الأصلي) ─────────────
        _reset_ok = False
        _reset_err = ""
        for _attempt in range(10):
            try:
                await asyncio.wait_for(new_client(ResetAuthorizationsRequest()), timeout=15)
                _reset_ok = True
                logger.info(f"rotate-otp: ✅ الملف الأصلي أُلغي نهائياً للرقم {phone_clean} (محاولة {_attempt+1})")
                break
            except Exception as _ke:
                _reset_err = str(_ke)
                if "too new" in _reset_err or "cannot be used to reset" in _reset_err:
                    logger.info(f"rotate-otp: جلسة جديدة جداً — انتظار 10 ث (محاولة {_attempt+1}/10)")
                    await asyncio.sleep(10)
                else:
                    logger.warning(f"rotate-otp: ResetAuth خطأ للرقم {phone_clean}: {_ke}")
                    break

        if not _reset_ok:
            # الجلسة الجديدة تعمل لكن الطرد فشل — نُرجع الجلسة الجديدة على الأقل
            logger.warning(f"rotate-otp: ⚠️ ResetAuth فشل للرقم {phone_clean}: {_reset_err}")
            return True, new_session_str

        logger.info(f"rotate-otp: ✅ اكتمل التدوير الكامل للرقم {phone_clean} — الملف الأصلي تالف")
        return True, new_session_str

    except Exception as e:
        logger.error(f"rotate-otp: خطأ على الرقم {phone}: {e}")
        return False, str(e)[:120]
    finally:
        for _cl in (old_client, new_client):
            if _cl:
                try:
                    await _cl.disconnect()
                except Exception:
                    pass


async def cmd_rotate_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /rotate_sessions — يدوّر جلسات كل الأرقام غير المباعة (ينشئ جلسة جديدة ويحذف القديمة)."""
    user = update.effective_user
    if user.id != OWNER_ID:
        return
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        await update.message.reply_text("❌ متغيرات API_ID / API_HASH غير مضبوطة.")
        return

    with db_conn() as _c:
        rows = _c.execute(
            "SELECT id, phone_number, session_string FROM number_stock "
            "WHERE ever_sold IS NOT TRUE AND session_string IS NOT NULL "
            "AND deleted_at IS NULL"
        ).fetchall()

    total = len(rows)
    if total == 0:
        await update.message.reply_text("ℹ️ لا توجد أرقام غير مباعة لديها جلسة.")
        return

    status_msg = await update.message.reply_text(
        f"🔁 *بدأ تدوير الجلسات...*\n📦 إجمالي: *{total}* رقم\n⏱️ الرجاء الانتظار...",
        parse_mode=ParseMode.MARKDOWN
    )

    ok_list, fail_list = [], []

    for idx, rec in enumerate(rows):
        rec = dict(rec)
        phone = rec["phone_number"]
        if idx > 0:
            await asyncio.sleep(3)   # تأخير 3 ثوانٍ بين كل رقم لتفادي FloodWait
        success, result = await _rotate_one_session(phone, rec["session_string"])

        if success:
            new_ss = result
            with db_conn() as _cx:
                _cx.execute(
                    "UPDATE number_stock SET session_string=%s, sessions_reset=TRUE WHERE id=%s",
                    (new_ss, rec["id"])
                )
            ok_list.append(f"`{phone}`")
        else:
            fail_list.append(f"`{phone}` — {result}")

        # ── تحديث رسالة التقدم كل 3 أرقام ─────────────────────────────
        if (idx + 1) % 3 == 0 or (idx + 1) == total:
            try:
                await status_msg.edit_text(
                    f"🔁 *تدوير الجلسات... {idx+1}/{total}*\n"
                    f"✅ نجح: *{len(ok_list)}*  |  ❌ فشل: *{len(fail_list)}*",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

    lines = [
        f"✅ *اكتمل تدوير الجلسات*\n",
        f"📦 إجمالي: *{total}*",
        f"✅ نجح التدوير: *{len(ok_list)}*",
        f"❌ فشل: *{len(fail_list)}*",
    ]
    if ok_list:
        lines.append("\n*✅ نجح:*")
        lines.extend(f"  • {p}" for p in ok_list[:30])
        if len(ok_list) > 30:
            lines.append(f"  _(+{len(ok_list)-30} آخرين)_")
    if fail_list:
        lines.append("\n*❌ فشل:*")
        lines.extend(f"  • {f}" for f in fail_list[:20])
        if len(fail_list) > 20:
            lines.append(f"  _(+{len(fail_list)-20} آخرين)_")
    await status_msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def _finish_number_login(update: Update, context: ContextTypes.DEFAULT_TYPE, owner_id: int):
    """يُستدعى بعد نجاح تسجيل الدخول (بكود فقط أو بكود + كلمة مرور): يحفظ الجلسة بالمخزون وينظّف الحالة المؤقتة."""
    pending = _pending_number_logins.get(owner_id)
    if not pending:
        return
    client = pending["client"]
    phone = pending["phone"]
    try:
        session_str = client.session.save()
        add_number_with_session(phone, session_str)
        kicked_note = ""
        try:
            await client(ResetAuthorizationsRequest())
            # ─── فحص is_solo: البوت الوحيد بعد الطرد ──────────────────────
            try:
                _dev_cnt = await get_device_count(client)
                _is_solo_now = (_dev_cnt == 1)
                with db_conn() as _sc:
                    _sc.execute(
                        "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s WHERE phone_number=%s",
                        (_is_solo_now, phone)
                    )
                # ─── تسجيل IP الجلسة لكشف الخطف الصامت لاحقاً ──────────────
                try:
                    _bot_ip = await get_session_ip(client)
                    if _bot_ip:
                        with db_conn() as _ipdb:
                            _ipdb.execute(
                                "UPDATE number_stock SET bot_session_ip=%s WHERE phone_number=%s",
                                (_bot_ip, phone)
                            )
                        logger.info(f"🔐 session_ip: سُجِّل IP={_bot_ip} للرقم {phone}")
                except Exception as _ip_e:
                    logger.debug(f"⚠️ تعذّر تسجيل IP الجلسة للرقم {phone}: {_ip_e}")
                # ─── استدعاء _test_and_set_can_send_code دائماً بغض النظر عن is_solo ───
                with db_conn() as _sid:
                    _sid_row = _sid.execute(
                        "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
                    ).fetchone()
                if _sid_row:
                    asyncio.create_task(
                        _test_and_set_can_send_code(phone, session_str, _sid_row["id"])
                    )
            except Exception as _dev_e:
                with db_conn() as c:
                    c.execute("UPDATE number_stock SET sessions_reset=TRUE WHERE phone_number=%s", (phone,))
                logger.debug(f"⚠️ فحص is_solo بعد الطرد فشل للرقم {phone}: {_dev_e}")
            kicked_note = "\n🔒 تم تسجيل خروج كل الأجهزة/الجلسات الأخرى من هذا الحساب تلقائياً."
        except Exception as e:
            logger.warning(f"⚠️ تعذر تسجيل خروج الجلسات الأخرى للرقم {phone} فوراً، سيُعاد المحاولة تلقائياً بالخلفية: {e}")
            kicked_note = "\n⏳ لم يُسمح بطرد الجلسات الأخرى فوراً (قيد مؤقت من تيليجرام)، سيحاول البوت تلقائياً كل فترة حتى ينجح ويرسل لك تنبيهاً."
        # ─── تفعيل التحقق بخطوتين تلقائياً ───────────────────────────
        twofa_note = ""
        try:
            with db_conn() as c:
                row = c.execute(
                    "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
                ).fetchone()
            if row:
                ok, msg_2fa, pwd_2fa = await enable_2fa_for_number(phone, session_str, row["id"], bot=context.bot)
                if ok and pwd_2fa:
                    twofa_note = f"\n🔐 *التحقق بخطوتين:* تم تفعيله تلقائياً.\n🗝 كلمة المرور: `{pwd_2fa}`"
                elif not ok:
                    twofa_note = f"\n⚠️ تعذّر تفعيل التحقق بخطوتين: {msg_2fa}"
        except Exception as e2:
            logger.warning(f"⚠️ خطأ في تفعيل 2FA للرقم {phone}: {e2}")
        avail = get_available_number_count()
        await update.message.reply_text(
            f"✅ *تم تسجيل الدخول وحفظ الرقم بالمخزون بنجاح!*\n\n"
            f"📱 {phone}\n📦 إجمالي المتاح الآن: {avail} رقم.{kicked_note}"
            f"{twofa_note}\n\n"
            "🔔 سيُبلّغك البوت تلقائياً بأي تغيير أمني على هذا الحساب (كلمة مرور، بريد استرجاع، جلسة دخول جديدة).\n\n"
            "عند بيع هذا الرقم، سيُرسَل رمز الجلسة تلقائياً للمشتري ليدخل مباشرة بدون أي كود.",
            parse_mode=ParseMode.MARKDOWN,
        )
        # ─── للسرعة: ننتقل مباشرة لطلب الرقم التالي بدون الرجوع لأي قائمة ───
        await update.message.reply_text(
            "📲 أرسل رقم الهاتف التالي (بصيغة دولية، مثل +9647xxxxxxxx) لإضافته، "
            "أو أرسل /cancel للتوقف والرجوع للقائمة."
        )
        context.user_data["state"] = "os_await_login_phone"
    except Exception as e:
        logger.error(f"❌ خطأ في حفظ جلسة الرقم {phone}: {e}")
        await update.message.reply_text(
            "❌ حدث خطأ أثناء حفظ الجلسة. أرسل الرقم التالي للمحاولة من جديد، أو /cancel للتوقف.",
        )
        context.user_data["state"] = "os_await_login_phone"
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        _pending_number_logins.pop(owner_id, None)

async def _finish_supervisor_login(update, context, supervisor_id: int):
    """يستدعى بعد نجاح تسجيل دخول رقم المشرف: يحفظ الجلسة بالمخزون وينظف الحالة المؤقتة."""
    pending = _pending_supervisor_logins.get(supervisor_id)
    if not pending:
        return
    client  = pending["client"]
    phone   = pending["phone"]
    try:
        session_str = client.session.save()
        # ── يُحفظ في مخزون المشرف الخاص، لا في مخزون البوت العام ──
        add_supervisor_account(supervisor_id, phone, session_str)
        kicked_note = ""
        try:
            await client(ResetAuthorizationsRequest())
            kicked_note = "\n🔒 تم تسجيل خروج كل الجلسات الأخرى تلقائياً."
        except Exception:
            kicked_note = "\n⏳ لم يُسمح بطرد الجلسات الأخرى فوراً."
        total = len(get_supervisor_accounts(supervisor_id))
        msg_parts = [
            "✅ *تم تسجيل الدخول وحفظ الحساب في قسم حساباتك الخاصة!*",
            "",
            f"📱 {phone}",
            f"📦 إجمالي حساباتك: {total} حساب.{kicked_note}",
            "",
            "📲 أرسل رقم الهاتف التالي (بصيغة دولية) لإضافته، أو /cancel للتوقف.",
        ]
        await update.message.reply_text(
            "\n".join(msg_parts),
            parse_mode="Markdown",
        )
        context.user_data["state"] = "sv_await_login_phone"
    except Exception as e:
        logger.error(f"❌ خطأ في حفظ جلسة المشرف {phone}: {e}")
        await update.message.reply_text(
            "❌ حدث خطأ أثناء حفظ الجلسة. أرسل رقماً آخر أو /cancel للتوقف."
        )
        context.user_data["state"] = "sv_await_login_phone"
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        _pending_supervisor_logins.pop(supervisor_id, None)

def is_user_verified(user_id: int) -> bool:
    with db_conn() as c:
        row = c.execute("SELECT verified FROM users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row["verified"])


def is_user_banned(user_id: int) -> bool:
    with db_conn() as c:
        row = c.execute("SELECT banned FROM users WHERE user_id=%s", (user_id,)).fetchone()
        return bool(row and row["banned"])

def is_user_restricted(user_id: int) -> bool:
    """هل هذا المستخدم مقيد (referral_points_blocked)؟"""
    with db_conn() as c:
        row = c.execute("SELECT referral_points_blocked FROM users WHERE user_id=%s", (user_id,)).fetchone()
        return bool(row and row["referral_points_blocked"])

# ─────────────────────────────────────────────────────
# ─── نظام المشرفين (Supervisors) ─────────────────────
# ─────────────────────────────────────────────────────

def is_supervisor(user_id: int) -> bool:
    """هل هذا المستخدم مشرف معتمد من المالك؟"""
    with db_conn() as c:
        row = c.execute("SELECT id FROM supervisors WHERE user_id=%s", (user_id,)).fetchone()
        return row is not None

def add_supervisor(user_id: int, username: str = "") -> bool:
    """يضيف مشرفاً جديداً. يُرجع True إن أُضيف، False إن كان موجوداً."""
    with db_conn() as c:
        existing = c.execute("SELECT id FROM supervisors WHERE user_id=%s", (user_id,)).fetchone()
        if existing:
            return False
        c.execute("INSERT INTO supervisors (user_id, username) VALUES (%s, %s)", (user_id, username or ""))
        return True

def remove_supervisor(user_id: int) -> bool:
    """يزيل مشرفاً. يُرجع True إن حُذف."""
    with db_conn() as c:
        c.execute("DELETE FROM supervisors WHERE user_id=%s", (user_id,))
        return c.rowcount > 0

def get_supervisors() -> list:
    """يُرجع قائمة المشرفين."""
    with db_conn() as c:
        return c.execute("SELECT * FROM supervisors ORDER BY id").fetchall() or []

# ── حسابات المشرفين (منفصلة عن مخزون البوت) ──────────────────────────────

def add_supervisor_account(supervisor_id: int, phone: str, session_str: str) -> bool:
    """يضيف حساباً لمخزون المشرف الخاص. لا يُضاف للمخزون العام."""
    with db_conn() as c:
        c.execute(
            "INSERT INTO supervisor_accounts (supervisor_id, phone_number, session_string) "
            "VALUES (%s, %s, %s) ON CONFLICT (supervisor_id, phone_number) "
            "DO UPDATE SET session_string=EXCLUDED.session_string",
            (supervisor_id, phone, session_str)
        )
        return True

def get_supervisor_accounts(supervisor_id: int) -> list:
    """يُرجع حسابات مشرف معيّن."""
    with db_conn() as c:
        return c.execute(
            "SELECT * FROM supervisor_accounts WHERE supervisor_id=%s ORDER BY added_at DESC",
            (supervisor_id,)
        ).fetchall() or []

def delete_supervisor_account(supervisor_id: int, phone: str) -> bool:
    """يحذف حساباً من مخزون المشرف. يُرجع True إن حُذف."""
    with db_conn() as c:
        c.execute(
            "DELETE FROM supervisor_accounts WHERE supervisor_id=%s AND phone_number=%s",
            (supervisor_id, phone)
        )
        return c.rowcount > 0

def get_all_supervisor_accounts_grouped() -> dict:
    """يُرجع كل حسابات المشرفين مُجمَّعة {supervisor_id: [rows]}."""
    with db_conn() as c:
        rows = c.execute(
            "SELECT sa.*, sv.username FROM supervisor_accounts sa "
            "LEFT JOIN supervisors sv ON sv.user_id = sa.supervisor_id "
            "ORDER BY sa.supervisor_id, sa.added_at DESC"
        ).fetchall() or []
    grouped = {}
    for r in rows:
        sid = r["supervisor_id"]
        grouped.setdefault(sid, {"username": r.get("username", ""), "accounts": []})
        grouped[sid]["accounts"].append(r)
    return grouped

def get_supervisor_available_accounts(supervisor_id: int) -> list:
    """يُرجع قائمة حسابات المشرف المتاحة للإحالة الإجبارية (لها session_string)."""
    with db_conn() as c:
        return c.execute(
            "SELECT * FROM supervisor_accounts "
            "WHERE supervisor_id=%s AND session_string IS NOT NULL AND session_string != '' "
            "ORDER BY added_at DESC",
            (supervisor_id,)
        ).fetchall() or []

def ban_user_db(user_id: int, reason: str = "") -> bool:
    """يحظر عضواً ويسجّل توقيت الحظر وسببه. يُرجع True إن وُجد المستخدم بالقاعدة."""
    with db_conn() as c:
        c.execute(
            "UPDATE users SET banned=1, banned_at=NOW(), ban_reason=%s WHERE user_id=%s",
            (reason or None, user_id)
        )
        return c.rowcount > 0

def unban_user_db(user_id: int) -> bool:
    with db_conn() as c:
        c.execute(
            "UPDATE users SET banned=0, banned_at=NULL, ban_reason=NULL WHERE user_id=%s",
            (user_id,)
        )
        return c.rowcount > 0

def lookup_user_by_id_or_username(text: str) -> dict | None:
    """يبحث عن مستخدم بالـ ID أو بالـ username (بدون أو مع @).
    يُرجع صف المستخدم كـ dict أو None إن لم يُوجد."""
    text = text.strip().lstrip("@")
    with db_conn() as c:
        if text.isdigit():
            row = c.execute("SELECT * FROM users WHERE user_id=%s", (int(text),)).fetchone()
            if row:
                return dict(row)
        row = c.execute(
            "SELECT * FROM users WHERE LOWER(username)=LOWER(%s)", (text,)
        ).fetchone()
        return dict(row) if row else None

def add_points(user_id: int, pts: int):
    with db_conn() as c:
        c.execute("UPDATE users SET points=points+? WHERE user_id=?", (pts, user_id))

def deduct_points(user_id: int, pts: int) -> bool:
    """خصم نقاط بشكل ذري باستخدام UPDATE مشروط — آمن للاستخدام المتزامن.
    إذا كان المستخدم مقيّداً (referral_points_blocked) يُرجع False مباشرةً دون خصم."""
    with db_conn() as c:
        restricted_row = c.execute(
            "SELECT referral_points_blocked FROM users WHERE user_id=%s", (user_id,)
        ).fetchone()
        if restricted_row and restricted_row["referral_points_blocked"]:
            return False  # مقيّد — لا يُسمح باستخدام النقاط
        c.execute(
            "UPDATE users SET points=points-%s WHERE user_id=%s AND points>=%s",
            (pts, user_id, pts)
        )
        return c.rowcount > 0

def deduct_points_clamped(user_id: int, pts: int) -> int:
    """يخصم نقاطاً بحد أقصى لا يقل عن صفر (لا يجعل الرصيد سالباً)، ويُرجع العدد الفعلي المخصوم."""
    with db_conn() as c:
        row = c.execute("SELECT points FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return 0
        current = row["points"] or 0
        actual = min(pts, current)
        if actual > 0:
            c.execute("UPDATE users SET points=points-%s WHERE user_id=%s", (actual, user_id))
        return actual

def get_user(user_id: int) -> dict | None:
    with db_conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

def next_order_code(user_id: int) -> str:
    """يُنشئ كود طلب فريد باستخدام UPDATE RETURNING لضمان عدم التكرار"""
    with db_conn() as c:
        c.execute(
            "UPDATE users SET total_orders=total_orders+1 WHERE user_id=%s RETURNING bot_user_num, total_orders",
            (user_id,)
        )
        u = c.fetchone()
        c.execute(
            "UPDATE settings SET value=(value::int+1)::text WHERE key='total_bot_orders' RETURNING value::int AS total",
        )
        row = c.fetchone()
        total = row["total"] if row else 1
        return f"{u['total_orders']}-{u['bot_user_num']}-{total}"

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
def smm_request(action: str, panel: int = 1, **params) -> dict:
    site = PANEL_MAP.get(int(panel), PANEL_MAP[1])
    payload = {"key": site["key"], "action": action, **params}
    try:
        r = requests.post(site["url"], data=payload, timeout=15)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

_services_cache: dict = {}  # panel -> (timestamp, list)
_SERVICES_CACHE_TTL = 3600  # ثانية

def smm_service_info(service_id: int, panel: int = 1) -> dict:
    now = time.time()
    cached = _services_cache.get(panel)
    if cached and now - cached[0] < _SERVICES_CACHE_TTL:
        services = cached[1]
    else:
        raw = smm_request("services", panel=panel)
        if isinstance(raw, list):
            services = raw
        elif isinstance(raw, dict) and "error" not in raw:
            services = []
            for k, v in raw.items():
                if isinstance(v, dict):
                    if "service" not in v:
                        v = dict(v, service=k)
                    services.append(v)
        else:
            site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
            logger.warning(f"⚠️ smm_service_info: رد غير متوقع من {site_name} (panel={panel}): {str(raw)[:300]}")
            return {}
        _services_cache[panel] = (now, services)
    for s in services:
        if str(s.get("service")) == str(service_id):
            return s
    return {}

def smm_create_order(service_id: int, link: str, quantity: int, panel: int = 1) -> dict:
    return smm_request("add", panel=panel, service=service_id, link=link, quantity=quantity)

def smm_order_status(order_id: str, panel: int = 1) -> dict:
    return smm_request("status", panel=panel, order=order_id)

LINK_ERROR_GUIDANCE = (
    "⚠️ *السبب الأكثر شيوعاً لهذا الخطأ هو إرسال رابط غير مطابق لنوع الخدمة.*\n\n"
    "📌 يرجى التأكد من التالي قبل إعادة الطلب:\n"
    "• إذا كانت الخدمة *لايكات / تعليقات / مشاهدات* ➜ أرسل رابط *المنشور (البوست)* نفسه، لا رابط الحساب.\n"
    "• إذا كانت الخدمة *متابعين / أعضاء* ➜ أرسل رابط *الحساب أو القناة* فقط، لا رابط منشور.\n"
    "• تأكد أن الرابط من *نفس المنصة* المطلوبة تماماً (إنستغرام، تيك توك، ...).\n"
    "• تأكد أن الحساب أو المنشور *عام (Public)* وغير خاص.\n\n"
    "🔁 بعد التأكد من الرابط الصحيح، أعد إرسال طلبك."
)

def _calc_partial_refund_pts(api_service_id: int, remains: int) -> int:
    """يحسب النقاط المستردّة من الطلب الجزئي لموقع SMMMAIN:
    المعادلة: (سعر الخدمة بالدولار / 1000) × الوحدات المتبقية × 100,000
    أي: 1000 نقطة لكل سنت يُستردّ (100,000 نقطة لكل دولار)."""
    try:
        svc_info = smm_service_info(api_service_id, panel=1)
        rate = float(svc_info.get("rate", 0) or 0)   # USD per 1000 units
        if rate <= 0 or remains <= 0:
            return 0
        refunded_usd   = (rate / 1000) * remains
        refunded_cents = refunded_usd * 100
        return max(1, round(refunded_cents * 1000))   # 1000 نقطة لكل سنت
    except Exception as e:
        logger.warning(f"⚠️ فشل حساب استرجاع الطلب الجزئي: {e}")
        return 0

def _format_elapsed(added_at) -> str:
    """يعيد نصاً يوضّح المدة المنقضية منذ إضافة الرقم للبوت."""
    try:
        if added_at is None:
            return "غير معروف"
        if added_at.tzinfo is None:
            added_at = added_at.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - added_at
        secs = int(delta.total_seconds())
        if secs < 60:
            return f"{secs} ثانية"
        mins = secs // 60
        if mins < 60:
            return f"{mins} دقيقة"
        hours = mins // 60
        if hours < 24:
            return f"{hours} ساعة"
        days = hours // 24
        return f"{days} يوم"
    except Exception:
        return "غير معروف"

_ARABIC_WEEKDAYS = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

def format_account_datetime(dt) -> str:
    """يهيّئ تاريخاً/وقتاً بالصيغة المطلوبة: 2028/8/8 الأربعاء 19:55"""
    try:
        if dt is None:
            return "غير معروف"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        weekday_ar = _ARABIC_WEEKDAYS[dt.weekday()]
        return f"{dt.year}/{dt.month}/{dt.day} {weekday_ar} {dt.strftime('%H:%M')}"
    except Exception:
        return "غير معروف"

_ARABIC_MONTHS = {
    1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو",
    7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر",
}

def translate_official_notice(text: str) -> str:
    """يترجم أشهر أنماط رسائل تيليجرام الرسمية الأمنية (من 777000) إلى العربية.
    تيليجرام يرسل هذه الرسائل بصيغ إنجليزية ثابتة معدودة؛ نطابقها بأنماط (regex)
    ونستخرج منها الحقول (التاريخ/الوقت/الجهاز/الموقع) ثم نعيد صياغتها عربياً.
    إن لم يُطابَق أي نمط معروف، تُعاد النسخة الأصلية كما هي بدلاً من كسر الرسالة."""
    if not text:
        return text
    original = text
    low = text.lower()

    def _fmt_date(y, mo, d):
        try:
            return f"{int(d)} {_ARABIC_MONTHS.get(int(mo), mo)} {y}"
        except Exception:
            return f"{d}/{mo}/{y}"

    # ─── نمط: "Two-Step Verification settings changed. ... changed on DD/MM/YYYY at HH:MM:SS UTC. Device: ... Location: ..."
    if "two-step verification" in low and "changed" in low:
        m_date = re.search(r"changed on\s+(\d{1,2})/(\d{1,2})/(\d{4})\s+at\s+([\d:]+)\s*(UTC)?", text, re.IGNORECASE)
        m_device = re.search(r"Device:\s*(.+?)(?:\n|$)", text)
        m_loc = re.search(r"Location:\s*(.+?)(?:\n|$)", text)
        parts = ["🔐 *تغيّرت إعدادات التحقق بخطوتين*", "تم تغيير كلمة مرور التحقق بخطوتين و/أو البريد الاحتياطي لهذا الحساب."]
        if m_date:
            day, mon, year, time_str = m_date.group(1), m_date.group(2), m_date.group(3), m_date.group(4)
            parts.append(f"🗓 الوقت: {_fmt_date(year, mon, day)} — {time_str} (توقيت UTC)")
        if m_device:
            parts.append(f"📱 الجهاز: {m_device.group(1).strip()}")
        if m_loc:
            parts.append(f"📍 الموقع: {m_loc.group(1).strip()}")
        parts.append("⚠️ إن لم يكن هذا التغيير معروفاً لك، راجع الجلسات النشطة فوراً.")
        return "\n".join(parts)

    # ─── نمط: "New login. We noticed a login into your account from a new device on ... Device: ... Location: ..."
    if ("new login" in low or "login from a new device" in low) and "device:" in low:
        m_device = re.search(r"Device:\s*(.+?)(?:\n|$)", text)
        m_loc = re.search(r"Location:\s*(.+?)(?:\n|$)", text)
        parts = ["🆕 *تسجيل دخول جديد على هذا الحساب*"]
        if m_device:
            parts.append(f"📱 الجهاز: {m_device.group(1).strip()}")
        if m_loc:
            parts.append(f"📍 الموقع: {m_loc.group(1).strip()}")
        parts.append("⚠️ إن لم يكن هذا تسجيل دخولك، راجع الجلسات النشطة فوراً.")
        return "\n".join(parts)

    # ─── نمط: رسالة كود تسجيل الدخول العادية ───
    if "login code" in low or "this code can be used to log" in low:
        m_code = re.search(r"\b(\d{4,7})\b", text)
        if m_code:
            return f"🔑 *كود تسجيل دخول*\n\nالكود: `{m_code.group(1)}`\n⚠️ لا تُعطِ هذا الكود لأي شخص، حتى لو زعم أنه من تيليجرام."

    # ─── نمط: تعطيل/تسجيل خروج الحساب ───
    if "account was" in low and ("deactivat" in low or "terminated" in low or "logged out" in low):
        return f"🔴 *تم تسجيل الخروج/تعطيل هذا الحساب من تيليجرام.*\n\n(النص الأصلي: {original})"

    # ─── لم يُطابَق أي نمط معروف: نُعيد النص الأصلي مع توضيح أنه لم تتم ترجمته تلقائياً ───
    return f"{original}\n\n(⚠️ لم تُترجم هذه الرسالة تلقائياً — نمط غير معروف)"

async def _kick_then_notify(bot, phone: str, stock_id: int, added_at, session_str: str):
    """يطرد كل الجلسات الإضافية فوراً (مع retry تلقائي) ثم يُرسل إشعاراً للمالك مع أزرار الإدارة."""
    kicked = False
    try:
        _kick_cl = TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await _kick_cl.connect()
        if await _kick_cl.is_user_authorized():
            try:
                await _kick_cl(ResetAuthorizationsRequest())
                kicked = True
                logger.info(f"🔐 _kick_then_notify: طُردت الجلسات الإضافية للرقم {phone}")
            except Exception as _re:
                err_s = str(_re)
                if "FROZEN_METHOD_INVALID" in err_s:
                    logger.warning(f"🧊 _kick_then_notify: الرقم {phone} مجمّد مؤقتاً — تعذّر الطرد")
                else:
                    # ─── الطرد الأول فشل (جلسة جديدة جداً) → retry في الخلفية ───
                    logger.info(f"⏳ _kick_then_notify: {phone} — سيُعاد المحاولة في الخلفية ({err_s[:60]})")
                    async def _delayed_kick_retry(ss, ph, bot_ref, s_id):
                        delay = 5
                        for attempt in range(1, 7):  # حتى 6 محاولات (إجمالي ~3 دقائق)
                            await asyncio.sleep(delay)
                            try:
                                _rc = TelegramClient(StringSession(ss), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                                await _rc.connect()
                                if not await _rc.is_user_authorized():
                                    await _rc.disconnect()
                                    logger.warning(f"⚠️ kick_retry: جلسة {ph} منتهية — إيقاف")
                                    break
                                await _rc(ResetAuthorizationsRequest())
                                await _rc.disconnect()
                                logger.info(f"🔒 kick_retry: طُردت جلسات {ph} بعد {delay} ث (محاولة {attempt})")
                                if bot_ref:
                                    try:
                                        await bot_ref.send_message(
                                            NUMBERS_GROUP_ID or OWNER_ID,
                                            f"🔒 تم طرد جلسات الرقم `{ph}` بعد {delay} ثانية (محاولة {attempt}).",
                                            parse_mode="Markdown"
                                        )
                                    except Exception:
                                        pass
                                # ─── تحديث can_send_code بعد نجاح الطرد المتأخر ───
                                try:
                                    with db_conn() as _db:
                                        _row = _db.execute(
                                            "SELECT id FROM number_stock WHERE phone_number=%s", (ph,)
                                        ).fetchone()
                                    if _row:
                                        asyncio.create_task(_test_and_set_can_send_code(ph, ss, _row["id"]))
                                except Exception:
                                    pass
                                break
                            except Exception as _re2:
                                _re2s = str(_re2)
                                if "too new" in _re2s or "cannot be used to reset" in _re2s or "NEW_SESSION" in _re2s:
                                    delay = min(delay * 2, 60)
                                    logger.info(f"⏳ kick_retry: {ph} لا يزال جديداً — انتظار {delay} ث...")
                                    try:
                                        await _rc.disconnect()
                                    except Exception:
                                        pass
                                else:
                                    logger.warning(f"⚠️ kick_retry: خطأ غير متوقع {ph}: {_re2s[:80]}")
                                    try:
                                        await _rc.disconnect()
                                    except Exception:
                                        pass
                                    break
                    asyncio.create_task(_delayed_kick_retry(session_str, phone, bot, stock_id))
        await _kick_cl.disconnect()
    except Exception as _e:
        logger.warning(f"⚠️ _kick_then_notify: فشل طرد {phone}: {_e}")

    await notify_new_login(bot, phone, added_at=added_at, stock_id=stock_id, kicked=kicked)

async def notify_account_change(bot, phone: str, change_desc: str, added_at=None, stock_id: int | None = None):
    """يُرسل إشعاراً موحّد الشكل عن أي تغيّر في حساب (طرد/تجميد/تغيّر أجهزة/تنبيه أمني...)
    إلى NUMBERS_GROUP_ID إن كان مضبوطاً، وإلا إلى OWNER_ID."""
    target = NUMBERS_GROUP_ID or OWNER_ID
    if not target:
        return
    assigned_to = None
    ever_sold   = False
    if stock_id is not None:
        try:
            with db_conn() as c:
                row = c.execute(
                    "SELECT added_at, assigned_to, ever_sold FROM number_stock WHERE id=%s", (stock_id,)
                ).fetchone()
                if row:
                    if added_at is None:
                        added_at = row["added_at"]
                    assigned_to = row["assigned_to"]
                    ever_sold   = bool(row["ever_sold"])
        except Exception:
            pass
    elif added_at is None:
        try:
            with db_conn() as c:
                row = c.execute(
                    "SELECT added_at, assigned_to, ever_sold FROM number_stock WHERE phone_number=%s", (phone,)
                ).fetchone()
                if row:
                    added_at    = row["added_at"]
                    assigned_to = row["assigned_to"]
                    ever_sold   = bool(row["ever_sold"])
        except Exception:
            pass
    if ever_sold or assigned_to:
        return

    sale_status = "❌ *غير مباع* — قد يكون اختراقاً!"
    text = (
        f"🔔 *تنبيه تغيّر في حساب*\n\n"
        f"التغيّر: {change_desc}\n"
        f"رقم الحساب: `{phone}`\n"
        f"الدولة: {guess_country(phone)}\n"
        f"وقت ادخال الحساب: {format_account_datetime(added_at)}\n"
        f"حالة الحساب: {sale_status}"
    )
    try:
        await bot.send_message(target, text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"❌ فشل إرسال تنبيه تغيّر الحساب {phone}: {e}")

async def notify_new_login(bot, phone: str, added_at=None, stock_id: int | None = None, kicked: bool = True):
    """يُرسل تنبيه دخول جديد مع أزرار الإدارة إلى NUMBERS_GROUP_ID أو OWNER_ID."""
    target = NUMBERS_GROUP_ID or OWNER_ID
    if not target:
        return
    kick_line = "✅ تم طرد الجلسة فوراً." if kicked else "⚠️ تعذّر الطرد التلقائي."
    text = (
        f"🚨 *دخول جديد على حساب غير مباع!*\n\n"
        f"📱 رقم الحساب: `{phone}`\n"
        f"🌍 الدولة: {guess_country(phone)}\n\n"
        f"{kick_line}\n\n"
        f"اضغط *سماح 5 دقائق* إذا أردت أن يتمكن شخص من الدخول مرة واحدة (الأول يدخل، الثاني يُطرد).\n"
        f"بعد انتهاء النافذة أو استخدامها يعود الطرد الفوري."
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ سماح 5 دقائق", callback_data=f"os:allow_5min:{phone}"),
            InlineKeyboardButton("📋 معلومات", callback_data=f"os:account_info:{phone}"),
        ],
        [
            InlineKeyboardButton("🚪 مغادرة البوت", callback_data=f"os:leave_account:{phone}"),
        ]
    ])
    try:
        await bot.send_message(target, text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    except Exception as e:
        logger.error(f"❌ فشل إرسال تنبيه دخول جديد {phone}: {e}")

async def request_manual_2fa_password(bot, phone: str, stock_id: int):
    """يُرسل طلباً (مع زر) لإدخال كلمة مرور التحقق بخطوتين إلى NUMBERS_GROUP_ID أو OWNER_ID."""
    target = NUMBERS_GROUP_ID or OWNER_ID
    if not target:
        return
    try:
        await bot.send_message(
            target,
            f"🔑 *طلب كلمة مرور التحقق بخطوتين الصحيحة*\n\n"
            f"رقم الحساب: `{phone}`\n"
            f"الدولة: {guess_country(phone)}\n\n"
            f"الكلمة الثابتة المعتمدة \"{OWNER_FIXED_2FA_PASSWORD}\" غير صحيحة على هذا الحساب. "
            f"اضغط الزر أدناه وأرسل كلمة المرور الصحيحة الفعلية لهذا الرقم.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📤 إرسال كلمة المرور الصحيحة الآن", callback_data=f"os:set_2fa_manual:{stock_id}")
            ]])
        )
    except Exception as e:
        logger.error(f"❌ فشل إرسال طلب كلمة مرور 2FA اليدوية للرقم {phone}: {e}")

async def monitor_number_changes_job(context: ContextTypes.DEFAULT_TYPE):
    """تم حذف هذه الوظيفة — كانت تفتح Telethon لكل رقم كل 30 دقيقة وتسبب نوم البوت."""
    return

async def retry_pending_session_resets(context: ContextTypes.DEFAULT_TYPE):
    """محاولة دورية لتسجيل خروج الجلسات الأخرى للأرقام التي فشل طردها فوراً بعد تسجيل الدخول
    (مثلاً بسبب قيود تيليجرام المؤقتة)، يعيد المحاولة كل دورة حتى تنجح، ثم يبلّغ المالك."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, phone_number, session_string, added_at FROM number_stock "
            "WHERE session_string IS NOT NULL AND (sessions_reset IS NULL OR sessions_reset=FALSE) AND assigned_to IS NULL AND ever_sold IS NOT TRUE"
        ).fetchall()
    for row in rows:
        rec = dict(row)
        client = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(client.connect(), timeout=20)
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                continue
            await client(ResetAuthorizationsRequest())
            # ─── فحص is_solo وcan_send_code بعد نجاح الطرد ─────────────────
            _dev_after = -1
            try:
                _dev_after = await get_device_count(client)
            except Exception:
                pass
            _is_solo_r = (_dev_after == 1)
            with db_conn() as c2:
                c2.execute(
                    "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s WHERE id=%s",
                    (_is_solo_r, rec["id"])
                )
            if _is_solo_r:
                asyncio.create_task(
                    _test_and_set_can_send_code(rec["phone_number"], rec["session_string"], rec["id"])
                )
            elapsed = _format_elapsed(rec["added_at"])
            if OWNER_ID:
                _solo_note = " | البوت الجلسة الوحيدة ✅" if _is_solo_r else " | يوجد جلسات أخرى بعد ⚠️"
                await context.bot.send_message(
                    OWNER_ID,
                    f"🔒 *تم أخيراً تسجيل خروج كل الجلسات الأخرى تلقائياً*\n\n"
                    f"📱 الرقم: `{rec['phone_number']}`\n"
                    f"⏱️ المدة منذ إضافته للبوت: {elapsed}{_solo_note}",
                    parse_mode=ParseMode.MARKDOWN
                )
            logger.info(f"🔒 تم تسجيل خروج الجلسات الأخرى (إعادة محاولة) للرقم {rec['phone_number']} | is_solo={_is_solo_r}")
        except Exception as e:
            err_str = str(e)
            if "FROZEN_METHOD_INVALID" in err_str or "frozen" in err_str.lower():
                logger.warning(f"🧊 الرقم {rec['phone_number']} مجمّد مؤقتاً عند تيليجرام (FROZEN_METHOD_INVALID) — سيُعاد المحاولة لاحقاً")
            else:
                logger.debug(f"⏳ إعادة محاولة لاحقاً لطرد جلسات الرقم {rec['phone_number']}: {e}")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
