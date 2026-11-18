"""تدقيق المؤجّرين: أدوات للمالك للتحقق من ادعاء عضو أُنهيت حساباته المؤجَّرة.

ما يفعله هذا الملف:
  * تقرير لكل عضو: حساباته، حالة كل حساب، توقيت الطرد، أرباحه، ومؤشرات
    تساعد على الحكم هل ادعاؤه منطقي أم لا (مؤشرات وليست حكماً قاطعاً).
  * فحص حي لجلسات البوت على حساباته (هل ما زالت حيّة؟ وهل جهازه ما زال داخلاً؟).
  * مراقبة دورية تسجّل توقيت كل تغيير في حالة أي حساب مؤجَّر وتنبّه المالك.
  * إجراءات المالك: إيقاف حسابات العضو داخل البوت، حظره، ملاحظات، تصحيح حالة خاطئة.

مهم: كل الإجراءات هنا تعمل داخل البوت فقط. لا شيء منها يسجّل خروجاً من حساب
تيليجرام ولا يغيّر كلمة مروره ولا إعداداته.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

# ───────────────────────── الجزء النقي (قابل للاختبار بدون قاعدة بيانات) ─────────────────────────
# PURE-START
import html as _html
from datetime import datetime as _datetime, timedelta as _timedelta, timezone as _timezone

_IQ_TZ = _timezone(_timedelta(hours=3))

MA_STATE_LABEL = {
    "alive": "✅ شغال",
    "dead": "🚫 مطرود (جلسة البوت ميتة)",
    "frozen": "🧊 مجمّد من تيليجرام",
    "excluded": "⛔ مستبعد من الرشق",
    "removed": "🗑 محذوف",
}


def ma_account_state(row) -> str:
    """حالة حساب مؤجَّر من أعمدة number_stock (نفس منطق البوت في فقدان الجلسة)."""
    if row.get("deleted_at"):
        return "removed"
    if row.get("frozen_at"):
        return "frozen"
    if row.get("raksh_excluded"):
        return "excluded"
    if row.get("last_authorized") is False or not row.get("has_session"):
        return "dead"
    return "alive"


def ma_mask_phone(phone) -> str:
    digits = str(phone or "").strip().lstrip("+")
    if len(digits) <= 7:
        return "+" + digits[:2] + "***"
    return "+" + digits[:4] + "****" + digits[-3:]


def ma_fmt_dt(value) -> str:
    if not value:
        return "—"
    try:
        return value.astimezone(_IQ_TZ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)[:16]


def ma_fmt_span(delta) -> str:
    try:
        seconds = int(delta.total_seconds())
    except Exception:
        return "—"
    if seconds < 0:
        seconds = 0
    if seconds < 3600:
        return f"{max(seconds // 60, 1)} دقيقة"
    if seconds < 86400:
        return f"{seconds // 3600} ساعة"
    return f"{seconds // 86400} يوم"


def ma_max_burst(times, window_minutes: int) -> int:
    """أكبر عدد أحداث وقعت داخل نافذة زمنية واحدة."""
    ordered = sorted(t for t in times if t)
    best = 0
    left = 0
    window = _timedelta(minutes=window_minutes)
    for right in range(len(ordered)):
        while ordered[right] - ordered[left] > window:
            left += 1
        best = max(best, right - left + 1)
    return best


def ma_assess(accounts, quick_hours: int = 24, burst_minutes: int = 30):
    """مؤشرات تساعد المالك على الحكم. تُرجع قائمة (أيقونة، نص).

    🔴 يرجّح أن العضو هو من سحب الجلسات، 🟡 يحتاج انتباهاً، 🟢 يدعم روايته.
    هذه مؤشرات فقط: تيليجرام لا يخبر من أنهى الجلسة.
    """
    out = []
    rows = [dict(a) for a in accounts]
    if not rows:
        return [("🟡", "لا توجد حسابات مؤجَّرة مسجّلة بهذا العضو.")]
    states = [ma_account_state(r) for r in rows]
    alive = [r for r, s in zip(rows, states) if s == "alive"]
    dead = [r for r, s in zip(rows, states) if s == "dead"]
    frozen = [r for r, s in zip(rows, states) if s == "frozen"]

    if not dead and not frozen:
        out.append(("🟢", "السجل لا يُظهر أي حساب مطرود له؛ ادّعاؤه غير مدعوم بالسجل. نفّذ الفحص الحي للتأكد."))
    if dead and alive:
        out.append(("🟡", f"{len(alive)} حساب ما زال شغالاً بالسجل، فادّعاء «كل حساباتي مطرودة» غير دقيق (تأكد بالفحص الحي)."))
    if frozen:
        out.append(("🟢", f"{len(frozen)} حساب مجمّد من تيليجرام (SpamBot): سبب خارج إرادته، لا تحاسبه عليها."))

    quick = []
    after_work = []
    for r in dead:
        kicked, added = r.get("kicked_at"), r.get("added_at")
        if kicked and added and (kicked - added) < _timedelta(hours=quick_hours) and int(r.get("jobs") or 0) == 0:
            quick.append(r)
        elif int(r.get("jobs") or 0) > 0:
            after_work.append(r)
    if quick:
        out.append(("🔴", f"{len(quick)} حساب طُرد خلال {quick_hours} ساعة من إضافته وبدون أي ربح للبوت: نمط «تأجير ثم سحب الجلسة»."))
    if after_work:
        total = sum(int(r.get("earned") or 0) for r in after_work)
        out.append(("🟡", f"{len(after_work)} حساب اشتغل ثم طُرد (أرباحه {total} نقطة): راجع وقت الطرد مقابل آخر ربح."))

    kick_times = [r.get("kicked_at") for r in dead if r.get("kicked_at")]
    if len(kick_times) >= 2:
        burst = ma_max_burst(kick_times, burst_minutes)
        if burst >= 2:
            out.append(("🔴", f"{burst} حسابات طُردت خلال {burst_minutes} دقيقة: نمط متزامن يرجّح أن الجلسات أُنهيت يدوياً دفعة واحدة. هذا ليس دليلاً قاطعاً."))
        else:
            out.append(("🟢", "توقيتات الطرد متباعدة وغير متزامنة: أقرب لأعطال أو حظر فردي منه لسحب جماعي."))
    no_time = [r for r in dead if not r.get("kicked_at")]
    if no_time:
        out.append(("🟡", f"{len(no_time)} حساب مطرود بلا توقيت (سُجّل قبل هذه الميزة). الفحص الحي أدق، ومن الآن يُسجَّل توقيت كل تغيير تلقائياً."))

    reset_marked = [r for r in rows if r.get("sessions_reset")]
    if reset_marked:
        out.append(("🟡", f"{len(reset_marked)} حساب عليه علامة «طُردت الجلسات الأخرى». قد يكون أمر طرد جماعي من جهتك أخرج العضو من حسابه؛ فإن كان يدّعي أنه انطرد من حساباته فهذا يدعمه."))
    return out


def ma_format_account_line(row, now=None) -> str:
    state = ma_account_state(row)
    parts = [f"#{row.get('id')} <code>{ma_mask_phone(row.get('phone_number'))}</code> {MA_STATE_LABEL.get(state, state)}"]
    added, kicked = row.get("added_at"), row.get("kicked_at")
    parts.append(f"أُضيف {ma_fmt_dt(added)}")
    if state == "dead":
        if kicked:
            life = f" (بعد {ma_fmt_span(kicked - added)})" if added else ""
            parts.append(f"طُرد {ma_fmt_dt(kicked)}{life}")
        else:
            parts.append("طُرد: بلا توقيت")
    if state == "frozen":
        parts.append(f"جُمّد {ma_fmt_dt(row.get('frozen_at'))}")
    jobs = int(row.get("jobs") or 0)
    earned = int(row.get("earned") or 0)
    if jobs:
        parts.append(f"ربح {earned} نقطة ({jobs} مهمة، آخرها {ma_fmt_dt(row.get('last_at'))})")
    else:
        parts.append("لم يربح شيئاً")
    return " • ".join(parts)
# PURE-END

import asyncio
import json

_AUDIT_TABLES_READY = False
_BG_TASKS = set()


def _h(value) -> str:
    return _html.escape(str(value if value is not None else ""))


def ma_ensure_tables() -> None:
    global _AUDIT_TABLES_READY
    if _AUDIT_TABLES_READY:
        return
    with db_conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS member_audit_events ("
            " id BIGSERIAL PRIMARY KEY, stock_id BIGINT, user_id BIGINT,"
            " event TEXT NOT NULL, details TEXT,"
            " created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_ma_events_user ON member_audit_events (user_id, id DESC)")
        c.execute(
            "CREATE TABLE IF NOT EXISTS member_audit_state ("
            " stock_id BIGINT PRIMARY KEY, state TEXT NOT NULL,"
            " updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS member_audit_notes ("
            " id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, note TEXT NOT NULL,"
            " created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
        )
    _AUDIT_TABLES_READY = True


def _ma_setting(key: str, default: str) -> str:
    try:
        value = get_setting(key)
    except Exception:
        value = None
    return default if value in (None, "") else str(value)


def _ma_int_setting(key: str, default: int) -> int:
    try:
        return max(1, int(_ma_setting(key, str(default))))
    except (TypeError, ValueError):
        return default


def ma_log_event(user_id, stock_id, event: str, details: str = "") -> None:
    try:
        ma_ensure_tables()
        with db_conn() as c:
            c.execute(
                "INSERT INTO member_audit_events (stock_id, user_id, event, details) VALUES (%s, %s, %s, %s)",
                (stock_id, user_id, event, details[:500]),
            )
    except Exception:
        logger.exception("تعذّر تسجيل حدث التدقيق")


def _ma_clear_cache() -> None:
    try:
        from .raksh_system.common import clear_raksh_session_cache
        clear_raksh_session_cache()
    except Exception as exc:
        logger.warning(f"تعذّر تنظيف ذاكرة حسابات الرشق: {exc}")


_ACCOUNT_SELECT = """
    SELECT ns.id, ns.phone_number, ns.added_at, ns.contributor_method,
           COALESCE(ns.contributor_share_percent, 50) AS share_percent,
           ns.last_authorized, ns.kicked_at, ns.frozen_at, ns.deleted_at,
           COALESCE(ns.raksh_excluded, FALSE) AS raksh_excluded,
           COALESCE(ns.sessions_reset, FALSE) AS sessions_reset,
           (ns.session_string IS NOT NULL AND BTRIM(ns.session_string) <> '') AS has_session,
           COALESCE(e.pts, 0) AS earned, COALESCE(e.cnt, 0) AS jobs,
           e.first_at, e.last_at
    FROM number_stock ns
    LEFT JOIN (
        SELECT stock_id, SUM(share_points) AS pts, COUNT(*) AS cnt,
               MIN(created_at) AS first_at, MAX(created_at) AS last_at
        FROM raksh_contributor_earnings
        WHERE contributor_id = %s
        GROUP BY stock_id
    ) e ON e.stock_id = ns.id
    WHERE ns.contributed_by = %s AND COALESCE(ns.ever_sold, FALSE) = FALSE
    ORDER BY ns.id
