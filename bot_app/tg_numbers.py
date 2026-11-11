"""أرقام تلي لكل دول العالم — كتالوج المورد TG-Lion مع الدفع بالنجوم أو الجواهر.

يعرض القسم الدول والأسعار نفسها المعروضة في البوت الأول (سعر المزوّد + الربح)،
ويحوّل السعر بالدولار إلى نجوم أو جواهر بحسب أسعار صرف يضبطها المالك.
لا يشتري البوت رقماً من المورد تلقائياً: بعد الدفع يصل العضو إشعار بالتواصل مع
المالك، ويصل المالك طلب في كروب الطلبات بزر «اكتمل الطلب».
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP

# ───────────────────────── الثوابت ─────────────────────────
TGNUM_API_URL = "https://TG-Lion.net/"
TGNUM_CACHE_TTL = 60
TGNUM_PAGE_SIZE = 14
TGNUM_QUOTE_TTL_SECONDS = 600

# نفس معادلة الربح في البوت الأول حتى تتطابق الأسعار تماماً.
TGNUM_FLAT_PROFIT_CENTS = 10               # سعر المزوّد 1$ أو أقل: +10 سنت
TGNUM_PERCENT_PROFIT_THRESHOLD_CENTS = 100  # أكثر من 1$: +10%
TGNUM_PERCENT_PROFIT = 10

DEFAULT_TGNUM_STARS_PER_USD = 100
DEFAULT_TGNUM_JEWELS_PER_USD = 100

TGNUM_VISIBLE_KEY = "tgnum_visible"
TGNUM_API_KEY_SETTING = "tgnum_api_key"
TGNUM_USER_ID_SETTING = "tgnum_user_id"
TGNUM_ORDERS_GROUP_SETTING = "tgnum_orders_group"
TGNUM_STARS_RATE_SETTING = "tgnum_stars_per_usd"
TGNUM_JEWELS_RATE_SETTING = "tgnum_jewels_per_usd"

_TGNUM_CACHE = {"countries": None, "expires_at": 0.0}

_TGNUM_CALLING_CODES = {
    "AD": "376", "AE": "971", "AF": "93", "AG": "1268", "AI": "1264",
    "AL": "355", "AM": "374", "AO": "244", "AR": "54", "AS": "1684",
    "AT": "43", "AU": "61", "AW": "297", "AX": "358", "AZ": "994",
    "BA": "387", "BB": "1246", "BD": "880", "BE": "32", "BF": "226",
    "BG": "359", "BH": "973", "BI": "257", "BJ": "229", "BL": "590",
    "BM": "1441", "BN": "673", "BO": "591", "BQ": "599", "BR": "55",
    "BS": "1242", "BT": "975", "BW": "267", "BY": "375", "BZ": "501",
    "CA": "1", "CC": "61", "CD": "243", "CF": "236", "CG": "242",
    "CH": "41", "CI": "225", "CK": "682", "CL": "56", "CM": "237",
    "CN": "86", "CO": "57", "CR": "506", "CU": "53", "CV": "238",
    "CW": "599", "CX": "61", "CY": "357", "CZ": "420", "DE": "49",
    "DJ": "253", "DK": "45", "DM": "1767", "DO": "1809", "DZ": "213",
    "EC": "593", "EE": "372", "EG": "20", "ER": "291", "ES": "34",
    "ET": "251", "FI": "358", "FJ": "679", "FK": "500", "FM": "691",
    "FO": "298", "FR": "33", "GA": "241", "GB": "44", "GD": "1473",
    "GE": "995", "GF": "594", "GG": "44", "GH": "233", "GI": "350",
    "GL": "299", "GM": "220", "GN": "224", "GP": "590", "GQ": "240",
    "GR": "30", "GT": "502", "GU": "1671", "GW": "245", "GY": "592",
    "HK": "852", "HN": "504", "HR": "385", "HT": "509", "HU": "36",
    "ID": "62", "IE": "353", "IL": "972", "IM": "44", "IN": "91",
    "IO": "246", "IQ": "964", "IR": "98", "IS": "354", "IT": "39",
    "JE": "44", "JM": "1876", "JO": "962", "JP": "81", "KE": "254",
    "KG": "996", "KH": "855", "KI": "686", "KM": "269", "KN": "1869",
    "KP": "850", "KR": "82", "KW": "965", "KY": "1345", "KZ": "7",
    "LA": "856", "LB": "961", "LC": "1758", "LI": "423", "LK": "94",
    "LR": "231", "LS": "266", "LT": "370", "LU": "352", "LV": "371",
    "LY": "218", "MA": "212", "MC": "377", "MD": "373", "ME": "382",
    "MF": "590", "MG": "261", "MH": "692", "MK": "389", "ML": "223",
    "MM": "95", "MN": "976", "MO": "853", "MP": "1670", "MQ": "596",
    "MR": "222", "MS": "1664", "MT": "356", "MU": "230", "MV": "960",
    "MW": "265", "MX": "52", "MY": "60", "MZ": "258", "NA": "264",
    "NC": "687", "NE": "227", "NF": "672", "NG": "234", "NI": "505",
    "NL": "31", "NO": "47", "NP": "977", "NR": "674", "NU": "683",
    "NZ": "64", "OM": "968", "PA": "507", "PE": "51", "PF": "689",
    "PG": "675", "PH": "63", "PK": "92", "PL": "48", "PM": "508",
    "PR": "1787", "PS": "970", "PT": "351", "PW": "680", "PY": "595",
    "QA": "974", "RE": "262", "RO": "40", "RS": "381", "RU": "7",
    "RW": "250", "SA": "966", "SB": "677", "SC": "248", "SD": "249",
    "SE": "46", "SG": "65", "SH": "290", "SI": "386", "SK": "421",
    "SL": "232", "SM": "378", "SN": "221", "SO": "252", "SR": "597",
    "SS": "211", "ST": "239", "SV": "503", "SX": "1721", "SY": "963",
    "SZ": "268", "TC": "1649", "TD": "235", "TG": "228", "TH": "66",
    "TJ": "992", "TK": "690", "TL": "670", "TM": "993", "TN": "216",
    "TO": "676", "TR": "90", "TT": "1868", "TV": "688", "TW": "886",
    "TZ": "255", "UA": "380", "UG": "256", "US": "1", "UY": "598",
    "UZ": "998", "VA": "379", "VC": "1784", "VE": "58", "VG": "1284",
    "VI": "1340", "VN": "84", "VU": "678", "WF": "681", "WS": "685",
    "YE": "967", "YT": "262", "ZA": "27", "ZM": "260", "ZW": "263",
}


# ───────────────────────── دوال نقية ─────────────────────────
def tgnum_final_price_cents(base_price_cents: int) -> int:
    """سعر البيع = سعر المزوّد + الربح (مطابق للبوت الأول)."""
    base = int(base_price_cents)
    if base > TGNUM_PERCENT_PROFIT_THRESHOLD_CENTS:
        profit = (base * TGNUM_PERCENT_PROFIT + 50) // 100
        return base + profit
    return base + TGNUM_FLAT_PROFIT_CENTS


def tgnum_money_to_cents(value) -> int:
    try:
        amount = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError, ValueError):
        return 0
    if not amount.is_finite():
        return 0
    return int(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


def tgnum_units_cost(price_cents, units_per_usd) -> int:
    """يحوّل سعراً بالسنت إلى نجوم/جواهر (تقريب للأعلى، أدنى قيمة 1)."""
    try:
        cents = Decimal(int(price_cents))
        rate = Decimal(str(units_per_usd))
        if cents <= 0 or not rate.is_finite() or rate <= 0:
            return 0
        return max(1, int((cents * rate / 100).to_integral_value(rounding=ROUND_CEILING)))
    except (InvalidOperation, TypeError, ValueError):
        return 0


def tgnum_country_flag(country_code: str) -> str:
    code = str(country_code or "").upper()
    if len(code) != 2 or not all("A" <= letter <= "Z" for letter in code):
        return "🌐"
    return "".join(chr(ord(letter) + 127397) for letter in code)


def normalize_tgnum_calling_code(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[2:] if digits.startswith("00") else digits


def tgnum_parse_calling_code_query(text: str):
    """يقبل 964 أو +964 أو 00964 ويعيد الأرقام فقط، أو None إن لم تصح."""
    candidate = str(text or "").strip()
    for ch in (" ", "-", "(", ")"):
        candidate = candidate.replace(ch, "")
    if candidate.startswith("+"):
        candidate = candidate[1:]
    elif candidate.startswith("00"):
        candidate = candidate[2:]
    if not candidate.isascii() or not candidate.isdigit() or not 1 <= len(candidate) <= 4:
        return None
    return candidate


def tgnum_find_by_calling_code(countries, calling_code: str) -> list:
    normalized = normalize_tgnum_calling_code(calling_code)
    return [
        country for country in countries
        if normalize_tgnum_calling_code(
            country.get("calling_code")
            or _TGNUM_CALLING_CODES.get(str(country.get("code", "")).upper(), "")
        ) == normalized
    ]


def parse_tgnum_chat_ref(text: str):
    """يستخرج معرّف كروب قابلاً للاستخدام: رقم -100… أو @username أو رابط عام.

    الروابط الخاصة (t.me/+xxxx) لا تكفي لأن البوت يحتاج معرّف الكروب نفسه.
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    if re.fullmatch(r"-?\d{5,20}", raw):
        return raw
    match = re.fullmatch(r"@([A-Za-z][A-Za-z0-9_]{3,31})", raw)
    if match:
        return f"@{match.group(1)}"
    match = re.fullmatch(
        r"(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z][A-Za-z0-9_]{3,31})/?(?:\?.*)?",
        raw,
        re.IGNORECASE,
    )
    if match:
        return f"@{match.group(1)}"
    return None


