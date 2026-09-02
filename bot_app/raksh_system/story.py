# story.py
from .common import *

class StoryService(RakshService):
    """خدمة مشاهدة ستوري وتفاعل - كل شيء في مكان واحد"""
    
    service_type = "story"
    label = "📱 مشاهدة ستوري وتفاعل"
    config = ServiceConfig(
        name=label,
        price_points=30,
        points_quantity=1,
        price_stars=1,
        stars_quantity=10,
        has_channel=False,
        has_reaction=True,
        has_ai=False,
        needs_link=True,
        min_delay=3,
        max_delay=3,
        max_concurrent=12  # ✅ 12 حساب بالتوازي
    )
    
    def get_link_instruction(self) -> str:
        return (
            "أرسل رابط الستوري بأحد هذه الصيغ:\n"
            "• https://t.me/username/s/123\n"
            "• https://t.me/username/story/123\n"
            "• https://t.me/c/123456789/123"
        )
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        
        entity_ref, story_id = _parse_story_link(value)
        if not entity_ref or not story_id:
            return (
                "⚠️ رابط الستوري غير صحيح.\n\n"
                "أرسله بهذا الشكل:\n"
                "https://t.me/username/s/123\n"
                "أو: https://t.me/username/story/123\n"
                "أو: https://t.me/c/123456789/123"
            )
        return None
    
    def get_start_message(self) -> str:
        return (
            f"{self.config.name}\n\n"
            f"💰 السعر: {self.get_rate_text('points')}\n"
            f"⭐ السعر: {self.get_rate_text('stars')}\n\n"
            f"🔗 *أرسل رابط الستوري:*\n"
            f"{self.get_link_instruction()}"
        )
    
    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        """معالجة النص لخدمة الستوري"""
        
        # الخطوة 1: استقبال الرابط
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
                f"✅ تم حفظ رابط الستوري.\n\n"
                f"🔢 *أرسل عدد المشاهدات المطلوبة:*\n"
                f"(الحد الأقصى: {max_qty})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        # الخطوة 2: استقبال العدد
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
            context.user_data["raksh_step"] = "payment"  # ✅ الخطوة الجديدة
            
            # عرض أزرار اختيار طريقة الدفع
            points_cost = self.get_total(quantity, "points")
            stars_cost = self.get_total(quantity, "stars")
            
            await update.message.reply_text(
                f"📋 *تفاصيل الطلب*\n\n"
                f"🔗 الرابط: `{context.user_data['raksh_link']}`\n"
                f"🔢 العدد: {quantity}\n\n"
                f"💳 *اختر طريقة الدفع:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"💰 دفع بالنقاط ({points_cost} نقطة)",
                            callback_data=f"raksh_story:payment:points:{quantity}:{points_cost}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                            callback_data=f"raksh_story:payment:stars:{quantity}:{stars_cost}"
                        )
                    ],
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        # الخطوة 3: انتظار التأكيد
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
        """معالجة الأزرار لخدمة الستوري"""
        
        # الخطوة 3: اختيار طريقة الدفع
        if data_parts[0] == "payment" and len(data_parts) >= 5:
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
            
            # عرض شاشة التأكيد النهائي
            await query.edit_message_text(
                f"📋 *تأكيد الطلب*\n\n"
                f"🔗 الرابط: `{context.user_data.get('raksh_link', '')}`\n"
                f"🔢 العدد: {quantity}\n"
                f"💳 طريقة الدفع: {'💰 نقاط' if payment_method == 'points' else '⭐ نجوم'}\n"
                f"💰 التكلفة: {total_cost} {'نقطة' if payment_method == 'points' else 'نجمة'}\n\n"
                f"*هل تريد تأكيد الطلب؟*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ تأكيد الطلب",
                            callback_data=f"raksh_story:confirm:{payment_method}:{quantity}:{total_cost}"
                        ),
                        InlineKeyboardButton(
                            "❌ إلغاء",
                            callback_data="raksh_cancel"
                        )
                    ]
                ])
            )
            return True
        
        # الخطوة 4: التأكيد النهائي وبدء التنفيذ
        if data_parts[0] == "confirm" and len(data_parts) >= 5:
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
                    f"💰 تم خصم: {total_cost} نقطة\n\n"
                    f"⏳ جاري بدء التنفيذ...",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                await _start_raksh_execution(
                    update, context, query, self.service_type, quantity, "points", total_cost  # ✅ تصحيح
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
                    description=f"{quantity} مشاهدة ستوري | {total_cost} نجمة",
                    payload=f"raksh_stars:{user.id}:{self.service_type}:{quantity}:{total_cost}",
                    provider_token="",
                    currency="XTR",
                    prices=[LabeledPrice("مشاهدة ستوري", total_cost)],
                )
                return True
        
        return False
    
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ مشاهدة ستوري وتفاعل"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"
            
            entity_ref, story_id = _parse_story_link(params["link"])
            if not entity_ref or not story_id:
                return False, "رابط الستوري غير صحيح"
            
            try:
                entity = await client.get_entity(entity_ref)
            except Exception as e:
                return False, f"تعذر الوصول للكيان: {str(e)[:80]}"
            
            # ✅ محاولة مشاهدة الستوري بعدة طرق
            view_success = False
            
            # الطريقة 1: IncrementStoryViewsRequest (الأفضل)
            try:
                await client(IncrementStoryViewsRequest(peer=entity, id=story_id))
                view_success = True
                logger.info(f"👁️ تمت مشاهدة الستوري {story_id} من {session['phone_number']}")
            except Exception:
                pass
            
            # الطريقة 2: SendReactionRequest (تعتبر مشاهدة)
            if not view_success:
                try:
                    await client(SendReactionRequest(
                        peer=entity,
                        story_id=story_id,
                        reaction=ReactionEmoji(emoticon="❤️")
                    ))
                    view_success = True
                    logger.info(f"👁️ تمت مشاهدة الستوري {story_id} من {session['phone_number']}")
                except Exception:
                    pass
            
            # الطريقة 3: get_messages (الوصول للستوري)
            if not view_success:
                try:
                    await client.get_messages(entity, ids=story_id)
                    view_success = True
                    logger.info(f"👁️ تم الوصول للستوري {story_id} من {session['phone_number']}")
                except Exception:
                    pass
            
            if not view_success:
                return False, "تعذر مشاهدة الستوري"
            
            # ✅ إضافة تفاعل عشوائي
            try:
                reaction = params.get("reaction") or "❤️"
                if reaction == "random":
                    reaction = random.choice(["❤️", "🔥", "👍", "😍", "🤩", "✨", "💯", "👏", "😂", "😮"])
                
                await client(
                    SendReactionRequest(
                        peer=entity,
                        story_id=story_id,
                        reaction=ReactionEmoji(emoticon=reaction),
                    )
                )
                return True, f"✅ تمت المشاهدة والتفاعل من {session['phone_number']}"
            except Exception as reaction_error:
                logger.warning(f"تفاعل فاشل للستوري {session['phone_number']}: {reaction_error}")
                return True, f"✅ تمت المشاهدة من {session['phone_number']}"
                
        except Exception as e:
            return False, f"❌ فشل: {str(e)[:80]}"
        finally:
            await client.disconnect()
