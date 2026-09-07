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
from ..services import get_menu_items
import json


OWNER_FAST_BATCH_SIZE = 12
OWNER_FAST_BATCH_INTERVAL_SECONDS = 2
RAKSH_ACCOUNT_EXECUTION_TIMEOUT_SECONDS = 180

_ACTIVE_RAKSH_ORDER_IDS = set()
RAKSH_ORDER_LEASE_MINUTES = 30

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

def _reserve_raksh_execution_slot(
    user_id: int,
    service_type: str,
    phone_number: str,
    order_id: Optional[int] = None,
) -> bool:
    """حجز تنفيذ واحد"""
    if RAKSH_MAX_EXECUTIONS_PER_HOUR <= 0 and RAKSH_MAX_EXECUTIONS_PER_DAY <= 0:
        return True
    try:
        with db_conn() as c:
            if order_id is not None:
                existing = c.execute(
                    """
                    SELECT 1
                    FROM raksh_execution_usage
                    WHERE order_id=%s AND phone_number=%s
                    LIMIT 1
                    """,
                    (order_id, phone_number),
                ).fetchone()
                if existing:
                    return True

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
                    (user_id, service_type, phone_number, order_id)
                VALUES (%s, %s, %s, %s)
                """,
                (user_id, service_type, phone_number, order_id),
            )
        return True
    except Exception:
        logger.exception(f"فشل حجز تنفيذ للمستخدم {user_id}")
        return False

# ════════════════════════════════════════════════════════
# ═══ 11. مدير التنفيذ ═══
# ════════════════════════════════════════════════════════

def _create_raksh_order(
    user_id: int,
    service_type: str,
    quantity: int,
    payment_method: str,
    total_cost: int,
    params: Dict,
    sessions: List[Dict],
) -> int:
    """حفظ طلب الرشق وحساباته قبل بدء أي تنفيذ."""
    serialized_params = json.dumps(params or {}, ensure_ascii=False, default=str)
    with db_conn() as c:
        row = c.execute(
            """
            INSERT INTO raksh_orders
                (user_id, service_type, quantity, payment_method, total_cost, params, status)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'pending')
            RETURNING id
            """,
            (
                user_id,
                service_type,
                quantity,
                payment_method,
                total_cost,
                serialized_params,
            ),
        ).fetchone()
        order_id = int(row["id"])

        seen_phones = set()
        for position, session in enumerate(sessions):
            phone = str(session.get("phone_number") or "").strip()
            if not phone or phone in seen_phones:
                continue
            seen_phones.add(phone)
            c.execute(
                """
                INSERT INTO raksh_order_items
                    (order_id, position, stock_id, phone_number)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (order_id, phone_number) DO NOTHING
                """,
                (order_id, position, session.get("id"), phone),
            )
    return order_id


def _load_raksh_order(order_id: int) -> Optional[Dict]:
    with db_conn() as c:
        row = c.execute(
            "SELECT * FROM raksh_orders WHERE id=%s",
            (order_id,),
        ).fetchone()
    if not row:
        return None
    order = dict(row)
    params = order.get("params") or {}
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except (TypeError, ValueError):
            params = {}
    order["params"] = params
    return order


def _is_raksh_order_cancelled(order_id: Optional[int]) -> bool:
    if not order_id:
        return False
    with db_conn() as c:
        row = c.execute(
            "SELECT status FROM raksh_orders WHERE id=%s",
            (order_id,),
        ).fetchone()
    return bool(row and row["status"] == "cancelled")


def _cancel_user_raksh_order(user_id: int, order_id: int) -> Dict:
    """إلغاء طلب يملكه المستخدم وإيقاف الحسابات التي لم تكتمل."""
    refund = 0
    success_count = 0
    quantity = 0
    payment_method = "points"
    with db_conn() as c:
        order = c.execute(
            "SELECT * FROM raksh_orders WHERE id=%s AND user_id=%s FOR UPDATE",
            (order_id, user_id),
        ).fetchone()
        if not order:
            return {"status": "missing"}
        if order["status"] not in {"pending", "running"}:
            return {"status": "finished", "order_status": order["status"]}

        quantity = int(order["quantity"] or 0)
        payment_method = order["payment_method"]
        success_row = c.execute(
            "SELECT COUNT(*) AS count FROM raksh_order_items WHERE order_id=%s AND status='success'",
            (order_id,),
        ).fetchone()
        success_count = int(success_row["count"] or 0)
        if payment_method == "points":
            try:
                refund = max(
                    0,
                    int(order["total_cost"] or 0)
                    - get_raksh_total(order["service_type"], success_count, "points"),
                )
            except Exception:
                refund = 0

        cancel_reason = "أُلغي من المستخدم"
        result_text = (
            f"❌ أُلغي الطلب #{order_id}.\n"
            f"✅ المنجز قبل الإلغاء: {success_count}/{quantity}"
        )
        if refund > 0:
            result_text += f"\n💰 تمت إعادة {refund} نقطة."
        c.execute(
            """
            UPDATE raksh_orders
            SET status='cancelled', refund_points=%s, result_text=%s,
                last_error=%s, lease_until=NULL, updated_at=NOW(), completed_at=NOW()
            WHERE id=%s AND status IN ('pending', 'running')
            """,
            (refund, result_text, cancel_reason, order_id),
        )
        c.execute(
            """
            UPDATE raksh_order_items
            SET status='cancelled', last_error=%s, updated_at=NOW()
            WHERE order_id=%s AND status IN ('pending', 'running')
            """,
            (cancel_reason, order_id),
        )

    if refund > 0:
        add_points(user_id, refund)
    return {
        "status": "cancelled",
        "refund": refund,
        "success_count": success_count,
        "quantity": quantity,
        "payment_method": payment_method,
    }


def _load_user_raksh_orders(user_id: int, statuses: tuple[str, ...], limit: int = 10):
    if not statuses:
        return []
    placeholders = ", ".join("%s" for _ in statuses)
    with db_conn() as c:
        return c.execute(
            f"""
            SELECT o.*,
                   (SELECT COUNT(*) FROM raksh_order_items i
                    WHERE i.order_id=o.id AND i.status='success') AS success_count,
                   (SELECT COUNT(*) FROM raksh_order_items i
                    WHERE i.order_id=o.id AND i.status='failed') AS failed_count
            FROM raksh_orders o
            WHERE o.user_id=%s AND o.status IN ({placeholders})
            ORDER BY o.created_at DESC, o.id DESC
            LIMIT %s
            """,
            (user_id, *statuses, limit),
        ).fetchall()


def _raksh_order_date(value) -> str:
    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value or "—")[:16]


def _raksh_order_service_name(order) -> str:
    svc = get_raksh_service(order["service_type"])
    return svc.label if svc else str(order["service_type"])


def _raksh_order_summary(order, current: bool) -> str:
    order_id = int(order["id"])
    service_name = md_escape(_raksh_order_service_name(order))
    quantity = int(order["quantity"] or 0)
    success_count = int(order.get("success_count") or 0)
    failed_count = int(order.get("failed_count") or 0)
    payment_label = "نقطة" if order["payment_method"] == "points" else "نجمة"
    if current:
        state = "⏳ جاري" if order["status"] == "running" else "🕐 بانتظار التنفيذ"
        return (
            f"• *#{order_id}* — {service_name}\n"
            f"  {state} | 📊 {success_count}/{quantity} | 💰 {order['total_cost']} {payment_label}\n"
            f"  🕒 {_raksh_order_date(order.get('created_at'))}"
        )
    state = "✅ مكتمل" if order["status"] == "completed" else "❌ ملغى"
    return (
        f"• *#{order_id}* — {service_name}\n"
        f"  {state} | ✅ المنجز: {success_count}/{quantity} | ❌ الفاشل: {failed_count}\n"
        f"  🕒 {_raksh_order_date(order.get('created_at'))}"
    )


async def _render_user_raksh_orders(query, user_id: int):
    current_orders = _load_user_raksh_orders(user_id, ("pending", "running"))
    completed_orders = _load_user_raksh_orders(user_id, ("completed", "cancelled"))
    lines = ["📋 *طلباتي*", ""]
    if current_orders:
        lines.append("⏳ *الطلبات الجارية:*\n")
        for order in current_orders:
            lines.append(_raksh_order_summary(order, current=True))
            lines.append("")
    else:
        lines.append("⏳ *الطلبات الجارية:* لا توجد طلبات قيد التنفيذ.\n")
    if completed_orders:
        lines.append("✅ *الطلبات المكتملة والملغاة:*\n")
        for order in completed_orders:
            lines.append(_raksh_order_summary(order, current=False))
            lines.append("")
    else:
        lines.append("✅ *الطلبات المكتملة:* لا توجد طلبات سابقة.")
    rows = []
    for order in current_orders:
        rows.append([InlineKeyboardButton(f"❌ إلغاء الطلب #{order['id']}", callback_data=f"raksh:order:cancel:{order['id']}")])
    rows.append([InlineKeyboardButton("🔙 رجوع لخدمات الرشق", callback_data="raksh_menu")])
    await query.edit_message_text(
        "\n".join(lines), parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows),
    )


def _load_raksh_order_items(order_id: int) -> Dict[str, Dict]:
    with db_conn() as c:
        rows = c.execute(
            """
            SELECT phone_number, status, result_message, last_error
            FROM raksh_order_items
            WHERE order_id=%s
            ORDER BY position ASC
            """,
            (order_id,),
        ).fetchall()
    return {str(row["phone_number"]): dict(row) for row in rows}


def _mark_raksh_order_item_started(order_id: int, phone: str) -> bool:
    with db_conn() as c:
        row = c.execute(
            """
            UPDATE raksh_order_items
            SET status='running', attempts=attempts + 1,
                last_error=NULL, updated_at=NOW()
            WHERE order_id=%s AND phone_number=%s AND status <> 'cancelled'
              AND EXISTS (
                  SELECT 1 FROM raksh_orders o
                  WHERE o.id=%s AND o.status <> 'cancelled'
              )
            RETURNING id
            """,
            (order_id, phone, order_id),
        ).fetchone()
        if not row:
            return False
        c.execute(
            """
            UPDATE raksh_orders
            SET status='running', updated_at=NOW(),
                lease_until=NOW() + (%s * INTERVAL '1 minute')
            WHERE id=%s AND status <> 'cancelled'
            """,
            (RAKSH_ORDER_LEASE_MINUTES, order_id),
        )
    return True


def _mark_raksh_order_item_result(
    order_id: int,
    phone: str,
    ok: bool,
    message: str,
) -> None:
    with db_conn() as c:
        c.execute(
            """
            UPDATE raksh_order_items
            SET status=%s,
                result_message=%s,
                last_error=%s,
                updated_at=NOW()
            WHERE order_id=%s AND phone_number=%s AND status <> 'cancelled'
            """,
            (
                "success" if ok else "failed",
                message if ok else None,
                None if ok else message,
                order_id,
                phone,
            ),
        )
        c.execute(
            """
            UPDATE raksh_orders
            SET updated_at=NOW(),
                lease_until=NOW() + (%s * INTERVAL '1 minute')
            WHERE id=%s AND status <> 'cancelled'
            """,
            (RAKSH_ORDER_LEASE_MINUTES, order_id),
        )


def _set_raksh_order_status(
    order_id: int,
    status: str,
    last_error: Optional[str] = None,
) -> None:
    with db_conn() as c:
        c.execute(
            """
            UPDATE raksh_orders
            SET status=%s, last_error=%s, updated_at=NOW(),
                completed_at=CASE
                    WHEN %s IN ('completed', 'cancelled') THEN NOW()
                    ELSE completed_at
                END,
                lease_until=NULL
            WHERE id=%s
            """,
            (status, last_error, status, order_id),
        )


def _claim_raksh_order(order_id: int) -> Optional[Dict]:
    """حجز طلب للاستئناف ومنع تشغيله مرتين بعد إعادة النشر."""
    with db_conn() as c:
        row = c.execute(
            """
            UPDATE raksh_orders
            SET status='running',
                lease_until=NOW() + (%s * INTERVAL '1 minute'),
                updated_at=NOW()
            WHERE id=%s
              AND status IN ('pending', 'running')
              AND (lease_until IS NULL OR lease_until < NOW())
            RETURNING *
            """,
            (RAKSH_ORDER_LEASE_MINUTES, order_id),
        ).fetchone()
    if not row:
        return None
    order = dict(row)
    params = order.get("params") or {}
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except (TypeError, ValueError):
            params = {}
    order["params"] = params
    return order


def _reset_interrupted_raksh_orders(force: bool = False) -> int:
    """إعادة الحساب الذي كان قيد التنفيذ إلى الطابور بعد توقف العملية."""
    item_order_condition = (
        "status IN ('pending', 'running')"
        if force
        else "status='pending' OR (status='running' AND lease_until < NOW())"
    )
    order_condition = (
        "status='running'"
        if force
        else "status='running' AND (lease_until IS NULL OR lease_until < NOW())"
    )
    with db_conn() as c:
        c.execute(
            f"""
            UPDATE raksh_order_items
            SET status='pending', updated_at=NOW()
            WHERE status='running'
              AND order_id IN (
                  SELECT id FROM raksh_orders
                  WHERE {item_order_condition}
              )
            """
        )
        rows = c.execute(
            f"""
            UPDATE raksh_orders
            SET status='pending', lease_until=NULL, updated_at=NOW()
            WHERE {order_condition}
            RETURNING id
            """
        ).fetchall()
    return len(rows or [])


def recover_raksh_orders_on_startup() -> int:
    """فتح الطلبات التي كانت تعمل في النسخة القديمة فور بدء نسخة جديدة."""
    return _reset_interrupted_raksh_orders(force=True)


async def execute_raksh_service(
    service_type: str,
    quantity: int,
    sessions: List[Dict],
    params: Dict,
    user_id: int,
    progress_callback=None,
    order_id: Optional[int] = None,
) -> Tuple[int, List[str], List[str], List[str], List[str]]:
    """تنفيذ طلب رشق"""
    if not sessions:
        raise RuntimeError("لا توجد جلسات نشطة متاحة")
    
    svc = get_raksh_service(service_type)
    if not svc:
        raise RuntimeError(f"خدمة غير معروفة: {service_type}")
    
    # get_sessions جهز ترتيب الأولوية للمالك والعشوائية للأعضاء.
    shuffled = sessions.copy()
    # المالك فقط يعمل على دفعات من 12 حساباً مع فاصل ثانيتين بين الدفعات.
    # الأعضاء يبقون على المسار التسلسلي والفاصل الحالي بدون تغيير.
    if user_id == OWNER_ID:
        if service_type == "votes_ai":
            async with _RAKSH_VOTE_FLOW_LOCK:
                return await _execute_raksh_parallel(
                    svc, shuffled, params, user_id, quantity,
                    progress_callback, service_type,
                    OWNER_FAST_BATCH_SIZE,
                    OWNER_FAST_BATCH_INTERVAL_SECONDS,
                    order_id,
                )
        return await _execute_raksh_parallel(
            svc, shuffled, params, user_id, quantity,
            progress_callback, service_type,
            OWNER_FAST_BATCH_SIZE,
            OWNER_FAST_BATCH_INTERVAL_SECONDS,
            order_id,
        )

    # الأعضاء: كل خدمات الرشق تمر عبر طابور تسلسلي واحد حتى يبقى الفاصل
    # الحالي كما هو، ولا تتنافس جلستان على نفس الموارد.
    if service_type == "votes_ai":
        async with _RAKSH_VOTE_FLOW_LOCK:
            return await _execute_raksh_sequential(
                svc, shuffled, params, user_id,
                quantity, progress_callback, service_type, order_id
            )
    return await _execute_raksh_sequential(
        svc, shuffled, params, user_id,
        quantity, progress_callback, service_type, order_id
    )


def _is_retryable_raksh_session_message(message: str) -> bool:
    """تمييز حالات الجلسة المؤقتة عن الفشل النهائي."""
    text = str(message or "").casefold()
    transient_markers = (
        "الجلسة قيد الاستخدام",
        "الجلسة مشغولة",
        "جلسة نشطة",
        "قيد الاستخدام",
        "busy",
        "active session",
        "temporarily",
        "timeout",
        "timed out",
        "connection reset",
        "flood wait",
        "a wait of",
    )
    return any(marker in text for marker in transient_markers)


async def _wait_for_raksh_session(
    session_lock: asyncio.Lock,
    phone: str,
) -> bool:
    """انتظار تحرير الجلسة بدلاً من اعتبارها فاشلة فوراً."""
    if not session_lock.locked():
        return True

    logger.info(f"⏳ الجلسة {phone} قيد الاستخدام؛ بانتظار تجهيزها")
    deadline = asyncio.get_running_loop().time() + RAKSH_SESSION_WAIT_TIMEOUT_SECONDS
    while session_lock.locked():
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            logger.warning(f"⌛ انتهت مهلة انتظار الجلسة {phone}")
            return False
        await asyncio.sleep(min(RAKSH_SESSION_POLL_SECONDS, remaining))
    return True

async def _execute_raksh_sequential(
    svc: RakshService,
    sessions: List[Dict],
    params: Dict,
    user_id: int,
    quantity: int,
    progress_callback,
    service_type: str,
    order_id: Optional[int] = None,
) -> Tuple[int, List[str], List[str], List[str], List[str]]:
    """تنفيذ الخدمات تسلسلياً مع انتظار الجلسات وإعادة المحاولة."""
    order_items = _load_raksh_order_items(order_id) if order_id else {}
    success_phones = [
        phone for phone, item in order_items.items()
        if item.get("status") == "success"
    ]
    success_details = [
        order_items[phone].get("result_message") or ""
        for phone in success_phones
    ]
    failed_phones = [
        phone for phone, item in order_items.items()
        if item.get("status") == "failed"
    ]
    failed_details = [
        order_items[phone].get("last_error") or "فشل"
        for phone in failed_phones
    ]
    success_count = len(success_phones)
    completed_count = success_count + len(failed_phones)
    attempt_count = 0
    channel_setup_done = False
    reserved_phones = set()
    retry_counts = {}
    queued_phones = set()
    queue = []

    # إزالة التكرارات مع الحفاظ على ترتيب الحساب المفضل أولاً.
    for session in sessions:
        phone = session.get("phone_number")
        item = order_items.get(str(phone)) if order_id else None
        if (
            phone
            and phone not in queued_phones
            and (not item or item.get("status") not in {"success", "failed"})
        ):
            queue.append(session)
            queued_phones.add(phone)

    while success_count < quantity and queue:
        session = queue.pop(0)
        phone = session["phone_number"]
        queued_phones.discard(phone)

        if order_id and _is_raksh_order_cancelled(order_id):
            break

        if attempt_count:
            delay = svc.get_delay_seconds(params.get("delay_seconds"))
            logger.info(f"⏱️ انتظار {delay} ثانية قبل الحساب {phone}")
            await asyncio.sleep(delay)
        attempt_count += 1

        if phone not in reserved_phones:
            if not _reserve_raksh_execution_slot(
                user_id, service_type, phone, order_id=order_id
            ):
                failed_phones.append(phone)
                failed_details.append("تم تجاوز حد التنفيذ")
                completed_count += 1
                if order_id:
                    _mark_raksh_order_item_result(
                        order_id, phone, False, "تم تجاوز حد التنفيذ"
                    )
                continue
            reserved_phones.add(phone)

        session_lock = _get_raksh_session_lock(phone)
        if not await _wait_for_raksh_session(session_lock, phone):
            retry_counts[phone] = retry_counts.get(phone, 0) + 1
            if retry_counts[phone] < RAKSH_SESSION_RETRY_LIMIT:
                queue.append(session)
                queued_phones.add(phone)
                logger.info(
                    f"🔁 إعادة جدولة الجلسة {phone} "
                    f"({retry_counts[phone]}/{RAKSH_SESSION_RETRY_LIMIT})"
                )
                continue
            failed_phones.append(phone)
            failed_details.append("تعذر تجهيز الجلسة بعد الانتظار")
            completed_count += 1
            if order_id:
                _mark_raksh_order_item_result(
                    order_id, phone, False, "تعذر تجهيز الجلسة بعد الانتظار"
                )
            continue

        if order_id and _is_raksh_order_cancelled(order_id):
            break

        async with session_lock:
            if order_id and not _mark_raksh_order_item_started(order_id, phone):
                break
            try:
                channel_setup_done_before = channel_setup_done
                channel_setup_done = True
                ok, msg = await svc.execute(
                    session=session,
                    params=params,
                    is_first=not channel_setup_done_before,
                )
            except Exception as e:
                ok = False
                msg = f"❌ خطأ: {str(e)}"

        if not ok and _is_retryable_raksh_session_message(msg):
            retry_counts[phone] = retry_counts.get(phone, 0) + 1
            if retry_counts[phone] < RAKSH_SESSION_RETRY_LIMIT:
                queue.append(session)
                queued_phones.add(phone)
                logger.info(
                    f"🔁 الجلسة {phone} مؤقتاً غير جاهزة؛ "
                    f"ستعاد المحاولة ({retry_counts[phone]}/{RAKSH_SESSION_RETRY_LIMIT})"
                )
                continue

        completed_count += 1
        if ok:
            success_count += 1
            success_phones.append(phone)
            success_details.append(msg)
        else:
            failed_phones.append(phone)
            failed_details.append(msg)
        if order_id:
            _mark_raksh_order_item_result(order_id, phone, ok, msg)

        if progress_callback:
            await progress_callback(
                completed_count,
                quantity,
                success_count,
                len(failed_details),
            )
    
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
    batch_delay_seconds: int = 0,
    order_id: Optional[int] = None,
) -> Tuple[int, List[str], List[str], List[str], List[str]]:
    """تنفيذ دفعات سريعة للمالك مع الحفاظ على ترتيب ونتائج الطلب."""
    order_items = _load_raksh_order_items(order_id) if order_id else {}
    success_phones = [
        phone for phone, item in order_items.items()
        if item.get("status") == "success"
    ]
    success_details = [
        order_items[phone].get("result_message") or ""
        for phone in success_phones
    ]
    failed_phones = [
        phone for phone, item in order_items.items()
        if item.get("status") == "failed"
    ]
    failed_details = [
        order_items[phone].get("last_error") or "فشل"
        for phone in failed_phones
    ]
    success_count = len(success_phones)
    completed_count = success_count + len(failed_phones)
    attempted_phones = set(success_phones) | set(failed_phones)
    pool = list(sessions)

    async def execute_one(session, index, is_first=False):
        phone = session["phone_number"]
        if order_id and _is_raksh_order_cancelled(order_id):
            return False, "تم إلغاء الطلب"
        if not _reserve_raksh_execution_slot(
            user_id, service_type, phone, order_id=order_id
        ):
            return False, "تم تجاوز حد التنفيذ"

        session_lock = _get_raksh_session_lock(phone)
        if not await _wait_for_raksh_session(session_lock, phone):
            return False, "تعذر تجهيز الجلسة بعد الانتظار"

        if order_id and _is_raksh_order_cancelled(order_id):
            return False, "تم إلغاء الطلب"

        async with session_lock:
            if order_id and not _mark_raksh_order_item_started(order_id, phone):
                return False, "تم إلغاء الطلب"
            try:
                return await asyncio.wait_for(
                    svc.execute(
                        session=session,
                        params=params,
                        is_first=is_first,
                    ),
                    timeout=RAKSH_ACCOUNT_EXECUTION_TIMEOUT_SECONDS,
                )
            except Exception as e:
                return False, f"❌ خطأ: {str(e)}"

    async def process_wave(wave, results):
        nonlocal completed_count, success_count
        for session, result in zip(wave, results):
            phone = session["phone_number"]
            if isinstance(result, BaseException):
                ok, msg = False, f"❌ خطأ من {phone}: {str(result)[:80]}"
            else:
                ok, msg = result
            completed_count += 1
            if ok:
                success_count += 1
                success_phones.append(phone)
                success_details.append(msg)
            else:
                failed_phones.append(phone)
                failed_details.append(msg)
            if order_id:
                _mark_raksh_order_item_result(order_id, phone, ok, msg)

        if progress_callback:
            await progress_callback(
                completed_count,
                quantity,
                success_count,
                len(failed_details),
            )

    # Schedule the next wave every two seconds instead of waiting for the
    # slowest account in the previous wave. This is the actual "12 every 2s"
    # owner behavior; member requests never enter this function.
    while pool and success_count < quantity and not (order_id and _is_raksh_order_cancelled(order_id)):
        planned = success_count
        scheduled = []
        wave_number = 0
        while pool and planned < quantity and not (order_id and _is_raksh_order_cancelled(order_id)):
            wave = []
            while pool and len(wave) < min(max_concurrent, quantity - planned):
                session = pool.pop(0)
                phone = session.get("phone_number")
                if not phone or phone in attempted_phones:
                    continue
                attempted_phones.add(phone)
                wave.append(session)
            if not wave:
                break

            wave_number += 1
            logger.info(
                "⚡ owner raksh wave=%s accounts=%s planned=%s/%s",
                wave_number,
                len(wave),
                planned,
                quantity,
            )
            wave_is_first = wave_number == 1 and success_count == 0
            async def gather_wave():
                return await asyncio.gather(
                    *(
                        execute_one(
                            session,
                            index,
                            is_first=(wave_is_first and index == 0),
                        )
                        for index, session in enumerate(wave)
                    ),
                    return_exceptions=True,
                )
            task = asyncio.create_task(gather_wave())
            scheduled.append((wave, task))
            planned += len(wave)
            if pool and planned < quantity and batch_delay_seconds:
                await asyncio.sleep(batch_delay_seconds)

        for wave, task in scheduled:
            results = await task
            await process_wave(wave, results)

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
    """قائمة خدمات الرشق القابلة للترتيب من إدارة الأزرار."""
    buttons = []
    for item in get_menu_items("raksh_menu"):
        action = item["action_value"]
        if action.startswith("raksh:start:"):
            key = action.split(":", 2)[2]
            svc = RAKSH_SERVICES.get(key)
            if not svc or (not is_owner and not svc.is_enabled()):
                continue
            service_button = InlineKeyboardButton(
                svc.config.name, callback_data=action
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
        elif action == "os:raksh_accounts" and is_owner:
            buttons.append([
                InlineKeyboardButton(
                    f"🔥 إدارة {get_raksh_accounts_label()}",
                    callback_data=action,
                )
            ])
        elif action == "raksh:my_orders":
            buttons.append([
                InlineKeyboardButton(item["label"], callback_data=action)
            ])
        elif action == "raksh:settings" and is_owner:
            buttons.append([
                InlineKeyboardButton(
                    "⚙️ إدارة الأسعار",
                    callback_data=action,
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

def _get_link_prompt_label(service_type: str) -> str:
    """عنوان حقل الرابط حسب الخدمة"""
    svc = get_raksh_service(service_type)
    getter = getattr(svc, "get_link_prompt_label", None) if svc else None
    if callable(getter):
        return getter()
    return "الرابط المطلوب"

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

async def _handle_raksh_callback_impl(
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
    
    await query.answer("⏳ جارٍ تجهيز الطلب...")
    
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
            f"📊 الحسابات المتاحة: *{get_available_sessions_count(is_owner=is_own)}*",
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
            "⚙️ *إعدادات أسعار رشق حقيقي*\n\n"
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
            f"📊 الحسابات المتاحة: *{get_available_sessions_count(is_owner=is_own)}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=raksh_menu_kb(is_own)
        )
        return

    # ─── طلباتي ───
    if data == "raksh:my_orders":
        _clear_raksh_state(context)
        await _render_user_raksh_orders(query, user.id)
        return

    if data.startswith("raksh:order:cancel:"):
        try:
            order_id = int(data.rsplit(":", 1)[1])
        except (TypeError, ValueError):
            await query.answer("⚠️ رقم الطلب غير صالح.", show_alert=True)
            return
        result = _cancel_user_raksh_order(user.id, order_id)
        if result["status"] == "missing":
            await query.answer("⚠️ الطلب غير موجود ضمن طلباتك.", show_alert=True)
            return
        if result["status"] == "finished":
            await query.answer("ℹ️ انتهى هذا الطلب ولا يمكن إلغاؤه الآن.", show_alert=True)
            await _render_user_raksh_orders(query, user.id)
            return
        message = f"✅ تم إلغاء الطلب #{order_id}."
        if result["refund"] > 0:
            message += f" تمت إعادة {result['refund']} نقطة."
        elif result["payment_method"] == "stars":
            message += " أُلغي الجزء المتبقي، والاسترداد التلقائي للنجوم غير متاح."
        await query.answer(message, show_alert=True)
        await _render_user_raksh_orders(query, user.id)
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
        service_type = context.user_data.get("raksh_service")
        await query.edit_message_text(
            f"✅ تم تخطي القنوات.\n\n"
            f"🔗 *أرسل {_get_link_prompt_label(service_type)}:*\n"
            f"{_get_link_instruction(service_type)}",
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
            try:
                handled = await svc.handle_callback(
                    update, context, query, parts, user, is_own
                )
            except Exception:
                logger.exception(
                    "فشل تنفيذ callback لخدمة الرشق %s للمستخدم %s",
                    service_type,
                    user.id,
                )
                await query.edit_message_text(
                    "⚠️ حدث خطأ أثناء بدء الطلب. حاول مرة أخرى.",
                    reply_markup=raksh_menu_kb(is_own),
                )
                return
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

async def handle_raksh_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query=None,
    data=None,
    user=None,
    is_own=None,
):
    """معالج آمن لأزرار الرشق مع رد واضح عند حدوث خطأ."""
    active_query = query or update.callback_query
    try:
        return await _handle_raksh_callback_impl(
            update, context, active_query, data, user, is_own
        )
    except Exception:
        error_user = user or getattr(active_query, "from_user", None)
        error_user_id = getattr(error_user, "id", "unknown")
        logger.exception(
            "فشل معالج دفع/زر الرشق للمستخدم %s",
            error_user_id,
        )
        try:
            await active_query.answer(
                "⚠️ حدث خطأ أثناء معالجة الدفع. حاول مرة أخرى.",
                show_alert=True,
            )
        except Exception:
            pass
        try:
            await active_query.edit_message_text(
                "⚠️ حدث خطأ أثناء معالجة الدفع. حاول مرة أخرى.",
                reply_markup=raksh_menu_kb(
                    getattr(error_user, "id", None) == OWNER_ID
                ),
            )
        except Exception:
            pass

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
            f"🔗 *أرسل {_get_link_prompt_label(service_type)}:*\n"
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

async def _run_raksh_order(
    context,
    order_id: int,
    progress_msg=None,
):
    """تشغيل طلب محفوظ؛ يمكن استدعاؤه من الطلب الجديد أو بعد إعادة النشر."""
    order = _load_raksh_order(order_id)
    if not order:
        logger.error(f"طلب رشق غير موجود: {order_id}")
        return

    svc = get_raksh_service(order["service_type"])
    if not svc:
        _set_raksh_order_status(order_id, "cancelled", "خدمة غير معروفة")
        return

    user_id = int(order["user_id"])
    quantity = int(order["quantity"])
    payment_method = order["payment_method"]
    total_cost = int(order["total_cost"] or 0)
    order_items = _load_raksh_order_items(order_id)
    saved_success_phones = [
        phone for phone, item in order_items.items()
        if item.get("status") == "success"
    ]
    saved_success_details = [
        order_items[phone].get("result_message") or ""
        for phone in saved_success_phones
    ]
    saved_failed_phones = [
        phone for phone, item in order_items.items()
        if item.get("status") == "failed"
    ]
    saved_failed_details = [
        order_items[phone].get("last_error") or "فشل"
        for phone in saved_failed_phones
    ]
    sessions = svc.get_sessions(is_owner=(user_id == OWNER_ID))
    if not sessions and len(saved_success_phones) < quantity:
        _set_raksh_order_status(order_id, "pending", "لا توجد حسابات متاحة مؤقتاً")
        logger.warning(f"⏳ لا توجد جلسات لطلب الرشق {order_id}; سيعاد فحصه لاحقاً")
        return

    async def update_progress(current, total, success, failed):
        if not progress_msg:
            return
        try:
            await progress_msg.edit_text(
                f"⏳ *جاري التنفيذ...*\n\n"
                f"📊 {current}/{total}\n"
                f"✅ نجح: {success}\n"
                f"❌ فشل: {failed}",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    if len(saved_success_phones) >= quantity:
        success_count = len(saved_success_phones)
        success_phones = saved_success_phones
        success_details = saved_success_details
        failed_phones = saved_failed_phones
        failed_details = saved_failed_details
    else:
        try:
            success_count, success_phones, success_details, failed_phones, failed_details = await execute_raksh_service(
                service_type=order["service_type"],
                quantity=quantity,
                sessions=sessions,
                params=order["params"],
                user_id=user_id,
                progress_callback=update_progress,
                order_id=order_id,
            )
        except Exception as exc:
            _set_raksh_order_status(order_id, "pending", str(exc))
            logger.exception(f"توقف طلب الرشق {order_id}; سيُستأنف تلقائياً")
            raise

    if _is_raksh_order_cancelled(order_id):
        return

    await _send_raksh_owner_result(
        context.bot,
        order["service_type"],
        quantity,
        success_phones,
        failed_phones,
        failed_details,
    )

    # حساب التعويض مرة واحدة عند إنهاء الطلب.
    refund = 0
    special_count = 0
    if payment_method == "points":
        failed_refund = max(
            0,
            total_cost - get_raksh_total(order["service_type"], success_count, "points"),
        )
        special_count = sum(
            1
            for msg in success_details
            if "بدون زر تحقق" in msg or RAKSH_NO_VERIFICATION_MESSAGE in msg
        )
        if special_count > 0:
            special_refund = int(
                get_raksh_total(order["service_type"], special_count, "points") / 2
            )
            refund = failed_refund + special_refund
        elif failed_refund > 0:
            refund = failed_refund

    result_text = (
        "✅ *اكتمل الطلب!*\n\n"
        f"الخدمة: {svc.config.name}\n"
        f"المطلوب: {quantity}\n"
        f"✅ المنجز: {success_count}\n"
        f"❌ الفاشل: {max(0, quantity - success_count)}\n"
    )
    if refund > 0:
        result_text += f"💰 تم تعويضك: {refund} نقطة\n"
    if special_count > 0:
        result_text += (
            f"🔁 استرداد نصف المبلغ لـ {special_count} حساب (بدون زر تحقق)\n"
        )

    with db_conn() as c:
        completed_row = c.execute(
            """
            UPDATE raksh_orders
            SET status='completed', refund_points=%s, special_count=%s,
                result_text=%s, last_error=NULL, lease_until=NULL,
                updated_at=NOW(), completed_at=NOW()
            WHERE id=%s AND status <> 'cancelled'
            RETURNING id
            """,
            (refund, special_count, result_text, order_id),
        ).fetchone()

    if not completed_row:
        return
    if refund > 0:
        add_points(user_id, refund)

    if progress_msg:
        await progress_msg.edit_text(
            result_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(),
        )
    else:
        await context.bot.send_message(user_id, result_text, parse_mode=ParseMode.MARKDOWN)


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
    """بدء طلب رشق محفوظ وقابل للاستئناف."""
    user = update.effective_user if update else query.from_user
    svc = get_raksh_service(service_type)

    if progress_message is None:
        progress_msg = await query.edit_message_text(
            "✅ *بدأ التنفيذ...*\n\n"
            f"📊 0/{quantity}",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        progress_msg = progress_message
        await progress_msg.edit_text(
            "✅ *بدأ التنفيذ...*\n\n"
            f"📊 0/{quantity}",
            parse_mode=ParseMode.MARKDOWN,
        )

    sessions = svc.get_sessions(is_owner=(user.id == OWNER_ID)) if svc else []
    if not sessions:
        await progress_msg.edit_text(
            "❌ لا توجد حسابات متاحة.",
            reply_markup=raksh_menu_kb(user.id == OWNER_ID),
        )
        if payment_method == "points":
            add_points(user.id, total_cost)
        _clear_raksh_state(context)
        return

    params = svc.get_execution_params(context) if svc else {}
    order_id = _create_raksh_order(
        user.id,
        service_type,
        quantity,
        payment_method,
        total_cost,
        params,
        sessions,
    )
    await _send_raksh_order_to_group(
        context.bot,
        user.id,
        quantity,
        payment_method,
        service_type,
    )

    if not _claim_raksh_order(order_id):
        _clear_raksh_state(context)
        await progress_msg.edit_text(
            "⚠️ تعذر حجز الطلب للتنفيذ، وسيتم استئنافه تلقائياً.",
            reply_markup=main_menu_kb(),
        )
        return

    # لا نربط تنفيذ الحسابات بعمر callback الخاص بزر Telegram. بعض الخدمات
    # (خصوصاً التصويت مع التحقق) قد تستغرق وقتاً أطول من المهلة المسموحة
    # للـ callback؛ انتظارها هنا كان يجعل الطلب ينجح ثم يظهر للمستخدم:
    # "حدث خطأ أثناء بدء الطلب".
    async def run_order_in_background():
        _ACTIVE_RAKSH_ORDER_IDS.add(order_id)
        try:
            await _run_raksh_order(context, order_id, progress_msg)
        except Exception:
            # _run_raksh_order يحفظ الطلب كـ pending قبل إعادة الاستثناء،
            # وسيعيده job الاستئناف تلقائياً. لا نعيد خطأً إلى callback.
            logger.exception(
                "فشل تنفيذ طلب الرشق في الخلفية order_id=%s",
                order_id,
            )
        finally:
            _ACTIVE_RAKSH_ORDER_IDS.discard(order_id)

    asyncio.create_task(run_order_in_background())
    _clear_raksh_state(context)

async def resume_raksh_orders_job(context) -> None:
    """استئناف طلبات الرشق غير المكتملة بعد إعادة النشر أو انقطاع العملية."""
    try:
        recovered = _reset_interrupted_raksh_orders()
        if recovered:
            logger.info(f"🔁 تمت إعادة {recovered} طلب رشق إلى طابور الاستئناف")

        with db_conn() as c:
            rows = c.execute(
                """
                SELECT id
                FROM raksh_orders
                WHERE status IN ('pending', 'running')
                  AND (lease_until IS NULL OR lease_until < NOW())
                ORDER BY created_at ASC, id ASC
                LIMIT 5
                """
            ).fetchall()

        for row in rows:
            order_id = int(row["id"])
            if order_id in _ACTIVE_RAKSH_ORDER_IDS:
                continue
            order = _claim_raksh_order(order_id)
            if not order:
                continue
            _ACTIVE_RAKSH_ORDER_IDS.add(order_id)
            try:
                logger.info(
                    f"▶️ استئناف طلب الرشق {order_id} "
                    f"({order['service_type']}, المستخدم {order['user_id']})"
                )
                await _run_raksh_order(context, order_id)
            except Exception:
                logger.exception(f"فشل استئناف طلب الرشق {order_id}; ستعاد المحاولة لاحقاً")
            finally:
                _ACTIVE_RAKSH_ORDER_IDS.discard(order_id)
    except Exception:
        logger.exception("فشل فحص طلبات الرشق القابلة للاستئناف")


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
    
    available_sessions = get_available_sessions_count(is_owner=(user.id == OWNER_ID))
    
    await update.message.reply_text(
        f"🔥 *{md_escape(get_raksh_accounts_label())}*\n\n"
        "اختر الخدمة المطلوبة:\n"
        f"📊 الحسابات المتاحة: *{available_sessions}*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=raksh_menu_kb(user.id == OWNER_ID)
    )
