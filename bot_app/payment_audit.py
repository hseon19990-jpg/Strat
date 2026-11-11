"""قسم المالك «تدقيق دفعات النجوم».

يجيب عن أسئلة الشكاوى مثل «دفعت نجوم ولم تصلني جواهر»:
  • هل سُلِّمت الجواهر فعلاً لكل دفعة؟ (مطابقة سجل الدفع star_income_log مع جداول التسليم)
  • ماذا فعل العضو بالجواهر التي وصلته من هذه الدفعة؟ (تتبع بنظام الأقدم أولاً)
  • حركة جواهر العضو كاملة مع مقارنة المجموع المسجل بالرصيد الحالي.
  • تقرير بكل الدفعات الناجحة التي لم تُسلَّم (آخر 30 يوماً).

المالك يرسل: معرّف العضو، أو @يوزر، أو رقم عملية الدفع (charge id).
"""

import asyncio
import html
import re
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

from .order_inspect import (
    _oi_collect_events,
    _oi_e,
    _oi_query,
    _oi_user_line,
    oi_fmt_amount,
    oi_split_message,
    oi_to_decimal,
)
from .owner_details import od_fmt_dt

PA_STATE = "os_pa_await_query"
PA_LIST_LIMIT = 12            # أقصى دفعات تُعرض لعضو واحد
PA_LEDGER_LIMIT = 25          # أقصى حركات تُعرض في سجل الجواهر
PA_BAD_LIMIT = 30             # أقصى دفعات غير مسلّمة في التقرير العام
PA_GRACE_SECONDS = 180        # لا نعدّ الدفعة «غير مسلّمة» قبل مرور هذه المدة
PA_BAD_DAYS = 30
_PA_TG_LIMIT = 3900

_PA_KIND_AR = {
    "jewel_stars": "شحن جواهر",
    "charge_stars": "شحن نقاط",
    "smm_stars": "طلب رشق بالنجوم",
    "number_stars": "شراء رقم",
    "tgnum_stars": "رقم تيليجرام",
    "fund_mandatory": "تمويل اشتراك إجباري",
    "fund_internal": "تمويل داخلي",
    "forced_ref_stars": "إحالة إجبارية",
    "legendary_stars": "خدمة أسطورية",
    "raksh_stars": "رشق أسطوري",
    "wheel_stars": "عجلة الحظ",
}

_pa_schema_ready = False


# ───────────────────────── أدوات عامة ─────────────────────────

def pa_ensure_schema() -> None:
    """يضمن وجود جدول سجل النجوم وعمود الحمولة (idempotent)."""
    global _pa_schema_ready
    if _pa_schema_ready:
        return
    try:
        from .owner_details import od_ensure_tables
        od_ensure_tables()
        with db_conn() as c:
            c.execute("ALTER TABLE star_income_log ADD COLUMN IF NOT EXISTS payload TEXT")
        _pa_schema_ready = True
    except Exception:
        logger.exception("payment_audit: تعذر تجهيز جدول سجل النجوم")


def _pa_ts_value(ts) -> float:
    if ts is None:
        return 0.0
    try:
        if isinstance(ts, datetime):
            d = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            return d.timestamp()
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except Exception:
        return 0.0


def _pa_kind_title(kind) -> str:
    kind = str(kind or "").strip()
    return _PA_KIND_AR.get(kind, kind or "غير معروف")


def pa_expected_jewels_from_payload(payload):
    """يستخرج الجواهر المتوقعة من حمولة فاتورة jewel_stars:{micro}:{user}:{stars}:v2."""
    parts = str(payload or "").split(":")
    if len(parts) == 5 and parts[0] == "jewel_stars" and parts[1].isdigit():
        return Decimal(int(parts[1])) / Decimal(1_000_000)
    if len(parts) in (3, 4) and parts[0] == "jewel_stars" and parts[1].isdigit():
        return Decimal(int(parts[1]))
    return None


