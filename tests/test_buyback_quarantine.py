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
    namespace = {"DEFAULT_BUYBACK_PRICE": 7000}
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), str(BUYBACK), "exec"),
        namespace,
    )
    return namespace["format_buyback_price"]


class BuybackQuarantineTests(unittest.TestCase):
    def test_price_formatting_is_stable_for_valid_and_missing_values(self):
        format_price = _load_price_formatter()
        self.assertEqual(format_price(7000), "7,000 نقطة")
        self.assertEqual(format_price("4000"), "4,000 نقطة")
        self.assertEqual(format_price(0), "7,000 نقطة")
        self.assertEqual(format_price("not-a-price"), "7,000 نقطة")

    def test_security_loop_checks_sessions_and_spambot_every_cycle(self):
        source = BUYBACK.read_text(encoding="utf-8")
        self.assertIn("check_spam_status_detailed(client)", source)
        self.assertIn("ResetAuthorizationsRequest()", source)
        self.assertIn("ORDER BY COALESCE(last_checked_at,created_at), id LIMIT 50", source)
        self.assertIn("state == \"retry\"", source)
        self.assertIn("state == \"reject\"", source)
        self.assertIn("set_buyback_price", source)

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

    def test_owner_can_change_the_point_price_for_new_offers(self):
        ui_source = (ROOT / "bot_app" / "ui.py").read_text(encoding="utf-8")
        callback_source = (
            ROOT / "bot_app" / "callback_groups_04.py"
        ).read_text(encoding="utf-8")
        message_source = (ROOT / "bot_app" / "messages.py").read_text(encoding="utf-8")
        database_source = (ROOT / "bot_app" / "database.py").read_text(encoding="utf-8")

        self.assertIn('callback_data="os:edit_buyback_price"', ui_source)
        self.assertIn('data == "os:edit_buyback_price" and is_own', callback_source)
        self.assertIn('state == "os_await_buyback_price" and is_own', message_source)
        self.assertIn('set_buyback_price(new_price)', message_source)
        self.assertIn("('buyback_price', '7000')", database_source)


    def test_price_is_selected_after_final_spambot_check(self):
        source = BUYBACK.read_text(encoding="utf-8")
        database_source = (ROOT / "bot_app" / "database.py").read_text(encoding="utf-8")

        self.assertIn('"restricted": bool(restricted)', source)
        self.assertIn(
            'final_price = _buyback_price(restricted=bool(result.get("restricted")))',
            source,
        )
        self.assertIn("quoted_price=%s", source)
        self.assertIn("('buyback_restricted_price', '4000')", database_source)
        self.assertIn("DEFAULT_BUYBACK_PRICE = 7000", source)
        self.assertIn("DEFAULT_BUYBACK_RESTRICTED_PRICE = 4000", source)


if __name__ == "__main__":
    unittest.main()