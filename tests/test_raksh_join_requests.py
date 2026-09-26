import ast
import unittest
from pathlib import Path


SOURCE_PATH = (
    Path(__file__).parents[1]
    / "bot_app"
    / "raksh_system"
    / "common.py"
)


def _load_pending_request_helper():
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_is_join_request_pending_error"
    )
    namespace = {}
    exec(
        compile(
            ast.Module(body=[function], type_ignores=[]),
            str(SOURCE_PATH),
            "exec",
        ),
        namespace,
    )
    return namespace[function.name]


class RakshJoinRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.is_pending = staticmethod(_load_pending_request_helper())

    def test_telegram_join_request_error_is_treated_as_pending(self):
        class InviteRequestSentError(Exception):
            pass

        class JoinRequestSentError(Exception):
            pass

        self.assertTrue(self.is_pending(InviteRequestSentError()))
        self.assertTrue(self.is_pending(JoinRequestSentError()))

    def test_unrelated_join_error_is_not_treated_as_pending(self):
        class InviteHashExpiredError(Exception):
            pass

        self.assertFalse(self.is_pending(InviteHashExpiredError()))
        self.assertFalse(self.is_pending(RuntimeError("channel unavailable")))

    def test_pending_request_is_not_recorded_as_membership(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        self.assertIn("request_pending = False", source)
        self.assertIn("if request_pending:", source)
        self.assertIn("return True", source)


if __name__ == "__main__":
    unittest.main()