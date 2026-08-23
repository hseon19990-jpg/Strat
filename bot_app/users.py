"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

import re
import html
import time
import asyncio

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

def _normalize_desc(desc: str) -> str:
    """يُطبّع الاختصارات الشائعة في أوصاف خدمات SMM إلى العربية.
    K → ألف  |  /D → /يوم  |  /H → /ساعة  |  /W → /أسبوع  |  /M → /شهر
    كما يُصحّح 'كيلوجرام' و'كيلو' المكتوبة بدلاً من 'ألف' خطأً."""
    if not desc:
        return desc

    t = desc

    t = re.sub(r"كيلو\s*جرام", "ألف", t)
    t = re.sub(r"كيلوجرام",     "ألف", t)
    t = re.sub(r"\bكيلو\b",     "ألف", t)

    t = re.sub(r"/\s*(?:day|daily)\b",   "/يوم",    t, flags=re.IGNORECASE)
    t = re.sub(r"/\s*D\b",               "/يوم",    t, flags=re.IGNORECASE)
    t = re.sub(r"\bper\s+day\b",         "يومياً",  t, flags=re.IGNORECASE)

    t = re.sub(r"/\s*(?:hour|hr)\b",     "/ساعة",   t, flags=re.IGNORECASE)
    t = re.sub(r"/\s*H\b",               "/ساعة",   t, flags=re.IGNORECASE)
    t = re.sub(r"\bper\s+hour\b",        "بالساعة", t, flags=re.IGNORECASE)

    t = re.sub(r"/\s*(?:week|wk)\b",     "/أسبوع",  t, flags=re.IGNORECASE)
    t = re.sub(r"/\s*W\b",               "/أسبوع",  t, flags=re.IGNORECASE)

    t = re.sub(r"/\s*(?:month|mo)\b",    "/شهر",    t, flags=re.IGNORECASE)
    t = re.sub(r"/\s*M\b",               "/شهر",    t, flags=re.IGNORECASE)

    t = re.sub(r"(\d)\s*[Kk]\b", r"\1 ألف", t)   # 5K → 5 ألف
    t = re.sub(r"\b[Kk]\b",      "ألف",     t)   # K وحيدة → ألف

    return t.strip()

def _strip_price_from_desc(desc: str, price_per_point: float = 0.0) -> str | None:
    """يُطبّع الاختصارات أولاً ثم يحذف جزء السعر فقط، ويُبقي باقي النص.
    يعيد None إذا لم يتبق شيء بعد الحذف."""
    if not desc:
        return None

    text = _normalize_desc(desc)   # K→ألف، /D→/يوم، كيلوجرام→ألف … أولاً

    text = re.sub(r"\$\s*\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\d+(?:[.,]\d+)?\s*\$", "", text)
    text = re.sub(r"USD\s*\d+(?:[.,]\d+)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\d+(?:[.,]\d+)?\s*USD", "", text, flags=re.IGNORECASE)

    if price_per_point and price_per_point > 0:
        panel_price = price_per_point / 100_000
        def _remove_price_num(m):
            val = float(m.group(0).replace(",", "."))
            if val > 0 and abs(val - panel_price) / panel_price <= 0.5:
                return ""
            return m.group(0)
        text = re.sub(r"\d+(?:[.,]\d+)?", _remove_price_num, text)

    text = re.sub(r"[-|/\\،,;:\s]+$", "", text.strip())
    text = re.sub(r"^[-|/\\،,;:\s]+", "", text.strip())
    text = re.sub(r"\s{2,}", " ", text).strip()

    return text if text else None

def _desc_has_price(desc: str, price_per_point: float = 0.0) -> bool:
    if not desc:
        return False
    stripped = _strip_price_from_desc(desc, price_per_point)
    return stripped != desc.strip()

def get_setting(key: str) -> str:
    with db_conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else ""

def _do_set_setting(key: str, value: str):
    with db_conn() as c:
        c.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (key, value))

def set_setting(key: str, value: str):
    """حفظ إعداد مع إعادة محاولة تلقائية عند انقطاع الاتصال"""
    with_db_retry(_do_set_setting, key, value)

THANK_OWNER_SETTINGS = {
    "thank_owner_button_label": ("نص زر «شكر المالك»", "💌 شكر المالك"),
    "thank_owner_ar_button_label": ("نص زر الرسالة العربية", "🇸🇦 رسالة بالعربية"),
    "thank_owner_en_button_label": ("نص زر الرسالة الإنجليزية", "🇬🇧 Message in English"),
    "thank_owner_photo_button_label": ("نص زر إرسال الصورة", "🖼️ إرسال صورة"),
    "thank_owner_ar_prompt": ("رسالة طلب النص العربي", "💌 أرسل رسالة الشكر بالعربية:"),
    "thank_owner_en_prompt": ("رسالة طلب النص الإنجليزي", "💌 Send your thank-you message in English:"),
    "thank_owner_photo_prompt": ("رسالة طلب الصورة", "🖼️ أرسل الصورة التي تريد مشاركتها مع المالك:"),
    "thank_owner_success_message": ("رسالة نجاح الإرسال", "✅ تم إرسال شكرك إلى المالك، شكراً لك!"),
}

