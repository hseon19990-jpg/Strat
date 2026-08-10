
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
            " AND ever_sold IS NOT TRUE"
            " AND force_listed IS NOT TRUE"
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
    selected = nums[:quantity]
    done = failed = reactivated = 0
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

    for _idx, num in enumerate(selected, 1):
        try:
            ok, reactiv, _ = await do_referral_for_number(
                num['phone_number'], num['session_string'],
                bot_user, start_p,
                mandatory_channels=channels or '',
                folder_link='',
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

        # ─── تحديث رسالة التقدم الحي (كل 3 ثوانٍ أو عند آخر حساب) ───
        _now = _time.monotonic()
        if _live_msg and (_now - _last_edit_time >= _EDIT_INTERVAL or _idx == len(selected)):
            try:
                await context.bot.edit_message_text(
                    _mansub_progress_text(_idx),
                    chat_id=requester_id,
                    message_id=_live_msg.message_id,
                    parse_mode='HTML'
                )
                _last_edit_time = _now
            except Exception:
                pass

        import asyncio as _aio2
        await _aio2.sleep(2)

    # ─── استرداد نقاط الحسابات الفاشلة فقط (إعادة التفعيل لا تُعوَّض) ───
    if failed > 0 and _cost_each > 0:
        refunded_pts = failed * _cost_each
        add_points(requester_id, refunded_pts)

    with db_conn() as c:
        c.execute("UPDATE mandatory_sub_orders SET status='done' WHERE id=%s", (order_id,))

    _refund_line  = f'\n💰 <b>استرداد تلقائي:</b> {refunded_pts:,} نقطة (عن {failed} فاشل)' if refunded_pts > 0 else ''
    _reactiv_note = f'\n⚠️ <i>الحسابات التي كان البوت مفعّلاً بها مسبقاً لا تستحق تعويضاً</i>' if reactivated > 0 else ''
    _final_text = (
        f'✅ <b>اكتمل طلب الاشتراك الإجباري!</b>\n'
        f'📌 @{bot_user}\n\n'
        f'✅ الحسابات الناجحة: {done}\n'
        f'❌ الفاشلة: {failed}\n'
        f'🔄 إعادة تفعيل البوت: {reactivated}'
        f'{_refund_line}{_reactiv_note}'
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
        f'🔑 اشتراك إجباري اكتمل | 👤 {requester_id} | @{bot_user} | ✅{done} ❌{failed} 🔄{reactivated} | استرداد {refunded_pts:,}نقطة',
        parse_mode='Markdown'
    )

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
    cost_pts_each = bp + ch_count * cp     # للدفع بالنقاط: حساب + قنوات
    # النجوم للحسابات فقط — القنوات تُخصم من النقاط
    if use_ai:
        # 1.5 نجمة/حساب → لكل حسابين = 3 نجوم (أعداد زوجية مضمونة)
        total_stars = qty * 3 // 2
    else:
        total_stars = qty  # 1 نجمة/حساب
    total_pts = cost_pts_each * qty
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
        f'🔑 *طلب إحالة بوت اجباري (نقاط)*\n👤 {user.id}\n📌 `@{bot_user}` | `{start_p if start_p else "بدون كود"}`\n🔢 {qty} | 💎 {total:,} نقطة\n🎫 `{code}`',
        parse_mode='Markdown'
    )
    import asyncio as _aio
    _use_ai = draft.get('use_ai', False)
    _aio.create_task(_run_forced_ref_order(order_id, bot_user, start_p, channels, qty, user.id, context, use_ai=_use_ai, payment_method='points', cost_stars=0))

