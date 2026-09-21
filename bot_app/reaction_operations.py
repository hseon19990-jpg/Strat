"""Telegram reaction campaigns executed by the existing bot process.

The web dashboard only writes campaign and post state. This module is the
runtime bridge that uses the bot's existing Telethon sessions from
``number_stock`` and writes progress back to the same PostgreSQL database.
"""

from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime, timezone

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.types import ReactionEmoji

from . import shared as _shared
from .database import db_conn
from .raksh_system.common import _get_raksh_session_lock

globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

_REACTION_EMOJIS = ("👍", "❤️", "🔥", "👏", "😁", "🎉", "🤩", "😱", "😢", "😡", "🤔")
_PUBLIC_POST_RE = re.compile(
    r"^https?://(?:t\.me|telegram\.me)/(?P<channel>[A-Za-z0-9_]+)/(?P<message_id>\d+)(?:\?.*)?/?$",
    re.IGNORECASE,
)
_job_lock = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_reaction_tables() -> None:
    with db_conn() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS reaction_post_accounts (
                id BIGSERIAL PRIMARY KEY,
                post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                stock_id BIGINT NOT NULL,
                account_handle TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                reaction_emoji TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0,
                reacted_at TIMESTAMPTZ,
                leave_after TIMESTAMPTZ,
                left_at TIMESTAMPTZ,
                last_error TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (post_id, stock_id)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS reaction_post_accounts_queue_idx "
            "ON reaction_post_accounts (status, leave_after, updated_at)"
        )


def _parse_public_post(url: str) -> tuple[str, int] | None:
    match = _PUBLIC_POST_RE.match((url or "").strip())
    if not match:
        return None
    return match.group("channel"), int(match.group("message_id"))


def _sync_account(cur, handle: str, status: str, total_reactions: int, action: str) -> None:
    cur.execute(
        """
        INSERT INTO accounts (handle, status, total_reactions, last_action, updated_at)
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT (handle) DO UPDATE SET
          status = EXCLUDED.status,
          total_reactions = EXCLUDED.total_reactions,
          last_action = EXCLUDED.last_action,
          updated_at = NOW()
        """,
        (handle or "tg:unknown", status, total_reactions, action),
    )


def _claim_queued_posts() -> None:
    with db_conn() as cur:
        cur.execute(
            """
            SELECT p.id, p.target_reactions, p.completed_reactions,
                   p.telegram_url, p.status, c.duration_days
            FROM posts p
            JOIN campaigns c ON c.id = p.campaign_id
            WHERE p.status IN ('queued', 'processing')
              AND c.status = 'active'
              AND CURRENT_DATE BETWEEN c.start_date AND c.end_date
              AND COALESCE(p.telegram_url, '') <> ''
              AND COALESCE(p.completed_reactions, 0) < p.target_reactions
            ORDER BY p.published_at ASC
            FOR UPDATE SKIP LOCKED
            """
        )
        posts = cur.fetchall()
        for post in posts:
            parsed = _parse_public_post(post["telegram_url"])
            if not parsed:
                cur.execute(
                    "UPDATE posts SET status = 'failed' WHERE id = %s",
                    (post["id"],),
                )
                cur.execute(
                    """
                    INSERT INTO activity (type, message, tone)
                    VALUES ('warning', %s, 'warning')
                    """,
                    (f"رابط Telegram غير صالح للمنشور #{post['id']}",),
                )
                continue

            cur.execute(
                """
                SELECT COUNT(*) AS waiting
                FROM reaction_post_accounts
                WHERE post_id = %s AND status IN ('pending', 'working')
                """,
                (post["id"],),
            )
            waiting = int((cur.fetchone() or {}).get("waiting") or 0)
            required = max(
                0,
                int(post["target_reactions"] or 0)
                - int(post["completed_reactions"] or 0)
                - waiting,
            )
            if required == 0:
                continue

            cur.execute(
                """
                SELECT ns.id, ns.phone_number
                FROM number_stock ns
                WHERE ns.session_string IS NOT NULL
                  AND BTRIM(ns.session_string) <> ''
                  AND ns.assigned_to IS NULL
                  AND ns.deleted_at IS NULL
                  AND ns.frozen_at IS NULL
                  AND ns.ever_sold IS NOT TRUE
                  AND ns.raksh_excluded IS NOT TRUE
                  AND NOT EXISTS (
                    SELECT 1
                    FROM reaction_post_accounts rpa
                    WHERE rpa.stock_id = ns.id
                      AND rpa.status IN ('pending', 'working', 'reacted', 'leaving')
                  )
                ORDER BY ns.last_authorized DESC NULLS LAST, ns.id
                LIMIT %s
                FOR UPDATE OF ns SKIP LOCKED
                """,
                (required,),
            )
            accounts = cur.fetchall()
            if not accounts:
                continue

            for account in accounts:
                cur.execute(
                    """
                    INSERT INTO reaction_post_accounts (post_id, stock_id, account_handle)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (post_id, stock_id) DO UPDATE
                    SET status = 'pending',
                        attempts = 0,
                        last_error = '',
                        updated_at = NOW()
                    WHERE reaction_post_accounts.status = 'failed'
                    """,
                    (post["id"], account["id"], account["phone_number"] or ""),
                )
            cur.execute(
                "UPDATE posts SET status = 'processing', leave_status = 'in_progress' WHERE id = %s",
                (post["id"],),
            )
            cur.execute(
                """
                INSERT INTO activity (type, message, tone)
                VALUES ('post', %s, 'neutral')
                """,
                (f"تم توزيع {len(accounts)} حسابًا على المنشور #{post['id']}",),
            )