def pa_trace_lot(events, lot_key):
    """يتتبع رصيداً دخل المحفظة (lot_key) بنظام الأقدم أولاً.

    يعيد (spent, remaining, found): spent قائمة (حدث الصرف، المقدار المأخوذ من هذا الرصيد)،
    remaining ما بقي منه غير مصروف، found هل وُجد الرصيد في السجل أصلاً.
    """
    lots = deque()
    spent = []
    found = False
    for event in events:
        amount = oi_to_decimal(event.get("amount"))
        if amount > 0:
            if event.get("key") == lot_key:
                found = True
            lots.append([event, amount])
            continue
        if amount == 0:
            continue
        need = -amount
        while need > 0 and lots:
            lot_event, remaining = lots[0]
            use = remaining if remaining <= need else need
            if lot_event.get("key") == lot_key:
                spent.append((event, use))
            need -= use
            if use >= remaining:
                lots.popleft()
            else:
                lots[0][1] = remaining - use
    left = sum((rem for lot_event, rem in lots if lot_event.get("key") == lot_key), Decimal(0))
    return spent, left, found


def pa_classify(p, now_ts=None):
    """يعيد (أيقونة، وصف) لحالة تسليم دفعة. p قاموس من pa_collect_payments."""
    now_ts = now_ts or datetime.now(timezone.utc).timestamp()
    kind = p.get("kind")
    jst, st, comp, intent = p.get("jst"), p.get("st"), p.get("comp"), p.get("intent")
    if p.get("refunded"):
        return "↩️", "استُردّت النجوم (Refund)"
    young = (now_ts - p.get("ts_value", 0)) < PA_GRACE_SECONDS if p.get("ts_value") else False

    if kind == "jewel_stars":
        if jst and jst.get("status") == "completed":
            return "✅", f"سُلّمت {oi_fmt_amount(jst.get('jewels_given'))} 💎"
        if comp:
            return "🟡", f"عُوّضت بالجواهر ({oi_fmt_amount(comp.get('amount'))} 💎) بعد عدم تطابق الفاتورة"
        if jst:
            return "⚠️", f"سجل التسليم موجود بحالة «{_oi_e(jst.get('status'))}» دون اكتماله"
        if young:
            return "⏳", "حديثة؛ قيد المعالجة"
        return "❌", "دُفعت النجوم ولم تُسلَّم الجواهر"
    if kind == "charge_stars":
        if st and st.get("status") == "completed":
            return "✅", f"أُضيفت {oi_fmt_amount(st.get('points_given'))} نقطة"
        if st:
            return "⚠️", f"سجل الشحن بحالة «{_oi_e(st.get('status'))}»"
        if young:
            return "⏳", "حديثة؛ قيد المعالجة"
        return "❌", "دُفعت النجوم ولم تُضَف النقاط"
    if kind == "smm_stars":
        if comp:
            return "🟡", f"عُوّضت بالجواهر ({oi_fmt_amount(comp.get('amount'))} 💎)"
        if intent:
            status = str(intent.get("status") or "")
            if status in {"needs_review", "refund_required", "failed"}:
                return "⚠️", f"طلب الرشق يحتاج مراجعة ({_oi_e(status)})"
            return "🔹", f"طلب رشق {_oi_e(intent.get('order_code') or '')} — حالته «{_oi_e(status)}»".replace("  ", " ")
        if young:
            return "⏳", "حديثة؛ قيد المعالجة"
        return "⚠️", "لا يوجد طلب رشق مرتبط بهذه الدفعة"
    if jst and jst.get("status") == "completed":
        return "✅", f"سُلّمت {oi_fmt_amount(jst.get('jewels_given'))} 💎"
    return "🔹", f"نوع «{_oi_e(_pa_kind_title(kind))}» — لا يُفحص تسليمه هنا"


# ───────────────────────── جمع البيانات ─────────────────────────

