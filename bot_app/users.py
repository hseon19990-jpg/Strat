"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

import re
import html
import time
import asyncio
import uuid
import random
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

REFERRAL_FREE_RAKSH_ACCOUNT_LIMIT = 250

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

DAILY_GIFT_POINTS_SETTING = "daily_gift_points"
DEFAULT_DAILY_GIFT_POINTS = 100

def get_daily_gift_points() -> int:
    """يُرجع قيمة الهدية اليومية مع قيمة افتراضية آمنة."""
    try:
        value = int(get_setting(DAILY_GIFT_POINTS_SETTING) or DEFAULT_DAILY_GIFT_POINTS)
    except (TypeError, ValueError):
        value = DEFAULT_DAILY_GIFT_POINTS
    return value if value > 0 else DEFAULT_DAILY_GIFT_POINTS

def get_daily_gift_claim_amount(user_id: int) -> int | None:
    """يُرجع مبلغ الهدية المستلمة اليوم وفق تاريخ العراق الحالي."""
    with db_conn() as c:
        row = c.execute(
            """
            SELECT amount
            FROM daily_gift_claims
            WHERE user_id=%s
              AND claim_date=(NOW() AT TIME ZONE 'Asia/Baghdad')::date
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    return int(row["amount"]) if row else None

def has_claimed_daily_gift(user_id: int) -> bool:
    """يتحقق من استلام المستخدم هديته وفق تاريخ العراق الحالي."""
    return get_daily_gift_claim_amount(user_id) is not None

def claim_daily_gift(user_id: int) -> tuple[int | None, int | None]:
    """
    يمنح الهدية مرة واحدة يومياً بشكل ذري.

    يُرجع (المبلغ، الرصيد الجديد) عند النجاح، أو (None, None) إذا استُلمت
    الهدية مسبقاً اليوم.
    """
    amount = get_daily_gift_points()
    with db_conn() as c:
        claimed = c.execute(
            f"""
            INSERT INTO daily_gift_claims (user_id, claim_date, amount)
            VALUES (%s, (NOW() AT TIME ZONE 'Asia/Baghdad')::date, %s)
            ON CONFLICT (user_id, claim_date) DO NOTHING
            RETURNING amount
            """,
            (user_id, amount),
        ).fetchone()
        if not claimed:
            return None, None

        updated = c.execute(
            """
            UPDATE users
            SET points=points+%s
            WHERE user_id=%s
            RETURNING points
            """,
            (amount, user_id),
        ).fetchone()
        if not updated:
            raise ValueError(f"Cannot credit daily gift to unknown user {user_id}")
    return amount, int(updated["points"])


def get_active_temporary_gift() -> dict | None:
    """يعيد الهدية المؤقتة الحالية إذا كانت ما زالت ضمن وقت الإتاحة."""
    with db_conn() as c:
        row = c.execute(
            """
            SELECT id, points, starts_at, ends_at
            FROM temporary_gifts
            WHERE active=1
              AND starts_at <= NOW()
              AND ends_at > NOW()
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def get_temporary_gift_claim(user_id: int, gift_id: int) -> dict | None:
    """يتحقق من استلام عضو لهدية مؤقتة محددة."""
    with db_conn() as c:
        row = c.execute(
            """
            SELECT gift_id, amount, claimed_at
            FROM temporary_gift_claims
            WHERE gift_id=%s AND user_id=%s
            LIMIT 1
            """,
            (gift_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def create_temporary_gift(points: int, duration_seconds: int, owner_id: int) -> dict:
    """ينشئ هدية مؤقتة جديدة ويغلق أي هدية سابقة."""
    with db_conn() as c:
        c.execute(
            "UPDATE temporary_gifts SET active=0 WHERE active=1"
        )
        row = c.execute(
            """
            INSERT INTO temporary_gifts (points, starts_at, ends_at, created_by)
            VALUES (%s, NOW(), NOW() + (%s * INTERVAL '1 second'), %s)
            RETURNING id, points, starts_at, ends_at
            """,
            (points, duration_seconds, owner_id),
        ).fetchone()
    return dict(row)


def claim_temporary_gift(
    user_id: int,
    gift_id: int | None = None,
) -> tuple[int | None, int | None, int | None, bool]:
    """
    يستلم العضو الهدية الحالية مرة واحدة بشكل ذري.

    يُرجع (النقاط، الرصيد، رقم الهدية، هل حان إشعار الأربع عمليات).
    """
    gift_filter = "AND id=%s" if gift_id is not None else ""
    params = [user_id, user_id]
    if gift_id is not None:
        params.append(gift_id)
    with db_conn() as c:
        claimed = c.execute(
            """
            INSERT INTO temporary_gift_claims (gift_id, user_id, amount)
            SELECT id, %s, points
            FROM temporary_gifts
            WHERE active=1
              AND starts_at <= NOW()
              AND ends_at > NOW()
              AND NOT EXISTS (
                  SELECT 1
                  FROM temporary_gift_claims old_claim
                  WHERE old_claim.gift_id=temporary_gifts.id
                    AND old_claim.user_id=%s
              )
            {gift_filter}
            ORDER BY id DESC
            LIMIT 1
            ON CONFLICT (gift_id, user_id) DO NOTHING
            RETURNING gift_id, amount
            """,
            params,
        ).fetchone()
        if not claimed:
            return None, None, None, False

        updated = c.execute(
            """
            UPDATE users
            SET points=points+%s
            WHERE user_id=%s
            RETURNING points
            """,
            (claimed["amount"], user_id),
        ).fetchone()
        if not updated:
            raise ValueError(f"Cannot credit temporary gift to unknown user {user_id}")

        count_row = c.execute(
            "SELECT COUNT(*) AS total FROM temporary_gift_claims WHERE gift_id=%s",
            (claimed["gift_id"],),
        ).fetchone()
    total_claims = int(count_row["total"]) if count_row else 0
    return (
        int(claimed["amount"]),
        int(updated["points"]),
        int(claimed["gift_id"]),
        total_claims % 4 == 0,
    )

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
                "تُحتسب الإحالة بعد اشتراك المدعو بجميع القنوات الإلزامية؛ لا حاجة لرقم الهاتف."
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.warning(f"⚠️ فشل إرسال إشعار فتح رابط الإحالة: {exc}")

def set_user_verified(user_id: int):
    with db_conn() as c:
        c.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))

REFERRAL_REWARD_TYPES = ("points", "jewels")
REFERRAL_MAX_LEVELS = 10


def get_referral_reward_type() -> str:
    """نوع مكافأة الإحالة المختار من المالك: points أو jewels (واحد فقط)."""
    value = (get_setting("referral_reward_type") or "points").strip().lower()
    return value if value in REFERRAL_REWARD_TYPES else "points"


def parse_referral_jewels(value) -> Decimal:
    """تحويل قيمة الجواهر إلى Decimal صالح (حتى 6 خانات عشرية)، أو ValueError."""
    try:
        amount = Decimal(str(value).strip().replace(",", ""))
        if not amount.is_finite():
            raise ValueError
        amount = amount.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("invalid jewel amount")
    if amount < 0:
        raise ValueError("negative jewel amount")
    return amount


def get_referral_level1_jewels() -> Decimal:
    try:
        return parse_referral_jewels(get_setting("referral_jewels") or "0")
    except ValueError:
        return Decimal("0")


def list_referral_level_rewards() -> list[dict]:
    """مكافآت المستويات 2 فما فوق (نقاط وجواهر لكل مستوى)."""
    with db_conn() as c:
        rows = c.execute(
            "SELECT level, points, jewels FROM referral_level_rewards ORDER BY level"
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_referral_level_reward(level: int, points: int, jewels) -> None:
    level = int(level)
    if level < 2 or level > REFERRAL_MAX_LEVELS:
        raise ValueError("level out of range")
    with db_conn() as c:
        c.execute(
            """
            INSERT INTO referral_level_rewards (level, points, jewels)
            VALUES (%s,%s,%s)
            ON CONFLICT (level) DO UPDATE SET
                points=EXCLUDED.points,
                jewels=EXCLUDED.jewels
            """,
            (level, max(0, int(points)), parse_referral_jewels(jewels)),
        )


def delete_referral_level_reward(level: int) -> None:
    with db_conn() as c:
        c.execute("DELETE FROM referral_level_rewards WHERE level=%s", (int(level),))


def fmt_referral_amount(reward_type: str, amount) -> str:
    """نص المكافأة: «30 نقطة» أو «💎 2.5 جوهرة»."""
    if reward_type == "jewels":
        try:
            value = Decimal(str(amount or 0)).normalize()
        except (InvalidOperation, ValueError, TypeError):
            value = Decimal(0)
        whole, dot, frac = format(value, "f").partition(".")
        text = f"{int(whole):,}" + (f".{frac}" if dot else "")
        return f"💎 {text} جوهرة"
    return f"{int(amount or 0):,} نقطة"


def _credit_referral_reward(c, user_id: int, reward_type: str, amount, level: int, source_id: int) -> None:
    """يضيف المكافأة (نقاط أو جواهر) داخل نفس معاملة قاعدة البيانات."""
    if reward_type == "jewels":
        amount = parse_referral_jewels(amount)
        c.execute(
            "UPDATE users SET jewels=COALESCE(jewels,0)+%s WHERE user_id=%s",
            (amount, user_id),
        )
        c.execute(
            "INSERT INTO jewel_transactions "
            "(user_id,amount,transaction_type,admin_id,reference) "
            "VALUES (%s,%s,%s,%s,%s)",
            (user_id, amount, "referral", None, f"referral:L{level}:from:{source_id}"),
        )
    else:
        c.execute(
            "UPDATE users SET points=points+%s WHERE user_id=%s",
            (int(amount), user_id),
        )


def referral_fraud_protection_enabled() -> bool:
    """هل حماية الإحالات (كشف الانضمام الآلي للقنوات الإجبارية) مفعّلة؟"""
    return (get_setting("referral_fraud_protection") or "0").strip() == "1"


def record_mandatory_join(user_id: int, channel_username: str, joined_ts) -> None:
    """يسجّل لحظة انضمام (بالثانية) لقناة إجبارية، ليُكشف الانضمام الجماعي في ثانية واحدة."""
    channel = (channel_username or "").lstrip("@").strip().lower()
    if not channel or not user_id:
        return
    with db_conn() as c:
        row = c.execute(
            "SELECT 1 FROM mandatory_channels "
            "WHERE LOWER(channel_username)=%s AND funding_type='mandatory'",
            (channel,),
        ).fetchone()
        if not row:
            return
        c.execute(
            "INSERT INTO mandatory_join_events (user_id, channel_username, joined_second) "
            "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            (int(user_id), channel, int(joined_ts)),
        )
        if random.random() < 0.01:
            c.execute(
                "DELETE FROM mandatory_join_events "
                "WHERE created_at < NOW() - INTERVAL '30 days'"
            )


def _detect_same_second_mandatory_joins(c, user_id: int):
    """يُرجع (انضم_معاً، أكبر_عدد_في_ثانية_واحدة، إجمالي_القنوات) أو None.

    الشرط: انضمام المدعو في نفس الثانية إلى 50% أو أكثر من القنوات الإجبارية
    الفعّالة، وبحد أدنى قناتان (حتى لا تُعدّ قناة واحدة غشاً).
    """
    channels = [
        (r["channel_username"] or "").lstrip("@").strip().lower()
        for r in c.execute(
            "SELECT channel_username FROM mandatory_channels "
            "WHERE active=1 AND funding_type='mandatory'"
        ).fetchall()
    ]
    channels = [ch for ch in channels if ch]
    total = len(channels)
    if total < 2:
        return None
    needed = max(2, -(-total // 2))  # ceil(total * 0.5)
    placeholders = ",".join(["%s"] * total)
    row = c.execute(
        "SELECT joined_second, COUNT(DISTINCT channel_username) AS cnt "
        "FROM mandatory_join_events "
        f"WHERE user_id=%s AND channel_username IN ({placeholders}) "
        "GROUP BY joined_second ORDER BY cnt DESC LIMIT 1",
        (int(user_id), *channels),
    ).fetchone()
    best = int((row or {}).get("cnt", 0) or 0)
    if best >= needed:
        return (best, total)
    return None


def _punish_referral_fraud(c, inviter_id: int, invited_id: int, joined: int, total: int) -> dict:
    """يصفّر نقاط وجواهر الداعي ويلغي طلباته الجارية دون أي تعويض."""
    before = c.execute(
        "SELECT points, jewels FROM users WHERE user_id=%s", (inviter_id,)
    ).fetchone() or {}
    c.execute(
        "UPDATE users SET points=LEAST(points,0), jewels=LEAST(COALESCE(jewels,0),0) "
        "WHERE user_id=%s",
        (inviter_id,),
    )
    old_jewels = Decimal(str(before.get("jewels") or 0))
    if old_jewels > 0:
        c.execute(
            "INSERT INTO jewel_transactions "
            "(user_id,amount,transaction_type,admin_id,reference) "
            "VALUES (%s,%s,%s,%s,%s)",
            (inviter_id, -old_jewels, "fraud_reset", None, f"referral_fraud:{invited_id}"),
        )
    smm_rows = c.execute(
        "SELECT o.id, o.order_code, o.api_order_id, s.panel AS panel "
        "FROM orders o LEFT JOIN services s ON s.id=o.service_id "
        "WHERE o.user_id=%s AND o.status='pending'",
        (inviter_id,),
    ).fetchall()
    smm_cancelled = []
    for o in smm_rows:
        c.execute(
            "UPDATE orders SET status='cancelled', refund_points=0, "
            "partial_refund_pts=0, refund_jewels=0 WHERE id=%s AND status='pending'",
            (o["id"],),
        )
        smm_cancelled.append(
            (o.get("panel") or 1, o.get("api_order_id") or "", o.get("order_code") or "")
        )
    raksh_ids = [
        int(r["id"])
        for r in c.execute(
            "SELECT id FROM raksh_orders "
            "WHERE user_id=%s AND status IN ('pending','running')",
            (inviter_id,),
        ).fetchall()
    ]
    c.execute(
        "INSERT INTO referral_fraud_log "
        "(inviter_id, invited_id, joined_count, total_channels) VALUES (%s,%s,%s,%s)",
        (inviter_id, invited_id, joined, total),
    )
    return {
        "inviter_id": inviter_id,
        "invited_id": invited_id,
        "joined": joined,
        "total": total,
        "smm_cancelled": smm_cancelled,
        "raksh_order_ids": raksh_ids,
        "points_before": int(before.get("points") or 0),
        "jewels_before": old_jewels,
    }


def credit_referral_if_pending(user_id: int, context=None):
    """يمنح مكافأة الإحالة للداعي مرة واحدة بعد اكتمال دخول المدعو.

    نوع المكافأة (نقاط أو جواهر) يحدده المالك. المستوى الأول للداعي المباشر،
    والمستويات التالية لمن دعا الداعي ثم من دعاه وهكذا حسب إعدادات المالك.
    يُعيد (inviter_id, amount) للمستوى الأول، أو None إن لم يكن هناك شيء لمنحه.
    تفاصيل المستويات الأعلى تُوضع في context.user_data["referral_upper_rewards"].
    """
    if context is not None:
        context.user_data.pop("referral_reward_granted_minutes", None)
        context.user_data.pop("referral_upper_rewards", None)
        context.user_data.pop("referral_reward_type", None)
        context.user_data.pop("referral_fraud", None)
    reward_type = get_referral_reward_type()
    upper_rewards = []
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

        # ── حماية الإحالات: انضمام جماعي في ثانية واحدة للقنوات الإجبارية ──
        if referral_fraud_protection_enabled() and invited_by != globals().get("OWNER_ID"):
            fraud = _detect_same_second_mandatory_joins(c, user_id)
            if fraud:
                info = _punish_referral_fraud(c, invited_by, user_id, fraud[0], fraud[1])
                if context is not None:
                    context.user_data["referral_fraud"] = info
                return None

        # ── المستوى الأول ──
        if reward_type == "jewels":
            rp = get_referral_level1_jewels()
        else:
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
        if rp > 0:
            _credit_referral_reward(c, invited_by, reward_type, rp, 1, user_id)
        minutes = _grant_daily_referral_free_access(c, invited_by)

        # ── المستويات 2 فما فوق ──
        level_rows = c.execute(
            "SELECT level, points, jewels FROM referral_level_rewards ORDER BY level"
        ).fetchall()
        level_map = {int(r["level"]): r for r in level_rows}
        if level_map:
            visited = {user_id, invited_by}
            current = invited_by
            for level in range(2, max(level_map) + 1):
                parent_row = c.execute(
                    "SELECT invited_by FROM users WHERE user_id=%s", (current,)
                ).fetchone()
                parent = int((parent_row or {}).get("invited_by", 0) or 0)
                if not parent or parent in visited:
                    break
                visited.add(parent)
                current = parent
                cfg = level_map.get(level)
                if not cfg:
                    continue
                amount = cfg["jewels"] if reward_type == "jewels" else cfg["points"]
                if not amount or Decimal(str(amount)) <= 0:
                    continue
                _credit_referral_reward(c, parent, reward_type, amount, level, user_id)
                upper_rewards.append((parent, level, amount))

        if context is not None:
            if minutes:
                context.user_data["referral_reward_granted_minutes"] = minutes
            context.user_data["referral_reward_type"] = reward_type
            if upper_rewards:
                context.user_data["referral_upper_rewards"] = upper_rewards
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
    """يمنح الحق المجاني مرة واحدة لكل شريحة في كل يوم (بتوقيت UTC).

    تُحتسب فقط الإحالات المكتملة خلال اليوم الحالي (00:00:00 → 23:59:59 UTC)،
    ويبدأ العداد من الصفر في اليوم التالي. الحق نفسه حصة 250 حساباً ناجحاً
    تُستهلك خلال مدة الشريحة، وما لم يُستهلك منها يسقط بانتهاء المدة.
    """
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
                AND credited_at >= (
                    date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
                )
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
        VALUES (%s,%s,(NOW() AT TIME ZONE 'UTC')::date)
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
            free_pass_id=referral_free_access.free_pass_id + 1,
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


def _referral_free_raksh_remaining(limit: int, used: int, reserved: int) -> int:
    """حساب الحصة المتبقية من الحسابات الناجحة والحجوزات الجارية."""
    try:
        return max(
            0,
            int(limit) - max(0, int(used or 0)) - max(0, int(reserved or 0)),
        )
    except (TypeError, ValueError):
        return 0


def get_referral_free_raksh_remaining(user_id: int) -> int:
    """عدد الحسابات المجانية المتاحة في نافذة الإحالة الحالية."""
    try:
        refresh_daily_referral_free_access(int(user_id))
        with db_conn() as c:
            access = c.execute(
                """
                SELECT r.free_pass_id
                FROM users u
                JOIN referral_free_access r ON r.user_id=u.user_id
                WHERE u.user_id=%s
                  AND COALESCE(u.referral_points_blocked, 0)=0
                  AND r.free_until>NOW()
                """,
                (int(user_id),),
            ).fetchone()
            if not access:
                return 0
            totals = c.execute(
                """
                SELECT
                    COALESCE(SUM(used_quantity), 0) AS used_quantity,
                    COALESCE(SUM(
                        CASE WHEN settled_at IS NULL
                             THEN reserved_quantity ELSE 0 END
                    ), 0) AS reserved_quantity
                FROM referral_free_raksh_reservations
                WHERE user_id=%s AND pass_id=%s
                """,
                (int(user_id), int(access["free_pass_id"] or 0)),
            ).fetchone()
        return _referral_free_raksh_remaining(
            REFERRAL_FREE_RAKSH_ACCOUNT_LIMIT,
            totals["used_quantity"] if totals else 0,
            totals["reserved_quantity"] if totals else 0,
        )
    except Exception:
        logger.exception("تعذر حساب حصة الرشق المجانية")
        return 0


def reserve_referral_free_raksh_quota(
    user_id: int,
    quantity: int,
    source_type: str,
    service_type: str,
) -> dict:
    """يحجز عدداً من وحدات الحصة بالتزامن الآمن حتى تنتهي عملية الرشق."""
    try:
        requested = max(0, int(quantity or 0))
    except (TypeError, ValueError):
        requested = 0
    if requested <= 0:
        return {"reservation_id": None, "pass_id": None, "quantity": 0}

    try:
        refresh_daily_referral_free_access(int(user_id))
        with db_conn() as c:
            access = c.execute(
                """
                SELECT r.free_pass_id
                FROM users u
                JOIN referral_free_access r ON r.user_id=u.user_id
                WHERE u.user_id=%s
                  AND COALESCE(u.referral_points_blocked, 0)=0
                  AND r.free_until>NOW()
                FOR UPDATE OF r
                """,
                (int(user_id),),
            ).fetchone()
            if not access:
                return {"reservation_id": None, "pass_id": None, "quantity": 0}

            pass_id = int(access["free_pass_id"] or 0)
            totals = c.execute(
                """
                SELECT
                    COALESCE(SUM(used_quantity), 0) AS used_quantity,
                    COALESCE(SUM(
                        CASE WHEN settled_at IS NULL
                             THEN reserved_quantity ELSE 0 END
                    ), 0) AS reserved_quantity
                FROM referral_free_raksh_reservations
                WHERE user_id=%s AND pass_id=%s
                """,
                (int(user_id), pass_id),
            ).fetchone()
            available = _referral_free_raksh_remaining(
                REFERRAL_FREE_RAKSH_ACCOUNT_LIMIT,
                totals["used_quantity"] if totals else 0,
                totals["reserved_quantity"] if totals else 0,
            )
            reserved_quantity = min(requested, available)
            if reserved_quantity <= 0:
                return {
                    "reservation_id": None,
                    "pass_id": pass_id,
                    "quantity": 0,
                }

            reservation = c.execute(
                """
                INSERT INTO referral_free_raksh_reservations
                    (user_id, pass_id, source_type, source_id, service_type,
                     reserved_quantity)
                VALUES (%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    int(user_id),
                    pass_id,
                    str(source_type or "raksh"),
                    uuid.uuid4().hex,
                    str(service_type or ""),
                    reserved_quantity,
                ),
            ).fetchone()
        return {
            "reservation_id": int(reservation["id"]),
            "pass_id": pass_id,
            "quantity": reserved_quantity,
        }
    except Exception:
        logger.exception("تعذر حجز حصة الرشق المجانية")
        return {"reservation_id": None, "pass_id": None, "quantity": 0}


def settle_referral_free_raksh_reservation(
    reservation_id: int | None,
    successful_free_accounts: int,
    connection=None,
) -> bool:
    """يستهلك الناجح فقط ويحرر بقية الحجز، بأمان عند تكرار الإنهاء."""
    if not reservation_id:
        return False
    try:
        successful = max(0, int(successful_free_accounts or 0))
    except (TypeError, ValueError):
        successful = 0
    def _settle(c):
        return c.execute(
            """
            UPDATE referral_free_raksh_reservations
            SET used_quantity=LEAST(reserved_quantity, %s),
                reserved_quantity=0,
                settled_at=NOW()
            WHERE id=%s AND settled_at IS NULL
            RETURNING id
            """,
            (successful, int(reservation_id)),
        ).fetchone()

    try:
        if connection is not None:
            return bool(_settle(connection))
        with db_conn() as c:
            updated = _settle(c)
        return bool(updated)
    except Exception:
        logger.exception("تعذر إنهاء حصة الرشق المجانية")
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
