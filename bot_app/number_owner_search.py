"""بحث المالك الشامل عن حسابات مخزون الأرقام.

يرسل المالك يوزر أو ID أو اسم حساب (أو رقم هاتف) فيظهر له كل ما يخص
الحساب: الاسم، تاريخ الإضافة، الحالة (مباع / مؤجّر / مشاركة / مطرود ...)،
كلمة 2FA، عدد الأجهزة، مع أزرار مباشرة لجلب آخر كود وطرد الأجهزة.

ملاحظة: تيليجرام لا يوفّر تاريخ إنشاء الحساب نفسه، لذلك يُعرض تاريخ
الإضافة للمخزون وتاريخ أقدم جلسة مسجّلة على الحساب (أقرب مؤشر متاح).
"""

from . import shared as _shared

globals().update(
    {key: value for key, value in vars(_shared).items() if not key.startswith("__")}
)

_ARABIC_DIGITS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)
_MAX_RESULTS = 8
_SCAN_CONCURRENCY = 6
_SCAN_LIMIT = 400


def normalize_search_query(text: str) -> dict:
    """يحوّل نص المالك إلى عناصر بحث: يوزر، أرقام، اسم."""
    raw = str(text or "").strip().translate(_ARABIC_DIGITS)
    raw = re.sub(r"^https?://(www\.)?t\.me/", "", raw, flags=re.I)
    raw = raw.lstrip("@").strip()
    digits = re.sub(r"\D", "", raw)
    is_numeric = bool(raw) and bool(re.fullmatch(r"[+\d\s\-]+", raw))
    username = raw.lower() if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{2,31}", raw) else ""
    return {
        "raw": raw,
        "digits": digits if is_numeric else "",
        "username": username,
        "name": raw if not is_numeric else "",
    }


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_BASE_SELECT = (
    "SELECT ns.id, ns.phone_number, ns.session_string, ns.assigned_to, "
    "       ns.assigned_at, ns.added_at, ns.ever_sold, ns.twofa_password, "
    "       ns.last_authorized, ns.deleted_at, ns.frozen_at, ns.raksh_only, "
    "       ns.contributor_share_percent, ns.contributed_by, "
    "       ns.last_device_count, ns.sessions_reset, "
    "       ns.tg_user_id, ns.tg_username, ns.tg_name, "
    "       u.full_name AS buyer_name, u.username AS buyer_username "
    "FROM number_stock ns "
    "LEFT JOIN users u ON u.user_id = COALESCE(ns.assigned_to, ns.contributed_by) "
)


def search_stock_cached(query: dict, limit: int = _MAX_RESULTS) -> list[dict]:
    """بحث سريع في قاعدة البيانات: رقم الهاتف، المعرّف المخزّن، المشتري/المشارك."""
    conditions: list[str] = []
    params: list = []
    digits = query.get("digits") or ""
    username = query.get("username") or ""
    name = query.get("name") or ""

    if digits:
        if len(digits) >= 5:
            conditions.append(
                "regexp_replace(COALESCE(ns.phone_number,''), '[^0-9]', '', 'g') LIKE %s"
            )
            params.append(f"%{digits}%")
        if len(digits) >= 4:
            try:
                numeric_id = int(digits)
            except ValueError:
                numeric_id = None
            if numeric_id is not None and numeric_id < 2**62:
                conditions += [
                    "ns.tg_user_id = %s",
                    "ns.assigned_to = %s",
                    "ns.contributed_by = %s",
                ]
                params += [numeric_id, numeric_id, numeric_id]
    if username:
        conditions += [
            "LOWER(COALESCE(ns.tg_username,'')) = %s",
            "LOWER(COALESCE(u.username,'')) = %s",
        ]
        params += [username, username]
    if name:
        pattern = f"%{_like_escape(name)}%"
        conditions += [
            "COALESCE(ns.tg_name,'') ILIKE %s",
            "COALESCE(ns.tg_username,'') ILIKE %s",
            "COALESCE(u.full_name,'') ILIKE %s",
        ]
        params += [pattern, pattern, pattern]

    if not conditions:
        return []

    sql = _BASE_SELECT + "WHERE (" + " OR ".join(conditions) + ") ORDER BY ns.id DESC LIMIT %s"
    params.append(limit)
    with db_conn() as c:
        rows = c.execute(sql, tuple(params)).fetchall() or []
    return [dict(r) for r in rows]


def get_stock_row(stock_id: int) -> dict | None:
    with db_conn() as c:
        row = c.execute(_BASE_SELECT + "WHERE ns.id=%s", (stock_id,)).fetchone()
    return dict(row) if row else None


