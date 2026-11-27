"""مساعدة تسجيل الدخول للأعضاء (تأجير/مشاركة رقم) عندما لا يصل الكود.

الحلول المقدَّمة:
1. إعادة إرسال الكود (تيليجرام يبدّل القناة: تطبيق ← SMS ← مكالمة).
2. دخول بدون كود عبر رابط تأكيد يُفتح من تطبيق تيليجرام على نفس الهاتف
   (لأن مسح QR من الشاشة نفسها مستحيل)، أو مسح QR من جهاز آخر.
3. توضيح السبب عندما يختار تيليجرام قناة لا يستطيع البوت إكمالها
   (مثل طلب إعداد بريد إلكتروني أو التحقق عبر Firebase).
4. تطبيع الرقم والكود (أرقام عربية/فارسية، فواصل، 00 بدل +، لصق رسالة كاملة).

الوحدة تُحمَّل ضمن نفس مساحة الأسماء المشتركة مثل بقية أقسام البوت.
"""

import io as _io
import re
import time as _time

from telegram import InputMediaPhoto

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

CTLOGIN_PREFIX = "ctlogin:"
LOGIN_RESEND_MAX = 3
LOGIN_RESEND_COOLDOWN_SECONDS = 20
LOGIN_QR_TOTAL_SECONDS = 150
LOGIN_QR_REFRESH_SECONDS = 25

_DIGIT_MAP = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


# ───────────────────────── تطبيع المدخلات ─────────────────────────

def normalize_login_phone(raw) -> str:
    """يحوّل ما كتبه العضو إلى صيغة +<digits> أو يعيد نصاً غير صالح كما هو."""
    text = _INVISIBLE_RE.sub("", str(raw or "")).translate(_DIGIT_MAP)
    text = re.sub(r"[\s\-().,/]", "", text)
    if text.startswith("00") and text[2:].isdigit():
        text = "+" + text[2:]
    if text and not text.startswith("+") and text.isdigit():
        text = "+" + text
    return text


def is_valid_login_phone(phone: str) -> bool:
    return bool(re.fullmatch(r"\+\d{7,15}", str(phone or "")))


def normalize_login_code(raw) -> str:
    """يستخرج كود الدخول حتى لو لُصقت رسالة تيليجرام كاملة أو كُتب بفواصل."""
    text = _INVISIBLE_RE.sub("", str(raw or "")).translate(_DIGIT_MAP)
    joined = re.sub(r"(?<=\d)[\s\-.](?=\d)", "", text)
    match = re.search(r"\d{5,6}", joined)
    if match:
        return match.group(0)
    return re.sub(r"\s+", "", text.strip())


# ───────────────────────── وصف قناة الإرسال ─────────────────────────

# أنواع لا يستطيع البوت إكمالها بالكود: لن يصل كود يمكن إدخاله هنا.
_BLOCKED_TYPES = {
    "SentCodeTypeSetUpEmailRequired": (
        "⚠️ تيليجرام يطلب *إعداد بريد إلكتروني* لهذا الحساب قبل إرسال الكود، "
        "ولا يمكن للبوت إكمال ذلك، لذلك لن يصلك كود هنا.\n"
        "استخدم زر «الدخول بدون كود» أدناه."
    ),
    "SentCodeTypeFirebaseSms": (
        "⚠️ تيليجرام اختار التحقق عبر خدمة Firebase لهذا الرقم، وهي قناة لا يدعمها البوت، "
        "لذلك قد لا يصلك كود.\n"
        "جرّب «إعادة الإرسال» أو استخدم «الدخول بدون كود»."
    ),
}


