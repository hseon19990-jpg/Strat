import ast
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).parents[1]


class RakshSpeedSelectionTests(unittest.TestCase):
    def test_all_registered_services_offer_speed_selection(self):
        source = (
            ROOT / "bot_app" / "raksh_system" / "raksh_system.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {
                "_should_prompt_raksh_speed",
                "_needs_raksh_speed_selection",
            }
        ]
        registered = (
            "comment",
            "votes",
            "votes_ai",
            "forced_ref_ai",
            "premium_reaction",
            "story",
        )
        namespace = {
            "str": str,
            "bool": bool,
            "RAKSH_SERVICES": {service_type: object() for service_type in registered},
        }
        exec(
            compile(
                ast.Module(body=functions, type_ignores=[]),
                "<raksh-speed-selection>",
                "exec",
            ),
            namespace,
        )
        should_prompt = namespace["_should_prompt_raksh_speed"]
        for service_type in registered:
            with self.subTest(service_type=service_type):
                self.assertTrue(should_prompt(service_type))

    def test_selected_delay_prevents_a_second_speed_prompt(self):
        source = (
            ROOT / "bot_app" / "raksh_system" / "raksh_system.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_needs_raksh_speed_selection"
        )
        namespace = {}
        exec(
            compile(
                ast.Module(body=[function], type_ignores=[]),
                "<raksh-speed-selection>",
                "exec",
            ),
            namespace,
        )
        needs_selection = namespace["_needs_raksh_speed_selection"]

        self.assertTrue(needs_selection(SimpleNamespace(user_data={}), False))
        self.assertFalse(needs_selection(SimpleNamespace(user_data={}), True))
        self.assertFalse(
            needs_selection(
                SimpleNamespace(user_data={"raksh_delay_seconds": 3.0}),
                False,
            )
        )


if __name__ == "__main__":
    unittest.main()
