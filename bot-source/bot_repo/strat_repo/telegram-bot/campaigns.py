"""Owner-only Telegram account profile and story campaign tools.

The campaign archive is intentionally explicit: it contains a manifest.json and the
media files referenced by that manifest. Session strings stay in the existing DB.
"""
from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import random
import re
import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from telethon import TelegramClient, functions, types
from telethon.errors import FloodWaitError, RPCError
from telethon.sessions import StringSession

logger = logging.getLogger(__name__)

_MAX_STORIES = 200
_MAX_ACCOUNTS = 100
_MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
_MAX_MEMBER_BYTES = 250 * 1024 * 1024
_ALLOWED_STORY_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v"}
_ALLOWED_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_STATE_KEY = "telegram_campaign"

_owner_id = 0
_api_id = ""
_api_hash = ""
_db_conn: Callable[..., Any] | None = None
_session_converter: Callable[[str], str] = lambda value: value


def configure_campaigns(*, owner_id: int, api_id: str, api_hash: str,
                        db_conn_fn: Callable[..., Any],
                        session_converter: Callable[[str], str]) -> None:
    global _owner_id, _api_id, _api_hash, _db_conn, _session_converter
    _owner_id = owner_id
    _api_id = api_id
    _api_hash = api_hash
    _db_conn = db_conn_fn
    _session_converter = session_converter


def _is_owner(update: Update) -> bool:
    user = update.effective_user
    return bool(user and _owner_id and user.id == _owner_id)


def _normalize_phone(value: Any) -> str:
    return re.sub(r"[^0-9+]", "", str(value or "")).replace("+", "+", 1)


def _safe_member_name(value: str) -> str:
    name = str(value or "").replace("\\", "/")
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"مسار غير آمن داخل الملف: {name}")
    return str(path)


def _manifest_text(zf: zipfile.ZipFile) -> str:
    names = {_safe_member_name(name) for name in zf.namelist() if name and not name.endswith("/")}
    if "manifest.json" not in names:
        raise ValueError("يجب أن يحتوي ZIP على ملف manifest.json")
    info = zf.getinfo("manifest.json")
    if info.file_size > 2 * 1024 * 1024:
        raise ValueError("manifest.json كبير جدًا")
    return zf.read("manifest.json").decode("utf-8")


