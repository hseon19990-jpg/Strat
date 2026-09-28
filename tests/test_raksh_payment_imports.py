import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
COMMON = ROOT / "bot_app" / "raksh_system" / "common.py"


class RakshPaymentImportTests(unittest.TestCase):
    def test_common_exports_service_points_cost_for_payment_handlers(self):
        tree = ast.parse(COMMON.read_text(encoding="utf-8"))

        security_imports = [
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "security"
            and node.level == 2
        ]

        imported_names = {
            alias.name
            for node in security_imports
            for alias in node.names
        }

        self.assertIn(
            "service_points_cost",
            imported_names,
            "Raksh point-payment callbacks would raise NameError",
        )


if __name__ == "__main__":
    unittest.main()
