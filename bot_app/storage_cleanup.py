"""Bounded PostgreSQL cleanup and storage diagnostics for transient bot data."""

import asyncio
import logging

from .database import db_conn

logger = logging.getLogger(__name__)

# Quota counters include recent history, so retain every usage row for 48 hours.
USAGE_RETENTION_DAYS = 2
# Keep non-critical audit-like records for two weeks.
TRANSIENT_RETENTION_DAYS = 14
# Limit write load and WAL growth when an old table has accumulated a backlog.
MAX_ROWS_PER_TABLE_PER_RUN = 500


def get_storage_size_snapshot() -> dict:
    """Return database size and the ten largest application tables, without row data."""
    with db_conn() as c:
        database = c.execute(
            "SELECT pg_database_size(current_database()) AS database_bytes"
        ).fetchone()
        tables = c.execute(
            """
            SELECT n.nspname AS schema_name,
                   c.relname AS table_name,
                   pg_total_relation_size(c.oid) AS total_bytes
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'm')
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND n.nspname NOT LIKE 'pg_toast%'
            ORDER BY pg_total_relation_size(c.oid) DESC
            LIMIT 10
            """
        ).fetchall()
    return {
        "database_bytes": int((database or {}).get("database_bytes") or 0),
        "top_tables": [
            {
                "schema": str(row["schema_name"]),
                "table": str(row["table_name"]),
                "bytes": int(row["total_bytes"] or 0),
            }
            for row in (tables or [])
        ],
    }


def log_storage_size_snapshot(label: str) -> None:
    """Log size metadata only; never read or emit customer rows."""
    try:
        snapshot = get_storage_size_snapshot()
        top_tables = ", ".join(
            f"{row['schema']}.{row['table']}={row['bytes']}B"
            for row in snapshot["top_tables"]
        ) or "none"
        logger.info(
            "Storage snapshot %s: database=%sB; largest tables: %s",
            label,
            snapshot["database_bytes"],
            top_tables,
        )
    except Exception:
        # Diagnostics must never prevent the conservative cleanup from running.
        logger.exception("Could not collect storage size diagnostics (%s)", label)


def cleanup_transient_storage_data() -> dict[str, int]:
    """Delete a bounded batch of expired transient rows, preserving operational data."""
    deleted = {}
    with db_conn() as c:
        # Quota logic counts the recent execution window. Never remove a row before
        # 48 hours, and retain older rows while their order is still active.
        c.execute(
            """
            WITH expired AS (
                SELECT usage.id
                FROM raksh_execution_usage AS usage
                WHERE usage.executed_at < NOW() - (%s * INTERVAL '1 day')
                  AND (
                      usage.order_id IS NULL
                      OR EXISTS (
                          SELECT 1
                          FROM raksh_orders AS orders
                          WHERE orders.id = usage.order_id
                            AND orders.status IN ('completed', 'cancelled')
                      )
                      OR NOT EXISTS (
                          SELECT 1
                          FROM raksh_orders AS orders
                          WHERE orders.id = usage.order_id
                      )
                  )
                ORDER BY usage.executed_at, usage.id
                LIMIT %s
            )
            DELETE FROM raksh_execution_usage AS usage
            USING expired
            WHERE usage.id = expired.id
            """,
            (USAGE_RETENTION_DAYS, MAX_ROWS_PER_TABLE_PER_RUN),
        )
        deleted["raksh_execution_usage"] = int(c.rowcount or 0)

        # Daily gift claims only prevent a second claim on the same Baghdad day.
        c.execute(
            """
            WITH expired AS (
                SELECT user_id, claim_date
                FROM daily_gift_claims
                WHERE claim_date < (NOW() AT TIME ZONE 'Asia/Baghdad')::date
                ORDER BY claim_date, user_id
                LIMIT %s
            )
            DELETE FROM daily_gift_claims AS claims
            USING expired
            WHERE claims.user_id = expired.user_id
              AND claims.claim_date = expired.claim_date
            """,
            (MAX_ROWS_PER_TABLE_PER_RUN,),
        )
        deleted["daily_gift_claims"] = int(c.rowcount or 0)

        # The points are already credited; keep expired gift metadata for 14 days.
        # Deleting a gift cascades only to its temporary per-gift claim list.
        c.execute(
            """
            WITH expired AS (
                SELECT id
                FROM temporary_gifts
                WHERE ends_at < NOW() - (%s * INTERVAL '1 day')
                ORDER BY ends_at, id
                LIMIT %s
            )
            DELETE FROM temporary_gifts AS gifts
            USING expired
            WHERE gifts.id = expired.id
            """,
            (TRANSIENT_RETENTION_DAYS, MAX_ROWS_PER_TABLE_PER_RUN),
        )
        deleted["temporary_gifts"] = int(c.rowcount or 0)

        c.execute(
            """
            WITH expired AS (
                SELECT id
                FROM activity
                WHERE created_at < NOW() - (%s * INTERVAL '1 day')
                ORDER BY created_at, id
                LIMIT %s
            )
            DELETE FROM activity
            USING expired
            WHERE activity.id = expired.id
            """,
            (TRANSIENT_RETENTION_DAYS, MAX_ROWS_PER_TABLE_PER_RUN),
        )
        deleted["activity"] = int(c.rowcount or 0)

        # Only abandoned intents without a payment method can expire. Pending
        # invoices and records carrying a payment ID remain for reconciliation.
        c.execute(
            """
            WITH expired AS (
                SELECT id
                FROM smm_payment_intents
                WHERE created_at < NOW() - (%s * INTERVAL '1 day')
                  AND telegram_payment_id IS NULL
                  AND payment_method IS NULL
                  AND status IN ('pending', 'cancelled')
                ORDER BY created_at, id
                LIMIT %s
            )
            DELETE FROM smm_payment_intents AS intents
            USING expired
            WHERE intents.id = expired.id
            """,
            (TRANSIENT_RETENTION_DAYS, MAX_ROWS_PER_TABLE_PER_RUN),
        )
        deleted["smm_payment_intents"] = int(c.rowcount or 0)

    return deleted


async def cleanup_transient_storage_job(context=None) -> None:
    """Log table sizes and run bounded cleanup without blocking the Telegram loop."""
    try:
        await asyncio.to_thread(log_storage_size_snapshot, "before cleanup")
        deleted = await asyncio.to_thread(cleanup_transient_storage_data)
        await asyncio.to_thread(log_storage_size_snapshot, "after cleanup")
        total = sum(deleted.values())
        if total:
            logger.info("Storage cleanup removed %s expired rows: %s", total, deleted)
    except Exception:
        logger.exception("Storage cleanup failed; the next scheduled run will retry")
