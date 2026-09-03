# votes.py
from .common import *
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

class VotesService(RakshService):
    """خدمة رشق أصوات - كل شيء في مكان واحد"""
    
    service_type = "votes"
    label = "🗳 رشق أصوات"
    config = ServiceConfig(
        name=label,
        price_points=20,
        points_quantity=1,
        price_stars=4,
        stars_quantity=1,
        has_channel=True,
        has_reaction=False,
        has_ai=False,
        needs_link=True,
        min_delay=3,
        max_delay=3
    )
    
    def get_initial_state(self) -> str:
        """البدء بطلب القنوات الإجبارية"""
        return "channel"
    
    def get_link_instruction(self) -> str:
        return (
            "أرسل رابط المنشور الذي يحتوي على زر التصويت:\n"
            "https://t.me/channel/123"
        )
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        
        channel_ref, msg_id = _parse_post_link(value)
        if not channel_ref:
            return "⚠️ الرابط غير صحيح.\n\nأرسل رابط منشور: https://t.me/channel/123"
        
        return None
    
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
            [InlineKeyboardButton("⏭️ تخطي (بدون قنوات)", callback_data="raksh_votes:skip_channels")],
            [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
        ])
    
    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        """معالجة النص لخدمة رشق الأصوات"""
        
        # ═══ الخطوة 1: استقبال القنوات الإجبارية ═══
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
                f"🔗 *أرسل رابط المنشور:*\n"
                f"{self.get_link_instruction()}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        # ═══ الخطوة 2: استقبال رابط المنشور ═══
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
                f"✅ تم حفظ رابط المنشور.\n\n"
                f"🔢 *أرسل عدد الأصوات المطلوبة:*\n"
                f"(الحد الأقصى: {max_qty})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        # ═══ الخطوة 3: استقبال العدد ═══
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
                f"🔗 رابط المنشور: `{context.user_data['raksh_link']}`\n"
                f"🔢 العدد: {quantity}\n\n"
                f"💳 *اختر طريقة الدفع:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"💰 دفع بالنقاط ({points_cost} نقطة)",
                            callback_data=f"raksh_votes:payment:points:{quantity}:{points_cost}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                            callback_data=f"raksh_votes:payment:stars:{quantity}:{stars_cost}"
                        )
                    ],
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        # ═══ الخطوة 4: انتظار التأكيد ═══
        if state == "confirm":
            await update.message.reply_text(
                "⚠️ استخدم الأزرار للتأكيد.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        return False
    
    async def handle_callback(self, update, context, query, data_parts, user, is_own) -> bool:
        """معالجة الأزرار لخدمة رشق الأصوات"""
        
        # ═══ تخطي القنوات ═══
        if data_parts[0] == "skip_channels":
            context.user_data["raksh_channels"] = []
            context.user_data["raksh_step"] = "link"
            
            await query.edit_message_text(
                f"✅ تم تخطي القنوات.\n\n"
                f"🔗 *أرسل رابط المنشور:*\n"
                f"{self.get_link_instruction()}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        # ═══ اختيار طريقة الدفع ═══
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
                await query.edit_message_text(
                    "⚠️ لا يمكن قبول هذا الطلب حالياً. حاول لاحقاً.",
                    reply_markup=raksh_menu_kb(is_own),
                )
                return True
            
            total_cost = self.get_total(quantity, payment_method)
            
            await query.edit_message_text(
                f"📋 *تأكيد الطلب*\n\n"
                f"📢 القنوات الإجبارية: {len(context.user_data.get('raksh_channels', []))} قناة\n"
                f"🔗 رابط المنشور: `{context.user_data.get('raksh_link', '')}`\n"
                f"🔢 العدد: {quantity}\n"
                f"💳 طريقة الدفع: {'💰 نقاط' if payment_method == 'points' else '⭐ نجوم'}\n"
                f"💰 التكلفة: {total_cost} {'نقطة' if payment_method == 'points' else 'نجمة'}\n\n"
                f"*هل تريد تأكيد الطلب؟*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ تأكيد الطلب",
                            callback_data=f"raksh_votes:confirm:{payment_method}:{quantity}:{total_cost}"
                        ),
                        InlineKeyboardButton(
                            "❌ إلغاء",
                            callback_data="raksh_cancel"
                        )
                    ]
                ])
            )
            return True
        
        # ═══ التأكيد النهائي وبدء التنفيذ ═══
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
                    f"⏳ جاري الانضمام للقنوات وبدء التصويت...",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # استيراد محلي لتجنب مشاكل الاستيراد الدائري
                from .raksh_system import _start_raksh_execution
                await _start_raksh_execution(
                    update, context, query, self.service_type, quantity, "points", total_cost
                )
                return True
            
            else:
                await query.edit_message_text(
                    "⭐ *جاري تجهيز فاتورة الدفع بالنجوم...*",
                    parse_mode=ParseMode.MARKDOWN,
                )
                await context.bot.send_invoice(
                    chat_id=user.id,
                    title=self.config.name,
                    description=f"{quantity} صوت | {total_cost} نجمة",
                    payload=f"raksh_stars:{user.id}:{self.service_type}:{quantity}:{total_cost}",
                    provider_token="",
                    currency="XTR",
                    prices=[LabeledPrice("رشق أصوات", total_cost)],
                )
                return True
        
        return False
    
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ رشق أصوات - الضغط على الزر في المنشور مباشرة"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"
            
            # 1️⃣ الانضمام للقنوات الإجبارية
            if params.get("channel_ref"):
                for channel_ref in params["channel_ref"]:
                    try:
                        await _join_channel_and_schedule_leave(client, channel_ref)
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.warning(f"فشل الانضمام للقناة {channel_ref}: {e}")
            
            # 2️⃣ تحليل رابط المنشور
            channel_ref, msg_id = _parse_post_link(params["link"])
            if not channel_ref:
                return False, "رابط المنشور غير صحيح"
            
            # 3️⃣ الوصول إلى القناة والمنشور
            entity = await client.get_entity(channel_ref)
            message = await client.get_messages(entity, ids=msg_id)
            if not message:
                return False, "المنشور غير موجود"
            
            # 4️⃣ البحث عن الزر في المنشور (زر بدون رابط = زر قابل للضغط)
            if getattr(message, "buttons", None):
                for row in message.buttons:
                    for btn in row:
                        # تجاهل الأزرار التي تحتوي على روابط
                        if getattr(btn, "url", None):
                            continue
                        
                        # الضغط على الزر باستخدام GetBotCallbackAnswerRequest
                        try:
                            # استخراج البيانات من الزر
                            callback_data = getattr(btn, "data", None)
                            if callback_data is None:
                                continue
                            
                            # إرسال طلب الضغط على الزر
                            await client(GetBotCallbackAnswerRequest(
                                peer=entity,
                                msg_id=msg_id,
                                data=callback_data
                            ))
                            
                            await asyncio.sleep(1.0)
                            return True, f"✅ تم الضغط على زر التصويت من {session['phone_number']}"
                            
                        except Exception as e:
                            logger.warning(f"فشل الضغط على الزر: {e}")
                            continue
            
            # 5️⃣ إذا لم نجد زر، نجرب الضغط على أول زر موجود
            if getattr(message, "buttons", None):
                for row in message.buttons:
                    for btn in row:
                        if getattr(btn, "url", None):
                            continue
                        try:
                            callback_data = getattr(btn, "data", None)
                            if callback_data is None:
                                continue
                            
                            await client(GetBotCallbackAnswerRequest(
                                peer=entity,
                                msg_id=msg_id,
                                data=callback_data
                            ))
                            
                            await asyncio.sleep(1.0)
                            return True, f"✅ تم الضغط على الزر من {session['phone_number']}"
                        except Exception:
                            continue
            
            return False, "لم يتم العثور على زر قابل للضغط في المنشور"
            
        except Exception as e:
            return False, f"❌ فشل التصويت: {str(e)}"
        finally:
            await client.disconnect()
