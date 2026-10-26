import asyncio
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).parents[1]
USERS = ROOT / "bot_app" / "users.py"
ONBOARDING = ROOT / "bot_app" / "onboarding.py"
CALLBACKS = ROOT / "bot_app" / "callback_groups_01.py"
ACCOUNTS = ROOT / "bot_app" / "accounts.py"
UI = ROOT / "bot_app" / "ui.py"


def _load_should_notify():
    tree = ast.parse(USERS.read_text(encoding="utf-8"))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "should_notify_referral_link_opened"
    )
    namespace = {}
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), str(USERS), "exec"),
        namespace,
    )
    return namespace["should_notify_referral_link_opened"]


def _load_proceed_after_mandatory(unjoined_channels):
    source = ONBOARDING.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.AsyncFunctionDef)
        and item.name == "proceed_after_mandatory"
    )
    calls = {}

    async def get_unjoined_mandatory_channels(context, user_id):
        return unjoined_channels

    async def show_mandatory_gate(update, context, channels, edit=False, is_owner=False):
        calls["gate"] = (channels, edit, is_owner)

    async def finalize_verification(update, context, user, edit=False, skip_referral=False):
        calls["finalized"] = (user.id, edit, skip_referral)

    namespace = {
        "OWNER_ID": 1,
        "Update": object,
        "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
        "get_unjoined_mandatory_channels": get_unjoined_mandatory_channels,
        "show_mandatory_gate": show_mandatory_gate,
        "finalize_verification": finalize_verification,
    }
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), str(ONBOARDING), "exec"),
        namespace,
    )
    return namespace["proceed_after_mandatory"], calls


class ReferralFlowTests(unittest.TestCase):
    def test_first_valid_link_open_is_notified(self):
        should_notify = _load_should_notify()
        self.assertTrue(should_notify(0, 10, 10, 20))

    def test_reopening_same_link_is_not_notified(self):
        should_notify = _load_should_notify()
        self.assertFalse(should_notify(10, 10, 10, 20))

    def test_self_referral_is_ignored(self):
        should_notify = _load_should_notify()
        self.assertFalse(should_notify(0, 20, 0, 20))

    def test_verification_completes_referral_without_daily_gift(self):
        source = ONBOARDING.read_text(encoding="utf-8")
        start = source.index("async def finalize_verification")
        end = source.index("async def start_onboarding", start)
        block = source[start:end]
        self.assertIn("credit_referral_if_pending(user.id, context)", block)
        self.assertNotIn("استلام الهدية اليومية", block)

    def test_credit_requires_verified_user(self):
        source = USERS.read_text(encoding="utf-8")
        start = source.index("def credit_referral_if_pending")
        end = source.index("def _referral_counter_reset_at", start)
        block = source[start:end]
        self.assertIn("SELECT invited_by, referral_credited, verified", block)
        self.assertIn("or not row[\"verified\"]", block)

    def test_referral_onboarding_requires_all_mandatory_channels_only(self):
        source = ONBOARDING.read_text(encoding="utf-8")
        start = source.index("async def proceed_after_mandatory")
        end = source.index("async def _notify_referral_credit", start)
        block = source[start:end]
        self.assertIn("get_unjoined_mandatory_channels", block)
        self.assertIn("await finalize_verification", block)
        self.assertNotIn("captcha_enabled", block)
        self.assertNotIn("ask_for_phone_share", block)

        proceed, calls = _load_proceed_after_mandatory(
            [{"channel_username": "required_channel"}]
        )
        update = SimpleNamespace(effective_user=SimpleNamespace(id=20))
        context = SimpleNamespace(user_data={})
        asyncio.run(proceed(update, context))
        self.assertEqual(context.user_data["state"], "await_mandatory_join")
        self.assertIn("gate", calls)
        self.assertNotIn("finalized", calls)

    def test_referral_is_completed_after_all_required_channels_are_joined(self):
        proceed, calls = _load_proceed_after_mandatory([])
        update = SimpleNamespace(effective_user=SimpleNamespace(id=20))
        context = SimpleNamespace(user_data={})
        asyncio.run(proceed(update, context, edit=True))
        self.assertEqual(calls["finalized"], (20, True, False))

    def test_phone_country_rejection_and_phone_collection_are_removed(self):
        accounts = ACCOUNTS.read_text(encoding="utf-8")
        contact_start = accounts.index("async def handle_contact_share")
        contact_end = accounts.index("\ndef guess_country", contact_start)
        contact_handler = accounts[contact_start:contact_end]
        self.assertNotIn("contact.phone_number", contact_handler)
        self.assertNotIn("classify_phone_region", accounts)
        self.assertNotIn("request_contact=True", accounts)
        self.assertNotIn("notify_referral_result_to_numbers_group", accounts)

    def test_removed_phone_and_captcha_controls_are_hidden(self):
        owner_settings = UI.read_text(encoding="utf-8").split(
            "def owner_settings_kb():", 1
        )[1].split("\ndef _account_info_counts", 1)[0]
        self.assertIn('"os:toggle_phone_verification"', owner_settings)
        self.assertIn('"os:toggle_captcha"', owner_settings)
        self.assertIn("if btn.callback_data not in disabled_verification_items", owner_settings)


if __name__ == "__main__":
    unittest.main()