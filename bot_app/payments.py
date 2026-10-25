"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

from decimal import Decimal

JEWEL_STAR_TOPUP_MAX = 10000
JEWEL_STAR_TOPUP_PRESETS = (3, 10, 50, 100)
CURRENCY_EXCHANGE_MAX_INPUT = 1_000_000_000
CURRENCY_EXCHANGE_MAX_POINTS = 2_147_483_647
CURRENCY_EXCHANGE_MAX_JEWELS = Decimal("99999999999999.999999")
DEFAULT_JEWELS_TO_POINTS_RATE = 5000
DEFAULT_POINTS_TO_JEWELS_RATE = 7000


def parse_currency_exchange_amount(value):
    """Parse a positive whole-number exchange amount in Arabic or Latin digits."""
    raw = str(value or "").strip().translate(str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789",
    ))
    try:
        amount = int(raw.replace(",", "").replace("٬", ""))
    except (TypeError, ValueError):
        return None
    return amount if 1 <= amount <= CURRENCY_EXCHANGE_MAX_INPUT else None


def get_currency_exchange_rates():
    """Return the independently configurable rates, falling back to safe defaults."""
    jewels_to_points = parse_currency_exchange_amount(
        get_setting("jewels_to_points_rate")
    )
    points_to_jewels = parse_currency_exchange_amount(
        get_setting("points_to_jewels_rate")
    )
    return {
        "jewels_to_points": jewels_to_points or DEFAULT_JEWELS_TO_POINTS_RATE,
        "points_to_jewels": points_to_jewels or DEFAULT_POINTS_TO_JEWELS_RATE,
    }


def calculate_currency_exchange(direction, amount, rate):
    """Build a whole-jewel exchange quote and reject values that exceed points storage."""
    amount = parse_currency_exchange_amount(amount)
    rate = parse_currency_exchange_amount(rate)
    if amount is None or rate is None:
        return None
    if direction not in {"jewels_to_points", "points_to_jewels"}:
        return None
    points_amount = amount * rate
    if points_amount > CURRENCY_EXCHANGE_MAX_POINTS:
        return None
    return {
        "direction": direction,
        "jewels_amount": amount,
        "points_amount": points_amount,
        "rate": rate,
    }


def perform_currency_exchange(user_id, request_id, direction, amount, rate):
    """Atomically exchange balances and record an idempotent transaction."""
    quote = calculate_currency_exchange(direction, amount, rate)
    request_id = str(request_id or "").strip()
    if not quote or not request_id:
        return {"status": "invalid"}

    with db_conn() as c:
        inserted = c.execute(
            """
            INSERT INTO currency_exchange_transactions
                (request_id, user_id, direction, jewels_amount, points_amount, rate, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending')
            ON CONFLICT (request_id) DO NOTHING
            RETURNING id
            """,
            (
                request_id,
                user_id,
                direction,
                quote["jewels_amount"],
                quote["points_amount"],
                quote["rate"],
            ),
        ).fetchone()
        if not inserted:
            existing = c.execute(
                "SELECT status FROM currency_exchange_transactions WHERE request_id=%s",
                (request_id,),
            ).fetchone()
            return {
                "status": "duplicate",
                "previous_status": existing["status"] if existing else None,
            }

        balance = c.execute(
            "SELECT points, jewels FROM users WHERE user_id=%s FOR UPDATE",
            (user_id,),
        ).fetchone()
        status = "user_missing"
        new_points = None
        new_jewels = None
        if balance:
            current_points = int(balance.get("points") or 0)
            current_jewels = Decimal(str(balance.get("jewels") or 0))
            jewels_amount = Decimal(quote["jewels_amount"])
            points_amount = quote["points_amount"]

            if direction == "jewels_to_points":
                if current_jewels < jewels_amount:
                    status = "insufficient_jewels"
                elif current_points + points_amount > CURRENCY_EXCHANGE_MAX_POINTS:
                    status = "points_limit"
                else:
                    new_jewels = current_jewels - jewels_amount
                    new_points = current_points + points_amount
                    status = "completed"
            elif current_points < points_amount:
                status = "insufficient_points"
            elif current_jewels + jewels_amount > CURRENCY_EXCHANGE_MAX_JEWELS:
                status = "jewels_limit"
            else:
                new_points = current_points - points_amount
                new_jewels = current_jewels + jewels_amount
                status = "completed"

        if status == "completed":
            c.execute(
                "UPDATE users SET points=%s, jewels=%s WHERE user_id=%s",
                (new_points, new_jewels, user_id),
            )
        c.execute(
            "UPDATE currency_exchange_transactions SET status=%s WHERE id=%s",
            (status, inserted["id"]),
        )
        return {
            "status": status,
            "quote": quote,
            "balance": (
                {"points": new_points, "jewels": new_jewels}
                if status == "completed"
                else None
            ),
        }


def parse_jewel_star_topup_amount(value):
    """Parse a user-entered jewel count, including Arabic-Indic digits."""
    raw = str(value or "").strip().translate(str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789",
    ))
    try:
        amount = int(raw.replace(",", "").replace("٬", ""))
    except (TypeError, ValueError):
        return None
    return amount if 1 <= amount <= JEWEL_STAR_TOPUP_MAX else None


def validate_jewel_star_invoice(payload, user_id, total_amount, currency):
    """Return the jewel quantity only for a correctly priced XTR invoice."""
    parts = str(payload or "").split(":")
    if (
        len(parts) != 3
        or parts[0] != "jewel_stars"
        or not parts[1].isdigit()
        or not parts[2].isdigit()
        or currency != "XTR"
    ):
        return None
    amount = int(parts[1])
    if (
        not 1 <= amount <= JEWEL_STAR_TOPUP_MAX
        or int(parts[2]) != int(user_id)
        or int(total_amount) != amount
    ):
        return None
    return amount


async def send_jewel_star_invoice(context, user, amount):
    """Create a Telegram Stars invoice at the fixed rate of one star per jewel."""
    amount = parse_jewel_star_topup_amount(amount)
    if amount is None:
        raise ValueError("invalid jewel top-up amount")
    await context.bot.send_invoice(
        chat_id=user.id,
        title="شحن مجوهرات",
        description=f"شراء {amount} مجوهرة مقابل {amount} نجمة",
        payload=f"jewel_stars:{amount}:{user.id}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice("مجوهرات", amount)],
    )


