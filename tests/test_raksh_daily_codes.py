import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

_PATH = Path(__file__).parents[1] / "bot_app" / "raksh_system" / "daily_codes.py"
_spec = importlib.util.spec_from_file_location("daily_codes", _PATH)
dc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dc)


class _FakeCursor:
    """يحاكي upsert العدّاد: (day, kind) -> last_value."""

    def __init__(self):
        self.counters = {}

    def execute(self, _sql, params):
        key = (params[0], params[1])
        self.counters[key] = self.counters.get(key, 0) + 1
        self._row = {"last_value": self.counters[key]}
        return self

    def fetchone(self):
        return self._row


def utc(y, m, d, h, mi):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


class DailyCodesTests(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(dc.classify_order_kind("stars", 50), "stars")
        self.assertEqual(dc.classify_order_kind("points", 120), "points")
        self.assertEqual(dc.classify_order_kind("points", 0), "free")
        self.assertEqual(dc.classify_order_kind("contributor_free", 0), "free")

    def test_each_kind_has_its_own_counter(self):
        cur, now = _FakeCursor(), utc(2026, 11, 15, 9, 0)
        seqs = [
            dc.allocate_daily_seq(cur, k, now)[1]
            for k in ("free", "points", "stars", "free", "points", "free")
        ]
        self.assertEqual(seqs, [1, 1, 1, 2, 2, 3])

    def test_counters_reset_at_iraq_midnight(self):
        cur = _FakeCursor()
        # 20:59 UTC = 23:59 بغداد
        for _ in range(99):
            dc.allocate_daily_seq(cur, "stars", utc(2026, 11, 14, 20, 59))
        # 21:00 UTC = 00:00 بغداد (اليوم التالي) -> يبدأ من 1 لا من 100
        day, seq = dc.allocate_daily_seq(cur, "stars", utc(2026, 11, 14, 21, 0))
        self.assertEqual(seq, 1)
        self.assertEqual(str(day), "2026-11-15")

    def test_display_code(self):
        self.assertEqual(
            dc.order_display_code({"id": 7, "daily_kind": "free", "daily_seq": 3}),
            "🎁 مجاني #3",
        )
        # طلب قديم بلا كود يومي
        self.assertEqual(dc.order_display_code({"id": 7}), "#7")


if __name__ == "__main__":
    unittest.main()
