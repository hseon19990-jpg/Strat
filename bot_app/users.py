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

    # احذف عبارة السعر كاملة، بما فيها الصياغة العربية مثل:
    # "0.05 دولار لكل 1000" و"3.33 دولار لكل 1000".
    text = re.sub(
        r"(?:[-|/\\،,;:]\s*)?"
        r"(?:\$\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*\$|"
        r"USD\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*USD|"
        r"\d+(?:[.,]\d+)?\s*(?:دولار|دولارات|دولاراً))"
        r"(?:\s*(?:لكل|per)\s*(?:\d+(?:[.,]\d+)?|ألف|1000))?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?:[-|/\\،,;:]\s*)?\d+(?:[.,]\d+)?\s*(?:دولار|دولارات|دولاراً)"
        r"(?:\s*(?:لكل|per)\s*(?:\d+(?:[.,]\d+)?|ألف|1000))?",
        "",
        text,
        flags=re.IGNORECASE,
    )

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
            # قد يفتح المستخدم البوت أولاً بدون رابط، ثم يعود لاحقاً من
            # رابط دعوة. لا نهمل الرابط في هذه الحالة، وإلا لن تُسجّل
            # الإحالة أبداً لهذا المستخدم.
            current_inviter = row.get("invited_by") or 0
            if (
                invited_by
                and invited_by != user_id
                and not current_inviter
            ):
                c.execute(
                    """
                    UPDATE users
                    SET username=?, full_name=?, invited_by=?,
                        referral_credited=0, credited_at=NULL
                    WHERE user_id=?
                    """,
                    (username, full_name, invited_by, user_id),
                )
            else:
                c.execute(
                    "UPDATE users SET username=?, full_name=? WHERE user_id=?",
                    (username, full_name, user_id),
                )
            return dict(
                c.execute(
                    "SELECT * FROM users WHERE user_id=%s",
                    (user_id,),
                ).fetchone()
            )
        num_row = c.execute(
            "UPDATE settings SET value=(value::int+1)::text WHERE key='total_bot_users' RETURNING value::int AS total"
        ).fetchone()
        total = num_row["total"] if num_row else 1
        c.execute(
            "INSERT INTO users (user_id, username, full_name, invited_by, bot_user_num, verified) VALUES (%s,%s,%s,%s,%s,0)",
            (user_id, username, full_name, invited_by, total)
        )
        return dict(c.execute("SELECT * FROM users WHERE user_id=%s", (user_id,)).fetchone())

def should_notify_referral_link_opened(
    previous_invited_by: int,
    requested_invited_by: int,
    stored_invited_by: int,
    user_id: int,
) -> bool:
    """يُرجع True عند تسجيل فتح رابط إحالة جديد لأول مرة لهذا المستخدم."""
    return bool(
        requested_invited_by
        and requested_invited_by != user_id
        and not previous_invited_by
        and stored_invited_by == requested_invited_by
    )

