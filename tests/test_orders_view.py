import asyncio
import logging
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "bot_app" / "orders_view.py"


class _Markup:
    def __init__(self, rows):
        self.rows = rows


class _Button:
    def __init__(self, text, callback_data=None):
        self.text = text
        self.callback_data = callback_data


def load_module(status_fn=None):
    source = MODULE.read_text(encoding="utf-8")
    source = source.replace("from . import shared as _shared\n", "")
    source = re.sub(r"^globals\(\)\.update\(.*\)\n", "", source, flags=re.M)
    ns = {
        "logger": logging.getLogger("test"),
        "InlineKeyboardMarkup": _Markup,
        "InlineKeyboardButton": _Button,
        "ParseMode": type("PM", (), {"HTML": "HTML"}),
        "smm_order_status": status_fn or (lambda oid, panel=1: {}),
    }
    exec(compile(source, str(MODULE), "exec"), ns)
    return ns


NS = load_module()


def order(**kw):
    base = {"id": 1, "user_id": 55, "order_code": "1-5-3", "quantity": 1000,
            "status": "completed", "payment_method": "points", "cost_points": 50,
            "s_name_ar": "متابعين", "link": "https://t.me/x", "created_at": "2026-11-01 10:00:00",
            "u_full_name": "علي", "u_username": "ali", "api_order_id": "9", "svc_api_id": 7}
    base.update(kw)
    return base


class ResolveTests(unittest.TestCase):
    def test_completed_without_live(self):
        _k, label, delivered, remains = NS["ov_resolve"](order())
        self.assertEqual((delivered, remains), (1000, 0))
        self.assertIn("مكتمل", label)

    def test_live_remains_gives_delivered(self):
        _k, label, delivered, remains = NS["ov_resolve"](
            order(status="pending"), {"status": "In progress", "remains": "250"})
        self.assertEqual((delivered, remains), (750, 250))
        self.assertIn("قيد التنفيذ", label)

    def test_pending_without_live_is_unknown(self):
        _k, _l, delivered, remains = NS["ov_resolve"](order(status="pending"))
        self.assertIsNone(delivered)
        self.assertIsNone(remains)

    def test_remains_clamped(self):
        _k, _l, delivered, remains = NS["ov_resolve"](
            order(status="pending"), {"status": "Partial", "remains": "5000"})
        self.assertEqual((delivered, remains), (0, 1000))

    def test_partial_refund_flag(self):
        key, *_ = NS["ov_resolve"](order(partial_refund_pts=10))
        self.assertEqual(key, "partial")


class PaidTests(unittest.TestCase):
    def test_methods(self):
        paid = NS["ov_paid_text"]
        self.assertEqual(paid(order()), "50 نقطة")
        self.assertIn("⭐", paid(order(payment_method="stars", cost_stars=7)))
        self.assertIn("💎", paid(order(payment_method="jewels", cost_jewels=3)))
        self.assertIn("مجاناً", paid(order(payment_method="free")))


class RenderTests(unittest.TestCase):
    def test_user_page_hides_provider_details(self):
        text = NS["ov_render_user_page"]([order(provider_cost_usd=0.5)], {}, 0, 1, 0)
        self.assertIn("1-5-3", text)
        self.assertNotIn("SMMMAIN", text)
        self.assertNotIn("0.5", text)
        self.assertNotIn("API", text)
        self.assertNotIn("9</code>", text)

    def test_user_page_escapes_html(self):
        text = NS["ov_render_user_page"]([order(s_name_ar="<b>x</b>")], {}, 0, 1, 0)
        self.assertNotIn("<b>x</b>", text)

    def test_owner_page_has_all_columns(self):
        text = NS["ov_render_owner_page"]([order()], {}, 0, 1, 0)
        for needle in ("1-5-3", "علي", "@ali", "50 نقطة", "مكتمل", "1,000/1,000", "باقي 0"):
            self.assertIn(needle, text)

    def test_owner_page_fits_telegram_limit(self):
        rows = [order(id=i, u_full_name="ا" * 80, link="x" * 500) for i in range(10)]
        text = NS["ov_render_owner_page"](rows, {}, 0, 500, 3)
        self.assertLess(len(text), 4096)


class NavTests(unittest.TestCase):
    def labels(self, offset, total, size=10):
        return [(b.text, b.callback_data) for b in NS["ov_nav_row"]("ov:own", offset, size, total)]

    def test_first_page_only_next(self):
        self.assertEqual(self.labels(0, 25), [("التالي ⏭", "ov:own:10")])

    def test_middle_page_both(self):
        self.assertEqual(self.labels(10, 25),
                         [("↩️ رجوع", "ov:own:0"), ("التالي ⏭", "ov:own:20")])

    def test_last_page_only_back(self):
        self.assertEqual(self.labels(20, 25), [("↩️ رجوع", "ov:own:10")])

    def test_single_page_none(self):
        self.assertEqual(self.labels(0, 4), [])


