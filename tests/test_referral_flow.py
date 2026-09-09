import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
USERS = ROOT / "bot_app" / "users.py"
ONBOARDING = ROOT / "bot_app" / "onboarding.py"
CALLBACKS = ROOT / "bot_app" / "callback_groups_01.py"


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

    def test_daily_gift_screen_only_credits_after_a_new_claim(self):
        source = CALLBACKS.read_text(encoding="utf-8")
        start = source.index('if data == "daily_gift_screen":')
        end = source.index('if data == "daily_gift_collect":', start)
        block = source[start:end]
        self.assertIn("if claimed", block)
        self.assertIn("credit_referral_if_pending(user.id, context)", block)
        self.assertIn("else None", block)

    def test_credit_requires_verified_user(self):
        source = USERS.read_text(encoding="utf-8")
        start = source.index("def credit_referral_if_pending")
        end = source.index("def _referral_counter_reset_at", start)
        block = source[start:end]
        self.assertIn("SELECT invited_by, referral_credited, verified", block)
        self.assertIn("or not row[\"verified\"]", block)


if __name__ == "__main__":
    unittest.main()