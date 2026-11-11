"""Part of the SMMMAIN Telegram bot.

* «📋 عرض طلباتي» للعضو: طلبات الرشق من المواقع بحالتها والواصل والمتبقي،
  دون ذكر اسم الموقع أو تكلفته.
* «📊 زر التفاصيل» للمالك: الطلبات، رسائل الشكر (مع الرد)، التنبيهات،
  فوز الأعضاء، والتقرير اليومي.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

import asyncio
import html as _html
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

OD_TZ = timezone(timedelta(hours=3))          # نفس توقيت الجوائز الأسبوعية
OD_STAR_USD_DEFAULT = Decimal("0.01275")      # قيمة النجمة بالدولار
OD_JEWEL_GIFT_USD_DEFAULT = Decimal("0.015")  # قيمة الجوهرة التي يهديها المالك
OD_MEMBER_PAGE = 5
OD_OWNER_PAGE = 6
OD_LIST_PAGE = 8
OD_REPORT_TIME_DEFAULT = "23:55"

_od_tables_ready = False


def _e(value) -> str:
    return _html.escape(str(value if value is not None else ""), quote=False)


# ───────────────────────── قاعدة البيانات ─────────────────────────

def od_ensure_tables() -> None:
    """ينشئ جداول الميزات الجديدة مرة واحدة (آمن عند التكرار)."""
    global _od_tables_ready
    if _od_tables_ready:
        return
    with db_conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS thank_messages (
            id            BIGSERIAL PRIMARY KEY,
            user_id       BIGINT NOT NULL,
            username      TEXT,
            full_name     TEXT,
            kind          TEXT NOT NULL DEFAULT 'text',
            language      TEXT,
            body          TEXT,
            photo_file_id TEXT,
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            replied_at    TIMESTAMPTZ,
            reply_text    TEXT
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS star_income_log (
            telegram_payment_id TEXT PRIMARY KEY,
            user_id    BIGINT,
            stars      INTEGER NOT NULL,
            kind       TEXT,
            refunded   BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS od_alert_seen (
            alert_key  TEXT PRIMARY KEY,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""")
    _od_tables_ready = True


# ───────────────────────── أدوات عرض ─────────────────────────

def od_fmt_dt(value) -> str:
    if not value:
        return "—"
    try:
        d = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(OD_TZ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)[:16]


def od_who(username, full_name, user_id=None) -> str:
    username = str(username or "").strip().lstrip("@")
    if username:
        label = f"@{username}"
    else:
        label = str(full_name or "").strip() or "بدون يوزر"
    if user_id:
        return f"{_e(label)} (<code>{int(user_id)}</code>)"
    return _e(label)


def od_pay_text(o) -> str:
    method = o.get("payment_method") or "points"
    if method == "stars":
        return f"{int(o.get('cost_stars') or 0):,} ⭐"
    if method == "jewels":
        return f"{int(o.get('cost_jewels') or 0):,} 💎"
    if method == "free":
        return "مجاناً"
    return f"{int(o.get('cost_points') or 0):,} نقطة"


OD_STATUS_LABELS = {
    "pending": "⏳ قيد الانتظار",
    "processing": "🔄 قيد التنفيذ",
    "in progress": "🔄 قيد التنفيذ",
    "inprogress": "🔄 قيد التنفيذ",
    "completed": "✅ مكتمل",
    "partial": "⚠️ مكتمل جزئياً",
    "cancelled": "❌ ملغي",
    "canceled": "❌ ملغي",
    "refund_processing": "🔄 استرداد قيد المعالجة",
    "refund_required": "⚠️ الاسترداد يحتاج مراجعة",
    "failed": "❌ فشل",
    "error": "❌ خطأ",
}


def od_order_progress(order: dict, api_status=None):
    """يعيد (مفتاح الحالة، الواصل، المتبقي). القيمتان None إن لم تُعرفا."""
    qty = int(order.get("quantity") or 0)
    local = str(order.get("status") or "").strip().lower()
    api = api_status if isinstance(api_status, dict) else {}
    remote = str(api.get("status") or "").strip().lower()
    key = remote or local
    remains = None
    try:
        if api.get("remains") is not None:
            remains = max(0, min(qty, int(float(api.get("remains")))))
    except (TypeError, ValueError):
        remains = None
    partial_refund = int(order.get("partial_refund_pts") or 0)
    if remains is None and key == "completed" and partial_refund == 0:
        remains = 0
    if not remote and local == "completed" and partial_refund > 0:
        key = "partial"
    delivered = (qty - remains) if remains is not None else None
    return key, delivered, remains


def od_status_label(key: str) -> str:
    return OD_STATUS_LABELS.get(key, key or "غير معروف")


async def od_fetch_live(orders):
    """يجلب الحالة الحية للطلبات الجارية فقط، بالتوازي ودون كسر العرض عند الفشل."""
    async def one(o):
        if str(o.get("status") or "").strip().lower() not in ("pending", "processing"):
            return {}
        api_id = str(o.get("api_order_id") or "").strip()
        if not api_id or not o.get("svc_api_id"):
            return {}
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(smm_order_status, api_id, panel=o.get("svc_panel") or 1),
                timeout=10,
            )
            return result if isinstance(result, dict) else {}
        except Exception:
            return {}
    return await asyncio.gather(*(one(o) for o in orders))


def od_nav_row(prefix: str, offset: int, total: int, size: int):
    """«التالي» يعرض الأقدم، «السابق» يرجع للأحدث."""
    row = []
    if offset > 0:
        row.append(InlineKeyboardButton("▶️ السابق", callback_data=f"{prefix}:{max(0, offset - size)}"))
    if offset + size < total:
        row.append(InlineKeyboardButton("التالي ◀️", callback_data=f"{prefix}:{offset + size}"))
    return row