"""


def ma_fetch_accounts(user_id: int) -> list:
    with db_conn() as c:
        rows = c.execute(_ACCOUNT_SELECT, (user_id, user_id)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["earned"] = int(d.get("earned") or 0)
        d["jobs"] = int(d.get("jobs") or 0)
        out.append(d)
    return out


def ma_build_report(user_id: int) -> str:
    ma_ensure_tables()
    accounts = ma_fetch_accounts(user_id)
    try:
        profile = get_user(user_id) or {}
    except Exception:
        profile = {}
    name = _h(profile.get("full_name") or "—")
    uname = f"@{_h(profile['username'])}" if profile.get("username") else "بلا يوزر"
    banned = bool(profile.get("banned"))
    lines = [
        "🔎 <b>تدقيق مؤجّر</b>",
        f"👤 {name} ({uname})",
        f"🆔 <code>{user_id}</code> • انضم: {_h(profile.get('joined_at') or '—')}",
        "🚫 محظور: " + (f"نعم ({_h(profile.get('ban_reason') or '—')})" if banned else "لا"),
    ]
    states = [ma_account_state(a) for a in accounts]
    counts = {s: states.count(s) for s in MA_STATE_LABEL}
    earned = sum(a["earned"] for a in accounts)
    jobs = sum(a["jobs"] for a in accounts)
    lines += [
        "",
        f"📦 <b>الحسابات:</b> {len(accounts)} • ✅ {counts['alive']} شغال • 🚫 {counts['dead']} مطرود"
        f" • 🧊 {counts['frozen']} مجمّد • ⛔/🗑 {counts['excluded'] + counts['removed']} مستبعد/محذوف",
        f"💵 مجموع أرباحه: {earned} نقطة ({jobs} مهمة)",
        "",
        "<b>التفصيل:</b>",
    ]
    for a in accounts[:12]:
        lines.append("• " + ma_format_account_line(a))
    if len(accounts) > 12:
        lines.append(f"… و{len(accounts) - 12} حساب آخر.")
    lines += ["", "<b>🧭 مؤشرات (وليست حكماً قاطعاً):</b>"]
    for icon, text in ma_assess(
        accounts,
        quick_hours=_ma_int_setting("audit_quick_kick_hours", 24),
        burst_minutes=_ma_int_setting("audit_burst_minutes", 30),
    ):
        lines.append(f"{icon} {_h(text)}")
    try:
        with db_conn() as c:
            notes = c.execute(
                "SELECT note, created_at FROM member_audit_notes WHERE user_id=%s ORDER BY id DESC LIMIT 3",
                (user_id,),
            ).fetchall()
        if notes:
            lines += ["", "📝 <b>ملاحظاتك:</b>"]
            for n in notes:
                lines.append(f"• {_h(n['note'])} ({ma_fmt_dt(n['created_at'])})")
    except Exception:
        pass
    text = "\n".join(lines)
    return text if len(text) <= 3900 else text[:3880] + "…"


def ma_member_kb(user_id: int, banned: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🔬 فحص حي لجلساته", callback_data=f"os:ma:live:{user_id}")],
        [InlineKeyboardButton("📜 سجل الأحداث", callback_data=f"os:ma:log:{user_id}"),
         InlineKeyboardButton("📝 ملاحظة", callback_data=f"os:ma:note:{user_id}")],
        [InlineKeyboardButton("🛑 إيقاف حساباته بالبوت", callback_data=f"os:ma:stop:{user_id}"),
         InlineKeyboardButton("♻️ استرجاع ما أوقفته", callback_data=f"os:ma:restore:{user_id}")],
        [InlineKeyboardButton("🚫 حظر العضو", callback_data=f"os:ma:ban:{user_id}")],
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"os:ma:m:{user_id}"),
         InlineKeyboardButton("🔙 التدقيق", callback_data="os:ma:menu")],
    ]
    return InlineKeyboardMarkup(rows)


def ma_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 فحص عضو (ID أو @يوزر)", callback_data="os:ma:ask")],
        [InlineKeyboardButton("📉 أعضاء عندهم حسابات مطرودة", callback_data="os:ma:kicked")],
        [InlineKeyboardButton("⚙️ إعدادات التدقيق", callback_data="os:ma:settings")],
        [InlineKeyboardButton("ℹ️ كيف أقرأ النتائج", callback_data="os:ma:help")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
    ])


MA_MENU_TEXT = (
    "🔎 <b>تدقيق المؤجّرين</b>\n\n"
    "افحص ادعاء أي عضو أُنهيت حساباته المؤجَّرة: تقرير، فحص حي للجلسات، "
    "سجل أحداث، وإجراءات داخل البوت فقط (لا شيء يمسّ حسابات تيليجرام نفسها)."
)

MA_HELP_TEXT = (
    "ℹ️ <b>كيف أقرأ النتائج</b>\n\n"
    "1) افتح تقرير العضو ثم اضغط «فحص حي».\n\n"
    "• جلسة حيّة والسجل يقول مطرود ← خطأ من النظام. اضغط «تصحيح الحالة»؛ العضو محق.\n"
    "• جلسة ميتة وكل الحسابات طُردت بنفس الدقائق وبلا أرباح ← غالباً هو سحبها.\n"
    "• جلسة ميتة وعليها تجميد SpamBot ← تيليجرام، ليس هو.\n"
    "• جلسة حيّة ولا جهاز آخر عليها وعليها علامة «طُردت الجلسات الأخرى» ← قد يكون أمر طرد جماعي منك أخرجه من حسابه؛ ادّعاؤه محتمل، لا تحظره بعد.\n"
    "• جلسة حيّة وجهاز آخر نشط حديثاً ← هو ما زال داخل حسابه؛ ادّعاء «انطردت» غير صحيح.\n\n"
    "تيليجرام لا يخبرك من أنهى الجلسة، فكل ما سبق مؤشرات. اجمع الصورة كاملة قبل الحظر. "
    "من الآن كل تغيير يُسجَّل بتوقيته، فستكون الأدلة أوضح في المرات القادمة."
)


def ma_settings_text_kb():
    monitor = _ma_setting("audit_monitor_enabled", "1") != "0"
    alerts = _ma_setting("audit_alerts_enabled", "1") != "0"
    quick = _ma_int_setting("audit_quick_kick_hours", 24)
    burst = _ma_int_setting("audit_burst_minutes", 30)
    text = (
        "⚙️ <b>إعدادات التدقيق</b>\n\n"
        f"• المراقبة التلقائية (كل 5 دقائق): {'مفعّلة ✅' if monitor else 'مغلقة ❌'}\n"
        f"• تنبيهك عند طرد حساب مؤجَّر: {'مفعّل ✅' if alerts else 'مغلق ❌'}\n"
        f"• «طرد سريع» = خلال {quick} ساعة من الإضافة بلا ربح\n"
        f"• «طرد متزامن» = حسابان أو أكثر خلال {burst} دقيقة"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(("🔕 إيقاف المراقبة" if monitor else "🔔 تشغيل المراقبة"), callback_data="os:ma:set:mon")],
        [InlineKeyboardButton(("🔕 إيقاف التنبيهات" if alerts else "🔔 تشغيل التنبيهات"), callback_data="os:ma:set:alert")],
        [InlineKeyboardButton(f"⏱ حد الطرد السريع: {quick} ساعة (تغيير)", callback_data="os:ma:set:quick")],
        [InlineKeyboardButton(f"⏱ نافذة التزامن: {burst} دقيقة (تغيير)", callback_data="os:ma:set:burst")],
        [InlineKeyboardButton("🔙 التدقيق", callback_data="os:ma:menu")],
    ])
    return text, kb


def _ma_cycle(key: str, default: int, options: list) -> None:
    current = _ma_int_setting(key, default)
    nxt = options[(options.index(current) + 1) % len(options)] if current in options else options[0]
    set_setting(key, str(nxt))


def ma_kicked_overview() -> tuple:
    with db_conn() as c:
        rows = c.execute(
            """
            SELECT ns.contributed_by AS uid, u.username, u.full_name, u.banned,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE ns.deleted_at IS NULL AND ns.frozen_at IS NULL
                                     AND (ns.last_authorized IS FALSE
                                          OR ns.session_string IS NULL
                                          OR BTRIM(ns.session_string) = '')) AS dead,
                   COUNT(*) FILTER (WHERE ns.frozen_at IS NOT NULL) AS frozen,
                   MAX(ns.kicked_at) AS last_kick,
                   (SELECT COALESCE(SUM(e.share_points), 0) FROM raksh_contributor_earnings e
                     WHERE e.contributor_id = ns.contributed_by) AS earned
            FROM number_stock ns
            LEFT JOIN users u ON u.user_id = ns.contributed_by
            WHERE ns.contributed_by IS NOT NULL AND COALESCE(ns.ever_sold, FALSE) = FALSE
            GROUP BY ns.contributed_by, u.username, u.full_name, u.banned
            HAVING COUNT(*) FILTER (WHERE ns.deleted_at IS NULL AND ns.frozen_at IS NULL
                                     AND (ns.last_authorized IS FALSE
                                          OR ns.session_string IS NULL
                                          OR BTRIM(ns.session_string) = '')) > 0
            ORDER BY dead DESC, last_kick DESC NULLS LAST
            LIMIT 15
            """
        ).fetchall()
    rows = [dict(r) for r in rows]
    if not rows:
        return "📉 لا يوجد أعضاء لديهم حسابات مؤجَّرة مطرودة حالياً. ✅", InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 التدقيق", callback_data="os:ma:menu")]]
        )
    lines = ["📉 <b>أعضاء لديهم حسابات مؤجَّرة مطرودة</b>", ""]
    kb_rows = []
    for r in rows:
        who = r.get("full_name") or (f"@{r['username']}" if r.get("username") else str(r["uid"]))
        flag = " 🚫" if r.get("banned") else ""
        lines.append(
            f"• {_h(who)}{flag} — مطرود {r['dead']} من {r['total']}"
            f" • مجمّد {r['frozen']} • أرباحه {int(r['earned'] or 0)} • آخر طرد {ma_fmt_dt(r.get('last_kick'))}"
        )
        kb_rows.append([InlineKeyboardButton(f"🔎 {str(who)[:24]} ({r['dead']})", callback_data=f"os:ma:m:{r['uid']}")])
    kb_rows.append([InlineKeyboardButton("🔙 التدقيق", callback_data="os:ma:menu")])
    text = "\n".join(lines)
    return (text if len(text) <= 3900 else text[:3880] + "…"), InlineKeyboardMarkup(kb_rows)


def ma_events_text(user_id: int) -> str:
    ma_ensure_tables()
    with db_conn() as c:
        rows = c.execute(
            "SELECT stock_id, event, details, created_at FROM member_audit_events "
            "WHERE user_id=%s ORDER BY id DESC LIMIT 25",
            (user_id,),
        ).fetchall()
    if not rows:
        return "📜 لا توجد أحداث مسجّلة لهذا العضو بعد. (التسجيل يبدأ من تفعيل هذا التحديث.)"
    labels = {
        "alive->dead": "🚫 صار مطروداً", "alive->frozen": "🧊 صار مجمّداً",
        "dead->alive": "✅ رجع شغالاً", "added": "➕ أُضيف",
        "stopped": "🛑 أوقفته أنت", "restored": "♻️ أرجعته أنت",
        "live_dead": "🔬 الفحص الحي: ميت", "live_alive": "🔬 الفحص الحي: حي",
        "live_unknown": "🔬 الفحص الحي: تعذّر", "fixed": "🛠 صحّحت الحالة",
    }
    lines = ["📜 <b>سجل الأحداث (الأحدث أولاً)</b>", ""]
    for r in rows:
        ev = labels.get(r["event"], r["event"])
        extra = f" — {_h(r['details'])}" if r.get("details") else ""
        lines.append(f"{ma_fmt_dt(r['created_at'])} • حساب #{r['stock_id']} • {ev}{extra}")
    return "\n".join(lines)


# ───────────────────────────── الفحص الحي ─────────────────────────────

async def _ma_probe(session_string: str) -> dict:
    client = None
    try:
        client = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return {"alive": False, "devices": []}
        devices = []
        try:
            from .accounts import get_authorizations_detail
            devices = await asyncio.wait_for(get_authorizations_detail(client), timeout=12)
        except Exception:
            devices = []
        return {"alive": True, "devices": devices}
    except Exception as exc:
        return {"alive": None, "error": type(exc).__name__}
    finally:
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass


async def ma_live_check(user_id: int, limit: int = 20) -> dict:
    """يفحص جلسات حسابات العضو فعلياً عند تيليجرام. لا يغيّر شيئاً على الحسابات."""
    ma_ensure_tables()
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return {"error": "إعدادات Telegram API غير مكتملة."}
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, phone_number, session_string, last_authorized FROM number_stock "
            "WHERE contributed_by=%s AND deleted_at IS NULL AND COALESCE(ever_sold, FALSE)=FALSE "
            "AND session_string IS NOT NULL AND BTRIM(session_string) <> '' "
            "ORDER BY id LIMIT %s",
            (user_id, limit),
        ).fetchall()
    results = []
    for r in rows:
        probe = await _ma_probe(r["session_string"])
        others = [d for d in probe.get("devices", []) if not d.get("current")]
        results.append({
            "id": r["id"], "phone": r["phone_number"], "db_alive": r["last_authorized"] is not False,
            "alive": probe.get("alive"), "others": others, "error": probe.get("error"),
        })
        await asyncio.sleep(0.4)
    for res in results:
        if res["alive"] is False:
            ev = "live_dead"
            if res["db_alive"]:
                with db_conn() as c:
                    c.execute(
                        "UPDATE number_stock SET last_authorized=FALSE, "
                        "kicked_at=COALESCE(kicked_at, NOW()) WHERE id=%s AND contributed_by=%s",
                        (res["id"], user_id),
                    )
        elif res["alive"] is True:
            ev = "live_alive"
        else:
            ev = "live_unknown"
        ma_log_event(user_id, res["id"], ev, f"devices_other={len(res['others'])}")
    return {"results": results}


def ma_live_text(user_id: int, data: dict) -> tuple:
    """(نص التقرير, معرّفات الحسابات الحيّة التي يسجّلها السجل ميتة)."""
    if data.get("error"):
        return f"❌ {_h(data['error'])}", []
    results = data.get("results", [])
    if not results:
        return "ℹ️ لا توجد حسابات لهذا العضو لديها جلسة محفوظة لفحصها.", []
    lines = ["🔬 <b>الفحص الحي لجلسات البوت</b>", ""]
    alive_but_marked_dead = []
    n_alive = n_dead = n_unknown = no_other_devices = recent_other = 0
    now = _datetime.now(_timezone.utc)
    for res in results:
        mask = ma_mask_phone(res["phone"])
        if res["alive"] is True:
            n_alive += 1
            others = res["others"]
            if not res["db_alive"]:
                alive_but_marked_dead.append(res["id"])
            if others:
                apps = ", ".join(sorted({f"{d.get('app')} {d.get('platform')}".strip() for d in others})[:3])
                newest = max((d.get("date_active") for d in others if d.get("date_active")), default=None)
                if newest and (now - newest) < _timedelta(days=3):
                    recent_other += 1
                lines.append(f"✅ #{res['id']} <code>{mask}</code> حيّة • {len(others)} جهاز آخر ({_h(apps)}) • آخر نشاط {ma_fmt_dt(newest)}"
                             + ("  ⚠️ السجل يقول مطرود" if not res["db_alive"] else ""))
            else:
                no_other_devices += 1
                lines.append(f"✅ #{res['id']} <code>{mask}</code> حيّة • لا جهاز آخر عليها"
                             + ("  ⚠️ السجل يقول مطرود" if not res["db_alive"] else ""))
        elif res["alive"] is False:
            n_dead += 1
            lines.append(f"🚫 #{res['id']} <code>{mask}</code> الجلسة ميتة عند تيليجرام")
        else:
            n_unknown += 1
            lines.append(f"❓ #{res['id']} <code>{mask}</code> تعذّر الفحص ({_h(res.get('error') or '—')})")
    lines += ["", f"الخلاصة: ✅ {n_alive} حيّة • 🚫 {n_dead} ميتة • ❓ {n_unknown} تعذّر"]
    if alive_but_marked_dead:
        lines.append(f"🟡 {len(alive_but_marked_dead)} حساب حيّ فعلياً لكن السجل يعدّه مطروداً: خطأ نظام؛ يمكنك تصحيح حالته بالزر.")
    if n_dead and not n_alive:
        lines.append("🔴 كل الجلسات ميتة فعلاً: الشق الأول من ادعائه صحيح. السؤال الآن: من أنهاها؟ (راجع التوقيت والتزامن بالتقرير).")
    if n_alive and no_other_devices == n_alive:
        lines.append("🟡 جلسات البوت حيّة ولا جهاز آخر على حساباته: هو غير داخل حساباته الآن. قد يكون خرج بنفسه أو أُخرج بطرد جماعي.")
    if recent_other:
        lines.append(f"🟢/🔴 {recent_other} حساب فيه جهاز آخر نشط خلال 3 أيام: صاحبه ما زال داخلاً، فادّعاء «انطردت من حساباتي» غير صحيح لهذه الحسابات.")
    lines.append("\nملاحظة: تيليجرام قد يردّ «غير مصرّح» مؤقتاً تحت الضغط، فأعد الفحص بعد دقائق قبل أن تحكم.")
    text = "\n".join(lines)
    return (text if len(text) <= 3900 else text[:3880] + "…"), alive_but_marked_dead


# ───────────────────────────── إجراءات المالك ─────────────────────────────

def ma_stop_accounts(user_id: int) -> list:
    """يوقف حسابات العضو داخل البوت فقط (استبعاد من الرشق + حذف مؤقت). لا يمس حسابات تيليجرام."""
    ma_ensure_tables()
    with db_conn() as c:
        rows = c.execute(
            "SELECT id FROM number_stock WHERE contributed_by=%s AND deleted_at IS NULL "
            "AND COALESCE(ever_sold, FALSE)=FALSE",
            (user_id,),
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            c.execute(
                "UPDATE number_stock SET raksh_excluded=TRUE, deleted_at=NOW() WHERE id = ANY(%s)",
                (ids,),
            )
    for sid in ids:
        ma_log_event(user_id, sid, "stopped", "أوقفه المالك من التدقيق")
    _ma_clear_cache()
    return ids


def ma_restore_accounts(user_id: int) -> list:
    """يرجع فقط الحسابات التي أوقفها المالك من هذه الأداة ولا تزال موقوفة."""
    ma_ensure_tables()
    with db_conn() as c:
        rows = c.execute(
            "SELECT DISTINCT ev.stock_id FROM member_audit_events ev "
            "JOIN number_stock ns ON ns.id = ev.stock_id "
            "WHERE ev.user_id=%s AND ev.event='stopped' AND ns.deleted_at IS NOT NULL "
            "AND ns.contributed_by=%s",
            (user_id, user_id),
        ).fetchall()
        ids = [r["stock_id"] for r in rows]
        if ids:
            c.execute(
                "UPDATE number_stock SET raksh_excluded=FALSE, deleted_at=NULL WHERE id = ANY(%s)",
                (ids,),
            )
    for sid in ids:
        ma_log_event(user_id, sid, "restored", "أرجعه المالك من التدقيق")
    _ma_clear_cache()
    return ids


def ma_fix_alive(user_id: int, stock_ids: list) -> int:
    ids = [int(i) for i in stock_ids]
    if not ids:
        return 0
    with db_conn() as c:
        c.execute(
            "UPDATE number_stock SET last_authorized=TRUE, kicked_at=NULL "
            "WHERE id = ANY(%s) AND contributed_by=%s AND deleted_at IS NULL",
            (ids, user_id),
        )
    for sid in ids:
        ma_log_event(user_id, sid, "fixed", "الفحص الحي أثبت أن الجلسة حيّة")
    _ma_clear_cache()
    return len(ids)


# ───────────────────────────── واجهة الأزرار ─────────────────────────────

async def _ma_edit(q, text, kb):
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)
    except Exception as exc:
        if "not modified" not in str(exc).lower():
            logger.warning(f"ma edit failed: {exc}")


def _ma_user_banned(user_id: int) -> bool:
    try:
        return bool((get_user(user_id) or {}).get("banned"))
    except Exception:
        return False


async def _ma_live_task(q, user_id: int, context):
    try:
        data = await ma_live_check(user_id)
        text, fixable = ma_live_text(user_id, data)
        context.user_data["ma_fixable"] = {"uid": user_id, "ids": fixable}
        rows = []
        if fixable:
            rows.append([InlineKeyboardButton(f"🛠 تصحيح حالة {len(fixable)} حساب حيّ", callback_data=f"os:ma:fix:{user_id}")])
        rows.append([InlineKeyboardButton("🔁 إعادة الفحص", callback_data=f"os:ma:live:{user_id}")])
        rows.append([InlineKeyboardButton("🔙 تقرير العضو", callback_data=f"os:ma:m:{user_id}")])
        await _ma_edit(q, text, InlineKeyboardMarkup(rows))
    except Exception:
        logger.exception("فشل الفحص الحي")
        await _ma_edit(q, "❌ فشل الفحص الحي. جرّب لاحقاً.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 تقرير العضو", callback_data=f"os:ma:m:{user_id}")]]))


async def handle_member_audit_callback(update, context, q, data: str, user) -> bool:
    """يعالج أزرار os:ma:* للمالك. يُرجع True إن تم التعامل مع الزر."""
    if not data.startswith("os:ma:"):
        return False
    parts = data.split(":")
    action = parts[2] if len(parts) > 2 else "menu"
    uid = None
    if len(parts) > 3:
        try:
            uid = int(parts[3])
        except ValueError:
            uid = None

    if action == "menu":
        reset_owner_flow(context)
        await _ma_edit(q, MA_MENU_TEXT, ma_menu_kb())
    elif action == "help":
        await _ma_edit(q, MA_HELP_TEXT, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 التدقيق", callback_data="os:ma:menu")]]))
    elif action == "ask":
        reset_owner_flow(context, state="os_await_audit_target")
        await _ma_edit(q, "🔎 أرسل <b>ID</b> العضو أو <b>@يوزره</b>:",
                       InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:ma:menu")]]))
    elif action == "kicked":
        text, kb = ma_kicked_overview()
        await _ma_edit(q, text, kb)
    elif action == "settings":
        text, kb = ma_settings_text_kb()
        await _ma_edit(q, text, kb)
    elif action == "set":
        key = parts[3] if len(parts) > 3 else ""
        if key == "mon":
            set_setting("audit_monitor_enabled", "0" if _ma_setting("audit_monitor_enabled", "1") != "0" else "1")
        elif key == "alert":
            set_setting("audit_alerts_enabled", "0" if _ma_setting("audit_alerts_enabled", "1") != "0" else "1")
        elif key == "quick":
            _ma_cycle("audit_quick_kick_hours", 24, [6, 12, 24, 48, 72])
        elif key == "burst":
            _ma_cycle("audit_burst_minutes", 30, [10, 30, 60, 120])
        text, kb = ma_settings_text_kb()
        await _ma_edit(q, text, kb)
    elif uid is None:
        await _ma_edit(q, "⚠️ معرّف العضو غير صالح.", ma_menu_kb())
    elif action == "m":
        reset_owner_flow(context)
        await _ma_edit(q, ma_build_report(uid), ma_member_kb(uid, _ma_user_banned(uid)))
    elif action == "log":
        await _ma_edit(q, ma_events_text(uid), InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 تقرير العضو", callback_data=f"os:ma:m:{uid}")]]))
    elif action == "live":
        await _ma_edit(q, "⏳ جارٍ فحص الجلسات عند تيليجرام… قد يستغرق دقيقة.", None)
        task = asyncio.create_task(_ma_live_task(q, uid, context))
        _BG_TASKS.add(task)
        task.add_done_callback(_BG_TASKS.discard)
    elif action == "fix":
        stash = context.user_data.get("ma_fixable") or {}
        ids = stash.get("ids", []) if stash.get("uid") == uid else []
        done = ma_fix_alive(uid, ids)
        await _ma_edit(q, f"✅ صُحّحت حالة {done} حساب.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 تقرير العضو", callback_data=f"os:ma:m:{uid}")]]))
    elif action == "stop":
        await _ma_edit(
            q,
            "🛑 <b>إيقاف حسابات العضو بالبوت؟</b>\n\n"
            "تُستبعد كل حساباته من الرشق وتُنقل لسلة المهملات. هذا داخل البوت فقط، "
            "ولا يسجّل خروجاً من أي حساب ولا يغيّر شيئاً عليه. يمكنك التراجع بزر «استرجاع».",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ نعم، أوقفها", callback_data=f"os:ma:stopdo:{uid}")],
                [InlineKeyboardButton("🔙 إلغاء", callback_data=f"os:ma:m:{uid}")],
            ]),
        )
    elif action == "stopdo":
        ids = ma_stop_accounts(uid)
        await _ma_edit(q, f"✅ أُوقف {len(ids)} حساب داخل البوت.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 تقرير العضو", callback_data=f"os:ma:m:{uid}")]]))
    elif action == "restore":
        ids = ma_restore_accounts(uid)
        await _ma_edit(q, f"♻️ أُرجع {len(ids)} حساب." if ids else "ℹ️ لا توجد حسابات أوقفتها من هذه الأداة لاسترجاعها.",
                       InlineKeyboardMarkup([[InlineKeyboardButton("🔙 تقرير العضو", callback_data=f"os:ma:m:{uid}")]]))
    elif action == "ban":
        reset_owner_flow(context, state="os_await_ban_reason")
        context.user_data["ban_target_id"] = uid
        await _ma_edit(q, f"🚫 <b>حظر العضو</b> <code>{uid}</code>\n\nأرسل سبب الحظر (أو - لتخطي السبب):",
                       InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data=f"os:ma:m:{uid}")]]))
    elif action == "note":
        reset_owner_flow(context, state="os_await_audit_note")
        context.user_data["ma_note_target"] = uid
        await _ma_edit(q, "📝 أرسل ملاحظتك عن هذا العضو:",
                       InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data=f"os:ma:m:{uid}")]]))
    else:
        await _ma_edit(q, MA_MENU_TEXT, ma_menu_kb())
    return True


async def ma_handle_owner_text(update, context, state: str, text: str) -> bool:
    """يعالج نصوص المالك لحالتي: انتظار عضو، وانتظار ملاحظة."""
    text = (text or "").strip()
    if state == "os_await_audit_target":
        target = None
        try:
            target = lookup_user_by_id_or_username(text)
        except Exception:
            target = None
        uid = None
        if target and target.get("user_id"):
            uid = int(target["user_id"])
        elif text.lstrip("-").isdigit():
            uid = int(text)
        if uid is None:
            await update.message.reply_text("⚠️ ما لقيت هذا العضو. أرسل ID رقمي أو @يوزر صحيح.")
            return True
        reset_owner_flow(context)
        await update.message.reply_text(
            ma_build_report(uid), parse_mode=ParseMode.HTML,
            reply_markup=ma_member_kb(uid, _ma_user_banned(uid)), disable_web_page_preview=True,
        )
        return True
    if state == "os_await_audit_note":
        uid = context.user_data.get("ma_note_target")
        reset_owner_flow(context)
        if not uid or not text:
            await update.message.reply_text("⚠️ انتهت الجلسة. افتح التدقيق من جديد.")
            return True
        ma_ensure_tables()
        with db_conn() as c:
            c.execute("INSERT INTO member_audit_notes (user_id, note) VALUES (%s, %s)", (int(uid), text[:500]))
        await update.message.reply_text(
            "✅ حُفظت الملاحظة.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 تقرير العضو", callback_data=f"os:ma:m:{uid}")]]),
        )
        return True
    return False


# ───────────────────────────── المراقبة الدورية ─────────────────────────────

async def ma_monitor_job(context) -> None:
    """كل 5 دقائق: يسجّل أي تغيير بحالة حساب مؤجَّر مع توقيته، وينبّه المالك عند الطرد/التجميد."""
    try:
        if _ma_setting("audit_monitor_enabled", "1") == "0":
            return
        ma_ensure_tables()
        with db_conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT ns.id, ns.contributed_by AS uid, ns.phone_number, ns.added_at, ns.last_authorized,"
                " ns.frozen_at, ns.deleted_at, COALESCE(ns.raksh_excluded, FALSE) AS raksh_excluded,"
                " (ns.session_string IS NOT NULL AND BTRIM(ns.session_string) <> '') AS has_session"
                " FROM number_stock ns"
                " WHERE ns.contributed_by IS NOT NULL AND COALESCE(ns.ever_sold, FALSE)=FALSE"
            ).fetchall()]
            prev = {r["stock_id"]: r["state"] for r in c.execute(
                "SELECT stock_id, state FROM member_audit_state").fetchall()}
        first_run = not prev
        changes = []
        for r in rows:
            new = ma_account_state(r)
            old = prev.get(r["id"])
            if old != new:
                changes.append((r, old, new))
        if not changes:
            return
        with db_conn() as c:
            for r, old, new in changes:
                c.execute(
                    "INSERT INTO member_audit_state (stock_id, state) VALUES (%s, %s) "
                    "ON CONFLICT (stock_id) DO UPDATE SET state=EXCLUDED.state, updated_at=NOW()",
                    (r["id"], new),
                )
                if not first_run:
                    c.execute(
                        "INSERT INTO member_audit_events (stock_id, user_id, event, details) VALUES (%s, %s, %s, %s)",
                        (r["id"], r["uid"], "added" if old is None else f"{old}->{new}", ""),
                    )
        if first_run or _ma_setting("audit_alerts_enabled", "1") == "0":
            return
        owner_id = int(OWNER_ID or 0)
        if not owner_id:
            return
        alerts = {}
        for r, old, new in changes:
            if old == "alive" and new in ("dead", "frozen"):
                alerts.setdefault(r["uid"], []).append((r, new))
        now = _datetime.now(_timezone.utc)
        for uid, items in list(alerts.items())[:5]:
            try:
                profile = get_user(uid) or {}
            except Exception:
                profile = {}
            who = profile.get("full_name") or (f"@{profile['username']}" if profile.get("username") else str(uid))
            lines = [f"⚠️ <b>حساب مؤجَّر تغيّرت حالته</b>", f"👤 {_h(who)} • <code>{uid}</code>", ""]
            for r, new in items:
                age = ma_fmt_span(now - r["added_at"]) if r.get("added_at") else "—"
                lines.append(f"• #{r['id']} <code>{ma_mask_phone(r['phone_number'])}</code> ← {MA_STATE_LABEL[new]} (عمره بالبوت {age})")
            if len(items) >= 2:
                lines.append(f"\n🔴 {len(items)} حسابات لنفس العضو تغيّرت في نفس الدورة: نمط متزامن.")
            await context.bot.send_message(
                owner_id, "\n".join(lines), parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔎 افتح التدقيق", callback_data=f"os:ma:m:{uid}")]]),
            )
    except Exception:
        logger.exception("فشلت مراقبة المؤجّرين")
