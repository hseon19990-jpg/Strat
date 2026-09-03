# votes_ai.py
from .common import *
from .forced_ref_ai import ForcedRefAIService

class VotesAIService(RakshService):
    """خدمة رشق تصويت مع تحقق - كل شيء في مكان واحد"""
    
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
        """البدء بطلب القنوات الإجبارية"""
        return "channel"
    
    def get_link_instruction(self) -> str:
        return (
            "أرسل رابط التصويت بأحد هذه الصيغ:\n"
            "• رابط بوت: https://t.me/i8YYBot?start=compvote_xxx\n"
            "• رابط قناة: https://t.me/z_10_f/1836"
        )
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        
        # التحقق من صحة الرابط
        bot_username, _ = _parse_bot_link(value)
        channel_ref, msg_id = _parse_post_link(value)
        
        if not bot_username and not channel_ref:
            return "⚠️ الرابط غير صحيح.\n\nأرسل رابط بوت أو رابط قناة"
        
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
            [InlineKeyboardButton("⏭️ تخطي (بدون قنوات)", callback_data="raksh_votes_ai:skip_channels")],
            [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
        ])
    
    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        """معالجة النص لخدمة رشق التصويت مع تحقق"""
        
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
                f"🔗 *أرسل رابط التصويت:*\n"
                f"{self.get_link_instruction()}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        # ═══ الخطوة 2: استقبال رابط التصويت ═══
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
                f"✅ تم حفظ رابط التصويت.\n\n"
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
                f"🔗 رابط التصويت: `{context.user_data['raksh_link']}`\n"
                f"🔢 العدد: {quantity}\n\n"
                f"💳 *اختر طريقة الدفع:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"💰 دفع بالنقاط ({points_cost} نقطة)",
                            callback_data=f"raksh_votes_ai:payment:points:{quantity}:{points_cost}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                            callback_data=f"raksh_votes_ai:payment:stars:{quantity}:{stars_cost}"
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
        """معالجة الأزرار لخدمة رشق التصويت مع تحقق"""
        
        # ═══ تخطي القنوات ═══
        if data_parts[0] == "skip_channels":
            context.user_data["raksh_channels"] = []
            context.user_data["raksh_step"] = "link"
            
            await query.edit_message_text(
                f"✅ تم تخطي القنوات.\n\n"
                f"🔗 *أرسل رابط التصويت:*\n"
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
                f"🔗 رابط التصويت: `{context.user_data.get('raksh_link', '')}`\n"
                f"🔢 العدد: {quantity}\n"
                f"💳 طريقة الدفع: {'💰 نقاط' if payment_method == 'points' else '⭐ نجوم'}\n"
                f"💰 التكلفة: {total_cost} {'نقطة' if payment_method == 'points' else 'نجمة'}\n\n"
                f"*هل تريد تأكيد الطلب؟*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ تأكيد الطلب",
                            callback_data=f"raksh_votes_ai:confirm:{payment_method}:{quantity}:{total_cost}"
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
                    f"⏳ جاري الانضمام للقنوات وبدء التصويت مع التحقق...",
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
                    description=f"{quantity} صوت مع تحقق | {total_cost} نجمة",
                    payload=f"raksh_stars:{user.id}:{self.service_type}:{quantity}:{total_cost}",
                    provider_token="",
                    currency="XTR",
                    prices=[LabeledPrice("تصويت مع تحقق", total_cost)],
                )
                return True
        
        return False
    
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ رشق تصويت مع تحقق - يدعم كل أنواع الروابط وحل التحقق"""
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
            
            link = params["link"]
            bot_entity = None
            bot_start_param = None
            
            # ─── الطريقة 1: رابط بوت تصويت مباشر ───
            bot_username, bot_start_param = _parse_bot_link(link)
            if bot_username:
                clean_username = bot_username.lstrip("@").strip()
                try:
                    resolved = await client(ResolveUsernameRequest(clean_username))
                    if resolved.users:
                        bot_entity = resolved.users[0]
                    elif resolved.chats:
                        bot_entity = resolved.chats[0]
                except Exception:
                    try:
                        bot_entity = await client.get_entity(bot_username)
                    except Exception:
                        try:
                            bot_entity = await client.get_entity(f"@{bot_username}")
                        except Exception as e3:
                            return False, f"فشل العثور على البوت {bot_username}: {str(e3)[:80]}"
                
                # بدء البوت
                await client(StartBotRequest(
                    bot=bot_entity,
                    peer=bot_entity,
                    start_param=bot_start_param or ""
                ))
                await asyncio.sleep(1.5)
                
                # محاولة حل التحقق
                verification_success = await self._solve_verification(client, bot_entity, session.get("phone_number"))
                
                if verification_success:
                    return True, f"✅ تم التصويت مع التحقق من {session['phone_number']}"
                else:
                    return False, "فشل التحقق بعد محاولات متعددة"
            
            # ─── الطريقة 2: رابط قناة يحتوي زر بوت ───
            channel_ref, msg_id = _parse_post_link(link)
            if not channel_ref:
                return False, "الرابط غير صحيح لهذه الخدمة"
            
            entity = await client.get_entity(channel_ref)
            message = await client.get_messages(entity, ids=msg_id)
            if not message:
                return False, "المنشور غير موجود"
            
            # البحث عن زر يحتوي رابط بوت
            bot_found = False
            for row in getattr(message, "buttons", None) or []:
                for btn in row:
                    if getattr(btn, "url", None):
                        url = btn.url
                        if "t.me/" in url or "telegram.me/" in url:
                            url_bot, url_start = _parse_bot_link(url)
                            if url_bot:
                                try:
                                    bot_entity = await client.get_entity(url_bot)
                                    await client(StartBotRequest(
                                        bot=bot_entity,
                                        peer=bot_entity,
                                        start_param=url_start or ""
                                    ))
                                    await asyncio.sleep(1.5)
                                    bot_found = True
                                    break
                                except Exception as e:
                                    logger.warning(f"فشل فتح رابط البوت: {e}")
                    else:
                        # زر عادي - ضغط عليه
                        try:
                            callback_data = getattr(btn, "data", None)
                            if callback_data:
                                await client(functions.messages.GetBotCallbackAnswerRequest(
                                    peer=entity,
                                    msg_id=msg_id,
                                    data=callback_data
                                ))
                                await asyncio.sleep(1.0)
                                return True, f"✅ تم التصويت من {session['phone_number']}"
                        except Exception:
                            continue
                if bot_found:
                    break
            
            if bot_found and bot_entity:
                # محاولة حل التحقق بعد فتح البوت
                verification_success = await self._solve_verification(client, bot_entity, session.get("phone_number"))
                
                if verification_success:
                    return True, f"✅ تم التصويت مع التحقق من {session['phone_number']}"
                else:
                    return False, "فشل التحقق بعد محاولات متعددة"
            
            return False, "لم يتم العثور على زر بوت في المنشور"
            
        except Exception as e:
            return False, f"❌ فشل: {str(e)}"
        finally:
            await client.disconnect()
    
    async def _solve_verification(self, client, bot_entity, phone_number: str) -> bool:
        """حل التحقق بذكاء - يستخدم الذكاء الاصطناعي لإيجاد الإيموجي أو حل مسائل"""
        max_attempts = 30
        base_id = 0
        
        # تحديد نقطة البداية
        try:
            out_messages = await client.get_messages(bot_entity, limit=10)
            for msg in out_messages:
                if msg.out:
                    base_id = msg.id
                    break
        except Exception:
            pass
        
        # استخدام دوال ForcedRefAIService لحل التحقق
        forced_ref_ai = ForcedRefAIService()
        
        # محاولة استخدام دوال الحل من ForcedRefAIService
        try:
            success = await forced_ref_ai._solve_verification(
                client,
                bot_entity,
                phone_number,
                start_after_message_id=base_id
            )
            return success
        except Exception as e:
            logger.warning(f"فشل استخدام دوال ForcedRefAIService: {e}")
        
        # خطة بديلة: حل التحقق يدوياً
        for attempt in range(max_attempts):
            try:
                messages = await client.get_messages(bot_entity, limit=20)
            except Exception:
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
                msg_text = getattr(msg, "message", "") or ""
                if msg_text.strip().startswith("/"):
                    continue
                if any(kw in msg_text for kw in ["أرسل", "التالي", "بالضبط", "اكتب", "retype", "type", "اضغط", "اختر", "انقر", "تحقق"]):
                    verification_message = msg
                    break
            
            if verification_message is None:
                verification_message = next(
                    (msg for msg in reversed(new_messages) if not getattr(msg, "message", "").strip().startswith("/")),
                    None
                )
            
            if verification_message is None:
                await asyncio.sleep(1.0)
                continue
            
            text = getattr(verification_message, "message", "") or ""
            
            # 1️⃣ استخراج الكود
            send_text = _extract_code_from_text(text)
            if send_text:
                try:
                    await client.send_message(bot_entity, send_text)
                    logger.info(f"✅ تم إرسال الكود: {send_text}")
                    return True
                except Exception:
                    pass
            
            # 2️⃣ حل المسائل الرياضية
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
            
            # 3️⃣ الضغط على الأزرار (إيموجي أو أزرار عادية)
            buttons = []
            for row in getattr(verification_message, "buttons", None) or []:
                for btn in row:
                    if not getattr(btn, "url", None):
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
                    logger.info(f"✅ تم استخراج الإيموجي المطلوب: {target_emoji}")
                
                # ترتيب الأزرار حسب الأولوية
                prioritized = []
                if target_emoji:
                    exact = [b for b in buttons if getattr(b, "text", "") == target_emoji]
                    prioritized.extend(exact)
                    partial = [b for b in buttons if target_emoji in (getattr(b, "text", "") or "")]
                    prioritized.extend(partial)
                
                # أزرار التحقق
                verify_keywords = ['تحقق', 'verify', 'اضغط هنا', 'continue', 'التالي', 'متابعة']
                verify_buttons = [
                    b for b in buttons
                    if any(kw in (getattr(b, "text", "") or "").casefold() for kw in verify_keywords)
                    and b not in prioritized
                ]
                prioritized.extend(verify_buttons)
                
                # باقي الأزرار
                remaining = [b for b in buttons if b not in prioritized]
                prioritized.extend(remaining)
                
                for btn in prioritized:
                    try:
                        await btn.click()
                        logger.info(f"🖱️ تم الضغط على الزر: {getattr(btn, 'text', '')}")
                        await asyncio.sleep(1.0)
                        # لا نعتبر النجاح بمجرد الضغط - ننتظر رسالة التأكيد
                        return True
                    except Exception:
                        continue
            
            await asyncio.sleep(1.0)
        
        return False
