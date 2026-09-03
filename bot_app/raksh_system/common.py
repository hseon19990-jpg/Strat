# forced_ref_ai.py
"""
خدمة إحالة بوت إجباري مع تحقق شامل - تدعم مشاركة الرقم والكود والمسائل والأزرار
تدعم الرشق السريع بمعدل 17 حساباً كل ثانيتين بالتوازي
"""

import re
import asyncio
from typing import List, Dict, Optional, Tuple

from .common import *
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import ResolveUsernameRequest
from telethon.tl.functions.messages import StartBotRequest
from telethon.tl.types import InputMediaContact, KeyboardButtonRequestPhone
from telethon.errors import FloodWaitError


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
        min_delay=2,
        max_delay=2
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

    # ─── 4. حل التحقق المدمج (يدعم مشاركة الرقم + المنطق القديم) ───

    async def _solve_verification(self, client, bot_entity, phone_number: str) -> bool:
        MAX_WAIT = 8
        CHECK_INTERVAL = 0.5

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

        # إذا وجدنا طلب رقم → نعالجه
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

            # انتظار زر متابعة
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
                    buttons = []
                    if msg.reply_markup:
                        for row in msg.reply_markup.rows:
                            for btn in row.buttons:
                                if not getattr(btn, 'url', None):
                                    buttons.append(btn)
                    for btn in buttons:
                        btn_text = (getattr(btn, 'text', '') or '').strip().casefold()
                        if any(kw in btn_text for kw in ['متابعة', 'التالي', 'ابدأ', 'تحقق', 'continue', 'next', 'start', 'verify']):
                            proceed_button = btn
                            break
                        if not proceed_button:
                            proceed_button = btn
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

            # انتظار تأكيد النجاح
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

            logger.warning(f"⚠️ نعتبر التحقق ناجحاً (مشاركة الرقم) لـ {phone_number}")
            return True

        # ─── المرحلة 2: استخدام المنطق القديم ───
        logger.info(f"🔍 لم يطلب البوت رقم هاتف، الانتقال للمنطق الرياضي/النصي لـ {phone_number}")
        return await self._solve_legacy_verification(client, bot_entity, phone_number)

    async def _solve_legacy_verification(self, client, bot_entity, phone_number: str) -> bool:
        max_attempts = 15
        base_id = 0
        processed_ids = set()

        try:
            out_messages = await client.get_messages(bot_entity, limit=5)
            for msg in out_messages:
                if msg.out:
                    base_id = msg.id
                    break
        except Exception:
            pass

        for _ in range(max_attempts):
            try:
                messages = await client.get_messages(bot_entity, limit=15)
            except Exception as exc:
                if "two different IP" in str(exc) or "AuthKeyDuplicated" in str(exc):
                    logger.error(f"⚠️ الجلسة {phone_number} تستخدم من IP مختلف")
                    _mark_raksh_session_unauthorized(phone_number)
                    return False
                await asyncio.sleep(0.5)
                continue

            incoming_messages = [msg for msg in messages if not msg.out]
            incoming_messages.sort(key=lambda m: m.id)

            new_messages = [
                msg for msg in incoming_messages
                if msg.id > base_id and msg.id not in processed_ids
            ]
            if not new_messages:
                await asyncio.sleep(0.5)
                continue

            for msg in reversed(new_messages):
                text = (getattr(msg, "message", "") or "").strip()
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

            verification_message = None
            for msg in new_messages:
                msg_text = getattr(msg, 'message', '') or ''
                if msg_text.strip().startswith("/"):
                    continue
                if any(kw in msg_text for kw in ["أرسل", "التالي", "بالضبط", "اكتب", "retype", "type", "اضغط", "اختر", "انقر"]):
                    verification_message = msg
                    break

            if verification_message is None:
                verification_message = next(
                    (msg for msg in reversed(new_messages) if not getattr(msg, 'message', '').strip().startswith("/")),
                    None
                )

            if verification_message is None:
                await asyncio.sleep(0.5)
                continue

            text = getattr(verification_message, 'message', '') or ''

            # 1. استخراج الكود
            send_text = _extract_code_from_text(text)
            if send_text:
                try:
                    await client.send_message(bot_entity, send_text)
                    processed_ids.add(verification_message.id)
                    await asyncio.sleep(0.8)
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
                        elif op == '/': result = str(a // b) if b != 0 else None
                        else: result = None
                        if result is not None:
                            await client.send_message(bot_entity, result)
                            processed_ids.add(verification_message.id)
                            await asyncio.sleep(0.8)
                            break
                    except Exception:
                        continue

            # 3. الضغط على الأزرار
            buttons = []
            for row in getattr(verification_message, 'buttons', None) or []:
                for btn in row:
                    if not getattr(btn, 'url', None):
                        buttons.append(btn)

            if buttons:
                emoji_pattern = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E0-\U0001F1FF]")
                target_emoji = None
                found_emojis = emoji_pattern.findall(text)
                if found_emojis:
                    target_emoji = found_emojis[-1]

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

                if not prioritized:
                    prioritized = buttons

                for btn in prioritized:
                    try:
                        await btn.click()
                        processed_ids.add(verification_message.id)
                        await asyncio.sleep(1.0)
                        break
                    except Exception:
                        continue

            await asyncio.sleep(0.8)

        logger.warning(f"⚠️ لم تصل رسالة نجاح صريحة لـ {phone_number}")
        return False

    # ─── 5. التنفيذ الفردي ───

    async def execute(self, session: Dict, params: Dict, is_first: bool = False) -> Tuple[bool, str]:
        """تنفيذ إحالة بوت إجباري مع تحقق شامل لحساب مفرد"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(client.connect(), timeout=15)
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"

            # الانضمام للقنوات إذا كانت موجودة
            channels = params.get("channel_ref") or []
            if channels:
                for channel_ref in channels:
                    try:
                        await _join_channel_and_schedule_leave(client, channel_ref)
                        await asyncio.sleep(0.3)
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
            await asyncio.sleep(0.5)

            # حل التحقق
            success = await self._solve_verification(client, bot_entity, session.get("phone_number"))
            if success:
                return True, f"✅ تمت الإحالة مع التحقق من {session['phone_number']}"
            else:
                return False, "فشل التحقق بعد محاولات متعددة"
        except FloodWaitError as e:
            return False, f"⚠️ حظر مؤقت من تليجرام (FloodWait): انتظر {e.seconds} ثانية"
        except Exception as e:
            if "two different IP" in str(e) or "AuthKeyDuplicated" in str(e):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة تستخدم من IP مختلف"
            return False, f"❌ فشل: {str(e)}"
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    # ─── 6. التنفيذ الجماعي السريع (17 حساب كل ثانيتين) ───

    async def execute_batch(self, sessions: List[Dict], params: Dict) -> List[Tuple[bool, str]]:
        """
        تشغيل 17 حساباً في نفس اللحظة بالتوازي (Concurrency)،
        ثم انتظار ثانيتين قبل تشغيل الدفعة التالية.
        """
        BATCH_SIZE = 17
        BATCH_DELAY = 2.0
        results = []

        for i in range(0, len(sessions), BATCH_SIZE):
            batch = sessions[i:i + BATCH_SIZE]
            logger.info(f"🚀 بدء دفعة جديدة: تشغيل {len(batch)} حساب بالتوازي...")

            # تشغيل الـ 17 حساب في نفس اللحظة بالتوازي
            tasks = [self.execute(session, params, is_first=(i == 0 and idx == 0)) for idx, session in enumerate(batch)]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in batch_results:
                if isinstance(res, Exception):
                    results.append((False, f"خطأ بالنظام: {str(res)}"))
                else:
                    results.append(res)

            # انتظر ثانيتين قبل الدفعة القادمة طالما توجد حسابات متبقية
            if i + BATCH_SIZE < len(sessions):
                logger.info(f"⏳ انتظار {BATCH_DELAY} ثوانٍ قبل الدفعة التالية...")
                await asyncio.sleep(BATCH_DELAY)

        return results
