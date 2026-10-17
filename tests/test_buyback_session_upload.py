import ast
import base64
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
BUYBACK = ROOT / "bot_app" / "buyback.py"
APPLICATION = ROOT / "bot_app" / "application.py"


def _load_session_parser():
    tree = ast.parse(BUYBACK.read_text(encoding="utf-8"))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "_parse_buyback_session_upload"
    )
    namespace = {
        "_TG_DC": {2: ("149.154.167.51", 443)},
        "_maybe_convert_session": lambda value: value,
        "pyrogram_json_to_telethon": lambda payload: "pyrogram-session",
    }
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), str(BUYBACK), "exec"),
        namespace,
    )
    return namespace["_parse_buyback_session_upload"]


class BuybackSessionUploadTests(unittest.TestCase):
    def test_json_accepts_one_string_session(self):
        parse = _load_session_parser()
        self.assertEqual(parse(json.dumps("telethon-session").encode(), "seller.json"), "telethon-session")
        self.assertEqual(
            parse(json.dumps({"session_string": "stored-session"}).encode(), "seller.json"),
            "stored-session",
        )

    def test_json_rejects_ambiguous_or_invalid_payloads(self):
        parse = _load_session_parser()
        self.assertIsNone(parse(json.dumps(["first", "second"]).encode(), "seller.json"))
        self.assertIsNone(parse(b"not json", "seller.json"))
        self.assertIsNone(parse(b"{}", "seller.txt"))

    def test_pyrogram_json_is_converted_without_importing_stock(self):
        parse = _load_session_parser()
        payload = json.dumps({"dc_id": 2, "auth_key": "fixture"}).encode()
        self.assertEqual(parse(payload, "seller.json"), "pyrogram-session")

    def test_telethon_sqlite_session_is_converted(self):
        parse = _load_session_parser()
        fd, path = tempfile.mkstemp(suffix=".session")
        os.close(fd)
        auth_key = bytes(range(256))
        try:
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TABLE sessions (dc_id INTEGER, server_address TEXT, port INTEGER, auth_key BLOB)"
                )
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?)",
                    (2, "149.154.167.51", 443, auth_key),
                )
            connection.close()
            converted = parse(Path(path).read_bytes(), "seller.session")
        finally:
            os.unlink(path)
        self.assertTrue(converted.startswith("1"))
        unpacked = base64.urlsafe_b64decode(converted[1:].encode("ascii"))
        self.assertEqual(unpacked[0], 2)
        self.assertEqual(unpacked[7:], auth_key)

    def test_pyrogram_sqlite_session_is_converted(self):
        parse = _load_session_parser()
        fd, path = tempfile.mkstemp(suffix=".session")
        os.close(fd)
        auth_key = bytes(reversed(range(256)))
        try:
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE sessions (dc_id INTEGER, auth_key BLOB)")
                connection.execute("INSERT INTO sessions VALUES (?, ?)", (2, auth_key))
            connection.close()
            converted = parse(Path(path).read_bytes(), "seller.session")
        finally:
            os.unlink(path)
        unpacked = base64.urlsafe_b64decode(converted[1:].encode("ascii"))
        self.assertEqual(unpacked[7:], auth_key)

    def test_upload_route_is_registered_before_owner_import_handlers(self):
        buyback_source = BUYBACK.read_text(encoding="utf-8")
        app_source = APPLICATION.read_text(encoding="utf-8")
        message_source = (ROOT / "bot_app" / "messages.py").read_text(encoding="utf-8")
        self.assertIn('callback_data="buyback:begin_session"', buyback_source)
        self.assertIn('callback_data="buyback:session_consent"', buyback_source)
        self.assertIn('"buyback_await_session_document"', buyback_source)
        self.assertIn("~filters.User(OWNER_ID)", app_source)
        self.assertIn("update.message.document and state.startswith(\"buyback_\")", message_source)
        self.assertLess(app_source.index("handle_buyback_document"), app_source.index("handle_json_file"))


if __name__ == "__main__":
    unittest.main()
