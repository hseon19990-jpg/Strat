import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class ContributorSessionShareTests(unittest.TestCase):
    def test_share_account_entry_offers_number_and_session(self):
        source = (ROOT / "bot_app" / "callback_groups_01.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('if data == "share_account:menu":', source)
        self.assertIn('callback_data="share_number:menu"', source)
        self.assertIn('callback_data="share_session:menu"', source)

    def test_uploaded_session_uses_the_personal_free_account_pool(self):
        source = (ROOT / "bot_app" / "messages.py").read_text(encoding="utf-8")
        handler = source.split(
            "async def handle_share_session_document", 1
        )[1].split("\nasync def handle_json_file", 1)[0]
        self.assertIn('contributor_method="session"', handler)
        self.assertIn("share_percent=0", handler)
        self.assertIn("_extract_buyback_session_uploads", handler)
        self.assertIn("_parse_buyback_session_upload", handler)
        self.assertIn("for index, (entry_name, entry_bytes) in enumerate(uploads", handler)

    def test_database_records_session_shares_separately(self):
        accounts = (ROOT / "bot_app" / "accounts.py").read_text(encoding="utf-8")
        database = (ROOT / "bot_app" / "database.py").read_text(encoding="utf-8")
        self.assertIn("contributor_method TEXT NOT NULL DEFAULT 'number'", database)
        self.assertIn("ns.contributor_method", accounts)
        self.assertIn("contributor_method=%s", accounts)


if __name__ == "__main__":
    unittest.main()
