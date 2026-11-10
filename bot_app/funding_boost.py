"""دعم القنوات الممولة بحسابات البوت.

كل 15 ثانية ينضم إلى كل قناة ممولة نشطة حساب واحد من الحسابات التي يملك البوت
جلستها. وكلما اكتملت عشرة حسابات منضمة لم تتفاعل بعد، تتفاعل العشرة بتفاعل
عشوائي على رسالة من القناة. إن لم توجد رسالة فلا بأس، تُعدّ الدفعة منتهية.

* لا تُحتسب هذه الحسابات ضمن current_members (عداد الأعضاء الحقيقيين).
* يتوقف الدعم عن القناة عند بلوغ عدد الحسابات المنضمة عدد الأعضاء المدفوع له.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji

from . import shared as _shared
from .database import db_conn
from .raksh_system.common import _get_raksh_session_lock

globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

_fb_log = logging.getLogger(__name__)

BOOST_INTERVAL_SECONDS = 15      # انضمام حساب واحد لكل قناة كل هذه المدة
REACT_BATCH_SIZE = 10            # كل 10 حسابات منضمة تتفاعل معاً
MAX_CHANNELS_PER_TICK = 10       # حد أقصى للقنوات المخدومة في الدورة الواحدة
_FB_ACCOUNT_TIMEOUT = 45
_FB_BOOST_EMOJIS = ("👍", "❤️", "🔥", "🎉", "👏", "😍", "🤩")

_fb_job_lock = asyncio.Lock()
_fb_table_ready = False
_fb_flood_until = 0.0                              # توقف شامل عند FloodWait
_fb_channel_fails: dict[str, tuple[int, float]] = {}   # قناة -> (إخفاقات متتالية، تجاهل حتى)
_fb_reacting: set[str] = set()                     # قنوات لها دفعة تفاعل جارية


def _fb_ensure_table() -> None:
    global _fb_table_ready
    if _fb_table_ready:
        return
    with db_conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS funding_boost_joins (
                id               BIGSERIAL PRIMARY KEY,
                channel_username TEXT NOT NULL,
                stock_id         BIGINT NOT NULL,
                status           TEXT NOT NULL DEFAULT 'joined',
                reacted          BOOLEAN NOT NULL DEFAULT FALSE,
                error            TEXT NOT NULL DEFAULT '',
                joined_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (channel_username, stock_id)
            )
            """
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS funding_boost_joins_chan_idx "
            "ON funding_boost_joins (channel_username, status, reacted)"
        )
    _fb_table_ready = True


def _fb_pick_channels() -> list[dict]:
    """القنوات الممولة النشطة التي لم تبلغ حدّها وحان دورها، الأقدم خدمةً أولاً."""
    with db_conn() as c:
        rows = c.execute(
            """
            SELECT f.channel_username AS channel, f.target, COALESCE(s.joined, 0) AS joined
            FROM (
                SELECT cf.channel_username, MAX(cf.target_members) AS target
                FROM channel_funding cf
                JOIN mandatory_channels mc ON mc.channel_username = cf.channel_username
                WHERE cf.status = 'active' AND mc.active = 1 AND cf.target_members > 0
                GROUP BY cf.channel_username
            ) f
            LEFT JOIN (
                SELECT channel_username,
                       COUNT(*) FILTER (WHERE status = 'joined') AS joined,
                       MAX(joined_at) AS last_join
                FROM funding_boost_joins
                GROUP BY channel_username
            ) s ON s.channel_username = f.channel_username
            WHERE COALESCE(s.joined, 0) < f.target
              AND (s.last_join IS NULL
                   OR s.last_join <= NOW() - (%s * INTERVAL '1 second'))
            ORDER BY s.last_join ASC NULLS FIRST
            LIMIT %s
            """,
            (BOOST_INTERVAL_SECONDS - 3, MAX_CHANNELS_PER_TICK),
        ).fetchall()
    return [dict(r) for r in rows or []]


