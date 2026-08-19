"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

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
    """يبحث عن مستخدم بالـ ID أو بالـ username.

    يقبل:
    - Telegram ID رقمي
    - username مع أو بدون ``@``
    - رابط ``t.me/username`` أو ``https://t.me/username``

    البحث باليوزر غير حساس لحالة الأحرف، ويعيد صف المستخدم كـ dict أو None.
    """
    text = (text or "").strip()
    text = re.sub(r"^(?:https?://)?t\.me/", "", text, flags=re.IGNORECASE)
    text = text.strip().lstrip("@").strip()
    if not text:
        return None
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

def smm_services_list(panel: int = 1, force_refresh: bool = False):
    """يجلب قائمة خدمات الموقع، مع إمكانية إجبار تحديثها عند فحص الخدمات."""
    now = time.time()
    cached = _services_cache.get(panel)
    if cached and not force_refresh and now - cached[0] < _SERVICES_CACHE_TTL:
        return cached[1]

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
        logger.warning(f"⚠️ smm_services_list: رد غير متوقع من {site_name} (panel={panel}): {str(raw)[:300]}")
        return None
    _services_cache[panel] = (now, services)
    return services

def smm_service_info(service_id: int, panel: int = 1) -> dict:
    services = smm_services_list(panel=panel)
    if services is None:
        return {}
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
                WHERE prize_type IN ('telegram_number', 'telegram_number_code', 'telegram_number_stars')
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

# ────────────────────────────────────────────────────────────
# ضع هذا في نهاية ملف security.py
async def run_referral_tasks_job(context: ContextTypes.DEFAULT_TYPE):
    """مهمة الإحالة التلقائية (Placeholder)"""
    logger.info("⚠️ run_referral_tasks_job: الدالة موجودة لمنع انهيار البوت.")
