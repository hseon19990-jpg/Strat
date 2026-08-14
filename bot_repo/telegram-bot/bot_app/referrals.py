"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

import re
import unicodedata


_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x2600, 0x27BF),
)


def _normalize_captcha_text(value) -> str:
    """توحيد نص Groq ونص الزر قبل المقارنة."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return (
        text.replace("\ufe0f", "")
        .replace("\u200d", "")
        .replace("\u200c", "")
        .replace("\u200b", "")
        .strip()
    )


def _emoji_tokens(value) -> str:
    """استخراج الإيموجي فقط، مع تجاهل العدادات والمسافات."""
    text = _normalize_captcha_text(value)
    return "".join(
        char
        for char in text
        if any(start <= ord(char) <= end for start, end in _EMOJI_RANGES)
    )


def _captcha_button_matches(button_text, target) -> bool:
    """مطابقة هدف Groq مع زر Telegram حتى مع اختلاف Unicode أو وجود عدّاد."""
    button_text = str(button_text or "").strip()
    target = str(target or "").strip().strip("`'\"“”‘’")
    if not button_text or not target:
        return False

    normalized_button = _normalize_captcha_text(button_text)
    normalized_target = _normalize_captcha_text(target)
    if normalized_target in normalized_button or normalized_button in normalized_target:
        return True

    target_emojis = _emoji_tokens(target)
    button_emojis = _emoji_tokens(button_text)
    return bool(target_emojis and target_emojis in button_emojis)

def get_referral_tasks(only_active: bool = False) -> list:
    with db_conn() as c:
        sql = "SELECT * FROM referral_tasks"
        if only_active:
            sql += " WHERE active=TRUE"
        sql += " ORDER BY id ASC"
        return [dict(r) for r in c.execute(sql).fetchall()]

def get_referral_task(task_id: int) -> dict | None:
    with db_conn() as c:
        row = c.execute("SELECT * FROM referral_tasks WHERE id=%s", (task_id,)).fetchone()
        return dict(row) if row else None

def add_referral_task(label: str, bot_username: str, start_param: str,
                       mandatory_channels: str = "", folder_link: str = "") -> int:
    with db_conn() as c:
        row = c.execute(
            "INSERT INTO referral_tasks "
            "(label, bot_username, start_param, mandatory_channels, folder_link) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (label, bot_username, start_param, mandatory_channels or "", folder_link or "")
        ).fetchone()
        return row["id"]

def delete_referral_task(task_id: int):
    with db_conn() as c:
        c.execute("DELETE FROM referral_completions WHERE task_id=%s", (task_id,))
        c.execute("DELETE FROM referral_tasks WHERE id=%s", (task_id,))

def toggle_referral_task(task_id: int) -> bool:
    """يعكس حالة التفعيل ويُرجع الحالة الجديدة (True=نشط)."""
    with db_conn() as c:
        row = c.execute("SELECT active FROM referral_tasks WHERE id=%s", (task_id,)).fetchone()
        if not row:
            return False
        new_val = 0 if row["active"] else 1
        c.execute("UPDATE referral_tasks SET active=%s WHERE id=%s", (new_val, task_id))
        return bool(new_val)

def get_referral_task_stats(task_id: int) -> dict:
    """يُرجع إحصاء: done / failed / pending / total لمهمة إحالة معيّنة."""
    with db_conn() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) as cnt FROM referral_completions WHERE task_id=%s GROUP BY status",
            (task_id,)
        ).fetchall()
        stats = {"done": 0, "failed": 0, "pending": 0}
        for r in rows:
            stats[r["status"]] = r["cnt"]
        stats["total"] = sum(stats.values())
        return stats

def get_pending_numbers_for_task(task_id: int) -> list:
    """أرقام المخزون التي لم تُكمل هذه المهمة بعد (لم تُسجَّل في referral_completions بحالة done).
    القيد الوحيد: استبعاد الحسابات المباعة (ever_sold IS TRUE).
    الأرقام بدون جلسة تُتجاوز وقت التشغيل ولا تُسجَّل كـ failed (تُعاد في الدورة التالية)."""
    with db_conn() as c:
        rows = c.execute(
            """
            SELECT ns.id, ns.phone_number, ns.session_string
            FROM number_stock ns
            WHERE ns.ever_sold IS NOT TRUE
              AND ns.id NOT IN (
                  SELECT stock_id FROM referral_completions
                  WHERE task_id=%s AND status='done'
              )
            ORDER BY ns.id ASC
            """,
            (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

def mark_referral_completion(task_id: int, stock_id: int, status: str, error_msg: str = None):
    with db_conn() as c:
        c.execute(
            """
            INSERT INTO referral_completions (task_id, stock_id, status, done_at, error_msg)
            VALUES (%s, %s, %s, NOW(), %s)
            ON CONFLICT (task_id, stock_id) DO UPDATE
              SET status=EXCLUDED.status, done_at=EXCLUDED.done_at, error_msg=EXCLUDED.error_msg
            """,
            (task_id, stock_id, status, error_msg)
        )

# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

def is_groq_available() -> bool:
    """يتحقق من وجود مفتاح Groq في البيئة."""
    return bool(os.environ.get("GROQ_API_KEY"))

def is_deepseek_available() -> bool:
    """يتحقق من وجود مفتاح DeepSeek في البيئة."""
    return bool(os.environ.get("DEEPSEEK_API_KEY"))

def is_ai_available() -> bool:
    """يتحقق من وجود مفتاح Groq أو DeepSeek."""
    return is_groq_available() or is_deepseek_available()

def is_telegram_api_configured() -> bool:
    """يتحقق من وجود بيانات Telegram API."""
    return bool(TELEGRAM_API_ID and TELEGRAM_API_HASH)

# ─── دوال مساعدة للإحالة التلقائية ───

def _parse_channel_tokens(raw: str) -> list:
    """يحوّل نص القنوات (مسافة / سطر جديد فاصل) إلى قائمة من dict {type, value}.
    يقبل: @username  أو  t.me/username  أو  t.me/+HASH  أو  t.me/joinchat/HASH
    """
    import re as _re
    results = []
    for tok in _re.split(r'[\s,]+', raw.strip()):
        tok = tok.strip()
        if not tok:
            continue
        if 't.me/' in tok or 'telegram.me/' in tok:
            from urllib.parse import urlparse as _up
            parsed = _up(tok if tok.startswith('http') else 'https://' + tok)
            path = parsed.path.strip('/')
            if path.startswith('+'):
                results.append({'type': 'invite', 'value': path[1:]})
            elif 'joinchat/' in path:
                results.append({'type': 'invite', 'value': path.split('joinchat/')[-1]})
            else:
                part = path.split('/')[0]
                if part:
                    results.append({'type': 'username', 'value': part})
        elif tok.startswith('@'):
            results.append({'type': 'username', 'value': tok[1:]})
        else:
            results.append({'type': 'username', 'value': tok})
    return results

async def _join_mandatory_channels(client, raw_channels: str) -> int:
    """ينضم لجميع القنوات الإجبارية. يُرجع عدد ما نجح."""
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.tl.functions.messages import ImportChatInviteRequest
    tokens = _parse_channel_tokens(raw_channels)
    joined = 0
    for tok in tokens:
        try:
            if tok['type'] == 'invite':
                await client(ImportChatInviteRequest(tok['value']))
            else:
                ch = await client.get_entity(tok['value'])
                await client(JoinChannelRequest(ch))
            joined += 1
            await asyncio.sleep(1.5)
        except Exception as e:
            logger.warning(f"⚠️ تعذّر الانضمام لـ {tok}: {e}")
    return joined

async def _leave_mandatory_channels(client, raw_channels: str) -> int:
    """يغادر جميع القنوات الإجبارية بعد اكتمال العملية. يُرجع عدد ما نجح."""
    from telethon.tl.functions.channels import LeaveChannelRequest
    tokens = _parse_channel_tokens(raw_channels)
    left = 0
    for tok in tokens:
        try:
            ch = await client.get_entity(tok['value'])
            await client(LeaveChannelRequest(ch))
            left += 1
            await asyncio.sleep(1.0)
        except Exception as e:
            logger.warning(f"⚠️ تعذّر مغادرة {tok}: {e}")
    return left

async def _join_folder_link(client, folder_url: str) -> str:
    """ينضم لمجلد تيليجرام (addlist link). إذا وصل الحد (2) يحذف الأقدم."""
    try:
        from telethon.tl.functions.chatlists import (
            CheckChatlistInviteRequest,
            JoinChatlistInviteRequest,
            GetChatlistsRequest,
            LeaveChatlistRequest,
        )
        import re as _re
        m = _re.search(r'addlist/([A-Za-z0-9_-]+)', folder_url)
        if not m:
            return "رابط مجلد غير صحيح"
        folder_hash = m.group(1)

        try:
            current = await client(GetChatlistsRequest())
            folders = getattr(current, 'filters', []) or []
        except Exception:
            folders = []

        if len(folders) >= 2:
            try:
                oldest = folders[0]
                await client(LeaveChatlistRequest(
                    chatlist=oldest,
                    peers=[]
                ))
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"⚠️ تعذّر حذف مجلد قديم: {e}")

        invite_info = await client(CheckChatlistInviteRequest(slug=folder_hash))
        await client(JoinChatlistInviteRequest(
            slug=folder_hash,
            peers=getattr(invite_info, 'peers', []) or [],
        ))
        return "انضم للمجلد ✅"
    except Exception as e:
        logger.warning(f"⚠️ تعذّر الانضمام للمجلد: {e}")
        return f"فشل المجلد: {str(e)[:60]}"


async def _solve_text(prompt: str) -> str | None:
    """يحل النصوص باستخدام Groq API فقط."""
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    
    if not GROQ_API_KEY:
        logger.warning("⚠️ GROQ_API_KEY مفقود")
        return None

    def _groq_request():
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.3-70b-versatile",  # النموذج الأحدث
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 20,
                    "temperature": 0
                },
                timeout=15
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("error"):
                    logger.warning(f"⚠️ Groq JSON error: {data['error']}")
                    return None
                if data.get("choices") and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"].strip()
            else:
                logger.warning(f"⚠️ Groq HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.warning(f"⚠️ Groq exception: {e}")
        return None

    result = await asyncio.to_thread(_groq_request)
    if result:
        logger.info(f"🤖 Groq → '{result[:30]}...'")
    else:
        logger.warning("⚠️ Groq فشل تماماً")
    return result


async def _solve_image(prompt: str, img_bytes: bytes) -> str | None:
    """يحل صور الكابتشا باستخدام Groq Vision."""
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    
    if GROQ_API_KEY:
        def _groq_vision_request():
            try:
                import base64
                img_b64 = base64.b64encode(img_bytes).decode()
                r = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {GROQ_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "llama-3.2-90b-vision-preview",
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                            ]
                        }],
                        "max_tokens": 20,
                        "temperature": 0
                    },
                    timeout=35
                )
                if r.status_code == 200:
                    data = r.json()
                    if data.get("choices"):
                        return data["choices"][0]["message"]["content"].strip()
                return None
            except Exception:
                return None
        return await asyncio.to_thread(_groq_vision_request)
    return None


async def solve_captcha_with_ai(client, bot_entity, msgs: list, phone: str = "", max_attempts: int = 3) -> tuple:
    """
    دالة ذكية شاملة لحل أي نوع من الكابتشا.
    تستخدم Groq Vision لتحليل الصورة، وGroq Text للكتابة،
    وتتعامل مع الأزرار، الأرقام، الإيموجي، وجهات الاتصال.
    """
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    if not GROQ_API_KEY:
        return False, "لا يوجد مفتاح GROQ_API_KEY"

    # دالة مساعدة لتحليل الصورة وإرجاع ما يجب فعله
    async def _analyze_screen_via_vision(msg_id):
        try:
            # 1. تنزيل صورة الرسالة (الشاشة)
            img_bytes = await client.download_media(msg_id, bytes)
            if not img_bytes:
                return None
            
            import base64
            img_b64 = base64.b64encode(img_bytes).decode()

            # 2. إرسال الصورة لـ Groq Vision
            def _vision_request():
                try:
                    r = requests.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {GROQ_API_KEY}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": "llama-3.2-90b-vision-preview",
                            "messages": [{
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "أنت بوت تيليغرام. هذه صورة لرسالة تحقق (كابتشا) تطلب مني إجراءً معيناً. حلل الصورة وأخبرني:\n1. ما هو الإجراء المطلوب؟ (اكتب: 'زر'، 'كتابة'، 'جهة اتصال'، أو 'لا شيء')\n2. إذا كان 'زر'، ما هو النص الظاهر على الزر الصحيح؟ وإذا كان الزر إيموجياً فأعد الإيموجي نفسه فقط بدون شرح أو عدّاد.\n3. إذا كان 'كتابة'، ما هو الجواب الصحيح الذي يجب كتابته؟ (مثل رقم ناتج مسألة رياضية).\nأجب بصيغة JSON فقط: {\"action\": \"زر\", \"target\": \"الإيموجي أو نص الزر فقط\"} أو {\"action\": \"كتابة\", \"answer\": \"الجواب\"} أو {\"action\": \"جهة اتصال\", \"target\": \"ارسل البيانات\"}."},
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                                ]
                            }],
                            "max_tokens": 100,
                            "temperature": 0
                        },
                        timeout=35
                    )
                    if r.status_code == 200:
                        data = r.json()
                        if data.get("choices"):
                            content = data["choices"][0]["message"]["content"].strip()
                            import json
                            try:
                                return json.loads(content)
                            except json.JSONDecodeError:
                                return None
                    return None
                except Exception:
                    return None
            return await asyncio.to_thread(_vision_request)
        except Exception:
            return None

    # ── بدء حل الكابتشا ──
    for _round in range(max_attempts):
        if _round > 0:
            await asyncio.sleep(3)
        
        # ابحث عن رسالة تحتوي على أزرار أو نص تحقق
        for msg in msgs:
            if not msg.text and not msg.buttons:
                continue
            
            # 1. استخدم الرؤية لتحليل الشاشة
            analysis = await _analyze_screen_via_vision(msg.id)
            if not isinstance(analysis, dict):
                continue

            action = _normalize_captcha_text(analysis.get("action"))
            target = analysis.get("target") or analysis.get("answer")

            # ── الحالة 1: زر إيموجي أو زر نصي ──
            is_button_action = (
                action in {"زر", "button", "emoji", "إيموجي", "click"}
                or "زر" in action
                or "button" in action
                or "emoji" in action
            )
            if is_button_action and msg.buttons:
                button_labels = [
                    (getattr(btn, "text", "") or "").strip()
                    for row in msg.buttons
                    for btn in row
                    if getattr(btn, "text", None)
                    and not getattr(btn, "url", None)
                ]
                logger.info(
                    "🤖 Groq target=%r action=%r | أزرار التحقق=%r",
                    target,
                    action,
                    button_labels,
                )
                for row in msg.buttons:
                    for btn in row:
                        # نبحث عن الزر الذي يطابق ما قاله الذكاء الاصطناعي
                        if _captcha_button_matches(
                            getattr(btn, "text", ""),
                            target,
                        ):
                            try:
                                await btn.click()
                                await asyncio.sleep(2)
                                # تحقق من النجاح
                                new_msgs = await client.get_messages(bot_entity, limit=5)
                                for nm in new_msgs:
                                    if any(k in nm.text for k in ["أهلاً", "مرحباً", "تم", "success", "✅"]):
                                        return True, f"نجح التحقق بالزر: {target}"
                            except Exception:
                                continue

            # ── الحالة 2: كتابة رقم أو جواب نصي ──
            elif action in {"كتابة", "write", "text"} and target:
                try:
                    await client.send_message(bot_entity, target)
                    await asyncio.sleep(2)
                    new_msgs = await client.get_messages(bot_entity, limit=5)
                    for nm in new_msgs:
                        if any(k in nm.text for k in ["أهلاً", "مرحباً", "تم", "success", "✅"]):
                            return True, f"نجح التحقق بالكتابة: {target}"
                except Exception:
                    continue

            # ── الحالة 3: مشاركة جهة اتصال ──
            elif action == "جهة اتصال" or "شارك" in str(analysis):
                try:
                    from telethon.tl.types import InputMediaContact
                    me = await client.get_me()
                    first = getattr(me, "first_name", "") or ""
                    last = getattr(me, "last_name", "") or ""
                    ph = getattr(me, "phone", "") or phone.lstrip("+")
                    if not ph.startswith("+"):
                        ph = "+" + ph
                    await client.send_file(
                        bot_entity,
                        InputMediaContact(phone_number=ph, first_name=first, last_name=last, vcard=""),
                    )
                    await asyncio.sleep(2)
                    new_msgs = await client.get_messages(bot_entity, limit=5)
                    for nm in new_msgs:
                        if any(k in nm.text for k in ["أهلاً", "مرحباً", "تم", "success", "✅"]):
                            return True, "نجح التحقق بمشاركة جهة الاتصال"
                except Exception:
                    continue
                
    return False, "لم يتم حل الكابتشا بعد المحاولات"


# ═══════════════════════════════════════════════════════════
# دوال مساعدة لتسلسل الإحالة الإجبارية
# ═══════════════════════════════════════════════════════════

async def _join_channels_from_buttons(client, msgs: list) -> int:
    """
    يفحص أزرار رسائل البوت ويجمع روابط القنوات (t.me) وينضم إليها.
    يُرجع عدد القنوات التي انضم إليها بنجاح.
    """
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.tl.functions.messages import ImportChatInviteRequest
    joined = 0
    for msg in msgs:
        if not msg.buttons:
            continue
        for row in msg.buttons:
            for btn in row:
                url = getattr(btn, "url", None) or ""
                if "t.me/" not in url and "telegram.me/" not in url:
                    continue
                last_seg = url.rstrip("/").split("/")[-1].split("?")[0]
                # تجاهل روابط ليست قنوات (share، start، إلخ)
                if not last_seg or last_seg.lower().startswith(("share", "start")):
                    continue
                try:
                    if "/+" in url or "joinchat/" in url:
                        invite_part = url.split("/+")[-1] if "/+" in url else url.split("joinchat/")[-1]
                        invite_part = invite_part.split("?")[0].strip()
                        if invite_part:
                            await client(ImportChatInviteRequest(invite_part))
                            joined += 1
                    else:
                        ch_entity = await client.get_entity(last_seg)
                        await client(JoinChannelRequest(ch_entity))
                        joined += 1
                    await asyncio.sleep(1.5)
                except Exception as _e:
                    logger.debug(f"_join_channels_from_buttons: {last_seg} — {_e}")
    return joined


async def _click_check_subscription_button(client, bot_entity, msgs: list) -> bool:
    """
    بعد الانضمام لقنوات البوت، يبحث عن زر "تحقق من الاشتراك" ويضغطه.
    يُرجع True إذا وُجد الزر وتم ضغطه.
    """
    CHECK_KW = [
        "تحقق", "اشتركت", "✅", "تم", "joined", "check", "verify",
        "تم الاشتراك", "لقد اشتركت", "متابع", "اشتراك", "انضممت",
        "i've joined", "i joined", "subscribed",
    ]
    for msg in msgs:
        if not msg.buttons:
            continue
        for row in msg.buttons:
            for btn in row:
                btn_text = (getattr(btn, "text", "") or "").lower()
                if any(k in btn_text for k in CHECK_KW):
                    try:
                        await btn.click()
                        logger.info(f"✅ ضغط زر التحقق من الاشتراك: '{btn.text}'")
                        return True
                    except Exception as _e:
                        logger.debug(f"_click_check_subscription_button: {_e}")
    return False


async def do_referral_for_number(phone: str, session_str: str, bot_username: str, start_param: str,
                                  mandatory_channels: str = "", folder_link: str = "",
                                  use_ai: bool = False, leave_channels_after: bool = False,
                                  stock_id: int = 0) -> tuple:
    """
    تسلسل الإحالة الإجبارية الصحيح:
      1. ينضم للقنوات الإجبارية المحددة مسبقاً (قنوات بوتنا الإجبارية)
      2. ينضم للمجلد إن وُجد
      3. يضغط رابط الدعوة (StartBotRequest مع start_param)
      4. يتجاوز قنوات البوت المستهدف لأن القنوات الإجبارية انضم إليها الحساب مسبقاً
      5. إذا كان النوع "بتحقق" (use_ai=True) → يحل التحقق بالذكاء الاصطناعي
         إذا كان "بدون تحقق" (use_ai=False) → يتجاوز أي تحقق ويُسجَّل كنجاح

    يُرجع (success: bool, reactivated: bool, detail: str).
    — success=True,  reactivated=False → نجاح حقيقي (أول تفعيل)
    — success=True,  reactivated=True  → البوت كان مفعّلاً مسبقاً (لا تعويض)
    — success=False, reactivated=False → فشل حقيقي (تُستردّ نقاطه تلقائياً)
    """
    # ════════════════════════════════════════════════════════════
    # 🔥 DEBUG: تأكد من وصول use_ai
    # ════════════════════════════════════════════════════════════
    logger.info(f"🚀 do_referral_for_number: {phone} → @{bot_username} | use_ai={use_ai} | start_param={start_param}")
    # ════════════════════════════════════════════════════════════

    # ── تخطي فوري: إذا كان البوت المستهدف هو البوت نفسه (ارشقلي) ──
    _clean_target = bot_username.lower().lstrip("@").strip()
    if _OWN_BOT_USERNAME and _clean_target == _OWN_BOT_USERNAME:
        return True, True, "البوت المستهدف هو البوت نفسه — تم التخطي تلقائياً (مكتمل)"

    # أخطاء تدل على انتهاء صلاحية الجلسة نهائياً — تستدعي تحديث DB
    _DEAD_SESSION_ERRORS = (
        "AuthKeyUnregistered", "SessionRevoked", "SessionExpired",
        "UserDeactivated", "AccountBanned", "PhoneNumberBanned",
        "AuthKeyDuplicated",
    )

    def _mark_session_dead(auto_delete: bool = False, reason: str = ""):
        """يضبط can_send_code=FALSE و last_authorized=FALSE و force_listed=FALSE.
        إذا auto_delete=True وstock_id مُعطى → يحذف الرقم فوراً من المخزون."""
        try:
            with db_conn() as _dc:
                _dc.execute(
                    "UPDATE number_stock SET can_send_code=FALSE, last_authorized=FALSE, force_listed=FALSE "
                    "WHERE phone_number=%s AND ever_sold IS NOT TRUE",
                    (phone,)
                )
            logger.info(f"🔴 جلسة {phone} مُعلَّمة كمنتهية في DB (force_listed أُزيل تلقائياً)")
        except Exception as _de:
            logger.debug(f"_mark_session_dead {phone}: {_de}")
        if auto_delete and stock_id:
            _auto_delete_number(stock_id, phone, reason or "حساب محذوف أو مجمّد")

    if not is_telegram_api_configured():
        return False, False, "TELEGRAM_API_ID/HASH غير مضبوط"

    client = TelegramClient(
        StringSession(session_str),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            _mark_session_dead(auto_delete=True, reason="حساب محذوف أو جلسة مُلغاة — حُذف تلقائياً")
            return False, False, "جلسة منتهية أو مُلغاة — حُذف من المخزون"

        steps = []

        # ── الخطوة 1: الانضمام للقنوات الإجبارية المحددة مسبقاً ──
        if mandatory_channels and mandatory_channels.strip():
            cnt = await _join_mandatory_channels(client, mandatory_channels)
            if cnt:
                steps.append(f"انضم لـ {cnt} قناة إجبارية")

        # ── الخطوة 2: الانضمام للمجلد (إن وُجد) ──
        if folder_link and folder_link.strip():
            folder_result = await _join_folder_link(client, folder_link)
            steps.append(folder_result)
            await asyncio.sleep(1)

        # نستخدم ResolveUsernameRequest مباشرةً بدل get_entity لتجنّب
        # ValueError "No user has X as username" عند الأرقام التي لم تتحدث
        # مع البوت المستهدف من قبل (الكاش المحلي فارغ).
        _clean_uname = bot_username.lstrip("@").strip()
        try:
            _resolved = await asyncio.wait_for(
                client(ResolveUsernameRequest(_clean_uname)), timeout=15
            )
            bot_entity = _resolved.users[0] if _resolved.users else _resolved.chats[0]
        except (IndexError, Exception) as _re:
            raise ValueError(f"تعذّر إيجاد البوت @{_clean_uname}: {_re}")

        # ── كشف إعادة التفعيل: هل البوت مفعّل مسبقاً؟ ──
        _was_reactivated = False
        try:
            _prev_msgs = await asyncio.wait_for(client.get_messages(bot_entity, limit=1), timeout=10)
            if _prev_msgs and len(_prev_msgs) > 0:
                _was_reactivated = True
        except Exception:
            pass

        # ── الخطوة 3: ضغط رابط الدعوة ──
        await asyncio.wait_for(
            client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param or '',
            )),
            timeout=20,
        )
        # بعض البوتات ترسل رسالة الترحيب أولاً ثم ترسل التحقق بعد عدة ثوانٍ.
        # جلب عدد أكبر من الرسائل هنا مهم لأن رسالة التحقق قد لا تكون الأخيرة.
        await asyncio.sleep(5)
        msgs = await asyncio.wait_for(client.get_messages(bot_entity, limit=15), timeout=10)

        # ── الخطوة 4: تجاوز اشتراك البوت المستهدف ──
        # القنوات المطلوبة تُرسل مسبقاً عبر زر القنوات الإجبارية في نظامنا،
        # لذلك لا ننضم إلى أي قناة من أزرار البوت المستهدف ولا نضغط زر اشتراكه.
        # ننتقل مباشرة إلى رسائل التحقق التي أرسلها البوت بعد /start.

        # ── الخطوة 5: حل التحقق (كابتشا) ──
        # "بتحقق" (use_ai=True)  → يحاول حل أي تحقق يطلبه البوت بالذكاء الاصطناعي
        # "بدون تحقق" (use_ai=False) → يتجاوز التحقق تماماً ويُسجَّل كنجاح
        if use_ai:
            if not is_ai_available():
                return False, False, "لا يوجد مفتاح AI (Groq أو DeepSeek) — لا يمكن حل التحقق"

            _ai_solved = False
            _ai_detail = "لم يتم حل الكابتشا"

            # لا تعتمد على قائمة الرسائل القديمة التي وصلت بعد /start أو بعد
            # الاشتراك بالقنوات. بعض البوتات تحتاج وقتاً إضافياً قبل إرسال
            # التحقق، لذلك نعيد الجلب قبل كل محاولة.
            for _ai_attempt in range(3):
                if _ai_attempt > 0:
                    await asyncio.sleep(4)
                msgs = await asyncio.wait_for(
                    client.get_messages(bot_entity, limit=15), timeout=10
                )
                logger.info(
                    f"🤖 محاولة حل الكابتشا للرقم {phone} "
                    f"(المحاولة {_ai_attempt + 1}/3)"
                )
                _ai_solved, _ai_detail = await solve_captcha_with_ai(
                    client, bot_entity, msgs, phone, max_attempts=3
                )
                if _ai_solved:
                    logger.info(
                        f"✅ تم حل الكابتشا للرقم {phone} "
                        f"في المحاولة {_ai_attempt + 1}"
                    )
                    break
                logger.warning(
                    f"⚠️ لم تُحل كابتشا {phone} في المحاولة "
                    f"{_ai_attempt + 1}/3: {_ai_detail}"
                )

            if _ai_solved:
                steps.append(f"🤖 AI: {_ai_detail}")
            elif _ai_detail != "لم يُكتشف تحقق":
                # فشل حقيقي مثل غياب مفاتيح AI أو تعذر الإجابة؛ لا نسجل
                # الحساب ناجحاً قبل اجتياز التحقق المطلوب.
                return False, False, f"فشل حل الكابتشا بعد 3 محاولات: {_ai_detail}"
            else:
                # عدم وجود تحدٍ ليس فشلاً: بعض البوتات لا تعرض تحققاً لكل
                # إحالة، لكننا تأكدنا من أحدث الرسائل عدة مرات قبل المتابعة.
                logger.info(f"ℹ️ لم يطلب البوت تحققاً للرقم {phone}")

        # سجّل أول رسالة وصلت من البوت للتشخيص
        if msgs:
            _last_txt = getattr(msgs[0], 'text', '') or ''
            if _last_txt:
                logger.info(f"📨 ردّ البوت ({phone}→@{bot_username}): {_last_txt[:120]}")

        # ── مغادرة القنوات الإجبارية بعد اكتمال العملية (إن طُلب ذلك) ──
        if leave_channels_after and mandatory_channels and mandatory_channels.strip():
            try:
                left_count = await _leave_mandatory_channels(client, mandatory_channels)
                if left_count:
                    steps.append(f"غادر {left_count} قناة إجبارية")
            except Exception as _le:
                logger.warning(f"⚠️ تعذّر مغادرة القنوات لـ {phone}: {_le}")

        if _was_reactivated:
            detail = "إعادة تفعيل (البوت كان مفعّلاً مسبقاً)" + (f" | {' | '.join(steps)}" if steps else "")
            return True, True, detail

        detail = "تمت الإحالة بنجاح" + (f" | {' | '.join(steps)}" if steps else "")
        return True, False, detail

    except PeerFloodError:
        # PeerFlood = تيليجرام يكتشف ضغطاً متكرراً على نفس البوت من حسابات كثيرة
        # هذا الحساب يُعدّ فاشلاً لكنه لا يزال صالحاً — لا نمسح can_send_code
        logger.warning(f"⚠️ PeerFlood {phone}→@{bot_username}: الحساب مقيّد مؤقتاً من تيليجرام")
        return False, False, "PeerFlood — مقيّد مؤقتاً (حاول لاحقاً)"

    except FloodWaitError as fw:
        # FloodWait = تيليجرام يطلب الانتظار X ثانية
        wait_sec = fw.seconds + 2
        logger.warning(f"⏳ FloodWait {phone}: انتظار {wait_sec}ث...")
        try:
            await asyncio.sleep(min(wait_sec, 90))
            # إعادة محاولة واحدة بعد انتهاء FloodWait
            async with TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH) as _retry_cli:
                if not await asyncio.wait_for(_retry_cli.is_user_authorized(), timeout=10):
                    return False, False, "جلسة منتهية (بعد FloodWait)"
                _clean_uname2 = bot_username.lstrip("@").strip()
                _resolved2 = await asyncio.wait_for(
                    _retry_cli(ResolveUsernameRequest(_clean_uname2)), timeout=15
                )
                _bot_e = _resolved2.users[0] if _resolved2.users else _resolved2.chats[0]
                await asyncio.wait_for(
                    _retry_cli(StartBotRequest(bot=_bot_e, peer=_bot_e, start_param=start_param or '')),
                    timeout=20,
                )
                await asyncio.sleep(3)
                return True, False, f"نجح بعد FloodWait {fw.seconds}ث"
        except Exception as _fw_e:
            logger.error(f"❌ فشل بعد FloodWait {phone}: {_fw_e}")
            return False, False, f"FloodWait {fw.seconds}ث ثم فشل: {str(_fw_e)[:80]}"

    except (UserBannedInChannelError, ChatWriteForbiddenError, UserPrivacyRestrictedError) as _restrict_e:
        # قيود خاصة بهذا الحساب — لا تُعطّل can_send_code لأن الحساب صالح للعمليات الأخرى
        logger.warning(f"⚠️ قيد خاص {phone}: {type(_restrict_e).__name__}")
        return False, False, f"قيد حساب: {type(_restrict_e).__name__}"

    except Exception as e:
        err = str(e)
        err_type = type(e).__name__
        # جلسة منتهية نهائياً أو حساب محذوف → حدّث DB وأحذفه من المخزون فوراً
        if any(k in err_type for k in _DEAD_SESSION_ERRORS):
            _mark_session_dead(auto_delete=True, reason=f"حساب محذوف/مجمّد ({err_type}) — حُذف تلقائياً")
        logger.error(f"❌ فشلت إحالة {phone} → {bot_username} [{err_type}]: {err[:100]}")
        return False, False, f"[{err_type}] {err[:100]}"
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════

async def _mansub_start(update, context, user, q, is_own):
    avail = get_referral_session_count()
    bp = int(get_setting('mansub_base_price') or '250')
    cp = int(get_setting('mansub_channel_price') or '50')
    vis = get_setting('mansub_visible') == '1'
    tgl = '🔒 إخفاء من الأعضاء' if vis else '🔓 إظهار للأعضاء'
    visnote = '👁 مرئية للأعضاء' if vis else '🔒 مخفية (مالك فقط)'
    context.user_data['state'] = 'await_mansub_link'
    context.user_data['mansub_draft'] = {}
    own_row = [[InlineKeyboardButton(tgl, callback_data='os:toggle_mansub_visible')]] if user.id == OWNER_ID else []
    await q.edit_message_text(
        f'🔑 *الاشتراك الإجباري*\n\n'
        f'📊 الحسابات المتاحة: *{avail}*\n'
        f'💰 {bp} نقطة/حساب + {cp} نقطة/قناة\n'
        f'📌 {visnote}\n\n'
        f'📎 *خطوة 1/3* — أرسل رابط إحالة بوتك:\n'
        f'`t.me/BotUsername?start=CODE`\n'
        f'أو: `@BotUsername CODE`',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(own_row + [
            [InlineKeyboardButton('🔙 رجوع', callback_data='cat:start_bot')]
        ])
    )

async def _mansub_handle_link(update, context):
    raw = update.message.text.strip()
    bot_user = start_p = ''
    try:
        if 't.me/' in raw or 'telegram.me/' in raw:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(raw if raw.startswith('http') else 'https://' + raw)
            bot_user = parsed.path.strip('/')
            start_p = parse_qs(parsed.query).get('start', [''])[0]
        else:
            parts = raw.split(None, 1)
            bot_user = parts[0].lstrip('@')
            start_p = parts[1] if len(parts) > 1 else ''
        # الكود اختياري — المهم أن يكون اسم البوت موجوداً
        if not bot_user:
            raise ValueError('اسم البوت فارغ')
        draft = context.user_data.setdefault('mansub_draft', {})
        draft['bot_user'] = bot_user
        draft['start_p'] = start_p
        context.user_data['state'] = 'await_mansub_channels'
        code_info = f'`{start_p}`' if start_p else 'بدون كود'
        bot_display = '`@' + bot_user + '`'
        await update.message.reply_text(
            f'✅ البوت: {bot_display} | {code_info}\n\n'
            f'📢 *خطوة 2/3 — القنوات الإجبارية:*\n'
            f'أرسل يوزرات القنوات مفصولة بمسافة.\n'
            f'مثال: `@chan1 @chan2`\n\n'
            f'أو اضغط تخطي إذا لا توجد قنوات.',
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('⏭️ تخطي (بدون قنوات)', callback_data='mansub_skip_channels')],
                [InlineKeyboardButton('🔙 إلغاء', callback_data='cat:start_bot')]
            ])
        )
    except Exception as _pe:
        import logging as _lg
        _lg.getLogger(__name__).warning(f'mansub_handle_link error: {_pe}')
        await update.message.reply_text(
            f'⚠️ تعذّر قراءة الرابط.\nأرسل اسم البوت هكذا:\n`@BotUsername` أو `t.me/BotUsername`',
            parse_mode=ParseMode.MARKDOWN
        )

async def _mansub_handle_channels(update, context):
    raw = update.message.text.strip()
    draft = context.user_data.setdefault('mansub_draft', {})
    draft['channels'] = '' if raw.lower() in ('تخطي', 'skip', '-') else raw
    context.user_data['state'] = 'await_mansub_qty'
    avail = get_referral_session_count()
    ch_count = len([t for t in raw.split() if t.strip()]) if draft['channels'] else 0
    bp = int(get_setting('mansub_base_price') or '250')
    cp = int(get_setting('mansub_channel_price') or '50')
    cost_each = bp + ch_count * cp
    await update.message.reply_text(
        f'✅ القنوات: `{draft["channels"] or "لا يوجد"}`\n\n'
        f'📊 المتاح: *{avail}* حساب\n'
        f'💰 سعر/حساب: *{cost_each}* نقطة\n\n'
        f'🔢 *خطوة 3/3* — أرسل عدد الحسابات (1 – {avail}):',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 إلغاء', callback_data='cat:start_bot')]])
    )

async def _mansub_handle_qty(update, context, user):
    try:
        qty = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text('⚠️ أرسل رقماً صحيحاً.')
        return
    avail = get_referral_session_count()
    if qty < 1 or qty > avail:
        await update.message.reply_text(f'⚠️ الكمية خارج النطاق (1 – {avail}).')
        return
    draft = context.user_data.setdefault('mansub_draft', {})
    channels = draft.get('channels', '')
    ch_count = len([t for t in channels.split() if t.strip()]) if channels else 0
    bp = int(get_setting('mansub_base_price') or '250')
    cp = int(get_setting('mansub_channel_price') or '50')
    cost_each = bp + ch_count * cp
    total = cost_each * qty
    draft['qty'] = qty
    draft['cost'] = total
    db_user = get_user(user.id)
    pts = db_user['points'] if db_user else 0
    context.user_data['state'] = 'confirm_mansub'
    ch_line = f'\n📢 القنوات: `{channels}`' if channels else ''
    _bu_m = draft.get('bot_user', '')
    _sp_m = draft.get('start_p', '')
    _code_m = f'`{_sp_m}`' if _sp_m else 'بدون كود'
    await update.message.reply_text(
        f'📋 *تأكيد الاشتراك الإجباري:*\n\n'
        f'📌 `@{_bu_m}` | كود: {_code_m}{ch_line}\n'
        f'🔢 {qty} حساب × {cost_each} نقطة = *{total}* نقطة\n'
        f'💎 رصيدك: {pts} نقطة\n\n'
        f'⚡ الحسابات تعمل بترتيب عشوائي\n'
        f'💡 الفاشلة: تُستردّ نقاطها تلقائياً | إعادة التفعيل: لا تعويض',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('✅ تأكيد', callback_data='confirm_mansub:yes'),
             InlineKeyboardButton('❌ إلغاء', callback_data='confirm_mansub:no')]
        ])
    )

async def _handle_confirm_mansub(update, context, user, q, is_own, data):
    action = data.split(':')[1]
    if context.user_data.get('state') != 'confirm_mansub':
        await q.edit_message_text('⚠️ انتهت صلاحية الطلب.', reply_markup=main_menu_kb(is_own))
        return
    draft = context.user_data.get('mansub_draft', {})
    if action == 'no':
        context.user_data['state'] = 'main_menu'
        await q.edit_message_text('❌ تم إلغاء الطلب.', reply_markup=main_menu_kb(is_own))
        return
    bot_user = draft.get('bot_user', '')
    start_p  = draft.get('start_p', '')
    channels = draft.get('channels', '')
    qty      = draft.get('qty', 0)
    total    = draft.get('cost', 0)
    if not bot_user or qty < 1:
        context.user_data['state'] = 'main_menu'
        await q.edit_message_text('⚠️ بيانات غير مكتملة.', reply_markup=main_menu_kb(is_own))
        return
    _dbu = get_user(user.id)
    if _dbu and _dbu.get('referral_points_blocked'):
        await q.edit_message_text('🔒 حسابك موقوف. تواصل مع المالك.', reply_markup=main_menu_kb(is_own))
        return
    if not deduct_points(user.id, total):
        await q.edit_message_text('❌ نقاطك غير كافية.', reply_markup=main_menu_kb(is_own))
        context.user_data['state'] = 'main_menu'
        return
    code = next_order_code(user.id)
    with db_conn() as c:
        row = c.execute(
            'INSERT INTO mandatory_sub_orders '
            '(user_id,bot_username,start_param,channels,quantity,cost_points,status,order_code) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
            (user.id, bot_user, start_p, channels, qty, total, 'pending', code)
        ).fetchone()
        order_id = row['id']
    context.user_data['state'] = 'main_menu'
    context.user_data.pop('mansub_draft', None)
    _code_ms = f'`{start_p}`' if start_p else 'بدون كود'
    ch_line = f'\n📢 القنوات: `{channels}`' if channels else ''
    await q.edit_message_text(
        f'✅ *تم استلام طلبك!*\n\n'
        f'📌 `@{bot_user}` | كود: {_code_ms}{ch_line}\n'
        f'🔢 {qty} حساب | 💰 {total} نقطة\n'
        f'🎫 كود: `{code}`\n\n'
        f'⏳ سيبدأ التنفيذ قريباً وستصلك إشعار عند الانتهاء.',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb(is_own)
    )
    await _maybe_send_to_group(
        context.bot, user.id,
        f'🔑 *طلب اشتراك إجباري*\n👤 {user.id}\n📌 `@{bot_user}` | `{start_p if start_p else "بدون كود"}`\n🔢 {qty} | 💰 {total}\n🎫 `{code}`',
        parse_mode='Markdown'
    )
    import asyncio as _aio
    _aio.create_task(_run_mansub_order(order_id, bot_user, start_p, channels, qty, user.id, context))

async def _run_mansub_order(order_id, bot_user, start_p, channels, quantity, requester_id, context):
    import random as _rnd
    import time as _time
    with db_conn() as c:
        c.execute("UPDATE mandatory_sub_orders SET status='running' WHERE id=%s", (order_id,))
        rows = c.execute(
            "SELECT id,phone_number,session_string FROM number_stock"
            " WHERE session_string IS NOT NULL AND BTRIM(session_string) <> ''"
            " AND deleted_at IS NULL"
            " ORDER BY id"
        ).fetchall()
    with db_conn() as _cm:
        _order_meta = _cm.execute(
            "SELECT cost_points, quantity FROM mandatory_sub_orders WHERE id=%s", (order_id,)
        ).fetchone()
    _total_cost = int(_order_meta["cost_points"] or 0) if _order_meta else 0
    _qty_total  = int(_order_meta["quantity"] or 1) if _order_meta else max(1, quantity)
    _cost_each  = round(_total_cost / _qty_total) if _qty_total else 0

    nums = [dict(r) for r in rows]
    _rnd.shuffle(nums)
    pool_ms     = list(nums)    # كامل المخزون المتاح بترتيب عشوائي
    pool_ms_idx = quantity      # أول حساب بديل بعد الدفعة الأولى
    done = failed = reactivated = 0
    replaced_ms = 0             # عدد الحسابات البديلة المستخدمة
    refunded_pts = 0

    # ─── رسالة التقدم الحي ───
    _live_msg        = None
    _last_edit_time  = 0.0
    _EDIT_INTERVAL   = 3.0   # ثوانٍ بين كل تحديث للرسالة (تجنّب Rate-Limit)

    def _mansub_progress_text(idx: int) -> str:
        parts = []
        if done > 0:        parts.append(f'{done} ✅ تم')
        if failed > 0:      parts.append(f'{failed} ❌ فشل')
        if reactivated > 0: parts.append(f'{reactivated} 🔄 مكرر')
        if replaced_ms > 0: parts.append(f'{replaced_ms} 🔁 بديل')
        status = '  |  '.join(parts) if parts else '⏳ جاري...'
        return (
            f'⏳ <b>جاري تنفيذ الاشتراك الإجباري...</b>\n'
            f'📌 @{bot_user} | {quantity} حساب\n\n'
            f'<b>حساب {idx}/{quantity}</b> — {status}'
        )

    try:
        _live_msg = await context.bot.send_message(
            requester_id,
            f'⏳ <b>جاري تنفيذ الاشتراك الإجباري...</b>\n📌 @{bot_user} | {quantity} حساب\n\nحساب 0/{quantity} — ⏳ جاري...',
            parse_mode='HTML'
        )
        _last_edit_time = _time.monotonic()
    except Exception:
        pass

    import asyncio as _aio2

    # ── معالجة الحسابات مع دعم الاستبدال التلقائي ──
    # عند فشل أي حساب يُستبدل بآخر من المخزون حتى يكتمل العدد المطلوب
    _ms_pending = pool_ms[:quantity]

    while _ms_pending and done + reactivated < quantity:
        _ms_cycle = list(_ms_pending)
        _ms_pending = []            # ستُملأ بالحسابات البديلة

        for _idx, num in enumerate(_ms_cycle, 1):
            if done + reactivated >= quantity:
                break               # ✅ اكتمل الهدف

            try:
                ok, reactiv, _ = await do_referral_for_number(
                    num['phone_number'], num['session_string'],
                    bot_user, start_p,
                    mandatory_channels=channels or '',
                    folder_link='',
                    leave_channels_after=True,
                    stock_id=num.get('id', 0),
                )
            except Exception as _e:
                ok = False; reactiv = False

            with db_conn() as c:
                if ok and reactiv:
                    c.execute("UPDATE mandatory_sub_orders SET reactivated_count=reactivated_count+1 WHERE id=%s", (order_id,))
                    reactivated += 1
                elif ok:
                    c.execute("UPDATE mandatory_sub_orders SET done_count=done_count+1 WHERE id=%s", (order_id,))
                    done += 1
                else:
                    c.execute("UPDATE mandatory_sub_orders SET failed_count=failed_count+1 WHERE id=%s", (order_id,))
                    failed += 1
                    # ── سحب حساب بديل إذا لم يكتمل الهدف ──
                    if done + reactivated < quantity and pool_ms_idx < len(pool_ms):
                        _ms_pending.append(pool_ms[pool_ms_idx])
                        pool_ms_idx += 1
                        replaced_ms += 1

            # ─── تحديث رسالة التقدم الحي (كل 3 ثوانٍ) ───
            _now = _time.monotonic()
            _ms_total = done + failed + reactivated
            if _live_msg and (_now - _last_edit_time >= _EDIT_INTERVAL or _ms_total == quantity):
                try:
                    await context.bot.edit_message_text(
                        _mansub_progress_text(_ms_total),
                        chat_id=requester_id,
                        message_id=_live_msg.message_id,
                        parse_mode='HTML'
                    )
                    _last_edit_time = _now
                except Exception:
                    pass

            await _aio2.sleep(2)

        # إشعار المستخدم بوجود حسابات بديلة
        if _ms_pending and _live_msg:
            try:
                await context.bot.edit_message_text(
                    _mansub_progress_text(done + failed + reactivated) +
                    f'\n🔁 جاري تجربة {len(_ms_pending)} حساب بديل...',
                    chat_id=requester_id,
                    message_id=_live_msg.message_id,
                    parse_mode='HTML'
                )
            except Exception:
                pass

    # ─── استرداد نقاط الكميات غير المكتملة (التي نفد بديلها من المخزون) ───
    unfulfilled_ms = max(0, quantity - done - reactivated)
    if unfulfilled_ms > 0 and _cost_each > 0:
        refunded_pts = unfulfilled_ms * _cost_each
        add_points(requester_id, refunded_pts)

    with db_conn() as c:
        c.execute("UPDATE mandatory_sub_orders SET status='done' WHERE id=%s", (order_id,))

    _refund_line  = f'\n💰 <b>استرداد تلقائي:</b> {refunded_pts:,} نقطة (عن {unfulfilled_ms} حساب لم يُكتمل)' if refunded_pts > 0 else ''
    _replaced_line = f'\n🔁 <i>استُبدل {replaced_ms} حساب فاشل بحسابات أخرى</i>' if replaced_ms > 0 else ''
    _reactiv_note = f'\n⚠️ <i>الحسابات التي كان البوت مفعّلاً بها مسبقاً لا تستحق تعويضاً</i>' if reactivated > 0 else ''
    _final_text = (
        f'✅ <b>اكتمل طلب الاشتراك الإجباري!</b>\n'
        f'📌 @{bot_user}\n\n'
        f'✅ المنجز: {done}\n'
        f'🔄 المكرر (مفعّل مسبقاً): {reactivated}\n'
        f'❌ الملغي (إجمالي): {failed}'
        f'{_replaced_line}{_refund_line}{_reactiv_note}'
    )
    # تحديث نفس رسالة التقدم بالنتيجة النهائية، أو إرسال رسالة جديدة إن تعذّر التحديث
    if _live_msg:
        try:
            await context.bot.edit_message_text(
                _final_text,
                chat_id=requester_id,
                message_id=_live_msg.message_id,
                parse_mode='HTML'
            )
        except Exception:
            try:
                await context.bot.send_message(requester_id, _final_text, parse_mode='HTML')
            except Exception:
                pass
    else:
        try:
            await context.bot.send_message(requester_id, _final_text, parse_mode='HTML')
        except Exception:
            pass
    await _maybe_send_to_group(
        context.bot, requester_id,
        f'🔑 اشتراك إجباري اكتمل | 👤 {requester_id} | @{bot_user} | ✅{done} ❌{failed} 🔄{reactivated} 🔁{replaced_ms} | استرداد {refunded_pts:,}نقطة',
        parse_mode='Markdown'
    )
    # ─── إشعار المالك بالتفاصيل الكاملة (فاشل/مكمل/مكرر/بديل) مع المصدر ───
    if OWNER_ID and requester_id != OWNER_ID:
        try:
            _src_lbl = '👤 من عضو — بوت اجباري'
            await context.bot.send_message(
                OWNER_ID,
                f'📊 <b>تقرير الاشتراك الإجباري</b>\n'
                f'📌 {_src_lbl}\n'
                f'🆔 طلب المستخدم: <code>{requester_id}</code> | @{bot_user}\n\n'
                f'✅ <b>المنجز:</b> {done}\n'
                f'🔄 <b>المكرر (مفعّل مسبقاً):</b> {reactivated}\n'
                f'❌ <b>الملغي (إجمالي):</b> {failed}\n'
                f'🔁 <b>الحسابات البديلة المستخدمة:</b> {replaced_ms}'
                + (f'\n💰 استرداد تلقائي: {refunded_pts:,} نقطة' if refunded_pts > 0 else ''),
                parse_mode='HTML'
            )
        except Exception:
            pass

# ══════════════════════════════════════════════════════════
# إحالة بوت اجباري — الدوال الكاملة
# ══════════════════════════════════════════════════════════

async def _forced_ref_start(update, context, user, q, is_own, with_ai: bool = False):
    """الشاشة الأولى — يختار المستخدم طريقة الدفع (نجوم أو نقاط)."""
    if with_ai:
        vis     = get_setting('forced_ref_ai_visible') == '1'
        tgl     = '🔒 إخفاء من الأعضاء' if vis else '🔓 إظهار للأعضاء'
        visnote = '👁 مرئية للأعضاء' if vis else '🔒 مخفية (مالك فقط)'
        title   = '🤖 إحالة بميزة تحقق'
        tgl_cb  = 'os:toggle_forced_ref_ai_visible'
        ai_flag = '1'
    else:
        vis     = get_setting('forced_ref_visible') == '1'
        tgl     = '🔒 إخفاء من الأعضاء' if vis else '🔓 إظهار للأعضاء'
        visnote = '👁 مرئية للأعضاء' if vis else '🔒 مخفية (مالك فقط)'
        title   = '🔑 إحالة بوت فقط'
        tgl_cb  = 'os:toggle_forced_ref_visible'
        ai_flag = '0'
    context.user_data['forced_ref_draft'] = {'use_ai': with_ai, 'payment_method': None}
    own_row = [[InlineKeyboardButton(tgl, callback_data=tgl_cb)]] if user.id == OWNER_ID else []
    await q.edit_message_text(
        f'*{title}*\n\n'
        f'📌 {visnote}\n\n'
        f'اختر طريقة الدفع:',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(own_row + [
            [InlineKeyboardButton('⭐ بنجوم', callback_data=f'forced_ref_pm:stars:{ai_flag}')],
            [InlineKeyboardButton('💎 بنقاط', callback_data=f'forced_ref_pm:points:{ai_flag}')],
            [InlineKeyboardButton('🔙 رجوع', callback_data='main_menu')],
        ])
    )

async def _forced_ref_go_channels(q_or_msg, context, draft, *, edit: bool):
    """بعد اختيار طريقة الدفع — يعرض تفاصيل السعر والعدد الأعلى، ثم يطلب القنوات."""
    use_ai  = draft.get('use_ai', False)
    pm      = draft.get('payment_method', 'points')
    avail   = get_forced_ref_account_count()

    if pm == 'stars':
        cp_ch        = int(get_setting('forced_ref_channel_stars_ai' if use_ai else 'forced_ref_channel_stars_no_ai') or ('35' if use_ai else '25'))
        max_qty      = (avail // 2) * 2 if use_ai else avail  # زوجي فقط عند AI
        stars_label  = '1.5 نجمة/حساب' if use_ai else '1 نجمة/حساب'
        even_note    = '\n⚠️ يُقبل فقط أعداد زوجية (٢ ، ٤ ، ٦ ...)' if use_ai else ''
        price_block  = (
            f'┌─────────────────────\n'
            f'│ ⭐ *سعر الإحالة الوحدة:* {stars_label}\n'
            f'│ 💎 *أسعار القناة الإجبارية المضافة:* {cp_ch} نقطة لكل قناة\n'
            f'│ 📊 *الحد الأعلى:* {max_qty} حساب{even_note}\n'
            f'└─────────────────────'
        )
    else:
        bp      = int(get_setting('forced_ref_ai_base_price' if use_ai else 'forced_ref_base_price') or ('300' if use_ai else '250'))
        cp      = int(get_setting('forced_ref_channel_price') or '25')
        max_qty = avail
        price_block = (
            f'┌─────────────────────\n'
            f'│ 💎 *سعر الإحالة الوحدة:* {bp} نقطة\n'
            f'│ 💎 *أسعار القناة الإجبارية المضافة:* {cp} نقطة لكل قناة\n'
            f'│ 📊 *الحد الأعلى:* {max_qty} حساب\n'
            f'└─────────────────────'
        )

    txt = (
        f'{price_block}\n\n'
        f'📢 *أرسل معرفات القنوات الإجبارية:*\n'
        f'مثال: `@chan1 @chan2`\n\n'
        f'أو اضغط تخطي إن لم توجد قنوات.'
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('⏭️ تخطي (بدون قنوات)', callback_data='forced_ref_skip_channels')],
        [InlineKeyboardButton('🔙 إلغاء', callback_data='main_menu')],
    ])
    if edit:
        await q_or_msg.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    else:
        await q_or_msg.reply_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

async def _forced_ref_handle_channels(update, context):
    raw   = update.message.text.strip()
    draft = context.user_data.setdefault('forced_ref_draft', {})
    draft['channels'] = '' if raw.lower() in ('تخطي', 'skip', '-') else raw
    context.user_data['state'] = 'await_forced_ref_link'
    chs_preview = draft['channels'] or 'لا يوجد'
    await update.message.reply_text(
        f'✅ القنوات: `{chs_preview}`\n\n'
        f'📎 *أرسل رابط البوت:*\n'
        f'`t.me/BotUsername?start=CODE`\n'
        f'أو: `@BotUsername CODE`',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 إلغاء', callback_data='main_menu')]])
    )

async def _forced_ref_handle_link(update, context):
    raw = update.message.text.strip()
    try:
        if 't.me/' in raw or 'telegram.me/' in raw:
            from urllib.parse import urlparse, parse_qs
            parsed  = urlparse(raw if raw.startswith('http') else 'https://' + raw)
            bot_user = parsed.path.strip('/')
            start_p  = parse_qs(parsed.query).get('start', [''])[0]
        else:
            parts    = raw.split(None, 1)
            bot_user = parts[0].lstrip('@')
            start_p  = parts[1] if len(parts) > 1 else ''
        if not bot_user:
            raise ValueError('اسم البوت فارغ')
        draft = context.user_data.setdefault('forced_ref_draft', {})
        draft['bot_user'] = bot_user
        draft['start_p']  = start_p
        context.user_data['state'] = 'await_forced_ref_qty'
        avail = get_forced_ref_account_count()
        _draft_link = context.user_data.get('forced_ref_draft', {})
        _use_ai_link = _draft_link.get('use_ai', False)
        _pm_link     = _draft_link.get('payment_method', 'points')
        _even_note   = '\n⚠️ *يُقبل فقط أعداد زوجية* (بسبب سعر 1.5 نجمة/حساب)' if (_use_ai_link and _pm_link == 'stars') else ''
        _max_note    = avail if not (_use_ai_link and _pm_link == 'stars') else (avail // 2) * 2
        await update.message.reply_text(
            f'✅ البوت: `@{bot_user}`\n\n'
            f'📊 المتاح: *{avail}* حساب\n\n'
            f'🔢 *أرسل عدد الحسابات (1 – {_max_note}):*{_even_note}',
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 إلغاء', callback_data='main_menu')]])
        )
    except Exception as _e:
        import logging as _lg
        _lg.getLogger(__name__).warning(f'forced_ref_handle_link error: {_e}')
        await update.message.reply_text(
            '⚠️ تعذّر قراءة الرابط. أرسل اسم البوت هكذا:\n`@BotUsername` أو `t.me/BotUsername`',
            parse_mode=ParseMode.MARKDOWN
        )

async def _show_forced_ref_confirmation(update, context, user):
    draft = context.user_data.setdefault('forced_ref_draft', {})
    qty = draft.get('qty', 0)
    use_ai = draft.get('use_ai', False)
    pm = draft.get('payment_method', 'points')
    total_pts = draft.get('cost', 0)
    total_stars = draft.get('cost_stars', 0)
    cost_pts_channels = draft.get('cost_pts_channels', 0)
    channels = draft.get('channels', '')
    ch_count = len([t for t in channels.split() if t.strip()]) if channels else 0
    db_user = get_user(user.id)
    pts = db_user['points'] if db_user else 0
    context.user_data['state'] = 'confirm_forced_ref'
    _bu_f = draft.get('bot_user', '')
    _sp_f = draft.get('start_p', '')
    _code_f = f'`{_sp_f}`' if _sp_f else 'بدون كود'
    ch_line = f'\n📢 القنوات: `{channels}`' if channels else ''
    _title_conf = '🤖 تأكيد إحالة بميزة تحقق:' if use_ai else '🔑 تأكيد إحالة بوت فقط:'
    if pm == 'stars':
        if ch_count > 0:
            cost_line = (f'⭐ التكلفة: *{total_stars:,} نجمة* (للحسابات)\n'
                         f'💎 نقاط القنوات: *{cost_pts_channels:,} نقطة* تُخصم من رصيدك (رصيدك: {pts:,})')
            lbl_confirm = f'✅ تأكيد ({total_stars:,}⭐ + {cost_pts_channels:,}💎)'
        else:
            cost_line = f'⭐ التكلفة الإجمالية: *{total_stars:,} نجمة*'
            lbl_confirm = f'✅ تأكيد ({total_stars:,} نجمة)'
        btn_confirm = InlineKeyboardButton(lbl_confirm, callback_data='confirm_forced_ref:stars')
    else:
        cost_line = f'💎 التكلفة الإجمالية: *{total_pts:,} نقطة* (رصيدك: {pts:,})'
        btn_confirm = InlineKeyboardButton(f'✅ تأكيد ({total_pts:,} نقطة)', callback_data='confirm_forced_ref:yes')
    await update.message.reply_text(
        f'📋 *{_title_conf}*\n\n'
        f'📌 `@{_bu_f}` | كود: {_code_f}{ch_line}\n'
        f'🔢 {qty} حساب\n'
        f'{cost_line}\n\n'
        f'⚡ الحسابات المستخدمة: كل رقم لديه جلسة محفوظة لدى البوت، مباعاً كان أو غير مباع\n'
        f'💡 الفاشلة: تُعوَّض دائماً | المكررة: تُعوَّض بالنجوم فقط',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [btn_confirm],
            [InlineKeyboardButton('❌ إلغاء', callback_data='confirm_forced_ref:no')],
        ])
    )


async def _forced_ref_handle_qty(update, context, user):
    try:
        qty = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text('⚠️ أرسل رقماً صحيحاً.')
        return
    avail = get_forced_ref_account_count()
    draft    = context.user_data.setdefault('forced_ref_draft', {})
    use_ai   = draft.get('use_ai', False)
    pm       = draft.get('payment_method', 'points')
    # بتحقق + نجوم: يُقبل فقط أعداد زوجية (لأن السعر 1.5 نجمة/حساب)
    if use_ai and pm == 'stars' and qty % 2 != 0:
        await update.message.reply_text(
            '⚠️ في وضع *التحقق بالنجوم* يُقبل فقط *أعداد زوجية* (٢، ٤، ٦...)\n'
            'السبب: سعر الحساب ١.٥ نجمة ولا يمكن كسر النجمة في تيليغرام.',
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if qty < 1 or qty > avail:
        await update.message.reply_text(f'⚠️ الكمية خارج النطاق (1 – {avail}).')
        return
    channels = draft.get('channels', '')
    ch_count = len([t for t in channels.split() if t.strip()]) if channels else 0
    bp  = int(get_setting('forced_ref_ai_base_price' if use_ai else 'forced_ref_base_price') or ('300' if use_ai else '250'))
    cp  = int(get_setting('forced_ref_channel_price') or '25')
    # القنوات دائماً بالنقاط بغض النظر عن طريقة الدفع
    cp_ch_key = 'forced_ref_channel_stars_ai' if use_ai else 'forced_ref_channel_stars_no_ai'
    cp_ch = int(get_setting(cp_ch_key) or ('35' if use_ai else '25'))  # نقاط/قناة
    cost_pts_channels = ch_count * cp_ch   # تكلفة القنوات بالنقاط دائماً
    cost_pts_each = bp + ch_count * cp     # للدفع بالنقاط: حساب + قنوات
    # النجوم للحسابات فقط — القنوات تُخصم من النقاط
    if use_ai:
        # 1.5 نجمة/حساب → لكل حسابين = 3 نجوم (أعداد زوجية مضمونة)
        total_stars = qty * 3 // 2
    else:
        total_stars = qty  # 1 نجمة/حساب
    total_pts = cost_pts_each * qty
    draft['qty']              = qty
    draft['cost']             = total_pts
    draft['cost_stars']       = total_stars
    draft['cost_pts_channels'] = cost_pts_channels  # نقاط القنوات عند الدفع بالنجوم
    if user.id == OWNER_ID:
        context.user_data['state'] = 'await_forced_ref_delay'
        await update.message.reply_text(
            '⏱️ *أرسل الفاصل الزمني بين الحسابات لهذا الطلب فقط بالثواني:*\n\n'
            'مثال: `1`\n'
            'أرسل `0` للتنفيذ بدون انتظار.',
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('🔙 إلغاء', callback_data='main_menu')]
            ])
        )
        return
    await _show_forced_ref_confirmation(update, context, user)


async def _forced_ref_handle_delay(update, context, user):
    if user.id != OWNER_ID:
        context.user_data['state'] = 'main_menu'
        await update.message.reply_text('⚠️ هذه الخطوة متاحة للمالك فقط.')
        return
    try:
        delay_seconds = float(update.message.text.strip().replace(',', '.'))
        if not math.isfinite(delay_seconds) or delay_seconds < 0:
            raise ValueError
    except (TypeError, ValueError):
        await update.message.reply_text(
            '⚠️ أرسل رقماً موجباً أو صفراً، مثل `1` أو `0.5` أو `0`.',
            parse_mode=ParseMode.MARKDOWN
        )
        return
    draft = context.user_data.setdefault('forced_ref_draft', {})
    draft['delay_seconds'] = delay_seconds
    await _show_forced_ref_confirmation(update, context, user)

async def _handle_confirm_forced_ref(update, context, user, q, is_own, data):
    action = data.split(':')[1]
    if context.user_data.get('state') != 'confirm_forced_ref':
        await q.edit_message_text('⚠️ انتهت صلاحية الطلب.', reply_markup=main_menu_kb(is_own))
        return
    draft = context.user_data.get('forced_ref_draft', {})
    if action == 'no':
        context.user_data['state'] = 'main_menu'
        await q.edit_message_text('❌ تم إلغاء الطلب.', reply_markup=main_menu_kb(is_own))
        return
    bot_user    = draft.get('bot_user', '')
    start_p     = draft.get('start_p', '')
    channels    = draft.get('channels', '')
    qty         = draft.get('qty', 0)
    total       = draft.get('cost', 0)
    total_stars = draft.get('cost_stars', 0)
    if not bot_user or qty < 1:
        context.user_data['state'] = 'main_menu'
        await q.edit_message_text('⚠️ بيانات غير مكتملة.', reply_markup=main_menu_kb(is_own))
        return
    _dbu = get_user(user.id)
    if _dbu and _dbu.get('referral_points_blocked'):
        await q.edit_message_text('🔒 حسابك موقوف. تواصل مع المالك.', reply_markup=main_menu_kb(is_own))
        return

    # ─── دفع بالنجوم ───
    if action == 'stars':
        if total_stars < 1:
            await q.edit_message_text('⚠️ تعذّر حساب تكلفة النجوم.', reply_markup=main_menu_kb(is_own))
            return
        _use_ai_s = draft.get('use_ai', False)
        cost_pts_ch = draft.get('cost_pts_channels', 0)
        # إذا كانت هناك قنوات → اخصم نقاطها مسبقاً من رصيد المستخدم
        if cost_pts_ch > 0:
            if not deduct_points(user.id, cost_pts_ch):
                await q.edit_message_text(
                    f'❌ نقاطك غير كافية لتغطية تكلفة القنوات ({cost_pts_ch:,} نقطة).',
                    reply_markup=main_menu_kb(is_own)
                )
                return
        _code_fr  = f'`{start_p}`' if start_p else 'بدون كود'
        _title_s  = '🤖 إحالة بتحقق' if _use_ai_s else '🔑 إحالة بدون تحقق'
        # payload: forced_ref_stars:{user_id}:{qty}:{total_stars}:{use_ai}:{cost_pts_channels}
        payload   = f'forced_ref_stars:{user.id}:{qty}:{total_stars}:{int(_use_ai_s)}:{cost_pts_ch}'
        await q.delete_message()
        await context.bot.send_invoice(
            chat_id=user.id,
            title=_title_s,
            description=f'{qty} حساب | @{bot_user} {_code_fr} | {channels or "بدون قنوات"}',
            payload=payload,
            provider_token='',
            currency='XTR',
            prices=[LabeledPrice(f'إحالة {qty} حساب', total_stars)],
        )
        return

    # ─── دفع بالنقاط ───
    if not deduct_points(user.id, total):
        await q.edit_message_text('❌ نقاطك غير كافية.', reply_markup=main_menu_kb(is_own))
        context.user_data['state'] = 'main_menu'
        return
    code = next_order_code(user.id)
    with db_conn() as c:
        row = c.execute(
            'INSERT INTO forced_ref_orders '
            '(user_id,bot_username,start_param,channels,quantity,cost_points,cost_stars,payment_method,status,order_code) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
            (user.id, bot_user, start_p, channels, qty, total, 0, 'points', 'pending', code)
        ).fetchone()
        order_id = row['id']
    context.user_data['state'] = 'main_menu'
    context.user_data.pop('forced_ref_draft', None)
    _code_fr = f'`{start_p}`' if start_p else 'بدون كود'
    ch_line  = f'\n📢 القنوات: `{channels}`' if channels else ''
    await q.edit_message_text(
        f'✅ *تم استلام طلبك!*\n\n'
        f'📌 `@{bot_user}` | كود: {_code_fr}{ch_line}\n'
        f'🔢 {qty} حساب | 💎 {total:,} نقطة\n'
        f'🎫 كود: `{code}`\n\n'
        f'⏳ سيبدأ التنفيذ قريباً وستصلك إشعار عند الانتهاء.',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb(is_own)
    )
    await _maybe_send_to_group(
        context.bot, user.id,
        f'تم إحالة بوت إجباري العدد {qty}',
        parse_mode='Markdown'
    )
    import asyncio as _aio
    _use_ai = draft.get('use_ai', False)
    _aio.create_task(_run_forced_ref_order(
        order_id, bot_user, start_p, channels, qty, user.id, context,
        use_ai=_use_ai, payment_method='points', cost_stars=0,
        delay_seconds=draft.get('delay_seconds') if user.id == OWNER_ID else None
    ))

# ═══════════════════════════════════════════════════════════════════════════
# ══ إحالة إجبارية للمشرف — يستخدم حساباته الخاصة فقط، بدون تكلفة ══
# ═══════════════════════════════════════════════════════════════════════════

async def _sv_forced_ref_start(update, context, user, q, with_ai: bool = False):
    """الشاشة الأولى للمشرف — يختار نوع الإحالة (تحقق أم بدون)."""
    sv_accounts = get_supervisor_available_accounts(user.id)
    avail = len(sv_accounts)
    if avail == 0:
        await q.edit_message_text(
            "⚠️ *لا توجد حسابات متاحة*\n\n"
            "أضف حسابات أولاً من قسم ➕ إضافة حساب جديد.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة المشرف", callback_data="sv:panel")]])
        )
        return
    context.user_data['sv_forced_ref_draft'] = {'use_ai': with_ai}
    title = '🤖 إحالة بميزة تحقق' if with_ai else '🔑 إحالة بوت فقط'
    await q.edit_message_text(
        f'*{title}*\n\n'
        f'📊 حساباتك المتاحة: *{avail}*\n\n'
        f'📢 *أرسل معرفات القنوات الإجبارية:*\n'
        f'مثال: `@chan1 @chan2`\n\n'
        f'أو اضغط تخطي إن لم توجد قنوات.',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('⏭️ تخطي (بدون قنوات)', callback_data='sv_forced_ref_skip_channels')],
            [InlineKeyboardButton('🔙 رجوع', callback_data='sv:forced_ref')],
        ])
    )
    context.user_data['state'] = 'sv_await_forced_ref_channels'

async def _sv_forced_ref_handle_channels(update, context):
    raw   = update.message.text.strip()
    draft = context.user_data.setdefault('sv_forced_ref_draft', {})
    draft['channels'] = '' if raw.lower() in ('تخطي', 'skip', '-') else raw
    sv_accounts = get_supervisor_available_accounts(update.effective_user.id)
    avail = len(sv_accounts)
    use_ai = draft.get('use_ai', False)
    even_note = '\n⚠️ يُقبل فقط أعداد زوجية (٢، ٤، ٦ ...)' if use_ai else ''
    context.user_data['state'] = 'sv_await_forced_ref_link'
    await update.message.reply_text(
        f'✅ تم تسجيل القنوات.\n\n'
        f'📊 المتاح: *{avail}* حساب{even_note}\n\n'
        f'📎 *أرسل رابط البوت:*\n'
        f'`t.me/BotUsername?start=CODE`\n'
        f'أو: `@BotUsername CODE`',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 إلغاء', callback_data='sv:panel')]])
    )

async def _sv_forced_ref_handle_link(update, context):
    text  = update.message.text.strip()
    draft = context.user_data.setdefault('sv_forced_ref_draft', {})
    import re as _re
    m = _re.search(r't\.me/([A-Za-z0-9_]+)\?start=(\S+)', text)
    if m:
        draft['bot_user'] = m.group(1)
        draft['start_p']  = m.group(2)
    else:
        parts = text.lstrip('@').split()
        draft['bot_user'] = parts[0] if parts else ''
        draft['start_p']  = parts[1] if len(parts) > 1 else ''
    if not draft.get('bot_user'):
        await update.message.reply_text('⚠️ لم أتمكن من قراءة رابط البوت. أعد المحاولة.')
        return
    sv_accounts = get_supervisor_available_accounts(update.effective_user.id)
    avail = len(sv_accounts)
    use_ai = draft.get('use_ai', False)
    even_note = '\n⚠️ يُقبل فقط أعداد زوجية (٢، ٤، ٦ ...)' if use_ai else ''
    context.user_data['state'] = 'sv_await_forced_ref_qty'
    _bu = draft['bot_user']
    _sp = draft.get('start_p', '')
    _code_lbl = f'`{_sp}`' if _sp else 'بدون كود'
    await update.message.reply_text(
        f'✅ البوت: `@{_bu}` | كود: {_code_lbl}\n\n'
        f'📊 المتاح: *{avail}* حساب{even_note}\n\n'
        f'🔢 *أرسل عدد الحسابات (1 – {avail}):*',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 إلغاء', callback_data='sv:panel')]])
    )

async def _sv_forced_ref_handle_qty(update, context, user):
    try:
        qty = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text('⚠️ أرسل رقماً صحيحاً.')
        return
    draft    = context.user_data.setdefault('sv_forced_ref_draft', {})
    use_ai   = draft.get('use_ai', False)
    sv_accounts = get_supervisor_available_accounts(user.id)
    avail = len(sv_accounts)
    if use_ai and qty % 2 != 0:
        await update.message.reply_text(
            '⚠️ في وضع *التحقق* يُقبل فقط *أعداد زوجية* (٢، ٤، ٦...).',
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if qty < 1 or qty > avail:
        await update.message.reply_text(f'⚠️ الكمية خارج النطاق (1 – {avail}).')
        return
    draft['qty'] = qty
    channels = draft.get('channels', '')
    ch_count = len([t for t in channels.split() if t.strip()]) if channels else 0
    _bu   = draft.get('bot_user', '')
    _sp   = draft.get('start_p', '')
    _code_lbl = f'`{_sp}`' if _sp else 'بدون كود'
    ch_line   = f'\n📢 القنوات: `{channels}`' if channels else ''
    _title    = '🤖 تأكيد إحالة بميزة تحقق:' if use_ai else '🔑 تأكيد إحالة بوت فقط:'
    context.user_data['state'] = 'sv_confirm_forced_ref'
    await update.message.reply_text(
        f'📋 *{_title}*\n\n'
        f'📌 `@{_bu}` | كود: {_code_lbl}{ch_line}\n'
        f'🔢 {qty} حساب من حساباتك الخاصة\n'
        f'💡 مجاني — يستخدم حساباتك أنت فقط\n\n'
        f'⚡ الفاشلة: تُتجاوز تلقائياً',
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('✅ تأكيد وتشغيل', callback_data='sv_forced_ref_confirm:yes')],
            [InlineKeyboardButton('❌ إلغاء',         callback_data='sv_forced_ref_confirm:no')],
        ])
    )

async def _run_sv_forced_ref_order(bot_user, start_p, channels, quantity, supervisor_id, context, use_ai: bool = False):
    """تنفيذ الإحالة الإجبارية باستخدام حسابات المشرف الخاصة فقط."""
    import asyncio as _aio_sv

    def _supervisor_ref_delay_seconds() -> float:
        try:
            _value = float(get_setting("referral_task_delay") or "30")
            if not math.isfinite(_value):
                raise ValueError("non-finite delay")
            return max(0.0, _value)
        except (TypeError, ValueError):
            return 30.0

    sv_accounts = get_supervisor_available_accounts(supervisor_id)
    pool = sv_accounts[:quantity]

    done = 0
    failed = 0
    reactivated = 0
    _done_phones    = []
    _reactiv_phones = []
    _fail_reasons   = []

    _all_channels = channels or ''
    _ai_label     = ' 🤖' if use_ai else ''

    # رسالة البداية
    try:
        msg = await context.bot.send_message(
            chat_id=supervisor_id,
            text=f'⏳ *بدأت الإحالة الإجبارية{_ai_label}*\n\n'
                 f'📌 `@{bot_user}` | كود: `{start_p or "بدون"}`\n'
                 f'🔢 {quantity} حساب | 0/{quantity} منجز...',
            parse_mode=ParseMode.MARKDOWN
        )
        progress_msg_id = msg.message_id
    except Exception:
        progress_msg_id = None

    def _progress_text(idx: int) -> str:
        return (
            f'⏳ *جارية الإحالة الإجبارية{_ai_label}*\n\n'
            f'📌 `@{bot_user}`\n'
            f'🔢 {idx}/{quantity} منجز | ✅ {done} | 🔁 {reactivated} | ❌ {failed}'
        )

    for idx, num in enumerate(pool, 1):
        if done + reactivated >= quantity:
            break
        try:
            ok, reactiv, detail = await do_referral_for_number(
                num['phone_number'], num['session_string'],
                bot_user, start_p,
                mandatory_channels=_all_channels,
                folder_link='',
                use_ai=use_ai,
                leave_channels_after=True,
                stock_id=0,
            )
        except Exception as _ex:
            ok = False; reactiv = False
            detail = f'[{type(_ex).__name__}] {str(_ex)[:80]}'

        if ok and reactiv:
            reactivated += 1
            _reactiv_phones.append(num['phone_number'])
        elif ok:
            done += 1
            _done_phones.append(num['phone_number'])
        else:
            failed += 1
            _fail_reasons.append(f"`{num['phone_number']}`: {detail[:60]}")

        # تحديث رسالة التقدم كل 3 حسابات
        if progress_msg_id and idx % 3 == 0:
            try:
                await context.bot.edit_message_text(
                    chat_id=supervisor_id,
                    message_id=progress_msg_id,
                    text=_progress_text(idx),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

        # نفس فاصل المالك المستخدم في إحالة البوت الإجبارية المدفوعة.
        if idx < len(pool):
            await _aio_sv.sleep(_supervisor_ref_delay_seconds())

    # ── رسالة النهاية ──
    fail_lines = '\n'.join(_fail_reasons[:10]) if _fail_reasons else ''
    fail_block = f'\n\n❌ *أسباب الفشل:*\n{fail_lines}' if fail_lines else ''
    final_text = (
        f'✅ *اكتملت الإحالة الإجبارية{_ai_label}*\n\n'
        f'📌 `@{bot_user}` | كود: `{start_p or "بدون"}`\n'
        f'🔢 المطلوب: {quantity}\n'
        f'✅ منجز: {done}\n'
        f'🔁 مكرر (كان مفعّلاً): {reactivated}\n'
        f'❌ فاشل: {failed}'
        f'{fail_block}'
    )
    try:
        if progress_msg_id:
            await context.bot.edit_message_text(
                chat_id=supervisor_id,
                message_id=progress_msg_id,
                text=final_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة المشرف", callback_data="sv:panel")]])
            )
        else:
            await context.bot.send_message(
                chat_id=supervisor_id,
                text=final_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لوحة المشرف", callback_data="sv:panel")]])
            )
    except Exception:
        pass

async def _run_forced_ref_order(order_id, bot_user, start_p, channels, quantity, requester_id, context,
                                use_ai: bool = False, payment_method: str = 'points', cost_stars: int = 0,
                                delay_seconds: float | None = None):
    import random as _rnd
    import time as _time

    def _forced_ref_delay_seconds() -> float:
        """Return the owner's current delay, with a safe fallback for bad settings."""
        if delay_seconds is not None:
            try:
                _value = float(delay_seconds)
                if not math.isfinite(_value):
                    raise ValueError("non-finite delay")
                return max(0.0, _value)
            except (TypeError, ValueError):
                return 30.0
        try:
            _value = float(get_setting("referral_task_delay") or "30")
            if not math.isfinite(_value):
                raise ValueError("non-finite delay")
            return max(0.0, _value)
        except (TypeError, ValueError):
            return 30.0

    # ── حماية: إذا استهدف المستخدم (غير المالك) البوت نفسه → طلب وهمي مكتمل بدون تعويض ──
    _clean_bot_target = bot_user.lower().lstrip("@").strip()
    if _OWN_BOT_USERNAME and _clean_bot_target == _OWN_BOT_USERNAME and requester_id != OWNER_ID:
        with db_conn() as _sc:
            _sc.execute(
                "UPDATE forced_ref_orders SET status='done', done_count=%s WHERE id=%s",
                (quantity, order_id)
            )
        _ai_label_s = ' 🤖' if use_ai else ''
        try:
            await context.bot.send_message(
                requester_id,
                f'✅ <b>اكتملت إحالة البوت الإجبارية{_ai_label_s}!</b>\n'
                f'📌 @{bot_user}\n\n'
                f'✅ تم: <b>{quantity}</b>  |  ❌ فشل: <b>0</b>',
                parse_mode='HTML'
            )
        except Exception:
            pass
        return

    with db_conn() as c:
        c.execute("UPDATE forced_ref_orders SET status='running' WHERE id=%s", (order_id,))
        rows = c.execute(
            "SELECT id,phone_number,session_string FROM number_stock"
            " WHERE session_string IS NOT NULL AND BTRIM(session_string) <> ''"
            " AND deleted_at IS NULL"
            " AND forced_ref_excluded IS NOT TRUE"
            " ORDER BY id"
        ).fetchall()
        # جلب القنوات الإجبارية العامة للبوت — الحسابات تنضم إليها أولاً قبل الضغط على الرابط
        _global_ch_rows = c.execute(
            "SELECT channel_username FROM mandatory_channels WHERE active=1 AND funding_type='mandatory'"
        ).fetchall()
    _global_ch_str = ' '.join(
        ('@' + r['channel_username'].lstrip('@')) for r in _global_ch_rows if r.get('channel_username')
    )
    with db_conn() as _cfm:
        _order_meta_f = _cfm.execute(
            "SELECT cost_points, cost_stars, quantity FROM forced_ref_orders WHERE id=%s", (order_id,)
        ).fetchone()
    _total_cost_pts   = int(_order_meta_f["cost_points"] or 0) if _order_meta_f else 0
    _total_cost_stars = int(_order_meta_f["cost_stars"]  or cost_stars) if _order_meta_f else cost_stars
    _qty_total_f      = int(_order_meta_f["quantity"]    or 1) if _order_meta_f else max(1, quantity)
    _cost_pts_each    = round(_total_cost_pts   / _qty_total_f) if _qty_total_f else 0
    _cost_stars_each  = round(_total_cost_stars / _qty_total_f) if _qty_total_f else 0

    # سعر النجمة بالنقاط (للتعويض عند الدفع بنجوم — كل النجوم المدفوعة تُحوَّل نقاطاً)
    _star_rate = int(get_setting('star_to_points') or '250')

    # دمج القنوات الإجبارية العامة + قنوات المستخدم المحددة في الطلب
    _all_channels = ' '.join(filter(None, [_global_ch_str, channels or ''])).strip()
    nums = [dict(r) for r in rows]
    _rnd.shuffle(nums)
    pool     = list(nums)      # كامل المخزون المتاح بترتيب عشوائي
    pool_idx = quantity        # أول حساب بديل يبدأ بعد الدفعة الأولى
    done = failed = reactivated = 0
    replaced = 0               # عدد الحسابات البديلة التي استُخدمت
    refunded_pts = 0
    _fail_reasons: list = []   # أسباب الفشل — تُعرض في الرسالة النهائية
    _done_phones:   list = []  # أرقام الحسابات الناجحة
    _reactiv_phones: list = [] # أرقام الحسابات المكررة
    _fail_phones:   list = []  # (phone, stock_id, سبب) الحسابات الفاشلة

    # ─── رسالة التقدم الحي ───
    _live_msg_f       = None
    _last_edit_time_f = 0.0
    _EDIT_INTERVAL_F  = 3.0   # ثوانٍ بين كل تحديث للرسالة (تجنّب Rate-Limit)
    _ai_label = ' 🤖' if use_ai else ''

    def _forced_ref_progress_text(idx: int) -> str:
        parts = []
        if done > 0:        parts.append(f'{done} ✅ تم')
        if failed > 0:      parts.append(f'{failed} ❌ فشل')
        if reactivated > 0: parts.append(f'{reactivated} 🔄 مكرر')
        status = '  |  '.join(parts) if parts else '⏳ جاري...'
        return (
            f'⏳ <b>جاري تنفيذ الإحالة الإجبارية{_ai_label}...</b>\n'
            f'📌 @{bot_user} | {quantity} حساب\n\n'
            f'<b>حساب {idx}/{quantity}</b> — {status}'
        )

    try:
        _live_msg_f = await context.bot.send_message(
            requester_id,
            f'⏳ <b>جاري تنفيذ الإحالة الإجبارية{_ai_label}...</b>\n📌 @{bot_user} | {quantity} حساب\n\nحساب 0/{quantity} — ⏳ جاري...',
            parse_mode='HTML'
        )
        _last_edit_time_f = _time.monotonic()
    except Exception:
        pass

    import asyncio as _aio2

    # الأخطاء الدائمة — لا فائدة من إعادة المحاولة
    _PERM_ERRORS = (
        "AuthKeyUnregistered", "SessionRevoked", "SessionExpired",
        "UserDeactivated", "AccountBanned", "PhoneNumberBanned",
        "AuthKeyDuplicated", "جلسة منتهية",
    )

    def _is_permanent(detail: str) -> bool:
        return any(k in detail for k in _PERM_ERRORS)

    async def _run_one_forced_ref(num):
        """Run one account; account attempts are launched concurrently at the configured rate."""
        _started_at = _time.monotonic()
        try:
            _result = await do_referral_for_number(
                num['phone_number'], num['session_string'],
                bot_user, start_p,
                mandatory_channels=_all_channels,
                folder_link='',
                use_ai=use_ai,
                leave_channels_after=True,
                stock_id=num.get('id', 0),
            )
        except Exception as _ex:
            _result = (False, False, f'[{type(_ex).__name__}] {str(_ex)[:80]}')
        logger.info(
            f'⏱️ إحالة {num["phone_number"]} → @{bot_user}: '
            f'{_time.monotonic() - _started_at:.1f}ث'
        )
        return _result

    async def _record_forced_ref_result(num, result):
        nonlocal done, failed, reactivated, _last_edit_time_f
        ok, reactiv, _detail = result
        if ok and reactiv:
            with db_conn() as c:
                c.execute("UPDATE forced_ref_orders SET reactivated_count=reactivated_count+1 WHERE id=%s", (order_id,))
            reactivated += 1
            _reactiv_phones.append(num['phone_number'])
        elif ok:
            with db_conn() as c:
                c.execute("UPDATE forced_ref_orders SET done_count=done_count+1 WHERE id=%s", (order_id,))
            done += 1
            _done_phones.append(num['phone_number'])
        else:
            with db_conn() as c:
                c.execute("UPDATE forced_ref_orders SET failed_count=failed_count+1 WHERE id=%s", (order_id,))
            failed += 1
            _fail_reasons.append(f"{num['phone_number']}: {_detail}")
            _fail_phones.append((num['phone_number'], num.get('id', 0), _detail))

        _now_f = _time.monotonic()
        _total_done = done + failed + reactivated
        if _live_msg_f and (_now_f - _last_edit_time_f >= _EDIT_INTERVAL_F or _total_done == quantity):
            try:
                _repl_note = f' | 🔁 بديل: {replaced}' if replaced > 0 else ''
                await context.bot.edit_message_text(
                    _forced_ref_progress_text(_total_done) + _repl_note,
                    chat_id=requester_id,
                    message_id=_live_msg_f.message_id,
                    parse_mode='HTML'
                )
                _last_edit_time_f = _now_f
            except Exception:
                pass
        return bool(ok)

    # إطلاق الحسابات بفاصل زمني بين بدايات المحاولات، لا بعد انتهاء الحساب السابق.
    # لذلك 40 حساباً مع فاصل 1ث تبدأ خلال نحو 40ث حتى لو استغرقت بعض المحاولات وقتاً أطول.
    _pending = pool[:quantity]
    while _pending and done + reactivated < quantity:
        _cycle = list(_pending)
        _pending = []
        _active = []
        _launch_delay = _forced_ref_delay_seconds()

        for _launch_idx, num in enumerate(_cycle):
            _active.append((num, _aio2.create_task(_run_one_forced_ref(num))))
            if _launch_idx < len(_cycle) - 1 and _launch_delay > 0:
                await _aio2.sleep(_launch_delay)

        # تُجمع نتائج الدفعة بعد إطلاقها؛ الحسابات تعمل بالتوازي.
        for num, task in _active:
            _result = await task
            _ok = await _record_forced_ref_result(num, _result)
            if not _ok and pool_idx < len(pool):
                _pending.append(pool[pool_idx])
                pool_idx += 1
                replaced += 1

        if _pending and _live_msg_f:
            try:
                await context.bot.edit_message_text(
                    _forced_ref_progress_text(done + failed + reactivated) +
                    f'\n🔁 جاري إطلاق {len(_pending)} حساب بديل بفاصل {_launch_delay:g}ث...',
                    chat_id=requester_id,
                    message_id=_live_msg_f.message_id,
                    parse_mode='HTML'
                )
            except Exception:
                pass

    # ─── حساب التعويضات ───
    # الكميات غير المكتملة (لم يُجد لها بديل): تُعوَّض دائماً
    unfulfilled = max(0, quantity - done - reactivated)
    if unfulfilled > 0:
        if payment_method == 'stars' and _cost_stars_each > 0:
            refunded_pts = unfulfilled * (_cost_stars_each * _star_rate)
        elif _cost_pts_each > 0:
            refunded_pts = unfulfilled * _cost_pts_each
        if refunded_pts > 0:
            add_points(requester_id, refunded_pts)

    # المكررة (إعادة تفعيل): تُعوَّض فقط عند الدفع بنجوم
    reactiv_refunded_pts = 0
    if reactivated > 0 and payment_method == 'stars' and _cost_stars_each > 0:
        reactiv_refunded_pts = reactivated * (_cost_stars_each * _star_rate)
        add_points(requester_id, reactiv_refunded_pts)

    with db_conn() as c:
        c.execute("UPDATE forced_ref_orders SET status='done' WHERE id=%s", (order_id,))

    # ─── رسالة الإشعار النهائية ───
    _refund_parts = []
    if refunded_pts > 0:
        _refund_parts.append(f'غير مكتمل: {refunded_pts:,} نقطة ({unfulfilled} حساب)')
    if reactiv_refunded_pts > 0:
        _refund_parts.append(f'المكررة: {reactiv_refunded_pts:,} نقطة ({reactivated} حساب)')
    _refund_line = '\n💰 <b>التعويض:</b> ' + ' | '.join(_refund_parts) if _refund_parts else ''

    _stars_note = ''
    if payment_method == 'stars' and reactivated > 0:
        _stars_note = '\n✅ <i>لأنك دفعت بالنجوم، تم تعويض المكررة أيضاً (250 نقطة لكل نجمة مدفوعة)</i>'
    elif payment_method != 'stars' and reactivated > 0:
        _stars_note = '\n⚠️ <i>الإحالات المكررة لا تُعوَّض عند الدفع بالنقاط</i>'

    _replaced_note = f'\n🔁 <i>استُبدل {replaced} حساب فاشل بحسابات أخرى</i>' if replaced > 0 else ''

    # ─── بناء قوائم الأرقام لكل فئة ───
    def _phones_block(phones: list, limit: int = 30) -> str:
        if not phones:
            return ''
        lines = '\n'.join(f'  • <code>{p}</code>' for p in phones[:limit])
        if len(phones) > limit:
            lines += f'\n  ... و{len(phones)-limit} آخرين'
        return lines

    # ══ رسالة العضو: مبسّطة بدون أرقام ══
    _member_text = (
        f'✅ <b>تم اكتمال طلبك{_ai_label}!</b>\n'
        f'📌 @{bot_user}\n\n'
        f'✅ المنجز: <b>{done}</b>'
    )
    if reactivated > 0:
        _member_text += f'  |  🔄 المكرر: <b>{reactivated}</b>'
    if failed > 0:
        _member_text += f'  |  ❌ الفاشل: <b>{failed}</b>'
    _member_text += _refund_line + _stars_note

    # ══ رسالة المالك: تفاصيل كاملة + أزرار طرد ══
    _done_block    = _phones_block(_done_phones)
    _reactiv_block = _phones_block(_reactiv_phones)
    _fail_block    = ''
    if _fail_phones:
        _fail_lines = []
        for _fp, _fid, _fd in _fail_phones[:20]:
            _short_reason = _fd[:50] if _fd else '—'
            _fail_lines.append(f'  • <code>{_fp}</code> — {_short_reason}')
        _fail_block = '\n'.join(_fail_lines)
        if len(_fail_phones) > 20:
            _fail_block += f'\n  ... و{len(_fail_phones)-20} آخرين'

    _owner_text = (
        f'📊 <b>تقرير إحالة بوت إجباري{_ai_label}</b>\n'
        f'📌 @{bot_user}'
        + (f' | 👤 <code>{requester_id}</code>' if requester_id != OWNER_ID else '')
        + f'\n💳 {"⭐ نجوم" if payment_method == "stars" else "💎 نقاط"}\n\n'
        f'✅ المنجز: <b>{done}</b>  |  🔄 المكرر: <b>{reactivated}</b>  |  ❌ الفاشل: <b>{failed}</b>'
        + (_replaced_note or '')
        + (_refund_line or '')
    )
    if _done_block:
        _owner_text += f'\n\n✅ <b>الحسابات المنجزة:</b>\n{_done_block}'
    if _reactiv_block:
        _owner_text += f'\n\n🔄 <b>الحسابات المكررة:</b>\n{_reactiv_block}'
    if _fail_block:
        _owner_text += f'\n\n❌ <b>الحسابات الفاشلة:</b>\n{_fail_block}'

    _kick_kb = []
    if _fail_phones:
        for _fp, _fid, _ in _fail_phones[:10]:
            _kick_kb.append([InlineKeyboardButton(f'⚡ طرد {_fp}', callback_data=f'fref_kick:{_fid}:{_fp}')])
        if len(_fail_phones) > 10:
            _owner_text += f'\n\n<i>⚠️ يظهر زر الطرد لأول 10 حسابات فاشلة فقط</i>'
    _kick_markup = InlineKeyboardMarkup(_kick_kb) if _kick_kb else None

    # ── إرسال الرسائل ──
    async def _send_msg(chat_id, txt, markup=None):
        try:
            await context.bot.send_message(chat_id, txt, parse_mode='HTML', reply_markup=markup)
        except Exception:
            pass

    if requester_id == OWNER_ID:
        # المالك يرى التقرير الكامل مباشرةً
        if _live_msg_f:
            try:
                await context.bot.edit_message_text(
                    _owner_text, chat_id=requester_id,
                    message_id=_live_msg_f.message_id,
                    parse_mode='HTML', reply_markup=_kick_markup
                )
            except Exception:
                await _send_msg(requester_id, _owner_text, _kick_markup)
        else:
            await _send_msg(requester_id, _owner_text, _kick_markup)
    else:
        # العضو يرى الملخص المبسط فقط
        if _live_msg_f:
            try:
                await context.bot.edit_message_text(
                    _member_text, chat_id=requester_id,
                    message_id=_live_msg_f.message_id,
                    parse_mode='HTML'
                )
            except Exception:
                await _send_msg(requester_id, _member_text)
        else:
            await _send_msg(requester_id, _member_text)
        # المالك يتلقى التقرير الكامل منفصلاً
        if OWNER_ID:
            await _send_msg(OWNER_ID, _owner_text, _kick_markup)

    await _maybe_send_to_group(
        context.bot, requester_id,
        f'🔑 إحالة بوت اجباري اكتملت | 👤 {requester_id} | @{bot_user} | ✅{done} ❌{failed} 🔄{reactivated} | تعويض {refunded_pts + reactiv_refunded_pts:,}نقطة | {payment_method}',
        parse_mode='Markdown'
    )

