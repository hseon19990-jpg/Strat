"""Callback case group 4 for the Telegram bot.

Cases stay in their original order. A matching case returns from this group,
while the sentinel lets the dispatcher continue to the next group.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

async def _handle_callback_group_04(update, context, q, data, user, is_own, is_supervisor_cb, _gmail_verification_done):
    if True:
        if data.startswith("verify_emoji:"):
            if context.user_data.get("state") != "verify_emoji":
                await q.answer("⚠️ انتهت جلسة التحقق.", show_alert=True)
                return
            try:
                selected_index = int(data.split(":", 1)[1])
                options = context.user_data.get("emoji_options") or []
                selected = options[selected_index]
            except (ValueError, IndexError, TypeError):
                await q.answer("⚠️ زر تحقق غير صالح.", show_alert=True)
                return
            if selected == context.user_data.get("emoji_ans"):
                await q.answer("✅ إجابة صحيحة")
                await ask_for_phone_share(update, context, edit=True)
            else:
                question, new_options = generate_emoji_captcha()
                context.user_data["emoji_ans"] = question
                context.user_data["emoji_options"] = new_options
                await q.answer("❌ إجابة خاطئة", show_alert=True)
                await q.edit_message_text(
                    f"🔐 للدخول للبوت، اختر الإيموجي المطابق:\n\n❓  *{question}*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=emoji_captcha_kb(new_options)
                )
            return
        if data == "os:cancel_order" and is_own:
            context.user_data["state"] = "os_await_cancel_order"
            await q.edit_message_text("❌ *إلغاء طلب:*\n\nأرسل كود الطلب المراد إلغاؤه:", parse_mode=ParseMode.MARKDOWN)
            return

        if data == "os:complete_order" and is_own:
            context.user_data["state"] = "os_await_complete_order"
            await q.edit_message_text("✅ *إكمال طلب:*\n\nأرسل كود الطلب الذي تم تنفيذه بالكامل:", parse_mode=ParseMode.MARKDOWN)
            return

        if data == "os:manage_channels" and is_own:
            context.user_data["state"] = "os_await_channel"
            with db_conn() as c:
                channels = c.execute(
                    "SELECT * FROM mandatory_channels WHERE active=1 OR queued=1 ORDER BY queued ASC, id ASC"
                ).fetchall()
                fundings = {}
                for ch in channels:
                    f = c.execute(
                        "SELECT current_members, target_members FROM channel_funding "
                        "WHERE channel_username=%s AND status='active' ORDER BY id DESC LIMIT 1",
                        (ch["channel_username"],)
                    ).fetchone()
                    if f:
                        fundings[ch["channel_username"]] = f
            if channels:
                lines = ["📡 *القنوات الحالية:*\n"]
                for ch in channels:
                    tag = " ⏳ قيد الانتظار" if ch["queued"] else ""
                    f = fundings.get(ch["channel_username"])
                    progress = f" — {f['current_members']}/{f['target_members']}" if f else ""
                    lines.append(f"• @{md_escape(ch['channel_username'])} ({md_escape(ch['funding_type'])}){progress}{tag}")
            else:
                lines = ["📡 لا توجد قنوات مضافة حالياً."]
            rows = []
            for ch in channels:
                rows.append([InlineKeyboardButton(
                    f"❌ حذف @{ch['channel_username']}",
                    callback_data=f"os_del_ch:{ch['id']}"
                )])
            rows.append([InlineKeyboardButton("➕ إضافة قناة", callback_data="os_add_ch")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
            await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("os_del_ch:") and is_own:
            ch_id = int(data.split(":")[1])
            with db_conn() as c:
                _deleted_ch = c.execute("SELECT funding_type FROM mandatory_channels WHERE id=%s", (ch_id,)).fetchone()
                c.execute("UPDATE mandatory_channels SET active=0, queued=0 WHERE id=%s", (ch_id,))
            if _deleted_ch and _deleted_ch.get("funding_type") == "mandatory":
                await promote_queued_mandatory_channel(context, app=context.application)
            await q.answer("🗑 تم حذف القناة")
            return

        if data == "os_add_ch" and is_own:
            context.user_data["state"] = "os_await_channel"
            await q.edit_message_text("📡 أرسل يوزرنيم القناة (مثال: @channel):")
            return

        if data == "os:ban_menu" and is_own:
            with db_conn() as c:
                banned_count = c.execute("SELECT COUNT(*) as cnt FROM users WHERE banned=1").fetchone()["cnt"]
            await q.edit_message_text(
                f"🚫 *إدارة الحظر*\n\nعدد الأعضاء المحظورين حالياً: *{banned_count}*\n\n"
                "اختر الإجراء:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚫 حظر عضو (ID أو @يوزر)", callback_data="os:ban_member")],
                    [InlineKeyboardButton("🔓 رفع حظر عضو", callback_data="os:unban_member")],
                    [InlineKeyboardButton("📋 قائمة المحظورين", callback_data="os:list_banned")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
                ]),
            )
            return

        if data == "os:ban_member" and is_own:
            context.user_data["state"] = "os_await_ban_target"
            await q.edit_message_text(
                "🚫 *حظر عضو*\n\nأرسل الـ ID الرقمي للعضو أو @يوزرنيم:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:ban_menu")]]),
            )
            return

        if data == "os:unban_member" and is_own:
            context.user_data["state"] = "os_await_unban_target"
            await q.edit_message_text(
                "🔓 *رفع حظر عضو*\n\nأرسل الـ ID الرقمي للعضو أو @يوزرنيم:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:ban_menu")]]),
            )
            return

        if data.startswith("os:unban_confirm:") and is_own:
            target_id = int(data.split(":")[-1])
            found = unban_user_db(target_id)
            target = get_user(target_id)
            if found and target:
                uname = f"@{target['username']}" if target.get("username") else f"ID: {target_id}"
                await q.edit_message_text(
                    f"✅ *تم رفع الحظر عن:* {target.get('full_name', '')} ({uname})",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")]]),
                )
            else:
                await q.answer("⚠️ لم يُوجد المستخدم.", show_alert=True)
            return

        if data == "os:list_banned" and is_own:
            try:
                with db_conn() as c:
                    banned = c.execute(
                        "SELECT user_id, username, full_name, banned_at, ban_reason FROM users "
                        "WHERE banned=1 ORDER BY banned_at DESC NULLS LAST LIMIT 50"
                    ).fetchall()
                if not banned:
                    await q.edit_message_text(
                        "📋 لا يوجد أعضاء محظورون حالياً.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")]]),
                    )
                    return
                lines = ["🚫 *الأعضاء المحظورون:*\n"]
                kb_rows = []
                for b in banned:
                    uname = f"@{md_escape(b['username'])}" if b["username"] else f"ID: {b['user_id']}"
                    ts_raw = b["banned_at"]
                    ts = ts_raw.strftime("%Y-%m-%d %H:%M") if ts_raw and hasattr(ts_raw, "strftime") else (str(ts_raw)[:16] if ts_raw else "—")
                    reason = md_escape(b["ban_reason"] or "—")
                    fname  = md_escape(b["full_name"] or "—")
                    lines.append(f"• {fname} ({uname})\n  📝 {reason} | 🕐 {ts}")
                    kb_rows.append([InlineKeyboardButton(
                        f"🔓 رفع حظر {uname}",
                        callback_data=f"os:unban_confirm:{b['user_id']}"
                    )])
                kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")])
                full_text = "\n".join(lines)
                if len(full_text) > 4000:
                    full_text = full_text[:4000] + "\n\n⚠️ القائمة طويلة، تم اقتصارها."
                await q.edit_message_text(
                    full_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(kb_rows),
                )
            except Exception as _e:
                logger.error(f"❌ os:list_banned error: {_e}")
                await q.answer(f"❌ خطأ: {_e}", show_alert=True)
            return

        if data == "os:create_promo" and is_own:
            context.user_data["state"] = "os_await_promo_code_text"
            await q.edit_message_text(
                "🎟 *إنشاء كود ترويجي جديد*\n\nأرسل الكود المراد إنشاؤه (أحرف وأرقام فقط):",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "os:list_promos" and is_own:
            with db_conn() as c:
                promos = c.execute("SELECT * FROM promo_codes ORDER BY created_at DESC").fetchall()
            if not promos:
                await q.edit_message_text("📋 لا توجد أكواد ترويجية.", reply_markup=owner_settings_kb())
                return
            lines = ["📋 *الأكواد الترويجية:*\n"]
            rows  = []
            for p in promos:
                status = "✅" if p["active"] else "❌"
                lines.append(
                    f"{status} `{p['code']}` — {p['points']} نقطة — {p['used_count']}/{p['max_uses']} استخدام"
                )
                tog = "❌ تعطيل" if p["active"] else "✅ تفعيل"
                rows.append([
                    InlineKeyboardButton(f"👥 {p['code']}", callback_data=f"os:promo_users:{p['code']}"),
                    InlineKeyboardButton(tog, callback_data=f"os_tog_promo:{p['code']}:{0 if p['active'] else 1}"),
                    InlineKeyboardButton("🗑", callback_data=f"os_del_promo:{p['code']}")
                ])
            rows.append([InlineKeyboardButton("🔍 بحث عن كود (حتى القديمة)", callback_data="os:search_code")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
            await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=InlineKeyboardMarkup(rows))
            return

        if data == "os:search_code" and is_own:
            context.user_data["state"] = "os_await_code_search"
            await q.edit_message_text(
                "🔍 *البحث عن مستخدمي كود*\n\n"
                "أرسل نص الكود (يعمل حتى للأكواد القديمة المحذوفة):",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="owner_settings")]]),
            )
            return

        if data.startswith("os:promo_users:") and is_own:
            code = data[len("os:promo_users:"):]
            try:
                with db_conn() as c:
                    promo = c.execute("SELECT * FROM promo_codes WHERE code=%s", (code,)).fetchone()
                with db_conn() as c:
                    uses = c.execute(
                        """
                    SELECT pu.user_id, pu.used_at,
                           u.username, u.full_name, u.points
                    FROM promo_uses pu
                    LEFT JOIN users u ON u.user_id = pu.user_id
                    WHERE pu.code = %s
                    ORDER BY pu.used_at DESC NULLS LAST
                    """,
                        (code,)
                    ).fetchall()
                if not promo:
                    await q.answer("⚠️ الكود غير موجود", show_alert=True)
                    return
                header = (
                    f"👥 *من استخدم الكود:* `{code}`\n"
                    f"🎁 النقاط: {promo['points']} | الاستخدامات: {promo['used_count']}/{promo['max_uses']}\n"
                )
                if not uses:
                    body = "\n_لم يستخدمه أحد بعد._"
                else:
                    lines = []
                    for i, u in enumerate(uses, 1):
                        name  = md_escape((u["full_name"] or "").strip() or "—")
                        uname = f"@{md_escape(u['username'])}" if u["username"] else f"ID: {u['user_id']}"
                        pts   = u["points"] if u["points"] is not None else "؟"
                        ts_raw = u["used_at"]
                        if ts_raw:
                            if hasattr(ts_raw, "strftime"):
                                ts = ts_raw.strftime("%Y-%m-%d %H:%M")
                            else:
                                ts = str(ts_raw)[:16]
                        else:
                            ts = "—"
                        lines.append(
                            f"{i}. {name} ({uname})\n"
                            f"   💰 رصيده: {pts} نقطة | 🕐 {ts}"
                        )
                    body = "\n\n" + "\n\n".join(lines)
                full_text = header + body
                if len(full_text) > 4000:
                    full_text = full_text[:4000] + "\n\n⚠️ القائمة طويلة، تم اقتصارها."
                await q.edit_message_text(
                    full_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 رجوع للأكواد", callback_data="os:list_promos")]
                    ])
                )
            except Exception as _e:
                logger.error(f"❌ os:promo_users error: {_e}")
                await q.answer(f"❌ خطأ: {_e}", show_alert=True)
            return

        if data.startswith("os_tog_promo:") and is_own:
            parts = data.split(":")
            code  = parts[1]
            val   = int(parts[2])
            with db_conn() as c:
                c.execute("UPDATE promo_codes SET active=? WHERE code=?", (val, code))
            await q.answer("✅ تم التحديث")
            return

        if data.startswith("os_del_promo:") and is_own:
            code = data.split(":")[1]
            with db_conn() as c:
                c.execute("DELETE FROM promo_codes WHERE code=?", (code,))
            await q.answer("🗑 تم الحذف")
            return

        if data == "os:manage_points" and is_own:
            await q.edit_message_text(
                "💰 *منح / خصم نقاط*\n\nاختر العملية:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ منح نقاط لعضو", callback_data="os:give_points")],
                    [InlineKeyboardButton("➖ خصم نقاط من عضو", callback_data="os:deduct_points")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
                ])
            )
            return

        if data == "os:give_points" and is_own:
            # افصل عملية النقاط عن أي حالة سابقة لتعديل خدمة/سعر.
            context.user_data.pop("edit_svc_id", None)
            context.user_data.pop("new_svc_id", None)
            context.user_data.pop("points_target_id", None)
            context.user_data["state"]       = "os_await_points_target"
            context.user_data["points_mode"] = "give"
            await q.edit_message_text(
                "➕ *منح نقاط*\n\nأرسل ID المستخدم أو @يوزرنيم:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_points")]])
            )
            return

        if data == "os:deduct_points" and is_own:
            # افصل عملية النقاط عن أي حالة سابقة لتعديل خدمة/سعر.
            context.user_data.pop("edit_svc_id", None)
            context.user_data.pop("new_svc_id", None)
            context.user_data.pop("points_target_id", None)
            context.user_data["state"]       = "os_await_points_target"
            context.user_data["points_mode"] = "deduct"
            await q.edit_message_text(
                "➖ *خصم نقاط*\n\nأرسل ID المستخدم أو @يوزرنيم:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_points")]])
            )
            return

        if data == "os:broadcast" and is_own:
            context.user_data["state"] = "os_await_broadcast"
            with db_conn() as c:
                total = c.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
            await q.edit_message_text(
                f"📢 *رسالة جماعية*\n\n"
                f"سيتم الإرسال لـ {total} مستخدم.\n\n"
                f"أرسل الرسالة الآن (يدعم HTML):",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "os:toggle_phone_verification" and is_own:
            current = int(get_setting("phone_verification_enabled") or "1")
            new_val = "0" if current else "1"
            set_setting("phone_verification_enabled", new_val)
            status = "مفعّل ✅" if new_val == "1" else "معطّل ❌"
            await q.edit_message_text(
                f"📱 *التحقق برقم الهاتف الآن: {status}*\n\n"
                f"{'سيطلب البوت رقم الهاتف عند وجود إحالة معلّقة' if new_val == '1' else 'لن يطلب البوت رقم الهاتف، ولن تُحتسب مكافأة الإحالة تلقائياً'}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=owner_settings_kb()
            )
            return

        if data == "os:toggle_captcha" and is_own:
            current = int(get_setting("captcha_enabled") or "0")
            new_val = "0" if current else "1"
            set_setting("captcha_enabled", new_val)
            status = "مفعّل ✅" if new_val == "1" else "معطّل ❌"
            await q.edit_message_text(
                f"🔐 *التحقق الرياضي الآن: {status}*\n\n"
                f"{'سيظهر السؤال للمستخدمين الجدد عند /start' if new_val == '1' else 'لن يظهر أي سؤال للمستخدمين الجدد'}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=owner_settings_kb()
            )
            return

        if data == "os:toggle_maintenance" and is_own:
            current = int(get_setting("maintenance_mode") or "0")
            new_val = "0" if current else "1"
            set_setting("maintenance_mode", new_val)
            status = "مفعّل 🛠" if new_val == "1" else "معطّل ✅"
            await q.edit_message_text(
                f"🛠 *وضع الصيانة الآن: {status}*\n\n"
                f"{'سيشاهد جميع الأعضاء (عدا المالك) رسالة الصيانة بدل البوت.' if new_val == '1' else 'البوت يعمل بشكل طبيعي لجميع الأعضاء.'}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=owner_settings_kb()
            )
            return

        if data == "os:manage_num_codes" and is_own:
            with db_conn() as c:
                ncodes = c.execute(
                    "SELECT code, max_uses, used_count, active FROM number_purchase_codes ORDER BY created_at DESC LIMIT 20"
                ).fetchall()
            rows = []
            if ncodes:
                for nc in ncodes:
                    status = "✅" if nc["active"] else "❌"
                    rows.append([InlineKeyboardButton(
                        f"{status} {nc['code']} ({nc['used_count']}/{nc['max_uses']})",
                        callback_data=f"os:num_code_info:{nc['code']}"
                    )])
            rows.append([InlineKeyboardButton("➕ إنشاء كود شراء جديد", callback_data="os:create_num_code")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:back_settings")])
            await q.edit_message_text(
                "🎟 *أكواد شراء رقم تيلغرام*\n\n"
                "كل كود يُتيح للمستخدم شراء رقم تيلغرام بدون نقاط.\n"
                "يمكنك تحديد عدد مرات الاستخدام لكل كود.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data == "os:create_num_code" and is_own:
            context.user_data["state"] = "os_await_num_code_text"
            await q.edit_message_text(
                "🎟 *إنشاء كود شراء رقم جديد*\n\nأرسل الكود المطلوب (حروف وأرقام فقط):",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data.startswith("os:num_code_info:") and is_own:
            nc_code = data[len("os:num_code_info:"):]
            with db_conn() as c:
                nc = c.execute("SELECT * FROM number_purchase_codes WHERE code=%s", (nc_code,)).fetchone()
            if not nc:
                await q.answer("⚠️ الكود غير موجود.", show_alert=True)
                return
            status = "✅ فعّال" if nc["active"] else "❌ معطّل"
            toggle_label = "❌ تعطيل الكود" if nc["active"] else "✅ تفعيل الكود"
            rows = [
                [InlineKeyboardButton(f"👥 من استخدم الكود ({nc['used_count']})", callback_data=f"os:num_code_users:{nc_code}")],
                [InlineKeyboardButton(toggle_label, callback_data=f"os:toggle_num_code:{nc_code}")],
                [InlineKeyboardButton("🗑 حذف الكود", callback_data=f"os:del_num_code:{nc_code}")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_num_codes")],
            ]
            await q.edit_message_text(
                f"🎟 *كود شراء رقم*\n\n"
                f"الكود: `{nc_code}`\n"
                f"الحالة: {status}\n"
                f"مرات الاستخدام: {nc['used_count']}/{nc['max_uses']}\n"
                f"تاريخ الإنشاء: {nc['created_at']}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data.startswith("os:num_code_users:") and is_own:
            nc_code = data[len("os:num_code_users:"):]
            try:
                with db_conn() as c:
                    nc = c.execute("SELECT * FROM number_purchase_codes WHERE code=%s", (nc_code,)).fetchone()
                    uses = c.execute(
                        """
                    SELECT ncu.user_id, ncu.used_at,
                           u.username, u.full_name, u.points,
                           pe.prize_value AS number_given
                    FROM number_purchase_code_uses ncu
                    LEFT JOIN users u ON u.user_id = ncu.user_id
                    LEFT JOIN prize_exchanges pe ON pe.user_id = ncu.user_id
                         AND pe.prize_type = 'telegram_number_code'
                         AND pe.status = 'completed'
                    WHERE ncu.code = %s
                    ORDER BY ncu.used_at DESC NULLS LAST
                    """,
                        (nc_code,)
                    ).fetchall()
                if nc:
                    header = (
                        f"👥 *من استخدم كود شراء الرقم:* `{nc_code}`\n"
                        f"الاستخدامات: {nc['used_count']}/{nc['max_uses']} | "
                        f"{'✅ فعّال' if nc['active'] else '❌ معطّل'}\n\n"
                    )
                else:
                    header = f"👥 *من استخدم الكود (قديم):* `{nc_code}`\n\n"
                if not uses:
                    body = "_لم يستخدمه أحد بعد._"
                else:
                    lines = []
                    for i, u in enumerate(uses, 1):
                        name  = md_escape((u["full_name"] or "").strip() or "—")
                        uname = f"@{md_escape(u['username'])}" if u["username"] else f"ID: {u['user_id']}"
                        num   = u["number_given"] or "—"
                        ts_raw = u["used_at"]
                        ts = ts_raw.strftime("%Y-%m-%d %H:%M") if ts_raw and hasattr(ts_raw, "strftime") else (str(ts_raw)[:16] if ts_raw else "—")
                        lines.append(
                            f"{i}. {name} ({uname})\n"
                            f"   📱 الرقم المسلَّم: `{num}`\n"
                            f"   🕐 {ts}"
                        )
                    body = "\n\n".join(lines)
                full_text = header + body
                if len(full_text) > 4000:
                    full_text = full_text[:3950] + "\n\n⚠️ القائمة طويلة، تم اقتصارها."
                await q.edit_message_text(
                    full_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 رجوع للكود", callback_data=f"os:num_code_info:{nc_code}")]
                    ])
                )
            except Exception as _e:
                logger.error(f"❌ os:num_code_users error: {_e}")
                await q.answer(f"❌ خطأ: {_e}", show_alert=True)
            return

        if data.startswith("os:toggle_num_code:") and is_own:
            nc_code = data[len("os:toggle_num_code:"):]
            with db_conn() as c:
                nc = c.execute("SELECT active FROM number_purchase_codes WHERE code=%s", (nc_code,)).fetchone()
                if nc:
                    new_active = 0 if nc["active"] else 1
                    c.execute("UPDATE number_purchase_codes SET active=%s WHERE code=%s", (new_active, nc_code))
            await q.answer("✅ تم تحديث حالة الكود.", show_alert=False)
            with db_conn() as c:
                nc2 = c.execute("SELECT * FROM number_purchase_codes WHERE code=%s", (nc_code,)).fetchone()
            status = "✅ فعّال" if nc2["active"] else "❌ معطّل"
            toggle_label = "❌ تعطيل الكود" if nc2["active"] else "✅ تفعيل الكود"
            rows = [
                [InlineKeyboardButton(f"👥 من استخدم الكود ({nc2['used_count']})", callback_data=f"os:num_code_users:{nc_code}")],
                [InlineKeyboardButton(toggle_label, callback_data=f"os:toggle_num_code:{nc_code}")],
                [InlineKeyboardButton("🗑 حذف الكود", callback_data=f"os:del_num_code:{nc_code}")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_num_codes")],
            ]
            await q.edit_message_text(
                f"🎟 *كود شراء رقم*\n\n"
                f"الكود: `{nc_code}`\n"
                f"الحالة: {status}\n"
                f"مرات الاستخدام: {nc2['used_count']}/{nc2['max_uses']}\n"
                f"تاريخ الإنشاء: {nc2['created_at']}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if data.startswith("os:del_num_code:") and is_own:
            nc_code = data[len("os:del_num_code:"):]
            with db_conn() as c:
                c.execute("DELETE FROM number_purchase_codes WHERE code=%s", (nc_code,))
                c.execute("DELETE FROM number_purchase_code_uses WHERE code=%s", (nc_code,))
            await q.edit_message_text(
                f"✅ تم حذف الكود `{nc_code}` بنجاح.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_kb("os:manage_num_codes")
            )
            return

        if data == "os:toggle_number_exchange" and is_own:
            current = int(get_setting("number_exchange_enabled") or "0")
            new_val = "0" if current else "1"
            set_setting("number_exchange_enabled", new_val)
            status = "مفعّل ✅" if new_val == "1" else "مغلق ❌"
            await q.edit_message_text(
                f"📱 *استبدال الأرقام الآن: {status}*\n\n"
                f"{'المستخدمون يستطيعون الآن شراء أرقام تيلغرام بالنقاط.' if new_val == '1' else 'زر شراء الرقم مغلق أمام جميع المستخدمين حتى تعيد تفعيله.'}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=owner_settings_kb()
            )
            return

        if data == "os:stats" and is_own:
            with db_conn() as c:
                total_users     = c.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
                verified_users  = c.execute("SELECT COUNT(*) as cnt FROM users WHERE verified=1").fetchone()["cnt"]
                total_orders    = c.execute("SELECT COUNT(*) as cnt FROM orders").fetchone()["cnt"]
                pending_orders  = c.execute("SELECT COUNT(*) as cnt FROM orders WHERE status='pending'").fetchone()["cnt"]
                completed_orders = c.execute("SELECT COUNT(*) as cnt FROM orders WHERE status='completed'").fetchone()["cnt"]
                cancelled_orders = c.execute("SELECT COUNT(*) as cnt FROM orders WHERE status='cancelled'").fetchone()["cnt"]
                total_pts       = c.execute("SELECT SUM(points) as s FROM users").fetchone()["s"] or 0
                total_promos    = c.execute("SELECT COUNT(*) as cnt FROM promo_codes WHERE active=1").fetchone()["cnt"]
                active_mandatory = c.execute(
                    "SELECT COUNT(*) as cnt FROM mandatory_channels WHERE active=1 AND funding_type='mandatory'"
                ).fetchone()["cnt"]
                queued_mandatory = c.execute(
                    "SELECT COUNT(*) as cnt FROM mandatory_channels WHERE queued=1 AND funding_type='mandatory'"
                ).fetchone()["cnt"]
                active_fundings = c.execute(
                    "SELECT COUNT(*) as cnt FROM channel_funding WHERE status='active'"
                ).fetchone()["cnt"]
                top_referrers = c.execute(
                    "SELECT invited_by, COUNT(*) as cnt FROM users "
                    "WHERE invited_by IS NOT NULL AND invited_by != 0 AND referral_credited=1 "
                    "GROUP BY invited_by ORDER BY cnt DESC LIMIT 5"
                ).fetchall()
        
            lines = [
                "📊 *إحصائيات البوت:*\n",
                f"👥 إجمالي المستخدمين: {total_users}",
                f"✅ المستخدمون المتحققون: {verified_users}\n",
                f"📦 إجمالي الطلبات: {total_orders}",
                f"🟡 الطلبات الحالية (قيد التنفيذ): {pending_orders}",
                f"🟢 الطلبات المكتملة: {completed_orders}",
                f"🔴 الطلبات الملغاة: {cancelled_orders}\n",
                f"💰 إجمالي النقاط في البوت: {total_pts}",
                f"🎟 أكواد ترويجية نشطة: {total_promos}\n",
                f"📡 قنوات إجبارية نشطة: {active_mandatory} (⏳ بانتظار الدور: {queued_mandatory})",
                f"💸 تمويلات قنوات نشطة حالياً: {active_fundings}\n",
            ]
        
            if top_referrers:
                lines.append("🏆 *الأكثر دعوةً للأصدقاء:*")
                for i, r in enumerate(top_referrers, start=1):
                    inviter = get_user(r["invited_by"])
                    if inviter and inviter.get("username"):
                        name = md_escape(f"@{inviter['username']}")
                    elif inviter and inviter.get("full_name"):
                        name = md_escape(inviter["full_name"])
                    else:
                        name = f"ID {r['invited_by']}"
                    lines.append(f"{i}. {name} — {r['cnt']} دعوة")
            else:
                lines.append("🏆 لا توجد دعوات مكتملة بعد.")
        
            await q.edit_message_text(
                "\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=owner_settings_kb()
            )
            return

        if data == "os:site_balance" and is_own:
            await q.edit_message_text("⏳ جارٍ الاستعلام عن رصيدك في المواقع...")
            lines = ["💵 *رصيد حساباتك في مواقع الرشق:*\n"]
            for panel_id, site in PANEL_MAP.items():
                res = await asyncio.to_thread(smm_request, "balance", panel=panel_id)
                if "error" in res:
                    lines.append(f"❌ *{site['name']}*: تعذّر الاتصال ({res['error']})")
                    continue
                balance  = res.get("balance", "غير معروف")
                currency = res.get("currency", "USD")
                lines.append(f"🌐 *{site['name']}*: {balance} {currency}")
            await q.edit_message_text(
                "\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_kb("owner_settings")
            )
            return

        if data == "os:manage_star_packages" and is_own:
            with db_conn() as c:
                packages = c.execute("SELECT * FROM exchange_star_packages ORDER BY stars").fetchall()
            rate = int(get_setting("exchange_star_rate") or "2000")
            lines = ["📦 *باقات الاستبدال بنجوم:*\n"]
            for pkg in packages:
                status = "✅" if pkg["active"] else "❌"
                cost = pkg["stars"] * rate
                lines.append(f"{status} {pkg['stars']} نجمة = {cost} نقطة")
            rows = []
            for pkg in packages:
                tog = "❌ تعطيل" if pkg["active"] else "✅ تفعيل"
                rows.append([
                    InlineKeyboardButton(f"⭐ {pkg['stars']} نجمة", callback_data="noop"),
                    InlineKeyboardButton(tog, callback_data=f"os_tog_pkg:{pkg['id']}:{0 if pkg['active'] else 1}"),
                    InlineKeyboardButton("🗑", callback_data=f"os_del_pkg:{pkg['id']}")
                ])
            rows.append([InlineKeyboardButton("➕ إضافة باقة", callback_data="os_add_pkg")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
            msg = "\n".join(lines) if len(packages) > 0 else "⭐ لا توجد باقات بعد. اضغط ➕ لإضافة باقة."
            await q.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=InlineKeyboardMarkup(rows))
            return

        if data == "os_add_pkg" and is_own:
            context.user_data["state"] = "os_await_pkg_stars"
            await q.edit_message_text("⭐ *إضافة باقة جديدة*\n\nأرسل عدد النجوم (مثال: 15):",
                                       parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("os_tog_pkg:") and is_own:
            parts = data.split(":")
            pkg_id = int(parts[1])
            val = int(parts[2])
            with db_conn() as c:
                c.execute("UPDATE exchange_star_packages SET active=? WHERE id=?", (val, pkg_id))
                packages = c.execute("SELECT * FROM exchange_star_packages ORDER BY stars").fetchall()
            await q.answer("✅ تم التحديث")
            rate = int(get_setting("exchange_star_rate") or "2000")
            lines = ["📦 *باقات الاستبدال بنجوم:*\n"]
            for pkg in packages:
                status = "✅" if pkg["active"] else "❌"
                cost = pkg["stars"] * rate
                lines.append(f"{status} {pkg['stars']} نجمة = {cost} نقطة")
            rows = []
            for pkg in packages:
                tog = "❌ تعطيل" if pkg["active"] else "✅ تفعيل"
                rows.append([
                    InlineKeyboardButton(f"⭐ {pkg['stars']} نجمة", callback_data="noop"),
                    InlineKeyboardButton(tog, callback_data=f"os_tog_pkg:{pkg['id']}:{0 if pkg['active'] else 1}"),
                    InlineKeyboardButton("🗑", callback_data=f"os_del_pkg:{pkg['id']}")
                ])
            rows.append([InlineKeyboardButton("➕ إضافة باقة", callback_data="os_add_pkg")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
            msg = "\n".join(lines) if len(packages) > 0 else "⭐ لا توجد باقات بعد."
            await q.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("os_del_pkg:") and is_own:
            pkg_id = int(data.split(":")[1])
            with db_conn() as c:
                c.execute("DELETE FROM exchange_star_packages WHERE id=?", (pkg_id,))
            await q.answer("🗑 تم الحذف")
            return

        if data.startswith("exchange:custom:"):
            parts = data.split(":")
            prize_id = int(parts[2])
            confirmed = len(parts) > 3 and parts[3] == "confirm"
            with db_conn() as c:
                prize = c.execute(
                    "SELECT * FROM custom_prizes WHERE id=%s AND active=1", (prize_id,)
                ).fetchone()
            if not prize:
                await q.edit_message_text("⚠️ هذه الجائزة لم تعد متاحة.", reply_markup=back_kb("exchange_points"))
                return
            cost = prize["points_cost"]
            db_user = get_user(user.id)
            pts = db_user["points"] if db_user else 0
            qty_txt = f" × {prize['quantity']}" if prize["quantity"] and prize["quantity"] > 1 else ""
        
            if not confirmed:
                can_afford = pts >= cost
                confirm_kb = [
                    [InlineKeyboardButton(
                        "✅ تأكيد الطلب" if can_afford else "❌ رصيدك غير كافٍ",
                        callback_data=f"exchange:custom:{prize_id}:confirm" if can_afford else "noop"
                    )],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="exchange_points")],
                ]
                await q.edit_message_text(
                    f"🎁 *{prize['name']}{qty_txt}*\n\n"
                    f"💰 التكلفة: *{cost:,} نقطة*\n"
                    f"💎 رصيدك الحالي: {pts:,} نقطة\n\n"
                    + ("✅ يمكنك الطلب — اضغط تأكيد للمتابعة." if can_afford else
                       f"❌ تحتاج {cost - pts:,} نقطة إضافية."),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(confirm_kb)
                )
                return
        
            if pts < cost:
                await q.edit_message_text("❌ رصيدك غير كافٍ!", reply_markup=back_kb("exchange_points"))
                return
            if not deduct_points(user.id, cost):
                await q.edit_message_text("❌ حدث خطأ في خصم النقاط.", reply_markup=back_kb("exchange_points"))
                return
            code = next_order_code(user.id)
            with db_conn() as c:
                pe = c.execute(
                    "INSERT INTO prize_exchanges (user_id,prize_type,prize_value,points_cost,status,order_code) "
                    "VALUES (%s,%s,%s,%s,'pending',%s) RETURNING id",
                    (user.id, "custom", f"{prize['name']}{qty_txt}", cost, code)
                ).fetchone()
            custom_msg = get_setting("exchange_success_msg") or ""
            result_kb = contact_owner_row() + [[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]]
            await q.edit_message_text(
                f"✅ *تمت العملية بنجاح!*\n\n"
                f"🎁 الجائزة: {prize['name']}{qty_txt}\n"
                f"💰 التكلفة: {cost:,} نقطة\n\n"
                + (f"{custom_msg}\n\n" if custom_msg else "")
                + "سيتواصل معك المالك قريباً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(result_kb)
            )
            await context.bot.send_message(
                user.id,
                f"📌 *كود عمليتك:* `{code}`",
                parse_mode=ParseMode.MARKDOWN
            )
            await notify_prize_exchange_owner(
                context, pe["id"],
                f"🎁 <b>طلب جائزة مخصصة</b>\n"
                f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                f"🎀 {prize['name']}{qty_txt}\n"
                f"💰 {cost:,} نقطة\n"
                f"📌 {code}"
            )
            return

        if data.startswith("pe_complete:") and is_own:
            pe_id = int(data.split(":")[1])
            with db_conn() as c:
                pe = c.execute("SELECT * FROM prize_exchanges WHERE id=%s", (pe_id,)).fetchone()
                if not pe:
                    await q.answer("⚠️ الطلب غير موجود.", show_alert=True)
                    return
                if pe["status"] == "completed":
                    await q.answer("✔️ هذا الطلب مكتمل مسبقاً.", show_alert=True)
                    return
                c.execute("UPDATE prize_exchanges SET status='completed', owner_seen=TRUE WHERE id=%s", (pe_id,))
            try:
                await context.bot.send_message(
                    pe["user_id"],
                    f"🎉 *تم تسليم طلبك بنجاح!*\n\n"
                    f"📌 الكود: `{pe['order_code'] or pe_id}`\n"
                    f"نتمنى أن تكون راضياً عن الخدمة 🌟",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.warning(f"⚠️ فشل إشعار المستخدم {pe['user_id']} باكتمال طلب الاستبدال: {e}")
            await q.answer("✅ تم تمييز الطلب كمكتمل وإشعار الطالب.", show_alert=True)
            try:
                await q.edit_message_text(
                    q.message.text_html + "\n\n✅ <b>مكتمل — تم التسليم</b>",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
            return

        if data.startswith("pe_ack:") and is_own:
            pe_id = int(data.split(":")[1])
            with db_conn() as c:
                pe = c.execute("SELECT * FROM prize_exchanges WHERE id=%s", (pe_id,)).fetchone()
            if not pe:
                await q.answer("⚠️ الطلب غير موجود.", show_alert=True)
                return
            if pe["status"] == "completed":
                await q.answer("✔️ هذا الطلب مكتمل مسبقاً.", show_alert=True)
                return
            try:
                await context.bot.send_message(
                    pe["user_id"],
                    "👀 لقد علم المالك بطلبك، سيعطيك حقك بأسرع وقت ممكن 🙏"
                )
            except Exception as e:
                logger.warning(f"⚠️ فشل إشعار المستخدم {pe['user_id']} بانتظار طلب الاستبدال: {e}")
            with db_conn() as _c_ack:
                _c_ack.execute("UPDATE prize_exchanges SET owner_seen=TRUE WHERE id=%s", (pe_id,))
            await q.answer("✅ تم إعلام الطالب بالانتظار.", show_alert=True)
            return

        if data.startswith("pe_seen:") and is_own:
            pe_id = int(data.split(":")[1])
            with db_conn() as c:
                c.execute("UPDATE prize_exchanges SET owner_seen=TRUE WHERE id=%s", (pe_id,))
            await q.answer("✅ تم تسجيل الاطلاع.", show_alert=True)
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            return

        if (data == "os:list_gmail" or data.startswith("os:list_gmail:")) and is_own:
            _gmail_page = 0
            if data.startswith("os:list_gmail:"):
                try:
                    _gmail_page = int(data.split(":")[2])
                except Exception:
                    _gmail_page = 0
            _gmail_limit  = 20
            _gmail_offset = _gmail_page * _gmail_limit
            with db_conn() as c:
                _gmail_total = c.execute("SELECT COUNT(*) AS n FROM gmail_submissions").fetchone()["n"]
                subs = c.execute(
                    "SELECT gs.*, u.points FROM gmail_submissions gs "
                    "LEFT JOIN users u ON u.user_id=gs.user_id "
                    "ORDER BY gs.id DESC LIMIT %s OFFSET %s",
                    (_gmail_limit, _gmail_offset)
                ).fetchall()
            if not subs and _gmail_page == 0:
                await q.edit_message_text("📧 لا توجد طلبات جيميل حتى الآن.", reply_markup=back_kb("owner_settings"))
                return
            rows = []
            for s in subs:
                status_icon = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(s["status"], "❓")
                rows.append([InlineKeyboardButton(
                    f"{status_icon} #{s['id']} — {s['gmail_email']}",
                    callback_data=f"gmail_detail:{s['id']}"
                )])
            # أزرار التنقل
            _nav = []
            if _gmail_page > 0:
                _nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"os:list_gmail:{_gmail_page - 1}"))
            if _gmail_offset + _gmail_limit < _gmail_total:
                _nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"os:list_gmail:{_gmail_page + 1}"))
            if _nav:
                rows.append(_nav)
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
            _start = _gmail_offset + 1
            _end   = min(_gmail_offset + _gmail_limit, _gmail_total)
            await q.edit_message_text(
                f"📧 *طلبات الجيميل* — {_start}–{_end} من {_gmail_total}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return

        if (data == "os:verified_gmail" or data.startswith("os:verified_gmail:")) and is_own:
            _verified_page = 0
            if data.startswith("os:verified_gmail:"):
                try:
                    _verified_page = int(data.split(":")[2])
                except Exception:
                    _verified_page = 0
            _verified_limit = 20
            _verified_offset = _verified_page * _verified_limit
            with db_conn() as c:
                _verified_total = c.execute(
                    "SELECT COUNT(*) AS n FROM gmail_submissions "
                    "WHERE status='rejected' "
                    "AND rejection_reason='need_verify' "
                    "AND COALESCE(verification_completed, FALSE)=TRUE "
                    "AND COALESCE(verification_notified, FALSE)=TRUE"
                ).fetchone()["n"]
                verified_subs = c.execute(
                    "SELECT gs.*, u.points FROM gmail_submissions gs "
                    "LEFT JOIN users u ON u.user_id=gs.user_id "
                    "WHERE gs.status='rejected' "
                    "AND gs.rejection_reason='need_verify' "
                    "AND COALESCE(gs.verification_completed, FALSE)=TRUE "
                    "AND COALESCE(gs.verification_notified, FALSE)=TRUE "
                    "ORDER BY gs.id DESC LIMIT %s OFFSET %s",
                    (_verified_limit, _verified_offset),
                ).fetchall()
            if not verified_subs and _verified_page == 0:
                await q.edit_message_text(
                    "🔐 لا توجد حسابات أكملت التحقق بانتظار المراجعة.",
                    reply_markup=back_kb("owner_settings"),
                )
                return
            rows = []
            for s in verified_subs:
                rows.append([InlineKeyboardButton(
                    f"🔐 #{s['id']} — {s['gmail_email']}",
                    callback_data=f"gmail_detail:{s['id']}:verified",
                )])
            _nav = []
            if _verified_page > 0:
                _nav.append(InlineKeyboardButton(
                    "◀️ السابق",
                    callback_data=f"os:verified_gmail:{_verified_page - 1}",
                ))
            if _verified_offset + _verified_limit < _verified_total:
                _nav.append(InlineKeyboardButton(
                    "التالي ▶️",
                    callback_data=f"os:verified_gmail:{_verified_page + 1}",
                ))
            if _nav:
                rows.append(_nav)
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
            _start = _verified_offset + 1
            _end = min(_verified_offset + _verified_limit, _verified_total)
            await q.edit_message_text(
                f"🔐 *حسابات التحقق* — {_start}–{_end} من {_verified_total}\n\n"
                "هذه الحسابات أتمّ أصحابها التحقق وتحتاج قرار المالك.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows),
            )
            return

        if data.startswith("gmail_detail:") and is_own:
            context.user_data.pop("gmail_verification_note_edit_sub_id", None)
            _detail_parts = data.split(":")
            sub_id = int(_detail_parts[1])
            _detail_source = _detail_parts[2] if len(_detail_parts) > 2 else "all"
            with db_conn() as c:
                sub = c.execute("SELECT * FROM gmail_submissions WHERE id=%s", (sub_id,)).fetchone()
            if not sub:
                await q.answer("❌ الطلب غير موجود.", show_alert=True)
                return
            status_text = {"pending": "⏳ قيد الانتظار", "approved": "✅ مقبول", "rejected": "❌ مرفوض"}.get(sub["status"], sub["status"])
            verification_note = html.escape((sub.get("verification_note") or "").strip()) or "لا توجد ملاحظة."
            text_html = (
                f"📧 <b>تفاصيل طلب #{sub['id']}</b>\n\n👤 <a href='tg://user?id={sub['user_id']}'>المستخدم</a> | 🆔 {sub['user_id']}\n📬 الإيميل: <code>{sub['gmail_email']}</code>\n🔐 الباسورد: <code>{sub['gmail_pass']}</code>\n💬 <b>رسالة التحقق:</b>\n<code>{verification_note}</code>\n📊 الحالة: {status_text}\n🕐 {sub['created_at']}"
            )
            detail_rows = []
            _is_verified_pending = (
                sub["status"] == "rejected"
                and sub.get("rejection_reason") == "need_verify"
                and bool(sub.get("verification_completed"))
                and bool(sub.get("verification_notified"))
            )
            if sub["status"] == "pending" or _is_verified_pending:
                gmail_reward = int(get_setting("gmail_points_reward") or "10000")
                detail_rows.append([InlineKeyboardButton(f"✅ قبول وإعطاء {gmail_reward:,} نقطة", callback_data=f"gmail_approve:{sub_id}")])
                _reject_callback = (
                    f"gmail_reject:{sub_id}:verified"
                    if _is_verified_pending
                    else f"gmail_reject:{sub_id}"
                )
                detail_rows.append([InlineKeyboardButton("❌ رفض", callback_data=_reject_callback)])
            detail_rows.append([InlineKeyboardButton(
                "✏️ تعديل رسالة التحقق",
                callback_data=f"gmail_edit_verification_note:{sub_id}",
            )])
            _detail_back = "os:verified_gmail" if _detail_source == "verified" else "os:list_gmail"
            detail_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=_detail_back)])
            await q.edit_message_text(text_html, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(detail_rows))
            return

        if data.startswith("gmail_edit_verification_note:") and is_own:
            sub_id = int(data.split(":")[1])
            with db_conn() as c:
                sub = c.execute(
                    "SELECT id, verification_note FROM gmail_submissions WHERE id=%s",
                    (sub_id,),
                ).fetchone()
            if not sub:
                await q.answer("❌ الطلب غير موجود.", show_alert=True)
                return
            context.user_data["state"] = "os_await_gmail_verification_note_edit"
            context.user_data["gmail_verification_note_edit_sub_id"] = sub_id
            await q.edit_message_text(
                "✏️ <b>تعديل رسالة التحقق</b>\n\n"
                f"النص الحالي:\n{html.escape(sub.get('verification_note') or '')}\n\n"
                "أرسل النص الجديد:",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🔙 إلغاء",
                        callback_data=f"gmail_detail:{sub_id}",
                    )
                ]]),
            )
            return

        if data == "os:edit_gmail_reward" and is_own:
            cur = get_setting("gmail_points_reward") or "10000"
            context.user_data["state"] = "os_await_gmail_reward"
            await q.edit_message_text(
                f"⚙️ نقاط طلب الجيميل الحالية: {cur}\n\nأرسل القيمة الجديدة:"
            )
            return

        if data == "os:edit_gmail_msg" and is_own:
            cur = get_setting("gmail_intro_message") or ""
            context.user_data["state"] = "os_await_gmail_msg"
            await q.edit_message_text(
                f"✏️ نص رسالة الجيميل الحالية:\n{cur}\n\nأرسل النص الجديد:"
            )
            return

        if data == "os:edit_gmail_btn_label" and is_own:
            cur = get_setting("gmail_button_label") or "📧 احصل على نقاط مقابل إيميل جيميل"
            context.user_data["state"] = "os_await_gmail_btn_label"
            await q.edit_message_text(
                f"🏷 اسم زر الإيميل الحالي:\n{cur}\n\nأرسل الاسم الجديد للزر:"
            )
            return

        if data == "os:edit_gmail_email_prompt" and is_own:
            cur = get_setting("gmail_email_prompt") or "📧 *أرسل الإيميل*"
            context.user_data["state"] = "os_await_gmail_email_prompt"
            await q.edit_message_text(
                f"📨 رسالة طلب الإيميل الحالية:\n{cur}\n\nأرسل الرسالة الجديدة:"
            )
            return

        if data == "os:edit_gmail_pass_prompt" and is_own:
            cur = get_setting("gmail_password_prompt") or "🔐 *أرسل الباسورد*"
            context.user_data["state"] = "os_await_gmail_pass_prompt"
            await q.edit_message_text(
                f"🔑 رسالة طلب الباسورد الحالية:\n{cur}\n\nأرسل الرسالة الجديدة:"
            )
            return

        if data == "os:edit_gmail_verification_note_prompt" and is_own:
            cur = get_setting("gmail_verification_note_prompt") or (
                "💬 <b>اكتب رسالتك للمالك</b>\n\n"
                "يجب كتابة ملاحظة قبل إرسال إشعار إكمال التحقق."
            )
            context.user_data["state"] = "os_await_gmail_verification_note_prompt"
            await q.edit_message_text(
                f"💬 نص طلب ملاحظة التحقق الحالي:\n\n{cur}\n\nأرسل النص الجديد:",
                parse_mode=ParseMode.HTML,
            )
            return

        if data == "os:edit_gmail_logout_instructions" and is_own:
            cur = get_setting("gmail_logout_instructions") or (
                "🔒 <b>خطوة مهمة لحماية حسابك</b>\n\n"
                "بعد إرسال الملاحظة، سجّل الخروج من حساب Google:\n\n"
                "1. افتح Gmail أو حساب Google.\n"
                "2. اضغط على صورة الحساب.\n"
                "3. اختر <b>تسجيل الخروج</b>.\n"
                "4. إذا كنت تستخدم جهازاً مشتركاً، افتح إدارة حساب Google ثم قسم الأمان، "
                "وراجع الأجهزة المسجّل دخولها وأزل الجهاز عند الحاجة."
            )
            context.user_data["state"] = "os_await_gmail_logout_instructions"
            await q.edit_message_text(
                f"🔒 تعليمات تسجيل الخروج الحالية:\n\n{cur}\n\nأرسل النص الجديد:",
                parse_mode=ParseMode.HTML,
            )
            return

        if data == "os:edit_reject_pass_video" and is_own:
            cur_vid = get_setting("gmail_reject_wrong_pass_video") or "غير محدد"
            has_vid = "✅ محدد" if (cur_vid and cur_vid != "غير محدد") else "❌ لم يُحدد بعد"
            context.user_data["state"] = "os_await_reject_pass_video"
            await q.edit_message_text(
                f"📹 <b>فيديو رفض: باسورد خطأ</b>\n\nالحالة: {has_vid}\n\nأرسل الفيديو الجديد الآن:",
                parse_mode=ParseMode.HTML
            )
            return

        if data == "os:edit_reject_pass_caption" and is_own:
            cur = get_setting("gmail_reject_wrong_pass_caption") or ""
            context.user_data["state"] = "os_await_reject_pass_caption"
            await q.edit_message_text(
                f"✏️ <b>نص رفض: باسورد خطأ</b>\n\nالنص الحالي:\n{cur}\n\nأرسل النص الجديد:",
                parse_mode=ParseMode.HTML
            )
            return

        if data == "os:edit_reject_verify_video" and is_own:
            cur_vid = get_setting("gmail_reject_need_verify_video") or "غير محدد"
            has_vid = "✅ محدد" if (cur_vid and cur_vid != "غير محدد") else "❌ لم يُحدد بعد"
            context.user_data["state"] = "os_await_reject_verify_video"
            await q.edit_message_text(
                f"📹 <b>فيديو رفض: يحتاج تحقق</b>\n\nالحالة: {has_vid}\n\nأرسل الفيديو الجديد الآن:",
                parse_mode=ParseMode.HTML
            )
            return

        if data == "os:edit_reject_verify_caption" and is_own:
            cur = get_setting("gmail_reject_need_verify_caption") or ""
            context.user_data["state"] = "os_await_reject_verify_caption"
            await q.edit_message_text(
                f"✏️ <b>نص رفض: يحتاج تحقق</b>\n\nالنص الحالي:\n{cur}\n\nأرسل النص الجديد:",
                parse_mode=ParseMode.HTML
            )
            return

        if data == "os:edit_reject_email_msg" and is_own:
            cur = get_setting("gmail_reject_wrong_email_msg") or ""
            context.user_data["state"] = "os_await_reject_email_msg"
            await q.edit_message_text(
                f"✏️ <b>رسالة رفض: إيميل خطأ</b>\n\nالرسالة الحالية:\n{cur}\n\nأرسل الرسالة الجديدة:",
                parse_mode=ParseMode.HTML
            )
            return

        if data.startswith("gmail_approve:") and is_own:
            sub_id = int(data.split(":")[1])
            with db_conn() as c:
                sub = c.execute("SELECT * FROM gmail_submissions WHERE id=%s", (sub_id,)).fetchone()
            if not sub:
                await q.answer("❌ الطلب غير موجود.", show_alert=True)
                return
            _is_verified_pending = (
                sub["status"] == "rejected"
                and sub.get("rejection_reason") == "need_verify"
                and bool(sub.get("verification_completed"))
                and bool(sub.get("verification_notified"))
            )
            if sub["status"] != "pending" and not _is_verified_pending:
                await q.answer("⚠️ هذا الطلب معالَج مسبقاً.", show_alert=True)
                return
            gmail_reward = int(get_setting("gmail_points_reward") or "10000")
            with db_conn() as c:
                c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (gmail_reward, sub["user_id"]))
                c.execute(
                    "UPDATE gmail_submissions SET status='approved', rejection_reason='', "
                    "verification_completed=FALSE, verification_notified=FALSE WHERE id=%s",
                    (sub_id,),
                )
            try:
                await context.bot.send_message(
                    sub["user_id"],
                    f"🎉 *تمت الموافقة على طلبك!*\n\n"
                    f"✅ تم إضافة *{gmail_reward:,} نقطة* إلى رصيدك.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.warning(f"gmail approve notify user error: {e}")
            gmail_reward_val = gmail_reward
            await q.edit_message_text(
                q.message.text_html + f"\n\n✅ <b>تمت الموافقة وأُضيفت {gmail_reward_val:,} نقطة.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"↩️ تراجع — خصم {gmail_reward_val:,} نقطة",
                                          callback_data=f"gmail_undo_approve:{sub_id}")]
                ])
            )
            return

        if data.startswith("gmail_undo_approve:") and is_own:
            sub_id = int(data.split(":")[1])
            with db_conn() as c:
                sub = c.execute("SELECT * FROM gmail_submissions WHERE id=%s", (sub_id,)).fetchone()
            if not sub:
                await q.answer("❌ الطلب غير موجود.", show_alert=True)
                return
            if sub["status"] != "approved":
                await q.answer("⚠️ لا يمكن التراجع — الطلب ليس في حالة مقبول.", show_alert=True)
                return
            gmail_reward = int(get_setting("gmail_points_reward") or "10000")
            with db_conn() as c:
                c.execute("UPDATE users SET points=GREATEST(0, points-%s) WHERE user_id=%s",
                          (gmail_reward, sub["user_id"]))
                c.execute("UPDATE gmail_submissions SET status='pending' WHERE id=%s", (sub_id,))
            try:
                await context.bot.send_message(
                    sub["user_id"],
                    f"⚠️ *تم التراجع عن قبول طلبك*\n\n"
                    f"تم خصم *{gmail_reward:,} نقطة* من رصيدك. سيتم مراجعة الحساب مجدداً.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as _ue:
                logger.warning(f"gmail undo approve notify error: {_ue}")
            await q.edit_message_text(
                q.message.text_html + "\n\n↩️ <b>تم التراجع وخُصمت النقاط — الطلب عاد إلى الانتظار.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"✅ إتمام العملية وإعطاء {gmail_reward:,} نقطة",
                                          callback_data=f"gmail_approve:{sub_id}")],
                    [InlineKeyboardButton("❌ رفض العملية", callback_data=f"gmail_reject:{sub_id}")],
                ])
            )
            return

        if data.startswith("gmail_reject:") and is_own:
            _reject_parts = data.split(":")
            sub_id = int(_reject_parts[1])
            _reject_source = _reject_parts[2] if len(_reject_parts) > 2 else "all"
            with db_conn() as c:
                sub = c.execute("SELECT * FROM gmail_submissions WHERE id=%s", (sub_id,)).fetchone()
            if not sub:
                await q.answer("❌ الطلب غير موجود.", show_alert=True)
                return
            _is_verified_pending = (
                sub["status"] == "rejected"
                and sub.get("rejection_reason") == "need_verify"
                and bool(sub.get("verification_completed"))
                and bool(sub.get("verification_notified"))
            )
            if sub["status"] != "pending" and not _is_verified_pending:
                await q.answer("⚠️ هذا الطلب معالَج مسبقاً.", show_alert=True)
                return
            user_link = f"tg://user?id={sub['user_id']}"
            _reject_back = (
                f"gmail_detail:{sub_id}:verified"
                if _reject_source == "verified"
                else f"gmail_detail:{sub_id}"
            )
            await q.edit_message_text(
                f"❌ <b>رفض طلب الجيميل</b>\n\n👤 <a href='{user_link}'>المستخدم</a> | 🆔 {sub['user_id']}\n\nاختر سبب الرفض:",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ إيميل خطأ", callback_data=f"gmail_reject_reason:wrong_email:{sub_id}")],
                    [InlineKeyboardButton("🔑 باسورد خطأ", callback_data=f"gmail_reject_reason:wrong_pass:{sub_id}")],
                    [InlineKeyboardButton("🔐 يحتاج تحقق", callback_data=f"gmail_reject_reason:need_verify:{sub_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=_reject_back)],
                ])
            )
            return

        if data.startswith("gmail_reject_reason:") and is_own:
            parts = data.split(":")
            reason = parts[1]   # wrong_email / wrong_pass / need_verify
            sub_id = int(parts[2])
            with db_conn() as c:
                sub = c.execute("SELECT * FROM gmail_submissions WHERE id=%s", (sub_id,)).fetchone()
            if not sub:
                await q.answer("❌ الطلب غير موجود.", show_alert=True)
                return
            _is_verified_pending = (
                sub["status"] == "rejected"
                and sub.get("rejection_reason") == "need_verify"
                and bool(sub.get("verification_completed"))
                and bool(sub.get("verification_notified"))
            )
            if sub["status"] != "pending" and not _is_verified_pending:
                await q.answer("⚠️ هذا الطلب معالَج مسبقاً.", show_alert=True)
                return
            with db_conn() as c:
                c.execute(
                    "UPDATE gmail_submissions SET status='rejected', "
                    "rejection_reason=%s, verification_completed=FALSE, "
                    "verification_notified=FALSE WHERE id=%s",
                    (reason, sub_id)
                )
            reason_labels = {
                "wrong_email":  "❌ إيميل خطأ",
                "wrong_pass":   "🔑 باسورد خطأ",
                "need_verify":  "🔐 يحتاج تحقق",
            }
            reason_label = reason_labels.get(reason, reason)
            user_link = f"tg://user?id={sub['user_id']}"
            # ── إخطار العضو حسب السبب ──
            try:
                if reason == "wrong_email":
                    msg_text = get_setting("gmail_reject_wrong_email_msg") or "❌ تم رفض طلبك بسبب أن الإيميل خاطئ."
                    await context.bot.send_message(
                        sub["user_id"],
                        f"❌ *تم رفض طلبك*\n\n"
                        f"{msg_text}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                elif reason == "wrong_pass":
                    caption = get_setting("gmail_reject_wrong_pass_caption") or "❌ تم رفض طلبك بسبب أن كلمة المرور خاطئة."
                    video_id = get_setting("gmail_reject_wrong_pass_video") or ""
                    if video_id:
                        await context.bot.send_video(
                            sub["user_id"],
                            video=video_id,
                            caption=caption,
                            parse_mode=ParseMode.MARKDOWN
                        )
                    else:
                        await context.bot.send_message(
                            sub["user_id"],
                            f"❌ *تم رفض طلبك*\n\n"
                            f"{caption}",
                            parse_mode=ParseMode.MARKDOWN
                        )
                elif reason == "need_verify":
                    caption = get_setting("gmail_reject_need_verify_caption") or "❌ تم رفض طلبك لأن الحساب يحتاج تحقق."
                    video_id = get_setting("gmail_reject_need_verify_video") or ""
                    if video_id:
                        await context.bot.send_video(
                            sub["user_id"],
                            video=video_id,
                            caption=caption,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton(
                                    "🔐 التحقق",
                                    callback_data=f"totp_generator:{sub_id}"
                                )
                            ]])
                        )
                    else:
                        await context.bot.send_message(
                            sub["user_id"],
                            f"❌ *تم رفض طلبك*\n\n"
                            f"{caption}",
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton(
                                    "🔐 التحقق",
                                    callback_data=f"totp_generator:{sub_id}"
                                )
                            ]])
                        )
            except Exception as _rr_e:
                logger.warning(f"gmail_reject_reason notify error: {_rr_e}")
            _rj_reward = int(get_setting("gmail_points_reward") or "10000")
            await q.edit_message_text(
                q.message.text_html + f"\n\n{reason_label} — ✅ <b>تم الرفض وإبلاغ العضو.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        f"↩️ تراجع — إعطاء {_rj_reward:,} نقطة وقبول الطلب",
                        callback_data=f"gmail_undo_reject:{sub_id}"
                    )],
                ])
            )
            return

        if data.startswith("gmail_undo_reject:") and is_own:
            sub_id = int(data.split(":")[1])
            with db_conn() as c:
                sub = c.execute("SELECT * FROM gmail_submissions WHERE id=%s", (sub_id,)).fetchone()
            if not sub:
                await q.answer("❌ الطلب غير موجود.", show_alert=True)
                return
            if sub["status"] != "rejected":
                await q.answer("⚠️ لا يمكن التراجع — الطلب ليس في حالة مرفوض.", show_alert=True)
                return
            gmail_reward = int(get_setting("gmail_points_reward") or "10000")
            with db_conn() as c:
                c.execute("UPDATE users SET points=points+%s WHERE user_id=%s",
                          (gmail_reward, sub["user_id"]))
                c.execute(
                    "UPDATE gmail_submissions SET status='approved', rejection_reason='', "
                    "verification_completed=FALSE, verification_notified=FALSE WHERE id=%s",
                    (sub_id,)
                )
            try:
                await context.bot.send_message(
                    sub["user_id"],
                    f"🎉 *تم التراجع عن رفض طلبك وقبوله!*\n\n"
                    f"✅ تم إضافة *{gmail_reward:,} نقطة* إلى رصيدك.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as _ure:
                logger.warning(f"gmail undo reject notify error: {_ure}")
            await q.edit_message_text(
                q.message.text_html + f"\n\n↩️ <b>تم التراجع عن الرفض — أُضيفت {gmail_reward:,} نقطة وقُبل الطلب.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"↩️ تراجع — خصم {gmail_reward:,} نقطة",
                                          callback_data=f"gmail_undo_approve:{sub_id}")]
                ])
            )
            return

        if (data == "os:all_gmail_history" or data.startswith("os:all_gmail_history:")) and is_own:
            # os:all_gmail_history              → شاشة الفلتر
            # os:all_gmail_history:STATUS:PAGE  → النتائج
            _parts = data.split(":")
            if len(_parts) < 4:
                # شاشة اختيار الفلتر — نعرض عدد كل فئة
                with db_conn() as c:
                    _counts = {r["status"]: r["n"] for r in c.execute(
                        "SELECT status, COUNT(*) AS n FROM gmail_submissions GROUP BY status"
                    ).fetchall()}
                _ap = _counts.get("approved", 0)
                _rj = _counts.get("rejected", 0)
                _pn = _counts.get("pending",  0)
                await q.edit_message_text(
                    "📧 <b>إيميلات جميع المستخدمين</b>\n\nاختر الفئة التي تريد عرضها:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"✅ المقبولة ({_ap})",  callback_data="os:all_gmail_history:approved:0")],
                        [InlineKeyboardButton(f"❌ المرفوضة ({_rj})", callback_data="os:all_gmail_history:rejected:0")],
                        [InlineKeyboardButton(f"⏳ المنتظرة ({_pn})", callback_data="os:all_gmail_history:pending:0")],
                        [InlineKeyboardButton("🔙 رجوع",              callback_data="owner_settings")],
                    ])
                )
                return
            # عرض النتائج بعد اختيار الفلتر
            _status = _parts[2]
            try: _page = int(_parts[3])
            except Exception: _page = 0
            _limit  = 15
            _offset = _page * _limit
            _label  = {"approved": "✅ المقبولة", "rejected": "❌ المرفوضة", "pending": "⏳ المنتظرة"}.get(_status, _status)
            with db_conn() as c:
                _total = c.execute(
                    "SELECT COUNT(*) AS n FROM gmail_submissions WHERE status=%s", (_status,)
                ).fetchone()["n"]
                _subs = c.execute(
                    "SELECT gs.gmail_email, gs.user_id, u.username, u.full_name "
                    "FROM gmail_submissions gs LEFT JOIN users u ON u.user_id=gs.user_id "
                    "WHERE gs.status=%s ORDER BY gs.id DESC LIMIT %s OFFSET %s",
                    (_status, _limit, _offset)
                ).fetchall()
            if not _subs:
                await q.edit_message_text(
                    f"📭 لا توجد إيميلات في فئة {_label}.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:all_gmail_history")]])
                )
                return
            lines = []
            for s in _subs:
                name = s["full_name"] or s["username"] or str(s["user_id"])
                _uid   = s["user_id"]
                _email = s["gmail_email"]
                lines.append(f"• <a href='tg://user?id={_uid}'>{name}</a>\n  <code>{_email}</code>")
            _nav = []
            if _page > 0:
                _nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"os:all_gmail_history:{_status}:{_page-1}"))
            if _offset + _limit < _total:
                _nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"os:all_gmail_history:{_status}:{_page+1}"))
            _rows = []
            if _nav: _rows.append(_nav)
            _rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:all_gmail_history")])
            _start = _offset + 1
            _end   = min(_offset + _limit, _total)
            await q.edit_message_text(
                f"📧 <b>{_label}</b> — {_start}–{_end} من {_total}\n\n" + "\n\n".join(lines),
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(_rows)
            )
            return

        if data == "os:manage_prizes" and is_own:
            with db_conn() as c:
                prizes = c.execute("SELECT * FROM custom_prizes ORDER BY id").fetchall()
            rows = []
            for p in prizes:
                st = "✅" if p["active"] else "❌"
                rows.append([
                    InlineKeyboardButton(
                        f"{st} {p['name']} × {p['quantity']} — {p['points_cost']:,} نقطة",
                        callback_data=f"os:toggle_prize:{p['id']}"
                    ),
                    InlineKeyboardButton("🗑", callback_data=f"os:del_prize:{p['id']}")
                ])
            rows.append([InlineKeyboardButton("➕ إضافة جائزة جديدة", callback_data="os:add_prize")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
            txt = "🎀 *الجوائز المخصصة:*\n\nاضغط على الجائزة لتفعيل/تعطيل · 🗑 للحذف" if prizes else "🎀 لا توجد جوائز مخصصة بعد."
            await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows))
            return

        if data == "os:add_prize" and is_own:
            context.user_data["state"] = "os_await_prize_name"
            await q.edit_message_text(
                "🎀 *إضافة جائزة مخصصة*\n\n"
                "الخطوة 1/2 — أرسل *اسم الجائزة*:\n"
                "مثال: `اسيا سيل 500` أو `بطاقة شحن`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "os:skip_prize_qty" and is_own:
            context.user_data["prize_qty"] = 1
            context.user_data["state"] = "os_await_prize_cost"
            name = context.user_data.get("prize_name", "")
            await q.edit_message_text(
                f"🎀 *الجائزة:* {name}\n\n"
                f"الخطوة 2/2 — أرسل *عدد النقاط* اللازمة للحصول عليها:\n"
                f"مثال: `1000`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data.startswith("os:toggle_prize:") and is_own:
            pid = int(data.split(":")[2])
            with db_conn() as c:
                c.execute("UPDATE custom_prizes SET active = 1-active WHERE id=%s", (pid,))
            await q.answer("✅ تم التحديث")
            with db_conn() as c:
                prizes = c.execute("SELECT * FROM custom_prizes ORDER BY id").fetchall()
            rows = []
            for p in prizes:
                st = "✅" if p["active"] else "❌"
                rows.append([
                    InlineKeyboardButton(
                        f"{st} {p['name']} × {p['quantity']} — {p['points_cost']:,} نقطة",
                        callback_data=f"os:toggle_prize:{p['id']}"
                    ),
                    InlineKeyboardButton("🗑", callback_data=f"os:del_prize:{p['id']}")
                ])
            rows.append([InlineKeyboardButton("➕ إضافة جائزة جديدة", callback_data="os:add_prize")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
            await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("os:del_prize:") and is_own:
            pid = int(data.split(":")[2])
            with db_conn() as c:
                c.execute("DELETE FROM custom_prizes WHERE id=%s", (pid,))
            await q.answer("🗑 تم الحذف")
            with db_conn() as c:
                prizes = c.execute("SELECT * FROM custom_prizes ORDER BY id").fetchall()
            rows = []
            for p in prizes:
                st = "✅" if p["active"] else "❌"
                rows.append([
                    InlineKeyboardButton(
                        f"{st} {p['name']} × {p['quantity']} — {p['points_cost']:,} نقطة",
                        callback_data=f"os:toggle_prize:{p['id']}"
                    ),
                    InlineKeyboardButton("🗑", callback_data=f"os:del_prize:{p['id']}")
                ])
            rows.append([InlineKeyboardButton("➕ إضافة جائزة جديدة", callback_data="os:add_prize")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
            txt = "🎀 *الجوائز المخصصة:*\n\nاضغط على الجائزة لتفعيل/تعطيل · 🗑 للحذف" if prizes else "🎀 لا توجد جوائز مخصصة بعد."
            await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("buyer:request_code:"):
            number_for_code = data[len("buyer:request_code:"):]
            import datetime as _dt_rc
        
            _purchase_time = None
            _session_str_rc = None
            try:
                with db_conn() as _rdb:
                    _rrow = _rdb.execute(
                        """SELECT pe.created_at, ns.session_string
                       FROM prize_exchanges pe
                       JOIN number_stock ns ON ns.phone_number = pe.prize_value
                       WHERE pe.prize_value=%s AND pe.user_id=%s AND pe.status='completed'
                       ORDER BY pe.created_at DESC LIMIT 1""",
                        (number_for_code, user.id)
                    ).fetchone()
                if _rrow:
                    _session_str_rc = _rrow["session_string"]
                    try:
                        _purchase_time = _dt_rc.datetime.fromisoformat(str(_rrow["created_at"]).replace("Z", "+00:00"))
                        if _purchase_time.tzinfo is None:
                            _purchase_time = _purchase_time.replace(tzinfo=_dt_rc.timezone.utc)
                    except Exception:
                        _purchase_time = None
            except Exception:
                pass
        
            if not _session_str_rc:
                _demo_entry = _demo_purchases.get(user.id)
                if _demo_entry and _demo_entry.get("phone") == number_for_code:
                    _session_str_rc = _demo_entry["session_str"]
                    _purchase_time  = _demo_entry["purchase_time"]
                else:
                    await q.answer("❌ لا يوجد رقم مشترى باسمك بهذا الرقم.", show_alert=True)
                    return
        
            async def _send_code_msg(code_val: str):
                """يرسل كود الدخول فقط — رمز 2FA يُطلب بزر منفصل."""
                await q.answer("✅ تم إرسال الكود أدناه", show_alert=False)
                await context.bot.send_message(
                    chat_id=user.id,
                    text=(
                        f"🔑 *كود الدخول*\n\n"
                        f"`{code_val}`\n\n"
                        f"📱 للرقم: `{number_for_code.lstrip('+')}`\n\n"
                        f"⚠️ لا تشاركه مع أحد — صالح لدقائق فقط."
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                )
        
            entry = _buyer_received_codes.get(user.id)
            if entry and entry.get("phone") == number_for_code:
                code_time = entry.get("time", 0)
                purchase_ts = _purchase_time.timestamp() if _purchase_time else 0
                if code_time >= purchase_ts:
                    await _send_code_msg(entry["code"])
                    return
        
            fetched_code = None
            try:
                if TELEGRAM_API_ID and TELEGRAM_API_HASH:
                    _fcli = TelegramClient(
                        StringSession(_session_str_rc),
                        int(TELEGRAM_API_ID), TELEGRAM_API_HASH
                    )
                    await asyncio.wait_for(_fcli.connect(), timeout=15)
                    try:
                        if await asyncio.wait_for(_fcli.is_user_authorized(), timeout=8):
                            raw_msg, _raw_msg_date = await fetch_last_login_code(_fcli, after_date=_purchase_time)
                            if raw_msg:
                                _m5 = re.search(r'\b(\d{5})\b', raw_msg)   # 5 أرقام بالضبط
                                if not _m5:
                                    _m5 = re.search(r'(\d{4,7})', raw_msg)  # fallback
                                if _m5:
                                    fetched_code = _m5.group(1)
                    finally:
                        try:
                            await _fcli.disconnect()
                        except Exception:
                            pass
            except Exception as _fe:
                logger.warning(f"⚠️ تعذّر جلب كود الدخول للرقم {number_for_code}: {_fe}")
        
            if fetched_code:
                _buyer_received_codes[user.id] = {
                    "code": fetched_code, "time": time.time(), "phone": number_for_code
                }
                await _send_code_msg(fetched_code)
            else:
                await q.answer(
                    "⏳ لم يصل أي كود بعد.\n\n"
                    "افتح تيليجرام على جهازك، أدخل الرقم واطلب كود الدخول، ثم اضغط الزر مجدداً.",
                    show_alert=True
                )
            return

        if data.startswith("buyer:show_twofa:"):
            twofa_phone = data[len("buyer:show_twofa:"):]
            try:
                with db_conn() as _twdb:
                    _twrow = _twdb.execute(
                        """SELECT ns.twofa_password FROM number_stock ns
                       WHERE ns.phone_number=%s
                         AND EXISTS (
                             SELECT 1 FROM prize_exchanges pe
                             WHERE pe.prize_value=%s
                               AND pe.user_id=%s
                               AND pe.status='completed'
                         )""",
                        (twofa_phone, twofa_phone, user.id)
                    ).fetchone()
                _twofa_val = (_twrow["twofa_password"] or "").strip() if _twrow else ""
                if not _twofa_val:
                    _demo_entry_twofa = _demo_purchases.get(user.id)
                    if _demo_entry_twofa and _demo_entry_twofa.get("phone") == twofa_phone:
                        _twofa_val = _demo_entry_twofa.get("twofa", "")
                if _twofa_val:
                    await q.answer("✅ تم إرسال رمز التحقق أدناه", show_alert=False)
                    await context.bot.send_message(
                        chat_id=user.id,
                        text=(
                            f"🔐 *رمز التحقق (المصادقة الثنائية)*\n\n"
                            f"`{_twofa_val}`\n\n"
                            f"📱 للرقم: `{twofa_phone.lstrip('+')}`\n\n"
                            f"⚠️ لا تشاركه مع أحد."
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    await q.answer("⚠️ لا يوجد رمز تحقق ثنائي مضبوط لهذا الرقم.", show_alert=True)
            except Exception as _twe:
                logger.warning(f"⚠️ خطأ في جلب رمز التحقق: {_twe}")
                await q.answer("❌ حدث خطأ. حاول مجدداً.", show_alert=True)
            return

        if data == "buyer:stay_account":
            await q.answer("✅ البوت سيبقى متصلاً بالحساب.", show_alert=True)
            return

        if data.startswith("buyer:leave_account:"):
            leave_phone = data[len("buyer:leave_account:"):]
            with db_conn() as c_lv:
                row_lv = c_lv.execute(
                    "SELECT id, session_string, assigned_to FROM number_stock WHERE phone_number=%s", (leave_phone,)
                ).fetchone()
                was_buyer = c_lv.execute(
                    "SELECT id FROM prize_exchanges WHERE user_id=%s AND prize_value=%s "
                    "AND prize_type IN ('telegram_number','telegram_number_code','telegram_number_stars') AND status='completed'",
                    (user.id, leave_phone)
                ).fetchone()
            if not row_lv or (row_lv["assigned_to"] != user.id and not was_buyer):
                await q.answer("⚠️ لا تملك صلاحية تنفيذ هذا الإجراء.", show_alert=True)
                return
            _sess_lv = None
            try:
                with db_conn() as c_lv_s:
                    _r_lv = c_lv_s.execute(
                        "SELECT session_string FROM number_stock WHERE phone_number=%s", (leave_phone,)
                    ).fetchone()
                    if _r_lv:
                        _sess_lv = _r_lv["session_string"]
            except Exception:
                pass
            _lo_ok = False
            if _sess_lv and TELEGRAM_API_ID and TELEGRAM_API_HASH:
                try:
                    _lo_cli = TelegramClient(
                        StringSession(_sess_lv),
                        int(TELEGRAM_API_ID), TELEGRAM_API_HASH
                    )
                    await asyncio.wait_for(_lo_cli.connect(), timeout=15)
                    await asyncio.wait_for(_lo_cli.log_out(), timeout=15)
                    _lo_ok = True
                    logger.info(f"✅ buyer:leave_account: سجّل البوت خروجه من {leave_phone} بنجاح")
                except Exception as _lo_err:
                    logger.warning(f"⚠️ buyer:leave_account: فشل log_out للرقم {leave_phone}: {_lo_err}")
            with db_conn() as c_lv2:
                c_lv2.execute(
                    "UPDATE number_stock SET assigned_to=NULL, assigned_at=NULL, force_listed=FALSE "
                    "WHERE phone_number=%s", (leave_phone,)
                )
            _buyer_received_codes.pop(user.id, None)
            _msg_lv = (
                "✅ *تم بنجاح!* البوت غادر الحساب وأنهى جلسته نهائياً.\n\nالحساب أصبح بيدك كاملاً 🤍"
                if _lo_ok else
                "⚠️ *تعذّر تسجيل الخروج تلقائياً.*\n\nتواصل مع المالك لإنهاء الجلسة يدوياً."
            )
            await q.edit_message_text(_msg_lv, parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("buyer:barcode:"):
            barcode_phone = data[len("buyer:barcode:"):]
            _is_buyer_bc = False
            try:
                with db_conn() as _bc_db:
                    _bc_row = _bc_db.execute(
                        "SELECT 1 FROM prize_exchanges "
                        "WHERE prize_value=%s AND user_id=%s AND status='completed' LIMIT 1",
                        (barcode_phone, user.id)
                    ).fetchone()
                    if _bc_row:
                        _is_buyer_bc = True
            except Exception:
                pass
            if not _is_buyer_bc:
                _demo_bc = _demo_purchases.get(user.id)
                if _demo_bc and _demo_bc.get("phone") == barcode_phone:
                    _is_buyer_bc = True
            if not _is_buyer_bc:
                await q.answer("❌ لا تملك صلاحية عرض باركود هذا الرقم.", show_alert=True)
                return
            try:
                import qrcode as _qr_mod
                import io as _io_mod
                _clean_phone = barcode_phone.lstrip("+")
                _qr_img = _qr_mod.make(_clean_phone)
                _buf = _io_mod.BytesIO()
                _qr_img.save(_buf, format="PNG")
                _buf.seek(0)
                await q.answer("✅ تم توليد الباركود أدناه", show_alert=False)
                _caption = (
                    "📷 *باركود الرقم*\n\n"
                    f"📱 الرقم: `{_clean_phone}`\n\n"
                    "امسح هذا الباركود بكاميرا جهازك لإدخال الرقم تلقائيًا."
                )
                await context.bot.send_photo(
                    chat_id=user.id,
                    photo=_buf,
                    caption=_caption,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except ImportError:
                await q.answer("❌ مكتبة الباركود غير مثبتّة. تواصل مع المالك.", show_alert=True)
            except Exception as _bc_err:
                logger.warning(f"⚠️ خطأ في توليد باركود الرقم {barcode_phone}: {_bc_err}")
                await q.answer("❌ حدث خطأ في توليد الباركود. حاول مجددًا.", show_alert=True)
            return

        if data == "noop":
            return

        if data == "os:sold_accounts" and is_own:
            with db_conn() as c:
                active_sold = c.execute(
                    "SELECT ns.id, ns.phone_number, ns.assigned_to, ns.assigned_at, ns.ever_sold, "
                    "       pe.order_code, pe.created_at AS sale_date, pe.points_cost, "
                    "       u.full_name AS buyer_name "
                    "FROM number_stock ns "
                    "LEFT JOIN prize_exchanges pe ON pe.prize_value = ns.phone_number "
                    "     AND pe.status = 'completed' "
                    "     AND pe.prize_type IN ('telegram_number','telegram_number_code','telegram_number_stars') "
                    "LEFT JOIN users u ON u.user_id = ns.assigned_to "
                    "WHERE ns.assigned_to IS NOT NULL AND ns.deleted_at IS NULL "
                    "ORDER BY ns.assigned_at DESC LIMIT 50"
                ).fetchall()
        
                past_sold = c.execute(
                    "SELECT ns.id, ns.phone_number, ns.ever_sold, "
                    "       pe.order_code, pe.created_at AS sale_date, pe.user_id AS buyer_id, "
                    "       pe.points_cost, u.full_name AS buyer_name "
                    "FROM number_stock ns "
                    "LEFT JOIN prize_exchanges pe ON pe.prize_value = ns.phone_number "
                    "     AND pe.status = 'completed' "
                    "     AND pe.prize_type IN ('telegram_number','telegram_number_code','telegram_number_stars') "
                    "LEFT JOIN users u ON u.user_id = pe.user_id "
                    "WHERE ns.ever_sold IS TRUE AND ns.assigned_to IS NULL AND ns.deleted_at IS NULL "
                    "ORDER BY pe.created_at DESC NULLS LAST LIMIT 30"
                ).fetchall()
        
                dupes_check = c.execute(
                    "SELECT prize_value, COUNT(*) AS cnt "
                    "FROM prize_exchanges "
                    "WHERE prize_type IN ('telegram_number','telegram_number_code','telegram_number_stars') "
                    "  AND prize_value NOT IN ('number','manual') "
                    "  AND status IN ('completed','duplicate_compensated') "
                    "GROUP BY prize_value HAVING COUNT(*) > 1"
                ).fetchall()
        
            def _fmt_dt(v):
                if v is None: return "—"
                if hasattr(v, "strftime"): return v.strftime("%Y-%m-%d %H:%M")
                return str(v)[:16]
        
            lines = ["🛒 *الحسابات المبيوعة*\n"]
        
            if active_sold:
                lines.append(f"🟢 *نشطة الآن ({len(active_sold)})*")
                for r in active_sold:
                    buyer_name = r["buyer_name"] or f"ID:{r['assigned_to']}"
                    lines.append(
                        f"📱 `{r['phone_number']}`\n"
                        f"   👤 المشتري: {buyer_name} (`{r['assigned_to']}`)\n"
                        f"   📅 تاريخ البيع: {_fmt_dt(r['assigned_at'])}\n"
                        f"   📌 كود: {r['order_code'] or '—'}"
                    )
            else:
                lines.append("🟢 *نشطة الآن:* لا يوجد حالياً")
        
            lines.append("")
        
            if past_sold:
                lines.append(f"⬜ *مبيوعة سابقاً — البوت غادرها ({len(past_sold)})*")
                for r in past_sold:
                    buyer_name = r["buyer_name"] or f"ID:{r.get('buyer_id','?')}"
                    lines.append(
                        f"📱 `{r['phone_number']}`\n"
                        f"   👤 المشتري: {buyer_name}\n"
                        f"   📅 تاريخ البيع: {_fmt_dt(r['sale_date'])}\n"
                        f"   📌 كود: {r['order_code'] or '—'}"
                    )
            else:
                lines.append("⬜ *مبيوعة سابقاً:* لا يوجد")
        
            if dupes_check:
                lines.append("")
                lines.append(f"⚠️ *حسابات بيعت أكثر من مرة ({len(dupes_check)}):*")
                for d in dupes_check:
                    lines.append(f"📱 `{d['prize_value']}` — بيعت {d['cnt']} مرة")
        
            text = "\n".join(lines)
            if len(text) > 4000:
                text = text[:3950] + "\n\n_(قُطع لطول القائمة)_"
        
            detail_rows = []
            for r in active_sold:
                detail_rows.append([InlineKeyboardButton(
                    f"📋 {r['phone_number']}",
                    callback_data=f"os:sold_detail:{r['id']}"
                )])
        
            await q.edit_message_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    detail_rows + [
                        [InlineKeyboardButton("🔍 بحث برقم", callback_data="os:sold_search"),
                         InlineKeyboardButton("🧾 تحقق بكود", callback_data="os:sold_code_search")],
                        [InlineKeyboardButton("⚠️ العمليات الفاشلة", callback_data="os:failed_deliveries")],
                        [InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")],
                    ]
                )
            )
            return

        if data.startswith("os:sold_detail:") and is_own:
            stock_id = int(data.split(":")[-1])
            with db_conn() as _c:
                rec = _c.execute(
                    "SELECT ns.id, ns.phone_number, ns.session_string, ns.assigned_to, ns.assigned_at, "
                    "       ns.twofa_password, pe.order_code, pe.created_at AS sale_date, "
                    "       u.full_name AS buyer_name "
                    "FROM number_stock ns "
                    "LEFT JOIN prize_exchanges pe ON pe.prize_value = ns.phone_number "
                    "     AND pe.status = 'completed' "
                    "     AND pe.prize_type IN ('telegram_number','telegram_number_code','telegram_number_stars') "
                    "LEFT JOIN users u ON u.user_id = ns.assigned_to "
                    "WHERE ns.id=%s",
                    (stock_id,)
                ).fetchone()
            if not rec:
                await q.edit_message_text("⚠️ لم يُعثر على الحساب.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:sold_accounts")]]))
                return
            rec = dict(rec)
            def _fd(v):
                if v is None: return "—"
                if hasattr(v, "strftime"): return v.strftime("%Y-%m-%d %H:%M")
                return str(v)[:16]
            has_session = bool(rec.get("session_string"))
            buyer_name  = rec.get("buyer_name") or f"ID:{rec.get('assigned_to', '?')}"
            saved_2fa   = rec.get("twofa_password") or "—"
            info = (
                f"📱 *{rec['phone_number']}*\n\n"
                f"👤 المشتري: {buyer_name} (`{rec.get('assigned_to', '—')}`)\n"
                f"📅 تاريخ البيع: {_fd(rec.get('assigned_at'))}\n"
                f"📌 كود الطلب: {rec.get('order_code') or '—'}\n"
                f"🗝 كلمة مرور 2FA: `{saved_2fa}`\n"
                f"📡 جلسة بوت: {'✅ نشطة' if has_session else '❌ لا يوجد'}"
            )
            action_btns = []
            if has_session:
                action_btns += [
                    [InlineKeyboardButton("🔑 جلب آخر كود وصل", callback_data=f"os:sold_code:{stock_id}")],
                    [InlineKeyboardButton("🚫 طرد جميع الجلسات الأخرى", callback_data=f"os:sold_kick:{stock_id}")],
                    [InlineKeyboardButton("🔐 تغيير/عرض 2FA", callback_data=f"os:sold_2fa:{stock_id}")],
                    [InlineKeyboardButton("🚪 تسجيل خروج البوت", callback_data=f"os:sold_logout:{stock_id}")],
                ]
            action_btns.append([InlineKeyboardButton("🔙 رجوع للمبيوعات", callback_data="os:sold_accounts")])
            await q.edit_message_text(info, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(action_btns))
            return

        if data.startswith("os:sold_code:") and is_own:
            stock_id = int(data.split(":")[-1])
            rec = get_stock_number(stock_id)
            if not rec or not rec.get("session_string"):
                await q.edit_message_text("⚠️ لا تتوفر جلسة لهذا الرقم.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:sold_accounts")]]))
                return
            await q.edit_message_text(f"⏳ يتم جلب آخر كود لرقم {rec['phone_number']}...")
            _cli = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            try:
                await asyncio.wait_for(_cli.connect(), timeout=15)
                if not await asyncio.wait_for(_cli.is_user_authorized(), timeout=8):
                    await q.edit_message_text("❌ الجلسة منتهية — الحساب مطرود.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_detail:{stock_id}")]]))
                    return
                code_msg, code_date = await fetch_last_login_code(_cli)
                if code_msg:
                    import datetime as _dt
                    _now = _dt.datetime.now(_dt.timezone.utc)
                    _msg_date = code_date
                    if _msg_date and _msg_date.tzinfo is None:
                        _msg_date = _msg_date.replace(tzinfo=_dt.timezone.utc)
                    _age_minutes = int((_now - _msg_date).total_seconds() // 60) if _msg_date else None
                    _age_str = (
                        f"منذ {_age_minutes} دقيقة" if _age_minutes is not None and _age_minutes < 60
                        else f"منذ {_age_minutes // 60} ساعة" if _age_minutes is not None
                        else ""
                    )
                    _freshness = "🟢 طازج" if _age_minutes is not None and _age_minutes <= 10 else "🔴 قديم"
                    txt = (
                        f"🔑 *آخر كود وصل لرقم {rec['phone_number']}:*\n\n"
                        f"{code_msg}\n\n"
                        f"🕐 وصل {_age_str} — {_freshness}"
                    )
                else:
                    txt = f"ℹ️ لا يوجد كود حديث لرقم {rec['phone_number']}."
                await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 تحديث", callback_data=f"os:sold_code:{stock_id}")],
                        [InlineKeyboardButton("🔙 رجوع للتفاصيل", callback_data=f"os:sold_detail:{stock_id}")],
                    ]))
            except Exception as _e:
                await q.edit_message_text(f"❌ خطأ: {str(_e)[:120]}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_detail:{stock_id}")]]))
            finally:
                try: await _cli.disconnect()
                except Exception: pass
            return

        if data.startswith("os:sold_kick:") and is_own:
            stock_id = int(data.split(":")[-1])
            rec = get_stock_number(stock_id)
            if not rec or not rec.get("session_string"):
                await q.edit_message_text("⚠️ لا تتوفر جلسة لهذا الرقم.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:sold_accounts")]]))
                return
            await q.edit_message_text(f"⏳ يتم طرد جميع الجلسات الأخرى من {rec['phone_number']}...")
            _cli = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            try:
                await asyncio.wait_for(_cli.connect(), timeout=15)
                if not await asyncio.wait_for(_cli.is_user_authorized(), timeout=8):
                    await q.edit_message_text("❌ الجلسة منتهية — الحساب مطرود.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_detail:{stock_id}")]]))
                    return
                await asyncio.wait_for(_cli(ResetAuthorizationsRequest()), timeout=20)
                with db_conn() as _kc:
                    _kc.execute("UPDATE number_stock SET sessions_reset=TRUE WHERE id=%s", (stock_id,))
                await q.edit_message_text(
                    f"✅ *تم طرد جميع الجلسات الأخرى بنجاح!*\n\n"
                    f"📱 {rec['phone_number']}\n\n"
                    "الآن البوت فقط هو المتصل بهذا الحساب.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للتفاصيل", callback_data=f"os:sold_detail:{stock_id}")]]))
            except asyncio.TimeoutError:
                await q.edit_message_text("⚠️ انتهت مهلة الاتصال. حاول مجدداً.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_detail:{stock_id}")]]))
            except Exception as _e:
                await q.edit_message_text(f"❌ خطأ: {str(_e)[:150]}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_detail:{stock_id}")]]))
            finally:
                try: await _cli.disconnect()
                except Exception: pass
            return

        if data.startswith("os:sold_2fa:") and is_own:
            stock_id = int(data.split(":")[-1])
            rec = get_stock_number(stock_id)
            if not rec:
                await q.edit_message_text("⚠️ الرقم غير موجود.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:sold_accounts")]]))
                return
            saved_pwd = rec.get("twofa_password") or ""
            if saved_pwd:
                await q.edit_message_text(
                    f"🔐 *التحقق بخطوتين — {rec['phone_number']}*\n\n"
                    f"✅ مفعّل\n🗝 كلمة المرور: `{saved_pwd}`",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 توليد كلمة مرور جديدة", callback_data=f"os:sold_2fa_reset:{stock_id}")],
                        [InlineKeyboardButton("🔙 رجوع للتفاصيل", callback_data=f"os:sold_detail:{stock_id}")],
                    ]))
            else:
                await q.edit_message_text(
                    f"🔐 *التحقق بخطوتين — {rec['phone_number']}*\n\n"
                    "❌ غير مفعّل أو كلمة المرور غير محفوظة.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔐 تفعيل التحقق بخطوتين", callback_data=f"os:sold_2fa_reset:{stock_id}")],
                        [InlineKeyboardButton("🔙 رجوع للتفاصيل", callback_data=f"os:sold_detail:{stock_id}")],
                    ]))
            return

        if data.startswith("os:sold_2fa_reset:") and is_own:
            stock_id = int(data.split(":")[-1])
            rec = get_stock_number(stock_id)
            if not rec or not rec.get("session_string"):
                await q.edit_message_text("⚠️ لا تتوفر جلسة لهذا الرقم.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_detail:{stock_id}")]]))
                return
            current_pwd = rec.get("twofa_password") or ""
            await q.edit_message_text(
                f"⏳ جاري {'تغيير' if current_pwd else 'تفعيل'} التحقق بخطوتين لرقم {rec['phone_number']}...")
            if current_pwd:
                _cli2 = TelegramClient(
                    StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                try:
                    await _cli2.connect()
                    new_pwd = generate_2fa_password()
                    _expected_2fa_change[rec["phone_number"]] = time.time()
                    await _cli2.edit_2fa(current_password=current_pwd, new_password=new_pwd, hint="Auto")
                    with db_conn() as _c2:
                        _c2.execute("UPDATE number_stock SET twofa_password=%s WHERE id=%s", (new_pwd, stock_id))
                    await q.edit_message_text(
                        f"✅ *تم تغيير كلمة مرور 2FA بنجاح!*\n\n"
                        f"📱 {rec['phone_number']}\n🗝 الجديدة: `{new_pwd}`",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للتفاصيل", callback_data=f"os:sold_detail:{stock_id}")]]))
                except Exception as _e2:
                    await q.edit_message_text(f"❌ فشل تغيير كلمة المرور: {str(_e2)[:150]}",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_2fa:{stock_id}")]]))
                finally:
                    try: await _cli2.disconnect()
                    except Exception: pass
            else:
                _ok, _msg, _pwd = await enable_2fa_for_number(
                    rec["phone_number"], rec["session_string"], stock_id, bot=context.bot)
                if _ok and _pwd:
                    await q.edit_message_text(
                        f"✅ *تم تفعيل 2FA بنجاح!*\n\n"
                        f"📱 {rec['phone_number']}\n🗝 كلمة المرور: `{_pwd}`",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للتفاصيل", callback_data=f"os:sold_detail:{stock_id}")]]))
                else:
                    await q.edit_message_text(f"❌ فشل تفعيل 2FA: {_msg}",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_detail:{stock_id}")]]))
            return

        if data.startswith("os:sold_logout:") and is_own:
            stock_id = int(data.split(":")[-1])
            rec = get_stock_number(stock_id)
            if not rec or not rec.get("session_string"):
                await q.edit_message_text("⚠️ لا تتوفر جلسة لهذا الرقم.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:sold_accounts")]]))
                return
            await q.edit_message_text(
                f"🚪 *تسجيل خروج البوت من:* `{rec['phone_number']}`\n\n"
                "⚠️ هذا سيُلغي جلسة البوت على هذا الحساب المباع نهائياً.\n"
                "لن تتمكن من إجراء أي عملية عليه لاحقاً حتى تُضاف جلسة جديدة.\n\n"
                "هل أنت متأكد؟",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ نعم، سجّل خروج", callback_data=f"os:sold_logout_confirm:{stock_id}")],
                    [InlineKeyboardButton("🔙 إلغاء", callback_data=f"os:sold_detail:{stock_id}")],
                ]))
            return

        if data.startswith("os:sold_logout_confirm:") and is_own:
            stock_id = int(data.split(":")[-1])
            rec = get_stock_number(stock_id)
            if not rec or not rec.get("session_string"):
                await q.edit_message_text("⚠️ لا تتوفر جلسة.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:sold_accounts")]]))
                return
            phone = rec["phone_number"]
            await q.edit_message_text(f"⏳ يتم تسجيل الخروج من {phone}...")
            _lo_ok = False
            _lo_note = ""
            _loc = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            try:
                await asyncio.wait_for(_loc.connect(), timeout=15)
                if await asyncio.wait_for(_loc.is_user_authorized(), timeout=8):
                    await _loc.log_out()
                    _lo_ok   = True
                    _lo_note = "تم تسجيل الخروج وإلغاء الجلسة بنجاح."
                else:
                    _lo_ok   = True
                    _lo_note = "الجلسة كانت منتهية مسبقاً."
            except asyncio.TimeoutError:
                _lo_note = "⚠️ انتهت مهلة الاتصال — تم مسح الجلسة محلياً فقط."
            except Exception as _le:
                _lo_note = f"⚠️ {str(_le)[:120]}"
            finally:
                try: await _loc.disconnect()
                except Exception: pass
            with db_conn() as _lc2:
                _lc2.execute(
                    "UPDATE number_stock SET session_string=NULL, sessions_reset=FALSE, "
                    "force_listed=FALSE, auto_2fa_enabled=FALSE WHERE id=%s",
                    (stock_id,)
                )
            await q.edit_message_text(
                f"🚪 *تسجيل خروج — {phone}*\n\n"
                f"{'✅' if _lo_ok else '⚠️'} {_lo_note}\n\n"
                "📌 الجلسة مُحذوفة من قاعدة البيانات.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للمبيوعات", callback_data="os:sold_accounts")]]))
            return

        if data == "os:failed_deliveries" and is_own:
            def _fmt_dt(v):
                if v is None: return "—"
                if hasattr(v, "strftime"): return v.strftime("%Y-%m-%d %H:%M")
                return str(v)[:16]
        
            with db_conn() as c:
                old_pending = c.execute(
                    "SELECT pe.id, pe.user_id, pe.prize_type, pe.prize_value, pe.points_cost, "
                    "       pe.order_code, pe.created_at, pe.compensated_at, pe.compensated_pts, "
                    "       pe.compensated_reason, u.full_name "
                    "FROM prize_exchanges pe "
                    "LEFT JOIN users u ON u.user_id = pe.user_id "
                    "WHERE pe.status = 'pending' "
                    "  AND pe.prize_type IN ('telegram_number','telegram_number_code','telegram_number_stars') "
                    "  AND pe.points_cost > 0 "
                    "  AND pe.created_at < NOW() - INTERVAL '2 hours' "
                    "ORDER BY pe.created_at ASC LIMIT 30"
                ).fetchall()
        
                already_compensated = c.execute(
                    "SELECT pe.id, pe.user_id, pe.prize_value, pe.points_cost, "
                    "       pe.compensated_at, pe.compensated_pts, pe.compensated_reason, u.full_name "
                    "FROM prize_exchanges pe "
                    "LEFT JOIN users u ON u.user_id = pe.user_id "
                    "WHERE pe.compensated_at IS NOT NULL "
                    "  AND pe.prize_type IN ('telegram_number','telegram_number_code','telegram_number_stars') "
                    "ORDER BY pe.compensated_at DESC LIMIT 10"
                ).fetchall()
        
            needs_comp  = [r for r in old_pending if not r["compensated_at"]]
            done_comp   = [r for r in old_pending if r["compensated_at"]]
        
            lines = ["⚠️ <b>تعويض المظلومين</b>\n"]
        
            if needs_comp:
                lines.append(f"🔴 <b>ينتظرون التعويض ({len(needs_comp)}):</b>")
                for r in needs_comp:
                    uid  = r["user_id"]
                    name = r["full_name"] or f"ID:{uid}"
                    pts  = r["points_cost"] or 0
                    lines.append(
                        f"📌 <code>{r['order_code'] or r['id']}</code>\n"
                        f"   👤 <a href='tg://user?id={uid}'>{name}</a>\n"
                        f"   💰 يستحق: {pts:,} نقطة\n"
                        f"   📅 {_fmt_dt(r['created_at'])}"
                    )
            else:
                lines.append("🔴 <b>ينتظرون التعويض:</b> لا يوجد ✅")
        
            lines.append("")
        
            if done_comp:
                lines.append(f"✅ <b>عُوِّضوا مسبقاً من هذه القائمة ({len(done_comp)}):</b>")
                for r in done_comp:
                    uid  = r["user_id"]
                    name = r["full_name"] or f"ID:{uid}"
                    comp_ts = _fmt_dt(r["compensated_at"])
                    lines.append(
                        f"   👤 <a href='tg://user?id={uid}'>{name}</a> — "
                        f"{r['compensated_pts'] or 0:,} نقطة — {comp_ts}"
                    )
        
            lines.append("")
        
            if already_compensated:
                lines.append(f"📋 <b>آخر التعويضات المنفّذة ({len(already_compensated)}):</b>")
                for r in already_compensated:
                    uid  = r["user_id"]
                    name = r["full_name"] or f"ID:{uid}"
                    comp_ts = _fmt_dt(r["compensated_at"])
                    reason_map = {
                        "owner_manual":           "يدوي بالمالك",
                        "auto_duplicate":         "تلقائي (بيع مكرر)",
                        "manual_number_deleted":  "حذف رقم يدوي",
                        "auto_bulk":              "تلقائي جماعي",
                    }
                    reason_label = reason_map.get(r["compensated_reason"] or "", r["compensated_reason"] or "—")
                    lines.append(
                        f"   ✅ <a href='tg://user?id={uid}'>{name}</a> — "
                        f"{r['compensated_pts'] or 0:,} نقطة — {reason_label} — {comp_ts}"
                    )
        
            text = "\n".join(lines)
            if len(text) > 4000:
                text = text[:3950] + "\n\n<i>(قُطع لطول القائمة)</i>"
        
            action_rows = []
            if needs_comp:
                total_pts = sum(r["points_cost"] or 0 for r in needs_comp)
                action_rows.append([InlineKeyboardButton(
                    f"🤖 تعويض {len(needs_comp)} مظلوم تلقائياً ({total_pts:,} نقطة)",
                    callback_data="admin:auto_compensate_all"
                )])
            for r in needs_comp[:5]:
                uid  = r["user_id"]
                pe_id = r["id"]
                pts  = r["points_cost"] or 0
                name = (r["full_name"] or f"ID:{uid}")[:20]
                action_rows.append([InlineKeyboardButton(
                    f"↩️ {pts:,} نقطة → {name}",
                    callback_data=f"admin:refund_pe:{pe_id}"
                )])
            action_rows.append([InlineKeyboardButton("🔄 تحديث", callback_data="os:failed_deliveries")])
            action_rows.append([InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")])
        
            await q.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(action_rows)
            )
            return

        if data == "admin:auto_compensate_all" and is_own:
            with db_conn() as c:
                pending_cases = c.execute(
                    "SELECT id, user_id, points_cost, order_code "
                    "FROM prize_exchanges "
                    "WHERE status = 'pending' "
                    "  AND prize_type IN ('telegram_number','telegram_number_code','telegram_number_stars') "
                    "  AND points_cost > 0 "
                    "  AND compensated_at IS NULL "
                    "  AND created_at < NOW() - INTERVAL '2 hours'"
                ).fetchall()
        
            if not pending_cases:
                await q.answer("✅ لا يوجد أحد يحتاج تعويضاً الآن.", show_alert=True)
                return
        
            compensated = 0
            skipped     = 0
            total_pts   = 0
        
            for pe in pending_cases:
                pe_id = pe["id"]
                uid   = pe["user_id"]
                pts   = int(pe["points_cost"] or 0)
                if pts <= 0:
                    skipped += 1
                    continue
                with db_conn() as c:
                    c.execute(
                        "UPDATE prize_exchanges SET status='refunded_by_owner', "
                        "compensated_at=NOW(), compensated_pts=%s, compensated_reason='auto_bulk' "
                        "WHERE id=%s AND compensated_at IS NULL AND status='pending'",
                        (pts, pe_id)
                    )
                    updated = c.rowcount
                if updated == 0:
                    skipped += 1
                    continue
                add_points(uid, pts)
                compensated += 1
                total_pts   += pts
                try:
                    await context.bot.send_message(
                        uid,
                        f"✅ *تعويض تلقائي*\n\n"
                        f"اكتشف النظام أن عمليتك `{pe['order_code'] or pe_id}` لم تكتمل.\n"
                        f"💰 تم إعادة *{pts:,} نقطة* لرصيدك تلقائياً.\n\n"
                        f"نعتذر عن الإزعاج 🙏",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass
        
            await q.edit_message_text(
                f"✅ <b>تم تعويض المظلومين</b>\n\n"
                f"👤 عدد المعوَّضين: <b>{compensated}</b>\n"
                f"💰 إجمالي النقاط الموزَّعة: <b>{total_pts:,}</b>\n"
                f"⏭ متخطَّى (عُوِّضوا مسبقاً): {skipped}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 مراجعة القائمة", callback_data="os:failed_deliveries")],
                    [InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")],
                ])
            )
            return

        if data.startswith("admin:refund_pe:") and is_own:
            pe_id = int(data.split(":")[-1])
            with db_conn() as c:
                pe = c.execute(
                    "SELECT id, user_id, points_cost, status, order_code, "
                    "       compensated_at, compensated_pts, compensated_reason "
                    "FROM prize_exchanges WHERE id=%s", (pe_id,)
                ).fetchone()
            if not pe:
                await q.answer("⚠️ العملية غير موجودة.", show_alert=True)
                return
            # ─── حماية من التعويض المزدوج ───
            if pe["compensated_at"]:
                _comp_ts = pe["compensated_at"]
                _comp_ts_str = _comp_ts.strftime("%Y-%m-%d %H:%M") if hasattr(_comp_ts, "strftime") else str(_comp_ts)[:16]
                await q.answer(
                    f"✅ هذا العضو عُوِّض مسبقاً بـ {pe['compensated_pts'] or 0:,} نقطة\n"
                    f"بتاريخ {_comp_ts_str}\n"
                    f"السبب: {pe['compensated_reason'] or '—'}\n\n"
                    f"لا يحتاج تعويضاً إضافياً.",
                    show_alert=True
                )
                return
            if pe["status"] not in ("pending", "failed"):
                await q.answer(f"⚠️ حالة العملية: {pe['status']} — لا يمكن استرداد نقاطها.", show_alert=True)
                return
            pts = int(pe["points_cost"] or 0)
            uid = pe["user_id"]
            with db_conn() as c:
                c.execute(
                    "UPDATE prize_exchanges SET status='refunded_by_owner', "
                    "compensated_at=NOW(), compensated_pts=%s, compensated_reason='owner_manual' "
                    "WHERE id=%s AND compensated_at IS NULL",
                    (pts, pe_id)
                )
                rows_updated = c.rowcount
            if rows_updated == 0:
                await q.answer("⚠️ تم تعويض هذه العملية للتو من مكان آخر. لا داعي للتكرار.", show_alert=True)
                return
            if pts > 0:
                add_points(uid, pts)
            try:
                await context.bot.send_message(
                    uid,
                    f"✅ *إعادة نقاط*\n\nأعاد المالك نقاطك لعملية `{pe['order_code'] or pe_id}`.\n"
                    f"💰 أُعيد إليك: *{pts:,} نقطة*.\n\nنعتذر عن الإزعاج 🙏",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
            await q.answer(f"✅ تمت إعادة {pts:,} نقطة للمستخدم {uid}.", show_alert=True)
            return
    return True
