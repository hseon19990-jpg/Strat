import logging
import re
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "bot_app" / "order_inspect.py"


class _Markup:
    def __init__(self, rows):
        self.rows = rows


class _Button:
    def __init__(self, text, callback_data=None):
        self.text = text
        self.callback_data = callback_data


def load_module():
    """Execute order_inspect.py without the telegram/psycopg2 runtime."""
    source = MODULE.read_text(encoding="utf-8")
    source = source.replace("from . import shared as _shared\n", "")
    source = re.sub(r"^globals\(\)\.update\(.*\)\n", "", source, flags=re.M)
    namespace = {
        "logger": logging.getLogger("test"),
        "InlineKeyboardMarkup": _Markup,
        "InlineKeyboardButton": _Button,
        "PANEL_MAP": {1: {"name": "SMMMAIN", "key": "SECRET-KEY", "url": "https://x"}},
        "ParseMode": type("PM", (), {"HTML": "HTML"}),
    }
    exec(compile(source, str(MODULE), "exec"), namespace)
    return namespace


NS = load_module()


class CodeNormalizationTests(unittest.TestCase):
    def test_dashed_and_plain_codes_match(self):
        self.assertEqual(NS["oi_normalize_code"]("1-1-1"), "111")
        self.assertEqual(NS["oi_normalize_code"]("111"), "111")
        self.assertEqual(NS["oi_normalize_code"](" 12-3-456 "), "123456")

    def test_arabic_digits_and_dash_variants(self):
        self.assertEqual(NS["oi_clean_code"]("١-١-١"), "1-1-1")
        self.assertEqual(NS["oi_normalize_code"]("١ – ١ — ١"), "111")
        self.assertEqual(NS["oi_normalize_code"]("۱۲۳"), "123")

    def test_empty_and_symbols_only(self):
        self.assertEqual(NS["oi_normalize_code"]("---"), "")
        self.assertEqual(NS["oi_normalize_code"](None), "")


class SourceClassificationTests(unittest.TestCase):
    def test_classification(self):
        classify = NS["oi_classify_source"]
        self.assertEqual(classify("referral", "referral:L1:from:55"), "referral")
        self.assertEqual(classify("gift", "wheel:9"), "wheel")
        self.assertEqual(classify("gift", "", 777), "admin_gift")
        self.assertEqual(classify("refund", "smm_refund:12"), "order_refund")
        self.assertEqual(classify("refund", "star_payment_jewels:abc"), "star_refund")
        self.assertEqual(classify("x", "r", origin="exchange"), "exchange")
        self.assertEqual(classify("x", "r", origin="stars"), "star_purchase")
        self.assertEqual(classify("weird", "?"), "other")

    def test_referral_reference_parsing(self):
        parse = NS["oi_parse_referral_reference"]
        self.assertEqual(parse("referral:L3:from:9001"), (3, 9001))
        self.assertIsNone(parse("referral:bad"))
        self.assertIsNone(parse(None))


class FifoTests(unittest.TestCase):
    def ev(self, key, amount, **extra):
        return {"key": key, "amount": Decimal(str(amount)), **extra}

    def test_target_consumes_oldest_unspent_credits(self):
        events = [
            self.ev("ref", 5, origin="ledger"),
            self.ev("exch", 10, origin="exchange"),
            self.ev("spend1", -3),
            self.ev("target", -8),
            self.ev("later", 100),
        ]
        taken, unrecorded = NS["oi_simulate_fifo"](events, "target")
        self.assertEqual([(lot["key"], amt) for lot, amt in taken],
                         [("ref", Decimal(2)), ("exch", Decimal(6))])
        self.assertEqual(unrecorded, 0)

    def test_shortfall_is_reported_as_unrecorded(self):
        events = [self.ev("c", 2), self.ev("target", -5)]
        taken, unrecorded = NS["oi_simulate_fifo"](events, "target")
        self.assertEqual(sum(a for _l, a in taken), Decimal(2))
        self.assertEqual(unrecorded, Decimal(3))

    def test_missing_target_returns_nothing(self):
        taken, unrecorded = NS["oi_simulate_fifo"]([self.ev("c", 2)], "nope")
        self.assertEqual(taken, [])
        self.assertEqual(unrecorded, 0)

    def test_fractional_amounts(self):
        events = [self.ev("c", "1.5"), self.ev("target", "-0.25")]
        taken, unrecorded = NS["oi_simulate_fifo"](events, "target")
        self.assertEqual(taken[0][1], Decimal("0.25"))
        self.assertEqual(unrecorded, 0)


class FormattingTests(unittest.TestCase):
    def test_split_respects_limit(self):
        text = "\n".join(f"line {i} " + "x" * 100 for i in range(200))
        chunks = NS["oi_split_message"](text, 1000)
        self.assertTrue(all(len(c) <= 1000 for c in chunks))
        self.assertEqual("\n".join(chunks).replace("\n", ""), text.replace("\n", ""))

    def test_amount_format(self):
        self.assertEqual(NS["oi_fmt_amount"](Decimal("1500")), "1,500")
        self.assertEqual(NS["oi_fmt_amount"]("2.50"), "2.5")
        self.assertEqual(NS["oi_fmt_amount"](None), "0")


