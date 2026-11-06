import asyncio
import html
import importlib.util
import json
import logging
import os
import re
import sys
import time
import types
import unittest
from datetime import timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]


class _Btn:
    def __init__(self, text, callback_data=None, url=None):
        self.text, self.callback_data, self.url = text, callback_data, url


class _Markup:
    def __init__(self, rows):
        self.inline_keyboard = rows


def _load_module(settings):
    """يحمّل tg_numbers مع مساحة أسماء مشتركة مُحاكاة بلا تيليجرام ولا قاعدة بيانات."""
    pkg = types.ModuleType("bot_app")
    pkg.__path__ = [str(ROOT / "bot_app")]
    shared = types.ModuleType("bot_app.shared")
    shared.__dict__.update(
        os=os, re=re, json=json, time=time, asyncio=asyncio, html=html,
        timezone=timezone, logger=logging.getLogger("test"),
        requests=types.SimpleNamespace(get=None),
        ParseMode=types.SimpleNamespace(HTML="HTML"),
        InlineKeyboardButton=_Btn, InlineKeyboardMarkup=_Markup,
        LabeledPrice=lambda label, amount: (label, amount),
        OWNER_ID=1,
        get_setting=lambda key: settings.get(key, ""),
        set_setting=lambda key, value: settings.__setitem__(key, value),
        fmt_jewel_amount=lambda v: str(v),
    )
    sys.modules["bot_app"] = pkg
    sys.modules["bot_app.shared"] = shared
    spec = importlib.util.spec_from_file_location(
        "bot_app.tg_numbers", ROOT / "bot_app" / "tg_numbers.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["bot_app.tg_numbers"] = module
    spec.loader.exec_module(module)
    return module


class TgNumbersPureTests(unittest.TestCase):
    def setUp(self):
        self.settings = {}
        self.m = _load_module(self.settings)

    def tearDown(self):
        for name in ("bot_app", "bot_app.shared", "bot_app.tg_numbers"):
            sys.modules.pop(name, None)

    def test_price_matches_first_bot_formula(self):
        f = self.m.tgnum_final_price_cents
        self.assertEqual(f(30), 40)      # حتى 1$: +10 سنت
        self.assertEqual(f(100), 110)
        self.assertEqual(f(101), 111)    # فوق 1$: +10%
        self.assertEqual(f(250), 275)
        self.assertEqual(f(255), 281)    # 25.5 تُقرَّب للأعلى كما في البوت الأول

    def test_units_cost_rounds_up_and_rejects_bad_rates(self):
        c = self.m.tgnum_units_cost
        self.assertEqual(c(110, 100), 110)  # 1.10$ = 110
        self.assertEqual(c(1, 100), 1)
        self.assertEqual(c(133, 70), 94)   # 93.1 → 94
        self.assertEqual(c(110, 0), 0)
        self.assertEqual(c(0, 70), 0)
        self.assertEqual(c(110, "abc"), 0)

    def test_default_and_custom_rates(self):
        self.assertEqual(self.m.tgnum_price_options(110), (110, 110))
        self.settings["tgnum_stars_per_usd"] = "50"
        self.settings["tgnum_jewels_per_usd"] = "-3"   # غير صالح → الافتراضي
        self.assertEqual(self.m.tgnum_price_options(100), (50, 100))

    def test_calling_code_query_parsing(self):
        p = self.m.tgnum_parse_calling_code_query
        self.assertEqual(p("+964"), "964")
        self.assertEqual(p("00 964"), "964")
        self.assertEqual(p("964"), "964")
        self.assertIsNone(p("abc"))
        self.assertIsNone(p("12345"))
        self.assertIsNone(p("٩٦٤"))

    def test_chat_ref_parsing(self):
        p = self.m.parse_tgnum_chat_ref
        self.assertEqual(p("-1001234567890"), "-1001234567890")
        self.assertEqual(p("@orders_group"), "@orders_group")
        self.assertEqual(p("https://t.me/orders_group"), "@orders_group")
        self.assertIsNone(p("https://t.me/+AbCdEfGh123"))
        self.assertIsNone(p("hello"))

    def test_secret_is_masked(self):
        masked = self.m.tgnum_mask_secret("abcdef123456")
        self.assertNotIn("abcdef", masked)
        self.assertIn("3456", masked)

    def test_catalog_keyboard_paginates(self):
        countries = [
            {"code": f"C{i}", "name": f"N{i}", "flag": "🏳", "price_cents": 100 + i}
            for i in range(30)
        ]
        kb, pages = self.m.tgnum_catalog_keyboard(countries, 1)
        self.assertEqual(pages, 3)
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("tgnum:c:C14:1", data)
        self.assertNotIn("tgnum:c:C0:1", data)
        self.assertTrue(all(len(d.encode()) <= 64 for d in data))

    def test_fetch_parses_supplier_and_applies_markup(self):
        payload = {"status": "ok", "countries": {
            "IQ": {"name": "Iraq", "price": "0.30", "qty": 5},
            "EG": {"name": "Egypt", "price": "2.00", "qty": 0},
            "US": {"name": "USA", "price": "bad", "qty": 3},
        }}
        resp = types.SimpleNamespace(content=json.dumps(payload).encode())
        self.settings.update(tgnum_api_key="key123", tgnum_user_id="77")
        self.m.requests.get = mock.Mock(return_value=resp)
        countries, status = self.m._tgnum_fetch_countries_sync()
        self.assertEqual(status, "ok")
        self.assertEqual([c["code"] for c in countries], ["IQ"])
        self.assertEqual(countries[0]["price_cents"], 40)
        self.assertEqual(countries[0]["calling_code"], "964")

    def test_fetch_requires_credentials(self):
        self.assertEqual(self.m._tgnum_fetch_countries_sync(), (None, "not_configured"))


if __name__ == "__main__":
    unittest.main()