class LiveTests(unittest.TestCase):
    def test_only_active_orders_are_queried(self):
        calls = []

        def fake(oid, panel=1):
            calls.append(oid)
            return {"status": "In progress", "remains": "10"}

        ns = load_module(fake)
        rows = [order(id=1, status="completed", api_order_id="a"),
                order(id=2, status="pending", api_order_id="b"),
                order(id=3, status="pending", api_order_id="")]
        lives = asyncio.run(ns["ov_fetch_live"](rows))
        self.assertEqual(calls, ["b"])
        self.assertEqual(list(lives), [2])

    def test_provider_error_is_ignored(self):
        ns = load_module(lambda oid, panel=1: {"error": "down"})
        lives = asyncio.run(ns["ov_fetch_live"]([order(status="pending")]))
        self.assertEqual(lives, {})


class FilterTests(unittest.TestCase):
    def test_parse_defaults_and_validation(self):
        parse = NS["ov_parse_filter"]
        self.assertEqual(parse([]), ("a", "a", 0))
        self.assertEqual(parse(["p", "w", "123"]), ("p", "w", 123))
        self.assertEqual(parse(["zz", "q", "abc"]), ("a", "a", 0))
        self.assertEqual(parse(["c", "t", "9" * 40]), ("c", "t", 0))

    def test_query_parts(self):
        build = NS["ov_build_query_parts"]
        source, where, params = build("a", "a", 0, None)
        self.assertEqual((source, where, params), ("orders o", "", ()))
        source, where, params = build("p", "w", 55, None)
        self.assertIn("o.ts", where)
        self.assertEqual(params, (55, 168))
        self.assertIn("created_at::timestamptz", source)
        _s, where, params = build("a", "a", 55, user_id=7)   # عضو عادي لا يتجاوز نفسه
        self.assertEqual(params, (7,))

    def test_describe(self):
        self.assertEqual(NS["ov_filter_describe"]("a", "a", 0), "")
        self.assertIn("قيد التنفيذ", NS["ov_filter_describe"]("p", "a", 0))

    def test_nav_keeps_filter(self):
        row = NS["ov_nav_row"]("ov:own", 0, 10, 25, "p:w:0")
        self.assertEqual(row[0].callback_data, "ov:own:10:p:w:0")


class CsvTests(unittest.TestCase):
    def test_formula_injection_is_neutralised(self):
        cell = NS["ov_csv_cell"]
        self.assertEqual(cell("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(cell("+1"), "'+1")
        self.assertEqual(cell("عادي"), "عادي")
        self.assertEqual(cell(None), "")

    def test_csv_has_bom_header_and_row(self):
        data = NS["ov_build_csv"]([order(u_full_name="=cmd")])
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        text = data.decode("utf-8-sig")
        self.assertIn("كود الطلب", text.splitlines()[0])
        self.assertIn("1-5-3", text)
        self.assertIn("'=cmd", text)


class ReorderTests(unittest.TestCase):
    svc = {"active": 1, "min_qty": 100, "max_qty": 5000, "service_type": None}

    def test_ok(self):
        self.assertIsNone(NS["ov_reorder_problem"](order(), self.svc))

    def test_problems(self):
        p = NS["ov_reorder_problem"]
        self.assertTrue(p(None, self.svc))
        self.assertTrue(p(order(), None))
        self.assertTrue(p(order(), dict(self.svc, active=0)))
        self.assertTrue(p(order(), dict(self.svc, service_type="mandatory_sub")))
        self.assertTrue(p(order(link=""), self.svc))
        self.assertTrue(p(order(quantity=10), self.svc))


class ReportTests(unittest.TestCase):
    def test_render(self):
        cur = dict(total=5, buyers=3, completed=2, partial=1, active=1, cancelled=1,
                   points=100, stars=3, jewels=9, free=0, provider_usd=1.234)
        text = NS["ov_render_report"]({"cur": cur, "prev": {"total": 8}}, [("خدمة <x>", 4)], 2)
        self.assertIn("-3", text)
        self.assertIn("$1.23", text)
        self.assertIn("خدمة &lt;x&gt;", text)
        self.assertIn("عالقة", text)

    def test_no_stuck_line_when_zero(self):
        cur = dict(total=0, buyers=0, completed=0, partial=0, active=0, cancelled=0,
                   points=0, stars=0, jewels=0, free=0, provider_usd=0.0)
        self.assertNotIn("عالقة", NS["ov_render_report"]({"cur": cur, "prev": {"total": 0}}, [], 0))


class WiringTests(unittest.TestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_everything_is_wired(self):
        self.assertIn('"orders_view"', self.read("bot_app/__init__.py"))
        self.assertIn("handle_orders_view_callback", self.read("bot_app/callbacks.py"))
        self.assertIn("handle_orders_view_text", self.read("bot_app/messages.py"))
        self.assertIn("handle_order_inspect_text", self.read("bot_app/messages.py"))
        self.assertIn("ov_schedule_daily_report", self.read("bot_app/application.py"))
        self.assertIn('"ov:me:0"', self.read("bot_app/services.py"))
        self.assertIn('"ov:own:0"', self.read("bot_app/services.py"))
        self.assertIn("order_inspect_snapshots", self.read("bot_app/database.py"))


if __name__ == "__main__":
    unittest.main()
