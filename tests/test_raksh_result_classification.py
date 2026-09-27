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
        helper = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_is_raksh_account_or_session_failure"
        )
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_classify_raksh_result"
        )
        namespace = {"Tuple": Tuple}
        exec(
            compile(
                ast.Module(body=[helper, function], type_ignores=[]),
                "<classifier>",
                "exec",
            ),
            namespace,
        )
        return namespace["_classify_raksh_result"]

    def test_link_or_network_failure_is_counted_as_success(self):
        classify = self._load_classifier()

        ok, message = classify("story", "+964000000000", False, "network error")

        self.assertTrue(ok)
        self.assertEqual("network error", message)

    def test_missing_post_is_counted_as_success(self):
        classify = self._load_classifier()

        ok, message = classify("votes", "+964000000000", False, "المنشور غير موجود")

        self.assertTrue(ok)
        self.assertEqual("المنشور غير موجود", message)

    def test_verification_or_vote_button_failure_is_counted_as_success(self):
        classify = self._load_classifier()

        for service_type, error in (
            ("votes_ai", "فشل التحقق"),
            ("forced_ref_ai", "لم يُعثر على رسالة تحقق"),
            ("votes", "لم يتم العثور على زر تصويت مناسب في المنشور"),
        ):
            with self.subTest(service_type=service_type, error=error):
                ok, message = classify(
                    service_type,
                    "+964000000000",
                    False,
                    error,
                )

                self.assertTrue(ok)
                self.assertEqual(error, message)

    def test_blocked_or_frozen_account_remains_rejected(self):
        classify = self._load_classifier()

        for error in (
            "الحساب محظور",
            "account is frozen",
            "__RAKSH_FROZEN_ACCOUNT__",
        ):
            with self.subTest(error=error):
                ok, message = classify(
                    "story",
                    "+964000000000",
                    False,
                    error,
                )

                self.assertFalse(ok)
                self.assertEqual(error, message)

    def test_real_success_remains_success(self):
        classify = self._load_classifier()

        ok, message = classify("story", "+964000000000", True, "تم التنفيذ")

        self.assertTrue(ok)
        self.assertEqual("تم التنفيذ", message)


if __name__ == "__main__":
    unittest.main()