import ast
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).parents[1]
PAYMENTS = ROOT / "bot_app" / "payments.py"


def _load_exchange_helpers(db_conn=None):
    tree = ast.parse(PAYMENTS.read_text(encoding="utf-8"))
    names = {
        "CURRENCY_EXCHANGE_MAX_INPUT",
        "CURRENCY_EXCHANGE_MAX_POINTS",
        "CURRENCY_EXCHANGE_MAX_JEWELS",
        "DEFAULT_JEWELS_TO_POINTS_RATE",
        "DEFAULT_POINTS_TO_JEWELS_RATE",
        "parse_currency_exchange_amount",
        "calculate_currency_exchange",
        "perform_currency_exchange",
    }
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in names
            for target in node.targets
        ):
            nodes.append(node)
    namespace = {"Decimal": Decimal, "db_conn": db_conn}
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(PAYMENTS), "exec"),
        namespace,
    )
    return namespace


class FakeExchangeDatabase:
    def __init__(self, points, jewels):
        self.balance = {"points": points, "jewels": Decimal(str(jewels))}
        self.requests = {}
        self.next_id = 1

    def __call__(self):
        return FakeExchangeConnection(self)


class FakeExchangeConnection:
    def __init__(self, database):
        self.database = database
        self.cursor = FakeExchangeCursor(database)

    def __enter__(self):
        return self.cursor

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FakeExchangeCursor:
    def __init__(self, database):
        self.database = database
        self.result = None

    def execute(self, query, params=()):
        sql = " ".join(query.split())
        if sql.startswith("INSERT INTO currency_exchange_transactions"):
            request_id = params[0]
            if request_id in self.database.requests:
                self.result = None
            else:
                row_id = self.database.next_id
                self.database.next_id += 1
                self.database.requests[request_id] = {
                    "id": row_id,
                    "status": "pending",
                }
                self.result = {"id": row_id}
        elif "SELECT status FROM currency_exchange_transactions" in sql:
            self.result = self.database.requests.get(params[0])
        elif "SELECT points, jewels FROM users" in sql:
            self.result = dict(self.database.balance)
        elif sql.startswith("UPDATE users SET points=%s, jewels=%s"):
            points, jewels, _user_id = params
            self.database.balance = {
                "points": points,
                "jewels": Decimal(str(jewels)),
            }
            self.result = None
        elif sql.startswith("UPDATE currency_exchange_transactions SET status=%s"):
            status, row_id = params
            for row in self.database.requests.values():
                if row["id"] == row_id:
                    row["status"] = status
                    break
            self.result = None
        else:
            raise AssertionError(f"Unexpected SQL: {sql}")
        return self

    def fetchone(self):
        return self.result


class CurrencyExchangeTests(unittest.TestCase):
    def test_amount_parser_accepts_arabic_digits_and_rejects_invalid_values(self):
        helpers = _load_exchange_helpers()
        parse_amount = helpers["parse_currency_exchange_amount"]
        self.assertEqual(parse_amount("١"), 1)
        self.assertEqual(parse_amount("۵٬۰۰۰"), 5000)
        self.assertEqual(parse_amount("7,000"), 7000)
        self.assertIsNone(parse_amount(""))
        self.assertIsNone(parse_amount("0"))
        self.assertIsNone(parse_amount("-1"))
        self.assertIsNone(parse_amount("1.5"))
        self.assertIsNone(parse_amount("1000000001"))

    def test_directional_rates_produce_independent_quotes(self):
        calculate = _load_exchange_helpers()["calculate_currency_exchange"]
        self.assertEqual(
            calculate("jewels_to_points", 1, 5000),
            {
                "direction": "jewels_to_points",
                "jewels_amount": 1,
                "points_amount": 5000,
                "rate": 5000,
            },
        )
        self.assertEqual(
            calculate("points_to_jewels", 1, 7000)["points_amount"],
            7000,
        )
        self.assertIsNone(calculate("unknown", 1, 10))
        self.assertIsNone(calculate("jewels_to_points", 1, 0))
        self.assertIsNone(calculate("jewels_to_points", 500000, 5000))

    def test_jewels_to_points_updates_both_balances_once(self):
        database = FakeExchangeDatabase(points=100, jewels=2)
        perform = _load_exchange_helpers(database)["perform_currency_exchange"]

        result = perform(99, "request-1", "jewels_to_points", 1, 5000)
        duplicate = perform(99, "request-1", "jewels_to_points", 1, 5000)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["balance"]["points"], 5100)
        self.assertEqual(result["balance"]["jewels"], Decimal("1"))
        self.assertEqual(duplicate["status"], "duplicate")
        self.assertEqual(duplicate["previous_status"], "completed")
        self.assertEqual(database.balance["points"], 5100)
        self.assertEqual(database.balance["jewels"], Decimal("1"))

    def test_points_to_jewels_and_insufficient_balance(self):
        database = FakeExchangeDatabase(points=7000, jewels=0)
        perform = _load_exchange_helpers(database)["perform_currency_exchange"]
        result = perform(99, "request-2", "points_to_jewels", 1, 7000)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["balance"]["points"], 0)
        self.assertEqual(result["balance"]["jewels"], Decimal("1"))

        insufficient_db = FakeExchangeDatabase(points=6999, jewels=0)
        insufficient = _load_exchange_helpers(insufficient_db)["perform_currency_exchange"](
            99, "request-3", "points_to_jewels", 1, 7000
        )
        self.assertEqual(insufficient["status"], "insufficient_points")
        self.assertEqual(insufficient_db.balance["points"], 6999)
        self.assertEqual(insufficient_db.balance["jewels"], Decimal("0"))

    def test_menu_rates_and_handlers_are_wired_to_bot_app(self):
        services = (ROOT / "bot_app" / "services.py").read_text(encoding="utf-8")
        ui = (ROOT / "bot_app" / "ui.py").read_text(encoding="utf-8")
        callbacks = (ROOT / "bot_app" / "callback_groups_01.py").read_text(encoding="utf-8")
        owner_callbacks = (ROOT / "bot_app" / "callback_groups_02.py").read_text(encoding="utf-8")
        messages = (ROOT / "bot_app" / "messages.py").read_text(encoding="utf-8")
        database = (ROOT / "bot_app" / "database.py").read_text(encoding="utf-8")

        self.assertIn('("↔️ تحويل بين النقاط والمجوهرات", "currency_exchange", 2)', services)
        self.assertIn('callback_data="currency_exchange"', ui)
        self.assertIn('data.startswith("cx:confirm:")', callbacks)
        self.assertIn('"os:edit_jewel_to_points_rate"', services)
        self.assertIn('"os:edit_points_to_jewel_rate"', services)
        self.assertIn('state == "os_await_jewels_to_points_rate"', messages)
        self.assertIn('"os_await_points_to_jewels_rate"', messages)
        self.assertIn("CREATE TABLE IF NOT EXISTS currency_exchange_transactions", database)
        self.assertIn("('jewels_to_points_rate', '5000')", database)
        self.assertIn("('points_to_jewels_rate', '7000')", database)


if __name__ == "__main__":
    unittest.main()
