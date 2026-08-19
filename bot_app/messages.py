"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

def _parse_account_name_lines(raw_text: str) -> list[str]:
    parsed = []
    for raw_line in raw_text.splitlines():
        display_name = raw_line.strip()
        if not display_name:
            continue
        parsed.append(display_name[:64])
    return parsed

def _load_unassigned_name_accounts() -> list[dict]:
    with db_conn() as c:
        return c.execute(
            """
            SELECT ns.phone_number, ns.session_string
            FROM number_stock ns
            WHERE ns.deleted_at IS NULL
              AND ns.session_string IS NOT NULL
              AND BTRIM(ns.session_string) <> ''
              AND NOT EXISTS (
                  SELECT 1
                  FROM account_name_assignments ana
                  WHERE ana.phone_number = ns.phone_number
              )
            ORDER BY ns.id
            """
        ).fetchall()

async def _apply_account_name(phone: str, display_name: str) -> None:
    with db_conn() as c:
        row = c.execute(
            """
            SELECT session_string
            FROM number_stock
            WHERE phone_number=%s
              AND deleted_at IS NULL
              AND session_string IS NOT NULL
              AND BTRIM(session_string) <> ''
            """,
            (phone,),
        ).fetchone()
    if not row:
        raise ValueError("الحساب غير موجود أو لا يملك جلسة صالحة")
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise RuntimeError("إعدادات Telegram API غير مكتملة")

    client = TelegramClient(
        StringSession(row["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            raise RuntimeError("الجلسة غير مصرح بها")
        await asyncio.wait_for(
            client(functions.account.UpdateProfileRequest(
                first_name=display_name,
                last_name="",
            )),
            timeout=30,
        )
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    with db_conn() as c:
        c.execute(
            """
            INSERT INTO account_name_assignments
                (phone_number, assigned_name, assigned_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (phone_number) DO UPDATE SET
                assigned_name=EXCLUDED.assigned_name,
                assigned_at=NOW()
            """,
            (phone, display_name),
        )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    text   = (update.message.text or update.message.caption or "").strip()
    state  = context.user_data.get("state", "")
    is_own = (user.id == OWNER_ID)

    # يسمح للمالك بإرسال auth_key_hex:dc_id مباشرةً دون فتح أمر منفصل.
    if is_own and state != "os_import_hex":
        _, _, looks_like_hex_sessions = _parse_hex_session_text(text)
        if looks_like_hex_sessions:
            state = "os_import_hex"
            context.user_data["state"] = state

    if not is_own and is_user_banned(user.id):
        await update.message.reply_text("🚫 تم حظرك من استخدام هذا البوت.")
        return

    if is_maintenance_on() and not is_own:
        await update.message.reply_text(MAINTENANCE_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return

    is_supervisor_txt = (not is_own) and is_supervisor(user.id)
    _owner_admin_state = is_own and (
        state.startswith("os_") or state.startswith("await_mb_")
        or state in ("confirm_cancel_order", "confirm_complete_order")
    )
    _sv_admin_state = is_supervisor_txt and state.startswith("sv_")
    _thank_owner_state = state in {"thank_owner_menu", "thank_owner_ar", "thank_owner_en", "thank_owner_photo"}
    if state != "verify_math" and not _thank_owner_state and not _owner_admin_state and not _sv_admin_state:
        try:
            _db_user = get_user(user.id)
            if _db_user and _db_user.get("verified", 0):
                _unjoined = await get_unjoined_mandatory_channels(context, user.id)
                if _unjoined:
                    context.user_data["state"] = "await_mandatory_join"
                    await show_mandatory_gate(update, context, _unjoined, edit=False, is_owner=is_own)
                    return
        except Exception as _gate_err:
            logger.warning(f"⚠️ خطأ في فحص القنوات الإجبارية للمستخدم {user.id}: {_gate_err}")

    # ─── نظام الرشق يستخدم نفس مسار استقبال الرسائل لكل خطوات الطلب ───
    if context.user_data.get("raksh_step"):
        from .raksh_system import handle_raksh_text
        if await handle_raksh_text(update, context):
            return

    # ─── الخدمات الأسطورية تستخدم نفس مسار استقبال الرسائل لكل أنواعها ───
    if await legendary_handle_text(update, context, text):
        return

    if state in ("thank_owner_ar", "thank_owner_en") and not is_own:
        if not text:
            await update.message.reply_text("⚠️ أرسل رسالة نصية.")
            return
        language = "العربية" if state == "thank_owner_ar" else "الإنجليزية"
        sender = f"{user.full_name or 'مستخدم'}"
        if user.username:
            sender += f" (@{user.username})"
        owner_text = (
            f"💌 رسالة شكر جديدة ({language})\n\n"
            f"👤 المرسل: {sender}\n"
            f"🆔 ID: {user.id}\n\n"
            f"{text}"
        )
        try:
            await context.bot.send_message(chat_id=OWNER_ID, text=owner_text[:4096])
            await update.message.reply_text(
                get_setting("thank_owner_success_message")
                or "✅ تم إرسال شكرك إلى المالك، شكراً لك!",
                reply_markup=main_menu_kb(False)
            )
        except Exception:
            logger.exception("فشل إرسال رسالة شكر إلى المالك")
            await update.message.reply_text(
                "⚠️ تعذر إرسال الرسالة حالياً، حاول مرة أخرى لاحقاً.",
                reply_markup=main_menu_kb(False)
            )
        context.user_data["state"] = "main_menu"
        return

    if state == "os_await_thank_owner_setting" and is_own:
        key = context.user_data.get("thank_owner_setting_key")
        if key not in THANK_OWNER_SETTINGS:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("⚠️ انتهت جلسة الإعداد، افتحها من جديد.", reply_markup=owner_settings_kb())
            return
        if not text:
            await update.message.reply_text("⚠️ النص لا يمكن أن يكون فارغاً.")
            return
        set_setting(key, text)
        context.user_data["state"] = "main_menu"
        context.user_data.pop("thank_owner_setting_key", None)
        await update.message.reply_text(
            f"✅ تم تحديث: {THANK_OWNER_SETTINGS[key][0]}",
            reply_markup=thank_owner_settings_kb()
        )
        return

    if state == "os_await_account_names" and is_own:
        context.user_data["state"] = "main_menu"
        names = _parse_account_name_lines(text)
        if not names:
            await update.message.reply_text(
                "⚠️ لم أجد أسماء صالحة.\n"
                "أرسل اسماً واحداً في كل سطر، مثل:\n"
                "محمد\n"
                "علي\n"
                "حسن",
                reply_markup=account_info_kb(),
            )
            return

        available_accounts = _load_unassigned_name_accounts()
        progress = await update.message.reply_text(
            f"⏳ جارٍ توزيع {len(names):,} اسماً على الحسابات بالتسلسل..."
        )
        success = []
        failed = []
        for account, display_name in zip(available_accounts, names):
            phone = account["phone_number"]
            try:
                await _apply_account_name(phone, display_name)
                success.append(f"{display_name} → {phone}")
            except Exception as exc:
                logger.warning(f"⚠️ فشل تحديث اسم الحساب {phone}: {exc}")
                failed.append(f"{display_name} → {phone} — {str(exc)[:120]}")

        unassigned_names = names[len(available_accounts):]
        if unassigned_names:
            failed.extend(
                f"{display_name} — لا يوجد حساب متاح"
                for display_name in unassigned_names
            )

        result_lines = [
            f"🔤 *تقرير تحديث الأسماء*",
            f"✅ تم تعيينه: {len(success):,}",
            f"❌ لم يتم تعيينه: {len(failed):,}",
        ]
        if success:
            result_lines.append("\n✅ الحسابات الناجحة:\n" + "\n".join(f"• {item}" for item in success[:30]))
            if len(success) > 30:
                result_lines.append(f"• ... و{len(success) - 30:,} حساباً آخر")
        if failed:
            result_lines.append("\n❌ الحسابات الفاشلة:\n" + "\n".join(f"• {item}" for item in failed[:30]))
            if len(failed) > 30:
                result_lines.append(f"• ... و{len(failed) - 30:,} حساباً آخر")
        await progress.edit_text(
            "\n".join(result_lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 معلومات الحسابات", callback_data="os:account_info")],
            ]),
        )
        return

    # ─── معالجة البايو ──────────────────────────────────────────────
    if state == "os_await_account_bios" and is_own:
        context.user_data["state"] = "main_menu"
        bios = _parse_generic_lines(text)
        if not bios:
            await update.message.reply_text(
                "⚠️ لم أجد بايو صالحاً.\n"
                "أرسل بايو واحداً في كل سطر:",
                reply_markup=account_info_kb(),
            )
            return

        available_accounts = _load_unassigned_bio_accounts()
        progress = await update.message.reply_text(
            f"⏳ جارٍ توزيع {len(bios):,} بايو على الحسابات بالتسلسل..."
        )
        success = []
        failed = []
        for account, bio in zip(available_accounts, bios):
            phone = account["phone_number"]
            try:
                await _apply_account_bio(phone, bio)
                success.append(f"{bio[:30]}… → {phone}")
            except Exception as exc:
                logger.warning(f"⚠️ فشل تحديث البايو للحساب {phone}: {exc}")
                failed.append(f"{bio[:30]}… → {phone} — {str(exc)[:120]}")

        unassigned = bios[len(available_accounts):]
        if unassigned:
            failed.extend(
                f"{b[:30]}… — لا يوجد حساب متاح"
                for b in unassigned
            )

        result_lines = [
            f"📝 *تقرير تحديث البايو*",
            f"✅ تم تعيينه: {len(success):,}",
            f"❌ لم يتم تعيينه: {len(failed):,}",
        ]
        if success:
            result_lines.append("\n✅ الناجحة:\n" + "\n".join(f"• {item}" for item in success[:30]))
            if len(success) > 30:
                result_lines.append(f"• ... و{len(success) - 30:,} بايو آخر")
        if failed:
            result_lines.append("\n❌ الفاشلة:\n" + "\n".join(f"• {item}" for item in failed[:30]))
            if len(failed) > 30:
                result_lines.append(f"• ... و{len(failed) - 30:,} بايو آخر")
        await progress.edit_text(
            "\n".join(result_lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 معلومات الحسابات", callback_data="os:account_info")],
            ]),
        )
        return

    # ─── معالجة اليوزرات ──────────────────────────────────────────────
    if state == "os_await_account_usernames" and is_own:
        context.user_data["state"] = "main_menu"
        usernames = _parse_generic_lines(text)
        if not usernames:
            await update.message.reply_text(
                "⚠️ لم أجد يوزرات صالحة.\n"
                "أرسل يوزر واحداً في كل سطر (بدون @):",
                reply_markup=account_info_kb(),
            )
            return

        available_accounts = _load_unassigned_username_accounts()
        progress = await update.message.reply_text(
            f"⏳ جارٍ توزيع {len(usernames):,} يوزر على الحسابات بالتسلسل..."
        )
        success = []
        failed = []
        for account, username in zip(available_accounts, usernames):
            phone = account["phone_number"]
            try:
                await _apply_account_username(phone, username)
                success.append(f"@{username} → {phone}")
            except Exception as exc:
                logger.warning(f"⚠️ فشل تحديث اليوزر للحساب {phone}: {exc}")
                failed.append(f"@{username} → {phone} — {str(exc)[:120]}")

        unassigned = usernames[len(available_accounts):]
        if unassigned:
            failed.extend(
                f"@{u} — لا يوجد حساب متاح"
                for u in unassigned
            )

        result_lines = [
            f"🔖 *تقرير تحديث اليوزرات*",
            f"✅ تم تعيينه: {len(success):,}",
            f"❌ لم يتم تعيينه: {len(failed):,}",
        ]
        if success:
            result_lines.append("\n✅ الناجحة:\n" + "\n".join(f"• {item}" for item in success[:30]))
            if len(success) > 30:
                result_lines.append(f"• ... و{len(success) - 30:,} يوزر آخر")
        if failed:
            result_lines.append("\n❌ الفاشلة:\n" + "\n".join(f"• {item}" for item in failed[:30]))
            if len(failed) > 30:
                result_lines.append(f"• ... و{len(failed) - 30:,} يوزر آخر")
        await progress.edit_text(
            "\n".join(result_lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 معلومات الحسابات", callback_data="os:account_info")],
            ]),
        )
        return

    if state == "os_import_hex" and is_own:
        context.user_data["state"] = ""
        sessions, bad_lines, _ = _parse_hex_session_text(text)
        if not sessions:
            await update.message.reply_text(
                f"❌ لم أجد أي جلسة صالحة في النص.\n"
                + (f"الأخطاء:\n" + "\n".join(f"• {b}" for b in bad_lines[:10]) if bad_lines else ""),
                parse_mode=ParseMode.MARKDOWN
            )
            return
        warn = f"\n⚠️ {len(bad_lines)} سطر مرفوض." if bad_lines else ""
        prog = await update.message.reply_text(
            f"⏳ جاري استيراد {len(sessions)} حساب...{warn}"
        )
        ok_list, fail_list = [], []
        for idx, sess in enumerate(sessions):
            try:
                client = TelegramClient(StringSession(sess), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                try:
                    await asyncio.wait_for(client.connect(), timeout=15)
                except asyncio.TimeoutError:
                    fail_list.append(f"#{idx+1}: انتهت مهلة الاتصال")
                    continue
                if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                    await client.disconnect()
                    fail_list.append(f"#{idx+1}: جلسة منتهية أو غير مفعّلة")
                    continue
                me = await client.get_me()
                phone = me.phone if me.phone.startswith("+") else f"+{me.phone}"
                await client.disconnect()
                with db_conn() as _c:
                    exists = _c.execute(
                        "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
                    ).fetchone()
                    if exists:
                        _c.execute(
                            "UPDATE number_stock SET session_string=%s, assigned_to=NULL, assigned_at=NULL,"
                            " forced_ref_excluded=FALSE WHERE phone_number=%s",
                            (sess, phone)
                        )
                    else:
                        _c.execute(
                            "INSERT INTO number_stock (phone_number, session_string, forced_ref_excluded)"
                            " VALUES (%s,%s,FALSE)",
                            (phone, sess)
                        )
                ok_list.append(phone)
                if len(ok_list) % 10 == 0:
                    await prog.edit_text(
                        f"⏳ تم {len(ok_list)}/{len(sessions)}...", parse_mode=ParseMode.MARKDOWN
                    )
            except Exception as _be:
                fail_list.append(f"#{idx+1}: {_be}")
        result_lines = [f"✅ *تم استيراد {len(ok_list)} حساب بنجاح:*"]
        for p in ok_list:
            result_lines.append(f"  • `{p}`")
        if fail_list:
            result_lines.append(f"\n❌ *فشل {len(fail_list)}:*")
            for f_ in fail_list[:20]:
                result_lines.append(f"  • {f_}")
            if len(fail_list) > 20:
                result_lines.append(f"  _(+{len(fail_list)-20} أخرى)_")
        await prog.edit_text("\n".join(result_lines), parse_mode=ParseMode.MARKDOWN)
        return

    if state == "os_bulk_import" and is_own:
        _pending_bulk_import.discard(user.id)
        context.user_data["state"] = ""
        import json as _json
        try:
            raw = _json.loads(text)
        except Exception:
            await update.message.reply_text("❌ الصيغة غير صحيحة. تأكد أنه JSON صالح وأعد المحاولة.\nأرسل /import_sessions للمحاولة مجدداً.")
            return
        if isinstance(raw, dict):
            raw = [raw]
        elif isinstance(raw, str):
            raw = [raw]
        sessions = []
        for item in raw:
            if isinstance(item, str):
                sessions.append({"session": _maybe_convert_session(item), "phone": None})
            elif isinstance(item, dict):
                if "dc_id" in item and "auth_key" in item:
                    converted = pyrogram_json_to_telethon(item)
                    if converted:
                        p = item.get("phone") or item.get("phone_number") or None
                        sessions.append({"session": converted, "phone": p})
                    continue
                s = (item.get("session") or item.get("session_string") or "").strip()
                p = item.get("phone") or item.get("phone_number") or None
                if s:
                    sessions.append({"session": _maybe_convert_session(s), "phone": p})
        if not sessions:
            await update.message.reply_text("❌ لم أجد أي جلسة في البيانات المرسلة.")
            return
        prog = await update.message.reply_text(f"⏳ جاري معالجة {len(sessions)} جلسة...")
        ok_list, fail_list = [], []
        for idx, entry in enumerate(sessions):
            sess = entry["session"]
            hint_phone = entry["phone"]
            try:
                if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
                    fail_list.append(hint_phone or f"#{idx+1}: لا توجد API credentials")
                    continue
                client = TelegramClient(StringSession(sess), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                await asyncio.wait_for(client.connect(), timeout=20)
                if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                    await client.disconnect()
                    fail_list.append(hint_phone or f"#{idx+1}: جلسة منتهية")
                    continue
                me = await client.get_me()
                phone = me.phone if me.phone.startswith("+") else f"+{me.phone}"
                await client.disconnect()
                with db_conn() as _c:
                    existing = _c.execute("SELECT id FROM number_stock WHERE phone_number=%s", (phone,)).fetchone()
                    if existing:
                        _c.execute(
                            "UPDATE number_stock SET session_string=%s, assigned_to=NULL, assigned_at=NULL,"
                            " forced_ref_excluded=FALSE WHERE phone_number=%s",
                            (sess, phone)
                        )
                    else:
                        _c.execute(
                            "INSERT INTO number_stock (phone_number, session_string, forced_ref_excluded)"
                            " VALUES (%s, %s, FALSE)",
                            (phone, sess)
                        )
                ok_list.append(phone)
            except Exception as _be:
                fail_list.append(hint_phone or f"#{idx+1}: {_be}")
        result_lines = [f"✅ *تم استيراد {len(ok_list)} حساب بنجاح:*"]
        for p in ok_list:
            result_lines.append(f"  • `{p}`")
        if fail_list:
            result_lines.append(f"\n❌ *فشل {len(fail_list)}:*")
            for f_ in fail_list:
                result_lines.append(f"  • {f_}")
        await prog.edit_text("\n".join(result_lines), parse_mode=ParseMode.MARKDOWN)
        return

    if state == "verify_math":
        correct = context.user_data.get("math_ans")
        try:
            ans = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً فقط.")
            return
        if ans == correct:
            await ask_for_phone_share(update, context, edit=False)
        else:
            prob, new_ans = generate_math()
            context.user_data["math_ans"] = new_ans
            await update.message.reply_text(
                f"❌ إجابة خاطئة! حاول مجدداً:\n\n❓  *{prob} = ؟*",
                parse_mode=ParseMode.MARKDOWN
            )
        return

    if state == "await_mb_label" and is_own:
        menu = context.user_data.get("mb_menu")
        mb_type = context.user_data.get("mb_type")
        if not (menu and mb_type):
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("⚠️ انتهت الجلسة، ابدأ من جديد.", reply_markup=owner_settings_kb())
            return
        context.user_data["mb_label"] = text
        if mb_type == "url":
            context.user_data["state"] = "await_mb_url"
            await update.message.reply_text("🔗 أرسل الرابط (يبدأ بـ https://):")
        elif mb_type == "text":
            context.user_data["state"] = "await_mb_textcontent"
            await update.message.reply_text("💬 أرسل النص الذي سيظهر للمستخدم عند الضغط على الزر:")
        elif mb_type == "owner":
            saved_contact = get_setting("owner_contact") or ""
            if saved_contact:
                with db_conn() as c:
                    max_order = c.execute("SELECT COALESCE(MAX(sort_order),-1) AS m FROM menu_items WHERE menu=?", (menu,)).fetchone()["m"]
                    c.execute(
                        "INSERT INTO menu_items (menu,label,action_type,action_value,width,sort_order,enabled) VALUES (?,?,?,?,?,?,1)",
                        (menu, text, "url", saved_contact, 2, max_order + 1)
                    )
                context.user_data["state"] = "main_menu"
                await update.message.reply_text(
                    f"✅ تمت إضافة الزر '{text}' (يفتح: {saved_contact}).",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للإدارة", callback_data=f"mb_menu:{menu}")]])
                )
            else:
                context.user_data["state"] = "await_mb_url"
                context.user_data["mb_save_as_owner_contact"] = True
                await update.message.reply_text(
                    "🔗 لم تحدد رابط تواصل مع المالك من قبل. أرسل الآن رابط حسابك الشخصي "
                    "(مثال: `https://t.me/username`) — سيُستخدم لهذا الزر وسيُحفظ لاستخدامه تلقائياً في المرات القادمة:",
                    parse_mode=ParseMode.MARKDOWN
                )
        else:  # goto
            rows = [[InlineKeyboardButton(lbl, callback_data=f"mb_goto_pick:{val}")] for lbl, val in GOTO_TARGETS]
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"mb_menu:{menu}")])
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("↪️ اختر القسم الذي تريد ربط الزر به:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if state == "await_mb_rename" and is_own:
        menu = context.user_data.get("mb_rename_menu")
        mid = context.user_data.get("mb_rename_id")
        new_label = text.strip()
        if not menu or not mid:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text(
                "⚠️ انتهت جلسة إعادة التسمية، ابدأ من جديد.",
                reply_markup=owner_settings_kb(),
            )
            return
        if not new_label:
            await update.message.reply_text("⚠️ الاسم لا يمكن أن يكون فارغاً. أرسل الاسم الجديد:")
            return
        new_label = new_label[:120]
        with db_conn() as c:
            updated = c.execute(
                "UPDATE menu_items SET label=? WHERE id=? AND menu=?",
                (new_label, int(mid), menu),
            ).rowcount
        context.user_data.pop("mb_rename_menu", None)
        context.user_data.pop("mb_rename_id", None)
        context.user_data["state"] = "main_menu"
        if not updated:
            await update.message.reply_text(
                "⚠️ لم يتم العثور على الزر، ربما تم حذفه أو تغييره.",
                reply_markup=owner_settings_kb(),
            )
            return
        _, menu_markup = render_mb_menu_screen(menu)
        await update.message.reply_text(
            f"✅ تم تغيير اسم الزر إلى: *{new_label}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_markup,
        )
        return

    if state == "await_mb_url" and is_own:
        if not (text.startswith("http://") or text.startswith("https://")):
            await update.message.reply_text("⚠️ الرابط يجب أن يبدأ بـ http:// أو https://")
            return
        menu  = context.user_data.get("mb_menu")
        label = context.user_data.get("mb_label")
        save_as_owner_contact = context.user_data.pop("mb_save_as_owner_contact", False)
        with db_conn() as c:
            max_order = c.execute("SELECT COALESCE(MAX(sort_order),-1) AS m FROM menu_items WHERE menu=?", (menu,)).fetchone()["m"]
            c.execute(
                "INSERT INTO menu_items (menu,label,action_type,action_value,width,sort_order,enabled) VALUES (?,?,?,?,?,?,1)",
                (menu, label, "url", text, 2, max_order + 1)
            )
        if save_as_owner_contact:
            set_setting("owner_contact", text)
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(f"✅ تمت إضافة الزر '{label}'.",
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للإدارة", callback_data=f"mb_menu:{menu}")]]))
        return

    if state == "await_mb_textcontent" and is_own:
        menu  = context.user_data.get("mb_menu")
        label = context.user_data.get("mb_label")
        with db_conn() as c:
            max_order = c.execute("SELECT COALESCE(MAX(sort_order),-1) AS m FROM menu_items WHERE menu=?", (menu,)).fetchone()["m"]
            c.execute(
                "INSERT INTO menu_items (menu,label,action_type,action_value,width,sort_order,enabled) VALUES (?,?,?,?,?,?,1)",
                (menu, label, "text", text, 2, max_order + 1)
            )
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(f"✅ تمت إضافة الزر '{label}'.",
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للإدارة", callback_data=f"mb_menu:{menu}")]]))
        return

    if state == "await_smm_link":
        context.user_data["smm_link"] = text
        svc  = context.user_data.get("smm_svc", {})
        qty  = context.user_data.get("smm_qty", 0)
        cost = context.user_data.get("smm_cost", 0)
        db_user = get_user(user.id)
        pts = db_user["points"] if db_user else 0
        desc_text = svc.get("description") or ""
        context.user_data["state"] = "confirm_smm"
        await update.message.reply_text(
            f"📋 *تفاصيل الطلب:*\n\n"
            f"🔹 الخدمة: {svc.get('name_ar', '')}\n"
            f"🔢 الكمية: {qty}\n"
            f"🔗 الرابط: `{text}`\n"
            + (f"📝 {desc_text}\n" if desc_text else "") +
            f"💰 التكلفة: {cost} نقطة\n"
            f"💎 رصيدك: {pts} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأكيد الطلب", callback_data="confirm_order:yes"),
                 InlineKeyboardButton("❌ إلغاء", callback_data="confirm_order:no")],
                [InlineKeyboardButton("🔙 رجوع (تغيير الرابط)", callback_data="smm_back:link")]
            ])
        )
        return

    if state == "await_smm_qty":
        try:
            qty = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        svc = context.user_data.get("smm_svc", {})
        if not svc:
            svc_id = context.user_data.get("smm_svc_db_id")
            with db_conn() as c:
                svc = dict(c.execute("SELECT * FROM services WHERE id=?", (svc_id,)).fetchone() or {})
            context.user_data["smm_svc"] = svc
        if qty < svc.get("min_qty", 1) or qty > svc.get("max_qty", 1000000):
            await update.message.reply_text(
                f"⚠️ الكمية خارج النطاق المسموح.\nالحد الأدنى: {svc['min_qty']} | الحد الأعلى: {svc['max_qty']}"
            )
            return
        cost = int(qty / 1000 * svc.get("price_per_point", 1))
        context.user_data["smm_qty"] = qty
        context.user_data["smm_cost"] = cost
        context.user_data["state"] = "await_smm_link"
        await update.message.reply_text(
            f"✅ الكمية: {qty} | التكلفة: {cost} نقطة\n\n"
            f"📎 أرسل *رابط* الحساب/القناة/البوست:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع (تغيير الكمية)", callback_data="smm_back:qty")]
            ])
        )
        return

    if state == "confirm_smm":
        if text == "نعم":
            svc  = context.user_data.get("smm_svc", {})
            qty  = context.user_data.get("smm_qty", 0)
            cost = context.user_data.get("smm_cost", 0)
            link = context.user_data.get("smm_link", "")
            if not deduct_points(user.id, cost):
                await update.message.reply_text("❌ نقاطك غير كافية.")
                context.user_data["state"] = "main_menu"
                await update.message.reply_text("🏠 القائمة الرئيسية:", reply_markup=main_menu_kb(is_own))
                return
            api_res = await asyncio.to_thread(smm_create_order, svc["api_service_id"], link, qty, panel=svc.get("panel", 1))
            if "error" in api_res or not api_res.get("order"):
                add_points(user.id, cost)
                err_msg = md_escape(api_res.get("error", "خطأ غير معروف من الموقع"))
                await update.message.reply_text(
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
            await update.message.reply_text(
                f"✅ *تمت العملية بنجاح!*\n\n"
                f"🔹 الخدمة: {svc['name_ar']}\n"
                f"🔢 الكمية: {qty}\n"
                f"💰 التكلفة: {cost} نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
            await update.message.reply_text(
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
        elif text == "لا":
            await update.message.reply_text("❌ تم إلغاء الطلب.", reply_markup=main_menu_kb(is_own))
        context.user_data["state"] = "main_menu"
        return

    if state == "await_transfer_id":
        try:
            to_user = lookup_user_by_id_or_username(text)
        except Exception:
            logger.exception("فشل البحث عن مستلم تحويل النقاط")
            await update.message.reply_text(
                "❌ تعذر البحث عن المستخدم حالياً. حاول مرة أخرى بعد قليل."
            )
            return
        if not to_user:
            await update.message.reply_text(
                "⚠️ لم يتم العثور على المستلم.\n"
                "أرسل ID رقمي أو @يوزرنيم مسجّل في البوت:"
            )
            return
        tid = int(to_user["user_id"])
        if tid == user.id:
            await update.message.reply_text("⚠️ لا يمكنك التحويل لنفسك.")
            return
        context.user_data["transfer_to"] = tid
        context.user_data["transfer_to_name"] = to_user["full_name"]
        context.user_data["transfer_to_username"] = to_user.get("username") or ""
        context.user_data["state"] = "await_transfer_pts"
        receiver_label = (
            f"{to_user.get('full_name') or '—'} "
            f"(@{to_user['username']})"
            if to_user.get("username")
            else f"{to_user.get('full_name') or '—'} (ID: {tid})"
        )
        await update.message.reply_text(
            f"👤 المستلم: {receiver_label}\n\nكم نقطة تريد تحويلها؟ (خصم 1%)"
        )
        return

    if state == "await_transfer_pts":
        try:
            pts = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        if pts <= 0:
            await update.message.reply_text("⚠️ أدخل كمية أكبر من صفر.")
            return
        fee  = max(1, int(pts * 0.01))
        total_deduct = pts + fee
        db_user = get_user(user.id)
        current_points = int(db_user.get("points") or 0) if db_user else 0
        if current_points < total_deduct:
            await update.message.reply_text(f"❌ نقاطك غير كافية. تحتاج {total_deduct} نقطة (شاملة رسوم 1%).")
            return
        context.user_data["transfer_pts"]   = pts
        context.user_data["transfer_fee"]   = fee
        context.user_data["transfer_total"] = total_deduct
        context.user_data["state"] = "confirm_transfer"
        to_name = context.user_data.get("transfer_to_name", "")
        await update.message.reply_text(
            f"📋 *تأكيد التحويل:*\n\n"
            f"👤 إلى: {to_name}\n"
            f"💰 المبلغ: {pts} نقطة\n"
            f"💸 الرسوم: {fee} نقطة (1%)\n"
            f"📤 الإجمالي: {total_deduct} نقطة\n\n"
            f"أرسل *نعم* للتأكيد أو *لا* للإلغاء",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if state == "confirm_transfer":
        if text == "نعم":
            pts   = context.user_data.get("transfer_pts", 0)
            fee   = context.user_data.get("transfer_fee", 0)
            total = context.user_data.get("transfer_total", 0)
            to_id = context.user_data.get("transfer_to")
            if not deduct_points(user.id, total):
                await update.message.reply_text("❌ نقاطك غير كافية.")
            else:
                add_points(to_id, pts)
                code = next_order_code(user.id)
                with db_conn() as c:
                    c.execute(
                        "INSERT INTO point_transfers (from_user,to_user,points,fee) VALUES (?,?,?,?)",
                        (user.id, to_id, pts, fee)
                    )
                await update.message.reply_text(
                    f"✅ *تم التحويل بنجاح!*\n\n"
                    f"💰 {pts} نقطة إلى المستخدم.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=main_menu_kb(is_own)
                )
                await update.message.reply_text(
                    f"📌 *كود عمليتك:* `{code}`",
                    parse_mode=ParseMode.MARKDOWN
                )
                try:
                    await context.bot.send_message(
                        to_id,
                        f"🎉 تلقيت {pts} نقطة من مستخدم!\n📌 كود: `{code}`",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass
        else:
            await update.message.reply_text("❌ تم إلغاء التحويل.", reply_markup=main_menu_kb(is_own))
        context.user_data["state"] = "main_menu"
        return

    if state == "await_charge_points_amount":
        try:
            pts = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً موجباً.")
            return
        if pts <= 0:
            await update.message.reply_text("⚠️ يجب أن يكون عدد النقاط أكبر من صفر.")
            return
        rate  = int(get_setting("star_to_points") or "250")
        stars = math.ceil(pts / rate)
        context.user_data["charge_stars"] = stars
        context.user_data["charge_pts"]   = stars * rate
        context.user_data["state"] = "confirm_charge_stars"
        await update.message.reply_text(
            f"💡 للحصول على {pts} نقطة تحتاج *{stars} ⭐*\n"
            f"(ستحصل فعلياً على {stars * rate} نقطة)\n\n"
            f"أرسل *نعم* للمتابعة للدفع أو *لا* للإلغاء",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if state == "await_charge_stars_amount":
        try:
            stars = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً موجباً.")
            return
        if stars <= 0:
            await update.message.reply_text("⚠️ يجب أن يكون عدد النجوم أكبر من صفر.")
            return
        rate = int(get_setting("star_to_points") or "250")
        pts  = stars * rate
        context.user_data["charge_stars"] = stars
        context.user_data["charge_pts"]   = pts
        context.user_data["state"] = "confirm_charge_stars"
        await update.message.reply_text(
            f"💡 *{stars} ⭐ = {pts} نقطة*\n\n"
            f"أرسل *نعم* للمتابعة للدفع أو *لا* للإلغاء",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if state == "confirm_charge_stars":
        if text == "نعم":
            stars = context.user_data.get("charge_stars", 1)
            await context.bot.send_invoice(
                chat_id=user.id,
                title="شحن نقاط",
                description=f"شراء {context.user_data.get('charge_pts')} نقطة مقابل {stars} نجمة",
                payload=f"charge_stars:{stars}:{user.id}",
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice("نجوم", stars)],
            )
        else:
            await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_kb(is_own))
        context.user_data["state"] = "main_menu"
        return

    if state == "await_exchange_stars_count":
        try:
            stars = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        if stars <= 0:
            await update.message.reply_text("⚠️ يجب أن يكون الرقم أكبر من صفر.")
            return
        rate = int(get_setting("exchange_star_rate") or "2000")
        cost = stars * rate
        db_user = get_user(user.id)
        pts = db_user["points"] if db_user else 0
        if pts < cost:
            await update.message.reply_text(
                f"❌ *نقاطك غير كافية!*\n\n⭐ تحتاج: {cost} نقطة\n💎 رصيدك: {pts} نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
            context.user_data["state"] = "main_menu"
            return
        if not deduct_points(user.id, cost):
            await update.message.reply_text("❌ حدث خطأ في خصم النقاط.", reply_markup=main_menu_kb(is_own))
            context.user_data["state"] = "main_menu"
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
        await update.message.reply_text(
            f"✅ *تمت العملية بنجاح!*\n\n"
            f"⭐ طلب {stars} نجمة مسجل\n"
            f"💰 التكلفة: {cost} نقطة\n\n"
            + (f"{custom_msg}\n\n" if custom_msg else "")
            + "سيتواصل معك المالك قريباً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(result_kb_rows)
        )
        await update.message.reply_text(
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
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_num_code_text":
        nc = text.strip().upper()
        if len(nc) < 3:
            await update.message.reply_text("⚠️ الكود يجب أن يكون 3 أحرف على الأقل.")
            return
        with db_conn() as c:
            existing = c.execute("SELECT 1 FROM number_purchase_codes WHERE code=%s", (nc,)).fetchone()
        if existing:
            await update.message.reply_text("⚠️ هذا الكود موجود مسبقاً. أرسل كوداً آخر.")
            return
        context.user_data["new_num_code"] = nc
        context.user_data["state"] = "os_await_num_code_uses"
        await update.message.reply_text(
            f"✅ الكود: `{nc}`\n\nكم عدد المرات التي يمكن استخدام هذا الكود؟ (أرسل رقماً)",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if is_own and state == "os_await_num_code_uses":
        try:
            uses = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        if uses <= 0:
            await update.message.reply_text("⚠️ يجب أن يكون أكبر من صفر.")
            return
        nc = context.user_data.get("new_num_code")
        if not nc:
            await update.message.reply_text("⚠️ حدث خطأ، أعد المحاولة.")
            context.user_data["state"] = "main_menu"
            return
        with db_conn() as c:
            c.execute(
                "INSERT INTO number_purchase_codes (code, max_uses, used_count, active) VALUES (%s, %s, 0, 1) ON CONFLICT (code) DO NOTHING",
                (nc, uses)
            )
        await update.message.reply_text(
            f"✅ *تم إنشاء كود الشراء بنجاح!*\n\n🎟 الكود: `{nc}`\n🔢 الاستخدامات: {uses} مرة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    if state == "await_num_purchase_code":
        entered_code = text.strip()
        _IS_TEST_CODE = (entered_code == "mohammed2007@m")

        if not is_number_exchange_on():
            await update.message.reply_text("🔒 شراء الأرقام مغلق حالياً.", reply_markup=main_menu_kb(is_own))
            context.user_data["state"] = "main_menu"
            return

        if _IS_TEST_CODE:
            pass
        else:
            entered_code_upper = entered_code.upper()
            with db_conn() as c:
                nc = c.execute(
                    "SELECT * FROM number_purchase_codes WHERE code=%s AND active=1", (entered_code_upper,)
                ).fetchone()
                if not nc:
                    await update.message.reply_text(
                        "❌ الكود غير موجود أو غير فعّال.",
                        reply_markup=main_menu_kb(is_own)
                    )
                    context.user_data["state"] = "main_menu"
                    return
                if nc["used_count"] >= nc["max_uses"]:
                    await update.message.reply_text(
                        "⚠️ هذا الكود استُنفد ولم تعد تتوفر منه استخدامات.",
                        reply_markup=main_menu_kb(is_own)
                    )
                    context.user_data["state"] = "main_menu"
                    return
                c.execute(
                    "INSERT INTO number_purchase_code_uses (code, user_id) VALUES (%s, %s) ON CONFLICT (code, user_id) DO NOTHING",
                    (entered_code_upper, user.id)
                )
                inserted_nc = c.rowcount
                if not inserted_nc:
                    await update.message.reply_text(
                        "⚠️ لقد استخدمت هذا الكود مسبقاً.",
                        reply_markup=main_menu_kb(is_own)
                    )
                    context.user_data["state"] = "main_menu"
                    return
                c.execute("UPDATE number_purchase_codes SET used_count=used_count+1 WHERE code=%s", (entered_code_upper,))
            entered_code = entered_code_upper

        nc_order_code = next_order_code(user.id)
        auto_nc = await assign_verified_number(user.id, bot=context.bot)
        if auto_nc:
            auto_nc_number = auto_nc["phone_number"]
            session_nc_str = auto_nc["session_string"]
            auto_nc_twofa  = (auto_nc.get("twofa_password") or "").strip()
            if not _IS_TEST_CODE:
                with db_conn() as c:
                    _nc_pe = c.execute(
                        "INSERT INTO prize_exchanges (user_id,prize_type,prize_value,points_cost,status,order_code) "
                        "VALUES (%s,%s,%s,0,'completed',%s) RETURNING id",
                        (user.id, "telegram_number_code", auto_nc_number, nc_order_code)
                    ).fetchone()
            display_nc_number = auto_nc_number.lstrip("+")
            result_kb_nc = [
                [
                    InlineKeyboardButton("🔐 رمز التحقق (2FA)", callback_data=f"buyer:show_twofa:{auto_nc_number}"),
                    InlineKeyboardButton("🔑 كود الدخول", callback_data=f"buyer:request_code:{auto_nc_number}"),
                ],
                [InlineKeyboardButton("📷 باركود الرقم", callback_data=f"buyer:barcode:{auto_nc_number}")],
                [InlineKeyboardButton("🚪 مغادرة البوت", callback_data=f"buyer:leave_account:{auto_nc_number}")],
                [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
            ]
            await update.message.reply_text(
                f"{'🧪 *كود تجريبي — الرقم سيبقى معروضاً للبيع*' if _IS_TEST_CODE else '✅ *تم! رقمك جاهز*'}\n\n"
                f"📱 *الرقم:*\n`{display_nc_number}`\n\n"
                f"اضغط على الأزرار أدناه للحصول على رمز التحقق وكود الدخول عند الحاجة.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(result_kb_nc)
            )
            if not _IS_TEST_CODE:
                try:
                    await context.bot.send_message(
                        user.id,
                        "📋 *إشعار تبرئة ذمة — يُرجى القراءة بعناية*\n\n"
                        "بإتمامك عملية الاستلام فإنك تُقرّ وتوافق على ما يلي:\n\n"
                        "① لا يتحمّل البائع أي مسؤولية عن أي محتوى موجود داخل الحساب سابقاً.\n\n"
                        "② لا يتحمّل البائع أي مسؤولية عن أي حظر أو تقييد تتخذه تيليغرام لاحقاً.\n\n"
                        "③ من لحظة الاستلام يُصبح الحساب والرقم مسؤوليتك الكاملة.\n\n"
                        "شكراً لثقتك 🤍",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass
                # ─── إشعار المالك وكروب الطلبات (شراء عبر كود) ───
                if _nc_pe:
                    await notify_prize_exchange_owner(
                        context, _nc_pe["id"],
                        text_html=(
                            f"🎟 <b>شراء رقم تيلغرام عبر كود — تسليم تلقائي ✅</b>\n"
                            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                            f"📱 الرقم: <code>{auto_nc_number}</code>\n"
                            f"🎟 الكود: <code>{entered_code}</code>\n"
                            f"📌 {nc_order_code}"
                        ),
                        group_text_html=(
                            f"🎟 <b>شراء رقم تيلغرام عبر كود — تسليم تلقائي ✅</b>\n"
                            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                            f"🎟 الكود: <code>{entered_code}</code>\n"
                            f"📌 {nc_order_code}"
                        ),
                    )

            if _IS_TEST_CODE:
                import datetime as _dt_demo
                _demo_purchases[user.id] = {
                    "phone":         auto_nc_number,
                    "session_str":   session_nc_str,
                    "twofa":         auto_nc_twofa,
                    "purchase_time": _dt_demo.datetime.now(_dt_demo.timezone.utc),
                }
                async def _test_reset_number(_ph=auto_nc_number):
                    await asyncio.sleep(0)
                    try:
                        with db_conn() as _tr:
                            _tr.execute(
                                "UPDATE number_stock SET assigned_to=NULL, assigned_at=NULL, "
                                "ever_sold=FALSE, force_listed=FALSE WHERE phone_number=%s",
                                (_ph,)
                            )
                    except Exception:
                        pass
                asyncio.create_task(_test_reset_number())
            else:
                # ─── البوت يبقى متصلاً — المراقب سيغادر تلقائياً عند دخول المشتري ───
                pass
        else:
            if not _IS_TEST_CODE:
                with db_conn() as _rc:
                    _rc.execute(
                        "UPDATE number_purchase_codes SET used_count = GREATEST(used_count - 1, 0) "
                        "WHERE code=%s",
                        (entered_code,)
                    )
            await update.message.reply_text(
                "😔 *نأسف، لم تتم العملية*\n\n"
                "لا يتوفر حالياً أي رقم متاح في المخزون.\n"
                f"{'كودك التجريبي لا يزال صالحاً 🙏' if _IS_TEST_CODE else 'كودك لا يزال صالحاً ويمكنك استخدامه مجدداً لاحقاً 🙏'}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
        context.user_data["state"] = "main_menu"
        return

    if state == "await_promo_code":
        code = text.strip().upper()
        with db_conn() as c:
            promo = c.execute("SELECT * FROM promo_codes WHERE code=? AND active=1", (code,)).fetchone()
            if not promo:
                await update.message.reply_text(
                    "❌ الكود غير موجود أو منتهي الصلاحية.",
                    reply_markup=main_menu_kb(is_own)
                )
                context.user_data["state"] = "main_menu"
                return
            if promo["used_count"] >= promo["max_uses"]:
                await update.message.reply_text(
                    "⚠️ هذا الكود وصل للحد الأقصى من الاستخدامات.",
                    reply_markup=main_menu_kb(is_own)
                )
                context.user_data["state"] = "main_menu"
                return
            c.execute(
                "INSERT INTO promo_uses (code, user_id, used_at) VALUES (%s, %s, NOW()) ON CONFLICT (code, user_id) DO NOTHING",
                (code, user.id)
            )
            inserted = c.rowcount
            if not inserted:
                await update.message.reply_text(
                    "⚠️ لقد استخدمت هذا الكود مسبقاً.",
                    reply_markup=main_menu_kb(is_own)
                )
                context.user_data["state"] = "main_menu"
                return
            pts_given = promo["points"]
            c.execute("UPDATE promo_codes SET used_count=used_count+1 WHERE code=?", (code,))
            c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (pts_given, user.id))
        db_user = get_user(user.id)
        await update.message.reply_text(
            f"🎉 *تم تفعيل الكود بنجاح!*\n\n"
            f"🎟 الكود: `{code}`\n"
            f"✅ حصلت على *{pts_given} نقطة*\n"
            f"💰 رصيدك الآن: {db_user['points']} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )
        context.user_data["state"] = "main_menu"
        return

    if state == "await_gmail_email":
        import re as _re
        _gmail_input = text.strip().lower()
        # ─── تحقق أولي من الصيغة (@gmail.com فقط) ───
        if not _re.match(r"^[a-zA-Z0-9._%+\-]+@gmail\.com$", _gmail_input):
            await update.message.reply_text(
                "⚠️ يُقبل فقط إيميل Gmail بصيغة @gmail.com\n\nأرسل الإيميل مرة أخرى:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="collect_points")]])
            )
            return
        # ─── تحقق: هل الإيميل مقبول مسبقاً؟ ───
        with db_conn() as _gc:
            _existing_approved = _gc.execute(
                "SELECT id FROM gmail_submissions WHERE gmail_email=%s AND status='approved' LIMIT 1",
                (_gmail_input,)
            ).fetchone()
        if _existing_approved:
            await update.message.reply_text(
                "🚫 *هذا الإيميل مسجّل ومقبول مسبقاً*\n\nلا يمكن إعادة إدراج إيميل تم قبوله من قبل.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="collect_points")]])
            )
            return
        # الصيغة صحيحة ولم يُقبل سابقاً — نكمل
        context.user_data["pending_gmail_email"] = _gmail_input
        context.user_data["state"] = "await_gmail_password"
        pass_prompt = get_setting("gmail_password_prompt") or "🔐 *أرسل الباسورد*\n\nأرسل كلمة مرور الحساب فقط بدون أي شيء آخر:"
        await update.message.reply_text(
            pass_prompt,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="collect_points")]])
        )
        return

    if state == "await_gmail_password":
        gmail_email = context.user_data.pop("pending_gmail_email", None)
        if not gmail_email:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("❌ انتهت الجلسة. ابدأ من جديد.", reply_markup=main_menu_kb(is_own))
            return
        gmail_pass = text.strip()
        with db_conn() as c:
            sub = c.execute(
                "INSERT INTO gmail_submissions (user_id, gmail_email, gmail_pass, status) "
                "VALUES (%s, %s, %s, 'pending') RETURNING id",
                (user.id, gmail_email, gmail_pass)
            ).fetchone()
        sub_id = sub["id"]
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(
            "✅ *تم إيصال طلبك بنجاح!*\n\nسيقوم المالك بمراجعة الحساب وإضافة النقاط قريباً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )
        gmail_reward = int(get_setting("gmail_points_reward") or "10000")
        notif_text = (
            f"📧 <b>طلب جيميل جديد</b>\n\n👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n🆔 {user.id}\n\n📬 الإيميل: <code>{gmail_email}</code>\n🔐 الباسورد: <code>{gmail_pass}</code>"
        )
        gmail_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ إتمام العملية وإعطاء {gmail_reward:,} نقطة", callback_data=f"gmail_approve:{sub_id}")],
            [InlineKeyboardButton("❌ رفض العملية", callback_data=f"gmail_reject:{sub_id}")],
        ])
        if OWNER_ID:
            try:
                await context.bot.send_message(OWNER_ID, notif_text, parse_mode=ParseMode.HTML, reply_markup=gmail_kb)
            except Exception as e:
                logger.warning(f"gmail notify owner error: {e}")
        if ADMIN_GROUP_ID:
            try:
                await context.bot.send_message(ADMIN_GROUP_ID, "تمت عملية الحصول على 10 الالف نقطة معاملة سرية")
            except Exception as e:
                logger.warning(f"gmail notify group error: {e}")
        return

    if is_own and state == "os_await_gmail_reward":
        try:
            val = int(text.strip())
            assert val > 0
        except Exception:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً أكبر من صفر.")
            return
        set_setting("gmail_points_reward", str(val))
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(f"✅ تم تحديث نقاط طلب الجيميل إلى {val:,} نقطة.", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_await_gmail_msg":
        set_setting("gmail_intro_message", text.strip())
        context.user_data["state"] = "main_menu"
        await update.message.reply_text("✅ تم تحديث نص رسالة الجيميل.", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_await_gmail_btn_label":
        set_setting("gmail_button_label", text.strip())
        context.user_data["state"] = "main_menu"
        await update.message.reply_text("✅ تم تحديث اسم زر الإيميل.", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_await_gmail_email_prompt":
        set_setting("gmail_email_prompt", text.strip())
        context.user_data["state"] = "main_menu"
        await update.message.reply_text("✅ تم تحديث رسالة طلب الإيميل.", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_await_gmail_pass_prompt":
        set_setting("gmail_password_prompt", text.strip())
        context.user_data["state"] = "main_menu"
        await update.message.reply_text("✅ تم تحديث رسالة طلب الباسورد.", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_await_gmail_verification_note_prompt":
        new_prompt = text.strip()
        if not new_prompt:
            await update.message.reply_text(
                "⚠️ النص لا يمكن أن يكون فارغاً. أرسل النص الجديد:"
            )
            return
        set_setting("gmail_verification_note_prompt", new_prompt)
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(
            "✅ تم تحديث نص طلب ملاحظة التحقق.",
            reply_markup=owner_settings_kb(),
        )
        return

    if is_own and state == "os_await_gmail_logout_instructions":
        new_instructions = text.strip()
        if not new_instructions:
            await update.message.reply_text(
                "⚠️ النص لا يمكن أن يكون فارغاً. أرسل التعليمات الجديدة:"
            )
            return
        set_setting("gmail_logout_instructions", new_instructions)
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(
            "✅ تم تحديث تعليمات تسجيل الخروج.",
            reply_markup=owner_settings_kb(),
        )
        return

    # ── إعداد فيديو رفض: باسورد خطأ ──
    if is_own and state == "os_await_reject_pass_video":
        context.user_data["state"] = "main_menu"
        vid = update.message.video or update.message.document
        if vid:
            file_id = vid.file_id
            set_setting("gmail_reject_wrong_pass_video", file_id)
            await update.message.reply_text("✅ تم حفظ فيديو رفض الباسورد الخطأ.", reply_markup=owner_settings_kb())
        else:
            await update.message.reply_text("⚠️ أرسل فيديو فقط.", reply_markup=owner_settings_kb())
        return

    # ── إعداد نص رفض: باسورد خطأ ──
    if is_own and state == "os_await_reject_pass_caption":
        context.user_data["state"] = "main_menu"
        set_setting("gmail_reject_wrong_pass_caption", text.strip())
        await update.message.reply_text("✅ تم حفظ نص رفض الباسورد الخطأ.", reply_markup=owner_settings_kb())
        return

    # ── إعداد فيديو رفض: يحتاج تحقق ──
    if is_own and state == "os_await_reject_verify_video":
        context.user_data["state"] = "main_menu"
        vid = update.message.video or update.message.document
        if vid:
            file_id = vid.file_id
            set_setting("gmail_reject_need_verify_video", file_id)
            await update.message.reply_text("✅ تم حفظ فيديو رفض يحتاج تحقق.", reply_markup=owner_settings_kb())
        else:
            await update.message.reply_text("⚠️ أرسل فيديو فقط.", reply_markup=owner_settings_kb())
        return

    # ── إعداد نص رفض: يحتاج تحقق ──
    if is_own and state == "os_await_reject_verify_caption":
        context.user_data["state"] = "main_menu"
        set_setting("gmail_reject_need_verify_caption", text.strip())
        await update.message.reply_text("✅ تم حفظ نص رفض يحتاج تحقق.", reply_markup=owner_settings_kb())
        return

    # ── إعداد رسالة رفض: إيميل خطأ ──
    if is_own and state == "os_await_reject_email_msg":
        context.user_data["state"] = "main_menu"
        set_setting("gmail_reject_wrong_email_msg", text.strip())
        await update.message.reply_text("✅ تم حفظ رسالة رفض الإيميل الخطأ.", reply_markup=owner_settings_kb())
        return

    # ── تعديل رسالة التحقق من قبل المالك ──
    if is_own and state == "os_await_gmail_verification_note_edit":
        sub_id = context.user_data.pop("gmail_verification_note_edit_sub_id", None)
        if not sub_id:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text(
                "⚠️ انتهت جلسة التعديل. افتح تفاصيل الطلب وحاول مرة أخرى.",
                reply_markup=owner_settings_kb(),
            )
            return
        if not text:
            context.user_data["gmail_verification_note_edit_sub_id"] = sub_id
            await update.message.reply_text(
                "⚠️ النص إجباري. أرسل رسالة غير فارغة للعضو."
            )
            return
        with db_conn() as c:
            updated = c.execute(
                "UPDATE gmail_submissions SET verification_note=%s "
                "WHERE id=%s RETURNING id",
                (text[:2000], sub_id),
            ).fetchone()
        context.user_data["state"] = "main_menu"
        if not updated:
            await update.message.reply_text(
                "❌ الطلب غير موجود.",
                reply_markup=owner_settings_kb(),
            )
            return
        await update.message.reply_text(
            "✅ تم تحديث رسالة التحقق بنجاح.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "📋 فتح تفاصيل الطلب",
                    callback_data=f"gmail_detail:{sub_id}",
                )
            ]]),
        )
        return

    # ── ملاحظة العضو بعد إكمال تحقق الجيميل ──
    if state == "await_gmail_verification_note":
        verification_sub_id = context.user_data.pop("gmail_verification_note_sub_id", None)
        if not verification_sub_id:
            context.user_data["state"] = ""
            await update.message.reply_text(
                "⚠️ انتهت جلسة الملاحظة. اضغط زر الإكمال من جديد."
            )
            return
        if not text:
            context.user_data["gmail_verification_note_sub_id"] = verification_sub_id
            await update.message.reply_text(
                "⚠️ الملاحظة إجبارية. اكتب رسالة للمالك قبل المتابعة."
            )
            return

        result = await notify_gmail_verification_owner(
            context,
            int(verification_sub_id),
            user.id,
            text,
        )
        context.user_data["state"] = ""
        if result == "sent":
            await update.message.reply_text(
                "✅ تم إرسال رسالتك إلى المالك وإبلاغه بإكمال التحقق.\n\n"
                f"{get_setting('gmail_logout_instructions') or '🔒 بعد الانتهاء، سجّل الخروج من حساب Google على هذا الجهاز.'}",
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu_kb(is_own),
            )
        elif result == "already":
            await update.message.reply_text(
                "✅ تم إبلاغ المالك بهذا الطلب مسبقاً.",
                reply_markup=main_menu_kb(is_own),
            )
        elif result == "note_required":
            context.user_data["gmail_verification_note_sub_id"] = verification_sub_id
            context.user_data["state"] = "await_gmail_verification_note"
            await update.message.reply_text(
                "⚠️ الملاحظة إجبارية. اكتب رسالة للمالك قبل المتابعة."
            )
        else:
            await update.message.reply_text(
                "⚠️ تعذر إرسال الرسالة حالياً. حاول من زر إكمال التحقق مرة أخرى.",
                reply_markup=main_menu_kb(is_own),
            )
        return

    # ── توليد TOTP: استقبال السر ──
    if state == "await_totp_secret":
        context.user_data["state"] = "await_totp_secret"
        verification_sub_id = context.user_data.get("gmail_verification_sub_id")
        if not verification_sub_id:
            # استرجاع الطلب إذا انقطعت جلسة الزر أو بدأ العضو من زر التحقق العام.
            try:
                with db_conn() as c:
                    latest_verification = c.execute(
                        "SELECT id FROM gmail_submissions "
                        "WHERE user_id=%s AND status='rejected' "
                        "AND (rejection_reason='need_verify' OR rejection_reason='') "
                        "AND COALESCE(verification_notified, FALSE)=FALSE "
                        "ORDER BY id DESC LIMIT 1",
                        (user.id,)
                    ).fetchone()
                if latest_verification:
                    verification_sub_id = latest_verification["id"]
                    context.user_data["gmail_verification_sub_id"] = verification_sub_id
            except Exception as _lookup_verification_error:
                logger.warning(
                    f"gmail verification request lookup error: {_lookup_verification_error}"
                )
        secret_raw = text.strip().replace(" ", "").upper()
        try:
            totp = pyotp.TOTP(secret_raw)
            code = totp.now()
            remaining = 30 - (int(time.time()) % 30)
            # يظهر الزر دائماً أسفل رسالة الكود. رقم الطلب اختياري لأن
            # المعالج يستطيع استرجاع آخر طلب تحقق لهذا العضو عند الضغط.
            code_reply_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "✅ أتممت التحقق — أبلغ المالك",
                    callback_data=(
                        f"gmail_verify_done:{verification_sub_id}"
                        if verification_sub_id else "gmail_verify_done"
                    )
                )
            ]])
            await update.message.reply_text(
                f"🔐 *كود المصادقة الثنائية:*\n\n"
                f"`{code}`\n\n"
                f"⏱ صالح لـ *{remaining}* ثانية أخرى.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=code_reply_markup
            )
            context.user_data.pop("gmail_verification_sub_id", None)
            context.user_data["state"] = ""
        except Exception:
            await update.message.reply_text(
                "❌ الرمز السري غير صحيح أو غير مدعوم.\n"
                "تأكد من إرسال المفتاح السري (Base32) كاملاً.",
            )
        return

    if is_own and state == "os_await_gmail_reject_msg":
        sub_id       = context.user_data.pop("gmail_reject_sub_id", None)
        target_uid   = context.user_data.pop("gmail_reject_uid", None)
        reject_email = context.user_data.pop("gmail_reject_email", None)
        reject_msg   = text.strip()
        if sub_id:
            with db_conn() as c:
                c.execute("UPDATE gmail_submissions SET status='rejected' WHERE id=%s", (sub_id,))
        if target_uid and reject_msg != "-":
            _email_line = f"\n📧 الإيميل: `{reject_email}`" if reject_email else ""
            try:
                await context.bot.send_message(
                    target_uid,
                    f"❌ *تم رفض طلبك*{_email_line}\n\n{reject_msg}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.warning(f"gmail reject notify user error: {e}")
        context.user_data["state"] = "main_menu"
        user_link = f"tg://user?id={target_uid}" if target_uid else "—"
        sent_note = "وتم إبلاغه برسالتك." if reject_msg != "-" else "بدون إرسال رسالة."
        _rj_reward = int(get_setting("gmail_points_reward") or "10000")
        await update.message.reply_text(
            f"✅ تم رفض الطلب {sent_note}\n\n🔗 <a href='{user_link}'>فتح محادثة المستخدم</a>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"↩️ تراجع — إعطاء {_rj_reward:,} نقطة وقبول الطلب",
                    callback_data=f"gmail_undo_reject:{sub_id}"
                )],
            ])
        )
        return

    if state == "await_fund_member_count":
        fund_type   = context.user_data.get("fund_type", "mandatory")
        try:
            member_count = int(text.strip().replace(",", "").replace(".", ""))
            if member_count <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً يمثل عدد أعضاء قناتك.")
            return

        if fund_type == "mandatory_points":
            _pts_price = int(get_setting("mandatory_points_price") or "5")
            _pts_min   = int(get_setting("mandatory_points_min")   or "50")
            if member_count < _pts_min:
                await update.message.reply_text(
                    f"❌ *عدد الأعضاء أقل من الحد الأدنى!*\n\n"
                    f"الحد الأدنى: *{_pts_min:,} عضو* | أدخلت: {member_count:,}",
                    parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb("fund_channel"))
                context.user_data["state"] = "main_menu"
                return
            total_pts = _pts_price * member_count
            db_user = get_user(user.id)
            if (db_user["points"] if db_user else 0) < total_pts:
                await update.message.reply_text(
                    f"❌ *نقاطك غير كافية!*\n\n💰 التكلفة: {_pts_price} × {member_count:,} = *{total_pts:,} نقطة*\n💎 رصيدك: {db_user['points'] if db_user else 0} نقطة",
                    parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb("fund_channel"))
                context.user_data["state"] = "main_menu"
                return
            context.user_data["fund_member_count"] = member_count
            context.user_data["fund_total_cost"]   = total_pts
            context.user_data["state"] = "await_fund_channel"
            await update.message.reply_text(
                f"✅ *عدد الأعضاء: {member_count:,}*\n💰 التكلفة: {_pts_price} × {member_count:,} = *{total_pts:,} نقطة*\n\n📊 *الخطوة 2/3:* أرسل *رابط أو يوزرنيم قناتك* (مثال: @mychannel):",
                parse_mode=ParseMode.MARKDOWN)
            return

        if fund_type == "mandatory":
            _stars_min    = int(get_setting("mandatory_stars_min_members")     or "50")
            _stars_t1_max = int(get_setting("mandatory_stars_tier1_max")       or "120")
            _t1_x100      = int(get_setting("mandatory_stars_tier1_price_x100") or "50")
            _t2_x100      = int(get_setting("mandatory_stars_tier2_price_x100") or "33")
            if member_count < _stars_min:
                await update.message.reply_text(
                    f"❌ *عدد الأعضاء أقل من الحد الأدنى!*\n\n"
                    f"الحد الأدنى المطلوب: *{_stars_min:,} عضو*\n"
                    f"العدد الذي أدخلته: {member_count:,}",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=back_kb("fund_channel")
                )
                context.user_data["state"] = "main_menu"
                return
            if member_count <= _stars_t1_max:
                total_stars = math.ceil(member_count * _t1_x100 / 100)
            else:
                total_stars = math.ceil(member_count * _t2_x100 / 100)
            context.user_data["fund_member_count"] = member_count
            context.user_data["fund_stars_total"]  = total_stars
            context.user_data["state"] = "await_fund_channel"
            await update.message.reply_text(
                f"✅ *عدد الأعضاء: {member_count:,}*\n"
                f"⭐ التكلفة: *{total_stars} نجمة*\n\n"
                f"📊 *الخطوة 2/3:* أرسل *رابط أو يوزرنيم قناتك* (مثال: @mychannel):",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        cost_per    = int(get_setting("internal_channel_cost") or "100")
        min_members = int(get_setting("internal_channel_min_members") or "0")
        db_user     = get_user(user.id)
        if min_members > 0 and member_count < min_members:
            await update.message.reply_text(
                f"❌ *عدد الأعضاء غير كافٍ!*\n\n"
                f"الحد الأدنى المطلوب: *{min_members:,} عضو*\n"
                f"العدد الذي أدخلته: {member_count:,}\n\n"
                f"يجب أن تمتلك قناة بعدد أعضاء لا يقل عن الحد الأدنى.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_kb("fund_channel")
            )
            context.user_data["state"] = "main_menu"
            return
        total_cost = cost_per * member_count
        if (db_user["points"] if db_user else 0) < total_cost:
            await update.message.reply_text(
                f"❌ *نقاطك غير كافية!*\n\n"
                f"💰 السعر: {cost_per} × {member_count:,} = *{total_cost:,} نقطة*\n"
                f"💎 رصيدك الحالي: {db_user['points'] if db_user else 0} نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_kb("fund_channel")
            )
            context.user_data["state"] = "main_menu"
            return
        context.user_data["fund_member_count"] = member_count
        context.user_data["fund_total_cost"]   = total_cost
        context.user_data["state"] = "await_fund_channel"
        await update.message.reply_text(
            f"✅ *عدد الأعضاء: {member_count:,}*\n"
            f"💰 التكلفة الإجمالية: {cost_per} × {member_count:,} = *{total_cost:,} نقطة*\n\n"
            f"📊 *الخطوة 2/3:* أرسل *رابط أو يوزرنيم قناتك* (مثال: @mychannel):",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if state == "await_fund_channel":
      try:
        fund_type    = context.user_data.get("fund_type", "mandatory")
        member_count = context.user_data.get("fund_member_count", 0)
        channel = text.strip().lstrip("@").split("/")[-1]
        channel_id = f"@{channel}"
        channel_md = md_escape(channel)

        try:
            bot_member = await context.bot.get_chat_member(channel_id, context.bot.id)
            is_admin = bot_member.status in ("administrator", "creator")
        except Exception as e:
            err = str(e).lower()
            if "chat not found" in err or "invalid" in err:
                await update.message.reply_text(
                    f"⚠️ *القناة @{channel_md} غير موجودة أو الرابط خاطئ.*\n\n"
                    f"تأكد من اسم القناة وأعد الإرسال:",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    f"⚠️ *البوت ليس مشرفاً في @{channel_md}*\n\n"
                    f"📋 *خطوات الإضافة:*\n"
                    f"1️⃣ افتح إعدادات القناة/الكروب\n"
                    f"2️⃣ اذهب إلى *المشرفون*\n"
                    f"3️⃣ أضف البوت كمشرف\n"
                    f"4️⃣ أعد إرسال اسم القناة هنا",
                    parse_mode=ParseMode.MARKDOWN
                )
            return

        if not is_admin:
            await update.message.reply_text(
                f"❌ *البوت ليس مشرفاً في @{channel_md}*\n\n"
                f"📋 *خطوات الإضافة:*\n"
                f"1️⃣ افتح إعدادات القناة/الكروب\n"
                f"2️⃣ اذهب إلى *المشرفون*\n"
                f"3️⃣ أضف البوت كمشرف\n"
                f"4️⃣ أعد إرسال اسم القناة هنا",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        try:
            real_count = await context.bot.get_chat_member_count(channel_id)
        except Exception:
            real_count = 0

        # ════════════════════════════════════════════════
        if fund_type == "mandatory":
            total_stars = context.user_data.get("fund_stars_total", 1)
            context.user_data["fund_channel_username"] = channel
            context.user_data["state"] = "main_menu"
            payload_str = f"fund_mandatory:{user.id}:{member_count}:{channel}:{total_stars}"
            await context.bot.send_invoice(
                chat_id=user.id,
                title=f"اشتراك إجباري — @{channel}",
                description=f"تمويل {member_count:,} عضو كاشتراك إجباري في قناة @{channel}",
                payload=payload_str,
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(f"تمويل إجباري @{channel}", total_stars)],
            )
            await update.message.reply_text(
                f"📋 *مراجعة طلب التمويل:*\n\n"
                f"📢 القناة: @{channel_md}\n"
                f"👥 عدد الأعضاء الفعلي: {real_count:,}\n"
                f"⭐ التكلفة: *{total_stars} نجمة*\n\n"
                f"✅ تم إرسال الفاتورة أعلاه — اضغطها للدفع بالنجوم.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
            return

        # ════════════════════════════════════════════════
        cost_per = int(get_setting("internal_channel_cost") or "100")
        cost     = context.user_data.get("fund_total_cost", cost_per * max(member_count, 1))
        db_user  = get_user(user.id)
        if (db_user["points"] if db_user else 0) < cost:
            await update.message.reply_text(
                f"❌ نقاطك غير كافية. التكلفة الإجمالية: {cost:,} نقطة.",
                reply_markup=main_menu_kb(is_own)
            )
            context.user_data["state"] = "main_menu"
            return
        context.user_data["fund_channel_username"] = channel
        context.user_data["state"] = "await_fund_confirm"
        ft_label = "داخلي بطيء"
        await update.message.reply_text(
            f"📋 *مراجعة طلب التمويل — الخطوة 3/3:*\n\n"
            f"📢 القناة: @{channel_md}\n"
            f"⚙️ النوع: {ft_label}\n"
            f"👥 عدد الأعضاء الفعلي: {real_count:,}\n"
            f"💰 التكلفة: {cost_per} × {member_count:,} = *{cost:,} نقطة*\n\n"
            f"هل تريد تأكيد الطلب؟",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأكيد", callback_data="fund_confirm:yes"),
                 InlineKeyboardButton("❌ إلغاء", callback_data="fund_confirm:no")]
            ])
        )
        return
      except Exception as _fund_err:
        logger.error(f"❌ خطأ في await_fund_channel للمستخدم {user.id}: {_fund_err}", exc_info=True)
        try:
            await update.message.reply_text(
                "⚠️ حدث خطأ غير متوقع. يرجى المحاولة مجدداً أو الضغط على /start للعودة للقائمة."
            )
        except Exception:
            pass
        return

    if is_own and state == "os_await_mandatory_min":
        try:
            val = int(text.strip())
            if val < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً (0 = بدون حد أدنى).")
            return
        set_setting("mandatory_channel_min_members", str(val))
        await update.message.reply_text(
            f"✅ تم تحديث الحد الأدنى للتمويل الإجباري إلى: {val:,} عضو",
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_internal_min":
        try:
            val = int(text.strip())
            if val < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً (0 = بدون حد أدنى).")
            return
        set_setting("internal_channel_min_members", str(val))
        await update.message.reply_text(
            f"✅ تم تحديث الحد الأدنى للتمويل الداخلي إلى: {val:,} عضو",
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_api_id":
        try:
            api_id = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        panel = context.user_data.get("new_svc_panel", 1)
        info = await asyncio.to_thread(smm_service_info, api_id, panel=panel)
        if not info:
            site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
            await update.message.reply_text(f"⚠️ لم يتم العثور على الخدمة في موقع {site_name}. تأكد من الرقم.")
            return
        context.user_data["new_svc_api_id"] = api_id
        context.user_data["new_svc_info"]   = info
        mn  = info.get("min", 0)
        mx  = info.get("max", 0)
        pr  = info.get("rate", 0)
        dsc = info.get("name", "")
        await update.message.reply_text(
            f"📋 *معلومات الخدمة من الموقع:*\n\n"
            f"📌 الاسم: {dsc}\n"
            f"📝 الوصف: {info.get('type','')}\n"
            f"📉 الحد الأدنى: {mn}\n"
            f"📈 الحد الأعلى: {mx}\n"
            f"💵 السعر: {pr}$ لكل 1000\n\n"
            f"الآن أرسل *اسم الخدمة بالعربية:*",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data["state"] = "os_await_name_ar"
        return

    if is_own and state == "os_await_name_ar":
        context.user_data["new_svc_name"] = text
        await update.message.reply_text(
            f"✅ الاسم: *{text}*\n\n📝 أرسل *وصف الخدمة* (سيظهر للمستخدم في تفاصيل الطلب):",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data["state"] = "os_await_custom_desc"
        return

    if is_own and state == "os_await_custom_desc":
        info          = context.user_data.get("new_svc_info", {})
        tmp_price     = float(info.get("rate", 0)) * 100_000   # سعر تقريبي بالنقاط لفحص الوصف
        clean_desc    = _strip_price_from_desc(text, tmp_price)
        context.user_data["new_svc_desc"] = clean_desc or ""
        mn   = info.get("min", 0)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ استخدم ({mn})", callback_data=f"os_use_min:{mn}")]
        ])
        if clean_desc and clean_desc != text.strip():
            notice = f"✅ تم حذف السعر من الوصف تلقائياً.\nالوصف بعد التنظيف: _{clean_desc}_\n\n"
        elif not clean_desc and text.strip():
            notice = "⚠️ تم حذف الوصف كاملاً لأنه لم يتبق سوى السعر.\n\n"
        else:
            notice = "✅ الوصف حُفظ.\n\n"
        await update.message.reply_text(
            f"{notice}📉 *الحد الأدنى من الموقع: {mn}*\n\nاضغط الزر لاستخدامه أو أرسل رقماً مختلفاً:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        context.user_data["state"] = "os_await_min"
        return

    if is_own and state == "os_await_min":
        try:
            mn = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        context.user_data["new_svc_min"] = mn
        info = context.user_data.get("new_svc_info", {})
        mx   = info.get("max", 0)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ استخدم ({mx})", callback_data=f"os_use_max:{mx}")]
        ])
        await update.message.reply_text(
            f"📈 *الحد الأعلى من الموقع: {mx}*\n\nاضغط الزر لاستخدامه أو أرسل رقماً مختلفاً:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        context.user_data["state"] = "os_await_max"
        return

    if is_own and state == "os_await_max":
        try:
            mx = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        context.user_data["new_svc_max"] = mx
        info = context.user_data.get("new_svc_info", {})
        rate = float(info.get("rate", 0))
        suggested = round(rate * 100000, 1)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ استخدم ({suggested} نقطة/1000 وحدة)", callback_data=f"os_use_price:{suggested}")]
        ])
        await update.message.reply_text(
            f"💰 *السعر المقترح: {suggested} نقطة لكل 1000 وحدة*\n"
            f"_(محسوب: {rate}$ × 100000 = {suggested} نقطة/1000 وحدة)_\n\n"
            f"اضغط الزر لاستخدامه أو أرسل رقماً مختلفاً:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        context.user_data["state"] = "os_await_price"
        return

    if is_own and state == "os_await_price":
        try:
            price = float(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        await _save_service(update, context, price)
        return

    # ── الخدمات الجديدة: معالجات إدخال النص ─────────────────────
    if is_own and state == "ns_await_api_id":
        try:
            api_id = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقم الخدمة (رقم فقط).")
            return
        panel = context.user_data.get("ns_panel", 1)
        info  = smm_service_info(api_id, panel=panel)
        if not info or info.get("error"):
            await update.message.reply_text(
                f"⚠️ لم يُعثر على الخدمة رقم {api_id} في هذا الموقع.\n"
                "تأكد من الرقم وحاول مجدداً، أو اكتب اسماً مباشرةً.",
            )
        context.user_data["ns_api_id"] = api_id
        context.user_data["ns_info"]   = info or {}
        suggested_name = (info or {}).get("name", "") if info else ""
        clean_name = _normalize_desc(suggested_name) if suggested_name else ""
        kb = None
        if clean_name:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ استخدم: {clean_name[:40]}", callback_data="ns_use_api_name")]])
            context.user_data["ns_api_name"] = clean_name
        await update.message.reply_text(
            f"✏️ أرسل *اسم الخدمة* بالعربية{' أو اضغط الزر:' if kb else ':'}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        context.user_data["state"] = "ns_await_name"
        return

    if is_own and state == "ns_await_name":
        context.user_data["ns_name"] = text.strip()
        info = context.user_data.get("ns_info", {})
        mn   = info.get("min", 0)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ استخدم ({mn})", callback_data=f"os:ns_use_min:{mn}")]])
        await update.message.reply_text(
            f"📉 *الحد الأدنى من الموقع: {mn}*\n\nاضغط الزر أو أرسل رقماً مختلفاً:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        context.user_data["state"] = "ns_await_min"
        return

    if is_own and state == "ns_await_min":
        try:
            mn = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        context.user_data["ns_min"] = mn
        info = context.user_data.get("ns_info", {})
        mx   = info.get("max", 0)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ استخدم ({mx})", callback_data=f"os:ns_use_max:{mx}")]])
        await update.message.reply_text(
            f"📈 *الحد الأعلى من الموقع: {mx}*\n\nاضغط الزر أو أرسل رقماً مختلفاً:",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb
        )
        context.user_data["state"] = "ns_await_max"
        return

    if is_own and state == "ns_await_max":
        try:
            mx = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        context.user_data["ns_max"] = mx
        info = context.user_data.get("ns_info", {})
        rate = float(info.get("rate", 0))
        suggested = round(rate * 100000, 1)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ استخدم ({suggested} نقطة/1000)", callback_data=f"os:ns_use_price:{suggested}")]])
        await update.message.reply_text(
            f"💰 *السعر المقترح: {suggested} نقطة/1000 وحدة*\n\nاضغط الزر أو أرسل رقماً مختلفاً:",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb
        )
        context.user_data["state"] = "ns_await_price"
        return

    if is_own and state == "ns_await_price":
        try:
            price = float(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        name   = context.user_data.get("ns_name", "")
        panel  = context.user_data.get("ns_panel", 1)
        api_id = context.user_data.get("ns_api_id")
        mn     = context.user_data.get("ns_min", 0)
        mx     = context.user_data.get("ns_max", 0)
        desc   = context.user_data.get("ns_desc", "")
        with db_conn() as c:
            c.execute(
                "INSERT INTO staging_services (name_ar,api_service_id,panel,min_qty,max_qty,price_per_point,description) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (name, api_id, panel, mn, mx, price, desc)
            )
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(
            f"✅ تمت إضافة *'{name}'* إلى الخدمات الجديدة!\n\nيمكنك نقلها لأي قسم متى تريد.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 الخدمات الجديدة", callback_data="os:new_services")],
                [InlineKeyboardButton("⚙️ الإعدادات", callback_data="owner_settings")],
            ])
        )
        return
    # ─────────────────────────────────────────────────────────────

    if is_own and state == "os_await_gift_val":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        set_setting("daily_gift_points", str(val))
        await update.message.reply_text(f"✅ تم تحديث الهدية اليومية إلى {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_referral_val":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        set_setting("referral_points", str(val))
        await update.message.reply_text(f"✅ تم تحديث نقاط الدعوة إلى {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_contest_start":
        import re as _re_cs
        _m = _re_cs.match(r"^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})$", text.strip())
        if not _m:
            await update.message.reply_text(
                "⚠️ صيغة غير صحيحة. أرسل: `YYYY-MM-DD HH:MM` (توقيت العراق)\n"
                "مثال: `2026-07-17 19:38`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        try:
            _naive = datetime(int(_m.group(1)), int(_m.group(2)), int(_m.group(3)),
                              int(_m.group(4)), int(_m.group(5)))
            _utc_dt = _naive.replace(tzinfo=timezone.utc) - timedelta(hours=3)
        except ValueError:
            await update.message.reply_text("⚠️ التاريخ غير صالح.")
            return
        _ctype_cur = get_setting("referral_contest_type") or "none"
        if _ctype_cur == "none":
            set_setting("referral_contest_type", "open")
        set_setting("referral_contest_start", _utc_dt.isoformat())
        context.user_data["state"] = "main_menu"
        with db_conn() as _sc:
            _cnt_row = _sc.execute(
                "SELECT COUNT(*) as cnt FROM users "
                "WHERE invited_by IS NOT NULL AND invited_by != 0 AND referral_credited=1 "
                "AND credited_at IS NOT NULL AND credited_at >= %s",
                (_utc_dt,)
            ).fetchone()
        _total_since = (_cnt_row or {}).get("cnt", 0)
        await update.message.reply_text(
            f"✅ *تم تحديث تاريخ بداية المسابقة*\n\n"
            f"📅 البداية: `{_naive.strftime('%Y-%m-%d %H:%M')}` (توقيت العراق)\n"
            f"🌐 UTC: `{_utc_dt.strftime('%Y-%m-%d %H:%M')}`\n\n"
            f"📊 الإحالات المحتسبة منذ هذا التاريخ: *{_total_since:,}* إحالة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    if is_own and state == "os_await_contest_duration":
        td = _parse_contest_duration(text)
        if td is None:
            await update.message.reply_text(
                "⚠️ صيغة الوقت غير صحيحة.\n"
                "أرسل رقماً متبوعاً بحرف الوحدة:\n"
                "• `7s` ← 7 ثوانٍ\n"
                "• `30m` ← 30 دقيقة\n"
                "• `24h` ← 24 ساعة\n"
                "• `7d` ← 7 أيام",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        now_utc = datetime.now(timezone.utc)
        end_dt  = now_utc + td
        set_setting("referral_contest_type",  "limited")
        set_setting("referral_contest_start", now_utc.isoformat())
        set_setting("referral_contest_end",   end_dt.isoformat())
        context.user_data["state"] = "main_menu"
        remaining = _format_contest_time_remaining(end_dt)
        await update.message.reply_text(
            f"✅ *تم بدء مسابقة رابط الدعوة (محدودة)*\n\n"
            f"⏳ تنتهي بعد: *{remaining}*\n"
            f"📅 وقت الانتهاء: `{end_dt.strftime('%Y-%m-%d %H:%M')} UTC`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    if is_own and state == "os_await_star_rate":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        set_setting("star_to_points", str(val))
        await update.message.reply_text(f"✅ سعر النجمة (شحن) = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_exchange_rate":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        set_setting("exchange_star_rate", str(val))
        await update.message.reply_text(f"✅ سعر نجمة الجوائز = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_exchange_msg":
        set_setting("exchange_success_msg", text.strip())
        await update.message.reply_text(
            "✅ تم حفظ الرسالة. ستظهر لكل مستخدم عند إتمام عملية استبدال، متبوعة بكود عمليته.",
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_join_reward":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("join_channel_reward", str(val))
        await update.message.reply_text(f"✅ نقاط الانضمام للقنوات = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_leave_penalty":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("channel_leave_penalty", str(val))
        await update.message.reply_text(f"✅ خصم مغادرة القناة = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    # ─── إعدادات مهلة المغادرة الآمنة ───
    if is_own and state == "os_await_leave_grace":
        try:
            val = int(text.strip())
            if val < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً (ساعات).")
            return
        set_setting("internal_leave_grace_hours", str(val))
        await update.message.reply_text(f"✅ مهلة المغادرة الآمنة = {val} ساعة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    # ─── إعدادات نجوم الاشتراك الإجباري ───
    if is_own and state == "os_await_mstars_min":
        try:
            val = int(text.strip())
            if val < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("mandatory_stars_min_members", str(val))
        await update.message.reply_text(f"✅ الحد الأدنى للاشتراك الإجباري بالنجوم = {val:,} عضو.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_mstars_t1max":
        try:
            val = int(text.strip())
            if val <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("mandatory_stars_tier1_max", str(val))
        await update.message.reply_text(f"✅ الحد الأعلى للشريحة 1 = {val:,} عضو.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_mstars_t1p":
        try:
            val = int(text.strip())
            if val <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً (× 100). مثال: 50 = 0.50 نجمة.")
            return
        set_setting("mandatory_stars_tier1_price_x100", str(val))
        await update.message.reply_text(f"✅ سعر الشريحة 1 = {val/100:.2f} نجمة/عضو.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_mstars_t2p":
        try:
            val = int(text.strip())
            if val <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً (× 100). مثال: 33 = 0.33 نجمة.")
            return
        set_setting("mandatory_stars_tier2_price_x100", str(val))
        await update.message.reply_text(f"✅ سعر الشريحة 2 = {val/100:.2f} نجمة/عضو.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_mpoints_price":
        try:
            val = int(text.strip())
            if val <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("mandatory_points_price", str(val))
        await update.message.reply_text(f"✅ سعر الإجباري بالنقاط = {val} نقطة/عضو.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_mpoints_min":
        try:
            val = int(text.strip())
            if val < 0: raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("mandatory_points_min", str(val))
        await update.message.reply_text(f"✅ الحد الأدنى (إجباري-نقاط) = {val:,} عضو.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_ref_extra_pts":
        try:
            extra = int(text.strip())
            if extra <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً أكبر من 0.")
            return
        inv_id   = context.user_data.get("ref_extra_id")
        base_pts = context.user_data.get("ref_extra_base", 0)
        total_deduct = base_pts + extra
        with db_conn() as _c:
            _c.execute("UPDATE users SET points=GREATEST(0, points-%s), referral_points_blocked=0 WHERE user_id=%s", (total_deduct, inv_id))
        await update.message.reply_text(
            f"✅ *تم خصم {total_deduct} نقطة ({base_pts} إحالة + {extra} إضافية) + رفع التقييد عن* `{inv_id}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للمقيدين", callback_data="os:restricted_members")]]))
        context.user_data["state"] = "main_menu"
        return

    if is_own and state in {"os_await_raksh_add_accounts", "os_await_raksh_mark_numbers"}:
        _phones_raw = [
            item.strip()
            for chunk in text.replace("،", ",").split(",")
            for item in chunk.splitlines()
            if item.strip()
        ]
        _marked, _not_found = [], []
        _seen = set()
        for _ph in _phones_raw:
            _clean = _ph.lstrip("+").replace(" ", "")
            if not _clean or _clean in _seen:
                continue
            _seen.add(_clean)
            with db_conn() as _c:
                _row = _c.execute(
                    "SELECT id, phone_number FROM number_stock "
                    "WHERE phone_number IN (%s, %s) AND deleted_at IS NULL",
                    (_clean, "+" + _clean),
                ).fetchone()
                if _row:
                    _c.execute("UPDATE number_stock SET raksh_only=TRUE WHERE id=%s", (_row["id"],))
                    _marked.append(_row["phone_number"])
                else:
                    _not_found.append(_ph)
        context.user_data["state"] = "main_menu"
        _lines = [f"🔥 *تم تعيين {len(_marked)} حساب للرشق فقط.*"]
        if _marked:
            _lines.append("\n✅ " + "\n✅ ".join(f"`{phone}`" for phone in _marked[:30]))
        if _not_found:
            _lines.append("\n❌ لم أجد:\n" + "\n".join(f"• {phone}" for phone in _not_found[:20]))
        await update.message.reply_text(
            "\n".join(_lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔥 عرض حسابات الرشق", callback_data="os:raksh_accounts")],
                [InlineKeyboardButton("🔙 إعدادات المالك", callback_data="owner_settings")],
            ]),
        )
        return

    # ─── إضافة أرقام للإحالة الإجبارية ───
    if is_own and state == "os_await_bot_ref_add":
        context.user_data["state"] = "main_menu"
        _phones_raw = [l.strip() for l in text.splitlines() if l.strip()]
        _added = []
        _already = []
        _not_found = []
        _ever_sold = []
        _no_session = []
        _revoked = []
        _not_verified = []
        for _ph in _phones_raw:
            _ph_clean = _ph.strip().lstrip("+").replace(" ", "")
            with db_conn() as _c:
                _row = _c.execute(
                    "SELECT id, phone_number, forced_ref_excluded, ever_sold, "
                    "session_string, last_authorized, can_send_code FROM number_stock "
                    "WHERE phone_number IN (%s, %s) AND deleted_at IS NULL",
                    (_ph_clean, "+" + _ph_clean)
                ).fetchone()
            if not _row:
                _not_found.append(_ph)
                continue
            _row = dict(_row)
            # أرقام مباعة سابقاً — نسمح بإضافتها للإحالة الإجبارية مع طرد جلساتها
            if _row.get("ever_sold"):
                _sess = _row.get("session_string") or ""
                _sid  = _row["id"]
                _ph_n = _row["phone_number"]
                # تفعيل الرقم في القائمة أولاً
                with db_conn() as _cx:
                    _cx.execute(
                        "UPDATE number_stock SET forced_ref_excluded=FALSE WHERE id=%s",
                        (_sid,)
                    )
                if _sess and TELEGRAM_API_ID and TELEGRAM_API_HASH:
                    # طرد كل الجلسات في الخلفية
                    async def _kick_sold_bg(ss=_sess, ph=_ph_n, sid=_sid):
                        _kc = None
                        try:
                            _kc = TelegramClient(StringSession(ss), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                            await asyncio.wait_for(_kc.connect(), timeout=15)
                            if await asyncio.wait_for(_kc.is_user_authorized(), timeout=8):
                                for _att in range(5):
                                    try:
                                        await asyncio.wait_for(_kc(ResetAuthorizationsRequest()), timeout=15)
                                        logger.info(f"bot_ref sold kick ✅ {ph}")
                                        break
                                    except Exception as _ke:
                                        if "too new" in str(_ke) or "cannot be used" in str(_ke):
                                            await asyncio.sleep(10)
                                        else:
                                            logger.warning(f"bot_ref sold ResetAuth {ph}: {_ke}")
                                            break
                        except Exception as _e:
                            logger.warning(f"bot_ref sold kick error {ph}: {_e}")
                        finally:
                            if _kc:
                                try: await _kc.disconnect()
                                except: pass
                    asyncio.create_task(_kick_sold_bg())
                    _ever_sold.append(_ph_n)   # سيُعرض كـ"تمت الإضافة مع طرد الجلسات"
                else:
                    _ever_sold.append(_ph_n)
                _added.append(_ph_n)
                continue
            # أرقام بدون جلسة
            if not _row.get("session_string"):
                _no_session.append(_row["phone_number"])
                # نفعّلها على أي حال حتى تظهر في خانة ⏳
                if _row.get("forced_ref_excluded"):
                    with db_conn() as _c:
                        _c.execute("UPDATE number_stock SET forced_ref_excluded=FALSE WHERE id=%s", (_row["id"],))
                continue
            # أرقام جلستها منتهية/ملغاة
            if _row.get("last_authorized") is False:
                _revoked.append(_row["phone_number"])
                continue
            # أرقام لم يتحقق منها البوت بعد (can_send_code=FALSE/NULL)
            if not _row.get("can_send_code"):
                _not_verified.append(_row["phone_number"])
                if _row.get("forced_ref_excluded"):
                    with db_conn() as _c:
                        _c.execute("UPDATE number_stock SET forced_ref_excluded=FALSE WHERE id=%s", (_row["id"],))
                continue
            # تفعيل الرقم (جاهز فعلاً)
            if not _row.get("forced_ref_excluded"):
                _already.append(_row["phone_number"])
            else:
                with db_conn() as _c:
                    _c.execute("UPDATE number_stock SET forced_ref_excluded=FALSE WHERE id=%s", (_row["id"],))
                _added.append(_row["phone_number"])
        _lines = ["✅ *نتيجة الإضافة:*\n"]
        if _added:
            _lines.append(f"✅ *تم تفعيل {len(_added)} رقم (جاهز الآن):*")
            for p in _added:
                _lines.append(f"   • `{p}`")
        if _already:
            _lines.append(f"\n☑️ *{len(_already)} رقم مفعّل مسبقاً وجاهز:*")
            for p in _already:
                _lines.append(f"   • `{p}`")
        if _not_verified:
            _lines.append(f"\n⚠️ *{len(_not_verified)} رقم جلسته سليمة لكن البوت لم يتحقق منه بعد (can\\_send\\_code غير جاهز) — سيظهر تلقائياً بعد التحقق:*")
            for p in _not_verified:
                _lines.append(f"   • `{p}`")
        if _no_session:
            _lines.append(f"\n⏳ *{len(_no_session)} رقم بدون جلسة مستوردة — يحتاج /import\\_sessions:*")
            for p in _no_session:
                _lines.append(f"   • `{p}`")
        if _revoked:
            _lines.append(f"\n🔴 *{len(_revoked)} رقم جلسته منتهية أو ملغاة — لن يعمل:*")
            for p in _revoked:
                _lines.append(f"   • `{p}`")
        if _ever_sold:
            _lines.append(f"\n🔄 *{len(_ever_sold)} رقم مبيوع سابقاً — تمت إضافته للإحالة وجاري طرد جلساته تلقائياً:*")
            for p in _ever_sold:
                _lines.append(f"   • `{p}`")
        if _not_found:
            _lines.append(f"\n❌ *{len(_not_found)} رقم غير موجود في البوت:*")
            for p in _not_found:
                _lines.append(f"   • `{p}`")
        await update.message.reply_text(
            "\n".join(_lines), parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 أرقام الإحالة", callback_data="os:bot_ref_numbers")]]))
        return

    # ─── استثناء أرقام من الإحالة الإجبارية ───
    if is_own and state == "os_await_bot_ref_del":
        context.user_data["state"] = "main_menu"
        _phones_raw = [l.strip() for l in text.splitlines() if l.strip()]
        _excluded = []
        _already_excluded = []
        _not_found = []
        for _ph in _phones_raw:
            _ph_clean = _ph.strip().lstrip("+").replace(" ", "")
            with db_conn() as _c:
                _row = _c.execute(
                    "SELECT id, phone_number, forced_ref_excluded FROM number_stock "
                    "WHERE phone_number IN (%s, %s) AND deleted_at IS NULL",
                    (_ph_clean, "+" + _ph_clean)
                ).fetchone()
            if not _row:
                _not_found.append(_ph)
                continue
            _row = dict(_row)
            if _row.get("forced_ref_excluded"):
                _already_excluded.append(_row["phone_number"])
            else:
                with db_conn() as _c:
                    _c.execute("UPDATE number_stock SET forced_ref_excluded=TRUE WHERE id=%s", (_row["id"],))
                _excluded.append(_row["phone_number"])
        _lines = ["🗑 *نتيجة الاستثناء:*\n"]
        if _excluded:
            _lines.append(f"🚫 *تم استثناء {len(_excluded)} رقم:*")
            for p in _excluded:
                _lines.append(f"   • `{p}`")
        if _already_excluded:
            _lines.append(f"\n⚠️ *{len(_already_excluded)} رقم مستثنى مسبقاً:*")
            for p in _already_excluded:
                _lines.append(f"   • `{p}`")
        if _not_found:
            _lines.append(f"\n❌ *{len(_not_found)} رقم غريب (غير موجود في البوت):*")
            for p in _not_found:
                _lines.append(f"   • `{p}`")
        await update.message.reply_text(
            "\n".join(_lines), parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 أرقام الإحالة", callback_data="os:bot_ref_numbers")]]))
        return

    if is_own and state == "os_await_bot_ref_delay":
        try:
            _delay_val = float(text.strip().replace(",", "."))
            if not math.isfinite(_delay_val) or _delay_val < 0:
                raise ValueError
        except (TypeError, ValueError):
            await update.message.reply_text(
                "⚠️ قيمة غير صالحة. أرسل رقماً موجباً أو صفراً مثل `1` أو `5` أو `0.5`.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:bot_ref_numbers")]]))
            return
        context.user_data["state"] = "main_menu"
        set_setting("referral_task_delay", str(_delay_val))
        await update.message.reply_text(
            f"✅ *تم ضبط التأخير بين الحسابات إلى {_delay_val} ثانية.*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 أرقام الإحالة", callback_data="os:bot_ref_numbers")]]))
        return

    if is_own and state == "os_await_ref_user_id":
        _search_id = text.strip().lstrip("@")
        _inv = None
        _refs = []
        with db_conn() as _c:
            if _search_id.isdigit():
                _inv = _c.execute("SELECT user_id, full_name, username FROM users WHERE user_id=%s", (int(_search_id),)).fetchone()
            if not _inv:
                _inv = _c.execute("SELECT user_id, full_name, username FROM users WHERE username=%s", (_search_id,)).fetchone()
            if _inv:
                _inv = dict(_inv)
                _refs = _c.execute(
                    "SELECT user_id, full_name, username, credited_at FROM users "
                    "WHERE invited_by=%s AND referral_credited=1 ORDER BY credited_at DESC LIMIT 30",
                    (_inv["user_id"],)
                ).fetchall()
        if not _inv:
            await update.message.reply_text(f"❌ لا يوجد مستخدم بـ «{_search_id}».", reply_markup=owner_settings_kb())
            context.user_data["state"] = "main_menu"
            return
        _inv_name = _inv.get("full_name") or f"ID:{_inv['user_id']}"
        _inv_un   = f" (@{_inv['username']})" if _inv.get("username") else ""
        if not _refs:
            _lines = [f"👤 *{_inv_name}{_inv_un}*\n📊 لا توجد إحالات مكتملة حتى الآن."]
        else:
            _lines = [f"👤 *{_inv_name}{_inv_un}* — {len(_refs)} إحالة:\n"]
            for _r in _refs:
                _r = dict(_r)
                _rn = _r.get("full_name") or f"ID:{_r['user_id']}"
                _run = f" (@{_r['username']})" if _r.get("username") else ""
                _raw_dt = _r.get("credited_at")
                if _raw_dt:
                    import datetime as _dt
                    if hasattr(_raw_dt, "strftime"):
                        _us = _raw_dt.microsecond
                        _dat = _raw_dt.strftime("%Y-%m-%d %H:%M:%S") + (f".{_us:06d}"[:8] if _us else "")
                    else:
                        _s = str(_raw_dt)
                        _dat = _s[:26]  # نحتفظ بأجزاء الثانية إن وُجدت
                else:
                    _dat = "—"
                _lines.append(f"• {_rn}{_run} — `{_dat}`")
        await update.message.reply_text(
            "\n".join(_lines), parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:top_referrers")]]))
        context.user_data["state"] = "main_menu"
        return

    # ─── تحقق بكود الطلب من الحسابات المبيوعة ───
    if is_own and state == "os_await_sold_code_search":
        search_code = text.strip().upper()
        with db_conn() as c:
            pe = c.execute(
                "SELECT pe.*, u.full_name AS buyer_name, u.user_id AS buyer_id "
                "FROM prize_exchanges pe "
                "LEFT JOIN users u ON u.user_id = pe.user_id "
                "WHERE UPPER(pe.order_code) = %s "
                "  AND pe.prize_type IN ('telegram_number','telegram_number_code','telegram_number_stars')",
                (search_code,)
            ).fetchone()
            ns = None
            if pe:
                ns = c.execute(
                    "SELECT phone_number, ever_sold, assigned_to, deleted_at, session_string, "
                    "       frozen_at, last_authorized, added_at "
                    "FROM number_stock WHERE phone_number = %s",
                    (pe["prize_value"],)
                ).fetchone()
        if not pe:
            await update.message.reply_text(
                f"❌ لا يوجد طلب بيع بالكود: `{search_code}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للمبيوعات", callback_data="os:sold_accounts")]])
            )
            context.user_data["state"] = "main_menu"
            return

        def _fmt_dt(v):
            if v is None: return "—"
            if hasattr(v, "strftime"): return v.strftime("%Y-%m-%d %H:%M")
            return str(v)[:16]

        if ns:
            if ns["deleted_at"]:
                acc_status = "🗑 محذوف"
            elif ns["assigned_to"]:
                acc_status = f"🟢 نشط — لدى المشتري حالياً (`{ns['assigned_to']}`)"
            elif ns["ever_sold"]:
                acc_status = "⬜ بيع سابق — البوت غادر الحساب"
            elif ns["frozen_at"]:
                acc_status = "🧊 مجمّد"
            elif not ns["last_authorized"]:
                acc_status = "🔴 مطرود (kicked)"
            else:
                acc_status = "✅ في المخزون"
            has_session = "✅ نعم" if ns["session_string"] else "❌ لا"
        else:
            acc_status = "⚠️ الرقم غير موجود في المخزون"
            has_session = "—"

        status_ar = {
            "completed": "✅ مكتمل",
            "pending": "⏳ معلق",
            "cancelled": "❌ ملغى",
            "duplicate_compensated": "⚠️ مكرر (عُوِّض)",
        }.get(pe["status"], pe["status"])

        msg = (
            f"🧾 *نتيجة التحقق — كود:* `{search_code}`\n\n"
            f"📱 *الرقم:* `{pe['prize_value']}`\n"
            f"👤 *المشتري:* {pe['buyer_name'] or '—'} (`{pe['buyer_id']}`)\n"
            f"💰 *التكلفة:* {pe['points_cost']:,} نقطة\n"
            f"📅 *تاريخ الشراء:* {_fmt_dt(pe['created_at'])}\n"
            f"📌 *حالة الطلب:* {status_ar}\n\n"
            f"🔑 *حالة الحساب الآن:* {acc_status}\n"
            f"💾 *جلسة موجودة:* {has_session}"
        )
        await update.message.reply_text(
            msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للمبيوعات", callback_data="os:sold_accounts")]])
        )
        context.user_data["state"] = "main_menu"
        return

    # ─── بحث شامل برقم هاتف (مباع أو غير مباع) ───
    if is_own and state == "os_await_phone_search":
        q_phone = text.strip()
        phone_digits = re.sub(r"\D", "", q_phone)
        if len(phone_digits) < 3:
            await update.message.reply_text(
                "⚠️ أرسل رقم هاتف صحيحاً أو جزءاً منه (3 أرقام على الأقل).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")]
                ])
            )
            context.user_data["state"] = "main_menu"
            return
        try:
            with db_conn() as _sc:
                rows = _sc.execute(
                    "SELECT ns.id, ns.phone_number, ns.session_string, ns.assigned_to, ns.assigned_at, "
                    "       ns.ever_sold, ns.twofa_password, ns.last_authorized, ns.deleted_at, "
                    "       ns.frozen_at, ns.sessions_reset, "
                    "       pe.order_code, pe.created_at AS sale_date, pe.points_cost, "
                    "       u.full_name AS buyer_name "
                    "FROM number_stock ns "
                    "LEFT JOIN prize_exchanges pe ON pe.prize_value = ns.phone_number "
                    "     AND pe.status = 'completed' "
                    "     AND pe.prize_type IN ('telegram_number','telegram_number_code','telegram_number_stars') "
                    "LEFT JOIN users u ON u.user_id = ns.assigned_to "
                    "WHERE regexp_replace(COALESCE(ns.phone_number, ''), '[^0-9]', '', 'g') LIKE %s "
                    "ORDER BY ns.id DESC LIMIT 5",
                    (f"%{phone_digits}%",)
                ).fetchall()
        except Exception as search_error:
            logger.exception("فشل البحث عن رقم الهاتف في المخزون")
            await update.message.reply_text(
                "❌ تعذر تنفيذ البحث حالياً بسبب خطأ في قاعدة البيانات.\n"
                f"التفاصيل: `{str(search_error)[:180]}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")]
                ])
            )
            context.user_data["state"] = "main_menu"
            return
        if not rows:
            await update.message.reply_text(
                f"❌ لا يوجد رقم يطابق «{q_phone}» في قاعدة البيانات.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")]]))
            context.user_data["state"] = "main_menu"
            return
        def _fd2(v):
            if v is None: return "—"
            if hasattr(v, "strftime"): return v.strftime("%Y-%m-%d %H:%M")
            return str(v)[:16]
        for r in rows:
            r = dict(r)
            has_session = bool(r.get("session_string"))
            is_sold_now = bool(r.get("assigned_to"))
            ever_sold   = bool(r.get("ever_sold"))
            is_deleted  = bool(r.get("deleted_at"))
            is_frozen   = bool(r.get("frozen_at"))
            is_kicked   = r.get("last_authorized") is False
            buyer_name  = r.get("buyer_name") or (f"ID:{r['assigned_to']}" if r.get("assigned_to") else "—")
            saved_2fa   = r.get("twofa_password") or "—"
            if is_deleted:
                status_icon = "🗑 محذوف (سلة المهملات)"
            elif is_sold_now:
                status_icon = "🟢 مباع الآن (نشط)"
            elif ever_sold:
                status_icon = "⬜ مباع سابقاً (البوت غادره)"
            elif is_frozen:
                status_icon = "🧊 مجمّد"
            elif is_kicked:
                status_icon = "🚫 مطرود (جلسة منتهية)"
            elif has_session:
                status_icon = "✅ متاح للبيع"
            else:
                status_icon = "⚠️ يدوي (بدون جلسة)"
            stock_id = r["id"]
            info = (
                f"📱 *{r['phone_number']}*\n"
                f"📌 الحالة: {status_icon}\n"
                f"🌍 الدولة: {guess_country(r['phone_number'])}\n"
                f"📡 جلسة البوت: {'✅' if has_session else '❌'}\n"
                f"🗝 كلمة 2FA: `{saved_2fa}`\n"
                f"👤 المشتري: {buyer_name}\n"
                f"📅 تاريخ البيع: {_fd2(r.get('assigned_at') or r.get('sale_date'))}\n"
                f"📌 كود الطلب: {r.get('order_code') or '—'}\n"
                f"🔒 طُردت الجلسات: {'✅' if r.get('sessions_reset') else '❌'}"
            )
            action_btns = []
            if has_session:
                action_btns += [
                    [InlineKeyboardButton("🔑 جلب آخر كود وصل",         callback_data=f"os:sold_code:{stock_id}")],
                    [InlineKeyboardButton("🚫 طرد جميع الجلسات الأخرى",  callback_data=f"os:sold_kick:{stock_id}")],
                    [InlineKeyboardButton("🔐 تغيير/عرض 2FA",            callback_data=f"os:sold_2fa:{stock_id}")],
                    [InlineKeyboardButton("🚪 تسجيل خروج البوت",          callback_data=f"os:sold_logout:{stock_id}")],
                ]
            action_btns.append([InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")])
            await update.message.reply_text(
                info, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(action_btns))
        context.user_data["state"] = "main_menu"
        return

    # ─── بحث في الحسابات المبيوعة ───
    if is_own and state == "os_await_sold_search":
        query_phone = text.strip().lstrip("+")
        with db_conn() as c:
            rows = c.execute(
                "SELECT ns.phone_number, ns.ever_sold, "
                "       pe.created_at AS sale_date, pe.order_code, u.full_name AS buyer_name, pe.user_id AS buyer_id "
                "FROM number_stock ns "
                "LEFT JOIN prize_exchanges pe ON pe.prize_value = ns.phone_number "
                "     AND pe.status = 'completed' "
                "     AND pe.prize_type IN ('telegram_number','telegram_number_code','telegram_number_stars') "
                "LEFT JOIN users u ON u.user_id = pe.user_id "
                "WHERE ns.phone_number LIKE %s AND ns.ever_sold IS TRUE",
                (f"%{query_phone}%",)
            ).fetchall()
        if not rows:
            await update.message.reply_text("🔍 لا توجد نتائج مطابقة.", reply_markup=owner_settings_kb())
            context.user_data["state"] = "main_menu"
            return
        def _fmt_dt(v):
            if v is None: return "—"
            if hasattr(v, "strftime"): return v.strftime("%Y-%m-%d %H:%M")
            return str(v)[:16]
        lines = [f"🔍 *نتائج البحث عن «{query_phone}»:*\n"]
        for r in rows:
            buyer_name = r["buyer_name"] or f"ID:{r.get('buyer_id','?')}"
            lines.append(
                f"📱 `{r['phone_number']}`\n"
                f"   👤 المشتري: {buyer_name}\n"
                f"   📅 تاريخ البيع: {_fmt_dt(r['sale_date'])}\n"
                f"   📌 كود: {r['order_code'] or '—'}"
            )
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للمبيوعات", callback_data="os:sold_accounts")]])
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_mandatory_cost":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("mandatory_channel_cost", str(val))
        await update.message.reply_text(f"✅ سعر تمويل القناة الإجباري = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_internal_cost":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("internal_channel_cost", str(val))
        await update.message.reply_text(f"✅ سعر تمويل القناة الداخلي = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_number_cost":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        set_setting("telegram_number_cost", str(val))
        await update.message.reply_text(f"✅ سعر رقم تيلغرام = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_number_stars":
        try:
            val = int(text)
            if val <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل عدداً صحيحاً أكبر من صفر.")
            return
        set_setting("telegram_number_stars", str(val))
        await update.message.reply_text(
            f"✅ سعر شراء رقم تيلغرام بالنجوم = {val} نجمة.",
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state in {"os_await_login_phone", "os_await_raksh_login_phone"}:
        _raksh_login = state == "os_await_raksh_login_phone"
        phone = text.strip()
        # ─── إضافة + تلقائياً إذا أرسل المالك الرقم بدونها ───
        if phone and not phone.startswith("+") and phone.isdigit():
            phone = "+" + phone
        if not phone.startswith("+") or not phone[1:].replace(" ", "").isdigit():
            await update.message.reply_text("⚠️ أرسل الرقم بصيغة دولية (مثال: `+9647701234567` أو `9647701234567`).", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            client = TelegramClient(StringSession(), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await asyncio.wait_for(client.connect(), timeout=20)
            sent = await client.send_code_request(phone)
        except FloodWaitError as e:
            await update.message.reply_text(f"⚠️ عدد محاولات كبير على هذا الرقم، انتظر {e.seconds} ثانية وحاول مجدداً.")
            return
        except PhoneNumberInvalidError:
            await update.message.reply_text("⚠️ الرقم غير صحيح. تأكد من الصيغة وأعد الإرسال.")
            return
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال كود الدخول: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء الاتصال بتيليجرام. حاول مرة أخرى لاحقاً.")
            return
        _pending_number_logins[user.id] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
            "raksh_only": _raksh_login,
        }
        context.user_data["state"] = "os_await_login_code"
        await update.message.reply_text(
            "📩 تم إرسال كود التفعيل إلى الرقم. أرسل الكود الذي وصلك (أرقام فقط):"
        )
        return

    if is_own and state == "os_await_login_code":
        pending = _pending_number_logins.get(user.id)
        if not pending:
            await update.message.reply_text("⚠️ انتهت الجلسة، ابدأ من جديد من قائمة إدارة الأرقام.", reply_markup=owner_settings_kb())
            context.user_data["state"] = "main_menu"
            return
        client = pending["client"]
        code = text.strip().replace(" ", "")
        try:
            await client.sign_in(pending["phone"], code, phone_code_hash=pending["phone_code_hash"])
        except SessionPasswordNeededError:
            context.user_data["state"] = "os_await_login_password"
            await update.message.reply_text("🔒 هذا الحساب محمي بكلمة مرور تحقق بخطوتين (2FA). أرسلها الآن:")
            return
        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            await update.message.reply_text("⚠️ الكود غير صحيح أو منتهي الصلاحية. أرسل الكود الصحيح مجدداً.")
            return
        except Exception as e:
            logger.error(f"❌ خطأ في تسجيل الدخول: {e}")
            await update.message.reply_text("❌ فشل تسجيل الدخول. حاول من جديد لاحقاً من قائمة إدارة الأرقام.", reply_markup=owner_settings_kb())
            await _cleanup_pending_login(user.id)
            context.user_data["state"] = "main_menu"
            return
        await _finish_number_login(update, context, user.id)
        return

    if is_own and state == "os_await_login_password":
        pending = _pending_number_logins.get(user.id)
        if not pending:
            await update.message.reply_text("⚠️ انتهت الجلسة، ابدأ من جديد من قائمة إدارة الأرقام.", reply_markup=owner_settings_kb())
            context.user_data["state"] = "main_menu"
            return
        client = pending["client"]
        try:
            await client.sign_in(password=text.strip())
        except PasswordHashInvalidError:
            await update.message.reply_text("⚠️ كلمة المرور غير صحيحة. أرسلها مجدداً:")
            return
        except Exception as e:
            logger.error(f"❌ خطأ في تسجيل الدخول (2FA): {e}")
            await update.message.reply_text("❌ فشل تسجيل الدخول. حاول من جديد لاحقاً من قائمة إدارة الأرقام.", reply_markup=owner_settings_kb())
            await _cleanup_pending_login(user.id)
            context.user_data["state"] = "main_menu"
            return
        await _finish_number_login(update, context, user.id)
        return

    # ═══════════════════════════════════════════════════════════
    # ══ معالجة حالات المشرف ══
    # ═══════════════════════════════════════════════════════════

    if is_own and state == "os_await_supervisor_id":
        context.user_data["state"] = "main_menu"
        raw = text.strip()
        target_id = None
        target_username = ""
        if raw.startswith("@"):
            target_username = raw[1:]
            # محاولة الحصول على الـ ID من قاعدة البيانات
            with db_conn() as c:
                row = c.execute(
                    "SELECT user_id FROM users WHERE username=%s", (target_username,)
                ).fetchone()
            if row:
                target_id = row["user_id"]
            else:
                await update.message.reply_text(
                    "⚠️ لم أجد المستخدم @" + target_username + " في قاعدة البيانات.\n\n"
                    "تأكد أن المستخدم قد استخدم البوت من قبل، أو أرسل الـ ID مباشرة.",
                    reply_markup=owner_settings_kb()
                )
                return
        else:
            try:
                target_id = int(raw)
            except ValueError:
                await update.message.reply_text(
                    "⚠️ صيغة غير صحيحة. أرسل @username أو ID رقمي.",
                    reply_markup=owner_settings_kb()
                )
                return
        if target_id == OWNER_ID:
            await update.message.reply_text("⚠️ المالك لا يحتاج صلاحية مشرف.", reply_markup=owner_settings_kb())
            return
        if not target_username:
            with db_conn() as c:
                row = c.execute("SELECT username FROM users WHERE user_id=%s", (target_id,)).fetchone()
            target_username = row["username"] if row and row.get("username") else ""
        added = add_supervisor(target_id, target_username)
        if added:
            await update.message.reply_text(
                "✅ *تمت إضافة المشرف بنجاح!*\n\n"
                "👤 المعرّف: `" + str(target_id) + "`\n"
                + ("🔖 اليوزر: @" + target_username if target_username else ""),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=owner_settings_kb()
            )
        else:
            await update.message.reply_text(
                f"⚠️ المستخدم `{target_id}` مضاف كمشرف مسبقاً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=owner_settings_kb()
            )
        return

    if is_supervisor_txt and state == "sv_await_login_phone":
        phone = text.strip()
        if not phone.startswith("+"):
            phone = "+" + phone
        if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
            await update.message.reply_text("⚠️ الاتصال بتيليجرام غير مُهيّأ. تواصل مع المالك.")
            return
        try:
            client = TelegramClient(StringSession(), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await asyncio.wait_for(client.connect(), timeout=20)
            sent = await client.send_code_request(phone)
        except FloodWaitError as e:
            await update.message.reply_text(f"⚠️ محاولات كثيرة على هذا الرقم، انتظر {e.seconds} ثانية.")
            return
        except PhoneNumberInvalidError:
            await update.message.reply_text("⚠️ الرقم غير صحيح. تأكد من الصيغة وأعد الإرسال.")
            return
        except Exception as e:
            logger.error(f"❌ خطأ إرسال كود المشرف: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء الاتصال. حاول مجدداً.")
            return
        _pending_supervisor_logins[user.id] = {
            "client": client, "phone": phone, "phone_code_hash": sent.phone_code_hash
        }
        context.user_data["state"] = "sv_await_login_code"
        await update.message.reply_text(
            "📩 تم إرسال كود التفعيل إلى الرقم. أرسل الكود الذي وصلك (أرقام فقط):"
        )
        return

    if is_supervisor_txt and state == "sv_await_login_code":
        pending = _pending_supervisor_logins.get(user.id)
        if not pending:
            await update.message.reply_text("⚠️ انتهت الجلسة. ابدأ من جديد من لوحة المشرف.")
            context.user_data["state"] = "main_menu"
            return
        client = pending["client"]
        code = text.strip().replace(" ", "")
        try:
            await client.sign_in(pending["phone"], code, phone_code_hash=pending["phone_code_hash"])
        except SessionPasswordNeededError:
            context.user_data["state"] = "sv_await_login_password"
            await update.message.reply_text("🔒 هذا الحساب محمي بكلمة مرور 2FA. أرسلها الآن:")
            return
        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            await update.message.reply_text("⚠️ الكود غير صحيح أو منتهي الصلاحية. أرسله مجدداً.")
            return
        except Exception as e:
            logger.error(f"❌ خطأ تسجيل دخول المشرف: {e}")
            await update.message.reply_text("❌ فشل تسجيل الدخول. حاول من جديد من لوحة المشرف.")
            _pending_supervisor_logins.pop(user.id, None)
            context.user_data["state"] = "main_menu"
            return
        await _finish_supervisor_login(update, context, user.id)
        return

    if is_supervisor_txt and state == "sv_await_login_password":
        pending = _pending_supervisor_logins.get(user.id)
        if not pending:
            await update.message.reply_text("⚠️ انتهت الجلسة. ابدأ من جديد من لوحة المشرف.")
            context.user_data["state"] = "main_menu"
            return
        client = pending["client"]
        try:
            await client.sign_in(password=text.strip())
        except PasswordHashInvalidError:
            await update.message.reply_text("⚠️ كلمة المرور غير صحيحة. أرسلها مجدداً:")
            return
        except Exception as e:
            logger.error(f"❌ خطأ تسجيل دخول المشرف (2FA): {e}")
            await update.message.reply_text("❌ فشل تسجيل الدخول. حاول من جديد من لوحة المشرف.")
            _pending_supervisor_logins.pop(user.id, None)
            context.user_data["state"] = "main_menu"
            return
        await _finish_supervisor_login(update, context, user.id)
        return

    if is_own and state == "os_await_manual_2fa_pwd":
        stock_id = context.user_data.get("manual_2fa_stock_id")
        pwd = text.strip()
        context.user_data["state"] = "main_menu"
        context.user_data.pop("manual_2fa_stock_id", None)
        if not stock_id:
            await update.message.reply_text("⚠️ انتهت صلاحية الطلب، افتح معلومات الرقم من جديد.")
            return
        with db_conn() as c:
            rec = c.execute(
                "SELECT phone_number, session_string FROM number_stock WHERE id=%s", (stock_id,)
            ).fetchone()
        if not rec or not rec["session_string"]:
            await update.message.reply_text("⚠️ لم يُعثر على هذا الرقم بعد الآن.")
            return
        await update.message.reply_text("⏳ جاري التحقق من كلمة المرور مع تيليجرام...")
        client = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(client.connect(), timeout=20)
            verified = await verify_current_2fa_password(client, pwd, phone=rec["phone_number"])
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        if verified is True:
            with db_conn() as c:
                c.execute("UPDATE number_stock SET twofa_password=%s WHERE id=%s", (pwd, stock_id))
            await update.message.reply_text(
                f"✅ تم التحقق من كلمة المرور وحفظها بنجاح لرقم `{rec['phone_number']}`.",
                parse_mode=ParseMode.MARKDOWN
            )
        elif verified is False:
            context.user_data["state"] = "os_await_manual_2fa_pwd"
            context.user_data["manual_2fa_stock_id"] = stock_id
            await update.message.reply_text(
                f"❌ كلمة المرور خاطئة لرقم `{rec['phone_number']}`. أرسل الكلمة الصحيحة مجدداً:",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("⚠️ تعذّر التحقق الآن (خطأ شبكي)، حاول مجدداً بعد قليل.")
        return

    if state == 'await_forced_ref_channels':
        await _forced_ref_handle_channels(update, context)
        return
    if state == 'await_forced_ref_link':
        await _forced_ref_handle_link(update, context)
        return
    if state == 'await_forced_ref_qty':
        await _forced_ref_handle_qty(update, context, user)
        return
    if state == 'await_forced_ref_delay':
        await _forced_ref_handle_delay(update, context, user)
        return

    # ── حالات إحالة إجبارية المشرف ──
    if state == 'sv_await_forced_ref_channels':
        await _sv_forced_ref_handle_channels(update, context)
        return
    if state == 'sv_await_forced_ref_link':
        await _sv_forced_ref_handle_link(update, context)
        return
    if state == 'sv_await_forced_ref_qty':
        await _sv_forced_ref_handle_qty(update, context, user)
        return

    if state == 'await_mansub_link':
        await _mansub_handle_link(update, context)
        return
    if state == 'await_mansub_channels':
        await _mansub_handle_channels(update, context)
        return
    if state == 'await_mansub_qty':
        await _mansub_handle_qty(update, context, user)
        return

    if is_own and state == "os_await_ref_task_channels":
        raw = text.strip()
        draft = context.user_data.setdefault("ref_task_draft", {})
        if raw.lower() in ("تخطي", "skip", "-"):
            draft["mandatory_channels"] = ""
        else:
            draft["mandatory_channels"] = raw
        context.user_data["state"] = "os_await_ref_task_link"
        chs_preview = draft["mandatory_channels"] or "لا يوجد"
        await update.message.reply_text(
            f"✅ القنوات الإجبارية: `{chs_preview}`\n\n"
            "🤝 *خطوة 2/3 — رابط الإحالة:*\n"
            "أرسل رابط إحالة البوت:\n\n"
            "`t.me/BotUsername?start=REFERRAL_CODE`\n"
            "أو: `@BotUsername REFERRAL_CODE`\n"
            "أو: `BotUsername REFERRAL_CODE`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:ref_tasks")]])
        )
        return

    if is_own and state == "os_await_ref_task_link":
        raw = text.strip()
        bot_user = ""
        start_p  = ""
        try:
            if "t.me/" in raw or "telegram.me/" in raw:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(raw if raw.startswith("http") else "https://" + raw)
                bot_user = parsed.path.strip("/")
                qs = parse_qs(parsed.query)
                start_p = qs.get("start", [""])[0]
            else:
                parts = raw.split(None, 1)
                bot_user = parts[0].lstrip("@")
                start_p  = parts[1] if len(parts) > 1 else ""

            if not bot_user or not start_p:
                raise ValueError("يوزر أو كود فارغ")

            draft = context.user_data.setdefault("ref_task_draft", {})
            draft["bot_user"]   = bot_user
            draft["start_p"]    = start_p
            context.user_data["state"] = "os_await_ref_task_folder"
            await update.message.reply_text(
                f"✅ البوت: `@{bot_user}` | الكود: `{start_p}`\n\n"
                "📂 *خطوة 3/3 — رابط مجموعة القنوات (Folder Link):*\n"
                "أرسل رابط المجلد بهذا الشكل:\n"
                "`t.me/addlist/XXXXXXXXX`\n\n"
                "⚠️ إذا كان لدى الرقم مجلدان مسبقاً سيتم حذف الأقدم تلقائياً لإضافة الجديد.\n\n"
                "أو أرسل `تخطي` إذا لا تريد إضافة مجلد.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:ref_tasks")]])
            )
        except Exception as parse_err:
            await update.message.reply_text(
                f"⚠️ تعذّر قراءة الرابط: `{parse_err}`\n\n"
                "أرسله بهذا الشكل:\n`t.me/BotUsername?start=REFERRAL_CODE`\n"
                "أو: `@BotUsername REFERRAL_CODE`",
                parse_mode=ParseMode.MARKDOWN
            )
        return

    if is_own and state == "os_await_ref_task_folder":
        raw = text.strip()
        draft = context.user_data.get("ref_task_draft", {})
        bot_user = draft.get("bot_user", "")
        start_p  = draft.get("start_p",  "")
        mandatory_channels = draft.get("mandatory_channels", "")
        if raw.lower() in ("تخطي", "skip", "-"):
            folder_link = ""
        elif "addlist/" in raw or "t.me/" in raw:
            folder_link = raw.strip()
        else:
            await update.message.reply_text(
                "⚠️ الرابط غير صحيح.\n"
                "يجب أن يكون بهذا الشكل: `t.me/addlist/XXXXXXXXX`\n"
                "أو أرسل `تخطي` للتخطي.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        if not bot_user or not start_p:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("⚠️ انتهت صلاحية المسودة، ابدأ من جديد.", reply_markup=owner_settings_kb())
            return
        label = f"@{bot_user} — {start_p[:20]}"
        task_id = add_referral_task(label, bot_user, start_p, mandatory_channels, folder_link)
        context.user_data["state"] = "main_menu"
        context.user_data.pop("ref_task_draft", None)
        ch_line = f"\n📢 القنوات الإجبارية: `{mandatory_channels}`" if mandatory_channels else ""
        fl_line = f"\n📂 رابط المجلد: `{folder_link}`" if folder_link else ""
        await update.message.reply_text(
            f"✅ *تمت إضافة مهمة الإحالة بنجاح!*\n\n"
            f"📌 البوت: `@{bot_user}`\n"
            f"🔑 الكود: `{start_p}`"
            f"{ch_line}{fl_line}\n\n"
            f"ستُنفَّذ تلقائياً على كل الأرقام كل ساعة.\n"
            f"يمكنك أيضاً تشغيلها فوراً من ⚙️ تفاصيل المهمة.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    if is_own and state == "os_await_add_numbers":
        raw_numbers = [n for chunk in text.split(",") for n in chunk.splitlines()]
        added = add_numbers_to_stock(raw_numbers)
        avail = get_available_number_count()
        with db_conn() as _dc:
            _total_row = _dc.execute(
                "SELECT COUNT(*) as cnt FROM number_stock "
                "WHERE deleted_at IS NULL AND ever_sold IS NOT TRUE AND assigned_to IS NULL"
            ).fetchone()
        _total = _total_row["cnt"] if _total_row else 0
        await update.message.reply_text(
            f"✅ تمت إضافة *{added}* رقم جديد للمخزون.\n\n"
            f"📦 إجمالي الأرقام في المخزون: *{_total}* رقم\n"
            f"🚀 منها معروض للبيع مباشرةً: *{avail}* رقم\n\n"
            f"_(الأرقام الجديدة تحتاج استيراد جلسة عبر /import\\_sessions ثم تحقق تلقائي قبل العرض للبيع)_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_welcome":
        set_setting("welcome_message", text)
        await update.message.reply_text("✅ تم تحديث رسالة الترحيب.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_contact":
        if text.strip().lower() == "حذف":
            set_setting("owner_contact", "")
            await update.message.reply_text("✅ تم حذف رابط تواصل المالك.", reply_markup=owner_settings_kb())
        elif text.strip().startswith("https://t.me/") or text.strip().startswith("https://"):
            set_setting("owner_contact", text.strip())
            await update.message.reply_text(f"✅ تم حفظ رابط التواصل:\n{text.strip()}", reply_markup=owner_settings_kb())
        else:
            await update.message.reply_text(
                "⚠️ الرابط غير صحيح. يجب أن يبدأ بـ `https://t.me/` مثال:\n`https://t.me/username`\n\nأو أرسل *حذف* لإزالة الرابط.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_contact_label":
        new_label = text.strip()
        if not new_label:
            await update.message.reply_text("⚠️ النص لا يمكن أن يكون فارغاً.")
            return
        set_setting("owner_contact_label", new_label)
        await update.message.reply_text(
            f"✅ تم تحديث نص زر التواصل (بعد الخصم) إلى:\n{new_label}",
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_support_label":
        new_label = text.strip()
        if not new_label:
            await update.message.reply_text("⚠️ النص لا يمكن أن يكون فارغاً.")
            return
        set_setting("support_contact_label", new_label)
        await update.message.reply_text(
            f"✅ تم تحديث نص زر الدعم إلى:\n{new_label}",
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_raksh_label":
        new_label = " ".join(text.split())[:64]
        if not new_label:
            await update.message.reply_text("⚠️ الاسم لا يمكن أن يكون فارغاً، أعد الإرسال.")
            return
        set_setting(RAKSH_ACCOUNTS_LABEL_SETTING, new_label)
        try:
            await sync_raksh_bot_commands(context.bot)
        except Exception as exc:
            logger.warning(f"⚠️ تعذر تحديث اسم أمر الرشق في قائمة تيليجرام: {exc}")
        await update.message.reply_text(
            f"✅ تم تحديث اسم خدمات تلي مميزة إلى:\n🔥 {new_label}",
            reply_markup=owner_settings_kb(),
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_prize_name":
        name = text.strip()
        if not name:
            await update.message.reply_text("⚠️ الاسم لا يمكن أن يكون فارغاً، أعد الإرسال.")
            return
        context.user_data["prize_name"] = name
        context.user_data["state"] = "os_await_prize_qty"
        await update.message.reply_text(
            f"🎀 *الجائزة:* {name}\n\n"
            f"الخطوة 1.5/2 — أرسل *العدد* لكل طلب (مثال: `1`) أو اضغط تخطي:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭ تخطي (العدد = 1)", callback_data="os:skip_prize_qty")]
            ])
        )
        return

    if is_own and state == "os_await_prize_qty":
        try:
            qty = int(text.strip().replace(",", ""))
            if qty <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً موجباً أو اضغط تخطي.")
            return
        context.user_data["prize_qty"] = qty
        context.user_data["state"] = "os_await_prize_cost"
        await update.message.reply_text(
            f"🎀 *الجائزة:* {context.user_data['prize_name']} × {qty}\n\n"
            f"الخطوة 2/2 — أرسل *عدد النقاط* اللازمة للحصول عليها:\n"
            f"مثال: `1000`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if is_own and state == "os_await_prize_cost":
        try:
            cost = int(text.strip().replace(",", ""))
            if cost <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً موجباً.")
            return
        name = context.user_data.get("prize_name", "")
        qty  = context.user_data.get("prize_qty", 1)
        qty_txt = f" × {qty}" if qty > 1 else ""
        with db_conn() as c:
            c.execute(
                "INSERT INTO custom_prizes (name, quantity, points_cost, active) VALUES (%s, %s, %s, 1)",
                (name, qty, cost)
            )
        context.user_data.pop("prize_name", None)
        context.user_data.pop("prize_qty", None)
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(
            f"✅ *تمت إضافة الجائزة بنجاح!*\n\n"
            f"🎀 الاسم: {name}{qty_txt}\n"
            f"💰 التكلفة: {cost:,} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    if is_own and state == "os_await_asiacell_text":
        set_setting("asiacell_text", text)
        await update.message.reply_text("✅ تم تحديث نص اسيا سيل.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_order_lookup":
        code = text.strip()
        with db_conn() as c:
            o = c.execute(
                """SELECT o.*, u.full_name AS u_full_name, u.username AS u_username,
                          s.name_ar AS s_name_ar, s.category AS s_category
                   FROM orders o
                   LEFT JOIN users u ON u.user_id = o.user_id
                   LEFT JOIN services s ON s.id = o.service_id
                   WHERE o.order_code=?""",
                (code,)
            ).fetchone()
        context.user_data["state"] = "main_menu"
        if not o:
            await update.message.reply_text("⚠️ كود الطلب غير موجود.", reply_markup=owner_settings_kb())
            return
        await update.message.reply_text(
            _render_order_block(dict(o)),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    if is_own and state == "os_await_cancel_order":
        code = text.strip()
        with db_conn() as c:
            order = c.execute("SELECT * FROM orders WHERE order_code=?", (code,)).fetchone()
        if not order:
            await update.message.reply_text("⚠️ كود الطلب غير موجود.")
            context.user_data["state"] = "main_menu"
            return
        context.user_data["cancel_order"] = dict(order)
        context.user_data["state"] = "confirm_cancel_order"
        await update.message.reply_text(
            f"⚠️ *تأكيد إلغاء الطلب:*\n\n"
            f"📌 الكود: {code}\n"
            f"👤 المستخدم ID: {order['user_id']}\n"
            f"💰 التكلفة: {order['cost_points']} نقطة\n\n"
            f"أرسل *نعم* للإلغاء وإعادة الرصيد أو *لا* للتراجع",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if is_own and state == "confirm_cancel_order":
        if text == "نعم":
            order  = context.user_data.get("cancel_order", {})
            uid    = order.get("user_id")
            pts    = order.get("cost_points", 0)
            o_code = order.get("order_code")
            with db_conn() as c:
                c.execute("UPDATE orders SET status='cancelled' WHERE order_code=?", (o_code,))
            if pts:
                add_points(uid, pts)
            await update.message.reply_text(
                f"✅ تم إلغاء الطلب {o_code} وإعادة {pts} نقطة للمستخدم.",
                reply_markup=owner_settings_kb()
            )
            try:
                await context.bot.send_message(
                    uid,
                    f"🔴 تم إلغاء طلبك بكود {o_code} وإعادة *{pts}* نقطة لرصيدك.\n\n"
                    f"{LINK_ERROR_GUIDANCE}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
        else:
            await update.message.reply_text("❌ تم التراجع.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_complete_order":
        code = text.strip()
        with db_conn() as c:
            order = c.execute("SELECT * FROM orders WHERE order_code=?", (code,)).fetchone()
        if not order:
            await update.message.reply_text("⚠️ كود الطلب غير موجود.", reply_markup=owner_settings_kb())
            context.user_data["state"] = "main_menu"
            return
        context.user_data["complete_order"] = dict(order)
        context.user_data["state"] = "confirm_complete_order"
        await update.message.reply_text(
            f"✅ *تأكيد إكمال الطلب:*\n\n"
            f"📌 الكود: {code}\n"
            f"👤 المستخدم ID: {order['user_id']}\n\n"
            f"أرسل *نعم* لتأكيد الإكمال وإشعار المستخدم أو *لا* للتراجع",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if is_own and state == "confirm_complete_order":
        if text == "نعم":
            order  = context.user_data.get("complete_order", {})
            uid    = order.get("user_id")
            o_code = order.get("order_code")
            with db_conn() as c:
                c.execute("UPDATE orders SET status='completed' WHERE order_code=?", (o_code,))
            await update.message.reply_text(
                f"✅ تم تحديد الطلب {o_code} كمكتمل وإشعار المستخدم.",
                reply_markup=owner_settings_kb()
            )
            try:
                await context.bot.send_message(
                    uid,
                    f"🎉 تم اكتمال طلبك بكود {o_code} بنجاح!\nنتمنى أن تكون راضياً عن الخدمة 🌟"
                )
            except Exception:
                pass
        else:
            await update.message.reply_text("❌ تم التراجع.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_channel":
        channel = text.lstrip("@")
        with db_conn() as c:
            c.execute(
                "INSERT INTO mandatory_channels (channel_username,funding_type,active) VALUES (%s,'mandatory',1) "
                "ON CONFLICT (channel_username) DO UPDATE SET active=1, funding_type='mandatory'",
                (channel,)
            )
        await update.message.reply_text(f"✅ تمت إضافة القناة @{channel} بنجاح! 🎉 أحسنت.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_promo_code_text":
        code = text.strip().upper()
        if len(code) < 3:
            await update.message.reply_text("⚠️ الكود يجب أن يكون 3 أحرف على الأقل.")
            return
        with db_conn() as c:
            existing = c.execute("SELECT 1 FROM promo_codes WHERE code=?", (code,)).fetchone()
        if existing:
            await update.message.reply_text("⚠️ هذا الكود موجود مسبقاً. أرسل كوداً آخر.")
            return
        context.user_data["new_promo_code"] = code
        context.user_data["state"] = "os_await_promo_uses"
        await update.message.reply_text(f"✅ الكود: `{code}`\n\nكم عدد المستخدمين الذين يمكنهم استخدامه؟",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    if is_own and state == "os_await_promo_uses":
        try:
            uses = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        if uses <= 0:
            await update.message.reply_text("⚠️ يجب أن يكون أكبر من صفر.")
            return
        context.user_data["new_promo_uses"] = uses
        context.user_data["state"] = "os_await_promo_points"
        await update.message.reply_text(f"✅ الحد الأقصى: {uses} مستخدم\n\nكم عدد النقاط لكل مستخدم؟")
        return

    if is_own and state == "os_await_promo_points":
        try:
            pts = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        if pts <= 0:
            await update.message.reply_text("⚠️ يجب أن يكون أكبر من صفر.")
            return
        code  = context.user_data.get("new_promo_code")
        uses  = context.user_data.get("new_promo_uses")
        with db_conn() as c:
            c.execute("INSERT INTO promo_codes (code, max_uses, points) VALUES (?,?,?)", (code, uses, pts))
        await update.message.reply_text(
            f"✅ *تم إنشاء الكود بنجاح!*\n\n"
            f"🎟 الكود: `{code}`\n"
            f"👥 الحد الأقصى: {uses} مستخدم\n"
            f"💰 النقاط لكل مستخدم: {pts}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_broadcast":
        broadcast_text = text
        with db_conn() as c:
            users = c.execute("SELECT user_id FROM users").fetchall()
        sent = 0
        failed = 0
        for u_row in users:
            try:
                await context.bot.send_message(u_row["user_id"], broadcast_text, parse_mode=ParseMode.HTML)
                sent += 1
            except Exception:
                failed += 1
        await update.message.reply_text(
            f"📢 *تم إرسال الرسالة الجماعية*\n\n✅ نجح: {sent}\n❌ فشل: {failed}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_ban_target":
        target = lookup_user_by_id_or_username(text)
        if not target:
            await update.message.reply_text(
                "⚠️ لم يتم إيجاد المستخدم. أرسل الـ ID الرقمي أو @يوزرنيم مسجّل في البوت.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")]]),
            )
            return
        if target["user_id"] == OWNER_ID:
            await update.message.reply_text("⚠️ لا يمكن حظر المالك.", reply_markup=owner_settings_kb())
            context.user_data["state"] = "main_menu"
            return
        if target.get("banned"):
            uname = f"@{target['username']}" if target.get("username") else f"ID: {target['user_id']}"
            await update.message.reply_text(
                f"ℹ️ *{target.get('full_name', '')}* ({uname}) محظور مسبقاً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔓 رفع الحظر عنه", callback_data=f"os:unban_confirm:{target['user_id']}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")],
                ]),
            )
            context.user_data["state"] = "main_menu"
            return
        context.user_data["ban_target_id"] = target["user_id"]
        context.user_data["state"] = "os_await_ban_reason"
        uname = f"@{target['username']}" if target.get("username") else f"ID: {target['user_id']}"
        await update.message.reply_text(
            f"🚫 *حظر:* {target.get('full_name', '')} ({uname})\n\n"
            "أرسل سبب الحظر (أو أرسل - لتخطي السبب):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:ban_menu")]]),
        )
        return

    if is_own and state == "os_await_ban_reason":
        target_id = context.user_data.get("ban_target_id")
        reason = text.strip() if text.strip() != "-" else ""
        if not target_id:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("⚠️ انتهت الجلسة.", reply_markup=owner_settings_kb())
            return
        found = ban_user_db(target_id, reason)
        target = get_user(target_id)
        uname = f"@{target['username']}" if target and target.get("username") else f"ID: {target_id}"
        name  = (target.get("full_name") or "") if target else ""
        context.user_data["state"] = "main_menu"
        if found:
            await update.message.reply_text(
                f"✅ *تم حظر العضو بنجاح*\n\n"
                f"👤 {name} ({uname})\n"
                f"📝 السبب: {reason or '—'}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔓 رفع الحظر", callback_data=f"os:unban_confirm:{target_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")],
                ]),
            )
        else:
            await update.message.reply_text("⚠️ المستخدم غير موجود في قاعدة البيانات.", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_await_unban_target":
        target = lookup_user_by_id_or_username(text)
        context.user_data["state"] = "main_menu"
        if not target:
            await update.message.reply_text(
                "⚠️ لم يتم إيجاد المستخدم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")]]),
            )
            return
        if not target.get("banned"):
            uname = f"@{target['username']}" if target.get("username") else f"ID: {target['user_id']}"
            await update.message.reply_text(
                f"ℹ️ {target.get('full_name', '')} ({uname}) غير محظور.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")]]),
            )
            return
        unban_user_db(target["user_id"])
        uname = f"@{target['username']}" if target.get("username") else f"ID: {target['user_id']}"
        await update.message.reply_text(
            f"✅ *تم رفع الحظر عن:* {target.get('full_name', '')} ({uname})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")]]),
        )
        return

    # ─── تقييد عضو يدوياً من قِبل المالك ──────────────────────────
    if is_own and state == "os_await_restrict_target":
        target = lookup_user_by_id_or_username(text)
        context.user_data["state"] = "main_menu"
        if not target:
            await update.message.reply_text(
                "⚠️ لم يتم إيجاد المستخدم. أرسل الـ ID الرقمي أو @يوزرنيم مسجّل في البوت.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:restricted_members")]]),
            )
            return
        if target["user_id"] == OWNER_ID:
            await update.message.reply_text("⚠️ لا يمكن تقييد المالك.", reply_markup=owner_settings_kb())
            return
        if target.get("referral_points_blocked"):
            uname = f"@{target['username']}" if target.get("username") else f"ID: {target['user_id']}"
            await update.message.reply_text(
                f"ℹ️ *{target.get('full_name', '')}* ({uname}) مقيد مسبقاً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔓 رفع التقييد", callback_data=f"os:ref_unblock:{target['user_id']}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="os:restricted_members")],
                ]),
            )
            return
        with db_conn() as c:
            c.execute(
                "UPDATE users SET referral_points_blocked=1 WHERE user_id=%s",
                (target["user_id"],)
            )
        uname = f"@{target['username']}" if target.get("username") else f"ID: {target['user_id']}"
        name  = target.get("full_name") or ""
        await update.message.reply_text(
            f"✅ *تم تقييد العضو*\n\n"
            f"👤 {name} ({uname})\n"
            f"🔒 لن يستطيع كسب نقاط الإحالة حتى ترفع التقييد.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔓 رفع التقييد", callback_data=f"os:ref_unblock:{target['user_id']}")],
                [InlineKeyboardButton("🔙 رجوع للمقيدين", callback_data="os:restricted_members")],
            ]),
        )
        return

    if is_own and state == "os_await_code_search":
        code = text.strip().upper()
        context.user_data["state"] = "main_menu"
        with db_conn() as c:
            promo = c.execute("SELECT * FROM promo_codes WHERE code=%s", (code,)).fetchone()
            promo_uses = c.execute(
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
            num_code = c.execute("SELECT * FROM number_purchase_codes WHERE code=%s", (code,)).fetchone()
            num_code_uses = c.execute(
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
                (code,)
            ).fetchall()

        if not promo_uses and not promo and not num_code_uses and not num_code:
            await update.message.reply_text(
                f"⚠️ لا توجد سجلات لاستخدام الكود `{code}` (لا الآن ولا في السابق).",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_promos")]]),
            )
            return

        parts = []

        # ─── قسم الأكواد الترويجية ───
        if promo or promo_uses:
            if promo:
                header = (
                    f"🎟 *كود ترويجي:* `{code}`\n"
                    f"🎁 النقاط: {promo['points']} | الاستخدامات: {promo['used_count']}/{promo['max_uses']}"
                    f" | {'✅ فعّال' if promo['active'] else '❌ معطّل'}\n"
                )
            else:
                header = f"🎟 *كود ترويجي (قديم):* `{code}`\n"
            if not promo_uses:
                body = "\n_لم يستخدمه أحد._"
            else:
                lines = []
                for i, u in enumerate(promo_uses, 1):
                    name  = (u["full_name"] or "").strip() or "—"
                    uname = f"@{u['username']}" if u["username"] else f"ID: {u['user_id']}"
                    pts   = u["points"] if u["points"] is not None else "؟"
                    ts_raw = u["used_at"]
                    ts = ts_raw.strftime("%Y-%m-%d %H:%M") if ts_raw and hasattr(ts_raw, "strftime") else (str(ts_raw)[:16] if ts_raw else "—")
                    lines.append(f"{i}. {name} ({uname})\n   💰 رصيده: {pts} نقطة | 🕐 {ts}")
                body = "\n\n" + "\n\n".join(lines)
            parts.append(header + body)

        # ─── قسم أكواد شراء الأرقام ───
        if num_code or num_code_uses:
            if num_code:
                header2 = (
                    f"📱 *كود شراء رقم:* `{code}`\n"
                    f"الاستخدامات: {num_code['used_count']}/{num_code['max_uses']}"
                    f" | {'✅ فعّال' if num_code['active'] else '❌ معطّل'}\n"
                )
            else:
                header2 = f"📱 *كود شراء رقم (قديم):* `{code}`\n"
            if not num_code_uses:
                body2 = "\n_لم يستخدمه أحد._"
            else:
                lines2 = []
                for i, u in enumerate(num_code_uses, 1):
                    name  = (u["full_name"] or "").strip() or "—"
                    uname = f"@{u['username']}" if u["username"] else f"ID: {u['user_id']}"
                    num   = u["number_given"] or "—"
                    ts_raw = u["used_at"]
                    ts = ts_raw.strftime("%Y-%m-%d %H:%M") if ts_raw and hasattr(ts_raw, "strftime") else (str(ts_raw)[:16] if ts_raw else "—")
                    lines2.append(f"{i}. {name} ({uname})\n   📱 الرقم المسلَّم: `{num}` | 🕐 {ts}")
                body2 = "\n\n" + "\n\n".join(lines2)
            parts.append(header2 + body2)

        msg = f"🔍 *نتائج البحث عن الكود:* `{code}`\n\n" + "\n\n─────────────────\n\n".join(parts)
        chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
        for idx, chunk in enumerate(chunks):
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للأكواد", callback_data="os:list_promos")]]) if idx == len(chunks) - 1 else None
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return

    if is_own and state == "os_await_points_target":
        # لا تسمح لحالة قديمة من تعديل الخدمة بأن تتداخل مع عملية النقاط.
        context.user_data.pop("edit_svc_id", None)
        try:
            target = lookup_user_by_id_or_username(text)
        except Exception:
            logger.exception("فشل البحث عن مستخدم لتعديل النقاط")
            await update.message.reply_text(
                "❌ تعذر البحث عن المستخدم حالياً. حاول مرة أخرى بعد قليل.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_points")]
                ])
            )
            return
        if not target:
            await update.message.reply_text(
                "⚠️ لم يتم إيجاد المستخدم. أرسل ID رقمي أو @يوزرنيم:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_points")]])
            )
            return
        context.user_data["points_target_id"] = target["user_id"]
        context.user_data["state"] = "os_await_points_amount"
        mode  = context.user_data.get("points_mode", "give")
        uname = f"@{target['username']}" if target.get("username") else f"ID: {target['user_id']}"
        verb  = "منح" if mode == "give" else "خصم"
        await update.message.reply_text(
            f"{'➕' if mode == 'give' else '➖'} *{verb} نقاط لـ:* {md_escape(target.get('full_name',''))} ({md_escape(uname)})\n"
            f"💰 رصيده الحالي: *{target.get('points', 0)}* نقطة\n\n"
            f"أرسل عدد النقاط المراد {'منحها' if mode == 'give' else 'خصمها'}:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_points")]])
        )
        return

    if is_own and state == "os_await_points_amount":
        context.user_data.pop("edit_svc_id", None)
        try:
            amount = int(text.strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً أكبر من صفر.")
            return
        target_id = context.user_data.get("points_target_id")
        mode      = context.user_data.get("points_mode", "give")
        context.user_data["state"] = "main_menu"
        if not target_id:
            await update.message.reply_text("⚠️ انتهت الجلسة.", reply_markup=owner_settings_kb())
            return
        target = get_user(target_id)
        uname  = f"@{target['username']}" if target and target.get("username") else f"ID: {target_id}"
        if mode == "give":
            add_points(target_id, amount)
            new_bal = (target.get("points") or 0) + amount
            await update.message.reply_text(
                f"✅ *تم منح {amount} نقطة*\n\n"
                f"👤 {md_escape(target.get('full_name','') if target else '')} ({md_escape(uname)})\n"
                f"💰 الرصيد الجديد: *{new_bal}* نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_points")]])
            )
            try:
                await context.bot.send_message(target_id, f"🎁 تم إضافة *{amount}* نقطة إلى رصيدك من قبل الإدارة.\n💰 رصيدك الآن: *{new_bal}* نقطة", parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass
        else:
            actual = deduct_points_clamped(target_id, amount)
            new_bal = max(0, (target.get("points") or 0) - actual)
            if actual == 0:
                await update.message.reply_text(
                    f"⚠️ رصيد العضو صفر — لم يُخصم شيء.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_points")]])
                )
            else:
                await update.message.reply_text(
                    f"✅ *تم خصم {actual} نقطة*\n\n"
                    f"👤 {md_escape(target.get('full_name','') if target else '')} ({md_escape(uname)})\n"
                    f"💰 الرصيد الجديد: *{new_bal}* نقطة",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_points")]])
                )
                try:
                    await context.bot.send_message(target_id, f"⚠️ تم خصم *{actual}* نقطة من رصيدك من قبل الإدارة.\n💰 رصيدك الآن: *{new_bal}* نقطة", parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    pass
        return

    if is_own and state == "os_await_pkg_stars":
        try:
            stars = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        if stars <= 0:
            await update.message.reply_text("⚠️ يجب أن يكون أكبر من صفر.")
            return
        with db_conn() as c:
            c.execute("INSERT INTO exchange_star_packages (stars) VALUES (?)", (stars,))
        rate = int(get_setting("exchange_star_rate") or "2000")
        cost = stars * rate
        await update.message.reply_text(
            f"✅ *تمت إضافة الباقة بنجاح!*\n\n⭐ {stars} نجمة = {cost} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_edit_await_name":
        sid = context.user_data.get("edit_svc_id")
        with db_conn() as c:
            c.execute("UPDATE services SET name_ar=? WHERE id=?", (text, sid))
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(f"✅ تم تحديث اسم الخدمة إلى: *{text}*", parse_mode=ParseMode.MARKDOWN,
                                         reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_edit_await_min":
        try:
            mn = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        sid = context.user_data.get("edit_svc_id")
        with db_conn() as c:
            c.execute("UPDATE services SET min_qty=? WHERE id=?", (mn, sid))
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(f"✅ تم تحديث الحد الأدنى إلى: {mn}", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_edit_await_max":
        try:
            mx = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        sid = context.user_data.get("edit_svc_id")
        with db_conn() as c:
            c.execute("UPDATE services SET max_qty=? WHERE id=?", (mx, sid))
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(f"✅ تم تحديث الحد الأعلى إلى: {mx}", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_edit_await_price":
        try:
            price = float(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        sid = context.user_data.get("edit_svc_id")
        with db_conn() as c:
            c.execute("UPDATE services SET price_per_point=? WHERE id=?", (price, sid))
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(f"✅ تم تحديث السعر إلى: {fmt_price(price)} نقطة/1000 وحدة", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_await_shared_description":
        shared_description = None if text.strip() == "-" else text.strip()
        if shared_description is None:
            description_label = "حذف الوصف من الخدمات المحددة"
        else:
            description_label = shared_description
        context.user_data["shared_description"] = shared_description
        context.user_data["shared_desc_ids"] = []
        context.user_data["state"] = "main_menu"
        selection_text, selection_rows = _render_description_service_selection()
        await update.message.reply_text(
            f"✅ تم حفظ الوصف المشترك:\n\n{description_label}\n\n"
            "الآن حدد الخدمات التي تريد تطبيقه عليها:",
            reply_markup=InlineKeyboardMarkup(selection_rows),
        )
        return

    if is_own and state == "os_edit_await_desc":
        sid = context.user_data.get("edit_svc_id")
        if text.strip() == "-":
            new_desc = None
        else:
            with db_conn() as c:
                svc_row = c.execute("SELECT price_per_point FROM services WHERE id=%s", (sid,)).fetchone()
            ppp = float(svc_row["price_per_point"] or 0) if svc_row else 0.0
            raw = text.strip()
            new_desc = _strip_price_from_desc(raw, ppp)
        with db_conn() as c:
            c.execute("UPDATE services SET description=%s WHERE id=%s", (new_desc, sid))
        context.user_data["state"] = "main_menu"
        if new_desc and new_desc != text.strip() and text.strip() != "-":
            msg = f"✅ تم حذف السعر من الوصف تلقائياً.\nالوصف بعد التنظيف:\n{new_desc}"
        elif new_desc is None and text.strip() != "-":
            msg = "⚠️ تم حذف الوصف كاملاً لأنه لم يتبق سوى السعر."
        elif new_desc is None:
            msg = "✅ تم حذف الوصف."
        else:
            msg = f"✅ تم تحديث الوصف إلى:\n{new_desc}"
        await update.message.reply_text(msg, reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_edit_await_apiid":
        try:
            api_id = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        sid   = context.user_data.get("edit_svc_id")
        panel = context.user_data.get("edit_svc_panel", 1)
        info = await asyncio.to_thread(smm_service_info, api_id, panel=panel)
        if not info:
            site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
            await update.message.reply_text(f"⚠️ لم يتم العثور على الخدمة في موقع {site_name}. تأكد من الرقم.")
            return
        with db_conn() as c:
            c.execute("UPDATE services SET api_service_id=?, panel=? WHERE id=?", (api_id, panel, sid))
        context.user_data["state"] = "main_menu"
        site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
        await update.message.reply_text(
            f"✅ تم ربط الخدمة برقم *{api_id}* من موقع {site_name}.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    await update.message.reply_text("🏠 القائمة الرئيسية:", reply_markup=main_menu_kb(is_own))

async def _remove_2fa_from_session(session_string: str) -> tuple[bool, str, str | None]:
    """
    يزيل التحقق بخطوتين (2FA) من حساب باستخدام جلسة تيلثون.
    الترتيب:
      1. يجرب كلمة المرور المخزّنة في قاعدة البيانات (إن عُرف رقم الهاتف).
      2. يجرب كلمة المرور الثابتة للمالك (OWNER_FIXED_2FA_PASSWORD).
      3. إن فشل الاثنان يُعيد الفشل مع رقم الهاتف.
    يُرجع (success, message, phone_or_None).
    """
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return False, "TELEGRAM_API_ID/HASH غير مضبوط", None

    client = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    phone = None
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            await client.disconnect()
            return False, "الجلسة منتهية أو غير صالحة", None

        me = await client.get_me()
        phone = f"+{me.phone}" if me and me.phone and not str(me.phone).startswith("+") else (me.phone if me else None)

        pwd_state = await client(GetPasswordRequest())
        if not pwd_state.has_password:
            await client.disconnect()
            return True, "✅ لا يوجد تحقق ثنائي على هذا الحساب أصلاً", phone

        candidates: list[str] = []
        if phone:
            with db_conn() as _dc:
                _row = _dc.execute(
                    "SELECT twofa_password FROM number_stock WHERE phone_number=%s AND twofa_password IS NOT NULL",
                    (phone,)
                ).fetchone()
            if _row and _row["twofa_password"]:
                candidates.append(_row["twofa_password"])
        if OWNER_FIXED_2FA_PASSWORD and OWNER_FIXED_2FA_PASSWORD not in candidates:
            candidates.append(OWNER_FIXED_2FA_PASSWORD)

        removed = False
        for pw in candidates:
            try:
                _expected_2fa_change[phone or ""] = time.time()
                await client.edit_2fa(current_password=pw, new_password="")
                removed = True
                if phone:
                    with db_conn() as _uc:
                        _uc.execute(
                            "UPDATE number_stock SET twofa_password=NULL, auto_2fa_enabled=FALSE WHERE phone_number=%s",
                            (phone,)
                        )
                break
            except Exception as _pe:
                err = str(_pe).upper()
                if "PASSWORD_HASH_INVALID" in err or "SRP_ID_INVALID" in err:
                    continue  # كلمة المرور خاطئة، جرّب التالية
                await client.disconnect()
                return False, f"❌ خطأ أثناء الإزالة: {_pe}", phone

        await client.disconnect()
        if removed:
            return True, "✅ تم إزالة التحقق الثنائي بنجاح", phone
        else:
            return False, "❌ كلمة المرور غير معروفة — أرسل كلمة المرور الصحيحة نصاً بعد الملف", phone

    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        return False, f"❌ خطأ: {e}", phone

async def handle_hex_text_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل ملف TXT من المالك يحتوي auth_key_hex:dc_id في كل سطر."""
    user = update.effective_user
    if user.id != OWNER_ID:
        return
    doc = update.message.document
    if not doc:
        return

    fname = doc.file_name or "sessions.txt"
    msg = await update.message.reply_text("⏳ جاري قراءة ملف الجلسات...")
    raw_bytes = None
    last_error = None
    for attempt in range(3):
        try:
            tg_file = await context.bot.get_file(doc.file_id)
            raw_bytes = await tg_file.download_as_bytearray()
            break
        except Exception as error:
            last_error = error
            if attempt < 2:
                await asyncio.sleep(2)

    if raw_bytes is None:
        await msg.edit_text(
            f"❌ تعذّر تنزيل الملف بعد 3 محاولات: `{last_error}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    raw_text = bytes(raw_bytes).decode("utf-8-sig", errors="replace")
    sessions, bad_lines, recognized = _parse_hex_session_text(raw_text)
    if not recognized:
        await msg.edit_text(
            "❌ صيغة الملف غير صحيحة.\n"
            "يجب أن يحتوي كل سطر على:\n"
            "`auth_key_hex:dc_id`\n"
            "ويجب أن يكون auth_key بطول 512 حرفًا وdc_id بين 1 و5.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if not sessions:
        await msg.edit_text(
            "❌ لم أجد أي جلسة صالحة في الملف.\n"
            + "\n".join(f"• {line}" for line in bad_lines[:10]),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    warn = f"\n⚠️ {len(bad_lines)} سطر مرفوض." if bad_lines else ""
    progress = await msg.edit_text(
        f"⏳ تم العثور على {len(sessions)} جلسة في `{fname}`، جاري التحقق...{warn}",
        parse_mode=ParseMode.MARKDOWN,
    )
    ok_list, fail_list = [], []
    for index, session in enumerate(sessions, start=1):
        client = None
        try:
            if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
                fail_list.append(f"#{index}: متغيرات Telegram API غير مضبوطة")
                continue
            client = TelegramClient(
                StringSession(session),
                int(TELEGRAM_API_ID),
                TELEGRAM_API_HASH,
            )
            await asyncio.wait_for(client.connect(), timeout=20)
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                fail_list.append(f"#{index}: الجلسة منتهية أو غير مفعّلة")
                continue
            me = await client.get_me()
            phone = me.phone if me.phone.startswith("+") else f"+{me.phone}"
            with db_conn() as db:
                existing = db.execute(
                    "SELECT id FROM number_stock WHERE phone_number=%s",
                    (phone,),
                ).fetchone()
                if existing:
                    db.execute(
                        "UPDATE number_stock SET session_string=%s, assigned_to=NULL,"
                        " assigned_at=NULL, forced_ref_excluded=FALSE WHERE phone_number=%s",
                        (session, phone),
                    )
                else:
                    db.execute(
                        "INSERT INTO number_stock "
                        "(phone_number, session_string, forced_ref_excluded) VALUES (%s,%s,FALSE)",
                        (phone, session),
                    )
            ok_list.append(phone)
        except asyncio.TimeoutError:
            fail_list.append(f"#{index}: انتهت مهلة الاتصال")
        except Exception as error:
            fail_list.append(f"#{index}: تعذّر التحقق ({type(error).__name__})")
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass
        if index % 3 == 0 or index == len(sessions):
            try:
                await progress.edit_text(
                    f"⏳ *{index}/{len(sessions)}* جاري التحقق...\n"
                    f"✅ {len(ok_list)} نجح | ❌ {len(fail_list)} فشل",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

    result_lines = [
        f"📄 *نتيجة ملف الجلسات* — ✅ {len(ok_list)} نجح | ❌ {len(fail_list)} فشل"
    ]
    if ok_list:
        result_lines.append("\n✅ *الحسابات المضافة:*")
        result_lines.extend(f"  • `{phone}`" for phone in ok_list[:30])
        if len(ok_list) > 30:
            result_lines.append(f"  ... و{len(ok_list) - 30} أخرى")
    if fail_list:
        result_lines.append("\n❌ *الحسابات الفاشلة:*")
        result_lines.extend(f"  • {failure}" for failure in fail_list[:20])
        if len(fail_list) > 20:
            result_lines.append(f"  ... و{len(fail_list) - 20} أخرى")
    await progress.edit_text("\n".join(result_lines), parse_mode=ParseMode.MARKDOWN)


async def handle_json_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل ملف JSON من المالك ويستورد الجلسات المحتواة فيه مباشرة."""
    user = update.effective_user
    if user.id != OWNER_ID:
        return
    doc = update.message.document
    if not doc:
        return
    msg = await update.message.reply_text("⏳ جاري قراءة الملف...")
    import json as _json
    raw_bytes = None
    _last_err = None
    for _attempt in range(3):
        try:
            file = await context.bot.get_file(doc.file_id)
            raw_bytes = await file.download_as_bytearray()
            break
        except Exception as e:
            _last_err = e
            if _attempt < 2:
                await asyncio.sleep(2)
    if raw_bytes is None:
        await msg.edit_text(f"❌ تعذّر تنزيل الملف (3 محاولات):\n`{_last_err}`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        data = _json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        await msg.edit_text(f"❌ تعذّر قراءة الملف:\n`{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    if isinstance(data, dict):
        data = [data]
    elif isinstance(data, str):
        data = [{"session_string": data}]

    sessions = []
    for item in data:
        if isinstance(item, str):
            sessions.append({"session": _maybe_convert_session(item.strip()), "phone": None})
        elif isinstance(item, dict):
            if "dc_id" in item and "auth_key" in item:
                converted = pyrogram_json_to_telethon(item)
                if converted:
                    phone = (
                        item.get("phone") or
                        item.get("phone_number") or
                        item.get("mobile") or None
                    )
                    sessions.append({"session": converted, "phone": phone})
                continue
            sess = (
                item.get("session_string") or
                item.get("session") or
                item.get("string_session") or ""
            ).strip()
            phone = (
                item.get("phone") or
                item.get("phone_number") or
                item.get("mobile") or None
            )
            if sess:
                sessions.append({"session": _maybe_convert_session(sess), "phone": phone})

    if not sessions:
        await msg.edit_text("❌ لم أجد أي جلسة صالحة في الملف. تأكد أن الملف يحتوي حقل `session_string` أو حقلي `dc_id` و`auth_key` (صيغة Pyrogram).")
        return

    if context.user_data.get("state") == "os_remove_2fa_mode":
        await msg.edit_text(f"⏳ جاري إزالة التحقق من {len(sessions)} حساب...")
        ok_list, fail_list = [], []
        for idx, entry in enumerate(sessions):
            ok, result_msg, phone = await _remove_2fa_from_session(entry["session"])
            label = phone or entry["phone"] or f"#{idx+1}"
            if ok:
                ok_list.append(f"`{label}` — {result_msg}")
            else:
                fail_list.append(f"`{label}` — {result_msg}")
        lines = [f"🔓 *نتيجة إزالة التحقق ({len(sessions)} حساب):*\n"]
        if ok_list:
            lines.append(f"✅ *نجح ({len(ok_list)}):*")
            lines.extend(f"  • {x}" for x in ok_list)
        if fail_list:
            lines.append(f"\n❌ *فشل ({len(fail_list)}):*")
            lines.extend(f"  • {x}" for x in fail_list[:20])
            if len(fail_list) > 20:
                lines.append(f"  ... و{len(fail_list)-20} أخرى")
        await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        return

    await msg.edit_text(f"⏳ تم العثور على {len(sessions)} جلسة، جاري الاستيراد والتدوير الفوري...")
    ok_list, fail_list = [], []

    for idx, entry in enumerate(sessions):
        sess  = entry["session"]
        phone_hint = entry["phone"]
        try:
            if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
                fail_list.append(phone_hint or f"#{idx+1}")
                continue
            client = TelegramClient(StringSession(sess), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await asyncio.wait_for(client.connect(), timeout=20)
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                await client.disconnect()
                fail_list.append(phone_hint or f"#{idx+1}: جلسة منتهية")
                continue
            me = await client.get_me()
            phone = me.phone if me.phone.startswith("+") else f"+{me.phone}"
            await client.disconnect()
            # ── حفظ الجلسة الأصلية مؤقتاً ──────────────────────────────
            with db_conn() as _c:
                exists = _c.execute(
                    "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
                ).fetchone()
                if exists:
                    _c.execute(
                        "UPDATE number_stock SET session_string=%s, assigned_to=NULL, assigned_at=NULL,"
                        " forced_ref_excluded=FALSE WHERE phone_number=%s",
                        (sess, phone)
                    )
                else:
                    _c.execute(
                        "INSERT INTO number_stock (phone_number, session_string, forced_ref_excluded)"
                        " VALUES (%s,%s,FALSE)",
                        (phone, sess)
                    )
            # ── تدوير فوري: جلسة جديدة + حذف القديمة ──────────────────
            rot_ok, rot_res = await _rotate_one_session(phone, sess)
            if rot_ok:
                final_sess = rot_res
                with db_conn() as _rc:
                    _rc.execute(
                        "UPDATE number_stock SET session_string=%s, sessions_reset=TRUE WHERE phone_number=%s",
                        (final_sess, phone)
                    )
                ok_list.append(f"{phone} 🔁")
            else:
                ok_list.append(f"{phone} ⚠️ تدوير: {rot_res}")
        except Exception as _e:
            fail_list.append(phone_hint or f"#{idx+1}: {_e}")

        if (idx + 1) % 3 == 0 or (idx + 1) == len(sessions):
            try:
                await msg.edit_text(
                    f"⏳ *{idx+1}/{len(sessions)}* جاري الاستيراد والتدوير...\n"
                    f"✅ {len(ok_list)} نجح | ❌ {len(fail_list)} فشل",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

    # ── رسالة الاستيراد ───────────────────────────────────────────────
    import_ok  = [p for p in ok_list if not p.startswith("⚠️")]
    import_all = ok_list + fail_list
    lines = [f"✅ *تم استيراد {len(import_ok)} حساب بنجاح*"]
    for p in ok_list:
        phone_clean = p.split(" ")[0]
        lines.append(f"  • `{phone_clean}`")
    if fail_list:
        lines.append(f"\n❌ *فشل {len(fail_list)}:*")
        for f_ in fail_list[:20]:
            lines.append(f"  • {f_}")
        if len(fail_list) > 20:
            lines.append(f"  ... و{len(fail_list)-20} أخرى")
    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    # ── رسالة منفصلة لحالة التدوير ───────────────────────────────────
    rot_ok_phones   = [p for p in ok_list if "🔁" in p]
    rot_fail_phones = [p for p in ok_list if "⚠️" in p]
    rot_lines = ["🔁 *تقرير التدوير*\n"]
    if rot_ok_phones:
        rot_lines.append(f"✅ *نجح التدوير ({len(rot_ok_phones)}):*")
        for entry in rot_ok_phones:
            phone_clean = entry.split(" ")[0]
            rot_lines.append(f"  • `{phone_clean}` — الجلسة القديمة محذوفة نهائياً")
    if rot_fail_phones:
        rot_lines.append(f"\n❌ *فشل التدوير ({len(rot_fail_phones)}):*")
        for entry in rot_fail_phones:
            phone_clean = entry.split(" ")[0]
            reason = entry.split("تدوير: ")[-1] if "تدوير: " in entry else ""
            rot_lines.append(f"  • `{phone_clean}` — {reason}")
    if not rot_ok_phones and not rot_fail_phones:
        rot_lines.append("⚠️ لم يُجرَ أي تدوير (كل الاستيرادات فشلت)")
    await update.effective_message.reply_text(
        "\n".join(rot_lines), parse_mode=ParseMode.MARKDOWN
    )

async def handle_session_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يستقبل ملف .session (SQLite) من المالك ويستورده مباشرةً.
    يدعم صيغتَي Telethon و Pyrogram.
    Telethon  → جدول sessions: dc_id, server_address, port, auth_key (blob)
    Pyrogram  → جدول sessions: dc_id, auth_key (blob)
    """
    user = update.effective_user
    if user.id != OWNER_ID:
        return
    doc = update.message.document
    if not doc:
        return
    fname = doc.file_name or ""
    if not fname.lower().endswith(".session"):
        return

    msg = await update.message.reply_text(f"⏳ جاري قراءة الملف `{fname}`...", parse_mode=ParseMode.MARKDOWN)
    import tempfile, sqlite3 as _sq3

    raw_bytes = None
    _last_err2 = None
    for _att2 in range(3):
        try:
            tg_file = await context.bot.get_file(doc.file_id)
            raw_bytes = await tg_file.download_as_bytearray()
            break
        except Exception as e:
            _last_err2 = e
            if _att2 < 2:
                await asyncio.sleep(2)
    if raw_bytes is None:
        await msg.edit_text(f"❌ تعذّر تنزيل الملف (3 محاولات):\n`{_last_err2}`", parse_mode=ParseMode.MARKDOWN)
        return

    session_string = None
    detected_format = "?"
    try:
        with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as tf:
            tf.write(raw_bytes)
            tf_path = tf.name

        conn = _sq3.connect(tf_path)
        conn.row_factory = _sq3.Row
        cur = conn.cursor()

        try:
            row = cur.execute(
                "SELECT dc_id, server_address, port, auth_key FROM sessions LIMIT 1"
            ).fetchone()
            if row and row["auth_key"] and len(row["auth_key"]) == 256:
                dc_id     = int(row["dc_id"])
                auth_key  = bytes(row["auth_key"])
                try:
                    srv_ip   = _socket.inet_aton(row["server_address"])
                    srv_port = int(row["port"])
                except Exception:
                    srv_ip_str, srv_port = _TG_DC.get(dc_id, ("149.154.167.51", 443))
                    srv_ip   = _socket.inet_aton(srv_ip_str)
                packed = struct.pack(">B4sH256s", dc_id, srv_ip, srv_port, auth_key)
                session_string = "1" + base64.urlsafe_b64encode(packed).decode("ascii")
                detected_format = "Telethon"
        except _sq3.OperationalError:
            pass

        if not session_string:
            try:
                row = cur.execute(
                    "SELECT dc_id, auth_key FROM sessions LIMIT 1"
                ).fetchone()
                if row and row["auth_key"] and len(bytes(row["auth_key"])) == 256:
                    dc_id    = int(row["dc_id"])
                    auth_key = bytes(row["auth_key"])
                    ip_str, port_dc = _TG_DC.get(dc_id, ("149.154.167.51", 443))
                    packed = struct.pack(
                        ">B4sH256s",
                        dc_id, _socket.inet_aton(ip_str), port_dc, auth_key
                    )
                    session_string = "1" + base64.urlsafe_b64encode(packed).decode("ascii")
                    detected_format = "Pyrogram"
            except _sq3.OperationalError:
                pass

        conn.close()
        import os as _os; _os.unlink(tf_path)
    except Exception as e:
        await msg.edit_text(f"❌ تعذّر قراءة قاعدة البيانات:\n`{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    if not session_string:
        await msg.edit_text(
            "❌ لم أتمكن من استخراج الجلسة.\n"
            "تأكد أن الملف جلسة Telethon أو Pyrogram صالحة (بها `auth_key` بطول 256 بايت).",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await msg.edit_text(f"⏳ تم كشف صيغة *{detected_format}* — جاري التحقق...", parse_mode=ParseMode.MARKDOWN)

    if context.user_data.get("state") == "os_remove_2fa_mode":
        ok, result_msg, phone = await _remove_2fa_from_session(session_string)
        label = phone or fname
        icon = "✅" if ok else "❌"
        await msg.edit_text(
            f"{icon} *{label}*\n{result_msg}",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
            await msg.edit_text("❌ TELEGRAM_API_ID / TELEGRAM_API_HASH غير محدّدَين.")
            return
        client = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            await client.disconnect()
            await msg.edit_text("❌ الجلسة منتهية أو غير صالحة — لم يتم الاستيراد.")
            return
        me = await client.get_me()
        phone = me.phone if me.phone.startswith("+") else f"+{me.phone}"
        await client.disconnect()
    except Exception as e:
        await msg.edit_text(f"❌ خطأ أثناء التحقق:\n`{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    _ref_only_flag = context.user_data.get("referral_only_import", False)
    with db_conn() as _c:
        exists = _c.execute(
            "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
        ).fetchone()
        if exists:
            _c.execute(
                "UPDATE number_stock SET session_string=%s, assigned_to=NULL, assigned_at=NULL,"
                " forced_ref_excluded=FALSE"
                + (", referral_only=TRUE" if _ref_only_flag else "") +
                " WHERE phone_number=%s",
                (session_string, phone)
            )
        else:
            _c.execute(
                "INSERT INTO number_stock (phone_number, session_string, forced_ref_excluded, referral_only)"
                " VALUES (%s,%s,FALSE,%s)",
                (phone, session_string, _ref_only_flag)
            )

    # ── تدوير فوري: جلسة جديدة + حذف القديمة نهائياً ────────────────
    await msg.edit_text(f"⏳ جاري تدوير الجلسة للرقم `{phone}`...", parse_mode=ParseMode.MARKDOWN)
    rot_ok, rot_res = await _rotate_one_session(phone, session_string)
    if rot_ok:
        session_string = rot_res
        with db_conn() as _rc:
            _rc.execute(
                "UPDATE number_stock SET session_string=%s, sessions_reset=TRUE WHERE phone_number=%s",
                (session_string, phone)
            )
    # ── تشغيل مهام الإحالة التلقائية فوراً للرقم الجديد ──
    try:
        _ns_row = None
        with db_conn() as _nc:
            _ns_row = _nc.execute("SELECT id FROM number_stock WHERE phone_number=%s", (phone,)).fetchone()
        if _ns_row:
            asyncio.create_task(_run_referral_for_new_number(phone, session_string, _ns_row["id"]))
    except Exception as _re:
        logger.debug(f"_run_referral_for_new_number spawn: {_re}")
    rot_note = " 🔁 تم التدوير — الجلسة القديمة محذوفة نهائياً" if rot_ok else f" ⚠️ التدوير فشل: {rot_res}"

    # ── تفعيل 2FA تلقائياً ────────────────────────────────────────────
    kick_note  = ""
    twofa_note = ""
    try:
        _kick_cl = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await _kick_cl.connect()
        if await _kick_cl.is_user_authorized():
            try:
                await _kick_cl(ResetAuthorizationsRequest())
                # ─── فحص is_solo بعد الطرد الفوري ─────────────────────────
                try:
                    _dev_imm = await get_device_count(_kick_cl)
                    _solo_imm = (_dev_imm == 1)
                    with db_conn() as _si:
                        _si_row = _si.execute(
                            "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
                        ).fetchone()
                    if _si_row:
                        with db_conn() as _su2:
                            _su2.execute(
                                "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s WHERE id=%s",
                                (_solo_imm, _si_row["id"])
                            )
                        # ─── تسجيل IP الجلسة لكشف الخطف الصامت ──────────────
                        try:
                            _bot_ip2 = await get_session_ip(_kick_cl)
                            if _bot_ip2:
                                with db_conn() as _ipdb2:
                                    _ipdb2.execute(
                                        "UPDATE number_stock SET bot_session_ip=%s WHERE id=%s",
                                        (_bot_ip2, _si_row["id"])
                                    )
                                logger.info(f"🔐 session_ip: سُجِّل IP={_bot_ip2} للرقم {phone}")
                        except Exception as _ip_e2:
                            logger.debug(f"⚠️ تعذّر تسجيل IP الجلسة للرقم {phone}: {_ip_e2}")
                        if _solo_imm:
                            asyncio.create_task(
                                _test_and_set_can_send_code(phone, session_string, _si_row["id"])
                            )
                    _solo_emoji = " ✅ البوت وحده" if _solo_imm else " ⚠️ ما زال هناك جلسات"
                    kick_note = f"\n🔒 تم طرد كل الجلسات الأخرى تلقائياً.{_solo_emoji}"
                except Exception as _di:
                    kick_note = "\n🔒 تم طرد كل الجلسات الأخرى تلقائياً."
                    logger.debug(f"⚠️ فحص is_solo فوري فشل للرقم {phone}: {_di}")
            except Exception as _ke:
                _ke_str = str(_ke)
                if "too new" in _ke_str or "cannot be used to reset" in _ke_str:
                    kick_note = "\n⏳ الجلسة جديدة — يُعيد البوت المحاولة تلقائياً كل بضع ثوانٍ."
                    async def _retry_kick_loop(ss, ph, bot_ref):
                        delay = 0
                        step  = 5
                        while True:
                            if delay > 0:
                                await asyncio.sleep(delay)
                            delay += step
                            try:
                                _rc2 = TelegramClient(StringSession(ss), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                                await _rc2.connect()
                                authorized = await _rc2.is_user_authorized()
                                if not authorized:
                                    await _rc2.disconnect()
                                    logger.warning(f"⚠️ retry_kick: جلسة {ph} منتهية — إيقاف المحاولات")
                                    break
                                await _rc2(ResetAuthorizationsRequest())
                                # ─── فحص is_solo بعد نجاح الطرد ────────────
                                _dev_r = -1
                                try:
                                    _dev_r = await get_device_count(_rc2)
                                except Exception:
                                    pass
                                _solo_r = (_dev_r == 1)
                                with db_conn() as _sr:
                                    _sr_row = _sr.execute(
                                        "SELECT id FROM number_stock WHERE phone_number=%s", (ph,)
                                    ).fetchone()
                                if _sr_row:
                                    with db_conn() as _su:
                                        _su.execute(
                                            "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s WHERE id=%s",
                                            (_solo_r, _sr_row["id"])
                                        )
                                    if _solo_r:
                                        asyncio.create_task(
                                            _ensure_can_send_code(ph, ss, _sr_row["id"])
                                        )
                                await _rc2.disconnect()
                                logger.info(f"🔒 retry_kick: طُردت الجلسات للرقم {ph} بعد {delay - step} ث | is_solo={_solo_r}")
                                _ng_rk = NUMBERS_GROUP_ID or OWNER_ID
                                if _ng_rk and bot_ref:
                                    try:
                                        _solo_note = " ✅ البوت الجلسة الوحيدة" if _solo_r else " ⚠️ ما زالت هناك جلسات"
                                        await bot_ref.send_message(
                                            _ng_rk,
                                            f"🔒 تم طرد كل الجلسات الأخرى للرقم `{ph}` "
                                            f"(بعد {delay - step} ثانية من الاستيراد).{_solo_note}",
                                            parse_mode=ParseMode.MARKDOWN
                                        )
                                    except Exception:
                                        pass
                                break  # نجح الطرد → توقف
                            except Exception as _re2:
                                _re2_str = str(_re2)
                                if "too new" in _re2_str or "cannot be used to reset" in _re2_str:
                                    logger.info(f"⏳ retry_kick: {ph} لا يزال جديداً، انتظار {delay} ث...")
                                    try:
                                        await _rc2.disconnect()
                                    except Exception:
                                        pass
                                    continue  # نكرر بعد delay أطول
                                else:
                                    logger.warning(f"⚠️ retry_kick: خطأ غير متوقع للرقم {ph}: {_re2_str[:80]}")
                                    try:
                                        await _rc2.disconnect()
                                    except Exception:
                                        pass
                                    break
                    asyncio.create_task(_retry_kick_loop(session_string, phone, context.bot))
                else:
                    kick_note = f"\n⚠️ تعذّر طرد الجلسات الأخرى: {_ke_str[:80]}"
        await _kick_cl.disconnect()
    except Exception as _ce:
        kick_note = f"\n⚠️ خطأ أثناء الطرد: {_ce}"

    with db_conn() as _rc:
        _stock_row = _rc.execute(
            "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
        ).fetchone()
    if _stock_row:
        try:
            _2fa_cl = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await _2fa_cl.connect()
            if await _2fa_cl.is_user_authorized():
                _pwd_state = await _2fa_cl(GetPasswordRequest())
                if _pwd_state.has_password:
                    try:
                        await _2fa_cl.edit_2fa(
                            current_password=None,
                            new_password=OWNER_FIXED_2FA_PASSWORD,
                        )
                        with db_conn() as _dc:
                            _dc.execute(
                                "UPDATE number_stock SET twofa_password=%s WHERE id=%s",
                                (OWNER_FIXED_2FA_PASSWORD, _stock_row["id"])
                            )
                        twofa_note = f"\n🔐 تم تغيير كلمة 2FA إلى: `{OWNER_FIXED_2FA_PASSWORD}`"
                    except Exception:
                        try:
                            _reset_res = await _2fa_cl(ResetPasswordRequest())
                            import datetime as _dt
                            if hasattr(_reset_res, "retry_date") and _reset_res.retry_date:
                                _retry_ts = _reset_res.retry_date
                            elif hasattr(_reset_res, "until_date") and _reset_res.until_date:
                                _retry_ts = _reset_res.until_date
                            else:
                                _retry_ts = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=7)
                            with db_conn() as _dc:
                                _dc.execute(
                                    "UPDATE number_stock SET twofa_reset_date=%s WHERE id=%s",
                                    (_retry_ts, _stock_row["id"])
                                )
                            twofa_note = (
                                f"\n⏳ بدأ إجراء إعادة تعيين 2FA (7 أيام).\n"
                                f"سيُكمل البوت التغيير تلقائياً بتاريخ: "
                                f"`{_retry_ts.strftime('%Y-%m-%d %H:%M') if hasattr(_retry_ts, 'strftime') else _retry_ts}`"
                            )
                            logger.info(f"⏳ بدأ reset 2FA للرقم {phone} — موعد الاكتمال: {_retry_ts}")
                        except Exception as _re:
                            twofa_note = f"\n⚠️ الحساب عليه 2FA مجهولة — تعذّر بدء إعادة التعيين: {str(_re)[:80]}"
                else:
                    try:
                        await _2fa_cl.edit_2fa(
                            new_password=OWNER_FIXED_2FA_PASSWORD,
                        )
                        with db_conn() as _dc:
                            _dc.execute(
                                "UPDATE number_stock SET twofa_password=%s, auto_2fa_enabled=TRUE WHERE id=%s",
                                (OWNER_FIXED_2FA_PASSWORD, _stock_row["id"])
                            )
                        twofa_note = f"\n🔐 تم تفعيل التحقق بخطوتين.\n🗝 كلمة المرور: `{OWNER_FIXED_2FA_PASSWORD}`"
                    except Exception as _e2:
                        twofa_note = f"\n⚠️ تعذّر تعيين 2FA: {str(_e2)[:80]}"
            await _2fa_cl.disconnect()
        except Exception as _2fa_err:
            twofa_note = f"\n⚠️ خطأ في 2FA: {str(_2fa_err)[:80]}"

    # ── رسالة الاستيراد ───────────────────────────────────────────────
    await msg.edit_text(
        f"✅ *تم استيراد الجلسة بنجاح!*\n\n"
        f"📱 الرقم: `{phone}`\n"
        f"🔧 الصيغة: {detected_format}\n"
        f"📄 الملف: `{fname}`"
        f"{kick_note}{twofa_note}",
        parse_mode=ParseMode.MARKDOWN
    )

    # ── رسالة منفصلة لحالة التدوير ───────────────────────────────────
    if rot_ok:
        rot_report = (
            f"🔁 *تقرير التدوير — `{phone}`*\n\n"
            f"✅ نجح التحقق 1: الجلسة الجديدة مفعّلة\n"
            f"✅ نجح التحقق 2: تم الوصول للحساب\n"
            f"✅ نجح التحقق 3: الجلسة القديمة محذوفة نهائياً\n\n"
            f"🛡 الجلسة القديمة لن تعمل مجدداً"
        )
    else:
        rot_report = (
            f"🔁 *تقرير التدوير — `{phone}`*\n\n"
            f"❌ *فشل التدوير*\n"
            f"`{rot_res}`\n\n"
            f"⚠️ الجلسة القديمة لا تزال صالحة — يُنصح بإعادة الاستيراد"
        )
    await update.effective_message.reply_text(rot_report, parse_mode=ParseMode.MARKDOWN)

async def _import_one_session_bytes(
    raw_bytes: bytes,
    fname: str,
    context,
    remove_2fa_mode: bool = False,
) -> dict:
    """
    يحاول استخراج session_string من bytes تمثّل ملف .session (SQLite) أو .json.
    يُرجع dict بالمفاتيح:
        ok        bool
        phone     str | None
        msg       str  — رسالة النتيجة للعرض
        session   str | None  — session_string المستخرج
        stock_id  int | None
    """
    import tempfile, sqlite3 as _sq3b, json as _jb, os as _osb

    session_string = None
    detected_format = "?"

    try:
        data = _jb.loads(raw_bytes.decode("utf-8"))
        if isinstance(data, str):
            session_string = _maybe_convert_session(data.strip())
            detected_format = "JSON/String"
        elif isinstance(data, dict):
            if "dc_id" in data and "auth_key" in data:
                session_string = pyrogram_json_to_telethon(data)
                detected_format = "Pyrogram-JSON"
            else:
                raw_s = (data.get("session_string") or data.get("session") or "").strip()
                if raw_s:
                    session_string = _maybe_convert_session(raw_s)
                    detected_format = "JSON"
        elif isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, str):
                session_string = _maybe_convert_session(first.strip())
                detected_format = "JSON/List"
            elif isinstance(first, dict):
                if "dc_id" in first and "auth_key" in first:
                    session_string = pyrogram_json_to_telethon(first)
                    detected_format = "Pyrogram-JSON"
                else:
                    raw_s = (first.get("session_string") or first.get("session") or "").strip()
                    if raw_s:
                        session_string = _maybe_convert_session(raw_s)
                        detected_format = "JSON"
    except Exception:
        pass

    if not session_string:
        tf_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as tf:
                tf.write(raw_bytes)
                tf_path = tf.name
            conn = _sq3b.connect(tf_path)
            conn.row_factory = _sq3b.Row
            cur = conn.cursor()

            try:
                row = cur.execute(
                    "SELECT dc_id, server_address, port, auth_key FROM sessions LIMIT 1"
                ).fetchone()
                if row and row["auth_key"] and len(bytes(row["auth_key"])) == 256:
                    dc_id    = int(row["dc_id"])
                    auth_key = bytes(row["auth_key"])
                    try:
                        srv_ip   = _socket.inet_aton(row["server_address"])
                        srv_port = int(row["port"])
                    except Exception:
                        srv_ip_str, srv_port = _TG_DC.get(dc_id, ("149.154.167.51", 443))
                        srv_ip = _socket.inet_aton(srv_ip_str)
                    packed = struct.pack(">B4sH256s", dc_id, srv_ip, srv_port, auth_key)
                    session_string = "1" + base64.urlsafe_b64encode(packed).decode("ascii")
                    detected_format = "Telethon"
            except _sq3b.OperationalError:
                pass

            if not session_string:
                try:
                    row = cur.execute(
                        "SELECT dc_id, auth_key FROM sessions WHERE auth_key IS NOT NULL LIMIT 1"
                    ).fetchone()
                    if row and row["auth_key"]:
                        ak = bytes(row["auth_key"])
                        if len(ak) == 256:
                            dc_id    = int(row["dc_id"]) if row["dc_id"] else 2
                            auth_key = ak
                            ip_str, port_dc = _TG_DC.get(dc_id, ("149.154.167.51", 443))
                            packed = struct.pack(
                                ">B4sH256s",
                                dc_id, _socket.inet_aton(ip_str), port_dc, auth_key
                            )
                            session_string = "1" + base64.urlsafe_b64encode(packed).decode("ascii")
                            detected_format = f"MTProto-DC{dc_id}"
                except _sq3b.OperationalError:
                    pass

            if not session_string:
                try:
                    row = cur.execute(
                        "SELECT dc_id, auth_key FROM sessions LIMIT 1"
                    ).fetchone()
                    if row and row["auth_key"] and len(bytes(row["auth_key"])) == 256:
                        dc_id    = int(row["dc_id"])
                        auth_key = bytes(row["auth_key"])
                        ip_str, port_dc = _TG_DC.get(dc_id, ("149.154.167.51", 443))
                        packed = struct.pack(
                            ">B4sH256s",
                            dc_id, _socket.inet_aton(ip_str), port_dc, auth_key
                        )
                        session_string = "1" + base64.urlsafe_b64encode(packed).decode("ascii")
                        detected_format = "Pyrogram"
                except _sq3b.OperationalError:
                    pass
            conn.close()
        except Exception as _sq_e:
            logger.debug(f"⚠️ _import_one_session_bytes SQLite فشل للملف {fname}: {_sq_e}")
        finally:
            if tf_path:
                try:
                    _osb.unlink(tf_path)
                except Exception:
                    pass

    if not session_string:
        return {"ok": False, "phone": None, "msg": "تعذّر استخراج الجلسة", "session": None, "stock_id": None}

    if remove_2fa_mode:
        ok, result_msg, phone = await _remove_2fa_from_session(session_string)
        return {"ok": ok, "phone": phone, "msg": result_msg, "session": session_string, "stock_id": None}

    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return {"ok": False, "phone": None, "msg": "TELEGRAM_API_ID/HASH غير محدّد", "session": session_string, "stock_id": None}
    try:
        _cli = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(_cli.connect(), timeout=20)
        except asyncio.TimeoutError:
            return {"ok": False, "phone": None, "msg": "انتهت مهلة الاتصال بخوادم تيليجرام", "session": session_string, "stock_id": None}
        try:
            authorized = await asyncio.wait_for(_cli.is_user_authorized(), timeout=10)
        except asyncio.TimeoutError:
            await _cli.disconnect()
            return {"ok": False, "phone": None, "msg": "انتهت مهلة التحقق — الجلسة قد تكون سليمة، أعد المحاولة", "session": session_string, "stock_id": None}
        if not authorized:
            await _cli.disconnect()
            return {"ok": False, "phone": None, "msg": "الجلسة منتهية أو غير صالحة", "session": session_string, "stock_id": None}
        me = await asyncio.wait_for(_cli.get_me(), timeout=10)
        phone = me.phone if me.phone.startswith("+") else f"+{me.phone}"
        await _cli.disconnect()
    except Exception as _ve:
        return {"ok": False, "phone": None, "msg": f"خطأ التحقق: {str(_ve)[:80]}", "session": session_string, "stock_id": None}

    with db_conn() as _dc:
        exists = _dc.execute(
            "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
        ).fetchone()
        if exists:
            _dc.execute(
                "UPDATE number_stock SET session_string=%s, assigned_to=NULL, assigned_at=NULL,"
                " forced_ref_excluded=FALSE WHERE phone_number=%s",
                (session_string, phone)
            )
            stock_id = exists["id"]
        else:
            _dc.execute(
                "INSERT INTO number_stock (phone_number, session_string, forced_ref_excluded)"
                " VALUES (%s,%s,FALSE)",
                (phone, session_string)
            )
            stock_id = _dc.execute(
                "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
            ).fetchone()["id"]

    # ── تدوير فوري: ينشئ auth_key جديد ويحذف القديم نهائياً ──────────
    rot_ok, rot_res = await _rotate_one_session(phone, session_string)
    if rot_ok:
        session_string = rot_res
        with db_conn() as _rc:
            _rc.execute(
                "UPDATE number_stock SET session_string=%s, sessions_reset=TRUE, is_solo=TRUE WHERE id=%s",
                (session_string, stock_id)
            )
        asyncio.create_task(_test_and_set_can_send_code(phone, session_string, stock_id))
        rot_note = "🔁 تدوير"
    else:
        # التدوير فشل — نطرد الجلسات الأخرى على الأقل
        try:
            _kc = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await _kc.connect()
            if await _kc.is_user_authorized():
                try:
                    await _kc(ResetAuthorizationsRequest())
                    with db_conn() as _su:
                        _su.execute("UPDATE number_stock SET sessions_reset=TRUE WHERE id=%s", (stock_id,))
                except Exception as _ke2:
                    _s = str(_ke2)
                    if "too new" in _s or "cannot be used to reset" in _s:
                        asyncio.create_task(_retry_zip_kick(phone, session_string, stock_id, context.bot))
            await _kc.disconnect()
        except Exception:
            pass
        rot_note = f"⚠️ تدوير فشل: {rot_res[:40]}"

    # ── تفعيل 2FA تلقائياً بعد الاستيراد ──────────────────────────────
    async def _post_import_2fa(ph, ss, sid, bot_ref):
        await asyncio.sleep(3)   # انتظار استقرار الجلسة الجديدة
        try:
            ok_2fa, msg_2fa, pwd_2fa = await enable_2fa_for_number(ph, ss, sid, bot=bot_ref)
            if ok_2fa:
                logger.info(f"✅ post_import_2fa: تم تفعيل 2FA للرقم {ph}")
            else:
                logger.warning(f"⚠️ post_import_2fa: فشل 2FA للرقم {ph}: {msg_2fa}")
                # تسجيل في قائمة الإصلاح التلقائي
                _accounts_needing_fixup[sid] = {"phone": ph, "session": ss, "stock_id": sid, "retries": 0}
        except Exception as _2fa_e:
            logger.warning(f"⚠️ post_import_2fa: خطأ للرقم {ph}: {_2fa_e}")
            _accounts_needing_fixup[sid] = {"phone": ph, "session": ss, "stock_id": sid, "retries": 0}

    try:
        _bot_ref = getattr(context, 'bot', None)
        asyncio.create_task(_post_import_2fa(phone, session_string, stock_id, _bot_ref))
    except Exception as _2fa_spawn_e:
        logger.debug(f"_post_import_2fa spawn: {_2fa_spawn_e}")

    # ── تشغيل مهام الإحالة التلقائية فوراً للرقم الجديد ──
    try:
        asyncio.create_task(_run_referral_for_new_number(phone, session_string, stock_id))
    except Exception as _re2:
        logger.debug(f"_run_referral_for_new_number spawn2: {_re2}")

    return {
        "ok": True,
        "phone": phone,
        "msg": f"{detected_format} | {rot_note}",
        "session": session_string,
        "stock_id": stock_id,
        "rot_ok": rot_ok,
        "rot_res": rot_res if not rot_ok else "",
    }

async def _retry_zip_kick(phone: str, session_str: str, stock_id: int, bot_ref):
    """إعادة محاولة طرد الجلسات للحسابات المستوردة من ZIP عندما تكون 'جديدة جداً'."""
    delay, step = 0, 5
    while True:
        if delay > 0:
            await asyncio.sleep(delay)
        delay += step
        try:
            _rc = TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await _rc.connect()
            if not await _rc.is_user_authorized():
                await _rc.disconnect()
                break
            await _rc(ResetAuthorizationsRequest())
            _dv = -1
            try:
                _dv = await get_device_count(_rc)
            except Exception:
                pass
            _solo = (_dv == 1)
            with db_conn() as _su:
                _su.execute(
                    "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s WHERE id=%s",
                    (_solo, stock_id)
                )
            if _solo:
                asyncio.create_task(_ensure_can_send_code(phone, session_str, stock_id))
            await _rc.disconnect()
            logger.info(f"🔒 retry_zip_kick: طُرد {phone} بعد {delay - step} ث | is_solo={_solo}")
            _ng_zk = NUMBERS_GROUP_ID or OWNER_ID
            if _ng_zk and bot_ref:
                try:
                    await bot_ref.send_message(
                        _ng_zk,
                        f"🔒 طُردت جلسات `{phone}` (ZIP, بعد {delay - step} ث)"
                        + (" ✅ البوت وحده" if _solo else ""),
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass
            break
        except Exception as _re:
            _rs = str(_re)
            if "too new" in _rs or "cannot be used to reset" in _rs:
                try:
                    await _rc.disconnect()
                except Exception:
                    pass
                continue
            try:
                await _rc.disconnect()
            except Exception:
                pass
            break

async def _account_fixup_job(context=None):
    """
    يعمل دورياً كل 30 ثانية: يُكرر محاولة الطرد + 2FA لكل حساب في قائمة الإصلاح.
    يُزال الحساب من القائمة عند نجاح كل الإجراءات أو بعد 30 محاولة.
    """
    global _accounts_needing_fixup
    if not _accounts_needing_fixup:
        return
    to_remove = []
    for sid, info in list(_accounts_needing_fixup.items()):
        phone = info["phone"]
        sess  = info["session"]
        retries = info.get("retries", 0)

        if retries >= 30:
            logger.warning(f"⚠️ fixup_job: تجاوز الرقم {phone} الحد الأقصى للمحاولات — إزالة من القائمة")
            to_remove.append(sid)
            continue

        info["retries"] = retries + 1
        kicked_ok = False
        twofa_ok  = False

        try:
            # ─── فحص حالة الحساب من DB ───
            with db_conn() as _db:
                _row = _db.execute(
                    "SELECT session_string, is_solo, twofa_password, auto_2fa_enabled, deleted_at "
                    "FROM number_stock WHERE id=%s", (sid,)
                ).fetchone()
            if not _row or _row["deleted_at"]:
                to_remove.append(sid)
                continue

            # تحديث الجلسة الحالية (قد تكون تغيّرت)
            latest_sess = _row["session_string"] or sess
            info["session"] = latest_sess

            _cli = TelegramClient(StringSession(latest_sess), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await asyncio.wait_for(_cli.connect(), timeout=15)

            if not await asyncio.wait_for(_cli.is_user_authorized(), timeout=8):
                await _cli.disconnect()
                to_remove.append(sid)
                logger.warning(f"⚠️ fixup_job: جلسة {phone} منتهية — إزالة")
                continue

            # ─── محاولة الطرد إذا لم يكن البوت وحيداً ───
            if not _row["is_solo"]:
                try:
                    await asyncio.wait_for(_cli(ResetAuthorizationsRequest()), timeout=15)
                    dev_cnt = await asyncio.wait_for(get_device_count(_cli), timeout=8)
                    is_solo = (dev_cnt == 1)
                    with db_conn() as _du:
                        _du.execute(
                            "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s WHERE id=%s",
                            (is_solo, sid)
                        )
                    kicked_ok = True
                    logger.info(f"🔒 fixup_job: طُردت جلسات {phone} | is_solo={is_solo}")
                    if is_solo:
                        asyncio.create_task(_test_and_set_can_send_code(phone, latest_sess, sid))
                except Exception as _ke:
                    _kes = str(_ke)
                    if "too new" in _kes or "cannot be used to reset" in _kes:
                        logger.debug(f"⏳ fixup_job: {phone} لا يزال جديداً — سيُعاد لاحقاً")
                    else:
                        logger.warning(f"⚠️ fixup_job: فشل طرد {phone}: {_kes[:60]}")
            else:
                kicked_ok = True  # البوت وحيد مسبقاً

            # ─── محاولة تفعيل 2FA إذا لم يكن مفعّلاً ───
            if not (_row["twofa_password"] and _row["auto_2fa_enabled"]):
                try:
                    bot_ref = getattr(context, 'bot', None) if context else None
                    ok_2fa, msg_2fa, _ = await enable_2fa_for_number(phone, latest_sess, sid, bot=bot_ref)
                    if ok_2fa:
                        twofa_ok = True
                        logger.info(f"✅ fixup_job: تم تفعيل 2FA للرقم {phone}")
                    else:
                        logger.debug(f"⚠️ fixup_job: فشل 2FA للرقم {phone}: {msg_2fa}")
                except Exception as _2fa_e:
                    logger.debug(f"⚠️ fixup_job: خطأ 2FA للرقم {phone}: {_2fa_e}")
            else:
                twofa_ok = True  # 2FA مفعّل مسبقاً

            await _cli.disconnect()

            if kicked_ok and twofa_ok:
                to_remove.append(sid)
                asyncio.create_task(_test_and_set_can_send_code(phone, latest_sess, sid))
                logger.info(f"✅ fixup_job: اكتمل إصلاح الرقم {phone} — يُزال من القائمة")

        except Exception as _fe:
            logger.debug(f"⚠️ fixup_job: خطأ عام للرقم {phone}: {_fe}")
        await asyncio.sleep(0.5)

    for sid in to_remove:
        _accounts_needing_fixup.pop(sid, None)


async def handle_zip_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يستقبل ملف ZIP من المالك يحتوي على ملفات .session (Telethon/Pyrogram/MTProto).
    يفكّك الضغط، يُلغي التكرار (حساب واحد = ملف .session واحد)،
    ويستورد كل جلسة تلقائياً مع التحقق وطرد الجلسات الأخرى.
    يُستدعى أيضاً من handle_unsupported_message كـ fallback.
    """
    user = update.effective_user
    if not user or user.id != OWNER_ID:
        return
    doc = update.message.document
    if not doc:
        return
    fname = doc.file_name or "sessions.zip"
    fname_l = fname.lower()
    mime_l  = (doc.mime_type or "").lower()
    if not (fname_l.endswith(".zip") or "zip" in mime_l or
            fname_l.endswith(".gz") or "octet" in mime_l):
        return

    msg = await update.message.reply_text(
        f"📦 استلمت `{fname}` — جاري التنزيل وفك الضغط...",
        parse_mode=ParseMode.MARKDOWN
    )

    raw_zip = None
    _last_err3 = None
    for _att3 in range(3):
        try:
            tg_file = await context.bot.get_file(doc.file_id)
            raw_zip = await tg_file.download_as_bytearray()
            break
        except Exception as e:
            _last_err3 = e
            if _att3 < 2:
                await asyncio.sleep(3)
    if raw_zip is None:
        await msg.edit_text(f"❌ تعذّر تنزيل الملف (3 محاولات):\n`{_last_err3}`", parse_mode=ParseMode.MARKDOWN)
        return

    import zipfile, io
    try:
        zf = zipfile.ZipFile(io.BytesIO(bytes(raw_zip)))
        all_names = [
            n for n in zf.namelist()
            if not n.startswith("__MACOSX") and not n.endswith("/")
        ]
    except Exception as e:
        await msg.edit_text(f"❌ تعذّر فتح ZIP:\n`{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    session_bases = {
        n.rsplit(".", 1)[0].split("/")[-1]
        for n in all_names if n.lower().endswith(".session")
    }
    entries = []
    seen_bases = set()
    for n in all_names:
        short = n.split("/")[-1]
        base  = short.rsplit(".", 1)[0]
        ext   = short.rsplit(".", 1)[-1].lower() if "." in short else ""
        if ext == "session":
            entries.append(n)
            seen_bases.add(base)
        elif ext == "json" and base not in session_bases:
            entries.append(n)

    if not entries:
        await msg.edit_text(
            f"❌ لا توجد ملفات `.session` داخل الـ ZIP.\n"
            f"الملفات الموجودة: {', '.join(n.split('/')[-1] for n in all_names[:10])}",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    total = len(entries)
    remove_2fa_mode = (context.user_data.get("state") == "os_remove_2fa_mode")
    await msg.edit_text(
        f"📦 وجدت *{total}* حساب — جاري التحقق والاستيراد...\n"
        f"_(قد يستغرق {total * 3}–{total * 8} ثانية)_",
        parse_mode=ParseMode.MARKDOWN
    )

    ok_list   = []
    fail_list = []
    rot_ok_list   = []   # (phone, rot_res) للناجحات
    rot_fail_list = []   # (phone, rot_res) للفاشلات

    for idx, entry_name in enumerate(entries):
        short = entry_name.split("/")[-1]
        try:
            file_bytes = zf.read(entry_name)
        except Exception as _re:
            fail_list.append(f"`{short}` — تعذّر القراءة: {str(_re)[:60]}")
            continue

        if (idx + 1) % 5 == 0 or (idx + 1) == total:
            try:
                await msg.edit_text(
                    f"📦 *{idx+1}/{total}* جاري المعالجة والتدوير...\n"
                    f"✅ {len(ok_list)} نجح | ❌ {len(fail_list)} فشل",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

        result = await _import_one_session_bytes(file_bytes, short, context, remove_2fa_mode)
        label  = result["phone"] or short
        if result["ok"]:
            ok_list.append(f"`{label}`")
            if result.get("rot_ok"):
                rot_ok_list.append(label)
            else:
                rot_fail_list.append((label, result.get("rot_res", "")))
        else:
            fail_list.append(f"`{short}` — {result['msg']}")

    zf.close()

    # ── رسالة الاستيراد ───────────────────────────────────────────────
    lines = [f"📦 *نتيجة استيراد ZIP* — *{len(ok_list)} نجح* / {total} إجمالي\n"]
    if ok_list:
        lines.append(f"✅ *نجح ({len(ok_list)}):*")
        lines.extend(f"  • {x}" for x in ok_list[:35])
        if len(ok_list) > 35:
            lines.append(f"  ... و{len(ok_list)-35} آخرين")
    if fail_list:
        lines.append(f"\n❌ *فشل ({len(fail_list)}):*")
        lines.extend(f"  • {x}" for x in fail_list[:15])
        if len(fail_list) > 15:
            lines.append(f"  ... و{len(fail_list)-15} آخرين")

    summary = "\n".join(lines)
    if len(summary) > 4000:
        summary = summary[:3950] + "\n...(مقتطع)"
    await msg.edit_text(summary, parse_mode=ParseMode.MARKDOWN)

    # ── رسالة منفصلة لحالة التدوير ───────────────────────────────────
    rot_lines = [f"🔁 *تقرير التدوير — ZIP ({total} حساب)*\n"]
    if rot_ok_list:
        rot_lines.append(f"✅ *نجح التدوير ({len(rot_ok_list)}):*")
        for _ph in rot_ok_list[:30]:
            rot_lines.append(f"  • `{_ph}` — الجلسة القديمة محذوفة نهائياً")
        if len(rot_ok_list) > 30:
            rot_lines.append(f"  ... و{len(rot_ok_list)-30} آخرين")
    if rot_fail_list:
        rot_lines.append(f"\n❌ *فشل التدوير ({len(rot_fail_list)}):*")
        for _ph, _res in rot_fail_list[:15]:
            rot_lines.append(f"  • `{_ph}` — {_res[:60]}")
        if len(rot_fail_list) > 15:
            rot_lines.append(f"  ... و{len(rot_fail_list)-15} آخرين")
    if not rot_ok_list and not rot_fail_list:
        rot_lines.append("⚠️ لم يُجرَ أي تدوير (كل الاستيرادات فشلت)")

    rot_summary = "\n".join(rot_lines)
    if len(rot_summary) > 4000:
        rot_summary = rot_summary[:3950] + "\n...(مقتطع)"
    await update.effective_message.reply_text(rot_summary, parse_mode=ParseMode.MARKDOWN)

async def handle_unsupported_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شبكة أمان: تُستدعى لأي رسالة لا تحمل نصاً أو وصفاً (صورة/فيديو/ملصق بلا caption،
    جهة اتصال، موقع، ملف...) ولا تطابق أي معالج آخر. بدون هذا المعالج كان البوت يبقى
    صامتاً تماماً بلا أي رد إن أرسل المستخدم قناته بالتوجيه/المشاركة بدل كتابة اليوزرنيم."""
    if not update.message:
        return
    state = context.user_data.get("state", "")
    user_id = update.effective_user.id if update.effective_user else None
    is_own = (user_id == OWNER_ID)

    # بعض تطبيقات تيليجرام ترسل الفيديو كملف بمحرر MIME أو امتداد غير قياسي،
    # لذلك نعيده لمسار الستوريات حتى لا يرفضه معالج الوسائط العام.
    if is_own and state == "os_story_upload" and update.message.document:
        await handle_story_photo(update, context)
        return

    # ── استقبال فيديو رفض الإيميل (للمالك فقط) ──
    _video_states = {"os_await_reject_pass_video", "os_await_reject_verify_video"}
    if is_own and state in _video_states:
        vid = update.message.video or update.message.document
        if vid:
            file_id = vid.file_id
            if state == "os_await_reject_pass_video":
                set_setting("gmail_reject_wrong_pass_video", file_id)
                await update.message.reply_text("✅ تم حفظ فيديو رفض الباسورد الخطأ.", reply_markup=owner_settings_kb())
            elif state == "os_await_reject_verify_video":
                set_setting("gmail_reject_need_verify_video", file_id)
                await update.message.reply_text("✅ تم حفظ فيديو رفض يحتاج تحقق.", reply_markup=owner_settings_kb())
            context.user_data["state"] = "main_menu"
        else:
            await update.message.reply_text("⚠️ أرسل فيديو فقط.", reply_markup=owner_settings_kb())
            context.user_data["state"] = "main_menu"
        return

    if state == "os_remove_2fa_mode" and update.effective_user.id == OWNER_ID:
        doc = update.message.document
        if doc:
            fname = doc.file_name or "file"
            msg = await update.message.reply_text(
                f"⏳ جاري معالجة `{fname}`...", parse_mode=ParseMode.MARKDOWN
            )
            try:
                tg_file  = await context.bot.get_file(doc.file_id)
                raw_bytes = await tg_file.download_as_bytearray()
            except Exception as e:
                await msg.edit_text(f"❌ تعذّر تنزيل الملف: `{e}`", parse_mode=ParseMode.MARKDOWN)
                return

            session_string = None
            try:
                import json as _j2
                data2 = _j2.loads(raw_bytes.decode("utf-8"))
                if isinstance(data2, str):
                    session_string = _maybe_convert_session(data2.strip())
                elif isinstance(data2, dict):
                    if "dc_id" in data2 and "auth_key" in data2:
                        session_string = pyrogram_json_to_telethon(data2)
                    else:
                        raw_s = (data2.get("session_string") or data2.get("session") or "").strip()
                        if raw_s:
                            session_string = _maybe_convert_session(raw_s)
                elif isinstance(data2, list) and data2:
                    first = data2[0]
                    if isinstance(first, str):
                        session_string = _maybe_convert_session(first.strip())
                    elif isinstance(first, dict):
                        if "dc_id" in first and "auth_key" in first:
                            session_string = pyrogram_json_to_telethon(first)
                        else:
                            raw_s = (first.get("session_string") or first.get("session") or "").strip()
                            if raw_s:
                                session_string = _maybe_convert_session(raw_s)
            except Exception:
                pass

            if not session_string:
                try:
                    import tempfile, sqlite3 as _sq3b, struct as _st2, base64 as _b2, socket as _sk2
                    with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as tf2:
                        tf2.write(raw_bytes)
                        tf2_path = tf2.name
                    conn2 = _sq3b.connect(tf2_path)
                    conn2.row_factory = _sq3b.Row
                    cur2 = conn2.cursor()
                    for cols in (
                        "dc_id, server_address, port, auth_key",
                        "dc_id, auth_key",
                    ):
                        try:
                            row2 = cur2.execute(f"SELECT {cols} FROM sessions LIMIT 1").fetchone()
                            if row2 and row2["auth_key"] and len(bytes(row2["auth_key"])) == 256:
                                dc2 = int(row2["dc_id"])
                                ak2 = bytes(row2["auth_key"])
                                try:
                                    ip2   = _sk2.inet_aton(row2["server_address"])
                                    prt2  = int(row2["port"])
                                except Exception:
                                    ip_s2, prt2 = _TG_DC.get(dc2, ("149.154.167.51", 443))
                                    ip2 = _sk2.inet_aton(ip_s2)
                                session_string = "1" + _b2.urlsafe_b64encode(
                                    _st2.pack(">B4sH256s", dc2, ip2, prt2, ak2)
                                ).decode("ascii")
                                break
                        except Exception:
                            pass
                    conn2.close()
                    import os as _os2; _os2.unlink(tf2_path)
                except Exception:
                    pass

            if not session_string:
                try:
                    raw_text = raw_bytes.decode("utf-8", errors="ignore").strip()
                    if raw_text.startswith("1") and len(raw_text) > 100:
                        session_string = raw_text.split()[0]
                except Exception:
                    pass

            if not session_string:
                await msg.edit_text(
                    "❌ لم أتمكن من استخراج جلسة من هذا الملف.\n"
                    "تأكد أنه ملف `.session` أو `.json` يحتوي على بيانات الجلسة.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            ok, result_msg, phone = await _remove_2fa_from_session(session_string)
            icon = "✅" if ok else "❌"
            await msg.edit_text(
                f"{icon} *{phone or fname}*\n{result_msg}",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        await update.message.reply_text(
            "🔓 أنت في وضع إزالة التحقق — أرسل ملف الجلسة أو أرسل /start للخروج."
        )
        return

    if state == "thank_owner_photo" and not is_own and update.message.photo:
        user = update.effective_user
        sender = f"{user.full_name or 'مستخدم'}"
        if user.username:
            sender += f" (@{user.username})"
        caption = f"💌 صورة شكر جديدة\n\n👤 المرسل: {sender}\n🆔 ID: {user.id}"
        try:
            await context.bot.send_photo(
                chat_id=OWNER_ID,
                photo=update.message.photo[-1].file_id,
                caption=caption
            )
            await update.message.reply_text(
                get_setting("thank_owner_success_message")
                or "✅ تم إرسال شكرك إلى المالك، شكراً لك!",
                reply_markup=main_menu_kb(False)
            )
        except Exception:
            logger.exception("فشل إرسال صورة شكر إلى المالك")
            await update.message.reply_text(
                "⚠️ تعذر إرسال الصورة حالياً، حاول مرة أخرى لاحقاً.",
                reply_markup=main_menu_kb(False)
            )
        context.user_data["state"] = "main_menu"
        return

    if state == "await_fund_channel":
        await update.message.reply_text(
            "⚠️ لم يصلني نص. يرجى إرسال *يوزرنيم قناتك كرسالة نصية* مباشرة، مثال: @mychannel\n"
            "(لا ترسله كمشاركة أو توجيه لمنشور — اكتب اليوزرنيم بنفسك)",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if state.startswith("await_") or state.startswith("os_await"):
        await update.message.reply_text("⚠️ لم يصلني نص. يرجى إرسال ردك كرسالة نصية فقط.")
        return
    is_own = (update.effective_user.id == OWNER_ID)

    # ── fallback: ملف ZIP من المالك → استيراد جلسات ──────────────────────
    if is_own and update.message.document:
        doc_fb = update.message.document
        fname_fb = (doc_fb.file_name or "").lower()
        mime_fb  = (doc_fb.mime_type or "").lower()
        # وضع الاستيراد الحصري للإحالة: الملفات تُستورد بـ referral_only=TRUE
        if state == "os_ref_only_import_ready" or context.user_data.get("referral_only_import"):
            context.user_data["referral_only_import"] = True
            if fname_fb.endswith(".zip") or "zip" in mime_fb:
                await handle_zip_file(update, context)
                return
            if fname_fb.endswith(".session"):
                await handle_session_file(update, context)
                return
            if fname_fb.endswith(".json") or "json" in mime_fb:
                await handle_json_file(update, context)
                return
            if fname_fb.endswith(".txt") or "text/plain" in mime_fb:
                await handle_hex_text_file(update, context)
                return
        if fname_fb.endswith(".zip") or "zip" in mime_fb:
            await handle_zip_file(update, context)
            return
        if fname_fb.endswith(".session"):
            await handle_session_file(update, context)
            return
        if fname_fb.endswith(".json") or "json" in mime_fb:
            await handle_json_file(update, context)
            return
        if fname_fb.endswith(".txt") or "text/plain" in mime_fb:
            await handle_hex_text_file(update, context)
            return

    await update.message.reply_text("🏠 القائمة الرئيسية:", reply_markup=main_menu_kb(is_own))
