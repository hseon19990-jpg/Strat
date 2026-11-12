"""ربط أرقام Strat ببوت آخر عبر جلسات مستقلة (جهاز ثانٍ منفصل تماماً).

لكل رقم يملك Strat جلسة صالحة له، تُنشأ تلقائياً جلسة ثانية جديدة بالكامل
(StringSession فارغة) عبر تسجيل دخول حقيقي: طلب كود، وقراءته تلقائياً من
محادثة الحساب الرسمي 777000 باستخدام الجلسة الأصلية الموجودة أصلاً عند
Strat، ثم إكمال تسجيل الدخول (وكلمة التحقق بخطوتين المحفوظة إن وُجدت).

الناتج جلسة مستقلة تماماً (جهازان مختلفان لنفس الحساب) تُخزَّن بانتظار أن
يسحبها بوت آخر عبر نقطة API محمية بمفتاح سري (انظر shared.py).
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    SessionPasswordNeededError,
)

from . import shared as _shared
from .database import db_conn
from .accounts import fetch_last_login_code

globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

_ebs_log = logging.getLogger(__name__)

# فاصل زمني بين كل محاولة وأخرى حتى لا تُحظر الأرقام أو الـ API من تيليجرام.
EXTERNAL_LINK_INTERVAL_SECONDS = 20
EXTERNAL_LINK_MAX_PER_TICK = 1
EXTERNAL_LINK_MAX_ATTEMPTS = 5
_CODE_WAIT_SECONDS = 25
_CODE_POLL_SECONDS = 2

_ebs_job_lock = asyncio.Lock()


def _queue_eligible_phones():
    """يضيف إلى الطابور كل رقم مخزون صالح (جلسة سارية، غير مباع، غير محذوف)
    وليس له سجل جلسة خارجية جاهزة أو قيد التنفيذ بعد."""
    with db_conn() as c:
        c.execute(
            "INSERT INTO external_bot_sessions (phone_number, source_stock_id, status) "
            "SELECT s.phone_number, s.id, 'pending' FROM number_stock s "
            "WHERE s.session_string IS NOT NULL AND s.session_string <> '' "
            "  AND s.last_authorized IS NOT FALSE "
            "  AND s.deleted_at IS NULL AND s.ever_sold IS NOT TRUE "
            "ON CONFLICT (phone_number) DO NOTHING"
        )


def _next_pending_row():
    with db_conn() as c:
        row = c.execute(
            "SELECT e.id, e.phone_number, e.attempts, s.session_string, s.twofa_password "
            "FROM external_bot_sessions e "
            "JOIN number_stock s ON s.phone_number = e.phone_number "
            "WHERE e.status = 'pending' AND e.attempts < %s "
            "  AND s.session_string IS NOT NULL AND s.session_string <> '' "
            "  AND s.last_authorized IS NOT FALSE AND s.deleted_at IS NULL AND s.ever_sold IS NOT TRUE "
            "ORDER BY e.created_at ASC LIMIT 1",
            (EXTERNAL_LINK_MAX_ATTEMPTS,),
        ).fetchone()
        return dict(row) if row else None


def _mark_row(row_id: int, *, status: str, session_string: str = None, fail_reason: str = None):
    with db_conn() as c:
        if status == "ready":
            c.execute(
                "UPDATE external_bot_sessions SET status='ready', session_string=%s, "
                "ready_at=NOW(), fail_reason=NULL, attempts=attempts+1 WHERE id=%s",
                (session_string, row_id),
            )
        else:
            c.execute(
                "UPDATE external_bot_sessions SET status=%s, fail_reason=%s, attempts=attempts+1 "
                "WHERE id=%s",
                (status, fail_reason or "", row_id),
            )


async def _generate_independent_session(phone: str, original_session: str, twofa_password: str):
    """ينشئ جلسة جديدة مستقلة (جهاز منفصل) لنفس الرقم. يُرجع session_string
    الجديد عند النجاح، أو يرفع استثناءً يحمل سبب الفشل."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise RuntimeError("لم يُضبط TELEGRAM_API_ID/HASH")

    orig_client = TelegramClient(StringSession(original_session), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    new_client = TelegramClient(StringSession(), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    try:
        await orig_client.connect()
        if not await orig_client.is_user_authorized():
            raise RuntimeError("الجلسة الأصلية لم تعد مُصرَّحة")

        await new_client.connect()
        start_time = _dt.datetime.now(_dt.timezone.utc)
        sent = await new_client.send_code_request(phone)

        code = None
        waited = 0
        while waited < _CODE_WAIT_SECONDS:
            await asyncio.sleep(_CODE_POLL_SECONDS)
            waited += _CODE_POLL_SECONDS
            text, _msg_date = await fetch_last_login_code(orig_client, after_date=start_time)
            if text:
                digits = "".join(ch for ch in text if ch.isdigit())
                # كود تيليجرام عادة 5 أرقام.
                if len(digits) >= 5:
                    code = digits[:5]
                    break
        if not code:
            raise RuntimeError("لم يصل كود الدخول خلال المهلة")

        try:
            await new_client.sign_in(phone, code, phone_code_hash=sent.phone_code_hash)
        except SessionPasswordNeededError:
            if not twofa_password:
                raise RuntimeError("الحساب يحتاج كلمة تحقق بخطوتين وهي غير محفوظة")
            await new_client.sign_in(password=twofa_password)

        if not await new_client.is_user_authorized():
            raise RuntimeError("فشل تسجيل الدخول للجهاز الجديد")

        return new_client.session.save()
    finally:
        try:
            await orig_client.disconnect()
        except Exception:
            pass
        try:
            await new_client.disconnect()
        except Exception:
            pass


async def run_external_bot_link_job(context=None):
    """مهمة دورية: تضيف الأرقام الجديدة للطابور، ثم تُنشئ جلسة مستقلة واحدة
    (أو أكثر بحسب EXTERNAL_LINK_MAX_PER_TICK) في كل دورة."""
    if _ebs_job_lock.locked():
        return
    async with _ebs_job_lock:
        try:
            _queue_eligible_phones()
        except Exception as e:
            _ebs_log.error(f"❌ تعذّر تحديث طابور ربط البوت الآخر: {e}")
            return

        for _ in range(EXTERNAL_LINK_MAX_PER_TICK):
            row = None
            try:
                row = _next_pending_row()
            except Exception as e:
                _ebs_log.error(f"❌ تعذّر قراءة طابور ربط البوت الآخر: {e}")
                return
            if not row:
                return
            try:
                new_session = await _generate_independent_session(
                    row["phone_number"], row["session_string"], row.get("twofa_password") or ""
                )
                _mark_row(row["id"], status="ready", session_string=new_session)
                _ebs_log.info(f"✅ جلسة مستقلة جاهزة للبوت الآخر: {row['phone_number']}")
            except FloodWaitError as e:
                _mark_row(row["id"], status="pending", fail_reason=f"flood_wait:{e.seconds}")
                return
            except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
                _mark_row(row["id"], status="failed", fail_reason=str(e))
            except Exception as e:
                _mark_row(row["id"], status="pending", fail_reason=str(e))
                _ebs_log.warning(f"⚠️ فشل إنشاء جلسة مستقلة لـ {row['phone_number']}: {e}")


def external_bot_link_counts():
    """إحصاءات لعرضها في لوحة المالك."""
    with db_conn() as c:
        row = c.execute(
            "SELECT "
            "COUNT(*) FILTER (WHERE status='pending') AS pending, "
            "COUNT(*) FILTER (WHERE status='ready' AND delivered=0) AS ready_undelivered, "
            "COUNT(*) FILTER (WHERE delivered=1) AS delivered, "
            "COUNT(*) FILTER (WHERE status='failed') AS failed "
            "FROM external_bot_sessions"
        ).fetchone()
        return dict(row) if row else {"pending": 0, "ready_undelivered": 0, "delivered": 0, "failed": 0}
