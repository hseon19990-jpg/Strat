# forced_ref_ai.py
"""
خدمة إحالة بوت إجباري مع تحقق شامل - تدعم مشاركة الرقم والكود والمسائل والأزرار
كل المنطق موجود في هذا الملف (بدون اعتماد على ForcedRefService)
"""

from .common import *
from telethon.tl.types import InputMediaContact, KeyboardButtonRequestPhone


def _verification_message_text(message) -> str:
    """قراءة نص الرسالة أو caption مهما كان نوع كائن Telethon."""
    for field_name in ("message", "raw_text", "text", "caption"):
        value = getattr(message, field_name, None)
        if value:
            return str(value)
    return ""


def _normalize_choice_text(value: str) -> str:
    """توحيد نصوص الأزرار حتى نطابق العربية والأرقام بأمان."""
    value = str(value or "").strip().casefold()
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    value = value.replace("ى", "ي").replace("ة", "ه")
    value = re.sub(r"[\u064B-\u065F\u0670]", "", value)
    value = value.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    return re.sub(r"\s+", " ", value).strip(" .:،,؛;!?؟-–—")


def _verification_choice_button(message, text: str):
    """
    اختيار زر التحقق عندما يكون التحدي من خيارين أو أكثر.

    لا نضغط زرًا عشوائيًا: لا نختار إلا إذا كان النص يحدد الإيموجي،
    رقم/حرف الخيار، أو اسم الزر نفسه. هذا يمنع اعتبار زر رابط أو زر
    واجهة عادي إجابةً للتحقق.
    """
    buttons = [
        btn
        for row in (getattr(message, "buttons", None) or [])
        for btn in (row if isinstance(row, (list, tuple)) else [row])
        if not getattr(btn, "url", None)
    ]
    if not buttons:
        return None

    labels = [
        _normalize_choice_text(getattr(btn, "text", ""))
        for btn in buttons
    ]
    folded_text = _normalize_choice_text(text)

    # 1) تحديات الإيموجي: «اختر نفس الإيموجي: 🍎»
    emoji_pattern = re.compile(
        "[\U0001F300-\U0001FAFF\u2600-\u27BF\U0001F1E0-\U0001F1FF]"
    )
    target_emojis = emoji_pattern.findall(text)
    if target_emojis:
        target_emoji = target_emojis[-1]
        for btn, label in zip(buttons, labels):
            if label == _normalize_choice_text(target_emoji) or target_emoji in getattr(btn, "text", ""):
                return btn

    # 2) «الخيار الأول/الثاني» أو «option A/B» أو «زر رقم 2».
    ordinal_indexes = {
        "الاول": 0, "الأول": 0, "اول": 0, "first": 0,
        "الثاني": 1, "الثانيه": 1, "الثاني": 1, "second": 1,
        "الثالث": 2, "الثالثه": 2, "third": 2,
        "الرابع": 3, "الرابعه": 3, "fourth": 3,
    }
    ordinal_match = re.search(
        r"(?:الخيار|الزر|زر|option|button)\s*"
        r"(?:رقم\s*)?(الأول|الاول|اول|الثاني|الثانيه|الثالث|الثالثه|الرابع|الرابعه|"
        r"first|second|third|fourth|\d+|[a-d])\b",
        folded_text,
    )
    if ordinal_match:
        token = ordinal_match.group(1)
        if token in ordinal_indexes:
            index = ordinal_indexes[token]
        elif token.isdigit():
            index = int(token) - 1
        else:
            index = ord(token) - ord("a")
        if 0 <= index < len(buttons):
            return buttons[index]

    # 3) الخيار المكتوب بين علامات اقتباس، مثل: اختر «نعم».
    quoted_values = re.findall(r"[«“\"']([^»”\"']+)[»”\"']", text)
    for quoted in quoted_values:
        quoted_normalized = _normalize_choice_text(quoted)
        for btn, label in zip(buttons, labels):
            if quoted_normalized and quoted_normalized == label:
                return btn

    # 4) إذا ذكر السؤال اسم خيار واحد بوضوح، نطابقه مع زر واحد فقط.
    # لا نستخدم هذا المسار إذا ظهر أكثر من زر في النص حتى لا نختار عشوائيًا.
    meaningful = [
        (btn, label)
        for btn, label in zip(buttons, labels)
        if label and len(label) > 1 and label in folded_text
    ]
    if len(meaningful) == 1 and any(
        marker in folded_text
        for marker in ("اختر", "اختار", "الصحيح", "correct", "choose", "select")
    ):
        return meaningful[0][0]

    return None


