import asyncio
import importlib.util
import logging
import re
import sys
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "bot_app" / "roulette_watch.py"


def _load_modules():
    """يحمّل roulette_watch و roulette_fast مع بدائل بسيطة لـ telethon وبقية الحزمة."""
    class _NS(types.SimpleNamespace):
        pass

    class _Req:
        def __init__(self, *a, **kw):
            self.__dict__.update(kw)

    functions = _NS(
        messages=_NS(GetDiscussionMessageRequest=_Req, StartBotRequest=_Req, GetBotCallbackAnswerRequest=_Req),
        channels=_NS(JoinChannelRequest=_Req),
    )
    telethon = types.ModuleType("telethon")
    telethon.TelegramClient = object
    telethon.functions = functions

    class _Ev:
        def __init__(self, chats=None):
            self.chats = chats

    telethon.events = _NS(NewMessage=_Ev, MessageEdited=_Ev)
    sessions = types.ModuleType("telethon.sessions")
    sessions.StringSession = object
    tl = types.ModuleType("telethon.tl")
    tl_types = types.ModuleType("telethon.tl.types")
    tl_types.PeerChannel = lambda x: x

    pkg = types.ModuleType("bot_app")
    pkg.__path__ = [str(ROOT / "bot_app")]
    shared = types.ModuleType("bot_app.shared")
    shared.OWNER_ID = 1
    shared.logger = logging.getLogger("test")
    shared.TELEGRAM_API_ID = 1
    shared.TELEGRAM_API_HASH = "x"
    users = types.ModuleType("bot_app.users")
    users.get_setting = lambda key: None
    users.set_setting = lambda key, value: None
    rs = types.ModuleType("bot_app.raksh_system")
    rs.__path__ = []
    common = types.ModuleType("bot_app.raksh_system.common")

    def _parse_post_link(value):
        parts = [p for p in value.replace("https://", "").split("?")[0].split("/") if p]
        if len(parts) == 3 and parts[0] == "t.me" and parts[2].isdigit():
            return f"@{parts[1]}", int(parts[2])
        return None, None

    common._parse_post_link = _parse_post_link
    def _parse_bot_link(url):
        m = re.match(r"https?://t\.me/([A-Za-z0-9_]+)\?start=(.+)", url or "")
        return (m.group(1), m.group(2)) if m else (None, None)

    common._parse_bot_link = _parse_bot_link
    common._parse_channel_refs = lambda text: []
    common._get_raksh_session_lock = lambda s: asyncio.Lock()
    common._get_sessions_for_service = lambda *a, **k: []

    async def _join(*a, **k):
        return True

    common._join_channel_and_schedule_leave = _join

    stubs = {
        "telethon": telethon, "telethon.sessions": sessions, "telethon.tl": tl,
        "telethon.tl.types": tl_types, "bot_app": pkg, "bot_app.shared": shared,
        "bot_app.users": users, "bot_app.raksh_system": rs,
        "bot_app.raksh_system.common": common,
    }
    saved = {k: sys.modules.get(k) for k in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location("bot_app.roulette_watch", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules["bot_app.roulette_watch"] = module
        pkg.roulette_watch = module
        spec.loader.exec_module(module)
        fast_spec = importlib.util.spec_from_file_location(
            "bot_app.roulette_fast", ROOT / "bot_app" / "roulette_fast.py"
        )
        fast = importlib.util.module_from_spec(fast_spec)
        sys.modules["bot_app.roulette_fast"] = fast
        fast_spec.loader.exec_module(fast)
    finally:
        for k in list(stubs) + ["bot_app.roulette_watch", "bot_app.roulette_fast"]:
            v = saved.get(k)
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return module, fast


def _load_roulette_module():
    return _load_modules()[0]


def _utf16_len(s):
    return len(s.encode("utf-16-le")) // 2


class _Ent:
    def __init__(self, offset, url):
        self.offset = offset
        self.url = url


class _Msg:
    def __init__(self, text, links):
        self.message = text
        self._pairs = []
        for label, url in links:
            idx = text.index(label)
            self._pairs.append((_Ent(_utf16_len(text[:idx]), url), label))

    def get_entities_text(self):
        return self._pairs


class _FakeClient:
    def __init__(self, calls):
        self.calls = calls

    async def __call__(self, request):
        if request.__class__.__name__ == "_Req" and hasattr(request, "msg_id"):
            self.calls.append("discussion_lookup")
            group = types.SimpleNamespace(id=222, username=None)
            channel = types.SimpleNamespace(id=111)
            return types.SimpleNamespace(chats=[channel, group])
        self.calls.append("join_group")

    async def send_message(self, entity, text, comment_to=None):
        self.calls.append(("comment", text, comment_to))


class RouletteCommentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_roulette_module()

    def test_comment_line_is_detected(self):
        text = "ا\n\n• الشرط ⇊\n❶الـتـعـليق >> هــنــا\n\nروليت سراب > جميع السحوبات"
        msg = _Msg(text, [("هــنــا", "https://t.me/somechan/77"), ("جميع السحوبات", "https://t.me/allgiveaways")])
        conds = self.mod._extract_conditions(msg)
        self.assertEqual(len(conds), 1)
        self.assertEqual(conds[0]["kind"], "comment")
        self.assertEqual(conds[0]["url"], "https://t.me/somechan/77")

    def test_vote_line_still_vote_post(self):
        text = "الشرط\nالتصويت >> هنا"
        msg = _Msg(text, [("هنا", "https://t.me/somechan/5")])
        self.assertEqual(self.mod._extract_conditions(msg)[0]["kind"], "vote_post")

    def test_do_comment_order_and_text(self):
        calls = []

        async def fake_join(client, ref, phone=None, **kw):
            calls.append(("join_channel", ref))
            return True

        async def fake_entity(client, ref):
            return types.SimpleNamespace(id=111)

        async def no_sleep(*a, **k):
            return None

        self.mod._join_channel_and_schedule_leave = fake_join
        self.mod._entity_for = fake_entity
        with mock.patch.object(self.mod.asyncio, "sleep", no_sleep):
            ok, note = asyncio.run(
                self.mod._do_comment(_FakeClient(calls), "+1", {"url": "https://t.me/somechan/77"})
            )
        self.assertTrue(ok)
        self.assertEqual(
            calls,
            [("join_channel", "@somechan"), "discussion_lookup", "join_group", ("comment", "يستحق", 77)],
        )


class RouletteSessionTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load_roulette_module()
        self.store = {}
        self.mod.get_setting = lambda k: self.store.get(k)
        self.mod.set_setting = lambda k, v: self.store.__setitem__(k, v)
        self.sessions = [
            {"id": 1, "phone_number": "+100", "session_string": "aaa", "contributed_by": None},
            {"id": 2, "phone_number": "+200", "session_string": "bbb", "contributed_by": None},
        ]
        self.mod._get_sessions_for_service = lambda *a, **k: list(self.sessions)

    def test_excluded_after_three_failures_and_back_with_new_session(self):
        bad = self.sessions[0]
        self.assertFalse(self.mod._record_session_failure(bad))
        self.assertFalse(self.mod._record_session_failure(bad))
        self.assertEqual(len(self.mod._owner_sessions()), 2)
        self.assertTrue(self.mod._record_session_failure(bad))
        self.assertEqual([s["phone_number"] for s in self.mod._owner_sessions()], ["+200"])
        self.assertEqual(self.mod._excluded_count(), 1)
        # إضافة الحساب من جديد بجلسة جديدة تعيده تلقائياً
        bad["session_string"] = "new-session"
        self.assertEqual(len(self.mod._owner_sessions()), 2)

    def test_success_resets_counter(self):
        bad = self.sessions[0]
        self.mod._record_session_failure(bad)
        self.mod._record_session_failure(bad)
        self.mod._record_session_ok(bad)
        self.assertFalse(self.mod._record_session_failure(bad))
        self.assertEqual(len(self.mod._owner_sessions()), 2)

    def test_lost_session_error_detection(self):
        class AuthKeyUnregisteredError(Exception):
            pass

        self.assertTrue(self.mod._is_lost_session_error(AuthKeyUnregisteredError("x")))
        self.assertTrue(self.mod._is_lost_session_error(Exception("USER_DEACTIVATED_BAN")))
        self.assertFalse(self.mod._is_lost_session_error(Exception("flood wait")))

    def test_ten_second_gap_between_accounts(self):
        sleeps = []

        async def fake_sleep(sec, *a, **k):
            sleeps.append(sec)

        async def fake_participate(session, trig, sem, runtime_bot=None):
            return True, "ok"

        class _Bot:
            async def send_message(self, *a, **k):
                return None

        self.mod._participate = fake_participate
        sessions = [{"phone_number": f"+{i}"} for i in range(4)]
        with mock.patch.object(self.mod.asyncio, "sleep", fake_sleep):
            asyncio.run(self.mod._run_roulette(_Bot(), {"ref": "@c", "bot": "b"}, sessions))
        self.assertEqual(sorted(sleeps), [10, 20, 30])


# ───────────────────────── الروليت السريع ─────────────────────────

class _Btn:
    def __init__(self, text, data=None, url=None):
        self.text, self.data, self.url = text, data, url


class _FastMsg:
    def __init__(self, msg_id, rows, channel_id=777, age=0, text=""):
        self.id = msg_id
        self.peer_id = types.SimpleNamespace(channel_id=channel_id)
        self.reply_markup = types.SimpleNamespace(rows=[types.SimpleNamespace(buttons=list(r)) for r in rows])
        self.buttons = [list(r) for r in rows]
        self.date = datetime.now(timezone.utc) - timedelta(seconds=age)
        self.message = text

    def get_entities_text(self):
        return []


class _PoolClient:
    def __init__(self, log, name, delay=0.2, answers=None):
        self.log, self.name, self.delay = log, name, delay
        self.answers = list(answers or [""])
        self.disconnected = 0
        self.handlers = []

    def is_connected(self):
        return True

    async def is_user_authorized(self):
        return False

    async def disconnect(self):
        self.disconnected += 1

    def add_event_handler(self, cb, ev):
        self.handlers.append(ev)

    def remove_event_handler(self, cb, ev=None):
        self.handlers.clear()

    async def __call__(self, request):
        self.log.append((self.name, request.msg_id, request.data, time.monotonic()))
        await asyncio.sleep(self.delay)
        text = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return types.SimpleNamespace(message=text)


def _entry(client, n):
    return {
        "client": client, "session": {"phone_number": f"+{n}", "session_string": f"s{n}"},
        "lock": asyncio.Lock(), "peers": {777: "peer"}, "entities": {777: object()},
        "refs": {"@c"}, "listening_on": None,
    }


JOIN_ROWS_1 = [[_Btn("انضم ✅", b"join"), _Btn("انسحب 🚪", b"leave")], [_Btn("للمسؤول: اسحب فائز 👑", b"admin")]]
JOIN_ROWS_2 = [[_Btn("⊕ الإنضمام إلى السحب", b"j2")], [_Btn("⛶ اختيار الفائز", b"w")]]


class RouletteFastTests(unittest.TestCase):
    def setUp(self):
        self.rw, self.rf = _load_modules()
        self.store = {}
        self.rw.get_setting = lambda k: self.store.get(k)
        self.rw.set_setting = lambda k, v: self.store.__setitem__(k, v)
        self.rf._seen.clear()
        self.rw._POOL.clear()
        self.rw._FAST_BOT = None
        self.rw._FAST_LISTENING = False

    def test_join_button_detection_never_picks_admin_buttons(self):
        self.assertEqual(self.rf._find_join_button(_FastMsg(1, JOIN_ROWS_1)), ("انضم ✅", b"join"))
        self.assertEqual(self.rf._find_join_button(_FastMsg(1, JOIN_ROWS_2)), ("⊕ الإنضمام إلى السحب", b"j2"))
        admin_only = [[_Btn("انسحب 🚪", b"leave")], [_Btn("للمسؤول: اسحب فائز 👑", b"admin")]]
        self.assertIsNone(self.rf._find_join_button(_FastMsg(1, admin_only)))

    def test_all_accounts_click_in_parallel(self):
        log = []
        for n in range(25):
            self.rw._POOL[f"k{n}"] = _entry(_PoolClient(log, n, delay=0.2), n)
        msg = _FastMsg(500, JOIN_ROWS_1)
        t = time.monotonic()
        asyncio.run(self.rf.fire_fast(msg, 777, "انضم ✅", b"join", t))
        elapsed = time.monotonic() - t
        self.assertEqual(len(log), 25)
        self.assertTrue(all(call[1] == 500 and call[2] == b"join" for call in log))
        starts = [call[3] for call in log]
        self.assertLess(max(starts) - min(starts), 0.1)   # كلها بدأت معاً
        self.assertLess(elapsed, 1.0)                    # تسلسلياً كانت ستحتاج 5 ثوانٍ

    def test_handle_message_dedup_age_and_edit_without_button(self):
        fired = []

        async def fake_fire(message, channel_id, label, data, received):
            fired.append(message.id)

        self.rf.fire_fast = fake_fire
        msg = _FastMsg(10, JOIN_ROWS_1)
        asyncio.run(self.rf.handle_message(msg))
        asyncio.run(self.rf.handle_message(msg))                      # الحساب المراقب الثاني
        asyncio.run(self.rf.handle_message(_FastMsg(11, [[_Btn("تحديث", b"x")]])))  # تعديل بلا زر انضمام
        asyncio.run(self.rf.handle_message(_FastMsg(12, JOIN_ROWS_1, age=600)))      # منشور قديم
        self.assertEqual(fired, [10])
        self.assertNotIn((777, 11), self.rf._seen)
        # نفس المنشور يُعدَّل لاحقاً فيظهر الزر: يُنفَّذ مرة واحدة
        asyncio.run(self.rf.handle_message(_FastMsg(11, JOIN_ROWS_2)))
        self.assertEqual(fired, [10, 11])

    def test_slow_post_uses_old_flow_not_fast_click(self):
        fired, started = [], []

        async def fake_fire(*a, **k):
            fired.append(1)

        async def fake_run(bot, trig, sessions):
            started.append(trig)

        self.rf.fire_fast = fake_fire
        self.rw._run_roulette = fake_run
        self.rw._owner_sessions = lambda: []
        self.rw._FAST_BOT = object()
        self.rf._REF_BY_ID[777] = "@chan"
        slow = _FastMsg(20, [[_Btn("مشاركة السحب", url="https://t.me/mybot?start=abc")], [_Btn("المشاركة في السحب [1]", b"cb")]])

        async def go():
            await self.rf.handle_message(slow)
            await asyncio.sleep(0)

        asyncio.run(go())
        self.assertEqual(fired, [])
        self.assertEqual(len(started), 1)
        self.assertEqual((started[0]["bot"], started[0]["ref"], started[0]["msg_id"]), ("mybot", "@chan", 20))
        self.assertIn(("@chan", 20), self.rw._handled)

    def test_need_join_answer_joins_then_clicks_again_once(self):
        log, joined = [], []
        for n in range(3):
            self.rw._POOL[f"k{n}"] = _entry(_PoolClient(log, n, delay=0.01, answers=["يجب الاشتراك في القناة أولاً", "تم"]), n)

        async def fake_handle_url(client, url, label, phone):
            joined.append((url, phone))
            return True, "ok"

        self.rw._handle_url = fake_handle_url
        msg = _FastMsg(30, [[_Btn("انضم ✅", b"join"), _Btn("القناة", url="https://t.me/sponsorchan")]])
        asyncio.run(self.rf.fire_fast(msg, 777, "انضم ✅", b"join", time.monotonic()))
        self.assertEqual(len(log), 6)                                   # ضغطتان لكل حساب
        self.assertEqual(sorted(j[1] for j in joined), ["+0", "+1", "+2"])
        self.assertTrue(all(j[0] == "https://t.me/sponsorchan" for j in joined))

    def test_participate_reuses_pooled_client_without_lock_or_disconnect(self):
        client = _PoolClient([], 0)
        session = {"phone_number": "+9", "session_string": "sess-9"}
        self.rw._POOL[self.rw._session_fp(session)] = _entry(client, 9)
        self.rw._POOL[self.rw._session_fp(session)]["client"] = client

        def no_lock(_):
            raise AssertionError("القفل محجوز للمجمّع ولا يجوز طلبه")

        self.rw._get_raksh_session_lock = no_lock
        ok, note = asyncio.run(self.rw._participate(session, {"ref": "@c", "bot": "b", "param": "p"}, asyncio.Semaphore(1)))
        self.assertEqual((ok, note), (False, "الجلسة غير مصرح بها"))
        self.assertEqual(client.disconnected, 0)

    def test_listeners_limited_and_poll_pauses(self):
        log = []
        for n in range(4):
            self.rw._POOL[f"k{n}"] = _entry(_PoolClient(log, n), n)
        self.rf.sync_listeners()
        attached = [e for e in self.rw._POOL.values() if e["listening_on"] is not None]
        self.assertEqual(len(attached), self.rf.LISTENERS)
        self.assertTrue(all(len(e["client"].handlers) == 2 for e in attached))  # جديد + تعديل
        self.assertTrue(self.rw._FAST_LISTENING)
        # قناة أُضيفت: يُعاد الربط بالقائمة الجديدة
        attached[0]["entities"][888] = object()
        self.rf.sync_listeners()
        self.assertEqual(attached[0]["listening_on"], (777, 888))

    def test_removed_channel_is_pruned(self):
        entry = _entry(_PoolClient([], 0), 0)
        self.rf._REF_BY_ID[777] = "@c"
        self.rf._prune_removed(entry, ["@other"])
        self.assertEqual(entry["entities"], {})
        self.assertNotIn("@c", entry["refs"])


if __name__ == "__main__":
    unittest.main()
