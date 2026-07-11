#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت تيلغرام متكامل مع منصة SMMMAIN.COM وموقع JustAnotherPanel
المتغيرات المطلوبة في Railway:
  BOT_TOKEN                  - توكن البوت
  OWNER_ID                   - ايدي المالك
  API_KEY                    - مفتاح API لموقع SMMMAIN.COM (الموقع 1)
  JUSTANOTHERPANEL_API_KEY   - مفتاح API لموقع JustAnotherPanel.com (الموقع 2)
  ADMIN_GROUP_ID             - ايدي الكروب الذي تصله الطلبات
"""

import os
import random
import math
import requests
import logging
import traceback
from datetime import date
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice, BotCommand, BotCommandScopeChat
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, PreCheckoutQueryHandler,
    ChatMemberHandler, ContextTypes, filters
)
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut, RetryAfter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
#  خادم HTTP بسيط لمنع النوم على Render المجاني
# ────────────────────────────────────────────────────────────
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK - Bot is running!")
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

def start_health_server():
    t = threading.Thread(target=run_health_server, daemon=True)
    t.start()
    logger.info("✅ Health server started")

# ────────────────────────────────────────────────────────────
#  إعدادات البيئة
# ────────────────────────────────────────────────────────────
BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
OWNER_ID       = int(os.getenv("OWNER_ID", "0"))
API_KEY        = os.getenv("API_KEY", "")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "0"))
API_URL        = "https://smmmain.com/api/v2"

JUSTANOTHERPANEL_API_KEY = os.getenv("JUSTANOTHERPANEL_API_KEY", "")
JUSTANOTHERPANEL_API_URL = "https://justanotherpanel.com/api/v2"

# ────────────────────────────────────────────────────────────
#  المواقع (المصادر) المتاحة لسحب الخدمات منها
# ────────────────────────────────────────────────────────────
PANEL_MAP = {
    1: {"name": "SMMMAIN",         "key": API_KEY,                  "url": API_URL},
    2: {"name": "JustAnotherPanel", "key": JUSTANOTHERPANEL_API_KEY, "url": JUSTANOTHERPANEL_API_URL},
}

# ────────────────────────────────────────────────────────────
#  قاعدة البيانات - PostgreSQL
# ────────────────────────────────────────────────────────────
import psycopg2
import psycopg2.extras
import psycopg2.pool

DATABASE_URL = (
    os.environ.get("DATABASE_URL") or
    os.environ.get("DB_FILE") or
    os.environ.get("POSTGRES_URL") or
    os.environ.get("POSTGRESQL_URL") or
    ""
)

_pool = None
_pool_lock = threading.Lock()

def get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    1, 20, DATABASE_URL,
                    connect_timeout=10
                )
    return _pool

def reset_pool():
    """إعادة تهيئة pool الاتصالات عند حدوث خطأ فادح"""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception:
                pass
            _pool = None
    logger.warning("⚠️ تم إعادة تهيئة pool قاعدة البيانات")


class SmartCursor:
    """Wrapper يحوّل ? إلى %s ويعيد نفسه من execute() لدعم السلسلة .fetchone()"""
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=None):
        sql = sql.replace('?', '%s')
        if params is None:
            self._cur.execute(sql)
        else:
            self._cur.execute(sql, params)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        return self._cur.rowcount

    def __iter__(self):
        return iter(self._cur)


_DB_RETRY_EXC = (psycopg2.OperationalError, psycopg2.InterfaceError)


class _DBContext:
    """
    مدير سياق آمن لاتصالات PostgreSQL.
    - يختبر الاتصال عند الاستحواذ ويعيد المحاولة مرة واحدة بعد reset_pool.
    - يعيد المحاولة في __exit__ عند فشل commit بسبب انقطاع الشبكة.
    - يُرجع الاتصال المكسور دائماً بـ close=True حتى لا يعود إلى الـ pool.
    """
    def __enter__(self):
        self._conn = None
        self._pool = None
        for attempt in range(2):
            try:
                self._pool = get_pool()
                self._conn = self._pool.getconn()
                # اختبار الاتصال سريعاً
                cur = self._conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                break
            except _DB_RETRY_EXC as e:
                if attempt == 0:
                    logger.warning(f"⚠️ خطأ في الاتصال بالDB، إعادة المحاولة... ({e})")
                    # أعد الاتصال المعطوب إن وُجد
                    if self._conn is not None and self._pool is not None:
                        try:
                            self._pool.putconn(self._conn, close=True)
                        except Exception:
                            pass
                        self._conn = None
                    reset_pool()
                else:
                    raise
        self._raw = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return SmartCursor(self._raw)

    def __exit__(self, exc_type, exc_val, exc_tb):
        conn_broken = False
        try:
            if exc_type:
                self._conn.rollback()
            else:
                self._conn.commit()
        except _DB_RETRY_EXC as e:
            logger.warning(f"⚠️ فشل commit/rollback: {e}")
            conn_broken = True
            try:
                self._conn.rollback()
            except Exception:
                pass
        finally:
            try:
                self._raw.close()
            except Exception:
                pass
            # استخدم نفس الـ pool الذي أصدر الاتصال
            if self._conn is not None and self._pool is not None:
                try:
                    self._pool.putconn(self._conn, close=conn_broken)
                except Exception:
                    pass
        return False


def db_conn():
    return _DBContext()


def with_db_retry(fn, *args, **kwargs):
    """
    تشغيل دالة تستخدم db_conn مع إعادة محاولة واحدة عند انقطاع الاتصال.
    مفيد لعمليات الكتابة الحساسة مثل set_setting.
    """
    for attempt in range(2):
        try:
            return fn(*args, **kwargs)
        except _DB_RETRY_EXC as e:
            if attempt == 0:
                logger.warning(f"⚠️ إعادة محاولة بعد خطأ DB: {e}")
                reset_pool()
            else:
                raise

def init_db():
      logger.info(f"🐘 PostgreSQL DB | DATABASE_URL configured: {bool(DATABASE_URL)}")
      with db_conn() as c:
          c.execute("""
          CREATE TABLE IF NOT EXISTS users (
              user_id      BIGINT PRIMARY KEY,
              username     TEXT,
              full_name    TEXT,
              points       INTEGER DEFAULT 0,
              invited_by   BIGINT DEFAULT 0,
              total_orders INTEGER DEFAULT 0,
              joined_at    TEXT DEFAULT CURRENT_DATE,
              bot_user_num INTEGER,
              verified     INTEGER DEFAULT 0
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS orders (
              id           SERIAL PRIMARY KEY,
              user_id      BIGINT,
              service_id   INTEGER,
              link         TEXT,
              quantity     INTEGER,
              cost_points  INTEGER DEFAULT 0,
              cost_stars   INTEGER DEFAULT 0,
              api_order_id TEXT DEFAULT '',
              status       TEXT DEFAULT 'pending',
              order_code   TEXT,
              created_at   TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS services (
              id              SERIAL PRIMARY KEY,
              category        TEXT,
              api_service_id  INTEGER,
              panel           INTEGER DEFAULT 1,
              name_ar         TEXT,
              description     TEXT,
              min_qty         INTEGER,
              max_qty         INTEGER,
              price_per_point REAL,
              active          INTEGER DEFAULT 1
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS settings (
              key   TEXT PRIMARY KEY,
              value TEXT
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS daily_gifts (
              user_id    BIGINT PRIMARY KEY,
              last_claim TEXT
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS channel_funding (
              id               SERIAL PRIMARY KEY,
              user_id          BIGINT,
              channel_username TEXT,
              funding_type     TEXT,
              cost_points      INTEGER,
              active           INTEGER DEFAULT 1,
              created_at       TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS star_transactions (
              id                  SERIAL PRIMARY KEY,
              user_id             BIGINT,
              stars               INTEGER,
              points_given        INTEGER,
              telegram_payment_id TEXT,
              status              TEXT DEFAULT 'completed',
              created_at          TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS point_transfers (
              id         SERIAL PRIMARY KEY,
              from_user  BIGINT,
              to_user    BIGINT,
              points     INTEGER,
              fee        INTEGER,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS prize_exchanges (
              id          SERIAL PRIMARY KEY,
              user_id     BIGINT,
              prize_type  TEXT,
              prize_value TEXT,
              points_cost INTEGER,
              status      TEXT DEFAULT 'pending',
              created_at  TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS mandatory_channels (
              id               SERIAL PRIMARY KEY,
              channel_username TEXT UNIQUE,
              channel_title    TEXT,
              owner_user_id    BIGINT DEFAULT 0,
              funding_type     TEXT DEFAULT 'mandatory',
              active           INTEGER DEFAULT 1
          )""")
          for _alt in [
              "ALTER TABLE channel_funding ADD COLUMN IF NOT EXISTS target_members INTEGER DEFAULT 0",
              "ALTER TABLE channel_funding ADD COLUMN IF NOT EXISTS current_members INTEGER DEFAULT 0",
              "ALTER TABLE channel_funding ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'",
          ]:
              try: c.execute(_alt)
              except Exception: pass
          c.execute("""
          CREATE TABLE IF NOT EXISTS channel_funding_counts (
              id         SERIAL PRIMARY KEY,
              user_id    BIGINT NOT NULL,
              funding_id INTEGER NOT NULL,
              UNIQUE(user_id, funding_id)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS custom_prizes (
              id          SERIAL PRIMARY KEY,
              name        TEXT NOT NULL,
              quantity    INTEGER DEFAULT 1,
              points_cost INTEGER NOT NULL,
              active      INTEGER DEFAULT 1,
              created_at  TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS promo_codes (
              code       TEXT PRIMARY KEY,
              max_uses   INTEGER DEFAULT 1,
              used_count INTEGER DEFAULT 0,
              points     INTEGER DEFAULT 0,
              active     INTEGER DEFAULT 1,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS promo_uses (
              code    TEXT,
              user_id BIGINT,
              PRIMARY KEY (code, user_id)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS exchange_star_packages (
              id     SERIAL PRIMARY KEY,
              stars  INTEGER NOT NULL,
              active INTEGER DEFAULT 1
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS channel_join_rewards (
              user_id    BIGINT,
              channel_id BIGINT,
              PRIMARY KEY (user_id, channel_id)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS menu_items (
              id           SERIAL PRIMARY KEY,
              menu         TEXT,
              label        TEXT,
              action_type  TEXT DEFAULT 'builtin',
              action_value TEXT,
              width        INTEGER DEFAULT 2,
              sort_order   INTEGER DEFAULT 0,
              enabled      INTEGER DEFAULT 1
          )""")
          # القيم الافتراضية للإعدادات
          default_settings = [
              ('join_channel_reward', '45'),
              ('daily_gift_points', '50'),
              ('referral_points', '30'),
              ('star_to_points', '250'),
              ('exchange_star_rate', '2000'),
              ('telegram_number_cost', '5000'),
              ('transfer_fee_percent', '1'),
              ('mandatory_channel_cost', '200'),
              ('internal_channel_cost', '100'),
              ('welcome_message', 'أهلاً وسهلاً بك في البوت!'),
              ('owner_contact', ''),
              ('total_bot_orders', '0'),
              ('total_bot_users', '0'),
              ('asiacell_text', '⚠️ الشحن التلقائي عبر اسيا سيل غير متاح حالياً.\nيرجى التواصل مع المالك.'),
              ('captcha_enabled', '0'),
              ('exchange_success_msg', ''),
              ('mandatory_channel_min_members', '0'),
              ('internal_channel_min_members', '0'),
              ('owner_contact_label', '💬 تواصل مع المالك'),
              ('support_contact_label', '🛎 تواصل مع الدعم'),
              ('channel_leave_penalty', '75'),
          ]
          for k, v in default_settings:
              c.execute(
                  "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                  (k, v)
              )
      # إضافة أعمدة جديدة بشكل آمن (تُتجاهل إن كانت موجودة)
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE users ADD COLUMN verified INTEGER DEFAULT 0")
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE services ADD COLUMN panel INTEGER DEFAULT 1")
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE users ADD COLUMN referral_credited INTEGER DEFAULT 0")
              # المستخدمون المدعوون سابقاً كانت نقاطهم تُمنح فوراً — علّمهم كمكتملين لتفادي منحهم مرتين
              c.execute("UPDATE users SET referral_credited=1 WHERE invited_by IS NOT NULL AND invited_by != 0")
      except Exception:
          pass
      # إعادة تسمية زر "بدء بوت" إلى "رشق بدء (ستارت) بوت" مع إبقاء نفس الخدمات (نفس action_value)
      try:
          with db_conn() as c:
              c.execute(
                  "UPDATE menu_items SET label=%s WHERE action_type='builtin' AND action_value='cat:start_bot' AND label != %s",
                  ("🤖 رشق بدء (ستارت) بوت", "🤖 رشق بدء (ستارت) بوت")
              )
      except Exception:
          pass
def get_setting(key: str) -> str:
    with db_conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else ""

def _do_set_setting(key: str, value: str):
    with db_conn() as c:
        c.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (key, value))

def set_setting(key: str, value: str):
    """حفظ إعداد مع إعادة محاولة تلقائية عند انقطاع الاتصال"""
    with_db_retry(_do_set_setting, key, value)

def get_or_create_user(user_id: int, username: str, full_name: str, invited_by: int = 0) -> dict:
    with db_conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            c.execute("UPDATE users SET username=?, full_name=? WHERE user_id=?",
                      (username, full_name, user_id))
            return dict(row)
        total = int(get_setting("total_bot_users") or "0") + 1
        set_setting("total_bot_users", str(total))
        c.execute(
            "INSERT INTO users (user_id, username, full_name, invited_by, bot_user_num, verified) VALUES (?,?,?,?,?,0)",
            (user_id, username, full_name, invited_by, total)
        )
        # ملاحظة: لا نمنح نقاط الإحالة هنا — تُمنح فقط بعد اشتراك المستخدم الجديد
        # بالقنوات الإجبارية واجتيازه للتحقق (انظر credit_referral_if_pending)
        return dict(c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone())

def set_user_verified(user_id: int):
    with db_conn() as c:
        c.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))

def credit_referral_if_pending(user_id: int, context=None):
    """يمنح نقاط الإحالة للداعي مرة واحدة فقط، بعد اشتراك المدعو بالقنوات الإجبارية واجتيازه التحقق.
    يُعيد (inviter_id, points) عند المنح، أو None إن لم يكن هناك شيء لمنحه."""
    with db_conn() as c:
        row = c.execute(
            "SELECT invited_by, referral_credited FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        if not row:
            return None
        invited_by = row["invited_by"]
        already = row["referral_credited"]
        if not invited_by or invited_by == 0 or invited_by == user_id or already:
            return None
        rp = int(get_setting("referral_points") or "30")
        # تحديث ذري يمنع منح النقاط أكثر من مرة عند أي تسابق محتمل
        c.execute(
            "UPDATE users SET referral_credited=1 WHERE user_id=%s AND referral_credited=0",
            (user_id,)
        )
        if c.rowcount == 0:
            return None
        c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (rp, invited_by))
    return (invited_by, rp)

def is_user_verified(user_id: int) -> bool:
    with db_conn() as c:
        row = c.execute("SELECT verified FROM users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row["verified"])

def add_points(user_id: int, pts: int):
    with db_conn() as c:
        c.execute("UPDATE users SET points=points+? WHERE user_id=?", (pts, user_id))

def deduct_points(user_id: int, pts: int) -> bool:
    """خصم نقاط بشكل ذري باستخدام UPDATE مشروط — آمن للاستخدام المتزامن"""
    with db_conn() as c:
        c.execute(
            "UPDATE users SET points=points-%s WHERE user_id=%s AND points>=%s",
            (pts, user_id, pts)
        )
        return c.rowcount > 0

def deduct_points_clamped(user_id: int, pts: int) -> int:
    """يخصم نقاطاً بحد أقصى لا يقل عن صفر (لا يجعل الرصيد سالباً)، ويُرجع العدد الفعلي المخصوم."""
    with db_conn() as c:
        row = c.execute("SELECT points FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return 0
        current = row["points"] or 0
        actual = min(pts, current)
        if actual > 0:
            c.execute("UPDATE users SET points=points-%s WHERE user_id=%s", (actual, user_id))
        return actual

def get_user(user_id: int) -> dict | None:
    with db_conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

def next_order_code(user_id: int) -> str:
    """يُنشئ كود طلب فريد باستخدام UPDATE RETURNING لضمان عدم التكرار"""
    with db_conn() as c:
        c.execute(
            "UPDATE users SET total_orders=total_orders+1 WHERE user_id=%s RETURNING bot_user_num, total_orders",
            (user_id,)
        )
        u = c.fetchone()
        c.execute(
            "UPDATE settings SET value=(value::int+1)::text WHERE key='total_bot_orders' RETURNING value::int AS total",
        )
        row = c.fetchone()
        total = row["total"] if row else 1
        return f"{u['total_orders']}-{u['bot_user_num']}-{total}"

# ────────────────────────────────────────────────────────────
#  واجهة SMMMAIN API
# ────────────────────────────────────────────────────────────
def smm_request(action: str, panel: int = 1, **params) -> dict:
    site = PANEL_MAP.get(int(panel), PANEL_MAP[1])
    payload = {"key": site["key"], "action": action, **params}
    try:
        r = requests.post(site["url"], data=payload, timeout=15)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def smm_service_info(service_id: int, panel: int = 1) -> dict:
    res = smm_request("services", panel=panel)
    if isinstance(res, list):
        for s in res:
            if str(s.get("service")) == str(service_id):
                return s
    return {}

def smm_create_order(service_id: int, link: str, quantity: int, panel: int = 1) -> dict:
    return smm_request("add", panel=panel, service=service_id, link=link, quantity=quantity)

def smm_order_status(order_id: str, panel: int = 1) -> dict:
    return smm_request("status", panel=panel, order=order_id)

# ────────────────────────────────────────────────────────────
#  مساعدات رياضية
# ────────────────────────────────────────────────────────────
def fmt_price(n) -> str:
    """يعرض السعر بدون فاصلة عشرية إن كان رقماً صحيحاً (100.0 → 100)، وإلا يُبقيه كما هو."""
    try:
        f = float(n)
    except (TypeError, ValueError):
        return str(n)
    return str(int(f)) if f == int(f) else str(f)


CATEGORY_MAP = {
    "followers":    "رشق متابعين",
    "views":        "رشق مشاهدات",
    "interactions": "رشق تفاعلات",
    "story_views":  "رشق مشاهدات ستوري",
    "start_bot":    "رشق بدء (ستارت) بوت",
    "boost":        "تعزيز قناة أو كروب",
    "post_stars":   "نجوم على بوست قناة",
}

# ────────────────────────────────────────────────────────────
#  إدارة أزرار القوائم (يتحكم بها المالك: إضافة/حذف/ترتيب/تحجيم)
# ────────────────────────────────────────────────────────────
MENU_LABELS = {"main": "القائمة الرئيسية", "owner_settings": "قائمة إعدادات المالك", "collect_points": "تجميع نقاط", "contact_support": "تواصل مع الدعم"}
MENU_LABELS.update({f"cat:{k}": f"قائمة فئة: {v}" for k, v in CATEGORY_MAP.items()})

MANAGEABLE_MENUS = ["main", "owner_settings"] + [f"cat:{k}" for k in CATEGORY_MAP]

BUILTIN_DEFAULTS = {
    "main": [
        ("👥 رشق متابعين", "cat:followers", 2), ("📺 تمويل قناتك حقيقي", "fund_channel", 2),
        ("👁 رشق مشاهدات", "cat:views", 2), ("💬 رشق تفاعلات", "cat:interactions", 2),
        ("📖 رشق مشاهدات ستوري", "cat:story_views", 2), ("🤖 رشق بدء (ستارت) بوت", "cat:start_bot", 2),
        ("📣 تعزيز قناة أو كروب", "cat:boost", 2), ("⭐ نجوم على بوست قناة", "cat:post_stars", 2),
        ("🔗 رابط دعوة", "referral", 2), ("💰 تجميع نقاط", "collect_points", 2),
        ("💎 شحن نقاط", "charge_points", 2),
        ("🏆 استبدال نقاط بجوائز", "exchange_points", 2), ("↔️ تحويل النقاط", "transfer_points", 2),
        ("🎟 استخدام كود", "use_promo", 2), ("ℹ️ معلوماتي", "my_info", 2),
        ("🛎 تواصل مع الدعم", "contact_support", 1),
    ],
    "owner_settings": [
        ("➕ إضافة خدمة", "os:add_service", 2), ("📋 قائمة الخدمات", "os:list_services", 2),
        ("🗂 عرض الخدمات", "os:view_services", 2), ("📦 قسم الطلبات", "os:orders_section", 2),
        ("🎁 تعديل الهدية اليومية", "os:edit_gift", 2), ("🎀 جوائز مخصصة", "os:manage_prizes", 2),
        ("🔗 تعديل نقاط الدعوة", "os:edit_referral", 2),
        ("⭐ سعر النجمة شحن", "os:edit_star_rate", 2), ("🏆 سعر نجمة الجوائز", "os:edit_exchange_rate", 2),
        ("📦 باقات الاستبدال بنجوم", "os:manage_star_packages", 1),
        ("📱 سعر رقم تيلغرام", "os:edit_number_cost", 2), ("💌 رسالة الترحيب", "os:edit_welcome", 2),
        ("📢 سعر تمويل إجباري", "os:edit_mandatory_cost", 2), ("🔄 سعر تمويل داخلي", "os:edit_internal_cost", 2),
        ("🎁 نقاط الانضمام للقنوات", "os:edit_join_reward", 1),
        ("❌ خصم مغادرة القناة", "os:edit_leave_penalty", 1),
        ("📡 إدارة قنوات الاشتراك", "os:manage_channels", 2), ("👥 حد أدنى تمويل إجباري", "os:edit_mandatory_min", 2),
        ("👥 حد أدنى تمويل داخلي", "os:edit_internal_min", 2), ("❌ إلغاء صفقة", "os:cancel_order", 2),
        ("✅ إكمال طلب", "os:complete_order", 2),
        ("🎟 إنشاء كود ترويجي", "os:create_promo", 2), ("📋 أكواد ترويجية", "os:list_promos", 2),
        ("💬 رابط تواصل المالك", "os:edit_contact", 2), ("✏️ نص زر التواصل", "os:edit_contact_label", 2),
        ("📲 تعديل نص اسيا سيل", "os:edit_asiacell", 2),
        ("✏️ نص زر الدعم بالقائمة", "os:edit_support_label", 2), ("📢 رسالة جماعية", "os:broadcast", 2),
        ("🔐 تفعيل/تعطيل التحقق", "os:toggle_captcha", 2), ("📊 إحصائيات", "os:stats", 2),
        ("💵 رصيد موقع الرشق", "os:site_balance", 1),
        ("🧩 إدارة الأزرار", "os:manage_buttons", 1),
        ("✏️ رسالة عند الاستبدال", "os:edit_exchange_msg", 1),
    ],
}

GOTO_TARGETS = [
    ("🏠 القائمة الرئيسية", "main_menu"), ("🔗 رابط دعوة", "referral"), ("💰 تجميع نقاط", "collect_points"),
    ("💎 شحن نقاط", "charge_points"),
    ("🏆 استبدال نقاط بجوائز", "exchange_points"), ("↔️ تحويل النقاط", "transfer_points"),
    ("🎟 استخدام كود", "use_promo"), ("ℹ️ معلوماتي", "my_info"), ("📺 تمويل قناتك حقيقي", "fund_channel"),
] + [(v, f"cat:{k}") for k, v in CATEGORY_MAP.items()]


def seed_menu_items(menu: str):
    # تأكد من حذف daily_gift و join_channels من القائمة الرئيسية دائماً
    with db_conn() as c:
        c.execute(
            "DELETE FROM menu_items WHERE menu='main' AND action_value IN ('daily_gift','join_channels')"
        )
    with db_conn() as c:
        existing = c.execute(
            "SELECT action_value FROM menu_items WHERE menu=? AND action_type='builtin'", (menu,)
        ).fetchall()
        existing_values = {r["action_value"] for r in existing}
        defaults = BUILTIN_DEFAULTS.get(menu, [])
        if not existing:
            for i, (label, value, width) in enumerate(defaults):
                c.execute(
                    "INSERT INTO menu_items (menu,label,action_type,action_value,width,sort_order,enabled) VALUES (?,?,?,?,?,?,1)",
                    (menu, label, "builtin", value, width, i)
                )
            return
        # نلحق أي أزرار أساسية جديدة أضيفت للكود بعد أول تشغيل (بدون التأثير على ترتيب/تعديلات المالك الحالية)
        row = c.execute("SELECT MAX(sort_order) AS m FROM menu_items WHERE menu=?", (menu,)).fetchone()
        next_order = (row["m"] or 0) + 1
        for label, value, width in defaults:
            if value not in existing_values:
                c.execute(
                    "INSERT INTO menu_items (menu,label,action_type,action_value,width,sort_order,enabled) VALUES (?,?,?,?,?,?,1)",
                    (menu, label, "builtin", value, width, next_order)
                )
                next_order += 1


def get_menu_items(menu: str, only_enabled: bool = True):
    seed_menu_items(menu)
    with db_conn() as c:
        q = "SELECT * FROM menu_items WHERE menu=?"
        if only_enabled:
            q += " AND enabled=1"
        q += " ORDER BY sort_order, id"
        return c.execute(q, (menu,)).fetchall()


def render_mb_menu_screen(menu: str):
    """يبني نص وأزرار شاشة إدارة أزرار قائمة معيّنة (مستخدم من عدة أماكن)."""
    items = get_menu_items(menu, only_enabled=False)
    rows = []
    for it in items:
        state_icon = "✅" if it["enabled"] else "🚫"
        width_icon = "▬ عريض" if it["width"] == 1 else "🔲 نصف"
        rows.append([InlineKeyboardButton(f"{state_icon} {it['label']}", callback_data="noop")])
        rows.append([
            InlineKeyboardButton("⬆️", callback_data=f"mb_up:{menu}:{it['id']}"),
            InlineKeyboardButton("⬇️", callback_data=f"mb_down:{menu}:{it['id']}"),
            InlineKeyboardButton(width_icon, callback_data=f"mb_width:{menu}:{it['id']}"),
            InlineKeyboardButton("🗑" if it["enabled"] else "♻️", callback_data=f"mb_toggle:{menu}:{it['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ إضافة زر جديد", callback_data=f"mb_add:{menu}")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_buttons")])
    text = (f"🧩 *أزرار: {MENU_LABELS.get(menu, menu)}*\n\n"
            f"✅ ظاهر | 🚫 مخفي — اضغط 🗑 للإخفاء و♻️ للإظهار مجدداً.")
    return text, InlineKeyboardMarkup(rows)


def build_kb_rows(items):
    """يبني صفوف الأزرار مع مراعاة عرض كل زر (1=يملأ السطر لحاله، 2=زران بجانب بعض)."""
    rows = []
    pending = None
    for it in items:
        label = it["label"]
        if it["action_type"] == "url":
            btn = InlineKeyboardButton(label, url=it["action_value"])
        elif it["action_type"] == "text":
            btn = InlineKeyboardButton(label, callback_data=f"mi_text:{it['id']}")
        else:  # builtin أو goto - يستخدم callback_data مباشرة
            btn = InlineKeyboardButton(label, callback_data=it["action_value"])
        if it["width"] == 1:
            if pending:
                rows.append([pending])
                pending = None
            rows.append([btn])
        else:
            if pending:
                rows.append([pending, btn])
                pending = None
            else:
                pending = btn
    if pending:
        rows.append([pending])
    return rows


def md_escape(text: str) -> str:
    """يُهرّب رموز Markdown (النمط القديم) داخل نص متغيّر (اسم مستخدم/اسم كامل)
    قبل إدراجه في رسالة parse_mode=MARKDOWN، لتفادي فشل الإرسال بصمت عند وجود
    عدد فردي من _ أو * أو ` أو [ في اسم المستخدم (شائع جداً في يوزرات تيليجرام)."""
    if not text:
        return text
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


def generate_math():
    a, b = random.randint(1, 9), random.randint(1, 9)
    op = random.choice(['+', '-', '×'])
    if op == '+': return f"{a} + {b}", a + b
    if op == '-':
        a, b = max(a, b), min(a, b)
        return f"{a} - {b}", a - b
    return f"{a} × {b}", a * b

# ────────────────────────────────────────────────────────────
#  لوحات المفاتيح
# ────────────────────────────────────────────────────────────
def main_menu_kb(is_owner=False):
    rows = build_kb_rows(get_menu_items("main"))
    if is_owner:
        rows.append([InlineKeyboardButton("🧩 إضافة/إزالة خيار", callback_data="mb_menu:main")])
        rows.append([InlineKeyboardButton("⚙️ إعدادات المالك", callback_data="owner_settings")])
    return InlineKeyboardMarkup(rows)

def _render_service_list():
    """يبني نص وأزرار قائمة الخدمات (يُستخدم من العرض والتفعيل/التعطيل)."""
    with db_conn() as c:
        svcs = c.execute("SELECT * FROM services ORDER BY category, id").fetchall()
    if not svcs:
        return "📋 لا توجد خدمات مضافة.", None
    lines = ["📋 *قائمة الخدمات:*\n"]
    for s in svcs:
        status = "✅" if s["active"] else "❌"
        site_name = PANEL_MAP.get(s["panel"] or 1, PANEL_MAP[1])["name"]
        lines.append(
            f"{status} [{s['id']}] *{s['name_ar']}*\n"
            f"الفئة: {CATEGORY_MAP.get(s['category'], s['category'])} | الموقع: {site_name} | Min:{s['min_qty']} Max:{s['max_qty']}\n"
        )
    rows = []
    for s in svcs:
        tog = "❌ تعطيل" if s["active"] else "✅ تفعيل"
        rows.append([
            InlineKeyboardButton(f"{s['name_ar'][:20]}", callback_data="noop"),
            InlineKeyboardButton("✏️ تعديل", callback_data=f"os_edit_svc:{s['id']}"),
            InlineKeyboardButton(tog, callback_data=f"os_tog_svc:{s['id']}:{1 if not s['active'] else 0}"),
            InlineKeyboardButton("🗑", callback_data=f"os_del_svc:{s['id']}")
        ])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
    return "\n".join(lines), rows


async def send_services_overview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض كل الخدمات مجمّعة حسب الفئة — رسالة مستقلة لكل فئة (الأعضاء برسالة، التفاعلات برسالة، وهكذا)."""
    chat_id = update.effective_chat.id
    sent_any = False
    first = True
    for cat_key, cat_name in CATEGORY_MAP.items():
        with db_conn() as c:
            svcs = c.execute(
                "SELECT * FROM services WHERE category=? ORDER BY id", (cat_key,)
            ).fetchall()
        if not svcs:
            continue
        sent_any = True
        lines = [f"📂 *{cat_name}*\n"]
        for s in svcs:
            status = "✅ متاحة" if s["active"] else "❌ معطّلة"
            site_name = PANEL_MAP.get(s["panel"] or 1, PANEL_MAP[1])["name"]
            lines.append(
                f"{status} *{s['name_ar']}*\n"
                f"💰 السعر: {fmt_price(s['price_per_point'])} نقطة / 1000 وحدة\n"
                f"📝 الوصف: {s['description'] or '—'}\n"
                f"📉 الحد الأدنى: {s['min_qty']} | 📈 الحد الأعلى: {s['max_qty']}\n"
                f"🌐 الموقع: {site_name}\n"
            )
        text = "\n".join(lines)
        if first and update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
            first = False
        else:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)

    if not sent_any:
        if update.callback_query:
            await update.callback_query.edit_message_text("📋 لا توجد خدمات مضافة بعد.", reply_markup=owner_settings_kb())
        else:
            await context.bot.send_message(chat_id=chat_id, text="📋 لا توجد خدمات مضافة بعد.", reply_markup=owner_settings_kb())
        return

    await context.bot.send_message(chat_id=chat_id, text="⬆️ هذه كل الخدمات المتاحة حالياً.", reply_markup=owner_settings_kb())


ORDERS_PAGE_SIZE = 10

def _fetch_orders_page(offset: int = 0, limit: int = ORDERS_PAGE_SIZE):
    with db_conn() as c:
        rows = c.execute(
            """SELECT o.*, u.full_name AS u_full_name, u.username AS u_username,
                      s.name_ar AS s_name_ar, s.category AS s_category
               FROM orders o
               LEFT JOIN users u ON u.user_id = o.user_id
               LEFT JOIN services s ON s.id = o.service_id
               ORDER BY o.id DESC
               LIMIT %s OFFSET %s""",
            (limit, offset)
        ).fetchall()
        total = c.execute("SELECT COUNT(*) AS cnt FROM orders").fetchone()["cnt"]
    return rows, total


def _render_order_block(o) -> str:
    uname = f"@{o['u_username']}" if o.get("u_username") else "—"
    full_name = o.get("u_full_name") or "—"
    service_name = o.get("s_name_ar") or f"خدمة #{o['service_id']}"
    category = CATEGORY_MAP.get(o.get("s_category"), o.get("s_category") or "—")
    status_map = {"pending": "⏳ قيد التنفيذ", "completed": "✅ مكتمل", "cancelled": "❌ ملغي"}
    status = status_map.get(o["status"], o["status"])
    return (
        f"🧾 *كود الطلب:* {o['order_code']}\n"
        f"👤 *صاحب الطلب:* {full_name} ({uname}) — ID: `{o['user_id']}`\n"
        f"📦 *نوع الطلب:* {service_name} ({category})\n"
        f"🔗 *الرابط:* {o['link'] or '—'}\n"
        f"🔢 *الكمية:* {o['quantity']}\n"
        f"💰 *التكلفة:* {o['cost_points']} نقطة" + (f" + {o['cost_stars']} نجمة" if o.get("cost_stars") else "") + "\n"
        f"📶 *الحالة:* {status}\n"
        f"🆔 *رقم API:* {o['api_order_id'] or '—'}\n"
        f"🕒 *الوقت:* {o['created_at']}\n"
    )


async def show_orders_section(update: Update, context: ContextTypes.DEFAULT_TYPE, offset: int = 0):
    rows, total = _fetch_orders_page(offset)
    if not rows:
        text = "📦 لا توجد طلبات بعد." if offset == 0 else "📦 لا مزيد من الطلبات."
        kb_rows = [[InlineKeyboardButton("🔍 بحث بكود الطلب", callback_data="os:order_lookup")],
                   [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")]]
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    blocks = [_render_order_block(o) for o in rows]
    header = f"📦 *قسم الطلبات* ({offset + 1}-{offset + len(rows)} من {total})\n\n"
    text = header + "\n➖➖➖➖➖\n".join(blocks)

    nav = []
    if offset + ORDERS_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("◀️ الأقدم", callback_data=f"os:orders_page:{offset + ORDERS_PAGE_SIZE}"))
    if offset > 0:
        nav.append(InlineKeyboardButton("الأحدث ▶️", callback_data=f"os:orders_page:{max(0, offset - ORDERS_PAGE_SIZE)}"))
    kb_rows = []
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton("🔍 بحث بكود الطلب", callback_data="os:order_lookup")])
    kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                                        reply_markup=InlineKeyboardMarkup(kb_rows))
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
                                         reply_markup=InlineKeyboardMarkup(kb_rows))


def owner_settings_kb():
    rows = build_kb_rows(get_menu_items("owner_settings"))
    rows.append([InlineKeyboardButton("🧩 إضافة/إزالة خيار", callback_data="mb_menu:owner_settings")])
    rows.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def charge_points_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ الشحن عبر النجوم", callback_data="charge:stars")],
        [InlineKeyboardButton("📱 الشحن عبر اسيا سيل", callback_data="charge:asiacell")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
    ])

def charge_stars_kb():
    rate = int(get_setting("star_to_points") or "250")
    quick_amounts = [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000]
    quick_rows = []
    for i in range(0, len(quick_amounts), 5):
        row = [InlineKeyboardButton(f"{n} ⭐", callback_data=f"charge:quick:{n}") for n in quick_amounts[i:i+5]]
        quick_rows.append(row)
    rows = [
        [InlineKeyboardButton(f"1 ⭐ = {rate} نقطة", callback_data="charge:info")],
    ] + quick_rows + [
        [InlineKeyboardButton("🔢 شحن عدد نقاط معين", callback_data="charge:by_points"),
         InlineKeyboardButton("⭐ شحن بعدد نجوم معين", callback_data="charge:by_stars")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="charge_points")],
    ]
    return InlineKeyboardMarkup(rows)

def exchange_kb():
    with db_conn() as c:
        prizes = c.execute(
            "SELECT id, name, quantity, points_cost FROM custom_prizes WHERE active=1 ORDER BY id"
        ).fetchall()
    rows = [
        [InlineKeyboardButton("⭐ استبدال نقاط بنجوم", callback_data="exchange:stars")],
        [InlineKeyboardButton("📱 شراء رقم تيلغرام",  callback_data="exchange:number")],
    ]
    for p in prizes:
        # يُعرض الاسم فقط — السعر يظهر بعد الضغط
        rows.append([InlineKeyboardButton(
            f"🎁 {p['name']}",
            callback_data=f"exchange:custom:{p['id']}"
        )])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def fund_channel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 تمويل قناة إجباري سريع", callback_data="fund:mandatory")],
        [InlineKeyboardButton("🔄 تمويل قناة داخلي بطيء", callback_data="fund:internal")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
    ])

def _leave_penalty_note() -> str:
    penalty = int(get_setting("channel_leave_penalty") or "75")
    return f"\n⚠️ *ملاحظة:* إذا غادرت القناة بعد الحصول على نقاطها سيتم خصم *{penalty} نقطة* من رصيدك تلقائياً."

def back_kb(target="main_menu"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=target)]])

def contact_owner_row() -> list:
    """يُرجع صفاً يحتوي زر تواصل مع المالك إن كان رابط التواصل مضبوطاً، وإلا قائمة فارغة."""
    contact = get_setting("owner_contact") or ""
    if not contact:
        return []
    label = get_setting("owner_contact_label") or "💬 تواصل مع المالك"
    return [[InlineKeyboardButton(label, url=contact)]]

# ────────────────────────────────────────────────────────────
#  إرسال إشعار للكروب
# ────────────────────────────────────────────────────────────
async def notify_group(app, text: str):
    if ADMIN_GROUP_ID:
        try:
            await app.bot.send_message(ADMIN_GROUP_ID, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"notify_group error: {e}")

# ────────────────────────────────────────────────────────────
#  عرض خدمات الفئة
# ────────────────────────────────────────────────────────────
async def show_category_services(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str):
    with db_conn() as c:
        svcs = c.execute(
            "SELECT * FROM services WHERE category=? AND active=1", (category,)
        ).fetchall()
    if not svcs:
        kb = back_kb("main_menu")
        text = f"⚠️ لا توجد خدمات متاحة في ({CATEGORY_MAP.get(category, category)}) حالياً.\nتواصل مع المالك لإضافة خدمات."
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)
        return
    rows = []
    for s in svcs:
        rows.append([InlineKeyboardButton(
            f"{'⭐' if s['category']=='post_stars' else '🔹'} {s['name_ar']}",
            callback_data=f"svc:{s['id']}"
        )])
    extra_items = get_menu_items(f"cat:{category}")
    rows.extend(build_kb_rows(extra_items))
    _cat_user = update.effective_user
    if _cat_user and _cat_user.id == OWNER_ID:
        rows.append([InlineKeyboardButton("🧩 إضافة/إزالة خيار", callback_data=f"mb_menu:cat:{category}")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
    text = f"📦 *{CATEGORY_MAP.get(category, category)}*\nاختر الخدمة المطلوبة:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                                      parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                        parse_mode=ParseMode.MARKDOWN)

# ────────────────────────────────────────────────────────────
#  الاشتراك الإجباري + التحقق النهائي
# ────────────────────────────────────────────────────────────
async def get_unjoined_mandatory_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """يُرجع قائمة القنوات الإجبارية التي لم ينضم لها المستخدم بعد."""
    with db_conn() as c:
        channels = c.execute(
            "SELECT * FROM mandatory_channels WHERE active=1 AND funding_type='mandatory'"
        ).fetchall()
    unjoined = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(f"@{ch['channel_username']}", user_id)
            if member.status in ("left", "kicked", "banned"):
                unjoined.append(ch)
        except Exception:
            # تعذّر التحقق (مثلاً البوت ليس مشرفاً بالقناة) — نعتبرها غير منضمة احتياطاً
            unjoined.append(ch)
    return unjoined


async def count_user_for_fundings(user_id: int, context):
    """
    تحسب هذا المستخدم ضمن التمويلات النشطة التي لم يُحسب فيها بعد.
    الشرط: يجب أن يكون المستخدم قد انضم عبر البوت (سجل في channel_join_rewards).
    عند اكتمال أي تمويل: يُوقَف تلقائياً ويُرسَل إشعار لصاحبه.
    """
    with db_conn() as c:
        fundings = c.execute(
            """SELECT cf.id, cf.channel_username, cf.funding_type,
                      cf.target_members, cf.current_members, cf.user_id AS owner_id,
                      mc.id AS mc_id
               FROM channel_funding cf
               JOIN mandatory_channels mc ON mc.channel_username = cf.channel_username
               WHERE mc.active = 1 AND cf.status = 'active' AND cf.target_members > 0"""
        ).fetchall()

    for f in fundings:
        # ── شرط التمييز: لا يُحسب إلا من انضم عبر البوت (ضغط تحقق فعلاً) ──
        with db_conn() as c:
            verified_via_bot = c.execute(
                "SELECT 1 FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                (user_id, f["mc_id"])
            ).fetchone()
        if not verified_via_bot:
            continue
        with db_conn() as c:
            c.execute(
                "INSERT INTO channel_funding_counts (user_id, funding_id) VALUES (%s, %s) "
                "ON CONFLICT (user_id, funding_id) DO NOTHING",
                (user_id, f["id"])
            )
            if c.rowcount == 0:
                continue
            c.execute(
                "UPDATE channel_funding SET current_members = current_members + 1 WHERE id = %s",
                (f["id"],)
            )
            row = c.execute(
                "SELECT current_members, target_members FROM channel_funding WHERE id = %s",
                (f["id"],)
            ).fetchone()

        if not row:
            continue
        if row["current_members"] >= row["target_members"]:
            # ✅ اكتمل التمويل — أوقف القناة وأبلغ المالك
            with db_conn() as c:
                c.execute("UPDATE channel_funding SET status='completed' WHERE id=%s", (f["id"],))
                c.execute("UPDATE mandatory_channels SET active=0 WHERE channel_username=%s", (f["channel_username"],))
            try:
                ft_label = "إجباري سريع" if f["funding_type"] == "mandatory" else "داخلي بطيء"
                await context.bot.send_message(
                    chat_id=f["owner_id"],
                    text=(
                        f"🎉 *اكتمل تمويل قناتك!*\n\n"
                        f"📢 القناة: @{f['channel_username']}\n"
                        f"⚙️ النوع: {ft_label}\n"
                        f"👥 العدد المستهدف: {f['target_members']:,} عضو — ✅ تم الوصول!"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass


def mandatory_join_kb(channels):
    rows = []
    for ch in channels:
        rows.append([InlineKeyboardButton(
            f"📢 {ch['channel_title'] or ('@' + ch['channel_username'])}",
            url=f"https://t.me/{ch['channel_username']}"
        )])
    rows.append([InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_mandatory_join")])
    return InlineKeyboardMarkup(rows)


async def show_mandatory_gate(update: Update, context: ContextTypes.DEFAULT_TYPE, channels, edit=False):
    text = (
        "📢 *الاشتراك الإجباري*\n\n"
        "للمتابعة، يجب عليك الاشتراك بالقنوات التالية أولاً:\n"
        "ثم اضغط «✅ تحقق من الاشتراك»."
    )
    kb = mandatory_join_kb(channels)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def proceed_after_mandatory(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
    """بعد اجتياز بوابة الاشتراك الإجباري: يعرض سؤال التحقق الرياضي إن كان مفعّلاً، وإلا يُنهي التحقق مباشرة."""
    user = update.effective_user
    captcha_on = int(get_setting("captcha_enabled") or "0")
    if not captcha_on:
        await finalize_verification(update, context, user, edit=edit)
        return

    prob, ans = generate_math()
    context.user_data["state"] = "verify_math"
    context.user_data["math_ans"] = ans

    text = f"🔐 للدخول للبوت، أجب على هذه المسألة البسيطة:\n\n❓  *{prob} = ؟*"
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def finalize_verification(update: Update, context: ContextTypes.DEFAULT_TYPE, user, edit=False):
    """تُستدعى بعد اجتياز الاشتراك الإجباري والتحقق: تُفعّل المستخدم، تمنح نقاط الإحالة، وتعرض القائمة الرئيسية."""
    set_user_verified(user.id)
    await count_user_for_fundings(user.id, context)
    is_own = (user.id == OWNER_ID)

    referral_note = ""
    credited = credit_referral_if_pending(user.id, context)
    if credited:
        invited_by, rp = credited
        invited_name = md_escape(f"@{user.username}") if user.username else md_escape(user.full_name or "مستخدم")
        inviter_row = get_user(invited_by)
        inviter_name = "صديقك"
        if inviter_row:
            inviter_username = inviter_row.get("username")
            inviter_full_name = inviter_row.get("full_name")
            inviter_name = md_escape(f"@{inviter_username}") if inviter_username else md_escape(inviter_full_name or "صديقك")
        try:
            await context.bot.send_message(
                chat_id=invited_by,
                text=f"🎉 مبروك! لقد أكمل المستخدم {invited_name} الاشتراك والتحقق عن طريق رابط دعوتك، وحصلت على {rp} نقطة.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as _e:
            logger.warning(f"⚠️ فشل إرسال إشعار الإحالة للمستخدم {invited_by}: {_e}")
        referral_note = f"\n\n🔗 لقد دخلت إلى رابط دعوة صديقك {inviter_name} وقد حصل على {rp} نقطة."

    context.user_data["state"] = "main_menu"
    db_user = get_user(user.id)
    pts = db_user["points"] if db_user else 0
    welcome = get_setting("welcome_message") or "أهلاً بك!"
    text = f"✅ *تم التحقق بنجاح!*\n\n{welcome}\n\n💰 رصيدك: {pts} نقطة{referral_note}"
    kb = main_menu_kb(is_own)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يبدأ تدفّق المستخدم الجديد/غير المتحقق: بوابة الاشتراك الإجباري أولاً، ثم التحقق."""
    user = update.effective_user
    unjoined = await get_unjoined_mandatory_channels(context, user.id)
    if unjoined:
        context.user_data["state"] = "await_mandatory_join"
        await show_mandatory_gate(update, context, unjoined, edit=False)
        return
    await proceed_after_mandatory(update, context, edit=False)


# ────────────────────────────────────────────────────────────
#  /start
# ────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    invited_by = int(args[0]) if args and args[0].isdigit() else 0

    db_user = get_or_create_user(user.id, user.username or "", user.full_name or "", invited_by)
    is_own = (user.id == OWNER_ID)

    # مستخدم متحقق مسبقاً → تحقق من قنوات إجبارية جديدة أولاً (الاشتراك الإجباري مقدس)
    if db_user.get("verified", 0):
        unjoined = await get_unjoined_mandatory_channels(context, user.id)
        if unjoined:
            context.user_data["state"] = "await_mandatory_join"
            await show_mandatory_gate(update, context, unjoined, edit=False)
            return
        # عَدّ المستخدم في التمويلات الجديدة التي لم يُحسب فيها بعد
        await count_user_for_fundings(user.id, context)
        context.user_data["state"] = "main_menu"
        db_user = get_user(user.id)
        pts = db_user["points"] if db_user else 0
        welcome = get_setting("welcome_message") or "أهلاً بك!"
        await update.message.reply_text(
            f"👋 *أهلاً بك مجدداً!*\n\n{welcome}\n\n💰 رصيدك: {pts} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )
        return

    # مستخدم جديد أو لم يُكمل التحقق بعد: تحية ثم بدء تدفّق الاشتراك الإجباري + التحقق
    await update.message.reply_text(
        "👋 *أهلاً بك!*", parse_mode=ParseMode.MARKDOWN
    )
    await start_onboarding(update, context)

# ────────────────────────────────────────────────────────────
#  /admin — لوحة المالك المباشرة
# ────────────────────────────────────────────────────────────
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    await update.message.reply_text(
        "⚙️ *لوحة المالك:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=owner_settings_kb()
    )

async def cmd_addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /addpoints <user_id> <points> — يضيف (أو يخصم برقم سالب) نقاطاً لمستخدم معيّن."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text("الاستخدام:\n/addpoints <user_id> <points>")
        return

    try:
        target_id = int(args[0])
        pts = int(args[1])
    except ValueError:
        await update.message.reply_text("⚠️ تأكد أن المعرف والنقاط أرقام صحيحة.")
        return

    target = get_user(target_id)
    if not target:
        await update.message.reply_text("⚠️ لا يوجد مستخدم بهذا المعرف في قاعدة البيانات.")
        return

    if pts == 0:
        await update.message.reply_text("⚠️ عدد النقاط لا يمكن أن يكون صفراً.")
        return

    if pts > 0:
        add_points(target_id, pts)
        actual = pts
    else:
        actual = -deduct_points_clamped(target_id, -pts)

    await update.message.reply_text(f"✅ تم تعديل رصيد المستخدم {target_id} بمقدار {actual} نقطة.")

    try:
        if actual > 0:
            await context.bot.send_message(target_id, f"💰 تم إضافة {actual} نقطة إلى رصيدك من قبل الإدارة.")
        elif actual < 0:
            await context.bot.send_message(target_id, f"⚠️ تم خصم {-actual} نقطة من رصيدك من قبل الإدارة.")
    except Exception:
        pass

# ────────────────────────────────────────────────────────────
#  معالج الرسائل النصية (آلة الحالة)
# ────────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    text   = update.message.text.strip()
    state  = context.user_data.get("state", "")
    is_own = (user.id == OWNER_ID)

    # ── فرض الاشتراك الإجباري على المستخدمين المتحققين عبر الرسائل أيضاً ──
    if not is_own and state not in ("verify_math", "await_mandatory_join"):
        _db_user = get_user(user.id)
        if _db_user and _db_user.get("verified", 0):
            _unjoined = await get_unjoined_mandatory_channels(context, user.id)
            if _unjoined:
                context.user_data["state"] = "await_mandatory_join"
                await show_mandatory_gate(update, context, _unjoined, edit=False)
                return

    # ── التحقق الرياضي ──
    if state == "verify_math":
        correct = context.user_data.get("math_ans")
        try:
            ans = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً فقط.")
            return
        if ans == correct:
            await finalize_verification(update, context, user, edit=False)
        else:
            prob, new_ans = generate_math()
            context.user_data["math_ans"] = new_ans
            await update.message.reply_text(
                f"❌ إجابة خاطئة! حاول مجدداً:\n\n❓  *{prob} = ؟*",
                parse_mode=ParseMode.MARKDOWN
            )
        return

    # ── إدارة الأزرار: استلام اسم الزر الجديد ──
    if state == "await_mb_label" and is_own:
        menu = context.user_data.get("mb_menu")
        mb_type = context.user_data.get("mb_type")
        if not (menu and mb_type):
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("⚠️ انتهت الجلسة، ابدأ من جديد.", reply_markup=owner_settings_kb())
            return
        context.user_data["mb_label"] = text
        if mb_type == "url":
            context.user_data["state"] = "await_mb_url"
            await update.message.reply_text("🔗 أرسل الرابط (يبدأ بـ https://):")
        elif mb_type == "text":
            context.user_data["state"] = "await_mb_textcontent"
            await update.message.reply_text("💬 أرسل النص الذي سيظهر للمستخدم عند الضغط على الزر:")
        else:  # goto
            rows = [[InlineKeyboardButton(lbl, callback_data=f"mb_goto_pick:{val}")] for lbl, val in GOTO_TARGETS]
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"mb_menu:{menu}")])
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("↪️ اختر القسم الذي تريد ربط الزر به:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if state == "await_mb_url" and is_own:
        if not (text.startswith("http://") or text.startswith("https://")):
            await update.message.reply_text("⚠️ الرابط يجب أن يبدأ بـ http:// أو https://")
            return
        menu  = context.user_data.get("mb_menu")
        label = context.user_data.get("mb_label")
        with db_conn() as c:
            max_order = c.execute("SELECT COALESCE(MAX(sort_order),-1) AS m FROM menu_items WHERE menu=?", (menu,)).fetchone()["m"]
            c.execute(
                "INSERT INTO menu_items (menu,label,action_type,action_value,width,sort_order,enabled) VALUES (?,?,?,?,?,?,1)",
                (menu, label, "url", text, 2, max_order + 1)
            )
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(f"✅ تمت إضافة الزر '{label}'.",
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للإدارة", callback_data=f"mb_menu:{menu}")]]))
        return

    if state == "await_mb_textcontent" and is_own:
        menu  = context.user_data.get("mb_menu")
        label = context.user_data.get("mb_label")
        with db_conn() as c:
            max_order = c.execute("SELECT COALESCE(MAX(sort_order),-1) AS m FROM menu_items WHERE menu=?", (menu,)).fetchone()["m"]
            c.execute(
                "INSERT INTO menu_items (menu,label,action_type,action_value,width,sort_order,enabled) VALUES (?,?,?,?,?,?,1)",
                (menu, label, "text", text, 2, max_order + 1)
            )
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(f"✅ تمت إضافة الزر '{label}'.",
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للإدارة", callback_data=f"mb_menu:{menu}")]]))
        return

    # ── مسار خدمة SMM: إدخال الرابط (بعد الكمية) ──
    if state == "await_smm_link":
        context.user_data["smm_link"] = text
        svc  = context.user_data.get("smm_svc", {})
        qty  = context.user_data.get("smm_qty", 0)
        cost = context.user_data.get("smm_cost", 0)
        db_user = get_user(user.id)
        pts = db_user["points"] if db_user else 0
        desc_text = svc.get("description") or ""
        context.user_data["state"] = "confirm_smm"
        await update.message.reply_text(
            f"📋 *تفاصيل الطلب:*\n\n"
            f"🔹 الخدمة: {svc.get('name_ar', '')}\n"
            f"🔢 الكمية: {qty}\n"
            f"🔗 الرابط: `{text}`\n"
            + (f"📝 {desc_text}\n" if desc_text else "") +
            f"💰 التكلفة: {cost} نقطة\n"
            f"💎 رصيدك: {pts} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأكيد الطلب", callback_data="confirm_order:yes"),
                 InlineKeyboardButton("❌ إلغاء", callback_data="confirm_order:no")],
                [InlineKeyboardButton("🔙 رجوع (تغيير الرابط)", callback_data="smm_back:link")]
            ])
        )
        return

    if state == "await_smm_qty":
        try:
            qty = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        svc = context.user_data.get("smm_svc", {})
        if not svc:
            svc_id = context.user_data.get("smm_svc_db_id")
            with db_conn() as c:
                svc = dict(c.execute("SELECT * FROM services WHERE id=?", (svc_id,)).fetchone() or {})
            context.user_data["smm_svc"] = svc
        if qty < svc.get("min_qty", 1) or qty > svc.get("max_qty", 1000000):
            await update.message.reply_text(
                f"⚠️ الكمية خارج النطاق المسموح.\nالحد الأدنى: {svc['min_qty']} | الحد الأعلى: {svc['max_qty']}"
            )
            return
        cost = int(qty / 1000 * svc.get("price_per_point", 1))
        context.user_data["smm_qty"] = qty
        context.user_data["smm_cost"] = cost
        context.user_data["state"] = "await_smm_link"
        await update.message.reply_text(
            f"✅ الكمية: {qty} | التكلفة: {cost} نقطة\n\n"
            f"📎 أرسل *رابط* الحساب/القناة/البوست:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع (تغيير الكمية)", callback_data="smm_back:qty")]
            ])
        )
        return

    if state == "confirm_smm":
        if text == "نعم":
            svc  = context.user_data.get("smm_svc", {})
            qty  = context.user_data.get("smm_qty", 0)
            cost = context.user_data.get("smm_cost", 0)
            link = context.user_data.get("smm_link", "")
            if not deduct_points(user.id, cost):
                await update.message.reply_text("❌ نقاطك غير كافية.")
                context.user_data["state"] = "main_menu"
                await update.message.reply_text("🏠 القائمة الرئيسية:", reply_markup=main_menu_kb(is_own))
                return
            api_res = smm_create_order(svc["api_service_id"], link, qty, panel=svc.get("panel", 1))
            if "error" in api_res or not api_res.get("order"):
                add_points(user.id, cost)
                err_msg = api_res.get("error", "خطأ غير معروف من الموقع")
                await update.message.reply_text(
                    f"❌ فشل الطلب: {err_msg}\nتمت إعادة نقاطك.\n\n"
                    f"⚠️ يرجى التأكد من إرسال رابط صحيح ومطابق لنوع الخدمة المطلوبة، ثم أعد إرسال الطلب.",
                    reply_markup=main_menu_kb(is_own)
                )
                context.user_data["state"] = "main_menu"
                return
            api_oid = str(api_res.get("order", ""))
            code    = next_order_code(user.id)
            with db_conn() as c:
                c.execute(
                    "INSERT INTO orders (user_id,service_id,link,quantity,cost_points,api_order_id,order_code) VALUES (?,?,?,?,?,?,?)",
                    (user.id, svc["id"], link, qty, cost, api_oid, code)
                )
            await update.message.reply_text(
                f"✅ *تمت العملية بنجاح!*\n\n"
                f"🔹 الخدمة: {svc['name_ar']}\n"
                f"🔢 الكمية: {qty}\n"
                f"💰 التكلفة: {cost} نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
            await update.message.reply_text(
                f"📌 *كود عمليتك هو:* `{code}`\nاحفظه قد تحتاجه لاحقاً.",
                parse_mode=ParseMode.MARKDOWN
            )
            await notify_group(
                context.application,
                f"🆕 <b>طلب جديد</b>\n"
                f"👤 المستخدم: <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                f"🔹 الخدمة: {svc['name_ar']}\n"
                f"🔗 الرابط: {link}\n"
                f"🔢 الكمية: {qty}\n"
                f"💰 التكلفة: {cost} نقطة\n"
                f"📌 الكود: {code}"
            )
        elif text == "لا":
            await update.message.reply_text("❌ تم إلغاء الطلب.", reply_markup=main_menu_kb(is_own))
        context.user_data["state"] = "main_menu"
        return

    # ── مسار تحويل النقاط ──
    if state == "await_transfer_id":
        try:
            tid = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل ايدي رقمي صحيح.")
            return
        if tid == user.id:
            await update.message.reply_text("⚠️ لا يمكنك التحويل لنفسك.")
            return
        to_user = get_user(tid)
        if not to_user:
            await update.message.reply_text("⚠️ المستخدم غير موجود في البوت.")
            return
        context.user_data["transfer_to"] = tid
        context.user_data["transfer_to_name"] = to_user["full_name"]
        context.user_data["state"] = "await_transfer_pts"
        await update.message.reply_text(
            f"👤 المستلم: {to_user['full_name']}\n\nكم نقطة تريد تحويلها؟ (خصم 1%)"
        )
        return

    if state == "await_transfer_pts":
        try:
            pts = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        if pts <= 0:
            await update.message.reply_text("⚠️ أدخل كمية أكبر من صفر.")
            return
        fee  = max(1, int(pts * 0.01))
        total_deduct = pts + fee
        db_user = get_user(user.id)
        if db_user["points"] < total_deduct:
            await update.message.reply_text(f"❌ نقاطك غير كافية. تحتاج {total_deduct} نقطة (شاملة رسوم 1%).")
            return
        context.user_data["transfer_pts"]   = pts
        context.user_data["transfer_fee"]   = fee
        context.user_data["transfer_total"] = total_deduct
        context.user_data["state"] = "confirm_transfer"
        to_name = context.user_data.get("transfer_to_name", "")
        await update.message.reply_text(
            f"📋 *تأكيد التحويل:*\n\n"
            f"👤 إلى: {to_name}\n"
            f"💰 المبلغ: {pts} نقطة\n"
            f"💸 الرسوم: {fee} نقطة (1%)\n"
            f"📤 الإجمالي: {total_deduct} نقطة\n\n"
            f"أرسل *نعم* للتأكيد أو *لا* للإلغاء",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if state == "confirm_transfer":
        if text == "نعم":
            pts   = context.user_data.get("transfer_pts", 0)
            fee   = context.user_data.get("transfer_fee", 0)
            total = context.user_data.get("transfer_total", 0)
            to_id = context.user_data.get("transfer_to")
            if not deduct_points(user.id, total):
                await update.message.reply_text("❌ نقاطك غير كافية.")
            else:
                add_points(to_id, pts)
                code = next_order_code(user.id)
                with db_conn() as c:
                    c.execute(
                        "INSERT INTO point_transfers (from_user,to_user,points,fee) VALUES (?,?,?,?)",
                        (user.id, to_id, pts, fee)
                    )
                await update.message.reply_text(
                    f"✅ *تم التحويل بنجاح!*\n\n"
                    f"💰 {pts} نقطة إلى المستخدم.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=main_menu_kb(is_own)
                )
                await update.message.reply_text(
                    f"📌 *كود عمليتك:* `{code}`",
                    parse_mode=ParseMode.MARKDOWN
                )
                try:
                    await context.bot.send_message(
                        to_id,
                        f"🎉 تلقيت {pts} نقطة من مستخدم!\n📌 كود: `{code}`",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass
                await notify_group(
                    context.application,
                    f"↔️ <b>تحويل نقاط</b>\n"
                    f"من: <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                    f"إلى: ID {to_id}\n"
                    f"المبلغ: {pts} نقطة | الرسوم: {fee}"
                )
        else:
            await update.message.reply_text("❌ تم إلغاء التحويل.", reply_markup=main_menu_kb(is_own))
        context.user_data["state"] = "main_menu"
        return

    # ── شحن بعدد نقاط معين ──
    if state == "await_charge_points_amount":
        try:
            pts = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً موجباً.")
            return
        if pts <= 0:
            await update.message.reply_text("⚠️ يجب أن يكون عدد النقاط أكبر من صفر.")
            return
        rate  = int(get_setting("star_to_points") or "250")
        stars = math.ceil(pts / rate)
        context.user_data["charge_stars"] = stars
        context.user_data["charge_pts"]   = stars * rate
        context.user_data["state"] = "confirm_charge_stars"
        await update.message.reply_text(
            f"💡 للحصول على {pts} نقطة تحتاج *{stars} ⭐*\n"
            f"(ستحصل فعلياً على {stars * rate} نقطة)\n\n"
            f"أرسل *نعم* للمتابعة للدفع أو *لا* للإلغاء",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if state == "await_charge_stars_amount":
        try:
            stars = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً موجباً.")
            return
        if stars <= 0:
            await update.message.reply_text("⚠️ يجب أن يكون عدد النجوم أكبر من صفر.")
            return
        rate = int(get_setting("star_to_points") or "250")
        pts  = stars * rate
        context.user_data["charge_stars"] = stars
        context.user_data["charge_pts"]   = pts
        context.user_data["state"] = "confirm_charge_stars"
        await update.message.reply_text(
            f"💡 *{stars} ⭐ = {pts} نقطة*\n\n"
            f"أرسل *نعم* للمتابعة للدفع أو *لا* للإلغاء",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if state == "confirm_charge_stars":
        if text == "نعم":
            stars = context.user_data.get("charge_stars", 1)
            await context.bot.send_invoice(
                chat_id=user.id,
                title="شحن نقاط",
                description=f"شراء {context.user_data.get('charge_pts')} نقطة مقابل {stars} نجمة",
                payload=f"charge_stars:{stars}:{user.id}",
                currency="XTR",
                prices=[LabeledPrice("نجوم", stars)],
            )
        else:
            await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_kb(is_own))
        context.user_data["state"] = "main_menu"
        return

    # ── استبدال نقاط بنجوم ──
    if state == "await_exchange_stars_count":
        try:
            stars = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        if stars <= 0:
            await update.message.reply_text("⚠️ يجب أن يكون الرقم أكبر من صفر.")
            return
        rate = int(get_setting("exchange_star_rate") or "2000")
        cost = stars * rate
        db_user = get_user(user.id)
        pts = db_user["points"] if db_user else 0
        if pts < cost:
            await update.message.reply_text(
                f"❌ *نقاطك غير كافية!*\n\n⭐ تحتاج: {cost} نقطة\n💎 رصيدك: {pts} نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
            context.user_data["state"] = "main_menu"
            return
        if not deduct_points(user.id, cost):
            await update.message.reply_text("❌ حدث خطأ في خصم النقاط.", reply_markup=main_menu_kb(is_own))
            context.user_data["state"] = "main_menu"
            return
        code = next_order_code(user.id)
        with db_conn() as c:
            c.execute(
                "INSERT INTO prize_exchanges (user_id,prize_type,prize_value,points_cost,status) VALUES (%s,%s,%s,%s,'pending')",
                (user.id, "stars", str(stars), cost)
            )
        custom_msg = get_setting("exchange_success_msg") or ""
        result_kb_rows = contact_owner_row() + [[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]]
        await update.message.reply_text(
            f"✅ *تمت العملية بنجاح!*\n\n"
            f"⭐ طلب {stars} نجمة مسجل\n"
            f"💰 التكلفة: {cost} نقطة\n\n"
            + (f"{custom_msg}\n\n" if custom_msg else "")
            + "سيتواصل معك المالك قريباً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(result_kb_rows)
        )
        await update.message.reply_text(
            f"📌 *كود عمليتك:* `{code}`",
            parse_mode=ParseMode.MARKDOWN
        )
        await notify_group(
            context.application,
            f"⭐ <b>طلب شراء نجوم (جائزة)</b>\n"
            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
            f"⭐ {stars} نجمة مقابل {cost} نقطة\n"
            f"📌 {code}"
        )
        context.user_data["state"] = "main_menu"
        return

    # ── استخدام كود ترويجي ──
    if state == "await_promo_code":
        code = text.strip().upper()
        # معالجة الكود بشكل ذري في معاملة واحدة لمنع الاستخدام المزدوج
        with db_conn() as c:
            promo = c.execute("SELECT * FROM promo_codes WHERE code=? AND active=1", (code,)).fetchone()
            if not promo:
                await update.message.reply_text(
                    "❌ الكود غير موجود أو منتهي الصلاحية.",
                    reply_markup=main_menu_kb(is_own)
                )
                context.user_data["state"] = "main_menu"
                return
            if promo["used_count"] >= promo["max_uses"]:
                await update.message.reply_text(
                    "⚠️ هذا الكود وصل للحد الأقصى من الاستخدامات.",
                    reply_markup=main_menu_kb(is_own)
                )
                context.user_data["state"] = "main_menu"
                return
            # نحاول إدراج الاستخدام أولاً — إن فشل بسبب PRIMARY KEY فهو مستخدم مسبقاً
            c.execute(
                "INSERT INTO promo_uses (code, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (code, user.id)
            )
            inserted = c.rowcount
            if not inserted:
                await update.message.reply_text(
                    "⚠️ لقد استخدمت هذا الكود مسبقاً.",
                    reply_markup=main_menu_kb(is_own)
                )
                context.user_data["state"] = "main_menu"
                return
            # الإدراج نجح — نكمل بنفس المعاملة
            pts_given = promo["points"]
            c.execute("UPDATE promo_codes SET used_count=used_count+1 WHERE code=?", (code,))
            c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (pts_given, user.id))
        db_user = get_user(user.id)
        await update.message.reply_text(
            f"🎉 *تم تفعيل الكود بنجاح!*\n\n"
            f"🎟 الكود: `{code}`\n"
            f"✅ حصلت على *{pts_given} نقطة*\n"
            f"💰 رصيدك الآن: {db_user['points']} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )
        context.user_data["state"] = "main_menu"
        return

    # ── تمويل قناة: الخطوة 1 — إدخال عدد الأعضاء ──
    if state == "await_fund_member_count":
        fund_type   = context.user_data.get("fund_type", "mandatory")
        cost_key    = "mandatory_channel_cost" if fund_type == "mandatory" else "internal_channel_cost"
        cost_per    = int(get_setting(cost_key) or "200")
        min_key     = "mandatory_channel_min_members" if fund_type == "mandatory" else "internal_channel_min_members"
        min_members = int(get_setting(min_key) or "0")
        db_user     = get_user(user.id)
        try:
            member_count = int(text.strip().replace(",", "").replace(".", ""))
            if member_count <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً يمثل عدد أعضاء قناتك.")
            return
        if min_members > 0 and member_count < min_members:
            await update.message.reply_text(
                f"❌ *عدد الأعضاء غير كافٍ!*\n\n"
                f"الحد الأدنى المطلوب: *{min_members:,} عضو*\n"
                f"العدد الذي أدخلته: {member_count:,}\n\n"
                f"يجب أن تمتلك قناة بعدد أعضاء لا يقل عن الحد الأدنى.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_kb("fund_channel")
            )
            context.user_data["state"] = "main_menu"
            return
        total_cost = cost_per * member_count
        if (db_user["points"] if db_user else 0) < total_cost:
            await update.message.reply_text(
                f"❌ *نقاطك غير كافية!*\n\n"
                f"💰 السعر: {cost_per} × {member_count:,} = *{total_cost:,} نقطة*\n"
                f"💎 رصيدك الحالي: {db_user['points'] if db_user else 0} نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_kb("fund_channel")
            )
            context.user_data["state"] = "main_menu"
            return
        context.user_data["fund_member_count"] = member_count
        context.user_data["fund_total_cost"]   = total_cost
        context.user_data["state"] = "await_fund_channel"
        await update.message.reply_text(
            f"✅ *عدد الأعضاء: {member_count:,}*\n"
            f"💰 التكلفة الإجمالية: {cost_per} × {member_count:,} = *{total_cost:,} نقطة*\n\n"
            f"📊 *الخطوة 2/3:* أرسل *رابط أو يوزرنيم قناتك* (مثال: @mychannel):",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ── تمويل قناة: الخطوة 2 — إدخال رابط القناة ──
    if state == "await_fund_channel":
        fund_type    = context.user_data.get("fund_type", "mandatory")
        cost_key     = "mandatory_channel_cost" if fund_type == "mandatory" else "internal_channel_cost"
        cost_per     = int(get_setting(cost_key) or "200")
        min_key      = "mandatory_channel_min_members" if fund_type == "mandatory" else "internal_channel_min_members"
        min_members  = int(get_setting(min_key) or "0")
        member_count = context.user_data.get("fund_member_count", 0)
        cost         = context.user_data.get("fund_total_cost", cost_per * max(member_count, 1))
        db_user      = get_user(user.id)
        if (db_user["points"] if db_user else 0) < cost:
            await update.message.reply_text(
                f"❌ نقاطك غير كافية. التكلفة الإجمالية: {cost:,} نقطة.",
                reply_markup=main_menu_kb(is_own)
            )
            context.user_data["state"] = "main_menu"
            return
        channel = text.strip().lstrip("@").split("/")[-1]
        channel_id = f"@{channel}"

        # ── التحقق من أن البوت مشرف في القناة ──
        try:
            bot_member = await context.bot.get_chat_member(channel_id, context.bot.id)
            is_admin = bot_member.status in ("administrator", "creator")
        except Exception as e:
            err = str(e).lower()
            if "chat not found" in err or "invalid" in err:
                await update.message.reply_text(
                    f"⚠️ *القناة @{channel} غير موجودة أو الرابط خاطئ.*\n\n"
                    f"تأكد من اسم القناة وأعد الإرسال:",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    f"⚠️ *البوت ليس مشرفاً في @{channel}*\n\n"
                    f"📋 *خطوات الإضافة:*\n"
                    f"1️⃣ افتح إعدادات القناة/الكروب\n"
                    f"2️⃣ اذهب إلى *المشرفون*\n"
                    f"3️⃣ أضف البوت كمشرف\n"
                    f"4️⃣ أعد إرسال اسم القناة هنا",
                    parse_mode=ParseMode.MARKDOWN
                )
            return

        if not is_admin:
            await update.message.reply_text(
                f"❌ *البوت ليس مشرفاً في @{channel}*\n\n"
                f"📋 *خطوات الإضافة:*\n"
                f"1️⃣ افتح إعدادات القناة/الكروب\n"
                f"2️⃣ اذهب إلى *المشرفون*\n"
                f"3️⃣ أضف البوت كمشرف\n"
                f"4️⃣ أعد إرسال اسم القناة هنا",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # ── التحقق من عدد الأعضاء الفعلي ──
        try:
            real_count = await context.bot.get_chat_member_count(channel_id)
        except Exception:
            real_count = 0

        if min_members > 0 and real_count < min_members:
            await update.message.reply_text(
                f"❌ *عدد الأعضاء الفعلي غير كافٍ!*\n\n"
                f"📢 القناة: @{channel}\n"
                f"👥 العدد الفعلي: {real_count:,} عضو\n"
                f"📌 الحد الأدنى المطلوب: {min_members:,} عضو\n\n"
                f"عزّز قناتك أولاً ثم حاول مجدداً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_kb("fund_channel")
            )
            context.user_data["state"] = "main_menu"
            return

        # ── عرض التأكيد ──
        ft_label = "إجباري سريع" if fund_type == "mandatory" else "داخلي بطيء"
        context.user_data["fund_channel_username"] = channel
        context.user_data["state"] = "await_fund_confirm"
        await update.message.reply_text(
            f"📋 *مراجعة طلب التمويل — الخطوة 3/3:*\n\n"
            f"📢 القناة: @{channel}\n"
            f"⚙️ النوع: {ft_label}\n"
            f"👥 عدد الأعضاء الفعلي: {real_count:,}\n"
            f"💰 التكلفة: {cost_per} × {member_count:,} = *{cost:,} نقطة*\n\n"
            f"هل تريد تأكيد الطلب؟",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأكيد", callback_data="fund_confirm:yes"),
                 InlineKeyboardButton("❌ إلغاء", callback_data="fund_confirm:no")]
            ])
        )
        return

    # ── إعدادات المالك: الحد الأدنى للأعضاء ──
    if is_own and state == "os_await_mandatory_min":
        try:
            val = int(text.strip())
            if val < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً (0 = بدون حد أدنى).")
            return
        set_setting("mandatory_channel_min_members", str(val))
        await update.message.reply_text(
            f"✅ تم تحديث الحد الأدنى للتمويل الإجباري إلى: {val:,} عضو",
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_internal_min":
        try:
            val = int(text.strip())
            if val < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً (0 = بدون حد أدنى).")
            return
        set_setting("internal_channel_min_members", str(val))
        await update.message.reply_text(
            f"✅ تم تحديث الحد الأدنى للتمويل الداخلي إلى: {val:,} عضو",
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    # ── إعدادات المالك: إضافة خدمة ──
    if is_own and state == "os_await_api_id":
        try:
            api_id = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        panel = context.user_data.get("new_svc_panel", 1)
        info = smm_service_info(api_id, panel=panel)
        if not info:
            site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
            await update.message.reply_text(f"⚠️ لم يتم العثور على الخدمة في موقع {site_name}. تأكد من الرقم.")
            return
        context.user_data["new_svc_api_id"] = api_id
        context.user_data["new_svc_info"]   = info
        mn  = info.get("min", 0)
        mx  = info.get("max", 0)
        pr  = info.get("rate", 0)
        dsc = info.get("name", "")
        await update.message.reply_text(
            f"📋 *معلومات الخدمة من الموقع:*\n\n"
            f"📌 الاسم: {dsc}\n"
            f"📝 الوصف: {info.get('type','')}\n"
            f"📉 الحد الأدنى: {mn}\n"
            f"📈 الحد الأعلى: {mx}\n"
            f"💵 السعر: {pr}$ لكل 1000\n\n"
            f"الآن أرسل *اسم الخدمة بالعربية:*",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data["state"] = "os_await_name_ar"
        return

    if is_own and state == "os_await_name_ar":
        context.user_data["new_svc_name"] = text
        await update.message.reply_text(
            f"✅ الاسم: *{text}*\n\n📝 أرسل *وصف الخدمة* (سيظهر للمستخدم في تفاصيل الطلب):",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data["state"] = "os_await_custom_desc"
        return

    if is_own and state == "os_await_custom_desc":
        context.user_data["new_svc_desc"] = text
        info = context.user_data.get("new_svc_info", {})
        mn   = info.get("min", 0)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ استخدم ({mn})", callback_data=f"os_use_min:{mn}")]
        ])
        await update.message.reply_text(
            f"✅ الوصف حُفظ.\n\n📉 *الحد الأدنى من الموقع: {mn}*\n\nاضغط الزر لاستخدامه أو أرسل رقماً مختلفاً:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        context.user_data["state"] = "os_await_min"
        return

    if is_own and state == "os_await_min":
        try:
            mn = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        context.user_data["new_svc_min"] = mn
        info = context.user_data.get("new_svc_info", {})
        mx   = info.get("max", 0)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ استخدم ({mx})", callback_data=f"os_use_max:{mx}")]
        ])
        await update.message.reply_text(
            f"📈 *الحد الأعلى من الموقع: {mx}*\n\nاضغط الزر لاستخدامه أو أرسل رقماً مختلفاً:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        context.user_data["state"] = "os_await_max"
        return

    if is_own and state == "os_await_max":
        try:
            mx = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        context.user_data["new_svc_max"] = mx
        info = context.user_data.get("new_svc_info", {})
        rate = float(info.get("rate", 0))
        # كل سنت = 1000 نقطة → كل دولار = 100000 نقطة
        # السعر لكل 1000 وحدة = rate * 100000 نقطة
        suggested = round(rate * 100000, 1)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ استخدم ({suggested} نقطة/1000 وحدة)", callback_data=f"os_use_price:{suggested}")]
        ])
        await update.message.reply_text(
            f"💰 *السعر المقترح: {suggested} نقطة لكل 1000 وحدة*\n"
            f"_(محسوب: {rate}$ × 100000 = {suggested} نقطة/1000 وحدة)_\n\n"
            f"اضغط الزر لاستخدامه أو أرسل رقماً مختلفاً:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        context.user_data["state"] = "os_await_price"
        return

    if is_own and state == "os_await_price":
        try:
            price = float(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        await _save_service(update, context, price)
        return

    if is_own and state == "os_await_gift_val":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        set_setting("daily_gift_points", str(val))
        await update.message.reply_text(f"✅ تم تحديث الهدية اليومية إلى {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_referral_val":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        set_setting("referral_points", str(val))
        await update.message.reply_text(f"✅ تم تحديث نقاط الدعوة إلى {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_star_rate":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        set_setting("star_to_points", str(val))
        await update.message.reply_text(f"✅ سعر النجمة (شحن) = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_exchange_rate":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        set_setting("exchange_star_rate", str(val))
        await update.message.reply_text(f"✅ سعر نجمة الجوائز = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_exchange_msg":
        set_setting("exchange_success_msg", text.strip())
        await update.message.reply_text(
            "✅ تم حفظ الرسالة. ستظهر لكل مستخدم عند إتمام عملية استبدال، متبوعة بكود عمليته.",
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_join_reward":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("join_channel_reward", str(val))
        await update.message.reply_text(f"✅ نقاط الانضمام للقنوات = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_leave_penalty":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("channel_leave_penalty", str(val))
        await update.message.reply_text(f"✅ خصم مغادرة القناة = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_mandatory_cost":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("mandatory_channel_cost", str(val))
        await update.message.reply_text(f"✅ سعر تمويل القناة الإجباري = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_internal_cost":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("internal_channel_cost", str(val))
        await update.message.reply_text(f"✅ سعر تمويل القناة الداخلي = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_number_cost":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        set_setting("telegram_number_cost", str(val))
        await update.message.reply_text(f"✅ سعر رقم تيلغرام = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_welcome":
        set_setting("welcome_message", text)
        await update.message.reply_text("✅ تم تحديث رسالة الترحيب.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_contact":
        if text.strip().lower() == "حذف":
            set_setting("owner_contact", "")
            await update.message.reply_text("✅ تم حذف رابط تواصل المالك.", reply_markup=owner_settings_kb())
        elif text.strip().startswith("https://t.me/") or text.strip().startswith("https://"):
            set_setting("owner_contact", text.strip())
            await update.message.reply_text(f"✅ تم حفظ رابط التواصل:\n{text.strip()}", reply_markup=owner_settings_kb())
        else:
            await update.message.reply_text(
                "⚠️ الرابط غير صحيح. يجب أن يبدأ بـ `https://t.me/` مثال:\n`https://t.me/username`\n\nأو أرسل *حذف* لإزالة الرابط.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_contact_label":
        new_label = text.strip()
        if not new_label:
            await update.message.reply_text("⚠️ النص لا يمكن أن يكون فارغاً.")
            return
        set_setting("owner_contact_label", new_label)
        await update.message.reply_text(
            f"✅ تم تحديث نص زر التواصل (بعد الخصم) إلى:\n{new_label}",
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_support_label":
        new_label = text.strip()
        if not new_label:
            await update.message.reply_text("⚠️ النص لا يمكن أن يكون فارغاً.")
            return
        set_setting("support_contact_label", new_label)
        await update.message.reply_text(
            f"✅ تم تحديث نص زر الدعم إلى:\n{new_label}",
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    # ── إضافة جائزة مخصصة: الاسم ──
    if is_own and state == "os_await_prize_name":
        name = text.strip()
        if not name:
            await update.message.reply_text("⚠️ الاسم لا يمكن أن يكون فارغاً، أعد الإرسال.")
            return
        context.user_data["prize_name"] = name
        context.user_data["state"] = "os_await_prize_qty"
        await update.message.reply_text(
            f"🎀 *الجائزة:* {name}\n\n"
            f"الخطوة 1.5/2 — أرسل *العدد* لكل طلب (مثال: `1`) أو اضغط تخطي:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭ تخطي (العدد = 1)", callback_data="os:skip_prize_qty")]
            ])
        )
        return

    # ── إضافة جائزة مخصصة: العدد ──
    if is_own and state == "os_await_prize_qty":
        try:
            qty = int(text.strip().replace(",", ""))
            if qty <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً موجباً أو اضغط تخطي.")
            return
        context.user_data["prize_qty"] = qty
        context.user_data["state"] = "os_await_prize_cost"
        await update.message.reply_text(
            f"🎀 *الجائزة:* {context.user_data['prize_name']} × {qty}\n\n"
            f"الخطوة 2/2 — أرسل *عدد النقاط* اللازمة للحصول عليها:\n"
            f"مثال: `1000`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ── إضافة جائزة مخصصة: التكلفة ──
    if is_own and state == "os_await_prize_cost":
        try:
            cost = int(text.strip().replace(",", ""))
            if cost <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً موجباً.")
            return
        name = context.user_data.get("prize_name", "")
        qty  = context.user_data.get("prize_qty", 1)
        qty_txt = f" × {qty}" if qty > 1 else ""
        with db_conn() as c:
            c.execute(
                "INSERT INTO custom_prizes (name, quantity, points_cost, active) VALUES (%s, %s, %s, 1)",
                (name, qty, cost)
            )
        context.user_data.pop("prize_name", None)
        context.user_data.pop("prize_qty", None)
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(
            f"✅ *تمت إضافة الجائزة بنجاح!*\n\n"
            f"🎀 الاسم: {name}{qty_txt}\n"
            f"💰 التكلفة: {cost:,} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    if is_own and state == "os_await_asiacell_text":
        set_setting("asiacell_text", text)
        await update.message.reply_text("✅ تم تحديث نص اسيا سيل.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_order_lookup":
        code = text.strip()
        with db_conn() as c:
            o = c.execute(
                """SELECT o.*, u.full_name AS u_full_name, u.username AS u_username,
                          s.name_ar AS s_name_ar, s.category AS s_category
                   FROM orders o
                   LEFT JOIN users u ON u.user_id = o.user_id
                   LEFT JOIN services s ON s.id = o.service_id
                   WHERE o.order_code=?""",
                (code,)
            ).fetchone()
        context.user_data["state"] = "main_menu"
        if not o:
            await update.message.reply_text("⚠️ كود الطلب غير موجود.", reply_markup=owner_settings_kb())
            return
        await update.message.reply_text(
            _render_order_block(dict(o)),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    if is_own and state == "os_await_cancel_order":
        code = text.strip()
        with db_conn() as c:
            order = c.execute("SELECT * FROM orders WHERE order_code=?", (code,)).fetchone()
        if not order:
            await update.message.reply_text("⚠️ كود الطلب غير موجود.")
            context.user_data["state"] = "main_menu"
            return
        context.user_data["cancel_order"] = dict(order)
        context.user_data["state"] = "confirm_cancel_order"
        await update.message.reply_text(
            f"⚠️ *تأكيد إلغاء الطلب:*\n\n"
            f"📌 الكود: {code}\n"
            f"👤 المستخدم ID: {order['user_id']}\n"
            f"💰 التكلفة: {order['cost_points']} نقطة\n\n"
            f"أرسل *نعم* للإلغاء وإعادة الرصيد أو *لا* للتراجع",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if is_own and state == "confirm_cancel_order":
        if text == "نعم":
            order  = context.user_data.get("cancel_order", {})
            uid    = order.get("user_id")
            pts    = order.get("cost_points", 0)
            o_code = order.get("order_code")
            with db_conn() as c:
                c.execute("UPDATE orders SET status='cancelled' WHERE order_code=?", (o_code,))
            if pts:
                add_points(uid, pts)
            await update.message.reply_text(
                f"✅ تم إلغاء الطلب {o_code} وإعادة {pts} نقطة للمستخدم.",
                reply_markup=owner_settings_kb()
            )
            try:
                await context.bot.send_message(
                    uid,
                    f"🔴 تم إلغاء طلبك بكود {o_code} وإعادة {pts} نقطة لرصيدك.\n\n"
                    f"⚠️ يرجى التأكد من إرسال رابط صحيح ومطابق لنوع الخدمة المطلوبة (رابط الحساب/المنشور/القناة الصحيح) عند إعادة إرسال الطلب."
                )
            except Exception:
                pass
        else:
            await update.message.reply_text("❌ تم التراجع.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_complete_order":
        code = text.strip()
        with db_conn() as c:
            order = c.execute("SELECT * FROM orders WHERE order_code=?", (code,)).fetchone()
        if not order:
            await update.message.reply_text("⚠️ كود الطلب غير موجود.", reply_markup=owner_settings_kb())
            context.user_data["state"] = "main_menu"
            return
        context.user_data["complete_order"] = dict(order)
        context.user_data["state"] = "confirm_complete_order"
        await update.message.reply_text(
            f"✅ *تأكيد إكمال الطلب:*\n\n"
            f"📌 الكود: {code}\n"
            f"👤 المستخدم ID: {order['user_id']}\n\n"
            f"أرسل *نعم* لتأكيد الإكمال وإشعار المستخدم أو *لا* للتراجع",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if is_own and state == "confirm_complete_order":
        if text == "نعم":
            order  = context.user_data.get("complete_order", {})
            uid    = order.get("user_id")
            o_code = order.get("order_code")
            with db_conn() as c:
                c.execute("UPDATE orders SET status='completed' WHERE order_code=?", (o_code,))
            await update.message.reply_text(
                f"✅ تم تحديد الطلب {o_code} كمكتمل وإشعار المستخدم.",
                reply_markup=owner_settings_kb()
            )
            try:
                await context.bot.send_message(
                    uid,
                    f"🎉 تم اكتمال طلبك بكود {o_code} بنجاح!\nنتمنى أن تكون راضياً عن الخدمة 🌟"
                )
            except Exception:
                pass
        else:
            await update.message.reply_text("❌ تم التراجع.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_channel":
        channel = text.lstrip("@")
        with db_conn() as c:
            c.execute("INSERT INTO mandatory_channels (channel_username,funding_type) VALUES (%s,'mandatory') ON CONFLICT DO NOTHING", (channel,))
        await update.message.reply_text(f"✅ تمت إضافة @{channel} كقناة اشتراك إجبارية.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    # ── إنشاء كود ترويجي ──
    if is_own and state == "os_await_promo_code_text":
        code = text.strip().upper()
        if len(code) < 3:
            await update.message.reply_text("⚠️ الكود يجب أن يكون 3 أحرف على الأقل.")
            return
        with db_conn() as c:
            existing = c.execute("SELECT 1 FROM promo_codes WHERE code=?", (code,)).fetchone()
        if existing:
            await update.message.reply_text("⚠️ هذا الكود موجود مسبقاً. أرسل كوداً آخر.")
            return
        context.user_data["new_promo_code"] = code
        context.user_data["state"] = "os_await_promo_uses"
        await update.message.reply_text(f"✅ الكود: `{code}`\n\nكم عدد المستخدمين الذين يمكنهم استخدامه؟",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    if is_own and state == "os_await_promo_uses":
        try:
            uses = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        if uses <= 0:
            await update.message.reply_text("⚠️ يجب أن يكون أكبر من صفر.")
            return
        context.user_data["new_promo_uses"] = uses
        context.user_data["state"] = "os_await_promo_points"
        await update.message.reply_text(f"✅ الحد الأقصى: {uses} مستخدم\n\nكم عدد النقاط لكل مستخدم؟")
        return

    if is_own and state == "os_await_promo_points":
        try:
            pts = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        if pts <= 0:
            await update.message.reply_text("⚠️ يجب أن يكون أكبر من صفر.")
            return
        code  = context.user_data.get("new_promo_code")
        uses  = context.user_data.get("new_promo_uses")
        with db_conn() as c:
            c.execute("INSERT INTO promo_codes (code, max_uses, points) VALUES (?,?,?)", (code, uses, pts))
        await update.message.reply_text(
            f"✅ *تم إنشاء الكود بنجاح!*\n\n"
            f"🎟 الكود: `{code}`\n"
            f"👥 الحد الأقصى: {uses} مستخدم\n"
            f"💰 النقاط لكل مستخدم: {pts}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    # ── رسالة جماعية ──
    if is_own and state == "os_await_broadcast":
        broadcast_text = text
        with db_conn() as c:
            users = c.execute("SELECT user_id FROM users").fetchall()
        sent = 0
        failed = 0
        for u_row in users:
            try:
                await context.bot.send_message(u_row["user_id"], broadcast_text, parse_mode=ParseMode.HTML)
                sent += 1
            except Exception:
                failed += 1
        await update.message.reply_text(
            f"📢 *تم إرسال الرسالة الجماعية*\n\n✅ نجح: {sent}\n❌ فشل: {failed}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    # ── إضافة باقة استبدال نجوم (مالك) ──
    if is_own and state == "os_await_pkg_stars":
        try:
            stars = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        if stars <= 0:
            await update.message.reply_text("⚠️ يجب أن يكون أكبر من صفر.")
            return
        with db_conn() as c:
            c.execute("INSERT INTO exchange_star_packages (stars) VALUES (?)", (stars,))
        rate = int(get_setting("exchange_star_rate") or "2000")
        cost = stars * rate
        await update.message.reply_text(
            f"✅ *تمت إضافة الباقة بنجاح!*\n\n⭐ {stars} نجمة = {cost} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    # ── تعديل خدمة موجودة (مالك) ──
    if is_own and state == "os_edit_await_name":
        sid = context.user_data.get("edit_svc_id")
        with db_conn() as c:
            c.execute("UPDATE services SET name_ar=? WHERE id=?", (text, sid))
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(f"✅ تم تحديث اسم الخدمة إلى: *{text}*", parse_mode=ParseMode.MARKDOWN,
                                         reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_edit_await_min":
        try:
            mn = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        sid = context.user_data.get("edit_svc_id")
        with db_conn() as c:
            c.execute("UPDATE services SET min_qty=? WHERE id=?", (mn, sid))
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(f"✅ تم تحديث الحد الأدنى إلى: {mn}", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_edit_await_max":
        try:
            mx = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        sid = context.user_data.get("edit_svc_id")
        with db_conn() as c:
            c.execute("UPDATE services SET max_qty=? WHERE id=?", (mx, sid))
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(f"✅ تم تحديث الحد الأعلى إلى: {mx}", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_edit_await_price":
        try:
            price = float(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        sid = context.user_data.get("edit_svc_id")
        with db_conn() as c:
            c.execute("UPDATE services SET price_per_point=? WHERE id=?", (price, sid))
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(f"✅ تم تحديث السعر إلى: {fmt_price(price)} نقطة/1000 وحدة", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_edit_await_desc":
        sid = context.user_data.get("edit_svc_id")
        new_desc = None if text.strip() == "-" else text.strip()
        with db_conn() as c:
            c.execute("UPDATE services SET description=? WHERE id=?", (new_desc, sid))
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(
            "✅ تم حذف الوصف." if new_desc is None else f"✅ تم تحديث الوصف إلى:\n{new_desc}",
            reply_markup=owner_settings_kb()
        )
        return

    if is_own and state == "os_edit_await_apiid":
        try:
            api_id = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً.")
            return
        sid   = context.user_data.get("edit_svc_id")
        panel = context.user_data.get("edit_svc_panel", 1)
        info = smm_service_info(api_id, panel=panel)
        if not info:
            site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
            await update.message.reply_text(f"⚠️ لم يتم العثور على الخدمة في موقع {site_name}. تأكد من الرقم.")
            return
        with db_conn() as c:
            c.execute("UPDATE services SET api_service_id=?, panel=? WHERE id=?", (api_id, panel, sid))
        context.user_data["state"] = "main_menu"
        site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
        await update.message.reply_text(
            f"✅ تم ربط الخدمة برقم *{api_id}* من موقع {site_name}.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    # إذا لا يوجد حالة معروفة، عرض القائمة
    await update.message.reply_text("🏠 القائمة الرئيسية:", reply_markup=main_menu_kb(is_own))


async def _save_service(update, context, price: float):
    """حفظ الخدمة الجديدة بعد تحديد جميع القيم"""
    cat    = context.user_data.get("new_svc_cat", "followers")
    api_id = context.user_data.get("new_svc_api_id")
    panel  = context.user_data.get("new_svc_panel", 1)
    name   = context.user_data.get("new_svc_name")
    mn     = context.user_data.get("new_svc_min", 0)
    mx     = context.user_data.get("new_svc_max", 0)
    desc   = context.user_data.get("new_svc_desc", "")
    with db_conn() as c:
        c.execute(
            "INSERT INTO services (category,api_service_id,panel,name_ar,description,min_qty,max_qty,price_per_point) VALUES (?,?,?,?,?,?,?,?)",
            (cat, api_id, panel, name, desc, mn, mx, price)
        )
    site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
    await update.message.reply_text(
        f"✅ تمت إضافة الخدمة *'{name}'* بنجاح!\n\n"
        f"🌐 الموقع: {site_name}\n"
        f"📉 الحد الأدنى: {mn}\n"
        f"📈 الحد الأعلى: {mx}\n"
        f"💰 السعر: {fmt_price(price)} نقطة/1000 وحدة",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=owner_settings_kb()
    )
    context.user_data["state"] = "main_menu"


# ────────────────────────────────────────────────────────────
#  معالج Callback
# ────────────────────────────────────────────────────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query
    # ملاحظة: لا نستدعي q.answer() هنا بدون محتوى — تيليجرام يسمح بالرد على
    # الـ callback_query مرة واحدة فقط. كل فرع أدناه يستدعي q.answer() بنفسه
    # عند الحاجة (فارغاً أو مع تنبيه). استدعاؤه هنا مسبقاً كان يجعل أي استدعاء
    # لاحق يفشل بخطأ "query is too old ... cannot answer it more than once"،
    # فيتوقف تنفيذ الفرع قبل تحديث الرسالة (مثال: الهدية اليومية كانت تُضاف
    # في قاعدة البيانات لكن الرسالة/التنبيه لا يظهران للمستخدم إطلاقاً).
    data   = q.data
    user   = q.from_user
    is_own = (user.id == OWNER_ID)

    # ── فرض الاشتراك الإجباري على جميع المستخدمين المتحققين (الاشتراك مقدس) ──
    _GATE_EXEMPT = {"check_mandatory_join", "noop", "main_menu"}
    if not is_own and data not in _GATE_EXEMPT and not data.startswith("join_verify:"):
        _db_user = get_user(user.id)
        if _db_user and _db_user.get("verified", 0):
            _unjoined = await get_unjoined_mandatory_channels(context, user.id)
            if _unjoined:
                await q.edit_message_text(
                    "📢 *يجب عليك الاشتراك بالقنوات الجديدة أولاً للمتابعة:*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=mandatory_join_kb(_unjoined)
                )
                context.user_data["state"] = "await_mandatory_join"
                return

    # ── القائمة الرئيسية ──
    if data == "main_menu":
        context.user_data["state"] = "main_menu"
        db_user = get_user(user.id)
        pts = db_user["points"] if db_user else 0
        await q.edit_message_text(
            f"🏠 *القائمة الرئيسية*\n💰 رصيدك: {pts} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )
        return

    # ── فئات الخدمات ──
    if data.startswith("cat:"):
        cat = data.split(":")[1]
        await show_category_services(update, context, cat)
        return

    # ── زر نصي مخصص أضافه المالك (يعرض نص فقط) ──
    if data.startswith("mi_text:"):
        mi_id = int(data.split(":")[1])
        with db_conn() as c:
            item = c.execute("SELECT * FROM menu_items WHERE id=?", (mi_id,)).fetchone()
        if item:
            await q.answer(item["action_value"] or "", show_alert=True)
        return

    # ── عرض خدمة بعينها ──
    if data.startswith("svc:"):
        svc_id = int(data.split(":")[1])
        with db_conn() as c:
            svc = c.execute("SELECT * FROM services WHERE id=?", (svc_id,)).fetchone()
        if not svc:
            await q.edit_message_text("⚠️ الخدمة غير موجودة.", reply_markup=back_kb())
            return
        cat = svc["category"]
        context.user_data["smm_svc_db_id"] = svc_id
        context.user_data["smm_svc"] = dict(svc)
        context.user_data["smm_cat"] = cat
        context.user_data["state"] = "await_smm_qty"
        await q.edit_message_text(
            f"🔹 *{svc['name_ar']}*\n\n"
            f"📉 الحد الأدنى: {svc['min_qty']}\n"
            f"📈 الحد الأعلى: {svc['max_qty']}\n"
            f"💰 السعر: {fmt_price(svc['price_per_point'])} نقطة / 1000 وحدة\n\n"
            f"🔢 أرسل *الكمية* المطلوبة:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data=f"cat:{cat}")]
            ])
        )
        return

    # ── رجوع داخل مسار SMM ──
    if data == "smm_back:qty":
        # رجوع لخطوة الكمية — أعد عرض بطاقة الخدمة
        svc = context.user_data.get("smm_svc", {})
        if not svc:
            await q.edit_message_text("⚠️ انتهت الجلسة. ابدأ من جديد.", reply_markup=main_menu_kb(is_own))
            return
        cat = context.user_data.get("smm_cat", svc.get("category", ""))
        context.user_data["state"] = "await_smm_qty"
        await q.edit_message_text(
            f"🔹 *{svc['name_ar']}*\n\n"
            f"📉 الحد الأدنى: {svc['min_qty']}\n"
            f"📈 الحد الأعلى: {svc['max_qty']}\n"
            f"💰 السعر: {fmt_price(svc['price_per_point'])} نقطة / 1000 وحدة\n\n"
            f"🔢 أرسل *الكمية* المطلوبة:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data=f"cat:{cat}")]
            ])
        )
        return

    if data == "smm_back:link":
        # رجوع لخطوة الرابط — أعد عرض طلب الرابط مع الكمية المحفوظة
        svc  = context.user_data.get("smm_svc", {})
        qty  = context.user_data.get("smm_qty", 0)
        cost = context.user_data.get("smm_cost", 0)
        if not svc:
            await q.edit_message_text("⚠️ انتهت الجلسة. ابدأ من جديد.", reply_markup=main_menu_kb(is_own))
            return
        context.user_data["state"] = "await_smm_link"
        await q.edit_message_text(
            f"✅ الكمية: {qty} | التكلفة: {cost} نقطة\n\n"
            f"📎 أرسل *رابط* الحساب/القناة/البوست:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع (تغيير الكمية)", callback_data="smm_back:qty")]
            ])
        )
        return

    # ── تأكيد الطلب (أزرار) ──
    if data.startswith("confirm_order:"):
        action = data.split(":")[1]
        if context.user_data.get("state") != "confirm_smm":
            await q.edit_message_text("⚠️ انتهت صلاحية هذا الطلب. ابدأ من جديد.", reply_markup=main_menu_kb(is_own))
            return
        if action == "yes":
            svc  = context.user_data.get("smm_svc", {})
            qty  = context.user_data.get("smm_qty", 0)
            cost = context.user_data.get("smm_cost", 0)
            link = context.user_data.get("smm_link", "")
            if not deduct_points(user.id, cost):
                await q.edit_message_text("❌ نقاطك غير كافية.", reply_markup=main_menu_kb(is_own))
                context.user_data["state"] = "main_menu"
                return
            api_res = smm_create_order(svc["api_service_id"], link, qty, panel=svc.get("panel", 1))
            if "error" in api_res or not api_res.get("order"):
                add_points(user.id, cost)
                err_msg = api_res.get("error", "خطأ غير معروف من الموقع")
                await q.edit_message_text(
                    f"❌ فشل الطلب: {err_msg}\nتمت إعادة نقاطك.\n\n"
                    f"⚠️ يرجى التأكد من إرسال رابط صحيح ومطابق لنوع الخدمة المطلوبة، ثم أعد إرسال الطلب.",
                    reply_markup=main_menu_kb(is_own)
                )
                context.user_data["state"] = "main_menu"
                return
            api_oid = str(api_res.get("order", ""))
            code    = next_order_code(user.id)
            with db_conn() as c:
                c.execute(
                    "INSERT INTO orders (user_id,service_id,link,quantity,cost_points,api_order_id,order_code) VALUES (?,?,?,?,?,?,?)",
                    (user.id, svc["id"], link, qty, cost, api_oid, code)
                )
            await q.edit_message_text(
                f"✅ *تمت العملية بنجاح!*\n\n"
                f"🔹 الخدمة: {svc['name_ar']}\n"
                f"🔢 الكمية: {qty}\n"
                f"💰 التكلفة: {cost} نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
            await context.bot.send_message(
                user.id,
                f"📌 *كود عمليتك هو:* `{code}`\nاحفظه قد تحتاجه لاحقاً.",
                parse_mode=ParseMode.MARKDOWN
            )
            await notify_group(
                context.application,
                f"🆕 <b>طلب جديد</b>\n"
                f"👤 المستخدم: <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                f"🔹 الخدمة: {svc['name_ar']}\n"
                f"🔗 الرابط: {link}\n"
                f"🔢 الكمية: {qty}\n"
                f"💰 التكلفة: {cost} نقطة\n"
                f"📌 الكود: {code}"
            )
        else:
            await q.edit_message_text("❌ تم إلغاء الطلب.", reply_markup=main_menu_kb(is_own))
        context.user_data["state"] = "main_menu"
        return

    # ── تواصل مع الدعم ──
    if data == "contact_support":
        contact = get_setting("owner_contact") or ""
        if not contact:
            await q.edit_message_text(
                "⚠️ خدمة الدعم غير متاحة حالياً.",
                reply_markup=back_kb()
            )
            return
        label = get_setting("support_contact_label") or "🛎 تواصل مع الدعم"
        await q.edit_message_text(
            "🛎 *تواصل مع الدعم*\n\nاضغط الزر أدناه للتواصل معنا مباشرة:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(label, url=contact)],
                [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]
            ])
        )
        return

    # ── رابط الدعوة ──
    if data == "referral":
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={user.id}"
        rp   = get_setting("referral_points") or "30"
        db_user = get_user(user.id)
        with db_conn() as c:
            invited = c.execute("SELECT COUNT(*) as cnt FROM users WHERE invited_by=?", (user.id,)).fetchone()["cnt"]
        await q.edit_message_text(
            f"🔗 *رابط دعوتك الشخصي:*\n\n`{link}`\n\n"
            f"✅ تحصل على *{rp} نقطة* لكل صديق يدخل عبر رابطك\n"
            f"👥 دعوت حتى الآن: {invited} شخص\n"
            f"💰 رصيدك: {db_user['points'] if db_user else 0} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_kb()
        )
        return

    # ── تجميع نقاط — قائمة فرعية (هدية يومية | انضمام بقنوات) ──
    if data in ("collect_points", "daily_gift", "join_channels_menu"):
        db_user = get_user(user.id)
        rows = [
            [InlineKeyboardButton("🎁 الهدية اليومية", callback_data="daily_gift_screen")],
            [InlineKeyboardButton("📡 الانضمام بقنوات", callback_data="join_channels")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
        ]
        await q.edit_message_text(
            f"💰 *تجميع النقاط*\n\n"
            f"💰 رصيدك الحالي: {db_user['points'] if db_user else 0} نقطة\n\n"
            f"اختر أحد الخيارين للحصول على نقاط:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    # ── شاشة الهدية اليومية ──
    if data == "daily_gift_screen":
        today = str(date.today())
        gift = int(get_setting("daily_gift_points") or "50")
        with db_conn() as c:
            gift_row = c.execute("SELECT last_claim FROM daily_gifts WHERE user_id=%s", (user.id,)).fetchone()
        already_claimed = gift_row and gift_row["last_claim"] == today
        db_user = get_user(user.id)
        if already_claimed:
            btn = [InlineKeyboardButton("⏰ تم استلام هديتك اليوم — عد غداً", callback_data="noop")]
        else:
            btn = [InlineKeyboardButton(f"🎁 استلام الهدية (+{gift} نقطة)", callback_data="daily_gift_collect")]
        rows = [
            btn,
            [InlineKeyboardButton("🔙 رجوع", callback_data="collect_points")],
        ]
        await q.edit_message_text(
            f"🎁 *الهدية اليومية*\n\n"
            f"💰 رصيدك الحالي: {db_user['points'] if db_user else 0} نقطة\n"
            f"🎁 الهدية اليوم: *{gift} نقطة* {'✅ مستلمة بالفعل' if already_claimed else '— متاحة الآن!'}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data == "daily_gift_collect":
        today = str(date.today())
        with db_conn() as c:
            row = c.execute("SELECT last_claim FROM daily_gifts WHERE user_id=%s", (user.id,)).fetchone()
            if row and row["last_claim"] == today:
                await q.answer("⏰ لقد استلمت هديتك اليومية بالفعل! عد غداً.", show_alert=True)
                return
            gift = int(get_setting("daily_gift_points") or "50")
            c.execute(
                "INSERT INTO daily_gifts (user_id, last_claim) VALUES (%s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET last_claim=EXCLUDED.last_claim",
                (user.id, today)
            )
            c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (gift, user.id))
        db_user = get_user(user.id)
        await q.answer(f"🎁 حصلت على {gift} نقطة!", show_alert=True)
        # تحديث شاشة الهدية بعد الاستلام
        rows = [
            [InlineKeyboardButton("⏰ تم استلام هديتك اليوم — عد غداً", callback_data="noop")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="collect_points")],
        ]
        await q.edit_message_text(
            f"🎁 *الهدية اليومية*\n\n"
            f"✅ استلمت *{gift} نقطة* بنجاح!\n"
            f"💰 رصيدك الآن: {db_user['points'] if db_user else 0} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    # ── التحقق من بوابة الاشتراك الإجباري ──
    if data == "check_mandatory_join":
        unjoined = await get_unjoined_mandatory_channels(context, user.id)
        if unjoined:
            await q.answer("❌ لم تشترك بعد بجميع القنوات المطلوبة.", show_alert=True)
            await show_mandatory_gate(update, context, unjoined, edit=True)
            return
        await q.answer("✅ تم التحقق من اشتراكك!")
        db_user = get_user(user.id)
        if db_user and db_user.get("verified", 0):
            # مستخدم متحقق سابقاً اضطُرّ للانضمام لقناة جديدة → عَدّه وأعد القائمة
            await count_user_for_fundings(user.id, context)
            context.user_data["state"] = "main_menu"
            db_user = get_user(user.id)
            pts = db_user["points"] if db_user else 0
            await q.edit_message_text(
                f"✅ *تم التحقق! أهلاً بك مجدداً.*\n\n💰 رصيدك: {pts} نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
        else:
            await proceed_after_mandatory(update, context, edit=True)
        return

    # ── انضمام بقنوات ──
    if data == "join_channels":
        with db_conn() as c:
            channels = c.execute(
                "SELECT * FROM mandatory_channels WHERE active=1 AND funding_type='internal' ORDER BY id"
            ).fetchall()
        if not channels:
            await q.edit_message_text(
                "📡 لا توجد قنوات للانضمام حالياً.",
                reply_markup=back_kb("collect_points")
            )
            return
        reward = int(get_setting("join_channel_reward") or "45")
        db_user = get_user(user.id)
        rows = []
        for ch in channels:
            with db_conn() as c:
                claimed = c.execute(
                    "SELECT 1 FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                    (user.id, ch["id"])
                ).fetchone()
            rows.append([InlineKeyboardButton(
                f"📢 @{ch['channel_username']}",
                url=f"https://t.me/{ch['channel_username']}"
            )])
            if not claimed:
                rows.append([InlineKeyboardButton(
                    f"✅ تحقق من انضمامي (+{reward} نقطة)",
                    callback_data=f"join_verify:{ch['id']}"
                )])
            else:
                rows.append([InlineKeyboardButton("✔️ تم الحصول على نقاطك", callback_data="noop")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="collect_points")])
        await q.edit_message_text(
            f"📡 *الانضمام بقنوات*\n\n"
            f"💰 رصيدك الحالي: {db_user['points'] if db_user else 0} نقطة\n"
            f"🎁 انضم لأي قناة واحصل على *{reward} نقطة*\n"
            f"اضغط ✅ تحقق من انضمامي بعد الانضمام:"
            f"{_leave_penalty_note()}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    # ── التحقق من الانضمام ومنح النقاط (إصلاح: ذري وآمن) ──
    if data.startswith("join_verify:"):
        ch_id = int(data.split(":")[1])
        with db_conn() as c:
            ch = c.execute("SELECT * FROM mandatory_channels WHERE id=%s", (ch_id,)).fetchone()
        if not ch:
            await q.answer("⚠️ القناة غير موجودة.", show_alert=True)
            return
        # تحقق مسبق من الحصول على النقاط
        with db_conn() as c:
            already = c.execute(
                "SELECT 1 FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                (user.id, ch_id)
            ).fetchone()
        if already:
            await q.answer("✔️ لقد حصلت على نقاط هذه القناة سابقاً.", show_alert=True)
            return
        # تحقق من أن المستخدم فعلاً منضم
        try:
            member = await context.bot.get_chat_member(f"@{ch['channel_username']}", user.id)
            is_member = member.status not in ("left", "kicked", "banned")
        except Exception:
            await q.answer("⚠️ تعذّر التحقق. تأكد أنك انضممت ثم حاول.", show_alert=True)
            return
        if not is_member:
            await q.answer("❌ لم تنضم بعد! انضم للقناة أولاً ثم اضغط تحقق.", show_alert=True)
            return
        reward = int(get_setting("join_channel_reward") or "45")
        # إدراج ذري مع فحص التكرار عبر RETURNING
        with db_conn() as c:
            c.execute(
                "INSERT INTO channel_join_rewards (user_id, channel_id) VALUES (%s, %s) "
                "ON CONFLICT (user_id, channel_id) DO NOTHING",
                (user.id, ch_id)
            )
            inserted = c.rowcount
            if inserted > 0:
                c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (reward, user.id))
        if not inserted:
            await q.answer("✔️ لقد حصلت على نقاط هذه القناة سابقاً.", show_alert=True)
            return
        db_user = get_user(user.id)
        await q.answer(f"🎉 حصلت على {reward} نقطة!", show_alert=True)
        # تحديث الشاشة — إعادة بناء القائمة
        with db_conn() as c:
            channels = c.execute(
                "SELECT * FROM mandatory_channels WHERE active=1 AND funding_type='internal' ORDER BY id"
            ).fetchall()
        rows = []
        for ch2 in channels:
            with db_conn() as c:
                claimed = c.execute(
                    "SELECT 1 FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                    (user.id, ch2["id"])
                ).fetchone()
            rows.append([InlineKeyboardButton(
                f"📢 @{ch2['channel_username']}",
                url=f"https://t.me/{ch2['channel_username']}"
            )])
            if not claimed:
                rows.append([InlineKeyboardButton(
                    f"✅ تحقق من انضمامي (+{reward} نقطة)",
                    callback_data=f"join_verify:{ch2['id']}"
                )])
            else:
                rows.append([InlineKeyboardButton("✔️ تم الحصول على نقاطك", callback_data="noop")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="join_channels")])
        await q.edit_message_text(
            f"📡 *الانضمام بقنوات*\n\n"
            f"🎁 انضم لأي قناة واحصل على *{reward} نقطة*\n"
            f"💰 رصيدك الآن: {db_user['points'] if db_user else 0} نقطة"
            f"{_leave_penalty_note()}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    # ── شحن نقاط ──
    if data == "charge_points":
        await q.edit_message_text("💎 *اختر طريقة الشحن:*", parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=charge_points_kb())
        return

    if data == "charge:stars":
        rate = get_setting("star_to_points") or "250"
        await q.edit_message_text(
            f"⭐ *الشحن عبر النجوم*\n\n💡 سعر النجمة الواحدة = {rate} نقطة\n\nاختر الكمية أو الطريقة:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=charge_stars_kb()
        )
        return

    if data == "charge:info":
        await q.answer("هذا مجرد عرض للسعر.", show_alert=False)
        return

    # ── شحن سريع بعدد محدد من النجوم ──
    if data.startswith("charge:quick:"):
        stars = int(data.split(":")[2])
        rate  = int(get_setting("star_to_points") or "250")
        pts   = stars * rate
        await q.edit_message_text(
            f"⭐ *{stars} نجمة = {pts} نقطة*\n\nجارٍ تحضير الفاتورة...",
            parse_mode=ParseMode.MARKDOWN
        )
        await context.bot.send_invoice(
            chat_id=user.id,
            title="شحن نقاط",
            description=f"شراء {pts} نقطة مقابل {stars} نجمة",
            payload=f"charge_stars:{stars}:{user.id}",
            currency="XTR",
            prices=[LabeledPrice("نجوم", stars)],
        )
        return

    if data == "charge:by_points":
        rate = get_setting("star_to_points") or "250"
        context.user_data["state"] = "await_charge_points_amount"
        await q.edit_message_text(
            f"💡 *ملاحظة:* سعر النجمة الواحدة = {rate} نقطة\n\nأرسل عدد النقاط التي تريدها:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "charge:by_stars":
        rate = get_setting("star_to_points") or "250"
        context.user_data["state"] = "await_charge_stars_amount"
        await q.edit_message_text(
            f"💡 *ملاحظة:* سعر النجمة الواحدة = {rate} نقطة\n\nأرسل عدد النجوم المراد شحنها:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "charge:asiacell":
        asiacell_txt = get_setting("asiacell_text") or "⚠️ الشحن التلقائي عبر اسيا سيل غير متاح حالياً.\nيرجى التواصل مع المالك."
        kb_rows = contact_owner_row() + [[InlineKeyboardButton("🔙 رجوع", callback_data="charge_points")]]
        await q.edit_message_text(asiacell_txt, reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    # ── استبدال نقاط ──
    if data == "exchange_points":
        await q.edit_message_text("🏆 *استبدال النقاط بجوائز:*",
                                   parse_mode=ParseMode.MARKDOWN, reply_markup=exchange_kb())
        return

    if data == "exchange:stars":
        rate = int(get_setting("exchange_star_rate") or "2000")
        with db_conn() as c:
            packages = c.execute("SELECT * FROM exchange_star_packages WHERE active=1 ORDER BY stars").fetchall()
        if not packages:
            kb_rows = contact_owner_row() + [[InlineKeyboardButton("🔙 رجوع", callback_data="exchange_points")]]
            await q.edit_message_text(
                "⚠️ لا توجد باقات استبدال متاحة حالياً.\nتواصل مع المالك لإضافة باقات.",
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
            return
        rows = []
        for pkg in packages:
            stars = pkg["stars"]
            cost = stars * rate
            rows.append([InlineKeyboardButton(f"⭐ {stars} نجمة = {cost} نقطة", callback_data=f"exchange:pkg:{stars}")])
        rows += contact_owner_row()
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="exchange_points")])
        await q.edit_message_text(
            f"⭐ *استبدال نقاط بنجوم*\n\n"
            f"💡 سعر النجمة الواحدة: {rate} نقطة\n\n"
            f"اختر الباقة المطلوبة:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data.startswith("exchange:pkg:"):
        stars = int(data.split(":")[2])
        rate = int(get_setting("exchange_star_rate") or "2000")
        cost = stars * rate
        db_user = get_user(user.id)
        pts = db_user["points"] if db_user else 0
        if pts < cost:
            kb_rows = contact_owner_row() + [[InlineKeyboardButton("🔙 رجوع", callback_data="exchange:stars")]]
            await q.edit_message_text(
                f"❌ *نقاطك غير كافية!*\n\n"
                f"⭐ تحتاج: {cost} نقطة\n"
                f"💎 رصيدك: {pts} نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
            return
        if not deduct_points(user.id, cost):
            await q.edit_message_text("❌ حدث خطأ في خصم النقاط.", reply_markup=back_kb("exchange:stars"))
            return
        code = next_order_code(user.id)
        with db_conn() as c:
            c.execute(
                "INSERT INTO prize_exchanges (user_id,prize_type,prize_value,points_cost,status) VALUES (%s,%s,%s,%s,'pending')",
                (user.id, "stars", str(stars), cost)
            )
        custom_msg = get_setting("exchange_success_msg") or ""
        result_kb_rows = contact_owner_row() + [[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]]
        await q.edit_message_text(
            f"✅ *تمت العملية بنجاح!*\n\n"
            f"⭐ طلب {stars} نجمة مسجل\n"
            f"💰 التكلفة: {cost} نقطة\n\n"
            + (f"{custom_msg}\n\n" if custom_msg else "")
            + "سيتواصل معك المالك قريباً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(result_kb_rows)
        )
        await context.bot.send_message(
            user.id,
            f"📌 *كود عمليتك:* `{code}`",
            parse_mode=ParseMode.MARKDOWN
        )
        await notify_group(
            context.application,
            f"⭐ <b>طلب شراء نجوم (جائزة)</b>\n"
            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
            f"⭐ {stars} نجمة مقابل {cost} نقطة\n"
            f"📌 {code}"
        )
        return

    if data == "exchange:number":
        cost = int(get_setting("telegram_number_cost") or "5000")
        db_user = get_user(user.id)
        if db_user["points"] < cost:
            kb_rows = contact_owner_row() + [[InlineKeyboardButton("🔙 رجوع", callback_data="exchange_points")]]
            await q.edit_message_text(
                f"❌ نقاطك غير كافية! تحتاج {cost} نقطة ولديك {db_user['points']} نقطة.",
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
            return
        if not deduct_points(user.id, cost):
            await q.edit_message_text("❌ حدث خطأ في خصم النقاط.", reply_markup=back_kb("exchange_points"))
            return
        code = next_order_code(user.id)
        with db_conn() as c:
            c.execute(
                "INSERT INTO prize_exchanges (user_id,prize_type,prize_value,points_cost,status) VALUES (?,?,?,?,'pending')",
                (user.id, "telegram_number", "number", cost)
            )
        custom_msg = get_setting("exchange_success_msg") or ""
        result_kb = contact_owner_row() + [[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]]
        await q.edit_message_text(
            f"✅ *تمت العملية بنجاح!*\n\n"
            f"📱 طلب رقم تيلغرام مسجل\n"
            f"💰 التكلفة: {cost} نقطة\n\n"
            + (f"{custom_msg}\n\n" if custom_msg else "")
            + "سيتواصل معك المالك قريباً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(result_kb)
        )
        await context.bot.send_message(
            user.id,
            f"📌 *كود عمليتك:* `{code}`",
            parse_mode=ParseMode.MARKDOWN
        )
        await notify_group(
            context.application,
            f"📱 <b>طلب رقم تيلغرام</b>\n"
            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
            f"💰 {cost} نقطة\n"
            f"📌 {code}"
        )
        return

    # ── استخدام كود ترويجي ──
    if data == "use_promo":
        context.user_data["state"] = "await_promo_code"
        await q.edit_message_text(
            "🎟 *استخدام كود ترويجي*\n\nأرسل الكود:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_kb()
        )
        return

    # ── تحويل النقاط ──
    if data == "transfer_points":
        context.user_data["state"] = "await_transfer_id"
        await q.edit_message_text("↔️ *تحويل النقاط*\n\nأرسل ايدي المستلم (رقمي):", parse_mode=ParseMode.MARKDOWN)
        return

    # ── معلوماتي ──
    if data == "my_info":
        db_user = get_user(user.id)
        if not db_user:
            await q.edit_message_text("⚠️ لم يتم العثور على بياناتك. أرسل /start أولاً.")
            return
        with db_conn() as c:
            invited = c.execute("SELECT COUNT(*) as cnt FROM users WHERE invited_by=?", (user.id,)).fetchone()["cnt"]
        await q.edit_message_text(
            f"👤 *معلوماتك:*\n\n"
            f"🆔 معرفك: `{user.id}`\n"
            f"💰 نقاطك: {db_user['points']}\n"
            f"👥 من دعوتهم: {invited} شخص\n"
            f"📦 عدد طلباتك: {db_user['total_orders']}\n"
            f"🔢 رقمك في البوت: #{db_user['bot_user_num']}\n"
            f"📅 تاريخ الانضمام: {db_user['joined_at']}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_kb()
        )
        return

    # ── تمويل القناة ──
    if data == "fund_channel":
        await q.edit_message_text("📺 *تمويل قناتك حقيقي:*", parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=fund_channel_kb())
        return

    if data == "fund:mandatory":
        cost_per = get_setting("mandatory_channel_cost") or "200"
        min_members = get_setting("mandatory_channel_min_members") or "0"
        context.user_data["fund_type"] = "mandatory"
        context.user_data["state"]     = "await_fund_member_count"
        min_txt = f"👥 الحد الأدنى للأعضاء: *{int(min_members):,}*\n" if int(min_members) > 0 else ""
        await q.edit_message_text(
            f"📢 *تمويل قناة إجباري سريع*\n\n"
            f"✅ ستُضاف قناتك كقناة اشتراك إجبارية في البوت\n"
            f"💰 السعر: *{cost_per} نقطة لكل عضو*\n"
            f"{min_txt}\n"
            f"📊 *الخطوة 1/3:* أرسل *عدد أعضاء قناتك* الحالي:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "fund:internal":
        cost_per = get_setting("internal_channel_cost") or "100"
        min_members = get_setting("internal_channel_min_members") or "0"
        context.user_data["fund_type"] = "internal"
        context.user_data["state"]     = "await_fund_member_count"
        min_txt = f"👥 الحد الأدنى للأعضاء: *{int(min_members):,}*\n" if int(min_members) > 0 else ""
        await q.edit_message_text(
            f"🔄 *تمويل قناة داخلي بطيء*\n\n"
            f"✅ ستُضاف قناتك في قسم انضم بقنوات\n"
            f"👥 الأعضاء يجمعون نقاط وينضمون لقناتك\n"
            f"💰 السعر: *{cost_per} نقطة لكل عضو*\n"
            f"{min_txt}\n"
            f"📊 *الخطوة 1/3:* أرسل *عدد أعضاء قناتك* الحالي:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ── تأكيد تمويل القناة ──
    if data == "fund_confirm:yes":
        fund_type    = context.user_data.get("fund_type", "mandatory")
        channel      = context.user_data.get("fund_channel_username", "")
        member_count = context.user_data.get("fund_member_count", 1)
        cost_key     = "mandatory_channel_cost" if fund_type == "mandatory" else "internal_channel_cost"
        cost_per     = int(get_setting(cost_key) or "200")
        cost         = context.user_data.get("fund_total_cost", cost_per * member_count)
        ft_label     = "إجباري سريع" if fund_type == "mandatory" else "داخلي بطيء"
        if not channel:
            await q.edit_message_text("⚠️ انتهت الجلسة، ابدأ من جديد.", reply_markup=main_menu_kb(is_own))
            context.user_data["state"] = "main_menu"
            return
        if not deduct_points(user.id, cost):
            await q.edit_message_text(f"❌ نقاطك غير كافية. التكلفة الإجمالية: {cost:,} نقطة.", reply_markup=main_menu_kb(is_own))
            context.user_data["state"] = "main_menu"
            return
        code = next_order_code(user.id)
        with db_conn() as c:
            c.execute(
                "INSERT INTO channel_funding (user_id,channel_username,funding_type,cost_points,target_members,current_members,status) "
                "VALUES (%s,%s,%s,%s,%s,0,'active')",
                (user.id, channel, fund_type, cost, member_count)
            )
            c.execute(
                "INSERT INTO mandatory_channels (channel_username,owner_user_id,funding_type,active) VALUES (%s,%s,%s,1) "
                "ON CONFLICT (channel_username) DO UPDATE SET funding_type=EXCLUDED.funding_type, owner_user_id=EXCLUDED.owner_user_id, active=1",
                (channel, user.id, fund_type)
            )
        context.user_data["state"] = "main_menu"
        context.user_data.pop("fund_channel_username", None)
        context.user_data.pop("fund_member_count", None)
        context.user_data.pop("fund_total_cost", None)
        await q.edit_message_text(
            f"✅ *تم تفعيل تمويل قناتك بنجاح!*\n\n"
            f"📢 القناة: @{channel}\n"
            f"⚙️ النوع: {ft_label}\n"
            f"👥 عدد الأعضاء: {member_count:,}\n"
            f"💰 التكلفة: {cost_per} × {member_count:,} = *{cost:,} نقطة*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )
        await context.bot.send_message(
            user.id,
            f"📌 *كود عمليتك:* `{code}`\nاحفظه قد تحتاجه لاحقاً.",
            parse_mode=ParseMode.MARKDOWN
        )
        await notify_group(
            context.application,
            f"📢 <b>تمويل قناة {ft_label}</b>\n"
            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
            f"📡 القناة: @{channel}\n"
            f"👥 {member_count:,} عضو\n"
            f"💰 {cost:,} نقطة ({cost_per} × {member_count:,})\n"
            f"📌 {code}"
        )
        return

    if data == "fund_confirm:no":
        context.user_data["state"] = "main_menu"
        context.user_data.pop("fund_channel_username", None)
        context.user_data.pop("fund_member_count", None)
        await q.edit_message_text("❌ تم إلغاء طلب التمويل.", reply_markup=main_menu_kb(is_own))
        return

    # ── إعدادات المالك ──
    if data == "owner_settings" and is_own:
        if context.user_data.get("state", "").startswith("await_mb_"):
            context.user_data["state"] = "main_menu"
            for k in ("mb_menu", "mb_type", "mb_label"):
                context.user_data.pop(k, None)
        await q.edit_message_text("⚙️ *إعدادات المالك:*", parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=owner_settings_kb())
        return

    # ────────────────────────────────────────────────────────
    #  إدارة أزرار القوائم (إضافة/حذف/ترتيب/تحجيم)
    # ────────────────────────────────────────────────────────
    if data == "os:manage_buttons" and is_own:
        if context.user_data.get("state", "").startswith("await_mb_"):
            context.user_data["state"] = "main_menu"
            for k in ("mb_menu", "mb_type", "mb_label"):
                context.user_data.pop(k, None)
        rows = [[InlineKeyboardButton(MENU_LABELS.get(m, m), callback_data=f"mb_menu:{m}")]
                for m in MANAGEABLE_MENUS]
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await q.edit_message_text("🧩 *إدارة الأزرار:*\nاختر القائمة التي تريد التحكم بها:",
                                   parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("mb_menu:") and is_own:
        menu = data.split(":", 1)[1]
        context.user_data.pop("mb_menu", None)
        context.user_data.pop("mb_type", None)
        context.user_data.pop("mb_label", None)
        if context.user_data.get("state", "").startswith("await_mb_"):
            context.user_data["state"] = "main_menu"
        text, kb = render_mb_menu_screen(menu)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return

    if (data.startswith("mb_up:") or data.startswith("mb_down:")) and is_own:
        direction, rest = data.split(":", 1)
        menu, mid = rest.rsplit(":", 1)
        mid = int(mid)
        with db_conn() as c:
            items = c.execute("SELECT id, sort_order FROM menu_items WHERE menu=? ORDER BY sort_order, id", (menu,)).fetchall()
            ids = [r["id"] for r in items]
            idx = ids.index(mid) if mid in ids else -1
            swap_idx = idx - 1 if direction == "mb_up" else idx + 1
            if idx != -1 and 0 <= swap_idx < len(ids):
                other_id = ids[swap_idx]
                orders = {r["id"]: r["sort_order"] for r in items}
                c.execute("UPDATE menu_items SET sort_order=? WHERE id=? AND menu=?", (orders[other_id], mid, menu))
                c.execute("UPDATE menu_items SET sort_order=? WHERE id=? AND menu=?", (orders[mid], other_id, menu))
        text, kb = render_mb_menu_screen(menu)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return

    if data.startswith("mb_width:") and is_own:
        _, rest = data.split(":", 1)
        menu, mid = rest.rsplit(":", 1)
        mid = int(mid)
        with db_conn() as c:
            row = c.execute("SELECT width FROM menu_items WHERE id=? AND menu=?", (mid, menu)).fetchone()
            if row:
                new_width = 1 if row["width"] == 2 else 2
                c.execute("UPDATE menu_items SET width=? WHERE id=? AND menu=?", (new_width, mid, menu))
        await q.answer("✅ تم تغيير الحجم")
        text, kb = render_mb_menu_screen(menu)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return

    if data.startswith("mb_toggle:") and is_own:
        _, rest = data.split(":", 1)
        menu, mid = rest.rsplit(":", 1)
        mid = int(mid)
        with db_conn() as c:
            row = c.execute("SELECT enabled FROM menu_items WHERE id=? AND menu=?", (mid, menu)).fetchone()
            if row:
                new_enabled = 0 if row["enabled"] else 1
                c.execute("UPDATE menu_items SET enabled=? WHERE id=? AND menu=?", (new_enabled, mid, menu))
        await q.answer("✅ تم التحديث")
        text, kb = render_mb_menu_screen(menu)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return

    if data.startswith("mb_add:") and is_own:
        menu = data.split(":", 1)[1]
        context.user_data["mb_menu"] = menu
        rows = [
            [InlineKeyboardButton("🔗 رابط خارجي", callback_data="mb_type:url")],
            [InlineKeyboardButton("💬 نص يظهر عند الضغط", callback_data="mb_type:text")],
            [InlineKeyboardButton("↪️ ربط بقسم موجود بالبوت", callback_data="mb_type:goto")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"mb_menu:{menu}")],
        ]
        await q.edit_message_text("اختر نوع الزر الجديد:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("mb_type:") and is_own:
        mb_type = data.split(":", 1)[1]
        context.user_data["mb_type"] = mb_type
        context.user_data["state"] = "await_mb_label"
        await q.edit_message_text("✏️ أرسل *اسم الزر* الذي سيظهر للمستخدمين:", parse_mode=ParseMode.MARKDOWN)
        return

    if data.startswith("mb_goto_pick:") and is_own:
        target = data.split(":", 1)[1]
        menu = context.user_data.get("mb_menu")
        label = context.user_data.get("mb_label")
        if not (menu and label):
            await q.edit_message_text("⚠️ انتهت الجلسة، ابدأ من جديد.", reply_markup=owner_settings_kb())
            return
        with db_conn() as c:
            max_order = c.execute("SELECT COALESCE(MAX(sort_order),-1) AS m FROM menu_items WHERE menu=?", (menu,)).fetchone()["m"]
            c.execute(
                "INSERT INTO menu_items (menu,label,action_type,action_value,width,sort_order,enabled) VALUES (?,?,?,?,?,?,1)",
                (menu, label, "goto", target, 2, max_order + 1)
            )
        context.user_data["state"] = "main_menu"
        await q.edit_message_text(f"✅ تمت إضافة الزر '{label}'.",
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للإدارة", callback_data=f"mb_menu:{menu}")]]))
        return

    if data == "os:add_service" and is_own:
        cats = list(CATEGORY_MAP.items())
        rows = [[InlineKeyboardButton(v, callback_data=f"os_cat:{k}")] for k, v in cats]
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await q.edit_message_text("اختر الفئة التي تريد إضافة خدمة لها:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("os_cat:") and is_own:
        cat = data.split(":")[1]
        context.user_data["new_svc_cat"] = cat
        rows = [
            [InlineKeyboardButton(f"1️⃣ {PANEL_MAP[1]['name']}", callback_data="os_panel:1")],
            [InlineKeyboardButton(f"2️⃣ {PANEL_MAP[2]['name']}", callback_data="os_panel:2")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="os:add_service")],
        ]
        await q.edit_message_text(
            f"📌 الفئة: {CATEGORY_MAP.get(cat, cat)}\n\nاختر *الموقع* الذي تريد إضافة الخدمة منه:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data.startswith("os_panel:") and is_own:
        panel = int(data.split(":")[1])
        context.user_data["new_svc_panel"] = panel
        context.user_data["state"] = "os_await_api_id"
        site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
        await q.edit_message_text(
            f"🌐 الموقع: {site_name}\n\nأرسل *رقم الخدمة* في هذا الموقع:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ── أزرار inline لاختيار القيم عند إضافة خدمة ──
    if data.startswith("os_use_min:") and is_own:
        mn = int(data.split(":")[1])
        context.user_data["new_svc_min"] = mn
        info = context.user_data.get("new_svc_info", {})
        mx   = info.get("max", 0)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ استخدم ({mx})", callback_data=f"os_use_max:{mx}")]
        ])
        await q.edit_message_text(
            f"✅ الحد الأدنى: {mn}\n\n"
            f"📈 *الحد الأعلى من الموقع: {mx}*\n\nاضغط الزر لاستخدامه أو أرسل رقماً مختلفاً:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        context.user_data["state"] = "os_await_max"
        return

    if data.startswith("os_use_max:") and is_own:
        mx = int(data.split(":")[1])
        context.user_data["new_svc_max"] = mx
        info = context.user_data.get("new_svc_info", {})
        rate = float(info.get("rate", 0))
        suggested = round(rate * 100000, 1)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ استخدم ({suggested} نقطة/1000 وحدة)", callback_data=f"os_use_price:{suggested}")]
        ])
        await q.edit_message_text(
            f"✅ الحد الأعلى: {mx}\n\n"
            f"💰 *السعر المقترح: {suggested} نقطة/1000 وحدة*\n"
            f"_(محسوب: {rate}$ × 100)_\n\n"
            f"اضغط الزر لاستخدامه أو أرسل رقماً مختلفاً:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        context.user_data["state"] = "os_await_price"
        return

    if data.startswith("os_use_price:") and is_own:
        price = float(data.split(":")[1])
        context.user_data["state"] = "main_menu"
        # نحتاج update.message لكن هنا callback — نرسل رسالة جديدة
        cat    = context.user_data.get("new_svc_cat", "followers")
        api_id = context.user_data.get("new_svc_api_id")
        panel  = context.user_data.get("new_svc_panel", 1)
        name   = context.user_data.get("new_svc_name")
        mn     = context.user_data.get("new_svc_min", 0)
        mx_val = context.user_data.get("new_svc_max", 0)
        desc   = context.user_data.get("new_svc_desc", "")
        with db_conn() as c:
            c.execute(
                "INSERT INTO services (category,api_service_id,panel,name_ar,description,min_qty,max_qty,price_per_point) VALUES (?,?,?,?,?,?,?,?)",
                (cat, api_id, panel, name, desc, mn, mx_val, price)
            )
        site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
        await q.edit_message_text(
            f"✅ تمت إضافة الخدمة *'{name}'* بنجاح!\n\n"
            f"🌐 الموقع: {site_name}\n"
            f"📉 الحد الأدنى: {mn}\n"
            f"📈 الحد الأعلى: {mx_val}\n"
            f"💰 السعر: {fmt_price(price)} نقطة/1000 وحدة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    if data == "os:view_services" and is_own:
        # عرض قائمة اختيار الفئة أولاً
        rows = []
        for cat_key, cat_name in CATEGORY_MAP.items():
            with db_conn() as c:
                cnt = c.execute("SELECT COUNT(*) AS n FROM services WHERE category=?", (cat_key,)).fetchone()
            n = cnt["n"] if cnt else 0
            rows.append([InlineKeyboardButton(f"{cat_name} ({n})", callback_data=f"os_view_cat:{cat_key}")])
        rows.append([InlineKeyboardButton("📂 عرض الجميع", callback_data="os_view_cat:ALL")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await q.edit_message_text(
            "🗂 *عرض الخدمات — اختر الفئة:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data.startswith("os_view_cat:") and is_own:
        cat_filter = data.split(":", 1)[1]
        if cat_filter == "ALL":
            cats_to_show = list(CATEGORY_MAP.items())
        else:
            cats_to_show = [(cat_filter, CATEGORY_MAP.get(cat_filter, cat_filter))]
        sent_any = False
        first = True
        for cat_key, cat_name in cats_to_show:
            with db_conn() as c:
                svcs = c.execute("SELECT * FROM services WHERE category=? ORDER BY id", (cat_key,)).fetchall()
            if not svcs:
                continue
            sent_any = True
            for s in svcs:
                status = "✅ مفعّلة" if s["active"] else "❌ معطّلة"
                site_name = PANEL_MAP.get(s["panel"] or 1, PANEL_MAP[1])["name"]
                svc_text = (
                    f"📂 *{cat_name}*\n"
                    f"🔹 *{s['name_ar']}*\n\n"
                    f"🟢 الحالة: {status}\n"
                    f"🌐 الموقع: {site_name} (رقم: {s['api_service_id']})\n"
                    f"📝 الوصف: {s['description'] or '—'}\n"
                    f"📉 الحد الأدنى: {s['min_qty']:,}\n"
                    f"📈 الحد الأعلى: {s['max_qty']:,}\n"
                    f"💰 السعر: {fmt_price(s['price_per_point'])} نقطة / 1000 وحدة\n"
                )
                tog = "❌ تعطيل" if s["active"] else "✅ تفعيل"
                svc_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ تعديل", callback_data=f"os_edit_svc:{s['id']}"),
                     InlineKeyboardButton(tog, callback_data=f"os_tog_svc:{s['id']}:{0 if s['active'] else 1}"),
                     InlineKeyboardButton("🗑 حذف", callback_data=f"os_del_svc:{s['id']}")],
                ])
                if first and update.callback_query:
                    await q.edit_message_text(svc_text, parse_mode=ParseMode.MARKDOWN, reply_markup=svc_kb)
                    first = False
                else:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=svc_text,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=svc_kb
                    )
        if not sent_any:
            cat_name = "الجميع" if cat_filter == "ALL" else CATEGORY_MAP.get(cat_filter, cat_filter)
            msg = f"📋 لا توجد خدمات في فئة ({cat_name}) بعد."
            if first and update.callback_query:
                await q.edit_message_text(msg, reply_markup=owner_settings_kb())
            else:
                await context.bot.send_message(update.effective_chat.id, msg)
        else:
            await context.bot.send_message(
                update.effective_chat.id,
                "⬆️ هذه جميع الخدمات المطلوبة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للعرض", callback_data="os:view_services"),
                                                    InlineKeyboardButton("⚙️ الإعدادات", callback_data="owner_settings")]])
            )
        return

    if data == "os:orders_section" and is_own:
        await show_orders_section(update, context, offset=0)
        return

    if data.startswith("os:orders_page:") and is_own:
        offset = int(data.split(":")[2])
        await show_orders_section(update, context, offset=offset)
        return

    if data == "os:order_lookup" and is_own:
        context.user_data["state"] = "os_await_order_lookup"
        await q.edit_message_text("🔍 أرسل كود الطلب الذي تريد عرض تفاصيله:")
        return

    if data == "os:list_services" and is_own:
        text_, rows = _render_service_list()
        if rows is None:
            await q.edit_message_text(text_, reply_markup=owner_settings_kb())
            return
        await q.edit_message_text(text_, parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("os_tog_svc:") and is_own:
        _, sid, val = data.split(":")
        with db_conn() as c:
            c.execute("UPDATE services SET active=? WHERE id=?", (int(val), int(sid)))
        await q.answer("✅ تم التحديث")
        text_, rows = _render_service_list()
        if rows is None:
            await q.edit_message_text(text_, reply_markup=owner_settings_kb())
            return
        await q.edit_message_text(text_, parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(rows))
        return

    # ── تعديل خدمة ──
    if data.startswith("os_edit_svc:") and is_own:
        sid = int(data.split(":")[1])
        with db_conn() as c:
            svc = c.execute("SELECT * FROM services WHERE id=?", (sid,)).fetchone()
        if not svc:
            await q.answer("⚠️ الخدمة غير موجودة")
            return
        site_name = PANEL_MAP.get(svc["panel"] or 1, PANEL_MAP[1])["name"]
        rows = [
            [InlineKeyboardButton("✏️ الاسم", callback_data=f"os_edit_field:{sid}:name"),
             InlineKeyboardButton("📉 الحد الأدنى", callback_data=f"os_edit_field:{sid}:min")],
            [InlineKeyboardButton("📈 الحد الأعلى", callback_data=f"os_edit_field:{sid}:max"),
             InlineKeyboardButton("💰 السعر", callback_data=f"os_edit_field:{sid}:price")],
            [InlineKeyboardButton("📝 الوصف", callback_data=f"os_edit_field:{sid}:desc")],
            [InlineKeyboardButton("🌐 الموقع ورقم الخدمة", callback_data=f"os_edit_field:{sid}:source")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="os:list_services")],
        ]
        await q.edit_message_text(
            f"✏️ *تعديل الخدمة:* {svc['name_ar']}\n\n"
            f"🌐 الموقع الحالي: {site_name} (رقم {svc['api_service_id']})\n"
            f"📉 الحد الأدنى: {svc['min_qty']}\n"
            f"📈 الحد الأعلى: {svc['max_qty']}\n"
            f"💰 السعر: {fmt_price(svc['price_per_point'])} نقطة/1000\n"
            f"📝 الوصف: {svc['description'] or '—'}\n\n"
            f"اختر ما تريد تعديله:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data.startswith("os_edit_field:") and is_own:
        _, sid, field = data.split(":")
        context.user_data["edit_svc_id"] = int(sid)
        prompts = {
            "name":  ("✏️ أرسل *الاسم الجديد بالعربية* للخدمة:", "os_edit_await_name"),
            "min":   ("📉 أرسل *الحد الأدنى* الجديد:", "os_edit_await_min"),
            "max":   ("📈 أرسل *الحد الأعلى* الجديد:", "os_edit_await_max"),
            "price": ("💰 أرسل *السعر* الجديد (نقطة/1000 وحدة):", "os_edit_await_price"),
            "desc":  ("📝 أرسل *الوصف الجديد* للخدمة (أو أرسل `-` لحذف الوصف):", "os_edit_await_desc"),
        }
        if field == "source":
            rows = [
                [InlineKeyboardButton(f"1️⃣ {PANEL_MAP[1]['name']}", callback_data=f"os_edit_panel:{sid}:1")],
                [InlineKeyboardButton(f"2️⃣ {PANEL_MAP[2]['name']}", callback_data=f"os_edit_panel:{sid}:2")],
                [InlineKeyboardButton("🔙 رجوع", callback_data=f"os_edit_svc:{sid}")],
            ]
            await q.edit_message_text(
                "🌐 اختر *الموقع الجديد* الذي تريد ربط الخدمة به:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows)
            )
            return
        msg, state_name = prompts[field]
        context.user_data["state"] = state_name
        await q.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
        return

    if data.startswith("os_edit_panel:") and is_own:
        _, sid, panel = data.split(":")
        context.user_data["edit_svc_id"] = int(sid)
        context.user_data["edit_svc_panel"] = int(panel)
        context.user_data["state"] = "os_edit_await_apiid"
        site_name = PANEL_MAP.get(int(panel), PANEL_MAP[1])["name"]
        await q.edit_message_text(
            f"🌐 الموقع: {site_name}\n\nأرسل *رقم الخدمة الجديد* في هذا الموقع:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data.startswith("os_del_svc:") and is_own:
        sid = int(data.split(":")[1])
        with db_conn() as c:
            svc = c.execute("SELECT * FROM services WHERE id=?", (sid,)).fetchone()
        if not svc:
            await q.answer("⚠️ الخدمة غير موجودة")
            return
        await q.edit_message_text(
            f"🗑 *تأكيد الحذف:*\n\n"
            f"هل أنت متأكد من حذف الخدمة:\n"
            f"*{svc['name_ar']}*؟\n\n"
            f"⚠️ لا يمكن التراجع عن هذا الإجراء!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ نعم، احذف", callback_data=f"os_confirm_del:{sid}"),
                 InlineKeyboardButton("❌ إلغاء", callback_data="os:list_services")]
            ])
        )
        return

    if data.startswith("os_confirm_del:") and is_own:
        sid = int(data.split(":")[1])
        with db_conn() as c:
            svc = c.execute("SELECT name_ar FROM services WHERE id=?", (sid,)).fetchone()
            c.execute("DELETE FROM services WHERE id=?", (sid,))
        name = svc["name_ar"] if svc else "الخدمة"
        await q.edit_message_text(
            f"✅ تم حذف الخدمة *'{name}'* بنجاح.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    if data == "os:edit_gift" and is_own:
        context.user_data["state"] = "os_await_gift_val"
        cur = get_setting("daily_gift_points") or "50"
        await q.edit_message_text(f"🎁 الهدية الحالية: {cur} نقطة\n\nأرسل القيمة الجديدة:")
        return

    if data == "os:edit_referral" and is_own:
        context.user_data["state"] = "os_await_referral_val"
        cur = get_setting("referral_points") or "30"
        await q.edit_message_text(f"🔗 نقاط الدعوة الحالية: {cur} نقطة\n\nأرسل القيمة الجديدة:")
        return

    if data == "os:edit_star_rate" and is_own:
        context.user_data["state"] = "os_await_star_rate"
        cur = get_setting("star_to_points") or "250"
        await q.edit_message_text(f"⭐ سعر النجمة (شحن) الحالي: {cur} نقطة\n\nأرسل القيمة الجديدة:")
        return

    if data == "os:edit_exchange_rate" and is_own:
        context.user_data["state"] = "os_await_exchange_rate"
        cur = get_setting("exchange_star_rate") or "2000"
        await q.edit_message_text(f"🏆 سعر نجمة الجوائز الحالي: {cur} نقطة\n\nأرسل القيمة الجديدة:")
        return

    if data == "os:edit_exchange_msg" and is_own:
        context.user_data["state"] = "os_await_exchange_msg"
        cur = get_setting("exchange_success_msg") or "(لا توجد رسالة مضافة حالياً)"
        await q.edit_message_text(
            f"✏️ الرسالة الحالية التي تظهر عند الاستبدال:\n\n{cur}\n\n"
            f"أرسل الرسالة الجديدة (ستظهر لكل مستخدم قبل كود عمليته تلقائياً):"
        )
        return

    if data == "os:edit_number_cost" and is_own:
        context.user_data["state"] = "os_await_number_cost"
        cur = get_setting("telegram_number_cost") or "5000"
        await q.edit_message_text(f"📱 سعر رقم تيلغرام الحالي: {cur} نقطة\n\nأرسل القيمة الجديدة:")
        return

    if data == "os:edit_contact" and is_own:
        context.user_data["state"] = "os_await_contact"
        cur = get_setting("owner_contact") or "غير مضبوط"
        cur_label = get_setting("owner_contact_label") or "💬 تواصل مع المالك"
        await q.edit_message_text(
            f"💬 *رابط تواصل المالك*\n\n"
            f"الرابط الحالي: {cur}\n"
            f"نص الزر الحالي: {cur_label}\n\n"
            f"أرسل رابط تيلغرام الخاص بك:\n"
            f"مثال: `https://t.me/username`\n\n"
            f"(أرسل *حذف* لإزالة الرابط)",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:edit_contact_label" and is_own:
        context.user_data["state"] = "os_await_contact_label"
        cur_label = get_setting("owner_contact_label") or "💬 تواصل مع المالك"
        await q.edit_message_text(
            f"✏️ *نص زر التواصل (بعد خصم النقاط)*\n\n"
            f"النص الحالي: {cur_label}\n\n"
            f"أرسل النص الجديد للزر:\n"
            f"مثال: `- الدعم الفني 🧑‍🔧 -`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:edit_support_label" and is_own:
        context.user_data["state"] = "os_await_support_label"
        cur_label = get_setting("support_contact_label") or "🛎 تواصل مع الدعم"
        await q.edit_message_text(
            f"✏️ *نص زر الدعم داخل صفحة التواصل*\n\n"
            f"النص الحالي: {cur_label}\n\n"
            f"أرسل النص الجديد:\n"
            f"مثال: `- الدعم الفني 🧑‍🔧 -`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:edit_welcome" and is_own:
        context.user_data["state"] = "os_await_welcome"
        cur = get_setting("welcome_message") or ""
        await q.edit_message_text(f"💌 رسالة الترحيب الحالية:\n{cur}\n\nأرسل الرسالة الجديدة:")
        return

    if data == "os:edit_asiacell" and is_own:
        context.user_data["state"] = "os_await_asiacell_text"
        cur = get_setting("asiacell_text") or ""
        await q.edit_message_text(f"📲 النص الحالي لاسيا سيل:\n\n{cur}\n\nأرسل النص الجديد:")
        return

    if data == "os:edit_join_reward" and is_own:
        cur = get_setting("join_channel_reward") or "45"
        context.user_data["state"] = "os_await_join_reward"
        await q.edit_message_text(
            f"🎁 *نقاط الانضمام للقنوات الداخلية*\n\n"
            f"القيمة الحالية: {cur} نقطة\n\n"
            f"أرسل عدد النقاط التي يحصل عليها العضو عند الانضمام:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:edit_leave_penalty" and is_own:
        cur = get_setting("channel_leave_penalty") or "75"
        context.user_data["state"] = "os_await_leave_penalty"
        await q.edit_message_text(
            f"❌ *خصم مغادرة القناة*\n\n"
            f"القيمة الحالية: {cur} نقطة\n\n"
            f"عند مغادرة العضو لقناة داخلية حصل منها على نقاط انضمام سابقاً، تُخصم منه هذه القيمة تلقائياً.\n"
            f"أرسل عدد النقاط الجديد:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:edit_mandatory_min" and is_own:
        cur = get_setting("mandatory_channel_min_members") or "0"
        context.user_data["state"] = "os_await_mandatory_min"
        await q.edit_message_text(
            f"👥 *الحد الأدنى للأعضاء — التمويل الإجباري*\n\n"
            f"القيمة الحالية: {int(cur):,} عضو\n"
            f"(0 = بدون حد أدنى)\n\n"
            f"أرسل العدد الجديد:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:edit_internal_min" and is_own:
        cur = get_setting("internal_channel_min_members") or "0"
        context.user_data["state"] = "os_await_internal_min"
        await q.edit_message_text(
            f"👥 *الحد الأدنى للأعضاء — التمويل الداخلي*\n\n"
            f"القيمة الحالية: {int(cur):,} عضو\n"
            f"(0 = بدون حد أدنى)\n\n"
            f"أرسل العدد الجديد:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:edit_mandatory_cost" and is_own:
        cur = get_setting("mandatory_channel_cost") or "200"
        context.user_data["state"] = "os_await_mandatory_cost"
        await q.edit_message_text(
            f"📢 *سعر تمويل القناة الإجباري السريع*\n\n"
            f"السعر الحالي: {cur} نقطة\n\n"
            f"أرسل السعر الجديد بالنقاط:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:edit_internal_cost" and is_own:
        cur = get_setting("internal_channel_cost") or "100"
        context.user_data["state"] = "os_await_internal_cost"
        await q.edit_message_text(
            f"🔄 *سعر تمويل القناة الداخلي البطيء*\n\n"
            f"السعر الحالي: {cur} نقطة\n\n"
            f"أرسل السعر الجديد بالنقاط:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:cancel_order" and is_own:
        context.user_data["state"] = "os_await_cancel_order"
        await q.edit_message_text("❌ *إلغاء طلب:*\n\nأرسل كود الطلب المراد إلغاؤه:", parse_mode=ParseMode.MARKDOWN)
        return

    if data == "os:complete_order" and is_own:
        context.user_data["state"] = "os_await_complete_order"
        await q.edit_message_text("✅ *إكمال طلب:*\n\nأرسل كود الطلب الذي تم تنفيذه بالكامل:", parse_mode=ParseMode.MARKDOWN)
        return

    if data == "os:manage_channels" and is_own:
        context.user_data["state"] = "os_await_channel"
        with db_conn() as c:
            channels = c.execute("SELECT * FROM mandatory_channels WHERE active=1").fetchall()
        lines = ["📡 *القنوات الحالية:*\n"]
        for ch in channels:
            lines.append(f"• @{ch['channel_username']} ({ch['funding_type']})")
        rows = []
        for ch in channels:
            rows.append([InlineKeyboardButton(
                f"❌ حذف @{ch['channel_username']}",
                callback_data=f"os_del_ch:{ch['id']}"
            )])
        rows.append([InlineKeyboardButton("➕ إضافة قناة", callback_data="os_add_ch")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await q.edit_message_text("\n".join(lines) or "لا توجد قنوات", parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("os_del_ch:") and is_own:
        ch_id = int(data.split(":")[1])
        with db_conn() as c:
            c.execute("UPDATE mandatory_channels SET active=0 WHERE id=?", (ch_id,))
        await q.answer("🗑 تم حذف القناة")
        return

    if data == "os_add_ch" and is_own:
        context.user_data["state"] = "os_await_channel"
        await q.edit_message_text("📡 أرسل يوزرنيم القناة (مثال: @channel):")
        return

    # ── الأكواد الترويجية (مالك) ──
    if data == "os:create_promo" and is_own:
        context.user_data["state"] = "os_await_promo_code_text"
        await q.edit_message_text(
            "🎟 *إنشاء كود ترويجي جديد*\n\nأرسل الكود المراد إنشاؤه (أحرف وأرقام فقط):",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:list_promos" and is_own:
        with db_conn() as c:
            promos = c.execute("SELECT * FROM promo_codes ORDER BY created_at DESC").fetchall()
        if not promos:
            await q.edit_message_text("📋 لا توجد أكواد ترويجية.", reply_markup=owner_settings_kb())
            return
        lines = ["📋 *الأكواد الترويجية:*\n"]
        rows  = []
        for p in promos:
            status = "✅" if p["active"] else "❌"
            lines.append(
                f"{status} `{p['code']}` — {p['points']} نقطة — {p['used_count']}/{p['max_uses']} استخدام"
            )
            tog = "❌ تعطيل" if p["active"] else "✅ تفعيل"
            rows.append([
                InlineKeyboardButton(p["code"], callback_data="noop"),
                InlineKeyboardButton(tog, callback_data=f"os_tog_promo:{p['code']}:{0 if p['active'] else 1}"),
                InlineKeyboardButton("🗑", callback_data=f"os_del_promo:{p['code']}")
            ])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("os_tog_promo:") and is_own:
        parts = data.split(":")
        code  = parts[1]
        val   = int(parts[2])
        with db_conn() as c:
            c.execute("UPDATE promo_codes SET active=? WHERE code=?", (val, code))
        await q.answer("✅ تم التحديث")
        return

    if data.startswith("os_del_promo:") and is_own:
        code = data.split(":")[1]
        with db_conn() as c:
            c.execute("DELETE FROM promo_codes WHERE code=?", (code,))
        await q.answer("🗑 تم الحذف")
        return

    # ── رسالة جماعية ──
    if data == "os:broadcast" and is_own:
        context.user_data["state"] = "os_await_broadcast"
        with db_conn() as c:
            total = c.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
        await q.edit_message_text(
            f"📢 *رسالة جماعية*\n\n"
            f"سيتم الإرسال لـ {total} مستخدم.\n\n"
            f"أرسل الرسالة الآن (يدعم HTML):",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:toggle_captcha" and is_own:
        current = int(get_setting("captcha_enabled") or "0")
        new_val = "0" if current else "1"
        set_setting("captcha_enabled", new_val)
        status = "مفعّل ✅" if new_val == "1" else "معطّل ❌"
        await q.edit_message_text(
            f"🔐 *التحقق الرياضي الآن: {status}*\n\n"
            f"{'سيظهر السؤال للمستخدمين الجدد عند /start' if new_val == '1' else 'لن يظهر أي سؤال للمستخدمين الجدد'}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    if data == "os:stats" and is_own:
        with db_conn() as c:
            total_users   = c.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
            total_orders  = c.execute("SELECT COUNT(*) as cnt FROM orders").fetchone()["cnt"]
            total_pts     = c.execute("SELECT SUM(points) as s FROM users").fetchone()["s"] or 0
            total_promos  = c.execute("SELECT COUNT(*) as cnt FROM promo_codes WHERE active=1").fetchone()["cnt"]
        await q.edit_message_text(
            f"📊 *إحصائيات البوت:*\n\n"
            f"👥 إجمالي المستخدمين: {total_users}\n"
            f"📦 إجمالي الطلبات: {total_orders}\n"
            f"💰 إجمالي النقاط في البوت: {total_pts}\n"
            f"🎟 أكواد ترويجية نشطة: {total_promos}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    # ── رصيد مواقع الرشق (مالك) ──
    if data == "os:site_balance" and is_own:
        await q.edit_message_text("⏳ جارٍ الاستعلام عن رصيدك في المواقع...")
        lines = ["💵 *رصيد حساباتك في مواقع الرشق:*\n"]
        for panel_id, site in PANEL_MAP.items():
            res = smm_request("balance", panel=panel_id)
            if "error" in res:
                lines.append(f"❌ *{site['name']}*: تعذّر الاتصال ({res['error']})")
                continue
            balance  = res.get("balance", "غير معروف")
            currency = res.get("currency", "USD")
            lines.append(f"🌐 *{site['name']}*: {balance} {currency}")
        await q.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_kb("owner_settings")
        )
        return

    # ── إدارة باقات الاستبدال بنجوم (مالك) ──
    if data == "os:manage_star_packages" and is_own:
        with db_conn() as c:
            packages = c.execute("SELECT * FROM exchange_star_packages ORDER BY stars").fetchall()
        rate = int(get_setting("exchange_star_rate") or "2000")
        lines = ["📦 *باقات الاستبدال بنجوم:*\n"]
        for pkg in packages:
            status = "✅" if pkg["active"] else "❌"
            cost = pkg["stars"] * rate
            lines.append(f"{status} {pkg['stars']} نجمة = {cost} نقطة")
        rows = []
        for pkg in packages:
            tog = "❌ تعطيل" if pkg["active"] else "✅ تفعيل"
            rows.append([
                InlineKeyboardButton(f"⭐ {pkg['stars']} نجمة", callback_data="noop"),
                InlineKeyboardButton(tog, callback_data=f"os_tog_pkg:{pkg['id']}:{0 if pkg['active'] else 1}"),
                InlineKeyboardButton("🗑", callback_data=f"os_del_pkg:{pkg['id']}")
            ])
        rows.append([InlineKeyboardButton("➕ إضافة باقة", callback_data="os_add_pkg")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        msg = "\n".join(lines) if len(packages) > 0 else "⭐ لا توجد باقات بعد. اضغط ➕ لإضافة باقة."
        await q.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(rows))
        return

    if data == "os_add_pkg" and is_own:
        context.user_data["state"] = "os_await_pkg_stars"
        await q.edit_message_text("⭐ *إضافة باقة جديدة*\n\nأرسل عدد النجوم (مثال: 15):",
                                   parse_mode=ParseMode.MARKDOWN)
        return

    if data.startswith("os_tog_pkg:") and is_own:
        parts = data.split(":")
        pkg_id = int(parts[1])
        val = int(parts[2])
        with db_conn() as c:
            c.execute("UPDATE exchange_star_packages SET active=? WHERE id=?", (val, pkg_id))
            packages = c.execute("SELECT * FROM exchange_star_packages ORDER BY stars").fetchall()
        await q.answer("✅ تم التحديث")
        rate = int(get_setting("exchange_star_rate") or "2000")
        lines = ["📦 *باقات الاستبدال بنجوم:*\n"]
        for pkg in packages:
            status = "✅" if pkg["active"] else "❌"
            cost = pkg["stars"] * rate
            lines.append(f"{status} {pkg['stars']} نجمة = {cost} نقطة")
        rows = []
        for pkg in packages:
            tog = "❌ تعطيل" if pkg["active"] else "✅ تفعيل"
            rows.append([
                InlineKeyboardButton(f"⭐ {pkg['stars']} نجمة", callback_data="noop"),
                InlineKeyboardButton(tog, callback_data=f"os_tog_pkg:{pkg['id']}:{0 if pkg['active'] else 1}"),
                InlineKeyboardButton("🗑", callback_data=f"os_del_pkg:{pkg['id']}")
            ])
        rows.append([InlineKeyboardButton("➕ إضافة باقة", callback_data="os_add_pkg")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        msg = "\n".join(lines) if len(packages) > 0 else "⭐ لا توجد باقات بعد."
        await q.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("os_del_pkg:") and is_own:
        pkg_id = int(data.split(":")[1])
        with db_conn() as c:
            c.execute("DELETE FROM exchange_star_packages WHERE id=?", (pkg_id,))
        await q.answer("🗑 تم الحذف")
        return

    # ── استبدال بجائزة مخصصة ──
    if data.startswith("exchange:custom:"):
        parts = data.split(":")
        prize_id = int(parts[2])
        confirmed = len(parts) > 3 and parts[3] == "confirm"
        with db_conn() as c:
            prize = c.execute(
                "SELECT * FROM custom_prizes WHERE id=%s AND active=1", (prize_id,)
            ).fetchone()
        if not prize:
            await q.edit_message_text("⚠️ هذه الجائزة لم تعد متاحة.", reply_markup=back_kb("exchange_points"))
            return
        cost = prize["points_cost"]
        db_user = get_user(user.id)
        pts = db_user["points"] if db_user else 0
        qty_txt = f" × {prize['quantity']}" if prize["quantity"] and prize["quantity"] > 1 else ""

        if not confirmed:
            # ── شاشة التفاصيل والتأكيد ──
            can_afford = pts >= cost
            confirm_kb = [
                [InlineKeyboardButton(
                    "✅ تأكيد الطلب" if can_afford else "❌ رصيدك غير كافٍ",
                    callback_data=f"exchange:custom:{prize_id}:confirm" if can_afford else "noop"
                )],
                [InlineKeyboardButton("🔙 رجوع", callback_data="exchange_points")],
            ]
            await q.edit_message_text(
                f"🎁 *{prize['name']}{qty_txt}*\n\n"
                f"💰 التكلفة: *{cost:,} نقطة*\n"
                f"💎 رصيدك الحالي: {pts:,} نقطة\n\n"
                + ("✅ يمكنك الطلب — اضغط تأكيد للمتابعة." if can_afford else
                   f"❌ تحتاج {cost - pts:,} نقطة إضافية."),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(confirm_kb)
            )
            return

        # ── تنفيذ الطلب بعد التأكيد ──
        if pts < cost:
            await q.edit_message_text("❌ رصيدك غير كافٍ!", reply_markup=back_kb("exchange_points"))
            return
        if not deduct_points(user.id, cost):
            await q.edit_message_text("❌ حدث خطأ في خصم النقاط.", reply_markup=back_kb("exchange_points"))
            return
        code = next_order_code(user.id)
        with db_conn() as c:
            c.execute(
                "INSERT INTO prize_exchanges (user_id,prize_type,prize_value,points_cost,status) VALUES (%s,%s,%s,%s,'pending')",
                (user.id, "custom", f"{prize['name']}{qty_txt}", cost)
            )
        custom_msg = get_setting("exchange_success_msg") or ""
        result_kb = contact_owner_row() + [[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]]
        await q.edit_message_text(
            f"✅ *تمت العملية بنجاح!*\n\n"
            f"🎁 الجائزة: {prize['name']}{qty_txt}\n"
            f"💰 التكلفة: {cost:,} نقطة\n\n"
            + (f"{custom_msg}\n\n" if custom_msg else "")
            + "سيتواصل معك المالك قريباً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(result_kb)
        )
        await context.bot.send_message(
            user.id,
            f"📌 *كود عمليتك:* `{code}`",
            parse_mode=ParseMode.MARKDOWN
        )
        await notify_group(
            context.application,
            f"🎁 <b>طلب جائزة مخصصة</b>\n"
            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
            f"🎀 {prize['name']}{qty_txt}\n"
            f"💰 {cost:,} نقطة\n"
            f"📌 {code}"
        )
        return

    # ── إدارة الجوائز المخصصة (المالك) ──
    if data == "os:manage_prizes" and is_own:
        with db_conn() as c:
            prizes = c.execute("SELECT * FROM custom_prizes ORDER BY id").fetchall()
        rows = []
        for p in prizes:
            st = "✅" if p["active"] else "❌"
            rows.append([
                InlineKeyboardButton(
                    f"{st} {p['name']} × {p['quantity']} — {p['points_cost']:,} نقطة",
                    callback_data=f"os:toggle_prize:{p['id']}"
                ),
                InlineKeyboardButton("🗑", callback_data=f"os:del_prize:{p['id']}")
            ])
        rows.append([InlineKeyboardButton("➕ إضافة جائزة جديدة", callback_data="os:add_prize")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        txt = "🎀 *الجوائز المخصصة:*\n\nاضغط على الجائزة لتفعيل/تعطيل · 🗑 للحذف" if prizes else "🎀 لا توجد جوائز مخصصة بعد."
        await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows))
        return

    if data == "os:add_prize" and is_own:
        context.user_data["state"] = "os_await_prize_name"
        await q.edit_message_text(
            "🎀 *إضافة جائزة مخصصة*\n\n"
            "الخطوة 1/2 — أرسل *اسم الجائزة*:\n"
            "مثال: `اسيا سيل 500` أو `بطاقة شحن`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:skip_prize_qty" and is_own:
        context.user_data["prize_qty"] = 1
        context.user_data["state"] = "os_await_prize_cost"
        name = context.user_data.get("prize_name", "")
        await q.edit_message_text(
            f"🎀 *الجائزة:* {name}\n\n"
            f"الخطوة 2/2 — أرسل *عدد النقاط* اللازمة للحصول عليها:\n"
            f"مثال: `1000`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data.startswith("os:toggle_prize:") and is_own:
        pid = int(data.split(":")[2])
        with db_conn() as c:
            c.execute("UPDATE custom_prizes SET active = 1-active WHERE id=%s", (pid,))
        await q.answer("✅ تم التحديث")
        with db_conn() as c:
            prizes = c.execute("SELECT * FROM custom_prizes ORDER BY id").fetchall()
        rows = []
        for p in prizes:
            st = "✅" if p["active"] else "❌"
            rows.append([
                InlineKeyboardButton(
                    f"{st} {p['name']} × {p['quantity']} — {p['points_cost']:,} نقطة",
                    callback_data=f"os:toggle_prize:{p['id']}"
                ),
                InlineKeyboardButton("🗑", callback_data=f"os:del_prize:{p['id']}")
            ])
        rows.append([InlineKeyboardButton("➕ إضافة جائزة جديدة", callback_data="os:add_prize")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("os:del_prize:") and is_own:
        pid = int(data.split(":")[2])
        with db_conn() as c:
            c.execute("DELETE FROM custom_prizes WHERE id=%s", (pid,))
        await q.answer("🗑 تم الحذف")
        with db_conn() as c:
            prizes = c.execute("SELECT * FROM custom_prizes ORDER BY id").fetchall()
        rows = []
        for p in prizes:
            st = "✅" if p["active"] else "❌"
            rows.append([
                InlineKeyboardButton(
                    f"{st} {p['name']} × {p['quantity']} — {p['points_cost']:,} نقطة",
                    callback_data=f"os:toggle_prize:{p['id']}"
                ),
                InlineKeyboardButton("🗑", callback_data=f"os:del_prize:{p['id']}")
            ])
        rows.append([InlineKeyboardButton("➕ إضافة جائزة جديدة", callback_data="os:add_prize")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        txt = "🎀 *الجوائز المخصصة:*\n\nاضغط على الجائزة لتفعيل/تعطيل · 🗑 للحذف" if prizes else "🎀 لا توجد جوائز مخصصة بعد."
        await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows))
        return

    if data == "noop":
        return

# ────────────────────────────────────────────────────────────
#  Telegram Stars — Pre-Checkout
# ────────────────────────────────────────────────────────────
async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.pre_checkout_query
    payload = query.invoice_payload

    valid = False
    if payload.startswith("charge_stars:"):
        parts = payload.split(":")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            expected_stars  = int(parts[1])
            uid_in_payload  = int(parts[2])
            actual_stars    = query.total_amount
            if query.from_user.id == uid_in_payload and actual_stars == expected_stars:
                valid = True

    if valid:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="حدث خطأ في التحقق من الدفع.")

# ────────────────────────────────────────────────────────────
#  Telegram Stars — Successful Payment
# ────────────────────────────────────────────────────────────
async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    user    = update.effective_user
    is_own  = (user.id == OWNER_ID)

    if payload.startswith("charge_stars:"):
        parts = payload.split(":")
        stars = int(parts[1])
        rate  = int(get_setting("star_to_points") or "250")
        pts   = stars * rate
        add_points(user.id, pts)
        with db_conn() as c:
            c.execute(
                "INSERT INTO star_transactions (user_id,stars,points_given,telegram_payment_id) VALUES (?,?,?,?)",
                (user.id, stars, pts, payment.telegram_payment_charge_id)
            )
        db_user = get_user(user.id)
        await update.message.reply_text(
            f"✅ *تم الشحن بنجاح!*\n\n"
            f"⭐ النجوم: {stars}\n"
            f"✨ النقاط المضافة: {pts}\n"
            f"💰 رصيدك الآن: {db_user['points']} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )
        await notify_group(
            context.application,
            f"⭐ <b>شحن نجوم ناجح</b>\n"
            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
            f"⭐ {stars} نجمة → {pts} نقطة"
        )

# ────────────────────────────────────────────────────────────
#  Main
# ────────────────────────────────────────────────────────────
# ── اكتشاف مغادرة الأعضاء لقنوات التمويل الداخلي وخصم نقاط العقوبة ──
async def handle_member_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmu = update.chat_member
    if not cmu:
        return
    old_status = cmu.old_chat_member.status
    new_status = cmu.new_chat_member.status
    member_user = cmu.new_chat_member.user
    if member_user.is_bot:
        return
    was_in = old_status in ("member", "administrator", "creator", "restricted")
    now_out = new_status in ("left", "kicked")
    if not (was_in and now_out):
        return
    username = (cmu.chat.username or "").lstrip("@")
    if not username:
        return
    with db_conn() as c:
        ch = c.execute(
            "SELECT * FROM mandatory_channels WHERE channel_username=? AND funding_type='internal' AND active=1",
            (username,)
        ).fetchone()
    if not ch:
        return
    with db_conn() as c:
        claimed = c.execute(
            "SELECT 1 FROM channel_join_rewards WHERE user_id=? AND channel_id=?",
            (member_user.id, ch["id"])
        ).fetchone()
        if not claimed:
            return
        c.execute(
            "DELETE FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
            (member_user.id, ch["id"])
        )
    penalty = int(get_setting("channel_leave_penalty") or "75")
    deducted = deduct_points_clamped(member_user.id, penalty)
    if deducted > 0:
        try:
            await context.bot.send_message(
                member_user.id,
                f"⚠️ *تنبيه خصم نقاط*\n\n"
                f"لاحظنا أنك غادرت القناة @{username} بعد حصولك على نقاط الانضمام إليها.\n"
                f"💸 تم خصم *{deducted} نقطة* من رصيدك.\n\n"
                f"يمكنك الانضمام للقناة مجدداً من قسم 💰 تجميع النقاط لكسب النقاط من جديد.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

def main():
    init_db()
    start_health_server()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("addpoints", cmd_addpoints))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE,
        handle_text
    ))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(ChatMemberHandler(handle_member_leave, ChatMemberHandler.CHAT_MEMBER))

    async def post_init(application):
        # أوامر عامة لجميع المستخدمين
        await application.bot.set_my_commands([
            BotCommand("start", "🏠 القائمة الرئيسية"),
        ])
        # أوامر إضافية للمالك فقط
        if OWNER_ID:
            await application.bot.set_my_commands(
                [
                    BotCommand("start", "🏠 القائمة الرئيسية"),
                    BotCommand("admin", "⚙️ لوحة المالك"),
                ],
                scope=BotCommandScopeChat(chat_id=OWNER_ID)
            )
        logger.info("✅ Bot commands set")

    # ── معالج الأخطاء العام ──
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        err = context.error
        if isinstance(err, RetryAfter):
            logger.warning(f"⚠️ RetryAfter: {err.retry_after}s")
            return
        if isinstance(err, (NetworkError, TimedOut)):
            logger.warning(f"⚠️ خطأ شبكي مؤقت: {err}")
            return
        logger.error(f"❌ خطأ غير متوقع:\n{traceback.format_exc()}")

    app.add_error_handler(error_handler)
    app.post_init = post_init
    logger.info("🤖 Bot started!")
    app.run_polling(
        drop_pending_updates=True,
        read_timeout=30,
        write_timeout=30,
        connect_timeout=30,
        pool_timeout=30,
        allowed_updates=["message", "callback_query", "pre_checkout_query", "successful_payment", "chat_member"],
    )

if __name__ == "__main__":
    main()
