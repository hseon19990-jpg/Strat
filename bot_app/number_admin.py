"""Scoped administrators for Telegram number-stock accounts.

Number admins are deliberately separate from the owner and from supervisors.
They can use the existing account-management callbacks only for the stock
numbers assigned to their Telegram user ID.
"""

from . import shared as _shared

globals().update(
    {key: value for key, value in vars(_shared).items() if not key.startswith("__")}
)


def is_number_admin(user_id: int) -> bool:
    """Return whether a user has at least one assigned number."""
    with db_conn() as c:
        row = c.execute(
            "SELECT 1 FROM number_admins WHERE user_id=%s LIMIT 1",
            (user_id,),
        ).fetchone()
    return row is not None


def number_admin_can_manage(
    user_id: int,
    stock_id: int | None = None,
    phone_number: str | None = None,
) -> bool:
    """Check ownership of a stock number by a scoped number admin."""
    if not user_id or (stock_id is None and not phone_number):
        return False

    with db_conn() as c:
        if stock_id is not None:
            row = c.execute(
                """
                SELECT 1
                FROM number_admins na
                JOIN number_stock ns ON ns.id = na.stock_id
                WHERE na.user_id=%s
                  AND na.stock_id=%s
                  AND ns.deleted_at IS NULL
                  AND ns.assigned_to IS NULL
                LIMIT 1
                """,
                (user_id, stock_id),
            ).fetchone()
        else:
            row = c.execute(
                """
                SELECT 1
                FROM number_admins na
                JOIN number_stock ns ON ns.id = na.stock_id
                WHERE na.user_id=%s
                  AND na.phone_number=%s
                  AND ns.deleted_at IS NULL
                  AND ns.assigned_to IS NULL
                LIMIT 1
                """,
                (user_id, phone_number),
            ).fetchone()
    return row is not None


def get_number_admin_stock_rows(user_id: int) -> list[dict]:
    """Return active stock rows assigned to a number admin."""
    with db_conn() as c:
        rows = c.execute(
            """
            SELECT ns.*
            FROM number_admins na
            JOIN number_stock ns ON ns.id = na.stock_id
            WHERE na.user_id=%s
              AND ns.deleted_at IS NULL
              AND ns.assigned_to IS NULL
            ORDER BY ns.id ASC
            """,
            (user_id,),
        ).fetchall() or []
    return [dict(row) for row in rows]


def search_number_admin_stock_rows(user_id: int, query: str) -> list[dict]:
    """Search only the active stock numbers assigned to this admin.

    Searching is intentionally scoped in SQL as well as in the caller.  This
    prevents a number-admin from discovering or opening an unassigned number
    by guessing its phone number.
    """
    raw_query = str(query or "").strip()
    compact_query = raw_query.replace(" ", "").replace("-", "")
    compact_query = compact_query.translate(str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789",
    ))
    if compact_query.startswith("+"):
        compact_query = compact_query[1:]
    if not compact_query or not re.fullmatch(r"\d{1,20}", compact_query):
        return []

    with db_conn() as c:
        rows = c.execute(
            """
            SELECT ns.*
            FROM number_admins na
            JOIN number_stock ns ON ns.id = na.stock_id
            WHERE na.user_id=%s
              AND ns.deleted_at IS NULL
              AND ns.assigned_to IS NULL
              AND REPLACE(REPLACE(ns.phone_number, ' ', ''), '-', '')
                  ILIKE %s
            ORDER BY ns.id ASC
            """,
            (user_id, f"%{compact_query}%"),
        ).fetchall() or []
    return [dict(row) for row in rows]


def get_number_admins() -> list[dict]:
    """Return owners of scoped number-admin assignments with their counts."""
    with db_conn() as c:
        rows = c.execute(
            """
            SELECT na.user_id, COUNT(*) AS number_count,
                   MAX(na.added_at) AS last_added_at
            FROM number_admins na
            JOIN number_stock ns ON ns.id = na.stock_id
            WHERE ns.deleted_at IS NULL AND ns.assigned_to IS NULL
            GROUP BY na.user_id
            ORDER BY na.user_id
            """
        ).fetchall() or []
    return [dict(row) for row in rows]


def remove_number_admin(user_id: int) -> int:
    """Remove all number assignments for a user and return deleted count."""
    with db_conn() as c:
        c.execute("DELETE FROM number_admins WHERE user_id=%s", (user_id,))
        return c.rowcount


