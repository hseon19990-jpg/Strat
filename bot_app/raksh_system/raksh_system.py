"""Public compatibility facade for the modular raksh services."""

from .common import *
from .story import StoryService
from .forced_ref import ForcedRefService
from .forced_ref_ai import ForcedRefAIService
from .comment import CommentService
from .poll import PollService
from .votes import VotesService
from .votes_ai import VotesAIService
from .premium_reaction import PremiumReactionService

# ═══ 9. تسجيل الخدمات ═══
# ════════════════════════════════════════════════════════

RAKSH_SERVICES: Dict[str, RakshService] = {
    StoryService.service_type: StoryService(),
    ForcedRefService.service_type: ForcedRefService(),
    ForcedRefAIService.service_type: ForcedRefAIService(),
    CommentService.service_type: CommentService(),
    PollService.service_type: PollService(),
    VotesService.service_type: VotesService(),
    VotesAIService.service_type: VotesAIService(),
    PremiumReactionService.service_type: PremiumReactionService(),
}

RAKSH_SERVICE_LABELS = {
    svc_type: svc.label for svc_type, svc in RAKSH_SERVICES.items()
}

# ════════════════════════════════════════════════════════
# ═══ 10. دوال مساعدة عامة ═══
# ════════════════════════════════════════════════════════

def get_raksh_service(service_type: str) -> Optional[RakshService]:
    """الحصول على الخدمة"""
    return RAKSH_SERVICES.get(service_type)

def get_raksh_price_config(service_type: str) -> Dict[str, int]:
    """إرجاع إعدادات الأسعار"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.get_price_config()
    return {}

def get_raksh_total(service_type: str, quantity: int, payment_method: str) -> int:
    """حساب السعر"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.get_total(quantity, payment_method)
    return 0

def _raksh_rate_text(service_type: str, payment_method: str) -> str:
    """نص عرض السعر"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.get_rate_text(payment_method)
    return ""

def _raksh_order_label(service_type: str) -> str:
    """اسم مختصر للطلب"""
    svc = get_raksh_service(service_type)
    return svc.label if svc else service_type

def _get_delay_seconds(service_type: str, custom_delay: Optional[int] = None) -> int:
    """حساب الفاصل الزمني بين التنفيذات"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.get_delay_seconds(custom_delay)
    return random.randint(RAKSH_MIN_DELAY_SECONDS, RAKSH_MAX_DELAY_SECONDS)

def get_raksh_hourly_remaining(user_id: int) -> int:
    """عدد التنفيذات المتبقية خلال الساعة"""
    if RAKSH_MAX_EXECUTIONS_PER_HOUR <= 0:
        return 2_147_483_647
    try:
        with db_conn() as c:
            row = c.execute(
                """
                SELECT COUNT(*) AS used
                FROM raksh_execution_usage
                WHERE user_id=%s
                  AND executed_at >= NOW() - INTERVAL '1 hour'
                """,
                (user_id,),
            ).fetchone()
        used = int(row["used"] or 0) if row else 0
        return max(0, RAKSH_MAX_EXECUTIONS_PER_HOUR - used)
    except Exception:
        logger.exception(f"فشل قراءة حد التنفيذ للمستخدم {user_id}")
        return 0

def get_raksh_daily_remaining(user_id: int) -> int:
    """عدد التنفيذات المتبقية خلال اليوم"""
    try:
        with db_conn() as c:
            row = c.execute(
                """
                SELECT COUNT(*) AS used
                FROM raksh_execution_usage
                WHERE user_id=%s
                  AND executed_at >= NOW() - INTERVAL '1 day'
                """,
                (user_id,),
            ).fetchone()
        used = int(row["used"] or 0) if row else 0
        return max(0, RAKSH_MAX_EXECUTIONS_PER_DAY - used)
    except Exception:
        return RAKSH_MAX_EXECUTIONS_PER_DAY

def _reserve_raksh_execution_slot(user_id: int, service_type: str, phone_number: str) -> bool:
    """حجز تنفيذ واحد"""
    if RAKSH_MAX_EXECUTIONS_PER_HOUR <= 0 and RAKSH_MAX_EXECUTIONS_PER_DAY <= 0:
        return True
    try:
        with db_conn() as c:
            c.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"raksh-hourly:{user_id}",),
            )
            
            if RAKSH_MAX_EXECUTIONS_PER_DAY > 0:
                row = c.execute(
                    """
                    SELECT COUNT(*) AS used
                    FROM raksh_execution_usage
                    WHERE user_id=%s
                      AND executed_at >= NOW() - INTERVAL '1 day'
                    """,
                    (user_id,),
                ).fetchone()
                if row and int(row["used"] or 0) >= RAKSH_MAX_EXECUTIONS_PER_DAY:
                    return False
            
            if RAKSH_MAX_EXECUTIONS_PER_HOUR > 0:
                row = c.execute(
                    """
                    SELECT COUNT(*) AS used
                    FROM raksh_execution_usage
                    WHERE user_id=%s
                      AND executed_at >= NOW() - INTERVAL '1 hour'
                    """,
                    (user_id,),
                ).fetchone()
                if row and int(row["used"] or 0) >= RAKSH_MAX_EXECUTIONS_PER_HOUR:
                    return False
            
            c.execute(
                """
                INSERT INTO raksh_execution_usage
                    (user_id, service_type, phone_number)
                VALUES (%s, %s, %s)
                """,
                (user_id, service_type, phone_number),
            )
        return True
    except Exception:
        logger.exception(f"فشل حجز تنفيذ للمستخدم {user_id}")
        return False

