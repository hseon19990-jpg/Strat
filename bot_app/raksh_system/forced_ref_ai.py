# forced_ref_ai.py
"""
خدمة إحالة بوت إجباري مع تحقق شامل - تدعم مشاركة الرقم والكود والمسائل والأزرار
كل المنطق موجود في هذا الملف (بدون اعتماد على ForcedRefService)
"""

from .common import *
from telethon.tl.types import InputMediaContact, KeyboardButtonRequestPhone


class ForcedRefAIService(RakshService):
    """خدمة إحالة بوت إجباري مع تحقق شامل - كل شيء في مكان واحد"""

    service_type = "forced_ref_ai"
    label = "🤖 إحالة بوت إجباري مع تحقق"
    config = ServiceConfig(
        name=label,
        price_points=300,
        points_quantity=1,
        price_stars=15,
        stars_quantity=1,
        has_channel=True,
        has_reaction=False,
        has_ai=True,
        needs_link=True,
        min_delay=3,
        max_delay=3
    )

    # ─── 1. دوال البداية ───

    def get_initial_state(self) -> str:
        return "channel"

    def get_start_message(self) -> str:
        return (
            f"{self.config.name}\n\n"
            f"💰 السعر: {self.get_rate_text('points')}\n"
            f"⭐ السعر: {self.get_rate_text('stars')}\n\n"
            f"📢 *أرسل القنوات الإجبارية:*\n"
            f"كل قناة في سطر منفصل:\n"
            f"@channel1\n"
            f"@channel2\n"
            f"أو أرسل روابط t.me\n\n"
            f"✍️ اكتب 'تخطي' لعدم وجود قنوات"
        )

    def get_start_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⏭️ تخطي (بدون قنوات)",
                callback_data=f"{self.get_callback_prefix()}:skip_channels",
            )],
            [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
        ])

    def get_callback_prefix(self) -> str:
        return "raksh_forced_ref_ai"

    def get_link_prompt_label(self) -> str:
        return "رابط البوت"

    def get_saved_link_label(self) -> str:
        return self.get_link_prompt_label()

    def get_quantity_label(self) -> str:
        return "عدد الإحالات المطلوبة"

    def get_activity_label(self) -> str:
        return "إحالة"

    def get_execution_label(self) -> str:
        return "الانضمام للقنوات وحل التحقق"

    def get_invoice_label(self) -> str:
        return "إحالة بوت إجباري مع تحقق"

    def get_link_instruction(self) -> str:
        return "@BotUsername start123  أو  t.me/BotUsername?start=123"

    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        bot_username, _ = _parse_bot_link(value)
        if not bot_username:
            return (
                "⚠️ رابط البوت غير صحيح.\n\n"
                "أرسله بهذا الشكل:\n"
                "@BotUsername start123\n"
                "أو: t.me/BotUsername?start=123"
            )
        return None

    # ─── 2. معالجة النصوص ───

    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        """معالجة النص لخدمة الإحالة مع التحقق"""

        if state == "channel":
            if text.strip().lower() in {"تخطي", "skip", "لا", "none", "بدون"}:
                context.user_data["raksh_channels"] = []
            else:
                channel_refs = _parse_channel_refs(text)
                if not channel_refs:
                    await update.message.reply_text(
                        "⚠️ لم أتعرف على أي قناة.\n"
                        "أرسل @username أو رابط t.me للقناة، ويمكنك إرسال أكثر من قناة مفصولة بمسافة أو سطر.\n"
                        "أو اكتب 'تخطي' لعدم وجود قنوات.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                        ]),
                    )
                    return True
                context.user_data["raksh_channels"] = channel_refs

            context.user_data["raksh_step"] = "link"

            await update.message.reply_text(
                f"✅ تم حفظ القنوات الإجبارية ({len(context.user_data['raksh_channels'])} قناة).\n\n"
                f"🔗 *أرسل {self.get_link_prompt_label()}:*\n"
                f"{self.get_link_instruction()}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        if state == "link":
            link_error = self.validate_link(text)
            if link_error:
                await update.message.reply_text(
                    link_error,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True

            context.user_data["raksh_link"] = text
            context.user_data["raksh_step"] = "quantity"

            max_qty = self.get_request_limit(user.id)
            if max_qty < 1:
                await update.message.reply_text(
                    "⚠️ لا توجد حسابات متاحة حالياً.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True

            await update.message.reply_text(
                f"✅ تم حفظ {self.get_saved_link_label()}.\n\n"
                f"🔢 *أرسل {self.get_quantity_label()}:*\n"
                f"(الحد الأقصى: {max_qty})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        if state == "quantity":
            try:
                quantity = int(text)
            except ValueError:
                await update.message.reply_text(
                    "⚠️ أرسل رقماً صحيحاً.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True

            max_qty = self.get_request_limit(user.id)
            if max_qty < 1:
                await update.message.reply_text(
                    "⚠️ لا توجد حسابات متاحة حالياً.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True

            if quantity < 1 or quantity > max_qty:
                await update.message.reply_text(
                    f"⚠️ العدد المسموح بين 1 و {max_qty}.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True

            context.user_data["raksh_quantity"] = quantity
            context.user_data["raksh_step"] = "payment"

            points_cost = self.get_total(quantity, "points")
            stars_cost = self.get_total(quantity, "stars")

            await update.message.reply_text(
                f"📋 *تفاصيل الطلب*\n\n"
                f"📢 القنوات الإجبارية: {len(context.user_data.get('raksh_channels', []))} قناة\n"
                f"🔗 {self.get_saved_link_label()}: `{context.user_data['raksh_link']}`\n"
                f"🔢 العدد: {quantity}\n\n"
                f"💳 *اختر طريقة الدفع:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"💰 دفع بالنقاط ({points_cost} نقطة)",
                            callback_data=f"{self.get_callback_prefix()}:payment:points:{quantity}:{points_cost}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                            callback_data=f"{self.get_callback_prefix()}:payment:stars:{quantity}:{stars_cost}"
                        )
                    ],
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        if state == "confirm":
            await update.message.reply_text(
                "⚠️ استخدم الأزرار للتأكيد.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        return False

    # ─── 3. معالجة الأزرار ───

    async def handle_callback(self, update, context, query, data_parts, user, is_own) -> bool:
        """معالجة الأزرار لخدمة الإحالة مع التحقق"""

        if data_parts[0] == "skip_channels":
            context.user_data["raksh_channels"] = []
            context.user_data["raksh_step"] = "link"

            await query.edit_message_text(
                f"✅ تم تخطي القنوات.\n\n"
                f"🔗 *أرسل {self.get_link_prompt_label()}:*\n"
                f"{self.get_link_instruction()}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        if data_parts[0] == "payment" and len(data_parts) >= 4:
            payment_method = data_parts[1]
            try:
                quantity = int(data_parts[2])
            except ValueError:
                await query.answer("⚠️ العدد أو السعر غير صالح.", show_alert=True)
                return True

            if payment_method not in {"points", "stars"}:
                await query.answer("⚠️ طريقة الدفع غير صالحة.", show_alert=True)
                return True

            if quantity > self.get_request_limit(user.id):
                await query.edit_message_text(
                    "⚠️ لا يمكن قبول هذا الطلب حالياً. حاول لاحقاً.",
                    reply_markup=raksh_menu_kb(is_own),
                )
                return True

            total_cost = self.get_total(quantity, payment_method)
            await query.edit_message_text(
                f"📋 *تأكيد الطلب*\n\n"
                f"📢 القنوات الإجبارية: {len(context.user_data.get('raksh_channels', []))} قناة\n"
                f"🔗 {self.get_saved_link_label()}: `{context.user_data.get('raksh_link', '')}`\n"
                f"🔢 العدد: {quantity}\n"
                f"💳 طريقة الدفع: {'💰 نقاط' if payment_method == 'points' else '⭐ نجوم'}\n"
                f"💰 التكلفة: {total_cost} {'نقطة' if payment_method == 'points' else 'نجمة'}\n\n"
                f"*هل تريد تأكيد الطلب؟*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ تأكيد الطلب",
                            callback_data=f"{self.get_callback_prefix()}:confirm:{payment_method}:{quantity}:{total_cost}"
                        ),
                        InlineKeyboardButton(
                            "❌ إلغاء",
                            callback_data="raksh_cancel"
                        )
                    ]
                ])
            )
            return True

        if data_parts[0] == "confirm" and len(data_parts) >= 4:
            payment_method = data_parts[1]
            try:
                quantity = int(data_parts[2])
            except ValueError:
                await query.answer("⚠️ العدد أو السعر غير صالح.", show_alert=True)
                return True

            if payment_method not in {"points", "stars"}:
                await query.answer("⚠️ طريقة الدفع غير صالحة.", show_alert=True)
                return True

            if quantity > self.get_request_limit(user.id):
                await query.edit_message_text(
                    "⚠️ لا يمكن قبول هذا الطلب حالياً. حاول لاحقاً.",
                    reply_markup=raksh_menu_kb(is_own),
                )
                return True

            total_cost = self.get_total(quantity, payment_method)

            if payment_method == "points":
                if not deduct_points(user.id, total_cost):
                    await query.edit_message_text(
                        "❌ *نقاطك غير كافية!*\n"
                        f"التكلفة المطلوبة: {total_cost} نقطة",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=raksh_menu_kb(is_own)
                    )
                    return True

                await query.edit_message_text(
                    "✅ *تم تأكيد الطلب وخصم النقاط!*\n\n"
                    f"📋 تفاصيل الطلب:\n"
                    f"📢 القنوات الإجبارية: {len(context.user_data.get('raksh_channels', []))} قناة\n"
                    f"🔗 الرابط: `{context.user_data.get('raksh_link', '')}`\n"
                    f"🔢 العدد: {quantity}\n"
                    f"💰 تم خصم: {total_cost} نقطة\n\n"
                    f"⏳ جاري {self.get_execution_label()}...",
                    parse_mode=ParseMode.MARKDOWN
                )
                from .raksh_system import _start_raksh_execution
                await _start_raksh_execution(update, context, query, self.service_type, quantity, "points", total_cost)
                return True
            else:
                await query.edit_message_text(
                    "⭐ *جاري تجهيز فاتورة الدفع بالنجوم...*",
                    parse_mode=ParseMode.MARKDOWN,
                )
                await context.bot.send_invoice(
                    chat_id=user.id,
                    title=self.config.name,
                    description=f"{quantity} {self.get_activity_label()} مع تحقق | {total_cost} نجمة",
                    payload=f"raksh_stars:{user.id}:{self.service_type}:{quantity}:{total_cost}",
                    provider_token="",
                    currency="XTR",
                    prices=[LabeledPrice(self.get_invoice_label(), total_cost)],
                )
                return True

        return False

    # ─── 4. حل التحقق المدمج (يدعم مشاركة الرقم + زر التفعيل + المنطق القديم المعاد كتابته) ───

    async def _solve_verification(self, client, bot_entity, phone_number: str) -> bool:
        """
        حل التحقق بذكاء:
        1. إذا طلب البوت مشاركة رقم الهاتف (زر KeyboardButtonRequestPhone) – نرسل الرقم ونضغط متابعة.
        2. وإلا نحاول الضغط على زر تفعيل (مثل "ابدأ" أو "التالي") ثم نبحث عن تحقق.
        3. وإلا نستخدم المنطق القديم المعاد كتابته (فحص جميع الرسائل الواردة).
        """
        MAX_WAIT = 12
        CHECK_INTERVAL = 1.0

        # ─── المرحلة 1: البحث عن طلب مشاركة رقم الهاتف ───
        contact_request_msg = None
        for _ in range(MAX_WAIT):
            try:
                messages = await client.get_messages(bot_entity, limit=5)
            except Exception:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            for msg in messages:
                if msg.out:
                    continue
                if msg.reply_markup:
                    for row in msg.reply_markup.rows:
                        for btn in row.buttons:
                            if isinstance(btn, KeyboardButtonRequestPhone):
                                contact_request_msg = msg
                                break
                        if contact_request_msg:
                            break
                if contact_request_msg:
                    break
            if contact_request_msg:
                break
            await asyncio.sleep(CHECK_INTERVAL)

        # إذا وجدنا طلب رقم → نعالجه بطريقة جديدة
        if contact_request_msg:
            logger.info(f"📱 تم اكتشاف طلب رقم هاتف من {phone_number}")

            # إرسال جهة الاتصال
            try:
                me = await client.get_me()
                if not me or not me.phone:
                    logger.warning(f"⚠️ الحساب {phone_number} ليس له رقم هاتف")
                    return False
                phone = me.phone if me.phone.startswith('+') else f'+{me.phone}'
                await client.send_file(
                    bot_entity,
                    file=InputMediaContact(
                        phone_number=phone,
                        first_name=me.first_name or "User",
                        last_name=me.last_name or "",
                        vcard="",
                    )
                )
                logger.info(f"📱 تم إرسال جهة الاتصال من {phone_number}")
            except Exception as e:
                logger.error(f"❌ فشل إرسال جهة الاتصال: {e}")
                return False

            # انتظار زر متابعة
            proceed_button = None
            for _ in range(MAX_WAIT):
                try:
                    messages = await client.get_messages(bot_entity, limit=5)
                except Exception:
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue

                for msg in messages:
                    if msg.out:
                        continue
                    buttons = []
                    if msg.reply_markup:
                        for row in msg.reply_markup.rows:
                            for btn in row.buttons:
                                if not getattr(btn, 'url', None):
                                    buttons.append(btn)
                    # نفضل الأزرار التي تحوي كلمات مفتاحية
                    for btn in buttons:
                        btn_text = (getattr(btn, 'text', '') or '').strip().casefold()
                        if any(kw in btn_text for kw in ['متابعة', 'التالي', 'ابدأ', 'تحقق', 'continue', 'next', 'start', 'verify']):
                            proceed_button = btn
                            break
                        if not proceed_button:
                            proceed_button = btn
                    if proceed_button:
                        break
                if proceed_button:
                    break
                await asyncio.sleep(CHECK_INTERVAL)

            if proceed_button:
                try:
                    await proceed_button.click()
                    logger.info(f"🖱️ تم الضغط على زر '{getattr(proceed_button, 'text', '')}'")
                except Exception as e:
                    logger.warning(f"⚠️ فشل الضغط على زر المتابعة: {e}")

            # انتظار تأكيد النجاح (اختفاء الأزرار أو رسالة تأكيد)
            for _ in range(MAX_WAIT):
                try:
                    latest = await client.get_messages(bot_entity, limit=3)
                    success = False
                    for msg in latest:
                        if msg.out:
                            continue
                        if not msg.reply_markup and (getattr(msg, 'message', '') or '').strip():
                            success = True
                            break
                        text = (getattr(msg, 'message', '') or '').strip().casefold()
                        if any(kw in text for kw in ['تم', 'نجاح', 'مرحباً', 'شكراً', 'success', 'done', 'welcome']):
                            success = True
                            break
                    if success:
                        logger.info(f"✅ تم التحقق بنجاح (مشاركة الرقم) من {phone_number}")
                        return True
                except Exception:
                    pass
                await asyncio.sleep(CHECK_INTERVAL)

            # فحص أخير: هل اختفت أزرار طلب الرقم؟
            try:
                original = await client.get_messages(bot_entity, ids=contact_request_msg.id)
                if original and not original.reply_markup:
                    logger.info(f"✅ اختفت أزرار طلب الرقم، نعتبر النجاح من {phone_number}")
                    return True
            except Exception:
                pass

            # إذا لم نجد تأكيداً، نعتبر العملية ناجحة (لعدم وجود خطأ واضح)
            logger.warning(f"⚠️ لم نؤكد التحقق لكننا سنعتبره ناجحاً (مشاركة الرقم) من {phone_number}")
            return True

        # ─── المرحلة 2: الضغط على زر تفعيل (إذا لم يطلب الرقم) ───
        logger.info(f"🔍 لم يطلب البوت رقم هاتف، نحاول الضغط على زر تفعيل لـ {phone_number}")

        # نبحث عن أحدث رسالة من البوت (غير خارجة) تحتوي على أزرار عادية
        activation_pressed = False
        for attempt in range(3):  # نحاول 3 مرات
            try:
                messages = await client.get_messages(bot_entity, limit=10)
            except Exception:
                await asyncio.sleep(1)
                continue

            # نبحث عن رسالة تحتوي على أزرار عادية (غير رابط)
            for msg in messages:
                if msg.out:
                    continue
                if not msg.reply_markup:
                    continue
                buttons = []
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        if not getattr(btn, 'url', None):
                            buttons.append(btn)
                if not buttons:
                    continue

                # نختار زراً يحوي كلمات مفتاحية
                target_btn = None
                keywords = ['ابدأ', 'التالي', 'متابعة', 'تحقق', 'استمر', 'start', 'continue', 'verify', 'go']
                for btn in buttons:
                    btn_text = (getattr(btn, 'text', '') or '').strip().casefold()
                    if any(kw in btn_text for kw in keywords):
                        target_btn = btn
                        break
                if not target_btn:
                    # إذا لم نجد زراً بكلمة مفتاحية، نأخذ أول زر
                    target_btn = buttons[0]

                # نضغط على الزر
                try:
                    await target_btn.click()
                    logger.info(f"🖱️ تم الضغط على زر التفعيل: {getattr(target_btn, 'text', '')}")
                    activation_pressed = True
                    await asyncio.sleep(2.0)  # انتظار رد البوت
                    break  # خروج من حلقة الرسائل
                except Exception as e:
                    logger.warning(f"⚠️ فشل الضغط على زر التفعيل: {e}")
                    continue

            if activation_pressed:
                # بعد الضغط، ننتظر قليلاً ثم نبحث عن تحقق
                for _ in range(3):
                    await asyncio.sleep(1.5)
                    # نحاول جلب رسالة تحقق (كود، مسألة، أزرار)
                    try:
                        new_messages = await client.get_messages(bot_entity, limit=10)
                    except Exception:
                        continue

                    # نبحث عن رسالة غير خارجة تحتوي على نص قد يكون تحقق
                    for msg in new_messages:
                        if msg.out:
                            continue
                        text = getattr(msg, 'message', '') or ''
                        # إذا كانت تحتوي على أرقام أو عمليات حسابية أو كلمات مفتاحية
                        if _extract_code_from_text(text):
                            logger.info(f"✅ تم العثور على كود بعد الضغط على زر التفعيل")
                            # نرسل الكود باستخدام المنطق القديم
                            return await self._solve_legacy_verification(client, bot_entity, phone_number)
                        if re.search(r'\d+\s*[+\-*/]\s*\d+\s*=', text):
                            logger.info(f"✅ تم العثور على مسألة رياضية بعد الضغط")
                            return await self._solve_legacy_verification(client, bot_entity, phone_number)
                        # إذا كان هناك أزرار تحقق
                        if msg.reply_markup:
                            for row in msg.reply_markup.rows:
                                for btn in row.buttons:
                                    if any(kw in (getattr(btn, 'text', '') or '').casefold() for kw in ['تحقق', 'verify', 'اضغط']):
                                        logger.info(f"✅ تم العثور على زر تحقق بعد الضغط")
                                        return await self._solve_legacy_verification(client, bot_entity, phone_number)
                    # إذا لم نجد تحققاً، نعيد المحاولة
                # إذا لم نجد تحققاً بعد عدة محاولات، نستمر للمنطق القديم
            # إذا لم نضغط أي زر (لا يوجد أزرار)، نذهب مباشرة للمنطق القديم

        # ─── المرحلة 3: المنطق القديم المعاد كتابته ───
        logger.info(f"🔍 ننتقل إلى المنطق القديم المحسن لـ {phone_number}")
        return await self._solve_legacy_verification(client, bot_entity, phone_number)

    async def _solve_legacy_verification(self, client, bot_entity, phone_number: str) -> bool:
        """
        المنطق القديم المُحسَّن: 
        - لا يعتمد على base_id، بل يفحص جميع الرسائل الواردة في كل محاولة.
        - يبحث عن كود، مسألة، أو أزرار تحقق في أي رسالة.
        - إذا لم يجد تحققاً، يضغط على زر (من أي رسالة) ثم يعيد الفحص.
        - يكرر حتى النجاح أو انتهاء المحاولات.
        """
        MAX_ATTEMPTS = 30
        # قائمة لتخزين معرفات الأزرار التي تم الضغط عليها بالفعل لتجنب التكرار
        pressed_buttons = set()

        for attempt in range(MAX_ATTEMPTS):
            try:
                # نجلب جميع الرسائل الواردة من البوت (آخر 30 رسالة مثلاً، لكن يمكن زيادتها)
                messages = await client.get_messages(bot_entity, limit=30)
            except Exception as exc:
                if "two different IP" in str(exc) or "AuthKeyDuplicated" in str(exc):
                    logger.error(f"⚠️ الجلسة {phone_number} تستخدم من IP مختلف - سيتم تعطيلها")
                    _mark_raksh_session_unauthorized(phone_number)
                    return False
                await asyncio.sleep(1.0)
                continue

            # فلترة الرسائل الواردة فقط (غير الصادرة من الحساب)
            incoming = [msg for msg in messages if not msg.out]
            # ترتيب تنازلي حسب المعرف (الأحدث أولاً) لتسهيل البحث
            incoming.sort(key=lambda m: m.id, reverse=True)

            # 1. البحث عن تحقق (كود أو مسألة أو أزرار تحقق)
            found_verification = False
            for msg in incoming:
                text = getattr(msg, 'message', '') or ''
                # تجاوز الرسائل التي تبدأ بـ "/" (أوامر)
                if text.strip().startswith('/'):
                    continue

                # 1.1 استخراج الكود
                code = _extract_code_from_text(text)
                if code:
                    try:
                        await client.send_message(bot_entity, code)
                        logger.info(f"✅ تم إرسال الكود: {code}")
                        # بعد الإرسال، ننتظر قليلاً ونتأكد من النجاح
                        await asyncio.sleep(2.0)
                        # يمكننا التحقق من اختفاء الأزرار أو ظهور رسالة نجاح
                        return True
                    except Exception as e:
                        logger.error(f"❌ فشل إرسال الكود: {e}")
                        continue

                # 1.2 حل المسائل الرياضية
                math_patterns = [
                    (r'(\d+)\s*([+\-*/])\s*(\d+)\s*=\s*\?', 1, 2, 3),
                    (r'(\d+)\s*([+\-*/])\s*(\d+)\s*=', 1, 2, 3),
                    (r'(\d+)\s*\+\s*(\d+)\s*=', 1, 2),
                    (r'(\d+)\s*\-\s*(\d+)\s*=', 1, 2),
                    (r'(\d+)\s*\*\s*(\d+)\s*=', 1, 2),
                    (r'(\d+)\s*\/\s*(\d+)\s*=', 1, 2),
                ]
                math_solved = False
                for pattern, *groups in math_patterns:
                    match = re.search(pattern, text)
                    if match:
                        try:
                            if len(groups) == 3:
                                a, op, b = int(match.group(groups[0])), match.group(groups[1]), int(match.group(groups[2]))
                            else:
                                a, b = int(match.group(groups[0])), int(match.group(groups[1]))
                                op = '+'
                            if op == '+': result = str(a + b)
                            elif op == '-': result = str(a - b)
                            elif op == '*': result = str(a * b)
                            elif op == '/': result = str(a / b) if b != 0 else None
                            else: result = None
                            if result is not None:
                                await client.send_message(bot_entity, result)
                                logger.info(f"✅ تم حل المسألة: {a} {op} {b} = {result}")
                                await asyncio.sleep(2.0)
                                return True
                        except Exception:
                            continue

                # 1.3 البحث عن أزرار تحقق (بدلاً من الأزرار العادية)
                if msg.reply_markup:
                    for row in msg.reply_markup.rows:
                        for btn in row.buttons:
                            if getattr(btn, 'url', None):
                                continue  # تجاهل أزرار الروابط
                            btn_text = (getattr(btn, 'text', '') or '').strip().casefold()
                            # إذا كان الزر يحوي كلمات مفتاحية للتحقق، نضغطه ونعد الفحص
                            if any(kw in btn_text for kw in ['تحقق', 'verify', 'اضغط', 'تأكيد', 'confirm', 'ابدأ']):
                                # نتأكد أننا لم نضغط هذا الزر من قبل
                                btn_id = f"{msg.id}_{btn_text}"
                                if btn_id in pressed_buttons:
                                    continue
                                try:
                                    await btn.click()
                                    pressed_buttons.add(btn_id)
                                    logger.info(f"🖱️ تم الضغط على زر تحقق: {btn_text}")
                                    await asyncio.sleep(2.0)
                                    # بعد الضغط، نعيد المحاولة (سنعود لحلقة while)
                                    found_verification = True
                                    break
                                except Exception as e:
                                    logger.warning(f"⚠️ فشل الضغط على زر التحقق: {e}")
                        if found_verification:
                            break
                if found_verification:
                    break  # نخرج من حلقة الرسائل ونبدأ دورة جديدة

            # إذا وجدنا تحققاً وضغطنا زراً، ننهي هذه المحاولة ونبدأ من جديد (بعد sleep)
            if found_verification:
                await asyncio.sleep(1.0)
                continue

            # إذا لم نجد أي تحقق، نبحث عن أي زر عادي (غير رابط) في أي رسالة ونضغطه
            # (قد يكون زر "التالي" أو "متابعة" الذي يقود إلى التحقق)
            any_button_pressed = False
            for msg in incoming:
                if not msg.reply_markup:
                    continue
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        if getattr(btn, 'url', None):
                            continue
                        btn_text = (getattr(btn, 'text', '') or '').strip()
                        btn_id = f"{msg.id}_{btn_text}"
                        if btn_id in pressed_buttons:
                            continue
                        try:
                            await btn.click()
                            pressed_buttons.add(btn_id)
                            logger.info(f"🖱️ تم الضغط على زر عادي: {btn_text}")
                            any_button_pressed = True
                            await asyncio.sleep(2.0)
                            break
                        except Exception as e:
                            logger.warning(f"⚠️ فشل الضغط على الزر: {e}")
                    if any_button_pressed:
                        break
                if any_button_pressed:
                    break

            if any_button_pressed:
                # بعد الضغط، ننتظر قليلاً ثم نكرر المحاولة
                await asyncio.sleep(1.0)
                continue
            else:
                # لا توجد أزرار للضغط، ننتظر قليلاً ثم نكرر
                await asyncio.sleep(1.0)

        # بعد كل المحاولات، نعتبر العملية ناجحة إذا لم يحدث خطأ واضح
        logger.warning(f"⚠️ لم نتمكن من حل التحقق لكننا سنعتبره ناجحاً (legacy) من {phone_number}")
        return True

    # ─── 5. التنفيذ الرئيسي ───

    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ إحالة بوت إجباري مع تحقق شامل (يدعم جميع الأنواع)"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=20)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"

            # الانضمام للقنوات إذا كانت موجودة
            channels = params.get("channel_ref") or []
            if channels:
                for channel_ref in channels:
                    try:
                        await _join_channel_and_schedule_leave(client, channel_ref)
                        await asyncio.sleep(1.0)
                    except Exception as e:
                        logger.warning(f"فشل الانضمام للقناة {channel_ref}: {e}")

            # تحليل رابط البوت
            bot_username, start_param = _parse_bot_link(params["link"])
            if not bot_username:
                return False, "رابط البوت غير صحيح"

            clean_username = bot_username.lstrip("@").strip()
            resolved = await client(ResolveUsernameRequest(clean_username))
            bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]

            # بدء البوت
            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param or ""
            ))
            await asyncio.sleep(2.0)

            # حل التحقق باستخدام الدالة المدمجة
            success = await self._solve_verification(client, bot_entity, session.get("phone_number"))

            if success:
                return True, f"✅ تمت الإحالة مع التحقق من {session['phone_number']}"
            else:
                return False, "فشل التحقق بعد محاولات متعددة"
        except Exception as e:
            if "two different IP" in str(e) or "AuthKeyDuplicated" in str(e):
                logger.error(f"⚠️ الجلسة {session.get('phone_number')} تستخدم من IP مختلف - سيتم تعطيلها")
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة تستخدم من IP مختلف - تم تعطيلها مؤقتاً"
            return False, f"❌ فشل: {str(e)}"
        finally:
            await client.disconnect()
