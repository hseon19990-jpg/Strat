import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
UTC = timezone.utc


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Conn:
    def __init__(self, script):
        self.script = list(script)
        self.sql = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.sql.append(sql)
        return _Result(self.script.pop(0))


def _load(script):
    conn = _Conn(script)
    if "telegram" not in sys.modules:
        tg = types.ModuleType("telegram")
        tg.InlineKeyboardButton = lambda text, callback_data=None: (text, callback_data)
        tg.InlineKeyboardMarkup = lambda rows: rows
        sys.modules["telegram"] = tg
    pkg = types.ModuleType("statpkg")
    pkg.__path__ = []
    db = types.ModuleType("statpkg.database")
    db.db_conn = lambda: conn
    sys.modules["statpkg"] = pkg
    sys.modules["statpkg.database"] = db
    spec = importlib.util.spec_from_file_location(
        "statpkg.contributor_stats", ROOT / "bot_app" / "contributor_stats.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["statpkg.contributor_stats"] = module
    spec.loader.exec_module(module)
    return module, conn


class ContributorStatsTests(unittest.TestCase):
    def test_top_contributors_lists_count_and_earnings(self):
        mod, _ = _load([
            [{"uid": 1, "username": "ali", "full_name": None, "total": 5,
              "alive": 3, "dead": 2, "earned": 120}],
            [{"members": 7}],
            [{"paid": 900}],
        ])
        text, _kb = mod.top_contributors_view()
        self.assertIn("1) @ali — 5 رقم", text)
        self.assertIn("شغال 3", text)
        self.assertIn("مطرود 2", text)
        self.assertIn("ربحه 120 نقطة", text)
        self.assertIn("أعضاء وضعوا أرقاماً: 7", text)
        self.assertIn("900", text)

    def test_best_numbers_masks_phone_and_shows_state(self):
        mod, _ = _load([[{
            "phone_number": "+9647701234567", "uid": 2, "username": None,
            "full_name": "سامي", "deleted_at": None, "frozen_at": None,
            "last_authorized": False, "has_session": True,
            "earned": 300, "orders": 12,
        }]])
        text, _kb = mod.best_numbers_view()
        self.assertIn("+9647****567", text)
        self.assertNotIn("9647701234567", text)
        self.assertIn("300 نقطة", text)
        self.assertIn("12 طلب", text)
        self.assertIn("مطرود", text)

    def test_kicked_numbers_show_earnings_and_lifetime(self):
        added = datetime(2026, 11, 1, tzinfo=UTC)
        kicked = added + timedelta(days=3)
        mod, conn = _load([
            [{"phone_number": "+9647701234567", "uid": 3, "username": "x",
              "full_name": None, "added_at": added, "kicked_at": kicked,
              "earned": 40, "orders": 4}],
            [{"cnt": 9, "earned": 500}],
        ])
        text, _kb = mod.kicked_numbers_view()
        self.assertIn("ربحت 40 نقطة", text)
        self.assertIn("عملت 3 يوم", text)
        self.assertIn("عددها: 9", text)
        self.assertIn("500 نقطة", text)
        self.assertIn("ever_sold IS NOT TRUE", conn.sql[0])
        self.assertIn("frozen_at IS NULL", conn.sql[0])

    def test_kicked_without_recorded_time(self):
        mod, _ = _load([
            [{"phone_number": "+9647701234567", "uid": 3, "username": None,
              "full_name": None, "added_at": None, "kicked_at": None,
              "earned": 0, "orders": 0}],
            [{"cnt": 1, "earned": 0}],
        ])
        text, _kb = mod.kicked_numbers_view()
        self.assertIn("غير مسجّل", text)

    def test_empty_states_and_error_fallback(self):
        mod, _ = _load([[], [{"members": 0}], [{"paid": 0}]])
        text, _ = mod.top_contributors_view()
        self.assertIn("لم يضف أي عضو", text)
        mod, _ = _load([])  # script exhausted -> exception inside
        text, _ = mod.stats_view("top")
        self.assertIn("تعذر", text)
        text, _ = mod.stats_view("nope")
        self.assertIn("غير معروف", text)

    def test_long_output_is_truncated(self):
        rows = [{"uid": i, "username": "u" * 50, "full_name": "ن" * 300,
                 "total": 1, "alive": 1, "dead": 0, "earned": 1} for i in range(15)]
        mod, _ = _load([])
        text, _ = mod.format_top_contributors(rows, 15, 15)
        self.assertLessEqual(len(text), 3900)

    def test_menu_and_handler_are_wired_for_owner_only_flow(self):
        audit = (ROOT / "bot_app/member_audit.py").read_text(encoding="utf-8")
        for action in ("os:ma:top", "os:ma:best", "os:ma:kickedearn"):
            self.assertIn(action, audit)
        self.assertIn('action in {"top", "best", "kickedearn"}', audit)
        callbacks = (ROOT / "bot_app/callbacks.py").read_text(encoding="utf-8")
        self.assertIn('data.startswith("os:ma:") and is_own', callbacks)


if __name__ == "__main__":
    unittest.main()
