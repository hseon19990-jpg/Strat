"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

def main():
    # ── إنشاء event loop جديد في كل تشغيل لتفادي RuntimeError: Event loop is closed ──
    import asyncio as _asyncio
    _loop = _asyncio.new_event_loop()
    _asyncio.set_event_loop(_loop)

    # ── التحقق من المتغيرات البيئية الضرورية عند الإطلاق ──────────────────
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not DATABASE_URL:
        missing.append("DATABASE_URL")
    if not OWNER_ID:
        missing.append("OWNER_ID")
    if missing:
        logger.critical(f"❌ متغيرات بيئية مفقودة: {', '.join(missing)}")
        logger.critical("❌ أضفها في إعدادات Railway ثم أعد التشغيل.")
        raise SystemExit(1)

    init_db()
    start_health_server()

    from telegram.request import HTTPXRequest
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .get_updates_request(HTTPXRequest(
            connection_pool_size=1,
            read_timeout=60,
            connect_timeout=30,
            write_timeout=30,
        ))
        .build()
    )

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("admin",     cmd_admin))
    app.add_handler(CommandHandler("addpoints", cmd_addpoints))
    app.add_handler(CommandHandler("grant_ref", cmd_grant_ref))
    app.add_handler(CommandHandler("broadcast",           cmd_broadcast))
    app.add_handler(CommandHandler("status",              cmd_status_order))
    app.add_handler(CommandHandler("compensate_partial",  cmd_compensate_partial))
    app.add_handler(CommandHandler("refund_mandatory",    cmd_refund_mandatory))
    app.add_handler(CommandHandler("cancel",              cmd_cancel))
    app.add_handler(CommandHandler("import_session",      cmd_import_session))
    app.add_handler(CommandHandler("import_sessions",     cmd_import_sessions))
    app.add_handler(CommandHandler("import_hex",          cmd_import_hex))
    app.add_handler(CommandHandler("mass_reset",          cmd_mass_reset))
    app.add_handler(CommandHandler("rotate_sessions",     cmd_rotate_sessions))
    
    # ════════════════════════════════════════════════════════════════
    # 🔥 أمر اختبار AI (للمالك فقط)
    # ════════════════════════════════════════════════════════════════
    app.add_handler(CommandHandler("testai", cmd_test_ai))
    # ════════════════════════════════════════════════════════════════
    
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (
            filters.PHOTO
            | filters.VIDEO
            | filters.Document.MimeType("video/mp4")
            | filters.Document.MimeType("video/quicktime")
            | filters.Document.MimeType("video/x-m4v")
            | filters.Document.FileExtension("mp4")
            | filters.Document.FileExtension("mov")
            | filters.Document.FileExtension("m4v")
        ),
        handle_avatar_photo
    ))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.CAPTION) & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_text
    ))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.Document.MimeType("application/json"),
        handle_json_file
    ))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.Document.FileExtension("session"),
        handle_session_file
    ))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.Document.FileExtension("zip"),
        handle_zip_file
    ))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.CONTACT,
        handle_contact_share
    ))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.SUCCESSFUL_PAYMENT,
        handle_unsupported_message
    ))
    app.add_handler(ChatMemberHandler(handle_member_leave, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(handle_bot_removed_from_channel, ChatMemberHandler.MY_CHAT_MEMBER))
    if ADMIN_GROUP_ID:
        app.add_handler(MessageHandler(
            filters.Chat(ADMIN_GROUP_ID) &
            (filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER),
            delete_group_service_messages
        ))

    async def post_init(application):
        # ─── معالج عالمي للاستثناءات غير المعالجة في asyncio tasks ────────
        def _handle_asyncio_exception(loop, context):
            exc = context.get("exception")
            msg = context.get("message", "")
            if exc is None:
                logger.warning(f"⚠️ asyncio unhandled: {msg}")
            elif isinstance(exc, asyncio.CancelledError):
                pass  # طبيعي عند إغلاق البوت
            else:
                logger.error(f"❌ asyncio task exception: {exc!r} | {msg}")
        try:
            asyncio.get_event_loop().set_exception_handler(_handle_asyncio_exception)
        except Exception:
            pass

        # ─── حذف أي webhook مسجّل مسبقاً حتى يعمل long polling بشكل صحيح ───
        try:
            await application.bot.delete_webhook(drop_pending_updates=True)
            logger.info("✅ Webhook deleted — polling mode active")
        except Exception as _wh_err:
            logger.warning(f"⚠️ تعذّر حذف webhook: {_wh_err}")

        await application.bot.set_my_commands([
            BotCommand("start", "🏠 القائمة الرئيسية"),
        ])
        if OWNER_ID:
            try:
                await application.bot.set_my_commands(
                    [
                        BotCommand("start",     "🏠 القائمة الرئيسية"),
                        BotCommand("admin",     "⚙️ لوحة المالك"),
                        BotCommand("addpoints", "💰 إضافة/خصم نقاط لمستخدم"),
                        BotCommand("broadcast",          "📢 إرسال رسالة جماعية"),
                        BotCommand("status",             "🔍 فحص حالة طلب"),
                        BotCommand("compensate_partial", "💰 تعويض أصحاب الطلبات الجزئية"),
                        BotCommand("refund_mandatory", "🔁 استرجاع تمويلات الاشتراك الإجباري"),
                        BotCommand("testai",             "🧪 اختبار مفاتيح AI"),
                    ],
                    scope=BotCommandScopeChat(chat_id=OWNER_ID)
                )
            except Exception as e:
                logger.warning(f"⚠️ تعذّر تعيين أوامر المالك الخاصة (ربما لم يبدأ المالك محادثة مع البوت بعد): {e}")
        
        # ════════════════════════════════════════════════════════════════
        # 🔥 سجل حالة مفاتيح AI عند بدء التشغيل
        # ════════════════════════════════════════════════════════════════
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        logger.info(f"🔑 GEMINI_API_KEY موجود: {bool(gemini_key)} | طوله: {len(gemini_key)}")
        logger.info(f"🔑 OPENAI_API_KEY موجود: {bool(openai_key)} | طوله: {len(openai_key)}")
        if not gemini_key and not openai_key:
            logger.warning("⚠️ لا يوجد مفتاح Gemini أو OpenAI — خدمات التحقق التلقائي لن تعمل.")
        # ════════════════════════════════════════════════════════════════
        
        logger.info("✅ Bot commands set")
        # حفظ اسم المستخدم الخاص بهذا البوت لاستخدامه في تخطي الإحالة الذاتية
        global _OWN_BOT_USERNAME
        try:
            _me = await application.bot.get_me()
            _OWN_BOT_USERNAME = (_me.username or "").lower().strip()
            logger.info(f"✅ _OWN_BOT_USERNAME = @{_OWN_BOT_USERNAME}")
        except Exception as _e:
            logger.warning(f"⚠️ تعذّر جلب username البوت: {_e}")
        # ─── تعويض المبيعات المكررة عند الإقلاع ────
        async def _bg_startup():
            try:
                await compensate_duplicate_sales_job(
                    type("_ctx", (), {"bot": application.bot})()
                )
            except Exception as e:
                logger.warning(f"⚠️ compensate_duplicate_sales (startup): {e}")
        asyncio.create_task(_bg_startup())
        try:
            with db_conn() as _mc:
                _mc.execute(
                    "UPDATE number_stock SET deleted_at=NOW() "
                    "WHERE session_string IS NULL AND deleted_at IS NULL"
                )
                _deleted_manual = _mc.rowcount
            if _deleted_manual:
                logger.warning(f"🗑 حُذفت {_deleted_manual} أرقام يدوية (بلا جلسة) عند الإقلاع.")
        except Exception as e:
            logger.warning(f"⚠️ تنظيف الأرقام اليدوية (startup): {e}")
        # ─── حذف الأرقام المجمّدة المكتشفة مسبقاً (frozen_at IS NOT NULL) ────
        try:
            with db_conn() as _fzc:
                _fzc.execute(
                    "DELETE FROM number_stock "
                    "WHERE frozen_at IS NOT NULL AND ever_sold IS NOT TRUE AND assigned_to IS NULL"
                )
                _frz_deleted = _fzc.rowcount
            if _frz_deleted:
                logger.warning(f"🧊 حُذفت {_frz_deleted} أرقام مجمّدة تلقائياً عند الإقلاع.")
        except Exception as e:
            logger.warning(f"⚠️ تنظيف الأرقام المجمّدة (startup): {e}")

        # ─── التحقق من وجود GEMINI_API_KEY و OPENAI_API_KEY ───
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if not gemini_key and not openai_key:
            logger.warning("⚠️ لا يوجد مفتاح Gemini أو OpenAI — خدمات التحقق التلقائي لن تعمل.")
        elif gemini_key:
            logger.info("✅ GEMINI_API_KEY موجودة")
        elif openai_key:
            logger.info("✅ OPENAI_API_KEY موجودة (بدون Gemini)")

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        err = context.error
        if isinstance(err, RetryAfter):
            logger.warning(f"⚠️ RetryAfter: {err.retry_after}s")
            return
        if isinstance(err, (NetworkError, TimedOut)):
            logger.warning(f"⚠️ خطأ شبكي مؤقت: {err}")
            return
        if isinstance(err, Conflict):
            # نسختان تعملان في نفس الوقت — طبيعي عند redeploy، سيختفي خلال ثوانٍ
            logger.warning("⚠️ Conflict: نسخة أخرى من البوت تعمل — جاري الانتظار حتى تنتهي...")
            return
        # أخطاء Forbidden/BadRequest من handlers — لا تُوقف البوت
        from telegram.error import Forbidden, BadRequest
        if isinstance(err, (Forbidden, BadRequest)):
            logger.warning(f"⚠️ Telegram API error (ignored): {err}")
            return
        logger.error(f"❌ خطأ غير متوقع:\n{traceback.format_exc()}")

    app.add_error_handler(error_handler)
    app.post_init = post_init

    if app.job_queue:
        app.job_queue.run_repeating(check_pending_orders_job, interval=300, first=30)
        logger.info("⏱️ تم تفعيل الفحص الدوري لحالة الطلبات (كل 5 دقائق)")
        app.job_queue.run_repeating(retry_pending_session_resets, interval=600, first=90)
        logger.info("🔒 تم تفعيل إعادة المحاولة الدورية لطرد جلسات الأرقام (كل 10 دقائق)")
        app.job_queue.run_repeating(run_referral_tasks_job, interval=3600, first=120)
        logger.info("🤝 تم تفعيل مهام الإحالة التلقائية (كل ساعة)")
        app.job_queue.run_repeating(compensate_duplicate_sales_job, interval=21600, first=300)
        logger.info("🔁 تم تفعيل فحص البيع المكرر وتعويض المتضررين (كل 6 ساعات)")
        app.job_queue.run_repeating(check_twofa_reset_job, interval=3600, first=60)
        logger.info("🔐 تم تفعيل فحص إكمال إعادة تعيين 2FA (كل ساعة)")
        app.job_queue.run_repeating(_account_fixup_job, interval=30, first=15)
        logger.info("🔧 تم تفعيل حلقة الإصلاح التلقائي للحسابات (كل 30 ثانية)")

    logger.info("🤖 Bot started!")
    app.run_polling(
        drop_pending_updates=True,
        read_timeout=45,
        write_timeout=45,
        connect_timeout=45,
        pool_timeout=45,
        allowed_updates=["message", "callback_query", "pre_checkout_query", "successful_payment", "chat_member", "my_chat_member"],
    )

# ════════════════════════════════════════════════════════════════
# 🔥 أمر اختبار AI (للمالك فقط)
# ════════════════════════════════════════════════════════════════
async def cmd_test_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    
    msg = f"🔑 GEMINI_API_KEY: {'✅ موجود' if GEMINI_API_KEY else '❌ مفقود'}\n"
    msg += f"🔑 OPENAI_API_KEY: {'✅ موجود' if OPENAI_API_KEY else '❌ مفقود'}\n\n"
    
    if GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
            r = requests.post(url, json={"contents": [{"parts": [{"text": "قل مرحباً"}]}]}, timeout=10)
            if r.status_code == 200:
                msg += f"✅ Gemini يعمل بشكل صحيح! (200 OK)\n"
            else:
                msg += f"❌ Gemini error: {r.status_code} - {r.text[:200]}\n"
        except Exception as e:
            msg += f"❌ Gemini exception: {e}\n"
    else:
        msg += "❌ Gemini غير مضبوط في البيئة\n"
    
    if OPENAI_API_KEY:
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "قل مرحباً"}], "max_tokens": 5},
                timeout=10
            )
            if r.status_code == 200:
                msg += f"✅ OpenAI يعمل بشكل صحيح! (200 OK)\n"
            else:
                msg += f"❌ OpenAI error: {r.status_code} - {r.text[:200]}\n"
        except Exception as e:
            msg += f"❌ OpenAI exception: {e}\n"
    else:
        msg += "❌ OpenAI غير مضبوط في البيئة\n"
    
    msg += "\n📌 الآن جرّب طلب 'إحالة بتحقق' وانظر الـ Logs."
    
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