# ════════════════════════════════════════════════════════
# ═══ 11. مدير التنفيذ ═══
# ════════════════════════════════════════════════════════

async def execute_raksh_service(
    service_type: str,
    quantity: int,
    sessions: List[Dict],
    params: Dict,
    user_id: int,
    progress_callback=None,
) -> Tuple[int, List[str], List[str], List[str], List[str]]:
    """تنفيذ طلب رشق"""
    if not sessions:
        raise RuntimeError("لا توجد جلسات نشطة متاحة")
    
    svc = get_raksh_service(service_type)
    if not svc:
        raise RuntimeError(f"خدمة غير معروفة: {service_type}")
    
    max_concurrent = svc.config.max_concurrent
    
    shuffled = sessions.copy()
    random.shuffle(shuffled)
    
    success_count = 0
    success_phones = []
    success_details = []
    failed_phones = []
    failed_details = []
    used_phones = set()
    
    if max_concurrent == 1 or service_type in {"votes_ai", "forced_ref", "forced_ref_ai"}:
        if service_type == "votes_ai":
            async with _RAKSH_VOTE_FLOW_LOCK:
                return await _execute_raksh_sequential(
                    svc, shuffled, params, user_id,
                    quantity, progress_callback, service_type
                )
        
        return await _execute_raksh_sequential(
            svc, shuffled, params, user_id,
            quantity, progress_callback, service_type
        )
    
    return await _execute_raksh_parallel(
        svc, shuffled, params, user_id,
        quantity, progress_callback, service_type, max_concurrent
    )

async def _execute_raksh_sequential(
    svc: RakshService,
    sessions: List[Dict],
    params: Dict,
    user_id: int,
    quantity: int,
    progress_callback,
    service_type: str,
) -> Tuple[int, List[str], List[str], List[str], List[str]]:
    """تنفيذ الخدمات بشكل تسلسلي"""
    success_count = 0
    success_phones = []
    success_details = []
    failed_phones = []
    failed_details = []
    used_phones = set()
    
    for i in range(quantity):
        if not sessions:
            break
        session = sessions.pop(0)
        phone = session["phone_number"]
        if phone in used_phones:
            continue
        used_phones.add(phone)
        
        if not _reserve_raksh_execution_slot(user_id, service_type, phone):
            failed_phones.append(phone)
            failed_details.append("تم تجاوز حد التنفيذ")
            continue
        
        session_lock = _get_raksh_session_lock(phone)
        if session_lock.locked():
            failed_phones.append(phone)
            failed_details.append("الجلسة قيد الاستخدام")
            continue
        
        async with session_lock:
            try:
                ok, msg = await svc.execute(
                    session=session,
                    params=params,
                    is_first=(i == 0),
                )
            except Exception as e:
                ok = False
                msg = f"❌ خطأ: {str(e)}"
        
        if ok:
            success_count += 1
            success_phones.append(phone)
            success_details.append(msg)
        else:
            failed_phones.append(phone)
            failed_details.append(msg)
        
        if progress_callback:
            await progress_callback(i + 1, quantity, success_count, len(failed_details))
        
        if i < quantity - 1 and sessions:
            delay = svc.get_delay_seconds(params.get("delay_seconds"))
            await asyncio.sleep(delay)
    
    await _remove_invalid_raksh_sessions(failed_phones)
    return success_count, success_phones, success_details, failed_phones, failed_details

async def _execute_raksh_parallel(
    svc: RakshService,
    sessions: List[Dict],
    params: Dict,
    user_id: int,
    quantity: int,
    progress_callback,
    service_type: str,
    max_concurrent: int,
) -> Tuple[int, List[str], List[str], List[str], List[str]]:
    """تنفيذ الخدمات بشكل متوازي"""
    success_count = 0
    success_phones = []
    success_details = []
    failed_phones = []
    failed_details = []
    used_phones = set()
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def execute_one(session, index):
        nonlocal success_count
        phone = session["phone_number"]
        if phone in used_phones:
            return
        used_phones.add(phone)
        
        if not _reserve_raksh_execution_slot(user_id, service_type, phone):
            failed_phones.append(phone)
            failed_details.append("تم تجاوز حد التنفيذ")
            return
        
        session_lock = _get_raksh_session_lock(phone)
        if session_lock.locked():
            failed_phones.append(phone)
            failed_details.append("الجلسة قيد الاستخدام")
            return
        
        async with session_lock:
            try:
                ok, msg = await svc.execute(
                    session=session,
                    params=params,
                    is_first=(index == 0),
                )
            except Exception as e:
                ok = False
                msg = f"❌ خطأ: {str(e)}"
        
        if ok:
            success_count += 1
            success_phones.append(phone)
            success_details.append(msg)
        else:
            failed_phones.append(phone)
            failed_details.append(msg)
        
        if progress_callback:
            await progress_callback(index + 1, quantity, success_count, len(failed_details))
    
    tasks = []
    for i, session in enumerate(sessions[:quantity]):
        if session["phone_number"] in used_phones:
            continue
        tasks.append(execute_one(session, i))
    
    await asyncio.gather(*tasks)
    await _remove_invalid_raksh_sessions(failed_phones)
    return success_count, success_phones, success_details, failed_phones, failed_details

