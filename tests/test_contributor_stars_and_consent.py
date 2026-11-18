import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class _Result:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, order, items):
        self.order, self.items = order, items
        self.earnings, self.points = [], []

    def execute(self, query, params=()):
        q = " ".join(query.split())
        if q.startswith("SELECT service_type, quantity"):
            return _Result([self.order])
        if q.startswith("SELECT i.stock_id"):
            return _Result(self.items)
        if "INSERT INTO raksh_contributor_earnings" in q:
            self.earnings.append(params)
            return _Result([{"id": len(self.earnings)}])
        if q.startswith("UPDATE users SET points=points+"):
            self.points.append(params)
        return _Result()


class _Svc:
    MAX_DURATION_DAYS = 30

    def get_total(self, quantity, method):
        assert method == "points"
        return 100 * quantity  # 100 نقطة للحساب


def _load():
    src = (ROOT / "bot_app/raksh_system/raksh_system.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    wanted = {"_stars_order_points_equivalent", "_credit_raksh_contributors"}
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    ns = {
        "json": json,
        "RAKSH_POINTS_PER_STAR": 250,
        "get_raksh_service": lambda t: _Svc(),
    }
    exec(compile(ast.Module(body=funcs, type_ignores=[]), "<t>", "exec"), ns)
    return ns["_credit_raksh_contributors"]


def _items(n, share=50):
    return [
        {"stock_id": i, "phone_number": f"+{i}", "contributed_by": 7, "share_percent": share}
        for i in range(1, n + 1)
    ]


class StarsShareTests(unittest.TestCase):
    def test_stars_order_pays_points_equivalent_share(self):
        # 100 حساب ناجح كلها بالنجوم: كأنها 100*100=10000 نقطة، حصة 50٪ = 5000
        order = {"service_type": "votes", "quantity": 100, "params": {}, "total_cost": 40}
        conn = _Conn(order, _items(100))
        credits = _load()(conn, 1, "stars", 40, 100, 0)
        self.assertEqual(sum(c["points"] for c in credits), 5000)
        self.assertEqual(sum(p[0] for p in conn.points), 5000)

    def test_partial_success_is_prorated(self):
        order = {"service_type": "votes", "quantity": 100, "params": {}, "total_cost": 40}
        conn = _Conn(order, _items(60))
        credits = _load()(conn, 1, "stars", 40, 60, 0)
        self.assertEqual(sum(c["points"] for c in credits), 3000)

    def test_points_payment_unchanged(self):
        conn = _Conn({}, _items(10))
        credits = _load()(conn, 1, "points", 1000, 10, 0)
        self.assertEqual(sum(c["points"] for c in credits), 500)

    def test_unknown_payment_method_pays_nothing(self):
        conn = _Conn({}, _items(10))
        self.assertEqual(_load()(conn, 1, "contributor_free", 0, 10, 0), [])


class ConsentFilterTests(unittest.TestCase):
    def test_filters_reference_block_table(self):
        common = (ROOT / "bot_app/raksh_system/common.py").read_text(encoding="utf-8")
        message = (ROOT / "bot_app/raksh_system/message.py").read_text(encoding="utf-8")
        self.assertIn("raksh_contributor_service_blocks", common)
        self.assertIn("RAKSH_CONTRIBUTOR_BLOCK_SQL", common)
        self.assertIn("RAKSH_CONTRIBUTOR_BLOCK_SQL", message)

    def test_tools_check_ownership_on_every_account_action(self):
        src = (ROOT / "bot_app/contributor_tools.py").read_text(encoding="utf-8")
        self.assertIn("contributed_by=%s", src)
        self.assertIn("_owned_account(user.id, stock_id)", src)


if __name__ == "__main__":
    unittest.main()