def _validate_manifest(raw: dict[str, Any], names: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("صيغة manifest.json يجب أن تكون كائن JSON")
    accounts = raw.get("accounts")
    stories = raw.get("stories")
    if not isinstance(accounts, list) or not accounts:
        raise ValueError("أضف حسابًا واحدًا على الأقل داخل accounts")
    if len(accounts) > _MAX_ACCOUNTS:
        raise ValueError(f"الحد الأقصى للحسابات هو {_MAX_ACCOUNTS}")
    if not isinstance(stories, list):
        raise ValueError("يجب أن تكون stories قائمة بمسارات القصص")
    if len(stories) > _MAX_STORIES:
        raise ValueError(f"الحد الأقصى للقصص هو {_MAX_STORIES}")

    clean_stories: list[str] = []
    for value in stories:
        path = _safe_member_name(str(value))
        if path not in names:
            raise ValueError(f"ملف القصة غير موجود داخل ZIP: {path}")
        if PurePosixPath(path).suffix.lower() not in _ALLOWED_STORY_EXTENSIONS:
            raise ValueError(f"امتداد قصة غير مدعوم: {path}")
        clean_stories.append(path)

    clean_accounts: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for index, item in enumerate(accounts, 1):
        if not isinstance(item, dict):
            raise ValueError(f"بيانات الحساب رقم {index} غير صحيحة")
        phone = item.get("phone_number", item.get("phone"))
        stock_id = item.get("stock_id")
        if phone is None and stock_id is None:
            raise ValueError(f"الحساب رقم {index} يحتاج phone_number أو stock_id")
        key = f"id:{stock_id}" if stock_id is not None else f"phone:{_normalize_phone(phone)}"
        if key in seen_keys:
            raise ValueError(f"الحساب مكرر في manifest: {key}")
        seen_keys.add(key)
        profile_photo = item.get("profile_photo")
        clean_photo = None
        if profile_photo:
            clean_photo = _safe_member_name(str(profile_photo))
            if clean_photo not in names:
                raise ValueError(f"صورة البروفايل غير موجودة: {clean_photo}")
            if PurePosixPath(clean_photo).suffix.lower() not in _ALLOWED_PHOTO_EXTENSIONS:
                raise ValueError(f"صورة بروفايل غير مدعومة: {clean_photo}")
        clean_accounts.append({
            "phone_number": str(phone) if phone is not None else None,
            "stock_id": int(stock_id) if stock_id is not None else None,
            "first_name": str(item.get("first_name", "")),
            "last_name": str(item.get("last_name", "")),
            "bio": str(item.get("bio", item.get("about", ""))),
            "username": str(item.get("username", "")).lstrip("@"),
            "profile_photo": clean_photo,
        })

    distribution = str(raw.get("distribution", "round_robin")).lower()
    if distribution != "round_robin":
        raise ValueError("التوزيع المدعوم حاليًا هو round_robin فقط")
    return {"distribution": distribution, "stories": clean_stories, "accounts": clean_accounts}


def _validate_archive(path: str) -> dict[str, Any]:
    if os.path.getsize(path) > _MAX_ARCHIVE_BYTES:
        raise ValueError("حجم ZIP أكبر من الحد المسموح")
    with zipfile.ZipFile(path) as zf:
        names = {_safe_member_name(name) for name in zf.namelist() if name and not name.endswith("/")}
        for info in zf.infolist():
            if info.file_size > _MAX_MEMBER_BYTES:
                raise ValueError(f"ملف كبير جدًا داخل ZIP: {info.filename}")
        raw = json.loads(_manifest_text(zf))
        return _validate_manifest(raw, names)


def _cleanup_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.user_data.pop(_STATE_KEY, None)
    if isinstance(state, dict):
        path = state.get("zip_path")
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


async def campaign_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    _cleanup_state(context)
    context.user_data[_STATE_KEY] = {"stage": "zip"}
    await update.message.reply_text(
        "أرسل الآن ملف ZIP للحملة. يجب أن يحتوي على manifest.json والقصص والصور.\n\n"
        "بعد الفحص سأعرض لك المعاينة ولن يبدأ أي حساب قبل الضغط على تأكيد.\n"
        "لإلغاء العملية استخدم /campaign_cancel."
    )


async def campaign_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    _cleanup_state(context)
    await update.message.reply_text("تم إلغاء حملة النشر وحذف الملفات المؤقتة.")


async def campaign_zip_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle a ZIP only when the owner is currently creating a campaign."""
    if not _is_owner(update):
        return False
    state = context.user_data.get(_STATE_KEY)
    if not isinstance(state, dict) or state.get("stage") != "zip":
        return False
    document = update.message.document if update.message else None
    if not document:
        return True

    temp_path = ""
    try:
        tg_file = await context.bot.get_file(document.file_id)
        with tempfile.NamedTemporaryFile(prefix="telegram-campaign-", suffix=".zip", delete=False) as handle:
            temp_path = handle.name
        await tg_file.download_to_drive(custom_path=temp_path)
        manifest = _validate_archive(temp_path)
        context.user_data[_STATE_KEY] = {"stage": "confirm", "zip_path": temp_path, "manifest": manifest}
        account_count = len(manifest["accounts"])
        story_count = len(manifest["stories"])
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("تأكيد التنفيذ", callback_data="campaign_confirm"),
            InlineKeyboardButton("إلغاء", callback_data="campaign_cancel"),
        ]])
        await update.message.reply_text(
            f"تم فحص الحملة بنجاح.\n\n"
            f"الحسابات: {account_count}\n"
            f"القصص: {story_count}\n"
            f"التوزيع: round_robin\n\n"
            "سيتم تحديث الاسم والبايو واليوزر والصورة لكل حساب، ثم توزيع القصص بالتتابع.\n"
            "ابدأ فقط إذا كانت هذه التغييرات مقصودة.",
            reply_markup=keyboard,
        )
    except Exception as exc:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        context.user_data.pop(_STATE_KEY, None)
        await update.message.reply_text(f"تعذر قبول الحملة: {exc}")
    return True


def _load_session_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if _db_conn is None:
        raise RuntimeError("قاعدة البيانات غير مهيأة")
    with _db_conn() as conn:
        rows = conn.execute(
            "SELECT id, phone_number, session_string FROM number_stock "
            "WHERE session_string IS NOT NULL AND deleted_at IS NULL ORDER BY id"
        ).fetchall()
    by_id = {int(row["id"]): row for row in rows}
    by_phone = {_normalize_phone(row["phone_number"]): row for row in rows if row.get("phone_number")}
    selected: list[dict[str, Any]] = []
    for item in manifest["accounts"]:
        row = by_id.get(item["stock_id"]) if item.get("stock_id") is not None else by_phone.get(_normalize_phone(item.get("phone_number")))
        if not row:
            selector = item.get("stock_id") or item.get("phone_number")
            raise ValueError(f"لم توجد جلسة مطابقة للحساب: {selector}")
        selected.append(row)
    return selected


def _story_paths(manifest: dict[str, Any], account_index: int) -> list[str]:
    stories = manifest["stories"]
    accounts = manifest["accounts"]
    return [path for story_index, path in enumerate(stories) if story_index % len(accounts) == account_index]


def _read_zip_member(zf: zipfile.ZipFile, path: str) -> bytes:
    return zf.read(path)


async def _update_profile(client: TelegramClient, account: dict[str, Any], zf: zipfile.ZipFile) -> list[str]:
    errors: list[str] = []
    me = await client.get_me()
    if any(key in account for key in ("first_name", "last_name", "bio")):
        try:
            await client(functions.account.UpdateProfileRequest(
                first_name=account.get("first_name") or getattr(me, "first_name", "") or "",
                last_name=account.get("last_name") or getattr(me, "last_name", "") or "",
                about=account.get("bio") or getattr(me, "about", "") or "",
            ))
        except Exception as exc:
            errors.append(f"الملف التعريفي: {exc}")
    username = account.get("username", "").strip()
    if username:
        try:
            await client(functions.account.UpdateUsernameRequest(username=username))
        except Exception as exc:
            errors.append(f"اليوزر @{username}: {exc}")
    photo_path = account.get("profile_photo")
    if photo_path:
        try:
            uploaded = await client.upload_file(BytesIO(_read_zip_member(zf, photo_path)), file_name=os.path.basename(photo_path))
            await client(functions.photos.UploadProfilePhotoRequest(file=uploaded))
        except Exception as exc:
            errors.append(f"صورة البروفايل: {exc}")
    return errors


async def _send_story(client: TelegramClient, me: Any, zf: zipfile.ZipFile, path: str) -> None:
    data = _read_zip_member(zf, path)
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    uploaded = await client.upload_file(BytesIO(data), file_name=os.path.basename(path))
    if mime.startswith("image/"):
        media = types.InputMediaUploadedPhoto(file=uploaded)
    else:
        attributes = [types.DocumentAttributeVideo(duration=0, w=0, h=0, supports_streaming=True)]
        media = types.InputMediaUploadedDocument(file=uploaded, mime_type=mime, attributes=attributes)
    await client(functions.stories.SendStoryRequest(
        peer=me,
        media=media,
        privacy_rules=[types.InputPrivacyValueAllowAll()],
        random_id=random.randint(-(1 << 63), (1 << 63) - 1),
    ))


async def _run_campaign(zip_path: str, manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    selected = _load_session_rows(manifest)
    results: list[dict[str, Any]] = []
    fatal: str | None = None
    with zipfile.ZipFile(zip_path) as zf:
        for account_index, account in enumerate(manifest["accounts"]):
            row = selected[account_index]
            result = {"account": account.get("phone_number") or f"id:{account.get('stock_id')}", "profile_errors": [], "stories_ok": 0, "stories_failed": 0}
            client: TelegramClient | None = None
            try:
                session = _session_converter(str(row["session_string"]))
                client = TelegramClient(StringSession(session), int(_api_id), _api_hash)
                await asyncio.wait_for(client.connect(), timeout=20)
                if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                    raise RuntimeError("الجلسة غير مصرّح بها")
                result["profile_errors"] = await _update_profile(client, account, zf)
                me = await client.get_me()
                for story_path in _story_paths(manifest, account_index):
                    try:
                        await _send_story(client, me, zf, story_path)
                        result["stories_ok"] += 1
                        await asyncio.sleep(1.5)
                    except FloodWaitError as exc:
                        fatal = f"توقف آمن بسبب FloodWait لمدة {exc.seconds} ثانية عند الحساب {result['account']}"
                        result["stories_failed"] += 1
                        break
                    except Exception as exc:
                        result["stories_failed"] += 1
                        logger.warning("Campaign story failed for account %s: %s", result["account"], exc)
                if fatal:
                    results.append(result)
                    break
            except FloodWaitError as exc:
                fatal = f"توقف آمن بسبب FloodWait لمدة {exc.seconds} ثانية عند الحساب {result['account']}"
                results.append(result)
                break
            except Exception as exc:
                result["profile_errors"].append(str(exc))
            finally:
                if client is not None:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
            results.append(result)
            await asyncio.sleep(1.5)
    return results, fatal


def _report(results: list[dict[str, Any]], fatal: str | None) -> str:
    lines = ["انتهت حملة النشر.", ""]
    for index, result in enumerate(results, 1):
        errors = len(result["profile_errors"])
        lines.append(
            f"{index}. {result['account']} — القصص: {result['stories_ok']} ناجحة / "
            f"{result['stories_failed']} فاشلة — أخطاء الملف: {errors}"
        )
    if fatal:
        lines.extend(["", f"تنبيه: {fatal}"])
    if not results:
        lines.append("لم يتم تنفيذ أي حساب.")
    return "\n".join(lines)


async def campaign_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not _is_owner(update):
        return
    await query.answer()
    state = context.user_data.get(_STATE_KEY)
    if not isinstance(state, dict) or state.get("stage") != "confirm":
        await query.edit_message_text("لا توجد حملة معلقة.")
        return
    if query.data == "campaign_cancel":
        _cleanup_state(context)
        await query.edit_message_text("تم إلغاء الحملة وحذف الملفات المؤقتة.")
        return
    await query.edit_message_text("بدأ التنفيذ. سأرسل لك النتيجة بعد معالجة الحسابات بالتتابع...")
    try:
        results, fatal = await _run_campaign(state["zip_path"], state["manifest"])
        await context.bot.send_message(chat_id=update.effective_chat.id, text=_report(results, fatal))
    except Exception as exc:
        logger.exception("Campaign failed")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"فشلت الحملة قبل الإكمال: {exc}")
    finally:
        _cleanup_state(context)


# ────────────────────────────────────────────────────────────
# تفاصيل حسابات الأرقام — واجهة المالك
# ────────────────────────────────────────────────────────────
_ACCOUNT_DETAILS_KEY = "account_details_campaign"

def account_details_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 بايو الأرقام", callback_data="account_details:bio")],
        [InlineKeyboardButton("📖 ستوري الأرقام", callback_data="account_details:stories")],
        [InlineKeyboardButton("🔤 اسم الأرقام", callback_data="account_details:name")],
        [InlineKeyboardButton("@ يوزر الأرقام", callback_data="account_details:username")],
        [InlineKeyboardButton("🖼 أفتار / صور الأرقام", callback_data="account_details:avatar")],
        [InlineKeyboardButton("📤 إرسال المعلومات", callback_data="account_details:send")],
        [InlineKeyboardButton("🗑 مسح المعلومات", callback_data="account_details:clear")],
        [InlineKeyboardButton("🔙 إعدادات المالك", callback_data="owner_settings")],
    ])

def _new_account_details_state() -> dict[str, Any]:
    return {
        "stage": "menu", "bios": {}, "names": {}, "usernames": {},
        "avatars": {}, "stories": [],
        "media_dir": tempfile.mkdtemp(prefix="telegram-account-details-"),
    }

def _details_state(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    state = context.user_data.get(_ACCOUNT_DETAILS_KEY)
    if not isinstance(state, dict):
        state = _new_account_details_state()
        context.user_data[_ACCOUNT_DETAILS_KEY] = state
    return state

def _details_phone(value: str) -> str:
    return re.sub(r"[^0-9+]", "", str(value or ""))

def _details_menu_text(state: dict[str, Any]) -> str:
    return (
        "👤 تفاصيل الحسابات\n\n"
        f"البايو: {len(state.get('bios', {}))}\n"
        f"الأسماء: {len(state.get('names', {}))}\n"
        f"اليوزرات: {len(state.get('usernames', {}))}\n"
        f"الأفتارات: {len(state.get('avatars', {}))}\n"
        f"الستوريات: {len(state.get('stories', []))}\n\n"
        "اختر القسم وأرسل بياناته، وبعد الانتهاء اضغط إرسال المعلومات."
    )

async def account_details_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or update.effective_user.id != _owner_id:
        return
    state = _details_state(context)
    query = update.callback_query
    text = _details_menu_text(state)
    if query:
        await query.edit_message_text(text, reply_markup=account_details_kb())
    elif update.message:
        await update.message.reply_text(text, reply_markup=account_details_kb())

async def account_details_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user or update.effective_user.id != _owner_id:
        return
    await query.answer()
    action = (query.data or "").split(":", 1)[-1]
    state = _details_state(context)
    if action == "menu":
        await account_details_open(update, context)
        return
    if action == "clear":
        shutil.rmtree(state.get("media_dir", ""), ignore_errors=True)
        context.user_data[_ACCOUNT_DETAILS_KEY] = _new_account_details_state()
        await query.edit_message_text("تم مسح تفاصيل الحملة الحالية.", reply_markup=account_details_kb())
        return
    if action == "send":
        if not state.get("stories") and not any(state.get(k) for k in ("bios", "names", "usernames", "avatars")):
            await query.answer("أرسل بيانات واحدة على الأقل أولاً.", show_alert=True)
            return
        state["stage"] = "running"
        await query.edit_message_text("بدأت معالجة تفاصيل الحسابات بالتتابع...", reply_markup=None)
        try:
            zip_path, manifest = _build_details_archive(state)
            results, fatal = await _run_campaign(zip_path, manifest)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=_report(results, fatal))
            try:
                os.unlink(zip_path)
            except OSError:
                pass
        except Exception as exc:
            logger.exception("Account details campaign failed")
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"فشلت العملية: {exc}")
        finally:
            _cleanup_account_details(context)
        return
    prompts = {
        "bio": "أرسل البايو بهذا الشكل، سطرًا لكل حساب:\nرقم الحساب | البايو",
        "name": "أرسل الاسم بهذا الشكل:\nرقم الحساب | الاسم الأول | اللقب",
        "username": "أرسل اليوزر بهذا الشكل:\nرقم الحساب | username",
        "stories": "أرسل الآن صور أو فيديوهات الستوريات واحدًا بعد الآخر. سيتم توزيعها بالتتابع.",
        "avatar": "أرسل صورة الأفتار واكتب رقم الحساب في Caption للصورة.",
    }
    if action in prompts:
        state["stage"] = action
        await query.edit_message_text(prompts[action], reply_markup=account_details_kb())

def _parse_detail_lines(text: str, kind: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for raw_line in text.splitlines():
        parts = [part.strip() for part in raw_line.split("|")]
        if len(parts) < 2:
            continue
        phone = _details_phone(parts[0])
        if not phone:
            continue
        if kind == "bio":
            parsed[phone] = parts[1]
        elif kind == "username":
            parsed[phone] = parts[1].lstrip("@")
        elif kind == "name":
            parsed[phone] = {"first_name": parts[1], "last_name": parts[2] if len(parts) >= 3 else ""}
    return parsed

async def account_details_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    state = context.user_data.get(_ACCOUNT_DETAILS_KEY)
    if not user or user.id != _owner_id or not isinstance(state, dict) or state.get("stage") not in {"bio", "name", "username"}:
        return False
    parsed = _parse_detail_lines((update.message.text or "").strip(), state["stage"] )
    if not parsed:
        await update.message.reply_text("الصيغة غير صحيحة. استخدم | بين رقم الحساب والبيانات.")
        return True
    key = {"bio": "bios", "name": "names", "username": "usernames"}[state["stage"]]
    state.setdefault(key, {}).update(parsed)
    state["stage"] = "menu"
    await update.message.reply_text(f"تم حفظ {len(parsed)} حساب.", reply_markup=account_details_kb())
    return True

async def account_details_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    state = context.user_data.get(_ACCOUNT_DETAILS_KEY)
    if not user or user.id != _owner_id or not isinstance(state, dict) or state.get("stage") not in {"stories", "avatar"}:
        return False
    message = update.message
    file_id = None
    extension = ".bin"
    if message.photo:
        file_id, extension = message.photo[-1].file_id, ".jpg"
    elif message.video:
        file_id, extension = message.video.file_id, ".mp4"
    if not file_id:
        return False
    media_dir = state.get("media_dir") or tempfile.mkdtemp(prefix="telegram-account-details-")
    state["media_dir"] = media_dir
    if state["stage"] == "avatar":
        phone = _details_phone(message.caption or "")
        if not phone:
            await message.reply_text("اكتب رقم الحساب في Caption للصورة.")
            return True
        target = os.path.join(media_dir, f"avatar_{len(state['avatars'])}{extension}")
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(custom_path=target)
        state.setdefault("avatars", {})[phone] = target
        await message.reply_text(f"تم حفظ أفتار الحساب {phone}.", reply_markup=account_details_kb())
    else:
        target = os.path.join(media_dir, f"story_{len(state['stories'])}{extension}")
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(custom_path=target)
        state.setdefault("stories", []).append(target)
        await message.reply_text(f"تم حفظ الستوري رقم {len(state['stories'])}.", reply_markup=account_details_kb())
    return True

def _all_detail_rows() -> list[dict[str, Any]]:
    if _db_conn is None:
        raise RuntimeError("قاعدة البيانات غير مهيأة")
    with _db_conn() as conn:
        return conn.execute("SELECT id, phone_number, session_string FROM number_stock WHERE session_string IS NOT NULL AND deleted_at IS NULL ORDER BY id").fetchall()

def _build_details_archive(state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    rows = _all_detail_rows()
    if not rows:
        raise ValueError("لا توجد حسابات بجلسات صالحة في مخزون البوت")
    zip_path = tempfile.mktemp(prefix="telegram-account-details-", suffix=".zip")
    stories: list[str] = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for index, source in enumerate(state.get("stories", []), 1):
            name = f"stories/{index:03d}{PurePosixPath(source).suffix.lower()}"
            zf.write(source, name)
            stories.append(name)
        avatar_paths: dict[str, str] = {}
        for index, (phone, source) in enumerate(state.get("avatars", {}).items(), 1):
            name = f"profiles/{index:03d}{PurePosixPath(source).suffix.lower()}"
            zf.write(source, name)
            avatar_paths[phone] = name
        accounts = []
        for row in rows:
            phone = _details_phone(row.get("phone_number", ""))
            name_data = state.get("names", {}).get(phone, {})
            accounts.append({"phone_number": row.get("phone_number"), "first_name": name_data.get("first_name", "") if isinstance(name_data, dict) else "", "last_name": name_data.get("last_name", "") if isinstance(name_data, dict) else "", "bio": state.get("bios", {}).get(phone, ""), "username": state.get("usernames", {}).get(phone, ""), "profile_photo": avatar_paths.get(phone)})
        zf.writestr("manifest.json", json.dumps({"distribution": "round_robin", "stories": stories, "accounts": accounts}, ensure_ascii=False, indent=2))
    return zip_path, {"distribution": "round_robin", "stories": stories, "accounts": accounts}

def _cleanup_account_details(context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.user_data.pop(_ACCOUNT_DETAILS_KEY, None)
    if isinstance(state, dict):
        shutil.rmtree(state.get("media_dir", ""), ignore_errors=True)