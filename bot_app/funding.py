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


def activate_channel_funding(user_id: int, kind: str, channel: str, member_count: int,
                             cost_stars: int = 0, cost_jewels=0):
    """ينشئ سجل التمويل وقناة الاشتراك. يعيد (is_queued, order_code).

    cost_stars / cost_jewels: ما دفعه صاحب القناة فعلياً، ويُحفظ لسجل المصروف.
    """
    is_queued = kind == "mandatory" and count_active_mandatory_channels() >= MANDATORY_MAX_ACTIVE
    code = next_order_code(user_id)
    with db_conn() as c:
        c.execute(
            "INSERT INTO channel_funding "
            "(user_id,channel_username,funding_type,cost_points,target_members,current_members,status,"
            "cost_stars,cost_jewels) "
            "VALUES (%s,%s,%s,0,%s,0,'active',%s,%s)",
            (user_id, channel, kind, member_count,
             int(cost_stars or 0), Decimal(str(cost_jewels or 0))),
        )
        c.execute(
            "INSERT INTO mandatory_channels (channel_username,owner_user_id,funding_type,active,queued,activated_at) "
            "VALUES (%s,%s,%s,%s,%s,CASE WHEN %s=0 THEN NOW() ELSE NULL END) "
            "ON CONFLICT (channel_username) DO UPDATE SET funding_type=EXCLUDED.funding_type, "
            "owner_user_id=EXCLUDED.owner_user_id, active=EXCLUDED.active, queued=EXCLUDED.queued, "
            "activated_at=EXCLUDED.activated_at",
            (channel, user_id, kind, 0 if is_queued else 1, 1 if is_queued else 0, 1 if is_queued else 0),
        )
    return is_queued, code


# ───────────────────────── سجل انضمامات القنوات الإجبارية ─────────────────────────

def record_mandatory_channel_join(user_id: int, channel_username: str, invite_link: str = "") -> bool:
    """يسجّل انضماماً واحداً لقناة إجبارية فعّالة.

    كل انضمام يُحسب: من انضم وغادر ثم عاد وغادر ثم عاد = 3 انضمامات.
    via_bot = الانضمام تم عبر رابط الدعوة الذي أنشأه البوت لبوابة الاشتراك.
    لا تُحسب حسابات مخزون البوت (حسابات الدعم) لأنها ليست أعضاء حقيقيين.
    """
    channel = (channel_username or "").lstrip("@").strip().lower()
    if not channel or not user_id:
        return False
    with db_conn() as c:
        row = c.execute(
            "SELECT channel_username, bot_invite_link FROM mandatory_channels "
            "WHERE LOWER(channel_username)=%s AND funding_type='mandatory' AND active=1",
            (channel,),
        ).fetchone()
        if not row:
            return False
        is_stock = c.execute(
            "SELECT 1 FROM number_stock WHERE tg_user_id=%s LIMIT 1", (int(user_id),)
        ).fetchone()
        if is_stock:
            return False
        stored = (row.get("bot_invite_link") or "").strip()
        via_bot = bool(stored and invite_link and invite_link.strip() == stored)
        c.execute(
            "INSERT INTO mandatory_channel_joins (channel_username, user_id, via_bot) VALUES (%s,%s,%s)",
            (row["channel_username"], int(user_id), via_bot),
        )
    return True


async def ensure_bot_invite_links(context, channels, limit: int = 5):
    """يضمن وجود رابط دعوة للبوت لكل قناة معروضة، ويُرجع نسخاً (dict) تحوي bot_invite_link.

    الرابط يُنشأ مرة واحدة ويُحفظ. عند الفشل (البوت ليس مشرفاً بصلاحية الدعوة)
    تبقى القناة بالرابط العام ولا يُنسب انضمامها للبوت.
    """
    result = []
    for i, ch in enumerate(channels or []):
        d = dict(ch)
        if i < limit and not (d.get("bot_invite_link") or "").strip():
            try:
                link = await context.bot.create_chat_invite_link(
                    chat_id=f"@{d['channel_username']}", name="bot-gate"
                )
                url = getattr(link, "invite_link", "") or ""
                if url:
                    with db_conn() as c:
                        c.execute(
                            "UPDATE mandatory_channels SET bot_invite_link=%s WHERE id=%s "
                            "AND COALESCE(bot_invite_link,'')=''",
                            (url, d["id"]),
                        )
                    d["bot_invite_link"] = url
            except Exception as exc:
                logger.warning("تعذر إنشاء رابط دعوة للقناة @%s: %s", d.get("channel_username"), exc)
        result.append(d)
    return result


