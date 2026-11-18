import ast
import asyncio
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]


def _exec_nodes(path, names, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    picked = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            picked.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id in names for t in targets):
                picked.append(node)
    exec(compile(ast.Module(body=picked, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class _Rows(list):
    def fetchall(self):
        return list(self)


class _Conn:
    def __init__(self, channels):
        self.channels = channels

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        return _Rows(self.channels)


class _Bot:
    def __init__(self, status="member"):
        self.calls = 0
        self.status = status

    async def get_chat_member(self, chat, user_id):
        self.calls += 1
        return SimpleNamespace(status=self.status)


def _gate_namespace(channels_box, bot_box):
    async def ensure_bot_invite_links(context, pending, limit=0):
        return pending

    return _exec_nodes(
        ROOT / "bot_app/onboarding.py",
        {
            "_JOINED_ALL_CACHE", "_JOINED_ALL_TTL_SECONDS", "_JOINED_ALL_CACHE_MAX",
            "_joined_all_cache_get", "_joined_all_cache_set",
            "get_unjoined_mandatory_channels",
        },
        {
            "OWNER_ID": 1,
            "asyncio": asyncio,
            "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
            "db_conn": lambda: _Conn(channels_box["rows"]),
            "logger": SimpleNamespace(warning=lambda *a, **k: None),
            "MANDATORY_PAGE_SIZE": 5,
            "ensure_bot_invite_links": ensure_bot_invite_links,
        },
    )


def _ctx(bot):
    return SimpleNamespace(bot=bot, bot_data={})


class GateCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_skips_telegram_on_second_click(self):
        rows = {"rows": [{"id": 1, "channel_username": "a"}, {"id": 2, "channel_username": "b"}]}
        bot = _Bot()
        ns = _gate_namespace(rows, bot)
        fn = ns["get_unjoined_mandatory_channels"]
        self.assertEqual(await fn(_ctx(bot), 5, use_cache=True), [])
        self.assertEqual(bot.calls, 2)
        self.assertEqual(await fn(_ctx(bot), 5, use_cache=True), [])
        self.assertEqual(bot.calls, 2)  # served from cache

    async def test_default_call_always_checks_telegram(self):
        rows = {"rows": [{"id": 1, "channel_username": "a"}]}
        bot = _Bot()
        fn = _gate_namespace(rows, bot)["get_unjoined_mandatory_channels"]
        await fn(_ctx(bot), 5)
        await fn(_ctx(bot), 5)
        self.assertEqual(bot.calls, 2)

    async def test_changing_channels_invalidates_cache(self):
        rows = {"rows": [{"id": 1, "channel_username": "a"}]}
        bot = _Bot()
        fn = _gate_namespace(rows, bot)["get_unjoined_mandatory_channels"]
        await fn(_ctx(bot), 5, use_cache=True)
        rows["rows"] = [{"id": 1, "channel_username": "a"}, {"id": 3, "channel_username": "c"}]
        await fn(_ctx(bot), 5, use_cache=True)
        self.assertEqual(bot.calls, 3)

    async def test_unjoined_result_is_never_cached(self):
        rows = {"rows": [{"id": 1, "channel_username": "a"}]}
        bot = _Bot(status="left")
        fn = _gate_namespace(rows, bot)["get_unjoined_mandatory_channels"]
        self.assertEqual(len(await fn(_ctx(bot), 5, use_cache=True)), 1)
        self.assertEqual(len(await fn(_ctx(bot), 5, use_cache=True)), 1)
        self.assertEqual(bot.calls, 2)

    async def test_expired_entry_is_rechecked(self):
        rows = {"rows": [{"id": 1, "channel_username": "a"}]}
        bot = _Bot()
        ns = _gate_namespace(rows, bot)
        fn = ns["get_unjoined_mandatory_channels"]
        await fn(_ctx(bot), 5, use_cache=True)
        ns["_JOINED_ALL_TTL_SECONDS"] = -1
        await fn(_ctx(bot), 5, use_cache=True)
        self.assertEqual(bot.calls, 2)

    async def test_owner_is_never_gated(self):
        rows = {"rows": [{"id": 1, "channel_username": "a"}]}
        bot = _Bot(status="left")
        fn = _gate_namespace(rows, bot)["get_unjoined_mandatory_channels"]
        self.assertEqual(await fn(_ctx(bot), 1, use_cache=True), [])
        self.assertEqual(bot.calls, 0)


class CallbackHelpersTests(unittest.IsolatedAsyncioTestCase):
    def _ns(self):
        return _exec_nodes(
            ROOT / "bot_app/callbacks.py",
            {"_ROLE_CACHE", "_ROLE_CACHE_TTL_SECONDS", "_BACKGROUND_ANSWERS",
             "_cached_role", "_spawn_callback_answer"},
            {"asyncio": asyncio},
        )

    async def test_answer_does_not_block_the_handler(self):
        ns = self._ns()
        done = []

        class Q:
            async def answer(self):
                await asyncio.sleep(0.2)
                done.append(1)

        start = time.perf_counter()
        ns["_spawn_callback_answer"](Q())
        self.assertLess(time.perf_counter() - start, 0.05)
        await asyncio.sleep(0.3)
        self.assertEqual(done, [1])

    async def test_answer_errors_are_swallowed(self):
        ns = self._ns()

        class Q:
            async def answer(self):
                raise RuntimeError("query too old")

        ns["_spawn_callback_answer"](Q())
        await asyncio.sleep(0.05)
        self.assertEqual(len(ns["_BACKGROUND_ANSWERS"]), 0)

    def test_role_cache_hits_then_expires(self):
        ns = self._ns()
        calls = []

        def loader(user_id):
            calls.append(user_id)
            return True

        self.assertTrue(ns["_cached_role"]("sv", 9, loader))
        self.assertTrue(ns["_cached_role"]("sv", 9, loader))
        self.assertEqual(calls, [9])
        ns["_ROLE_CACHE_TTL_SECONDS"] = -1
        ns["_cached_role"]("sv", 9, loader)
        self.assertEqual(calls, [9, 9])
        ns["_cached_role"]("na", 9, loader)  # different role kind -> separate entry
        self.assertEqual(calls, [9, 9, 9])

    def test_handler_uses_cache_and_background_answer(self):
        source = (ROOT / "bot_app/callbacks.py").read_text(encoding="utf-8")
        self.assertIn("get_unjoined_mandatory_channels(context, user.id, use_cache=True)", source)
        self.assertIn("_spawn_callback_answer(q)", source)
        self.assertIn('_cached_role("sv", user.id, is_supervisor)', source)


if __name__ == "__main__":
    unittest.main()
