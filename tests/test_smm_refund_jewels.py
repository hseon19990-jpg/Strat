import ast
import unittest
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _load_refund_helpers():
    source_path = ROOT / "bot_app" / "security.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    names = {
        "_usd_to_refund_jewels",
        "_calc_refund_jewels_from_rate",
        "_credit_star_payment_as_jewels_once",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {
        "Decimal": Decimal,
        "InvalidOperation": InvalidOperation,
        "ROUND_HALF_UP": ROUND_HALF_UP,
    }
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(source_path), "exec"),
        namespace,
    )
    return namespace


class SmmRefundJewelsTests(unittest.TestCase):
    def test_one_cent_is_one_jewel_and_fractional_cents_are_preserved(self):
        helpers = _load_refund_helpers()
        refund = helpers["_usd_to_refund_jewels"]

        self.assertEqual(refund("0.01"), Decimal("1.000000"))
        self.assertEqual(refund("0.091"), Decimal("9.100000"))
        self.assertEqual(refund("0.024"), Decimal("2.400000"))
        self.assertEqual(refund("0.001"), Decimal("0.100000"))

    def test_partial_refund_uses_unfulfilled_quantity(self):
        helpers = _load_refund_helpers()
        calculate = helpers["_calc_refund_jewels_from_rate"]

        self.assertEqual(calculate("0.091", 1000), Decimal("9.100000"))
        self.assertEqual(calculate("0.024", 1000), Decimal("2.400000"))
        self.assertEqual(calculate("0.091", 0), Decimal("0"))

    def test_full_cancel_credits_star_paid_value_as_jewels(self):
        security_source = (ROOT / "bot_app" / "security.py").read_text(encoding="utf-8")
        tree = ast.parse(security_source)
        checker = next(
            node for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "check_pending_orders_job"
        )
        checker_source = ast.get_source_segment(security_source, checker)
        self.assertNotIn("refund_star_payment(", checker_source)
        self.assertIn('if payment_method == "stars":', checker_source)
        self.assertIn('Decimal(str(o.get("cost_stars") or 0))', checker_source)
        self.assertIn("refund_jewels=refund_amount", checker_source)
        self.assertIn('elif payment_method == "jewels":', checker_source)
        self.assertIn('refund_amount = int(o.get("cost_points") or 0)', checker_source)
        self.assertIn('elif payment_method == "free":', checker_source)

        messages_source = (ROOT / "bot_app" / "messages.py").read_text(encoding="utf-8")
        self.assertNotIn("refund_star_payment(", messages_source)
        self.assertIn('if payment_method in {"stars", "jewels"}:', messages_source)

        payments_source = (ROOT / "bot_app" / "payments.py").read_text(encoding="utf-8")
        smm_star_branch = payments_source.split(
            'if payload.startswith("smm_stars:"):', 1
        )[1].split('if payload.startswith("jewel_stars:"):', 1)[0]
        self.assertNotIn("refund_star_payment(", smm_star_branch)
        self.assertIn("_credit_star_payment_as_jewels_once(", smm_star_branch)
        self.assertNotIn("refund_star_payment(", payments_source)
        self.assertIn(
            "_credit_star_payment_as_jewels_once(",
            payments_source.split('if payload.startswith("jewel_stars:"):', 1)[1],
        )

    def test_star_payment_is_credited_as_jewels_once_per_charge(self):
        class Cursor:
            def __init__(self, row=None, rowcount=0):
                self.row = row
                self.rowcount = rowcount

            def fetchone(self):
                return self.row

        class FakeDb:
            def __init__(self):
                self.balance = Decimal("0")
                self.references = set()
                self.insert_count = 0

            def execute(self, sql, params=()):
                normalized = " ".join(sql.split())
                if normalized.startswith("SELECT pg_advisory_xact_lock"):
                    return Cursor()
                if normalized.startswith("SELECT id FROM jewel_transactions"):
                    return Cursor(
                        {"id": 1} if params[0] in self.references else None
                    )
                if normalized.startswith("UPDATE users SET jewels="):
                    amount, user_id = params
                    if user_id != 25:
                        return Cursor()
                    self.balance += Decimal(amount)
                    return Cursor({"jewels": self.balance}, 1)
                if normalized.startswith("INSERT INTO jewel_transactions"):
                    user_id, amount, reference = params
                    self.references.add(reference)
                    self.insert_count += 1
                    return Cursor(rowcount=1)
                raise AssertionError(f"Unexpected query: {normalized}")

        db = FakeDb()

        class DbContext:
            def __enter__(self):
                return db

            def __exit__(self, exc_type, exc, tb):
                return False

        helpers = _load_refund_helpers()
        helpers["db_conn"] = DbContext
        credit = helpers["_credit_star_payment_as_jewels_once"]

        self.assertTrue(credit(25, 9, "charge-123"))
        self.assertFalse(credit(25, 9, "charge-123"))
        self.assertEqual(db.balance, Decimal("9.000000"))
        self.assertEqual(db.insert_count, 1)


if __name__ == "__main__":
    unittest.main()