def tgnum_mask_secret(value: str) -> str:
    value = str(value or "")
    if not value:
        return "غير مضبوط ❌"
    return f"محفوظ ✅ (…{value[-4:]})" if len(value) > 6 else "محفوظ ✅"


# ───────────────────────── الإعدادات ─────────────────────────
def is_tgnum_visible() -> bool:
    return str(get_setting(TGNUM_VISIBLE_KEY) or "1") == "1"


def tgnum_credentials() -> tuple:
    api_key = (get_setting(TGNUM_API_KEY_SETTING) or os.environ.get("TG_LION_API_KEY", "")).strip()
    your_id = (get_setting(TGNUM_USER_ID_SETTING) or os.environ.get("TG_LION_USER_ID", "")).strip()
    return api_key, your_id


def _tgnum_rate(key: str, default: int) -> Decimal:
    raw = str(get_setting(key) or "").strip()
    try:
        value = Decimal(raw)
        if value.is_finite() and value > 0:
            return value
    except (InvalidOperation, ValueError):
        pass
    return Decimal(default)


def tgnum_stars_rate() -> Decimal:
    return _tgnum_rate(TGNUM_STARS_RATE_SETTING, DEFAULT_TGNUM_STARS_PER_USD)


def tgnum_jewels_rate() -> Decimal:
    return _tgnum_rate(TGNUM_JEWELS_RATE_SETTING, DEFAULT_TGNUM_JEWELS_PER_USD)


def tgnum_price_options(price_cents: int) -> tuple:
    return (
        tgnum_units_cost(price_cents, tgnum_stars_rate()),
        tgnum_units_cost(price_cents, tgnum_jewels_rate()),
    )


def get_tgnum_orders_chat():
    raw = str(get_setting(TGNUM_ORDERS_GROUP_SETTING) or "").strip()
    if not raw:
        return None
    return int(raw) if re.fullmatch(r"-?\d+", raw) else raw


def _tgnum_reset_cache() -> None:
    _TGNUM_CACHE["countries"] = None
    _TGNUM_CACHE["expires_at"] = 0.0


# ───────────────────────── المورد TG-Lion ─────────────────────────
def _tgnum_fetch_countries_sync() -> tuple:
    api_key, your_id = tgnum_credentials()
    if not api_key or not your_id:
        return None, "not_configured"
    try:
        response = requests.get(
            TGNUM_API_URL,
            params={"action": "available_countries", "apiKey": api_key, "YourID": your_id},
            headers={"Accept": "application/json", "User-Agent": "strat-bot"},
            timeout=15,
        )
        raw_body = response.content
        if len(raw_body) > 1024 * 1024:
            return None, "invalid_response"
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        # لا نسجّل نص الاستثناء: قد يتضمن الرابط ومعه مفتاح API.
        logger.warning("TG-Lion country-list request failed (%s)", type(exc).__name__)
        return None, "provider_error"
    if not isinstance(payload, dict) or str(payload.get("status", "")).lower() != "ok":
        return None, "provider_error"
    raw_countries = payload.get("countries")
    if isinstance(raw_countries, dict):
        entries = raw_countries.items()
    elif isinstance(raw_countries, list):
        entries = [(item.get("code", ""), item) for item in raw_countries if isinstance(item, dict)]
    else:
        return None, "invalid_response"
    countries = []
    seen_codes = set()
    for fallback_code, item in entries:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or fallback_code or "").strip().upper()
        if not code or len(code) > 12 or code in seen_codes:
            continue
        try:
            source_price = Decimal(str(item.get("price")))
            if not source_price.is_finite() or source_price < 0:
                continue
            base_price_cents = tgnum_money_to_cents(source_price)
            quantity = int(item.get("qty", 0))
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            continue
        if quantity <= 0:
            continue
        name = str(item.get("name") or code).strip()[:120]
        raw_calling_code = next(
            (item.get(key) for key in (
                "calling_code", "callingCode", "dial_code", "dialCode",
                "phone_code", "phoneCode", "prefix",
            ) if item.get(key)),
            _TGNUM_CALLING_CODES.get(code, ""),
        )
        countries.append({
            "code": code,
            "name": name,
            "flag": str(item.get("flag") or tgnum_country_flag(code)),
            "calling_code": normalize_tgnum_calling_code(raw_calling_code),
            "qty": quantity,
            "base_price_cents": base_price_cents,
            "price_cents": tgnum_final_price_cents(base_price_cents),
        })
        seen_codes.add(code)
    return countries, "ok"