def assign_number_admin_numbers(user_id: int, raw_numbers: list[str]) -> dict:
    """Create missing stock rows and assign the submitted numbers to a user."""
    result = {
        "linked": 0,
        "created": 0,
        "duplicates": 0,
        "invalid": [],
    }
    seen: set[str] = set()

    with db_conn() as c:
        for raw in raw_numbers:
            phone = str(raw or "").strip()
            if not phone:
                continue
            if phone in seen:
                result["duplicates"] += 1
                continue
            seen.add(phone)

            compact = phone.replace(" ", "").replace("-", "")
            if not re.fullmatch(r"\+?\d{5,20}", compact):
                result["invalid"].append(phone[:80])
                continue
            phone = compact

            c.execute(
                """
                INSERT INTO number_stock (phone_number)
                VALUES (%s)
                ON CONFLICT (phone_number) DO NOTHING
                """,
                (phone,),
            )
            if c.rowcount:
                result["created"] += 1

            row = c.execute(
                "SELECT id FROM number_stock WHERE phone_number=%s",
                (phone,),
            ).fetchone()
            if not row:
                result["invalid"].append(phone)
                continue

            c.execute(
                """
                INSERT INTO number_admins (user_id, stock_id, phone_number)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, stock_id) DO NOTHING
                """,
                (user_id, row["id"], phone),
            )
            if c.rowcount:
                result["linked"] += 1
            else:
                result["duplicates"] += 1

    return result


NUMBER_ADMIN_PAGE_SIZE = 10


def number_admin_panel_markup(
    rows: list[dict],
    page: int = 0,
    total: int | None = None,
) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                f"📱 {row['phone_number']}",
                callback_data=f"na:number:{row['id']}",
            )
        ]
        for row in rows
    ]
    total = total if total is not None else len(rows)
    pages = max(1, (total + NUMBER_ADMIN_PAGE_SIZE - 1) // NUMBER_ADMIN_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    if pages > 1:
        navigation = []
        if page > 0:
            navigation.append(
                InlineKeyboardButton(
                    "⬅️ السابق",
                    callback_data=f"na:panel:{page - 1}",
                )
            )
        navigation.append(
            InlineKeyboardButton(
                f"📄 {page + 1}/{pages}",
                callback_data="noop",
            )
        )
        if page < pages - 1:
            navigation.append(
                InlineKeyboardButton(
                    "التالي ➡️",
                    callback_data=f"na:panel:{page + 1}",
                )
            )
        buttons.append(navigation)
    buttons.append(
        [InlineKeyboardButton("🔍 البحث عن رقم", callback_data="na:search")]
    )
    buttons.append(
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"na:panel:{page}")]
    )
    buttons.append(
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]
    )
    return InlineKeyboardMarkup(buttons)