def pa_collect_payments(user_id, limit=PA_LIST_LIMIT):
    """يدمج كل ما يخص دفعات النجوم لعضو: سجل الدخل + جداول التسليم + التعويضات."""
    pa_ensure_schema()
    uid = int(user_id)
    income = _oi_query(
        "SELECT * FROM star_income_log WHERE user_id=%s ORDER BY created_at DESC LIMIT 80", (uid,)
    )
    jst_rows = _oi_query(
        "SELECT * FROM jewel_star_transactions WHERE user_id=%s ORDER BY created_at DESC LIMIT 80", (uid,)
    )
    st_rows = _oi_query(
        "SELECT * FROM star_transactions WHERE user_id=%s ORDER BY id DESC LIMIT 80", (uid,)
    )
    comp_rows = _oi_query(
        "SELECT id, amount, reference, created_at FROM jewel_transactions "
        "WHERE user_id=%s AND reference LIKE %s ORDER BY id DESC LIMIT 80",
        (uid, "star_payment_jewels:%"),
    )
    intent_rows = _oi_query(
        "SELECT id, status, order_code, cost_stars, telegram_payment_id FROM smm_payment_intents "
        "WHERE user_id=%s AND telegram_payment_id IS NOT NULL ORDER BY id DESC LIMIT 80",
        (uid,),
    )
    comp_by_charge = {str(r["reference"]).split(":", 1)[1]: r for r in comp_rows if ":" in str(r["reference"])}
    intent_by_charge = {str(r["telegram_payment_id"]): r for r in intent_rows}

    merged = {}

    def slot(cid):
        return merged.setdefault(str(cid), {
            "cid": str(cid), "stars": None, "kind": None, "refunded": False, "ts": None,
            "payload": None, "in_income": False, "jst": None, "st": None,
        })

    for r in income:
        p = slot(r["telegram_payment_id"])
        p.update(stars=r.get("stars"), kind=r.get("kind") or p["kind"], refunded=bool(r.get("refunded")),
                 ts=r.get("created_at"), payload=r.get("payload"), in_income=True)
    for r in jst_rows:
        p = slot(r["telegram_payment_id"])
        p["jst"] = r
        p["kind"] = p["kind"] or "jewel_stars"
        p["stars"] = p["stars"] if p["stars"] is not None else r.get("stars")
        p["ts"] = p["ts"] or r.get("created_at")
    for r in st_rows:
        if not r.get("telegram_payment_id"):
            continue
        p = slot(r["telegram_payment_id"])
        p["st"] = r
        p["kind"] = p["kind"] or "charge_stars"
        p["stars"] = p["stars"] if p["stars"] is not None else r.get("stars")
        p["ts"] = p["ts"] or r.get("created_at")

    payments = list(merged.values())
    for p in payments:
        p["comp"] = comp_by_charge.get(p["cid"])
        p["intent"] = intent_by_charge.get(p["cid"])
        p["ts_value"] = _pa_ts_value(p["ts"])
    payments.sort(key=lambda x: x["ts_value"], reverse=True)
    return payments[:limit]


def pa_user_row(user_id):
    return _oi_query(
        "SELECT user_id, username, full_name, jewels, points FROM users WHERE user_id=%s",
        (int(user_id),), one=True,
    )


def pa_find_target(raw):
    """يحدد ما أرسله المالك: ('user', id) أو ('charge', {cid, user_id}) أو None."""
    text = str(raw or "").strip().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))
    if not text:
        return None
    if re.fullmatch(r"-?\d{5,}", text):
        return "user", int(text)
    if text.startswith("@") or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", text):
        row = _oi_query(
            "SELECT user_id FROM users WHERE LOWER(username)=LOWER(%s) LIMIT 1",
            (text.lstrip("@"),), one=True,
        )
        if row:
            return "user", int(row["user_id"])
    pa_ensure_schema()
    for table in ("star_income_log", "jewel_star_transactions", "star_transactions"):
        row = _oi_query(
            f"SELECT user_id, telegram_payment_id FROM {table} WHERE telegram_payment_id=%s LIMIT 1",
            (text,), one=True,
        ) or _oi_query(
            f"SELECT user_id, telegram_payment_id FROM {table} WHERE telegram_payment_id ILIKE %s LIMIT 1",
            (f"%{text}%",), one=True,
        )
        if row and row.get("user_id"):
            return "charge", {"cid": str(row["telegram_payment_id"]), "user_id": int(row["user_id"])}
    return None


