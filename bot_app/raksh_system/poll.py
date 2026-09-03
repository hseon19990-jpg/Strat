from .common import *

class PollService(RakshService):
    """خدمة رشق استفتاء - تدفق مخصص حسب الطلب"""

    service_type = "poll"
    label = "📊 رشق استفتاء"
    config = ServiceConfig(
        name=label,
        price_points=30,
        points_quantity=1,
        price_stars=5,
        stars_quantity=1,
        has_channel=True,
        has_reaction=False,
        has_ai=False,
        needs_link=True,
        min_delay=0,
        max_delay=0,
        max_concurrent=6
    )

    def get_link_instruction(self) -> str:
        return "أرسل رابط الاستفتاء: https://t.me/channel/123"

    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        if not all(_parse_post_link(value)):
            return "⚠️ الرابط غير صحيح لهذه الخدمة.\n\nأرسل: https://t.me/channel/123"
        return None

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
            [InlineKeyboardButton("⏭️ تخطي (بدون قنوات)", callback_data="raksh_poll:skip_channels")],
            [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
        ])

    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        """معالجة النص لخدمة الاستفتاء"""

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
                f"🔗 *أرسل رابط الاستفتاء:*\n"
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
            context.user_data["raksh_step"] = "poll_option"

            await update.message.reply_text(
                f"✅ تم حفظ الرابط.\n\n"
                f"🔢 *أرسل رقم الخيار الذي تريد التصويت عليه:*\n"
                f"مثال: 1 (إذا كان الاستفتاء لديه 4 خيارات، أرسل رقمًا من 1 إلى 4)",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        if state == "poll_option":
            try:
                option_number = int(text)
            except ValueError:
                await update.message.reply_text(
                    "⚠️ أرسل رقماً صحيحاً (مثل 1، 2، 3...).",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True

            if option_number < 1:
                await update.message.reply_text(
                    "⚠️ الرقم يجب أن يكون 1 أو أكثر.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True

            context.user_data["raksh_poll_option"] = str(option_number)
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
                f"✅ تم حفظ الخيار: {option_number}.\n\n"
                f"🔢 *أرسل عدد الأصوات المطلوبة:*\n"
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
                f"🔗 الرابط: `{context.user_data['raksh_link']}`\n"
                f"🗳 الخيار: {context.user_data['raksh_poll_option']}\n"
                f"🔢 العدد: {quantity}\n\n"
                f"💳 *اختر طريقة الدفع:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"💰 دفع بالنقاط ({points_cost} نقطة)",
                            callback_data=f"raksh:pay:points:{self.service_type}:{quantity}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                            callback_data=f"raksh:pay:stars:{self.service_type}:{quantity}"
                        )
                    ],
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        return False

    async def handle_callback(self, update, context, query, data_parts, user, is_own) -> bool:
        """معالجة الأزرار لخدمة الاستفتاء"""
        if data_parts[0] == "skip_channels":
            context.user_data["raksh_channels"] = []
            context.user_data["raksh_step"] = "link"

            await query.edit_message_text(
                f"✅ تم تخطي القنوات.\n\n"
                f"🔗 *أرسل رابط الاستفتاء:*\n"
                f"{self.get_link_instruction()}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        return False

    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ رشق استفتاء - يدعم الاستفتاءات الأصلية والأزرار"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"

            # الانضمام للقنوات الإجبارية
            if params.get("channel_ref"):
                for channel_ref in params["channel_ref"]:
                    await _join_channel_and_schedule_leave(client, channel_ref, leave_after_seconds=86400)
                    await asyncio.sleep(0.5)

            # تحليل رابط الاستفتاء
            channel_ref, msg_id = _parse_post_link(params["link"])
            if not channel_ref:
                return False, "رابط الاستفتاء غير صحيح"

            entity = await client.get_entity(channel_ref)

            # الانضمام للقناة المستهدفة إذا كانت قناة
            if hasattr(entity, 'megagroup') and not entity.megagroup:
                try:
                    await client(JoinChannelRequest(entity))
                    await asyncio.sleep(0.5)
                except Exception:
                    pass

            # جلب الرسالة
            message = await client.get_messages(entity, ids=msg_id)
            if isinstance(message, (list, tuple)):
                message = message[0] if message else None
            if not message:
                return False, "الاستفتاء غير موجود"

            option_request = params.get("poll_option", "1")
            option_number = int(option_request)

            # 1️⃣ محاولة التصويت كاستفتاء أصلي
            poll = getattr(message, "poll", None)
            if poll:
                answers = getattr(poll, "answers", [])
                if answers:
                    option = _select_poll_option(answers, option_request)
                    if option:
                        success = await _send_vote_and_check(client, entity, msg_id, option)
                        if success:
                            return True, f"✅ تم التصويت من {session['phone_number']}"
                        else:
                            return False, "تعذر تأكيد التصويت"
                    else:
                        return False, f"الخيار {option_request} غير موجود في الاستفتاء"
                else:
                    return False, "الاستفتاء ليس له خيارات"

            # 2️⃣ إذا لم يكن استفتاء أصلي، نتعامل مع الأزرار
            buttons = getattr(message, "buttons", None) or []
            if not buttons:
                return False, "لا يوجد استفتاء أو أزرار تصويت في هذا المنشور"

            # البحث عن زر الخيار المطلوب
            target_button = None
            # البحث بالنص المطابق للرقم
            for row in buttons:
                for btn in row:
                    btn_text = (getattr(btn, "text", "") or "").strip()
                    # إذا كان الزر نصه رقم أو يبدأ برقم الخيار
                    if btn_text == option_request or btn_text.startswith(f"{option_request}.") or btn_text.startswith(f"{option_request} "):
                        target_button = btn
                        break
                if target_button:
                    break

            # إذا لم نجد، نحاول البحث بالترتيب (الزر الأول = الخيار 1)
            if not target_button:
                flat_buttons = [btn for row in buttons for btn in row if not getattr(btn, "url", None)]
                if 1 <= option_number <= len(flat_buttons):
                    target_button = flat_buttons[option_number - 1]

            if not target_button:
                return False, f"الخيار {option_request} غير موجود"

            # الضغط على زر الخيار
            try:
                await target_button.click()
                await asyncio.sleep(1.0)
            except Exception as e:
                return False, f"فشل الضغط على زر الخيار: {str(e)}"

            # البحث عن زر تأكيد/تصويت
            confirmation_buttons = []
            for row in buttons:
                for btn in row:
                    btn_text = (getattr(btn, "text", "") or "").lower()
                    if any(word in btn_text for word in ["تأكيد", "تصويت", "confirm", "vote", "send", "إرسال"]):
                        confirmation_buttons.append(btn)

            # الضغط على زر التأكيد إذا وجد
            if confirmation_buttons:
                try:
                    await confirmation_buttons[0].click()
                    await asyncio.sleep(1.0)
                except Exception:
                    pass

            return True, f"✅ تم التصويت من {session['phone_number']}"

        except Exception as e:
            return False, f"❌ فشل التصويت: {str(e)}"
        finally:
            await client.disconnect()