async def _run_account_action(job: dict, action: str) -> tuple[bool, str, str]:
    # Share the same per-account lock as the raksh services. Without this,
    # this scheduler can open the same authorization key while the continuous
    # campaign is using it from another task.
    session_key = str(
        job.get("account_handle") or f"stock:{job.get('stock_id') or ''}"
    ).strip()
    session_lock = _get_raksh_session_lock(session_key)
    async with session_lock:
        async with TelegramClient(
            StringSession(job["session_string"]),
            int(TELEGRAM_API_ID),
            TELEGRAM_API_HASH,
        ) as client:
            channel, message_id = _parse_public_post(job["telegram_url"]) or ("", 0)
            entity = await client.get_entity(channel)
            me = await client.get_me()
            handle = f"@{me.username}" if getattr(me, "username", None) else f"tg:{me.id}"
            if action == "react":
                emoji = random.choice(_REACTION_EMOJIS)
                await client(
                    SendReactionRequest(
                        peer=entity,
                        msg_id=message_id,
                        reaction=[ReactionEmoji(emoticon=emoji)],
                    )
                )
                return True, handle, emoji
            await client(LeaveChannelRequest(channel=entity))
            return True, handle, ""


def _claim_job(status: str) -> dict | None:
    with db_conn() as cur:
        cur.execute(
            """
            SELECT rpa.*, p.telegram_url, p.target_reactions, p.campaign_id,
                   c.duration_days
            FROM reaction_post_accounts rpa
            JOIN posts p ON p.id = rpa.post_id
            JOIN campaigns c ON c.id = p.campaign_id
            WHERE rpa.status = %s
              AND (%s <> 'reacted' OR rpa.leave_after <= NOW())
            ORDER BY rpa.created_at ASC
            LIMIT 1
            FOR UPDATE OF rpa SKIP LOCKED
            """,
            (status, status),
        )
        job = cur.fetchone()
        if not job:
            return None
        cur.execute(
            """
            UPDATE reaction_post_accounts
            SET status = 'working', attempts = attempts + 1, updated_at = NOW()
            WHERE id = %s
            """,
            (job["id"],),
        )
        cur.execute(
            "SELECT session_string FROM number_stock WHERE id = %s",
            (job["stock_id"],),
        )
        session = cur.fetchone()
        if not session or not session["session_string"]:
            cur.execute(
                """
                UPDATE reaction_post_accounts
                SET status = 'failed', last_error = %s, updated_at = NOW()
                WHERE id = %s
                """,
                ("جلسة الحساب غير متاحة", job["id"]),
            )
            return None
        job["session_string"] = session["session_string"]
        return job


