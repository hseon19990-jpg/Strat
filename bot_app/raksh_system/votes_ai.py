from .common import *

from .forced_ref_ai import ForcedRefAIService


class VotesAIService(RakshService):
    """خدمة رشق تصويت مع تحقق - تستخدم نفس تحقق الإحالة."""

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

    def get_link_instruction(self) -> str:
        return "https://t.me/i8YYBot?start=compvote_xxx أو رابط منشور"

    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        if not ("@" in value or "t.me/" in value):
            return "⚠️ الرابط يجب أن يحتوي على @username أو t.me/"
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
        """التصويت مع تحقق مطابق تماماً لتدفق ForcedRefAIService."""
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

            # نحدد نقطة البداية قبل /start حتى لا نستخدم تحدياً قديماً.
            start_after_message_id = 0
            try:
                old_messages = await client.get_messages(bot_entity, limit=50)
                start_after_message_id = max(
                    (getattr(msg, "id", 0) or 0)
                    for msg in (old_messages or [])
                ) if old_messages else 0
            except Exception as exc:
                logger.warning(f"تعذر تحديد نقطة بداية التحقق: {exc}")

            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=bot_start_param or "",
            ))
            await asyncio.sleep(0.5)

            # استخدام نفس الكلاس يضمن نفس: الضغط، القراءة كل ثانيتين،
            # الرسالة المعدلة، الرسالة الجديدة، النص، caption، الكيبورد
            # وطلب مشاركة الرقم.
            verifier = ForcedRefAIService()
            verified = await verifier._solve_verification(
                client,
                bot_entity,
                session.get("phone_number"),
                start_after_message_id=start_after_message_id,
            )
            if not verified:
                return False, "فشل التحقق بعد محاولات متعددة."

            # رابط البوت ينجز التصويت من خلال البوت نفسه.
            if post_entity is None:
                return True, f"✅ تم التصويت مع التحقق من {session['phone_number']}"

            # إذا كان الرابط منشوراً، نفذ التصويت بعد اكتمال تحقق البوت.
            refreshed_post = self._as_message(
                await client.get_messages(post_entity, ids=post_id)
            )
            if not refreshed_post:
                return False, "اختفى المنشور بعد التحقق."

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
                return True, f"✅ تم التصويت مع التحقق من {session['phone_number']}"

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
                return True, f"✅ تم التصويت مع التحقق من {session['phone_number']}"

            return False, "تم التحقق، لكن لم يتم العثور على تصويت في المنشور."
        except Exception as exc:
            if "two different IP" in str(exc) or "AuthKeyDuplicated" in str(exc):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة تستخدم من IP مختلف - تم تعطيلها مؤقتاً"
            return False, f"❌ فشل التصويت: {str(exc)[:80]}"
        finally:
            await client.disconnect()

    async def execute(self, session, params, is_first):
        return await self._execute_verified_vote(session, params, is_first)