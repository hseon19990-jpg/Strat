"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""
from .security import run_referral_tasks_job
from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})
from telegram.ext import ExtBot, Updater

class ResilientExtBot(ExtBot):
    """Let polling handle Telegram bootstrap retries instead of blocking on getMe()."""

    @property
    def id(self) -> int:
        # Application.start() uses bot.id only for asyncio task names. Keep
        # startup non-blocking until the background getMe() call succeeds.
        return self._bot_user.id if self._bot_user is not None else 0

    @property
    def username(self) -> str:
        # Some legacy handlers read bot.username while polling is starting.
        # ExtBot normally raises until getMe() has populated _bot_user; return
        # an empty value instead so a temporary Telegram/API delay cannot
        # crash the update handler.
        return self._bot_user.username if self._bot_user is not None else ""

    async def initialize(self) -> None:
        if self._initialized:
            return
        if self.rate_limiter:
            await self.rate_limiter.initialize()
        await asyncio.gather(self._request[0].initialize(), self._request[1].initialize())
        self._initialized = True

class ResilientUpdater(Updater):
    """Start polling without blocking on a temporary Telegram outage."""

    async def _bootstrap(self, *args, **kwargs) -> None:
        # Clear the webhook once before polling when Telegram responds quickly.
        # A slow API must not hold the whole application; the background retry
        # task in post_init continues cleanup after polling has started.
        try:
            await asyncio.wait_for(
                self.bot.delete_webhook(
                    drop_pending_updates=True,
                    read_timeout=8,
                    write_timeout=8,
                    connect_timeout=8,
                    pool_timeout=8,
                ),
                timeout=10,
            )
            logger.info("✅ Webhook cleanup completed before polling")
        except asyncio.TimeoutError:
            logger.warning("⚠️ Webhook cleanup timed out; polling starts and background retry continues")
        except (TimedOut, NetworkError) as e:
            logger.warning(f"⚠️ Webhook cleanup delayed: {e}; polling starts and background retry continues")
        except Exception as e:
            logger.warning(f"⚠️ Webhook cleanup failed: {e}; polling starts and background retry continues")

async def sync_raksh_bot_commands(bot) -> None:
    """يحدّث اسم أمر الرشق في قائمة تيليجرام فور تغيير الاسم."""
    label = get_raksh_accounts_label()
    await bot.set_my_commands([
        BotCommand("start", "🏠 القائمة الرئيسية"),
        BotCommand("raksh", f"🔥 {label}"),
    ])
    if OWNER_ID:
        await bot.set_my_commands(
            [
                BotCommand("start", "🏠 القائمة الرئيسية"),
                BotCommand("admin", "⚙️ لوحة المالك"),
                BotCommand("addpoints", "💰 إضافة/خصم نقاط لمستخدم"),
                BotCommand("broadcast", "📢 إرسال رسالة جماعية"),
                BotCommand("status", "🔍 فحص حالة طلب"),
                BotCommand("compensate_partial", "💰 تعويض أصحاب الطلبات الجزئية"),
                BotCommand("refund_mandatory", "🔁 استرجاع تمويلات الاشتراك الإجباري"),
                BotCommand("testai", "🧪 اختبار مفاتيح AI"),
                BotCommand("raksh", f"🔥 {label}"),
            ],
            scope=BotCommandScopeChat(chat_id=OWNER_ID),
        )

