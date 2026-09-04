"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

def generate_math():
    a, b = random.randint(1, 9), random.randint(1, 9)
    op = random.choice(['+', '-', '×'])
    if op == '+': return f"{a} + {b}", a + b
    if op == '-':
        a, b = max(a, b), min(a, b)
        return f"{a} - {b}", a - b
    return f"{a} × {b}", a * b

EMOJI_CAPTCHA_SET = ["😀", "😎", "🐶", "🐱", "🦊", "🐼", "🐸", "🦁", "🐵", "🍎", "🍋", "🍉", "⭐", "🔥", "🌈"]

def generate_emoji_captcha():
    question = random.choice(EMOJI_CAPTCHA_SET)
    distractors = random.sample([emoji for emoji in EMOJI_CAPTCHA_SET if emoji != question], 5)
    options = distractors + [question]
    random.shuffle(options)
    return question, options

def emoji_captcha_kb(options):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(options[i], callback_data=f"verify_emoji:{i}") for i in range(row, min(row + 2, len(options)))]
        for row in range(0, len(options), 2)
    ])

# ────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────
def supervisor_panel_kb():
    """لوحة المشرف — تظهر فقط للمشرفين المعتمدين من المالك."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة حساب جديد", callback_data="sv:login_number")],
        [InlineKeyboardButton("📋 حساباتي الخاصة",  callback_data="sv:my_accounts")],
        [InlineKeyboardButton("🔑 إحالة إجبارية",    callback_data="sv:forced_ref")],
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
    ])

def main_menu_kb(is_owner=False, is_supervisor_user=False):
    menu_items = get_menu_items("main")
    if not is_owner and not is_legendary_services_visible():
        menu_items = [
            item for item in menu_items
            if item["action_value"] != "legendary_services"
        ]
    rows = build_kb_rows(menu_items)
    if is_supervisor_user and not is_owner:
        rows.append([InlineKeyboardButton("🛡 لوحة المشرف", callback_data="sv:panel")])
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
    rows.append([InlineKeyboardButton("📝 تعديل وصف عدة خدمات", callback_data="os:share_description")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
    return "\n".join(lines), rows


def _render_description_service_selection(selected_ids=None):
    """عرض الخدمات لتحديد الخدمات التي سيُطبّق عليها الوصف المشترك."""
    selected_ids = {int(item) for item in (selected_ids or [])}
    with db_conn() as c:
        svcs = c.execute("SELECT * FROM services ORDER BY category, id").fetchall()

    rows = []
    for service in svcs:
        mark = "✅" if int(service["id"]) in selected_ids else "⬜"
        rows.append([
            InlineKeyboardButton(
                f"{mark} {service['name_ar'][:28]}",
                callback_data=f"os:desc_toggle:{service['id']}"
            )
        ])

    if svcs:
        rows.append([
            InlineKeyboardButton(
                f"✅ تطبيق الوصف ({len(selected_ids)})",
                callback_data="os:desc_apply"
            ),
            InlineKeyboardButton("☑️ تحديد الكل", callback_data="os:desc_select_all"),
        ])
        rows.append([
            InlineKeyboardButton("🧹 إلغاء التحديد", callback_data="os:desc_clear")
        ])
    rows.append([InlineKeyboardButton("🔙 إلغاء", callback_data="os:list_services")])
    text = (
        f"📝 *اختيار خدمات لمشاركة الوصف* ({len(svcs)} خدمة)\n\n"
        "حدد الخدمات التي تريد وضع الوصف عليها، ثم اضغط «تطبيق الوصف»."
    )
    return text, rows


def _render_staging_services(selected_ids=None):
    """يعرض الخدمات الجديدة مع دعم تحديد عدة خدمات للنقل الجماعي."""
    selected_ids = {int(item) for item in (selected_ids or [])}
    with db_conn() as c:
        staged = c.execute("SELECT * FROM staging_services ORDER BY id DESC").fetchall()

    rows = []
    for service in staged:
        panel_name = PANEL_MAP.get(service["panel"] or 1, PANEL_MAP[1])["name"]
        mark = "✅" if int(service["id"]) in selected_ids else "⬜"
        rows.append([
            InlineKeyboardButton(
                f"{mark} {service['name_ar']} — {panel_name}",
                callback_data=f"os:ns_toggle:{service['id']}"
            ),
            InlineKeyboardButton(
                "🔍 التفاصيل",
                callback_data=f"os:ns_view:{service['id']}"
            ),
        ])

    if staged:
        rows.append([
            InlineKeyboardButton(
                f"📤 نقل المحدد ({len(selected_ids)})",
                callback_data="os:ns_move_start"
            ),
            InlineKeyboardButton("☑️ تحديد الكل", callback_data="os:ns_select_all"),
        ])
        rows.append([
            InlineKeyboardButton("🧹 إلغاء التحديد", callback_data="os:ns_clear_selection")
        ])

    rows.append([InlineKeyboardButton("➕ إضافة خدمة", callback_data="os:ns_add")])
    rows.append([InlineKeyboardButton("🔙 إعدادات المالك", callback_data="owner_settings")])
    count_txt = f"({len(staged)} خدمة)" if staged else "(فارغة)"
    text = (
        f"📦 *الخدمات الجديدة* {count_txt}\n\n"
        "حدد خدمة واحدة أو عدة خدمات من الأزرار، ثم اضغط «نقل المحدد»."
    )
    return text, rows

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


def _inspection_display(value, fallback="—") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _inspection_num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _inspection_same(left, right) -> bool:
    left_num = _inspection_num(left)
    right_num = _inspection_num(right)
    if left_num is not None and right_num is not None:
        return left_num == right_num
    return str(left or "").strip() == str(right or "").strip()


def _inspection_line(label: str, local_value, site_value, site_label: str = "الموقع") -> str:
    marker = "✅" if _inspection_same(local_value, site_value) else "⚠️"
    return (
        f"{marker} <b>{html.escape(label)}:</b> "
        f"المحلي: <code>{html.escape(_inspection_display(local_value))}</code> | "
        f"{html.escape(site_label)}: <code>{html.escape(_inspection_display(site_value))}</code>"
    )


def _render_service_inspection_block(local_service, remote_service, site_name: str) -> str:
    """يبني تقرير مقارنة واحد بين الخدمة المحفوظة وردّ الموقع."""
    local = local_service
    remote = remote_service or {}
    remote_price = None
    rate_num = _inspection_num(remote.get("rate"))
    if rate_num is not None:
        remote_price = fmt_price(rate_num * 100_000)

    if remote_service is None:
        return (
            f"🧾 <b>الخدمة المحلية #{local['id']}</b> — API: "
            f"<code>{html.escape(_inspection_display(local['api_service_id']))}</code>\n"
            f"🌐 الموقع: <b>{html.escape(site_name)}</b>\n"
            f"❌ لم يتم العثور على الخدمة في ردّ الموقع أو تعذّر جلبه.\n\n"
            f"🏠 <b>بيانات البوت</b>\n"
            f"الاسم: <code>{html.escape(_inspection_display(local['name_ar']))}</code>\n"
            f"الوصف: <code>{html.escape(_inspection_display(local['description']))}</code>\n"
            f"السعر: <code>{html.escape(fmt_price(local['price_per_point']))}</code> نقطة/1000\n"
            f"الحدود: <code>{local['min_qty']}</code> — <code>{local['max_qty']}</code>\n"
        )

    lines = [
        f"🧾 <b>الخدمة المحلية #{local['id']}</b> — API: "
        f"<code>{html.escape(_inspection_display(local['api_service_id']))}</code>",
        f"🌐 الموقع: <b>{html.escape(site_name)}</b>",
        "🏠 <b>بيانات البوت مقابل 🌐 بيانات الموقع</b>",
        _inspection_line("الاسم", local["name_ar"], remote.get("name")),
        _inspection_line("الوصف", local["description"], remote.get("description")),
        _inspection_line("السعر/1000", fmt_price(local["price_per_point"]), remote_price),
        _inspection_line("الحد الأدنى", local["min_qty"], remote.get("min")),
        _inspection_line("الحد الأعلى", local["max_qty"], remote.get("max")),
        _inspection_line("الفئة", CATEGORY_MAP.get(local["category"], local["category"]), remote.get("category")),
        _inspection_line("النوع", local.get("service_type"), remote.get("type")),
        f"الحالة في البوت: {'✅ مفعّلة' if local['active'] else '❌ معطّلة'}",
    ]

    # عرض بقية بيانات الموقع كما وردت من API، وليس الحقول الأساسية فقط.
    known_keys = {"service", "name", "description", "rate", "min", "max", "category", "type"}
    extra = [
        (key, value) for key, value in remote.items()
        if key not in known_keys and value not in (None, "")
    ]
    if extra:
        lines.append("📋 <b>بقية بيانات الموقع:</b>")
        for key, value in sorted(extra, key=lambda item: str(item[0])):
            lines.append(
                f"• <code>{html.escape(str(key))}</code>: "
                f"<code>{html.escape(str(value))}</code>"
            )
    return "\n".join(lines)


async def send_services_inspection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يفحص كل الخدمات محلياً مقابل بياناتها المباشرة من مواقع SMM."""
    with db_conn() as c:
        services = c.execute("SELECT * FROM services ORDER BY panel, id").fetchall()

    if not services:
        await update.callback_query.edit_message_text(
            "🔍 لا توجد خدمات لفحصها.",
            reply_markup=owner_settings_kb()
        )
        return

    # تحديث مباشر لكل موقع مستخدم، حتى لا يعرض الفحص نتيجة قديمة من الكاش.
    remote_by_panel = {}
    for panel in sorted({int(s["panel"] or 1) for s in services}):
        try:
            remote_list = await asyncio.to_thread(smm_services_list, panel, True)
            remote_by_panel[panel] = (
                {str(item.get("service")): item for item in (remote_list or [])}
                if remote_list is not None else None
            )
        except Exception as exc:
            logger.warning(f"⚠️ فشل فحص خدمات الموقع {panel}: {exc}")
            remote_by_panel[panel] = None

    blocks = []
    found_count = 0
    different_count = 0
    for local in services:
        panel = int(local["panel"] or 1)
        site_name = PANEL_MAP.get(panel, PANEL_MAP[1])["name"]
        panel_services = remote_by_panel.get(panel)
        remote = panel_services.get(str(local["api_service_id"])) if panel_services is not None else None
        if remote is not None:
            found_count += 1
            remote_price_num = _inspection_num(remote.get("rate"))
            remote_price = fmt_price(remote_price_num * 100_000) if remote_price_num is not None else None
            if any([
                not _inspection_same(local["name_ar"], remote.get("name")),
                not _inspection_same(local["description"], remote.get("description")),
                not _inspection_same(fmt_price(local["price_per_point"]), remote_price),
                not _inspection_same(local["min_qty"], remote.get("min")),
                not _inspection_same(local["max_qty"], remote.get("max")),
            ]):
                different_count += 1
        blocks.append(_render_service_inspection_block(local, remote, site_name))

    header = (
        f"🔍 <b>فحص الخدمات</b>\n"
        f"📊 الإجمالي: <b>{len(services)}</b> | موجودة بالموقع: <b>{found_count}</b> | "
        f"بها اختلافات: <b>{different_count}</b>\n"
        f"✅ مطابق | ⚠️ مختلف\n\n"
    )

    # نرسل التقرير على دفعات آمنة ضمن حد تيليغرام، مع بقاء كل خدمة كاملة في رسالة واحدة.
    chunks = []
    current = header
    for block in blocks:
        candidate = current + block + "\n\n" + ("─" * 25) + "\n\n"
        if len(candidate) > 3800 and current != header:
            chunks.append(current)
            current = block + "\n\n" + ("─" * 25) + "\n\n"
        else:
            current = candidate
    if current.strip():
        chunks.append(current)

    for index, chunk in enumerate(chunks):
        if index == 0:
            await update.callback_query.edit_message_text(chunk, parse_mode=ParseMode.HTML)
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=chunk,
                parse_mode=ParseMode.HTML
            )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ انتهى الفحص. هذه مقارنة مباشرة بين إعدادات البوت وبيانات الموقع.",
        reply_markup=owner_settings_kb()
    )


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
    _legendary_on = is_legendary_services_visible()
    _legendary_suffix = " (ظاهر للأعضاء ✅)" if _legendary_on else " (مخفي عن الأعضاء ❌)"
    _mandatory_active = count_active_mandatory_channels()
    _verify_suffix = f" ({_mandatory_active} قناة ✅)" if _mandatory_active > 0 else " (مغلق ❌)"
    _phone_verify_on = int(get_setting("phone_verification_enabled") or "1")
    _captcha_on = int(get_setting("captcha_enabled") or "0")
    rows.append([InlineKeyboardButton(
        f"📱 التحقق برقم الهاتف ({'مفعّل ✅' if _phone_verify_on else 'معطّل ❌'})",
        callback_data="os:toggle_phone_verification"
    )])
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
            elif btn.callback_data == "os:toggle_legendary_services":
                base_label = btn.text.split(" (")[0]
                row[i] = InlineKeyboardButton(
                    base_label + _legendary_suffix,
                    callback_data="os:toggle_legendary_services",
                )
            elif btn.callback_data == "os:toggle_captcha":
                row[i] = InlineKeyboardButton(
                    f"🔐 التحقق ({'مفعّل ✅' if _captcha_on else 'معطّل ❌'})",
                    callback_data="os:toggle_captcha",
                )
    # Add legendary settings button
    rows.append([InlineKeyboardButton("👑 إعدادات الخدمات الأسطورية", callback_data="legendary:settings")])
    rows.append([InlineKeyboardButton("🛡 إضافة مشرف", callback_data="os:add_supervisor"),
                  InlineKeyboardButton("📋 إدارة المشرفين", callback_data="os:list_supervisors")])
    rows.append([InlineKeyboardButton("👁 حسابات المشرفين", callback_data="os:sv_accounts")])
    rows.append([InlineKeyboardButton("👤 معلومات الحسابات", callback_data="os:account_info")])
    rows.append([
        InlineKeyboardButton(
            f"🔥 {get_raksh_accounts_label()}",
            callback_data="os:raksh_accounts",
        )
    ])
    rows.append([
        InlineKeyboardButton(
            "✏️ تغيير اسم خدمات تلي مميزة",
            callback_data="os:edit_raksh_label",
        )
    ])
    rows.append([InlineKeyboardButton("📦 الخدمات الجديدة", callback_data="os:new_services")])
    rows.append([InlineKeyboardButton("🧩 إضافة/إزالة خيار", callback_data="mb_menu:owner_settings")])
    rows.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def _account_info_counts() -> tuple[int, int, int, int]:
    """يعيد إجمالي الحسابات والجلسات والحصص المتبقية للستوري والأفتار."""
    try:
        with db_conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE session_string IS NOT NULL "
                "AND BTRIM(session_string) <> '') AS with_session "
                "FROM number_stock WHERE deleted_at IS NULL"
            ).fetchone()
        total = int(row["total"] or 0)
        with_session = int(row["with_session"] or 0)
        story_available = len(_load_unused_media_accounts("stories"))
        avatar_available = len(_load_unused_media_accounts("avatar"))
        return total, with_session, story_available, avatar_available
    except Exception as exc:
        logger.warning(f"⚠️ تعذر قراءة إحصائيات الحسابات: {exc}")
        return 0, 0, 0, 0

