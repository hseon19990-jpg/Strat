from .common import *

class VotesService(RakshService):
    """خدمة رشق أصوات - كل شيء في مكان واحد"""
    
    service_type = "votes"
    label = "🗳 رشق أصوات"
    config = ServiceConfig(
        name=label,
        price_points=20,
        points_quantity=1,
        price_stars=4,
        stars_quantity=1,
        has_channel=True,
        has_reaction=False,
        has_ai=False,
        needs_link=True,
        min_delay=3,
        max_delay=3
    )
    
    def get_link_instruction(self) -> str:
        return "https://t.me/channel/123 أو رابط بوت تصويت"
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        return None
    
    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        """تنفيذ رشق أصوات"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها"
            
            if is_first and params.get("channel_ref"):
                await _join_channel_and_schedule_leave(client, params["channel_ref"])
            
            link = params["link"]
            channel_ref, msg_id = _parse_post_link(link)
            if not channel_ref:
                bot_username, start_param = _parse_bot_link(link)
                if bot_username:
                    clean_username = bot_username.lstrip("@").strip()
                    resolved = await client(ResolveUsernameRequest(clean_username))
                    bot_entity = resolved.users[0] if resolved.users else resolved.chats[0]
                    await client(StartBotRequest(
                        bot=bot_entity,
                        peer=bot_entity,
                        start_param=start_param or ""
                    ))
                    await asyncio.sleep(1.5)
                    return True, f"✅ تم التصويت من {session['phone_number']}"
                return False, "الرابط غير صحيح لهذه الخدمة"
            
            entity = await client.get_entity(channel_ref)
            message = await client.get_messages(entity, ids=msg_id)
            if not message:
                return False, "المنشور غير موجود"
            
            vote_button = None
            for row in getattr(message, "buttons", None) or []:
                for btn in row:
                    if getattr(btn, "url", None):
                        continue
                    btn_text = (getattr(btn, "text", None) or "").lower()
                    if any(word in btn_text for word in ["تصويت", "صوت", "vote", "voting"]):
                        vote_button = btn
                        break
                if vote_button:
                    break
            
            if vote_button:
                await vote_button.click()
                await asyncio.sleep(1.0)
                return True, f"✅ تم التصويت من {session['phone_number']}"
            else:
                return False, "لم يتم العثور على زر التصويت"
        except Exception as e:
            return False, f"❌ فشل التصويت: {str(e)}"
        finally:
            await client.disconnect()
