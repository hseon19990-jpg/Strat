import base64, os, socket, struct, unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1].joinpath("bot_app", "shared.py").read_text(encoding="utf-8")
_NS = {"struct": struct, "base64": base64, "_socket": socket}
exec(_SRC[_SRC.index("_TG_DC = {"):_SRC.index("def _parse_hex_session_text")], _NS)
convert = _NS["_maybe_convert_session"]
DC = _NS["_TG_DC"]


def _telethon(dc, key):
    packed = struct.pack(">B4sH256s", dc, socket.inet_aton(DC[dc][0]), 443, key)
    return "1" + base64.urlsafe_b64encode(packed).decode()


class PyrogramStringSessionTest(unittest.TestCase):
    def setUp(self):
        self.key = os.urandom(256)

    def test_new_format(self):
        raw = base64.urlsafe_b64encode(struct.pack(">BI?256sQ?", 2, 1, False, self.key, 5, False)).decode().rstrip("=")
        self.assertEqual(convert(raw), _telethon(2, self.key))

    def test_old_format(self):
        raw = base64.urlsafe_b64encode(struct.pack(">B?256sI?", 4, False, self.key, 5, False)).decode().rstrip("=")
        self.assertEqual(convert(raw), _telethon(4, self.key))

    def test_telethon_string_unchanged(self):
        s = _telethon(2, self.key)
        self.assertEqual(convert(s), s)

    def test_test_mode_rejected(self):
        raw = base64.urlsafe_b64encode(struct.pack(">BI?256sQ?", 2, 1, True, self.key, 5, False)).decode().rstrip("=")
        self.assertEqual(convert(raw), raw)


if __name__ == "__main__":
    unittest.main()