def account_info_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔤 الاسم", callback_data="os:account_names"),
        ],
        [
            InlineKeyboardButton("📝 البايو", callback_data="os:account_bios"),
            InlineKeyboardButton("🔖 اليوزر", callback_data="os:account_usernames"),
        ],
        [
            InlineKeyboardButton("🖼️ الأفتار", callback_data="os:avatars"),
            InlineKeyboardButton("📊 نتائج الأفتار", callback_data="os:media_report:avatar:summary"),
        ],
        [
            InlineKeyboardButton("📖 الستوري", callback_data="os:stories"),
            InlineKeyboardButton("📊 نتائج الستوري", callback_data="os:media_report:stories:summary"),
        ],
        [
            InlineKeyboardButton("🌍 جعل الستوريات عامة", callback_data="os:make_stories_public"),
        ],
        [InlineKeyboardButton("🔙 إعدادات المالك", callback_data="owner_settings")],
    ])

def _account_name_count() -> int:
    try:
        with db_conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS total FROM account_name_assignments"
            ).fetchone()
        return int(row["total"] or 0)
    except Exception as exc:
        logger.warning(f"⚠️ تعذر قراءة عدد أسماء الحسابات: {exc}")
        return 0

def _account_bio_count() -> int:
    try:
        with db_conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS total FROM account_bio_assignments"
            ).fetchone()
        return int(row["total"] or 0)
    except Exception as exc:
        logger.warning(f"⚠️ تعذر قراءة عدد البايو: {exc}")
        return 0