# ════════════════════════════════════════════════════════
# ═══ 12. واجهات المستخدم ═══
# ════════════════════════════════════════════════════════

def _is_raksh_service_enabled(service_type: str) -> bool:
    """التحقق من تفعيل الخدمة"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.is_enabled()
    return False

def _set_raksh_service_enabled(service_type: str, enabled: bool) -> None:
    """تفعيل/إخفاء خدمة"""
    svc = get_raksh_service(service_type)
    if svc:
        svc.set_enabled(enabled)

def raksh_menu_kb(is_owner: bool = False):
    """قائمة الخدمات"""
    buttons = []
    for key, svc in RAKSH_SERVICES.items():
        if not is_owner and not svc.is_enabled():
            continue
        service_button = InlineKeyboardButton(
            svc.config.name, callback_data=f"raksh:start:{key}"
        )
        if is_owner:
            enabled = svc.is_enabled()
            buttons.append([
                service_button,
                InlineKeyboardButton(
                    "✅ مفعلة" if enabled else "🚫 مخفية",
                    callback_data=f"raksh:toggle:{key}",
                ),
            ])
        else:
            buttons.append([service_button])
    
    if is_owner:
        buttons.append([
            InlineKeyboardButton(
                f"🔥 إدارة {get_raksh_accounts_label()}",
                callback_data="os:raksh_accounts",
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                "⚙️ إدارة الأسعار",
                callback_data="raksh:settings",
            )
        ])
    
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def raksh_price_settings_kb():
    """أزرار إدارة الأسعار"""
    rows = []
    for service_type, svc in RAKSH_SERVICES.items():
        config = svc.get_price_config()
        rows.append([
            InlineKeyboardButton(
                f"{svc.label}: ⭐ {config['stars_price']}/{config['stars_quantity']} | "
                f"💰 {config['points_price']}/{config['points_quantity']}",
                callback_data=f"raksh:price:{service_type}",
            )
        ])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
    return InlineKeyboardMarkup(rows)

def raksh_payment_kb(service_type: str, quantity: int, points_cost: int, stars_cost: int):
    """أزرار الدفع"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"⭐ دفع بالنجوم ({stars_cost} نجمة)",
                callback_data=f"raksh:pay:stars:{service_type}:{quantity}"
            )
        ],
        [
            InlineKeyboardButton(
                f"💰 دفع بالنقاط ({points_cost} نقطة)",
                callback_data=f"raksh:pay:points:{service_type}:{quantity}"
            )
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data="raksh_menu")],
    ])

def raksh_channel_kb():
    """أزرار تخطي القنوات"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭️ تخطي (بدون قنوات)", callback_data="raksh:skip_channels")],
        [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")],
    ])

def raksh_reaction_kb(service_type: str, reactions: Optional[List[str]] = None):
    """أزرار التفاعلات"""
    buttons = []
    row = []
    
    if reactions:
        reaction_items = [(r, r) for r in reactions]
    else:
        reaction_items = list(RAKSH_REACTIONS.items())
    
    for index, (reaction_key, reaction) in enumerate(reaction_items, start=1):
        if reaction == RAKSH_PAID_REACTION:
            callback_key = "paid"
            reaction_label = RAKSH_PAID_REACTION_LABEL
        elif _custom_reaction_document_id(reaction) is not None:
            callback_key = f"custom_{_custom_reaction_document_id(reaction)}"
            reaction_label = f"🎨 تفاعل مميز {index}"
        else:
            callback_key = reaction_key if reaction_key in RAKSH_REACTIONS else str(index)
            reaction_label = reaction
        
        row.append(
            InlineKeyboardButton(
                reaction_label,
                callback_data=f"raksh:reaction:{service_type}:{callback_key}",
            )
        )
        if len(row) == 4:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    buttons.append([
        InlineKeyboardButton(
            "🎲 عشوائي",
            callback_data=f"raksh:reaction:{service_type}:random"
        )
    ])
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="raksh_menu")])
    return InlineKeyboardMarkup(buttons)

def raksh_confirm_kb(service_type: str, quantity: int, total_cost: int, payment_method: str):
    """أزرار تأكيد الطلب"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ تأكيد الطلب",
                callback_data=f"raksh:confirm:{service_type}:{quantity}:{total_cost}:{payment_method}"
            )
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data="raksh_cancel")],
    ])

