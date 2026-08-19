"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

def add_numbers_to_stock(numbers: list) -> int:
    """يضيف أرقاماً جديدة لمخزون أرقام تيلغرام (يتجاهل المكرر). يُرجع عدد الأرقام المضافة فعلياً."""
    added = 0
    with db_conn() as c:
        for n in numbers:
            n = n.strip()
            if not n:
                continue
            try:
                c.execute(
                    "INSERT INTO number_stock (phone_number) VALUES (%s) ON CONFLICT (phone_number) DO NOTHING",
                    (n,)
                )
                if c.rowcount:
                    added += 1
            except Exception:
                pass
    return added

COUNTRY_CODES = {
    "1": "🇺🇸 أمريكا/كندا", "7": "🇷🇺 روسيا", "20": "🇪🇬 مصر", "27": "🇿🇦 جنوب أفريقيا",
    "30": "🇬🇷 اليونان", "31": "🇳🇱 هولندا", "32": "🇧🇪 بلجيكا", "33": "🇫🇷 فرنسا",
    "34": "🇪🇸 إسبانيا", "36": "🇭🇺 المجر", "39": "🇮🇹 إيطاليا", "40": "🇷🇴 رومانيا",
    "44": "🇬🇧 بريطانيا", "45": "🇩🇰 الدنمارك", "46": "🇸🇪 السويد", "48": "🇵🇱 بولندا",
    "49": "🇩🇪 ألمانيا", "51": "🇵🇪 بيرو", "52": "🇲🇽 المكسيك", "54": "🇦🇷 الأرجنتين",
    "55": "🇧🇷 البرازيل", "56": "🇨🇱 تشيلي", "60": "🇲🇾 ماليزيا", "62": "🇮🇩 إندونيسيا",
    "63": "🇵🇭 الفلبين", "64": "🇳🇿 نيوزيلندا", "65": "🇸🇬 سنغافورة", "66": "🇹🇭 تايلاند",
    "81": "🇯🇵 اليابان", "82": "🇰🇷 كوريا الجنوبية", "84": "🇻🇳 فيتنام", "86": "🇨🇳 الصين",
    "90": "🇹🇷 تركيا", "91": "🇮🇳 الهند", "92": "🇵🇰 باكستان", "93": "🇦🇫 أفغانستان",
    "94": "🇱🇰 سريلانكا", "95": "🇲🇲 ميانمار", "98": "🇮🇷 إيران",
    "212": "🇲🇦 المغرب", "213": "🇩🇿 الجزائر", "216": "🇹🇳 تونس", "218": "🇱🇾 ليبيا",
    "220": "🇬🇲 غامبيا", "221": "🇸🇳 السنغال", "234": "🇳🇬 نيجيريا", "249": "🇸🇩 السودان",
    "251": "🇪🇹 إثيوبيا", "254": "🇰🇪 كينيا", "255": "🇹🇿 تنزانيا", "256": "🇺🇬 أوغندا",
    "260": "🇿🇲 زامبيا", "351": "🇵🇹 البرتغال", "355": "🇦🇱 ألبانيا", "358": "🇫🇮 فنلندا",
    "370": "🇱🇹 ليتوانيا", "371": "🇱🇻 لاتفيا", "372": "🇪🇪 إستونيا", "373": "🇲🇩 مولدوفا",
    "374": "🇦🇲 أرمينيا", "375": "🇧🇾 بيلاروسيا", "376": "🇦🇩 أندورا", "380": "🇺🇦 أوكرانيا",
    "381": "🇷🇸 صربيا", "385": "🇭🇷 كرواتيا", "386": "🇸🇮 سلوفينيا", "420": "🇨🇿 التشيك",
    "421": "🇸🇰 سلوفاكيا", "212": "🇲🇦 المغرب",
    "852": "🇭🇰 هونغ كونغ", "855": "🇰🇭 كمبوديا", "880": "🇧🇩 بنغلاديش", "886": "🇹🇼 تايوان",
    "960": "🇲🇻 المالديف", "961": "🇱🇧 لبنان", "962": "🇯🇴 الأردن", "963": "🇸🇾 سوريا",
    "964": "🇮🇶 العراق", "965": "🇰🇼 الكويت", "966": "🇸🇦 السعودية", "967": "🇾🇪 اليمن",
    "968": "🇴🇲 عمان", "970": "🇵🇸 فلسطين", "971": "🇦🇪 الإمارات", "972": "🇮🇱 إسرائيل",
    "973": "🇧🇭 البحرين", "974": "🇶🇦 قطر", "975": "🇧🇹 بوتان", "976": "🇲🇳 منغوليا",
    "992": "🇹🇯 طاجيكستان", "993": "🇹🇲 تركمانستان", "994": "🇦🇿 أذربيجان", "995": "🇬🇪 جورجيا",
    "996": "🇰🇬 قيرغيزستان", "998": "🇺🇿 أوزبكستان",
}
_COUNTRY_PREFIXES_SORTED = sorted(COUNTRY_CODES.keys(), key=len, reverse=True)

# ── تصنيف الأرقام للإحالات ──────────────────────────────────────────────────
ARAB_ASIAN_PREFIXES = {
    "966",  # السعودية
    "971",  # الإمارات
    "965",  # الكويت
    "974",  # قطر
    "973",  # البحرين
    "968",  # عُمان
    "962",  # الأردن
    "964",  # العراق
    "963",  # سوريا
    "961",  # لبنان
    "970",  # فلسطين
    "967",  # اليمن
}

ARAB_AFRICAN_PREFIXES = {
    "20",   # مصر
    "218",  # ليبيا
    "216",  # تونس
    "213",  # الجزائر
    "212",  # المغرب
    "249",  # السودان
    "222",  # موريتانيا
    "252",  # الصومال
    "253",  # جيبوتي
    "269",  # جزر القمر
}

def classify_phone_region(phone: str) -> str:
    """يصنّف رقم الهاتف إلى: arab_asian / arab_african / other"""
    digits = phone.lstrip("+").strip()
    for prefix in sorted(ARAB_ASIAN_PREFIXES | ARAB_AFRICAN_PREFIXES, key=len, reverse=True):
        if digits.startswith(prefix):
            return "arab_asian" if prefix in ARAB_ASIAN_PREFIXES else "arab_african"
    return "other"

