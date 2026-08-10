"""Internal loader for the split Telegram bot source.

The source chunks are executed in their original order and shared namespace,
so moving the code does not change cross-function name resolution or runtime
behaviour.
"""

from pathlib import Path as _Path

_namespace = {"__name__": "bot", "__package__": None}
_base = _Path(__file__).parent
for _part in sorted(_base.glob("part_*.py")):
    _source = _part.read_text(encoding="utf-8")
    exec(compile(_source, str(_part), "exec"), _namespace, _namespace)

# Keep every original symbol available to callers, including private helpers.
globals().update({
    _key: _value
    for _key, _value in _namespace.items()
    if _key not in {"__name__", "__package__", "__built__"}
})
__all__ = [
    _key for _key in _namespace
    if not _key.startswith("_") and _key not in {"__name__", "__package__", "__built__"}
]