async def od_show(q, text: str, kb) -> None:
    """يعدّل الرسالة الحالية، وإن تعذر (مثلاً رسالة صورة) يرسل رسالة جديدة."""
    text = text[:4000]
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb,
                                  disable_web_page_preview=True)
    except Exception as exc:
        if "not modified" in str(exc).lower():
            return
        try:
            await q.message.chat.send_message(text, parse_mode=ParseMode.HTML, reply_markup=kb,
                                              disable_web_page_preview=True)
        except Exception:
            logger.exception("تعذر عرض شاشة التفاصيل")


# ───────────────────────── 1) عرض طلباتي (للعضو) ─────────────────────────

def od_member_orders_page(user_id: int, offset: int):
    with db_conn() as c:
        total = int((c.execute(
            "SELECT COUNT(*) AS cnt FROM orders WHERE user_id=%s", (user_id,)
        ).fetchone() or {}).get("cnt") or 0)
        rows = c.execute(
            """SELECT o.id, o.order_code, o.quantity, o.status, o.api_order_id, o.link,
                      o.created_at, o.partial_refund_pts, o.payment_method,
                      o.cost_points, o.cost_stars, o.cost_jewels,
                      s.name_ar AS s_name, s.panel AS svc_panel,
                      s.api_service_id AS svc_api_id
               FROM orders o LEFT JOIN services s ON s.id = o.service_id
               WHERE o.user_id=%s ORDER BY o.id DESC LIMIT %s OFFSET %s""",
            (user_id, OD_MEMBER_PAGE, offset),
        ).fetchall()
    return total, [dict(r) for r in rows]


def od_member_order_block(index: int, o: dict, api) -> str:
    key, delivered, remains = od_order_progress(o, api)
    qty = int(o.get("quantity") or 0)
    got = f"{delivered:,}" if delivered is not None else "—"
    left = f"{remains:,}" if remains is not None else "—"
    link = str(o.get("link") or "—")
    if len(link) > 45:
        link = link[:42] + "…"
    return (
        f"<b>{index}. {_e(o.get('s_name') or 'خدمة')}</b>\n"
        f"🧾 الكود: <code>{_e(o.get('order_code') or '—')}</code>\n"
        f"🔗 {_e(link)}\n"
        f"🔢 المطلوب: {qty:,} | ✅ الواصل: {got} | ⏳ المتبقي: {left}\n"
        f"💳 المدفوع: {od_pay_text(o)}\n"
        f"📊 الحالة: <b>{od_status_label(key)}</b>\n"
        f"🕒 {od_fmt_dt(o.get('created_at'))}"
    )


async def od_show_member_orders(q, user_id: int, offset: int = 0) -> None:
    od_ensure_tables()
    offset = max(0, int(offset))
    total, rows = od_member_orders_page(user_id, offset)
    back = [InlineKeyboardButton("🔙 رجوع", callback_data="mmg:wallet")]
    if not rows:
        text = "📋 <b>طلباتي</b>\n\n" + (
            "لا توجد طلبات بعد." if offset == 0 else "لا مزيد من الطلبات."
        )
        kb_rows = []
        if offset > 0:
            kb_rows.append([InlineKeyboardButton("▶️ السابق", callback_data=f"smo:{max(0, offset - OD_MEMBER_PAGE)}")])
        kb_rows.append(back)
        await od_show(q, text, InlineKeyboardMarkup(kb_rows))
        return
    live = await od_fetch_live(rows)
    blocks = [od_member_order_block(offset + i + 1, o, api)
              for i, (o, api) in enumerate(zip(rows, live))]
    text = (
        f"📋 <b>طلباتي</b> ({offset + 1}-{offset + len(rows)} من {total})\n\n"
        + "\n➖➖➖➖➖\n".join(blocks)
    )
    kb_rows = []
    nav = od_nav_row("smo", offset, total, OD_MEMBER_PAGE)
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton("🔄 تحديث", callback_data=f"smo:{offset}")])
    kb_rows.append(back)
    await od_show(q, text, InlineKeyboardMarkup(kb_rows))


async def handle_smo_callback(update, context, q, data, user, is_own) -> bool:
    if not data.startswith("smo:"):
        return False
    try:
        offset = int(data.split(":", 1)[1])
    except ValueError:
        offset = 0
    context.user_data["state"] = "main_menu"
    await od_show_member_orders(q, user.id, offset)
    return True


# ───────────────────────── 2) جدول الطلبات (للمالك) ─────────────────────────

def od_owner_orders_page(offset: int):
    with db_conn() as c:
        total = int((c.execute("SELECT COUNT(*) AS cnt FROM orders").fetchone() or {}).get("cnt") or 0)
        rows = c.execute(
            """SELECT o.id, o.user_id, o.order_code, o.quantity, o.status, o.api_order_id,
                      o.created_at, o.partial_refund_pts, o.payment_method,
                      o.cost_points, o.cost_stars, o.cost_jewels,
                      u.username AS u_username, u.full_name AS u_full_name,
                      s.name_ar AS s_name, s.panel AS svc_panel,
                      s.api_service_id AS svc_api_id
               FROM orders o
               LEFT JOIN users u ON u.user_id = o.user_id
               LEFT JOIN services s ON s.id = o.service_id
               ORDER BY o.id DESC LIMIT %s OFFSET %s""",
            (OD_OWNER_PAGE, offset),
        ).fetchall()
    return total, [dict(r) for r in rows]


def od_owner_order_block(o: dict, api) -> str:
    key, delivered, remains = od_order_progress(o, api)
    qty = int(o.get("quantity") or 0)
    got = f"{delivered:,}" if delivered is not None else "—"
    left = f"{remains:,}" if remains is not None else "—"
    return (
        f"🧾 <b>الكود:</b> <code>{_e(o.get('order_code') or '—')}</code>\n"
        f"📦 <b>الطلب:</b> {_e(o.get('s_name') or 'خدمة')} × {qty:,}\n"
        f"👤 <b>المشتري:</b> {od_who(o.get('u_username'), o.get('u_full_name'), o.get('user_id'))}\n"
        f"💳 <b>المدفوع:</b> {od_pay_text(o)}\n"
        f"📶 <b>حالته:</b> {od_status_label(key)}\n"
        f"🔢 <b>الباقي/الواصل:</b> {left} / {got}"
    )