def describe_code_delivery(sent) -> tuple[str, bool]:
    """(نص للمستخدم، هل القناة غير قابلة للإكمال؟)."""
    name = type(getattr(sent, "type", None)).__name__
    if name in _BLOCKED_TYPES:
        return _BLOCKED_TYPES[name], True
    if name == "SentCodeTypeApp":
        return (
            "📨 أُرسل الكود *داخل تطبيق Telegram* إلى جلسة مفتوحة للحساب "
            "(محادثة Telegram الرسمية 777000) وليس عبر SMS.\n"
            "إن لم يكن الحساب مفتوحاً على أي جهاز، اضغط «إعادة الإرسال» ليُرسَل SMS.",
            False,
        )
    if name in {"SentCodeTypeSms", "SentCodeTypeSmsWord", "SentCodeTypeSmsPhrase"}:
        return "📨 أُرسل الكود عبر SMS إلى الشريحة المرتبطة بالرقم (قد يتأخر دقائق).", False
    if name == "SentCodeTypeCall":
        return "📞 سيتصل بك تيليجرام ويُملي الكود صوتياً.", False
    if name in {"SentCodeTypeFlashCall", "SentCodeTypeMissedCall"}:
        return (
            "📞 سيصلك اتصال قصير؛ الكود هو آخر أرقام الرقم المتصل. "
            "إن لم يظهر، اضغط «إعادة الإرسال».",
            False,
        )
    if name == "SentCodeTypeFragmentSms":
        return "📨 الكود يُرسل عبر Fragment (للأرقام المجهولة)، افتح Fragment لاستلامه.", False
    if name in {"SentCodeTypeEmailCode"}:
        return "📧 أُرسل الكود إلى البريد الإلكتروني المرتبط بالحساب.", False
    return (
        "📨 تم قبول طلب الكود. افحص تطبيق Telegram (777000) ثم SMS. "
        "إن لم يصل خلال دقيقة اضغط «إعادة الإرسال».",
        False,
    )


def _next_type_hint(sent) -> str:
    name = type(getattr(sent, "next_type", None)).__name__
    labels = {
        "CodeTypeSms": "SMS",
        "CodeTypeCall": "مكالمة صوتية",
        "CodeTypeFlashCall": "اتصال قصير",
        "CodeTypeMissedCall": "اتصال قصير",
        "CodeTypeFragmentSms": "Fragment",
    }
    label = labels.get(name)
    if not label:
        return ""
    return f"\nالإرسال التالي المتاح: {label}."


# ───────────────────────── لوحات الأزرار ─────────────────────────

def login_assist_kb(
    *, contributor: bool, resends_left: int = LOGIN_RESEND_MAX
) -> InlineKeyboardMarkup:
    rows = []
    if resends_left > 0:
        rows.append([InlineKeyboardButton(
            "🔁 لم يصل الكود؟ أعد الإرسال", callback_data="ctlogin:resend"
        )])
    if contributor:
        rows.append([InlineKeyboardButton(
            "🔗 الدخول بدون كود (رابط / QR)", callback_data="ctlogin:qr"
        )])
    else:
        rows.append([InlineKeyboardButton(
            "📷 الدخول عبر QR بدل الكود", callback_data="os:login_qr_fallback"
        )])
    rows.append([InlineKeyboardButton("❌ إلغاء", callback_data="ctlogin:cancel")])
    return InlineKeyboardMarkup(rows)


def _qr_kb(url: str | None) -> InlineKeyboardMarkup:
    rows = []
    if url:
        rows.append([InlineKeyboardButton(
            "🔗 تأكيد من تطبيق Telegram (نفس الهاتف)", url=url
        )])
    rows.append([InlineKeyboardButton("🔄 رمز جديد", callback_data="ctlogin:qr")])
    rows.append([InlineKeyboardButton("❌ إلغاء", callback_data="ctlogin:cancel")])
    return InlineKeyboardMarkup(rows)


def _is_share_login(pending: dict) -> bool:
    return pending.get("contributor_share_percent") == 0


def _back_callback(pending: dict | None, is_own: bool) -> str:
    if pending and pending.get("contributor_id"):
        return "share_number:menu" if _is_share_login(pending) else "contributor_accounts"
    return "os:manage_numbers" if is_own else "main_menu"


# ───────────────────────── المعالج الرئيسي ─────────────────────────