def pa_unsettled(limit=PA_BAD_LIMIT):
    """دفعات ناجحة في سجل النجوم لا أثر تسليم لها (آخر PA_BAD_DAYS يوماً)."""
    pa_ensure_schema()
    return _oi_query(
        """
        SELECT i.telegram_payment_id, i.user_id, i.stars, i.kind, i.created_at
        FROM star_income_log i
        WHERE NOT i.refunded
          AND i.created_at < NOW() - make_interval(secs => %s)
          AND i.created_at > NOW() - make_interval(days => %s)
          AND NOT EXISTS (
              SELECT 1 FROM jewel_transactions t
              WHERE t.reference = 'star_payment_jewels:' || i.telegram_payment_id)
          AND (
              (i.kind = 'jewel_stars' AND NOT EXISTS (
                  SELECT 1 FROM jewel_star_transactions j
                  WHERE j.telegram_payment_id = i.telegram_payment_id AND j.status = 'completed'))
              OR
              (i.kind = 'charge_stars' AND NOT EXISTS (
                  SELECT 1 FROM star_transactions s
                  WHERE s.telegram_payment_id = i.telegram_payment_id AND s.status = 'completed'))
          )
        ORDER BY i.created_at DESC
        LIMIT %s
        """,
        (PA_GRACE_SECONDS, PA_BAD_DAYS, int(limit)),
    )


def pa_recent_stats():
    row = _oi_query(
        "SELECT COUNT(*) AS cnt, COALESCE(SUM(stars),0) AS stars FROM star_income_log "
        "WHERE NOT refunded AND created_at > NOW() - INTERVAL '24 hours'",
        one=True,
    ) or {}
    return int(row.get("cnt") or 0), int(row.get("stars") or 0)


# ───────────────────────── وصف الصرف ─────────────────────────

def _pa_spend_label(event) -> str:
    origin = event.get("origin")
    ref = str(event.get("reference") or "")
    tx_type = str(event.get("tx_type") or "")
    if origin == "exchange":
        return f"حوّلها إلى <b>{oi_fmt_amount(event.get('points'))}</b> نقطة"
    match = re.match(r"^smm_intent:(\d+)$", ref)
    if match:
        row = _oi_query(
            "SELECT order_code, service_name, quantity FROM smm_payment_intents WHERE id=%s",
            (int(match.group(1)),), one=True,
        )
        if row:
            code = _oi_e(row.get("order_code"), "بلا كود")
            return f"دفع بها طلب <b>{code}</b> — {_oi_e(row.get('service_name'))} × {oi_fmt_amount(row.get('quantity'))}"
        return f"دفع بها طلباً (<code>{_oi_e(ref)}</code>)"
    if ref.startswith("tgnum_order:"):
        return f"اشترى بها رقم تيليجرام (<code>{_oi_e(ref)}</code>)"
    if tx_type == "fraud_reset":
        return "صُفّرت بسبب كشف احتيال في الإحالة"
    if event.get("admin_id"):
        return f"خصمها المالك/المشرف <code>{_oi_e(event.get('admin_id'))}</code>"
    return f"{_oi_e(tx_type or 'حركة')} — <code>{_oi_e(ref)}</code>" if ref else _oi_e(tx_type or "حركة")


