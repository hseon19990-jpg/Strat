import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SERVICES = ROOT / "bot_app" / "services.py"


def _load_order_helper():
    tree = ast.parse(SERVICES.read_text(encoding="utf-8"))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "_raksh_menu_order_with_message_before_orders"
    )
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SERVICES), "exec"), namespace)
    return namespace[node.name]


class RakshMenuOrderTests(unittest.TestCase):
    def test_message_is_moved_immediately_before_my_orders(self):
        reorder = _load_order_helper()
        items = [
            {"id": 1, "action_value": "raksh:start:story"},
            {"id": 2, "action_value": "raksh:my_orders"},
            {"id": 3, "action_value": "raksh:send_message"},
        ]

        result = reorder(items)

        self.assertEqual(
            [item["action_value"] for item in result],
            ["raksh:start:story", "raksh:send_message", "raksh:my_orders"],
        )

    def test_existing_correct_order_is_unchanged(self):
        reorder = _load_order_helper()
        items = [
            {"id": 1, "action_value": "raksh:send_message"},
            {"id": 2, "action_value": "raksh:my_orders"},
        ]

        self.assertIsNot(reorder(items), items)
        self.assertEqual(reorder(items), items)


if __name__ == "__main__":
    unittest.main()
