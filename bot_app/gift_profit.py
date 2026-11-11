"""تقرير أرباح وخسائر إهداء المجوهرات.

كل مجوهرة يهديها المالك تُحتسب ربحاً بقيمة GIFT_PROFIT_PER_JEWEL (0.01275 افتراضياً)،
وكل مجوهرة تُخصم منه تُحتسب خسارة بنفس القيمة. الفترات:
  • آخر 24 ساعة
  • اليوم منذ الساعة 12 منتصف الليل بتوقيت العراق (Asia/Baghdad)
callback_data: gp:view:<d|w> — d=اليوم، w=آخر 7 أيام (إضافي) ؛ gp:rate لتعديل السعر.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

GIFT_PROFIT_PER_JEWEL = Decimal("0.01275")
GIFT_PROFIT_RATE_SETTING = "gift_profit_per_jewel"
GP_TZ = ZoneInfo("Asia/Baghdad")


def gp_rate() -> Decimal:
    try:
        value = Decimal(str(get_setting(GIFT_PROFIT_RATE_SETTING) or GIFT_PROFIT_PER_JEWEL))
        return value if value > 0 else GIFT_PROFIT_PER_JEWEL
    except Exception:
        return GIFT_PROFIT_PER_JEWEL


def gp_midnight_baghdad(now=None) -> datetime:
    now = (now or datetime.now(GP_TZ)).astimezone(GP_TZ)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def gp_period_stats(since: datetime):
    """يعيد (مجوهرات مهداة، مجوهرات مخصومة، عدد الإهداءات، عدد المستفيدين)."""
    with db_conn() as c:
        row = c.execute(
            """SELECT
                 COALESCE(SUM(amount) FILTER (WHERE amount > 0 AND reference = 'owner_gift'), 0) AS gifted,
                 COALESCE(-SUM(amount) FILTER (WHERE amount < 0 AND reference = 'owner_deduct'), 0) AS deducted,
                 COUNT(*) FILTER (WHERE amount > 0 AND reference = 'owner_gift') AS gifts,
                 COUNT(DISTINCT user_id) FILTER (WHERE amount > 0 AND reference = 'owner_gift') AS people
               FROM jewel_transactions
               WHERE created_at >= %s AND reference IN ('owner_gift','owner_deduct')""",
            (since,),
        ).fetchone()
    return (Decimal(str(row["gifted"] or 0)), Decimal(str(row["deducted"] or 0)),
            int(row["gifts"] or 0), int(row["people"] or 0))


def gp_fmt(value) -> str:
    return f"{Decimal(value).quantize(Decimal('0.00001')):,.5f}".rstrip("0").rstrip(".")


def gp_block(title: str, since: datetime, rate: Decimal) -> str:
    gifted, deducted, gifts, people = gp_period_stats(since)
    profit, loss = gifted * rate, deducted * rate
    net = profit - loss
    sign = "🟢" if net >= 0 else "🔴"
    return (
        f"<b>{title}</b>\n"
        f"🎁 إهداءات: {gifts} لـ {people} عضو | 💎 {gp_fmt(gifted)}\n"
        f"➖ مخصوم: 💎 {gp_fmt(deducted)}\n"
        f"💵 الربح: <b>{gp_fmt(profit)}</b> | الخسارة: <b>{gp_fmt(loss)}</b>\n"
        f"{sign} الصافي: <b>{gp_fmt(net)}</b>"
    )


def gp_report_text() -> str:
    now = datetime.now(GP_TZ)
    rate = gp_rate()
    parts = [
        "📈 <b>أرباح وخسائر الهدايا</b>",
        f"💎 كل مجوهرة = {gp_fmt(rate)}",
        gp_block("⏱ آخر 24 ساعة", now - timedelta(hours=24), rate),
        gp_block("🌙 اليوم (من 12 منتصف الليل بتوقيت العراق)", gp_midnight_baghdad(now), rate),
        gp_block("📅 آخر 7 أيام", now - timedelta(days=7), rate),
        f"🕒 {now.strftime('%Y-%m-%d %H:%M')} (بغداد)",
    ]
    return "\n\n".join(parts)


async def handle_gift_profit_callback(update, context, q, data: str, user, is_own: bool) -> bool:
    if not data.startswith("gp:") or not is_own:
        return False
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data="gp:view:d")],
        [InlineKeyboardButton("✏️ تغيير سعر المجوهرة", callback_data="gp:rate")],
        [InlineKeyboardButton("🔙 إدارة المجوهرات", callback_data="os:manage_points")],
    ])
    if data == "gp:rate":
        context.user_data["state"] = "os_await_gift_rate"
        await q.edit_message_text(
            f"✏️ أرسل السعر الجديد لربح كل مجوهرة (الحالي {gp_fmt(gp_rate())}):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="gp:view:d")]]),
        )
        return True
    try:
        text = await asyncio.to_thread(gp_report_text)
    except Exception:
        logger.exception("gift_profit report failed")
        text = "⚠️ تعذر حساب التقرير الآن."
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception as exc:
        if "not modified" not in str(exc).lower():
            await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    return True


async def handle_gift_profit_text(update, context, text: str) -> bool:
    user = update.effective_user
    if context.user_data.get("state") != "os_await_gift_rate" or user is None or user.id != OWNER_ID:
        return False
    try:
        value = Decimal(text.strip().replace(",", "."))
        if value <= 0 or value > 100:
            raise ValueError
    except Exception:
        await update.message.reply_text("⚠️ أرسل رقماً صحيحاً أكبر من صفر، مثل 0.01275")
        return True
    set_setting(GIFT_PROFIT_RATE_SETTING, str(value))
    context.user_data["state"] = "main_menu"
    await update.message.reply_text(
        f"✅ تم تحديث ربح المجوهرة إلى {gp_fmt(value)}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📈 عرض التقرير", callback_data="gp:view:d")]]),
    )
    return True
