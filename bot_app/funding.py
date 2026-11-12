"""تمويل القنوات: التسعير والتفعيل. الدفع بالنجوم أو الجواهر فقط (لا نقاط).

لا يستورد هذا الملف شيئاً من الحزمة؛ الأسماء المشتركة (db_conn, get_setting,
next_order_code ...) تُحقن فيه عند تحميل الحزمة، كبقية الأقسام.
"""

import math
from decimal import Decimal, ROUND_CEILING

FUND_KINDS = ("mandatory", "internal")
FUND_PAYMENTS = ("stars", "jewels")
FUND_KIND_LABELS = {"mandatory": "إجباري سريع", "internal": "داخلي بطيء"}


def stars_price_mandatory(member_count: int, tier1_max: int, t1_x100: int, t2_x100: int) -> int:
    """كل عضوين بنجمة حتى tier1_max، وبعدها كل 3 بنجمة (الأسعار ×100)."""
    x100 = t1_x100 if member_count <= tier1_max else t2_x100
    return max(1, math.ceil(member_count * x100 / 100))


def stars_price_internal(member_count: int, points_per_member, star_to_points) -> int:
    """يحوّل سعر العضو الداخلي القديم (نقاط) إلى نجوم بمعدل شحن النجوم، بحد أدنى نجمة."""
    rate = Decimal(str(star_to_points or 0))
    if rate <= 0:
        rate = Decimal(250)
    total_points = Decimal(int(member_count)) * Decimal(str(points_per_member or 0))
    return max(1, int((total_points / rate).to_integral_value(rounding=ROUND_CEILING)))


def funding_jewels_for_stars(stars: int, jewels_per_star) -> Decimal:
    """سعر الجواهر المكافئ للنجوم بنفس معدل شحن الجواهر (نجمة = jewels_per_star جوهرة)."""
    jps = Decimal(str(jewels_per_star or 0))
    if jps <= 0:
        jps = Decimal(1)
    return (Decimal(int(stars)) * jps).quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


def fund_min_members(kind: str) -> int:
    if kind == "mandatory":
        return int(get_setting("mandatory_stars_min_members") or "50")
    return int(get_setting("internal_channel_min_members") or "0")


def fund_quote(kind: str, member_count: int) -> dict:
    """السعر بالنجوم والجواهر لعدد أعضاء معيّن."""
    if kind == "mandatory":
        stars = stars_price_mandatory(
            member_count,
            int(get_setting("mandatory_stars_tier1_max") or "120"),
            int(get_setting("mandatory_stars_tier1_price_x100") or "50"),
            int(get_setting("mandatory_stars_tier2_price_x100") or "33"),
        )
    else:
        stars = stars_price_internal(
            member_count,
            get_setting("internal_channel_cost") or "100",
            get_star_to_points_rate(),
        )
    return {
        "stars": stars,
        "jewels": funding_jewels_for_stars(stars, get_jewels_per_star()),
        "min": fund_min_members(kind),
    }


def fund_price_lines(kind: str) -> str:
    """جدول الأسعار المعروض للعضو قبل إدخال العدد."""
    if kind == "mandatory":
        tier1 = int(get_setting("mandatory_stars_tier1_max") or "120")
        return (
            f"  • حتى {tier1:,} عضو: كل *عضوان* بـ *1 ⭐*\n"
            f"  • {tier1 + 1:,} وأكثر: كل *3 أعضاء* بـ *1 ⭐*\n"
        )
    one = fund_quote("internal", 1000)
    return f"  • السعر التقريبي: *{one['stars']:,} ⭐* لكل 1,000 عضو\n"


def activate_channel_funding(user_id: int, kind: str, channel: str, member_count: int):
    """ينشئ سجل التمويل وقناة الاشتراك. يعيد (is_queued, order_code)."""
    is_queued = kind == "mandatory" and count_active_mandatory_channels() >= MANDATORY_MAX_ACTIVE
    code = next_order_code(user_id)
    with db_conn() as c:
        c.execute(
            "INSERT INTO channel_funding "
            "(user_id,channel_username,funding_type,cost_points,target_members,current_members,status) "
            "VALUES (%s,%s,%s,0,%s,0,'active')",
            (user_id, channel, kind, member_count),
        )
        c.execute(
            "INSERT INTO mandatory_channels (channel_username,owner_user_id,funding_type,active,queued) "
            "VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (channel_username) DO UPDATE SET funding_type=EXCLUDED.funding_type, "
            "owner_user_id=EXCLUDED.owner_user_id, active=EXCLUDED.active, queued=EXCLUDED.queued",
            (channel, user_id, kind, 0 if is_queued else 1, 1 if is_queued else 0),
        )
    return is_queued, code
