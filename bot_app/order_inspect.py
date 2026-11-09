"""قسم المالك «فحص الطلب».

يرسل المالك كود الطلب (1-1-1 أو 111 أو بالأرقام العربية) فيظهر اسم الطالب
وتحته أربعة أزرار: معلومات الطلب بالموقع، معلومات الخدمة في البوت، معلومات
الشخص، ومصدر الجواهر.

تُحفظ «لقطة» صغيرة عند إنشاء كل طلب (جدول order_inspect_snapshots) لأن مصدر
الجواهر وحالة العضو يتغيران بعد الشراء. تُمسح اللقطة تلقائياً بعد أسبوع
(ORDER_INSPECT_RETENTION_DAYS) حتى لا تمتلئ قاعدة البيانات؛ أما سجل الطلب
نفسه في جدول orders فلا يُمس.
"""

import html
import json
import re
from collections import deque
from decimal import Decimal, InvalidOperation

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

ORDER_INSPECT_RETENTION_DAYS = 7
ORDER_INSPECT_PURGE_BATCH = 500
ORDER_INSPECT_FALLBACK_SCAN = 3000      # آخر طلبات يُبحث فيها إن لم توجد لقطة
ORDER_INSPECT_MAX_EVENTS = 20000        # سقف حركات الجواهر المقروءة لعضو واحد
ORDER_INSPECT_MAX_PERSONS = 25          # أقصى عدد محالين يُسرد بالاسم
ORDER_INSPECT_STATE = "os_oi_await_code"
_OI_TG_LIMIT = 3900

_OI_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_OI_DASHES = str.maketrans({"–": "-", "—": "-", "‑": "-", "−": "-", "ـ": "-", "_": "-", "/": "-"})

_OI_USER_LABELS = {
    "user_id": "🆔 المعرّف",
    "username": "🔗 اليوزر",
    "full_name": "👤 الاسم",
    "points": "⭐ النقاط",
    "jewels": "💎 الجواهر",
    "referral_jewels": "💎 جواهر الإحالة",
    "invited_by": "👥 دعاه (ID)",
    "total_orders": "📦 عدد الطلبات",
    "joined_at": "📅 تاريخ الانضمام",
    "bot_user_num": "🔢 رقم العضو في البوت",
    "verified": "✅ متحقق",
    "banned": "🚫 محظور",
    "banned_at": "🕒 وقت الحظر",
    "ban_reason": "📝 سبب الحظر",
    "wheel_spins": "🎡 لفات العجلة",
    "referral_credited": "🎁 أُحتسبت إحالته",
    "credited_at": "🕒 وقت احتساب الإحالة",
    "referral_points_blocked": "⛔ منع نقاط الإحالة",
}

_OI_STATUS_AR = {
    "pending": "قيد التنفيذ",
    "processing": "قيد المعالجة",
    "in progress": "جارٍ التنفيذ",
    "completed": "مكتمل",
    "partial": "جزئي",
    "canceled": "ملغي",
    "cancelled": "ملغي",
    "failed": "فاشل",
    "refunded": "مُسترد",
}

_OI_KIND_TITLES = {
    "referral": "👥 إحالات",
    "exchange": "🔁 تحويل نقاط إلى جواهر",
    "star_purchase": "⭐ شراء جواهر بالنجوم",
    "admin_gift": "🎁 هدية من الإدارة",
    "wheel": "🎡 عجلة الحظ",
    "gift": "🎁 هدية",
    "order_refund": "↩️ استرداد من طلب سابق",
    "star_refund": "↩️ تعويض دفعة نجوم",
    "refund": "↩️ استرداد",
    "other": "❓ مصدر آخر",
    "unrecorded": "❔ غير مسجّل في السجل",
}


# ───────────────────────── دوال نقية (قابلة للاختبار بدون قاعدة بيانات) ─────────────────────────

def oi_clean_code(text) -> str:
    """يوحّد الأرقام العربية والشرطات ويحذف المسافات: «١ – ١ – ١» → «1-1-1»."""
    value = str(text or "").translate(_OI_DIGITS).translate(_OI_DASHES)
    value = re.sub(r"\s+", "", value)
    return value.strip("-").upper()


def oi_normalize_code(text) -> str:
    """يحذف كل ما ليس حرفاً أو رقماً: «1-1-1» و«111» تعطيان «111»."""
    return re.sub(r"[^0-9A-Za-z]", "", oi_clean_code(text))


def oi_to_decimal(value) -> Decimal:
    try:
        number = Decimal(str(value if value is not None else 0))
        return number if number.is_finite() else Decimal(0)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def oi_fmt_amount(value) -> str:
    number = oi_to_decimal(value)
    if number == number.to_integral_value():
        return f"{int(number):,}"
    text = format(number.normalize(), "f")
    whole, _, fraction = text.partition(".")
    return f"{int(whole):,}.{fraction}"


def oi_classify_source(tx_type, reference, admin_id=None, origin="ledger") -> str:
    """يصنّف رصيداً دخل المحفظة إلى مصدر مفهوم للمالك."""
    if origin == "exchange":
        return "exchange"
    if origin == "stars":
        return "star_purchase"
    reference = str(reference or "")
    tx_type = str(tx_type or "")
    if reference.startswith("referral:") or tx_type == "referral":
        return "referral"
    if reference.startswith("wheel:"):
        return "wheel"
    if reference.startswith("star_payment_jewels:"):
        return "star_refund"
    if reference.startswith("smm_refund:"):
        return "order_refund"
    if tx_type == "gift":
        return "admin_gift" if admin_id else "gift"
    if tx_type == "refund":
        return "refund"
    return "other"