def _account_username_count() -> int:
    try:
        with db_conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS total FROM account_username_assignments"
            ).fetchone()
        return int(row["total"] or 0)
    except Exception as exc:
        logger.warning(f"⚠️ تعذر قراءة عدد اليوزرات: {exc}")
        return 0

def _seed_historical_media_assignments(kind: str) -> None:
    """ينقل الحسابات الناجحة في التقارير القديمة إلى سجل الاستخدام الدائم."""
    if kind not in {"stories", "avatar"}:
        raise ValueError(f"نوع توزيع غير معروف: {kind}")

    successful_phones: set[str] = set()
    for report in _load_media_reports(kind):
        successful_phones.update(
            str(phone).strip()
            for phone in report.get("success") or []
            if str(phone).strip()
        )

    # قد تكون هناك عملية قُطعت قبل الضغط على «إنهاء»، لذلك نقرأ تقرير التقدم
    # أيضًا حتى لا تعود الحسابات التي نجحت في تلك العملية بعد إعادة التشغيل.
    try:
        progress = json.loads(get_setting(_media_report_progress_key(kind)) or "null")
        if isinstance(progress, dict):
            successful_phones.update(
                str(phone).strip()
                for phone in progress.get("success") or []
                if str(phone).strip()
            )
    except Exception:
        pass

    if not successful_phones:
        return

    with db_conn() as c:
        for phone in successful_phones:
            c.execute(
                """
                INSERT INTO account_media_assignments
                    (kind, stock_id, phone_number, status, assigned_at, completed_at)
                SELECT %s, id, phone_number, 'completed', COALESCE(added_at, NOW()), NOW()
                FROM number_stock
                WHERE phone_number = %s
                ON CONFLICT DO NOTHING
                """,
                (kind, phone),
            )

def _load_unused_media_accounts(kind: str) -> list[dict]:
    """يعيد الحسابات التي لم تُستخدم لهذا النوع طوال عمرها."""
    if kind not in {"stories", "avatar"}:
        raise ValueError(f"نوع توزيع غير معروف: {kind}")

    _seed_historical_media_assignments(kind)
    with db_conn() as c:
        rows = c.execute(
            """
            SELECT ns.id, ns.phone_number, ns.session_string
            FROM number_stock ns
            WHERE ns.deleted_at IS NULL
              AND ns.session_string IS NOT NULL
              AND BTRIM(ns.session_string) <> ''
              AND NOT EXISTS (
                  SELECT 1
                  FROM account_media_assignments ama
                  WHERE ama.kind = %s
                    AND (
                        ama.stock_id = ns.id
                        OR (
                            ama.phone_number IS NOT NULL
                            AND ama.phone_number = ns.phone_number
                        )
                    )
              )
            ORDER BY ns.id
            """,
            (kind,),
        ).fetchall()
    return [dict(row) for row in rows]

def _claim_media_account(kind: str, stock_id: int, phone_number: str | None) -> bool:
    """يحجز الحساب مرة واحدة فقط، حتى مع وصول عمليتين في نفس الوقت."""
    with db_conn() as c:
        row = c.execute(
            """
            INSERT INTO account_media_assignments
                (kind, stock_id, phone_number, status)
            VALUES (%s, %s, %s, 'processing')
            ON CONFLICT DO NOTHING
            RETURNING stock_id
            """,
            (kind, stock_id, phone_number),
        ).fetchone()
    return bool(row)

def _complete_media_account(kind: str, stock_id: int) -> None:
    with db_conn() as c:
        c.execute(
            """
            UPDATE account_media_assignments
            SET status = 'completed', completed_at = NOW()
            WHERE kind = %s AND stock_id = %s AND status = 'processing'
            """,
            (kind, stock_id),
        )

def _release_media_account(kind: str, stock_id: int) -> None:
    """يفتح الحجز عند فشل النشر قبل أن يستلم الحساب أي محتوى."""
    with db_conn() as c:
        c.execute(
            """
            DELETE FROM account_media_assignments
            WHERE kind = %s AND stock_id = %s AND status = 'processing'
            """,
            (kind, stock_id),
        )

_MEDIA_REPORT_PAGE_SIZE = 20
_MEDIA_REPORT_HISTORY_PAGE_SIZE = 8
_MEDIA_REPORT_HISTORY_MAX = 50

def _media_report_key(kind: str) -> str:
    if kind not in {"stories", "avatar"}:
        raise ValueError(f"نوع تقرير غير معروف: {kind}")
    return f"media_report_{kind}"

def _media_report_history_key(kind: str) -> str:
    if kind not in {"stories", "avatar"}:
        raise ValueError(f"نوع تقرير غير معروف: {kind}")
    return f"media_report_history_{kind}"

def _media_report_progress_key(kind: str) -> str:
    if kind not in {"stories", "avatar"}:
        raise ValueError(f"نوع تقرير غير معروف: {kind}")
    return f"media_report_progress_{kind}"

def _normalise_failed_media_item(item: object) -> dict[str, str]:
    """يحافظ على توافق التقارير القديمة التي كانت تُخزّن كسطر نصي واحد."""
    if isinstance(item, dict):
        return {
            "phone": str(item.get("phone") or "رقم غير معروف"),
            "reason": str(item.get("reason") or "سبب غير محدد"),
        }
    text = str(item or "")
    phone, separator, reason = text.partition(" — ")
    return {
        "phone": phone.strip() or "رقم غير معروف",
        "reason": reason.strip() if separator else "سبب غير محدد",
    }

