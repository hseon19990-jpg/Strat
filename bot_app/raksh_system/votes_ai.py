from .common import *

from .votes import VotesService

class VotesAIService(RakshService):
    """خدمة رشق تصويت مع تحقق - كل شيء في مكان واحد"""
    
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
        max_concurrent=1
    )
    
    def get_link_instruction(self) -> str:
        return "https://t.me/i8YYBot?start=compvote_xxx"
    
    def validate_link(self, value: str) -> Optional[str]:
        if not value.strip():
            return "⚠️ الرابط لا يمكن أن يكون فارغاً"
        if not ("@" in value or "t.me/" in value):
            return "⚠️ الرابط يجب أن يحتوي على @username أو t.me/"
        return None
    
    async def execute(self, session, params, is_first):
        """تنفيذ تصويت مع تحقق"""
        client = TelegramClient(StringSession(session["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=15)
        try:
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                _mark_raksh_session_unauthorized(session.get("phone_number"))
                return False, "الجلسة غير مصرح بها."

            bot_username, bot_start_param = _parse_bot_link(params.get("link", ""))
            bot_entity = None

            if bot_username and bot_start_param:
                try:
                    resolved = await client(ResolveUsernameRequest(bot_username))
                    if resolved.users:
                        bot_entity = resolved.users[0]
                    elif resolved.chats:
                        bot_entity = resolved.chats[0]
                except Exception:
                    try:
                        bot_entity = await client.get_entity(bot_username)
                    except Exception:
                        try:
                            bot_entity = await client.get_entity(f"@{bot_username}")
                        except Exception as e3:
                            return False, f"فشل العثور على البوت {bot_username}: {str(e3)[:80]}"
            else:
                post_ref, post_id = _parse_post_link(params.get("link", ""))
                if not post_ref or not post_id:
                    return False, "الرابط غير صالح (ليس بوتًا ولا بوستًا)."

                try:
                    post_entity = await client.get_entity(post_ref)
                except Exception:
                    return False, "تعذر الوصول إلى القناة/المنشور."

                try:
                    messages = await client.get_messages(post_entity, ids=post_id)
                    if isinstance(messages, (list, tuple)):
                        messages = messages[0] if messages else None
                    else:
                        messages = messages
                    if not messages:
                        return False, "المنشور غير موجود."
                    post_message = messages
                except Exception:
                    return False, "تعذر جلب المنشور."

                bot_username, bot_start_param = _find_bot_start_link(post_message)
                if not bot_username or not bot_start_param:
                    return False, "المنشور لا يحتوي على زر بوت صالح."

                try:
                    bot_entity = await client.get_entity(bot_username)
                except Exception:
                    try:
                        bot_entity = await client.get_entity(f"@{bot_username}")
                    except Exception as e3:
                        return False, f"تعذر العثور على بوت الزر: {str(e3)[:80]}"

            await client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=bot_start_param
            ))

            await asyncio.sleep(1.0)
            verification_message_id = None
            verification_message = None
            for attempt in range(5):
                msgs = await client.get_messages(bot_entity, limit=50)
                if isinstance(msgs, (list, tuple)):
                    for m in msgs:
                        if getattr(m, "buttons", None) and not getattr(m, "url", None):
                            verification_message = m
                            verification_message_id = m.id
                            break
                    if verification_message:
                        break
                await asyncio.sleep(1.0)

            if verification_message is None or verification_message_id is None:
                logger.info(f"لم يظهر زر تحقق بعد فتح البوت، تعتبر العملية ناجحة (بدون تحقق) للحساب {session['phone_number']}")
                return True, RAKSH_NO_VERIFICATION_MESSAGE

            verification_text = getattr(verification_message, "message", "") or getattr(verification_message, "text", "") or ""
            
            target_emoji = None
            emoji_pattern = re.compile(
                "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E0-\U0001F1FF]"
            )
            found_emojis = emoji_pattern.findall(verification_text)
            if found_emojis:
                target_emoji = found_emojis[-1]
                logger.info(f"✅ تم استخراج الإيموجي المطلوب: {target_emoji}")

            all_buttons = []
            for row in (getattr(verification_message, "buttons", None) or []):
                for btn in row:
                    if not getattr(btn, "url", None):
                        all_buttons.append(btn)

            if not all_buttons:
                logger.info(f"رسالة التحقق لا تحتوي أزرار قابلة للضغط، تعتبر العملية ناجحة (بدون تحقق) للحساب {session['phone_number']}")
                return True, RAKSH_NO_VERIFICATION_MESSAGE

            buttons_to_try = []
            if target_emoji:
                exact = [b for b in all_buttons if getattr(b, "text", "") == target_emoji]
                buttons_to_try.extend(exact)
                partial = [b for b in all_buttons if target_emoji in (getattr(b, "text", "") or "")]
                buttons_to_try.extend(partial)
            verify = [b for b in all_buttons if any(w in (getattr(b, "text", "") or "").lower() for w in ['تحقق', 'verify', 'اضغط هنا', 'continue', 'التالي'])]
            buttons_to_try.extend(verify)
            emojis = [b for b in all_buttons if any(0x1F300 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF for c in (getattr(b, "text", "") or ""))]
            buttons_to_try.extend(emojis)
            buttons_to_try.extend([b for b in all_buttons if b not in buttons_to_try])

            seen = set()
            unique_buttons = []
            for b in buttons_to_try:
                if id(b) not in seen:
                    seen.add(id(b))
                    unique_buttons.append(b)

            max_attempts = 30
            pressed_ids = set()
            current_index = 0
            for attempt in range(max_attempts):
                try:
                    target_message = await client.get_messages(bot_entity, ids=verification_message_id)
                    if isinstance(target_message, (list, tuple)):
                        target_message = target_message[0] if target_message else None
                except Exception:
                    target_message = None

                if target_message is None:
                    logger.info(f"✅ رسالة التحقق اختفت تماماً – تم تأكيد التحقق للحساب {session['phone_number']}")
                    return True, f"✅ تم تسجيل التصويت من {session['phone_number']}"

                if not getattr(target_message, "buttons", None):
                    logger.info(f"✅ اختفت أزرار رسالة التحقق – تم تأكيد التحقق للحساب {session['phone_number']}")
                    return True, f"✅ تم تسجيل التصويت من {session['phone_number']}"

                button = None
                if target_emoji:
                    for row in (getattr(target_message, "buttons", None) or []):
                        for b in row:
                            if not getattr(b, "url", None) and (getattr(b, "text", "") == target_emoji or target_emoji in (getattr(b, "text", "") or "")) and id(b) not in pressed_ids:
                                button = b
                                break
                        if button:
                            break

                if button is None:
                    while current_index < len(unique_buttons) and id(unique_buttons[current_index]) in pressed_ids:
                        current_index += 1
                    if current_index < len(unique_buttons):
                        button = unique_buttons[current_index]
                        current_index += 1
                    else:
                        pressed_ids.clear()
                        current_index = 0
                        if unique_buttons:
                            button = unique_buttons[current_index]
                            current_index += 1
                        else:
                            break

                if button is None:
                    break

                button_text = getattr(button, "text", "") or ""
                logger.info(f"🖱️ الحساب {session['phone_number']} – محاولة {attempt+1}: الضغط على '{button_text}'")
                try:
                    await button.click()
                except Exception as e:
                    logger.warning(f"⚠️ فشل الضغط على الزر '{button_text}': {e}")
                    continue

                pressed_ids.add(id(button))
                await asyncio.sleep(2.0)

            try:
                final_message = await client.get_messages(bot_entity, ids=verification_message_id)
                if isinstance(final_message, (list, tuple)):
                    final_message = final_message[0] if final_message else None
            except Exception:
                final_message = None

            if final_message is None or not getattr(final_message, "buttons", None):
                logger.info(f"✅ اختفت الأزرار في الفحص النهائي – تم تأكيد التحقق للحساب {session['phone_number']}")
                return True, f"✅ تم تسجيل التصويت من {session['phone_number']}"
            else:
                logger.warning(f"⚠️ لم تختفِ أزرار رسالة التحقق بعد {max_attempts} محاولة للحساب {session['phone_number']}")
                return False, "لم تختفِ أزرار التحقق – فشل"

        except Exception as e:
            return False, f"❌ فشل: {str(e)[:80]}"
        finally:
            await client.disconnect()
