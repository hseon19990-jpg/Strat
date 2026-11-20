import asyncio
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

# يتيح اختبار الوحدة دون تثبيت telethon.
_fn_account = types.ModuleType("telethon.tl.functions.account")
_fn_account.GetAuthorizationsRequest = lambda: "req"
_fn_auth = types.ModuleType("telethon.tl.functions.auth")
_fn_auth.ResetAuthorizationsRequest = lambda: "reset"
for name in ("telethon", "telethon.tl", "telethon.tl.functions"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["telethon.tl.functions.account"] = _fn_account
sys.modules["telethon.tl.functions.auth"] = _fn_auth

import importlib.util

spec = importlib.util.spec_from_file_location(
    "oes", ROOT / "bot_app" / "owner_extra_sessions.py"
)
oes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oes)


def auth(current=False, device="Phone"):
    return SimpleNamespace(current=current, device_model=device, app_name="Telegram", country="IQ")


class FakeClient:
    def __init__(self, auths):
        self.auths = auths

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def __call__(self, _req):
        return SimpleNamespace(authorizations=self.auths)


class ExtraSessionsTest(unittest.TestCase):
    def test_bot_session_not_counted(self):
        self.assertEqual(oes.count_extra_sessions([auth(True), auth(), auth()]), 2)

    def test_scan_filters_by_extra_sessions(self):
        data = {
            "s1": [auth(True)],                       # 0 إضافية
            "s2": [auth(True), auth()],               # 1 إضافية
            "s3": [auth(True), auth(), auth()],       # 2 إضافية ← يظهر
            "s4": [auth(True), auth(), auth(), auth()],  # 3 إضافية ← يظهر
        }
        accounts = [{"id": i, "phone_number": f"+{i}", "session_string": k}
                    for i, k in enumerate(data, 1)]
        with mock.patch.object(oes, "_save_device_count") as saved:
            report = asyncio.run(
                oes.scan_owner_extra_sessions(lambda s: FakeClient(data[s]), accounts)
            )
        self.assertEqual([m["extra"] for m in report["matches"]], [3, 2])
        self.assertEqual(saved.call_count, 4)
        self.assertIn("+4", oes.format_report(report)[0])


if __name__ == "__main__":
    unittest.main()


class KickExtraSessionsTest(unittest.TestCase):
    def test_kick_only_resets_does_not_create_session(self):
        calls = []

        class KickClient(FakeClient):
            async def __call__(self, req):
                calls.append(req)
                return SimpleNamespace()

        accounts = [{"id": 1, "phone_number": "+1", "session_string": "s1"},
                    {"id": 2, "phone_number": "+2", "session_string": "s2"}]
        with mock.patch.object(oes, "_save_device_count") as saved:
            result = asyncio.run(
                oes.kick_extra_sessions(lambda s: KickClient([]), accounts)
            )
        self.assertEqual(sorted(result["succeeded"]), ["+1", "+2"])
        self.assertEqual(result["failed"], [])
        # لم يُستدعَ غير ResetAuthorizationsRequest لكل حساب — لا توليد جلسات.
        self.assertEqual(len(calls), 2)
        self.assertEqual(saved.call_count, 2)
