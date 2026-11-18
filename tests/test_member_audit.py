import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_pure():
    src = (ROOT / "bot_app" / "member_audit.py").read_text(encoding="utf-8")
    block = src.split("# PURE-START", 1)[1].split("# PURE-END", 1)[0]
    ns = {}
    exec(compile(block, "member_audit_pure", "exec"), ns)
    return ns


class MemberAuditPureTests(unittest.TestCase):
    def setUp(self):
        self.ns = _load_pure()
        from datetime import datetime, timedelta, timezone
        self.dt = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
        self.td = timedelta

    def acct(self, **kw):
        base = dict(id=1, phone_number="+9647701234567", added_at=self.dt, kicked_at=None,
                    frozen_at=None, deleted_at=None, raksh_excluded=False, last_authorized=True,
                    has_session=True, earned=0, jobs=0, sessions_reset=False, last_at=None)
        base.update(kw)
        return base

    def test_state(self):
        st = self.ns["ma_account_state"]
        self.assertEqual(st(self.acct()), "alive")
        self.assertEqual(st(self.acct(last_authorized=False)), "dead")
        self.assertEqual(st(self.acct(has_session=False)), "dead")
        self.assertEqual(st(self.acct(frozen_at=self.dt, last_authorized=False, has_session=False)), "frozen")
        self.assertEqual(st(self.acct(deleted_at=self.dt)), "removed")
        self.assertEqual(st(self.acct(raksh_excluded=True)), "excluded")

    def test_mask_never_leaks_full_number(self):
        masked = self.ns["ma_mask_phone"]("+9647701234567")
        self.assertNotIn("1234567", masked)
        self.assertTrue(masked.endswith("567"))

    def test_burst(self):
        burst = self.ns["ma_max_burst"]
        t = [self.dt, self.dt + self.td(minutes=5), self.dt + self.td(minutes=9), self.dt + self.td(hours=5)]
        self.assertEqual(burst(t, 30), 3)
        self.assertEqual(burst([self.dt, self.dt + self.td(hours=2)], 30), 1)

    def test_assess_coordinated_quick_kick(self):
        rows = [self.acct(id=i, last_authorized=False, kicked_at=self.dt + self.td(hours=1, minutes=i)) for i in range(3)]
        icons = [i for i, _ in self.ns["ma_assess"](rows, 24, 30)]
        self.assertIn("🔴", icons)

    def test_assess_frozen_supports_member(self):
        rows = [self.acct(frozen_at=self.dt, last_authorized=False, has_session=False)]
        out = self.ns["ma_assess"](rows, 24, 30)
        self.assertTrue(any(i == "🟢" and "مجمّد" in t for i, t in out))

    def test_assess_all_alive_not_supported(self):
        out = self.ns["ma_assess"]([self.acct(), self.acct(id=2)], 24, 30)
        self.assertEqual(out[0][0], "🟢")
        self.assertIn("غير مدعوم", out[0][1])

    def test_assess_sessions_reset_flags_possible_mass_kick(self):
        out = self.ns["ma_assess"]([self.acct(sessions_reset=True)], 24, 30)
        self.assertTrue(any("طرد جماعي" in t for _, t in out))

    def test_account_line_has_no_session_or_password(self):
        line = self.ns["ma_format_account_line"](self.acct(last_authorized=False, kicked_at=self.dt + self.td(days=2)))
        self.assertIn("مطرود", line)
        self.assertNotIn("session", line.lower())


class MemberAuditWiringTests(unittest.TestCase):
    def test_mass_kick_commands_skip_rented_accounts(self):
        for rel in ("bot_app/callback_groups_03.py", "bot_app/onboarding.py"):
            src = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("contributed_by IS NULL AND raksh_only IS NOT TRUE", src, rel)

    def test_audit_is_routed(self):
        self.assertIn("os:ma:", (ROOT / "bot_app" / "callbacks.py").read_text(encoding="utf-8"))
        self.assertIn("os_await_audit_target", (ROOT / "bot_app" / "messages.py").read_text(encoding="utf-8"))
        self.assertIn("ma_monitor_job", (ROOT / "bot_app" / "application.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