async def get_tgnum_countries(force_refresh: bool = False) -> tuple:
    now = time.monotonic()
    cached = _TGNUM_CACHE.get("countries")
    if not force_refresh and cached is not None and now < _TGNUM_CACHE.get("expires_at", 0.0):
        return cached, "ok"
    countries, status = await asyncio.to_thread(_tgnum_fetch_countries_sync)
    if status == "ok" and countries is not None:
        _TGNUM_CACHE["countries"] = countries
        _TGNUM_CACHE["expires_at"] = time.monotonic() + TGNUM_CACHE_TTL
    return countries, status


# ───────────────────────── قاعدة البيانات ─────────────────────────
def get_tgnum_order(order_id: int):
    with db_conn() as c:
        row = c.execute("SELECT * FROM tg_number_orders WHERE id=%s", (int(order_id),)).fetchone()
    return dict(row) if row else None


def create_tgnum_stars_order(user, country: dict, stars: int) -> dict:
    """ينشئ طلباً بانتظار الدفع بالنجوم ويلغي أي فاتورة قديمة غير مدفوعة للعضو."""
    with db_conn() as c:
        c.execute(
            """
            UPDATE tg_number_orders SET status='cancelled', updated_at=NOW()
            WHERE user_id=%s AND status='awaiting_payment' AND telegram_payment_id IS NULL
            """,
            (user.id,),
        )
        row = c.execute(
            """
            INSERT INTO tg_number_orders
                (user_id, user_name, user_username, country_code, country_name,
                 base_price_cents, price_cents, payment_method, amount, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'stars',%s,'awaiting_payment')
            RETURNING *
            """,
            (
                user.id, user.full_name or "", user.username or "",
                country["code"], country["name"],
                int(country["base_price_cents"]), int(country["price_cents"]), int(stars),
            ),
        ).fetchone()
    return dict(row)


def cancel_tgnum_order(order_id: int, user_id: int) -> None:
    with db_conn() as c:
        c.execute(
            """
            UPDATE tg_number_orders SET status='cancelled', updated_at=NOW()
            WHERE id=%s AND user_id=%s AND status='awaiting_payment'
              AND telegram_payment_id IS NULL
            """,
            (int(order_id), int(user_id)),
        )


def pay_tgnum_order_with_jewels(user, country: dict, jewels: int) -> tuple:
    """يخصم الجواهر ويسجّل الطلب والقيد المحاسبي في معاملة واحدة."""
    amount = int(jewels)
    if amount <= 0:
        return "invalid", None, None
    with db_conn() as c:
        updated = c.execute(
            """
            UPDATE users SET jewels=COALESCE(jewels,0)-%s
            WHERE user_id=%s AND COALESCE(jewels,0)>=%s
            RETURNING jewels
            """,
            (amount, user.id, amount),
        ).fetchone()
        if not updated:
            return "insufficient", None, None
        order = c.execute(
            """
            INSERT INTO tg_number_orders
                (user_id, user_name, user_username, country_code, country_name,
                 base_price_cents, price_cents, payment_method, amount, status, paid_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'jewels',%s,'paid',NOW())
            RETURNING *
            """,
            (
                user.id, user.full_name or "", user.username or "",
                country["code"], country["name"],
                int(country["base_price_cents"]), int(country["price_cents"]), amount,
            ),
        ).fetchone()
        c.execute(
            "INSERT INTO jewel_transactions (user_id,amount,transaction_type,reference) "
            "VALUES (%s,%s,'spend',%s)",
            (user.id, -amount, f"tgnum_order:{order['id']}"),
        )
    return "claimed", dict(order), updated["jewels"]


def validate_tgnum_stars_invoice(order_id: int, user_id: int, stars: int) -> bool:
    with db_conn() as c:
        row = c.execute(
            """
            SELECT id FROM tg_number_orders
            WHERE id=%s AND user_id=%s AND payment_method='stars'
              AND status='awaiting_payment' AND amount=%s
              AND created_at > NOW() - INTERVAL '1 day'
            """,
            (int(order_id), int(user_id), int(stars)),
        ).fetchone()
    return bool(row)


def claim_tgnum_stars_payment(order_id: int, user_id: int, stars: int, charge_id: str) -> tuple:
    """يؤكد الدفعة مرة واحدة فقط؛ أي دفعة مكررة أو غير مطابقة تُرجَع للعضو."""
    with db_conn() as c:
        row = c.execute(
            """
            UPDATE tg_number_orders
            SET status='paid', telegram_payment_id=%s, paid_at=NOW(), updated_at=NOW()
            WHERE id=%s AND user_id=%s AND payment_method='stars'
              AND status='awaiting_payment' AND amount=%s
            RETURNING *
            """,
            (charge_id, int(order_id), int(user_id), int(stars)),
        ).fetchone()
        if row:
            return "claimed", dict(row)
        existing = c.execute(
            "SELECT * FROM tg_number_orders WHERE id=%s", (int(order_id),)
        ).fetchone()
    if existing and existing.get("telegram_payment_id") == charge_id:
        return "duplicate_update", dict(existing)
    return "invalid", dict(existing) if existing else None