def _get_link_instruction(service_type: str) -> str:
    """تعليمات الرابط حسب الخدمة"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.get_link_instruction()
    return "أرسل الرابط المطلوب"

def _parse_raksh_rate_updates(text: str) -> Dict[str, Tuple[int, int]]:
    """قراءة تحديثات الأسعار"""
    updates = {}
    for line in (text or "").splitlines():
        normalized = line.casefold().strip()
        numbers = re.findall(r"\d+", normalized)
        if len(numbers) < 2:
            continue
        price, bundle_quantity = int(numbers[0]), int(numbers[1])
        if price < 1 or bundle_quantity < 1:
            continue
        if "نج" in normalized or "star" in normalized:
            updates["stars"] = (price, bundle_quantity)
        elif "نق" in normalized or "point" in normalized:
            updates["points"] = (price, bundle_quantity)
    return updates

def _raksh_link_error(service_type: str, value: str) -> Optional[str]:
    """التحقق من صحة الرابط"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.validate_link(value)
    return "⚠️ خدمة غير معروفة"

def _get_max_quantity(service_type: str) -> int:
    """الحد الأقصى للكمية"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.get_max_quantity()
    return 0

def _get_request_limit(user_id: int, service_type: str) -> int:
    """الحد الفعلي للطلب"""
    svc = get_raksh_service(service_type)
    if svc:
        return svc.get_request_limit(user_id)
    return 0

def _chunk_lines(lines: List[str], max_chars: int = 3500) -> List[str]:
    """تقسيم القوائم الطويلة"""
    chunks = []
    current = []
    current_length = 0
    for line in lines:
        line_length = len(line) + 1
        if current and current_length + line_length > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_length = 0
        current.append(line)
        current_length += line_length
    if current:
        chunks.append("\n".join(current))
    return chunks

# ════════════════════════════════════════════════════════
# ═══ 13. المعالج الرئيسي للأزرار ═══
# ════════════════════════════════════════════════════════

async def handle_raksh_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query=None,
    data=None,
    user=None,
    is_own=None,
):
    """معالج أزرار الرشق الرئيسي"""
    query = query or update.callback_query
    data = query.data if data is None else data
    user = user or query.from_user
    is_own = (user.id == OWNER_ID) if is_own is None else is_own
    
    await query.answer()
    
    # ─── تفعيل/إخفاء خدمة ───
    if data.startswith("raksh:toggle:"):
        if not is_own:
            await query.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
            return
        service_type = data.split(":", 2)[2]
        if service_type not in RAKSH_SERVICES:
            await query.answer("⚠️ الخدمة غير موجودة.", show_alert=True)
            return
        svc = RAKSH_SERVICES[service_type]
        enabled = not svc.is_enabled()
        svc.set_enabled(enabled)
        await query.edit_message_text(
            f"🔥 *إدارة {md_escape(get_raksh_accounts_label())}*\n\n"
            "✅ مفعلة: تظهر للأعضاء\n"
            "🚫 مخفية: لا تظهر للأعضاء\n\n"
            f"📊 الحسابات المتاحة: *{get_available_sessions_count()}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_menu_kb(True),
        )
        return
    
    # ─── إدارة الأسعار ───
    if data == "raksh:settings":
        if not is_own:
            await query.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
            return
        await query.edit_message_text(
            "⚙️ *إعدادات أسعار خدمات الرشق*\n\n"
            "اضغط على الخدمة، ثم أرسل السعرين بصيغة:\n"
            "⭐ `نجوم 1 لكل 10`\n"
            "💰 `نقاط 30 لكل 1`\n\n"
            "أي سطر ترسله سيحدّث الطريقة المذكورة فيه.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_price_settings_kb(),
        )
        return
    
    # ─── تعديل سعر خدمة ───
    if data.startswith("raksh:price:"):
        if not is_own:
            await query.answer("⛔ هذا الخيار للمالك فقط.", show_alert=True)
            return
        service_type = data.split(":")[2]
        if service_type not in RAKSH_SERVICES:
            await query.answer("⚠️ الخدمة غير موجودة.", show_alert=True)
            return
        svc = RAKSH_SERVICES[service_type]
        config = svc.get_price_config()
        context.user_data["raksh_price_edit_service"] = service_type
        context.user_data["raksh_step"] = "admin_price"
        await query.edit_message_text(
            f"✏️ *تعديل سعر {svc.label}*\n\n"
            f"⭐ الحالي: {config['stars_price']} نجمة لكل {config['stars_quantity']}\n"
            f"💰 الحالي: {config['points_price']} نقطة لكل {config['points_quantity']}\n\n"
            "أرسل سطراً أو سطرين بهذا الشكل:\n"
            "`نجوم 1 لكل 10`\n"
            "`نقاط 30 لكل 1`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع للأسعار", callback_data="raksh:settings")]
            ]),
        )
        return
    
    # ─── القائمة الرئيسية ───
    if data in {"raksh_menu", "raksh_cancel"}:
        _clear_raksh_state(context)
        if data == "raksh_cancel":
            await query.edit_message_text(
                "🏠 *القائمة الرئيسية*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(is_own),
            )
            return
        await query.edit_message_text(
            f"🔥 *{md_escape(get_raksh_accounts_label())}*\n\n"
            "اختر الخدمة المطلوبة:\n"
            f"📊 الحسابات المتاحة: *{get_available_sessions_count()}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_menu_kb(is_own)
        )
        return
    
    # ─── بدء خدمة ───
    if data.startswith("raksh:start:"):
        service_type = data.split(":")[2]
        svc = RAKSH_SERVICES.get(service_type)
        if not svc:
            await query.edit_message_text(
                "⚠️ خدمة غير موجودة.",
                reply_markup=raksh_menu_kb(is_own),
            )
            return
        if not is_own and not svc.is_enabled():
            await query.edit_message_text(
                "⚠️ هذه الخدمة مخفية حالياً.",
                reply_markup=raksh_menu_kb(False),
            )
            return
        
        _clear_raksh_state(context)
        context.user_data["raksh_service"] = service_type
        context.user_data["raksh_step"] = svc.get_initial_state()
        
        await query.edit_message_text(
            svc.get_start_message(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=svc.get_start_keyboard()
        )
        return
    
    # ─── تخطي القنوات ───
    if data == "raksh:skip_channels":
        context.user_data["raksh_channels"] = []
        context.user_data["raksh_step"] = "link"
        svc = RAKSH_SERVICES.get(context.user_data.get("raksh_service"))
        await query.edit_message_text(
            f"✅ تم تخطي القنوات.\n\n"
            f"🔗 *أرسل الرابط المطلوب:*\n"
            f"{_get_link_instruction(context.user_data.get('raksh_service'))}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
            ])
        )
        return
    
    # ─── اختيار تفاعل ───
    if data.startswith("raksh:reaction:"):
        parts = data.split(":")
        service_type = parts[2]
        reaction_key = parts[3]
        
        if reaction_key == "paid":
            reaction = RAKSH_PAID_REACTION
        elif reaction_key.startswith("custom_") and reaction_key[7:].isdigit():
            reaction = f"{RAKSH_CUSTOM_REACTION_PREFIX}{reaction_key[7:]}"
        else:
            reaction = RAKSH_REACTIONS.get(reaction_key, reaction_key)
        
        if service_type == "premium_reaction":
            available_reactions = context.user_data.get("raksh_available_reactions") or []
            if reaction_key == "random":
                reaction = "random"
            elif available_reactions and reaction not in available_reactions:
                await query.answer("⚠️ هذا التفاعل غير متاح في المنشور.", show_alert=True)
                return
        
        context.user_data["raksh_reaction"] = reaction
        context.user_data["raksh_step"] = "quantity"
        
        reaction_label = (
            RAKSH_PAID_REACTION_LABEL
            if reaction == RAKSH_PAID_REACTION
            else reaction
        )
        
        await query.edit_message_text(
            f"✅ تم اختيار التفاعل: {reaction_label}\n\n"
            f"🔢 *أرسل عدد الوحدات المطلوبة:*\n"
            f"(الحد الأقصى: {_get_max_quantity(service_type)})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="raksh_menu")]
            ])
        )
        return
    
    # ─── تمرير للخدمة المحددة ───
    # كل خدمة تفحص إذا كانت الأزرار تخصها
    for service_type, svc in RAKSH_SERVICES.items():
        prefix = f"raksh_{service_type}:"
        if data.startswith(prefix):
            parts = data[len(prefix):].split(":")
            handled = await svc.handle_callback(update, context, query, parts, user, is_own)
            if handled:
                return
    
    # ─── اختيار طريقة الدفع (الافتراضي) ───
    if data.startswith("raksh:pay:"):
        parts = data.split(":")
        if len(parts) != 5 or parts[2] not in {"stars", "points"}:
            await query.answer("⚠️ بيانات الدفع غير صالحة.", show_alert=True)
            return
        method = parts[2]
        service_type = parts[3]
        try:
            quantity = int(parts[4])
        except ValueError:
            await query.answer("⚠️ العدد غير صالح.", show_alert=True)
            return
        
        svc = RAKSH_SERVICES.get(service_type)
        if not svc or quantity < 1:
            await query.answer("⚠️ الخدمة أو العدد غير صالح.", show_alert=True)
            return
        
        request_limit = _get_request_limit(user.id, service_type)
        if quantity > request_limit:
            await query.answer(
                "⚠️ لا يمكن قبول هذا العدد حالياً. الحد المتاح: "
                f"{request_limit} وحدة.",
                show_alert=True,
            )
            return
        
        context.user_data["raksh_payment_method"] = method
        context.user_data["raksh_step"] = "payment_confirm"
        
        if method == "stars":
            total = svc.get_total(quantity, "stars")
            await query.edit_message_text(
                f"⭐ *الدفع بالنجوم*\n\n"
                f"الخدمة: {svc.config.name}\n"
                f"العدد: {quantity}\n"
                f"التكلفة: *{total} نجمة*\n\n"
                "اضغط تأكيد للمتابعة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=raksh_confirm_kb(service_type, quantity, total, "stars")
            )
        else:
            total = svc.get_total(quantity, "points")
            db_user = get_user(user.id)
            points = db_user["points"] if db_user else 0
            await query.edit_message_text(
                f"💰 *الدفع بالنقاط*\n\n"
                f"الخدمة: {svc.config.name}\n"
                f"العدد: {quantity}\n"
                f"التكلفة: *{total} نقطة*\n"
                f"رصيدك: *{points} نقطة*\n\n"
                "اضغط تأكيد للمتابعة:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=raksh_confirm_kb(service_type, quantity, total, "points")
            )
        return
    
    # ─── تأكيد الطلب (الافتراضي) ───
    if data.startswith("raksh:confirm:"):
        parts = data.split(":")
        if len(parts) != 6:
            await query.answer("⚠️ بيانات التأكيد غير صالحة.", show_alert=True)
            return
        service_type = parts[2]
        try:
            quantity = int(parts[3])
            button_total = int(parts[4])
        except ValueError:
            await query.answer("⚠️ العدد أو السعر غير صالح.", show_alert=True)
            return
        payment_method = parts[5]
        
        if service_type not in RAKSH_SERVICES or payment_method not in {"points", "stars"}:
            await query.answer("⚠️ بيانات الطلب غير صالحة.", show_alert=True)
            return
        
        if quantity > _get_request_limit(user.id, service_type):
            await query.edit_message_text(
                "⚠️ لا يمكن قبول هذا الطلب حالياً. حاول لاحقاً.",
                reply_markup=raksh_menu_kb(is_own),
            )
            return
        
        total_cost = get_raksh_total(service_type, quantity, payment_method)
        if button_total != total_cost:
            logger.info(f"تحديث سعر الرشق: {service_type} {quantity}")
        
        if payment_method == "points":
            if not deduct_points(user.id, total_cost):
                current_user = get_user(user.id)
                if current_user and current_user.get("referral_points_blocked"):
                    error_text = (
                        "🔒 *تم إيقاف استخدام النقاط في حسابك مؤقتاً.*\n\n"
                        "تواصل مع الدعم لمراجعة حالة الإحالات وإعادة تفعيل الرصيد."
                    )
                else:
                    error_text = "❌ *نقاطك غير كافية!*"
                await query.edit_message_text(
                    error_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=raksh_menu_kb(is_own)
                )
                return
        else:
            # الدفع بالنجوم
            svc = RAKSH_SERVICES.get(service_type)
            total_stars = get_raksh_total(service_type, quantity, "stars")
            await query.edit_message_text(
                "⭐ *جاري تجهيز فاتورة الدفع بالنجوم...*",
                parse_mode=ParseMode.MARKDOWN,
            )
            await context.bot.send_invoice(
                chat_id=user.id,
                title=svc.config.name,
                description=f"{quantity} وحدة | {total_stars} نجمة",
                payload=f"raksh_stars:{user.id}:{service_type}:{quantity}:{total_stars}",
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice("خدمة الرشق", total_stars)],
            )
            return
        
        await _start_raksh_execution(
            update, context, query, service_type, quantity, payment_method, total_cost
        )
        return

# ════════════════════════════════════════════════════════
# ═══ 14. المعالج الرئيسي للنصوص ═══
# ════════════════════════════════════════════════════════

async def handle_raksh_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج النصوص للرشق الرئيسي"""
    user = update.effective_user
    text = update.message.text
    state = context.user_data.get("raksh_step")
    service_type = context.user_data.get("raksh_service")
    
    if not state:
        return False
    
    # ─── تعديل الأسعار (للمالك) ───
    if state == "admin_price":
        if user.id != OWNER_ID:
            _clear_raksh_state(context)
            return False
        service_type = context.user_data.get("raksh_price_edit_service")
        if service_type not in RAKSH_SERVICES:
            _clear_raksh_state(context)
            await update.message.reply_text("⚠️ انتهت جلسة تعديل الأسعار.")
            return True
        
        updates = _parse_raksh_rate_updates(text)
        if not updates:
            await update.message.reply_text(
                "⚠️ لم أفهم الصيغة.\n"
                "استخدم مثلاً:\n"
                "⭐ نجوم 1 لكل 10\n"
                "💰 نقاط 30 لكل 1",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع للأسعار", callback_data="raksh:settings")]
                ]),
            )
            return True
        
        svc = RAKSH_SERVICES[service_type]
        keys = svc.get_price_keys()
        if "stars" in updates:
            price, bundle_quantity = updates["stars"]
            set_setting(keys["stars_price"], str(price))
            set_setting(keys["stars_quantity"], str(bundle_quantity))
        if "points" in updates:
            price, bundle_quantity = updates["points"]
            set_setting(keys["points_price"], str(price))
            set_setting(keys["points_quantity"], str(bundle_quantity))
        
        config = svc.get_price_config()
        await update.message.reply_text(
            f"✅ تم حفظ أسعار {svc.label}.\n\n"
            f"⭐ {config['stars_price']} نجمة لكل {config['stars_quantity']}\n"
            f"💰 {config['points_price']} نقطة لكل {config['points_quantity']}\n\n"
            "يمكنك إرسال تعديل آخر أو اختيار خدمة أخرى.",
            reply_markup=raksh_price_settings_kb(),
        )
        return True
    
    # ─── القنوات ───
    if state == "channel":
        channel_refs = _parse_channel_refs(text)
        if text.strip() and not channel_refs:
            await update.message.reply_text(
                "⚠️ لم أتعرف على أي قناة.\n"
                "أرسل @username أو رابط t.me للقناة، ويمكنك إرسال أكثر من قناة مفصولة بمسافة أو سطر.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
                ]),
            )
            return True
        
        context.user_data["raksh_channels"] = channel_refs
        context.user_data["raksh_step"] = "link"
        service_type = context.user_data.get("raksh_service")
        
        await update.message.reply_text(
            f"✅ تم حفظ القنوات.\n\n"
            f"🔗 *أرسل الرابط المطلوب:*\n"
            f"{_get_link_instruction(service_type)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 إلغاء", callback_data="raksh_cancel")]
            ])
        )
        return True
    
    # ─── الرابط (الافتراضي لجميع الخدمات) ───
    if state == "link":
        svc = RAKSH_SERVICES.get(service_type)
        if not svc:
            return False
        
        # تمرير للخدمة المحددة
        handled = await svc.handle_text(update, context, text, user, state, user.id == OWNER_ID)
        if handled:
            return True
        
        return False
    
    # ─── تمرير لبقية الحالات للخدمة المحددة ───
    if service_type and service_type in RAKSH_SERVICES:
        svc = RAKSH_SERVICES[service_type]
        handled = await svc.handle_text(update, context, text, user, state, user.id == OWNER_ID)
        if handled:
            return True
    
    return False