def _normalise_media_report(report: object, kind: str) -> dict | None:
    if not isinstance(report, dict):
        return None
    report = dict(report)
    report["kind"] = kind
    report["saved_at"] = str(report.get("saved_at") or "")
    report["total"] = int(report.get("total") or 0)
    report["processed"] = int(report.get("processed") or 0)
    report["success"] = [str(item) for item in report.get("success") or []]
    report["failed"] = [
        _normalise_failed_media_item(item) for item in report.get("failed") or []
    ]
    return report

def _decode_media_report_history(raw: str, kind: str) -> list[dict]:
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except Exception:
        return []
    candidates = decoded if isinstance(decoded, list) else [decoded]
    reports = [
        report
        for report in (_normalise_media_report(item, kind) for item in candidates)
        if report
    ]
    return reports[:_MEDIA_REPORT_HISTORY_MAX]

def _load_media_reports(kind: str) -> list[dict]:
    """يعيد كل التقارير بترتيب الأحدث أولاً، مع ترحيل التقرير القديم المفرد."""
    try:
        history = _decode_media_report_history(
            get_setting(_media_report_history_key(kind)),
            kind,
        )
        if history:
            return history

        # قبل دعم السجل كانت آخر نتيجة محفوظة في هذا المفتاح المفرد.
        # نُبقيها ظاهرة كي لا تختفي التقارير القديمة بعد التحديث.
        legacy = _normalise_media_report(
            json.loads(get_setting(_media_report_key(kind)) or "null"),
            kind,
        )
        return [legacy] if legacy else []
    except Exception as exc:
        logger.warning(f"⚠️ تعذر قراءة سجل تقارير {kind}: {exc}")
        return []

def _begin_media_report(kind: str) -> None:
    """يهيئ السجل قبل عملية جديدة من دون خلط تقدمها بالتقارير المكتملة."""
    try:
        history = _load_media_reports(kind)
        set_setting(
            _media_report_history_key(kind),
            json.dumps(history[:_MEDIA_REPORT_HISTORY_MAX], ensure_ascii=False),
        )
        set_setting(_media_report_progress_key(kind), "")
    except Exception as exc:
        logger.warning(f"⚠️ تعذر تهيئة سجل تقارير {kind}: {exc}")

def _save_media_report(
    kind: str,
    total: int,
    success: list[object],
    failed: list[object],
) -> None:
    """يحفظ النتيجة الأخيرة ويضيفها إلى سجل العمليات المكتملة."""
    payload = {
        "kind": kind,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "total": int(total),
        "processed": len(success) + len(failed),
        "success": [str(phone) for phone in success],
        "failed": [_normalise_failed_media_item(item) for item in failed],
    }
    history = _load_media_reports(kind)
    history.insert(0, payload)
    set_setting(
        _media_report_history_key(kind),
        json.dumps(history[:_MEDIA_REPORT_HISTORY_MAX], ensure_ascii=False),
    )
    set_setting(_media_report_key(kind), json.dumps(payload, ensure_ascii=False))
    set_setting(_media_report_progress_key(kind), "")

def _persist_upload_report(kind: str, user_data: dict) -> None:
    """يحفظ تقدم العملية الحالية دون تسجيلها كسجل مكتمل."""
    try:
        accounts_key = "story_accounts" if kind == "stories" else "avatar_accounts"
        success_key = "story_success" if kind == "stories" else "avatar_success"
        failed_key = "story_failed" if kind == "stories" else "avatar_failed"
        payload = {
            "kind": kind,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "total": int(len(user_data.get(accounts_key) or [])),
            "processed": len(user_data.get(success_key) or [])
            + len(user_data.get(failed_key) or []),
            "success": [str(phone) for phone in user_data.get(success_key) or []],
            "failed": [
                _normalise_failed_media_item(item)
                for item in user_data.get(failed_key) or []
            ],
        }
        set_setting(
            _media_report_progress_key(kind),
            json.dumps(payload, ensure_ascii=False),
        )
    except Exception as exc:
        logger.warning(f"⚠️ تعذر حفظ تقرير {kind}: {exc}")

def _load_media_report(kind: str) -> dict | None:
    reports = _load_media_reports(kind)
    return reports[0] if reports else None

def _media_reports_text() -> str:
    lines = [
        "📊 تقارير نتائج الستوري والأفتار",
        "",
        "اختر نوع العملية لعرض الأرقام الناجحة والأرقام الفاشلة مع سبب الفشل.",
    ]
    for kind, label in (("stories", "الستوري"), ("avatar", "الأفتار")):
        reports = _load_media_reports(kind)
        report = reports[0] if reports else None
        if not report:
            lines.append(f"\n{label}: لا يوجد تقرير محفوظ بعد.")
            continue
        lines.append(
            f"\n{label}: ✅ {len(report['success']):,} ناجح | "
            f"❌ {len(report['failed']):,} فاشل | "
            f"📚 {len(reports):,} عملية محفوظة"
        )
    return "\n".join(lines)

def _media_reports_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 تقرير الستوري", callback_data="os:media_report:stories:summary"),
            InlineKeyboardButton("🖼️ تقرير الأفتار", callback_data="os:media_report:avatar:summary"),
        ],
        [InlineKeyboardButton("🔙 معلومات الحسابات", callback_data="os:account_info")],
    ])

def _media_report_summary(
    kind: str,
    report: dict | None,
    report_index: int = 0,
    report_count: int = 0,
) -> tuple[str, InlineKeyboardMarkup]:
    label = "الستوري" if kind == "stories" else "الأفتار"
    if not report:
        return (
            f"📋 تقرير {label}\n\nلا يوجد تقرير محفوظ لهذا النوع حتى الآن.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 معلومات الحسابات", callback_data="os:account_info")],
            ]),
        )
    saved_at = str(report.get("saved_at") or "").replace("T", " ").split(".")[0]
    text = (
        f"📋 تقرير {label}\n\n"
        f"📦 الحسابات المستهدفة: {int(report.get('total') or 0):,}\n"
        f"📊 الحسابات المعالجة: {int(report.get('processed') or 0):,}\n"
        f"✅ نجح: {len(report['success']):,}\n"
        f"❌ فشل: {len(report['failed']):,}\n"
        f"🕐 آخر تحديث: {saved_at or 'غير معروف'}\n\n"
        "اختر القائمة التي تريد عرضها:"
    )
    return (
        text,
        InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"✅ الأرقام الناجحة ({len(report['success']):,})",
                    callback_data=f"os:media_report:{kind}:success:{report_index}:0",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"❌ الأرقام الفاشلة ({len(report['failed']):,})",
                    callback_data=f"os:media_report:{kind}:failed:{report_index}:0",
                ),
            ],
            *(
                [[InlineKeyboardButton(
                    f"📚 السجلات السابقة ({report_count:,})",
                    callback_data=f"os:media_report:{kind}:history:0",
                )]]
                if report_count > 1
                else []
            ),
            [InlineKeyboardButton("🔙 معلومات الحسابات", callback_data="os:account_info")],
        ]),
    )

