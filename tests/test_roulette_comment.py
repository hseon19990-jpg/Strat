import asyncio
import importlib.util
import logging
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "bot_app" / "roulette_watch.py"


def _load_roulette_module():
    """يحمّل roulette_watch مع بدائل بسيطة لـ telethon وبقية الحزمة."""
    class _NS(types.SimpleNamespace):
        pass

    class _Req:
        def __init__(self, *a, **kw):
            self.__dict__.update(kw)

    functions = _NS(
        messages=_NS(GetDiscussionMessageRequest=_Req, StartBotRequest=_Req),
        channels=_NS(JoinChannelRequest=_Req),
    )
    telethon = types.ModuleType("telethon")
    telethon.TelegramClient = object
    telethon.functions = functions
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
    common._parse_bot_link = lambda url: (None, None)
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
        spec.loader.exec_module(module)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return module


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
        self.mod.asyncio.sleep = no_sleep
        ok, note = asyncio.run(
            self.mod._do_comment(_FakeClient(calls), "+1", {"url": "https://t.me/somechan/77"})
        )
        self.assertTrue(ok)
        self.assertEqual(
            calls,
            [("join_channel", "@somechan"), "discussion_lookup", "join_group", ("comment", "يستحق", 77)],
        )


if __name__ == "__main__":
    unittest.main()
