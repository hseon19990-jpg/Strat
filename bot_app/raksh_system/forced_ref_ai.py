# forced_ref_ai.py
from .common import *

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

    # ─── بداية الطلب: القنوات الإجبارية ───
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

    # ─── معالجة النص ───
    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        # 1) استقبال القنوات
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

        # 2) استقبال رابط البوت
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
                await update.message.reply_text("⚠️ لا توجد حسابات متاحة حالياً.")
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

        # 3) استقبال العدد
        if state == "quantity":
            try:
                quantity = int(text)
            except ValueError:
                await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
                return True

            max_qty = self.get_request_limit(user.id)
            if max_qty < 1:
                await update.message.reply_text("⚠️ لا توجد حسابات متاحة حالياً.")
                return True

            if quantity < 1 or quantity > max_qty:
                await update.message.reply_text(f"⚠️ العدد المسموح بين 1 و {max_qty}.")
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
                    [InlineKeyboardButton(
                        f"💰 دفع بالنقاط ({points_cost} نقطة)",
                        callback_data=f"raksh_forced_ref_ai:payment:points:{quantity}:{points_cost}"
                    )],
                    [InlineKeyboardButton(
                        f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                        callback_data=f"raksh_forced_ref_ai:payment:stars:{quantity}:{stars_cost}"
                    )],
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        # 4) حالة التأكيد (لن تصل هنا عادةً لأن الأزرار تظهر)
        if state == "confirm":
            await update.message.reply_text("⚠️ استخدم الأزرار للتأكيد.")
            return True

        return False

    # ─── معالجة الأزرار ───
    async def handle_callback(self, update, context, query, data_parts, user, is_own) -> bool:
        # تخطي القنوات
        if data_parts[0] == "skip_channels":
            context.user_data["raksh_channels"] = []
            context.user_data["raksh_step"] = "link"
            await query.edit_message_text(
                f"✅ تم تخطي القنوات.\n\n🔗 *أرسل رابط البوت:*\n{self.get_link_instruction()}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        # اختيار طريقة الدفع
        if data_parts[0] == "payment" and len(data_parts) >= 4:
            payment_method = data_parts[1]
            try:
                quantity = int(data_parts[2])
                button_total = int(data_parts[3])
            except ValueError:
                await query.answer("⚠️ العدد أو السعر غير صالح.", show_alert=True)
                return True

            if payment_method not in {"points", "stars"}:
                await query.answer("⚠️ طريقة الدفع غير صالحة.", show_alert=True)
                return True

            if quantity > self.get_request_limit(user.id):
                await query.edit_message_text("⚠️ لا يمكن قبول هذا الطلب حالياً.")
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
                    [InlineKeyboardButton(
                        "✅ تأكيد الطلب",
                        callback_data=f"raksh_forced_ref_ai:confirm:{payment_method}:{quantity}:{total_cost}"
                    )],
                    [InlineKeyboardButton("❌ إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        # التأكيد النهائي
        if data_parts[0] == "confirm" and len(data_parts) >= 4:
            payment_method = data_parts[1]
            try:
                quantity = int(data_parts[2])
                button_total = int(data_parts[3])
            except ValueError:
                await query.answer("⚠️ العدد أو السعر غير صالح.", show_alert=True)
                return True

            if payment_method not in {"points", "stars"}:
                await query.answer("⚠️ طريقة الدفع غير صالحة.", show_alert=True)
                return True

            if quantity > self.get_request_limit(user.id):
                await query.edit_message_text("⚠️ لا يمكن قبول هذا الطلب حالياً.")
                return True

            total_cost = self.get_total(quantity, payment_method)

            if payment_method == "points":
                if not deduct_points(user.id, total_cost):
                    await query.edit_message_text("❌ *نقاطك غير كافية!*")
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
                await _start_raksh_execution(
                    update, context, query, self.service_type, quantity, "points", total_cost
                )
                return True

            else:
                await query.edit_message_text("⭐ *جاري تجهيز فاتورة الدفع بالنجوم...*")
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

    # ─── دالة تحقق خاصة تدعم مشاركة جهة الاتصال ───
    async def _solve_verification_with_contact(self, client, bot_entity, phone_number: str) -> bool:
        max_attempts = 20
        base_id = 0

        try:
            out_messages = await client.get_messages(bot_entity, limit=10)
            for msg in out_messages:
                if msg.out:
                    base_id = msg.id
                    break
        except Exception:
            pass

        for attempt in range(max_attempts):
            try:
                messages = await client.get_messages(bot_entity, limit=20)
            except Exception:
                await asyncio.sleep(1.0)
                continue

            incoming = [msg for msg in messages if not msg.out and msg.id > base_id]
            if not incoming:
                await asyncio.sleep(1.0)
                continue

            verification_message = None
            for msg in incoming:
                text = getattr(msg, 'message', '') or ''
                if text.startswith("/"):
                    continue
                if any(kw in text for kw in ["أرسل", "التالي", "اكتب", "اضغط", "اختر", "شارك", "contact", "phone"]):
                    verification_message = msg
                    break
            if verification_message is None:
                verification_message = incoming[-1]

            text = getattr(verification_message, 'message', '') or ''

            # 1) استخراج كود
            code = _extract_code_from_text(text)
            if code:
                try:
                    await client.send_message(bot_entity, code)
                    return True
                except Exception:
                    continue

            # 2) حل مسألة رياضية
            math_patterns = [
                (r'(\d+)\s*([+\-*/])\s*(\d+)\s*=\s*\?', 1, 2, 3),
                (r'(\d+)\s*([+\-*/])\s*(\d+)\s*=', 1, 2, 3),
            ]
            for pattern, *groups in math_patterns:
                match = re.search(pattern, text)
                if match:
                    try:
                        a = int(match.group(groups[0]))
                        op = match.group(groups[1])
                        b = int(match.group(groups[2]))
                        if op == '+': result = str(a + b)
                        elif op == '-': result = str(a - b)
                        elif op == '*': result = str(a * b)
                        elif op == '/': result = str(a / b)
                        else: result = None
                        if result:
                            await client.send_message(bot_entity, result)
                            return True
                    except Exception:
                        continue

            # 3) الأزرار (بما فيها مشاركة جهة الاتصال)
            buttons = []
            for row in (getattr(verification_message, 'buttons', None) or []):
                for btn in row:
                    if not getattr(btn, 'url', None):
                        buttons.append(btn)

            if buttons:
                for btn in buttons:
                    # ✅ دعم زر مشاركة جهة الاتصال
                    if hasattr(btn, 'request_contact') and btn.request_contact:
                        try:
                            await btn.click()
                            return True
                        except Exception:
                            continue
                    # ✅ دعم زر مشاركة رقم الهاتف
                    if hasattr(btn, 'request_phone') and btn.request_phone:
                        try:
                            await btn.click()
                            return True
                        except Exception:
                            continue
                    # الضغط على أي زر آخر
                    try:
                        await btn.click()
                        return True
                    except Exception:
                        continue

            await asyncio.sleep(2.0)

        return False

    # ─── التنفيذ الفعلي ───
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        client = TelegramClient(
            StringSession(session["session_string"]),
            int(TELEGRAM_API_ID),
            int(TELEGRAM_API_HASH),
        )
        await asyncio.wait_for(client.connect(), timeout=20)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"

            # 1) الانضمام للقنوات الإجبارية
            channels = params.get("channel_ref") or []
            if channels:
                for channel_ref in channels:
                    try:
                        await _join_channel_and_schedule_leave(client, channel_ref)
                        await asyncio.sleep(1.0)
                    except Exception as e:
                        logger.warning(f"فشل الانضمام للقناة {channel_ref}: {e}")

            # 2) فتح البوت
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

            # 3) حل التحقق الخاص بنا (مع دعم جهة الاتصال)
            success = await self._solve_verification_with_contact(client, bot_entity, session.get("phone_number"))

            if success:
                return True, f"✅ تمت الإحالة مع التحقق من {session['phone_number']}"
            else:
                return False, "فشل التحقق بعد محاولات متعددة"

        except Exception as e:
            return False, f"❌ فشل: {str(e)}"
        finally:
            await client.disconnect()
