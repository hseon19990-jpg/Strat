import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "bot_app" / "raksh_system" / "raksh_system.py"


def _load_function(name, namespace):
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), "<function>", "exec"),
        namespace,
    )
    return namespace[name]


class _Service:
    def __init__(self, sessions=None):
        self.sessions = list(sessions or [])
        self.calls = []

    def get_sessions(self, **kwargs):
        self.calls.append(kwargs)
        return self.sessions


class PersonalFreeRakshRewardTests(unittest.TestCase):
    def test_free_limit_uses_only_the_users_unrewarded_shared_accounts(self):
        service = _Service([{"id": 1}, {"id": 2}, {"id": 3}])
        namespace = {
            "get_raksh_service": lambda _service_type: service,
            "get_raksh_hourly_remaining": lambda _user_id: 2,
            "get_raksh_daily_remaining": lambda _user_id: 5,
        }
        get_limit = _load_function("_get_contributor_raksh_limit", namespace)

        self.assertEqual(2, get_limit(77, "comment"))
        self.assertEqual(
            [{"contributor_id": 77, "contributor_share_percent": 0}],
            service.calls,
        )

    def test_free_orders_filter_to_owner_accounts_but_paid_orders_keep_shared_pool(self):
        service = _Service([{"id": 1}])
        get_sessions = _load_function(
            "_get_raksh_order_sessions",
            {"OWNER_ID": 1},
        )

        get_sessions(service, 77, "contributor_free")
        self.assertEqual(
            {
                "is_owner": False,
                "contributor_id": 77,
                "contributor_share_percent": 0,
            },
            service.calls[-1],
        )

        get_sessions(service, 77, "points")
        self.assertEqual(
            {
                "is_owner": False,
                "contributor_id": None,
                "contributor_share_percent": None,
            },
            service.calls[-1],
        )

    def test_shared_account_query_has_an_explicit_owner_filter(self):
        source = (ROOT / "bot_app" / "raksh_system" / "common.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("AND contributed_by=%s", source)
        self.assertIn(
            "AND COALESCE(contributor_share_percent, 50)=%s",
            source,
        )
        self.assertIn(
            'callback_data=f"raksh:contributor_free:{service_type}:{quantity}"',
            SOURCE.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
