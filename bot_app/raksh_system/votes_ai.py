from .common import *

from .forced_ref_ai import ForcedRefAIService


class VotesAIService(ForcedRefAIService):
    """
    خدمة رشق تصويت مع تحقق.

    ترث تدفق الإحالة بالكامل: القنوات الإجبارية، الرابط، الكمية، الدفع،
    والتحقق متعدد المراحل. الاستثناء الوحيد هو أن الرابط قد يكون رابط بوت
    أو رابط منشور/قناة لتنفيذ التصويت بعد اكتمال التحقق.
    """

    service_type = "votes_ai"
    label = "🛡 رشق تصويت مع تحقق"
    config = ServiceConfig(
        name=label,
        price_points=50,
        points_quantity=1,
        price_stars=10,
        stars_quantity=1,
        has_channel=True,
        has_reaction=False,
        has_ai=True,
        needs_link=True,
        min_delay=3,
        max_delay=3,
        max_concurrent=1,
        channel_free_limit=1,
        channel_extra_point_price=0,
    )

    def get_start_message(self) -> str:
        return (
            f"{self.config.name}\n\n"
            f"💰 السعر: {self.get_rate_text('points')}\n"
            f"⭐ السعر: {self.get_rate_text('stars')}\n\n"
            f"📢 *أرسل قناة إجبارية واحدة (اختياري):*\n"
            f"@channel1\n"
            f"أو أرسل رابط t.me للقناة\n\n"
            f"✍️ اكتب 'تخطي' لعدم وجود قناة"
        )

    def get_start_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⏭️ تخطي (بدون قنوات)",
                callback_data=f"{self.get_callback_prefix()}:skip_channels",
            )],
            [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")],
        ])

    def get_callback_prefix(self) -> str:
        return "raksh_votes_ai"

    def get_link_prompt_label(self) -> str:
        return "رابط البوت أو المنشور"

    def get_saved_link_label(self) -> str:
        return "رابط البوت/المنشور"

    def get_quantity_label(self) -> str:
        return "عدد التصويتات المطلوبة"

    def get_activity_label(self) -> str:
        return "تصويت"

    def get_execution_label(self) -> str:
        return "تنفيذ التصويت وحل التحقق"

    def get_invoice_label(self) -> str:
        return "تصويت مع تحقق"

    def get_link_instruction(self) -> str:
        return (
            "🔹 رابط بوت: `https://t.me/xxxBot?start=compvote-xxx`\n"
            "🔹 أو رابط منشور يحتوي على زر: `https://t.me/channel/123`"
        )

    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ أرسل رابط البوت أو رابط المنشور الذي يحتوي على زر."

        channel_ref, message_id = _parse_post_link(value)
        if channel_ref and message_id is not None:
            return None

        bot_username, _ = _parse_bot_link(value)
        if not bot_username:
            return (
                "⚠️ الرابط غير صحيح لهذه الخدمة.\n\n"
                "أرسل رابط بوت مباشر أو رابط منشور يحتوي على زر، مثل:\n"
                "https://t.me/xxxBot?start=compvote-xxx\n"
                "https://t.me/channel/123"
            )
        return None

    @staticmethod
    def _as_message(value):
        if isinstance(value, (list, tuple)):
            return value[0] if value else None
        return value

    async def _resolve_bot(self, client, username):
        """حل البوت مع نفس أسلوب fallback المستخدم في الإحالة."""
        clean_username = (username or "").lstrip("@").strip()
        if not clean_username:
            return None
        try:
            resolved = await client(ResolveUsernameRequest(clean_username))
            if resolved.users:
                return resolved.users[0]
            if resolved.chats:
                return resolved.chats[0]
        except Exception:
            pass
        try:
            return await client.get_entity(clean_username)
        except Exception:
            return await client.get_entity(f"@{clean_username}")

    async def _start_target_bot(self, client, bot_entity, start_param: str) -> int:
        """بدء البوت فعلياً مع fallback لإرسال /start مباشرةً.

        StartBotRequest هو المكافئ البرمجي لزر Start، لكن بعض البوتات أو
        إصدارات Telethon لا تُظهر رسالة جديدة بعد الطلب. نحتفظ بمعرّف آخر
        رسالة قبل البدء، ثم نستخدم /start كمسار احتياطي فقط إذا لم يصل رد.
        """
        base_id = 0
        try:
            previous = await client.get_messages(bot_entity, limit=1)
            previous_message = self._as_message(previous)
            base_id = getattr(previous_message, "id", 0) or 0
        except Exception as exc:
            logger.warning("تعذر تحديد آخر رسالة قبل بدء بوت التصويت: %s", exc)

        start_param = (start_param or "").strip()
        try:
            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param,
            ))
            logger.info(
                "▶️ تم إرسال StartBotRequest إلى بوت التصويت (param=%s)",
                start_param or "empty",
            )
        except Exception as exc:
            logger.warning(
                "فشل StartBotRequest لبوت التصويت؛ سيتم استخدام /start مباشرةً: %s",
                exc,
            )

        async def has_new_incoming_message() -> bool:
            try:
                recent = await client.get_messages(bot_entity, limit=5)
                return any(
                    not getattr(message, "out", False)
                    and (not base_id or (getattr(message, "id", 0) or 0) > base_id)
                    for message in recent
                )
            except Exception:
                return False

        # نعطي StartBotRequest فرصة قصيرة لإظهار رسالة البداية.
        await asyncio.sleep(1.5)
        if not await has_new_incoming_message():
            start_command = f"/start {start_param}" if start_param else "/start"
            try:
                await client.send_message(bot_entity, start_command)
                logger.info("▶️ تم إرسال أمر %s يدوياً إلى بوت التصويت", start_command)
            except Exception as exc:
                logger.error("❌ فشل إرسال أمر البدء إلى بوت التصويت: %s", exc)
                raise
            await asyncio.sleep(1.5)

        return base_id

    async def _check_already_voted(self, client, bot_entity) -> bool:
        """فحص آخر رسائل البوت للتحقق من رسالة 'لقد صوّتت لهذا الشخص من قبل'."""
        try:
            messages = await client.get_messages(bot_entity, limit=10)
            for msg in messages:
                text = (msg.text or "").strip()
                if "لقد صوّتت لهذا الشخص من قبل" in text or "already voted" in text.casefold():
                    return True
        except Exception as exc:
            logger.warning(f"فشل فحص رسائل البوت للتحقق من التصويت المسبق: {exc}")
        return False

    async def _execute_verified_vote(self, session, params, is_first):
        """التصويت مع تحقق باستخدام مسار الإحالة نفسه عند وجود رابط بوت."""
        link = (params.get("link") or "").strip()
        post_ref, post_id = _parse_post_link(link)

        # رابط البوت يجب أن يمر حرفياً عبر تنفيذ الإحالة مع التحقق، بما في
        # ذلك تمرير بيانات صاحب الطلب للكابتشا اليدوية.
        if not (post_ref and post_id):
            return await super().execute(session, params, is_first)

        client = TelegramClient(
            StringSession(session["session_string"]),
            int(TELEGRAM_API_ID),
            TELEGRAM_API_HASH,
        )
        await asyncio.wait_for(client.connect(), timeout=20)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها."

            post_entity = None
            post_message = None

            try:
                post_entity = await client.get_entity(post_ref)
                post_message = self._as_message(
                    await client.get_messages(post_entity, ids=post_id)
                )
            except Exception as exc:
                logger.warning(f"تعذر جلب المنشور {link}: {exc}")
                return False, "تعذر الوصول إلى القناة/المنشور."

            if not post_message:
                return False, "المنشور غير موجود."
            post_button = _select_post_action_button(post_message)
            if post_button is None:
                return False, "لم يتم العثور على زر مناسب في المنشور."

            button_url = getattr(post_button, "url", None)
            bot_username, _ = _parse_bot_link(button_url or "")
            if bot_username:
                # زر البوت في المنشور يصبح رابط الهدف، ثم نعيد تشغيل مسار
                # الإحالة بالكامل بدلاً من تنفيذ نسخة تحقق خاصة بالتصويت.
                verification_params = dict(params)
                verification_params["link"] = button_url
                await client.disconnect()
                client = None
                return await super().execute(
                    session,
                    verification_params,
                    is_first,
                )

            # الزر callback هو استثناء المنشور: نضغطه مباشرة بعد تجهيز
            # القناة، لأن الزر نفسه هو عملية التصويت ولا يفتح بوت تحقق.
            if is_first:
                channels = params.get("channel_ref") or []
                if isinstance(channels, str):
                    channels = [channels]
                for channel_ref in channels[:1]:
                    try:
                        await _join_channel_and_schedule_leave(
                            client,
                            channel_ref,
                            session.get("phone_number"),
                        )
                        await asyncio.sleep(1.0)
                    except Exception as exc:
                        logger.warning(f"فشل الانضمام للقناة {channel_ref}: {exc}")
            try:
                await post_button.click()
                await asyncio.sleep(0.5)
                return True, f"✅ تم الضغط على زر التصويت من {session['phone_number']}"
            except Exception as exc:
                return False, f"تعذر الضغط على زر المنشور: {str(exc)[:80]}"

        except Exception as exc:
            if "two different IP" in str(exc) or "AuthKeyDuplicated" in str(exc):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة تستخدم من IP مختلف - تم تعطيلها مؤقتاً"
            return False, f"❌ فشل التصويت: {str(exc)[:80]}"
        finally:
            if client is not None:
                await client.disconnect()

    async def execute(self, session, params, is_first):
        return await self._execute_verified_vote(session, params, is_first)
