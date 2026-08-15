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
    - تعتمد الآن بشكل أساسي على الأزرار (Buttons) لأن هذا هو النوع الموجود في صورة "روليت تناهيد".
    """
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    if not GROQ_API_KEY:
        return False, "لا يوجد مفتاح GROQ_API_KEY"

    # دالة مساعدة لاستخراج نصوص الأزرار
    def get_button_labels(msg) -> list:
        labels = []
        if msg.buttons:
            for row in msg.buttons:
                for btn in row:
                    # نستخرج النص فقط، ونتجاهل أزرار الروابط (URLs)
                    if getattr(btn, 'text', None) and not getattr(btn, 'url', None):
                        labels.append(btn.text)
        return labels

    # دالة مساعدة للضغط على الزر
    async def click_button_by_text(msg, target_text):
        # نقوم بتطبيع النص للمقارنة (إزالة المسافات والرموز الزائدة)
        clean_target = _normalize_captcha_text(target_text)
        
        for row in msg.buttons:
            for btn in row:
                if _captcha_button_matches(getattr(btn, "text", ""), target_text):
                    try:
                        await btn.click()
                        return True
                    except Exception:
                        pass
        return False

    # ── بدء حل الكابتشا ──
    for attempt in range(max_attempts):
        if attempt > 0:
            await asyncio.sleep(3)  # انتظر قليلاً قبل إعادة المحاولة
        
        # احصل على أحدث الرسائل
        msgs = await asyncio.wait_for(client.get_messages(bot_entity, limit=5), timeout=10)
        
        for msg in msgs:
            # 1. فحص وجود أزرار (هذا هو الأهم للصورة التي أرسلتها)
            if msg.buttons:
                # جلب نصوص الأزرار المتاحة
                button_labels = get_button_labels(msg)
                
                # 2. إرسال سؤال نصي لـ Groq (بدون صورة، مجرد نص ونصوص الأزرار)
                prompt = f"""
                أنا بوت تيليغرام. تلقيت رسالة تحقق تحتوي على أزرار في لوحة المفاتيح.
                
                نص الرسالة التي وصلتني هو:
                "{msg.text or ''}"
                
                الأزرار المتاحة للضغط هي:
                {', '.join(button_labels)}
                
                بناءً على نص الرسالة، أخبرني باسم الزر الصحيح الذي يجب أن أضغط عليه.
                أعد فقط اسم الزر كما هو بالضبط، بدون أي شرح أو رموز إضافية.
                """
                
                def _groq_text_request():
                    try:
                        r = requests.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {GROQ_API_KEY}",
                                "Content-Type": "application/json"
                            },
                            json={
                                "model": "llama-3.3-70b-versatile",  # نموذج نصوص، أسرع من نموذج الرؤية
                                "messages": [{"role": "user", "content": prompt}],
                                "max_tokens": 20,
                                "temperature": 0
                            },
                            timeout=15
                        )
                        if r.status_code == 200:
                            data = r.json()
                            if data.get("choices"):
                                return data["choices"][0]["message"]["content"].strip()
                        return None
                    except Exception:
                        return None
                
                # الحصول على الإجابة من الذكاء الاصطناعي
                target_button = await asyncio.to_thread(_groq_text_request)
                
                if target_button:
                    logger.info(f"🤖 Groq اختار الزر: '{target_button}'")
                    # 3. محاولة الضغط على الزر المطابق
                    if await click_button_by_text(msg, target_button):
                        await asyncio.sleep(2)
                        # التحقق من نجاح العملية
                        check_msgs = await asyncio.wait_for(client.get_messages(bot_entity, limit=5), timeout=10)
                        for nm in check_msgs:
                            if any(k in nm.text for k in ["أهلاً", "مرحباً", "تم", "success", "✅", "صحيح"]):
                                return True, f"نجح التحقق بالزر: {target_button}"
                
                # إذا فشلنا، جرب استخدام "الزر الوحيد" (إذا كان هناك زر واحد فقط)
                if len(button_labels) == 1:
                    if await click_button_by_text(msg, button_labels[0]):
                        await asyncio.sleep(2)
                        return True, f"نجح التحقق بالزر الوحيد: {button_labels[0]}"

    return False, "لم يتم حل الكابتشا بعد المحاولات"
