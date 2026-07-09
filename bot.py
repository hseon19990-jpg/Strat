#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت تيلغرام متكامل مع منصة SMMMAIN.COM
المتغيرات المطلوبة في Railway:
  BOT_TOKEN       - توكن البوت
  OWNER_ID        - ايدي المالك
  API_KEY         - مفتاح API لموقع SMMMAIN.COM
  ADMIN_GROUP_ID  - ايدي الكروب الذي تصله الطلبات
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
    LabeledPrice, PreCheckoutQuery
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
        pass  # إخفاء سجلات HTTP

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
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            full_name   TEXT,
            points      INTEGER DEFAULT 0,
            invited_by  INTEGER DEFAULT 0,
            total_orders INTEGER DEFAULT 0,
            joined_at   TEXT DEFAULT (date('now')),
            bot_user_num INTEGER
        );

        CREATE TABLE IF NOT EXISTS orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            service_id  INTEGER,
            link        TEXT,
            quantity    INTEGER,
            cost_points INTEGER DEFAULT 0,
            cost_stars  INTEGER DEFAULT 0,
            api_order_id TEXT DEFAULT '',
            status      TEXT DEFAULT 'pending',
            order_code  TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS services (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            category    TEXT,
            api_service_id INTEGER,
            name_ar     TEXT,
            description TEXT,
            min_qty     INTEGER,
            max_qty     INTEGER,
            price_per_point REAL,
            active      INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS settings (
            key         TEXT PRIMARY KEY,
            value       TEXT
        );

        CREATE TABLE IF NOT EXISTS daily_gifts (
            user_id     INTEGER PRIMARY KEY,
            last_claim  TEXT
        );

        CREATE TABLE IF NOT EXISTS channel_funding (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            channel_username TEXT,
            funding_type TEXT,
            cost_points INTEGER,
            active      INTEGER DEFAULT 1,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS star_transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            stars       INTEGER,
            points_given INTEGER,
            telegram_payment_id TEXT,
            status      TEXT DEFAULT 'completed',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS point_transfers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user   INTEGER,
            to_user     INTEGER,
            points      INTEGER,
            fee         INTEGER,
            created_at  TEXT DEFAULT (datetime('now'))
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
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_username TEXT,
            channel_title TEXT,
            owner_user_id INTEGER DEFAULT 0,
            funding_type TEXT DEFAULT 'mandatory',
            active      INTEGER DEFAULT 1
        );

        INSERT OR IGNORE INTO settings VALUES ('daily_gift_points','50');
        INSERT OR IGNORE INTO settings VALUES ('referral_points','30');
        INSERT OR IGNORE INTO settings VALUES ('star_to_points','250');
        INSERT OR IGNORE INTO settings VALUES ('stars_25_cost','2500');
        INSERT OR IGNORE INTO settings VALUES ('stars_15_cost','1500');
        INSERT OR IGNORE INTO settings VALUES ('stars_50_cost','5000');
        INSERT OR IGNORE INTO settings VALUES ('stars_100_cost','10000');
        INSERT OR IGNORE INTO settings VALUES ('telegram_number_cost','5000');
        INSERT OR IGNORE INTO settings VALUES ('transfer_fee_percent','1');
        INSERT OR IGNORE INTO settings VALUES ('mandatory_channel_cost','200');
        INSERT OR IGNORE INTO settings VALUES ('internal_channel_cost','100');
        INSERT OR IGNORE INTO settings VALUES ('welcome_message','أهلاً وسهلاً بك في البوت!');
        INSERT OR IGNORE INTO settings VALUES ('owner_contact','');
        INSERT OR IGNORE INTO settings VALUES ('total_bot_orders','0');
        INSERT OR IGNORE INTO settings VALUES ('total_bot_users','0');
        """)

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
            "INSERT INTO users (user_id, username, full_name, invited_by, bot_user_num) VALUES (?,?,?,?,?)",
            (user_id, username, full_name, invited_by, total)
        )
        # مكافأة من دعا
        if invited_by and invited_by != user_id:
            rp = int(get_setting("referral_points") or "30")
            c.execute("UPDATE users SET points=points+? WHERE user_id=?", (rp, invited_by))
        return dict(c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone())

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
    """كود الطلب: user_order_number - bot_user_number - total_bot_orders"""
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
def smm_request(action: str, **params) -> dict:
    payload = {"key": API_KEY, "action": action, **params}
    try:
        r = requests.post(API_URL, data=payload, timeout=15)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def smm_service_info(service_id: int) -> dict:
    res = smm_request("services")
    if isinstance(res, list):
        for s in res:
            if str(s.get("service")) == str(service_id):
                return s
    return {}

def smm_create_order(service_id: int, link: str, quantity: int) -> dict:
    return smm_request("add", service=service_id, link=link, quantity=quantity)

def smm_order_status(order_id: str) -> dict:
    return smm_request("status", order=order_id)

# ────────────────────────────────────────────────────────────
#  مساعدات رياضية
# ────────────────────────────────────────────────────────────
CATEGORY_MAP = {
    "followers":   "رشق متابعين",
    "views":       "رشق مشاهدات",
    "interactions":"رشق تفاعلات",
    "story_views": "رشق مشاهدات ستوري",
    "start_bot":   "بدء بوت",
    "boost":       "تعزيز قناة أو كروب",
    "post_stars":  "نجوم على بوست قناة",
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
        [InlineKeyboardButton("ℹ️ معلوماتي", callback_data="my_info")],
    ]
    if is_owner:
        rows.append([InlineKeyboardButton("⚙️ إعدادات المالك", callback_data="owner_settings")])
    return InlineKeyboardMarkup(rows)

def owner_settings_kb():
    rows = [
        [InlineKeyboardButton("➕ إضافة خدمة", callback_data="os:add_service"),
         InlineKeyboardButton("📋 قائمة الخدمات", callback_data="os:list_services")],
        [InlineKeyboardButton("🎁 تعديل الهدية اليومية", callback_data="os:edit_gift"),
         InlineKeyboardButton("🔗 تعديل نقاط الدعوة", callback_data="os:edit_referral")],
        [InlineKeyboardButton("⭐ سعر النجمة", callback_data="os:edit_star_rate"),
         InlineKeyboardButton("🏆 أسعار الجوائز", callback_data="os:edit_prizes")],
        [InlineKeyboardButton("📱 سعر رقم تيلغرام", callback_data="os:edit_number_cost"),
         InlineKeyboardButton("💌 رسالة الترحيب", callback_data="os:edit_welcome")],
        [InlineKeyboardButton("📡 إدارة قنوات الاشتراك", callback_data="os:manage_channels"),
         InlineKeyboardButton("❌ إلغاء صفقة", callback_data="os:cancel_order")],
        [InlineKeyboardButton("📊 إحصائيات", callback_data="os:stats"),
         InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"1 ⭐ = {rate} نقطة", callback_data="charge:info")],
        [InlineKeyboardButton("🔢 شحن عدد نقاط معين", callback_data="charge:by_points"),
         InlineKeyboardButton("⭐ شحن بعدد نجوم معين", callback_data="charge:by_stars")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="charge_points")],
    ])

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

def exchange_stars_kb():
    costs = {
        "15":  int(get_setting("stars_15_cost")  or "1500"),
        "25":  int(get_setting("stars_25_cost")  or "2500"),
        "50":  int(get_setting("stars_50_cost")  or "5000"),
        "100": int(get_setting("stars_100_cost") or "10000"),
    }
    rows = [
        [InlineKeyboardButton(f"15 ⭐ مقابل {costs['15']} نقطة",  callback_data="buy_stars:15")],
        [InlineKeyboardButton(f"25 ⭐ مقابل {costs['25']} نقطة",  callback_data="buy_stars:25")],
        [InlineKeyboardButton(f"50 ⭐ مقابل {costs['50']} نقطة",  callback_data="buy_stars:50")],
        [InlineKeyboardButton(f"100 ⭐ مقابل {costs['100']} نقطة", callback_data="buy_stars:100")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="exchange_points")],
    ]
    return InlineKeyboardMarkup(rows)

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
    get_or_create_user(user.id, user.username or "", user.full_name or "", invited_by)

    prob, ans = generate_math()
    context.user_data.clear()
    context.user_data["state"] = "verify_math"
    context.user_data["math_ans"] = ans

    await update.message.reply_text(
        f"👋 *أهلاً بك!*\n\n🔐 للدخول للبوت، أجب على هذه المسألة البسيطة:\n\n"
        f"❓  *{prob} = ؟*",
        parse_mode=ParseMode.MARKDOWN
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
            db_user = get_user(user.id)
            pts = db_user["points"] if db_user else 0
            welcome = get_setting("welcome_message") or "أهلاً بك!"
            await update.message.reply_text(
                f"✅ *إجابة صحيحة!*\n\n{welcome}\n\n💰 رصيدك: {pts} نقطة",
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

    # ── مسار خدمة SMM: إدخال رابط ──
    if state == "await_smm_link":
        context.user_data["smm_link"] = text
        svc_id = context.user_data.get("smm_svc_db_id")
        with db_conn() as c:
            svc = c.execute("SELECT * FROM services WHERE id=?", (svc_id,)).fetchone()
        if not svc:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("⚠️ خدمة غير موجودة.", reply_markup=main_menu_kb(is_own))
            return
        context.user_data["smm_svc"] = dict(svc)
        context.user_data["state"] = "await_smm_qty"
        await update.message.reply_text(
            f"🔢 أدخل الكمية المطلوبة:\n"
            f"الحد الأدنى: {svc['min_qty']} | الحد الأعلى: {svc['max_qty']}"
        )
        return

    if state == "await_smm_qty":
        try:
            qty = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        svc = context.user_data.get("smm_svc", {})
        if qty < svc.get("min_qty", 1) or qty > svc.get("max_qty", 1000000):
            await update.message.reply_text(
                f"⚠️ الكمية خارج النطاق المسموح.\nالحد الأدنى: {svc['min_qty']} | الحد الأعلى: {svc['max_qty']}"
            )
            return
        cost = int(qty * svc.get("price_per_point", 1))
        context.user_data["smm_qty"] = qty
        context.user_data["smm_cost"] = cost
        context.user_data["state"] = "confirm_smm"
        db_user = get_user(user.id)
        pts = db_user["points"] if db_user else 0
        await update.message.reply_text(
            f"📋 *تفاصيل الطلب:*\n\n"
            f"🔹 الخدمة: {svc['name_ar']}\n"
            f"🔗 الرابط: `{context.user_data.get('smm_link')}`\n"
            f"🔢 الكمية: {qty}\n"
            f"💰 التكلفة: {cost} نقطة\n"
            f"💎 رصيدك: {pts} نقطة\n\n"
            f"هل تؤكد الطلب؟ أرسل *نعم* أو *لا*",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if state == "confirm_smm":
        if text == "نعم":
            svc  = context.user_data.get("smm_svc", {})
            qty  = context.user_data.get("smm_qty", 0)
            cost = context.user_data.get("smm_cost", 0)
            link = context.user_data.get("smm_link", "")
            # خصم النقاط أولاً
            if not deduct_points(user.id, cost):
                await update.message.reply_text("❌ نقاطك غير كافية.")
                context.user_data["state"] = "main_menu"
                await update.message.reply_text("🏠 القائمة الرئيسية:", reply_markup=main_menu_kb(is_own))
                return
            # إرسال الطلب لـ API
            api_res = smm_create_order(svc["api_service_id"], link, qty)
            if "error" in api_res or not api_res.get("order"):
                # إعادة النقاط في حالة فشل API
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
            # لا نعيد نقاطاً لأنها لم تُخصم بعد
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
        context.user_data["charge_stars"]  = stars
        context.user_data["charge_pts"]    = stars * rate
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
        context.user_data["charge_stars"]  = stars
        context.user_data["charge_pts"]    = pts
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
        channel = text.lstrip("@")
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
        info = smm_service_info(api_id)
        if not info:
            await update.message.reply_text("⚠️ لم يتم العثور على الخدمة في الموقع. تأكد من الرقم.")
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
        info = context.user_data.get("new_svc_info", {})
        await update.message.reply_text(
            f"الحد الأدنى ({info.get('min',0)}) - الحد الأعلى ({info.get('max',0)})\n"
            f"أرسل: *حد_أدنى حد_أعلى سعر_نقطة* (مفصولة بمسافة)\n"
            f"مثال: 100 10000 0.5",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data["state"] = "os_await_svc_params"
        return

    if is_own and state == "os_await_svc_params":
        parts = text.split()
        if len(parts) != 3:
            await update.message.reply_text("⚠️ أرسل ثلاثة أرقام مفصولة بمسافة: حد_أدنى حد_أعلى سعر_نقطة")
            return
        try:
            mn, mx, price = int(parts[0]), int(parts[1]), float(parts[2])
        except ValueError:
            await update.message.reply_text("⚠️ تأكد من صحة الأرقام.")
            return
        cat = context.user_data.get("new_svc_cat", "followers")
        with db_conn() as c:
            c.execute(
                "INSERT INTO services (category,api_service_id,name_ar,min_qty,max_qty,price_per_point) VALUES (?,?,?,?,?,?)",
                (cat, context.user_data.get("new_svc_api_id"), context.user_data.get("new_svc_name"), mn, mx, price)
            )
        await update.message.reply_text(
            f"✅ تمت إضافة الخدمة '{context.user_data.get('new_svc_name')}' بنجاح!",
            reply_markup=owner_settings_kb()
        )
        context.user_data["state"] = "main_menu"
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
        await update.message.reply_text(f"✅ سعر النجمة = {val} نقطة.", reply_markup=owner_settings_kb())
        context.user_data["state"] = "main_menu"
        return

    if is_own and state == "os_await_prizes":
        lines = text.strip().splitlines()
        for line in lines:
            parts = line.split(":")
            if len(parts) == 2:
                set_setting(parts[0].strip(), parts[1].strip())
        await update.message.reply_text("✅ تم تحديث أسعار الجوائز.", reply_markup=owner_settings_kb())
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
            f"💰 التكلفة: {order['cost_points']} نقطة\n"
            f"⭐ النجوم: {order['cost_stars']}\n\n"
            f"أرسل *نعم* للإلغاء وإعادة الرصيد أو *لا* للتراجع",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if is_own and state == "confirm_cancel_order":
        if text == "نعم":
            order  = context.user_data.get("cancel_order", {})
            uid    = order.get("user_id")
            pts    = order.get("cost_points", 0)
            stars  = order.get("cost_stars", 0)
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

    # إذا لا يوجد حالة معروفة، عرض القائمة
    await update.message.reply_text("🏠 القائمة الرئيسية:", reply_markup=main_menu_kb(is_own))

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
        # مسح الحالة عند الرجوع للقائمة الرئيسية لتجنب تعليق المستخدم في حالة قديمة
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
        context.user_data["smm_svc_db_id"] = svc_id
        context.user_data["state"] = "await_smm_link"
        await q.edit_message_text(
            f"🔹 *{svc['name_ar']}*\n\n"
            f"📝 {svc['description'] or 'خدمة متميزة'}\n"
            f"📉 الحد الأدنى: {svc['min_qty']}\n"
            f"📈 الحد الأعلى: {svc['max_qty']}\n"
            f"💰 السعر: {svc['price_per_point']} نقطة / وحدة\n\n"
            f"📎 أرسل *رابط* الحساب/القناة/البوست:",
            parse_mode=ParseMode.MARKDOWN
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
            channels = c.execute("SELECT * FROM mandatory_channels WHERE active=1").fetchall()
        if not channels:
            await q.edit_message_text("📡 لا توجد قنوات للاشتراك حالياً.", reply_markup=back_kb())
            return
        rows = []
        for ch in channels:
            rows.append([InlineKeyboardButton(
                f"📢 {ch['channel_username']}",
                url=f"https://t.me/{ch['channel_username']}"
            )])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
        await q.edit_message_text(
            "📡 *قنوات الاشتراك:*\nانضم للقنوات التالية:",
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
            f"⭐ *الشحن عبر النجوم*\n\n💡 سعر النجمة الواحدة = {rate} نقطة\n\nاختر طريقة الشحن:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=charge_stars_kb()
        )
        return

    if data == "charge:info":
        await q.answer("هذا مجرد عرض للسعر.", show_alert=False)
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
        owner_contact = get_setting("owner_contact") or ""
        txt = "⚠️ الشحن التلقائي عبر اسيا سيل غير متاح حالياً.\nيرجى التواصل مع المالك."
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 تواصل مع المالك", url=owner_contact)] if owner_contact else [],
            [InlineKeyboardButton("🔙 رجوع", callback_data="charge_points")],
        ])
        await q.edit_message_text(txt, reply_markup=kb)
        return

    # ── استبدال نقاط ──
    if data == "exchange_points":
        await q.edit_message_text("🏆 *استبدال النقاط بجوائز:*",
                                   parse_mode=ParseMode.MARKDOWN, reply_markup=exchange_kb())
        return

    if data == "exchange:stars":
        await q.edit_message_text("⭐ *استبدال نقاط بنجوم:*\nاختر الكمية:",
                                   parse_mode=ParseMode.MARKDOWN, reply_markup=exchange_stars_kb())
        return

    if data.startswith("buy_stars:"):
        stars_count = int(data.split(":")[1])
        key  = f"stars_{stars_count}_cost"
        cost = int(get_setting(key) or "0")
        if cost == 0:
            await q.edit_message_text("⚠️ السعر غير محدد من المالك.", reply_markup=back_kb("exchange_points"))
            return
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
                (user.id, "stars", str(stars_count), cost)
            )
        await q.edit_message_text(
            f"✅ *تمت العملية بنجاح!*\n\n"
            f"⭐ طلب {stars_count} نجمة مسجل\n"
            f"💰 التكلفة: {cost} نقطة\n\n"
            f"📌 *كود عمليتك: `{code}`*\nاحفظه قد تحتاجه لاحقاً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_kb()
        )
        await notify_group(
            context.application,
            f"⭐ <b>طلب شراء نجوم</b>\n"
            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
            f"⭐ {stars_count} نجمة مقابل {cost} نقطة\n"
            f"📌 {code}"
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
        context.user_data["state"] = "os_await_api_id"
        await q.edit_message_text(
            f"📌 الفئة: {CATEGORY_MAP.get(cat, cat)}\n\nأرسل *رقم الخدمة* في موقع SMMMAIN:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "os:list_services" and is_own:
        with db_conn() as c:
            svcs = c.execute("SELECT * FROM services ORDER BY category, id").fetchall()
        if not svcs:
            await q.edit_message_text("📋 لا توجد خدمات مضافة.", reply_markup=owner_settings_kb())
            return
        lines = ["📋 *قائمة الخدمات:*\n"]
        for s in svcs:
            status = "✅" if s["active"] else "❌"
            lines.append(f"{status} [{s['id']}] *{s['name_ar']}*\nالفئة: {CATEGORY_MAP.get(s['category'], s['category'])} | Min:{s['min_qty']} Max:{s['max_qty']}\n")
        rows = []
        for s in svcs:
            tog = "❌ تعطيل" if s["active"] else "✅ تفعيل"
            rows.append([
                InlineKeyboardButton(f"{s['name_ar'][:20]}", callback_data="noop"),
                InlineKeyboardButton(tog, callback_data=f"os_tog_svc:{s['id']}:{1 if not s['active'] else 0}"),
                InlineKeyboardButton("🗑", callback_data=f"os_del_svc:{s['id']}")
            ])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("os_tog_svc:") and is_own:
        _, sid, val = data.split(":")
        with db_conn() as c:
            c.execute("UPDATE services SET active=? WHERE id=?", (int(val), int(sid)))
            svcs = c.execute("SELECT * FROM services ORDER BY category, id").fetchall()
        await q.answer("✅ تم التحديث")
        # إعادة بناء القائمة مباشرة بدون استدعاء handle_callback تجنباً للتكرار
        if not svcs:
            await q.edit_message_text("📋 لا توجد خدمات مضافة.", reply_markup=owner_settings_kb())
            return
        lines = ["📋 *قائمة الخدمات:*\n"]
        for s in svcs:
            status = "✅" if s["active"] else "❌"
            lines.append(f"{status} [{s['id']}] *{s['name_ar']}*\nالفئة: {CATEGORY_MAP.get(s['category'], s['category'])} | Min:{s['min_qty']} Max:{s['max_qty']}\n")
        rows = []
        for s in svcs:
            tog = "❌ تعطيل" if s["active"] else "✅ تفعيل"
            rows.append([
                InlineKeyboardButton(f"{s['name_ar'][:20]}", callback_data="noop"),
                InlineKeyboardButton(tog, callback_data=f"os_tog_svc:{s['id']}:{1 if not s['active'] else 0}"),
                InlineKeyboardButton("🗑", callback_data=f"os_del_svc:{s['id']}")
            ])
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("os_del_svc:") and is_own:
        sid = int(data.split(":")[1])
        with db_conn() as c:
            c.execute("DELETE FROM services WHERE id=?", (sid,))
        await q.answer("🗑 تم الحذف")
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
        await q.edit_message_text(f"⭐ سعر النجمة الحالي: {cur} نقطة\n\nأرسل القيمة الجديدة:")
        return

    if data == "os:edit_prizes" and is_own:
        context.user_data["state"] = "os_await_prizes"
        c15  = get_setting("stars_15_cost")
        c25  = get_setting("stars_25_cost")
        c50  = get_setting("stars_50_cost")
        c100 = get_setting("stars_100_cost")
        await q.edit_message_text(
            f"🏆 *تعديل أسعار الجوائز:*\n\n"
            f"الأسعار الحالية:\n"
            f"15 نجمة = {c15} نقطة\n"
            f"25 نجمة = {c25} نقطة\n"
            f"50 نجمة = {c50} نقطة\n"
            f"100 نجمة = {c100} نقطة\n\n"
            f"أرسل على الشكل (سطر لكل قيمة):\n"
            f"`stars_15_cost:1500`\n"
            f"`stars_25_cost:2500`\n"
            f"`stars_50_cost:5000`\n"
            f"`stars_100_cost:10000`",
            parse_mode=ParseMode.MARKDOWN
        )
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

    if data == "os:stats" and is_own:
        with db_conn() as c:
            total_users  = c.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
            total_orders = c.execute("SELECT COUNT(*) as cnt FROM orders").fetchone()["cnt"]
            total_pts    = c.execute("SELECT SUM(points) as s FROM users").fetchone()["s"] or 0
        await q.edit_message_text(
            f"📊 *إحصائيات البوت:*\n\n"
            f"👥 إجمالي المستخدمين: {total_users}\n"
            f"📦 إجمالي الطلبات: {total_orders}\n"
            f"💰 إجمالي النقاط في البوت: {total_pts}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
        return

    if data == "noop":
        return

# ────────────────────────────────────────────────────────────
#  Telegram Stars — Pre-Checkout
# ────────────────────────────────────────────────────────────
async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    payload = query.invoice_payload

    # التحقق من صحة الـ payload وتطابق المستخدم
    valid = False
    if payload.startswith("charge_stars:"):
        parts = payload.split(":")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            expected_stars = int(parts[1])
            uid_in_payload = int(parts[2])
            # تأكد أن المستخدم هو نفسه الذي طلب الفاتورة وأن المبلغ متطابق
            if uid_in_payload == query.from_user.id and query.total_amount == expected_stars:
                valid = True

    if valid:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="حدث خطأ في التحقق من الدفع. يرجى المحاولة مجدداً.")

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    paid_stars = payment.total_amount   # المبلغ الفعلي الذي دفعه المستخدم

    if payload.startswith("charge_stars:"):
        parts = payload.split(":")
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            logger.error(f"Invalid payment payload: {payload}")
            return
        expected_stars = int(parts[1])
        uid_in_payload = int(parts[2])

        # تحقق مزدوج: المستخدم متطابق والمبلغ متطابق
        if uid_in_payload != user.id or paid_stars != expected_stars:
            logger.warning(
                f"Payment mismatch! user={user.id} payload_uid={uid_in_payload} "
                f"paid={paid_stars} expected={expected_stars}"
            )
            await update.message.reply_text("⚠️ خطأ في التحقق من الدفع. تواصل مع المالك.")
            return

        rate  = int(get_setting("star_to_points") or "250")
        pts   = paid_stars * rate          # نستخدم paid_stars الفعلية وليس الـ payload
        add_points(user.id, pts)
        code = next_order_code(user.id)
        with db_conn() as c:
            c.execute(
                "INSERT INTO star_transactions (user_id,stars,points_given,telegram_payment_id) VALUES (?,?,?,?)",
                (user.id, paid_stars, pts, payment.telegram_payment_charge_id)
            )
        db_user = get_user(user.id)
        await update.message.reply_text(
            f"✅ *تمت عملية الشحن بنجاح!*\n\n"
            f"⭐ النجوم المدفوعة: {paid_stars}\n"
            f"💰 النقاط المضافة: {pts}\n"
            f"💎 رصيدك الآن: {db_user['points']} نقطة\n\n"
            f"📌 *كود عمليتك هو: `{code}`*\nاحفظه قد تحتاجه لاحقاً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(user.id == OWNER_ID)
        )
        await notify_group(
            context.application,
            f"⭐ <b>شحن نجوم ناجح</b>\n"
            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
            f"⭐ {paid_stars} نجمة → {pts} نقطة\n"
            f"📌 {code}"
        )

# ────────────────────────────────────────────────────────────
#  /broadcast (للمالك)
# ────────────────────────────────────────────────────────────
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("⚠️ أرسل الرسالة بعد الأمر: /broadcast رسالتك")
        return
    with db_conn() as c:
        users = c.execute("SELECT user_id FROM users").fetchall()
    success, fail = 0, 0
    for u in users:
        try:
            await context.bot.send_message(u["user_id"], msg)
            success += 1
        except Exception:
            fail += 1
    await update.message.reply_text(f"✅ أُرسلت إلى {success} مستخدم، فشل: {fail}")

# ────────────────────────────────────────────────────────────
#  /addpoints (للمالك)
# ────────────────────────────────────────────────────────────
async def cmd_addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("⚠️ الاستخدام: /addpoints <user_id> <points>")
        return
    try:
        uid, pts = int(args[0]), int(args[1])
    except ValueError:
        await update.message.reply_text("⚠️ أرسل أرقاماً صحيحة.")
        return
    add_points(uid, pts)
    await update.message.reply_text(f"✅ تمت إضافة {pts} نقطة للمستخدم {uid}.")
    try:
        await context.bot.send_message(uid, f"🎉 أضاف لك المالك {pts} نقطة!")
    except Exception:
        pass

# ────────────────────────────────────────────────────────────
#  /status (للمالك — فحص حالة طلب API)
# ────────────────────────────────────────────────────────────
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("⚠️ الاستخدام: /status <order_code>")
        return
    code = context.args[0]
    with db_conn() as c:
        order = c.execute("SELECT * FROM orders WHERE order_code=?", (code,)).fetchone()
    if not order:
        await update.message.reply_text("⚠️ كود الطلب غير موجود.")
        return
    api_status = {}
    if order["api_order_id"]:
        api_status = smm_order_status(order["api_order_id"])
    await update.message.reply_text(
        f"📊 *حالة الطلب:*\n\n"
        f"📌 الكود: {code}\n"
        f"👤 المستخدم: {order['user_id']}\n"
        f"🔗 الرابط: {order['link']}\n"
        f"🔢 الكمية: {order['quantity']}\n"
        f"💰 التكلفة: {order['cost_points']} نقطة\n"
        f"🔖 الحالة: {order['status']}\n"
        f"📡 حالة API: {api_status.get('status', 'N/A')}\n"
        f"📅 التاريخ: {order['created_at']}",
        parse_mode=ParseMode.MARKDOWN
    )

# ────────────────────────────────────────────────────────────
#  تشغيل البوت
# ────────────────────────────────────────────────────────────
def main():
    init_db()
    start_health_server()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("broadcast",  cmd_broadcast))
    app.add_handler(CommandHandler("addpoints",  cmd_addpoints))
    app.add_handler(CommandHandler("status",     cmd_status))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("✅ البوت يعمل...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
