"""خدمة إرسال رسالة عبر أحد حسابات الرشق القادرة على المراسلة."""

import asyncio
import logging
import re
from urllib.parse import urlparse

from telethon import TelegramClient
from telethon.sessions import StringSession

from ..accounts import check_spam_status_detailed
from ..database import db_conn
from ..shared import TELEGRAM_API_HASH, TELEGRAM_API_ID
from .common import (
    RakshService,
    ServiceConfig,
    _get_raksh_session_lock,
    get_raksh_sessions_for_request,
)

logger = logging.getLogger(__name__)

MESSAGE_BOT_SIGNATURE = (
    "يتم ارسال هذه الرسالة من بوت ارشقلي :@arshaqlibot\n"
    "بوت رشق متابعين لجميع التطبيقات"
)


def normalize_message_recipient(value: str) -> str | None:
    """تحويل إدخال المستخدم إلى يوزر تيليجرام فقط، ومنع إدخال أرقام أو روابط عشوائية."""
    raw = str(value or "").strip()
    if not raw:
        return None

    if raw.startswith(("https://t.me/", "http://t.me/", "t.me/")):
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        username = parsed.path.strip("/").split("/", 1)[0]
    else:
        username = raw.split()[0]

    username = username.lstrip("@").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        return None
    return f"@{username}"


def message_identity_keyboard():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕵️ شخص مجهول", callback_data="raksh:message:identity:anonymous")],
        [InlineKeyboardButton("👤 تحديد هويتي", callback_data="raksh:message:identity:self")],
        [InlineKeyboardButton("🎭 هوية مزيفة", callback_data="raksh:message:identity:fake")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="raksh:message:cancel")],
    ])


def message_confirmation_keyboard():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأكيد وإرسال", callback_data="raksh:message:send")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="raksh:message:cancel")],
    ])


def message_identity_label(identity_type: str, identity_name: str = "") -> str:
    if identity_type == "anonymous":
        return "لديك رسالة من شخص مجهول"
    return f"لديك رسالة من صديقك: {identity_name or 'غير معروف'}"


def build_raksh_message(
    recipient_name: str,
    message_text: str,
    identity_type: str,
    identity_name: str = "",
) -> str:
    return (
        f"مرحبا عزيزي: {recipient_name or 'صديقي'}\n\n"
        f"{MESSAGE_BOT_SIGNATURE}\n\n"
        f"{message_identity_label(identity_type, identity_name)}\n"
        f"الرسالة :\n{message_text}"
    )


def message_confirmation_text(data: dict) -> str:
    identity_type = data.get("identity_type") or "anonymous"
    identity_name = data.get("identity_name") or ""
    identity_label = (
        "شخص مجهول"
        if identity_type == "anonymous"
        else f"صديقك: {identity_name}"
    )
    return (
        "📨 تأكيد إرسال الرسالة\n\n"
        f"👤 المستلم: {data.get('recipient')}\n"
        f"🕵️ هوية الرسالة: {identity_label}\n\n"
        "📝 نص الرسالة:\n"
        f"{data.get('message')}\n\n"
        "⚠️ ملاحظة: الحساب المرسل قد يظهر للمستلم في تيليجرام، "
        "أما نص الرسالة فسيستخدم الهوية التي اخترتها."
    )


def _message_sessions(is_owner: bool = False) -> list[dict]:
    with db_conn() as connection:
        rows = connection.execute(
            """
            SELECT id, phone_number, session_string, raksh_only, last_authorized
            FROM number_stock
            WHERE session_string IS NOT NULL
              AND BTRIM(session_string) <> ''
              AND deleted_at IS NULL
              AND forced_ref_excluded IS NOT TRUE
            ORDER BY last_authorized DESC NULLS LAST, id ASC
            """
        ).fetchall()
    return get_raksh_sessions_for_request([dict(row) for row in rows], is_owner)


class MessageService(RakshService):
    """خدمة إرسال رسالة مدفوعة بحساب رشق واحد."""

    service_type = "send_message"
    label = "✉️ إرسال رسالة"
    config = ServiceConfig(
        name=label,
        price_points=100,
        points_quantity=1,
        price_stars=10,
        stars_quantity=1,
        has_channel=False,
        has_reaction=False,
        has_ai=False,
        needs_link=False,
        min_delay=3,
        max_delay=3,
    )

    def get_sessions(self, is_owner: bool = False) -> list[dict]:
        return _message_sessions(is_owner=is_owner)

    def get_execution_params(self, context) -> dict:
        data = context.user_data.get("raksh_message_data") or {}
        return {
            "message_recipient": data.get("recipient") or "",
            "message_text": data.get("message") or "",
            "message_identity_type": data.get("identity_type") or "anonymous",
            "message_identity_name": data.get("identity_name") or "",
        }

    async def execute(self, session: dict, params: dict, is_first: bool) -> tuple[bool, str]:
        return await _send_message_from_session(
            session,
            params.get("message_recipient") or "",
            params.get("message_text") or "",
            params.get("message_identity_type") or "anonymous",
            params.get("message_identity_name") or "",
        )


async def _send_message_from_session(
    session: dict,
    recipient: str,
    message_text: str,
    identity_type: str,
    identity_name: str,
) -> tuple[bool, str]:
    """إرسال الرسالة من جلسة واحدة؛ قفل الجلسة يديره مدير التنفيذ."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return False, "إعدادات Telegram API غير مكتملة."

    phone = session.get("phone_number") or "غير معروف"
    client = TelegramClient(
        StringSession(session["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=15)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
            return False, "الجلسة غير مصرح بها."

        spam_status = await asyncio.wait_for(
            check_spam_status_detailed(client),
            timeout=25,
        )
        if spam_status.get("restricted") is not False:
            return False, "الحساب مقيد من المراسلة."

        entity = await asyncio.wait_for(client.get_entity(recipient), timeout=15)
        recipient_name = " ".join(
            part for part in (
                getattr(entity, "first_name", ""),
                getattr(entity, "last_name", ""),
            )
            if part
        ).strip() or getattr(entity, "title", None) or recipient
        body = build_raksh_message(
            recipient_name,
            message_text,
            identity_type,
            identity_name,
        )
        await asyncio.wait_for(client.send_message(entity, body), timeout=30)
        return True, f"تم إرسال الرسالة بنجاح إلى {recipient}."
    except Exception as exc:
        logger.warning("فشل إرسال رسالة الرشق من %s: %s", phone, exc)
        return False, f"فشل إرسال الرسالة من الحساب {phone}."
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def send_raksh_message(
    recipient: str,
    message_text: str,
    identity_type: str,
    identity_name: str,
    is_owner: bool = False,
) -> tuple[bool, str]:
    """يفحص الحسابات واحداً تلو الآخر عبر SpamBot ثم يرسل من أول حساب صالح."""
    sessions = _message_sessions(is_owner=is_owner)
    if not sessions:
        return False, "لا توجد حسابات رشق متاحة للمراسلة حالياً."

    for session in sessions:
        phone = session.get("phone_number") or "غير معروف"
        lock = _get_raksh_session_lock(str(phone))
        async with lock:
            ok, result = await _send_message_from_session(
                session,
                recipient,
                message_text,
                identity_type,
                identity_name,
            )
            if ok:
                return True, result

    return False, "لم يتم العثور على حساب قادر على مراسلة هذا المستخدم حالياً."
