import ast
import asyncio
import time
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Tuple


SOURCE_PATH = (
    Path(__file__).parents[1]
    / "bot_app"
    / "raksh_system"
    / "raksh_system.py"
)


class _QuietLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


def _load_parallel_executor():
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_execute_raksh_parallel"
    )

    async def wait_for_session(_lock, _phone):
        return True

    async def remove_invalid_sessions(_phones):
        return None

    namespace = {
        "asyncio": asyncio,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Tuple": Tuple,
        "RakshService": type("RakshService", (), {}),
        "OWNER_ID": -1,
        "RAKSH_FROZEN_ACCOUNT_MARKER": "__FROZEN__",
        "RAKSH_ACCOUNT_EXECUTION_TIMEOUT_SECONDS": 1,
        "logger": _QuietLogger(),
        "_load_raksh_order_items": lambda _order_id: {},
        "_is_raksh_order_cancelled": lambda _order_id: False,
        "_reserve_raksh_execution_slot": lambda *args, **kwargs: True,
        "_get_raksh_session_lock": lambda _session: asyncio.Lock(),
        "_wait_for_raksh_session": wait_for_session,
        "_mark_raksh_order_item_started": lambda *_args: True,
        "_mark_raksh_session_frozen": lambda *_args: None,
        "_is_raksh_frozen_account_error": lambda _error: False,
        "is_raksh_frozen_account_error": lambda _error: False,
        "_is_retryable_raksh_session_message": lambda _message: False,
        "_reset_raksh_order_item_for_retry": lambda *_args: None,
        "_classify_raksh_result": lambda _type, _phone, ok, message: (ok, message),
        "_mark_raksh_order_item_result": lambda *_args: None,
        "_add_raksh_order_item_for_replacement": lambda *_args: True,
        "_remove_invalid_raksh_sessions": remove_invalid_sessions,
    }
    exec(
        compile(
            ast.Module(body=[function], type_ignores=[]),
            str(SOURCE_PATH),
            "exec",
        ),
        namespace,
    )
    return namespace["_execute_raksh_parallel"]


class _TimedService:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.slow_account_finished = asyncio.Event()
        self.start_times = []

    async def execute(self, session, params, is_first):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.start_times.append(time.monotonic())
        try:
            if session["phone_number"] == "blocked":
                await asyncio.sleep(0.005)
                return False, "ChatWriteForbiddenError: You can't write in this chat"
            if session["phone_number"] == "slow":
                await asyncio.sleep(0.12)
                self.slow_account_finished.set()
            else:
                await asyncio.sleep(0.01)
            return True, "sent"
        finally:
            self.active -= 1


class RakshParallelSchedulerTests(unittest.TestCase):
    def test_respects_concurrency_and_reports_fast_results_without_waiting_for_slowest(self):
        executor = _load_parallel_executor()
        service = _TimedService()
        progress_before_slow_account = []
        progress_updates = []

        async def progress(completed, _quantity, _successes, _failures):
            progress_updates.append(completed)
            if completed and not service.slow_account_finished.is_set():
                progress_before_slow_account.append(completed)

        sessions = [
            {"phone_number": "blocked", "session_string": "session"},
            {"phone_number": "slow", "session_string": "session"},
            *[
                {"phone_number": f"fast-{index}", "session_string": "session"}
                for index in range(4)
            ],
        ]

        started_at = time.monotonic()
        result = asyncio.run(
            executor(
                service,
                sessions,
                {},
                user_id=1,
                quantity=5,
                progress_callback=progress,
                service_type="comment",
                max_concurrent=2,
                batch_delay_seconds=0.02,
            )
        )

        self.assertEqual(5, result[0])
        self.assertEqual(["blocked"], result[3])
        self.assertEqual(2, service.max_active)
        self.assertTrue(progress_before_slow_account)
        self.assertTrue(all(value <= 5 for value in progress_updates))
        self.assertLess(service.start_times[0] - started_at, 0.05)
        for previous, current in zip(service.start_times, service.start_times[1:]):
            with self.subTest(previous=previous, current=current):
                self.assertGreaterEqual(current - previous, 0.015)


if __name__ == "__main__":
    unittest.main()