def _pa_event_title(event) -> str:
    origin, tx_type = event.get("origin"), str(event.get("tx_type") or "")
    ref = str(event.get("reference") or "")
    if origin == "stars":
        return f"شحن بالنجوم ({oi_fmt_amount(event.get('stars'))} ⭐)"
    if origin == "exchange":
        return "تحويل نقاط ← جواهر" if tx_type == "points_to_jewels" else "تحويل جواهر ← نقاط"
    if ref.startswith("referral:") or tx_type == "referral":
        return "مكافأة إحالة"
    if ref.startswith("wheel:"):
        return "جائزة عجلة"
    if ref.startswith("star_payment_jewels:"):
        return "تعويض دفعة نجوم"
    if ref.startswith("smm_refund:"):
        return "استرداد طلب"
    if ref.startswith("smm_intent:"):
        return "دفع طلب رشق"
    if ref.startswith("tgnum_order:"):
        return "شراء رقم تيليجرام"
    if tx_type == "gift":
        return "هدية من المالك" if event.get("admin_id") else "هدية"
    return tx_type or "حركة"


# ───────────────────────── العرض ─────────────────────────

def _pa_user_header(row, uid) -> str:
    if not row:
        return f"👤 عضو غير موجود في جدول الأعضاء — <code>{int(uid)}</code>"
    return _oi_user_line(row.get("full_name"), row.get("username"), row.get("user_id"))


def pa_render_user(uid, payments):
    row = pa_user_row(uid)
    lines = ["🧾 <b>تدقيق دفعات النجوم</b>", "", _pa_user_header(row, uid)]
    if row:
        lines.append(
            f"💎 رصيده الآن: <b>{oi_fmt_amount(row.get('jewels'))}</b> • ⭐ نقاطه: <b>{oi_fmt_amount(row.get('points'))}</b>"
        )
    if not payments:
        lines += ["", "لا توجد أي دفعة نجوم مسجلة لهذا العضو في البوت.",
                  "<i>إن أكد العضو أنه دفع، فأرسل لي رقم العملية (charge id) من إيصال تيليجرام للبحث به.</i>"]
        return "\n".join(lines)

    now_ts = datetime.now(timezone.utc).timestamp()
    bad = 0
    total_stars = 0
    delivered_jewels = Decimal(0)
    rows_text = []
    for index, p in enumerate(payments, 1):
        icon, label = pa_classify(p, now_ts)
        bad += icon == "❌"
        if not p.get("refunded") and p.get("stars"):
            total_stars += int(p["stars"])
        if p.get("jst") and p["jst"].get("status") == "completed":
            delivered_jewels += oi_to_decimal(p["jst"].get("jewels_given"))
        rows_text.append(
            f"{index}. {icon} <b>{oi_fmt_amount(p.get('stars'))}⭐</b> — {_oi_e(_pa_kind_title(p.get('kind')))}\n"
            f"    🕒 {_oi_e(od_fmt_dt(p.get('ts')))} • {label}"
        )
    lines += [
        "",
        f"📊 آخر {len(payments)} دفعة: ⭐ {total_stars:,} مدفوعة • 💎 {oi_fmt_amount(delivered_jewels)} سُلّمت عبر الشحن",
        ("🚨 <b>يوجد دفعات لم تُسلَّم!</b> افتح تفاصيلها بالأسفل." if bad else "✅ لا توجد دفعات غير مسلّمة بين هذه الدفعات."),
        "",
    ]
    lines += rows_text
    lines += ["", "<i>اضغط رقم الدفعة لعرض تفاصيلها وماذا فعل العضو بجواهرها.</i>"]
    return "\n".join(lines)


def pa_user_kb(uid, count):
    rows, buttons = [], []
    for index in range(1, count + 1):
        buttons.append(InlineKeyboardButton(f"🔬 {index}", callback_data=f"os:pa:d:{int(uid)}:{index - 1}"))
        if len(buttons) == 4:
            rows.append(buttons)
            buttons = []
    if buttons:
        rows.append(buttons)
    rows.append([
        InlineKeyboardButton("📜 حركة الجواهر", callback_data=f"os:pa:led:{int(uid)}"),
        InlineKeyboardButton("🔄 تحديث", callback_data=f"os:pa:u:{int(uid)}"),
    ])
    rows.append([
        InlineKeyboardButton("⚠️ الدفعات غير المسلّمة", callback_data="os:pa:bad"),
        InlineKeyboardButton("🔍 عضو آخر", callback_data="os:pa:ask"),
    ])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
    return InlineKeyboardMarkup(rows)


