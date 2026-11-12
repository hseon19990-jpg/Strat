"""النشر التلقائي في القناة الخاصة.

يوفر الملف ميزتين تعملان في قناة واحدة يحددها المالك:

1. كليشة كل ساعة: المالك يضيف أكثر من كليشة، والبوت ينشر واحدة كل ساعة
   بالتتابع (طابور دائري): 1 ثم 2 ثم 3 ... ثم يعود للأولى.
2. كود وهمي كل ربع ساعة: يُنشر في القناة كود بصيغة عادية (لمستخدم واحد، بقيمة
   ٣٠٠٠ نقطة قابلة للتعديل)، بدون أي زر، ولا يُعدَّل المنشور ولا يُشطب ولا يُحذف.
   هذا الكود **وهمي بالكامل**:
   - لا يُحفظ في جدول promo_codes ولا تُمنح به نقاط.
   - عندما يدخله عضو في «استخدام كود» يرد البوت بنفس رسالة الكود العادي
     المستنفد: «هذا الكود وصل للحد الأقصى من الاستخدامات».
   أما الأكواد الحقيقية التي ينشئها المالك من «إنشاء كود ترويجي» فتبقى كما هي.

كل المؤقتات محفوظة في جدول settings، فلا تتكرر المنشورات ولا تضيع بعد
إعادة تشغيل Railway.

callback_data:
  feed:*      — لوحة المالك (للمالك فقط)
حالات النص: os_await_feed_channel / os_await_feed_cliche / os_await_feed_points
"""

import secrets
import string

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

# ── مفاتيح الإعدادات ──
FEED_CHANNEL_KEY = "feed_channel_id"
FEED_CLICHE_ON_KEY = "feed_cliche_enabled"
FEED_CODE_ON_KEY = "feed_code_enabled"
FEED_CLICHES_KEY = "feed_cliches"            # JSON: قائمة نصوص HTML
FEED_NEXT_INDEX_KEY = "feed_cliche_next"
FEED_CLICHE_TS_KEY = "feed_cliche_last_ts"
FEED_CODE_TS_KEY = "feed_code_last_ts"
FEED_CODE_POINTS_KEY = "feed_code_points"

FEED_CLICHE_INTERVAL = 3600      # كل ساعة
FEED_CODE_INTERVAL = 900         # كل ربع ساعة
FEED_RETRY_AFTER_FAILURE = 300   # إعادة المحاولة بعد فشل النشر (5 دقائق)
FEED_DEFAULT_CODE_POINTS = 3000
FEED_MAX_CLICHES = 50
FEED_MAX_CLICHE_LEN = 3500

_FEED_CODE_ALPHABET = string.ascii_uppercase + string.digits
_feed_tables_ready = False