def _save_identity(stock_id: int, tg_id, username: str, name: str) -> None:
    try:
        with db_conn() as c:
            c.execute(
                "UPDATE number_stock SET tg_user_id=%s, tg_username=%s, "
                "tg_name=%s, tg_info_at=NOW() WHERE id=%s",
                (tg_id, username or None, name or None, stock_id),
            )
    except Exception as exc:
        logger.warning(f"تعذّر حفظ معلومات حساب المخزون {stock_id}: {exc}")


async def fetch_live_info(row: dict, with_devices: bool = True) -> dict:
    """يتصل بجلسة الحساب ويجلب الاسم واليوزر والـ ID والأجهزة وحالة 2FA.

    يُرجع dict دائماً؛ المفتاح ``error`` يشرح سبب الفشل إن حدث.
    """
    info: dict = {"live": False}
    session = str(row.get("session_string") or "").strip()
    if not session:
        info["error"] = "لا توجد جلسة محفوظة لهذا الرقم"
        return info
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        info["error"] = "إعدادات Telegram API غير مكتملة"
        return info

    client = TelegramClient(StringSession(session), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    try:
        await asyncio.wait_for(client.connect(), timeout=15)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            info["error"] = "الجلسة منتهية — الحساب مطرود"
            return info
        me = await asyncio.wait_for(client.get_me(), timeout=10)
        if me is None:
            info["error"] = "لم يُرجع تيليجرام بيانات الحساب"
            return info
        first = str(getattr(me, "first_name", "") or "").strip()
        last = str(getattr(me, "last_name", "") or "").strip()
        info.update(
            live=True,
            tg_id=getattr(me, "id", None),
            username=str(getattr(me, "username", "") or "").strip(),
            name=" ".join(p for p in (first, last) if p),
        )
        _save_identity(row["id"], info["tg_id"], info["username"], info["name"])

        if with_devices:
            try:
                auths = (
                    await asyncio.wait_for(client(GetAuthorizationsRequest()), timeout=15)
                ).authorizations
                info["devices"] = len(auths)
                dates = [a.date_created for a in auths if getattr(a, "date_created", None)]
                info["oldest_session"] = min(dates) if dates else None
                info["other_devices"] = [
                    {
                        "device": a.device_model or "غير معروف",
                        "app": a.app_name or "",
                        "country": a.country or "",
                        "active": a.date_active,
                    }
                    for a in auths
                    if not a.current
                ][:6]
            except Exception as exc:
                logger.warning(f"تعذّر جلب أجهزة {row.get('phone_number')}: {exc}")
            try:
                pw = await asyncio.wait_for(client(GetPasswordRequest()), timeout=15)
                info["has_2fa"] = bool(getattr(pw, "has_password", False))
            except Exception:
                pass
    except asyncio.TimeoutError:
        info["error"] = "انتهت مهلة الاتصال بتيليجرام"
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {str(exc)[:100]}"
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    return info


def _identity_matches(query: dict, info: dict) -> bool:
    digits = query.get("digits") or ""
    username = query.get("username") or ""
    name = (query.get("name") or "").lower()
    if digits and str(info.get("tg_id") or "") == digits:
        return True
    if username and (info.get("username") or "").lower() == username:
        return True
    if name and (
        name in (info.get("name") or "").lower()
        or name in (info.get("username") or "").lower()
    ):
        return True
    return False


async def live_scan(query: dict, deep: bool = False) -> tuple[list[dict], int]:
    """يبحث داخل الجلسات نفسها عند عدم وجود الحساب في الكاش.

    الافتراضي: يفحص فقط الحسابات التي لم تُخزَّن هويتها بعد. ``deep=True``
    يعيد فحص كل الجلسات (يحدّث الأسماء المتغيّرة أيضاً).
    """
    where = "ns.session_string IS NOT NULL AND BTRIM(ns.session_string) <> ''"
    if not deep:
        where += " AND ns.tg_user_id IS NULL"
    with db_conn() as c:
        rows = c.execute(
            _BASE_SELECT + f"WHERE {where} ORDER BY ns.id DESC LIMIT %s",
            (_SCAN_LIMIT,),
        ).fetchall() or []
    rows = [dict(r) for r in rows]
    sem = asyncio.Semaphore(_SCAN_CONCURRENCY)
    matches: list[dict] = []

    async def _check(row: dict):
        async with sem:
            info = await fetch_live_info(row, with_devices=False)
        if info.get("live") and _identity_matches(query, info):
            row["tg_user_id"] = info.get("tg_id")
            row["tg_username"] = info.get("username")
            row["tg_name"] = info.get("name")
            matches.append(row)

    await asyncio.gather(*(_check(r) for r in rows), return_exceptions=True)
    return matches[:_MAX_RESULTS], len(rows)


def _fmt_dt(value) -> str:
    if value is None:
        return "—"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)[:16]