def oi_parse_referral_reference(reference):
    """«referral:L2:from:555» → (2, 555) أو None."""
    match = re.match(r"^referral:L(\d+):from:(-?\d+)$", str(reference or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def oi_simulate_fifo(events, target_key):
    """يحاكي صرف الجواهر بنظام الأقدم أولاً ويعيد ما استهلكه الحدث المستهدف.

    events: قائمة مرتبة زمنياً من قواميس: key, amount (موجب = دخول، سالب = صرف)
    وبقية الحقول وصفية. يعيد (consumed, unrecorded) حيث consumed قائمة
    (lot, amount) و unrecorded ما لم يغطّه السجل (رصيد قديم بلا حركة مسجلة).
    """
    lots = deque()
    for event in events:
        amount = oi_to_decimal(event.get("amount"))
        if amount > 0:
            lots.append([event, amount])
            continue
        if amount == 0:
            continue
        need = -amount
        taken = []
        while need > 0 and lots:
            lot_event, remaining = lots[0]
            use = remaining if remaining <= need else need
            taken.append((lot_event, use))
            need -= use
            if use >= remaining:
                lots.popleft()
            else:
                lots[0][1] = remaining - use
        if event.get("key") == target_key:
            return taken, need
    return [], oi_to_decimal(0)


def oi_split_message(text: str, limit: int = _OI_TG_LIMIT):
    """يقسم النص الطويل على أسطر حتى لا يتجاوز حد تيليجرام."""
    chunks, current = [], ""
    for line in str(text).split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit and current:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks or [""]


def _oi_e(value, default="—") -> str:
    text = str(value).strip() if value is not None else ""
    return html.escape(text if text else default, quote=False)


def _oi_user_line(name, username, user_id) -> str:
    parts = [f"<b>{_oi_e(name, 'بدون اسم')}</b>"]
    if username:
        parts.append(f"@{_oi_e(str(username).lstrip('@'))}")
    parts.append(f"<code>{_oi_e(user_id)}</code>")
    return " — ".join(parts)


# ───────────────────────── قاعدة البيانات ─────────────────────────

def _oi_query(sql, params=(), one=False):
    """استعلام اختياري في اتصال مستقل؛ فشله لا يُفسد بقية المعلومات."""
    try:
        with db_conn() as c:
            cur = c.execute(sql, params)
            if one:
                row = cur.fetchone()
                return dict(row) if row else None
            return [dict(r) for r in (cur.fetchall() or [])]
    except Exception:
        logger.exception("order_inspect: استعلام اختياري فشل")
        return None if one else []


def purge_expired_order_inspections() -> int:
    """يمسح لقطات الفحص التي مضى عليها أسبوع (دفعة محدودة)."""
    try:
        with db_conn() as c:
            c.execute(
                """
                DELETE FROM order_inspect_snapshots
                WHERE order_id IN (
                    SELECT order_id FROM order_inspect_snapshots
                    WHERE created_at < NOW() - (%s * INTERVAL '1 day')
                    ORDER BY created_at
                    LIMIT %s
                )
                """,
                (ORDER_INSPECT_RETENTION_DAYS, ORDER_INSPECT_PURGE_BATCH),
            )
            return int(c.rowcount or 0)
    except Exception:
        logger.exception("order_inspect: فشل مسح اللقطات المنتهية")
        return 0


def _oi_user_brief(user_id):
    row = _oi_query(
        "SELECT user_id, username, full_name, joined_at, invited_by, referral_credited "
        "FROM users WHERE user_id=%s",
        (int(user_id),),
        one=True,
    )
    return row or {"user_id": int(user_id), "username": None, "full_name": None}


def _oi_referral_chain(source_id, owner_id, max_hops=8):
    """سلسلة الدعوة من المحال الجديد وصولاً إلى صاحب الطلب."""
    chain, seen, current = [], {int(source_id)}, int(source_id)
    for _ in range(max_hops):
        row = _oi_user_brief(current)
        chain.append({
            "id": int(row.get("user_id") or current),
            "name": row.get("full_name"),
            "username": row.get("username"),
        })
        parent = int(row.get("invited_by") or 0)
        if not parent or parent in seen or current == int(owner_id):
            break
        seen.add(parent)
        current = parent
    return chain


def _oi_ts_value(ts) -> float:
    try:
        return float(ts.timestamp())
    except (AttributeError, OverflowError, OSError, ValueError):
        return 0.0


def _oi_collect_events(user_id):
    """يدمج سجل الجواهر مع التحويلات وشراء النجوم (لا يُسجَّلان في jewel_transactions)."""
    events = []
    for row in _oi_query(
        "SELECT id, amount, transaction_type, admin_id, reference, created_at "
        "FROM jewel_transactions WHERE user_id=%s ORDER BY created_at, id LIMIT %s",
        (int(user_id), ORDER_INSPECT_MAX_EVENTS),
    ):
        events.append({
            "key": ("ledger", int(row["id"])), "origin": "ledger",
            "amount": row["amount"], "tx_type": row["transaction_type"],
            "reference": row["reference"], "admin_id": row["admin_id"],
            "ts": row["created_at"], "rank": 0, "id": int(row["id"]),
        })
    for row in _oi_query(
        "SELECT id, request_id, direction, jewels_amount, points_amount, rate, created_at "
        "FROM currency_exchange_transactions WHERE user_id=%s AND status='completed' "
        "ORDER BY created_at, id LIMIT %s",
        (int(user_id), ORDER_INSPECT_MAX_EVENTS),
    ):
        sign = 1 if row["direction"] == "points_to_jewels" else -1
        events.append({
            "key": ("exchange", int(row["id"])), "origin": "exchange",
            "amount": sign * oi_to_decimal(row["jewels_amount"]),
            "tx_type": row["direction"], "reference": row["request_id"],
            "points": row["points_amount"], "rate": row["rate"],
            "ts": row["created_at"], "rank": 1, "id": int(row["id"]),
        })
    for row in _oi_query(
        "SELECT id, stars, jewels_given, telegram_payment_id, created_at "
        "FROM jewel_star_transactions WHERE user_id=%s AND status='completed' "
        "ORDER BY created_at, id LIMIT %s",
        (int(user_id), ORDER_INSPECT_MAX_EVENTS),
    ):
        events.append({
            "key": ("stars", int(row["id"])), "origin": "stars",
            "amount": oi_to_decimal(row["jewels_given"]),
            "tx_type": "star_purchase", "reference": row["telegram_payment_id"],
            "stars": row["stars"],
            "ts": row["created_at"], "rank": 2, "id": int(row["id"]),
        })
    events.sort(key=lambda e: (_oi_ts_value(e["ts"]), e["rank"], e["id"]))
    return events


def _oi_describe_lot(lot, consumed):
    """يحوّل رصيداً مستهلكاً إلى وصف جاهز للعرض (يُجمَّد داخل اللقطة)."""
    kind = oi_classify_source(
        lot.get("tx_type"), lot.get("reference"), lot.get("admin_id"), lot.get("origin", "ledger")
    )
    item = {
        "kind": kind,
        "amount": str(consumed),
        "when": str(lot.get("ts") or ""),
        "reference": str(lot.get("reference") or ""),
    }
    if kind == "referral":
        parsed = oi_parse_referral_reference(lot.get("reference"))
        if parsed:
            level, source_id = parsed
            item["level"] = level
            item["chain"] = _oi_referral_chain(source_id, lot.get("owner_id") or 0)
            brief = _oi_user_brief(source_id)
            item["person"] = {
                "id": source_id,
                "name": brief.get("full_name"),
                "username": brief.get("username"),
                "joined_at": str(brief.get("joined_at") or ""),
            }
    elif kind == "exchange":
        item["points"] = int(lot.get("points") or 0)
        item["rate"] = int(lot.get("rate") or 0)
    elif kind == "star_purchase":
        item["stars"] = int(lot.get("stars") or 0)
    elif kind == "admin_gift":
        item["admin_id"] = lot.get("admin_id")
    elif kind == "order_refund":
        match = re.match(r"^smm_refund:(\d+)$", item["reference"])
        if match:
            row = _oi_query(
                "SELECT order_code FROM orders WHERE id=%s", (int(match.group(1)),), one=True
            )
            item["refund_of_order"] = (row or {}).get("order_code")
    return item


def oi_compute_jewel_sources(user_id, intent_id):
    """مصدر الجواهر التي دُفع بها الطلب (الأقدم أولاً) مع تفاصيل كل مصدر."""
    if not intent_id:
        return None
    events = _oi_collect_events(user_id)
    target = None
    for event in events:
        if event["origin"] == "ledger" and event["reference"] == f"smm_intent:{int(intent_id)}":
            target = event["key"]
            break
    if target is None:
        return None
    for event in events:
        event["owner_id"] = int(user_id)
    consumed, unrecorded = oi_simulate_fifo(events, target)
    grouped = {}
    for lot, amount in consumed:
        slot = grouped.setdefault(lot["key"], [lot, Decimal(0)])
        slot[1] += amount
    sources = [_oi_describe_lot(lot, amount) for lot, amount in grouped.values()]
    if unrecorded > 0:
        sources.append({"kind": "unrecorded", "amount": str(unrecorded), "when": "", "reference": ""})
    return sources


def _oi_collect_person(user_id):
    uid = int(user_id)
    person = {"row": None, "inviter": None}
    row = _oi_query("SELECT * FROM users WHERE user_id=%s", (uid,), one=True)
    if row:
        person["row"] = {key: (None if value is None else str(value)) for key, value in row.items()}
        inviter_id = int(row.get("invited_by") or 0)
        if inviter_id:
            person["inviter"] = _oi_user_brief(inviter_id)
    refs = _oi_query(
        "SELECT COUNT(*) AS total, "
        "COALESCE(SUM(CASE WHEN referral_credited=1 THEN 1 ELSE 0 END),0) AS credited "
        "FROM users WHERE invited_by=%s",
        (uid,),
        one=True,
    ) or {}
    person["referrals_total"] = int(refs.get("total") or 0)
    person["referrals_credited"] = int(refs.get("credited") or 0)
    person["orders_summary"] = _oi_query(
        "SELECT COUNT(*) AS cnt, COALESCE(SUM(cost_stars),0) AS stars, "
        "COALESCE(SUM(cost_jewels),0) AS jewels, "
        "COALESCE(SUM(CASE WHEN payment_method='free' THEN 1 ELSE 0 END),0) AS free_cnt "
        "FROM orders WHERE user_id=%s",
        (uid,),
        one=True,
    ) or {}
    person["recent_orders"] = _oi_query(
        "SELECT o.order_code, o.status, o.payment_method, o.created_at, s.name_ar "
        "FROM orders o LEFT JOIN services s ON s.id=o.service_id "
        "WHERE o.user_id=%s ORDER BY o.id DESC LIMIT 5",
        (uid,),
    )
    person["ledger"] = _oi_query(
        "SELECT transaction_type, COUNT(*) AS cnt, COALESCE(SUM(amount),0) AS total "
        "FROM jewel_transactions WHERE user_id=%s GROUP BY transaction_type ORDER BY transaction_type",
        (uid,),
    )
    person["exchanges"] = _oi_query(
        "SELECT direction, COUNT(*) AS cnt, COALESCE(SUM(jewels_amount),0) AS jewels, "
        "COALESCE(SUM(points_amount),0) AS points "
        "FROM currency_exchange_transactions WHERE user_id=%s AND status='completed' GROUP BY direction",
        (uid,),
    )
    person["star_purchases"] = _oi_query(
        "SELECT COUNT(*) AS cnt, COALESCE(SUM(stars),0) AS stars, COALESCE(SUM(jewels_given),0) AS jewels "
        "FROM jewel_star_transactions WHERE user_id=%s AND status='completed'",
        (uid,),
        one=True,
    ) or {}
    sent = _oi_query(
        "SELECT COUNT(*) AS cnt, COALESCE(SUM(points),0) AS pts FROM point_transfers WHERE from_user=%s",
        (uid,), one=True) or {}
    received = _oi_query(
        "SELECT COUNT(*) AS cnt, COALESCE(SUM(points),0) AS pts FROM point_transfers WHERE to_user=%s",
        (uid,), one=True) or {}
    person["transfers"] = {"sent": sent, "received": received}
    counts = {}
    for label, sql in (
        ("gmail", "SELECT COUNT(*) AS n FROM gmail_submissions WHERE user_id=%s"),
        ("buyback", "SELECT COUNT(*) AS n FROM account_buyback_offers WHERE seller_user_id=%s"),
        ("tg_numbers", "SELECT COUNT(*) AS n FROM tg_number_orders WHERE user_id=%s"),
        ("raksh", "SELECT COUNT(*) AS n FROM raksh_orders WHERE user_id=%s"),
        ("forced_ref", "SELECT COUNT(*) AS n FROM forced_ref_orders WHERE user_id=%s"),
        ("prizes", "SELECT COUNT(*) AS n FROM prize_exchanges WHERE user_id=%s"),
        ("promo_uses", "SELECT COUNT(*) AS n FROM promo_uses WHERE user_id=%s"),
    ):
        counts[label] = int((_oi_query(sql, (uid,), one=True) or {}).get("n") or 0)
    person["counts"] = counts
    return person


def oi_capture_order(order_id, order_code=None, use_order_time=False):
    """يبني لقطة الفحص ويحفظها. تُستدعى بعد إنشاء الطلب أو عند أول فحص لطلب قديم.

    use_order_time=True يحسب مهلة الأسبوع من وقت إنشاء الطلب نفسه (لا من وقت الفحص).
    """
    order = _oi_query(
        "SELECT o.*, s.name_ar AS s_name_ar, s.category AS s_category "
        "FROM orders o LEFT JOIN services s ON s.id=o.service_id WHERE o.id=%s",
        (int(order_id),),
        one=True,
    )
    if not order:
        return None
    code = str(order.get("order_code") or order_code or "")
    user_id = int(order.get("user_id") or 0)
    service = _oi_query("SELECT * FROM services WHERE id=%s", (order.get("service_id"),), one=True)
    intent = _oi_query(
        "SELECT * FROM smm_payment_intents WHERE order_code=%s ORDER BY id DESC LIMIT 1",
        (code,),
        one=True,
    )
    person = _oi_collect_person(user_id)
    sources = None
    if str(order.get("payment_method") or "") == "jewels" and intent:
        try:
            sources = oi_compute_jewel_sources(user_id, intent.get("id"))
        except Exception:
            logger.exception("order_inspect: تعذر حساب مصدر الجواهر")
    data = {
        "order": {k: (None if v is None else str(v)) for k, v in order.items()},
        "service": {k: (None if v is None else str(v)) for k, v in (service or {}).items()},
        "intent": {k: (None if v is None else str(v)) for k, v in (intent or {}).items()},
        "person": person,
        "sources": sources,
    }
    payload = json.dumps(data, ensure_ascii=False, default=str)
    base_params = (int(order_id), code, oi_normalize_code(code), user_id, payload)
    inserted = False
    if use_order_time and order.get("created_at"):
        try:
            with db_conn() as c:
                c.execute(
                    """
                    INSERT INTO order_inspect_snapshots
                        (order_id, order_code, order_code_norm, user_id, data, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s::timestamptz)
                    ON CONFLICT (order_id) DO UPDATE
                       SET data=EXCLUDED.data, order_code=EXCLUDED.order_code,
                           order_code_norm=EXCLUDED.order_code_norm
                    """,
                    base_params + (str(order["created_at"]),),
                )
            inserted = True
        except Exception:
            logger.warning("order_inspect: تعذر قراءة وقت الطلب، سيُستخدم الوقت الحالي")
    if not inserted:
        with db_conn() as c:
            c.execute(
                """
                INSERT INTO order_inspect_snapshots
                    (order_id, order_code, order_code_norm, user_id, data)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (order_id) DO UPDATE
                   SET data=EXCLUDED.data, order_code=EXCLUDED.order_code,
                       order_code_norm=EXCLUDED.order_code_norm
                """,
                base_params,
            )
    return data


def oi_capture_order_safely(order_id, order_code=None):
    """نسخة لا ترفع استثناءً أبداً: فشل الفحص يجب ألا يعطّل تسليم الطلب."""
    try:
        data = oi_capture_order(order_id, order_code)
        purge_expired_order_inspections()
        return data
    except Exception:
        logger.exception("order_inspect: فشل حفظ لقطة الطلب %s", order_id)
        return None


def _oi_load_snapshot(order_id):
    row = _oi_query(
        "SELECT order_id, data, created_at FROM order_inspect_snapshots "
        "WHERE order_id=%s AND created_at >= NOW() - (%s * INTERVAL '1 day')",
        (int(order_id), ORDER_INSPECT_RETENTION_DAYS),
        one=True,
    )
    if not row:
        return None
    try:
        return json.loads(row["data"])
    except (TypeError, ValueError):
        return None


def _oi_get_or_build(order_id, order_code=None):
    """اللقطة المحفوظة، أو يبنيها لطلب سابق لتفعيل الميزة إن كان ضمن مهلة الأسبوع."""
    data = _oi_load_snapshot(order_id)
    if data is not None:
        return data
    try:
        oi_capture_order(order_id, order_code, use_order_time=True)
    except Exception:
        logger.exception("order_inspect: تعذر بناء لقطة الطلب %s", order_id)
        return None
    return _oi_load_snapshot(order_id)


def oi_find_orders(raw_code):
    """يعيد الطلبات المطابقة (ضمن آخر أسبوع فقط)، الأدق تطابقاً أولاً."""
    exact = oi_clean_code(raw_code)
    norm = oi_normalize_code(raw_code)
    if not norm:
        return []
    purge_expired_order_inspections()
    rows = _oi_query(
        """
        SELECT s.order_id AS id, s.order_code, s.user_id
        FROM order_inspect_snapshots s
        WHERE (s.order_code_norm=%s OR UPPER(s.order_code)=%s)
          AND s.created_at >= NOW() - (%s * INTERVAL '1 day')
        ORDER BY (UPPER(s.order_code)=%s) DESC, s.order_id DESC
        LIMIT 10
        """,
        (norm, exact, ORDER_INSPECT_RETENTION_DAYS, exact),
    )
    if not rows:
        # طلبات أُنشئت قبل تفعيل الميزة: نفحص آخر الطلبات ونبني لها لقطة عند الحاجة.
        rows = _oi_query(
            """
            SELECT o.id, o.order_code, o.user_id
            FROM (SELECT * FROM orders ORDER BY id DESC LIMIT %s) o
            WHERE (UPPER(o.order_code)=%s
                   OR UPPER(regexp_replace(COALESCE(o.order_code,''), '[^0-9A-Za-z]', '', 'g'))=%s)
              AND o.created_at::timestamptz >= NOW() - (%s * INTERVAL '1 day')
            ORDER BY (UPPER(o.order_code)=%s) DESC, o.id DESC
            LIMIT 10
            """,
            (ORDER_INSPECT_FALLBACK_SCAN, exact, norm, ORDER_INSPECT_RETENTION_DAYS, exact),
        )
    results = []
    for row in rows:
        data = _oi_get_or_build(row["id"], row["order_code"])
        if data:
            results.append({"order_id": int(row["id"]), "data": data})
    return results


# ───────────────────────── العرض ─────────────────────────

def _oi_status_label(value) -> str:
    raw = str(value or "").strip()
    return _OI_STATUS_AR.get(raw.lower(), raw or "—")


def _oi_pay_text(order) -> str:
    method = str(order.get("payment_method") or "points")
    if method == "stars":
        return f"{oi_fmt_amount(order.get('cost_stars'))} نجمة ⭐"
    if method == "jewels":
        return f"{oi_fmt_amount(order.get('cost_jewels'))} جوهرة 💎"
    if method == "free":
        return "مجاناً"
    return f"{oi_fmt_amount(order.get('cost_points'))} نقطة"


def oi_render_card(data) -> str:
    order, person = data.get("order") or {}, data.get("person") or {}
    row = person.get("row") or {}
    service = data.get("service") or {}
    return (
        "🔎 <b>فحص الطلب</b>\n\n"
        f"👤 الطالب: {_oi_user_line(row.get('full_name'), row.get('username'), order.get('user_id'))}\n"
        f"📌 الكود: <code>{_oi_e(order.get('order_code'))}</code>\n"
        f"🛍 الخدمة: {_oi_e(order.get('s_name_ar') or service.get('name_ar'))}\n"
        f"📊 الحالة: {_oi_e(_oi_status_label(order.get('status')))}\n"
        f"🕒 التاريخ: {_oi_e(order.get('created_at'))}\n\n"
        f"<i>تُمسح معلومات الفحص تلقائياً بعد {ORDER_INSPECT_RETENTION_DAYS} أيام.</i>"
    )


def oi_card_kb(order_id):
    oid = int(order_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 معلومات الطلب بالموقع", callback_data=f"os:oi:site:{oid}")],
        [InlineKeyboardButton("🛠 معلومات الخدمة في البوت", callback_data=f"os:oi:svc:{oid}")],
        [InlineKeyboardButton("👤 معلومات الشخص كاملة", callback_data=f"os:oi:usr:{oid}")],
        [InlineKeyboardButton("💎 مصدر الجواهر", callback_data=f"os:oi:src:{oid}")],
        [InlineKeyboardButton("🔍 فحص طلب آخر", callback_data="os:oi:ask")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
    ])


def _oi_sub_kb(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع للطلب", callback_data=f"os:oi:card:{int(order_id)}")],
        [InlineKeyboardButton("🔍 فحص طلب آخر", callback_data="os:oi:ask")],
    ])


def oi_render_site(data, live=None) -> str:
    order, intent = data.get("order") or {}, data.get("intent") or {}
    service = data.get("service") or {}
    panel_no = int(service.get("panel") or 1) if str(service.get("panel") or "1").isdigit() else 1
    panel_name = (PANEL_MAP.get(panel_no) or PANEL_MAP.get(1) or {}).get("name", f"#{panel_no}")
    lines = [
        "📦 <b>معلومات الطلب بالموقع</b>",
        "",
        f"📌 كود الطلب: <code>{_oi_e(order.get('order_code'))}</code>",
        f"🌐 الموقع: {_oi_e(panel_name)} (رقم {panel_no})",
        f"🆔 رقم الطلب لدى الموقع: <code>{_oi_e(order.get('api_order_id'))}</code>",
        f"🔖 رقم الخدمة لدى الموقع: <code>{_oi_e(service.get('api_service_id') or intent.get('api_service_id'))}</code>",
        f"🔗 الرابط: {_oi_e(order.get('link'))}",
        f"🔢 الكمية المطلوبة: {_oi_e(order.get('quantity'))}",
        f"💳 الدفع: {_oi_e(_oi_pay_text(order))}",
        f"🏷 قيمة الخدمة (نقاط): {_oi_e(order.get('service_value_points'))}",
        f"💵 سعر الموقع للألف: {_oi_e(order.get('provider_rate_usd'))} $",
        f"💵 تكلفتنا لدى الموقع: {_oi_e(order.get('provider_cost_usd'))} $",
        f"📊 حالة الطلب المحفوظة: {_oi_e(_oi_status_label(order.get('status')))}",
        f"↩️ استرداد جزئي (نقاط): {_oi_e(order.get('partial_refund_pts'))}",
        f"↩️ استرداد نقاط: {_oi_e(order.get('refund_points'))}",
        f"↩️ استرداد جواهر: {_oi_e(order.get('refund_jewels'))}",
        f"🕒 وقت الإنشاء: {_oi_e(order.get('created_at'))}",
    ]
    if order.get("telegram_payment_id"):
        lines.append(f"🧾 معرّف دفعة تيليجرام: <code>{_oi_e(order.get('telegram_payment_id'))}</code>")
    if intent:
        lines += [
            "",
            "🧾 <b>طلب الدفع (النية)</b>",
            f"• رقمها: {_oi_e(intent.get('id'))} — حالتها: {_oi_e(intent.get('status'))}",
            f"• طريقة الدفع: {_oi_e(intent.get('payment_method'))}",
            f"• آخر خطأ: {_oi_e(intent.get('last_error'))}",
            f"• أُنشئت: {_oi_e(intent.get('created_at'))} — حُدّثت: {_oi_e(intent.get('updated_at'))}",
        ]
    lines.append("")
    if live is None:
        lines.append("🌐 <b>الحالة المباشرة من الموقع:</b> غير متاحة (لا يوجد رقم طلب لدى الموقع).")
    elif live.get("error"):
        lines.append(f"🌐 <b>الحالة المباشرة من الموقع:</b> تعذر الجلب — {_oi_e(live.get('error'))}")
    else:
        lines.append("🌐 <b>الحالة المباشرة من الموقع (الآن):</b>")
        for key, label in (
            ("status", "الحالة"), ("start_count", "العدد عند البدء"), ("remains", "المتبقي"),
            ("charge", "المبلغ المخصوم من رصيدنا"), ("currency", "العملة"),
        ):
            if key in live:
                lines.append(f"• {label}: {_oi_e(live.get(key))}")
        extra = [k for k in live if k not in {"status", "start_count", "remains", "charge", "currency"}]
        for key in extra:
            lines.append(f"• {_oi_e(key)}: {_oi_e(live.get(key))}")
    return "\n".join(lines)


def oi_render_service(data) -> str:
    service = data.get("service") or {}
    if not service:
        return "🛠 <b>معلومات الخدمة في البوت</b>\n\n⚠️ الخدمة محذوفة من البوت أو غير موجودة."
    labels = {
        "id": "🆔 رقم الخدمة في البوت", "category": "📂 القسم", "api_service_id": "🔖 رقم الخدمة لدى الموقع",
        "panel": "🌐 رقم الموقع", "name_ar": "🏷 الاسم", "min_qty": "⬇️ أقل كمية", "max_qty": "⬆️ أكبر كمية",
        "price_per_point": "💰 السعر لكل نقطة", "active": "✅ فعّالة", "service_type": "🧩 النوع",
    }
    lines = ["🛠 <b>معلومات الخدمة في البوت</b> (كما كانت وقت الطلب)", ""]
    for key, value in service.items():
        if key == "description":
            continue
        lines.append(f"{labels.get(key, '▫️ ' + key)}: {_oi_e(value)}")
    description = str(service.get("description") or "").strip()
    if description:
        lines += ["", "📝 <b>الوصف:</b>", _oi_e(description)]
    order = data.get("order") or {}
    lines += [
        "",
        "💳 <b>تسعير هذا الطلب</b>",
        f"• قيمة الخدمة (نقاط): {_oi_e(order.get('service_value_points'))}",
        f"• المدفوع: {_oi_e(_oi_pay_text(order))}",
        f"• الكمية: {_oi_e(order.get('quantity'))}",
    ]
    return "\n".join(lines)


def oi_render_person(data, live=None) -> str:
    person = data.get("person") or {}
    row = person.get("row") or {}
    if not row:
        return "👤 <b>معلومات الشخص</b>\n\n⚠️ لم يعد العضو موجوداً في قاعدة البيانات."
    lines = ["👤 <b>معلومات الشخص كاملة</b> (وقت الطلب)", ""]
    for key, value in row.items():
        lines.append(f"{_OI_USER_LABELS.get(key, '▫️ ' + key)}: {_oi_e(value)}")
    if live:
        lines += [
            "",
            "🔄 <b>حالته الآن:</b>",
            f"• النقاط: {_oi_e(live.get('points'))} — الجواهر: {_oi_e(live.get('jewels'))} "
            f"(منها إحالة: {_oi_e(live.get('referral_jewels'))})",
            f"• محظور: {_oi_e(live.get('banned'))}",
        ]
    inviter = person.get("inviter")
    lines += ["", "👥 <b>الإحالات</b>"]
    if inviter:
        lines.append(f"• دعاه: {_oi_user_line(inviter.get('full_name'), inviter.get('username'), inviter.get('user_id'))}")
    else:
        lines.append("• لم يدخل عبر إحالة.")
    lines.append(
        f"• عدد من دعاهم: {person.get('referrals_total', 0)} "
        f"(المحتسبة: {person.get('referrals_credited', 0)})"
    )
    summary = person.get("orders_summary") or {}
    lines += [
        "",
        "📦 <b>طلبات الخدمات</b>",
        f"• العدد: {oi_fmt_amount(summary.get('cnt'))} — مجانية: {oi_fmt_amount(summary.get('free_cnt'))}",
        f"• مجموع ما دفعه: {oi_fmt_amount(summary.get('stars'))} نجمة، {oi_fmt_amount(summary.get('jewels'))} جوهرة",
    ]
    for item in person.get("recent_orders") or []:
        lines.append(
            f"  – <code>{_oi_e(item.get('order_code'))}</code> | {_oi_e(item.get('name_ar'))} | "
            f"{_oi_e(_oi_status_label(item.get('status')))} | {_oi_e(item.get('payment_method'))}"
        )
    ledger = person.get("ledger") or []
    if ledger:
        lines += ["", "💎 <b>حركات الجواهر حسب النوع</b>"]
        for item in ledger:
            lines.append(
                f"• {_oi_e(item.get('transaction_type'))}: {oi_fmt_amount(item.get('cnt'))} حركة، "
                f"المجموع {oi_fmt_amount(item.get('total'))}"
            )
    for item in person.get("exchanges") or []:
        way = "نقاط ← جواهر" if item.get("direction") == "points_to_jewels" else "جواهر ← نقاط"
        lines.append(
            f"🔁 تحويل {way}: {oi_fmt_amount(item.get('cnt'))} مرة "
            f"({oi_fmt_amount(item.get('points'))} نقطة / {oi_fmt_amount(item.get('jewels'))} جوهرة)"
        )
    stars = person.get("star_purchases") or {}
    if int(stars.get("cnt") or 0):
        lines.append(
            f"⭐ شراء جواهر بالنجوم: {oi_fmt_amount(stars.get('cnt'))} مرة "
            f"({oi_fmt_amount(stars.get('stars'))} نجمة ← {oi_fmt_amount(stars.get('jewels'))} جوهرة)"
        )
    transfers = person.get("transfers") or {}
    sent, received = transfers.get("sent") or {}, transfers.get("received") or {}
    lines += [
        "",
        "🔄 <b>تحويل النقاط بين الأعضاء</b>",
        f"• أرسل: {oi_fmt_amount(sent.get('cnt'))} مرة ({oi_fmt_amount(sent.get('pts'))} نقطة)",
        f"• استلم: {oi_fmt_amount(received.get('cnt'))} مرة ({oi_fmt_amount(received.get('pts'))} نقطة)",
    ]
    counts = person.get("counts") or {}
    names = {
        "raksh": "طلبات الرشق", "forced_ref": "طلبات الإحالة الإجبارية", "tg_numbers": "طلبات أرقام تيليجرام",
        "buyback": "عروض بيع الحسابات", "gmail": "تسليمات جيميل", "prizes": "استبدال الجوائز",
        "promo_uses": "استخدام أكواد ترويجية",
    }
    lines += ["", "🧩 <b>نشاطات أخرى</b>"]
    for key, label in names.items():
        lines.append(f"• {label}: {counts.get(key, 0)}")
    return "\n".join(lines)


def oi_render_sources(data) -> str:
    order = data.get("order") or {}
    method = str(order.get("payment_method") or "points")
    lines = ["💎 <b>مصدر الجواهر</b>", "", f"💳 طريقة الدفع: {_oi_e(_oi_pay_text(order))}"]
    if method == "stars":
        lines += [
            "",
            "⭐ الطلب دُفع بنجوم تيليجرام مباشرة، فلا توجد جواهر لتتبّع مصدرها.",
            f"🧾 معرّف الدفعة: <code>{_oi_e(order.get('telegram_payment_id'))}</code>",
        ]
        return "\n".join(lines)
    if method != "jewels":
        lines += ["", "ℹ️ لم يُدفع هذا الطلب بالجواهر، فلا يوجد مصدر جواهر."]
        return "\n".join(lines)
    sources = data.get("sources")
    if not sources:
        lines += ["", "⚠️ تعذر تحديد المصدر (لم يُعثر على حركة الخصم في السجل)."]
        return "\n".join(lines)
    totals = {}
    for item in sources:
        totals[item["kind"]] = totals.get(item["kind"], Decimal(0)) + oi_to_decimal(item["amount"])
    lines += ["", "📊 <b>الملخص:</b>"]
    for kind, total in totals.items():
        lines.append(f"• {_OI_KIND_TITLES.get(kind, kind)}: {oi_fmt_amount(total)} 💎")
    lines.append("")
    lines.append("<i>التتبع بنظام «الأقدم أولاً»: يُعدّ الصرف من أقدم رصيد دخل المحفظة.</i>")
    shown_persons = 0
    for item in sources:
        kind = item["kind"]
        lines += ["", f"━━━━━━━━━━", f"{_OI_KIND_TITLES.get(kind, kind)} — <b>{oi_fmt_amount(item['amount'])} 💎</b>"]
        if item.get("when"):
            lines.append(f"🕒 دخل المحفظة: {_oi_e(item['when'])}")
        if kind == "referral":
            person = item.get("person")
            if person:
                if shown_persons >= ORDER_INSPECT_MAX_PERSONS:
                    lines.append("… (اختُصرت بقية الأسماء)")
                    continue
                shown_persons += 1
                lines.append(f"المستوى: {item.get('level')}")
                lines.append(f"👤 المحال: {_oi_user_line(person.get('name'), person.get('username'), person.get('id'))}")
                if person.get("joined_at"):
                    lines.append(f"📅 انضمامه: {_oi_e(person['joined_at'])}")
                chain = item.get("chain") or []
                if len(chain) > 1:
                    path = " ← ".join(
                        f"{_oi_e(n.get('name') or n.get('id'))}" for n in chain
                    )
                    lines.append(f"🔗 سلسلة الدعوة: {path}")
            else:
                lines.append(f"المرجع: <code>{_oi_e(item.get('reference'))}</code>")
        elif kind == "exchange":
            lines.append(
                f"كيف حصل: حوّل <b>{oi_fmt_amount(item.get('points'))}</b> نقطة إلى جواهر "
                f"بسعر {oi_fmt_amount(item.get('rate'))} نقطة للجوهرة."
            )
            lines.append(f"🧾 رقم العملية: <code>{_oi_e(item.get('reference'))}</code>")
        elif kind == "star_purchase":
            lines.append(f"كيف حصل: اشترى جواهر بـ <b>{oi_fmt_amount(item.get('stars'))}</b> نجمة.")
            lines.append(f"🧾 معرّف الدفعة: <code>{_oi_e(item.get('reference'))}</code>")
        elif kind == "admin_gift":
            lines.append(f"أضافها: <code>{_oi_e(item.get('admin_id'))}</code>")
            if item.get("reference"):
                lines.append(f"السبب: {_oi_e(item['reference'])}")
        elif kind == "order_refund":
            lines.append(f"من استرداد الطلب: <code>{_oi_e(item.get('refund_of_order') or item.get('reference'))}</code>")
        elif kind == "unrecorded":
            lines.append("رصيد لا أثر له في سجل الحركات (غالباً رصيد قديم أو تعديل مباشر).")
        else:
            lines.append(f"المرجع: <code>{_oi_e(item.get('reference'))}</code>")
    return "\n".join(lines)


# ───────────────────────── المعالجات ─────────────────────────

async def _oi_show(q_or_message, text, kb, edit=True):
    """يعرض النص مقسّماً عند الحاجة؛ لوحة الأزرار تكون تحت آخر جزء."""
    chunks = oi_split_message(text)
    for index, chunk in enumerate(chunks):
        last = index == len(chunks) - 1
        markup = kb if last else None
        if index == 0 and edit:
            try:
                await q_or_message.edit_message_text(
                    chunk, parse_mode=ParseMode.HTML, reply_markup=markup,
                    disable_web_page_preview=True,
                )
                continue
            except Exception:
                logger.warning("order_inspect: تعذر تعديل الرسالة، سيُرسل جزء جديد")
            target = q_or_message.message
        elif edit:
            target = q_or_message.message
        else:
            target = q_or_message
        await target.reply_text(
            chunk, parse_mode=ParseMode.HTML, reply_markup=markup,
            disable_web_page_preview=True,
        )


def _oi_prompt_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")]])


async def _oi_live_panel_status(data):
    order, service = data.get("order") or {}, data.get("service") or {}
    api_order_id = str(order.get("api_order_id") or "").strip()
    if not api_order_id:
        return None
    try:
        panel = int(service.get("panel") or 1)
    except (TypeError, ValueError):
        panel = 1
    try:
        result = await asyncio.to_thread(smm_order_status, api_order_id, panel=panel)
    except Exception as exc:
        return {"error": str(exc)[:200]}
    return result if isinstance(result, dict) else {"error": "رد غير متوقع من الموقع"}


async def handle_order_inspect_callback(update, context, q, data: str, user, is_owner: bool) -> bool:
    if not data.startswith("os:oi:"):
        return False
    if not is_owner:
        await q.answer("🚫 هذا القسم للمالك فقط.", show_alert=True)
        return True
    parts = data.split(":")
    action = parts[2] if len(parts) > 2 else ""

    if action == "ask":
        context.user_data["state"] = ORDER_INSPECT_STATE
        await _oi_show(
            q,
            "🔎 <b>فحص الطلب</b>\n\nأرسل كود الطلب، مثل <code>1-1-1</code> أو <code>111</code>.\n"
            f"<i>تتوفر معلومات الطلبات خلال آخر {ORDER_INSPECT_RETENTION_DAYS} أيام فقط.</i>",
            _oi_prompt_kb(),
        )
        return True

    if action not in {"card", "site", "svc", "usr", "src"} or len(parts) < 4 or not parts[3].isdigit():
        return True
    order_id = int(parts[3])
    snapshot = await asyncio.to_thread(_oi_get_or_build, order_id)
    if snapshot is None:
        context.user_data["state"] = ORDER_INSPECT_STATE
        await _oi_show(
            q,
            f"⌛ مضى أكثر من {ORDER_INSPECT_RETENTION_DAYS} أيام على هذا الطلب، فحُذفت معلومات الفحص.\n"
            "أرسل كود طلب آخر:",
            _oi_prompt_kb(),
        )
        return True

    if action == "card":
        await _oi_show(q, oi_render_card(snapshot), oi_card_kb(order_id))
    elif action == "site":
        live = await _oi_live_panel_status(snapshot)
        await _oi_show(q, oi_render_site(snapshot, live), _oi_sub_kb(order_id))
    elif action == "svc":
        await _oi_show(q, oi_render_service(snapshot), _oi_sub_kb(order_id))
    elif action == "usr":
        uid = int((snapshot.get("order") or {}).get("user_id") or 0)
        live_user = _oi_query(
            "SELECT points, jewels, referral_jewels, banned FROM users WHERE user_id=%s", (uid,), one=True
        )
        await _oi_show(q, oi_render_person(snapshot, live_user), _oi_sub_kb(order_id))
    elif action == "src":
        await _oi_show(q, oi_render_sources(snapshot), _oi_sub_kb(order_id))
    return True


async def handle_order_inspect_text(update, context, text: str) -> bool:
    user = update.effective_user
    if context.user_data.get("state") != ORDER_INSPECT_STATE:
        return False
    if user is None or user.id != OWNER_ID:
        return False
    message = update.message
    if not oi_normalize_code(text):
        await message.reply_text("⚠️ أرسل كود الطلب بصيغة صحيحة، مثل 1-1-1 أو 111.", reply_markup=_oi_prompt_kb())
        return True
    matches = await asyncio.to_thread(oi_find_orders, text)
    if not matches:
        await message.reply_text(
            "⚠️ لم أجد طلباً بهذا الكود.\n"
            f"قد يكون الكود غير صحيح، أو مضى عليه أكثر من {ORDER_INSPECT_RETENTION_DAYS} أيام "
            "فحُذفت معلوماته.\nأرسل كوداً آخر:",
            reply_markup=_oi_prompt_kb(),
        )
        return True
    if len(matches) == 1:
        context.user_data["state"] = "main_menu"
        found = matches[0]
        await _oi_show(message, oi_render_card(found["data"]), oi_card_kb(found["order_id"]), edit=False)
        return True
    rows = []
    for found in matches[:8]:
        order = found["data"].get("order") or {}
        row = (found["data"].get("person") or {}).get("row") or {}
        label = f"{order.get('order_code')} — {row.get('full_name') or order.get('user_id')}"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"os:oi:card:{found['order_id']}")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
    context.user_data["state"] = "main_menu"
    await message.reply_text(
        "🔎 يوجد أكثر من طلب بهذه الأرقام، اختر الطلب المقصود:",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return True
