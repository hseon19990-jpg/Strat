import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class RakshFrozenAccountTests(unittest.TestCase):
    def test_main_raksh_pool_excludes_frozen_accounts(self):
        source = (ROOT / "bot_app" / "raksh_system" / "common.py").read_text(
            encoding="utf-8"
        )
        start = source.index("def _get_sessions_for_service")
        end = source.index("def get_available_sessions_count", start)
        pool_query = source[start:end]

        self.assertIn("AND frozen_at IS NULL", pool_query)
        self.assertNotIn("AND last_authorized IS NOT FALSE", pool_query)

    def test_message_and_legendary_pools_exclude_frozen_accounts(self):
        message_source = (ROOT / "bot_app" / "raksh_system" / "message.py").read_text(
            encoding="utf-8"
        )
        legendary_source = (ROOT / "bot_app" / "legendary_comment.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("AND frozen_at IS NULL", message_source)
        self.assertIn("AND deleted_at IS NULL AND frozen_at IS NULL", legendary_source)

    def test_account_count_shows_all_non_sold_non_excluded_accounts(self):
        source = (ROOT / "bot_app" / "accounts.py").read_text(encoding="utf-8")
        start = source.index("def get_raksh_account_count")
        end = source.index("def get_forced_ref_account_count", start)
        count_query = source[start:end]

        self.assertIn("WHERE deleted_at IS NULL", count_query)
        self.assertIn("AND ever_sold IS NOT TRUE", count_query)
        self.assertIn("AND raksh_excluded IS NOT TRUE", count_query)
        self.assertNotIn("frozen_at IS NULL", count_query)
        self.assertNotIn("session_string IS NOT NULL", count_query)

    def test_raksh_pool_uses_all_non_frozen_sessions(self):
        common_source = (ROOT / "bot_app" / "raksh_system" / "common.py").read_text(
            encoding="utf-8"
        )
        start = common_source.index("def _get_sessions_for_service")
        end = common_source.index("def get_available_sessions_count", start)
        pool_query = common_source[start:end]

        self.assertIn("AND frozen_at IS NULL", pool_query)
        self.assertNotIn("AND last_authorized IS NOT FALSE", pool_query)
        self.assertNotIn("forced_ref_excluded IS NOT TRUE", pool_query)

    def test_legacy_raksh_pools_match_the_same_session_rule(self):
        referrals_source = (ROOT / "bot_app" / "referrals.py").read_text(
            encoding="utf-8"
        )
        message_source = (ROOT / "bot_app" / "raksh_system" / "message.py").read_text(
            encoding="utf-8"
        )
        forced_start = referrals_source.index("async def _run_forced_ref_order")
        forced_pool = referrals_source[forced_start:]

        self.assertIn("AND frozen_at IS NULL", forced_pool)
        self.assertNotIn("AND last_authorized IS NOT FALSE", forced_pool)
        self.assertNotIn("AND forced_ref_excluded IS NOT TRUE", forced_pool)
        self.assertNotIn("AND raksh_only IS NOT TRUE", forced_pool)
        self.assertNotIn("forced_ref_excluded IS NOT TRUE", message_source)

    def test_frozen_service_failures_persist_frozen_at_and_clear_pool_cache(self):
        common_source = (ROOT / "bot_app" / "raksh_system" / "common.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def _mark_raksh_session_frozen", common_source)
        self.assertIn("frozen_at=COALESCE(frozen_at, NOW())", common_source)
        self.assertIn("last_authorized=FALSE, session_string=NULL", common_source)
        all_posts_source = (
            ROOT / "bot_app" / "raksh_system" / "all_posts_reactions.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_mark_raksh_session_frozen(", all_posts_source)


if __name__ == "__main__":
    unittest.main()