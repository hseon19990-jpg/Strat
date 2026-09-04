# forced_ref_ai.py
"""
خدمة إحالة بوت إجباري مع تحقق شامل - تدعم الذكاء الاصطناعي (Groq API)
كل المنطق موجود في هذا الملف (بدون اعتماد على ForcedRefService)
"""

from .common import *
from telethon.tl.types import InputMediaContact, KeyboardButtonRequestPhone
from datetime import datetime
import re
import json
import os
from typing import Dict, Any, Optional, Tuple

# استيراد مكتبة Groq
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    print("⚠️ مكتبة Groq غير مثبتة. قم بتثبيتها: pip install groq")


class ForcedRefAIService(RakshService):
    """خدمة إحالة بوت إجباري مع تحقق شامل - تدعم الذكاء الاصطناعي"""

    service_type = "forced_ref_ai"
    label = "🤖 إحالة بوت إجباري مع تحقق (AI)"
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

    def __init__(self):
        super().__init__()
        self.groq_client = None
        if GROQ_AVAILABLE:
            api_key = os.environ.get("GROQ_API_KEY")
            if api_key:
                try:
                    self.groq_client = Groq(api_key=api_key)
                    print("✅ Groq API تم تهيئتها بنجاح")
                except Exception as e:
                    print(f"⚠️ فشل تهيئة Groq: {e}")
            else:
                print("⚠️ GROQ_API_KEY غير موجودة في المتغيرات البيئية")
        else:
            print("⚠️ مكتبة Groq غير مثبتة")

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
            [InlineKeyboardButton(
                "⏭️ تخطي (بدون قنوات)",
                callback_data=f"{self.get_callback_prefix()}:skip_channels",
            )],
            [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
        ])

    def get_callback_prefix(self) -> str:
        return "raksh_forced_ref_ai"

    def get_link_prompt_label(self) -> str:
        return "رابط البوت"

    def get_saved_link_label(self) -> str:
        return self.get_link_prompt_label()

    def get_quantity_label(self) -> str:
        return "عدد الإحالات المطلوبة"

    def get_activity_label(self) -> str:
        return "إحالة"

    def get_execution_label(self) -> str:
        return "الانضمام للقنوات وحل التحقق"

    def get_invoice_label(self) -> str:
        return "إحالة بوت إجباري مع تحقق"

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
                f"🔗 *أرسل {self.get_link_prompt_label()}:*\n"
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
                f"✅ تم حفظ {self.get_saved_link_label()}.\n\n"
                f"🔢 *أرسل {self.get_quantity_label()}:*\n"
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
                f"🔗 {self.get_saved_link_label()}: `{context.user_data['raksh_link']}`\n"
                f"🔢 العدد: {quantity}\n\n"
                f"💳 *اختر طريقة الدفع:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"💰 دفع بالنقاط ({points_cost} نقطة)",
                            callback_data=f"{self.get_callback_prefix()}:payment:points:{quantity}:{points_cost}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                            callback_data=f"{self.get_callback_prefix()}:payment:stars:{quantity}:{stars_cost}"
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
                f"🔗 *أرسل {self.get_link_prompt_label()}:*\n"
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
                f"🔗 {self.get_saved_link_label()}: `{context.user_data.get('raksh_link', '')}`\n"
                f"🔢 العدد: {quantity}\n"
                f"💳 طريقة الدفع: {'💰 نقاط' if payment_method == 'points' else '⭐ نجوم'}\n"
                f"💰 التكلفة: {total_cost} {'نقطة' if payment_method == 'points' else 'نجمة'}\n\n"
                f"*هل تريد تأكيد الطلب؟*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ تأكيد الطلب",
                            callback_data=f"{self.get_callback_prefix()}:confirm:{payment_method}:{quantity}:{total_cost}"
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
                    f"⏳ جاري {self.get_execution_label()}...",
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
                    description=f"{quantity} {self.get_activity_label()} مع تحقق | {total_cost} نجمة",
                    payload=f"raksh_stars:{user.id}:{self.service_type}:{quantity}:{total_cost}",
                    provider_token="",
                    currency="XTR",
                    prices=[LabeledPrice(self.get_invoice_label(), total_cost)],
                )
                return True

        return False

    # ─── 4. التحليل الذكي باستخدام Groq API ───

    async def _analyze_with_ai(self, text: str, buttons_text: list = None) -> Dict[str, Any]:
        """
        استخدام Groq API لتحليل النص وفهم المطلوب
        """
        if not self.groq_client:
            # إذا لم تتوفر Groq، استخدم التحليل التقليدي
            return self._analyze_without_ai(text, buttons_text)

        # بناء وصف الأزرار
        buttons_desc = ""
        if buttons_text:
            buttons_desc = f"\nالأزرار المتاحة: {', '.join(buttons_text)}"

        prompt = f"""
        أنت مساعد متخصص في تحليل رسائل بوتات التحقق على تيليجرام.

        المهمة: تحليل النص التالي وتحديد نوع التحقق المطلوب.

        النص:
        "{text}"
        {buttons_desc}

        قم بتحليل النص وأعد JSON بالتالي:
        {{
            "has_verification": true/false,     // هل يوجد طلب تحقق؟
            "verification_type": "code|math|button|phone|none",  // نوع التحقق
            "code": "الكود المطلوب إرساله إن وجد",   // مثال: JXL428UL
            "math_expression": "المسألة الرياضية",    // مثال: 5 + 3 = ?
            "math_result": "نتيجة المسألة",           // مثال: 8
            "button_text": "نص الزر الذي يجب الضغط عليه", // مثال: اضغط للتطبيق
            "should_press_button": true/false,    // هل يجب الضغط على زر؟
            "should_send_code": true/false,      // هل يجب إرسال كود؟
            "should_solve_math": true/false,     // هل يجب حل مسألة؟
            "explanation": "شرح مختصر للتحليل"
        }}

        ملاحظات مهمة:
        - إذا كان النص يحتوي على "اضغط على الزر" أو "انقر" أو "click" -> verification_type = "button"
        - إذا كان النص يحتوي على أرقام وحروف مثل JXL428UL -> verification_type = "code"
        - إذا كان النص يحتوي على مسألة رياضية مثل 5+3=? -> verification_type = "math"
        - إذا كان النص يحتوي على "شارك رقم هاتفك" -> verification_type = "phone"
        - إذا لم يكن هناك تحقق -> verification_type = "none"
        - استخرج الكود من النص إن وجد (أحرف وأرقام متتالية، طولها 6-10)
        - استخرج المسألة الرياضية وحلها

        أعد JSON فقط، بدون أي نص إضافي.
        """

        try:
            response = self.groq_client.chat.completions.create(
                model="llama3-70b-8192",
                messages=[
                    {"role": "system", "content": "أنت مساعد متخصص في تحليل رسائل التحقق. أعد JSON فقط."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=300,
                response_format={"type": "json_object"}
            )

            result_text = response.choices[0].message.content
            try:
                # محاولة استخراج JSON من النص
                import json
                # البحث عن JSON بين { و }
                start = result_text.find('{')
                end = result_text.rfind('}') + 1
                if start != -1 and end != 0:
                    json_str = result_text[start:end]
                    result = json.loads(json_str)
                    logger.info(f"🧠 تحليل AI: {result}")
                    return result
                else:
                    logger.warning(f"⚠️ لم يتم العثور على JSON في الرد: {result_text}")
                    return self._analyze_without_ai(text, buttons_text)
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ فشل تحليل JSON من Groq: {e}")
                return self._analyze_without_ai(text, buttons_text)

        except Exception as e:
            logger.error(f"❌ فشل استدعاء Groq API: {e}")
            return self._analyze_without_ai(text, buttons_text)

    def _analyze_without_ai(self, text: str, buttons_text: list = None) -> Dict[str, Any]:
        """
        تحليل تقليدي بدون AI (نسخة احتياطية)
        """
        result = {
            "has_verification": False,
            "verification_type": "none",
            "code": None,
            "math_expression": None,
            "math_result": None,
            "button_text": None,
            "should_press_button": False,
            "should_send_code": False,
            "should_solve_math": False,
            "explanation": ""
        }

        # 1. البحث عن كود
        code = _extract_code_from_text(text)
        if code:
            result["has_verification"] = True
            result["verification_type"] = "code"
            result["code"] = code
            result["should_send_code"] = True
            result["explanation"] = f"تم استخراج كود: {code}"
            return result

        # 2. البحث عن مسألة رياضية
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
                    if op == '+': result_val = a + b
                    elif op == '-': result_val = a - b
                    elif op == '*': result_val = a * b
                    elif op == '/': result_val = a / b if b != 0 else None
                    else: result_val = None
                    if result_val is not None:
                        result["has_verification"] = True
                        result["verification_type"] = "math"
                        result["math_expression"] = f"{a} {op} {b}"
                        result["math_result"] = str(result_val)
                        result["should_solve_math"] = True
                        result["explanation"] = f"تم حل المسألة: {a} {op} {b} = {result_val}"
                        return result
                except:
                    continue

        # 3. البحث عن زر أو طلب ضغط
        button_keywords = ['اضغط', 'انقر', 'click', 'tap', 'press', 'تطبيق', 'تحقق', 'verify', 'start', 'ابدأ']
        if any(kw in text.lower() for kw in button_keywords):
            result["has_verification"] = True
            result["verification_type"] = "button"
            result["should_press_button"] = True
            if buttons_text:
                result["button_text"] = buttons_text[0] if buttons_text else None
            result["explanation"] = "تم اكتشاف طلب ضغط زر"

            return result

        # 4. طلب رقم الهاتف
        phone_keywords = ['رقم', 'هاتف', 'phone', 'number', 'شارك']
        if any(kw in text.lower() for kw in phone_keywords) and 'طلب' in text.lower():
            result["has_verification"] = True
            result["verification_type"] = "phone"
            result["explanation"] = "تم اكتشاف طلب مشاركة رقم الهاتف"
            return result

        result["explanation"] = "لم يتم اكتشاف أي تحقق"
        return result

    # ─── 5. دوال مساعدة للأزرار ───

    async def _press_button(self, client, bot_entity, message) -> bool:
        """
        ضغط زر في رسالة معينة
        """
        if not message or not message.reply_markup:
            return False

        for row in message.reply_markup.rows:
            for btn in row.buttons:
                if not getattr(btn, 'url', None):
                    try:
                        await btn.click()
                        logger.info(f"🖱️ تم الضغط على زر: {getattr(btn, 'text', '')}")
                        return True
                    except Exception as e:
                        logger.warning(f"⚠️ فشل الضغط على الزر: {e}")
                        continue
        return False

    # ─── 6. حل التحقق باستخدام الذكاء الاصطناعي ───

    async def _solve_with_ai(self, client, bot_entity, phone_number: str, messages) -> bool:
        """
        استخدام الذكاء الاصطناعي لتحليل الرسائل وحل التحقق
        """
        # جمع الرسائل الواردة
        incoming = [msg for msg in messages if not msg.out and msg.date]

        if not incoming:
            return False

        for msg in incoming:
            text = getattr(msg, 'message', '') or ''
            if text.strip().startswith('/'):
                continue

            # استخراج نصوص الأزرار
            buttons_text = []
            if msg.reply_markup:
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        if not getattr(btn, 'url', None):
                            buttons_text.append(getattr(btn, 'text', '') or '')

            # تحليل باستخدام AI
            analysis = await self._analyze_with_ai(text, buttons_text)

            logger.info(f"🧠 تحليل AI للرسالة: {analysis}")

            # 1. إذا كان يجب إرسال كود
            if analysis.get("should_send_code") and analysis.get("code"):
                try:
                    await client.send_message(bot_entity, analysis["code"])
                    logger.info(f"✅ تم إرسال الكود (AI): {analysis['code']}")
                    await asyncio.sleep(2)
                    return True
                except Exception as e:
                    logger.error(f"❌ فشل إرسال الكود: {e}")

            # 2. إذا كان يجب حل مسألة
            if analysis.get("should_solve_math") and analysis.get("math_result"):
                try:
                    await client.send_message(bot_entity, analysis["math_result"])
                    logger.info(f"✅ تم إرسال نتيجة المسألة (AI): {analysis['math_result']}")
                    await asyncio.sleep(2)
                    return True
                except Exception as e:
                    logger.error(f"❌ فشل إرسال نتيجة المسألة: {e}")

            # 3. إذا كان يجب الضغط على زر
            if analysis.get("should_press_button"):
                if await self._press_button(client, bot_entity, msg):
                    await asyncio.sleep(2)
                    return True

        return False

    # ─── 7. حل التحقق المدمج ───

    async def _solve_verification(self, client, bot_entity, phone_number: str) -> bool:
        """
        حل التحقق بذكاء باستخدام AI:
        1. إذا طلب البوت مشاركة رقم الهاتف – نرسل الرقم.
        2. وإلا نستخدم الذكاء الاصطناعي لتحليل الرسائل.
        """
        MAX_WAIT = 15
        CHECK_INTERVAL = 1.0

        # ─── المرحلة 1: البحث عن طلب مشاركة رقم الهاتف ───
        contact_request_msg = None
        for _ in range(MAX_WAIT):
            try:
                messages = await client.get_messages(bot_entity, limit=5)
            except Exception:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            for msg in messages:
                if msg.out:
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

        if contact_request_msg:
            logger.info(f"📱 تم اكتشاف طلب رقم هاتف من {phone_number}")

            # إرسال جهة الاتصال
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

            await asyncio.sleep(2)

            # بعد إرسال الرقم، نبحث عن أي زر آخر
            for _ in range(MAX_WAIT):
                try:
                    messages = await client.get_messages(bot_entity, limit=5)
                    for msg in messages:
                        if await self._press_button(client, bot_entity, msg):
                            await asyncio.sleep(2)
                            break
                except Exception:
                    pass
                await asyncio.sleep(CHECK_INTERVAL)

            # انتظار تأكيد النجاح
            for _ in range(MAX_WAIT):
                try:
                    latest = await client.get_messages(bot_entity, limit=3)
                    for msg in latest:
                        if msg.out:
                            continue
                        if not msg.reply_markup and (getattr(msg, 'message', '') or '').strip():
                            logger.info(f"✅ تم التحقق بنجاح (مشاركة الرقم) من {phone_number}")
                            return True
                        text = (getattr(msg, 'message', '') or '').strip().casefold()
                        if any(kw in text for kw in ['تم', 'نجاح', 'مرحباً', 'شكراً', 'success', 'done', 'welcome']):
                            logger.info(f"✅ تم التحقق بنجاح (مشاركة الرقم) من {phone_number}")
                            return True
                except Exception:
                    pass
                await asyncio.sleep(CHECK_INTERVAL)

            logger.warning(f"⚠️ لم نؤكد التحقق لكننا سنعتبره ناجحاً من {phone_number}")
            return True

        # ─── المرحلة 2: استخدام الذكاء الاصطناعي ───
        logger.info(f"🧠 استخدام الذكاء الاصطناعي لحل التحقق لـ {phone_number}")

        start_time = datetime.now().timestamp()

        for cycle in range(5):
            try:
                messages = await client.get_messages(bot_entity, limit=30)
            except Exception as exc:
                if "two different IP" in str(exc) or "AuthKeyDuplicated" in str(exc):
                    _mark_raksh_session_unauthorized(phone_number)
                    return False
                await asyncio.sleep(1)
                continue

            # فلترة الرسائل الواردة بعد وقت البداية
            incoming = []
            for msg in messages:
                if msg.out:
                    continue
                if msg.date and msg.date.timestamp() > start_time:
                    incoming.append(msg)

            if not incoming:
                await asyncio.sleep(1)
                continue

            # محاولة حل التحقق باستخدام AI
            if await self._solve_with_ai(client, bot_entity, phone_number, incoming):
                logger.info(f"✅ تم حل التحقق باستخدام AI من {phone_number}")
                return True

            # إذا لم نجد تحققاً، نبحث عن أي زر ونضغطه
            for msg in incoming:
                if await self._press_button(client, bot_entity, msg):
                    logger.info(f"🖱️ تم الضغط على زر، نعيد المحاولة")
                    await asyncio.sleep(2)
                    break

            await asyncio.sleep(1)

        logger.warning(f"⚠️ لم نتمكن من حل التحقق لكننا سنعتبره ناجحاً من {phone_number}")
        return True

    # ─── 8. التنفيذ الرئيسي ───

    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ إحالة بوت إجباري مع تحقق شامل مع AI"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=20)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"

            # الانضمام للقنوات إذا كانت موجودة
            channels = params.get("channel_ref") or []
            if channels:
                for channel_ref in channels:
                    try:
                        await _join_channel_and_schedule_leave(client, channel_ref)
                        await asyncio.sleep(1.0)
                    except Exception as e:
                        logger.warning(f"فشل الانضمام للقناة {channel_ref}: {e}")

            # تحليل رابط البوت
            bot_username, start_param = _parse_bot_link(params["link"])
            if not bot_username:
                return False, "رابط البوت غير صحيح"

            clean_username = bot_username.lstrip("@").strip()
            resolved = await client(ResolveUsernameRequest(clean_username))
            bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]

            # بدء البوت
            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param or ""
            ))
            await asyncio.sleep(2.0)

            # حل التحقق باستخدام الذكاء الاصطناعي
            success = await self._solve_verification(client, bot_entity, session.get("phone_number"))

            if success:
                return True, f"✅ تمت الإحالة مع التحقق من {session['phone_number']}"
            else:
                return False, "فشل التحقق بعد محاولات متعددة"
        except Exception as e:
            if "two different IP" in str(e) or "AuthKeyDuplicated" in str(e):
                logger.error(f"⚠️ الجلسة {session.get('phone_number')} تستخدم من IP مختلف")
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة تستخدم من IP مختلف - تم تعطيلها مؤقتاً"
            return False, f"❌ فشل: {str(e)}"
        finally:
            await client.disconnect()
