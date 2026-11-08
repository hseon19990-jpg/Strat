"""Part of the SMMMAIN Telegram bot.

«دورة وهداية كبيرة» — عجلة الحظ للأعضاء.

القواعد (كما حددها المالك):
  * الجواهر والنقاط تُسلَّم تلقائياً من البوت، وأي جائزة أخرى يُبلَّغ بها المالك
    ليتواصل مع الفائز.
  * لا تُعرض النسب للأعضاء إطلاقاً.
  * دورة مجانية لكل إحالة صالحة، أو شراء دورة بنجمة/جوهرة، أو 10 دورات بـ 9.
  * «مميز» (3/6/12 شهر) و«تعزيز أسبوعي» يظهران في العجلة لكن نسبتهما 0%.
  * ضمان الجوهرة: من كل 100 دورة (عالمياً) يفوز واحد بجوهرة، أي 10 من كل 1000.
  * التعزيز اليومي: يفوز به أول 4 دورات في كل يوم (بتوقيت العراق).

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

import secrets as _secrets
from decimal import Decimal

WHEEL_BLOCK_SIZE = 100            # كل 100 دورة: جوهرة واحدة مضمونة
WHEEL_DAILY_BOOST_LIMIT = 4       # أول 4 دورات يومياً تربح التعزيز اليومي
WHEEL_IRAQ_OFFSET = timedelta(hours=3)
WHEEL_TEN_SPINS = 10
WHEEL_ROLL_SCALE = 10_000         # دقة 0.01%

# (المفتاح، الاسم الظاهر، نوع التسليم، القيمة)
#   kind: "jewels" و"points" تلقائي، "owner" يدوي عبر المالك.
WHEEL_PRIZES = {
    "premium3":      ("👑 مميز 3 شهر", "owner", 0),
    "premium6":      ("👑 مميز 6 شهر", "owner", 0),
    "premium12":     ("👑 مميز 12 شهر", "owner", 0),
    "boost_daily":   ("🚀 تعزيز يومي", "owner", 0),
    "boost_weekly":  ("🚀 تعزيز أسبوعي", "owner", 0),
    "boost_monthly": ("🚀 تعزيز شهر", "owner", 0),
    "bear":          ("🧸 دب", "owner", 0),
    "rose":          ("🌹 وردة", "owner", 0),
    "ring":          ("💍 خاتم", "owner", 0),
    "jewel":         ("💎 جوهرة", "jewels", 1),
    "jewels10":      ("💎 10 جواهر", "jewels", 10),
    "points1000":    ("⭐ 1000 نقطة", "points", 1000),
    "points50":      ("⭐ 50 نقطة", "points", 50),
}

# ترتيب العرض على العجلة.
WHEEL_DISPLAY_ORDER = (
    "premium3", "premium6", "premium12",
    "boost_daily", "boost_weekly", "boost_monthly",
    "bear", "rose", "ring",
    "jewel", "jewels10", "points1000", "points50",
)

# أوزان السحب العشوائي من 10000 (1 = 0.01%). الباقي كله «50 نقطة».
# لا يظهر هنا: المميز/التعزيز الأسبوعي (0%)، ولا الجوهرة (مضمونة بالكتلة)،
# ولا التعزيز اليومي (لأول 4 دورات في اليوم).
WHEEL_RANDOM_WEIGHTS = (
    ("ring", 1),            # 0.01%
    ("rose", 5),            # 0.05%
    ("bear", 8),            # 0.08%
    ("boost_monthly", 50),  # 0.5%
    ("jewels10", 10),       # 0.1%
    ("points1000", 7000),   # 70%
)
WHEEL_REMAINDER_PRIZE = "points50"


def wheel_pick_prize(roll: int, jewel_guarantee: bool = False, daily_boost_open: bool = False) -> str:
    """يحدد الجائزة من رقم عشوائي 0..9999 دون أي اتصال بقاعدة البيانات."""
    if jewel_guarantee:
        return "jewel"
    if daily_boost_open:
        return "boost_daily"
    total = 0
    for key, weight in WHEEL_RANDOM_WEIGHTS:
        total += weight
        if roll < total:
            return key
    return WHEEL_REMAINDER_PRIZE


class WheelEngine:
    """حالة العجلة العالمية: عدّاد الدورات، موضع الجوهرة المضمونة، وتعزيز اليوم."""

    def __init__(self, total=0, slot_block=-1, slot=0, day="", day_count=0, rng=None):
        self.total = int(total)
        self.slot_block = int(slot_block)
        self.slot = int(slot)
        self.day = str(day or "")
        self.day_count = int(day_count)
        self.rng = rng or _secrets.SystemRandom()

    def next_prize(self, today: str) -> str:
        self.total += 1
        block, position = divmod(self.total - 1, WHEEL_BLOCK_SIZE)
        if block != self.slot_block:
            # كتلة جديدة من 100 دورة: نختار عشوائياً أي دورة فيها تفوز بالجوهرة.
            self.slot_block = block
            self.slot = self.rng.randrange(WHEEL_BLOCK_SIZE)
        if today != self.day:
            self.day = today
            self.day_count = 0

        jewel_hit = position == self.slot
        boost_open = (not jewel_hit) and self.day_count < WHEEL_DAILY_BOOST_LIMIT
        prize = wheel_pick_prize(
            self.rng.randrange(WHEEL_ROLL_SCALE),
            jewel_guarantee=jewel_hit,
            daily_boost_open=boost_open,
        )
        if prize == "boost_daily":
            self.day_count += 1
        return prize


def wheel_today() -> str:
    """تاريخ اليوم بتوقيت العراق (تُصفَّر حصة التعزيز اليومي عند منتصف الليل هناك)."""
    return (datetime.now(timezone.utc) + WHEEL_IRAQ_OFFSET).date().isoformat()


def wheel_price(kind: str, count: int) -> int:
    """سعر الدورة/العشر دورات. kind: stars | jewels."""
    size = "ten" if count == WHEEL_TEN_SPINS else "spin"
    key = f"wheel_{size}_price_{kind}"
    default = 9 if size == "ten" else 1
    try:
        value = int(get_setting(key) or default)
    except (TypeError, ValueError):
        value = default
    return value if value > 0 else default


def init_wheel_tables(c) -> None:
    """ينشئ جداول العجلة ويضيف عمود الدورات المجانية."""
    c.execute("""
    CREATE TABLE IF NOT EXISTS wheel_results (
        id            BIGSERIAL PRIMARY KEY,
        user_id       BIGINT NOT NULL,
        prize_key     TEXT NOT NULL,
        prize_label   TEXT NOT NULL,
        delivery      TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'delivered',
        source        TEXT,
        spin_number   BIGINT,
        created_at    TIMESTAMPTZ DEFAULT NOW()
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS wheel_payments (
        telegram_payment_id TEXT PRIMARY KEY,
        user_id             BIGINT NOT NULL,
        stars               INTEGER NOT NULL,
        spins               INTEGER NOT NULL,
        created_at          TIMESTAMPTZ DEFAULT NOW()
    )""")


def get_wheel_spins(user_id: int) -> int:
    with db_conn() as c:
        row = c.execute("SELECT wheel_spins FROM users WHERE user_id=%s", (user_id,)).fetchone()
    return int((row or {}).get("wheel_spins") or 0)


def grant_wheel_spins(user_id: int, count: int = 1) -> int:
    with db_conn() as c:
        row = c.execute(
            "UPDATE users SET wheel_spins=COALESCE(wheel_spins,0)+%s WHERE user_id=%s RETURNING wheel_spins",
            (int(count), user_id),
        ).fetchone()
    return int((row or {}).get("wheel_spins") or 0)


def consume_wheel_spins(user_id: int, count: int) -> bool:
    """يخصم دورات من رصيد العضو بشكل ذري؛ False إن لم تكفِ."""
    with db_conn() as c:
        c.execute(
            "UPDATE users SET wheel_spins=wheel_spins-%s WHERE user_id=%s AND COALESCE(wheel_spins,0)>=%s",
            (int(count), user_id, int(count)),
        )
        return c.rowcount > 0


def _wheel_load_engine(c) -> WheelEngine:
    def _get(key, default=""):
        row = c.execute("SELECT value FROM settings WHERE key=%s", (key,)).fetchone()
        return row["value"] if row and row["value"] not in (None, "") else default

    block_s, _, slot_s = str(_get("wheel_jewel_slot", "-1:0")).partition(":")
    day_s, _, count_s = str(_get("wheel_daily_boost", ":0")).partition(":")
    return WheelEngine(
        total=int(_get("wheel_total_spins", "0") or 0),
        slot_block=int(block_s or -1),
        slot=int(slot_s or 0),
        day=day_s,
        day_count=int(count_s or 0),
    )


def _wheel_save_engine(c, engine: WheelEngine) -> None:
    for key, value in (
        ("wheel_total_spins", str(engine.total)),
        ("wheel_jewel_slot", f"{engine.slot_block}:{engine.slot}"),
        ("wheel_daily_boost", f"{engine.day}:{engine.day_count}"),
    ):
        c.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
            (key, value),
        )


def wheel_spin_once(user_id: int, source: str = "free") -> dict:
    """يدور العجلة مرة: يختار الجائزة، يسلّم الجواهر/النقاط تلقائياً، ويسجل الباقي للمالك."""
    with db_conn() as c:
        # قفل عام: عدّاد الدورات وحصة اليوم وضمان الجوهرة يجب أن تكون متسلسلة.
        c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("wheel_global",))
        engine = _wheel_load_engine(c)
        prize_key = engine.next_prize(wheel_today())
        _wheel_save_engine(c, engine)
        label, kind, value = WHEEL_PRIZES[prize_key]

        if kind == "jewels":
            c.execute(
                "UPDATE users SET jewels=COALESCE(jewels,0)+%s WHERE user_id=%s",
                (Decimal(value), user_id),
            )
            c.execute(
                "INSERT INTO jewel_transactions (user_id,amount,transaction_type,admin_id,reference) "
                "VALUES (%s,%s,'gift',NULL,%s)",
                (user_id, Decimal(value), f"wheel:{engine.total}"),
            )
            status = "delivered"
        elif kind == "points":
            c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (int(value), user_id))
            status = "delivered"
        else:
            status = "pending"

        row = c.execute(
            "INSERT INTO wheel_results (user_id,prize_key,prize_label,delivery,status,source,spin_number) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (user_id, prize_key, label, "auto" if kind != "owner" else "owner", status, source, engine.total),
        ).fetchone()
    return {
        "id": row["id"],
        "prize_key": prize_key,
        "label": label,
        "kind": kind,
        "value": value,
        "status": status,
        "spin_number": engine.total,
    }


def wheel_menu_text(include_user_spins: int | None = None) -> str:
    prizes = "\n".join(f"• {WHEEL_PRIZES[key][0]}" for key in WHEEL_DISPLAY_ORDER)
    text = (
        "🎡 *دورة وهداية كبيرة*\n\n"
        "أدر العجلة واربح إحدى الجوائز:\n\n"
        f"{prizes}\n\n"
        "💎 الجواهر و⭐ النقاط تصلك تلقائياً، وأي جائزة أخرى تتواصل مع المالك لاستلامها.\n"
        "🎟 تحصل على دورة مجانية عن كل إحالة جديدة."
    )
    if include_user_spins is not None:
        text += f"\n\n🎟 دوراتك المجانية: *{include_user_spins}*"
    return text


def wheel_menu_kb(free_spins: int) -> InlineKeyboardMarkup:
    rows = []
    if free_spins > 0:
        rows.append([InlineKeyboardButton(f"🎡 استخدم دورة مجانية ({free_spins})", callback_data="wheel:free:1")])
        if free_spins >= WHEEL_TEN_SPINS:
            rows.append([InlineKeyboardButton("🎡 استخدم 10 دورات مجانية", callback_data="wheel:free:10")])
    one_s, one_j = wheel_price("stars", 1), wheel_price("jewels", 1)
    ten_s, ten_j = wheel_price("stars", 10), wheel_price("jewels", 10)
    rows.append([
        InlineKeyboardButton(f"🎡 دورة بـ {one_s} ⭐", callback_data="wheel:buy:stars:1"),
        InlineKeyboardButton(f"🎡 دورة بـ {one_j} 💎", callback_data="wheel:buy:jewels:1"),
    ])
    rows.append([
        InlineKeyboardButton(f"🎡 10 دورات بـ {ten_s} ⭐", callback_data="wheel:buy:stars:10"),
        InlineKeyboardButton(f"🎡 10 دورات بـ {ten_j} 💎", callback_data="wheel:buy:jewels:10"),
    ])
    rows.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def _wheel_result_line(result: dict) -> str:
    if result["kind"] == "owner":
        return f"{result['label']} — 📩 تواصل مع المالك لاستلامها"
    return f"{result['label']} — ✅ أُضيفت تلقائياً"


def wheel_results_text(results: list) -> str:
    if len(results) == 1:
        r = results[0]
        if r["kind"] == "owner":
            return (
                f"🎉 *مبروك! ربحت {r['label']}*\n\n"
                "📩 هذه الجائزة تُسلَّم يدوياً، تواصل مع المالك لاستلامها.\n"
                f"🔖 رقم الجائزة: `{r['id']}`"
            )
        return f"🎉 *مبروك! ربحت {r['label']}*\n\n✅ أُضيفت إلى رصيدك تلقائياً."
    lines = ["🎡 *نتائج دوراتك:*\n"]
    lines += [f"{i}. {_wheel_result_line(r)}" for i, r in enumerate(results, 1)]
    owner_ids = [str(r["id"]) for r in results if r["kind"] == "owner"]
    if owner_ids:
        lines.append("\n📩 تواصل مع المالك لاستلام الجوائز اليدوية، أرقامها: " + "، ".join(f"`{i}`" for i in owner_ids))
    return "\n".join(lines)


async def _wheel_notify_owner(context, user, result: dict) -> None:
    """إشعار المالك بجائزة تحتاج تسليماً يدوياً."""
    name = html.escape(getattr(user, "full_name", None) or str(user.id))
    username = f"@{user.username}" if getattr(user, "username", None) else "—"
    text = (
        "🎡 <b>فوز في دورة وهداية كبيرة</b>\n\n"
        f"👤 <a href='tg://user?id={user.id}'>{name}</a> ({username})\n"
        f"🆔 <code>{user.id}</code>\n"
        f"🎁 الجائزة: <b>{html.escape(result['label'])}</b>\n"
        f"🔖 رقم الجائزة: <code>{result['id']}</code>\n\n"
        "⚠️ جائزة يدوية: تواصل مع الفائز لتسليمها."
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تم التسليم", callback_data=f"wheel:done:{result['id']}")
    ]])
    try:
        await notify_group(context.application, text)
    except Exception:
        logger.exception("تعذر إرسال إشعار فوز العجلة إلى كروب الإدارة")
    if OWNER_ID:
        try:
            await context.bot.send_message(OWNER_ID, text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            logger.exception("تعذر إرسال إشعار فوز العجلة إلى المالك")


async def wheel_run_spins(context, user, count: int, source: str, message=None) -> list:
    """يدور `count` دورات من رصيد العضو (يُفترض أنه اكتسبها/دفعها) ويعيد النتائج."""
    results = []
    try:
        for _ in range(count):
            results.append(wheel_spin_once(user.id, source))
    except Exception:
        # لو تعثرت الدورات نعيد ما لم يُدَر إلى رصيد العضو بدل ضياعه.
        remaining = count - len(results)
        if remaining > 0:
            grant_wheel_spins(user.id, remaining)
        logger.exception("تعثرت دورة العجلة للمستخدم %s", user.id)
        if not results:
            raise
    for result in results:
        if result["kind"] == "owner":
            await _wheel_notify_owner(context, user, result)
    return results


async def _wheel_animate(message) -> None:
    """رسوم بسيطة قبل إظهار النتيجة (لا تكشف أي نسب)."""
    frames = [WHEEL_PRIZES[k][0] for k in ("bear", "points1000", "jewel", "ring", "points50", "rose")]
    for frame in frames[:4]:
        try:
            await message.edit_text(f"🎡 العجلة تدور...\n\n➡️ {frame}")
        except Exception:
            return
        await asyncio.sleep(0.6)


async def _wheel_show_results(context, q, user, results, is_own) -> None:
    free_left = get_wheel_spins(user.id)
    rows = []
    if any(r["kind"] == "owner" for r in results):
        rows += contact_owner_row()
    rows.append([InlineKeyboardButton("🎡 دورة أخرى", callback_data="wheel:menu")])
    rows.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")])
    text = wheel_results_text(results)
    if free_left:
        text += f"\n\n🎟 دوراتك المجانية المتبقية: *{free_left}*"
    await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows))


async def handle_wheel_callback(update, context, q, data, user, is_own) -> bool:
    """يعالج أزرار العجلة؛ يعيد True إن كان الزر لها."""
    if not data.startswith("wheel:"):
        return False
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else "menu"

    if action == "menu":
        context.user_data["state"] = "main_menu"
        free = get_wheel_spins(user.id)
        await q.edit_message_text(
            wheel_menu_text(free), parse_mode=ParseMode.MARKDOWN, reply_markup=wheel_menu_kb(free)
        )
        return True

    if action == "done" and is_own:
        try:
            result_id = int(parts[2])
        except (IndexError, ValueError):
            await q.answer("⚠️ رقم غير صالح.", show_alert=True)
            return True
        with db_conn() as c:
            c.execute(
                "UPDATE wheel_results SET status='delivered_by_owner' WHERE id=%s AND status='pending'",
                (result_id,),
            )
            changed = c.rowcount
        await q.answer("✅ سُجّل التسليم." if changed else "ℹ️ سبق تسجيل التسليم.", show_alert=False)
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return True

    if action == "free":
        try:
            count = int(parts[2])
        except (IndexError, ValueError):
            count = 1
        if count not in (1, WHEEL_TEN_SPINS) or not consume_wheel_spins(user.id, count):
            await q.answer("⚠️ ليس لديك دورات مجانية كافية.", show_alert=True)
            return True
        await q.answer()
        if count == 1:
            await _wheel_animate(q.message)
        results = await wheel_run_spins(context, user, count, "free")
        await _wheel_show_results(context, q, user, results, is_own)
        return True

    if action == "buy" and len(parts) == 4:
        pay_with, count_s = parts[2], parts[3]
        try:
            count = int(count_s)
        except ValueError:
            count = 0
        if pay_with not in ("stars", "jewels") or count not in (1, WHEEL_TEN_SPINS):
            await q.answer("⚠️ خيار غير صالح.", show_alert=True)
            return True

        if pay_with == "stars":
            stars = wheel_price("stars", count)
            await q.answer("✅ جارٍ تجهيز فاتورة النجوم.")
            try:
                await context.bot.send_invoice(
                    chat_id=user.id,
                    title="دورة وهداية كبيرة",
                    description=f"{count} دورة على عجلة الحظ مقابل {stars} نجمة",
                    payload=f"wheel_stars:{count}:{user.id}:{stars}",
                    provider_token="",
                    currency="XTR",
                    prices=[LabeledPrice("دورات العجلة", stars)],
                )
            except Exception:
                logger.exception("تعذر إرسال فاتورة العجلة للمستخدم %s", user.id)
                await q.message.reply_text("⚠️ تعذر إنشاء فاتورة النجوم الآن. حاول لاحقاً.")
            return True

        price = wheel_price("jewels", count)
        if deduct_jewels(user.id, price, reference=f"wheel_buy:{count}") is None:
            await q.answer(
                f"❌ جواهرك غير كافية! تحتاج {price} 💎 ورصيدك {fmt_jewel_amount(get_user_jewels(user.id))}.",
                show_alert=True,
            )
            return True
        await q.answer()
        try:
            if count == 1:
                await _wheel_animate(q.message)
            results = await wheel_run_spins(context, user, count, "jewels")
        except Exception:
            add_jewels(user.id, price, reference=f"wheel_buy_refund:{count}")
            await q.edit_message_text(
                "⚠️ تعذر تشغيل العجلة، أُعيدت جواهرك إلى رصيدك.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="wheel:menu")]]),
            )
            return True
        await _wheel_show_results(context, q, user, results, is_own)
        return True

    await q.answer()
    return True


def validate_wheel_invoice(payload, user_id, total_amount, currency):
    """يعيد عدد الدورات فقط إذا كانت فاتورة النجوم مطابقة للمستخدم والسعر."""
    parts = str(payload or "").split(":")
    if (
        len(parts) != 4
        or parts[0] != "wheel_stars"
        or not all(p.isdigit() for p in parts[1:])
        or currency != "XTR"
    ):
        return None
    count, uid, stars = int(parts[1]), int(parts[2]), int(parts[3])
    if count not in (1, WHEEL_TEN_SPINS) or uid != int(user_id) or stars < 1 or stars != int(total_amount):
        return None
    return count


async def wheel_pre_checkout(update, context):
    query = update.pre_checkout_query
    ok = validate_wheel_invoice(
        query.invoice_payload, query.from_user.id, query.total_amount, query.currency
    ) is not None
    if ok:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="حدث خطأ في التحقق من الدفع.")


async def wheel_successful_payment(update, context):
    """بعد دفع النجوم: تُسجَّل الدفعة مرة واحدة ثم تُدار الدورات فوراً."""
    payment = update.message.successful_payment
    user = update.effective_user
    is_own = user.id == OWNER_ID
    count = validate_wheel_invoice(payment.invoice_payload, user.id, payment.total_amount, payment.currency)
    charge_id = payment.telegram_payment_charge_id
    if count is None:
        logger.error("دفعة عجلة غير مطابقة: user=%s payload=%s", user.id, payment.invoice_payload)
        try:
            credited = _credit_star_payment_as_jewels_once(
                user.id, payment.total_amount, charge_id or f"update:{update.update_id}"
            )
            await update.message.reply_text(
                f"⚠️ لم تتطابق بيانات الفاتورة؛ {'أُضيفت' if credited else 'سبق إضافة'} "
                f"{fmt_jewel_amount(payment.total_amount)} جواهر إلى رصيدك."
            )
        except Exception:
            logger.exception("تعذر تعويض دفعة عجلة غير مطابقة")
            await update.message.reply_text("⚠️ تعذّر التحقق من الدفعة؛ أبلغت المالك لمراجعتها.")
            await _notify_owner_manual_star_purchase(
                context,
                f"⚠️ دفعة عجلة غير مطابقة. المستخدم: {user.id}، العملية: {charge_id}، "
                f"الحمولة: {payment.invoice_payload}",
            )
        return

    with db_conn() as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"wheel-pay:{charge_id}",))
        inserted = c.execute(
            "INSERT INTO wheel_payments (telegram_payment_id,user_id,stars,spins) "
            "VALUES (%s,%s,%s,%s) ON CONFLICT (telegram_payment_id) DO NOTHING RETURNING telegram_payment_id",
            (charge_id, user.id, int(payment.total_amount), count),
        ).fetchone()
    if not inserted:
        await update.message.reply_text(
            "✅ تمت معالجة هذه الدفعة مسبقاً.", reply_markup=main_menu_kb(is_own)
        )
        return

    try:
        results = await wheel_run_spins(context, user, count, "stars")
    except Exception:
        grant_wheel_spins(user.id, count)
        await update.message.reply_text(
            "⚠️ تعذر تشغيل العجلة الآن؛ أُضيفت دوراتك إلى رصيدك لتستخدمها لاحقاً.",
            reply_markup=main_menu_kb(is_own),
        )
        return
    rows = []
    if any(r["kind"] == "owner" for r in results):
        rows += contact_owner_row()
    rows.append([InlineKeyboardButton("🎡 دورة أخرى", callback_data="wheel:menu")])
    rows.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")])
    await update.message.reply_text(
        wheel_results_text(results), parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows)
    )