def pa_render_detail(uid, p):
    icon, label = pa_classify(p)
    kind = p.get("kind")
    lines = [
        "🔬 <b>تفاصيل الدفعة</b>", "",
        f"{icon} {label}", "",
        f"🧾 رقم العملية: <code>{_oi_e(p.get('cid'))}</code>",
        f"⭐ النجوم: <b>{oi_fmt_amount(p.get('stars'))}</b> • النوع: {_oi_e(_pa_kind_title(kind))}",
        f"🕒 الوقت: {_oi_e(od_fmt_dt(p.get('ts')))}",
        f"📒 مسجلة في سجل دخل النجوم: {'نعم' if p.get('in_income') else 'لا (دفعة قديمة أو لم تُسجَّل)'}",
    ]
    jst = p.get("jst")
    if kind == "jewel_stars":
        expected = pa_expected_jewels_from_payload(p.get("payload"))
        if expected is not None:
            lines.append(f"💎 المتوقع حسب الفاتورة: {oi_fmt_amount(expected)}")
        elif p.get("stars"):
            try:
                estimate = jewels_for_stars(int(p["stars"]))
                lines.append(f"💎 تقدير بالسعر الحالي ({oi_fmt_amount(get_jewels_per_star())}/نجمة): {oi_fmt_amount(estimate)}")
            except Exception:
                pass
        if jst:
            lines.append(
                f"✅ سجل التسليم #{jst.get('id')}: {oi_fmt_amount(jst.get('jewels_given'))} 💎 "
                f"• {_oi_e(od_fmt_dt(jst.get('created_at')))} • الحالة «{_oi_e(jst.get('status'))}»"
            )
            if expected is not None and oi_to_decimal(jst.get("jewels_given")) != expected:
                lines.append("⚠️ الكمية المسلّمة تختلف عن المتوقعة في الفاتورة.")
        else:
            lines.append("❌ لا يوجد سجل تسليم لهذه الدفعة في jewel_star_transactions.")
        if p.get("comp"):
            lines.append(f"🟡 تعويض مسجل في دفتر الجواهر: {oi_fmt_amount(p['comp'].get('amount'))} 💎")
    elif kind == "charge_stars" and p.get("st"):
        lines.append(f"سجل الشحن: {oi_fmt_amount(p['st'].get('points_given'))} نقطة • الحالة «{_oi_e(p['st'].get('status'))}»")

    if jst and jst.get("status") == "completed":
        events = _oi_collect_events(uid)
        spent, left, found = pa_trace_lot(events, ("stars", int(jst["id"])))
        lines += ["", "━━━━━━━━━━", "🔎 <b>ماذا فعل بجواهر هذه الدفعة؟</b>",
                  "<i>تقدير بنظام «الأقدم أولاً» (الرصيد غير مقسّم فعلياً حسب المصدر).</i>"]
        if not found:
            lines.append("لم أجد هذه الدفعة في حركات الجواهر.")
        elif not spent:
            lines.append(f"لم يصرف منها شيئاً بعد؛ بقيت كاملة <b>{oi_fmt_amount(left)}</b> 💎.")
        else:
            for event, amount in spent[:15]:
                lines.append(
                    f"• {_oi_e(od_fmt_dt(event.get('ts')))} — <b>{oi_fmt_amount(amount)}</b> 💎: {_pa_spend_label(event)}"
                )
            if len(spent) > 15:
                lines.append(f"… و{len(spent) - 15} عملية أخرى")
            lines.append(f"المتبقي منها: <b>{oi_fmt_amount(left)}</b> 💎")
    elif kind == "jewel_stars":
        lines += ["", "<i>لا يمكن تتبع الصرف لأن الجواهر لم تُسلَّم أصلاً.</i>",
                  "<i>راجع سجل أخطاء البوت (logs) وقت هذه الدفعة لمعرفة سبب الفشل.</i>"]
    return "\n".join(lines)


