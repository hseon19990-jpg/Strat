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
import json
import mimetypes
import requests
import logging
import subprocess
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

from telethon import TelegramClient, events, functions
from telethon.sessions import StringSession
from telethon.tl.types import (
    DocumentAttributeVideo,
    InputMediaUploadedDocument,
    InputMediaUploadedPhoto,
    InputPrivacyValueAllowAll,
)
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

def _parse_hex_session_text(raw_text: str) -> tuple[list[str], list[str], bool]:
    """يقرأ نص auth_key_hex:dc_id دون إعادة النص الحساس في رسائل الخطأ."""
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return [], [], False

    candidate_lines = []
    for line in lines:
        if ":" not in line:
            return [], [], False
        hex_part, dc_part = line.rsplit(":", 1)
        compact_hex = "".join(hex_part.split())
        if dc_part.strip() not in {"1", "2", "3", "4", "5"}:
            return [], [], False
        if not re.fullmatch(r"[0-9a-fA-F]{512}", compact_hex):
            return [], [], False
        candidate_lines.append((compact_hex, int(dc_part.strip())))

    sessions = []
    bad_lines = []
    for index, (hex_part, dc_id) in enumerate(candidate_lines, start=1):
        converted = pyrogram_json_to_telethon({"dc_id": dc_id, "auth_key": hex_part})
        if converted:
            sessions.append(converted)
        else:
            bad_lines.append(f"السطر {index}: auth_key غير صالح")
    return sessions, bad_lines, True

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
from telethon.tl.functions.photos import UploadProfilePhotoRequest
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
_avatar_upload_locks = {}  # owner_id -> asyncio.Lock لمنع معالجة صور الألبوم بالتوازي
_avatar_album_buffers = {}  # (owner_id, media_group_id) -> {"file_ids": [], "chat_id": int}
_avatar_album_tasks = {}  # (owner_id, media_group_id) -> debounce task
_story_upload_locks = {}  # owner_id -> asyncio.Lock لمنع معالجة صور الستوري بالتوازي
_story_album_buffers = {}  # (owner_id, media_group_id) -> {"file_ids": [], "chat_id": int}
_story_album_tasks = {}  # (owner_id, media_group_id) -> debounce task
_EXPECTED_2FA_WINDOW_SEC = 180
_allow_5min_phones = {}  # phone_number -> {"until": float, "used": bool}
_permanently_allowed_phones = set()  # أرقام فيها جلسة خارجية مسموح لها بالبقاء للأبد
_OWN_BOT_USERNAME: str = ""          # يُضبط عند الإقلاع — يُستخدم لتخطي الإحالة الذاتية
JUSTANOTHERPANEL_API_URL = "https://justanotherpanel.com/api/v2"
SMMFOLLOWS_API_URL       = "https://smmfollows.com/api/v2"

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
