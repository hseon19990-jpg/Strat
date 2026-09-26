# forced_ref_ai.py
"""
خدمة إحالة بوت إجباري مع تحقق شامل - تدعم مشاركة الرقم والكود والمسائل والأزرار
كل المنطق موجود في هذا الملف (بدون اعتماد على ForcedRefService)
"""

from .common import *
from telethon.tl.types import InputMediaContact
try:
    from telethon.tl.types import KeyboardButtonRequestPhone
except ImportError:
    # بعض إصدارات Telethon لا تصدّر هذا النوع؛ نكتفي بفحص اسم النوع لاحقاً.
    KeyboardButtonRequestPhone = None
from io import BytesIO
import base64
import json
import unicodedata
import colorsys
import urllib.error
import urllib.request

try:
    import ddddocr
except ImportError:
    ddddocr = None

try:
    from PIL import Image, ImageFilter, ImageOps
except ImportError:
    Image = None
    ImageFilter = None
    ImageOps = None


_CAPTCHA_OCR = None


# ═══════════════════════════════════════════════════════════════
# خرائط مرجعية لكابتشا "اختر الإيموجي المطابق"
# كل إيموجي → (لون سائد RGB, أسماء عربية/إنجليزية محتملة)
# ═══════════════════════════════════════════════════════════════
_EMOJI_COLOR_HINTS = {
    "🍅": {"name": ["طماطم", "بندورة", "tomato"], "rgb": (220, 60, 50)},
    "🥕": {"name": ["جزر", "جزرة", "carrot"], "rgb": (240, 140, 40)},
    "🦇": {"name": ["خفاش", "bat"], "rgb": (80, 60, 80)},
    "⌚": {"name": ["ساعة", "watch", "clock"], "rgb": (30, 30, 30)},
    "🦏": {"name": ["وحيد القرن", "خرتيت", "rhino", "rhinoceros"], "rgb": (140, 140, 140)},
    "🚓": {"name": ["سيارة شرطة", "شرطة", "police", "car"], "rgb": (40, 80, 180)},
    "🐷": {"name": ["خنزير", "pig", "piglet"], "rgb": (250, 170, 180)},
    "🐮": {"name": ["بقرة", "cow", "cattle"], "rgb": (240, 180, 180)},
    "🐄": {"name": ["بقرة", "cow"], "rgb": (240, 180, 180)},
    "🍎": {"name": ["تفاحة", "apple"], "rgb": (220, 50, 50)},
    "🍌": {"name": ["موز", "banana"], "rgb": (250, 220, 60)},
    "🍇": {"name": ["عنب", "grapes"], "rgb": (140, 60, 160)},
    "🍓": {"name": ["فراولة", "strawberry"], "rgb": (220, 50, 80)},
    "🐶": {"name": ["كلب", "dog"], "rgb": (200, 160, 120)},
    "🐱": {"name": ["قط", "قطة", "cat"], "rgb": (200, 170, 150)},
    "🐭": {"name": ["فأر", "mouse"], "rgb": (170, 170, 170)},
    "🐰": {"name": ["أرنب", "rabbit"], "rgb": (230, 230, 230)},
    "🦊": {"name": ["ثعلب", "fox"], "rgb": (220, 130, 60)},
    "🐻": {"name": ["دب", "bear"], "rgb": (150, 100, 70)},
    "🐼": {"name": ["باندا", "panda"], "rgb": (230, 230, 230)},
    "🐨": {"name": ["كوالا", "koala"], "rgb": (170, 170, 170)},
    "🐯": {"name": ["نمر", "tiger"], "rgb": (230, 160, 60)},
    "🦁": {"name": ["أسد", "lion"], "rgb": (220, 170, 80)},
    "🐸": {"name": ["ضفدع", "frog"], "rgb": (110, 180, 80)},
    "🐵": {"name": ["قرد", "monkey"], "rgb": (180, 130, 90)},
    "🐔": {"name": ["دجاجة", "دجاج", "chicken", "hen"], "rgb": (230, 200, 150)},
    "🐧": {"name": ["بطريق", "penguin"], "rgb": (40, 40, 60)},
    "🐦": {"name": ["طائر", "عصفور", "bird"], "rgb": (90, 160, 220)},
    "🦆": {"name": ["بطة", "duck"], "rgb": (200, 200, 180)},
    "🦉": {"name": ["بومة", "owl"], "rgb": (170, 140, 100)},
    "🐴": {"name": ["حصان", "horse"], "rgb": (170, 120, 80)},
    "🦄": {"name": ["يونيكورن", "unicorn"], "rgb": (240, 180, 220)},
    "🐝": {"name": ["نحلة", "bee"], "rgb": (240, 200, 60)},
    "🦋": {"name": ["فراشة", "butterfly"], "rgb": (120, 140, 220)},
    "🐢": {"name": ["سلحفاة", "turtle"], "rgb": (100, 150, 90)},
    "🐍": {"name": ["ثعبان", "أفعى", "snake"], "rgb": (100, 180, 90)},
    "🐙": {"name": ["أخطبوط", "octopus"], "rgb": (200, 90, 100)},
    "🦀": {"name": ["سلطعون", "crab"], "rgb": (220, 80, 60)},
    "🐟": {"name": ["سمكة", "سمك", "fish"], "rgb": (100, 170, 220)},
    "🐬": {"name": ["دلفين", "dolphin"], "rgb": (90, 150, 210)},
    "🐳": {"name": ["حوت", "whale"], "rgb": (80, 140, 220)},
    "🌻": {"name": ["عباد الشمس", "sunflower"], "rgb": (250, 200, 50)},
    "🌹": {"name": ["وردة", "rose"], "rgb": (220, 50, 70)},
    "🌷": {"name": ["توليب", "tulip"], "rgb": (230, 100, 150)},
    "🌳": {"name": ["شجرة", "tree"], "rgb": (90, 160, 80)},
    "⚽": {"name": ["كرة قدم", "football", "soccer"], "rgb": (240, 240, 240)},
    "🏀": {"name": ["كرة سلة", "basketball"], "rgb": (230, 130, 60)},
    "🎈": {"name": ["بالون", "balloon"], "rgb": (220, 80, 80)},
    "🎁": {"name": ["هدية", "gift"], "rgb": (220, 80, 100)},
    "💎": {"name": ["ماسة", "الماس", "diamond"], "rgb": (120, 200, 230)},
    "⭐": {"name": ["نجمة", "star"], "rgb": (250, 210, 70)},
    "🔥": {"name": ["نار", "لهب", "fire"], "rgb": (240, 120, 50)},
    "💧": {"name": ["ماء", "قطرة", "water", "drop"], "rgb": (100, 170, 230)},
    "🌙": {"name": ["قمر", "moon"], "rgb": (230, 220, 170)},
    "☀️": {"name": ["شمس", "sun"], "rgb": (250, 200, 60)},
    "⚡": {"name": ["برق", "صاعقة", "lightning"], "rgb": (250, 210, 60)},
    "❄️": {"name": ["ثلج", "snow"], "rgb": (170, 220, 240)},
}


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

    # ═══════════════════════════════════════════════════════════
    # دوال مساعدة جديدة لحل كابتشا الأرقام والإيموجي
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _extract_target_number(text: str) -> Optional[str]:
        """
        يستخرج الرقم المطلوب الضغط عليه من نص مثل:
        - "اضغط على الرقم (79)"
        - "الرقم 79"
        - "Press the number (79)"
        - "رقم: 79"
        """
        normalized = unicodedata.normalize("NFKC", str(text or "")).translate(
            str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        )
        patterns = [
            r"(?:الرقم|رقم|number|press|اضغط)\s*[\(\[]?\s*(\d{1,4})\s*[\)\]]?",
            r"[\(\[]\s*(\d{1,4})\s*[\)\]]",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _extract_dominant_color(image_bytes: bytes) -> Optional[tuple]:
        """يستخرج اللون السائد من صورة (يتجاهل الأبيض/الأسود/الرمادي)."""
        if Image is None:
            return None
        try:
            with Image.open(BytesIO(image_bytes)) as img:
                img = img.convert("RGB")
                img.thumbnail((100, 100))
                pixels = list(img.getdata())
                filtered = []
                for r, g, b in pixels:
                    mx, mn = max(r, g, b), min(r, g, b)
                    if mx - mn < 25:
                        continue
                    if r > 240 and g > 240 and b > 240:
                        continue
                    filtered.append((r, g, b))
                if not filtered:
                    filtered = pixels
                n = len(filtered)
                avg = (
                    sum(p[0] for p in filtered) // n,
                    sum(p[1] for p in filtered) // n,
                    sum(p[2] for p in filtered) // n,
                )
                return avg
        except Exception:
            return None

    @staticmethod
    def _color_similarity(c1: tuple, c2: tuple) -> float:
        """تشابه لوني بين لونين (0..1)."""
        try:
            r1, g1, b1 = [x / 255.0 for x in c1]
            r2, g2, b2 = [x / 255.0 for x in c2]
            h1, s1, v1 = colorsys.rgb_to_hsv(r1, g1, b1)
            h2, s2, v2 = colorsys.rgb_to_hsv(r2, g2, b2)
            dh = min(abs(h1 - h2), 1 - abs(h1 - h2)) * 2.0
            ds = abs(s1 - s2)
            dv = abs(v1 - v2)
            diff = (dh * 0.6) + (ds * 0.2) + (dv * 0.2)
            return max(0.0, 1.0 - diff)
        except Exception:
            return 0.0

    async def _solve_emoji_captcha(
        self,
        client,
        bot_entity,
        verification_message,
        text: str,
        buttons: list,
        phone_number: str,
    ) -> bool:
        """حل كابتشا الإيموجي بالرؤية، مع مطابقة صارمة لأزرار Telegram."""
        if not self._has_image_media(verification_message):
            return False

        try:
            image_buffer = BytesIO()
            await client.download_media(verification_message, file=image_buffer)
            image_bytes = image_buffer.getvalue()
        except Exception as exc:
            logger.warning("⚠️ تعذر تنزيل صورة كابتشا الإيموجي: %s", exc)
            return False
        if not image_bytes:
            return False

        candidate_labels = []
        for button in buttons:
            label = self._button_label(button).strip()
            if label and label not in candidate_labels:
                candidate_labels.append(label)
        if not candidate_labels:
            return False

        selected_label = await self._vision_select_button(
            image_bytes=image_bytes,
            challenge_text=text,
            candidate_labels=candidate_labels,
            phone_number=phone_number,
        )
        if not selected_label:
            logger.warning(
                "⚠️ لم يتم التعرف بثقة على إيموجي كابتشا الحساب %s؛ "
                "لن يتم الضغط عشوائياً",
                phone_number,
            )
            return False

        selected_normalized = self._normalise_captcha_label(selected_label)
        matching_button = next(
            (
                button for button in buttons
                if self._normalise_captcha_label(self._button_label(button))
                == selected_normalized
            ),
            None,
        )
        if matching_button is None:
            logger.warning(
                "⚠️ النموذج أعاد خياراً غير موجود ضمن أزرار Telegram: %r",
                selected_label,
            )
            return False

        try:
            await matching_button.click()
            logger.info(
                "✅ تم اختيار إيموجي الكابتشا %s للحساب %s",
                selected_label,
                phone_number,
            )
            return True
        except Exception as exc:
            logger.warning("⚠️ تعذر الضغط على إيموجي الكابتشا: %s", exc)
            return False

    async def _vision_select_button(
        self,
        image_bytes: bytes,
        challenge_text: str,
        candidate_labels: list,
        phone_number: str,
    ) -> Optional[str]:
        """يرى الصورة مرتين ويضغط فقط عند اتفاق تحليلين مستقلين."""
        api_key = (
            os.getenv("GPT_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("OPENAI_TOKEN")
        )
        if not api_key:
            logger.error(
                "❌ لا يوجد GPT_API_KEY أو OPENAI_API_KEY؛ "
                "لا يمكن حل كابتشا الإيموجي للحساب %s",
                phone_number,
            )
            return None

        endpoint = (
            os.getenv("GPT_VISION_ENDPOINT")
            or os.getenv("OPENAI_CHAT_COMPLETIONS_URL")
            or "https://api.openai.com/v1/chat/completions"
        )
        model = (
            os.getenv("GPT_VISION_MODEL")
            or os.getenv("OPENAI_VISION_MODEL")
            or "gpt-4o-mini"
        )
        encoded_image = base64.b64encode(image_bytes).decode("ascii")
        options_json = json.dumps(candidate_labels, ensure_ascii=False)
        if image_bytes.startswith(b"\x89PNG"):
            image_mime = "image/png"
        elif image_bytes.startswith(b"GIF"):
            image_mime = "image/gif"
        elif image_bytes.startswith(b"RIFF"):
            image_mime = "image/webp"
        else:
            image_mime = "image/jpeg"

        prompts = (
            (
                "Act as a strict visual inspector. Look at the attached image itself, "
                "identify the main object or emoji shown in it, and match it to exactly "
                "one of the Telegram buttons. Do not use color alone; inspect its shape "
                "and semantic object. "
            ),
            (
                "Independently verify this visual captcha from the image. Ignore any "
                "guess based only on dominant color. Compare the actual pictured object "
                "with every candidate button and choose one only if the visual identity "
                "is clear. "
            ),
        )

        def _parse_response(raw_response: str):
            response = json.loads(raw_response)
            content = (
                response.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            if isinstance(content, list):
                content = "".join(
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict)
                )
            text = str(content).strip()
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            result = json.loads(match.group(0) if match else text)
            if not isinstance(result, dict):
                return None, 0.0, ""
            label = result.get("label")
            confidence = result.get("confidence", 0.0)
            description = str(result.get("description", ""))[:160]
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = 0.0
            if not isinstance(label, str):
                return None, confidence, description
            normalized = self._normalise_captcha_label(label)
            for candidate in candidate_labels:
                if self._normalise_captcha_label(candidate) == normalized:
                    return candidate, confidence, description
            return None, confidence, description

        async def _inspect(prompt_prefix: str):
            prompt = (
                f"{prompt_prefix}"
                f"Available Telegram button labels are exactly: {options_json}. "
                f"Challenge text: {challenge_text!r}. "
                'Return JSON only in this shape: '
                '{"label":"one exact candidate","confidence":0.0,'
                '"description":"short description of what is visible"}. '
                'If the image is unclear or no candidate matches, return '
                '{"label":null,"confidence":0.0,"description":"unclear"}. '
                "Never invent a label. Confidence must be between 0 and 1."
            )
            payload = {
                "model": model,
                "temperature": 0,
                "max_tokens": 140,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    f"data:{image_mime};base64,{encoded_image}"
                                ),
                                "detail": "high",
                            },
                        },
                    ],
                }],
            }

            def _request():
                request = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    return response.read().decode("utf-8")

            raw_response = await asyncio.to_thread(_request)
            return _parse_response(raw_response)

        try:
            first = await _inspect(prompts[0])
            second = await _inspect(prompts[1])
            first_label, first_confidence, first_description = first
            second_label, second_confidence, second_description = second
            first_normalized = self._normalise_captcha_label(first_label or "")
            second_normalized = self._normalise_captcha_label(second_label or "")
            logger.info(
                "👁️ فحص الصورة: الأول=%r (%.2f، %s)، الثاني=%r (%.2f، %s)",
                first_label,
                first_confidence,
                first_description,
                second_label,
                second_confidence,
                second_description,
            )
            if (
                first_normalized
                and first_normalized == second_normalized
                and first_confidence >= 0.85
                and second_confidence >= 0.85
            ):
                return first_label
            logger.warning(
                "⚠️ رفض اختيار كابتشا الإيموجي: لا يوجد اتفاق بصري بثقة كافية"
            )
        except urllib.error.HTTPError as exc:
            logger.error(
                "❌ فشل GPT Vision للحساب %s: HTTP %s",
                phone_number,
                exc.code,
            )
        except Exception as exc:
            logger.warning(
                "⚠️ تعذر تحليل كابتشا الإيموجي عبر GPT Vision للحساب %s: %s",
                phone_number,
                exc,
            )
        return None

    async def _solve_number_captcha(
        self,
        bot_entity,
        text: str,
        buttons: list,
        phone_number: str,
    ) -> bool:
        """يحل كابتشا "اضغط على الرقم (XX)"."""
        target_number = self._extract_target_number(text)
        if not target_number:
            return False

        logger.info(
            "🔢 كابتشا الرقم: المطلوب الضغط على %s للحساب %s",
            target_number,
            phone_number,
        )

        target_norm = self._normalise_captcha_label(target_number)
        for btn in buttons:
            label = self._normalise_captcha_label(self._button_label(btn))
            if label == target_norm:
                try:
                    await btn.click()
                    logger.info(
                        "🖱️ ضغط على الرقم %s للحساب %s",
                        target_number,
                        phone_number,
                    )
                    return True
                except Exception as exc:
                    logger.warning("⚠️ فشل الضغط على زر الرقم: %s", exc)
                    return False

        logger.warning(
            "⚠️ لم أجد زراً مطابقاً للرقم %s. الأزرار: %s",
            target_number,
            [getattr(b, "text", "") for b in buttons],
        )
        return False

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

            points_cost = self.get_total(quantity, "points", len(context.user_data.get("raksh_channels") or []))
            stars_cost = self.get_total(quantity, "stars", len(context.user_data.get("raksh_channels") or []))

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

            total_cost = self.get_total(quantity, payment_method, len(context.user_data.get("raksh_channels") or []))
            await query.edit_message_text(
                f"📋 *تأكيد الطلب*\n\n"
                f"📢 القنوات الإجبارية: {len(context.user_data.get('raksh_channels', []))} قناة\n"
                f"🔗 {self.get_saved_link_label()}: `{context.user_data.get('raksh_link', '')}`\n"
                f"🔢 العدد: {quantity}\n"
                f"💳 طريقة الدفع: {'💰 نقاط' if payment_method == 'points' else '⭐ نجوم'}\n"
                f"💰 التكلفة: {total_cost} {'نقطة' if payment_method == 'points' else 'نجمة'}\n\n"
                f"{self.get_payment_warning()}\n\n"
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

            total_cost = self.get_total(quantity, payment_method, len(context.user_data.get("raksh_channels") or []))

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
                    f"{self.get_payment_warning()}\n\n"
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

    # ─── 4. حل التحقق المدمج (يدعم مشاركة الرقم + المنطق القديم) ───

    @staticmethod
    def _is_invitation_link_button(button) -> bool:
        """تمييز أزرار روابط الدعوة حتى لو كانت Callback وليست URL صريحاً."""
        button_url = getattr(button, "url", None)
        button_text = (getattr(button, "text", "") or "").strip().casefold()
        invitation_markers = (
            "رابط الدعوة",
            "رابط دعوة",
            "الدعوة",
            "دعوة",
            "invite",
            "invitation",
            "join link",
            "انضمام",
            "انضم",
            "رابط",
        )
        if any(marker in button_text for marker in invitation_markers):
            return True
        if not button_url:
            return False

        normalized_url = str(button_url).casefold()
        return bool(re.search(
            r"(?:https?://)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)",
            normalized_url,
        ))

    @staticmethod
    def _is_verification_success_text(value) -> bool:
        """يتحقق من نجاح صريح، ولا يعتبر عبارات الفشل نجاحاً."""
        text = str(value or "").strip().casefold()
        if not text:
            return False

        failure_markers = (
            "لم ينجح",
            "لم يتم",
            "لم يكتمل",
            "لم تكتمل",
            "ما تم",
            "لا نجاح",
            "لا يوجد نجاح",
            "لا يمكن",
            "غير ناجح",
            "غير صحيح",
            "التحقق غير مكتمل",
            "فشل",
            "فاشل",
            "خطأ في التحقق",
            "تعذر",
            "يتعذر",
            "verification failed",
            "not verified",
            "not successful",
            "unsuccessful",
            "failed",
            "failure",
            "invalid",
            "incorrect",
            "wrong answer",
            "try again",
        )
        if any(marker in text for marker in failure_markers):
            return False

        success_markers = (
            "تم التحقق",
            "نجح التحقق",
            "نجاح التحقق",
            "تم اجتياز التحقق",
            "اجتياز الكابتشا",
            "تم حل التحقق",
            "تم قبولك",
            "تم التسجيل بنجاح",
            "أنت لست روبوت",
            "لم تعد روبوت",
            "أنت بشري",
            "انت بشري",
            "verification successful",
            "verification complete",
            "verified successfully",
            "captcha solved",
            "captcha passed",
            "human verified",
            "you are verified",
            "access granted",
            "welcome to the group",
        )
        if any(marker.casefold() in text for marker in success_markers):
            return True
        return False

    @staticmethod
    def _looks_like_verification_message(message) -> bool:
        """يميّز تحققاً جديداً عن رسالة ترحيب أو رد عادي بعد فتح البوت."""
        text = (getattr(message, "message", "") or "").casefold()
        if getattr(message, "photo", None) or getattr(message, "document", None):
            return True
        buttons = [
            button
            for row in (getattr(message, "buttons", None) or [])
            for button in (row or [])
            if not ForcedRefAIService._is_invitation_link_button(button)
        ]
        markers = (
            "تحقق", "verify", "captcha", "كابتشا", "human", "بشر",
            "robot", "روبوت", "أدخل", "ادخل", "اكتب", "أجب",
            "اختر", "اضغط", "code", "كود", "رمز",
        )
        if any(marker in text for marker in markers):
            return True

        button_markers = (
            "تحقق", "verify", "captcha", "كابتشا", "human", "بشر",
            "robot", "روبوت", "check", "continue", "التالي", "متابعة",
        )
        return any(
            any(marker in (getattr(button, "text", "") or "").casefold()
                for marker in button_markers)
            for button in buttons
        )

    @staticmethod
    def _fallback_button_from_messages(messages):
        """إرجاع أول زر قابل للضغط لمسار البوتات التي لا تعرض تحققاً."""
        ordered_messages = sorted(
            (message for message in (messages or []) if not getattr(message, "out", False)),
            key=lambda message: getattr(message, "id", 0),
            reverse=True,
        )
        for message in ordered_messages:
            for row in getattr(message, "buttons", None) or []:
                for button in row or []:
                    if getattr(button, "url", None) and not getattr(button, "data", None):
                        continue
                    if (
                        KeyboardButtonRequestPhone is not None
                        and isinstance(button, KeyboardButtonRequestPhone)
                    ) or button.__class__.__name__ == "KeyboardButtonRequestPhone":
                        continue
                    if callable(getattr(button, "click", None)):
                        return button
        return None

    @staticmethod
    def _has_image_media(message) -> bool:
        """Return True for Telegram photo messages and image documents."""
        if getattr(message, "photo", None):
            return True
        media = getattr(message, "media", None)
        document = getattr(media, "document", None) if media else None
        mime_type = getattr(document, "mime_type", "") or ""
        return mime_type.startswith("image/")

    @staticmethod
    def _normalise_captcha_label(value: str) -> str:
        """Normalize button/custom-emoji labels before comparing them."""
        value = unicodedata.normalize("NFKC", str(value or "")).casefold()
        value = value.strip(" \t\r\n:：-—.,،؛!?؟")
        return re.sub(
            r"[\s\u200d\ufe0e\ufe0f\u20e3\U0001F3FB-\U0001F3FF]+",
            "",
            value,
        )

    @staticmethod
    def _button_label(button) -> str:
        """Return the visible label from Telethon's button wrappers."""
        labels = []
        for candidate in (button, getattr(button, "button", None)):
            label = getattr(candidate, "text", None) if candidate else None
            if label is not None and str(label) not in labels:
                labels.append(str(label))
        return " ".join(labels)

    @staticmethod
    def _normalise_math_text(value: str) -> str:
        """Normalize Arabic-Indic digits and common Unicode operators."""
        translation = str.maketrans(
            "٠١٢٣٤٥٦٧٨٩−–—﹣×✕✖÷",
            "0123456789----***/",
        )
        return unicodedata.normalize("NFKC", str(value or "")).translate(
            translation
        )

    @classmethod
    def _captcha_target_labels(cls, message, text: str) -> list:
        """Extract normal and Telegram custom-emoji targets from a challenge."""
        labels = []

        target_marker_match = re.search(
            r"(?:الرمز|العلامة|symbol|emoji|icon)\s*[:：-]?\s*([^\s،,.!?؟]+)",
            text,
            flags=re.IGNORECASE,
        )
        target_offset = (
            target_marker_match.start(1) if target_marker_match else None
        )

        if target_marker_match:
            labels.append(target_marker_match.group(1))
        else:
            labels.extend(re.findall(
                "[\U0001F300-\U0001FAFF\u2600-\u27BF\U0001F1E0-\U0001F1FF]",
                text,
            ))

        try:
            get_entities_text = getattr(message, "get_entities_text", None)
            if get_entities_text:
                for entity, entity_text in get_entities_text():
                    if (
                        entity.__class__.__name__ == "MessageEntityCustomEmoji"
                        and (
                            target_offset is None
                            or getattr(entity, "offset", 0) >= target_offset
                        )
                    ):
                        labels.append(entity_text)
        except Exception:
            pass

        return [
            label for label in labels
            if cls._normalise_captcha_label(label)
        ]

    async def _extract_image_captcha(self, client, message, phone_number: str) -> Optional[str]:
        """Download and recognize noisy numeric/alphanumeric image CAPTCHAs."""
        if not self._has_image_media(message):
            return None
        if ddddocr is None:
            logger.error("❌ مكتبة ddddocr غير مثبتة؛ لا يمكن حل صورة التحقق")
            return None

        global _CAPTCHA_OCR
        try:
            image_buffer = BytesIO()
            await client.download_media(message, file=image_buffer)
            image_bytes = image_buffer.getvalue()
            if not image_bytes:
                logger.warning("⚠️ تعذر تنزيل صورة التحقق للحساب %s", phone_number)
                return None

            if _CAPTCHA_OCR is None:
                _CAPTCHA_OCR = ddddocr.DdddOcr(show_ad=False, beta=True)

            def _normalise_ocr_result(raw_result) -> str:
                translated = str(raw_result or "").translate(
                    str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
                )
                return re.sub(r"[^A-Za-z0-9]", "", translated)

            def _encode_png(image) -> bytes:
                output = BytesIO()
                image.save(output, format="PNG", optimize=True)
                return output.getvalue()

            def _build_variants() -> list:
                variants = [("original", image_bytes)]
                if Image is None or ImageOps is None:
                    return variants

                with Image.open(BytesIO(image_bytes)) as opened:
                    source = ImageOps.exif_transpose(opened).convert("RGB")
                    width, height = source.size

                    scale = min(4.0, max(1.0, 720.0 / max(width, height, 1)))
                    if scale > 1.0:
                        source = source.resize(
                            (max(1, round(width * scale)), max(1, round(height * scale))),
                            Image.Resampling.LANCZOS,
                        )

                    gray = ImageOps.grayscale(source)
                    gray = ImageOps.autocontrast(gray, cutoff=1)
                    variants.append(("gray", _encode_png(gray)))
                    variants.append((
                        "gray_median",
                        _encode_png(gray.filter(ImageFilter.MedianFilter(size=3))),
                    ))

                    for channel_name, channel in (
                        ("red", source.getchannel("R")),
                        ("green", source.getchannel("G")),
                        ("blue", source.getchannel("B")),
                    ):
                        channel = ImageOps.autocontrast(channel, cutoff=1)
                        variants.append((channel_name, _encode_png(channel)))

                    for threshold in (110, 145, 180, 210):
                        binary = gray.point(
                            lambda value, limit=threshold:
                                255 if value >= limit else 0
                        )
                        variants.append((f"threshold_{threshold}", _encode_png(binary)))

                return variants

            variants = _build_variants()
            candidates = []
            for index, (variant_name, variant_bytes) in enumerate(variants):
                try:
                    raw_result = await asyncio.to_thread(
                        _CAPTCHA_OCR.classification,
                        variant_bytes,
                    )
                except Exception as variant_error:
                    logger.debug(
                        "OCR variant %s failed for %s: %s",
                        variant_name,
                        phone_number,
                        variant_error,
                    )
                    continue

                code = _normalise_ocr_result(raw_result)
                if 3 <= len(code) <= 12:
                    candidates.append((code, variant_name, index))

            if candidates:
                counts = {}
                for code, _variant_name, _index in candidates:
                    counts[code] = counts.get(code, 0) + 1
                best_code = min(
                    counts,
                    key=lambda code: (
                        -counts[code],
                        min(index for candidate, _name, index in candidates if candidate == code),
                    ),
                )
                best_count = counts[best_code]
                best_variant = next(
                    name for code, name, _index in candidates if code == best_code
                )
                logger.info(
                    "🖼️ تم حل صورة التحقق للحساب %s: %s "
                    "(اتفاق %s/%s، variant=%s)",
                    phone_number,
                    best_code,
                    best_count,
                    len(candidates),
                    best_variant,
                )
                return best_code

            logger.warning(
                "⚠️ لم تُنتج أي نسخة OCR صالحة للحساب %s (عدد النسخ=%s)",
                phone_number,
                len(variants),
            )
        except Exception as exc:
            logger.warning("⚠️ فشل تحليل صورة التحقق للحساب %s: %s", phone_number, exc)
        return None

    async def _solve_verification(
        self,
        client,
        bot_entity,
        phone_number: str,
        base_id: int = 0,
        start_param: str = "",
    ) -> bool:
        """حل التحقق بذكاء."""
        MAX_INITIAL_PROBE_ATTEMPTS = 2
        CHECK_INTERVAL = 2.0

        if not base_id:
            try:
                latest_messages = await client.get_messages(bot_entity, limit=1)
                base_id = latest_messages[0].id if latest_messages else 0
            except Exception:
                base_id = 0

        contact_request_msg = None
        initial_verification_messages = None
        last_probe_messages = []
        successful_probe = False
        for probe_index in range(MAX_INITIAL_PROBE_ATTEMPTS):
            try:
                messages = await client.get_messages(bot_entity, limit=5)
                successful_probe = True
                last_probe_messages = messages
            except Exception:
                if probe_index + 1 < MAX_INITIAL_PROBE_ATTEMPTS:
                    await asyncio.sleep(CHECK_INTERVAL)
                continue

            for msg in messages:
                if msg.out:
                    continue
                if base_id and msg.id <= base_id:
                    continue
                if msg.reply_markup:
                    for row in msg.reply_markup.rows:
                        for btn in row.buttons:
                            if (
                                KeyboardButtonRequestPhone is not None
                                and isinstance(btn, KeyboardButtonRequestPhone)
                            ) or btn.__class__.__name__ == "KeyboardButtonRequestPhone":
                                contact_request_msg = msg
                                break
                        if contact_request_msg:
                            break
                if contact_request_msg:
                    break
            if contact_request_msg:
                break

            incoming = [
                msg for msg in messages
                if not getattr(msg, "out", False)
                and (not base_id or msg.id > base_id)
            ]
            if any(self._looks_like_verification_message(msg) for msg in incoming):
                initial_verification_messages = messages
                break

            if probe_index + 1 < MAX_INITIAL_PROBE_ATTEMPTS:
                await asyncio.sleep(CHECK_INTERVAL)

        if not contact_request_msg and initial_verification_messages is None:
            return await self._complete_without_verification(
                client,
                bot_entity,
                phone_number,
                base_id=base_id,
                start_param=start_param,
                initial_messages=last_probe_messages if successful_probe else None,
            )

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
                    messages = await client.get_messages(bot_entity, limit=5)
                except Exception:
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue

                for msg in messages:
                    if msg.out:
                        continue
                    if base_id and msg.id <= base_id:
                        continue
                    buttons = []
                    if msg.reply_markup:
                        for row in msg.reply_markup.rows:
                            for btn in row.buttons:
                                if not self._is_invitation_link_button(btn):
                                    buttons.append(btn)
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
                    return False
            else:
                logger.info(
                    f"⏭️ تم تجاهل زر رابط الدعوة بعد مشاركة الرقم من {phone_number} "
                    "وسنواصل قراءة الرسائل الجديدة"
                )
                return await self._solve_legacy_verification(
                    client,
                    bot_entity,
                    phone_number,
                    base_id=base_id,
                    initial_messages=initial_verification_messages,
                )

            try:
                await asyncio.sleep(2.0)
                followup_messages = []
                async for msg in client.iter_messages(
                    bot_entity,
                    min_id=base_id,
                    reverse=True,
                ):
                    followup_messages.append(msg)
                logger.info(
                    f"🔄 إعادة قراءة رسائل التحقق بعد زر المتابعة: "
                    f"{len(followup_messages)} رسالة منذ ضغط الرابط من {phone_number}"
                )
                return await self._solve_legacy_verification(
                    client,
                    bot_entity,
                    phone_number,
                    base_id=base_id,
                    initial_messages=followup_messages,
                )
            except Exception as e:
                logger.warning(f"⚠️ تعذر قراءة المرحلة الثانية للتحقق: {e}")
                return False

        logger.info(f"🔍 لم يطلب البوت رقم هاتف، ننتقل إلى المنطق القديم لـ {phone_number}")
        return await self._solve_legacy_verification(
            client,
            bot_entity,
            phone_number,
            base_id=base_id,
            initial_messages=initial_verification_messages,
        )

    async def _complete_without_verification(
        self,
        client,
        bot_entity,
        phone_number: str,
        base_id: int = 0,
        start_param: str = "",
        initial_messages: Optional[list] = None,
    ) -> bool:
        """إنهاء إحالة البوتات التي لا تعرض نوع تحقق معروف."""

        async def _read_flow_messages():
            try:
                collected = []
                async for message in client.iter_messages(
                    bot_entity,
                    min_id=base_id,
                    reverse=True,
                ):
                    collected.append(message)
                return collected
            except Exception:
                try:
                    return await client.get_messages(bot_entity, limit=100)
                except Exception:
                    return []

        async def _verification_after_action(messages=None):
            current_messages = messages
            if current_messages is None:
                current_messages = await _read_flow_messages()

            incoming = [
                message for message in (current_messages or [])
                if not getattr(message, "out", False)
                and (not base_id or getattr(message, "id", 0) > base_id)
            ]
            for message in reversed(incoming):
                text = getattr(message, "message", "") or ""
                if self._is_verification_success_text(text):
                    logger.info(
                        "✅ وصلت إشارة نجاح من بوت الإحالة للحساب %s",
                        phone_number,
                    )
                    return True

            if any(self._looks_like_verification_message(message) for message in incoming):
                logger.info(
                    "🔍 ظهر تحقق بعد fallback للحساب %s؛ سيتم حله",
                    phone_number,
                )
                return await self._solve_legacy_verification(
                    client,
                    bot_entity,
                    phone_number,
                    base_id=base_id,
                    initial_messages=current_messages,
                )
            return None

        async def _click_any_button(messages=None) -> bool:
            current_messages = messages if messages is not None else await _read_flow_messages()
            button = self._fallback_button_from_messages(current_messages)
            if not button:
                return False
            try:
                await button.click()
                logger.info(
                    "🖱️ تم الضغط على زر fallback للحساب %s: %s",
                    phone_number,
                    getattr(button, "text", ""),
                )
                return True
            except Exception as exc:
                logger.warning(
                    "⚠️ تعذر الضغط على زر fallback للحساب %s: %s",
                    phone_number,
                    exc,
                )
                return False

        async def _send_start():
            try:
                await client(StartBotRequest(
                    bot=bot_entity,
                    peer=bot_entity,
                    start_param=start_param or "",
                ))
                logger.info("▶️ تم إرسال Start fallback للحساب %s", phone_number)
            except Exception as exc:
                logger.warning(
                    "⚠️ تعذر إرسال Start fallback للحساب %s: %s",
                    phone_number,
                    exc,
                )

        current_messages = (
            initial_messages
            if initial_messages is not None
            else await _read_flow_messages()
        )
        first_button = self._fallback_button_from_messages(current_messages)

        if not first_button:
            await _send_start()
            await asyncio.sleep(2.0)
            result = await _verification_after_action()
            return True if result is None else result

        await _click_any_button(current_messages)
        await asyncio.sleep(2.0)
        result = await _verification_after_action()
        if result is not None:
            return result

        await _send_start()
        await asyncio.sleep(2.0)
        result = await _verification_after_action()
        if result is not None:
            return result

        current_messages = await _read_flow_messages()
        if self._fallback_button_from_messages(current_messages):
            await _click_any_button(current_messages)
            await asyncio.sleep(2.0)
            result = await _verification_after_action()
            if result is not None:
                return result

        logger.info(
            "✅ لم يظهر أي تحقق بعد fallback للحساب %s؛ تُحتسب الإحالة ناجحة",
            phone_number,
        )
        return True

    async def _solve_legacy_verification(
        self,
        client,
        bot_entity,
        phone_number: str,
        base_id: int = 0,
        initial_messages: Optional[list] = None,
    ) -> bool:
        """المنطق القديم + كابتشا الأرقام والإيموجي."""
        processed_fingerprints = set()

        if not base_id:
            try:
                out_messages = await client.get_messages(bot_entity, limit=10)
                for msg in out_messages:
                    if msg.out:
                        base_id = msg.id
                        logger.info(f"🔑 نقطة البداية هي رسالة الحساب رقم: {base_id}")
                        break
            except Exception as e:
                logger.warning(f"تعذر تحديد الرسالة المرجعية: {e}")

        saw_verification = False
        quiet_attempts = 0
        verification_started_at = None
        max_verification_seconds = 180.0
        loop = asyncio.get_running_loop()

        def _message_fingerprint(message) -> str:
            parts = [
                str(getattr(message, "id", "")),
                str(getattr(message, "message", "") or ""),
                str(getattr(message, "edit_date", "") or ""),
                "image" if self._has_image_media(message) else "no-image",
            ]
            for row in getattr(message, "buttons", None) or []:
                for button in row:
                    parts.append(
                        "|".join(
                            [
                                str(getattr(button, "text", "") or ""),
                                str(getattr(button, "data", "") or ""),
                                str(getattr(button, "url", "") or ""),
                            ]
                        )
                    )
            return "\x1f".join(parts)

        async def _verification_action_succeeded(message, button=None) -> bool:
            try:
                for item in await _read_flow_messages():
                    if self._is_verification_success_text(
                        getattr(item, "message", "") or getattr(item, "text", "") or ""
                    ):
                        return True
            except Exception:
                pass
            return False

        async def _read_flow_messages():
            try:
                collected = []
                async for msg in client.iter_messages(
                    bot_entity,
                    min_id=base_id,
                    reverse=True,
                ):
                    collected.append(msg)
                return collected
            except Exception:
                try:
                    return await client.get_messages(
                        bot_entity, limit=100, min_id=base_id
                    )
                except Exception:
                    return []

        while True:
            if (
                verification_started_at is not None
                and loop.time() - verification_started_at >= max_verification_seconds
            ):
                logger.warning(
                    "⏱️ انتهت مهلة التحقق للحساب %s بعد %.0f ثانية",
                    phone_number,
                    max_verification_seconds,
                )
                return False
            try:
                if initial_messages is not None:
                    messages = initial_messages
                    initial_messages = None
                else:
                    messages = await _read_flow_messages()
            except Exception as exc:
                if "two different IP" in str(exc) or "AuthKeyDuplicated" in str(exc):
                    logger.error(f"⚠️ الجلسة {phone_number} تستخدم من IP مختلف - سيتم تعطيلها")
                    _mark_raksh_session_unauthorized(phone_number)
                    return False
                await asyncio.sleep(2.0)
                continue

            incoming_messages = [msg for msg in messages if not msg.out]
            incoming_messages.sort(key=lambda m: m.id)

            for msg in reversed(incoming_messages):
                if msg.id <= base_id:
                    continue
                success_text = (getattr(msg, "message", "") or "").strip().casefold()
                if self._is_verification_success_text(success_text):
                    logger.info(f"✅ تم تأكيد التحقق من {phone_number}: {success_text[:120]}")
                    return True

            new_messages = [
                msg for msg in incoming_messages
                if msg.id > base_id
                and _message_fingerprint(msg) not in processed_fingerprints
            ]
            if not new_messages:
                quiet_attempts += 1
                if not saw_verification and quiet_attempts >= 30:
                    logger.info(
                        "ℹ️ لم يصل تحقق جديد بعد ضغط الرابط للحساب %s؛ تُحتسب الإحالة ناجحة",
                        phone_number,
                    )
                    return True
                await asyncio.sleep(2.0)
                continue
            quiet_attempts = 0

            candidate_messages = new_messages

            code_prompt_markers = (
                "النص التالي",
                "أرسل النص",
                "ارسل النص",
                "أرسل الكود",
                "ارسل الكود",
                "send the text",
                "send the code",
                "retype",
                "type",
            )
            verification_message = next(
                (
                    msg for msg in reversed(candidate_messages)
                    if self._has_image_media(msg)
                ),
                None,
            )
            if verification_message is None:
                verification_message = next(
                    (
                        msg for msg in candidate_messages
                        if not (getattr(msg, "message", "") or "").strip().startswith("/")
                        and any(
                            marker in (getattr(msg, "message", "") or "").casefold()
                            for marker in code_prompt_markers
                        )
                        and _extract_code_from_text(getattr(msg, "message", "") or "")
                    ),
                    None,
                )

            if verification_message is None:
                for msg in candidate_messages:
                    msg_text = getattr(msg, 'message', '') or ''
                    if msg_text.strip().startswith("/"):
                        continue
                    if any(kw in msg_text for kw in ["أرسل", "التالي", "بالضبط", "اكتب", "retype", "type", "اضغط", "اختر", "انقر"]):
                        verification_message = msg
                        break

            if verification_message is None:
                verification_message = next(
                    (msg for msg in reversed(candidate_messages) if not getattr(msg, 'message', '').strip().startswith("/")),
                    None
                )

            if verification_message is None:
                await asyncio.sleep(2.0)
                continue

            if not self._looks_like_verification_message(verification_message):
                processed_fingerprints.add(_message_fingerprint(verification_message))
                await asyncio.sleep(2.0)
                continue
            saw_verification = True
            if verification_started_at is None:
                verification_started_at = loop.time()

            text = getattr(verification_message, 'message', '') or ''
            image_code = await self._extract_image_captcha(
                client,
                verification_message,
                phone_number,
            )
            if image_code:
                try:
                    await client.send_message(bot_entity, image_code)
                    logger.info("✅ تم إرسال حل صورة التحقق للحساب %s", phone_number)
                    processed_fingerprints.add(_message_fingerprint(verification_message))
                    await asyncio.sleep(2.0)
                    continue
                except Exception as exc:
                    logger.warning("⚠️ تعذر إرسال حل صورة التحقق للحساب %s: %s", phone_number, exc)
                    await asyncio.sleep(2.0)
                    continue

            math_text = self._normalise_math_text(text)
            math_match = re.search(
                r"(?<!\d)(\d{1,9})\s*([+\-*/])\s*(\d{1,9})"
                r"\s*=\s*[?؟]?",
                math_text,
            )
            if math_match:
                try:
                    a = int(math_match.group(1))
                    op = math_match.group(2)
                    b = int(math_match.group(3))
                    if op == "+":
                        result = str(a + b)
                    elif op == "-":
                        result = str(a - b)
                    elif op == "*":
                        result = str(a * b)
                    elif b == 0:
                        result = None
                    else:
                        quotient = a / b
                        result = (
                            str(int(quotient))
                            if quotient.is_integer()
                            else str(quotient)
                        )
                    if result is not None:
                        await client.send_message(bot_entity, result)
                        logger.info(
                            "✅ تم حل المسألة: %s %s %s = %s",
                            a,
                            op,
                            b,
                            result,
                        )
                        processed_fingerprints.add(_message_fingerprint(verification_message))
                        await asyncio.sleep(2.0)
                        continue
                except Exception:
                    logger.warning("⚠️ تعذر حل المسألة الحسابية: %r", text[:160])

            send_text = _extract_code_from_text(text)
            if send_text:
                try:
                    await client.send_message(bot_entity, send_text)
                    logger.info(f"✅ تم إرسال الكود: {send_text}")
                    processed_fingerprints.add(_message_fingerprint(verification_message))
                    await asyncio.sleep(2.0)
                    continue
                except Exception:
                    await asyncio.sleep(2.0)
                    continue

            if math_match:
                continue

            # 3. الضغط على الأزرار
            buttons = []
            invitation_buttons = []
            for row in getattr(verification_message, 'buttons', None) or []:
                for btn in row:
                    if self._is_invitation_link_button(btn):
                        invitation_buttons.append(btn)
                    else:
                        buttons.append(btn)

            # ═══════════════════════════════════════════════════
            # 3أ. كابتشا "اضغط على الرقم (XX)"
            # ═══════════════════════════════════════════════════
            if buttons and self._extract_target_number(text):
                clicked = await self._solve_number_captcha(
                    bot_entity, text, buttons, phone_number
                )
                if clicked:
                    processed_fingerprints.add(
                        _message_fingerprint(verification_message)
                    )
                    await asyncio.sleep(2.0)
                    continue

            # ═══════════════════════════════════════════════════
            # 3ب. كابتشا "اختر الإيموجي المطابق للصورة"
            # ═══════════════════════════════════════════════════
            emoji_markers = ("إيموجي", "ايموجي", "الإيموجي", "الايموجي",
                             "emoji", "الرمز التعبيري", "الصورة أعلاه",
                             "المطابق للصورة", "اختر")
            if (
                buttons
                and self._has_image_media(verification_message)
                and any(m in text for m in emoji_markers)
            ):
                clicked = await self._solve_emoji_captcha(
                    client,
                    bot_entity,
                    verification_message,
                    text,
                    buttons,
                    phone_number,
                )
                if clicked:
                    processed_fingerprints.add(
                        _message_fingerprint(verification_message)
                    )
                    await asyncio.sleep(2.0)
                    continue

            # ═══════════════════════════════════════════════════
            # 3ج. المنطق القديم
            # ═══════════════════════════════════════════════════
            button_clicked = False
            if buttons:
                prioritized = []
                target_labels = {
                    self._normalise_captcha_label(label)
                    for label in self._captcha_target_labels(
                        verification_message,
                        text,
                    )
                }
                button_labels = {
                    id(button): self._normalise_captcha_label(
                        self._button_label(button)
                    )
                    for button in buttons
                }

                exact = [
                    button for button in buttons
                    if button_labels.get(id(button)) in target_labels
                    and button_labels.get(id(button))
                ]
                prioritized.extend(exact)

                target_tail = text.casefold()
                marker_positions = [
                    target_tail.rfind(marker)
                    for marker in ("الرمز", "العلامة", "symbol", "emoji", "icon")
                ]
                marker_position = max(marker_positions) if marker_positions else -1
                if marker_position >= 0:
                    target_tail = target_tail[marker_position:]
                tail_matches = [
                    button for button in buttons
                    if button not in prioritized
                    and button_labels.get(id(button))
                    and len(button_labels[id(button)]) >= 1
                    and button_labels[id(button)] in self._normalise_captcha_label(target_tail)
                ]
                prioritized.extend(tail_matches)

                for target_label in target_labels:
                    prioritized.extend(
                        button for button in buttons
                        if button not in prioritized
                        and target_label
                        and (
                            target_label in button_labels.get(id(button), "")
                            or button_labels.get(id(button), "") in target_label
                        )
                    )

                verify_keywords = ['تحقق', 'verify', 'اضغط هنا', 'continue', 'التالي', 'متابعة']
                verify_buttons = [
                    b for b in buttons
                    if any(
                        kw in self._button_label(b).casefold()
                        for kw in verify_keywords
                    )
                    and b not in prioritized
                ]
                prioritized.extend(verify_buttons)

                if not prioritized:
                    logger.warning(
                        "⚠️ تعذر تحديد زر الكابتشا؛ النص=%r، الأزرار=%r، "
                        "الأهداف=%r",
                        text[:160],
                        [getattr(button, "text", "") for button in buttons],
                        sorted(target_labels),
                    )
                    processed_fingerprints.add(_message_fingerprint(verification_message))
                    if invitation_buttons:
                        logger.info(
                            f"⏭️ تم تجاهل {len(invitation_buttons)} زر رابط دعوة "
                            f"في الرسالة {verification_message.id}"
                        )
                    await asyncio.sleep(2.0)
                    continue

                for btn in prioritized:
                    try:
                        callback_result = await btn.click()
                        logger.info(f"🖱️ تم الضغط على الزر: {getattr(btn, 'text', '')}")
                        processed_fingerprints.add(_message_fingerprint(verification_message))
                        callback_text = getattr(callback_result, "message", "")
                        if not callback_text:
                            callback_text = getattr(callback_result, "alert", "")
                        if self._is_verification_success_text(callback_text):
                            logger.info(
                                "✅ أكد رد callback اكتمال التحقق للحساب %s: %s",
                                phone_number,
                                str(callback_text)[:120],
                            )
                            return True
                        await asyncio.sleep(2.0)
                        if await _verification_action_succeeded(
                            verification_message, btn
                        ):
                            logger.info(
                                "✅ اختفت أزرار التحقق/وصلت إشارة نجاح للحساب %s",
                                phone_number,
                            )
                            return True
                        button_clicked = True
                        break
                    except Exception:
                        await asyncio.sleep(2.0)
                        continue

            if button_clicked:
                continue

            processed_fingerprints.add(_message_fingerprint(verification_message))
            await asyncio.sleep(2.0)

    # ─── 5. التنفيذ الرئيسي ───

    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ إحالة بوت إجباري مع تحقق شامل."""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=20)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"

            channels = params.get("channel_ref") or []
            if channels:
                for channel_ref in channels:
                    try:
                        await _join_channel_and_schedule_leave(client, channel_ref, session.get("phone_number"))
                        await asyncio.sleep(1.0)
                    except Exception as e:
                        logger.warning(f"فشل الانضمام للقناة {channel_ref}: {e}")

            bot_username, start_param = _parse_bot_link(params["link"])
            if not bot_username:
                return False, "رابط البوت غير صحيح"

            clean_username = bot_username.lstrip("@").strip()
            if _is_no_action_bot(clean_username):
                logger.info(f"ℹ️ تم تجاوز فتح البوت المستثنى للحساب {session['phone_number']}: @{clean_username}")
                return True, f"✅ تمت الإحالة من {session['phone_number']}"

            resolved = await client(ResolveUsernameRequest(clean_username))
            bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]

            verification_base_id = 0
            try:
                latest_messages = await client.get_messages(bot_entity, limit=1)
                verification_base_id = latest_messages[0].id if latest_messages else 0
            except Exception as e:
                logger.warning(f"تعذر تحديد نقطة بداية رابط الإحالة: {e}")

            try:
                latest_messages = await client.get_messages(bot_entity, limit=1)
                activation_base_id = latest_messages[0].id if latest_messages else 0
            except Exception:
                activation_base_id = 0

            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param or ""
            ))
            await asyncio.sleep(2.0)

            if await _raksh_has_duplicate_response(
                client, bot_entity, after_id=activation_base_id
            ):
                logger.info(
                    f"ℹ️ ظهر رد تكرار من البوت، لكن الإحالة تُحتسب ناجحة "
                    f"بعد فتحه للحساب {session['phone_number']}"
                )

            try:
                verification_success = await self._solve_verification(
                    client,
                    bot_entity,
                    session.get("phone_number"),
                    base_id=verification_base_id,
                    start_param=start_param or "",
                )
                if verification_success:
                    logger.info(
                        f"✅ اكتمل التحقق بعد فتح البوت للحساب "
                        f"{session['phone_number']}"
                    )
                else:
                    logger.warning(
                        f"⚠️ لم يكتمل التحقق للحساب "
                        f"{session['phone_number']}؛ لن تُحتسب الإحالة ناجحة"
                    )
                    return False, "❌ لم يكتمل تحقق البوت."
            except Exception as verification_error:
                logger.warning(
                    f"⚠️ تعذر إكمال التحقق بعد فتح البوت: {verification_error}"
                )
                return False, "❌ تعذر إكمال تحقق البوت."

            return True, f"✅ تمت الإحالة من {session['phone_number']}"
        except Exception as e:
            if "two different IP" in str(e) or "AuthKeyDuplicated" in str(e):
                logger.error(f"⚠️ الجلسة {session.get('phone_number')} تستخدم من IP مختلف - سيتم تعطيلها")
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة تستخدم من IP مختلف - تم تعطيلها مؤقتاً"
            return False, f"❌ فشل: {str(e)}"
        finally:
            await client.disconnect()
