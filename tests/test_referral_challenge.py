import ast
import random
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
ONBOARDING = ROOT / "bot_app" / "onboarding.py"


def _load():
    tree = ast.parse(ONBOARDING.read_text(encoding="utf-8"))
    funcs = {"referral_burst_hit", "make_math_challenge", "make_emoji_challenge"}
    consts = {
        "REFERRAL_BURST_COUNT", "REFERRAL_BURST_SECONDS", "REFERRAL_CHALLENGE_EMOJIS",
    }
    nodes = [
        n for n in tree.body
        if (isinstance(n, ast.FunctionDef) and n.name in funcs)
        or (isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in consts for t in n.targets))
    ]
    ns = {"_rc_secrets": __import__("secrets")}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ONBOARDING), "exec"), ns)
    return ns


class ReferralChallengeTests(unittest.TestCase):
    def setUp(self):
        self.ns = _load()

    def test_three_within_a_minute_is_a_burst(self):
        hit = self.ns["referral_burst_hit"]
        self.assertTrue(hit([0, 20, 59], 20))
        self.assertTrue(hit([0, 20, 59], 59))
        self.assertTrue(hit([100, 101, 102, 500], 101))

    def test_two_within_a_minute_is_not_a_burst(self):
        hit = self.ns["referral_burst_hit"]
        self.assertFalse(hit([0, 30], 30))
        self.assertFalse(hit([0, 30, 200], 30))

    def test_slow_referrals_are_not_a_burst(self):
        hit = self.ns["referral_burst_hit"]
        self.assertFalse(hit([0, 61, 122, 183], 122))

    def test_member_outside_the_burst_window_is_not_flagged(self):
        hit = self.ns["referral_burst_hit"]
        self.assertFalse(hit([0, 10, 20, 500], 500))

    def test_math_challenge_has_one_correct_addition_answer(self):
        make = self.ns["make_math_challenge"]
        for seed in range(200):
            a, b, options, idx = make(random.Random(seed))
            self.assertEqual(len(options), 4)
            self.assertEqual(len(set(options)), 4)
            self.assertEqual(options[idx], a + b)
            self.assertTrue(all(o > 0 for o in options))

    def test_emoji_challenge_has_six_distinct_options_and_valid_target(self):
        make = self.ns["make_emoji_challenge"]
        pool = set(self.ns["REFERRAL_CHALLENGE_EMOJIS"])
        for seed in range(200):
            options, idx = make(random.Random(seed))
            self.assertEqual(len(options), 6)
            self.assertEqual(len(set(options)), 6)
            self.assertTrue(set(options) <= pool)
            self.assertTrue(0 <= idx < 6)

    def test_gate_and_callback_are_wired(self):
        onboarding = ONBOARDING.read_text(encoding="utf-8")
        groups = (ROOT / "bot_app" / "callback_groups_01.py").read_text(encoding="utf-8")
        self.assertIn("start_referral_challenge_if_needed(update, context, user, edit=edit)", onboarding)
        self.assertLess(
            onboarding.index("start_referral_challenge_if_needed(update, context, user, edit=edit)"),
            onboarding.index("await finalize_verification(update, context, user, edit=edit, skip_referral=False)\n\nREFERRAL_FRAUD_MESSAGE"),
        )
        self.assertIn('data.startswith("rc:")', groups)
        self.assertIn("handle_referral_challenge_callback", groups)


if __name__ == "__main__":
    unittest.main()