def _fb_pick_account(channel: str) -> dict | None:
    """حساب مخزون لديه جلسة ولم ينضم لهذه القناة من قبل، وغير مباع أو محجوز."""
    with db_conn() as c:
        row = c.execute(
            """
            SELECT ns.id, ns.phone_number, ns.session_string
            FROM number_stock ns
            WHERE ns.session_string IS NOT NULL
              AND BTRIM(ns.session_string) <> ''
              AND ns.assigned_to IS NULL
              AND ns.deleted_at IS NULL
              AND ns.frozen_at IS NULL
              AND ns.ever_sold IS NOT TRUE
              AND ns.raksh_excluded IS NOT TRUE
              AND ns.last_authorized IS NOT FALSE
              AND NOT EXISTS (SELECT 1 FROM number_admins na WHERE na.stock_id = ns.id)
              AND NOT EXISTS (
                  SELECT 1 FROM funding_boost_joins j
                  WHERE j.channel_username = %s AND j.stock_id = ns.id
              )
            ORDER BY random()
            LIMIT 1
            """,
            (channel,),
        ).fetchone()
    return dict(row) if row else None


def _fb_record(channel: str, stock_id: int, status: str, error: str = "") -> None:
    with db_conn() as c:
        c.execute(
            "INSERT INTO funding_boost_joins (channel_username, stock_id, status, error) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (channel_username, stock_id) DO NOTHING",
            (channel, stock_id, status, error[:300]),
        )


def _fb_pending_reactors(channel: str, limit: int) -> list[dict]:
    with db_conn() as c:
        rows = c.execute(
            """
            SELECT j.id AS join_id, ns.id, ns.phone_number, ns.session_string
            FROM funding_boost_joins j
            JOIN number_stock ns ON ns.id = j.stock_id
            WHERE j.channel_username = %s AND j.status = 'joined' AND j.reacted = FALSE
              AND ns.session_string IS NOT NULL AND BTRIM(ns.session_string) <> ''
            ORDER BY j.id
            LIMIT %s
            """,
            (channel, limit),
        ).fetchall()
    return [dict(r) for r in rows or []]


def _fb_count_unreacted(channel: str) -> int:
    with db_conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM funding_boost_joins "
            "WHERE channel_username = %s AND status = 'joined' AND reacted = FALSE",
            (channel,),
        ).fetchone()
    return int((row or {}).get("n") or 0)


def _fb_mark_reacted(join_ids: list[int]) -> None:
    if not join_ids:
        return
    with db_conn() as c:
        c.execute(
            "UPDATE funding_boost_joins SET reacted = TRUE WHERE id = ANY(%s)",
            (join_ids,),
        )


async def _fb_join_with_account(channel: str, account: dict) -> None:
    session_lock = _get_raksh_session_lock(account)
    async with session_lock:
        async with TelegramClient(
            StringSession(account["session_string"]),
            int(TELEGRAM_API_ID),
            TELEGRAM_API_HASH,
        ) as client:
            entity = await client.get_entity(channel)
            await client(JoinChannelRequest(entity))


def _fb_is_channel_level_error(error: Exception) -> bool:
    """أخطاء سببها القناة نفسها (لا الحساب): لا نحرق بها بقية الحسابات."""
    name = type(error).__name__
    return isinstance(error, ValueError) or name in {
        "UsernameInvalidError", "UsernameNotOccupiedError", "ChannelPrivateError",
        "ChannelInvalidError", "InviteHashExpiredError", "InviteHashInvalidError",
    }


async def _fb_join_one(channel: str) -> bool:
    """ينضم حساب واحد للقناة. يعيد True إن نجح الانضمام."""
    global _fb_flood_until
    failures, ignore_until = _fb_channel_fails.get(channel, (0, 0.0))
    if ignore_until > time.monotonic():
        return False
    account = await asyncio.to_thread(_fb_pick_account, channel)
    if not account:
        return False
    try:
        await asyncio.wait_for(_fb_join_with_account(channel, account), timeout=_FB_ACCOUNT_TIMEOUT)
    except FloodWaitError as error:
        _fb_flood_until = time.monotonic() + min(int(getattr(error, "seconds", 60) or 60), 300)
        _fb_log.warning("FloodWait أثناء دعم @%s: إيقاف مؤقت %ss", channel, getattr(error, "seconds", "?"))
        return False
    except Exception as error:
        if _fb_is_channel_level_error(error):
            failures += 1
            _fb_channel_fails[channel] = (
                failures,
                time.monotonic() + (600 if failures >= 3 else 0),
            )
            _fb_log.warning("تعذر الوصول للقناة @%s لدعمها: %s", channel, error)
        else:
            await asyncio.to_thread(_fb_record, channel, account["id"], "failed", str(error))
            _fb_log.info("تعذر انضمام الحساب %s إلى @%s: %s", account["id"], channel, error)
        return False
    _fb_channel_fails.pop(channel, None)
    await asyncio.to_thread(_fb_record, channel, account["id"], "joined")
    return True


