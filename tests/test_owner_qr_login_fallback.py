import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MESSAGES = ROOT / "bot_app" / "messages.py"
SECURITY = ROOT / "bot_app" / "security.py"
CALLBACKS = ROOT / "bot_app" / "callback_groups_03.py"


class OwnerQrLoginFallbackTests(unittest.TestCase):
    def test_code_flow_exposes_qr_fallback(self):
        source = MESSAGES.read_text(encoding="utf-8")
        self.assertIn('callback_data="os:login_qr_fallback"', source)
        self.assertIn("الدخول عبر QR بدل الكود", source)

    def test_qr_flow_verifies_the_requested_phone(self):
        source = SECURITY.read_text(encoding="utf-8")
        self.assertIn("async def _start_owner_qr_login", source)
        self.assertIn("async def _wait_owner_qr_login", source)
        self.assertIn("تم مسح QR لحساب مختلف عن الرقم المطلوب", source)
        self.assertIn("qr_login.wait()", source)

    def test_callback_starts_qr_fallback_only_for_pending_login(self):
        source = CALLBACKS.read_text(encoding="utf-8")
        self.assertIn('if data == "os:login_qr_fallback" and is_own:', source)
        self.assertIn("_start_owner_qr_login(update, context, user.id)", source)


if __name__ == "__main__":
    unittest.main()