async def _run_forced_ref_order(order_id, bot_user, start_p, channels, quantity, requester_id, context,
                               use_ai: bool = False, payment_method: str = 'points', cost_stars: int = 0):
    import random as _rnd
    import time as _time
    with db_conn() as c:
        c.execute("UPDATE forced_ref_orders SET status='running' WHERE id=%s", (order_id,))
        rows = c.execute(
            "SELECT id,phone_number,session_string FROM number_stock"
            " WHERE session_string IS NOT NULL AND deleted_at IS NULL AND assigned_to IS NULL"
            " AND ever_sold IS NOT TRUE"
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
    selected = nums[:quantity]
    done = failed = reactivated = 0
    refunded_pts = 0

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

    for _idx_f, num in enumerate(selected, 1):
        try:
            ok, reactiv, _ = await do_referral_for_number(
                num['phone_number'], num['session_string'],
                bot_user, start_p,
                mandatory_channels=_all_channels,
                folder_link='',
                use_ai=use_ai,
            )
        except Exception:
            ok = False; reactiv = False
        with db_conn() as c:
            if ok and reactiv:
                c.execute("UPDATE forced_ref_orders SET reactivated_count=reactivated_count+1 WHERE id=%s", (order_id,))
                reactivated += 1
            elif ok:
                c.execute("UPDATE forced_ref_orders SET done_count=done_count+1 WHERE id=%s", (order_id,))
                done += 1
            else:
                c.execute("UPDATE forced_ref_orders SET failed_count=failed_count+1 WHERE id=%s", (order_id,))
                failed += 1

        # ─── تحديث رسالة التقدم الحي (كل 3 ثوانٍ أو عند آخر حساب) ───
        _now_f = _time.monotonic()
        if _live_msg_f and (_now_f - _last_edit_time_f >= _EDIT_INTERVAL_F or _idx_f == len(selected)):
            try:
                await context.bot.edit_message_text(
                    _forced_ref_progress_text(_idx_f),
                    chat_id=requester_id,
                    message_id=_live_msg_f.message_id,
                    parse_mode='HTML'
                )
                _last_edit_time_f = _now_f
            except Exception:
                pass

        import asyncio as _aio2
        await _aio2.sleep(2)

    # ─── حساب التعويضات ───
    # الفاشلة: تُعوَّض دائماً (نقاط أو نجوم → نقاط)
    if failed > 0:
        if payment_method == 'stars' and _cost_stars_each > 0:
            refunded_pts = failed * (_cost_stars_each * _star_rate)
        elif _cost_pts_each > 0:
            refunded_pts = failed * _cost_pts_each
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
        _refund_parts.append(f'الفاشلة: {refunded_pts:,} نقطة ({failed} حساب)')
    if reactiv_refunded_pts > 0:
        _refund_parts.append(f'المكررة: {reactiv_refunded_pts:,} نقطة ({reactivated} حساب)')
    _refund_line = '\n💰 <b>التعويض:</b> ' + ' | '.join(_refund_parts) if _refund_parts else ''

    _stars_note = ''
    if payment_method == 'stars' and reactivated > 0:
        _stars_note = '\n✅ <i>لأنك دفعت بالنجوم، تم تعويض المكررة أيضاً (250 نقطة لكل نجمة مدفوعة)</i>'
    elif payment_method != 'stars' and reactivated > 0:
        _stars_note = '\n⚠️ <i>الإحالات المكررة لا تُعوَّض عند الدفع بالنقاط</i>'

    _final_text_f = (
        f'✅ <b>اكتملت إحالة البوت الإجبارية{_ai_label}!</b>\n'
        f'📌 @{bot_user}\n\n'
        f'✅ الإحالة الناجحة: {done}\n'
        f'❌ الإحالة الفاشلة: {failed}\n'
        f'🔄 إحالة مكررة (مفعّل سابقاً): {reactivated}'
        f'{_refund_line}{_stars_note}'
    )
    # تحديث نفس رسالة التقدم بالنتيجة النهائية، أو إرسال رسالة جديدة إن تعذّر التحديث
    if _live_msg_f:
        try:
            await context.bot.edit_message_text(
                _final_text_f,
                chat_id=requester_id,
                message_id=_live_msg_f.message_id,
                parse_mode='HTML'
            )
        except Exception:
            try:
                await context.bot.send_message(requester_id, _final_text_f, parse_mode='HTML')
            except Exception:
                pass
    else:
        try:
            await context.bot.send_message(requester_id, _final_text_f, parse_mode='HTML')
        except Exception:
            pass
    await _maybe_send_to_group(
        context.bot, requester_id,
        f'🔑 إحالة بوت اجباري اكتملت | 👤 {requester_id} | @{bot_user} | ✅{done} ❌{failed} 🔄{reactivated} | تعويض {refunded_pts + reactiv_refunded_pts:,}نقطة | {payment_method}',
        parse_mode='Markdown'
    )

async def run_referral_tasks_job(context: ContextTypes.DEFAULT_TYPE):
    """تُشغَّل كل ساعة: تُكمل الإحالات لكل الأرقام التي لم تُنفّذها بعد."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    tasks = get_referral_tasks(only_active=True)
    if not tasks:
        return
    for task in tasks:
        pending = get_pending_numbers_for_task(task["id"])
        if not pending:
            continue
        logger.info(f"🤝 مهمة إحالة [{task['label']}]: {len(pending)} رقم معلّق")
        done = failed = 0
        for num in pending:
            # تخطي الأرقام التي لم تحصل على جلسة بعد (ستُشمل تلقائياً في الدورة القادمة)
            if not num.get("session_string"):
                continue
            success, _reactiv_t, detail = await do_referral_for_number(
                num["phone_number"], num["session_string"],
                task["bot_username"], task["start_param"],
                mandatory_channels=task.get("mandatory_channels", "") or "",
                folder_link=task.get("folder_link", "") or "",
            )
            status = "done" if success else "failed"
            mark_referral_completion(task["id"], num["id"], status,
                                     None if success else detail)
            if success:
                done += 1
            else:
                failed += 1
            await asyncio.sleep(2)   # فاصل بين أرقام لتفادي flood
        logger.info(f"✅ مهمة [{task['label']}]: {done} نجحت، {failed} فشلت")
        if OWNER_ID:
            try:
                await context.bot.send_message(
                    OWNER_ID,
                    f"🤝 *مهمة إحالة: {task['label']}*\n\n"
                    f"✅ نجحت: {done}\n❌ فشلت: {failed}",
                    parse_mode=ParseMode.MARKDOWN
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
        await client.connect()
        if not await client.is_user_authorized():
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
                # ─── كلمة المرور غير معروفة وليست "محمد" → نطلب إعادة تعيين 7 أيام ───
                import datetime as _dt_r
                try:
                    await client(ResetPasswordRequest())
                    _reset_date = _dt_r.datetime.now(_dt_r.timezone.utc) + _dt_r.timedelta(days=7)
                    with db_conn() as _rc:
                        _rc.execute(
                            "UPDATE number_stock SET twofa_reset_date=%s WHERE id=%s",
                            (_reset_date, stock_id)
                        )
                    logger.info(f"🔐 بدأ إجراء إعادة تعيين 2FA (7 أيام) للرقم {phone}")
                    if bot is not None:
                        try:
                            await bot.send_message(
                                NUMBERS_GROUP_ID or OWNER_ID,
                                f"⏳ *إعادة تعيين 2FA — انتظار 7 أيام*\n\n"
                                f"📱 الرقم: `{phone}`\n"
                                f"🔐 كلمة المرور الثابتة \"{OWNER_FIXED_2FA_PASSWORD}\" غير صحيحة.\n"
                                f"✅ تم تشغيل إجراء نسيان التحقق تلقائياً.\n"
                                f"📅 سيتم تعيين كلمة المرور الجديدة تلقائياً بعد 7 أيام.",
                                parse_mode="Markdown"
                            )
                        except Exception:
                            pass
                    return False, "تم تشغيل إعادة التعيين — ستُضبط كلمة المرور تلقائياً بعد 7 أيام", None
                except Exception as _rp_e:
                    logger.warning(f"⚠️ فشل تشغيل ResetPasswordRequest للرقم {phone}: {_rp_e}")
                    if bot is not None:
                        try:
                            await request_manual_2fa_password(bot, phone, stock_id)
                        except Exception:
                            pass
                    return False, f"كلمة المرور الثابتة \"{OWNER_FIXED_2FA_PASSWORD}\" غير صحيحة ولم ينجح إجراء الإعادة: {str(_rp_e)[:60]}", None
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
        sent = await asyncio.wait_for(new_client.send_code_request(phone_clean), timeout=20)
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
        success, result = await _rotate_one_session(phone, rec["session_string"])

        if success:
            new_ss = result
            with db_conn() as _cx:
                _cx.execute(
                    "UPDATE number_stock SET session_string=%s, sessions_reset=TRUE WHERE id=%s",
                    (new_ss, rec["id"])
                )
            asyncio.create_task(_start_number_monitor(phone, new_ss, context.application))
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
                if _is_solo_now:
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
        try:
            await _start_number_monitor(phone, session_str, context.application)
        except Exception as e:
            logger.warning(f"⚠️ تعذر بدء مراقبة الرقم {phone}: {e}")
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

def is_user_verified(user_id: int) -> bool:
    with db_conn() as c:
        row = c.execute("SELECT verified FROM users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row["verified"])


def is_user_banned(user_id: int) -> bool:
    with db_conn() as c:
        row = c.execute("SELECT banned FROM users WHERE user_id=%s", (user_id,)).fetchone()
        return bool(row and row["banned"])

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
    """خصم نقاط بشكل ذري باستخدام UPDATE مشروط — آمن للاستخدام المتزامن"""
    with db_conn() as c:
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
    """يطرد كل الجلسات الإضافية فوراً ثم يُرسل إشعاراً للمالك مع أزرار الإدارة."""
    kicked = False
    try:
        _kick_cl = TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await _kick_cl.connect()
        if await _kick_cl.is_user_authorized():
            await _kick_cl(ResetAuthorizationsRequest())
            kicked = True
            logger.info(f"🔐 _kick_then_notify: طُردت الجلسات الإضافية للرقم {phone}")
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
    """مهمة دورية: تفحص كل رقم بالمخزون له جلسة، وتقارن حالته الحالية (تجميد/تصريح/عدد الأجهزة)
    بآخر حالة معروفة محفوظة بقاعدة البيانات. أي اختلاف عن آخر مرة يُبلَّغ للمالك فوراً
    بالصيغة الموحّدة (التغيّر/رقم الحساب/الدولة/وقت الإدخال)، ثم تُحفظ الحالة الجديدة كمرجع للمقارنة القادمة.
    لا تُرسل أي رسائل فعلية لأي بوت خارجي (مثل SpamBot) لتجنّب أي نشاط آلي مكثّف قد يرفع خطر الحظر."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, phone_number, session_string, added_at, last_frozen, last_authorized, last_device_count, bot_session_ip "
            "FROM number_stock WHERE session_string IS NOT NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE"
        ).fetchall()
    for row in rows:
        rec = dict(row)
        client = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await client.connect()
            authorized = await client.is_user_authorized()
            is_frozen, _, _ = (False, None, None)
            devices = -1
            if authorized:
                is_frozen, _, _ = await check_account_frozen(client, rec["id"])
                devices = await get_device_count(client)

            # ═══════════════════════════════════════════════════════════════
            # ═══════════════════════════════════════════════════════════════
            if authorized and rec.get("bot_session_ip"):
                try:
                    _cur_ip = await get_session_ip(client)
                    if _cur_ip and _cur_ip != rec["bot_session_ip"]:
                        logger.warning(
                            f"🚨 SILENT HIJACK: {rec['phone_number']} "
                            f"IP تغيّر من {rec['bot_session_ip']} إلى {_cur_ip}"
                        )
                        try:
                            await asyncio.wait_for(client.log_out(), timeout=10)
                        except Exception:
                            pass
                        with db_conn() as _hj:
                            _hj.execute(
                                "UPDATE number_stock SET session_string=NULL, bot_session_ip=NULL, "
                                "last_authorized=FALSE, is_solo=FALSE, sessions_reset=FALSE "
                                "WHERE id=%s",
                                (rec["id"],)
                            )
                        try:
                            await _stop_number_monitor(rec["phone_number"])
                        except Exception:
                            pass
                        _hj_target = NUMBERS_GROUP_ID or OWNER_ID
                        if _hj_target:
                            try:
                                await context.bot.send_message(
                                    _hj_target,
                                    f"🚨 *خطف جلسة مكتشَف!*\n\n"
                                    f"📱 الرقم: `{rec['phone_number']}`\n"
                                    f"🖥 IP البوت السابق: `{rec['bot_session_ip']}`\n"
                                    f"🔴 IP الخاطف: `{_cur_ip}`\n\n"
                                    f"✅ *تم إلغاء الجلسة نهائياً.*\n"
                                    f"ملف الجلسة القديم أصبح عديم الفائدة تماماً.\n\n"
                                    f"⚠️ يجب إعادة إضافة الرقم بجلسة جديدة.",
                                    parse_mode="Markdown"
                                )
                            except Exception:
                                pass
                        continue  # ننتقل للرقم التالي بعد التعامل مع الاختراق
                except Exception as _hj_e:
                    logger.debug(f"⚠️ فحص IP الجلسة فشل للرقم {rec['phone_number']}: {_hj_e}")

            changes = []
            last_authorized = rec["last_authorized"] if rec["last_authorized"] is not None else True
            last_frozen = bool(rec["last_frozen"])
            last_devices = rec["last_device_count"] if rec["last_device_count"] is not None else -1

            just_kicked = False
            if last_authorized and not authorized:
                changes.append("تم طرد الحساب (تسجيل خروج/انتهاء الجلسة من تيليجرام)")
                just_kicked = True
            elif not last_authorized and authorized:
                changes.append("عاد الحساب مصرَّحاً (تسجيل الدخول سليم من جديد)")

            if authorized:
                if is_frozen and not last_frozen:
                    changes.append("تم تجميد الحساب 🔴")
                elif last_frozen and not is_frozen:
                    changes.append("تم رفع التجميد عن الحساب (نشط الآن)")
                if devices >= 0 and last_devices >= 0 and devices != last_devices:
                    changes.append(f"تغيّر عدد الأجهزة المسجّلة من {last_devices} إلى {devices}")

            # ─── منطق الجهاز الثاني ───────────────────────────────────────────────
            if authorized and devices > 0:
                owner_logging = any(
                    p.get("phone") == rec["phone_number"]
                    for p in _pending_number_logins.values()
                )
                with db_conn() as _ca:
                    _ass = _ca.execute(
                        "SELECT assigned_to, ever_sold FROM number_stock WHERE id=%s", (rec["id"],)
                    ).fetchone()
                    is_assigned  = bool(_ass and _ass["assigned_to"])
                    is_ever_sold = bool(_ass and _ass["ever_sold"])

                is_sold = is_assigned or is_ever_sold
                device_count_rose = (
                    last_devices >= 1 and devices > last_devices
                )

                if not owner_logging:
                    if is_sold and device_count_rose:
                        buyer_id_exit = _ass["assigned_to"] if _ass else None
                        phone_exit    = rec["phone_number"]
                        stock_id_exit = rec["id"]
                        logger.info(
                            f"🚪 bot_exit_sold_account: {phone_exit} — "
                            f"أجهزة ارتفعت {last_devices}→{devices}، انتظار 10 ث ثم مغادرة."
                        )

                        async def _delayed_exit(phone_e, stock_id_e, buyer_e):
                            await asyncio.sleep(15)
                            _sess_del = None
                            try:
                                with db_conn() as _dsx:
                                    _sr_del = _dsx.execute(
                                        "SELECT session_string FROM number_stock WHERE phone_number=%s", (phone_e,)
                                    ).fetchone()
                                    if _sr_del:
                                        _sess_del = _sr_del["session_string"]
                            except Exception:
                                pass
                            try:
                                await _stop_number_monitor(phone_e)
                            except Exception:
                                pass
                            # ─── طرد الجلسة الدائمة (إن وُجدت) قبل مغادرة البوت ───
                            if _sess_del and TELEGRAM_API_ID and TELEGRAM_API_HASH and phone_e in _permanently_allowed_phones:
                                try:
                                    _kick_cli = TelegramClient(
                                        StringSession(_sess_del),
                                        int(TELEGRAM_API_ID), TELEGRAM_API_HASH
                                    )
                                    await asyncio.wait_for(_kick_cli.connect(), timeout=10)
                                    _auths = await asyncio.wait_for(
                                        _kick_cli(GetAuthorizationsRequest()), timeout=10
                                    )
                                    _others = sorted(
                                        [a for a in _auths.authorizations if not a.current],
                                        key=lambda a: a.date_created
                                    )
                                    for _a in _others[:-1]:
                                        try:
                                            await asyncio.wait_for(
                                                _kick_cli(ResetAuthorizationRequest(hash=_a.hash)),
                                                timeout=8
                                            )
                                        except Exception:
                                            pass
                                    try:
                                        await _kick_cli.disconnect()
                                    except Exception:
                                        pass
                                    _permanently_allowed_phones.discard(phone_e)
                                    logger.info(f"✅ delayed_exit: طُرد الشخص الدائم من {phone_e} — المشتري يبقى وحده")
                                except Exception as _pe:
                                    logger.warning(f"⚠️ delayed_exit: فشل طرد الشخص الدائم من {phone_e}: {_pe}")
                            _permanently_allowed_phones.discard(phone_e)
                            # ─── تسجيل خروج البوت فعلياً — المشتري يبقى الوحيد ───
                            _logout_ok = False
                            if _sess_del and TELEGRAM_API_ID and TELEGRAM_API_HASH:
                                try:
                                    _lo_del = TelegramClient(
                                        StringSession(_sess_del),
                                        int(TELEGRAM_API_ID), TELEGRAM_API_HASH
                                    )
                                    await asyncio.wait_for(_lo_del.connect(), timeout=15)
                                    await asyncio.wait_for(_lo_del.log_out(), timeout=15)
                                    _logout_ok = True
                                    logger.info(f"✅ delayed_exit: سجّل البوت خروجه من {phone_e} بنجاح")
                                except Exception as _lo_err:
                                    logger.warning(f"⚠️ delayed_exit: فشل log_out للرقم {phone_e}: {_lo_err}")
                            with db_conn() as _cx:
                                _cx.execute(
                                    "UPDATE number_stock SET assigned_to=NULL, assigned_at=NULL WHERE id=%s",
                                    (stock_id_e,)
                                )
                            _buyer_received_codes.pop(buyer_e, None)
                            if buyer_e:
                                try:
                                    _msg = (
                                        "✅ *دخلت للحساب بنجاح!*\n\n"
                                        "البوت غادر الحساب تلقائياً. الحساب أصبح بيدك كاملاً 🤍"
                                        if _logout_ok else
                                        "✅ *دخلت للحساب!*\n\n"
                                        "⚠️ تعذّر على البوت تسجيل الخروج تلقائياً — تواصل مع المالك."
                                    )
                                    await context.bot.send_message(
                                        buyer_e,
                                        _msg,
                                        parse_mode="Markdown"
                                    )
                                except Exception:
                                    pass
                            _ng = NUMBERS_GROUP_ID or OWNER_ID
                            if _ng:
                                try:
                                    await context.bot.send_message(
                                        _ng,
                                        f"🚪 <b>خروج تلقائي — دخل المشتري</b>\n\n"
                                        f"📱 <code>{phone_e}</code>\n"
                                        f"📲 الأجهزة: {last_devices} → {devices}\n"
                                        f"✅ البوت غادر وأنهى علاقته بالحساب 100%.",
                                        parse_mode="HTML"
                                    )
                                except Exception:
                                    pass

                        asyncio.create_task(_delayed_exit(phone_exit, stock_id_exit, buyer_id_exit))

                    elif not is_sold and devices > 1:
                        _phone_key = rec["phone_number"]
                        _now = time.time()
                        _win = _allow_5min_phones.get(_phone_key)

                        if _phone_key in _permanently_allowed_phones:
                            logger.debug(f"✅ monitor: جلسة دائمة مسموح بها للرقم {_phone_key} — لا طرد")

                        elif _win and _win["until"] > _now and not _win["used"]:
                            _allow_5min_phones.pop(_phone_key, None)
                            _permanently_allowed_phones.add(_phone_key)
                            logger.info(f"✅ monitor: دخول مسموح (نافذة 5 دق) للرقم {_phone_key} — يبقى للأبد")
                            changes.append("✅ دخول مسموح به — الجلسة تبقى للأبد، النافذة أُغلقت")

                        else:
                            try:
                                await client(ResetAuthorizationsRequest())
                                logger.info(f"🔒 monitor: طُردت الجلسات الدخيلة للرقم {_phone_key} عبر عميل المراقبة")
                                asyncio.create_task(notify_new_login(
                                    context.bot, _phone_key,
                                    added_at=rec["added_at"], stock_id=rec["id"], kicked=True
                                ))
                                changes.append("🚨 جلسة دخيلة — طُردت فوراً عبر عميل المراقبة")
                            except Exception as _mk:
                                logger.warning(f"⚠️ monitor kick فشل للرقم {_phone_key}: {_mk}")
                                asyncio.create_task(_kick_then_notify(
                                    context.bot, _phone_key, rec["id"], rec["added_at"],
                                    rec["session_string"]
                                ))
                                changes.append("🚨 جلسة دخيلة — جارٍ الطرد...")

            if changes:
                await notify_account_change(
                    context.bot, rec["phone_number"], "، ".join(changes),
                    added_at=rec["added_at"], stock_id=rec["id"]
                )

            # ─── حساب is_solo: البوت الجلسة الوحيدة؟ ────────────────────────
            new_is_solo = authorized and (devices == 1) if devices >= 0 else False
            prev_is_solo = False
            with db_conn() as _pcheck:
                _prow = _pcheck.execute(
                    "SELECT is_solo, can_send_code, ever_sold FROM number_stock WHERE id=%s", (rec["id"],)
                ).fetchone()
                if _prow:
                    prev_is_solo  = bool(_prow["is_solo"])
            with db_conn() as c2:
                if just_kicked:
                    # ─── حذف تلقائي: البوت فقد السيطرة على الحساب ──────────────
                    # إذا لم يُباع الحساب → احذفه نهائياً (لا فائدة منه)
                    _is_ever_sold = bool(_prow and _prow.get("ever_sold"))
                    if not _is_ever_sold:
                        c2.execute("DELETE FROM number_stock WHERE id=%s", (rec["id"],))
                        logger.info(
                            f"🗑️ حذف تلقائي: الرقم {rec['phone_number']} — "
                            f"انتهت جلسته وفقد البوت السيطرة عليه."
                        )
                        asyncio.create_task(_stop_number_monitor(rec["phone_number"]))
                    else:
                        # مباع سابقاً → اكتفِ بالتحديث للأرشيف
                        c2.execute(
                            "UPDATE number_stock SET last_authorized=%s, last_frozen=%s, last_device_count=%s, "
                            "is_solo=%s, kicked_at=NOW(), sessions_reset=TRUE WHERE id=%s",
                            (authorized, is_frozen if authorized else last_frozen,
                             devices if devices >= 0 else last_devices, new_is_solo, rec["id"])
                        )
                else:
                    c2.execute(
                        "UPDATE number_stock SET last_authorized=%s, last_frozen=%s, last_device_count=%s, "
                        "is_solo=%s WHERE id=%s",
                        (authorized, is_frozen if authorized else last_frozen,
                         devices if devices >= 0 else last_devices, new_is_solo, rec["id"])
                    )
            # ─── إذا أصبح البوت للتو الجلسة الوحيدة → اختبر can_send_code ─
            if new_is_solo and not prev_is_solo and _prow and not _prow["ever_sold"] and not _prow["can_send_code"]:
                asyncio.create_task(
                    _test_and_set_can_send_code(rec["phone_number"], rec["session_string"], rec["id"])
                )
        except Exception as e:
            logger.debug(f"⏳ تعذّر فحص تغيّرات الرقم {rec['phone_number']} بهذه الدورة: {e}")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        await asyncio.sleep(2)  # تباعد بين كل حساب والآخر لتجنّب أي نشاط مكثّف من نفس السيرفر

