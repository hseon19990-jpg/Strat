import ast
import asyncio
import unittest
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "bot_app" / "join_rewards.py"
WANTED = {
    "parse_join_price", "get_join_reward_jewels", "channel_is_request",
    "claim_join_reward", "check_join_status",
}


class FakeRow(dict):
    pass


class FakeDB:
    def __init__(self):
        self.rewards = {}
        self.jewels = {1: Decimal(0)}
        self.tx = []
        self.requests = set()
        self.rowcount = 0
        self._last = None

    @contextmanager
    def conn(self):
        yield self

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        self._last = None
        if sql.startswith("INSERT INTO channel_join_rewards"):
            user_id, ch_id, amount = params
            if (user_id, ch_id) in self.rewards:
                self.rowcount = 0
            else:
                self.rewards[(user_id, ch_id)] = amount
                self.rowcount = 1
        elif sql.startswith("UPDATE users SET jewels"):
            amount, user_id = params
            self.jewels[user_id] += amount
            self._last = FakeRow(jewels=self.jewels[user_id])
        elif sql.startswith("INSERT INTO jewel_transactions"):
            self.tx.append(params)
        elif sql.startswith("SELECT 1 FROM channel_join_requests"):
            user_id, username = params
            self._last = FakeRow(x=1) if (user_id, username) in self.requests else None
        return self

    def fetchone(self):
        return self._last


def _load(db, settings, bot_member=None):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    nodes = [
        n for n in tree.body
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in WANTED)
        or (isinstance(n, ast.Assign) and any(
            getattr(t, "id", "") in {
                "JOIN_REWARD_SETTING", "JOIN_REQUEST_REWARD_SETTING",
                "DEFAULT_JOIN_REWARD_JEWELS", "DEFAULT_JOIN_REQUEST_REWARD_JEWELS",
                "JOIN_PRICE_MAX", "_AR_DIGITS",
            } for t in n.targets))
    ]
    ns = {
        "Decimal": Decimal, "InvalidOperation": InvalidOperation,
        "ROUND_HALF_UP": ROUND_HALF_UP,
        "get_setting": lambda key: settings.get(key),
        "db_conn": db.conn,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), ns)
    return ns


class FakeBot:
    def __init__(self, status=None, error=False):
        self.status, self.error = status, error

    async def get_chat_member(self, chat, user_id):
        if self.error:
            raise RuntimeError("boom")

        class M:
            pass
        m = M()
        m.status = self.status
        return m


class JoinRewardTests(unittest.TestCase):
    def test_defaults_and_parsing(self):
        ns = _load(FakeDB(), {})
        self.assertEqual(ns["get_join_reward_jewels"](False), Decimal("0.1"))
        self.assertEqual(ns["get_join_reward_jewels"](True), Decimal("0.15"))
        p = ns["parse_join_price"]
        self.assertEqual(p("٠٫١٥"), Decimal("0.15"))
        self.assertEqual(p("0,25"), Decimal("0.25"))
        self.assertIsNone(p("0"))
        self.assertIsNone(p("abc"))
        self.assertIsNone(p("-1"))

    def test_owner_values_override_defaults(self):
        ns = _load(FakeDB(), {"join_channel_reward_jewels": "0.3", "join_request_reward_jewels": "0.5"})
        self.assertEqual(ns["get_join_reward_jewels"](False), Decimal("0.3"))
        self.assertEqual(ns["get_join_reward_jewels"](True), Decimal("0.5"))

    def test_claim_once_only(self):
        db = FakeDB()
        ns = _load(db, {})
        self.assertEqual(ns["claim_join_reward"](1, 7, False), Decimal("0.1"))
        self.assertIsNone(ns["claim_join_reward"](1, 7, False))
        self.assertEqual(db.jewels[1], Decimal("0.1"))
        self.assertEqual(ns["claim_join_reward"](1, 8, True), Decimal("0.15"))
        self.assertEqual(db.jewels[1], Decimal("0.25"))
        self.assertEqual(len(db.tx), 2)

    def test_status_member_request_and_error(self):
        db = FakeDB()
        ns = _load(db, {})
        run = lambda coro: asyncio.new_event_loop().run_until_complete(coro)
        normal = {"channel_username": "Chan", "join_request": 0}
        req = {"channel_username": "Chan", "join_request": 1}
        self.assertEqual(run(ns["check_join_status"](FakeBot("member"), normal, 1)), "member")
        self.assertEqual(run(ns["check_join_status"](FakeBot("left"), normal, 1)), "no")
        self.assertEqual(run(ns["check_join_status"](FakeBot(error=True), normal, 1)), "error")
        self.assertEqual(run(ns["check_join_status"](FakeBot("left"), req, 1)), "no")
        db.requests.add((1, "chan"))
        self.assertEqual(run(ns["check_join_status"](FakeBot("left"), req, 1)), "requested")
        self.assertEqual(run(ns["check_join_status"](FakeBot(error=True), req, 1)), "requested")


if __name__ == "__main__":
    unittest.main()
