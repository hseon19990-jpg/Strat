"""عرض الطلبات: «عرض طلباتي» للعضو و«الطلبات» للمالك.

العضو  : طلباته فقط (الخدمة، الكود، الحالة، الواصل/الباقي، المدفوع) دون ذكر الموقع
         المنفِّذ أو رقم الطلب عنده أو تكلفته، مع «🔄 تتبّع» و«🔁 إعادة» لكل طلب.
المالك : جدول مختصر (الطلب │ المشتري │ المدفوع │ الحالة │ الباقي/الواصل) مع
         «التالي/رجوع»، فلاتر (الحالة، الفترة، مشتري محدد)، تصدير CSV،
         وتقرير يومي تلقائي يصل المالك.

الحالة المباشرة تُسأل من الموقع للطلبات غير المنتهية فقط؛ المنتهية تُقرأ من
قاعدة البيانات دون أي طلب خارجي.

صيغة callback_data:
  ov:me:<offset>                     طلباتي
  ov:tr:<id>:<offset>                تتبّع طلب واحد
  ov:re:<id>:<offset>                شاشة إعادة الطلب   (ov:ru = نفس الرابط، ov:rn = رابط جديد)
  ov:own:<offset>[:<s>:<p>:<u>]      جدول المالك (s=حالة، p=فترة، u=مشتري)
  ov:flt:<s>:<p>:<u>                 شاشة الفلاتر      (ov:fb = اختيار مشتري)
  ov:csv:<s>:<p>:<u>                 تصدير CSV
  ov:rep / ov:rept                   تقرير 24 ساعة الآن / تفعيل-تعطيل التقرير اليومي
"""

import asyncio
import csv
import html as _html
import io
from datetime import time as _dtime

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

OV_USER_PAGE_SIZE = 5
OV_OWNER_PAGE_SIZE = 10
OV_LIVE_TIMEOUT = 10          # أقصى انتظار (ثوانٍ) لحالة الموقع المباشرة
OV_MAX_LIVE_LOOKUPS = 10      # سقف أسئلة الموقع في الصفحة الواحدة
OV_TG_LIMIT = 3900
OV_CSV_MAX_ROWS = 5000
OV_BUYER_STATE = "ov_await_buyer"
OV_REPORT_ENABLED_SETTING = "orders_report_enabled"   # "0" = متوقف، غير ذلك = يعمل
OV_REPORT_HOUR_SETTING = "orders_report_hour"
OV_REPORT_DEFAULT_HOUR = 9
OV_REPORT_TZ = "Asia/Baghdad"
OV_STUCK_HOURS = 6

_OV_ACTIVE = {"pending", "processing", "in progress", "inprogress", "in_progress"}
_OV_ACTIVE_SQL = "('pending','processing','in progress','inprogress','in_progress')"
_OV_CANCELLED_SQL = "('cancelled','canceled','failed','error','refunded')"

_OV_STATUS_AR = {
    "pending": "⏳ قيد الانتظار",
    "processing": "🔄 قيد التنفيذ",
    "in progress": "🔄 قيد التنفيذ",
    "inprogress": "🔄 قيد التنفيذ",
    "in_progress": "🔄 قيد التنفيذ",
    "completed": "✅ مكتمل",
    "partial": "⚠️ مكتمل جزئياً",
    "cancelled": "❌ ملغي",
    "canceled": "❌ ملغي",
    "failed": "❌ فشل",
    "error": "❌ فشل",
    "refunded": "↩️ مُسترد",
    "refund_processing": "🔄 استرداد قيد المعالجة",
    "refund_required": "⚠️ استرداد قيد المراجعة",
}

OV_STATUS_FILTERS = (
    ("a", "الكل"), ("p", "⏳ قيد التنفيذ"), ("c", "✅ مكتمل"),
    ("r", "⚠️ جزئي"), ("x", "❌ ملغي"),
)
OV_PERIOD_FILTERS = (("a", "كل الوقت"), ("t", "24 ساعة"), ("w", "7 أيام"), ("m", "30 يوماً"))
_OV_PERIOD_HOURS = {"t": 24, "w": 24 * 7, "m": 24 * 30}


# ───────────────────── دوال نقية (قابلة للاختبار بدون قاعدة بيانات) ─────────────────────

def ov_esc(value, default="—") -> str:
    text = str(value).strip() if value is not None else ""
    return _html.escape(text) if text else default


def ov_short(value, limit=22) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return _html.escape(text) if text else "—"


def ov_paid_text(order) -> str:
    """المدفوع بالعملة التي استُخدمت فعلاً: نقاط / نجوم / جواهر / مجاناً."""
    method = str(order.get("payment_method") or "points").lower()
    if method == "stars":
        return f"{int(order.get('cost_stars') or 0):,} ⭐"
    if method == "jewels":
        return f"{int(order.get('cost_jewels') or 0):,} 💎"
    if method == "free":
        return "مجاناً 🎁"
    return f"{int(order.get('cost_points') or 0):,} نقطة"