async def _fb_latest_message_id(client, entity) -> int | None:
    """أحدث رسالة عادية في القناة (تجاهل رسائل الخدمة)، أو None."""
    async for message in client.iter_messages(entity, limit=10):
        if getattr(message, "id", None) and getattr(message, "action", None) is None:
            return int(message.id)
    return None


async def _fb_react_with_account(account: dict, channel: str, message_id: int | None):
    """يتفاعل الحساب على الرسالة. إن كان message_id فارغاً يبحث عن أحدث رسالة ويعيد معرّفها."""
    session_lock = _get_raksh_session_lock(account)
    async with session_lock:
        async with TelegramClient(
            StringSession(account["session_string"]),
            int(TELEGRAM_API_ID),
            TELEGRAM_API_HASH,
        ) as client:
            entity = await client.get_entity(channel)
            if message_id is None:
                message_id = await _fb_latest_message_id(client, entity)
                if message_id is None:
                    return None
            await client(
                SendReactionRequest(
                    peer=entity,
                    msg_id=message_id,
                    reaction=[ReactionEmoji(emoticon=random.choice(_FB_BOOST_EMOJIS))],
                )
            )
            return message_id


async def _fb_react_batch(channel: str) -> None:
    """تتفاعل أقدم 10 حسابات منضمة على رسالة من القناة؛ غياب الرسالة ليس خطأ."""
    try:
        batch = await asyncio.to_thread(_fb_pending_reactors, channel, REACT_BATCH_SIZE)
        if len(batch) < REACT_BATCH_SIZE:
            return
        message_id = None
        for index, account in enumerate(batch):
            try:
                found = await asyncio.wait_for(
                    _fb_react_with_account(account, channel, message_id),
                    timeout=_FB_ACCOUNT_TIMEOUT,
                )
                if index == 0 and found is None:
                    break            # لا توجد رسالة للتفاعل معها: لا بأس
                message_id = found or message_id
            except FloodWaitError:
                break
            except Exception as error:
                _fb_log.info("تعذر تفاعل الحساب %s في @%s: %s", account["id"], channel, error)
                if index == 0 and message_id is None:
                    break
            await asyncio.sleep(random.uniform(1.0, 2.5))
        # تُعدّ الدفعة منتهية سواء تفاعلت أم لا، حتى لا تتكرر المحاولة بلا نهاية.
        await asyncio.to_thread(_fb_mark_reacted, [a["join_id"] for a in batch])
    except Exception:
        _fb_log.exception("فشل تفاعل دفعة دعم القناة @%s", channel)
    finally:
        _fb_reacting.discard(channel)


async def run_funding_boost_job(_context=None) -> None:
    """يُشغَّل كل 15 ثانية: ينضم حساب واحد لكل قناة ممولة، ويطلق التفاعل كل 10."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return
    if time.monotonic() < _fb_flood_until or _fb_job_lock.locked():
        return
    async with _fb_job_lock:
        try:
            await asyncio.to_thread(_fb_ensure_table)
            channels = await asyncio.to_thread(_fb_pick_channels)
            for item in channels:
                channel = item["channel"]
                if time.monotonic() < _fb_flood_until:
                    break
                if await _fb_join_one(channel) and channel not in _fb_reacting:
                    unreacted = await asyncio.to_thread(_fb_count_unreacted, channel)
                    if unreacted >= REACT_BATCH_SIZE:
                        _fb_reacting.add(channel)
                        asyncio.ensure_future(_fb_react_batch(channel))
        except Exception:
            _fb_log.exception("مهمة دعم القنوات الممولة فشلت")
