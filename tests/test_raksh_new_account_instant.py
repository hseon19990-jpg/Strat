import ast
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

COMMON = Path(__file__).parents[1] / "bot_app" / "raksh_system" / "common.py"
_NEEDED = ("_raksh_stock_fingerprint", "_get_sessions_for_service")


def _load(stock):
    """يشغّل دالة اختيار الحسابات الحقيقية مع قاعدة بيانات وهمية قابلة للتعديل."""
    tree = ast.parse(COMMON.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in _NEEDED]
    loads = {"n": 0}

    class Cur:
        def __init__(self, sql):
            self.sql = sql

        def fetchone(self):
            return {"n": len(stock), "m": max((r["id"] for r in stock), default=0)}

        def fetchall(self):
            loads["n"] += 1
            return [dict(r) for r in stock]

    class Conn:
        def execute(self, sql, params=()):
            return Cur(sql)

    @contextmanager
    def db_conn():
        yield Conn()

    ns = {
        "Optional": __import__("typing").Optional, "List": list, "Dict": dict,
        "time": time, "db_conn": db_conn,
        "_RAKSH_SESSION_CACHE": {}, "_RAKSH_SESSION_CACHE_TIME": {},
        "_RAKSH_SESSION_CACHE_FP": {}, "_RAKSH_SESSION_CACHE_TTL": 60,
        "RAKSH_CONTRIBUTOR_BLOCK_SQL": "",
        "_dedupe_raksh_sessions": lambda rows: rows,
        "get_raksh_sessions_for_request": lambda rows, is_owner=False: rows,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(COMMON), "exec"), ns)
    return ns["_get_sessions_for_service"], loads


class NewAccountEntersRakshImmediatelyTests(unittest.TestCase):
    def test_new_account_is_picked_up_without_waiting_for_cache_expiry(self):
        stock = [{"id": 1, "phone_number": "+1"}]
        get_sessions, loads = _load(stock)
        self.assertEqual([r["id"] for r in get_sessions("vote")], [1])
        # نفس الدقيقة: بلا تغيير في المخزون → يُستخدم الكاش ولا يُعاد التحميل
        get_sessions("vote")
        self.assertEqual(loads["n"], 1)
        # يصل حساب جديد (بأي طريقة) → يظهر في الطلب التالي مباشرة
        stock.append({"id": 2, "phone_number": "+2"})
        self.assertEqual([r["id"] for r in get_sessions("vote")], [1, 2])
        self.assertEqual(loads["n"], 2)

    def test_removed_account_leaves_immediately_too(self):
        stock = [{"id": 1, "phone_number": "+1"}, {"id": 2, "phone_number": "+2"}]
        get_sessions, _ = _load(stock)
        get_sessions("vote")
        stock.pop()
        self.assertEqual([r["id"] for r in get_sessions("vote")], [1])

    def test_no_account_age_gate_in_raksh_pool_query(self):
        source = COMMON.read_text(encoding="utf-8")
        start = source.index("def _get_sessions_for_service")
        end = source.index("def get_available_sessions_count", start)
        pool = source[start:end]
        for gate in ("INTERVAL", "added_at", "created_at", "accepted_at", "sessions_reset", "is_solo"):
            self.assertNotIn(gate, pool)


if __name__ == "__main__":
    unittest.main()
