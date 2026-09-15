"""خدمة تفاعل مستمرة على منشورات قناة تيليجرام."""

from .common import *
from ..database import db_conn
from datetime import datetime, timezone
import json
from telethon import events
from telethon.tl.functions.messages import (
    GetMessagesViewsRequest,
    SendReactionRequest as SendMessageReactionRequest,
)
from telethon.tl.types import ReactionCustomEmoji, ReactionEmoji


_LIVE_MONITORS = {}


async def _leave_non_interaction_channel_if_needed(
    client,
    phone_number: Optional[str],
    interaction_entity,
) -> None:
    """يفرغ قناة غير مستخدمة للتفاعل عند بلوغ الحساب 500 قناة."""
    try:
        dialogs = await asyncio.wait_for(client.get_dialogs(), timeout=25)
        channel_dialogs = [
            dialog
            for dialog in dialogs
            if getattr(dialog, "is_channel", False)
            and getattr(getattr(dialog, "entity", None), "id", None) is not None
        ]
        if len(channel_dialogs) < 500:
            return

        excluded_ids = {
            getattr(interaction_entity, "id", None),
        }
        if phone_number:
            with db_conn() as c:
                rows = c.execute(
                    """
                    SELECT telegram_channel_id
                    FROM raksh_channel_memberships
                    WHERE phone_number=%s AND leave_at > NOW()
                    """,
                    (str(phone_number).strip(),),
                ).fetchall()
            excluded_ids.update(
                row["telegram_channel_id"]
                for row in rows
                if row["telegram_channel_id"] is not None
            )

        candidates = [
            dialog
            for dialog in channel_dialogs
            if getattr(dialog.entity, "id", None) not in excluded_ids
        ]
        if not candidates:
            logger.warning(
                "الحساب %s بلغ 500 قناة لكن لا توجد قناة آمنة للمغادرة",
                phone_number,
            )
            return

        selected = random.choice(candidates)
        await client(LeaveChannelRequest(selected.entity))
        logger.info(
            "👋 الحساب %s بلغ حد 500 قناة؛ غادر قناة غير مستخدمة للتفاعل",
            phone_number,
        )
    except Exception as exc:
        # لا نوقف التفاعل إذا تعذر تنظيف قناة قديمة.
        logger.warning(
            "تعذر إخلاء قناة قديمة للحساب %s عند بلوغ حد 500: %s",
            phone_number,
            exc,
        )