def _media_report_history_page(
    kind: str,
    page: int,
) -> tuple[str, InlineKeyboardMarkup]:
    label = "الستوري" if kind == "stories" else "الأفتار"
    reports = _load_media_reports(kind)
    total_pages = max(
        1,
        (len(reports) + _MEDIA_REPORT_HISTORY_PAGE_SIZE - 1)
        // _MEDIA_REPORT_HISTORY_PAGE_SIZE,
    )
    page = max(0, min(page, total_pages - 1))
    start = page * _MEDIA_REPORT_HISTORY_PAGE_SIZE
    current = reports[start:start + _MEDIA_REPORT_HISTORY_PAGE_SIZE]
    lines = [
        f"📚 سجل تقارير {label}",
        "",
        f"📄 الصفحة {page + 1}/{total_pages} | الإجمالي: {len(reports):,}",
        "",
    ]
    if not current:
        lines.append("لا توجد تقارير محفوظة.")

    rows = []
    for offset, report in enumerate(current):
        report_index = start + offset
        saved_at = str(report.get("saved_at") or "").replace("T", " ").split(".")[0]
        rows.append([
            InlineKeyboardButton(
                f"عملية {report_index + 1} — {saved_at or 'وقت غير معروف'}",
                callback_data=f"os:media_report:{kind}:run:{report_index}",
            )
        ])
        lines.append(
            f"{report_index + 1}. {saved_at or 'وقت غير معروف'} — "
            f"✅ {len(report['success']):,} | ❌ {len(report['failed']):,}"
        )

    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "◀️ السابق",
                callback_data=f"os:media_report:{kind}:history:{page - 1}",
            )
        )
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                "التالي ▶️",
                callback_data=f"os:media_report:{kind}:history:{page + 1}",
            )
        )
    if nav:
        rows.append(nav)
    rows.extend([
        [InlineKeyboardButton(
            "🔙 أحدث تقرير",
            callback_data=f"os:media_report:{kind}:summary",
        )],
        [InlineKeyboardButton("🔙 معلومات الحسابات", callback_data="os:account_info")],
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)

def _media_report_page(
    kind: str,
    section: str,
    page: int,
    report: dict | None,
    report_index: int = 0,
) -> tuple[str, InlineKeyboardMarkup]:
    label = "الستوري" if kind == "stories" else "الأفتار"
    if not report:
        return _media_report_summary(kind, report)

    items = report["success"] if section == "success" else report["failed"]
    total_pages = max(1, (len(items) + _MEDIA_REPORT_PAGE_SIZE - 1) // _MEDIA_REPORT_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * _MEDIA_REPORT_PAGE_SIZE
    current = items[start:start + _MEDIA_REPORT_PAGE_SIZE]
    title = "الأرقام الناجحة" if section == "success" else "الأرقام الفاشلة وأسباب الفشل"
    lines = [
        f"📋 تقرير {label} — {title}",
        "",
        f"📄 الصفحة {page + 1}/{total_pages} | الإجمالي: {len(items):,}",
        "",
    ]
    if not current:
        lines.append("لا توجد نتائج في هذه القائمة.")
    elif section == "success":
        lines.extend(f"✅ {phone}" for phone in current)
    else:
        lines.extend(
            f"❌ {item['phone']} — {item['reason']}"
            for item in current
        )

    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "◀️ السابق",
                callback_data=(
                    f"os:media_report:{kind}:{section}:{report_index}:{page - 1}"
                ),
            )
        )
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                "التالي ▶️",
                callback_data=(
                    f"os:media_report:{kind}:{section}:{report_index}:{page + 1}"
                ),
            )
        )
    rows = [nav] if nav else []
    rows.extend([
        [InlineKeyboardButton(
            "🔙 ملخص التقرير",
            callback_data=(
                f"os:media_report:{kind}:summary"
                if report_index == 0
                else f"os:media_report:{kind}:run:{report_index}"
            ),
        )],
        [InlineKeyboardButton("🔙 معلومات الحسابات", callback_data="os:account_info")],
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)

def avatar_upload_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ إنهاء التوزيع", callback_data="os:avatar_finish")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="os:avatar_cancel")],
    ])

def _clear_avatar_upload_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        "avatar_accounts",
        "avatar_index",
        "avatar_success",
        "avatar_failed",
    ):
        context.user_data.pop(key, None)
    context.user_data["state"] = "main_menu"

def _avatar_report_keyboard(has_more: bool) -> InlineKeyboardMarkup:
    if has_more:
        return avatar_upload_kb()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 عرض التقرير", callback_data="os:avatar_finish")],
    ])

