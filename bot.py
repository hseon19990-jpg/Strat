"""Canonical Telegram bot entry point.

The repository also contains an older nested copy under ``bot_repo``. Keeping
the root package as the only import target prevents deployments from silently
loading that incomplete copy.
"""

from bot_app import *  # noqa: F401,F403 - backwards-compatible bot API
from bot_app import Conflict, logger, main, time, traceback


def run_forever() -> None:
    """Keep the bot process alive and recover from polling interruptions."""
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
            # A clean return from run_polling must not leave Railway with an
            # apparently healthy but non-polling process.
            logger.warning("⚠️ انتهى polling بشكل غير متوقع — إعادة التشغيل بعد 3 ثوانٍ...")
            time.sleep(3)
            restart_delay = 5


if __name__ == "__main__":
    run_forever()