async def od_show_owner_orders(q, offset: int = 0) -> None:
    offset = max(0, int(offset))
    total, rows = od_owner_orders_page(offset)
    back = [InlineKeyboardButton("🔙 زر التفاصيل", callback_data="od:menu")]
    if not rows:
        kb_rows = []
        if offset > 0:
            kb_rows.append([InlineKeyboardButton("▶️ السابق", callback_data=f"od:orders:{max(0, offset - OD_OWNER_PAGE)}")])
        kb_rows.append(back)
        await od_show(q, "📦 <b>الطلبات</b>\n\n" + ("لا توجد طلبات بعد." if offset == 0 else "لا مزيد من الطلبات."),
                      InlineKeyboardMarkup(kb_rows))
        return
    live = await od_fetch_live(rows)
    blocks = [od_owner_order_block(o, api) for o, api in zip(rows, live)]
    text = (
        f"📦 <b>الطلبات</b> ({offset + 1}-{offset + len(rows)} من {total})\n"
        "الطلب • المشتري • المدفوع • حالته • الباقي/الواصل\n\n"
        + "\n➖➖➖➖➖\n".join(blocks)
    )
    kb_rows = []
    nav = od_nav_row("od:orders", offset, total, OD_OWNER_PAGE)
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton("🔍 بحث بكود الطلب", callback_data="os:order_lookup")])
    kb_rows.append(back)
    await od_show(q, text, InlineKeyboardMarkup(kb_rows))


# ───────────────────────── 3) رسائل الشكر مع الرد ─────────────────────────

def record_thank_message(user, kind: str, language: str = "", body: str = "", photo_file_id: str = "") -> int:
    """يحفظ رسالة الشكر ويعيد رقمها (0 عند الفشل حتى لا تتعطل رسالة العضو)."""
    try:
        od_ensure_tables()
        with db_conn() as c:
            row = c.execute(
                "INSERT INTO thank_messages (user_id,username,full_name,kind,language,body,photo_file_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (user.id, user.username or "", user.full_name or "", kind, language or "",
                 body or "", photo_file_id or ""),
            ).fetchone()
        return int((row or {}).get("id") or 0)
    except Exception:
        logger.exception("تعذر حفظ رسالة الشكر")
        return 0


def od_thank_reply_kb(thank_id: int):
    if not thank_id:
        return None
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("↩️ رد على العضو", callback_data=f"od:thxr:{thank_id}")
    ]])


def od_thanks_page(offset: int):
    with db_conn() as c:
        total = int((c.execute("SELECT COUNT(*) AS cnt FROM thank_messages").fetchone() or {}).get("cnt") or 0)
        rows = c.execute(
            "SELECT id,user_id,username,full_name,kind,replied_at FROM thank_messages "
            "ORDER BY id DESC LIMIT %s OFFSET %s",
            (OD_LIST_PAGE, offset),
        ).fetchall()
    return total, [dict(r) for r in rows]


async def od_show_thanks(q, offset: int = 0) -> None:
    od_ensure_tables()
    offset = max(0, int(offset))
    total, rows = od_thanks_page(offset)
    kb_rows = []
    for r in rows:
        mark = "✅" if r.get("replied_at") else "🕓"
        kind = "🖼" if r.get("kind") == "photo" else "💌"
        name = str(r.get("username") or "").strip() and f"@{r['username']}" or (r.get("full_name") or "—")
        kb_rows.append([InlineKeyboardButton(
            f"{mark} {kind} #{r['id']} • {name}"[:60],
            callback_data=f"od:thxv:{r['id']}:{offset}",
        )])
    nav = od_nav_row("od:thx", offset, total, OD_LIST_PAGE)
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton("🔙 زر التفاصيل", callback_data="od:menu")])
    text = f"💌 <b>عمليات رسائل الشكر</b> ({total})\n🕓 بانتظار الرد  |  ✅ تم الرد" if rows else \
        "💌 <b>عمليات رسائل الشكر</b>\n\nلا توجد رسائل شكر بعد."
    await od_show(q, text, InlineKeyboardMarkup(kb_rows))


async def od_view_thank(q, context, thank_id: int, offset: int = 0) -> None:
    od_ensure_tables()
    with db_conn() as c:
        r = c.execute("SELECT * FROM thank_messages WHERE id=%s", (thank_id,)).fetchone()
    if not r:
        await od_show(q, "⚠️ الرسالة غير موجودة.",
                      InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"od:thx:{offset}")]]))
        return
    r = dict(r)
    status = f"✅ تم الرد ({od_fmt_dt(r.get('replied_at'))})" if r.get("replied_at") else "🕓 بانتظار الرد"
    body = r.get("body") or ("🖼 صورة (تُرسل أدناه)" if r.get("kind") == "photo" else "—")
    text = (
        f"💌 <b>رسالة شكر #{r['id']}</b>\n"
        f"👤 {od_who(r.get('username'), r.get('full_name'), r.get('user_id'))}\n"
        f"🌐 {_e(r.get('language') or '—')} | 🕒 {od_fmt_dt(r.get('created_at'))}\n"
        f"📌 {status}\n\n{_e(body)}"
    )
    if r.get("reply_text"):
        text += f"\n\n↩️ <b>ردك:</b>\n{_e(r['reply_text'])}"
    if r.get("kind") == "photo" and r.get("photo_file_id"):
        try:
            await q.message.chat.send_photo(r["photo_file_id"], caption=f"🖼 صورة الشكر #{r['id']}")
        except Exception:
            logger.exception("تعذر إرسال صورة الشكر للمالك")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ رد على العضو" if not r.get("replied_at") else "↩️ رد جديد",
                              callback_data=f"od:thxr:{r['id']}")],
        [InlineKeyboardButton("🔙 رجوع للرسائل", callback_data=f"od:thx:{offset}")],
    ])
    await od_show(q, text, kb)