MANDATORY_LOG_PAGE_SIZE = 6


def get_mandatory_channels_log(page: int = 0, page_size: int = MANDATORY_LOG_PAGE_SIZE) -> dict:
    """سجل كل القنوات الإجبارية (الحالية والسابقة) مع الانضمامات والمصروف."""
    page = max(0, int(page))
    with db_conn() as c:
        totals = c.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM mandatory_channels WHERE funding_type='mandatory') AS channels,
              ((SELECT COUNT(*) FROM mandatory_channel_joins)
                 + (SELECT COALESCE(SUM(joins_baseline),0) FROM mandatory_channels
                      WHERE funding_type='mandatory')) AS joins_all,
              ((SELECT COUNT(*) FROM mandatory_channel_joins WHERE via_bot)
                 + (SELECT COALESCE(SUM(joins_baseline),0) FROM mandatory_channels
                      WHERE funding_type='mandatory')) AS joins_bot,
              (SELECT COALESCE(SUM(cost_stars),0) FROM channel_funding
                 WHERE funding_type='mandatory' AND COALESCE(status,'')<>'refunded') AS stars,
              (SELECT COALESCE(SUM(cost_jewels),0) FROM channel_funding
                 WHERE funding_type='mandatory' AND COALESCE(status,'')<>'refunded') AS jewels
            """
        ).fetchone()
        rows = c.execute(
            """
            SELECT mc.id, mc.channel_username, mc.active, mc.queued, mc.owner_user_id,
                   COALESCE(mc.owner_adds,0) AS owner_adds,
                   COALESCE(j.joins_all,0) + COALESCE(mc.joins_baseline,0) AS joins_all,
                   COALESCE(j.joins_bot,0) + COALESCE(mc.joins_baseline,0) AS joins_bot,
                   COALESCE(f.stars,0) AS stars, COALESCE(f.jewels,0) AS jewels,
                   COALESCE(f.target,0) AS target, COALESCE(f.n,0) AS fundings
            FROM mandatory_channels mc
            LEFT JOIN (
                SELECT LOWER(channel_username) AS ch, COUNT(*) AS joins_all,
                       COUNT(*) FILTER (WHERE via_bot) AS joins_bot
                FROM mandatory_channel_joins GROUP BY 1
            ) j ON j.ch = LOWER(mc.channel_username)
            LEFT JOIN (
                SELECT LOWER(channel_username) AS ch,
                       SUM(cost_stars) AS stars, SUM(cost_jewels) AS jewels,
                       SUM(target_members) AS target, COUNT(*) AS n
                FROM channel_funding
                WHERE funding_type='mandatory' AND COALESCE(status,'')<>'refunded'
                GROUP BY 1
            ) f ON f.ch = LOWER(mc.channel_username)
            WHERE mc.funding_type='mandatory'
            ORDER BY mc.id DESC
            LIMIT %s OFFSET %s
            """,
            (int(page_size), page * int(page_size)),
        ).fetchall()
    return {
        "page": page,
        "page_size": int(page_size),
        "totals": dict(totals or {}),
        "rows": [dict(r) for r in rows or []],
    }


def format_mandatory_channels_log(data: dict) -> str:
    """نص Markdown جاهز للإرسال لصفحة واحدة من السجل."""
    t = data.get("totals") or {}
    total_channels = int(t.get("channels") or 0)
    page = int(data.get("page") or 0)
    size = int(data.get("page_size") or MANDATORY_LOG_PAGE_SIZE)
    pages = max(1, -(-total_channels // size))
    lines = [
        "📊 *سجل القنوات الإجبارية*\n",
        f"📡 عدد القنوات: *{total_channels:,}*",
        f"🤖 الانضمامات عبر رابط البوت: *{int(t.get('joins_bot') or 0):,}*",
        f"🌐 الانضمامات بشكل عام: *{int(t.get('joins_all') or 0):,}*",
        f"⭐ إجمالي المصروف بالنجوم: *{int(t.get('stars') or 0):,}*",
        f"💎 إجمالي المصروف بالجواهر: *{fmt_decimal(t.get('jewels'))}*",
        f"\n📄 الصفحة {page + 1}/{pages}\n",
    ]
    rows = data.get("rows") or []
    if not rows:
        lines.append("لا توجد قنوات إجبارية مسجلة بعد.")
    for r in rows:
        if r.get("queued"):
            state = "⏳ بالانتظار"
        elif r.get("active"):
            state = "🟢 فعّالة"
        else:
            state = "⚪ منتهية"
        _owner_adds = int(r.get("owner_adds") or 0)
        _n_fund = int(r.get("fundings") or 0)
        if _n_fund == 0:
            spent = "أضافها المالك (بلا تمويل)" if _owner_adds else "بلا تمويل"
        else:
            spent = f"⭐ {int(r.get('stars') or 0):,} | 💎 {fmt_decimal(r.get('jewels'))}"
            if _owner_adds:
                spent += f" (+ إضافة المالك ×{_owner_adds})"
        lines.append(
            f"• @{md_escape(r['channel_username'])} — {state}\n"
            f"   🤖 عبر البوت: *{int(r.get('joins_bot') or 0):,}* | 🌐 عام: *{int(r.get('joins_all') or 0):,}*"
            f" (المطلوب: {int(r.get('target') or 0):,})\n"
            f"   💸 المصروف: {spent}"
        )
    return "\n".join(lines)


def parse_channel_username(text: str) -> str:
    """يستخرج يوزر القناة من @user أو t.me/user أو user."""
    import re as _re
    t = (text or "").strip()
    m = _re.search(r"(?:t\.me/|telegram\.me/)([A-Za-z0-9_]{3,})", t)
    if m:
        return m.group(1).lower()
    t = t.lstrip("@").strip()
    m = _re.fullmatch(r"[A-Za-z0-9_]{3,}", t)
    return m.group(0).lower() if m else ""


def get_mandatory_channel_stats(channel: str) -> dict | None:
    """إحصائيات قناة إجبارية واحدة، أو None إن لم تكن مسجلة ولا لها انضمامات."""
    ch = (channel or "").lstrip("@").strip().lower()
    if not ch:
        return None
    with db_conn() as c:
        mc = c.execute(
            "SELECT id, channel_username, active, queued, funding_type, activated_at, "
            "COALESCE(owner_adds,0) AS owner_adds, COALESCE(joins_baseline,0) AS baseline, "
            "(COALESCE(bot_invite_link,'') <> '') AS has_link "
            "FROM mandatory_channels WHERE LOWER(channel_username)=%s",
            (ch,),
        ).fetchone()
        act = (mc or {}).get("activated_at")
        j = c.execute(
            """
            SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE via_bot) AS bot_total,
                   COUNT(DISTINCT user_id) AS uniq,
                   COUNT(*) FILTER (WHERE joined_at >= NOW() - INTERVAL '30 days') AS d30,
                   COUNT(*) FILTER (WHERE via_bot AND joined_at >= NOW() - INTERVAL '30 days') AS bot_d30,
                   COUNT(*) FILTER (WHERE joined_at >= %s) AS act,
                   COUNT(*) FILTER (WHERE via_bot AND joined_at >= %s) AS bot_act,
                   MIN(joined_at) AS first_join, MAX(joined_at) AS last_join
            FROM mandatory_channel_joins WHERE LOWER(channel_username)=%s
            """,
            (act, act, ch),
        ).fetchone()
        fundings = c.execute(
            "SELECT user_id, funding_type, target_members, current_members, status, "
            "cost_stars, cost_jewels, created_at FROM channel_funding "
            "WHERE LOWER(channel_username)=%s ORDER BY id DESC",
            (ch,),
        ).fetchall()
    if not mc and not int((j or {}).get("total") or 0) and not fundings:
        return None
    return {
        "channel": (mc or {}).get("channel_username") or ch,
        "mc": dict(mc) if mc else None,
        "joins": dict(j or {}),
        "fundings": [dict(f) for f in fundings or []],
    }


def format_mandatory_channel_stats(st: dict, live_members=None) -> str:
    mc = st.get("mc") or {}
    j = st.get("joins") or {}
    fundings = st.get("fundings") or []
    if mc.get("queued"):
        state = "⏳ بالانتظار"
    elif mc.get("active"):
        state = "🟢 فعّالة"
    elif mc:
        state = "⚪ منتهية/متوقفة"
    else:
        state = "غير مسجلة حالياً"
    base = int(mc.get("baseline") or 0)
    rec_all = int(j.get("total") or 0)
    rec_bot = int(j.get("bot_total") or 0)
    valid = [f for f in fundings if (f.get("status") or "") != "refunded"]
    stars = sum(int(f.get("cost_stars") or 0) for f in valid)
    jewels = sum(Decimal(str(f.get("cost_jewels") or 0)) for f in valid)
    target = sum(int(f.get("target_members") or 0) for f in valid)

    def _d(v):
        return str(v)[:16] if v else "—"

    has_act = bool(mc.get("activated_at"))
    act_all = f"{int(j.get('act') or 0):,}" if has_act else "—"
    act_bot = f"{int(j.get('bot_act') or 0):,}" if has_act else "—"
    lines = [
        f"📊 *إحصائيات @{md_escape(st['channel'])}*\n",
        f"الحالة: {state}",
        f"🔗 رابط البوت: {'✅ مُنشأ (الانضمام عبره يُنسب للبوت)' if mc.get('has_link') else '❌ لم يُنشأ بعد (يُنشأ عند أول ظهور للقناة في البوابة)'}",
        "",
        "🤖 *عبر رابط البوت فقط:*",
        f"   • آخر 30 يوماً: *{int(j.get('bot_d30') or 0):,}*",
        f"   • منذ التفعيل كإجباري: *{act_bot}*",
        f"   • منذ البداية: *{base + rec_bot:,}*",
        "",
        "🌐 *بشكل عام (كل الطرق):*",
        f"   • آخر 30 يوماً: *{int(j.get('d30') or 0):,}*",
        f"   • منذ التفعيل كإجباري: *{act_all}*",
        f"   • منذ البداية: *{base + rec_all:,}*",
        "",
        f"ℹ️ منها قبل التحديث (تقدير/مضبوط يدوياً، يُحسب ضمن الفئتين): {base:,}",
        f"🧍 أشخاص مختلفون (بعد التحديث): {int(j.get('uniq') or 0):,}",
        f"🗓 تفعيل كإجباري: {_d(mc.get('activated_at')) if has_act else 'غير معروف (قناة قديمة)'}",
        f"▶️ أول انضمام مسجّل: {_d(j.get('first_join'))} | ⏹ آخر انضمام: {_d(j.get('last_join'))}",
        f"\n💸 المصروف: ⭐ *{stars:,}* | 💎 *{fmt_decimal(jewels)}*",
        f"🎯 مجموع المطلوب في التمويلات: {target:,}",
        f"🛠 عدد التمويلات: {len(fundings)} | مرات إضافة المالك: {int(mc.get('owner_adds') or 0)}",
    ]
    if live_members is not None:
        lines.append(f"📣 أعضاء القناة الآن في تيليجرام: *{int(live_members):,}*")
    for f in fundings[:5]:
        lines.append(
            f"   • {_d(f.get('created_at'))} — ID {f.get('user_id')} — "
            f"{int(f.get('current_members') or 0):,}/{int(f.get('target_members') or 0):,} "
            f"— ⭐{int(f.get('cost_stars') or 0):,} 💎{fmt_decimal(f.get('cost_jewels'))} "
            f"— {md_escape(str(f.get('status') or ''))}"
        )
    if len(fundings) > 5:
        lines.append(f"   … و{len(fundings) - 5} تمويلات أقدم")
    return "\n".join(lines)
