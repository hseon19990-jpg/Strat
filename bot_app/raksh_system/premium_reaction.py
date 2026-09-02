from .common import *

class PremiumReactionService(RakshService):
    """خدمة رشق تفاعل مميز - كل شيء في مكان واحد"""
    
    service_type = "premium_reaction"
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
        min_delay=30,
        max_delay=60
    )
    
    def get_link_instruction(self) -> str:
        return "https://t.me/channel/123"
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        if not all(_parse_post_link(value)):
            return "⚠️ الرابط غير صحيح لهذه الخدمة.\n\nأرسل: https://t.me/channel/123"
        return None
    
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ رشق تفاعل مميز"""
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
            
            reaction = params.get("reaction")
            if not reaction or reaction == "random":
                available = params.get("available_reactions") or list(RAKSH_REACTIONS.values())
                reaction = random.choice(available)
            
            if reaction == RAKSH_PAID_REACTION:
                try:
                    await client(
                        SendReactionRequest(
                            peer=entity,
                            msg_id=msg_id,
                            reaction=ReactionEmoji(emoticon="⭐"),
                            big=True,
                        )
                    )
                    return True, f"✅ تم التفاعل المدفوع من {session['phone_number']}"
                except Exception as e:
                    logger.warning(f"فشل التفاعل المدفوع: {e}")
                    return False, f"فشل التفاعل المدفوع: {str(e)}"
            else:
                try:
                    await client(
                        SendReactionRequest(
                            peer=entity,
                            msg_id=msg_id,
                            reaction=ReactionEmoji(emoticon=reaction),
                        )
                    )
                    return True, f"✅ تم التفاعل من {session['phone_number']}"
                except Exception as e:
                    return False, f"فشل التفاعل: {str(e)}"
        except Exception as e:
            return False, f"❌ فشل: {str(e)}"
        finally:
            await client.disconnect()

# ════════════════════════════════════════════════════════
