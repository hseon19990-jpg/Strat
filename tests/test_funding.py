import asyncio
import importlib.util
import sys
import types
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parents[1]
BOT = ROOT / "bot_app"


def _load_funding():
    spec = importlib.util.spec_from_file_location("funding_mod", BOT / "funding.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.f = _load_funding()

    def test_mandatory_stars_tiers(self):
        p = self.f.stars_price_mandatory
        self.assertEqual(p(100, 120, 50, 33), 50)     # عضوان بنجمة
        self.assertEqual(p(120, 120, 50, 33), 60)
        self.assertEqual(p(300, 120, 50, 33), 99)     # كل 3 بنجمة
        self.assertEqual(p(1, 120, 50, 33), 1)

    def test_internal_price_converts_points_to_stars(self):
        p = self.f.stars_price_internal
        self.assertEqual(p(1000, 100, 250), 400)      # 100000 نقطة / 250
        self.assertEqual(p(1, 100, 250), 1)           # حد أدنى نجمة
        self.assertEqual(p(10, 100, 0), 4)            # معدل غير صالح → 250

    def test_jewels_follow_star_rate(self):
        j = self.f.jewels_for_stars
        self.assertEqual(j(50, "1"), Decimal("50"))
        self.assertEqual(j(50, "0.5"), Decimal("25"))
        self.assertEqual(j(3, "0.333333"), Decimal("0.999999"))
        self.assertEqual(j(5, 0), Decimal("5"))

    def test_no_points_payment_left_in_flow(self):
        for name in ("callback_groups_02.py", "messages.py"):
            src = (BOT / name).read_text(encoding="utf-8")
            a = src.index("fund:mandatory") if name.startswith("callback") else src.index('state == "await_fund_member_count"')
            block = src[a:a + 9000]
            self.assertNotIn("deduct_points", block, name)
            self.assertNotIn("mandatory_points", block.replace("fund:mandatory:points", ""), name)
        cb = (BOT / "callback_groups_02.py").read_text(encoding="utf-8")
        self.assertIn('callback_data=f"fund:{_kind}:jewels"', cb)
        self.assertIn('callback_data=f"fund:{_kind}:stars"', cb)

    def test_jewel_payment_charges_once_and_refunds_on_failure(self):
        cb = (BOT / "callback_groups_02.py").read_text(encoding="utf-8")
        i = cb.index('if data == "fund_confirm:yes":')
        block = cb[i:i + 4500]
        # الحالة تُصفَّر قبل الخصم (منع الدفع المزدوج)، والإرجاع عند فشل التفعيل
        self.assertLess(block.index('context.user_data["state"] = "main_menu"'), block.index("deduct_jewels("))
        self.assertIn("add_jewels(user.id, jewels", block)

    def test_stars_invoice_payload_supports_both_kinds(self):
        pay = (BOT / "payments.py").read_text(encoding="utf-8")
        self.assertEqual(pay.count('("fund_mandatory:", "fund_internal:")'), 2)


def _install_stubs():
    """يحمّل funding_boost بلا telethon ولا قاعدة بيانات حقيقية."""
    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    class FloodWaitError(Exception):
        seconds = 5

    class _Client:
        def __init__(self, *a, **k): ...

    mod("telethon", TelegramClient=_Client)
    mod("telethon.errors", FloodWaitError=FloodWaitError)
    mod("telethon.sessions", StringSession=lambda s: s)
    mod("telethon.tl")
    mod("telethon.tl.functions")
    mod("telethon.tl.functions.channels", JoinChannelRequest=object)
    mod("telethon.tl.functions.messages", SendReactionRequest=object)
    mod("telethon.tl.types", ReactionEmoji=object)
    pkg = mod("fbpkg")
    pkg.__path__ = []
    mod("fbpkg.shared", TELEGRAM_API_ID="1", TELEGRAM_API_HASH="h")
    mod("fbpkg.database", db_conn=lambda: None)
    mod("fbpkg.raksh_system")
    mod("fbpkg.raksh_system.common", _get_raksh_session_lock=lambda a: asyncio.Lock())
    spec = importlib.util.spec_from_file_location(
        "fbpkg.funding_boost", BOT / "funding_boost.py", submodule_search_locations=None)
    m = importlib.util.module_from_spec(spec)
    m.__package__ = "fbpkg"
    sys.modules["fbpkg.funding_boost"] = m
    spec.loader.exec_module(m)
    return m, FloodWaitError


class BoostLogicTests(unittest.TestCase):
    def setUp(self):
        self.m, self.Flood = _install_stubs()
        self.m._fb_table_ready = True

    def _run(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def test_one_join_per_tick_and_reaction_every_ten(self):
        m = self.m
        joined, batches = [], []
        state = {"unreacted": 0}

        m._fb_pick_channels = lambda: [{"channel": "chan", "target": 100, "joined": 0}]
        m._fb_pick_account = lambda ch: {"id": len(joined) + 1, "session_string": "s"}

        async def fake_join(ch, acc):
            joined.append(acc["id"])
        m._fb_join_with_account = fake_join
        m._fb_record = lambda ch, sid, status, err="": state.__setitem__("unreacted", state["unreacted"] + 1)
        m._fb_count_unreacted = lambda ch: state["unreacted"]

        async def fake_batch(ch):
            batches.append(state["unreacted"])
            state["unreacted"] = 0
            m._fb_reacting.discard(ch)
        m._fb_react_batch = fake_batch

        async def go():
            for _ in range(25):
                await m.run_funding_boost_job()
                await asyncio.sleep(0)
        self._run(go())
        self.assertEqual(len(joined), 25)          # حساب واحد في كل دورة
        self.assertEqual(batches, [10, 10])        # دفعتا تفاعل بعد 10 و20

    def test_floodwait_pauses_and_account_error_is_recorded(self):
        m = self.m
        recorded = []
        m._fb_pick_channels = lambda: [{"channel": "c", "target": 5, "joined": 0}]
        m._fb_pick_account = lambda ch: {"id": 7, "session_string": "s"}
        m._fb_record = lambda ch, sid, status, err="": recorded.append((sid, status))

        async def boom(ch, acc):
            raise RuntimeError("USER_BANNED_IN_CHANNEL")
        m._fb_join_with_account = boom
        self._run(m.run_funding_boost_job())
        self.assertEqual(recorded, [(7, "failed")])       # الحساب لا يُعاد عليه

        async def flood(ch, acc):
            raise self.Flood()
        m._fb_join_with_account = flood
        self._run(m.run_funding_boost_job())
        self.assertGreater(m._fb_flood_until, 0)
        recorded.clear()
        self._run(m.run_funding_boost_job())               # متوقفة بسبب FloodWait
        self.assertEqual(recorded, [])
        m._fb_flood_until = 0.0

    def test_channel_level_error_does_not_burn_accounts(self):
        m = self.m
        recorded = []
        m._fb_channel_fails.clear()
        m._fb_pick_channels = lambda: [{"channel": "gone", "target": 5, "joined": 0}]
        m._fb_pick_account = lambda ch: {"id": 1, "session_string": "s"}
        m._fb_record = lambda *a, **k: recorded.append(a)

        async def nochan(ch, acc):
            raise ValueError("Cannot find any entity")
        m._fb_join_with_account = nochan
        for _ in range(4):
            self._run(m.run_funding_boost_job())
        self.assertEqual(recorded, [])                      # لا تُسجَّل إخفاقات حسابات
        self.assertGreaterEqual(m._fb_channel_fails["gone"][0], 3)

    def test_react_batch_without_message_is_fine(self):
        m = self.m
        marked = []
        accounts = [{"join_id": i, "id": i, "session_string": "s"} for i in range(1, 11)]
        m._fb_pending_reactors = lambda ch, n: accounts
        m._fb_mark_reacted = lambda ids: marked.extend(ids)

        async def none_found(acc, ch, mid):
            return None
        m._fb_react_with_account = none_found
        self._run(m._fb_react_batch("chan"))
        self.assertEqual(marked, list(range(1, 11)))        # الدفعة تُغلق دون خطأ

    def test_react_batch_all_ten_react_on_same_message(self):
        m = self.m
        marked, calls = [], []
        accounts = [{"join_id": i, "id": i, "session_string": "s"} for i in range(1, 11)]
        m._fb_pending_reactors = lambda ch, n: accounts
        m._fb_mark_reacted = lambda ids: marked.extend(ids)

        async def react(acc, ch, mid):
            calls.append(mid)
            return mid or 555
        m._fb_react_with_account = react

        async def nosleep(_):
            return None
        m.asyncio.sleep = nosleep
        try:
            self._run(m._fb_react_batch("chan"))
        finally:
            import asyncio as _a
            m.asyncio.sleep = _a.sleep
        self.assertEqual(calls, [None] + [555] * 9)
        self.assertEqual(len(marked), 10)

    def test_job_is_scheduled_every_15_seconds(self):
        app = (BOT / "application.py").read_text(encoding="utf-8")
        self.assertIn("run_repeating(run_funding_boost_job, interval=15", app)
        init = (BOT / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('"funding_boost"', init)


if __name__ == "__main__":
    unittest.main()