def is_maintenance_on() -> bool:
    return int(get_setting("maintenance_mode") or "0") == 1

def is_number_exchange_on() -> bool:
    return int(get_setting("number_exchange_enabled") or "0") == 1

def is_legendary_services_visible() -> bool:
    """يحدد ما إذا كان زر «خدمات أسطورية» ظاهراً للأعضاء."""
    return int(get_setting("legendary_services_visible") or "1") == 1

MAINTENANCE_MESSAGE = (
    "🛠 *البوت في وضع الصيانة حالياً*\n\n"
    "نعمل على تحسين تجربتك، ونعتذر عن أي إزعاج.\n"
    "سيعود البوت للعمل خلال وقت قصير — شكراً لتفهّمك 💙"
)

def get_or_create_user(user_id: int, username: str, full_name: str, invited_by: int = 0) -> dict:
    with db_conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            c.execute("UPDATE users SET username=?, full_name=? WHERE user_id=?",
                      (username, full_name, user_id))
            return dict(row)
        num_row = c.execute(
            "UPDATE settings SET value=(value::int+1)::text WHERE key='total_bot_users' RETURNING value::int AS total"
        ).fetchone()
        total = num_row["total"] if num_row else 1
        c.execute(
            "INSERT INTO users (user_id, username, full_name, invited_by, bot_user_num, verified) VALUES (%s,%s,%s,%s,%s,0)",
            (user_id, username, full_name, invited_by, total)
        )
        return dict(c.execute("SELECT * FROM users WHERE user_id=%s", (user_id,)).fetchone())

def set_user_verified(user_id: int):
    with db_conn() as c:
        c.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))

async def notify_referral_result_to_numbers_group(
    bot,
    user_id: int,
    phone: str,
    accepted: bool,
    credited: tuple | None = None,
    details: list[str] | None = None,
):
    """يرسل إشعار الإحالة ونتيجة فحص الحساب في رسالة واحدة إلى كروب الأرقام."""
    if not bot or not NUMBERS_GROUP_ID:
        return

    db_user = get_user(user_id) or {}
    invited_by = db_user.get("invited_by") or 0
    if not invited_by:
        return

    inviter = get_user(invited_by) or {}
    inviter_name = html.escape(inviter.get("full_name") or f"ID:{invited_by}")
    inviter_username = inviter.get("username")
    inviter_handle = f" (@{html.escape(inviter_username)})" if inviter_username else ""
    invited_name = html.escape(db_user.get("full_name") or f"ID:{user_id}")
    invited_username = db_user.get("username")
    invited_handle = f" (@{html.escape(invited_username)})" if invited_username else ""

    try:
        with db_conn() as c:
            total_referrals = (
                c.execute(
                    "SELECT COUNT(*) AS cnt FROM users "
                    "WHERE invited_by=%s AND referral_credited=1",
                    (invited_by,),
                ).fetchone()
                or {}
            ).get("cnt", 0)
    except Exception:
        total_referrals = 0

    if accepted:
        status_line = "✅ <b>الحساب مقبول</b>"
        if credited:
            points_line = f"💰 <b>النقاط الممنوحة:</b> {credited[1]} نقطة"
        else:
            points_line = "ℹ️ <b>النقاط:</b> الإحالة مسجلة مسبقاً"
    else:
        status_line = "❌ <b>الحساب مرفوض</b>"
        points_line = "💰 <b>النقاط:</b> لم تُمنح بسبب رفض الحساب"

    details_block = ""
    if details:
        safe_details = "\n".join(f"• {html.escape(item)}" for item in details)
        details_block = f"\n🔎 <b>نتيجة الفحص:</b>\n{safe_details}"

    text = (
        f"🤝 <b>إشعار إحالة</b>\n\n"
        f"{status_line}\n"
        f"👤 <b>المُحيل:</b> {inviter_name}{inviter_handle} "
        f"(<code>{invited_by}</code>)\n"
        f"🆕 <b>المدعو:</b> {invited_name}{invited_handle} "
        f"(<code>{user_id}</code>)\n"
        f"📱 <b>الرقم:</b> <code>{html.escape(phone)}</code>\n"
        f"{points_line}\n"
        f"📊 <b>إجمالي إحالات المُحيل:</b> {total_referrals}"
        f"{details_block}"
    )
    try:
        await bot.send_message(NUMBERS_GROUP_ID, text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"referral result group notify error: {e}")

