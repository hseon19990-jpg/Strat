import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, row, fail=False):
        self.row, self.fail, self.calls = row, fail, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if self.fail:
            raise RuntimeError("db down")
        self.calls.append((sql, params))
        return _Result(self.row)


def _load(row, fail=False):
    conn = _Conn(row, fail)
    pkg = types.ModuleType("ownpkg")
    pkg.__path__ = []
    db = types.ModuleType("ownpkg.database")
    db.db_conn = lambda: conn
    sys.modules["ownpkg"] = pkg
    sys.modules["ownpkg.database"] = db
    spec = importlib.util.spec_from_file_location(
        "ownpkg.stock_ownership", ROOT / "bot_app" / "stock_ownership.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["ownpkg.stock_ownership"] = module
    spec.loader.exec_module(module)
    return module, conn


class BotOwnedAccountTests(unittest.TestCase):
    def test_live_session_is_rejected_and_phone_is_digits_only(self):
        mod, conn = _load({"?column?": 1})
        self.assertTrue(mod.bot_holds_live_session("+964 770 123 4567"))
        self.assertEqual(conn.calls[0][1], ("9647701234567",))

    def test_no_row_means_allowed(self):
        mod, _ = _load(None)
        self.assertFalse(mod.bot_holds_live_session("+9647701234567"))

    def test_empty_phone_and_db_error_do_not_block(self):
        mod, _ = _load({"x": 1})
        self.assertFalse(mod.bot_holds_live_session(""))
        mod, _ = _load(None, fail=True)
        self.assertFalse(mod.bot_holds_live_session("+9647701234567"))

    def test_query_requires_live_unsold_session(self):
        source = (ROOT / "bot_app/stock_ownership.py").read_text(encoding="utf-8")
        for fragment in (
            "deleted_at IS NULL",
            "BTRIM(session_string) <> ''",
            "last_authorized IS NOT FALSE",
            "ever_sold IS NOT TRUE",
        ):
            self.assertIn(fragment, source)

    def test_checks_run_before_code_is_sent(self):
        buyback = (ROOT / "bot_app/buyback.py").read_text(encoding="utf-8")
        check = buyback.index("bot_holds_live_session(phone)")
        send = buyback.index("client.send_code_request(phone, force_sms=True)")
        self.assertLess(check, send)

        messages = (ROOT / "bot_app/messages.py").read_text(encoding="utf-8")
        check = messages.index("bot_holds_live_session(phone)")
        send = messages.index("client.send_code_request(phone)", check)
        self.assertLess(check, send)
        self.assertIn("if _contributor_login:", messages[check - 300:check])


if __name__ == "__main__":
    unittest.main()
