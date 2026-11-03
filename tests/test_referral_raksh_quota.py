import ast
import unittest
from pathlib import Path
from typing import Tuple


ROOT = Path(__file__).parents[1]
USERS = ROOT / "bot_app" / "users.py"
COMMON = ROOT / "bot_app" / "raksh_system" / "common.py"
SECURITY = ROOT / "bot_app" / "security.py"
RAKSH_SYSTEM = ROOT / "bot_app" / "raksh_system" / "raksh_system.py"


def load_function(path, function_name, namespace=None, class_name=None):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    if class_name:
        owner = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        )
        function = next(
            node for node in owner.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        )
    else:
        function = next(
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        )
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    scope = {"Tuple": Tuple}
    if namespace:
        scope.update(namespace)
    exec(compile(module, str(path), "exec"), scope)
    return scope[function_name]


class ReferralRakshQuotaTests(unittest.TestCase):
    def test_quota_is_250_and_only_successes_or_reservations_reduce_it(self):
        tree = ast.parse(USERS.read_text(encoding="utf-8"))
        limit = next(
            node.value.value for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "REFERRAL_FREE_RAKSH_ACCOUNT_LIMIT"
                for target in node.targets
            )
        )
        remaining = load_function(USERS, "_referral_free_raksh_remaining")

        self.assertEqual(limit, 250)
        self.assertEqual(remaining(limit, 0, 0), 250)
        self.assertEqual(remaining(limit, 250, 0), 0)
        self.assertEqual(remaining(limit, 0, 250), 0)
        self.assertEqual(remaining(limit, 10, 200), 40)
        # Failed free attempts settle with used_quantity=0 and release holds.
        self.assertEqual(remaining(limit, 0, 0), 250)

    def test_300_account_request_prices_only_the_50_billable_accounts(self):
        calls = []

        class FakeService:
            def get_total(self, quantity, payment_method, channel_count=0):
                calls.append((quantity, payment_method, channel_count))
                return quantity * 3

        quote = load_function(
            COMMON,
            "get_points_quote",
            namespace={"get_referral_free_raksh_remaining": lambda _user_id: 250},
            class_name="RakshService",
        )
        FakeService.get_points_quote = quote

        cost, free_quantity = FakeService().get_points_quote(123, 300, 2)

        self.assertEqual(free_quantity, 250)
        self.assertEqual(cost, 150)
        self.assertEqual(calls, [(50, "points", 2)])

    def test_generic_services_do_not_get_the_raksh_free_quota(self):
        cost = load_function(SECURITY, "service_points_cost")
        self.assertEqual(cost(123, 50), 50)

    def test_raksh_orders_split_free_slots_and_keep_fixed_account_count(self):
        source = RAKSH_SYSTEM.read_text(encoding="utf-8")
        self.assertIn("is_referral_free", source)
        self.assertIn('params["_fixed_account_count"] = True', source)
        self.assertIn("paid_success_count", source)
        self.assertIn("settle_referral_free_raksh_reservation", source)


if __name__ == "__main__":
    unittest.main()
