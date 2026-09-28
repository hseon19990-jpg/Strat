import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
CALLBACKS = ROOT / "bot_app" / "callback_groups_02.py"
MESSAGES = ROOT / "bot_app" / "messages.py"
SERVICES = ROOT / "bot_app" / "services.py"
USERS = ROOT / "bot_app" / "users.py"
DATABASE = ROOT / "bot_app" / "database.py"


class ReferralRewardSectionsTests(unittest.TestCase):
    def test_owner_menu_exposes_two_independent_sections(self):
        source = SERVICES.read_text(encoding="utf-8")
        self.assertIn('"os:referral_rewards"', source)
        self.assertIn('"os:referral_daily_free"', source)

        callbacks = CALLBACKS.read_text(encoding="utf-8")
        self.assertIn("تغيير مكافأة الإحالة عند بلوغ عدد معين", callbacks)
        self.assertIn("إعادة الضبط اليومية للإحالات", callbacks)

    def test_reward_and_daily_free_flows_use_separate_states(self):
        source = MESSAGES.read_text(encoding="utf-8")
        self.assertIn("os_await_ref_tier_points", source)
        self.assertIn("os_await_ref_daily_count", source)
        self.assertIn("os_await_ref_daily_minutes", source)
        self.assertNotIn("os_await_ref_tier_minutes", source)

    def test_daily_free_access_has_a_daily_claim_key(self):
        database = DATABASE.read_text(encoding="utf-8")
        self.assertIn("referral_daily_free_tiers", database)
        self.assertIn("referral_daily_free_claims", database)
        self.assertIn("PRIMARY KEY (user_id, tier_id, claim_date)", database)

        users = USERS.read_text(encoding="utf-8")
        self.assertIn("ON CONFLICT (user_id, tier_id, claim_date) DO NOTHING", users)
        self.assertIn("refresh_daily_referral_free_access", users)


if __name__ == "__main__":
    unittest.main()