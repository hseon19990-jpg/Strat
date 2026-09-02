from .common import *

class PollService(RakshService):
    """خدمة رشق استفتاء - كل شيء في مكان واحد"""
    
    service_type = "poll"
    label = "📊 رشق استفتاء"
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
        min_delay=60,
        max_delay=120
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
        """تنفيذ رشق استفتاء"""
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
            message = await client.get_messages(entity, ids=msg_id)
            if not message:
                return False, "المنشور غير موجود"
            
            poll = getattr(message, "poll", None)
            if not poll:
                return False, "هذا المنشور ليس استفتاءً"
            
            options = getattr(poll, "answers", [])
            if not options:
                return False, "الاستفتاء ليس له خيارات"
            
            option_request = params.get("poll_option", "1")
            option = _select_poll_option(options, option_request)
            if not option:
                return False, f"الخيار {option_request} غير موجود"
            
            success = await _send_vote_and_check(client, entity, msg_id, option)
            if not success:
                return False, "تعذر تأكيد التصويت"
            
            return True, f"✅ تم التصويت من {session['phone_number']}"
        except Exception as e:
            return False, f"❌ فشل التصويت: {str(e)}"
        finally:
            await client.disconnect()
