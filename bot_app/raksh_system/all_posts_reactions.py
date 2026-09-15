"""خدمة رشق تفاعلات لعدة منشورات من قناة تيليجرام."""

from .common import *


class AllPostsReactionsService(RakshService):
    """رشق تفاعل واحد على عدد محدد من منشورات قناة تيليجرام."""

    service_type = "all_posts_reactions"
    label = "✨ رشق تفاعلات لكل البوستات"
    config = ServiceConfig(
        name=label,
        price_points=1,
        points_quantity=1,
        price_stars=1,
        stars_quantity=1,
        has_channel=False,
        has_reaction=True,
        has_ai=False,
        needs_link=True,
        min_delay=3,
        max_delay=3,
    )

    def get_initial_state(self) -> str:
        return "link"

    @staticmethod
    def _parse_channel_target(value: str) -> Optional[str]:
        """تحويل رابط القناة أو رابط أحد منشوراتها إلى مرجع تيليجرام."""
        raw = (value or "").strip().strip("<>")
        if not raw:
            return None

        channel_ref, _ = _parse_post_link(raw)
        if channel_ref:
            return channel_ref

        if raw.startswith("@") and re.fullmatch(r"@[A-Za-z0-9_]{5,32}", raw):
            return raw

        try:
            url = raw if "://" in raw else f"https://{raw}"
            parsed = urlparse(url)
            if parsed.netloc.lower().replace("www.", "") not in {"t.me", "telegram.me"}:
                return None
            parts = [part for part in parsed.path.strip("/").split("/") if part]
            if parts and parts[0] == "s":
                parts = parts[1:]
            if not parts:
                return None
            if parts[0] == "c" and len(parts) >= 2 and parts[1].isdigit():
                return f"-100{parts[1]}"
            if re.fullmatch(r"[A-Za-z0-9_]{5,32}", parts[0]):
                return f"@{parts[0]}"
        except Exception:
            pass
        return None

    def get_link_instruction(self) -> str:
        return (
            "أرسل رابط القناة أو رابط أي منشور منها.\n"
            "مثال: https://t.me/channel أو https://t.me/channel/123"
        )

    def validate_link(self, value: str) -> Optional[str]:
        if not self._parse_channel_target(value):
            return (
                "⚠️ الرابط غير صحيح.\n\n"
                "أرسل رابط قناة تيليجرام أو رابط منشور منها، مثل:\n"
                "https://t.me/channel/123"
            )
        return None

    def get_start_message(self) -> str:
        return (
            f"{self.config.name}\n\n"
            f"💰 السعر: {self.get_rate_text('points')}\n"
            f"⭐ السعر: {self.get_rate_text('stars')}\n\n"
            "🔗 *أرسل رابط القناة أو رابط أحد منشوراتها:*\n"
            f"{self.get_link_instruction()}"
        )

    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        """جمع بيانات الطلب قبل الانتقال إلى الدفع والتنفيذ."""
        cancel_keyboard = self.get_start_keyboard()

        if state == "link":
            link_error = self.validate_link(text)
            if link_error:
                await update.message.reply_text(link_error, reply_markup=cancel_keyboard)
                return True

            context.user_data["raksh_link"] = text.strip()
            context.user_data["raksh_step"] = "post_limit"
            await update.message.reply_text(
                "✅ تم حفظ الرابط.\n\n"
                "🔢 *أرسل عدد المنشورات المطلوب التفاعل معها:*\n"
                "مثال: 10 (الحد الأقصى 100 منشور)",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=cancel_keyboard,
            )
            return True

        if state == "post_limit":
            try:
                post_limit = int(text.strip())
            except (TypeError, ValueError):
                await update.message.reply_text(
                    "⚠️ أرسل رقماً صحيحاً بين 1 و 100.",
                    reply_markup=cancel_keyboard,
                )
                return True

            if not 1 <= post_limit <= 100:
                await update.message.reply_text(
                    "⚠️ العدد المسموح بين 1 و 100 منشور.",
                    reply_markup=cancel_keyboard,
                )
                return True

            context.user_data["raksh_post_limit"] = post_limit
            context.user_data["raksh_step"] = "reaction"
            await update.message.reply_text(
                "✨ *أرسل نوع التفاعل المطلوب:*\n"
                "مثال: ❤️ أو 👍 أو 🔥\n"
                "أرسل كلمة عشوائي لاختيار تفاعل عشوائي لكل حساب.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=cancel_keyboard,
            )
            return True

        if state == "reaction":
            reaction_text = text.strip()
            if reaction_text.lower() in {"عشوائي", "عشوائيًا", "random"}:
                reaction = "random"
            else:
                reaction = RAKSH_REACTIONS.get(reaction_text.lower(), reaction_text)
                if reaction not in RAKSH_REACTIONS.values():
                    await update.message.reply_text(
                        "⚠️ أرسل إيموجي مدعوماً مثل ❤️ أو 👍 أو 🔥، أو اكتب عشوائي.",
                        reply_markup=cancel_keyboard,
                    )
                    return True

            context.user_data["raksh_reaction"] = reaction
            context.user_data["raksh_step"] = "quantity"
            max_qty = self.get_request_limit(user.id)
            if max_qty < 1:
                await update.message.reply_text(
                    "⚠️ لا توجد حسابات متاحة حالياً.",
                    reply_markup=cancel_keyboard,
                )
                return True

            await update.message.reply_text(
                f"✅ تم حفظ التفاعل: {('🎲 عشوائي' if reaction == 'random' else reaction)}\n\n"
                f"👥 *أرسل عدد الحسابات المطلوبة:*\n"
                f"(الحد الأقصى: {max_qty})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=cancel_keyboard,
            )
            return True

        if state == "quantity":
            try:
                quantity = int(text.strip())
            except (TypeError, ValueError):
                await update.message.reply_text(
                    "⚠️ أرسل رقماً صحيحاً.",
                    reply_markup=cancel_keyboard,
                )
                return True

            max_qty = self.get_request_limit(user.id)
            if max_qty < 1:
                await update.message.reply_text(
                    "⚠️ لا توجد حسابات متاحة حالياً.",
                    reply_markup=cancel_keyboard,
                )
                return True
            if not 1 <= quantity <= max_qty:
                await update.message.reply_text(
                    f"⚠️ العدد المسموح بين 1 و {max_qty}.",
                    reply_markup=cancel_keyboard,
                )
                return True

            context.user_data["raksh_quantity"] = quantity
            context.user_data["raksh_step"] = "payment"
            points_cost = self.get_total(quantity, "points")
            stars_cost = self.get_total(quantity, "stars")
            await update.message.reply_text(
                "📋 *تفاصيل الطلب*\n\n"
                f"🔗 الرابط: {context.user_data['raksh_link']}\n"
                f"📰 عدد المنشورات: {context.user_data['raksh_post_limit']}\n"
                f"✨ التفاعل: {context.user_data['raksh_reaction']}\n"
                f"👥 عدد الحسابات: {quantity}\n\n"
                "💳 *اختر طريقة الدفع:*",
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

        return False

    def get_execution_params(self, context) -> Dict:
        params = super().get_execution_params(context)
        params["post_limit"] = context.user_data.get("raksh_post_limit")
        return params

    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """إضافة التفاعل المختار إلى أحدث المنشورات المحددة في القناة."""
        client = TelegramClient(
            StringSession(session["session_string"]),
            int(TELEGRAM_API_ID),
            TELEGRAM_API_HASH,
        )
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"

            channel_ref = self._parse_channel_target(params.get("link"))
            if not channel_ref:
                return False, "رابط القناة غير صحيح"

            try:
                entity = await asyncio.wait_for(client.get_entity(channel_ref), timeout=15)
            except Exception as exc:
                return False, f"تعذر الوصول إلى القناة: {exc}"

            try:
                post_limit = int(params.get("post_limit") or 1)
            except (TypeError, ValueError):
                post_limit = 1
            post_limit = max(1, min(post_limit, 100))

            reaction = params.get("reaction") or "❤️"
            if reaction == "random":
                reaction = random.choice(list(RAKSH_REACTIONS.values()))

            success_count = 0
            attempted_count = 0
            async for message in client.iter_messages(entity, limit=post_limit):
                if not getattr(message, "id", None):
                    continue
                attempted_count += 1
                try:
                    await client(SendReactionRequest(
                        peer=entity,
                        msg_id=message.id,
                        reaction=[ReactionEmoji(emoticon=reaction)],
                    ))
                    success_count += 1
                except Exception as exc:
                    logger.warning(
                        "فشل تفاعل خدمة كل المنشورات على %s/%s: %s",
                        channel_ref,
                        message.id,
                        exc,
                    )

            if not attempted_count:
                return False, "لم يتم العثور على منشورات في القناة"
            if not success_count:
                return False, "تعذر تنفيذ التفاعل على المنشورات"
            return True, (
                f"✅ تم التفاعل على {success_count} من {attempted_count} منشوراً "
                f"من الحساب {session.get('phone_number', '')}"
            )
        except Exception as exc:
            return False, f"❌ فشل تنفيذ التفاعلات: {exc}"
        finally:
            await client.disconnect()
