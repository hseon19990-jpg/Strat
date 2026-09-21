import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class RakshStockPolicyTests(unittest.TestCase):
    def test_raksh_pool_excludes_sold_numbers_but_keeps_unfrozen_sessions(self):
        source = (ROOT / "bot_app" / "raksh_system" / "common.py").read_text(
            encoding="utf-8"
        )
        start = source.index("def _get_sessions_for_service")
        end = source.index("def get_available_sessions_count", start)
        pool = source[start:end]

        self.assertIn("AND ever_sold IS NOT TRUE", pool)
        self.assertIn("AND frozen_at IS NULL", pool)
        self.assertIn("def _mark_raksh_session_unauthorized", source)
        unauthorized = source.index(
            "def _mark_raksh_session_unauthorized"
        )
        frozen = source.index("def _mark_raksh_session_frozen", unauthorized)
        self.assertNotIn("session_string=NULL", source[unauthorized:frozen])

    def test_service_counts_exclude_sold_numbers(self):
        accounts_source = (ROOT / "bot_app" / "accounts.py").read_text(
            encoding="utf-8"
        )
        start = accounts_source.index("def get_raksh_account_count")
        end = accounts_source.index("def get_forced_ref_account_count", start)
        count_query = accounts_source[start:end]
        self.assertIn("AND ever_sold IS NOT TRUE", count_query)
        self.assertNotIn("AND frozen_at IS NULL", count_query)
        self.assertNotIn("session_string IS NOT NULL", count_query)

    def test_temporary_failures_do_not_delete_stock_rows(self):
        accounts_source = (ROOT / "bot_app" / "accounts.py").read_text(
            encoding="utf-8"
        )
        frozen_start = accounts_source.index("async def check_account_frozen")
        frozen_end = accounts_source.index("def ", frozen_start + 10)
        frozen_check = accounts_source[frozen_start:frozen_end]
        self.assertNotIn('"auth_key_unregistered"', frozen_check)
        self.assertNotIn('"session_revoked"', frozen_check)

        application_source = (ROOT / "bot_app" / "application.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(
            "WHERE session_string IS NULL AND deleted_at IS NULL",
            application_source,
        )

        onboarding_source = (ROOT / "bot_app" / "onboarding.py").read_text(
            encoding="utf-8"
        )
        start = onboarding_source.index("if not await _client.is_user_authorized()")
        end = onboarding_source.index("continue", start)
        self.assertNotIn("DELETE FROM number_stock", onboarding_source[start:end])

        scan_source = (ROOT / "bot_app" / "callback_groups_03.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("انتهت مهلة الاتصال (25ث) — لم يُحذف الرقم", scan_source)

    def test_referral_service_pools_exclude_sold_numbers(self):
        source = (ROOT / "bot_app" / "referrals.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("AND ever_sold IS NOT TRUE"), 3)


if __name__ == "__main__":
    unittest.main()