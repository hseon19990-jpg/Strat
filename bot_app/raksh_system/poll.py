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
        min_delay=0,          # بدون تأخير (سرعة عالية)
        max_delay=0,
        max_concurrent=6      # 6 حسابات في نفس الوقت
    )

    # ─── تعليمات الرابط ───
    def get_link_instruction(self) -> str:
        return "أرسل رابط الاستفتاء: https://t.me/channel/123"

    # ─── التحقق من الرابط ───
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        if not all(_parse_post_link(value)):
            return "⚠️ الرابط غير صحيح لهذه الخدمة.\n\nأرسل: https://t.me/channel/123"
        return None

    # ─── بداية التدفق (القنوات الإجبارية) ───
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

    # ─── دالة جلب خيارات الاستفتاء من الرابط ───
    async def _fetch_poll_options(self, link: str) -> Optional[List[str]]:
        """جلب خيارات الاستفتاء المتاحة من الرابط"""
        channel_ref, msg_id = _parse_post_link(link)
        if not channel_ref or not msg_id:
            return None

        # استخدام أول جلسة متاحة للاستعلام
        sessions = _get_sessions_for_service(self.service_type)
        if not sessions:
            return None

        client = TelegramClient(StringSession(sessions[0]["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(client.connect(), timeout=15)
            entity = await asyncio.wait_for(client.get_entity(channel_ref), timeout=8)
            message = await asyncio.wait_for(client.get_messages(entity, ids=msg_id), timeout=8)

            if not message:
                return None
            poll = getattr(message, "poll", None)
            if not poll:
                return None
            answers = getattr(poll, "answers", [])
            if not answers:
                return None

            # تحويل الخيارات إلى قائمة نصوص (رقم + نص الخيار)
            result = []
            for idx, ans in enumerate(answers, start=1):
                text = getattr(ans, "text", str(ans))
                result.append(f"{idx}. {text}")
            return result
        except Exception as e:
            logger.warning(f"فشل جلب خيارات الاستفتاء: {e}")
            return None
        finally:
            await client.disconnect()

    # ─── معالجة النصوص (تدفق جديد) ───
    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        """معالجة النص لخدمة الاستفتاء"""

        # 1️⃣ استقبال القنوات الإجبارية (اختياري)
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

        # 2️⃣ استقبال رابط الاستفتاء وجلب الخيارات
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

            # جلب الخيارات المتاحة من الرابط
            options = await self._fetch_poll_options(text)
            if not options:
                await update.message.reply_text(
                    "⚠️ تعذر جلب الخيارات من هذا الرابط.\n"
                    "تأكد من أن الرابط يحتوي على استفتاء صالح.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True

            context.user_data["raksh_link"] = text
            context.user_data["raksh_options"] = options
            context.user_data["raksh_step"] = "poll_option"

            options_text = "\n".join(options)
            await update.message.reply_text(
                f"✅ تم حفظ الرابط.\n\n"
                f"📊 *الخيارات المتاحة:*\n"
                f"{options_text}\n\n"
                f"🔢 *أرسل رقم الخيار الذي تريد التصويت عليه:*\n"
                f"مثال: 1",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        # 3️⃣ استقبال رقم الخيار
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

            options_count = len(context.user_data.get("raksh_options", []))
            if option_number < 1 or option_number > options_count:
                await update.message.reply_text(
                    f"⚠️ الرقم يجب أن يكون بين 1 و {options_count}.",
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

        # 4️⃣ استقبال العدد
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

    # ─── معالجة الأزرار (تخطي القنوات) ───
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

    # ─── التنفيذ الفعلي ───
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ رشق استفتاء مع الانضمام للقنوات لمدة 24 ساعة"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"

            # الانضمام للقنوات الإجبارية (فقط لأول حساب، لمدة 24 ساعة)
            if is_first and params.get("channel_ref"):
                for channel_ref in params["channel_ref"]:
                    await _join_channel_and_schedule_leave(client, channel_ref, leave_after_seconds=86400)
                    await asyncio.sleep(0.5)

            # تحليل رابط الاستفتاء
            channel_ref, msg_id = _parse_post_link(params["link"])
            if not channel_ref:
                return False, "رابط الاستفتاء غير صحيح"

            entity = await client.get_entity(channel_ref)
            message = await client.get_messages(entity, ids=msg_id)
            if not message:
                return False, "الاستفتاء غير موجود"

            poll = getattr(message, "poll", None)
            if not poll:
                return False, "هذا المنشور ليس استفتاءً"

            options = getattr(poll, "answers", [])
            if not options:
                return False, "الاستفتاء ليس له خيارات"

            option_request = params.get("poll_option", "1")
            option = _select_poll_option(options, option_request)
            if not option:
                return False, f"الخيار {option_request} غير موجود"

            success = await _send_vote_and_check(client, entity, msg_id, option)
            if not success:
                return False, "تعذر تأكيد التصويت"

            return True, f"✅ تم التصويت من {session['phone_number']}"
        except Exception as e:
            return False, f"❌ فشل التصويت: {str(e)}"
        finally:
            await client.disconnect()