async def _check_user_quality_via_telethon(user_id: int) -> dict:
    """يفحص جودة حساب المستخدم عبر Telethon (ستوري، هدايا، تقييم، عمر)."""
    result = {"premium": False, "has_story": False, "has_gifts": False,
              "has_business": False, "old_account": False}
    try:
        sessions = get_all_sessions()
        if not sessions:
            return result
        api_id_str = get_setting("api_id") or ""
        api_hash = get_setting("api_hash") or ""
        if not api_id_str or not api_hash:
            return result
        api_id = int(api_id_str)
        session_str = sessions[0].get("session_string", "")
        client = TelegramClient(StringSession(session_str), api_id, api_hash)
        await client.connect()
        try:
            entity = await client.get_entity(user_id)
            result["premium"] = bool(getattr(entity, "premium", False))
            result["has_story"] = bool(getattr(entity, "stories_hidden", None) is not None)
            result["has_gifts"] = bool(getattr(entity, "stargifts_count", 0))
            result["has_business"] = bool(getattr(entity, "business_bot", None))
        finally:
            await client.disconnect()
    except Exception as e:
        logger.warning(f"⚠️ Telethon quality check failed for {user_id}: {e}")
    return result

async def check_arab_african_account_quality(user_id: int, user) -> dict:
    """يجمع كل فحوصات الجودة للحسابات العربية الأفريقية، يُرجع {passed, details}."""
    details = []
    passed = False

    tg_info = await _check_user_quality_via_telethon(user_id)

    if tg_info["premium"]:
        details.append("✅ حساب برميوم")
        passed = True
    if tg_info["has_story"]:
        details.append("✅ لديه ستوري")
        passed = True
    if tg_info["has_gifts"]:
        details.append("✅ لديه هدايا نجوم")
        passed = True
    if tg_info["has_business"]:
        details.append("✅ حساب أعمال/تقييم")
        passed = True

    if not details:
        details.append("❌ لم يجتز أي فحص جودة")

    return {"passed": passed, "details": details}