async def _run_referral_for_new_number(phone: str, session_str: str, stock_id: int):
    """يُشغَّل فور إضافة رقم جديد: ينفّذ جميع مهام الإحالة التلقائية النشطة لهذا الرقم مباشرةً،
    دون انتظار الدورة الساعية. يتجاهل المهام التي أكملها الرقم مسبقاً."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    if not session_str:
        return
    tasks = get_referral_tasks(only_active=True)
    if not tasks:
        return
    # ── تأخير عشوائي عند البداية لتفريق الأرقام المُضافة دفعةً واحدة ──
    import random as _rand_rfn
    _jitter = _rand_rfn.uniform(60, 480)
    logger.info(f"🤝 الرقم الجديد {phone}: انتظار {_jitter:.0f}ث قبل بدء الإحالة التلقائية")
    await asyncio.sleep(_jitter)
    logger.info(f"🤝 تشغيل مهام الإحالة الفورية للرقم الجديد {phone} ({len(tasks)} مهمة)")
    for task in tasks:
        # تخطي إذا كان الرقم أنجز هذه المهمة بالفعل
        with db_conn() as _c:
            _done = _c.execute(
                "SELECT 1 FROM referral_completions WHERE task_id=%s AND stock_id=%s AND status='done'",
                (task["id"], stock_id)
            ).fetchone()
        if _done:
            continue
        # تخطي فوري إذا كان البوت المستهدف هو البوت نفسه
        if _OWN_BOT_USERNAME and task["bot_username"].lower().lstrip("@") == _OWN_BOT_USERNAME:
            mark_referral_completion(task["id"], stock_id, "done", "البوت المستهدف هو البوت نفسه")
            continue
        success, _reactiv, detail = await do_referral_for_number(
            phone, session_str,
            task["bot_username"], task.get("start_param", "") or "",
            mandatory_channels=task.get("mandatory_channels", "") or "",
            folder_link=task.get("folder_link", "") or "",
            stock_id=stock_id,
        )
        status = "done" if success else "failed"
        mark_referral_completion(task["id"], stock_id, status, None if success else detail)
        logger.info(f"🤝 مهمة [{task['label']}] ← {phone}: {'✅ نجح' if success else '❌ فشل'}")
        # تأخير بين كل مهمة إحالة لنفس الرقم — قابل للضبط
        _task_delay = float(get_setting("referral_task_delay") or "30")
        await asyncio.sleep(max(0.00001, _task_delay))


async def run_referral_tasks_job(context: ContextTypes.DEFAULT_TYPE):
    """تُشغَّل كل ساعة: تُكمل الإحالات لكل الأرقام التي لم تُنفّذها بعد."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    tasks = get_referral_tasks(only_active=True)
    if not tasks:
        return
    for task in tasks:
        # تخطي فوري إذا كان البوت المستهدف هو البوت نفسه (ارشقلي)
        if _OWN_BOT_USERNAME and task["bot_username"].lower().lstrip("@") == _OWN_BOT_USERNAME:
            logger.info(f"🤝 مهمة [{task['label']}]: البوت المستهدف هو البوت نفسه — تم التخطي")
            continue
        pending = get_pending_numbers_for_task(task["id"])
        if not pending:
            continue
        logger.info(f"🤝 مهمة إحالة [{task['label']}]: {len(pending)} رقم معلّق")
        done = failed = reactivated_auto = 0
        for num in pending:
            # تخطي الأرقام التي لم تحصل على جلسة بعد (ستُشمل تلقائياً في الدورة القادمة)
            if not num.get("session_string"):
                continue
            success, _reactiv_t, detail = await do_referral_for_number(
                num["phone_number"], num["session_string"],
                task["bot_username"], task["start_param"],
                mandatory_channels=task.get("mandatory_channels", "") or "",
                folder_link=task.get("folder_link", "") or "",
                stock_id=num.get("id", 0),
            )
            status = "done" if success else "failed"
            mark_referral_completion(task["id"], num["id"], status,
                                     None if success else detail)
            if success and _reactiv_t:
                reactivated_auto += 1
                done += 1
            elif success:
                done += 1
            else:
                failed += 1
            _ref_delay = float(get_setting("referral_task_delay") or "30")
            await asyncio.sleep(max(0.00001, _ref_delay))   # فاصل بين أرقام — قابل للضبط
        logger.info(f"✅ مهمة [{task['label']}]: {done} نجحت، {failed} فشلت، {reactivated_auto} مكرر")
        if OWNER_ID:
            try:
                await context.bot.send_message(
                    OWNER_ID,
                    f'📊 <b>تقرير الإحالة التلقائية</b>\n'
                    f'📌 🤖 من المالك — الإحالة التلقائية\n'
                    f'🏷 المهمة: {task["label"]} | @{task["bot_username"]}\n\n'
                    f'✅ <b>الحسابات المكملة:</b> {done - reactivated_auto}\n'
                    f'❌ <b>الحسابات الفاشلة:</b> {failed}\n'
                    f'🔄 <b>الحسابات المكررة (مفعّل مسبقاً):</b> {reactivated_auto}',
                    parse_mode='HTML'
                )
            except Exception:
                pass

# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
