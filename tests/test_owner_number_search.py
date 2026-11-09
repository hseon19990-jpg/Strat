import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(*parts):
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


class OwnerNumberSearchWiringTests(unittest.TestCase):
    def test_menu_has_owner_search_button(self):
        source = _read("bot_app", "callback_groups_02.py")
        self.assertIn("os:owner_search", source)

    def test_callbacks_are_owner_only(self):
        source = _read("bot_app", "callback_groups_03.py")
        for marker in (
            'data == "os:owner_search" and is_own',
            'data == "os:owner_search_deep" and is_own',
            'data.startswith("os:osv:") and is_own',
        ):
            self.assertIn(marker, source)

    def test_message_state_is_owner_only(self):
        source = _read("bot_app", "messages.py")
        self.assertIn('is_own and state == "os_await_owner_search"', source)

    def test_identity_cache_columns_are_migrated(self):
        source = _read("bot_app", "database.py")
        for column in ("tg_user_id", "tg_username", "tg_name", "tg_info_at"):
            self.assertIn(f"number_stock ADD COLUMN IF NOT EXISTS {column}", source)

    def test_card_reuses_existing_code_and_kick_actions(self):
        source = _read("bot_app", "number_owner_search.py")
        self.assertIn("os:sold_code:", source)
        self.assertIn("os:sold_kick:", source)
        self.assertIn("os:sold_2fa:", source)


if __name__ == "__main__":
    unittest.main()
