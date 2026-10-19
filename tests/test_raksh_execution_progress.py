import ast
import asyncio
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _load_completion_processor():
    source = (
        ROOT / "bot_app" / "raksh_system" / "raksh_system.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_process_raksh_results_as_completed"
    )
    namespace = {"asyncio": asyncio}
    exec(
        compile(
            ast.Module(body=[function], type_ignores=[]),
            "<raksh-progress>",
            "exec",
        ),
        namespace,
    )
    return namespace["_process_raksh_results_as_completed"]


class RakshExecutionProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_results_are_processed_as_accounts_finish(self):
        process_results = _load_completion_processor()
        processed = []

        async def finish_account(label, delay):
            await asyncio.sleep(delay)
            return label

        async def on_result(result):
            processed.append(result)

        tasks = [
            asyncio.create_task(finish_account("slow", 0.04)),
            asyncio.create_task(finish_account("fast", 0.005)),
        ]

        await process_results(tasks, on_result)

        self.assertEqual(["fast", "slow"], processed)


if __name__ == "__main__":
    unittest.main()
