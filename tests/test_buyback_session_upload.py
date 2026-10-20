import ast
import base64
import json
import io
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
BUYBACK = ROOT / "bot_app" / "buyback.py"
APPLICATION = ROOT / "bot_app" / "application.py"


def _load_session_upload_helpers():
    tree = ast.parse(BUYBACK.read_text(encoding="utf-8"))
    nodes = [
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name in {
            "_extract_buyback_session_uploads",
            "_parse_buyback_session_upload",
        }
    ]
    namespace = {
        "_TG_DC": {2: ("149.154.167.51", 443)},
        "_maybe_convert_session": lambda value: value,
        "pyrogram_json_to_telethon": lambda payload: "pyrogram-session",
        "BUYBACK_SESSION_MAX_BYTES": 5 * 1024 * 1024,
        "BUYBACK_ZIP_MAX_FILES": 50,
        "BUYBACK_ZIP_MAX_UNCOMPRESSED_BYTES": 50 * 1024 * 1024,
    }
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(BUYBACK), "exec"),
        namespace,
    )
    return namespace


def _load_session_parser():
    return _load_session_upload_helpers()["_parse_buyback_session_upload"]


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

    def test_zip_accepts_exactly_one_session(self):
        parse = _load_session_parser()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("sessions/member.json", json.dumps("zip-session"))
        self.assertEqual(
            "zip-session",
            parse(archive.getvalue(), "seller.zip"),
        )

    def test_buyback_zip_rejects_multiple_sessions_instead_of_choosing_one(self):
        parse = _load_session_parser()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("first.json", json.dumps("first-session"))
            zipped.writestr("second.json", json.dumps("second-session"))
        self.assertIsNone(parse(archive.getvalue(), "seller.zip"))

    def test_zip_extractor_pairs_session_with_same_named_metadata_json(self):
        extract = _load_session_upload_helpers()["_extract_buyback_session_uploads"]
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("accounts/member.session", b"sqlite-session")
            zipped.writestr("accounts/member.json", json.dumps({"twofa_password": "metadata"}))
            zipped.writestr("accounts/other.json", json.dumps("other-session"))
        entries = extract(archive.getvalue(), "seller.zip")
        self.assertEqual(["member.session", "other.json"], [name for name, _raw in entries])

    def test_upload_route_is_registered_before_owner_import_handlers(self):
        buyback_source = BUYBACK.read_text(encoding="utf-8")
        app_source = APPLICATION.read_text(encoding="utf-8")
        message_source = (ROOT / "bot_app" / "messages.py").read_text(encoding="utf-8")
        self.assertIn('callback_data="buyback:begin_session"', buyback_source)
        self.assertIn('callback_data="buyback:session_consent"', buyback_source)
        self.assertIn('"buyback_await_session_document"', buyback_source)
        self.assertIn("~filters.User(OWNER_ID)", app_source)
        self.assertIn('filters.Document.FileExtension("zip")', app_source)
        self.assertIn('filters.Document.MimeType("application/zip")', app_source)
        self.assertIn('if state != "buyback_await_session_document":', buyback_source)
        self.assertIn('if state == "share_session_await_upload":', buyback_source)
        self.assertLess(app_source.index("handle_buyback_document"), app_source.index("handle_json_file"))


if __name__ == "__main__":
    unittest.main()
