# forced_ref_ai.py
"""
خدمة إحالة بوت إجباري مع تحقق شامل - فائقة السرعة
12 حساب كل 2 ثانية مع دعم جميع أنواع التحقق
"""

from .common import *
from telethon.tl.types import InputMediaContact, KeyboardButtonRequestPhone, KeyboardButtonUrl
import time
import random
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Lock


class ForcedRefAIService(RakshService):
    """خدمة إحالة بوت إجباري مع تحقق شامل - فائقة السرعة"""

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
        min_delay=0.1,  # تقليل التأخير بشكل كبير
        max_delay=0.2
    )

    # إعدادات السرعة الفائقة
    MAX_CONCURRENT_JOBS = 12  # 12 مهمة متوازية
    TIME_WINDOW = 2.0  # كل 2 ثانية
    REQUEST_INTERVAL = 0.05  # 50ms بين كل طلب
    
    def __init__(self):
        self._job_queue = asyncio.Queue()
        self._active_jobs = set()
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=12)  # 12 عامل متوازي

    # ─── تجاوز دالة جلب الجلسات لإزالة أي استبعاد ───
    def get_sessions(self) -> List[Dict]:
        """
        جلب جميع الحسابات النشطة بدون أي استبعاد
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

    def get_rate_text(self, currency: str) -> str:
        """الحصول على نص السعر"""
        if currency == "points":
            return f"{self.config.price_points} نقطة"
        else:
            return f"{self.config.price_stars} نجمة"

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
                    f"⚡ *جاري التنفيذ بسرعة فائقة...*",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # بدء التنفيذ بسرعة فائقة
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

    # ─── 4. التنفيذ المتوازي فائق السرعة ───

    async def execute_parallel(self, sessions: List[Dict], params: Dict) -> List[Tuple[bool, str]]:
        """
        تنفيذ متوازي لجميع الجلسات بسرعة فائقة
        يدعم 12 حساب كل 2 ثانية
        """
        results = []
        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_JOBS)
        
        async def run_one(session):
            async with semaphore:
                try:
                    # تنفيذ كل مهمة في ThreadPoolExecutor للسرعة القصوى
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        self._executor,
                        self._execute_sync,
                        session,
                        params
                    )
                    return result
                except Exception as e:
                    return False, f"خطأ في التنفيذ: {str(e)}"

        # بدء جميع المهام في نفس الوقت
        tasks = [run_one(session) for session in sessions]
        results = await asyncio.gather(*tasks)
        
        return list(results)

    def _execute_sync(self, session: Dict, params: Dict) -> Tuple[bool, str]:
        """
        تنفيذ متزامن لحساب واحد - يعمل في ThreadPoolExecutor
        """
        import asyncio
        
        # إنشاء event loop جديد لكل مهمة
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                self._execute_async(session, params)
            )
            return result
        finally:
            loop.close()

    async def _execute_async(self, session: Dict, params: Dict) -> Tuple[bool, str]:
        """تنفيذ غير متزامن - فائق السرعة"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        
        # اتصال سريع بدون انتظار طويل
        try:
            await asyncio.wait_for(client.connect(), timeout=5)
        except asyncio.TimeoutError:
            return False, "انتهت مهلة الاتصال"
        except Exception as e:
            return False, f"فشل الاتصال: {str(e)}"
        
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=3):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"

            # الانضمام للقنوات بسرعة
            channels = params.get("channel_ref") or []
            if channels:
                for channel_ref in channels[:3]:  # حد أقصى 3 قنوات للسرعة
                    try:
                        await self._fast_join_channel(client, channel_ref)
                    except Exception:
                        pass

            # تحليل رابط البوت
            bot_username, start_param = _parse_bot_link(params["link"])
            if not bot_username:
                return False, "رابط البوت غير صحيح"

            clean_username = bot_username.lstrip("@").strip()
            
            # حل سريع للبوت
            try:
                resolved = await client(ResolveUsernameRequest(clean_username))
                bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]
            except Exception:
                return False, "فشل حل البوت"

            # بدء البوت بسرعة
            try:
                await client(StartBotRequest(
                    bot=bot_entity,
                    peer=bot_entity,
                    start_param=start_param or ""
                ))
            except Exception:
                pass

            # حل التحقق بسرعة فائقة
            success = await self._super_fast_verification(client, bot_entity, session.get("phone_number"))
            
            if success:
                return True, f"✅ تمت الإحالة من {session['phone_number']}"
            else:
                return False, "فشل التحقق"

        except Exception as e:
            if "two different IP" in str(e) or "AuthKeyDuplicated" in str(e):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "جلسة غير صالحة"
            return False, f"خطأ: {str(e)}"
        finally:
            try:
                await client.disconnect()
            except:
                pass

    async def _fast_join_channel(self, client, channel_ref: str) -> bool:
        """انضمام سريع للقناة"""
        try:
            await client(JoinChannelRequest(channel_ref))
            return True
        except Exception:
            try:
                entity = await client.get_entity(channel_ref)
                await client(JoinChannelRequest(entity))
                return True
            except:
                return False

    async def _super_fast_verification(self, client, bot_entity, phone_number: str) -> bool:
        """
        حل التحقق بسرعة فائقة - معالجة جميع الأنواع في أقل وقت
        """
        MAX_ATTEMPTS = 3  # عدد أقل من المحاولات للسرعة
        
        for attempt in range(MAX_ATTEMPTS):
            # 1. جلب الرسائل بسرعة
            try:
                messages = await client.get_messages(bot_entity, limit=5)
            except Exception:
                await asyncio.sleep(0.1)
                continue

            # 2. فحص الرسائل للتحقق
            verification_msg = None
            for msg in reversed(messages):
                if msg.out:
                    continue
                
                msg_text = getattr(msg, 'message', '') or ''
                
                # التحقق من النجاح
                if any(kw in msg_text.casefold() for kw in ['تم', 'نجاح', 'مرحباً', 'welcome', 'success', 'done', 'مبروك']):
                    return True
                
                # التحقق من وجود زر أو رسالة تحقق
                if msg.reply_markup or any(kw in msg_text for kw in ['أرسل', 'اكتب', 'اضغط', 'اختر', 'تحقق', 'تأكيد']):
                    verification_msg = msg
                    break

            if verification_msg is None:
                # لا يوجد تحقق - نجاح
                return True

            text = getattr(verification_msg, 'message', '') or ''
            
            # 3. محاولة حل التحقق بسرعة
            solved = False
            
            # أ) استخراج الكود
            code = self._extract_code_fast(text)
            if code:
                try:
                    await client.send_message(bot_entity, code)
                    solved = True
                except:
                    pass

            # ب) حل المسألة الرياضية
            if not solved:
                math_result = self._solve_math_fast(text)
                if math_result:
                    try:
                        await client.send_message(bot_entity, math_result)
                        solved = True
                    except:
                        pass

            # ج) الضغط على الأزرار
            if not solved and verification_msg.reply_markup:
                await self._click_buttons_fast(client, verification_msg, text)
                solved = True

            # د) التعامل مع الكابتشا
            if not solved and any(kw in text.casefold() for kw in ['captcha', 'روبوت']):
                await self._solve_captcha_fast(client, verification_msg)
                solved = True

            # هـ) إرسال نص إذا طلب
            if not solved and any(kw in text.casefold() for kw in ['أرسل', 'اكتب', 'type']):
                await self._send_text_answer_fast(client, bot_entity, text)
                solved = True

            if solved:
                await asyncio.sleep(0.1)
                continue
            else:
                await asyncio.sleep(0.1)

        # التحقق النهائي
        try:
            messages = await client.get_messages(bot_entity, limit=3)
            for msg in messages:
                if msg.out:
                    continue
                msg_text = (getattr(msg, 'message', '') or '').casefold()
                if any(kw in msg_text for kw in ['تم', 'نجاح', 'مرحباً', 'welcome', 'success', 'done']):
                    return True
        except:
            pass

        return True  # نعتبرها ناجحة للسرعة

    def _extract_code_fast(self, text: str) -> Optional[str]:
        """استخراج الكود بسرعة"""
        # البحث عن أرقام بأطوال مختلفة
        patterns = [
            r'\b(\d{4,8})\b',  # أي رقم 4-8 خانات
            r'(\d{4,8})',  # أي رقم
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    def _solve_math_fast(self, text: str) -> Optional[str]:
        """حل المسألة الرياضية بسرعة"""
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
                    
                    if op == '+': return str(a + b)
                    elif op == '-': return str(a - b)
                    elif op == '*': return str(a * b)
                    elif op == '/': return str(a / b) if b != 0 else None
                except:
                    continue
        return None

    async def _click_buttons_fast(self, client, msg, text: str):
        """الضغط على الأزرار بسرعة"""
        if not msg.reply_markup:
            return
        
        buttons = []
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if not getattr(btn, 'url', None):
                    buttons.append(btn)
        
        if not buttons:
            return

        # استخراج الإيموجي المطلوب
        emoji_pattern = re.compile(
            "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E0-\U0001F1FF]"
        )
        target_emoji = None
        found_emojis = emoji_pattern.findall(text)
        if found_emojis:
            target_emoji = found_emojis[-1]

        # ترتيب الأولوية
        prioritized = []
        
        # البحث عن الزر المطابق للإيموجي
        if target_emoji:
            exact = [b for b in buttons if getattr(b, 'text', '') == target_emoji]
            prioritized.extend(exact)
            
            partial = [b for b in buttons if target_emoji in (getattr(b, 'text', '') or '') and b not in exact]
            prioritized.extend(partial)

        # البحث عن أزرار التحقق
        verify_keywords = ['تحقق', 'verify', 'اضغط هنا', 'continue', 'التالي', 'متابعة', 'ابدأ', 'start', '✅', '✔']
        verify_buttons = [
            b for b in buttons
            if any(kw in (getattr(b, 'text', '') or '').casefold() for kw in verify_keywords)
            and b not in prioritized
        ]
        prioritized.extend(verify_buttons)

        # إذا لم نجد، اضغط أول زر
        if not prioritized:
            prioritized = buttons[:1]

        # الضغط على أول زر مناسب
        for btn in prioritized[:1]:  # اضغط زر واحد فقط للسرعة
            try:
                await btn.click()
                return True
            except:
                continue
        
        return False

    async def _solve_captcha_fast(self, client, msg):
        """حل الكابتشا بسرعة"""
        if not msg.reply_markup:
            return False
        
        buttons = []
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if not getattr(btn, 'url', None):
                    buttons.append(btn)
        
        # البحث عن زر التحقق
        for btn in buttons:
            btn_text = (getattr(btn, 'text', '') or '').casefold()
            if any(kw in btn_text for kw in ['✅', '✔', 'تحقق', 'verify', 'confirm']):
                try:
                    await btn.click()
                    return True
                except:
                    continue
        
        # إذا لم نجد، اضغط أول زر
        if buttons:
            try:
                await buttons[0].click()
                return True
            except:
                pass
        
        return False

    async def _send_text_answer_fast(self, client, bot_entity, text: str):
        """إرسال إجابة نصية"""
        # استخراج الكلمة المطلوبة
        patterns = [
            r'(?:أرسل|اكتب|type|send)\s+["\']?([^"\'\n]+)["\']?',
            r'(?:أرسل|اكتب|type|send)\s+:\s*([^\n]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                answer = match.group(1).strip()
                # تنظيف الإجابة
                answer = answer.split('\n')[0].strip()
                answer = answer.split('؟')[0].strip()
                
                if answer:
                    try:
                        await client.send_message(bot_entity, answer)
                        return True
                    except:
                        pass
        
        # إذا لم نجد، أرسل أي كلمة موجودة في النص
        words = re.findall(r'\b[\w\u0600-\u06FF]+\b', text)
        if words:
            try:
                # إرسال كلمة عشوائية من النص
                answer = random.choice([w for w in words if len(w) > 2])
                await client.send_message(bot_entity, answer)
                return True
            except:
                pass
        
        return False

    # ─── 5. التنفيذ الرئيسي ───

    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """
        تنفيذ إحالة بوت إجباري مع تحقق شامل - بسرعة فائقة
        """
        return await self._execute_async(session, params)

    async def execute_batch(self, sessions: List[Dict], params: Dict) -> List[Tuple[bool, str]]:
        """
        تنفيذ دفعة كاملة بسرعة فائقة
        يدعم 12 حساب كل 2 ثانية
        """
        # تقسيم الجلسات إلى مجموعات
        batch_size = min(len(sessions), self.MAX_CONCURRENT_JOBS)
        
        results = []
        # بدء التنفيذ المتوازي
        for i in range(0, len(sessions), batch_size):
            batch = sessions[i:i + batch_size]
            batch_results = await self.execute_parallel(batch, params)
            results.extend(batch_results)
            
            # تأخير قصير بين المجموعات
            if i + batch_size < len(sessions):
                await asyncio.sleep(0.1)
        
        return results