# ───────────────────────── 4) التنبيهات ─────────────────────────

def od_find_nouser_blocks(rows, block_size: int = 5, min_missing: int = 3):
    """rows: مدعوّون مرتبون بالداعي ثم بترتيب الدخول.
    كل 5 مدعوين متتالين لنفس الداعي، إن كان 3 منهم أو أكثر بلا يوزر فهو تنبيه."""
    by_inviter = {}
    for r in rows:
        by_inviter.setdefault(int(r["invited_by"]), []).append(r)
    alerts = []
    for inviter, members in by_inviter.items():
        for start in range(0, len(members) - block_size + 1, block_size):
            chunk = members[start:start + block_size]
            missing = sum(1 for m in chunk if not str(m.get("username") or "").strip())
            if missing >= min_missing:
                alerts.append({
                    "inviter": inviter,
                    "block_no": start // block_size + 1,
                    "members": chunk,
                    "missing": missing,
                })
    return alerts


def od_load_nouser_alerts():
    with db_conn() as c:
        rows = c.execute(
            """SELECT u.invited_by, u.user_id, u.username, u.full_name
               FROM users u
               WHERE COALESCE(u.invited_by,0) > 0
                 AND u.invited_by IN (
                     SELECT invited_by FROM users
                     WHERE COALESCE(invited_by,0) > 0
                     GROUP BY invited_by HAVING COUNT(*) >= 5)
               ORDER BY u.invited_by, u.bot_user_num NULLS LAST, u.user_id"""
        ).fetchall()
        alerts = od_find_nouser_blocks([dict(r) for r in rows])
        names = {}
        ids = sorted({a["inviter"] for a in alerts})
        if ids:
            placeholders = ",".join(["%s"] * len(ids))
            for r in c.execute(
                f"SELECT user_id, username, full_name FROM users WHERE user_id IN ({placeholders})",
                tuple(ids),
            ).fetchall():
                names[int(r["user_id"])] = dict(r)
    for a in alerts:
        a["inviter_info"] = names.get(a["inviter"], {})
    return alerts


def od_nouser_alert_text(a: dict) -> str:
    inv = a.get("inviter_info") or {}
    lines = [
        f"👥 <b>دعوات مشبوهة</b>: {od_who(inv.get('username'), inv.get('full_name'), a['inviter'])}",
        f"المجموعة رقم {a['block_no']}: <b>{a['missing']} من 5</b> بدون يوزر",
    ]
    for m in a["members"]:
        has = bool(str(m.get("username") or "").strip())
        lines.append(f"{'✅' if has else '🚫'} {od_who(m.get('username'), m.get('full_name'), m.get('user_id'))}")
    return "\n".join(lines)


def od_fraud_page(offset: int):
    with db_conn() as c:
        total = int((c.execute("SELECT COUNT(*) AS cnt FROM referral_fraud_log").fetchone() or {}).get("cnt") or 0)
        rows = c.execute(
            """SELECT f.id, f.inviter_id, f.invited_id, f.joined_count, f.total_channels, f.created_at,
                      ui.username AS i_user, ui.full_name AS i_name,
                      ud.username AS d_user, ud.full_name AS d_name
               FROM referral_fraud_log f
               LEFT JOIN users ui ON ui.user_id = f.inviter_id
               LEFT JOIN users ud ON ud.user_id = f.invited_id
               ORDER BY f.id DESC LIMIT %s OFFSET %s""",
            (OD_LIST_PAGE, offset),
        ).fetchall()
    return total, [dict(r) for r in rows]


def od_fraud_text(r: dict) -> str:
    return (
        f"🚨 <b>غش في الإحالة</b> #{r['id']}\n"
        f"الداعي: {od_who(r.get('i_user'), r.get('i_name'), r.get('inviter_id'))}\n"
        f"المدعو: {od_who(r.get('d_user'), r.get('d_name'), r.get('invited_id'))}\n"
        f"اشترك بـ {int(r.get('joined_count') or 0)} من {int(r.get('total_channels') or 0)} قناة\n"
        f"🕒 {od_fmt_dt(r.get('created_at'))}"
    )


async def od_show_alerts_menu(q) -> None:
    od_ensure_tables()
    try:
        fraud_total = od_fraud_page(0)[0]
    except Exception:
        fraud_total = 0
    try:
        nouser_total = len(od_load_nouser_alerts())
    except Exception:
        logger.exception("تعذر حساب تنبيهات الدعوات بلا يوزر")
        nouser_total = 0
    text = (
        "🚨 <b>التنبيهات</b>\n\n"
        f"🚨 أعضاء غاشّون (إحالة وهمية): <b>{fraud_total}</b>\n"
        f"👥 داعون جلبوا 3 من كل 5 بدون يوزر: <b>{nouser_total}</b>\n\n"
        "تصلك التنبيهات الجديدة تلقائياً هنا في المحادثة."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚨 الأعضاء الغاشّون", callback_data="od:alf:0")],
        [InlineKeyboardButton("👥 3 من 5 بدون يوزر", callback_data="od:aln:0")],
        [InlineKeyboardButton("🔙 زر التفاصيل", callback_data="od:menu")],
    ])
    await od_show(q, text, kb)


