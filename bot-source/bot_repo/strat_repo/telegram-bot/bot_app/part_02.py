
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

# ────────────────────────────────────────────────────────────
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
# ────────────────────────────────────────────────────────────
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
         ("💌 شكر المالك", "thank_owner", 2),
        ("🏆 مسابقة الدعوة", "referral_contest_view", 2),
        ("📧 احصل على نقاط مقابل إيميل جيميل", "gmail_points", 1),
        ("🔑 إحالة بوت اجباري", "forced_ref", 2),
    ],
    "services_menu": [(label, value, 2) for label, value in SERVICE_PLATFORMS],
    "services_menu_tg": [
        ("👥 رشق متابعين", "cat:followers", 2), ("👁 رشق مشاهدات", "cat:views", 2),
        ("💬 رشق تفاعلات", "cat:interactions", 2), ("📖 رشق مشاهدات ستوري", "cat:story_views", 2),
        ("🤖 رشق بدء (ستارت) بوت", "cat:start_bot", 2), ("📣 تعزيز قناة أو كروب", "cat:boost", 2),
        ("⭐ نجوم على بوست قناة", "cat:post_stars", 1),
        ("🔧 خدمات أخرى", "cat:other", 1),
    ],
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
        ("📧 إيميلات جيميل", "os:list_gmail", 2), ("⚙️ نقاط طلب جيميل", "os:edit_gmail_reward", 2),
        ("✏️ نص رسالة الجيميل", "os:edit_gmail_msg", 2),
        ("🏷 اسم زر الإيميل", "os:edit_gmail_btn_label", 2),
        ("📨 رسالة طلب الإيميل", "os:edit_gmail_email_prompt", 2), ("🔑 رسالة طلب الباسورد", "os:edit_gmail_pass_prompt", 2),
        ("💰 إجباري-نقاط: سعر/عضو", "os:edit_mpoints_price", 2), ("💰 إجباري-نقاط: حد أدنى", "os:edit_mpoints_min", 2),
        ("📡 إدارة قنوات الاشتراك", "os:manage_channels", 2), ("👥 حد أدنى تمويل داخلي", "os:edit_internal_min", 2),
        ("❌ إلغاء صفقة", "os:cancel_order", 2),
        ("✅ إكمال طلب", "os:complete_order", 2),
        ("🎟 إنشاء كود ترويجي", "os:create_promo", 2), ("📋 أكواد ترويجية", "os:list_promos", 2),
        ("🚫 إدارة الحظر", "os:ban_menu", 2),
        ("🔍 من استخدم الكود", "os:search_code", 2),
        ("💰 منح/خصم نقاط", "os:manage_points", 2),
        ("💬 رابط تواصل المالك", "os:edit_contact", 2), ("✏️ نص زر التواصل", "os:edit_contact_label", 2),
         ("💌 إعدادات شكر المالك", "os:thank_owner_settings", 1),
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
    with db_conn() as c:
        c.execute(
            "DELETE FROM menu_items WHERE menu='main' AND action_value IN ('daily_gift','join_channels')"
        )
    if menu == "main":
        with db_conn() as c:
            old_cats = tuple(f"cat:{k}" for k in SERVICES_MENU_CATEGORIES)
            c.execute(
                f"DELETE FROM menu_items WHERE menu='main' AND action_type='builtin' AND action_value IN "
                f"({','.join('?' for _ in old_cats)})",
                old_cats
            )
        with db_conn() as c:
            row = c.execute(
                "SELECT MIN(sort_order) AS m FROM menu_items WHERE menu='main'"
            ).fetchone()
            min_order = row["m"] if row and row["m"] is not None else 0
            c.execute(
                "UPDATE menu_items SET sort_order=? WHERE menu='main' AND action_value='services_menu'",
                (min_order - 1,)
            )
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
    if menu == "services_menu":
        with db_conn() as c:
            old_cats = tuple(f"cat:{k}" for k in SERVICES_MENU_CATEGORIES)
            c.execute(
                f"DELETE FROM menu_items WHERE menu='services_menu' AND action_type='builtin' AND action_value IN "
                f"({','.join('?' for _ in old_cats)})",
                old_cats
            )
    with db_conn() as c:
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
        if it["action_value"] == "thank_owner":
            label = get_setting("thank_owner_button_label") or label
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
    _maint_on = is_maintenance_on()
    _maint_suffix = " (مفعل ✅)" if _maint_on else " (مغلق ❌)"
    _numex_on = is_number_exchange_on()
    _numex_suffix = " (مفعل ✅)" if _numex_on else " (مغلق ❌)"
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
    rows.append([InlineKeyboardButton("👤 تفاصيل الحسابات", callback_data="account_details:menu")])
    rows.append([InlineKeyboardButton("🧩 إضافة/إزالة خيار", callback_data="mb_menu:owner_settings")])
    rows.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def thank_owner_settings_kb():
    rows = []
    for key, (title, default) in THANK_OWNER_SETTINGS.items():
        current = get_setting(key) or default
        label = title if len(current) <= 24 else f"{title[:18]}…"
        rows.append([InlineKeyboardButton(label, callback_data=f"os:thank_owner_edit:{key}")])
    rows.append([InlineKeyboardButton("🔙 إعدادات المالك", callback_data="owner_settings")])
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
# ────────────────────────────────────────────────────────────
async def notify_group(app, text: str, reply_markup=None):
    if ADMIN_GROUP_ID:
        try:
            await app.bot.send_message(ADMIN_GROUP_ID, text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        except Exception as e:
            logger.warning(f"notify_group error: {e}")


async def _maybe_send_to_group(bot, requester_id: int, text: str, parse_mode: str = 'Markdown'):
    """
    إذا كان مُرسِل الطلب هو المالك → يسأله أولاً قبل الإرسال لكروب الطلبات.
    إذا كان عضواً عادياً → يُرسل مباشرة لكروب الطلبات كالمعتاد.
    """
    if not ADMIN_GROUP_ID:
        return
    if requester_id != OWNER_ID:
        # عضو عادي → أرسل مباشرة
        try:
            await bot.send_message(ADMIN_GROUP_ID, text, parse_mode=parse_mode)
        except Exception:
            pass
        return
    # المالك → اسأله أولاً قبل الإرسال
    import uuid as _uuid
    key = _uuid.uuid4().hex[:10]
    _pending_group_msgs[key] = {"text": text, "parse_mode": parse_mode}
    preview = text[:500] + ("…" if len(text) > 500 else "")
    try:
        await bot.send_message(
            OWNER_ID,
            f"📤 *هل تريد إرسال هذا الطلب لكروب الطلبات أيضاً؟*\n\n{preview}",
            parse_mode=parse_mode,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ إرسال للكروب", callback_data=f"owner_fwd:yes:{key}"),
                InlineKeyboardButton("❌ لا تُرسل",    callback_data=f"owner_fwd:no:{key}"),
            ]])
        )
    except Exception as _e:
        logger.warning(f"_maybe_send_to_group prompt error: {_e}")

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