def credit_referral_if_pending(user_id: int, context=None):
    """يمنح نقاط الإحالة للداعي مرة واحدة فقط، بعد اشتراك المدعو بالقنوات الإجبارية واجتيازه التحقق.
    يُعيد (inviter_id, points) عند المنح، أو None إن لم يكن هناك شيء لمنحه."""
    with db_conn() as c:
        row = c.execute(
            "SELECT invited_by, referral_credited FROM users WHERE user_id=%s", (user_id,)
        ).fetchone()
        if not row:
            return None
        invited_by = row["invited_by"]
        already = row["referral_credited"]
        if not invited_by or invited_by == 0 or invited_by == user_id or already:
            return None

        # إذا قُيّد الداعي بسبب الاشتباه برشق الإحالات، تُوقَف أي إحالات جديدة
        # حتى يراجعها المالك ويرفع التقييد.
        inviter_status = c.execute(
            "SELECT referral_points_blocked FROM users WHERE user_id=%s FOR UPDATE",
            (invited_by,),
        ).fetchone()
        if inviter_status and inviter_status.get("referral_points_blocked"):
            logger.info(
                "Referral skipped: inviter %s is blocked pending owner review",
                invited_by,
            )
            return None

        rp = int(get_setting("referral_points") or "30")
        c.execute(
            "UPDATE users SET referral_credited=1, credited_at=NOW() WHERE user_id=%s AND referral_credited=0",
            (user_id,)
        )
        if c.rowcount == 0:
            return None
        c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (rp, invited_by))
    _now_ts = time.time()
    _bucket = _referral_rate_tracker.setdefault(invited_by, [])
    _bucket.append(_now_ts)
    _referral_rate_tracker[invited_by] = [t for t in _bucket if _now_ts - t <= 300]
    if len(_referral_rate_tracker[invited_by]) >= 5 and context is not None:
        with db_conn() as _rc:
            _rc.execute("UPDATE users SET referral_points_blocked=1 WHERE user_id=%s", (invited_by,))
        _referral_rate_tracker.pop(invited_by, None)
        _bot2 = getattr(context, 'bot', None)
        if _bot2 and OWNER_ID:
            _rq = get_user(invited_by) or {}
            _rq_name = _rq.get('full_name') or f"ID:{invited_by}"
            _rq_un = (f" (@{_rq['username']})" if _rq.get('username') else '')
            _fraud_text = (
                f"⚠️ *تنبيه: رشق إحالات محتمل!*\n\n"
                f"👤 المُحيل: {_rq_name}{_rq_un} (`{invited_by}`)\n"
                f"📊 تلقّى 5+ إحالات في أقل من 5 دقائق\n"
                f"💰 نقاط آخر إحالة: {rp} نقطة\n"
                f"🔒 تم تقييده تلقائياً\n\n"
                f"اختر الإجراء:"
            )
            _fraud_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ إبقاء + رفع التقييد",   callback_data=f"os:ref_keep:{invited_by}:{rp}")],
                [InlineKeyboardButton("❌ خصم الإحالة + رفع التقييد", callback_data=f"os:ref_deduct:{invited_by}:{rp}")],
                [InlineKeyboardButton("➕ خصم نقاط إضافية",               callback_data=f"os:ref_extra:{invited_by}:{rp}")],
                [InlineKeyboardButton("🔓 رفع التقييد فقط",            callback_data=f"os:ref_unblock:{invited_by}")],
            ])
            try:
                asyncio.ensure_future(_bot2.send_message(OWNER_ID, _fraud_text, parse_mode='Markdown', reply_markup=_fraud_kb))
            except Exception:
                pass
    return (invited_by, rp)

