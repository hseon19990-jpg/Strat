import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
CLEANUP = ROOT / "bot_app" / "storage_cleanup.py"


class FakeConnection:
    def __init__(self):
        self.queries = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        self.rowcount = len(self.queries)
        return self


def load_cleanup(connection):
    tree = ast.parse(CLEANUP.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "cleanup_transient_storage_data"
    )
    namespace = {
        "db_conn": lambda: connection,
        "USAGE_RETENTION_DAYS": 2,
        "TRANSIENT_RETENTION_DAYS": 14,
    }
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), str(CLEANUP), "exec"),
        namespace,
    )
    return namespace["cleanup_transient_storage_data"]


class StorageCleanupTests(unittest.TestCase):
    def test_runs_only_the_whitelisted_cleanup_queries(self):
        connection = FakeConnection()
        deleted = load_cleanup(connection)()

        self.assertEqual(
            [name for name, _ in deleted.items()],
            [
                "raksh_execution_usage",
                "daily_gift_claims",
                "temporary_gifts",
                "activity",
                "smm_payment_intents",
            ],
        )
        self.assertEqual(list(deleted.values()), [1, 2, 3, 4, 5])
        sql = "\n".join(query for query, _ in connection.queries).lower()
        self.assertNotIn("delete from users", sql)
        self.assertNotIn("delete from orders", sql)
        self.assertNotIn("delete from raksh_orders", sql)
        self.assertNotIn("delete from jewel_transactions", sql)

    def test_keeps_active_order_usage_and_recent_quota_window(self):
        connection = FakeConnection()
        load_cleanup(connection)()
        usage_sql, usage_params = connection.queries[0]
        self.assertIn("orders.status in ('completed', 'cancelled')", usage_sql.lower())
        self.assertIn("not exists", usage_sql.lower())
        self.assertEqual(usage_params, (2, 2))

    def test_daily_claims_expire_only_before_current_baghdad_day(self):
        connection = FakeConnection()
        load_cleanup(connection)()
        claims_sql, _ = connection.queries[1]
        self.assertIn("claim_date < (now() at time zone 'asia/baghdad')::date", claims_sql.lower())

    def test_two_week_cleanup_preserves_paid_payment_records(self):
        connection = FakeConnection()
        load_cleanup(connection)()
        gift_sql, gift_params = connection.queries[2]
        activity_sql, activity_params = connection.queries[3]
        payment_sql, payment_params = connection.queries[4]
        self.assertEqual(gift_params, (14,))
        self.assertEqual(activity_params, (14,))
        self.assertEqual(payment_params, (14,))
        self.assertIn("telegram_payment_id is null", payment_sql.lower())
        self.assertIn("'cancelled'", payment_sql.lower())
        self.assertNotIn("'completed'", payment_sql.lower())


if __name__ == "__main__":
    unittest.main()
