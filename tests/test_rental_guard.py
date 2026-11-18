import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load_guard(rows):
    """يحمّل rental_guard مع Telethon وقاعدة بيانات وهمية."""
    class Kick:  # ResetAuthorizationsRequest
        pass

    class KickOne:  # ResetAuthorizationRequest
        pass

    class Other:
        pass

    class Key:
        def __init__(self, key):
            self.key = key

    class StringSession:
        def __init__(self, s=""):
            self.auth_key = Key(s.encode()) if s else None

    calls = []

    class TelegramClient:
        def __init__(self, s):
            self.session = StringSession(s)

        def __call__(self, request, *a, **k):
            async def go():
                calls.append(request)
                return "done"
            return go()

    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    mod("telethon", TelegramClient=TelegramClient)
    mod("telethon.sessions", StringSession=StringSession)
    mod("telethon.tl")
    mod("telethon.tl.functions")
    mod("telethon.tl.functions.auth", ResetAuthorizationsRequest=Kick)
    mod("telethon.tl.functions.account", ResetAuthorizationRequest=KickOne)

    class Db:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, q, p=()):
            class R:
                def fetchall(_):
                    return [{"session_string": r} for r in rows]
            return R()

    pkg = types.ModuleType("bot_app")
    pkg.__path__ = []
    sys.modules["bot_app"] = pkg
    mod("bot_app.database", db_conn=lambda: Db())
    spec = importlib.util.spec_from_file_location(
        "bot_app.rental_guard", ROOT / "bot_app/rental_guard.py"
    )
    guard = importlib.util.module_from_spec(spec)
    sys.modules["bot_app.rental_guard"] = guard
    spec.loader.exec_module(guard)
    guard.install()
    return guard, TelegramClient, Kick, KickOne, Other, calls


class RentalGuardTests(unittest.TestCase):
    def test_kick_blocked_for_rented_but_allowed_for_others(self):
        guard, Client, Kick, KickOne, Other, calls = _load_guard(["RENTED"])
        run = asyncio.run
        for kick in (Kick, KickOne):
            with self.assertRaises(guard.RentedAccountProtected):
                run(Client("RENTED")(kick()))
        self.assertEqual(calls, [])
        # حساب غير مؤجَّر يُطرد كالمعتاد
        self.assertEqual(run(Client("OTHER")(Kick())), "done")
        # طلبات غير الطرد تمر على حساب مؤجَّر
        self.assertEqual(run(Client("RENTED")(Other())), "done")

    def test_only_owner_manual_context_may_kick_rented(self):
        guard, Client, Kick, KickOne, Other, calls = _load_guard(["RENTED"])
        with guard.owner_manual_kick():
            self.assertEqual(asyncio.run(Client("RENTED")(KickOne())), "done")
        # خارج السياق يعود المنع
        with self.assertRaises(guard.RentedAccountProtected):
            asyncio.run(Client("RENTED")(KickOne()))

    def test_db_failure_blocks_kick(self):
        guard, Client, Kick, KickOne, Other, calls = _load_guard([])
        guard._cache["at"] = 0.0
        guard._rented_auth_keys = lambda: (_ for _ in ()).throw(RuntimeError("db"))
        with self.assertRaises(guard.RentedAccountProtected):
            asyncio.run(Client("X")(Kick()))


class OwnerGuardSourceTests(unittest.TestCase):
    def test_owner_kick_device_refuses_rented(self):
        src = (ROOT / "bot_app/callback_groups_03.py").read_text(encoding="utf-8")
        i = src.index('data.startswith("os:kick_device:")')
        self.assertIn("contributed_by IS NOT NULL", src[i:i + 2500])
        self.assertIn("OWNER_ID", src[i:i + 2500])

    def test_member_tools_have_no_kick(self):
        src = (ROOT / "bot_app/contributor_tools.py").read_text(encoding="utf-8")
        self.assertNotIn("ResetAuthorization", src.split('"""', 2)[2])


if __name__ == "__main__":
    unittest.main()
