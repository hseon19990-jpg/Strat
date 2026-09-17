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


if __name__ == "__main__":
    unittest.main()