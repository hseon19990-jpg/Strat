"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

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

RAKSH_ACCOUNTS_LABEL_SETTING = "raksh_accounts_label"
DEFAULT_RAKSH_ACCOUNTS_LABEL = "خدمات تيليجرام أسطورية"

def get_raksh_accounts_label() -> str:
    """يعيد الاسم المخصص لقسم حسابات الرشق مع قيمة افتراضية آمنة."""
    configured = (get_setting(RAKSH_ACCOUNTS_LABEL_SETTING) or "").strip()
    
    # إذا كان الاسم المخصص فارغاً أو يساوي الاسم القديم، نعيد الاسم الجديد دائماً
    if not configured or configured in {
        "حسابات خدمات الرشق",
        "خدمات الرشق",
        "خدمات المرتقى",
        "خدمات تلي مميزة",
    }:
        return "خدمات تيليجرام أسطورية"
    
    # وإلا نعيد الاسم المخصص الذي اختاره المالك
    return " ".join(configured.split())[:64]

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

MENU_LABELS = {
    "main": "القائمة الرئيسية",
    "owner_settings": "قائمة إعدادات المالك",
    "collect_points": "تجميع نقاط",
    "contact_support": "تواصل مع الدعم",
    "services_menu": "قائمة الخدمات",
}
MENU_LABELS.update({v: f"خدمات: {lbl.split(' ', 1)[1]}" for lbl, v in SERVICE_PLATFORMS})
MENU_LABELS.update({f"cat:{k}": f"قائمة فئة: {v}" for k, v in CATEGORY_MAP.items()})
MENU_LABELS["legendary_services"] = "الخدمات الأسطورية"

SERVICES_MENU_CATEGORIES = [
    "followers",
    "views",
    "interactions",
    "story_views",
    "start_bot",
    "boost",
    "post_stars",
    "other",
]

MANAGEABLE_MENUS = [
    "main",
    "owner_settings",
    "services_menu",
    "legendary_services",
] + [v for _, v in SERVICE_PLATFORMS] + [f"cat:{k}" for k in CATEGORY_MAP]

LEGENDARY_SERVICES_MESSAGE = (
    "👑 *الخدمات الأسطورية*\n\n"
    "جميع الحسابات حقيقية ولديها ستوري وبايو وصورة وافتار\n\n"
    "💰 *أسعار الخدمات (نقاط + نجوم):*\n"
    "• 💬 تعليق: 30 نقطة/وحدة + 30 قناة | ⭐ 1 نجمة لكل 5\n"
    "• 📊 استفتاء: 30 نقطة/وحدة + 30 قناة | ⭐ 1 نجمة لكل 5\n"
    "• 👁 ستوري: 30 نقطة/وحدة + 30 قناة | ⭐ 1 نجمة لكل 10\n"
    "• 🗳 أصوات: 20 نقطة/وحدة + 25 قناة | ⭐ 1 نجمة لكل 10\n"
    "• 🤖 تصويت بتحقق: 50 نقطة/وحدة + 25 قناة | ⭐ 1 نجمة لكل 4\n"
    "• ✨ تفاعل مميز: 10 نقاط/وحدة + 0 قناة | ⭐ 1 نجمة لكل 25\n"
    "• 🤖 إحالة بوت إجباري تحتوي تحقق: 300 نقطة/وحدة + 25 قناة | ⭐ 1.5 نجمة/حساب (أعداد زوجية فقط) ⚠️\n\n"
    "⏱️ الفاصل بين الحسابات: 1-8 دقائق (تلقائي)\n"
    "🔹 المالك يمكنه تحديد فاصل زمني مخصص\n\n"
    "اختر الخدمة:"
)

LEGENDARY_SERVICE_OPTIONS = [
    ("💬 رشق تعليق", "legendary:start:comment", 1),
    ("📊 رشق استفتاء", "legendary:start:poll", 1),
    ("👁 رشق مشاهدة وتفاعل ستوري", "legendary:start:story", 1),
    ("🗳 رشق أصوات", "legendary:start:votes", 1),
    ("🤖 رشق تصويت بتحقق", "legendary:start:votes_ai", 1),
    ("✨ رشق تفاعل مميز", "legendary:start:premium_reaction", 1),
    ("🤖 إحالة بوت إجباري تحتوي تحقق", "legendary:start:forced_ref_ai", 1),
]