async def od_show_fraud_list(q, offset: int = 0) -> None:
    offset = max(0, int(offset))
    total, rows = od_fraud_page(offset)
    kb_rows = []
    nav = od_nav_row("od:alf", offset, total, OD_LIST_PAGE)
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton("🔙 التنبيهات", callback_data="od:alerts")])
    text = ("🚨 <b>الأعضاء الغاشّون</b>\n\n" + "\n➖➖➖\n".join(od_fraud_text(r) for r in rows)) \
        if rows else "🚨 <b>الأعضاء الغاشّون</b>\n\nلا توجد سجلات."
    await od_show(q, text, InlineKeyboardMarkup(kb_rows))


async def od_show_nouser_list(q, offset: int = 0) -> None:
    offset = max(0, int(offset))
    alerts = od_load_nouser_alerts()
    total = len(alerts)
    page = alerts[offset:offset + 3]
    kb_rows = []
    nav = od_nav_row("od:aln", offset, total, 3)
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton("🔙 التنبيهات", callback_data="od:alerts")])
    text = ("👥 <b>3 من 5 بدون يوزر</b>\n\n" + "\n➖➖➖\n".join(od_nouser_alert_text(a) for a in page)) \
        if page else "👥 <b>3 من 5 بدون يوزر</b>\n\nلا توجد حالات."
    await od_show(q, text, InlineKeyboardMarkup(kb_rows))


async def run_owner_alerts_job(context) -> None:
    """يفحص دورياً ويرسل للمالك التنبيهات الجديدة فقط (أول تشغيل يسجل القديم بصمت)."""
    try:
        od_ensure_tables()
        owner_id = int(OWNER_ID or 0)
        if not owner_id:
            return
        pending = []  # (key, text)
        with db_conn() as c:
            seen_count = int((c.execute("SELECT COUNT(*) AS cnt FROM od_alert_seen").fetchone() or {}).get("cnt") or 0)
            seen = {r["alert_key"] for r in c.execute("SELECT alert_key FROM od_alert_seen").fetchall()}
        for a in od_load_nouser_alerts():
            key = f"nouser:{a['inviter']}:{a['block_no']}"
            if key not in seen:
                pending.append((key, "🚨 <b>تنبيه جديد</b>\n" + od_nouser_alert_text(a)))
        try:
            with db_conn() as c:
                rows = [dict(r) for r in c.execute(
                    """SELECT f.id, f.inviter_id, f.invited_id, f.joined_count, f.total_channels, f.created_at,
                              ui.username AS i_user, ui.full_name AS i_name,
                              ud.username AS d_user, ud.full_name AS d_name
                       FROM referral_fraud_log f
                       LEFT JOIN users ui ON ui.user_id = f.inviter_id
                       LEFT JOIN users ud ON ud.user_id = f.invited_id
                       ORDER BY f.id DESC LIMIT 200"""
                ).fetchall()]
            for r in rows:
                key = f"fraud:{r['id']}"
                if key not in seen:
                    pending.append((key, od_fraud_text(r)))
        except Exception:
            logger.exception("تعذر فحص سجل الغش")
        if not pending:
            return
        silent = seen_count == 0  # أول تشغيل: لا نغرق المالك بالتاريخ القديم
        sent = 0
        for key, text in pending:
            if not silent and sent >= 10:
                break  # الباقي يُرسل في الدورة التالية
            if not silent:
                try:
                    await context.bot.send_message(owner_id, text[:4000], parse_mode=ParseMode.HTML)
                except Exception:
                    logger.exception("تعذر إرسال تنبيه للمالك")
                    continue
                sent += 1
            with db_conn() as c:
                c.execute("INSERT INTO od_alert_seen (alert_key) VALUES (%s) ON CONFLICT DO NOTHING", (key,))
    except Exception:
        logger.exception("فشل فحص تنبيهات المالك")


# ───────────────────────── 5) فوز الأعضاء ─────────────────────────

def _od_win_exchanges(offset: int):
    with db_conn() as c:
        total = int((c.execute("SELECT COUNT(*) AS cnt FROM prize_exchanges").fetchone() or {}).get("cnt") or 0)
        rows = c.execute(
            """SELECT pe.id, pe.user_id, pe.prize_type, pe.prize_value, pe.points_cost,
                      COALESCE(pe.cost_currency,'points') AS cur, pe.status, pe.order_code,
                      pe.created_at, u.username, u.full_name
               FROM prize_exchanges pe LEFT JOIN users u ON u.user_id = pe.user_id
               ORDER BY pe.id DESC LIMIT %s OFFSET %s""",
            (OD_LIST_PAGE, offset),
        ).fetchall()
    cur_label = {"points": "نقطة", "jewels": "💎", "stars": "⭐"}
    items = []
    for r in rows:
        r = dict(r)
        cost = r.get("points_cost")
        try:
            cost_txt = f"{Decimal(str(cost)).normalize():f}"
        except Exception:
            cost_txt = str(cost)
        items.append(
            f"🎁 <b>{_e(r.get('prize_type') or '—')}</b>"
            + (f" — {_e(r['prize_value'])}" if r.get("prize_value") and r['prize_value'] not in ("number", "manual") else "")
            + f"\n👤 {od_who(r.get('username'), r.get('full_name'), r.get('user_id'))}"
            f"\n💰 {cost_txt} {cur_label.get(r['cur'], r['cur'])} | 📌 {_e(r.get('status') or '—')}"
            f" | 🧾 <code>{_e(r.get('order_code') or '—')}</code>"
            f"\n🕒 {od_fmt_dt(r.get('created_at'))}"
        )
    return total, items


def _od_win_wheel(offset: int):
    with db_conn() as c:
        total = int((c.execute("SELECT COUNT(*) AS cnt FROM wheel_results").fetchone() or {}).get("cnt") or 0)
        rows = c.execute(
            """SELECT w.id, w.user_id, w.prize_label, w.delivery, w.status, w.created_at,
                      u.username, u.full_name
               FROM wheel_results w LEFT JOIN users u ON u.user_id = w.user_id
               ORDER BY w.id DESC LIMIT %s OFFSET %s""",
            (OD_LIST_PAGE, offset),
        ).fetchall()
    items = []
    for r in rows:
        r = dict(r)
        items.append(
            f"🎡 <b>{_e(r.get('prize_label') or '—')}</b>"
            f"\n👤 {od_who(r.get('username'), r.get('full_name'), r.get('user_id'))}"
            f"\n📌 {_e(r.get('status') or '—')} | {_e(r.get('delivery') or '')}"
            f"\n🕒 {od_fmt_dt(r.get('created_at'))}"
        )
    return total, items


