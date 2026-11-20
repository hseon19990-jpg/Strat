# premium_reaction.py
from .common import *
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionCustomEmoji

# إعدادات جلب التفاعلات المميزة: عدة جلسات على دفعات بدل جلسة واحدة.
PREMIUM_REACTION_LOOKUP_BATCH_SIZE = 3
PREMIUM_REACTION_LOOKUP_MAX_BATCHES = 3
PREMIUM_REACTION_LOOKUP_TIMEOUT_SECONDS = 30
PREMIUM_REACTION_STEP_TIMEOUT_SECONDS = 8
PREMIUM_REACTION_POOL_LIMIT = 50
PREMIUM_REACTION_JOIN_MAX_ATTEMPTS = 15
# مهلة احتياطية لمغادرة حساب الفحص/الحسابات إن فشلت المغادرة الفورية.
PREMIUM_REACTION_PROBE_LEAVE_SECONDS = 1800
PREMIUM_REACTION_EXEC_LEAVE_SECONDS = 300


def _custom_premium_reactions(reactions):
    """Keep only unique custom emoji reactions; exclude regular and paid ones."""
    result = []
    for reaction in reactions or []:
        if (
            _custom_reaction_document_id(reaction) is not None
            and reaction not in result
        ):
            result.append(reaction)
    return result


def _premium_reaction_keyboard(reactions):
    buttons = []
    row = []
    for index, reaction in enumerate(_custom_premium_reactions(reactions), start=1):
        document_id = _custom_reaction_document_id(reaction)
        row.append(
            InlineKeyboardButton(
                f"🎨 تفاعل مميز {index}",
                callback_data=f"raksh_premium_reaction:select:custom_{document_id}",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if buttons:
        buttons.append([
            InlineKeyboardButton(
                "🎲 عشوائي",
                callback_data="raksh_premium_reaction:select:random",
            )
        ])
    buttons.append([
        InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")
    ])
    return InlineKeyboardMarkup(buttons)


async def _resolve_post_entity(client, channel_ref: str, phone_number=None):
    """حل كيان القناة، بما فيها القنوات الخاصة (-100...) بعد الانضمام."""
    if isinstance(channel_ref, str) and channel_ref.startswith("-100") and channel_ref[4:].isdigit():
        from telethon.tl.types import PeerChannel
        channel_id = int(channel_ref[4:])
        try:
            return await client.get_entity(PeerChannel(channel_id))
        except Exception:
            # الجلسة الجديدة لا تملك access_hash؛ تحميل المحادثات يملأ الكاش.
            await client.get_dialogs()
            return await client.get_entity(PeerChannel(channel_id))
    return await _resolve_raksh_entity(client, channel_ref, phone_number)


async def _acquire_session_lock(session, timeout: float = 4.0):
    """اقفل الجلسة كي لا يفتح عاملان نفس auth key (يسبب AUTH_KEY_DUPLICATED).

    يعيد القفل، أو None إن كانت الجلسة مشغولة (حملة مستمرة مثلاً).
    """
    lock = _get_raksh_session_lock(session)
    try:
        await asyncio.wait_for(lock.acquire(), timeout=timeout)
        return lock
    except asyncio.TimeoutError:
        return None


def _is_private_post_ref(channel_ref) -> bool:
    return isinstance(channel_ref, str) and channel_ref.startswith("-100")


def _premium_private_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ لقد قبلت طلب الانضمام",
                callback_data="raksh_premium_reaction:join_accepted",
            )
        ],
        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")],
    ])


def _mask_phone(phone) -> str:
    digits = str(phone or "").strip()
    return f"***{digits[-4:]}" if len(digits) > 4 else "***"


def _premium_reaction_retry_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔄 إعادة جلب التفاعلات",
                callback_data="raksh_premium_reaction:retry_reactions",
            )
        ],
        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")],
    ])

