"""عدّادات يومية مستقلة لطلبات الرشق: مجاني / نقاط / نجوم.

لكل نوع عدّاد وكود خاص به (مجاني #1، نقاط #1، نجوم #1 ...)، ويبدأ كل عدّاد
من 1 مجدداً مع أول طلب في اليوم الجديد (بتوقيت العراق، منتصف الليل 00:00).

التصفير لا يحتاج مهمة مجدولة: مفتاح العدّاد هو (اليوم، النوع)، وعند بدء يوم
جديد يُنشأ صف جديد يبدأ من 1 تلقائياً، فلا يرث شيئاً من اليوم السابق.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional

# توقيت العراق ثابت UTC+3 (لا توقيت صيفي).
IRAQ_TZ = timezone(timedelta(hours=3))

KIND_FREE = "free"
KIND_POINTS = "points"
KIND_STARS = "stars"
ALL_KINDS = (KIND_FREE, KIND_POINTS, KIND_STARS)

KIND_LABELS = {
    KIND_FREE: "🎁 مجاني",
    KIND_POINTS: "💰 نقاط",
    KIND_STARS: "⭐ نجوم",
}


def iraq_today(now: Optional[datetime] = None) -> date:
    """تاريخ اليوم الحالي بتوقيت العراق."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(IRAQ_TZ).date()


def classify_order_kind(payment_method: str, total_cost: int) -> str:
    """يحدد عدّاد الطلب: نجوم، مجاني، أو نقاط.

    المجاني = رشق بحسابات صاحب الطلب (contributor_free)، أو طلب بالنقاط
    كلفته صفر (إعفاء دائم أو حصة إحالة مجانية تغطي كل الطلب).
    أما الطلب الذي تُخصم منه نقاط فعلاً (حتى لو غطّت الحصة المجانية جزءاً
    منه) فيبقى ضمن عدّاد النقاط.
    """
    method = str(payment_method or "").strip().lower()
    if method == "stars":
        return KIND_STARS
    if method == "contributor_free":
        return KIND_FREE
    if int(total_cost or 0) <= 0:
        return KIND_FREE
    return KIND_POINTS


def allocate_daily_seq(cursor: Any, kind: str, now: Optional[datetime] = None) -> tuple[date, int]:
    """يحجز الرقم التالي للنوع في اليوم الحالي بشكل ذري (آمن مع الطلبات المتزامنة).

    يجب استدعاؤها داخل نفس الاتصال/المعاملة التي تُدخل الطلب، حتى إذا فشل
    إدخال الطلب لا يُستهلك رقم.
    """
    if kind not in ALL_KINDS:
        raise ValueError(f"نوع عدّاد غير معروف: {kind!r}")
    day = iraq_today(now)
    row = cursor.execute(
        """
        INSERT INTO raksh_daily_counters (day, kind, last_value)
        VALUES (%s, %s, 1)
        ON CONFLICT (day, kind)
        DO UPDATE SET last_value = raksh_daily_counters.last_value + 1
        RETURNING last_value
        """,
        (day, kind),
    ).fetchone()
    return day, int(row["last_value"])


def format_order_code(kind: Optional[str], seq: Optional[int]) -> str:
    """مثال: «مجاني #3». يعيد نصاً فارغاً إن لم يكن للطلب كود يومي."""
    if not kind or not seq:
        return ""
    return f"{KIND_LABELS.get(kind, kind)} #{int(seq)}"


def order_display_code(order: Mapping[str, Any]) -> str:
    """الكود المعروض للمستخدم؛ الطلبات القديمة بلا كود يومي تعرض رقمها العام."""
    code = format_order_code(order.get("daily_kind"), order.get("daily_seq"))
    return code or f"#{int(order['id'])}"