_LEGENDARY_SERVICE_TYPES = {
    action.rsplit(":", 1)[-1]
    for _, action, _ in LEGENDARY_SERVICE_OPTIONS
}

def resolve_legendary_service_type(action_value: str) -> str | None:
    """Resolve current and legacy callback values to a service type."""
    if not action_value:
        return None

    parts = action_value.split(":")
    candidates = []
    if len(parts) == 3 and parts[:2] == ["legendary", "start"]:
        candidates.append(parts[2])
    elif len(parts) == 2 and parts[0] in {"legendary", "legendary_service"}:
        candidates.append(parts[1])
    elif len(parts) == 2 and parts[0] == "legendary_start":
        candidates.append(parts[1])

    for candidate in candidates:
        if candidate in _LEGENDARY_SERVICE_TYPES:
            return candidate
    return None

def normalize_legendary_menu_item(item):
    """Return a menu item with the callback format understood by the router."""
    action_value = item["action_value"]
    service_type = resolve_legendary_service_type(action_value)

    if not service_type:
        label = item["label"]
        service_type = next(
            (
                action.rsplit(":", 1)[-1]
                for default_label, action, _ in LEGENDARY_SERVICE_OPTIONS
                if label == default_label
            ),
            None,
        )

    if not service_type:
        return item

    normalized = dict(item)
    normalized["action_type"] = "builtin"
    normalized["action_value"] = f"legendary:start:{service_type}"
    return normalized

