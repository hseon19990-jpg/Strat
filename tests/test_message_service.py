import ast
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).parents[1]
MESSAGE = ROOT / "bot_app" / "raksh_system" / "message.py"


def _load_message_helpers():
    tree = ast.parse(MESSAGE.read_text(encoding="utf-8"))
    wanted = {"normalize_message_recipient", "message_identity_label", "build_raksh_message"}
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace = {
        "re": re,
        "urlparse": urlparse,
        "MESSAGE_BOT_SIGNATURE": (
            "يتم ارسال هذه الرسالة من بوت ارشقلي :@arshaqlibot\n"
            "بوت رشق متابعين لجميع التطبيقات"
        ),
    }
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(MESSAGE), "exec"),
        namespace,
    )
    return namespace


class MessageServiceTests(unittest.TestCase):
    def test_recipient_accepts_username_forms_and_rejects_phone(self):
        helpers = _load_message_helpers()
        normalize_message_recipient = helpers["normalize_message_recipient"]
        self.assertEqual(normalize_message_recipient("@example_user"), "@example_user")
        self.assertEqual(
            normalize_message_recipient("https://t.me/example_user"),
            "@example_user",
        )
        self.assertIsNone(normalize_message_recipient("+9647700000000"))

    def test_message_body_contains_requested_identity_and_signature(self):
        helpers = _load_message_helpers()
        build_raksh_message = helpers["build_raksh_message"]
        anonymous = build_raksh_message(
            "محمد", "النص التجريبي", "anonymous"
        )
        self.assertIn("مرحبا عزيزي: محمد", anonymous)
        self.assertIn("لديك رسالة من شخص مجهول", anonymous)
        self.assertIn("@arshaqlibot", anonymous)
        self.assertIn("الرسالة :", anonymous)

        fake = build_raksh_message(
            "محمد", "النص التجريبي", "fake", "صديق مجهول"
        )
        self.assertIn("لديك رسالة من صديقك: صديق مجهول", fake)


if __name__ == "__main__":
    unittest.main()