async def _set_account_avatar(
    session_string: str,
    photo_bytes: bytes,
    file_name: str,
) -> None:
    """يرفع صورة واحدة إلى حساب تيليجرام مرتبط بجلسة مخزنة."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise RuntimeError("إعدادات Telegram API غير مكتملة")

    client = TelegramClient(
        StringSession(session_string),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            raise RuntimeError("الجلسة غير مصرح بها")
        uploaded = await asyncio.wait_for(
            client.upload_file(photo_bytes, file_name=file_name),
            timeout=45,
        )
        await asyncio.wait_for(
            client(UploadProfilePhotoRequest(file=uploaded)),
            timeout=30,
        )
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

async def _process_avatar_batch(
    owner_id: int,
    bot,
    chat_id: int,
    file_ids: list[str],
    user_data,
) -> None:
    """يعالج دفعة صور على طابور حسابات عشوائي لا يعيد الحسابات."""
    lock = _avatar_upload_locks.setdefault(owner_id, asyncio.Lock())
    async with lock:
        if user_data.get("state") != "os_avatar_upload":
            return

        accounts = user_data.get("avatar_accounts") or []
        index = int(user_data.get("avatar_index", 0) or 0)
        available = max(0, len(accounts) - index)
        if not available:
            await bot.send_message(
                chat_id,
                "ℹ️ انتهت الحسابات التي لديها جلسة. اضغط «إنهاء التوزيع» لرؤية التقرير.",
                reply_markup=avatar_upload_kb(),
            )
            return

        batch = file_ids[:available]
        ignored = max(0, len(file_ids) - len(batch))
        success = 0
        failed = 0
        result_lines = []

        for offset, file_id in enumerate(batch):
            account_index = index + offset
            account = accounts[account_index]
            label = account.get("phone_number") or f"الحساب رقم {account_index + 1}"
            stock_id = int(account["id"])
            if not _claim_media_account("avatar", stock_id, account.get("phone_number")):
                user_data.setdefault("avatar_failed", []).append(
                    f"{label} — الحساب مستخدم مسبقاً في توزيع سابق"
                )
                failed += 1
                continue
            published = False
            try:
                tg_file = await bot.get_file(file_id)
                photo_bytes = bytes(await tg_file.download_as_bytearray())
                await _set_account_avatar(
                    account["session_string"],
                    photo_bytes,
                    f"avatar_{account_index + 1}.jpg",
                )
                published = True
                _complete_media_account("avatar", stock_id)
                user_data.setdefault("avatar_success", []).append(label)
                success += 1
            except Exception as exc:
                # إذا نجح تيليجرام ثم فشل حفظ الحالة، نُبقي الحجز حتى لا
                # تؤدي إعادة المحاولة إلى وضع أفتار ثانٍ على الحساب.
                if not published:
                    try:
                        _release_media_account("avatar", stock_id)
                    except Exception as release_exc:
                        logger.error(f"❌ تعذر تحرير حجز الأفتار للحساب {label}: {release_exc}")
                logger.warning(f"⚠️ فشل وضع الأفتار على {label}: {exc}")
                user_data.setdefault("avatar_failed", []).append(
                    f"{label} — {str(exc)[:100]}"
                )
                failed += 1

        user_data["avatar_index"] = index + len(batch)
        _persist_upload_report("avatar", user_data)
        remaining = max(0, len(accounts) - user_data["avatar_index"])
        result_lines.append(
            f"✅ تمت معالجة الدفعة: {len(batch)} صورة\n"
            f"🟢 نجح: {success} | 🔴 فشل: {failed}\n"
            f"🎲 التوزيع عشوائي، والحسابات المستخدمة لا تتكرر.\n"
            f"📊 التقدم الكلي: {user_data['avatar_index']}/{len(accounts)}\n"
            f"👤 الحسابات المتبقية: {remaining}"
        )
        if ignored:
            result_lines.append(
                f"⚠️ تم تجاهل {ignored} صورة لأن عدد الصور أكبر من الحسابات المتبقية."
            )
        if remaining:
            result_lines.append("أرسل الدفعة التالية، وسأكمل من حسابات جديدة عشوائياً.")

        await bot.send_message(
            chat_id,
            "\n\n".join(result_lines),
            reply_markup=_avatar_report_keyboard(bool(remaining)),
        )

async def _flush_avatar_album(owner_id: int, media_group_id: str, bot) -> None:
    """ينتظر اكتمال ألبوم تيليجرام ثم يعالجه كدفعة واحدة."""
    try:
        await asyncio.sleep(1.5)
        key = (owner_id, media_group_id)
        entry = _avatar_album_buffers.pop(key, None)
        _avatar_album_tasks.pop(key, None)
        if not entry:
            return
        user_data = entry["user_data"]
        await _process_avatar_batch(
            owner_id,
            bot,
            entry["chat_id"],
            entry["file_ids"],
            user_data,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception(f"❌ خطأ في معالجة ألبوم الأفتارات: {exc}")

async def handle_avatar_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يجمع الألبومات ويدفع الصور المفردة مباشرة إلى طابور الأفتارات."""
    if not update.message or update.effective_user is None:
        return
    if update.effective_user.id != OWNER_ID:
        return
    if context.user_data.get("state") == "os_story_upload":
        await handle_story_photo(update, context)
        return
    if context.user_data.get("state") != "os_avatar_upload":
        return

    photo = update.message.photo[-1] if update.message.photo else None
    if photo is None:
        await update.message.reply_text(
            "⚠️ أرسل صورة واضحة فقط.",
            reply_markup=avatar_upload_kb(),
        )
        return

    media_group_id = update.message.media_group_id
    if not media_group_id:
        await _process_avatar_batch(
            update.effective_user.id,
            context.bot,
            update.effective_chat.id,
            [photo.file_id],
            context.user_data,
        )
        return

    key = (update.effective_user.id, str(media_group_id))
    entry = _avatar_album_buffers.setdefault(
        key,
        {
            "file_ids": [],
            "chat_id": update.effective_chat.id,
            "user_data": context.user_data,
        },
    )
    if photo.file_id not in entry["file_ids"]:
        entry["file_ids"].append(photo.file_id)
    if key not in _avatar_album_tasks:
        _avatar_album_tasks[key] = asyncio.create_task(
            _flush_avatar_album(update.effective_user.id, str(media_group_id), context.bot)
        )

def story_upload_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ إنهاء النشر", callback_data="os:story_finish")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="os:story_cancel")],
    ])

_STORY_VIDEO_EXTENSIONS = {
    ".3g2", ".3gp", ".avi", ".flv", ".m2ts", ".m4v",
    ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".mts",
    ".ts", ".webm", ".wmv",
}

def _public_story_privacy_rules() -> list[InputPrivacyValueAllowAll]:
    """Return a fresh privacy rule list that makes every new story public."""
    return [InputPrivacyValueAllowAll()]

async def _story_ids_for_account(client: TelegramClient, me) -> list[int]:
    """Collect active and archived story IDs without returning duplicate IDs."""
    story_ids: list[int] = []
    seen: set[int] = set()

    def add_story_ids(items) -> None:
        for item in items or []:
            story_id = getattr(item, "id", None)
            if isinstance(story_id, int) and story_id > 0 and story_id not in seen:
                seen.add(story_id)
                story_ids.append(story_id)

    active = await client(
        functions.stories.GetPeerStoriesRequest(peer=me)
    )
    add_story_ids(getattr(active, "stories", None))

    # Telegram returns the archive in pages. The next page starts at the
    # smallest story ID from the previous page.
    archive_offset = 0
    visited_offsets: set[int] = set()
    archive_limit = 100
    while archive_offset not in visited_offsets:
        visited_offsets.add(archive_offset)
        archive = await client(
            functions.stories.GetStoriesArchiveRequest(
                peer=me,
                offset_id=archive_offset,
                limit=archive_limit,
            )
        )
        page = getattr(archive, "stories", None) or []
        page_ids = [
            story_id
            for story_id in (getattr(item, "id", None) for item in page)
            if isinstance(story_id, int) and story_id > 0
        ]
        if not page_ids:
            break
        add_story_ids(page)
        next_offset = min(page_ids)
        if next_offset == archive_offset or next_offset in visited_offsets:
            break
        archive_offset = next_offset
        if len(page) < archive_limit:
            break

    return story_ids

