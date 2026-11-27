import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MESSAGES = ROOT / "bot_app" / "messages.py"
ASSIST = ROOT / "bot_app" / "login_assist.py"


class LoginCodeDeliveryTests(unittest.TestCase):
    def test_owner_login_explains_telegram_delivery_channel(self):
        source = MESSAGES.read_text(encoding="utf-8") + ASSIST.read_text(encoding="utf-8")
        self.assertIn("SentCodeTypeApp", source)
        self.assertIn("SentCodeTypeSms", source)
        self.assertIn("777000", source)
        self.assertIn("def _login_code_delivery_note(sent)", source)
        self.assertIn("describe_code_delivery(sent)", source)

    def test_owner_login_surfaces_common_telegram_errors(self):
        source = MESSAGES.read_text(encoding="utf-8")
        self.assertIn("PhoneNumberBannedError", source)
        self.assertIn("PhoneNumberFloodError", source)
        self.assertIn("SendCodeUnavailableError", source)
        self.assertIn("_login_code_error_message(e)", source)

    def test_phone_spaces_are_removed_before_telegram_request(self):
        source = MESSAGES.read_text(encoding="utf-8")
        self.assertIn("phone = normalize_login_phone(text)", source)


if __name__ == "__main__":
    unittest.main()