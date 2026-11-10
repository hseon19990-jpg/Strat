import ast
import random
import unittest
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "bot_app" / "wheel.py"
USERS = ROOT / "bot_app" / "users.py"


def _load():
    """يحمّل المنطق الصرف للعجلة دون أي استيراد من البوت أو قاعدة البيانات."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    wanted_funcs = {
        "wheel_pick_prize", "wheel_section_prize_keys",
        "validate_wheel_invoice", "_wheel_public_name",
    }
    wanted_classes = {"WheelEngine"}
    wanted_vars = {
        "WHEEL_TEN_SPINS", "WHEEL_ROLL_SCALE", "WHEEL_PRIZES", "WHEEL_DISPLAY_ORDER",
        "WHEEL_DAY_OFFSET_SECONDS", "WHEEL_FREE_POINTS1000_DAILY_CAP", "WHEEL_SECTIONS", "WHEEL_SECTION_TITLES",
        "_WHEEL_PAID_WEIGHTS", "_WHEEL_PAID_DAILY_CAPS", "_WHEEL_NAME_STRIP_RE",
    }
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_funcs:
            nodes.append(node)
        elif isinstance(node, ast.ClassDef) and node.name in wanted_classes:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in wanted_vars for t in node.targets
        ):
            nodes.append(node)
    ns = {"_secrets": __import__("secrets"), "re": __import__("re"), "html": __import__("html")}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SRC), "exec"), ns)
    return ns


def _load_decimal_helpers():
    tree = ast.parse(USERS.read_text(encoding="utf-8"))
    names = {"parse_positive_decimal", "fmt_decimal", "plain_decimal", "star_points"}
    nodes = [
        n for n in tree.body
        if (isinstance(n, ast.FunctionDef) and n.name in names)
        or (isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_ARABIC_DIGITS" for t in n.targets))
    ]
    from decimal import ROUND_DOWN, ROUND_HALF_UP, InvalidOperation
    ns = {"Decimal": Decimal, "ROUND_DOWN": ROUND_DOWN, "ROUND_HALF_UP": ROUND_HALF_UP,
          "InvalidOperation": InvalidOperation,
          "get_star_to_points_rate": lambda: Decimal("250")}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(USERS), "exec"), ns)
    return ns


DAY0 = 86_400 * 20_000 - 3 * 3600  # بداية يوم بتوقيت بغداد


class WheelRulesTests(unittest.TestCase):
    def setUp(self):
        self.w = _load()

    def engine(self, section, seed=1, **kw):
        return self.w["WheelEngine"](section=section, rng=random.Random(seed), **kw)

    def test_section_weights_match_owner_spec(self):
        w = self.w
        scale = w["WHEEL_ROLL_SCALE"]
        for section, remainder in (("jewels", "points200"), ("stars", "points250")):
            counts = Counter(w["wheel_pick_prize"](r, section) for r in range(scale))
            self.assertEqual(scale, 100_000)
            self.assertEqual(counts["points1000"], 1000)  # 1%
            self.assertEqual(counts["points500"], 1000)   # 1%
            self.assertEqual(counts["jewel"], 5000)       # 5%
            self.assertEqual(counts["star1"], 5000)       # 5%
            self.assertEqual(counts["premium3"], 1)       # 0.001%
            self.assertEqual(counts["developer"], 1)      # 0.001%
            self.assertEqual(counts[remainder], scale - 13_662)
            for never in ("premium6", "premium12", "boost_weekly", "boost_daily"):
                self.assertEqual(counts[never], 0)
        free = Counter(w["wheel_pick_prize"](r, "free") for r in range(scale))
        self.assertEqual(dict(free), {"points100": 70000, "points50": 25000, "points1000": 5000})

    def test_jewels_remainder_is_200_and_stars_remainder_is_250(self):
        w = self.w
        self.assertEqual(w["WHEEL_SECTIONS"]["jewels"]["remainder"], "points200")
        self.assertEqual(w["WHEEL_SECTIONS"]["stars"]["remainder"], "points250")
        self.assertEqual(w["WHEEL_PRIZES"]["points200"][1:], ("points", 200))
        self.assertEqual(w["WHEEL_PRIZES"]["points250"][1:], ("points", 250))

    def test_free_section_only_50_100_1000(self):
        e = self.engine("free", seed=11)
        prizes = [e.next_prize(DAY0) for _ in range(20_000)]
        self.assertEqual(set(prizes), {"points50", "points100", "points1000"})
        n = len(prizes)
        self.assertAlmostEqual(prizes.count("points100") / n, 0.75, delta=0.02)   # 70% + ما زاد عن السقف
        self.assertAlmostEqual(prizes.count("points50") / n, 0.25, delta=0.02)
        self.assertEqual(prizes.count("points1000"), 5)                            # السقف اليومي
        e2 = self.engine("free", seed=12)
        day2 = [e2.next_prize(DAY0 + 86_400 + i) for i in range(20_000)]
        self.assertEqual(day2.count("points1000"), 5)

    def test_jewel_and_star_capped_at_three_winners_per_day(self):
        for section in ("jewels", "stars"):
            e = self.engine(section, seed=3)
            day1 = [e.next_prize(DAY0 + 100 + i) for i in range(5_000)]
            self.assertEqual(day1.count("jewel"), 3, section)
            self.assertEqual(day1.count("star1"), 3, section)
            day2 = [e.next_prize(DAY0 + 86_400 + 100 + i) for i in range(5_000)]
            self.assertEqual(day2.count("jewel"), 3, section)
            self.assertEqual(day2.count("star1"), 3, section)

    def test_bear_two_per_day_across_both_paid_sections(self):
        total = 0
        for section in ("jewels", "stars"):
            e = self.engine(section, seed=4)
            total += [e.next_prize(DAY0 + 100 + i) for i in range(60_000)].count("bear")
        self.assertEqual(total, 2)

    def test_daily_boost_one_per_100_jewel_spins_max_two_per_day(self):
        e = self.engine("jewels", seed=7)
        prizes = [e.next_prize(DAY0 + 100) for _ in range(200)]
        self.assertEqual(prizes.count("boost_daily"), 2)           # كتلتان = فوزان
        more = [e.next_prize(DAY0 + 100) for _ in range(100_000)]
        self.assertEqual(more.count("boost_daily"), 0)             # الحد اليومي مكتمل
        tomorrow = [e.next_prize(DAY0 + 86_400 + 100) for _ in range(300)]
        self.assertEqual(tomorrow.count("boost_daily"), 2)         # يوم جديد

    def test_daily_boost_one_per_50_star_spins_max_two_per_day(self):
        e = self.engine("stars", seed=8)
        prizes = [e.next_prize(DAY0 + 100) for _ in range(100)]
        self.assertEqual(prizes.count("boost_daily"), 2)
        for block in range(0, 100, 50):
            self.assertEqual(prizes[block:block + 50].count("boost_daily"), 1)
        self.assertEqual([e.next_prize(DAY0 + 100) for _ in range(50_000)].count("boost_daily"), 0)

    def test_premium3_and_developer_only_in_paid_sections(self):
        w = self.w
        for section in ("jewels", "stars"):
            self.assertIn("premium3", w["wheel_section_prize_keys"](section))
            self.assertIn("developer", w["wheel_section_prize_keys"](section))
        self.assertNotIn("premium3", w["wheel_section_prize_keys"]("free"))
        self.assertNotIn("developer", w["wheel_section_prize_keys"]("free"))
        self.assertEqual(w["WHEEL_PRIZES"]["premium3"][1], "owner")
        self.assertEqual(w["WHEEL_PRIZES"]["developer"][1], "owner")
        e = self.engine("free", seed=5)
        seen = {e.next_prize(DAY0 + i) for i in range(50_000)}
        self.assertFalse(seen & {"premium3", "developer"})

    def test_free_never_wins_boost_or_paid_prizes(self):
        e = self.engine("free", seed=2)
        seen = {e.next_prize(DAY0) for _ in range(30_000)}
        self.assertFalse(seen & {"boost_daily", "jewel", "star1", "bear", "ring", "rose"})

    def test_members_see_possible_prizes_per_section(self):
        w = self.w
        keys = w["wheel_section_prize_keys"]
        self.assertEqual(set(keys("free")), {"points50", "points100", "points1000"})
        self.assertEqual(
            set(keys("jewels")),
            {"premium3", "developer", "boost_daily", "boost_monthly", "bear", "rose", "ring",
             "star1", "jewel", "jewels10", "points1000", "points500", "points200"},
        )
        self.assertIn("points250", keys("stars"))
        self.assertNotIn("points200", keys("stars"))
        for section in ("free", "jewels", "stars"):
            for never in ("premium6", "premium12", "boost_weekly"):
                self.assertNotIn(never, keys(section))

    def test_group_name_has_no_id_username_or_link(self):
        name = self.w["_wheel_public_name"]

        class U:
            full_name = "𝗨𝗡!𝗖𝗟 | جـيـمـي @QB_IB https://t.me/QB_IB tg://user?id=6438209923"
            id = 6438209923

        out = name(U())
        for banned in ("@", "QB_IB", "t.me", "tg://", "6438209923"):
            self.assertNotIn(banned, out)
        self.assertIn("جـيـمـي", out)

        class Empty:
            full_name = "@only_handle"
            id = 1

        self.assertEqual(name(Empty()), "عضو")

    def test_only_jewels_and_points_are_auto_delivered(self):
        prizes = self.w["WHEEL_PRIZES"]
        auto = {k for k, (_l, kind, _v) in prizes.items() if kind != "owner"}
        self.assertEqual(
            auto,
            {"jewel", "jewels10", "points1000", "points500", "points250",
             "points200", "points100", "points50"},
        )
        self.assertEqual(prizes["jewel"][1:], ("jewels", 1))
        self.assertEqual(prizes["jewels10"][1:], ("jewels", 10))

    def test_every_section_prize_exists(self):
        w = self.w
        for section in w["WHEEL_SECTIONS"]:
            for key in w["wheel_section_prize_keys"](section):
                self.assertIn(key, w["WHEEL_PRIZES"])
        self.assertTrue(set(w["WHEEL_DISPLAY_ORDER"]) <= set(w["WHEEL_PRIZES"]))

    def test_wheel_invoice_validation(self):
        v = self.w["validate_wheel_invoice"]
        self.assertEqual(v("wheel_stars:1:5:1", 5, 1, "XTR"), 1)
        self.assertEqual(v("wheel_stars:10:5:9", 5, 9, "XTR"), 10)
        self.assertIsNone(v("wheel_stars:10:5:9", 6, 9, "XTR"))
        self.assertIsNone(v("wheel_stars:10:5:9", 5, 10, "XTR"))
        self.assertIsNone(v("wheel_stars:3:5:3", 5, 3, "XTR"))
        self.assertIsNone(v("wheel_stars:1:5:1", 5, 1, "USD"))


class DecimalSettingsTests(unittest.TestCase):
    def setUp(self):
        self.h = _load_decimal_helpers()

    def test_accepts_small_decimals(self):
        p = self.h["parse_positive_decimal"]
        self.assertEqual(p("0.01"), Decimal("0.01"))
        self.assertEqual(p("0.1"), Decimal("0.1"))
        self.assertEqual(p("٠٫٠١"), Decimal("0.01"))
        self.assertEqual(p("2,000"), Decimal("2000"))
        self.assertEqual(p("1.5"), Decimal("1.5"))

    def test_rejects_bad_values(self):
        p = self.h["parse_positive_decimal"]
        for bad in ("", "0", "-1", "abc", "nan", "inf", "0.0000001"):
            self.assertIsNone(p(bad), bad)

    def test_format_has_no_trailing_zeros(self):
        f = self.h["fmt_decimal"]
        self.assertEqual(f(Decimal("0.010000")), "0.01")
        self.assertEqual(f(Decimal("2000.000000")), "2,000")
        self.assertEqual(f("1.5"), "1.5")

    def test_star_points_round_down_to_whole_points(self):
        sp = self.h["star_points"]
        self.assertEqual(sp(3, Decimal("2.5")), 7)
        self.assertEqual(sp(10, Decimal("0.1")), 1)
        self.assertEqual(sp(1, Decimal("0.5")), 0)
        self.assertEqual(sp(2, None), 500)


if __name__ == "__main__":
    unittest.main()
