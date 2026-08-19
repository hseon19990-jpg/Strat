"""Callback case group 2 for the Telegram bot.

Cases stay in their original order. A matching case returns from this group,
while the sentinel lets the dispatcher continue to the next group.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

async def _handle_callback_group_02(update, context, q, data, user, is_own, is_supervisor_cb, _gmail_verification_done):
    if True:
        if data.startswith("my_numbers:kicked:"):
            _kicked_ph = data[len("my_numbers:kicked:"):].lstrip("+")
            _kicked_msg = ("\u26a0\ufe0f \u0639\u0630\u0631\u064b\u0627\u060c \u0644\u0642\u062f \u0642\u0645\u062a \u0628\u0637\u0631\u062f \u0627\u0644\u0628\u0648\u062a \u0645\u0646 \u0627\u0644\u0631\u0642\u0645 "
                           + _kicked_ph + "\n\u0644\u0627 \u064a\u0645\u0643\u0646\u0646\u064a \u0627\u0644\u0645\u0633\u0627\u0639\u062f\u0629 \u0628\u0639\u062f \u0627\u0644\u0622\u0646.")
            await q.answer(_kicked_msg, show_alert=True)
            return

        if data == "fund_channel":
            await q.edit_message_text("📺 *تمويل قناتك حقيقي:*", parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=fund_channel_kb())
            return

        if data == "fund:mandatory":
            _stars_min    = int(get_setting("mandatory_stars_min_members")    or "50")
            _stars_t1_max = int(get_setting("mandatory_stars_tier1_max")      or "120")
            _t1_x100      = int(get_setting("mandatory_stars_tier1_price_x100") or "50")
            _t2_x100      = int(get_setting("mandatory_stars_tier2_price_x100") or "33")
            _pts_price    = int(get_setting("mandatory_points_price") or "5")
            _pts_min      = int(get_setting("mandatory_points_min")   or "50")
            await q.edit_message_text(
                f"📢 *تمويل قناة إجباري*\n\n"
                f"اختر طريقة الدفع:\n\n"
                f"⭐ *بالنجوم:* {_stars_min:,}–{_stars_t1_max:,} عضو → كل عضوان بـ 1⭐ | {_stars_t1_max+1:,}+ → كل 3 بـ 1⭐\n"
                f"💰 *بالنقاط:* {_pts_price} نقطة/عضو | حد أدنى {_pts_min:,} عضو",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⭐ الدفع بالنجوم", callback_data="fund:mandatory:stars")],
                    [InlineKeyboardButton("💰 الدفع بالنقاط", callback_data="fund:mandatory:points")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="fund_channel")],
                ])
            )
            return

        if data == "fund:mandatory:stars":
            _stars_min    = int(get_setting("mandatory_stars_min_members")    or "50")
            _stars_t1_max = int(get_setting("mandatory_stars_tier1_max")      or "120")
            _t1_x100      = int(get_setting("mandatory_stars_tier1_price_x100") or "50")
            _t2_x100      = int(get_setting("mandatory_stars_tier2_price_x100") or "33")
            context.user_data["fund_type"] = "mandatory"
            context.user_data["state"]     = "await_fund_member_count"
            await q.edit_message_text(
                f"📢 *تمويل إجباري — الدفع بالنجوم ⭐*\n\n"
                f"📊 *جدول الأسعار:*\n"
                f"  • {_stars_min:,} – {_stars_t1_max:,} عضو: كل *عضوان* بـ *1 ⭐*\n"
                f"  • {_stars_t1_max+1:,} وأكثر: كل *3 أعضاء* بـ *1 ⭐*\n"
                f"  • الحد الأدنى: *{_stars_min:,} عضو*\n\n"
                f"📊 *الخطوة 1/3:* أرسل *عدد أعضاء قناتك* الحالي:",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "fund:mandatory:points":
            _pts_price = int(get_setting("mandatory_points_price") or "5")
            _pts_min   = int(get_setting("mandatory_points_min")   or "50")
            context.user_data["fund_type"] = "mandatory_points"
            context.user_data["state"]     = "await_fund_member_count"
            await q.edit_message_text(
                f"📢 *تمويل إجباري — الدفع بالنقاط 💰*\n\n"
                f"💰 السعر: *{_pts_price} نقطة لكل عضو*\n"
                f"👥 الحد الأدنى: *{_pts_min:,} عضو*\n\n"
                f"📊 *الخطوة 1/3:* أرسل *عدد أعضاء قناتك* الحالي:",
                parse_mode=ParseMode.MARKDOWN
            )
            return
            # ─── تمويل إجباري بالنجوم (Stars) ───
            _stars_min    = int(get_setting("mandatory_stars_min_members")    or "50")
            _stars_t1_max = int(get_setting("mandatory_stars_tier1_max")      or "120")
            _t1_x100      = int(get_setting("mandatory_stars_tier1_price_x100") or "50")
            _t2_x100      = int(get_setting("mandatory_stars_tier2_price_x100") or "33")
            context.user_data["fund_type"] = "mandatory"
            context.user_data["state"]     = "await_fund_member_count"
            await q.edit_message_text(
                f"📢 *تمويل قناة إجباري — الدفع بالنجوم ⭐*\n\n"
                f"✅ ستُضاف قناتك كقناة اشتراك إجباري في البوت\n\n"
                f"📊 *جدول الأسعار:*\n"
                f"  • {_stars_min:,} – {_stars_t1_max:,} عضو: كل *عضوان* بـ *1 ⭐*\n"
                f"  • {_stars_t1_max+1:,} وأكثر: كل *3 أعضاء* بـ *1 ⭐*\n"
                f"  • الحد الأدنى: *{_stars_min:,} عضو*\n\n"
                f"📊 *الخطوة 1/3:* أرسل *عدد أعضاء قناتك* الحالي:",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "fund:internal":
            cost_per = get_setting("internal_channel_cost") or "100"
            min_members = get_setting("internal_channel_min_members") or "0"
            context.user_data["fund_type"] = "internal"
            context.user_data["state"]     = "await_fund_member_count"
            min_txt = f"👥 الحد الأدنى للأعضاء: *{int(min_members):,}*\n" if int(min_members) > 0 else ""
            await q.edit_message_text(
                f"🔄 *تمويل قناة داخلي بطيء*\n\n"
                f"✅ ستُضاف قناتك في قسم انضم بقنوات\n"
                f"👥 الأعضاء يجمعون نقاط وينضمون لقناتك\n"
                f"💰 السعر: *{cost_per} نقطة لكل عضو*\n"
                f"{min_txt}\n"
                f"📊 *الخطوة 1/3:* أرسل *عدد أعضاء قناتك* الحالي:",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "fund_confirm:yes":
            fund_type    = context.user_data.get("fund_type", "mandatory")
            channel      = context.user_data.get("fund_channel_username", "")
            member_count = context.user_data.get("fund_member_count", 1)
            cost_key     = "mandatory_channel_cost" if fund_type in ("mandatory", "mandatory_points") else "internal_channel_cost"
            cost_per     = int(get_setting(cost_key) or "200")
            cost         = context.user_data.get("fund_total_cost", cost_per * member_count)
            ft_label     = "إجباري سريع" if fund_type in ("mandatory", "mandatory_points") else "داخلي بطيء"
            channel_md   = md_escape(channel)
            if not channel:
                await q.edit_message_text("⚠️ انتهت الجلسة، ابدأ من جديد.", reply_markup=main_menu_kb(is_own))
                context.user_data["state"] = "main_menu"
                return
            if not deduct_points(user.id, cost):
                await q.edit_message_text(f"❌ نقاطك غير كافية. التكلفة الإجمالية: {cost:,} نقطة.", reply_markup=main_menu_kb(is_own))
                context.user_data["state"] = "main_menu"
                return
            code = next_order_code(user.id)
        
            is_queued = False
            if fund_type in ("mandatory", "mandatory_points") and count_active_mandatory_channels() >= MANDATORY_MAX_ACTIVE:
                is_queued = True
        
            with db_conn() as c:
                c.execute(
                    "INSERT INTO channel_funding (user_id,channel_username,funding_type,cost_points,target_members,current_members,status) "
                    "VALUES (%s,%s,%s,%s,%s,0,'active')",
                    (user.id, channel, fund_type, cost, member_count)
                )
                mc_fund_type = "mandatory" if fund_type in ("mandatory", "mandatory_points") else fund_type
                c.execute(
                    "INSERT INTO mandatory_channels (channel_username,owner_user_id,funding_type,active,queued) "
                    "VALUES (%s,%s,%s,%s,%s) "
                    "ON CONFLICT (channel_username) DO UPDATE SET funding_type=EXCLUDED.funding_type, owner_user_id=EXCLUDED.owner_user_id, "
                    "active=EXCLUDED.active, queued=EXCLUDED.queued",
                    (channel, user.id, mc_fund_type, 0 if is_queued else 1, 1 if is_queued else 0)
                )
            context.user_data["state"] = "main_menu"
            context.user_data.pop("fund_channel_username", None)
            context.user_data.pop("fund_member_count", None)
            context.user_data.pop("fund_total_cost", None)
        
            if is_queued:
                await q.edit_message_text(
                    f"⏳ *تم استلام تمويل قناتك وسُحبت النقاط بنجاح، لكنها في قائمة الانتظار حالياً.*\n\n"
                    f"📢 القناة: @{channel_md}\n"
                    f"👥 عدد الأعضاء: {member_count:,}\n"
                    f"💰 التكلفة: {cost_per} × {member_count:,} = *{cost:,} نقطة*\n\n"
                    f"⚠️ عدد القنوات الإجبارية النشطة حالياً بلغ الحد الأقصى ({MANDATORY_MAX_ACTIVE} قنوات).\n"
                    f"✅ ستُفعَّل قناتك تلقائياً وتظهر لجميع المستخدمين فور تحرّر أحد الأماكن (عند اكتمال إحدى القنوات العشرة).",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=main_menu_kb(is_own)
                )
            else:
                await q.edit_message_text(
                    f"✅ *تم تفعيل تمويل قناتك بنجاح!*\n\n"
                    f"📢 القناة: @{channel_md}\n"
                    f"⚙️ النوع: {ft_label}\n"
                    f"👥 عدد الأعضاء: {member_count:,}\n"
                    f"💰 التكلفة: {cost_per} × {member_count:,} = *{cost:,} نقطة*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=main_menu_kb(is_own)
                )
            await context.bot.send_message(
                user.id,
                f"📌 *كود عمليتك:* `{code}`\nاحفظه قد تحتاجه لاحقاً.",
                parse_mode=ParseMode.MARKDOWN
            )
        
            _queue_note = "\n⏳ <b>ملاحظة:</b> دخلت قائمة الانتظار (الحد الأقصى ممتلئ) وستُفعَّل تلقائياً عند توفر مكان." if is_queued else ""
            _terms = mandatory_terms_text_html() if fund_type in ("mandatory", "mandatory_points") else ""
            await notify_group(
                context.application,
                f"📢 <b>تمويل قناة {ft_label}</b>\n"
                f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                f"📡 القناة: @{channel}\n"
                f"👥 {member_count:,} عضو\n"
                f"💰 {cost:,} نقطة ({cost_per} × {member_count:,})\n"
                f"📌 {code}"
                f"{_queue_note}\n"
                f"{_terms}",
                parse_mode="HTML"
            )
            return

        if data == "fund_confirm:no":
            context.user_data["state"] = "main_menu"
            context.user_data.pop("fund_channel_username", None)
            context.user_data.pop("fund_member_count", None)
            await q.edit_message_text("❌ تم إلغاء طلب التمويل.", reply_markup=main_menu_kb(is_own))
            return

        if data == "owner_settings" and is_own:
            if context.user_data.get("state", "").startswith("await_mb_"):
                context.user_data["state"] = "main_menu"
                for k in ("mb_menu", "mb_type", "mb_label"):
                    context.user_data.pop(k, None)
            await q.edit_message_text("⚙️ *إعدادات المالك:*", parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=owner_settings_kb())
            return

        if data == "os:account_info" and is_own:
            total_accounts, session_accounts, story_available, avatar_available = _account_info_counts()
            name_count = _account_name_count()
            await q.edit_message_text(
                "👤 *معلومات الحسابات*\n\n"
                f"📦 إجمالي الحسابات: {total_accounts:,}\n"
                f"🔐 حسابات لديها جلسة: {session_accounts:,}\n"
                f"🔤 أسماء محفوظة: {name_count:,}\n"
                f"📖 المتبقي للستوري: {story_available:,}\n"
                f"🖼️ المتبقي للأفتار: {avatar_available:,}\n\n"
                "اختر العملية المطلوبة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=account_info_kb(),
            )
            return

        if data == "os:account_names" and is_own:
            name_count = _account_name_count()
            context.user_data["state"] = "os_await_account_names"
            await q.edit_message_text(
                "🔤 *أسماء الحسابات*\n\n"
                f"تم حفظ أسماء {name_count:,} حساباً حتى الآن.\n\n"
                "أرسل اسماً واحداً في كل سطر، وسيتم توزيعه بالتسلسل "
                "على الحسابات التي لم تحصل على اسم من قبل.\n\n"
                "مثال:\n"
                "`محمد`\n"
                "`علي`\n"
                "`حسن`\n\n"
                "كل حساب يحصل على اسم واحد فقط.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 معلومات الحسابات", callback_data="os:account_info")],
                ]),
            )
            return

        # ─── بايو ──────────────────────────────────────────────────────────
        if data == "os:account_bios" and is_own:
            bio_count = _account_bio_count()
            context.user_data["state"] = "os_await_account_bios"
            await q.edit_message_text(
                "📝 *البايو*\n\n"
                f"تم حفظ بايو لـ {bio_count:,} حساباً حتى الآن.\n\n"
                "أرسل بايو واحداً في كل سطر، وسيتم توزيعه بالتسلسل "
                "على الحسابات التي لم تحصل على بايو من قبل.\n\n"
                "مثال:\n"
                "`مبرمج ومطور تطبيقات`\n"
                "`مهندس معماري`\n"
                "`طالب جامعي`\n\n"
                "كل حساب يحصل على بايو واحد فقط.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 معلومات الحسابات", callback_data="os:account_info")],
                ]),
            )
            return

        # ─── يوزر ──────────────────────────────────────────────────────────
        if data == "os:account_usernames" and is_own:
            username_count = _account_username_count()
            context.user_data["state"] = "os_await_account_usernames"
            await q.edit_message_text(
                "🔖 *اليوزرات*\n\n"
                f"تم حفظ يوزر لـ {username_count:,} حساباً حتى الآن.\n\n"
                "أرسل يوزر واحداً في كل سطر (بدون @)، وسيتم توزيعه بالتسلسل "
                "على الحسابات التي لم تحصل على يوزر من قبل.\n\n"
                "مثال:\n"
                "`myusername`\n"
                "`yourusername`\n\n"
                "كل حساب يحصل على يوزر واحد فقط.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 معلومات الحسابات", callback_data="os:account_info")],
                ]),
            )
            return

        if data == "os:make_stories_public" and is_own:
            if context.user_data.get("make_stories_public_running"):
                await q.answer("العملية جارية بالفعل، انتظر التقرير النهائي.", show_alert=True)
                return
        
            with db_conn() as c:
                rows = c.execute(
                    "SELECT phone_number, session_string "
                    "FROM number_stock "
                    "WHERE deleted_at IS NULL "
                    "AND session_string IS NOT NULL "
                    "AND BTRIM(session_string) <> '' "
                    "ORDER BY id"
                ).fetchall()
            accounts = [dict(row) for row in rows]
            context.user_data["make_stories_public_running"] = True
            await q.edit_message_text(
                "🌍 *جعل الستوريات عامة*\n\n"
                f"سيتم فحص *{len(accounts):,}* حساباً، ثم تعديل الستوريات الحالية "
                "والمؤرشفة لتصبح متاحة للجميع.\n\n"
                "بدأت العملية، سيصلك تقرير عند الانتهاء.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⏳ العملية جارية...", callback_data="os:account_info")]
                ]),
            )
            asyncio.create_task(
                _make_all_stories_public_job(
                    context.bot,
                    q.message.chat_id,
                    accounts,
                    context.user_data,
                )
            )
            return

        if data == "os:media_reports" and is_own:
            await q.edit_message_text(
                _media_reports_text(),
                reply_markup=_media_reports_kb(),
            )
            return

        if data.startswith("os:media_report:") and is_own:
            parts = data.split(":")
            if len(parts) not in {4, 5, 6}:
                await q.answer("تقرير غير صالح.", show_alert=True)
                return
            _, _, kind, section, *page_parts = parts
            if kind not in {"stories", "avatar"} or section not in {
                "summary", "history", "run", "success", "failed"
            }:
                await q.answer("تقرير غير صالح.", show_alert=True)
                return
            reports = _load_media_reports(kind)
            if section == "history":
                if len(page_parts) != 1:
                    await q.answer("صفحة غير صالحة.", show_alert=True)
                    return
                try:
                    history_page = int(page_parts[0])
                except ValueError:
                    await q.answer("صفحة غير صالحة.", show_alert=True)
                    return
                text, markup = _media_report_history_page(kind, history_page)
                await q.edit_message_text(text, reply_markup=markup)
                return
        
            report_index = 0
            page = 0
            if section == "summary":
                if page_parts:
                    await q.answer("تقرير غير صالح.", show_alert=True)
                    return
            elif section == "run":
                if len(page_parts) != 1:
                    await q.answer("عملية غير صالحة.", show_alert=True)
                    return
                try:
                    report_index = int(page_parts[0])
                except ValueError:
                    await q.answer("عملية غير صالحة.", show_alert=True)
                    return
            else:
                # التوافق مع أزرار التقارير القديمة: section:page
                if len(page_parts) == 1:
                    try:
                        page = int(page_parts[0])
                    except ValueError:
                        await q.answer("صفحة غير صالحة.", show_alert=True)
                        return
                elif len(page_parts) == 2:
                    try:
                        report_index = int(page_parts[0])
                        page = int(page_parts[1])
                    except ValueError:
                        await q.answer("صفحة غير صالحة.", show_alert=True)
                        return
                else:
                    await q.answer("صفحة غير صالحة.", show_alert=True)
                    return
        
            if section != "summary" and (report_index < 0 or report_index >= len(reports)):
                await q.answer("هذا التقرير غير موجود.", show_alert=True)
                return
            report = reports[report_index] if reports else None
            if section == "summary" or section == "run":
                text, markup = _media_report_summary(
                    kind,
                    report,
                    report_index,
                    len(reports),
                )
            else:
                text, markup = _media_report_page(
                    kind,
                    section,
                    page,
                    report,
                    report_index,
                )
            await q.edit_message_text(text, reply_markup=markup)
            return

        if data == "os:avatars" and is_own:
            _clear_story_upload_state(context)
            accounts = _load_unused_media_accounts("avatar")
            # نخلط طابور الحسابات مرة واحدة عند بدء العملية؛
            # الدفعات التالية تكمل نفس الطابور ولا تعيد أي حساب.
            random.shuffle(accounts)
            context.user_data["state"] = "os_avatar_upload"
            context.user_data["avatar_accounts"] = accounts
            context.user_data["avatar_index"] = 0
            context.user_data["avatar_success"] = []
            context.user_data["avatar_failed"] = []
            _begin_media_report("avatar")
            if not accounts:
                _clear_avatar_upload_state(context)
                await q.edit_message_text(
                    "⚠️ لا توجد حسابات متاحة: كل الحسابات التي لديها جلسة استلمت أفتاراً من قبل.",
                    reply_markup=account_info_kb(),
                )
                return
            await q.edit_message_text(
                "🖼️ *توزيع الأفتارات*\n\n"
                f"وجدت *{len(accounts):,}* حساباً لديه جلسة.\n"
                "أرسل الصور على دفعات، مثلاً ٥٠ صورة معاً.\n"
                "سيتم توزيع كل دفعة على حسابات مختارة عشوائياً، "
                "والدفعة التالية ستكمل من حسابات جديدة بدون تكرار، ولن يُستخدم أي حساب "
                "استلم أفتاراً في عملية سابقة.\n\n"
                "بعد الانتهاء اضغط «إنهاء التوزيع».",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=avatar_upload_kb(),
            )
            return

        if data == "os:stories" and is_own:
            _clear_avatar_upload_state(context)
            accounts = _load_unused_media_accounts("stories")
            random.shuffle(accounts)
            context.user_data["state"] = "os_story_upload"
            context.user_data["story_accounts"] = accounts
            context.user_data["story_index"] = 0
            context.user_data["story_success"] = []
            context.user_data["story_failed"] = []
            _begin_media_report("stories")
            if not accounts:
                _clear_story_upload_state(context)
                await q.edit_message_text(
                    "⚠️ لا توجد حسابات متاحة: كل الحسابات التي لديها جلسة استلمت ستوري من قبل.",
                    reply_markup=account_info_kb(),
                )
                return
            await q.edit_message_text(
                "📖 *نشر الستوريات*\n\n"
                f"وجدت *{len(accounts):,}* حساباً لديه جلسة.\n"
                "أرسل الصور أو الفيديوهات على دفعات، مثلاً ٥٠ وسائط معاً.\n"
                "سيتم نشر كل وسيط كستوري على حساب مختار عشوائياً، "
                "والدفعة التالية ستكمل من حسابات جديدة بدون تكرار، ولن يُستخدم أي حساب "
                "استلم ستوري في عملية سابقة.\n"
                "كل ستوري ستُنشر عامة وليست مؤرشفة أو مقيّدة.\n\n"
                "بعد الانتهاء اضغط «إنهاء النشر».",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=story_upload_kb(),
            )
            return

        if data in {"os:avatar_finish", "os:avatar_cancel"} and is_own:
            if data == "os:avatar_cancel":
                _clear_avatar_upload_state(context)
                await q.edit_message_text(
                    "❌ تم إلغاء توزيع الأفتارات.",
                    reply_markup=owner_settings_kb(),
                )
                return
        
            success = context.user_data.get("avatar_success") or []
            failed = context.user_data.get("avatar_failed") or []
            total = len(context.user_data.get("avatar_accounts") or [])
            _save_media_report("avatar", total, success, failed)
            processed = len(success) + len(failed)
            lines = [
                "📋 تقرير توزيع الأفتارات",
                "",
                f"📦 الحسابات المستهدفة: {total:,}",
                f"🖼️ الصور المعالجة: {processed:,}",
                f"✅ نجح: {len(success):,}",
                f"❌ فشل: {len(failed):,}",
            ]
            if failed:
                lines.extend(["", "تفاصيل الفشل:"])
                lines.extend(f"• {item}" for item in failed[:25])
                if len(failed) > 25:
                    lines.append(f"• ... و{len(failed) - 25:,} حساباً آخر")
            _clear_avatar_upload_state(context)
            await q.edit_message_text(
                "\n".join(lines),
                reply_markup=account_info_kb(),
            )
            return

        if data in {"os:story_finish", "os:story_cancel"} and is_own:
            if data == "os:story_cancel":
                _clear_story_upload_state(context)
                await q.edit_message_text(
                    "❌ تم إلغاء نشر الستوريات.",
                    reply_markup=owner_settings_kb(),
                )
                return
        
            success = context.user_data.get("story_success") or []
            failed = context.user_data.get("story_failed") or []
            total = len(context.user_data.get("story_accounts") or [])
            _save_media_report("stories", total, success, failed)
            processed = len(success) + len(failed)
            lines = [
                "📋 تقرير نشر الستوريات",
                "",
                f"📦 الحسابات المستهدفة: {total:,}",
                f"📖 الستوريات المعالجة: {processed:,}",
                f"✅ نجح: {len(success):,}",
                f"❌ فشل: {len(failed):,}",
            ]
            if failed:
                lines.extend(["", "تفاصيل الفشل:"])
                lines.extend(f"• {item}" for item in failed[:25])
                if len(failed) > 25:
                    lines.append(f"• ... و{len(failed) - 25:,} حساباً آخر")
            _clear_story_upload_state(context)
            await q.edit_message_text(
                "\n".join(lines),
                reply_markup=account_info_kb(),
            )
            return

        if data == "os:manage_buttons" and is_own:
            if context.user_data.get("state", "").startswith("await_mb_"):
                context.user_data["state"] = "main_menu"
                for k in ("mb_menu", "mb_type", "mb_label"):
                    context.user_data.pop(k, None)
            rows = [[InlineKeyboardButton(MENU_LABELS.get(m, m), callback_data=f"mb_menu:{m}")]
                    for m in MANAGEABLE_MENUS]
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
            await q.edit_message_text("🧩 *إدارة الأزرار:*\nاختر القائمة التي تريد التحكم بها:",
                                       parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("mb_menu:") and is_own:
            menu = data.split(":", 1)[1]
            context.user_data.pop("mb_menu", None)
            context.user_data.pop("mb_type", None)
            context.user_data.pop("mb_label", None)
            if context.user_data.get("state", "").startswith("await_mb_"):
                context.user_data["state"] = "main_menu"
            text, kb = render_mb_menu_screen(menu)
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
            return

        if (data.startswith("mb_up:") or data.startswith("mb_down:")) and is_own:
            direction, rest = data.split(":", 1)
            menu, mid = rest.rsplit(":", 1)
            mid = int(mid)
            with db_conn() as c:
                items = c.execute("SELECT id, sort_order FROM menu_items WHERE menu=? ORDER BY sort_order, id", (menu,)).fetchall()
                ids = [r["id"] for r in items]
                idx = ids.index(mid) if mid in ids else -1
                swap_idx = idx - 1 if direction == "mb_up" else idx + 1
                if idx != -1 and 0 <= swap_idx < len(ids):
                    other_id = ids[swap_idx]
                    orders = {r["id"]: r["sort_order"] for r in items}
                    c.execute("UPDATE menu_items SET sort_order=? WHERE id=? AND menu=?", (orders[other_id], mid, menu))
                    c.execute("UPDATE menu_items SET sort_order=? WHERE id=? AND menu=?", (orders[mid], other_id, menu))
            text, kb = render_mb_menu_screen(menu)
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
            return

        if data.startswith("mb_width:") and is_own:
            _, rest = data.split(":", 1)
            menu, mid = rest.rsplit(":", 1)
            mid = int(mid)
            with db_conn() as c:
                row = c.execute("SELECT width FROM menu_items WHERE id=? AND menu=?", (mid, menu)).fetchone()
                if row:
                    new_width = 1 if row["width"] == 2 else 2
                    c.execute("UPDATE menu_items SET width=? WHERE id=? AND menu=?", (new_width, mid, menu))
            await q.answer("✅ تم تغيير الحجم")
            text, kb = render_mb_menu_screen(menu)
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
            return

        if data.startswith("mb_toggle:") and is_own:
            _, rest = data.split(":", 1)
            menu, mid = rest.rsplit(":", 1)
            mid = int(mid)
            with db_conn() as c:
                row = c.execute("SELECT enabled FROM menu_items WHERE id=? AND menu=?", (mid, menu)).fetchone()
                if row:
                    new_enabled = 0 if row["enabled"] else 1
                    c.execute("UPDATE menu_items SET enabled=? WHERE id=? AND menu=?", (new_enabled, mid, menu))
            await q.answer("✅ تم التحديث")
            text, kb = render_mb_menu_screen(menu)
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
            return

        if data.startswith("mb_add:") and is_own:
            menu = data.split(":", 1)[1]
            context.user_data["mb_menu"] = menu
            rows = [
                [InlineKeyboardButton("🔗 رابط خارجي", callback_data="mb_type:url")],
                [InlineKeyboardButton("💬 نص يظهر عند الضغط", callback_data="mb_type:text")],
                [InlineKeyboardButton("↪️ ربط بقسم موجود بالبوت", callback_data="mb_type:goto")],
                [InlineKeyboardButton("👤 تواصل مع المالك (يفتح حسابك الشخصي)", callback_data="mb_type:owner")],
                [InlineKeyboardButton("🔙 رجوع", callback_data=f"mb_menu:{menu}")],
            ]
            await q.edit_message_text("اختر نوع الزر الجديد:", reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("mb_type:") and is_own:
            mb_type = data.split(":", 1)[1]
            context.user_data["mb_type"] = mb_type
            context.user_data["state"] = "await_mb_label"
            await q.edit_message_text("✏️ أرسل *اسم الزر* الذي سيظهر للمستخدمين:", parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("mb_goto_pick:") and is_own:
            target = data.split(":", 1)[1]
            menu = context.user_data.get("mb_menu")
            label = context.user_data.get("mb_label")
            if not (menu and label):
                await q.edit_message_text("⚠️ انتهت الجلسة، ابدأ من جديد.", reply_markup=owner_settings_kb())
                return
            with db_conn() as c:
                max_order = c.execute("SELECT COALESCE(MAX(sort_order),-1) AS m FROM menu_items WHERE menu=?", (menu,)).fetchone()["m"]
                c.execute(
                    "INSERT INTO menu_items (menu,label,action_type,action_value,width,sort_order,enabled) VALUES (?,?,?,?,?,?,1)",
                    (menu, label, "goto", target, 2, max_order + 1)
                )
            context.user_data["state"] = "main_menu"
            await q.edit_message_text(f"✅ تمت إضافة الزر '{label}'.",
                                       reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للإدارة", callback_data=f"mb_menu:{menu}")]]))
            return

        if data == "os:add_service" and is_own:
            plat_rows = [[InlineKeyboardButton(lbl, callback_data=f"os_plat:{PLATFORM_MENU_MAP[val]}")] for lbl, val in SERVICE_PLATFORMS]
            plat_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
            await q.edit_message_text(
                "➕ *إضافة خدمة جديدة*\n\nالخطوة 1/3 — اختر *المنصة* التي تريد إضافة الخدمة لها:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(plat_rows)
            )
            return

        if data.startswith("os_plat:") and is_own:
            platform = data.split(":")[1]
            context.user_data["new_svc_platform"] = platform
            plat_label = PLATFORM_LABEL_MAP.get(platform, platform)
            cats = list(CATEGORY_MAP.items())
            rows = [[InlineKeyboardButton(v, callback_data=f"os_cat:{k}")] for k, v in cats]
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:add_service")])
            await q.edit_message_text(
                f"➕ *إضافة خدمة — {plat_label}*\n\nالخطوة 2/3 — اختر *الفئة:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data.startswith("os_cat:") and is_own:
            cat = data.split(":")[1]
            context.user_data["new_svc_cat"] = cat
            platform = context.user_data.get("new_svc_platform", "tg")
            plat_label = PLATFORM_LABEL_MAP.get(platform, platform)
            panel_emojis = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣"}
            panel_rows = [
                [InlineKeyboardButton(f"{panel_emojis.get(pid,'➡️')} {pinfo['name']}", callback_data=f"os_panel:{pid}")]
                for pid, pinfo in PANEL_MAP.items() if pinfo["key"]
            ]
            panel_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"os_plat:{platform}")])
            await q.edit_message_text(
                f"📌 المنصة: {plat_label} | الفئة: {CATEGORY_MAP.get(cat, cat)}\n\nالخطوة 3/3 — اختر *الموقع:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(panel_rows)
            )
            return

        if data.startswith("os_panel:") and is_own:
            panel = int(data.split(":")[1])
            context.user_data["new_svc_panel"] = panel
            context.user_data["state"] = "os_await_api_id"
            site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
            await q.edit_message_text(
                f"🌐 الموقع: {site_name}\n\nأرسل *رقم الخدمة* في هذا الموقع:",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data.startswith("os_use_min:") and is_own:
            mn = int(data.split(":")[1])
            context.user_data["new_svc_min"] = mn
            info = context.user_data.get("new_svc_info", {})
            mx   = info.get("max", 0)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✅ استخدم ({mx})", callback_data=f"os_use_max:{mx}")]
            ])
            await q.edit_message_text(
                f"✅ الحد الأدنى: {mn}\n\n"
                f"📈 *الحد الأعلى من الموقع: {mx}*\n\nاضغط الزر لاستخدامه أو أرسل رقماً مختلفاً:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
            context.user_data["state"] = "os_await_max"
            return

        if data.startswith("os_use_max:") and is_own:
            mx = int(data.split(":")[1])
            context.user_data["new_svc_max"] = mx
            info = context.user_data.get("new_svc_info", {})
            rate = float(info.get("rate", 0))
            suggested = round(rate * 100000, 1)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✅ استخدم ({suggested} نقطة/1000 وحدة)", callback_data=f"os_use_price:{suggested}")]
            ])
            await q.edit_message_text(
                f"✅ الحد الأعلى: {mx}\n\n"
                f"💰 *السعر المقترح: {suggested} نقطة/1000 وحدة*\n"
                f"_(محسوب: {rate}$ × 100)_\n\n"
                f"اضغط الزر لاستخدامه أو أرسل رقماً مختلفاً:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
            context.user_data["state"] = "os_await_price"
            return

        if data.startswith("os_use_price:") and is_own:
            price    = float(data.split(":")[1])
            context.user_data["state"] = "main_menu"
            cat      = context.user_data.get("new_svc_cat", "followers")
            api_id   = context.user_data.get("new_svc_api_id")
            panel    = context.user_data.get("new_svc_panel", 1)
            platform = context.user_data.get("new_svc_platform", "tg")
            name     = context.user_data.get("new_svc_name")
            mn       = context.user_data.get("new_svc_min", 0)
            mx_val   = context.user_data.get("new_svc_max", 0)
            desc     = context.user_data.get("new_svc_desc", "")
            with db_conn() as c:
                c.execute(
                    "INSERT INTO services (category,api_service_id,panel,platform,name_ar,description,min_qty,max_qty,price_per_point) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (cat, api_id, panel, platform, name, desc, mn, mx_val, price)
                )
            site_name  = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
            plat_label = PLATFORM_LABEL_MAP.get(platform, platform)
            await q.edit_message_text(
                f"✅ تمت إضافة الخدمة *'{name}'* بنجاح!\n\n"
                f"📱 المنصة: {plat_label}\n"
                f"🌐 الموقع: {site_name}\n"
                f"📉 الحد الأدنى: {mn}\n"
                f"📈 الحد الأعلى: {mx_val}\n"
                f"💰 السعر: {fmt_price(price)} نقطة/1000 وحدة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=owner_settings_kb()
            )
            return

        if data == "os:view_services" and is_own:
            rows = []
            for lbl, val in SERVICE_PLATFORMS:
                plat_code = PLATFORM_MENU_MAP[val]
                with db_conn() as c:
                    cnt = c.execute("SELECT COUNT(*) AS n FROM services WHERE platform=%s", (plat_code,)).fetchone()
                n = cnt["n"] if cnt else 0
                rows.append([InlineKeyboardButton(f"{lbl} ({n})", callback_data=f"os_view_plat:{plat_code}")])
            with db_conn() as c:
                total = c.execute("SELECT COUNT(*) AS n FROM services").fetchone()
            rows.append([InlineKeyboardButton(f"📂 جميع المنصات ({total['n'] if total else 0})", callback_data="os_view_plat:ALL")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
            await q.edit_message_text(
                "🗂 *عرض الخدمات — اختر المنصة:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "os:inspect_services" and is_own:
            await q.answer("⏳ جارٍ فحص الخدمات من المواقع مباشرة...")
            await send_services_inspection(update, context)
            return

        if data.startswith("os_view_plat:") and is_own:
            platform = data.split(":", 1)[1]   # "tg" / "ig" / ... / "ALL"
            rows = []
            for cat_key, cat_name in CATEGORY_MAP.items():
                with db_conn() as c:
                    if platform == "ALL":
                        cnt = c.execute("SELECT COUNT(*) AS n FROM services WHERE category=%s", (cat_key,)).fetchone()
                    else:
                        cnt = c.execute("SELECT COUNT(*) AS n FROM services WHERE category=%s AND platform=%s", (cat_key, platform)).fetchone()
                n = cnt["n"] if cnt else 0
                if n == 0:
                    continue
                rows.append([InlineKeyboardButton(f"{cat_name} ({n})", callback_data=f"os_view_cat:{platform}:{cat_key}")])
            rows.append([InlineKeyboardButton("📂 عرض الجميع", callback_data=f"os_view_cat:{platform}:ALL")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:view_services")])
            plat_label = "جميع المنصات" if platform == "ALL" else PLATFORM_LABEL_MAP.get(platform, platform)
            await q.edit_message_text(
                f"🗂 *عرض الخدمات — {plat_label}*\nاختر الفئة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data.startswith("os_view_cat:") and is_own:
            rest = data[len("os_view_cat:"):]
            if ":" in rest:
                platform, cat_filter = rest.split(":", 1)
            else:
                platform, cat_filter = "ALL", rest
            if cat_filter == "ALL":
                cats_to_show = list(CATEGORY_MAP.items())
            else:
                cats_to_show = [(cat_filter, CATEGORY_MAP.get(cat_filter, cat_filter))]
            sent_any = False
            first = True
            for cat_key, cat_name in cats_to_show:
                with db_conn() as c:
                    if platform == "ALL":
                        svcs = c.execute("SELECT * FROM services WHERE category=%s ORDER BY platform, id", (cat_key,)).fetchall()
                    else:
                        svcs = c.execute("SELECT * FROM services WHERE category=%s AND platform=%s ORDER BY id", (cat_key, platform)).fetchall()
                if not svcs:
                    continue
                sent_any = True
                for s in svcs:
                    status     = "✅ مفعّلة" if s["active"] else "❌ معطّلة"
                    site_name  = PANEL_MAP.get(s["panel"] or 1, PANEL_MAP[1])["name"]
                    plat_label = PLATFORM_LABEL_MAP.get(s.get("platform") or "tg", "📱 تيلجرام")
                    svc_text = (
                        f"📂 *{cat_name}*\n"
                        f"🔹 *{s['name_ar']}*\n\n"
                        f"🟢 الحالة: {status}\n"
                        f"📱 المنصة: {plat_label}\n"
                        f"🌐 الموقع: {site_name} (رقم: {s['api_service_id']})\n"
                        f"📝 الوصف: {s['description'] or '—'}\n"
                        f"📉 الحد الأدنى: {s['min_qty']:,}\n"
                        f"📈 الحد الأعلى: {s['max_qty']:,}\n"
                        f"💰 السعر: {fmt_price(s['price_per_point'])} نقطة / 1000 وحدة\n"
                    )
                    tog = "❌ تعطيل" if s["active"] else "✅ تفعيل"
                    back_cb = f"os_view_plat:{platform}"
                    svc_kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("✏️ تعديل", callback_data=f"os_edit_svc:{s['id']}"),
                         InlineKeyboardButton(tog, callback_data=f"os_tog_svc:{s['id']}:{0 if s['active'] else 1}"),
                         InlineKeyboardButton("🗑 حذف", callback_data=f"os_del_svc:{s['id']}")],
                        [InlineKeyboardButton("📤 نقل الخدمة", callback_data=f"os:move_svc:{s['id']}")],
                    ])
                    if first and update.callback_query:
                        await q.edit_message_text(svc_text, parse_mode=ParseMode.MARKDOWN, reply_markup=svc_kb)
                        first = False
                    else:
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=svc_text,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=svc_kb
                        )
            if not sent_any:
                cat_name   = "الجميع" if cat_filter == "ALL" else CATEGORY_MAP.get(cat_filter, cat_filter)
                plat_label = "جميع المنصات" if platform == "ALL" else PLATFORM_LABEL_MAP.get(platform, platform)
                msg = f"📋 لا توجد خدمات في فئة ({cat_name}) للمنصة ({plat_label})."
                if first and update.callback_query:
                    await q.edit_message_text(msg, reply_markup=owner_settings_kb())
                else:
                    await context.bot.send_message(update.effective_chat.id, msg)
            else:
                back_cb = f"os_view_plat:{platform}"
                await context.bot.send_message(
                    update.effective_chat.id,
                    "⬆️ هذه جميع الخدمات المطلوبة.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للعرض", callback_data=back_cb),
                                                        InlineKeyboardButton("⚙️ الإعدادات", callback_data="owner_settings")]])
                )
            return

        if data == "os:orders_section" and is_own:
            await show_orders_section(update, context, offset=0)
            return

        if data.startswith("os:orders_page:") and is_own:
            offset = int(data.split(":")[2])
            await show_orders_section(update, context, offset=offset)
            return

        if data == "os:order_lookup" and is_own:
            context.user_data["state"] = "os_await_order_lookup"
            await q.edit_message_text("🔍 أرسل كود الطلب الذي تريد عرض تفاصيله:")
            return

        if data == "os:new_services" and is_own:
            context.user_data.pop("ns_move_ids", None)
            text, rows = _render_staging_services()
            await q.edit_message_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "os:ns_add" and is_own:
            panel_rows = [
                [InlineKeyboardButton(f"{pinfo['name']}", callback_data=f"os:ns_panel:{pid}")]
                for pid, pinfo in PANEL_MAP.items() if pinfo["key"]
            ]
            panel_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:new_services")])
            await q.edit_message_text(
                "➕ *إضافة خدمة جديدة*\n\nاختر *الموقع* (المنصة التقنية للخدمة):",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(panel_rows)
            )
            return

        if data.startswith("os:ns_panel:") and is_own:
            panel = int(data.split(":")[2])
            context.user_data["ns_panel"] = panel
            context.user_data["state"] = "ns_await_api_id"
            site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
            await q.edit_message_text(
                f"🌐 الموقع: *{site_name}*\n\nأرسل *رقم الخدمة* في هذا الموقع:",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data.startswith("os:ns_use_min:") and is_own:
            mn = int(data.split(":")[2])
            context.user_data["ns_min"] = mn
            info = context.user_data.get("ns_info", {})
            mx = info.get("max", 0)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ استخدم ({mx})", callback_data=f"os:ns_use_max:{mx}")]])
            await q.edit_message_text(
                f"✅ الحد الأدنى: {mn}\n\n📈 *الحد الأعلى من الموقع: {mx}*\n\nاضغط أو أرسل رقماً مختلفاً:",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb
            )
            context.user_data["state"] = "ns_await_max"
            return

        if data.startswith("os:ns_use_max:") and is_own:
            mx = int(data.split(":")[2])
            context.user_data["ns_max"] = mx
            info = context.user_data.get("ns_info", {})
            rate = float(info.get("rate", 0))
            suggested = round(rate * 100000, 1)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ استخدم ({suggested} نقطة/1000)", callback_data=f"os:ns_use_price:{suggested}")]])
            await q.edit_message_text(
                f"✅ الحد الأعلى: {mx}\n\n💰 *السعر المقترح: {suggested} نقطة/1000 وحدة*\n\nاضغط أو أرسل رقماً مختلفاً:",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb
            )
            context.user_data["state"] = "ns_await_price"
            return

        if data.startswith("os:ns_use_price:") and is_own:
            price = float(data.split(":")[2])
            name    = context.user_data.get("ns_name", "")
            panel   = context.user_data.get("ns_panel", 1)
            api_id  = context.user_data.get("ns_api_id")
            mn      = context.user_data.get("ns_min", 0)
            mx      = context.user_data.get("ns_max", 0)
            desc    = context.user_data.get("ns_desc", "")
            with db_conn() as c:
                c.execute(
                    "INSERT INTO staging_services (name_ar,api_service_id,panel,min_qty,max_qty,price_per_point,description) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (name, api_id, panel, mn, mx, price, desc)
                )
            context.user_data["state"] = "main_menu"
            await q.edit_message_text(
                f"✅ تمت إضافة *'{name}'* إلى الخدمات الجديدة!\n\nيمكنك نقلها لأي قسم متى تريد.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 الخدمات الجديدة", callback_data="os:new_services"),
                                                    InlineKeyboardButton("⚙️ الإعدادات", callback_data="owner_settings")]])
            )
            return

        if data.startswith("os:ns_view:") and is_own:
            sid = int(data.split(":")[2])
            with db_conn() as c:
                s = c.execute("SELECT * FROM staging_services WHERE id=%s", (sid,)).fetchone()
            if not s:
                await q.answer("❌ الخدمة غير موجودة.", show_alert=True)
                return
            panel_name = PANEL_MAP.get(s["panel"] or 1, PANEL_MAP[1])["name"]
            text = (
                f"📦 *خدمة في المرحلة الجديدة*\n\n"
                f"🔹 الاسم: *{s['name_ar']}*\n"
                f"🌐 الموقع: {panel_name}\n"
                f"🔢 رقم الخدمة: {s['api_service_id']}\n"
                f"📉 الحد الأدنى: {s['min_qty']:,}\n"
                f"📈 الحد الأعلى: {s['max_qty']:,}\n"
                f"💰 السعر: {fmt_price(s['price_per_point'])} نقطة/1000\n"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 نقل الخدمة", callback_data=f"os:ns_transfer:{sid}")],
                [InlineKeyboardButton("🗑 حذف", callback_data=f"os:ns_del:{sid}"),
                 InlineKeyboardButton("🔙 رجوع", callback_data="os:new_services")],
            ])
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
            return

        if data.startswith("os:ns_del:") and is_own:
            sid = int(data.split(":")[2])
            with db_conn() as c:
                c.execute("DELETE FROM staging_services WHERE id=%s", (sid,))
            await q.answer("✅ تم حذف الخدمة.")
            context.user_data.pop("ns_move_ids", None)
            text, rows = _render_staging_services()
            await q.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "os:ns_move_mode" and is_own:
            text, rows = _render_staging_services(context.user_data.get("ns_move_ids"))
            await q.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data.startswith("os:ns_toggle:") and is_own:
            sid = int(data.split(":")[2])
            with db_conn() as c:
                exists = c.execute("SELECT id FROM staging_services WHERE id=%s", (sid,)).fetchone()
            if not exists:
                await q.answer("❌ الخدمة غير موجودة.", show_alert=True)
                return
            selected = {int(item) for item in context.user_data.get("ns_move_ids", [])}
            if sid in selected:
                selected.remove(sid)
            else:
                selected.add(sid)
            context.user_data["ns_move_ids"] = sorted(selected)
            text, rows = _render_staging_services(selected)
            await q.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "os:ns_select_all" and is_own:
            with db_conn() as c:
                staged = c.execute("SELECT id FROM staging_services").fetchall()
            selected = [int(row["id"]) for row in staged]
            context.user_data["ns_move_ids"] = selected
            text, rows = _render_staging_services(selected)
            await q.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "os:ns_clear_selection" and is_own:
            context.user_data["ns_move_ids"] = []
            text, rows = _render_staging_services()
            await q.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "os:ns_move_start" and is_own:
            selected = sorted({
                int(item) for item in context.user_data.get("ns_move_ids", [])
            })
            if not selected:
                await q.answer("حدد خدمة واحدة على الأقل أولاً", show_alert=True)
                return
            context.user_data["ns_move_ids"] = selected
            panel_rows = [
                [InlineKeyboardButton(
                    label,
                    callback_data=f"os:ns_move_plat:{PLATFORM_MENU_MAP[value]}"
                )]
                for label, value in SERVICE_PLATFORMS
            ]
            panel_rows.append([
                InlineKeyboardButton("🔙 رجوع للتحديد", callback_data="os:ns_move_mode")
            ])
            await q.edit_message_text(
                f"📤 تم تحديد {len(selected)} خدمة.\n\nاختر *المنصة* التي تريد نقلها إليها:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(panel_rows)
            )
            return

        if data.startswith("os:ns_move_plat:") and is_own:
            platform = data.split(":")[2]
            selected = sorted({
                int(item) for item in context.user_data.get("ns_move_ids", [])
            })
            if not selected:
                await q.answer("انتهى التحديد، اختر الخدمات من جديد", show_alert=True)
                text, rows = _render_staging_services()
                await q.edit_message_text(
                    text, parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(rows)
                )
                return
            category_rows = [
                [InlineKeyboardButton(
                    label,
                    callback_data=f"os:ns_move_cat:{platform}:{category}"
                )]
                for category, label in CATEGORY_MAP.items()
            ]
            category_rows.append([
                InlineKeyboardButton("🔙 رجوع لاختيار المنصة", callback_data="os:ns_move_start")
            ])
            platform_label = PLATFORM_LABEL_MAP.get(platform, platform)
            await q.edit_message_text(
                f"📤 تم اختيار {len(selected)} خدمة.\n"
                f"المنصة: *{platform_label}*\n\nاختر *الفئة* الجديدة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(category_rows)
            )
            return

        if data.startswith("os:ns_move_cat:") and is_own:
            parts = data.split(":")
            platform = parts[2]
            category = parts[3]
            selected = sorted({
                int(item) for item in context.user_data.get("ns_move_ids", [])
            })
            if not selected:
                await q.answer("انتهى التحديد، اختر الخدمات من جديد", show_alert=True)
                text, rows = _render_staging_services()
                await q.edit_message_text(
                    text, parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(rows)
                )
                return
            placeholders = ",".join(["%s"] * len(selected))
            with db_conn() as c:
                staged = c.execute(
                    f"SELECT * FROM staging_services WHERE id IN ({placeholders}) ORDER BY id",
                    tuple(selected)
                ).fetchall()
                for service in staged:
                    c.execute(
                        "INSERT INTO services (category,api_service_id,panel,platform,name_ar,description,min_qty,max_qty,price_per_point) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            category, service["api_service_id"], service["panel"] or 1,
                            platform, service["name_ar"], service["description"] or "",
                            service["min_qty"], service["max_qty"], service["price_per_point"]
                        )
                    )
                c.execute(
                    f"DELETE FROM staging_services WHERE id IN ({placeholders})",
                    tuple(selected)
                )
            moved_count = len(staged)
            context.user_data.pop("ns_move_ids", None)
            platform_label = PLATFORM_LABEL_MAP.get(platform, platform)
            category_label = CATEGORY_MAP.get(category, category)
            text, rows = _render_staging_services()
            await q.edit_message_text(
                f"✅ تم نقل *{moved_count} خدمة* بنجاح.\n"
                f"📱 المنصة: {platform_label}\n"
                f"📂 الفئة: {category_label}\n\n{text}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data.startswith("os:ns_transfer:") and is_own:
            sid = int(data.split(":")[2])
            context.user_data["ns_transfer_id"] = sid
            plat_rows = [[InlineKeyboardButton(lbl, callback_data=f"os:ns_tr_plat:{sid}:{PLATFORM_MENU_MAP[val]}")] for lbl, val in SERVICE_PLATFORMS]
            plat_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"os:ns_view:{sid}")])
            await q.edit_message_text(
                "📤 *نقل الخدمة*\n\nاختر *المنصة* التي تريد نقل الخدمة إليها:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(plat_rows)
            )
            return

        if data.startswith("os:ns_tr_plat:") and is_own:
            parts = data.split(":")
            sid   = int(parts[2])
            plat  = parts[3]
            cats  = list(CATEGORY_MAP.items())
            rows  = [[InlineKeyboardButton(v, callback_data=f"os:ns_tr_cat:{sid}:{plat}:{k}")] for k, v in cats]
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"os:ns_transfer:{sid}")])
            plat_lbl = PLATFORM_LABEL_MAP.get(plat, plat)
            await q.edit_message_text(
                f"📤 *نقل الخدمة — {plat_lbl}*\n\nاختر *الفئة:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data.startswith("os:ns_tr_cat:") and is_own:
            parts = data.split(":")
            sid   = int(parts[2])
            plat  = parts[3]
            cat   = parts[4]
            with db_conn() as c:
                s = c.execute("SELECT * FROM staging_services WHERE id=%s", (sid,)).fetchone()
            if not s:
                await q.answer("❌ الخدمة غير موجودة.", show_alert=True)
                return
            with db_conn() as c:
                c.execute(
                    "INSERT INTO services (category,api_service_id,panel,platform,name_ar,description,min_qty,max_qty,price_per_point) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (cat, s["api_service_id"], s["panel"], plat, s["name_ar"], s["description"] or "", s["min_qty"], s["max_qty"], s["price_per_point"])
                )
                c.execute("DELETE FROM staging_services WHERE id=%s", (sid,))
            plat_lbl = PLATFORM_LABEL_MAP.get(plat, plat)
            cat_lbl  = CATEGORY_MAP.get(cat, cat)
            await q.edit_message_text(
                f"✅ تم نقل *'{s['name_ar']}'* إلى:\n📱 {plat_lbl} ← {cat_lbl}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📦 الخدمات الجديدة", callback_data="os:new_services"),
                     InlineKeyboardButton("⚙️ الإعدادات", callback_data="owner_settings")]
                ])
            )
            return

        if data.startswith("os:move_svc:") and is_own:
            sid = int(data.split(":")[2])
            context.user_data["move_svc_id"] = sid
            plat_rows = [[InlineKeyboardButton(lbl, callback_data=f"os:mv_plat:{sid}:{PLATFORM_MENU_MAP[val]}")] for lbl, val in SERVICE_PLATFORMS]
            plat_rows.append([InlineKeyboardButton("📦 الخدمات الجديدة (تجميد)", callback_data=f"os:mv_staging:{sid}")])
            plat_rows.append([InlineKeyboardButton("🔙 إلغاء", callback_data="os:view_services")])
            await q.edit_message_text(
                "📤 *نقل الخدمة*\n\nاختر *المنصة الجديدة:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(plat_rows)
            )
            return

        if data.startswith("os:mv_plat:") and is_own:
            parts = data.split(":")
            sid   = int(parts[2])
            plat  = parts[3]
            cats  = list(CATEGORY_MAP.items())
            rows  = [[InlineKeyboardButton(v, callback_data=f"os:mv_cat:{sid}:{plat}:{k}")] for k, v in cats]
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"os:move_svc:{sid}")])
            plat_lbl = PLATFORM_LABEL_MAP.get(plat, plat)
            await q.edit_message_text(
                f"📤 *نقل إلى — {plat_lbl}*\n\nاختر *الفئة:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data.startswith("os:mv_cat:") and is_own:
            parts = data.split(":")
            sid   = int(parts[2])
            plat  = parts[3]
            cat   = parts[4]
            with db_conn() as c:
                s = c.execute("SELECT name_ar FROM services WHERE id=%s", (sid,)).fetchone()
                c.execute("UPDATE services SET platform=%s, category=%s WHERE id=%s", (plat, cat, sid))
            name = s["name_ar"] if s else f"#{sid}"
            plat_lbl = PLATFORM_LABEL_MAP.get(plat, plat)
            cat_lbl  = CATEGORY_MAP.get(cat, cat)
            await q.edit_message_text(
                f"✅ تم نقل *'{name}'* إلى:\n📱 {plat_lbl} ← {cat_lbl}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ الإعدادات", callback_data="owner_settings")]])
            )
            return

        if data.startswith("os:mv_staging:") and is_own:
            sid = int(data.split(":")[2])
            with db_conn() as c:
                s = c.execute("SELECT * FROM services WHERE id=%s", (sid,)).fetchone()
            if not s:
                await q.answer("❌ الخدمة غير موجودة.", show_alert=True)
                return
            with db_conn() as c:
                c.execute(
                    "INSERT INTO staging_services (name_ar,api_service_id,panel,min_qty,max_qty,price_per_point,description) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (s["name_ar"], s["api_service_id"], s["panel"] or 1, s["min_qty"], s["max_qty"], s["price_per_point"], s["description"] or "")
                )
                c.execute("DELETE FROM services WHERE id=%s", (sid,))
            await q.edit_message_text(
                f"✅ تم تجميد *'{s['name_ar']}'* في قسم الخدمات الجديدة.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📦 الخدمات الجديدة", callback_data="os:new_services"),
                     InlineKeyboardButton("⚙️ الإعدادات", callback_data="owner_settings")]
                ])
            )
            return

        if data == "os:list_services" and is_own:
            text_, rows = _render_service_list()
            if rows is None:
                await q.edit_message_text(text_, reply_markup=owner_settings_kb())
                return
            await q.edit_message_text(text_, parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=InlineKeyboardMarkup(rows))
            return

        if data == "os:share_description" and is_own:
            context.user_data["state"] = "os_await_shared_description"
            await q.edit_message_text(
                "📝 *تعديل وصف عدة خدمات*\n\n"
                "اكتب الوصف الذي تريد تطبيقه على عدة خدمات.\n"
                "أرسل `-` إذا كنت تريد حذف الوصف من الخدمات المحددة.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ إلغاء", callback_data="os:list_services")]
                ])
            )
            return

        if data.startswith("os:desc_toggle:") and is_own:
            sid = int(data.split(":")[2])
            with db_conn() as c:
                exists = c.execute("SELECT id FROM services WHERE id=%s", (sid,)).fetchone()
            if not exists:
                await q.answer("⚠️ الخدمة غير موجودة", show_alert=True)
                return
            selected = {int(item) for item in context.user_data.get("shared_desc_ids", [])}
            if sid in selected:
                selected.remove(sid)
            else:
                selected.add(sid)
            context.user_data["shared_desc_ids"] = sorted(selected)
            text, rows = _render_description_service_selection(selected)
            await q.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "os:desc_select_all" and is_own:
            with db_conn() as c:
                services = c.execute("SELECT id FROM services ORDER BY id").fetchall()
            selected = [int(service["id"]) for service in services]
            context.user_data["shared_desc_ids"] = selected
            text, rows = _render_description_service_selection(selected)
            await q.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "os:desc_clear" and is_own:
            context.user_data["shared_desc_ids"] = []
            text, rows = _render_description_service_selection()
            await q.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "os:desc_apply" and is_own:
            has_description = "shared_description" in context.user_data
            description = context.user_data.get("shared_description")
            selected = sorted({
                int(item) for item in context.user_data.get("shared_desc_ids", [])
            })
            if not has_description:
                await q.answer("اكتب الوصف أولاً", show_alert=True)
                return
            if not selected:
                await q.answer("حدد خدمة واحدة على الأقل", show_alert=True)
                return
        
            placeholders = ",".join(["%s"] * len(selected))
            with db_conn() as c:
                c.execute(
                    f"UPDATE services SET description=%s WHERE id IN ({placeholders})",
                    tuple([description, *selected])
                )
            applied_count = len(selected)
            context.user_data.pop("shared_description", None)
            context.user_data.pop("shared_desc_ids", None)
            context.user_data["state"] = "main_menu"
            text_, rows = _render_service_list()
            await q.edit_message_text(
                f"✅ تم تطبيق الوصف على {applied_count} خدمة.\n\n{text_}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows) if rows else owner_settings_kb()
            )
            return

        if data.startswith("os_tog_svc:") and is_own:
            _, sid, val = data.split(":")
            with db_conn() as c:
                c.execute("UPDATE services SET active=? WHERE id=?", (int(val), int(sid)))
            await q.answer("✅ تم التحديث")
            text_, rows = _render_service_list()
            if rows is None:
                await q.edit_message_text(text_, reply_markup=owner_settings_kb())
                return
            await q.edit_message_text(text_, parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("os_edit_svc:") and is_own:
            sid = int(data.split(":")[1])
            with db_conn() as c:
                svc = c.execute("SELECT * FROM services WHERE id=?", (sid,)).fetchone()
            if not svc:
                await q.answer("⚠️ الخدمة غير موجودة")
                return
            site_name = PANEL_MAP.get(svc["panel"] or 1, PANEL_MAP[1])["name"]
            rows = [
                [InlineKeyboardButton("✏️ الاسم", callback_data=f"os_edit_field:{sid}:name"),
                 InlineKeyboardButton("📉 الحد الأدنى", callback_data=f"os_edit_field:{sid}:min")],
                [InlineKeyboardButton("📈 الحد الأعلى", callback_data=f"os_edit_field:{sid}:max"),
                 InlineKeyboardButton("💰 السعر", callback_data=f"os_edit_field:{sid}:price")],
                [InlineKeyboardButton("📝 الوصف", callback_data=f"os_edit_field:{sid}:desc")],
                [InlineKeyboardButton("🌐 الموقع ورقم الخدمة", callback_data=f"os_edit_field:{sid}:source")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="os:list_services")],
            ]
            await q.edit_message_text(
                f"✏️ *تعديل الخدمة:* {svc['name_ar']}\n\n"
                f"🌐 الموقع الحالي: {site_name} (رقم {svc['api_service_id']})\n"
                f"📉 الحد الأدنى: {svc['min_qty']}\n"
                f"📈 الحد الأعلى: {svc['max_qty']}\n"
                f"💰 السعر: {fmt_price(svc['price_per_point'])} نقطة/1000\n"
                f"📝 الوصف: {svc['description'] or '—'}\n\n"
                f"اختر ما تريد تعديله:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data.startswith("os_edit_field:") and is_own:
            _, sid, field = data.split(":")
            context.user_data["edit_svc_id"] = int(sid)
            prompts = {
                "name":  ("✏️ أرسل *الاسم الجديد بالعربية* للخدمة:", "os_edit_await_name"),
                "min":   ("📉 أرسل *الحد الأدنى* الجديد:", "os_edit_await_min"),
                "max":   ("📈 أرسل *الحد الأعلى* الجديد:", "os_edit_await_max"),
                "price": ("💰 أرسل *السعر* الجديد (نقطة/1000 وحدة):", "os_edit_await_price"),
                "desc":  ("📝 أرسل *الوصف الجديد* للخدمة (أو أرسل `-` لحذف الوصف):", "os_edit_await_desc"),
            }
            if field == "source":
                rows = [
                    [InlineKeyboardButton(f"1️⃣ {PANEL_MAP[1]['name']}", callback_data=f"os_edit_panel:{sid}:1")],
                    [InlineKeyboardButton(f"2️⃣ {PANEL_MAP[2]['name']}", callback_data=f"os_edit_panel:{sid}:2")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"os_edit_svc:{sid}")],
                ]
                await q.edit_message_text(
                    "🌐 اختر *الموقع الجديد* الذي تريد ربط الخدمة به:",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(rows)
                )
                return
            msg, state_name = prompts[field]
            context.user_data["state"] = state_name
            await q.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("os_edit_panel:") and is_own:
            _, sid, panel = data.split(":")
            context.user_data["edit_svc_id"] = int(sid)
            context.user_data["edit_svc_panel"] = int(panel)
            context.user_data["state"] = "os_edit_await_apiid"
            site_name = PANEL_MAP.get(int(panel), PANEL_MAP[1])["name"]
            await q.edit_message_text(
                f"🌐 الموقع: {site_name}\n\nأرسل *رقم الخدمة الجديد* في هذا الموقع:",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data.startswith("os_del_svc:") and is_own:
            sid = int(data.split(":")[1])
            with db_conn() as c:
                svc = c.execute("SELECT * FROM services WHERE id=?", (sid,)).fetchone()
            if not svc:
                await q.answer("⚠️ الخدمة غير موجودة")
                return
            await q.edit_message_text(
                f"🗑 *تأكيد الحذف:*\n\n"
                f"هل أنت متأكد من حذف الخدمة:\n"
                f"*{svc['name_ar']}*؟\n\n"
                f"⚠️ لا يمكن التراجع عن هذا الإجراء!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ نعم، احذف", callback_data=f"os_confirm_del:{sid}"),
                     InlineKeyboardButton("❌ إلغاء", callback_data="os:list_services")]
                ])
            )
            return

        if data.startswith("os_confirm_del:") and is_own:
            sid = int(data.split(":")[1])
            with db_conn() as c:
                svc = c.execute("SELECT name_ar FROM services WHERE id=?", (sid,)).fetchone()
                c.execute("DELETE FROM services WHERE id=?", (sid,))
            name = svc["name_ar"] if svc else "الخدمة"
            await q.edit_message_text(
                f"✅ تم حذف الخدمة *'{name}'* بنجاح.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=owner_settings_kb()
            )
            return

        if data == "os:edit_gift" and is_own:
            context.user_data["state"] = "os_await_gift_val"
            cur = get_setting("daily_gift_points") or "50"
            await q.edit_message_text(f"🎁 الهدية الحالية: {cur} نقطة\n\nأرسل القيمة الجديدة:")
            return

        if data == "os:edit_referral" and is_own:
            context.user_data["state"] = "os_await_referral_val"
            cur = get_setting("referral_points") or "30"
            await q.edit_message_text(f"🔗 نقاط الدعوة الحالية: {cur} نقطة\n\nأرسل القيمة الجديدة:")
            return

        if data == "os:edit_star_rate" and is_own:
            context.user_data["state"] = "os_await_star_rate"
            cur = get_setting("star_to_points") or "250"
            await q.edit_message_text(f"⭐ سعر النجمة (شحن) الحالي: {cur} نقطة\n\nأرسل القيمة الجديدة:")
            return

        if data == "os:edit_exchange_rate" and is_own:
            context.user_data["state"] = "os_await_exchange_rate"
            cur = get_setting("exchange_star_rate") or "2000"
            await q.edit_message_text(f"🏆 سعر نجمة الجوائز الحالي: {cur} نقطة\n\nأرسل القيمة الجديدة:")
            return

        if data == "os:edit_exchange_msg" and is_own:
            context.user_data["state"] = "os_await_exchange_msg"
            cur = get_setting("exchange_success_msg") or "(لا توجد رسالة مضافة حالياً)"
            await q.edit_message_text(
                f"✏️ الرسالة الحالية التي تظهر عند الاستبدال:\n\n{cur}\n\n"
                f"أرسل الرسالة الجديدة (ستظهر لكل مستخدم قبل كود عمليته تلقائياً):"
            )
            return

        if data == "os:edit_raksh_label" and is_own:
            context.user_data["state"] = "os_await_raksh_label"
            cur = get_raksh_accounts_label()
            await q.edit_message_text(
                "✏️ *تغيير اسم خدمات الرشق*\n\n"
                f"الاسم الحالي: *{md_escape(cur)}*\n\n"
                "أرسل الاسم الجديد بدون رمز 🔥، وسيبقى الرمز ظاهراً تلقائياً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع لإعدادات المالك", callback_data="owner_settings")]
                ]),
            )
            return

        if data == "os:raksh_accounts" and is_own:
            context.user_data["state"] = "main_menu"
            _raksh_label = md_escape(get_raksh_accounts_label())
            with db_conn() as _rc:
                _raksh_rows = _rc.execute(
                    "SELECT id, phone_number, session_string, last_authorized "
                    "FROM number_stock WHERE raksh_only=TRUE AND deleted_at IS NULL "
                    "ORDER BY id ASC"
                ).fetchall()
            _raksh_lines = [
                f"🔥 *{_raksh_label}*\n",
                "هذه الحسابات مخصصة لتنفيذ خدمات الرشق فقط، ولا تظهر ضمن مخزون بيع أرقام تيلغرام.\n",
                f"📦 العدد: *{len(_raksh_rows)}* حساب\n",
            ]
            if _raksh_rows:
                _raksh_lines.append("*الحسابات الحالية:*")
                _raksh_lines.extend(
                    f"• `{row['phone_number']}` "
                    f"{'✅ جلسة جاهزة' if row['session_string'] and row.get('last_authorized') is not False else '⚠️ تحتاج جلسة'}"
                    for row in _raksh_rows[:40]
                )
                if len(_raksh_rows) > 40:
                    _raksh_lines.append(f"_(+{len(_raksh_rows) - 40} حساباً آخر)_")
            else:
                _raksh_lines.append("لا توجد حسابات مخصصة للرشق حالياً.")
            _raksh_buttons = [
                [InlineKeyboardButton("🔑 تسجيل دخول حساب للرشق", callback_data="os:raksh_login_number")],
                [InlineKeyboardButton("➕ إضافة حسابات", callback_data="os:raksh_add_accounts")],
            ]
            for _raksh_row in _raksh_rows[:30]:
                _raksh_buttons.append([
                    InlineKeyboardButton(
                        f"🚫 إزالة {str(_raksh_row['phone_number'])[-8:]} من الرشق",
                        callback_data=f"os:raksh_unmark:{_raksh_row['id']}",
                    )
                ])
            _raksh_buttons.append([InlineKeyboardButton("🔙 رجوع لإعدادات المالك", callback_data="owner_settings")])
            await q.edit_message_text(
                "\n".join(_raksh_lines),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(_raksh_buttons),
            )
            return

        if data == "os:raksh_login_number" and is_own:
            if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
                await q.answer("❌ TELEGRAM_API_ID / TELEGRAM_API_HASH غير مضبوطة.", show_alert=True)
                return
            context.user_data["state"] = "os_await_raksh_login_phone"
            context.user_data.pop("raksh_only_import", None)
            await q.edit_message_text(
                "🔥 *تسجيل دخول حساب مخصص للرشق*\n\n"
                "أرسل رقم الهاتف بصيغة دولية، مثال: `+9647701234567`.\n"
                "بعد نجاح الدخول سيُحفظ الحساب للرشق فقط ولن يظهر للبيع.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="os:raksh_accounts")]
                ]),
            )
            return

        if data in {"os:raksh_add_accounts", "os:raksh_mark_existing"} and is_own:
            context.user_data["state"] = "os_await_raksh_add_accounts"
            await q.edit_message_text(
                "➕ *إضافة حسابات للرشق*\n\n"
                "أرسل رقماً أو عدة أرقام، كل رقم في سطر مستقل أو مفصول بفاصلة.\n"
                "سيتم تخصيص الحسابات لتنفيذ عمليات الرشق فقط واستبعادها من البيع فوراً.\n"
                "يمكنك إزالة التصنيف لاحقاً من قائمة حسابات الرشق.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="os:raksh_accounts")]
                ]),
            )
            return

        if data.startswith("os:raksh_unmark:") and is_own:
            context.user_data["state"] = "main_menu"
            _raksh_id = data.split(":", 2)[2]
            with db_conn() as _uc:
                _uc.execute(
                    "UPDATE number_stock SET raksh_only=FALSE "
                    "WHERE id=%s AND deleted_at IS NULL",
                    (_raksh_id,),
                )
            await q.answer("✅ تمت إزالة التصنيف. سيعود الحساب للبيع فقط إذا استوفى شروط الجاهزية.")
            data = "os:raksh_accounts"
            # إعادة عرض القائمة بنفس المعالج في الأسفل
            with db_conn() as _rc:
                _raksh_rows = _rc.execute(
                    "SELECT id, phone_number, session_string, last_authorized "
                    "FROM number_stock WHERE raksh_only=TRUE AND deleted_at IS NULL ORDER BY id ASC"
                ).fetchall()
            _raksh_lines = [
                f"🔥 *{md_escape(get_raksh_accounts_label())}*\n",
                "هذه الحسابات مخصصة لتنفيذ خدمات الرشق فقط، ولا تظهر ضمن مخزون بيع أرقام تيلغرام.\n",
                f"📦 العدد: *{len(_raksh_rows)}* حساب\n",
            ]
            if _raksh_rows:
                _raksh_lines.append("*الحسابات الحالية:*")
                _raksh_lines.extend(f"• `{row['phone_number']}`" for row in _raksh_rows[:40])
            else:
                _raksh_lines.append("لا توجد حسابات مخصصة للرشق حالياً.")
            _raksh_buttons = [
                [InlineKeyboardButton("🔑 تسجيل دخول حساب للرشق", callback_data="os:raksh_login_number")],
                [InlineKeyboardButton("➕ إضافة حسابات", callback_data="os:raksh_add_accounts")],
            ]
            for _raksh_row in _raksh_rows[:30]:
                _raksh_buttons.append([
                    InlineKeyboardButton(
                        f"🚫 إزالة {str(_raksh_row['phone_number'])[-8:]} من الرشق",
                        callback_data=f"os:raksh_unmark:{_raksh_row['id']}",
                    )
                ])
            _raksh_buttons.append([InlineKeyboardButton("🔙 رجوع لإعدادات المالك", callback_data="owner_settings")])
            await q.edit_message_text(
                "\n".join(_raksh_lines),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(_raksh_buttons),
            )
            return

        if data == "os:manage_numbers" and is_own:
            avail = get_available_number_count()
            await q.edit_message_text(
                "📥 *مخزون أرقام تيلغرام*\n\n"
                f"📦 الأرقام المتاحة حالياً: *{avail}*\n\n"
                "عندما يشتري عضو رقماً وهناك مخزون متاح، يُسلَّم له تلقائياً وفوراً بدون أي تدخل منك.\n"
                "إذا نفد المخزون، يعود الطلب لطريقة التواصل اليدوي كما هو معتاد.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔑 تسجيل دخول رقم جديد (تلقائي بالكامل)", callback_data="os:login_number")],
                    [InlineKeyboardButton("📋 قائمة الأرقام ومعلوماتها", callback_data="os:list_numbers")],
                    [InlineKeyboardButton("🔍 فحص جميع الحسابات الآن", callback_data="os:scan_all_numbers")],
                    [InlineKeyboardButton("📊 فحص الحسابات جميعاً (إحصاء + نقل الميتة للمهملات)", callback_data="os:full_audit")],
                    [InlineKeyboardButton("🧹 فحص ذكي شامل (تنظيف + إعادة 2FA + ترتيب للبيع)", callback_data="os:smart_audit")],
                    [InlineKeyboardButton("➕ إضافة أرقام بدون تسجيل دخول (يدوي)", callback_data="os:add_numbers")],
                    [InlineKeyboardButton("🔄 إرجاع جميع الأرقام المباعة للبيع", callback_data="os:release_all_numbers")],
                    [InlineKeyboardButton("🔍 فحص جاهزية الأرقام (كود + 2FA)", callback_data="os:check_readiness")],
                    [InlineKeyboardButton("🗑️ حذف الأرقام اليدوية + تعويض المشترين", callback_data="os:delete_manual_numbers")],
                    [InlineKeyboardButton("🔑 تعيين كلمة مرور 'محمد' لجميع الحسابات", callback_data="os:set_all_2fa_muhammed")],
                    [InlineKeyboardButton("✅ التأكد من الحسابات التي تحققها محمد", callback_data="os:verify_muhammed_accounts")],
                    [InlineKeyboardButton("💥 محاولة طرد جميع الأجهزة", callback_data="os:kick_all_devices")],
                    [InlineKeyboardButton("🔓 إزالة التحقق (2FA) من ملفات جلسة", callback_data="os:remove_2fa_mode")],
                    [InlineKeyboardButton("🔁 تدوير الجلسات (تجديد كل السيشن)", callback_data="os:rotate_sessions")],
                    [InlineKeyboardButton("🤝 مهام الإحالة التلقائية", callback_data="os:ref_tasks")],
                    [InlineKeyboardButton("🔎 بحث برقم هاتف", callback_data="os:phone_search")],
                    [InlineKeyboardButton("🛒 الحسابات المبيوعة", callback_data="os:sold_accounts")],
                    [InlineKeyboardButton("⚠️ تعويض المظلومين / العمليات الفاشلة", callback_data="os:failed_deliveries")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
                ])
            )
            return

        if data == "os:check_readiness" and is_own:
            with db_conn() as c:
                rows = c.execute(
                    "SELECT phone_number, session_string, twofa_password, last_authorized, deleted_at "
                    "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL ORDER BY id ASC"
                ).fetchall()
            total = len(rows)
            full_ready   = []  # session + 2FA
            session_only = []  # session but no 2FA
            no_session   = []  # no session (manual/kicked)
            for r in rows:
                has_session = bool(r["session_string"]) and r.get("last_authorized") is not False
                has_twofa   = bool((r["twofa_password"] or "").strip())
                if has_session and has_twofa:
                    full_ready.append(r["phone_number"])
                elif has_session:
                    session_only.append(r["phone_number"])
                else:
                    no_session.append(r["phone_number"])
        
            lines = [f"🔍 *فحص جاهزية الأرقام ({total} رقم)*\n"]
            lines.append(
                f"✅ *جاهز بالكامل (كود + 2FA): {len(full_ready)}*\n"
                + ("\n".join(f"   • `{p}`" for p in full_ready[:20])
                   + (f"\n   _(+{len(full_ready)-20} آخرين)_" if len(full_ready) > 20 else ""))
                if full_ready else "✅ *جاهز بالكامل:* لا يوجد"
            )
            lines.append("")
            lines.append(
                f"⚠️ *يملك جلسة فقط (بدون 2FA): {len(session_only)}*\n"
                + ("\n".join(f"   • `{p}`" for p in session_only[:20])
                   + (f"\n   _(+{len(session_only)-20} آخرين)_" if len(session_only) > 20 else ""))
                if session_only else "⚠️ *بدون 2FA:* لا يوجد"
            )
            lines.append("")
            lines.append(
                f"❌ *بدون جلسة (لا كود ولا 2FA): {len(no_session)}*\n"
                + ("\n".join(f"   • `{p}`" for p in no_session[:20])
                   + (f"\n   _(+{len(no_session)-20} آخرين)_" if len(no_session) > 20 else ""))
                if no_session else "❌ *بدون جلسة:* لا يوجد"
            )
            await q.edit_message_text(
                "\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")],
                ])
            )
            return

        if data == "os:delete_manual_numbers" and is_own:
            with db_conn() as c:
                manual_rows = c.execute(
                    "SELECT id, phone_number, assigned_to FROM number_stock "
                    "WHERE session_string IS NULL AND deleted_at IS NULL"
                ).fetchall()
        
                if not manual_rows:
                    await q.answer("✅ لا توجد أرقام يدوية في المخزون.", show_alert=True)
                    return
        
                deleted_count  = 0
                compensated    = 0
                buyers_notified = []
        
                for row in manual_rows:
                    phone = row["phone_number"]
                    pe = c.execute(
                        "SELECT id, user_id, points_cost, compensated_at FROM prize_exchanges "
                        "WHERE prize_value=%s AND prize_type IN ('telegram_number','telegram_number_code','telegram_number_stars') "
                        "AND status='completed' ORDER BY id DESC LIMIT 1",
                        (phone,)
                    ).fetchone()
        
                    c.execute(
                        "UPDATE number_stock SET deleted_at=NOW(), assigned_to=NULL, assigned_at=NULL WHERE id=%s",
                        (row["id"],)
                    )
                    deleted_count += 1
        
                    if pe and pe["points_cost"]:
                        if pe["compensated_at"]:
                            logger.info(f"⏭ delete_manual_numbers: {phone} عُوِّض مسبقاً، تخطّي.")
                            continue
                        pts = pe["points_cost"]
                        uid = pe["user_id"]
                        pe_id_m = pe["id"]
                        rows_m = c.execute(
                            "UPDATE prize_exchanges SET "
                            "compensated_at=NOW(), compensated_pts=%s, compensated_reason='manual_number_deleted' "
                            "WHERE id=%s AND compensated_at IS NULL",
                            (pts, pe_id_m)
                        ).rowcount
                        if rows_m == 0:
                            continue
                        add_points(uid, pts)
                        compensated += 1
                        buyers_notified.append((uid, phone, pts))
        
            for uid, phone, pts in buyers_notified:
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=(
                            f"💰 *إشعار تعويض*\n"
                            f"{'─' * 28}\n\n"
                            f"عزيزي العميل،\n"
                            f"الرقم الذي حصلت عليه `{phone}` تبيّن أنه أُضيف يدوياً "
                            f"ولا يضمن وصولك الكامل للحساب (بدون جلسة أو 2FA).\n\n"
                            f"✅ *تم تعويضك فوراً بـ {pts:,} نقطة* أُضيفت لرصيدك.\n\n"
                            f"يمكنك استخدامها لشراء رقم جديد متاح بالكامل.\n"
                            f"نعتذر عن الإزعاج 🙏"
                        ),
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass
        
            summary = (
                f"🗑️ *تم حذف {deleted_count} رقم يدوي*\n\n"
                f"💰 *عُوِّض {compensated} مشترٍ* وأُعيدت لهم نقاطهم كاملةً.\n"
            )
            if deleted_count - compensated > 0:
                summary += f"📦 *{deleted_count - compensated}* رقم لم يُباع (لا يحتاج تعويض)."
        
            await q.edit_message_text(
                summary,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")],
                ])
            )
            return

        if data.startswith("os:allow_5min:") and is_own:
            _phone_allow = data[len("os:allow_5min:"):]
            _allow_5min_phones[_phone_allow] = {"until": time.time() + 300, "used": False}
            await q.answer("✅ رُفعت الحراسة — أول دخول خلال 5 دقائق يُسمح له ويبقى للأبد.")
            await q.edit_message_text(
                f"✅ *نافذة سماح 5 دقائق مفتوحة*\n\n"
                f"📱 الرقم: `{_phone_allow}`\n\n"
                f"• الشخص *الأول* الذي يدخل خلال 5 دقائق يبقى *للأبد* — لن يُطرد.\n"
                f"• أي دخول *ثانٍ* يُطرد فوراً حتى لو في نفس الوقت.\n"
                f"• إذا انتهت الدقائق الخمس قبل الدخول، يعود الطرد الفوري لأي جلسة جديدة.\n"
                f"• عند بيع الحساب: الشخص المسموح له يُطرد تلقائياً والمشتري يبقى وحده.",
                parse_mode=ParseMode.MARKDOWN
            )
            async def _expire_allow(ph):
                await asyncio.sleep(305)
                _allow_5min_phones.pop(ph, None)
            asyncio.create_task(_expire_allow(_phone_allow))
            return

        if data.startswith("os:account_info:") and is_own:
            _phone_info = data[len("os:account_info:"):]
            await q.answer()
            try:
                with db_conn() as _ci:
                    _row_info = _ci.execute(
                        "SELECT phone_number, session_string, twofa_password, added_at, "
                        "last_authorized, last_device_count, ever_sold, assigned_to "
                        "FROM number_stock WHERE phone_number=%s", (_phone_info,)
                    ).fetchone()
                if not _row_info:
                    await q.edit_message_text(f"⚠️ الرقم `{_phone_info}` غير موجود في المخزون.", parse_mode=ParseMode.MARKDOWN)
                    return
                _devices_info = _row_info["last_device_count"] or "؟"
                _auth_info    = "✅ نشطة" if _row_info["last_authorized"] else "❌ منتهية"
                _sold_info    = "مباع" if _row_info["ever_sold"] else "غير مباع"
                _pwd_info     = f"`{_row_info['twofa_password']}`" if _row_info["twofa_password"] else "غير محفوظة"
                _added_info   = format_account_datetime(_row_info["added_at"]) if _row_info["added_at"] else "؟"
                text_info = (
                    f"📋 *معلومات الحساب*\n\n"
                    f"📱 الرقم: `{_phone_info}`\n"
                    f"🌍 الدولة: {guess_country(_phone_info)}\n"
                    f"📅 أُضيف: {_added_info}\n"
                    f"🔗 الجلسة: {_auth_info}\n"
                    f"📲 الأجهزة: {_devices_info}\n"
                    f"💰 الحالة: {_sold_info}\n"
                    f"🔐 كلمة 2FA: {_pwd_info}"
                )
                await q.edit_message_text(text_info, parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ سماح 5 دقائق", callback_data=f"os:allow_5min:{_phone_info}"),
                        InlineKeyboardButton("🚪 مغادرة البوت", callback_data=f"os:leave_account:{_phone_info}"),
                    ]]))
            except Exception as _ei:
                await q.edit_message_text(f"❌ خطأ أثناء جلب المعلومات: {_ei}", parse_mode=ParseMode.MARKDOWN)
            return
    return True