async def handle_login_assist_callback(update, context, q, data: str, user, is_own: bool) -> bool:
    """يعالج ``ctlogin:*``. يعيد True عند التعامل مع الزر."""
    if not data.startswith(CTLOGIN_PREFIX):
        return False
    action = data[len(CTLOGIN_PREFIX):]
    pending = _pending_number_logins.get(user.id)

    if action == "cancel":
        back = _back_callback(pending, is_own)
        await _cleanup_pending_login(user.id)
        context.user_data["state"] = "main_menu"
        try:
            await q.answer("تم الإلغاء")
        except Exception:
            pass
        try:
            await q.edit_message_text(
                "❎ تم إلغاء تسجيل الدخول.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 رجوع", callback_data=back)
                ]]),
            )
        except Exception:
            pass
        return True

    if not pending or not pending.get("phone") or not pending.get("client"):
        await q.answer("⚠️ انتهت جلسة الرقم. ابدأ من جديد.", show_alert=True)
        return True

    if action == "resend":
        await _resend_login_code(context, q, user, pending, is_own)
        return True

    if action == "qr":
        if not pending.get("contributor_id") and not is_own:
            await q.answer("⚠️ غير مسموح.", show_alert=True)
            return True
        await q.answer()
        try:
            await q.edit_message_text("⏳ جارٍ تجهيز الدخول بدون كود...")
        except Exception:
            pass
        asyncio.create_task(_run_member_qr_login(update, context, user.id, is_own))
        return True

    await q.answer("⚠️ أمر غير معروف.", show_alert=True)
    return True


# ───────────────────────── إعادة إرسال الكود ─────────────────────────

async def _resend_login_code(context, q, user, pending: dict, is_own: bool) -> None:
    contributor = bool(pending.get("contributor_id"))
    used = int(pending.get("resend_count") or 0)
    if used >= LOGIN_RESEND_MAX:
        await q.answer(
            "⚠️ استُهلكت محاولات إعادة الإرسال. استخدم «الدخول بدون كود».",
            show_alert=True,
        )
        return
    wait_left = int(
        LOGIN_RESEND_COOLDOWN_SECONDS - (_time.monotonic() - float(pending.get("resend_at") or 0))
    )
    if wait_left > 0:
        await q.answer(f"⏳ انتظر {wait_left} ثانية قبل إعادة الإرسال.", show_alert=True)
        return

    await q.answer("🔁 جارٍ إعادة الإرسال...")
    client = pending["client"]
    phone = pending["phone"]
    try:
        # نفس العميل ونفس الرقم: تيليجرام يعتبرها ResendCode ويبدّل القناة.
        sent = await asyncio.wait_for(client.send_code_request(phone, force_sms=True), timeout=25)
    except FloodWaitError as exc:
        await _safe_edit(
            q,
            f"⏳ فرض تيليجرام انتظار {exc.seconds} ثانية. حاول لاحقاً أو استخدم «الدخول بدون كود».",
            login_assist_kb(contributor=contributor, resends_left=LOGIN_RESEND_MAX - used),
        )
        return
    except asyncio.TimeoutError:
        await _safe_edit(
            q,
            "⌛ تأخر الاتصال بتيليجرام. حاول مرة أخرى بعد قليل.",
            login_assist_kb(contributor=contributor, resends_left=LOGIN_RESEND_MAX - used),
        )
        return
    except Exception as exc:
        name = type(exc).__name__
        logger.warning("تعذّرت إعادة إرسال كود الدخول (%s): %s", name, exc)
        if name == "SendCodeUnavailableError":
            text = (
                "⚠️ استُنفدت كل قنوات الإرسال المتاحة لهذا الرقم.\n"
                "استخدم «الدخول بدون كود» أو انتظر عدة ساعات ثم أعد المحاولة."
            )
        elif name in {"PhoneCodeExpiredError", "PhoneCodeInvalidError"}:
            text = "⚠️ انتهت صلاحية الطلب. اضغط إلغاء ثم أعد إرسال الرقم من البداية."
        else:
            text = _login_code_error_message(exc)
        await _safe_edit(
            q, text,
            login_assist_kb(contributor=contributor, resends_left=LOGIN_RESEND_MAX - used),
        )
        return

    pending["phone_code_hash"] = sent.phone_code_hash
    pending["resend_count"] = used + 1
    pending["resend_at"] = _time.monotonic()
    note, _blocked = describe_code_delivery(sent)
    await _safe_edit(
        q,
        f"🔁 *أُعيد إرسال الكود* (المحاولة {used + 1}/{LOGIN_RESEND_MAX})\n\n"
        f"{note}{_next_type_hint(sent)}\n\n"
        "أرسل آخر كود وصلك هنا.",
        login_assist_kb(contributor=contributor, resends_left=LOGIN_RESEND_MAX - used - 1),
        markdown=True,
    )


