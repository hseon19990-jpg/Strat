"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

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
              AND ns.raksh_only IS NOT TRUE
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

async def solve_captcha_with_ai(client, bot_entity, msgs: list, phone: str = "", max_attempts: int = 3) -> tuple:
    """
    يستخدم Groq أو DeepSeek لكشف وحل جميع أنواع التحقق الشائعة في بوتات تيليغرام.
    يُرجع (solved: bool, detail: str).
    """
    # ════════════════════════════════════════════════════════════
    # 🔥 DEBUG: تأكد من أن الدالة تُستدعى والمفاتيح موجودة
    # ════════════════════════════════════════════════════════════
    logger.info(f"🔥🔥🔥 solve_captcha_with_ai تم استدعاؤها للرقم {phone} 🔥🔥🔥")
    
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
    
    logger.info(f"🔑 GROQ_API_KEY موجود: {bool(GROQ_API_KEY)} | طوله: {len(GROQ_API_KEY)}")
    logger.info(f"🔑 DEEPSEEK_API_KEY موجود: {bool(DEEPSEEK_API_KEY)} | طوله: {len(DEEPSEEK_API_KEY)}")
    # ════════════════════════════════════════════════════════════

    if not GROQ_API_KEY and not DEEPSEEK_API_KEY:
        return False, "لا يوجد مفتاح API للتحقق (Groq أو DeepSeek)"

    # ميّز بين عدم وجود كابتشا وبين تعذر الوصول إلى مزود الذكاء
    # الاصطناعي. مسار التصويت يستطيع المتابعة عندما لا يطلب البوت تحققاً،
    # لكنه يجب أن يتوقف عندما تكون الكابتشا موجودة والمزود غير متاح.
    provider_failures: list[str] = []
    groq_blocked = False
    deepseek_blocked = False
    ai_request_attempted = False

    # ── كلمات دلالية ──────────────────────────────────────────
    SUCCESS_KW = [
        "✅", "تم", "نجح", "مبروك", "أهلاً", "مرحباً", "welcome", "success",
        "تم التحقق", "مقبول", "accepted", "verified", "شكراً", "برافو",
        "اشتركت", "سجلت", "تسجيل", "دخلت", "ترحيب", "congratulations",
        "passed", "اجتزت", "صحيح", "correct", "ممتاز", "👍", "تم قبولك",
        "تم التسجيل", "انتهت عملية", "تم التفعيل", "بنجاح",
        "تم التصويت", "صوتك", "سجلنا تصويتك", "تم تسجيل التصويت",
        "vote recorded", "vote accepted", "voted successfully", "your vote",
    ]
    FAIL_KW = [
        "خطأ", "غلط", "wrong", "incorrect", "فشل", "error", "❌",
        "حاول مجدداً", "try again", "retry", "invalid", "غير صحيح",
        "أعد", "مجدداً", "again", "حاول ثانية", "إجابة خاطئة",
        # لا نعتبر كلمة error العامة فشلاً؛ بعض البوتات تسجل التصويت
        # ثم تعرض تنبيهًا عامًا أو نصًا مضللًا.

    ]
    CAPTCHA_KW = [
        "تحقق", "verify", "captcha", "اضغط", "ادخل", "أجب", "اختر",
        "robot", "بشر", "human", "confirm", "verification", "كابتشا",
        "لست روبوت", "لست بوت", "not a robot", "prove", "إثبت",
    ]
    MATH_KW = [
        "=", "؟", "?", "كم", "احسب", "حل", "اكتب", "أدخل",
        "اجمع", "اطرح", "اضرب", "اقسم", "ناتج", "حاصل", "result",
        "calculate", "solve", "answer", "الإجابة", "الجواب", "الرقم",
    ]
    FORWARD_KW = [
        "شارك", "أرسل ملف", "ارسل ملف", "forward", "ملفك الشخصي",
        "profile", "بروفايل", "contact", "جهة اتصال", "رقمك",
        "رقم هاتفك", "شارك ملفك", "ارسل بياناتك", "بياناتك الشخصية",
    ]
    REACTION_KW = [
        "تفاعل", "react", "reaction", "اضغط على", "ارسل إيموجي",
        "أرسل إيموجي", "انقر", "إيموجي", "emoji", "رد بـ", "reply with",
        "أرسل رد", "ارسل رد",
    ]

    # ── دوال مساعدة ───────────────────────────────────────────
    # ════════════════════════════════════════════════════════════
    # 🔥 _solve_text: يستخدم Groq أولاً، ثم DeepSeek
    # ════════════════════════════════════════════════════════════
    async def _solve_text(prompt: str) -> str | None:
        """
        يحل النصوص باستخدام Groq API أولاً (أسرع وأكثر استقراراً).
        في حال فشل Groq، يستخدم DeepSeek كاحتياطي.
        """
        
        nonlocal groq_blocked, deepseek_blocked, ai_request_attempted

        GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
        DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
        
        # ── المحاولة 1: Groq (الأسرع والأفضل) ──
        if GROQ_API_KEY and not groq_blocked:
            def _groq_request():
                nonlocal groq_blocked, ai_request_attempted
                ai_request_attempted = True
                # اسم النموذج القديم قد لا يكون متاحاً لكل مفاتيح Groq.
                # يمكن تخصيصه من GROQ_TEXT_MODEL. وإذا رفضه المفتاح،
                # نقرأ /models لاختيار نموذج متاح فعلياً لهذا المفتاح.
                configured = os.environ.get("GROQ_TEXT_MODEL", "").strip()
                configured_models = [configured] if configured else []
                fallback_models = [
                    "llama-3.1-8b-instant",
                    "openai/gpt-oss-20b",
                    "qwen/qwen3-32b",
                    "llama-3.3-70b-versatile",
                ]
                discovered = []
                try:
                    available = requests.get(
                        "https://api.groq.com/openai/v1/models",
                        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                        timeout=10,
                    )
                    if available.status_code == 200:
                        ids = [
                            item.get("id", "") for item in
                            available.json().get("data", [])
                        ]
                        # استبعد نماذج الصوت/التضمين، وفضّل نماذج النص
                        # الشائعة. نضيفها بعد القائمة اليدوية للحفاظ على
                        # ترتيب التفضيل إن كان المفتاح يتيح أحدها.
                        discovered = [
                            mid for mid in ids
                            if mid and not any(
                                part in mid.lower()
                                for part in ("whisper", "embedding", "guard")
                            )
                        ]
                        logger.info(
                            f"🤖 Groq models available={len(discovered)}"
                        )
                    elif available.status_code == 429:
                        groq_blocked = True
                        provider_failures.append("تجاوز حد Groq")
                        return None
                except Exception as model_exc:
                    logger.warning(f"⚠️ تعذر جلب قائمة نماذج Groq: {model_exc}")

                # نماذج /models هي المصدر الحقيقي لصلاحية المفتاح. لا نضع
                # نموذجاً ثابتاً غير موجود أمامها، لأن ذلك كان يسبب
                # model_not_found قبل الوصول إلى النماذج الصالحة.
                if discovered:
                    discovered_set = set(discovered)
                    models = [
                        model for model in configured_models + fallback_models
                        if model in discovered_set
                    ]
                    models.extend(discovered)
                else:
                    models = configured_models + fallback_models
                # إذا نجح /models، لا تجرب أي موديل خارج القائمة التي
                # أعادها Groq؛ القائمة القديمة قد تسبب 404 متتالية وتمنع
                # الوصول إلى موديل صالح.
                if discovered:
                    discovered_set = set(discovered)
                    ordered_models = [
                        model for model in configured_models + fallback_models + discovered
                        if model in discovered_set
                    ]
                else:
                    ordered_models = configured_models + fallback_models
                models = list(dict.fromkeys(model for model in ordered_models if model))
                for model in models:
                    try:
                        r = requests.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {GROQ_API_KEY}",
                                "Content-Type": "application/json"
                            },
                            json={
                                "model": model,
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
                        else:
                            logger.warning(
                                f"⚠️ Groq model={model} error: "
                                f"{r.status_code} - {r.text[:200]}"
                            )
                            # لا نكرر الطلب على بقية النماذج بعد 429؛
                            # الحد غالباً يخص المؤسسة/المفتاح وليس النموذج.
                            if r.status_code == 429:
                                groq_blocked = True
                                provider_failures.append("تجاوز حد Groq")
                                return None
                            if r.status_code in (401, 403):
                                groq_blocked = True
                                provider_failures.append(
                                    "مفتاح Groq غير صالح أو غير مصرح"
                                )
                                break
                    except Exception as e:
                        logger.warning(f"⚠️ Groq model={model} exception: {e}")
                return None
            
            result = await asyncio.to_thread(_groq_request)
            if result:
                logger.info(f"🤖 Groq → '{result[:30]}...'")
                return result
            logger.warning("⚠️ Groq فشل، جارٍ الانتقال إلى DeepSeek...")
        
        # ── المحاولة 2: DeepSeek (احتياطي) ──
        if DEEPSEEK_API_KEY and not deepseek_blocked:
            def _deepseek_request():
                nonlocal deepseek_blocked, ai_request_attempted
                ai_request_attempted = True
                try:
                    r = requests.post(
                        "https://api.deepseek.com/chat/completions",
                        headers={
                            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": "deepseek-chat",
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
                    else:
                        logger.warning(f"⚠️ DeepSeek error: {r.status_code} - {r.text[:200]}")
                        if r.status_code == 429:
                            deepseek_blocked = True
                            provider_failures.append("تجاوز حد DeepSeek")
                        elif r.status_code in (401, 403):
                            deepseek_blocked = True
                            provider_failures.append(
                                "مفتاح DeepSeek غير صالح أو غير مصرح"
                            )
                except Exception as e:
                    logger.warning(f"⚠️ DeepSeek exception: {e}")
                return None
            
            result = await asyncio.to_thread(_deepseek_request)
            if result:
                logger.info(f"🤖 DeepSeek → '{result[:30]}...'")
                return result
            logger.warning("⚠️ DeepSeek فشل أيضاً!")
        
        return None

    # ════════════════════════════════════════════════════════════
    # 🔥 _solve_image: يستخدم Groq Vision
    # ════════════════════════════════════════════════════════════
    async def _solve_image(prompt: str, img_bytes: bytes) -> str | None:
        """يحل صور الكابتشا باستخدام Groq Vision."""
        
        GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
        
        # لا تثبّت موديل الرؤية على اسم واحد؛ أسماء/توافر موديلات Groq
        # تختلف بين المفاتيح، وكان هذا سبباً في أن مسار الصورة لا يرجع
        # إجابة حتى مع وجود GROQ_API_KEY.
        if GROQ_API_KEY and not groq_blocked:
            def _groq_vision_request():
                nonlocal groq_blocked, ai_request_attempted
                ai_request_attempted = True
                try:
                    import base64
                    img_b64 = base64.b64encode(img_bytes).decode()
                    headers = {
                        "Authorization": f"Bearer {GROQ_API_KEY}",
                        "Content-Type": "application/json",
                    }

                    configured = os.environ.get("GROQ_VISION_MODEL", "").strip()
                    preferred = [
                        "meta-llama/llama-4-scout-17b-16e-instruct",
                        "meta-llama/llama-4-maverick-17b-128e-instruct",
                        "llama-3.2-90b-vision-preview",
                        "llama-3.2-11b-vision-preview",
                    ]
                    discovered = []
                    try:
                        model_response = requests.get(
                            "https://api.groq.com/openai/v1/models",
                            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                            timeout=10,
                        )
                        if model_response.status_code == 200:
                            discovered = [
                                item.get("id", "")
                                for item in model_response.json().get("data", [])
                                if item.get("id")
                            ]
                    except Exception as model_error:
                        logger.debug(f"تعذر اكتشاف موديلات Groq للرؤية: {model_error}")

                    # نرسل فقط إلى موديلات الرؤية المتاحة فعلياً إن نجح
                    # /models، مع إبقاء الاسم المخصص للمستخدم في البداية.
                    if discovered:
                        discovered_set = set(discovered)
                        available_vision = [
                            model for model in discovered
                            if any(token in model.lower() for token in ("vision", "scout", "maverick"))
                        ]
                        models = [
                            model for model in [configured] + preferred + available_vision
                            if model and (model == configured or model in discovered_set)
                        ]
                    else:
                        models = [model for model in [configured] + preferred if model]
                    models = list(dict.fromkeys(models))

                    for model in models:
                        r = requests.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers=headers,
                            json={
                                "model": model,
                                "messages": [{
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": prompt},
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": f"data:image/jpeg;base64,{img_b64}"
                                            },
                                        },
                                    ],
                                }],
                                "max_tokens": 40,
                                "temperature": 0,
                            },
                            timeout=35,
                        )
                        if r.status_code == 200:
                            data = r.json()
                            if data.get("choices"):
                                return (
                                    data["choices"][0]["message"].get("content", "")
                                    .strip()
                                )

                        logger.warning(
                            f"⚠️ Groq Vision model={model} error: "
                            f"{r.status_code} - {r.text[:200]}"
                        )
                        if r.status_code == 429:
                            groq_blocked = True
                            provider_failures.append("تجاوز حد Groq")
                            return None
                        if r.status_code in (401, 403):
                            groq_blocked = True
                            provider_failures.append(
                                "مفتاح Groq غير صالح أو غير مصرح"
                            )
                            return None
                except Exception as e:
                    logger.warning(f"⚠️ Groq Vision exception: {e}")
                return None
            
            result = await asyncio.to_thread(_groq_vision_request)
            if result:
                return result
        
        return None

    def _is_success(text: str) -> bool:
        t = (text or "").lower()
        return any(k.lower() in t for k in SUCCESS_KW)

    def _is_fail(text: str) -> bool:
        t = (text or "").lower()
        return any(k.lower() in t for k in FAIL_KW)

    def _extract_emojis_from_text(text: str) -> list:
        """يستخرج الإيموجيات كعناقيد، لا كحروف منفردة.

        ``FE0F`` (variation selector) وskin-tone modifier ليسا إيموجي
        مستقلين. إرجاعهما كعنصر مستقل كان يجعل ``❤️`` يُقرأ أحياناً على
        أنه ``️``، وبالتالي يفشل التطابق مع زر الإيموجي.
        """
        result = []
        current = []

        def _flush():
            if current:
                result.append("".join(current))
                current.clear()

        for ch in str(text or ""):
            cp = ord(ch)
            is_base = (
                0x1F000 <= cp <= 0x1FAFF
                or 0x2600 <= cp <= 0x27BF
                or cp in {0x3030, 0x303D, 0x3297, 0x3299}
            ) and not (0x1F3FB <= cp <= 0x1F3FF)
            is_extend = (
                cp in {0xFE0E, 0xFE0F, 0x200D, 0x20E3}
                or 0x1F3FB <= cp <= 0x1F3FF
            )
            if is_base:
                if current and current[-1] != "\u200d":
                    _flush()
                current.append(ch)
            elif is_extend and current:
                current.append(ch)
            else:
                _flush()
        _flush()
        return result

    def _emoji_signatures(text: str) -> set[str]:
        """يبني بصمات للإيموجي مع وبدون variation selector/modifier.

        أزرار تيليغرام قد تصل بصيغة مختلفة عن النص الذي يرجعه النموذج:
        مثلاً ``👍`` مقابل ``👍️`` أو ``👍🏻``. المقارنة بحرف واحد فقط
        كانت تفشل مع هذه الحالات وتضغط أحياناً على زر غير مقصود.
        """
        raw = "".join(_extract_emojis_from_text(text or ""))
        if not raw:
            return set()
        signatures = {raw}
        stripped = "".join(
            ch for ch in raw
            if ord(ch) not in {0xFE0E, 0xFE0F, 0x200D}
            and not (0x1F3FB <= ord(ch) <= 0x1F3FF)
        )
        if stripped:
            signatures.add(stripped)
        signatures.update(_extract_emojis_from_text(text or ""))
        return signatures

    def _custom_emoji_ids(value) -> list[int]:
        """يستخرج document_id للإيموجيات المدفوعة من كائن تيليغرام."""
        result = []
        for entity in getattr(value, "entities", None) or []:
            document_id = getattr(entity, "document_id", None)
            if document_id is None:
                continue
            # لا نعتمد على اسم الصنف فقط حتى يعمل الكود مع إصدارات
            # Telethon التي تضيف حقولاً جديدة أو تغيّر طريقة العرض.
            if "CustomEmoji" in type(entity).__name__:
                try:
                    result.append(int(document_id))
                except (TypeError, ValueError):
                    pass
        return result

    def _button_custom_emoji_id(button) -> int | None:
        """يقرأ أيقونة custom emoji المدفوعة من KeyboardButtonStyle."""
        candidates = [button, getattr(button, "button", None)]
        for candidate in candidates:
            style = getattr(candidate, "style", None)
            icon = getattr(style, "icon", None)
            if icon is not None:
                try:
                    return int(icon)
                except (TypeError, ValueError):
                    return None
        return None

    def _choose_button_by_custom_emoji(
        custom_ids: list[int],
        entries: list[tuple[str, object]],
    ):
        """يطابق target document_id مع أيقونة الزر، دون الاعتماد على Unicode."""
        wanted = {int(value) for value in (custom_ids or []) if value is not None}
        if not wanted:
            return None
        matches = [
            button for _label, button in entries
            if _button_custom_emoji_id(button) in wanted
        ]
        return matches[0] if len(matches) == 1 else None

    def _normalise_button_label(value: str) -> str:
        import unicodedata
        value = unicodedata.normalize("NFKC", str(value or "")).casefold()
        value = "".join(
            ch for ch in value
            if not unicodedata.category(ch).startswith(("C", "M"))
        )
        return " ".join(value.split()).strip()

    def _button_entries(message) -> list[tuple[str, object]]:
        """يُرجع أزرار الرسالة مع الحفاظ على التكرار وترتيبها."""
        entries = []
        for row in getattr(message, "buttons", None) or []:
            for button in row or []:
                label = getattr(button, "text", "") or ""
                url = getattr(button, "url", "") or ""
                # روابط القنوات/الدعوات ليست إجابات كابتشا.
                if url and ("t.me/" in url or "telegram.me/" in url):
                    continue
                # Custom emoji buttons may have an empty text label; their
                # actual visible icon is stored in KeyboardButtonStyle.icon.
                if label or _button_custom_emoji_id(button) is not None:
                    entries.append((str(label).strip(), button))
        return entries

    def _choose_button(answer: str, entries: list[tuple[str, object]]):
        """يطابق إجابة AI مع زر واحد فقط، مع دعم emoji المركب."""
        answer = str(answer or "").strip()
        if not answer or answer.casefold() in {"none", "null", "no match", "لا يوجد"}:
            return None

        answer_norm = _normalise_button_label(answer)
        exact = [
            button for label, button in entries
            if _normalise_button_label(label) == answer_norm
        ]
        if len(exact) == 1:
            return exact[0]

        answer_emojis = _emoji_signatures(answer)
        if answer_emojis:
            emoji_matches = [
                button for label, button in entries
                if answer_emojis.intersection(_emoji_signatures(label))
            ]
            if len(emoji_matches) == 1:
                return emoji_matches[0]
            # إذا وُجدت بصمة كاملة، استخدمها قبل بصمات الحروف المفردة.
            for signature in answer_emojis:
                complete = [
                    button for label, button in entries
                    if signature in _emoji_signatures(label)
                ]
                if len(complete) == 1:
                    return complete[0]

        # For icon-only paid buttons the vision/text provider may return the
        # button number instead of an empty label.
        import re as _re
        number_match = _re.fullmatch(
            r"(?:button|option|زر|خيار)?\s*([1-9]\d*)",
            answer.casefold(),
        )
        if number_match:
            index = int(number_match.group(1)) - 1
            if 0 <= index < len(entries):
                return entries[index][1]

        # المطابقة النصية الاحتياطية لا تُستخدم إلا إذا كانت النتيجة وحيدة؛
        # هذا يمنع اختيار أول زر عندما يعيد النموذج شرحاً طويلاً.
        partial = [
            button for label, button in entries
            if answer_norm
            and (answer_norm in _normalise_button_label(label)
                 or _normalise_button_label(label) in answer_norm)
        ]
        return partial[0] if len(partial) == 1 else None

    def _caption_target_emoji(text: str) -> str | None:
        """يستخرج الإيموجي المطلوب عندما يكون مذكوراً صراحة في الكابتشن."""
        lowered = (text or "").casefold()
        markers = (
            "correct emoji:", "select emoji", "choose emoji", "pick emoji",
            "اختر الإيموجي", "الإيموجي الصحيح", "الإيموجي المطابق",
            "الصورة المطابقة",
        )
        for marker in markers:
            position = lowered.find(marker.casefold())
            if position >= 0:
                emojis = _extract_emojis_from_text(text[position + len(marker):])
                if emojis:
                    return emojis[-1]
        return None

    def _target_custom_emoji_ids(message, text: str) -> list[int]:
        """يحدد custom emoji المطلوب من نص التحقق، وغالباً يكون آخر entity."""
        custom_ids = _custom_emoji_ids(message)
        if not custom_ids:
            return []
        lowered = (text or "").casefold()
        target_markers = (
            "الرمز", "الإيموجي الصحيح", "الإيموجي المطابق",
            "correct emoji", "select emoji", "choose emoji",
            "pick emoji", "matching emoji",
        )
        if any(marker.casefold() in lowered for marker in target_markers):
            return [custom_ids[-1]]
        return custom_ids[-1:]

    async def _wait_and_check(limit: int = 5) -> tuple:
        """ينتظر الرد الجديد فقط لتجنب اعتبار رسائل التحقق القديمة فشلاً."""
        last_msgs = []
        for _ in range(5):
            await asyncio.sleep(2)
            last_msgs = await client.get_messages(bot_entity, limit=limit)
            # تيليغرام يعيد الأحدث أولاً؛ افحص أحدث الرسائل فقط.
            recent_msgs = last_msgs[:5]
            for m in recent_msgs:
                t = getattr(m, "message", "") or getattr(m, "text", "") or ""
                if _is_success(t):
                    return "success", last_msgs
            # الفشل لا يُستنتج من غياب كلمة نجاح؛ لا نعتمده إلا بعبارة صريحة.
            for m in recent_msgs:
                t = getattr(m, "message", "") or getattr(m, "text", "") or ""
                if _is_fail(t):
                    return "fail", last_msgs
            # بعض بوتات التحقق تعدّل/تحذف رسالة الزر وتستبدلها برسالة
            # إتمام بلا كلمة نجاح. إذا اختفت أزرار رسالة التحقق التي عالجناها،
            # فهذا هو دليل الانتقال المطلوب ويُحسب نجاحًا.
            for m in recent_msgs:
                mid = getattr(m, "id", None)
                t = getattr(m, "message", "") or getattr(m, "text", "") or ""
                if mid in processed_ids and not getattr(m, "buttons", None):
                    return "success", last_msgs
            # إذا حُذفت رسالة الزر وظهرت رسالة جديدة من البوت بلا أزرار،
            # نعدّ تبدّل التدفق نجاحًا ما لم توجد عبارة فشل صريحة.
            if processed_ids and any(
                getattr(m, "id", None) not in processed_ids
                and (getattr(m, "message", "") or getattr(m, "text", ""))
                and not getattr(m, "buttons", None)
                for m in recent_msgs
            ):
                return "success", last_msgs
        return "unknown", last_msgs

    all_details: list[str] = []
    processed_ids: set[int] = set()
    replied_numeric_codes: set[str] = set()

    def _extract_numeric_code(messages: list) -> str | None:
        """يستخرج رمز التحقق الرقمي الذي يرسله البوت بعد زر التحقق."""
        code_markers = (
            "رقم التحقق", "رمز التحقق", "أرسل الكود", "ارسل الكود",
            "أدخل الكود", "ادخل الكود", "الكود", "رمز",
            "verification code", "verify code", "code is", "code:",
        )
        trans = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        for item in messages or []:
            text = getattr(item, "message", "") or getattr(item, "text", "") or ""
            if not any(marker in text.casefold() for marker in code_markers):
                continue
            normalized = text.translate(trans)
            found = re.findall(r"(?<!\d)\d{4,8}(?!\d)", normalized)
            if found:
                return found[-1]
        return None

    async def _reply_to_numeric_code(messages: list):
        code = _extract_numeric_code(messages)
        if not code or code in replied_numeric_codes:
            return None, messages
        replied_numeric_codes.add(code)
        logger.info(f"🔢 تم اكتشاف رمز تحقق رقمي ({phone}) — سيتم إرساله للبوت")
        await asyncio.sleep(1)
        await client.send_message(bot_entity, code)
        # التسلسل المطلوب لبعض بوتات التحقق: زر التحقق ثم الرمز ثم /start مجدداً.
        await asyncio.sleep(1)
        await client(StartBotRequest(
            bot=bot_entity,
            peer=bot_entity,
            start_param='',
        ))
        return await _wait_and_check()


    # ── حلقة المحاولات (تدعم تحقق متعدد المراحل) ─────────────
    for _round in range(max_attempts):
        logger.info(f"🔄 محاولة حل الكابتشا {_round+1}/{max_attempts} للرقم {phone}")

        # بعض البوتات ترسل رمزاً فور ضغط زر «إضغط هنا للتحقق».
        # افحص الرمز قبل تحليل أي كابتشا أخرى، ثم أعد إرساله لنفس البوت.
        _numeric_result, _numeric_msgs = await _reply_to_numeric_code(msgs)
        if _numeric_result is not None:
            msgs = _numeric_msgs
            all_details.append("إعادة إرسال رمز التحقق")
            if _numeric_result == "success":
                return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"

        if _round > 0:
            await asyncio.sleep(4)
            msgs = await client.get_messages(bot_entity, limit=15)

        for msg in msgs:
            msg_id = getattr(msg, "id", 0)
            if msg_id in processed_ids:
                continue

            msg_text       = getattr(msg, "message", "") or getattr(msg, "text", "") or ""
            msg_text_lower = msg_text.lower()
            has_photo      = bool(getattr(msg, "photo", None))
            has_doc        = bool(getattr(msg, "document", None))
            has_media      = has_photo or has_doc
            has_btns       = bool(msg.buttons)
            has_poll       = bool(getattr(msg, "poll", None))

            # اكتشاف نجاح مبكر — إذا وصلنا رسالة ترحيب بعد حل سابق
            if _is_success(msg_text) and all_details:
                logger.info(f"✅ تم حل الكابتشا للرقم {phone} في المحاولة {_round+1}")
                return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"

            # ════════════════════════════════════════════════════
            # 1. كابتشا صورة (CAPTCHA بصورة مشوّهة)
            # ════════════════════════════════════════════════════
            # إذا احتوت الصورة على سؤال بصري وأزرار إجابة، فلا ترسل
            # الصورة إلى OCR كنص. هذا هو شكل كابتشا الإيموجي/الصورة
            # المطابقة: الصورة هي السؤال والأزرار هي الإجابات.
            if has_media and has_btns:
                button_entries = _button_entries(msg)
                button_labels = [label for label, _button in button_entries]
                button_text = " ".join(button_labels).casefold()
                icon_button_count = sum(
                    _button_custom_emoji_id(button) is not None
                    for _label, button in button_entries
                )
                all_emoji_buttons = bool(button_labels) and all(
                    bool(_emoji_signatures(label)) for label in button_labels
                )
                is_visual_button_captcha = (
                    bool(button_entries)
                    and (
                        any(k in msg_text_lower for k in CAPTCHA_KW)
                        or any(k in msg_text_lower for k in REACTION_KW)
                        or "select" in msg_text_lower
                        or "choose" in msg_text_lower
                        or "click" in msg_text_lower
                        or "press" in msg_text_lower
                        or "pick" in msg_text_lower
                        or all_emoji_buttons
                        or icon_button_count >= 2
                        or any(k in button_text for k in ("emoji", "إيموجي", "صورة"))
                    )
                )
                if is_visual_button_captcha:
                    try:
                        target_custom_ids = _target_custom_emoji_ids(msg, msg_text)
                        target_emoji = _caption_target_emoji(msg_text)
                        answer = target_emoji
                        chosen = _choose_button_by_custom_emoji(
                            target_custom_ids, button_entries
                        )
                        if not chosen:
                            chosen = _choose_button(answer, button_entries)

                        img_bytes = await client.download_media(msg, bytes)
                        if img_bytes and not chosen:
                            button_descriptions = []
                            for index, (label, button) in enumerate(button_entries, 1):
                                icon_id = _button_custom_emoji_id(button)
                                suffix = (
                                    f"custom emoji icon id={icon_id}"
                                    if icon_id is not None else "text button"
                                )
                                button_descriptions.append(
                                    f"{index}. {label or '(icon only)'} [{suffix}]"
                                )
                            prompt = (
                                "This is a visual Telegram CAPTCHA. "
                                "The image is the challenge and the following are "
                                "the exact answer-button labels:\n"
                                + "\n".join(button_descriptions)
                                + "\n\n"
                                "Inspect the image and select the one button that "
                                "matches the emoji, symbol, object, or picture shown. "
                                "If the image shows an emoji, compare it with the "
                                "emoji buttons. Do not solve it as OCR. "
                                "Return ONLY the exact button label, with no explanation. "
                                "Return NONE if no button can be matched.\n"
                                f"Message text: {msg_text or '(none)'}"
                            )
                            answer = await _solve_image(prompt, img_bytes)
                            chosen = _choose_button(answer, button_entries)

                        if not chosen:
                            logger.warning(
                                f"⚠️ لم يُعثر على زر يطابق الصورة/الإيموجي "
                                f"({phone}) — إجابة AI: {answer!r}"
                            )
                            all_details.append("لم يتم الضغط: لا يوجد زر مطابق للصورة")
                            continue

                        processed_ids.add(msg_id)
                        await chosen.click()
                        result, msgs = await _wait_and_check()
                        if result == "unknown":
                            numeric_result, numeric_msgs = await _reply_to_numeric_code(msgs)
                            if numeric_result is not None:
                                result, msgs = numeric_result, numeric_msgs
                        detail = (
                            f"ضغط زر الصورة/الإيموجي: "
                            f"{getattr(chosen, 'text', '')}"
                        )
                        all_details.append(detail)
                        logger.info(
                            f"🤖 AI visual button → {getattr(chosen, 'text', '')!r} "
                            f"({phone})"
                        )
                        if result == "success":
                            logger.info(
                                f"✅ تم حل الكابتشا للرقم {phone} "
                                f"في المحاولة {_round+1}"
                            )
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        if result == "fail":
                            break
                        return True, f"ضغط الزر | {' | '.join(all_details)}"
                    except Exception as _e:
                        logger.warning(
                            f"⚠️ AI visual image/button captcha ({phone}): {_e}"
                        )
                    continue

            if has_media:
                try:
                    img_bytes = await client.download_media(msg, bytes)
                    if not img_bytes:
                        continue
                    prompt = (
                        "هذه صورة كابتشا (CAPTCHA) من بوت تيليغرام.\n"
                        f"النص المرافق للصورة: {msg_text or '(لا يوجد)'}\n\n"
                        "اقرأ بدقة النص أو الأرقام الظاهرة في الصورة وأجب بها فقط "
                        "بدون أي شرح أو مسافات إضافية."
                    )
                    answer = await _solve_image(prompt, img_bytes)
                    if answer:
                        logger.info(f"🤖 AI كابتشا صورة → '{answer}' ({phone})")
                        processed_ids.add(msg_id)
                        await asyncio.sleep(1)
                        await client.send_message(bot_entity, answer)
                        result, msgs = await _wait_and_check()
                        if result == "unknown":
                            numeric_result, numeric_msgs = await _reply_to_numeric_code(msgs)
                            if numeric_result is not None:
                                result, msgs = numeric_result, numeric_msgs
                        detail = f"كابتشا صورة: {answer}"
                        all_details.append(detail)
                        if result == "success":
                            logger.info(f"✅ تم حل الكابتشا للرقم {phone} في المحاولة {_round+1}")
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result == "fail":
                            break  # حاول في الجولة التالية
                        else:
                            return True, f"أُرسلت إجابة الصورة | {' | '.join(all_details)}"
                except Exception as _e:
                    logger.warning(f"⚠️ AI image captcha ({phone}): {_e}")
                continue

            # ════════════════════════════════════════════════════
            # 2. مشاركة ملف شخصي / Contact
            # ════════════════════════════════════════════════════
            if any(k in msg_text_lower for k in FORWARD_KW):
                try:
                    from telethon.tl.types import InputMediaContact
                    me    = await client.get_me()
                    first = getattr(me, "first_name", "") or ""
                    last  = getattr(me, "last_name",  "") or ""
                    ph    = getattr(me, "phone",      "") or phone.lstrip("+")
                    if not ph.startswith("+"):
                        ph = "+" + ph
                    logger.info(f"🤖 AI مشاركة ملف شخصي ({phone})")
                    processed_ids.add(msg_id)
                    await client.send_file(
                        bot_entity,
                        InputMediaContact(
                            phone_number=ph,
                            first_name=first,
                            last_name=last,
                            vcard="",
                        ),
                    )
                    result, msgs = await _wait_and_check()
                    if result == "unknown":
                        numeric_result, numeric_msgs = await _reply_to_numeric_code(msgs)
                        if numeric_result is not None:
                            result, msgs = numeric_result, numeric_msgs
                    detail = "شارك ملفه الشخصي (Contact)"
                    all_details.append(detail)
                    if result == "success":
                        logger.info(f"✅ تم حل الكابتشا للرقم {phone} في المحاولة {_round+1}")
                        return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                    elif result != "fail":
                        return True, f"أُرسل الملف الشخصي | {' | '.join(all_details)}"
                    continue
                except Exception as _e:
                    logger.warning(f"⚠️ AI forward profile ({phone}): {_e}")

            # ════════════════════════════════════════════════════
            # 3. Poll / Quiz (اختبار متعدد الخيارات)
            # ════════════════════════════════════════════════════
            if has_poll:
                try:
                    poll_obj = msg.poll.poll
                    question = getattr(poll_obj, "question", "") or ""
                    answers  = [getattr(a, "text", "") for a in (getattr(poll_obj, "answers", []) or [])]
                    if question and answers:
                        prompt = (
                            f"بوت تيليغرام يطرح اختباراً:\nالسؤال: {question}\n"
                            "الخيارات:\n" + "\n".join(f"{i+1}. {a}" for i, a in enumerate(answers)) + "\n\n"
                            "أي خيار هو الصحيح؟ أجب برقم الخيار فقط (1، 2، 3...)."
                        )
                        ai_ans = await _solve_text(prompt)
                        chosen_idx = None
                        if ai_ans:
                            # لا تضغط خياراً افتراضياً إذا لم تكن إجابة الذكاء واضحة.
                            nums = re.findall(r"\d+", ai_ans)
                            if nums:
                                candidate = int(nums[0]) - 1
                                if 0 <= candidate < len(answers):
                                    chosen_idx = candidate
                            else:
                                # مطابقة نصية بعد تنظيف الإجابة.
                                answer_text = ai_ans.strip().lower()
                                for i, a in enumerate(answers):
                                    if answer_text == a.strip().lower() or answer_text in a.lower():
                                        chosen_idx = i
                                        break
                        if chosen_idx is None:
                            all_details.append("تعذر تحديد إجابة الاختبار")
                            logger.warning(f"⚠️ لم يحدد الذكاء إجابة Poll صالحة ({phone})")
                            continue
                        processed_ids.add(msg_id)
                        await msg.click(chosen_idx)
                        result, msgs = await _wait_and_check()
                        if result == "unknown":
                            numeric_result, numeric_msgs = await _reply_to_numeric_code(msgs)
                            if numeric_result is not None:
                                result, msgs = numeric_result, numeric_msgs
                        detail = f"أجاب Poll: {answers[chosen_idx]}"
                        all_details.append(detail)
                        logger.info(f"🤖 AI Poll → '{answers[chosen_idx]}' ({phone})")
                        if result == "success":
                            logger.info(f"✅ تم حل الكابتشا للرقم {phone} في المحاولة {_round+1}")
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result != "fail":
                            return True, f"أجاب على اختبار | {' | '.join(all_details)}"
                        else:
                            # اسمح بإعادة معالجة نفس الاختبار بعد إجابة خاطئة.
                            processed_ids.discard(msg_id)
                        continue
                except Exception as _e:
                    logger.warning(f"⚠️ AI poll captcha ({phone}): {_e}")

            # ════════════════════════════════════════════════════
            # 4. أزرار اختيار (كابتشا أزرار / إيموجي / خيارات)
            # ════════════════════════════════════════════════════
            if has_btns:
                try:
                    button_entries = _button_entries(msg)
                    btn_labels = [label for label, _button in button_entries]
                    icon_button_count = sum(
                        _button_custom_emoji_id(button) is not None
                        for _label, button in button_entries
                    )
                    if not button_entries:
                        continue
                    # هل تبدو رسالة تحقق؟ (تحقق، رياضيات، إيموجي...)
                    is_verif = (
                        any(k in msg_text_lower for k in CAPTCHA_KW)
                        or any(k in msg_text_lower for k in MATH_KW)
                        or any(k in msg_text_lower for k in REACTION_KW)
                        or "select" in msg_text_lower
                        or "choose" in msg_text_lower
                        or "click" in msg_text_lower
                        or "press" in msg_text_lower
                        or "pick" in msg_text_lower
                        # بعض كابتشا الإيموجي المدفوعة تصل بأزرار فقط بلا نص دال.
                        or (
                            len(btn_labels) >= 2
                            and all(bool(_emoji_signatures(lbl)) for lbl in btn_labels)
                        )
                        or icon_button_count >= 2
                    )
                    if not is_verif:
                        continue

                    # ── كشف مباشر: نمط "select the correct emoji: X" ──────
                    target_custom_ids = _target_custom_emoji_ids(msg, msg_text)
                    target_emoji = _caption_target_emoji(msg_text)
                    direct_chosen = _choose_button_by_custom_emoji(
                        target_custom_ids, button_entries
                    )
                    if not direct_chosen:
                        direct_chosen = _choose_button(target_emoji, button_entries)
                    # نمط: "correct emoji: X" أو "اختر الإيموجي: X" أو "select emoji X"
                    is_emoji_select = (
                        "correct emoji" in msg_text_lower
                        or "select emoji" in msg_text_lower
                        or "choose emoji" in msg_text_lower
                        or "pick emoji" in msg_text_lower
                        or "اختر الإيموجي" in msg_text
                        or "الإيموجي الصحيح" in msg_text
                        or "الإيموجي المطابق" in msg_text
                        or "الصورة المطابقة" in msg_text
                    )
                    if is_emoji_select:
                        # لا تضغط على None؛ عند غياب التطابق يكمل المسار الاحتياطي.
                        if direct_chosen:
                            processed_ids.add(msg_id)
                            await direct_chosen.click()
                            result, msgs = await _wait_and_check()
                            if result == "unknown":
                                numeric_result, numeric_msgs = await _reply_to_numeric_code(msgs)
                                if numeric_result is not None:
                                    result, msgs = numeric_result, numeric_msgs
                            detail = f"ضغط إيموجي مباشر: {getattr(direct_chosen, 'text', '')}"
                            all_details.append(detail)
                            if result == "success":
                                return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                            elif result == "fail":
                                break  # حاول مجدداً
                    else:
                        # ── الوضع الاحتياطي: استخدم Groq أو DeepSeek ─────────
                        # إذا كانت الأزرار كلها إيموجيات، وضّح ذلك للنموذج
                        button_descriptions = []
                        for index, (label, button) in enumerate(button_entries, 1):
                            icon_id = _button_custom_emoji_id(button)
                            suffix = (
                                f"custom emoji icon id={icon_id}"
                                if icon_id is not None else "text button"
                            )
                            button_descriptions.append(
                                f"{index}. {label or '(icon only)'} [{suffix}]"
                            )
                        all_emoji_btns = all(
                            bool(_emoji_signatures(lbl)) for lbl in btn_labels
                        ) and bool(btn_labels)
                        all_paid_icon_btns = all(
                            _button_custom_emoji_id(button) is not None
                            for _label, button in button_entries
                        )
                        if all_emoji_btns:
                            prompt = (
                                f"Telegram bot verification:\n{msg_text}\n\n"
                                "Available emoji buttons:\n"
                                + "\n".join(button_descriptions)
                                + "\n\nWhich emoji button should be clicked? "
                                "Reply with ONLY the exact emoji character or its "
                                "button number, nothing else."
                            )
                        elif all_paid_icon_btns:
                            prompt = (
                                f"Telegram bot verification:\n{msg_text}\n\n"
                                "Available paid custom-emoji buttons:\n"
                                + "\n".join(button_descriptions)
                                + "\n\nChoose the button whose custom emoji matches "
                                "the custom emoji in the verification text. Reply with "
                                "ONLY its button number, nothing else."
                            )
                        else:
                            prompt = (
                                f"بوت تيليغرام يطلب التحقق:\n{msg_text}\n\n"
                                "الأزرار المتاحة:\n"
                                + "\n".join(button_descriptions)
                                + "\n\nأي زر يجب الضغط عليه؟ أجب برقم الزر أو نصه "
                                "فقط كما هو بالضبط."
                            )
                        answer = await _solve_text(prompt)
                        if answer:
                            logger.info(f"🤖 AI اختار زر → '{answer}' ({phone})")
                            chosen = _choose_button(answer, button_entries)
                            if not chosen:
                                # Never guess: paid/custom-emoji captchas need a confirmed visual/ID match.
                                logger.warning(f"⚠️ لا يوجد تطابق مؤكد لزر الكابتشا — لن يتم الضغط ({phone})")
                                all_details.append("لم يتم الضغط: لا يوجد تطابق مؤكد")
                                continue
                            processed_ids.add(msg_id)
                            await chosen.click()
                            result, msgs = await _wait_and_check()
                            if result == "unknown":
                                numeric_result, numeric_msgs = await _reply_to_numeric_code(msgs)
                                if numeric_result is not None:
                                    result, msgs = numeric_result, numeric_msgs
                            detail = f"ضغط زر: {getattr(chosen, 'text', '')}"
                            all_details.append(detail)
                            if result == "success":
                                logger.info(f"✅ تم حل الكابتشا للرقم {phone} في المحاولة {_round+1}")
                                return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                            elif result == "fail":
                                break  # حاول مجدداً
                            else:
                                return True, f"ضغط الزر | {' | '.join(all_details)}"
                except Exception as _e:
                    logger.warning(f"⚠️ AI button captcha ({phone}): {_e}")
                continue

            # ════════════════════════════════════════════════════
            # 5. سؤال نصي / رياضي / إيموجي كرسالة نصية
            # ════════════════════════════════════════════════════
            if msg_text and not has_btns and not has_media and not has_poll:
                is_captcha_q = any(k in msg_text_lower for k in CAPTCHA_KW)
                is_math_q    = any(k in msg_text_lower for k in MATH_KW)
                is_react_q   = any(k in msg_text_lower for k in REACTION_KW)
                if not (is_captcha_q or is_math_q or is_react_q):
                    continue
                try:
                    prompt = (
                        f"بوت تيليغرام يطرح هذا السؤال للتحقق:\n{msg_text}\n\n"
                        "أجب بالرقم أو النص أو الإيموجي المطلوب فقط "
                        "بدون أي شرح أو رموز إضافية. إذا كان السؤال رياضياً أجب بالرقم فقط."
                    )
                    answer = await _solve_text(prompt)
                    if answer:
                        logger.info(f"🤖 AI سؤال نصي → '{answer}' ({phone})")
                        processed_ids.add(msg_id)
                        await asyncio.sleep(1)
                        await client.send_message(bot_entity, answer)
                        result, msgs = await _wait_and_check()
                        if result == "unknown":
                            numeric_result, numeric_msgs = await _reply_to_numeric_code(msgs)
                            if numeric_result is not None:
                                result, msgs = numeric_result, numeric_msgs
                        detail = f"أجاب: {answer}"
                        all_details.append(detail)
                        if result == "success":
                            logger.info(f"✅ تم حل الكابتشا للرقم {phone} في المحاولة {_round+1}")
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result == "fail":
                            break  # حاول مجدداً
                        else:
                            return True, f"أُرسلت الإجابة | {' | '.join(all_details)}"
                except Exception as _e:
                    logger.warning(f"⚠️ AI text captcha ({phone}): {_e}")

            # ════════════════════════════════════════════════════
            # 6. ردود فعل Reactions (البوت يطلب تفاعلاً على رسالة)
            # ════════════════════════════════════════════════════
            if any(k in msg_text_lower for k in REACTION_KW):
                try:
                    from telethon.tl.functions.messages import SendReactionRequest
                    from telethon.tl.types import ReactionEmoji
                    prompt = (
                        f"بوت تيليغرام يطلب منك التفاعل:\n{msg_text}\n\n"
                        "ما هو الإيموجي أو التفاعل المطلوب؟ "
                        "أجب بالإيموجي فقط (مثال: 👍 أو ❤️ أو 🔥)."
                    )
                    emoji_answer = await _solve_text(prompt)
                    if emoji_answer:
                        # خذ أول إيموجي فقط
                        emoji_clean = emoji_answer.strip().split()[0]
                        processed_ids.add(msg_id)
                        await client(SendReactionRequest(
                            peer=bot_entity,
                            msg_id=msg_id,
                            reaction=[ReactionEmoji(emoticon=emoji_clean)],
                        ))
                        result, msgs = await _wait_and_check()
                        if result == "unknown":
                            numeric_result, numeric_msgs = await _reply_to_numeric_code(msgs)
                            if numeric_result is not None:
                                result, msgs = numeric_result, numeric_msgs
                        detail = f"تفاعل: {emoji_clean}"
                        all_details.append(detail)
                        logger.info(f"🤖 AI Reaction → '{emoji_clean}' ({phone})")
                        if result == "success":
                            logger.info(f"✅ تم حل الكابتشا للرقم {phone} في المحاولة {_round+1}")
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result != "fail":
                            return True, f"أُرسل التفاعل | {' | '.join(all_details)}"
                except Exception as _e:
                    logger.warning(f"⚠️ AI reaction ({phone}): {_e}")

    # ── النتيجة النهائية ───────────────────────────────────────
    if all_details:
        logger.info(f"ℹ️ تم حل الكابتشا جزئياً للرقم {phone}: {all_details}")
        return True, f"حُلّ جزئياً | {' | '.join(all_details)}"
    
    if provider_failures:
        reason = provider_failures[0]
        logger.warning(
            f"❌ تعذر استخدام مزود التحقق للرقم {phone}: {reason}"
        )
        return False, f"مزود التحقق غير متاح: {reason}"
    if ai_request_attempted:
        logger.warning(
            f"❌ لم يُرجع مزود التحقق إجابة للرقم {phone} "
            f"بعد {max_attempts} محاولات"
        )
        return False, "تعذر الحصول على إجابة من مزود التحقق"

    logger.info(f"ℹ️ لم يُكتشف تحقق للرقم {phone}")
    return False, "لم يُكتشف تحقق"


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
    """يكتشف زر التحقق ويضغطه رغم اختلاف النص وتمثيل Telethon."""
    from telethon.tl.functions.messages import GetBotCallbackAnswerRequest
    import unicodedata

    def _norm(value: str) -> str:
        # لا نعتمد على اسم ثابت للزر: قد يتغير النص أو يكون مخفياً داخل
        # callback_data. نزيل التشكيل ومحارف الاتجاه والـ zero-width أيضاً.
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        value = unicodedata.normalize("NFKC", str(value or ""))
        return "".join(ch for ch in value.casefold() if not unicodedata.category(ch).startswith("M")) \
            .replace("إ", "ا").replace("أ", "ا").replace("آ", "ا") \
            .replace("ٱ", "ا").replace("ى", "ي").replace("ئ", "ي") \
            .replace("ؤ", "و").replace("ة", "ه").replace("ـ", "") \
            .replace("\u200f", "").replace("\u200e", "") \
            .replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")

    # أضفنا مرادفات عامة لأن مالك البوت قد يغيّر العبارة أو يضعها داخل
    # قالب قصير/مشفّر. هذه الكلمات تستخدم للترجيح، وليست شرطاً وحيداً.
    verify_words = tuple(_norm(x) for x in (
        "إضغط هنا للتحقق", "اضغط هنا للتحقق", "اضغط للتحقق",
        "انقر هنا للتحقق", "اضغط على الزر", "اضغط للمتابعة",
        "إضغط", "اضغط", "انقر", "زر",
        "click here to verify", "click to verify", "verify", "check",
        "تحقق", "فحص", "اثبت", "إثبات", "متابعة", "استمرار",
        "لست روبوت", "لست بوت", "أنا بشر", "i am human",
        "i'm human", "not a robot", "robot check", "captcha",
        "تم الاشتراك", "لقد اشتركت",
    ))
    context_words = tuple(_norm(x) for x in (
        "لست روبوت", "لست بوت", "اثبت انك", "اثبت أنك",
        "تحقق من انك", "تحقق من أنك", "بعد التحقق",
        "اضغط على الزر", "اضغط للمتابعة", "للمتابعة",
        "verify you are", "not a robot", "robot check",
        "captcha", "verification", "human check",
    ))
    # سياق الرسالة الظاهر في تدفق البوت الحالي. قد لا تذكر الرسالة
    # كلمة captcha إطلاقاً، لكنها تكون بوضوح شاشة فتح الهدية/الميزات.
    flow_words = tuple(_norm(x) for x in (
        "للحصول على الهدية", "افتح كل ميزات البوت",
        "ستفتح كل ميزات البوت", "اضغط على الزر للمتابعة",
        "الهدية", "ميزات البوت",
    ))
    data_words = tuple(_norm(x) for x in (
        "verify", "verification", "captcha", "check", "human",
        "robot", "confirm", "continue", "start", "join",
        "تحقق", "كابتشا", "روبوت", "بشر", "تاكيد", "تأكيد",
        "متابعة", "استمرار",
    ))

    def _collect_strings(value, output=None, seen=None, depth=0):
        """يجمع كل النصوص من كائن Telethon، بما فيها الحقول المتداخلة."""
        if output is None:
            output = []
        if seen is None:
            seen = set()
        if value is None or depth > 8 or len(output) >= 500:
            return output
        if isinstance(value, bytes):
            # callback_data قد تكون bytes، لكن لا نحاول تحويل الصور أو
            # الملفات الكبيرة إلى نص.
            if len(value) <= 4096:
                output.append(value.decode("utf-8", "replace"))
            return output
        if isinstance(value, str):
            if value.strip():
                output.append(value)
            return output
        if isinstance(value, (int, float, bool)):
            return output
        identity = id(value)
        if identity in seen:
            return output
        seen.add(identity)
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str):
                    output.append(key)
                _collect_strings(item, output, seen, depth + 1)
            return output
        if isinstance(value, (list, tuple, set)):
            for item in value:
                _collect_strings(item, output, seen, depth + 1)
            return output
        try:
            to_dict = getattr(value, "to_dict", None)
            if callable(to_dict):
                _collect_strings(to_dict(), output, seen, depth + 1)
        except Exception:
            pass
        return output

    def _message_text(msg) -> str:
        """يقرأ كل نصوص Message/Media/Markup وليس أول حقل فقط."""
        values = []
        for attr in ("raw_text", "message", "text", "caption", "reply_markup"):
            try:
                _collect_strings(getattr(msg, attr, None), values)
            except Exception:
                pass
        try:
            _collect_strings(msg.to_dict(), values)
        except Exception:
            pass
        # إزالة التكرار مع إبقاء الترتيب، ثم توحيد النص العربي.
        unique = list(dict.fromkeys(
            item for item in values if isinstance(item, str) and item.strip()
        ))
        return _norm("\n".join(unique))

    def _button_parts(btn) -> tuple[str, object]:
        """يدعم Button wrapper و KeyboardButtonCallback الخام معاً."""
        raw = getattr(btn, "button", None) or btn
        text = getattr(raw, "text", None) or getattr(btn, "text", None) or ""
        data = getattr(raw, "data", None)
        if data is None:
            data = getattr(btn, "data", None)
        return _norm(text), data

    for msg in msgs or []:
        # اجمع الأزرار من كل تمثيلات Telethon؛ بعض الإصدارات تعرض
        # reply_markup.rows، وأخرى تعرض inline_keyboard فقط.
        rows = getattr(getattr(msg, "reply_markup", None), "rows", None) or []
        candidates = []
        for ri, row in enumerate(rows):
            for ci, button in enumerate(getattr(row, "buttons", []) or []):
                candidates.append((ri, ci, button))
        if not candidates:
            raw_rows = getattr(getattr(msg, "reply_markup", None), "inline_keyboard", None)
            if raw_rows:
                for ri, row in enumerate(raw_rows):
                    for ci, button in enumerate(row or []):
                        candidates.append((ri, ci, button))
        if not candidates:
            for ri, row in enumerate(getattr(msg, "buttons", []) or []):
                for ci, button in enumerate(row):
                    candidates.append((ri, ci, button))

        msg_text = _message_text(msg)
        captcha_message = (
            any(marker in msg_text for marker in context_words)
            or any(marker in msg_text for marker in flow_words)
        )
        # بعض البوتات تجعل النص قصيراً جداً أو ترسل صورة بلا نص واضح؛
        # وجود عبارة تحقق في أحد الأزرار يكفي عندها لبدء الترجيح.
        message_has_verify_hint = any(word in msg_text for word in verify_words)
        scored = []
        for ri, ci, btn in candidates:
            btn_text, btn_data = _button_parts(btn)
            raw_text = getattr(btn, "text", "") or getattr(
                getattr(btn, "button", None), "text", ""
            ) or btn_text
            data_text = _norm(btn_data)
            if not btn_text and not btn_data:
                continue

            score = 0
            if any(word in btn_text for word in verify_words):
                score += 100
            if any(word in data_text for word in data_words):
                score += 60
            if captcha_message:
                score += 30
            elif message_has_verify_hint:
                score += 15
            # زر callback داخل رسالة تحقق بلا نص/اسم معروف هو آخر احتمال
            # آمن نسبياً، ونقبله فقط إذا احتوت الرسالة نفسها على سياق تحقق.
            if btn_data and captcha_message:
                score += 10
            if score:
                scored.append((score, ri, ci, btn, raw_text, btn_data))

        if not scored:
            if candidates:
                _button_debug = [
                    (
                        _norm(getattr(b, "text", "") or ""),
                        _norm(getattr(b, "data", None)),
                    )
                    for _, _, b in candidates
                ]
                logger.debug(
                    f"🔎 رسالة تحقق بلا تطابق: message_id={getattr(msg, 'id', 0)}, "
                    f"text={msg_text[:180]!r}, "
                    f"buttons={_button_debug!r}"
                )
            continue

        # عند وجود عدة أزرار، لا نضغط أول زر عشوائياً؛ نرتب حسب التطابق
        # النصي ثم callback_data ثم سياق الرسالة.
        scored.sort(key=lambda item: item[0], reverse=True)
        for score, ri, ci, btn, raw_text, btn_data in scored:
            try:
                # Message.click يختار peer الصحيح داخلياً. استعمال
                # msg.peer_id مباشرة قد يفشل مع PeerUser/PeerChannel في
                # بعض إصدارات Telethon، لذلك نجعله fallback فقط.
                if btn_data:
                    try:
                        result = await msg.click(ri, ci)
                    except Exception:
                        peer = getattr(msg, "peer_id", None) or bot_entity
                        result = await client(GetBotCallbackAnswerRequest(
                            peer=peer, msg_id=msg.id, data=btn_data
                        ))
                else:
                    result = await msg.click(ri, ci)
                logger.info(
                    f"✅ نُفّذ ضغط زر التحقق: '{raw_text}' "
                    f"(score={score}, message_id={getattr(msg, 'id', 0)}, "
                    f"callback={btn_data!r}, answer={type(result).__name__})"
                )
                return True
            except Exception as exc:
                # fallback أخير للرسائل التي لا يمكن لـ Message.click
                # تحويل صفوفها إلى فهارس (خصوصاً بعد تحديثات Telethon).
                if btn_data:
                    try:
                        await msg.click(data=btn_data)
                        logger.info(
                            f"✅ نُفّذ ضغط زر التحقق عبر callback_data: "
                            f"'{raw_text}' (score={score}, "
                            f"message_id={getattr(msg, 'id', 0)})"
                        )
                        return True
                    except Exception:
                        pass
                logger.warning(
                    f"⚠️ تعذر ضغط زر كابتشا الإحالة '{raw_text}' "
                    f"(message_id={getattr(msg, 'id', 0)}): {exc}"
                )
    logger.warning("⚠️ لم يُعثر على زر كابتشا مطابق في رسائل البوت")
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
      4. يفحص ردّ البوت: إذا طلب الانضمام لقنوات → ينضم ثم يضغط زر التحقق من الاشتراك
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
            required_count = len(_parse_channel_tokens(mandatory_channels))
            if cnt:
                steps.append(f"انضم لـ {cnt}/{required_count} قناة إجبارية")
            if cnt < required_count:
                return (
                    False,
                    False,
                    f"فشل الاشتراك الإجباري: انضم إلى {cnt}/{required_count} قناة فقط",
                )

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

        # زر كابتشا بوت رشق العرب قد يصل في رسالة متأخرة؛ أعد الفحص عدة مرات.
        # هذا مستقل عن أزرار القنوات وعن مسار الإحالة بدون تحقق.
        _initial_verify_clicked = False
        _any_verify_clicked = False
        for _verify_poll in range(5):
            _initial_verify_clicked = await _click_check_subscription_button(client, bot_entity, msgs)
            if _initial_verify_clicked:
                _any_verify_clicked = True
                await asyncio.sleep(4)
                msgs = await asyncio.wait_for(client.get_messages(bot_entity, limit=20), timeout=10)
                break
            await asyncio.sleep(2)
            msgs = await asyncio.wait_for(client.get_messages(bot_entity, limit=20), timeout=10)

        # ── الخطوة 4: التعامل مع اشتراط البوت الانضمام لقنواته (حلقة متكررة) ──
        # يكرر: انضم للقنوات من ردود البوت → تحقق من الاشتراك → رسائل جديدة
        # يستمر حتى لا توجد قنوات جديدة أو يبلغ الحد الأقصى (6 جولات)
        _total_joined_from_bot = 0
        for _sub_round in range(6):
            joined_channels = await _join_channels_from_buttons(client, msgs)
            if joined_channels == 0:
                break  # لا قنوات جديدة → خروج من الحلقة
            _total_joined_from_bot += joined_channels
            steps.append(f"انضم لـ {joined_channels} قناة من رد البوت (جولة {_sub_round + 1})")
            await asyncio.sleep(2)
            # بعد الانضمام، ابحث عن زر التحقق من الاشتراك واضغطه
            _clicked = await _click_check_subscription_button(client, bot_entity, msgs)
            if _clicked:
                _any_verify_clicked = True
                steps.append(f"ضغط زر التحقق من الاشتراك (جولة {_sub_round + 1})")
            await asyncio.sleep(4)
            # احصل على رسائل جديدة — قد تحتوي على قنوات إضافية تطلبها
            msgs = await asyncio.wait_for(client.get_messages(bot_entity, limit=15), timeout=10)
        if _total_joined_from_bot > 0:
            logger.info(f"🔗 {phone}: انضم إجمالاً لـ {_total_joined_from_bot} قناة من ردود البوت")

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
                    client.get_messages(bot_entity, limit=50), timeout=10
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
                # إذا ضغطنا زر التحقق الأول ثم تبدلت الرسالة ولم تبقَ
                # كابتشا واضحة أو فشل صريح، فالـ AI اللاحق ليس شرطاً
                # للنجاح؛ بعض البوتات تسجل التصويت وتعرض تنبيهاً عاماً.
                _post_verify_text = " ".join(
                    (getattr(_m, "message", "") or getattr(_m, "text", "") or "")
                    for _m in (msgs or [])
                ).casefold()
                _explicit_fail = any(_x in _post_verify_text for _x in (
                    "إجابة خاطئة", "غير صحيح", "حاول مجدداً",
                    "wrong answer", "try again", "captcha failed"
                ))
                _pending_controls = any(
                    getattr(_m, "buttons", None)
                    and any(
                        _k in ((getattr(_m, "message", "") or getattr(_m, "text", "") or "").casefold())
                        for _k in ("captcha", "verification", "تحقق", "كابتشا", "اختر", "اضغط")
                    )
                    for _m in (msgs or [])
                )
                if _initial_verify_clicked and not _explicit_fail and not _pending_controls:
                    steps.append("تم قبول التحقق بعد تبدّل رسالة البوت")
                    logger.info(
                        f"✅ {phone}: تم التصويت وتبدلت رسالة التحقق؛ "
                        "تجاوز فشل AI اللاحق"
                    )
                else:
                    return False, False, f"فشل حل الكابتشا بعد 3 محاولات: {_ai_detail}"
            else:
                # محاولة أخيرة مستقلة عن AI: قد تصل رسالة الزر بعد انتهاء
                # polling السابق أو تكون خارج أول 15 رسالة.
                try:
                    _late_msgs = await asyncio.wait_for(
                        client.get_messages(bot_entity, limit=50), timeout=10
                    )
                    if await _click_check_subscription_button(
                        client, bot_entity, _late_msgs
                    ):
                        _any_verify_clicked = True
                        await asyncio.sleep(4)
                        steps.append("تم ضغط زر التحقق في الفحص المتأخر")
                        logger.info(
                            f"✅ تم العثور على زر التحقق في الفحص المتأخر للرقم {phone}"
                        )
                except Exception as _late_exc:
                    logger.warning(
                        f"⚠️ فشل فحص زر التحقق المتأخر للرقم {phone}: {_late_exc}"
                    )
                # إذا ضغطنا زر التحقق فعلاً ثم لم يظهر تحدٍ جديد، فهذه
                # نتيجة ناجحة حتى لو لم يرسل البوت كلمة "تم التحقق".
                # سابقاً كان هذا المسار يسجل الحساب فاشلاً برسالة مضللة.
                if _any_verify_clicked:
                    steps.append("تم ضغط زر التحقق ولم يظهر تحدٍ إضافي")
                    logger.info(
                        f"✅ اعتُبر التحقق ناجحاً بعد تنفيذ الضغط للرقم {phone}"
                    )
                else:
                    # عدم وجود تحدٍ ليس فشلاً: بعض البوتات لا تعرض تحققاً
                    # لكل إحالة، لكننا تأكدنا من أحدث الرسائل عدة مرات.
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
            " AND raksh_only IS NOT TRUE"
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
    # استخدم كامل الحسابات المتاحة لتعويض الحسابات الفاشلة تلقائياً.
    pool = list(sv_accounts)

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

        # أظهر الانتقال للحساب البديل مباشرة بعد كل محاولة.
        if progress_msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=supervisor_id,
                    message_id=progress_msg_id,
                    text=_progress_text(idx),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

        # عند الفشل انتقل للحساب التالي فوراً؛ الانتظار يبقى بعد النجاح فقط.
        if idx < len(pool) and done + reactivated < quantity and (ok or reactiv):
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
            " AND raksh_only IS NOT TRUE"
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