BUILTIN_DEFAULTS = {
    "main": [
        ("رشق حقيقي", "services_menu", 1),
        ("👑 خدمات تيليجرام أسطورية", "legendary_services", 1),
        ("🦇 تمويل قناتك حقيقي", "fund_channel", 1),
        ("👻 رابط دعوة", "referral", 1),
        ("👍 شحن نقاط", "charge_points", 2),
        ("⭐ تجميع نقاط", "collect_points", 2),
        ("🎁 استبدال نقاط بجوائز", "exchange_points", 2),
        ("🎙 تحويل النقاط", "transfer_points", 2),
        ("🎟 استخدام كود", "use_promo", 2),
        ("⭐ معلوماتي", "my_info", 2),
        ("📱 ارقامي", "my_numbers", 1),
        ("🎁 الأكثر دعوةً اليوم", "top_ref_today", 2),
        ("✅ تواصل مع الدعم", "contact_support", 2),
        ("💌 شكر المالك", "thank_owner", 2),
        ("🏆 مسابقة الدعوة", "referral_contest_view", 2),
        ("📧 احصل على نقاط مقابل إيميل جيميل", "gmail_points", 1),
        ("🔑 إحالة بوت اجباري", "forced_ref", 2),
    ],
    "services_menu": [(label, value, 2) for label, value in SERVICE_PLATFORMS],
    "legendary_services": LEGENDARY_SERVICE_OPTIONS,
    "services_menu_tg": [
        ("👥 رشق متابعين", "cat:followers", 2),
        ("👁 رشق مشاهدات", "cat:views", 2),
        ("💬 رشق تفاعلات", "cat:interactions", 2),
        ("📖 رشق مشاهدات ستوري", "cat:story_views", 2),
        ("🤖 رشق بدء (ستارت) بوت", "cat:start_bot", 2),
        ("📣 تعزيز قناة أو كروب", "cat:boost", 2),
        ("⭐ نجوم على بوست قناة", "cat:post_stars", 1),
        ("🔧 خدمات أخرى", "cat:other", 1),
    ],
    "services_menu_ig": [
        ("👥 متابعين", "cat:followers", 2),
        ("👁 مشاهدات", "cat:views", 2),
        ("💬 تفاعلات", "cat:interactions", 2),
        ("📖 مشاهدات ستوري", "cat:story_views", 2),
        ("🔧 خدمات أخرى", "cat:other", 1),
    ],
    "services_menu_tt": [
        ("👥 متابعين", "cat:followers", 2),
        ("👁 مشاهدات", "cat:views", 2),
        ("💬 تفاعلات", "cat:interactions", 2),
        ("🔧 خدمات أخرى", "cat:other", 1),
    ],
    "services_menu_wa": [
        ("👥 أعضاء", "cat:followers", 2),
        ("👁 مشاهدات", "cat:views", 2),
        ("🔧 خدمات أخرى", "cat:other", 1),
    ],
    "services_menu_fb": [
        ("👥 متابعين", "cat:followers", 2),
        ("👁 مشاهدات", "cat:views", 2),
        ("💬 تفاعلات", "cat:interactions", 2),
        ("🔧 خدمات أخرى", "cat:other", 1),
    ],
    "services_menu_yt": [
        ("👥 مشتركين", "cat:followers", 2),
        ("👁 مشاهدات", "cat:views", 2),
        ("💬 تفاعلات", "cat:interactions", 2),
        ("🔧 خدمات أخرى", "cat:other", 1),
    ],
    "services_menu_sc": [
        ("👥 متابعين", "cat:followers", 2),
        ("👁 مشاهدات", "cat:views", 2),
        ("📖 مشاهدات ستوري", "cat:story_views", 2),
        ("🔧 خدمات أخرى", "cat:other", 1),
    ],
    "services_menu_tw": [
        ("👥 متابعين", "cat:followers", 2),
        ("👁 مشاهدات", "cat:views", 2),
        ("💬 تفاعلات", "cat:interactions", 2),
        ("🔧 خدمات أخرى", "cat:other", 1),
    ],
    "owner_settings": [
        ("➕ إضافة خدمة", "os:add_service", 2),
        ("📋 قائمة الخدمات", "os:list_services", 2),
        ("🗂 عرض الخدمات", "os:view_services", 2),
        ("🔍 الفحص", "os:inspect_services", 2),
        ("📦 قسم الطلبات", "os:orders_section", 2),
        ("📝 تعديل وصف عدة خدمات", "os:share_description", 2),
        ("🎁 تعديل الهدية اليومية", "os:edit_gift", 2),
        ("🎀 جوائز مخصصة", "os:manage_prizes", 2),
        ("🔗 تعديل نقاط الدعوة", "os:edit_referral", 2),
        ("⭐ سعر النجمة شحن", "os:edit_star_rate", 2),
        ("🏆 سعر نجمة الجوائز", "os:edit_exchange_rate", 2),
        ("📦 باقات الاستبدال بنجوم", "os:manage_star_packages", 1),
        ("📱 سعر رقم تيلغرام", "os:edit_number_cost", 2),
        ("⭐ سعر رقم بالنجوم", "os:edit_number_stars", 2),
        ("💌 رسالة الترحيب", "os:edit_welcome", 2),
        ("📥 مخزون أرقام تيلغرام", "os:manage_numbers", 2),
        ("🎟 أكواد شراء رقم", "os:manage_num_codes", 2),
        ("🔄 سعر تمويل داخلي", "os:edit_internal_cost", 2),
        ("🎁 نقاط الانضمام للقنوات", "os:edit_join_reward", 1),
        ("❌ خصم مغادرة القناة", "os:edit_leave_penalty", 1),
        ("⏱ مهلة المغادرة الآمنة (ساعة)", "os:edit_leave_grace", 1),
        ("⭐ إجباري: حد أدنى (نجوم)", "os:edit_mstars_min", 2),
        ("⭐ إجباري: حد الشريحة 1", "os:edit_mstars_t1max", 2),
        ("⭐ إجباري: سعر ش1 (×100)", "os:edit_mstars_t1p", 2),
        ("⭐ إجباري: سعر ش2 (×100)", "os:edit_mstars_t2p", 2),
        ("📧 إيميلات جيميل", "os:list_gmail", 2),
        ("🔐 حسابات التحقق", "os:verified_gmail", 2),
        ("📋 سجل كل الإيميلات", "os:all_gmail_history", 2),
        ("⚙️ نقاط طلب جيميل", "os:edit_gmail_reward", 2),
        ("✏️ نص رسالة الجيميل", "os:edit_gmail_msg", 2),
        ("🏷 اسم زر الإيميل", "os:edit_gmail_btn_label", 2),
        ("📨 رسالة طلب الإيميل", "os:edit_gmail_email_prompt", 2),
        ("🔑 رسالة طلب الباسورد", "os:edit_gmail_pass_prompt", 2),
        ("💬 نص طلب ملاحظة التحقق", "os:edit_gmail_verification_note_prompt", 2),
        ("🔒 تعليمات تسجيل الخروج", "os:edit_gmail_logout_instructions", 2),
        ("📹 فيديو رفض: باسورد خطأ", "os:edit_reject_pass_video", 2),
        ("✏️ نص رفض: باسورد خطأ", "os:edit_reject_pass_caption", 2),
        ("📹 فيديو رفض: يحتاج تحقق", "os:edit_reject_verify_video", 2),
        ("✏️ نص رفض: يحتاج تحقق", "os:edit_reject_verify_caption", 2),
        ("✏️ رسالة رفض: إيميل خطأ", "os:edit_reject_email_msg", 1),
        ("💰 إجباري-نقاط: سعر/عضو", "os:edit_mpoints_price", 2),
        ("💰 إجباري-نقاط: حد أدنى", "os:edit_mpoints_min", 2),
        ("📡 إدارة قنوات الاشتراك", "os:manage_channels", 2),
        ("👥 حد أدنى تمويل داخلي", "os:edit_internal_min", 2),
        ("❌ إلغاء صفقة", "os:cancel_order", 2),
        ("✅ إكمال طلب", "os:complete_order", 2),
        ("🎟 إنشاء كود ترويجي", "os:create_promo", 2),
        ("📋 أكواد ترويجية", "os:list_promos", 2),
        ("🚫 إدارة الحظر", "os:ban_menu", 2),
        ("🔍 من استخدم الكود", "os:search_code", 2),
        ("💰 منح/خصم نقاط", "os:manage_points", 2),
        ("💬 رابط تواصل المالك", "os:edit_contact", 2),
        ("✏️ نص زر التواصل", "os:edit_contact_label", 2),
        ("💌 إعدادات شكر المالك", "os:thank_owner_settings", 1),
        ("📲 تعديل نص اسيا سيل", "os:edit_asiacell", 2),
        ("✏️ نص زر الدعم بالقائمة", "os:edit_support_label", 2),
        ("📢 رسالة جماعية", "os:broadcast", 2),
        ("🔐 تفعيل/تعطيل التحقق", "os:toggle_captcha", 2),
        ("📊 إحصائيات", "os:stats", 2),
        ("🛠 وضع الصيانة", "os:toggle_maintenance", 2),
        ("📱 استبدال الأرقام", "os:toggle_number_exchange", 2),
        ("🏆 الأكثر إرسالاً لرابط الدعوة", "os:top_referrers", 2),
        ("🎯 مسابقة رابط الدعوة", "os:referral_contest", 1),
        ("👑 خدمات أسطورية للأعضاء", "os:toggle_legendary_services", 1),
        ("💵 رصيد موقع الرشق", "os:site_balance", 1),
        ("🧩 إدارة الأزرار", "os:manage_buttons", 1),
        ("✏️ رسالة عند الاستبدال", "os:edit_exchange_msg", 1),
        ("⚠️ تعويض المظلومين", "os:failed_deliveries", 1),
        ("📱 أرقام إحالة بوت إجباري", "os:bot_ref_numbers", 1),
        ("👥 الأعضاء المقيدين", "os:restricted_members", 1),
        ("💰 تعديل أسعار الخدمات الأسطورية", "legendary:price_settings", 1),
        ("🌐 استيراد الخدمات من المواقع", "import_services", 1),
    ],
}

