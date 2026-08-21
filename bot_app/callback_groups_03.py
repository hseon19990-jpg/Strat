"""Callback case group 3 for the Telegram bot.

Cases stay in their original order. A matching case returns from this group,
while the sentinel lets the dispatcher continue to the next group.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

async def _handle_callback_group_03(update, context, q, data, user, is_own, is_supervisor_cb, _gmail_verification_done):
    if True:
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
                            # 2FA غير مفعّل — نفعّله بكلمة "محمد"
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
                            # تحقق من الكلمة الثابتة
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
                                # أُضف لقائمة الإصلاح
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
                                # يُضاف لقائمة الإصلاح للمحاولة لاحقاً
                                _accounts_needing_fixup[sid] = {"phone": ph, "session": ss, "stock_id": sid, "retries": 0}
                        except Exception as _ke:
                            _kes = str(_ke)
                            if "too new" in _kes or "cannot be used to reset" in _kes:
                                # جلسة جديدة جداً — يُضاف للإصلاح التلقائي
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
                "🔍 *بدأ الفحص التلقائي للحسابات...*\n\n"
                "سيتم رفع كل حساب يجتاز فحص الجلسة و2FA وعدم التجميد للبيع مباشرة، "
                "وإزالة العرض عن الحسابات التي تفشل.\n\n"
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
                        # ── حذف المجمّد تلقائياً إذا لم يُباع مسبقاً ──────────
                        with db_conn() as _fc:
                            _fe = _fc.execute(
                                "SELECT ever_sold FROM number_stock WHERE id=%s", (rec["id"],)
                            ).fetchone()
                            if _fe and not _fe["ever_sold"]:
                                _fc.execute("DELETE FROM number_stock WHERE id=%s", (rec["id"],))
                                result["note"] += " — حُذف تلقائياً"
                                logger.info(f"🗑️ حذف تلقائي (مجمّد): الرقم {rec['phone_number']}")
                        return result
        
                    # ✅ الحساب متاح ونشط — ضبط can_send_code=TRUE حتى يظهر في عداد الإحالة الإجبارية
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
                    # البوت لا يستطيع فتحه → حذف نهائي
                    with db_conn() as _c:
                        _es = _c.execute(
                            "SELECT ever_sold FROM number_stock WHERE id=%s", (rec["id"],)
                        ).fetchone()
                        if _es and not _es["ever_sold"]:
                            _c.execute("DELETE FROM number_stock WHERE id=%s", (rec["id"],))
                            logger.info(f"🗑️ حذف تلقائي (timeout): الرقم {rec['phone_number']}")
                except Exception as e:
                    err_txt = str(e)
                    # AuthKeyUnregistered / SessionRevoked / UserDeactivated = فقدان سيطرة نهائي → حذف
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
        
                # ─── فحص واحد بالواحد لتجنب حظر Telegram من الاتصالات المتزامنة الكثيرة ───
                for rec in rows:
                    res = await asyncio.wait_for(_scan_one(dict(rec)), timeout=35)
                    st = res["status"]
                    # الفحص التلقائي يرفع الناجح للبيع مباشرة، ويزيل العرض عن أي فاشل.
                    with db_conn() as _lc:
                        _lc.execute(
                            "UPDATE number_stock SET force_listed=%s "
                            "WHERE id=%s AND ever_sold IS NOT TRUE",
                            (st == "ok", res["id"]),
                        )
        
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
        
                # ─── تفعيل 2FA للأرقام التي تحتاجه (في الخلفية بعد التقرير) ───
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
        
                # ─── إرسال التقرير ───
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
            # إذا كان إجراء الإعادة جارياً مسبقاً، أخبر المالك بالوقت المتبقي
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
            # بدء إجراء إعادة التعيين
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
                        # فحص التجميد
                        _frz, _frz_s, _ = await asyncio.wait_for(check_account_frozen(_cli, _rec["id"]), timeout=10)
                        if _frz:
                            soft_delete_number(_rec["id"])
                            trashed += 1
                            detail_lines.append(f"🗑 `{_phone}` — مجمّد/محظور ← مهملات")
                            continue
                        # تحديث can_send_code
                        try:
                            _me = await asyncio.wait_for(_cli.get_me(), timeout=8)
                            if _me:
                                with db_conn() as _uc:
                                    _uc.execute("UPDATE number_stock SET can_send_code=TRUE WHERE id=%s AND ever_sold IS NOT TRUE", (_rec["id"],))
                        except Exception:
                            pass
                        # عدد الأجهزة
                        _devs = await get_device_count(_cli)
                        if _devs > 1:
                            multi_dev += 1
                            detail_lines.append(f"📲 `{_phone}` — {_devs} أجهزة (يحتاج طرد)")
                        # إذا لا 2FA → بدء إجراء الإعادة
                        _has_2fa = bool((_rec.get("twofa_password") or "").strip())
                        if not _has_2fa:
                            _ok_2fa, _msg_2fa, _ = await enable_2fa_for_number(_phone, _sess, _rec["id"], bot=context.bot)
                            if _ok_2fa:
                                reset_2fa += 1
                                detail_lines.append(f"🔐 `{_phone}` — بدأ إجراء 2FA")
                            else:
                                ok_no_2fa += 1
                        else:
                            # فحص مؤهلية البيع
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
                                # ✅ مكتشف — أعِد وضعه في المخزون وفعّل can_send_code
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
            # رقم واحد في كل سطر بدون أي إضافات
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
        
            # ══════════════════════════════════════════════════════
            # ══════════════════════════════════════════════════════
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
        
            # ══════════════════════════════════════════════════════
            # ══════════════════════════════════════════════════════
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
        
            # ══════════════════════════════════════════════════════
            # ══════════════════════════════════════════════════════
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
        
            # ══════════════════════════════════════════════════════
            # ✅ حسابات مفتوحة بالكامل — وصول + رسائل + تحكم
            # ══════════════════════════════════════════════════════
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
        
            # ══════════════════════════════════════════════════════
            # 📲 أجهزة متعددة — يمكن الوصول
            # ══════════════════════════════════════════════════════
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
        
            # ══════════════════════════════════════════════════════
            # 📨 أرقام بدون 2FA — مع أزرار إعادة تعيين وعرض الوقت المتبقي
            # ══════════════════════════════════════════════════════
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
        
            # ══════════════════════════════════════════════════════
            # ══════════════════════════════════════════════════════
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
            # ─── زر فحص حسابات المهملات (يظهر فقط في سلة المهملات) ───
            if filter_type == "trash":
                rows.append([InlineKeyboardButton("🔍 فحص حسابات المهملات (اكتشاف القابلة للاسترداد)", callback_data="os:check_trash_accounts")])
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")])
        
            # ─── تفسير الرموز ───
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
                # ─── الرقم في سلة المهملات: عرض مبسّط بدون فحص مباشر من تيليجرام + خيارات الاستعادة/الحذف النهائي ───
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
                # ─── اتصال بـ timeout صريح حتى لا يعلّق البوت على جلسات ملغية ───
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
        
                # ─── تحقق من صلاحية الجلسة قبل أي طلب ───
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
        
                # ─── فحص التجميد أولاً ───
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
                # ─── حالة التجميد المحفوظة في DB ───
                db_frozen_at = rec.get("frozen_at")
                if db_frozen_at and not frozen_at_str:
                    if hasattr(db_frozen_at, "strftime"):
                        frozen_at_str = db_frozen_at.strftime("%Y-%m-%d %H:%M UTC")
                    else:
                        frozen_at_str = str(db_frozen_at)
                # ─── حالة البيع ───
                if rec["force_listed"]:
                    sale_status = "🚀 معروض مباشرة للبيع (تجاوز انتظار طرد الجلسات)"
                elif rec["sessions_reset"]:
                    sale_status = "✅ جاهز للبيع (البوت وحده بالحساب)"
                else:
                    sale_status = "⏳ بانتظار طرد الجلسات الأخرى — غير معروض للبيع بعد"
                # ─── اسم المستخدم ───
                display_name = ""
                if me:
                    display_name = (
                        f"\n👤 الاسم: {(me.first_name or '')} {(me.last_name or '')}".rstrip()
                    )
                    if me.username:
                        display_name += f" (@{me.username})"
                # ─── معلومات التجميد/الحظر الكامل ───
                frozen_line = (
                    f"\n🧊 جامد: {'✅ نعم' if is_frozen else '❌ لا'}"
                    f"\n⛔ محظور بالكامل: {'✅ نعم' if is_frozen else '❌ لا'}"
                )
                if is_frozen and frozen_at_str:
                    frozen_line += f"\n📅 تاريخ التجميد: {frozen_at_str}"
                # ─── حالة التقييد المؤقت من الإرسال ───
                restricted = spam_detail.get("restricted")
                if restricted is True:
                    until_txt = spam_detail.get("until")
                    spam_line = f"\n📵 مقيّد من الإرسال: ✅ نعم" + (f"\n⏳ ينتهي القيد: {until_txt}" if until_txt else "\n⏳ ينتهي القيد: غير محدد بدقة في رد تيليجرام")
                elif restricted is False:
                    spam_line = f"\n📵 مقيّد من الإرسال: ❌ لا"
                else:
                    spam_line = f"\n📵 مقيّد من الإرسال: ⚠️ تعذّر التأكد الآن"
                # ─── حالة 2FA ───
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
                # ─── رسائل خطأ واضحة حسب نوع الخطأ ───
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
            # ─── خطوة تأكيد قبل التنفيذ ───
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
            # ─── سجّل خروج عبر Telethon ───
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
            # ─── امسح الجلسة من DB في جميع الحالات ───
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
            # تأكيد التشغيل
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
            # os:del_sv_acc:{sv_id}:{phone}
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

        if data == "os:toggle_legendary_services" and is_own:
            nv = "0" if is_legendary_services_visible() else "1"
            set_setting("legendary_services_visible", nv)
            lbl = "مرئية للأعضاء ✅" if nv == "1" else "مخفية (مالك فقط) 🔒"
            await q.answer(f"خدمات أسطورية أصبحت {lbl}", show_alert=True)
            await q.edit_message_reply_markup(reply_markup=owner_settings_kb())
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
            # إعادة ضبط جميع السجلات لتُعيد كل الأرقام الاشتراك من جديد
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
                    # تخطي الأرقام التي لم تحصل على جلسة بعد
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
                    # تأخير كافٍ بين الحسابات لتجنّب قيود تيليجرام
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

        if data == "os:edit_number_stars" and is_own:
            context.user_data["state"] = "os_await_number_stars"
            cur = get_setting("telegram_number_stars") or "18"
            await q.edit_message_text(
                f"⭐ سعر شراء رقم تيلغرام بالنجوم حالياً: {cur} نجمة\n\n"
                "أرسل السعر الجديد بالنجوم:"
            )
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
    return True
