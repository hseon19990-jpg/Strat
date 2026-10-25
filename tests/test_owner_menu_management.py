import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SERVICES = ROOT / "bot_app" / "services.py"
UI = ROOT / "bot_app" / "ui.py"


def _load_menu_helpers():
    tree = ast.parse(SERVICES.read_text(encoding="utf-8"))
    wanted = {
        "OWNER_ONLY_MAIN_ACTIONS",
        "MENU_ACTIONS_CANNOT_HIDE",
        "visible_main_menu_items",
        "menu_action_cannot_hide",
        "owner_settings_with_purchase_rate_after_sale",
    }
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in wanted
            for target in node.targets
        ):
            nodes.append(node)
    namespace = {}
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(SERVICES), "exec"),
        namespace,
    )
    return namespace


class OwnerMenuManagementTests(unittest.TestCase):
    def test_owner_shortcuts_are_hidden_from_members_but_kept_for_owner(self):
        helpers = _load_menu_helpers()
        menu_items = [
            {"action_value": "daily_gift"},
            {"action_value": "mb_menu:main"},
            {"action_value": "owner_settings"},
        ]

        self.assertEqual(
            helpers["visible_main_menu_items"](menu_items, False),
            [{"action_value": "daily_gift"}],
        )
        self.assertEqual(
            helpers["visible_main_menu_items"](menu_items, True),
            menu_items,
        )

    def test_owner_navigation_can_be_renamed_but_not_hidden(self):
        cannot_hide = _load_menu_helpers()["menu_action_cannot_hide"]

        for action in (
            "mb_menu:main",
            "owner_settings",
            "mb_menu:owner_settings",
            "main_menu",
        ):
            with self.subTest(action=action):
                self.assertTrue(cannot_hide(action))
        self.assertFalse(cannot_hide("daily_gift"))

    def test_hard_coded_owner_controls_are_registered_with_the_menu_store(self):
        services = SERVICES.read_text(encoding="utf-8")
        self.assertIn('("🧩 تعديل أزرار الواجهة", "mb_menu:main", 1)', services)
        self.assertIn('("⚙️ إعدادات المالك", "owner_settings", 1)', services)
        self.assertIn('("🧩 إضافة/إزالة خيار", "mb_menu:owner_settings", 1)', services)
        self.assertIn('("🔙 القائمة الرئيسية", "main_menu", 2)', services)

    def test_currency_exchange_buttons_are_available_in_button_manager(self):
        services = SERVICES.read_text(encoding="utf-8")
        callbacks = (ROOT / "bot_app" / "callback_groups_01.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('"currency_exchange",', services)
        self.assertIn('"currency_exchange": [', services)
        self.assertIn(
            '("💎 تحويل مجوهرات إلى نقاط", "cx:start:jewels_to_points", 1)',
            services,
        )
        self.assertIn(
            '("💰 تحويل نقاط إلى مجوهرات", "cx:start:points_to_jewels", 1)',
            services,
        )
        self.assertIn(
            'build_kb_rows(get_menu_items("currency_exchange"))',
            callbacks,
        )

    def test_settings_menu_shows_exchange_rates_without_duplicate_static_buttons(self):
        ui = UI.read_text(encoding="utf-8")
        owner_settings = ui.split("def owner_settings_kb():", 1)[1].split(
            "\ndef _account_info_counts", 1
        )[0]

        self.assertIn("_currency_rates['jewels_to_points']", owner_settings)
        self.assertIn("_currency_rates['points_to_jewels']", owner_settings)
        self.assertNotIn('callback_data="os:toggle_phone_verification"', owner_settings)
        self.assertNotIn('callback_data="os:openai_api"', owner_settings)
        self.assertNotIn('callback_data="mb_menu:owner_settings"', owner_settings)

    def test_purchase_rate_button_is_clear_and_next_to_sale_rate(self):
        helpers = _load_menu_helpers()
        items = [
            {"id": 10, "action_value": "os:edit_jewel_to_points_rate"},
            {"id": 11, "action_value": "os:other"},
            {"id": 12, "action_value": "os:edit_points_to_jewel_rate"},
        ]
        ordered = helpers["owner_settings_with_purchase_rate_after_sale"](items)
        self.assertEqual(
            [item["action_value"] for item in ordered],
            [
                "os:edit_jewel_to_points_rate",
                "os:edit_points_to_jewel_rate",
                "os:other",
            ],
        )

        services = SERVICES.read_text(encoding="utf-8")
        self.assertIn(
            '("💰 سعر شراء الجوهرة بالنقاط", "os:edit_points_to_jewel_rate", 2)',
            services,
        )
        self.assertIn(
            "POINTS_TO_JEWELS_RATE_BUTTON_MIGRATION_SETTING",
            services,
        )
        self.assertIn(
            'UPDATE menu_items SET enabled=1',
            services,
        )
        self.assertIn(
            '("owner_settings", "os:edit_points_to_jewel_rate")',
            services,
        )


if __name__ == "__main__":
    unittest.main()
