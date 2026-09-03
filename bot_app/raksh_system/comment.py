from .common import *

class CommentService(RakshService):
    """خدمة رشق تعليق - تدفق مخصص حسب الطلب"""

    service_type = "comment"
    label = "💬 رشق تعليق"
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
        return "أرسل رابط المنشور: https://t.me/channel/123"

    # ─── التحقق من الرابط ───
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        if not all(_parse_post_link(value)):
            return "⚠️ الرابط غير صحيح لهذه الخدمة.\n\nأرسل: https://t.me/channel/123"
        return None

    # ─── معالجة النصوص (تدفق جديد) ───
    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        """معالجة النص لخدمة التعليقات"""

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
                f"🔗 *أرسل رابط المنشور:*\n"
                f"{self.get_link_instruction()}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        # 2️⃣ استقبال رابط المنشور
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
            context.user_data["raksh_step"] = "comment_text"

            await update.message.reply_text(
                "✅ تم حفظ الرابط.\n\n"
                "✍️ *أرسل نص التعليق:*\n"
                "مثال: شكراً على الموضوع",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        # 3️⃣ استقبال نص التعليق
        if state == "comment_text":
            if not text.strip():
                await update.message.reply_text(
                    "⚠️ لا يمكن أن يكون التعليق فارغاً.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True

            context.user_data["raksh_comment"] = text.strip()
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
                f"✅ تم حفظ نص التعليق.\n\n"
                f"🔢 *أرسل عدد التعليقات المطلوبة:*\n"
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
                f"✍️ التعليق: `{context.user_data['raksh_comment']}`\n"
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

        # 5️⃣ حالة التأكيد (نستخدم الأزرار)
        if state == "confirm":
            await update.message.reply_text(
                "⚠️ استخدم الأزرار للتأكيد.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        return False

    # ─── معالجة الأزرار (تأكيد الدفع والتنفيذ) ───
    async def handle_callback(self, update, context, query, data_parts, user, is_own) -> bool:
        """
        لا نحتاج لمعالجة الأزرار هنا لأن الدفع والتأكيد يتم عبر
        المعالج العام في raksh_system.py (raksh:pay و raksh:confirm)
        """
        return False

    # ─── التنفيذ الفعلي ───
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ رشق تعليق مع الانضمام للقنوات والكتابة في مجموعة النقاش"""
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

            # تحليل رابط المنشور
            channel_ref, msg_id = _parse_post_link(params["link"])
            if not channel_ref:
                return False, "رابط المنشور غير صحيح"

            entity = await client.get_entity(channel_ref)

            # محاولة الحصول على مجموعة النقاش المرتبطة
            discussion_group = None
            try:
                full_channel = await client(functions.channels.GetFullChannelRequest(channel=entity))
                linked_chat_id = full_channel.full_chat.linked_chat_id
                if linked_chat_id:
                    discussion_group = await client.get_entity(linked_chat_id)
            except Exception as e:
                logger.warning(f"تعذر الحصول على مجموعة النقاش: {e}")

            comment_text = params.get("comment_text", "").strip()
            if not comment_text:
                return False, "نص التعليق فارغ"

            # محاولة إرسال التعليق إلى مجموعة النقاش (إذا وجدت) أو إلى الكيان الأصلي
            try:
                if discussion_group:
                    # الانضمام إلى مجموعة النقاش (إن لم يكن عضوًا)
                    try:
                        await client(JoinChannelRequest(discussion_group))
                    except Exception:
                        pass
                    # إرسال الرسالة مع reply_to إلى msg_id الأصلي
                    await client.send_message(discussion_group, comment_text, reply_to=msg_id)
                    return True, f"✅ تم التعليق من {session['phone_number']}"
                else:
                    # لا توجد مجموعة نقاش، نحاول الإرسال مباشرة (قد تفشل للقنوات)
                    await client.send_message(entity, comment_text, reply_to=msg_id)
                    return True, f"✅ تم التعليق من {session['phone_number']}"
            except Exception as e:
                # إذا فشل بسبب الصلاحيات، نحاول الانضمام للقناة ثم إعادة المحاولة
                if "admin privileges" in str(e).lower() or "can't write in this chat" in str(e).lower():
                    try:
                        # الانضمام إلى القناة
                        if channel_ref.startswith("invite:"):
                            invite_hash = channel_ref[7:]
                            await client(ImportChatInviteRequest(invite_hash))
                        else:
                            await client(JoinChannelRequest(entity))
                        await asyncio.sleep(1.0)
                        # إعادة المحاولة
                        if discussion_group:
                            await client.send_message(discussion_group, comment_text, reply_to=msg_id)
                        else:
                            await client.send_message(entity, comment_text, reply_to=msg_id)
                        return True, f"✅ تم التعليق بعد الانضمام من {session['phone_number']}"
                    except Exception as e2:
                        return False, f"❌ فشل التعليق: {str(e2)}"
                else:
                    return False, f"❌ فشل التعليق: {str(e)}"

        except Exception as e:
            return False, f"❌ فشل التعليق: {str(e)}"
        finally:
            await client.disconnect()
