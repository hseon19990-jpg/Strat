import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SHARED = ROOT / "bot_app" / "shared.py"
MESSAGES = ROOT / "bot_app" / "messages.py"
CALLBACKS = ROOT / "bot_app" / "callback_groups_02.py"


def _load_flow_helpers():
    tree = ast.parse(SHARED.read_text(encoding="utf-8"))
    wanted = {"reset_owner_flow", "begin_owner_flow"}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_OWNER_FLOW_PREFIXES"
            for target in node.targets
        ):
            nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted:
            nodes.append(node)
    namespace = {}
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(SHARED), "exec"),
        namespace,
    )
    return namespace["reset_owner_flow"], namespace["begin_owner_flow"]


class FakeContext:
    def __init__(self, **user_data):
        self.user_data = user_data


class OwnerFlowIsolationTests(unittest.TestCase):
    def test_beginning_points_flow_removes_service_price_data(self):
        _, begin_owner_flow = _load_flow_helpers()
        context = FakeContext(
            state="os_await_service_price",
            owner_flow="service_create",
            edit_svc_id=42,
            new_svc_name="خدمة قديمة",
            points_target_id=7,
        )

        begin_owner_flow(
            context,
            "points",
            "os_await_points_target",
            points_mode="give",
        )

        self.assertEqual(context.user_data["state"], "os_await_points_target")
        self.assertEqual(context.user_data["owner_flow"], "points")
        self.assertEqual(context.user_data["points_mode"], "give")
        self.assertNotIn("edit_svc_id", context.user_data)
        self.assertNotIn("new_svc_name", context.user_data)
        self.assertNotIn("points_target_id", context.user_data)

    def test_reset_owner_flow_keeps_unrelated_user_data(self):
        reset_owner_flow, _ = _load_flow_helpers()
        context = FakeContext(
            state="os_await_service_price",
            owner_flow="service_create",
            ns_info={"rate": 1},
            transfer_to=123,
            regular_setting="keep",
        )

        reset_owner_flow(context)

        self.assertEqual(context.user_data["state"], "main_menu")
        self.assertNotIn("owner_flow", context.user_data)
        self.assertNotIn("ns_info", context.user_data)
        self.assertEqual(context.user_data["transfer_to"], 123)
        self.assertEqual(context.user_data["regular_setting"], "keep")

    def test_price_handlers_no_longer_use_ambiguous_state_names(self):
        messages = MESSAGES.read_text(encoding="utf-8")
        callbacks = CALLBACKS.read_text(encoding="utf-8")

        self.assertNotIn('state == "os_await_price"', messages)
        self.assertNotIn('state == "ns_await_price"', messages)
        self.assertNotIn('"os_edit_await_price"', messages + callbacks)
        self.assertIn('state == "os_await_service_price"', messages)
        self.assertIn('state == "ns_await_service_price"', messages)
        self.assertIn('state == "os_edit_await_service_price"', messages)
        self.assertIn('owner_flow") == "points"', messages)
        self.assertIn('owner_flow") == "service_create"', messages)


if __name__ == "__main__":
    unittest.main()