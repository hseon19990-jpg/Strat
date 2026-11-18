"""حماية مطلقة للحسابات المؤجّرة: لا يُطرد أي جهاز أو جلسة منها بأي حال.

الحساب المؤجّر (المضاف من عضو، أي contributed_by غير فارغ) خط أحمر. الحسابات
التي يضيفها المالك بنفسه والحسابات المباعة لا تشملها الحماية وتُطرد كالمعتاد. بدل الاعتماد على
فحص كل مسار طرد على حدة، نعترض طلبات Telethon نفسها
(ResetAuthorizationsRequest / ResetAuthorizationRequest) عند نقطة واحدة،
فيُرفض الطرد مهما كان المسار الذي استدعاه: المالك أو المشرف أو الفحص التلقائي
أو أي كود مستقبلي.

الاستثناء الوحيد: طرد يدوي صريح يطلبه مالك البوت من لوحته وبتأكيد، ويُنفَّذ
داخل ``owner_manual_kick()``. أي مسار آخر (البوت نفسه، الفحوص التلقائية،
المشرفون، الأعضاء) مرفوض دائماً.

المطابقة تتم عبر auth_key للجلسة لا نص الجلسة، فتنجح حتى لو تغير DC.
عند تعذّر التحقق من قاعدة البيانات يُمنع الطرد (فشل آمن).
"""

import contextlib
import contextvars
import logging
import time

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.auth import ResetAuthorizationsRequest
from telethon.tl.functions.account import ResetAuthorizationRequest

logger = logging.getLogger(__name__)

PROTECTED_MESSAGE = "🔴 حساب مؤجَّر محمي: يُمنع طرد أي جهاز أو جلسة منه بأي حال."
_KICK_TYPES = (ResetAuthorizationsRequest, ResetAuthorizationRequest)
_CACHE_TTL_SECONDS = 5
_cache = {"at": 0.0, "keys": frozenset()}
_installed = False
_owner_manual = contextvars.ContextVar("rental_owner_manual_kick", default=False)


@contextlib.contextmanager
def owner_manual_kick():
    """يسمح بطرد واحد يدوي من المالك ضمن هذا السياق فقط."""
    token = _owner_manual.set(True)
    try:
        yield
    finally:
        _owner_manual.reset(token)


class RentedAccountProtected(PermissionError):
    """محاولة طرد جلسات حساب مؤجَّر."""


def _rented_auth_keys() -> frozenset:
    now = time.monotonic()
    if now - _cache["at"] < _CACHE_TTL_SECONDS:
        return _cache["keys"]
    from .database import db_conn

    with db_conn() as c:
        rows = c.execute(
            "SELECT session_string FROM number_stock "
            "WHERE session_string IS NOT NULL AND BTRIM(session_string) <> '' "
            "AND deleted_at IS NULL "
            "AND contributed_by IS NOT NULL AND ever_sold IS NOT TRUE"
        ).fetchall()
    keys = set()
    for row in rows:
        try:
            key = StringSession(row["session_string"]).auth_key
            if key is not None and getattr(key, "key", None):
                keys.add(bytes(key.key))
        except Exception:
            continue
    _cache["keys"] = frozenset(keys)
    _cache["at"] = now
    return _cache["keys"]


def is_rented_client(client) -> bool:
    """هل جلسة هذا العميل تخص حساباً مؤجَّراً؟"""
    auth = getattr(getattr(client, "session", None), "auth_key", None)
    key = getattr(auth, "key", None)
    if not key:
        return False
    return bytes(key) in _rented_auth_keys()


def _has_kick(request) -> bool:
    if isinstance(request, _KICK_TYPES):
        return True
    if isinstance(request, (list, tuple)):
        return any(isinstance(r, _KICK_TYPES) for r in request)
    return False


def install() -> None:
    """يفعّل الاعتراض مرة واحدة على TelegramClient."""
    global _installed
    if _installed:
        return
    original_call = TelegramClient.__call__

    def guarded_call(self, request, *args, **kwargs):
        if not _has_kick(request):
            return original_call(self, request, *args, **kwargs)

        async def _run():
            try:
                rented = is_rented_client(self)
            except Exception as exc:  # فشل آمن: لا نطرد إن لم نستطع التحقق
                logger.error("تعذّر التحقق من حماية الحساب المؤجَّر: %s", exc)
                raise RentedAccountProtected(
                    "تعذّر التحقق من حالة الحساب، لذلك مُنع الطرد احتياطاً."
                ) from exc
            if rented and _owner_manual.get():
                logger.warning("⚠️ طرد يدوي من المالك لحساب مؤجَّر")
                return await original_call(self, request, *args, **kwargs)
            if rented:
                logger.warning("🔴 مُنعت محاولة طرد جلسات حساب مؤجَّر")
                raise RentedAccountProtected(PROTECTED_MESSAGE)
            return await original_call(self, request, *args, **kwargs)

        return _run()

    TelegramClient.__call__ = guarded_call
    _installed = True
