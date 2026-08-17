"""مراقب الطلبات - يرسل تقرير الطلبات غير المكتملة فور التشغيل"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

import datetime

# ==================== دوال مساعدة ====================

def _get_pending_orders():
    """جلب جميع الطلبات المعلقة حالياً"""
    with db_conn() as c:
        rows = c.execute("""
            SELECT o.order_code, o.user_id, o.created_at, o.api_order_id,
                   o.link, o.quantity, o.cost_points,
                   s.name_ar AS service_name, s.panel AS panel
            FROM orders o
            LEFT JOIN services s ON s.id = o.service_id
            WHERE o.status = 'pending'
              AND o.api_order_id IS NOT NULL
              AND o.api_order_id != ''
            ORDER BY o.created_at ASC
        """).fetchall()
    
    return [dict(row) for row in rows]

def _get_panel_name(panel_id: int) -> str:
    """إرجاع اسم الموقع بناءً على رقم اللوحة"""
    panel_names = {
        1: "SMMMAIN",
        2: "JustAnotherPanel",
        3: "SmmFollows",
    }
    return panel_names.get(panel_id, f"موقع غير معروف")

# ==================== إرسال التقرير للمالك ====================

async def _send_report_to_owner(bot):
    """إرسال تقرير الطلبات غير المكتملة للمالك"""
    if not OWNER_ID:
        return
    
    pending_orders = _get_pending_orders()
    
    if not pending_orders:
        text = "📊 *تقرير الطلبات*\n\n✅ لا توجد طلبات معلقة حالياً."
        await bot.send_message(OWNER_ID, text, parse_mode=ParseMode.MARKDOWN)
        logger.info("📊 تم إرسال التقرير: لا توجد طلبات معلقة")
        return
    
    # تجميع الطلبات حسب الموقع
    orders_by_panel = {}
    for order in pending_orders:
        panel = order.get('panel', 1)
        if panel not in orders_by_panel:
            orders_by_panel[panel] = []
        orders_by_panel[panel].append(order)
    
    # بناء التقرير
    lines = [
        "📊 *تقرير الطلبات غير المكتملة*",
        f"📦 إجمالي الطلبات المعلقة: *{len(pending_orders)}*",
        "",
    ]
    
    for panel, orders in orders_by_panel.items():
        panel_name = _get_panel_name(panel)
        lines.append(f"🌐 *{panel_name}* — {len(orders)} طلب")
        
        for order in orders:
            created_at = order['created_at']
            if hasattr(created_at, 'strftime'):
                date_str = created_at.strftime("%Y-%m-%d %H:%M")
            else:
                date_str = str(created_at)[:16]
            
            lines.append(f"  └ 📌 `{order['order_code']}` — {date_str}")
        
        lines.append("")  # فاصل بين المواقع
    
    text = "\n".join(lines)
    
    # تقسيم الرسالة إذا كانت طويلة جداً
    if len(text) > 4000:
        chunks = []
        current = []
        current_length = 0
        
        for line in lines:
            line_length = len(line) + 1
            if current and current_length + line_length > 3500:
                chunks.append("\n".join(current))
                current = []
                current_length = 0
            current.append(line)
            current_length += line_length
        
        if current:
            chunks.append("\n".join(current))
        
        for i, chunk in enumerate(chunks):
            if i == 0:
                await bot.send_message(OWNER_ID, chunk, parse_mode=ParseMode.MARKDOWN)
            else:
                await bot.send_message(OWNER_ID, chunk, parse_mode=ParseMode.MARKDOWN)
    else:
        await bot.send_message(OWNER_ID, text, parse_mode=ParseMode.MARKDOWN)
    
    logger.info(f"📊 تم إرسال تقرير: {len(pending_orders)} طلب معلق")

# ==================== التشغيل الفوري ====================

async def startup_report(app):
    """إرسال التقرير فور تشغيل البوت"""
    await asyncio.sleep(3)  # انتظار 3 ثوانٍ لضمان اكتمال الاتصال
    await _send_report_to_owner(app.bot)

def setup_order_monitor(application):
    """تهيئة مراقب الطلبات"""
    # إرسال التقرير فوراً عند التشغيل
    asyncio.create_task(startup_report(application))
    logger.info("📊 تم تفعيل تقرير الطلبات غير المكتملة (سيُرسل فوراً)")