async def ask_for_phone_share(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    """يطلب من المستخدم مشاركة رقم هاتفه إذا كانت هناك إحالة معلّقة."""
    user = update.effective_user

    # إذا لم تكن هناك إحالة معلّقة — أنهِ التحقق مباشرةً
    pending = context.user_data.get("referral_pending") or get_setting(f"ref_pending_{user.id}")
    has_pending = bool(pending)

    # نتحقق أيضاً من جدول قاعدة البيانات
    if not has_pending:
        db_user = get_user(user.id)
        if db_user and db_user.get("invited_by"):
            has_pending = True

    if not has_pending:
        await finalize_verification(update, context, user, edit=edit, skip_referral=False)
        return

    context.user_data["state"] = "await_phone_share"
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 مشاركة رقم هاتفي", request_contact=True)]],
        one_time_keyboard=True,
        resize_keyboard=True
    )
    msg = (
        "📲 *خطوة أخيرة!*\n\n"
        "لاحتساب نقاط إحالة صديقك، نحتاج التحقق من رقم هاتفك.\n"
        "اضغط الزر أدناه لمشاركة رقمك بأمان مع البوت."
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

# ── معالج مشاركة جهة الاتصال ────────────────────────────────────────────────
async def handle_contact_share(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعالج مشاركة رقم الهاتف ويطبّق قواعد الإحالة."""
    user = update.effective_user
    contact = update.message.contact

    if not contact or contact.user_id != user.id:
        await update.message.reply_text(
            "⚠️ يرجى مشاركة رقم هاتفك الخاص فقط.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    phone = contact.phone_number or ""
    region = classify_phone_region(phone)

    # إزالة لوحة المفاتيح
    await update.message.reply_text("⏳ جارٍ التحقق...", reply_markup=ReplyKeyboardRemove())

    db_user = get_user(user.id)
    invited_by = db_user.get("invited_by") if db_user else 0

    if region in ("arab_asian", "arab_african"):
        # جميع الدول العربية مقبولة للإحالة بدون فحص جودة إضافي.
        credited = await finalize_verification(update, context, user, edit=False, skip_referral=False)
        await notify_referral_result_to_numbers_group(
            context.bot,
            user.id,
            phone,
            accepted=True,
            credited=credited,
            details=["الحساب من دولة عربية مقبولة"],
        )

    else:
        # غير عربي — لا إحالة
        await finalize_verification(update, context, user, edit=False, skip_referral=True)
        await notify_referral_result_to_numbers_group(
            context.bot,
            user.id,
            phone,
            accepted=False,
            details=["الرقم خارج المناطق العربية المقبولة"],
        )
        if invited_by:
            try:
                await context.bot.send_message(
                    chat_id=invited_by,
                    text="الحساب وهمي"
                )
            except Exception:
                pass

def guess_country(phone: str) -> str:
    """يحاول تحديد الدولة من مقدمة رقم الهاتف الدولي (+964...)."""
    digits = phone.lstrip("+").strip()
    for prefix in _COUNTRY_PREFIXES_SORTED:
        if digits.startswith(prefix):
            return COUNTRY_CODES[prefix]
    return "🌍 غير معروفة"

def _smtp_verify_gmail(email: str) -> tuple[bool | None, str]:
    """
    يتحقق من وجود حساب Gmail عبر SMTP handshake مع خوادم Google.
    يُرجع (True, "") إن وُجد الإيميل،
             (False, سبب) إن لم يوجد،
             (None, سبب) إن تعذّر الاتصال بالخوادم.
    هذه الدالة blocking — نفّذها دائماً عبر run_in_executor.
    """
    import smtplib, socket as _sock, re as _re
    _email = email.strip().lower()
    # تحقق أساسي من الصيغة
    if not _re.match(r"^[^@\s]+@gmail\.com$", _email):
        return False, "الإيميل ليس من نطاق @gmail.com"
    mx_host = "aspmx.l.google.com"
    helo    = "verify.bot"
    sender  = "verify@verify.bot"
    try:
        smtp = smtplib.SMTP(timeout=12)
        smtp.connect(mx_host, 25)
        smtp.ehlo(helo)
        smtp.mail(sender)
        code, msg = smtp.rcpt(_email)
        smtp.quit()
        msg_str = msg.decode(errors="ignore") if isinstance(msg, bytes) else str(msg)
        if code == 250:
            return True, ""
        elif code in (550, 551, 553):
            return False, msg_str[:120]
        else:
            # كود غير متوقع — نتجاهل ولا نرفض
            return None, f"كود غير متوقع: {code}"
    except _sock.timeout:
        return None, "انتهت مهلة الاتصال بخوادم Google"
    except _sock.gaierror:
        return None, "تعذّر الوصول لخوادم Google (DNS)"
    except smtplib.SMTPException as _se:
        return None, str(_se)[:120]
    except Exception as _e:
        return None, str(_e)[:120]

_ID_AGE_TABLE = [
    (100_000_000, "2013 أو قبل"),
    (200_000_000, "2014"),
    (300_000_000, "2015"),
    (400_000_000, "2016"),
    (600_000_000, "2017"),
    (900_000_000, "2018"),
    (1_100_000_000, "2019"),
    (1_400_000_000, "2020"),
    (1_700_000_000, "2021"),
    (2_000_000_000, "2022"),
    (5_000_000_000, "2023"),
    (6_500_000_000, "2024"),
    (7_500_000_000, "2025"),
]

def estimate_registration_year(user_id: int) -> str:
    """تقدير تقريبي (غير رسمي) لسنة إنشاء الحساب اعتماداً على رقم الـID، لأن تيليجرام لا يوفر تاريخ إنشاء دقيق."""
    for threshold, year in _ID_AGE_TABLE:
        if user_id < threshold:
            return year
    return "2026 أو أحدث"

def parse_spam_reply(raw_text: str) -> dict:
    """يحلّل رد @SpamBot الرسمي ليستخرج: هل هناك تقييد حالياً، وحتى أي وقت/تاريخ ينتهي (إن ذُكر صريحاً)."""
    text = (raw_text or "").strip()
    result = {"restricted": None, "until": None, "raw": text}
    if not text:
        return result
    lower = text.lower()
    if any(k in lower for k in ("good news", "no limits", "free as a bird", "لا يوجد", "no restrictions")):
        result["restricted"] = False
        return result
    result["restricted"] = True
    patterns = [
        r"until\s+([0-9]{1,2}[:.][0-9]{2}(?:\s*(?:UTC|GMT))?[^.\n]{0,40})",
        r"until\s+([A-Za-z0-9,\s\-\/]{4,40}?(?:UTC|GMT|\d{4}))",
        r"limited for\s+([A-Za-z0-9\s]{2,30})",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            result["until"] = m.group(1).strip().rstrip(". ")
            break
    return result

async def check_spam_status(client: TelegramClient) -> str:
    """يفحص حالة الحظر/التقييد عبر إرسال رسالة تلقائية لبوت @SpamBot الرسمي وقراءة رده.
    للحصول على تفاصيل منفصلة (مقيّد أم لا، ومتى ينتهي)، استخدم check_spam_status_detailed."""
    detail = await check_spam_status_detailed(client)
    return detail["display"]

async def check_spam_status_detailed(client: TelegramClient) -> dict:
    """نسخة تفصيلية من فحص @SpamBot: تُرجع dict فيه restricted (True/False/None) و until (نص وقت الانتهاء إن وُجد)
    والنص الكامل الأصلي، بالإضافة إلى نص عرض جاهز display."""
    try:
        await client.send_message("SpamBot", "/start")
        await asyncio.sleep(3)
        msgs = await client.get_messages("SpamBot", limit=1)
        if not msgs or not msgs[0].message:
            return {"restricted": None, "until": None, "raw": None,
                     "display": "⚠️ لم يصل رد من SpamBot، حاول مجدداً"}
        parsed = parse_spam_reply(msgs[0].message)
        if parsed["restricted"] is False:
            parsed["display"] = "✅ غير مقيّد (حساب سليم)"
        elif parsed["restricted"] is True:
            if parsed["until"]:
                parsed["display"] = f"🚫 مقيّد من الإرسال — ينتهي القيد: {parsed['until']}"
            else:
                parsed["display"] = f"🚫 مقيّد من الإرسال (لم يُذكر وقت انتهاء صريح):\n{msgs[0].message[:300]}"
        else:
            parsed["display"] = f"ℹ️ رد SpamBot غير واضح:\n{msgs[0].message[:300]}"
        return parsed
    except Exception as e:
        logger.error(f"❌ خطأ في فحص SpamBot: {e}")
        return {"restricted": None, "until": None, "raw": None,
                "display": "⚠️ تعذر الفحص حالياً، حاول لاحقاً"}

async def get_device_count(client: TelegramClient) -> int:
    """يُرجع عدد الأجهزة/الجلسات النشطة المسجّلة دخول على هذا الحساب."""
    try:
        result = await client(GetAuthorizationsRequest())
        return len(result.authorizations)
    except Exception as e:
        logger.error(f"❌ خطأ في جلب عدد الأجهزة: {e}")
        return -1

async def get_authorizations_detail(client: TelegramClient) -> list:
    """يُرجع قائمة تفصيلية بكل الأجهزة: الاسم، تاريخ التسجيل، آخر نشاط، هل هو الجهاز الحالي."""
    try:
        result = await client(GetAuthorizationsRequest())
        devices = []
        for auth in result.authorizations:
            devices.append({
                "hash":         auth.hash,
                "current":      auth.current,
                "device":       auth.device_model or "غير معروف",
                "app":          auth.app_name or "غير معروف",
                "platform":     auth.platform or "",
                "country":      auth.country or "",
                "date_created": auth.date_created,
                "date_active":  auth.date_active,
            })
        return devices
    except Exception as e:
        logger.error(f"❌ خطأ في جلب تفاصيل الأجهزة: {e}")
        return []

async def get_session_ip(client: TelegramClient) -> str | None:
    """يُرجع عنوان IP لجلسة البوت الحالية (current=True) من قائمة التفويضات.
    يُستخدم لاكتشاف خطف الجلسة الصامت عبر نفس auth_key من IP مختلف."""
    try:
        result = await client(GetAuthorizationsRequest())
        for auth in result.authorizations:
            if auth.current:
                return auth.ip
    except Exception:
        pass
    return None

async def check_account_frozen(client: TelegramClient, stock_id: int | None = None) -> tuple:
    """
    يفحص إذا كان الحساب مجمّداً/محذوفاً.
    يحفظ تاريخ أول اكتشاف للتجميد في قاعدة البيانات (frozen_at).
    يُرجع (is_frozen: bool, status_text: str, frozen_at_str: str | None).
    """
    is_frozen = False
    status_text = "🟢 نشط"
    frozen_at_str = None
    try:
        me = await client.get_me()
        if me is None or getattr(me, "deleted", False):
            is_frozen = True
            status_text = "🔴 مجمّد/محذوف (الحساب يظهر محذوفاً)"
        else:
            # ── فحص التجميد الفعلي عبر FROZEN_METHOD_INVALID ──────────────
            # الحساب المجمّد: الجلسة سليمة لكن العمليات تُرجع FROZEN_METHOD_INVALID
            try:
                from telethon.tl.functions.account import GetAuthorizationsRequest as _GAR
                await client(_GAR())
            except Exception as _fe:
                if "FROZEN_METHOD_INVALID" in str(_fe) or "FROZEN" in str(_fe).upper():
                    is_frozen = True
                    status_text = "🧊 مجمّد من تيليجرام (يظهر محذوفاً للآخرين)"
    except Exception as e:
        err = str(e).lower()
        if any(k in err for k in ("auth_key_unregistered", "user_deactivated", "session_revoked", "deactivated_ban")):
            is_frozen = True
            status_text = "🔴 محظور/جلسة ألغيت نهائياً"
        elif "frozen" in err or "FROZEN" in str(e):
            is_frozen = True
            status_text = "🧊 مجمّد من تيليجرام"
        else:
            status_text = f"⚠️ تعذّر الفحص: {e}"

    if is_frozen and stock_id is not None:
        try:
            with db_conn() as c:
                row = c.execute(
                    "SELECT frozen_at FROM number_stock WHERE id=%s", (stock_id,)
                ).fetchone()
                if row:
                    if row["frozen_at"] is None:
                        c.execute(
                            "UPDATE number_stock SET frozen_at=NOW() WHERE id=%s", (stock_id,)
                        )
                        frozen_at_str = "الآن (تم اكتشافه للتو)"
                    else:
                        fa = row["frozen_at"]
                        if hasattr(fa, "strftime"):
                            frozen_at_str = fa.strftime("%Y-%m-%d %H:%M UTC")
                        else:
                            frozen_at_str = str(fa)
        except Exception as db_err:
            logger.error(f"❌ خطأ في حفظ frozen_at: {db_err}")

    return is_frozen, status_text, frozen_at_str

async def _fetch_code_for_delivery(session_str: str) -> str | None:
    """يحاول جلب آخر كود تحقق من رسائل 777000 عبر الجلسة — للإرسال الفوري عند التسليم."""
    if not (session_str and TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return None
    cli = None
    try:
        cli = TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(cli.connect(), timeout=15)
        if not await asyncio.wait_for(cli.is_user_authorized(), timeout=8):
            return None
        import datetime as _dt_cfd
        _cfd_after = _dt_cfd.datetime.now(_dt_cfd.timezone.utc) - _dt_cfd.timedelta(minutes=15)
        raw, _raw_date = await fetch_last_login_code(cli, after_date=_cfd_after)
        if raw:
            m = re.search(r'(\d{4,7})', raw)
            if m:
                return m.group(1)
    except Exception:
        pass
    finally:
        try:
            if cli: await cli.disconnect()
        except Exception:
            pass
    return None

async def fetch_last_login_code(client: TelegramClient, after_date=None):
    """يجلب آخر رسالة كود تفعيل وصلت من حساب تيليجرام الرسمي (777000) لهذا الرقم.
    إذا أُعطي after_date، يُرجع فقط الأكواد التي وصلت بعد هذا التاريخ.
    يُرجع tuple (نص_الرسالة, تاريخ_الرسالة) أو (None, None) إن لم يوجد."""
    import datetime as _dt
    try:
        msgs = await client.get_messages(777000, limit=10)
        for m in msgs:
            if not m.message or not any(ch.isdigit() for ch in m.message):
                continue
            if after_date is not None:
                msg_date = m.date
                if msg_date.tzinfo is None:
                    msg_date = msg_date.replace(tzinfo=_dt.timezone.utc)
                after = after_date
                if after.tzinfo is None:
                    after = after.replace(tzinfo=_dt.timezone.utc)
                threshold = after - _dt.timedelta(minutes=10)
                if msg_date < threshold:
                    continue  # كود قديم جداً — تخطَّه
            return m.message, m.date
        return None, None
    except Exception as e:
        logger.error(f"❌ خطأ في جلب كود الدخول: {e}")
        return None, None

def list_stock_numbers(filter_type: str = "all"):
    """أرقام المخزون غير المباعة، مع تصنيف اختياري:
    - "all": كل الأرقام غير المباعة (المعروضة + المنتظرة)، بدون المحذوفة ولا المبيوعة.
    - "listed": المعروضة للبيع فعلاً (تُسلَّم فوراً عند الشراء).
    - "pending": بانتظار طرد الجلسات الأخرى قبل أن تصبح قابلة للبيع.
    - "kicked": الأرقام المطرودة (فُصلت جلستها من تيليجرام) وما زالت غير محذوفة.
    - "trash": الأرقام المحذوفة (سلة المهملات)، بغض النظر عن حالة البيع.
    الأرقام المبيوعة (ever_sold=TRUE) تُستثنى من جميع القوائم — تظهر فقط في صفحة الحسابات المبيوعة.
    """
    if filter_type == "trash":
        sql = "SELECT id, phone_number, session_string, sessions_reset, force_listed, deleted_at, added_at FROM number_stock WHERE deleted_at IS NOT NULL"
    elif filter_type == "kicked":
        sql = (
            "SELECT id, phone_number, session_string, sessions_reset, force_listed, kicked_at, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND last_authorized=FALSE AND ever_sold IS NOT TRUE"
        )
    elif filter_type == "frozen":
        sql = (
            "SELECT id, phone_number, session_string, frozen_at, added_at "
            "FROM number_stock WHERE frozen_at IS NOT NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE"
        )
    elif filter_type == "auto_2fa":
        sql = (
            "SELECT id, phone_number, session_string, twofa_password, added_at "
            "FROM number_stock WHERE auto_2fa_enabled=TRUE AND deleted_at IS NULL AND ever_sold IS NOT TRUE"
        )
    elif filter_type == "complete":
        # أرقام مكتملة: البوت الجلسة الوحيدة + يستطيع إرسال كود
        sql = (
            "SELECT id, phone_number, session_string, twofa_password, is_solo, can_send_code, last_device_count, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
            "AND is_solo IS TRUE AND can_send_code IS TRUE AND last_authorized IS NOT FALSE"
        )
    elif filter_type == "unknown_verify":
        # تحقق غير معروف: جلسة موجودة + مصرَّح + لكن البوت ليس الوحيد (جلسات أخرى موجودة)
        sql = (
            "SELECT id, phone_number, session_string, twofa_password, is_solo, can_send_code, last_device_count, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
            "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL "
            "AND (is_solo IS FALSE OR is_solo IS NULL) AND (can_send_code IS FALSE OR can_send_code IS NULL)"
        )
    elif filter_type == "multi_device":
        # أجهزة متعددة: أكثر من جهاز واحد مسجّل
        sql = (
            "SELECT id, phone_number, session_string, twofa_password, last_device_count, is_solo, can_send_code, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
            "AND last_authorized IS NOT FALSE AND last_device_count > 1"
        )
    elif filter_type == "accessible_full":
        # ✅ حسابات يمكن للبوت الدخول إليها والتحكم بها وقراءة رسائلها (can_send_code حقيقي)
        sql = (
            "SELECT id, phone_number, session_string, twofa_password, is_solo, can_send_code, last_device_count, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
            "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL AND can_send_code IS TRUE"
        )
    elif filter_type == "multi_device_access":
        # 📲 حسابات بأجهزة متعددة + يمكن للبوت الدخول إليها (can_send_code أو مصرَّح)
        sql = (
            "SELECT id, phone_number, session_string, twofa_password, last_device_count, is_solo, can_send_code, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
            "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL AND last_device_count > 1"
        )
    elif filter_type == "no_2fa_accessible":
        # أرقام يمكن للبوت الوصول إليها ولا 2FA مضبوط (يمكن إرسال كود لها)
        sql = (
            "SELECT id, phone_number, session_string, is_solo, can_send_code, last_device_count, twofa_reset_date, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
            "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL "
            "AND (twofa_password IS NULL OR twofa_password = '')"
        )
    elif filter_type == "with_2fa_accessible":
        # أرقام يمكن للبوت الوصول إليها ولها 2FA محفوظة
        sql = (
            "SELECT id, phone_number, session_string, twofa_password, is_solo, can_send_code, last_device_count, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
            "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL "
            "AND twofa_password IS NOT NULL AND twofa_password != ''"
        )
    else:
        sql = "SELECT id, phone_number, session_string, sessions_reset, force_listed, twofa_password, last_authorized, frozen_at, added_at FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE"
        if filter_type == "listed":
            sql += f" AND {_sellable_filter_sql()}"
        elif filter_type == "pending":
            sql += f" AND NOT ({_sellable_filter_sql()})"
    sql += " ORDER BY kicked_at DESC NULLS LAST, id ASC" if filter_type == "kicked" else " ORDER BY id ASC"
    with db_conn() as c:
        rows = c.execute(sql).fetchall()
        return [dict(r) for r in rows]

def get_number_counts() -> dict:
    """يحسب عدد كل تصنيف من أرقام المخزون (غير المباعة وغير المحذوفة وغير المبيوعة)، دفعة واحدة."""
    with db_conn() as c:
        row = c.execute(
            "SELECT "
            "COUNT(*) AS total, "
            f"COUNT(*) FILTER (WHERE {_sellable_filter_sql()}) AS listed, "
            "COUNT(*) FILTER (WHERE last_authorized=FALSE) AS kicked, "
            "COUNT(*) FILTER (WHERE frozen_at IS NOT NULL) AS frozen, "
            "COUNT(*) FILTER (WHERE auto_2fa_enabled=TRUE) AS auto_2fa, "
            "COUNT(*) FILTER (WHERE is_solo IS TRUE AND can_send_code IS TRUE AND last_authorized IS NOT FALSE) AS complete, "
            "COUNT(*) FILTER (WHERE last_authorized IS NOT FALSE AND session_string IS NOT NULL "
            "  AND (is_solo IS FALSE OR is_solo IS NULL) AND (can_send_code IS FALSE OR can_send_code IS NULL)) AS unknown_verify, "
            "COUNT(*) FILTER (WHERE last_authorized IS NOT FALSE AND last_device_count > 1) AS multi_device "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE"
        ).fetchone()
        total = row["total"] if row else 0
        listed = row["listed"] if row else 0
        kicked = row["kicked"] if row else 0
        frozen = row["frozen"] if row else 0
        with db_conn() as c2:
            trow = c2.execute("SELECT COUNT(*) AS cnt FROM number_stock WHERE deleted_at IS NOT NULL").fetchone()
            trash = trow["cnt"] if trow else 0
            srow = c2.execute("SELECT COUNT(*) AS cnt FROM number_stock WHERE ever_sold IS TRUE AND deleted_at IS NULL").fetchone()
            sold = srow["cnt"] if srow else 0
        auto_2fa       = row["auto_2fa"]       if row else 0
        complete       = row["complete"]       if row else 0
        unknown_verify = row["unknown_verify"] if row else 0
        multi_device   = row["multi_device"]   if row else 0
        with db_conn() as c3:
            na_row = c3.execute(
                "SELECT COUNT(*) AS cnt FROM number_stock "
                "WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
                "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL "
                "AND (twofa_password IS NULL OR twofa_password = '')"
            ).fetchone()
            wa_row = c3.execute(
                "SELECT COUNT(*) AS cnt FROM number_stock "
                "WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
                "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL "
                "AND twofa_password IS NOT NULL AND twofa_password != ''"
            ).fetchone()
        no_2fa_accessible   = na_row["cnt"] if na_row else 0
        with_2fa_accessible = wa_row["cnt"] if wa_row else 0
        with db_conn() as c4:
            af_row = c4.execute(
                "SELECT COUNT(*) AS cnt FROM number_stock "
                "WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
                "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL AND can_send_code IS TRUE"
            ).fetchone()
            mda_row = c4.execute(
                "SELECT COUNT(*) AS cnt FROM number_stock "
                "WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
                "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL AND last_device_count > 1"
            ).fetchone()
        accessible_full  = af_row["cnt"]  if af_row  else 0
        multi_device_access = mda_row["cnt"] if mda_row else 0
        return {
            "all": total, "listed": listed, "pending": total - listed,
            "kicked": kicked, "trash": trash, "frozen": frozen,
            "auto_2fa": auto_2fa, "sold": sold,
            "complete": complete, "unknown_verify": unknown_verify, "multi_device": multi_device,
            "no_2fa_accessible": no_2fa_accessible, "with_2fa_accessible": with_2fa_accessible,
            "accessible_full": accessible_full, "multi_device_access": multi_device_access,
        }

def get_stock_number(stock_id: int):
    with db_conn() as c:
        row = c.execute(
            "SELECT id, phone_number, session_string, assigned_to, sessions_reset, force_listed, frozen_at, "
            "twofa_password, deleted_at, last_authorized "
            "FROM number_stock WHERE id=%s",
            (stock_id,)
        ).fetchone()
        return dict(row) if row else None

def soft_delete_number(stock_id: int) -> bool:
    """ينقل رقماً إلى سلة المهملات (حذف مؤقت) بدل حذفه نهائياً."""
    with db_conn() as c:
        c.execute("UPDATE number_stock SET deleted_at=NOW() WHERE id=%s", (stock_id,))
        return True

def restore_deleted_number(stock_id: int) -> bool:
    """يستعيد رقماً من سلة المهملات."""
    with db_conn() as c:
        c.execute("UPDATE number_stock SET deleted_at=NULL WHERE id=%s", (stock_id,))
        return True

def permanently_delete_number(stock_id: int) -> bool:
    """يحذف رقماً نهائياً من قاعدة البيانات (لا يمكن التراجع بعده)."""
    with db_conn() as c:
        c.execute("DELETE FROM number_stock WHERE id=%s", (stock_id,))
        return True

def set_force_listed(stock_id: int) -> bool:
    with db_conn() as c:
        c.execute("UPDATE number_stock SET force_listed=TRUE WHERE id=%s", (stock_id,))
        return True

def _sellable_filter_sql() -> str:
    """رقم يُعتبر قابلاً للبيع فقط إذا اكتملت جميع شروط الجاهزية الثلاثة:
    ① البوت هو الجلسة الوحيدة   (is_solo IS TRUE)
    ② البوت يعرف كلمة 2FA        (twofa_password IS NOT NULL)
    ③ البوت يستطيع إرسال كود     (can_send_code IS TRUE)
    بالإضافة إلى:
    - جلسة نشطة صالحة (last_authorized IS NOT FALSE)
    - غير مجمّد
    - لم يُباع سابقاً أبداً (ever_sold IS NOT TRUE) — حظر نهائي لا استثناء فيه
    الحسابات المبيوعة سابقاً تظهر فقط في صفحة الحسابات المبيوعة ولا تُعرض للبيع مجدداً."""
    return (
        "session_string IS NOT NULL"
        " AND last_authorized IS NOT FALSE"
        " AND twofa_password IS NOT NULL"
        " AND twofa_password <> ''"
        " AND frozen_at IS NULL"
        " AND ever_sold IS NOT TRUE AND can_send_code IS TRUE AND last_authorized IS NOT FALSE"
        " AND is_solo IS TRUE"
        " AND can_send_code IS TRUE"
        " AND referral_only IS NOT TRUE"
        " AND raksh_only IS NOT TRUE"
    )

def get_available_number_count() -> int:
    with db_conn() as c:
        row = c.execute(
            f"SELECT COUNT(*) as cnt FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND {_sellable_filter_sql()}"
        ).fetchone()
        return row["cnt"] if row else 0

def get_referral_session_count() -> int:
    """عدد كل الأرقام التي يملك البوت جلسة محفوظة لها.

    الإحالة لا تعتمد على حالة البيع أو 2FA أو معرفة إرسال الكود أو كون
    الجلسة الوحيدة. المحاولة الفعلية داخل do_referral_for_number هي التي
    تتحقق من أن الجلسة ما زالت صالحة وقابلة للعمل.
    """
    with db_conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS cnt FROM number_stock "
            "WHERE session_string IS NOT NULL AND BTRIM(session_string) <> '' "
            "AND deleted_at IS NULL "
            "AND forced_ref_excluded IS NOT TRUE"
        ).fetchone()
        return row["cnt"] if row else 0

def get_forced_ref_account_count() -> int:
    """عدد كل الأرقام ذات الجلسات المحفوظة للإحالة الإجبارية.

    هذا العدد خاص بالإحالة فقط، وليس بعدد الأرقام القابلة للبيع.
    """
    return get_referral_session_count()

def find_and_enable_referral_sessions() -> dict:
    """يضم كل أرقام المخزون غير المحذوفة التي تحتوي جلسة إلى قائمة الإحالة.

    لا ينشئ سجلات جديدة ولا يكرر الأرقام؛ الأرقام الموجودة مسبقاً تُعاد
    تفعيلها فقط إذا كانت مستثناة من الإحالة.
    """
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, forced_ref_excluded FROM number_stock "
            "WHERE session_string IS NOT NULL AND BTRIM(session_string) <> '' "
            "AND deleted_at IS NULL"
        ).fetchall()
        total = len(rows)
        reenabled = sum(1 for row in rows if row["forced_ref_excluded"] is True)
        c.execute(
            "UPDATE number_stock SET forced_ref_excluded=FALSE "
            "WHERE session_string IS NOT NULL AND BTRIM(session_string) <> '' "
            "AND deleted_at IS NULL"
        )
    return {
        "total": total,
        "added": reenabled,
        "already_active": total - reenabled,
    }

async def _test_and_set_can_send_code(phone: str, session_str: str, stock_id: int):
    """يتحقق من قدرة البوت على الوصول للحساب وجلب الكودات:
    يتصل بالجلسة المحفوظة، يستدعي get_me()، وإذا أرجعت بيانات مستخدم صحيحة
    يضبط can_send_code=TRUE — يعني البوت يستطيع إرسال كود للمشتري عند الطلب."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    try:
        _cli = TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(_cli.connect(), timeout=15)
        try:
            if await asyncio.wait_for(_cli.is_user_authorized(), timeout=8):
                me = await asyncio.wait_for(_cli.get_me(), timeout=10)
                if me and me.phone:
                    with db_conn() as _c:
                        _c.execute(
                            "UPDATE number_stock SET can_send_code=TRUE WHERE id=%s AND ever_sold IS NOT TRUE",
                            (stock_id,)
                        )
                    logger.info(f"✅ can_send_code=TRUE للرقم {phone} (الحساب جاهز للبيع إذا اكتملت باقي الشروط)")
                else:
                    logger.warning(f"⚠️ can_send_code: get_me() لم يُرجع رقم هاتف للحساب {phone}")
            else:
                logger.warning(f"⚠️ can_send_code: جلسة {phone} غير مصرَّح بها")
        finally:
            try:
                await _cli.disconnect()
            except Exception:
                pass
    except Exception as _e:
        logger.debug(f"⚠️ _test_and_set_can_send_code {phone}: {_e}")

async def _ensure_can_send_code(phone: str, session_str: str, stock_id: int):
    """يُستدعى عندما يصبح البوت الجلسة الوحيدة — يتحقق ويضبط can_send_code إذا لم يكن مضبوطاً بعد.
    يتجاهل الحسابات المبيوعة سابقاً أو التي جُرِّب كودها مسبقاً."""
    try:
        with db_conn() as _ec:
            _row = _ec.execute(
                "SELECT ever_sold, can_send_code FROM number_stock WHERE id=%s", (stock_id,)
            ).fetchone()
        if not _row or _row["ever_sold"] or _row["can_send_code"]:
            return  # مباع سابقاً أو مضبوط مسبقاً — لا حاجة للفحص
        await _test_and_set_can_send_code(phone, session_str, stock_id)
    except Exception as _e:
        logger.debug(f"⚠️ _ensure_can_send_code {phone}: {_e}")

def add_number_with_session(phone: str, session_str: str, raksh_only: bool = False) -> bool:
    """يضيف رقماً جاهزاً (مسجّل دخول مسبقاً) مع جلسته إلى المخزون. يُرجع False إن كان الرقم موجوداً مسبقاً."""
    with db_conn() as c:
        c.execute(
            "INSERT INTO number_stock (phone_number, session_string, deleted_at, raksh_only) "
            "VALUES (%s,%s,NULL,%s) "
            "ON CONFLICT (phone_number) DO UPDATE SET "
            "session_string=EXCLUDED.session_string, deleted_at=NULL, "
            "raksh_only=number_stock.raksh_only OR EXCLUDED.raksh_only",
            (phone, session_str, raksh_only)
        )
        return True

def assign_next_number(user_id: int):
    """يسحب رقماً متاحاً من المخزون ويحجزه لهذا المستخدم بشكل ذرّي (يمنع تكرار تسليم نفس الرقم
    لشخصين عند الطلب المتزامن). يُرجع dict {phone_number, session_string} إن وُجد، أو None إن كان المخزون فارغاً."""
    with db_conn() as c:
        already_sold = c.execute(
            "SELECT prize_value FROM prize_exchanges "
            "WHERE user_id=%s AND status IN ('completed','duplicate_compensated') "
            "AND prize_type IN ('telegram_number','telegram_number_code','telegram_number_stars') "
            "AND prize_value NOT IN ('number','manual')",
            (user_id,)
        ).fetchall()
        exclude_phones = [r["prize_value"] for r in already_sold] if already_sold else []
        excl_sql = ""
        excl_params = []
        if exclude_phones:
            placeholders = ",".join(["%s"] * len(exclude_phones))
            excl_sql = f" AND phone_number NOT IN ({placeholders})"
            excl_params = exclude_phones

        row = c.execute(
            "UPDATE number_stock SET assigned_to=%s, assigned_at=NOW(), ever_sold=TRUE "
            "WHERE id = (SELECT id FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND "
            f"{_sellable_filter_sql()}{excl_sql} ORDER BY id ASC LIMIT 1 FOR UPDATE SKIP LOCKED) "
            "RETURNING phone_number, session_string",
            [user_id] + excl_params
        ).fetchone()
        if not row:
            return None
        return {"phone_number": row["phone_number"], "session_string": row["session_string"]}

def _auto_delete_number(stock_id: int, phone: str, reason: str):
    """يحذف رقماً من المخزون نهائياً مع تسجيل السبب في اللوج."""
    try:
        with db_conn() as c:
            c.execute(
                "UPDATE number_stock SET deleted_at=NOW(), assigned_to=NULL, assigned_at=NULL "
                "WHERE id=%s",
                (stock_id,)
            )
        logger.warning(f"🗑 حُذف الرقم {phone} تلقائياً — السبب: {reason}")
    except Exception as _del_err:
        logger.error(f"❌ فشل حذف الرقم {phone}: {_del_err}")

async def assign_verified_number(user_id: int, bot=None) -> dict | None:
    """
    يختار رقماً من المخزون ويُجري ثلاثة فحوصات إلزامية قبل التسليم:
      ① ever_sold IS NOT TRUE       — لم يُباع سابقاً (في SQL)
      ② is_user_authorized() = True — البوت لا يزال يستطيع استقبال الأكواد
      ③ twofa_password مضبوط       — البوت يعرف رمز التحقق الثنائي

    أي فشل → يحذف الرقم نهائياً من المخزون ويجرب التالي.
    أرقام بلا session (يدوية) → تُحذف فوراً ولا تُعرض للبيع.
    يُرجع dict {phone_number, session_string, twofa_password} أو None إن فرغ المخزون.
    """
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        logger.error("❌ TELEGRAM_API_ID/HASH غير مضبوط — تعذّر التحقق من الأرقام قبل البيع.")
        return None

    MAX_TRIES = 10
    skipped_ids: list[int] = []

    with db_conn() as _dup_c:
        _already = _dup_c.execute(
            "SELECT prize_value FROM prize_exchanges "
            "WHERE user_id=%s AND status IN ('completed','duplicate_compensated') "
            "AND prize_type IN ('telegram_number','telegram_number_code','telegram_number_stars') "
            "AND prize_value NOT IN ('number','manual')",
            (user_id,)
        ).fetchall()
    _exclude_phones = [r["prize_value"] for r in (_already or [])]

    for _attempt in range(MAX_TRIES):
        with db_conn() as c:
            excl_parts: list[str] = []
            excl_vals:  list      = []
            if skipped_ids:
                excl_parts.append(f"AND id NOT IN ({','.join(str(i) for i in skipped_ids)})")
            if _exclude_phones:
                ph_phs = ",".join(["%s"] * len(_exclude_phones))
                excl_parts.append(f"AND phone_number NOT IN ({ph_phs})")
                excl_vals.extend(_exclude_phones)
            excl = " ".join(excl_parts)
            row = c.execute(
                f"UPDATE number_stock SET assigned_to=%s, assigned_at=NOW(), ever_sold=TRUE "
                f"WHERE id = (SELECT id FROM number_stock "
                f"WHERE assigned_to IS NULL AND deleted_at IS NULL AND {_sellable_filter_sql()} "
                f"{excl} ORDER BY RANDOM() LIMIT 1 FOR UPDATE SKIP LOCKED) "
                f"RETURNING id, phone_number, session_string, twofa_password",
                [user_id] + excl_vals
            ).fetchone()

        if not row:
            break  # المخزون فارغ تماماً

        stock_id = row["id"]
        phone    = row["phone_number"]
        sess     = row["session_string"]
        saved_pw = row["twofa_password"] or ""

        # ─── فحص ①: هل للرقم جلسة أصلاً؟ (رقم يدوي = يُحذف) ───
        if not sess:
            _auto_delete_number(stock_id, phone, "رقم يدوي بلا جلسة — لا يُباع")
            continue

        # ─── فحص ③: هل كلمة مرور 2FA مخزّنة؟ ───
        if not saved_pw.strip():
            _auto_delete_number(stock_id, phone, "لا يوجد رمز 2FA — لا يمكن تسليمه للمشتري")
            continue

        # ─── فحص ②: هل البوت لا يزال مصرّحاً (يستطيع استقبال الأكواد)؟ ───
        cli_check = None
        try:
            cli_check = TelegramClient(StringSession(sess), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await asyncio.wait_for(cli_check.connect(), timeout=15)
            authorized = await asyncio.wait_for(cli_check.is_user_authorized(), timeout=10)

            if not authorized:
                _auto_delete_number(stock_id, phone, "جلسة منتهية — البوت لا يستطيع استقبال الأكواد")
                await cli_check.disconnect()
                continue

            # ─── فحص إضافي: هل الحساب مجمّد؟ ───
            is_frz, _, _ = await check_account_frozen(cli_check, stock_id)
            if is_frz:
                _auto_delete_number(stock_id, phone, "حساب مجمّد من تيليغرام")
                await cli_check.disconnect()
                continue

            # ─── تنظيف: طرد أي أجهزة إضافية قبل التسليم ───
            devices = await get_device_count(cli_check)
            if devices > 1:
                try:
                    await cli_check(ResetAuthorizationsRequest())
                    with db_conn() as c:
                        c.execute("UPDATE number_stock SET sessions_reset=TRUE WHERE id=%s", (stock_id,))
                    logger.info(f"✅ طُردت {devices - 1} جلسة إضافية للرقم {phone} قبل التسليم.")
                except Exception as kick_err:
                    logger.warning(f"⚠️ تعذّر طرد جلسات {phone}: {kick_err}")

            # ─── مسح جميع المحادثات قبل تسليم الرقم للمشتري ───
            try:
                async for _dlg in cli_check.iter_dialogs(limit=300):
                    try:
                        await cli_check.delete_dialog(_dlg, revoke=True)
                    except Exception:
                        pass
                logger.info(f"🧹 تم مسح محادثات الرقم {phone} قبل التسليم.")
            except Exception as _clr_err:
                logger.warning(f"⚠️ تعذّر مسح بعض محادثات {phone}: {_clr_err}")

            await cli_check.disconnect()

        except Exception as chk_err:
            logger.warning(f"⚠️ فشل الاتصال بجلسة {phone}: {chk_err} — يُحذف")
            _auto_delete_number(stock_id, phone, f"خطأ في الاتصال: {type(chk_err).__name__}")
            try:
                if cli_check:
                    await cli_check.disconnect()
            except Exception:
                pass
            continue

        # ─── الرقم اجتاز الفحوصات الثلاثة ✅ ───
        logger.info(f"✅ الرقم {phone} اجتاز جميع الفحوصات — جاهز للتسليم.")
        return {"phone_number": phone, "session_string": sess, "twofa_password": saved_pw}

    logger.info(f"📭 assign_verified_number: لا يوجد رقم صالح بعد {MAX_TRIES} محاولة.")
    return None

# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
