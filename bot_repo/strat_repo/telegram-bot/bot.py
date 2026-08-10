"""Compatibility entry point for the split Telegram bot."""

from bot_app import _namespace as _bot_namespace

globals().update({
    _key: _value for _key, _value in _bot_namespace.items()
    if _key not in {"__name__", "__package__", "__built__"}
})
del _bot_namespace

if __name__ == "__main__":
    main()
