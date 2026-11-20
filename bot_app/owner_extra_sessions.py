"""فحص حسابات المالك التي عليها أكثر من جلسة غير جلسة البوت.

القراءة فقط: لا يطرد أي جلسة ولا يعدّل حالة الحساب، سوى تحديث العمود
``last_device_count`` بالعدد الفعلي لأجهزة الحساب (يشمل جلسة البوت).
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# عدد الجلسات الإضافية (غير جلسة البوت) المطلوب للظهور في القائمة.
MIN_EXTRA_SESSIONS = 2
_CONCURRENCY = 5
_PER_ACCOUNT_TIMEOUT = 25


def count_extra_sessions(authorizations) -> int:
    """عدد الجلسات غير الحالية (أي غير جلسة البوت)."""
    return sum(1 for auth in authorizations if not getattr(auth, "current", False))


def describe_extra_sessions(authorizations) -> List[str]:
    lines = []
    for auth in authorizations:
        if getattr(auth, "current", False):
            continue
        device = getattr(auth, "device_model", "") or "غير معروف"
        app = getattr(auth, "app_name", "") or ""
        country = getattr(auth, "country", "") or ""
        label = " | ".join(part for part in (device, app, country) if part)
        lines.append(label)
    return lines


def load_owner_accounts() -> List[Dict[str, Any]]:
    """حسابات أضافها المالك (بدون مساهم) ولها جلسة صالحة للفحص."""
    from .database import db_conn

    with db_conn() as c:
        rows = c.execute(
            "SELECT id, phone_number, session_string FROM number_stock "
            "WHERE contributed_by IS NULL "
            "AND session_string IS NOT NULL AND BTRIM(session_string) <> '' "
            "AND deleted_at IS NULL AND frozen_at IS NULL "
            "AND ever_sold IS NOT TRUE AND last_authorized IS NOT FALSE "
            "ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def _save_device_count(stock_id: int, total_devices: int) -> None:
    from .database import db_conn

    try:
        with db_conn() as c:
            c.execute(
                "UPDATE number_stock SET last_device_count=%s WHERE id=%s",
                (int(total_devices), int(stock_id)),
            )
    except Exception as exc:
        logger.warning("تعذر حفظ عدد الأجهزة للحساب %s: %s", stock_id, exc)


async def _check_one(account: Dict[str, Any], client_factory) -> Dict[str, Any]:
    from telethon.tl.functions.account import GetAuthorizationsRequest

    result = {"phone": account["phone_number"], "id": account["id"], "error": None}
    client = None
    try:
        client = client_factory(account["session_string"])
        await asyncio.wait_for(client.connect(), timeout=15)
        response = await asyncio.wait_for(
            client(GetAuthorizationsRequest()), timeout=_PER_ACCOUNT_TIMEOUT
        )
        auths = list(response.authorizations)
        result["total"] = len(auths)
        result["extra"] = count_extra_sessions(auths)
        result["details"] = describe_extra_sessions(auths)
        _save_device_count(account["id"], len(auths))
    except Exception as exc:
        result["error"] = type(exc).__name__
    finally:
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass
    return result


async def scan_owner_extra_sessions(
    client_factory: Callable[[str], Any],
    accounts: Optional[List[Dict[str, Any]]] = None,
    min_extra: int = MIN_EXTRA_SESSIONS,
    progress: Optional[Callable[[int, int], Awaitable[None]]] = None,
) -> Dict[str, Any]:
    accounts = load_owner_accounts() if accounts is None else accounts
    semaphore = asyncio.Semaphore(_CONCURRENCY)
    done = 0

    async def run(account):
        nonlocal done
        async with semaphore:
            res = await _check_one(account, client_factory)
        done += 1
        if progress and done % 25 == 0:
            try:
                await progress(done, len(accounts))
            except Exception:
                pass
        return res

    results = await asyncio.gather(*(run(a) for a in accounts))
    matches = sorted(
        (r for r in results if not r["error"] and r["extra"] >= min_extra),
        key=lambda r: -r["extra"],
    )
    return {
        "scanned": len(accounts),
        "failed": [r["phone"] for r in results if r["error"]],
        "matches": matches,
        "min_extra": min_extra,
    }


async def _kick_one(account: Dict[str, Any], client_factory) -> Dict[str, Any]:
    """يطرد كل الجلسات الأخرى غير جلسة البوت على هذا الحساب (بلا إنشاء أي جلسة جديدة)."""
    from telethon.tl.functions.auth import ResetAuthorizationsRequest

    result = {"phone": account["phone_number"], "id": account["id"], "error": None}
    client = None
    try:
        client = client_factory(account["session_string"])
        await asyncio.wait_for(client.connect(), timeout=15)
        await asyncio.wait_for(client(ResetAuthorizationsRequest()), timeout=20)
        _save_device_count(account["id"], 1)
    except Exception as exc:
        result["error"] = type(exc).__name__
    finally:
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass
    return result


async def kick_extra_sessions(
    client_factory: Callable[[str], Any],
    accounts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """يطرد الجلسات الإضافية لكل حساب في القائمة المعطاة فقط (نتيجة الفحص)."""
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def run(account):
        async with semaphore:
            return await _kick_one(account, client_factory)

    results = await asyncio.gather(*(run(a) for a in accounts))
    return {
        "attempted": len(accounts),
        "succeeded": [r["phone"] for r in results if not r["error"]],
        "failed": [(r["phone"], r["error"]) for r in results if r["error"]],
    }


def format_report(report: Dict[str, Any]) -> List[str]:
    """نصوص جاهزة للإرسال، مقسمة بحيث لا تتجاوز حد تيليجرام."""
    matches = report["matches"]
    head = (
        "📲 حسابات المالك بأكثر من جلسة إضافية\n"
        f"تم فحص {report['scanned']} حساب — "
        f"المطابق (≥{report['min_extra']} جلسات غير البوت): {len(matches)}"
        + (f" — تعذر فحص {len(report['failed'])}" if report["failed"] else "")
    )
    if not matches:
        return [head]
    chunks, current = [], head
    for r in matches:
        block = f"\n\n📱 {r['phone']} — جلسات إضافية: {r['extra']}"
        for detail in r["details"][:6]:
            block += f"\n   • {detail}"
        if len(current) + len(block) > 3800:
            chunks.append(current)
            current = block.lstrip("\n")
        else:
            current += block
    chunks.append(current)
    return chunks
