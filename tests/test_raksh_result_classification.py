import ast
import unittest
from pathlib import Path
from typing import Tuple


ROOT = Path(__file__).parents[1]


class RakshResultClassificationTests(unittest.TestCase):
    def _load_classifier(self):
        source = (
            ROOT / "bot_app" / "raksh_system" / "raksh_system.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_classify_raksh_result"
        )
        namespace = {"Tuple": Tuple}
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), "<classifier>", "exec"),
            namespace,
        )
        return namespace["_classify_raksh_result"]

    def test_generic_failure_is_not_promoted_to_success(self):
        classify = self._load_classifier()

        ok, message = classify("story", "+964000000000", False, "network error")

        self.assertFalse(ok)
        self.assertEqual("network error", message)

    def test_verification_failure_is_not_promoted_to_success(self):
        classify = self._load_classifier()

        ok, message = classify("votes_ai", "+964000000000", False, "فشل التحقق")

        self.assertFalse(ok)
        self.assertEqual("فشل التحقق", message)

    def test_real_success_remains_success(self):
        classify = self._load_classifier()

        ok, message = classify("story", "+964000000000", True, "تم التنفيذ")

        self.assertTrue(ok)
        self.assertEqual("تم التنفيذ", message)


if __name__ == "__main__":
    unittest.main()