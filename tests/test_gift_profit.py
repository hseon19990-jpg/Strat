import logging
import re
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "bot_app" / "gift_profit.py"


def load():
    source = MODULE.read_text(encoding="utf-8")
    source = source.replace("from . import shared as _shared\n", "")
    source = re.sub(r"^globals\(\)\.update\(.*\)\n", "", source, flags=re.M)
    ns = {"logger": logging.getLogger("t"), "get_setting": lambda k: None,
          "asyncio": __import__("asyncio")}
    exec(compile(source, str(MODULE), "exec"), ns)
    return ns


NS = load()


class GiftProfitTests(unittest.TestCase):
    def test_default_rate(self):
        self.assertEqual(NS["gp_rate"](), Decimal("0.01275"))

    def test_midnight_baghdad(self):
        now = datetime(2026, 11, 11, 15, 42, tzinfo=ZoneInfo("Asia/Baghdad"))
        mid = NS["gp_midnight_baghdad"](now)
        self.assertEqual((mid.hour, mid.minute, mid.day), (0, 0, 11))

    def test_profit_math(self):
        self.assertEqual(Decimal("100") * NS["gp_rate"](), Decimal("1.27500"))
        self.assertEqual(NS["gp_fmt"](Decimal("1.275")), "1.275")

    def test_wired(self):
        read = lambda r: (ROOT / r).read_text(encoding="utf-8")
        self.assertIn("gift_profit", read("bot_app/__init__.py"))
        self.assertIn("handle_gift_profit_callback", read("bot_app/callbacks.py"))
        self.assertIn("handle_gift_profit_text", read("bot_app/messages.py"))
        self.assertIn('"gp:view:d"', read("bot_app/callback_groups_04.py"))


if __name__ == "__main__":
    unittest.main()