async def _stop_number_monitor(phone: str):
    """يوقف مراقبة رقم معيّن نهائياً (يُستخدم عند حذف الرقم نهائياً من سلة المهملات)."""
    client = _monitor_clients.pop(phone, None)
    task = _monitor_tasks.pop(phone, None)
    if client is not None:
        try:
            await client.disconnect()
        except Exception:
            pass
    if task is not None:
        try:
            task.cancel()
        except Exception:
            pass

async def _start_number_monitor(phone: str, session_str: str, application):
    """يفتح اتصالاً دائماً بحساب هذا الرقم ليراقب أي تنبيهات أمنية تصله من تيليجرام الرسمي
    (جلسة دخول جديدة، تغيير كلمة المرور، إضافة/تغيير بريد الاسترجاع، ...) ويبلّغ المالك فوراً.

    ⚠️ السبب الجذري لعدم وصول الإشعارات سابقاً: كان الكلايانت يتصل فقط بدون تشغيل
    حلقة استقبال التحديثات. Telethon لا يُطلق أحداث NewMessage إلا إذا كانت هناك مهمة
    run_until_disconnected() تعمل بالخلفية. الإصلاح: asyncio.create_task.
    """
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    if phone in _monitor_clients:
        return

    client = TelegramClient(
        StringSession(session_str),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )

    async def _on_official_message(event):
        try:
            text = (event.raw_text or "").strip()
            if not text:
                return

            # ─── جلب حالة الرقم من DB (مشترٍ + id المخزون) ───
            buyer_id = None
            stock_id = None
            try:
                with db_conn() as c:
                    row = c.execute(
                        "SELECT id, assigned_to FROM number_stock WHERE phone_number=%s", (phone,)
                    ).fetchone()
                    if row:
                        buyer_id = row["assigned_to"]
                        stock_id = row["id"]
            except Exception:
                pass

            is_new_login_msg = (
                "new login" in text.lower() or
                "login from a new device" in text.lower() or
                ("we noticed" in text.lower() and "device" in text.lower())
            )

            # ─── إذا وصلت رسالة "تسجيل دخول جديد" → نحدد هل هي مصرّح بها أم لا ───
            if is_new_login_msg:
                owner_is_logging_in = any(
                    p.get("phone") == phone
                    for p in _pending_number_logins.values()
                )
                buyer_owns_it = bool(buyer_id)

                if buyer_owns_it and not owner_is_logging_in:
                    _bid_snap   = buyer_id
                    _phone_snap = phone
                    _app_snap   = application

                    async def _exit_after_delay():
                        await asyncio.sleep(0)
                        # ─── أوقف المراقبة واحصل على الجلسة قبل إيقافها ───
                        _sess_for_logout = None
                        try:
                            with db_conn() as _dcs:
                                _srow = _dcs.execute(
                                    "SELECT session_string FROM number_stock WHERE phone_number=%s", (_phone_snap,)
                                ).fetchone()
                                if _srow:
                                    _sess_for_logout = _srow["session_string"]
                        except Exception:
                            pass
                        try:
                            await _stop_number_monitor(_phone_snap)
                        except Exception:
                            pass
                        # ─── تسجيل خروج البوت فقط — المشتري يبقى الوحيد في الحساب ───
                        if _sess_for_logout and TELEGRAM_API_ID and TELEGRAM_API_HASH:
                            try:
                                _lo = TelegramClient(
                                    StringSession(_sess_for_logout),
                                    int(TELEGRAM_API_ID), TELEGRAM_API_HASH
                                )
                                await asyncio.wait_for(_lo.connect(), timeout=10)
                                await asyncio.wait_for(_lo.log_out(), timeout=10)
                            except Exception:
                                pass
                        try:
                            with db_conn() as _clv:
                                _clv.execute(
                                    "UPDATE number_stock SET assigned_to=NULL, assigned_at=NULL, force_listed=FALSE "
                                    "WHERE phone_number=%s",
                                    (_phone_snap,)
                                )
                            _buyer_received_codes.pop(_bid_snap, None)
                            await _app_snap.bot.send_message(
                                _bid_snap,
                                "✅ *دخلت للحساب بنجاح!*\n\n"
                                "البوت غادر الحساب تلقائياً. الحساب أصبح بيدك كاملاً 🤍",
                                parse_mode="Markdown"
                            )
                        except Exception as _le:
                            logger.warning(f"⚠️ تعذّر المغادرة التلقائية للرقم {_phone_snap}: {_le}")

                    asyncio.create_task(_exit_after_delay())
                    return

                _ever_sold = False
                try:
                    with db_conn() as _ces:
                        _es_row = _ces.execute(
                            "SELECT ever_sold FROM number_stock WHERE phone_number=%s", (phone,)
                        ).fetchone()
                        _ever_sold = bool(_es_row and _es_row["ever_sold"])
                except Exception:
                    pass

                if not owner_is_logging_in and not buyer_owns_it and not _ever_sold:
                    # ─── جلسة غير مصرّح بها على رقم لم يُباع قط → نطردها فوراً ───
                    logger.warning(f"🔐 جلسة دخول غير مصرّح بها على الرقم {phone} — يتم الطرد الفوري...")
                    try:
                        await client(ResetAuthorizationsRequest())
                        logger.info(f"✅ تم طرد كل الجلسات الأخرى للرقم {phone} بنجاح.")
                        _ng_sec = NUMBERS_GROUP_ID or OWNER_ID
                        if _ng_sec:
                            await application.bot.send_message(
                                _ng_sec,
                                (
                                    "🚨 *تنبيه أمني: تم طرد جلسة غير مصرّح بها*\n\n"
                                    f"📱 الرقم: `{phone}`\n"
                                    f"🌍 الدولة: {guess_country(phone)}\n"
                                    "✅ تم طرد الجلسة الغريبة تلقائياً."
                                ),
                                parse_mode=ParseMode.MARKDOWN,
                            )
                    except Exception as kick_err:
                        logger.error(f"❌ فشل طرد الجلسة للرقم {phone}: {kick_err}")
                    return  # لا ترسل أي إشعار آخر لهذه الرسالة

                if not owner_is_logging_in and not buyer_owns_it and _ever_sold:
                    return

            # ─── إرسال الكود للمشتري — أرقام فقط، بعد تاريخ البيع فقط ───
            if buyer_id and any(ch.isdigit() for ch in text):
                _skip_old = False
                try:
                    with db_conn() as _c2:
                        _row_at = _c2.execute(
                            "SELECT assigned_at FROM number_stock WHERE phone_number=%s", (phone,)
                        ).fetchone()
                    if _row_at and _row_at["assigned_at"]:
                        _assigned_ts = _row_at["assigned_at"]
                        _msg_date = getattr(event, "date", None)
                        if _msg_date and _assigned_ts:
                            import datetime as _dt
                            if _msg_date.tzinfo is None:
                                _msg_date = _msg_date.replace(tzinfo=_dt.timezone.utc)
                            if hasattr(_assigned_ts, "tzinfo") and _assigned_ts.tzinfo is None:
                                _assigned_ts = _assigned_ts.replace(tzinfo=_dt.timezone.utc)
                            if _msg_date < _assigned_ts:
                                _skip_old = True
                except Exception:
                    pass
                if _skip_old:
                    return  # كود قديم قبل البيع — تجاهله
                code_match = re.search(r'(\d{4,7})', text)
                if code_match:
                    code_only = code_match.group(1)
                    _buyer_received_codes[buyer_id] = {"code": code_only, "time": time.time(), "phone": phone}
                    _auto_twofa = ""
                    try:
                        with db_conn() as _pwdb:
                            _pwrow = _pwdb.execute(
                                "SELECT twofa_password FROM number_stock WHERE phone_number=%s", (phone,)
                            ).fetchone()
                            if _pwrow:
                                _auto_twofa = (_pwrow["twofa_password"] or "").strip()
                    except Exception:
                        pass
                    _twofa_line = (
                        f"\n\n🔐 *كلمة مرور المصادقة الثنائية (2FA):*\n`{_auto_twofa}`"
                        if _auto_twofa else ""
                    )
                    try:
                        await application.bot.send_message(
                            buyer_id,
                            f"🔑 *رمز التحقق:*\n`{code_only}`"
                            f"{_twofa_line}",
                            parse_mode="Markdown"
                        )
                    except Exception as buyer_err:
                        logger.error(f"❌ فشل إرسال كود الدخول للمشتري {buyer_id} (الرقم {phone}): {buyer_err}")
                return  # كود الدخول → للمشتري فقط، لا نرسله للمالك

            # ─── هل رسالة "تغيّر التحقق بخطوتين" هذه ناتجة عن فعل البوت نفسه (تفعيل/تغيير 2FA تلقائياً)؟ ───
            is_2fa_change_msg = "two-step verification" in text.lower() and "changed" in text.lower()
            last_expected = _expected_2fa_change.get(phone)
            if is_2fa_change_msg and last_expected and (time.time() - last_expected) <= _EXPECTED_2FA_WINDOW_SEC:
                _expected_2fa_change.pop(phone, None)
                await notify_account_change(
                    application.bot, phone,
                    "✅ (طبيعي) البوت نفسه فعّل/غيّر كلمة مرور التحقق بخطوتين تلقائياً لهذا الرقم — ليس تغييراً من طرف خارجي",
                    stock_id=stock_id,
                )
                return

            translated = translate_official_notice(text)
            await notify_account_change(
                application.bot, phone, f"رسالة أمنية من تيليجرام الرسمي:\n\n{translated}",
                stock_id=stock_id,
            )
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال تنبيه أمني للرقم {phone}: {e}")

    async def _on_disconnect():
        """إعادة تشغيل المراقبة تلقائياً عند انقطاع الاتصال (مثلاً انقطاع شبكة Railway).
        قبل إعادة المحاولة، يفحص إن كان الانقطاع طرداً فعلياً (جلسة أُلغيت) لا انقطاع شبكة عابر،
        فيُبلّغ المالك بالصيغة الموحّدة إن كان طرداً حقيقياً."""
        _monitor_clients.pop(phone, None)
        _monitor_tasks.pop(phone, None)
        try:
            probe = TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await probe.connect()
            still_authorized = await probe.is_user_authorized()
            await probe.disconnect()
            if not still_authorized:
                stock_id2 = None
                try:
                    with db_conn() as c:
                        row3 = c.execute(
                            "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
                        ).fetchone()
                        if row3:
                            stock_id2 = row3["id"]
                except Exception:
                    pass
                await notify_account_change(
                    application.bot, phone, "تم طرد الحساب (تسجيل خروج/انتهاء الجلسة من تيليجرام)",
                    stock_id=stock_id2,
                )
                logger.warning(f"🔴 الرقم {phone} تم طرده فعلياً، توقفت مراقبته.")
                return
        except Exception as probe_err:
            logger.debug(f"⏳ تعذّر التأكد من سبب انقطاع مراقبة الرقم {phone}: {probe_err}")
        logger.warning(f"⚠️ انقطع اتصال مراقبة الرقم {phone}، سيُعاد المحاولة خلال 30 ثانية...")
        await asyncio.sleep(30)
        await _start_number_monitor(phone, session_str, application)

    client.add_event_handler(_on_official_message, events.NewMessage(chats=777000))

    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning(f"⚠️ جلسة الرقم {phone} غير مخوّلة (expired/revoked)، توقف عن المراقبة.")
            await client.disconnect()
            return

        _monitor_clients[phone] = client

        # ─── الإصلاح الجوهري ───────────────────────────────────────────────
        async def _run_loop():
            try:
                await client.run_until_disconnected()
            except Exception as run_err:
                logger.error(f"❌ خطأ في حلقة مراقبة الرقم {phone}: {run_err}")
            finally:
                await _on_disconnect()

        task = asyncio.create_task(_run_loop())
        _monitor_tasks[phone] = task
        logger.info(f"👁️ بدأت مراقبة الرقم {phone} — حلقة الاستقبال تعمل بالخلفية ✅")

    except Exception as e:
        logger.warning(f"⚠️ تعذّر بدء مراقبة الرقم {phone}: {e}")
        try:
            await client.disconnect()
        except Exception:
            pass

