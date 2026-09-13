import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
BUYBACK = ROOT / "bot_app" / "buyback.py"
APPLICATION = ROOT / "bot_app" / "application.py"


def _load_price_formatter():
    tree = ast.parse(BUYBACK.read_text(encoding="utf-8"))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "format_buyback_price"
    )
    namespace = {}
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), str(BUYBACK), "exec"),
        namespace,
    )
    return namespace["format_buyback_price"]


class BuybackQuarantineTests(unittest.TestCase):
    def test_price_formatting_is_stable_for_valid_and_missing_values(self):
        format_price = _load_price_formatter()
        self.assertEqual(format_price(7000), "7,000 دينار")
        self.assertEqual(format_price("4000"), "4,000 دينار")
        self.assertEqual(format_price(0), "يحدده المالك بعد الفحص")
        self.assertEqual(format_price("not-a-price"), "يحدده المالك بعد الفحص")

    def test_security_loop_checks_sessions_and_spambot_every_cycle(self):
        source = BUYBACK.read_text(encoding="utf-8")
        self.assertIn("check_spam_status_detailed(client)", source)
        self.assertIn("ResetAuthorizationsRequest()", source)
        self.assertIn("ORDER BY COALESCE(last_checked_at,created_at), id LIMIT 50", source)
        self.assertIn("state == \"retry\"", source)
        self.assertIn("state == \"reject\"", source)

        app_source = APPLICATION.read_text(encoding="utf-8")
        self.assertIn(
            "app.job_queue.run_repeating(process_buyback_quarantine_job, interval=300",
            app_source,
        )

    def test_stock_insert_is_gated_by_successful_owner_payment(self):
        source = BUYBACK.read_text(encoding="utf-8")
        start = source.index("def mark_buyback_paid")
        end = source.index("def reject_buyback_offer", start)
        payment_block = source[start:end]
        self.assertIn("status='ready_for_payment'", payment_block)
        self.assertIn("INSERT INTO number_stock", payment_block)
        self.assertIn("status='paid'", payment_block)

        confirm_start = source.index('if data.startswith("buyback:confirm:")')
        confirm_end = source.index('if data == "buyback:owner:list"', confirm_start)
        confirm_block = source[confirm_start:confirm_end]
        self.assertNotIn("INSERT INTO number_stock", confirm_block)
        self.assertIn("status='quarantine_24h'", confirm_block)


if __name__ == "__main__":
    unittest.main()