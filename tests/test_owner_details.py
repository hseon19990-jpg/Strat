import ast
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "bot_app" / "owner_details.py"
FUNCS = {
    "od_order_progress", "od_find_nouser_blocks", "od_report_math", "od_day_bounds",
    "od_pay_text", "od_nav_row", "od_status_label", "od_fmt_dt",
}
CONSTS = {"OD_TZ", "OD_STAR_USD_DEFAULT", "OD_JEWEL_GIFT_USD_DEFAULT", "OD_STATUS_LABELS"}


class _Btn:
    def __init__(self, text, callback_data=None):
        self.text, self.callback_data = text, callback_data


def _load():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    nodes = [
        n for n in tree.body
        if (isinstance(n, ast.FunctionDef) and n.name in FUNCS)
        or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in CONSTS for t in n.targets))
    ]
    ns = {
        "Decimal": Decimal, "datetime": datetime, "timedelta": timedelta,
        "timezone": timezone, "InlineKeyboardButton": _Btn,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), ns)
    return ns


class OwnerDetailsTests(unittest.TestCase):
    def setUp(self):
        self.ns = _load()

    def test_progress_from_provider_remains(self):
        key, got, left = self.ns["od_order_progress"](
            {"quantity": 1000, "status": "pending"}, {"status": "In progress", "remains": "700"})
        self.assertEqual((key, got, left), ("in progress", 300, 700))

    def test_progress_completed_local_and_partial(self):
        p = self.ns["od_order_progress"]
        self.assertEqual(p({"quantity": 500, "status": "completed"}), ("completed", 500, 0))
        key, got, left = p({"quantity": 500, "status": "completed", "partial_refund_pts": 10})
        self.assertEqual(key, "partial")
        self.assertIsNone(got)

    def test_progress_unknown_when_api_down(self):
        key, got, left = self.ns["od_order_progress"]({"quantity": 100, "status": "pending"}, {})
        self.assertEqual((key, got, left), ("pending", None, None))

    def test_progress_clamps_remains(self):
        _k, got, left = self.ns["od_order_progress"](
            {"quantity": 100, "status": "pending"}, {"remains": "999"})
        self.assertEqual((got, left), (0, 100))

    def test_three_of_five_without_username(self):
        rows = []
        # الداعي 1: 5 مدعوين، 3 بلا يوزر => تنبيه
        for i, u in enumerate(["a", "", None, "d", ""], start=1):
            rows.append({"invited_by": 1, "user_id": 10 + i, "username": u})
        # الداعي 2: 5 مدعوين، 2 بلا يوزر => لا تنبيه
        for i, u in enumerate(["a", "b", "", "d", ""], start=1):
            rows.append({"invited_by": 2, "user_id": 20 + i, "username": u})
        # الداعي 3: 4 فقط => لا مجموعة كاملة
        for i in range(4):
            rows.append({"invited_by": 3, "user_id": 30 + i, "username": ""})
        alerts = self.ns["od_find_nouser_blocks"](rows)
        self.assertEqual([(a["inviter"], a["block_no"], a["missing"]) for a in alerts], [(1, 1, 3)])

    def test_second_block_is_separate_alert(self):
        rows = [{"invited_by": 7, "user_id": i, "username": "x"} for i in range(5)]
        rows += [{"invited_by": 7, "user_id": 100 + i, "username": ""} for i in range(5)]
        alerts = self.ns["od_find_nouser_blocks"](rows)
        self.assertEqual([(a["block_no"], a["missing"]) for a in alerts], [(2, 5)])

    def test_report_math_uses_given_rates(self):
        r = self.ns["od_report_math"](1000, "1.5", "100")
        self.assertEqual(r["earned_usd"], Decimal("12.75"))
        self.assertEqual(r["gifted_usd"], Decimal("1.500"))
        self.assertEqual(r["spent_usd"], Decimal("1.5"))
        self.assertEqual(r["net_usd"], Decimal("9.750"))

    def test_report_math_empty_day(self):
        r = self.ns["od_report_math"](0, 0, 0)
        self.assertEqual(r["net_usd"], Decimal("0"))

    def test_day_bounds_are_utc_plus_3(self):
        from datetime import date
        start, end = self.ns["od_day_bounds"](date(2026, 11, 11))
        self.assertEqual(end - start, timedelta(days=1))
        self.assertEqual(start.utcoffset(), timedelta(hours=3))

    def test_pay_text(self):
        p = self.ns["od_pay_text"]
        self.assertEqual(p({"payment_method": "stars", "cost_stars": 50}), "50 ⭐")
        self.assertEqual(p({"payment_method": "jewels", "cost_jewels": 7}), "7 💎")
        self.assertEqual(p({"payment_method": "free"}), "مجاناً")

    def test_nav_row(self):
        nav = self.ns["od_nav_row"]("od:orders", 6, 20, 6)
        self.assertEqual([b.callback_data for b in nav], ["od:orders:0", "od:orders:12"])
        self.assertEqual(self.ns["od_nav_row"]("x", 0, 3, 6), [])


if __name__ == "__main__":
    unittest.main()
