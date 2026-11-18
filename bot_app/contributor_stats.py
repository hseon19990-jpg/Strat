"""إحصاءات المالك عن الأعضاء الذين وضعوا أرقاماً في البوت وأرباحهم.

ثلاث شاشات (تُفتح من قسم تدقيق المؤجّرين):
  * ترتيب الأعضاء حسب عدد الأرقام التي وضعوها مع أرباح كل عضو،
  * أكثر الأرقام ربحاً،
  * الأرقام التي أُضيفت ثم طُرد البوت منها وكم ربحت.

الأرباح كلها بالنقاط، ومصدرها جدول raksh_contributor_earnings (حصة العضو
المسجّلة فعلاً عند نجاح كل طلب رشق).
"""

from __future__ import annotations

import html as _html
import logging
from datetime import timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .database import db_conn

logger = logging.getLogger(__name__)

_IQ_TZ = timezone(timedelta(hours=3))
_LIMIT = 15
_MAX_TEXT = 3900

# الحساب «مطرود» = غير محذوف وغير مجمّد ولم يُبَع، وجلسة البوت ميتة أو غائبة.
_DEAD_SQL = (
    "ns.deleted_at IS NULL AND ns.frozen_at IS NULL "
    "AND ns.ever_sold IS NOT TRUE "
    "AND (ns.last_authorized IS FALSE OR ns.session_string IS NULL "
    "OR BTRIM(ns.session_string) = '')"
)
_ALIVE_SQL = (
    "ns.deleted_at IS NULL AND ns.frozen_at IS NULL "
    "AND ns.last_authorized IS NOT FALSE "
    "AND ns.session_string IS NOT NULL AND BTRIM(ns.session_string) <> ''"
)

_BACK = InlineKeyboardButton("🔙 التدقيق", callback_data="os:ma:menu")


def _h(value) -> str:
    return _html.escape(str(value if value is not None else ""))


def _mask(phone) -> str:
    digits = str(phone or "").strip().lstrip("+")
    if len(digits) <= 7:
        return "+" + digits[:2] + "***"
    return "+" + digits[:4] + "****" + digits[-3:]


def _fmt_dt(value) -> str:
    if not value:
        return "—"
    try:
        return value.astimezone(_IQ_TZ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)[:16]


def _fmt_span(start, end) -> str:
    try:
        seconds = int((end - start).total_seconds())
    except Exception:
        return "—"
    seconds = max(seconds, 0)
    if seconds < 3600:
        return f"{max(seconds // 60, 1)} دقيقة"
    if seconds < 86400:
        return f"{seconds // 3600} ساعة"
    return f"{seconds // 86400} يوم"


def _who(row) -> str:
    return (
        row.get("full_name")
        or (f"@{row['username']}" if row.get("username") else "")
        or str(row.get("uid") or "—")
    )


def _finish(lines: list) -> tuple:
    text = "\n".join(lines)
    if len(text) > _MAX_TEXT:
        text = text[: _MAX_TEXT - 20] + "…"
    return text, InlineKeyboardMarkup([[_BACK]])


def format_top_contributors(rows: list, members: int, paid_total: int) -> tuple:
    if not rows:
        return _finish(["🏆 لم يضف أي عضو أرقاماً بعد."])
    lines = [
        "🏆 <b>أكثر الأعضاء وضعاً للأرقام</b>",
        f"👥 أعضاء وضعوا أرقاماً: {members} • مجموع أرباحهم: {paid_total} نقطة",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}) {_h(_who(row))} — {int(row['total'])} رقم "
            f"(شغال {int(row['alive'])} • مطرود {int(row['dead'])})"
            f" • ربحه {int(row['earned'] or 0)} نقطة"
        )
    return _finish(lines)


def format_best_numbers(rows: list) -> tuple:
    if not rows:
        return _finish(["💎 لا توجد أرباح مسجّلة لأي رقم بعد."])
    lines = ["💎 <b>أكثر الأرقام ربحاً</b>", ""]
    for index, row in enumerate(rows, start=1):
        if row.get("deleted_at"):
            state = "🗑 محذوف"
        elif row.get("frozen_at"):
            state = "🧊 مجمّد"
        elif row.get("last_authorized") is False or not row.get("has_session"):
            state = "🚫 مطرود"
        else:
            state = "✅ شغال"
        lines.append(
            f"{index}) {_mask(row.get('phone_number'))} — ربح {int(row['earned'] or 0)} نقطة"
            f" من {int(row['orders'] or 0)} طلب • {state}\n"
            f"   👤 {_h(_who(row))}"
        )
    return _finish(lines)


