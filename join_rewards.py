"""Part of the SMMMAIN Telegram bot.

مكافآت الانضمام للقنوات بالجواهر (قناة عادية / قناة بطلب إضافة) ولوحة تحكم
المالك بأسعارها وبأسعار الاشتراك الإجباري.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

JOIN_REWARD_SETTING = "join_channel_reward_jewels"
JOIN_REQUEST_REWARD_SETTING = "join_request_reward_jewels"
DEFAULT_JOIN_REWARD_JEWELS = Decimal("0.1")
DEFAULT_JOIN_REQUEST_REWARD_JEWELS = Decimal("0.15")
JOIN_PRICE_MAX = Decimal("1000")

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def parse_join_price(value):
    """يقرأ سعراً كسرياً بأرقام عربية/لاتينية (يقبل ٫ و ، و , كفاصلة عشرية)."""
    raw = str(value or "").strip().translate(_AR_DIGITS)
    raw = raw.replace("٫", ".").replace("،", ".").replace(",", ".")
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    amount = amount.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    if amount <= 0 or amount > JOIN_PRICE_MAX:
        return None
    return amount


def get_join_reward_jewels(is_request: bool = False) -> Decimal:
    key = JOIN_REQUEST_REWARD_SETTING if is_request else JOIN_REWARD_SETTING
    default = DEFAULT_JOIN_REQUEST_REWARD_JEWELS if is_request else DEFAULT_JOIN_REWARD_JEWELS
    return parse_join_price(get_setting(key)) or default


def channel_is_request(ch) -> bool:
    try:
        return bool(int(ch["join_request"] or 0))
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def join_leave_note() -> str:
    return (
        "\n⚠️ *ملاحظة:* إذا غادرت القناة خلال مهلة المغادرة بعد الحصول على "
        "مكافأتها فستُخصم المكافأة من رصيدك تلقائياً."
    )


def claim_join_reward(user_id: int, ch_id: int, is_request: bool):
    """يمنح مكافأة القناة مرة واحدة لكل (عضو، قناة). يعيد المبلغ أو None إن سبق استلامها."""
    amount = get_join_reward_jewels(is_request)
    with db_conn() as c:
        c.execute(
            "INSERT INTO channel_join_rewards (user_id, channel_id, joined_at, reward_jewels) "
            "VALUES (%s, %s, NOW(), %s) ON CONFLICT (user_id, channel_id) DO NOTHING",
            (user_id, ch_id, amount),
        )
        if not c.rowcount:
            return None
        updated = c.execute(
            "UPDATE users SET jewels=COALESCE(jewels,0)+%s WHERE user_id=%s RETURNING jewels",
            (amount, user_id),
        ).fetchone()
        if not updated:
            raise ValueError(f"unknown user {user_id}")
        c.execute(
            "INSERT INTO jewel_transactions (user_id,amount,transaction_type,admin_id,reference) "
            "VALUES (%s,%s,%s,%s,%s)",
            (user_id, amount, "refund", None, f"channel_join:{ch_id}"),
        )
    return amount


async def check_join_status(bot, ch, user_id: int) -> str:
    """'member' | 'requested' | 'no' | 'error'."""
    username = (ch["channel_username"] or "").lstrip("@")
    state = "error"
    try:
        member = await bot.get_chat_member(f"@{username}", user_id)
        state = "member" if member.status not in ("left", "kicked", "banned") else "no"
    except Exception:
        state = "error"
    if state == "member":
        return "member"
    if channel_is_request(ch):
        with db_conn() as c:
            row = c.execute(
                "SELECT 1 FROM channel_join_requests WHERE user_id=%s AND lower(channel_username)=%s",
                (user_id, username.lower()),
            ).fetchone()
        if row:
            return "requested"
        if state == "error":
            return "no"
    return state


async def handle_channel_join_request(update, context):
    """يسجّل طلبات الانضمام لقنوات «طلب الإضافة» ليتحقق منها البوت."""
    req = getattr(update, "chat_join_request", None)
    if not req or not req.chat:
        return
    username = (req.chat.username or "").lstrip("@").lower()
    if not username:
        return
    try:
        with db_conn() as c:
            c.execute(
                "INSERT INTO channel_join_requests (user_id, channel_username, requested_at) "
                "VALUES (%s,%s,NOW()) ON CONFLICT (user_id, channel_username) "
                "DO UPDATE SET requested_at=NOW()",
                (req.from_user.id, username),
            )
    except Exception as exc:
        logger.warning(f"handle_channel_join_request error: {exc}")


def render_join_channels_screen(user_id: int, notice: str = ""):
    with db_conn() as c:
        channels = c.execute(
            "SELECT * FROM mandatory_channels WHERE active=1 AND funding_type='internal' ORDER BY id"
        ).fetchall()
    db_user = get_user(user_id)
    balance = fmt_jewel_amount(db_user["jewels"] if db_user else 0)
    if not channels:
        return "📡 لا توجد قنوات للانضمام حالياً.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 رجوع", callback_data="collect_points")]]
        )
    normal = get_join_reward_jewels(False)
    request = get_join_reward_jewels(True)
    rows = []
    for ch in channels:
        is_req = channel_is_request(ch)
        reward = request if is_req else normal
        with db_conn() as c:
            claimed = c.execute(
                "SELECT 1 FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                (user_id, ch["id"]),
            ).fetchone()
        tag = "📨" if is_req else "📢"
        rows.append([InlineKeyboardButton(
            f"{tag} @{ch['channel_username']}",
            url=f"https://t.me/{ch['channel_username']}",
        )])
        if claimed:
            rows.append([InlineKeyboardButton("✔️ تم الحصول على جائزتك", callback_data="noop")])
        else:
            label = "✅ تحقق من طلبي" if is_req else "✅ تحقق من انضمامي"
            rows.append([InlineKeyboardButton(
                f"{label} (+{fmt_jewel_amount(reward)} 💎)",
                callback_data=f"join_verify:{ch['id']}",
            )])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="collect_points")])
    text = (
        "📡 *الانضمام بقنوات*\n\n"
        f"💎 رصيدك الحالي: {balance} جوهرة\n"
        f"📢 انضم لقناة عادية واحصل على *{fmt_jewel_amount(normal)} 💎*\n"
        f"📨 أرسل طلب إضافة لقناة (📨) واحصل على *{fmt_jewel_amount(request)} 💎*\n"
        "اضغط ✅ تحقق بعد الانضمام أو إرسال الطلب:"
        f"{join_leave_note()}"
    )
    if notice:
        text = notice + "\n\n" + text
    return text, InlineKeyboardMarkup(rows)


def render_join_prices_panel():
    normal = get_join_reward_jewels(False)
    request = get_join_reward_jewels(True)
    text = (
        "📡 *أسعار الانضمام للقنوات*\n\n"
        "💎 *مكافآت العضو (جواهر):*\n"
        f"• قناة عادية: *{fmt_jewel_amount(normal)}* جوهرة\n"
        f"• قناة بطلب إضافة: *{fmt_jewel_amount(request)}* جوهرة\n\n"
        "📨 لتحديد أي قناة هي «طلب إضافة» ادخل إدارة القنوات واضغط زر 📨 بجانبها.\n\n"
        "⭐ *أسعار الاشتراك الإجباري والتمويل:*\n"
        f"• حد أدنى (نجوم): {get_setting('mandatory_stars_min_members') or '50'} عضو\n"
        f"• حد الشريحة 1: {get_setting('mandatory_stars_tier1_max') or '120'} عضو\n"
        f"• إجباري بالنقاط: {get_setting('mandatory_points_price') or '5'} نقطة/عضو "
        f"(حد أدنى {get_setting('mandatory_points_min') or '50'})\n"
        "اضغط الأزرار أدناه للتعديل."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 سعر القناة العادية", callback_data="os:edit_join_price:normal")],
        [InlineKeyboardButton("📨 سعر طلب الإضافة", callback_data="os:edit_join_price:request")],
        [InlineKeyboardButton("📡 إدارة القنوات", callback_data="os:manage_channels")],
        [
            InlineKeyboardButton("⭐ إجباري: حد أدنى", callback_data="os:edit_mstars_min"),
            InlineKeyboardButton("⭐ إجباري: حد ش1", callback_data="os:edit_mstars_t1max"),
        ],
        [
            InlineKeyboardButton("⭐ إجباري: سعر ش1", callback_data="os:edit_mstars_t1p"),
            InlineKeyboardButton("⭐ إجباري: سعر ش2", callback_data="os:edit_mstars_t2p"),
        ],
        [
            InlineKeyboardButton("💰 إجباري-نقاط: سعر", callback_data="os:edit_mpoints_price"),
            InlineKeyboardButton("💰 إجباري-نقاط: حد أدنى", callback_data="os:edit_mpoints_min"),
        ],
        [
            InlineKeyboardButton("🔄 سعر تمويل داخلي", callback_data="os:edit_internal_cost"),
            InlineKeyboardButton("👥 حد أدنى داخلي", callback_data="os:edit_internal_min"),
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
    ])
    return text, kb


def render_manage_channels():
    with db_conn() as c:
        channels = c.execute(
            "SELECT * FROM mandatory_channels WHERE active=1 OR queued=1 ORDER BY queued ASC, id ASC"
        ).fetchall()
        fundings = {}
        for ch in channels:
            f = c.execute(
                "SELECT current_members, target_members FROM channel_funding "
                "WHERE channel_username=%s AND status='active' ORDER BY id DESC LIMIT 1",
                (ch["channel_username"],),
            ).fetchone()
            if f:
                fundings[ch["channel_username"]] = f
    if channels:
        lines = ["📡 *القنوات الحالية:*\n"]
        for ch in channels:
            tag = " ⏳ قيد الانتظار" if ch["queued"] else ""
            req = " 📨 طلب إضافة" if channel_is_request(ch) else ""
            f = fundings.get(ch["channel_username"])
            progress = f" — {f['current_members']}/{f['target_members']}" if f else ""
            lines.append(
                f"• @{md_escape(ch['channel_username'])} ({md_escape(ch['funding_type'])}){progress}{tag}{req}"
            )
    else:
        lines = ["📡 لا توجد قنوات مضافة حالياً."]
    rows = []
    for ch in channels:
        row = [InlineKeyboardButton(
            f"❌ حذف @{ch['channel_username']}", callback_data=f"os_del_ch:{ch['id']}"
        )]
        if ch["funding_type"] == "internal":
            on = channel_is_request(ch)
            row.append(InlineKeyboardButton(
                "📨 طلب إضافة: ✅" if on else "📨 طلب إضافة: ⬜",
                callback_data=f"os_ch_req:{ch['id']}",
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton("➕ إضافة قناة", callback_data="os_add_ch")])
    rows.append([InlineKeyboardButton("💎 أسعار الانضمام", callback_data="os:join_prices")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)