def pa_detail_kb(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 كل دفعات العضو", callback_data=f"os:pa:u:{int(uid)}"),
         InlineKeyboardButton("📜 حركة الجواهر", callback_data=f"os:pa:led:{int(uid)}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
    ])


def pa_render_ledger(uid):
    row = pa_user_row(uid)
    events = _oi_collect_events(uid)
    lines = ["📜 <b>حركة الجواهر</b>", "", _pa_user_header(row, uid)]
    if not events:
        lines += ["", "لا توجد حركات جواهر مسجلة."]
    else:
        total = sum((oi_to_decimal(e.get("amount")) for e in events), Decimal(0))
        current = oi_to_decimal((row or {}).get("jewels"))
        lines.append(f"💎 الرصيد الحالي: <b>{oi_fmt_amount(current)}</b> • مجموع الحركات المسجلة: <b>{oi_fmt_amount(total)}</b>")
        diff = current - total
        if diff != 0:
            lines.append(
                f"⚠️ فرق <b>{oi_fmt_amount(diff)}</b> بين الرصيد والمسجل (رصيد قديم قبل التسجيل أو تعديل مباشر في القاعدة)."
            )
        lines += ["", f"آخر {min(len(events), PA_LEDGER_LIMIT)} حركة (الأحدث أولاً):"]
        for event in list(reversed(events))[:PA_LEDGER_LIMIT]:
            amount = oi_to_decimal(event.get("amount"))
            sign = "➕" if amount > 0 else "➖"
            lines.append(
                f"{sign} {oi_fmt_amount(abs(amount))} 💎 — {_oi_e(_pa_event_title(event))} • {_oi_e(od_fmt_dt(event.get('ts')))}"
            )
    return "\n".join(lines)


def pa_render_unsettled():
    rows = pa_unsettled()
    count_24h, stars_24h = pa_recent_stats()
    lines = ["⚠️ <b>دفعات نجوم لم تُسلَّم</b>", "",
             f"آخر 24 ساعة: {count_24h} دفعة • ⭐ {stars_24h:,}", ""]
    if not rows:
        lines.append(f"✅ لا توجد دفعات غير مسلّمة خلال آخر {PA_BAD_DAYS} يوماً (شحن جواهر/نقاط).")
        lines.append("<i>يشمل ما سُجّل في سجل دخل النجوم فقط.</i>")
        return "\n".join(lines), []
    lines.append(f"🚨 وُجدت <b>{len(rows)}</b> دفعة تحتاج مراجعة:")
    for row in rows:
        lines.append(
            f"• <code>{_oi_e(row.get('user_id'))}</code> — {oi_fmt_amount(row.get('stars'))}⭐ "
            f"{_oi_e(_pa_kind_title(row.get('kind')))} • {_oi_e(od_fmt_dt(row.get('created_at')))}\n"
            f"   <code>{_oi_e(row.get('telegram_payment_id'))}</code>"
        )
    return "\n".join(lines), rows


# ───────────────────────── المعالجات ─────────────────────────

def _pa_prompt_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ الدفعات غير المسلّمة", callback_data="os:pa:bad")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
    ])


async def _pa_show(q_or_message, text, kb, edit=True):
    chunks = oi_split_message(text, _PA_TG_LIMIT)
    for index, chunk in enumerate(chunks):
        last = index == len(chunks) - 1
        markup = kb if last else None
        if index == 0 and edit:
            try:
                await q_or_message.edit_message_text(
                    chunk, parse_mode=ParseMode.HTML, reply_markup=markup, disable_web_page_preview=True,
                )
                continue
            except Exception:
                logger.warning("payment_audit: تعذر تعديل الرسالة، سيُرسل جزء جديد")
            target = q_or_message.message
        elif edit:
            target = q_or_message.message
        else:
            target = q_or_message
        await target.reply_text(chunk, parse_mode=ParseMode.HTML, reply_markup=markup, disable_web_page_preview=True)