async def start_all_number_monitors(application):
    """يُستدعى عند إقلاع البوت: يبدأ مراقبة كل الأرقام التي تملك جلسة محفوظة بالمخزون."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    with db_conn() as c:
        rows = c.execute(
            "SELECT phone_number, session_string FROM number_stock WHERE session_string IS NOT NULL"
        ).fetchall()
    for row in rows:
        await _start_number_monitor(row["phone_number"], row["session_string"], application)
    if rows:
        logger.info(f"👁️ تم تفعيل مراقبة {len(rows)} رقم (تنبيهات أمنية فورية)")

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
            await client.connect()
            if not await client.is_user_authorized():
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
            logger.debug(f"⏳ إعادة محاولة لاحقاً لطرد جلسات الرقم {rec['phone_number']}: {e}")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

async def compensate_duplicate_sales_job(context: ContextTypes.DEFAULT_TYPE):
    """يفحص دورياً أرقام الهاتف التي بيعت لأكثر من مشترٍ واحد ويُعوّض
    جميع المشترين عدا الأول (صاحب أقدم سجل مكتمل).
    يُغيّر حالة سجل المكرر إلى 'duplicate_compensated' لتجنب التعويض المزدوج."""
    bot = context.bot
    try:
        with db_conn() as c:
            dupes = c.execute("""
                SELECT
                    prize_value,
                    array_agg(id          ORDER BY created_at ASC) AS pe_ids,
                    array_agg(user_id     ORDER BY created_at ASC) AS user_ids,
                    array_agg(points_cost ORDER BY created_at ASC) AS costs,
                    array_agg(order_code  ORDER BY created_at ASC) AS codes
                FROM prize_exchanges
                WHERE prize_type IN ('telegram_number', 'telegram_number_code')
                  AND prize_value NOT IN ('number', 'manual')
                  AND status = 'completed'
                GROUP BY prize_value
                HAVING COUNT(*) > 1
            """).fetchall()
    except Exception as e:
        logger.warning(f"⚠️ compensate_duplicate_sales: فشل جلب السجلات المكررة: {e}")
        return

    for dupe in (dupes or []):
        pe_ids   = dupe["pe_ids"]
        user_ids = dupe["user_ids"]
        costs    = dupe["costs"]
        codes    = dupe["codes"]
        phone    = dupe["prize_value"]

        for i in range(1, len(pe_ids)):
            pe_id = pe_ids[i]
            uid   = user_ids[i]
            cost  = int(costs[i] or 0)
            code  = codes[i] or str(pe_id)

            # ─── حماية من التعويض المزدوج — تحقق أنه لم يُعوَّض مسبقاً ───
            try:
                with db_conn() as _chk:
                    _already = _chk.execute(
                        "SELECT compensated_at FROM prize_exchanges WHERE id=%s", (pe_id,)
                    ).fetchone()
                if _already and _already["compensated_at"]:
                    logger.info(f"⏭ compensate_duplicate_sales: pe_id={pe_id} عُوِّض مسبقاً، تخطّي.")
                    continue
            except Exception:
                pass

            try:
                with db_conn() as _rec:
                    _rec.execute(
                        "UPDATE prize_exchanges SET status='duplicate_compensated', "
                        "compensated_at=NOW(), compensated_pts=%s, compensated_reason='auto_duplicate' "
                        "WHERE id=%s AND compensated_at IS NULL",
                        (cost, pe_id)
                    )
                    _updated = _rec.rowcount
                if _updated == 0:
                    logger.info(f"⏭ compensate_duplicate_sales: pe_id={pe_id} سُبق بالتعويض، تخطّي.")
                    continue
            except Exception as e:
                logger.warning(f"⚠️ compensate_duplicate_sales: فشل تسجيل التعويض pe_id={pe_id}: {e}")
                continue

            if cost > 0:
                add_points(uid, cost)

            try:
                msg = (
                    f"⚠️ *تنبيه — تعويض تلقائي*\n\n"
                    f"اكتشف النظام أن الرقم الذي حصلت عليه بكود `{code}` "
                    f"قد سُلِّم بالخطأ لأكثر من شخص.\n\n"
                )
                if cost > 0:
                    msg += f"✅ تم إعادة *{cost:,} نقطة* لرصيدك تلقائياً.\n\n"
                else:
                    msg += "✅ تم تسجيل الحادثة وسيتواصل معك المالك لحلها.\n\n"
                msg += "نعتذر عن هذا الخلل ونقدّر صبرك 🙏"
                await bot.send_message(uid, msg, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.warning(f"⚠️ compensate_duplicate_sales: فشل إشعار المستخدم {uid}: {e}")


            logger.info(
                f"✅ compensate_duplicate_sales: عوّضنا المستخدم {uid} "
                f"({cost:,} نقطة) بسبب بيع مكرر للرقم {phone} (pe_id={pe_id})"
            )

async def check_pending_orders_job(context: ContextTypes.DEFAULT_TYPE):
    """يفحص دورياً حالة الطلبات المعلّقة عبر API موقع الرشق، ويحدّث حالتها:
    - Completed  ← يُعلّم الطلب مكتملاً ويُشعر المستخدم.
    - Partial    ← يُعلّم مكتملاً ويُعيد النقاط المستحقة (1000 نقطة/سنت) لموقع SMMMAIN.
    - Canceled/Failed/Error ← يُعيد كامل النقاط ويُشعر المستخدم.
    - Pending/Processing → لا تغيير، يُعاد فحصه لاحقاً."""
    try:
        with db_conn() as c:
            pending = c.execute(
                "SELECT o.*, s.panel AS svc_panel, s.api_service_id AS svc_api_id FROM orders o "
                "LEFT JOIN services s ON s.id = o.service_id "
                "WHERE o.status='pending' AND o.api_order_id IS NOT NULL AND o.api_order_id != ''"
            ).fetchall()
    except Exception as e:
        logger.warning(f"⚠️ فشل جلب الطلبات المعلّقة للفحص الدوري: {e}")
        return

    for o in pending:
        panel = o.get("svc_panel") or 1
        try:
            res = await asyncio.to_thread(smm_order_status, o["api_order_id"], panel)
        except Exception as e:
            logger.warning(f"⚠️ فشل فحص حالة الطلب {o.get('order_code')}: {e}")
            continue
        if not isinstance(res, dict) or "error" in res:
            continue
        panel_status = str(res.get("status", "")).strip().lower()
        if not panel_status:
            continue

        if panel_status == "completed":
            with db_conn() as c:
                c.execute("UPDATE orders SET status='completed' WHERE id=?", (o["id"],))
            try:
                await context.bot.send_message(
                    o["user_id"],
                    f"🎉 تم اكتمال طلبك بكود {o['order_code']} بنجاح!\nنتمنى أن تكون راضياً عن الخدمة 🌟"
                )
            except Exception:
                pass

        elif panel_status == "partial":
            remains    = int(res.get("remains", 0) or 0)
            refund_pts = 0
            if panel == 1 and remains > 0 and o.get("svc_api_id"):
                refund_pts = await asyncio.to_thread(_calc_partial_refund_pts, o["svc_api_id"], remains)

            with db_conn() as c:
                c.execute(
                    "UPDATE orders SET status='completed', partial_refund_pts=%s WHERE id=%s",
                    (refund_pts, o["id"])
                )
            if refund_pts > 0:
                add_points(o["user_id"], refund_pts)
                logger.info(f"💰 استرجاع جزئي: طلب {o['order_code']} — {refund_pts:,} نقطة → مستخدم {o['user_id']}")

            try:
                if refund_pts > 0:
                    msg = (
                        f"⚠️ طلبك بكود `{o['order_code']}` اكتمل *جزئياً*.\n\n"
                        f"📦 الوحدات غير المنفذة: {remains:,}\n"
                        f"💰 تم استرجاع *{refund_pts:,}* نقطة لرصيدك تعويضاً عن الجزء الناقص.\n\n"
                        f"ℹ️ سياسة الموقع: يُعيد الموقع قيمة الجزء غير المنفذ تلقائياً."
                    )
                else:
                    msg = (
                        f"⚠️ طلبك بكود {o['order_code']} اكتمل جزئياً.\n"
                        f"ℹ️ تم تنفيذ الطلب جزئياً حسب سياسة الموقع."
                    )
                await context.bot.send_message(o["user_id"], msg, parse_mode="Markdown")
            except Exception:
                pass

        elif panel_status in ("canceled", "cancelled", "failed", "error"):
            with db_conn() as c:
                c.execute("UPDATE orders SET status='cancelled' WHERE id=?", (o["id"],))
            pts = o.get("cost_points", 0) or 0
            if pts:
                add_points(o["user_id"], pts)
            try:
                await context.bot.send_message(
                    o["user_id"],
                    f"🔴 تم إلغاء طلبك بكود {o['order_code']} من قبل موقع الرشق وإعادة *{pts}* نقطة لرصيدك.\n\n"
                    f"{LINK_ERROR_GUIDANCE}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
