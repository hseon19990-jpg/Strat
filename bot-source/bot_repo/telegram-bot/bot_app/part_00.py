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
import re
import asyncio
import time
import random
import math
import html
import requests
import logging
import traceback
from datetime import date, datetime, timedelta, timezone
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
from telegram.error import NetworkError, TimedOut, RetryAfter, Conflict

from telethon import TelegramClient, events
from telethon.sessions import StringSession
import struct, base64, socket as _socket

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
_TG_DC = {
    1: ("149.154.175.53",  443),
    2: ("149.154.167.51",  443),
    3: ("149.154.175.100", 443),
    4: ("149.154.167.91",  443),
    5: ("91.108.56.130",   443),
}

def pyrogram_json_to_telethon(data: dict) -> str | None:
    """
    يحوّل صيغة Pyrogram JSON إلى Telethon StringSession.
    يتوقع dict يحتوي على:
      - dc_id   : رقم مركز البيانات (1-5)
      - auth_key: مفتاح المصادقة بصيغة hex (512 رمز = 256 بايت)
    يُرجع StringSession string جاهز للاستخدام، أو None عند الفشل.

    صيغة Telethon StringSession الصحيحة:
      '1' + base64url( struct.pack('>B4sH256s', dc_id, ip_bytes, port, auth_key) )
    """
    try:
        dc_id    = int(data.get("dc_id") or 0)
        auth_hex = (data.get("auth_key") or "").strip()
        if not dc_id or not auth_hex:
            return None
        auth_key = bytes.fromhex(auth_hex)
        if len(auth_key) != 256:
            return None
        ip, port = _TG_DC.get(dc_id, ("149.154.167.51", 443))
        packed = struct.pack(
            ">B4sH256s",
            dc_id,                      # dc_id  (1 byte)
            _socket.inet_aton(ip),      # IP     (4 bytes)
            port,                       # port   (2 bytes)
            auth_key,                   # key    (256 bytes)
        )
        return "1" + base64.urlsafe_b64encode(packed).decode("ascii")
    except Exception:
        return None

def _maybe_convert_session(raw: str) -> str:
    """
    إذا كانت raw عبارة عن JSON يحتوي dc_id + auth_key (صيغة Pyrogram)
    يحوّلها إلى Telethon StringSession ويُعيدها، وإلا يُعيد raw كما هي.
    """
    s = raw.strip()
    if s.startswith("{"):
        import json as _j
        try:
            d = _j.loads(s)
            converted = pyrogram_json_to_telethon(d)
            if converted:
                return converted
        except Exception:
            pass
    return s
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError,
    PhoneNumberInvalidError, FloodWaitError, PasswordHashInvalidError,
    PeerFloodError, UserBannedInChannelError, ChatWriteForbiddenError,
    UserPrivacyRestrictedError,
)
from telethon.tl.functions.auth import ResetAuthorizationsRequest, CheckPasswordRequest, AcceptLoginTokenRequest, ExportLoginTokenRequest
from telethon.password import compute_check
from telethon.tl.functions.account import (
    GetAuthorizationsRequest, ResetAuthorizationRequest,
    GetPasswordRequest, ResetPasswordRequest,
)
from telethon.tl.types import (
    account as tl_account,
)
from telethon.tl.functions.messages import StartBotRequest
from telethon.tl.functions.contacts import ResolveUsernameRequest
import pyotp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
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
    import socket as _hsock
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.socket.setsockopt(_hsock.SOL_SOCKET, _hsock.SO_REUSEADDR, 1)
    server.serve_forever()

