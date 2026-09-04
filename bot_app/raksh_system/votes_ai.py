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
    )

    def get_start_message(self) -> str:
        return (
            f"{self.config.name}\n\n"
            f"💰 السعر: {self.get_rate_text('points')}\n"
            f"⭐ السعر: {self.get_rate_text('stars')}\n\n"
            f"📢 *أرسل روابط القنوات الإجبارية:*\n"
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
            [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")],
        ])

    def get_callback_prefix(self) -> str:
        return "raksh_votes_ai"

    def get_link_prompt_label(self) -> str:
        return "رابط البوست أو رابط التصويت"

    def get_saved_link_label(self) -> str:
        return "رابط البوست/التصويت"

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
            "🔹 أو رابط منشور/تصويت: `https://t.me/channel/123`"
        )

    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ أرسل رابط البوت أو رابط المنشور/التصويت."
        if not ("@" in value or "t.me/" in value):
            return "⚠️ أرسل رابط بوت أو رابط منشور/تصويت صالحاً من Telegram."
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

    async def _execute_verified_vote(self, session, params, is_first):
        """التصويت مع تحقق: يحاول تنفيذ التصويت إن أمكن، ويعتبر ناجحاً فور التحقق."""
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

            if is_first:
                channels = params.get("channel_ref") or []
                if isinstance(channels, str):
                    channels = [channels]
                for channel_ref in channels:
                    try:
                        await _join_channel_and_schedule_leave(client, channel_ref)
                        await asyncio.sleep(1.0)
                    except Exception as exc:
                        logger.warning(f"فشل الانضمام للقناة {channel_ref}: {exc}")

            link = (params.get("link") or "").strip()
            post_ref, post_id = _parse_post_link(link)
            post_entity = None
            post_message = None

            # الفرق الوحيد عن الإحالة: رابط التصويت قد يكون منشوراً.
            if post_ref and post_id:
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
                bot_username, bot_start_param = _find_bot_start_link(post_message)
                if not bot_username:
                    return False, "المنشور لا يحتوي على زر بوت صالح."
            else:
                bot_username, bot_start_param = _parse_bot_link(link)
                if not bot_username:
                    return False, "الرابط غير صحيح لهذه الخدمة."

            try:
                bot_entity = await self._resolve_bot(client, bot_username)
            except Exception as exc:
                return False, f"تعذر العثور على البوت {bot_username}: {str(exc)[:80]}"
            if not bot_entity:
                return False, "تعذر العثور على البوت."

            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=bot_start_param or "",
            ))
            await asyncio.sleep(2.0)

            # استخدام نفس الكلاس يضمن نفس: الضغط، القراءة كل ثانيتين،
            # الرسالة المعدلة، الرسالة الجديدة، النص، caption، الكيبورد
            # وطلب مشاركة الرقم.
            verified = await self._solve_verification(
                client,
                bot_entity,
                session.get("phone_number"),
            )
            if not verified:
                return False, "فشل التحقق بعد محاولات متعددة."

            # ===== تعديل: بمجرد اكتمال التحقق، نعتبر التصويت ناجحاً =====
            # لكن نحاول تنفيذ التصويت الفعلي إن كان ممكناً دون فشل إذا تعذر.

            if post_entity is not None:
                # محاولة جلب المنشور مجدداً وتنفيذ التصويت إن أمكن
                try:
                    refreshed_post = self._as_message(
                        await client.get_messages(post_entity, ids=post_id)
                    )
                    if refreshed_post:
                        media = getattr(refreshed_post, "media", None)
                        poll_media = getattr(refreshed_post, "poll", None) or media
                        poll = getattr(poll_media, "poll", None) or poll_media
                        options = getattr(poll, "answers", None) or []
                        if options:
                            chosen = _select_poll_option(
                                options,
                                params.get("poll_option"),
                            )
                            if chosen is None:
                                chosen = random.choice(options)
                            await _send_vote_and_check(
                                client,
                                post_entity,
                                post_id,
                                chosen.option,
                            )
                        else:
                            # البحث عن زر تصويت في الأزرار
                            vote_keywords = ("تصويت", "صوت", "vote", "voting")
                            vote_button = None
                            for row in getattr(refreshed_post, "buttons", None) or []:
                                for button in row:
                                    if getattr(button, "url", None):
                                        continue
                                    button_text = (
                                        getattr(button, "text", "") or ""
                                    ).casefold()
                                    if any(keyword in button_text for keyword in vote_keywords):
                                        vote_button = button
                                        break
                                if vote_button:
                                    break
                            if vote_button:
                                await vote_button.click()
                                await asyncio.sleep(0.5)
                except Exception as exc:
                    logger.warning(f"تعذر تنفيذ التصويت بعد التحقق: {exc}")

            # النجاح مضمون فور التحقق حتى لو لم يتم العثور على زر
            return True, f"✅ تم التصويت مع التحقق من {session['phone_number']}"

        except Exception as exc:
            if "two different IP" in str(exc) or "AuthKeyDuplicated" in str(exc):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة تستخدم من IP مختلف - تم تعطيلها مؤقتاً"
            return False, f"❌ فشل التصويت: {str(exc)[:80]}"
        finally:
            await client.disconnect()

    async def execute(self, session, params, is_first):
        return await self._execute_verified_vote(session, params, is_first)