def _tgnum_ensure_order_code(order: dict) -> str:
    if order.get("order_code"):
        return order["order_code"]
    try:
        code = next_order_code(int(order["user_id"]))
    except Exception:
        logger.exception("تعذر توليد كود طلب أرقام تلي، سيُستخدم كود احتياطي")
        code = f"TGN-{order['id']}"
    with db_conn() as c:
        row = c.execute(
            "UPDATE tg_number_orders SET order_code=%s, updated_at=NOW() "
            "WHERE id=%s AND order_code IS NULL RETURNING order_code",
            (code, int(order["id"])),
        ).fetchone()
        if row:
            return row["order_code"]
        current = c.execute(
            "SELECT order_code FROM tg_number_orders WHERE id=%s", (int(order["id"]),)
        ).fetchone()
    return (current or {}).get("order_code") or code


def complete_tgnum_order(order_id: int, actor_id: int):
    with db_conn() as c:
        row = c.execute(
            """
            UPDATE tg_number_orders
            SET status='completed', completed_at=NOW(), completed_by=%s, updated_at=NOW()
            WHERE id=%s AND status='paid'
            RETURNING *
            """,
            (int(actor_id), int(order_id)),
        ).fetchone()
    return dict(row) if row else None


def mark_tgnum_notified(order_id: int) -> None:
    with db_conn() as c:
        c.execute(
            "UPDATE tg_number_orders SET notified_at=NOW() WHERE id=%s", (int(order_id),)
        )


def list_pending_tgnum_orders(limit: int = 15) -> list:
    with db_conn() as c:
        rows = c.execute(
            "SELECT * FROM tg_number_orders WHERE status='paid' ORDER BY id DESC LIMIT %s",
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def count_pending_tgnum_orders() -> int:
    try:
        with db_conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM tg_number_orders WHERE status='paid'"
            ).fetchone()
        return int(row["n"] or 0)
    except Exception:
        return 0


def _tgnum_jewel_balance(user_id: int):
    try:
        with db_conn() as c:
            row = c.execute("SELECT jewels FROM users WHERE user_id=%s", (user_id,)).fetchone()
        return row["jewels"] if row else 0
    except Exception:
        return 0


# ───────────────────────── نصوص ولوحات ─────────────────────────
def _tgnum_paid_text(order: dict) -> str:
    amount = int(order.get("amount") or 0)
    if order.get("payment_method") == "stars":
        return f"{amount:,} ⭐ نجمة"
    return f"{fmt_jewel_amount(amount)} 💎 جوهرة"


def _tgnum_usd(cents) -> str:
    return f"{Decimal(int(cents or 0)) / 100:.2f}$"


def _tgnum_order_text(order: dict, heading: str, fallback_note: str = "") -> str:
    code = html.escape(str(order.get("order_code") or f"TGN-{order['id']}"))
    username = f"@{order['user_username']}" if order.get("user_username") else "لا يوجد"
    status_text = {
        "paid": "⏳ بانتظار التسليم",
        "completed": "✅ مكتمل",
    }.get(order.get("status"), str(order.get("status")))
    paid_at = order.get("paid_at")
    time_text = (
        paid_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if hasattr(paid_at, "astimezone") else ""
    )
    lines = [
        heading, "",
        f"🧾 كود الطلب: <code>{code}</code>",
        f"👤 العضو: {html.escape(order.get('user_name') or 'غير معروف')}",
        f"🆔 المعرف: {html.escape(username)} | <code>{order['user_id']}</code>",
        f"🌍 الدولة: <b>{html.escape(order.get('country_name') or '')}</b> "
        f"(<code>{html.escape(order.get('country_code') or '')}</code>)",
        f"💵 السعر: <b>{_tgnum_usd(order.get('price_cents'))}</b> "
        f"(سعر المزوّد {_tgnum_usd(order.get('base_price_cents'))})",
        f"💳 المدفوع: <b>{_tgnum_paid_text(order)}</b>",
        f"📝 الحالة: {status_text}",
    ]
    if time_text:
        lines.append(f"⏰ {time_text}")
    if fallback_note:
        lines.extend(["", fallback_note])
    return "\n".join(lines)


def _tgnum_done_markup(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ اكتمل الطلب", callback_data=f"tgnum:done:{order_id}")
    ]])


def tgnum_catalog_keyboard(countries: list, page: int) -> tuple:
    total_pages = max(1, (len(countries) + TGNUM_PAGE_SIZE - 1) // TGNUM_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * TGNUM_PAGE_SIZE
    page_items = countries[start:start + TGNUM_PAGE_SIZE]
    rows = []
    for index in range(0, len(page_items), 2):
        row = []
        for country in page_items[index:index + 2]:
            flag = country.get("flag") or tgnum_country_flag(country["code"])
            label = f"{flag} {country['code']} | {Decimal(country['price_cents']) / 100:.2f}$"
            row.append(InlineKeyboardButton(label[:64], callback_data=f"tgnum:c:{country['code']}:{page}"))
        rows.append(row)
    for start_page in range(0, total_pages, 7):
        rows.append([
            InlineKeyboardButton(
                f"[{page_num + 1}]" if page_num == page else str(page_num + 1),
                callback_data=f"tgnum:page:{page_num}",
            )
            for page_num in range(start_page, min(start_page + 7, total_pages))
        ])
    rows.append([InlineKeyboardButton("🔎 بحث عن الدولة", callback_data=f"tgnum:search:{page}")])
    rows.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows), total_pages


async def _tgnum_edit(q, text: str, markup=None) -> None:
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception as exc:
        if "not modified" in str(exc).lower():
            return
        try:
            await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            logger.exception("تعذر عرض شاشة أرقام تلي")


def _tgnum_back_markup(target: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=target)]])


# ───────────────────────── شاشات الأعضاء ─────────────────────────
async def _tgnum_load_countries(q, is_owner: bool):
    countries, status = await get_tgnum_countries()
    if status != "ok" or countries is None:
        hint = ""
        if is_owner and status == "not_configured":
            hint = "\n\n(للمالك: اضبط مفتاح المورد ومعرّفه من «📲 إعدادات أرقام تلي».)"
        await _tgnum_edit(
            q, "⚠️ الخدمة غير متاحة حالياً. يرجى التواصل مع الإدارة." + hint,
            _tgnum_back_markup(),
        )
        return None
    if not countries:
        await _tgnum_edit(q, "📭 لا توجد دول متاحة حالياً.", _tgnum_back_markup())
        return None
    return countries


async def _tgnum_show_catalog(q, context, page: int, is_owner: bool) -> None:
    context.user_data.pop("tgnum_quote", None)
    if context.user_data.get("state") == "tgnum_await_search":
        context.user_data["state"] = "main_menu"
    countries = await _tgnum_load_countries(q, is_owner)
    if countries is None:
        return
    keyboard, _ = tgnum_catalog_keyboard(countries, page)
    await _tgnum_edit(
        q, "📲 <b>أرقام تلي لكل دول العالم</b>\n\nاختر الدولة:", keyboard
    )


