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

    def test_message_and_legendary_pools_exclude_frozen_accounts(self):
        message_source = (ROOT / "bot_app" / "raksh_system" / "message.py").read_text(
            encoding="utf-8"
        )
        legendary_source = (ROOT / "bot_app" / "legendary_comment.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("AND frozen_at IS NULL", message_source)
        self.assertIn("AND deleted_at IS NULL AND frozen_at IS NULL", legendary_source)

    def test_account_count_excludes_frozen_sessions(self):
        source = (ROOT / "bot_app" / "accounts.py").read_text(encoding="utf-8")
        start = source.index("def get_referral_session_count")
        end = source.index("def get_forced_ref_account_count", start)
        count_query = source[start:end]

        self.assertIn("AND frozen_at IS NULL", count_query)


if __name__ == "__main__":
    unittest.main()