class PremiumReactionService(RakshService):
    """خدمة رشق تفاعل مميز - كل شيء في مكان واحد"""
    
    service_type = "premium_reaction"
    # مهلة أقصر لكل حساب حتى لا يعلق حساب بطيء ويؤخر النتائج (الافتراضي 180).
    account_timeout_seconds = 75
    label = "✨ رشق تفاعل مميز"
    config = ServiceConfig(
        name=label,
        price_points=10,
        points_quantity=1,
        price_stars=2,
        stars_quantity=1,
        has_channel=True,
        has_reaction=True,
        has_ai=False,
        needs_link=True,
        min_delay=3,
        max_delay=3
    )
    
    def get_execution_params(self, context) -> Dict:
        params = super().get_execution_params(context)
        invite = context.user_data.get("raksh_private_invite")
        channels = list(params.get("channel_ref") or [])
        if invite and invite not in channels:
            # كل حساب ينضم لقناة المنشور الخاصة قبل التفاعل (بدون احتسابها في السعر).
            channels.append(invite)
        params["channel_ref"] = channels
        return params

    async def _register_probe_membership(self, context) -> None:
        """سجّل عضوية حساب الفحص ليغادر لاحقاً حتى لو لم يُكمل الطلب."""
        invite = context.user_data.get("raksh_private_invite")
        phone = context.user_data.get("raksh_private_session_phone")
        if not invite or not phone:
            return
        session = next(
            (item for item in (self.get_sessions() or [])
             if str(item.get("phone_number")) == str(phone)),
            None,
        )
        if not session:
            return
        lock = await _acquire_session_lock(session, timeout=5.0)
        if lock is None:
            return
        client = TelegramClient(
            StringSession(session["session_string"]),
            int(TELEGRAM_API_ID),
            TELEGRAM_API_HASH,
        )
        try:
            await asyncio.wait_for(client.connect(), timeout=15)
            await asyncio.wait_for(
                _join_channel_and_schedule_leave(
                    client, invite, phone,
                    leave_after_seconds=PREMIUM_REACTION_PROBE_LEAVE_SECONDS,
                ),
                timeout=40,
            )
        except Exception as e:
            logger.debug("تعذر تسجيل عضوية حساب الفحص: %s", e)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
            lock.release()

    def get_initial_state(self) -> str:
        """البدء بطلب القنوات الإجبارية"""
        return "channel"
    
    def get_link_instruction(self) -> str:
        return "https://t.me/channel/123"
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        
        channel_ref, msg_id = _parse_post_link(value)
        if not channel_ref:
            return "⚠️ الرابط غير صحيح.\n\nأرسل: https://t.me/channel/123"
        
        return None
    
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
            [InlineKeyboardButton("⏭️ تخطي (بدون قنوات)", callback_data="raksh_premium_reaction:skip_channels")],
            [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
        ])

    async def _show_reaction_options(self, target, context, *, edit=False):
        link = context.user_data.get("raksh_link", "")
        preferred_phone = context.user_data.get("raksh_private_session_phone")
        reactions = _custom_premium_reactions(
            await self._fetch_reactions_from_post(link, preferred_phone)
        )
        context.user_data["raksh_available_reactions"] = reactions
        send = target.edit_message_text if edit else target.reply_text

        if not reactions and _is_private_post_ref(_parse_post_link(link)[0]):
            # القناة خاصة ولا يوجد حساب عضو: نطلب رابط الدعوة لإرسال طلب انضمام.
            if preferred_phone:
                context.user_data["raksh_step"] = "private_wait"
                await send(
                    "⏳ لم يتم قبول طلب انضمام الحساب بعد، أو لا توجد تفاعلات مميزة متاحة.\n"
                    "اقبل طلب الانضمام في القناة ثم اضغط الزر مرة أخرى.",
                    reply_markup=_premium_private_keyboard(),
                )
            else:
                context.user_data["raksh_step"] = "private_invite"
                await send(
                    "🔒 هذه القناة خاصة ولا يمكن لحساباتنا الوصول للمنشور.\n\n"
                    "🔗 أرسل *رابط دعوة القناة* (مثل https://t.me/+xxxx) "
                    "💡 أنشئ الرابط من إعدادات القناة ← روابط الدعوة، واترك خيار "
                    "«طلب موافقة المشرفين» *مطفأً* وبدون حد للاستخدام، حتى تنضم "
                    "الحسابات تلقائياً بلا حاجة لقبول طلباتها.\n"
                    "وإن كان الرابط بموافقة فسيُرسل طلب انضمام وعليك قبوله.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
            return False

        if reactions and context.user_data.get("raksh_private_invite"):
            await self._register_probe_membership(context)

        if not reactions:
            context.user_data["raksh_step"] = "quantity"
            await send(
                "⚠️ لم أتمكن من جلب تفاعلات مميزة مخصصة لهذا المنشور.\n"
                "لن أعرض الإيموجيات العادية أو التفاعل المدفوع. أعد المحاولة، "
                "أو استخدم منشوراً يتيح تفاعلات مميزة.",
                reply_markup=_premium_reaction_retry_keyboard(),
            )
            return False

        context.user_data["raksh_step"] = "select_reaction"
        quantity = context.user_data.get("raksh_quantity", 1)
        await send(
            f"✅ تم جلب التفاعلات المميزة المتاحة.\n\n"
            f"📋 *تفاصيل الطلب*\n\n"
            f"📢 القنوات الإجبارية: {len(context.user_data.get('raksh_channels', []))} قناة\n"
            f"🔗 الرابط: `{context.user_data.get('raksh_link', '')}`\n"
            f"🔢 العدد: {quantity}\n\n"
            f"✨ *اختر نوع التفاعل المميز:*\n"
            f"(العشوائي يختار من التفاعلات المميزة المتاحة فقط)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_premium_reaction_keyboard(reactions),
        )
        return True
    
    async def _request_private_join(self, invite_ref: str):
        """يرسل طلب انضمام بحساب واحد. يعيد (الحالة, الجلسة, وصف الحساب)."""
        sessions = list(self.get_sessions() or [])
        random.shuffle(sessions)
        last_error = "لا توجد حسابات متاحة"
        # نجرب عدداً أكبر: كثير من الحسابات قد تكون ميتة أو مشغولة بحملات أخرى.
        for session in sessions[:PREMIUM_REACTION_JOIN_MAX_ATTEMPTS]:
            phone = session.get("phone_number")
            lock = await _acquire_session_lock(session, timeout=2.0)
            if lock is None:
                logger.info("طلب الانضمام: تخطي %s (مشغول)", phone)
                continue
            client = TelegramClient(
                StringSession(session["session_string"]),
                int(TELEGRAM_API_ID),
                TELEGRAM_API_HASH,
            )
            try:
                await asyncio.wait_for(client.connect(), timeout=15)
                if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                    logger.info("طلب الانضمام: الجلسة %s غير مصرح بها", phone)
                    try:
                        _mark_raksh_session_unauthorized(phone)
                    except Exception:
                        pass
                    last_error = "الحسابات المجرّبة غير صالحة"
                    continue
                me = await asyncio.wait_for(client.get_me(), timeout=8)
                name = " ".join(
                    part for part in (getattr(me, "first_name", ""), getattr(me, "last_name", "")) if part
                ) or "—"
                username = getattr(me, "username", None)
                desc = f"👤 الاسم: {name}\n"
                if username:
                    desc += f"🔖 المعرف: @{username}\n"
                desc += f"📱 الرقم: {_mask_phone(session.get('phone_number'))}"

                try:
                    await asyncio.wait_for(
                        client(functions.messages.ImportChatInviteRequest(invite_ref[7:])),
                        timeout=20,
                    )
                    logger.info("📨 انضم الحساب %s للقناة الخاصة مباشرة", phone)
                    return "joined", session, desc
                except Exception as join_error:
                    if _is_join_request_pending_error(join_error):
                        logger.info("📨 أُرسل طلب انضمام من الحساب %s", phone)
                        return "pending", session, desc
                    if _is_already_joined_error(join_error):
                        return "joined", session, desc
                    last_error = str(join_error)[:100]
                    logger.warning("فشل إرسال طلب الانضمام من %s: %s", phone, join_error)
                    # رابط غير صالح/منتهي: لا فائدة من تجربة حسابات أخرى.
                    if type(join_error).__name__ in {
                        "InviteHashExpiredError", "InviteHashInvalidError", "InviteHashEmptyError",
                    }:
                        return "error", None, "رابط الدعوة غير صالح أو منتهي"
            except Exception as e:
                last_error = str(e)[:100]
                logger.warning("فشل تجهيز حساب طلب الانضمام %s: %s", phone, e)
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass
                lock.release()
        return "error", None, last_error

    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        """معالجة النص لخدمة رشق التفاعل المميز"""

        # ═══ قناة خاصة: استقبال رابط الدعوة وإرسال طلب الانضمام ═══
        if state == "private_invite":
            refs = [ref for ref in _parse_channel_refs(text) if ref.startswith("invite:")]
            if not refs:
                await update.message.reply_text(
                    "⚠️ أرسل رابط دعوة صحيح للقناة الخاصة، مثل: https://t.me/+xxxx",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True
            await update.message.reply_text("⏳ *جاري إرسال طلب الانضمام للقناة...*", parse_mode=ParseMode.MARKDOWN)
            status, session, info = await self._request_private_join(refs[0])
            if status == "error":
                await update.message.reply_text(
                    f"❌ تعذر إرسال طلب الانضمام: {info}\nتأكد من أن الرابط صالح وأعد إرساله.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                    ]),
                )
                return True
            context.user_data["raksh_private_session_phone"] = session.get("phone_number")
            context.user_data["raksh_private_invite"] = refs[0]
            if status == "joined":
                context.user_data["raksh_step"] = "fetch_reactions"
                await update.message.reply_text("✅ انضم الحساب للقناة.\n⏳ *جاري جلب التفاعلات...*", parse_mode=ParseMode.MARKDOWN)
                await self._show_reaction_options(update.message, context)
                return True
            context.user_data["raksh_step"] = "private_wait"
            await update.message.reply_text(
                "📨 تم إرسال طلب انضمام للقناة.\n\n"
                "افتح قائمة طلبات الانضمام في قناتك واقبل طلب هذا الحساب:\n"
                f"{info}\n\n"
                "بعد القبول اضغط الزر أدناه لأعرض لك التفاعلات المتاحة.",
                reply_markup=_premium_private_keyboard(),
            )
            return True
        
        # ═══ الخطوة 1: استقبال القنوات الإجبارية ═══
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
        
        # ═══ الخطوة 2: استقبال رابط المنشور ═══
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
            context.user_data.pop("raksh_private_session_phone", None)
            context.user_data.pop("raksh_private_invite", None)
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
                f"✅ تم حفظ رابط المنشور.\n\n"
                f"🔢 *أرسل عدد التفاعلات المطلوبة:*\n"
                f"(الحد الأقصى: {max_qty})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        # ═══ الخطوة 3: استقبال العدد ═══
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
            context.user_data["raksh_step"] = "fetch_reactions"
            context.user_data["raksh_available_reactions"] = []
            
            # ═══ جلب التفاعلات المتاحة من البوست ═══
            await update.message.reply_text(
                "⏳ *جاري جلب التفاعلات المتاحة من المنشور...*",
                parse_mode=ParseMode.MARKDOWN
            )
            await self._show_reaction_options(update.message, context)
            return True
        
        return False
    
    async def handle_callback(self, update, context, query, data_parts, user, is_own) -> bool:
        """معالجة الأزرار لخدمة رشق التفاعل المميز"""
        
        # ═══ تخطي القنوات ═══
        if data_parts[0] == "skip_channels":
            context.user_data["raksh_channels"] = []
            context.user_data["raksh_step"] = "link"
            
            await query.edit_message_text(
                f"✅ تم تخطي القنوات.\n\n"
                f"🔗 *أرسل رابط المنشور:*\n"
                f"{self.get_link_instruction()}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True

        if data_parts[0] == "join_accepted":
            if not context.user_data.get("raksh_link") or not context.user_data.get("raksh_private_session_phone"):
                await query.answer("⚠️ انتهت صلاحية الطلب، ابدأ من جديد.", show_alert=True)
                return True
            context.user_data["raksh_step"] = "fetch_reactions"
            await query.edit_message_text(
                "⏳ *جاري التحقق من القبول وجلب التفاعلات...*",
                parse_mode=ParseMode.MARKDOWN,
            )
            await self._show_reaction_options(query, context, edit=True)
            return True

        if data_parts[0] == "retry_reactions":
            if (
                not context.user_data.get("raksh_link")
                or not context.user_data.get("raksh_quantity")
            ):
                await query.answer(
                    "⚠️ انتهت صلاحية الطلب، ابدأ من جديد.",
                    show_alert=True,
                )
                return True
            context.user_data["raksh_step"] = "fetch_reactions"
            await query.edit_message_text(
                "⏳ *جاري إعادة جلب التفاعلات المميزة...*",
                parse_mode=ParseMode.MARKDOWN,
            )
            await self._show_reaction_options(query, context, edit=True)
            return True
        
        # ═══ اختيار التفاعل ═══
        if data_parts[0] == "select" and len(data_parts) >= 2:
            reaction_key = data_parts[1]
            available_reactions = _custom_premium_reactions(
                context.user_data.get("raksh_available_reactions", [])
            )

            if reaction_key == "random":
                if not available_reactions:
                    await query.answer(
                        "⚠️ لا توجد تفاعلات مميزة متاحة لهذا الطلب.",
                        show_alert=True,
                    )
                    return True
                reaction = "random"
                reaction_label = "🎲 عشوائي"
            elif reaction_key.startswith("custom_") and reaction_key[7:].isdigit():
                doc_id = int(reaction_key[7:])
                reaction = f"{RAKSH_CUSTOM_REACTION_PREFIX}{doc_id}"
                if reaction not in available_reactions:
                    await query.answer(
                        "⚠️ هذا التفاعل المميز غير متاح في المنشور.",
                        show_alert=True,
                    )
                    return True
                reaction_label = (
                    f"🎨 تفاعل مميز {available_reactions.index(reaction) + 1}"
                )
            else:
                await query.answer(
                    "⚠️ هذا الخيار قديم أو غير مدعوم. اختر تفاعلاً مميزاً من القائمة الحالية.",
                    show_alert=True,
                )
                return True
            
            context.user_data["raksh_reaction"] = reaction
            
            quantity = context.user_data.get("raksh_quantity", 1)
            points_cost, free_quantity = self.get_points_quote(
                user.id, quantity, len(context.user_data.get("raksh_channels") or [])
            )
            stars_cost = self.get_total(quantity, "stars", len(context.user_data.get("raksh_channels") or []))
            
            await query.edit_message_text(
                f"📋 *تأكيد الطلب*\n\n"
                f"📢 القنوات الإجبارية: {len(context.user_data.get('raksh_channels', []))} قناة\n"
                f"🔗 الرابط: `{context.user_data.get('raksh_link', '')}`\n"
                f"🔢 العدد: {quantity}\n"
                f"✨ التفاعل: {reaction_label}\n\n"
                f"💳 *اختر طريقة الدفع:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"💰 دفع بالنقاط ({raksh_cost_text(points_cost)})"
                            + (f" — {free_quantity} حساب مجاني" if free_quantity else ""),
                            callback_data=f"raksh_premium_reaction:payment:points:{quantity}:{points_cost}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                            callback_data=f"raksh_premium_reaction:payment:stars:{quantity}:{stars_cost}"
                        )
                    ],
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ])
            )
            return True
        
        # ═══ اختيار طريقة الدفع ═══
        if data_parts[0] == "payment" and len(data_parts) >= 4:
            payment_method = data_parts[1]
            try:
                quantity = int(data_parts[2])
                button_total = int(data_parts[3])
            except ValueError:
                await query.answer("⚠️ العدد أو السعر غير صالح.", show_alert=True)
                return True
            
            if payment_method not in {"points", "stars"}:
                await query.answer("⚠️ طريقة الدفع غير صالحة.", show_alert=True)
                return True
            
            if quantity > self.get_request_limit(user.id):
                await query.edit_message_text(
                    "⚠️ لا يمكن قبول هذا الطلب حالياً. حاول لاحقاً.",
                    reply_markup=get_raksh_menu_keyboard(is_own),
                )
                return True
            
            total_cost = self.get_total(quantity, payment_method, len(context.user_data.get("raksh_channels") or []))
            free_quantity = 0
            if payment_method == "points":
                total_cost, free_quantity = self.get_points_quote(
                    user.id,
                    quantity,
                    len(context.user_data.get("raksh_channels") or []),
                )
            
            await query.edit_message_text(
                f"📋 *تأكيد الطلب*\n\n"
                f"📢 القنوات الإجبارية: {len(context.user_data.get('raksh_channels', []))} قناة\n"
                f"🔗 الرابط: `{context.user_data.get('raksh_link', '')}`\n"
                f"🔢 العدد: {quantity}\n"
                f"✨ التفاعل: {context.user_data.get('raksh_reaction', '')}\n"
                f"💳 طريقة الدفع: {'💰 نقاط' if payment_method == 'points' else '⭐ نجوم'}\n"
                f"💰 التكلفة: {raksh_cost_text(total_cost) if payment_method == 'points' else str(total_cost) + ' نجمة'}\n\n"
                f"*هل تريد تأكيد الطلب؟*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ تأكيد الطلب",
                            callback_data=f"raksh_premium_reaction:confirm:{payment_method}:{quantity}:{total_cost}"
                        ),
                        InlineKeyboardButton(
                            "❌ إلغاء",
                            callback_data="raksh_cancel"
                        )
                    ]
                ])
            )
            return True
        
        # ═══ التأكيد النهائي وبدء التنفيذ ═══
        if data_parts[0] == "confirm" and len(data_parts) >= 4:
            payment_method = data_parts[1]
            try:
                quantity = int(data_parts[2])
                button_total = int(data_parts[3])
            except ValueError:
                await query.answer("⚠️ العدد أو السعر غير صالح.", show_alert=True)
                return True
            
            if payment_method not in {"points", "stars"}:
                await query.answer("⚠️ طريقة الدفع غير صالحة.", show_alert=True)
                return True
            
            if quantity > self.get_request_limit(user.id):
                await query.edit_message_text(
                    "⚠️ لا يمكن قبول هذا الطلب حالياً. حاول لاحقاً.",
                    reply_markup=get_raksh_menu_keyboard(is_own),
                )
                return True
            
            total_cost = self.get_total(quantity, payment_method, len(context.user_data.get("raksh_channels") or []))
            free_quantity = 0
            if payment_method == "points":
                total_cost, free_quantity = self.get_points_quote(
                    user.id,
                    quantity,
                    len(context.user_data.get("raksh_channels") or []),
                )
            
            if payment_method == "points":
                if not deduct_points(user.id, total_cost):
                    await query.edit_message_text(
                        "❌ *نقاطك غير كافية!*\n"
                        f"التكلفة المطلوبة: {raksh_cost_text(total_cost)}",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=get_raksh_menu_keyboard(is_own)
                    )
                    return True
                
                await query.edit_message_text(
                    "✅ *تم تأكيد الطلب وخصم النقاط!*\n\n"
                    f"📋 تفاصيل الطلب:\n"
                    f"📢 القنوات الإجبارية: {len(context.user_data.get('raksh_channels', []))} قناة\n"
                    f"🔗 الرابط: `{context.user_data.get('raksh_link', '')}`\n"
                    f"🔢 العدد: {quantity}\n"
                    f"✨ التفاعل: {context.user_data.get('raksh_reaction', '')}\n"
                    f"💰 تم خصم: {raksh_cost_text(total_cost)}\n\n"
                    f"⏳ جاري الانضمام للقنوات وبدء التنفيذ...",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # استيراد محلي لتجنب مشاكل الاستيراد الدائري
                from .raksh_system import _start_raksh_execution
                await _start_raksh_execution(
                    update, context, query, self.service_type, quantity, "points", total_cost
                )
                return True
            
            else:
                await query.edit_message_text(
                    "⭐ *جاري تجهيز فاتورة الدفع بالنجوم...*",
                    parse_mode=ParseMode.MARKDOWN,
                )
                await context.bot.send_invoice(
                    chat_id=user.id,
                    title=self.config.name,
                    description=f"{quantity} تفاعل مميز | {total_cost} نجمة",
                    payload=f"raksh_stars:{user.id}:{self.service_type}:{quantity}:{total_cost}",
                    provider_token="",
                    currency="XTR",
                    prices=[LabeledPrice("تفاعل مميز", total_cost)],
                )
                return True
        
        return False
    
    async def _fetch_reactions_from_post(self, link: str, preferred_phone: Optional[str] = None) -> List[str]:
        """جلب التفاعلات المميزة المتاحة للمنشور باستخدام عدة جلسات.

        كان الجلب يعتمد على أول جلسة فقط وعلى قائمة التفاعلات المحددة في القناة،
        فيفشل عندما تكون هذه الجلسة معطلة/محظورة مؤقتاً/غير قادرة على الوصول
        للمنشور، أو عندما تسمح القناة بكل التفاعلات (ChatReactionsAll) فلا تحمل
        قائمة صريحة. الآن نجرب عدة جلسات على دفعات، ونكمل القائمة من التفاعلات
        الشائعة/الأخيرة عندما تسمح القناة بالإيموجي المخصص.
        """
        try:
            channel_ref, msg_id = _parse_post_link(link)
            if not channel_ref or not msg_id:
                return []

            sessions = list(self.get_sessions() or [])
            if preferred_phone:
                # قناة خاصة: فقط الحساب الذي أُرسل طلب انضمامه هو العضو.
                sessions = [
                    item for item in sessions
                    if str(item.get("phone_number")) == str(preferred_phone)
                ]
            if not sessions:
                return []
            random.shuffle(sessions)

            batch_size = PREMIUM_REACTION_LOOKUP_BATCH_SIZE
            candidates = sessions[: batch_size * PREMIUM_REACTION_LOOKUP_MAX_BATCHES]
            for offset in range(0, len(candidates), batch_size):
                batch = candidates[offset: offset + batch_size]
                tasks = [
                    asyncio.create_task(
                        self._lookup_reactions_with_session(session, channel_ref, msg_id)
                    )
                    for session in batch
                ]
                try:
                    for completed in asyncio.as_completed(tasks):
                        try:
                            reactions = await completed
                        except Exception:
                            continue
                        if reactions:
                            return reactions
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
            return []
        except Exception as e:
            logger.warning(f"فشل جلب التفاعلات: {e}")
            return []

    async def _lookup_reactions_with_session(
        self, session: Dict, channel_ref: str, msg_id: int
    ) -> List[str]:
        lock = await _acquire_session_lock(session)
        if lock is None:
            logger.info("تخطي الجلسة %s: مشغولة بخدمة أخرى", session.get("phone_number"))
            return []
        try:
            return await asyncio.wait_for(
                self._fetch_reactions_with_session(session, channel_ref, msg_id),
                timeout=PREMIUM_REACTION_LOOKUP_TIMEOUT_SECONDS,
            )
        except Exception as e:
            logger.warning(
                "تعذر جلب التفاعلات المميزة بالجلسة %s: %s",
                session.get("phone_number"),
                e,
            )
            return []
        finally:
            lock.release()

    @staticmethod
    def _custom_keys(reactions) -> List[str]:
        """حوّل كائنات Reaction إلى مفاتيح مخصصة (إيموجي مخصص فقط)."""
        keys = []
        for reaction in reactions or []:
            reaction = getattr(reaction, "reaction", None) or reaction
            if reaction.__class__.__name__ != "ReactionCustomEmoji":
                continue
            doc_id = getattr(reaction, "document_id", None)
            if doc_id:
                key = f"{RAKSH_CUSTOM_REACTION_PREFIX}{doc_id}"
                if key not in keys:
                    keys.append(key)
        return keys

    async def _fetch_reactions_with_session(
        self, session: Dict, channel_ref: str, msg_id: int
    ) -> List[str]:
        client = TelegramClient(
            StringSession(session["session_string"]),
            int(TELEGRAM_API_ID),
            TELEGRAM_API_HASH,
        )
        step_timeout = PREMIUM_REACTION_STEP_TIMEOUT_SECONDS
        try:
            await asyncio.wait_for(client.connect(), timeout=step_timeout)
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=step_timeout):
                return []

            # يحل الاسم العام، ويرجع لمحادثات الحساب عند فشل الحل.
            entity = await asyncio.wait_for(
                _resolve_post_entity(client, channel_ref, session.get("phone_number")),
                timeout=step_timeout * 3,
            )

            message = await asyncio.wait_for(
                client.get_messages(entity, ids=msg_id), timeout=step_timeout
            )
            if isinstance(message, (list, tuple)):
                message = message[0] if message else None
            if not message:
                return []

            # (أ) التفاعلات المستخدمة فعلاً في المنشور.
            message_reactions = getattr(message, "reactions", None)
            from_message = self._custom_keys(
                getattr(item, "reaction", None)
                for item in (getattr(message_reactions, "results", None) or [])
            )
            from_message += [
                key
                for key in self._custom_keys(
                    getattr(item, "reaction", None)
                    for item in (getattr(message_reactions, "recent_reactions", None) or [])
                )
                if key not in from_message
            ]

            # (ب) إعدادات القناة/المجموعة.
            available = None
            try:
                if entity.__class__.__name__ == "Chat":
                    full = await asyncio.wait_for(
                        client(functions.messages.GetFullChatRequest(chat_id=entity.id)),
                        timeout=step_timeout,
                    )
                else:
                    full = await asyncio.wait_for(
                        client(functions.channels.GetFullChannelRequest(channel=entity)),
                        timeout=step_timeout,
                    )
                available = getattr(getattr(full, "full_chat", None), "available_reactions", None)
            except Exception as e:
                logger.debug("تعذر جلب إعدادات تفاعلات القناة: %s", e)
                return from_message

            kind = available.__class__.__name__ if available is not None else ""
            if kind == "ChatReactionsNone":
                return []
            if kind == "ChatReactionsSome":
                # القائمة المحددة في القناة هي المرجع الوحيد لما هو مسموح.
                return self._custom_keys(getattr(available, "reactions", None))

            # ChatReactionsAll أو لا إعداد: الإيموجي المخصص مسموح إن لم يُمنع صراحة.
            if kind == "ChatReactionsAll" and getattr(available, "allow_custom", True) is False:
                return []

            result = list(from_message)
            for request_name in ("GetTopReactionsRequest", "GetRecentReactionsRequest"):
                try:
                    request_cls = getattr(functions.messages, request_name)
                    response = await asyncio.wait_for(
                        client(request_cls(limit=PREMIUM_REACTION_POOL_LIMIT, hash=0)),
                        timeout=step_timeout,
                    )
                    for key in self._custom_keys(getattr(response, "reactions", None)):
                        if key not in result:
                            result.append(key)
                except Exception as e:
                    logger.debug("تعذر جلب %s: %s", request_name, e)
            return result
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ رشق تفاعل مميز - فتح الرابط والتفاعل بالإيموجي المختار"""
        # flood_sleep_threshold صغير: لا ينام الحساب دقيقة كاملة داخل Telethon،
        # وإعادة المحاولات أقل حتى لا يتأخر الحساب المعطوب.
        client = TelegramClient(
            StringSession(session["session_string"]),
            int(TELEGRAM_API_ID),
            TELEGRAM_API_HASH,
            flood_sleep_threshold=10,
            connection_retries=2,
            retry_delay=1,
            request_retries=2,
        )
        await asyncio.wait_for(client.connect(), timeout=12)
        joined = []
        join_failed = []
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"
            
            # 1️⃣ الانضمام للقنوات (يغادر الحساب بعد التفاعل مباشرة)
            if params.get("channel_ref"):
                for channel_ref in params["channel_ref"]:
                    try:
                        joined_entity = await _join_channel_and_schedule_leave(
                            client,
                            channel_ref,
                            session.get("phone_number"),
                            return_entity=True,
                            leave_after_seconds=PREMIUM_REACTION_EXEC_LEAVE_SECONDS,
                        )
                        if joined_entity is not None and not isinstance(joined_entity, bool):
                            joined.append((channel_ref, joined_entity))
                        elif joined_entity is False:
                            join_failed.append(channel_ref)
                        await asyncio.sleep(0.2)
                    except Exception as e:
                        logger.warning(f"فشل الانضمام للقناة {channel_ref}: {e}")
            
            # 2️⃣ تحليل رابط المنشور
            channel_ref, msg_id = _parse_post_link(params["link"])
            if not channel_ref:
                return False, "رابط المنشور غير صحيح"
            
            # 3️⃣ الوصول إلى القناة والمنشور
            entity = await _resolve_post_entity(client, channel_ref, session.get("phone_number"))
            
            # 4️⃣ تحديد التفاعل المختار
            reaction_value = params.get("reaction", "random")
            available_reactions = _custom_premium_reactions(
                params.get("available_reactions")
            )
            if reaction_value == "random":
                if not available_reactions:
                    return False, "لا توجد تفاعلات مميزة متاحة لهذا المنشور"
                reaction_value = random.choice(available_reactions)

            document_id = _custom_reaction_document_id(reaction_value)
            if document_id is None or reaction_value not in available_reactions:
                return False, "التفاعل المميز المختار غير متاح لهذا المنشور"
            
            # 5️⃣ تنفيذ التفاعل - الطريقة الصحيحة
            try:
                await client(SendReactionRequest(
                    peer=entity,
                    msg_id=msg_id,
                    reaction=[ReactionCustomEmoji(document_id=document_id)]
                ))
                return True, f"✅ تم التفاعل من {session['phone_number']}"
                
            except Exception as e:
                logger.warning(f"فشل التفاعل {reaction_value}: {e}")
                note = " (تعذر الانضمام للقناة)" if join_failed else ""
                return False, f"❌ فشل إرسال التفاعل المميز: {str(e)}{note}"
                
        except Exception as e:
            note = " (تعذر الانضمام للقناة)" if join_failed else ""
            return False, f"❌ فشل: {str(e)}{note}"
        finally:
            await self._leave_joined_channels(client, session.get("phone_number"), joined)
            await client.disconnect()

    async def _leave_joined_channels(self, client, phone_number, joined) -> None:
        """يغادر الحساب القنوات التي انضم لها لهذا التفاعل ويحذف سجل مهلتها."""
        from telethon.tl.functions.channels import LeaveChannelRequest
        for channel_ref, entity in joined:
            try:
                await asyncio.wait_for(client(LeaveChannelRequest(entity)), timeout=15)
            except Exception as e:
                # تبقى مهلة المغادرة الاحتياطية في قاعدة البيانات لتنظفها المهمة الدورية.
                logger.debug("تعذرت المغادرة الفورية من %s: %s", channel_ref, e)
                continue
            try:
                with db_conn() as c:
                    c.execute(
                        "DELETE FROM raksh_channel_memberships WHERE phone_number=%s AND channel_ref=%s",
                        (str(phone_number).strip(), _normalize_raksh_channel_ref(channel_ref)),
                    )
            except Exception as e:
                logger.debug("تعذر حذف سجل العضوية: %s", e)