async def _tgnum_show_country(q, context, country: dict, page: int, price_changed: bool = False) -> None:
    price_cents = int(country["price_cents"])
    stars, jewels = tgnum_price_options(price_cents)
    context.user_data["tgnum_quote"] = {
        "code": country["code"], "price_cents": price_cents,
        "stars": stars, "jewels": jewels,
        "expires_at": time.time() + TGNUM_QUOTE_TTL_SECONDS,
    }
    note = "⚠️ تغيّر السعر؛ راجعه ثم اختر طريقة الدفع.\n\n" if price_changed else ""
    balance = _tgnum_jewel_balance(q.from_user.id)
    text = (
        f"{note}📲 طلب رقم من <b>{html.escape(country['name'])}</b>\n\n"
        f"💰 السعر: <b>{_tgnum_usd(price_cents)}</b>\n"
        f"⭐ بالنجوم: <b>{stars:,}</b>\n"
        f"💎 بالجواهر: <b>{jewels:,}</b>  (رصيدك: {fmt_jewel_amount(balance)})\n"
        f"📦 المتوفر عند المزوّد: {country['qty']}\n\n"
        "اختر طريقة الدفع. بعد الدفع تواصل مع المالك لاستلام الرقم."
    )
    rows = []
    if stars > 0:
        rows.append([InlineKeyboardButton(
            f"⭐ الدفع بالنجوم — {stars:,}", callback_data=f"tgnum:pay:stars:{country['code']}:{page}")])
    if jewels > 0:
        rows.append([InlineKeyboardButton(
            f"💎 الدفع بالجواهر — {jewels:,}", callback_data=f"tgnum:pay:jewels:{country['code']}:{page}")])
    rows.append([InlineKeyboardButton("🔙 رجوع للدول", callback_data=f"tgnum:page:{page}")])
    await _tgnum_edit(q, text, InlineKeyboardMarkup(rows))


async def _tgnum_start_payment(q, context, user, method: str, code: str, page: int) -> None:
    quote = context.user_data.get("tgnum_quote")
    if (
        not quote or quote.get("code") != code
        or quote.get("expires_at", 0) < time.time()
    ):
        context.user_data.pop("tgnum_quote", None)
        await q.answer("انتهت صلاحية العرض. اختر الدولة مجدداً.", show_alert=True)
        return
    countries, status = await get_tgnum_countries(force_refresh=True)
    if status != "ok" or countries is None:
        await _tgnum_edit(
            q, "⚠️ تعذر تحديث قائمة الدول. لم يُخصم أي رصيد؛ حاول لاحقاً.",
            _tgnum_back_markup(f"tgnum:page:{page}"),
        )
        return
    country = next((item for item in countries if item["code"] == code), None)
    if not country:
        context.user_data.pop("tgnum_quote", None)
        await _tgnum_edit(
            q, "⚠️ لم تعد هذه الدولة متاحة. لم يُخصم أي رصيد.",
            _tgnum_back_markup(f"tgnum:page:{page}"),
        )
        return
    stars, jewels = tgnum_price_options(country["price_cents"])
    if (
        int(country["price_cents"]) != int(quote["price_cents"])
        or stars != quote["stars"] or jewels != quote["jewels"]
    ):
        await _tgnum_show_country(q, context, country, page, price_changed=True)
        return

    if method == "stars":
        if stars <= 0:
            await q.answer("⚠️ الدفع بالنجوم غير متاح حالياً.", show_alert=True)
            return
        order = create_tgnum_stars_order(user, country, stars)
        try:
            await context.bot.send_invoice(
                chat_id=user.id,
                title=f"رقم تلي — {country['name']}"[:32],
                description=f"رقم تيليجرام من {country['name']} مقابل {stars} نجمة"[:255],
                payload=f"tgnum_stars:{order['id']}",
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice("رقم تلي", stars)],
            )
        except Exception:
            logger.exception("تعذر إرسال فاتورة أرقام تلي للمستخدم %s", user.id)
            cancel_tgnum_order(order["id"], user.id)
            await _tgnum_edit(
                q, "⚠️ تعذر إنشاء الفاتورة. لم يُخصم أي مبلغ؛ حاول لاحقاً.",
                _tgnum_back_markup(f"tgnum:page:{page}"),
            )
            return
        context.user_data.pop("tgnum_quote", None)
        await _tgnum_edit(
            q,
            "🧾 أُرسلت فاتورة النجوم. أكمل الدفع من رسالة الفاتورة، "
            "وبعدها ستصلك رسالة بالخطوة التالية.",
            _tgnum_back_markup("main_menu"),
        )
        return

    # الدفع بالجواهر
    if jewels <= 0:
        await q.answer("⚠️ الدفع بالجواهر غير متاح حالياً.", show_alert=True)
        return
    status_code, order, balance = await asyncio.to_thread(
        pay_tgnum_order_with_jewels, user, country, jewels
    )
    if status_code == "insufficient":
        await q.answer(
            f"❌ رصيدك غير كافٍ. المطلوب {jewels:,} جوهرة.", show_alert=True
        )
        return
    if status_code != "claimed" or not order:
        await q.answer("⚠️ تعذر إتمام الدفع. حاول لاحقاً.", show_alert=True)
        return
    context.user_data.pop("tgnum_quote", None)
    await finalize_tgnum_order(context, order)
    try:
        await q.message.delete()
    except Exception:
        pass