def _od_win_weekly(offset: int):
    try:
        with db_conn() as c:
            total = int((c.execute("SELECT COUNT(*) AS cnt FROM weekly_referral_awards").fetchone() or {}).get("cnt") or 0)
            rows = c.execute(
                "SELECT week_start, awarded_at, winners FROM weekly_referral_awards "
                "WHERE winners <> 'baseline' ORDER BY week_start DESC LIMIT %s OFFSET %s",
                (OD_LIST_PAGE, offset),
            ).fetchall()
    except Exception:
        return 0, []
    items = []
    for r in rows:
        r = dict(r)
        items.append(
            f"🏆 <b>أسبوع {od_fmt_dt(r.get('week_start'))[:10]}</b>\n"
            f"{_e(r.get('winners') or '—')}"
        )
    return total, items


def _od_win_ref_rewards(offset: int):
    with db_conn() as c:
        total = int((c.execute("SELECT COUNT(*) AS cnt FROM referral_reward_claims").fetchone() or {}).get("cnt") or 0)
        rows = c.execute(
            """SELECT rc.user_id, rc.granted_at, t.referral_count, t.free_minutes,
                      u.username, u.full_name
               FROM referral_reward_claims rc
               JOIN referral_reward_tiers t ON t.id = rc.tier_id
               LEFT JOIN users u ON u.user_id = rc.user_id
               ORDER BY rc.granted_at DESC LIMIT %s OFFSET %s""",
            (OD_LIST_PAGE, offset),
        ).fetchall()
    items = []
    for r in rows:
        r = dict(r)
        items.append(
            f"🎯 بلوغ {int(r.get('referral_count') or 0)} دعوة"
            + (f" (+{int(r['free_minutes'])} دقيقة مجانية)" if r.get("free_minutes") else "")
            + f"\n👤 {od_who(r.get('username'), r.get('full_name'), r.get('user_id'))}"
            f"\n🕒 {od_fmt_dt(r.get('granted_at'))}"
        )
    return total, items


OD_WIN_KINDS = {
    "x": ("🎁 الاستبدالات", _od_win_exchanges),
    "w": ("🎡 جوائز العجلة", _od_win_wheel),
    "k": ("🏆 الأكثر دعوة (أسبوعي)", _od_win_weekly),
    "r": ("🎯 مكافآت الإحالة", _od_win_ref_rewards),
}


async def od_show_wins_menu(q) -> None:
    rows = [[InlineKeyboardButton(title, callback_data=f"od:win:{key}:0")]
            for key, (title, _fn) in OD_WIN_KINDS.items()]
    rows.append([InlineKeyboardButton("🔙 زر التفاصيل", callback_data="od:menu")])
    await od_show(q, "🏆 <b>فوز الأعضاء</b>\n\nاختر القسم:", InlineKeyboardMarkup(rows))


async def od_show_wins(q, kind: str, offset: int = 0) -> None:
    if kind not in OD_WIN_KINDS:
        await od_show_wins_menu(q)
        return
    offset = max(0, int(offset))
    title, fn = OD_WIN_KINDS[kind]
    try:
        total, items = fn(offset)
    except Exception:
        logger.exception("تعذر جلب قائمة الفوز %s", kind)
        total, items = 0, []
    kb_rows = []
    nav = od_nav_row(f"od:win:{kind}", offset, total, OD_LIST_PAGE)
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton("🔙 فوز الأعضاء", callback_data="od:wins")])
    text = (f"{title} ({total})\n\n" + "\n➖➖➖\n".join(items)) if items else f"{title}\n\nلا توجد سجلات."
    await od_show(q, text, InlineKeyboardMarkup(kb_rows))


# ───────────────────────── 6) التقرير اليومي ─────────────────────────

def _od_decimal_setting(key: str, default: Decimal) -> Decimal:
    try:
        value = Decimal(str(get_setting(key) or "").strip())
        return value if value > 0 else default
    except (InvalidOperation, ValueError, TypeError):
        return default


STAR_KIND_LABELS = {
    "charge_stars": "شحن نقاط",
    "jewel_stars": "شحن جواهر",
    "smm_stars": "طلبات الرشق",
    "number_stars": "أرقام",
    "fund_mandatory": "تمويل قنوات",
    "fund_internal": "تمويل قنوات",
    "forced_ref_stars": "إحالة بوت",
    "legendary_stars": "خدمات أسطورية",
}


def record_star_income(payment, user) -> None:
    """يسجل كل دفعة نجوم ناجحة (مرة واحدة لكل عملية) ليعتمد عليها التقرير اليومي."""
    try:
        if str(getattr(payment, "currency", "") or "").upper() != "XTR":
            return
        charge = str(getattr(payment, "telegram_payment_charge_id", "") or "").strip()
        stars = int(getattr(payment, "total_amount", 0) or 0)
        if not charge or stars <= 0:
            return
        od_ensure_tables()
        kind = str(getattr(payment, "invoice_payload", "") or "").split(":", 1)[0][:40]
        with db_conn() as c:
            c.execute(
                "INSERT INTO star_income_log (telegram_payment_id,user_id,stars,kind) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT (telegram_payment_id) DO NOTHING",
                (charge, getattr(user, "id", None), stars, kind),
            )
    except Exception:
        logger.exception("تعذر تسجيل دفعة النجوم للتقرير اليومي")