def _pa_build_user_view(uid):
    payments = pa_collect_payments(uid)
    return pa_render_user(uid, payments), pa_user_kb(uid, len(payments))


async def handle_payment_audit_callback(update, context, q, data: str, user, is_owner: bool) -> bool:
    if not data.startswith("os:pa:"):
        return False
    if not is_owner:
        await q.answer("🚫 هذا القسم للمالك فقط.", show_alert=True)
        return True
    parts = data.split(":")
    action = parts[2] if len(parts) > 2 else ""

    if action == "ask":
        context.user_data["state"] = PA_STATE
        await _pa_show(
            q,
            "🧾 <b>تدقيق دفعات النجوم</b>\n\nأرسل أحد التالي:\n"
            "• معرّف العضو (رقم)\n• يوزره <code>@name</code>\n• رقم عملية الدفع (charge id)\n\n"
            "ويظهر لك: هل سُلّمت الجواهر؟ وماذا فعل بها؟",
            _pa_prompt_kb(),
        )
        return True

    if action == "bad":
        text, rows = await asyncio.to_thread(pa_render_unsettled)
        kb_rows, seen = [], set()
        for row in rows:
            uid = row.get("user_id")
            if uid and uid not in seen and len(seen) < 8:
                seen.add(uid)
                kb_rows.append([InlineKeyboardButton(f"👤 {uid}", callback_data=f"os:pa:u:{int(uid)}")])
        kb_rows.append([InlineKeyboardButton("🔄 تحديث", callback_data="os:pa:bad"),
                        InlineKeyboardButton("🔍 عضو", callback_data="os:pa:ask")])
        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await _pa_show(q, text, InlineKeyboardMarkup(kb_rows))
        return True

    if len(parts) < 4 or not re.fullmatch(r"-?\d+", parts[3]):
        return True
    uid = int(parts[3])

    if action == "u":
        context.user_data["state"] = "main_menu"
        text, kb = await asyncio.to_thread(_pa_build_user_view, uid)
        await _pa_show(q, text, kb)
    elif action == "led":
        text = await asyncio.to_thread(pa_render_ledger, uid)
        await _pa_show(q, text, pa_detail_kb(uid))
    elif action == "d" and len(parts) >= 5 and parts[4].isdigit():
        index = int(parts[4])
        payments = await asyncio.to_thread(pa_collect_payments, uid)
        if index >= len(payments):
            await q.answer("تغيّرت القائمة، حدّثها.", show_alert=True)
            return True
        text = await asyncio.to_thread(pa_render_detail, uid, payments[index])
        await _pa_show(q, text, pa_detail_kb(uid))
    return True


async def handle_payment_audit_text(update, context, text: str) -> bool:
    user = update.effective_user
    if context.user_data.get("state") != PA_STATE:
        return False
    if user is None or user.id != OWNER_ID:
        return False
    message = update.message
    target = await asyncio.to_thread(pa_find_target, text)
    if not target:
        await message.reply_text(
            "⚠️ لم أجد عضواً أو دفعة بهذا المدخل.\nأرسل معرّف العضو أو @يوزره أو رقم عملية الدفع:",
            reply_markup=_pa_prompt_kb(),
        )
        return True
    context.user_data["state"] = "main_menu"
    kind, value = target
    if kind == "user":
        view, kb = await asyncio.to_thread(_pa_build_user_view, value)
        await _pa_show(message, view, kb, edit=False)
        return True

    uid, cid = value["user_id"], value["cid"]
    payments = await asyncio.to_thread(pa_collect_payments, uid, 200)
    match = next((p for p in payments if p["cid"] == cid), None)
    if match is None:
        view, kb = await asyncio.to_thread(_pa_build_user_view, uid)
        await _pa_show(message, view, kb, edit=False)
        return True
    detail = await asyncio.to_thread(pa_render_detail, uid, match)
    await _pa_show(message, detail, pa_detail_kb(uid), edit=False)
    return True