class RenderingTests(unittest.TestCase):
    def sample(self, method="jewels", sources=None):
        return {
            "order": {
                "id": "5", "user_id": "42", "order_code": "3-7-19", "payment_method": method,
                "cost_jewels": "12", "cost_stars": "0", "status": "pending",
                "api_order_id": "9001", "link": "https://t.me/<x>", "quantity": "500",
                "created_at": "2026-11-08 10:00:00", "telegram_payment_id": "",
            },
            "service": {"id": "3", "name_ar": "متابعين <b>", "panel": "1", "api_service_id": "77",
                        "description": "وصف"},
            "intent": {"id": "8", "status": "completed"},
            "person": {"row": {"user_id": "42", "full_name": "أحمد <script>", "username": "ahmed",
                               "jewels": "3"}, "referrals_total": 2},
            "sources": sources,
        }

    def test_card_escapes_html_and_shows_name(self):
        text = NS["oi_render_card"](self.sample())
        self.assertIn("أحمد &lt;script&gt;", text)
        self.assertIn("3-7-19", text)
        self.assertNotIn("<script>", text)

    def test_card_has_the_four_buttons(self):
        kb = NS["oi_card_kb"](5)
        callbacks = [b.callback_data for row in kb.rows for b in row]
        for expected in ("os:oi:site:5", "os:oi:svc:5", "os:oi:usr:5", "os:oi:src:5"):
            self.assertIn(expected, callbacks)

    def test_site_info_never_leaks_panel_key(self):
        text = NS["oi_render_site"](self.sample(), {"status": "In progress", "remains": "10"})
        self.assertNotIn("SECRET-KEY", text)
        self.assertIn("9001", text)
        self.assertIn("In progress", text)

    def test_sources_referral_lists_person_and_username(self):
        sources = [{
            "kind": "referral", "amount": "7", "when": "2026-11-01", "reference": "referral:L2:from:55",
            "level": 2,
            "person": {"id": 55, "name": "سارة", "username": "sara", "joined_at": "2026-10-30"},
            "chain": [{"id": 55, "name": "سارة", "username": "sara"}, {"id": 60, "name": "ليث", "username": None}],
        }]
        text = NS["oi_render_sources"](self.sample(sources=sources))
        self.assertIn("سارة", text)
        self.assertIn("@sara", text)
        self.assertIn("55", text)
        self.assertIn("ليث", text)

    def test_sources_exchange_explains_how_it_was_obtained(self):
        sources = [{"kind": "exchange", "amount": "5", "when": "t", "reference": "req-1",
                    "points": 5000, "rate": 1000}]
        text = NS["oi_render_sources"](self.sample(sources=sources))
        self.assertIn("5,000", text)
        self.assertIn("req-1", text)

    def test_stars_order_has_no_jewel_source(self):
        text = NS["oi_render_sources"](self.sample(method="stars"))
        self.assertIn("نجوم", text)

    def test_person_card_lists_all_user_columns(self):
        text = NS["oi_render_person"](self.sample())
        self.assertIn("أحمد &lt;script&gt;", text)
        self.assertIn("@", NS["_oi_user_line"]("n", "u", 1))


class FakeConn:
    def __init__(self):
        self.queries = []
        self.rowcount = 4

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        return self


class RetentionAndWiringTests(unittest.TestCase):
    def test_retention_is_one_week(self):
        self.assertEqual(NS["ORDER_INSPECT_RETENTION_DAYS"], 7)

    def test_purge_deletes_only_expired_snapshots_in_batches(self):
        conn = FakeConn()
        NS["db_conn"] = lambda: conn
        deleted = NS["purge_expired_order_inspections"]()
        sql, params = conn.queries[0]
        self.assertEqual(deleted, 4)
        self.assertIn("DELETE FROM order_inspect_snapshots", sql)
        self.assertIn("LIMIT", sql)
        self.assertEqual(params, (7, NS["ORDER_INSPECT_PURGE_BATCH"]))
        self.assertNotIn("orders ", sql.replace("order_inspect_snapshots", ""))

    def read(self, relative):
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_everything_is_wired(self):
        self.assertIn('"order_inspect"', self.read("bot_app/__init__.py"))
        self.assertIn("CREATE TABLE IF NOT EXISTS order_inspect_snapshots", self.read("bot_app/database.py"))
        smm = self.read("bot_app/smm_payments.py")
        self.assertIn("RETURNING id", smm)
        self.assertIn("oi_capture_order_safely", smm)
        self.assertIn("handle_order_inspect_callback", self.read("bot_app/callbacks.py"))
        self.assertIn("handle_order_inspect_text", self.read("bot_app/messages.py"))
        self.assertIn('"os:oi:ask"', self.read("bot_app/services.py"))
        self.assertIn('"os:oi:ask"', self.read("bot_app/ui.py"))
        self.assertIn("purge_expired_order_inspections", self.read("bot_app/storage_cleanup.py"))

    def test_order_creation_never_fails_because_of_the_snapshot(self):
        smm = self.read("bot_app/smm_payments.py")
        block = smm[smm.index("لقطة «فحص الطلب»"):]
        block = block[: block.index("await context.bot.send_message")]
        self.assertIn("try:", block)
        self.assertIn("except Exception:", block)


if __name__ == "__main__":
    unittest.main()
