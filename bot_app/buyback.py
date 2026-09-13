"""Member Telegram-account buyback flow.

The flow keeps a submitted account in quarantine until two delayed checks pass.
It deliberately requires the owner to confirm the final payout manually.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})
from .accounts import check_spam_status_detailed

BUYBACK_VISIBLE_KEY = "buyback_visible"
BUYBACK_PRICE_KEY = "buyback_price"
BUYBACK_RESTRICTED_PRICE_KEY = "buyback_restricted_price"
DEFAULT_BUYBACK_PRICE = 7000
DEFAULT_BUYBACK_RESTRICTED_PRICE = 4000
BUYBACK_ACTIVE_STATUSES = (
    "awaiting_seller_confirm",
    "quarantine_24h",
    "quarantine_48h",
    "ready_for_payment",
)

# Login clients live only for the short code/2FA hand-off flow.  Keep this
# process-local and never persist the raw login code or 2FA password.
_pending_buyback_logins = {}


def is_buyback_visible() -> bool:
    return str(get_setting(BUYBACK_VISIBLE_KEY) or "0") == "1"


def set_buyback_visible(enabled: bool) -> bool:
    set_setting(BUYBACK_VISIBLE_KEY, "1" if enabled else "0")
    return bool(enabled)


def _buyback_price(restricted: bool = False) -> int:
    key = BUYBACK_RESTRICTED_PRICE_KEY if restricted else BUYBACK_PRICE_KEY
    default = DEFAULT_BUYBACK_RESTRICTED_PRICE if restricted else DEFAULT_BUYBACK_PRICE
    try:
        amount = int(get_setting(key) or default)
        return amount if amount > 0 else default
    except (TypeError, ValueError):
        return default


def set_buyback_price(points: int) -> int:
    """يحفظ سعر شراء الحساب بالنقاط ويعيد القيمة التي تم اعتمادها."""
    amount = int(points)
    if amount <= 0:
        raise ValueError("يجب أن يكون السعر أكبر من صفر")
    set_setting(BUYBACK_PRICE_KEY, str(amount))
    return amount


def format_buyback_price(price: int | str | None) -> str:
    """يعرض السعر الموحد في رسائل البائع والمالك."""
    try:
        amount = int(price or DEFAULT_BUYBACK_PRICE)
    except (TypeError, ValueError):
        amount = DEFAULT_BUYBACK_PRICE
    if amount <= 0:
        amount = DEFAULT_BUYBACK_PRICE
    return f"{amount:,} نقطة"


def _mask_buyback_phone(phone: str) -> str:
    phone = str(phone or "")
    if len(phone) <= 6:
        return "***"
    return phone[:4] + "***" + phone[-3:]


def _normalize_buyback_phone(raw: str) -> str | None:
    phone = (raw or "").strip().replace(" ", "")
    if phone and not phone.startswith("+") and phone.isdigit():
        phone = "+" + phone
    if not phone.startswith("+") or not phone[1:].isdigit() or len(phone) < 8 or len(phone) > 16:
        return None
    return phone


def _buyback_cancel_markup():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ إلغاء", callback_data="buyback:cancel")
    ]])


def _buyback_confirm_markup(offer_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ أؤكد بيع الحساب", callback_data=f"buyback:confirm:{offer_id}"),
        InlineKeyboardButton("❌ إلغاء", callback_data=f"buyback:cancel:{offer_id}"),
    ]])


def _buyback_owner_markup(offer_id: int, ready: bool = False):
    rows = []
    if ready:
        rows.append([InlineKeyboardButton("💵 تم دفع المستحق", callback_data=f"buyback:owner:paid:{offer_id}")])
    rows.append([InlineKeyboardButton("🚫 رفض الطلب", callback_data=f"buyback:owner:reject:{offer_id}")])
    rows.append([InlineKeyboardButton("📋 تحديث الطلبات", callback_data="buyback:owner:list")])
    return InlineKeyboardMarkup(rows)


async def _disconnect_buyback_client(client) -> None:
    if client is not None:
        try:
            await client.disconnect()
        except Exception:
            pass


async def _clear_buyback_pending(user_id: int) -> None:
    pending = _pending_buyback_logins.pop(user_id, None)
    if pending:
        await _disconnect_buyback_client(pending.get("client"))


def _active_buyback_phone_exists(phone: str) -> bool:
    with db_conn() as c:
        row = c.execute(
            "SELECT id FROM account_buyback_offers "
            "WHERE phone_number=%s AND status IN "
            "('awaiting_seller_confirm','quarantine_24h','quarantine_48h','ready_for_payment') "
            "LIMIT 1",
            (phone,),
        ).fetchone()
        if row:
            return True
        stock = c.execute(
            "SELECT id FROM number_stock WHERE phone_number=%s AND deleted_at IS NULL LIMIT 1",
            (phone,),
        ).fetchone()
    return bool(stock)


async def _finish_buyback_login(update, context, user_id: int) -> bool:
    pending = _pending_buyback_logins.get(user_id)
    if not pending:
        await update.message.reply_text("⚠️ انتهت جلسة البيع. ابدأ من جديد من زر بيع الحساب.")
        context.user_data["state"] = "main_menu"
        return True

    client = pending.get("client")
    phone = pending.get("phone")
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=15):
            raise RuntimeError("الجلسة غير مصرح بها")
        me = await asyncio.wait_for(client.get_me(), timeout=15)
        if _active_buyback_phone_exists(phone):
            await update.message.reply_text(
                "⚠️ هذا الحساب موجود مسبقاً في طلب بيع أو في المخزون.",
                reply_markup=main_menu_kb(False),
            )
            context.user_data["state"] = "main_menu"
            return True

        session_string = client.session.save()
        username = getattr(me, "username", "") or ""
        with db_conn() as c:
            row = c.execute(
                "INSERT INTO account_buyback_offers "
                "(seller_user_id,phone_number,account_username,session_string,quoted_price,status) "
                "VALUES (%s,%s,%s,%s,0,'awaiting_seller_confirm') RETURNING id",
                (user_id, phone, username, session_string),
            ).fetchone()
        offer_id = int(row["id"])
        context.user_data["buyback_offer_id"] = offer_id
        context.user_data["state"] = "buyback_await_confirm"
        await update.message.reply_text(
            "🔎 تم الدخول إلى الحساب بنجاح.\n\n"
            f"📱 الرقم: {_mask_buyback_phone(phone)}\n"
            f"👤 المعرف: @{username if username else 'بدون معرف'}\n"
            f"💵 السعر النهائي يُحدد بعد فحص 48 ساعة: "
            f"{format_buyback_price(_buyback_price(restricted=True))} إذا كان مقيّداً، "
            f"أو {format_buyback_price(_buyback_price())} إذا كان سليماً.\n\n"
            "عند التأكيد سيتم تسجيل الحساب باسم البوت، وإلغاء الجلسات الأخرى، "
            "ثم يبقى تحت الفحص 48 ساعة قبل تحديد المبلغ النهائي. إذا كنت موافقاً اضغط تأكيد البيع.",
            reply_markup=_buyback_confirm_markup(offer_id),
        )
        return True
    except Exception as exc:
        logger.warning(f"⚠️ فشل تجهيز طلب شراء الحساب للعضو {user_id}: {exc}")
        await update.message.reply_text(
            "❌ تعذر تجهيز الحساب للبيع. لم يتم إنشاء طلب شراء.",
            reply_markup=main_menu_kb(False),
        )
        context.user_data["state"] = "main_menu"
        return True
    finally:
        _pending_buyback_logins.pop(user_id, None)
        await _disconnect_buyback_client(client)


async def handle_buyback_text(update, context, text: str) -> bool:
    state = context.user_data.get("state", "")
    user = update.effective_user
    if not state.startswith("buyback_"):
        return False

    if state == "buyback_await_phone":
        phone = _normalize_buyback_phone(text)
        if not phone:
            await update.message.reply_text(
                "⚠️ أرسل الرقم بصيغة دولية، مثال: +9647701234567",
                reply_markup=_buyback_cancel_markup(),
            )
            return True
        if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
            await update.message.reply_text("❌ إعدادات Telegram API غير مكتملة حالياً.", reply_markup=main_menu_kb(False))
            context.user_data["state"] = "main_menu"
            return True
        if _active_buyback_phone_exists(phone):
            await update.message.reply_text("⚠️ هذا الحساب موجود مسبقاً في طلب بيع أو في المخزون.", reply_markup=main_menu_kb(False))
            context.user_data["state"] = "main_menu"
            return True
        client = TelegramClient(StringSession(), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(client.connect(), timeout=20)
            sent = await asyncio.wait_for(client.send_code_request(phone), timeout=30)
        except FloodWaitError as exc:
            await _disconnect_buyback_client(client)
            await update.message.reply_text(f"⚠️ محاولات كثيرة على الرقم. انتظر {exc.seconds} ثانية.", reply_markup=main_menu_kb(False))
            context.user_data["state"] = "main_menu"
            return True
        except PhoneNumberInvalidError:
            await _disconnect_buyback_client(client)
            await update.message.reply_text("⚠️ الرقم غير صحيح.", reply_markup=_buyback_cancel_markup())
            return True
        except Exception as exc:
            await _disconnect_buyback_client(client)
            logger.warning(f"⚠️ تعذر إرسال كود شراء الحساب: {exc}")
            await update.message.reply_text("❌ تعذر إرسال الكود حالياً. حاول لاحقاً.", reply_markup=main_menu_kb(False))
            context.user_data["state"] = "main_menu"
            return True
        _pending_buyback_logins[user.id] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
        }
        context.user_data["state"] = "buyback_await_code"
        await update.message.reply_text("📩 أرسل كود الدخول الذي وصلك، ولن يتم حفظه.", reply_markup=_buyback_cancel_markup())
        return True

    if state == "buyback_await_code":
        pending = _pending_buyback_logins.get(user.id)
        if not pending:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("⚠️ انتهت جلسة الكود. ابدأ من جديد.", reply_markup=main_menu_kb(False))
            return True
        code = (text or "").replace(" ", "")
        try:
            await pending["client"].sign_in(pending["phone"], code, phone_code_hash=pending["phone_code_hash"])
        except SessionPasswordNeededError:
            context.user_data["state"] = "buyback_await_password"
            await update.message.reply_text("🔒 يوجد تحقق بخطوتين. أرسل كلمة المرور مرة واحدة فقط.", reply_markup=_buyback_cancel_markup())
            return True
        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            await update.message.reply_text("⚠️ الكود غير صحيح أو منتهي. أرسل الكود الصحيح.", reply_markup=_buyback_cancel_markup())
            return True
        except Exception as exc:
            logger.warning(f"⚠️ فشل كود شراء الحساب: {exc}")
            await _clear_buyback_pending(user.id)
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("❌ فشل تسجيل الدخول.", reply_markup=main_menu_kb(False))
            return True
        return await _finish_buyback_login(update, context, user.id)

    if state == "buyback_await_password":
        pending = _pending_buyback_logins.get(user.id)
        if not pending:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("⚠️ انتهت جلسة التحقق. ابدأ من جديد.", reply_markup=main_menu_kb(False))
            return True
        try:
            await pending["client"].sign_in(password=(text or "").strip())
        except PasswordHashInvalidError:
            await update.message.reply_text("⚠️ كلمة المرور غير صحيحة. أرسلها مجدداً.", reply_markup=_buyback_cancel_markup())
            return True
        except Exception as exc:
            logger.warning(f"⚠️ فشل تحقق 2FA لطلب شراء الحساب: {exc}")
            await _clear_buyback_pending(user.id)
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("❌ فشل التحقق.", reply_markup=main_menu_kb(False))
            return True
        return await _finish_buyback_login(update, context, user.id)

    if state == "buyback_await_confirm":
        await update.message.reply_text("استخدم أزرار التأكيد أو الإلغاء الظاهرة في الرسالة.")
        return True
    return False


async def _revoke_buyback_sessions(session_string: str) -> tuple[bool, str]:
    client = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return False, "الجلسة غير مصرح بها"
        await asyncio.wait_for(client(ResetAuthorizationsRequest()), timeout=30)
        return True, ""
    except Exception as exc:
        return False, str(exc)[:180]
    finally:
        await _disconnect_buyback_client(client)


async def _inspect_buyback_session(session_string: str) -> dict:
    """يفحص جلسة طلب البيع ويؤمّنها أثناء فترة الحجز.

    فشل الشبكة لا يلغي الطلب، بل يعيد الفحص في الدورة التالية. أما فقدان
    الجلسة أو ثبوت تقييد SpamBot فيُعامل كفشل نهائي. عند ظهور جلسة إضافية
    يحاول البوت طردها فوراً ثم يعيد قراءة التفويضات قبل اعتماد الفحص.
    """
    client = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    extra_session_removed = False
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return {
                "state": "reject",
                "reason": "الجلسة لم تعد مصرحاً بها",
                "extra_session_removed": False,
            }
        me = await asyncio.wait_for(client.get_me(), timeout=15)
        if not me:
            return {
                "state": "reject",
                "reason": "تعذر قراءة الحساب",
                "extra_session_removed": False,
            }
        auths = await asyncio.wait_for(client(GetAuthorizationsRequest()), timeout=20)
        sessions = getattr(auths, "authorizations", []) or []
        if len(sessions) > 1:
            try:
                await asyncio.wait_for(client(ResetAuthorizationsRequest()), timeout=30)
                extra_session_removed = True
                auths = await asyncio.wait_for(
                    client(GetAuthorizationsRequest()), timeout=20
                )
                sessions = getattr(auths, "authorizations", []) or []
            except Exception as exc:
                return {
                    "state": "retry",
                    "reason": f"ظهر دخول آخر وتعذر طرده مؤقتاً: {str(exc)[:140]}",
                    "extra_session_removed": False,
                }
            if len(sessions) > 1:
                return {
                    "state": "retry",
                    "reason": "ظهر دخول آخر وما زالت الجلسة الإضافية موجودة",
                    "extra_session_removed": extra_session_removed,
                }

        spam_detail = await asyncio.wait_for(
            check_spam_status_detailed(client), timeout=40
        )
        restricted = spam_detail.get("restricted")
        if restricted not in (True, False):
            return {
                "state": "retry",
                "reason": "تعذر التأكد من حالة الحساب عبر SpamBot مؤقتاً",
                "extra_session_removed": extra_session_removed,
            }
        return {
            "state": "ok",
            "reason": "",
            "restricted": bool(restricted),
            "extra_session_removed": extra_session_removed,
        }
    except Exception as exc:
        return {
            "state": "retry",
            "reason": str(exc)[:180],
            "extra_session_removed": extra_session_removed,
        }
    finally:
        await _disconnect_buyback_client(client)


async def _verify_buyback_session(session_string: str) -> tuple[bool, str]:
    """واجهة توافقية للفحص النهائي القديم."""
    result = await _inspect_buyback_session(session_string)
    return result["state"] == "ok", result["reason"]


async def _notify_buyback_user(context, user_id: int, text: str) -> None:
    try:
        await context.bot.send_message(user_id, text)
    except Exception as exc:
        logger.warning(f"⚠️ تعذر إشعار بائع الحساب {user_id}: {exc}")


async def _notify_buyback_owner(context, offer_id: int, ready: bool = False) -> None:
    if not OWNER_ID:
        return
    with db_conn() as c:
        row = c.execute(
            "SELECT seller_user_id,phone_number,account_username,quoted_price,status FROM account_buyback_offers WHERE id=%s",
            (offer_id,),
        ).fetchone()
    if not row:
        return
    price = (
        format_buyback_price(row["quoted_price"])
        if row["quoted_price"]
        else "يُحدد بعد فحص 48 ساعة"
    )
    text = (
        "💰 <b>طلب بيع حساب تيليجرام</b>\n\n"
        f"📌 الطلب: <code>#{offer_id}</code>\n"
        f"👤 البائع: <code>{row['seller_user_id']}</code>\n"
        f"📱 الرقم: <code>{html.escape(_mask_buyback_phone(row['phone_number']))}</code>\n"
        f"🔗 المعرف: @{html.escape(row['account_username'] or 'بدون معرف')}\n"
        f"💵 السعر: <b>{price}</b>\n"
        f"📊 الحالة: <code>{row['status']}</code>"
    )
    await context.bot.send_message(
        OWNER_ID,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=_buyback_owner_markup(offer_id, ready=ready),
    )


async def handle_buyback_callback(update, context, q, data: str, user, is_owner: bool) -> bool:
    if data == "buyback:start":
        if not is_owner and not is_buyback_visible():
            await q.answer("هذا القسم غير متاح حالياً.", show_alert=True)
            return True
        await q.edit_message_text(
            "💰 <b>بيع حساب تيليجرام</b>\n\n"
            "سيتم فحص ملكية الحساب أولاً. بعد موافقتك النهائية تُلغى الجلسات الأخرى، "
            "ويبقى الحساب تحت الحجز 48 ساعة. يتم دفع المبلغ بعد نجاح فحص 24 و48 ساعة.\n\n"
            "⚠️ لا تستخدم هذه الخدمة لحساب لا تملكه، ولا ترسل كوداً لحساب شخص آخر.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ بدء بيع الحساب", callback_data="buyback:begin")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="buyback:cancel")],
            ]),
        )
        return True

    if data == "buyback:begin":
        await _clear_buyback_pending(user.id)
        context.user_data["state"] = "buyback_await_phone"
        await q.edit_message_text("📱 أرسل رقم الحساب بصيغة دولية.", reply_markup=_buyback_cancel_markup())
        return True

    if data == "buyback:cancel" or data.startswith("buyback:cancel:"):
        await _clear_buyback_pending(user.id)
        offer_id = data.rsplit(":", 1)[-1] if data.count(":") == 2 else ""
        if offer_id.isdigit():
            with db_conn() as c:
                c.execute(
                    "UPDATE account_buyback_offers SET status='cancelled', session_string=NULL, updated_at=NOW() "
                    "WHERE id=%s AND seller_user_id=%s AND status='awaiting_seller_confirm'",
                    (int(offer_id), user.id),
                )
        context.user_data["state"] = "main_menu"
        await q.edit_message_text("❌ تم إلغاء طلب بيع الحساب.", reply_markup=main_menu_kb(False))
        return True

    if data.startswith("buyback:confirm:"):
        if is_owner:
            await q.answer("هذا الزر مخصص للبائع.", show_alert=True)
            return True
        try:
            offer_id = int(data.rsplit(":", 1)[-1])
        except ValueError:
            await q.answer("طلب غير صالح.", show_alert=True)
            return True
        with db_conn() as c:
            row = c.execute(
                "SELECT * FROM account_buyback_offers WHERE id=%s AND seller_user_id=%s AND status='awaiting_seller_confirm'",
                (offer_id, user.id),
            ).fetchone()
        if not row:
            await q.edit_message_text("⚠️ الطلب غير موجود أو انتهت صلاحيته.", reply_markup=main_menu_kb(False))
            return True
        ok, reason = await _revoke_buyback_sessions(row["session_string"])
        if not ok:
            with db_conn() as c:
                c.execute(
                    "UPDATE account_buyback_offers SET status='rejected', session_string=NULL, rejection_reason=%s, updated_at=NOW() WHERE id=%s",
                    (reason, offer_id),
                )
            await q.edit_message_text("❌ تعذر تأمين الحساب، لذلك لم يتم قبول البيع.", reply_markup=main_menu_kb(False))
            return True
        with db_conn() as c:
            c.execute(
                "UPDATE account_buyback_offers SET status='quarantine_24h', accepted_at=NOW(), next_check_at=NOW()+INTERVAL '24 hours', updated_at=NOW() WHERE id=%s",
                (offer_id,),
            )
        context.user_data["state"] = "main_menu"
        await q.edit_message_text(
            "✅ تم استلام الحساب وتأمينه.\n\n"
            "⏳ بدأ الحجز والفحص لمدة 48 ساعة. سيتم إشعارك بعد الفحص النهائي قبل تحويل المبلغ.",
            reply_markup=main_menu_kb(False),
        )
        await _notify_buyback_owner(context, offer_id)
        return True

    if data == "buyback:owner:list" and is_owner:
        text, markup = render_buyback_owner_list()
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return True

    if data.startswith("buyback:owner:paid:") and is_owner:
        try:
            offer_id = int(data.rsplit(":", 1)[-1])
        except ValueError:
            await q.answer("طلب غير صالح.", show_alert=True)
            return True
        seller_id = mark_buyback_paid(offer_id)
        if not seller_id:
            await q.answer("لا يمكن الدفع قبل نجاح فحص 48 ساعة.", show_alert=True)
            return True
        await q.edit_message_text(f"✅ تم تعليم الطلب #{offer_id} كمدفوع يدوياً.", reply_markup=owner_settings_kb())
        await _notify_buyback_user(context, seller_id, f"✅ تم اعتماد دفع مستحقات طلب بيع الحساب رقم #{offer_id}. تواصل مع المالك لاستلام المبلغ.")
        return True

    if data.startswith("buyback:owner:reject:") and is_owner:
        try:
            offer_id = int(data.rsplit(":", 1)[-1])
        except ValueError:
            await q.answer("طلب غير صالح.", show_alert=True)
            return True
        seller_id = reject_buyback_offer(offer_id, "رفض المالك الطلب")
        await q.edit_message_text(f"🚫 تم رفض طلب البيع #{offer_id}.", reply_markup=owner_settings_kb())
        if seller_id:
            await _notify_buyback_user(context, seller_id, f"🚫 تم رفض طلب بيع الحساب رقم #{offer_id}.")
        return True

    return False


def render_buyback_owner_list():
    with db_conn() as c:
        rows = c.execute(
            "SELECT id,seller_user_id,phone_number,quoted_price,status,created_at,next_check_at "
            "FROM account_buyback_offers WHERE status NOT IN ('paid','cancelled','rejected') "
            "ORDER BY id DESC LIMIT 30"
        ).fetchall()
    if not rows:
        return "📋 لا توجد طلبات بيع حسابات معلقة.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")]])
    lines = ["💰 <b>طلبات بيع الحسابات</b>", ""]
    rows_kb = []
    for row in rows:
        price = (
            f"{int(row['quoted_price']):,}" if row["quoted_price"] else "بعد فحص 48 ساعة"
        )
        lines.append(f"#{row['id']} — {_mask_buyback_phone(row['phone_number'])} — {row['status']} — {price}")
        if row["status"] == "ready_for_payment":
            rows_kb.append([InlineKeyboardButton(f"💵 دفع #{row['id']}", callback_data=f"buyback:owner:paid:{row['id']}"), InlineKeyboardButton(f"🚫 رفض #{row['id']}", callback_data=f"buyback:owner:reject:{row['id']}")])
        else:
            rows_kb.append([InlineKeyboardButton(f"🚫 رفض #{row['id']}", callback_data=f"buyback:owner:reject:{row['id']}")])
    rows_kb.append([InlineKeyboardButton("🔄 تحديث", callback_data="buyback:owner:list"), InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
    return "\n".join(lines), InlineKeyboardMarkup(rows_kb)


def mark_buyback_paid(offer_id: int) -> int | None:
    with db_conn() as c:
        row = c.execute(
            "SELECT * FROM account_buyback_offers WHERE id=%s AND status='ready_for_payment' FOR UPDATE",
            (offer_id,),
        ).fetchone()
        if not row:
            return None
        c.execute(
            "INSERT INTO number_stock (phone_number,session_string,assigned_to,deleted_at,ever_sold,sessions_reset,last_authorized,can_send_code,raksh_only) "
            "VALUES (%s,%s,NULL,NULL,FALSE,TRUE,TRUE,FALSE,FALSE) "
            "ON CONFLICT (phone_number) DO UPDATE SET session_string=EXCLUDED.session_string, assigned_to=NULL, deleted_at=NULL, ever_sold=FALSE, sessions_reset=TRUE, last_authorized=TRUE, raksh_only=FALSE",
            (row["phone_number"], row["session_string"]),
        )
        c.execute(
            "UPDATE account_buyback_offers SET status='paid', paid_at=NOW(), updated_at=NOW() WHERE id=%s",
            (offer_id,),
        )
    return int(row["seller_user_id"])


def reject_buyback_offer(offer_id: int, reason: str = "") -> int | None:
    with db_conn() as c:
        row = c.execute(
            "SELECT seller_user_id FROM account_buyback_offers WHERE id=%s AND status NOT IN ('paid','cancelled','rejected') FOR UPDATE",
            (offer_id,),
        ).fetchone()
        if not row:
            return None
        c.execute(
            "UPDATE account_buyback_offers SET status='rejected', session_string=NULL, rejection_reason=%s, updated_at=NOW() WHERE id=%s",
            (reason[:500], offer_id),
        )
    return int(row["seller_user_id"])


async def process_buyback_quarantine_job(context) -> None:
    """حلقة الحماية والفحص الدوري لطلبات بيع الحسابات.

    تُستدعى كل خمس دقائق. لذلك لا ننتظر موعد فحص 24/48 ساعة كي نكتشف
    دخولاً جديداً أو قيداً مستجداً في SpamBot.
    """
    with db_conn() as c:
        rows = c.execute(
            "SELECT id,seller_user_id,session_string,status,next_check_at "
            "FROM account_buyback_offers "
            "WHERE status IN ('quarantine_24h','quarantine_48h') "
            "ORDER BY COALESCE(last_checked_at,created_at), id LIMIT 50"
        ).fetchall()
    for row in rows:
        result = await _inspect_buyback_session(row["session_string"])
        state = result["state"]
        reason = result["reason"]
        now_due = row["next_check_at"] is not None and row["next_check_at"] <= datetime.now(timezone.utc)

        if state == "reject":
            seller_id = reject_buyback_offer(row["id"], reason)
            if seller_id:
                await _notify_buyback_user(
                    context,
                    seller_id,
                    f"🚫 لم ينجح فحص طلب بيع الحساب #{row['id']}، وتم إلغاء الطلب.",
                )
            if OWNER_ID:
                await context.bot.send_message(
                    OWNER_ID,
                    f"🚫 فشل فحص طلب بيع الحساب #{row['id']}: {html.escape(reason)}",
                    parse_mode=ParseMode.HTML,
                )
            continue

        if state == "retry":
            logger.info(
                "⏳ فحص طلب بيع الحساب #%s مؤجل: %s",
                row["id"],
                reason,
            )
            continue

        if result["extra_session_removed"]:
            security_note = (
                f"🔒 رصدت حلقة الحماية دخولاً إضافياً أثناء حجز الطلب #{row['id']} "
                "وطردته تلقائياً."
            )
            await _notify_buyback_user(context, row["seller_user_id"], security_note)
            if OWNER_ID:
                await context.bot.send_message(OWNER_ID, security_note)

        with db_conn() as c:
            c.execute(
                "UPDATE account_buyback_offers SET last_checked_at=NOW(), updated_at=NOW() "
                "WHERE id=%s AND status IN ('quarantine_24h','quarantine_48h')",
                (row["id"],),
            )

        if not now_due:
            continue

        if row["status"] == "quarantine_24h":
            with db_conn() as c:
                c.execute("UPDATE account_buyback_offers SET status='quarantine_48h', next_check_at=NOW()+INTERVAL '24 hours', last_checked_at=NOW(), updated_at=NOW() WHERE id=%s", (row["id"],))
            await _notify_buyback_user(context, row["seller_user_id"], f"✅ نجح فحص 24 ساعة لطلب البيع #{row['id']}. سيستمر الحجز حتى الفحص النهائي.")
        else:
            final_price = _buyback_price(restricted=bool(result.get("restricted")))
            with db_conn() as c:
                c.execute(
                    "UPDATE account_buyback_offers "
                    "SET status='ready_for_payment', quoted_price=%s, next_check_at=NULL, "
                    "last_checked_at=NOW(), updated_at=NOW() WHERE id=%s",
                    (final_price, row["id"]),
                )
            await _notify_buyback_user(
                context,
                row["seller_user_id"],
                f"✅ نجح الفحص النهائي لطلب البيع #{row['id']}. "
                f"السعر النهائي: {format_buyback_price(final_price)}. "
                "سيؤكد المالك دفع المبلغ الآن.",
            )
            await _notify_buyback_owner(context, row["id"], ready=True)
