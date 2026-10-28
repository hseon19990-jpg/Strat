"""Periodic cleanup for PostgreSQL rows that are no longer operationally useful."""

import asyncio
import logging

from .database import db_conn

logger = logging.getLogger(__name__)

# Usage rows are only needed for one-day quotas; keep a 48-hour safety window.
USAGE_RETENTION_DAYS = 2
# Keep non-critical audit-like records for two weeks.
TRANSIENT_RETENTION_DAYS = 14


def cleanup_transient_storage_data() -> dict[str, int]:
    """Delete expired transient rows without touching balances or order ledgers."""
    deleted = {}
    with db_conn() as c:
        c.execute(
            """
            DELETE FROM raksh_execution_usage AS usage
            WHERE (
                (
                    usage.order_id IS NULL
                    AND usage.executed_at < NOW() - (%s * INTERVAL '1 day')
                )
                OR EXISTS (
                    SELECT 1
                    FROM raksh_orders AS orders
                    WHERE orders.id = usage.order_id
                      AND orders.status IN ('completed', 'cancelled')
                )
                OR (
                    usage.order_id IS NOT NULL
                    AND usage.executed_at < NOW() - (%s * INTERVAL '1 day')
                    AND NOT EXISTS (
                        SELECT 1
                        FROM raksh_orders AS orders
                        WHERE orders.id = usage.order_id
                    )
                )
            )
            """,
            (USAGE_RETENTION_DAYS, USAGE_RETENTION_DAYS),
        )
        deleted["raksh_execution_usage"] = int(c.rowcount or 0)

        # Daily gift claims only prevent a second claim on the same Baghdad day.
        c.execute(
            """
            DELETE FROM daily_gift_claims
            WHERE claim_date < (NOW() AT TIME ZONE 'Asia/Baghdad')::date
            """
        )
        deleted["daily_gift_claims"] = int(c.rowcount or 0)

        # The gift's points are already credited to users.points; expired gift
        # metadata and its claim list are disposable after the two-week window.
        c.execute(
            """
            DELETE FROM temporary_gifts
            WHERE ends_at < NOW() - (%s * INTERVAL '1 day')
            """,
            (TRANSIENT_RETENTION_DAYS,),
        )
        deleted["temporary_gifts"] = int(c.rowcount or 0)

        c.execute(
            """
            DELETE FROM activity
            WHERE created_at < NOW() - (%s * INTERVAL '1 day')
            """,
            (TRANSIENT_RETENTION_DAYS,),
        )
        deleted["activity"] = int(c.rowcount or 0)

        # Only uncharged, abandoned intents expire. Paid/completed intents and
        # any intent with a Telegram charge id remain available for reconciliation.
        c.execute(
            """
            DELETE FROM smm_payment_intents
            WHERE created_at < NOW() - (%s * INTERVAL '1 day')
              AND telegram_payment_id IS NULL
              AND status IN ('pending', 'awaiting_payment', 'cancelled', 'failed')
            """,
            (TRANSIENT_RETENTION_DAYS,),
        )
        deleted["smm_payment_intents"] = int(c.rowcount or 0)

    return deleted


async def cleanup_transient_storage_job(context=None) -> None:
    """Run cleanup off the Telegram event loop and keep the bot alive on errors."""
    try:
        deleted = await asyncio.to_thread(cleanup_transient_storage_data)
        total = sum(deleted.values())
        if total:
            logger.info("🧹 Storage cleanup removed %s expired rows", total)
    except Exception:
        logger.exception("Storage cleanup failed; the next scheduled run will retry")
