import ast
import unittest
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _load_smm_price_helpers():
    source = (ROOT / "bot_app" / "services.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        "smm_stars_cost",
        "smm_jewels_cost",
        "smm_price_rates",
        "smm_service_cost_points",
        "fmt_jewel_amount",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {
        "SMM_POINTS_PER_STAR": 1000,
        "SMM_POINTS_PER_JEWEL": 1000,
        "Decimal": Decimal,
        "InvalidOperation": InvalidOperation,
        "ROUND_CEILING": ROUND_CEILING,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / "bot_app" / "services.py"), "exec"), namespace)
    return namespace


class SmmPaymentMethodTests(unittest.TestCase):
    def test_stars_cost_uses_one_star_per_thousand_and_rounds_up(self):
        helpers = _load_smm_price_helpers()
        self.assertEqual(helpers["smm_stars_cost"](0), 0)
        self.assertEqual(helpers["smm_stars_cost"](1), 1)
        self.assertEqual(helpers["smm_stars_cost"](1000), 1)
        self.assertEqual(helpers["smm_stars_cost"](1001), 2)

    def test_jewels_use_one_jewel_per_cent_and_round_up(self):
        helpers = _load_smm_price_helpers()
        jewels_cost = helpers["smm_jewels_cost"]
        self.assertEqual(jewels_cost(0), 0)
        self.assertEqual(jewels_cost(1000), 1)
        self.assertEqual(jewels_cost(1001), 2)
        self.assertEqual(jewels_cost(9100), 10)

    def test_service_rate_preview_shows_stars_and_jewels(self):
        helpers = _load_smm_price_helpers()
        self.assertEqual(helpers["smm_price_rates"](5000), (5, 5))
        self.assertEqual(helpers["smm_price_rates"](9100), (10, 10))

    def test_service_cost_keeps_decimal_cent_value_before_rounding_checkout(self):
        helpers = _load_smm_price_helpers()
        points = helpers["smm_service_cost_points"](1000, 9100.0)
        self.assertEqual(points, 9100)
        self.assertEqual(helpers["smm_jewels_cost"](points), 10)
        self.assertEqual(helpers["smm_stars_cost"](points), 10)

    def test_decimal_jewel_balance_is_displayed_without_losing_fraction(self):
        formatter = _load_smm_price_helpers()["fmt_jewel_amount"]
        self.assertEqual(formatter("0.100000"), "0.1")
        self.assertEqual(formatter("2.400000"), "2.4")
        self.assertEqual(formatter("1200.400000"), "1,200.4")

    def test_smm_orders_do_not_charge_or_credit_points(self):
        source = (ROOT / "bot_app" / "smm_payments.py").read_text(encoding="utf-8")
        self.assertIn("VALUES (%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s,%s)", source)
        self.assertNotIn("deduct_points(", source)
        self.assertNotIn("add_points(", source)
        self.assertIn("payment_method", source)
        self.assertIn("cost_jewels", source)

    def test_checkout_offers_stars_or_jewels_and_not_points(self):
        source = (ROOT / "bot_app" / "messages.py").read_text(encoding="utf-8")
        self.assertIn('callback_data=f"smm:pay:stars:{intent_id}"', source)
        self.assertIn('callback_data=f"smm:pay:jewels:{intent_id}"', source)
        self.assertIn("⭐ السعر:", source)
        self.assertIn("💎 السعر:", source)

    def test_owner_can_gift_jewels_and_smm_rate_is_fixed(self):
        callback_source = (ROOT / "bot_app" / "callback_groups_04.py").read_text(encoding="utf-8")
        message_source = (ROOT / "bot_app" / "messages.py").read_text(encoding="utf-8")
        security_source = (ROOT / "bot_app" / "security.py").read_text(encoding="utf-8")
        self.assertIn('callback_data="os:give_jewels"', callback_source)
        self.assertNotIn('callback_data="os:raksh_jewel_rate"', callback_source)
        self.assertIn('state == "os_await_jewels_amount"', message_source)
        self.assertIn("معدل مجوهرات خدمات الرشق ثابت", message_source)
        self.assertIn("def add_jewels(", security_source)


if __name__ == "__main__":
    unittest.main()