def ov_resolve(order, live=None):
    """يحدد (مفتاح الحالة، النص، الواصل، الباقي) — الواصل/الباقي قد يكونان None."""
    live = live if isinstance(live, dict) else {}
    local = str(order.get("status") or "").strip().lower()
    remote = str(live.get("status") or "").strip().lower()
    key = remote or local
    if not remote and local == "completed" and int(order.get("partial_refund_pts") or 0) > 0:
        key = "partial"

    quantity = max(0, int(order.get("quantity") or 0))
    delivered = remains = None
    try:
        if live.get("remains") is not None:
            remains = min(quantity, max(0, int(float(live.get("remains")))))
            delivered = quantity - remains
    except (TypeError, ValueError):
        delivered = remains = None
    if remains is None and key == "completed":
        delivered, remains = quantity, 0
    label = _OV_STATUS_AR.get(key, _html.escape(key) if key else "غير معروف")
    return key, label, delivered, remains


def ov_progress_text(quantity, delivered, remains) -> str:
    quantity = int(quantity or 0)
    if delivered is None or remains is None:
        return f"الطلب {quantity:,} · الواصل غير معروف"
    percent = int(round(delivered * 100 / quantity)) if quantity else 0
    return f"وصل {delivered:,} من {quantity:,} ({percent}%) · الباقي {remains:,}"


def ov_needs_live(order, force=False) -> bool:
    status = str(order.get("status") or "").strip().lower()
    has_ids = bool(str(order.get("api_order_id") or "").strip()) and bool(order.get("svc_api_id"))
    return has_ids and (force or status in _OV_ACTIVE)


def ov_split_message(text: str, limit: int = OV_TG_LIMIT):
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


# ── الفلاتر ──

def ov_parse_filter(parts):
    """يقرأ [s, p, u] من أجزاء callback ويعيد قيماً صالحة دائماً (الافتراضي: بلا فلتر)."""
    parts = list(parts or [])
    status = parts[0] if len(parts) > 0 and parts[0] in dict(OV_STATUS_FILTERS) else "a"
    period = parts[1] if len(parts) > 1 and parts[1] in dict(OV_PERIOD_FILTERS) else "a"
    buyer = 0
    if len(parts) > 2 and str(parts[2]).isdigit() and len(str(parts[2])) <= 15:
        buyer = int(parts[2])
    return status, period, buyer


def ov_filter_suffix(status="a", period="a", buyer=0) -> str:
    return f"{status}:{period}:{int(buyer)}"


def ov_filter_is_default(status="a", period="a", buyer=0) -> bool:
    return (status, period, int(buyer)) == ("a", "a", 0)


def ov_filter_describe(status="a", period="a", buyer=0) -> str:
    if ov_filter_is_default(status, period, buyer):
        return ""
    bits = []
    if status != "a":
        bits.append(dict(OV_STATUS_FILTERS)[status])
    if period != "a":
        bits.append(dict(OV_PERIOD_FILTERS)[period])
    if buyer:
        bits.append(f"المشتري {buyer}")
    return "🎛 الفلتر: " + " · ".join(bits)


def ov_build_query_parts(status="a", period="a", buyer=0, user_id=None):
    """يبني (FROM، شروط WHERE، وسائط) — نقية لتسهّل اختبارها."""
    conds, params = [], []
    if user_id is not None:
        conds.append("o.user_id = %s")
        params.append(int(user_id))
    elif buyer:
        conds.append("o.user_id = %s")
        params.append(int(buyer))
    if status == "p":
        conds.append(f"LOWER(COALESCE(o.status,'')) IN {_OV_ACTIVE_SQL}")
    elif status == "c":
        conds.append("LOWER(COALESCE(o.status,'')) = 'completed' AND COALESCE(o.partial_refund_pts,0) = 0")
    elif status == "r":
        conds.append("LOWER(COALESCE(o.status,'')) = 'completed' AND COALESCE(o.partial_refund_pts,0) > 0")
    elif status == "x":
        conds.append(f"LOWER(COALESCE(o.status,'')) IN {_OV_CANCELLED_SQL}")
    hours = _OV_PERIOD_HOURS.get(period)
    if hours:
        conds.append("o.ts >= NOW() - (%s * INTERVAL '1 hour')")
        params.append(hours)
        source = _OV_TS_SOURCE
    else:
        source = "orders o"
    where = ("WHERE " + " AND ".join(f"({c})" for c in conds)) if conds else ""
    return source, where, tuple(params)


# created_at نص؛ نحوّله لوقت فقط إن كان بصيغة تاريخ صحيحة حتى لا يفشل الاستعلام كله.
_OV_TS_SOURCE = (
    "(SELECT x.*, CASE WHEN x.created_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}' "
    "THEN x.created_at::timestamptz END AS ts FROM orders x) o"
)


