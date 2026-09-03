# forced_ref_ai.py
"""
خدمة إحالة بوت إجباري مع تحقق شامل - تدعم مشاركة الرقم والكود والمسائل والأزرار وإرسال ID
مع تحسينات السرعة ودعم جميع أنواع الأزرار
السلوك: يدخل الرابط ← يقرأ كل الرسائل الواردة ← يضغط زر التحقق المناسب ← يعيد القراءة ← يحل التحقق الجديد ← يتكرر
"""

from .common import *
from telethon.tl.types import (
    InputMediaContact,
    KeyboardButtonRequestPhone,
    KeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)


class ForcedRefAIService(RakshService):
    """خدمة إحالة بوت إجباري مع تحقق شامل - محسّن للسرعة"""

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
                    f"⏳ جاري الانضمام للقنوات وحل التحقق...",
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

    # ─── 4. دوال مساعدة محسّنة للسرعة ───

    def _extract_id_from_text(self, text: str) -> Optional[str]:
        """استخراج معرف مطلوب من النص (رقمي، @username، -100xxx) بسرعة"""
        match = re.search(r'(-?\d{5,})', text)
        if match:
            return match.group(1)
        match = re.search(r'@[\w_]+', text)
        if match:
            return match.group(0)
        match = re.search(r'\b(\d{4,})\b', text)
        if match:
            return match.group(1)
        return None

    def _solve_math(self, text: str) -> Optional[str]:
        """استخراج مسألة حسابية وحلها بسرعة"""
        patterns = [
            (r'(\d+)\s*([+\-*/])\s*(\d+)\s*=\s*\?', lambda a, op, b: str(eval(f"{a}{op}{b}"))),
            (r'(\d+)\s*([+\-*/])\s*(\d+)\s*=', lambda a, op, b: str(eval(f"{a}{op}{b}"))),
            (r'(\d+)\s*\+\s*(\d+)\s*=', lambda a, _, b: str(int(a)+int(b))),
            (r'(\d+)\s*\-\s*(\d+)\s*=', lambda a, _, b: str(int(a)-int(b))),
            (r'(\d+)\s*\*\s*(\d+)\s*=', lambda a, _, b: str(int(a)*int(b))),
            (r'(\d+)\s*\/\s*(\d+)\s*=', lambda a, _, b: str(int(a)/int(b)) if int(b)!=0 else None),
        ]
        for pattern, solver in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    if len(match.groups()) == 3:
                        a, op, b = match.groups()
                        result = solver(a, op, b)
                    else:
                        a, b = match.groups()
                        result = solver(a, '+', b)
                    if result is not None:
                        return result
                except:
                    continue
        return None

    def _get_buttons_from_message(self, msg):
        """استخراج جميع الأزرار من الرسالة (أيا كان نوعها) مع نصها ونوعها"""
        buttons = []
        if not msg.reply_markup:
            return buttons

        # أزرار مضمّنة (InlineKeyboardMarkup)
        if hasattr(msg.reply_markup, 'rows'):
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    if hasattr(btn, 'url') and btn.url:
                        continue  # نتجاهل أزرار الروابط
                    buttons.append({
                        'button': btn,
                        'text': getattr(btn, 'text', ''),
                        'type': 'inline'
                    })
        # أزرار لوحة مفاتيح (ReplyKeyboardMarkup)
        elif hasattr(msg.reply_markup, 'rows') and hasattr(msg.reply_markup.rows[0].buttons, '__iter__'):
            # في حال كان هيكل مختلف، لكننا نتعامل مع الـ ReplyKeyboardMarkup
            # لكن Telethon يستخدم نفس البنية rows.buttons
            # يمكن أن يكون هناك اختلاف، سنتعامل معها بنفس الطريقة
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    text = getattr(btn, 'text', '')
                    if isinstance(btn, KeyboardButtonRequestPhone):
                        buttons.append({
                            'button': btn,
                            'text': text,
                            'type': 'request_phone'
                        })
                    else:
                        buttons.append({
                            'button': btn,
                            'text': text,
                            'type': 'reply'
                        })
        else:
            # محاولة الوصول المباشر في حال كانت البنية مختلفة
            try:
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        if hasattr(btn, 'url') and btn.url:
                            continue
                        buttons.append({
                            'button': btn,
                            'text': getattr(btn, 'text', ''),
                            'type': 'inline' if hasattr(btn, 'callback_data') else 'reply'
                        })
            except:
                pass

        return buttons

    def _is_verification_button(self, text: str) -> bool:
        """تحديد إذا كان الزر يخص التحقق بناءً على نصه (نتجنب أزرار التجميع والروابط)"""
        text_lower = text.casefold().strip()
        # كلمات تدل على التحقق (أولوية عالية)
        verify_keywords = [
            'تحقق', 'verify', 'تأكيد', 'confirm', 'متابعة', 'التالي', 'next',
            'continue', 'ابدأ', 'start', 'إرسال', 'send', 'موافق', 'ok',
            'نعم', 'yes', 'تمام', 'done', 'استمر', 'proceed', 'تفعيل', 'activate',
            'ارسال', 'إدخال', 'ادخل', 'enter', 'submit', 'تقديم',
            'اضغط للتحقق', 'اضغط هنا', 'click here', 'اضغط على الزر'
        ]
        # كلمات تدل على أشياء أخرى (نتجنبها)
        ignore_keywords = [
            'رابط', 'link', 'نقاط', 'points', 'تجميع', 'collect', 'دعوة', 'invite',
            'انضمام', 'join', 'حذف', 'delete', 'إلغاء', 'cancel', 'خروج', 'exit',
            'مشاركة', 'share', 'تحميل', 'download', 'رفع', 'upload',
            'تخطي', 'skip', 'لا', 'none'
        ]
        for kw in verify_keywords:
            if kw in text_lower:
                return True
        for kw in ignore_keywords:
            if kw in text_lower:
                return False
        if len(text) <= 2:
            return True
        return True

    async def _press_verification_button(self, client, bot_entity, msg, phone_number: str) -> bool:
        """محاولة الضغط على زر تحقق مناسب من الرسالة"""
        buttons = self._get_buttons_from_message(msg)
        if not buttons:
            logger.info(f"⚠️ لا توجد أزرار في الرسالة: {msg.id}")
            return False

        logger.info(f"🔍 تم العثور على {len(buttons)} زر/أزرار في الرسالة {msg.id}")

        # البحث عن زر طلب رقم (نعطيها أولوية خاصة)
        for b in buttons:
            if b['type'] == 'request_phone':
                try:
                    me = await client.get_me()
                    if me and me.phone:
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
                        return True
                except Exception as e:
                    logger.warning(f"فشل إرسال جهة الاتصال: {e}")
                continue

        # ترتيب الأزرار حسب الأولوية
        # 1. زر يحوي "اضغط للتحقق" بالضبط
        selected = None
        for b in buttons:
            if b['text'].strip() == "اضغط للتحقق":
                selected = b
                break
        if not selected:
            # 2. زر يحوي "تحقق" أو "verify"
            for b in buttons:
                if 'تحقق' in b['text'] or 'verify' in b['text'].lower():
                    selected = b
                    break
        if not selected:
            # 3. أي زر تحقق حسب القائمة
            for b in buttons:
                if self._is_verification_button(b['text']):
                    selected = b
                    break
        if not selected:
            # 4. أي زر عادي (ما عدا الروابط)
            for b in buttons:
                if b['type'] != 'inline' or not hasattr(b['button'], 'url') or not b['button'].url:
                    selected = b
                    break

        if not selected:
            logger.info("⚠️ لم يتم العثور على زر مناسب للضغط")
            return False

        # الضغط على الزر
        try:
            btn = selected['button']
            if selected['type'] == 'inline':
                await btn.click()
                logger.info(f"🖱️ تم الضغط على زر Inline: '{selected['text']}'")
            elif selected['type'] in ('reply', 'request_phone'):
                await client.send_message(bot_entity, selected['text'])
                logger.info(f"🖱️ تم إرسال نص الزر: '{selected['text']}'")
            else:
                return False
            return True
        except Exception as e:
            logger.warning(f"فشل الضغط على الزر: {e}")
            return False

    async def _solve_legacy_verification(self, client, bot_entity, phone_number: str, channel_id: Optional[str] = None) -> bool:
        """
        حل التحقق بسرعة فائقة وبالسلوك المطلوب:
        1. يدخل الرابط (يرسل /start) ويحدد نقطة البداية كآخر رسالة خارجة.
        2. يقرأ كل الرسائل الواردة التي أتت بعد نقطة البداية.
        3. إذا وجد زر تحقق مناسب، يضغطه (يتجنب أزرار الروابط والنقاط).
        4. بعد الضغط، يقرأ الرسائل الجديدة مرة أخرى.
        5. يستمر حتى يتم حل التحقق بالكامل.
        """
        MAX_ATTEMPTS = 30
        base_id = 0

        try:
            out_msgs = await client.get_messages(bot_entity, limit=1, outgoing=True)
            if out_msgs:
                base_id = out_msgs[0].id
                logger.info(f"🔑 نقطة البداية (آخر رسالة خارجة): {base_id}")
            else:
                logger.info("⚠️ لم يتم العثور على رسائل خارجة، سنبدأ من 0")
        except Exception as e:
            logger.warning(f"تعذر تحديد الرسالة المرجعية: {e}")

        pressed_verify = False

        for attempt in range(MAX_ATTEMPTS):
            try:
                # جلب الرسائل الواردة التي id > base_id
                messages = await client.get_messages(bot_entity, limit=5, min_id=base_id, incoming=True)
            except Exception as e:
                logger.warning(f"فشل جلب الرسائل: {e}")
                await asyncio.sleep(0.1)
                continue

            if not messages:
                if not pressed_verify:
                    await asyncio.sleep(0.1)
                    continue
                await asyncio.sleep(0.1)
                continue

            # ترتيب تصاعدي
            messages = sorted(messages, key=lambda m: m.id)
            logger.info(f"📩 تم جلب {len(messages)} رسالة جديدة (min_id={base_id})")

            for msg in messages:
                if msg.id <= base_id:
                    continue
                base_id = msg.id  # تحديث إلى آخر رسالة تمت معالجتها
                text = getattr(msg, 'message', '') or ''
                logger.info(f"📨 معالجة رسالة {msg.id}: {text[:50]}...")

                # 1. محاولة استخراج كود وإرساله
                code = _extract_code_from_text(text)
                if code:
                    try:
                        await client.send_message(bot_entity, code)
                        logger.info(f"✅ تم إرسال الكود: {code}")
                        await asyncio.sleep(0.2)
                        continue
                    except Exception as e:
                        logger.warning(f"فشل إرسال الكود: {e}")

                # 2. حل مسألة رياضية
                math_result = self._solve_math(text)
                if math_result is not None:
                    try:
                        await client.send_message(bot_entity, math_result)
                        logger.info(f"✅ تم حل المسألة: {math_result}")
                        await asyncio.sleep(0.2)
                        continue
                    except Exception as e:
                        logger.warning(f"فشل حل المسألة: {e}")

                # 3. طلب ID
                if any(kw in text.casefold() for kw in ['id', 'ايدي', 'معرف', 'رقم', 'كود']):
                    id_to_send = channel_id if channel_id else self._extract_id_from_text(text)
                    if id_to_send:
                        try:
                            await client.send_message(bot_entity, id_to_send)
                            logger.info(f"✅ تم إرسال ID: {id_to_send}")
                            await asyncio.sleep(0.2)
                            continue
                        except Exception as e:
                            logger.warning(f"فشل إرسال ID: {e}")

                # 4. الضغط على زر التحقق
                if msg.reply_markup:
                    logger.info(f"🧩 تحتوي الرسالة على أزرار، نحاول الضغط...")
                    pressed = await self._press_verification_button(client, bot_entity, msg, phone_number)
                    if pressed:
                        pressed_verify = True
                        logger.info("✅ تم الضغط على زر التحقق، ننتظر قليلاً ثم نستمر")
                        await asyncio.sleep(0.5)
                        continue
                    else:
                        logger.info("⚠️ لم يتم الضغط على أي زر")
                else:
                    logger.info("ℹ️ لا توجد أزرار في هذه الرسالة")

                # إذا لم نجد أي شيء نفعله، ننتظر قليلاً
                await asyncio.sleep(0.1)

        # إذا انتهت المحاولات ولم يحدث خطأ، نعتبر النجاح
        logger.warning(f"⚠️ انتهت المحاولات، نعتبر النجاح من {phone_number}")
        return True

    # ─── 5. دالة حل التحقق الرئيسية ───

    async def _solve_verification(self, client, bot_entity, phone_number: str, channel_ref: Optional[str] = None) -> bool:
        MAX_WAIT = 6
        CHECK_INTERVAL = 0.2

        # ─── المرحلة 1: طلب مشاركة الرقم ───
        contact_request_msg = None
        for _ in range(MAX_WAIT):
            try:
                messages = await client.get_messages(bot_entity, limit=3)
            except Exception:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            for msg in messages:
                if msg.out:
                    continue
                buttons = self._get_buttons_from_message(msg)
                for b in buttons:
                    if isinstance(b['button'], KeyboardButtonRequestPhone):
                        contact_request_msg = msg
                        break
                if contact_request_msg:
                    break
            if contact_request_msg:
                break
            await asyncio.sleep(CHECK_INTERVAL)

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

            proceed_button = None
            for _ in range(MAX_WAIT):
                try:
                    messages = await client.get_messages(bot_entity, limit=3)
                except Exception:
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue

                for msg in messages:
                    if msg.out:
                        continue
                    buttons = self._get_buttons_from_message(msg)
                    for b in buttons:
                        if b['type'] == 'url':
                            continue
                        btn_text = b['text'].strip().casefold()
                        if any(kw in btn_text for kw in ['متابعة', 'التالي', 'ابدأ', 'تحقق', 'continue', 'next', 'start', 'verify']):
                            proceed_button = b
                            break
                        if not proceed_button:
                            proceed_button = b
                    if proceed_button:
                        break
                if proceed_button:
                    break
                await asyncio.sleep(CHECK_INTERVAL)

            if proceed_button:
                try:
                    if proceed_button['type'] == 'inline':
                        await proceed_button['button'].click()
                    else:
                        await client.send_message(bot_entity, proceed_button['text'])
                    logger.info(f"🖱️ تم الضغط على زر '{proceed_button['text']}'")
                except Exception as e:
                    logger.warning(f"⚠️ فشل الضغط على زر المتابعة: {e}")

            for _ in range(MAX_WAIT):
                try:
                    latest = await client.get_messages(bot_entity, limit=3)
                    success = False
                    for msg in latest:
                        if msg.out:
                            continue
                        if not msg.reply_markup and (getattr(msg, 'message', '') or '').strip():
                            success = True
                            break
                        text = (getattr(msg, 'message', '') or '').strip().casefold()
                        if any(kw in text for kw in ['تم', 'نجاح', 'مرحباً', 'شكراً', 'success', 'done', 'welcome']):
                            success = True
                            break
                    if success:
                        logger.info(f"✅ تم التحقق بنجاح (مشاركة الرقم) من {phone_number}")
                        return True
                except Exception:
                    pass
                await asyncio.sleep(CHECK_INTERVAL)

            try:
                original = await client.get_messages(bot_entity, ids=contact_request_msg.id)
                if original and not original.reply_markup:
                    logger.info(f"✅ اختفت أزرار طلب الرقم، نعتبر النجاح من {phone_number}")
                    return True
            except Exception:
                pass

            logger.warning(f"⚠️ لم نؤكد التحقق لكننا سنعتبره ناجحاً (مشاركة الرقم) من {phone_number}")
            return True

        logger.info(f"🔍 لم يطلب البوت رقم هاتف، ننتقل إلى المنطق المحسّن لـ {phone_number}")
        return await self._solve_legacy_verification(client, bot_entity, phone_number, channel_ref)

    # ─── 6. التنفيذ الرئيسي ───

    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=10)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=5):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"

            channels = params.get("channel_ref") or []
            channel_id = channels[0] if channels else None
            if channels:
                for channel_ref in channels:
                    try:
                        await _join_channel_and_schedule_leave(client, channel_ref)
                        await asyncio.sleep(0.2)
                    except Exception as e:
                        logger.warning(f"فشل الانضمام للقناة {channel_ref}: {e}")

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
            await asyncio.sleep(1.0)  # زيادة الانتظار قليلاً

            success = await self._solve_verification(client, bot_entity, session.get("phone_number"), channel_id)

            if success:
                return True, f"✅ تمت الإحالة مع التحقق من {session['phone_number']}"
            else:
                return False, "فشل التحقق بعد محاولات متعددة"
        except Exception as e:
            if "two different IP" in str(e) or "AuthKeyDuplicated" in str(e):
                logger.error(f"⚠️ الجلسة {session.get('phone_number')} تستخدم من IP مختلف - سيتم تعطيلها")
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة تستخدم من IP مختلف - تم تعطيلها مؤقتاً"
            return False, f"❌ فشل: {str(e)}"
        finally:
            await client.disconnect()
