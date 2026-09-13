import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
UI = ROOT / "bot_app" / "ui.py"
CALLBACKS = ROOT / "bot_app" / "callback_groups_02.py"


class SendReadyAccountsTests(unittest.TestCase):
    def test_account_menu_exposes_read_only_send_ready_list(self):
        ui_source = UI.read_text(encoding="utf-8")
        callback_source = CALLBACKS.read_text(encoding="utf-8")
        accounts_source = (ROOT / "bot_app" / "accounts.py").read_text(encoding="utf-8")

        self.assertIn('callback_data="os:send_ready_accounts"', ui_source)
        self.assertIn('if data == "os:send_ready_accounts" and is_own:', callback_source)
        self.assertIn("find_unrestricted_message_accounts()", callback_source)
        self.assertIn("check_spam_status_detailed(client)", accounts_source)
        self.assertIn('detail.get("restricted") is False', accounts_source)

    def test_send_ready_list_does_not_reclassify_accounts(self):
        callback_source = CALLBACKS.read_text(encoding="utf-8")
        start = callback_source.index('if data == "os:send_ready_accounts" and is_own:')
        end = callback_source.index('if data == "os:account_names" and is_own:', start)
        block = callback_source[start:end]

        self.assertNotIn("UPDATE number_stock", block)
        self.assertIn("os:number_info:", block)
        self.assertIn("لن يتم تغيير حالة البيع أو الرشق", block)

    def test_export_uses_encrypted_session_documents(self):
        ui_source = UI.read_text(encoding="utf-8")
        callback_source = CALLBACKS.read_text(encoding="utf-8")

        self.assertIn('callback_data="os:export_ready_sessions"', ui_source)
        start = callback_source.index('if data == "os:export_ready_sessions" and is_own:')
        end = callback_source.index('if data == "os:account_names" and is_own:', start)
        block = callback_source[start:end]

        self.assertIn("SESSION_EXPORT_KEY", block)
        self.assertIn("Fernet", block)
        self.assertIn("session_string", block)
        self.assertIn("send_document", block)
        self.assertIn(".session.enc", block)
        self.assertNotIn("document=_export_session", block)


if __name__ == "__main__":
    unittest.main()
