"""توزيع عادل لحسابات الرشق + تشخيص الحسابات المستبعدة.

المشكلة: الاختيار العشوائي الصرف قد يترك بعض الحسابات بلا استخدام لفترات
طويلة، خصوصاً عندما تكون كمية الطلب أقل من عدد الحسابات. هنا نرتب الحسابات
بحيث يأتي أولاً الحساب الذي لم يُستخدم قط، ثم الأقدم استخداماً، فيدور
الاستخدام على كل الحسابات المتاحة بالتساوي.

لا يغيّر هذا الملف شروط الاستبعاد نفسها (المباع، المستبعد يدوياً، المجمّد،
رفض المؤجر)؛ هذه قرارات مقصودة.
"""

from __future__ import annotations

import logging
import random
from typing import Dict, List

from .database import db_conn

logger = logging.getLogger(__name__)


def order_sessions_fairly(sessions: List[Dict]) -> List[Dict]:
    """رتّب الحسابات: لم يُستخدم قط أولاً، ثم الأقدم استخداماً.

    الحسابات المتساوية في آخر استخدام تُرتب عشوائياً حتى لا يتكرر نفس
    الترتيب. إذا فشل الاستعلام نرجع للعشوائية العادية فلا يتعطل أي طلب.
    """
    shuffled = list(sessions)
    random.shuffle(shuffled)
    if len(shuffled) < 2:
        return shuffled

    phones = sorted({
        str(item.get("phone_number") or "").strip()
        for item in shuffled
        if item.get("phone_number")
    })
    if not phones:
        return shuffled

    try:
        with db_conn() as c:
            rows = c.execute(
                "SELECT phone_number, "
                "EXTRACT(EPOCH FROM MAX(executed_at)) AS last_at "
                "FROM raksh_execution_usage "
                "WHERE phone_number = ANY(%s) "
                "GROUP BY phone_number",
                (phones,),
            ).fetchall()
        last_used = {
            str(row["phone_number"]).strip(): float(row["last_at"] or 0)
            for row in rows
        }
    except Exception:
        logger.exception("تعذر قراءة آخر استخدام للحسابات؛ سيُستخدم ترتيب عشوائي")
        return shuffled

    # الفرز مستقر، لذلك يبقى الخلط العشوائي كفاصل بين المتساويين.
    shuffled.sort(
        key=lambda item: last_used.get(
            str(item.get("phone_number") or "").strip(), 0.0
        )
    )
    return shuffled


_USABLE_SQL = (
    "deleted_at IS NULL "
    "AND session_string IS NOT NULL AND BTRIM(session_string) <> '' "
    "AND frozen_at IS NULL "
    "AND ever_sold IS NOT TRUE "
    "AND raksh_excluded IS NOT TRUE"
)


def get_raksh_account_diagnostics() -> Dict[str, int]:
    """عدّ حسابات المخزون غير المحذوفة حسب سبب عدم دخولها في الرشق."""
    result: Dict[str, int] = {
        "usable": 0,
        "sold": 0,
        "excluded": 0,
        "frozen": 0,
        "no_session": 0,
        "blocked_some": 0,
        "unauthorized": 0,
        "idle_7d": 0,
        "never_used": 0,
    }
    with db_conn() as c:
        rows = c.execute(
            """
            SELECT CASE
                WHEN COALESCE(BTRIM(session_string), '') = '' THEN 'no_session'
                WHEN ever_sold IS TRUE THEN 'sold'
                WHEN raksh_excluded IS TRUE THEN 'excluded'
                WHEN frozen_at IS NOT NULL THEN 'frozen'
                ELSE 'usable'
            END AS reason, COUNT(*) AS cnt
            FROM number_stock
            WHERE deleted_at IS NULL
            GROUP BY 1
            """
        ).fetchall()
        for row in rows:
            result[row["reason"]] = int(row["cnt"] or 0)

        row = c.execute(
            f"SELECT COUNT(*) AS cnt FROM number_stock WHERE {_USABLE_SQL} "
            "AND last_authorized IS FALSE"
        ).fetchone()
        result["unauthorized"] = int(row["cnt"] or 0) if row else 0

        row = c.execute(
            f"SELECT COUNT(*) AS cnt FROM number_stock WHERE {_USABLE_SQL} "
            "AND EXISTS (SELECT 1 FROM raksh_contributor_service_blocks b "
            "WHERE b.contributor_id = number_stock.contributed_by)"
        ).fetchone()
        result["blocked_some"] = int(row["cnt"] or 0) if row else 0

        row = c.execute(
            f"SELECT COUNT(*) AS cnt FROM number_stock ns WHERE {_USABLE_SQL} "
            "AND NOT EXISTS (SELECT 1 FROM raksh_execution_usage u "
            "WHERE u.phone_number = ns.phone_number "
            "AND u.executed_at >= NOW() - INTERVAL '7 days')"
        ).fetchone()
        result["idle_7d"] = int(row["cnt"] or 0) if row else 0

        row = c.execute(
            f"SELECT COUNT(*) AS cnt FROM number_stock ns WHERE {_USABLE_SQL} "
            "AND NOT EXISTS (SELECT 1 FROM raksh_execution_usage u "
            "WHERE u.phone_number = ns.phone_number)"
        ).fetchone()
        result["never_used"] = int(row["cnt"] or 0) if row else 0
    return result


def format_raksh_account_diagnostics(data: Dict[str, int]) -> str:
    return (
        "📊 تشخيص حسابات الرشق\n\n"
        f"✅ حسابات تدخل الرشق: {data['usable']}\n"
        f"   • منها لم تُستخدم قط: {data['never_used']}\n"
        f"   • منها بلا استخدام آخر 7 أيام: {data['idle_7d']}\n"
        f"   • منها جلستها غير مصرح بها (تُجرَّب وقد تفشل): {data['unauthorized']}\n"
        f"   • منها محجوبة عند بعض الخدمات برفض المؤجر: {data['blocked_some']}\n\n"
        "⛔ حسابات لا تدخل الرشق:\n"
        f"   • مباعة: {data['sold']}\n"
        f"   • مستبعدة يدوياً: {data['excluded']}\n"
        f"   • مجمّدة: {data['frozen']}\n"
        f"   • بلا جلسة: {data['no_session']}"
    )


async def cmd_raksh_accounts(update, context) -> None:
    """/raksh_accounts — للمالك فقط."""
    from .shared import OWNER_ID

    user = update.effective_user
    if not user or int(user.id) != int(OWNER_ID):
        return
    try:
        text = format_raksh_account_diagnostics(get_raksh_account_diagnostics())
    except Exception as exc:
        logger.exception("فشل تشخيص حسابات الرشق")
        text = f"❌ تعذر قراءة التشخيص: {str(exc)[:120]}"
    await update.message.reply_text(text)
