import ast
import re
import unicodedata
import unittest
from pathlib import Path


SOURCE_PATH = (
    Path(__file__).parents[1]
    / "bot_app"
    / "raksh_system"
    / "forced_ref_ai.py"
)


def _load_helper_methods():
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    service = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ForcedRefAIService"
    )
    selected = {
        "_is_invitation_link_button",
        "_is_verification_success_text",
        "_normalise_captcha_label",
        "_normalise_math_text",
        "_button_label",
        "_custom_emoji_id_from_button",
        "_captcha_target_labels",
        "_captcha_target_custom_emoji_ids",
    }
    namespace = {"re": re, "unicodedata": unicodedata}
    methods = {}
    for node in service.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in selected:
            node = ast.fix_missing_locations(
                ast.FunctionDef(
                    name=node.name,
                    args=node.args,
                    body=node.body,
                    decorator_list=[],
                    returns=node.returns,
                    type_comment=node.type_comment,
                )
            )
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE_PATH), "exec"), namespace)
            methods[node.name] = namespace[node.name]

    class Helper:
        pass

    for name, method in methods.items():
        setattr(Helper, name, staticmethod(method))
    # These target-extraction helpers are classmethods in production, but the
    # helper methods only need the class to call normalization utilities.
    Helper._captcha_target_labels = classmethod(methods["_captcha_target_labels"])
    Helper._captcha_target_custom_emoji_ids = classmethod(
        methods["_captcha_target_custom_emoji_ids"]
    )
    return Helper


class FakeButton:
    def __init__(self, text="", url=None, style=None):
        self.text = text
        self.url = url
        self.style = style


class FakeStyle:
    def __init__(self, icon=None):
        self.icon = icon


class MessageEntityCustomEmoji:
    def __init__(self, offset, document_id):
        self.offset = offset
        self.document_id = document_id


class FakeMessage:
    def __init__(self, text, entities=()):
        self.message = text
        self._entities = entities

    def get_entities_text(self):
        return self._entities


class ForcedRefAIHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = _load_helper_methods()

    def test_target_emoji_is_taken_after_marker_not_heading_emoji(self):
        text = "🤖 للتحقق اضغط على الرمز: 🐙"
        marker_offset = text.index("🐙")
        # A real Telethon entity exposes this class name; this lightweight
        # object keeps the test independent of the Telegram dependencies.
        entity = MessageEntityCustomEmoji(marker_offset, 987654321)
        message = FakeMessage(
            text,
            [(entity, "🐙")],
        )

        labels = self.helper._captcha_target_labels(message, text)
        normalised = {self.helper._normalise_captcha_label(label) for label in labels}

        self.assertIn("🐙", normalised)
        self.assertNotIn("🤖", normalised)

    def test_paid_emoji_matches_button_style_icon(self):
        text = "🤖 للتحقق اضغط على الرمز: 🐙"
        marker_offset = text.index("🐙")
        message = FakeMessage(
            text,
            [(MessageEntityCustomEmoji(marker_offset, 987654321), "🐙")],
        )
        target_ids = self.helper._captcha_target_custom_emoji_ids(message, text)

        matching = FakeButton("🧍", style=FakeStyle(987654321))
        other = FakeButton("🐙", style=FakeStyle(111111111))

        self.assertEqual(target_ids, {987654321})
        self.assertEqual(
            self.helper._custom_emoji_id_from_button(matching),
            987654321,
        )
        self.assertNotEqual(
            self.helper._custom_emoji_id_from_button(other),
            next(iter(target_ids)),
        )

    def test_invitation_detection_does_not_discard_arbitrary_url_button(self):
        self.assertFalse(
            self.helper._is_invitation_link_button(
                FakeButton("تحقق الآن", "https://example.com/verify")
            )
        )
        self.assertTrue(
            self.helper._is_invitation_link_button(
                FakeButton("رابط الدعوة", "https://example.com/anything")
            )
        )
        self.assertTrue(
            self.helper._is_invitation_link_button(
                FakeButton("", "https://t.me/+invitehash")
            )
        )

    def test_success_requires_a_success_marker(self):
        self.assertTrue(self.helper._is_verification_success_text("✅ تم التحقق"))
        self.assertTrue(self.helper._is_verification_success_text("نجح التحقق"))
        self.assertTrue(self.helper._is_verification_success_text("صح"))
        self.assertFalse(self.helper._is_verification_success_text("لم ينجح التحقق"))
        self.assertFalse(self.helper._is_verification_success_text("لم يتم التحقق"))
        self.assertFalse(self.helper._is_verification_success_text("غير صحيح، حاول مرة أخرى"))
        self.assertFalse(self.helper._is_verification_success_text("تم تغيير الأزرار"))

    def test_math_answer_is_not_followed_by_same_message_button_click(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        self.assertEqual(
            self.helper._normalise_math_text("٥ ﹣ ١١ = ؟"),
            "5 - 11 = ؟",
        )
        self.assertIn("math_match = re.search", source)
        self.assertIn("if math_match:\n                continue", source)

    def test_button_label_reads_telethon_wrapper_and_raw_button(self):
        button = FakeButton("🐙")
        button.button = FakeButton("🐙")
        self.assertEqual(self.helper._button_label(button), "🐙")


if __name__ == "__main__":
    unittest.main()