async def handle_jewel_topup_callback(update, context, q, data, user, is_owner):
    """Route jewel top-up choices, custom counts, and manual-payment instructions."""
    if data in ("jewels_topup", "jtopup:menu"):
        context.user_data["state"] = "main_menu"
        await q.edit_message_text(
            "💎 *شحن مجوهرات*\n\nاختر طريقة الشحن:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 الشحن برصيد آسيا سيل", callback_data="jtopup:asiacell")],
                [InlineKeyboardButton("⭐ الشحن بالنجوم", callback_data="jtopup:stars")],
                [InlineKeyboardButton("💳 العملات الإلكترونية", callback_data="jtopup:ewallet")],
                [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
            ]),
        )
        return

    if data in ("jtopup:asiacell", "jtopup:ewallet"):
        if data.endswith("asiacell"):
            setting_key = "jewels_asiacell_text"
            default_text = "💎 تواصل مع المالك لمعرفة تعليمات التحويل عبر آسيا سيل."
        else:
            setting_key = "jewels_ewallet_text"
            default_text = "💎 تواصل مع المالك لمعرفة تعليمات التحويل عبر العملات الإلكترونية."
        text = get_setting(setting_key) or default_text
        contact = get_setting("owner_contact") or (
            f"tg://user?id={OWNER_ID}" if OWNER_ID else ""
        )
        rows = []
        if contact:
            rows.append([InlineKeyboardButton("💬 التواصل مع المالك", url=contact)])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="jtopup:menu")])
        context.user_data["state"] = "main_menu"
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))
        return

    if data == "jtopup:stars":
        context.user_data["state"] = "main_menu"
        rows = []
        for start in range(0, len(JEWEL_STAR_TOPUP_PRESETS), 2):
            rows.append([
                InlineKeyboardButton(
                    f"{amount} 💎",
                    callback_data=f"jtopup:stars:qty:{amount}",
                )
                for amount in JEWEL_STAR_TOPUP_PRESETS[start:start + 2]
            ])
        rows.extend([
            [InlineKeyboardButton("🔢 كمية أخرى", callback_data="jtopup:stars:custom")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="jtopup:menu")],
        ])
        await q.edit_message_text(
            "⭐ *الشحن بالنجوم*\n\n"
            "سعر كل مجوهرة: *1 نجمة*.\n"
            "اختر كمية جاهزة أو أدخل كمية أخرى؛ ستظهر فاتورة Telegram قبل الدفع.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if data == "jtopup:stars:custom":
        context.user_data["state"] = "await_jewel_star_amount"
        await q.edit_message_text(
            f"🔢 أرسل عدد المجوهرات المطلوب شحنها (من 1 إلى {JEWEL_STAR_TOPUP_MAX:,}).",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="jtopup:stars")
            ]]),
        )
        return

    if data.startswith("jtopup:stars:qty:"):
        amount = parse_jewel_star_topup_amount(data.rsplit(":", 1)[-1])
        if amount is None:
            await q.answer("⚠️ الكمية غير صالحة.", show_alert=True)
            return
        await q.answer("✅ جارٍ تجهيز فاتورة النجوم.")
        try:
            await send_jewel_star_invoice(context, user, amount)
        except Exception:
            logger.exception("تعذر إرسال فاتورة شحن المجوهرات بالنجوم للمستخدم %s", user.id)
            await q.message.reply_text(
                "⚠️ تعذر إنشاء فاتورة النجوم الآن. حاول مرة أخرى لاحقاً.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 رجوع لشحن المجوهرات", callback_data="jtopup:stars")
                ]]),
            )


async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.pre_checkout_query
    payload = query.invoice_payload

    try:
        valid = False
        if payload.startswith("charge_stars:"):
            parts = payload.split(":")
            if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                expected_stars = int(parts[1])
                uid_in_payload = int(parts[2])
                actual_stars   = query.total_amount
                if query.from_user.id == uid_in_payload and actual_stars == expected_stars:
                    valid = True

        if payload.startswith("jewel_stars:"):
            valid = validate_jewel_star_invoice(
                payload,
                query.from_user.id,
                query.total_amount,
                query.currency,
            ) is not None

        if payload.startswith("number_stars:"):
            parts = payload.split(":")
            if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                uid_in_payload = int(parts[1])
                expected_stars = int(parts[2])
                if query.from_user.id == uid_in_payload and query.total_amount == expected_stars:
                    valid = True

        # ─── الاشتراك الإجباري بالنجوم ───
        if payload.startswith("fund_mandatory:"):
            parts = payload.split(":")
            if len(parts) == 5 and parts[1].isdigit() and parts[4].isdigit():
                uid_in_payload = int(parts[1])
                expected_stars = int(parts[4])
                if query.from_user.id == uid_in_payload and query.total_amount == expected_stars:
                    valid = True

        # ─── إحالة بوت إجبارية بالنجوم ───
        if payload.startswith("forced_ref_stars:"):
            parts = payload.split(":")
            if len(parts) >= 5 and parts[1].isdigit() and parts[3].isdigit():
                uid_in_payload = int(parts[1])
                expected_stars = int(parts[3])
                if query.from_user.id == uid_in_payload and query.total_amount == expected_stars:
                    valid = True

        # الخدمات الأسطورية بالنجوم
        if payload.startswith("legendary_stars:"):
            parts = payload.split(":")
            if (
                len(parts) == 5
                and parts[1].isdigit()
                and parts[3].isdigit()
                and parts[4].isdigit()
            ):
                uid_in_payload = int(parts[1])
                expected_stars = int(parts[4])
                if query.from_user.id == uid_in_payload and query.total_amount == expected_stars:
                    valid = True

        if payload.startswith("smm_stars:"):
            parts = payload.split(":")
            if len(parts) == 2 and parts[1].isdigit():
                intent = get_smm_payment_intent(int(parts[1]), query.from_user.id)
                if (
                    intent
                    and query.currency == "XTR"
                    and intent.get("payment_method") == "stars"
                    and validate_smm_stars_invoice(
                        int(parts[1]),
                        query.from_user.id,
                        int(query.total_amount),
                    )
                ):
                    valid = True

        if valid:
            await query.answer(ok=True)
        else:
            await query.answer(ok=False, error_message="حدث خطأ في التحقق من الدفع.")
    except Exception as _pce:
        logger.error(f"❌ خطأ في pre_checkout: {_pce}")
        try:
            await query.answer(ok=False, error_message="خطأ داخلي، حاول مجدداً.")
        except Exception:
            pass