def mark_star_income_refunded(charge_id: str) -> None:
    try:
        od_ensure_tables()
        with db_conn() as c:
            c.execute("UPDATE star_income_log SET refunded=TRUE WHERE telegram_payment_id=%s", (str(charge_id),))
    except Exception:
        logger.exception("تعذر وسم دفعة النجوم كمستردة")


def od_report_math(stars: int, spent_usd, gifted_jewels, star_usd=OD_STAR_USD_DEFAULT,
                   jewel_usd=OD_JEWEL_GIFT_USD_DEFAULT) -> dict:
    star_usd = Decimal(str(star_usd))
    jewel_usd = Decimal(str(jewel_usd))
    earned = Decimal(int(stars)) * star_usd
    spent = Decimal(str(spent_usd or 0))
    gifted_cost = Decimal(str(gifted_jewels or 0)) * jewel_usd
    return {
        "earned_usd": earned,
        "spent_usd": spent,
        "gifted_usd": gifted_cost,
        "net_usd": earned - spent - gifted_cost,
    }


def od_day_bounds(day):
    start = datetime(day.year, day.month, day.day, tzinfo=OD_TZ)
    return start, start + timedelta(days=1)


def od_build_daily_report(day) -> dict:
    od_ensure_tables()
    start, end = od_day_bounds(day)
    owner_id = int(OWNER_ID or 0)
    with db_conn() as c:
        o = c.execute(
            """SELECT COUNT(*) AS n, COALESCE(SUM(provider_cost_usd),0) AS spent
               FROM orders
               WHERE created_at::timestamptz >= %s AND created_at::timestamptz < %s
                 AND COALESCE(status,'') <> 'cancelled'""",
            (start, end),
        ).fetchone() or {}
        stars_rows = c.execute(
            """SELECT COALESCE(kind,'') AS kind, COALESCE(SUM(stars),0) AS stars, COUNT(*) AS n
               FROM star_income_log
               WHERE created_at >= %s AND created_at < %s AND NOT refunded
               GROUP BY COALESCE(kind,'') ORDER BY 2 DESC""",
            (start, end),
        ).fetchall()
        log_total = int((c.execute("SELECT COUNT(*) AS cnt FROM star_income_log").fetchone() or {}).get("cnt") or 0)
        g = c.execute(
            """SELECT COALESCE(SUM(amount),0) AS jewels, COUNT(*) AS n
               FROM jewel_transactions
               WHERE transaction_type='gift' AND admin_id IS NOT NULL AND amount > 0
                 AND created_at >= %s AND created_at < %s""",
            (start, end),
        ).fetchone() or {}
    by_kind = [(r["kind"], int(r["stars"]), int(r["n"])) for r in stars_rows]
    stars = sum(s for _k, s, _n in by_kind)
    star_usd = _od_decimal_setting("star_usd_value", OD_STAR_USD_DEFAULT)
    jewel_usd = _od_decimal_setting("jewel_gift_usd_value", OD_JEWEL_GIFT_USD_DEFAULT)
    math = od_report_math(stars, o.get("spent") or 0, g.get("jewels") or 0, star_usd, jewel_usd)
    math.update({
        "orders": int(o.get("n") or 0),
        "stars": stars,
        "by_kind": by_kind,
        "gifted_jewels": Decimal(str(g.get("jewels") or 0)),
        "log_total": log_total,
        "star_usd": star_usd,
        "jewel_usd": jewel_usd,
    })
    return math


def _usd(value) -> str:
    return f"{Decimal(str(value)):,.4f}$"


def od_render_daily_report(day, partial: bool = False) -> str:
    r = od_build_daily_report(day)
    kinds = {}
    for kind, stars, _n in r["by_kind"]:
        label = STAR_KIND_LABELS.get(kind, kind or "أخرى")
        kinds[label] = kinds.get(label, 0) + stars
    lines = [
        f"📊 <b>التقرير اليومي — {day.isoformat()}</b>" + (" (حتى الآن)" if partial else ""),
        "",
        f"💸 <b>المصروف على مواقع الرشق:</b> {_usd(r['spent_usd'])}  ({r['orders']:,} طلب)",
        "",
        f"⭐ <b>النجوم المستلمة:</b> {r['stars']:,} × {r['star_usd']} = {_usd(r['earned_usd'])}",
    ]
    for label, stars in sorted(kinds.items(), key=lambda kv: -kv[1]):
        lines.append(f"   • {_e(label)}: {stars:,} ⭐")
    lines += [
        "",
        f"🎁 <b>جواهر أهديتها:</b> {r['gifted_jewels']:,.2f} × {r['jewel_usd']} = {_usd(r['gifted_usd'])}",
        "",
        f"🧮 <b>الصافي</b> (النجوم − الرشق − الجواهر المُهداة): <b>{_usd(r['net_usd'])}</b>",
    ]
    if r["log_total"] == 0 or r["stars"] == 0:
        lines += ["", "ℹ️ تسجيل النجوم يبدأ من لحظة تفعيل هذا التحديث، وقبلها لا تظهر دفعات."]
    return "\n".join(lines)


async def od_show_report(q) -> None:
    day = datetime.now(OD_TZ).date()
    try:
        text = od_render_daily_report(day, partial=True)
    except Exception:
        logger.exception("تعذر بناء التقرير اليومي")
        text = "⚠️ تعذر بناء التقرير الآن."
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data="od:report")],
        [InlineKeyboardButton("🔙 زر التفاصيل", callback_data="od:menu")],
    ])
    await od_show(q, text, kb)


def _od_report_time():
    raw = str(get_setting("daily_report_time") or OD_REPORT_TIME_DEFAULT).strip()
    try:
        hh, mm = raw.split(":", 1)
        hh, mm = int(hh), int(mm)
        if 0 <= hh < 24 and 0 <= mm < 60:
            return hh, mm
    except Exception:
        pass
    hh, mm = OD_REPORT_TIME_DEFAULT.split(":")
    return int(hh), int(mm)


