"""أدوات المؤجر على حساباته: موافقة الخدمات + الكود + الأجهزة + الطرد.

الحسابات المضافة من العضو تخصه من الأصل، لذلك يحصل على نفس أدوات المالك
على حساباته هو فقط (يُتحقق من contributed_by في كل خطوة):

* 🎛 خدمات الرشق المسموحة: يقبل أو يرفض استخدام حساباته في كل نوع خدمة.
* 🔑 جلب آخر كود دخول وصل للحساب.
* 📋 عرض الأجهزة المسجلة (للاطلاع فقط).

لا يوجد أي طرد للأجهزة: الحساب المؤجَّر خط أحمر (انظر rental_guard.py).
"""

import asyncio

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})


# ════════════════════════════════════════════════════════
# موافقة المؤجر على خدمات الرشق
# ════════════════════════════════════════════════════════

def get_blocked_services(user_id: int) -> set[str]:
    """الخدمات التي رفضها المؤجر. الغياب يعني مسموح (السلوك القديم)."""
    with db_conn() as c:
        rows = c.execute(
            "SELECT service_type FROM raksh_contributor_service_blocks "
            "WHERE contributor_id=%s",
            (int(user_id),),
        ).fetchall()
    return {str(r["service_type"]) for r in rows}


def set_service_allowed(user_id: int, service_type: str, allowed: bool) -> None:
    with db_conn() as c:
        if allowed:
            c.execute(
                "DELETE FROM raksh_contributor_service_blocks "
                "WHERE contributor_id=%s AND service_type=%s",
                (int(user_id), service_type),
            )
        else:
            c.execute(
                "INSERT INTO raksh_contributor_service_blocks "
                "(contributor_id, service_type) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                (int(user_id), service_type),
            )
    # ذاكرة الجلسات تُحفظ دقيقة؛ نفرغها حتى يسري القرار فوراً.
    try:
        from .raksh_system import common as _raksh_common
        _raksh_common._RAKSH_SESSION_CACHE.clear()
        _raksh_common._RAKSH_SESSION_CACHE_TIME.clear()
    except Exception:
        pass


def _service_labels() -> dict[str, str]:
    from .raksh_system.raksh_system import RAKSH_SERVICE_LABELS
    return dict(RAKSH_SERVICE_LABELS)


def _services_screen(user_id: int):
    labels = _service_labels()
    blocked = get_blocked_services(user_id)
    lines = [
        "🎛 *خدمات الرشق المسموحة لحساباتك*",
        "",
        "اختر الخدمات التي توافق على استخدام حساباتك المؤجَّرة فيها. "
        "الخدمة المرفوضة (🚫) لن يستخدم البوت حساباتك فيها أبداً، "
        "والمسموحة (✅) تُحتسب لك فيها نسبتك من النقاط.",
        "",
        "اضغط على الخدمة لتبديل حالتها:",
    ]
    rows = []
    for service_type, label in labels.items():
        mark = "🚫 مرفوض" if service_type in blocked else "✅ مسموح"
        rows.append([InlineKeyboardButton(
            f"{label} — {mark}",
            callback_data=f"contributor:svc:{service_type}",
        )])
    rows.append([
        InlineKeyboardButton("✅ السماح للكل", callback_data="contributor:svc_all:1"),
        InlineKeyboardButton("🚫 رفض الكل", callback_data="contributor:svc_all:0"),
    ])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="contributor_accounts")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ════════════════════════════════════════════════════════
# أدوات الحساب
# ════════════════════════════════════════════════════════

def _owned_account(user_id: int, stock_id: int):
    with db_conn() as c:
        return c.execute(
            "SELECT id, phone_number, session_string, last_authorized, "
            "twofa_password, COALESCE(contributor_share_percent, 50) AS share "
            "FROM number_stock "
            "WHERE id=%s AND contributed_by=%s AND raksh_only IS TRUE "
            "AND deleted_at IS NULL AND ever_sold IS NOT TRUE",
            (int(stock_id), int(user_id)),
        ).fetchone()


def _back_kb(stock_id: int, target: str = "acct"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 رجوع", callback_data=f"contributor:{target}:{stock_id}")
    ]])


def _client_for(rec):
    return TelegramClient(
        StringSession(rec["session_string"]),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )


async def _show_account(q, rec):
    status = "✅ جاهزة" if rec.get("last_authorized") is not False else "⚠️ الجلسة منتهية"
    twofa = rec.get("twofa_password") or "غير محفوظة"
    text = (
        f"⚙️ *إدارة الحساب* `{rec['phone_number']}`\n\n"
        f"الحالة: {status}\n"
        f"🔐 2FA: `{twofa}`\n\n"
        "هذا حسابك، ولك عليه أدوات المالك: جلب الكود وعرض الأجهزة.\n"
        "🔴 الحساب المؤجَّر محمي: لا يُطرد منه أي جهاز أو جلسة بأي حال."
    )
    sid = rec["id"]
    rows = [
        [InlineKeyboardButton("🔑 جلب آخر كود دخول", callback_data=f"contributor:code:{sid}")],
        [InlineKeyboardButton("📋 الأجهزة المسجّلة", callback_data=f"contributor:devices:{sid}")],
    ]
    if rec.get("last_authorized") is False:
        rows.append([InlineKeyboardButton("🔄 إعادة تأجير", callback_data=f"contributor:relogin:{sid}")])
    rows.append([InlineKeyboardButton("🔙 حساباتي", callback_data="contributor_accounts")])
    await q.edit_message_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows)
    )