async def _notify_owner_manual_star_purchase(context, text: str):
    """إشعار المالك بطلب دفع نجوم يحتاج تسليماً يدوياً فقط."""
    if not OWNER_ID:
        logger.warning("⚠️ OWNER_ID غير مضبوط؛ تعذر إرسال طلب النجوم للمالك")
        return
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=text)
    except Exception as _owner_notify_error:
        logger.warning(f"⚠️ تعذر إشعار المالك بطلب نجوم يدوي: {_owner_notify_error}")

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    user    = update.effective_user
    is_own  = (user.id == OWNER_ID)

    if payload.startswith("smm_stars:"):
        parts = payload.split(":")
        if len(parts) != 2 or not parts[1].isdigit():
            try:
                _credit_star_payment_as_jewels_once(
                    user.id,
                    payment.total_amount,
                    payment.telegram_payment_charge_id or f"update:{update.update_id}",
                )
                await update.message.reply_text(
                    f"⚠️ بيانات طلب الرشق غير صالحة؛ أُضيفت "
                    f"{fmt_jewel_amount(payment.total_amount)} جواهر إلى رصيدك.",
                    reply_markup=main_menu_kb(is_own),
                )
            except Exception:
                logger.exception("تعذر تعويض دفعة SMM غير صالحة بالجواهر")
                await _notify_owner_manual_star_purchase(
                    context,
                    f"⚠️ تعذّر إضافة جواهر تعويض لدفعة رشق غير صالحة. "
                    f"المستخدم: {user.id}، العملية: {payment.telegram_payment_charge_id}",
                )
                await update.message.reply_text(
                    "⚠️ بيانات الطلب غير صالحة وتعذّر إضافة جواهر التعويض تلقائياً. "
                    "أبلغت المالك للمراجعة.",
                    reply_markup=main_menu_kb(is_own),
                )
            return

        intent_id = int(parts[1])
        charge_id = payment.telegram_payment_charge_id
        claim_status, intent = claim_smm_stars_payment(
            intent_id,
            user.id,
            int(payment.total_amount),
            charge_id,
        )
        if claim_status == "duplicate_update":
            await update.message.reply_text(
                "✅ تمت معالجة هذا الدفع مسبقاً.",
                reply_markup=main_menu_kb(is_own),
            )
            return

        if claim_status == "duplicate_charge":
            try:
                credited = _credit_star_payment_as_jewels_once(
                    user.id, payment.total_amount, charge_id
                )
                await update.message.reply_text(
                    f"⚠️ تم رصد دفعة إضافية؛ "
                    f"{'أُضيفت' if credited else 'سبق إضافة'} "
                    f"{fmt_jewel_amount(payment.total_amount)} جواهر إلى رصيدك.",
                    reply_markup=main_menu_kb(is_own),
                )
            except Exception:
                logger.exception("تعذر تعويض دفعة SMM مكررة بالجواهر")
                await _notify_owner_manual_star_purchase(
                    context,
                    f"⚠️ يلزم إضافة جواهر تعويض لدفعة رشق مكررة. المستخدم: {user.id}، "
                    f"رقم العملية: {charge_id}",
                )
                await update.message.reply_text(
                    "⚠️ وصل دفع إضافي وتعذّر إضافة جواهر التعويض تلقائياً. "
                    "أبلغت المالك للمراجعة.",
                    reply_markup=main_menu_kb(is_own),
                )
            return

        if claim_status != "claimed" or not intent:
            try:
                _credit_star_payment_as_jewels_once(
                    user.id, payment.total_amount, charge_id
                )
                await update.message.reply_text(
                    f"⚠️ لم يعد هذا الطلب صالحاً؛ أُضيفت "
                    f"{fmt_jewel_amount(payment.total_amount)} جواهر إلى رصيدك.",
                    reply_markup=main_menu_kb(is_own),
                )
            except Exception:
                logger.exception("تعذر تعويض دفعة SMM لطلب غير صالح بالجواهر")
                await _notify_owner_manual_star_purchase(
                    context,
                    f"⚠️ يلزم مراجعة إضافة جواهر لدفعة طلب رشق غير صالح. المستخدم: {user.id}، "
                    f"رقم العملية: {charge_id}",
                )
                await update.message.reply_text(
                    "⚠️ تعذّر بدء الطلب أو إضافة جواهر التعويض تلقائياً. "
                    "أبلغت المالك للمراجعة.",
                    reply_markup=main_menu_kb(is_own),
                )
            return

        try:
            result = await execute_smm_payment_intent(
                context,
                intent,
                "stars",
                int(payment.total_amount),
                telegram_payment_id=charge_id,
            )
        except Exception:
            # A transport or persistence error after an upstream submission is
            # ambiguous; avoid charging/refunding blindly and alert the owner.
            logger.exception("نتيجة طلب SMM بعد دفع النجوم غير مؤكدة")
            finish_smm_payment_intent(
                intent_id, "needs_review", "order submission outcome uncertain"
            )
            await _notify_owner_manual_star_purchase(
                context,
                f"⚠️ يلزم التحقق من طلب مواقع الرشق بعد دفع النجوم. "
                f"المستخدم: {user.id}، الطلب: {intent_id}، العملية: {charge_id}",
            )
            await update.message.reply_text(
                "⚠️ تم استلام النجوم، لكن تعذر تأكيد نتيجة الطلب تلقائياً. أبلغت المالك للمراجعة؛ لا تعِد الدفع.",
                reply_markup=main_menu_kb(is_own),
            )
            return

        if result.get("ok"):
            return

        try:
            _credit_star_payment_as_jewels_once(
                user.id, payment.total_amount, charge_id
            )
            finish_smm_payment_intent(
                intent_id, "jewels_refunded", str(result.get("error") or "provider_error")
            )
            await update.message.reply_text(
                f"⚠️ تعذّر إرسال الطلب إلى موقع الرشق؛ أُضيفت "
                f"{fmt_jewel_amount(payment.total_amount)} جواهر إلى رصيدك.",
                reply_markup=main_menu_kb(is_own),
            )
        except Exception:
            logger.exception("تعذر تعويض طلب SMM بالجواهر بعد رفض موقع الرشق")
            finish_smm_payment_intent(
                intent_id, "refund_required", str(result.get("error") or "refund_failed")
            )
            await _notify_owner_manual_star_purchase(
                context,
                f"⚠️ تعذرت إضافة جواهر التعويض لطلب مواقع الرشق. المستخدم: {user.id}، "
                f"الطلب: {intent_id}، العملية: {charge_id}، المبلغ: {payment.total_amount} نجمة",
            )
            await update.message.reply_text(
                "⚠️ تعذّر تنفيذ الطلب أو إضافة جواهر التعويض تلقائياً. "
                "أبلغت المالك لمتابعة الحالة.",
                reply_markup=main_menu_kb(is_own),
            )
        return

    if payload.startswith("jewel_stars:"):
        amount = validate_jewel_star_invoice(
            payload,
            user.id,
            payment.total_amount,
            payment.currency,
        )
        charge_id = payment.telegram_payment_charge_id
        if amount is None:
            logger.error(
                "دفعة شحن مجوهرات غير مطابقة: user=%s payload=%s amount=%s currency=%s",
                user.id,
                payload,
                payment.total_amount,
                payment.currency,
            )
            try:
                credited = _credit_star_payment_as_jewels_once(
                    user.id,
                    payment.total_amount,
                    charge_id or f"update:{update.update_id}",
                )
                await update.message.reply_text(
                    f"⚠️ لم تتطابق بيانات الفاتورة؛ "
                    f"{'أُضيفت' if credited else 'سبق إضافة'} "
                    f"{fmt_jewel_amount(payment.total_amount)} جواهر إلى رصيدك."
                )
            except Exception:
                logger.exception("تعذر تحويل دفعة شحن مجوهرات غير مطابقة إلى جواهر")
                await _notify_owner_manual_star_purchase(
                    context,
                    f"⚠️ دفعة شحن مجوهرات غير مطابقة تعذّر تحويلها إلى جواهر. المستخدم: {user.id}، "
                    f"العملية: {charge_id}، الحمولة: {payload}",
                )
                await update.message.reply_text(
                    "⚠️ تعذّر التحقق من الدفعة أو إضافة جواهرها تلقائياً؛ "
                    "أبلغت المالك لمراجعتها.",
                    reply_markup=main_menu_kb(is_own),
                )
            return

        already_credited = False
        with db_conn() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"jewel-stars:{charge_id}",))
            existing = c.execute(
                "SELECT status FROM jewel_star_transactions "
                "WHERE telegram_payment_id=%s FOR UPDATE",
                (charge_id,),
            ).fetchone()
            if existing and existing["status"] == "completed":
                already_credited = True
            else:
                c.execute(
                    "INSERT INTO users (user_id,username,full_name,jewels) "
                    "VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "jewels=COALESCE(users.jewels,0)+EXCLUDED.jewels, "
                    "username=COALESCE(EXCLUDED.username,users.username), "
                    "full_name=COALESCE(EXCLUDED.full_name,users.full_name)",
                    (user.id, user.username, user.full_name, amount),
                )
                if existing:
                    c.execute(
                        "UPDATE jewel_star_transactions "
                        "SET status='completed', stars=%s, jewels_given=%s "
                        "WHERE telegram_payment_id=%s",
                        (amount, amount, charge_id),
                    )
                else:
                    c.execute(
                        "INSERT INTO jewel_star_transactions "
                        "(user_id,stars,jewels_given,telegram_payment_id,status) "
                        "VALUES (%s,%s,%s,%s,'completed')",
                        (user.id, amount, amount, charge_id),
                    )

        if already_credited:
            await update.message.reply_text(
                "✅ تمت معالجة هذه الدفعة مسبقاً؛ لم تتم إضافة المجوهرات مرة أخرى.",
                reply_markup=main_menu_kb(is_own),
            )
            return

        db_user = get_user(user.id)
        jewels_balance = (db_user or {}).get("jewels") or 0
        await update.message.reply_text(
            "✅ تم شحن المجوهرات تلقائياً بنجاح!\n\n"
            f"⭐ المدفوع: {amount} نجمة\n"
            f"💎 المضاف: {amount} مجوهرة\n"
            f"💎 رصيدك الحالي: {fmt_jewel_amount(jewels_balance)} مجوهرة",
            reply_markup=main_menu_kb(is_own),
        )
        return

    if payload.startswith("charge_stars:"):
        parts = payload.split(":")
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            await update.message.reply_text("⚠️ بيانات شحن النقاط غير صالحة.", reply_markup=main_menu_kb(is_own))
            return

        stars = int(parts[1])
        payload_user_id = int(parts[2])
        charge_id = payment.telegram_payment_charge_id
        if payload_user_id != user.id or payment.total_amount != stars:
            logger.error(
                f"❌ بيانات شحن النقاط بالنجوم غير متطابقة: user={user.id}, "
                f"payload_user={payload_user_id}, paid={payment.total_amount}, expected={stars}"
            )
            await update.message.reply_text("⚠️ تعذّر التحقق من عملية الدفع.", reply_markup=main_menu_kb(is_own))
            return

        rate = int(get_setting("star_to_points") or "250")
        pts = stars * rate
        already_credited = False

        # Telegram can retry a successful-payment update. Record and credit in
        # the same database transaction so a retry never gives the same payment
        # points twice.
        with db_conn() as c:
            # Lock by Telegram's immutable charge ID even when the first
            # callback has not inserted its transaction row yet.
            c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (charge_id,))
            existing = c.execute(
                "SELECT status FROM star_transactions "
                "WHERE telegram_payment_id=%s FOR UPDATE",
                (charge_id,)
            ).fetchone()

            if existing and existing["status"] == "completed":
                already_credited = True
            else:
                # The user normally exists already, but UPSERT makes the
                # payment handler safe when the first update is the payment.
                c.execute(
                    "INSERT INTO users (user_id,username,full_name,points) "
                    "VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "points=COALESCE(users.points,0)+EXCLUDED.points, "
                    "username=COALESCE(EXCLUDED.username,users.username), "
                    "full_name=COALESCE(EXCLUDED.full_name,users.full_name)",
                    (user.id, user.username, user.full_name, pts)
                )
                if existing:
                    c.execute(
                        "UPDATE star_transactions "
                        "SET status='completed', points_given=%s "
                        "WHERE telegram_payment_id=%s",
                        (pts, charge_id)
                    )
                else:
                    c.execute(
                        "INSERT INTO star_transactions "
                        "(user_id,stars,points_given,telegram_payment_id,status) "
                        "VALUES (%s,%s,%s,%s,'completed')",
                        (user.id, stars, pts, charge_id)
                    )

        if already_credited:
            await update.message.reply_text(
                "✅ هذه العملية مضافة مسبقاً إلى رصيدك.\n"
                f"💰 رصيد الشحن: {pts} نقطة\n"
                "⚠️ النجوم المدفوعة نهائية ولا تُسترد.",
                reply_markup=main_menu_kb(is_own)
            )
            return

        await update.message.reply_text(
            "✅ تم الشحن تلقائياً بنجاح!\n\n"
            f"⭐ المدفوع: {stars} نجمة\n"
            f"💎 تمت إضافة: {pts} نقطة إلى رصيدك\n"
            "⚠️ النجوم المدفوعة نهائية ولا تُسترد أو تُعاد بأي طريقة.",
            reply_markup=main_menu_kb(is_own)
        )

    # ─── الخدمات الأسطورية بالنجوم ───
    elif payload.startswith("legendary_stars:"):
        from .legendary_comment import execute_legendary_order, get_service_display_name

        parts = payload.split(":")
        if (
            len(parts) != 5
            or not parts[1].isdigit()
            or not parts[3].isdigit()
            or not parts[4].isdigit()
        ):
            await update.message.reply_text(
                "⚠️ بيانات دفع الخدمة الأسطورية غير صالحة.",
                reply_markup=main_menu_kb(is_own),
            )
            return

        payload_user_id = int(parts[1])
        service_type = parts[2]
        quantity = int(parts[3])
        expected_stars = int(parts[4])
        allowed_services = {
            "comment", "poll", "story", "votes", "votes_ai", "premium_reaction"
        }
        if (
            payload_user_id != user.id
            or service_type not in allowed_services
            or quantity < 1
            or expected_stars < 1
            or payment.total_amount != expected_stars
        ):
            logger.error(
                "❌ بيانات دفع الخدمة الأسطورية غير متطابقة: "
                f"user={user.id}, payload_user={payload_user_id}, "
                f"service={service_type}, paid={payment.total_amount}, expected={expected_stars}"
            )
            await update.message.reply_text(
                "⚠️ تعذّر التحقق من عملية الدفع.",
                reply_markup=main_menu_kb(is_own),
            )
            return

        # يمنع تنفيذ الطلب مرة أخرى إذا أعاد تيليغرام إشعار الدفع.
        if context.user_data.get("legendary_payment_charge_id") == payment.telegram_payment_charge_id:
            return
        context.user_data["legendary_payment_charge_id"] = payment.telegram_payment_charge_id

        if (
            context.user_data.get("legendary_service_type") != service_type
            or context.user_data.get("legendary_quantity") != quantity
        ):
            await update.message.reply_text(
                "⚠️ انتهت جلسة الطلب قبل تأكيد الدفع. تواصل مع المالك لمراجعة العملية.",
                reply_markup=main_menu_kb(is_own),
            )
            return

        context.user_data["legendary_stars_cost"] = expected_stars

        # Create progress message
        progress_message = await update.message.reply_text(
            f"⏳ تم تأكيد الدفع بالنجوم، جاري بدء تنفيذ خدمة {get_service_display_name(service_type)}..."
        )

        # We need to create a dummy callback query object for execute_legendary_order
        class DummyQ:
            def __init__(self, msg):
                self.message = msg
                self.from_user = update.effective_user
            async def edit_message_text(self, text, **kwargs):
                return await progress_message.edit_text(text, **kwargs)
            async def delete_message(self):
                return await progress_message.delete()

        dummy_q = DummyQ(progress_message)

        await execute_legendary_order(
            update,
            context,
            dummy_q,
            is_own,
            "stars",
        )

    # ─── إحالة بوت إجبارية بالنجوم ───
    elif payload.startswith("forced_ref_stars:"):
        parts           = payload.split(":")
        _uid            = int(parts[1])
        qty             = int(parts[2])
        total_stars     = int(parts[3])
        use_ai          = parts[4] == '1'
        cost_pts_ch     = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 0
        avail = get_forced_ref_account_count()
        if qty < 1 or qty > avail:
            await update.message.reply_text(
                f'⚠️ تعذّر تنفيذ الطلب: الحسابات المتاحة الآن {avail}.',
                reply_markup=main_menu_kb(is_own)
            )
            return
        # استرجاع بيانات البوت من السياق
        _draft = context.user_data.get('forced_ref_draft', {})
        bot_user = _draft.get('bot_user', '')
        start_p  = _draft.get('start_p', '')
        channels = _draft.get('channels', '')
        delay_seconds = _draft.get('delay_seconds') if user.id == OWNER_ID else None
        if not bot_user:
            await update.message.reply_text(
                '⚠️ تعذّر استرجاع بيانات الطلب. ابدأ من جديد.',
                reply_markup=main_menu_kb(is_own)
            )
            return
        code = next_order_code(user.id)
        with db_conn() as c:
            row = c.execute(
                'INSERT INTO forced_ref_orders '
                '(user_id,bot_username,start_param,channels,quantity,cost_points,cost_stars,payment_method,status,order_code) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
                (user.id, bot_user, start_p, channels, qty, cost_pts_ch, total_stars, 'stars', 'pending', code)
            ).fetchone()
            order_id = row['id']
        context.user_data.pop('forced_ref_draft', None)
        _code_fr = f'`{start_p}`' if start_p else 'بدون كود'
        ch_line  = f'\n📢 القنوات: `{channels}`' if channels else ''
        ch_pts_line = f'\n💎 نقاط القنوات المخصومة: {cost_pts_ch:,}' if cost_pts_ch > 0 else ''
        await update.message.reply_text(
            f'✅ *تم استلام طلبك!*\n\n'
            f'📌 `@{bot_user}` | كود: {_code_fr}{ch_line}\n'
            f'🔢 {qty} حساب | ⭐ {total_stars:,} نجمة{ch_pts_line}\n'
            f'🎫 كود: `{code}`\n\n'
            f'⏳ سيبدأ التنفيذ قريباً وستصلك إشعار عند الانتهاء.',
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )
        await _maybe_send_to_group(
            context.application.bot, user.id,
            f'تم إحالة بوت إجباري العدد {qty}',
            parse_mode='Markdown'
        )
        import asyncio as _aio_fr
        _aio_fr.create_task(_run_forced_ref_order(
            order_id, bot_user, start_p, channels, qty, user.id, context,
            use_ai=use_ai, payment_method='stars', cost_stars=total_stars,
            delay_seconds=delay_seconds
        ))

    # ─── شراء رقم تيلغرام بالنجوم — تسليم تلقائي ───
    elif payload.startswith("number_stars:"):
        parts = payload.split(":")
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            await update.message.reply_text("⚠️ بيانات شراء الرقم غير صالحة.", reply_markup=main_menu_kb(is_own))
            return

        payload_user_id = int(parts[1])
        stars = int(parts[2])
        charge_id = payment.telegram_payment_charge_id
        if payload_user_id != user.id or payment.total_amount != stars:
            logger.error(
                f"❌ بيانات شراء رقم بالنجوم غير متطابقة: user={user.id}, "
                f"payload_user={payload_user_id}, paid={payment.total_amount}, expected={stars}"
            )
            await update.message.reply_text("⚠️ تعذّر التحقق من عملية الدفع.", reply_markup=main_menu_kb(is_own))
            return

        # Reserve the payment before doing the network-heavy stock checks.
        # A duplicate Telegram update will see "processing" and cannot receive
        # a second number.
        already_completed = False
        with db_conn() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (charge_id,))
            existing = c.execute(
                "SELECT status,phone_number FROM number_star_purchases "
                "WHERE telegram_payment_id=%s FOR UPDATE",
                (charge_id,)
            ).fetchone()

            if existing and existing["status"] == "completed" and existing["phone_number"]:
                auto_number = existing["phone_number"]
                already_completed = True
            elif existing and existing["status"] == "processing":
                await update.message.reply_text(
                    "⏳ تم استلام الدفع، وجارٍ تجهيز الرقم تلقائياً. "
                    "سيصلك الرقم برسالة منفصلة قريباً.",
                    reply_markup=main_menu_kb(is_own)
                )
                return
            elif existing:
                # Old pending_manual rows are intentionally not re-delivered:
                # they may already have been handled by the owner.
                await update.message.reply_text(
                    "⏳ هذا الطلب مسجل مسبقاً وسيتم إكمال تسليمه من الإدارة.",
                    reply_markup=main_menu_kb(is_own)
                )
                return
            else:
                c.execute(
                    "INSERT INTO number_star_purchases "
                    "(telegram_payment_id,user_id,stars,status) "
                    "VALUES (%s,%s,%s,'processing')",
                    (charge_id, user.id, stars)
                )
                auto_number = None

        if auto_number and already_completed:
            await update.message.reply_text(
                "✅ تم تسليم هذا الرقم مسبقاً.\n"
                f"📱 الرقم: `{auto_number.lstrip('+')}`\n"
                "استخدم الأزرار في رسالتك السابقة للحصول على بيانات الدخول.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🔐 رمز التحقق (2FA)", callback_data=f"buyer:show_twofa:{auto_number}"),
                        InlineKeyboardButton("🔑 كود الدخول", callback_data=f"buyer:request_code:{auto_number}"),
                    ],
                    [InlineKeyboardButton("📷 دخول عبر QR", callback_data=f"buyer:barcode:{auto_number}")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ])
            )
            return

        if auto_number:
            code = next_order_code(user.id)
            with db_conn() as c:
                pe = c.execute(
                    "INSERT INTO prize_exchanges "
                    "(user_id,prize_type,prize_value,points_cost,status,order_code) "
                    "VALUES (%s,%s,%s,0,'completed',%s) RETURNING id",
                    (user.id, "telegram_number_stars", auto_number, code)
                ).fetchone()
                c.execute(
                    "UPDATE number_star_purchases "
                    "SET status='completed',phone_number=%s "
                    "WHERE telegram_payment_id=%s",
                    (auto_number, charge_id)
                )
        else:
            auto = await assign_verified_number(user.id, bot=context.bot)
            if not auto:
                with db_conn() as c:
                    c.execute(
                        "UPDATE number_star_purchases SET status='pending_manual' "
                        "WHERE telegram_payment_id=%s",
                        (charge_id,)
                    )
                await update.message.reply_text(
                    "✅ تم استلام الدفع، لكن لا يوجد حالياً رقم صالح في المخزون.\n"
                    "تم حفظ طلبك وسيتم تسليمه عند توفر رقم.",
                    reply_markup=main_menu_kb(is_own)
                )
                await _notify_owner_manual_star_purchase(
                    context,
                    "🛒 شراء رقم بالنجوم يحتاج تدخلاً بسبب نفاد المخزون\n\n"
                    f"👤 User ID: {user.id}\n"
                    f"⭐ النجوم: {stars}\n"
                    f"🧾 Payment ID: {charge_id}"
                )
                return

            auto_number = auto["phone_number"]
            code = next_order_code(user.id)
            with db_conn() as c:
                pe = c.execute(
                    "INSERT INTO prize_exchanges "
                    "(user_id,prize_type,prize_value,points_cost,status,order_code) "
                    "VALUES (%s,%s,%s,0,'completed',%s) RETURNING id",
                    (user.id, "telegram_number_stars", auto_number, code)
                ).fetchone()
                c.execute(
                    "UPDATE number_star_purchases "
                    "SET status='completed',phone_number=%s "
                    "WHERE telegram_payment_id=%s",
                    (auto_number, charge_id)
                )

        display_number = auto_number.lstrip("+")
        result_kb = [
            [
                InlineKeyboardButton("🔐 رمز التحقق (2FA)", callback_data=f"buyer:show_twofa:{auto_number}"),
                InlineKeyboardButton("🔑 كود الدخول", callback_data=f"buyer:request_code:{auto_number}"),
            ],
            [InlineKeyboardButton("📷 دخول عبر QR", callback_data=f"buyer:barcode:{auto_number}")],
            [InlineKeyboardButton("🚪 مغادرة البوت", callback_data=f"buyer:leave_account:{auto_number}")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
        ]
        await update.message.reply_text(
            "✅ *تم شراء الرقم وتسليمه تلقائياً!*\n\n"
            f"⭐ المدفوع: {stars} نجمة\n"
            f"📱 *الرقم:*\n`{display_number}`\n\n"
            "اضغط على الأزرار للحصول على رمز التحقق أو كود الدخول.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(result_kb)
        )
        try:
            await context.bot.send_message(
                user.id,
                "📋 *إشعار تبرئة ذمة — يُرجى القراءة بعناية*\n\n"
                "بإتمامك عملية الشراء فإنك توافق على أن الرقم والحساب أصبحا مسؤوليتك، "
                "ولا يتحمل البائع مسؤولية أي حظر أو تقييد لاحق من تيليغرام.\n\n"
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
                    "📱 <b>شراء رقم تيلغرام بالنجوم — تسليم تلقائي ✅</b>\n"
                    f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                    f"📱 الرقم: <code>{auto_number}</code>\n"
                    f"⭐ {stars} نجمة\n"
                    f"📌 {code}"
                ),
                group_text_html=(
                    "📱 <b>شراء رقم تيلغرام بالنجوم — تسليم تلقائي ✅</b>\n"
                    f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                    f"⭐ {stars} نجمة\n"
                    f"📌 {code}"
                ),
            )
        return

    # ─── تمويل الاشتراك الإجباري بالنجوم ───
    elif payload.startswith("fund_mandatory:"):
        parts        = payload.split(":")
        _uid         = int(parts[1])
        member_count = int(parts[2])
        channel      = parts[3]
        total_stars  = int(parts[4])
        channel_md   = md_escape(channel)

        is_queued = False
        if count_active_mandatory_channels() >= MANDATORY_MAX_ACTIVE:
            is_queued = True

        code = next_order_code(user.id)
        with db_conn() as c:
            c.execute(
                "INSERT INTO channel_funding (user_id,channel_username,funding_type,cost_points,target_members,current_members,status) "
                "VALUES (%s,%s,'mandatory',0,%s,0,'active')",
                (user.id, channel, member_count)
            )
            c.execute(
                "INSERT INTO mandatory_channels (channel_username,owner_user_id,funding_type,active,queued) "
                "VALUES (%s,%s,'mandatory',%s,%s) "
                "ON CONFLICT (channel_username) DO UPDATE SET funding_type=EXCLUDED.funding_type, owner_user_id=EXCLUDED.owner_user_id, "
                "active=EXCLUDED.active, queued=EXCLUDED.queued",
                (channel, user.id, 0 if is_queued else 1, 1 if is_queued else 0)
            )

        if is_queued:
            await update.message.reply_text(
                f"⏳ *تم استلام تمويل قناتك بنجاح — في قائمة الانتظار!*\n\n"
                f"📢 القناة: @{channel_md}\n"
                f"👥 عدد الأعضاء: {member_count:,}\n"
                f"⭐ دفعت: {total_stars} نجمة\n\n"
                f"⚠️ عدد القنوات الإجبارية النشطة بلغ الحد الأقصى ({MANDATORY_MAX_ACTIVE}).\n"
                f"✅ ستُفعَّل قناتك تلقائياً فور تحرّر أحد الأماكن.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
        else:
            await update.message.reply_text(
                f"✅ *تم تفعيل قناتك الإجبارية بنجاح!*\n\n"
                f"📢 القناة: @{channel_md}\n"
                f"👥 عدد الأعضاء: {member_count:,}\n"
                f"⭐ دفعت: {total_stars} نجمة\n"
                f"📌 كود العملية: `{code}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )

        _queue_note = "\n⏳ <b>ملاحظة:</b> دخلت قائمة الانتظار وستُفعَّل عند توفر مكان." if is_queued else ""
        _terms = mandatory_terms_text_html()
        try:
            await context.application.bot.send_message(
                ADMIN_GROUP_ID,
                f"📢 <b>تمويل قناة إجباري — نجوم</b>\n"
                f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                f"📡 القناة: @{channel}\n"
                f"👥 {member_count:,} عضو\n"
                f"⭐ {total_stars} نجمة\n"
                f"📌 {code}"
                f"{_queue_note}\n"
                f"{_terms}",
                parse_mode="HTML"
            )
        except Exception:
            pass

async def delete_group_service_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"⚠️ فشل حذف رسالة انضمام/مغادرة في كروب الإشعارات: {e}")

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
async def handle_bot_removed_from_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عندما يُزال البوت من قناة:
    1. احذف القناة من طلبات الاشتراك الإجباري النشطة (mandatory_sub_orders).
    2. أوقف القناة في جدول mandatory_channels (الاشتراك الإجباري الرئيسي والداخلي).
    """
    cmu = update.my_chat_member
    if not cmu:
        return
    new_status = cmu.new_chat_member.status
    if new_status not in ("left", "kicked", "banned"):
        return
    chat = cmu.chat
    username = (chat.username or "").lstrip("@").lower()
    if not username:
        return
    try:
        # ── 1. حذف القناة من طلبات mandatory_sub_orders النشطة ──
        with db_conn() as c:
            orders = c.execute(
                "SELECT id, channels FROM mandatory_sub_orders "
                "WHERE status IN ('pending','running') AND channels != '' AND channels IS NOT NULL"
            ).fetchall()
        updated = 0
        for o in orders:
            raw = o["channels"] or ""
            tokens = raw.split()
            new_tokens = [
                t for t in tokens
                if t.lstrip("@").lower().split("?")[0].rstrip("/") != username
                and t.lower().replace("https://t.me/","").replace("https://telegram.me/","").lstrip("+").rstrip("/") != username
            ]
            if len(new_tokens) != len(tokens):
                new_channels = " ".join(new_tokens)
                with db_conn() as c:
                    c.execute(
                        "UPDATE mandatory_sub_orders SET channels=%s WHERE id=%s",
                        (new_channels, o["id"])
                    )
                updated += 1
        if updated:
            logger.info(f"🔕 البوت أُزيل من @{username} — حُذفت من {updated} طلب اشتراك إجباري")

        # ── 2. إيقاف القناة من mandatory_channels (رئيسي وداخلي) ──
        with db_conn() as c:
            deactivated = c.execute(
                "UPDATE mandatory_channels SET active=0, queued=0 "
                "WHERE lower(channel_username)=%s AND (active=1 OR queued=1)",
                (username,)
            ).rowcount
        if deactivated:
            logger.info(f"🔕 تم إيقاف القناة @{username} من mandatory_channels ({deactivated} صف)")
            # تفعيل القناة التالية في قائمة الانتظار (إن وُجدت) لملء الفراغ
            try:
                await promote_queued_mandatory_channel(context)
            except Exception as _pe:
                logger.warning(f"promote_queued_mandatory_channel error: {_pe}")

    except Exception as _e:
        logger.warning(f"handle_bot_removed_from_channel error: {_e}")


async def handle_member_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmu = update.chat_member
    if not cmu:
        return
    old_status = cmu.old_chat_member.status
    new_status = cmu.new_chat_member.status
    member_user = cmu.new_chat_member.user
    if member_user.is_bot:
        return
    was_in = old_status in ("member", "administrator", "creator", "restricted")
    now_out = new_status in ("left", "kicked")
    if not (was_in and now_out):
        return
    username = (cmu.chat.username or "").lstrip("@")
    if not username:
        return
    with db_conn() as c:
        ch = c.execute(
            "SELECT * FROM mandatory_channels WHERE channel_username=? AND funding_type='internal' AND active=1",
            (username,)
        ).fetchone()
    if not ch:
        return
    with db_conn() as c:
        claimed = c.execute(
            "SELECT joined_at FROM channel_join_rewards WHERE user_id=? AND channel_id=?",
            (member_user.id, ch["id"])
        ).fetchone()
        if not claimed:
            return
        # ─── فحص مهلة المغادرة الآمنة (24 ساعة افتراضياً) ───
        grace_hours = int(get_setting("internal_leave_grace_hours") or "24")
        joined_at = claimed["joined_at"]
        if joined_at:
            import datetime as _dt_grace
            now_utc = _dt_grace.datetime.now(_dt_grace.timezone.utc)
            if hasattr(joined_at, "tzinfo") and joined_at.tzinfo is None:
                joined_at = joined_at.replace(tzinfo=_dt_grace.timezone.utc)
            time_passed = now_utc - joined_at
            if time_passed.total_seconds() >= grace_hours * 3600:
                c.execute(
                    "DELETE FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                    (member_user.id, ch["id"])
                )
                return
        c.execute(
            "DELETE FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
            (member_user.id, ch["id"])
        )
    # ─── خصم النقاط — يُسمح بالرصيد السالب ───
    penalty = int(get_setting("channel_leave_penalty") or "75")
    with db_conn() as _pc:
        _pc.execute("UPDATE users SET points=points-%s WHERE user_id=%s", (penalty, member_user.id))
    db_u = get_user(member_user.id)
    balance_after = db_u["points"] if db_u else 0
    try:
        await context.bot.send_message(
            member_user.id,
            f"⚠️ *تنبيه خصم نقاط*\n\n"
            f"لاحظنا أنك غادرت القناة @{username} خلال مهلة {grace_hours} ساعة من انضمامك.\n"
            f"💸 تم خصم *{penalty} نقطة* من رصيدك.\n"
            f"💰 رصيدك الآن: *{balance_after} نقطة*\n\n"
            f"يمكنك الانضمام للقناة مجدداً من قسم 💰 تجميع النقاط لكسب النقاط من جديد.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        pass

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /broadcast <رسالة> — يبث رسالة HTML لجميع المستخدمين."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    if not context.args:
        await update.message.reply_text("الاستخدام:\n/broadcast <نص الرسالة>")
        return
    broadcast_text = " ".join(context.args)
    with db_conn() as c:
        users_list = c.execute("SELECT user_id FROM users").fetchall()
    sent, failed = 0, 0
    for u_row in users_list:
        try:
            await context.bot.send_message(u_row["user_id"], broadcast_text, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"✅ أُرسلت: {sent} | ❌ فشل: {failed}")

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر عام: /cancel — يوقف أي عملية إدخال نصي معلّقة (مثل حلقة إضافة أرقام متتالية) ويرجع للقائمة."""
    user = update.effective_user
    if user and (user.id == OWNER_ID or _pending_number_logins.get(user.id)):
        await _cleanup_pending_login(user.id)
    if user:
        _pending_supervisor_logins.pop(user.id, None)
    context.user_data["state"] = "main_menu"
    _is_sv = user and is_supervisor(user.id) and (user.id != OWNER_ID)
    if user and user.id == OWNER_ID:
        kb = owner_settings_kb()
    elif _is_sv:
        kb = supervisor_panel_kb()
    else:
        kb = main_menu_kb()
    await update.message.reply_text("🔙 تم التوقف والرجوع للقائمة الرئيسية.", reply_markup=kb)

async def cmd_status_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /status <كود_الطلب> — يعرض تفاصيل طلب بكوده."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    if not context.args:
        await update.message.reply_text("الاستخدام:\n/status <كود_الطلب>")
        return
    code = context.args[0].strip()
    with db_conn() as c:
        order = c.execute(
            "SELECT o.*, s.name_ar FROM orders o LEFT JOIN services s ON s.id=o.service_id WHERE o.order_code=?",
            (code,)
        ).fetchone()
    if not order:
        await update.message.reply_text(f"⚠️ لا يوجد طلب بالكود: {code}")
        return
    status_map = {"pending": "⏳ قيد الانتظار", "completed": "✅ مكتمل", "cancelled": "❌ ملغى"}
    status_label = status_map.get(order["status"], order["status"])
    await update.message.reply_text(
        f"📋 *تفاصيل الطلب*\n\n"
        f"📌 الكود: `{order['order_code']}`\n"
        f"👤 المستخدم: {order['user_id']}\n"
        f"🔹 الخدمة: {order['name_ar'] or '—'}\n"
        f"🔗 الرابط: {order['link']}\n"
        f"🔢 الكمية: {order['quantity']}\n"
        f"💰 التكلفة: {order['cost_points']} نقطة\n"
        f"📊 الحالة: {status_label}\n"
        f"🆔 كود API: {order['api_order_id'] or '—'}\n"
        f"🕐 التاريخ: {order['created_at']}",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_compensate_partial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /compensate_partial
    يفحص جميع طلبات المواقع المكتملة التي لم تحصل على تعويض جزئي بعد،
    يسأل موقع الرشق عن حالتها، وإن كانت Partial يحسب قيمة الجزء غير المنفذ
    ويعيدها كمجوهرات بدقة عشرية."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return

    await update.message.reply_text(
        "🔍 جاري فحص الطلبات المكتملة للبحث عن طلبات جزئية غير معوَّضة...\n"
        "⏳ قد يستغرق هذا بعض الوقت حسب عدد الطلبات."
    )

    try:
        with db_conn() as c:
            candidates = c.execute(
                "SELECT o.*, s.panel AS svc_panel, s.api_service_id AS svc_api_id "
                "FROM orders o "
                "LEFT JOIN services s ON s.id = o.service_id "
                "WHERE o.status='completed' "
                "  AND COALESCE(o.refund_points, 0) = 0 "
                "  AND COALESCE(o.partial_refund_pts, 0) = 0 "
                "  AND COALESCE(o.refund_jewels, 0) = 0 "
                "  AND o.api_order_id IS NOT NULL AND o.api_order_id != '' "
            ).fetchall()
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في جلب الطلبات: {e}")
        return

    if not candidates:
        await update.message.reply_text("✅ لا توجد طلبات تحتاج فحصاً.")
        return

    await update.message.reply_text(f"📋 عدد الطلبات المراد فحصها: {len(candidates):,}")

    compensated, skipped, errors = 0, 0, 0
    total_jewels_given = Decimal("0")

    for o in candidates:
        try:
            panel = o.get("svc_panel") or 1
            res = await asyncio.to_thread(
                smm_order_status, o["api_order_id"], panel=panel
            )
        except Exception:
            errors += 1
            continue

        if not isinstance(res, dict) or "error" in res:
            skipped += 1
            continue

        panel_status = str(res.get("status", "")).strip().lower()

        if panel_status != "partial":
            skipped += 1
            continue

        remains = int(res.get("remains", 0) or 0)
        if remains <= 0 or not o.get("svc_api_id"):
            skipped += 1
            continue

        refund_jewels = _calc_partial_refund_jewels(
            o["svc_api_id"],
            remains,
            panel,
            o.get("provider_rate_usd") or 0,
        )
        if refund_jewels <= 0:
            skipped += 1
            continue

        settled = _settle_smm_order(
            o["id"],
            o["user_id"],
            0,
            "completed",
            refund_jewels=refund_jewels,
            partial=True,
            allow_completed=True,
        )
        if not settled:
            skipped += 1
            continue

        try:
            await context.bot.send_message(
                o["user_id"],
                f"💰 *تعويض طلب جزئي*\n\n"
                f"📌 كود الطلب: `{o['order_code']}`\n"
                f"📦 الوحدات غير المنفذة: {remains:,}\n"
                f"✅ تم إضافة *{fmt_jewel_amount(refund_jewels)}* مجوهرة إلى رصيدك تعويضاً.\n\n"
                f"نعتذر عن التأخير في هذا التعويض.",
                parse_mode="Markdown"
            )
        except Exception:
            pass

        compensated += 1
        total_jewels_given += refund_jewels
        logger.info(
            f"✅ تعويض جزئي: طلب {o['order_code']} — "
            f"{fmt_jewel_amount(refund_jewels)} مجوهرة → {o['user_id']}"
        )

    await update.message.reply_text(
        f"✅ *انتهى فحص التعويضات*\n\n"
        f"💚 طلبات عُوِّضت: {compensated}\n"
        f"💎 إجمالي المجوهرات الموزّعة: {fmt_jewel_amount(total_jewels_given)}\n"
        f"⏭ طلبات تخطّيها (غير جزئية): {skipped}\n"
        f"❌ أخطاء API: {errors}",
        parse_mode="Markdown"
    )

async def cmd_refund_mandatory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /refund_mandatory
    كان هنالك خلل في تفعيل الاشتراك الإجباري يجعل المستخدمين القدامى لا يُطالَبون
    بالانضمام للقنوات الإجبارية الجديدة (تم إصلاحه الآن). هذا الأمر يعيد نقاط كل من
    دفع لتفعيل «تمويل قناة إجباري سريع» ولم يُسترجع له ماله بعد، ويرسل له اعتذاراً
    مع طلب إعادة تفعيل تمويل قناته من جديد بعد الإصلاح."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return

    with db_conn() as c:
        fundings = c.execute(
            "SELECT * FROM channel_funding WHERE funding_type='mandatory' AND status != 'refunded'"
        ).fetchall()

    if not fundings:
        await update.message.reply_text("✅ لا توجد تمويلات إجبارية بحاجة لاسترجاع.")
        return

    await update.message.reply_text(
        f"🔍 تم العثور على {len(fundings):,} تمويل إجباري. جاري إعادة النقاط والاعتذار لأصحابها..."
    )

    refunded, errors, total_pts = 0, 0, 0
    for f in fundings:
        pts = f.get("cost_points", 0) or 0
        try:
            if pts:
                add_points(f["user_id"], pts)
            with db_conn() as c:
                c.execute("UPDATE channel_funding SET status='refunded' WHERE id=?", (f["id"],))
                c.execute(
                    "UPDATE mandatory_channels SET active=0, queued=0 WHERE channel_username=? AND funding_type='mandatory'",
                    (f["channel_username"],)
                )
        except Exception as e:
            logger.warning(f"⚠️ فشل استرجاع تمويل القناة @{f.get('channel_username')}: {e}")
            errors += 1
            continue

        try:
            await context.bot.send_message(
                f["user_id"],
                f"🙏 *اعتذار بخصوص تمويل قناتك @{f['channel_username']}*\n\n"
                f"اكتشفنا خللاً فنياً كان يمنع القناة الإجبارية من الظهور لبعض\n"
                f"المستخدمين القدامى في البوت، ما أثّر على نتيجة تمويلك.\n\n"
                f"✅ تم إعادة *{pts:,}* نقطة كاملة إلى رصيدك تعويضاً عن ذلك.\n"
                f"🛠 تم إصلاح الخلل الآن بالكامل، وأصبحت القنوات الإجبارية تظهر لجميع\n"
                f"المستخدمين (القدامى والجدد) في كل مرة يستخدمون فيها البوت.\n\n"
                f"🔁 يمكنك الآن إعادة طلب «📺 تمويل قناتك حقيقي ← تمويل قناة إجباري سريع»\n"
                f"من القائمة الرئيسية لتفعيل تمويل قناتك من جديد والاستفادة الكاملة منه.\n\n"
                f"نعتذر عن الإزعاج ونشكر تفهمك 🌹",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

        refunded += 1
        total_pts += pts
        logger.info(f"✅ استرجاع تمويل إجباري: @{f['channel_username']} — {pts:,} نقطة → {f['user_id']}")

    await promote_queued_mandatory_channel(context, app=context.application)

    await update.message.reply_text(
        f"✅ *انتهى استرجاع تمويلات الاشتراك الإجباري*\n\n"
        f"💚 عدد من تم استرجاع تمويله: {refunded}\n"
        f"💰 إجمالي النقاط المُعادة: {total_pts:,}\n"
        f"❌ أخطاء: {errors}",
        parse_mode=ParseMode.MARKDOWN
    )
