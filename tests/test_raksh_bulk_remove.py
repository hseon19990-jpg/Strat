import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class RakshBulkRemoveTests(unittest.TestCase):
    def test_raksh_menu_exposes_bulk_remove(self):
        source = (ROOT / "bot_app" / "callback_groups_02.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('callback_data="os:raksh_unmark_bulk"', source)
        self.assertIn('state"] = "os_await_raksh_unmark_accounts"', source)

    def test_bulk_remove_accepts_phone_id_and_username_inputs(self):
        source = (ROOT / "bot_app" / "messages.py").read_text(encoding="utf-8")
        start = source.index('state == "os_await_raksh_unmark_accounts"')
        end = source.index(
            'state in {"os_await_raksh_add_accounts", "os_await_raksh_mark_numbers"}',
            start,
        )
        block = source[start:end]

        self.assertIn("number_stock", block)
        self.assertIn("phone_number", block)
        self.assertIn("get_me()", block)
        self.assertIn("raksh_only=FALSE", block)
        self.assertIn("raksh_excluded=TRUE", block)

    def test_removal_pool_is_independent_of_raksh_only(self):
        accounts_source = (ROOT / "bot_app" / "accounts.py").read_text(
            encoding="utf-8"
        )
        common_source = (ROOT / "bot_app" / "raksh_system" / "common.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("AND BTRIM(session_string) <> ''", accounts_source)
        self.assertIn("raksh_excluded=TRUE", accounts_source)
        self.assertIn("AND raksh_excluded IS NOT TRUE", common_source)

    def test_raksh_exclusion_column_is_migrated(self):
        source = (ROOT / "bot_app" / "database.py").read_text(encoding="utf-8")
        self.assertIn(
            "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS raksh_excluded",
            source,
        )


if __name__ == "__main__":
    unittest.main()