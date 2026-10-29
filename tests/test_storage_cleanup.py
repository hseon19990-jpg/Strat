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

    def fetchone(self):
        return {"database_bytes": 987654}

    def fetchall(self):
        return [{"schema_name": "public", "table_name": "activity", "total_bytes": 4096}]


def load_function(connection, name):
    tree = ast.parse(CLEANUP.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    namespace = {
        "db_conn": lambda: connection,
        "USAGE_RETENTION_DAYS": 2,
        "TRANSIENT_RETENTION_DAYS": 14,
        "MAX_ROWS_PER_TABLE_PER_RUN": 500,
    }
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), str(CLEANUP), "exec"),
        namespace,
    )
    return namespace[name]


class StorageCleanupTests(unittest.TestCase):
    def test_runs_only_the_whitelisted_batched_cleanup_queries(self):
        connection = FakeConnection()
        deleted = load_function(connection, "cleanup_transient_storage_data")()

        self.assertEqual(
            list(deleted),
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
        self.assertEqual(len(connection.queries), 5)
        for query, params in connection.queries:
            self.assertIn("limit %s", query.lower())
            self.assertEqual(params[-1], 500)

    def test_usage_history_is_retained_for_quota_window_and_active_orders(self):
        connection = FakeConnection()
        load_function(connection, "cleanup_transient_storage_data")()
        usage_sql, usage_params = connection.queries[0]
        normalized = usage_sql.lower()
        self.assertIn("usage.executed_at < now() - (%s * interval '1 day')", normalized)
        self.assertIn("orders.status in ('completed', 'cancelled')", normalized)
        self.assertIn("not exists", normalized)
        self.assertEqual(usage_params, (2, 500))

    def test_daily_claims_expire_only_before_current_baghdad_day(self):
        connection = FakeConnection()
        load_function(connection, "cleanup_transient_storage_data")()
        claims_sql, _ = connection.queries[1]
        self.assertIn(
            "claim_date < (now() at time zone 'asia/baghdad')::date",
            claims_sql.lower(),
        )

    def test_two_week_cleanup_preserves_paid_payment_records(self):
        connection = FakeConnection()
        load_function(connection, "cleanup_transient_storage_data")()
        gift_sql, gift_params = connection.queries[2]
        activity_sql, activity_params = connection.queries[3]
        payment_sql, payment_params = connection.queries[4]
        self.assertEqual(gift_params, (14, 500))
        self.assertEqual(activity_params, (14, 500))
        self.assertEqual(payment_params, (14, 500))
        self.assertIn("telegram_payment_id is null", payment_sql.lower())
        self.assertIn("payment_method is null", payment_sql.lower())
        self.assertIn("'cancelled'", payment_sql.lower())
        self.assertNotIn("'awaiting_payment'", payment_sql.lower())
        self.assertNotIn("'failed'", payment_sql.lower())
        self.assertNotIn("'completed'", payment_sql.lower())

    def test_size_diagnostic_reads_only_database_metadata_and_top_ten(self):
        connection = FakeConnection()
        snapshot = load_function(connection, "get_storage_size_snapshot")()
        self.assertEqual(snapshot["database_bytes"], 987654)
        self.assertEqual(snapshot["top_tables"][0]["table"], "activity")
        self.assertEqual(snapshot["top_tables"][0]["bytes"], 4096)
        sql = "\n".join(query for query, _ in connection.queries).lower()
        self.assertIn("pg_database_size(current_database())", sql)
        self.assertIn("pg_total_relation_size(c.oid)", sql)
        self.assertIn("limit 10", sql)
        self.assertNotIn("password", sql)
        self.assertNotIn("session", sql)
        self.assertNotIn("select *", sql)


if __name__ == "__main__":
    unittest.main()