_health_server_started = False
def start_health_server():
    global _health_server_started
    if _health_server_started:
        return  # لا تُشغّل مرتين عند إعادة التشغيل الداخلية
    _health_server_started = True
    t = threading.Thread(target=run_health_server, daemon=True)
    t.start()
    logger.info("✅ Health server started")

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
def _safe_int_env(name: str, default: int = 0) -> int:
    """يقرأ متغير بيئة كرقم صحيح، ويرجع القيمة الافتراضية إذا كانت القيمة غير موجودة أو غير صالحة."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"⚠️ المتغير البيئي {name} له قيمة غير صالحة كرقم ({raw!r})، سيتم استخدام {default}.")
        return default

BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
OWNER_ID       = _safe_int_env("OWNER_ID", 0)
API_KEY        = os.getenv("API_KEY", "")
ADMIN_GROUP_ID   = _safe_int_env("ADMIN_GROUP_ID", 0)
NUMBERS_GROUP_ID = _safe_int_env("NUMBERS_GROUP_ID", 0)  # كروب إشعارات الأرقام (منفصل عن كروب الطلبات)
API_URL        = "https://smmmain.com/api/v2"

JUSTANOTHERPANEL_API_KEY = os.getenv("JUSTANOTHERPANEL_API_KEY", "")
SMMFOLLOWS_API_KEY       = os.getenv("SMMFOLLOWS_API_KEY", "")
TELEGRAM_API_ID   = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")

_pending_number_logins = {}
_pending_supervisor_logins = {}   # supervisor_user_id -> {client, phone, phone_code_hash}
_buyer_received_codes = {}  # buyer_user_id -> {"code": str, "time": float} آخر كود وصل بعد البيع
_demo_purchases = {}        # buyer_user_id -> {"phone": str, "session_str": str, "twofa": str, "purchase_time": datetime} — شراء بكود تجريبي (لا يُسجَّل في prize_exchanges)
_pending_bulk_import  = set()  # user_ids ينتظرون إرسال JSON للاستيراد الجماعي
# stock_id -> {"phone", "session", "stock_id", "retries"} — حسابات تحتاج إصلاح تلقائي (طرد + 2FA)
_accounts_needing_fixup: dict = {}
_pending_group_msgs   = {}  # key -> {"text": str, "parse_mode": str} رسائل كروب معلّقة تنتظر موافقة المالك
_expected_2fa_change = {}
_referral_rate_tracker = {}  # inviter_id -> list[float] لكشف رشق الإحالات (5 في 5 ثوانٍ)
_EXPECTED_2FA_WINDOW_SEC = 180
_allow_5min_phones = {}  # phone_number -> {"until": float, "used": bool}
_permanently_allowed_phones = set()  # أرقام فيها جلسة خارجية مسموح لها بالبقاء للأبد
_OWN_BOT_USERNAME: str = ""          # يُضبط عند الإقلاع — يُستخدم لتخطي الإحالة الذاتية
JUSTANOTHERPANEL_API_URL = "https://justanotherpanel.com/api/v2"
SMMFOLLOWS_API_URL       = "https://smmfollows.io/api/v2"

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
PANEL_MAP = {
    1: {"name": "SMMMAIN",         "key": API_KEY,                  "url": API_URL},
    2: {"name": "JustAnotherPanel", "key": JUSTANOTHERPANEL_API_KEY, "url": JUSTANOTHERPANEL_API_URL},
    3: {"name": "SmmFollows",       "key": SMMFOLLOWS_API_KEY,       "url": SMMFOLLOWS_API_URL},
}

# ────────────────────────────────────────────────────────────
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
                cur = self._conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                break
            except _DB_RETRY_EXC as e:
                if attempt == 0:
                    logger.warning(f"⚠️ خطأ في الاتصال بالDB، إعادة المحاولة... ({e})")
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
              active          INTEGER DEFAULT 1,
              service_type    TEXT DEFAULT 'smm'
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS mandatory_sub_orders (
              id            SERIAL PRIMARY KEY,
              user_id       BIGINT NOT NULL,
              bot_username  TEXT NOT NULL,
              start_param   TEXT NOT NULL,
              channels      TEXT DEFAULT '',
              quantity      INTEGER NOT NULL,
              cost_points   INTEGER NOT NULL,
              done_count    INTEGER DEFAULT 0,
              failed_count  INTEGER DEFAULT 0,
              status        TEXT DEFAULT 'pending',
              order_code    TEXT,
              created_at    TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS forced_ref_orders (
              id            SERIAL PRIMARY KEY,
              user_id       BIGINT NOT NULL,
              bot_username  TEXT NOT NULL,
              start_param   TEXT NOT NULL,
              channels      TEXT DEFAULT '',
              quantity      INTEGER NOT NULL,
              cost_points   INTEGER NOT NULL,
              done_count    INTEGER DEFAULT 0,
              failed_count  INTEGER DEFAULT 0,
              status        TEXT DEFAULT 'pending',
              order_code    TEXT,
              created_at    TIMESTAMPTZ DEFAULT NOW()
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
          CREATE TABLE IF NOT EXISTS number_stock (
              id            SERIAL PRIMARY KEY,
              phone_number  TEXT UNIQUE,
              assigned_to   BIGINT,
              assigned_at   TIMESTAMPTZ,
              added_at      TIMESTAMPTZ DEFAULT NOW()
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
              "ALTER TABLE mandatory_channels ADD COLUMN IF NOT EXISTS queued INTEGER DEFAULT 0",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS order_code TEXT",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS owner_seen BOOLEAN DEFAULT FALSE",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS compensated_at TIMESTAMPTZ",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS compensated_pts INTEGER DEFAULT 0",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS compensated_reason TEXT",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS ever_sold BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS session_string TEXT",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS sessions_reset BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS force_listed BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS frozen_at TIMESTAMPTZ",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS twofa_password TEXT",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS last_frozen BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS last_authorized BOOLEAN DEFAULT TRUE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS last_device_count INTEGER DEFAULT -1",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS kicked_at TIMESTAMPTZ",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS auto_2fa_enabled BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS twofa_reset_date TIMESTAMPTZ",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS is_solo BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS can_send_code BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS bot_session_ip TEXT",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS forced_ref_excluded BOOLEAN DEFAULT FALSE",
              "ALTER TABLE services ADD COLUMN IF NOT EXISTS platform TEXT DEFAULT 'tg'",
              "ALTER TABLE users ADD COLUMN IF NOT EXISTS banned INTEGER DEFAULT 0",
              "ALTER TABLE users ADD COLUMN IF NOT EXISTS banned_at TIMESTAMPTZ",
              "ALTER TABLE users ADD COLUMN IF NOT EXISTS ban_reason TEXT",
              "ALTER TABLE channel_join_rewards ADD COLUMN IF NOT EXISTS joined_at TIMESTAMPTZ DEFAULT NOW()",
              "ALTER TABLE mandatory_sub_orders ADD COLUMN IF NOT EXISTS reactivated_count INTEGER DEFAULT 0",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS referral_only BOOLEAN DEFAULT FALSE",
              "ALTER TABLE forced_ref_orders ADD COLUMN IF NOT EXISTS reactivated_count INTEGER DEFAULT 0",
              "ALTER TABLE forced_ref_orders ADD COLUMN IF NOT EXISTS payment_method TEXT DEFAULT 'points'",
              "ALTER TABLE forced_ref_orders ADD COLUMN IF NOT EXISTS cost_stars INTEGER DEFAULT 0",
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
              used_at TIMESTAMPTZ DEFAULT NOW(),
              PRIMARY KEY (code, user_id)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS number_purchase_codes (
              code       TEXT PRIMARY KEY,
              max_uses   INTEGER DEFAULT 1,
              used_count INTEGER DEFAULT 0,
              active     INTEGER DEFAULT 1,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS number_purchase_code_uses (
              code    TEXT,
              user_id BIGINT,
              used_at TIMESTAMPTZ DEFAULT NOW(),
              PRIMARY KEY (code, user_id)
          )""")
          try:
              c.execute("ALTER TABLE promo_uses ADD COLUMN IF NOT EXISTS used_at TIMESTAMPTZ DEFAULT NOW()")
          except Exception:
              pass
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
              joined_at  TIMESTAMPTZ DEFAULT NOW(),
              PRIMARY KEY (user_id, channel_id)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS referral_tasks (
              id                  SERIAL PRIMARY KEY,
              label               TEXT NOT NULL,
              bot_username        TEXT NOT NULL,
              start_param         TEXT NOT NULL,
              mandatory_channels  TEXT DEFAULT '',
              folder_link         TEXT DEFAULT '',
              active              INTEGER DEFAULT 1,
              created_at          TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS referral_completions (
              task_id   INTEGER NOT NULL,
              stock_id  INTEGER NOT NULL,
              status    TEXT DEFAULT 'pending',
              done_at   TIMESTAMPTZ,
              error_msg TEXT,
              PRIMARY KEY (task_id, stock_id)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS supervisors (
              id         SERIAL PRIMARY KEY,
              user_id    BIGINT UNIQUE NOT NULL,
              username   TEXT DEFAULT '',
              added_at   TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS supervisor_accounts (
              id             SERIAL PRIMARY KEY,
              supervisor_id  BIGINT NOT NULL,
              phone_number   TEXT NOT NULL,
              session_string TEXT,
              added_at       TIMESTAMPTZ DEFAULT NOW(),
              UNIQUE(supervisor_id, phone_number)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS gmail_submissions (
              id          SERIAL PRIMARY KEY,
              user_id     BIGINT NOT NULL,
              gmail_email TEXT NOT NULL,
              gmail_pass  TEXT NOT NULL,
              verification_note TEXT DEFAULT '',
              status      TEXT DEFAULT 'pending',
              created_at  TIMESTAMPTZ DEFAULT NOW()
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
              ('maintenance_mode', '0'),
              ('number_exchange_enabled', '0'),
              ('exchange_success_msg', ''),
              ('mandatory_channel_min_members', '0'),
              ('internal_channel_min_members', '0'),
              ('owner_contact_label', '💬 تواصل مع المالك'),
              ('support_contact_label', '🛎 تواصل مع الدعم'),
              ('thank_owner_button_label', '💌 شكر المالك'),
              ('thank_owner_ar_button_label', '🇸🇦 رسالة بالعربية'),
              ('thank_owner_en_button_label', '🇬🇧 Message in English'),
              ('thank_owner_photo_button_label', '🖼️ إرسال صورة'),
              ('thank_owner_ar_prompt', '💌 أرسل رسالة الشكر بالعربية:'),
              ('thank_owner_en_prompt', '💌 Send your thank-you message in English:'),
              ('thank_owner_photo_prompt', '🖼️ أرسل الصورة التي تريد مشاركتها مع المالك:'),
              ('thank_owner_success_message', '✅ تم إرسال شكرك إلى المالك، شكراً لك!'),
              ('channel_leave_penalty', '75'),
              ('mandatory_stars_min_members', '50'),
              ('mandatory_stars_tier1_max', '120'),
              ('mandatory_stars_tier1_price_x100', '50'),   # 0.50 نجمة × 100
                            ('mandatory_stars_tier2_price_x100', '33'),   # 0.33 نجمة × 100
              ('mandatory_points_price', '5'),    # سعر العضو الواحد بالنقاط
              ('mandatory_points_min',   '50'),   # الحد الأدنى للأعضاء
              ('mansub_base_price',    '250'),
              ('mansub_channel_price', '50'),
              ('mansub_visible',       '0'),
              ('forced_ref_base_price',         '250'),   # سعر الإحالة بدون تحقق (نقاط/حساب)
              ('forced_ref_ai_base_price',      '300'),   # سعر الإحالة بتحقق (نقاط/حساب)
              ('forced_ref_channel_price',      '25'),    # سعر القناة (نقاط/قناة) — للنوعين
              ('forced_ref_channel_stars_no_ai','25'),    # سعر القناة بالنجوم — بدون تحقق
              ('forced_ref_channel_stars_ai',   '35'),    # سعر القناة بالنجوم — بتحقق
              ('forced_ref_visible',            '0'),
              ('forced_ref_ai_visible',         '0'),
              ('referral_task_delay',            '30'),  # تأخير بين الحسابات في مهام الإحالة (ثوانٍ)
              ('internal_leave_grace_hours', '24'),
              ('gmail_points_reward', '10000'),
              ('gmail_intro_message', 'للحصول على النقاط يجب عليك تقديم حساب جيميل لا تستخدمه، سيتم مراجعته من قبل المالك وإضافة النقاط بعد التحقق.'),
              ('gmail_button_label', '📧 احصل على نقاط مقابل إيميل جيميل'),
              ('gmail_email_prompt', '📧 *أرسل الإيميل*\n\nأرسل عنوان البريد الإلكتروني فقط بدون أي شيء آخر:'),
              ('gmail_password_prompt', '🔐 *أرسل الباسورد*\n\nأرسل كلمة مرور الحساب فقط بدون أي شيء آخر:'),
              ('gmail_verification_note_prompt', '💬 <b>اكتب رسالتك للمالك</b>\n\nيجب كتابة ملاحظة قبل إرسال إشعار إكمال التحقق.'),
              ('gmail_reject_wrong_email_msg', '❌ تم رفض طلبك بسبب أن الإيميل الذي أرسلته خاطئ أو غير صحيح. يرجى التحقق من الإيميل والمحاولة مجدداً.'),
              ('gmail_reject_wrong_pass_caption', '❌ تم رفض طلبك بسبب أن كلمة المرور خاطئة. شاهد الفيديو التالي لمعرفة كيفية إدخال الباسورد الصحيح.'),
              ('gmail_reject_wrong_pass_video', ''),
              ('gmail_reject_need_verify_caption', '❌ تم رفض طلبك لأن الحساب يحتاج إلى تحقق. شاهد الفيديو التالي لمعرفة كيفية إتمام التحقق.'),
              ('gmail_reject_need_verify_video', ''),
          ]
          for k, v in default_settings:
              c.execute(
                  "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                  (k, v)
              )
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE users ADD COLUMN verified INTEGER DEFAULT 0")
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute(
                  "ALTER TABLE gmail_submissions "
                  "ADD COLUMN IF NOT EXISTS rejection_reason TEXT DEFAULT ''"
              )
              c.execute(
                  "ALTER TABLE gmail_submissions "
                  "ADD COLUMN IF NOT EXISTS verification_completed BOOLEAN DEFAULT FALSE"
              )
              c.execute(
                  "ALTER TABLE gmail_submissions "
                  "ADD COLUMN IF NOT EXISTS verification_notified BOOLEAN DEFAULT FALSE"
              )
              c.execute(
                  "ALTER TABLE gmail_submissions "
                  "ADD COLUMN IF NOT EXISTS verification_note TEXT DEFAULT ''"
              )
      except Exception as e:
          logger.warning(f"⚠️ فشل تحديث أعمدة تحقق الإيميل: {e}")
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE services ADD COLUMN panel INTEGER DEFAULT 1")
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE users ADD COLUMN referral_credited INTEGER DEFAULT 0")
              c.execute("UPDATE users SET referral_credited=1 WHERE invited_by IS NOT NULL AND invited_by != 0")
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS partial_refund_pts INTEGER DEFAULT 0")
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_points_blocked INTEGER DEFAULT 0")
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credited_at TIMESTAMPTZ")
              c.execute(
                  "UPDATE users SET credited_at=joined_at::timestamptz "
                  "WHERE referral_credited=1 AND credited_at IS NULL"
              )
      except Exception as e:
          logger.warning(f"⚠️ فشل تعبئة credited_at للدعوات القديمة: {e}")
      try:
          with db_conn() as c:
              fixed = c.execute(
                  "UPDATE mandatory_channels SET funding_type='mandatory' "
                  "WHERE funding_type='mandatory_points'"
              ).rowcount
          if fixed:
              logger.info(f"✅ تم تصحيح {fixed} قناة إجبارية كانت مخزّنة بـ mandatory_points → mandatory")
      except Exception as e:
          logger.warning(f"⚠️ فشل تصحيح القنوات الإجبارية القديمة: {e}")

      try:
          with db_conn() as c:
              c.execute("ALTER TABLE services ADD COLUMN IF NOT EXISTS service_type TEXT DEFAULT 'smm'")
      except Exception: pass
      try:
          with db_conn() as c:
              if not c.execute("SELECT id FROM services WHERE service_type='mandatory_sub' LIMIT 1").fetchone():
                  c.execute(
                      "INSERT INTO services (category,api_service_id,panel,platform,name_ar,description,min_qty,max_qty,price_per_point,active,service_type) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                      ('start_bot',0,0,'tg','🔑 الاشتراك الإجباري','حسابات المخزون تنضم لقنواتك ثم تضغط ستارت',1,9999,0,1,'mandatory_sub')
                  )
      except Exception as _e: logger.warning(f'mansub seed: {_e}')
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE referral_tasks ADD COLUMN IF NOT EXISTS mandatory_channels TEXT DEFAULT ''")
              c.execute("ALTER TABLE referral_tasks ADD COLUMN IF NOT EXISTS folder_link TEXT DEFAULT ''")
      except Exception:
          pass

      try:
          with db_conn() as c:
              c.execute(
                  "UPDATE menu_items SET label=%s WHERE action_type='builtin' AND action_value='cat:start_bot' AND label != %s",
                  ("🤖 رشق بدء (ستارت) بوت", "🤖 رشق بدء (ستارت) بوت")
              )
      except Exception:
          pass
      try:
          with db_conn() as c:
              svcs_with_desc = c.execute(
                  "SELECT id, description, price_per_point FROM services WHERE description IS NOT NULL AND description != ''"
              ).fetchall()
          cleaned = 0
          for s in svcs_with_desc:
              stripped = _strip_price_from_desc(s["description"], float(s["price_per_point"] or 0))
              if stripped != (s["description"] or "").strip():
                  with db_conn() as c:
                      c.execute("UPDATE services SET description=%s WHERE id=%s", (stripped, s["id"]))
                  cleaned += 1
          if cleaned:
              logger.info(f"🧹 تم تنظيف السعر من وصف {cleaned} خدمة تلقائياً.")
      except Exception as e:
          logger.warning(f"⚠️ فشل تنظيف أوصاف الأسعار: {e}")

def _normalize_desc(desc: str) -> str:
    """يُطبّع الاختصارات الشائعة في أوصاف خدمات SMM إلى العربية.
    K → ألف  |  /D → /يوم  |  /H → /ساعة  |  /W → /أسبوع  |  /M → /شهر
    كما يُصحّح 'كيلوجرام' و'كيلو' المكتوبة بدلاً من 'ألف' خطأً."""
    if not desc:
        return desc

    t = desc

    t = re.sub(r"كيلو\s*جرام", "ألف", t)
    t = re.sub(r"كيلوجرام",     "ألف", t)
    t = re.sub(r"\bكيلو\b",     "ألف", t)

    t = re.sub(r"/\s*(?:day|daily)\b",   "/يوم",    t, flags=re.IGNORECASE)
    t = re.sub(r"/\s*D\b",               "/يوم",    t, flags=re.IGNORECASE)
    t = re.sub(r"\bper\s+day\b",         "يومياً",  t, flags=re.IGNORECASE)

    t = re.sub(r"/\s*(?:hour|hr)\b",     "/ساعة",   t, flags=re.IGNORECASE)
    t = re.sub(r"/\s*H\b",               "/ساعة",   t, flags=re.IGNORECASE)
    t = re.sub(r"\bper\s+hour\b",        "بالساعة", t, flags=re.IGNORECASE)

    t = re.sub(r"/\s*(?:week|wk)\b",     "/أسبوع",  t, flags=re.IGNORECASE)
    t = re.sub(r"/\s*W\b",               "/أسبوع",  t, flags=re.IGNORECASE)

    t = re.sub(r"/\s*(?:month|mo)\b",    "/شهر",    t, flags=re.IGNORECASE)
    t = re.sub(r"/\s*M\b",               "/شهر",    t, flags=re.IGNORECASE)

    t = re.sub(r"(\d)\s*[Kk]\b", r"\1 ألف", t)   # 5K → 5 ألف
    t = re.sub(r"\b[Kk]\b",      "ألف",     t)   # K وحيدة → ألف

    return t.strip()

def _strip_price_from_desc(desc: str, price_per_point: float = 0.0) -> str | None:
    """يُطبّع الاختصارات أولاً ثم يحذف جزء السعر فقط، ويُبقي باقي النص.
    يعيد None إذا لم يتبق شيء بعد الحذف."""
    if not desc:
        return None

    text = _normalize_desc(desc)   # K→ألف، /D→/يوم، كيلوجرام→ألف … أولاً

    text = re.sub(r"\$\s*\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\d+(?:[.,]\d+)?\s*\$", "", text)
    text = re.sub(r"USD\s*\d+(?:[.,]\d+)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\d+(?:[.,]\d+)?\s*USD", "", text, flags=re.IGNORECASE)

    if price_per_point and price_per_point > 0:
        panel_price = price_per_point / 100_000
        def _remove_price_num(m):
            val = float(m.group(0).replace(",", "."))
            if val > 0 and abs(val - panel_price) / panel_price <= 0.5:
                return ""
            return m.group(0)
        text = re.sub(r"\d+(?:[.,]\d+)?", _remove_price_num, text)

    text = re.sub(r"[-|/\\،,;:\s]+$", "", text.strip())
    text = re.sub(r"^[-|/\\،,;:\s]+", "", text.strip())
    text = re.sub(r"\s{2,}", " ", text).strip()

    return text if text else None

def _desc_has_price(desc: str, price_per_point: float = 0.0) -> bool:
    if not desc:
        return False
    stripped = _strip_price_from_desc(desc, price_per_point)
    return stripped != desc.strip()

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

THANK_OWNER_SETTINGS = {
    "thank_owner_button_label": ("نص زر «شكر المالك»", "💌 شكر المالك"),
    "thank_owner_ar_button_label": ("نص زر الرسالة العربية", "🇸🇦 رسالة بالعربية"),
    "thank_owner_en_button_label": ("نص زر الرسالة الإنجليزية", "🇬🇧 Message in English"),
    "thank_owner_photo_button_label": ("نص زر إرسال الصورة", "🖼️ إرسال صورة"),
    "thank_owner_ar_prompt": ("رسالة طلب النص العربي", "💌 أرسل رسالة الشكر بالعربية:"),
    "thank_owner_en_prompt": ("رسالة طلب النص الإنجليزي", "💌 Send your thank-you message in English:"),
    "thank_owner_photo_prompt": ("رسالة طلب الصورة", "🖼️ أرسل الصورة التي تريد مشاركتها مع المالك:"),
    "thank_owner_success_message": ("رسالة نجاح الإرسال", "✅ تم إرسال شكرك إلى المالك، شكراً لك!"),
}

def is_maintenance_on() -> bool:
    return int(get_setting("maintenance_mode") or "0") == 1

def is_number_exchange_on() -> bool:
    return int(get_setting("number_exchange_enabled") or "0") == 1

MAINTENANCE_MESSAGE = (
    "🛠 *البوت في وضع الصيانة حالياً*\n\n"
    "نعمل على تحسين تجربتك، ونعتذر عن أي إزعاج.\n"
    "سيعود البوت للعمل خلال وقت قصير — شكراً لتفهّمك 💙"
)

def get_or_create_user(user_id: int, username: str, full_name: str, invited_by: int = 0) -> dict:
    with db_conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            c.execute("UPDATE users SET username=?, full_name=? WHERE user_id=?",
                      (username, full_name, user_id))
            return dict(row)
        num_row = c.execute(
            "UPDATE settings SET value=(value::int+1)::text WHERE key='total_bot_users' RETURNING value::int AS total"
        ).fetchone()
        total = num_row["total"] if num_row else 1
        c.execute(
            "INSERT INTO users (user_id, username, full_name, invited_by, bot_user_num, verified) VALUES (%s,%s,%s,%s,%s,0)",
            (user_id, username, full_name, invited_by, total)
        )
        return dict(c.execute("SELECT * FROM users WHERE user_id=%s", (user_id,)).fetchone())

def set_user_verified(user_id: int):
    with db_conn() as c:
        c.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))

def credit_referral_if_pending(user_id: int, context=None):
    """يمنح نقاط الإحالة للداعي مرة واحدة فقط، بعد اشتراك المدعو بالقنوات الإجبارية واجتيازه التحقق.
    يُعيد (inviter_id, points) عند المنح، أو None إن لم يكن هناك شيء لمنحه."""
    with db_conn() as c:
        row = c.execute(
            "SELECT invited_by, referral_credited FROM users WHERE user_id=%s", (user_id,)
        ).fetchone()
        if not row:
            return None
        invited_by = row["invited_by"]
        already = row["referral_credited"]
        if not invited_by or invited_by == 0 or invited_by == user_id or already:
            return None
        rp = int(get_setting("referral_points") or "30")
        c.execute(
            "UPDATE users SET referral_credited=1, credited_at=NOW() WHERE user_id=%s AND referral_credited=0",
            (user_id,)
        )
        if c.rowcount == 0:
            return None
        c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (rp, invited_by))
    import asyncio as _aio
    _bot_ref = getattr(context, 'bot', None) if context else None
    if _bot_ref and NUMBERS_GROUP_ID:
        _inviter_row  = get_user(invited_by) or {}
        _invited_row  = get_user(user_id)    or {}
        _inviter_name = md_escape(_inviter_row.get('full_name') or f"ID:{invited_by}")
        _inviter_un   = f" (@{md_escape(_inviter_row['username'])})" if _inviter_row.get('username') else ''
        _invited_name = md_escape(_invited_row.get('full_name')  or f"ID:{user_id}")
        _invited_un   = f" (@{md_escape(_invited_row['username'])})"  if _invited_row.get('username')  else ''
        with db_conn() as _rc:
            _total_ref = (_rc.execute(
                "SELECT COUNT(*) AS cnt FROM users WHERE invited_by=%s AND referral_credited=1",
                (invited_by,)
            ).fetchone() or {}).get("cnt", 1)
        _ref_notif = (
            f"🤝 *إحالة جديدة ناجحة!*\n\n"
            f"👤 *المُحيل:* {_inviter_name}{_inviter_un} (`{invited_by}`)\n"
            f"🆕 *المدعو:* {_invited_name}{_invited_un} (`{user_id}`)\n"
            f"💰 *النقاط الممنوحة:* {rp} نقطة\n"
            f"📊 *إجمالي إحالات المُحيل:* {_total_ref}"
        )
        try:
            _aio.ensure_future(_bot_ref.send_message(NUMBERS_GROUP_ID, _ref_notif, parse_mode='Markdown'))
        except Exception:
            pass

    import time as _time_mod
    _now_ts = _time_mod.time()
    _bucket = _referral_rate_tracker.setdefault(invited_by, [])
    _bucket.append(_now_ts)
    _referral_rate_tracker[invited_by] = [t for t in _bucket if _now_ts - t <= 300]
    if len(_referral_rate_tracker[invited_by]) >= 5 and context is not None:
        with db_conn() as _rc:
            _rc.execute("UPDATE users SET referral_points_blocked=1 WHERE user_id=%s", (invited_by,))
        _referral_rate_tracker.pop(invited_by, None)
        _bot2 = getattr(context, 'bot', None)
        if _bot2 and OWNER_ID:
            _rq = get_user(invited_by) or {}
            _rq_name = _rq.get('full_name') or f"ID:{invited_by}"
            _rq_un = (f" (@{_rq['username']})" if _rq.get('username') else '')
            _fraud_text = (
                f"⚠️ *تنبيه: رشق إحالات محتمل!*\n\n"
                f"👤 المُحيل: {_rq_name}{_rq_un} (`{invited_by}`)\n"
                f"📊 تلقّى 5+ إحالات في أقل من 5 دقائق\n"
                f"💰 نقاط آخر إحالة: {rp} نقطة\n"
                f"🔒 تم تقييده تلقائياً\n\n"
                f"اختر الإجراء:"
            )
            _fraud_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ إبقاء + رفع التقييد",   callback_data=f"os:ref_keep:{invited_by}:{rp}")],
                [InlineKeyboardButton("❌ خصم الإحالة + رفع التقييد", callback_data=f"os:ref_deduct:{invited_by}:{rp}")],
                [InlineKeyboardButton("➕ خصم نقاط إضافية",               callback_data=f"os:ref_extra:{invited_by}:{rp}")],
                [InlineKeyboardButton("🔓 رفع التقييد فقط",            callback_data=f"os:ref_unblock:{invited_by}")],
            ])
            try:
                _aio.ensure_future(_bot2.send_message(OWNER_ID, _fraud_text, parse_mode='Markdown', reply_markup=_fraud_kb))
            except Exception:
                pass
    return (invited_by, rp)

