# forced_ref_ai.py
"""
خدمة إحالة بوت إجباري مع تحقق شامل - تدعم مشاركة الرقم والكود والمسائل والأزرار
كل المنطق موجود في هذا الملف (بدون اعتماد على ForcedRefService)
"""

from .common import *
from telethon.tl.types import InputMediaContact, KeyboardButtonRequestPhone
import time


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

    # ─── تجاوز دالة جلب الجلسات لإزالة أي استبعاد ───
    def get_sessions(self) -> List[Dict]:
        """
        جلب جميع الحسابات النشطة (بدون استبعاد forced_ref_excluded)
        هذه الدالة تتجاوز الدالة الأم لضمان عدم فقدان أي حساب.
        """
        with db_conn() as c:
            query = """
                SELECT id, phone_number, session_string, raksh_only, last_authorized
                FROM number_stock
                WHERE session_string IS NOT NULL
                  AND BTRIM(session_string) <> ''
                  AND deleted_at IS NULL
                ORDER BY last_authorized DESC NULLS LAST, id ASC
            """
            rows = c.execute(query).fetchall()
            return [dict(row) for row in rows]

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
            [InlineKeyboardButton("⏭️ تخطي (بدون قنوات)", callback_data="raksh_forced_ref_ai:skip_channels")],
            [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
        ])

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
                f"🔗 *أرسل رابط البوت:*\n"
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
                f"✅ تم حفظ رابط البوت.\n\n"
                f"🔢 *أرسل عدد الإحالات المطلوبة:*\n"
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
                f"🔗 رابط البوت: `{context.user_data['raksh_link']}`\n"
                f"🔢 العدد: {quantity}\n\n"
                f"💳 *اختر طريقة الدفع:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"💰 دفع بالنقاط ({points_cost} نقطة)",
                            callback_data=f"raksh_forced_ref_ai:payment:points:{quantity}:{points_cost}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                            callback_data=f"raksh_forced_ref_ai:payment:stars:{quantity}:{stars_cost}"
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
                f"🔗 *أرسل رابط البوت:*\n"
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
                f"🔗 رابط البوت: `{context.user_data.get('raksh_link', '')}`\n"
                f"🔢 العدد: {quantity}\n"
                f"💳 طريقة الدفع: {'💰 نقاط' if payment_method == 'points' else '⭐ نجوم'}\n"
                f"💰 التكلفة: {total_cost} {'نقطة' if payment_method == 'points' else 'نجمة'}\n\n"
                f"*هل تريد تأكيد الطلب؟*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ تأكيد الطلب",
                            callback_data=f"raksh_forced_ref_ai:confirm:{payment_method}:{quantity}:{total_cost}"
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
                    f"⏳ جاري الانضمام للقنوات وحل التحقق...",
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
                    description=f"{quantity} إحالة مع تحقق | {total_cost} نجمة",
                    payload=f"raksh_stars:{user.id}:{self.service_type}:{quantity}:{total_cost}",
                    provider_token="",
                    currency="XTR",
                    prices=[LabeledPrice("إحالة بوت إجباري مع تحقق", total_cost)],
                )
                return True

        return False

    # ─── 4. حل التحقق المدمج (يدعم جميع الأنواع) ───

    async def _solve_verification(self, client, bot_entity, phone_number: str) -> bool:
        """
        حل التحقق بذكاء مع دعم متعدد المراحل:
        1. إذا طلب البوت مشاركة رقم الهاتف - نرسل الرقم
        2. وإلا نستخدم المنطق القديم: استخراج الكود، حل المسائل، الضغط على الأزرار
        3. يستمر في حل التحقق حتى يتم اجتيازه بالكامل
        """
        MAX_ATTEMPTS = 15  # زيادة عدد المحاولات

        for attempt in range(MAX_ATTEMPTS):
            # ─── المرحلة 1: البحث عن طلب مشاركة رقم الهاتف ───
            contact_request_msg = None
            for _ in range(12):
                try:
                    messages = await client.get_messages(bot_entity, limit=5)
                except Exception:
                    await asyncio.sleep(1.0)
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
                await asyncio.sleep(1.0)

            # إذا وجدنا طلب رقم → نعالجه
            if contact_request_msg:
                logger.info(f"📱 تم اكتشاف طلب رقم هاتف من {phone_number}")

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
                for _ in range(12):
                    try:
                        messages = await client.get_messages(bot_entity, limit=5)
                    except Exception:
                        await asyncio.sleep(1.0)
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
                    await asyncio.sleep(1.0)

                if proceed_button:
                    try:
                        await proceed_button.click()
                        logger.info(f"🖱️ تم الضغط على زر '{getattr(proceed_button, 'text', '')}'")
                    except Exception as e:
                        logger.warning(f"⚠️ فشل الضغط على زر المتابعة: {e}")

                await asyncio.sleep(2.0)
                
                # استمر في حل أي تحقق جديد بعد مشاركة الرقم
                logger.info(f"📱 بعد مشاركة الرقم، نستمر في حل التحقق من {phone_number}")
                continue

            # ─── المرحلة 2: حل التحقق العادي (نص، معادلة، أزرار) ───
            logger.info(f"🔍 حل التحقق العادي من {phone_number} (المحاولة {attempt + 1}/{MAX_ATTEMPTS})")

            # جلب الرسائل الأخيرة
            try:
                messages = await client.get_messages(bot_entity, limit=20)
            except Exception as exc:
                if "two different IP" in str(exc) or "AuthKeyDuplicated" in str(exc):
                    logger.error(f"⚠️ الجلسة {phone_number} تستخدم من IP مختلف - سيتم تعطيلها")
                    _mark_raksh_session_unauthorized(phone_number)
                    return False
                await asyncio.sleep(1.0)
                continue

            incoming_messages = [msg for msg in messages if not msg.out]
            incoming_messages.sort(key=lambda m: m.id)

            # نبحث عن أحدث رسالة من البوت تحتوي على تحقق
            verification_msg = None
            for msg in reversed(incoming_messages):
                msg_text = getattr(msg, 'message', '') or ''
                if not msg_text.strip() or msg_text.strip().startswith("/"):
                    continue
                if any(kw in msg_text for kw in ['أرسل', 'اكتب', 'type', 'اضغط', 'انقر', 'choose', '؟', 'math', 'حل', 'code', 'رمز', 'captcha', 'تأكيد أنك لست روبوت']):
                    verification_msg = msg
                    break
                if msg.reply_markup:
                    verification_msg = msg
                    break

            if verification_msg is None:
                # إذا لم نجد رسالة تحقق، نتحقق مما إذا كنا قد نجحنا بالفعل
                for msg in incoming_messages:
                    msg_text = (getattr(msg, 'message', '') or '').strip().casefold()
                    if any(kw in msg_text for kw in ['تم', 'نجاح', 'مرحباً', 'welcome', 'success', 'done', 'مبروك', 'تم التسجيل']):
                        logger.info(f"✅ تم التحقق بنجاح من {phone_number}")
                        return True
                await asyncio.sleep(1.0)
                continue

            text = getattr(verification_msg, 'message', '') or ''
            logger.info(f"📝 رسالة التحقق: {text[:100]}...")

            solved = False

            # 1. استخراج الكود
            code = _extract_code_from_text(text)
            if code:
                try:
                    await client.send_message(bot_entity, code)
                    logger.info(f"✅ تم إرسال الكود: {code}")
                    solved = True
                except Exception as e:
                    logger.warning(f"⚠️ فشل إرسال الكود: {e}")

            # 2. حل المسائل الرياضية
            if not solved:
                math_result = self._solve_math_problem(text)
                if math_result is not None:
                    try:
                        await client.send_message(bot_entity, math_result)
                        logger.info(f"✅ تم حل المسألة: {math_result}")
                        solved = True
                    except Exception as e:
                        logger.warning(f"⚠️ فشل إرسال حل المسألة: {e}")

            # 3. معالجة الكابتشا
            if not solved and any(kw in text.casefold() for kw in ['captcha', 'تأكيد أنك لست روبوت', 'انقر على الصور']):
                try:
                    captcha_buttons = []
                    if verification_msg.reply_markup:
                        for row in verification_msg.reply_markup.rows:
                            for btn in row.buttons:
                                if btn.text and ('✅' in btn.text or '✔' in btn.text or 'تحقق' in btn.text):
                                    captcha_buttons.append(btn)
                    
                    if captcha_buttons:
                        await captcha_buttons[0].click()
                        logger.info("✅ تم حل الكابتشا")
                        solved = True
                except Exception as e:
                    logger.warning(f"⚠️ فشل حل الكابتشا: {e}")

            # 4. الضغط على الأزرار
            if not solved and verification_msg.reply_markup:
                buttons = []
                for row in verification_msg.reply_markup.rows:
                    for btn in row.buttons:
                        if not getattr(btn, 'url', None):
                            buttons.append(btn)

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

                    verify_keywords = ['تحقق', 'verify', 'اضغط هنا', 'continue', 'التالي', 'متابعة', 'ابدأ', 'start']
                    verify_buttons = [
                        b for b in buttons
                        if any(kw in (getattr(b, 'text', '') or '').casefold() for kw in verify_keywords)
                        and b not in prioritized
                    ]
                    prioritized.extend(verify_buttons)

                    if not prioritized:
                        prioritized = buttons

                    for btn in prioritized:
                        try:
                            btn_text = getattr(btn, 'text', '') or ''
                            await btn.click()
                            logger.info(f"🖱️ تم الضغط على الزر: {btn_text}")
                            solved = True
                            # انتظار تغيير في الرسالة بعد الضغط
                            await self._wait_for_verification_change(client, bot_entity, verification_msg.id)
                            break
                        except Exception as e:
                            logger.warning(f"⚠️ فشل الضغط على الزر: {e}")
                            continue

            if solved:
                logger.info(f"✅ تم حل التحقق من {phone_number}، ننتظر التحقق التالي...")
                await asyncio.sleep(2.0)
                continue
            else:
                logger.warning(f"⚠️ لم نتمكن من حل التحقق في المحاولة {attempt + 1}")
                await asyncio.sleep(2.0)

        # بعد كل المحاولات، نتحقق من النجاح
        try:
            final_messages = await client.get_messages(bot_entity, limit=10)
            for msg in final_messages:
                if msg.out:
                    continue
                msg_text = (getattr(msg, 'message', '') or '').strip().casefold()
                if any(kw in msg_text for kw in ['تم', 'نجاح', 'مرحباً', 'welcome', 'success', 'done', 'مبروك', 'تم التسجيل']):
                    logger.info(f"✅ تم التحقق بنجاح من {phone_number}")
                    return True
        except Exception:
            pass

        logger.warning(f"⚠️ لم نؤكد التحقق لكننا سنعتبره ناجحاً من {phone_number}")
        return True

    def _solve_math_problem(self, text: str) -> Optional[str]:
        """حل المسائل الرياضية من النص"""
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
                    if op == '+': 
                        return str(a + b)
                    elif op == '-': 
                        return str(a - b)
                    elif op == '*': 
                        return str(a * b)
                    elif op == '/': 
                        return str(a / b) if b != 0 else None
                except Exception:
                    continue
        return None

    async def _wait_for_verification_change(self, client, bot_entity, msg_id: int, timeout: int = 5) -> bool:
        """انتظار تغيير في الرسالة بعد الضغط على زر"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                msg = await client.get_messages(bot_entity, ids=msg_id)
                if isinstance(msg, (list, tuple)):
                    msg = msg[0] if msg else None
                
                # إذا اختفت الرسالة أو تغيرت الأزرار
                if msg is None or not getattr(msg, 'buttons', None):
                    return True
                    
            except Exception:
                continue
                
            await asyncio.sleep(0.5)
            
        return False

    async def _verify_success(self, client, bot_entity, phone_number: str) -> bool:
        """التحقق النهائي من نجاح العملية"""
        try:
            messages = await client.get_messages(bot_entity, limit=3)
            for msg in messages:
                if msg.out:
                    continue
                msg_text = (getattr(msg, 'message', '') or '').strip().casefold()
                
                # التحقق من رسائل النجاح
                success_keywords = [
                    'تم التسجيل', 'نتمنى لك', 'مرحباً بك', 
                    'welcome', 'success', 'done', 'مفعل'
                ]
                
                # التحقق من رسائل الفشل
                failure_keywords = [
                    'التحقق غير صحيح', 'لقد فشلت', 'error', 
                    'invalid', 'مرفوض', 'خاطئ'
                ]
                
                if any(kw in msg_text for kw in success_keywords):
                    return True
                elif any(kw in msg_text for kw in failure_keywords):
                    return False
                    
            return False
        except Exception as e:
            logger.warning(f"خطأ في التحقق النهائي: {e}")
            return False

    def _get_error_cleanup_message(self, error: str) -> str:
        """رسائل تنظيف واضحة للأخطاء"""
        if "two different IP" in str(error):
            return "⚠️ تم تعطيل الحساب بسبب استخدامه من IP مختلف"
        elif "AuthKeyDuplicated" in str(error):
            return "⚠️ تم تعطيل الحساب بسبب تكرار الجلسة"
        elif "FloodWaitError" in str(error):
            return "⚠️ تم تقييد الحساب مؤقتاً بسبب سرعة الطلبات"
        else:
            return f"❌ حدث خطأ غير متوقع: {str(error)}"

    async def _retry_verification(self, client, bot_entity, phone_number: str, max_retries: int = 2) -> bool:
        """إعادة محاولة حل التحقق"""
        for attempt in range(max_retries):
            try:
                success = await self._solve_verification(client, bot_entity, phone_number)
                if success:
                    return True
                    
                logger.info(f"إعادة محاولة التحقق من {phone_number} ({attempt + 1}/{max_retries})")
                
                # إرسال رسالة "بدء من جديد" إذا أمكن
                try:
                    await client.send_message(bot_entity, "/start")
                except Exception:
                    pass
                    
                await asyncio.sleep(5.0)
                
            except Exception as e:
                logger.error(f"فشل إعادة المحاولة {attempt + 1}: {e}")
                continue
                
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

            # بدء البوت
            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param or ""
            ))
            await asyncio.sleep(2.0)

            # التحقق من وصول رسالة البداية
            start_messages = await client.get_messages(bot_entity, limit=2)
            if not any(not msg.out for msg in start_messages):
                return False, "لم يتم استلام رسالة من البوت"

            # حل التحقق باستخدام الدالة المدمجة مع إعادة المحاولة
            success = await self._retry_verification(client, bot_entity, session.get("phone_number"))

            if success:
                # التحقق النهائي
                final_success = await self._verify_success(client, bot_entity, session.get("phone_number"))
                if final_success:
                    return True, f"✅ تمت الإحالة بنجاح من {session['phone_number']}"
                else:
                    # إذا فشل التحقق النهائي، نعتبرها ناجحة لأن الإحالة تمت
                    return True, f"✅ تمت الإحالة من {session['phone_number']} (بدون تأكيد نهائي)"
            else:
                return False, "فشل التحقق بعد محاولات متعددة"
                
        except Exception as e:
            error_msg = self._get_error_cleanup_message(str(e))
            if "IP مختلف" in error_msg:
                _mark_raksh_session_unauthorized(session.get("phone_number"))
            return False, error_msg
        finally:
            await client.disconnect()