async def _safe_edit(q, text: str, markup, markdown: bool = False) -> None:
    try:
        await q.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN if markdown else None,
            reply_markup=markup,
        )
    except Exception as exc:
        # Markdown قد يفشل بسبب رموز في النص؛ نعيد المحاولة نصاً عادياً.
        if markdown:
            try:
                await q.edit_message_text(text.replace("*", ""), reply_markup=markup)
            except Exception:
                logger.debug("تعذّر تعديل رسالة تسجيل الدخول: %s", exc)


# ───────────────────────── الدخول بدون كود ─────────────────────────

def _qr_caption(seconds_left: int) -> str:
    return (
        "🔗 *الدخول بدون كود*\n\n"
        "*من نفس الهاتف:* افتح تطبيق Telegram الرسمي المسجَّل فيه الحساب أولاً، "
        "ثم اضغط الزر «تأكيد من تطبيق Telegram» أدناه ووافق على تسجيل الدخول.\n\n"
        "*من جهاز آخر:* امسح الرمز من Telegram على هاتف الحساب: "
        "الإعدادات ← الأجهزة ← ربط جهاز سطح مكتب.\n\n"
        f"⏱ الرمز يتجدد تلقائياً (صالح نحو {seconds_left} ثانية). "
        "لا ترسل الصورة أو الرابط لأي شخص."
    )


def _make_qr_png(url: str):
    try:
        import qrcode as _qrcode
    except Exception:
        return None
    buffer = _io.BytesIO()
    _qrcode.make(url).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


async def _run_member_qr_login(update, context, user_id: int, is_own: bool) -> None:
    pending = _pending_number_logins.get(user_id)
    if not pending:
        await context.bot.send_message(user_id, "⚠️ انتهت جلسة تسجيل الدخول. ابدأ من جديد.")
        context.user_data["state"] = "main_menu"
        return

    old_client = pending.get("client")
    try:
        if old_client:
            await old_client.disconnect()
    except Exception:
        pass

    contributor = bool(pending.get("contributor_id"))
    share = _is_share_login(pending)
    client = None
    try:
        client = TelegramClient(StringSession(), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=20)
        qr_login = await asyncio.wait_for(client.qr_login(), timeout=20)
    except Exception as exc:
        logger.warning("⚠️ فشل تجهيز الدخول بدون كود: %s", exc)
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        _pending_number_logins.pop(user_id, None)
        context.user_data["state"] = "main_menu"
        await context.bot.send_message(
            user_id,
            "❌ تعذّر تجهيز الدخول بدون كود. أعد المحاولة بعد قليل.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🔙 رجوع", callback_data=_back_callback(pending, is_own)
                )
            ]]),
        )
        return

    pending["client"] = client
    pending["qr_login"] = qr_login
    pending["login_method"] = "qr"
    if contributor:
        context.user_data["state"] = (
            "share_number_await_login_qr" if share else "contributor_await_login_qr"
        )
    else:
        context.user_data["state"] = "os_await_login_qr"

    photo = _make_qr_png(qr_login.url)
    caption = _qr_caption(LOGIN_QR_REFRESH_SECONDS + 5)
    message = None
    try:
        if photo is not None:
            message = await context.bot.send_photo(
                chat_id=user_id, photo=photo, caption=caption,
                parse_mode=ParseMode.MARKDOWN, reply_markup=_qr_kb(qr_login.url),
            )
        else:
            message = await context.bot.send_message(
                chat_id=user_id, text=caption,
                parse_mode=ParseMode.MARKDOWN, reply_markup=_qr_kb(qr_login.url),
            )
    except Exception as exc:
        # قد يرفض تيليجرام رابط tg:// داخل الزر؛ نرسل بدونه ونضع الرابط نصاً.
        logger.info("تعذّر إرسال زر الرابط المباشر (%s)، إرسال بدونه", exc)
        try:
            photo = _make_qr_png(qr_login.url)
            if photo is not None:
                message = await context.bot.send_photo(
                    chat_id=user_id, photo=photo, caption=caption,
                    parse_mode=ParseMode.MARKDOWN, reply_markup=_qr_kb(None),
                )
            else:
                message = await context.bot.send_message(
                    chat_id=user_id, text=caption,
                    parse_mode=ParseMode.MARKDOWN, reply_markup=_qr_kb(None),
                )
        except Exception as exc2:
            logger.warning("فشل إرسال رمز الدخول: %s", exc2)
            await _cleanup_pending_login(user_id)
            context.user_data["state"] = "main_menu"
            await context.bot.send_message(user_id, "❌ تعذّر إرسال رمز الدخول. أعد المحاولة.")
            return

    pending["qr_message_id"] = getattr(message, "message_id", None)
    asyncio.create_task(_wait_member_qr_login(update, context, user_id, qr_login, is_own))


