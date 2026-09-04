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

    # ─── 4. حل التحقق المدمج (يدعم مشاركة الرقم + المنطق القديم) ───

    @staticmethod
    def _is_invitation_link_button(button) -> bool:
        """تمييز أزرار روابط الدعوة حتى لو كانت Callback وليست URL صريحاً."""
        button_url = getattr(button, "url", None)
        if button_url:
            return True

        button_text = (getattr(button, "text", "") or "").strip().casefold()
        invitation_markers = (
            "رابط الدعوة",
            "رابط دعوة",
            "الدعوة",
            "دعوة",
            "invite",
            "invitation",
            "join link",
            "انضمام",
            "انضم",
            "رابط",
        )
        return any(marker in button_text for marker in invitation_markers)

    async def _solve_verification(
        self,
        client,
        bot_entity,
        phone_number: str,
        base_id: int = 0,
    ) -> bool:
        """
        حل التحقق بذكاء:
        1. إذا طلب البوت مشاركة رقم الهاتف (زر KeyboardButtonRequestPhone) – نرسل الرقم ونضغط متابعة.
        2. وإلا نستخدم المنطق القديم: استخراج الكود، حل المسائل، الضغط على الأزرار العادية.
        """
        MAX_WAIT = 12
        CHECK_INTERVAL = 1.0

        # base_id هو آخر معرف رسالة قبل ضغط رابط الإحالة. كل الرسائل القديمة
        # قبله خارج عملية التحقق ويجب ألا تؤثر على اختيار المرحلة الحالية.
        if not base_id:
            try:
                latest_messages = await client.get_messages(bot_entity, limit=1)
                base_id = latest_messages[0].id if latest_messages else 0
            except Exception:
                base_id = 0

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
                if base_id and msg.id <= base_id:
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
                    if base_id and msg.id <= base_id:
                        continue
                    buttons = []
                    if msg.reply_markup:
                        for row in msg.reply_markup.rows:
                            for btn in row.buttons:
                                # لا نضغط زر رابط الدعوة، سواء كان URL أو Callback.
                                if not self._is_invitation_link_button(btn):
                                    buttons.append(btn)
                    # نفضل الأزرار التي تحوي كلمات مفتاحية
                    for btn in buttons:
                        btn_text = (getattr(btn, 'text', '') or '').strip().casefold()
                        if any(kw in btn_text for kw in ['متابعة', 'التالي', 'ابدأ', 'تحقق', 'continue', 'next', 'start', 'verify']):
                            proceed_button = btn
                            break
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
                    return False
            else:
                logger.warning(f"⚠️ لم يظهر زر المتابعة بعد مشاركة الرقم من {phone_number}")
                return False

            try:
                # بعد الضغط على الزر الأول ننتظر ثم نعيد قراءة كامل محادثة
                # التحقق منذ لحظة ضغط رابط الإحالة حتى آخر رسالة.
                await asyncio.sleep(2.0)
                followup_messages = []
                async for msg in client.iter_messages(
                    bot_entity,
                    min_id=base_id,
                    reverse=True,
                ):
                    followup_messages.append(msg)
                logger.info(
                    f"🔄 إعادة قراءة رسائل التحقق بعد زر المتابعة: "
                    f"{len(followup_messages)} رسالة منذ ضغط الرابط من {phone_number}"
                )
                return await self._solve_legacy_verification(
                    client,
                    bot_entity,
                    phone_number,
                    base_id=base_id,
                    initial_messages=followup_messages,
                )
            except Exception as e:
                logger.warning(f"⚠️ تعذر قراءة المرحلة الثانية للتحقق: {e}")
                return False

        # ─── المرحلة 2: لم يطلب الرقم → استخدم المنطق القديم ───
        logger.info(f"🔍 لم يطلب البوت رقم هاتف، ننتقل إلى المنطق القديم لـ {phone_number}")

        # المنطق القديم (مستند على _solve_forced_ref_verification من common.py)
        # ولكن سنعيد تنفيذه هنا لتكامل الملف
        return await self._solve_legacy_verification(client, bot_entity, phone_number)

    async def _solve_legacy_verification(
        self,
        client,
        bot_entity,
        phone_number: str,
        base_id: int = 0,
        initial_messages: Optional[List] = None,
    ) -> bool:
        """
        المنطق القديم: استخراج الكود، حل المسائل، الضغط على الأزرار
        (نسخة محسنة من _solve_forced_ref_verification في common.py)
        """
        max_attempts = 30
        processed_ids = set()

        if not base_id:
            try:
                out_messages = await client.get_messages(bot_entity, limit=10)
                for msg in out_messages:
                    if msg.out:
                        base_id = msg.id
                        logger.info(f"🔑 نقطة البداية هي رسالة الحساب رقم: {base_id}")
                        break
            except Exception as e:
                logger.warning(f"تعذر تحديد الرسالة المرجعية: {e}")

        cursor_id = base_id

        async def _read_flow_messages():
            """إعادة قراءة كل رسائل المحادثة منذ بداية عملية التحقق."""
            try:
                collected = []
                async for msg in client.iter_messages(
                    bot_entity,
                    min_id=base_id,
                    reverse=True,
                ):
                    collected.append(msg)
                return collected
            except Exception:
                return await client.get_messages(bot_entity, limit=100)

        for attempt in range(max_attempts):
            try:
                if initial_messages is not None:
                    messages = initial_messages
                    initial_messages = None
                else:
                    messages = await _read_flow_messages()
            except Exception as exc:
                if "two different IP" in str(exc) or "AuthKeyDuplicated" in str(exc):
                    logger.error(f"⚠️ الجلسة {phone_number} تستخدم من IP مختلف - سيتم تعطيلها")
                    _mark_raksh_session_unauthorized(phone_number)
                    return False
                await asyncio.sleep(1.0)
                continue

            incoming_messages = [msg for msg in messages if not msg.out]
            incoming_messages.sort(key=lambda m: m.id)

            new_messages = [
                msg for msg in incoming_messages
                if msg.id > base_id and msg.id not in processed_ids
            ]
            if not new_messages:
                await asyncio.sleep(1.0)
                continue

            # النجاح لا يعتمد على اختفاء الأزرار أو مجرد إرسال إجابة.
            for msg in reversed(new_messages):
                success_text = (getattr(msg, "message", "") or "").strip().casefold()
                if (
                    any(marker in success_text for marker in (
                        "تم التحقق بنجاح",
                        "تم التحقق",
                        "نجح التحقق",
                        "verification successful",
                        "verification complete",
                        "تم قبولك",
                        "تم التسجيل بنجاح",
                        "مرحباً بك في المجموعة",
                        "welcome to the group",
                    ))
                    and not any(marker in success_text for marker in (
                        "أرسل النص",
                        "ارسل النص",
                        "النص التالي",
                        "أرسل الكود",
                        "ارسل الكود",
                        "send the text",
                        "resend",
                        "أعد إرسال",
                    ))
                ):
                    logger.info(f"✅ تم تأكيد التحقق من {phone_number}: {success_text[:120]}")
                    return True

            # بعد كل إجابة أو زر، نعالج فقط الرسائل التي ظهرت بعدها.
            # مع إبقاء القراءة كاملة من بداية العملية حتى لا نفقد رسالة
            # تحقق ظهرت بين مرحلتين.
            candidate_messages = [
                msg for msg in new_messages
                if msg.id > cursor_id
            ]
            if not candidate_messages:
                candidate_messages = new_messages

            verification_message = None
            for msg in candidate_messages:
                msg_text = getattr(msg, 'message', '') or ''
                if msg_text.strip().startswith("/"):
                    continue
                if any(kw in msg_text for kw in ["أرسل", "التالي", "بالضبط", "اكتب", "retype", "type", "اضغط", "اختر", "انقر"]):
                    verification_message = msg
                    break

            if verification_message is None:
                verification_message = next(
                    (msg for msg in reversed(candidate_messages) if not getattr(msg, 'message', '').strip().startswith("/")),
                    None
                )

            if verification_message is None:
                await asyncio.sleep(1.0)
                continue

            text = getattr(verification_message, 'message', '') or ''

            # 1. استخراج الكود
            send_text = _extract_code_from_text(text)
            if send_text:
                try:
                    await client.send_message(bot_entity, send_text)
                    logger.info(f"✅ تم إرسال الكود: {send_text}")
                    processed_ids.add(verification_message.id)
                    cursor_id = verification_message.id
                    await asyncio.sleep(2.0)
                    continue
                except Exception:
                    return False

            # 2. حل المسائل الرياضية
            math_patterns = [
                (r'(\d+)\s*([+\-*/])\s*(\d+)\s*=\s*\?', 1, 2, 3),
                (r'(\d+)\s*([+\-*/])\s*(\d+)\s*=', 1, 2, 3),
                (r'(\d+)\s*\+\s*(\d+)\s*=', 1, 2),
                (r'(\d+)\s*\-\s*(\d+)\s*=', 1, 2),
                (r'(\d+)\s*\*\s*(\d+)\s*=', 1, 2),
                (r'(\d+)\s*\/\s*(\d+)\s*=', 1, 2),
            ]
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
                            processed_ids.add(verification_message.id)
                            cursor_id = verification_message.id
                            await asyncio.sleep(2.0)
                            break
                    except Exception:
                        continue

            # 3. الضغط على الأزرار
            buttons = []
            for row in getattr(verification_message, 'buttons', None) or []:
                for btn in row:
                    # لا نضغط زر رابط الدعوة حتى لو كان Callback بلا URL.
                    if not self._is_invitation_link_button(btn):
                        buttons.append(btn)

            button_clicked = False
            if buttons:
                # استخراج الإيموجي المطلوب
                emoji_pattern = re.compile(
                    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E0-\U0001F1FF]"
                )
                target_emoji = None
                found_emojis = emoji_pattern.findall(text)
                if found_emojis:
                    target_emoji = found_emojis[-1]

                # ترتيب الأزرار حسب الأولوية
                prioritized = []
                if target_emoji:
                    exact = [b for b in buttons if getattr(b, 'text', '') == target_emoji]
                    prioritized.extend(exact)
                    partial = [b for b in buttons if target_emoji in (getattr(b, 'text', '') or '') and b not in exact]
                    prioritized.extend(partial)

                verify_keywords = ['تحقق', 'verify', 'اضغط هنا', 'continue', 'التالي', 'متابعة']
                verify_buttons = [
                    b for b in buttons
                    if any(kw in (getattr(b, 'text', '') or '').casefold() for kw in verify_keywords)
                    and b not in prioritized
                ]
                prioritized.extend(verify_buttons)

                for btn in prioritized:
                    try:
                        await btn.click()
                        logger.info(f"🖱️ تم الضغط على الزر: {getattr(btn, 'text', '')}")
                        processed_ids.add(verification_message.id)
                        cursor_id = verification_message.id
                        await asyncio.sleep(2.0)
                        # لا نعلن النجاح هنا؛ نعيد قراءة الرسائل لمعالجة
                        # التحقق التالي الذي قد يظهر بعد هذا الزر.
                        button_clicked = True
                        break
                    except Exception:
                        continue

            if button_clicked:
                # انتهى انتظار الزر (ثانيتان)؛ تبدأ الدورة التالية
                # بإعادة القراءة مباشرة دون تأخير إضافي.
                continue

            await asyncio.sleep(2.0)

        logger.warning(f"⚠️ لم تصل رسالة نجاح صريحة بعد التحقق من {phone_number}")
        return False

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

            # حفظ نقطة البداية قبل ضغط رابط الإحالة. سيعيد محلّل التحقق قراءة
            # كل الرسائل التي تظهر بعد هذه النقطة، لا آخر رسالة فقط.
            verification_base_id = 0
            try:
                latest_messages = await client.get_messages(bot_entity, limit=1)
                verification_base_id = latest_messages[0].id if latest_messages else 0
            except Exception as e:
                logger.warning(f"تعذر تحديد نقطة بداية رابط الإحالة: {e}")

            # بدء البوت
            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param or ""
            ))
            await asyncio.sleep(2.0)

            # حل التحقق باستخدام الدالة المدمجة
            success = await self._solve_verification(
                client,
                bot_entity,
                session.get("phone_number"),
                base_id=verification_base_id,
            )

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
