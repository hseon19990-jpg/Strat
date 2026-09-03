# premium_reaction.py
from .common import *
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji, ReactionCustomEmoji, ReactionPaid

class PremiumReactionService(RakshService):
    """خدمة رشق تفاعل مميز - كل شيء في مكان واحد"""
    
    service_type = "premium_reaction"
    label = "✨ رشق تفاعل مميز"
    config = ServiceConfig(
        name=label,
        price_points=10,
        points_quantity=1,
        price_stars=2,
        stars_quantity=1,
        has_channel=False,
        has_reaction=True,
        has_ai=False,
        needs_link=True,
        min_delay=3,
        max_delay=3
    )
    
    def get_initial_state(self) -> str:
        """البدء بطلب الرابط مباشرة"""
        return "link"
    
    def get_link_instruction(self) -> str:
        return "https://t.me/channel/123"
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        
        channel_ref, msg_id = _parse_post_link(value)
        if not channel_ref:
            return "⚠️ الرابط غير صحيح.\n\nأرسل: https://t.me/channel/123"
        
        return None
    
    def get_start_message(self) -> str:
        return (
            f"{self.config.name}\n\n"
            f"💰 السعر: {self.get_rate_text('points')}\n"
            f"⭐ السعر: {self.get_rate_text('stars')}\n\n"
            f"🔗 *أرسل رابط المنشور:*\n"
            f"{self.get_link_instruction()}"
        )
    
    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        """معالجة النص لخدمة رشق التفاعل المميز"""
        
        # ═══ الخطوة 1: استقبال رابط المنشور ═══
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
                f"🔢 *أرسل عدد التفاعلات المطلوبة:*\n"
                f"(الحد الأقصى: {max_qty})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        # ═══ الخطوة 2: استقبال العدد ═══
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
            context.user_data["raksh_step"] = "fetch_reactions"
            
            # ═══ جلب التفاعلات المتاحة من البوست ═══
            await update.message.reply_text(
                "⏳ *جاري جلب التفاعلات المتاحة من المنشور...*",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # جلب التفاعلات
            reactions = await self._fetch_reactions_from_post(context.user_data["raksh_link"])
            
            if not reactions:
                # إذا لم نجد تفاعلات، نستخدم الافتراضية
                reactions = list(RAKSH_REACTIONS.values())
            
            context.user_data["raksh_available_reactions"] = reactions
            
            # عرض التفاعلات
            points_cost = self.get_total(quantity, "points")
            stars_cost = self.get_total(quantity, "stars")
            
            reaction_buttons = []
            row = []
            
            for index, reaction in enumerate(reactions, start=1):
                if reaction == RAKSH_PAID_REACTION:
                    label = RAKSH_PAID_REACTION_LABEL
                    callback_key = "paid"
                elif _custom_reaction_document_id(reaction) is not None:
                    label = f"🎨 تفاعل مميز {index}"
                    callback_key = f"custom_{_custom_reaction_document_id(reaction)}"
                else:
                    label = reaction
                    callback_key = reaction if reaction in RAKSH_REACTIONS else str(index)
                
                row.append(
                    InlineKeyboardButton(
                        label,
                        callback_data=f"raksh_premium_reaction:select:{callback_key}"
                    )
                )
                if len(row) == 4:
                    reaction_buttons.append(row)
                    row = []
            
            if row:
                reaction_buttons.append(row)
            
            reaction_buttons.append([
                InlineKeyboardButton(
                    "🎲 عشوائي",
                    callback_data="raksh_premium_reaction:select:random"
                )
            ])
            reaction_buttons.append([
                InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")
            ])
            
            await update.message.reply_text(
                f"✅ تم جلب التفاعلات المتاحة!\n\n"
                f"📋 *تفاصيل الطلب*\n\n"
                f"🔗 الرابط: `{context.user_data['raksh_link']}`\n"
                f"🔢 العدد: {quantity}\n\n"
                f"✨ *اختر نوع التفاعل:*\n"
                f"(إذا اخترت عشوائي سيتم اختيار تفاعل عشوائياً)",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(reaction_buttons)
            )
            return True
        
        return False
    
    async def handle_callback(self, update, context, query, data_parts, user, is_own) -> bool:
        """معالجة الأزرار لخدمة رشق التفاعل المميز"""
        
        # ═══ اختيار التفاعل ═══
        if data_parts[0] == "select" and len(data_parts) >= 2:
            reaction_key = data_parts[1]
            
            available_reactions = context.user_data.get("raksh_available_reactions", [])
            
            if reaction_key == "random":
                reaction = "random"
                reaction_label = "🎲 عشوائي"
            elif reaction_key == "paid":
                reaction = RAKSH_PAID_REACTION
                reaction_label = RAKSH_PAID_REACTION_LABEL
            elif reaction_key.startswith("custom_"):
                doc_id = reaction_key[7:]
                reaction = f"{RAKSH_CUSTOM_REACTION_PREFIX}{doc_id}"
                reaction_label = f"🎨 تفاعل مميز {doc_id}"
            else:
                reaction = RAKSH_REACTIONS.get(reaction_key, reaction_key)
                reaction_label = reaction
            
            context.user_data["raksh_reaction"] = reaction
            
            quantity = context.user_data.get("raksh_quantity", 1)
            points_cost = self.get_total(quantity, "points")
            stars_cost = self.get_total(quantity, "stars")
            
            await query.edit_message_text(
                f"📋 *تأكيد الطلب*\n\n"
                f"🔗 الرابط: `{context.user_data.get('raksh_link', '')}`\n"
                f"🔢 العدد: {quantity}\n"
                f"✨ التفاعل: {reaction_label}\n\n"
                f"💳 *اختر طريقة الدفع:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"💰 دفع بالنقاط ({points_cost} نقطة)",
                            callback_data=f"raksh_premium_reaction:payment:points:{quantity}:{points_cost}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                            callback_data=f"raksh_premium_reaction:payment:stars:{quantity}:{stars_cost}"
                        )
                    ],
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
                f"🔗 الرابط: `{context.user_data.get('raksh_link', '')}`\n"
                f"🔢 العدد: {quantity}\n"
                f"✨ التفاعل: {context.user_data.get('raksh_reaction', '')}\n"
                f"💳 طريقة الدفع: {'💰 نقاط' if payment_method == 'points' else '⭐ نجوم'}\n"
                f"💰 التكلفة: {total_cost} {'نقطة' if payment_method == 'points' else 'نجمة'}\n\n"
                f"*هل تريد تأكيد الطلب؟*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ تأكيد الطلب",
                            callback_data=f"raksh_premium_reaction:confirm:{payment_method}:{quantity}:{total_cost}"
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
                    f"🔗 الرابط: `{context.user_data.get('raksh_link', '')}`\n"
                    f"🔢 العدد: {quantity}\n"
                    f"✨ التفاعل: {context.user_data.get('raksh_reaction', '')}\n"
                    f"💰 تم خصم: {total_cost} نقطة\n\n"
                    f"⏳ جاري بدء التنفيذ...",
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
                    description=f"{quantity} تفاعل مميز | {total_cost} نجمة",
                    payload=f"raksh_stars:{user.id}:{self.service_type}:{quantity}:{total_cost}",
                    provider_token="",
                    currency="XTR",
                    prices=[LabeledPrice("تفاعل مميز", total_cost)],
                )
                return True
        
        return False
    
    async def _fetch_reactions_from_post(self, link: str) -> List[str]:
        """جلب التفاعلات المتاحة من المنشور"""
        try:
            # تحليل الرابط
            channel_ref, msg_id = _parse_post_link(link)
            if not channel_ref:
                return []
            
            # جلب جلسة مؤقتة للفحص
            sessions = self.get_sessions()
            if not sessions:
                return []
            
            # استخدام أول جلسة متاحة للفحص
            session = sessions[0]
            client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            
            try:
                await asyncio.wait_for(client.connect(), timeout=10)
                if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                    return []
                
                entity = await client.get_entity(channel_ref)
                message = await client.get_messages(entity, ids=msg_id)
                
                if not message:
                    return []
                
                # جلب التفاعلات المتاحة من الرسالة
                reactions = []
                
                # 1. التفاعلات الموجودة في الرسالة
                message_reactions = getattr(getattr(message, "reactions", None), "results", None)
                if message_reactions:
                    for reaction in message_reactions:
                        reaction_type = getattr(reaction, "reaction", None)
                        if reaction_type:
                            reaction_class = reaction_type.__class__.__name__
                            if reaction_class == "ReactionPaid":
                                reactions.append(RAKSH_PAID_REACTION)
                            elif reaction_class == "ReactionCustomEmoji":
                                doc_id = getattr(reaction_type, "document_id", None)
                                if doc_id:
                                    reactions.append(f"{RAKSH_CUSTOM_REACTION_PREFIX}{doc_id}")
                            else:
                                emoticon = getattr(reaction_type, "emoticon", None)
                                if emoticon:
                                    reactions.append(emoticon)
                
                # 2. التفاعلات المتاحة من القناة
                if not reactions:
                    full_channel = await client(functions.channels.GetFullChannelRequest(channel=entity))
                    full_chat = getattr(full_channel, "full_chat", None)
                    
                    # التفاعلات المدفوعة
                    if getattr(full_chat, "paid_reactions_available", False):
                        reactions.append(RAKSH_PAID_REACTION)
                    
                    # التفاعلات المتاحة
                    available = getattr(full_chat, "available_reactions", None)
                    configured = getattr(available, "reactions", None)
                    if configured:
                        for reaction in configured:
                            reaction_type = getattr(reaction, "reaction", None)
                            if reaction_type:
                                reaction_class = reaction_type.__class__.__name__
                                if reaction_class == "ReactionCustomEmoji":
                                    doc_id = getattr(reaction_type, "document_id", None)
                                    if doc_id:
                                        reactions.append(f"{RAKSH_CUSTOM_REACTION_PREFIX}{doc_id}")
                                else:
                                    emoticon = getattr(reaction_type, "emoticon", None)
                                    if emoticon:
                                        reactions.append(emoticon)
                    
                    # إذا كانت كل التفاعلات متاحة
                    if available is not None and available.__class__.__name__ == "ChatReactionsAll":
                        reactions.extend(list(RAKSH_REACTIONS.values()))
                
                return list(dict.fromkeys(reactions))  # إزالة التكرارات
                
            finally:
                await client.disconnect()
                
        except Exception as e:
            logger.warning(f"فشل جلب التفاعلات: {e}")
            return []
    
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ رشق تفاعل مميز - الضغط على الرابط والتفاعل"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"
            
            # تحليل رابط المنشور
            channel_ref, msg_id = _parse_post_link(params["link"])
            if not channel_ref:
                return False, "رابط المنشور غير صحيح"
            
            entity = await client.get_entity(channel_ref)
            
            # تحديد التفاعل
            reaction_value = params.get("reaction", "random")
            
            if reaction_value == "random":
                # اختيار تفاعل عشوائي من المتاح
                available = params.get("available_reactions") or list(RAKSH_REACTIONS.values())
                reaction_value = random.choice(available)
            
            # تنفيذ التفاعل
            try:
                if reaction_value == RAKSH_PAID_REACTION:
                    # تفاعل مدفوع
                    await client(SendReactionRequest(
                        peer=entity,
                        msg_id=msg_id,
                        reaction=ReactionEmoji(emoticon="⭐"),
                        big=True
                    ))
                elif _custom_reaction_document_id(reaction_value) is not None:
                    # تفاعل مخصص
                    doc_id = _custom_reaction_document_id(reaction_value)
                    await client(SendReactionRequest(
                        peer=entity,
                        msg_id=msg_id,
                        reaction=ReactionCustomEmoji(document_id=doc_id)
                    ))
                else:
                    # تفاعل عادي
                    await client(SendReactionRequest(
                        peer=entity,
                        msg_id=msg_id,
                        reaction=ReactionEmoji(emoticon=reaction_value)
                    ))
                
                return True, f"✅ تم التفاعل من {session['phone_number']}"
                
            except Exception as e:
                logger.warning(f"فشل التفاعل {reaction_value}: {e}")
                
                # محاولة بديلة: تفاعل عادي
                try:
                    await client(SendReactionRequest(
                        peer=entity,
                        msg_id=msg_id,
                        reaction=ReactionEmoji(emoticon="❤️")
                    ))
                    return True, f"✅ تم التفاعل (بديل) من {session['phone_number']}"
                except Exception as e2:
                    return False, f"❌ فشل التفاعل: {str(e2)}"
                
        except Exception as e:
            return False, f"❌ فشل: {str(e)}"
        finally:
            await client.disconnect()
