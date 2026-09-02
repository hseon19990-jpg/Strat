# داخل raksh_system.py

async def _start_raksh_execution(
    update,
    context,
    query,
    service_type: str,
    quantity: int,
    payment_method: str,
    total_cost: int,
    progress_message=None,
):
    """بدء تنفيذ الرشق فوراً"""
    user = update.effective_user if update else query.from_user
    
    if progress_message is None:
        progress_msg = await query.edit_message_text(
            "✅ *بدأ التنفيذ الآن...*\n\n"
            f"📊 0/{quantity}",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        progress_msg = progress_message
        await progress_msg.edit_text(
            "✅ *بدأ التنفيذ الآن...*\n\n"
            f"📊 0/{quantity}",
            parse_mode=ParseMode.MARKDOWN,
        )
    
    svc = get_raksh_service(service_type)
    
    # 🔥 1. جلب الحسابات فوراً (بدون أي انتظار)
    sessions = svc.get_sessions() if svc else []
    if not sessions:
        await progress_msg.edit_text(
            "❌ لا توجد حسابات متاحة.",
            reply_markup=raksh_menu_kb(user.id == OWNER_ID)
        )
        if payment_method == "points":
            add_points(user.id, total_cost)
        _clear_raksh_state(context)
        return
    
    await _send_raksh_order_to_group(
        context.bot,
        user.id,
        quantity,
        payment_method,
        service_type,
    )
    
    params = svc.get_execution_params(context) if svc else {}
    
    # 🔥 2. دالة التقدم المحدثة (تظهر ✅ مع كل حساب ينجح)
    async def update_progress(current, total, success, failed):
        try:
            await progress_msg.edit_text(
                f"⏳ *جاري التنفيذ...*\n\n"
                f"📊 {current}/{total}\n"
                f"✅ نجح: {success}\n"
                f"❌ فشل: {failed}",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
    
    # 🔥 3. التشغيل الفوري (لا يوجد sleep قبل أول عملية)
    success_count, success_phones, success_details, failed_phones, failed_details = await execute_raksh_service(
        service_type=service_type,
        quantity=quantity,
        sessions=sessions,
        params=params,
        user_id=user.id,
        progress_callback=update_progress
    )
    
    await _send_raksh_owner_result(
        context.bot,
        service_type,
        quantity,
        success_phones,
        failed_phones,
        failed_details,
    )
    
    # حساب التعويض
    refund = 0
    special_count = 0
    if payment_method == "points":
        failed_refund = max(0, total_cost - get_raksh_total(service_type, success_count, "points"))
        special_count = sum(1 for msg in success_details if "بدون زر تحقق" in msg or RAKSH_NO_VERIFICATION_MESSAGE in msg)
        if special_count > 0:
            special_refund = int(get_raksh_total(service_type, special_count, "points") / 2)
            refund = failed_refund + special_refund
            if refund > 0:
                add_points(user.id, refund)
    
    # عرض النتيجة النهائية
    failed_count = quantity - success_count
    result_text = f"✅ *اكتمل الطلب!*\n\n"
    result_text += f"الخدمة: {svc.config.name if svc else service_type}\n"
    result_text += f"المطلوب: {quantity}\n"
    result_text += f"✅ المنجز: {success_count}\n"
    result_text += f"❌ الفاشل: {failed_count}\n"
    if refund > 0:
        result_text += f"💰 تم تعويضك: {refund} نقطة\n"
    if special_count > 0:
        result_text += f"🔁 استرداد نصف المبلغ لـ {special_count} حساب (بدون زر تحقق)\n"
    
    if success_phones:
        result_text += f"\n✅ *الحسابات الناجحة ({len(success_phones)}):*\n"
        result_text += "\n".join(f"• `{p}`" for p in success_phones[:10])
        if len(success_phones) > 10:
            result_text += f"\n... و{len(success_phones)-10} أخرى"
    
    if failed_details:
        result_text += f"\n\n❌ *الفاشلة ({len(failed_details)}):*\n"
        result_text += "\n".join(f"• {d[:80]}" for d in failed_details[:5])
        if len(failed_details) > 5:
            result_text += f"\n... و{len(failed_details)-5} أخرى"
    
    await progress_msg.edit_text(
        result_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb()
    )
    
    _clear_raksh_state(context)
