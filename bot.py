"""Compatibility entry point for the modular Telegram bot.

The repository contains a newer bot under ``bot_repo/telegram-bot``. The
Docker image already starts there, while the root Procfile starts this file.
Put the newer package first so both launch paths use the same Raksh system.
"""

from pathlib import Path
import sys

_NESTED_BOT_DIR = Path(__file__).resolve().parent / "bot_repo" / "telegram-bot"
if _NESTED_BOT_DIR.is_dir():
    sys.path.insert(0, str(_NESTED_BOT_DIR))

from bot_app import *  # noqa: F401,F403 - backwards-compatible bot API
from bot_app import Conflict, logger, main, time, traceback


def run_forever() -> None:
    """Run polling with the existing crash-restart policy."""
    restart_delay = 5
    while True:
        last_start_time = time.monotonic()
        try:
            main()
        except SystemExit:
            raise
        except Exception as crash:
            uptime = time.monotonic() - last_start_time
            if uptime > 120:
                restart_delay = 5
            error_name = type(crash).__name__
            if "Conflict" in error_name:
                logger.warning("⚠️ Conflict أثناء polling — انتظار 45 ثانية ثم إعادة التشغيل...")
                time.sleep(45)
                restart_delay = 5
                continue
            logger.critical(
                f"💥 البوت انهار [{error_name}] بعد {uptime:.0f}ث: {crash}\n"
                f"{traceback.format_exc()}"
            )
            logger.info(f"🔄 إعادة تشغيل بعد {restart_delay}ث...")
            time.sleep(restart_delay)
            restart_delay = min(restart_delay * 2, 30)
        else:
            logger.warning("⚠️ run_polling انتهى — إعادة التشغيل...")
            time.sleep(3)
            restart_delay = 5


if __name__ == "__main__":
    run_forever()
