import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SERVICE = ROOT / "bot_app" / "raksh_system" / "all_posts_reactions.py"
SERVICES = ROOT / "bot_app" / "services.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class AllPostsReactionsServiceTests(unittest.TestCase):
    def test_service_is_registered_as_a_reaction_and_views_menu_item(self):
        menu_source = _read(SERVICES)
        self.assertIn(
            '("💬👁 رشق تفاعلات ومشاهدات لكل البوستات", "raksh:start:all_posts_reactions", 1)',
            menu_source,
        )

        service_tree = ast.parse(_read(SERVICE))
        service_class = next(
            node
            for node in service_tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "AllPostsReactionsService"
        )
        class_assignments = {
            node.targets[0].id: node.value
            for node in service_class.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        }
        self.assertFalse(
            ast.literal_eval(class_assignments["reaction_only"])
        )
        self.assertEqual(
            ast.literal_eval(class_assignments["service_type"]),
            "all_posts_reactions",
        )

    def test_runtime_contains_reaction_and_view_requests(self):
        source = _read(SERVICE)
        self.assertIn("SendMessageReactionRequest", source)
        self.assertIn("GetMessagesViewsRequest", source)
        self.assertIn("increment=True", source)
        self.assertNotIn("ولا تنفذ مشاهدات أو رشق مشاهدات", source)


if __name__ == "__main__":
    unittest.main()