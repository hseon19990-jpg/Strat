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
async def handle_json_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل ملف JSON من المالك ويستورد الجلسات المحتواة فيه مباشرة."""
    user = update.effective_user
    if user.id != OWNER_ID:
        return
    doc = update.message.document
    if not doc:
        return
    msg = await update.message.reply_text("⏳ جاري قراءة الملف...")
    try:
        file = await context.bot.get_file(doc.file_id)
        raw_bytes = await file.download_as_bytearray()
        import json as _json
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
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        raw_bytes = await tg_file.download_as_bytearray()
    except Exception as e:
        await msg.edit_text(f"❌ تعذّر تنزيل الملف:\n`{e}`", parse_mode=ParseMode.MARKDOWN)
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
    await msg.edit_text(f"⏳ جاري تدوير الجلسة للرقم `{phone}`...", parse_mode=ParseMode.MARKDOWN)
    rot_ok, rot_res = await _rotate_one_session(phone, session_string)
    if rot_ok:
        session_string = rot_res
        with db_conn() as _rc:
            _rc.execute(
                "UPDATE number_stock SET session_string=%s, sessions_reset=TRUE WHERE phone_number=%s",
                (session_string, phone)
            )
    try:
        _ns_row = None
        with db_conn() as _nc:
            _ns_row = _nc.execute("SELECT id FROM number_stock WHERE phone_number=%s", (phone,)).fetchone()
        if _ns_row:
            asyncio.create_task(_run_referral_for_new_number(phone, session_string, _ns_row["id"]))
    except Exception as _re:
        logger.debug(f"_run_referral_for_new_number spawn: {_re}")
    rot_note = " 🔁 تم التدوير — الجلسة القديمة محذوفة نهائياً" if rot_ok else f" ⚠️ التدوير فشل: {rot_res}"
    kick_note  = ""
    twofa_note = ""
    try:
        _kick_cl = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await _kick_cl.connect()
        if await _kick_cl.is_user_authorized():
            try:
                await _kick_cl(ResetAuthorizationsRequest())
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
    await msg.edit_text(
        f"✅ *تم استيراد الجلسة بنجاح!*\n\n"
        f"📱 الرقم: `{phone}`\n"
        f"🔧 الصيغة: {detected_format}\n"
        f"📄 الملف: `{fname}`"
        f"{kick_note}{twofa_note}",
        parse_mode=ParseMode.MARKDOWN
    )
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
        await _cli.connect()
        if not await _cli.is_user_authorized():
            await _cli.disconnect()
            return {"ok": False, "phone": None, "msg": "الجلسة منتهية أو غير صالحة", "session": session_string, "stock_id": None}
        me = await _cli.get_me()
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
    async def _post_import_2fa(ph, ss, sid, bot_ref):
        await asyncio.sleep(3)   # انتظار استقرار الجلسة الجديدة
        try:
            ok_2fa, msg_2fa, pwd_2fa = await enable_2fa_for_number(ph, ss, sid, bot=bot_ref)
            if ok_2fa:
                logger.info(f"✅ post_import_2fa: تم تفعيل 2FA للرقم {ph}")
            else:
                logger.warning(f"⚠️ post_import_2fa: فشل 2FA للرقم {ph}: {msg_2fa}")
                _accounts_needing_fixup[sid] = {"phone": ph, "session": ss, "stock_id": sid, "retries": 0}
        except Exception as _2fa_e:
            logger.warning(f"⚠️ post_import_2fa: خطأ للرقم {ph}: {_2fa_e}")
            _accounts_needing_fixup[sid] = {"phone": ph, "session": ss, "stock_id": sid, "retries": 0}
    try:
        _bot_ref = getattr(context, 'bot', None)
        asyncio.create_task(_post_import_2fa(phone, session_string, stock_id, _bot_ref))
    except Exception as _2fa_spawn_e:
        logger.debug(f"_post_import_2fa spawn: {_2fa_spawn_e}")
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
            with db_conn() as _db:
                _row = _db.execute(
                    "SELECT session_string, is_solo, twofa_password, auto_2fa_enabled, deleted_at "
                    "FROM number_stock WHERE id=%s", (sid,)
                ).fetchone()
            if not _row or _row["deleted_at"]:
                to_remove.append(sid)
                continue
            latest_sess = _row["session_string"] or sess
            info["session"] = latest_sess
            _cli = TelegramClient(StringSession(latest_sess), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await asyncio.wait_for(_cli.connect(), timeout=15)
            if not await asyncio.wait_for(_cli.is_user_authorized(), timeout=8):
                await _cli.disconnect()
                to_remove.append(sid)
                logger.warning(f"⚠️ fixup_job: جلسة {phone} منتهية — إزالة")
                continue
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
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        raw_zip = await tg_file.download_as_bytearray()
    except Exception as e:
        await msg.edit_text(f"❌ تعذّر تنزيل الملف:\n`{e}`", parse_mode=ParseMode.MARKDOWN)
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
async def handle_contact_share(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يُعالج مشاركة رقم الهاتف عبر زر جهة الاتصال.
    يُطبّق قواعد الإحالة حسب المنطقة الجغرافية للرقم:
      - عربي آسيوي  → قبول فوري
      - عربي أفريقي → فحص جودة الحساب
      - غير عربي    → رفض الإحالة مع الإبقاء على وصول البوت
    """
    if not update.message or not update.message.contact:
        return
    user    = update.effective_user
    contact = update.message.contact
    phone   = (contact.phone_number or "").strip()
    await update.message.reply_text(
        "⏳ جاري التحقق من رقمك...",
        reply_markup=ReplyKeyboardRemove()
    )
    if contact.user_id and contact.user_id != user.id:
        await update.message.reply_text(
            "⚠️ يرجى مشاركة رقم هاتفك الخاص فقط.",
            reply_markup=ReplyKeyboardRemove()
        )
        return
    region = classify_phone_region(phone)
    country_name = guess_country(phone)
    if region == "arab_asian":
        logger.info(f"📱 رقم عربي آسيوي {phone} ({country_name}) — قبول مباشر للإحالة")
        await update.message.reply_text(
            f"✅ *رقم مقبول!*\n🌍 {country_name}\n\n"
            "تم قبول إحالتك بنجاح ✔️",
            parse_mode=ParseMode.MARKDOWN
        )
        await finalize_verification(update, context, user, edit=False, skip_referral=False)
    elif region == "arab_african":
        logger.info(f"📱 رقم عربي أفريقي {phone} ({country_name}) — بدء فحص الجودة")
        checking_msg = await update.message.reply_text(
            f"🔍 *جاري فحص الحساب...*\n🌍 {country_name}",
            parse_mode=ParseMode.MARKDOWN
        )
        quality = await check_arab_african_account_quality(user.id, user, context)
        if quality["passed"]:
            logger.info(f"✅ حساب {user.id} اجتاز الفحص: {quality['details']}")
            try:
                await checking_msg.edit_text(
                    f"✅ *تم قبول الإحالة!*\n🌍 {country_name}\n\n"
                    f"نتائج الفحص:\n{quality['details']}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
            if NUMBERS_GROUP_ID:
                try:
                    inviter_row = get_user(
                        (get_user(user.id) or {}).get("invited_by", 0)
                    ) or {}
                    inv_name = md_escape(inviter_row.get("full_name") or "مجهول")
                    inv_un   = (f" (@{md_escape(inviter_row['username'])})"
                                if inviter_row.get("username") else "")
                    await context.bot.send_message(
                        NUMBERS_GROUP_ID,
                        f"📱 *إحالة عربية أفريقية مقبولة*\n\n"
                        f"👤 المُحيل: {inv_name}{inv_un}\n"
                        f"🆕 المدعو: {md_escape(user.full_name or str(user.id))}"
                        f"{(' (@' + md_escape(user.username) + ')') if user.username else ''}\n"
                        f"🌍 الدولة: {country_name}\n"
                        f"🔍 الفحص: {quality['details']}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass
            await finalize_verification(update, context, user, edit=False, skip_referral=False)
        else:
            logger.info(f"❌ حساب {user.id} لم يجتز الفحص: {quality['details']}")
            try:
                await checking_msg.edit_text(
                    f"⚠️ *لم تُحتسب الإحالة*\n🌍 {country_name}\n\n"
                    f"نتائج الفحص:\n{quality['details']}\n\n"
                    "يمكنك استخدام البوت بشكل طبيعي.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
            if NUMBERS_GROUP_ID:
                try:
                    inviter_row = get_user(
                        (get_user(user.id) or {}).get("invited_by", 0)
                    ) or {}
                    inv_name = md_escape(inviter_row.get("full_name") or "مجهول")
                    inv_un   = (f" (@{md_escape(inviter_row['username'])})"
                                if inviter_row.get("username") else "")
                    await context.bot.send_message(
                        NUMBERS_GROUP_ID,
                        f"📱 *إحالة عربية أفريقية مرفوضة (جودة منخفضة)*\n\n"
                        f"👤 المُحيل: {inv_name}{inv_un}\n"
                        f"🆕 المدعو: {md_escape(user.full_name or str(user.id))}"
                        f"{(' (@' + md_escape(user.username) + ')') if user.username else ''}\n"
                        f"🌍 الدولة: {country_name}\n"
                        f"🔍 الفحص: {quality['details']}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass
            await finalize_verification(update, context, user, edit=False, skip_referral=True)
    else:
        logger.info(f"📱 رقم غير عربي {phone} ({country_name}) — رفض الإحالة")
        await update.message.reply_text(
            f"⚠️ *الإحالة غير مقبولة*\n🌍 {country_name}\n\n"
            "سبب الرفض: الحساب وهمي (رقم من دولة غير عربية)\n\n"
            "يمكنك استخدام البوت بشكل طبيعي.",
            parse_mode=ParseMode.MARKDOWN
        )
        if NUMBERS_GROUP_ID:
            try:
                inviter_row = get_user(
                    (get_user(user.id) or {}).get("invited_by", 0)
                ) or {}
                inv_name = md_escape(inviter_row.get("full_name") or "مجهول")
                inv_un   = (f" (@{md_escape(inviter_row['username'])})"
                            if inviter_row.get("username") else "")
                await context.bot.send_message(
                    NUMBERS_GROUP_ID,
                    f"📱 *إحالة مرفوضة — دولة غير عربية*\n\n"
                    f"👤 المُحيل: {inv_name}{inv_un}\n"
                    f"🆕 المدعو: {md_escape(user.full_name or str(user.id))}"
                    f"{(' (@' + md_escape(user.username) + ')') if user.username else ''}\n"
                    f"🌍 الدولة: {country_name}\n"
                    f"📱 الرقم: +{(contact.phone_number or '').lstrip('+')}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
        await finalize_verification(update, context, user, edit=False, skip_referral=True)
async def handle_unsupported_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شبكة أمان: تُستدعى لأي رسالة لا تحمل نصاً أو وصفاً (صورة/فيديو/ملصق بلا caption،
    جهة اتصال، موقع، ملف...) ولا تطابق أي معالج آخر. بدون هذا المعالج كان البوت يبقى
    صامتاً تماماً بلا أي رد إن أرسل المستخدم قناته بالتوجيه/المشاركة بدل كتابة اليوزرنيم."""
    if not update.message:
        return
    state = context.user_data.get("state", "")
    user_id = update.effective_user.id if update.effective_user else None
    is_own = (user_id == OWNER_ID)
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
    if is_own and update.message.document:
        doc_fb = update.message.document
        fname_fb = (doc_fb.file_name or "").lower()
        mime_fb  = (doc_fb.mime_type or "").lower()
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
        if fname_fb.endswith(".zip") or "zip" in mime_fb:
            await handle_zip_file(update, context)
            return
        if fname_fb.endswith(".session"):
            await handle_session_file(update, context)
            return
        if fname_fb.endswith(".json") or "json" in mime_fb:
            await handle_json_file(update, context)
            return
    await update.message.reply_text("🏠 القائمة الرئيسية:", reply_markup=main_menu_kb(is_own))
async def _save_service(update, context, price: float):
    """حفظ الخدمة الجديدة بعد تحديد جميع القيم"""
    cat      = context.user_data.get("new_svc_cat", "followers")
    api_id   = context.user_data.get("new_svc_api_id")
    panel    = context.user_data.get("new_svc_panel", 1)
    platform = context.user_data.get("new_svc_platform", "tg")
    name     = context.user_data.get("new_svc_name")
    mn       = context.user_data.get("new_svc_min", 0)
    mx       = context.user_data.get("new_svc_max", 0)
    desc     = context.user_data.get("new_svc_desc", "")
    with db_conn() as c:
        c.execute(
            "INSERT INTO services (category,api_service_id,panel,platform,name_ar,description,min_qty,max_qty,price_per_point) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (cat, api_id, panel, platform, name, desc, mn, mx, price)
        )
    site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
    await update.message.reply_text(
        f"✅ تمت إضافة الخدمة *'{name}'* بنجاح!\n\n"
        f"🌐 الموقع: {site_name}\n"
        f"📉 الحد الأدنى: {mn}\n"
        f"📈 الحد الأعلى: {mx}\n"
        f"💰 السعر: {fmt_price(price)} نقطة/1000 وحدة",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=owner_settings_kb()
    )
    context.user_data["state"] = "main_menu"
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query
    data   = q.data
    user   = q.from_user
    is_own        = (user.id == OWNER_ID)
    is_supervisor_cb = (not is_own) and is_supervisor(user.id)
    if not is_own and is_user_banned(user.id):
        await q.answer("🚫 تم حظرك من استخدام هذا البوت.", show_alert=True)
        return
    if is_maintenance_on() and not is_own:
        await q.answer()
        await q.edit_message_text(MAINTENANCE_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return
    _GATE_EXEMPT = {"check_mandatory_join", "noop", "skip_mandatory_gate"}
    _owner_admin_action = is_own and data.startswith("os:")
    _sv_admin_action    = is_supervisor_cb and data.startswith("sv:")
    _gmail_verification_done = (
        data == "gmail_verify_done" or data.startswith("gmail_verify_done:")
    )
    if data not in _GATE_EXEMPT and not _gmail_verification_done and not data.startswith("join_verify:") and not data.startswith("thank_owner") and not _owner_admin_action and not _sv_admin_action:
        try:
            _db_user = get_user(user.id)
            if _db_user and _db_user.get("verified", 0):
                _unjoined = await get_unjoined_mandatory_channels(context, user.id)
                if _unjoined:
                    _remaining = max(0, len(_unjoined) - MANDATORY_PAGE_SIZE)
                    _more_note = (
                        f"\n\n➕ يوجد *{_remaining}* قناة إضافية ستظهر تلقائياً بعد إكمال هذه المجموعة."
                        if _remaining > 0 else ""
                    )
                    await q.edit_message_text(
                        f"📢 *يجب عليك الاشتراك بالقنوات الجديدة أولاً للمتابعة:*{_more_note}",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=mandatory_join_kb(_unjoined, is_owner=is_own)
                    )
                    context.user_data["state"] = "await_mandatory_join"
                    return
        except Exception as _gate_err:
            logger.warning(f"⚠️ خطأ في فحص القنوات الإجبارية (callback) للمستخدم {user.id}: {_gate_err}")
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
        parts  = data.split(":", 2)   # ["owner_fwd", "yes/no", "key"]
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
            "• أدنى قيمة: `0.00001` (بلا تأخير تقريباً)\n"
            "• أمثلة: `0.5` أو `5` أو `30` أو `120`\n\n"
            "_(البوت كان يستخدم 30-60 ثانية افتراضياً)_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 إلغاء", callback_data="os:bot_ref_numbers")
            ]]))
        return
    if data == "os:fr_order_delay" and is_own:
        context.user_data["state"] = "os_await_fr_order_delay"
        _cur_od = get_setting("forced_ref_order_delay") or "60"
        await q.edit_message_text(
            f"⏱️ *ضبط سرعة التفعيل بين الحسابات*\n\n"
            f"القيمة الحالية: *{_cur_od} ثانية*\n\n"
            "أرسل الفرق الزمني بالثوانٍ بين كل حساب وحساب:\n"
            "• `1` = ثانية واحدة بين كل حساب\n"
            "• `5` = 5 ثوانٍ\n"
            "• `0.5` = نصف ثانية\n"
            "• `0.00001` = بلا تأخير تقريباً\n\n"
            "⚠️ *ملاحظة:* هذا الإعداد للمالك فقط.\n"
            "غير المالك يستخدم تأخيراً ثابتاً 2-8 دقائق.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 إلغاء", callback_data="main_menu")
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
        await q.answer()  # إجابة فورية لمنع ظهور "جاري التحميل"
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
        await q.answer()  # إجابة فورية لتفادي دوران محدد التحميل
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
                f"💰 رصيده الحالي: *{_pts:,} نقطة*\n"
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
        else:  # open — لا يُظهر وقتاً للأعضاء
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
                " AND pe.prize_type IN ('telegram_number', 'telegram_number_code')"
                " ORDER BY pe.created_at DESC",
                (user.id,)
            ).fetchall()
        if not _mn_rows:
            await q.edit_message_text(
                "\U0001f4f1 *\u0627\u0631\u0642\u0627\u0645\u064a*\n\n"
                "\u0644\u0645 \u062a\u0642\u0645 \u0628\u0634\u0631\u0627\u0621 \u0623\u064a \u0631\u0642\u0645 \u062d\u062a\u0649 \u0627\u0644\u0622\u0646.\n\n"
                "\u0627\u0630\u0647\u0628 \u0625\u0644\u0649 *\u0627\u0633\u062a\u0628\u062f\u0627\u0644 \u0646\u0642\u0627\u0637 \u0628\u062c\u0648\u0627\u0626\u0632* \u0644\u0634\u0631\u0627\u0621 \u0631\u0642\u0645.",
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
                    "\U0001f6ab " + _mn_clean + " (\u0645\u0637\u0631\u0648\u062f)",
                    callback_data="my_numbers:kicked:" + _mn_phone
                )])
            else:
                _mn_kb.append([InlineKeyboardButton(
                    "\U0001f4f1 " + _mn_clean,
                    callback_data="noop"
                )])
                _mn_kb.append([
                    InlineKeyboardButton("\U0001f510 2FA",    callback_data="buyer:show_twofa:"  + _mn_phone),
                    InlineKeyboardButton("\U0001f511 \u0643\u0648\u062f", callback_data="buyer:request_code:" + _mn_phone),
                    InlineKeyboardButton("\U0001f4f7 \u0628\u0627\u0631\u0643\u0648\u062f",  callback_data="buyer:barcode:"       + _mn_phone),
                ])
        _mn_kb.append([InlineKeyboardButton("\U0001f519 \u0631\u062c\u0648\u0639", callback_data="main_menu")])
        _mn_total  = len(_mn_rows)
        _mn_active = _mn_total - _mn_kicked_count
        _mn_title  = "\U0001f4f1 *\u0627\u0631\u0642\u0627\u0645\u064a*\n\n"
        _mn_stats  = ("\U0001f4ca \u0625\u062c\u0645\u0627\u0644\u064a: " + str(_mn_total)
                      + " | \u2705 " + str(_mn_active)
                      + " | \U0001f6ab " + str(_mn_kicked_count) + "\n\n")
        _mn_hint   = "\u0627\u062e\u062a\u0631 \u0631\u0642\u0645\u064b\u0627 \u0644\u0639\u0631\u0636 \u062e\u064a\u0627\u0631\u0627\u062a\u0647:"
        await q.edit_message_text(
            _mn_title + _mn_stats + _mn_hint,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(_mn_kb)
        )
        return
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
            f"{_terms}"
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
    if data == "os:list_services" and is_own:
        text_, rows = _render_service_list()
        if rows is None:
            await q.edit_message_text(text_, reply_markup=owner_settings_kb())
            return
        await q.edit_message_text(text_, parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(rows))
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
                    "WHERE prize_value=%s AND prize_type IN ('telegram_number','telegram_number_code') "
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
    if data.startswith("os:leave_account:") and is_own:
        _phone_leave = data[len("os:leave_account:"):]
        await q.answer()
        try:
            with db_conn() as _cl:
                _cl.execute("DELETE FROM number_stock WHERE phone_number=%s", (_phone_leave,))
            await q.edit_message_text(
                f"🚪 *تم حذف الحساب من المخزون*\n\n"
                f"📱 الرقم: `{_phone_leave}`\n"
                f"البوت أنهى كل علاقته بهذا الحساب.",
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"🚪 os:leave_account: تم حذف الرقم {_phone_leave} من المخزون.")
        except Exception as _el:
            await q.edit_message_text(f"❌ فشل حذف الحساب: {_el}", parse_mode=ParseMode.MARKDOWN)
        return
    if data == "os:rotate_sessions" and is_own:
        if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
            await q.answer("❌ API_ID / API_HASH غير مضبوطة.", show_alert=True)
            return
        with db_conn() as _c:
            _rows = _c.execute(
                "SELECT id, phone_number, session_string FROM number_stock "
                "WHERE ever_sold IS NOT TRUE AND session_string IS NOT NULL AND deleted_at IS NULL"
            ).fetchall()
        total_rot = len(_rows)
        if total_rot == 0:
            await q.answer("ℹ️ لا توجد أرقام للتدوير.", show_alert=True)
            return
        await q.edit_message_text(
            f"🔁 *بدأ تدوير الجلسات...*\n📦 إجمالي: *{total_rot}* رقم\n⏱️ الرجاء الانتظار...",
            parse_mode=ParseMode.MARKDOWN
        )
        ok_rot, fail_rot = [], []
        for idx_r, rec_r in enumerate(_rows):
            rec_r = dict(rec_r)
            ph_r = rec_r["phone_number"]
            suc_r, res_r = await _rotate_one_session(ph_r, rec_r["session_string"])
            if suc_r:
                with db_conn() as _cx:
                    _cx.execute(
                        "UPDATE number_stock SET session_string=%s, sessions_reset=TRUE WHERE id=%s",
                        (res_r, rec_r["id"])
                    )
                ok_rot.append(f"`{ph_r}`")
            else:
                fail_rot.append(f"`{ph_r}` — {res_r}")
            if (idx_r + 1) % 3 == 0 or (idx_r + 1) == total_rot:
                try:
                    await context.bot.edit_message_text(
                        chat_id=q.message.chat_id,
                        message_id=q.message.message_id,
                        text=(
                            f"🔁 *تدوير الجلسات... {idx_r+1}/{total_rot}*\n"
                            f"✅ نجح: *{len(ok_rot)}*  |  ❌ فشل: *{len(fail_rot)}*"
                        ),
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass
        _lines = [
            f"✅ *اكتمل تدوير الجلسات*\n",
            f"📦 إجمالي: *{total_rot}*",
            f"✅ نجح: *{len(ok_rot)}*  |  ❌ فشل: *{len(fail_rot)}*",
        ]
        if ok_rot:
            _lines.append("\n*✅ نجح:*")
            _lines.extend(f"  • {p}" for p in ok_rot[:30])
        if fail_rot:
            _lines.append("\n*❌ فشل:*")
            _lines.extend(f"  • {f}" for f in fail_rot[:20])
        _lines.append("")
        await context.bot.edit_message_text(
            chat_id=q.message.chat_id,
            message_id=q.message.message_id,
            text="\n".join(_lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")
            ]])
        )
        return
    if data == "os:remove_2fa_mode" and is_own:
        context.user_data["state"] = "os_remove_2fa_mode"
        await q.edit_message_text(
            "🔓 *وضع إزالة التحقق الثنائي*\n\n"
            "أرسل ملفات الجلسة (`.session` أو `.json`) واحداً تلو الآخر.\n"
            "البوت سيزيل التحقق الثنائي (2FA) من كل حساب تُرسله.\n\n"
            "💡 يعمل مع: Telethon SQLite، Pyrogram JSON، StringSession JSON\n\n"
            "أرسل /start أو اضغط رجوع للخروج من هذا الوضع.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")
            ]])
        )
        return
    if data == "os:verify_muhammed_accounts" and is_own:
        with db_conn() as _c:
            _rows = _c.execute(
                "SELECT id, phone_number, session_string, twofa_password "
                "FROM number_stock WHERE session_string IS NOT NULL AND deleted_at IS NULL"
            ).fetchall()
        if not _rows:
            await q.answer("✅ لا توجد حسابات في المخزون.", show_alert=True)
            return
        await q.edit_message_text(
            f"✅ *التحقق من كلمة المرور '{OWNER_FIXED_2FA_PASSWORD}' على {len(_rows)} حساب...*\n\n"
            "سيصلك تقرير عند الانتهاء.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")
            ]])
        )
        async def _verify_muhammed_bg():
            verified_ok, verified_saved, wrong_pw, failed = [], [], [], []
            for rec in _rows:
                ph  = rec["phone_number"]
                ss  = rec["session_string"]
                sid = rec["id"]
                saved = rec["twofa_password"] or ""
                cli_v = None
                try:
                    cli_v = TelegramClient(StringSession(ss), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                    await asyncio.wait_for(cli_v.connect(), timeout=15)
                    if not await asyncio.wait_for(cli_v.is_user_authorized(), timeout=8):
                        failed.append(f"`{ph}`: جلسة منتهية")
                        continue
                    pwd_state = await asyncio.wait_for(cli_v(GetPasswordRequest()), timeout=10)
                    if not pwd_state.has_password:
                        _expected_2fa_change[ph] = time.time()
                        await asyncio.wait_for(
                            cli_v.edit_2fa(new_password=OWNER_FIXED_2FA_PASSWORD, hint="Auto"),
                            timeout=20
                        )
                        with db_conn() as _uu:
                            _uu.execute(
                                "UPDATE number_stock SET twofa_password=%s, auto_2fa_enabled=TRUE WHERE id=%s",
                                (OWNER_FIXED_2FA_PASSWORD, sid)
                            )
                        verified_saved.append(ph)
                    else:
                        ok_v = await asyncio.wait_for(
                            verify_current_2fa_password(cli_v, OWNER_FIXED_2FA_PASSWORD, phone=ph),
                            timeout=12
                        )
                        if ok_v is True:
                            with db_conn() as _uu2:
                                _uu2.execute(
                                    "UPDATE number_stock SET twofa_password=%s, auto_2fa_enabled=TRUE WHERE id=%s",
                                    (OWNER_FIXED_2FA_PASSWORD, sid)
                                )
                            verified_ok.append(ph)
                        else:
                            wrong_pw.append(ph)
                            _accounts_needing_fixup[sid] = {"phone": ph, "session": ss, "stock_id": sid, "retries": 0}
                except Exception as _ve:
                    failed.append(f"`{ph}`: {str(_ve)[:60]}")
                finally:
                    try:
                        if cli_v: await cli_v.disconnect()
                    except Exception:
                        pass
                await asyncio.sleep(0.8)
            lines = [f"✅ *تقرير التحقق من كلمة المرور '{OWNER_FIXED_2FA_PASSWORD}':*\n"]
            lines.append(f"✅ تحققت مسبقاً: *{len(verified_ok)}* | 🆕 فُعِّلت الآن: *{len(verified_saved)}* | ❌ كلمة مختلفة: *{len(wrong_pw)}* | ⚠️ أخطاء: *{len(failed)}*")
            if wrong_pw:
                lines.append("\n*❌ كلمة مرور مختلفة (أُضيفت لقائمة الإصلاح):*")
                lines.extend(f"  • `{p}`" for p in wrong_pw[:20])
            if failed:
                lines.append("\n*⚠️ أخطاء:*")
                lines.extend(f"  • {x}" for x in failed[:15])
            try:
                await context.bot.send_message(OWNER_ID, "\n".join(lines), parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass
        asyncio.create_task(_verify_muhammed_bg())
        return
    if data == "os:kick_all_devices" and is_own:
        with db_conn() as _c:
            _rows_k = _c.execute(
                "SELECT id, phone_number, session_string "
                "FROM number_stock WHERE session_string IS NOT NULL AND deleted_at IS NULL"
                " AND (is_solo IS NOT TRUE OR sessions_reset IS NOT TRUE)"
            ).fetchall()
        if not _rows_k:
            await q.answer("✅ جميع الحسابات مطرودة بالفعل (is_solo=TRUE).", show_alert=True)
            return
        await q.edit_message_text(
            f"💥 *جاري طرد جميع الأجهزة على {len(_rows_k)} حساب...*\n\n"
            "سيصلك تقرير عند الانتهاء.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")
            ]])
        )
        async def _kick_all_bg():
            kicked_ok, still_multi, failed_kick = [], [], []
            for rec in _rows_k:
                ph  = rec["phone_number"]
                ss  = rec["session_string"]
                sid = rec["id"]
                cli_k = None
                try:
                    cli_k = TelegramClient(StringSession(ss), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                    await asyncio.wait_for(cli_k.connect(), timeout=15)
                    if not await asyncio.wait_for(cli_k.is_user_authorized(), timeout=8):
                        failed_kick.append(f"`{ph}`: جلسة منتهية")
                        continue
                    try:
                        await asyncio.wait_for(cli_k(ResetAuthorizationsRequest()), timeout=15)
                        dev_cnt_k = await asyncio.wait_for(get_device_count(cli_k), timeout=8)
                        is_solo_k = (dev_cnt_k == 1)
                        with db_conn() as _du:
                            _du.execute(
                                "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s WHERE id=%s",
                                (is_solo_k, sid)
                            )
                        if is_solo_k:
                            kicked_ok.append(ph)
                            asyncio.create_task(_test_and_set_can_send_code(ph, ss, sid))
                        else:
                            still_multi.append(f"`{ph}` ({dev_cnt_k} أجهزة)")
                            _accounts_needing_fixup[sid] = {"phone": ph, "session": ss, "stock_id": sid, "retries": 0}
                    except Exception as _ke:
                        _kes = str(_ke)
                        if "too new" in _kes or "cannot be used to reset" in _kes:
                            _accounts_needing_fixup[sid] = {"phone": ph, "session": ss, "stock_id": sid, "retries": 0}
                            failed_kick.append(f"`{ph}`: جديد — سيُعاد تلقائياً")
                        else:
                            failed_kick.append(f"`{ph}`: {_kes[:50]}")
                except Exception as _ge:
                    failed_kick.append(f"`{ph}`: {str(_ge)[:60]}")
                finally:
                    try:
                        if cli_k: await cli_k.disconnect()
                    except Exception:
                        pass
                await asyncio.sleep(0.5)
            lines = [f"💥 *تقرير طرد الأجهزة:*\n"]
            lines.append(f"✅ طُرد بنجاح (بوت وحيد): *{len(kicked_ok)}* | ⚠️ ما زال متعدد: *{len(still_multi)}* | ❌ فشل: *{len(failed_kick)}*")
            if still_multi:
                lines.append("\n*⚠️ ما زالت هناك أجهزة أخرى (تُعاد تلقائياً):*")
                lines.extend(f"  • {x}" for x in still_multi[:20])
            if failed_kick:
                lines.append("\n*❌ فشل:*")
                lines.extend(f"  • {x}" for x in failed_kick[:15])
            try:
                await context.bot.send_message(OWNER_ID, "\n".join(lines), parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass
        asyncio.create_task(_kick_all_bg())
        return
    if data == "os:set_all_2fa_muhammed" and is_own:
        target_pw = OWNER_FIXED_2FA_PASSWORD or "محمد"
        if not target_pw:
            await q.answer("⚠️ متغير TWOFA_PASSWORD غير مضبوط في البيئة.", show_alert=True)
            return
        with db_conn() as c:
            rows = c.execute(
                "SELECT id, phone_number, session_string, twofa_password "
                "FROM number_stock WHERE session_string IS NOT NULL AND deleted_at IS NULL"
            ).fetchall()
        if not rows:
            await q.answer("✅ لا توجد حسابات بجلسة في المخزون.", show_alert=True)
            return
        await q.edit_message_text(
            f"⏳ *جاري تعيين كلمة المرور '{target_pw}' على {len(rows)} حساب...*\n\n"
            "سيصلك تقرير عند الانتهاء.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")
            ]])
        )
        async def _set_all_2fa_bg():
            done, skipped, failed = [], [], []
            for rec in rows:
                phone   = rec["phone_number"]
                sess    = rec["session_string"]
                old_pw  = rec["twofa_password"] or ""
                stock_id = rec["id"]
                if old_pw == target_pw:
                    skipped.append(phone)
                    continue
                cli = None
                try:
                    cli = TelegramClient(StringSession(sess), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                    await asyncio.wait_for(cli.connect(), timeout=20)
                    if not await asyncio.wait_for(cli.is_user_authorized(), timeout=10):
                        failed.append(f"{phone}: جلسة منتهية")
                        continue
                    pwd_state = await cli(GetPasswordRequest())
                    _expected_2fa_change[phone] = time.time()
                    if not pwd_state.has_password:
                        await cli.edit_2fa(new_password=target_pw, hint="Auto")
                    else:
                        candidates = []
                        if old_pw and old_pw != target_pw:
                            candidates.append(old_pw)
                        if target_pw not in candidates:
                            candidates.append(target_pw)
                        changed = False
                        for cand_pw in candidates:
                            try:
                                await cli.edit_2fa(current_password=cand_pw, new_password=target_pw, hint="Auto")
                                changed = True
                                break
                            except Exception as _pe:
                                if "PASSWORD_HASH_INVALID" in str(_pe).upper() or "SRP_ID_INVALID" in str(_pe).upper():
                                    continue
                                raise
                        if not changed:
                            failed.append(f"{phone}: كلمة المرور غير معروفة")
                            continue
                    with db_conn() as _uc:
                        _uc.execute(
                            "UPDATE number_stock SET twofa_password=%s, auto_2fa_enabled=TRUE WHERE id=%s",
                            (target_pw, stock_id)
                        )
                    done.append(phone)
                except Exception as _e:
                    failed.append(f"{phone}: {_e}")
                finally:
                    try:
                        if cli: await cli.disconnect()
                    except Exception:
                        pass
                await asyncio.sleep(1)  # لتجنب flood
            lines = [f"🔑 *نتيجة تعيين كلمة المرور '{target_pw}':*\n"]
            lines.append(f"✅ تم ({len(done)}) / ⏭ مخطّى ({len(skipped)}) / ❌ فشل ({len(failed)})")
            if done:
                lines.append("\n*✅ نجح:*")
                lines.extend(f"  • `{p}`" for p in done[:30])
                if len(done) > 30: lines.append(f"  ... و{len(done)-30} آخرين")
            if failed:
                lines.append("\n*❌ فشل:*")
                lines.extend(f"  • {x}" for x in failed[:20])
            try:
                await context.bot.send_message(
                    OWNER_ID, "\n".join(lines), parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
        asyncio.create_task(_set_all_2fa_bg())
        return
    if data == "os:release_all_numbers" and is_own:
        with db_conn() as c:
            rows = c.execute(
                "SELECT phone_number FROM number_stock WHERE assigned_to IS NOT NULL AND deleted_at IS NULL"
            ).fetchall()
            count = len(rows)
            if count == 0:
                await q.answer("✅ لا توجد أرقام مباعة حالياً.", show_alert=True)
                return
            c.execute(
                "UPDATE number_stock SET assigned_to=NULL, assigned_at=NULL, "
                "force_listed=FALSE, ever_sold=FALSE "
                "WHERE assigned_to IS NOT NULL AND deleted_at IS NULL"
            )
        await q.edit_message_text(
            f"✅ *تم إرجاع {count} رقم للبيع بنجاح!*\n\n"
            f"جميع الأرقام المحددة أصبحت متاحة للشراء من جديد.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")],
            ])
        )
        return
    if data == "os:scan_all_numbers" and is_own:
        await q.edit_message_text(
            "🔍 *بدأ فحص جميع الحسابات...*\n\n"
            "سيصلك تقرير عند الانتهاء (عادةً أقل من دقيقة).",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_numbers")]])
        )
        async def _scan_one(rec) -> dict:
            """يفحص رقماً واحداً ويُرجع نتيجة مختصرة. محاط بـ timeout=25ث."""
            phone_r  = rec["phone_number"]
            sess_r   = rec["session_string"]
            saved_pw = rec["twofa_password"] or ""
            result   = {"phone": phone_r, "id": rec["id"], "status": "ok", "note": "", "devs": 1}
            cli = None
            try:
                cli = TelegramClient(StringSession(sess_r), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                await asyncio.wait_for(cli.connect(), timeout=15)
                if not await asyncio.wait_for(cli.is_user_authorized(), timeout=10):
                    result["status"] = "kicked"
                    result["note"] = "جلسة منتهية/مطرودة — حُذف تلقائياً"
                    with db_conn() as _c:
                        _es = _c.execute(
                            "SELECT ever_sold FROM number_stock WHERE id=%s", (rec["id"],)
                        ).fetchone()
                        if _es and not _es["ever_sold"]:
                            _c.execute("DELETE FROM number_stock WHERE id=%s", (rec["id"],))
                            logger.info(
                                f"🗑️ حذف تلقائي (فحص): الرقم {rec['phone_number']} — جلسة منتهية."
                            )
                        else:
                            _c.execute("UPDATE number_stock SET last_authorized=FALSE WHERE id=%s", (rec["id"],))
                    return result
                is_frz, frz_status, _ = await asyncio.wait_for(
                    check_account_frozen(cli, rec["id"]), timeout=10
                )
                if is_frz:
                    result["status"] = "frozen"
                    result["note"] = frz_status
                    with db_conn() as _fc:
                        _fe = _fc.execute(
                            "SELECT ever_sold FROM number_stock WHERE id=%s", (rec["id"],)
                        ).fetchone()
                        if _fe and not _fe["ever_sold"]:
                            _fc.execute("DELETE FROM number_stock WHERE id=%s", (rec["id"],))
                            result["note"] += " — حُذف تلقائياً"
                            logger.info(f"🗑️ حذف تلقائي (مجمّد): الرقم {rec['phone_number']}")
                    return result
                try:
                    _me_scan = await asyncio.wait_for(cli.get_me(), timeout=8)
                    if _me_scan:
                        with db_conn() as _uc:
                            _uc.execute(
                                "UPDATE number_stock SET can_send_code=TRUE WHERE id=%s AND ever_sold IS NOT TRUE",
                                (rec["id"],)
                            )
                except Exception:
                    pass
                devs = await asyncio.wait_for(get_device_count(cli), timeout=10)
                result["devs"] = devs
                pwd_state = await asyncio.wait_for(cli(GetPasswordRequest()), timeout=10)
                if pwd_state.has_password:
                    if saved_pw:
                        result["status"] = "ok"   # لدينا كلمة مرور محفوظة → بخير
                    else:
                        try:
                            verified = await asyncio.wait_for(
                                verify_current_2fa_password(cli, OWNER_FIXED_2FA_PASSWORD, phone=phone_r),
                                timeout=12
                            )
                        except asyncio.TimeoutError:
                            verified = None
                        if verified is True:
                            with db_conn() as _c:
                                _c.execute("UPDATE number_stock SET twofa_password=%s WHERE id=%s",
                                           (OWNER_FIXED_2FA_PASSWORD, rec["id"]))
                            result["status"] = "ok"
                        else:
                            result["status"] = "no_2fa"
                            result["note"] = "2FA مفعّل لكن كلمة المرور غير معروفة"
                else:
                    result["status"] = "no_2fa"
                    result["note"] = "2FA غير مفعّل"
            except asyncio.TimeoutError:
                result["status"] = "timeout"
                result["note"] = "انتهت مهلة الاتصال (25ث) — حُذف تلقائياً"
                with db_conn() as _c:
                    _es = _c.execute(
                        "SELECT ever_sold FROM number_stock WHERE id=%s", (rec["id"],)
                    ).fetchone()
                    if _es and not _es["ever_sold"]:
                        _c.execute("DELETE FROM number_stock WHERE id=%s", (rec["id"],))
                        logger.info(f"🗑️ حذف تلقائي (timeout): الرقم {rec['phone_number']}")
            except Exception as e:
                err_txt = str(e)
                unrecoverable = any(k in err_txt for k in (
                    "AuthKeyUnregistered", "SessionRevoked", "AuthKeyDuplicated",
                    "UserDeactivated", "AccountBanned", "PhoneNumberBanned",
                    "AUTH_KEY_UNREGISTERED", "SESSION_REVOKED",
                ))
                result["status"] = "error"
                result["note"] = err_txt[:100] + (" — حُذف تلقائياً" if unrecoverable else "")
                if unrecoverable:
                    with db_conn() as _c:
                        _es = _c.execute(
                            "SELECT ever_sold FROM number_stock WHERE id=%s", (rec["id"],)
                        ).fetchone()
                        if _es and not _es["ever_sold"]:
                            _c.execute("DELETE FROM number_stock WHERE id=%s", (rec["id"],))
                            logger.info(f"🗑️ حذف تلقائي (error/{err_txt[:40]}): الرقم {rec['phone_number']}")
            finally:
                try:
                    if cli:
                        await cli.disconnect()
                except Exception:
                    pass
            return result
        async def _run_full_scan():
            if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
                await context.bot.send_message(OWNER_ID, "❌ TELEGRAM_API_ID/HASH غير مضبوط — تعذّر الفحص.")
                return
            with db_conn() as _c:
                rows = _c.execute(
                    "SELECT id, phone_number, session_string, twofa_password "
                    "FROM number_stock WHERE session_string IS NOT NULL AND deleted_at IS NULL"
                ).fetchall()
            if not rows:
                await context.bot.send_message(OWNER_ID, "📭 لا توجد أرقام مضافة بجلسة للفحص.")
                return
            total = len(rows)
            ok_cnt = frz_cnt = kick_cnt = no_2fa_cnt = timeout_cnt = err_cnt = multi_dev_cnt = 0
            deleted_cnt = 0
            problem_lines = []
            needs_2fa_fix = []   # أرقام تحتاج تفعيل/تصحيح 2FA
            for rec in rows:
                res = await asyncio.wait_for(_scan_one(dict(rec)), timeout=35)
                st = res["status"]
                if st == "ok":
                    ok_cnt += 1
                    if res["devs"] > 1:
                        multi_dev_cnt += 1
                        problem_lines.append(f"📲 `{res['phone']}` — {res['devs']} أجهزة (يُفضَّل جهاز واحد)")
                elif st == "frozen":
                    frz_cnt += 1
                    was_deleted = "حُذف تلقائياً" in res["note"]
                    if was_deleted:
                        deleted_cnt += 1
                    problem_lines.append(f"🗑️ `{res['phone']}` — {res['note']}")
                elif st == "kicked":
                    kick_cnt += 1
                    deleted_cnt += 1
                    problem_lines.append(f"🗑️ `{res['phone']}` — جلسة منتهية (حُذف)")
                elif st == "no_2fa":
                    no_2fa_cnt += 1
                    problem_lines.append(f"🔑 `{res['phone']}` — {res['note']}")
                    needs_2fa_fix.append(res)
                elif st == "timeout":
                    timeout_cnt += 1
                    deleted_cnt += 1
                    problem_lines.append(f"🗑️ `{res['phone']}` — لا يستجيب (حُذف)")
                else:
                    err_cnt += 1
                    was_deleted = "حُذف تلقائياً" in res["note"]
                    if was_deleted:
                        deleted_cnt += 1
                    problem_lines.append(f"{'🗑️' if was_deleted else '❓'} `{res['phone']}` — {res['note']}")
                await asyncio.sleep(0.4)   # فترة قصيرة بين الأرقام
            async def _fix_2fa_later():
                for item in needs_2fa_fix:
                    with db_conn() as _c2:
                        row2 = _c2.execute(
                            "SELECT session_string FROM number_stock WHERE id=%s", (item["id"],)
                        ).fetchone()
                    if row2 and row2["session_string"]:
                        ok2, _, pwd2 = await enable_2fa_for_number(
                            item["phone"], row2["session_string"], item["id"], bot=context.bot
                        )
                        if not ok2:
                            await request_manual_2fa_password(context.bot, item["phone"], item["id"])
                    await asyncio.sleep(1)
            if needs_2fa_fix:
                asyncio.create_task(_fix_2fa_later())
            icons = []
            if ok_cnt:        icons.append(f"✅ سليمة: *{ok_cnt}*")
            if frz_cnt:       icons.append(f"🗑️ مجمّدة (حُذفت): *{frz_cnt}*")
            if no_2fa_cnt:    icons.append(f"🔑 مشكلة 2FA: *{no_2fa_cnt}*")
            if multi_dev_cnt: icons.append(f"📲 أجهزة متعددة: *{multi_dev_cnt}*")
            if deleted_cnt:   icons.append(f"🗑️ حُذفت تلقائياً: *{deleted_cnt}* (جلسة منتهية/لا تستجيب)")
            if err_cnt - (deleted_cnt - kick_cnt - timeout_cnt) > 0:
                icons.append(f"❓ أخطاء أخرى: *{err_cnt}*")
            summary = (
                f"📊 *تقرير فحص جميع الحسابات*\n"
                f"الإجمالي المفحوص: *{total}*\n\n"
                + "\n".join(icons)
            )
            if problem_lines:
                detail = "\n".join(problem_lines[:25])
                if len(problem_lines) > 25:
                    detail += f"\n... و{len(problem_lines)-25} أخرى"
                summary += f"\n\n*التفاصيل:*\n{detail}"
            if needs_2fa_fix:
                summary += f"\n\n_⏳ جاري تفعيل/إصلاح 2FA على {len(needs_2fa_fix)} رقم في الخلفية..._"
            await context.bot.send_message(
                OWNER_ID, summary,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📋 قائمة الأرقام", callback_data="os:list_numbers")
                ]])
            )
        asyncio.create_task(_run_full_scan())
        return
    if data == "os:full_audit" and is_own:
        await q.edit_message_text(
            "📊 *بدأ فحص الحسابات جميعاً...*\n\n"
            "سيتم فحص كل حساب على حدة وسيُنقل أي حساب غير قابل للاستخدام إلى سلة المهملات.\n"
            "سيصلك تقرير مفصّل عند الانتهاء.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_numbers")]])
        )
        async def _run_full_audit():
            if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
                await context.bot.send_message(OWNER_ID, "❌ TELEGRAM_API_ID/HASH غير مضبوط — تعذّر الفحص.")
                return
            with db_conn() as _c:
                rows = _c.execute(
                    "SELECT id, phone_number, session_string, twofa_password, last_device_count "
                    "FROM number_stock WHERE session_string IS NOT NULL AND deleted_at IS NULL"
                ).fetchall()
            if not rows:
                await context.bot.send_message(OWNER_ID, "📭 لا توجد أرقام مضافة بجلسة للفحص.")
                return
            total = len(rows)
            ok_cnt = frz_cnt = kick_cnt = timeout_cnt = err_cnt = trashed_cnt = multi_dev_cnt = 0
            banned_list   = []   # محظور / معلّق
            kicked_list   = []   # مطرود / جلسة منتهية
            dup_sess_list = []   # جلسة مستعملة في موقعين
            multi_dev_list = []  # أجهزة متعددة
            problem_lines = []
            for rec in rows:
                rec = dict(rec)
                phone_r  = rec["phone_number"]
                sess_r   = rec["session_string"]
                cli2 = None
                try:
                    cli2 = TelegramClient(StringSession(sess_r), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                    await asyncio.wait_for(cli2.connect(), timeout=15)
                    authorized = await asyncio.wait_for(cli2.is_user_authorized(), timeout=10)
                    if not authorized:
                        kick_cnt += 1
                        trashed_cnt += 1
                        kicked_list.append(phone_r)
                        soft_delete_number(rec["id"])
                        problem_lines.append(f"🗑 `{phone_r}` — جلسة منتهية/مطرودة ← نُقل للمهملات")
                        continue
                    is_frz, frz_status, _ = await asyncio.wait_for(
                        check_account_frozen(cli2, rec["id"]), timeout=10
                    )
                    if is_frz:
                        frz_cnt += 1
                        trashed_cnt += 1
                        banned_list.append(phone_r)
                        soft_delete_number(rec["id"])
                        problem_lines.append(f"🗑 `{phone_r}` — محظور/مجمّد ({frz_status}) ← نُقل للمهملات")
                        continue
                    devs = await asyncio.wait_for(get_device_count(cli2), timeout=10)
                    if devs > 1:
                        multi_dev_cnt += 1
                        multi_dev_list.append(f"`{phone_r}` ({devs} أجهزة)")
                        problem_lines.append(f"📲 `{phone_r}` — {devs} أجهزة (الجلسة مستعملة في أكثر من موقع)")
                    ok_cnt += 1
                except asyncio.TimeoutError:
                    timeout_cnt += 1
                    trashed_cnt += 1
                    soft_delete_number(rec["id"])
                    problem_lines.append(f"🗑 `{phone_r}` — لا يستجيب (timeout) ← نُقل للمهملات")
                except Exception as _ae:
                    err_str = str(_ae)
                    unrecoverable = any(k in err_str for k in (
                        "AuthKeyUnregistered", "SessionRevoked", "AuthKeyDuplicated",
                        "UserDeactivated", "AccountBanned", "PhoneNumberBanned",
                        "AUTH_KEY_UNREGISTERED", "SESSION_REVOKED",
                    ))
                    is_dup = "AuthKeyDuplicated" in err_str or "AUTH_KEY_DUPLICATED" in err_str
                    if unrecoverable:
                        trashed_cnt += 1
                        soft_delete_number(rec["id"])
                        if is_dup:
                            dup_sess_list.append(phone_r)
                            problem_lines.append(f"🗑 `{phone_r}` — جلسة مكررة (موقعين) ← نُقل للمهملات")
                        else:
                            err_cnt += 1
                            problem_lines.append(f"🗑 `{phone_r}` — خطأ فادح: {err_str[:80]} ← نُقل للمهملات")
                    else:
                        err_cnt += 1
                        problem_lines.append(f"❓ `{phone_r}` — خطأ: {err_str[:80]}")
                finally:
                    try:
                        if cli2:
                            await cli2.disconnect()
                    except Exception:
                        pass
                await asyncio.sleep(0.4)
            icons = [f"📊 *تقرير فحص الحسابات جميعاً*\nالإجمالي المفحوص: *{total}*\n"]
            if ok_cnt:         icons.append(f"✅ سليمة: *{ok_cnt}*")
            if multi_dev_cnt:  icons.append(f"📲 أجهزة متعددة: *{multi_dev_cnt}* (جلسة في موقعين أو أكثر)")
            if kick_cnt:       icons.append(f"🚫 جلسة منتهية/مطرودة: *{kick_cnt}* — نُقلت للمهملات")
            if frz_cnt:        icons.append(f"⛔ محظور/مجمّد: *{frz_cnt}* — نُقلت للمهملات")
            if len(dup_sess_list): icons.append(f"🔑 جلسة مكررة (موقعين): *{len(dup_sess_list)}* — نُقلت للمهملات")
            if timeout_cnt:    icons.append(f"⏳ لا تستجيب: *{timeout_cnt}* — نُقلت للمهملات")
            if err_cnt:        icons.append(f"❓ أخطاء أخرى: *{err_cnt}*")
            icons.append(f"\n🗑 إجمالي ما نُقل للمهملات: *{trashed_cnt}*")
            summary = "\n".join(icons)
            if problem_lines:
                detail = "\n".join(problem_lines[:30])
                if len(problem_lines) > 30:
                    detail += f"\n... و{len(problem_lines)-30} أخرى"
                summary += f"\n\n*التفاصيل:*\n{detail}"
            await context.bot.send_message(
                OWNER_ID, summary,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑 عرض سلة المهملات", callback_data="os:nums:trash")],
                    [InlineKeyboardButton("📋 قائمة الأرقام", callback_data="os:list_numbers")],
                ])
            )
        asyncio.create_task(_run_full_audit())
        return
    if data.startswith("os:reset_2fa_single:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec.get("session_string"):
            await q.answer("⚠️ الحساب غير موجود أو بلا جلسة.", show_alert=True)
            return
        with db_conn() as _rc:
            _rr = _rc.execute(
                "SELECT twofa_reset_date FROM number_stock WHERE id=%s", (stock_id,)
            ).fetchone()
        existing_reset = _rr["twofa_reset_date"] if _rr else None
        if existing_reset:
            import datetime as _dt_chk
            _now_c = _dt_chk.datetime.now(_dt_chk.timezone.utc)
            if hasattr(existing_reset, "replace") and existing_reset.tzinfo is None:
                existing_reset = existing_reset.replace(tzinfo=_dt_chk.timezone.utc)
            diff_c = existing_reset - _now_c
            secs_c = int(diff_c.total_seconds())
            if secs_c > 0:
                d_c = secs_c // 86400; h_c = (secs_c % 86400) // 3600; m_c = (secs_c % 3600) // 60
                await q.answer(
                    f"⏳ إجراء الإعادة جارٍ بالفعل.\nالوقت المتبقي: {d_c}ي {h_c}س {m_c}د",
                    show_alert=True
                )
                return
        ok, msg_r, _ = await enable_2fa_for_number(
            rec["phone_number"], rec["session_string"], stock_id, bot=context.bot
        )
        if ok:
            await q.answer("✅ تم بدء إعادة التعيين بنجاح!", show_alert=True)
        else:
            await q.answer(f"ℹ️ {msg_r[:100]}", show_alert=True)
        return
    if data == "os:reset_2fa_all_no2fa" and is_own:
        await q.edit_message_text(
            "🔄 *جاري بدء إعادة تعيين 2FA لجميع الحسابات بدون تحقق...*\n\n"
            "سيُرسَل إليك تقرير عند الانتهاء.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:nums:no_2fa_accessible")]])
        )
        async def _reset_all_no2fa():
            with db_conn() as _c:
                _rows = _c.execute(
                    "SELECT id, phone_number, session_string FROM number_stock "
                    "WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
                    "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL "
                    "AND (twofa_password IS NULL OR twofa_password = '') "
                    "AND twofa_reset_date IS NULL"
                ).fetchall()
            if not _rows:
                await context.bot.send_message(OWNER_ID, "✅ لا توجد حسابات تحتاج إعادة تعيين 2FA.")
                return
            ok_cnt = fail_cnt = skip_cnt = 0
            for _rec in _rows:
                try:
                    _ok, _msg, _ = await enable_2fa_for_number(
                        _rec["phone_number"], _rec["session_string"], _rec["id"], bot=context.bot
                    )
                    if _ok:
                        ok_cnt += 1
                    else:
                        fail_cnt += 1
                except Exception:
                    fail_cnt += 1
                await asyncio.sleep(1)
            await context.bot.send_message(
                OWNER_ID,
                f"📊 *تقرير إعادة تعيين 2FA الشاملة*\n\n"
                f"✅ نجح: {ok_cnt}\n"
                f"❌ فشل: {fail_cnt}\n"
                f"⏳ إجمالي الحسابات المعالجة: {len(_rows)}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 قائمة بدون 2FA", callback_data="os:nums:no_2fa_accessible")]])
            )
        asyncio.create_task(_reset_all_no2fa())
        return
    if data == "os:smart_audit" and is_own:
        if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
            await q.answer("⚠️ TELEGRAM_API_ID/HASH غير مضبوط.", show_alert=True)
            return
        await q.edit_message_text(
            "🧹 *بدأ الفحص الذكي الشامل...*\n\n"
            "▸ الحسابات غير القابلة للوصول → سلة المهملات\n"
            "▸ الحسابات بدون 2FA → إعادة تعيين تلقائي\n"
            "▸ الحسابات المؤهلة → تُرتَّب للبيع\n\n"
            "سيصلك تقرير مفصّل عند الانتهاء.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_numbers")]])
        )
        async def _run_smart_audit():
            with db_conn() as _c:
                _rows = _c.execute(
                    "SELECT id, phone_number, session_string, twofa_password, is_solo, can_send_code, last_device_count "
                    "FROM number_stock WHERE session_string IS NOT NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE"
                ).fetchall()
            if not _rows:
                await context.bot.send_message(OWNER_ID, "📭 لا توجد حسابات للفحص.")
                return
            total = len(_rows)
            trashed = reset_2fa = ready_sell = multi_dev = ok_no_2fa = err_cnt = 0
            detail_lines = []
            for _rec in _rows:
                _phone = _rec["phone_number"]
                _sess  = _rec["session_string"]
                _cli   = None
                try:
                    _cli = TelegramClient(StringSession(_sess), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                    await asyncio.wait_for(_cli.connect(), timeout=15)
                    _auth = await asyncio.wait_for(_cli.is_user_authorized(), timeout=10)
                    if not _auth:
                        soft_delete_number(_rec["id"])
                        trashed += 1
                        detail_lines.append(f"🗑 `{_phone}` — جلسة منتهية ← مهملات")
                        continue
                    _frz, _frz_s, _ = await asyncio.wait_for(check_account_frozen(_cli, _rec["id"]), timeout=10)
                    if _frz:
                        soft_delete_number(_rec["id"])
                        trashed += 1
                        detail_lines.append(f"🗑 `{_phone}` — مجمّد/محظور ← مهملات")
                        continue
                    try:
                        _me = await asyncio.wait_for(_cli.get_me(), timeout=8)
                        if _me:
                            with db_conn() as _uc:
                                _uc.execute("UPDATE number_stock SET can_send_code=TRUE WHERE id=%s AND ever_sold IS NOT TRUE", (_rec["id"],))
                    except Exception:
                        pass
                    _devs = await get_device_count(_cli)
                    if _devs > 1:
                        multi_dev += 1
                        detail_lines.append(f"📲 `{_phone}` — {_devs} أجهزة (يحتاج طرد)")
                    _has_2fa = bool((_rec.get("twofa_password") or "").strip())
                    if not _has_2fa:
                        _ok_2fa, _msg_2fa, _ = await enable_2fa_for_number(_phone, _sess, _rec["id"], bot=context.bot)
                        if _ok_2fa:
                            reset_2fa += 1
                            detail_lines.append(f"🔐 `{_phone}` — بدأ إجراء 2FA")
                        else:
                            ok_no_2fa += 1
                    else:
                        _solo = _rec.get("is_solo")
                        _can  = _rec.get("can_send_code")
                        if _solo and _can and _has_2fa:
                            ready_sell += 1
                        detail_lines.append(f"✅ `{_phone}` — مؤهّل")
                except asyncio.TimeoutError:
                    soft_delete_number(_rec["id"])
                    trashed += 1
                    detail_lines.append(f"🗑 `{_phone}` — timeout ← مهملات")
                except Exception as _ea:
                    _es = str(_ea)
                    if any(k in _es for k in ("AuthKeyUnregistered","SessionRevoked","UserDeactivated","AccountBanned","PhoneNumberBanned")):
                        soft_delete_number(_rec["id"])
                        trashed += 1
                        detail_lines.append(f"🗑 `{_phone}` — {_es[:60]} ← مهملات")
                    else:
                        err_cnt += 1
                        detail_lines.append(f"❓ `{_phone}` — {_es[:60]}")
                finally:
                    try:
                        if _cli: await _cli.disconnect()
                    except Exception:
                        pass
                await asyncio.sleep(0.5)
            summary_lines = [
                f"🧹 *تقرير الفحص الذكي الشامل*\n📊 إجمالي مفحوص: *{total}*\n",
                f"✅ مؤهّلة للبيع: *{ready_sell}*",
                f"🔐 بدأ إجراء 2FA: *{reset_2fa}*",
                f"📲 أجهزة متعددة: *{multi_dev}* (تحتاج طرد جلسات)",
                f"🗑 نُقلت للمهملات: *{trashed}*",
            ]
            if ok_no_2fa:
                summary_lines.append(f"⏳ بدون 2FA (معالجة جارية): *{ok_no_2fa}*")
            if err_cnt:
                summary_lines.append(f"❓ أخطاء أخرى: *{err_cnt}*")
            summary = "\n".join(summary_lines)
            if detail_lines:
                detail = "\n".join(detail_lines[:25])
                if len(detail_lines) > 25:
                    detail += f"\n... و{len(detail_lines)-25} أخرى"
                summary += f"\n\n*التفاصيل:*\n{detail}"
            await context.bot.send_message(
                OWNER_ID, summary, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ الحسابات المفتوحة بالكامل", callback_data="os:nums:accessible_full")],
                    [InlineKeyboardButton("🗑 سلة المهملات", callback_data="os:nums:trash")],
                    [InlineKeyboardButton("📋 قائمة الأرقام", callback_data="os:list_numbers")],
                ])
            )
        asyncio.create_task(_run_smart_audit())
        return
    if data == "os:check_trash_accounts" and is_own:
        await q.edit_message_text(
            "🔍 *جاري فحص حسابات سلة المهملات...*\n\n"
            "سيتم فحص كل حساب في المهملات — أي حساب يمكن للبوت قراءته أو الانضمام بواسطته سيُستعاد تلقائياً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:nums:trash")]])
        )
        async def _check_trash():
            if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
                await context.bot.send_message(OWNER_ID, "❌ TELEGRAM_API_ID/HASH غير مضبوط.")
                return
            with db_conn() as _c:
                rows = _c.execute(
                    "SELECT id, phone_number, session_string, twofa_password "
                    "FROM number_stock WHERE deleted_at IS NOT NULL AND session_string IS NOT NULL"
                ).fetchall()
            if not rows:
                await context.bot.send_message(OWNER_ID, "📭 لا توجد حسابات في المهملات لها جلسة للفحص.")
                return
            total   = len(rows)
            ok_list = []
            dead_list = []
            for rec in rows:
                rec = dict(rec)
                cli3 = None
                try:
                    cli3 = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                    await asyncio.wait_for(cli3.connect(), timeout=15)
                    authorized = await asyncio.wait_for(cli3.is_user_authorized(), timeout=10)
                    if authorized:
                        try:
                            me3 = await asyncio.wait_for(cli3.get_me(), timeout=8)
                        except Exception:
                            me3 = None
                        is_frz3, _, _ = await asyncio.wait_for(
                            check_account_frozen(cli3, rec["id"]), timeout=10
                        )
                        if not is_frz3:
                            restore_deleted_number(rec["id"])
                            with db_conn() as _rc:
                                _rc.execute(
                                    "UPDATE number_stock SET last_authorized=TRUE, can_send_code=TRUE "
                                    "WHERE id=%s",
                                    (rec["id"],)
                                )
                            name = (me3.first_name or "") if me3 else ""
                            ok_list.append(f"`{rec['phone_number']}` {name}".strip())
                        else:
                            dead_list.append(f"`{rec['phone_number']}` (محظور/مجمّد)")
                    else:
                        dead_list.append(f"`{rec['phone_number']}` (جلسة منتهية)")
                except asyncio.TimeoutError:
                    dead_list.append(f"`{rec['phone_number']}` (لا يستجيب)")
                except Exception as _ce:
                    dead_list.append(f"`{rec['phone_number']}` (خطأ: {str(_ce)[:50]})")
                finally:
                    try:
                        if cli3:
                            await cli3.disconnect()
                    except Exception:
                        pass
                await asyncio.sleep(0.4)
            lines = [f"🔍 *نتائج فحص سلة المهملات*\nإجمالي المفحوص: *{total}*\n"]
            if ok_list:
                lines.append(f"✅ *تمت استعادتها ({len(ok_list)}) وأُضيفت لحسابات الإحالة:*")
                lines.extend(f"  • {x}" for x in ok_list[:20])
                if len(ok_list) > 20:
                    lines.append(f"  ... و{len(ok_list)-20} أخرى")
            else:
                lines.append("❌ لا توجد حسابات قابلة للاسترداد في المهملات.")
            if dead_list:
                lines.append(f"\n🗑 ما زالت ميتة ({len(dead_list)}):")
                lines.extend(f"  • {x}" for x in dead_list[:15])
                if len(dead_list) > 15:
                    lines.append(f"  ... و{len(dead_list)-15} أخرى")
            summary3 = "\n".join(lines)
            await context.bot.send_message(
                OWNER_ID, summary3,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑 سلة المهملات", callback_data="os:nums:trash")],
                    [InlineKeyboardButton("📋 قائمة الأرقام", callback_data="os:list_numbers")],
                ])
            )
        asyncio.create_task(_check_trash())
        return
    if data == "os:purge_frozen" and is_own:
        try:
            with db_conn() as _pfc:
                _pfc.execute(
                    "DELETE FROM number_stock "
                    "WHERE frozen_at IS NOT NULL AND ever_sold IS NOT TRUE AND assigned_to IS NULL"
                )
                _pf_cnt = _pfc.rowcount
            await q.edit_message_text(
                f"✅ *تم حذف {_pf_cnt} رقم مجمّد*\n\n"
                f"جميع الأرقام التي كانت مجمّدة (frozen_at) حُذفت نهائياً من المخزون.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 قائمة الأرقام", callback_data="os:list_numbers")],
                    [InlineKeyboardButton("🔙 إدارة المخزون", callback_data="os:manage_numbers")],
                ])
            )
        except Exception as _pfe:
            await q.edit_message_text(f"❌ خطأ: {_pfe}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]]))
        return
    if data == "os:list_numbers" and is_own:
        counts = get_number_counts()
        await q.edit_message_text(
            "📋 *قائمة الأرقام*\n\nاختر التصنيف الذي تريد عرض أرقامه ومعلوماتها التفصيلية:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📦 جميع الأرقام ({counts['all']})", callback_data="os:nums:all")],
                [InlineKeyboardButton(f"🚀 الأرقام المعروضة ({counts['listed']})", callback_data="os:nums:listed")],
                [InlineKeyboardButton(f"⏳ الأرقام المنتظرة ({counts['pending']})", callback_data="os:nums:pending")],
                [InlineKeyboardButton(f"🛒 الحسابات المبيوعة ({counts.get('sold', 0)})", callback_data="os:sold_accounts")],
                [InlineKeyboardButton(f"🚫 الحسابات المطرودة ({counts['kicked']})", callback_data="os:nums:kicked")],
                [InlineKeyboardButton(f"🧊 قائمة المجمّدين ({counts.get('frozen', 0)})", callback_data="os:nums:frozen")],
                [InlineKeyboardButton(f"🔐 حسابات التحقق التلقائي ({counts.get('auto_2fa', 0)})", callback_data="os:nums:auto_2fa")],
                [InlineKeyboardButton(f"✅ الأرقام المكتملة —تحقق+كود— ({counts.get('complete', 0)})", callback_data="os:nums:complete")],
                [InlineKeyboardButton(f"❓ تحقق غير معروف ({counts.get('unknown_verify', 0)})", callback_data="os:nums:unknown_verify")],
                [InlineKeyboardButton(f"📲 أجهزة متعددة ({counts.get('multi_device', 0)})", callback_data="os:nums:multi_device")],
                [InlineKeyboardButton(f"✅ حسابات مفتوحة بالكامل — وصول + رسائل + تحكم ({counts.get('accessible_full', 0)})", callback_data="os:nums:accessible_full")],
                [InlineKeyboardButton(f"📨 أرقام يمكن وصولها — بدون 2FA ({counts.get('no_2fa_accessible', 0)})", callback_data="os:nums:no_2fa_accessible")],
                [InlineKeyboardButton(f"🔐 أرقام يمكن وصولها — لها 2FA معلومة ({counts.get('with_2fa_accessible', 0)})", callback_data="os:nums:with_2fa_accessible")],
                [InlineKeyboardButton(f"📲 أجهزة متعددة — يمكن الوصول ({counts.get('multi_device_access', 0)})", callback_data="os:nums:multi_device_access")],
                [InlineKeyboardButton(f"🗑 سلة المهملات ({counts['trash']})", callback_data="os:nums:trash")],
                [InlineKeyboardButton("📤 إرسال جميع الأرقام نصاً", callback_data="os:send_all_nums_text")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_numbers")],
            ])
        )
        return
    if data == "os:send_all_nums_text" and is_own:
        all_nums = list_stock_numbers("all")
        if not all_nums:
            await q.answer("لا توجد أرقام في المخزون حالياً.", show_alert=True)
            return
        text_block = "\n".join(n["phone_number"] for n in all_nums)
        await q.answer()
        chunk_size = 4000
        for i in range(0, len(text_block), chunk_size):
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text=text_block[i:i + chunk_size],
            )
        return
    if data.startswith("os:nums:") and is_own:
        _parts = data.split(":")
        filter_type = _parts[2]
        _page = int(_parts[3]) if len(_parts) > 3 else 0
        _PAGE_SIZE = 30
        titles = {
            "all":               "📦 جميع الأرقام",
            "listed":            "🚀 الأرقام المعروضة",
            "pending":           "⏳ الأرقام المنتظرة",
            "kicked":            "🚫 الأرقام المطرودة",
            "trash":             "🗑 سلة المهملات",
            "frozen":            "🧊 قائمة المجمّدين",
            "auto_2fa":              "🔐 حسابات التحقق التلقائي",
            "complete":              "✅ الأرقام المكتملة (تحقق + كود)",
            "unknown_verify":        "❓ أرقام التحقق غير المعروف",
            "multi_device":          "📲 أجهزة متعددة",
            "no_2fa_accessible":     "📨 أرقام بدون 2FA (يمكن للبوت وصولها)",
            "with_2fa_accessible":   "🔐 أرقام لها 2FA معلومة (يمكن للبوت وصولها)",
            "accessible_full":       "✅ حسابات مفتوحة بالكامل (وصول + رسائل + تحكم)",
            "multi_device_access":   "📲 أجهزة متعددة — يمكن الوصول",
        }
        title   = titles.get(filter_type, "الأرقام")
        numbers = list_stock_numbers(filter_type)
        total   = len(numbers)
        if not total:
            empty_note = "لا توجد أرقام حالياً ضمن هذا التصنيف."
            if filter_type == "trash":
                empty_note = "سلة المهملات فارغة حالياً."
            elif filter_type == "kicked":
                empty_note = "✅ لا توجد أرقام مطرودة حالياً — كل الأرقام متصلة."
            elif filter_type == "frozen":
                empty_note = "✅ لا توجد حسابات مجمّدة حالياً — جميع الأرقام سليمة."
            elif filter_type == "auto_2fa":
                empty_note = "لا توجد حسابات قام البوت بتفعيل التحقق التلقائي عليها بعد."
            elif filter_type == "complete":
                empty_note = "لا توجد أرقام مكتملة بعد — الأرقام المكتملة هي التي البوت جلستها الوحيدة ويستطيع إرسال كود منها."
            elif filter_type == "unknown_verify":
                empty_note = "✅ لا توجد أرقام بتحقق غير معروف — كل الأرقام حالتها واضحة."
            elif filter_type == "multi_device":
                empty_note = "✅ لا توجد أرقام بأجهزة متعددة — كل الأرقام على جهاز واحد فقط."
            elif filter_type == "no_2fa_accessible":
                empty_note = "لا توجد أرقام يمكن للبوت الوصول إليها بدون 2FA حالياً."
            elif filter_type == "with_2fa_accessible":
                empty_note = "لا توجد أرقام يمكن للبوت الوصول إليها مع 2FA معلومة حالياً."
            elif filter_type == "accessible_full":
                empty_note = "✅ لا توجد حسابات مفتوحة بالكامل حالياً — تحقق من can_send_code."
            elif filter_type == "multi_device_access":
                empty_note = "✅ لا توجد حسابات بأجهزة متعددة مع إمكانية الوصول حالياً."
            await q.edit_message_text(
                f"{title}\n\n{empty_note}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        total_pages = (total + _PAGE_SIZE - 1) // _PAGE_SIZE
        _page       = max(0, min(_page, total_pages - 1))   # تثبيت في الحدود
        _start      = _page * _PAGE_SIZE
        _end        = _start + _PAGE_SIZE
        page_nums   = numbers[_start:_end]
        def _fmt_dt_pg(val):
            if val is None:
                return "غير مسجّل"
            if hasattr(val, "strftime"):
                return val.strftime("%Y-%m-%d %H:%M")
            return str(val)[:16]
        def _nav_row():
            nav = []
            if _page > 0:
                nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"os:nums:{filter_type}:{_page - 1}"))
            if total_pages > 1:
                nav.append(InlineKeyboardButton(f"📄 {_page + 1}/{total_pages}", callback_data="noop"))
            if _page < total_pages - 1:
                nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"os:nums:{filter_type}:{_page + 1}"))
            return nav
        if filter_type == "frozen":
            lines_frz = [
                f"🧊 *{title} ({total})* — صفحة {_page + 1}/{total_pages}\n"
                "⛔ هذه الأرقام محظورة نهائياً من تيليغرام ولا يمكن بيعها.\n"
            ]
            for n in page_nums:
                lines_frz.append(
                    f"📱 `{n['phone_number']}` — {guess_country(n['phone_number'])}\n"
                    f"   📅 أُضيف للبوت: {_fmt_dt_pg(n.get('added_at'))}\n"
                    f"   🧊 تجمّد في:    {_fmt_dt_pg(n.get('frozen_at'))}"
                )
            text_frz = "\n\n".join(lines_frz)
            if len(text_frz) > 4000:
                text_frz = text_frz[:4000] + "\n\n_(النص مقتصر)_"
            btn_rows_frz = [[InlineKeyboardButton(
                f"📱 {n['phone_number']}", callback_data=f"os:number_info:{n['id']}"
            )] for n in page_nums]
            _nr = _nav_row()
            if _nr:
                btn_rows_frz.append(_nr)
            btn_rows_frz.append([InlineKeyboardButton("🗑️ حذف كل المجمّدة الآن", callback_data="os:purge_frozen")])
            btn_rows_frz.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")])
            await q.edit_message_text(text_frz, parse_mode=ParseMode.MARKDOWN,
                                      reply_markup=InlineKeyboardMarkup(btn_rows_frz))
            return
        if filter_type == "auto_2fa":
            lines_2fa = [
                f"🔐 *{title} ({total})* — صفحة {_page + 1}/{total_pages}\n"
                "هذه الحسابات قام البوت بتفعيل كلمة مرور التحقق بخطوتين عليها تلقائياً.\n"
            ]
            for n in page_nums:
                has_pwd = "✅ محفوظة" if n.get("twofa_password") else "❌ غير محفوظة"
                lines_2fa.append(
                    f"📱 `{n['phone_number']}` — {guess_country(n['phone_number'])}\n"
                    f"   📅 أُضيف للبوت: {_fmt_dt_pg(n.get('added_at'))}\n"
                    f"   🔑 كلمة المرور: {has_pwd}"
                )
            text_2fa = "\n\n".join(lines_2fa)
            if len(text_2fa) > 4000:
                text_2fa = text_2fa[:4000] + "\n\n_(النص مقتصر)_"
            btn_rows_2fa = [[InlineKeyboardButton(
                f"📱 {n['phone_number']}", callback_data=f"os:number_info:{n['id']}"
            )] for n in page_nums]
            _nr = _nav_row()
            if _nr:
                btn_rows_2fa.append(_nr)
            btn_rows_2fa.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")])
            await q.edit_message_text(text_2fa, parse_mode=ParseMode.MARKDOWN,
                                      reply_markup=InlineKeyboardMarkup(btn_rows_2fa))
            return
        if filter_type == "kicked":
            lines_kk = [f"🚫 *{title} ({total})* — صفحة {_page + 1}/{total_pages}\n"]
            for n in page_nums:
                lines_kk.append(
                    f"📱 `{n['phone_number']}` — {guess_country(n['phone_number'])}\n"
                    f"   📅 تسجيل: {_fmt_dt_pg(n.get('added_at'))}\n"
                    f"   🚫 طُرد:   {_fmt_dt_pg(n.get('kicked_at'))}"
                )
            text_kk = "\n\n".join(lines_kk)
            if len(text_kk) > 4000:
                text_kk = text_kk[:4000] + "\n\n_(النص مقتصر)_"
            btn_rows_kk = [[InlineKeyboardButton(
                f"📱 {n['phone_number']}", callback_data=f"os:number_info:{n['id']}"
            )] for n in page_nums]
            _nr = _nav_row()
            if _nr:
                btn_rows_kk.append(_nr)
            btn_rows_kk.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")])
            await q.edit_message_text(text_kk, parse_mode=ParseMode.MARKDOWN,
                                      reply_markup=InlineKeyboardMarkup(btn_rows_kk))
            return
        if filter_type == "accessible_full":
            import datetime as _dt_af
            lines_af = [
                f"✅ *{title} ({total})* — صفحة {_page + 1}/{total_pages}\n"
                "هذه الحسابات يمكن للبوت فتحها والتحكم بها وقراءة رسائلها فعلياً.\n"
            ]
            for n in page_nums:
                has_2fa  = "✅ نعم" if n.get("twofa_password") else "❌ لا"
                is_solo  = "✅ نعم" if n.get("is_solo") else "❌ لا"
                devs     = n.get("last_device_count", -1)
                devs_str = str(devs) if devs and devs >= 0 else "؟"
                lines_af.append(
                    f"📱 `{n['phone_number']}` — {guess_country(n['phone_number'])}\n"
                    f"   🔐 2FA: {has_2fa}   |  🎯 وحيد: {is_solo}   |  💻 أجهزة: {devs_str}\n"
                    f"   📅 أُضيف: {_fmt_dt_pg(n.get('added_at'))}"
                )
            text_af = "\n\n".join(lines_af)
            if len(text_af) > 4000:
                text_af = text_af[:4000] + "\n\n_(النص مقتصر)_"
            btn_rows_af = [[InlineKeyboardButton(
                f"✅ {n['phone_number']}", callback_data=f"os:number_info:{n['id']}"
            )] for n in page_nums]
            _nr = _nav_row()
            if _nr:
                btn_rows_af.append(_nr)
            btn_rows_af.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")])
            await q.edit_message_text(text_af, parse_mode=ParseMode.MARKDOWN,
                                      reply_markup=InlineKeyboardMarkup(btn_rows_af))
            return
        if filter_type == "multi_device_access":
            lines_mda = [
                f"📲 *{title} ({total})* — صفحة {_page + 1}/{total_pages}\n"
                "حسابات بأكثر من جهاز مسجّل دخول — البوت لديه وصول إليها.\n"
                "يُنصح بطرد الجلسات الإضافية لتصبح جاهزة للبيع.\n"
            ]
            for n in page_nums:
                has_2fa  = "✅" if n.get("twofa_password") else "❌"
                can_code = "✅" if n.get("can_send_code") else "❌"
                devs     = n.get("last_device_count", -1)
                devs_str = str(devs) if devs and devs >= 0 else "؟"
                lines_mda.append(
                    f"📱 `{n['phone_number']}` — {guess_country(n['phone_number'])}\n"
                    f"   💻 أجهزة: {devs_str}   |  🔐 2FA: {has_2fa}   |  📤 كود: {can_code}\n"
                    f"   📅 أُضيف: {_fmt_dt_pg(n.get('added_at'))}"
                )
            text_mda = "\n\n".join(lines_mda)
            if len(text_mda) > 4000:
                text_mda = text_mda[:4000] + "\n\n_(النص مقتصر)_"
            btn_rows_mda = [[InlineKeyboardButton(
                f"📲 {n['phone_number']} ({n.get('last_device_count', '?')} أجهزة)",
                callback_data=f"os:number_info:{n['id']}"
            )] for n in page_nums]
            _nr = _nav_row()
            if _nr:
                btn_rows_mda.append(_nr)
            btn_rows_mda.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")])
            await q.edit_message_text(text_mda, parse_mode=ParseMode.MARKDOWN,
                                      reply_markup=InlineKeyboardMarkup(btn_rows_mda))
            return
        if filter_type == "no_2fa_accessible":
            import datetime as _dt_no2fa
            _now_utc = _dt_no2fa.datetime.now(_dt_no2fa.timezone.utc)
            lines_no2 = [
                f"📨 *{title} ({total})* — صفحة {_page + 1}/{total_pages}\n"
                "هذه الحسابات يمكن للبوت وصولها لكنها تفتقر إلى التحقق بخطوتين.\n"
                "استخدم أزرار إعادة التعيين لبدء إجراء 2FA (7 أيام انتظار إن كان مشفّراً).\n"
            ]
            btn_rows_no2 = []
            for n in page_nums:
                can_code = "✅" if n.get("can_send_code") else "⏳"
                reset_dt = n.get("twofa_reset_date")
                if reset_dt:
                    if hasattr(reset_dt, "replace"):
                        if reset_dt.tzinfo is None:
                            import datetime as _dtfix
                            reset_dt = reset_dt.replace(tzinfo=_dtfix.timezone.utc)
                    diff     = reset_dt - _now_utc
                    secs     = int(diff.total_seconds())
                    if secs > 0:
                        days_r  = secs // 86400
                        hours_r = (secs % 86400) // 3600
                        mins_r  = (secs % 3600) // 60
                        remain  = f"⏳ إعادة تعيين جارية — باقي: {days_r}ي {hours_r}س {mins_r}د"
                    else:
                        remain = "🔄 مهلة إعادة التعيين انتهت — سيُكمل التحقق قريباً"
                else:
                    remain = "⚠️ لم يبدأ إجراء إعادة التعيين بعد"
                lines_no2.append(
                    f"📱 `{n['phone_number']}` — {guess_country(n['phone_number'])}\n"
                    f"   📤 كود: {can_code}   |  {remain}\n"
                    f"   📅 أُضيف: {_fmt_dt_pg(n.get('added_at'))}"
                )
                btn_rows_no2.append([
                    InlineKeyboardButton(
                        f"📱 {n['phone_number']}",
                        callback_data=f"os:number_info:{n['id']}"
                    ),
                    InlineKeyboardButton(
                        "🔄 إعادة 2FA" if not reset_dt else "⏳ جارٍ",
                        callback_data=f"os:reset_2fa_single:{n['id']}"
                    ),
                ])
            text_no2 = "\n\n".join(lines_no2)
            if len(text_no2) > 4000:
                text_no2 = text_no2[:4000] + "\n\n_(النص مقتصر)_"
            _nr = _nav_row()
            if _nr:
                btn_rows_no2.append(_nr)
            btn_rows_no2.append([InlineKeyboardButton("🔄 إعادة تعيين 2FA للكل", callback_data="os:reset_2fa_all_no2fa")])
            btn_rows_no2.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")])
            await q.edit_message_text(text_no2, parse_mode=ParseMode.MARKDOWN,
                                      reply_markup=InlineKeyboardMarkup(btn_rows_no2))
            return
        def _is_sellable(n) -> bool:
            """نفس شروط _sellable_filter_sql() لكن على كائن Python."""
            return (
                bool(n.get("session_string"))
                and n.get("last_authorized") is not False
                and bool((n.get("twofa_password") or "").strip())
                and not n.get("frozen_at")
            )
        rows = []
        for n in page_nums:
            country = guess_country(n['phone_number'])
            if filter_type == "trash":
                label = f"🗑 {n['phone_number']} — {country}"
            elif not n.get("session_string"):
                label = f"⚠️ {n['phone_number']} — {country} (بدون جلسة)"
            elif n.get("frozen_at"):
                label = f"🧊 {n['phone_number']} — {country} (مجمّد)"
            elif n.get("last_authorized") is False:
                label = f"🚫 {n['phone_number']} — {country} (مطرود)"
            elif _is_sellable(n):
                label = f"✅ {n['phone_number']} — {country}"
            else:
                label = f"⏳ {n['phone_number']} — {country} (غير جاهز)"
            rows.append([InlineKeyboardButton(label, callback_data=f"os:number_info:{n['id']}")])
        _nr = _nav_row()
        if _nr:
            rows.append(_nr)
        if filter_type == "trash":
            rows.append([InlineKeyboardButton("🔍 فحص حسابات المهملات (اكتشاف القابلة للاسترداد)", callback_data="os:check_trash_accounts")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")])
        if filter_type == "all":
            legend = "\n✅ جاهز للبيع  |  ⏳ غير جاهز  |  🚫 مطرود  |  🧊 مجمّد  |  ⚠️ بدون جلسة"
        elif filter_type == "listed":
            legend = "\n✅ هذه الأرقام جاهزة للبيع وتُسلَّم فوراً عند الشراء."
        elif filter_type == "pending":
            legend = "\n⏳ هذه الأرقام غير جاهزة — تحتاج جلسة أو 2FA أو طرد جلسات."
        elif filter_type == "complete":
            legend = "\n✅ البوت جلستها الوحيدة + يستطيع إرسال كود — أعلى مستوى سيطرة."
        elif filter_type == "unknown_verify":
            legend = "\n❓ البوت متصل لكن لا يعرف إن كان الوحيد — لم تُحدَّث حالة is_solo بعد."
        elif filter_type == "multi_device":
            legend = "\n📲 أكثر من جهاز مسجّل — يُنصح بطرد الجلسات الأخرى."
        elif filter_type == "no_2fa_accessible":
            legend = "\n📨 هذه الأرقام متاحة للبوت ويمكن إرسال كود SMS منها — ولا يوجد لها 2FA مضبوط."
        elif filter_type == "with_2fa_accessible":
            legend = "\n🔐 هذه الأرقام متاحة للبوت ولها كلمة مرور 2FA محفوظة."
        elif filter_type == "accessible_full":
            legend = "\n✅ البوت يمكنه الدخول والتحكم وقراءة الرسائل — هذه الحسابات مفتوحة بالكامل."
        elif filter_type == "multi_device_access":
            legend = "\n📲 أكثر من جهاز — البوت لديه وصول. يُنصح بطرد الجلسات الأخرى."
        else:
            legend = ""
        await q.edit_message_text(
            f"*{title} ({total})* — صفحة {_page + 1}/{total_pages}"
            f"{legend}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return
    if data.startswith("os:number_info:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or (rec["assigned_to"] is not None and not rec.get("deleted_at")):
            await q.edit_message_text(
                "⚠️ هذا الرقم غير متاح (تم بيعه).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        if rec.get("deleted_at"):
            del_str = rec["deleted_at"].strftime("%Y-%m-%d %H:%M UTC") if hasattr(rec["deleted_at"], "strftime") else str(rec["deleted_at"])
            await q.edit_message_text(
                f"🗑 *{rec['phone_number']}* — في سلة المهملات\n\n"
                f"🌍 الدولة: {guess_country(rec['phone_number'])}\n"
                f"📅 وقت الحذف: {del_str}\n",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("♻️ استعادة الرقم", callback_data=f"os:number_restore:{stock_id}")],
                    [InlineKeyboardButton("🗑 حذف نهائي (لا يمكن التراجع)", callback_data=f"os:number_purge:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="os:nums:trash")],
                ])
            )
            return
        if not rec["session_string"]:
            await q.edit_message_text(
                f"📱 {rec['phone_number']}\n🌍 {guess_country(rec['phone_number'])}\n\n"
                "⚠️ هذا الرقم أُضيف يدوياً بدون تسجيل دخول، فلا تتوفر معلومات تفصيلية عنه (ولا يمكن جلب كود له).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        await q.edit_message_text(f"⏳ يتم جلب معلومات {rec['phone_number']}... قد يستغرق ذلك بضع ثوانٍ.")
        client = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            try:
                await asyncio.wait_for(client.connect(), timeout=15)
            except asyncio.TimeoutError:
                await q.edit_message_text(
                    f"⏳ *انتهت مهلة الاتصال بـ {rec['phone_number']}*\n\n"
                    "السبب المحتمل: الجلسة ملغية أو الحساب محظور أو شبكة بطيئة.\n"
                    "جرّب مجدداً أو انقل الرقم إلى سلة المهملات.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🗑 نقل إلى سلة المهملات", callback_data=f"os:number_delete:{stock_id}")],
                        [InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")],
                    ])
                )
                return
            try:
                _authorized = await asyncio.wait_for(client.is_user_authorized(), timeout=8)
            except asyncio.TimeoutError:
                _authorized = False
            if not _authorized:
                await q.edit_message_text(
                    f"🔒 *الجلسة منتهية أو ملغية — {rec['phone_number']}*\n\n"
                    "البوت لم يعد مصرّحاً له بالوصول لهذا الحساب.\n"
                    "الرقم لن يُعرَض للبيع تلقائياً حتى تُحدَّث جلسته.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🗑 نقل إلى سلة المهملات", callback_data=f"os:number_delete:{stock_id}")],
                        [InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")],
                    ])
                )
                return
            is_frozen, frozen_status, frozen_at_str = await check_account_frozen(client, stock_id)
            me = None
            age = "غير معروف"
            if not is_frozen:
                try:
                    me = await asyncio.wait_for(client.get_me(), timeout=10)
                    age = estimate_registration_year(me.id) if me else "غير معروف"
                except Exception:
                    pass
            devices = await get_device_count(client)
            spam_detail = await check_spam_status_detailed(client)
            db_frozen_at = rec.get("frozen_at")
            if db_frozen_at and not frozen_at_str:
                if hasattr(db_frozen_at, "strftime"):
                    frozen_at_str = db_frozen_at.strftime("%Y-%m-%d %H:%M UTC")
                else:
                    frozen_at_str = str(db_frozen_at)
            if rec["force_listed"]:
                sale_status = "🚀 معروض مباشرة للبيع (تجاوز انتظار طرد الجلسات)"
            elif rec["sessions_reset"]:
                sale_status = "✅ جاهز للبيع (البوت وحده بالحساب)"
            else:
                sale_status = "⏳ بانتظار طرد الجلسات الأخرى — غير معروض للبيع بعد"
            display_name = ""
            if me:
                display_name = (
                    f"\n👤 الاسم: {(me.first_name or '')} {(me.last_name or '')}".rstrip()
                )
                if me.username:
                    display_name += f" (@{me.username})"
            frozen_line = (
                f"\n🧊 جامد: {'✅ نعم' if is_frozen else '❌ لا'}"
                f"\n⛔ محظور بالكامل: {'✅ نعم' if is_frozen else '❌ لا'}"
            )
            if is_frozen and frozen_at_str:
                frozen_line += f"\n📅 تاريخ التجميد: {frozen_at_str}"
            restricted = spam_detail.get("restricted")
            if restricted is True:
                until_txt = spam_detail.get("until")
                spam_line = f"\n📵 مقيّد من الإرسال: ✅ نعم" + (f"\n⏳ ينتهي القيد: {until_txt}" if until_txt else "\n⏳ ينتهي القيد: غير محدد بدقة في رد تيليجرام")
            elif restricted is False:
                spam_line = f"\n📵 مقيّد من الإرسال: ❌ لا"
            else:
                spam_line = f"\n📵 مقيّد من الإرسال: ⚠️ تعذّر التأكد الآن"
            saved_pwd = rec.get("twofa_password") or ""
            if saved_pwd:
                twofa_line = "\n🔐 التحقق بخطوتين: ✅ مفعّل (انظر زر كلمة المرور)"
            else:
                twofa_line = "\n🔐 التحقق بخطوتين: ❌ غير مفعّل / كلمة المرور غير محفوظة"
            text = (
                f"📱 *{rec['phone_number']}*"
                f"{display_name}\n"
                f"🌍 الدولة: {guess_country(rec['phone_number'])}\n"
                f"🕰️ عمر الحساب (تقريبي): {age}\n"
                f"💻 عدد الأجهزة المسجّلة: {devices if devices >= 0 else 'غير متاح'}"
                f"{frozen_line}"
                f"{spam_line}"
                f"{twofa_line}\n"
                f"🛒 حالة العرض للبيع: {sale_status}\n"
            )
            kb_rows = [
                [InlineKeyboardButton("📋 تفاصيل الأجهزة وتواريخ التسجيل", callback_data=f"os:number_devices:{stock_id}")],
                [InlineKeyboardButton("🔑 جلب آخر كود دخول", callback_data=f"os:number_code:{stock_id}")],
                [InlineKeyboardButton("🔐 كلمة مرور التحقق بخطوتين", callback_data=f"os:number_2fa:{stock_id}")],
                [InlineKeyboardButton("⏱ سماح 5 دقائق (طرد باقي الجلسات فوراً)", callback_data=f"os:allow_5min:{rec['phone_number']}")],
            ]
            if not rec["sessions_reset"] and not rec["force_listed"]:
                kb_rows.append([InlineKeyboardButton("🚀 عرض مباشر للبيع الآن (تجاوز الانتظار)", callback_data=f"os:force_list:{stock_id}")])
            kb_rows.append([InlineKeyboardButton("🚪 تسجيل خروج البوت من هذا الحساب", callback_data=f"os:number_logout:{stock_id}")])
            kb_rows.append([InlineKeyboardButton("🗑 نقل إلى سلة المهملات", callback_data=f"os:number_delete:{stock_id}")])
            kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")])
            await q.edit_message_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
        except Exception as e:
            _err_str = str(e)
            logger.error(f"❌ خطأ في جلب معلومات الرقم {rec['phone_number']}: {_err_str}")
            if any(k in _err_str.lower() for k in ("auth_key_unregistered", "session_revoked", "user_deactivated", "deactivated_ban")):
                _err_msg = "🔒 الجلسة ألغيت أو الحساب محظور نهائياً من تيليجرام."
            elif "flood" in _err_str.lower():
                _err_msg = "⏳ تيليجرام يطلب الانتظار (FloodWait). حاول بعد دقائق."
            elif "network" in _err_str.lower() or "connect" in _err_str.lower():
                _err_msg = "🌐 تعذّر الاتصال بتيليجرام. تحقق من الشبكة وحاول مجدداً."
            else:
                _err_msg = f"❌ خطأ غير متوقع:\n`{_err_str[:200]}`"
            await q.edit_message_text(
                f"⚠️ *تعذّر جلب معلومات {rec['phone_number']}*\n\n{_err_msg}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 إعادة المحاولة", callback_data=f"os:number_info:{stock_id}")],
                    [InlineKeyboardButton("🗑 نقل إلى سلة المهملات", callback_data=f"os:number_delete:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")],
                ])
            )
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        return
    if data.startswith("os:force_list:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or rec["assigned_to"] is not None:
            await q.edit_message_text(
                "⚠️ هذا الرقم غير متاح (تم بيعه أو حذفه).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        set_force_listed(stock_id)
        await q.edit_message_text(
            f"🚀 *تم تفعيل العرض المباشر*\n\n"
            f"📱 {rec['phone_number']} أصبح الآن متاحاً للبيع والتسليم التلقائي فوراً، "
            "حتى لو لم ينتهِ طرد الجلسات الأخرى بعد.\n\n"
            "⚠️ تنبيه: إذا كانت هناك جلسة قديمة لصاحب الرقم السابق لم تُطرد بعد، فقد يبقى بإمكانه رؤية رسائل المشتري الجديد "
            "حتى تنجح إعادة المحاولة التلقائية بالخلفية.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
        )
        return
    if data.startswith("os:number_logout:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec.get("session_string"):
            await q.edit_message_text(
                "⚠️ لا تتوفر جلسة لهذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        await q.edit_message_text(
            f"🚪 *تسجيل خروج البوت من:* `{rec['phone_number']}`\n\n"
            "⚠️ هذا سيُلغي جلسة البوت الحالية على هذا الحساب نهائياً.\n"
            "بعد الخروج: الرقم لن يكون قابلاً للبيع حتى تُضاف جلسة جديدة.\n\n"
            "هل أنت متأكد؟",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ نعم، سجّل خروج", callback_data=f"os:number_logout_confirm:{stock_id}")],
                [InlineKeyboardButton("🔙 إلغاء", callback_data=f"os:number_info:{stock_id}")],
            ])
        )
        return
    if data.startswith("os:number_logout_confirm:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec.get("session_string"):
            await q.edit_message_text(
                "⚠️ لا تتوفر جلسة لهذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        phone = rec["phone_number"]
        await q.edit_message_text(f"⏳ يتم تسجيل الخروج من {phone}...")
        _logout_ok   = False
        _logout_note = ""
        client_lo = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(client_lo.connect(), timeout=15)
            authorized = await asyncio.wait_for(client_lo.is_user_authorized(), timeout=8)
            if authorized:
                await client_lo.log_out()
                _logout_ok   = True
                _logout_note = "تم تسجيل الخروج وإلغاء الجلسة بنجاح."
            else:
                _logout_ok   = True
                _logout_note = "الجلسة كانت منتهية مسبقاً (لا داعي للخروج)."
        except asyncio.TimeoutError:
            _logout_note = "⚠️ انتهت مهلة الاتصال — تم مسح الجلسة محلياً فقط."
        except Exception as _le:
            _logout_note = f"⚠️ خطأ أثناء تسجيل الخروج: `{str(_le)[:120]}`\nتم مسح الجلسة من قاعدة البيانات."
        finally:
            try:
                await client_lo.disconnect()
            except Exception:
                pass
        try:
            with db_conn() as _lc:
                _lc.execute(
                    "UPDATE number_stock SET session_string=NULL, sessions_reset=FALSE, "
                    "force_listed=FALSE, auto_2fa_enabled=FALSE WHERE id=%s",
                    (stock_id,)
                )
        except Exception as _dbe:
            logger.error(f"❌ فشل مسح الجلسة من DB للرقم {phone}: {_dbe}")
        await q.edit_message_text(
            f"🚪 *تسجيل خروج — {phone}*\n\n"
            f"{'✅' if _logout_ok else '⚠️'} {_logout_note}\n\n"
            "📌 الجلسة مُحذوفة من قاعدة البيانات.\n"
            "الرقم انتقل لحالة *يدوي* (بلا جلسة) ولن يُعرض للبيع.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 نقل إلى سلة المهملات", callback_data=f"os:number_delete:{stock_id}")],
                [InlineKeyboardButton("🔙 رجوع لقائمة الأرقام", callback_data="os:list_numbers")],
            ])
        )
        return
    if data.startswith("os:number_delete:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec:
            await q.edit_message_text(
                "⚠️ لم يُعثر على هذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        soft_delete_number(stock_id)
        await q.edit_message_text(
            f"🗑 تم نقل الرقم `{rec['phone_number']}` إلى سلة المهملات.\n\n"
            "يمكنك استعادته في أي وقت من 🗑 سلة المهملات.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لقائمة الأرقام", callback_data="os:list_numbers")]])
        )
        return
    if data.startswith("os:number_restore:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec:
            await q.edit_message_text(
                "⚠️ لم يُعثر على هذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:nums:trash")]])
            )
            return
        restore_deleted_number(stock_id)
        await q.edit_message_text(
            f"♻️ تم استعادة الرقم `{rec['phone_number']}` من سلة المهملات.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لقائمة الأرقام", callback_data="os:list_numbers")]])
        )
        return
    if data.startswith("os:number_purge:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec:
            await q.edit_message_text(
                "⚠️ لم يُعثر على هذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:nums:trash")]])
            )
            return
        phone_del = rec["phone_number"]
        permanently_delete_number(stock_id)
        await q.edit_message_text(
            f"🗑 تم حذف الرقم `{phone_del}` نهائياً من قاعدة البيانات.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لسلة المهملات", callback_data="os:nums:trash")]])
        )
        return
    if data.startswith("os:number_devices:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec["session_string"]:
            await q.edit_message_text(
                "⚠️ لا تتوفر جلسة لهذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
            )
            return
        await q.edit_message_text(f"⏳ يتم جلب قائمة الأجهزة لـ {rec['phone_number']}...")
        client = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(client.connect(), timeout=20)
            devices = await get_authorizations_detail(client)
            if not devices:
                await q.edit_message_text(
                    "⚠️ لم يتم جلب أي جهاز (ربما الحساب جامد أو الجلسة منتهية).",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
                )
                return
            lines = [f"📱 *{rec['phone_number']}* — {len(devices)} جهاز مسجّل\n"]
            kb_rows = []
            for i, d in enumerate(devices, 1):
                created = d["date_created"]
                active  = d["date_active"]
                created_str = created.strftime("%Y-%m-%d %H:%M") if hasattr(created, "strftime") else str(created)
                active_str  = active.strftime("%Y-%m-%d %H:%M")  if hasattr(active,  "strftime") else str(active)
                current_tag = " *(الجهاز الحالي — البوت)*" if d["current"] else ""
                lines.append(
                    f"*{i}.* {d['device']} — {d['app']}{current_tag}\n"
                    f"   🌍 {d['country']}  |  📅 سُجِّل: {created_str}\n"
                    f"   🕑 آخر نشاط: {active_str}\n"
                )
                if not d["current"]:
                    kb_rows.append([InlineKeyboardButton(
                        f"🚫 طرد الجهاز {i}: {d['device'][:30]}",
                        callback_data=f"os:kick_device:{stock_id}:{d['hash']}"
                    )])
            kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")])
            await q.edit_message_text(
                "\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
        except Exception as e:
            logger.error(f"❌ خطأ في جلب الأجهزة للرقم {rec['phone_number']}: {e}")
            await q.edit_message_text(
                "❌ حدث خطأ أثناء جلب الأجهزة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
            )
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        return
    if data.startswith("os:kick_device:") and is_own:
        parts = data.split(":")
        stock_id    = int(parts[2])
        device_hash = int(parts[3])
        rec = get_stock_number(stock_id)
        if not rec or not rec["session_string"]:
            await q.edit_message_text(
                "⚠️ لا تتوفر جلسة لهذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
            )
            return
        await q.edit_message_text("⏳ يتم طرد الجهاز...")
        client = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(client.connect(), timeout=20)
            await client(ResetAuthorizationRequest(hash=device_hash))
            remaining = await get_authorizations_detail(client)
            non_current = [d for d in remaining if not d["current"]]
            if not non_current:
                with db_conn() as c:
                    c.execute("UPDATE number_stock SET sessions_reset=TRUE WHERE id=%s", (stock_id,))
            await q.edit_message_text(
                f"✅ *تم طرد الجهاز بنجاح!*\n\n"
                f"📱 {rec['phone_number']}\n"
                f"الأجهزة المتبقية الآن: {len(remaining)} "
                f"({'البوت فقط ✅' if not non_current else f'{len(non_current)} جهاز خارجي ⚠️'})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 عرض الأجهزة المتبقية", callback_data=f"os:number_devices:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع لمعلومات الرقم", callback_data=f"os:number_info:{stock_id}")],
                ])
            )
        except Exception as e:
            logger.error(f"❌ خطأ في طرد الجهاز للرقم {rec['phone_number']}: {e}")
            await q.edit_message_text(
                f"❌ تعذّر طرد الجهاز: {e}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_devices:{stock_id}")]])
            )
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        return
    if data.startswith("os:number_code:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or rec["assigned_to"] is not None or not rec["session_string"]:
            await q.edit_message_text(
                "⚠️ هذا الرقم غير متاح الآن (تم بيعه أو لا يملك جلسة).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        await q.edit_message_text(f"⏳ يتم جلب آخر كود لرقم {rec['phone_number']}...")
        client = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(client.connect(), timeout=20)
            code_msg, code_date = await fetch_last_login_code(client)
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
                text = (
                    f"🔑 *آخر رسالة من تيليجرام لرقم {rec['phone_number']}:*\n\n"
                    f"{code_msg}\n\n"
                    f"🕐 وصل {_age_str} — {_freshness}"
                )
            else:
                text = f"ℹ️ لا توجد أي رسالة كود حالياً لرقم {rec['phone_number']}."
            await q.edit_message_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 تحديث", callback_data=f"os:number_code:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")],
                ])
            )
        except Exception as e:
            logger.error(f"❌ خطأ في جلب الكود للرقم {rec['phone_number']}: {e}")
            await q.edit_message_text(
                "❌ حدث خطأ أثناء جلب الكود. حاول مجدداً لاحقاً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        return
    if data.startswith("os:number_2fa:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec:
            await q.edit_message_text(
                "⚠️ الرقم غير موجود.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        saved_pwd = rec.get("twofa_password") or ""
        if saved_pwd:
            await q.edit_message_text(
                f"🔐 *التحقق بخطوتين — {rec['phone_number']}*\n\n"
                f"✅ مفعّل\n"
                f"🗝 كلمة المرور: `{saved_pwd}`\n\n"
                "احتفظ بها في مكان آمن — ستحتاجها لو أردت تغييرها.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 إعادة تفعيل بكلمة مرور جديدة", callback_data=f"os:number_2fa_reset:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")],
                ])
            )
        else:
            await q.edit_message_text(
                f"🔐 *التحقق بخطوتين — {rec['phone_number']}*\n\n"
                "❌ غير مفعّل بعد.\n\n"
                "اضغط التفعيل لتوليد كلمة مرور قوية وحفظها تلقائياً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔐 تفعيل التحقق بخطوتين الآن", callback_data=f"os:number_2fa_enable:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")],
                ])
            )
        return
    if data.startswith("os:set_2fa_manual:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec:
            await q.edit_message_text("⚠️ الرقم غير موجود.")
            return
        context.user_data["state"] = "os_await_manual_2fa_pwd"
        context.user_data["manual_2fa_stock_id"] = stock_id
        await q.message.reply_text(
            f"🔑 أرسل الآن كلمة مرور التحقق بخطوتين الصحيحة لرقم `{rec['phone_number']}`:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data.startswith("os:number_2fa_enable:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec.get("session_string"):
            await q.edit_message_text(
                "⚠️ لا يمكن تفعيل التحقق — الرقم بلا جلسة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
            )
            return
        await q.edit_message_text(f"⏳ جاري تفعيل التحقق بخطوتين لرقم {rec['phone_number']}...")
        ok, msg_2fa, pwd_2fa = await enable_2fa_for_number(
            rec["phone_number"], rec["session_string"], stock_id, bot=context.bot
        )
        if ok and pwd_2fa:
            await q.edit_message_text(
                f"✅ *تم تفعيل التحقق بخطوتين بنجاح!*\n\n"
                f"📱 {rec['phone_number']}\n"
                f"🗝 كلمة المرور: `{pwd_2fa}`\n\n"
                "تم حفظها تلقائياً وستظهر دائماً في معلومات الرقم.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
            )
        else:
            await q.edit_message_text(
                f"❌ *فشل تفعيل التحقق بخطوتين*\n\n{msg_2fa}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
            )
        return
    if data.startswith("os:number_2fa_reset:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec.get("session_string"):
            await q.edit_message_text(
                "⚠️ لا يمكن إعادة التفعيل — الرقم بلا جلسة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_2fa:{stock_id}")]])
            )
            return
        current_pwd = rec.get("twofa_password") or ""
        if not current_pwd:
            await q.edit_message_text(f"⏳ جاري تفعيل التحقق بخطوتين لرقم {rec['phone_number']}...")
            ok, msg_2fa, pwd_2fa = await enable_2fa_for_number(
                rec["phone_number"], rec["session_string"], stock_id, bot=context.bot
            )
        else:
            await q.edit_message_text(f"⏳ جاري تغيير كلمة مرور التحقق لرقم {rec['phone_number']}...")
            client2 = TelegramClient(
                StringSession(rec["session_string"]),
                int(TELEGRAM_API_ID), TELEGRAM_API_HASH
            )
            try:
                await client2.connect()
                new_pwd = generate_2fa_password()
                _expected_2fa_change[rec["phone_number"]] = time.time()
                await client2.edit_2fa(
                    current_password=current_pwd,
                    new_password=new_pwd,
                    hint="Auto",
                )
                with db_conn() as c:
                    c.execute("UPDATE number_stock SET twofa_password=%s WHERE id=%s", (new_pwd, stock_id))
                ok, msg_2fa, pwd_2fa = True, "تم", new_pwd
            except Exception as e2:
                ok, msg_2fa, pwd_2fa = False, str(e2)[:120], None
            finally:
                try: await client2.disconnect()
                except Exception: pass
        if ok and pwd_2fa:
            await q.edit_message_text(
                f"✅ *تم تغيير كلمة المرور بنجاح!*\n\n"
                f"📱 {rec['phone_number']}\n"
                f"🗝 كلمة المرور الجديدة: `{pwd_2fa}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
            )
        else:
            await q.edit_message_text(
                f"❌ *فشل تغيير كلمة المرور*\n\n{msg_2fa}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_2fa:{stock_id}")]])
            )
        return
    if data == "sv:panel" and is_supervisor_cb:
        await q.answer()
        await q.edit_message_text(
            "🛡 *لوحة المشرف*\n\n"
            "يمكنك من هنا إضافة أرقامك الخاصة للمخزون لأغراض الاشتراك الإجباري.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=supervisor_panel_kb()
        )
        return
    if data == "sv:login_number" and is_supervisor_cb:
        if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
            await q.edit_message_text(
                "⚠️ *الاتصال بتيليجرام غير مُهيّأ*\n\n"
                "تواصل مع المالك لإعداد `TELEGRAM_API_ID` و `TELEGRAM_API_HASH`.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="sv:panel")]])
            )
            return
        context.user_data["state"] = "sv_await_login_phone"
        await q.edit_message_text(
            "🔑 *إضافة حساب جديد إلى قسم حساباتك*\n\n"
            "أرسل رقم الهاتف بصيغة دولية كاملة، مثال:\n`+9647701234567`\n\n"
            "سيُرسل تيليجرام كود تفعيل لهذا الرقم فوراً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="sv:panel")]])
        )
        return
    if data == "sv:my_accounts" and is_supervisor_cb:
        await q.answer()
        sv_id = user.id
        accounts = get_supervisor_accounts(sv_id)
        if not accounts:
            await q.edit_message_text(
                "📋 *قسم حساباتي الخاصة*\n\n"
                "لا توجد حسابات مضافة بعد.\n"
                "اضغط ➕ لإضافة حسابك الأول.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ إضافة حساب جديد", callback_data="sv:login_number")],
                    [InlineKeyboardButton("🔙 لوحة المشرف",     callback_data="sv:panel")],
                ])
            )
            return
        lines = [f"📋 *قسم حساباتي الخاصة* — {len(accounts)} حساب\n"]
        kb_rows = []
        for acc in accounts:
            ph = acc["phone_number"]
            lines.append(f"• `{ph}`")
            kb_rows.append([InlineKeyboardButton(
                f"🗑 حذف {ph}", callback_data=f"sv:del_account:{ph}"
            )])
        kb_rows.append([InlineKeyboardButton("➕ إضافة حساب جديد", callback_data="sv:login_number")])
        kb_rows.append([InlineKeyboardButton("🔙 لوحة المشرف",     callback_data="sv:panel")])
        await q.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb_rows)
        )
        return
    if data.startswith("sv:del_account:") and is_supervisor_cb:
        await q.answer()
        phone_to_del = data[len("sv:del_account:"):]
        await q.edit_message_text(
            f"⚠️ *تأكيد الحذف*\n\n"
            f"هل تريد حذف الحساب `{phone_to_del}` من قسمك؟\n"
            f"هذا الإجراء لا يمكن التراجع عنه.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ نعم، احذفه",   callback_data=f"sv:confirm_del:{phone_to_del}")],
                [InlineKeyboardButton("❌ إلغاء",        callback_data="sv:my_accounts")],
            ])
        )
        return
    if data.startswith("sv:confirm_del:") and is_supervisor_cb:
        await q.answer()
        phone_to_del = data[len("sv:confirm_del:"):]
        deleted = delete_supervisor_account(user.id, phone_to_del)
        note = "✅ تم حذف الحساب بنجاح." if deleted else "⚠️ لم يُعثر على هذا الحساب."
        accounts = get_supervisor_accounts(user.id)
        if not accounts:
            await q.edit_message_text(
                f"{note}\n\n📋 *قسم حساباتي الخاصة فارغ الآن.*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ إضافة حساب جديد", callback_data="sv:login_number")],
                    [InlineKeyboardButton("🔙 لوحة المشرف",     callback_data="sv:panel")],
                ])
            )
        else:
            lines = [f"{note}\n\n📋 *قسم حساباتي الخاصة* — {len(accounts)} حساب\n"]
            kb_rows = []
            for acc in accounts:
                ph = acc["phone_number"]
                lines.append(f"• `{ph}`")
                kb_rows.append([InlineKeyboardButton(
                    f"🗑 حذف {ph}", callback_data=f"sv:del_account:{ph}"
                )])
            kb_rows.append([InlineKeyboardButton("➕ إضافة حساب جديد", callback_data="sv:login_number")])
            kb_rows.append([InlineKeyboardButton("🔙 لوحة المشرف",     callback_data="sv:panel")])
            await q.edit_message_text(
                "\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
        return
    if data == "sv:forced_ref" and is_supervisor_cb:
        await q.answer()
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
        await q.edit_message_text(
            f'📊 حساباتك المتاحة: *{avail}*\n\n'
            f'اختر نوع الإحالة:',
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('🔑 إحالة بدون تحقق', callback_data='sv:forced_ref_no_ai')],
                [InlineKeyboardButton('🤖 إحالة بميزة تحقق', callback_data='sv:forced_ref_ai')],
                [InlineKeyboardButton('🔙 رجوع', callback_data='sv:panel')],
            ])
        )
        return
    if data == "sv:forced_ref_no_ai" and is_supervisor_cb:
        await q.answer()
        await _sv_forced_ref_start(update, context, user, q, with_ai=False)
        return
    if data == "sv:forced_ref_ai" and is_supervisor_cb:
        await q.answer()
        await _sv_forced_ref_start(update, context, user, q, with_ai=True)
        return
    if data == "sv_forced_ref_skip_channels" and is_supervisor_cb:
        await q.answer()
        draft = context.user_data.setdefault('sv_forced_ref_draft', {})
        draft['channels'] = ''
        sv_accounts = get_supervisor_available_accounts(user.id)
        avail = len(sv_accounts)
        use_ai = draft.get('use_ai', False)
        even_note = '\n⚠️ يُقبل فقط أعداد زوجية (٢، ٤، ٦ ...)' if use_ai else ''
        context.user_data['state'] = 'sv_await_forced_ref_link'
        await q.edit_message_text(
            f'✅ بدون قنوات إجبارية.\n\n'
            f'📊 المتاح: *{avail}* حساب{even_note}\n\n'
            f'📎 *أرسل رابط البوت:*\n'
            f'`t.me/BotUsername?start=CODE`\n'
            f'أو: `@BotUsername CODE`',
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 إلغاء', callback_data='sv:panel')]])
        )
        return
    if data.startswith("sv_forced_ref_confirm:") and is_supervisor_cb:
        await q.answer()
        action = data.split(':')[1]
        if action == 'no':
            context.user_data.pop('sv_forced_ref_draft', None)
            context.user_data['state'] = 'main_menu'
            await q.edit_message_text(
                "❌ تم إلغاء الإحالة الإجبارية.",
                reply_markup=supervisor_panel_kb()
            )
            return
        draft    = context.user_data.get('sv_forced_ref_draft', {})
        bot_user = draft.get('bot_user', '')
        start_p  = draft.get('start_p', '')
        channels = draft.get('channels', '')
        qty      = draft.get('qty', 0)
        use_ai   = draft.get('use_ai', False)
        if not bot_user or qty < 1:
            await q.edit_message_text(
                "⚠️ بيانات الطلب غير مكتملة. ابدأ من جديد.",
                reply_markup=supervisor_panel_kb()
            )
            return
        context.user_data.pop('sv_forced_ref_draft', None)
        context.user_data['state'] = 'main_menu'
        _ai_lbl = ' 🤖' if use_ai else ''
        _code_lbl = f'`{start_p}`' if start_p else 'بدون كود'
        _ch_line  = f'\n📢 القنوات: `{channels}`' if channels else ''
        await q.edit_message_text(
            f'✅ *تم استلام طلبك!*\n\n'
            f'📌 `@{bot_user}` | كود: {_code_lbl}{_ch_line}\n'
            f'🔢 {qty} حساب{_ai_lbl}\n\n'
            f'⏳ سيبدأ التنفيذ الآن وستصلك إشعار عند الانتهاء.',
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=supervisor_panel_kb()
        )
        import asyncio as _aio_sv_cb
        _aio_sv_cb.create_task(
            _run_sv_forced_ref_order(bot_user, start_p, channels, qty, user.id, context, use_ai=use_ai)
        )
        return
    if data == "os:add_supervisor" and is_own:
        await q.answer()
        context.user_data["state"] = "os_await_supervisor_id"
        await q.edit_message_text(
            "🛡 *إضافة مشرف جديد*\n\n"
            "أرسل يوزر المشرف (@username) أو الـ ID الخاص به:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="owner_settings")]])
        )
        return
    if data == "os:list_supervisors" and is_own:
        await q.answer()
        svs = get_supervisors()
        if not svs:
            await q.edit_message_text(
                "📋 *قائمة المشرفين فارغة*\n\nلم يتم إضافة أي مشرف بعد.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛡 إضافة مشرف", callback_data="os:add_supervisor")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
                ])
            )
            return
        lines = ["📋 *قائمة المشرفين:*\n"]
        kb_rows = []
        for sv in svs:
            un = f"@{sv['username']}" if sv.get("username") else ""
            lines.append(f"• `{sv['user_id']}` {un}")
            kb_rows.append([InlineKeyboardButton(
                f"🗑 إزالة {un or sv['user_id']}",
                callback_data=f"os:remove_supervisor:{sv['user_id']}"
            )])
        kb_rows.append([InlineKeyboardButton("🛡 إضافة مشرف", callback_data="os:add_supervisor")])
        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await q.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb_rows)
        )
        return
    if data.startswith("os:remove_supervisor:") and is_own:
        await q.answer()
        try:
            sv_id = int(data.split(":")[-1])
        except ValueError:
            await q.answer("⚠️ معرّف غير صحيح", show_alert=True)
            return
        removed = remove_supervisor(sv_id)
        note = f"✅ تم إزالة المشرف {sv_id}" if removed else "⚠️ لم يُعثر على هذا المشرف"
        svs = get_supervisors()
        if not svs:
            await q.edit_message_text(
                f"{note}\n\n📋 *قائمة المشرفين فارغة الآن.*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛡 إضافة مشرف", callback_data="os:add_supervisor")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
                ])
            )
        else:
            lines = [f"{note}\n\n📋 *قائمة المشرفين:*\n"]
            kb_rows = []
            for sv in svs:
                un = f"@{sv['username']}" if sv.get("username") else ""
                lines.append(f"• `{sv['user_id']}` {un}")
                kb_rows.append([InlineKeyboardButton(
                    f"🗑 إزالة {un or sv['user_id']}",
                    callback_data=f"os:remove_supervisor:{sv['user_id']}"
                )])
            kb_rows.append([InlineKeyboardButton("🛡 إضافة مشرف", callback_data="os:add_supervisor")])
            kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
            await q.edit_message_text(
                "\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
        return
    if data == "os:sv_accounts" and is_own:
        await q.answer()
        grouped = get_all_supervisor_accounts_grouped()
        if not grouped:
            await q.edit_message_text(
                "📋 *حسابات المشرفين*\n\nلا توجد حسابات مضافة من أي مشرف بعد.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")]])
            )
            return
        lines = ["👁 *حسابات جميع المشرفين:*\n"]
        kb_rows = []
        for sv_id, data_sv in grouped.items():
            un = f"@{data_sv['username']}" if data_sv.get("username") else str(sv_id)
            count = len(data_sv["accounts"])
            lines.append(f"🛡 *{un}* — {count} حساب")
            kb_rows.append([InlineKeyboardButton(
                f"👁 عرض حسابات {un}", callback_data=f"os:sv_accs:{sv_id}"
            )])
        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await q.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb_rows)
        )
        return
    if data.startswith("os:sv_accs:") and is_own:
        await q.answer()
        try:
            sv_id = int(data.split(":")[-1])
        except ValueError:
            return
        accounts = get_supervisor_accounts(sv_id)
        svs = {sv["user_id"]: sv for sv in get_supervisors()}
        sv_info = svs.get(sv_id)
        un = f"@{sv_info['username']}" if sv_info and sv_info.get("username") else str(sv_id)
        if not accounts:
            await q.edit_message_text(
                f"📋 *حسابات المشرف {un}*\n\nلا توجد حسابات مضافة.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:sv_accounts")]])
            )
            return
        lines = [f"👁 *حسابات المشرف {un}:*\n"]
        kb_rows = []
        for acc in accounts:
            ph = acc["phone_number"]
            lines.append(f"• `{ph}`")
            kb_rows.append([InlineKeyboardButton(
                f"🗑 حذف {ph}", callback_data=f"os:del_sv_acc:{sv_id}:{ph}"
            )])
        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:sv_accounts")])
        await q.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb_rows)
        )
        return
    if data.startswith("os:del_sv_acc:") and is_own:
        await q.answer()
        parts = data.split(":", 3)
        if len(parts) < 4:
            return
        try:
            sv_id = int(parts[2])
        except ValueError:
            return
        phone = parts[3]
        deleted = delete_supervisor_account(sv_id, phone)
        note = f"✅ تم حذف الحساب `{phone}` من مشرف `{sv_id}`." if deleted else "⚠️ لم يُعثر على الحساب."
        accounts = get_supervisor_accounts(sv_id)
        svs = {sv["user_id"]: sv for sv in get_supervisors()}
        sv_info = svs.get(sv_id)
        un = f"@{sv_info['username']}" if sv_info and sv_info.get("username") else str(sv_id)
        if not accounts:
            await q.edit_message_text(
                f"{note}\n\n📋 لا توجد حسابات أخرى للمشرف {un}.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:sv_accounts")]])
            )
        else:
            lines = [f"{note}\n\n👁 *حسابات المشرف {un}:*\n"]
            kb_rows = []
            for acc in accounts:
                ph = acc["phone_number"]
                lines.append(f"• `{ph}`")
                kb_rows.append([InlineKeyboardButton(
                    f"🗑 حذف {ph}", callback_data=f"os:del_sv_acc:{sv_id}:{ph}"
                )])
            kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:sv_accounts")])
            await q.edit_message_text(
                "\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
        return
    if data == "os:login_number" and is_own:
        if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
            await q.edit_message_text(
                "⚠️ *لم يتم إعداد الاتصال بعد*\n\n"
                "يجب إضافة `TELEGRAM_API_ID` و `TELEGRAM_API_HASH` كمتغيرات بيئة في Railway أولاً "
                "(تحصل عليهما من my.telegram.org بحسابك الشخصي)، ثم أعد المحاولة.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_numbers")]])
            )
            return
        context.user_data["state"] = "os_await_login_phone"
        await q.edit_message_text(
            "🔑 *تسجيل دخول رقم جديد*\n\n"
            "أرسل رقم الهاتف بصيغة دولية كاملة، مثال:\n`+9647701234567`\n\n"
            "سيرسل تيليجرام كود تفعيل لهذا الرقم فوراً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_numbers")]])
        )
        return
    if data == "os:add_numbers" and is_own:
        context.user_data["state"] = "os_await_add_numbers"
        await q.edit_message_text(
            "➕ *إضافة أرقام للمخزون*\n\n"
            "أرسل الأرقام دفعة واحدة، رقم واحد في كل سطر (أو مفصولة بفاصلة)، مثال:\n\n"
            "`+9647701234567`\n`+9647709876543`\n\n"
            "سيتم تجاهل أي رقم مكرر موجود مسبقاً بالمخزون.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_numbers")]])
        )
        return
    if data == 'os:toggle_mansub_visible' and is_own:
        nv = '0' if get_setting('mansub_visible') == '1' else '1'
        set_setting('mansub_visible', nv)
        lbl = 'مرئية للأعضاء ✅' if nv == '1' else 'مخفية (مالك فقط) 🔒'
        await q.answer(f'خدمة الاشتراك الإجباري أصبحت {lbl}', show_alert=True)
        return
    if data == 'os:toggle_forced_ref_visible' and is_own:
        nv = '0' if get_setting('forced_ref_visible') == '1' else '1'
        set_setting('forced_ref_visible', nv)
        lbl = 'مرئية للأعضاء ✅' if nv == '1' else 'مخفية (مالك فقط) 🔒'
        await q.answer(f'خدمة "إحالة بوت فقط" أصبحت {lbl}', show_alert=True)
        return
    if data == 'os:toggle_forced_ref_ai_visible' and is_own:
        nv = '0' if get_setting('forced_ref_ai_visible') == '1' else '1'
        set_setting('forced_ref_ai_visible', nv)
        lbl = 'مرئية للأعضاء ✅' if nv == '1' else 'مخفية (مالك فقط) 🔒'
        await q.answer(f'خدمة "إحالة بميزة تحقق" أصبحت {lbl}', show_alert=True)
        return
    if data == "os:ref_tasks" and is_own:
        await q.answer()
        try:
            tasks = get_referral_tasks()
            lines = ["🤝 <b>مهام الإحالة التلقائية</b>\n"]
            kb_rows = []
            if tasks:
                for t in tasks:
                    _stats = get_referral_task_stats(t["id"])
                    st = "🟢" if t["active"] else "🔴"
                    _lbl  = t['label'].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                    _user = t['bot_username'].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                    _sp   = str(t['start_param'] or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                    lines.append(
                        f"{st} <b>{_lbl}</b>\n"
                        f"   📌 @{_user} | كود: <code>{_sp}</code>\n"
                        f"   ✅ {_stats['done']} | ❌ {_stats['failed']} | ⏳ {_stats['pending']}\n"
                    )
                    kb_rows.append([InlineKeyboardButton(
                        f"⚙️ {t['label']}", callback_data=f"os:ref_task:{t['id']}"
                    )])
            else:
                lines.append("لا توجد مهام إحالة بعد. أضف أولى مهامك!")
            lines.append(
                "\n📌 <b>كيف تعمل؟</b>\n"
                "أضف مهمة إحالة بـ يوزر البوت وكود الإحالة، سيدخل كل رقم في مخزونك "
                "تلقائياً ويُرسل /start مع الكود كإحالة حقيقية."
            )
            kb_rows.append([InlineKeyboardButton("➕ إضافة مهمة إحالة جديدة", callback_data="os:ref_task_add")])
            kb_rows.append([InlineKeyboardButton("▶️ تشغيل كل المهام الآن", callback_data="os:ref_run_all")])
            kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_numbers")])
            try:
                await q.edit_message_text(
                    "\n".join(lines),
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb_rows)
                )
            except Exception as _edit_err:
                if "Message is not modified" not in str(_edit_err):
                    await q.answer(f"⚠️ خطأ: {str(_edit_err)[:120]}", show_alert=True)
        except Exception as _ref_err:
            logger.error(f"❌ os:ref_tasks error: {_ref_err}")
            await q.answer(f"⚠️ خطأ تقني: {str(_ref_err)[:120]}", show_alert=True)
        return
    if data == "os:ref_task_add" and is_own:
        context.user_data["state"] = "os_await_ref_task_channels"
        context.user_data["ref_task_draft"] = {}
        await q.edit_message_text(
            "🤝 *إضافة مهمة إحالة جديدة — خطوة 1/3*\n\n"
            "📢 *القنوات الإجبارية:*\n"
            "أرسل يوزرات أو روابط القنوات التي يجب على الرقم الانضمام إليها قبل الإحالة.\n\n"
            "مثال:\n"
            "`@zzzxxxx @zxxxxxz`\n"
            "`t.me/channel1 t.me/+InviteHash`\n\n"
            "يمكن إرسال أكثر من قناة مفصولة بمسافة أو سطر جديد.\n"
            "أو أرسل `تخطي` إذا لا توجد قنوات إجبارية.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:ref_tasks")]])
        )
        return
    if data.startswith("os:ref_task:") and is_own:
        await q.answer()
        task_id = int(data.split(":")[-1])
        try:
            task = get_referral_task(task_id)
            if not task:
                await q.edit_message_text("⚠️ مهمة غير موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ref_tasks")]]))
                return
            stats = get_referral_task_stats(task_id)
            pending_cnt = len(get_pending_numbers_for_task(task_id))
            status_icon = "🟢 نشطة" if task["active"] else "🔴 موقوفة"
            _chs  = (task.get("mandatory_channels", "") or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            _fl   = (task.get("folder_link", "") or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            _lbl  = task['label'].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            _user = task['bot_username'].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            _sp   = str(task['start_param'] or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            _ch_line = f"\n📢 القنوات الإجبارية: <code>{_chs}</code>" if _chs else ""
            _fl_line = f"\n📂 رابط المجلد: <code>{_fl}</code>" if _fl else ""
            text = (
                f"⚙️ <b>{_lbl}</b>\n\n"
                f"📌 البوت: @{_user}\n"
                f"🔑 كود الإحالة: <code>{_sp}</code>"
                f"{_ch_line}{_fl_line}\n"
                f"الحالة: {status_icon}\n\n"
                f"📊 <b>الإحصاء:</b>\n"
                f"✅ أكملت الإحالة: {stats['done']} رقم\n"
                f"❌ فشلت: {stats['failed']} رقم\n"
                f"⏳ معلّقة (لم تُنفَّذ بعد): {pending_cnt} رقم\n"
            )
            toggle_label = "🔴 إيقاف المهمة" if task["active"] else "🟢 تفعيل المهمة"
            try:
                await q.edit_message_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("▶️ تشغيل الآن على كل الأرقام المعلّقة", callback_data=f"os:ref_run:{task_id}")],
                        [InlineKeyboardButton("🔄 إعادة الاشتراك الإجباري", callback_data=f"os:ref_resub:{task_id}")],
                        [InlineKeyboardButton(toggle_label, callback_data=f"os:ref_toggle:{task_id}")],
                        [InlineKeyboardButton("🗑 حذف هذه المهمة", callback_data=f"os:ref_delete:{task_id}")],
                        [InlineKeyboardButton("🔙 رجوع", callback_data="os:ref_tasks")],
                    ])
                )
            except Exception as _edit_err:
                if "Message is not modified" not in str(_edit_err):
                    await q.answer(f"⚠️ خطأ: {str(_edit_err)[:120]}", show_alert=True)
        except Exception as _err:
            logger.error(f"❌ os:ref_task:{task_id} error: {_err}")
            await q.answer(f"⚠️ خطأ تقني: {str(_err)[:120]}", show_alert=True)
        return
    if data.startswith("os:ref_resub:") and is_own:
        task_id = int(data.split(":")[-1])
        task = get_referral_task(task_id)
        if not task:
            await q.answer("⚠️ مهمة غير موجودة.", show_alert=True)
            return
        with db_conn() as c:
            c.execute("DELETE FROM referral_completions WHERE task_id=%s", (task_id,))
        stats_new = get_referral_task_stats(task_id)
        pending_new = len(get_pending_numbers_for_task(task_id))
        await q.edit_message_text(
            f"✅ <b>تم إعادة الاشتراك الإجباري للمهمة:</b> {task['label']}\n\n"
            f"🔄 تم مسح سجلات الإحالة السابقة.\n"
            f"⏳ <b>معلّقة (جاهزة للتنفيذ):</b> {pending_new} رقم\n\n"
            f"استخدم ▶️ <b>تشغيل الآن</b> لإعادة تنفيذ الإحالة لكل الأرقام.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ تشغيل الآن", callback_data=f"os:ref_run:{task_id}")],
                [InlineKeyboardButton("🔙 رجوع للمهمة", callback_data=f"os:ref_task:{task_id}")],
            ])
        )
        return
    if data.startswith("os:ref_toggle:") and is_own:
        task_id = int(data.split(":")[-1])
        new_active = toggle_referral_task(task_id)
        status = "مفعّلة 🟢" if new_active else "موقوفة 🔴"
        await q.answer(f"المهمة الآن {status}", show_alert=False)
        task = get_referral_task(task_id)
        if not task:
            await q.edit_message_text("⚠️ مهمة غير موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ref_tasks")]]))
            return
        stats = get_referral_task_stats(task_id)
        pending_cnt = len(get_pending_numbers_for_task(task_id))
        status_icon = "🟢 نشطة" if task["active"] else "🔴 موقوفة"
        _chs_t = (task.get("mandatory_channels", "") or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        _fl_t  = (task.get("folder_link", "") or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        _lbl_t = task['label'].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        _usr_t = task['bot_username'].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        _sp_t  = str(task['start_param'] or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        _ch_line = f"\n📢 القنوات الإجبارية: <code>{_chs_t}</code>" if _chs_t else ""
        _fl_line = f"\n📂 رابط المجلد: <code>{_fl_t}</code>" if _fl_t else ""
        try:
            await q.edit_message_text(
                f"⚙️ <b>{_lbl_t}</b>\n\n"
                f"📌 البوت: @{_usr_t}\n"
                f"🔑 كود الإحالة: <code>{_sp_t}</code>"
                f"{_ch_line}{_fl_line}\n"
                f"الحالة: {status_icon}\n\n"
                f"📊 <b>الإحصاء:</b>\n"
                f"✅ أكملت الإحالة: {stats['done']} رقم\n"
                f"❌ فشلت: {stats['failed']} رقم\n"
                f"⏳ معلّقة (لم تُنفَّذ بعد): {pending_cnt} رقم\n",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ تشغيل الآن على كل الأرقام المعلّقة", callback_data=f"os:ref_run:{task_id}")],
                    [InlineKeyboardButton("🔄 إعادة الاشتراك الإجباري", callback_data=f"os:ref_resub:{task_id}")],
                    [InlineKeyboardButton("🔴 إيقاف المهمة" if task["active"] else "🟢 تفعيل المهمة", callback_data=f"os:ref_toggle:{task_id}")],
                    [InlineKeyboardButton("🗑 حذف هذه المهمة", callback_data=f"os:ref_delete:{task_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="os:ref_tasks")],
                ])
            )
        except Exception as _tg_e:
            if "Message is not modified" not in str(_tg_e):
                raise _tg_e
        return
    if data == "os:ref_run_all" and is_own:
        await q.answer("⏳ جاري تشغيل كل المهام النشطة...", show_alert=True)
        tasks = get_referral_tasks(only_active=True)
        if not tasks:
            await q.answer("⚠️ لا توجد مهام نشطة الآن.", show_alert=True)
            return
        async def _run_all_tasks_bg():
            for _t in tasks:
                pending = get_pending_numbers_for_task(_t["id"])
                for _num in pending:
                    if not _num.get("session_string"):
                        continue
                    _ok, _reactiv, _det = await do_referral_for_number(
                        _num["phone_number"], _num["session_string"],
                        _t["bot_username"], _t.get("start_param","") or "",
                        mandatory_channels=_t.get("mandatory_channels","") or "",
                        folder_link=_t.get("folder_link","") or "",
                        stock_id=_num.get("id",0),
                    )
                    _st = "done" if _ok else "failed"
                    mark_referral_completion(_t["id"], _num["id"], _st, None if _ok else _det)
                    import random as _rnd; await asyncio.sleep(_rnd.uniform(10, 25))
        asyncio.ensure_future(_run_all_tasks_bg())
        return
    if data.startswith("os:ref_run:") and is_own:
        task_id = int(data.split(":")[-1])
        task = get_referral_task(task_id)
        if not task:
            await q.edit_message_text("⚠️ مهمة غير موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ref_tasks")]]))
            return
        if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
            await q.edit_message_text(
                "⚠️ يجب إضافة `TELEGRAM_API_ID` و `TELEGRAM_API_HASH` في Railway أولاً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:ref_task:{task_id}")]])
            )
            return
        pending = get_pending_numbers_for_task(task_id)
        if not pending:
            await q.answer("✅ جميع الأرقام أكملت هذه الإحالة بالفعل!", show_alert=True)
            return
        await q.edit_message_text(
            f"⏳ جاري تشغيل مهمة الإحالة على {len(pending)} رقم...\n\n"
            f"سيصلك إشعار فور الانتهاء. هذا قد يستغرق بضع دقائق.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ref_tasks")]])
        )
        async def _run_task_bg():
            import random as _rnd_bg
            done = failed = skipped = reactivated_bg = 0
            for num in pending:
                if not num.get("session_string"):
                    skipped += 1
                    continue
                try:
                    success, _reactiv_t2, detail = await do_referral_for_number(
                        num["phone_number"], num["session_string"],
                        task["bot_username"], task["start_param"],
                        mandatory_channels=task.get("mandatory_channels", "") or "",
                        folder_link=task.get("folder_link", "") or "",
                        stock_id=num.get("id", 0),
                    )
                except Exception as _bg_ex:
                    success = False
                    _reactiv_t2 = False
                    detail = f'[{type(_bg_ex).__name__}] {str(_bg_ex)[:80]}'
                mark_referral_completion(task_id, num["id"],
                                         "done" if success else "failed",
                                         None if success else detail)
                if success and _reactiv_t2:
                    reactivated_bg += 1
                    done += 1
                elif success:
                    done += 1
                else:
                    failed += 1
                await asyncio.sleep(_rnd_bg.uniform(15, 30))
            try:
                await context.bot.send_message(
                    OWNER_ID,
                    f'📊 <b>تقرير الإحالة التلقائية</b>\n'
                    f'📌 🤖 من المالك — الإحالة التلقائية\n'
                    f'🏷 المهمة: {task["label"]} | @{task["bot_username"]}\n\n'
                    f'✅ <b>الحسابات المكملة:</b> {done - reactivated_bg}\n'
                    f'❌ <b>الحسابات الفاشلة:</b> {failed}\n'
                    f'🔄 <b>الحسابات المكررة (مفعّل مسبقاً):</b> {reactivated_bg}'
                    + (f'\n⏭ تخطّى (بدون جلسة بعد): {skipped} رقم' if skipped else ''),
                    parse_mode='HTML'
                )
            except Exception:
                pass
        asyncio.create_task(_run_task_bg())
        return
    if data.startswith("os:ref_delete:") and is_own:
        task_id = int(data.split(":")[-1])
        task = get_referral_task(task_id)
        if task:
            delete_referral_task(task_id)
        await q.edit_message_text(
            f"🗑 تم حذف مهمة الإحالة *{task['label'] if task else ''}* بنجاح.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ref_tasks")]])
        )
        return
    if data == "os:edit_number_cost" and is_own:
        context.user_data["state"] = "os_await_number_cost"
        cur = get_setting("telegram_number_cost") or "5000"
        await q.edit_message_text(f"📱 سعر رقم تيلغرام الحالي: {cur} نقطة\n\nأرسل القيمة الجديدة:")
        return
    if data == "os:edit_mstars_min" and is_own:
        cur = get_setting("mandatory_stars_min_members") or "50"
        context.user_data["state"] = "os_await_mstars_min"
        await q.edit_message_text(
            f"⭐ *الحد الأدنى للأعضاء — التمويل الإجباري بالنجوم*\n\n"
            f"القيمة الحالية: {cur} عضو\n\nأرسل القيمة الجديدة:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:edit_mstars_t1max" and is_own:
        cur = get_setting("mandatory_stars_tier1_max") or "120"
        context.user_data["state"] = "os_await_mstars_t1max"
        await q.edit_message_text(
            f"⭐ *الحد الأعلى للشريحة 1 — التمويل الإجباري*\n\n"
            f"القيمة الحالية: {cur} عضو\n"
            f"(أعضاء ≤ هذا الحد يدفعون سعر الشريحة 1)\n\nأرسل القيمة الجديدة:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:edit_mstars_t1p" and is_own:
        cur = int(get_setting("mandatory_stars_tier1_price_x100") or "50")
        context.user_data["state"] = "os_await_mstars_t1p"
        await q.edit_message_text(
            f"⭐ *سعر الشريحة 1 (مضروباً × 100)*\n\n"
            f"القيمة الحالية: {cur} (= {cur/100:.2f} نجمة/عضو)\n"
            f"مثال: 50 = 0.50 نجمة لكل عضو\n\nأرسل القيمة الجديدة:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:edit_mstars_t2p" and is_own:
        cur = int(get_setting("mandatory_stars_tier2_price_x100") or "33")
        context.user_data["state"] = "os_await_mstars_t2p"
        await q.edit_message_text(
            f"⭐ *سعر الشريحة 2 (مضروباً × 100)*\n\n"
            f"القيمة الحالية: {cur} (= {cur/100:.2f} نجمة/عضو)\n"
            f"مثال: 33 = 0.33 نجمة لكل عضو\n\nأرسل القيمة الجديدة:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:edit_leave_grace" and is_own:
        cur = get_setting("internal_leave_grace_hours") or "24"
        context.user_data["state"] = "os_await_leave_grace"
        await q.edit_message_text(
            f"⏱ *مهلة المغادرة الآمنة — القنوات الداخلية*\n\n"
            f"القيمة الحالية: {cur} ساعة\n"
            f"(المستخدم يُعاقب فقط إذا غادر خلال هذه المدة)\n\nأرسل القيمة الجديدة بالساعات:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:sold_search" and is_own:
        context.user_data["state"] = "os_await_sold_search"
        await q.edit_message_text(
            "🔍 *البحث في الحسابات المبيوعة*\n\nأرسل رقم الهاتف أو جزءاً منه:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:phone_search" and is_own:
        context.user_data["state"] = "os_await_phone_search"
        await q.edit_message_text(
            "🔎 *بحث برقم هاتف*\n\n"
            "أرسل رقم الهاتف أو جزءاً منه وسأجلب لك جميع المعلومات عنه،\n"
            "سواء كان مباعاً أو متاحاً أو محذوفاً:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_numbers")]]))
        return
    if data == "os:sold_code_search" and is_own:
        context.user_data["state"] = "os_await_sold_code_search"
        await q.edit_message_text(
            "🧾 *التحقق بكود الطلب*\n\nأرسل كود الطلب للتحقق منه:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:edit_contact" and is_own:
        context.user_data["state"] = "os_await_contact"
        cur = get_setting("owner_contact") or "غير مضبوط"
        cur_label = get_setting("owner_contact_label") or "💬 تواصل مع المالك"
        await q.edit_message_text(
            f"💬 *رابط تواصل المالك*\n\n"
            f"الرابط الحالي: {cur}\n"
            f"نص الزر الحالي: {cur_label}\n\n"
            f"أرسل رابط تيلغرام الخاص بك:\n"
            f"مثال: `https://t.me/username`\n\n"
            f"(أرسل *حذف* لإزالة الرابط)",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:thank_owner_settings" and is_own:
        context.user_data["state"] = "main_menu"
        await q.edit_message_text(
            "💌 *إعدادات شكر المالك*\n\n"
            "اختر النص الذي تريد تغييره. التغييرات تُحفظ مباشرةً وتظهر للأعضاء:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=thank_owner_settings_kb()
        )
        return
    if data.startswith("os:thank_owner_edit:") and is_own:
        key = data.split(":", 2)[2]
        if key not in THANK_OWNER_SETTINGS:
            await q.answer("⚠️ هذا الإعداد غير موجود.", show_alert=True)
            return
        title, default = THANK_OWNER_SETTINGS[key]
        current = get_setting(key) or default
        context.user_data["state"] = "os_await_thank_owner_setting"
        context.user_data["thank_owner_setting_key"] = key
        await q.edit_message_text(
            f"✏️ *{title}*\n\n"
            f"النص الحالي:\n{current}\n\n"
            "أرسل النص الجديد:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="os:thank_owner_settings")]
            ])
        )
        return
    if data == "os:edit_contact_label" and is_own:
        context.user_data["state"] = "os_await_contact_label"
        cur_label = get_setting("owner_contact_label") or "💬 تواصل مع المالك"
        await q.edit_message_text(
            f"✏️ *نص زر التواصل (بعد خصم النقاط)*\n\n"
            f"النص الحالي: {cur_label}\n\n"
            f"أرسل النص الجديد للزر:\n"
            f"مثال: `- الدعم الفني 🧑‍🔧 -`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:edit_support_label" and is_own:
        context.user_data["state"] = "os_await_support_label"
        cur_label = get_setting("support_contact_label") or "🛎 تواصل مع الدعم"
        await q.edit_message_text(
            f"✏️ *نص زر الدعم داخل صفحة التواصل*\n\n"
            f"النص الحالي: {cur_label}\n\n"
            f"أرسل النص الجديد:\n"
            f"مثال: `- الدعم الفني 🧑‍🔧 -`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:edit_welcome" and is_own:
        context.user_data["state"] = "os_await_welcome"
        cur = get_setting("welcome_message") or ""
        await q.edit_message_text(f"💌 رسالة الترحيب الحالية:\n{cur}\n\nأرسل الرسالة الجديدة:")
        return
    if data == "os:edit_asiacell" and is_own:
        context.user_data["state"] = "os_await_asiacell_text"
        cur = get_setting("asiacell_text") or ""
        await q.edit_message_text(f"📲 النص الحالي لاسيا سيل:\n\n{cur}\n\nأرسل النص الجديد:")
        return
    if data == "os:edit_join_reward" and is_own:
        cur = get_setting("join_channel_reward") or "45"
        context.user_data["state"] = "os_await_join_reward"
        await q.edit_message_text(
            f"🎁 *نقاط الانضمام للقنوات الداخلية*\n\n"
            f"القيمة الحالية: {cur} نقطة\n\n"
            f"أرسل عدد النقاط التي يحصل عليها العضو عند الانضمام:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:edit_leave_penalty" and is_own:
        cur = get_setting("channel_leave_penalty") or "75"
        context.user_data["state"] = "os_await_leave_penalty"
        await q.edit_message_text(
            f"❌ *خصم مغادرة القناة*\n\n"
            f"القيمة الحالية: {cur} نقطة\n\n"
            f"عند مغادرة العضو لقناة داخلية حصل منها على نقاط انضمام سابقاً، تُخصم منه هذه القيمة تلقائياً.\n"
            f"أرسل عدد النقاط الجديد:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:edit_mandatory_min" and is_own:
        cur = get_setting("mandatory_channel_min_members") or "0"
        context.user_data["state"] = "os_await_mandatory_min"
        await q.edit_message_text(
            f"👥 *الحد الأدنى للأعضاء — التمويل الإجباري*\n\n"
            f"القيمة الحالية: {int(cur):,} عضو\n"
            f"(0 = بدون حد أدنى)\n\n"
            f"أرسل العدد الجديد:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:edit_internal_min" and is_own:
        cur = get_setting("internal_channel_min_members") or "0"
        context.user_data["state"] = "os_await_internal_min"
        await q.edit_message_text(
            f"👥 *الحد الأدنى للأعضاء — التمويل الداخلي*\n\n"
            f"القيمة الحالية: {int(cur):,} عضو\n"
            f"(0 = بدون حد أدنى)\n\n"
            f"أرسل العدد الجديد:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:edit_mandatory_cost" and is_own:
        cur = get_setting("mandatory_channel_cost") or "200"
        context.user_data["state"] = "os_await_mandatory_cost"
        await q.edit_message_text(
            f"📢 *سعر تمويل القناة الإجباري السريع*\n\n"
            f"السعر الحالي: {cur} نقطة\n\n"
            f"أرسل السعر الجديد بالنقاط:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if data == "os:edit_internal_cost" and is_own:
        cur = get_setting("internal_channel_cost") or "100"
        context.user_data["state"] = "os_await_internal_cost"
        await q.edit_message_text(
            f"🔄 *سعر تمويل القناة الداخلي البطيء*\n\n"
            f"السعر الحالي: {cur} نقطة\n\n"
            f"أرسل السعر الجديد بالنقاط:",
            parse_mode=ParseMode.MARKDOWN
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
            _deleted_ch = c.execute("SELECT funding_type FROM mandatory_channels WHERE id=?", (ch_id,)).fetchone()
            c.execute("UPDATE mandatory_channels SET active=0, queued=0 WHERE id=?", (ch_id,))
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
        context.user_data["state"]       = "os_await_points_target"
        context.user_data["points_mode"] = "give"
        await q.edit_message_text(
            "➕ *منح نقاط*\n\nأرسل ID المستخدم أو @يوزرنيم:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_points")]])
        )
        return
    if data == "os:deduct_points" and is_own:
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
    if data.startswith("gmail_detail:") and is_own:
        context.user_data.pop("gmail_verification_note_edit_sub_id", None)
        sub_id = int(data.split(":")[1])
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
        if sub["status"] == "pending":
            gmail_reward = int(get_setting("gmail_points_reward") or "10000")
            detail_rows.append([InlineKeyboardButton(f"✅ قبول وإعطاء {gmail_reward:,} نقطة", callback_data=f"gmail_approve:{sub_id}")])
            detail_rows.append([InlineKeyboardButton("❌ رفض", callback_data=f"gmail_reject:{sub_id}")])
        detail_rows.append([InlineKeyboardButton(
            "✏️ تعديل رسالة التحقق",
            callback_data=f"gmail_edit_verification_note:{sub_id}",
        )])
        detail_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_gmail")])
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
        if sub["status"] != "pending":
            await q.answer("⚠️ هذا الطلب معالَج مسبقاً.", show_alert=True)
            return
        gmail_reward = int(get_setting("gmail_points_reward") or "10000")
        with db_conn() as c:
            c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (gmail_reward, sub["user_id"]))
            c.execute("UPDATE gmail_submissions SET status='approved' WHERE id=%s", (sub_id,))
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
        sub_id = int(data.split(":")[1])
        with db_conn() as c:
            sub = c.execute("SELECT * FROM gmail_submissions WHERE id=%s", (sub_id,)).fetchone()
        if not sub:
            await q.answer("❌ الطلب غير موجود.", show_alert=True)
            return
        if sub["status"] != "pending":
            await q.answer("⚠️ هذا الطلب معالَج مسبقاً.", show_alert=True)
            return
        user_link = f"tg://user?id={sub['user_id']}"
        await q.edit_message_text(
            f"❌ <b>رفض طلب الجيميل</b>\n\n👤 <a href='{user_link}'>المستخدم</a> | 🆔 {sub['user_id']}\n\nاختر سبب الرفض:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ إيميل خطأ", callback_data=f"gmail_reject_reason:wrong_email:{sub_id}")],
                [InlineKeyboardButton("🔑 باسورد خطأ", callback_data=f"gmail_reject_reason:wrong_pass:{sub_id}")],
                [InlineKeyboardButton("🔐 يحتاج تحقق", callback_data=f"gmail_reject_reason:need_verify:{sub_id}")],
                [InlineKeyboardButton("🔙 رجوع", callback_data=f"gmail_detail:{sub_id}")],
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
        if sub["status"] != "pending":
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
        _parts = data.split(":")
        if len(_parts) < 4:
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
                "AND prize_type IN ('telegram_number','telegram_number_code') AND status='completed'",
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
                "     AND pe.prize_type IN ('telegram_number','telegram_number_code') "
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
                "     AND pe.prize_type IN ('telegram_number','telegram_number_code') "
                "LEFT JOIN users u ON u.user_id = pe.user_id "
                "WHERE ns.ever_sold IS TRUE AND ns.assigned_to IS NULL AND ns.deleted_at IS NULL "
                "ORDER BY pe.created_at DESC NULLS LAST LIMIT 30"
            ).fetchall()
            dupes_check = c.execute(
                "SELECT prize_value, COUNT(*) AS cnt "
                "FROM prize_exchanges "
                "WHERE prize_type IN ('telegram_number','telegram_number_code') "
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
                "     AND pe.prize_type IN ('telegram_number','telegram_number_code') "
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
                "  AND pe.prize_type IN ('telegram_number','telegram_number_code') "
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
                "  AND pe.prize_type IN ('telegram_number','telegram_number_code') "
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
                "  AND prize_type IN ('telegram_number','telegram_number_code') "
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
    try:
        await q.answer()
    except Exception:
        pass
