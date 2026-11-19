import ast
import asyncio
import logging
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

VOTES = Path(__file__).parents[1] / "bot_app" / "raksh_system" / "votes.py"
COMMON = Path(__file__).parents[1] / "bot_app" / "raksh_system" / "common.py"


def _load():
    ns = {"re": re, "asyncio": asyncio, "logger": logging.getLogger("t")}
    # duplicate-text helper from common.py
    ctree = ast.parse(COMMON.read_text(encoding="utf-8"))
    for node in ctree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == "RAKSH_DUPLICATE_TEXT_MARKERS" for t in node.targets
        ):
            exec(compile(ast.Module([node], []), "c", "exec"), ns)
        if isinstance(node, ast.FunctionDef) and node.name == "_raksh_is_duplicate_text":
            exec(compile(ast.Module([node], []), "c", "exec"), ns)
    ns["GetBotCallbackAnswerRequest"] = lambda **kw: SimpleNamespace(**kw)
    claims = set()
    ns["_claim_vote"] = lambda key, phone: (key, phone) not in claims and not claims.add((key, phone))
    ns["_unclaim_vote"] = lambda key, phone: claims.discard((key, phone))
    ns["_claims"] = claims
    vtree = ast.parse(VOTES.read_text(encoding="utf-8"))
    wanted = {
        "_VOTED_BUTTON_PATTERNS", "_UNVOTE_DATA_MARKERS", "_VOTE_REMOVED_PATTERNS",
        "_button_shows_voted", "_classify_vote_answer", "_smart_press_vote",
        "_callback_vote_may_have_applied",
    }
    for node in vtree.body:
        name = getattr(node, "name", None) or next(
            (getattr(t, "id", None) for t in getattr(node, "targets", [])), None
        )
        if name in wanted:
            exec(compile(ast.Module([node], []), "v", "exec"), ns)
    return ns


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.presses = 0

    async def __call__(self, request):
        self.presses += 1
        return SimpleNamespace(message=self.replies.pop(0) if self.replies else "")


def btn(text="✅ صوّت", data=b"vote:1"):
    return SimpleNamespace(text=text, data=data)


class VoteStateTests(unittest.TestCase):
    def setUp(self):
        self.ns = _load()

    def run_press(self, client, button, key="k", phone="1"):
        return asyncio.run(self.ns["_smart_press_vote"](client, "peer", 5, button, key, phone))

    def test_normal_label_with_check_is_not_treated_as_voted(self):
        self.assertFalse(self.ns["_button_shows_voted"](btn("✅ صوّت")))

    def test_button_that_shows_voted_is_skipped_without_press(self):
        client = FakeClient([])
        ok, _ = self.run_press(client, btn("تم التصويت ✅"))
        self.assertFalse(ok)
        self.assertEqual(client.presses, 0)

    def test_unvote_callback_is_skipped(self):
        client = FakeClient([])
        ok, _ = self.run_press(client, btn("x", b"unvote:3"))
        self.assertFalse(ok)
        self.assertEqual(client.presses, 0)

    def test_already_voted_answer_not_counted(self):
        client = FakeClient(["لقد صوّتت لهذا الشخص من قبل"])
        ok, _ = self.run_press(client, btn())
        self.assertFalse(ok)

    def test_removed_vote_is_restored_and_not_counted(self):
        client = FakeClient(["تم سحب صوتك", ""])
        ok, msg = self.run_press(client, btn())
        self.assertFalse(ok)
        self.assertEqual(client.presses, 2)  # press + restore

    def test_normal_vote_counts_and_second_try_is_skipped(self):
        client = FakeClient(["شكراً، تم احتساب صوتك"])
        ok, _ = self.run_press(client, btn())
        self.assertTrue(ok)
        ok2, _ = self.run_press(client, btn())
        self.assertFalse(ok2)
        self.assertEqual(client.presses, 1)


if __name__ == "__main__":
    unittest.main()