# ───────────────────────── إنهاء الطلب والإشعارات ─────────────────────────
async def notify_tgnum_order(context, order: dict) -> bool:
    """يرسل الطلب إلى كروب الطلبات (أو خاص المالك عند تعذر الكروب)."""
    markup = _tgnum_done_markup(order["id"])
    chat = get_tgnum_orders_chat()
    targets = []
    if chat is not None:
        targets.append(chat)
    if OWNER_ID and OWNER_ID not in targets:
        targets.append(OWNER_ID)
    for index, target in enumerate(targets):
        note = ""
        if index > 0 and chat is not None:
            note = "⚠️ تعذر الإرسال إلى كروب الطلبات؛ راجع إعداد الكروب من إعدادات أرقام تلي."
        try:
            await context.bot.send_message(
                target,
                _tgnum_order_text(order, "📥 <b>طلب جديد — أرقام تلي</b>", note),
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            mark_tgnum_notified(order["id"])
            return True
        except Exception:
            logger.exception("تعذر إرسال طلب أرقام تلي %s إلى %s", order["id"], target)
    return False


async def finalize_tgnum_order(context, order: dict) -> None:
    order = dict(order)
    order["order_code"] = await asyncio.to_thread(_tgnum_ensure_order_code, order)
    code = html.escape(order["order_code"])
    try:
        await context.bot.send_message(
            order["user_id"],
            "✅ <b>تم استلام طلبك</b>\n\n"
            f"🧾 كود الطلب: <code>{code}</code>\n"
            f"🌍 الدولة: <b>{html.escape(order['country_name'])}</b>\n"
            f"💳 المدفوع: <b>{_tgnum_paid_text(order)}</b>\n\n"
            "📞 <b>تواصل مع المالك الآن لاستلام رقمك</b> واذكر كود الطلب أعلاه.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                contact_owner_row()
                + [[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]]
            ),
        )
    except Exception:
        logger.exception("تعذر إشعار العضو %s بطلب أرقام تلي", order["user_id"])
    if not await notify_tgnum_order(context, order):
        logger.error(
            "طلب أرقام تلي %s مدفوع لكن لم يصل إشعاره لأي جهة؛ يظهر في الطلبات المعلقة", order["id"]
        )


async def tgnum_pre_checkout(update, context) -> None:
    query = update.pre_checkout_query
    try:
        parts = (query.invoice_payload or "").split(":")
        valid = (
            len(parts) == 2 and parts[1].isdigit()
            and query.currency == "XTR"
            and validate_tgnum_stars_invoice(
                int(parts[1]), query.from_user.id, int(query.total_amount)
            )
        )
        if valid:
            await query.answer(ok=True)
        else:
            await query.answer(ok=False, error_message="انتهت صلاحية الفاتورة. أعد الطلب من البوت.")
    except Exception:
        logger.exception("خطأ في pre_checkout لأرقام تلي")
        try:
            await query.answer(ok=False, error_message="خطأ داخلي، حاول مجدداً.")
        except Exception:
            pass


async def tgnum_successful_payment(update, context) -> None:
    payment = update.message.successful_payment
    user = update.effective_user
    charge_id = payment.telegram_payment_charge_id or f"update:{update.update_id}"
    parts = (payment.invoice_payload or "").split(":")
    status, order = "invalid", None
    if len(parts) == 2 and parts[1].isdigit():
        status, order = await asyncio.to_thread(
            claim_tgnum_stars_payment, int(parts[1]), user.id,
            int(payment.total_amount), charge_id,
        )
    if status == "claimed":
        await finalize_tgnum_order(context, order)
        return
    if status == "duplicate_update":
        return
    # دفعة لا تطابق أي طلب صالح: نعيد النجوم تلقائياً أو نبلغ المالك.
    try:
        await context.bot.refund_star_payment(
            user_id=user.id, telegram_payment_charge_id=charge_id
        )
        try:
            from .owner_details import mark_star_income_refunded
            mark_star_income_refunded(charge_id)
        except Exception:
            logger.exception("تعذر تحديث سجل النجوم بعد الاسترداد")
        await update.message.reply_text(
            "⚠️ تعذر ربط الدفعة بطلب صالح، وأُعيدت نجومك تلقائياً. أعد الطلب من القائمة."
        )
    except Exception:
        logger.exception("تعذر استرجاع نجوم دفعة أرقام تلي غير صالحة")
        if OWNER_ID:
            try:
                await context.bot.send_message(
                    OWNER_ID,
                    "⚠️ دفعة نجوم لأرقام تلي لا تطابق طلباً صالحاً وتعذّر استردادها تلقائياً.\n"
                    f"المستخدم: {user.id}\nالمبلغ: {payment.total_amount}\nالعملية: {charge_id}",
                )
            except Exception:
                logger.exception("تعذر إبلاغ المالك بدفعة أرقام تلي غير صالحة")
        await update.message.reply_text(
            "⚠️ تعذر ربط الدفعة بطلب صالح. أبلغنا المالك وسيراجعها."
        )


# ───────────────────────── إعدادات المالك ─────────────────────────
def _tgnum_admin_view() -> tuple:
    api_key, your_id = tgnum_credentials()
    group = str(get_setting(TGNUM_ORDERS_GROUP_SETTING) or "").strip()
    stars_set = bool(str(get_setting(TGNUM_STARS_RATE_SETTING) or "").strip())
    jewels_set = bool(str(get_setting(TGNUM_JEWELS_RATE_SETTING) or "").strip())
    visible = is_tgnum_visible()
    pending = count_pending_tgnum_orders()
    group_line = (
        f"👥 كروب الطلبات: <code>{html.escape(group)}</code>\n" if group
        else "👥 كروب الطلبات: غير مضبوط (تصل الطلبات إلى خاصك)\n"
    )
    text = (
        "📲 <b>إعدادات أرقام تلي</b>\n\n"
        f"🔑 مفتاح المورد: {html.escape(tgnum_mask_secret(api_key))}\n"
        f"🆔 معرّف المورد: {html.escape(your_id) if your_id else 'غير مضبوط ❌'}\n"
        + group_line
    )
    text += (
        f"⭐ سعر النجوم: {tgnum_stars_rate().normalize():f} نجمة لكل 1$"
        f"{'' if stars_set else ' (افتراضي)'}\n"
        f"💎 سعر الجواهر: {tgnum_jewels_rate().normalize():f} جوهرة لكل 1$"
        f"{'' if jewels_set else ' (افتراضي)'}\n"
        f"👁 الظهور للأعضاء: {'ظاهر ✅' if visible else 'مخفي ❌'}\n"
        f"📋 طلبات بانتظار التسليم: {pending}"
    )
    rows = [
        [InlineKeyboardButton("🔑 مفتاح المورد (API)", callback_data="tgnum:admin:key"),
         InlineKeyboardButton("🆔 معرّف المورد", callback_data="tgnum:admin:uid")],
        [InlineKeyboardButton("👥 رابط/معرّف كروب الطلبات", callback_data="tgnum:admin:group")],
        [InlineKeyboardButton("⭐ سعر النجوم", callback_data="tgnum:admin:stars"),
         InlineKeyboardButton("💎 سعر الجواهر", callback_data="tgnum:admin:jewels")],
        [InlineKeyboardButton("🔄 اختبار الاتصال بالمورد", callback_data="tgnum:admin:test")],
        [InlineKeyboardButton(f"📋 الطلبات المعلقة ({pending})", callback_data="tgnum:admin:pending")],
        [InlineKeyboardButton(
            "🙈 إخفاء القسم عن الأعضاء" if visible else "👁 إظهار القسم للأعضاء",
            callback_data="tgnum:admin:toggle")],
        [InlineKeyboardButton("🔙 إعدادات المالك", callback_data="owner_settings")],
    ]
    return text, InlineKeyboardMarkup(rows)