def ov_csv_cell(value):
    """يمنع حقن الصيغ في Excel: أي خلية تبدأ بـ = + - @ تُسبق بفاصلة عليا."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def ov_build_csv(rows, lives=None) -> bytes:
    """CSV بترميز UTF-8 مع BOM ليفتح بالعربية سليماً في Excel."""
    lives = lives or {}
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["كود الطلب", "التاريخ", "ID المشتري", "الاسم", "اليوزر", "الخدمة",
                     "الكمية", "الواصل", "الباقي", "الحالة", "المدفوع", "تكلفة الموقع $", "الرابط"])
    for o in rows:
        _k, label, delivered, remains = ov_resolve(o, lives.get(o.get("id")))
        status_text = label.split(" ", 1)[-1]
        writer.writerow([ov_csv_cell(v) for v in (
            o.get("order_code"), str(o.get("created_at") or "")[:19], o.get("user_id"),
            o.get("u_full_name"), o.get("u_username"), o.get("s_name_ar"),
            o.get("quantity"), "" if delivered is None else delivered,
            "" if remains is None else remains, status_text, ov_paid_text(o),
            o.get("provider_cost_usd") or 0, o.get("link"),
        )])
    return ("﻿" + out.getvalue()).encode("utf-8")


# ── النصوص ──

def ov_render_user_page(rows, lives, offset, total, active_count) -> str:
    lines = [
        "📦 <b>طلباتي</b>",
        f"المجموع: <b>{total:,}</b> · قيد التنفيذ: <b>{active_count:,}</b>",
        "",
    ]
    for index, order in enumerate(rows):
        lines += ov_user_block(order, lives.get(order.get("id")), offset + index + 1)
        lines.append("➖➖➖➖➖")
    return "\n".join(lines).rstrip("➖\n ")


def ov_user_block(order, live, number=None):
    _key, label, delivered, remains = ov_resolve(order, live)
    quantity = int(order.get("quantity") or 0)
    prefix = f"<b>{number}.</b> " if number else ""
    return [
        f"{prefix}🧾 <code>{ov_esc(order.get('order_code'))}</code>"
        f" — {ov_short(order.get('s_name_ar') or 'خدمة', 30)}",
        f"📶 {label}",
        f"📊 {ov_progress_text(quantity, delivered, remains)}",
        f"💳 المدفوع: {ov_paid_text(order)}",
        f"🔗 {ov_short(order.get('link'), 38)}",
        f"🕒 {ov_esc(str(order.get('created_at') or '')[:16])}",
    ]


def ov_render_owner_page(rows, lives, offset, total, active_count, filter_text="") -> str:
    lines = [
        "📊 <b>الطلبات</b>",
        f"({offset + 1}–{offset + len(rows)} من {total:,}) · قيد التنفيذ: <b>{active_count:,}</b>",
    ]
    if filter_text:
        lines.append(_html.escape(filter_text))
    lines += ["<i>الطلب │ المشتري │ المدفوع │ الحالة │ الباقي/الواصل</i>", ""]
    for order in rows:
        _key, label, delivered, remains = ov_resolve(order, lives.get(order.get("id")))
        quantity = int(order.get("quantity") or 0)
        name = ov_short(order.get("u_full_name"), 18)
        uname = f" @{ov_esc(order.get('u_username'))}" if order.get("u_username") else ""
        if delivered is None or remains is None:
            progress = f"؟/{quantity:,}"
        else:
            progress = f"{delivered:,}/{quantity:,} (باقي {remains:,})"
        lines += [
            f"🧾 <code>{ov_esc(order.get('order_code'))}</code> │ 👤 {name}{uname}"
            f" <code>{order.get('user_id')}</code>",
            f"   💳 {ov_paid_text(order)} │ {label} │ 📦 {progress}",
            "",
        ]
    return "\n".join(lines).rstrip()


def ov_nav_row(prefix, offset, page_size, total, suffix=""):
    """صف التنقل: «رجوع» للصفحة الأحدث، «التالي» للأقدم."""
    tail = f":{suffix}" if suffix else ""
    row = []
    if offset > 0:
        row.append(InlineKeyboardButton(
            "↩️ رجوع", callback_data=f"{prefix}:{max(0, offset - page_size)}{tail}"))
    if offset + page_size < total:
        row.append(InlineKeyboardButton(
            "التالي ⏭", callback_data=f"{prefix}:{offset + page_size}{tail}"))
    return row


def ov_reorder_problem(order, service):
    """يعيد نص المشكلة إن تعذّرت إعادة الطلب، وإلا None."""
    if not order:
        return "⚠️ لم أجد هذا الطلب."
    if not service:
        return "⚠️ هذه الخدمة لم تعد موجودة."
    if not service.get("active"):
        return "⚠️ هذه الخدمة متوقفة حالياً."
    if service.get("service_type") == "mandatory_sub":
        return "⚠️ هذا النوع من الخدمات لا يدعم إعادة الطلب السريعة."
    if not str(order.get("link") or "").strip():
        return "⚠️ لا يوجد رابط محفوظ لهذا الطلب."
    quantity = int(order.get("quantity") or 0)
    if quantity < int(service.get("min_qty") or 1) or quantity > int(service.get("max_qty") or 10**9):
        return (f"⚠️ الكمية السابقة ({quantity:,}) خارج النطاق الحالي للخدمة "
                f"({service.get('min_qty')}–{service.get('max_qty')}). اطلب الخدمة من جديد.")
    return None


# ── التقرير اليومي ──

def ov_render_report(stats, top_services, stuck) -> str:
    cur, prev = stats["cur"], stats["prev"]
    delta = cur["total"] - prev["total"]
    arrow = "📈" if delta > 0 else ("📉" if delta < 0 else "➖")
    lines = [
        "📈 <b>تقرير آخر 24 ساعة</b>",
        "",
        f"📦 الطلبات: <b>{cur['total']:,}</b> {arrow} ({delta:+,} عن اليوم السابق)",
        f"👥 مشترون مختلفون: <b>{cur['buyers']:,}</b>",
        f"✅ مكتمل: {cur['completed']:,} · ⚠️ جزئي: {cur['partial']:,}",
        f"⏳ قيد التنفيذ: {cur['active']:,} · ❌ ملغي: {cur['cancelled']:,}",
        "",
        "💰 <b>الإيراد (بعد استبعاد الملغي)</b>",
        f"• {cur['points']:,} نقطة · {cur['stars']:,} ⭐ · {cur['jewels']:,} 💎"
        + (f" · {cur['free']:,} مجاني" if cur["free"] else ""),
        f"🌐 تكلفة التنفيذ: <b>${cur['provider_usd']:.2f}</b>",
    ]
    if top_services:
        lines += ["", "🏆 <b>الأكثر طلباً</b>"]
        for index, (name, count) in enumerate(top_services, 1):
            lines.append(f"{index}. {ov_short(name, 32)} — {count:,}")
    if stuck:
        lines += ["", f"🚨 طلبات عالقة أكثر من {OV_STUCK_HOURS} ساعات: <b>{stuck:,}</b> (افتح «📊 الطلبات» ← فلتر ⏳)"]
    return "\n".join(lines)


# ───────────────────────────── قاعدة البيانات ─────────────────────────────

def ov_fetch_page(offset, limit, user_id=None, status="a", period="a", buyer=0):
    """يعيد (الصفوف، الإجمالي، عدد غير المنتهية). user_id=None ⇒ كل الطلبات (للمالك)."""
    offset = max(0, int(offset))
    source, where, params = ov_build_query_parts(status, period, buyer, user_id)
    with db_conn() as c:
        rows = c.execute(
            "SELECT o.*, u.full_name AS u_full_name, u.username AS u_username, "
            "s.name_ar AS s_name_ar, s.panel AS svc_panel, s.api_service_id AS svc_api_id "
            f"FROM {source} LEFT JOIN users u ON u.user_id = o.user_id "
            f"LEFT JOIN services s ON s.id = o.service_id {where} "
            "ORDER BY o.id DESC LIMIT %s OFFSET %s",
            params + (int(limit), offset),
        ).fetchall()
        counts = c.execute(
            "SELECT COUNT(*) AS total, "
            f"COUNT(*) FILTER (WHERE LOWER(COALESCE(o.status,'')) IN {_OV_ACTIVE_SQL}) AS active "
            f"FROM {source} {where}",
            params,
        ).fetchone()
    return [dict(r) for r in rows], int(counts["total"] or 0), int(counts["active"] or 0)


def ov_fetch_one(order_id):
    with db_conn() as c:
        row = c.execute(
            "SELECT o.*, u.full_name AS u_full_name, u.username AS u_username, "
            "s.name_ar AS s_name_ar, s.panel AS svc_panel, s.api_service_id AS svc_api_id "
            "FROM orders o LEFT JOIN users u ON u.user_id = o.user_id "
            "LEFT JOIN services s ON s.id = o.service_id WHERE o.id = %s",
            (int(order_id),),
        ).fetchone()
    return dict(row) if row else None


def ov_fetch_service(service_id):
    with db_conn() as c:
        row = c.execute("SELECT * FROM services WHERE id = %s", (service_id,)).fetchone()
    return dict(row) if row else None


def ov_collect_report():
    """يجمع أرقام آخر 24 ساعة (والـ24 قبلها للمقارنة) بعمليات قراءة فقط."""
    non_cancel = f"LOWER(COALESCE(o.status,'')) NOT IN {_OV_CANCELLED_SQL}"
    method = "LOWER(COALESCE(o.payment_method,'points'))"
    window = "o.ts >= NOW() - INTERVAL '24 hours'"
    with db_conn() as c:
        cur = c.execute(
            f"""
            SELECT COUNT(*) AS total,
                   COUNT(DISTINCT o.user_id) AS buyers,
                   COUNT(*) FILTER (WHERE LOWER(COALESCE(o.status,''))='completed'
                                    AND COALESCE(o.partial_refund_pts,0)=0) AS completed,
                   COUNT(*) FILTER (WHERE LOWER(COALESCE(o.status,''))='completed'
                                    AND COALESCE(o.partial_refund_pts,0)>0) AS partial,
                   COUNT(*) FILTER (WHERE LOWER(COALESCE(o.status,'')) IN {_OV_ACTIVE_SQL}) AS active,
                   COUNT(*) FILTER (WHERE LOWER(COALESCE(o.status,'')) IN {_OV_CANCELLED_SQL}) AS cancelled,
                   COALESCE(SUM(o.cost_points) FILTER (WHERE {non_cancel} AND {method} NOT IN ('stars','jewels','free')),0) AS points,
                   COALESCE(SUM(o.cost_stars) FILTER (WHERE {non_cancel} AND {method}='stars'),0) AS stars,
                   COALESCE(SUM(o.cost_jewels) FILTER (WHERE {non_cancel} AND {method}='jewels'),0) AS jewels,
                   COUNT(*) FILTER (WHERE {non_cancel} AND {method}='free') AS free,
                   COALESCE(SUM(o.provider_cost_usd) FILTER (WHERE {non_cancel}),0) AS provider_usd
            FROM {_OV_TS_SOURCE} WHERE {window}
            """
        ).fetchone()
        prev = c.execute(
            f"SELECT COUNT(*) AS total FROM {_OV_TS_SOURCE} "
            "WHERE o.ts >= NOW() - INTERVAL '48 hours' AND o.ts < NOW() - INTERVAL '24 hours'"
        ).fetchone()
        top = c.execute(
            f"""
            SELECT COALESCE(s.name_ar, 'خدمة #' || o.service_id::text) AS name, COUNT(*) AS cnt
            FROM {_OV_TS_SOURCE} LEFT JOIN services s ON s.id = o.service_id
            WHERE {window} GROUP BY 1 ORDER BY cnt DESC LIMIT 5
            """
        ).fetchall()
        stuck = c.execute(
            f"SELECT COUNT(*) AS n FROM {_OV_TS_SOURCE} "
            f"WHERE LOWER(COALESCE(o.status,'')) IN {_OV_ACTIVE_SQL} "
            "AND o.ts < NOW() - (%s * INTERVAL '1 hour')",
            (OV_STUCK_HOURS,),
        ).fetchone()
    cur_d = {k: (float(v) if k == "provider_usd" else int(v or 0)) for k, v in dict(cur).items()}
    return (
        {"cur": cur_d, "prev": {"total": int(prev["total"] or 0)}},
        [(r["name"], int(r["cnt"])) for r in top],
        int(stuck["n"] or 0),
    )


async def ov_fetch_live(rows, force=False):
    """يسأل الموقع بالتوازي عن الطلبات غير المنتهية فقط. أي فشل = بلا حالة مباشرة."""
    targets = [o for o in rows if ov_needs_live(o, force)][:OV_MAX_LIVE_LOOKUPS]
    if not targets:
        return {}

    async def one(order):
        try:
            panel = int(order.get("svc_panel") or 1)
        except (TypeError, ValueError):
            panel = 1
        try:
            result = await asyncio.to_thread(
                smm_order_status, str(order["api_order_id"]).strip(), panel=panel)
        except Exception:
            return order["id"], None
        if isinstance(result, dict) and "error" not in result and result.get("status"):
            return order["id"], result
        return order["id"], None

    try:
        done = await asyncio.wait_for(
            asyncio.gather(*(one(o) for o in targets)), timeout=OV_LIVE_TIMEOUT)
    except Exception:
        return {}
    return {oid: res for oid, res in done if res}


# ───────────────────────────── العرض والأزرار ─────────────────────────────

class _OvReplyTarget:
    """يجعل رسالة نصية تتصرف مثل callback query في _ov_edit (ترسل رسالة جديدة)."""

    def __init__(self, message):
        self.message = message

    async def edit_message_text(self, *args, **kwargs):
        return await self.message.reply_text(*args, **kwargs)


async def _ov_edit(q, chunks, kb):
    first, rest = chunks[0], chunks[1:]
    markup_first = kb if not rest else None
    try:
        await q.edit_message_text(
            first, parse_mode=ParseMode.HTML, reply_markup=markup_first,
            disable_web_page_preview=True)
    except Exception as exc:
        if "not modified" not in str(exc).lower():
            await q.message.reply_text(
                first, parse_mode=ParseMode.HTML, reply_markup=markup_first,
                disable_web_page_preview=True)
    for index, chunk in enumerate(rest):
        await q.message.reply_text(
            chunk, parse_mode=ParseMode.HTML,
            reply_markup=kb if index == len(rest) - 1 else None,
            disable_web_page_preview=True)


def _ov_btn(text, data):
    return InlineKeyboardButton(text, callback_data=data)


async def ov_show_my_orders(update, context, q, offset=0):
    user_id = update.effective_user.id
    rows, total, active = await asyncio.to_thread(ov_fetch_page, offset, OV_USER_PAGE_SIZE, user_id)
    if not rows and offset > 0:
        offset = 0
        rows, total, active = await asyncio.to_thread(ov_fetch_page, 0, OV_USER_PAGE_SIZE, user_id)
    if not rows:
        await _ov_edit(q, ["📦 <b>طلباتي</b>\n\nلا توجد طلبات لديك بعد."],
                       InlineKeyboardMarkup([[_ov_btn("🔙 رجوع", "main_menu")]]))
        return
    lives = await ov_fetch_live(rows)
    text = ov_render_user_page(rows, lives, offset, total, active)
    keyboard = []
    for order in rows:
        code = str(order.get("order_code") or order["id"])
        keyboard.append([_ov_btn(f"🔄 تتبّع {code}", f"ov:tr:{order['id']}:{offset}"),
                         _ov_btn(f"🔁 إعادة {code}", f"ov:re:{order['id']}:{offset}")])
    nav = ov_nav_row("ov:me", offset, OV_USER_PAGE_SIZE, total)
    if nav:
        keyboard.append(nav)
    keyboard.append([_ov_btn("🔄 تحديث", f"ov:me:{offset}")])
    keyboard.append([_ov_btn("🔙 رجوع", "main_menu")])
    await _ov_edit(q, ov_split_message(text), InlineKeyboardMarkup(keyboard))


async def ov_show_track(update, context, q, order_id, offset, is_owner):
    order = await asyncio.to_thread(ov_fetch_one, order_id)
    if not order or (order.get("user_id") != update.effective_user.id and not is_owner):
        await q.answer("⚠️ لم أجد هذا الطلب.", show_alert=True)
        return
    lives = await ov_fetch_live([order], force=True)
    lines = ["🔄 <b>تتبّع الطلب</b>", ""] + ov_user_block(order, lives.get(order["id"]))
    keyboard = [[_ov_btn("🔄 تحديث", f"ov:tr:{order_id}:{offset}")]]
    if order.get("user_id") == update.effective_user.id:
        keyboard[0].append(_ov_btn("🔁 إعادة", f"ov:re:{order_id}:{offset}"))
    keyboard.append([_ov_btn("🔙 لطلباتي", f"ov:me:{offset}")])
    await _ov_edit(q, ["\n".join(lines)], InlineKeyboardMarkup(keyboard))


async def _ov_reorder_load(update, q, order_id):
    """يحمّل الطلب القديم ويتحقق منه (طلبات العضو نفسه فقط). يعيد (order, service) أو None."""
    order = await asyncio.to_thread(ov_fetch_one, order_id)
    if order and order.get("user_id") != update.effective_user.id:
        order = None
    service = await asyncio.to_thread(ov_fetch_service, order["service_id"]) if order else None
    problem = ov_reorder_problem(order, service)
    if problem:
        await q.answer(problem, show_alert=True)
        return None
    return order, service


async def ov_show_reorder(update, context, q, order_id, offset):
    loaded = await _ov_reorder_load(update, q, order_id)
    if not loaded:
        return
    order, service = loaded
    qty = int(order["quantity"])
    cost = smm_service_cost_points(qty, service.get("price_per_point", 1))
    if cost <= 0:
        await q.answer("⚠️ سعر هذه الخدمة غير صالح حالياً.", show_alert=True)
        return
    text = (
        "🔁 <b>إعادة الطلب</b>\n\n"
        f"🔹 الخدمة: {ov_short(service.get('name_ar'), 60)}\n"
        f"🔢 الكمية: {qty:,}\n"
        f"🔗 الرابط: <code>{ov_short(order.get('link'), 80)}</code>\n"
        f"💎 السعر التقريبي: {smm_jewels_cost(cost):,} مجوهرة\n\n"
        "اختر: نفس الرابط، أو أرسل رابطاً جديداً بنفس الخدمة والكمية."
    )
    kb = InlineKeyboardMarkup([
        [_ov_btn("✅ نفس الرابط", f"ov:ru:{order_id}:{offset}")],
        [_ov_btn("✏️ رابط جديد", f"ov:rn:{order_id}:{offset}")],
        [_ov_btn("🔙 رجوع", f"ov:me:{offset}")],
    ])
    await _ov_edit(q, [text], kb)


def _ov_seed_reorder_state(context, service, qty, cost):
    context.user_data["smm_svc_db_id"] = service["id"]
    context.user_data["smm_svc"] = service
    context.user_data["smm_cat"] = service.get("category")
    context.user_data["smm_qty"] = qty
    context.user_data["smm_cost"] = cost


async def ov_reorder_new_link(update, context, q, order_id, offset):
    loaded = await _ov_reorder_load(update, q, order_id)
    if not loaded:
        return
    order, service = loaded
    qty = int(order["quantity"])
    cost = smm_service_cost_points(qty, service.get("price_per_point", 1))
    if cost <= 0:
        await q.answer("⚠️ سعر هذه الخدمة غير صالح حالياً.", show_alert=True)
        return
    _ov_seed_reorder_state(context, service, qty, cost)
    context.user_data["state"] = "await_smm_link"
    await _ov_edit(q, [
        f"✅ الكمية: {qty:,}\n💎 السعر التقريبي: {smm_jewels_cost(cost):,} مجوهرة\n\n"
        "📎 أرسل <b>الرابط الجديد</b>:"
    ], InlineKeyboardMarkup([[_ov_btn("🔙 رجوع", f"ov:re:{order_id}:{offset}")]]))


async def ov_reorder_same_link(update, context, q, order_id, offset):
    """يجهّز معاينة الدفع نفسها التي يعرضها البوت عادةً؛ الدفع يتم بأزرارها المعتادة."""
    loaded = await _ov_reorder_load(update, q, order_id)
    if not loaded:
        return
    order, service = loaded
    qty, link = int(order["quantity"]), str(order["link"]).strip()
    cost = smm_service_cost_points(qty, service.get("price_per_point", 1))
    if cost <= 0:
        await q.answer("⚠️ سعر هذه الخدمة غير صالح حالياً.", show_alert=True)
        return
    try:
        intent = await asyncio.to_thread(
            create_smm_payment_intent, update.effective_user.id, service, link, qty, cost)
        db_user = await asyncio.to_thread(get_user, update.effective_user.id)
    except Exception:
        logger.exception("orders_view: تعذر تجهيز إعادة الطلب")
        await q.answer("⚠️ تعذر تجهيز الطلب حالياً. حاول بعد قليل.", show_alert=True)
        return
    _ov_seed_reorder_state(context, service, qty, cost)
    context.user_data["smm_link"] = link
    context.user_data["smm_intent_id"] = int(intent["id"])
    context.user_data["state"] = "confirm_smm"
    jewels = (db_user or {}).get("jewels") or 0
    text = (
        "📋 <b>تفاصيل الطلب:</b>\n\n"
        f"🔹 الخدمة: {_smm_preview_value(service.get('name_ar') or 'الخدمة', 300)}\n"
        f"🔢 الكمية: {qty}\n"
        f"🔗 الرابط: <code>{_smm_preview_value(link, 1500)}</code>\n"
        f"💎 السعر: {int(intent['cost_jewels']):,} مجوهرة\n"
        f"💎 رصيد مجوهراتك: {fmt_jewel_amount(jewels)}"
    )
    kb = InlineKeyboardMarkup([
        [_ov_btn(f"💎 الدفع بالمجوهرات — {intent['cost_jewels']:,}", f"smm:pay:jewels:{int(intent['id'])}")],
        [_ov_btn("❌ إلغاء", f"smm:cancel:{int(intent['id'])}")],
        [_ov_btn("🔙 رجوع", f"ov:re:{order_id}:{offset}")],
    ])
    await _ov_edit(q, [text], kb)


# ── المالك ──

def _ov_report_toggle_label():
    on = get_setting(OV_REPORT_ENABLED_SETTING) != "0"
    return "🔔 التقرير اليومي: مفعّل ✅" if on else "🔕 التقرير اليومي: متوقف 🚫"


async def ov_show_owner_orders(update, context, q, offset=0, flt=("a", "a", 0)):
    status, period, buyer = flt
    rows, total, active = await asyncio.to_thread(
        ov_fetch_page, offset, OV_OWNER_PAGE_SIZE, None, status, period, buyer)
    if not rows and offset > 0:
        offset = 0
        rows, total, active = await asyncio.to_thread(
            ov_fetch_page, 0, OV_OWNER_PAGE_SIZE, None, status, period, buyer)
    suffix = ov_filter_suffix(status, period, buyer)
    flt_btn = _ov_btn("🎛 فلاتر" + ("" if ov_filter_is_default(*flt) else " ●"), f"ov:flt:{suffix}")
    back = [_ov_btn("⚙️ الإعدادات", "owner_settings")]
    if not rows:
        kb = InlineKeyboardMarkup([[flt_btn], back])
        note = ov_filter_describe(*flt)
        await _ov_edit(q, [f"📊 <b>الطلبات</b>\n{_html.escape(note)}\n\nلا توجد طلبات مطابقة."], kb)
        return
    lives = await ov_fetch_live(rows)
    text = ov_render_owner_page(rows, lives, offset, total, active, ov_filter_describe(*flt))
    keyboard = []
    nav = ov_nav_row("ov:own", offset, OV_OWNER_PAGE_SIZE, total, suffix)
    if nav:
        keyboard.append(nav)
    keyboard.append([flt_btn, _ov_btn("📤 تصدير CSV", f"ov:csv:{suffix}")])
    keyboard.append([_ov_btn("📈 تقرير 24 ساعة", "ov:rep"), _ov_btn("🔄 تحديث", f"ov:own:{offset}:{suffix}")])
    keyboard.append([_ov_btn(_ov_report_toggle_label(), "ov:rept")])
    keyboard.append([_ov_btn("🔎 فحص طلب بالكود", "os:oi:ask")])
    keyboard.append(back)
    await _ov_edit(q, ov_split_message(text), InlineKeyboardMarkup(keyboard))


async def ov_show_filter_screen(q, flt):
    status, period, buyer = flt
    mark = lambda cur, val: "● " if cur == val else ""
    rows = [[_ov_btn(f"{mark(status, k)}{label}", f"ov:flt:{ov_filter_suffix(k, period, buyer)}")
             for k, label in OV_STATUS_FILTERS[:3]],
            [_ov_btn(f"{mark(status, k)}{label}", f"ov:flt:{ov_filter_suffix(k, period, buyer)}")
             for k, label in OV_STATUS_FILTERS[3:]],
            [_ov_btn(f"{mark(period, k)}{label}", f"ov:flt:{ov_filter_suffix(status, k, buyer)}")
             for k, label in OV_PERIOD_FILTERS],
            [_ov_btn("👤 مشتري محدد" + (f" ({buyer})" if buyer else ""), f"ov:fb:{status}:{period}")]]
    if buyer:
        rows.append([_ov_btn("🧹 إزالة المشتري", f"ov:flt:{ov_filter_suffix(status, period, 0)}")])
    rows.append([_ov_btn("✅ عرض النتائج", f"ov:own:0:{ov_filter_suffix(status, period, buyer)}")])
    rows.append([_ov_btn("♻️ مسح الكل", "ov:flt:a:a:0"), _ov_btn("🔙 رجوع", "ov:own:0")])
    await _ov_edit(q, ["🎛 <b>فلاتر الطلبات</b>\nاختر الحالة والفترة، ثم «عرض النتائج»."],
                   InlineKeyboardMarkup(rows))


async def ov_send_csv(update, context, q, flt):
    status, period, buyer = flt
    rows, total, _active = await asyncio.to_thread(
        ov_fetch_page, 0, OV_CSV_MAX_ROWS, None, status, period, buyer)
    if not rows:
        await q.answer("لا توجد طلبات مطابقة للتصدير.", show_alert=True)
        return
    data = await asyncio.to_thread(ov_build_csv, rows)
    bio = io.BytesIO(data)
    bio.name = "orders.csv"
    note = f" (أحدث {OV_CSV_MAX_ROWS:,} من {total:,})" if total > len(rows) else ""
    await q.message.reply_document(
        document=bio, filename="orders.csv",
        caption=f"📤 {len(rows):,} طلب{note}\n{ov_filter_describe(*flt)}".strip())


async def ov_send_report(context, chat_id):
    stats, top, stuck = await asyncio.to_thread(ov_collect_report)
    await context.bot.send_message(
        chat_id, ov_render_report(stats, top, stuck), parse_mode=ParseMode.HTML)


async def ov_daily_report_job(context):
    """مهمة يومية: ترسل للمالك ملخص آخر 24 ساعة ما لم يعطّلها."""
    try:
        if get_setting(OV_REPORT_ENABLED_SETTING) == "0" or not OWNER_ID:
            return
        await ov_send_report(context, OWNER_ID)
    except Exception:
        logger.exception("orders_view: فشل التقرير اليومي")


def ov_schedule_daily_report(job_queue):
    try:
        from zoneinfo import ZoneInfo
        try:
            hour = int(get_setting(OV_REPORT_HOUR_SETTING) or OV_REPORT_DEFAULT_HOUR)
        except (TypeError, ValueError):
            hour = OV_REPORT_DEFAULT_HOUR
        hour = hour if 0 <= hour <= 23 else OV_REPORT_DEFAULT_HOUR
        job_queue.run_daily(
            ov_daily_report_job,
            time=_dtime(hour, 0, tzinfo=ZoneInfo(OV_REPORT_TZ)),
            name="orders_daily_report",
        )
        logger.info("📈 تم تفعيل التقرير اليومي للطلبات الساعة %02d:00 (%s)", hour, OV_REPORT_TZ)
    except Exception:
        logger.exception("orders_view: تعذر جدولة التقرير اليومي")


# ───────────────────────────── المعالجات ─────────────────────────────

def _ov_int(parts, index, default=0):
    try:
        return max(0, int(parts[index]))
    except (IndexError, ValueError):
        return default


async def handle_orders_view_callback(update, context, q, data: str, user, is_owner: bool) -> bool:
    if not data.startswith("ov:"):
        return False
    parts = data.split(":")
    scope = parts[1] if len(parts) > 1 else ""
    try:
        await q.answer()
    except Exception:
        pass

    if scope == "me":
        context.user_data["state"] = "main_menu"
        await ov_show_my_orders(update, context, q, _ov_int(parts, 2))
        return True
    if scope == "tr":
        await ov_show_track(update, context, q, _ov_int(parts, 2), _ov_int(parts, 3), is_owner)
        return True
    if scope == "re":
        await ov_show_reorder(update, context, q, _ov_int(parts, 2), _ov_int(parts, 3))
        return True
    if scope == "ru":
        await ov_reorder_same_link(update, context, q, _ov_int(parts, 2), _ov_int(parts, 3))
        return True
    if scope == "rn":
        await ov_reorder_new_link(update, context, q, _ov_int(parts, 2), _ov_int(parts, 3))
        return True

    # ── ما يلي للمالك فقط ──
    if scope in {"own", "flt", "fb", "csv", "rep", "rept"}:
        if not is_owner:
            await q.answer("🚫 هذا القسم للمالك فقط.", show_alert=True)
            return True
        if scope == "own":
            context.user_data["state"] = "main_menu"
            await ov_show_owner_orders(update, context, q, _ov_int(parts, 2), ov_parse_filter(parts[3:6]))
        elif scope == "flt":
            await ov_show_filter_screen(q, ov_parse_filter(parts[2:5]))
        elif scope == "fb":
            status, period, _b = ov_parse_filter(parts[2:4])
            context.user_data["state"] = OV_BUYER_STATE
            context.user_data["ov_filter"] = (status, period)
            await _ov_edit(q, ["👤 أرسل <b>ID</b> المشتري أو يوزره (مع أو بدون @):"],
                           InlineKeyboardMarkup([[_ov_btn("🔙 إلغاء", f"ov:flt:{status}:{period}:0")]]))
        elif scope == "csv":
            await ov_send_csv(update, context, q, ov_parse_filter(parts[2:5]))
        elif scope == "rep":
            await ov_send_report(context, update.effective_chat.id)
        elif scope == "rept":
            now_on = get_setting(OV_REPORT_ENABLED_SETTING) != "0"
            set_setting(OV_REPORT_ENABLED_SETTING, "0" if now_on else "1")
            await ov_show_owner_orders(update, context, q, 0)
        return True
    return True


async def handle_orders_view_text(update, context, text: str) -> bool:
    """يستقبل ID/يوزر المشتري لفلتر جدول المالك."""
    user = update.effective_user
    if context.user_data.get("state") != OV_BUYER_STATE or user is None or user.id != OWNER_ID:
        return False
    status, period = context.user_data.get("ov_filter", ("a", "a"))
    found = await asyncio.to_thread(lookup_user_by_id_or_username, text)
    if not found:
        await update.message.reply_text(
            "⚠️ لم أجد هذا المستخدم. أرسل ID أو يوزراً صحيحاً:",
            reply_markup=InlineKeyboardMarkup([[_ov_btn("🔙 إلغاء", f"ov:flt:{status}:{period}:0")]]))
        return True
    context.user_data["state"] = "main_menu"
    await ov_show_owner_orders(update, context, _OvReplyTarget(update.message), 0,
                            (status, period, int(found["user_id"])))
    return True