# ════════════════════════════════════════════════════════
# ═══ 15. معالجات الدفع ═══
# ════════════════════════════════════════════════════════

async def raksh_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التحقق من الدفع بالنجوم"""
    query = update.pre_checkout_query
    payload = query.invoice_payload
    
    if payload.startswith("raksh_stars:"):
        parts = payload.split(":")
        user_id = int(parts[1])
        service_type = parts[2]
        quantity = int(parts[3])
        total_stars = int(parts[4])
        
        if (
            query.from_user.id == user_id
            and query.total_amount == total_stars
            and quantity <= _get_request_limit(user_id, service_type)
        ):
            await query.answer(ok=True)
            return
    
    await query.answer(ok=False, error_message="حدث خطأ في التحقق من الدفع.")

async def raksh_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الدفع الناجح"""
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    
    if payload.startswith("raksh_stars:"):
        parts = payload.split(":")
        user_id = int(parts[1])
        service_type = parts[2]
        quantity = int(parts[3])
        total_stars = int(parts[4])
        
        if update.effective_user.id != user_id:
            return
        
        if quantity > _get_request_limit(user_id, service_type):
            try:
                await context.bot.refund_star_payment(
                    user_id=user_id,
                    telegram_payment_charge_id=payment.telegram_payment_charge_id,
                )
                await update.message.reply_text(
                    "⚠️ تعذر بدء الطلب حالياً، وتمت إعادة قيمة الدفع.",
                    reply_markup=raksh_menu_kb(user_id == OWNER_ID),
                )
            except Exception:
                logger.exception(f"فشل إعادة دفع النجوم للمستخدم {user_id}")
                await update.message.reply_text(
                    "⚠️ تعذر بدء الطلب حالياً. تواصل مع المالك.",
                    reply_markup=raksh_menu_kb(user_id == OWNER_ID),
                )
            return
        
        context.user_data["raksh_service"] = service_type
        context.user_data["raksh_quantity"] = quantity
        context.user_data["raksh_payment_method"] = "stars"
        
        await update.message.reply_text(
            "✅ *تم تأكيد الدفع بالنجوم!*\n\n"
            "⏳ جاري بدء التنفيذ...",
            parse_mode=ParseMode.MARKDOWN
        )
        await _start_raksh_execution(
            update,
            context,
            query=None,
            service_type=service_type,
            quantity=quantity,
            payment_method="stars",
            total_cost=total_stars,
            progress_message=await update.message.reply_text(
                "⏳ *يتم تشغيل الحسابات النشطة الآن...*",
                parse_mode=ParseMode.MARKDOWN,
            ),
        )