async def handle_contributor_tools_callback(update, context, q, data, user) -> bool:
    """يعالج أزرار أدوات المؤجر. يُرجع True إذا كان الزر لها."""
    if not data.startswith("contributor:"):
        return False
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    if action not in {
        "services", "svc", "svc_all", "acct", "code", "devices",
    }:
        return False

    if is_user_banned(user.id):
        await q.answer("🚫 لا يمكنك استخدام هذه الميزة.", show_alert=True)
        return True

    # ─── موافقة الخدمات ───
    if action == "services":
        text, kb = _services_screen(user.id)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return True

    if action == "svc" and len(parts) >= 3:
        service_type = parts[2]
        if service_type not in _service_labels():
            await q.answer("⚠️ خدمة غير معروفة.", show_alert=True)
            return True
        allowed_now = service_type not in get_blocked_services(user.id)
        set_service_allowed(user.id, service_type, not allowed_now)
        text, kb = _services_screen(user.id)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return True

    if action == "svc_all" and len(parts) >= 3:
        allow = parts[2] == "1"
        for service_type in _service_labels():
            set_service_allowed(user.id, service_type, allow)
        text, kb = _services_screen(user.id)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return True

    # ─── أدوات الحساب ───
    try:
        stock_id = int(parts[2])
    except (IndexError, ValueError):
        await q.answer("⚠️ الحساب غير صحيح.", show_alert=True)
        return True
    rec = _owned_account(user.id, stock_id)
    if not rec:
        await q.answer("⚠️ الحساب غير موجود ضمن حساباتك.", show_alert=True)
        return True
    rec = dict(rec)

    if action == "acct":
        await _show_account(q, rec)
        return True

    if not str(rec.get("session_string") or "").strip():
        await q.edit_message_text(
            "⚠️ لا تتوفر جلسة لهذا الحساب. أعد تأجيره بجلسة جديدة.",
            reply_markup=_back_kb(stock_id),
        )
        return True
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        await q.answer("❌ إعدادات Telegram API غير مكتملة.", show_alert=True)
        return True

    phone = rec["phone_number"]

    if action == "code":
        await q.edit_message_text(f"⏳ يتم جلب آخر كود لرقم {phone}...")
        client = _client_for(rec)
        try:
            from .accounts import fetch_last_login_code
            await asyncio.wait_for(client.connect(), timeout=20)
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=8):
                await q.edit_message_text(
                    f"🔒 جلسة البوت منتهية لرقم {phone}، ولذلك لا يمكن جلب الكود. "
                    "يمكنك إعادة تأجير الحساب.",
                    reply_markup=_back_kb(stock_id),
                )
                return True
            code_msg, code_date = await fetch_last_login_code(client)
            if code_msg:
                import datetime as _dt
                msg_date = code_date
                if msg_date and msg_date.tzinfo is None:
                    msg_date = msg_date.replace(tzinfo=_dt.timezone.utc)
                age = (
                    int((_dt.datetime.now(_dt.timezone.utc) - msg_date).total_seconds() // 60)
                    if msg_date else None
                )
                age_str = (
                    f"منذ {age} دقيقة" if age is not None and age < 60
                    else f"منذ {age // 60} ساعة" if age is not None else ""
                )
                fresh = "🟢 طازج" if age is not None and age <= 10 else "🔴 قديم"
                text = (
                    f"🔑 *آخر رسالة من تيليجرام لرقم {phone}:*\n\n"
                    f"{code_msg}\n\n🕐 وصل {age_str} — {fresh}"
                )
            else:
                text = f"ℹ️ لا توجد أي رسالة كود حالياً لرقم {phone}."
            await q.edit_message_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 تحديث", callback_data=f"contributor:code:{stock_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"contributor:acct:{stock_id}")],
                ]),
            )
        except Exception as e:
            logger.error(f"❌ خطأ في جلب كود المؤجر للرقم {phone}: {e}")
            await q.edit_message_text(
                "❌ حدث خطأ أثناء جلب الكود. حاول لاحقاً.",
                reply_markup=_back_kb(stock_id),
            )
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        return True

    if action == "devices":
        await q.edit_message_text(f"⏳ يتم جلب قائمة الأجهزة لـ {phone}...")
        client = _client_for(rec)
        try:
            from .accounts import get_authorizations_detail
            await asyncio.wait_for(client.connect(), timeout=20)
            devices = await get_authorizations_detail(client)
            if not devices:
                await q.edit_message_text(
                    "⚠️ لم يتم جلب أي جهاز (ربما الجلسة منتهية).",
                    reply_markup=_back_kb(stock_id),
                )
                return True
            lines = [f"📱 *{phone}* — {len(devices)} جهاز مسجّل\n"]
            rows = []
            for i, d in enumerate(devices, 1):
                created, active = d["date_created"], d["date_active"]
                created_s = created.strftime("%Y-%m-%d %H:%M") if hasattr(created, "strftime") else str(created)
                active_s = active.strftime("%Y-%m-%d %H:%M") if hasattr(active, "strftime") else str(active)
                tag = " *(البوت)*" if d["current"] else ""
                lines.append(
                    f"*{i}.* {d['device']} — {d['app']}{tag}\n"
                    f"   🌍 {d['country']} | 📅 {created_s}\n"
                    f"   🕑 آخر نشاط: {active_s}\n"
                )
            rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"contributor:acct:{stock_id}")])
            await q.edit_message_text(
                "\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows),
            )
        except Exception as e:
            logger.error(f"❌ خطأ في جلب أجهزة المؤجر للرقم {phone}: {e}")
            await q.edit_message_text(
                "❌ حدث خطأ أثناء جلب الأجهزة.", reply_markup=_back_kb(stock_id)
            )
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        return True

    return False
