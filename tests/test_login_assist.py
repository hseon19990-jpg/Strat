import asyncio
import importlib.util
import logging
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load_login_assist():
    pkg = types.ModuleType("bot_app")
    pkg.__path__ = [str(ROOT / "bot_app")]
    shared = types.ModuleType("bot_app.shared")

    class Button:
        def __init__(self, text, callback_data=None, url=None):
            self.text, self.callback_data, self.url = text, callback_data, url

    shared.InlineKeyboardButton = Button
    shared.InlineKeyboardMarkup = lambda rows: rows
    shared.asyncio = asyncio
    shared.logger = logging.getLogger("login_assist_test")
    shared.ParseMode = types.SimpleNamespace(MARKDOWN="Markdown")
    shared._pending_number_logins = {}
    shared.FloodWaitError = type("FloodWaitError", (Exception,), {})
    shared.SessionPasswordNeededError = type("SessionPasswordNeededError", (Exception,), {})
    telegram = types.ModuleType("telegram")
    telegram.InputMediaPhoto = object
    saved = {k: sys.modules.get(k) for k in ("bot_app", "bot_app.shared", "telegram")}
    sys.modules.update({"bot_app": pkg, "bot_app.shared": shared, "telegram": telegram})
    try:
        spec = importlib.util.spec_from_file_location(
            "bot_app.login_assist", ROOT / "bot_app" / "login_assist.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["bot_app.login_assist"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
        sys.modules.pop("bot_app.login_assist", None)


class LoginAssistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load_login_assist()

    def test_phone_normalization(self):
        n = self.m.normalize_login_phone
        self.assertEqual(n("+977 98-1234 5678"), "+9779812345678")
        self.assertEqual(n("٠٠٩٧٧٩٨١٢٣٤٥٦٧٨"), "+9779812345678")
        self.assertEqual(n("9779812345678"), "+9779812345678")
        self.assertEqual(n("+٩٦٤٧٧٠١٢٣٤٥٦٧"), "+9647701234567")
        self.assertFalse(self.m.is_valid_login_phone(n("abc")))
        self.assertFalse(self.m.is_valid_login_phone("+12"))

    def test_code_normalization(self):
        c = self.m.normalize_login_code
        self.assertEqual(c("1 2 3 4 5"), "12345")
        self.assertEqual(c("12-345"), "12345")
        self.assertEqual(c("Login code: 54321. Do not give this code"), "54321")
        self.assertEqual(c("٧٨٩٠١"), "78901")

    def test_unsupported_delivery_channels_are_flagged(self):
        def sent(name):
            return types.SimpleNamespace(type=type(name, (), {})())

        self.assertTrue(self.m.describe_code_delivery(sent("SentCodeTypeSetUpEmailRequired"))[1])
        self.assertTrue(self.m.describe_code_delivery(sent("SentCodeTypeFirebaseSms"))[1])
        self.assertFalse(self.m.describe_code_delivery(sent("SentCodeTypeSms"))[1])
        self.assertFalse(self.m.describe_code_delivery(sent("SentCodeTypeApp"))[1])

    def test_member_keyboard_offers_resend_and_codeless_login(self):
        rows = self.m.login_assist_kb(contributor=True)
        data = [row[0].callback_data for row in rows]
        self.assertEqual(data, ["ctlogin:inapp", "ctlogin:resend", "ctlogin:qr", "ctlogin:cancel"])
        rows = self.m.login_assist_kb(contributor=True, resends_left=0)
        self.assertNotIn("ctlogin:resend", [row[0].callback_data for row in rows])

    def test_wiring(self):
        init = (ROOT / "bot_app" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('"login_assist"', init)
        callbacks = (ROOT / "bot_app" / "callbacks.py").read_text(encoding="utf-8")
        self.assertIn('data.startswith("ctlogin:")', callbacks)


if __name__ == "__main__":
    unittest.main()


class CodelessFlowWiringTests(unittest.TestCase):
    def test_entry_buttons_and_failure_fallback_exist(self):
        groups = (ROOT / "bot_app" / "callback_groups_01.py").read_text(encoding="utf-8")
        self.assertIn("ctlogin:nocode:share", groups)
        self.assertIn("ctlogin:nocode:rent", groups)
        messages = (ROOT / "bot_app" / "messages.py").read_text(encoding="utf-8")
        self.assertIn("begin_codeless_login", messages)
        self.assertGreaterEqual(messages.count("offer_codeless_login"), 4)
        assist = (ROOT / "bot_app" / "login_assist.py").read_text(encoding="utf-8")
        # لا يُطلب كود عند الدخول بدون كود، ويُسمح بالـ QR بلا عميل سابق.
        self.assertIn('"client": None', assist)
        self.assertIn('if not pending or not pending.get("phone"):', assist)
