import ast
import unittest
from pathlib import Path


SOURCE_PATH = (
    Path(__file__).parents[1]
    / "bot_app"
    / "raksh_system"
    / "raksh_system.py"
)


def _load_speed_selection_rule():
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_requires_raksh_speed_selection"
    )
    namespace = {
        "RAKSH_SERVICES": {
            service_type: None
            for service_type in (
                "forced_ref_ai",
                "forced_ref",
                "comment",
                "poll",
                "votes",
                "votes_ai",
                "premium_reaction",
                "all_posts_reactions",
                "send_message",
            )
        }
    }
    exec(
        compile(
            ast.Module(body=[function], type_ignores=[]),
            str(SOURCE_PATH),
            "exec",
        ),
        namespace,
    )
    return namespace["_requires_raksh_speed_selection"]


class RakshSpeedSelectionTests(unittest.TestCase):
    def test_every_registered_service_requests_speed_selection(self):
        requires_speed = _load_speed_selection_rule()

        for service_type in (
            "forced_ref_ai",
            "forced_ref",
            "comment",
            "poll",
            "votes",
            "votes_ai",
            "premium_reaction",
            "all_posts_reactions",
            "send_message",
        ):
            with self.subTest(service_type=service_type):
                self.assertTrue(requires_speed(service_type))

    def test_verified_referral_passes_selected_interval_to_scheduler(self):
        tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
        execute_service = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "execute_raksh_service"
        )
        forced_ref_branch = next(
            node
            for node in ast.walk(execute_service)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "service_type"
            and any(
                isinstance(comparator, ast.Constant)
                and comparator.value == "forced_ref_ai"
                for comparator in node.test.comparators
            )
        )
        scheduler_call = next(
            node
            for node in ast.walk(forced_ref_branch)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_execute_raksh_parallel"
        )
        delay_argument = next(
            keyword.value
            for keyword in scheduler_call.keywords
            if keyword.arg == "batch_delay_seconds"
        )

        self.assertIsInstance(delay_argument, ast.Name)
        self.assertEqual("delay_seconds", delay_argument.id)


if __name__ == "__main__":
    unittest.main()
