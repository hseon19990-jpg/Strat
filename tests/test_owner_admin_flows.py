import ast
import unittest
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).parents[1]
CALLBACKS = ROOT / "bot_app" / "callback_groups_04.py"
MESSAGES = ROOT / "bot_app" / "messages.py"
SECURITY = ROOT / "bot_app" / "security.py"


def _load_jewel_helpers(db_conn):
    tree = ast.parse(SECURITY.read_text(encoding="utf-8"))
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_parse_jewel_amount", "deduct_jewels"}
    ]
    namespace = {
        "db_conn": db_conn,
        "Decimal": Decimal,
        "InvalidOperation": InvalidOperation,
        "ROUND_HALF_UP": ROUND_HALF_UP,
    }
    exec(
        compile(ast.Module(body=functions, type_ignores=[]), str(SECURITY), "exec"),
        namespace,
    )
    return namespace["_parse_jewel_amount"], namespace["deduct_jewels"]


class FakeCursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class FakeDatabase:
    def __init__(self, balance):
        self.balance = balance
        self.ledger = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=()):
        if query.startswith("UPDATE users SET jewels=COALESCE(jewels,0)-"):
            amount, _user_id, minimum_balance = params
            if self.balance < minimum_balance:
                return FakeCursor()
            self.balance -= amount
            return FakeCursor({"jewels": self.balance})
        if query.startswith("INSERT INTO jewel_transactions"):
            self.ledger.append((query, params))
        return FakeCursor()


class OwnerAdminFlowTests(unittest.TestCase):
    def test_jewel_deduction_is_atomic_and_records_admin(self):
        db = FakeDatabase(balance=20)
        _parse_jewel_amount, deduct_jewels = _load_jewel_helpers(lambda: db)

        new_balance = deduct_jewels(
            17,
            8,
            reference="owner_deduct",
            admin_id=99,
        )

        self.assertEqual(new_balance, 12)
        self.assertEqual(db.ledger[0][1], (17, -8, 99, "owner_deduct"))

    def test_jewel_deduction_does_not_overdraw_or_write_ledger(self):
        db = FakeDatabase(balance=3)
        _parse_jewel_amount, deduct_jewels = _load_jewel_helpers(lambda: db)

        new_balance = deduct_jewels(
            17,
            8,
            reference="owner_deduct",
            admin_id=99,
        )

        self.assertIsNone(new_balance)
        self.assertEqual(db.balance, 3)
        self.assertEqual(db.ledger, [])

    def test_fractional_jewel_deduction_preserves_precision_and_admin_ledger(self):
        db = FakeDatabase(balance=Decimal("10.750000"))
        _parse_jewel_amount, deduct_jewels = _load_jewel_helpers(lambda: db)

        new_balance = deduct_jewels(
            17,
            "0.125",
            reference="owner_deduct",
            admin_id=99,
        )

        self.assertEqual(new_balance, Decimal("10.625000"))
        self.assertEqual(
            db.ledger[0][1],
            (17, Decimal("-0.125000"), 99, "owner_deduct"),
        )

    def test_fractional_deduction_refuses_to_overdraw(self):
        db = FakeDatabase(balance=Decimal("0.25"))
        _parse_jewel_amount, deduct_jewels = _load_jewel_helpers(lambda: db)

        self.assertIsNone(deduct_jewels(17, "0.5", admin_id=99))
        self.assertEqual(db.balance, Decimal("0.25"))
        self.assertEqual(db.ledger, [])

    def test_jewel_amount_parser_accepts_locale_digits_and_rejects_excess_precision(self):
        parse_jewel_amount, _deduct_jewels = _load_jewel_helpers(lambda: None)

        self.assertEqual(parse_jewel_amount("٠٫٥"), Decimal("0.500000"))
        self.assertEqual(parse_jewel_amount("0,125"), Decimal("0.125000"))
        with self.assertRaises(ValueError):
            parse_jewel_amount("0.1234567")
        with self.assertRaises(ValueError):
            parse_jewel_amount("NaN")

    def test_owner_menu_exposes_deduction_and_routes_both_jewel_modes(self):
        callbacks = CALLBACKS.read_text(encoding="utf-8")
        messages = MESSAGES.read_text(encoding="utf-8")

        self.assertIn('callback_data="os:deduct_jewels"', callbacks)
        self.assertIn('data in ("os:give_jewels", "os:deduct_jewels")', callbacks)
        self.assertIn('jewels_mode=jewels_mode', callbacks)
        self.assertIn('if jewels_mode == "deduct":', messages)
        self.assertIn('reference="owner_deduct"', messages)
        self.assertIn('admin_id=user.id', messages)
        self.assertIn("_parse_jewel_amount(text.strip())", messages)
        self.assertIn("0.5، حتى 6 منازل عشرية", messages)

    def test_ban_menu_cancels_pending_ban_or_unban_input(self):
        callbacks = CALLBACKS.read_text(encoding="utf-8")
        ban_menu = callbacks.split(
            'if data == "os:ban_menu" and is_own:', 1
        )[1].split('if data == "os:ban_member" and is_own:', 1)[0]

        self.assertIn("reset_owner_flow(context)", ban_menu)
        self.assertIn('context.user_data.pop("ban_target_id", None)', ban_menu)


if __name__ == "__main__":
    unittest.main()