async def notify_prize_exchange_owner(context, pe_id: int, text_html: str, group_text_html: str | None = None):
    """يرسل إشعار طلب الاستبدال إلى كروب الإدارة (إن كان مُعرّفاً) كنص فقط بدون
    أزرار/علامة الحالة، وإلى خاص المالك (البوت) مع أزرار مكتمل/غير مكتمل —
    التحكم بالحالة يبقى حصراً داخل البوت.
    إن أُعطي group_text_html يُرسَل للكروب بديلاً عن text_html (مثلاً: بدون رقم الهاتف)."""
    badge = _unseen_badge_html(exclude_pe_id=pe_id)
    full_text = badge + text_html
    group_full_text = badge + (group_text_html if group_text_html is not None else text_html)
    kb = prize_exchange_admin_kb(pe_id)
    await notify_group(context.application, group_full_text)
    if OWNER_ID:
        try:
            await context.bot.send_message(OWNER_ID, full_text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception as e:
            logger.warning(f"notify_prize_exchange_owner error: {e}")

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
async def show_category_services(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str):
    platform = context.user_data.get("current_platform", "tg") if context else "tg"
    back_map = {"tg": "services_menu_tg", "ig": "services_menu_ig", "tt": "services_menu_tt",
                "wa": "services_menu_wa", "fb": "services_menu_fb", "yt": "services_menu_yt",
                "sc": "services_menu_sc", "tw": "services_menu_tw"}
    back_target = back_map.get(platform, "services_menu_tg") if category in SERVICES_MENU_CATEGORIES else "main_menu"
    _vu = update.effective_user
    _is_own_v = _vu and _vu.id == OWNER_ID
    _ms_vis = get_setting('mansub_visible') == '1'
    with db_conn() as c:
        svcs = c.execute(
            "SELECT * FROM services WHERE category=%s AND platform=%s AND active=1", (category, platform)
        ).fetchall()
    if not svcs and platform != 'tg':
        with db_conn() as c:
            svcs = c.execute(
                "SELECT * FROM services WHERE category=%s AND (platform=%s OR platform IS NULL) AND active=1",
                (category, platform)
            ).fetchall()
    if _is_own_v and category == 'start_bot' and platform == 'tg':
        with db_conn() as c:
            _ms = c.execute("SELECT * FROM services WHERE service_type='mandatory_sub' LIMIT 1").fetchone()
        if _ms and not any(x['id'] == _ms['id'] for x in (svcs or [])):
            svcs = list(svcs or []) + [_ms]
    if not _is_own_v and svcs:
        svcs = [x for x in svcs if x.get('service_type') != 'mandatory_sub' or _ms_vis]
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
        ico = '🔑' if s.get('service_type') == 'mandatory_sub' else ('⭐' if s['category'] == 'post_stars' else '🔹')
        rows.append([InlineKeyboardButton(f"{ico} {s['name_ar']}", callback_data=f"svc:{s['id']}" )])
    extra_items = get_menu_items(f"cat:{category}")
    rows.extend(build_kb_rows(extra_items))
    if _is_own_v:
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
        if f["funding_type"] == "internal":
            with db_conn() as c:
                verified = c.execute(
                    "SELECT 1 FROM channel_join_rewards WHERE user_id=%s AND channel_id=%s",
                    (user_id, f["mc_id"])
                ).fetchone()
            if not verified:
                continue
        else:
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
# ────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    invited_by = int(args[0]) if args and args[0].isdigit() else 0

    db_user = get_or_create_user(user.id, user.username or "", user.full_name or "", invited_by)
    is_own = (user.id == OWNER_ID)

    if is_maintenance_on() and not is_own:
        await update.message.reply_text(MAINTENANCE_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return

    if db_user.get("verified", 0):
        unjoined = await get_unjoined_mandatory_channels(context, user.id)
        if unjoined:
            context.user_data["state"] = "await_mandatory_join"
            await show_mandatory_gate(update, context, unjoined, edit=False, is_owner=is_own)
            return
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

    await update.message.reply_text(
        "👋 *أهلاً بك!*", parse_mode=ParseMode.MARKDOWN
    )
    await start_onboarding(update, context)

# ────────────────────────────────────────────────────────────
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

async def cmd_mass_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /mass_reset
    يقرأ ملفات الجلسة لكل الحسابات غير المباعة ويطرد جميع الجلسات الأخرى.
    الحسابات المباعة (ever_sold=TRUE) تُتخطى تماماً — خارج نطاق البوت.
    """
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        await update.message.reply_text("❌ متغيرات API_ID / API_HASH غير مضبوطة.")
        return

    # ─── جلب كل الحسابات غير المباعة التي لديها ملف جلسة ──────────────────
    with db_conn() as _c:
        rows = _c.execute(
            "SELECT id, phone_number, session_string FROM number_stock "
            "WHERE ever_sold IS NOT TRUE "
            "  AND session_string IS NOT NULL"
        ).fetchall()

    total = len(rows)
    if total == 0:
        await update.message.reply_text("ℹ️ لا يوجد حسابات غير مباعة لديها ملف جلسة.")
        return

    status_msg = await update.message.reply_text(
        f"⏳ بدأ إعادة قراءة الملفات وطرد الجلسات...\n"
        f"📦 إجمالي الحسابات: *{total}*\n"
        f"⏱️ الرجاء الانتظار...",
        parse_mode=ParseMode.MARKDOWN
    )

    done, kicked_ok, already_solo, failed, kicked_out = 0, 0, 0, 0, 0

    for rec in rows:
        rec = dict(rec)
        phone = rec["phone_number"]
        _client = None
        try:
            _client = TelegramClient(
                StringSession(rec["session_string"]),
                int(TELEGRAM_API_ID), TELEGRAM_API_HASH
            )
            await _client.connect()

            if not await _client.is_user_authorized():
                kicked_out += 1
                with db_conn() as _cx:
                    _es2 = _cx.execute(
                        "SELECT ever_sold FROM number_stock WHERE id=%s", (rec["id"],)
                    ).fetchone()
                    if _es2 and not _es2["ever_sold"]:
                        _cx.execute("DELETE FROM number_stock WHERE id=%s", (rec["id"],))
                        logger.info(
                            f"🗑️ حذف تلقائي (mass_reset): الرقم {phone} — جلسة منتهية."
                        )
                    else:
                        _cx.execute(
                            "UPDATE number_stock SET last_authorized=FALSE WHERE id=%s",
                            (rec["id"],)
                        )
                continue

            # ── طرد كل الجلسات الأخرى ─────────────────────────────────
            try:
                await _client(ResetAuthorizationsRequest())
                kicked_ok += 1
            except Exception as _re:
                logger.debug(f"mass_reset: ResetAuth فشل للرقم {phone}: {_re}")
                failed += 1

            # ── فحص ما إذا كان البوت الجلسة الوحيدة ─────────────────────
            _dev = -1
            try:
                _dev = await get_device_count(_client)
            except Exception:
                pass
            _is_solo_r = (_dev == 1)
            if _is_solo_r:
                already_solo += 1

            # ── تسجيل IP الجلسة الجديدة بعد الطرد ────────────────────────
            _new_ip = None
            try:
                _new_ip = await get_session_ip(_client)
            except Exception:
                pass

            with db_conn() as _cx:
                _cx.execute(
                    "UPDATE number_stock SET sessions_reset=TRUE, is_solo=%s, "
                    "last_authorized=TRUE, bot_session_ip=%s WHERE id=%s",
                    (_is_solo_r, _new_ip, rec["id"])
                )

            # ── تفعيل can_send_code إذا أصبح منفرداً ─────────────────────
            if _is_solo_r:
                asyncio.create_task(
                    _test_and_set_can_send_code(phone, rec["session_string"], rec["id"])
                )

        except Exception as _e:
            logger.warning(f"mass_reset: خطأ على الرقم {phone}: {_e}")
            failed += 1
        finally:
            if _client:
                try:
                    await _client.disconnect()
                except Exception:
                    pass
            done += 1

            # ── تحديث رسالة التقدم كل 5 حسابات ──────────────────────────
            if done % 5 == 0 or done == total:
                try:
                    await status_msg.edit_text(
                        f"⏳ جاري المعالجة... {done}/{total}\n\n"
                        f"✅ طُردت جلساته: *{kicked_ok}*\n"
                        f"🔒 كان منفرداً أصلاً: *{already_solo}*\n"
                        f"⛔ جلسة منتهية: *{kicked_out}*\n"
                        f"❌ فشل: *{failed}*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass

    # ─── رسالة النتيجة النهائية ──────────────────────────────────────────
    await status_msg.edit_text(
        f"✅ *اكتملت عملية إعادة القراءة والطرد الجماعي*\n\n"
        f"📦 إجمالي الحسابات المعالجة: *{total}*\n"
        f"🔐 نجح الطرد (ResetAuthorizations): *{kicked_ok}*\n"
        f"🔒 كان منفرداً مسبقاً (solo): *{already_solo}*\n"
        f"⛔ جلسة منتهية الصلاحية: *{kicked_out}*\n"
        f"❌ فشل الاتصال أو الطرد: *{failed}*\n\n"
        f"🚫 الحسابات المباعة: *لم تُمسّ* (خارج النطاق)",
        parse_mode=ParseMode.MARKDOWN
    )
    logger.info(
        f"mass_reset مكتمل | total={total} kicked={kicked_ok} "
        f"solo={already_solo} expired={kicked_out} failed={failed}"
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

    with db_conn() as c:
        c.execute("UPDATE users SET points=points+%s WHERE user_id=%s", (rp, invited_by))
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

    try:
        await context.bot.send_message(
            chat_id=invited_by,
            text=f"🎉 تم تصحيح إحالة ضائعة! حصلت على {rp} نقطة بسبب دعوة المستخدم {invited_name}."
        )
    except Exception:
        pass

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    text   = (update.message.text or update.message.caption or "").strip()
    state  = context.user_data.get("state", "")
    is_own = (user.id == OWNER_ID)

    if not is_own and is_user_banned(user.id):
        await update.message.reply_text("🚫 تم حظرك من استخدام هذا البوت.")
        return

    if is_maintenance_on() and not is_own:
        await update.message.reply_text(MAINTENANCE_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return

    if await account_details_text(update, context):
        return

    _owner_admin_state = is_own and (
        state.startswith("os_") or state.startswith("await_mb_")
        or state in ("confirm_cancel_order", "confirm_complete_order")
    )
    _thank_owner_state = state in {"thank_owner_menu", "thank_owner_ar", "thank_owner_en", "thank_owner_photo"}
    if state != "verify_math" and not _thank_owner_state and not _owner_admin_state:
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

    if state in ("thank_owner_ar", "thank_owner_en") and not is_own:
        if not text:
            await update.message.reply_text("⚠️ أرسل رسالة نصية.")
            return
        language = "العربية" if state == "thank_owner_ar" else "الإنجليزية"
        sender = f"{user.full_name or 'مستخدم'}"
        if user.username:
            sender += f" (@{user.username})"
        owner_text = (
            f"💌 رسالة شكر جديدة ({language})\n\n"
            f"👤 المرسل: {sender}\n"
            f"🆔 ID: {user.id}\n\n"
            f"{text}"
        )
        try:
            await context.bot.send_message(chat_id=OWNER_ID, text=owner_text[:4096])
            await update.message.reply_text(
                get_setting("thank_owner_success_message")
                or "✅ تم إرسال شكرك إلى المالك، شكراً لك!",
                reply_markup=main_menu_kb(False)
            )
        except Exception:
            logger.exception("فشل إرسال رسالة شكر إلى المالك")
            await update.message.reply_text(
                "⚠️ تعذر إرسال الرسالة حالياً، حاول مرة أخرى لاحقاً.",
                reply_markup=main_menu_kb(False)
            )
        context.user_data["state"] = "main_menu"
        return

    if state == "os_await_thank_owner_setting" and is_own:
        key = context.user_data.get("thank_owner_setting_key")
        if key not in THANK_OWNER_SETTINGS:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("⚠️ انتهت جلسة الإعداد، افتحها من جديد.", reply_markup=owner_settings_kb())
            return
        if not text:
            await update.message.reply_text("⚠️ النص لا يمكن أن يكون فارغاً.")
            return
        set_setting(key, text)
        context.user_data["state"] = "main_menu"
        context.user_data.pop("thank_owner_setting_key", None)
        await update.message.reply_text(
            f"✅ تم تحديث: {THANK_OWNER_SETTINGS[key][0]}",
            reply_markup=thank_owner_settings_kb()
        )
        return

    if state == "thank_owner_photo" and not is_own and update.message.photo:
        sender = f"{user.full_name or 'مستخدم'}"
        if user.username:
            sender += f" (@{user.username})"
        caption = (
            f"💌 صورة شكر جديدة\n\n"
            f"👤 المرسل: {sender}\n"
            f"🆔 ID: {user.id}"
        )
        if update.message.caption:
            caption += f"\n\n💬 تعليق المرسل:\n{update.message.caption}"
        try:
            await context.bot.send_photo(
                chat_id=OWNER_ID,
                photo=update.message.photo[-1].file_id,
                caption=caption[:1024]
            )
            await update.message.reply_text(
                get_setting("thank_owner_success_message")
                or "✅ تم إرسال شكرك إلى المالك، شكراً لك!",
                reply_markup=main_menu_kb(False)
            )
        except Exception:
            logger.exception("فشل إرسال صورة شكر إلى المالك")
            await update.message.reply_text(
                "⚠️ تعذر إرسال الصورة حالياً، حاول مرة أخرى لاحقاً.",
                reply_markup=main_menu_kb(False)
            )
        context.user_data["state"] = "main_menu"
        return

    if state == "os_import_hex" and is_own:
        context.user_data["state"] = ""
        raw_lines = [l.strip() for l in text.splitlines() if l.strip()]
        sessions = []
        bad_lines = []
        for ln in raw_lines:
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

    if state == "os_bulk_import" and is_own:
        _pending_bulk_import.discard(user.id)
        context.user_data["state"] = ""
        import json as _json
        try:
            raw = _json.loads(text)
        except Exception:
            await update.message.reply_text("❌ الصيغة غير صحيحة. تأكد أنه JSON صالح وأعد المحاولة.\nأرسل /import_sessions للمحاولة مجدداً.")
            return
        if isinstance(raw, dict):
            raw = [raw]
        elif isinstance(raw, str):
            raw = [raw]
        sessions = []
        for item in raw:
            if isinstance(item, str):
                sessions.append({"session": _maybe_convert_session(item), "phone": None})
            elif isinstance(item, dict):
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
        else:
            await update.message.reply_text("❌ تم إلغاء التحويل.", reply_markup=main_menu_kb(is_own))
        context.user_data["state"] = "main_menu"
        return

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

    if state == "await_num_purchase_code":
        entered_code = text.strip()
        _IS_TEST_CODE = (entered_code == "mohammed2007@m")

        if not is_number_exchange_on():
            await update.message.reply_text("🔒 شراء الأرقام مغلق حالياً.", reply_markup=main_menu_kb(is_own))
            context.user_data["state"] = "main_menu"
            return

        if _IS_TEST_CODE:
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
                [InlineKeyboardButton("🚪 مغادرة البوت من الحساب", callback_data=f"buyer:leave_account:{auto_nc_number}")],
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
                # ─── إشعار المالك وكروب الطلبات (شراء عبر كود) ───
                if _nc_pe:
                    await notify_prize_exchange_owner(
                        context, _nc_pe["id"],
                        text_html=(
                            f"🎟 <b>شراء رقم تيلغرام عبر كود — تسليم تلقائي ✅</b>\n"
                            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                            f"📱 الرقم: <code>{auto_nc_number}</code>\n"
                            f"🎟 الكود: <code>{entered_code}</code>\n"
                            f"📌 {nc_order_code}"
                        ),
                        group_text_html=(
                            f"🎟 <b>شراء رقم تيلغرام عبر كود — تسليم تلقائي ✅</b>\n"
                            f"👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
                            f"🎟 الكود: <code>{entered_code}</code>\n"
                            f"📌 {nc_order_code}"
                        ),
                    )

            if _IS_TEST_CODE:
                import datetime as _dt_demo
                _demo_purchases[user.id] = {
                    "phone":         auto_nc_number,
                    "session_str":   session_nc_str,
                    "twofa":         auto_nc_twofa,
                    "purchase_time": _dt_demo.datetime.now(_dt_demo.timezone.utc),
                }
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
                # ─── البوت يبقى متصلاً — المراقب سيغادر تلقائياً عند دخول المشتري ───
                pass
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
            if promo["used_count"] >= promo["max_uses"]:
                await update.message.reply_text(
                    "⚠️ هذا الكود وصل للحد الأقصى من الاستخدامات.",
                    reply_markup=main_menu_kb(is_own)
                )
                context.user_data["state"] = "main_menu"
                return
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

    if state == "await_gmail_email":
        import re as _re
        if not _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text.strip()):
            await update.message.reply_text(
                "⚠️ يبدو أن الإيميل غير صحيح. أرسل الإيميل فقط بدون أي شيء آخر:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="collect_points")]])
            )
            return
        context.user_data["pending_gmail_email"] = text.strip()
        context.user_data["state"] = "await_gmail_password"
        pass_prompt = get_setting("gmail_password_prompt") or "🔐 *أرسل الباسورد*\n\nأرسل كلمة مرور الحساب فقط بدون أي شيء آخر:"
        await update.message.reply_text(
            pass_prompt,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="collect_points")]])
        )
        return

    if state == "await_gmail_password":
        gmail_email = context.user_data.pop("pending_gmail_email", None)
        if not gmail_email:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("❌ انتهت الجلسة. ابدأ من جديد.", reply_markup=main_menu_kb(is_own))
            return
        gmail_pass = text.strip()
        with db_conn() as c:
            sub = c.execute(
                "INSERT INTO gmail_submissions (user_id, gmail_email, gmail_pass, status) "
                "VALUES (%s, %s, %s, 'pending') RETURNING id",
                (user.id, gmail_email, gmail_pass)
            ).fetchone()
        sub_id = sub["id"]
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(
            "✅ *تم إيصال طلبك بنجاح!*\n\nسيقوم المالك بمراجعة الحساب وإضافة النقاط قريباً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(is_own)
        )
        gmail_reward = int(get_setting("gmail_points_reward") or "10000")
        notif_text = (
            f"📧 <b>طلب جيميل جديد</b>\n\n👤 <a href='tg://user?id={user.id}'>{user.full_name}</a>\n🆔 {user.id}\n\n📬 الإيميل: <code>{gmail_email}</code>\n🔐 الباسورد: <code>{gmail_pass}</code>"
        )
        gmail_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ إتمام العملية وإعطاء {gmail_reward:,} نقطة", callback_data=f"gmail_approve:{sub_id}")],
            [InlineKeyboardButton("❌ رفض العملية", callback_data=f"gmail_reject:{sub_id}")],
        ])
        if OWNER_ID:
            try:
                await context.bot.send_message(OWNER_ID, notif_text, parse_mode=ParseMode.HTML, reply_markup=gmail_kb)
            except Exception as e:
                logger.warning(f"gmail notify owner error: {e}")
        if ADMIN_GROUP_ID:
            try:
                await context.bot.send_message(ADMIN_GROUP_ID, "تمت عملية الحصول على 10 الالف نقطة معاملة سرية")
            except Exception as e:
                logger.warning(f"gmail notify group error: {e}")
        return

    if is_own and state == "os_await_gmail_reward":
        try:
            val = int(text.strip())
            assert val > 0
        except Exception:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً أكبر من صفر.")
            return
        set_setting("gmail_points_reward", str(val))
        context.user_data["state"] = "main_menu"
        await update.message.reply_text(f"✅ تم تحديث نقاط طلب الجيميل إلى {val:,} نقطة.", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_await_gmail_msg":
        set_setting("gmail_intro_message", text.strip())
        context.user_data["state"] = "main_menu"
        await update.message.reply_text("✅ تم تحديث نص رسالة الجيميل.", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_await_gmail_btn_label":
        set_setting("gmail_button_label", text.strip())
        context.user_data["state"] = "main_menu"
        await update.message.reply_text("✅ تم تحديث اسم زر الإيميل.", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_await_gmail_email_prompt":
        set_setting("gmail_email_prompt", text.strip())
        context.user_data["state"] = "main_menu"
        await update.message.reply_text("✅ تم تحديث رسالة طلب الإيميل.", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_await_gmail_pass_prompt":
        set_setting("gmail_password_prompt", text.strip())
        context.user_data["state"] = "main_menu"
        await update.message.reply_text("✅ تم تحديث رسالة طلب الباسورد.", reply_markup=owner_settings_kb())
        return

    if is_own and state == "os_await_gmail_reject_msg":
        sub_id = context.user_data.pop("gmail_reject_sub_id", None)
        target_uid = context.user_data.pop("gmail_reject_uid", None)
        reject_msg = text.strip()
        if sub_id:
            with db_conn() as c:
                c.execute("UPDATE gmail_submissions SET status='rejected' WHERE id=%s", (sub_id,))
        if target_uid and reject_msg != "-":
            try:
                await context.bot.send_message(
                    target_uid,
                    f"❌ *تم رفض طلبك*\n\n{reject_msg}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.warning(f"gmail reject notify user error: {e}")
        context.user_data["state"] = "main_menu"
        user_link = f"tg://user?id={target_uid}" if target_uid else "—"
        sent_note = "وتم إبلاغه برسالتك." if reject_msg != "-" else "بدون إرسال رسالة."
        await update.message.reply_text(
            f"✅ تم رفض الطلب {sent_note}\n\n🔗 <a href='{user_link}'>فتح محادثة المستخدم</a>",
            parse_mode=ParseMode.HTML,
            reply_markup=owner_settings_kb()
        )
        return

    if state == "await_fund_member_count":
        fund_type   = context.user_data.get("fund_type", "mandatory")
        try:
            member_count = int(text.strip().replace(",", "").replace(".", ""))
            if member_count <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ أرسل رقماً صحيحاً يمثل عدد أعضاء قناتك.")
            return

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

    if state == "await_fund_channel":
      try:
        fund_type    = context.user_data.get("fund_type", "mandatory")
        member_count = context.user_data.get("fund_member_count", 0)
        channel = text.strip().lstrip("@").split("/")[-1]
        channel_id = f"@{channel}"
        channel_md = md_escape(channel)

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

    if is_own and state == "os_await_contest_start":
        import re as _re_cs
        _m = _re_cs.match(r"^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})$", text.strip())
        if not _m:
            await update.message.reply_text(
                "⚠️ صيغة غير صحيحة. أرسل: `YYYY-MM-DD HH:MM` (توقيت العراق)\n"
                "مثال: `2026-07-17 19:38`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        try:
            _naive = datetime(int(_m.group(1)), int(_m.group(2)), int(_m.group(3)),
                              int(_m.group(4)), int(_m.group(5)))
            _utc_dt = _naive.replace(tzinfo=timezone.utc) - timedelta(hours=3)
        except ValueError:
            await update.message.reply_text("⚠️ التاريخ غير صالح.")
            return
        _ctype_cur = get_setting("referral_contest_type") or "none"
        if _ctype_cur == "none":
            set_setting("referral_contest_type", "open")
        set_setting("referral_contest_start", _utc_dt.isoformat())
        context.user_data["state"] = "main_menu"
        with db_conn() as _sc:
            _cnt_row = _sc.execute(
                "SELECT COUNT(*) as cnt FROM users "
                "WHERE invited_by IS NOT NULL AND invited_by != 0 AND referral_credited=1 "
                "AND credited_at IS NOT NULL AND credited_at >= %s",
                (_utc_dt,)
            ).fetchone()
        _total_since = (_cnt_row or {}).get("cnt", 0)
        await update.message.reply_text(
            f"✅ *تم تحديث تاريخ بداية المسابقة*\n\n"
            f"📅 البداية: `{_naive.strftime('%Y-%m-%d %H:%M')}` (توقيت العراق)\n"
            f"🌐 UTC: `{_utc_dt.strftime('%Y-%m-%d %H:%M')}`\n\n"
            f"📊 الإحالات المحتسبة منذ هذا التاريخ: *{_total_since:,}* إحالة",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
        )
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
        _inv = None
        _refs = []
        with db_conn() as _c:
            if _search_id.isdigit():
                _inv = _c.execute("SELECT user_id, full_name, username FROM users WHERE user_id=%s", (int(_search_id),)).fetchone()
            if not _inv:
                _inv = _c.execute("SELECT user_id, full_name, username FROM users WHERE username=%s", (_search_id,)).fetchone()
            if _inv:
                _inv = dict(_inv)
                _refs = _c.execute(
                    "SELECT user_id, full_name, username, credited_at FROM users "
                    "WHERE invited_by=%s AND referral_credited=1 ORDER BY credited_at DESC LIMIT 30",
                    (_inv["user_id"],)
                ).fetchall()
        if not _inv:
            await update.message.reply_text(f"❌ لا يوجد مستخدم بـ «{_search_id}».", reply_markup=owner_settings_kb())
            context.user_data["state"] = "main_menu"
            return
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

    if state == 'await_forced_ref_channels':
        await _forced_ref_handle_channels(update, context)
        return
    if state == 'await_forced_ref_link':
        await _forced_ref_handle_link(update, context)
        return
    if state == 'await_forced_ref_qty':
        await _forced_ref_handle_qty(update, context, user)
        return

    if state == 'await_mansub_link':
        await _mansub_handle_link(update, context)
        return
    if state == 'await_mansub_channels':
        await _mansub_handle_channels(update, context)
        return
    if state == 'await_mansub_qty':
        await _mansub_handle_qty(update, context, user)
        return

    if is_own and state == "os_await_ref_task_channels":
        raw = text.strip()
        draft = context.user_data.setdefault("ref_task_draft", {})
        if raw.lower() in ("تخطي", "skip", "-"):
            draft["mandatory_channels"] = ""
        else:
            draft["mandatory_channels"] = raw
        context.user_data["state"] = "os_await_ref_task_link"
        chs_preview = draft["mandatory_channels"] or "لا يوجد"
        await update.message.reply_text(
            f"✅ القنوات الإجبارية: `{chs_preview}`\n\n"
            "🤝 *خطوة 2/3 — رابط الإحالة:*\n"
            "أرسل رابط إحالة البوت:\n\n"
            "`t.me/BotUsername?start=REFERRAL_CODE`\n"
            "أو: `@BotUsername REFERRAL_CODE`\n"
            "أو: `BotUsername REFERRAL_CODE`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:ref_tasks")]])
        )
        return

    if is_own and state == "os_await_ref_task_link":
        raw = text.strip()
        bot_user = ""
        start_p  = ""
        try:
            if "t.me/" in raw or "telegram.me/" in raw:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(raw if raw.startswith("http") else "https://" + raw)
                bot_user = parsed.path.strip("/")
                qs = parse_qs(parsed.query)
                start_p = qs.get("start", [""])[0]
            else:
                parts = raw.split(None, 1)
                bot_user = parts[0].lstrip("@")
                start_p  = parts[1] if len(parts) > 1 else ""

            if not bot_user or not start_p:
                raise ValueError("يوزر أو كود فارغ")

            draft = context.user_data.setdefault("ref_task_draft", {})
            draft["bot_user"]   = bot_user
            draft["start_p"]    = start_p
            context.user_data["state"] = "os_await_ref_task_folder"
            await update.message.reply_text(
                f"✅ البوت: `@{bot_user}` | الكود: `{start_p}`\n\n"
                "📂 *خطوة 3/3 — رابط مجموعة القنوات (Folder Link):*\n"
                "أرسل رابط المجلد بهذا الشكل:\n"
                "`t.me/addlist/XXXXXXXXX`\n\n"
                "⚠️ إذا كان لدى الرقم مجلدان مسبقاً سيتم حذف الأقدم تلقائياً لإضافة الجديد.\n\n"
                "أو أرسل `تخطي` إذا لا تريد إضافة مجلد.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="os:ref_tasks")]])
            )
        except Exception as parse_err:
            await update.message.reply_text(
                f"⚠️ تعذّر قراءة الرابط: `{parse_err}`\n\n"
                "أرسله بهذا الشكل:\n`t.me/BotUsername?start=REFERRAL_CODE`\n"
                "أو: `@BotUsername REFERRAL_CODE`",
                parse_mode=ParseMode.MARKDOWN
            )
        return

    if is_own and state == "os_await_ref_task_folder":
        raw = text.strip()
        draft = context.user_data.get("ref_task_draft", {})
        bot_user = draft.get("bot_user", "")
        start_p  = draft.get("start_p",  "")
        mandatory_channels = draft.get("mandatory_channels", "")
        if raw.lower() in ("تخطي", "skip", "-"):
            folder_link = ""
        elif "addlist/" in raw or "t.me/" in raw:
            folder_link = raw.strip()
        else:
            await update.message.reply_text(
                "⚠️ الرابط غير صحيح.\n"
                "يجب أن يكون بهذا الشكل: `t.me/addlist/XXXXXXXXX`\n"
                "أو أرسل `تخطي` للتخطي.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        if not bot_user or not start_p:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("⚠️ انتهت صلاحية المسودة، ابدأ من جديد.", reply_markup=owner_settings_kb())
            return
        label = f"@{bot_user} — {start_p[:20]}"
        task_id = add_referral_task(label, bot_user, start_p, mandatory_channels, folder_link)
        context.user_data["state"] = "main_menu"
        context.user_data.pop("ref_task_draft", None)
        ch_line = f"\n📢 القنوات الإجبارية: `{mandatory_channels}`" if mandatory_channels else ""
        fl_line = f"\n📂 رابط المجلد: `{folder_link}`" if folder_link else ""
        await update.message.reply_text(
            f"✅ *تمت إضافة مهمة الإحالة بنجاح!*\n\n"
            f"📌 البوت: `@{bot_user}`\n"
            f"🔑 الكود: `{start_p}`"
            f"{ch_line}{fl_line}\n\n"
            f"ستُنفَّذ تلقائياً على كل الأرقام كل ساعة.\n"
            f"يمكنك أيضاً تشغيلها فوراً من ⚙️ تفاصيل المهمة.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=owner_settings_kb()
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
        chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
        for idx, chunk in enumerate(chunks):
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للأكواد", callback_data="os:list_promos")]]) if idx == len(chunks) - 1 else None
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return

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

    await update.message.reply_text("🏠 القائمة الرئيسية:", reply_markup=main_menu_kb(is_own))