def _referral_counter_reset_at():
    """يُرجع لحظة آخر تصفير للعداد (UTC) إن وُجدت، وإلا None."""
    raw = get_setting("referral_counter_reset_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def reset_referral_counter():
    """يصفّر عداد 'الأكثر إرسالاً لرابط الدعوة' من الآن، دون المساس بنقاط
    الأعضاء أو حالة الدعوات الفعلية — فقط يستثني ما قبل هذه اللحظة من العدّ."""
    set_setting("referral_counter_reset_at", datetime.now(timezone.utc).isoformat())

def _referral_period_bounds(period: str):
    """يُرجع (since_utc, عنوان الفترة) لفترة زمنية معيّنة، محسوبة بالتوقيت العالمي (UTC)،
    مع مراعاة آخر عملية تصفير للعداد إن وُجدت (يُؤخذ الأحدث بين الاثنين)."""
    now = datetime.now(timezone.utc)
    if period == "24h":
        since, title = now - timedelta(hours=24), "آخر 24 ساعة"
    elif period == "day":
        since, title = now.replace(hour=0, minute=0, second=0, microsecond=0), "اليوم (منذ 00:00 بالتوقيت العالمي)"
    elif period == "week":
        since, title = now - timedelta(days=7), "آخر أسبوع"
    elif period == "month":
        since, title = now - timedelta(days=30), "آخر شهر"
    else:
        since, title = None, "كل الأوقات"
    reset_at = _referral_counter_reset_at()
    if reset_at is not None and (since is None or reset_at > since):
        since = reset_at
    return since, title

def get_top_referrers_since(since_dt, limit: int = 10):
    """يُرجع قائمة أكثر الأعضاء إرسالاً لرابط الدعوة (دعوات مكتملة/معتمدة فقط)
    منذ لحظة زمنية محدّدة (UTC)، أو لكل الأوقات إن كانت since_dt=None."""
    with db_conn() as c:
        if since_dt is None:
            rows = c.execute(
                "SELECT invited_by, COUNT(*) as cnt FROM users "
                "WHERE invited_by IS NOT NULL AND invited_by != 0 AND referral_credited=1 "
                "GROUP BY invited_by ORDER BY cnt DESC LIMIT %s",
                (limit,)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT invited_by, COUNT(*) as cnt FROM users "
                "WHERE invited_by IS NOT NULL AND invited_by != 0 AND referral_credited=1 "
                "AND credited_at IS NOT NULL AND credited_at >= %s "
                "GROUP BY invited_by ORDER BY cnt DESC LIMIT %s",
                (since_dt, limit)
            ).fetchall()
    return rows

def _format_top_referrers(rows, title: str) -> str:
    lines = [f"🏆 *الأكثر إرسالاً لرابط الدعوة — {title}:*\n"]
    if not rows:
        lines.append("لا توجد دعوات مكتملة خلال هذه الفترة.")
        return "\n".join(lines)
    inviter_ids = [r["invited_by"] for r in rows]
    inviters_map = {}
    if inviter_ids:
        placeholders = ",".join(["%s"] * len(inviter_ids))
        with db_conn() as _c:
            _batch = _c.execute(
                f"SELECT user_id, username, full_name FROM users WHERE user_id IN ({placeholders})",
                tuple(inviter_ids)
            ).fetchall()
        for u in _batch:
            inviters_map[u["user_id"]] = u
    for i, r in enumerate(rows, start=1):
        inviter = inviters_map.get(r["invited_by"])
        if inviter and inviter.get("username"):
            name = md_escape(f"@{inviter['username']}")
        elif inviter and inviter.get("full_name"):
            name = md_escape(inviter["full_name"])
        else:
            name = f"ID {r['invited_by']}"
        lines.append(f"{i}. {name} — {r['cnt']} دعوة")
    return "\n".join(lines)

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────

def get_referral_contest() -> dict:
    """يُرجع معلومات المسابقة الحالية من قاعدة الإعدادات."""
    ctype     = get_setting("referral_contest_type")  or "none"
    start_raw = get_setting("referral_contest_start") or ""
    end_raw   = get_setting("referral_contest_end")   or ""
    start_dt = end_dt = None
    try:
        if start_raw:
            start_dt = datetime.fromisoformat(start_raw)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        if end_raw:
            end_dt = datetime.fromisoformat(end_raw)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return {"type": ctype, "start": start_dt, "end": end_dt}

def _parse_contest_duration(text: str):
    """يُحوّل نصاً مثل 7s / 7m / 7h / 7d إلى timedelta، أو None إن كانت الصيغة خاطئة."""
    m = re.match(r"^(\d+)([smhd])$", text.strip().lower())
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2)
    if unit == "s": return timedelta(seconds=val)
    if unit == "m": return timedelta(minutes=val)
    if unit == "h": return timedelta(hours=val)
    if unit == "d": return timedelta(days=val)
    return None

def _format_contest_time_remaining(end_dt) -> str:
    """يُرجع نص الوقت المتبقي بصيغة مقروءة بالعربية."""
    now = datetime.now(timezone.utc)
    if end_dt is None or end_dt <= now:
        return "انتهت المسابقة"
    total_seconds = int((end_dt - now).total_seconds())
    days    = total_seconds // 86400
    hours   = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600)  // 60
    seconds = total_seconds % 60
    parts = []
    if days:              parts.append(f"{days} يوم")
    if hours:             parts.append(f"{hours} ساعة")
    if minutes:           parts.append(f"{minutes} دقيقة")
    if seconds and not days: parts.append(f"{seconds} ثانية")
    return " و ".join(parts) if parts else "أقل من ثانية"

def add_numbers_to_stock(numbers: list) -> int:
    """يضيف أرقاماً جديدة لمخزون أرقام تيلغرام (يتجاهل المكرر). يُرجع عدد الأرقام المضافة فعلياً."""
    added = 0
    with db_conn() as c:
        for n in numbers:
            n = n.strip()
            if not n:
                continue
            try:
                c.execute(
                    "INSERT INTO number_stock (phone_number) VALUES (%s) ON CONFLICT (phone_number) DO NOTHING",
                    (n,)
                )
                if c.rowcount:
                    added += 1
            except Exception:
                pass
    return added

COUNTRY_CODES = {
    "1": "🇺🇸 أمريكا/كندا", "7": "🇷🇺 روسيا", "20": "🇪🇬 مصر", "27": "🇿🇦 جنوب أفريقيا",
    "30": "🇬🇷 اليونان", "31": "🇳🇱 هولندا", "32": "🇧🇪 بلجيكا", "33": "🇫🇷 فرنسا",
    "34": "🇪🇸 إسبانيا", "36": "🇭🇺 المجر", "39": "🇮🇹 إيطاليا", "40": "🇷🇴 رومانيا",
    "44": "🇬🇧 بريطانيا", "45": "🇩🇰 الدنمارك", "46": "🇸🇪 السويد", "48": "🇵🇱 بولندا",
    "49": "🇩🇪 ألمانيا", "51": "🇵🇪 بيرو", "52": "🇲🇽 المكسيك", "54": "🇦🇷 الأرجنتين",
    "55": "🇧🇷 البرازيل", "56": "🇨🇱 تشيلي", "60": "🇲🇾 ماليزيا", "62": "🇮🇩 إندونيسيا",
    "63": "🇵🇭 الفلبين", "64": "🇳🇿 نيوزيلندا", "65": "🇸🇬 سنغافورة", "66": "🇹🇭 تايلاند",
    "81": "🇯🇵 اليابان", "82": "🇰🇷 كوريا الجنوبية", "84": "🇻🇳 فيتنام", "86": "🇨🇳 الصين",
    "90": "🇹🇷 تركيا", "91": "🇮🇳 الهند", "92": "🇵🇰 باكستان", "93": "🇦🇫 أفغانستان",
    "94": "🇱🇰 سريلانكا", "95": "🇲🇲 ميانمار", "98": "🇮🇷 إيران",
    "212": "🇲🇦 المغرب", "213": "🇩🇿 الجزائر", "216": "🇹🇳 تونس", "218": "🇱🇾 ليبيا",
    "220": "🇬🇲 غامبيا", "221": "🇸🇳 السنغال", "234": "🇳🇬 نيجيريا", "249": "🇸🇩 السودان",
    "251": "🇪🇹 إثيوبيا", "254": "🇰🇪 كينيا", "255": "🇹🇿 تنزانيا", "256": "🇺🇬 أوغندا",
    "260": "🇿🇲 زامبيا", "351": "🇵🇹 البرتغال", "355": "🇦🇱 ألبانيا", "358": "🇫🇮 فنلندا",
    "370": "🇱🇹 ليتوانيا", "371": "🇱🇻 لاتفيا", "372": "🇪🇪 إستونيا", "373": "🇲🇩 مولدوفا",
    "374": "🇦🇲 أرمينيا", "375": "🇧🇾 بيلاروسيا", "376": "🇦🇩 أندورا", "380": "🇺🇦 أوكرانيا",
    "381": "🇷🇸 صربيا", "385": "🇭🇷 كرواتيا", "386": "🇸🇮 سلوفينيا", "420": "🇨🇿 التشيك",
    "421": "🇸🇰 سلوفاكيا", "212": "🇲🇦 المغرب",
    "852": "🇭🇰 هونغ كونغ", "855": "🇰🇭 كمبوديا", "880": "🇧🇩 بنغلاديش", "886": "🇹🇼 تايوان",
    "960": "🇲🇻 المالديف", "961": "🇱🇧 لبنان", "962": "🇯🇴 الأردن", "963": "🇸🇾 سوريا",
    "964": "🇮🇶 العراق", "965": "🇰🇼 الكويت", "966": "🇸🇦 السعودية", "967": "🇾🇪 اليمن",
    "968": "🇴🇲 عمان", "970": "🇵🇸 فلسطين", "971": "🇦🇪 الإمارات", "972": "🇮🇱 إسرائيل",
    "973": "🇧🇭 البحرين", "974": "🇶🇦 قطر", "975": "🇧🇹 بوتان", "976": "🇲🇳 منغوليا",
    "992": "🇹🇯 طاجيكستان", "993": "🇹🇲 تركمانستان", "994": "🇦🇿 أذربيجان", "995": "🇬🇪 جورجيا",
    "996": "🇰🇬 قيرغيزستان", "998": "🇺🇿 أوزبكستان",
}
_COUNTRY_PREFIXES_SORTED = sorted(COUNTRY_CODES.keys(), key=len, reverse=True)

def guess_country(phone: str) -> str:
    """يحاول تحديد الدولة من مقدمة رقم الهاتف الدولي (+964...)."""
    digits = phone.lstrip("+").strip()
    for prefix in _COUNTRY_PREFIXES_SORTED:
        if digits.startswith(prefix):
            return COUNTRY_CODES[prefix]
    return "🌍 غير معروفة"

def _smtp_verify_gmail(email: str) -> tuple[bool | None, str]:
    """
    يتحقق من وجود حساب Gmail عبر SMTP handshake مع خوادم Google.
    يُرجع (True, "") إن وُجد الإيميل،
             (False, سبب) إن لم يوجد،
             (None, سبب) إن تعذّر الاتصال بالخوادم.
    هذه الدالة blocking — نفّذها دائماً عبر run_in_executor.
    """
    import smtplib, socket as _sock, re as _re
    _email = email.strip().lower()
    # تحقق أساسي من الصيغة
    if not _re.match(r"^[^@\s]+@gmail\.com$", _email):
        return False, "الإيميل ليس من نطاق @gmail.com"
    mx_host = "aspmx.l.google.com"
    helo    = "verify.bot"
    sender  = "verify@verify.bot"
    try:
        smtp = smtplib.SMTP(timeout=12)
        smtp.connect(mx_host, 25)
        smtp.ehlo(helo)
        smtp.mail(sender)
        code, msg = smtp.rcpt(_email)
        smtp.quit()
        msg_str = msg.decode(errors="ignore") if isinstance(msg, bytes) else str(msg)
        if code == 250:
            return True, ""
        elif code in (550, 551, 553):
            return False, msg_str[:120]
        else:
            # كود غير متوقع — نتجاهل ولا نرفض
            return None, f"كود غير متوقع: {code}"
    except _sock.timeout:
        return None, "انتهت مهلة الاتصال بخوادم Google"
    except _sock.gaierror:
        return None, "تعذّر الوصول لخوادم Google (DNS)"
    except smtplib.SMTPException as _se:
        return None, str(_se)[:120]
    except Exception as _e:
        return None, str(_e)[:120]

_ID_AGE_TABLE = [
    (100_000_000, "2013 أو قبل"),
    (200_000_000, "2014"),
    (300_000_000, "2015"),
    (400_000_000, "2016"),
    (600_000_000, "2017"),
    (900_000_000, "2018"),
    (1_100_000_000, "2019"),
    (1_400_000_000, "2020"),
    (1_700_000_000, "2021"),
    (2_000_000_000, "2022"),
    (5_000_000_000, "2023"),
    (6_500_000_000, "2024"),
    (7_500_000_000, "2025"),
]

def estimate_registration_year(user_id: int) -> str:
    """تقدير تقريبي (غير رسمي) لسنة إنشاء الحساب اعتماداً على رقم الـID، لأن تيليجرام لا يوفر تاريخ إنشاء دقيق."""
    for threshold, year in _ID_AGE_TABLE:
        if user_id < threshold:
            return year
    return "2026 أو أحدث"

