import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RAKSH_SYSTEM = ROOT / "bot_app" / "raksh_system" / "raksh_system.py"


class RakshRefundPolicyTests(unittest.TestCase):
    def test_forced_referral_bonus_refund_is_removed(self):
        source = RAKSH_SYSTEM.read_text(encoding="utf-8")

        self.assertNotIn("RAKSH_FORCED_REF_REFUND_PERCENT", source)
        self.assertNotIn("_forced_ref_points_bonus_refund", source)
        self.assertNotIn("استرداد 10%", source)


if __name__ == "__main__":
    unittest.main()