# التحقق لا يحتاج انتظار ثانيتين بين كل قراءة؛ هذا كان يضيف دقيقة تقريباً
# للحساب الواحد. نقرأ بسرعة مع إبقاء فاصل صغير حتى لا نكرر طلبات Telegram
# بلا داعٍ.
VERIFICATION_READ_INTERVAL_SECONDS = 0.25
VERIFICATION_MAX_WAIT_CYCLES = 8


class ForcedRefAIService(RakshService):
    """خدمة إحالة بوت إجباري مع تحقق شامل - كل شيء في مكان واحد"""

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

    # ─── تجاوز دالة جلب الجلسات لإزالة أي استبعاد ───
    def get_sessions(self) -> List[Dict]:
        """
        جلب جميع الحسابات النشطة (بدون استبعاد forced_ref_excluded)
        هذه الدالة تتجاوز الدالة الأم لضمان عدم فقدان أي حساب.
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
                callback_data=f"raksh_{self.service_type}:skip_channels",
            )],
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
                            callback_data=f"raksh_{self.service_type}:payment:points:{quantity}:{points_cost}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                            callback_data=f"raksh_{self.service_type}:payment:stars:{quantity}:{stars_cost}"
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
                            callback_data=f"raksh_{self.service_type}:confirm:{payment_method}:{quantity}:{total_cost}"
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

    # ─── 4. حل التحقق المدمج (يدعم مشاركة الرقم + المنطق القديم) ───

    async def _click_initial_verification_button(
        self,
        client,
        bot_entity,
        start_after_message_id: int = 0,
    ) -> Optional[int]:
        """اضغط زر بدء التحقق قبل قراءة التحدي الفعلي."""
        start_keywords = (
            "اضغط للتحقق",
            "ابدأ التحقق",
            "بدء التحقق",
            "تحقق الآن",
            "click to verify",
            "start verification",
            "verify now",
            "проверить",
        )

        for _ in range(VERIFICATION_MAX_WAIT_CYCLES):
            try:
                messages = await client.get_messages(bot_entity, limit=10)
            except Exception:
                await asyncio.sleep(VERIFICATION_READ_INTERVAL_SECONDS)
                continue

            # Telethon يعيد الأحدث أولاً؛ نبدأ به حتى لا نضغط زرًا قديمًا
            # من محاولة تحقق سابقة.
            for msg in messages:
                if msg.out or msg.id <= start_after_message_id:
                    continue
                # مهم: msg.reply_markup.rows تعيد أزرار Telethon الخام،
                # وهذه الكائنات لا تملك click(). أما msg.buttons فتعيد
                # MessageButton المرتبط بالرسالة والقابل للضغط.
                for btn in getattr(msg, "buttons", None) or []:
                    btn_text = (getattr(btn, "text", "") or "").strip().casefold()
                    if getattr(btn, "url", None):
                        continue
                    is_arabic_verify_button = (
                        "اضغط" in btn_text and "تحقق" in btn_text
                    )
                    is_english_verify_button = (
                        "press" in btn_text and "verify" in btn_text
                    )
                    if not (
                        is_arabic_verify_button
                        or is_english_verify_button
                        or any(keyword in btn_text for keyword in start_keywords)
                    ):
                        continue
                    try:
                        await btn.click()
                        logger.info(
                            f"🖱️ تم الضغط على زر بدء التحقق: "
                            f"'{getattr(btn, 'text', '')}'"
                        )
                        return getattr(msg, "id", None)
                    except Exception as exc:
                        logger.warning(f"⚠️ فشل الضغط على زر بدء التحقق: {exc}")
            await asyncio.sleep(VERIFICATION_READ_INTERVAL_SECONDS)

        logger.info("ℹ️ لم يظهر زر بدء تحقق منفصل؛ متابعة فحص التحدي مباشرة")
        return None

    async def _solve_verification(
        self,
        client,
        bot_entity,
        phone_number: str,
        start_after_message_id: int = 0,
    ) -> bool:
        """
        حل التحقق بذكاء:
        1. الضغط على زر بدء التحقق مثل «اضغط للتحقق».
        2. إذا طلب البوت مشاركة رقم الهاتف – نرسل الرقم ونضغط متابعة.
        3. وإلا نستخدم المنطق القديم: استخراج الكود، حل المسائل، الضغط على الأزرار العادية.
        """
        MAX_WAIT = VERIFICATION_MAX_WAIT_CYCLES
        CHECK_INTERVAL = VERIFICATION_READ_INTERVAL_SECONDS

        # بعض البوتات ترسل زرًا أوليًا، وبعد الضغط عليه تعدّل نفس الرسالة
        # وتضع فيها التحقق الحقيقي، بينما ترسل بوتات أخرى رسالة جديدة.
        # لذلك نعيد قراءة المحادثة بعد الضغط ولا نتجاهل رقم الرسالة القديم:
        # الرقم نفسه قد يحمل محتوى جديدًا بعد التعديل.
        initial_button_message_id = await self._click_initial_verification_button(
            client,
            bot_entity,
            start_after_message_id=start_after_message_id,
        )
        if initial_button_message_id is not None:
            await asyncio.sleep(VERIFICATION_READ_INTERVAL_SECONDS)

        text_challenge_markers = (
            "أرسل النص التالي",
            "ارسل النص التالي",
            "النص التالي",
            "send the following text",
            "send the text",
            "type the following",
            "retype",
        )
        processed_message_ids = set()

        # بعض البوتات تعدّل نفس رسالة زر التحقق، وأخرى ترسل رسالة جديدة
        # بعد الضغط. نستخدم نفس التدفق الذي ينجح مع هذه البوتات:
        # اضغط الزر أولاً، ثم أعد القراءة عدة مرات، ثم أرسل النص المطلوب.
        # لا نعتمد على رقم الرسالة وحده؛ الرسالة المعدّلة قد تحتفظ برقمها
        # القديم، بينما الرد الجديد يحصل على رقم مختلف.
        if initial_button_message_id is not None:
            for _ in range(MAX_WAIT):
                observed_messages = []
                try:
                    updated_message = await client.get_messages(
                        bot_entity,
                        ids=initial_button_message_id,
                    )
                    if isinstance(updated_message, (list, tuple)):
                        updated_message = (
                            updated_message[0] if updated_message else None
                        )
                    if updated_message:
                        observed_messages.append(updated_message)
                except Exception as exc:
                    logger.warning(
                        f"تعذر قراءة رسالة التحقق المعدّلة "
                        f"{initial_button_message_id}: {exc}"
                    )

                try:
                    recent_messages = await client.get_messages(
                        bot_entity,
                        limit=20,
                    )
                    observed_messages.extend(recent_messages or [])
                except Exception as exc:
                    logger.warning(f"تعذر قراءة الرد بعد زر التحقق: {exc}")

                sent_after_click = False
                seen_ids = set()
                for message in observed_messages:
                    message_id = getattr(message, "id", None)
                    if message_id in seen_ids:
                        continue
                    seen_ids.add(message_id)
                    if (
                        not message
                        or getattr(message, "out", False)
                        or (message_id is not None and message_id <= start_after_message_id)
                    ):
                        continue

                    message_text = _verification_message_text(message).strip()
                    if not message_text or message_text.startswith("/"):
                        continue

                    folded_text = message_text.casefold()
                    has_text_prompt = any(
                        marker in folded_text for marker in text_challenge_markers
                    )
                    # بعض النسخ ترد بالكود في سطر مستقل دون عبارة
                    # «أرسل النص التالي»، لذلك نفحص السطر نفسه أيضاً.
                    has_standalone_code = any(
                        re.fullmatch(r"[A-Za-z0-9]{3,50}", line.strip().strip("`*_ "))
                        for line in message_text.splitlines()
                    )
                    if not has_text_prompt and not has_standalone_code:
                        continue

                    send_text = _extract_code_from_text(message_text)
                    if not send_text:
                        for line in message_text.splitlines():
                            candidate = line.strip().strip("`*_ ")
                            if re.fullmatch(r"[A-Za-z0-9]{3,50}", candidate):
                                send_text = candidate
                                break
                    if not send_text:
                        continue

                    try:
                        await client.send_message(bot_entity, send_text)
                        processed_message_ids.add(message_id)
                        logger.info(
                            f"✅ تم الضغط على زر التحقق ثم إرسال النص: {send_text}"
                        )
                        sent_after_click = True
                        break
                    except Exception as exc:
                        logger.warning(f"تعذر إرسال نص التحقق بعد الضغط: {exc}")

                if sent_after_click:
                    break
                await asyncio.sleep(CHECK_INTERVAL)

        # بعد الضغط أو بعد /start مباشرة، قد تكون رسالة «أرسل النص التالي»
        # موجودة بالفعل، وقد يكون رقمها أقدم من آخر رسالة صادرة للحساب
        # بسبب تعديل الرسالة. نضع أحدث رسالة نصية صريحة في قائمة الأولوية
        # حتى تصل إلى محلل الكود مهما كان ترتيب أرقام Telegram.
        priority_message_ids = (
            {initial_button_message_id}
            if initial_button_message_id is not None
            else set()
        )
        try:
            post_click_messages = await client.get_messages(bot_entity, limit=50)
            for msg in post_click_messages:
                if msg.out or msg.id <= start_after_message_id:
                    continue
                # نضع كل الرسائل اللاحقة في الأولوية، وليس رسائل النص فقط:
                # قد يكون التحقق في caption أو keyboard أو رسالة معدّلة
                # دون تغيير النص.
                priority_message_ids.add(msg.id)
                msg_text = _verification_message_text(msg).casefold()
                if any(marker in msg_text for marker in text_challenge_markers):
                    logger.info(
                        f"🔎 تم تحديد رسالة نص التحقق رقم {msg.id} "
                        f"للمعالجة بعد الضغط"
                    )
        except Exception as exc:
            logger.warning(f"تعذر إعادة قراءة رسالة التحقق بعد الضغط: {exc}")

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

        # إذا وجدنا طلب رقم → نعالجه بطريقة جديدة
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

            # انتظار زر متابعة
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
                    # استخدم MessageButton وليس أزرار reply_markup الخام؛
                    # الأول فقط يملك click() في Telethon.
                    buttons = [
                        btn for btn in (getattr(msg, "buttons", None) or [])
                        if not getattr(btn, "url", None)
                    ]
                    # لا نضغط زرًا عشوائيًا؛ قد يكون زر رابط دعوة أو زرًا
                    # تابعًا لواجهة البوت وليس خطوة تحقق.
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

            # انتظار تأكيد النجاح (اختفاء الأزرار أو رسالة تأكيد)
            for _ in range(MAX_WAIT):
                try:
                    latest = await client.get_messages(bot_entity, limit=3)
                    success = False
                    for msg in latest:
                        if msg.out or msg.id <= start_after_message_id:
                            continue
                        if not msg.reply_markup and _verification_message_text(msg).strip():
                            success = True
                            break
                        text = _verification_message_text(msg).strip().casefold()
                        if any(kw in text for kw in ['تم', 'نجاح', 'مرحباً', 'شكراً', 'success', 'done', 'welcome']):
                            success = True
                            break
                    if success:
                        logger.info(f"✅ تم التحقق بنجاح (مشاركة الرقم) من {phone_number}")
                        return True
                except Exception:
                    pass
                await asyncio.sleep(CHECK_INTERVAL)

            # فحص أخير: هل اختفت أزرار طلب الرقم؟
            try:
                original = await client.get_messages(bot_entity, ids=contact_request_msg.id)
                if original and not original.reply_markup:
                    logger.info(f"✅ اختفت أزرار طلب الرقم، نعتبر النجاح من {phone_number}")
                    return True
            except Exception:
                pass

            # إذا لم نجد تأكيداً، نعتبر العملية ناجحة (لعدم وجود خطأ واضح)
            logger.warning(f"⚠️ لم نؤكد التحقق لكننا سنعتبره ناجحاً (مشاركة الرقم) من {phone_number}")
            return True

        # ─── المرحلة 2: لم يطلب الرقم → استخدم المنطق القديم ───
        logger.info(f"🔍 لم يطلب البوت رقم هاتف، ننتقل إلى المنطق القديم لـ {phone_number}")

        # المنطق القديم (مستند على _solve_forced_ref_verification من common.py)
        # ولكن سنعيد تنفيذه هنا لتكامل الملف
        return await self._solve_legacy_verification(
            client,
            bot_entity,
            phone_number,
            start_after_message_id=start_after_message_id,
            priority_message_ids=priority_message_ids,
            processed_message_ids=processed_message_ids,
        )

    async def _solve_legacy_verification(
        self,
        client,
        bot_entity,
        phone_number: str,
        ignored_message_ids=None,
        priority_message_ids=None,
        start_after_message_id: int = 0,
        processed_message_ids=None,
    ) -> bool:
        """
        المنطق القديم: استخراج الكود، حل المسائل، الضغط على الأزرار
        (نسخة محسنة من _solve_forced_ref_verification في common.py)
        """
        max_attempts = 24
        base_id = 0
        processed_ids = set(processed_message_ids or ())
        # أبقينا الوسيط للتوافق مع أي استدعاء قديم، لكن لا نتجاهل رسالة
        # الزر هنا؛ Telegram قد يعدّلها ويضع فيها التحدي الثاني.
        ignored_message_ids = set(ignored_message_ids or ())
        priority_message_ids = set(priority_message_ids or ())

        try:
            out_messages = await client.get_messages(bot_entity, limit=10)
            for msg in out_messages:
                if msg.out:
                    base_id = msg.id
                    logger.info(f"🔑 نقطة البداية هي رسالة الحساب رقم: {base_id}")
                    break
        except Exception as e:
            logger.warning(f"تعذر تحديد الرسالة المرجعية: {e}")

        for attempt in range(max_attempts):
            try:
                messages = await client.get_messages(bot_entity, limit=20)
            except Exception as exc:
                if "two different IP" in str(exc) or "AuthKeyDuplicated" in str(exc):
                    logger.error(f"⚠️ الجلسة {phone_number} تستخدم من IP مختلف - سيتم تعطيلها")
                    _mark_raksh_session_unauthorized(phone_number)
                    return False
                await asyncio.sleep(VERIFICATION_READ_INTERVAL_SECONDS)
                continue

            incoming_messages = [msg for msg in messages if not msg.out]
            incoming_messages.sort(key=lambda m: m.id)

            new_messages = [
                msg for msg in incoming_messages
                if (
                    msg.id > start_after_message_id
                    and (msg.id > base_id or msg.id in priority_message_ids)
                    and msg.id not in processed_ids
                    and msg.id not in ignored_message_ids
                )
            ]
            if not new_messages:
                await asyncio.sleep(VERIFICATION_READ_INTERVAL_SECONDS)
                continue

            # لا نعتبر اختفاء الأزرار أو إرسال الإجابة نجاحاً. النجاح يجب أن
            # يأتي من رسالة صريحة من البوت، مثل «تم التحقق بنجاح».
            for msg in reversed(new_messages):
                text = _verification_message_text(msg).strip()
                text_folded = text.casefold()
                if (
                    "تم التحقق" in text_folded
                    or "نجح التحقق" in text_folded
                    or "verification successful" in text_folded
                    or "verification complete" in text_folded
                    or "تم التحقق بنجاح" in text_folded
                    or "مرحباً بك في المجموعة" in text_folded
                    or "welcome to the group" in text_folded
                ) and not any(
                    marker in text_folded
                    for marker in (
                        "أرسل النص", "ارسل النص", "النص التالي",
                        "send the text", "resend", "أعد إرسال",
                    )
                ):
                    logger.info(f"✅ تم تأكيد التحقق من {phone_number}: {text[:120]}")
                    return True

            # نفضّل رسالة «أرسل النص التالي» صراحةً، حتى لو كانت معها
            # أزرار أخرى مثل «رابط الدعوة». تلك الأزرار ليست جواب التحقق.
            text_challenge_markers = (
                "أرسل النص التالي",
                "ارسل النص التالي",
                "النص التالي",
                "send the following text",
                "send the text",
                "type the following",
                "retype",
            )
            verification_message = next(
                (
                    msg for msg in reversed(new_messages)
                    if any(
                        marker in _verification_message_text(msg).casefold()
                        for marker in text_challenge_markers
                    )
                ),
                None,
            )
            for msg in new_messages:
                if verification_message is not None:
                    break
                msg_text = _verification_message_text(msg)
                if msg_text.strip().startswith("/"):
                    continue
                if any(kw in msg_text for kw in ["أرسل", "التالي", "بالضبط", "اكتب", "retype", "type", "اضغط", "اختر", "انقر"]):
                    verification_message = msg
                    break

            if verification_message is None:
                verification_message = next(
                    (
                        msg for msg in reversed(new_messages)
                        if not _verification_message_text(msg).strip().startswith("/")
                    ),
                    None
                )

            if verification_message is None:
                await asyncio.sleep(VERIFICATION_READ_INTERVAL_SECONDS)
                continue

            text = _verification_message_text(verification_message)

            # 1. استخراج الكود
            send_text = _extract_code_from_text(text)
            # احتياط إضافي للكود الموجود في سطر مستقل، مثل XILX9DRL،
            # عندما يرفق البوت رسالة التحقق بزر غير متعلق بالإجابة.
            if not send_text and any(
                marker in text.casefold() for marker in text_challenge_markers
            ):
                for line in text.splitlines():
                    candidate = line.strip().strip("`*_ ")
                    if re.fullmatch(r"[A-Za-z0-9]{3,50}", candidate):
                        send_text = candidate
                        break
            if send_text:
                try:
                    await client.send_message(bot_entity, send_text)
                    logger.info(f"✅ تم إرسال الكود: {send_text}")
                    processed_ids.add(verification_message.id)
                    # ننتظر رسالة البوت التالية؛ قد تكون نجاحاً أو مرحلة
                    # تحقق جديدة، ولا نعلن النجاح بمجرد إرسال الرمز.
                    await asyncio.sleep(VERIFICATION_READ_INTERVAL_SECONDS)
                    continue
                except Exception:
                    return False

            # 2. حل المسائل الرياضية
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
                            processed_ids.add(verification_message.id)
                            await asyncio.sleep(VERIFICATION_READ_INTERVAL_SECONDS)
                            break
                    except Exception:
                        continue
                else:
                    continue

            # 3. التحقق من خيارين أو عدة خيارات.
            # نستخدم نص السؤال لتحديد الزر الصحيح، ولا نضغط أول زر عشوائيًا.
            choice_button = _verification_choice_button(
                verification_message,
                text,
            )
            if choice_button:
                try:
                    await choice_button.click()
                    logger.info(
                        f"🖱️ تم اختيار زر التحقق الصحيح: "
                        f"{getattr(choice_button, 'text', '')}"
                    )
                    processed_ids.add(verification_message.id)
                    await asyncio.sleep(VERIFICATION_READ_INTERVAL_SECONDS)
                    continue
                except Exception as exc:
                    logger.warning(f"⚠️ فشل اختيار زر التحقق: {exc}")

            # 4. الضغط على أزرار التحقق العامة
            buttons = []
            for row in getattr(verification_message, 'buttons', None) or []:
                for btn in row:
                    if not getattr(btn, 'url', None):
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

                # ترتيب الأزرار حسب الأولوية
                prioritized = []
                if target_emoji:
                    exact = [b for b in buttons if getattr(b, 'text', '') == target_emoji]
                    prioritized.extend(exact)
                    partial = [b for b in buttons if target_emoji in (getattr(b, 'text', '') or '') and b not in exact]
                    prioritized.extend(partial)

                verify_keywords = ['تحقق', 'verify', 'اضغط هنا', 'continue', 'التالي', 'متابعة']
                verify_buttons = [
                    b for b in buttons
                    if any(kw in (getattr(b, 'text', '') or '').casefold() for kw in verify_keywords)
                    and b not in prioritized
                ]
                prioritized.extend(verify_buttons)

                for btn in prioritized:
                    try:
                        await btn.click()
                        logger.info(f"🖱️ تم الضغط على الزر: {getattr(btn, 'text', '')}")
                        processed_ids.add(verification_message.id)
                        await asyncio.sleep(VERIFICATION_READ_INTERVAL_SECONDS)
                        # لا نعتبر اختفاء الأزرار نجاحاً؛ ستتم قراءة رسالة
                        # البوت الجديدة في الدورة التالية.
                        break
                    except Exception:
                        continue

            await asyncio.sleep(VERIFICATION_READ_INTERVAL_SECONDS)

        logger.warning(f"⚠️ لم تصل رسالة نجاح صريحة بعد التحقق من {phone_number}")
        return False

    # ─── 5. التنفيذ الرئيسي ───

    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ إحالة بوت إجباري مع تحقق شامل (يدعم جميع الأنواع)"""
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

            # نحدد آخر رسالة قبل /start حتى لا نستخدم أي تحدٍّ قديم
            # موجودًا في نفس محادثة الحساب.
            start_after_message_id = 0
            try:
                before_start_messages = await client.get_messages(
                    bot_entity,
                    limit=50,
                )
                start_after_message_id = max(
                    (getattr(msg, "id", 0) or 0)
                    for msg in before_start_messages
                ) if before_start_messages else 0
            except Exception as exc:
                logger.warning(f"تعذر تحديد نقطة بداية /start: {exc}")

            # بدء البوت
            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param or ""
            ))
            await asyncio.sleep(0.5)

            # حل التحقق باستخدام الدالة المدمجة
            success = await self._solve_verification(
                client,
                bot_entity,
                session.get("phone_number"),
                start_after_message_id=start_after_message_id,
            )

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
