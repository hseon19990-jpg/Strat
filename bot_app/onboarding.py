"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

import asyncio

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

MANDATORY_MAX_ACTIVE = 10   # الحد الأقصى لعدد القنوات الإجبارية النشطة في نفس الوقت
MANDATORY_PAGE_SIZE   = 5   # عدد القنوات المعروضة للمستخدم دفعة واحدة في بوابة الاشتراك

def count_active_mandatory_channels() -> int:
    with db_conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM mandatory_channels WHERE active=1 AND funding_type='mandatory'"
        ).fetchone()
    return row["n"] if row else 0

async def promote_queued_mandatory_channel(context: ContextTypes.DEFAULT_TYPE, app=None):
    """يُستدعى بعد أي إخراج لقناة إجبارية من القائمة النشطة (اكتمال تمويلها أو تعطيلها يدوياً).
    إن وُجدت قناة إجبارية بانتظار الدور (queued=1) وتوفّر عدد أقل من الحد الأقصى، تُفعَّل تلقائياً
    وتُخطَر مالكها ويُعلَن عنها في الكروب، حتى لا يبقى دور القناة معلّقاً بلا داعٍ."""
    if count_active_mandatory_channels() >= MANDATORY_MAX_ACTIVE:
        return
    with db_conn() as c:
        nxt = c.execute(
            "SELECT * FROM mandatory_channels WHERE queued=1 AND funding_type='mandatory' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if not nxt:
            return
        c.execute("UPDATE mandatory_channels SET active=1, queued=0 WHERE id=%s", (nxt["id"],))

    try:
        await context.bot.send_message(
            nxt["owner_user_id"],
            f"🎉 *أصبحت قناتك الآن ضمن قائمة الاشتراك الإجباري!*\n\n"
            f"📢 القناة: @{nxt['channel_username']}\n"
            f"✅ تحرّر أحد الأماكن العشرة فأصبح دور قناتك، وباتت تظهر الآن لجميع مستخدمي البوت.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        pass


def mandatory_terms_text_html() -> str:
    """نص الشروط المرفق مع أي إعلان في الكروب عن قناة إجبارية جديدة (HTML)."""
    penalty = int(get_setting("channel_leave_penalty") or "75")
    return (
        f"📌 <b>الشروط:</b>\n"
        f"• الاشتراك بهذه القناة أصبح إجبارياً لاستخدام البوت.\n"
        f"• الحد الأقصى للقنوات الإجبارية النشطة في نفس الوقت: {MANDATORY_MAX_ACTIVE} قنوات.\n"
        f"• مغادرة القناة بعد التحقق تخصم {penalty} نقطة تلقائياً من رصيد المستخدم."
    )

async def get_unjoined_mandatory_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """يُرجع قائمة القنوات الإجبارية التي لم ينضم لها المستخدم بعد.

    المالك مستثنى دائماً من بوابة الاشتراك حتى يستطيع إدارة القنوات،
    بما فيها حذف قناة غير صالحة أو لم يعد بالإمكان الانضمام إليها.
    """
    if user_id == OWNER_ID:
        return []
    with db_conn() as c:
        channels = c.execute(
            "SELECT * FROM mandatory_channels WHERE active=1 AND funding_type='mandatory'"
        ).fetchall()
    # This semaphore lives in bot_data so concurrent /start requests share
    # one limit instead of each opening up to ten Telegram API calls.
    check_semaphore = context.bot_data.setdefault(
        "_mandatory_channel_check_semaphore",
        asyncio.Semaphore(10),
    )

    async def check_channel(ch):
        try:
            # Do not let a slow or invalid channel make /start appear dead.
            # Fail closed: an unverifiable channel remains in the gate.
            async with check_semaphore:
                member = await asyncio.wait_for(
                    context.bot.get_chat_member(
                        f"@{ch['channel_username']}",
                        user_id,
                    ),
                    timeout=8,
                )
            return ch if member.status in ("left", "kicked", "banned") else None
        except Exception as exc:
            logger.warning(
                "تعذر التحقق من اشتراك المستخدم %s في @%s: %s",
                user_id,
                ch.get("channel_username", ""),
                exc,
            )
            return ch

    checked = await asyncio.gather(*(check_channel(ch) for ch in channels))
    return [channel for channel in checked if channel is not None]

async def count_user_for_fundings(user_id: int, context):
    """
    تحسب هذا المستخدم ضمن التمويلات النشطة التي لم يُحسب فيها بعد.
    الشرط: يجب أن يكون المستخدم قد انضم عبر البوت (سجل في channel_join_rewards).
    عند اكتمال أي تمويل: يُوقَف تلقائياً ويُرسَل إشعار لصاحبه.
    """
    with db_conn() as c:
        fundings = c.execute(
            """SELECT cf.id, cf.channel_username, cf.funding_type,
                      cf.target_members, cf.current_members, cf.user_id AS owner_id,
                      mc.id AS mc_id
               FROM channel_funding cf
               JOIN mandatory_channels mc ON mc.channel_username = cf.channel_username
               WHERE mc.active = 1 AND cf.status = 'active' AND cf.target_members > 0"""
        ).fetchall()

    for f in fundings:
        if f["funding_type"] == "internal":
            with db_conn() as c:
                verified = c.execute(
                    "SELECT 1 FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                    (user_id, f["mc_id"])
                ).fetchone()
            if not verified:
                continue
        else:
            try:
                member = await context.bot.get_chat_member(f"@{f['channel_username']}", user_id)
                if member.status in ("left", "kicked", "banned"):
                    continue
            except Exception:
                continue
        with db_conn() as c:
            c.execute(
                "INSERT INTO channel_funding_counts (user_id, funding_id) VALUES (%s, %s) "
                "ON CONFLICT (user_id, funding_id) DO NOTHING",
                (user_id, f["id"])
            )
            if c.rowcount == 0:
                continue
            c.execute(
                "UPDATE channel_funding SET current_members = current_members + 1 WHERE id = %s",
                (f["id"],)
            )
            row = c.execute(
                "SELECT current_members, target_members FROM channel_funding WHERE id = %s",
                (f["id"],)
            ).fetchone()

        if not row:
            continue
        if row["current_members"] >= row["target_members"]:
            with db_conn() as c:
                c.execute("UPDATE channel_funding SET status='completed' WHERE id=%s", (f["id"],))
                c.execute("UPDATE mandatory_channels SET active=0 WHERE channel_username=%s", (f["channel_username"],))
            try:
                ft_label = "إجباري سريع" if f["funding_type"] == "mandatory" else "داخلي بطيء"
                await context.bot.send_message(
                    chat_id=f["owner_id"],
                    text=(
                        f"🎉 *اكتمل تمويل قناتك!*\n\n"
                        f"📢 القناة: @{f['channel_username']}\n"
                        f"⚙️ النوع: {ft_label}\n"
                        f"👥 العدد المستهدف: {f['target_members']:,} عضو — ✅ تم الوصول!"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
            if f["funding_type"] == "mandatory":
                await promote_queued_mandatory_channel(context)

def mandatory_join_kb(channels, is_owner=False):
    page = channels[:MANDATORY_PAGE_SIZE]
    rows = []
    for ch in page:
        rows.append([InlineKeyboardButton(
            f"📢 {ch['channel_title'] or ('@' + ch['channel_username'])}",
            url=f"https://t.me/{ch['channel_username']}"
        )])
    rows.append([InlineKeyboardButton("✅ متابعة بعد الاشتراك", callback_data="check_mandatory_join")])
    if is_owner:
        rows.append([InlineKeyboardButton("⏭ تخطى (للمالك فقط)", callback_data="skip_mandatory_gate")])
    return InlineKeyboardMarkup(rows)

async def show_mandatory_gate(update: Update, context: ContextTypes.DEFAULT_TYPE, channels, edit=False, is_owner=False):
    remaining = max(0, len(channels) - MANDATORY_PAGE_SIZE)
    more_note = (
        f"\n\n➕ يوجد *{remaining}* قناة إضافية ستظهر تلقائياً بعد إكمال هذه المجموعة."
        if remaining > 0 else ""
    )
    text = (
        "📢 *الاشتراك الإجباري*\n\n"
        "للمتابعة، يجب عليك الاشتراك بالقنوات التالية أولاً:\n"
        "ثم اضغط «✅ تحقق من الاشتراك»."
        f"{more_note}"
    )
    kb = mandatory_join_kb(channels, is_owner=is_owner)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

# ────────────────────────────────────────────────────────────
# تحقق المدعوّين: كل عضو جديد دخل عبر رابط دعوة يمرّ بهذا التسلسل بالضبط قبل
# احتساب الإحالة:
#   انضمام بالقنوات ← ستارت ← تحقق حسابي ← ستارت ← تحقق إيموجي ← ستارت ← تُحتسب.
# «ستارت» = زر ▶️ ستارت أو إرسال /start.
# ────────────────────────────────────────────────────────────
import secrets as _rc_secrets

REFERRAL_BURST_COUNT = 3          # عدد المدعوّين المشبوه
REFERRAL_BURST_SECONDS = 60       # خلال هذه المدة
REFERRAL_CHALLENGE_MAX_FAILS = 3  # أخطاء متتالية قبل القفل المؤقت
REFERRAL_CHALLENGE_LOCK_MINUTES = 10
REFERRAL_CHALLENGE_EMOJIS = ("🍎", "🐱", "🚗", "⚽", "🌙", "🔑", "🎈", "🐟", "🍕", "🌵")


def referral_burst_hit(timestamps, mine, count=REFERRAL_BURST_COUNT, seconds=REFERRAL_BURST_SECONDS) -> bool:
    """هل توجد نافذة طولها `seconds` ثانية تضم وقت دخول هذا المدعو وتحوي `count` مدعوّين أو أكثر؟"""
    times = sorted(float(t) for t in timestamps)
    mine = float(mine)
    for start in times:
        if start <= mine <= start + seconds:
            inside = sum(1 for t in times if start <= t <= start + seconds)
            if inside >= count:
                return True
    return False


def make_math_challenge(rng=None):
    """يعيد (a, b, الخيارات, فهرس الجواب الصحيح) لمسألة جمع بأربعة خيارات."""
    rng = rng or _rc_secrets.SystemRandom()
    a, b = rng.randint(3, 19), rng.randint(3, 19)
    correct = a + b
    options = {correct}
    while len(options) < 4:
        wrong = correct + rng.choice([-5, -4, -3, -2, -1, 1, 2, 3, 4, 5])
        if wrong > 0:
            options.add(wrong)
    options = list(options)
    rng.shuffle(options)
    return a, b, options, options.index(correct)


def make_emoji_challenge(rng=None):
    """يعيد (الإيموجيات الستة، فهرس الإيموجي المطلوب)."""
    rng = rng or _rc_secrets.SystemRandom()
    options = rng.sample(list(REFERRAL_CHALLENGE_EMOJIS), 6)
    return options, rng.randrange(len(options))


_rc_table_ready = False


def _rc_ensure_table(c) -> None:
    global _rc_table_ready
    if _rc_table_ready:
        return
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS referral_challenges (
            user_id      BIGINT PRIMARY KEY,
            stage        TEXT NOT NULL DEFAULT 'math',
            prompt       TEXT NOT NULL DEFAULT '',
            options      TEXT NOT NULL DEFAULT '',
            target_idx   INTEGER NOT NULL DEFAULT 0,
            fails        INTEGER NOT NULL DEFAULT 0,
            passed       INTEGER NOT NULL DEFAULT 0,
            locked_until TIMESTAMPTZ,
            created_at   TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    _rc_table_ready = True


def referral_challenge_enabled() -> bool:
    return (get_setting("referral_challenge_enabled") or "1").strip() != "0"


def referral_burst_detected(user_id: int) -> bool:
    """يفحص هل دخل هذا المدعو ضمن 3+ مدعوّين لنفس الداعي خلال دقيقة."""
    with db_conn() as c:
        row = c.execute("SELECT invited_by FROM users WHERE user_id=%s", (user_id,)).fetchone()
        inviter = int((row or {}).get("invited_by") or 0)
        if not inviter or inviter == user_id or inviter == OWNER_ID:
            return False
        me = c.execute("SELECT first_seen_at FROM first_seen WHERE user_id=%s", (user_id,)).fetchone()
        if not me:
            return False
        rows = c.execute(
            "SELECT f.first_seen_at AS t FROM users u "
            "JOIN first_seen f ON f.user_id=u.user_id "
            "WHERE u.invited_by=%s "
            "AND f.first_seen_at BETWEEN %s - (%s * INTERVAL '1 second') "
            "AND %s + (%s * INTERVAL '1 second')",
            (inviter, me["first_seen_at"], REFERRAL_BURST_SECONDS,
             me["first_seen_at"], REFERRAL_BURST_SECONDS),
        ).fetchall()
    stamps = [r["t"].timestamp() for r in rows]
    return referral_burst_hit(stamps, me["first_seen_at"].timestamp())


def _rc_new_stage(stage: str):
    """يولّد سؤال المرحلة ويعيد (نص السؤال، الخيارات كسلسلة، فهرس الصحيح)."""
    if stage == "math":
        a, b, options, idx = make_math_challenge()
        return f"{a} + {b}", ",".join(str(o) for o in options), idx
    options, idx = make_emoji_challenge()
    return options[idx], ",".join(options), idx


def _rc_render(stage: str, prompt: str, options: str, note: str = ""):
    opts = options.split(",")
    if stage == "math":
        text = f"🔐 *تحقق أمني (1/2)*\n\n{note}ما ناتج: *{prompt}* ؟"
        rows = [[InlineKeyboardButton(o, callback_data=f"rc:math:{i}") for i, o in enumerate(opts)]]
    else:
        text = f"🔐 *تحقق أمني (2/2)*\n\n{note}اضغط على هذا الإيموجي: {prompt}"
        buttons = [InlineKeyboardButton(o, callback_data=f"rc:emoji:{i}") for i, o in enumerate(opts)]
        rows = [buttons[:3], buttons[3:]]
    return text, InlineKeyboardMarkup(rows)


_RC_GATE_TEXT = {
    "gate1": "✅ *تم الاشتراك في القنوات*\n\nاضغط ▶️ *ستارت* للانتقال إلى التحقق الحسابي.",
    "gate2": "✅ *تم حل التحقق الحسابي*\n\nاضغط ▶️ *ستارت* للانتقال إلى تحقق الإيموجي.",
    "gate3": "✅ *تم حل تحقق الإيموجي*\n\nاضغط ▶️ *ستارت* لإكمال الدخول وتفعيل حسابك.",
}
_RC_GATE_STAGES = tuple(_RC_GATE_TEXT)


def _rc_gate_render(stage: str):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("▶️ ستارت", callback_data="rc:go")]])
    return _RC_GATE_TEXT[stage], kb


async def _rc_send(update, text, kb=None, edit=False):
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


_RC_LOCK_TEXT = (
    f"⛔ *تعذّر التحقق*\n\nأخطأت عدة مرات. حاول مجدداً بعد "
    f"{REFERRAL_CHALLENGE_LOCK_MINUTES} دقائق بإرسال /start."
)


async def _rc_set_stage(user_id: int, stage: str, new_question: bool = False):
    """ينقل المدعو لمرحلة جديدة ويعيد (النص، الأزرار) لعرضها."""
    if stage in _RC_GATE_STAGES:
        with db_conn() as c:
            c.execute(
                "UPDATE referral_challenges SET stage=%s, fails=0 WHERE user_id=%s",
                (stage, user_id),
            )
        return _rc_gate_render(stage)
    prompt, options, idx = _rc_new_stage(stage)
    with db_conn() as c:
        c.execute(
            "UPDATE referral_challenges SET stage=%s, prompt=%s, options=%s, "
            "target_idx=%s, fails=0 WHERE user_id=%s",
            (stage, prompt, options, idx, user_id),
        )
    return _rc_render(stage, prompt, options)


async def _rc_advance(update, context, user, edit=False) -> bool:
    """يعالج ضغطة «ستارت». يعيد True إذا عُرضت مرحلة جديدة، و False إذا اكتملت كل المراحل."""
    with db_conn() as c:
        _rc_ensure_table(c)
        row = c.execute(
            "SELECT * FROM referral_challenges WHERE user_id=%s", (user.id,)
        ).fetchone()
    if not row or row["passed"]:
        return False
    stage = row["stage"]
    if stage == "gate1":
        text, kb = await _rc_set_stage(user.id, "math")
    elif stage == "gate2":
        text, kb = await _rc_set_stage(user.id, "emoji")
    elif stage == "gate3":
        with db_conn() as c:
            c.execute("UPDATE referral_challenges SET passed=1 WHERE user_id=%s", (user.id,))
        return False
    else:
        text, kb = _rc_render(stage, row["prompt"], row["options"])
    await _rc_send(update, text, kb, edit=edit)
    return True


async def start_referral_challenge_if_needed(update, context, user, edit=False, from_start=False) -> bool:
    """يعيد True إذا عُرضت خطوة تحقق (أو قفل) على المدعو وعلى المتصل التوقف.

    from_start=True تعني أن المدعو أرسل /start، فتُحتسب ضغطة «ستارت» إن كان
    واقفاً عند إحدى بوابات «ستارت».
    """
    if user.id == OWNER_ID or not referral_challenge_enabled():
        return False
    db_user = get_user(user.id) or {}
    if (
        not db_user
        or db_user.get("verified", 0)
        or not (db_user.get("invited_by") or 0)
        or db_user.get("referral_credited")
    ):
        return False
    with db_conn() as c:
        _rc_ensure_table(c)
        state = c.execute(
            "SELECT *, (locked_until IS NOT NULL AND locked_until > NOW()) AS locked "
            "FROM referral_challenges WHERE user_id=%s",
            (user.id,),
        ).fetchone()
    if state and state["passed"]:
        return False
    if state and state["locked"]:
        await _rc_send(update, _RC_LOCK_TEXT, None, edit=edit)
        return True
    if not state:
        # أول مرة بعد الاشتراك في القنوات: بوابة «ستارت» الأولى.
        with db_conn() as c:
            c.execute(
                "INSERT INTO referral_challenges (user_id,stage,prompt,options,target_idx,fails,passed,locked_until) "
                "VALUES (%s,'gate1','','',0,0,0,NULL) "
                "ON CONFLICT (user_id) DO UPDATE SET stage='gate1', prompt='', options='', "
                "target_idx=0, fails=0, passed=0, locked_until=NULL",
                (user.id,),
            )
        text, kb = _rc_gate_render("gate1")
        await _rc_send(update, text, kb, edit=edit)
        return True
    if state["stage"] in _RC_GATE_STAGES:
        if from_start:
            return await _rc_advance(update, context, user, edit=edit)
        text, kb = _rc_gate_render(state["stage"])
        await _rc_send(update, text, kb, edit=edit)
        return True
    # وسط سؤال: نعيد عرض السؤال نفسه.
    text, kb = _rc_render(state["stage"], state["prompt"], state["options"])
    await _rc_send(update, text, kb, edit=edit)
    return True


async def handle_referral_challenge_callback(update, context, q, data, user) -> None:
    """أزرار التحقق: rc:go (ستارت) ثم rc:math:<i> و rc:emoji:<i>."""
    parts = data.split(":")
    if len(parts) >= 2 and parts[1] == "go":
        with db_conn() as c:
            _rc_ensure_table(c)
            row = c.execute(
                "SELECT *, (locked_until IS NOT NULL AND locked_until > NOW()) AS locked "
                "FROM referral_challenges WHERE user_id=%s",
                (user.id,),
            ).fetchone()
        if not row:
            await q.answer("انتهت صلاحية التحقق. أرسل /start من جديد.", show_alert=True)
            return
        if row["passed"]:
            await proceed_after_mandatory(update, context, edit=True)
            return
        if row["locked"]:
            await q.edit_message_text(_RC_LOCK_TEXT, parse_mode=ParseMode.MARKDOWN)
            return
        if row["stage"] not in _RC_GATE_STAGES:
            return  # زر ستارت قديم
        shown = await _rc_advance(update, context, user, edit=True)
        if not shown:
            await proceed_after_mandatory(update, context, edit=True)
        return
    try:
        stage, picked = parts[1], int(parts[2])
    except (IndexError, ValueError):
        return
    with db_conn() as c:
        _rc_ensure_table(c)
        row = c.execute(
            "SELECT *, (locked_until IS NOT NULL AND locked_until > NOW()) AS locked "
            "FROM referral_challenges WHERE user_id=%s",
            (user.id,),
        ).fetchone()
    if not row or row["passed"]:
        await q.answer("انتهت صلاحية التحقق. أرسل /start من جديد.", show_alert=True)
        return
    if row["locked"]:
        await q.edit_message_text(_RC_LOCK_TEXT, parse_mode=ParseMode.MARKDOWN)
        return
    if stage != row["stage"]:
        return  # زر قديم من مرحلة سابقة

    if picked == int(row["target_idx"]):
        next_gate = "gate2" if stage == "math" else "gate3"
        text, kb = await _rc_set_stage(user.id, next_gate)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return

    fails = int(row["fails"]) + 1
    if fails >= REFERRAL_CHALLENGE_MAX_FAILS:
        with db_conn() as c:
            c.execute(
                "UPDATE referral_challenges SET stage='gate1', fails=0, "
                "locked_until=NOW() + (%s * INTERVAL '1 minute') WHERE user_id=%s",
                (REFERRAL_CHALLENGE_LOCK_MINUTES, user.id),
            )
        await q.edit_message_text(_RC_LOCK_TEXT, parse_mode=ParseMode.MARKDOWN)
        return
    prompt, options, idx = _rc_new_stage(stage)
    with db_conn() as c:
        c.execute(
            "UPDATE referral_challenges SET prompt=%s, options=%s, target_idx=%s, fails=%s WHERE user_id=%s",
            (prompt, options, idx, fails, user.id),
        )
    text, kb = _rc_render(stage, prompt, options, note="❌ إجابة خاطئة، حاول مرة أخرى.\n\n")
    await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def proceed_after_mandatory(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False, from_start=False):
    """يكمل الدخول ويحتسب الإحالة بعد الاشتراك في كل القنوات الإلزامية."""
    user = update.effective_user
    unjoined = (
        await get_unjoined_mandatory_channels(context, user.id)
        if user.id != OWNER_ID
        else []
    )
    if unjoined:
        context.user_data["state"] = "await_mandatory_join"
        await show_mandatory_gate(
            update,
            context,
            unjoined,
            edit=edit,
            is_owner=user.id == OWNER_ID,
        )
        return

    if await start_referral_challenge_if_needed(
        update, context, user, edit=edit, from_start=from_start
    ):
        return

    await finalize_verification(update, context, user, edit=edit, skip_referral=False)

REFERRAL_FRAUD_MESSAGE = (
    "⚠️ *إشعار من الإدارة*\n\n"
    "تم رصد مخالفة لشروط الاستخدام على حسابك، وعليه تم تصفير رصيدك "
    "وإلغاء طلباتك الجارية دون تعويض.\n\n"
    "هذا القرار نهائي.\n\n"
    "إدارة البوت"
)


async def _handle_referral_fraud(context, user, info: dict) -> None:
    """ينفّذ بقية عقوبة الغش: إيقاف الطلبات الجارية، إشعار الداعي، وإبلاغ المالك."""
    inviter_id = int(info["inviter_id"])
    # أمر الإلغاء لدى موقع الرشق (إن كان يدعمه) — أفضل جهد دون أي تعويض
    for panel, api_order_id, _code in info.get("smm_cancelled", []):
        if not api_order_id:
            continue
        try:
            await asyncio.to_thread(smm_request, "cancel", panel=panel, orders=str(api_order_id))
        except Exception as exc:
            logger.warning(f"⚠️ تعذر طلب إلغاء {api_order_id} لدى موقع الرشق: {exc}")
    raksh_cancelled = 0
    try:
        from .raksh_system.raksh_system import _cancel_user_raksh_order
        for order_id in info.get("raksh_order_ids", []):
            try:
                result = await asyncio.to_thread(
                    _cancel_user_raksh_order, inviter_id, int(order_id), True
                )
                if result.get("status") == "cancelled":
                    raksh_cancelled += 1
            except Exception as exc:
                logger.warning(f"⚠️ تعذر إلغاء طلب الرشق {order_id}: {exc}")
    except Exception as exc:
        logger.warning(f"⚠️ تعذر تحميل إلغاء طلبات الرشق: {exc}")
    try:
        await context.bot.send_message(
            chat_id=inviter_id, text=REFERRAL_FRAUD_MESSAGE, parse_mode=ParseMode.MARKDOWN
        )
    except Exception as exc:
        logger.warning(f"⚠️ فشل إرسال إشعار الغش للمستخدم {inviter_id}: {exc}")
    if OWNER_ID:
        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=(
                    "🛡 حماية الإحالات: تم رصد انضمام جماعي في ثانية واحدة\n"
                    f"👤 الداعي: {inviter_id}\n"
                    f"🆔 المدعو: {user.id}\n"
                    f"📡 انضم في {info['joined']} من {info['total']} قنوات إجبارية معاً\n"
                    f"💰 النقاط قبل التصفير: {info['points_before']:,}\n"
                    f"💎 الجواهر قبل التصفير: {fmt_referral_amount('jewels', info['jewels_before'])}\n"
                    f"🧾 طلبات موقع الرشق الملغاة: {len(info.get('smm_cancelled', []))}\n"
                    f"⚙️ طلبات خدمات الرشق الملغاة: {raksh_cancelled}"
                ),
            )
        except Exception as exc:
            logger.warning(f"⚠️ فشل إبلاغ المالك بحالة الغش: {exc}")


async def _notify_referral_credit(context, user, credited) -> str:
    """إشعار الداعي بعد منح النقاط، ويعيد النص الذي يظهر للمدعو."""
    fraud_info = context.user_data.pop("referral_fraud", None)
    if fraud_info:
        await _handle_referral_fraud(context, user, fraud_info)
        return ""
    if not credited:
        return ""

    invited_by, rp = credited
    reward_type = context.user_data.pop("referral_reward_type", None) or get_referral_reward_type()
    upper_rewards = context.user_data.pop("referral_upper_rewards", None) or []
    reward_text = fmt_referral_amount(reward_type, rp)
    free_minutes = int(context.user_data.pop("referral_reward_granted_minutes", 0) or 0)
    free_note = (
        f"\n🎁 حصلت أيضاً على 250 حساب رشق مجاني خلال {free_minutes} دقيقة "
        f"(ما زاد عن 250 يُدفع، وما لم يُستخدم يسقط بانتهاء المدة، ولا يشمل بعض الخدمات)."
        if free_minutes > 0
        else ""
    )
    invited_name = md_escape(
        f"@{user.username}" if user.username else user.full_name or "مستخدم"
    )
    inviter_row = get_user(invited_by)
    inviter_name = "صديقك"
    if inviter_row:
        inviter_username = inviter_row.get("username")
        inviter_full_name = inviter_row.get("full_name")
        inviter_name = md_escape(
            f"@{inviter_username}"
            if inviter_username
            else inviter_full_name or "صديقك"
        )
    try:
        await context.bot.send_message(
            chat_id=invited_by,
            text=(
                f"🎉 مبروك! أكمل المستخدم {invited_name} "
                f"شرط الإحالة عبر رابط دعوتك، وحصلت على {reward_text}."
                "\n🎡 وحصلت أيضاً على دورة مجانية في «دورة وهداية كبيرة»."
                f"{free_note}"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as exc:
        logger.warning(f"⚠️ فشل إرسال إشعار الإحالة للمستخدم {invited_by}: {exc}")
    for upper_id, upper_level, upper_amount in upper_rewards:
        try:
            await context.bot.send_message(
                chat_id=upper_id,
                text=(
                    f"🎉 مبروك! انضم عضو جديد ضمن شبكة دعواتك (المستوى {upper_level})، "
                    f"وحصلت على {fmt_referral_amount(reward_type, upper_amount)}."
                ),
            )
        except Exception as exc:
            logger.warning(f"⚠️ فشل إرسال إشعار مستوى الإحالة {upper_level} للمستخدم {upper_id}: {exc}")
    return f"\n\n🔗 لقد دخلت إلى رابط دعوة صديقك {inviter_name} وقد حصل على {reward_text}."


async def _notify_referral_rejected_no_username(context, user):
    """يُشعر كروب الطلبات (مرة واحدة) بأن إحالة المدعو رُفضت لأنه بلا يوزر."""
    inviter_id = context.user_data.pop("referral_rejected_no_username", None)
    if not inviter_id:
        return
    db_user = get_user(user.id) or {}
    try:
        await notify_invited_without_username(
            context.bot, user, int(inviter_id), db_user.get("bot_user_num")
        )
    except Exception:
        logger.exception("❌ تعذر إشعار كروب الطلبات برفض الإحالة")


async def finalize_verification(update: Update, context: ContextTypes.DEFAULT_TYPE, user, edit=False, skip_referral=False):
    """يُفعّل المستخدم بعد الاشتراك الإجباري، ويمنح مكافأة الإحالة مرة واحدة."""
    set_user_verified(user.id)
    try:
        await count_user_for_fundings(user.id, context)
    except Exception:
        # فشل تحديث تمويل قناة لا يجب أن يمنع احتساب إحالة مكتملة.
        logger.exception("فشل تحديث تمويلات القنوات أثناء إنهاء التحقق")
    is_own = (user.id == OWNER_ID)

    credited = (
        credit_referral_if_pending(user.id, context)
        if not skip_referral
        else None
    )
    await _notify_referral_rejected_no_username(context, user)
    referral_note = await _notify_referral_credit(context, user, credited)

    context.user_data["state"] = "main_menu"
    db_user = get_user(user.id)
    pts = db_user["points"] if db_user else 0
    welcome = get_setting("welcome_message") or "أهلاً بك!"
    text = f"✅ *تم الدخول بنجاح!*\n\n{welcome}\n\n💰 رصيدك: {pts} نقطة{referral_note}"
    menu_kb = main_menu_kb(
        is_own,
        is_supervisor_user=is_supervisor(user.id) and not is_own,
        is_number_admin_user=(not is_own and is_number_admin(user.id)),
    )
    kb = menu_kb
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb
        )
    else:
        await update.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb
        )
    return credited

async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يبدأ تدفّق المستخدم الجديد مع اشتراط القنوات الإلزامية فقط."""
    await proceed_after_mandatory(update, context, edit=False, from_start=True)

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
async def _cmd_start_impl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    requested_invited_by = int(args[0]) if args and args[0].isdigit() else 0
    invited_by = requested_invited_by if requested_invited_by != user.id else 0

    previous_user = get_user(user.id) or {}
    # وقت أول /start للمستخدم الجديد، يطلبه بوت الإيميلات للتحقق من الجدة.
    if not previous_user:
        try:
            record_first_seen(user.id)
        except Exception:
            logger.exception("❌ تعذر تسجيل وقت أول فتح للمستخدم")
    previous_invited_by = previous_user.get("invited_by") or 0
    db_user = get_or_create_user(user.id, user.username or "", user.full_name or "", invited_by)
    is_own = (user.id == OWNER_ID)
    referral_link_just_opened = should_notify_referral_link_opened(
        previous_invited_by,
        invited_by,
        db_user.get("invited_by") or 0,
        user.id,
    )

    # المدعو بلا يوزر: تُرفض الإحالة نهائياً ويصل إشعار سرّي لكروب الطلبات والمالك فقط
    # (لا يعلم الداعي ولا المدعو). لا تُحتسب حتى لو أضاف يوزراً لاحقاً.
    if not (user.username or "").strip():
        invitee_inviter = int(db_user.get("invited_by") or 0)
        if invitee_inviter and invitee_inviter != user.id:
            try:
                newly_rejected = reject_referral_no_username(user.id)
            except Exception:
                logger.exception("❌ تعذر رفض إحالة المدعو بلا يوزر")
                newly_rejected = False
            if newly_rejected:
                asyncio.create_task(
                    notify_invited_without_username(
                        context.bot, user, invitee_inviter, db_user.get("bot_user_num")
                    ),
                    name=f"nouser-invite-{user.id}",
                )
        referral_link_just_opened = False
    if referral_link_just_opened:
        await notify_referral_link_opened(context.bot, user, invited_by)

    # عضو جديد لأول مرة: أشعر كروب الأعضاء الجدد (إن كان مضبوطاً) وبيّن إن دعاه أحد.
    if not previous_user:
        asyncio.create_task(
            notify_new_user_group(
                context.bot,
                user,
                db_user.get("invited_by") or 0,
                db_user.get("bot_user_num"),
            ),
            name=f"new-user-group-{user.id}",
        )

    # ─── فحص الحظر في /start ──────────────────────────
    if not is_own and is_user_banned(user.id):
        await update.message.reply_text("🚫 تم حظرك من استخدام هذا البوت.")
        return

    if is_maintenance_on() and not is_own:
        await update.message.reply_text(MAINTENANCE_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return

    if db_user.get("verified", 0):
        unjoined = await get_unjoined_mandatory_channels(context, user.id)
        if unjoined:
            context.user_data["state"] = "await_mandatory_join"
            await show_mandatory_gate(update, context, unjoined, edit=False, is_owner=is_own)
            return
        context.user_data["state"] = "main_menu"
        welcome = get_setting("welcome_message") or "أهلاً بك!"
        credited = credit_referral_if_pending(user.id, context)
        await _notify_referral_rejected_no_username(context, user)
        referral_note = await _notify_referral_credit(context, user, credited)
        db_user = get_user(user.id)
        pts = db_user["points"] if db_user else 0
        await update.message.reply_text(
            f"👋 *أهلاً بك مجدداً!*\n\n{welcome}\n\n💰 رصيدك: {pts} نقطة"
            f"{referral_note}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(
                is_own,
                is_number_admin_user=(not is_own and is_number_admin(user.id)),
            )
        )
        async def refresh_fundings():
            try:
                await count_user_for_fundings(user.id, context)
            except Exception:
                logger.exception("فشل تحديث تمويلات القنوات أثناء /start")

        # This bookkeeping performs extra Telegram checks. It must not delay
        # the welcome menu or make a healthy /start look unresponsive.
        asyncio.create_task(
            refresh_fundings(),
            name=f"refresh-fundings-{user.id}",
        )
        return

    await update.message.reply_text(
        (
            "👋 *أهلاً بك!*"
            + (
                "\n\n🔗 تم فتح رابط دعوة صديقك.\n"
                "اشترك في جميع القنوات الإلزامية حتى تُحتسب الإحالة."
                if referral_link_just_opened
                else ""
            )
        ),
        parse_mode=ParseMode.MARKDOWN,
    )
    await start_onboarding(update, context)

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start without silently dropping it on a preflight error."""
    try:
        await _cmd_start_impl(update, context)
    except Exception:
        user = update.effective_user
        logger.exception(
            "❌ فشل تنفيذ /start للمستخدم %s",
            getattr(user, "id", "unknown"),
        )
        message = update.effective_message
        if message is not None:
            try:
                await message.reply_text(
                    "⚠️ تعذر فتح القائمة الآن بسبب تأخر مؤقت في الخدمة. "
                    "أرسل /start مرة أخرى بعد لحظات."
                )
            except Exception:
                logger.exception("❌ تعذر إرسال رسالة الخطأ الخاصة بـ /start")

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == OWNER_ID:
        await update.message.reply_text(
            "⚙️ *لوحة المالك:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return
    if is_supervisor(user.id):
        await update.message.reply_text(
            "🛡 *لوحة المشرف:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=supervisor_panel_kb()
        )
        return
    await update.message.reply_text("⛔ هذا الأمر للمالك والمشرفين فقط.")

async def cmd_import_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /import_session <session_string> — يستورد جلسة قديمة ويضيف رقمها للمخزون."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    if not context.args:
        await update.message.reply_text(
            "الاستخدام:\n`/import_session SESSION_STRING`\n\nالصق رمز الجلسة بعد الأمر.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    session_str = context.args[0].strip()
    session_str = _maybe_convert_session(session_str)
    msg = await update.message.reply_text("⏳ جاري التحقق من الجلسة...")
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        await msg.edit_text("❌ متغيرات TELEGRAM_API_ID أو TELEGRAM_API_HASH غير مضبوطة.")
        return
    try:
        client = TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            await client.disconnect()
            await msg.edit_text("❌ الجلسة منتهية الصلاحية أو غير صالحة. لا يمكن الاستيراد.")
            return
        me = await client.get_me()
        phone = me.phone if me.phone.startswith("+") else f"+{me.phone}"
        await client.disconnect()
        with db_conn() as c:
            existing = c.execute(
                "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
            ).fetchone()
            if existing:
                c.execute(
                    "UPDATE number_stock SET session_string=%s, assigned_to=NULL, assigned_at=NULL,"
                    " forced_ref_excluded=FALSE WHERE phone_number=%s",
                    (session_str, phone)
                )
                action = "تم تحديث"
            else:
                c.execute(
                    "INSERT INTO number_stock (phone_number, session_string, forced_ref_excluded)"
                    " VALUES (%s, %s, FALSE)",
                    (phone, session_str)
                )
                action = "تمت إضافة"
        await msg.edit_text(
            f"✅ *{action} الرقم بنجاح!*\n\n📱 الرقم: `{phone}`\n\n"
            "الرقم الآن أُضيف تلقائياً لقائمة إحالة بوت إجباري وجاهز للاستخدام.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await msg.edit_text(f"❌ خطأ أثناء الاستيراد:\n`{e}`", parse_mode=ParseMode.MARKDOWN)

async def cmd_import_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /import_sessions — استيراد جماعي للجلسات عبر JSON."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    _pending_bulk_import.add(user.id)
    context.user_data["state"] = "os_bulk_import"
    await update.message.reply_text(
        "📥 *استيراد جماعي للحسابات*\n\n"
        "أرسل JSON بالصيغة التالية:\n\n"
        "```\n"
        '["SESSION1", "SESSION2", "SESSION3"]\n'
        "```\n\n"
        "أو مع أرقام (اختياري):\n\n"
        "```\n"
        '[{"session": "SESSION1", "phone": "+212xxxxxxx"},\n'
        ' {"session": "SESSION2"}]\n'
        "```",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_import_hex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /import_hex — استيراد جلسات بصيغة hex_auth_key:dc_id (سطر لكل حساب)."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    context.user_data["state"] = "os_import_hex"
    await update.message.reply_text(
        "📥 *استيراد حسابات بصيغة hex:dc*\n\n"
        "الصيغة المتوقعة — سطر واحد لكل حساب:\n"
        "`<auth_key_hex>:<dc_id>`\n\n"
        "مثال:\n"
        "`12f6766c...3f04b:5`\n\n"
        "الـ dc\\_id يكون 1-5 (الرقم بعد النقطتين).\n"
        "أرسل النص الآن (أو /cancel للإلغاء).",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_mass_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /mass_reset
    يقرأ ملفات الجلسة لكل الحسابات غير المباعة ويطرد جميع الجلسات الأخرى.
    الحسابات المباعة (ever_sold=TRUE) تُتخطى تماماً — خارج نطاق البوت.
    """
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        await update.message.reply_text("❌ متغيرات API_ID / API_HASH غير مضبوطة.")
        return

    # ─── جلب كل الحسابات غير المباعة التي لديها ملف جلسة ──────────────────
    with db_conn() as _c:
        rows = _c.execute(
            "SELECT id, phone_number, session_string FROM number_stock "
            "WHERE ever_sold IS NOT TRUE "
            "  AND session_string IS NOT NULL"
        ).fetchall()

    total = len(rows)
    if total == 0:
        await update.message.reply_text("ℹ️ لا يوجد حسابات غير مباعة لديها ملف جلسة.")
        return

    status_msg = await update.message.reply_text(
        f"⏳ بدأ إعادة قراءة الملفات وطرد الجلسات...\n"
        f"📦 إجمالي الحسابات: *{total}*\n"
        f"⏱️ الرجاء الانتظار...",
        parse_mode=ParseMode.MARKDOWN
    )

    done, kicked_ok, already_solo, failed, kicked_out = 0, 0, 0, 0, 0

    for rec in rows:
        rec = dict(rec)
        phone = rec["phone_number"]
        _client = None
        try:
            _client = TelegramClient(
                StringSession(rec["session_string"]),
                int(TELEGRAM_API_ID), TELEGRAM_API_HASH
            )
            await _client.connect()

            if not await _client.is_user_authorized():
                kicked_out += 1
                with db_conn() as _cx:
                    _cx.execute(
                        "UPDATE number_stock SET last_authorized=FALSE, kicked_at=CASE WHEN last_authorized IS FALSE THEN kicked_at ELSE NOW() END WHERE id=%s",
                        (rec["id"],)
                    )
                continue

            # ── طرد كل الجلسات الأخرى ─────────────────────────────────
            try:
                await _client(ResetAuthorizationsRequest())
                kicked_ok += 1
            except Exception as _re:
                logger.debug(f"mass_reset: ResetAuth فشل للرقم {phone}: {_re}")
                failed += 1

            # ── فحص ما إذا كان البوت الجلسة الوحيدة ─────────────────────
            _dev = -1
            try:
                _dev = await get_device_count(_client)
            except Exception:
                pass
            _is_solo_r = (_dev == 1)
            if _is_solo_r:
                already_solo += 1

            # ── تسجيل IP الجلسة الجديدة بعد الطرد ────────────────────────
            _new_ip = None
            try:
                _new_ip = await get_session_ip(_client)
            except Exception:
                pass

            with db_conn() as _cx:
                _cx.execute(
                    "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s, "
                    "last_authorized=TRUE, bot_session_ip=%s WHERE id=%s",
                    (_is_solo_r, _new_ip, rec["id"])
                )

            # ── تفعيل can_send_code إذا أصبح منفرداً ─────────────────────
            if _is_solo_r:
                asyncio.create_task(
                    _test_and_set_can_send_code(phone, rec["session_string"], rec["id"])
                )

        except Exception as _e:
            logger.warning(f"mass_reset: خطأ على الرقم {phone}: {_e}")
            failed += 1
        finally:
            if _client:
                try:
                    await _client.disconnect()
                except Exception:
                    pass
            done += 1

            # ── تحديث رسالة التقدم كل 5 حسابات ──────────────────────────
            if done % 5 == 0 or done == total:
                try:
                    await status_msg.edit_text(
                        f"⏳ جاري المعالجة... {done}/{total}\n\n"
                        f"✅ طُردت جلساته: *{kicked_ok}*\n"
                        f"🔒 كان منفرداً أصلاً: *{already_solo}*\n"
                        f"⛔ جلسة منتهية: *{kicked_out}*\n"
                        f"❌ فشل: *{failed}*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass

    # ─── رسالة النتيجة النهائية ──────────────────────────────────────────
    await status_msg.edit_text(
        f"✅ *اكتملت عملية إعادة القراءة والطرد الجماعي*\n\n"
        f"📦 إجمالي الحسابات المعالجة: *{total}*\n"
        f"🔐 نجح الطرد (ResetAuthorizations): *{kicked_ok}*\n"
        f"🔒 كان منفرداً مسبقاً (solo): *{already_solo}*\n"
        f"⛔ جلسة منتهية الصلاحية: *{kicked_out}*\n"
        f"❌ فشل الاتصال أو الطرد: *{failed}*\n\n"
        f"🚫 الحسابات المباعة: *لم تُمسّ* (خارج النطاق)",
        parse_mode=ParseMode.MARKDOWN
    )
    logger.info(
        f"mass_reset مكتمل | total={total} kicked={kicked_ok} "
        f"solo={already_solo} expired={kicked_out} failed={failed}"
    )

async def cmd_addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /addpoints <user_id> [points].
    يقبل المعرف وحده ثم يطلب عدد النقاط في رسالة مستقلة.
    """
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return

    args = context.args
    if len(args) not in (1, 2):
        await update.message.reply_text(
            "الاستخدام:\n"
            "/addpoints <user_id> [points]\n\n"
            "مثال مباشر: `/addpoints 123456789 500`\n"
            "أو أرسل المعرف أولاً ثم عدد النقاط.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("⚠️ تأكد أن معرف المستخدم رقم صحيح.")
        return

    target = get_user(target_id)
    if not target:
        await update.message.reply_text("⚠️ لا يوجد مستخدم بهذا المعرف في قاعدة البيانات.")
        return

    if len(args) == 1:
        begin_owner_flow(
            context,
            "points",
            "os_await_points_amount",
            points_target_id=target_id,
            points_mode="give",
        )
        await update.message.reply_text(
            f"👤 المستخدم: {target.get('full_name') or target_id}\n"
            f"🆔 المعرف: `{target_id}`\n"
            f"💰 الرصيد الحالي: {target.get('points', 0)} نقطة\n\n"
            "أرسل عدد النقاط الآن (رقم موجب):",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # لا تترك مسار سعر/خدمة قديمًا فعالاً بعد تنفيذ الأمر المباشر.
    reset_owner_flow(context)

    try:
        pts = int(args[1])
    except ValueError:
        await update.message.reply_text("⚠️ تأكد أن عدد النقاط رقم صحيح.")
        return

    if pts == 0:
        await update.message.reply_text("⚠️ عدد النقاط لا يمكن أن يكون صفراً.")
        return

    if pts > 0:
        add_points(target_id, pts)
        actual = pts
    else:
        actual = -deduct_points_clamped(target_id, -pts)

    await update.message.reply_text(f"✅ تم تعديل رصيد المستخدم {target_id} بمقدار {actual} نقطة.")

    try:
        if actual > 0:
            await context.bot.send_message(target_id, f"💰 تم إضافة {actual} نقطة إلى رصيدك من قبل الإدارة.")
        elif actual < 0:
            await context.bot.send_message(target_id, f"⚠️ تم خصم {-actual} نقطة من رصيدك من قبل الإدارة.")
    except Exception:
        pass

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
async def cmd_grant_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /grant_ref <invited_user_id>
    يمنح نقاط الإحالة للداعي في حال كانت ضائعة (referral_credited=1 لكن النقاط لم تُمنح فعلاً).
    يستخدم لتصحيح حالات سببها مايغريشن قديم وضع referral_credited=1 بدون منح نقاط.
    """
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return

    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "📋 *الاستخدام:*\n`/grant_ref <user_id_المدعو>`\n\n"
            "يمنح نقاط الإحالة للداعي إن كانت لم تُمنح سابقاً.\n\n"
            "💡 *للعثور على الإحالات الضائعة:*\n"
            "ابحث عن مستخدمين عندهم `invited_by != 0` وتم تسجيلهم قبل تفعيل نظام النقاط.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    invited_user_id = int(args[0])

    with db_conn() as c:
        row = c.execute(
            "SELECT user_id, invited_by, referral_credited, full_name, username FROM users WHERE user_id=?",
            (invited_user_id,)
        ).fetchone()

    if not row:
        await update.message.reply_text(f"⚠️ لا يوجد مستخدم بالمعرف {invited_user_id} في قاعدة البيانات.")
        return

    invited_by = row["invited_by"]
    if not invited_by or invited_by == 0:
        await update.message.reply_text(f"⚠️ المستخدم {invited_user_id} لم يدخل عبر رابط دعوة (invited_by=0).")
        return

    inviter = get_user(invited_by)
    if not inviter:
        await update.message.reply_text(f"⚠️ الداعي (ID: {invited_by}) غير موجود في قاعدة البيانات.")
        return

    rp = int(get_setting("referral_points") or "30")

    with db_conn() as c:
        c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (rp, invited_by))
        c.execute(
            "UPDATE users SET referral_credited=1, credited_at=COALESCE(credited_at, NOW()) WHERE user_id=%s",
            (invited_user_id,)
        )

    invited_name = row.get("username") or row.get("full_name") or str(invited_user_id)
    inviter_name = inviter.get("username") or inviter.get("full_name") or str(invited_by)

    await update.message.reply_text(
        f"✅ *تم منح نقاط الإحالة الضائعة*\n\n"
        f"👤 المدعو: @{invited_name} (`{invited_user_id}`)\n"
        f"🎁 الداعي: @{inviter_name} (`{invited_by}`) ← حصل على {rp} نقطة\n"
        f"💰 رصيد الداعي الآن: {inviter['points'] + rp} نقطة",
        parse_mode=ParseMode.MARKDOWN
    )

    try:
        await context.bot.send_message(
            chat_id=invited_by,
            text=f"🎉 تم تصحيح إحالة ضائعة! حصلت على {rp} نقطة بسبب دعوة المستخدم {invited_name}."
        )
    except Exception:
        pass

# ────────────────────────────────────────────────────────────