GOTO_TARGETS = [
    ("🏠 القائمة الرئيسية", "main_menu"),
    ("🛍 خدمات", "services_menu"),
    ("🔗 رابط دعوة", "referral"),
    ("💰 تجميع نقاط", "collect_points"),
    ("💎 شحن نقاط", "charge_points"),
    ("🏆 استبدال نقاط بجوائز", "exchange_points"),
    ("↔️ تحويل النقاط", "transfer_points"),
    ("🎟 استخدام كود", "use_promo"),
    ("ℹ️ معلوماتي", "my_info"),
    ("📱 ارقامي", "my_numbers"),
    ("📺 تمويل قناتك حقيقي", "fund_channel"),
] + SERVICE_PLATFORMS + [(v, f"cat:{k}") for k, v in CATEGORY_MAP.items()]

def seed_menu_items(menu: str):
    with db_conn() as c:
        c.execute(
            "DELETE FROM menu_items WHERE menu='main' AND action_value IN "
            "('daily_gift','join_channels','totp_generator')"
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
            # ترقية أسماء الزر القديمة فقط، مع الحفاظ على أي اسم مخصص جديد.
            c.execute(
                "UPDATE menu_items SET label=?, width=1 WHERE menu='main' "
                "AND action_value='services_menu' AND label IN (?, ?, ?, ?)",
                ("رشق حقيقي", "🐺 خدمات", "🛍 خدمات", "خدمات الرشق", "خدمات الرشق 🔥")
            )
        _main_icon_migration = {
            "services_menu": ("خدمات الرشق 🔥", "رشق حقيقي", 1),
            "fund_channel": ("📺 تمويل قناتك حقيقي", "🦇 تمويل قناتك حقيقي", 1),
            "referral": ("🔗 رابط دعوة", "👻 رابط دعوة", 1),
            "charge_points": ("💎 شحن نقاط", "👍 شحن نقاط", 2),
            "collect_points": ("💰 تجميع نقاط", "⭐ تجميع نقاط", 2),
            "exchange_points": ("🏆 استبدال نقاط بجوائز", "🎁 استبدال نقاط بجوائز", 2),
            "transfer_points": ("↔️ تحويل النقاط", "🎙 تحويل النقاط", 2),
            "my_info": ("ℹ️ معلوماتي", "⭐ معلوماتي", 2),
            "top_ref_today": ("🏆 الأكثر دعوةً اليوم", "🎁 الأكثر دعوةً اليوم", 2),
            "contact_support": ("🛎 تواصل مع الدعم", "✅ تواصل مع الدعم", 2),
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
    if menu == "legendary_services":
        with db_conn() as c:
            existing_rows = c.execute(
                "SELECT id, label, action_value FROM menu_items "
                "WHERE menu='legendary_services'"
            ).fetchall()
            for row in existing_rows:
                normalized = normalize_legendary_menu_item(row)
                if normalized["action_value"] != row["action_value"]:
                    c.execute(
                        "UPDATE menu_items SET action_type='builtin', action_value=? "
                        "WHERE id=?",
                        (normalized["action_value"], row["id"]),
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
            InlineKeyboardButton("✏️ الاسم", callback_data=f"mb_rename:{menu}:{it['id']}"),
            InlineKeyboardButton("🗑" if it["enabled"] else "♻️", callback_data=f"mb_toggle:{menu}:{it['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ إضافة زر جديد", callback_data=f"mb_add:{menu}")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="os:manage_buttons")])
    text = (f"🧩 *أزرار: {MENU_LABELS.get(menu, menu)}*\n\n"
            f"✅ ظاهر | 🚫 مخفي — اضغط 🗑 للإخفاء و♻️ للإظهار مجدداً.")
    return text, InlineKeyboardMarkup(rows)