def stock_status_label(row: dict) -> tuple[str, str]:
    """يُرجع (أيقونة, وصف) لحالة الحساب."""
    if row.get("deleted_at"):
        return "🗑", "محذوف (سلة المهملات)"
    if row.get("assigned_to"):
        return "🟢", "مباع الآن (نشط)"
    if row.get("ever_sold"):
        return "⬜", "مباع سابقاً (البوت غادره)"
    if row.get("raksh_only"):
        share_value = row.get("contributor_share_percent")
        share = int(share_value if share_value is not None else 50)
        if share == 0:
            return "🔵", "مشاركة رقم — رشق مجاني لصاحبه"
        return "🔵", f"مؤجّر للرشق ({share}٪ للعضو)"
    if row.get("frozen_at"):
        return "🧊", "مجمّد"
    if row.get("last_authorized") is False:
        return "🚫", "مطرود (جلسة منتهية)"
    if row.get("session_string"):
        return "✅", "متاح للبيع"
    return "⚠️", "يدوي (بدون جلسة)"


def _md(value) -> str:
    """يهرّب رموز Markdown البسيطة في النصوص الحرة (أسماء/يوزرات)."""
    return re.sub(r"([_*`\[])", r"\\\1", str(value or ""))


def build_card(row: dict, info: dict | None = None) -> str:
    info = info or {}
    icon, status = stock_status_label(row)
    name = info.get("name") or row.get("tg_name") or "—"
    username = info.get("username") or row.get("tg_username") or ""
    tg_id = info.get("tg_id") or row.get("tg_user_id") or "—"

    lines = [
        f"📱 {icon} *{row['phone_number']}*",
        "",
        f"👤 الاسم: {_md(name)}",
        f"🔗 اليوزر: {'@' + _md(username) if username else '—'}",
        f"🆔 ID: `{tg_id}`",
        f"🌍 الدولة: {guess_country(row['phone_number'])}",
        "",
        f"📌 الحالة: {status}",
    ]

    holder_id = row.get("assigned_to") or row.get("contributed_by")
    if holder_id:
        holder_name = row.get("buyer_name") or "—"
        holder_user = row.get("buyer_username")
        role = "المشتري" if row.get("assigned_to") else "صاحب المشاركة"
        lines.append(
            f"🧑‍💼 {role}: {_md(holder_name)}"
            f"{' @' + _md(holder_user) if holder_user else ''} (`{holder_id}`)"
        )
    if row.get("assigned_at"):
        lines.append(f"📅 تاريخ البيع: {_fmt_dt(row.get('assigned_at'))}")

    lines += [
        "",
        f"📥 تاريخ الإضافة للمخزون: {_fmt_dt(row.get('added_at'))}",
        f"🕰 أقدم جلسة على الحساب: {_fmt_dt(info.get('oldest_session'))}",
        "",
        f"🗝 2FA المحفوظة: `{row.get('twofa_password') or 'غير محفوظة'}`",
    ]
    if "has_2fa" in info:
        lines.append(f"🔐 التحقق بخطوتين: {'مفعّل' if info['has_2fa'] else 'غير مفعّل'}")

    devices = info.get("devices")
    if devices is None and row.get("last_device_count", -1) not in (None, -1):
        devices = row.get("last_device_count")
        devices_note = " (آخر فحص محفوظ)"
    else:
        devices_note = ""
    if devices is not None:
        lines.append(f"💻 عدد الأجهزة المتصلة: {devices}{devices_note}")
    for dev in info.get("other_devices") or []:
        extra = " — ".join(p for p in (dev.get("app"), dev.get("country")) if p)
        lines.append(f"   • {_md(dev['device'])}{(' — ' + _md(extra)) if extra else ''}")

    lines.append(f"📡 جلسة البوت: {'✅' if row.get('session_string') else '❌'}")
    if info.get("error"):
        lines += ["", f"⚠️ تعذّر التحديث المباشر: {_md(info['error'])}"]
    elif info.get("live"):
        lines += ["", "🟢 المعلومات محدّثة الآن من تيليجرام"]
    return "\n".join(lines)