# ─── استيراد نظام الرشق الجديد من داخل حزمة bot_app ────────────────────────
from .raksh_system import (
    cmd_raksh,
    handle_raksh_callback,
    raksh_pre_checkout,
    raksh_successful_payment,
)

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

    start_health_server()
    init_db()

    from telegram.request import HTTPXRequest

    # Railway can occasionally take longer to establish or return a Telegram
    # API connection. Configure both request clients: get_me() and normal bot
    # calls use the default client, while long polling uses the updates client.
    telegram_request = HTTPXRequest(
        connection_pool_size=8,
        read_timeout=120,
        connect_timeout=60,
        write_timeout=60,
        pool_timeout=60,
    )
    updates_request = HTTPXRequest(
        connection_pool_size=2,
        read_timeout=120,
        connect_timeout=60,
        write_timeout=60,
        pool_timeout=60,
    )

    telegram_bot = ResilientExtBot(
        token=BOT_TOKEN,
        request=telegram_request,
        get_updates_request=updates_request,
    )
    polling_updater = ResilientUpdater(telegram_bot, asyncio.Queue())
    app = (
        ApplicationBuilder()
        .updater(polling_updater)
        .concurrent_updates(True)
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
    
    # ════════════════════════════════════════════════════════════════
    # 🔥 نظام الرشق الجديد (RAKSH SYSTEM)
    # ════════════════════════════════════════════════════════════════
    app.add_handler(CommandHandler("raksh", cmd_raksh))
    # لا تلتقط أزرار البوت العامة؛ هذا المعالج مخصص لـ Raksh فقط.
    # بدون pattern كان يطابق كل CallbackQuery ويمنع handle_callback من العمل.
    app.add_handler(
        CallbackQueryHandler(
            handle_raksh_callback,
            # Match the menu callback as well as every Raksh step explicitly.
            # The old catch-all handler below must never consume these queries.
            pattern=r"^(?:raksh_menu|raksh_cancel|raksh(?:_|:))",
        )
    )
    app.add_handler(PreCheckoutQueryHandler(raksh_pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, raksh_successful_payment))
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

    # ════════════════════════════════════════════════════════════════
    # 🔥 أمر الطلبات المتأخرة (للمالك فقط) - مدمج هنا لضمان العمل
    # ════════════════════════════════════════════════════════════════
    async def cmd_delayed_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user.id != OWNER_ID:
            await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
            return
        
        await update.message.reply_text("⏳ *جاري فحص الطلبات المتأخرة...*", parse_mode=ParseMode.MARKDOWN)
        
        threshold = datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=6)
        
        with db_conn() as c:
            rows = c.execute("""
                SELECT o.order_code, o.user_id, o.created_at, 
                       s.name_ar AS service_name, s.panel AS panel
                FROM orders o
                LEFT JOIN services s ON s.id = o.service_id
                WHERE o.status = 'pending'
                  AND o.created_at::timestamptz < %s
                  AND o.api_order_id IS NOT NULL
                  AND o.api_order_id != ''
                ORDER BY o.created_at ASC
            """, (threshold,)).fetchall()
        
        orders = [dict(row) for row in rows]
        
        if not orders:
            await update.message.reply_text("📊 *الطلبات المتأخرة*\n\n✅ لا توجد طلبات مضى عليها أكثر من 6 ساعات.")
            return
        
        from collections import defaultdict
        orders_by_panel = defaultdict(list)
        for order in orders:
            orders_by_panel[order['panel'] or 1].append(order)
        
        for panel, order_list in orders_by_panel.items():
            panel_names = {1: "SMMMAIN", 2: "JustAnotherPanel", 3: "SmmFollows"}
            panel_name = panel_names.get(panel, "موقع غير معروف")
            
            lines = [f"📊 *الطلبات المتأخرة - {panel_name}*", f"📦 عدد الطلبات: {len(order_list)}", ""]
            for o in order_list:
                created = o['created_at']
                date_str = created.strftime("%Y-%m-%d %H:%M") if hasattr(created, 'strftime') else str(created)[:16]
                delay = round((datetime.datetime.now(timezone.utc) - created).total_seconds() / 3600, 1)
                lines.append(f"  └ 📌 `{o['order_code']}` — {date_str} (تأخير {delay} ساعة)")
            
            await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    
    app.add_handler(CommandHandler("delayed_orders", cmd_delayed_orders))
    # ════════════════════════════════════════════════════════════════

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

        async def _configure_telegram():
            """Configure optional Telegram metadata without blocking polling startup."""
            try:
                await application.bot.set_my_commands([
                    BotCommand("start", "🏠 القائمة الرئيسية"),
                    BotCommand("raksh", f"🔥 {get_raksh_accounts_label()}"),
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
                                BotCommand("raksh",              f"🔥 {get_raksh_accounts_label()}"),
                            ],
                            scope=BotCommandScopeChat(chat_id=OWNER_ID)
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ تعذّر تعيين أوامر المالك الخاصة (ربما لم يبدأ المالك محادثة مع البوت بعد): {e}")

                global _OWN_BOT_USERNAME
                _me = await application.bot.get_me()
                _OWN_BOT_USERNAME = (_me.username or "").lower().strip()
                logger.info(f"✅ Telegram API connected — bot username: @{_OWN_BOT_USERNAME}")
            except (TimedOut, NetworkError) as e:
                logger.warning(f"⚠️ تعذّر مزامنة إعدادات Telegram مؤقتاً؛ polling مستمر: {e}")
            except Exception as e:
                logger.warning(f"⚠️ تعذّر مزامنة إعدادات Telegram: {e}")

        async def _clear_webhook():
            retry_delay = 5
            for attempt in range(1, 7):
                try:
                    await application.bot.delete_webhook(
                        drop_pending_updates=True,
                        read_timeout=10,
                        write_timeout=10,
                        connect_timeout=10,
                        pool_timeout=10,
                    )
                    logger.info("✅ Webhook cleanup completed")
                    return
                except (TimedOut, NetworkError) as e:
                    logger.warning(
                        f"⚠️ Webhook cleanup attempt {attempt}/6 مؤجل بسبب Telegram: {e}"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Webhook cleanup attempt {attempt}/6 failed: {e}")
                if attempt < 6:
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 60)
            logger.error(
                "❌ Webhook cleanup لم يكتمل بعد 6 محاولات؛ polling مستمر وسيُعاد تنظيفه عند إعادة التشغيل."
            )

        asyncio.create_task(_configure_telegram(), name="telegram-metadata-sync")
        asyncio.create_task(_clear_webhook(), name="telegram-webhook-cleanup")
        logger.info("✅ Telegram metadata synchronization scheduled in background")
        
        # ════════════════════════════════════════════════════════════════
        # 🔥 سجل حالة مفاتيح AI عند بدء التشغيل
        # ════════════════════════════════════════════════════════════════
        groq_key = os.environ.get("GROQ_API_KEY", "")
        deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
        logger.info(f"🔑 GROQ_API_KEY موجود: {bool(groq_key)} | طوله: {len(groq_key)}")
        logger.info(f"🔑 DEEPSEEK_API_KEY موجود: {bool(deepseek_key)} | طوله: {len(deepseek_key)}")
        if not groq_key and not deepseek_key:
            logger.warning("⚠️ لا يوجد مفتاح Groq أو DeepSeek — خدمات التحقق التلقائي لن تعمل.")
        # ════════════════════════════════════════════════════════════════
        
        logger.info("ℹ️ Telegram command synchronization scheduled in background")
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

        # ─── التحقق من وجود GROQ_API_KEY و DEEPSEEK_API_KEY ───
        groq_key = os.environ.get("GROQ_API_KEY", "")
        deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not groq_key and not deepseek_key:
            logger.warning("⚠️ لا يوجد مفتاح Groq أو DeepSeek — خدمات التحقق التلقائي لن تعمل.")
        elif groq_key:
            logger.info("✅ GROQ_API_KEY موجودة")
        elif deepseek_key:
            logger.info("✅ DEEPSEEK_API_KEY موجودة (بدون Groq)")

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
        # Keep Telegram bootstrap failures recoverable. The outer runner also
        # retries failures from getMe(), which happens before polling starts.
        timeout=45,
        bootstrap_retries=-1,
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
    
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

    msg = "🧪 فحص مفاتيح الذكاء الاصطناعي\n\n"
    msg += f"🔑 GROQ_API_KEY: {'✅ موجود' if GROQ_API_KEY else '❌ مفقود'}\n"
    msg += f"🔑 DEEPSEEK_API_KEY: {'✅ موجود' if DEEPSEEK_API_KEY else '❌ مفقود'}\n\n"

    def _http_status_message(name: str, status_code: int) -> str:
        if status_code == 200:
            return f"✅ {name}: يعمل بشكل صحيح | HTTP {status_code}"
        if status_code in (401, 403):
            return f"❌ {name}: المفتاح غير صالح أو منتهي الصلاحية | HTTP {status_code}"
        if status_code == 429:
            return f"⚠️ {name}: تم تجاوز حد الطلبات | HTTP {status_code}"
        if 400 <= status_code < 500:
            return f"❌ {name}: طلب مرفوض من الخدمة | HTTP {status_code}"
        if status_code >= 500:
            return f"❌ {name}: عطل مؤقت في خادم الخدمة | HTTP {status_code}"
        return f"⚠️ {name}: استجابة غير متوقعة | HTTP {status_code}"

    for name, key, url, model in [
        ("Groq", GROQ_API_KEY, "https://api.groq.com/openai/v1/chat/completions", "llama-3.3-70b-versatile"),
        ("DeepSeek", DEEPSEEK_API_KEY, "https://api.deepseek.com/chat/completions", "deepseek-chat"),
    ]:
        if not key:
            msg += f"❌ {name}: المفتاح مفقود | HTTP —\n"
            continue
        try:
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": "قل مرحباً"}], "max_tokens": 5},
                timeout=10,
            )
            msg += _http_status_message(name, r.status_code) + "\n"
        except Exception as e:
            msg += f"❌ {name}: لم يصل رد من الخدمة | HTTP — | {type(e).__name__}: {e}\n"
    
    msg += "\n📌 جرّب الآن طلب إحالة بتحقق للتأكد من عمل مسار الكابتشا."
    
    await update.message.reply_text(msg)
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
