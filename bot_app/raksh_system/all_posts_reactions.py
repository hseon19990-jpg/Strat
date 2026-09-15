"""خدمة تفاعل مستمرة على منشورات قناة تيليجرام."""

from .common import *
from ..database import db_conn
from datetime import datetime, timezone
import json
from telethon.tl.functions.messages import SendReactionRequest as SendMessageReactionRequest
from telethon.tl.types import ReactionCustomEmoji, ReactionEmoji


class AllPostsReactionsService(RakshService):
    """تفاعل مستمر على كل منشورات القناة بعدد حسابات يحدده المستخدم."""

    service_type = "all_posts_reactions"
    label = "✨ تفاعل على جميع البوستات"
    MAX_DURATION_DAYS = 30
    MAX_POSTS_PER_CYCLE = 100
    POST_CUTOFFS_PARAM = "post_reaction_cutoffs"
    ORDER_ID_PARAM = "_raksh_order_id"

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
            "أرسل رابط القناة.\n"
            "مثال: https://t.me/channel أو https://t.me/channel/123"
        )

    def validate_link(self, value: str) -> Optional[str]:
        if not self._parse_channel_target(value):
            return (
                "⚠️ الرابط غير صحيح.\n\n"
                "أرسل رابط قناة تيليجرام، مثل:\n"
                "https://t.me/channel"
            )
        return None

    def get_start_message(self) -> str:
        return (
            f"{self.config.name}\n\n"
            f"💰 السعر الأساسي: {self.get_rate_text('points')} لكل حساب/يوم\n"
            f"⭐ السعر الأساسي: {self.get_rate_text('stars')} لكل حساب/يوم\n\n"
            "📌 العدد الذي سترسله = عدد الحسابات على كل منشور.\n"
            "مثال: 5 حسابات تعني أن كل منشور سيتفاعل عليه 5 حسابات.\n"
            "سيتم ضم نفس عدد الحسابات إلى القناة قبل بدء التفاعل.\n"
            "ويستمر ذلك مع المنشورات الجديدة حتى انتهاء المدة.\n\n"
            "🔗 *أرسل رابط القناة:*\n"
            f"{self.get_link_instruction()}"
        )

    def get_total_for_duration(
        self,
        quantity: int,
        payment_method: str,
        duration_days: int,
    ) -> int:
        """السعر = عدد الحسابات لكل منشور × عدد الأيام × السعر اليومي."""
        days = max(1, min(int(duration_days or 1), self.MAX_DURATION_DAYS))
        return self.get_total(quantity, payment_method) * days

    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        """جمع الرابط ثم عدد الحسابات لكل منشور ثم عدد الأيام فقط."""
        cancel_keyboard = self.get_start_keyboard()

        if state == "link":
            link_error = self.validate_link(text)
            if link_error:
                await update.message.reply_text(link_error, reply_markup=cancel_keyboard)
                return True

            context.user_data["raksh_link"] = text.strip()
            context.user_data["raksh_step"] = "quantity"
            max_qty = self.get_request_limit(user.id)
            if max_qty < 1:
                await update.message.reply_text(
                    "⚠️ لا تتوفر إمكانية تنفيذ حالياً.",
                    reply_markup=cancel_keyboard,
                )
                return True

            await update.message.reply_text(
                "✅ تم حفظ الرابط.\n\n"
                "✨ *أرسل عدد الحسابات التي ستتفاعل مع كل منشور:*\n"
                "مثال: 5 = خمسة حسابات تتفاعل مع كل منشور\n"
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
                    "⚠️ أرسل رقماً صحيحاً لعدد الحسابات.",
                    reply_markup=cancel_keyboard,
                )
                return True

            max_qty = self.get_request_limit(user.id)
            if max_qty < 1:
                await update.message.reply_text(
                    "⚠️ لا تتوفر إمكانية تنفيذ حالياً.",
                    reply_markup=cancel_keyboard,
                )
                return True
            if not 1 <= quantity <= max_qty:
                await update.message.reply_text(
                    f"⚠️ عدد الحسابات المسموح بين 1 و {max_qty}.",
                    reply_markup=cancel_keyboard,
                )
                return True

            context.user_data["raksh_quantity"] = quantity
            context.user_data["raksh_step"] = "duration_days"
            await update.message.reply_text(
                "✅ تم حفظ عدد الحسابات لكل منشور.\n\n"
                "🗓 *أرسل عدد الأيام:*\n"
                f"(من 1 إلى {self.MAX_DURATION_DAYS} يوماً)",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=cancel_keyboard,
            )
            return True

        if state == "duration_days":
            try:
                duration_days = int(text.strip())
            except (TypeError, ValueError):
                await update.message.reply_text(
                    "⚠️ أرسل رقماً صحيحاً لعدد الأيام.",
                    reply_markup=cancel_keyboard,
                )
                return True

            if not 1 <= duration_days <= self.MAX_DURATION_DAYS:
                await update.message.reply_text(
                    f"⚠️ عدد الأيام المسموح بين 1 و {self.MAX_DURATION_DAYS}.",
                    reply_markup=cancel_keyboard,
                )
                return True

            quantity = int(context.user_data.get("raksh_quantity") or 0)
            context.user_data["raksh_duration_days"] = duration_days
            context.user_data["raksh_reaction"] = "random"
            context.user_data["raksh_step"] = "payment"
            points_cost = self.get_total_for_duration(quantity, "points", duration_days)
            stars_cost = self.get_total_for_duration(quantity, "stars", duration_days)
            await update.message.reply_text(
                "📋 *تفاصيل الطلب*\n\n"
                f"🔗 الرابط: {context.user_data['raksh_link']}\n"
                f"👥 الحسابات لكل منشور: {quantity}\n"
                f"🗓 المدة: {duration_days} يوم\n\n"
                f"💰 التكلفة: {points_cost} نقطة أو {stars_cost} نجمة\n\n"
                f"سيتم ضم {quantity} حساباً إلى القناة قبل بدء التفاعل.\n"
                "كل منشور جديد سيتفاعل عليه هذا العدد من الحسابات طوال المدة.\n\n"
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
        params["duration_days"] = context.user_data.get("raksh_duration_days")
        params["post_limit"] = self.MAX_POSTS_PER_CYCLE
        return params

    @staticmethod
    def _as_utc(value) -> Optional[datetime]:
        """تحويل قيمة تاريخ محفوظة إلى تاريخ UTC قابل للمقارنة."""
        if not value:
            return None
        try:
            parsed = (
                value
                if isinstance(value, datetime)
                else datetime.fromisoformat(str(value))
            )
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _get_post_cutoff(self, params: Dict, phone_number: str) -> Optional[datetime]:
        cutoffs = params.get(self.POST_CUTOFFS_PARAM) or {}
        return self._as_utc(cutoffs.get(str(phone_number)))

    def _save_post_cutoff(
        self,
        params: Dict,
        phone_number: str,
        cutoff: datetime,
    ) -> None:
        """حفظ أول وقت انضمام للحساب حتى لا تعود الدورات للمنشورات القديمة."""
        cutoffs = params.setdefault(self.POST_CUTOFFS_PARAM, {})
        cutoffs[str(phone_number)] = cutoff.astimezone(timezone.utc).isoformat()

        # تحفظ النقطة فوراً، لا بعد انتهاء الدورة، حتى لا تضيع عند إعادة تشغيل
        # البوت أثناء أول تنفيذ.
        order_id = params.get(self.ORDER_ID_PARAM)
        if not order_id:
            return
        persisted_params = dict(params)
        persisted_params.pop(self.ORDER_ID_PARAM, None)
        try:
            with db_conn() as c:
                c.execute(
                    """
                    UPDATE raksh_orders
                    SET params=%s::jsonb, updated_at=NOW()
                    WHERE id=%s
                    """,
                    (
                        json.dumps(persisted_params, ensure_ascii=False, default=str),
                        int(order_id),
                    ),
                )
        except Exception:
            logger.exception(
                "تعذر حفظ نقطة بداية منشورات التفاعل للطلب %s",
                order_id,
            )

    async def _get_allowed_reactions(self, client, entity) -> list:
        """جلب التفاعلات المسموحة فعلياً في القناة."""
        fallback = [
            ReactionEmoji(emoticon=emoji)
            for emoji in RAKSH_REACTIONS.values()
        ]
        try:
            full_channel = await asyncio.wait_for(
                client(functions.channels.GetFullChannelRequest(channel=entity)),
                timeout=10,
            )
            full_chat = getattr(full_channel, "full_chat", None)
            available = getattr(full_chat, "available_reactions", None)
            if available is None:
                return fallback

            if available.__class__.__name__ == "ChatReactionsAll":
                return fallback

            configured = getattr(available, "reactions", None) or []
            reactions = []
            for item in configured:
                reaction = getattr(item, "reaction", None) or item
                if isinstance(reaction, ReactionEmoji):
                    reactions.append(reaction)
                elif isinstance(reaction, ReactionCustomEmoji):
                    reactions.append(reaction)
            return reactions
        except Exception as exc:
            logger.warning(
                "تعذر جلب التفاعلات المسموحة للقناة؛ سيتم استخدام التفاعلات العامة: %s",
                exc,
            )
            return fallback

    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ دورة تفاعل على أحدث منشورات القناة."""
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

            phone_number = session.get("phone_number")
            post_cutoff = self._get_post_cutoff(params, phone_number)

            # كل حساب محسوب في الطلب يجب أن يكون عضواً في القناة قبل تنفيذ
            # التفاعل. نكرر الاستدعاء في كل دورة حتى تبقى العضوية وموعد
            # المغادرة محدثين طوال مدة الحملة.
            joined = await _join_channel_and_schedule_leave(
                client,
                channel_ref,
                phone_number,
            )
            if not joined:
                return False, "تعذر انضمام الحساب إلى القناة"

            # لا نستخدم تاريخ الطلب أو أحدث منشور كمرجع. المرجع هو اللحظة
            # التي اكتمل فيها انضمام هذا الحساب في هذا الطلب تحديداً.
            # عند الدورات التالية نعيد استخدام نفس النقطة، فلا نلمس أي منشور
            # سبق انضمام الحساب.
            if post_cutoff is None:
                post_cutoff = datetime.now(timezone.utc)
                self._save_post_cutoff(params, phone_number, post_cutoff)

            try:
                entity = await asyncio.wait_for(client.get_entity(channel_ref), timeout=15)
            except Exception as exc:
                return False, f"تعذر الوصول إلى القناة: {exc}"

            allowed_reactions = await self._get_allowed_reactions(client, entity)
            if not allowed_reactions:
                return True, (
                    f"✅ انضم الحساب {session.get('phone_number', '')} إلى القناة، "
                    "لكن القناة لا تسمح حالياً بتفاعلات عادية"
                )

            try:
                post_limit = int(params.get("post_limit") or self.MAX_POSTS_PER_CYCLE)
            except (TypeError, ValueError):
                post_limit = self.MAX_POSTS_PER_CYCLE
            post_limit = max(1, min(post_limit, self.MAX_POSTS_PER_CYCLE))

            success_count = 0
            attempted_count = 0
            async for message in client.iter_messages(entity, limit=post_limit):
                if not getattr(message, "id", None):
                    continue
                message_date = self._as_utc(getattr(message, "date", None))
                if message_date is None:
                    # المنشور بلا تاريخ غير قابل للتأكد من أنه جديد؛ تجاهله
                    # بدلاً من المخاطرة بالتفاعل مع منشور قديم.
                    continue
                if message_date <= post_cutoff:
                    # iter_messages يعيد الأحدث أولاً، لذا لا حاجة لفحص ما
                    # بعد أول منشور وصل قبل نقطة الانضمام.
                    break
                attempted_count += 1
                reaction = random.choice(allowed_reactions)
                try:
                    await client(SendMessageReactionRequest(
                        peer=entity,
                        msg_id=message.id,
                        reaction=[reaction],
                    ))
                    success_count += 1
                except Exception as exc:
                    logger.warning(
                        "فشل تفاعل الخدمة المستمرة على %s/%s: %s",
                        channel_ref,
                        message.id,
                        exc,
                    )

            if not attempted_count:
                return True, (
                    f"✅ انضم الحساب {session.get('phone_number', '')} إلى القناة؛ "
                    "لا توجد منشورات حالياً للتفاعل معها"
                )
            if not success_count:
                return True, (
                    f"✅ انضم الحساب {session.get('phone_number', '')} إلى القناة، "
                    "لكن تعذر تنفيذ التفاعل على المنشورات الحالية"
                )
            return True, (
                f"✅ تمت معالجة {success_count} من {attempted_count} منشوراً "
                f"من الحساب {session.get('phone_number', '')}"
            )
        except Exception as exc:
            return False, f"❌ فشل تنفيذ دورة التفاعلات: {exc}"
        finally:
            await client.disconnect()
