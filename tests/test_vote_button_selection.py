import ast
import re
import unittest
from pathlib import Path


SOURCE_PATH = (
    Path(__file__).parents[1]
    / "bot_app"
    / "raksh_system"
    / "common.py"
)


def _load_button_helpers():
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    selected = {
        "_button_label",
        "_message_buttons",
        "_select_post_action_button",
    }
    nodes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in selected
    }
    namespace = {"Any": object, "List": list, "re": re}
    namespace["_BUTTON_EMOJI_RE"] = re.compile(
        r"[\U0001F300-\U0001FAFF\U0001F1E0-\U0001F1FF\u2600-\u27BF]"
    )
    module = ast.Module(
        body=[ast.fix_missing_locations(nodes[name]) for name in selected],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(SOURCE_PATH), "exec"), namespace)
    return namespace


class FakeButton:
    def __init__(self, text="", url=None):
        self.text = text
        self.url = url


class FakeMessage:
    def __init__(self, rows):
        self.buttons = rows


class VoteButtonSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        helpers = _load_button_helpers()
        cls.select = staticmethod(helpers["_select_post_action_button"])

    def test_single_button_is_selected_regardless_of_label(self):
        button = FakeButton("الملف الشخصي")
        self.assertIs(self.select(FakeMessage([[button]])), button)

    def test_multiple_buttons_choose_the_first_emoji_button(self):
        plain = FakeButton("الملف الشخصي")
        emoji = FakeButton("🔥")
        other_emoji = FakeButton("⭐")
        self.assertIs(
            self.select(FakeMessage([[plain, emoji, other_emoji]])),
            emoji,
        )

    def test_multiple_buttons_without_emoji_are_not_guessed(self):
        self.assertIsNone(
            self.select(FakeMessage([[FakeButton("تصويت"), FakeButton("نسخ")]]))
        )

    def test_reply_markup_rows_are_supported_when_buttons_property_is_empty(self):
        button = FakeButton("زر واحد")

        class Markup:
            rows = [type("Row", (), {"buttons": [button]})()]

        message = type("Message", (), {"buttons": [], "reply_markup": Markup()})()
        self.assertIs(self.select(message), button)


if __name__ == "__main__":
    unittest.main()