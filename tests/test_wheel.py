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
    wanted_funcs = {"wheel_pick_prize", "validate_wheel_invoice", "_wheel_public_name"}
    wanted_classes = {"WheelEngine"}
    wanted_vars = {
        "WHEEL_BLOCK_SIZE", "WHEEL_BOOST_INTERVAL_SECONDS", "WHEEL_TEN_SPINS",
        "WHEEL_ROLL_SCALE", "WHEEL_PRIZES", "WHEEL_DISPLAY_ORDER",
        "WHEEL_RANDOM_WEIGHTS", "WHEEL_REMAINDER_PRIZE", "_WHEEL_NAME_STRIP_RE",
        "WHEEL_FREE_PRIZE_KEYS", "WHEEL_FREE_POINTS1000_WEIGHT",
        "WHEEL_BEAR_DAILY_MAX", "WHEEL_DAY_OFFSET_SECONDS",
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


class WheelRulesTests(unittest.TestCase):
    def setUp(self):
        self.w = _load()

    def test_premium_and_weekly_boost_never_win(self):
        w = self.w
        engine = w["WheelEngine"](rng=random.Random(1))
        seen = Counter(engine.next_prize(i * 3600.0) for i in range(200_000))
        for key in ("premium3", "premium6", "premium12", "boost_weekly"):
            self.assertEqual(seen[key], 0)

    def test_at_least_one_jewel_guaranteed_per_100_paid_spins(self):
        w = self.w
        engine = w["WheelEngine"](rng=random.Random(7))
        prizes = [engine.next_prize(0.0) for _ in range(10_000)]
        for start in range(0, 10_000, 100):
            self.assertGreaterEqual(prizes[start:start + 100].count("jewel"), 1, start)

    def test_jewel_and_star_are_about_six_percent(self):
        w = self.w
        engine = w["WheelEngine"](rng=random.Random(3))
        n = 200_000
        counts = Counter(engine.next_prize(0.0) for _ in range(n))
        self.assertAlmostEqual(counts["jewel"] / n, 0.06, delta=0.004)
        self.assertAlmostEqual(counts["star1"] / n, 0.06, delta=0.004)

    def test_bear_never_more_than_two_per_day_and_resets_next_day(self):
        w = self.w
        engine = w["WheelEngine"](rng=random.Random(4))
        start = 86_400 * 20_000 - w["WHEEL_DAY_OFFSET_SECONDS"]  # بداية يوم بتوقيت بغداد
        today = [engine.next_prize(start + 100 + i) for i in range(60_000)]
        self.assertEqual(today.count("bear"), w["WHEEL_BEAR_DAILY_MAX"])
        tomorrow = [engine.next_prize(start + 86_400 + 100 + i) for i in range(60_000)]
        self.assertEqual(tomorrow.count("bear"), 2)

    def test_free_spins_win_only_500_or_1000_points_and_skip_counters(self):
        w = self.w
        engine = w["WheelEngine"](rng=random.Random(11))
        prizes = [engine.next_prize(0.0, paid=False) for _ in range(5000)]
        self.assertEqual(set(prizes), {"points1000", "points500"})
        self.assertEqual(engine.total, 0)
        self.assertEqual(set(w["WHEEL_FREE_PRIZE_KEYS"]), {"points1000", "points500"})
        share = prizes.count("points1000") / len(prizes)
        self.assertAlmostEqual(share, 0.70, delta=0.03)

    def test_paid_spins_can_win_every_listed_prize(self):
        w = self.w
        pick = w["wheel_pick_prize"]
        seen = {pick(r) for r in range(w["WHEEL_ROLL_SCALE"])}
        for key in ("ring", "rose", "bear", "boost_monthly", "jewels10", "star1", "jewel", "points1000", "points500"):
            self.assertIn(key, seen)

    def test_daily_boost_only_once_per_six_hours(self):
        w = self.w
        gap = w["WHEEL_BOOST_INTERVAL_SECONDS"]
        self.assertEqual(gap, 6 * 3600)
        engine = w["WheelEngine"](rng=random.Random(5))
        t0 = 1_800_000_000.0
        wins = []
        # دورة كل دقيقة لمدة 24 ساعة.
        for minute in range(24 * 60):
            now = t0 + minute * 60
            if engine.next_prize(now) == "boost_daily":
                wins.append(now)
        self.assertEqual(len(wins), 4)
        for earlier, later in zip(wins, wins[1:]):
            self.assertGreaterEqual(later - earlier, gap)

    def test_daily_boost_closed_inside_six_hours(self):
        w = self.w
        engine = w["WheelEngine"](rng=random.Random(9))
        t0 = 1_800_000_000.0
        first = [engine.next_prize(t0 + i) for i in range(50)]
        self.assertEqual(first.count("boost_daily"), 1)
        later = [engine.next_prize(t0 + 3 * 3600 + i) for i in range(50)]
        self.assertEqual(later.count("boost_daily"), 0)
        reopened = [engine.next_prize(t0 + 6 * 3600 + i) for i in range(50)]
        self.assertEqual(reopened.count("boost_daily"), 1)

    def test_daily_boost_not_stolen_by_guaranteed_jewel(self):
        w = self.w
        # الدورة الأولى هي موضع الجوهرة المضمونة: يبقى التعزيز اليومي مفتوحاً للدورة التالية.
        engine = w["WheelEngine"](slot_block=0, slot=0, rng=random.Random(2))
        t0 = 1_800_000_000.0
        prizes = [engine.next_prize(t0) for _ in range(30)]
        self.assertEqual(prizes[0], "jewel")
        self.assertEqual(prizes.count("boost_daily"), 1)

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

    def test_probabilities_match_owner_spec(self):
        w = self.w
        pick = w["wheel_pick_prize"]
        scale = w["WHEEL_ROLL_SCALE"]
        counts = Counter(pick(roll) for roll in range(scale))
        self.assertEqual(counts["ring"], 1)            # 0.01%
        self.assertEqual(counts["rose"], 5)            # 0.05%
        self.assertEqual(counts["bear"], 100)          # 1%
        self.assertEqual(counts["boost_monthly"], 50)  # 0.5%
        self.assertEqual(counts["jewels10"], 10)       # 0.1%
        self.assertEqual(counts["star1"], 600)         # 6%
        self.assertEqual(counts["jewel"], 505)         # 5.05% + 1% مضمونة
        self.assertEqual(counts["points1000"], 7000)   # 70%
        self.assertEqual(counts["points500"], scale - 8271)
        for never in ("premium3", "premium6", "premium12", "boost_weekly", "boost_daily"):
            self.assertEqual(counts[never], 0)

    def test_only_jewels_and_points_are_auto_delivered(self):
        prizes = self.w["WHEEL_PRIZES"]
        auto = {k for k, (_l, kind, _v) in prizes.items() if kind != "owner"}
        self.assertEqual(auto, {"jewel", "jewels10", "points1000", "points500"})
        self.assertEqual(prizes["jewel"][1:], ("jewels", 1))
        self.assertEqual(prizes["jewels10"][1:], ("jewels", 10))
        self.assertEqual(prizes["points1000"][1:], ("points", 1000))
        self.assertEqual(prizes["points500"][1:], ("points", 500))

    def test_every_listed_prize_exists(self):
        w = self.w
        self.assertEqual(set(w["WHEEL_DISPLAY_ORDER"]), set(w["WHEEL_PRIZES"]))
        self.assertEqual(len(w["WHEEL_DISPLAY_ORDER"]), 14)

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
