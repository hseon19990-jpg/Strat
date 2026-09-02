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
        max_delay=3
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
            context.user_data["raksh_step"] = "confirm"
            
            points_cost = self.get_total(quantity, "points")
            stars_cost = self.get_total(quantity, "stars")
            
            await update.message.reply_text(
                f"📋 *مراجعة طلب مشاهدة الستوري*\n\n"
                f"🔗 الرابط: `{context.user_data['raksh_link']}`\n"
                f"🔢 العدد: {quantity}\n"
                f"💰 السعر بالنقاط: {points_cost} نقطة\n"
                f"⭐ السعر بالنجوم: {stars_cost} نجمة\n\n"
                f"اختر طريقة الدفع:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"💰 دفع بالنقاط ({points_cost} نقطة)",
                            callback_data=f"raksh_story:confirm:points:{quantity}:{points_cost}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                            callback_data=f"raksh_story:confirm:stars:{quantity}:{stars_cost}"
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
    
    async def handle_callback(self, update, context, query, data_parts, user, is_own) -> bool:
        """معالجة الأزرار لخدمة الستوري"""
        
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
                    f"💰 تم خصم: {total_cost} نقطة\n\n"
                    f"⏳ جاري بدء التنفيذ...",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                await _start_raksh_execution(
                    update, context, query, "story", quantity, "points", total_cost
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
        """تنفيذ مشاهدة ستوري وتفاعل عشوائي"""
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
            
            # ✅ 1. فتح الستوري فعلياً (جلب بياناته) - هذا يجعل الحساب "يشاهد" الستوري
            try:
                # استخدام GetStoryViewsRequest لتأكيد الستوري موجود وقابل للمشاهدة
                await client(GetStoryViewsRequest(
                    peer=entity,
                    id=story_id
                ))
                # استخدام IncrementStoryViewsRequest لإخبار تيليجرام بأن الحساب شاهد الستوري
                await client(IncrementStoryViewsRequest(
                    peer=entity,
                    id=story_id
                ))
                logger.info(f"👁️ تم فتح الستوري {story_id} من {session['phone_number']}")
            except Exception as e:
                # إذا فشل، قد يكون الستوري خاص أو محذوف
                logger.warning(f"تعذر فتح الستوري {story_id}: {str(e)[:80]}")
                return False, f"تعذر مشاهدة الستوري: {str(e)[:80]}"
            
            # ✅ 2. إضافة تفاعل عشوائي
            try:
                # قائمة تفاعلات عشوائية
                random_reactions = ["❤️", "🔥", "👍", "😍", "🤩", "✨", "💯", "👏", "😂", "😮", "👎", "💔", "🥰", "🤔"]
                
                # اختيار تفاعل عشوائي
                chosen_reaction = random.choice(random_reactions)
                
                # إرسال التفاعل على الستوري
                await client(SendReactionRequest(
                    peer=entity,
                    story_id=story_id,
                    reaction=ReactionEmoji(emoticon=chosen_reaction)
                ))
                
                # إرجاع رسالة نجاح تتضمن التفاعل العشوائي
                return True, f"✅ تمت مشاهدة الستوري وتفاعل ({chosen_reaction}) من {session['phone_number']}"
                
            except Exception as reaction_error:
                # إذا فشل التفاعل، نعتبر المشاهدة ناجحة (لأن المهم هو "الفتح")
                logger.warning(f"تفاعل فاشل للستوري {session['phone_number']}: {reaction_error}")
                return True, f"✅ تمت مشاهدة الستوري من {session['phone_number']}"
                
        except Exception as e:
            return False, f"❌ فشل: {str(e)[:80]}"
        finally:
            await client.disconnect()
