import ast
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

USERS = Path(__file__).parents[1] / "bot_app" / "users.py"
NAMES = {
    "_detect_same_second_mandatory_joins", "_punish_referral_fraud",
    "credit_referral_if_pending", "referral_fraud_protection_enabled",
    "get_referral_reward_type", "parse_referral_jewels",
    "get_referral_level1_jewels", "_credit_referral_reward",
}


class Res:
    def __init__(self, rows=None, rowcount=1):
        self.rows, self.rowcount = rows or [], rowcount

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeDb:
    def __init__(self, channels, events, inviter_points=500, inviter_jewels="3"):
        self.channels = channels          # active mandatory channels
        self.events = events              # list of (channel, second) for the invited user
        self.users = {
            10: {"invited_by": 5, "referral_credited": 0, "verified": 1},
            5: {"points": inviter_points, "jewels": Decimal(inviter_jewels)},
        }
        self.orders = [
            {"id": 1, "order_code": "A1", "api_order_id": "991", "panel": 2, "status": "pending"},
            {"id": 2, "order_code": "A2", "api_order_id": "992", "panel": 1, "status": "completed"},
        ]
        self.raksh = [{"id": 7, "status": "running"}, {"id": 8, "status": "completed"}]
        self.log = []
        self.tx = []
        self.rowcount = 1

    def execute(self, sql, params=()):
        r = self._run(" ".join(sql.split()), params)
        self.rowcount = r.rowcount
        return r

    def _run(self, sql, p):
        if sql.startswith("SELECT invited_by, referral_credited"):
            return Res([self.users[10]])
        if sql.startswith("UPDATE users SET referral_credited=1"):
            return Res()
        if sql.startswith("SELECT channel_username FROM mandatory_channels"):
            return Res([{"channel_username": c} for c in self.channels])
        if sql.startswith("SELECT joined_second, COUNT(DISTINCT"):
            allowed = set(p[1:])
            groups = {}
            for ch, sec in self.events:
                if ch in allowed:
                    groups.setdefault(sec, set()).add(ch)
            if not groups:
                return Res()
            sec, chs = max(groups.items(), key=lambda kv: len(kv[1]))
            return Res([{"joined_second": sec, "cnt": len(chs)}])
        if sql.startswith("SELECT points, jewels FROM users"):
            return Res([dict(self.users[5])])
        if sql.startswith("UPDATE users SET points=LEAST"):
            u = self.users[5]
            u["points"] = min(u["points"], 0)
            u["jewels"] = min(u["jewels"], Decimal(0))
            return Res()
        if sql.startswith("INSERT INTO jewel_transactions"):
            self.tx.append(p)
            return Res()
        if sql.startswith("SELECT o.id, o.order_code"):
            return Res([dict(o) for o in self.orders if o["status"] == "pending"])
        if sql.startswith("UPDATE orders SET status='cancelled'"):
            for o in self.orders:
                if o["id"] == p[0] and o["status"] == "pending":
                    o["status"] = "cancelled"
            return Res()
        if sql.startswith("SELECT id FROM raksh_orders"):
            return Res([{"id": o["id"]} for o in self.raksh if o["status"] in ("pending", "running")])
        if sql.startswith("INSERT INTO referral_fraud_log"):
            self.log.append(p)
            return Res()
        if sql.startswith("SELECT COUNT(*) AS cnt FROM users"):
            return Res([{"cnt": 1}])
        if sql.startswith("SELECT referral_count, points_per_referral"):
            return Res()
        if sql.startswith("UPDATE users SET wheel_spins="):
            return Res()
        if sql.startswith("UPDATE users SET points=points+"):
            self.users[p[1]]["points"] += p[0]
            return Res()
        if sql.startswith("SELECT level, points, jewels"):
            return Res()
        raise AssertionError(sql)


def load(db, settings):
    tree = ast.parse(USERS.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]

    class Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    ns = {
        "Decimal": Decimal, "InvalidOperation": ArithmeticError,
        "ROUND_HALF_UP": "ROUND_HALF_UP", "REFERRAL_REWARD_TYPES": ("points", "jewels"),
        "get_setting": lambda k: settings.get(k, ""), "db_conn": lambda: Ctx(),
        "_grant_daily_referral_free_access": lambda c, uid: 0, "OWNER_ID": 999,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(USERS), "exec"), ns)
    return ns


class ReferralFraudTests(unittest.TestCase):
    def run_case(self, channels, events, enabled="1", **kw):
        db = FakeDb(channels, events, **kw)
        ns = load(db, {"referral_fraud_protection": enabled, "referral_points": "30"})
        ctx = SimpleNamespace(user_data={})
        return db, ctx, ns["credit_referral_if_pending"](10, ctx)

    def test_two_of_four_in_same_second_is_fraud(self):
        db, ctx, res = self.run_case(["a", "b", "c", "d"], [("a", 100), ("b", 100), ("c", 105)])
        self.assertIsNone(res)
        info = ctx.user_data["referral_fraud"]
        self.assertEqual((info["inviter_id"], info["joined"], info["total"]), (5, 2, 4))
        self.assertEqual(db.users[5]["points"], 0)
        self.assertEqual(db.users[5]["jewels"], Decimal(0))
        self.assertEqual([o["status"] for o in db.orders], ["cancelled", "completed"])
        self.assertEqual(info["raksh_order_ids"], [7])
        self.assertEqual(info["smm_cancelled"], [(2, "991", "A1")])
        self.assertEqual(len(db.log), 1)

    def test_spread_joins_are_not_fraud(self):
        db, ctx, res = self.run_case(["a", "b", "c", "d"], [("a", 100), ("b", 101), ("c", 102), ("d", 103)])
        self.assertEqual(res, (5, 30))
        self.assertNotIn("referral_fraud", ctx.user_data)
        self.assertEqual(db.users[5]["points"], 530)

    def test_below_half_is_not_fraud(self):
        _db, ctx, res = self.run_case(["a", "b", "c", "d", "e"], [("a", 100), ("b", 100)])
        self.assertIsNotNone(res)  # 2 من 5 = 40% فقط

    def test_single_channel_never_counts(self):
        _db, _ctx, res = self.run_case(["a"], [("a", 100)])
        self.assertIsNotNone(res)

    def test_disabled_protection_does_nothing(self):
        db, ctx, res = self.run_case(["a", "b"], [("a", 100), ("b", 100)], enabled="0")
        self.assertIsNotNone(res)
        self.assertEqual(db.users[5]["points"], 530)


if __name__ == "__main__":
    unittest.main()