async def _make_account_stories_public(session_string: str) -> tuple[int, int, list[str]]:
    """Make every accessible active and archived story public for one account."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise RuntimeError("إعدادات Telegram API غير مكتملة")

    client = TelegramClient(
        StringSession(session_string),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    success = 0
    failed: list[str] = []
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            raise RuntimeError("الجلسة غير مصرح بها")

        me = await client.get_me()
        story_ids = await asyncio.wait_for(
            _story_ids_for_account(client, me),
            timeout=45,
        )
        for story_id in story_ids:
            try:
                await asyncio.wait_for(
                    client(
                        functions.stories.EditStoryRequest(
                            peer=me,
                            id=story_id,
                            privacy_rules=_public_story_privacy_rules(),
                        )
                    ),
                    timeout=30,
                )
                success += 1
                await asyncio.sleep(0.15)
            except Exception as exc:
                failed.append(f"#{story_id}: {str(exc)[:100]}")
        return len(story_ids), success, failed
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

async def _make_all_stories_public_job(
    bot,
    chat_id: int,
    accounts: list[dict],
    user_data: dict,
) -> None:
    """Process all stored accounts sequentially and send the owner a report."""
    account_success: list[str] = []
    account_failed: list[str] = []
    total_stories = 0
    public_stories = 0

    try:
        for index, account in enumerate(accounts, 1):
            label = account.get("phone_number") or f"الحساب رقم {index}"
            try:
                total, success, failures = await _make_account_stories_public(
                    account["session_string"]
                )
                total_stories += total
                public_stories += success
                if failures:
                    account_failed.append(
                        f"{label} — {success}/{total} نجحت: {'؛ '.join(failures[:3])}"
                    )
                else:
                    account_success.append(f"{label} — {success} ستوري")
            except Exception as exc:
                account_failed.append(f"{label} — {str(exc)[:120]}")
            await asyncio.sleep(0.4)

        lines = [
            "🌍 تقرير جعل الستوريات عامة",
            "",
            f"📦 الحسابات المعالجة: {len(accounts):,}",
            f"📖 إجمالي الستوريات التي تم العثور عليها: {total_stories:,}",
            f"✅ تم جعلها عامة: {public_stories:,}",
            f"❌ الحسابات التي لديها فشل: {len(account_failed):,}",
        ]
        if account_failed:
            lines.extend(["", "تفاصيل الفشل:"])
            lines.extend(f"• {item}" for item in account_failed[:25])
            if len(account_failed) > 25:
                lines.append(f"• ... و{len(account_failed) - 25:,} حساباً آخر")
        if not accounts:
            lines.append("\nلا توجد حسابات لديها جلسة صالحة.")

        await bot.send_message(
            chat_id,
            "\n".join(lines),
            reply_markup=account_info_kb(),
        )
    except Exception:
        logger.exception("❌ فشل تقرير جعل الستوريات عامة")
        await bot.send_message(
            chat_id,
            "❌ تعذر إكمال عملية جعل الستوريات عامة. راجع السجل وحاول مرة أخرى.",
            reply_markup=account_info_kb(),
        )
    finally:
        user_data.pop("make_stories_public_running", None)

def _clear_story_upload_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        "story_accounts",
        "story_index",
        "story_success",
        "story_failed",
    ):
        context.user_data.pop(key, None)
    context.user_data["state"] = "main_menu"

def _story_report_keyboard(has_more: bool) -> InlineKeyboardMarkup:
    if has_more:
        return story_upload_kb()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 عرض التقرير", callback_data="os:story_finish")],
    ])

def _probe_story_video(data: bytes) -> tuple[int, int, int]:
    """Return valid duration/width/height values for Telegram video stories."""
    fallback = (1, 720, 1280)
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,duration:format=duration",
                "-of", "json",
                "pipe:0",
            ],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=15,
        )
        payload = json.loads(probe.stdout.decode("utf-8"))
        stream = (payload.get("streams") or [{}])[0]
        raw_duration = stream.get("duration") or (payload.get("format") or {}).get("duration")
        duration = max(1, int(round(float(raw_duration or 0))))
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        return (duration, width, height) if width > 0 and height > 0 else fallback
    except (OSError, ValueError, TypeError, KeyError, IndexError, subprocess.SubprocessError):
        return fallback


async def _publish_account_story(
    session_string: str,
    media_bytes: bytes,
    file_name: str,
    mime_type: str | None = None,
    video_metadata: tuple[int, int, int] | None = None,
) -> None:
    """ينشر صورة أو فيديو كستوري في حساب تيليجرام مرتبط بجلسة مخزنة."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise RuntimeError("إعدادات Telegram API غير مكتملة")

    client = TelegramClient(
        StringSession(session_string),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            raise RuntimeError("الجلسة غير مصرح بها")
        uploaded = await asyncio.wait_for(
            client.upload_file(media_bytes, file_name=file_name),
            timeout=45,
        )
        media_mime = mime_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        if media_mime.startswith("image/"):
            media = InputMediaUploadedPhoto(file=uploaded)
        else:
            duration, width, height = video_metadata or _probe_story_video(media_bytes)
            media = InputMediaUploadedDocument(
                file=uploaded,
                mime_type=media_mime if media_mime.startswith("video/") else "video/mp4",
                attributes=[
                    DocumentAttributeVideo(
                        duration=duration,
                        w=width,
                        h=height,
                        supports_streaming=True,
                    )
                ],
            )
        await asyncio.wait_for(
            client(
                functions.stories.SendStoryRequest(
                    peer=await client.get_me(),
                    media=media,
                    # Stories created from Details → Stories → Publish Story
                    # must be public and pinned to the profile after expiry.
                    privacy_rules=_public_story_privacy_rules(),
                    pinned=True,
                    random_id=random.randint(-(1 << 63), (1 << 63) - 1),
                )
            ),
            timeout=45,
        )
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

async def _process_story_batch(
    owner_id: int,
    bot,
    chat_id: int,
    media_items: list[dict],
    user_data,
) -> None:
    """يعالج دفعة صور أو فيديوهات كستوريات على حسابات عشوائية بلا تكرار."""
    lock = _story_upload_locks.setdefault(owner_id, asyncio.Lock())
    async with lock:
        if user_data.get("state") != "os_story_upload":
            return

        accounts = user_data.get("story_accounts") or []
        index = int(user_data.get("story_index", 0) or 0)
        available = max(0, len(accounts) - index)
        if not available:
            await bot.send_message(
                chat_id,
                "ℹ️ انتهت الحسابات التي لديها جلسة. اضغط «إنهاء النشر» لرؤية التقرير.",
                reply_markup=story_upload_kb(),
            )
            return

        batch = media_items[:available]
        ignored = max(0, len(media_items) - len(batch))
        success = 0
        failed = 0

        for offset, item in enumerate(batch):
            account_index = index + offset
            account = accounts[account_index]
            label = account.get("phone_number") or f"الحساب رقم {account_index + 1}"
            stock_id = int(account["id"])
            if not _claim_media_account("stories", stock_id, account.get("phone_number")):
                user_data.setdefault("story_failed", []).append(
                    f"{label} — الحساب مستخدم مسبقاً في توزيع سابق"
                )
                failed += 1
                continue
            published = False
            try:
                tg_file = await bot.get_file(item["file_id"])
                media_bytes = bytes(await tg_file.download_as_bytearray())
                await _publish_account_story(
                    account["session_string"],
                    media_bytes,
                    item["file_name"],
                    item.get("mime_type"),
                    item.get("video_metadata"),
                )
                published = True
                _complete_media_account("stories", stock_id)
                user_data.setdefault("story_success", []).append(label)
                success += 1
            except Exception as exc:
                # إذا نُشرت الستوري ثم تعذر حفظ الحالة، نُبقي الحجز لمنع
                # إعادة النشر على الحساب نفسه في المحاولة التالية.
                if not published:
                    try:
                        _release_media_account("stories", stock_id)
                    except Exception as release_exc:
                        logger.error(f"❌ تعذر تحرير حجز الستوري للحساب {label}: {release_exc}")
                logger.warning(f"⚠️ فشل نشر الستوري على {label}: {exc}")
                user_data.setdefault("story_failed", []).append(
                    f"{label} — {str(exc)[:100]}"
                )
                failed += 1

        user_data["story_index"] = index + len(batch)
        _persist_upload_report("stories", user_data)
        remaining = max(0, len(accounts) - user_data["story_index"])
        result_lines = [
            f"✅ تمت معالجة الدفعة: {len(batch)} وسائط",
            f"🟢 نجح: {success} | 🔴 فشل: {failed}",
            "🎲 التوزيع عشوائي، والحسابات المستخدمة لا تتكرر.",
            f"📊 التقدم الكلي: {user_data['story_index']}/{len(accounts)}",
            f"👤 الحسابات المتبقية: {remaining}",
        ]
        if ignored:
            result_lines.append(
                f"⚠️ تم تجاهل {ignored} ملفات لأن عدد الملفات أكبر من الحسابات المتبقية."
            )
        if remaining:
            result_lines.append("أرسل الدفعة التالية، وسأكمل النشر من حسابات جديدة عشوائياً.")

        await bot.send_message(
            chat_id,
            "\n".join(result_lines),
            reply_markup=_story_report_keyboard(bool(remaining)),
        )

async def _flush_story_album(owner_id: int, media_group_id: str, bot) -> None:
    """ينتظر اكتمال ألبوم تيليجرام ثم ينشره كدفعة ستوريات."""
    try:
        await asyncio.sleep(1.5)
        key = (owner_id, media_group_id)
        entry = _story_album_buffers.pop(key, None)
        _story_album_tasks.pop(key, None)
        if not entry:
            return
        await _process_story_batch(
            owner_id,
            bot,
            entry["chat_id"],
            entry["media_items"],
            entry["user_data"],
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception(f"❌ خطأ في معالجة ألبوم الستوريات: {exc}")

async def handle_story_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يجمع الصور والفيديوهات ويدفعها إلى طابور نشر الستوريات."""
    if not update.message or update.effective_user is None:
        return
    if update.effective_user.id != OWNER_ID:
        return
    if context.user_data.get("state") != "os_story_upload":
        return

    message = update.message
    item = None
    if message.photo:
        photo = message.photo[-1]
        item = {
            "file_id": photo.file_id,
            "file_name": "story.jpg",
            "mime_type": "image/jpeg",
        }
    elif message.video:
        video = message.video
        item = {
            "file_id": video.file_id,
            "file_name": "story.mp4",
            "mime_type": video.mime_type or "video/mp4",
            "video_metadata": (
                max(1, int(video.duration or 0)),
                int(video.width or 0) or 720,
                int(video.height or 0) or 1280,
            ),
        }
    elif message.document:
        document = message.document
        file_name = document.file_name or "story.mp4"
        extension = os.path.splitext(file_name)[1].lower()
        mime_type = (document.mime_type or "").lower()
        if mime_type.startswith("video/") or extension in _STORY_VIDEO_EXTENSIONS:
            item = {
                "file_id": document.file_id,
                "file_name": file_name,
                "mime_type": mime_type or "video/mp4",
            }
    if item is None:
        await update.message.reply_text(
            "⚠️ أرسل صورة أو فيديو واضحًا فقط.",
            reply_markup=story_upload_kb(),
        )
        return

    media_group_id = message.media_group_id
    if not media_group_id:
        await _process_story_batch(
            update.effective_user.id,
            context.bot,
            update.effective_chat.id,
            [item],
            context.user_data,
        )
        return

    key = (update.effective_user.id, str(media_group_id))
    entry = _story_album_buffers.setdefault(
        key,
        {
            "media_items": [],
            "chat_id": update.effective_chat.id,
            "user_data": context.user_data,
        },
    )
    if not any(existing["file_id"] == item["file_id"] for existing in entry["media_items"]):
        entry["media_items"].append(item)
    if key not in _story_album_tasks:
        _story_album_tasks[key] = asyncio.create_task(
            _flush_story_album(update.effective_user.id, str(media_group_id), context.bot)
        )

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
        [InlineKeyboardButton("📱 شراء رقم بالنجوم", callback_data="exchange:number_stars")],
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
        active_filter = "" if _is_own_v else " AND active=1"
        svcs = c.execute(
            f"SELECT * FROM services WHERE category=%s AND platform=%s{active_filter}",
            (category, platform)
        ).fetchall()
    if not svcs and platform != 'tg':
        with db_conn() as c:
            svcs = c.execute(
                f"SELECT * FROM services WHERE category=%s "
                f"AND (platform=%s OR platform IS NULL){active_filter}",
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
        status = f" {'✅' if s['active'] else '❌'}" if _is_own_v else ""
        display_name = _arabic_only_service_name(s["name_ar"])
        rows.append([InlineKeyboardButton(f"{ico} {display_name}{status}", callback_data=f"svc:{s['id']}" )])
    # ==================== نهاية الدالة show_category_services ====================
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

# ⬇️ ⬇️ ⬇️ هنا تضع الدوال الجديدة (بعد نهاية الدالة) ⬇️ ⬇️ ⬇️
# لا تكرر تعريف show_category_services مرة أخرى!

def _load_unassigned_bio_accounts() -> list[dict]:
    """Load accounts that don't have a bio assigned yet."""
    with db_conn() as c:
        return c.execute(
            """
            SELECT ns.phone_number, ns.session_string
            FROM number_stock ns
            WHERE ns.deleted_at IS NULL
              AND ns.session_string IS NOT NULL
              AND BTRIM(ns.session_string) <> ''
              AND NOT EXISTS (
                  SELECT 1
                  FROM account_bio_assignments aba
                  WHERE aba.phone_number = ns.phone_number
              )
            ORDER BY ns.id
            """
        ).fetchall()

def _load_unassigned_username_accounts() -> list[dict]:
    """Load accounts that don't have a username assigned yet."""
    with db_conn() as c:
        return c.execute(
            """
            SELECT ns.phone_number, ns.session_string
            FROM number_stock ns
            WHERE ns.deleted_at IS NULL
              AND ns.session_string IS NOT NULL
              AND BTRIM(ns.session_string) <> ''
              AND NOT EXISTS (
                  SELECT 1
                  FROM account_username_assignments aua
                  WHERE aua.phone_number = ns.phone_number
              )
            ORDER BY ns.id
            """
        ).fetchall()

async def _apply_account_bio(phone: str, bio: str) -> None:
    """Apply a bio to a Telegram account."""
    with db_conn() as c:
        row = c.execute(
            """
            SELECT session_string
            FROM number_stock
            WHERE phone_number=%s
              AND deleted_at IS NULL
              AND session_string IS NOT NULL
              AND BTRIM(session_string) <> ''
            """,
            (phone,),
        ).fetchone()
    if not row:
        raise ValueError("الحساب غير موجود أو لا يملك جلسة صالحة")
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise RuntimeError("إعدادات Telegram API غير مكتملة")

    client = TelegramClient(
        StringSession(row["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            raise RuntimeError("الجلسة غير مصرح بها")
        await asyncio.wait_for(
            client(functions.account.UpdateProfileRequest(about=bio)),
            timeout=30,
        )
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    with db_conn() as c:
        c.execute(
            """
            INSERT INTO account_bio_assignments
                (phone_number, assigned_bio, assigned_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (phone_number) DO UPDATE SET
                assigned_bio=EXCLUDED.assigned_bio,
                assigned_at=NOW()
            """,
            (phone, bio),
        )

async def _apply_account_username(phone: str, username: str) -> None:
    """Apply a username to a Telegram account."""
    with db_conn() as c:
        row = c.execute(
            """
            SELECT session_string
            FROM number_stock
            WHERE phone_number=%s
              AND deleted_at IS NULL
              AND session_string IS NOT NULL
              AND BTRIM(session_string) <> ''
            """,
            (phone,),
        ).fetchone()
    if not row:
        raise ValueError("الحساب غير موجود أو لا يملك جلسة صالحة")
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise RuntimeError("إعدادات Telegram API غير مكتملة")

    client = TelegramClient(
        StringSession(row["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            raise RuntimeError("الجلسة غير مصرح بها")
        await asyncio.wait_for(
            client(functions.account.UpdateUsernameRequest(username=username)),
            timeout=30,
        )
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    with db_conn() as c:
        c.execute(
            """
            INSERT INTO account_username_assignments
                (phone_number, assigned_username, assigned_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (phone_number) DO UPDATE SET
                assigned_username=EXCLUDED.assigned_username,
                assigned_at=NOW()
            """,
            (phone, username),
        )

def _parse_generic_lines(raw_text: str) -> list[str]:
    """Parse a list of items (names, bios, usernames) from text, one per line."""
    parsed = []
    for raw_line in raw_text.splitlines():
        item = raw_line.strip()
        if not item:
            continue
        parsed.append(item[:128])
    return parsed