async def run_daily_report_job(context) -> None:
    """يُرسل التقرير مرة واحدة يومياً (23:55 بتوقيت UTC+3 افتراضياً)."""
    try:
        owner_id = int(OWNER_ID or 0)
        if not owner_id:
            return
        now = datetime.now(OD_TZ)
        if (now.hour, now.minute) < _od_report_time():
            return
        today = now.date().isoformat()
        if get_setting("daily_report_last_date") == today:
            return
        set_setting("daily_report_last_date", today)
        try:
            text = od_render_daily_report(now.date())
            await context.bot.send_message(owner_id, text[:4000], parse_mode=ParseMode.HTML)
        except Exception:
            set_setting("daily_report_last_date", "")  # نعيد المحاولة في الدورة التالية
            raise
    except Exception:
        logger.exception("فشل إرسال التقرير اليومي")


# ───────────────────────── القائمة الرئيسية لزر التفاصيل ─────────────────────────

def od_details_kb():
    try:
        od_ensure_tables()
        with db_conn() as c:
            waiting = int((c.execute(
                "SELECT COUNT(*) AS cnt FROM thank_messages WHERE replied_at IS NULL"
            ).fetchone() or {}).get("cnt") or 0)
    except Exception:
        waiting = 0
    thanks_label = "💌 عمليات رسائل الشكر" + (f" ({waiting})" if waiting else "")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 الطلبات", callback_data="od:orders:0")],
        [InlineKeyboardButton(thanks_label, callback_data="od:thx:0")],
        [InlineKeyboardButton("🚨 التنبيهات", callback_data="od:alerts")],
        [InlineKeyboardButton("🏆 فوز الأعضاء", callback_data="od:wins")],
        [InlineKeyboardButton("📊 تقرير اليوم", callback_data="od:report")],
        [InlineKeyboardButton("🔙 إعدادات المالك", callback_data="owner_settings")],
    ])


async def od_show_menu(q) -> None:
    await od_show(q, "📊 <b>زر التفاصيل</b>\n\nاختر ما تريد مراجعته:", od_details_kb())


# ───────────────────────── موزّعات الأزرار والنصوص ─────────────────────────

async def handle_od_callback(update, context, q, data, user, is_own) -> bool:
    if not data.startswith("od:") or not is_own:
        return False
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    def _int(index, default=0):
        try:
            return int(parts[index])
        except (IndexError, ValueError):
            return default

    if action != "thxr":
        context.user_data["state"] = "main_menu"

    if action == "menu":
        await od_show_menu(q)
    elif action == "orders":
        await od_show_owner_orders(q, _int(2))
    elif action == "thx":
        await od_show_thanks(q, _int(2))
    elif action == "thxv":
        await od_view_thank(q, context, _int(2), _int(3))
    elif action == "thxr":
        thank_id = _int(2)
        with db_conn() as c:
            row = c.execute("SELECT id, username, full_name, user_id FROM thank_messages WHERE id=%s",
                            (thank_id,)).fetchone()
        if not row:
            await q.answer("⚠️ الرسالة غير موجودة.", show_alert=True)
            return True
        context.user_data["state"] = "os_od_thx_reply"
        context.user_data["od_thx_id"] = thank_id
        await q.message.chat.send_message(
            f"↩️ <b>الرد على {od_who(row.get('username'), row.get('full_name'), row.get('user_id'))}</b>\n\n"
            "أرسل نص ردّك الآن وسيصل للعضو مباشرة.\nللإلغاء أرسل /start.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ إلغاء", callback_data=f"od:thx:0")
            ]]),
        )
    elif action == "alerts":
        await od_show_alerts_menu(q)
    elif action == "alf":
        await od_show_fraud_list(q, _int(2))
    elif action == "aln":
        await od_show_nouser_list(q, _int(2))
    elif action == "wins":
        await od_show_wins_menu(q)
    elif action == "win":
        await od_show_wins(q, parts[2] if len(parts) > 2 else "", _int(3))
    elif action == "report":
        await od_show_report(q)
    else:
        return False
    return True


async def handle_od_text(update, context, text: str, state: str) -> bool:
    if state != "os_od_thx_reply":
        return False
    od_ensure_tables()
    thank_id = context.user_data.get("od_thx_id")
    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💌 رسائل الشكر", callback_data="od:thx:0")],
        [InlineKeyboardButton("🔙 زر التفاصيل", callback_data="od:menu")],
    ])
    if not thank_id or not text:
        context.user_data["state"] = "main_menu"
        await update.message.reply_text("⚠️ انتهت جلسة الرد، افتح الرسالة من جديد.", reply_markup=back_kb)
        return True
    with db_conn() as c:
        row = c.execute("SELECT user_id FROM thank_messages WHERE id=%s", (int(thank_id),)).fetchone()
    if not row:
        context.user_data["state"] = "main_menu"
        await update.message.reply_text("⚠️ الرسالة غير موجودة.", reply_markup=back_kb)
        return True
    try:
        await context.bot.send_message(
            int(row["user_id"]),
            f"💌 <b>رد من المالك على رسالتك:</b>\n\n{_e(text)}",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.warning("تعذر إرسال رد الشكر للعضو %s: %s", row["user_id"], exc)
        await update.message.reply_text(
            "⚠️ تعذر وصول الرد للعضو (ربما حظر البوت). لم يُسجَّل كمُرسل.", reply_markup=back_kb)
        context.user_data["state"] = "main_menu"
        return True
    with db_conn() as c:
        c.execute("UPDATE thank_messages SET replied_at=NOW(), reply_text=%s WHERE id=%s",
                  (text, int(thank_id)))
    context.user_data["state"] = "main_menu"
    context.user_data.pop("od_thx_id", None)
    await update.message.reply_text("✅ وصل ردّك للعضو.", reply_markup=back_kb)
    return True