# ────────────────────────────────────────────────────────────
# الإعدادات والتخزين
# ────────────────────────────────────────────────────────────
def _feed_ensure_tables() -> None:
    global _feed_tables_ready
    if _feed_tables_ready:
        return
    with db_conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS channel_fake_codes (
            code       TEXT PRIMARY KEY,
            points     INTEGER NOT NULL,
            message_id BIGINT,
            opened_by  BIGINT,
            opened_at  TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""")
    _feed_tables_ready = True


def feed_get_channel():
    raw = (get_setting(FEED_CHANNEL_KEY) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


def feed_is_on(key: str) -> bool:
    return get_setting(key) == "1"


def feed_get_cliches() -> list:
    try:
        data = json.loads(get_setting(FEED_CLICHES_KEY) or "[]")
        return [str(x) for x in data if str(x).strip()]
    except Exception:
        return []


def feed_save_cliches(items: list) -> None:
    set_setting(FEED_CLICHES_KEY, json.dumps(items, ensure_ascii=False))


def feed_get_int(key: str, default: int = 0) -> int:
    try:
        return int(get_setting(key) or default)
    except (TypeError, ValueError):
        return default


def feed_code_points() -> int:
    value = feed_get_int(FEED_CODE_POINTS_KEY, FEED_DEFAULT_CODE_POINTS)
    return value if value > 0 else FEED_DEFAULT_CODE_POINTS


def feed_make_fake_code() -> str:
    """يولّد كوداً عشوائياً لا يطابق أي كود حقيقي موجود في البوت."""
    for _ in range(20):
        code = "".join(secrets.choice(_FEED_CODE_ALPHABET) for _ in range(10))
        with db_conn() as c:
            real = c.execute("SELECT 1 FROM promo_codes WHERE code=?", (code,)).fetchone()
            real_num = c.execute("SELECT 1 FROM number_purchase_codes WHERE code=?", (code,)).fetchone()
            fake = c.execute("SELECT 1 FROM channel_fake_codes WHERE code=?", (code,)).fetchone()
        if not (real or real_num or fake):
            return code
    raise RuntimeError("تعذر توليد كود وهمي فريد")


# ────────────────────────────────────────────────────────────
# النشر في القناة
# ────────────────────────────────────────────────────────────
def _feed_code_text(code: str, points: int) -> str:
    """منشور الكود بصيغة عادية (يُنسخ بضغطة واحدة). لا يُعدَّل ولا يُشطب بعد النشر."""
    return (
        "🎟 <b>كود ترويجي جديد!</b>\n\n"
        f"<code>{html.escape(code)}</code>\n\n"
        "👥 الحد الأقصى: 1 مستخدم\n"
        f"💰 النقاط: <b>{points:,}</b> نقطة"
    )


def feed_is_fake_code(code: str) -> bool:
    """هل هذا الكود من أكواد القناة الوهمية؟ (يستخدمها معالج «استخدام كود»)"""
    code = (code or "").strip().upper()
    if not code:
        return False
    try:
        _feed_ensure_tables()
        with db_conn() as c:
            return c.execute(
                "SELECT 1 FROM channel_fake_codes WHERE code=?", (code,)
            ).fetchone() is not None
    except Exception:
        logger.exception("feed_is_fake_code failed")
        return False


async def feed_post_next_cliche(context) -> bool:
    """ينشر الكليشة التالية في الطابور. يرجع True عند النجاح."""
    channel = feed_get_channel()
    cliches = feed_get_cliches()
    if channel is None or not cliches:
        return False
    index = feed_get_int(FEED_NEXT_INDEX_KEY, 0) % len(cliches)
    await context.bot.send_message(
        chat_id=channel,
        text=cliches[index],
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    set_setting(FEED_NEXT_INDEX_KEY, str((index + 1) % len(cliches)))
    return True


async def feed_post_fake_code(context) -> bool:
    """ينشر كوداً وهمياً مع زر الفتح. لا يُسجَّل في promo_codes أبداً."""
    channel = feed_get_channel()
    if channel is None:
        return False
    _feed_ensure_tables()
    code = feed_make_fake_code()
    points = feed_code_points()
    sent = await context.bot.send_message(
        chat_id=channel,
        text=_feed_code_text(code, points),
        parse_mode=ParseMode.HTML,
    )
    with db_conn() as c:
        c.execute(
            "INSERT INTO channel_fake_codes (code, points, message_id) VALUES (%s,%s,%s)",
            (code, points, sent.message_id),
        )
    return True


async def run_channel_feed_job(context) -> None:
    """مهمة دورية (كل 30 ثانية): تفحص المؤقتات المخزنة وتنشر عند حلول الموعد."""
    if feed_get_channel() is None:
        return
    now = int(time.time())

    if feed_is_on(FEED_CLICHE_ON_KEY) and now - feed_get_int(FEED_CLICHE_TS_KEY) >= FEED_CLICHE_INTERVAL:
        # نحجز الموعد قبل الإرسال حتى لا يتكرر المنشور إذا تداخلت دورتان.
        set_setting(FEED_CLICHE_TS_KEY, str(now))
        try:
            if not await feed_post_next_cliche(context):
                set_setting(FEED_CLICHE_TS_KEY, str(now - FEED_CLICHE_INTERVAL + FEED_RETRY_AFTER_FAILURE))
        except Exception as exc:
            logger.warning(f"⚠️ فشل نشر الكليشة في القناة: {exc}")
            set_setting(FEED_CLICHE_TS_KEY, str(now - FEED_CLICHE_INTERVAL + FEED_RETRY_AFTER_FAILURE))

    if feed_is_on(FEED_CODE_ON_KEY) and now - feed_get_int(FEED_CODE_TS_KEY) >= FEED_CODE_INTERVAL:
        set_setting(FEED_CODE_TS_KEY, str(now))
        try:
            await feed_post_fake_code(context)
        except Exception as exc:
            logger.warning(f"⚠️ فشل نشر الكود في القناة: {exc}")
            set_setting(FEED_CODE_TS_KEY, str(now - FEED_CODE_INTERVAL + FEED_RETRY_AFTER_FAILURE))


# ────────────────────────────────────────────────────────────
# لوحة المالك
# ────────────────────────────────────────────────────────────
def _feed_status_text() -> str:
    channel = feed_get_channel()
    cliches = feed_get_cliches()
    nxt = (feed_get_int(FEED_NEXT_INDEX_KEY, 0) % len(cliches) + 1) if cliches else 0
    return (
        "📣 <b>النشر التلقائي في القناة</b>\n\n"
        f"📡 القناة: <code>{html.escape(str(channel)) if channel is not None else 'غير مضبوطة ❌'}</code>\n\n"
        f"📝 كليشة كل ساعة: {'مفعّل ✅' if feed_is_on(FEED_CLICHE_ON_KEY) else 'متوقف ❌'}\n"
        f"   عدد الكليشات: {len(cliches)}"
        + (f" | التالية: رقم {nxt}" if cliches else "")
        + "\n\n"
        f"🎟 كود وهمي كل ربع ساعة: {'مفعّل ✅' if feed_is_on(FEED_CODE_ON_KEY) else 'متوقف ❌'}\n"
        f"   قيمته المعروضة: {feed_code_points():,} نقطة\n"
        "   ⚠️ وهمي: لا يُمنح به أي نقاط، ويظهر للعضو أنه مستنفد."
    )


def _feed_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 ضبط القناة", callback_data="feed:chan")],
        [
            InlineKeyboardButton("➕ إضافة كليشة", callback_data="feed:add"),
            InlineKeyboardButton("📋 الكليشات", callback_data="feed:list"),
        ],
        [
            InlineKeyboardButton(
                "📝 الكليشات: " + ("إيقاف" if feed_is_on(FEED_CLICHE_ON_KEY) else "تشغيل"),
                callback_data="feed:tc",
            ),
            InlineKeyboardButton(
                "🎟 الأكواد: " + ("إيقاف" if feed_is_on(FEED_CODE_ON_KEY) else "تشغيل"),
                callback_data="feed:tk",
            ),
        ],
        [InlineKeyboardButton("💰 نقاط الكود المعروضة", callback_data="feed:pts")],
        [InlineKeyboardButton("🚀 نشر كليشة الآن (تجربة)", callback_data="feed:now")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
    ])


async def _feed_show_menu(q=None, message=None, note: str = "") -> None:
    text = (note + "\n\n" if note else "") + _feed_status_text()
    kb = _feed_menu_kb()
    if q is not None:
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            return
        except Exception as exc:
            if "not modified" in str(exc).lower():
                return
        await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif message is not None:
        await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


def _feed_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="feed:menu")]])


async def handle_channel_feed_callback(update, context, q, data: str, user, is_own: bool) -> bool:
    if not data.startswith("feed:") or not is_own:
        return False
    action = data[len("feed:"):]

    if action == "menu":
        context.user_data["state"] = "main_menu"
        await q.answer()
        await _feed_show_menu(q=q)
        return True

    if action == "chan":
        await q.answer()
        context.user_data["state"] = "os_await_feed_channel"
        await q.edit_message_text(
            "📡 أرسل معرّف القناة (مثل @mychannel) أو رقمها (مثل -1001234567890).\n\n"
            "⚠️ يجب أن يكون البوت مشرفاً في القناة مع صلاحية نشر الرسائل.",
            reply_markup=_feed_cancel_kb(),
        )
        return True

    if action == "add":
        await q.answer()
        if len(feed_get_cliches()) >= FEED_MAX_CLICHES:
            await q.answer(f"⚠️ الحد الأقصى {FEED_MAX_CLICHES} كليشة.", show_alert=True)
            return True
        context.user_data["state"] = "os_await_feed_cliche"
        await q.edit_message_text(
            "📝 أرسل نص الكليشة الآن.\n\n"
            "يمكنك استخدام التنسيق (عريض، مائل، روابط...) وسيُنشر كما كتبته.",
            reply_markup=_feed_cancel_kb(),
        )
        return True

    if action == "list":
        await q.answer()
        cliches = feed_get_cliches()
        if not cliches:
            await q.edit_message_text(
                "📋 لا توجد كليشات بعد.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ إضافة كليشة", callback_data="feed:add")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="feed:menu")],
                ]),
            )
            return True
        nxt = feed_get_int(FEED_NEXT_INDEX_KEY, 0) % len(cliches)
        rows = []
        lines = ["📋 <b>الكليشات (بترتيب النشر)</b>\n"]
        for i, item in enumerate(cliches):
            plain = re.sub(r"<[^>]+>", "", item).replace("\n", " ")
            short = plain[:60] + ("…" if len(plain) > 60 else "")
            mark = "👉 " if i == nxt else ""
            lines.append(f"{mark}<b>{i + 1}.</b> {html.escape(short)}")
            rows.append([InlineKeyboardButton(f"🗑 حذف رقم {i + 1}", callback_data=f"feed:del:{i}")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="feed:menu")])
        await q.edit_message_text(
            "\n".join(lines) + "\n\n👉 = الكليشة التالية في الطابور",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return True

    if action.startswith("del:"):
        try:
            idx = int(action.split(":", 1)[1])
        except ValueError:
            await q.answer("⚠️ رقم غير صحيح.", show_alert=True)
            return True
        cliches = feed_get_cliches()
        if 0 <= idx < len(cliches):
            nxt = feed_get_int(FEED_NEXT_INDEX_KEY, 0)
            cliches.pop(idx)
            feed_save_cliches(cliches)
            # حافظ على موضع الطابور بعد الحذف.
            if cliches:
                if idx < nxt:
                    nxt -= 1
                set_setting(FEED_NEXT_INDEX_KEY, str(nxt % len(cliches)))
            else:
                set_setting(FEED_NEXT_INDEX_KEY, "0")
        await q.answer("🗑 تم الحذف.")
        return await handle_channel_feed_callback(update, context, q, "feed:list", user, is_own)

    if action in ("tc", "tk"):
        key = FEED_CLICHE_ON_KEY if action == "tc" else FEED_CODE_ON_KEY
        ts_key = FEED_CLICHE_TS_KEY if action == "tc" else FEED_CODE_TS_KEY
        turning_on = not feed_is_on(key)
        if turning_on and feed_get_channel() is None:
            await q.answer("⚠️ اضبط القناة أولاً.", show_alert=True)
            return True
        if turning_on and action == "tc" and not feed_get_cliches():
            await q.answer("⚠️ أضف كليشة واحدة على الأقل أولاً.", show_alert=True)
            return True
        set_setting(key, "1" if turning_on else "0")
        if turning_on:
            set_setting(ts_key, "0")  # أول منشور عند الدورة التالية مباشرة
        await q.answer("✅ تم التفعيل" if turning_on else "⏸ تم الإيقاف")
        await _feed_show_menu(q=q)
        return True

    if action == "pts":
        await q.answer()
        context.user_data["state"] = "os_await_feed_points"
        await q.edit_message_text(
            f"💰 القيمة المعروضة حالياً: {feed_code_points():,} نقطة\n\n"
            "أرسل الرقم الجديد (للعرض فقط؛ لن تُمنح هذه النقاط لأحد):",
            reply_markup=_feed_cancel_kb(),
        )
        return True

    if action == "now":
        if feed_get_channel() is None:
            await q.answer("⚠️ اضبط القناة أولاً.", show_alert=True)
            return True
        if not feed_get_cliches():
            await q.answer("⚠️ لا توجد كليشات.", show_alert=True)
            return True
        try:
            await feed_post_next_cliche(context)
            await q.answer("🚀 تم النشر في القناة.", show_alert=True)
        except Exception as exc:
            await q.answer(f"⚠️ فشل النشر: {str(exc)[:150]}", show_alert=True)
        await _feed_show_menu(q=q)
        return True

    return False


async def handle_channel_feed_text(update, context, text: str) -> bool:
    user = update.effective_user
    state = context.user_data.get("state", "")
    if user is None or user.id != OWNER_ID or not state.startswith("os_await_feed_"):
        return False
    msg = update.message

    if state == "os_await_feed_channel":
        target = text.strip()
        if re.fullmatch(r"-?\d+", target):
            target = int(target)
        elif not target.startswith("@"):
            target = "@" + target
        try:
            chat = await context.bot.get_chat(target)
            me = await context.bot.get_chat_member(chat.id, context.bot.id)
        except Exception as exc:
            await msg.reply_text(f"⚠️ تعذر الوصول للقناة: {str(exc)[:150]}\nتأكد أن البوت مشرف فيها وأعد الإرسال.")
            return True
        can_post = getattr(me, "can_post_messages", None)
        if me.status not in ("administrator", "creator") or can_post is False:
            await msg.reply_text("⚠️ البوت ليس مشرفاً بصلاحية نشر الرسائل في هذه القناة.")
            return True
        set_setting(FEED_CHANNEL_KEY, str(chat.id))
        context.user_data["state"] = "main_menu"
        await _feed_show_menu(message=msg, note=f"✅ تم ضبط القناة: {html.escape(chat.title or str(chat.id))}")
        return True

    if state == "os_await_feed_cliche":
        body = (msg.text_html or msg.caption_html or text).strip()
        if not body:
            await msg.reply_text("⚠️ أرسل نصاً.")
            return True
        if len(body) > FEED_MAX_CLICHE_LEN:
            await msg.reply_text(f"⚠️ الكليشة طويلة جداً (الحد {FEED_MAX_CLICHE_LEN} حرف).")
            return True
        items = feed_get_cliches()
        items.append(body)
        feed_save_cliches(items)
        context.user_data["state"] = "main_menu"
        await _feed_show_menu(message=msg, note=f"✅ تمت إضافة الكليشة رقم {len(items)}.")
        return True

    if state == "os_await_feed_points":
        try:
            value = int(text.strip().replace(",", ""))
            if value <= 0:
                raise ValueError
        except ValueError:
            await msg.reply_text("⚠️ أرسل رقماً صحيحاً أكبر من صفر.")
            return True
        set_setting(FEED_CODE_POINTS_KEY, str(value))
        context.user_data["state"] = "main_menu"
        await _feed_show_menu(message=msg, note=f"✅ القيمة المعروضة = {value:,} نقطة.")
        return True

    return False
