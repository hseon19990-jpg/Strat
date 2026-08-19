"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

MANDATORY_MAX_ACTIVE = 10   # الحد الأقصى لعدد القنوات الإجبارية النشطة في نفس الوقت
MANDATORY_PAGE_SIZE   = 5   # عدد القنوات المعروضة للمستخدم دفعة واحدة في بوابة الاشتراك

def count_active_mandatory_channels() -> int:
    with db_conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM mandatory_channels WHERE active=1 AND funding_type='mandatory'"
        ).fetchone()
    return row["n"] if row else 0

async def promote_queued_mandatory_channel(context: ContextTypes.DEFAULT_TYPE, app=None):
    """يُستدعى بعد أي إخراج لقناة إجبارية من القائمة النشطة (اكتمال تمويلها أو تعطيلها يدوياً).
    إن وُجدت قناة إجبارية بانتظار الدور (queued=1) وتوفّر عدد أقل من الحد الأقصى، تُفعَّل تلقائياً
    وتُخطَر مالكها ويُعلَن عنها في الكروب، حتى لا يبقى دور القناة معلّقاً بلا داعٍ."""
    if count_active_mandatory_channels() >= MANDATORY_MAX_ACTIVE:
        return
    with db_conn() as c:
        nxt = c.execute(
            "SELECT * FROM mandatory_channels WHERE queued=1 AND funding_type='mandatory' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if not nxt:
            return
        c.execute("UPDATE mandatory_channels SET active=1, queued=0 WHERE id=%s", (nxt["id"],))

    try:
        await context.bot.send_message(
            nxt["owner_user_id"],
            f"🎉 *أصبحت قناتك الآن ضمن قائمة الاشتراك الإجباري!*\n\n"
            f"📢 القناة: @{nxt['channel_username']}\n"
            f"✅ تحرّر أحد الأماكن العشرة فأصبح دور قناتك، وباتت تظهر الآن لجميع مستخدمي البوت.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        pass


def mandatory_terms_text_html() -> str:
    """نص الشروط المرفق مع أي إعلان في الكروب عن قناة إجبارية جديدة (HTML)."""
    penalty = int(get_setting("channel_leave_penalty") or "75")
    return (
        f"📌 <b>الشروط:</b>\n"
        f"• الاشتراك بهذه القناة أصبح إجبارياً لاستخدام البوت.\n"
        f"• الحد الأقصى للقنوات الإجبارية النشطة في نفس الوقت: {MANDATORY_MAX_ACTIVE} قنوات.\n"
        f"• مغادرة القناة بعد التحقق تخصم {penalty} نقطة تلقائياً من رصيد المستخدم."
    )

async def get_unjoined_mandatory_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """يُرجع قائمة القنوات الإجبارية التي لم ينضم لها المستخدم بعد."""
    with db_conn() as c:
        channels = c.execute(
            "SELECT * FROM mandatory_channels WHERE active=1 AND funding_type='mandatory'"
        ).fetchall()
    unjoined = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(f"@{ch['channel_username']}", user_id)
            if member.status in ("left", "kicked", "banned"):
                unjoined.append(ch)
        except Exception:
            unjoined.append(ch)
    return unjoined

async def count_user_for_fundings(user_id: int, context):
    """
    تحسب هذا المستخدم ضمن التمويلات النشطة التي لم يُحسب فيها بعد.
    الشرط: يجب أن يكون المستخدم قد انضم عبر البوت (سجل في channel_join_rewards).
    عند اكتمال أي تمويل: يُوقَف تلقائياً ويُرسَل إشعار لصاحبه.
    """
    with db_conn() as c:
        fundings = c.execute(
            """SELECT cf.id, cf.channel_username, cf.funding_type,
                      cf.target_members, cf.current_members, cf.user_id AS owner_id,
                      mc.id AS mc_id
               FROM channel_funding cf
               JOIN mandatory_channels mc ON mc.channel_username = cf.channel_username
               WHERE mc.active = 1 AND cf.status = 'active' AND cf.target_members > 0"""
        ).fetchall()

    for f in fundings:
        if f["funding_type"] == "internal":
            with db_conn() as c:
                verified = c.execute(
                    "SELECT 1 FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                    (user_id, f["mc_id"])
                ).fetchone()
            if not verified:
                continue
        else:
            try:
                member = await context.bot.get_chat_member(f"@{f['channel_username']}", user_id)
                if member.status in ("left", "kicked", "banned"):
                    continue
            except Exception:
                continue
        with db_conn() as c:
            c.execute(
                "INSERT INTO channel_funding_counts (user_id, funding_id) VALUES (%s, %s) "
                "ON CONFLICT (user_id, funding_id) DO NOTHING",
                (user_id, f["id"])
            )
            if c.rowcount == 0:
                continue
            c.execute(
                "UPDATE channel_funding SET current_members = current_members + 1 WHERE id = %s",
                (f["id"],)
            )
            row = c.execute(
                "SELECT current_members, target_members FROM channel_funding WHERE id = %s",
                (f["id"],)
            ).fetchone()

        if not row:
            continue
        if row["current_members"] >= row["target_members"]:
            with db_conn() as c:
                c.execute("UPDATE channel_funding SET status='completed' WHERE id=%s", (f["id"],))
                c.execute("UPDATE mandatory_channels SET active=0 WHERE channel_username=%s", (f["channel_username"],))
            try:
                ft_label = "إجباري سريع" if f["funding_type"] == "mandatory" else "داخلي بطيء"
                await context.bot.send_message(
                    chat_id=f["owner_id"],
                    text=(
                        f"🎉 *اكتمل تمويل قناتك!*\n\n"
                        f"📢 القناة: @{f['channel_username']}\n"
                        f"⚙️ النوع: {ft_label}\n"
                        f"👥 العدد المستهدف: {f['target_members']:,} عضو — ✅ تم الوصول!"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
            if f["funding_type"] == "mandatory":
                await promote_queued_mandatory_channel(context)

def mandatory_join_kb(channels, is_owner=False):
    page = channels[:MANDATORY_PAGE_SIZE]
    rows = []
    for ch in page:
        rows.append([InlineKeyboardButton(
            f"📢 {ch['channel_title'] or ('@' + ch['channel_username'])}",
            url=f"https://t.me/{ch['channel_username']}"
        )])
    rows.append([InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_mandatory_join")])
    if is_owner:
        rows.append([InlineKeyboardButton("⏭ تخطى (للمالك فقط)", callback_data="skip_mandatory_gate")])
    return InlineKeyboardMarkup(rows)

async def show_mandatory_gate(update: Update, context: ContextTypes.DEFAULT_TYPE, channels, edit=False, is_owner=False):
    remaining = max(0, len(channels) - MANDATORY_PAGE_SIZE)
    more_note = (
        f"\n\n➕ يوجد *{remaining}* قناة إضافية ستظهر تلقائياً بعد إكمال هذه المجموعة."
        if remaining > 0 else ""
    )
    text = (
        "📢 *الاشتراك الإجباري*\n\n"
        "للمتابعة، يجب عليك الاشتراك بالقنوات التالية أولاً:\n"
        "ثم اضغط «✅ تحقق من الاشتراك»."
        f"{more_note}"
    )
    kb = mandatory_join_kb(channels, is_owner=is_owner)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

async def proceed_after_mandatory(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
    """بعد اجتياز بوابة الاشتراك الإجباري: يعرض سؤال التحقق الرياضي إن كان مفعّلاً، وإلا يطلب الهاتف إن كانت هناك إحالة."""
    user = update.effective_user
    captcha_on = int(get_setting("captcha_enabled") or "0")
    if not captcha_on:
        await ask_for_phone_share(update, context, edit=edit)
        return

    prob, ans = generate_math()
    context.user_data["state"] = "verify_math"
    context.user_data["math_ans"] = ans

    text = f"🔐 للدخول للبوت، أجب على هذه المسألة البسيطة:\n\n❓  *{prob} = ؟*"
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def finalize_verification(update: Update, context: ContextTypes.DEFAULT_TYPE, user, edit=False, skip_referral=False):
    """تُستدعى بعد اجتياز التحقق: تُفعّل المستخدم، تمنح نقاط الإحالة (إلا إذا skip_referral=True)، وتعرض القائمة الرئيسية."""
    set_user_verified(user.id)
    await count_user_for_fundings(user.id, context)
    is_own = (user.id == OWNER_ID)

    referral_note = ""
    credited = (not skip_referral) and credit_referral_if_pending(user.id, context)
    if credited:
        invited_by, rp = credited
        invited_name = md_escape(f"@{user.username}") if user.username else md_escape(user.full_name or "مستخدم")
        inviter_row = get_user(invited_by)
        inviter_name = "صديقك"
        if inviter_row:
            inviter_username = inviter_row.get("username")
            inviter_full_name = inviter_row.get("full_name")
            inviter_name = md_escape(f"@{inviter_username}") if inviter_username else md_escape(inviter_full_name or "صديقك")
        try:
            await context.bot.send_message(
                chat_id=invited_by,
                text=f"🎉 مبروك! لقد أكمل المستخدم {invited_name} الاشتراك والتحقق عن طريق رابط دعوتك، وحصلت على {rp} نقطة.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as _e:
            logger.warning(f"⚠️ فشل إرسال إشعار الإحالة للمستخدم {invited_by}: {_e}")
        referral_note = f"\n\n🔗 لقد دخلت إلى رابط دعوة صديقك {inviter_name} وقد حصل على {rp} نقطة."

    context.user_data["state"] = "main_menu"
    db_user = get_user(user.id)
    pts = db_user["points"] if db_user else 0
    welcome = get_setting("welcome_message") or "أهلاً بك!"
    text = f"✅ *تم التحقق بنجاح!*\n\n{welcome}\n\n💰 رصيدك: {pts} نقطة{referral_note}"
    kb = main_menu_kb(is_own, is_supervisor_user=is_supervisor(user.id) and not is_own)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    return credited

async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يبدأ تدفّق المستخدم الجديد/غير المتحقق: بوابة الاشتراك الإجباري أولاً، ثم التحقق."""
    user = update.effective_user
    unjoined = await get_unjoined_mandatory_channels(context, user.id)
    is_owner = (user.id == OWNER_ID)
    if unjoined:
        context.user_data["state"] = "await_mandatory_join"
        await show_mandatory_gate(update, context, unjoined, edit=False, is_owner=is_owner)
        return
    await proceed_after_mandatory(update, context, edit=False)

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    invited_by = int(args[0]) if args and args[0].isdigit() else 0

    db_user = get_or_create_user(user.id, user.username or "", user.full_name or "", invited_by)
    is_own = (user.id == OWNER_ID)

    # ─── فحص الحظر في /start ──────────────────────────
    if not is_own and is_user_banned(user.id):
        await update.message.reply_text("🚫 تم حظرك من استخدام هذا البوت.")
        return

    if is_maintenance_on() and not is_own:
        await update.message.reply_text(MAINTENANCE_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return

    if db_user.get("verified", 0):
        unjoined = await get_unjoined_mandatory_channels(context, user.id)
        if unjoined:
            context.user_data["state"] = "await_mandatory_join"
            await show_mandatory_gate(update, context, unjoined, edit=False, is_owner=is_own)
            return
        await count_user_for_fundings(user.id, context)
        context.user_data["state"] = "main_menu"
        db_user = get_user(user.id)
        pts = db_user["points"] if db_user else 0
        welcome = get_setting("welcome_message") or "أهلاً بك!"
        await update.message.reply_text(
            f"👋 *أهلاً بك مجدداً!*\n\n{welcome}\n\n💰 رصيدك: {pts} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )
        return

    await update.message.reply_text(
        "👋 *أهلاً بك!*", parse_mode=ParseMode.MARKDOWN
    )
    await start_onboarding(update, context)

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == OWNER_ID:
        await update.message.reply_text(
            "⚙️ *لوحة المالك:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return
    if is_supervisor(user.id):
        await update.message.reply_text(
            "🛡 *لوحة المشرف:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=supervisor_panel_kb()
        )
        return
    await update.message.reply_text("⛔ هذا الأمر للمالك والمشرفين فقط.")

async def cmd_import_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /import_session <session_string> — يستورد جلسة قديمة ويضيف رقمها للمخزون."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    if not context.args:
        await update.message.reply_text(
            "الاستخدام:\n`/import_session SESSION_STRING`\n\nالصق رمز الجلسة بعد الأمر.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    session_str = context.args[0].strip()
    session_str = _maybe_convert_session(session_str)
    msg = await update.message.reply_text("⏳ جاري التحقق من الجلسة...")
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        await msg.edit_text("❌ متغيرات TELEGRAM_API_ID أو TELEGRAM_API_HASH غير مضبوطة.")
        return
    try:
        client = TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            await client.disconnect()
            await msg.edit_text("❌ الجلسة منتهية الصلاحية أو غير صالحة. لا يمكن الاستيراد.")
            return
        me = await client.get_me()
        phone = me.phone if me.phone.startswith("+") else f"+{me.phone}"
        await client.disconnect()
        with db_conn() as c:
            existing = c.execute(
                "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
            ).fetchone()
            if existing:
                c.execute(
                    "UPDATE number_stock SET session_string=%s, assigned_to=NULL, assigned_at=NULL,"
                    " forced_ref_excluded=FALSE WHERE phone_number=%s",
                    (session_str, phone)
                )
                action = "تم تحديث"
            else:
                c.execute(
                    "INSERT INTO number_stock (phone_number, session_string, forced_ref_excluded)"
                    " VALUES (%s, %s, FALSE)",
                    (phone, session_str)
                )
                action = "تمت إضافة"
        await msg.edit_text(
            f"✅ *{action} الرقم بنجاح!*\n\n📱 الرقم: `{phone}`\n\n"
            "الرقم الآن أُضيف تلقائياً لقائمة إحالة بوت إجباري وجاهز للاستخدام.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await msg.edit_text(f"❌ خطأ أثناء الاستيراد:\n`{e}`", parse_mode=ParseMode.MARKDOWN)

async def cmd_import_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /import_sessions — استيراد جماعي للجلسات عبر JSON."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    _pending_bulk_import.add(user.id)
    context.user_data["state"] = "os_bulk_import"
    await update.message.reply_text(
        "📥 *استيراد جماعي للحسابات*\n\n"
        "أرسل JSON بالصيغة التالية:\n\n"
        "```\n"
        '["SESSION1", "SESSION2", "SESSION3"]\n'
        "```\n\n"
        "أو مع أرقام (اختياري):\n\n"
        "```\n"
        '[{"session": "SESSION1", "phone": "+212xxxxxxx"},\n'
        ' {"session": "SESSION2"}]\n'
        "```",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_import_hex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /import_hex — استيراد جلسات بصيغة hex_auth_key:dc_id (سطر لكل حساب)."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    context.user_data["state"] = "os_import_hex"
    await update.message.reply_text(
        "📥 *استيراد حسابات بصيغة hex:dc*\n\n"
        "الصيغة المتوقعة — سطر واحد لكل حساب:\n"
        "`<auth_key_hex>:<dc_id>`\n\n"
        "مثال:\n"
        "`12f6766c...3f04b:5`\n\n"
        "الـ dc\\_id يكون 1-5 (الرقم بعد النقطتين).\n"
        "أرسل النص الآن (أو /cancel للإلغاء).",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_mass_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /mass_reset
    يقرأ ملفات الجلسة لكل الحسابات غير المباعة ويطرد جميع الجلسات الأخرى.
    الحسابات المباعة (ever_sold=TRUE) تُتخطى تماماً — خارج نطاق البوت.
    """
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        await update.message.reply_text("❌ متغيرات API_ID / API_HASH غير مضبوطة.")
        return

    # ─── جلب كل الحسابات غير المباعة التي لديها ملف جلسة ──────────────────
    with db_conn() as _c:
        rows = _c.execute(
            "SELECT id, phone_number, session_string FROM number_stock "
            "WHERE ever_sold IS NOT TRUE "
            "  AND session_string IS NOT NULL"
        ).fetchall()

    total = len(rows)
    if total == 0:
        await update.message.reply_text("ℹ️ لا يوجد حسابات غير مباعة لديها ملف جلسة.")
        return

    status_msg = await update.message.reply_text(
        f"⏳ بدأ إعادة قراءة الملفات وطرد الجلسات...\n"
        f"📦 إجمالي الحسابات: *{total}*\n"
        f"⏱️ الرجاء الانتظار...",
        parse_mode=ParseMode.MARKDOWN
    )

    done, kicked_ok, already_solo, failed, kicked_out = 0, 0, 0, 0, 0

    for rec in rows:
        rec = dict(rec)
        phone = rec["phone_number"]
        _client = None
        try:
            _client = TelegramClient(
                StringSession(rec["session_string"]),
                int(TELEGRAM_API_ID), TELEGRAM_API_HASH
            )
            await _client.connect()

            if not await _client.is_user_authorized():
                kicked_out += 1
                with db_conn() as _cx:
                    _es2 = _cx.execute(
                        "SELECT ever_sold FROM number_stock WHERE id=%s", (rec["id"],)
                    ).fetchone()
                    if _es2 and not _es2["ever_sold"]:
                        _cx.execute("DELETE FROM number_stock WHERE id=%s", (rec["id"],))
                        logger.info(
                            f"🗑️ حذف تلقائي (mass_reset): الرقم {phone} — جلسة منتهية."
                        )
                    else:
                        _cx.execute(
                            "UPDATE number_stock SET last_authorized=FALSE WHERE id=%s",
                            (rec["id"],)
                        )
                continue

            # ── طرد كل الجلسات الأخرى ─────────────────────────────────
            try:
                await _client(ResetAuthorizationsRequest())
                kicked_ok += 1
            except Exception as _re:
                logger.debug(f"mass_reset: ResetAuth فشل للرقم {phone}: {_re}")
                failed += 1

            # ── فحص ما إذا كان البوت الجلسة الوحيدة ─────────────────────
            _dev = -1
            try:
                _dev = await get_device_count(_client)
            except Exception:
                pass
            _is_solo_r = (_dev == 1)
            if _is_solo_r:
                already_solo += 1

            # ── تسجيل IP الجلسة الجديدة بعد الطرد ────────────────────────
            _new_ip = None
            try:
                _new_ip = await get_session_ip(_client)
            except Exception:
                pass

            with db_conn() as _cx:
                _cx.execute(
                    "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s, "
                    "last_authorized=TRUE, bot_session_ip=%s WHERE id=%s",
                    (_is_solo_r, _new_ip, rec["id"])
                )

            # ── تفعيل can_send_code إذا أصبح منفرداً ─────────────────────
            if _is_solo_r:
                asyncio.create_task(
                    _test_and_set_can_send_code(phone, rec["session_string"], rec["id"])
                )

        except Exception as _e:
            logger.warning(f"mass_reset: خطأ على الرقم {phone}: {_e}")
            failed += 1
        finally:
            if _client:
                try:
                    await _client.disconnect()
                except Exception:
                    pass
            done += 1

            # ── تحديث رسالة التقدم كل 5 حسابات ──────────────────────────
            if done % 5 == 0 or done == total:
                try:
                    await status_msg.edit_text(
                        f"⏳ جاري المعالجة... {done}/{total}\n\n"
                        f"✅ طُردت جلساته: *{kicked_ok}*\n"
                        f"🔒 كان منفرداً أصلاً: *{already_solo}*\n"
                        f"⛔ جلسة منتهية: *{kicked_out}*\n"
                        f"❌ فشل: *{failed}*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass

    # ─── رسالة النتيجة النهائية ──────────────────────────────────────────
    await status_msg.edit_text(
        f"✅ *اكتملت عملية إعادة القراءة والطرد الجماعي*\n\n"
        f"📦 إجمالي الحسابات المعالجة: *{total}*\n"
        f"🔐 نجح الطرد (ResetAuthorizations): *{kicked_ok}*\n"
        f"🔒 كان منفرداً مسبقاً (solo): *{already_solo}*\n"
        f"⛔ جلسة منتهية الصلاحية: *{kicked_out}*\n"
        f"❌ فشل الاتصال أو الطرد: *{failed}*\n\n"
        f"🚫 الحسابات المباعة: *لم تُمسّ* (خارج النطاق)",
        parse_mode=ParseMode.MARKDOWN
    )
    logger.info(
        f"mass_reset مكتمل | total={total} kicked={kicked_ok} "
        f"solo={already_solo} expired={kicked_out} failed={failed}"
    )

async def cmd_addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /addpoints <user_id> [points].
    يقبل المعرف وحده ثم يطلب عدد النقاط في رسالة مستقلة.
    """
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return

    args = context.args
    if len(args) not in (1, 2):
        await update.message.reply_text(
            "الاستخدام:\n"
            "/addpoints <user_id> [points]\n\n"
            "مثال مباشر: `/addpoints 123456789 500`\n"
            "أو أرسل المعرف أولاً ثم عدد النقاط.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("⚠️ تأكد أن معرف المستخدم رقم صحيح.")
        return

    target = get_user(target_id)
    if not target:
        await update.message.reply_text("⚠️ لا يوجد مستخدم بهذا المعرف في قاعدة البيانات.")
        return

    if len(args) == 1:
        context.user_data.pop("edit_svc_id", None)
        context.user_data["points_target_id"] = target_id
        context.user_data["points_mode"] = "give"
        context.user_data["state"] = "os_await_points_amount"
        await update.message.reply_text(
            f"👤 المستخدم: {target.get('full_name') or target_id}\n"
            f"🆔 المعرف: `{target_id}`\n"
            f"💰 الرصيد الحالي: {target.get('points', 0)} نقطة\n\n"
            "أرسل عدد النقاط الآن (رقم موجب):",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        pts = int(args[1])
    except ValueError:
        await update.message.reply_text("⚠️ تأكد أن عدد النقاط رقم صحيح.")
        return

    if pts == 0:
        await update.message.reply_text("⚠️ عدد النقاط لا يمكن أن يكون صفراً.")
        return

    if pts > 0:
        add_points(target_id, pts)
        actual = pts
    else:
        actual = -deduct_points_clamped(target_id, -pts)

    await update.message.reply_text(f"✅ تم تعديل رصيد المستخدم {target_id} بمقدار {actual} نقطة.")

    try:
        if actual > 0:
            await context.bot.send_message(target_id, f"💰 تم إضافة {actual} نقطة إلى رصيدك من قبل الإدارة.")
        elif actual < 0:
            await context.bot.send_message(target_id, f"⚠️ تم خصم {-actual} نقطة من رصيدك من قبل الإدارة.")
    except Exception:
        pass

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
async def cmd_grant_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /grant_ref <invited_user_id>
    يمنح نقاط الإحالة للداعي في حال كانت ضائعة (referral_credited=1 لكن النقاط لم تُمنح فعلاً).
    يستخدم لتصحيح حالات سببها مايغريشن قديم وضع referral_credited=1 بدون منح نقاط.
    """
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return

    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "📋 *الاستخدام:*\n`/grant_ref <user_id_المدعو>`\n\n"
            "يمنح نقاط الإحالة للداعي إن كانت لم تُمنح سابقاً.\n\n"
            "💡 *للعثور على الإحالات الضائعة:*\n"
            "ابحث عن مستخدمين عندهم `invited_by != 0` وتم تسجيلهم قبل تفعيل نظام النقاط.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    invited_user_id = int(args[0])

    with db_conn() as c:
        row = c.execute(
            "SELECT user_id, invited_by, referral_credited, full_name, username FROM users WHERE user_id=?",
            (invited_user_id,)
        ).fetchone()

    if not row:
        await update.message.reply_text(f"⚠️ لا يوجد مستخدم بالمعرف {invited_user_id} في قاعدة البيانات.")
        return

    invited_by = row["invited_by"]
    if not invited_by or invited_by == 0:
        await update.message.reply_text(f"⚠️ المستخدم {invited_user_id} لم يدخل عبر رابط دعوة (invited_by=0).")
        return

    inviter = get_user(invited_by)
    if not inviter:
        await update.message.reply_text(f"⚠️ الداعي (ID: {invited_by}) غير موجود في قاعدة البيانات.")
        return

    rp = int(get_setting("referral_points") or "30")

    with db_conn() as c:
        c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (rp, invited_by))
        c.execute(
            "UPDATE users SET referral_credited=1, credited_at=COALESCE(credited_at, NOW()) WHERE user_id=%s",
            (invited_user_id,)
        )

    invited_name = row.get("username") or row.get("full_name") or str(invited_user_id)
    inviter_name = inviter.get("username") or inviter.get("full_name") or str(invited_by)

    await update.message.reply_text(
        f"✅ *تم منح نقاط الإحالة الضائعة*\n\n"
        f"👤 المدعو: @{invited_name} (`{invited_user_id}`)\n"
        f"🎁 الداعي: @{inviter_name} (`{invited_by}`) ← حصل على {rp} نقطة\n"
        f"💰 رصيد الداعي الآن: {inviter['points'] + rp} نقطة",
        parse_mode=ParseMode.MARKDOWN
    )

    try:
        await context.bot.send_message(
            chat_id=invited_by,
            text=f"🎉 تم تصحيح إحالة ضائعة! حصلت على {rp} نقطة بسبب دعوة المستخدم {invited_name}."
        )
    except Exception:
        pass

# ────────────────────────────────────────────────────────────
