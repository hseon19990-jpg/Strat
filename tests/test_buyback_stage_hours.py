import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
BUYBACK = ROOT / "bot_app" / "buyback.py"

_FUNCS = (
    "_buyback_stage_hours",
    "set_buyback_stage_hours",
    "buyback_total_hours",
    "format_buyback_hours",
    "buyback_total_label",
)


def _load(store):
    tree = ast.parse(BUYBACK.read_text(encoding="utf-8"))
    nodes = [
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name in _FUNCS
    ]
    ns = {
        "BUYBACK_STAGE1_HOURS_KEY": "buyback_stage1_hours",
        "BUYBACK_STAGE2_HOURS_KEY": "buyback_stage2_hours",
        "DEFAULT_BUYBACK_STAGE1_HOURS": 24,
        "DEFAULT_BUYBACK_STAGE2_HOURS": 24,
        "BUYBACK_STAGE_MIN_HOURS": 0,
        "BUYBACK_STAGE_MAX_HOURS": 720,
        "get_setting": lambda k: store.get(k),
        "set_setting": lambda k, v: store.__setitem__(k, v),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(BUYBACK), "exec"), ns)
    return ns


class BuybackStageHoursTests(unittest.TestCase):
    def test_defaults_keep_the_old_24_plus_24(self):
        ns = _load({})
        self.assertEqual(ns["_buyback_stage_hours"](1), 24)
        self.assertEqual(ns["_buyback_stage_hours"](2), 24)
        self.assertEqual(ns["buyback_total_hours"](), 48)
        self.assertEqual(ns["buyback_total_label"](), "2 يوم")

    def test_owner_can_change_each_stage_independently(self):
        store = {}
        ns = _load(store)
        ns["set_buyback_stage_hours"](1, 6)
        ns["set_buyback_stage_hours"](2, 72)
        self.assertEqual(ns["_buyback_stage_hours"](1), 6)
        self.assertEqual(ns["_buyback_stage_hours"](2), 72)
        self.assertEqual(ns["buyback_total_hours"](), 78)

    def test_zero_means_no_wait_and_out_of_range_is_rejected(self):
        store = {}
        ns = _load(store)
        self.assertEqual(ns["set_buyback_stage_hours"](1, 0), 0)
        self.assertEqual(ns["format_buyback_hours"](0), "بدون انتظار")
        with self.assertRaises(ValueError):
            ns["set_buyback_stage_hours"](1, -1)
        with self.assertRaises(ValueError):
            ns["set_buyback_stage_hours"](2, 721)

    def test_corrupt_saved_value_falls_back_to_default(self):
        ns = _load({"buyback_stage1_hours": "abc", "buyback_stage2_hours": "9999"})
        self.assertEqual(ns["_buyback_stage_hours"](1), 24)
        self.assertEqual(ns["_buyback_stage_hours"](2), 24)

    def test_hours_formatting(self):
        fmt = _load({})["format_buyback_hours"]
        self.assertEqual(fmt(12), "12 ساعة")
        self.assertEqual(fmt(72), "3 يوم")
        self.assertEqual(fmt(30), "1 يوم و6 ساعة")

    def test_no_hardcoded_24_hour_interval_or_48_text_remains(self):
        source = BUYBACK.read_text(encoding="utf-8")
        self.assertNotIn("INTERVAL '24 hours'", source)
        self.assertNotIn("فحص 48 ساعة", source)
        self.assertIn("(%s * INTERVAL '1 hour')", source)

    def test_owner_controls_are_wired(self):
        services = (ROOT / "bot_app" / "services.py").read_text(encoding="utf-8")
        ui = (ROOT / "bot_app" / "ui.py").read_text(encoding="utf-8")
        cb = (ROOT / "bot_app" / "callback_groups_04.py").read_text(encoding="utf-8")
        msg = (ROOT / "bot_app" / "messages.py").read_text(encoding="utf-8")
        for key in ("os:edit_buyback_stage1", "os:edit_buyback_stage2"):
            self.assertIn(key, services)
            self.assertIn(key, ui)
            self.assertIn(key, cb)
        self.assertIn('f"os_await_buyback_stage{stage}"', cb)
        self.assertIn('state in ("os_await_buyback_stage1", "os_await_buyback_stage2")', msg)


if __name__ == "__main__":
    unittest.main()


class BuybackImmediateRakshTests(unittest.TestCase):
    def setUp(self):
        self.source = BUYBACK.read_text(encoding="utf-8")

    def test_released_at_acceptance_in_both_acceptance_paths(self):
        self.assertEqual(self.source.count("paid=False,"), 2)  # confirm + twofa-reset job

    def test_not_sellable_to_members_until_paid(self):
        helper = self.source[self.source.index("def _release_buyback_account_to_stock"):self.source.index("def mark_buyback_paid")]
        self.assertIn(", not paid)", helper)
        self.assertIn("sale_excluded=EXCLUDED.sale_excluded", helper)
        self.assertIn("SET sale_excluded=FALSE", helper)

    def test_reject_removes_released_account_from_stock(self):
        start = self.source.index("def reject_buyback_offer")
        block = self.source[start:self.source.index("async def process_buyback_twofa_reset_job")]
        self.assertIn("accepted_at", block)
        self.assertIn("UPDATE number_stock SET deleted_at=NOW()", block)
