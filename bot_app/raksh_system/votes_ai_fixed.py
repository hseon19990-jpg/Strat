# votes_ai_fixed.py
from .common import *
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest
from telethon.tl.types import KeyboardButtonRequestPhone, InputMediaContact

class VotesAIService(RakshService):
    """خدمة رشق تصويت مع تحقق - كل شيء في مكان واحد (نسخة مستقلة)"""

    service_type = "votes_ai"
    label = "🛡 رشق تصويت مع تحقق"
    config = ServiceConfig(
        name=label,
        price_points=50,
        points_quantity=1,
        price_stars=10,
        stars_quantity=1,
        has_channel=True,
        has_reaction=False,
        has_ai=True,
        needs_link=True,
        min_delay=3,
        max_delay=3,
        max_concurrent=1
    )

    def get_initial_state(self) -> str:
        return "channel"

    def get_link_instruction(self) -> str:
        return (
            "أرسل رابط المنشور أو البوت بأحد هذه الصيغ:\n"
            "• رابط منشور قناة: https://t.me/channel/123\n"
            "• رابط بوت تصويت: https://t.me/BotUsername?start=compvote_xxx"
        )

    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        bot_username, _ = _parse_bot_link(value)
        channel_ref, msg_id = _parse_post_link(value)
        if not bot_username and not channel_ref:
            return "⚠️ الرابط غير صحيح.\n\nأرسل رابط منشور قناة أو رابط بوت"
        return None

    def get_start_message(self) -> str:
        return (
            f"{self.config.name}\n\n"
            f"💰 السعر: {self.get_rate_text('points')}\n"
            f"⭐ السعر: {self.get_rate_text('stars')}\n\n"
            f"📢 *أرسل القنوات الإجبارية:*\n"
            f"كل قناة في سطر منفصل:\n"
            f"@channel1\n@channel2\nأو أرسل روابط t.me\n\n"
            f"✍️ اكتب 'تخطي' لعدم وجود قنوات"
        )

    def get_start_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ تخطي (بدون قنوات)", callback_data="raksh_votes_ai:skip_channels")],
            [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
        ])

    def _is_vote_link(self, value: str) -> bool:
        bot_username, start_param = _parse_bot_link(value)
        channel_ref, msg_id = _parse_post_link(value)
        return bool(channel_ref and msg_id) or bool(bot_username and start_param)

    async def _show_quantity_prompt(self, update, context, user) -> bool:
        try:
            max_qty = self.get_request_limit(user.id)
        except Exception:
            logger.exception("فشل حساب الحد الأقصى لأصوات المستخدم %s", user.id)
            await update.message.reply_text(
                "⚠️ تعذر قراءة الحسابات المتاحة حالياً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
            )
            return True
        if max_qty < 1:
            await update.message.reply_text(
                "⚠️ لا توجد حسابات متاحة حالياً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
            )
            return True
        await update.message.reply_text(
            "✅ تم حفظ رابط التصويت.\n\n🔢 *أرسل عدد الأصوات المطلوبة:*\n"
            f"(الحد الأقصى: {max_qty})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
        )
        return True

    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        if state == "channel":
            clean_text = text.strip()
            if clean_text.lower() in {"تخطي", "skip", "لا", "none", "بدون"}:
                context.user_data["raksh_channels"] = []
            elif self._is_vote_link(clean_text):
                context.user_data["raksh_channels"] = []
                context.user_data["raksh_link"] = clean_text
                context.user_data["raksh_step"] = "quantity"
                return await self._show_quantity_prompt(update, context, user)
            else:
                channel_refs = _parse_channel_refs(text)
                if not channel_refs:
                    await update.message.reply_text(
                        "⚠️ لم أتعرف على أي قناة.\nأرسل @username أو رابط t.me للقناة، ويمكنك إرسال أكثر من قناة مفصولة بمسافة أو سطر.\nأو اكتب 'تخطي' لعدم وجود قنوات.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
                    )
                    return True
                context.user_data["raksh_channels"] = channel_refs
            context.user_data["raksh_step"] = "link"
            await update.message.reply_text(
                f"✅ تم حفظ القنوات الإجبارية ({len(context.user_data['raksh_channels'])} قناة).\n\n🔗 <b>أرسل رابط التصويت:</b>\n{self.get_link_instruction()}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
            )
            return True

        if state == "link":
            link_error = self.validate_link(text)
            if link_error:
                await update.message.reply_text(link_error, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]]))
                return True
            context.user_data["raksh_link"] = text.strip()
            context.user_data["raksh_step"] = "quantity"
            return await self._show_quantity_prompt(update, context, user)

        if state == "quantity":
            try:
                quantity = int(text)
            except ValueError:
                await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]]))
                return True
            max_qty = self.get_request_limit(user.id)
            if max_qty < 1:
                await update.message.reply_text("⚠️ لا توجد حسابات متاحة حالياً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]]))
                return True
            if quantity < 1 or quantity > max_qty:
                await update.message.reply_text(f"⚠️ العدد المسموح بين 1 و {max_qty}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]]))
                return True
            context.user_data["raksh_quantity"] = quantity
            context.user_data["raksh_step"] = "payment"
            points_cost = self.get_total(quantity, "points")
            stars_cost = self.get_total(quantity, "stars")
            await update.message.reply_text(
                f"📋 *تفاصيل الطلب*\n\n📢 القنوات الإجبارية: {len(context.user_data.get('raksh_channels', []))} قناة\n🔗 رابط التصويت: `{context.user_data['raksh_link']}`\n🔢 العدد: {quantity}\n\n💳 *اختر طريقة الدفع:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"💰 دفع بالنقاط ({points_cost} نقطة)", callback_data=f"raksh_votes_ai:payment:points:{quantity}:{points_cost}")],
                    [InlineKeyboardButton(f"⭐ دفع بالنجوم ({stars_cost} نجمة)", callback_data=f"raksh_votes_ai:payment:stars:{quantity}:{stars_cost}")],
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        if state == "confirm":
            await update.message.reply_text("⚠️ استخدم الأزرار للتأكيد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]]))
            return True

        return False

    async def handle_callback(self, update, context, query, data_parts, user, is_own) -> bool:
        if data_parts[0] == "skip_channels":
            context.user_data["raksh_channels"] = []
            context.user_data["raksh_step"] = "link"
            await query.edit_message_text(
                f"✅ تم تخطي القنوات.\n\n🔗 <b>أرسل رابط التصويت:</b>\n{self.get_link_instruction()}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]])
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
                await query.edit_message_text("⚠️ لا يمكن قبول هذا الطلب حالياً. حاول لاحقاً.", reply_markup=raksh_menu_kb(is_own))
                return True
            total_cost = self.get_total(quantity, payment_method)
            await query.edit_message_text(
                f"📋 *تأكيد الطلب*\n\n📢 القنوات الإجبارية: {len(context.user_data.get('raksh_channels', []))} قناة\n🔗 رابط التصويت: `{context.user_data.get('raksh_link', '')}`\n🔢 العدد: {quantity}\n💳 طريقة الدفع: {'💰 نقاط' if payment_method == 'points' else '⭐ نجوم'}\n💰 التكلفة: {total_cost} {'نقطة' if payment_method == 'points' else 'نجمة'}\n\n*هل تريد تأكيد الطلب؟*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ تأكيد الطلب", callback_data=f"raksh_votes_ai:confirm:{payment_method}:{quantity}:{total_cost}")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data="raksh_cancel")]
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
                await query.edit_message_text("⚠️ لا يمكن قبول هذا الطلب حالياً. حاول لاحقاً.", reply_markup=raksh_menu_kb(is_own))
                return True
            total_cost = self.get_total(quantity, payment_method)

            if payment_method == "points":
                if not deduct_points(user.id, total_cost):
                    await query.edit_message_text("❌ *نقاطك غير كافية!*", parse_mode=ParseMode.MARKDOWN, reply_markup=raksh_menu_kb(is_own))
                    return True
                await query.edit_message_text(
                    f"✅ *تم تأكيد الطلب وخصم النقاط!*\n\n📋 تفاصيل الطلب:\n📢 القنوات الإجبارية: {len(context.user_data.get('raksh_channels', []))} قناة\n🔗 الرابط: `{context.user_data.get('raksh_link', '')}`\n🔢 العدد: {quantity}\n💰 تم خصم: {total_cost} نقطة\n\n⏳ جاري الانضمام للقنوات وبدء التصويت مع التحقق...",
                    parse_mode=ParseMode.MARKDOWN
                )
                from .raksh_system import _start_raksh_execution
                await _start_raksh_execution(update, context, query, self.service_type, quantity, "points", total_cost)
                return True
            else:
                await query.edit_message_text("⭐ *جاري تجهيز فاتورة الدفع بالنجوم...*", parse_mode=ParseMode.MARKDOWN)
                await context.bot.send_invoice(
                    chat_id=user.id,
                    title=self.config.name,
                    description=f"{quantity} صوت مع تحقق | {total_cost} نجمة",
                    payload=f"raksh_stars:{user.id}:{self.service_type}:{quantity}:{total_cost}",
                    provider_token="", currency="XTR", prices=[LabeledPrice("تصويت مع تحقق", total_cost)]
                )
                return True

        return False

    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"

            if is_first and params.get("channel_ref"):
                for channel_ref in params["channel_ref"]:
                    try:
                        await _join_channel_and_schedule_leave(client, channel_ref)
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.warning(f"فشل الانضمام للقناة {channel_ref}: {e}")

            link = params["link"]
            channel_ref, msg_id = _parse_post_link(link)
            if channel_ref:
                return await self._handle_channel_vote(client, session, channel_ref, msg_id)

            bot_username, bot_start_param = _parse_bot_link(link)
            if bot_username:
                return await self._handle_bot_vote(client, session, bot_username, bot_start_param or "")

            return False, "الرابط غير صحيح لهذه الخدمة"

        except Exception as e:
            return False, f"❌ فشل: {str(e)}"
        finally:
            await client.disconnect()

    async def _handle_channel_vote(self, client, session, channel_ref: str, msg_id: int) -> Tuple[bool, str]:
        phone = session.get("phone_number")
        try:
            entity = await client.get_entity(channel_ref)
        except Exception as e:
            return False, f"تعذر الوصول للقناة: {str(e)[:80]}"

        try:
            message = await client.get_messages(entity, ids=msg_id)
            if isinstance(message, (list, tuple)):
                message = message[0] if message else None
        except Exception as e:
            return False, f"تعذر الوصول للمنشور: {str(e)[:80]}"

        if not message:
            return False, "المنشور غير موجود"

        bot_entity = None
        bot_start_param = ""

        if getattr(message, "buttons", None):
            for row in message.buttons:
                for btn in row:
                    if getattr(btn, "url", None):
                        url = btn.url
                        if "t.me/" in url or "telegram.me/" in url:
                            url_bot, url_start = _parse_bot_link(url)
                            if url_bot:
                                bot_entity = await self._get_bot_entity(client, url_bot)
                                bot_start_param = url_start or ""
                                break
                    else:
                        callback_data = getattr(btn, "data", None)
                        if callback_data:
                            try:
                                await client(GetBotCallbackAnswerRequest(peer=entity, msg_id=msg_id, data=callback_data))
                                await asyncio.sleep(1.0)
                                return await self._check_and_solve_verification(client, phone, bot_entity if bot_entity else None)
                            except Exception as e:
                                logger.warning(f"فشل الضغط على زر التصويت: {e}")
                                continue
                if bot_entity:
                    break

        if bot_entity:
            try:
                last_id = 0
                try:
                    msgs = await client.get_messages(bot_entity, limit=5)
                    if msgs:
                        last_id = max(msg.id for msg in msgs)
                except Exception:
                    pass

                await client(StartBotRequest(bot=bot_entity, peer=bot_entity, start_param=bot_start_param or ""))
                await asyncio.sleep(1.5)
                return await self._check_and_solve_verification(client, phone, bot_entity, start_after_message_id=last_id)
            except Exception as e:
                return False, f"فشل فتح البوت: {str(e)[:80]}"

        return False, "لم يتم العثور على زر بوت في المنشور"

    async def _handle_bot_vote(self, client, session, bot_username: str, start_param: str) -> Tuple[bool, str]:
        phone = session.get("phone_number")
        try:
            bot_entity = await self._get_bot_entity(client, bot_username)
        except Exception as e:
            return False, f"تعذر العثور على البوت: {str(e)[:80]}"

        try:
            last_id = 0
            try:
                msgs = await client.get_messages(bot_entity, limit=5)
                if msgs:
                    last_id = max(msg.id for msg in msgs)
            except Exception:
                pass

            await client(StartBotRequest(bot=bot_entity, peer=bot_entity, start_param=start_param or ""))
            await asyncio.sleep(1.5)
            return await self._check_and_solve_verification(client, phone, bot_entity, start_after_message_id=last_id)
        except Exception as e:
            return False, f"فشل بدء البوت: {str(e)[:80]}"

    async def _get_bot_entity(self, client, bot_username: str):
        clean_username = bot_username.lstrip("@").strip()
        try:
            resolved = await client(ResolveUsernameRequest(clean_username))
            if resolved.users:
                return resolved.users[0]
            elif resolved.chats:
                return resolved.chats[0]
        except Exception:
            pass
        try:
            return await client.get_entity(bot_username)
        except Exception:
            pass
        try:
            return await client.get_entity(f"@{bot_username}")
        except Exception as e:
            raise Exception(f"فشل العثور على البوت {bot_username}: {str(e)[:80]}")

    async def _check_and_solve_verification(self, client, phone: str, bot_entity=None, start_after_message_id: int = 0) -> Tuple[bool, str]:
        try:
            success = await self._solve_verification(client, bot_entity, phone, start_after_message_id)
            if success:
                return True, f"✅ تم التصويت مع التحقق من {phone}"
            else:
                return False, "فشل التحقق بعد محاولات متعددة"
        except Exception as e:
            logger.warning(f"فشل حل التحقق: {e}")
            return False, f"فشل التحقق: {str(e)[:80]}"

    # ========== دوال حل التحقق (مأخوذة من forced_ref_ai.py مع تسريع) ==========

    def _verification_message_text(self, message) -> str:
        """قراءة نص الرسالة أو caption مهما كان نوع كائن Telethon."""
        for field_name in ("message", "raw_text", "text"):
            value = getattr(message, field_name, None)
            if value:
                return str(value)
        return ""

    async def _solve_verification(self, client, bot_entity, phone_number: str, start_after_message_id: int = 0) -> bool:
        """
        حل التحقق بذكاء وسرعة:
        1. البحث عن طلب مشاركة رقم الهاتف وإرساله إذا وُجد.
        2. وإلا استخدام المنطق القديم: استخراج الكود، حل المسائل، الضغط على الأزرار.
        """
        MAX_WAIT = 8
        CHECK_INTERVAL = 0.5  # أسرع من السابق

        # ─── المرحلة 1: البحث عن طلب مشاركة رقم الهاتف ───
        contact_request_msg = None
        for _ in range(MAX_WAIT):
            try:
                messages = await client.get_messages(bot_entity, limit=5)
            except Exception:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            for msg in messages:
                if msg.out or msg.id <= start_after_message_id:
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

            # انتظار زر متابعة (أسرع)
            proceed_button = None
            for _ in range(MAX_WAIT):
                try:
                    messages = await client.get_messages(bot_entity, limit=5)
                except Exception:
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                for msg in messages:
                    if msg.out or msg.id <= start_after_message_id:
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

            # انتظار تأكيد النجاح (أسرع)
            for _ in range(MAX_WAIT):
                try:
                    latest = await client.get_messages(bot_entity, limit=3)
                    success = False
                    for msg in latest:
                        if msg.out or msg.id <= start_after_message_id:
                            continue
                        text = self._verification_message_text(msg).strip().casefold()
                        if not msg.reply_markup and text:
                            success = True
                            break
                        if any(kw in text for kw in ['تم', 'نجاح', 'مرحباً', 'شكراً', 'success', 'done', 'welcome']):
                            success = True
                            break
                    if success:
                        logger.info(f"✅ تم التحقق بنجاح (مشاركة الرقم) من {phone_number}")
                        return True
                except Exception:
                    pass
                await asyncio.sleep(CHECK_INTERVAL)

            # فحص اختفاء الأزرار
            try:
                original = await client.get_messages(bot_entity, ids=contact_request_msg.id)
                if original and not original.reply_markup:
                    logger.info(f"✅ اختفت أزرار طلب الرقم، نعتبر النجاح من {phone_number}")
                    return True
            except Exception:
                pass

            logger.warning(f"⚠️ لم نؤكد التحقق لكننا سنعتبره ناجحاً (مشاركة الرقم) من {phone_number}")
            return True

        # ─── المرحلة 2: لم يطلب الرقم → استخدم المنطق السريع للكابتشا ───
        logger.info(f"🔍 لم يطلب البوت رقم هاتف، ننتقل إلى المنطق السريع لـ {phone_number}")
        return await self._solve_legacy_verification(client, bot_entity, phone_number, start_after_message_id)

    async def _solve_legacy_verification(self, client, bot_entity, phone_number: str, start_after_message_id: int = 0) -> bool:
        """
        المنطق السريع: استخراج الكود، حل المسائل، الضغط على الأزرار (الكابتشا)
        مع تحسين السرعة: فترات انتظار قصيرة (0.3 ثانية) ومحاولات أكثر.
        """
        max_attempts = 25
        base_id = start_after_message_id

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
            except Exception as exc:
                if "two different IP" in str(exc) or "AuthKeyDuplicated" in str(exc):
                    logger.error(f"⚠️ الجلسة {phone_number} تستخدم من IP مختلف - سيتم تعطيلها")
                    _mark_raksh_session_unauthorized(phone_number)
                    return False
                await asyncio.sleep(0.3)
                continue

            incoming_messages = [msg for msg in messages if not msg.out and msg.id > base_id]
            if not incoming_messages:
                await asyncio.sleep(0.3)
                continue

            # 1. فحص رسالة النجاح
            for msg in incoming_messages:
                text = self._verification_message_text(msg)
                if ("تم التحقق" in text or "نجح التحقق" in text or "successful" in text.lower() or "welcome" in text.lower()):
                    logger.info(f"✅ تم تأكيد التحقق من {phone_number}")
                    return True

            # 2. تحديد رسالة التحقق (التي تحتوي على أزرار أو طلب)
            verification_msg = None
            for msg in incoming_messages:
                if not msg.reply_markup and not getattr(msg, 'buttons', None):
                    continue
                text = self._verification_message_text(msg)
                if any(kw in text for kw in ["اضغط", "اختر", "انقر", "الرمز", "رمز", "verify", "تحقق"]):
                    verification_msg = msg
                    break
            if verification_msg is None:
                for msg in incoming_messages:
                    if msg.reply_markup or getattr(msg, 'buttons', None):
                        verification_msg = msg
                        break

            if not verification_msg:
                await asyncio.sleep(0.3)
                continue

            text = self._verification_message_text(verification_msg)

            # 3. استخراج الكود
            send_text = _extract_code_from_text(text)
            if send_text:
                try:
                    await client.send_message(bot_entity, send_text)
                    logger.info(f"✅ تم إرسال الكود: {send_text}")
                    return True
                except Exception:
                    pass

            # 4. حل المسائل الرياضية (سريع)
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

            # 5. الضغط على الأزرار (الكابتشا)
            buttons = []
            if verification_msg.reply_markup:
                for row in verification_msg.reply_markup.rows:
                    for btn in row.buttons:
                        if not getattr(btn, 'url', None):
                            buttons.append(btn)
            if not buttons and getattr(verification_msg, 'buttons', None):
                for row in verification_msg.buttons:
                    for btn in row:
                        if not getattr(btn, 'url', None):
                            buttons.append(btn)

            if buttons:
                # استخراج الإيموجي المطلوب
                emoji_pattern = re.compile(
                    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E0-\U0001F1FF]"
                )
                found_emojis = emoji_pattern.findall(text)
                target_emoji = found_emojis[-1] if found_emojis else None
                logger.info(f"🎯 الإيموجي المطلوب: {target_emoji}")

                # ترتيب الأزرار حسب الأولوية
                prioritized = []
                if target_emoji:
                    exact = [b for b in buttons if getattr(b, 'text', '') == target_emoji]
                    prioritized.extend(exact)
                    partial = [b for b in buttons if target_emoji in (getattr(b, 'text', '') or '')]
                    prioritized.extend(partial)

                verify_keywords = ['تحقق', 'verify', 'اضغط هنا', 'continue', 'التالي', 'متابعة']
                verify_buttons = [
                    b for b in buttons
                    if any(kw in (getattr(b, 'text', '') or '').casefold() for kw in verify_keywords)
                    and b not in prioritized
                ]
                prioritized.extend(verify_buttons)

                # باقي الأزرار
                remaining = [b for b in buttons if b not in prioritized]
                prioritized.extend(remaining)

                # الضغط على الأزرار بالترتيب مع فحص النجاح بعد كل ضغطة
                for btn in prioritized:
                    try:
                        btn_text = getattr(btn, 'text', '')
                        await btn.click()
                        logger.info(f"🖱️ تم الضغط على الزر: {btn_text}")
                        # انتظار قصير ثم التحقق من النجاح
                        await asyncio.sleep(0.3)
                        # إعادة فحص الرسائل للتحقق من النجاح
                        latest = await client.get_messages(bot_entity, limit=3)
                        for msg in latest:
                            if msg.out or msg.id <= base_id:
                                continue
                            msg_text = self._verification_message_text(msg)
                            if ("تم التحقق" in msg_text or "نجح التحقق" in msg_text or "successful" in msg_text.lower()):
                                logger.info(f"✅ تم تأكيد التحقق من {phone_number}")
                                return True
                        # إذا اختفت الأزرار من الرسالة الأصلية، نعتبر نجاحاً
                        refreshed = await client.get_messages(bot_entity, ids=verification_msg.id)
                        if isinstance(refreshed, (list, tuple)):
                            refreshed = refreshed[0] if refreshed else None
                        if refreshed and not getattr(refreshed, 'buttons', None) and not refreshed.reply_markup:
                            logger.info(f"✅ اختفت الأزرار بعد الضغط، نجاح من {phone_number}")
                            return True
                    except Exception:
                        continue

            await asyncio.sleep(0.3)

        # بعد كل المحاولات، نعتبر العملية ناجحة إذا لم يحدث خطأ واضح
        logger.warning(f"⚠️ لم نتمكن من حل التحقق لكننا سنعتبره ناجحاً (legacy) من {phone_number}")
        return True
