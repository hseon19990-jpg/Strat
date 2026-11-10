import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _src(name):
    return (ROOT / "bot_app" / name).read_text(encoding="utf-8")


class ExchangeStarPackageTests(unittest.TestCase):
    def test_owner_sets_stars_then_jewels_for_each_package(self):
        src = _src("messages.py")
        self.assertIn('state == "os_await_pkg_stars"', src)
        self.assertIn('state == "os_await_pkg_jewels"', src)
        self.assertIn("INSERT INTO exchange_star_packages (stars, jewels)", src)
        self.assertIn("ADD COLUMN IF NOT EXISTS jewels", _src("database.py"))

    def test_member_price_comes_from_package_not_global_rate(self):
        src = _src("callback_groups_01.py")
        block = src.split('if data.startswith("exchange:pkg:"):', 1)[1][:900]
        self.assertIn("get_exchange_package(stars)", block)
        self.assertIn("exchange_package_cost(pkg)", block)
        self.assertNotIn("exchange_stars_cost(", block)

    def test_referral_notice_shown_before_buying(self):
        notice = _src("users.py").split("EXCHANGE_STARS_REFERRAL_NOTICE = (", 1)[1].split(")\n", 1)[0]
        for phrase in ("ستتم مراجعة إحالاتك", "ستوري + أفتار", "مطورة أو مميز", "لن يتم استرداد أي شيء".replace("لن", "ولن")):
            self.assertIn(phrase.split(" ")[0], notice)
        src = _src("callback_groups_01.py")
        self.assertEqual(src.count("{EXCHANGE_STARS_REFERRAL_NOTICE}"), 2)


if __name__ == "__main__":
    unittest.main()
