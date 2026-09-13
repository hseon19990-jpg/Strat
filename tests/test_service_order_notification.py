import ast
import datetime
import html
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
UI = ROOT / "bot_app" / "ui.py"


def _load_formatter():
    tree = ast.parse(UI.read_text(encoding="utf-8"))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "format_service_order_group_message"
    )
    namespace = {
        "datetime": datetime.datetime,
        "timezone": datetime.timezone,
        "timedelta": datetime.timedelta,
        "html": html,
    }
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), str(UI), "exec"),
        namespace,
    )
    return namespace["format_service_order_group_message"]


class ServiceOrderNotificationTests(unittest.TestCase):
    def test_group_message_uses_requested_labels_and_order(self):
        formatter = _load_formatter()

        message = formatter(
            "مشاهدة منشور تيليجرام",
            150,
            150,
            "1-11469-2195",
            datetime.datetime(2026, 9, 9, 9, 0, tzinfo=datetime.timezone.utc),
        )

        labels = [
            "📱 التطبيق:",
            "💰 السعر:",
            "🔢 العدد:",
            "🕒 الوقت:",
            "📌 الكود:",
        ]
        positions = [message.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("مشاهدة منشور تيليجرام", message)
        self.assertIn("150 نقطة", message)
        self.assertIn("2026-09-09 12:00 (توقيت العراق)", message)
        self.assertNotIn("المستخدم:", message)
        self.assertNotIn("الرابط:", message)

    def test_message_service_group_notification_is_private(self):
        source = (ROOT / "bot_app" / "raksh_system" / "raksh_system.py").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'if service_type == "send_message":',
            source,
        )
        function_source = source[source.index("async def _send_raksh_order_to_group"):]
        private_branch = function_source.split(
            'if service_type == "send_message":',
            1,
        )[1].split(
            "        notification_lines = [",
            1,
        )[0]

        self.assertIn("تم طلب رسالة", private_branch)
        self.assertIn("total_cost", private_branch)
        self.assertIn("الوقت", private_branch)
        self.assertNotIn("message_text", private_branch)
        self.assertNotIn("message_recipient", private_branch)
        self.assertNotIn("identity_name", private_branch)
        self.assertNotIn("user_id", private_branch)


if __name__ == "__main__":
    unittest.main()