async def _tgnum_show_admin(q=None, message=None, context=None) -> None:
    text, markup = _tgnum_admin_view()
    if q is not None:
        await _tgnum_edit(q, text, markup)
    elif message is not None:
        await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


_TGNUM_ADMIN_PROMPTS = {
    "key": ("os_tgnum_api_key", "🔑 أرسل مفتاح API الخاص بالمورد TG-Lion.\nسأحذف رسالتك بعد حفظه.\n(أرسل «حذف» لإزالته)"),
    "uid": ("os_tgnum_user_id", "🆔 أرسل معرّفك لدى المورد (YourID).\n(أرسل «حذف» لإزالته)"),
    "group": (
        "os_tgnum_group",
        "👥 أرسل معرّف كروب الطلبات الثاني: رقمه (يبدأ بـ -100) أو @username أو رابطه العام.\n\n"
        "⚠️ أضف البوت إلى الكروب أولاً. الروابط الخاصة (t.me/+…) لا تكفي لأن البوت يحتاج معرّف الكروب.\n"
        "(أرسل «حذف» لإزالته)",
    ),
    "stars": ("os_tgnum_rate_stars", "⭐ أرسل عدد النجوم المقابل لكل 1$ (مثال: 100)."),
    "jewels": ("os_tgnum_rate_jewels", "💎 أرسل عدد الجواهر المقابل لكل 1$ (مثال: 100)."),
}


async def _tgnum_handle_admin_callback(update, context, q, parts: list) -> None:
    sub = parts[2] if len(parts) > 2 else ""
    if sub == "":
        context.user_data["state"] = "main_menu"
        await _tgnum_show_admin(q=q)
        return
    if sub in _TGNUM_ADMIN_PROMPTS:
        state, prompt = _TGNUM_ADMIN_PROMPTS[sub]
        context.user_data["state"] = state
        await _tgnum_edit(q, html.escape(prompt), _tgnum_back_markup("tgnum:admin"))
        return
    if sub == "toggle":
        set_setting(TGNUM_VISIBLE_KEY, "0" if is_tgnum_visible() else "1")
        await _tgnum_show_admin(q=q)
        return
    if sub == "test":
        _tgnum_reset_cache()
        countries, status = await get_tgnum_countries(force_refresh=True)
        if status == "ok" and countries is not None:
            result = f"✅ الاتصال ناجح — {len(countries)} دولة متاحة."
        elif status == "not_configured":
            result = "⚠️ اضبط مفتاح المورد ومعرّفه أولاً."
        else:
            result = "❌ فشل الاتصال بالمورد. تحقق من المفتاح والمعرّف."
        await _tgnum_edit(q, result, _tgnum_back_markup("tgnum:admin"))
        return
    if sub == "pending":
        orders = await asyncio.to_thread(list_pending_tgnum_orders)
        if not orders:
            await _tgnum_edit(q, "📋 لا توجد طلبات معلقة.", _tgnum_back_markup("tgnum:admin"))
            return
        rows = [
            [InlineKeyboardButton(
                f"{o.get('order_code') or 'TGN-' + str(o['id'])} — {o['country_code']}",
                callback_data=f"tgnum:view:{o['id']}")]
            for o in orders
        ]
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="tgnum:admin")])
        await _tgnum_edit(q, "📋 <b>الطلبات بانتظار التسليم</b>", InlineKeyboardMarkup(rows))
        return
    await q.answer("⚠️ أمر غير معروف.", show_alert=True)


