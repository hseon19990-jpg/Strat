"""تتبّع إحالات عضو معيّن (للمالك).

يكتب المالك ID أو @يوزر، فيظهر ملخص (المكتملة / غير المكتملة) وأزرار لاختيار
عدد الإحالات: 50 / 100 / 200 / الكل / عدد مخصص، مع خيار تضمين غير المكتملة.
القوائم حتى 100 إحالة تُرسل رسائل في المحادثة، والأكبر تُرسل ملف نصي.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from .database import db_conn
from .services import md_escape

logger = logging.getLogger(__name__)

REFERRAL_LOOKUP_MAX = 5000       # أقصى عدد يُجلب مرة واحدة
REFERRAL_CHAT_MAX = 100          # فوق هذا العدد يُرسل ملفاً بدل رسائل
_CHUNK_CHARS = 3800              # حد آمن أقل من 4096 لرسالة تيليجرام
STATE_AWAIT_COUNT = "os_await_ref_count"


# ───────────────────────── جلب البيانات ─────────────────────────

def find_inviter(search: str) -> dict | None:
    """ابحث بالـ ID الرقمي أو اليوزر (@user أو t.me/user، بلا حساسية لحالة الأحرف)."""
    raw = (search or "").strip()
    raw = re.sub(r"^(?:https?://)?(?:www\.)?t(?:elegram)?\.me/", "", raw, flags=re.I)
    raw = raw.lstrip("@").strip()
    if not raw:
        return None
    with db_conn() as c:
        row = None
        if raw.isdigit():
            row = c.execute(
                "SELECT user_id, full_name, username FROM users WHERE user_id=%s",
                (int(raw),),
            ).fetchone()
        if not row:
            row = c.execute(
                "SELECT user_id, full_name, username FROM users "
                "WHERE LOWER(username)=LOWER(%s) LIMIT 1",
                (raw,),
            ).fetchone()
    return dict(row) if row else None


def count_referrals(user_id: int) -> tuple[int, int]:
    """(المكتملة، غير المكتملة)."""
    with db_conn() as c:
        row = c.execute(
            "SELECT COUNT(*) FILTER (WHERE referral_credited=1) AS done, "
            "COUNT(*) FILTER (WHERE COALESCE(referral_credited,0)<>1) AS pending "
            "FROM users WHERE invited_by=%s",
            (int(user_id),),
        ).fetchone()
    return (int(row["done"] or 0), int(row["pending"] or 0)) if row else (0, 0)


def fetch_referrals(user_id: int, limit: int | None, include_pending: bool) -> list[dict]:
    """آخر الإحالات (الأحدث أولاً). limit=None يعني الحد الأقصى المسموح."""
    n = REFERRAL_LOOKUP_MAX if not limit else max(1, min(int(limit), REFERRAL_LOOKUP_MAX))
    cols = "user_id, full_name, username, credited_at, joined_at, referral_credited"
    if include_pending:
        where = "invited_by=%s"
        order_ts = "COALESCE(credited_at, NULLIF(joined_at,'')::timestamptz)"
        order_simple = "credited_at DESC NULLS LAST, joined_at DESC NULLS LAST, user_id DESC"
    else:
        where = "invited_by=%s AND referral_credited=1"
        order_ts = "credited_at"
        order_simple = "credited_at DESC NULLS LAST, user_id DESC"
    with db_conn() as c:
        try:
            rows = c.execute(
                f"SELECT {cols} FROM users WHERE {where} "
                f"ORDER BY {order_ts} DESC NULLS LAST, user_id DESC LIMIT %s",
                (int(user_id), n),
            ).fetchall()
        except Exception:
            # صيغة joined_at غير قابلة للتحويل: نرجع لترتيب بسيط لا يفشل.
            logger.warning("referral lookup: fallback ordering", exc_info=True)
            rows = c.execute(
                f"SELECT {cols} FROM users WHERE {where} ORDER BY {order_simple} LIMIT %s",
                (int(user_id), n),
            ).fetchall()
    return [dict(r) for r in rows]


# ───────────────────────── التنسيق ─────────────────────────

def _fmt_dt(value) -> str:
    if not value:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)[:19]


def format_row(index: int, row: dict, *, markdown: bool) -> str:
    name = row.get("full_name") or f"ID:{row['user_id']}"
    username = row.get("username")
    done = int(row.get("referral_credited") or 0) == 1
    when = _fmt_dt(row.get("credited_at") if done else row.get("joined_at"))
    status = "✅" if done else "⏳"
    if markdown:
        user = f" (@{md_escape(username)})" if username else ""
        return f"{index}. {status} {md_escape(name)}{user}\n    🆔 `{row['user_id']}` • {when}"
    user = f" (@{username})" if username else ""
    return f"{index}. {status} {name}{user} | ID: {row['user_id']} | {when}"


def chunk_lines(lines: list[str], limit: int = _CHUNK_CHARS) -> list[str]:
    chunks, current, size = [], [], 0
    for line in lines:
        add = len(line) + 1
        if current and size + add > limit:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += add
    if current:
        chunks.append("\n".join(current))
    return chunks


def parse_count(text: str) -> int | None:
    """رقم موجب، أو None لـ«الكل». يرفع ValueError إن كان غير صالح."""
    value = (text or "").strip().lower()
    if value in {"all", "الكل", "كل", "كلها"}:
        return None
    if not value.isdigit() or int(value) < 1:
        raise ValueError("invalid count")
    return min(int(value), REFERRAL_LOOKUP_MAX)


def selector_keyboard(user_id: int, include_pending: bool) -> InlineKeyboardMarkup:
    m = "a" if include_pending else "c"
    toggle_mode = "c" if include_pending else "a"
    toggle_label = "✅ المكتملة فقط" if include_pending else "⏳ مع غير المكتملة"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("50", callback_data=f"os:refv:{user_id}:50:{m}"),
            InlineKeyboardButton("100", callback_data=f"os:refv:{user_id}:100:{m}"),
            InlineKeyboardButton("200", callback_data=f"os:refv:{user_id}:200:{m}"),
        ],
        [
            InlineKeyboardButton("📋 الكل", callback_data=f"os:refv:{user_id}:all:{m}"),
            InlineKeyboardButton("✏️ عدد آخر", callback_data=f"os:refv:{user_id}:custom:{m}"),
        ],
        [InlineKeyboardButton(toggle_label, callback_data=f"os:refv:{user_id}:menu:{toggle_mode}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="os:top_referrers")],
    ])


def summary_text(inviter: dict, done: int, pending: int, include_pending: bool) -> str:
    name = md_escape(inviter.get("full_name") or f"ID:{inviter['user_id']}")
    user = f" (@{md_escape(inviter['username'])})" if inviter.get("username") else ""
    scope = "المكتملة + غير المكتملة" if include_pending else "المكتملة فقط"
    return (
        f"👤 *{name}*{user}\n🆔 `{inviter['user_id']}`\n\n"
        f"✅ إحالات مكتملة: *{done}*\n⏳ غير مكتملة: *{pending}*\n\n"
        f"النطاق الحالي: _{scope}_\nاختر عدد الإحالات التي تريد عرضها:"
    )


# ───────────────────────── الإرسال ─────────────────────────

def _get_inviter(user_id: int) -> dict | None:
    with db_conn() as c:
        row = c.execute(
            "SELECT user_id, full_name, username FROM users WHERE user_id=%s", (int(user_id),)
        ).fetchone()
    return dict(row) if row else None


async def send_selector(message, inviter: dict, include_pending: bool, *, edit: bool = False) -> None:
    done, pending = count_referrals(inviter["user_id"])
    text = summary_text(inviter, done, pending, include_pending)
    kb = selector_keyboard(inviter["user_id"], include_pending)
    if edit:
        await message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    else:
        await message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def send_referral_list(message, user_id: int, limit: int | None, include_pending: bool) -> None:
    inviter = _get_inviter(user_id)
    if not inviter:
        await message.reply_text("❌ المستخدم غير موجود.")
        return
    rows = fetch_referrals(user_id, limit, include_pending)
    done, pending = count_referrals(user_id)
    scope = "المكتملة + غير المكتملة" if include_pending else "المكتملة"
    kb = selector_keyboard(user_id, include_pending)
    if not rows:
        await message.reply_text(
            f"📋 لا توجد إحالات ({scope}) لهذا العضو.", reply_markup=kb
        )
        return

    head = f"📋 آخر {len(rows)} إحالة ({scope}) — ✅ {done} مكتملة • ⏳ {pending} غير مكتملة"
    if len(rows) <= REFERRAL_CHAT_MAX:
        title = md_escape(inviter.get("full_name") or f"ID:{inviter['user_id']}")
        user = f" (@{md_escape(inviter['username'])})" if inviter.get("username") else ""
        lines = [f"👤 *{title}*{user}\n{head}\n"] + [
            format_row(i, r, markdown=True) for i, r in enumerate(rows, 1)
        ]
        chunks = chunk_lines(lines)
        for i, chunk in enumerate(chunks):
            last = i == len(chunks) - 1
            await message.reply_text(
                chunk, parse_mode=ParseMode.MARKDOWN, reply_markup=kb if last else None
            )
        return

    # قائمة كبيرة: ملف نصي أفضل من عشرات الرسائل.
    plain = [
        f"{inviter.get('full_name') or inviter['user_id']} (ID: {inviter['user_id']})",
        head,
        "",
    ] + [format_row(i, r, markdown=False) for i, r in enumerate(rows, 1)]
    bio = io.BytesIO("\n".join(plain).encode("utf-8"))
    await message.reply_document(
        document=bio,
        filename=f"referrals_{inviter['user_id']}_{len(rows)}.txt",
        caption=head,
        reply_markup=kb,
    )


async def handle_refv_callback(q, context, data: str) -> None:
    """os:refv:<uid>:<n|all|custom|menu>:<c|a>"""
    parts = data.split(":")
    try:
        user_id = int(parts[2])
        action = parts[3]
        include_pending = (parts[4] == "a") if len(parts) > 4 else False
    except (IndexError, ValueError):
        await q.answer("طلب غير صالح.", show_alert=True)
        return
    inviter = _get_inviter(user_id)
    if not inviter:
        await q.answer("المستخدم غير موجود.", show_alert=True)
        return

    if action == "menu":
        await send_selector(q.message, inviter, include_pending, edit=True)
        return
    if action == "custom":
        context.user_data["state"] = STATE_AWAIT_COUNT
        context.user_data["ref_view_uid"] = user_id
        context.user_data["ref_view_mode"] = "a" if include_pending else "c"
        await q.message.reply_text(
            "✏️ أرسل عدد الإحالات المطلوب (مثال: `75`) أو كلمة «الكل».",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    try:
        limit = parse_count(action)
    except ValueError:
        await q.answer("عدد غير صالح.", show_alert=True)
        return
    await send_referral_list(q.message, user_id, limit, include_pending)


async def handle_ref_count_text(update, context, text: str) -> None:
    user_id = context.user_data.get("ref_view_uid")
    include_pending = context.user_data.get("ref_view_mode") == "a"
    try:
        limit = parse_count(text)
    except ValueError:
        await update.message.reply_text("⚠️ أرسل رقماً موجباً مثل 75 أو كلمة «الكل».")
        return
    context.user_data["state"] = "main_menu"
    if not user_id:
        await update.message.reply_text("⚠️ انتهت الجلسة، ابحث عن العضو من جديد.")
        return
    await send_referral_list(update.message, int(user_id), limit, include_pending)