class AllPostsReactionsService(RakshService):
    """رشق تفاعلات ومشاهدات مستمر على كل منشورات القناة."""

    service_type = "all_posts_reactions"
    label = "💬👁 رشق تفاعلات ومشاهدات لكل البوستات"
    # Each new post receives one view attempt and one reaction attempt per account.
    reaction_only = False
    MAX_DURATION_DAYS = 30
    MAX_POSTS_PER_CYCLE = 100
    POST_CUTOFFS_PARAM = "post_reaction_cutoffs"
    CAMPAIGN_EXPIRES_PARAM = "campaign_expires_at"
    CAMPAIGN_ACCOUNTS_PARAM = "campaign_account_phones"
    ORDER_ID_PARAM = "_raksh_order_id"

    config = ServiceConfig(
        name=label,
        price_points=30,
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
            if parts[0] == "joinchat" and len(parts) >= 2:
                return f"invite:{parts[1]}"
            if parts[0].startswith("+"):
                invite_hash = parts[0][1:]
                return f"invite:{invite_hash}" if invite_hash else None
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
            f"⭐ الدفع بالنجوم: كل {RAKSH_POINTS_PER_STAR} نقطة = نجمة\n\n"
            "📌 العدد الذي سترسله = عدد الحسابات على كل منشور.\n"
            "مثال: 5 حسابات تعني أن كل منشور سيتفاعل عليه 5 حسابات.\n"
            "سيتم ضم نفس عدد الحسابات إلى القناة قبل بدء التفاعل.\n"
            "ويستمر ذلك مع المنشورات الجديدة حتى انتهاء المدة.\n"
            "✅ كل حساب يسجل مشاهدة ويرسل تفاعلاً على المنشورات الجديدة.\n\n"
            "🔗 *أرسل رابط القناة:*\n"
            f"{self.get_link_instruction()}"
        )

    def get_total_for_duration(
        self,
        quantity: int,
        payment_method: str,
        duration_days: int,
    ) -> int:
        """السعر يعتمد على الحسابات والأيام، لا على عدد المنشورات."""
        days = max(1, min(int(duration_days or 1), self.MAX_DURATION_DAYS))
        points_total = self.get_total(quantity, "points") * days
        if payment_method == "stars":
            return points_to_stars(points_total)
        return points_total

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

    @staticmethod
    def _is_order_cancelled(order_id: int) -> bool:
        with db_conn() as c:
            row = c.execute(
                "SELECT status FROM raksh_orders WHERE id=%s",
                (order_id,),
            ).fetchone()
        return bool(row and row["status"] == "cancelled")

    def is_live_monitoring(self, order_id: int) -> bool:
        """هل يوجد مستمع مباشر يعمل لهذا الطلب؟"""
        task = _LIVE_MONITORS.get(int(order_id))
        if task is None:
            return False
        if task.done():
            _LIVE_MONITORS.pop(int(order_id), None)
            return False
        return True

    async def start_live_monitor(
        self,
        order_id: int,
        sessions: List[Dict],
        params: Dict,
        expires_at: datetime,
        on_finished: Callable[[], Any],
    ) -> bool:
        """بدء مستمع مباشر للمنشورات الجديدة بدلاً من انتظار دورة الفحص."""
        order_id = int(order_id)
        if self.is_live_monitoring(order_id) or not sessions:
            return False

        task = asyncio.create_task(
            self._run_live_monitor(
                order_id=order_id,
                sessions=sessions,
                params=dict(params),
                expires_at=expires_at,
                on_finished=on_finished,
            ),
            name=f"raksh-live-reactions-{order_id}",
        )
        _LIVE_MONITORS[order_id] = task

        def forget_monitor(done_task):
            if _LIVE_MONITORS.get(order_id) is done_task:
                _LIVE_MONITORS.pop(order_id, None)
            if done_task.cancelled():
                return
            error = done_task.exception()
            if error:
                logger.error(
                    "توقف مستمع التفاعل المباشر للطلب %s",
                    order_id,
                    exc_info=(type(error), error, error.__traceback__),
                )

        task.add_done_callback(forget_monitor)
        return True

    async def _run_live_monitor(
        self,
        order_id: int,
        sessions: List[Dict],
        params: Dict,
        expires_at: datetime,
        on_finished: Callable[[], Any],
    ) -> None:
        stop_event = asyncio.Event()
        account_tasks = [
            asyncio.create_task(
                self._watch_account(
                    session=session,
                    params=params,
                    stop_event=stop_event,
                    expires_at=expires_at,
                ),
                name=f"raksh-live-account-{session.get('phone_number')}",
            )
            for session in sessions
        ]
        try:
            while datetime.now(timezone.utc) < expires_at:
                if self._is_order_cancelled(order_id):
                    return
                remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
                await asyncio.sleep(min(5, max(1, remaining)))
        finally:
            stop_event.set()
            for task in account_tasks:
                task.cancel()
            await asyncio.gather(*account_tasks, return_exceptions=True)

        if not self._is_order_cancelled(order_id):
            await on_finished()

    async def _watch_account(
        self,
        session: Dict,
        params: Dict,
        stop_event: asyncio.Event,
        expires_at: datetime,
    ) -> None:
        """إبقاء جلسة الحساب مستمعة للقناة والتفاعل مع كل منشور جديد."""
        phone_number = session.get("phone_number")
        channel_ref = self._parse_channel_target(params.get("link"))
        if not channel_ref:
            return

        # Keep failed deliveries out of the processed set so a temporary
        # Telegram/network error can be retried by the polling fallback.
        processed_message_ids = set()
        viewed_message_ids = set()
        reacted_message_ids = set()
        retry_messages = {}
        processing_message_ids = set()
        last_seen_message_id = 0
        last_membership_refresh = 0.0

        while not stop_event.is_set():
            client = TelegramClient(
                StringSession(session["session_string"]),
                int(TELEGRAM_API_ID),
                TELEGRAM_API_HASH,
            )
            try:
                # قد يستمع الحساب نفسه إلى عدة قنوات؛ لا نفتح طلبات Telegram
                # متزامنة للجلسة نفسها حتى لا يتحول التفاعل إلى FloodWait.
                session_lock = _get_raksh_session_lock(str(phone_number or ""))
                async with session_lock:
                    await asyncio.wait_for(client.connect(), timeout=15)
                    if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                        _mark_raksh_session_unauthorized(phone_number)
                        return

                    entity = await _join_channel_and_schedule_leave(
                        client,
                        channel_ref,
                        phone_number,
                        return_entity=True,
                        leave_until=expires_at,
                    )
                    if not entity:
                        raise RuntimeError("تعذر انضمام الحساب إلى القناة")

                    cutoff = self._get_post_cutoff(params, phone_number)
                    if cutoff is None:
                        cutoff = datetime.now(timezone.utc)
                        self._save_post_cutoff(params, phone_number, cutoff)

                    allowed_reactions = await self._get_allowed_reactions(client, entity)
                async def process_message(message):
                    nonlocal last_seen_message_id
                    if not getattr(message, "id", None):
                        return
                    message_id = int(message.id)
                    if (
                        message_id in processed_message_ids
                        or message_id in processing_message_ids
                    ):
                        return
                    last_seen_message_id = max(last_seen_message_id, message_id)
                    message_date = self._as_utc(getattr(message, "date", None))
                    if message_date is None or message_date <= cutoff:
                        processed_message_ids.add(message_id)
                        retry_messages.pop(message_id, None)
                        return
                    processing_message_ids.add(message_id)
                    view_done = message_id in viewed_message_ids
                    reaction_done = not allowed_reactions or message_id in reacted_message_ids
                    try:
                        async with session_lock:
                            if not client.is_connected():
                                await asyncio.wait_for(client.connect(), timeout=15)
                            if not view_done:
                                await client(
                                    GetMessagesViewsRequest(
                                        peer=entity,
                                        id=[message.id],
                                        increment=True,
                                    )
                                )
                                viewed_message_ids.add(message_id)
                                view_done = True
                                logger.info(
                                    "👁 مشاهدة على %s/%s من الحساب %s",
                                    channel_ref,
                                    message.id,
                                    phone_number,
                                )
                            if allowed_reactions and not reaction_done:
                                reaction = random.choice(allowed_reactions)
                                await client(
                                    SendMessageReactionRequest(
                                        peer=entity,
                                        msg_id=message.id,
                                        reaction=[reaction],
                                    )
                                )
                                reacted_message_ids.add(message_id)
                                reaction_done = True
                                logger.info(
                                    "✅ تفاعل مباشر على %s/%s من الحساب %s",
                                    channel_ref,
                                    message.id,
                                    phone_number,
                                )
                    except Exception as exc:
                        if is_raksh_frozen_account_error(exc):
                            _mark_raksh_session_unauthorized(phone_number)
                            stop_event.set()
                            return
                        logger.warning(
                            "فشل المشاهدة/التفاعل المباشر على %s/%s من الحساب %s: %s",
                            channel_ref,
                            message.id,
                            phone_number,
                            exc,
                        )
                    finally:
                        processing_message_ids.discard(message_id)

                    if view_done and reaction_done:
                        processed_message_ids.add(message_id)
                        retry_messages.pop(message_id, None)
                    else:
                        # إذا نجحت المشاهدة وفشل التفاعل أو العكس، تعاد المحاولة
                        # للجزء الفاشل فقط دون تكرار الجزء الناجح.
                        retry_messages[message_id] = message

                async def on_new_message(event):
                    await process_message(event.message)

                async def poll_new_messages():
                    """تعويض أي تحديث مباشر لم يصل من Telegram."""
                    nonlocal entity, last_membership_refresh
                    now = asyncio.get_running_loop().time()
                    if now - last_membership_refresh >= 900:
                        async with session_lock:
                            if not client.is_connected():
                                await asyncio.wait_for(client.connect(), timeout=15)
                            refreshed_entity = await _join_channel_and_schedule_leave(
                                client,
                                channel_ref,
                                phone_number,
                                return_entity=True,
                                leave_until=expires_at,
                            )
                        if not refreshed_entity:
                            raise RuntimeError("تعذر تجديد عضوية الحساب في القناة")
                        entity = refreshed_entity
                        last_membership_refresh = now

                    # Retry failed sends before asking Telegram for a newer
                    # range. This matters after a short disconnect or flood
                    # wait: last_seen_message_id may already be past the post.
                    for message in list(retry_messages.values()):
                        await process_message(message)

                    async with session_lock:
                        if not client.is_connected():
                            await asyncio.wait_for(client.connect(), timeout=15)
                        messages = await client.get_messages(
                            entity,
                            limit=50,
                            **(
                                {"min_id": last_seen_message_id}
                                if last_seen_message_id
                                else {}
                            ),
                        )
                    for message in reversed(list(messages or [])):
                        await process_message(message)

                client.add_event_handler(
                    on_new_message,
                    events.NewMessage(chats=entity),
                )
                while not stop_event.is_set():
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        await poll_new_messages()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if is_raksh_frozen_account_error(exc):
                    _mark_raksh_session_unauthorized(phone_number)
                    return
                logger.warning(
                    "انقطع مستمع التفاعل المباشر للحساب %s؛ ستعاد المحاولة: %s",
                    phone_number,
                    exc,
                )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=10)
                except asyncio.TimeoutError:
                    pass
            finally:
                await client.disconnect()

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
        try:
            try:
                await asyncio.wait_for(client.connect(), timeout=15)
            except Exception as exc:
                if is_raksh_frozen_account_error(exc):
                    _mark_raksh_session_unauthorized(session.get("phone_number"))
                    return False, RAKSH_FROZEN_ACCOUNT_MARKER
                raise

            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, RAKSH_FROZEN_ACCOUNT_MARKER

            channel_ref = self._parse_channel_target(params.get("link"))
            if not channel_ref:
                return False, "رابط القناة غير صحيح"

            phone_number = session.get("phone_number")
            post_cutoff = self._get_post_cutoff(params, phone_number)

            # كل حساب محسوب في الطلب يجب أن يكون عضواً في القناة قبل تنفيذ
            # التفاعل. نكرر الاستدعاء في كل دورة حتى تبقى العضوية وموعد
            # المغادرة محدثين طوال مدة الحملة.
            entity = await _join_channel_and_schedule_leave(
                client,
                channel_ref,
                phone_number,
                return_entity=True,
                leave_until=self._as_utc(params.get("_raksh_expires_at")),
            )
            if not entity:
                return False, "تعذر انضمام الحساب إلى القناة"

            await _leave_non_interaction_channel_if_needed(
                client,
                phone_number,
                entity,
            )

            # لا نستخدم تاريخ الطلب أو أحدث منشور كمرجع. المرجع هو اللحظة
            # التي اكتمل فيها انضمام هذا الحساب في هذا الطلب تحديداً.
            # عند الدورات التالية نعيد استخدام نفس النقطة، فلا نلمس أي منشور
            # سبق انضمام الحساب.
            if post_cutoff is None:
                post_cutoff = datetime.now(timezone.utc)
                self._save_post_cutoff(params, phone_number, post_cutoff)

            allowed_reactions = await self._get_allowed_reactions(client, entity)
            try:
                post_limit = int(params.get("post_limit") or self.MAX_POSTS_PER_CYCLE)
            except (TypeError, ValueError):
                post_limit = self.MAX_POSTS_PER_CYCLE
            post_limit = max(1, min(post_limit, self.MAX_POSTS_PER_CYCLE))

            success_count = 0
            view_success_count = 0
            reaction_success_count = 0
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
                view_ok = False
                reaction_ok = not allowed_reactions
                try:
                    await client(
                        GetMessagesViewsRequest(
                            peer=entity,
                            id=[message.id],
                            increment=True,
                        )
                    )
                    view_success_count += 1
                    view_ok = True
                except Exception as exc:
                    if is_raksh_frozen_account_error(exc):
                        raise
                    logger.warning(
                        "فشل تسجيل مشاهدة الخدمة المستمرة على %s/%s: %s",
                        channel_ref,
                        message.id,
                        exc,
                    )

                if allowed_reactions:
                    reaction = random.choice(allowed_reactions)
                    try:
                        await client(SendMessageReactionRequest(
                            peer=entity,
                            msg_id=message.id,
                            reaction=[reaction],
                        ))
                        reaction_success_count += 1
                        reaction_ok = True
                    except Exception as exc:
                        if is_raksh_frozen_account_error(exc):
                            raise
                        logger.warning(
                            "فشل تفاعل الخدمة المستمرة على %s/%s: %s",
                            channel_ref,
                            message.id,
                            exc,
                        )

                if view_ok and reaction_ok:
                    success_count += 1

            if not attempted_count:
                return True, (
                    f"✅ انضم الحساب {session.get('phone_number', '')} إلى القناة؛ "
                    "لا توجد منشورات حالياً للتفاعل معها"
                )
            if not view_success_count and not reaction_success_count:
                return True, (
                    f"✅ انضم الحساب {session.get('phone_number', '')} إلى القناة، "
                    "لكن تعذر تسجيل المشاهدات والتفاعلات على المنشورات الحالية"
                )
            return True, (
                f"✅ تمت معالجة {success_count} من {attempted_count} منشوراً "
                f"من الحساب {session.get('phone_number', '')}
"
                f"👁 مشاهدات: {view_success_count} | 💬 تفاعلات: {reaction_success_count}"
            )
        except Exception as exc:
            if is_raksh_frozen_account_error(exc):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, RAKSH_FROZEN_ACCOUNT_MARKER
            return False, f"❌ فشل تنفيذ دورة التفاعلات: {exc}"
        finally:
            await client.disconnect()