# ════════════════════════════════════════════════════════
# ═══ 16. تنفيذ الطلب ═══
# ════════════════════════════════════════════════════════

async def _send_raksh_order_to_group(bot, user_id: int, quantity: int, payment_method: str, service_type: str):
    """إرسال إشعار الطلب إلى المجموعة"""
    if not ADMIN_GROUP_ID:
        return
    try:
        await bot.send_message(
            ADMIN_GROUP_ID,
            f"📋 طلب {_raksh_order_label(service_type)}\n"
            f"👤 المستخدم: {user_id}\n"
            f"📦 العدد: {quantity}\n"
            f"💳 طريقة الدفع: {payment_method}",
        )
    except Exception:
        logger.exception("فشل إرسال إشعار الطلب")

async def _send_raksh_owner_result(
    bot,
    service_type: str,
    quantity: int,
    success_phones: List[str],
    failed_phones: List[str],
    failed_details: List[str],
):
    """إرسال النتيجة للمالك"""
    if not OWNER_ID:
        return
    try:
        lines = [
            f"📊 نتيجة {_raksh_order_label(service_type)}",
            f"📦 المطلوب: {quantity}",
            f"✅ الناجح: {len(success_phones)}",
            f"❌ الفاشل: {len(failed_phones)}",
            "",
        ]
        
        if success_phones:
            lines.append("✅ الناجحين:")
            lines.extend(f"• {p}" for p in success_phones[:20])
            if len(success_phones) > 20:
                lines.append(f"... و{len(success_phones)-20} أخرى")
        
        if failed_phones:
            lines.append("")
            lines.append("❌ الفاشلين:")
            for idx, phone in enumerate(failed_phones[:10]):
                detail = failed_details[idx] if idx < len(failed_details) else "فشل"
                lines.append(f"• {phone} — {detail[:50]}")
            if len(failed_phones) > 10:
                lines.append(f"... و{len(failed_phones)-10} أخرى")
        
        for chunk in _chunk_lines(lines):
            await bot.send_message(OWNER_ID, chunk)
    except Exception as e:
        logger.exception(f"فشل إرسال النتيجة للمالك: {e}")