def _number_admin_account_markup(
    stock_id: int,
    phone_number: str,
) -> InlineKeyboardMarkup:
    """Buttons available to an admin for one assigned number."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📋 تفاصيل الأجهزة",
                callback_data=f"os:number_devices:{stock_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "🔑 جلب آخر كود وصل",
                callback_data=f"os:number_code:{stock_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "📷 تسجيل دخول جهاز عبر QR",
                callback_data=f"os:number_qr:{stock_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "🔐 عرض / تغيير 2FA",
                callback_data=f"os:number_2fa:{stock_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "🚪 تسجيل خروج البوت",
                callback_data=f"os:number_logout:{stock_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "⏱ سماح 5 دقائق وطرد الجلسات",
                callback_data=f"os:allow_5min:{phone_number}",
            )
        ],
        [
            InlineKeyboardButton(
                "🚀 عرض الرقم للبيع الآن",
                callback_data=f"os:force_list:{stock_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "🗑 نقل الرقم إلى سلة المهملات",
                callback_data=f"os:number_delete:{stock_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 رجوع إلى أرقامك",
                callback_data="na:panel",
            )
        ],
    ])


def get_number_admin_stock_number(user_id: int, stock_id: int) -> dict | None:
    """Fetch one assigned number without opening its Telethon session."""
    with db_conn() as c:
        row = c.execute(
            """
            SELECT ns.*
            FROM number_admins na
            JOIN number_stock ns ON ns.id = na.stock_id
            WHERE na.user_id=%s
              AND na.stock_id=%s
              AND ns.deleted_at IS NULL
              AND ns.assigned_to IS NULL
            LIMIT 1
            """,
            (user_id, stock_id),
        ).fetchone()
    return dict(row) if row else None


async def render_number_admin_account(update, context, stock_id: int) -> None:
    """Render the fast, scoped account card shown after choosing a number."""
    user = update.effective_user
    rec = get_number_admin_stock_number(user.id, stock_id)
    if not rec:
        await update.callback_query.edit_message_text(
            "⚠️ هذا الرقم غير موجود أو لم يعد مخصصاً لك.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع إلى أرقامك", callback_data="na:panel")
            ]]),
        )
        return

    phone = str(rec.get("phone_number") or "غير معروف")
    session_string = str(rec.get("session_string") or "").strip()
    session_active = bool(
        session_string
        and rec.get("last_authorized") is not False
    )
    twofa_password = rec.get("twofa_password") or "غير محفوظة"
    added_at = rec.get("added_at")
    added_text = (
        format_account_datetime(added_at)
        if added_at
        else "غير معروف"
    )
    devices = rec.get("last_device_count")
    device_text = str(devices) if devices is not None and int(devices) >= 0 else "غير معروف"
    text = (
        f"📱 *{phone}*\n\n"
        f"🆔 رقم المخزون: `{rec.get('id')}`\n"
        f"🌍 الدولة: {guess_country(phone)}\n"
        f"📅 تاريخ الإضافة: {added_text}\n"
        f"🔐 كلمة مرور 2FA: `{twofa_password}`\n"
        f"📡 جلسة البوت: {'✅ نشطة' if session_active else '❌ غير نشطة'}\n"
        f"💻 الأجهزة المسجلة: {device_text}\n\n"
        "اختر الإجراء المطلوب:"
    )
    await update.callback_query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_number_admin_account_markup(stock_id, phone),
    )


async def render_number_admin_panel(
    update,
    context,
    page: int = 0,
    search_query: str | None = None,
) -> None:
    """Render the scoped number-admin panel."""
    user = update.effective_user
    all_rows = (
        search_number_admin_stock_rows(user.id, search_query)
        if search_query is not None
        else get_number_admin_stock_rows(user.id)
    )
    total = len(all_rows)
    pages = max(1, (total + NUMBER_ADMIN_PAGE_SIZE - 1) // NUMBER_ADMIN_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    rows = all_rows[
        page * NUMBER_ADMIN_PAGE_SIZE:(page + 1) * NUMBER_ADMIN_PAGE_SIZE
    ]
    if total:
        if search_query is not None:
            title = f"🔍 *نتائج البحث عن:* `{search_query}`"
            hint = "اختر رقماً من نتائج البحث:"
        else:
            title = "📱 *لوحة ادمن الأرقام*"
            hint = "اختر رقماً لعرض معلوماته وإجراءاته:"
        lines = [
            title,
            "",
            "صلاحياتك على هذه الأرقام مطابقة لصلاحيات المالك.",
            f"📦 عدد الأرقام: *{total}*",
            f"📄 الصفحة: *{page + 1}/{pages}*",
            "",
            hint,
        ]
    else:
        lines = [
            (
                f"🔍 *لا توجد نتائج للبحث عن:* `{search_query}`"
                if search_query is not None
                else "📱 *لوحة ادمن الأرقام*"
            ),
            "",
            (
                "جرّب جزءاً آخر من الرقم أو اضغط البحث من جديد."
                if search_query is not None
                else "لا توجد أرقام مخصصة لك حالياً."
            ),
        ]

    text = "\n".join(lines)
    markup = number_admin_panel_markup(rows, page=page, total=total)
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup,
        )
    else:
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup,
        )


async def render_number_admins_for_owner(update, context, note: str = "") -> None:
    """Render the owner's list of scoped number admins."""
    admins = get_number_admins()
    lines = [f"{note}\n" if note else "", "📋 *ادمن الأرقام:*", ""]
    rows = []
    if not admins:
        lines.append("لا يوجد ادمن أرقام مضاف حالياً.")
    else:
        for item in admins:
            user_id = item["user_id"]
            count = item["number_count"]
            lines.append(f"• `{user_id}` — {count} رقم")
            rows.append(
                [
                    InlineKeyboardButton(
                        f"🗑 إزالة {user_id}",
                        callback_data=f"os:remove_number_admin:{user_id}",
                    )
                ]
            )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    "➕ إضافة ادمن الأرقام",
                    callback_data="os:add_number_admin",
                )
            ],
            [InlineKeyboardButton("🔙 إعدادات المالك", callback_data="owner_settings")],
        ]
    )
    await update.callback_query.edit_message_text(
        "\n".join(line for line in lines if line != ""),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows),
    )
