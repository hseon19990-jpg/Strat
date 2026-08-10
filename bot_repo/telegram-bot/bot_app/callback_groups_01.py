"""Callback case group 1 for the Telegram bot.

Cases stay in their original order. A matching case returns from this group,
while the sentinel lets the dispatcher continue to the next group.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

async def _handle_callback_group_01(update, context, q, data, user, is_own, is_supervisor_cb, _gmail_verification_done):
    if True:
        if _gmail_verification_done:
            sub_id = None
            if ":" in data:
                try:
                    sub_id = int(data.split(":", 1)[1])
                except (IndexError, TypeError, ValueError):
                    await q.answer("❌ رابط التحقق غير صالح.", show_alert=True)
                    return
        
            try:
                with db_conn() as c:
                    if sub_id is None:
                        latest_verification = c.execute(
                            "SELECT id FROM gmail_submissions "
                            "WHERE user_id=%s AND status='rejected' "
                            "AND (rejection_reason='need_verify' OR rejection_reason='') "
                            "AND COALESCE(verification_notified, FALSE)=FALSE "
                            "ORDER BY id DESC LIMIT 1",
                            (user.id,)
                        ).fetchone()
                        sub_id = latest_verification["id"] if latest_verification else None
                    if sub_id is None:
                        await q.answer(
                            "⚠️ لا يوجد طلب إيميل يحتاج إكمال التحقق حالياً.",
                            show_alert=True
                        )
                        return
        
                    lock = c.execute(
                        "SELECT pg_try_advisory_xact_lock(%s) AS acquired",
                        (sub_id,)
                    ).fetchone()
                    if not lock or not lock["acquired"]:
                        await q.answer(
                            "⏳ تتم معالجة طلبك الآن، حاول بعد لحظات.",
                            show_alert=True
                        )
                        return
        
                    sub = c.execute(
                        "SELECT id, user_id, gmail_email, status, rejection_reason, "
                        "verification_completed, verification_notified "
                        "FROM gmail_submissions WHERE id=%s",
                        (sub_id,)
                    ).fetchone()
        
                    if not sub or sub["user_id"] != user.id:
                        await q.answer("❌ هذا الزر لا يخص طلبك.", show_alert=True)
                        return
                    if (
                        sub["status"] != "rejected"
                        or sub["rejection_reason"] not in ("need_verify", "")
                    ):
                        await q.answer(
                            "⚠️ لم يعد هذا الطلب بانتظار إكمال التحقق.",
                            show_alert=True
                        )
                        return
                    if sub["verification_notified"]:
                        await q.answer(
                            "✅ تم إبلاغ المالك بهذا الطلب مسبقاً.",
                            show_alert=True
                        )
                        try:
                            await q.edit_message_reply_markup(reply_markup=None)
                        except Exception:
                            pass
                        return
        
                    context.user_data["state"] = "await_gmail_verification_note"
                    context.user_data["gmail_verification_note_sub_id"] = sub_id
                    await q.answer("اكتب رسالة للمالك للمتابعة.", show_alert=False)
                    note_prompt = get_setting("gmail_verification_note_prompt") or (
                        "💬 <b>اكتب رسالتك للمالك</b>\n\n"
                        "يجب كتابة ملاحظة قبل إرسال إشعار إكمال التحقق."
                    )
                    await q.edit_message_text(
                        note_prompt,
                        parse_mode=ParseMode.HTML,
                    )
                    return
                await q.answer("✅ تم إبلاغ المالك بإكمال التحقق.", show_alert=True)
                try:
                    await q.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass
            except Exception as _verify_notify_error:
                logger.warning(
                    f"gmail verification owner notify error: {_verify_notify_error}"
                )
                await q.answer(
                    "⚠️ تعذر إبلاغ المالك حالياً. اضغط الزر مرة أخرى للمحاولة.",
                    show_alert=True
                )
            return

        if data.startswith("owner_fwd:") and is_own:
            parts  = data.split(":", 2)
            action = parts[1] if len(parts) > 1 else ""
            key    = parts[2] if len(parts) > 2 else ""
            pending = _pending_group_msgs.pop(key, None)
            if action == "yes" and pending and ADMIN_GROUP_ID:
                try:
                    await context.bot.send_message(
                        ADMIN_GROUP_ID,
                        pending["text"],
                        parse_mode=pending.get("parse_mode", "Markdown")
                    )
                    await q.answer("✅ تم إرسال الطلب للكروب", show_alert=False)
                except Exception as _e:
                    await q.answer(f"⚠️ فشل الإرسال: {str(_e)[:60]}", show_alert=True)
            else:
                await q.answer("❌ لم يُرسل الطلب للكروب", show_alert=False)
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            return

        if data == "skip_mandatory_gate":
            if user.id != OWNER_ID:
                await q.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
                return
            await q.answer("⏭ تم التخطي")
            db_user = get_user(user.id)
            if db_user and db_user.get("verified", 0):
                context.user_data["state"] = "main_menu"
                db_user = get_user(user.id)
                pts = db_user["points"] if db_user else 0
                await q.edit_message_text(
                    f"🏠 *القائمة الرئيسية*\n💰 رصيدك: {pts} نقطة",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=main_menu_kb(True)
                )
            else:
                await proceed_after_mandatory(update, context, edit=True)
            return

        if data == "main_menu":
            context.user_data["state"] = "main_menu"
            db_user = get_user(user.id)
            pts = db_user["points"] if db_user else 0
            await q.edit_message_text(
                f"🏠 *القائمة الرئيسية*\n💰 رصيدك: {pts} نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own, is_supervisor_user=is_supervisor_cb)
            )
            return

        if data == "services_menu":
            context.user_data["state"] = "services_menu"
            rows = build_kb_rows(get_menu_items("services_menu"))
            if is_own:
                rows.append([InlineKeyboardButton("🧩 إضافة/إزالة خيار", callback_data="mb_menu:services_menu")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
            await q.edit_message_text(
                "🛍 *خدمات*\nاختر المنصة المطلوبة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "legendary_services":
            if data == "legendary_services" and not is_own and not is_legendary_services_visible():
                await q.answer("⚠️ خدمات أسطورية مخفية حالياً من قبل المالك.", show_alert=True)
                return
            context.user_data["state"] = "legendary_services"
            # Get items and filter out forced_ref options
            items = get_menu_items("legendary_services")
            filtered_items = [item for item in items if not item["action_value"].startswith("legendary:forced_ref")]
            rows = build_kb_rows(filtered_items)
            if is_own:
                rows.append([InlineKeyboardButton("🧩 إضافة/إزالة خيار", callback_data="mb_menu:legendary_services")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
            await q.edit_message_text(
                f"{LEGENDARY_SERVICES_MESSAGE}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "legendary_comment:skip_channel":
            await legendary_skip_channel(update, context, q, is_own)
            return

        if data == "legendary_comment:confirm":
            await q.answer("⚠️ هذا الزر قديم. ابدأ الطلب من قائمة الخدمات الأسطورية.", show_alert=True)
            return

        # ─── الخدمات الأسطورية ──────────────────────────────────────────
        if data.startswith("legendary:"):
            if data == "legendary:price_settings" and is_own:
                await q.edit_message_text(
                    "💰 *تعديل أسعار الخدمات الأسطورية*\n\nاختر الخدمة لتعديل سعرها:",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_price_settings_kb()
                )
                return
            
            if data.startswith("legendary:edit_price:") and is_own:
                service_type = data.split(":")[2]
                await legendary_edit_price(update, context, q, is_own, service_type)
                return
            
            if data == "legendary:skip_channel":
                await legendary_skip_channel(update, context, q, is_own)
                return

            if data == "legendary:set_delay":
                await legendary_set_delay(update, context, q, is_own)
                return
            
            if data.startswith("legendary:pay:"):
                payment_method = data.split(":")[2]
                await legendary_payment_callback(update, context, q, is_own, payment_method)
                return
            
            # Handle premium reaction selection
            if data.startswith("legendary:reaction:"):
                await legendary_premium_reaction_callback(update, context, q, is_own, data)
                return
            
            # Map service type to handler
            service_map = {
                "legendary:comment": "comment",
                "legendary:poll": "poll",
                "legendary:story": "story",
                "legendary:votes": "votes",
                "legendary:votes_ai": "votes_ai",
                "legendary:premium_reaction": "premium_reaction",
            }
            
            service_type = service_map.get(data)
            if service_type:
                await legendary_service_start(update, context, q, is_own, service_type)
                return
            
            # Fallback
            await q.answer("⚠️ الخيار غير متاح حالياً.", show_alert=True)
            return

        if data in SERVICE_PLATFORM_MENUS:
            context.user_data["state"] = data
            context.user_data["current_platform"] = PLATFORM_MENU_MAP.get(data, "tg")
            items = get_menu_items(data)
            rows = build_kb_rows(items)
            platform_label = next((lbl for lbl, val in SERVICE_PLATFORMS if val == data), "خدمات")
            if is_own:
                rows.append([InlineKeyboardButton("🧩 إضافة/إزالة خيار", callback_data=f"mb_menu:{data}")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="services_menu")])
            body = "اختر الخدمة المطلوبة:" if items else "⚠️ لا توجد خدمات مضافة هنا حالياً.\nتواصل مع المالك لإضافتها."
            await q.edit_message_text(
                f"{platform_label}\n{body}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data.startswith("cat:"):
            cat = data.split(":")[1]
            await show_category_services(update, context, cat)
            return

        if data.startswith("mi_text:"):
            mi_id = int(data.split(":")[1])
            with db_conn() as c:
                item = c.execute("SELECT * FROM menu_items WHERE id=?", (mi_id,)).fetchone()
            if not item:
                await q.answer("⚠️ هذا الزر لم يعد موجوداً.", show_alert=True)
                return
            content = item["action_value"] or ""
            if len(content) <= 200:
                try:
                    await q.answer(content, show_alert=True)
                    return
                except Exception as e:
                    logger.warning(f"⚠️ فشل عرض تنبيه mi_text كـ alert، سيُرسل كرسالة عادية: {e}")
            await q.answer()
            await context.bot.send_message(user.id, content or "—")
            return

        if data.startswith("svc:"):
            svc_id = int(data.split(":")[1])
            with db_conn() as c:
                svc = c.execute("SELECT * FROM services WHERE id=?", (svc_id,)).fetchone()
            if not svc:
                await q.edit_message_text("⚠️ الخدمة غير موجودة.", reply_markup=back_kb())
                return
            if svc.get('service_type') == 'mandatory_sub':
                await _mansub_start(update, context, user, q, is_own)
                return
            cat = svc["category"]
            context.user_data["smm_svc_db_id"] = svc_id
            context.user_data["smm_svc"] = dict(svc)
            context.user_data["smm_cat"] = cat
            context.user_data["state"] = "await_smm_qty"
            await q.edit_message_text(
                f"🔹 *{svc['name_ar']}*\n\n"
                f"📉 الحد الأدنى: {svc['min_qty']}\n"
                f"📈 الحد الأعلى: {svc['max_qty']}\n"
                f"💰 السعر: {fmt_price(svc['price_per_point'])} نقطة / 1000 وحدة\n\n"
                f"🔢 أرسل *الكمية* المطلوبة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"cat:{cat}")]
                ])
            )
            return

        if data == 'forced_ref':
            with db_conn() as _c:
                _fr_row = _c.execute(
                    "SELECT enabled FROM menu_items WHERE menu='main' AND action_value='forced_ref' AND action_type='builtin' LIMIT 1"
                ).fetchone()
            if _fr_row and not _fr_row['enabled'] and not is_own:
                await q.answer('⚠️ هذه الخدمة متوقفة حالياً.', show_alert=True)
                return
            if not is_own and get_setting('forced_ref_visible') != '1' and get_setting('forced_ref_ai_visible') != '1':
                await q.answer('⚠️ هذه الخدمة غير متاحة حالياً.', show_alert=True)
                return
        
            avail = get_forced_ref_account_count()
            kb_rows = []
        
            show_no_ai = is_own or get_setting('forced_ref_visible') == '1'
            show_ai    = is_own or get_setting('forced_ref_ai_visible') == '1'
        
            if show_no_ai:
                kb_rows.append([InlineKeyboardButton(
                    '🔑 إحالة إجبارية بدون تحقق',
                    callback_data='forced_ref_no_ai'
                )])
            if show_ai:
                kb_rows.append([InlineKeyboardButton(
                    '🤖 إحالة إجبارية تحتوي تحقق',
                    callback_data='forced_ref_ai'
                )])
            kb_rows.append([InlineKeyboardButton('🔙 رجوع', callback_data='main_menu')])
        
            await q.edit_message_text(
                f'📊 الحسابات المتاحة: *{avail}*',
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
            return

        if data == 'forced_ref_no_ai':
            if not is_own and get_setting('forced_ref_visible') != '1':
                await q.answer('⚠️ هذه الخدمة غير متاحة حالياً.', show_alert=True)
                return
            await _forced_ref_start(update, context, user, q, is_own, with_ai=False)
            return

        if data == 'forced_ref_ai':
            if not is_own and get_setting('forced_ref_ai_visible') != '1':
                await q.answer('⚠️ هذه الخدمة غير متاحة حالياً.', show_alert=True)
                return
            await _forced_ref_start(update, context, user, q, is_own, with_ai=True)
            return

        if data.startswith('forced_ref_pm:'):
            _, pm, ai_flag = data.split(':')
            use_ai = ai_flag == '1'
            if use_ai and not is_own and get_setting('forced_ref_ai_visible') != '1':
                await q.answer('⚠️ هذه الخدمة غير متاحة حالياً.', show_alert=True)
                return
            if not use_ai and not is_own and get_setting('forced_ref_visible') != '1':
                await q.answer('⚠️ هذه الخدمة غير متاحة حالياً.', show_alert=True)
                return
            draft = context.user_data.setdefault('forced_ref_draft', {})
            draft['use_ai']         = use_ai
            draft['payment_method'] = pm
            context.user_data['state'] = 'await_forced_ref_channels'
            await _forced_ref_go_channels(q, context, draft, edit=True)
            return

        if data == 'forced_ref_skip_channels':
            draft = context.user_data.setdefault('forced_ref_draft', {})
            draft['channels'] = ''
            context.user_data['state'] = 'await_forced_ref_link'
            avail = get_forced_ref_account_count()
            await q.edit_message_text(
                f'✅ بدون قنوات إجبارية.\n\n'
                f'📊 المتاح: *{avail}* حساب\n\n'
                f'📎 *أرسل رابط البوت:*\n'
                f'`t.me/BotUsername?start=CODE`\n'
                f'أو: `@BotUsername CODE`',
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 إلغاء', callback_data='main_menu')]])
            )
            return

        if data == 'mansub_skip_channels':
            draft = context.user_data.setdefault('mansub_draft', {})
            draft['channels'] = ''
            context.user_data['state'] = 'await_mansub_qty'
            avail = get_available_number_count()
            bp = int(get_setting('mansub_base_price') or '250')
            await q.edit_message_text(
                f'✅ بدون قنوات إجبارية.\n\n📊 المتاح: *{avail}* حساب\n💰 سعر/حساب: *{bp}* نقطة\n\n🔢 خطوة 3/3 — أرسل عدد الحسابات (1 – {avail}):',
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 إلغاء', callback_data='cat:start_bot')]])
            )
            return

        if data == "smm_back:qty":
            svc = context.user_data.get("smm_svc", {})
            if not svc:
                await q.edit_message_text("⚠️ انتهت الجلسة. ابدأ من جديد.", reply_markup=main_menu_kb(is_own))
                return
            cat = context.user_data.get("smm_cat", svc.get("category", ""))
            context.user_data["state"] = "await_smm_qty"
            await q.edit_message_text(
                f"🔹 *{svc['name_ar']}*\n\n"
                f"📉 الحد الأدنى: {svc['min_qty']}\n"
                f"📈 الحد الأعلى: {svc['max_qty']}\n"
                f"💰 السعر: {fmt_price(svc['price_per_point'])} نقطة / 1000 وحدة\n\n"
                f"🔢 أرسل *الكمية* المطلوبة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"cat:{cat}")]
                ])
            )
            return

        if data == "smm_back:link":
            svc  = context.user_data.get("smm_svc", {})
            qty  = context.user_data.get("smm_qty", 0)
            cost = context.user_data.get("smm_cost", 0)
            if not svc:
                await q.edit_message_text("⚠️ انتهت الجلسة. ابدأ من جديد.", reply_markup=main_menu_kb(is_own))
                return
            context.user_data["state"] = "await_smm_link"
            await q.edit_message_text(
                f"✅ الكمية: {qty} | التكلفة: {cost} نقطة\n\n"
                f"📎 أرسل *رابط* الحساب/القناة/البوست:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع (تغيير الكمية)", callback_data="smm_back:qty")]
                ])
            )
            return

        if data.startswith('confirm_forced_ref:'):
            await _handle_confirm_forced_ref(update, context, user, q, is_own, data)
            return

        if data.startswith('confirm_mansub:'):
            await _handle_confirm_mansub(update, context, user, q, is_own, data)
            return

        if data.startswith("confirm_order:"):
            action = data.split(":")[1]
            if context.user_data.get("state") != "confirm_smm":
                await q.edit_message_text("⚠️ انتهت صلاحية هذا الطلب. ابدأ من جديد.", reply_markup=main_menu_kb(is_own))
                return
            if action == "yes":
                svc  = context.user_data.get("smm_svc", {})
                qty  = context.user_data.get("smm_qty", 0)
                cost = context.user_data.get("smm_cost", 0)
                link = context.user_data.get("smm_link", "")
                _db_u_chk = get_user(user.id)
                if _db_u_chk and _db_u_chk.get("referral_points_blocked"):
                    await q.edit_message_text(
                        "🔒 *حسابك موقوف مؤقتاً عن استخدام النقاط.*\n\n"
                        "تم رصد نشاط مشبوه في إحالاتك. تواصل مع المالك لرفع التقييد.",
                        parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_kb(is_own))
                    return
                if not deduct_points(user.id, cost):
                    await q.edit_message_text("❌ نقاطك غير كافية.", reply_markup=main_menu_kb(is_own))
                    context.user_data["state"] = "main_menu"
                    return
                api_res = await asyncio.to_thread(smm_create_order, svc["api_service_id"], link, qty, panel=svc.get("panel", 1))
                if "error" in api_res or not api_res.get("order"):
                    add_points(user.id, cost)
                    err_msg = md_escape(api_res.get("error", "خطأ غير معروف من الموقع"))
                    await q.edit_message_text(
                        f"❌ *فشل الطلب:* {err_msg}\n✅ تمت إعادة نقاطك.\n\n"
                        f"{LINK_ERROR_GUIDANCE}",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=main_menu_kb(is_own)
                    )
                    context.user_data["state"] = "main_menu"
                    return
                api_oid = str(api_res.get("order", ""))
                code    = next_order_code(user.id)
                with db_conn() as c:
                    c.execute(
                        "INSERT INTO orders (user_id,service_id,link,quantity,cost_points,api_order_id,order_code) VALUES (?,?,?,?,?,?,?)",
                        (user.id, svc["id"], link, qty, cost, api_oid, code)
                    )
                await q.edit_message_text(
                    f"✅ *تمت العملية بنجاح!*\n\n"
                    f"🔹 الخدمة: {svc['name_ar']}\n"
                    f"🔢 الكمية: {qty}\n"
                    f"💰 التكلفة: {cost} نقطة",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=main_menu_kb(is_own)
                )
                await context.bot.send_message(
                    user.id,
                    f"📌 *كود عمليتك هو:* `{code}`\nاحفظه قد تحتاجه لاحقاً.",
                    parse_mode=ParseMode.MARKDOWN
                )
                await notify_group(
                    context.application,
                    f"🆕 <b>طلب جديد</b>\n"
                    f"👤 المستخدم: <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                    f"🔹 الخدمة: {svc['name_ar']}\n"
                    f"🔗 الرابط: {link}\n"
                    f"🔢 الكمية: {qty}\n"
                    f"💰 التكلفة: {cost} نقطة\n"
                    f"📌 الكود: {code}"
                )
            else:
                await q.edit_message_text("❌ تم إلغاء الطلب.", reply_markup=main_menu_kb(is_own))
            context.user_data["state"] = "main_menu"
            return

        if data == "contact_support":
            contact = get_setting("owner_contact") or ""
            if not contact:
                await q.edit_message_text(
                    "⚠️ خدمة الدعم غير متاحة حالياً.",
                    reply_markup=back_kb()
                )
                return
            label = get_setting("support_contact_label") or "🛎 تواصل مع الدعم"
            await q.edit_message_text(
                "🛎 *تواصل مع الدعم*\n\nاضغط الزر أدناه للتواصل معنا مباشرة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(label, url=contact)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]
                ])
            )
            return

        if data == "thank_owner" and is_own:
            await q.edit_message_text(
                "💌 *إعدادات شكر المالك*\n\n"
                "هذه الميزة مخصصة للأعضاء. يمكنك تعديل نصوصها من إعدادات المالك:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=thank_owner_settings_kb()
            )
            return

        if data == "thank_owner" and not is_own:
            context.user_data["state"] = "thank_owner_menu"
            await q.edit_message_text(
                "💌 *شكر المالك*\n\nاختر طريقة الشكر:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        get_setting("thank_owner_ar_button_label") or "🇸🇦 رسالة بالعربية",
                        callback_data="thank_owner:ar"
                    )],
                    [InlineKeyboardButton(
                        get_setting("thank_owner_en_button_label") or "🇬🇧 Message in English",
                        callback_data="thank_owner:en"
                    )],
                    [InlineKeyboardButton(
                        get_setting("thank_owner_photo_button_label") or "🖼️ إرسال صورة",
                        callback_data="thank_owner:photo"
                    )],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
                ])
            )
            return

        if data in ("thank_owner:ar", "thank_owner:en", "thank_owner:photo") and not is_own:
            kind = data.split(":", 1)[1]
            if kind == "ar":
                context.user_data["state"] = "thank_owner_ar"
                prompt = get_setting("thank_owner_ar_prompt") or "💌 أرسل رسالة الشكر بالعربية:"
            elif kind == "en":
                context.user_data["state"] = "thank_owner_en"
                prompt = get_setting("thank_owner_en_prompt") or "💌 Send your thank-you message in English:"
            else:
                context.user_data["state"] = "thank_owner_photo"
                prompt = get_setting("thank_owner_photo_prompt") or "🖼️ أرسل الصورة التي تريد مشاركتها مع المالك:"
            await q.edit_message_text(
                prompt,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع", callback_data="thank_owner")]
                ])
            )
            return

        if data == "referral":
            await q.edit_message_text(
                "👻 *رابط الدعوة*\n\nاختر ما تريد:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 رابط دعوتي", callback_data="referral:my_link")],
                    [InlineKeyboardButton("🏆 الأكثر دعوةً", callback_data="referral:top")],
                    [InlineKeyboardButton("🥇 تصنيف المسابقة", callback_data="referral_contest_view")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
                ])
            )
            return

        if data == "referral:my_link":
            bot_username = (await context.bot.get_me()).username
            link = f"https://t.me/{bot_username}?start={user.id}"
            rp   = get_setting("referral_points") or "30"
            db_user = get_user(user.id)
            with db_conn() as c:
                credited  = c.execute(
                    "SELECT COUNT(*) as cnt FROM users WHERE invited_by=? AND referral_credited=1",
                    (user.id,)
                ).fetchone()["cnt"]
                pending   = c.execute(
                    "SELECT COUNT(*) as cnt FROM users WHERE invited_by=? AND referral_credited=0",
                    (user.id,)
                ).fetchone()["cnt"]
            pending_line = f"\n⏳ بانتظار إكمال التحقق: {pending} شخص" if pending else ""
            await q.edit_message_text(
                f"🔗 *رابط دعوتك الشخصي:*\n\n`{link}`\n\n"
                f"✅ تحصل على *{rp} نقطة* لكل صديق يُكمل التحقق عبر رابطك\n"
                f"👥 إحالات مكتملة (حصلت على نقاطها): {credited} شخص{pending_line}\n"
                f"💰 رصيدك: {db_user['points'] if db_user else 0} نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="referral")]])
            )
            return

        if data == "referral:top":
            rows = [
                [InlineKeyboardButton("🕐 آخر 24 ساعة", callback_data="top_ref_pick:24h")],
                [InlineKeyboardButton("📅 اليوم الحالي (منذ 00:00 بالتوقيت العالمي)", callback_data="top_ref_pick:day")],
            ]
            if is_own:
                rows.append([InlineKeyboardButton("🗓 آخر أسبوع 🔒", callback_data="top_ref_pick:week")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="referral")])
            await q.edit_message_text(
                "🏆 *الأكثر دعوةً*\n\nاختر الفترة التي تريد عرض المتصدرين خلالها:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "top_ref_today":
            rows = [
                [InlineKeyboardButton("🕐 آخر 24 ساعة", callback_data="top_ref_pick:24h")],
                [InlineKeyboardButton("📅 اليوم الحالي (منذ 00:00 بالتوقيت العالمي)", callback_data="top_ref_pick:day")],
            ]
            if is_own:
                rows.append([InlineKeyboardButton("🗓 آخر أسبوع 🔒", callback_data="top_ref_pick:week")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
            await q.edit_message_text(
                "🏆 *الأكثر دعوةً*\n\nاختر الفترة التي تريد عرض المتصدرين خلالها:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data.startswith("top_ref_pick:"):
            period = data.split(":", 1)[1]
            if period == "week" and not is_own:
                await q.answer("🔒 هذا الخيار متاح للمالك فقط.", show_alert=True)
                return
            since, title = _referral_period_bounds(period)
            rows = get_top_referrers_since(since, limit=10)
            text = _format_top_referrers(rows, title)
            await q.edit_message_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="top_ref_today")]])
            )
            return

        if data == "os:top_referrers" and is_own:
            rows = [
                [InlineKeyboardButton("🕐 آخر 24 ساعة (من لحظة الضغط)", callback_data="os:top_ref:24h")],
                [InlineKeyboardButton("📅 آخر يوم (بالتوقيت العالمي)", callback_data="os:top_ref:day")],
                [InlineKeyboardButton("🗓 آخر أسبوع", callback_data="os:top_ref:week")],
                [InlineKeyboardButton("🗓 آخر شهر", callback_data="os:top_ref:month")],
                [InlineKeyboardButton("🔄 تصفير العداد", callback_data="os:top_ref_reset_confirm")],
                [InlineKeyboardButton("🔍 إحالات شخص معين", callback_data="os:ref_search_user")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
            ]
            await q.edit_message_text(
                "🏆 *الأكثر إرسالاً لرابط الدعوة*\n\nاختر الفترة الزمنية:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data.startswith("os:top_ref:") and is_own:
            period = data.split(":", 2)[2]
            since, title = _referral_period_bounds(period)
            rows = get_top_referrers_since(since, limit=10)
            text = _format_top_referrers(rows, title)
            await q.edit_message_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:top_referrers")]])
            )
            return

        if data == "os:top_ref_reset_confirm" and is_own:
            await q.edit_message_text(
                "⚠️ *تصفير عداد الأكثر إرسالاً لرابط الدعوة*\n\n"
                "سيبدأ العدّ من جديد من هذه اللحظة (لن يتأثر رصيد نقاط أي عضو).\n"
                "هل أنت متأكد؟",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ نعم، صفّر العداد", callback_data="os:top_ref_reset")],
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="os:top_referrers")],
                ])
            )
            return

        if data == "os:top_ref_reset" and is_own:
            reset_referral_counter()
            await q.answer("✅ تم تصفير العداد.", show_alert=True)
            await q.edit_message_text(
                "✅ *تم تصفير عداد الأكثر إرسالاً لرابط الدعوة بنجاح.*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:top_referrers")]])
            )
            return

        if data.startswith("os:ref_keep:") and is_own:
            parts = data.split(":")
            inv_id, rp_pts = int(parts[2]), int(parts[3])
            with db_conn() as _c:
                _c.execute("UPDATE users SET referral_points_blocked=0 WHERE user_id=%s", (inv_id,))
            await q.edit_message_text(
                f"✅ *تم الإبقاء على الإحالة + رفع التقييد عن* `{inv_id}`\n💰 النقاط تبقى معه.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للمقيدين", callback_data="os:restricted_members")]]))
            return

        if data.startswith("os:ref_deduct:") and is_own:
            parts = data.split(":")
            inv_id, rp_pts = int(parts[2]), int(parts[3])
            with db_conn() as _c:
                _c.execute("UPDATE users SET points=GREATEST(0, points-%s), referral_points_blocked=0 WHERE user_id=%s", (rp_pts, inv_id))
            await q.edit_message_text(
                f"❌ *تم خصم {rp_pts} نقطة + رفع التقييد عن* `{inv_id}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للمقيدين", callback_data="os:restricted_members")]]))
            return

        if data.startswith("os:ref_unblock:") and is_own:
            inv_id = int(data.split(":")[2])
            with db_conn() as _c:
                _c.execute("UPDATE users SET referral_points_blocked=0 WHERE user_id=%s", (inv_id,))
            await q.edit_message_text(
                f"🔓 *تم رفع التقييد عن* `{inv_id}` *بدون خصم.*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للمقيدين", callback_data="os:restricted_members")]]))
            return

        if data.startswith("os:ref_extra:") and is_own:
            parts = data.split(":")
            inv_id, rp_pts = int(parts[2]), int(parts[3])
            context.user_data["ref_extra_id"]  = inv_id
            context.user_data["ref_extra_base"] = rp_pts
            context.user_data["state"] = "os_await_ref_extra_pts"
            await q.message.reply_text(
                f"➕ *خصم إضافي من* `{inv_id}`\n\nأرسل عدد النقاط الإضافية للخصم:",
                parse_mode=ParseMode.MARKDOWN)
            return

        if data == "os:ref_search_user" and is_own:
            context.user_data["state"] = "os_await_ref_user_id"
            await q.edit_message_text(
                "🔍 *إحالات شخص معين*\n\nأرسل user_id أو @يوزرنيم:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:top_referrers")]]))
            return

        if data == "os:bot_ref_numbers" and is_own:
            context.user_data.pop("referral_only_import", None)
            with db_conn() as _c:
                _rows_ready = _c.execute(
                    "SELECT phone_number, forced_ref_excluded FROM number_stock "
                    "WHERE session_string IS NOT NULL AND deleted_at IS NULL "
                    "AND last_authorized IS NOT FALSE AND can_send_code IS TRUE "
                    "AND (forced_ref_excluded IS NOT TRUE) "
                    "ORDER BY id ASC"
                ).fetchall()
                _rows_pending = _c.execute(
                    "SELECT phone_number FROM number_stock "
                    "WHERE deleted_at IS NULL "
                    "AND (forced_ref_excluded IS NOT TRUE) "
                    "AND (session_string IS NULL OR can_send_code IS NOT TRUE OR last_authorized IS FALSE) "
                    "ORDER BY id ASC"
                ).fetchall()
                _rows_excluded_q = _c.execute(
                    "SELECT phone_number FROM number_stock "
                    "WHERE deleted_at IS NULL AND forced_ref_excluded IS TRUE "
                    "ORDER BY id ASC"
                ).fetchall()
            _active = [r["phone_number"] for r in _rows_ready]
            _excluded = [r["phone_number"] for r in _rows_excluded_q]
            _pending = [r["phone_number"] for r in _rows_pending]
            with db_conn() as _ccx:
                _ref_only_cnt = (_ccx.execute(
                    "SELECT COUNT(*) as n FROM number_stock WHERE referral_only=TRUE AND deleted_at IS NULL"
                ).fetchone() or {}).get("n", 0) or 0
            _lines = [f"📱 *أرقام إحالة بوت إجباري*\n\n"
                      f"✅ مفعّل وجاهز للإحالة فعلاً: *{len(_active)}*\n"
                      f"⏳ مفعّل لكن ينتظر جلسة/تحقق: *{len(_pending)}*\n"
                      f"🚫 مستثنى من الإحالة: *{len(_excluded)}*\n"
                      f"📁 حصري للإحالة (غير قابل للبيع): *{_ref_only_cnt}*\n\n"
                      f"_(الأرقام التي بدون جلسة مستوردة أو لم يتحقق منها البوت تظهر في خانة ⏳ ولن تُستخدم حتى تجهز)_\n\n"]
            if _active:
                _lines.append("─────────────────\n✅ *الأرقام المفعّلة والجاهزة:*\n")
                for i, p in enumerate(_active, 1):
                    _lines.append(f"{i}. `{p}`")
            else:
                _lines.append("✅ *لا توجد أرقام جاهزة حالياً.*")
            if _pending:
                _lines.append("\n─────────────────\n⏳ *مفعّلة — تنتظر استيراد الجلسة أو التحقق:*\n")
                for i, p in enumerate(_pending, 1):
                    _lines.append(f"{i}. `{p}`")
            if _excluded:
                _lines.append("\n─────────────────\n🚫 *الأرقام المستثناة من الإحالة:*\n")
                for i, p in enumerate(_excluded, 1):
                    _lines.append(f"{i}. `{p}`")
            _text = "\n".join(_lines)
            _cur_delay = get_setting("referral_task_delay") or "30"
            _kb = [
                [InlineKeyboardButton("🔎 البحث عن حسابات تحتوي جلسة", callback_data="os:bot_ref_find_sessions")],
                [InlineKeyboardButton("➕ إضافة رقم للإحالة", callback_data="os:bot_ref_add")],
                [InlineKeyboardButton("📁 استيراد جلسات حصرية للإحالة", callback_data="os:bot_ref_only_import")],
                [InlineKeyboardButton("🗑 مسح/استثناء أرقام", callback_data="os:bot_ref_del_menu")],
                [InlineKeyboardButton(f"⏱️ تأخير بين الحسابات: {_cur_delay}ث", callback_data="os:bot_ref_delay")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
            ]
            try:
                await q.edit_message_text(_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(_kb))
            except Exception:
                await q.message.reply_text(_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(_kb))
            return

        if data == "os:bot_ref_find_sessions" and is_own:
            try:
                _result = find_and_enable_referral_sessions()
                _total = _result["total"]
                _added = _result["added"]
                _already_active = _result["already_active"]
                _active_now = get_forced_ref_account_count()
                await q.answer("✅ اكتمل البحث.", show_alert=False)
                await q.edit_message_text(
                    "🔎 *نتيجة البحث عن الحسابات التي تحتوي جلسة*\n\n"
                    f"📦 إجمالي الحسابات التي عُثر عليها: *{_total}*\n"
                    f"➕ تمت إضافتها/إعادة تفعيلها للإحالة: *{_added}*\n"
                    f"✅ كانت مفعّلة مسبقاً: *{_already_active}*\n"
                    f"📊 إجمالي الجاهز للإحالة الآن: *{_active_now}*\n\n"
                    "تم تجاهل السجلات المحذوفة، ولم يتم إنشاء أي رقم مكرر.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 أرقام إحالة بوت إجباري", callback_data="os:bot_ref_numbers")
                    ]])
                )
            except Exception as _find_err:
                logger.error(f"❌ os:bot_ref_find_sessions error: {_find_err}")
                await q.answer("⚠️ تعذّر تنفيذ البحث.", show_alert=True)
            return

        if data == "os:bot_ref_add" and is_own:
            context.user_data["state"] = "os_await_bot_ref_add"
            await q.edit_message_text(
                "➕ *إضافة رقم للإحالة الإجبارية*\n\n"
                "أرسل رقم الهاتف الذي تريد تفعيله للإحالة (يجب أن يكون موجوداً في مخزون البوت).\n\n"
                "مثال: `+9647701234567`\n\n"
                "_(يمكنك إرسال عدة أرقام كل واحد في سطر)_",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:bot_ref_numbers")]]))
            return

        if data == "os:bot_ref_only_import" and is_own:
            context.user_data["state"] = "os_ref_only_import_ready"
            context.user_data["referral_only_import"] = True
            await q.edit_message_text(
                "📁 *استيراد جلسات حصرية للإحالة*\n\n"
                "أرسل ملفات الجلسة (`.session` أو `.json` أو `.zip`) مباشرةً الآن.\n\n"
                "⚠️ الحسابات المستوردة بهذه الطريقة ستكون *حصراً للإحالة الإجبارية* "
                "ولن تظهر في قائمة المبيعات.\n\n"
                "_(أرسل ملفاً واحداً أو أكثر، ثم اضغط رجوع عند الانتهاء)_",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 رجوع", callback_data="os:bot_ref_numbers")
                ]]))
            return

        if data == "os:bot_ref_delay" and is_own:
            context.user_data["state"] = "os_await_bot_ref_delay"
            _cur = get_setting("referral_task_delay") or "30"
            await q.edit_message_text(
                f"⏱️ *ضبط التأخير بين الحسابات*\n\n"
                f"القيمة الحالية: *{_cur} ثانية*\n\n"
                "أرسل القيمة الجديدة بالثوانٍ:\n"
                "• أدنى قيمة: `0` (بدون تأخير)\n"
                "• أمثلة: `0.5` أو `5` أو `30` أو `120`\n\n"
                "_يُطبّق الفاصل على إحالة البوت الإجبارية، بما فيها الحسابات البديلة._",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 إلغاء", callback_data="os:bot_ref_numbers")
                ]]))
            return

        if data == "os:bot_ref_del_menu" and is_own:
            with db_conn() as _c:
                _rows = _c.execute(
                    "SELECT id, phone_number, forced_ref_excluded FROM number_stock "
                    "WHERE session_string IS NOT NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
                    "AND last_authorized IS NOT FALSE AND can_send_code IS TRUE "
                    "ORDER BY id ASC"
                ).fetchall()
            if not _rows:
                await q.edit_message_text(
                    "⚠️ لا توجد أرقام في البوت يمكن إدارتها.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:bot_ref_numbers")]]))
                return
            _lines = ["🗑 *مسح/استثناء أرقام من الإحالة الإجبارية*\n\n"]
            _lines.append("الأرقام الموجودة في البوت:\n")
            for i, r in enumerate(_rows, 1):
                _status = "🚫 مستثنى" if r.get("forced_ref_excluded") else "✅ مفعّل"
                _lines.append(f"{i}. `{r['phone_number']}` — {_status}")
            _lines.append(
                "\n\n─────────────────\n"
                "أرسل الأرقام التي تريد *استثناءها* (كل رقم في سطر).\n"
                "للإعادة تفعيل رقم مستثنى، استخدم خيار «➕ إضافة»."
            )
            context.user_data["state"] = "os_await_bot_ref_del"
            try:
                await q.edit_message_text(
                    "\n".join(_lines), parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:bot_ref_numbers")]]))
                except Exception:
                    await q.message.reply_text(
                        "\n".join(_lines), parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:bot_ref_numbers")]]))
            return

        if data.startswith("fref_kick:") and is_own:
            _parts = data.split(":")
            _fk_stock_id = int(_parts[1]) if len(_parts) > 1 else 0
            _fk_phone    = _parts[2]      if len(_parts) > 2 else ""
            await q.answer()
            with db_conn() as _fkc:
                _fkc.execute(
                    "UPDATE number_stock SET deleted_at=NOW() "
                    "WHERE (id=%s OR phone_number=%s) AND deleted_at IS NULL",
                    (_fk_stock_id, _fk_phone)
                )
            await context.bot.send_message(
                user.id,
                f"✅ تم إزالة الرقم <code>{_fk_phone}</code> من قائمة الإحالة الإجبارية.",
                parse_mode="HTML"
            )
            try:
                _orig_kb = q.message.reply_markup.inline_keyboard if q.message and q.message.reply_markup else []
                _new_kb  = [row for row in _orig_kb if not any(btn.callback_data == data for btn in row)]
                await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(_new_kb) if _new_kb else None)
            except Exception:
                pass
            return

        if data == "os:restricted_members" and is_own:
            await q.answer()
            try:
                with db_conn() as _c:
                    _rest = _c.execute(
                        "SELECT u.user_id, u.full_name, u.username, u.points, "
                        "COUNT(inv.user_id) AS ref_count "
                        "FROM users u "
                        "LEFT JOIN users inv ON inv.invited_by=u.user_id "
                        "WHERE u.referral_points_blocked=1 "
                        "GROUP BY u.user_id, u.full_name, u.username, u.points "
                        "ORDER BY ref_count DESC"
                    ).fetchall()
                _back_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔒 تقييد عضو يدوياً", callback_data="os:manual_restrict")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
                ])
                if not _rest:
                    await q.edit_message_text(
                        "👥 *الأعضاء المقيدون*\n\n✅ لا يوجد أعضاء مقيدون حالياً.",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=_back_kb)
                    return
                _lines = [f"👥 *الأعضاء المقيدون* ({len(_rest)} عضو)\n"]
                _kb_rows = []
                for r in _rest:
                    _r = dict(r)
                    _name = _r.get("full_name") or f"ID:{_r['user_id']}"
                    _un = f" (@{md_escape(_r['username'])})" if _r.get("username") else ""
                    _cnt = _r.get("ref_count", 0)
                    _pts = _r.get("points", 0)
                    _lines.append(f"👤 *{md_escape(_name)}*{_un}\n   🆔 `{_r['user_id']}` | 💰 {_pts:,} نقطة | 📊 {_cnt} إحالة")
                    _kb_rows.append([InlineKeyboardButton(
                        f"⚙️ {_name[:25]} ({_cnt} إحالة)",
                        callback_data=f"os:restricted_member:{_r['user_id']}:{_cnt}"
                    )])
                _kb_rows.append([InlineKeyboardButton("🔒 تقييد عضو يدوياً", callback_data="os:manual_restrict")])
                _kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
                _text = "\n".join(_lines)
                if len(_text) > 4000:
                    _text = _text[:4000] + "\n\n⚠️ القائمة طويلة، تم اقتصارها."
                try:
                    await q.edit_message_text(_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(_kb_rows))
                except Exception:
                    await q.message.reply_text(_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(_kb_rows))
            except Exception as _err:
                logger.error(f"❌ os:restricted_members error: {_err}")
                await q.message.reply_text(f"❌ خطأ في قاعدة البيانات: {_err}")
            return

        if data == "os:manual_restrict" and is_own:
            context.user_data["state"] = "os_await_restrict_target"
            await q.edit_message_text(
                "🔒 *تقييد عضو يدوياً*\n\n"
                "أرسل الـ ID الرقمي للعضو أو @يوزرنيم:\n"
                "_(سيُمنع من كسب نقاط الإحالة حتى ترفع التقييد)_",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:restricted_members")]]),
            )
            return

        if data.startswith("os:restricted_member:") and is_own:
            await q.answer()
            _parts = data.split(":")
            _rm_uid  = int(_parts[2])
            _rm_cnt  = int(_parts[3]) if len(_parts) > 3 else 0
            try:
                with db_conn() as _c:
                    _rm_user = _c.execute(
                        "SELECT user_id, full_name, username, points FROM users WHERE user_id=%s", (_rm_uid,)
                    ).fetchone()
                    _rm_refs = _c.execute(
                        "SELECT user_id, full_name, username, credited_at FROM users "
                        "WHERE invited_by=%s AND referral_credited=1 ORDER BY credited_at DESC LIMIT 20",
                        (_rm_uid,)
                    ).fetchall()
                if not _rm_user:
                    await q.edit_message_text("❌ المستخدم غير موجود.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:restricted_members")]]))
                    return
                _rm_user = dict(_rm_user)
                _name = md_escape(_rm_user.get("full_name") or f"ID:{_rm_uid}")
                _un   = f" (@{md_escape(_rm_user['username'])})" if _rm_user.get("username") else ""
                _pts  = _rm_user.get("points", 0)
                _rp   = int(get_setting("referral_points") or "30")
                _lines = [
                    f"⚙️ *إدارة العضو المقيد*\n\n"
                    f"👤 *{_name}*{_un}\n"
                    f"🆔 `{_rm_uid}`\n"
                    f"💰 رصيده الحالي: *{_pts:,} نقطة*\n
                    f"📊 إجمالي إحالاته: *{_rm_cnt}* إحالة\n\n"
                ]
                if _rm_refs:
                    _lines.append("📋 *آخر الإحالات:*\n")
                    for _r in _rm_refs:
                        _r = dict(_r)
                        _rn = md_escape(_r.get("full_name") or f"ID:{_r['user_id']}")
                        _run = f" (@{md_escape(_r['username'])})" if _r.get("username") else ""
                        _lines.append(f"• {_rn}{_run}")
                else:
                    _lines.append("📋 لا توجد إحالات مكتملة.")
                _text = "\n".join(_lines)
                if len(_text) > 4000:
                    _text = _text[:4000] + "\n\n⚠️ القائمة طويلة، تم اقتصارها."
                _act_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ إبقاء + رفع التقييد",          callback_data=f"os:ref_keep:{_rm_uid}:{_rp}")],
                    [InlineKeyboardButton("❌ خصم الإحالة + رفع التقييد",   callback_data=f"os:ref_deduct:{_rm_uid}:{_rp}")],
                    [InlineKeyboardButton("➕ خصم نقاط إضافية",              callback_data=f"os:ref_extra:{_rm_uid}:{_rp}")],
                    [InlineKeyboardButton("🔓 رفع التقييد فقط",              callback_data=f"os:ref_unblock:{_rm_uid}")],
                    [InlineKeyboardButton("🔙 رجوع للمقيدين",                callback_data="os:restricted_members")],
                ])
                try:
                    await q.edit_message_text(_text, parse_mode=ParseMode.MARKDOWN, reply_markup=_act_kb)
                except Exception:
                    await q.message.reply_text(_text[:4000], parse_mode=ParseMode.MARKDOWN, reply_markup=_act_kb)
            except Exception as _rm_err:
                logger.error(f"❌ os:restricted_member error: {_rm_err}")
                await q.message.reply_text(f"❌ خطأ في قاعدة البيانات: {_rm_err}")
            return

        if data == "os:edit_mpoints_price" and is_own:
            cur = get_setting("mandatory_points_price") or "5"
            context.user_data["state"] = "os_await_mpoints_price"
            await q.edit_message_text(
                f"💰 *سعر تمويل الإجباري بالنقاط (لكل عضو)*\n\nالحالي: {cur} نقطة\nأرسل السعر الجديد:",
                parse_mode=ParseMode.MARKDOWN)
            return

        if data == "os:edit_mpoints_min" and is_own:
            cur = get_setting("mandatory_points_min") or "50"
            context.user_data["state"] = "os_await_mpoints_min"
            await q.edit_message_text(
                f"💰 *الحد الأدنى للأعضاء (إجباري-نقاط)*\n\nالحالي: {cur} عضو\nأرسل الحد الجديد:",
                parse_mode=ParseMode.MARKDOWN)
            return

        if data == "os:referral_contest" and is_own:
            contest   = get_referral_contest()
            ctype     = contest["type"]
            now_utc   = datetime.now(timezone.utc)
            if ctype == "open":
                active_note = "\n\n🟢 *المسابقة نشطة الآن — مفتوحة (بدون وقت محدد)*"
            elif ctype == "limited":
                end_dt = contest["end"]
                if end_dt and end_dt > now_utc:
                    remaining   = _format_contest_time_remaining(end_dt)
                    active_note = f"\n\n🟡 *المسابقة نشطة — الوقت المتبقي: {remaining}*"
                else:
                    active_note = "\n\n🔴 *المسابقة انتهت*"
            else:
                active_note = "\n\n⚫ *لا توجد مسابقة نشطة حالياً*"
            _cs = contest.get("start")
            _start_str = _cs.strftime("%Y-%m-%d %H:%M UTC") if _cs else "غير محدد"
            kb_rows = [
                [InlineKeyboardButton("🔓 مفتوح (بدون وقت)", callback_data="os:contest:open")],
                [InlineKeyboardButton("⏳ محدد (بوقت)", callback_data="os:contest:limited")],
                [InlineKeyboardButton(f"📅 تعديل تاريخ البداية ({_start_str})", callback_data="os:contest:set_start")],
                [InlineKeyboardButton("🏁 إنهاء المسابقة", callback_data="os:contest:stop")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
            ]
            await q.edit_message_text(
                f"🎯 *مسابقة رابط الدعوة*{active_note}\n\nاختر نوع المسابقة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
            return

        if data == "os:contest:open" and is_own:
            now_utc = datetime.now(timezone.utc)
            set_setting("referral_contest_type",  "open")
            set_setting("referral_contest_start", now_utc.isoformat())
            set_setting("referral_contest_end",   "")
            await q.edit_message_text(
                "✅ *تم بدء مسابقة رابط الدعوة (مفتوحة)*\n\n"
                "لا يوجد وقت محدد للانتهاء — ستستمر حتى تُوقفها يدوياً.\n"
                "يرى الأعضاء قائمة المتصدرين بدون ذكر الوقت.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:referral_contest")]])
            )
            return

        if data == "os:contest:limited" and is_own:
            context.user_data["state"] = "os_await_contest_duration"
            await q.edit_message_text(
                "⏳ *مسابقة محدودة بوقت*\n\n"
                "أرسل المدة الزمنية بالصيغة التالية:\n"
                "• `7s` ← 7 ثوانٍ\n"
                "• `30m` ← 30 دقيقة\n"
                "• `24h` ← 24 ساعة\n"
                "• `7d` ← 7 أيام\n\n"
                "مثال: أرسل `7d` لمسابقة تدوم 7 أيام",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "os:contest:stop" and is_own:
            set_setting("referral_contest_type", "none")
            await q.edit_message_text(
                "🛑 *تم إيقاف المسابقة بنجاح.*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:referral_contest")]])
            )
            return

        if data == "os:contest:set_start" and is_own:
            context.user_data["state"] = "os_await_contest_start"
            await q.edit_message_text(
                "📅 *تعديل تاريخ بداية المسابقة*\n\n"
                "أرسل التاريخ والوقت بهذا الشكل (توقيت العراق UTC+3):\n"
                "`YYYY-MM-DD HH:MM`\n\n"
                "مثال: `2026-07-17 19:38`\n\n"
                "⚠️ كل الإحالات من هذا التاريخ فصاعداً ستُحتسب في المسابقة.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "referral_contest_view":
            contest  = get_referral_contest()
            ctype    = contest["type"]
            now_utc  = datetime.now(timezone.utc)
            back_to_referral = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="referral")]])
            if ctype == "none":
                await q.edit_message_text(
                    "⚫ *لا توجد مسابقة نشطة حالياً.*\n\nتابع البوت لمعرفة موعد انطلاق المسابقة القادمة!",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=back_to_referral
                )
                return
            since_dt = contest["start"]
            lb_rows  = get_top_referrers_since(since_dt, limit=10)
            if ctype == "limited":
                end_dt = contest["end"]
                if end_dt and end_dt > now_utc:
                    remaining = _format_contest_time_remaining(end_dt)
                    header    = f"🏆 *مسابقة رابط الدعوة*\n⏳ *الوقت المتبقي: {remaining}*\n\n"
                else:
                    header = "🏆 *مسابقة رابط الدعوة — انتهت المسابقة*\n\n"
            else:
                header = "🏆 *مسابقة رابط الدعوة*\n\n"
            leaderboard = _format_top_referrers(lb_rows, "المتصدرون")
            lb_lines    = leaderboard.split("\n")
            lb_body     = "\n".join(lb_lines[1:]) if len(lb_lines) > 1 else leaderboard
            await q.edit_message_text(
                header + lb_body,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_to_referral
            )
            return

        if data in ("collect_points", "daily_gift", "join_channels_menu"):
            db_user = get_user(user.id)
            rows = [
                [InlineKeyboardButton("🎁 الهدية اليومية", callback_data="daily_gift_screen")],
                [InlineKeyboardButton("📡 الانضمام بقنوات", callback_data="join_channels")],
                [InlineKeyboardButton(get_setting("gmail_button_label") or "📧 احصل على نقاط مقابل إيميل جيميل", callback_data="gmail_points")],
                [InlineKeyboardButton("🔐 التحقق", callback_data="totp_generator")],
                [InlineKeyboardButton("📋 الإيميلات المقبولة والمرفوضة", callback_data="my_gmail_history")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
            ]
            await q.edit_message_text(
                f"💰 *تجميع النقاط*\n\n"
                f"💰 رصيدك الحالي: {db_user['points'] if db_user else 0} نقطة\n\n"
                f"اختر أحد الخيارين للحصول على نقاط:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "gmail_points":
            intro_msg = get_setting("gmail_intro_message") or "للحصول على النقاط قدّم حساب جيميل لا تستخدمه."
            gmail_reward = int(get_setting("gmail_points_reward") or "10000")
            await q.edit_message_text(
                f"📧 *احصل على {gmail_reward:,} نقطة*\n\n{intro_msg}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ التالي", callback_data="gmail_next")],
                    [InlineKeyboardButton("🔐 التحقق", callback_data="totp_generator")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data="collect_points")],
                ])
            )
            return

        if data == "gmail_next":
            context.user_data["state"] = "await_gmail_email"
            email_prompt = get_setting("gmail_email_prompt") or "📧 *أرسل الإيميل*\n\nأرسل عنوان البريد الإلكتروني فقط بدون أي شيء آخر:"
            await q.edit_message_text(
                email_prompt,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ إلغاء", callback_data="collect_points")]
                ])
            )
            return

        if data == "totp_generator" or data.startswith("totp_generator:"):
            verification_sub_id = None
            if data.startswith("totp_generator:"):
                try:
                    verification_sub_id = int(data.split(":", 1)[1])
                except (IndexError, TypeError, ValueError):
                    await q.answer("❌ رابط التحقق غير صالح.", show_alert=True)
                    return
        
                with db_conn() as c:
                    verification_sub = c.execute(
                        "SELECT user_id, status, rejection_reason "
                        "FROM gmail_submissions WHERE id=%s",
                        (verification_sub_id,)
                    ).fetchone()
                if (
                    not verification_sub
                    or verification_sub["user_id"] != user.id
                    or verification_sub["status"] != "rejected"
                    or verification_sub["rejection_reason"] != "need_verify"
                ):
                    await q.answer(
                        "⚠️ لم يعد هذا الطلب متاحاً للتحقق.",
                        show_alert=True
                    )
                    return
                context.user_data["gmail_verification_sub_id"] = verification_sub_id
            else:
                context.user_data.pop("gmail_verification_sub_id", None)
        
            context.user_data["state"] = "await_totp_secret"
            await q.answer("✅ تم فتح خطوة التحقق.")
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            await context.bot.send_message(
                user.id,
                "🔐 *توليد كود المصادقة الثنائية*\n\n"
                "أرسل المفتاح السري (Base32) الخاص بحساب المصادقة الثنائية\n"
                "وسيقوم البوت بتوليد الكود الحالي فوراً.\n\n"
                "_مثال: JBSWY3DPEHPK3PXP_",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ إلغاء", callback_data="main_menu")]
                ])
            )
            return

        if data == "my_gmail_history" or data.startswith("my_gmail_history:"):
            _parts = data.split(":")
            if len(_parts) < 3:
                with db_conn() as c:
                    _counts = {r["status"]: r["n"] for r in c.execute(
                        "SELECT status, COUNT(*) AS n FROM gmail_submissions WHERE user_id=%s GROUP BY status",
                        (user.id,)
                    ).fetchall()}
                _ap = _counts.get("approved", 0)
                _rj = _counts.get("rejected", 0)
                _pn = _counts.get("pending",  0)
                await q.edit_message_text(
                    "📧 <b>إيميلاتك المقدَّمة</b>\n\nاختر الفئة التي تريد عرضها:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"✅ المقبولة ({_ap})",     callback_data="my_gmail_history:approved:0")],
                        [InlineKeyboardButton(f"❌ المرفوضة ({_rj})",     callback_data="my_gmail_history:rejected:0")],
                        [InlineKeyboardButton(f"⏳ المنتظرة ({_pn})",     callback_data="my_gmail_history:pending:0")],
                        [InlineKeyboardButton("🔙 رجوع",                  callback_data="collect_points")],
                    ])
                )
                return
            _status = _parts[1]
            try: _page = int(_parts[2])
            except Exception: _page = 0
            _limit  = 10
            _offset = _page * _limit
            _label  = {"approved": "✅ المقبولة", "rejected": "❌ المرفوضة", "pending": "⏳ المنتظرة"}.get(_status, _status)
            with db_conn() as c:
                _total = c.execute(
                    "SELECT COUNT(*) AS n FROM gmail_submissions WHERE user_id=%s AND status=%s",
                    (user.id, _status)
                ).fetchone()["n"]
                _subs = c.execute(
                    "SELECT gmail_email FROM gmail_submissions "
                    "WHERE user_id=%s AND status=%s ORDER BY id DESC LIMIT %s OFFSET %s",
                    (user.id, _status, _limit, _offset)
                ).fetchall()
            if not _subs:
                await q.edit_message_text(
                    f"📭 لا توجد إيميلات في فئة {_label}.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="my_gmail_history")]])
                )
                return
            lines = [f"• <code>{s['gmail_email']}</code>" for s in _subs]
            _nav = []
            if _page > 0:
                _nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"my_gmail_history:{_status}:{_page-1}"))
            if _offset + _limit < _total:
                _nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"my_gmail_history:{_status}:{_page+1}"))
            _rows = []
            if _nav: _rows.append(_nav)
            _rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="my_gmail_history")])
            await q.edit_message_text(
                f"📧 <b>{_label}</b> — {_total} إيميل\n\n" + "\n".join(lines),
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(_rows)
            )
            return

        if data == "daily_gift_screen":
            today = str(date.today())
            gift = int(get_setting("daily_gift_points") or "50")
            with db_conn() as c:
                gift_row = c.execute("SELECT last_claim FROM daily_gifts WHERE user_id=%s", (user.id,)).fetchone()
            already_claimed = gift_row and gift_row["last_claim"] == today
            db_user = get_user(user.id)
            if already_claimed:
                btn = [InlineKeyboardButton("⏰ تم استلام هديتك اليوم — عد غداً", callback_data="noop")]
            else:
                btn = [InlineKeyboardButton(f"🎁 استلام الهدية (+{gift} نقطة)", callback_data="daily_gift_collect")]
            rows = [
                btn,
                [InlineKeyboardButton("🔙 رجوع", callback_data="collect_points")],
            ]
            await q.edit_message_text(
                f"🎁 *الهدية اليومية*\n\n"
                f"💰 رصيدك الحالي: {db_user['points'] if db_user else 0} نقطة\n"
                f"🎁 الهدية اليوم: *{gift} نقطة* {'✅ مستلمة بالفعل' if already_claimed else '— متاحة الآن!'}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "daily_gift_collect":
            today = str(date.today())
            with db_conn() as c:
                row = c.execute("SELECT last_claim FROM daily_gifts WHERE user_id=%s", (user.id,)).fetchone()
                if row and row["last_claim"] == today:
                    await q.answer("⏰ لقد استلمت هديتك اليومية بالفعل! عد غداً.", show_alert=True)
                    return
                gift = int(get_setting("daily_gift_points") or "50")
                c.execute(
                    "INSERT INTO daily_gifts (user_id, last_claim) VALUES (%s, %s) "
                    "ON CONFLICT (user_id) DO UPDATE SET last_claim=EXCLUDED.last_claim",
                    (user.id, today)
                )
                c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (gift, user.id))
            db_user = get_user(user.id)
            await q.answer(f"🎁 حصلت على {gift} نقطة!", show_alert=True)
            rows = [
                [InlineKeyboardButton("⏰ تم استلام هديتك اليوم — عد غداً", callback_data="noop")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="collect_points")],
            ]
            await q.edit_message_text(
                f"🎁 *الهدية اليومية*\n\n"
                f"✅ استلمت *{gift} نقطة* بنجاح!\n"
                f"💰 رصيدك الآن: {db_user['points'] if db_user else 0} نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "check_mandatory_join":
            unjoined = await get_unjoined_mandatory_channels(context, user.id)
            if unjoined:
                await q.answer("❌ لم تشترك بعد بجميع القنوات المطلوبة.", show_alert=True)
                await show_mandatory_gate(update, context, unjoined, edit=True, is_owner=is_own)
                return
            await q.answer("✅ تم التحقق من اشتراكك!")
            db_user = get_user(user.id)
            if db_user and db_user.get("verified", 0):
                await count_user_for_fundings(user.id, context)
                context.user_data["state"] = "main_menu"
                db_user = get_user(user.id)
                pts = db_user["points"] if db_user else 0
                await q.edit_message_text(
                    f"✅ *تم التحقق! أهلاً بك مجدداً.*\n\n💰 رصيدك: {pts} نقطة",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=main_menu_kb(is_own)
                )
            else:
                await proceed_after_mandatory(update, context, edit=True)
            return

        if data == "join_channels":
            with db_conn() as c:
                channels = c.execute(
                    "SELECT * FROM mandatory_channels WHERE active=1 AND funding_type='internal' ORDER BY id"
                ).fetchall()
            if not channels:
                await q.edit_message_text(
                    "📡 لا توجد قنوات للانضمام حالياً.",
                    reply_markup=back_kb("collect_points")
                )
                return
            reward = int(get_setting("join_channel_reward") or "45")
            db_user = get_user(user.id)
            rows = []
            for ch in channels:
                with db_conn() as c:
                    claimed = c.execute(
                        "SELECT 1 FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                        (user.id, ch["id"])
                    ).fetchone()
                rows.append([InlineKeyboardButton(
                    f"📢 @{ch['channel_username']}",
                    url=f"https://t.me/{ch['channel_username']}"
                )])
                if not claimed:
                    rows.append([InlineKeyboardButton(
                        f"✅ تحقق من انضمامي (+{reward} نقطة)",
                        callback_data=f"join_verify:{ch['id']}"
                    )])
                else:
                    rows.append([InlineKeyboardButton("✔️ تم الحصول على نقاطك", callback_data="noop")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="collect_points")])
            await q.edit_message_text(
                f"📡 *الانضمام بقنوات*\n\n"
                f"💰 رصيدك الحالي: {db_user['points'] if db_user else 0} نقطة\n"
                f"🎁 انضم لأي قناة واحصل على *{reward} نقطة*\n"
                f"اضغط ✅ تحقق من انضمامي بعد الانضمام:"
                f"{_leave_penalty_note()}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data.startswith("join_verify:"):
            ch_id = int(data.split(":")[1])
            with db_conn() as c:
                ch = c.execute("SELECT * FROM mandatory_channels WHERE id=%s", (ch_id,)).fetchone()
            if not ch:
                await q.answer("⚠️ القناة غير موجودة.", show_alert=True)
                return
            with db_conn() as c:
                already = c.execute(
                    "SELECT 1 FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                    (user.id, ch_id)
                ).fetchone()
            if already:
                await q.answer("✔️ لقد حصلت على نقاط هذه القناة سابقاً.", show_alert=True)
                return
            try:
                member = await context.bot.get_chat_member(f"@{ch['channel_username']}", user.id)
                is_member = member.status not in ("left", "kicked", "banned")
            except Exception:
                await q.answer("⚠️ تعذّر التحقق. تأكد أنك انضممت ثم حاول.", show_alert=True)
                return
            if not is_member:
                await q.answer("❌ لم تنضم بعد! انضم للقناة أولاً ثم اضغط تحقق.", show_alert=True)
                return
            reward = int(get_setting("join_channel_reward") or "45")
            with db_conn() as c:
                c.execute(
                    "INSERT INTO channel_join_rewards (user_id, channel_id, joined_at) VALUES (%s, %s, NOW()) "
                    "ON CONFLICT (user_id, channel_id) DO NOTHING",
                    (user.id, ch_id)
                )
                inserted = c.rowcount
                if inserted > 0:
                    c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (reward, user.id))
            if not inserted:
                await q.answer("✔️ لقد حصلت على نقاط هذه القناة سابقاً.", show_alert=True)
                return
            db_user = get_user(user.id)
            await q.answer(f"🎉 حصلت على {reward} نقطة!", show_alert=True)
            with db_conn() as c:
                channels = c.execute(
                    "SELECT * FROM mandatory_channels WHERE active=1 AND funding_type='internal' ORDER BY id"
                ).fetchall()
            rows = []
            for ch2 in channels:
                with db_conn() as c:
                    claimed = c.execute(
                        "SELECT 1 FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                        (user.id, ch2["id"])
                    ).fetchone()
                rows.append([InlineKeyboardButton(
                    f"📢 @{ch2['channel_username']}",
                    url=f"https://t.me/{ch2['channel_username']}"
                )])
                if not claimed:
                    rows.append([InlineKeyboardButton(
                        f"✅ تحقق من انضمامي (+{reward} نقطة)",
                        callback_data=f"join_verify:{ch2['id']}"
                    )])
                else:
                    rows.append([InlineKeyboardButton("✔️ تم الحصول على نقاطك", callback_data="noop")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="join_channels")])
            await q.edit_message_text(
                f"📡 *الانضمام بقنوات*\n\n"
                f"🎁 انضم لأي قناة واحصل على *{reward} نقطة*\n"
                f"💰 رصيدك الآن: {db_user['points'] if db_user else 0} نقطة"
                f"{_leave_penalty_note()}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "charge_points":
            try:
                await q.edit_message_text("💎 *اختر طريقة الشحن:*", parse_mode=ParseMode.MARKDOWN,
                                           reply_markup=charge_points_kb())
            except Exception as _e:
                logger.error(f"❌ charge_points error: {_e}")
                if is_own:
                    await q.answer(f"❌ خطأ: {_e}", show_alert=True)
            return

        if data == "charge:stars":
            rate = get_setting("star_to_points") or "250"
            await q.edit_message_text(
                f"⭐ *الشحن عبر النجوم*\n\n💡 سعر النجمة الواحدة = {rate} نقطة\n\nاختر الكمية أو الطريقة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=charge_stars_kb()
            )
            return

        if data == "charge:info":
            await q.answer("هذا مجرد عرض للسعر.", show_alert=False)
            return

        if data.startswith("charge:quick:"):
            stars = int(data.split(":")[2])
            rate  = int(get_setting("star_to_points") or "250")
            pts   = stars * rate
            await q.edit_message_text(
                f"⭐ *{stars} نجمة = {pts} نقطة*\n\nجارٍ تحضير الفاتورة...",
                parse_mode=ParseMode.MARKDOWN
            )
            await context.bot.send_invoice(
                chat_id=user.id,
                title="شحن نقاط",
                description=f"شراء {pts} نقطة مقابل {stars} نجمة",
                payload=f"charge_stars:{stars}:{user.id}",
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice("نجوم", stars)],
            )
            return

        if data == "charge:by_points":
            rate = get_setting("star_to_points") or "250"
            context.user_data["state"] = "await_charge_points_amount"
            await q.edit_message_text(
                f"💡 *ملاحظة:* سعر النجمة الواحدة = {rate} نقطة\n\nأرسل عدد النقاط التي تريدها:",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "charge:by_stars":
            rate = get_setting("star_to_points") or "250"
            context.user_data["state"] = "await_charge_stars_amount"
            await q.edit_message_text(
                f"💡 *ملاحظة:* سعر النجمة الواحدة = {rate} نقطة\n\nأرسل عدد النجوم المراد شحنها:",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "charge:asiacell":
            asiacell_txt = get_setting("asiacell_text") or "⚠️ الشحن التلقائي عبر اسيا سيل غير متاح حالياً.\nيرجى التواصل مع المالك."
            kb_rows = contact_owner_row() + [[InlineKeyboardButton("🔙 رجوع", callback_data="charge_points")]]
            await q.edit_message_text(asiacell_txt, reply_markup=InlineKeyboardMarkup(kb_rows))
            return

        if data == "exchange_points":
            await q.edit_message_text("🏆 *استبدال النقاط بجوائز:*",
                                       parse_mode=ParseMode.MARKDOWN, reply_markup=exchange_kb())
            return

        if data == "exchange:stars":
            rate = int(get_setting("exchange_star_rate") or "2000")
            with db_conn() as c:
                packages = c.execute("SELECT * FROM exchange_star_packages WHERE active=1 ORDER BY stars").fetchall()
            if not packages:
                kb_rows = contact_owner_row() + [[InlineKeyboardButton("🔙 رجوع", callback_data="exchange_points")]]
                await q.edit_message_text(
                    "⚠️ لا توجد باقات استبدال متاحة حالياً.\nتواصل مع المالك لإضافة باقات.",
                    reply_markup=InlineKeyboardMarkup(kb_rows)
                )
                return
            rows = []
            for pkg in packages:
                stars = pkg["stars"]
                cost = stars * rate
                rows.append([InlineKeyboardButton(f"⭐ {stars} نجمة = {cost} نقطة", callback_data=f"exchange:pkg:{stars}")])
            rows += contact_owner_row()
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="exchange_points")])
            await q.edit_message_text(
                f"⭐ *استبدال نقاط بنجوم*\n\n"
                f"💡 سعر النجمة الواحدة: {rate} نقطة\n\n"
                f"اختر الباقة المطلوبة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data.startswith("exchange:pkg:"):
            stars = int(data.split(":")[2])
            rate = int(get_setting("exchange_star_rate") or "2000")
            cost = stars * rate
            db_user = get_user(user.id)
            pts = db_user["points"] if db_user else 0
            if pts < cost:
                kb_rows = contact_owner_row() + [[InlineKeyboardButton("🔙 رجوع", callback_data="exchange:stars")]]
                await q.edit_message_text(
                    f"❌ *نقاطك غير كافية!*\n\n"
                    f"⭐ تحتاج: {cost} نقطة\n"
                    f"💎 رصيدك: {pts} نقطة",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(kb_rows)
                )
                return
            if not deduct_points(user.id, cost):
                await q.edit_message_text("❌ حدث خطأ في خصم النقاط.", reply_markup=back_kb("exchange:stars"))
                return
            code = next_order_code(user.id)
            with db_conn() as c:
                pe = c.execute(
                    "INSERT INTO prize_exchanges (user_id,prize_type,prize_value,points_cost,status,order_code) "
                    "VALUES (%s,%s,%s,%s,'pending',%s) RETURNING id",
                    (user.id, "stars", str(stars), cost, code)
                ).fetchone()
            custom_msg = get_setting("exchange_success_msg") or ""
            result_kb_rows = contact_owner_row() + [[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]]
            await q.edit_message_text(
                f"✅ *تمت العملية بنجاح!*\n\n"
                f"⭐ طلب {stars} نجمة مسجل\n"
                f"💰 التكلفة: {cost} نقطة\n\n"
                + (f"{custom_msg}\n\n" if custom_msg else "")
                + "سيتواصل معك المالك قريباً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(result_kb_rows)
            )
            await context.bot.send_message(
                user.id,
                f"📌 *كود عمليتك:* `{code}`",
                parse_mode=ParseMode.MARKDOWN
            )
            await notify_prize_exchange_owner(
                context, pe["id"],
                f"⭐ <b>طلب شراء نجوم (جائزة)</b>\n"
                f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                f"⭐ {stars} نجمة مقابل {cost} نقطة\n"
                f"📌 {code}"
            )
            return

        if data == "exchange:number":
            if not is_number_exchange_on():
                await q.answer("🔒 استبدال الأرقام مغلق حالياً. تواصل مع المالك.", show_alert=True)
                return
            cost = int(get_setting("telegram_number_cost") or "5000")
            db_user = get_user(user.id)
            if db_user["points"] < cost:
                kb_rows = contact_owner_row() + [[InlineKeyboardButton("🔙 رجوع", callback_data="exchange_points")]]
                await q.edit_message_text(
                    f"❌ نقاطك غير كافية! تحتاج {cost} نقطة ولديك {db_user['points']} نقطة.",
                    reply_markup=InlineKeyboardMarkup(kb_rows)
                )
                return
            if not deduct_points(user.id, cost):
                await q.edit_message_text("❌ حدث خطأ في خصم النقاط.", reply_markup=back_kb("exchange_points"))
                return
            code = next_order_code(user.id)
        
            auto = await assign_verified_number(user.id, bot=context.bot)
            if auto:
                auto_number = auto["phone_number"]
                session_str = auto["session_string"]
                with db_conn() as c:
                    pe = c.execute(
                        "INSERT INTO prize_exchanges (user_id,prize_type,prize_value,points_cost,status,order_code) "
                        "VALUES (%s,%s,%s,%s,'completed',%s) RETURNING id",
                        (user.id, "telegram_number", auto_number, cost, code)
                    ).fetchone()
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
                await q.edit_message_text(
                    f"✅ *تم شراء رقمك بنجاح!*\n\n"
                    f"📱 *الرقم:*\n`{display_number}`\n\n"
                    f"اضغط على الأزرار أدناه للحصول على رمز التحقق وكود الدخول عند الحاجة.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(result_kb)
                )
                try:
                    await context.bot.send_message(
                        user.id,
                        "📋 *إشعار تبرئة ذمة — يُرجى القراءة بعناية*\n\n"
                        "بإتمامك عملية الشراء فإنك تُقرّ وتوافق على ما يلي:\n\n"
                        "① لا يتحمّل البائع أي مسؤولية عن أي محتوى موجود داخل الحساب سابقاً، "
                        "سواء كان مجموعات، قنوات، محادثات، جهات اتصال، صور، ملفات، أو أي بيانات أخرى.\n\n"
                        "② لا يتحمّل البائع أي مسؤولية عن أي حظر، تقييد، أو إجراء تتخذه منصة تيليغرام "
                        "على الحساب لاحقاً بسبب أي نشاط سابق أو لاحق.\n\n"
                        "③ لا يتحمّل البائع أي مسؤولية عن أي استخدام سابق للرقم أو الحساب قبل تاريخ بيعه.\n\n"
                        "④ من لحظة الاستلام يُصبح الحساب والرقم مسؤوليتك الكاملة والمطلقة؛ "
                        "أي حظر، تجميد، أو تغيير يطرأ عليه لاحقاً لا يخصّ البائع بأي شكل.\n\n"
                        "⑤ لا يحق المطالبة باسترداد أو تعويض بعد استلام بيانات الدخول.\n\n"
                        "شكراً لثقتك 🤍",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass
                if pe:
                    await notify_prize_exchange_owner(
                        context, pe["id"],
                        text_html=(
                            f"📱 <b>شراء رقم تيلغرام — تسليم تلقائي ✅</b>\n"
                            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                            f"📱 الرقم: <code>{auto_number}</code>\n"
                            f"💰 {cost:,} نقطة\n"
                            f"📌 {code}"
                        ),
                        group_text_html=(
                            f"📱 <b>شراء رقم تيلغرام — تسليم تلقائي ✅</b>\n"
                            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                            f"💰 {cost:,} نقطة\n"
                            f"📌 {code}"
                        ),
                    )
                return
        
            add_points(user.id, cost)
            await q.edit_message_text(
                "😔 *نأسف، لم تتم العملية*\n\n"
                "لا يتوفر حالياً أي رقم متاح في المخزون.\n"
                f"تم إعادة *{cost:,} نقطة* إلى رصيدك كاملةً.\n\n"
                "يمكنك المحاولة مجدداً في وقت لاحق 🙏",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")
                ]])
            )
            return

        if data == "exchange:number_stars":
            if not is_number_exchange_on():
                await q.answer("🔒 شراء الأرقام مغلق حالياً. تواصل مع المالك.", show_alert=True)
                return
            stars = int(get_setting("telegram_number_stars") or "18")
            if stars <= 0:
                await q.answer("⚠️ شراء الرقم بالنجوم غير متاح حالياً.", show_alert=True)
                return
            await q.edit_message_text(
                f"📱 *شراء رقم تيلغرام بالنجوم*\n\n"
                f"⭐ السعر: *{stars} نجمة*\n"
                f"سيتم تسليم الرقم تلقائياً بعد نجاح الدفع.",
                parse_mode=ParseMode.MARKDOWN
            )
            await context.bot.send_invoice(
                chat_id=user.id,
                title="شراء رقم تيلغرام",
                description=f"رقم تيلغرام جاهز مقابل {stars} نجمة",
                payload=f"number_stars:{user.id}:{stars}",
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice("رقم تيلغرام", stars)],
            )
            return

        if data == "exchange:num_code":
            if not is_number_exchange_on():
                await q.answer("🔒 شراء الأرقام مغلق حالياً. تواصل مع المالك.", show_alert=True)
                return
            context.user_data["state"] = "await_num_purchase_code"
            await q.edit_message_text(
                "🎟 *شراء رقم تيلغرام عبر كود*\n\n"
                "أرسل الكود الخاص بك لإتمام عملية الشراء:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_kb("exchange_points")
            )
            return

        if data == "use_promo":
            context.user_data["state"] = "await_promo_code"
            await q.edit_message_text(
                "🎟 *استخدام كود ترويجي*\n\nأرسل الكود:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_kb()
            )
            return

        if data == "transfer_points":
            context.user_data["state"] = "await_transfer_id"
            await q.edit_message_text("↔️ *تحويل النقاط*\n\nأرسل ايدي المستلم (رقمي):", parse_mode=ParseMode.MARKDOWN)
            return

        if data == "my_info":
            db_user = get_user(user.id)
            if not db_user:
                await q.edit_message_text("⚠️ لم يتم العثور على بياناتك. أرسل /start أولاً.")
                return
            with db_conn() as c:
                inv_credited = c.execute(
                    "SELECT COUNT(*) as cnt FROM users WHERE invited_by=? AND referral_credited=1",
                    (user.id,)
                ).fetchone()["cnt"]
                inv_pending  = c.execute(
                    "SELECT COUNT(*) as cnt FROM users WHERE invited_by=? AND referral_credited=0",
                    (user.id,)
                ).fetchone()["cnt"]
            invited_line = f"{inv_credited} مكتمل"
            if inv_pending:
                invited_line += f" + {inv_pending} بانتظار التحقق"
            await q.edit_message_text(
                f"👤 *معلوماتك:*\n\n"
                f"🆔 معرفك: `{user.id}`\n"
                f"💰 نقاطك: {db_user['points']}\n"
                f"👥 من دعوتهم: {invited_line}\n"
                f"📦 عدد طلباتك: {db_user['total_orders']}\n"
                f"🔢 رقمك في البوت: #{db_user['bot_user_num']}\n"
                f"📅 تاريخ الانضمام: {db_user['joined_at']}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_kb()
            )
            return

        if data == "my_numbers":
            with db_conn() as _mn_db:
                _mn_rows = _mn_db.execute(
                    "SELECT pe.prize_value AS phone, pe.created_at AS purchased_at,"
                    "       ns.last_authorized, ns.twofa_password"
                    " FROM prize_exchanges pe"
                    " LEFT JOIN number_stock ns ON ns.phone_number = pe.prize_value"
                    " WHERE pe.user_id = %s AND pe.status = 'completed'"
                    " AND pe.prize_type IN ('telegram_number', 'telegram_number_code', 'telegram_number_stars')"
                    " ORDER BY pe.created_at DESC",
                    (user.id,)
                ).fetchall()
            if not _mn_rows:
                await q.edit_message_text(
                    "📱 *ارقامي*\n\n"
                    "لم تقم بشراء أي رقم حتى الآن.\n\n"
                    "اذهب إلى *استبدال نقاط بجوائز* لشراء رقم.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=back_kb()
                )
                return
            _mn_kb = []
            _mn_kicked_count = 0
            for _mn_r in _mn_rows:
                _mn_phone = _mn_r["phone"]
                _mn_clean = _mn_phone.lstrip("+")
                _mn_kicked = (_mn_r["last_authorized"] is False) or (_mn_r["last_authorized"] == False)
                if _mn_kicked:
                    _mn_kicked_count += 1
                    _mn_kb.append([InlineKeyboardButton(
                        "🚫 " + _mn_clean + " (مطرود)",
                        callback_data="my_numbers:kicked:" + _mn_phone
                    )])
                else:
                    _mn_kb.append([InlineKeyboardButton(
                        "📱 " + _mn_clean,
                        callback_data="noop"
                    )])
                    _mn_kb.append([
                        InlineKeyboardButton("🔐 2FA",    callback_data="buyer:show_twofa:"  + _mn_phone),
                        InlineKeyboardButton("🔑 كود", callback_data="buyer:request_code:" + _mn_phone),
                        InlineKeyboardButton("📷 باركود",  callback_data="buyer:barcode:"       + _mn_phone),
                    ])
                    _mn_kb.append([InlineKeyboardButton(
                        "🚪 مغادرة البوت",
                        callback_data="buyer:leave_account:" + _mn_phone
                    )])
            _mn_kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
            _mn_total  = len(_mn_rows)
            _mn_active = _mn_total - _mn_kicked_count
            _mn_title  = "📱 *ارقامي*\n\n"
            _mn_stats  = ("📊 إجمالي: " + str(_mn_total)
                          + " | ✅ " + str(_mn_active)
                          + " | 🚫 " + str(_mn_kicked_count) + "\n\n")
            _mn_hint   = "اختر رقماً لعرض خياراته:"
            await q.edit_message_text(
                _mn_title + _mn_stats + _mn_hint,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(_mn_kb)
            )
            return
    return True
