"""Global maintenance gate.

While maintenance mode is on, nothing except the owner may reach any bot
feature. The older per-handler checks only covered ``handle_callback`` and
``handle_text``; dedicated handlers (Raksh menu/commands, photo and file
uploads, contact sharing, order commands, new payment checkouts) bypassed
them, so members could still use e.g. the Raksh services menu.

This gate runs in an early handler group and stops the update before any
other handler sees it.

Deliberately NOT blocked:
- the owner;
- ``os:`` callbacks (the existing handlers still enforce owner/number-admin
  permissions and the maintenance check for everyone else);
- ``successful_payment`` messages: money has already been taken, so the
  payment must always be processed and credited.
"""

import time

from telegram.ext import ApplicationHandlerStop

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

_CACHE_SECONDS = 2.0
_cache = {"at": 0.0, "value": False}

MAINTENANCE_PLAIN_TEXT = "🛠 البوت في وضع الصيانة حالياً، حاول لاحقاً."


def _maintenance_on_cached() -> bool:
    """Avoid one extra DB read on every single update."""
    now = time.monotonic()
    if now - _cache["at"] > _CACHE_SECONDS:
        try:
            _cache["value"] = bool(is_maintenance_on())
        except Exception:
            # If the setting cannot be read, fail open so the bot is not
            # locked by a transient DB error; per-handler checks still apply.
            _cache["value"] = False
        _cache["at"] = now
    return _cache["value"]


def reset_maintenance_cache() -> None:
    _cache["at"] = 0.0


async def maintenance_gate(update, context) -> None:
    user = update.effective_user
    if not user or user.id == OWNER_ID:
        return
    if not _maintenance_on_cached():
        return

    pre_checkout = getattr(update, "pre_checkout_query", None)
    if pre_checkout is not None:
        # Refusing a checkout before payment is safe: the member is not charged.
        try:
            await pre_checkout.answer(ok=False, error_message=MAINTENANCE_PLAIN_TEXT)
        except Exception:
            pass
        raise ApplicationHandlerStop

    query = getattr(update, "callback_query", None)
    if query is not None:
        if (query.data or "").startswith("os:"):
            return
        try:
            await query.answer()
            await query.edit_message_text(MAINTENANCE_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass  # e.g. "message is not modified" when the notice is already shown
        raise ApplicationHandlerStop

    message = update.effective_message
    chat = update.effective_chat
    if message is not None and chat is not None and chat.type == "private":
        if getattr(message, "successful_payment", None):
            return
        try:
            await message.reply_text(MAINTENANCE_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
        raise ApplicationHandlerStop