def build_kb_rows(items):
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
        else:
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
    if not text:
        return text
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text

async def notify_gmail_verification_owner(
    context: ContextTypes.DEFAULT_TYPE,
    sub_id: int,
    user_id: int,
    note: str = "",
) -> str:
    note = (note or "").strip()[:2000]
    if not note:
        return "note_required"
    if not OWNER_ID:
        return "owner_missing"

    with db_conn() as c:
        lock = c.execute(
            "SELECT pg_try_advisory_xact_lock(%s) AS acquired",
            (sub_id,),
        ).fetchone()
        if not lock or not lock["acquired"]:
            return "busy"

        sub = c.execute(
            "SELECT id, user_id, gmail_email, status, rejection_reason, "
            "verification_notified FROM gmail_submissions WHERE id=%s",
            (sub_id,),
        ).fetchone()
        if not sub or sub["user_id"] != user_id:
            return "invalid"
        if (
            sub["status"] != "rejected"
            or sub["rejection_reason"] not in ("need_verify", "")
        ):
            return "unavailable"
        if sub["verification_notified"]:
            return "already"

        note_html = html.escape(note)
        await context.bot.send_message(
            OWNER_ID,
            f"🔔 <b>العضو أتمّ التحقق من حساب الجيميل</b>\n\n"
            f"🆔 العضو: <code>{sub['user_id']}</code>\n"
            f"📬 الإيميل: <code>{html.escape(sub['gmail_email'] or '')}</code>\n"
            f"📌 الطلب: <code>#{sub_id}</code>\n"
            f"💬 <b>رسالة العضو:</b>\n<code>{note_html}</code>\n\n"
            "يمكنك مراجعة الطلب واتخاذ القرار من الزر أدناه.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "📋 عرض التفاصيل",
                    callback_data=f"gmail_detail:{sub_id}",
                )
            ]]),
        )
        c.execute(
            "UPDATE gmail_submissions SET verification_completed=TRUE, "
            "verification_notified=TRUE, verification_note=%s WHERE id=%s",
            (note, sub_id),
        )
    return "sent"