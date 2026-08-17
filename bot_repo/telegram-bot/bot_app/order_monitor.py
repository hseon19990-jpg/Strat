"""مراقب الطلبات المتأخرة - أمر يدوي للمالك فقط"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

import datetime
import asyncio

# ==================== دوال مساعدة ====================

def _get_delayed_orders():
    """جلب الطلبات التي مضى عليها أكثر من 6 ساعات"""
    threshold = datetime.datetime.now(timezone.utc) - timedelta(hours=6)
    
    with db_conn() as c:
        rows = c.execute("""
            SELECT o.order_code, o.user_id, o.created_at, o.api_order_id,
                   o.link, o.quantity, o.cost_points,
                   s.name_ar AS service_name, s.panel AS panel
            FROM orders o
            LEFT JOIN services s ON s.id = o.service_id
            WHERE o.status = 'pending'
              AND o.created_at::timestamptz < %s
              AND o.api_order_id IS NOT NULL
              AND o.api_order_id != ''
            ORDER BY o.created_at ASC
        """, (threshold,)).fetchall()
    
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

async def _send_delayed_report_to_owner(bot):
    """إرسال تقرير الطلبات المتأخرة للمالك (مفصول حسب الموقع)"""
    if not OWNER_ID:
        return
    
    delayed_orders = _get_delayed_orders()
    
    if not delayed_orders:
        await bot.send_message(OWNER_ID, "📊 *الطلبات المتأخرة*\n\n✅ لا توجد طلبات مضى عليها أكثر من 6 ساعات.")
        logger.info("📊 تم إرسال التقرير: لا توجد طلبات متأخرة")
        return
    
    # تجميع الطلبات حسب الموقع
    orders_by_panel = {}
    for order in delayed_orders:
        panel = order.get('panel', 1)
        if panel not in orders_by_panel:
            orders_by_panel[panel] = []
        orders_by_panel[panel].append(order)
    
    # إرسال رسالة منفصلة لكل موقع
    total_sent = 0
    for panel, orders in orders_by_panel.items():
        panel_name = _get_panel_name(panel)
        
        lines = [
            f"📊 *الطلبات المتأخرة - {panel_name}*",
            f"📦 عدد الطلبات: {len(orders)}",
            "",
        ]
        
        for order in orders:
            created_at = order['created_at']
            if hasattr(created_at, 'strftime'):
                date_str = created_at.strftime("%Y-%m-%d %H:%M")
                # حساب مدة التأخير بالساعات
                delay_hours = round((datetime.datetime.now(timezone.utc) - created_at).total_seconds() / 3600, 1)
            else:
                date_str = str(created_at)[:16]
                delay_hours = 0
            
            lines.append(
                f"  └ 📌 `{order['order_code']}` — {date_str} (تأخير {delay_hours} ساعة)\n"
                f"     👤 ID: {order['user_id']} | 💰 {order['cost_points']} نقطة\n"
                f"     🔹 {order['service_name'] or 'غير معروف'}"
            )
        
        text = "\n".join(lines)
        
        # تقسيم الرسالة إذا كانت طويلة
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
            
            for chunk in chunks:
                await bot.send_message(OWNER_ID, chunk, parse_mode=ParseMode.MARKDOWN)
        else:
            await bot.send_message(OWNER_ID, text, parse_mode=ParseMode.MARKDOWN)
        
        total_sent += 1
    
    logger.info(f"📊 تم إرسال {total_sent} تقرير للطلبات المتأخرة (مفصولة حسب الموقع)")

# ==================== أمر المالك ====================

async def cmd_delayed_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المالك: /delayed_orders - عرض الطلبات المتأخرة 6+ ساعات"""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط.")
        return
    
    await update.message.reply_text("⏳ *جاري فحص الطلبات المتأخرة...*", parse_mode=ParseMode.MARKDOWN)
    await _send_delayed_report_to_owner(context.bot)

# ==================== التهيئة ====================

def setup_order_monitor(application):
    """إضافة أمر المالك"""
    application.add_handler(CommandHandler("delayed_orders", cmd_delayed_orders))
    logger.info("📊 تم تفعيل أمر /delayed_orders للمالك")
