import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class NumberPurchaseExclusionTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "bot_app" / "accounts.py").read_text(encoding="utf-8")

    def test_sellable_filter_excludes_deleted_frozen_and_number_admin_accounts(self):
        start = self.source.index("def _sellable_filter_sql")
        end = self.source.index("def get_available_number_count", start)
        sellable_filter = self.source[start:end]

        self.assertIn("deleted_at IS NULL", sellable_filter)
        self.assertIn("frozen_at IS NULL", sellable_filter)
        self.assertIn("ever_sold IS NOT TRUE", sellable_filter)
        self.assertIn("sale_excluded IS NOT TRUE", sellable_filter)
        self.assertIn("NOT EXISTS", sellable_filter)
        self.assertIn("FROM number_admins", sellable_filter)

    def test_verified_purchase_does_not_use_blocked_account_fallback(self):
        start = self.source.index("async def assign_verified_number")
        purchase_flow = self.source[start:]

        self.assertIn("_sellable_filter_sql()", purchase_flow)
        self.assertNotIn("_sellable_filter_sql(allow_send_blocked=True)", purchase_flow)

    def test_deleted_account_errors_are_classified_as_unavailable(self):
        start = self.source.index("async def check_account_frozen")
        end = self.source.index("async def scan_all_account_statuses", start)
        frozen_check = self.source[start:end]

        self.assertIn("user has been deleted", frozen_check)
        self.assertIn("deleted/deactivated", frozen_check)
        self.assertIn("userdeactivatedbanerror", frozen_check)
        self.assertIn("phonenumberbannederror", frozen_check)


if __name__ == "__main__":
    unittest.main()