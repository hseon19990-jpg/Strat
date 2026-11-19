"""Member Telegram-account buyback flow.

The flow keeps a submitted account in quarantine until two delayed checks pass.
It deliberately requires the owner to confirm the final payout manually.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})
from .accounts import check_spam_status_detailed
from .stock_ownership import bot_holds_live_session, BOT_OWNS_ACCOUNT_SELL_MESSAGE
import secrets
from string import ascii_letters, digits

BUYBACK_VISIBLE_KEY = "buyback_visible"
BUYBACK_PRICE_KEY = "buyback_price"
BUYBACK_RESTRICTED_PRICE_KEY = "buyback_restricted_price"
DEFAULT_BUYBACK_PRICE = 7000
DEFAULT_BUYBACK_RESTRICTED_PRICE = 4000
BUYBACK_ACTIVE_STATUSES = (
    "awaiting_seller_confirm",
    "quarantine_24h",
    "quarantine_48h",
    "ready_for_payment",
)

# مدة مرحلتَي الحجز والفحص (بالساعات). الافتراضي 24 + 24 = 48 ساعة كما كان،
# ويستطيع المالك تغييرهما من: إعدادات المالك ← الحسابات والمشرفون.
BUYBACK_STAGE1_HOURS_KEY = "buyback_stage1_hours"
BUYBACK_STAGE2_HOURS_KEY = "buyback_stage2_hours"
DEFAULT_BUYBACK_STAGE1_HOURS = 24
DEFAULT_BUYBACK_STAGE2_HOURS = 24
BUYBACK_STAGE_MIN_HOURS = 0      # 0 = بلا انتظار (يُفحص في أقرب دورة، كل 5 دقائق)
BUYBACK_STAGE_MAX_HOURS = 720    # 30 يوماً

BUYBACK_SESSION_MAX_BYTES = 5 * 1024 * 1024
BUYBACK_ZIP_MAX_FILES = 50
BUYBACK_ZIP_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024

# Login clients live only for the short code/2FA hand-off flow.  Keep this
# process-local and never persist the raw login code or 2FA password.
_pending_buyback_logins = {}
# Keep the seller's old 2FA password only in process memory until the
# confirmation callback. It is never persisted in the database.
_pending_buyback_passwords = {}


def _generate_buyback_2fa_password() -> str:
    """Generate a strong, readable random 2FA password for the new owner."""
    alphabet = ascii_letters + digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(20))


def is_buyback_visible() -> bool:
    return str(get_setting(BUYBACK_VISIBLE_KEY) or "0") == "1"


def set_buyback_visible(enabled: bool) -> bool:
    set_setting(BUYBACK_VISIBLE_KEY, "1" if enabled else "0")
    return bool(enabled)


def _buyback_price(restricted: bool = False) -> int:
    key = BUYBACK_RESTRICTED_PRICE_KEY if restricted else BUYBACK_PRICE_KEY
    default = DEFAULT_BUYBACK_RESTRICTED_PRICE if restricted else DEFAULT_BUYBACK_PRICE
    try:
        amount = int(get_setting(key) or default)
        return amount if amount > 0 else default
    except (TypeError, ValueError):
        return default


def set_buyback_price(points: int) -> int:
    """يحفظ سعر شراء الحساب السليم بالنقاط."""
    amount = int(points)
    if amount <= 0:
        raise ValueError("يجب أن يكون السعر أكبر من صفر")
    set_setting(BUYBACK_PRICE_KEY, str(amount))
    return amount


def set_buyback_restricted_price(points: int) -> int:
    """يحفظ سعر شراء الحساب المقيّد بالإرسال بالنقاط."""
    amount = int(points)
    if amount <= 0:
        raise ValueError("يجب أن يكون السعر أكبر من صفر")
    set_setting(BUYBACK_RESTRICTED_PRICE_KEY, str(amount))
    return amount


def _buyback_stage_hours(stage: int) -> int:
    """مدة المرحلة (1 = الفحص الأول، 2 = الفحص النهائي) بالساعات."""
    key = BUYBACK_STAGE1_HOURS_KEY if stage == 1 else BUYBACK_STAGE2_HOURS_KEY
    default = DEFAULT_BUYBACK_STAGE1_HOURS if stage == 1 else DEFAULT_BUYBACK_STAGE2_HOURS
    try:
        raw = get_setting(key)
        hours = default if raw in (None, "") else int(raw)
    except (TypeError, ValueError):
        return default
    if hours < BUYBACK_STAGE_MIN_HOURS or hours > BUYBACK_STAGE_MAX_HOURS:
        return default
    return hours


def set_buyback_stage_hours(stage: int, hours: int) -> int:
    """يحفظ مدة مرحلة الحجز. تُطبَّق على الطلبات الجديدة وعلى المراحل التي لم تبدأ بعد."""
    hours = int(hours)
    if hours < BUYBACK_STAGE_MIN_HOURS or hours > BUYBACK_STAGE_MAX_HOURS:
        raise ValueError(
            f"المدة يجب أن تكون بين {BUYBACK_STAGE_MIN_HOURS} و{BUYBACK_STAGE_MAX_HOURS} ساعة"
        )
    set_setting(BUYBACK_STAGE1_HOURS_KEY if stage == 1 else BUYBACK_STAGE2_HOURS_KEY, str(hours))
    return hours


def buyback_total_hours() -> int:
    return _buyback_stage_hours(1) + _buyback_stage_hours(2)


def format_buyback_hours(hours: int) -> str:
    """عرض مدة بالساعات بشكل مقروء: 0 / 12 ساعة / 3 أيام / 2 يوم و6 ساعات."""
    hours = int(hours)
    if hours <= 0:
        return "بدون انتظار"
    if hours < 24:
        return f"{hours} ساعة"
    days, rem = divmod(hours, 24)
    return f"{days} يوم" if rem == 0 else f"{days} يوم و{rem} ساعة"


def buyback_total_label() -> str:
    return format_buyback_hours(buyback_total_hours())


def format_buyback_price(price: int | str | None) -> str:
    """يعرض السعر الموحد في رسائل البائع والمالك."""
    try:
        amount = int(price or DEFAULT_BUYBACK_PRICE)
    except (TypeError, ValueError):
        amount = DEFAULT_BUYBACK_PRICE
    if amount <= 0:
        amount = DEFAULT_BUYBACK_PRICE
    return f"{amount:,} نقطة"


def _mask_buyback_phone(phone: str) -> str:
    phone = str(phone or "")
    if len(phone) <= 6:
        return "***"
    return phone[:4] + "***" + phone[-3:]


def _normalize_buyback_phone(raw: str) -> str | None:
    phone = (raw or "").strip().replace(" ", "")
    if phone and not phone.startswith("+") and phone.isdigit():
        phone = "+" + phone
    if not phone.startswith("+") or not phone[1:].isdigit() or len(phone) < 8 or len(phone) > 16:
        return None
    return phone


def _buyback_cancel_markup():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ إلغاء", callback_data="buyback:cancel")
    ]])


def _buyback_code_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 إعادة إرسال الكود", callback_data="buyback:resend_code")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="buyback:cancel")],
    ])


def _buyback_confirm_markup(offer_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ أؤكد بيع الحساب", callback_data=f"buyback:confirm:{offer_id}"),
        InlineKeyboardButton("❌ إلغاء", callback_data=f"buyback:cancel:{offer_id}"),
    ]])


def _buyback_owner_markup(offer_id: int, ready: bool = False):
    rows = []
    if ready:
        rows.append([InlineKeyboardButton("💵 تم دفع المستحق", callback_data=f"buyback:owner:paid:{offer_id}")])
    rows.append([InlineKeyboardButton("🚫 رفض الطلب", callback_data=f"buyback:owner:reject:{offer_id}")])
    rows.append([InlineKeyboardButton("📋 تحديث الطلبات", callback_data="buyback:owner:list")])
    return InlineKeyboardMarkup(rows)


async def _disconnect_buyback_client(client) -> None:
    if client is not None:
        try:
            await client.disconnect()
        except Exception:
            pass


async def _clear_buyback_pending(user_id: int) -> None:
    pending = _pending_buyback_logins.pop(user_id, None)
    if pending:
        await _disconnect_buyback_client(pending.get("client"))


async def _stock_session_alive(session_string: str):
    """True=جلسة البوت شغالة، False=ميتة/مطرودة، None=تعذر الفحص (شبكة...)."""
    client = None
    try:
        client = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=20)
        return bool(await asyncio.wait_for(client.is_user_authorized(), timeout=10))
    except Exception:
        return None
    finally:
        if client is not None:
            await _disconnect_buyback_client(client)


async def _active_buyback_phone_exists(phone: str) -> bool:
    """هل يُرفض الرقم؟ يُرفض فقط في حالتين:

    1) يوجد طلب بيع جارٍ لنفس الرقم (انتظار/حجز/جاهز للدفع).
    2) الرقم مسند حالياً لزبون (مؤجَّر/مباع الآن) وجلسة البوت عليه ما زالت
       شغالة، لأن استبداله سيقطع الزبون.
    غير ذلك يُقبل: لا سجل في المخزون، أو لا جلسة للبوت، أو جلسته ميتة
    (مطرود)، أو الرقم غير مسند (حتى لو بيع/دُفع سابقاً). البائع أثبت
    سيطرته بدخوله الحساب، وعند الدفع تُستبدل الجلسة القديمة بالجديدة.
    """
    with db_conn() as c:
        row = c.execute(
            "SELECT id FROM account_buyback_offers "
            "WHERE phone_number=%s AND status IN "
            "('awaiting_seller_confirm','quarantine_24h','quarantine_48h','ready_for_payment') "
            "LIMIT 1",
            (phone,),
        ).fetchone()
        if row:
            return True
        stock = c.execute(
            "SELECT id, session_string, assigned_to, last_authorized FROM number_stock "
            "WHERE phone_number=%s AND deleted_at IS NULL LIMIT 1",
            (phone,),
        ).fetchone()
    if not stock:
        return False
    if stock["assigned_to"] is None:
        return False
    if stock["last_authorized"] is False or not stock["session_string"]:
        return False
    if await _stock_session_alive(stock["session_string"]) is False:
        with db_conn() as c:
            c.execute(
                "UPDATE number_stock SET last_authorized=FALSE, "
                "kicked_at=CASE WHEN last_authorized IS FALSE THEN kicked_at ELSE NOW() END "
                "WHERE id=%s",
                (stock["id"],),
            )
        return False
    return True


async def _finish_buyback_login(update, context, user_id: int) -> bool:
    pending = _pending_buyback_logins.get(user_id)
    if not pending:
        await update.message.reply_text("⚠️ انتهت جلسة البيع. ابدأ من جديد من زر بيع الحساب.")
        context.user_data["state"] = "main_menu"
        return True

    client = pending.get("client")
    phone = pending.get("phone")
    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=15):
            raise RuntimeError("الجلسة غير مصرح بها")
        me = await asyncio.wait_for(client.get_me(), timeout=15)
        if await _active_buyback_phone_exists(phone):
            await update.message.reply_text(
                "⚠️ هذا الحساب موجود مسبقاً في طلب بيع أو في المخزون.",
                reply_markup=main_menu_kb(False),
            )
            context.user_data["state"] = "main_menu"
            return True

        session_string = client.session.save()
        username = getattr(me, "username", "") or ""
        with db_conn() as c:
            row = c.execute(
                "INSERT INTO account_buyback_offers "
                "(seller_user_id,phone_number,account_username,session_string,quoted_price,status) "
                "VALUES (%s,%s,%s,%s,0,'awaiting_seller_confirm') RETURNING id",
                (user_id, phone, username, session_string),
            ).fetchone()
        offer_id = int(row["id"])
        context.user_data["buyback_offer_id"] = offer_id
        _pending_buyback_passwords[offer_id] = pending.get("current_password")
        context.user_data["state"] = "buyback_await_confirm"
        await update.message.reply_text(
            "🔎 تم الدخول إلى الحساب بنجاح.\n\n"
            f"📱 الرقم: {_mask_buyback_phone(phone)}\n"
            f"👤 المعرف: @{username if username else 'بدون معرف'}\n"
            f"💵 السعر النهائي يُحدد بعد فحص {buyback_total_label()}: "
            f"{format_buyback_price(_buyback_price(restricted=True))} إذا كان مقيّداً، "
            f"أو {format_buyback_price(_buyback_price())} إذا كان سليماً.\n\n"
            "عند التأكيد سيتم تسجيل الحساب باسم البوت، وإلغاء الجلسات الأخرى، "
            f"ثم يبقى تحت الفحص {buyback_total_label()} قبل تحديد المبلغ النهائي. إذا كنت موافقاً اضغط تأكيد البيع.",
            reply_markup=_buyback_confirm_markup(offer_id),
        )
        return True
    except Exception as exc:
        logger.warning("فشل تجهيز طلب شراء الحساب للعضو %s: %s", user_id, type(exc).__name__)
        await update.message.reply_text(
            "❌ تعذر تجهيز الحساب للبيع. لم يتم إنشاء طلب شراء.",
            reply_markup=main_menu_kb(False),
        )
        context.user_data["state"] = "main_menu"
        return True
    finally:
        _pending_buyback_logins.pop(user_id, None)
        await _disconnect_buyback_client(client)


def _extract_buyback_session_uploads(raw_bytes: bytes, filename: str) -> list[tuple[str, bytes]]:
    """Return safe .session/.json payloads from a direct upload or ZIP archive."""
    import io as _io
    import zipfile as _zipfile

    raw = bytes(raw_bytes or b"")
    name = str(filename or "").strip()
    lower_name = name.lower()
    if not raw:
        return []
    if lower_name.endswith((".session", ".json")):
        if len(raw) > BUYBACK_SESSION_MAX_BYTES:
            return []
        return [(name or "session.session", raw)]
    if not lower_name.endswith(".zip") or len(raw) > BUYBACK_SESSION_MAX_BYTES:
        return []

    try:
        with _zipfile.ZipFile(_io.BytesIO(raw)) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if (
                len(infos) > BUYBACK_ZIP_MAX_FILES
                or sum(info.file_size for info in infos) > BUYBACK_ZIP_MAX_UNCOMPRESSED_BYTES
            ):
                return []

            session_infos = []
            json_infos = []
            for info in infos:
                normalized = str(info.filename or "").replace("\\", "/")
                short_name = normalized.rsplit("/", 1)[-1]
                if not short_name or normalized.startswith("__MACOSX/"):
                    continue
                lower_short_name = short_name.lower()
                if not lower_short_name.endswith((".session", ".json")):
                    continue
                if info.file_size > BUYBACK_SESSION_MAX_BYTES:
                    return []
                if lower_short_name.endswith(".session"):
                    session_infos.append((short_name, info))
                else:
                    json_infos.append((short_name, info))

            session_bases = {
                short_name.rsplit(".", 1)[0].casefold()
                for short_name, _info in session_infos
            }
            entries = list(session_infos)
            entries.extend(
                (short_name, info)
                for short_name, info in json_infos
                if short_name.rsplit(".", 1)[0].casefold() not in session_bases
            )
            if len(entries) > BUYBACK_ZIP_MAX_FILES:
                return []
            return [(short_name, archive.read(info)) for short_name, info in entries]
    except Exception:
        return []


def _parse_buyback_session_upload(raw_bytes: bytes, filename: str) -> str | None:
    """Extract exactly one Telethon/Pyrogram session without stock-import side effects."""
    import base64 as _base64
    import json as _json
    import os as _os
    import socket as _socket
    import sqlite3 as _sqlite3
    import struct as _struct
    import tempfile as _tempfile

    name = str(filename or "").strip().lower()
    session_string = None
    if name.endswith(".zip"):
        uploads = _extract_buyback_session_uploads(raw_bytes, filename)
        if len(uploads) != 1:
            return None
        inner_name, inner_bytes = uploads[0]
        return _parse_buyback_session_upload(inner_bytes, inner_name)
    if name.endswith(".json"):
        try:
            payload = _json.loads(bytes(raw_bytes).decode("utf-8"))
            if isinstance(payload, list):
                if len(payload) != 1:
                    return None
                payload = payload[0]
            if isinstance(payload, str):
                session_string = _maybe_convert_session(payload.strip())
            elif isinstance(payload, dict):
                if "dc_id" in payload and "auth_key" in payload:
                    session_string = pyrogram_json_to_telethon(payload)
                else:
                    candidate = payload.get("session_string") or payload.get("session") or ""
                    if isinstance(candidate, str) and candidate.strip():
                        session_string = _maybe_convert_session(candidate.strip())
        except Exception:
            return None
    elif name.endswith(".session"):
        temp_path = None
        connection = None
        try:
            with _tempfile.NamedTemporaryFile(suffix=".session", delete=False) as temp_file:
                temp_file.write(bytes(raw_bytes))
                temp_path = temp_file.name
            connection = _sqlite3.connect(f"file:{temp_path}?mode=ro", uri=True)
            connection.row_factory = _sqlite3.Row
            cursor = connection.cursor()
            try:
                rows = cursor.execute(
                    "SELECT dc_id, server_address, port, auth_key FROM sessions LIMIT 2"
                ).fetchall()
            except _sqlite3.DatabaseError:
                rows = []
            if len(rows) > 1:
                return None
            if rows and rows[0]["auth_key"] and len(bytes(rows[0]["auth_key"])) == 256:
                row = rows[0]
                dc_id = int(row["dc_id"])
                auth_key = bytes(row["auth_key"])
                try:
                    server_ip = _socket.inet_aton(str(row["server_address"]))
                    server_port = int(row["port"])
                except Exception:
                    dc = _TG_DC.get(dc_id)
                    if not dc:
                        return None
                    server_ip = _socket.inet_aton(dc[0])
                    server_port = int(dc[1])
                packed = _struct.pack(">B4sH256s", dc_id, server_ip, server_port, auth_key)
                session_string = "1" + _base64.urlsafe_b64encode(packed).decode("ascii")
            if not session_string:
                try:
                    rows = cursor.execute(
                        "SELECT dc_id, auth_key FROM sessions LIMIT 2"
                    ).fetchall()
                except _sqlite3.DatabaseError:
                    rows = []
                if len(rows) > 1:
                    return None
                if rows and rows[0]["auth_key"] and len(bytes(rows[0]["auth_key"])) == 256:
                    row = rows[0]
                    dc_id = int(row["dc_id"])
                    dc = _TG_DC.get(dc_id)
                    if not dc:
                        return None
                    packed = _struct.pack(
                        ">B4sH256s", dc_id, _socket.inet_aton(dc[0]), int(dc[1]), bytes(row["auth_key"])
                    )
                    session_string = "1" + _base64.urlsafe_b64encode(packed).decode("ascii")
        except Exception:
            return None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            if temp_path:
                try:
                    _os.unlink(temp_path)
                except OSError:
                    pass
    else:
        return None

    if not isinstance(session_string, str):
        return None
    session_string = session_string.strip()
    if not session_string or len(session_string) > 8192:
        return None
    return session_string


_TWOFA_PASSWORD_KEYS = {
    "twofa_password", "twofa", "two_fa", "2fa", "password", "pass",
    "twostep", "two_step_password", "twostepverification", "twofapassword",
    "cloud_password", "cloudpassword", "mail_password",
}


def _extract_embedded_twofa_password(payload) -> str | None:
    """يبحث داخل كائن JSON عن حقل يحمل كلمة مرور التحقق بخطوتين (2FA)،
    مهما اختلف اسم الحقل بين الحزم المختلفة (twoFA / password / 2fa ...)."""
    if not isinstance(payload, dict):
        return None
    normalized_targets = {key.replace("_", "") for key in _TWOFA_PASSWORD_KEYS}
    for key, value in payload.items():
        if not isinstance(value, str):
            continue
        normalized_key = str(key).strip().lower().replace(" ", "").replace("-", "").replace("_", "")
        if normalized_key in normalized_targets:
            candidate = value.strip()
            if candidate:
                return candidate
    return None


def _find_embedded_twofa_password(raw_bytes: bytes, filename: str) -> str | None:
    """يبحث عن كلمة مرور 2FA داخل الملف المرفوع مباشرة (JSON)، أو داخل أي ملف
    JSON موجود ضمن أرشيف ZIP — بما فيه ملف بنفس اسم ملف الجلسة (.session)،
    لأن _extract_buyback_session_uploads يستبعد ذلك الملف عمداً من اختيار
    الجلسة نفسها، فلا يجوز استبعاده أيضاً من البحث عن كلمة المرور."""
    import json as _json
    import zipfile as _zipfile
    import io as _io

    name = str(filename or "").strip().lower()
    raw = bytes(raw_bytes or b"")
    if not raw:
        return None
    try:
        if name.endswith(".json"):
            payload = _json.loads(raw.decode("utf-8"))
            if isinstance(payload, list) and len(payload) == 1:
                payload = payload[0]
            return _extract_embedded_twofa_password(payload)
        if name.endswith(".zip"):
            if len(raw) > BUYBACK_SESSION_MAX_BYTES:
                return None
            with _zipfile.ZipFile(_io.BytesIO(raw)) as archive:
                for info in archive.infolist():
                    if info.is_dir() or info.file_size > BUYBACK_SESSION_MAX_BYTES:
                        continue
                    short_name = str(info.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
                    if not short_name.lower().endswith(".json"):
                        continue
                    try:
                        payload = _json.loads(archive.read(info).decode("utf-8"))
                    except Exception:
                        continue
                    if isinstance(payload, list) and len(payload) == 1:
                        payload = payload[0]
                    found = _extract_embedded_twofa_password(payload)
                    if found:
                        return found
    except Exception:
        return None
    return None


async def handle_buyback_document(update, context) -> bool:
    """Accept seller-owned .session/.json/.zip uploads only in the buyback step."""
    user = update.effective_user
    message = update.effective_message
    document = getattr(message, "document", None) if message else None
    if not user or not document or user.id == OWNER_ID:
        return False
    if is_user_banned(user.id):
        await message.reply_text("🚫 تم حظرك من استخدام هذا البوت.")
        return True
    if is_maintenance_on():
        await message.reply_text(MAINTENANCE_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return True
    try:
        db_user = get_user(user.id)
        if db_user and db_user.get("verified", 0):
            unjoined = await get_unjoined_mandatory_channels(context, user.id)
            if unjoined:
                context.user_data["state"] = "await_mandatory_join"
                await show_mandatory_gate(update, context, unjoined, edit=False, is_owner=False)
                return True
    except Exception as exc:
        logger.warning("تعذر فحص بوابة رفع جلسة البيع للمستخدم %s: %s", user.id, type(exc).__name__)

    state = context.user_data.get("state", "")
    if state == "share_session_await_upload":
        # The earlier document route normally handles account sharing, but
        # non-owner session files arrive here first. Route only this
        # explicit upload state to its dedicated, non-destructive handler.
        from .messages import handle_share_session_document
        await handle_share_session_document(update, context)
        return True
    if state != "buyback_await_session_document":
        if state == "buyback_session_await_password":
            await message.reply_text("أرسل كلمة مرور التحقق بخطوتين كنص، أو اضغط إلغاء.", reply_markup=_buyback_cancel_markup())
        else:
            await message.reply_text("لرفع الجلسة كطريقة بيع، ابدأ من قسم بيع الحساب واختر رفع ملف الجلسة أولاً.")
        return True

    filename = str(
        getattr(document, "file_name", "")
        or (
            "upload.zip"
            if "zip" in str(getattr(document, "mime_type", "") or "").lower()
            else "upload.json"
            if "json" in str(getattr(document, "mime_type", "") or "").lower()
            else ""
        )
    )
    if not filename.lower().endswith((".session", ".json", ".zip")):
        await message.reply_text(
            "⚠️ ارفع ملفاً بصيغة .session أو .json أو .zip.",
            reply_markup=_buyback_cancel_markup(),
        )
        return True
    file_size = getattr(document, "file_size", None)
    if file_size is not None and int(file_size) > BUYBACK_SESSION_MAX_BYTES:
        await message.reply_text("⚠️ حجم الملف أكبر من الحد المسموح (5 ميغابايت).", reply_markup=_buyback_cancel_markup())
        return True
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        context.user_data["state"] = "main_menu"
        await message.reply_text("❌ إعدادات Telegram API غير مكتملة حالياً.", reply_markup=main_menu_kb(False))
        return True

    progress = await message.reply_text("⏳ جارٍ تنزيل الملف والتحقق من الجلسة...")
    client = None
    keep_client = False
    try:
        telegram_file = await context.bot.get_file(document.file_id)
        raw_bytes = bytes(await telegram_file.download_as_bytearray())
        if len(raw_bytes) > BUYBACK_SESSION_MAX_BYTES:
            await progress.edit_text("⚠️ حجم الملف أكبر من الحد المسموح (5 ميغابايت). لم يُنشأ طلب بيع.")
            return True
        session_string = _parse_buyback_session_upload(raw_bytes, filename)
        if not session_string:
            if filename.lower().endswith(".zip"):
                await progress.edit_text(
                    "❌ تعذرت قراءة جلسة واحدة صالحة. يجب أن يحتوي ZIP على ملف "
                    ".session أو .json لحساب واحد فقط؛ لم يُنشأ طلب بيع."
                )
            else:
                await progress.edit_text(
                    "❌ تعذرت قراءة جلسة واحدة صالحة من الملف. لم يُنشأ طلب بيع."
                )
            return True

        client = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            context.user_data["state"] = "buyback_await_session_document"
            await progress.edit_text("❌ الجلسة منتهية أو غير صالحة. لم يُنشأ طلب بيع؛ يمكنك رفع ملف آخر.")
            return True
        me = await asyncio.wait_for(client.get_me(), timeout=15)
        phone = _normalize_buyback_phone(getattr(me, "phone", "") or "")
        if not phone:
            context.user_data["state"] = "buyback_await_session_document"
            await progress.edit_text("❌ تعذر قراءة رقم الحساب من الجلسة. استخدم طريقة الرقم وكود الدخول بدلاً منها.")
            return True
        if await _active_buyback_phone_exists(phone):
            context.user_data["state"] = "main_menu"
            await progress.edit_text("⚠️ هذا الحساب موجود مسبقاً في طلب بيع أو في المخزون.")
            return True

        password_state = await asyncio.wait_for(client(GetPasswordRequest()), timeout=15)
        _pending_buyback_logins[user.id] = {
            "client": client,
            "phone": phone,
            "current_password": None,
            "uploaded_session": True,
        }
        keep_client = True
        if getattr(password_state, "has_password", False):
            # ─── الملف قد يحمل كلمة مرور 2FA مضمّنة (حزم الجلسات الجاهزة
            # غالباً تُرفق كلمة المرور داخل JSON) — نتحقق منها فعلياً قبل
            # أن نطلب من المستخدم كتابتها يدوياً. لا نثق بها إلا بعد تأكيد
            # تيليجرام أنها صحيحة فعلاً عبر CheckPasswordRequest.
            embedded_password = _find_embedded_twofa_password(raw_bytes, filename)
            if embedded_password:
                try:
                    check = compute_check(password_state, embedded_password)
                    await asyncio.wait_for(client(CheckPasswordRequest(check)), timeout=15)
                    _pending_buyback_logins[user.id]["current_password"] = embedded_password
                    context.user_data["state"] = "buyback_session_processing"
                    await progress.edit_text(
                        "🔒 تم العثور على كلمة مرور 2FA داخل الملف والتحقق منها بنجاح. "
                        "أراجع تفاصيل طلب البيع الآن..."
                    )
                    return await _finish_buyback_login(update, context, user.id)
                except Exception:
                    logger.info(
                        "كلمة مرور 2FA الموجودة داخل الملف المرفوع للحساب %s غير صحيحة؛ سيُطلب إدخالها يدوياً.",
                        _mask_buyback_phone(phone),
                    )
            context.user_data["state"] = "buyback_session_await_password"
            await progress.edit_text(
                chr(10).join([
                    "🔒 تم التحقق من الجلسة للحساب " + _mask_buyback_phone(phone) + ".",
                    "",
                    "الحساب محمي بكلمة مرور التحقق بخطوتين. أرسل كلمة المرور الحالية للتحقق منها؛",
                    "تبقى في الذاكرة فقط حتى تأكيد البيع ولا تُحفظ في قاعدة البيانات.",
                    "",
                    "لن يبدأ نقل الحساب إلا بعد تأكيدك النهائي.",
                ]),
                reply_markup=_buyback_cancel_markup(),
            )
            return True

        context.user_data["state"] = "buyback_session_processing"
        await progress.edit_text("✅ تم التحقق من الجلسة. أراجع تفاصيل طلب البيع الآن...")
        return await _finish_buyback_login(update, context, user.id)
    except Exception as exc:
        logger.warning(
            "تعذر التحقق من ملف جلسة بيع الحساب للمستخدم %s: %s",
            user.id,
            type(exc).__name__,
        )
        context.user_data["state"] = "buyback_await_session_document"
        try:
            await progress.edit_text("❌ تعذر التحقق من الملف الآن. لم يُنشأ طلب بيع؛ أعد المحاولة أو ألغِ.")
        except Exception:
            await message.reply_text("❌ تعذر التحقق من الملف الآن. لم يُنشأ طلب بيع؛ أعد المحاولة أو ألغِ.", reply_markup=_buyback_cancel_markup())
        return True
    finally:
        if client is not None and not keep_client:
            pending = _pending_buyback_logins.get(user.id)
            if pending and pending.get("client") is client:
                _pending_buyback_logins.pop(user.id, None)
            await _disconnect_buyback_client(client)


async def handle_buyback_text(update, context, text: str) -> bool:
    state = context.user_data.get("state", "")
    user = update.effective_user
    if not state.startswith("buyback_"):
        return False

    if state == "buyback_await_phone":
        phone = _normalize_buyback_phone(text)
        if not phone:
            await update.message.reply_text(
                "⚠️ أرسل الرقم بصيغة دولية، مثال: +9647701234567",
                reply_markup=_buyback_cancel_markup(),
            )
            return True
        if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
            await update.message.reply_text("❌ إعدادات Telegram API غير مكتملة حالياً.", reply_markup=main_menu_kb(False))
            context.user_data["state"] = "main_menu"
            return True
        if await _active_buyback_phone_exists(phone):
            await update.message.reply_text("⚠️ هذا الحساب موجود مسبقاً في طلب بيع أو في المخزون.", reply_markup=main_menu_kb(False))
            context.user_data["state"] = "main_menu"
            return True
        # للبوت جلسة حيّة على الرقم: نرفض قبل إرسال أي كود.
        if bot_holds_live_session(phone):
            await update.message.reply_text(BOT_OWNS_ACCOUNT_SELL_MESSAGE, reply_markup=main_menu_kb(False))
            context.user_data["state"] = "main_menu"
            return True
        client = TelegramClient(StringSession(), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(client.connect(), timeout=20)
            # The default delivery is often the Telegram app (777000), which
            # is easy to miss when the seller is waiting for an SMS.  Request
            # an SMS resend while still explaining that Telegram may deliver
            # the code inside the account instead.
            sent = await asyncio.wait_for(
                client.send_code_request(phone, force_sms=True),
                timeout=30,
            )
        except FloodWaitError as exc:
            await _disconnect_buyback_client(client)
            await update.message.reply_text(f"⚠️ محاولات كثيرة على الرقم. انتظر {exc.seconds} ثانية.", reply_markup=main_menu_kb(False))
            context.user_data["state"] = "main_menu"
            return True
        except PhoneNumberInvalidError:
            await _disconnect_buyback_client(client)
            await update.message.reply_text("⚠️ الرقم غير صحيح.", reply_markup=_buyback_cancel_markup())
            return True
        except Exception as exc:
            await _disconnect_buyback_client(client)
            logger.warning(f"⚠️ تعذر إرسال كود شراء الحساب: {exc}")
            await update.message.reply_text("❌ تعذر إرسال الكود حالياً. حاول لاحقاً.", reply_markup=main_menu_kb(False))
            context.user_data["state"] = "main_menu"
            return True
        _pending_buyback_logins[user.id] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
        }
        context.user_data["state"] = "buyback_await_code"
        await update.message.reply_text(
            "📩 تم طلب كود تسجيل الدخول.\n\n"
            "تحقق أولاً من رسالة Telegram الرسمية باسم <b>Telegram</b> أو الرقم "
            "<code>777000</code> داخل الحساب، وإذا لم يصل فافحص SMS.\n"
            "يمكنك الضغط على «إعادة إرسال الكود» لطلب كود جديد. أرسل آخر كود وصلك فقط؛ "
            "لن يتم حفظه.",
            parse_mode=ParseMode.HTML,
            reply_markup=_buyback_code_markup(),
        )
        return True

    if state == "buyback_await_code":
        pending = _pending_buyback_logins.get(user.id)
        if not pending:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("⚠️ انتهت جلسة الكود. ابدأ من جديد.", reply_markup=main_menu_kb(False))
            return True
        code = (text or "").replace(" ", "")
        try:
            await pending["client"].sign_in(pending["phone"], code, phone_code_hash=pending["phone_code_hash"])
        except SessionPasswordNeededError:
            context.user_data["state"] = "buyback_await_password"
            await update.message.reply_text("🔒 يوجد تحقق بخطوتين. أرسل كلمة المرور مرة واحدة فقط.", reply_markup=_buyback_cancel_markup())
            return True
        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            await update.message.reply_text("⚠️ الكود غير صحيح أو منتهي. أرسل الكود الصحيح.", reply_markup=_buyback_cancel_markup())
            return True
        except Exception as exc:
            logger.warning(f"⚠️ فشل كود شراء الحساب: {exc}")
            await _clear_buyback_pending(user.id)
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("❌ فشل تسجيل الدخول.", reply_markup=main_menu_kb(False))
            return True
        return await _finish_buyback_login(update, context, user.id)

    if state == "buyback_await_password":
        pending = _pending_buyback_logins.get(user.id)
        if not pending:
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("⚠️ انتهت جلسة التحقق. ابدأ من جديد.", reply_markup=main_menu_kb(False))
            return True
        try:
            # Keep it only in memory until the seller confirms the sale.
            # It is needed to replace an existing Telegram 2FA password.
            pending["current_password"] = (text or "").strip()
            await pending["client"].sign_in(password=(text or "").strip())
        except PasswordHashInvalidError:
            await update.message.reply_text("⚠️ كلمة المرور غير صحيحة. أرسلها مجدداً.", reply_markup=_buyback_cancel_markup())
            return True
        except Exception as exc:
            logger.warning(f"⚠️ فشل تحقق 2FA لطلب شراء الحساب: {exc}")
            await _clear_buyback_pending(user.id)
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("❌ فشل التحقق.", reply_markup=main_menu_kb(False))
            return True
        return await _finish_buyback_login(update, context, user.id)

    if state == "buyback_session_await_password":
        pending = _pending_buyback_logins.get(user.id)
        if not pending or not pending.get("uploaded_session"):
            context.user_data["state"] = "main_menu"
            await update.message.reply_text("⚠️ انتهت جلسة رفع الملف. ابدأ من جديد.", reply_markup=main_menu_kb(False))
            return True
        password = (text or "").strip()
        try:
            password_state = await asyncio.wait_for(pending["client"](GetPasswordRequest()), timeout=15)
            check = compute_check(password_state, password)
            await asyncio.wait_for(pending["client"](CheckPasswordRequest(check)), timeout=15)
        except PasswordHashInvalidError:
            await update.message.reply_text("⚠️ كلمة المرور غير صحيحة. أرسلها مجدداً.", reply_markup=_buyback_cancel_markup())
            return True
        except Exception as exc:
            logger.warning("تعذر التحقق من كلمة مرور 2FA لطلب شراء الحساب: %s", type(exc).__name__)
            await update.message.reply_text("❌ تعذر التحقق الآن. أعد المحاولة أو ألغِ.", reply_markup=_buyback_cancel_markup())
            return True
        pending["current_password"] = password
        return await _finish_buyback_login(update, context, user.id)

    if state == "buyback_await_confirm":
        await update.message.reply_text("استخدم أزرار التأكيد أو الإلغاء الظاهرة في الرسالة.")
        return True
    return False


async def _start_buyback_twofa_reset(session_string: str):
    """يبدأ مهلة تيليجرام الرسمية لحذف 2FA (نحو أسبوع) حين لا نعرف كلمة المرور
    الحالية، بدل رفض الحساب نهائياً. يُرجع موعد انتهاء المهلة أو None عند الفشل."""
    client = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return None
        result = await asyncio.wait_for(client(ResetPasswordRequest()), timeout=20)
        retry_at = getattr(result, "retry_date", None) or getattr(result, "until_date", None)
        if isinstance(retry_at, (int, float)):
            retry_at = datetime.fromtimestamp(retry_at, tz=timezone.utc)
        elif isinstance(retry_at, datetime) and retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return retry_at or (datetime.now(timezone.utc) + timedelta(days=7))
    except Exception as exc:
        logger.warning("تعذر بدء مهلة إعادة تعيين 2FA لحساب شراء: %s", type(exc).__name__)
        return None
    finally:
        await _disconnect_buyback_client(client)


async def _secure_buyback_account(
    session_string: str,
    current_password: str | None,
) -> tuple[bool, str, str | None, bool]:
    """Rotate 2FA immediately, then revoke every other Telegram session.

    If the seller supplied the old password, Telegram can change 2FA
    immediately. If the account has no 2FA, a new password is created
    directly. An account with an existing but unknown password cannot be
    secured right away: the 4th return value (``needs_reset``) tells the
    caller to start Telegram's week-long password-reset flow instead of
    rejecting the offer outright.
    """
    client = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return False, "الجلسة غير مصرح بها", None, False
        password_state = await asyncio.wait_for(client(GetPasswordRequest()), timeout=15)
        new_password = _generate_buyback_2fa_password()
        if getattr(password_state, "has_password", False):
            if not current_password:
                return (
                    False,
                    "الحساب محمي بــ2FA لكن كلمة المرور القديمة غير متوفرة.",
                    None,
                    True,
                )
            await asyncio.wait_for(
                client.edit_2fa(
                    current_password=current_password,
                    new_password=new_password,
                    hint="Auto",
                    # An empty email explicitly removes the Telegram 2FA
                    # recovery email instead of leaving the seller a way to
                    # recover the account after the sale.
                    email="",
                ),
                timeout=30,
            )
        else:
            await asyncio.wait_for(
                client.edit_2fa(
                    new_password=new_password,
                    hint="Auto",
                    email="",
                ),
                timeout=30,
            )
        # Fail closed: never accept the account if Telegram still reports a
        # configured recovery method after the password rotation.
        updated_password_state = await asyncio.wait_for(
            client(GetPasswordRequest()),
            timeout=15,
        )
        if getattr(updated_password_state, "has_recovery", False):
            return (
                False,
                "تعذر حذف بريد استرداد كلمة مرور 2FA.",
                None,
                False,
            )
        # فاصل زمني آمن قبل طرد الجلسات: تغيير 2FA ثم الطرد فوراً نمط يسهل على
        # تيليجرام كشفه كاستيلاء على حساب. الانتظار العشوائي يفصل الخطوتين.
        await asyncio.sleep(random.uniform(6, 14))
        await asyncio.wait_for(client(ResetAuthorizationsRequest()), timeout=30)
        return True, "", new_password, False
    except Exception as exc:
        return False, str(exc)[:180], None, False
    finally:
        await _disconnect_buyback_client(client)


async def _inspect_buyback_session(session_string: str) -> dict:
    """يفحص جلسة طلب البيع ويؤمّنها أثناء فترة الحجز.

    فشل الشبكة لا يلغي الطلب، بل يعيد الفحص في الدورة التالية. أما فقدان
    الجلسة أو ثبوت تقييد SpamBot فيُعامل كفشل نهائي. عند ظهور جلسة إضافية
    يحاول البوت طردها فوراً ثم يعيد قراءة التفويضات قبل اعتماد الفحص.
    """
    client = TelegramClient(StringSession(session_string), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    extra_session_removed = False
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
            return {
                "state": "reject",
                "reason": "الجلسة لم تعد مصرحاً بها",
                "extra_session_removed": False,
            }
        me = await asyncio.wait_for(client.get_me(), timeout=15)
        if not me:
            return {
                "state": "reject",
                "reason": "تعذر قراءة الحساب",
                "extra_session_removed": False,
            }
        auths = await asyncio.wait_for(client(GetAuthorizationsRequest()), timeout=20)
        sessions = getattr(auths, "authorizations", []) or []
        if len(sessions) > 1:
            try:
                await asyncio.wait_for(client(ResetAuthorizationsRequest()), timeout=30)
                extra_session_removed = True
                auths = await asyncio.wait_for(
                    client(GetAuthorizationsRequest()), timeout=20
                )
                sessions = getattr(auths, "authorizations", []) or []
            except Exception as exc:
                return {
                    "state": "retry",
                    "reason": f"ظهر دخول آخر وتعذر طرده مؤقتاً: {str(exc)[:140]}",
                    "extra_session_removed": False,
                }
            if len(sessions) > 1:
                return {
                    "state": "retry",
                    "reason": "ظهر دخول آخر وما زالت الجلسة الإضافية موجودة",
                    "extra_session_removed": extra_session_removed,
                }

        spam_detail = await asyncio.wait_for(
            check_spam_status_detailed(client), timeout=40
        )
        restricted = spam_detail.get("restricted")
        if restricted not in (True, False):
            return {
                "state": "retry",
                "reason": "تعذر التأكد من حالة الحساب عبر SpamBot مؤقتاً",
                "extra_session_removed": extra_session_removed,
            }
        return {
            "state": "ok",
            "reason": "",
            "restricted": bool(restricted),
            "extra_session_removed": extra_session_removed,
        }
    except Exception as exc:
        return {
            "state": "retry",
            "reason": str(exc)[:180],
            "extra_session_removed": extra_session_removed,
        }
    finally:
        await _disconnect_buyback_client(client)


async def _verify_buyback_session(session_string: str) -> tuple[bool, str]:
    """واجهة توافقية للفحص النهائي القديم."""
    result = await _inspect_buyback_session(session_string)
    return result["state"] == "ok", result["reason"]


async def _notify_buyback_user(context, user_id: int, text: str) -> None:
    try:
        await context.bot.send_message(user_id, text)
    except Exception as exc:
        logger.warning(f"⚠️ تعذر إشعار بائع الحساب {user_id}: {exc}")


async def _notify_buyback_owner(context, offer_id: int, ready: bool = False) -> None:
    if not OWNER_ID:
        return
    with db_conn() as c:
        row = c.execute(
            "SELECT seller_user_id,phone_number,account_username,quoted_price,status,twofa_password "
            "FROM account_buyback_offers WHERE id=%s",
            (offer_id,),
        ).fetchone()
    if not row:
        return
    price = (
        format_buyback_price(row["quoted_price"])
        if row["quoted_price"]
        else f"يُحدد بعد فحص {buyback_total_label()}"
    )
    text = (
        "💰 <b>طلب بيع حساب تيليجرام</b>\n\n"
        f"📌 الطلب: <code>#{offer_id}</code>\n"
        f"👤 البائع: <code>{row['seller_user_id']}</code>\n"
        f"📱 الرقم: <code>{html.escape(_mask_buyback_phone(row['phone_number']))}</code>\n"
        f"🔗 المعرف: @{html.escape(row['account_username'] or 'بدون معرف')}\n"
        f"💵 السعر: <b>{price}</b>\n"
        f"🔐 كلمة 2FA الجديدة: <code>{html.escape(row['twofa_password'] or 'غير متوفرة')}</code>\n"
        f"📊 الحالة: <code>{row['status']}</code>"
    )
    await context.bot.send_message(
        OWNER_ID,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=_buyback_owner_markup(offer_id, ready=ready),
    )


def _buyback_stage_labels() -> dict:
    return {
        "awaiting_seller_confirm": "⏸ بانتظار تأكيدك النهائي",
        "quarantine_24h": f"🔒 الحجز — بانتظار الفحص الأول ({format_buyback_hours(_buyback_stage_hours(1))})",
        "quarantine_48h": f"🔒 الحجز — بانتظار الفحص النهائي (بعد {buyback_total_label()} من القبول)",
        "ready_for_payment": "✅ نجح الفحص — بانتظار تحويل المبلغ",
        "paid": "💵 تم اعتماد الدفع",
        "rejected": "🚫 مرفوض",
        "cancelled": "❌ ملغى",
    }


def _format_buyback_remaining(target) -> str:
    """وقت متبقٍّ مفهوم للعضو (ساعات ودقائق) أو «قريباً» إن حان الموعد."""
    if not target:
        return ""
    try:
        seconds = int((target - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return ""
    if seconds <= 60:
        return "قريباً (خلال دقائق)"
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours:
        return f"{hours} ساعة و{minutes} دقيقة"
    return f"{minutes} دقيقة"


def user_has_buyback_offers(user_id: int) -> bool:
    try:
        with db_conn() as c:
            row = c.execute(
                "SELECT 1 FROM account_buyback_offers WHERE seller_user_id=%s LIMIT 1",
                (int(user_id),),
            ).fetchone()
        return bool(row)
    except Exception:
        return False


def render_buyback_member_status(user_id: int) -> str:
    """نص حالة طلبات البيع الخاصة بالعضو: المرحلة والوقت المتبقي والخطوة التالية."""
    with db_conn() as c:
        rows = c.execute(
            "SELECT id,phone_number,status,quoted_price,next_check_at,accepted_at,paid_at "
            "FROM account_buyback_offers WHERE seller_user_id=%s "
            "ORDER BY id DESC LIMIT 10",
            (int(user_id),),
        ).fetchall()
    if not rows:
        return "📋 *حالة طلبات البيع*\n\nلا توجد لديك طلبات بيع بعد."
    lines = ["📋 *حالة طلبات البيع*", ""]
    for row in rows:
        status = row["status"]
        lines.append(f"📌 *طلب #{row['id']}* — `{_mask_buyback_phone(row['phone_number'])}`")
        lines.append(_buyback_stage_labels().get(status, status))
        if status in ("quarantine_24h", "quarantine_48h"):
            remaining = _format_buyback_remaining(row["next_check_at"])
            if remaining:
                lines.append(f"⏳ المتبقي للفحص التالي: {remaining}")
            lines.append("➡️ لا تحتاج لفعل شيء الآن، سيصلك إشعار تلقائي عند كل مرحلة.")
        elif status == "ready_for_payment":
            if row["quoted_price"]:
                lines.append(f"💰 المبلغ: {format_buyback_price(row['quoted_price'])}")
            lines.append("➡️ المالك سيؤكد دفع المبلغ، وسيصلك إشعار عند اعتماد الدفع.")
        elif status == "paid":
            lines.append("➡️ تواصل مع المالك إن لم تستلم مستحقاتك.")
        elif status == "rejected":
            lines.append("➡️ لم يُقبل الطلب. يمكنك تقديم حساب آخر.")
        lines.append("")
    lines.append("🔔 تصلك رسالة تلقائية عند: نجاح الفحص الأول، ونجاح الفحص النهائي، واعتماد الدفع، وأي رفض.")
    return "\n".join(lines).strip()


async def handle_buyback_callback(update, context, q, data: str, user, is_owner: bool) -> bool:
    if data == "buyback:start":
        if not is_owner and not is_buyback_visible():
            await q.answer("هذا القسم غير متاح حالياً.", show_alert=True)
            return True
        await q.edit_message_text(
            "💰 <b>بيع حساب تيليجرام</b>\n\n"
            "سيتم فحص ملكية الحساب أولاً. بعد موافقتك النهائية تُلغى الجلسات الأخرى، "
            f"ويبقى الحساب تحت الحجز {buyback_total_label()}. يتم دفع المبلغ بعد نجاح الفحص الأول "
            f"({format_buyback_hours(_buyback_stage_hours(1))}) والفحص النهائي.\n\n"
            "⚠️ استخدم هذه الخدمة لحساب تملكه فقط. يمكنك التقديم برقم وكود الدخول أو برفع ملف جلسة .session أو .json أو ZIP.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 رقم + كود الدخول", callback_data="buyback:begin")],
                [InlineKeyboardButton("📁 رفع ملف جلسة (.session / .json / .zip)", callback_data="buyback:begin_session")],
                [InlineKeyboardButton("📋 حالة طلباتي", callback_data="buyback:my_status")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="buyback:cancel")],
            ]),
        )
        return True

    if data == "buyback:my_status":
        await q.edit_message_text(
            render_buyback_member_status(user.id),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 تحديث", callback_data="buyback:my_status")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="sell_rent:menu")],
            ]),
        )
        return True

    if data == "buyback:begin_session":
        if is_owner:
            await q.answer("هذا المسار مخصص للبائعين.", show_alert=True)
            return True
        if not is_buyback_visible():
            await q.answer("هذا القسم غير متاح حالياً.", show_alert=True)
            return True
        await _clear_buyback_pending(user.id)
        old_offer_id = context.user_data.pop("buyback_offer_id", None)
        if old_offer_id:
            _pending_buyback_passwords.pop(int(old_offer_id), None)
        context.user_data["state"] = "buyback_await_session_consent"
        await q.edit_message_text(
            chr(10).join([
                "📁 رفع الجلسة يمنح البوت إمكانية الدخول إلى الحساب. بعد تأكيدك النهائي سيغيّر البوت كلمة مرور 2FA إن وجدت،",
                f"ويلغي الجلسات الأخرى ويحذف بريد الاسترداد، ثم يبدأ حجز الحساب وفحصه لمدة {buyback_total_label()}.",
                "",
                "ارفع جلسة حساب تملكه أنت فقط. لن يبدأ نقل الحساب قبل تأكيد البيع في الخطوة التالية.",
            ]),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ أملك الحساب وأوافق على المتابعة", callback_data="buyback:session_consent")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="buyback:cancel")],
            ]),
        )
        return True

    if data == "buyback:session_consent":
        if is_owner or not is_buyback_visible():
            await q.answer("هذا القسم غير متاح حالياً.", show_alert=True)
            return True
        if context.user_data.get("state") != "buyback_await_session_consent":
            await q.answer("انتهت خطوة الموافقة. ابدأ من جديد.", show_alert=True)
            return True
        context.user_data["state"] = "buyback_await_session_document"
        await q.edit_message_text(
            chr(10).join([
                "📎 أرسل ملفاً بصيغة .session أو .json أو ZIP يحتوي جلسة حساب واحد فقط.",
                "",
                "يجب أن يحتوي الملف على جلسة حساب واحد فقط. لن يُستورد إلى مخزون الحسابات العادي؛",
                "سيُنشأ طلب بيع بعد التحقق، ويبقى تأكيد البيع النهائي بيدك.",
            ]),
            reply_markup=_buyback_cancel_markup(),
        )
        return True

    if data == "buyback:begin":
        await _clear_buyback_pending(user.id)
        old_offer_id = context.user_data.pop("buyback_offer_id", None)
        if old_offer_id:
            _pending_buyback_passwords.pop(int(old_offer_id), None)
        context.user_data["state"] = "buyback_await_phone"
        await q.edit_message_text("📱 أرسل رقم الحساب بصيغة دولية.", reply_markup=_buyback_cancel_markup())
        return True

    if data == "buyback:resend_code":
        pending = _pending_buyback_logins.get(user.id)
        if not pending or context.user_data.get("state") != "buyback_await_code":
            await q.answer("⚠️ انتهت جلسة الكود. ابدأ بيع الحساب من جديد.", show_alert=True)
            return True
        try:
            sent = await asyncio.wait_for(
                pending["client"].send_code_request(
                    pending["phone"],
                    force_sms=True,
                ),
                timeout=30,
            )
            pending["phone_code_hash"] = sent.phone_code_hash
            await q.answer("✅ تم طلب كود جديد.")
            await q.edit_message_text(
                "📩 تم طلب كود جديد.\n\n"
                "تحقق من رسالة Telegram الرسمية باسم <b>Telegram</b> أو الرقم "
                "<code>777000</code> داخل الحساب، ثم افحص SMS أيضاً.\n"
                "أرسل آخر كود وصلك فقط؛ لن يتم حفظه.",
                parse_mode=ParseMode.HTML,
                reply_markup=_buyback_code_markup(),
            )
        except FloodWaitError as exc:
            await q.answer(
                f"⚠️ انتظر {exc.seconds} ثانية قبل إعادة الطلب.",
                show_alert=True,
            )
        except Exception as exc:
            logger.warning(f"⚠️ تعذر إعادة إرسال كود بيع الحساب: {exc}")
            await q.answer("❌ تعذر إعادة إرسال الكود حالياً. حاول بعد قليل.", show_alert=True)
        return True

    if data == "buyback:cancel" or data.startswith("buyback:cancel:"):
        await _clear_buyback_pending(user.id)
        offer_id = data.rsplit(":", 1)[-1] if data.count(":") == 2 else ""
        if offer_id.isdigit():
            _pending_buyback_passwords.pop(int(offer_id), None)
            with db_conn() as c:
                c.execute(
                    "UPDATE account_buyback_offers SET status='cancelled', session_string=NULL, updated_at=NOW() "
                    "WHERE id=%s AND seller_user_id=%s AND status='awaiting_seller_confirm'",
                    (int(offer_id), user.id),
                )
        context.user_data["state"] = "main_menu"
        await q.edit_message_text("❌ تم إلغاء طلب بيع الحساب.", reply_markup=main_menu_kb(False))
        return True

    if data.startswith("buyback:confirm:"):
        if is_owner:
            await q.answer("هذا الزر مخصص للبائع.", show_alert=True)
            return True
        try:
            offer_id = int(data.rsplit(":", 1)[-1])
        except ValueError:
            await q.answer("طلب غير صالح.", show_alert=True)
            return True
        await q.answer("⏳ جارٍ تأمين الحساب، انتظر قليلاً...")

        with db_conn() as c:
            row = c.execute(
                "SELECT * FROM account_buyback_offers WHERE id=%s AND seller_user_id=%s AND status='awaiting_seller_confirm'",
                (offer_id, user.id),
            ).fetchone()
        if not row:
            await q.edit_message_text("⚠️ الطلب غير موجود أو انتهت صلاحيته.", reply_markup=main_menu_kb(False))
            return True
        old_password = _pending_buyback_passwords.pop(offer_id, None)
        ok, reason, new_password, needs_reset = await _secure_buyback_account(
            row["session_string"],
            old_password,
        )
        if not ok and needs_reset:
            # لا نعرف كلمة مرور 2FA الحالية: نبدأ مهلة تيليجرام الرسمية
            # (أسبوع تقريباً) بدل رفض الحساب نهائياً. ستُكمل
            # process_buyback_twofa_reset_job العملية تلقائياً عند انتهائها.
            retry_at = await _start_buyback_twofa_reset(row["session_string"])
            if retry_at:
                with db_conn() as c:
                    c.execute(
                        "UPDATE account_buyback_offers SET status='twofa_reset_pending', "
                        "twofa_reset_date=%s, updated_at=NOW() WHERE id=%s",
                        (retry_at, offer_id),
                    )
                    # الجلسة صالحة ويملكها البوت: تدخل الرشق فوراً دون انتظار مهلة 2FA.
                    _release_buyback_account_to_stock(
                        c, row["phone_number"], row["session_string"], "", paid=False
                    )
                context.user_data["state"] = "main_menu"
                await q.edit_message_text(
                    "🔒 الحساب محمي بكلمة مرور 2FA لا نعرفها.\n\n"
                    "بدأ تيليجرام مهلته الرسمية لحذفها (نحو أسبوع). "
                    "الحساب يعمل الآن في الرشق، وسيُكمَل تأمينه تلقائياً بعد "
                    "انتهاء المهلة دون أي إجراء إضافي منك، وستُبلَّغ حينها بالنتيجة.",
                    reply_markup=main_menu_kb(False),
                )
                return True
            # تعذّر حتى بدء المهلة (جلسة غير صالحة مثلاً) — نرفض كالمعتاد.
        if not ok:
            with db_conn() as c:
                c.execute(
                    "UPDATE account_buyback_offers SET status='rejected', session_string=NULL, rejection_reason=%s, updated_at=NOW() WHERE id=%s",
                    (reason, offer_id),
                )
            await q.edit_message_text("❌ تعذر تأمين الحساب، لذلك لم يتم قبول البيع.", reply_markup=main_menu_kb(False))
            return True
        with db_conn() as c:
            c.execute(
                "UPDATE account_buyback_offers SET status='quarantine_24h', "
                "accepted_at=NOW(), next_check_at=NOW()+(%s * INTERVAL '1 hour'), "
                "twofa_password=%s, updated_at=NOW() WHERE id=%s",
                (_buyback_stage_hours(1), new_password, offer_id),
            )
            _release_buyback_account_to_stock(
                c, row["phone_number"], row["session_string"], new_password, paid=False,
            )
        context.user_data["state"] = "main_menu"
        await q.edit_message_text(
            "✅ تم استلام الحساب وتأمينه.\n\n"
            f"⏳ بدأ الحجز والفحص لمدة {buyback_total_label()}. سيتم إشعارك بعد الفحص النهائي قبل تحويل المبلغ.",
            reply_markup=main_menu_kb(False),
        )
        await _notify_buyback_owner(context, offer_id)
        return True

    if data == "buyback:owner:list" and is_owner:
        text, markup = render_buyback_owner_list()
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return True

    if data.startswith("buyback:owner:paid:") and is_owner:
        try:
            offer_id = int(data.rsplit(":", 1)[-1])
        except ValueError:
            await q.answer("طلب غير صالح.", show_alert=True)
            return True
        seller_id = mark_buyback_paid(offer_id)
        if not seller_id:
            await q.answer(f"لا يمكن الدفع قبل نجاح الفحص النهائي ({buyback_total_label()}).", show_alert=True)
            return True
        await q.edit_message_text(f"✅ تم تعليم الطلب #{offer_id} كمدفوع يدوياً.", reply_markup=owner_settings_kb())
        await _notify_buyback_user(context, seller_id, f"✅ تم اعتماد دفع مستحقات طلب بيع الحساب رقم #{offer_id}. تواصل مع المالك لاستلام المبلغ.")
        return True

    if data.startswith("buyback:owner:reject:") and is_owner:
        try:
            offer_id = int(data.rsplit(":", 1)[-1])
        except ValueError:
            await q.answer("طلب غير صالح.", show_alert=True)
            return True
        seller_id = reject_buyback_offer(offer_id, "رفض المالك الطلب")
        await q.edit_message_text(f"🚫 تم رفض طلب البيع #{offer_id}.", reply_markup=owner_settings_kb())
        if seller_id:
            await _notify_buyback_user(context, seller_id, f"🚫 تم رفض طلب بيع الحساب رقم #{offer_id}.")
        return True

    return False


def render_buyback_owner_list():
    with db_conn() as c:
        rows = c.execute(
            "SELECT id,seller_user_id,phone_number,quoted_price,status,created_at,next_check_at "
            "FROM account_buyback_offers WHERE status NOT IN ('paid','cancelled','rejected') "
            "ORDER BY id DESC LIMIT 30"
        ).fetchall()
    if not rows:
        return "📋 لا توجد طلبات بيع حسابات معلقة.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")]])
    lines = ["💰 <b>طلبات بيع الحسابات</b>", ""]
    rows_kb = []
    for row in rows:
        price = (
            f"{int(row['quoted_price']):,}" if row["quoted_price"] else f"بعد فحص {buyback_total_label()}"
        )
        lines.append(f"#{row['id']} — {_mask_buyback_phone(row['phone_number'])} — {row['status']} — {price}")
        if row["status"] == "ready_for_payment":
            rows_kb.append([InlineKeyboardButton(f"💵 دفع #{row['id']}", callback_data=f"buyback:owner:paid:{row['id']}"), InlineKeyboardButton(f"🚫 رفض #{row['id']}", callback_data=f"buyback:owner:reject:{row['id']}")])
        else:
            rows_kb.append([InlineKeyboardButton(f"🚫 رفض #{row['id']}", callback_data=f"buyback:owner:reject:{row['id']}")])
    rows_kb.append([InlineKeyboardButton("🔄 تحديث", callback_data="buyback:owner:list"), InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")])
    return "\n".join(lines), InlineKeyboardMarkup(rows_kb)


def _release_buyback_account_to_stock(c, phone: str, session_string: str, twofa_password: str, *, paid: bool, keep_live: bool = False) -> None:
    """يضع الحساب المشترى في المخزون ليبدأ الرشق به فور وجوده، بلا انتظار حجز الفحص.

    paid=False (لحظة قبول البيع وتأمين الحساب): يدخل الرشق فوراً، لكنه يُستبعد
    من بيع الأرقام للأعضاء (sale_excluded) حتى يُعتمد الدفع.
    paid=True (بعد دفع المالك): يُرفع الاستبعاد فقط إن كان الحساب في المخزون
    بجلسة حيّة، وإلا يُدرج كاملاً. هكذا لا تُستبدل جلسة دوّرها البوت أثناء الرشق.
    """
    if keep_live and not paid:
        # الحساب دخل المخزون مسبقاً (مثلاً أثناء مهلة 2FA): لا نستبدل جلسته
        # الحيّة، نحدّث كلمة المرور فقط.
        row = c.execute(
            "UPDATE number_stock SET twofa_password=%s, auto_2fa_enabled=TRUE "
            "WHERE phone_number=%s AND deleted_at IS NULL "
            "AND BTRIM(COALESCE(session_string,'')) <> '' "
            "AND last_authorized IS NOT FALSE RETURNING id",
            (twofa_password, phone),
        ).fetchone()
        if row:
            return
    if paid:
        row = c.execute(
            "UPDATE number_stock SET sale_excluded=FALSE "
            "WHERE phone_number=%s AND deleted_at IS NULL "
            "AND BTRIM(COALESCE(session_string,'')) <> '' "
            "AND last_authorized IS NOT FALSE RETURNING id",
            (phone,),
        ).fetchone()
        if row:
            return
    c.execute(
        "INSERT INTO number_stock (phone_number,session_string,twofa_password,auto_2fa_enabled,"
        "assigned_to,deleted_at,ever_sold,sessions_reset,last_authorized,can_send_code,raksh_only,sale_excluded) "
        "VALUES (%s,%s,%s,TRUE,NULL,NULL,FALSE,TRUE,TRUE,FALSE,FALSE,%s) "
        "ON CONFLICT (phone_number) DO UPDATE SET "
        "session_string=EXCLUDED.session_string, twofa_password=EXCLUDED.twofa_password, "
        "auto_2fa_enabled=TRUE, assigned_to=NULL, deleted_at=NULL, ever_sold=FALSE, "
        "sessions_reset=TRUE, last_authorized=TRUE, kicked_at=NULL, raksh_only=FALSE, "
        "contributed_by=NULL, sale_excluded=EXCLUDED.sale_excluded",
        (phone, session_string, twofa_password, not paid),
    )


def mark_buyback_paid(offer_id: int) -> int | None:
    with db_conn() as c:
        row = c.execute(
            "SELECT * FROM account_buyback_offers WHERE id=%s AND status='ready_for_payment' FOR UPDATE",
            (offer_id,),
        ).fetchone()
        if not row:
            return None
        _release_buyback_account_to_stock(
            c, row["phone_number"], row["session_string"], row["twofa_password"], paid=True,
        )
        c.execute(
            "UPDATE account_buyback_offers SET status='paid', paid_at=NOW(), updated_at=NOW() WHERE id=%s",
            (offer_id,),
        )
    return int(row["seller_user_id"])


def reject_buyback_offer(offer_id: int, reason: str = "") -> int | None:
    with db_conn() as c:
        row = c.execute(
            "SELECT seller_user_id, phone_number, accepted_at FROM account_buyback_offers "
            "WHERE id=%s AND status NOT IN ('paid','cancelled','rejected') FOR UPDATE",
            (offer_id,),
        ).fetchone()
        if not row:
            return None
        if row["accepted_at"] is not None:
            # الحساب دخل المخزون/الرشق عند القبول؛ الرفض يخرجه منه (سلة المهملات).
            c.execute(
                "UPDATE number_stock SET deleted_at=NOW() "
                "WHERE phone_number=%s AND deleted_at IS NULL AND ever_sold IS NOT TRUE "
                "AND assigned_to IS NULL AND contributed_by IS NULL",
                (row["phone_number"],),
            )
        c.execute(
            "UPDATE account_buyback_offers SET status='rejected', session_string=NULL, rejection_reason=%s, updated_at=NOW() WHERE id=%s",
            (reason[:500], offer_id),
        )
    return int(row["seller_user_id"])


async def process_buyback_twofa_reset_job(context) -> None:
    """يُكمل تأمين الحسابات التي كانت محمية بكلمة مرور 2FA مجهولة بعد انتهاء
    مهلة تيليجرام الرسمية (نحو أسبوع)، ثم يتابعها بنفس مسار التأمين العادي:
    تعيين كلمة مرور جديدة، وطرد الجلسات الأخرى بفاصل زمني آمن، ثم دخول حجز
    المعتاد (المدة من إعدادات المالك، الافتراضي 48 ساعة). تُستدعى كل ساعة.
    """
    with db_conn() as c:
        rows = c.execute(
            "SELECT id, seller_user_id, session_string, phone_number FROM account_buyback_offers "
            "WHERE status='twofa_reset_pending' AND twofa_reset_date IS NOT NULL "
            "AND twofa_reset_date <= NOW() AND session_string IS NOT NULL "
            "ORDER BY twofa_reset_date LIMIT 20"
        ).fetchall()
    for row in rows:
        offer_id = int(row["id"])
        client = TelegramClient(StringSession(row["session_string"]), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        try:
            await asyncio.wait_for(client.connect(), timeout=20)
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                seller_id = reject_buyback_offer(offer_id, "الجلسة لم تعد مصرحاً بها بعد مهلة إعادة تعيين 2FA")
                if seller_id:
                    await _notify_buyback_user(context, seller_id, f"🚫 لم ينجح استكمال طلب بيع الحساب #{offer_id}، وتم إلغاء الطلب.")
                continue
            result = await asyncio.wait_for(client(ResetPasswordRequest()), timeout=20)
            retry_at = getattr(result, "retry_date", None) or getattr(result, "until_date", None)
            if retry_at:
                # تيليجرام مدّد المهلة (نادر) — نحدّث الموعد ونعيد المحاولة لاحقاً.
                if isinstance(retry_at, (int, float)):
                    retry_at = datetime.fromtimestamp(retry_at, tz=timezone.utc)
                elif isinstance(retry_at, datetime) and retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                with db_conn() as c:
                    c.execute(
                        "UPDATE account_buyback_offers SET twofa_reset_date=%s, updated_at=NOW() WHERE id=%s",
                        (retry_at, offer_id),
                    )
                continue

            new_password = _generate_buyback_2fa_password()
            await asyncio.wait_for(
                client.edit_2fa(new_password=new_password, hint="Auto", email=""),
                timeout=30,
            )
            # نفس الفاصل الآمن المستخدم في _secure_buyback_account قبل الطرد.
            await asyncio.sleep(random.uniform(6, 14))
            await asyncio.wait_for(client(ResetAuthorizationsRequest()), timeout=30)

            with db_conn() as c:
                c.execute(
                    "UPDATE account_buyback_offers SET status='quarantine_24h', "
                    "accepted_at=NOW(), next_check_at=NOW()+(%s * INTERVAL '1 hour'), "
                    "twofa_password=%s, updated_at=NOW() WHERE id=%s",
                    (_buyback_stage_hours(1), new_password, offer_id),
                )
                _release_buyback_account_to_stock(
                    c, row["phone_number"], row["session_string"], new_password, paid=False, keep_live=True,
                )
            logger.info("✅ buyback twofa-reset: اكتمل تأمين الطلب #%s بعد مهلة 2FA", offer_id)
            await _notify_buyback_user(
                context, int(row["seller_user_id"]),
                f"✅ اكتمل تأمين حساب طلب البيع #{offer_id} بعد انتهاء مهلة 2FA. سيبدأ الحجز والفحص الآن.",
            )
            await _notify_buyback_owner(context, offer_id)
        except Exception as exc:
            logger.warning("⚠️ buyback twofa-reset: فشل استكمال الطلب #%s: %s", offer_id, type(exc).__name__)
        finally:
            await _disconnect_buyback_client(client)
        await asyncio.sleep(3)


BUYBACK_BACKFILL_KEY = "buyback_backfill_instant_raksh_v2"


def _backfill_quarantined_buyback_to_stock() -> int:
    """مرة واحدة: أدخل الحسابات المحجوزة قبل التحديث إلى الرشق فوراً.

    الطلبات المقبولة قبل التحديث بقيت خارج المخزون حتى الدفع. هنا نُدرجها
    بنفس طريقة القبول الجديدة (مستبعدة من بيع الأرقام فقط). لا نستبدل جلسة
    حيّة موجودة، ولا نعيد حساباً حذفه المالك لاحقاً لأن التنفيذ مرة واحدة.
    """
    if get_setting(BUYBACK_BACKFILL_KEY) == "done":
        return 0
    added = 0
    with db_conn() as c:
        rows = c.execute(
            "SELECT o.id, o.phone_number, o.session_string, o.twofa_password "
            "FROM account_buyback_offers o "
            "WHERE o.status IN ('quarantine_24h','quarantine_48h','ready_for_payment','twofa_reset_pending') "
            "AND o.session_string IS NOT NULL AND BTRIM(o.session_string) <> '' "
            "AND NOT EXISTS (SELECT 1 FROM number_stock n "
            "  WHERE n.phone_number=o.phone_number AND n.deleted_at IS NULL "
            "  AND BTRIM(COALESCE(n.session_string,'')) <> '')"
        ).fetchall()
        for row in rows:
            _release_buyback_account_to_stock(
                c, row["phone_number"], row["session_string"],
                row["twofa_password"] or "", paid=False
            )
            added += 1
    set_setting(BUYBACK_BACKFILL_KEY, "done")
    if added:
        logger.info("✅ buyback backfill: أُدخل %s حساب محجوز إلى الرشق فوراً", added)
    return added


async def process_buyback_quarantine_job(context) -> None:
    """حلقة الحماية والفحص الدوري لطلبات بيع الحسابات.

    تُستدعى كل خمس دقائق. لذلك لا ننتظر موعد الفحصين الأول والنهائي كي نكتشف
    دخولاً جديداً أو قيداً مستجداً في SpamBot.
    """
    try:
        _backfill_quarantined_buyback_to_stock()
    except Exception:
        logger.exception("تعذر إدخال الحسابات المحجوزة القديمة إلى الرشق")
    with db_conn() as c:
        rows = c.execute(
            "SELECT id,seller_user_id,session_string,status,next_check_at "
            "FROM account_buyback_offers "
            "WHERE status IN ('quarantine_24h','quarantine_48h') "
            "ORDER BY COALESCE(last_checked_at,created_at), id LIMIT 50"
        ).fetchall()
    for row in rows:
        result = await _inspect_buyback_session(row["session_string"])
        state = result["state"]
        reason = result["reason"]
        now_due = row["next_check_at"] is not None and row["next_check_at"] <= datetime.now(timezone.utc)

        if state == "reject":
            seller_id = reject_buyback_offer(row["id"], reason)
            if seller_id:
                await _notify_buyback_user(
                    context,
                    seller_id,
                    f"🚫 لم ينجح فحص طلب بيع الحساب #{row['id']}، وتم إلغاء الطلب.",
                )
            if OWNER_ID:
                await context.bot.send_message(
                    OWNER_ID,
                    f"🚫 فشل فحص طلب بيع الحساب #{row['id']}: {html.escape(reason)}",
                    parse_mode=ParseMode.HTML,
                )
            continue

        if state == "retry":
            logger.info(
                "⏳ فحص طلب بيع الحساب #%s مؤجل: %s",
                row["id"],
                reason,
            )
            continue

        if result["extra_session_removed"]:
            security_note = (
                f"🔒 رصدت حلقة الحماية دخولاً إضافياً أثناء حجز الطلب #{row['id']} "
                "وطردته تلقائياً."
            )
            await _notify_buyback_user(context, row["seller_user_id"], security_note)
            if OWNER_ID:
                await context.bot.send_message(OWNER_ID, security_note)

        with db_conn() as c:
            c.execute(
                "UPDATE account_buyback_offers SET last_checked_at=NOW(), updated_at=NOW() "
                "WHERE id=%s AND status IN ('quarantine_24h','quarantine_48h')",
                (row["id"],),
            )

        if not now_due:
            continue

        if row["status"] == "quarantine_24h":
            with db_conn() as c:
                c.execute(
                    "UPDATE account_buyback_offers SET status='quarantine_48h', "
                    "next_check_at=NOW()+(%s * INTERVAL '1 hour'), last_checked_at=NOW(), updated_at=NOW() WHERE id=%s",
                    (_buyback_stage_hours(2), row["id"]),
                )
            await _notify_buyback_user(
                context, row["seller_user_id"],
                f"✅ نجح الفحص الأول لطلب البيع #{row['id']}. "
                f"سيستمر الحجز {format_buyback_hours(_buyback_stage_hours(2))} حتى الفحص النهائي.",
            )
        else:
            final_price = _buyback_price(restricted=bool(result.get("restricted")))
            with db_conn() as c:
                c.execute(
                    "UPDATE account_buyback_offers "
                    "SET status='ready_for_payment', quoted_price=%s, next_check_at=NULL, "
                    "last_checked_at=NOW(), updated_at=NOW() WHERE id=%s",
                    (final_price, row["id"]),
                )
            await _notify_buyback_user(
                context,
                row["seller_user_id"],
                f"✅ نجح الفحص النهائي لطلب البيع #{row['id']}. "
                f"السعر النهائي: {format_buyback_price(final_price)}. "
                "سيؤكد المالك دفع المبلغ الآن.",
            )
            await _notify_buyback_owner(context, row["id"], ready=True)
