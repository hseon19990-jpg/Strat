"""Modular SMMMAIN Telegram bot.

The original bot grew as a single script. The sections below are imported in
the same order as the original file, then receive the combined namespace.
That compatibility layer lets the refactor happen without changing callback
behaviour or deployment commands. New work should go in the smallest relevant
section instead of growing ``bot.py``.
"""

from importlib import import_module

_SECTION_NAMES = (
    "shared",
    "database",
    "users",
    "accounts",
    "referrals",
    "security",
    "services",
    "ui",
    "onboarding",
    "messages",
    "callbacks",
    "payments",
    "application",
)

_sections = [import_module(f".{name}", __name__) for name in _SECTION_NAMES]
_namespace = {}
for _section in _sections:
    _namespace.update(
        {key: value for key, value in vars(_section).items() if not key.startswith("__")}
    )

# Functions resolve names in their defining module. Give every section the
# same final namespace so cross-domain calls retain the old runtime behaviour.
for _section in _sections:
    for _key, _value in _namespace.items():
        if not _key.startswith("__"):
            setattr(_section, _key, _value)

globals().update(_namespace)

__all__ = [key for key in _namespace if not key.startswith("_")]
