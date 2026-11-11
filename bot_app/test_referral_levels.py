import ast
import unittest
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from types import SimpleNamespace

USERS = Path(__file__).parents[1] / "bot_app" / "users.py"
NAMES = {
    "get_referral_reward_type", "parse_referral_jewels", "get_referral_level1_jewels",
    "fmt_referral_amount", "_credit_referral_reward", "credit_referral_if_pending",
    "referral_fraud_protection_enabled",
}


class FakeResult:
    def __init__(self, rows=None, rowcount=1):
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class FakeDb:
    def __init__(self, users, levels, tiers=()):
        self.users = users
        self.levels = levels
        self.tiers = list(tiers)
        self.jewel_tx = []
        self.rowcount = 1

    def execute(self, sql, params=()):
        result = self._execute(sql, params)
        self.rowcount = result.rowcount
        return result

    def _execute(self, sql, params=()):
        sql = " ".join(sql.split())
        if sql.startswith("SELECT invited_by, referral_credited, verified"):
            return FakeResult([self.users[params[0]]])
        if sql.startswith("UPDATE users SET referral_credited=1"):
            u = self.users[params[0]]
            if u["referral_credited"]:
                return FakeResult(rowcount=0)
            u["referral_credited"] = 1
            return FakeResult()
        if sql.startswith("SELECT COUNT(*) AS cnt FROM users"):
            n = sum(1 for u in self.users.values()
                    if u["invited_by"] == params[0] and u["referral_credited"])
            return FakeResult([{"cnt": n}])
        if sql.startswith("SELECT referral_count, points_per_referral"):
            return FakeResult(self.tiers[:1])
        if sql.startswith("SELECT level, points, jewels"):
            return FakeResult([dict(level=k, **v) for k, v in sorted(self.levels.items())])
        if sql.startswith("SELECT invited_by FROM users"):
            return FakeResult([{"invited_by": self.users[params[0]]["invited_by"]}])
        if sql.startswith("UPDATE users SET wheel_spins="):
            return FakeResult()
        if sql.startswith("UPDATE users SET points=points+"):
            self.users[params[1]]["points"] += params[0]
            return FakeResult()
        if sql.startswith("UPDATE users SET jewels="):
            self.users[params[1]]["jewels"] += params[0]
            return FakeResult()
        if sql.startswith("INSERT INTO jewel_transactions"):
            self.jewel_tx.append(params)
            return FakeResult()
        raise AssertionError(f"unexpected sql: {sql}")


def load(db, settings):
    tree = ast.parse(USERS.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]

    class Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    ns = {
        "Decimal": Decimal, "InvalidOperation": InvalidOperation,
        "ROUND_HALF_UP": ROUND_HALF_UP,
        "REFERRAL_REWARD_TYPES": ("points", "jewels"),
        "get_setting": lambda k: settings.get(k, ""),
        "db_conn": lambda: Ctx(),
        "_grant_daily_referral_free_access": lambda c, uid: 0,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(USERS), "exec"), ns)
    return ns


def make_users():
    def u(invited_by=0, verified=1, username="user"):
        return {"invited_by": invited_by, "referral_credited": 0, "verified": verified,
                "username": username, "points": 0, "jewels": Decimal(0)}
    # 4 invited by 3, 3 invited by 2, 2 invited by 1
    return {1: u(), 2: u(1), 3: u(2), 4: u(3)}


class ReferralLevelsTest(unittest.TestCase):
    def test_points_multi_level(self):
        users = make_users()
        db = FakeDb(users, {2: {"points": 10, "jewels": Decimal(0)}, 3: {"points": 5, "jewels": Decimal(0)}})
        ns = load(db, {"referral_reward_type": "points", "referral_points": "30"})
        ctx = SimpleNamespace(user_data={})
        self.assertEqual(ns["credit_referral_if_pending"](4, ctx), (3, 30))
        self.assertEqual((users[3]["points"], users[2]["points"], users[1]["points"]), (30, 10, 5))
        self.assertEqual(ctx.user_data["referral_upper_rewards"], [(2, 2, 10), (1, 3, 5)])
        self.assertEqual(db.jewel_tx, [])
        # لا تكرار
        self.assertIsNone(ns["credit_referral_if_pending"](4, ctx))

    def test_invited_without_username_is_silent_and_not_credited(self):
        users = make_users()
        users[4]["username"] = ""
        db = FakeDb(users, {2: {"points": 10, "jewels": Decimal(0)}})
        ns = load(db, {"referral_reward_type": "points", "referral_points": "30"})
        ctx = SimpleNamespace(user_data={})
        # لا مكافأة ولا إشعار (None) ولا نقاط لأي مستوى
        self.assertIsNone(ns["credit_referral_if_pending"](4, ctx))
        self.assertEqual((users[3]["points"], users[2]["points"]), (0, 0))
        self.assertEqual(users[4]["referral_credited"], 0)
        self.assertNotIn("referral_upper_rewards", ctx.user_data)
        # عند إضافته يوزر لاحقاً تُحتسب الإحالة مرة واحدة
        users[4]["username"] = "now_has_username"
        self.assertEqual(ns["credit_referral_if_pending"](4, ctx), (3, 30))
        self.assertEqual(users[3]["points"], 30)

    def test_jewels_only(self):
        users = make_users()
        db = FakeDb(users, {2: {"points": 10, "jewels": Decimal("1.5")}})
        ns = load(db, {"referral_reward_type": "jewels", "referral_jewels": "2", "referral_points": "30"})
        ctx = SimpleNamespace(user_data={})
        inviter, amount = ns["credit_referral_if_pending"](4, ctx)
        self.assertEqual((inviter, amount), (3, Decimal("2.000000")))
        self.assertEqual(users[3]["jewels"], Decimal("2.000000"))
        self.assertEqual(users[2]["jewels"], Decimal("1.500000"))
        self.assertEqual(users[3]["points"], 0)
        self.assertEqual(users[2]["points"], 0)
        self.assertEqual(len(db.jewel_tx), 2)

    def test_chain_stops_and_zero_levels(self):
        users = make_users()
        db = FakeDb(users, {2: {"points": 0, "jewels": Decimal(0)}, 3: {"points": 7, "jewels": Decimal(0)}})
        ns = load(db, {"referral_points": "30"})
        ctx = SimpleNamespace(user_data={})
        ns["credit_referral_if_pending"](3, ctx)  # inviter=2, level2=1, level3 يتوقف
        self.assertEqual((users[2]["points"], users[1]["points"]), (30, 0))
        self.assertNotIn("referral_upper_rewards", ctx.user_data)

    def test_invalid_type_falls_back_to_points(self):
        ns = load(FakeDb({}, {}), {"referral_reward_type": "stars"})
        self.assertEqual(ns["get_referral_reward_type"](), "points")
        self.assertEqual(ns["fmt_referral_amount"]("points", 30), "30 نقطة")
        self.assertIn("جوهرة", ns["fmt_referral_amount"]("jewels", Decimal("2.5")))


if __name__ == "__main__":
    unittest.main()
