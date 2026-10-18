import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class _Result:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Connection:
    def __init__(self, order_rows):
        self.order_rows = order_rows
        self.earning_params = []
        self.point_updates = []

    def execute(self, query, params=()):
        normalized = " ".join(query.split())
        if normalized.startswith("SELECT i.stock_id"):
            return _Result(self.order_rows)
        if "INSERT INTO raksh_contributor_earnings" in normalized:
            self.earning_params.append(params)
            return _Result([{"id": len(self.earning_params)}])
        if normalized.startswith("UPDATE users SET points=points+"):
            self.point_updates.append(params)
        return _Result()


class _AccountDb:
    def __init__(self):
        self.insert_params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params=()):
        if "SELECT id, contributed_by" in query:
            return _Result()
        self.insert_params = params
        return _Result()


class RakshContributorShareTests(unittest.TestCase):
    @staticmethod
    def _load_credit_function():
        source = (
            ROOT / "bot_app" / "raksh_system" / "raksh_system.py"
        ).read_text(encoding="utf-8")
        module = ast.parse(source)
        function = next(
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_credit_raksh_contributors"
        )
        namespace = {}
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), "<credit>", "exec"),
            namespace,
        )
        return namespace["_credit_raksh_contributors"]

    @staticmethod
    def _load_add_account_function(db):
        source = (ROOT / "bot_app" / "accounts.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        function = next(
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "add_contributor_account"
        )
        namespace = {"db_conn": lambda: db}
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), "<add-account>", "exec"),
            namespace,
        )
        return namespace["add_contributor_account"]

    def test_share_number_is_persisted_with_zero_reward_rate(self):
        db = _AccountDb()
        add_account = self._load_add_account_function(db)

        added, result = add_account(
            77,
            "+9647700000002",
            "session-string",
            share_percent=0,
        )

        self.assertTrue(added)
        self.assertEqual("added", result)
        self.assertEqual(0, db.insert_params[-1])

    def test_shared_number_gets_zero_points_and_is_not_credited(self):
        credit = self._load_credit_function()
        connection = _Connection([
            {
                "stock_id": 12,
                "phone_number": "+9647700000000",
                "contributed_by": 77,
                "share_percent": 0,
            }
        ])

        result = credit(
            connection,
            order_id=501,
            payment_method="points",
            total_cost=100,
            success_count=1,
        )

        self.assertEqual(0, result[0]["points"])
        self.assertEqual(0, connection.earning_params[0][5])
        self.assertEqual(0, connection.earning_params[0][6])
        self.assertEqual([], connection.point_updates)

    def test_legacy_null_share_keeps_the_existing_fifty_percent_default(self):
        credit = self._load_credit_function()
        connection = _Connection([
            {
                "stock_id": 13,
                "phone_number": "+9647700000001",
                "contributed_by": 78,
                "share_percent": None,
            }
        ])

        result = credit(
            connection,
            order_id=502,
            payment_method="points",
            total_cost=100,
            success_count=1,
        )

        self.assertEqual(50, connection.earning_params[0][5])
        self.assertEqual(50, result[0]["points"])
        self.assertEqual([(50, 78)], connection.point_updates)


if __name__ == "__main__":
    unittest.main()