def format_kicked_numbers(rows: list, count: int, earned_total: int) -> tuple:
    if not rows:
        return _finish(["🚫 لا توجد أرقام مضافة طُرد البوت منها حالياً. ✅"])
    lines = [
        "🚫 <b>أرقام أُضيفت ثم طُرد البوت منها</b>",
        f"عددها: {count} • مجموع ما ربحته: {earned_total} نقطة",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        kicked = row.get("kicked_at")
        span = (
            f" • عملت {_fmt_span(row['added_at'], kicked)}"
            if kicked and row.get("added_at")
            else ""
        )
        lines.append(
            f"{index}) {_mask(row.get('phone_number'))} — ربحت {int(row['earned'] or 0)} نقطة"
            f" من {int(row['orders'] or 0)} طلب\n"
            f"   👤 {_h(_who(row))} • أُضيف {_fmt_dt(row.get('added_at'))}"
            f" • طُرد {_fmt_dt(kicked) if kicked else 'غير مسجّل'}{span}"
        )
    if count > len(rows):
        lines.append(f"\n… ويُعرض أعلى {len(rows)} حسب الأرباح.")
    return _finish(lines)


def top_contributors_view() -> tuple:
    with db_conn() as c:
        rows = c.execute(
            f"""
            SELECT ns.contributed_by AS uid, u.username, u.full_name,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE {_ALIVE_SQL}) AS alive,
                   COUNT(*) FILTER (WHERE {_DEAD_SQL}) AS dead,
                   (SELECT COALESCE(SUM(e.share_points), 0)
                      FROM raksh_contributor_earnings e
                     WHERE e.contributor_id = ns.contributed_by) AS earned
            FROM number_stock ns
            LEFT JOIN users u ON u.user_id = ns.contributed_by
            WHERE ns.contributed_by IS NOT NULL
            GROUP BY ns.contributed_by, u.username, u.full_name
            ORDER BY total DESC, earned DESC
            LIMIT {_LIMIT}
            """
        ).fetchall()
        summary = c.execute(
            "SELECT COUNT(DISTINCT contributed_by) AS members "
            "FROM number_stock WHERE contributed_by IS NOT NULL"
        ).fetchone()
        paid = c.execute(
            "SELECT COALESCE(SUM(share_points), 0) AS paid "
            "FROM raksh_contributor_earnings"
        ).fetchone()
    return format_top_contributors(
        [dict(r) for r in rows],
        int((summary or {}).get("members") or 0),
        int((paid or {}).get("paid") or 0),
    )


def best_numbers_view() -> tuple:
    with db_conn() as c:
        rows = c.execute(
            f"""
            SELECT ns.id, ns.phone_number, ns.contributed_by AS uid,
                   u.username, u.full_name, ns.deleted_at, ns.frozen_at,
                   ns.last_authorized,
                   (ns.session_string IS NOT NULL
                    AND BTRIM(ns.session_string) <> '') AS has_session,
                   COALESCE(SUM(e.share_points), 0) AS earned,
                   COUNT(e.id) AS orders
            FROM raksh_contributor_earnings e
            JOIN number_stock ns ON ns.id = e.stock_id
            LEFT JOIN users u ON u.user_id = ns.contributed_by
            GROUP BY ns.id, u.username, u.full_name
            ORDER BY earned DESC, orders DESC
            LIMIT {_LIMIT}
            """
        ).fetchall()
    return format_best_numbers([dict(r) for r in rows])


def kicked_numbers_view() -> tuple:
    with db_conn() as c:
        rows = c.execute(
            f"""
            SELECT ns.id, ns.phone_number, ns.contributed_by AS uid,
                   u.username, u.full_name, ns.added_at, ns.kicked_at,
                   COALESCE((SELECT SUM(e.share_points)
                               FROM raksh_contributor_earnings e
                              WHERE e.stock_id = ns.id), 0) AS earned,
                   (SELECT COUNT(*) FROM raksh_contributor_earnings e
                     WHERE e.stock_id = ns.id) AS orders
            FROM number_stock ns
            LEFT JOIN users u ON u.user_id = ns.contributed_by
            WHERE ns.contributed_by IS NOT NULL AND {_DEAD_SQL}
            ORDER BY earned DESC, ns.kicked_at DESC NULLS LAST
            LIMIT {_LIMIT}
            """
        ).fetchall()
        totals = c.execute(
            f"""
            SELECT COUNT(*) AS cnt,
                   COALESCE(SUM((SELECT COALESCE(SUM(e.share_points), 0)
                                   FROM raksh_contributor_earnings e
                                  WHERE e.stock_id = ns.id)), 0) AS earned
            FROM number_stock ns
            WHERE ns.contributed_by IS NOT NULL AND {_DEAD_SQL}
            """
        ).fetchone()
    return format_kicked_numbers(
        [dict(r) for r in rows],
        int((totals or {}).get("cnt") or 0),
        int((totals or {}).get("earned") or 0),
    )


def stats_view(action: str) -> tuple:
    """يرجع (النص, الأزرار) للشاشة المطلوبة أو رسالة خطأ آمنة."""
    try:
        if action == "top":
            return top_contributors_view()
        if action == "best":
            return best_numbers_view()
        if action == "kickedearn":
            return kicked_numbers_view()
    except Exception:
        logger.exception("فشل بناء إحصاءات الأعضاء (%s)", action)
        return _finish(["❌ تعذر قراءة الإحصاءات الآن. حاول لاحقاً."])
    return _finish(["⚠️ خيار غير معروف."])
