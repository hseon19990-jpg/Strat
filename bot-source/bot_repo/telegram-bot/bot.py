"""Compatibility entry point for the split Telegram bot."""

from bot_app import _namespace as _bot_namespace

globals().update({
    _key: _value for _key, _value in _bot_namespace.items()
    if _key not in {"__name__", "__package__", "__built__"}
})
del _bot_namespace

if __name__ == "__main__":
    import time as _time
    _restart_delay = 5
    _last_start_time = 0.0
    while True:
        _last_start_time = _time.monotonic()
        try:
            main()
        except SystemExit:
            raise
        except Exception as _crash:
            _uptime = _time.monotonic() - _last_start_time
            # إذا كان البوت يعمل أكثر من دقيقتين قبل الكراش → أعد التأخير لـ 5 ثوانٍ
            if _uptime > 120:
                _restart_delay = 5
            err_name = type(_crash).__name__
            # Conflict = نسختان تتعارضان أثناء redeploy — انتظر أطول قليلاً ثم أعد
            if "Conflict" in err_name:
                logger.warning(f"⚠️ Conflict أثناء polling — انتظار 45 ثانية ثم إعادة التشغيل...")
                _time.sleep(45)
                _restart_delay = 5
                continue
            logger.critical(
                f"💥 البوت انهار [{err_name}] بعد {_uptime:.0f}ث: {_crash}\n"
                f"{traceback.format_exc()}"
            )
            logger.info(f"🔄 إعادة تشغيل بعد {_restart_delay}ث...")
            _time.sleep(_restart_delay)
            _restart_delay = min(_restart_delay * 2, 30)  # حد أقصى 30 ثانية بدل 60
        else:
            logger.warning("⚠️ run_polling انتهى — إعادة التشغيل...")
            _time.sleep(3)
            _restart_delay = 5
