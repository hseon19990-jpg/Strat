"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

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

    # ── معالجة الخدمات الأسطورية أولاً ────────────────────────────
    # ── الخدمات الأسطورية ──────────────────────────────────────────
    if data.startswith("legendary:"):
        from .legendary_comment import (
            legendary_service_start, legendary_skip_channel, legendary_payment_choice,
            legendary_confirm, legendary_show_settings, legendary_edit_service,
            legendary_toggle_service, legendary_edit_price_points, legendary_edit_price_stars,
            legendary_edit_welcome, legendary_set_delay
        )

        # ─── إعدادات المالك ───
        if data == "legendary:settings" and is_own:
            await legendary_show_settings(update, context, q, is_own)
            return

        if data.startswith("legendary:edit_service:") and is_own:
            service_type = data.split(":")[2]
            await legendary_edit_service(update, context, q, is_own, service_type)
            return

        if data.startswith("legendary:toggle_service:") and is_own:
            service_type = data.split(":")[2]
            await legendary_toggle_service(update, context, q, is_own, service_type)
            return

        if data.startswith("legendary:edit_price_points:") and is_own:
            service_type = data.split(":")[2]
            await legendary_edit_price_points(update, context, q, is_own, service_type)
            return

        if data.startswith("legendary:edit_price_stars:") and is_own:
            service_type = data.split(":")[2]
            await legendary_edit_price_stars(update, context, q, is_own, service_type)
            return

        if data == "legendary:edit_welcome" and is_own:
            await legendary_edit_welcome(update, context, q, is_own)
            return

        if data == "legendary:set_delay" and is_own:
            await legendary_set_delay(update, context, q, is_own)
            return

        # ─── دفع ───
        if data.startswith("legendary:pay_stars:"):
            service_type = data.split(":")[2]
            await legendary_payment_choice(update, context, q, is_own, service_type, "stars")
            return

        if data.startswith("legendary:pay_points:"):
            service_type = data.split(":")[2]
            await legendary_payment_choice(update, context, q, is_own, service_type, "points")
            return

        # ─── تخطي القناة ───
        if data.startswith("legendary:skip_channel:"):
            service_type = data.split(":")[2]
            await legendary_skip_channel(update, context, q, service_type)
            return

        # ─── تأكيد ───
        if data == "legendary:confirm":
            await legendary_confirm(update, context, q, is_own)
            return

        # ─── بدء الخدمة من القائمة ───
        if data.startswith("legendary:start:"):
            service_type = data.split(":")[2]
            await legendary_service_start(update, context, q, is_own, service_type)
            return

        await q.answer("⚠️ خيار غير معروف.", show_alert=True)
        return

    # ────────────────────────────────────────────────────────────────
    # ── باقي المعالجات (من الكود الأصلي) ──────────────────────────
    # ────────────────────────────────────────────────────────────────

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

    # ── العضو يُبلغ المالك بعد إكمال تحقق حساب الجيميل ──
    for _callback_group in (
        _handle_callback_group_01,
        _handle_callback_group_02,
        _handle_callback_group_03,
        _handle_callback_group_04,
    ):
        _handled = await _callback_group(
            update, context, q, data, user, is_own, is_supervisor_cb,
            _gmail_verification_done,
        )
        if _handled is not True:
            return

    try:
        await q.answer()
    except Exception:
        pass
