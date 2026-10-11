import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _load_topup_helpers():
    source_path = ROOT / "bot_app" / "payments.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    names = {
        "JEWEL_STAR_TOPUP_MAX",
        "parse_jewel_star_topup_amount",
        "validate_jewel_star_invoice",
    }
    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, (ast.FunctionDef, ast.Assign))
            and (
                node.name in names
                if isinstance(node, ast.FunctionDef)
                else any(
                    isinstance(target, ast.Name) and target.id in names
                    for target in node.targets
                )
            )
        )
    ]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace


class JewelTopupTests(unittest.TestCase):
    def test_custom_quantity_accepts_ascii_and_arabic_digits(self):
        helpers = _load_topup_helpers()
        parse_amount = helpers["parse_jewel_star_topup_amount"]
        self.assertEqual(parse_amount("3"), 3)
        self.assertEqual(parse_amount("١٠"), 10)
        self.assertEqual(parse_amount("۵۰"), 50)

    def test_custom_quantity_rejects_invalid_and_out_of_range_values(self):
        parse_amount = _load_topup_helpers()["parse_jewel_star_topup_amount"]
        self.assertIsNone(parse_amount(""))
        self.assertIsNone(parse_amount("0"))
        self.assertIsNone(parse_amount("-1"))
        self.assertIsNone(parse_amount("10001"))
        self.assertIsNone(parse_amount("abc"))

    def test_invoice_requires_matching_user_price_and_stars_currency(self):
        validate = _load_topup_helpers()["validate_jewel_star_invoice"]
        self.assertEqual(validate("jewel_stars:50:123", 123, 50, "XTR"), 50)
        self.assertIsNone(validate("jewel_stars:50:123", 124, 50, "XTR"))
        self.assertIsNone(validate("jewel_stars:50:123", 123, 49, "XTR"))
        self.assertIsNone(validate("jewel_stars:50:123", 123, 50, "USD"))
        self.assertIsNone(validate("jewel_stars:0:123", 123, 0, "XTR"))
        self.assertIsNone(validate("jewel_stars:50:123:extra", 123, 50, "XTR"))

    def test_default_menu_and_owner_editors_are_registered(self):
        services = (ROOT / "bot_app" / "services.py").read_text(encoding="utf-8")
        callbacks = (ROOT / "bot_app" / "callback_groups_03.py").read_text(encoding="utf-8")
        messages = (ROOT / "bot_app" / "messages.py").read_text(encoding="utf-8")
        self.assertIn('("💎 شحن مجوهرات", "jewels_topup", 2)', services)
        self.assertIn('"os:edit_jewels_asiacell"', services)
        self.assertIn('"os:edit_jewels_ewallet"', services)
        self.assertIn('data == "os:edit_jewels_asiacell"', callbacks)
        self.assertIn('data == "os:edit_jewels_ewallet"', callbacks)
        self.assertIn('state == "os_await_jewels_asiacell_text"', messages)
        self.assertIn('state == "os_await_jewels_ewallet_text"', messages)


if __name__ == "__main__":
    unittest.main()