async def notify_referral_link_opened(bot, invited_user, inviter_id: int):
    """يُخبر صاحب الرابط أن الرابط فُتح وأن الإحالة ما زالت معلّقة."""
    if not bot or not inviter_id or inviter_id == invited_user.id:
        return

    invited_name = html.escape(
        invited_user.full_name or f"ID:{invited_user.id}"
    )
    invited_username = getattr(invited_user, "username", None)
    invited_handle = (
        f" (@{html.escape(invited_username)})"
        if invited_username
        else ""
    )
    try:
        await bot.send_message(
            chat_id=inviter_id,
            text=(
                "🔗 <b>تم فتح رابط دعوتك</b>\n\n"
                f"👤 المدعو: {invited_name}{invited_handle}\n"
                "⏳ الإحالة ما زالت معلّقة؛ لن تُضاف نقاط الآن.\n"
                "يجب على المدعو إكمال التحقق حتى تُحتسب الإحالة."
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.warning(f"⚠️ فشل إرسال إشعار فتح رابط الإحالة: {exc}")

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
    """يمنح نقاط الإحالة للداعي مرة واحدة فقط بعد إكمال المدعو التحقق.
    يُعيد (inviter_id, points) عند المنح، أو None إن لم يكن هناك شيء لمنحه."""
    if context is not None:
        context.user_data.pop("referral_reward_granted_minutes", None)
    with db_conn() as c:
        row = c.execute(
            "SELECT invited_by, referral_credited, verified FROM users WHERE user_id=%s",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        invited_by = row["invited_by"]
        already = row["referral_credited"]
        if (
            not invited_by
            or invited_by == 0
            or invited_by == user_id
            or already
            or not row["verified"]
        ):
            return None

        c.execute(
            "UPDATE users SET referral_credited=1, credited_at=NOW() WHERE user_id=%s AND referral_credited=0",
            (user_id,)
        )
        if c.rowcount == 0:
            return None
        count_row = c.execute(
            "SELECT COUNT(*) AS cnt FROM users "
            "WHERE invited_by=%s AND referral_credited=1",
            (invited_by,),
        ).fetchone()
        referral_count = int((count_row or {}).get("cnt", 0) or 0)
        tier = c.execute(
            "SELECT referral_count, points_per_referral "
            "FROM referral_reward_tiers "
            "WHERE active=1 AND referral_count<=%s "
            "ORDER BY referral_count DESC LIMIT 1",
            (referral_count,),
        ).fetchone()
        rp = int(
            tier["points_per_referral"]
            if tier is not None
            else (get_setting("referral_points") or 30)
        )
        c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (rp, invited_by))
        minutes = _grant_daily_referral_free_access(c, invited_by)
        if context is not None and minutes:
            context.user_data["referral_reward_granted_minutes"] = minutes
    return (invited_by, rp)


def list_referral_reward_tiers() -> list[dict]:
    """إرجاع شرائح تغيير مكافأة الإحالة فقط."""
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, referral_count, points_per_referral "
            "FROM referral_reward_tiers WHERE active=1 ORDER BY referral_count"
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_referral_reward_tier(
    referral_count: int, points_per_referral: int
) -> None:
    """إضافة/تحديث مكافأة النقاط عند بلوغ عدد إحالات محدد."""
    with db_conn() as c:
        c.execute(
            """
            INSERT INTO referral_reward_tiers
                (referral_count, points_per_referral, active)
            VALUES (%s,%s,1)
            ON CONFLICT (referral_count) DO UPDATE SET
                points_per_referral=EXCLUDED.points_per_referral,
                active=1
            """,
            (int(referral_count), int(points_per_referral)),
        )


def delete_referral_reward_tier(tier_id: int) -> None:
    with db_conn() as c:
        c.execute("DELETE FROM referral_reward_tiers WHERE id=%s", (int(tier_id),))


def list_referral_daily_free_tiers() -> list[dict]:
    """إرجاع شرائح الحق المجاني المؤقت التي تُراجع مرة كل يوم."""
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, referral_count, free_minutes "
            "FROM referral_daily_free_tiers "
            "WHERE active=1 ORDER BY referral_count"
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_referral_daily_free_tier(
    referral_count: int, free_minutes: int
) -> None:
    """إضافة/تحديث مدة الاستخدام المجاني اليومية عند عدد إحالات محدد."""
    with db_conn() as c:
        c.execute(
            """
            INSERT INTO referral_daily_free_tiers
                (referral_count, free_minutes, active)
            VALUES (%s,%s,1)
            ON CONFLICT (referral_count) DO UPDATE SET
                free_minutes=EXCLUDED.free_minutes,
                active=1
            """,
            (int(referral_count), int(free_minutes)),
        )


def delete_referral_daily_free_tier(tier_id: int) -> None:
    with db_conn() as c:
        c.execute(
            "DELETE FROM referral_daily_free_tiers WHERE id=%s",
            (int(tier_id),),
        )


def _grant_daily_referral_free_access(c, user_id: int) -> int:
    """يمنح الحق المجاني مرة واحدة لكل شريحة في كل يوم."""
    eligible = c.execute(
        """
        SELECT t.id, t.free_minutes
        FROM referral_daily_free_tiers t
        WHERE t.active=1
          AND t.free_minutes>0
          AND t.referral_count <= (
              SELECT COUNT(*)
              FROM users
              WHERE invited_by=%s AND referral_credited=1
          )
        ORDER BY t.referral_count DESC
        LIMIT 1
        """,
        (int(user_id),),
    ).fetchone()
    if not eligible:
        return 0

    claim = c.execute(
        """
        INSERT INTO referral_daily_free_claims
            (user_id, tier_id, claim_date)
        VALUES (%s,%s,CURRENT_DATE)
        ON CONFLICT (user_id, tier_id, claim_date) DO NOTHING
        """,
        (int(user_id), int(eligible["id"])),
    )
    if claim.rowcount == 0:
        return 0

    minutes = int(eligible["free_minutes"])
    c.execute(
        """
        INSERT INTO referral_free_access (user_id, free_until)
        VALUES (%s, NOW() + (%s * INTERVAL '1 minute'))
        ON CONFLICT (user_id) DO UPDATE SET
            free_until=NOW() + (%s * INTERVAL '1 minute'),
            updated_at=NOW()
        """,
        (int(user_id), minutes, minutes),
    )
    return minutes


def refresh_daily_referral_free_access(user_id: int) -> int:
    """يبدأ حق اليوم عند أول محاولة لاستخدام خدمة مدفوعة."""
    try:
        with db_conn() as c:
            blocked = c.execute(
                "SELECT COALESCE(referral_points_blocked, 0) AS blocked "
                "FROM users WHERE user_id=%s",
                (int(user_id),),
            ).fetchone()
            if blocked and blocked["blocked"]:
                return 0
            return _grant_daily_referral_free_access(c, int(user_id))
    except Exception:
        logger.exception("تعذر تحديث الحق المجاني اليومي للإحالة")
        return 0


def has_active_referral_free_access(user_id: int) -> bool:
    """هل يملك المستخدم إعفاء الإحالات المؤقت الساري؟ يبدأ حق اليوم عند الحاجة."""
    try:
        refresh_daily_referral_free_access(int(user_id))
        with db_conn() as c:
            row = c.execute(
                """
                SELECT 1
                FROM users u
                JOIN referral_free_access r ON r.user_id=u.user_id
                WHERE u.user_id=%s
                  AND COALESCE(u.referral_points_blocked, 0)=0
                  AND r.free_until>NOW()
                """,
                (int(user_id),),
            ).fetchone()
        return bool(row)
    except Exception:
        logger.exception("تعذر فحص إعفاء الإحالة المؤقت")
        return False

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
