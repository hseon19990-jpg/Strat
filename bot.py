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
import sqlite3
import random
import math
import requests
import logging
from datetime import datetime, date
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice, PreCheckoutQuery, BotCommand, BotCommandScopeChat
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, PreCheckoutQueryHandler,
    ContextTypes, filters
)
from telegram.constants import ParseMode

logging.basicConfig(level=logging.INFO)
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
#  قاعدة البيانات
# ────────────────────────────────────────────────────────────
DB_FILE = "bot.db"

def db_conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db_conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id      INTEGER PRIMARY KEY,
            username     TEXT,
            full_name    TEXT,
            points       INTEGER DEFAULT 0,
            invited_by   INTEGER DEFAULT 0,
            total_orders INTEGER DEFAULT 0,
            joined_at    TEXT DEFAULT (date('now')),
            bot_user_num INTEGER,
            verified     INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS orders (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER,
            service_id   INTEGER,
            link         TEXT,
            quantity     INTEGER,
            cost_points  INTEGER DEFAULT 0,
            cost_stars   INTEGER DEFAULT 0,
            api_order_id TEXT DEFAULT '',
            status       TEXT DEFAULT 'pending',
            order_code   TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS services (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            category        TEXT,
            api_service_id  INTEGER,
            panel           INTEGER DEFAULT 1,
            name_ar         TEXT,
            description     TEXT,
            min_qty         INTEGER,
            max_qty         INTEGER,
            price_per_point REAL,
            active          INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS daily_gifts (
            user_id    INTEGER PRIMARY KEY,
            last_claim TEXT
        );

        CREATE TABLE IF NOT EXISTS channel_funding (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER,
            channel_username TEXT,
            funding_type     TEXT,
            cost_points      INTEGER,
            active           INTEGER DEFAULT 1,
            created_at       TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS star_transactions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id             INTEGER,
            stars               INTEGER,
            points_given        INTEGER,
            telegram_payment_id TEXT,
            status              TEXT DEFAULT 'completed',
            created_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS point_transfers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user  INTEGER,
            to_user    INTEGER,
            points     INTEGER,
            fee        INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS prize_exchanges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            prize_type  TEXT,
            prize_value TEXT,
            points_cost INTEGER,
            status      TEXT DEFAULT 'pending',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS mandatory_channels (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_username TEXT,
            channel_title    TEXT,
            owner_user_id    INTEGER DEFAULT 0,
            funding_type     TEXT DEFAULT 'mandatory',
            active           INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS promo_codes (
            code       TEXT PRIMARY KEY,
            max_uses   INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            points     INTEGER DEFAULT 0,
            active     INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS promo_uses (
            code    TEXT,
            user_id INTEGER,
            PRIMARY KEY (code, user_id)
        );

        CREATE TABLE IF NOT EXISTS exchange_star_packages (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            stars  INTEGER NOT NULL,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS channel_join_rewards (
            user_id    INTEGER,
            channel_id INTEGER,
            PRIMARY KEY (user_id, channel_id)
        );

        INSERT OR IGNORE INTO settings VALUES ('join_channel_reward','20');
        INSERT OR IGNORE INTO settings VALUES ('daily_gift_points','50');
        INSERT OR IGNORE INTO settings VALUES ('referral_points','30');
        INSERT OR IGNORE INTO settings VALUES ('star_to_points','250');
        INSERT OR IGNORE INTO settings VALUES ('exchange_star_rate','2000');
        INSERT OR IGNORE INTO settings VALUES ('telegram_number_cost','5000');
        INSERT OR IGNORE INTO settings VALUES ('transfer_fee_percent','1');
        INSERT OR IGNORE INTO settings VALUES ('mandatory_channel_cost','200');
        INSERT OR IGNORE INTO settings VALUES ('internal_channel_cost','100');
        INSERT OR IGNORE INTO settings VALUES ('welcome_message','أهلاً وسهلاً بك في البوت!');
        INSERT OR IGNORE INTO settings VALUES ('owner_contact','');
        INSERT OR IGNORE INTO settings VALUES ('total_bot_orders','0');
        INSERT OR IGNORE INTO settings VALUES ('total_bot_users','0');
        INSERT OR IGNORE INTO settings VALUES ('asiacell_text','⚠️ الشحن التلقائي عبر اسيا سيل غير متاح حالياً.\nيرجى التواصل مع المالك.');
        INSERT OR IGNORE INTO settings VALUES ('captcha_enabled','0');
        """)
    # إضافة عمود verified للمستخدمين القدامى
    try:
        with db_conn() as c:
            c.execute("ALTER TABLE users ADD COLUMN verified INTEGER DEFAULT 0")
    except Exception:
        pass
    # إضافة عمود panel (الموقع المصدر) للخدمات القديمة
    try:
        with db_conn() as c:
            c.execute("ALTER TABLE services ADD COLUMN panel INTEGER DEFAULT 1")
    except Exception:
        pass

def get_setting(key: str) -> str:
    with db_conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else ""

def set_setting(key: str, value: str):
    with db_conn() as c:
        c.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))

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
        if invited_by and invited_by != user_id:
            rp = int(get_setting("referral_points") or "30")
            c.execute("UPDATE users SET points=points+? WHERE user_id=?", (rp, invited_by))
        return dict(c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone())

def set_user_verified(user_id: int):
    with db_conn() as c:
        c.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))

def is_user_verified(user_id: int) -> bool:
    with db_conn() as c:
        row = c.execute("SELECT verified FROM users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row["verified"])

def add_points(user_id: int, pts: int):
    with db_conn() as c:
        c.execute("UPDATE users SET points=points+? WHERE user_id=?", (pts, user_id))

def deduct_points(user_id: int, pts: int) -> bool:
    with db_conn() as c:
        row = c.execute("SELECT points FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row or row["points"] < pts:
            return False
        c.execute("UPDATE users SET points=points-? WHERE user_id=?", (pts, user_id))
        return True

def get_user(user_id: int) -> dict | None:
    with db_conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

def next_order_code(user_id: int) -> str:
    with db_conn() as c:
        u = c.execute("SELECT bot_user_num, total_orders FROM users WHERE user_id=?", (user_id,)).fetchone()
        new_user_orders = (u["total_orders"] or 0) + 1
        c.execute("UPDATE users SET total_orders=? WHERE user_id=?", (new_user_orders, user_id))
        total = int(get_setting("total_bot_orders") or "0") + 1
        set_setting("total_bot_orders", str(total))
        return f"{new_user_orders}-{u['bot_user_num']}-{total}"

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
CATEGORY_MAP = {
    "followers":    "رشق متابعين",
    "views":        "رشق مشاهدات",
    "interactions": "رشق تفاعلات",
    "story_views":  "رشق مشاهدات ستوري",
    "start_bot":    "بدء بوت",
    "boost":        "تعزيز قناة أو كروب",
    "post_stars":   "نجوم على بوست قناة",
}

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
    rows = [
        [InlineKeyboardButton("👥 رشق متابعين", callback_data="cat:followers"),
         InlineKeyboardButton("📺 تمويل قناتك حقيقي", callback_data="fund_channel")],
        [InlineKeyboardButton("👁 رشق مشاهدات", callback_data="cat:views"),
         InlineKeyboardButton("💬 رشق تفاعلات", callback_data="cat:interactions")],
        [InlineKeyboardButton("📖 رشق مشاهدات ستوري", callback_data="cat:story_views"),
         InlineKeyboardButton("🤖 بدء بوت", callback_data="cat:start_bot")],
        [InlineKeyboardButton("📣 تعزيز قناة أو كروب", callback_data="cat:boost"),
         InlineKeyboardButton("⭐ نجوم على بوست قناة", callback_data="cat:post_stars")],
        [InlineKeyboardButton("🔗 رابط دعوة", callback_data="referral"),
         InlineKeyboardButton("🎁 هدية يومية", callback_data="daily_gift")],
        [InlineKeyboardButton("📡 انضمام بقنوات", callback_data="join_channels"),
         InlineKeyboardButton("💎 شحن نقاط", callback_data="charge_points")],
        [InlineKeyboardButton("🏆 استبدال نقاط بجوائز", callback_data="exchange_points"),
         InlineKeyboardButton("↔️ تحويل النقاط", callback_data="transfer_points")],
        [InlineKeyboardButton("🎟 استخدام كود", callback_data="use_promo"),
         InlineKeyboardButton("ℹ️ معلوماتي", callback_data="my_info")],
    ]
    if is_owner:
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


def owner_settings_kb():
    rows = [
        [InlineKeyboardButton("➕ إضافة خدمة", callback_data="os:add_service"),
         InlineKeyboardButton("📋 قائمة الخدمات", callback_data="os:list_services")],
        [InlineKeyboardButton("🎁 تعديل الهدية اليومية", callback_data="os:edit_gift"),
         InlineKeyboardButton("🔗 تعديل نقاط الدعوة", callback_data="os:edit_referral")],
        [InlineKeyboardButton("⭐ سعر النجمة شحن", callback_data="os:edit_star_rate"),
         InlineKeyboardButton("🏆 سعر نجمة الجوائز", callback_data="os:edit_exchange_rate")],
        [InlineKeyboardButton("📦 باقات الاستبدال بنجوم", callback_data="os:manage_star_packages")],
        [InlineKeyboardButton("📱 سعر رقم تيلغرام", callback_data="os:edit_number_cost"),
         InlineKeyboardButton("💌 رسالة الترحيب", callback_data="os:edit_welcome")],
        [InlineKeyboardButton("📢 سعر تمويل إجباري", callback_data="os:edit_mandatory_cost"),
         InlineKeyboardButton("🔄 سعر تمويل داخلي", callback_data="os:edit_internal_cost")],
        [InlineKeyboardButton("🎁 نقاط الانضمام للقنوات", callback_data="os:edit_join_reward")],
        [InlineKeyboardButton("📡 إدارة قنوات الاشتراك", callback_data="os:manage_channels"),
         InlineKeyboardButton("❌ إلغاء صفقة", callback_data="os:cancel_order")],
        [InlineKeyboardButton("🎟 إنشاء كود ترويجي", callback_data="os:create_promo"),
         InlineKeyboardButton("📋 أكواد ترويجية", callback_data="os:list_promos")],
        [InlineKeyboardButton("📲 تعديل نص اسيا سيل", callback_data="os:edit_asiacell"),
         InlineKeyboardButton("📢 رسالة جماعية", callback_data="os:broadcast")],
        [InlineKeyboardButton("🔐 تفعيل/تعطيل التحقق", callback_data="os:toggle_captcha"),
         InlineKeyboardButton("📊 إحصائيات", callback_data="os:stats")],
        [InlineKeyboardButton("💵 رصيد موقع الرشق", callback_data="os:site_balance")],
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
    ]
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ استبدال نقاط بنجوم", callback_data="exchange:stars")],
        [InlineKeyboardButton("📱 شراء رقم تيلغرام", callback_data="exchange:number")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
    ])

def fund_channel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 تمويل قناة إجباري سريع", callback_data="fund:mandatory")],
        [InlineKeyboardButton("🔄 تمويل قناة داخلي بطيء", callback_data="fund:internal")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
    ])

def back_kb(target="main_menu"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=target)]])

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
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
    text = f"📦 *{CATEGORY_MAP.get(category, category)}*\nاختر الخدمة المطلوبة:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                                      parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                        parse_mode=ParseMode.MARKDOWN)

# ────────────────────────────────────────────────────────────
#  /start
# ────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    invited_by = int(args[0]) if args and args[0].isdigit() else 0

    # تحقق هل المستخدم موجود في قاعدة البيانات قبل التسجيل
    existing = get_user(user.id)
    is_new_user = existing is None

    db_user = get_or_create_user(user.id, user.username or "", user.full_name or "", invited_by)
    is_own = (user.id == OWNER_ID)

    # ── إشعارات نظام الدعوة (تُرسل مرة واحدة فقط عند أول دخول فعلي للمستخدم الجديد) ──
    referral_note = ""
    if is_new_user and invited_by and invited_by != user.id:
        rp = int(get_setting("referral_points") or "30")
        invited_name = f"@{user.username}" if user.username else (user.full_name or "مستخدم")
        inviter_row = get_user(invited_by)
        inviter_name = "صديقك"
        if inviter_row:
            inviter_username = inviter_row.get("username")
            inviter_full_name = inviter_row.get("full_name")
            inviter_name = f"@{inviter_username}" if inviter_username else (inviter_full_name or "صديقك")

        try:
            await context.bot.send_message(
                chat_id=invited_by,
                text=f"🎉 مبروك! لقد دخل المستخدم {invited_name} عن طريق رابط دعوتك، وحصلت على {rp} نقطة.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

        referral_note = f"\n\n🔗 لقد دخلت إلى رابط دعوة صديقك {inviter_name} وقد حصل على {rp} نقطة."

    # مستخدم موجود سابقاً أو متحقق مسبقاً → القائمة مباشرة
    if not is_new_user or db_user.get("verified", 0):
        if not db_user.get("verified", 0):
            set_user_verified(user.id)
        context.user_data["state"] = "main_menu"
        pts = db_user["points"]
        welcome = get_setting("welcome_message") or "أهلاً بك!"
        await update.message.reply_text(
            f"👋 *أهلاً بك مجدداً!*\n\n{welcome}\n\n💰 رصيدك: {pts} نقطة{referral_note}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )
        return

    # مستخدم جديد فعلاً: تحقق هل التحقق الرياضي مفعّل
    captcha_on = int(get_setting("captcha_enabled") or "0")
    if not captcha_on:
        # التحقق معطّل → دخول مباشر وتسجيل كمتحقق
        set_user_verified(user.id)
        context.user_data["state"] = "main_menu"
        pts = db_user["points"]
        welcome = get_setting("welcome_message") or "أهلاً بك!"
        await update.message.reply_text(
            f"👋 *أهلاً بك!*\n\n{welcome}\n\n💰 رصيدك: {pts} نقطة{referral_note}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )
        return

    # التحقق مفعّل → سؤال رياضي للمستخدمين الجدد فقط
    prob, ans = generate_math()
    context.user_data.clear()
    context.user_data["state"] = "verify_math"
    context.user_data["math_ans"] = ans
    # احفظ إشعار الدعوة (بعد clear) لعرضه بعد نجاح التحقق الرياضي
    if referral_note:
        context.user_data["referral_note"] = referral_note

    await update.message.reply_text(
        f"👋 *أهلاً بك!*\n\n🔐 للدخول للبوت، أجب على هذه المسألة البسيطة:\n\n"
        f"❓  *{prob} = ؟*",
        parse_mode=ParseMode.MARKDOWN
    )

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

# ────────────────────────────────────────────────────────────
#  معالج الرسائل النصية (آلة الحالة)
# ────────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    text   = update.message.text.strip()
    state  = context.user_data.get("state", "")
    is_own = (user.id == OWNER_ID)

    # ── التحقق الرياضي ──
    if state == "verify_math":
        correct = context.user_data.get("math_ans")
        try:
            ans = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً فقط.")
            return
        if ans == correct:
            context.user_data["state"] = "main_menu"
            set_user_verified(user.id)
            db_user = get_user(user.id)
            pts = db_user["points"] if db_user else 0
            welcome = get_setting("welcome_message") or "أهلاً بك!"
            referral_note = context.user_data.pop("referral_note", "")
            await update.message.reply_text(
                f"✅ *إجابة صحيحة!*\n\n{welcome}\n\n💰 رصيدك: {pts} نقطة{referral_note}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
        else:
            prob, new_ans = generate_math()
            context.user_data["math_ans"] = new_ans
            await update.message.reply_text(
                f"❌ إجابة خاطئة! حاول مجدداً:\n\n❓  *{prob} = ؟*",
                parse_mode=ParseMode.MARKDOWN
            )
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
                    f"❌ فشل الطلب: {err_msg}\nتمت إعادة نقاطك.",
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
                f"💰 التكلفة: {cost} نقطة\n\n"
                f"📌 *كود عمليتك هو: `{code}`*\nاحفظه قد تحتاجه لاحقاً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
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
                    f"💰 {pts} نقطة إلى المستخدم.\n"
                    f"📌 *كود عمليتك: `{code}`*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=main_menu_kb(is_own)
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
        context.user_data["exchange_stars"] = stars
        context.user_data["exchange_cost"]  = cost
        context.user_data["state"] = "confirm_exchange_stars"
        await update.message.reply_text(
            f"⭐ *تأكيد الاستبدال:*\n\n"
            f"⭐ عدد النجوم: {stars}\n"
            f"💰 التكلفة: {cost} نقطة\n"
            f"💎 رصيدك: {pts} نقطة\n\n"
            f"أرسل *نعم* للتأكيد أو *لا* للإلغاء",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if state == "confirm_exchange_stars":
        if text == "نعم":
            stars = context.user_data.get("exchange_stars", 0)
            cost  = context.user_data.get("exchange_cost", 0)
            if not deduct_points(user.id, cost):
                await update.message.reply_text("❌ نقاطك غير كافية.", reply_markup=main_menu_kb(is_own))
                context.user_data["state"] = "main_menu"
                return
            code = next_order_code(user.id)
            with db_conn() as c:
                c.execute(
                    "INSERT INTO prize_exchanges (user_id,prize_type,prize_value,points_cost,status) VALUES (?,?,?,?,'pending')",
                    (user.id, "stars", str(stars), cost)
                )
            await update.message.reply_text(
                f"✅ *تمت العملية بنجاح!*\n\n"
                f"⭐ طلب {stars} نجمة مسجل\n"
                f"💰 التكلفة: {cost} نقطة\n\n"
                f"📌 *كود عمليتك: `{code}`*\nسيتواصل معك المالك قريباً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
            )
            await notify_group(
                context.application,
                f"⭐ <b>طلب شراء نجوم (جائزة)</b>\n"
                f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                f"⭐ {stars} نجمة مقابل {cost} نقطة\n"
                f"📌 {code}"
            )
        else:
            await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_kb(is_own))
        context.user_data["state"] = "main_menu"
        return

    # ── استخدام كود ترويجي ──
    if state == "await_promo_code":
        code = text.strip().upper()
        with db_conn() as c:
            promo = c.execute("SELECT * FROM promo_codes WHERE code=? AND active=1", (code,)).fetchone()
        if not promo:
            await update.message.reply_text(
                "❌ الكود غير موجود أو منتهي الصلاحية.",
                reply_markup=main_menu_kb(is_own)
            )
            context.user_data["state"] = "main_menu"
            return
        # تحقق إذا استخدمه مسبقاً
        with db_conn() as c:
            used = c.execute("SELECT 1 FROM promo_uses WHERE code=? AND user_id=?", (code, user.id)).fetchone()
        if used:
            await update.message.reply_text(
                "⚠️ لقد استخدمت هذا الكود مسبقاً.",
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
        # تطبيق الكود
        pts_given = promo["points"]
        add_points(user.id, pts_given)
        with db_conn() as c:
            c.execute("UPDATE promo_codes SET used_count=used_count+1 WHERE code=?", (code,))
            c.execute("INSERT INTO promo_uses (code, user_id) VALUES (?,?)", (code, user.id))
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

    # ── تمويل قناة: إدخال اسم القناة ──
    if state == "await_fund_channel":
        fund_type = context.user_data.get("fund_type", "mandatory")
        cost_key  = "mandatory_channel_cost" if fund_type == "mandatory" else "internal_channel_cost"
        cost      = int(get_setting(cost_key) or "200")
        db_user   = get_user(user.id)
        if db_user["points"] < cost:
            await update.message.reply_text(
                f"❌ نقاطك غير كافية. السعر: {cost} نقطة.",
                reply_markup=main_menu_kb(is_own)
            )
            context.user_data["state"] = "main_menu"
            return
        channel = text.strip().lstrip("@")
        channel_id = f"@{channel}"

        # ── التحقق من أن البوت مشرف في القناة/الكروب ──
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
        deduct_points(user.id, cost)
        code = next_order_code(user.id)
        ft_label = "إجباري سريع" if fund_type == "mandatory" else "داخلي بطيء"
        with db_conn() as c:
            c.execute(
                "INSERT INTO channel_funding (user_id,channel_username,funding_type,cost_points) VALUES (?,?,?,?)",
                (user.id, channel, fund_type, cost)
            )
            if fund_type == "mandatory":
                c.execute(
                    "INSERT INTO mandatory_channels (channel_username,owner_user_id,funding_type) VALUES (?,?,?)",
                    (channel, user.id, "mandatory")
                )
            else:
                c.execute(
                    "INSERT INTO mandatory_channels (channel_username,owner_user_id,funding_type) VALUES (?,?,?)",
                    (channel, user.id, "internal")
                )
        await update.message.reply_text(
            f"✅ *تم تفعيل تمويل قناتك بنجاح!*\n\n"
            f"📢 القناة: @{channel}\n"
            f"⚙️ النوع: {ft_label}\n"
            f"💰 التكلفة: {cost} نقطة\n\n"
            f"📌 *كود عمليتك: `{code}`*\nاحفظه قد تحتاجه لاحقاً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )
        await notify_group(
            context.application,
            f"📢 <b>تمويل قناة {ft_label}</b>\n"
            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
            f"📡 القناة: @{channel}\n"
            f"💰 {cost} نقطة\n"
            f"📌 {code}"
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

    if is_own and state == "os_await_asiacell_text":
        set_setting("asiacell_text", text)
        await update.message.reply_text("✅ تم تحديث نص اسيا سيل.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
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
                    f"🔴 تم إلغاء طلبك بكود {o_code} وإعادة {pts} نقطة لرصيدك."
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
            c.execute("INSERT OR IGNORE INTO mandatory_channels (channel_username,funding_type) VALUES (?,'mandatory')", (channel,))
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
        await update.message.reply_text(f"✅ تم تحديث السعر إلى: {price} نقطة/1000 وحدة", reply_markup=owner_settings_kb())
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
        f"💰 السعر: {price} نقطة/1000 وحدة",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=owner_settings_kb()
    )
    context.user_data["state"] = "main_menu"


# ────────────────────────────────────────────────────────────
#  معالج Callback
# ────────────────────────────────────────────────────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query
    await q.answer()
    data   = q.data
    user   = q.from_user
    is_own = (user.id == OWNER_ID)

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
            f"💰 السعر: {svc['price_per_point']} نقطة / 1000 وحدة\n\n"
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
            f"💰 السعر: {svc['price_per_point']} نقطة / 1000 وحدة\n\n"
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
                    f"❌ فشل الطلب: {err_msg}\nتمت إعادة نقاطك.",
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
                f"💰 التكلفة: {cost} نقطة\n\n"
                f"📌 *كود عمليتك هو: `{code}`*\nاحفظه قد تحتاجه لاحقاً.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own)
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

    # ── الهدية اليومية ──
    if data == "daily_gift":
        today = str(date.today())
        with db_conn() as c:
            row = c.execute("SELECT last_claim FROM daily_gifts WHERE user_id=?", (user.id,)).fetchone()
            if row and row["last_claim"] == today:
                await q.edit_message_text(
                    "⏰ لقد استلمت هديتك اليومية بالفعل! عد غداً.",
                    reply_markup=back_kb()
                )
                return
            gift = int(get_setting("daily_gift_points") or "50")
            c.execute("INSERT OR REPLACE INTO daily_gifts VALUES (?,?)", (user.id, today))
            add_points(user.id, gift)
        db_user = get_user(user.id)
        await q.edit_message_text(
            f"🎁 *مبروك!* حصلت على هديتك اليومية!\n\n"
            f"✅ {gift} نقطة أضيفت لرصيدك\n"
            f"💰 رصيدك الآن: {db_user['points']} نقطة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_kb()
        )
        return

    # ── انضمام بقنوات ──
    if data == "join_channels":
        with db_conn() as c:
            channels = c.execute("SELECT * FROM mandatory_channels WHERE active=1 AND funding_type='internal'").fetchall()
        if not channels:
            await q.edit_message_text("📡 لا توجد قنوات للانضمام حالياً.", reply_markup=back_kb())
            return
        reward = int(get_setting("join_channel_reward") or "20")
        rows = []
        for ch in channels:
            # check if user already claimed this channel
            with db_conn() as c:
                claimed = c.execute("SELECT 1 FROM channel_join_rewards WHERE user_id=? AND channel_id=?",
                                    (user.id, ch['id'])).fetchone()
            status = "✅ تم" if claimed else "🎁 انضم واحصل على نقاط"
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
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
        await q.edit_message_text(
            f"📡 *قنوات الانضمام:*\n\n"
            f"🎁 انضم لأي قناة واحصل على *{reward} نقطة*\n"
            f"اضغط ✅ تحقق من انضمامي بعد الانضمام:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    # ── التحقق من الانضمام ومنح النقاط ──
    if data.startswith("join_verify:"):
        ch_id = int(data.split(":")[1])
        with db_conn() as c:
            ch = c.execute("SELECT * FROM mandatory_channels WHERE id=?", (ch_id,)).fetchone()
            already = c.execute("SELECT 1 FROM channel_join_rewards WHERE user_id=? AND channel_id=?",
                                (user.id, ch_id)).fetchone()
        if already:
            await q.answer("✔️ لقد حصلت على نقاط هذه القناة سابقاً.", show_alert=True)
            return
        if not ch:
            await q.answer("⚠️ القناة غير موجودة.", show_alert=True)
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
        reward = int(get_setting("join_channel_reward") or "20")
        add_points(user.id, reward)
        with db_conn() as c:
            c.execute("INSERT OR IGNORE INTO channel_join_rewards (user_id, channel_id) VALUES (?,?)",
                      (user.id, ch_id))
        db_user = get_user(user.id)
        await q.answer(f"🎉 حصلت على {reward} نقطة!", show_alert=True)
        # تحديث القائمة
        channels = []
        with db_conn() as c:
            channels = c.execute("SELECT * FROM mandatory_channels WHERE active=1 AND funding_type='internal'").fetchall()
        rows = []
        for ch2 in channels:
            with db_conn() as c:
                claimed = c.execute("SELECT 1 FROM channel_join_rewards WHERE user_id=? AND channel_id=?",
                                    (user.id, ch2['id'])).fetchone()
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
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
        await q.edit_message_text(
            f"📡 *قنوات الانضمام:*\n\n"
            f"🎁 انضم لأي قناة واحصل على *{reward} نقطة*\n"
            f"💰 رصيدك الآن: {db_user['points'] if db_user else 0} نقطة",
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
        owner_contact = get_setting("owner_contact") or ""
        kb_rows = []
        if owner_contact:
            kb_rows.append([InlineKeyboardButton("💬 تواصل مع المالك", url=owner_contact)])
        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="charge_points")])
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
            await q.edit_message_text(
                "⚠️ لا توجد باقات استبدال متاحة حالياً.\nتواصل مع المالك لإضافة باقات.",
                reply_markup=back_kb("exchange_points")
            )
            return
        rows = []
        for pkg in packages:
            stars = pkg["stars"]
            cost = stars * rate
            rows.append([InlineKeyboardButton(f"⭐ {stars} نجمة = {cost} نقطة", callback_data=f"exchange:pkg:{stars}")])
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
        context.user_data["exchange_stars"] = stars
        context.user_data["exchange_cost"]  = cost
        context.user_data["state"] = "confirm_exchange_stars"
        await q.edit_message_text(
            f"⭐ *تأكيد الاستبدال:*\n\n"
            f"⭐ عدد النجوم: {stars}\n"
            f"💰 التكلفة: {cost} نقطة\n"
            f"💎 رصيدك: {pts} نقطة\n\n"
            f"أرسل *نعم* للتأكيد أو *لا* للإلغاء",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "exchange:number":
        cost = int(get_setting("telegram_number_cost") or "5000")
        db_user = get_user(user.id)
        if db_user["points"] < cost:
            await q.edit_message_text(
                f"❌ نقاطك غير كافية! تحتاج {cost} نقطة ولديك {db_user['points']} نقطة.",
                reply_markup=back_kb("exchange_points")
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
        await q.edit_message_text(
            f"✅ *تمت العملية بنجاح!*\n\n"
            f"📱 طلب رقم تيلغرام مسجل\n"
            f"💰 التكلفة: {cost} نقطة\n\n"
            f"📌 *كود عمليتك: `{code}`*\nسيتواصل معك المالك قريباً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_kb()
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
        cost = get_setting("mandatory_channel_cost") or "200"
        context.user_data["fund_type"] = "mandatory"
        context.user_data["state"]     = "await_fund_channel"
        await q.edit_message_text(
            f"📢 *تمويل قناة إجباري سريع*\n\n"
            f"✅ ستُضاف قناتك كقناة اشتراك إجبارية في البوت\n"
            f"💰 التكلفة: {cost} نقطة\n\n"
            f"📎 أرسل *رابط* أو *يوزرنيم* قناتك (مثال: @channel):",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "fund:internal":
        cost = get_setting("internal_channel_cost") or "100"
        context.user_data["fund_type"] = "internal"
        context.user_data["state"]     = "await_fund_channel"
        await q.edit_message_text(
            f"🔄 *تمويل قناة داخلي بطيء*\n\n"
            f"✅ ستُضاف قناتك في قسم انضم بقنوات\n"
            f"👥 الأعضاء يجمعون نقاط وينضمون لقناتك\n"
            f"💰 التكلفة: {cost} نقطة\n\n"
            f"📎 أرسل *رابط* أو *يوزرنيم* قناتك (مثال: @channel):",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ── إعدادات المالك ──
    if data == "owner_settings" and is_own:
        await q.edit_message_text("⚙️ *إعدادات المالك:*", parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=owner_settings_kb())
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
            f"💰 السعر: {price} نقطة/1000 وحدة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
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
            [InlineKeyboardButton("🌐 الموقع ورقم الخدمة", callback_data=f"os_edit_field:{sid}:source")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="os:list_services")],
        ]
        await q.edit_message_text(
            f"✏️ *تعديل الخدمة:* {svc['name_ar']}\n\n"
            f"🌐 الموقع الحالي: {site_name} (رقم {svc['api_service_id']})\n"
            f"📉 الحد الأدنى: {svc['min_qty']}\n"
            f"📈 الحد الأعلى: {svc['max_qty']}\n"
            f"💰 السعر: {svc['price_per_point']} نقطة/1000\n\n"
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

    if data == "os:edit_number_cost" and is_own:
        context.user_data["state"] = "os_await_number_cost"
        cur = get_setting("telegram_number_cost") or "5000"
        await q.edit_message_text(f"📱 سعر رقم تيلغرام الحالي: {cur} نقطة\n\nأرسل القيمة الجديدة:")
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
        cur = get_setting("join_channel_reward") or "20"
        context.user_data["state"] = "os_await_join_reward"
        await q.edit_message_text(
            f"🎁 *نقاط الانضمام للقنوات الداخلية*\n\n"
            f"القيمة الحالية: {cur} نقطة\n\n"
            f"أرسل عدد النقاط التي يحصل عليها العضو عند الانضمام:",
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
def main():
    init_db()
    start_health_server()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE,
        handle_text
    ))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

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

    app.post_init = post_init
    logger.info("🤖 Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
