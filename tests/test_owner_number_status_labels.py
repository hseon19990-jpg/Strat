import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class OwnerNumberStatusLabelTests(unittest.TestCase):
    def test_owner_phone_search_reads_and_labels_rented_accounts(self):
        source = (ROOT / "bot_app" / "messages.py").read_text(encoding="utf-8")

        self.assertIn("ns.raksh_only", source)
        self.assertIn("is_rented", source)
        self.assertIn("مؤجّر للرشق", source)
        self.assertIn("contributor_share_percent", source)

    def test_owner_account_details_shows_sold_or_rented_marker(self):
        source = (ROOT / "bot_app" / "callback_groups_02.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("raksh_only, contributor_share_percent", source)
        self.assertIn("🟢 مباع", source)
        self.assertIn("مؤجّر للرشق", source)

    def test_owner_status_menu_has_rented_and_sold_lists(self):
        source = (ROOT / "bot_app" / "callback_groups_04.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("os:owner_number_status", source)
        self.assertIn("os:rented_accounts", source)
        self.assertIn("os:sold_accounts", source)
        self.assertIn("raksh_contributor_earnings", source)


if __name__ == "__main__":
    unittest.main()