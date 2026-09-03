from .common import *

class PollService(RakshService):
    """خدمة رشق استفتاء - كل شيء في مكان واحد"""

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
        min_delay=3,
        max_delay=3
    )

    def get_link_instruction(self) -> str:
        return "https://t.me/channel/123"

    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        if not all(_parse_post_link(value)):
            return "⚠️ الرابط غير صحيح لهذه الخدمة.\n\nأرسل: https://t.me/channel/123"
        return None

    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        """معالجة رابط الاستفتاء والخيار والكمية"""
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

            context.user_data["raksh_link"] = text.strip()
            context.user_data["raksh_step"] = "poll_option"
            await update.message.reply_text(
                "✅ تم حفظ رابط الاستفتاء.\n\n"
                "🔢 أرسل رقم الخيار المطلوب كما يظهر في الاستفتاء "
                "(مثال: 1 أو 2 أو 3):",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ]),
            )
            return True

        if state == "poll_option":
            option = _normalize_digits(text).strip()
            if not option.isdigit() or int(option) < 1:
                await update.message.reply_text(
                    "⚠️ أرسل رقم خيار صحيحاً يبدأ من 1.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True

            context.user_data["raksh_poll_option"] = option
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
                f"✅ تم اختيار الخيار رقم {option}.\n\n"
                "🔢 أرسل عدد التصويتات المطلوبة:\n"
                f"(الحد الأقصى: {max_qty})",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ]),
            )
            return True

        if state == "quantity":
            try:
                quantity = int(_normalize_digits(text).strip())
            except (TypeError, ValueError):
                await update.message.reply_text(
                    "⚠️ أرسل عدداً صحيحاً.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True

            max_qty = self.get_request_limit(user.id)
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
                "📋 *مراجعة طلب رشق الاستفتاء*\n\n"
                f"🔗 الرابط: `{context.user_data['raksh_link']}`\n"
                f"🔢 الخيار: {context.user_data['raksh_poll_option']}\n"
                f"📦 العدد: {quantity}\n"
                f"💰 السعر بالنقاط: {points_cost} نقطة\n"
                f"⭐ السعر بالنجوم: {stars_cost} نجمة\n\n"
                "اختر طريقة الدفع:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        f"💰 دفع بالنقاط ({points_cost} نقطة)",
                        callback_data=f"raksh:pay:points:{self.service_type}:{quantity}",
                    )],
                    [InlineKeyboardButton(
                        f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                        callback_data=f"raksh:pay:stars:{self.service_type}:{quantity}",
                    )],
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")],
                ]),
            )
            return True

        if state == "payment":
            return True

        return False

    async def handle_callback(self, update, context, query, data_parts, user, is_own) -> bool:
        return False

    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ رشق استفتاء - يضغط الخيار المحدد ثم زر التصويت إن وجد"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"

            if is_first and params.get("channel_ref"):
                await _join_channel_and_schedule_leave(client, params["channel_ref"])

            channel_ref, msg_id = _parse_post_link(params["link"])
            if not channel_ref:
                return False, "رابط المنشور غير صحيح"

            entity = await client.get_entity(channel_ref)
            message = await client.get_messages(entity, ids=msg_id)
            if not message:
                return False, "المنشور غير موجود"

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

            # محاولة التصويت المباشر عبر SendVoteRequest
            try:
                await client(SendVoteRequest(peer=entity, msg_id=msg_id, options=[option]))
                await asyncio.sleep(1.0)
                # التحقق من نجاح التصويت (بشكل اختياري)
                try:
                    refreshed = await client.get_messages(entity, ids=msg_id)
                    if isinstance(refreshed, (list, tuple)):
                        refreshed = refreshed[0] if refreshed else None
                    if refreshed and refreshed.poll:
                        results = getattr(refreshed.poll, "results", None)
                        if results and results.results:
                            for result in results.results:
                                if getattr(result, "option", None) == option and getattr(result, "chosen", False):
                                    return True, f"✅ تم التصويت من {session['phone_number']}"
                except Exception:
                    pass
                # إذا لم نتمكن من التأكيد، نعتبر النجاح (SendVoteRequest لم يرمِ خطأ)
                return True, f"✅ تم التصويت من {session['phone_number']}"
            except Exception as e:
                logger.warning(f"فشل SendVoteRequest: {e}")

            # إذا فشل التصويت المباشر، محاولة الضغط على الأزرار
            if message.buttons:
                # البحث عن زر مطابق للخيار أو زر "تصويت"
                target_text = getattr(option, "text", "") if hasattr(option, "text") else str(option)
                for row in message.buttons:
                    for btn in row:
                        if getattr(btn, "url", None):
                            continue
                        btn_text = (getattr(btn, "text", "") or "").strip()
                        if btn_text == target_text or btn_text == str(option) or "تصويت" in btn_text or "vote" in btn_text.lower():
                            try:
                                await btn.click()
                                await asyncio.sleep(1.0)
                                return True, f"✅ تم التصويت من {session['phone_number']}"
                            except Exception as e:
                                logger.warning(f"فشل الضغط على الزر: {e}")
                                continue

            return False, "تعذر التصويت"
        except Exception as e:
            return False, f"❌ فشل التصويت: {str(e)}"
        finally:
            await client.disconnect()