def _mark_reaction_success(job: dict, handle: str, emoji: str) -> None:
    with db_conn() as cur:
        cur.execute(
            """
            UPDATE reaction_post_accounts
            SET status = 'reacted',
                account_handle = %s,
                reaction_emoji = %s,
                reacted_at = NOW(),
                leave_after = NOW() + (%s || ' days')::interval,
                last_error = '',
                updated_at = NOW()
            WHERE id = %s
            """,
            (handle, emoji, job["duration_days"], job["id"]),
        )
        cur.execute(
            """
            UPDATE posts
            SET completed_reactions = completed_reactions + 1,
                status = CASE
                  WHEN completed_reactions + 1 >= target_reactions THEN 'completed'
                  ELSE 'processing'
                END
            WHERE id = %s
            """,
            (job["post_id"],),
        )
        cur.execute(
            """
            SELECT COALESCE(SUM(a.total_reactions), 0) AS total
            FROM accounts a WHERE a.handle = %s
            """,
            (handle,),
        )
        total = int((cur.fetchone() or {}).get("total") or 0) + 1
        _sync_account(cur, handle, "reacting", total, f"تفاعل مع المنشور #{job['post_id']}")
        cur.execute(
            "INSERT INTO activity (type, message, tone) VALUES ('reaction', %s, 'success')",
            (f"تم تنفيذ تفاعل {emoji} بواسطة {handle} على المنشور #{job['post_id']}",),
        )


def _mark_action_failed(job: dict, error: str, action: str) -> None:
    with db_conn() as cur:
        attempts = int(job.get("attempts") or 0)
        status = ("pending" if action == "react" else "reacted") if attempts < 3 else "failed"
        cur.execute(
            """
            UPDATE reaction_post_accounts
            SET status = %s, last_error = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (status, error[:500], job["id"]),
        )
        if status == "failed" and action == "react":
            cur.execute(
                "UPDATE posts SET status = 'failed' WHERE id = %s",
                (job["post_id"],),
            )
            cur.execute(
                "INSERT INTO activity (type, message, tone) VALUES ('warning', %s, 'warning')",
                (f"فشل تنفيذ تفاعل المنشور #{job['post_id']}: {error[:180]}",),
            )


def _mark_leave_success(job: dict, handle: str) -> None:
    with db_conn() as cur:
        cur.execute(
            """
            UPDATE reaction_post_accounts
            SET status = 'left', account_handle = %s, left_at = NOW(),
                last_error = '', updated_at = NOW()
            WHERE id = %s
            """,
            (handle, job["id"]),
        )
        cur.execute(
            """
            SELECT COUNT(*) AS remaining
            FROM reaction_post_accounts
            WHERE post_id = %s AND status NOT IN ('left', 'failed')
            """,
            (job["post_id"],),
        )
        remaining = int(cur.fetchone()["remaining"])
        if remaining == 0:
            cur.execute(
                "UPDATE posts SET leave_status = 'completed' WHERE id = %s",
                (job["post_id"],),
            )
        cur.execute("SELECT COALESCE(total_reactions, 0) AS total FROM accounts WHERE handle = %s", (handle,))
        total = int((cur.fetchone() or {}).get("total") or 0)
        _sync_account(cur, handle, "cooldown", total, f"غادر بعد التفاعل مع المنشور #{job['post_id']}")
        cur.execute(
            "INSERT INTO activity (type, message, tone) VALUES ('leave', %s, 'neutral')",
            (f"غادر الحساب {handle} بعد التفاعل مع المنشور #{job['post_id']}",),
        )


async def _process_one(status: str, action: str) -> bool:
    job = _claim_job(status)
    if not job:
        return False
    try:
        success, handle, emoji = await _run_account_action(job, action)
        if success and action == "react":
            _mark_reaction_success(job, handle, emoji)
        elif success:
            _mark_leave_success(job, handle)
    except Exception as error:
        logger.warning("Reaction operation failed for job %s: %s", job.get("id"), error)
        _mark_action_failed(job, str(error), action)
    return True


async def run_reaction_ops_job(_context=None) -> None:
    """Process a small batch so the main bot remains responsive."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return
    if _job_lock.locked():
        return
    async with _job_lock:
        try:
            _ensure_reaction_tables()
            _claim_queued_posts()
            for _ in range(5):
                if not await _process_one("pending", "react"):
                    break
            for _ in range(5):
                if not await _process_one("reacted", "leave"):
                    break
        except Exception:
            logger.exception("Reaction operations scheduler failed")