def card_buttons(row: dict) -> InlineKeyboardMarkup:
    sid = row["id"]
    rows: list[list] = []
    if row.get("session_string"):
        rows += [
            [InlineKeyboardButton("🔑 آخر كود وصل", callback_data=f"os:sold_code:{sid}")],
            [InlineKeyboardButton("🚫 طرد جميع الأجهزة الأخرى", callback_data=f"os:sold_kick:{sid}")],
            [InlineKeyboardButton("🔐 عرض/تغيير 2FA", callback_data=f"os:sold_2fa:{sid}")],
        ]
    rows += [
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"os:osv:{sid}")],
        [
            InlineKeyboardButton("🔎 بحث جديد", callback_data="os:owner_search"),
            InlineKeyboardButton("🔙 المخزون", callback_data="os:manage_numbers"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def results_buttons(rows: list[dict], query_text: str = "") -> InlineKeyboardMarkup:
    buttons = []
    for r in rows:
        icon, _ = stock_status_label(r)
        label = r.get("tg_name") or r.get("tg_username") or r["phone_number"]
        buttons.append(
            [InlineKeyboardButton(f"{icon} {r['phone_number']} — {str(label)[:20]}", callback_data=f"os:osv:{r['id']}")]
        )
    buttons.append(
        [
            InlineKeyboardButton("🔎 بحث جديد", callback_data="os:owner_search"),
            InlineKeyboardButton("🔙 المخزون", callback_data="os:manage_numbers"),
        ]
    )
    return InlineKeyboardMarkup(buttons)


async def render_card(row: dict) -> tuple[str, InlineKeyboardMarkup]:
    """يبني بطاقة الحساب بعد تحديث مباشر من تيليجرام."""
    info = await fetch_live_info(row)
    fresh = get_stock_row(row["id"]) or row
    return build_card(fresh, info), card_buttons(fresh)


async def handle_owner_search_query(
    update, context, text: str, deep: bool = False, message=None
) -> None:
    """معالج النص الذي يرسله المالك بعد الضغط على زر البحث.

    ``message`` يُمرَّر عند الاستدعاء من زر (الفحص الشامل) حيث لا يوجد
    ``update.message``.
    """
    message = message or update.message
    query = normalize_search_query(text)
    back_kb = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("🔎 بحث جديد", callback_data="os:owner_search"),
            InlineKeyboardButton("🔙 المخزون", callback_data="os:manage_numbers"),
        ]]
    )
    if not query["raw"] or (query["digits"] and len(query["digits"]) < 4):
        await message.reply_text(
            "⚠️ أرسل يوزر أو ID أو اسم الحساب (أو رقم الهاتف، 4 خانات على الأقل).",
            reply_markup=back_kb,
        )
        context.user_data["state"] = "main_menu"
        return

    context.user_data["state"] = "main_menu"
    context.user_data["owner_search_last"] = query["raw"]
    status_msg = await message.reply_text("⏳ جارٍ البحث...")

    try:
        rows = search_stock_cached(query)
        scanned = 0
        if not rows:
            await status_msg.edit_text("⏳ غير موجود في الكاش — أفحص الجلسات مباشرة، قد يستغرق دقيقة...")
            rows, scanned = await live_scan(query, deep=deep)
    except Exception as exc:
        logger.exception("فشل بحث المالك عن حساب المخزون")
        await status_msg.edit_text(
            f"❌ تعذّر البحث بسبب خطأ: {str(exc)[:150]}", reply_markup=back_kb
        )
        return

    if not rows:
        buttons = []
        if not deep:
            buttons.append(
                [InlineKeyboardButton("🔬 فحص شامل لكل الجلسات", callback_data="os:owner_search_deep")]
            )
        buttons.append(
            [
                InlineKeyboardButton("🔎 بحث جديد", callback_data="os:owner_search"),
                InlineKeyboardButton("🔙 المخزون", callback_data="os:manage_numbers"),
            ]
        )
        scanned_note = f"\n(فُحصت {scanned} جلسة)" if scanned else ""
        await status_msg.edit_text(
            f"❌ لا يوجد حساب يطابق «{query['raw']}».{scanned_note}",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if len(rows) == 1:
        await status_msg.edit_text("⏳ أجلب أحدث المعلومات من تيليجرام...")
        card, kb = await render_card(rows[0])
        await status_msg.edit_text(card, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return

    await status_msg.edit_text(
        f"🔎 وجدت {len(rows)} نتيجة لـ «{query['raw']}» — اختر الحساب:",
        reply_markup=results_buttons(rows, query["raw"]),
    )