def _referral_counter_reset_at():
    """يُرجع لحظة آخر تصفير للعداد (UTC) إن وُجدت، وإلا None."""
    raw = get_setting("referral_counter_reset_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def reset_referral_counter():
    """يصفّر عداد 'الأكثر إرسالاً لرابط الدعوة' من الآن، دون المساس بنقاط
    الأعضاء أو حالة الدعوات الفعلية — فقط يستثني ما قبل هذه اللحظة من العدّ."""
    set_setting("referral_counter_reset_at", datetime.now(timezone.utc).isoformat())

def _referral_period_bounds(period: str):
    """يُرجع (since_utc, عنوان الفترة) لفترة زمنية معيّنة، محسوبة بالتوقيت العالمي (UTC)،
    مع مراعاة آخر عملية تصفير للعداد إن وُجدت (يُؤخذ الأحدث بين الاثنين)."""
    now = datetime.now(timezone.utc)
    if period == "24h":
        since, title = now - timedelta(hours=24), "آخر 24 ساعة"
    elif period == "day":
        since, title = now.replace(hour=0, minute=0, second=0, microsecond=0), "اليوم (منذ 00:00 بالتوقيت العالمي)"
    elif period == "week":
        since, title = now - timedelta(days=7), "آخر أسبوع"
    elif period == "month":
        since, title = now - timedelta(days=30), "آخر شهر"
    else:
        since, title = None, "كل الأوقات"
    reset_at = _referral_counter_reset_at()
    if reset_at is not None and (since is None or reset_at > since):
        since = reset_at
    return since, title

def get_top_referrers_since(since_dt, limit: int = 10):
    """يُرجع قائمة أكثر الأعضاء إرسالاً لرابط الدعوة (دعوات مكتملة/معتمدة فقط)
    منذ لحظة زمنية محدّدة (UTC)، أو لكل الأوقات إن كانت since_dt=None."""
    with db_conn() as c:
        if since_dt is None:
            rows = c.execute(
                "SELECT invited_by, COUNT(*) as cnt FROM users "
                "WHERE invited_by IS NOT NULL AND invited_by != 0 AND referral_credited=1 "
                "GROUP BY invited_by ORDER BY cnt DESC LIMIT %s",
                (limit,)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT invited_by, COUNT(*) as cnt FROM users "
                "WHERE invited_by IS NOT NULL AND invited_by != 0 AND referral_credited=1 "
                "AND credited_at IS NOT NULL AND credited_at >= %s "
                "GROUP BY invited_by ORDER BY cnt DESC LIMIT %s",
                (since_dt, limit)
            ).fetchall()
    return rows

def _format_top_referrers(rows, title: str) -> str:
    lines = [f"🏆 *الأكثر إرسالاً لرابط الدعوة — {title}:*\n"]
    if not rows:
        lines.append("لا توجد دعوات مكتملة خلال هذه الفترة.")
        return "\n".join(lines)
    inviter_ids = [r["invited_by"] for r in rows]
    inviters_map = {}
    if inviter_ids:
        placeholders = ",".join(["%s"] * len(inviter_ids))
        with db_conn() as _c:
            _batch = _c.execute(
                f"SELECT user_id, username, full_name FROM users WHERE user_id IN ({placeholders})",
                tuple(inviter_ids)
            ).fetchall()
        for u in _batch:
            inviters_map[u["user_id"]] = u
    for i, r in enumerate(rows, start=1):
        inviter = inviters_map.get(r["invited_by"])
        if inviter and inviter.get("username"):
            name = md_escape(f"@{inviter['username']}")
        elif inviter and inviter.get("full_name"):
            name = md_escape(inviter["full_name"])
        else:
            name = f"ID {r['invited_by']}"
        lines.append(f"{i}. {name} — {r['cnt']} دعوة")
    return "\n".join(lines)

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────

def get_referral_contest() -> dict:
    """يُرجع معلومات المسابقة الحالية من قاعدة الإعدادات."""
    ctype     = get_setting("referral_contest_type")  or "none"
    start_raw = get_setting("referral_contest_start") or ""
    end_raw   = get_setting("referral_contest_end")   or ""
    start_dt = end_dt = None
    try:
        if start_raw:
            start_dt = datetime.fromisoformat(start_raw)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        if end_raw:
            end_dt = datetime.fromisoformat(end_raw)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return {"type": ctype, "start": start_dt, "end": end_dt}

def _parse_contest_duration(text: str):
    """يُحوّل نصاً مثل 7s / 7m / 7h / 7d إلى timedelta، أو None إن كانت الصيغة خاطئة."""
    m = re.match(r"^(\d+)([smhd])$", text.strip().lower())
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2)
    if unit == "s": return timedelta(seconds=val)
    if unit == "m": return timedelta(minutes=val)
    if unit == "h": return timedelta(hours=val)
    if unit == "d": return timedelta(days=val)
    return None

def _format_contest_time_remaining(end_dt) -> str:
    """يُرجع نص الوقت المتبقي بصيغة مقروءة بالعربية."""
    now = datetime.now(timezone.utc)
    if end_dt is None or end_dt <= now:
        return "انتهت المسابقة"
    total_seconds = int((end_dt - now).total_seconds())
    days    = total_seconds // 86400
    hours   = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600)  // 60
    seconds = total_seconds % 60
    parts = []
    if days:              parts.append(f"{days} يوم")
    if hours:             parts.append(f"{hours} ساعة")
    if minutes:           parts.append(f"{minutes} دقيقة")
    if seconds and not days: parts.append(f"{seconds} ثانية")
    return " و ".join(parts) if parts else "أقل من ثانية"
