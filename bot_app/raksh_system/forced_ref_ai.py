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
import re
import logging
from typing import List, Dict, Optional, Tuple, Any
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.messages import StartBotRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import (
    InputMediaContact,
    KeyboardButtonRequestPhone,
    KeyboardButtonUrl,
    KeyboardButtonCallback,
    KeyboardButton
)
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ParseMode
)
from telegram.ext import ContextTypes
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

# إعداد التسجيل
logger = logging.getLogger(__name__)


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
        min_delay=0.05,  # 50ms فقط
        max_delay=0.1    # 100ms فقط
    )

    # إعدادات السرعة الفائقة
    MAX_CONCURRENT = 12  # 12 حساب متوازي
    MAX_VERIFICATION_ATTEMPTS = 7  # 7 محاولات لحل التحقق
    REQUEST_TIMEOUT = 2  # مهلة الطلب بالثواني
    BATCH_SIZE = 12  # حجم الدفعة
    RETRY_DELAY = 0.5  # تأخير بين المحاولات

    def __init__(self):
        """تهيئة الخدمة"""
        self._active_clients = {}
        self._session_pool = {}
        self._executor = ThreadPoolExecutor(max_workers=12)
        self._stats = {
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'last_batch_time': None
        }

    # ─── دوال مساعدة ───

    def get_service_type(self) -> str:
        """إرجاع نوع الخدمة"""
        return self.service_type

    def get_service_name(self) -> str:
        """إرجاع اسم الخدمة"""
        return self.label

    def get_price_points(self) -> int:
        """إرجاع سعر النقاط"""
        return self.config.price_points

    def get_price_stars(self) -> int:
        """إرجاع سعر النجوم"""
        return self.config.price_stars

    def get_rate_text(self, currency: str) -> str:
        """الحصول على نص السعر"""
        if currency == "points":
            return f"{self.config.price_points} نقطة"
        else:
            return f"{self.config.price_stars} نجمة"

    def get_total(self, quantity: int, currency: str) -> int:
        """حساب التكلفة الكلية"""
        if currency == "points":
            return quantity * self.config.price_points
        else:
            return quantity * self.config.price_stars

    def get_request_limit(self, user_id: int) -> int:
        """الحصول على الحد الأقصى للطلبات"""
        # يمكن تعديل هذا حسب نظام النقاط الخاص بك
        return 100  # حد أقصى 100 حساب

    # ─── تجاوز دالة جلب الجلسات ───
    def get_sessions(self) -> List[Dict]:
        """
        جلب جميع الحسابات النشطة
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

    # ─── دوال البداية ───
    def get_initial_state(self) -> str:
        """الحالة الأولية"""
        return "channel"

    def get_start_message(self) -> str:
        """رسالة البداية"""
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
        """لوحة المفاتيح للبداية"""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ تخطي (بدون قنوات)", callback_data="raksh_forced_ref_ai:skip_channels")],
            [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
        ])

    def get_link_instruction(self) -> str:
        """تعليمات الرابط"""
        return "@BotUsername start123  أو  t.me/BotUsername?start=123"

    def validate_link(self, value: str) -> Optional[str]:
        """التحقق من صحة الرابط"""
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

    # ─── معالجة النصوص ───
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, user: Dict, state: str, is_own: bool) -> bool:
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

    # ─── معالجة الأزرار ───
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, query: Any, data_parts: List[str], user: Dict, is_own: bool) -> bool:
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

    # ─── التنفيذ المتوازي الفائق ───
    
    async def execute_batch(self, sessions: List[Dict], params: Dict) -> List[Tuple[bool, str]]:
        """
        تنفيذ دفعة كاملة بسرعة فائقة
        جميع العمليات تعمل بالتوازي الكامل
        """
        self._stats['last_batch_time'] = datetime.now()
        
        tasks = [self._process_session(session, params) for session in sessions]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append((False, f"خطأ: {str(result)}"))
                self._stats['failed'] += 1
            else:
                final_results.append(result)
                if result[0]:  # نجاح
                    self._stats['successful'] += 1
                else:
                    self._stats['failed'] += 1
                
            self._stats['total_processed'] += 1
        
        return final_results

    async def _process_session(self, session: Dict, params: Dict) -> Tuple[bool, str]:
        """
        معالجة حساب واحد بسرعة فائقة
        """
        try:
            client = TelegramClient(
                StringSession(session["session_string"]),
                int(TELEGRAM_API_ID),
                TELEGRAM_API_HASH
            )
            
            await asyncio.wait_for(client.connect(), timeout=2)
            
            try:
                if not await asyncio.wait_for(client.is_user_authorized(), timeout=1):
                    return False, "جلسة غير صالحة"

                # الانضمام للقنوات
                channels = params.get("channel_ref") or []
                if channels:
                    for channel_ref in channels[:2]:
                        try:
                            await self._quick_join(client, channel_ref)
                        except:
                            pass

                # تحليل رابط البوت
                bot_username, start_param = _parse_bot_link(params["link"])
                if not bot_username:
                    return False, "رابط غير صحيح"

                clean_username = bot_username.lstrip("@").strip()
                
                try:
                    resolved = await client(ResolveUsernameRequest(clean_username))
                    bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]
                except:
                    return False, "فشل حل البوت"

                # بدء البوت
                try:
                    await client(StartBotRequest(
                        bot=bot_entity,
                        peer=bot_entity,
                        start_param=start_param or ""
                    ))
                except:
                    pass

                # حل التحقق - 7 محاولات
                success = await self._verify_with_attempts(client, bot_entity, session.get("phone_number"))
                
                if success:
                    return True, f"✅ تم من {session['phone_number']}"
                else:
                    return False, "فشل التحقق"

            finally:
                try:
                    await client.disconnect()
                except:
                    pass

        except Exception as e:
            if "two different IP" in str(e) or "AuthKeyDuplicated" in str(e):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "جلسة غير صالحة"
            return False, f"خطأ: {str(e)}"

    async def _verify_with_attempts(self, client: TelegramClient, bot_entity: Any, phone_number: str) -> bool:
        """
        حل التحقق مع 7 محاولات
        يتوقف فوراً عند أول نجاح
        """
        for attempt in range(self.MAX_VERIFICATION_ATTEMPTS):
            try:
                # التحقق من النجاح أولاً
                if await self._check_success(client, bot_entity):
                    return True
                
                # جلب الرسائل
                messages = await client.get_messages(bot_entity, limit=5)
                
                # البحث عن رسالة تحقق
                verification_msg = None
                for msg in messages:
                    if msg.out:
                        continue
                    
                    msg_text = getattr(msg, 'message', '') or ''
                    
                    # التحقق من النجاح
                    if any(kw in msg_text.casefold() for kw in ['تم', 'نجاح', 'مرحباً', 'welcome', 'success', 'done', 'مبروك', 'تم التسجيل']):
                        return True
                    
                    # البحث عن رسالة تحقق
                    if msg.reply_markup or any(kw in msg_text for kw in ['أرسل', 'اكتب', 'اضغط', 'اختر', 'تحقق', 'تأكيد', 'كود', 'رمز', '؟']):
                        verification_msg = msg
                        break
                
                if verification_msg is None:
                    # لا يوجد تحقق - نجاح
                    return True
                
                # محاولة حل التحقق
                solved = await self._solve_verification(client, verification_msg, bot_entity)
                
                if solved:
                    # نجحنا في حل التحقق - نتحقق من النجاح
                    await asyncio.sleep(0.5)  # انتظار قصير للتحقق
                    if await self._check_success(client, bot_entity):
                        return True
                    # إذا لم نتأكد، نستمر في المحاولات
                
                # تأخير قصير بين المحاولات (فقط 0.5 ثانية)
                if attempt < self.MAX_VERIFICATION_ATTEMPTS - 1:
                    await asyncio.sleep(self.RETRY_DELAY)
                    
            except Exception as e:
                logger.warning(f"خطأ في محاولة التحقق {attempt + 1}: {e}")
                await asyncio.sleep(self.RETRY_DELAY)
        
        # فحص أخير
        return await self._check_success(client, bot_entity)

    async def _check_success(self, client: TelegramClient, bot_entity: Any) -> bool:
        """فحص نجاح التحقق"""
        try:
            messages = await client.get_messages(bot_entity, limit=5)
            for msg in messages:
                if msg.out:
                    continue
                msg_text = (getattr(msg, 'message', '') or '').casefold()
                if any(kw in msg_text for kw in ['تم', 'نجاح', 'مرحباً', 'welcome', 'success', 'done', 'مبروك', 'تم التسجيل']):
                    return True
        except:
            pass
        return False

    async def _solve_verification(self, client: TelegramClient, msg: Any, bot_entity: Any) -> bool:
        """محاولة حل التحقق - ترجع True إذا نجحت"""
        text = getattr(msg, 'message', '') or ''
        
        # 1. استخراج الكود
        code = self._extract_code(text)
        if code:
            try:
                await client.send_message(bot_entity, code)
                return True
            except:
                pass

        # 2. حل المسألة الرياضية
        math_result = self._solve_math(text)
        if math_result:
            try:
                await client.send_message(bot_entity, math_result)
                return True
            except:
                pass

        # 3. الضغط على الأزرار
        if msg.reply_markup:
            try:
                buttons = []
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        if not getattr(btn, 'url', None):
                            buttons.append(btn)
                
                if buttons:
                    target_btn = None
                    
                    # البحث عن الإيموجي المطلوب
                    emoji_pattern = re.compile(
                        "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E0-\U0001F1FF]"
                    )
                    found_emojis = emoji_pattern.findall(text)
                    if found_emojis:
                        target_emoji = found_emojis[-1]
                        for btn in buttons:
                            if target_emoji in (getattr(btn, 'text', '') or ''):
                                target_btn = btn
                                break
                    
                    # البحث عن زر التحقق
                    if not target_btn:
                        for btn in buttons:
                            btn_text = (getattr(btn, 'text', '') or '').casefold()
                            if any(kw in btn_text for kw in ['تحقق', 'verify', 'confirm', 'تم', '✅', '✔']):
                                target_btn = btn
                                break
                    
                    # إذا لم نجد، اضغط أول زر
                    if not target_btn:
                        target_btn = buttons[0]
                    
                    if target_btn:
                        await target_btn.click()
                        return True
                        
            except:
                pass

        # 4. إرسال نص
        if any(kw in text.casefold() for kw in ['أرسل', 'اكتب', 'type', 'send']):
            try:
                patterns = [
                    r'(?:أرسل|اكتب|type|send)\s+["\']?([^"\'\n]+)["\']?',
                    r'(?:أرسل|اكتب|type|send)\s*:\s*([^\n]+)',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        answer = match.group(1).strip()
                        answer = answer.split('\n')[0].strip()
                        answer = answer.split('؟')[0].strip()
                        
                        if answer and len(answer) > 1:
                            await client.send_message(bot_entity, answer)
                            return True
            except:
                pass

        return False

    async def _quick_join(self, client: TelegramClient, channel_ref: str):
        """انضمام سريع للقناة"""
        try:
            await client(JoinChannelRequest(channel_ref))
        except:
            try:
                entity = await client.get_entity(channel_ref)
                await client(JoinChannelRequest(entity))
            except:
                pass

    def _extract_code(self, text: str) -> Optional[str]:
        """استخراج الكود من النص"""
        patterns = [
            r'\b(\d{4,8})\b',  # أي رقم 4-8 خانات
            r'(\d{4,8})',  # أي رقم
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    def _solve_math(self, text: str) -> Optional[str]:
        """حل المسألة الرياضية"""
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

    # ─── دوال إحصائية ───

    def get_stats(self) -> Dict:
        """الحصول على الإحصائيات"""
        return self._stats.copy()

    def reset_stats(self):
        """إعادة تعيين الإحصائيات"""
        self._stats = {
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'last_batch_time': None
        }

    # ─── التنفيذ الرئيسي ───
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ حساب واحد"""
        return await self._process_session(session, params)

    # ─── دوال مساعدة إضافية ───

    def is_available(self) -> bool:
        """التحقق من توفر الخدمة"""
        try:
            sessions = self.get_sessions()
            return len(sessions) > 0
        except:
            return False

    def get_available_count(self) -> int:
        """الحصول على عدد الحسابات المتاحة"""
        try:
            sessions = self.get_sessions()
            return len(sessions)
        except:
            return 0

    async def cleanup(self):
        """تنظيف الموارد"""
        try:
            for client in self._active_clients.values():
                try:
                    await client.disconnect()
                except:
                    pass
            self._active_clients.clear()
            self._session_pool.clear()
        except:
            pass
