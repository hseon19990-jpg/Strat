import ast
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_SERVICE_MODULES = (
    "story.py",
    "forced_ref.py",
    "forced_ref_ai.py",
    "votes.py",
    "premium_reaction.py",
)


class RakshMenuFallbackTests(unittest.TestCase):
    def test_active_service_handlers_use_the_shared_menu_helper(self):
        common_path = ROOT / "bot_app" / "raksh_system" / "common.py"
        common_tree = ast.parse(common_path.read_text(encoding="utf-8"))
        self.assertTrue(
            any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "get_raksh_menu_keyboard"
                for node in common_tree.body
            )
        )

        for filename in ACTIVE_SERVICE_MODULES:
            with self.subTest(filename=filename):
                source = (
                    ROOT / "bot_app" / "raksh_system" / filename
                ).read_text(encoding="utf-8")
                tree = ast.parse(source)
                names = {
                    node.id
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Name)
                }
                self.assertIn("get_raksh_menu_keyboard", names)
                self.assertNotIn("raksh_menu_kb", names)

    def test_shared_helper_delegates_to_the_central_menu_lazily(self):
        common_path = ROOT / "bot_app" / "raksh_system" / "common.py"
        tree = ast.parse(common_path.read_text(encoding="utf-8"))
        helper = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "get_raksh_menu_keyboard"
        )

        package_name = "raksh_menu_helper_test_package"
        package = types.ModuleType(package_name)
        package.__path__ = []
        central_module = types.ModuleType(f"{package_name}.raksh_system")
        expected_keyboard = object()
        calls = []

        def central_menu(is_owner=False):
            calls.append(is_owner)
            return expected_keyboard

        central_module.raksh_menu_kb = central_menu
        previous = {
            name: sys.modules.get(name)
            for name in (package_name, f"{package_name}.raksh_system")
        }
        sys.modules[package_name] = package
        sys.modules[f"{package_name}.raksh_system"] = central_module
        try:
            namespace = {"__package__": package_name}
            module = ast.Module(body=[helper], type_ignores=[])
            exec(compile(module, str(common_path), "exec"), namespace)

            self.assertIs(namespace["get_raksh_menu_keyboard"](True), expected_keyboard)
            self.assertEqual(calls, [True])
        finally:
            for name, module in previous.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


if __name__ == "__main__":
    unittest.main()