def parse_spam_reply(raw_text: str) -> dict:
    """يحلّل رد @SpamBot الرسمي ليستخرج: هل هناك تقييد حالياً، وحتى أي وقت/تاريخ ينتهي (إن ذُكر صريحاً)."""
    text = (raw_text or "").strip()
    result = {"restricted": None, "until": None, "raw": text}
    if not text:
        return result
    lower = text.lower()
    if any(k in lower for k in ("good news", "no limits", "free as a bird", "لا يوجد", "no restrictions")):
        result["restricted"] = False
        return result
    result["restricted"] = True
    patterns = [
        r"until\s+([0-9]{1,2}[:.][0-9]{2}(?:\s*(?:UTC|GMT))?[^.\n]{0,40})",
        r"until\s+([A-Za-z0-9,\s\-\/]{4,40}?(?:UTC|GMT|\d{4}))",
        r"limited for\s+([A-Za-z0-9\s]{2,30})",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            result["until"] = m.group(1).strip().rstrip(". ")
            break
    return result

async def check_spam_status(client: TelegramClient) -> str:
    """يفحص حالة الحظر/التقييد عبر إرسال رسالة تلقائية لبوت @SpamBot الرسمي وقراءة رده.
    للحصول على تفاصيل منفصلة (مقيّد أم لا، ومتى ينتهي)، استخدم check_spam_status_detailed."""
    detail = await check_spam_status_detailed(client)
    return detail["display"]

async def check_spam_status_detailed(client: TelegramClient) -> dict:
    """نسخة تفصيلية من فحص @SpamBot: تُرجع dict فيه restricted (True/False/None) و until (نص وقت الانتهاء إن وُجد)
    والنص الكامل الأصلي، بالإضافة إلى نص عرض جاهز display."""
    try:
        await client.send_message("SpamBot", "/start")
        await asyncio.sleep(3)
        msgs = await client.get_messages("SpamBot", limit=1)
        if not msgs or not msgs[0].message:
            return {"restricted": None, "until": None, "raw": None,
                     "display": "⚠️ لم يصل رد من SpamBot، حاول مجدداً"}
        parsed = parse_spam_reply(msgs[0].message)
        if parsed["restricted"] is False:
            parsed["display"] = "✅ غير مقيّد (حساب سليم)"
        elif parsed["restricted"] is True:
            if parsed["until"]:
                parsed["display"] = f"🚫 مقيّد من الإرسال — ينتهي القيد: {parsed['until']}"
            else:
                parsed["display"] = f"🚫 مقيّد من الإرسال (لم يُذكر وقت انتهاء صريح):\n{msgs[0].message[:300]}"
        else:
            parsed["display"] = f"ℹ️ رد SpamBot غير واضح:\n{msgs[0].message[:300]}"
        return parsed
    except Exception as e:
        logger.error(f"❌ خطأ في فحص SpamBot: {e}")
        return {"restricted": None, "until": None, "raw": None,
                "display": "⚠️ تعذر الفحص حالياً، حاول لاحقاً"}

async def get_device_count(client: TelegramClient) -> int:
    """يُرجع عدد الأجهزة/الجلسات النشطة المسجّلة دخول على هذا الحساب."""
    try:
        result = await client(GetAuthorizationsRequest())
        return len(result.authorizations)
    except Exception as e:
        logger.error(f"❌ خطأ في جلب عدد الأجهزة: {e}")
        return -1

async def get_authorizations_detail(client: TelegramClient) -> list:
    """يُرجع قائمة تفصيلية بكل الأجهزة: الاسم، تاريخ التسجيل، آخر نشاط، هل هو الجهاز الحالي."""
    try:
        result = await client(GetAuthorizationsRequest())
        devices = []
        for auth in result.authorizations:
            devices.append({
                "hash":         auth.hash,
                "current":      auth.current,
                "device":       auth.device_model or "غير معروف",
                "app":          auth.app_name or "غير معروف",
                "platform":     auth.platform or "",
                "country":      auth.country or "",
                "date_created": auth.date_created,
                "date_active":  auth.date_active,
            })
        return devices
    except Exception as e:
        logger.error(f"❌ خطأ في جلب تفاصيل الأجهزة: {e}")
        return []

async def get_session_ip(client: TelegramClient) -> str | None:
    """يُرجع عنوان IP لجلسة البوت الحالية (current=True) من قائمة التفويضات.
    يُستخدم لاكتشاف خطف الجلسة الصامت عبر نفس auth_key من IP مختلف."""
    try:
        result = await client(GetAuthorizationsRequest())
        for auth in result.authorizations:
            if auth.current:
                return auth.ip
    except Exception:
        pass
    return None

async def check_account_frozen(client: TelegramClient, stock_id: int | None = None) -> tuple:
    """
    يفحص إذا كان الحساب مجمّداً/محذوفاً.
    يحفظ تاريخ أول اكتشاف للتجميد في قاعدة البيانات (frozen_at).
    يُرجع (is_frozen: bool, status_text: str, frozen_at_str: str | None).
    """
    is_frozen = False
    status_text = "🟢 نشط"
    frozen_at_str = None
    try:
        me = await client.get_me()
        if me is None or getattr(me, "deleted", False):
            is_frozen = True
            status_text = "🔴 مجمّد/محذوف (الحساب يظهر محذوفاً)"
        else:
            # ── فحص التجميد الفعلي عبر FROZEN_METHOD_INVALID ──────────────
            # الحساب المجمّد: الجلسة سليمة لكن العمليات تُرجع FROZEN_METHOD_INVALID
            try:
                from telethon.tl.functions.account import GetAuthorizationsRequest as _GAR
                await client(_GAR())
            except Exception as _fe:
                if "FROZEN_METHOD_INVALID" in str(_fe) or "FROZEN" in str(_fe).upper():
                    is_frozen = True
                    status_text = "🧊 مجمّد من تيليجرام (يظهر محذوفاً للآخرين)"
    except Exception as e:
        err = str(e).lower()
        if any(k in err for k in ("auth_key_unregistered", "user_deactivated", "session_revoked", "deactivated_ban")):
            is_frozen = True
            status_text = "🔴 محظور/جلسة ألغيت نهائياً"
        elif "frozen" in err or "FROZEN" in str(e):
            is_frozen = True
            status_text = "🧊 مجمّد من تيليجرام"
        else:
            status_text = f"⚠️ تعذّر الفحص: {e}"

    if is_frozen and stock_id is not None:
        try:
            with db_conn() as c:
                row = c.execute(
                    "SELECT frozen_at FROM number_stock WHERE id=%s", (stock_id,)
                ).fetchone()
                if row:
                    if row["frozen_at"] is None:
                        c.execute(
                            "UPDATE number_stock SET frozen_at=NOW() WHERE id=%s", (stock_id,)
                        )
                        frozen_at_str = "الآن (تم اكتشافه للتو)"
                    else:
                        fa = row["frozen_at"]
                        if hasattr(fa, "strftime"):
                            frozen_at_str = fa.strftime("%Y-%m-%d %H:%M UTC")
                        else:
                            frozen_at_str = str(fa)
        except Exception as db_err:
            logger.error(f"❌ خطأ في حفظ frozen_at: {db_err}")

    return is_frozen, status_text, frozen_at_str

async def _fetch_code_for_delivery(session_str: str) -> str | None:
    """يحاول جلب آخر كود تحقق من رسائل 777000 عبر الجلسة — للإرسال الفوري عند التسليم."""
    if not (session_str and TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return None
    cli = None
    try:
        cli = TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(cli.connect(), timeout=15)
        if not await asyncio.wait_for(cli.is_user_authorized(), timeout=8):
            return None
        import datetime as _dt_cfd
        _cfd_after = _dt_cfd.datetime.now(_dt_cfd.timezone.utc) - _dt_cfd.timedelta(minutes=15)
        raw, _raw_date = await fetch_last_login_code(cli, after_date=_cfd_after)
        if raw:
            m = re.search(r'(\d{4,7})', raw)
            if m:
                return m.group(1)
    except Exception:
        pass
    finally:
        try:
            if cli: await cli.disconnect()
        except Exception:
            pass
    return None

async def fetch_last_login_code(client: TelegramClient, after_date=None):
    """يجلب آخر رسالة كود تفعيل وصلت من حساب تيليجرام الرسمي (777000) لهذا الرقم.
    إذا أُعطي after_date، يُرجع فقط الأكواد التي وصلت بعد هذا التاريخ.
    يُرجع tuple (نص_الرسالة, تاريخ_الرسالة) أو (None, None) إن لم يوجد."""
    import datetime as _dt
    try:
        msgs = await client.get_messages(777000, limit=10)
        for m in msgs:
            if not m.message or not any(ch.isdigit() for ch in m.message):
                continue
            if after_date is not None:
                msg_date = m.date
                if msg_date.tzinfo is None:
                    msg_date = msg_date.replace(tzinfo=_dt.timezone.utc)
                after = after_date
                if after.tzinfo is None:
                    after = after.replace(tzinfo=_dt.timezone.utc)
                threshold = after - _dt.timedelta(minutes=10)
                if msg_date < threshold:
                    continue  # كود قديم جداً — تخطَّه
            return m.message, m.date
        return None, None
    except Exception as e:
        logger.error(f"❌ خطأ في جلب كود الدخول: {e}")
        return None, None

def list_stock_numbers(filter_type: str = "all"):
    """أرقام المخزون غير المباعة، مع تصنيف اختياري:
    - "all": كل الأرقام غير المباعة (المعروضة + المنتظرة)، بدون المحذوفة ولا المبيوعة.
    - "listed": المعروضة للبيع فعلاً (تُسلَّم فوراً عند الشراء).
    - "pending": بانتظار طرد الجلسات الأخرى قبل أن تصبح قابلة للبيع.
    - "kicked": الأرقام المطرودة (فُصلت جلستها من تيليجرام) وما زالت غير محذوفة.
    - "trash": الأرقام المحذوفة (سلة المهملات)، بغض النظر عن حالة البيع.
    الأرقام المبيوعة (ever_sold=TRUE) تُستثنى من جميع القوائم — تظهر فقط في صفحة الحسابات المبيوعة.
    """
    if filter_type == "trash":
        sql = "SELECT id, phone_number, session_string, sessions_reset, force_listed, deleted_at, added_at FROM number_stock WHERE deleted_at IS NOT NULL"
    elif filter_type == "kicked":
        sql = (
            "SELECT id, phone_number, session_string, sessions_reset, force_listed, kicked_at, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND last_authorized=FALSE AND ever_sold IS NOT TRUE"
        )
    elif filter_type == "frozen":
        sql = (
            "SELECT id, phone_number, session_string, frozen_at, added_at "
            "FROM number_stock WHERE frozen_at IS NOT NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE"
        )
    elif filter_type == "auto_2fa":
        sql = (
            "SELECT id, phone_number, session_string, twofa_password, added_at "
            "FROM number_stock WHERE auto_2fa_enabled=TRUE AND deleted_at IS NULL AND ever_sold IS NOT TRUE"
        )
    elif filter_type == "complete":
        # أرقام مكتملة: البوت الجلسة الوحيدة + يستطيع إرسال كود
        sql = (
            "SELECT id, phone_number, session_string, twofa_password, is_solo, can_send_code, last_device_count, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
            "AND is_solo IS TRUE AND can_send_code IS TRUE AND last_authorized IS NOT FALSE"
        )
    elif filter_type == "unknown_verify":
        # تحقق غير معروف: جلسة موجودة + مصرَّح + لكن البوت ليس الوحيد (جلسات أخرى موجودة)
        sql = (
            "SELECT id, phone_number, session_string, twofa_password, is_solo, can_send_code, last_device_count, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
            "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL "
            "AND (is_solo IS FALSE OR is_solo IS NULL) AND (can_send_code IS FALSE OR can_send_code IS NULL)"
        )
    elif filter_type == "multi_device":
        # أجهزة متعددة: أكثر من جهاز واحد مسجّل
        sql = (
            "SELECT id, phone_number, session_string, twofa_password, last_device_count, is_solo, can_send_code, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
            "AND last_authorized IS NOT FALSE AND last_device_count > 1"
        )
    elif filter_type == "accessible_full":
        # ✅ حسابات يمكن للبوت الدخول إليها والتحكم بها وقراءة رسائلها (can_send_code حقيقي)
        sql = (
            "SELECT id, phone_number, session_string, twofa_password, is_solo, can_send_code, last_device_count, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
            "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL AND can_send_code IS TRUE"
        )
    elif filter_type == "multi_device_access":
        # 📲 حسابات بأجهزة متعددة + يمكن للبوت الدخول إليها (can_send_code أو مصرَّح)
        sql = (
            "SELECT id, phone_number, session_string, twofa_password, last_device_count, is_solo, can_send_code, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
            "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL AND last_device_count > 1"
        )
    elif filter_type == "no_2fa_accessible":
        # أرقام يمكن للبوت الوصول إليها ولا 2FA مضبوط (يمكن إرسال كود لها)
        sql = (
            "SELECT id, phone_number, session_string, is_solo, can_send_code, last_device_count, twofa_reset_date, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
            "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL "
            "AND (twofa_password IS NULL OR twofa_password = '')"
        )
    elif filter_type == "with_2fa_accessible":
        # أرقام يمكن للبوت الوصول إليها ولها 2FA محفوظة
        sql = (
            "SELECT id, phone_number, session_string, twofa_password, is_solo, can_send_code, last_device_count, added_at "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
            "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL "
            "AND twofa_password IS NOT NULL AND twofa_password != ''"
        )
    else:
        sql = "SELECT id, phone_number, session_string, sessions_reset, force_listed, twofa_password, last_authorized, frozen_at, added_at FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE"
        if filter_type == "listed":
            sql += f" AND {_sellable_filter_sql()}"
        elif filter_type == "pending":
            sql += f" AND NOT ({_sellable_filter_sql()})"
    sql += " ORDER BY kicked_at DESC NULLS LAST, id ASC" if filter_type == "kicked" else " ORDER BY id ASC"
    with db_conn() as c:
        rows = c.execute(sql).fetchall()
        return [dict(r) for r in rows]

def get_number_counts() -> dict:
    """يحسب عدد كل تصنيف من أرقام المخزون (غير المباعة وغير المحذوفة وغير المبيوعة)، دفعة واحدة."""
    with db_conn() as c:
        row = c.execute(
            "SELECT "
            "COUNT(*) AS total, "
            f"COUNT(*) FILTER (WHERE {_sellable_filter_sql()}) AS listed, "
            "COUNT(*) FILTER (WHERE last_authorized=FALSE) AS kicked, "
            "COUNT(*) FILTER (WHERE frozen_at IS NOT NULL) AS frozen, "
            "COUNT(*) FILTER (WHERE auto_2fa_enabled=TRUE) AS auto_2fa, "
            "COUNT(*) FILTER (WHERE is_solo IS TRUE AND can_send_code IS TRUE AND last_authorized IS NOT FALSE) AS complete, "
            "COUNT(*) FILTER (WHERE last_authorized IS NOT FALSE AND session_string IS NOT NULL "
            "  AND (is_solo IS FALSE OR is_solo IS NULL) AND (can_send_code IS FALSE OR can_send_code IS NULL)) AS unknown_verify, "
            "COUNT(*) FILTER (WHERE last_authorized IS NOT FALSE AND last_device_count > 1) AS multi_device "
            "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE"
        ).fetchone()
        total = row["total"] if row else 0
        listed = row["listed"] if row else 0
        kicked = row["kicked"] if row else 0
        frozen = row["frozen"] if row else 0
        with db_conn() as c2:
            trow = c2.execute("SELECT COUNT(*) AS cnt FROM number_stock WHERE deleted_at IS NOT NULL").fetchone()
            trash = trow["cnt"] if trow else 0
            srow = c2.execute("SELECT COUNT(*) AS cnt FROM number_stock WHERE ever_sold IS TRUE AND deleted_at IS NULL").fetchone()
            sold = srow["cnt"] if srow else 0
        auto_2fa       = row["auto_2fa"]       if row else 0
        complete       = row["complete"]       if row else 0
        unknown_verify = row["unknown_verify"] if row else 0
        multi_device   = row["multi_device"]   if row else 0
        with db_conn() as c3:
            na_row = c3.execute(
                "SELECT COUNT(*) AS cnt FROM number_stock "
                "WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
                "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL "
                "AND (twofa_password IS NULL OR twofa_password = '')"
            ).fetchone()
            wa_row = c3.execute(
                "SELECT COUNT(*) AS cnt FROM number_stock "
                "WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
                "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL "
                "AND twofa_password IS NOT NULL AND twofa_password != ''"
            ).fetchone()
        no_2fa_accessible   = na_row["cnt"] if na_row else 0
        with_2fa_accessible = wa_row["cnt"] if wa_row else 0
        with db_conn() as c4:
            af_row = c4.execute(
                "SELECT COUNT(*) AS cnt FROM number_stock "
                "WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
                "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL AND can_send_code IS TRUE"
            ).fetchone()
            mda_row = c4.execute(
                "SELECT COUNT(*) AS cnt FROM number_stock "
                "WHERE assigned_to IS NULL AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
                "AND last_authorized IS NOT FALSE AND session_string IS NOT NULL AND last_device_count > 1"
            ).fetchone()
        accessible_full  = af_row["cnt"]  if af_row  else 0
        multi_device_access = mda_row["cnt"] if mda_row else 0
        return {
            "all": total, "listed": listed, "pending": total - listed,
            "kicked": kicked, "trash": trash, "frozen": frozen,
            "auto_2fa": auto_2fa, "sold": sold,
            "complete": complete, "unknown_verify": unknown_verify, "multi_device": multi_device,
            "no_2fa_accessible": no_2fa_accessible, "with_2fa_accessible": with_2fa_accessible,
            "accessible_full": accessible_full, "multi_device_access": multi_device_access,
        }

def get_stock_number(stock_id: int):
    with db_conn() as c:
        row = c.execute(
            "SELECT id, phone_number, session_string, assigned_to, sessions_reset, force_listed, frozen_at, "
            "twofa_password, deleted_at, last_authorized "
            "FROM number_stock WHERE id=%s",
            (stock_id,)
        ).fetchone()
        return dict(row) if row else None

def soft_delete_number(stock_id: int) -> bool:
    """ينقل رقماً إلى سلة المهملات (حذف مؤقت) بدل حذفه نهائياً."""
    with db_conn() as c:
        c.execute("UPDATE number_stock SET deleted_at=NOW() WHERE id=%s", (stock_id,))
        return True

def restore_deleted_number(stock_id: int) -> bool:
    """يستعيد رقماً من سلة المهملات."""
    with db_conn() as c:
        c.execute("UPDATE number_stock SET deleted_at=NULL WHERE id=%s", (stock_id,))
        return True

def permanently_delete_number(stock_id: int) -> bool:
    """يحذف رقماً نهائياً من قاعدة البيانات (لا يمكن التراجع بعده)."""
    with db_conn() as c:
        c.execute("DELETE FROM number_stock WHERE id=%s", (stock_id,))
        return True

def set_force_listed(stock_id: int) -> bool:
    with db_conn() as c:
        c.execute("UPDATE number_stock SET force_listed=TRUE WHERE id=%s", (stock_id,))
        return True

def _sellable_filter_sql() -> str:
    """رقم يُعتبر قابلاً للبيع فقط إذا اكتملت جميع شروط الجاهزية الثلاثة:
    ① البوت هو الجلسة الوحيدة   (is_solo IS TRUE)
    ② البوت يعرف كلمة 2FA        (twofa_password IS NOT NULL)
    ③ البوت يستطيع إرسال كود     (can_send_code IS TRUE)
    بالإضافة إلى:
    - جلسة نشطة صالحة (last_authorized IS NOT FALSE)
    - غير مجمّد
    - لم يُباع سابقاً أبداً (ever_sold IS NOT TRUE) — حظر نهائي لا استثناء فيه
    الحسابات المبيوعة سابقاً تظهر فقط في صفحة الحسابات المبيوعة ولا تُعرض للبيع مجدداً."""
    return (
        "session_string IS NOT NULL"
        " AND last_authorized IS NOT FALSE"
        " AND twofa_password IS NOT NULL"
        " AND twofa_password <> ''"
        " AND frozen_at IS NULL"
        " AND ever_sold IS NOT TRUE AND can_send_code IS TRUE AND last_authorized IS NOT FALSE"
        " AND is_solo IS TRUE"
        " AND can_send_code IS TRUE"
        " AND referral_only IS NOT TRUE"
    )

def get_available_number_count() -> int:
    with db_conn() as c:
        row = c.execute(
            f"SELECT COUNT(*) as cnt FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND {_sellable_filter_sql()}"
        ).fetchone()
        return row["cnt"] if row else 0

def get_forced_ref_account_count() -> int:
    """عدد الحسابات المؤهلة للإحالة الإجبارية: فقط الحسابات التي يمكن للبوت فعلاً فتحها والعمل بها
    (can_send_code=TRUE وغير مجمّدة)."""
    with db_conn() as c:
        row = c.execute(
            f"SELECT COUNT(*) as cnt FROM number_stock"
            f" WHERE session_string IS NOT NULL AND deleted_at IS NULL AND assigned_to IS NULL"
            f" AND ever_sold IS NOT TRUE AND can_send_code IS TRUE AND last_authorized IS NOT FALSE"
            f" AND frozen_at IS NULL AND forced_ref_excluded IS NOT TRUE"
        ).fetchone()
        return row["cnt"] if row else 0

async def _test_and_set_can_send_code(phone: str, session_str: str, stock_id: int):
    """يتحقق من قدرة البوت على الوصول للحساب وجلب الكودات:
    يتصل بالجلسة المحفوظة، يستدعي get_me()، وإذا أرجعت بيانات مستخدم صحيحة
    يضبط can_send_code=TRUE — يعني البوت يستطيع إرسال كود للمشتري عند الطلب."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    try:
        _cli = TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(_cli.connect(), timeout=15)
        try:
            if await asyncio.wait_for(_cli.is_user_authorized(), timeout=8):
                me = await asyncio.wait_for(_cli.get_me(), timeout=10)
                if me and me.phone:
                    with db_conn() as _c:
                        _c.execute(
                            "UPDATE number_stock SET can_send_code=TRUE WHERE id=%s AND ever_sold IS NOT TRUE",
                            (stock_id,)
                        )
                    logger.info(f"✅ can_send_code=TRUE للرقم {phone} (الحساب جاهز للبيع إذا اكتملت باقي الشروط)")
                else:
                    logger.warning(f"⚠️ can_send_code: get_me() لم يُرجع رقم هاتف للحساب {phone}")
            else:
                logger.warning(f"⚠️ can_send_code: جلسة {phone} غير مصرَّح بها")
        finally:
            try:
                await _cli.disconnect()
            except Exception:
                pass
    except Exception as _e:
        logger.debug(f"⚠️ _test_and_set_can_send_code {phone}: {_e}")

async def _ensure_can_send_code(phone: str, session_str: str, stock_id: int):
    """يُستدعى عندما يصبح البوت الجلسة الوحيدة — يتحقق ويضبط can_send_code إذا لم يكن مضبوطاً بعد.
    يتجاهل الحسابات المبيوعة سابقاً أو التي جُرِّب كودها مسبقاً."""
    try:
        with db_conn() as _ec:
            _row = _ec.execute(
                "SELECT ever_sold, can_send_code FROM number_stock WHERE id=%s", (stock_id,)
            ).fetchone()
        if not _row or _row["ever_sold"] or _row["can_send_code"]:
            return  # مباع سابقاً أو مضبوط مسبقاً — لا حاجة للفحص
        await _test_and_set_can_send_code(phone, session_str, stock_id)
    except Exception as _e:
        logger.debug(f"⚠️ _ensure_can_send_code {phone}: {_e}")

def add_number_with_session(phone: str, session_str: str) -> bool:
    """يضيف رقماً جاهزاً (مسجّل دخول مسبقاً) مع جلسته إلى المخزون. يُرجع False إن كان الرقم موجوداً مسبقاً."""
    with db_conn() as c:
        c.execute(
            "INSERT INTO number_stock (phone_number, session_string, deleted_at) VALUES (%s,%s,NULL) "
            "ON CONFLICT (phone_number) DO UPDATE SET session_string=EXCLUDED.session_string, deleted_at=NULL",
            (phone, session_str)
        )
        return True

def assign_next_number(user_id: int):
    """يسحب رقماً متاحاً من المخزون ويحجزه لهذا المستخدم بشكل ذرّي (يمنع تكرار تسليم نفس الرقم
    لشخصين عند الطلب المتزامن). يُرجع dict {phone_number, session_string} إن وُجد، أو None إن كان المخزون فارغاً."""
    with db_conn() as c:
        already_sold = c.execute(
            "SELECT prize_value FROM prize_exchanges "
            "WHERE user_id=%s AND status IN ('completed','duplicate_compensated') "
            "AND prize_type IN ('telegram_number','telegram_number_code') "
            "AND prize_value NOT IN ('number','manual')",
            (user_id,)
        ).fetchall()
        exclude_phones = [r["prize_value"] for r in already_sold] if already_sold else []
        excl_sql = ""
        excl_params = []
        if exclude_phones:
            placeholders = ",".join(["%s"] * len(exclude_phones))
            excl_sql = f" AND phone_number NOT IN ({placeholders})"
            excl_params = exclude_phones

        row = c.execute(
            "UPDATE number_stock SET assigned_to=%s, assigned_at=NOW(), ever_sold=TRUE "
            "WHERE id = (SELECT id FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND "
            f"{_sellable_filter_sql()}{excl_sql} ORDER BY id ASC LIMIT 1 FOR UPDATE SKIP LOCKED) "
            "RETURNING phone_number, session_string",
            [user_id] + excl_params
        ).fetchone()
        if not row:
            return None
        return {"phone_number": row["phone_number"], "session_string": row["session_string"]}

def _auto_delete_number(stock_id: int, phone: str, reason: str):
    """يحذف رقماً من المخزون نهائياً مع تسجيل السبب في اللوج."""
    try:
        with db_conn() as c:
            c.execute(
                "UPDATE number_stock SET deleted_at=NOW(), assigned_to=NULL, assigned_at=NULL "
                "WHERE id=%s",
                (stock_id,)
            )
        logger.warning(f"🗑 حُذف الرقم {phone} تلقائياً — السبب: {reason}")
    except Exception as _del_err:
        logger.error(f"❌ فشل حذف الرقم {phone}: {_del_err}")

async def assign_verified_number(user_id: int, bot=None) -> dict | None:
    """
    يختار رقماً من المخزون ويُجري ثلاثة فحوصات إلزامية قبل التسليم:
      ① ever_sold IS NOT TRUE       — لم يُباع سابقاً (في SQL)
      ② is_user_authorized() = True — البوت لا يزال يستطيع استقبال الأكواد
      ③ twofa_password مضبوط       — البوت يعرف رمز التحقق الثنائي

    أي فشل → يحذف الرقم نهائياً من المخزون ويجرب التالي.
    أرقام بلا session (يدوية) → تُحذف فوراً ولا تُعرض للبيع.
    يُرجع dict {phone_number, session_string, twofa_password} أو None إن فرغ المخزون.
    """
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        logger.error("❌ TELEGRAM_API_ID/HASH غير مضبوط — تعذّر التحقق من الأرقام قبل البيع.")
        return None

    MAX_TRIES = 10
    skipped_ids: list[int] = []

    with db_conn() as _dup_c:
        _already = _dup_c.execute(
            "SELECT prize_value FROM prize_exchanges "
            "WHERE user_id=%s AND status IN ('completed','duplicate_compensated') "
            "AND prize_type IN ('telegram_number','telegram_number_code') "
            "AND prize_value NOT IN ('number','manual')",
            (user_id,)
        ).fetchall()
    _exclude_phones = [r["prize_value"] for r in (_already or [])]

    for _attempt in range(MAX_TRIES):
        with db_conn() as c:
            excl_parts: list[str] = []
            excl_vals:  list      = []
            if skipped_ids:
                excl_parts.append(f"AND id NOT IN ({','.join(str(i) for i in skipped_ids)})")
            if _exclude_phones:
                ph_phs = ",".join(["%s"] * len(_exclude_phones))
                excl_parts.append(f"AND phone_number NOT IN ({ph_phs})")
                excl_vals.extend(_exclude_phones)
            excl = " ".join(excl_parts)
            row = c.execute(
                f"UPDATE number_stock SET assigned_to=%s, assigned_at=NOW(), ever_sold=TRUE "
                f"WHERE id = (SELECT id FROM number_stock "
                f"WHERE assigned_to IS NULL AND deleted_at IS NULL AND {_sellable_filter_sql()} "
                f"{excl} ORDER BY RANDOM() LIMIT 1 FOR UPDATE SKIP LOCKED) "
                f"RETURNING id, phone_number, session_string, twofa_password",
                [user_id] + excl_vals
            ).fetchone()

        if not row:
            break  # المخزون فارغ تماماً

        stock_id = row["id"]
        phone    = row["phone_number"]
        sess     = row["session_string"]
        saved_pw = row["twofa_password"] or ""

        # ─── فحص ①: هل للرقم جلسة أصلاً؟ (رقم يدوي = يُحذف) ───
        if not sess:
            _auto_delete_number(stock_id, phone, "رقم يدوي بلا جلسة — لا يُباع")
            continue

        # ─── فحص ③: هل كلمة مرور 2FA مخزّنة؟ ───
        if not saved_pw.strip():
            _auto_delete_number(stock_id, phone, "لا يوجد رمز 2FA — لا يمكن تسليمه للمشتري")
            continue

        # ─── فحص ②: هل البوت لا يزال مصرّحاً (يستطيع استقبال الأكواد)؟ ───
        cli_check = None
        try:
            cli_check = TelegramClient(StringSession(sess), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await asyncio.wait_for(cli_check.connect(), timeout=15)
            authorized = await asyncio.wait_for(cli_check.is_user_authorized(), timeout=10)

            if not authorized:
                _auto_delete_number(stock_id, phone, "جلسة منتهية — البوت لا يستطيع استقبال الأكواد")
                await cli_check.disconnect()
                continue

            # ─── فحص إضافي: هل الحساب مجمّد؟ ───
            is_frz, _, _ = await check_account_frozen(cli_check, stock_id)
            if is_frz:
                _auto_delete_number(stock_id, phone, "حساب مجمّد من تيليغرام")
                await cli_check.disconnect()
                continue

            # ─── تنظيف: طرد أي أجهزة إضافية قبل التسليم ───
            devices = await get_device_count(cli_check)
            if devices > 1:
                try:
                    await cli_check(ResetAuthorizationsRequest())
                    with db_conn() as c:
                        c.execute("UPDATE number_stock SET sessions_reset=TRUE WHERE id=%s", (stock_id,))
                    logger.info(f"✅ طُردت {devices - 1} جلسة إضافية للرقم {phone} قبل التسليم.")
                except Exception as kick_err:
                    logger.warning(f"⚠️ تعذّر طرد جلسات {phone}: {kick_err}")

            # ─── مسح جميع المحادثات قبل تسليم الرقم للمشتري ───
            try:
                async for _dlg in cli_check.iter_dialogs(limit=300):
                    try:
                        await cli_check.delete_dialog(_dlg, revoke=True)
                    except Exception:
                        pass
                logger.info(f"🧹 تم مسح محادثات الرقم {phone} قبل التسليم.")
            except Exception as _clr_err:
                logger.warning(f"⚠️ تعذّر مسح بعض محادثات {phone}: {_clr_err}")

            await cli_check.disconnect()

        except Exception as chk_err:
            logger.warning(f"⚠️ فشل الاتصال بجلسة {phone}: {chk_err} — يُحذف")
            _auto_delete_number(stock_id, phone, f"خطأ في الاتصال: {type(chk_err).__name__}")
            try:
                if cli_check:
                    await cli_check.disconnect()
            except Exception:
                pass
            continue

        # ─── الرقم اجتاز الفحوصات الثلاثة ✅ ───
        logger.info(f"✅ الرقم {phone} اجتاز جميع الفحوصات — جاهز للتسليم.")
        return {"phone_number": phone, "session_string": sess, "twofa_password": saved_pw}

    logger.info(f"📭 assign_verified_number: لا يوجد رقم صالح بعد {MAX_TRIES} محاولة.")
    return None

# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

def get_referral_tasks(only_active: bool = False) -> list:
    with db_conn() as c:
        sql = "SELECT * FROM referral_tasks"
        if only_active:
            sql += " WHERE active=TRUE"
        sql += " ORDER BY id ASC"
        return [dict(r) for r in c.execute(sql).fetchall()]

def get_referral_task(task_id: int) -> dict | None:
    with db_conn() as c:
        row = c.execute("SELECT * FROM referral_tasks WHERE id=%s", (task_id,)).fetchone()
        return dict(row) if row else None

def add_referral_task(label: str, bot_username: str, start_param: str,
                       mandatory_channels: str = "", folder_link: str = "") -> int:
    with db_conn() as c:
        row = c.execute(
            "INSERT INTO referral_tasks "
            "(label, bot_username, start_param, mandatory_channels, folder_link) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (label, bot_username, start_param, mandatory_channels or "", folder_link or "")
        ).fetchone()
        return row["id"]

def delete_referral_task(task_id: int):
    with db_conn() as c:
        c.execute("DELETE FROM referral_completions WHERE task_id=%s", (task_id,))
        c.execute("DELETE FROM referral_tasks WHERE id=%s", (task_id,))

def toggle_referral_task(task_id: int) -> bool:
    """يعكس حالة التفعيل ويُرجع الحالة الجديدة (True=نشط)."""
    with db_conn() as c:
        row = c.execute("SELECT active FROM referral_tasks WHERE id=%s", (task_id,)).fetchone()
        if not row:
            return False
        new_val = 0 if row["active"] else 1
        c.execute("UPDATE referral_tasks SET active=%s WHERE id=%s", (new_val, task_id))
        return bool(new_val)

def get_referral_task_stats(task_id: int) -> dict:
    """يُرجع إحصاء: done / failed / pending / total لمهمة إحالة معيّنة."""
    with db_conn() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) as cnt FROM referral_completions WHERE task_id=%s GROUP BY status",
            (task_id,)
        ).fetchall()
        stats = {"done": 0, "failed": 0, "pending": 0}
        for r in rows:
            stats[r["status"]] = r["cnt"]
        stats["total"] = sum(stats.values())
        return stats

def get_pending_numbers_for_task(task_id: int) -> list:
    """أرقام المخزون التي لم تُكمل هذه المهمة بعد (لم تُسجَّل في referral_completions بحالة done).
    القيد الوحيد: استبعاد الحسابات المباعة (ever_sold IS TRUE).
    الأرقام بدون جلسة تُتجاوز وقت التشغيل ولا تُسجَّل كـ failed (تُعاد في الدورة التالية)."""
    with db_conn() as c:
        rows = c.execute(
            """
            SELECT ns.id, ns.phone_number, ns.session_string
            FROM number_stock ns
            WHERE ns.ever_sold IS NOT TRUE
              AND ns.id NOT IN (
                  SELECT stock_id FROM referral_completions
                  WHERE task_id=%s AND status='done'
              )
            ORDER BY ns.id ASC
            """,
            (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

def mark_referral_completion(task_id: int, stock_id: int, status: str, error_msg: str = None):
    with db_conn() as c:
        c.execute(
            """
            INSERT INTO referral_completions (task_id, stock_id, status, done_at, error_msg)
            VALUES (%s, %s, %s, NOW(), %s)
            ON CONFLICT (task_id, stock_id) DO UPDATE
              SET status=EXCLUDED.status, done_at=EXCLUDED.done_at, error_msg=EXCLUDED.error_msg
            """,
            (task_id, stock_id, status, error_msg)
        )

# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

# ─── دوال مساعدة للإحالة التلقائية ───

def _parse_channel_tokens(raw: str) -> list:
    """يحوّل نص القنوات (مسافة / سطر جديد فاصل) إلى قائمة من dict {type, value}.
    يقبل: @username  أو  t.me/username  أو  t.me/+HASH  أو  t.me/joinchat/HASH
    """
    import re as _re
    results = []
    for tok in _re.split(r'[\s,]+', raw.strip()):
        tok = tok.strip()
        if not tok:
            continue
        if 't.me/' in tok or 'telegram.me/' in tok:
            from urllib.parse import urlparse as _up, parse_qs as _pq
            parsed = _up(tok if tok.startswith('http') else 'https://' + tok)
            path = parsed.path.strip('/')
            if path.startswith('+'):
                results.append({'type': 'invite', 'value': path[1:]})
            elif 'joinchat/' in path:
                results.append({'type': 'invite', 'value': path.split('joinchat/')[-1]})
            else:
                part = path.split('/')[0]
                if part:
                    results.append({'type': 'username', 'value': part})
        elif tok.startswith('@'):
            results.append({'type': 'username', 'value': tok[1:]})
        else:
            results.append({'type': 'username', 'value': tok})
    return results

async def _join_mandatory_channels(client, raw_channels: str) -> int:
    """ينضم لجميع القنوات الإجبارية. يُرجع عدد ما نجح."""
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.tl.functions.messages import ImportChatInviteRequest
    tokens = _parse_channel_tokens(raw_channels)
    joined = 0
    for tok in tokens:
        try:
            if tok['type'] == 'invite':
                await client(ImportChatInviteRequest(tok['value']))
            else:
                ch = await client.get_entity(tok['value'])
                await client(JoinChannelRequest(ch))
            joined += 1
            await asyncio.sleep(1.5)
        except Exception as e:
            logger.warning(f"⚠️ تعذّر الانضمام لـ {tok}: {e}")
    return joined

async def _leave_mandatory_channels(client, raw_channels: str) -> int:
    """يغادر جميع القنوات الإجبارية بعد اكتمال العملية. يُرجع عدد ما نجح."""
    from telethon.tl.functions.channels import LeaveChannelRequest
    tokens = _parse_channel_tokens(raw_channels)
    left = 0
    for tok in tokens:
        try:
            ch = await client.get_entity(tok['value'])
            await client(LeaveChannelRequest(ch))
            left += 1
            await asyncio.sleep(1.0)
        except Exception as e:
            logger.warning(f"⚠️ تعذّر مغادرة {tok}: {e}")
    return left

async def _join_folder_link(client, folder_url: str) -> str:
    """ينضم لمجلد تيليجرام (addlist link). إذا وصل الحد (2) يحذف الأقدم."""
    try:
        from telethon.tl.functions.chatlists import (
            CheckChatlistInviteRequest,
            JoinChatlistInviteRequest,
            GetChatlistsRequest,
            LeaveChatlistRequest,
        )
        import re as _re
        m = _re.search(r'addlist/([A-Za-z0-9_-]+)', folder_url)
        if not m:
            return "رابط مجلد غير صحيح"
        folder_hash = m.group(1)

        try:
            current = await client(GetChatlistsRequest())
            folders = getattr(current, 'filters', []) or []
        except Exception:
            folders = []

        if len(folders) >= 2:
            try:
                oldest = folders[0]
                await client(LeaveChatlistRequest(
                    chatlist=oldest,
                    peers=[]
                ))
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"⚠️ تعذّر حذف مجلد قديم: {e}")

        invite_info = await client(CheckChatlistInviteRequest(slug=folder_hash))
        await client(JoinChatlistInviteRequest(
            slug=folder_hash,
            peers=getattr(invite_info, 'peers', []) or [],
        ))
        return "انضم للمجلد ✅"
    except Exception as e:
        logger.warning(f"⚠️ تعذّر الانضمام للمجلد: {e}")
        return f"فشل المجلد: {str(e)[:60]}"

async def solve_captcha_with_ai(client, bot_entity, msgs: list, phone: str = "", max_rounds: int = 4) -> tuple:
    """
    يستخدم Gemini AI لكشف وحل جميع أنواع التحقق الشائعة في بوتات تيليغرام:
    ① كابتشا صورة   ② أزرار / إيموجي   ③ سؤال نصي / رياضي
    ④ مشاركة ملف شخصي / Contact   ⑤ Poll / Quiz   ⑥ ردود فعل Reactions
    ⑦ إيموجي كرسالة   ⑧ إعادة المحاولة تلقائياً عند الإجابة الخاطئة
    يُرجع (solved: bool, detail: str).
    """
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    if not GEMINI_API_KEY:
        return False, "GEMINI_API_KEY غير مضبوط"

    GEMINI_URL = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    )

    # ── كلمات دلالية ──────────────────────────────────────────
    SUCCESS_KW = [
        "✅", "تم", "نجح", "مبروك", "أهلاً", "مرحباً", "welcome", "success",
        "تم التحقق", "مقبول", "accepted", "verified", "شكراً", "برافو",
        "اشتركت", "سجلت", "تسجيل", "دخلت", "ترحيب", "congratulations",
        "passed", "اجتزت", "صحيح", "correct", "ممتاز", "👍", "تم قبولك",
        "تم التسجيل", "انتهت عملية", "تم التفعيل", "بنجاح",
    ]
    FAIL_KW = [
        "خطأ", "غلط", "wrong", "incorrect", "فشل", "error", "❌",
        "حاول مجدداً", "try again", "retry", "invalid", "غير صحيح",
        "أعد", "مجدداً", "again", "حاول ثانية", "إجابة خاطئة",
    ]
    CAPTCHA_KW = [
        "تحقق", "verify", "captcha", "اضغط", "ادخل", "أجب", "اختر",
        "robot", "بشر", "human", "confirm", "verification", "كابتشا",
        "لست روبوت", "لست بوت", "not a robot", "prove", "إثبت",
    ]
    MATH_KW = [
        "=", "؟", "?", "كم", "احسب", "حل", "اكتب", "أدخل",
        "اجمع", "اطرح", "اضرب", "اقسم", "ناتج", "حاصل", "result",
        "calculate", "solve", "answer", "الإجابة", "الجواب", "الرقم",
    ]
    FORWARD_KW = [
        "شارك", "أرسل ملف", "ارسل ملف", "forward", "ملفك الشخصي",
        "profile", "بروفايل", "contact", "جهة اتصال", "رقمك",
        "رقم هاتفك", "شارك ملفك", "ارسل بياناتك", "بياناتك الشخصية",
    ]
    REACTION_KW = [
        "تفاعل", "react", "reaction", "اضغط على", "ارسل إيموجي",
        "أرسل إيموجي", "انقر", "إيموجي", "emoji", "رد بـ", "reply with",
        "أرسل رد", "ارسل رد",
    ]

    # ── دوال مساعدة ───────────────────────────────────────────
    async def _gemini_text(prompt: str) -> str | None:
        def _do_request():
            r = requests.post(
                GEMINI_URL,
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=25,
            )
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            return None
        try:
            return await asyncio.to_thread(_do_request)
        except Exception as _e:
            logger.warning(f"⚠️ Gemini text error ({phone}): {_e}")
        return None

    async def _gemini_image(prompt: str, img_bytes: bytes) -> str | None:
        def _do_request():
            img_b64 = base64.b64encode(img_bytes).decode()
            r = requests.post(
                GEMINI_URL,
                json={"contents": [{"parts": [
                    {"text": prompt},
                    {"inlineData": {"mimeType": "image/jpeg", "data": img_b64}},
                ]}]},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            return None
        try:
            return await asyncio.to_thread(_do_request)
        except Exception as _e:
            logger.warning(f"⚠️ Gemini image error ({phone}): {_e}")
        return None

    def _is_success(text: str) -> bool:
        t = (text or "").lower()
        return any(k.lower() in t for k in SUCCESS_KW)

    def _is_fail(text: str) -> bool:
        t = (text or "").lower()
        return any(k.lower() in t for k in FAIL_KW)

    async def _wait_and_check(limit: int = 3) -> tuple:
        """ينتظر رد البوت ويُرجع ('success'|'fail'|'unknown', new_msgs)."""
        await asyncio.sleep(3)
        new_msgs = await client.get_messages(bot_entity, limit=limit)
        for m in new_msgs:
            t = getattr(m, "message", "") or ""
            if _is_success(t):
                return "success", new_msgs
            if _is_fail(t):
                return "fail", new_msgs
        return "unknown", new_msgs

    all_details: list[str] = []
    processed_ids: set[int] = set()

    # ── حلقة المحاولات (تدعم تحقق متعدد المراحل) ─────────────
    for _round in range(max_rounds):
        if _round > 0:
            await asyncio.sleep(3)
            msgs = await client.get_messages(bot_entity, limit=6)

        for msg in msgs:
            msg_id = getattr(msg, "id", 0)
            if msg_id in processed_ids:
                continue

            msg_text       = getattr(msg, "message", "") or getattr(msg, "text", "") or ""
            msg_text_lower = msg_text.lower()
            has_photo      = bool(getattr(msg, "photo", None))
            has_doc        = bool(getattr(msg, "document", None))
            has_media      = has_photo or has_doc
            has_btns       = bool(msg.buttons)
            has_poll       = bool(getattr(msg, "poll", None))

            # اكتشاف نجاح مبكر — إذا وصلنا رسالة ترحيب بعد حل سابق
            if _is_success(msg_text) and all_details:
                return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"

            # ════════════════════════════════════════════════════
            # 1. كابتشا صورة (CAPTCHA بصورة مشوّهة)
            # ════════════════════════════════════════════════════
            if has_media and not has_btns:
                try:
                    img_bytes = await client.download_media(msg, bytes)
                    if not img_bytes:
                        continue
                    prompt = (
                        "هذه صورة كابتشا (CAPTCHA) من بوت تيليغرام.\n"
                        f"النص المرافق للصورة: {msg_text or '(لا يوجد)'}\n\n"
                        "اقرأ بدقة النص أو الأرقام الظاهرة في الصورة وأجب بها فقط "
                        "بدون أي شرح أو مسافات إضافية."
                    )
                    answer = await _gemini_image(prompt, img_bytes)
                    if answer:
                        logger.info(f"🤖 AI كابتشا صورة → '{answer}' ({phone})")
                        processed_ids.add(msg_id)
                        await asyncio.sleep(1)
                        await client.send_message(bot_entity, answer)
                        result, msgs = await _wait_and_check()
                        detail = f"كابتشا صورة: {answer}"
                        all_details.append(detail)
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result == "fail":
                            break  # حاول في الجولة التالية
                        else:
                            return True, f"أُرسلت إجابة الصورة | {' | '.join(all_details)}"
                except Exception as _e:
                    logger.warning(f"⚠️ AI image captcha ({phone}): {_e}")
                continue

            # ════════════════════════════════════════════════════
            # 2. مشاركة ملف شخصي / Contact
            # ════════════════════════════════════════════════════
            if any(k in msg_text_lower for k in FORWARD_KW):
                try:
                    from telethon.tl.types import InputMediaContact
                    me    = await client.get_me()
                    first = getattr(me, "first_name", "") or ""
                    last  = getattr(me, "last_name",  "") or ""
                    ph    = getattr(me, "phone",      "") or phone.lstrip("+")
                    if not ph.startswith("+"):
                        ph = "+" + ph
                    logger.info(f"🤖 AI مشاركة ملف شخصي ({phone})")
                    processed_ids.add(msg_id)
                    await client.send_file(
                        bot_entity,
                        InputMediaContact(
                            phone_number=ph,
                            first_name=first,
                            last_name=last,
                            vcard="",
                        ),
                    )
                    result, msgs = await _wait_and_check()
                    detail = "شارك ملفه الشخصي (Contact)"
                    all_details.append(detail)
                    if result == "success":
                        return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                    elif result != "fail":
                        return True, f"أُرسل الملف الشخصي | {' | '.join(all_details)}"
                    continue
                except Exception as _e:
                    logger.warning(f"⚠️ AI forward profile ({phone}): {_e}")

            # ════════════════════════════════════════════════════
            # 3. Poll / Quiz (اختبار متعدد الخيارات)
            # ════════════════════════════════════════════════════
            if has_poll:
                try:
                    poll_obj = msg.poll.poll
                    question = getattr(poll_obj, "question", "") or ""
                    answers  = [getattr(a, "text", "") for a in (getattr(poll_obj, "answers", []) or [])]
                    if question and answers:
                        prompt = (
                            f"بوت تيليغرام يطرح اختباراً:\nالسؤال: {question}\n"
                            "الخيارات:\n" + "\n".join(f"{i+1}. {a}" for i, a in enumerate(answers)) + "\n\n"
                            "أي خيار هو الصحيح؟ أجب برقم الخيار فقط (1، 2، 3...)."
                        )
                        ai_ans = await _gemini_text(prompt)
                        chosen_idx = 0
                        if ai_ans:
                            # حاول استخراج رقم
                            nums = re.findall(r"\d+", ai_ans)
                            if nums:
                                chosen_idx = max(0, int(nums[0]) - 1)
                            else:
                                # مطابقة نصية
                                for i, a in enumerate(answers):
                                    if ai_ans.strip().lower() in a.lower():
                                        chosen_idx = i
                                        break
                        chosen_idx = min(chosen_idx, len(answers) - 1)
                        processed_ids.add(msg_id)
                        await msg.click(chosen_idx)
                        result, msgs = await _wait_and_check()
                        detail = f"أجاب Poll: {answers[chosen_idx]}"
                        all_details.append(detail)
                        logger.info(f"🤖 AI Poll → '{answers[chosen_idx]}' ({phone})")
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result != "fail":
                            return True, f"أجاب على اختبار | {' | '.join(all_details)}"
                        continue
                except Exception as _e:
                    logger.warning(f"⚠️ AI poll captcha ({phone}): {_e}")

            # ════════════════════════════════════════════════════
            # 4. أزرار اختيار (كابتشا أزرار / إيموجي / خيارات)
            # ════════════════════════════════════════════════════
            if has_btns and msg_text:
                try:
                    btn_labels  = []
                    btn_objects = {}
                    for row in msg.buttons:
                        for btn in row:
                            label = getattr(btn, "text", "") or ""
                            url   = getattr(btn, "url",  None) or ""
                            # تخطي أزرار روابط القنوات — تُعالج لاحقاً في do_referral_for_number
                            if url and ("t.me/" in url or "telegram.me/" in url):
                                continue
                            if label:
                                btn_labels.append(label)
                                btn_objects[label] = btn
                    if not btn_labels:
                        continue
                    logger.info(f"🔘 Captcha buttons detected: {len(btn_labels)} ({phone})")
                    # هل تبدو رسالة تحقق؟ (تحقق، رياضيات، إيموجي...)
                    is_verif = (
                        any(k in msg_text_lower for k in CAPTCHA_KW)
                        or any(k in msg_text_lower for k in MATH_KW)
                        or any(k in msg_text_lower for k in REACTION_KW)
                        or "select" in msg_text_lower
                        or "choose" in msg_text_lower
                        or "click" in msg_text_lower
                        or "press" in msg_text_lower
                        or "pick" in msg_text_lower
                    )
                    if not is_verif:
                        continue

                    # ── مطابقة مباشرة لإيموجي التحقق قبل استدعاء Gemini ──
                    # بعض البوتات تستخدم Custom/Premium Emoji في نص الرسالة
                    # والأزرار. نعتمد على النص الفعلي للزر ونزيل اختلافات
                    # العرض (variation selectors و ZWJ) قبل المقارنة.
                    def _extract_emojis_from_text(text: str) -> list:
                        result = []
                        import unicodedata
                        for ch in text or "":
                            cp = ord(ch)
                            if (
                                0x1F300 <= cp <= 0x1FFFF
                                or 0x2600 <= cp <= 0x27BF
                                or 0x1F900 <= cp <= 0x1F9FF
                                or 0x1FA00 <= cp <= 0x1FAFF
                                or cp == 0xFFFC  # placeholder محتمل لـ Custom Emoji
                                or unicodedata.category(ch) == "So"
                            ):
                                result.append(ch)
                        return result

                    def _emoji_signature(text: str) -> str:
                        return "".join(
                            ch for ch in _extract_emojis_from_text(text)
                            if ch not in "\ufe0e\ufe0f\u200d"
                        )

                    def _emoji_match_score(target: str, label: str) -> int:
                        target_sig = _emoji_signature(target)
                        label_sig = _emoji_signature(label)
                        if not target_sig or not label_sig:
                            return 0
                        if target_sig == label_sig:
                            return 100
                        if target_sig in label_sig or label_sig in target_sig:
                            return 85
                        # يسمح باختلافات التركيب مع منع اختيار زر لا علاقة له.
                        if any(ch in label_sig for ch in target_sig):
                            return 60
                        return 0

                    def _extract_target_emoji(text: str) -> str | None:
                        import re as _captcha_re
                        target_match = _captcha_re.search(
                            r"(?:اضغط\s+على\s+(?:الرمز|الإيموجي)|اختر\s+الإيموجي|"
                            r"الإيموجي\s+الصحيح|انقر\s+على\s+(?:الرمز|الإيموجي)|"
                            r"correct\s+emoji|select\s+emoji|choose\s+emoji|pick\s+emoji)"
                            r"\s*[:：]?\s*(.*)$",
                            text or "",
                            flags=_captcha_re.IGNORECASE,
                        )
                        target_tail = target_match.group(1) if target_match else ""
                        return next(
                            (item for item in _extract_emojis_from_text(target_tail) if item),
                            None,
                        )

                    chosen = None
                    chosen_label = None
                    chosen_source = "AI"
                    target_emoji = _extract_target_emoji(msg_text)
                    if target_emoji:
                        ranked_buttons = []
                        for button_label, button in btn_objects.items():
                            score = _emoji_match_score(target_emoji, button_label)
                            if score:
                                ranked_buttons.append((score, button_label, button))
                        if ranked_buttons:
                            _, chosen_label, chosen = max(
                                ranked_buttons, key=lambda item: item[0]
                            )
                            chosen_source = "emoji-direct"
                            logger.info(
                                f"🎯 تطابق مباشر لإيموجي التحقق: '{target_emoji}' → "
                                f"'{chosen_label}' ({phone})"
                            )

                    # إذا لم يوجد تطابق مباشر، استخدم Gemini كاحتياط.
                    if not chosen:
                        all_emoji_btns = all(
                            bool(_extract_emojis_from_text(lbl)) for lbl in btn_labels
                        )
                        if all_emoji_btns:
                            prompt = (
                                "Telegram bot button CAPTCHA.\n"
                                f"Instruction: {msg_text}\n\n"
                                "Important: ignore decorative emojis in the instruction "
                                "(for example the robot emoji in 'not a robot'). "
                                "Find the target emoji after phrases such as 'click the symbol' "
                                "or 'اضغط على الرمز', then choose ONLY the matching button "
                                "from the available buttons.\n\n"
                                "Available emoji buttons:\n"
                                + "\n".join(f"- {b}" for b in btn_labels)
                                + "\n\nReply with ONLY the exact emoji character."
                            )
                        else:
                            prompt = (
                                f"بوت تيليغرام يطلب التحقق:\n{msg_text}\n\n"
                                "الأزرار المتاحة:\n"
                                + "\n".join(f"- {b}" for b in btn_labels)
                                + "\n\nاختر الزر الذي يطابق المطلوب، وأجب بنص الزر فقط. "
                                "تجاهل أي إيموجي زخرفي في نص التعليمات."
                            )

                        answer = await _gemini_text(prompt)
                        if answer:
                            logger.info(f"🤖 AI اختار زر → '{answer}' ({phone})")
                            a_clean = answer.strip()
                            a_lower = a_clean.lower()
                            for label, btn in btn_objects.items():
                                if label.strip() == a_clean:
                                    chosen = btn
                                    chosen_label = label
                                    break
                            if not chosen:
                                for answer_emoji in _extract_emojis_from_text(a_clean):
                                    ranked = [
                                        (_emoji_match_score(answer_emoji, label), label, btn)
                                        for label, btn in btn_objects.items()
                                        if _emoji_match_score(answer_emoji, label)
                                    ]
                                    if ranked:
                                        _, chosen_label, chosen = max(
                                            ranked, key=lambda item: item[0]
                                        )
                                        break
                            if not chosen and a_lower:
                                for label, btn in btn_objects.items():
                                    if a_lower in label.lower() or label.lower() in a_lower:
                                        chosen = btn
                                        chosen_label = label
                                        break

                    # مطابقة نصية أخيرة، من دون اختيار أول زر عشوائياً.
                    if not chosen and answer:
                        a_lower = answer.strip().lower()
                        if a_lower:
                            for label, btn in btn_objects.items():
                                if a_lower in label.lower() or label.lower() in a_lower:
                                    chosen = btn
                                    chosen_label = label
                                    break

                    attempted_labels = set()
                    current_msgs = list(msgs or [])
                    last_result = "unknown"

                    async def _click_button_and_check(label, button, source):
                        try:
                            await button.click()
                        except Exception as click_error:
                            logger.warning(
                                f"⚠️ فشل الضغط على زر Captcha ({source}, {phone}): {click_error}"
                            )
                            return "unknown", current_msgs
                        result, fresh_msgs = await _wait_and_check()
                        all_details.append(f"{source}: {label}")
                        logger.info(
                            f"🔘 Captcha button ({source}) → '{label}' ({phone}) = {result}"
                        )
                        return result, fresh_msgs

                    # المحاولة الأولى من التطابق المباشر، ثم اختيار Gemini.
                    if chosen and chosen_label:
                        attempted_labels.add(chosen_label)
                        processed_ids.add(msg_id)
                        last_result, current_msgs = await _click_button_and_check(
                            chosen_label, chosen, chosen_source
                        )
                        if last_result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"

                    def _candidate_buttons(message_list):
                        candidates = []
                        seen = set()
                        ordered_messages = sorted(
                            [m for m in (message_list or []) if getattr(m, "buttons", None)],
                            key=lambda m: getattr(m, "id", 0),
                            reverse=True,
                        )
                        for candidate_msg in ordered_messages:
                            for row in (candidate_msg.buttons or []):
                                for button in row:
                                    label = getattr(button, "text", "") or ""
                                    url = getattr(button, "url", None) or ""
                                    if not label or label in seen:
                                        continue
                                    if url and ("t.me/" in url or "telegram.me/" in url):
                                        continue
                                    seen.add(label)
                                    candidates.append((label, button))
                        return candidates

                    # إن لم ينجح AI، أعد ترتيب الأزرار بحيث يأتي الرمز الموجود
                    # بعد عبارة التعليمات أولاً، ثم جرّب بقية الأزرار كلها.
                    target_emoji = None
                    try:
                        import re as _captcha_re
                        target_match = _captcha_re.search(
                            r"(?:اضغط\s+على\s+الرمز|اختر\s+الإيموجي|الإيموجي\s+الصحيح|"
                            r"correct\s+emoji|select\s+emoji|choose\s+emoji|pick\s+emoji)"
                            r"\s*[:：]?\s*(.*)$",
                            msg_text,
                            flags=_captcha_re.IGNORECASE,
                        )
                        target_tail = target_match.group(1) if target_match else msg_text
                        for text_emoji in _extract_emojis_from_text(target_tail):
                            if any(text_emoji in label for label in btn_labels):
                                target_emoji = text_emoji
                                break
                    except Exception:
                        target_emoji = None

                    fallback_attempts = 0
                    while fallback_attempts < 12:
                        candidates = [
                            item for item in _candidate_buttons(current_msgs or msgs)
                            if item[0] not in attempted_labels
                        ]
                        if target_emoji:
                            candidates.sort(key=lambda item: 0 if target_emoji in item[0] else 1)
                        if not candidates:
                            break
                        label, button = candidates[0]
                        attempted_labels.add(label)
                        fallback_attempts += 1
                        processed_ids.add(msg_id)
                        last_result, current_msgs = await _click_button_and_check(
                            label, button, "fallback"
                        )
                        if last_result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"

                    if attempted_labels:
                        logger.warning(
                            f"⚠️ لم يكتمل Captcha بعد تجربة {len(attempted_labels)} زر/أزرار ({phone})"
                        )
                except Exception as _e:
                    logger.warning(f"⚠️ AI button captcha ({phone}): {_e}")
                continue
                continue

            # ════════════════════════════════════════════════════
            # 5. سؤال نصي / رياضي / إيموجي كرسالة نصية
            # ════════════════════════════════════════════════════
            if msg_text and not has_btns and not has_media and not has_poll:
                is_captcha_q = any(k in msg_text_lower for k in CAPTCHA_KW)
                is_math_q    = any(k in msg_text_lower for k in MATH_KW)
                is_react_q   = any(k in msg_text_lower for k in REACTION_KW)
                if not (is_captcha_q or is_math_q or is_react_q):
                    continue
                try:
                    prompt = (
                        f"بوت تيليغرام يطرح هذا السؤال للتحقق:\n{msg_text}\n\n"
                        "أجب بالرقم أو النص أو الإيموجي المطلوب فقط "
                        "بدون أي شرح أو رموز إضافية. إذا كان السؤال رياضياً أجب بالرقم فقط."
                    )
                    answer = await _gemini_text(prompt)
                    if answer:
                        logger.info(f"🤖 AI سؤال نصي → '{answer}' ({phone})")
                        processed_ids.add(msg_id)
                        await asyncio.sleep(1)
                        await client.send_message(bot_entity, answer)
                        result, msgs = await _wait_and_check()
                        detail = f"أجاب: {answer}"
                        all_details.append(detail)
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result == "fail":
                            break  # حاول مجدداً
                        else:
                            return True, f"أُرسلت الإجابة | {' | '.join(all_details)}"
                except Exception as _e:
                    logger.warning(f"⚠️ AI text captcha ({phone}): {_e}")

            # ════════════════════════════════════════════════════
            # 6. ردود فعل Reactions (البوت يطلب تفاعلاً على رسالة)
            # ════════════════════════════════════════════════════
            if any(k in msg_text_lower for k in REACTION_KW):
                try:
                    from telethon.tl.functions.messages import SendReactionRequest
                    from telethon.tl.types import ReactionEmoji
                    prompt = (
                        f"بوت تيليغرام يطلب منك التفاعل:\n{msg_text}\n\n"
                        "ما هو الإيموجي أو التفاعل المطلوب؟ "
                        "أجب بالإيموجي فقط (مثال: 👍 أو ❤️ أو 🔥)."
                    )
                    emoji_answer = await _gemini_text(prompt)
                    if emoji_answer:
                        # خذ أول إيموجي فقط
                        emoji_clean = emoji_answer.strip().split()[0]
                        processed_ids.add(msg_id)
                        await client(SendReactionRequest(
                            peer=bot_entity,
                            msg_id=msg_id,
                            reaction=[ReactionEmoji(emoticon=emoji_clean)],
                        ))
                        result, msgs = await _wait_and_check()
                        detail = f"تفاعل: {emoji_clean}"
                        all_details.append(detail)
                        logger.info(f"🤖 AI Reaction → '{emoji_clean}' ({phone})")
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result != "fail":
                            return True, f"أُرسل التفاعل | {' | '.join(all_details)}"
                except Exception as _e:
                    logger.warning(f"⚠️ AI reaction ({phone}): {_e}")

    # ── النتيجة النهائية ───────────────────────────────────────
    if all_details:
        return True, f"حُلّ جزئياً | {' | '.join(all_details)}"
    return False, "لم يُكتشف تحقق"


# ═══════════════════════════════════════════════════════════
# دوال مساعدة لتسلسل الإحالة الإجبارية
# ═══════════════════════════════════════════════════════════

async def _join_channels_from_buttons(client, msgs: list) -> int:
    """
    يفحص أزرار رسائل البوت ويجمع روابط القنوات (t.me) وينضم إليها.
    يُرجع عدد القنوات التي انضم إليها بنجاح.
    """
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.tl.functions.messages import ImportChatInviteRequest
    joined = 0
    for msg in msgs:
        if not msg.buttons:
            continue
        for row in msg.buttons:
            for btn in row:
                url = getattr(btn, "url", None) or ""
                if "t.me/" not in url and "telegram.me/" not in url:
                    continue
                last_seg = url.rstrip("/").split("/")[-1].split("?")[0]
                # تجاهل روابط ليست قنوات (share، start، إلخ)
                if not last_seg or last_seg.lower().startswith(("share", "start")):
                    continue
                try:
                    if "/+" in url or "joinchat/" in url:
                        invite_part = url.split("/+")[-1] if "/+" in url else url.split("joinchat/")[-1]
                        invite_part = invite_part.split("?")[0].strip()
                        if invite_part:
                            await client(ImportChatInviteRequest(invite_part))
                            joined += 1
                    else:
                        ch_entity = await client.get_entity(last_seg)
                        await client(JoinChannelRequest(ch_entity))
                        joined += 1
                    await asyncio.sleep(1.5)
                except Exception as _e:
                    logger.debug(f"_join_channels_from_buttons: {last_seg} — {_e}")
    return joined


async def _click_check_subscription_button(client, bot_entity, msgs: list) -> bool:
    """
    بعد الانضمام لقنوات البوت، يبحث عن زر "تحقق من الاشتراك" ويضغطه.
    يُرجع True إذا وُجد الزر وتم ضغطه.
    """
    CHECK_KW = [
        "تحقق", "اشتركت", "✅", "تم", "joined", "check", "verify",
        "تم الاشتراك", "لقد اشتركت", "متابع", "اشتراك", "انضممت",
        "i've joined", "i joined", "subscribed",
    ]
    for msg in msgs:
        if not msg.buttons:
            continue
        for row in msg.buttons:
            for btn in row:
                btn_text = (getattr(btn, "text", "") or "").lower()
                if any(k in btn_text for k in CHECK_KW):
                    try:
                        await btn.click()
                        logger.info(f"✅ ضغط زر التحقق من الاشتراك: '{btn.text}'")
                        return True
                    except Exception as _e:
                        logger.debug(f"_click_check_subscription_button: {_e}")
    return False


async def do_referral_for_number(phone: str, session_str: str, bot_username: str, start_param: str,
                                  mandatory_channels: str = "", folder_link: str = "",
                                  use_ai: bool = False, leave_channels_after: bool = False,
                                  stock_id: int = 0) -> tuple:
    """
    تسلسل الإحالة الإجبارية الصحيح:
      1. ينضم للقنوات الإجبارية المحددة مسبقاً (قنوات بوتنا الإجبارية)
      2. ينضم للمجلد إن وُجد
      3. يضغط رابط الدعوة (StartBotRequest مع start_param)
      4. يفحص ردّ البوت: إذا طلب الانضمام لقنوات → ينضم ثم يضغط زر التحقق من الاشتراك
      5. إذا كان النوع "بتحقق" (use_ai=True) → يحل التحقق بالذكاء الاصطناعي
         إذا كان "بدون تحقق" (use_ai=False) → يتجاوز أي تحقق ويُسجَّل كنجاح

    يُرجع (success: bool, reactivated: bool, detail: str).
    — success=True,  reactivated=False → نجاح حقيقي (أول تفعيل)
    — success=True,  reactivated=True  → البوت كان مفعّلاً مسبقاً (لا تعويض)
    — success=False, reactivated=False → فشل حقيقي (تُستردّ نقاطه تلقائياً)
    """
    # ── تخطي فوري: إذا كان البوت المستهدف هو البوت نفسه (ارشقلي) ──
    _clean_target = bot_username.lower().lstrip("@").strip()
    if _OWN_BOT_USERNAME and _clean_target == _OWN_BOT_USERNAME:
        return True, True, "البوت المستهدف هو البوت نفسه — تم التخطي تلقائياً (مكتمل)"

    # أخطاء تدل على انتهاء صلاحية الجلسة نهائياً — تستدعي تحديث DB
    _DEAD_SESSION_ERRORS = (
        "AuthKeyUnregistered", "SessionRevoked", "SessionExpired",
        "UserDeactivated", "AccountBanned", "PhoneNumberBanned",
        "AuthKeyDuplicated",
    )

    def _mark_session_dead(auto_delete: bool = False, reason: str = ""):
        """يضبط can_send_code=FALSE و last_authorized=FALSE و force_listed=FALSE.
        إذا auto_delete=True وstock_id مُعطى → يحذف الرقم فوراً من المخزون."""
        try:
            with db_conn() as _dc:
                _dc.execute(
                    "UPDATE number_stock SET can_send_code=FALSE, last_authorized=FALSE, force_listed=FALSE "
                    "WHERE phone_number=%s AND ever_sold IS NOT TRUE",
                    (phone,)
                )
            logger.info(f"🔴 جلسة {phone} مُعلَّمة كمنتهية في DB (force_listed أُزيل تلقائياً)")
        except Exception as _de:
            logger.debug(f"_mark_session_dead {phone}: {_de}")
        if auto_delete and stock_id:
            _auto_delete_number(stock_id, phone, reason or "حساب محذوف أو مجمّد")

    client = TelegramClient(
        StringSession(session_str),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            _mark_session_dead(auto_delete=True, reason="حساب محذوف أو جلسة مُلغاة — حُذف تلقائياً")
            return False, False, "جلسة منتهية أو مُلغاة — حُذف من المخزون"

        steps = []

        # ── الخطوة 1: الانضمام للقنوات الإجبارية المحددة مسبقاً ──
        if mandatory_channels and mandatory_channels.strip():
            cnt = await _join_mandatory_channels(client, mandatory_channels)
            if cnt:
                steps.append(f"انضم لـ {cnt} قناة إجبارية")

        # ── الخطوة 2: الانضمام للمجلد (إن وُجد) ──
        if folder_link and folder_link.strip():
            folder_result = await _join_folder_link(client, folder_link)
            steps.append(folder_result)
            await asyncio.sleep(1)

        # نستخدم ResolveUsernameRequest مباشرةً بدل get_entity لتجنّب
        # ValueError "No user has X as username" عند الأرقام التي لم تتحدث
        # مع البوت المستهدف من قبل (الكاش المحلي فارغ).
        _clean_uname = bot_username.lstrip("@").strip()
        try:
            _resolved = await asyncio.wait_for(
                client(ResolveUsernameRequest(_clean_uname)), timeout=15
            )
            bot_entity = _resolved.users[0] if _resolved.users else _resolved.chats[0]
        except (IndexError, Exception) as _re:
            raise ValueError(f"تعذّر إيجاد البوت @{_clean_uname}: {_re}")

        # ── كشف إعادة التفعيل: هل البوت مفعّل مسبقاً؟ ──
        _was_reactivated = False
        try:
            _prev_msgs = await asyncio.wait_for(client.get_messages(bot_entity, limit=1), timeout=10)
            if _prev_msgs and len(_prev_msgs) > 0:
                _was_reactivated = True
        except Exception:
            pass

        # ── الخطوة 3: ضغط رابط الدعوة ──
        await asyncio.wait_for(
            client(StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param or '',
            )),
            timeout=20,
        )
        await asyncio.sleep(3)
        msgs = await asyncio.wait_for(client.get_messages(bot_entity, limit=8), timeout=10)

        # ── الخطوة 4: التعامل مع اشتراط البوت الانضمام لقنواته (حلقة متكررة) ──
        # يكرر: انضم للقنوات من ردود البوت → تحقق من الاشتراك → رسائل جديدة
        # يستمر حتى لا توجد قنوات جديدة أو يبلغ الحد الأقصى (6 جولات)
        _total_joined_from_bot = 0
        for _sub_round in range(6):
            joined_channels = await _join_channels_from_buttons(client, msgs)
            if joined_channels == 0:
                break  # لا قنوات جديدة → خروج من الحلقة
            _total_joined_from_bot += joined_channels
            steps.append(f"انضم لـ {joined_channels} قناة من رد البوت (جولة {_sub_round + 1})")
            await asyncio.sleep(2)
            # بعد الانضمام، ابحث عن زر التحقق من الاشتراك واضغطه
            _clicked = await _click_check_subscription_button(client, bot_entity, msgs)
            if _clicked:
                steps.append(f"ضغط زر التحقق من الاشتراك (جولة {_sub_round + 1})")
            await asyncio.sleep(4)
            # احصل على رسائل جديدة — قد تحتوي على قنوات إضافية تطلبها
            msgs = await asyncio.wait_for(client.get_messages(bot_entity, limit=8), timeout=10)
        if _total_joined_from_bot > 0:
            logger.info(f"🔗 {phone}: انضم إجمالاً لـ {_total_joined_from_bot} قناة من ردود البوت")

        # ── الخطوة 5: حل التحقق (كابتشا) ──
        # "بتحقق" (use_ai=True)  → يحاول حل أي تحقق يطلبه البوت بالذكاء الاصطناعي
        # "بدون تحقق" (use_ai=False) → يتجاوز التحقق تماماً ويُسجَّل كنجاح
        if use_ai:
            _ai_solved, _ai_detail = await solve_captcha_with_ai(client, bot_entity, msgs, phone)
            if _ai_solved:
                steps.append(f"🤖 AI: {_ai_detail}")

        # سجّل أول رسالة وصلت من البوت للتشخيص
        if msgs:
            _last_txt = getattr(msgs[0], 'text', '') or ''
            if _last_txt:
                logger.info(f"📨 ردّ البوت ({phone}→@{bot_username}): {_last_txt[:120]}")

        # ── مغادرة القنوات الإجبارية بعد اكتمال العملية (إن طُلب ذلك) ──
        if leave_channels_after and mandatory_channels and mandatory_channels.strip():
            try:
                left_count = await _leave_mandatory_channels(client, mandatory_channels)
                if left_count:
                    steps.append(f"غادر {left_count} قناة إجبارية")
            except Exception as _le:
                logger.warning(f"⚠️ تعذّر مغادرة القنوات لـ {phone}: {_le}")

        if _was_reactivated:
            detail = "إعادة تفعيل (البوت كان مفعّلاً مسبقاً)" + (f" | {' | '.join(steps)}" if steps else "")
            return True, True, detail

        detail = "تمت الإحالة بنجاح" + (f" | {' | '.join(steps)}" if steps else "")
        return True, False, detail

    except PeerFloodError:
        # PeerFlood = تيليجرام يكتشف ضغطاً متكرراً على نفس البوت من حسابات كثيرة
        # هذا الحساب يُعدّ فاشلاً لكنه لا يزال صالحاً — لا نمسح can_send_code
        logger.warning(f"⚠️ PeerFlood {phone}→@{bot_username}: الحساب مقيّد مؤقتاً من تيليجرام")
        return False, False, "PeerFlood — مقيّد مؤقتاً (حاول لاحقاً)"

    except FloodWaitError as fw:
        # FloodWait = تيليجرام يطلب الانتظار X ثانية
        wait_sec = fw.seconds + 2
        logger.warning(f"⏳ FloodWait {phone}: انتظار {wait_sec}ث...")
        try:
            await asyncio.sleep(min(wait_sec, 90))
            # إعادة محاولة واحدة بعد انتهاء FloodWait
            async with TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH) as _retry_cli:
                if not await asyncio.wait_for(_retry_cli.is_user_authorized(), timeout=10):
                    return False, False, "جلسة منتهية (بعد FloodWait)"
                _clean_uname2 = bot_username.lstrip("@").strip()
                _resolved2 = await asyncio.wait_for(
                    _retry_cli(ResolveUsernameRequest(_clean_uname2)), timeout=15
                )
                _bot_e = _resolved2.users[0] if _resolved2.users else _resolved2.chats[0]
                await asyncio.wait_for(
                    _retry_cli(StartBotRequest(bot=_bot_e, peer=_bot_e, start_param=start_param or '')),
                    timeout=20,
                )
                await asyncio.sleep(3)
                return True, False, f"نجح بعد FloodWait {fw.seconds}ث"
        except Exception as _fw_e:
            logger.error(f"❌ فشل بعد FloodWait {phone}: {_fw_e}")
            return False, False, f"FloodWait {fw.seconds}ث ثم فشل: {str(_fw_e)[:80]}"

    except (UserBannedInChannelError, ChatWriteForbiddenError, UserPrivacyRestrictedError) as _restrict_e:
        # قيود خاصة بهذا الحساب — لا تُعطّل can_send_code لأن الحساب صالح للعمليات الأخرى
        logger.warning(f"⚠️ قيد خاص {phone}: {type(_restrict_e).__name__}")
        return False, False, f"قيد حساب: {type(_restrict_e).__name__}"

    except Exception as e:
        err = str(e)
        err_type = type(e).__name__
        # جلسة منتهية نهائياً أو حساب محذوف → حدّث DB وأحذفه من المخزون فوراً
        if any(k in err_type for k in _DEAD_SESSION_ERRORS):
            _mark_session_dead(auto_delete=True, reason=f"حساب محذوف/مجمّد ({err_type}) — حُذف تلقائياً")
        logger.error(f"❌ فشلت إحالة {phone} → {bot_username} [{err_type}]: {err[:100]}")
        return False, False, f"[{err_type}] {err[:100]}"
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