async def _refresh_qr_message(context, user_id: int, pending: dict, qr_login) -> None:
    message_id = pending.get("qr_message_id")
    if not message_id:
        return
    try:
        photo = _make_qr_png(qr_login.url)
        if photo is not None:
            await context.bot.edit_message_media(
                chat_id=user_id, message_id=message_id,
                media=InputMediaPhoto(
                    media=photo,
                    caption=_qr_caption(LOGIN_QR_REFRESH_SECONDS + 5),
                    parse_mode=ParseMode.MARKDOWN,
                ),
                reply_markup=_qr_kb(qr_login.url),
            )
        else:
            await context.bot.edit_message_reply_markup(
                chat_id=user_id, message_id=message_id, reply_markup=_qr_kb(qr_login.url),
            )
    except Exception as exc:
        logger.debug("تعذّر تحديث رمز الدخول: %s", exc)
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=user_id, message_id=message_id, reply_markup=_qr_kb(None),
            )
        except Exception:
            pass


async def _wait_member_qr_login(update, context, user_id: int, qr_login, is_own: bool) -> None:
    pending = _pending_number_logins.get(user_id)
    if not pending or pending.get("qr_login") is not qr_login:
        return
    client = pending["client"]
    expected_phone = re.sub(r"\D", "", str(pending.get("phone") or ""))
    contributor = bool(pending.get("contributor_id"))
    share = _is_share_login(pending)
    deadline = _time.monotonic() + LOGIN_QR_TOTAL_SECONDS

    def _stale() -> bool:
        current = _pending_number_logins.get(user_id)
        return not current or current.get("qr_login") is not qr_login

    try:
        while True:
            if _stale():
                return  # طُلب رمز جديد أو أُلغي الطلب
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError
            slice_seconds = min(float(LOGIN_QR_REFRESH_SECONDS), remaining)
            try:
                await asyncio.wait_for(qr_login.wait(), timeout=slice_seconds)
                break
            except asyncio.TimeoutError:
                if deadline - _time.monotonic() <= 0 or _stale():
                    raise
                await qr_login.recreate()
                await _refresh_qr_message(context, user_id, pending, qr_login)

        me = await asyncio.wait_for(client.get_me(), timeout=15)
        actual_phone = re.sub(r"\D", "", str(getattr(me, "phone", "") or ""))
        if expected_phone and actual_phone and expected_phone != actual_phone:
            raise ValueError("تم تأكيد الدخول من حساب مختلف عن الرقم المطلوب")
        if expected_phone and not actual_phone:
            raise ValueError("تعذّر التحقق من رقم الحساب بعد التأكيد")
        await context.bot.send_message(user_id, "✅ تم قبول الدخول، جارٍ حفظ الحساب...")
        await _finish_number_login(update, context, user_id)
    except SessionPasswordNeededError:
        if _stale():
            return
        if contributor:
            context.user_data["state"] = (
                "share_number_await_login_password" if share
                else "contributor_await_login_password"
            )
        else:
            context.user_data["state"] = "os_await_login_password"
        await context.bot.send_message(
            user_id,
            "🔒 تم قبول الدخول، لكن الحساب محمي بكلمة مرور التحقق بخطوتين (2FA). "
            "أرسلها الآن:",
        )
    except asyncio.TimeoutError:
        if _stale():
            return
        back = _back_callback(pending, is_own)
        await _cleanup_pending_login(user_id)
        context.user_data["state"] = "main_menu"
        await context.bot.send_message(
            user_id,
            "⌛ انتهت مهلة الدخول بدون كود. ابدأ من جديد.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data=back)
            ]]),
        )
    except Exception as exc:
        if _stale():
            return
        logger.warning("⚠️ فشل الدخول بدون كود: %s", exc)
        back = _back_callback(pending, is_own)
        await _cleanup_pending_login(user_id)
        context.user_data["state"] = "main_menu"
        await context.bot.send_message(
            user_id,
            "❌ لم يتم قبول الدخول. تأكد أنك تؤكد من الحساب الصحيح ثم أعد المحاولة.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data=back)
            ]]),
        )