async def _start_raksh_execution(
    update,
    context,
    query,
    service_type: str,
    quantity: int,
    payment_method: str,
    total_cost: int,
    progress_message=None,
):
    """بدء تنفيذ الرشق"""
    user = update.effective_user if update else query.from_user
    
    if progress_message is None:
        progress_msg = await query.edit_message_text(
            "✅ *بدأ التنفيذ...*\n\n"
            f"📊 0/{quantity}",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        progress_msg = progress_message
        await progress_msg.edit_text(
            "✅ *بدأ التنفيذ...*\n\n"
            f"📊 0/{quantity}",
            parse_mode=ParseMode.MARKDOWN,
        )
    
    svc = get_raksh_service(service_type)
    sessions = svc.get_sessions() if svc else []
    if not sessions:
        await progress_msg.edit_text(
            "❌ لا توجد حسابات متاحة.",
            reply_markup=raksh_menu_kb(user.id == OWNER_ID)
        )
        if payment_method == "points":
            add_points(user.id, total_cost)
        _clear_raksh_state(context)
        return
    
    await _send_raksh_order_to_group(
        context.bot,
        user.id,
        quantity,
        payment_method,
        service_type,
    )
    
    params = svc.get_execution_params(context) if svc else {}
    
    async def update_progress(current, total, success, failed):
        try:
            await progress_msg.edit_text(
                f"⏳ *جاري التنفيذ...*\n\n"
                f"📊 {current}/{total}\n"
                f"✅ نجح: {success}\n"
                f"❌ فشل: {failed}",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
    
    success_count, success_phones, success_details, failed_phones, failed_details = await execute_raksh_service(
        service_type=service_type,
        quantity=quantity,
        sessions=sessions,
        params=params,
        user_id=user.id,
        progress_callback=update_progress
    )
    
    await _send_raksh_owner_result(
        context.bot,
        service_type,
        quantity,
        success_phones,
        failed_phones,
        failed_details,
    )
    
    # حساب التعويض
    refund = 0
    special_count = 0
    if payment_method == "points":
        failed_refund = max(0, total_cost - get_raksh_total(service_type, success_count, "points"))
        special_count = sum(1 for msg in success_details if "بدون زر تحقق" in msg or RAKSH_NO_VERIFICATION_MESSAGE in msg)
        if special_count > 0:
            special_refund = int(get_raksh_total(service_type, special_count, "points") / 2)
            refund = failed_refund + special_refund
            if refund > 0:
                add_points(user.id, refund)
    
    # عرض النتيجة
    failed_count = quantity - success_count
    result_text = f"✅ *اكتمل الطلب!*\n\n"
    result_text += f"الخدمة: {svc.config.name if svc else service_type}\n"
    result_text += f"المطلوب: {quantity}\n"
    result_text += f"✅ المنجز: {success_count}\n"
    result_text += f"❌ الفاشل: {failed_count}\n"
    if refund > 0:
        result_text += f"💰 تم تعويضك: {refund} نقطة\n"
    if special_count > 0:
        result_text += f"🔁 استرداد نصف المبلغ لـ {special_count} حساب (بدون زر تحقق)\n"
    
    if success_phones:
        result_text += f"\n✅ *الحسابات الناجحة ({len(success_phones)}):*\n"
        result_text += "\n".join(f"• `{p}`" for p in success_phones[:10])
        if len(success_phones) > 10:
            result_text += f"\n... و{len(success_phones)-10} أخرى"
    
    if failed_details:
        result_text += f"\n\n❌ *الفاشلة ({len(failed_details)}):*\n"
        result_text += "\n".join(f"• {d[:80]}" for d in failed_details[:5])
        if len(failed_details) > 5:
            result_text += f"\n... و{len(failed_details)-5} أخرى"
    
    await progress_msg.edit_text(
        result_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb()
    )
    
    _clear_raksh_state(context)

# ════════════════════════════════════════════════════════
# ═══ 17. الأمر الرئيسي ═══
# ════════════════════════════════════════════════════════

async def cmd_raksh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الأمر /raksh"""
    user = update.effective_user
    _clear_raksh_state(context)
    
    if not (user.id == OWNER_ID) and is_user_banned(user.id):
        await update.message.reply_text("🚫 تم حظرك من استخدام هذا البوت.")
        return
    
    available_sessions = get_available_sessions_count()
    
    await update.message.reply_text(
        f"🔥 *{md_escape(get_raksh_accounts_label())}*\n\n"
        "اختر الخدمة المطلوبة:\n"
        f"📊 الحسابات المتاحة: *{available_sessions}*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=raksh_menu_kb(user.id == OWNER_ID)
    )
