# forced_ref_ai.py
from .common import *
from telethon.tl.types import (
    InputMediaContact,
    KeyboardButtonRequestPhone,
    KeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButtonRow,
)

class ForcedRefAIService(RakshService):
    """خدمة إحالة بوت إجباري مع تحقق - كل شيء في مكان واحد"""

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

    # 1️⃣ البدء بطلب القنوات الإجبارية
    def get_initial_state(self) -> str:
        return "channel"

    # 2️⃣ رسالة البداية
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

    # 3️⃣ أزرار البداية (تخطي / إلغاء)
    def get_start_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ تخطي (بدون قنوات)", callback_data="raksh_forced_ref_ai:skip_channels")],
            [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
        ])

    # 4️⃣ تعليمات الرابط
    def get_link_instruction(self) -> str:
        return "@BotUsername start123  أو  t.me/BotUsername?start=123"

    # 5️⃣ التحقق من الرابط
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

    # 6️⃣ معالجة النص (القنوات ← الرابط ← العدد ← الدفع)
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

    # 7️⃣ معالجة الأزرار
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

    # ═══ دالة حل التحقق المحسّنة (مع مشاركة جهة الاتصال) ═══
    async def _solve_verification(self, client, bot_entity, phone_number: str) -> bool:
        """حل التحقق بذكاء - إرسال جهة الاتصال عند الطلب + إعادة محاولة الضغط على الأزرار"""
        max_attempts = 50
        base_id = 0

        try:
            out_messages = await client.get_messages(bot_entity, limit=10)
            for msg in out_messages:
                if msg.out:
                    base_id = msg.id
                    logger.info(f"🔑 نقطة البداية هي رسالة الحساب رقم: {base_id}")
                    break
        except Exception as e:
            logger.warning(f"تعذر تحديد الرسالة المرجعية: {e}")

        # ✅ دالة إرسال جهة الاتصال (تعمل في جميع الحالات)
        async def send_contact_manually():
            try:
                me = await client.get_me()
                if not me or not me.phone:
                    return False
                phone = me.phone if me.phone.startswith('+') else f'+{me.phone}'
                # إرسال جهة الاتصال مباشرة عبر send_file
                await client.send_file(
                    bot_entity,
                    file=InputMediaContact(
                        phone_number=phone,
                        first_name=me.first_name or "User",
                        last_name=me.last_name or "",
                        vcard="",
                    )
                )
                logger.info(f"📱 تم إرسال جهة الاتصال يدوياً من {phone_number}")
                return True
            except Exception as e:
                logger.warning(f"فشل إرسال جهة الاتصال يدوياً: {e}")
                return False

        for attempt in range(max_attempts):
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

            new_messages = [msg for msg in incoming_messages if msg.id > base_id]
            if not new_messages:
                await asyncio.sleep(1.0)
                continue

            verification_message = None
            for msg in new_messages:
                msg_text = getattr(msg, 'message', '') or ''
                if msg_text.strip().startswith("/"):
                    continue
                if any(kw in msg_text for kw in ["أرسل", "التالي", "بالضبط", "اكتب", "retype", "type", "اضغط", "اختر", "انقر", "مشاركة", "share", "contact"]):
                    verification_message = msg
                    break

            if verification_message is None:
                verification_message = next(
                    (msg for msg in reversed(new_messages) if not getattr(msg, 'message', '').strip().startswith("/")),
                    None
                )

            if verification_message is None:
                await asyncio.sleep(1.0)
                continue

            text = getattr(verification_message, 'message', '') or ''

            # جمع كل الأزرار (المضمّنة + لوحة المفاتيح العادية)
            all_buttons = []
            for row in (getattr(verification_message, 'buttons', None) or []):
                for btn in row:
                    if not getattr(btn, 'url', None):
                        all_buttons.append(btn)

            reply_markup = getattr(verification_message, 'reply_markup', None)
            if reply_markup and hasattr(reply_markup, 'rows'):
                for row in reply_markup.rows:
                    for btn in row.buttons:
                        if not getattr(btn, 'url', None):
                            all_buttons.append(btn)

            # ═══ 1️⃣ إرسال جهة الاتصال إذا طلبها البوت ═══
            contact_requested = False
            if any(kw in text.lower() for kw in ["مشاركة جهة اتصال", "share contact", "phone number", "رقم هاتف"]):
                contact_requested = True

            # ✅ البحث عن زر مشاركة جهة الاتصال
            phone_btn = None
            for btn in all_buttons:
                if isinstance(btn, KeyboardButtonRequestPhone):
                    phone_btn = btn
                    break

            if contact_requested or phone_btn is not None:
                # ✅ إرسال جهة الاتصال يدوياً (الطريقة الأضمن)
                if await send_contact_manually():
                    await asyncio.sleep(2.0)
                    # تحقق من اختفاء الرسالة
                    try:
                        updated = await client.get_messages(bot_entity, ids=verification_message.id)
                        if isinstance(updated, (list, tuple)):
                            updated = updated[0] if updated else None
                        if updated is None or not getattr(updated, 'buttons', None) and not getattr(updated, 'reply_markup', None):
                            logger.info(f"✅ اختفت الرسالة بعد مشاركة جهة الاتصال من {phone_number}")
                            return True
                    except Exception:
                        pass
                    # ✅ بعد الإرسال، نضغط على زر متابعة إذا كان موجوداً
                    continue_btn = None
                    for btn in all_buttons:
                        btn_text = (getattr(btn, 'text', '') or '').lower()
                        if any(kw in btn_text for kw in ["متابعة", "التالي", "تحقق", "continue", "next", "verify", "تم", "done"]):
                            continue_btn = btn
                            break
                    if continue_btn:
                        try:
                            await continue_btn.click()
                            logger.info(f"✅ تم الضغط على زر 'متابعة' من {phone_number}")
                        except Exception:
                            pass
                    continue

            # ═══ 2️⃣ استخراج الكود ═══
            send_text = _extract_code_from_text(text)
            if send_text:
                try:
                    await client.send_message(bot_entity, send_text)
                    logger.info(f"✅ تم إرسال الكود: {send_text}")
                    return True
                except Exception:
                    return False

            # ═══ 3️⃣ حل المسائل الرياضية ═══
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
                            return True
                    except Exception:
                        continue

            # ═══ 4️⃣ الضغط على الأزرار العادية ═══
            if all_buttons:
                # استخراج الإيموجي المطلوب
                emoji_pattern = re.compile(
                    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E0-\U0001F1FF]"
                )
                target_emoji = None
                found_emojis = emoji_pattern.findall(text)
                if found_emojis:
                    target_emoji = found_emojis[-1]

                prioritized = []
                if target_emoji:
                    exact = [b for b in all_buttons if getattr(b, 'text', '') == target_emoji]
                    prioritized.extend(exact)
                    partial = [b for b in all_buttons if target_emoji in (getattr(b, 'text', '') or '') and b not in exact]
                    prioritized.extend(partial)

                verify_keywords = ['تحقق', 'verify', 'اضغط هنا', 'continue', 'التالي', 'متابعة']
                verify_buttons = [b for b in all_buttons if any(kw in (getattr(b, 'text', '') or '').lower() for kw in verify_keywords) and b not in prioritized]
                prioritized.extend(verify_buttons)

                remaining = [b for b in all_buttons if b not in prioritized]
                prioritized.extend(remaining)

                seen = set()
                unique_buttons = []
                for b in prioritized:
                    if id(b) not in seen:
                        seen.add(id(b))
                        unique_buttons.append(b)

                pressed_ids = set()
                for _ in range(30):
                    try:
                        current_msg = await client.get_messages(bot_entity, ids=verification_message.id)
                        if isinstance(current_msg, (list, tuple)):
                            current_msg = current_msg[0] if current_msg else None
                    except Exception as exc:
                        if "two different IP" in str(exc):
                            logger.error(f"⚠️ الجلسة {phone_number} تستخدم من IP مختلف - سيتم تعطيلها")
                            _mark_raksh_session_unauthorized(phone_number)
                            return False
                        current_msg = None

                    if current_msg is None or (not getattr(current_msg, 'buttons', None) and not getattr(current_msg, 'reply_markup', None)):
                        logger.info(f"✅ اختفت الأزرار - تم التحقق بنجاح من {phone_number}")
                        return True

                    button_to_click = None
                    for b in unique_buttons:
                        if id(b) not in pressed_ids:
                            for row in (getattr(current_msg, 'buttons', None) or []):
                                for btn in row:
                                    if not getattr(btn, 'url', None) and getattr(btn, 'text', '') == getattr(b, 'text', ''):
                                        button_to_click = btn
                                        break
                                if button_to_click:
                                    break
                            if button_to_click:
                                break
                            reply_markup = getattr(current_msg, 'reply_markup', None)
                            if reply_markup and hasattr(reply_markup, 'rows'):
                                for row in reply_markup.rows:
                                    for btn in row.buttons:
                                        if not getattr(btn, 'url', None) and getattr(btn, 'text', '') == getattr(b, 'text', ''):
                                            button_to_click = btn
                                            break
                                    if button_to_click:
                                        break
                            if button_to_click:
                                break

                    if button_to_click is None:
                        pressed_ids.clear()
                        continue

                    try:
                        await button_to_click.click()
                        pressed_ids.add(id(button_to_click))
                        logger.info(f"🖱️ ضغط على زر '{getattr(button_to_click, 'text', '')}' من {phone_number}")
                        await asyncio.sleep(2.0)
                    except Exception as exc:
                        if "two different IP" in str(exc):
                            logger.error(f"⚠️ الجلسة {phone_number} تستخدم من IP مختلف - سيتم تعطيلها")
                            _mark_raksh_session_unauthorized(phone_number)
                            return False
                        continue

                continue

            await asyncio.sleep(2.0)

        return False

    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ إحالة بوت إجباري مع تحقق شامل"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=20)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"

            channels = params.get("channel_ref") or []
            if channels:
                for channel_ref in channels:
                    try:
                        await _join_channel_and_schedule_leave(client, channel_ref)
                        await asyncio.sleep(1.0)
                    except Exception as e:
                        logger.warning(f"فشل الانضمام للقناة {channel_ref}: {e}")

            bot_username, start_param = _parse_bot_link(params["link"])
            if not bot_username:
                return False, "رابط البوت غير صحيح"

            clean_username = bot_username.lstrip("@").strip()
            resolved = await client(ResolveUsernameRequest(clean_username))
            bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]

            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param or ""
            ))
            await asyncio.sleep(2.0)

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
