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

        class User:
            id = 17
            full_name = "محمد <اختبار>"

        message = formatter(
            User(),
            "مشاهدة منشور تيليجرام",
            "https://t.me/example/42",
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
        self.assertIn("محمد &lt;اختبار&gt;", message)
        self.assertIn("الرابط: https://t.me/example/42", message)


if __name__ == "__main__":
    unittest.main()