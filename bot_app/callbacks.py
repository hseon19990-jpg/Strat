"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

# Ensure fmt_price is available (defined in services.py). Importing directly
# avoids a NameError when formatting prices in _save_service.
from .services import fmt_price
from .number_admin import (
    is_number_admin,
    number_admin_can_manage,
    render_number_admin_account,
    render_number_admin_panel,
)

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

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
from .callback_groups_01 import _handle_callback_group_01
from .callback_groups_02 import _handle_callback_group_02
from .callback_groups_03 import _handle_callback_group_03
from .callback_groups_04 import _handle_callback_group_04

_CALLBACK_NOT_HANDLED = object()

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query
    data   = q.data
    user   = q.from_user
    is_own        = (user.id == OWNER_ID)
    is_supervisor_cb = (not is_own) and is_supervisor(user.id)
    is_number_admin_user = (not is_own) and is_number_admin(user.id)
    number_admin_action = False

    # Number-admin callbacks are translated to the existing owner account
    # callbacks only after checking the requested stock row belongs to the
    # caller. This preserves the mature account-management implementation
    # without exposing owner-wide settings.
    if is_number_admin_user:
        if (
            data in {
                "na:panel",
                "na:list",
                "na:search",
                "os:manage_numbers",
                "os:list_numbers",
                "owner_settings",
            }
            or data.startswith("na:panel:")
        ):
            try:
                await q.answer()
            except Exception:
                pass
            page = 0
            if data.startswith("na:panel:"):
                try:
                    page = max(0, int(data.rsplit(":", 1)[-1]))
                except ValueError:
                    page = 0
            if data == "na:search":
                context.user_data["state"] = "na_await_search"
                await q.edit_message_text(
                    "🔍 *البحث عن رقم*\n\n"
                    "أرسل الرقم كاملاً أو جزءاً منه، ويمكنك كتابة + أو مسافات.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            "🔙 رجوع إلى أرقامك",
                            callback_data="na:panel",
                        )
                    ]]),
                )
                return
            context.user_data["state"] = "main_menu"
            await render_number_admin_panel(update, context, page=page)
            return
        if data.startswith("na:number:"):
            try:
                stock_id = int(data.rsplit(":", 1)[-1])
            except ValueError:
                await q.answer("⚠️ الرقم غير صحيح.", show_alert=True)
                return
            if not number_admin_can_manage(user.id, stock_id=stock_id):
                await q.answer("🚫 هذا الرقم غير مخصص لك.", show_alert=True)
                return
            await render_number_admin_account(update, context, stock_id)
            return
        elif data.startswith("na:"):
            await q.answer("🚫 هذا الإجراء غير متاح.", show_alert=True)
            return
        elif data.startswith("os:number_info:"):
            try:
                stock_id = int(data.rsplit(":", 1)[-1])
            except ValueError:
                await q.answer("⚠️ الرقم غير صحيح.", show_alert=True)
                return
            if not number_admin_can_manage(user.id, stock_id=stock_id):
                await q.answer("🚫 هذا الرقم غير مخصص لك.", show_alert=True)
                return
            await render_number_admin_account(update, context, stock_id)
            return
        elif data.startswith("os:number_"):
            try:
                stock_id = int(data.rsplit(":", 1)[-1])
            except ValueError:
                await q.answer("⚠️ الرقم غير صحيح.", show_alert=True)
                return
            if not number_admin_can_manage(user.id, stock_id=stock_id):
                await q.answer("🚫 هذا الرقم غير مخصص لك.", show_alert=True)
                return
            number_admin_action = True
        elif data.startswith("os:force_list:"):
            try:
                stock_id = int(data.rsplit(":", 1)[-1])
            except ValueError:
                await q.answer("⚠️ الرقم غير صحيح.", show_alert=True)
                return
            if not number_admin_can_manage(user.id, stock_id=stock_id):
                await q.answer("🚫 هذا الرقم غير مخصص لك.", show_alert=True)
                return
            number_admin_action = True
        elif data.startswith("os:kick_device:"):
            try:
                stock_id = int(data.split(":")[2])
            except (IndexError, ValueError):
                await q.answer("⚠️ الرقم غير صحيح.", show_alert=True)
                return
            if not number_admin_can_manage(user.id, stock_id=stock_id):
                await q.answer("🚫 هذا الرقم غير مخصص لك.", show_alert=True)
                return
            number_admin_action = True
        elif data.startswith("os:allow_5min:"):
            phone = data[len("os:allow_5min:"):]
            if not number_admin_can_manage(user.id, phone_number=phone):
                await q.answer("🚫 هذا الرقم غير مخصص لك.", show_alert=True)
                return
            number_admin_action = True
        elif data.startswith("os:account_info:"):
            phone = data[len("os:account_info:"):]
            if not number_admin_can_manage(user.id, phone_number=phone):
                await q.answer("🚫 هذا الرقم غير مخصص لك.", show_alert=True)
                return
            number_admin_action = True

    effective_is_own = is_own or number_admin_action

    # Acknowledge immediately so Telegram never leaves the button spinning
    # while database checks or message rendering are in progress.
    try:
        await q.answer()
    except Exception:
        pass

    # Log the incoming callback for debugging.
    try:
        logger.info(f"🔥🔥🔥 CALLBACK RECEIVED: {data}")
    except Exception:
        pass

    # ── الخدمات الأسطورية تُمرر مباشرة للمجموعة 1 ──
    # تم إزالة المعالج المكرر هنا لتجنب التعارض
    # المعالج موجود الآن في callback_groups_01.py

    if not effective_is_own and is_user_banned(user.id):
        await q.answer("🚫 تم حظرك من استخدام هذا البوت.", show_alert=True)
        return

    if is_maintenance_on() and not effective_is_own:
        await q.answer()
        await q.edit_message_text(MAINTENANCE_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return

    _GATE_EXEMPT = {"check_mandatory_join", "noop", "skip_mandatory_gate"}
    _owner_admin_action = effective_is_own and data.startswith("os:")
    _sv_admin_action    = is_supervisor_cb and data.startswith("sv:")
    _gmail_verification_done = (
        data == "gmail_verify_done" or data.startswith("gmail_verify_done:")
    )
    if not effective_is_own and data not in _GATE_EXEMPT and not _gmail_verification_done and not data.startswith("join_verify:") and not data.startswith("thank_owner") and not _owner_admin_action and not _sv_admin_action:
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
                        reply_markup=mandatory_join_kb(_unjoined, is_owner=effective_is_own)
                    )
                    context.user_data["state"] = "await_mandatory_join"
                    return
        except Exception as _gate_err:
            logger.warning(f"⚠️ خطأ في فحص القنوات الإجبارية (callback) للمستخدم {user.id}: {_gate_err}")

    if data.startswith("buyback:"):
        if await handle_buyback_callback(update, context, q, data, user, is_own):
            return

    # ── العضو يُبلغ المالك بعد إكمال تحقق حساب الجيميل ──
    for _callback_group in (
        _handle_callback_group_01,
        _handle_callback_group_02,
        _handle_callback_group_03,
        _handle_callback_group_04,
    ):
        _handled = await _callback_group(
            update, context, q, data, user, effective_is_own, is_supervisor_cb,
            _gmail_verification_done,
        )
        if _handled is not True:
            return

    # ─── معالج استيراد الخدمات ───
    if data.startswith("import_services:"):
        await handle_import_services_callback(update, context, q, data, user, effective_is_own)
        return

    try:
        await q.answer()
    except Exception:
        pass