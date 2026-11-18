import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows, fail=False):
        self.rows = rows
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if self.fail:
            raise RuntimeError("db down")
        return _FakeResult(self.rows)


def _load(rows, fail=False):
    pkg = types.ModuleType("rotpkg")
    pkg.__path__ = []
    db = types.ModuleType("rotpkg.database")
    db.db_conn = lambda: _FakeConn(rows, fail)
    sys.modules["rotpkg"] = pkg
    sys.modules["rotpkg.database"] = db
    spec = importlib.util.spec_from_file_location(
        "rotpkg.session_rotation", ROOT / "bot_app" / "session_rotation.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["rotpkg.session_rotation"] = module
    spec.loader.exec_module(module)
    return module


def _sessions(*phones):
    return [{"phone_number": p, "session_string": "x"} for p in phones]


class SessionRotationTests(unittest.TestCase):
    def test_never_used_first_then_oldest(self):
        rows = [
            {"phone_number": "1", "last_at": 300.0},
            {"phone_number": "2", "last_at": 100.0},
            {"phone_number": "3", "last_at": 200.0},
        ]
        mod = _load(rows)
        for _ in range(20):
            ordered = [s["phone_number"] for s in mod.order_sessions_fairly(
                _sessions("1", "2", "3", "4", "5")
            )]
            self.assertEqual(set(ordered[:2]), {"4", "5"})
            self.assertEqual(ordered[2:], ["2", "3", "1"])

    def test_database_failure_keeps_all_accounts(self):
        mod = _load([], fail=True)
        ordered = mod.order_sessions_fairly(_sessions("1", "2", "3"))
        self.assertEqual(sorted(s["phone_number"] for s in ordered), ["1", "2", "3"])

    def test_single_or_empty_input(self):
        mod = _load([])
        self.assertEqual(mod.order_sessions_fairly([]), [])
        self.assertEqual(len(mod.order_sessions_fairly(_sessions("1"))), 1)

    def test_services_use_fair_ordering(self):
        common = (ROOT / "bot_app/raksh_system/common.py").read_text(encoding="utf-8")
        self.assertIn("order_sessions_fairly(sessions)", common)
        legendary = (ROOT / "bot_app/legendary_comment.py").read_text(encoding="utf-8")
        self.assertNotIn("random.shuffle", legendary)
        self.assertIn("order_sessions_fairly(sessions)", legendary)


if __name__ == "__main__":
    unittest.main()