async def _tgnum_handle_order_callback(update, context, q, action: str, order_id: int, user) -> None:
    order = await asyncio.to_thread(get_tgnum_order, order_id)
    if not order:
        await q.answer("⚠️ الطلب غير موجود.", show_alert=True)
        return
    if action == "view":
        if order["status"] == "completed":
            await _tgnum_edit(q, _tgnum_order_text(order, "📋 <b>تفاصيل الطلب</b>"), None)
        else:
            await _tgnum_edit(
                q, _tgnum_order_text(order, "📥 <b>طلب — أرقام تلي</b>"), _tgnum_done_markup(order_id)
            )
        return
    if order["status"] == "completed":
        await q.answer("ℹ️ هذا الطلب مكتمل مسبقاً.", show_alert=True)
        await _tgnum_edit(q, _tgnum_order_text(order, "📋 <b>تفاصيل الطلب</b>"), None)
        return
    if order["status"] != "paid":
        await q.answer("⚠️ هذا الطلب غير مدفوع.", show_alert=True)
        return
    if action == "done":
        await _tgnum_edit(
            q,
            _tgnum_order_text(order, "❓ <b>تأكيد إكمال الطلب</b>"),
            InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأكيد الإكمال", callback_data=f"tgnum:ok:{order_id}")],
                [InlineKeyboardButton("↩️ إلغاء", callback_data=f"tgnum:view:{order_id}")],
            ]),
        )
        return
    # action == "ok"
    done = await asyncio.to_thread(complete_tgnum_order, order_id, user.id)
    if not done:
        await q.answer("ℹ️ مكتمل مسبقاً.", show_alert=True)
        return
    try:
        await context.bot.send_message(
            done["user_id"],
            "✅ <b>تم إكمال طلبك</b>\n\n"
            f"🧾 كود الطلب: <code>{html.escape(str(done.get('order_code') or ''))}</code>\n"
            f"🌍 الدولة: <b>{html.escape(done['country_name'])}</b>\n\n"
            "<i>شكراً لاستخدامك البوت.</i>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        logger.exception("تعذر إشعار العضو بإكمال طلب أرقام تلي")
    await _tgnum_edit(q, _tgnum_order_text(done, "✅ <b>طلب مكتمل — أرقام تلي</b>"), None)


# ───────────────────────── الموزّع ─────────────────────────
async def handle_tgnum_callback(update, context, q, data: str, user, is_owner: bool) -> bool:
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action in {"admin", "done", "ok", "view"}:
        if not is_owner:
            await q.answer("🚫 للمالك فقط.", show_alert=True)
            return True
        if action == "admin":
            await _tgnum_handle_admin_callback(update, context, q, parts)
        else:
            if len(parts) != 3 or not parts[2].isdigit():
                await q.answer("⚠️ طلب غير صالح.", show_alert=True)
                return True
            await _tgnum_handle_order_callback(update, context, q, action, int(parts[2]), user)
        return True

    if not is_owner and not is_tgnum_visible():
        await q.answer("هذا القسم غير متاح حالياً.", show_alert=True)
        return True

    def _page(index: int) -> int:
        try:
            return max(0, int(parts[index]))
        except (IndexError, ValueError):
            return 0

    if action == "start":
        await _tgnum_show_catalog(q, context, 0, is_owner)
    elif action == "page":
        await _tgnum_show_catalog(q, context, _page(2), is_owner)
    elif action == "search":
        context.user_data["state"] = "tgnum_await_search"
        context.user_data["tgnum_search_page"] = _page(2)
        await _tgnum_edit(
            q, "أرسل رمز الاتصال الدولي للدولة، مثل 964 أو +964.",
            InlineKeyboardMarkup([[InlineKeyboardButton(
                "↩️ الرجوع إلى الدول", callback_data=f"tgnum:page:{_page(2)}")]]),
        )
    elif action == "c" and len(parts) >= 3:
        countries = await _tgnum_load_countries(q, is_owner)
        if countries is None:
            return True
        code = parts[2].upper()
        country = next((item for item in countries if item["code"] == code), None)
        if not country:
            await _tgnum_edit(
                q, "⚠️ لم تعد هذه الدولة متاحة. افتح القائمة وحاول مجدداً.",
                _tgnum_back_markup("tgnum:start"),
            )
            return True
        await _tgnum_show_country(q, context, country, _page(3))
    elif action == "pay" and len(parts) >= 4 and parts[2] in {"stars", "jewels"}:
        await _tgnum_start_payment(q, context, user, parts[2], parts[3].upper(), _page(4))
    else:
        await q.answer("⚠️ أمر غير معروف.", show_alert=True)
    return True


async def handle_tgnum_text(update, context, text: str) -> bool:
    user = update.effective_user
    is_owner = user.id == OWNER_ID
    state = context.user_data.get("state", "")
    message = update.message

    if state == "tgnum_await_search":
        if not is_tgnum_visible() and not is_owner:
            context.user_data["state"] = "main_menu"
            return True
        page = max(0, int(context.user_data.get("tgnum_search_page", 0)))
        back = InlineKeyboardMarkup([[InlineKeyboardButton(
            "↩️ الرجوع إلى الدول", callback_data=f"tgnum:page:{page}")]])
        candidate = tgnum_parse_calling_code_query(text)
        if candidate is None:
            await message.reply_text("أرسل رمز اتصال دولياً بالأرقام فقط، مثل 964 أو +964.", reply_markup=back)
            return True
        countries, status = await get_tgnum_countries()
        if status != "ok" or countries is None:
            await message.reply_text("⚠️ تعذر تحميل قائمة الدول الآن. أعد إرسال الرمز بعد قليل.")
            return True
        context.user_data["state"] = "main_menu"
        matches = tgnum_find_by_calling_code(countries, candidate)
        if not matches:
            await message.reply_text(f"لم أجد دولة متاحة برمز الاتصال +{candidate}.", reply_markup=back)
            return True
        rows = []
        for country in matches:
            flag = country.get("flag") or tgnum_country_flag(country["code"])
            label = f"{flag} {country['name']} | {Decimal(country['price_cents']) / 100:.2f}$"
            rows.append([InlineKeyboardButton(label[:64], callback_data=f"tgnum:c:{country['code']}:{page}")])
        rows.extend(back.inline_keyboard)
        await message.reply_text(
            f"الدول المتاحة لرمز الاتصال +{candidate}:", reply_markup=InlineKeyboardMarkup(rows)
        )
        return True

    if not state.startswith("os_tgnum_"):
        return False
    if not is_owner:
        return True
    delete_input = text.strip() in {"حذف", "delete"}
    admin_back = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إعدادات أرقام تلي", callback_data="tgnum:admin")]])

    if state in {"os_tgnum_api_key", "os_tgnum_user_id"}:
        key = TGNUM_API_KEY_SETTING if state == "os_tgnum_api_key" else TGNUM_USER_ID_SETTING
        value = "" if delete_input else text.strip()
        if state == "os_tgnum_api_key":
            try:  # لا نترك المفتاح ظاهراً في المحادثة
                await message.delete()
            except Exception:
                pass
        if value and (not re.fullmatch(r"\S{3,200}", value)):
            await message.reply_text("⚠️ القيمة غير صالحة (بلا مسافات، من 3 إلى 200 حرفاً). أعد الإرسال.")
            return True
        set_setting(key, value)
        _tgnum_reset_cache()
        context.user_data["state"] = "main_menu"
        await _tgnum_show_admin(message=message)
        return True

    if state == "os_tgnum_group":
        if delete_input:
            set_setting(TGNUM_ORDERS_GROUP_SETTING, "")
            context.user_data["state"] = "main_menu"
            await _tgnum_show_admin(message=message)
            return True
        ref = parse_tgnum_chat_ref(text)
        if not ref:
            await message.reply_text(
                "⚠️ لم أتعرف على الكروب. أرسل رقمه (-100…) أو @username أو رابطه العام.\n"
                "الرابط الخاص (t.me/+…) لا يكفي؛ أضف البوت للكروب ثم استخدم معرّفه الرقمي.",
                reply_markup=admin_back,
            )
            return True
        try:
            chat = await context.bot.get_chat(int(ref) if re.fullmatch(r"-?\d+", ref) else ref)
        except Exception:
            await message.reply_text(
                "⚠️ لا يستطيع البوت الوصول لهذا الكروب. أضفه إليه كعضو ثم أعد الإرسال.",
                reply_markup=admin_back,
            )
            return True
        set_setting(TGNUM_ORDERS_GROUP_SETTING, str(chat.id))
        context.user_data["state"] = "main_menu"
        await message.reply_text(f"✅ تم ضبط كروب الطلبات: {chat.title or chat.id}")
        await _tgnum_show_admin(message=message)
        return True

    if state in {"os_tgnum_rate_stars", "os_tgnum_rate_jewels"}:
        key = TGNUM_STARS_RATE_SETTING if state == "os_tgnum_rate_stars" else TGNUM_JEWELS_RATE_SETTING
        if delete_input:
            set_setting(key, "")
        else:
            try:
                value = Decimal(text.strip().replace(",", ""))
                if not value.is_finite() or value <= 0 or value > 100000:
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                await message.reply_text("⚠️ أرسل رقماً موجباً صحيحاً، مثال: 100", reply_markup=admin_back)
                return True
            set_setting(key, str(value.normalize()))
        context.user_data["state"] = "main_menu"
        await _tgnum_show_admin(message=message)
        return True

    return False
