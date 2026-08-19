"""Compatibility entry point for the modular Telegram bot.

Railway/Procfile can continue to run ``python bot.py``. Importing this file
also keeps the old ``from bot import ...`` style available.
"""

from bot_app import *  # noqa: F401,F403 - backwards-compatible bot API
from bot_app import Conflict, NetworkError, TimedOut, logger, main, time, traceback


def run_forever() -> None:
    """Run polling with the existing crash-restart policy."""
    restart_delay = 5
    while True:
        last_start_time = time.monotonic()
        try:
            main()
        except SystemExit:
            raise
        except Conflict:
            logger.warning("⚠️ Conflict أثناء polling — انتظار 45 ثانية ثم إعادة التشغيل...")
            time.sleep(45)
            restart_delay = 5
            continue
        except (TimedOut, NetworkError) as transient_error:
            uptime = time.monotonic() - last_start_time
            if uptime > 120:
                restart_delay = 5
            logger.warning(
                "⚠️ Telegram API غير متاح مؤقتاً (%s). "
                "إعادة الاتصال بعد %ss دون إيقاف الخدمة...",
                type(transient_error).__name__,
                restart_delay,
            )
            time.sleep(restart_delay)
            restart_delay = min(restart_delay * 2, 60)
            continue
        except Exception as crash:
            uptime = time.monotonic() - last_start_time
            if uptime > 120:
                restart_delay = 5
            error_name = type(crash).__name__
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
