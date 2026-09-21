import ast
import unittest
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).parents[1]


class RakshSessionIdentityTests(unittest.TestCase):
    def _load_deduper(self):
        source = (
            ROOT / "bot_app" / "raksh_system" / "common.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_dedupe_raksh_sessions"
        )
        namespace = {"Dict": Dict, "List": List}
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), "<deduper>", "exec"),
            namespace,
        )
        return namespace["_dedupe_raksh_sessions"]

    def test_different_sessions_for_same_phone_are_kept(self):
        dedupe = self._load_deduper()

        sessions = dedupe(
            [
                {"id": 1, "phone_number": "+9641", "session_string": "session-a"},
                {"id": 2, "phone_number": "+9641", "session_string": "session-b"},
            ]
        )

        self.assertEqual([1, 2], [session["id"] for session in sessions])

    def test_duplicate_auth_key_is_kept_only_once(self):
        dedupe = self._load_deduper()

        sessions = dedupe(
            [
                {"id": 1, "phone_number": "+9641", "session_string": "same-session"},
                {"id": 2, "phone_number": "+9642", "session_string": "same-session"},
            ]
        )

        self.assertEqual([1], [session["id"] for session in sessions])


if __name__ == "__main__":
    unittest.main()