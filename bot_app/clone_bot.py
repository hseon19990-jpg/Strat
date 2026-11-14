"""قسم «🤖 إنشاء بوت كهذا»: أي عضو ينشئ بوتاً مطابقاً لهذا البوت ويكون مالكه.

كيف يعمل (ملخص):
1. العضو ينشئ بوتاً من @BotFather ويرسل التوكن هنا.
2. نتحقق من التوكن (getMe)، ثم نُنشئ للبوت الجديد مخطط PostgreSQL مستقلاً
   (clone_<bot_id>) داخل نفس قاعدة البيانات، فتكون بياناته وأعضاؤه وأرصدته
   منفصلة تماماً عن البوت الأصلي.
3. نشغّل نسخة من نفس الكود (`python bot.py`) كعملية فرعية بمتغيرات خاصة:
   BOT_TOKEN = توكن العضو، OWNER_ID = آيدي العضو، BOT_DB_SCHEMA = مخططه.
4. مشرف داخلي (thread) يعيد تشغيل أي بوت يتعطل، ويُشغّل كل البوتات «العاملة»
   تلقائياً بعد إعادة تشغيل/نشر البوت الأصلي.

الأمان:
- لا تُمرَّر أسرار البوت الأصلي إلى البوتات المستنسخة: كل متغير بيئة اسمه يحوي
  KEY / TOKEN / SECRET / PASSWORD... يُحذف (مفاتيح اللوحات والذكاء الاصطناعي وغيرها)،
  وكذلك ADMIN_GROUP_ID وNUMBERS_GROUP_ID. يبقى فقط DATABASE_URL (مع عزل المخطط)
  وTELEGRAM_API_ID/HASH.
- البوت المستنسخ لا يعرض هذا القسم ولا يشغّل مشرفاً (لا استنساخ متسلسل).
- لا نعرض التوكن أبداً ولا نكتب نص سجلات البوتات في الرسائل (قد يحوي التوكن).

callback_data:
  clone:start / new / mine / view:<id> / stop:<id> / run:<id> / del:<id> / delok:<id>
  clone:panel / toggle / all / limits            — لوحة المالك (للمالك فقط)
حالات النص: clone_await_token (العضو) / os_await_clone_limits (المالك)
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

import atexit
import sys
import tempfile
import threading
from pathlib import Path

# ── مفاتيح الإعدادات ──
CLONE_ENABLED_KEY = "clone_bot_enabled"          # "0" = مخفي، أي شيء آخر = ظاهر
CLONE_MAX_PER_USER_KEY = "clone_max_per_user"    # عدد البوتات المسموح لكل عضو
CLONE_MAX_TOTAL_KEY = "clone_max_total"          # الحد الأقصى لكل البوتات المستنسخة
CLONE_DEFAULT_PER_USER = 1
CLONE_DEFAULT_TOTAL = 10
CLONE_LIMIT_CEILING = 100

CLONE_TOKEN_STATE = "clone_await_token"
CLONE_LIMITS_STATE = "os_await_clone_limits"
CLONE_BUTTON_LABEL = "🤖 إنشاء بوت كهذا"

_CLONE_TOKEN_RE = re.compile(r"^\d{6,14}:[A-Za-z0-9_-]{30,60}$")
_CLONE_SCHEMA_RE = re.compile(r"^clone_\d+$")

# ── إعدادات التشغيل ──
_CLONE_ROOT = Path(__file__).resolve().parents[1]          # مجلد فيه bot.py
_CLONE_LOG_DIR = Path(tempfile.gettempdir()) / "clone_logs"
_CLONE_LOG_MAX_BYTES = 1_000_000
_CLONE_CHECK_INTERVAL = 20          # ثوانٍ بين فحوص المشرف
_CLONE_QUICK_DEATH_SEC = 60         # عملية ماتت قبل هذا = فشل سريع (backoff)
_CLONE_BACKOFF_BASE = 10
_CLONE_BACKOFF_MAX = 300
_CLONE_STOP_TIMEOUT = 8
_CLONE_POOL_MAX = "6"

# متغيرات البيئة التي تُحذف من البوت المستنسخ، ما لم تكن في قائمة الاستثناء.
_CLONE_SENSITIVE_ENV_RE = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|SESSION)", re.IGNORECASE
)
_CLONE_ENV_DROP = {
    "BOT_TOKEN", "OWNER_ID", "ADMIN_GROUP_ID", "NUMBERS_GROUP_ID",
    "OWNER_WEBAPP_URL", "PORT",
}
_CLONE_ENV_KEEP = {
    "TELEGRAM_API_ID", "TELEGRAM_API_HASH",
    "DATABASE_URL", "DB_FILE", "POSTGRES_URL", "POSTGRESQL_URL",
}

# أخطاء في سجل البوت تعني أن التوكن لم يعد صالحاً (فنتوقف عن إعادة المحاولة).
_CLONE_FATAL_LOG_RE = re.compile(r"\[InvalidToken\]|rejected by the server|\[Unauthorized\]", re.IGNORECASE)

_CLONE_PROCS: dict = {}       # clone_id -> subprocess.Popen
_CLONE_STATE: dict = {}       # clone_id -> {"started": t, "fails": n, "next_at": t}
_CLONE_LOCK = threading.RLock()
_CLONE_SUPERVISOR = {"started": False}


# ────────────────────────────────────────────────────────────
# أدوات عامة
# ────────────────────────────────────────────────────────────
def clone_is_child() -> bool:
    """True داخل عملية بوت مستنسخ: لا يعرض القسم ولا يشغّل مشرفاً."""
    return os.environ.get("BOT_CLONE_CHILD", "") == "1"


def clone_is_enabled() -> bool:
    return (get_setting(CLONE_ENABLED_KEY) or "1") != "0"


def clone_button_row(is_owner: bool = False) -> list:
    """صف زر القسم في القائمة الرئيسية (فارغ إذا كان مخفياً أو داخل بوت مستنسخ)."""
    try:
        if clone_is_child() or not clone_is_enabled():
            return []
    except Exception:
        return []
    return [[InlineKeyboardButton(CLONE_BUTTON_LABEL, callback_data="clone:start")]]


def _clone_limit(key: str, default: int) -> int:
    try:
        value = int((get_setting(key) or "").strip() or default)
    except (TypeError, ValueError):
        value = default
    return max(0, min(value, CLONE_LIMIT_CEILING))


def clone_max_per_user() -> int:
    return _clone_limit(CLONE_MAX_PER_USER_KEY, CLONE_DEFAULT_PER_USER)


def clone_max_total() -> int:
    return _clone_limit(CLONE_MAX_TOTAL_KEY, CLONE_DEFAULT_TOTAL)


def _clone_back_kb(target: str = "main_menu", label: str = "🔙 القائمة الرئيسية") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=target)]])


# ────────────────────────────────────────────────────────────
# قاعدة البيانات
# ────────────────────────────────────────────────────────────
def clone_db_list(owner_user_id: int | None = None) -> list:
    with db_conn() as c:
        if owner_user_id is None:
            rows = c.execute("SELECT * FROM cloned_bots ORDER BY id").fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM cloned_bots WHERE owner_user_id=? ORDER BY id", (int(owner_user_id),)
            ).fetchall()
    return list(rows or [])


def clone_db_get(clone_id: int):
    with db_conn() as c:
        return c.execute("SELECT * FROM cloned_bots WHERE id=?", (int(clone_id),)).fetchone()


def clone_db_get_by_bot_id(bot_id: int):
    with db_conn() as c:
        return c.execute("SELECT * FROM cloned_bots WHERE bot_id=?", (int(bot_id),)).fetchone()


def _clone_db_update(clone_id: int, **fields) -> None:
    allowed = {"desired_state", "last_error", "bot_username", "bot_name"}
    sets, values = [], []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(key)
        sets.append(f"{key}=?")
        values.append(value)
    if not sets:
        return
    values.append(int(clone_id))
    with db_conn() as c:
        c.execute(f"UPDATE cloned_bots SET {', '.join(sets)} WHERE id=?", tuple(values))


def _clone_quote_schema(schema: str) -> str:
    if not _CLONE_SCHEMA_RE.fullmatch(schema or ""):
        raise ValueError("invalid schema name")
    return f'"{schema}"'


def _clone_ensure_schema(schema: str) -> None:
    with db_conn() as c:
        c.execute(f"CREATE SCHEMA IF NOT EXISTS {_clone_quote_schema(schema)}")


def _clone_drop_schema(schema: str) -> None:
    with db_conn() as c:
        c.execute(f"DROP SCHEMA IF EXISTS {_clone_quote_schema(schema)} CASCADE")


# ────────────────────────────────────────────────────────────
# Telegram (التحقق من التوكن)
# ────────────────────────────────────────────────────────────
def _clone_tg_get_me(token: str) -> dict:
    """getMe متزامن. يرفع RuntimeError('invalid_token' | 'network') دون إظهار التوكن."""
    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15)
    except requests.RequestException:
        raise RuntimeError("network") from None
    if response.status_code in (401, 404):
        raise RuntimeError("invalid_token")
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError("network") from None
    result = data.get("result") if isinstance(data, dict) else None
    if response.status_code != 200 or not data.get("ok") or not isinstance(result, dict) or not result.get("is_bot"):
        raise RuntimeError("invalid_token")
    return result


def _clone_tg_delete_webhook(token: str) -> None:
    """البوت المستنسخ يعمل بالـ polling: نحذف أي webhook قديم حتى لا يحدث Conflict."""
    try:
        requests.post(f"https://api.telegram.org/bot{token}/deleteWebhook", timeout=15)
    except requests.RequestException:
        pass


# ────────────────────────────────────────────────────────────
# إدارة العمليات
# ────────────────────────────────────────────────────────────
def _clone_log_path(clone_id: int) -> Path:
    return _CLONE_LOG_DIR / f"{int(clone_id)}.log"


def _clone_child_env(row) -> dict:
    """بيئة البوت المستنسخ: بدون أي أسرار من البوت الأصلي."""
    env = {}
    for name, value in os.environ.items():
        if name in _CLONE_ENV_KEEP:
            env[name] = value
        elif name in _CLONE_ENV_DROP or _CLONE_SENSITIVE_ENV_RE.search(name):
            continue
        else:
            env[name] = value
    env.update({
        "BOT_TOKEN": row["token"],
        "OWNER_ID": str(int(row["owner_user_id"])),
        "BOT_DB_SCHEMA": row["schema_name"],
        "BOT_DB_POOL_MAX": _CLONE_POOL_MAX,
        "BOT_CLONE_CHILD": "1",
        "PORT": "0",                 # منفذ صحي عشوائي: لا يتعارض مع البوت الأصلي
        "PYTHONUNBUFFERED": "1",
    })
    return env


def _clone_is_alive(clone_id: int) -> bool:
    proc = _CLONE_PROCS.get(int(clone_id))
    return bool(proc and proc.poll() is None)


def _clone_log_tail(clone_id: int, size: int = 4000) -> str:
    try:
        with open(_clone_log_path(clone_id), "rb") as fh:
            fh.seek(0, os.SEEK_END)
            end = fh.tell()
            fh.seek(max(0, end - size))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def clone_spawn(row) -> bool:
    """يشغّل البوت المستنسخ إن لم يكن يعمل. يرجع True عند النجاح."""
    clone_id = int(row["id"])
    with _CLONE_LOCK:
        if _clone_is_alive(clone_id):
            return True
        try:
            _clone_ensure_schema(row["schema_name"])
            _CLONE_LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_path = _clone_log_path(clone_id)
            if log_path.exists() and log_path.stat().st_size > _CLONE_LOG_MAX_BYTES:
                log_path.unlink()
            with open(log_path, "ab") as log_file:
                proc = subprocess.Popen(
                    [sys.executable, "bot.py"],
                    cwd=str(_CLONE_ROOT),
                    env=_clone_child_env(row),
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except Exception:
            logger.exception("clone: فشل تشغيل البوت المستنسخ %s", clone_id)
            return False
        _CLONE_PROCS[clone_id] = proc
        state = _CLONE_STATE.setdefault(clone_id, {"fails": 0, "next_at": 0.0})
        state["started"] = time.time()
        logger.info("clone: تم تشغيل البوت المستنسخ %s (@%s) pid=%s", clone_id, row.get("bot_username"), proc.pid)
        return True


def clone_terminate(clone_id: int) -> None:
    """يوقف عملية البوت المستنسخ (إن وُجدت) بلطف ثم بالقوة."""
    with _CLONE_LOCK:
        proc = _CLONE_PROCS.pop(int(clone_id), None)
    if not proc or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=_CLONE_STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=_CLONE_STOP_TIMEOUT)
        except Exception:
            pass
    except Exception:
        logger.exception("clone: فشل إيقاف البوت المستنسخ %s", clone_id)


def _clone_stop_all() -> None:
    for clone_id in list(_CLONE_PROCS):
        try:
            clone_terminate(clone_id)
        except Exception:
            pass


def _clone_supervise_once() -> None:
    rows = clone_db_list()
    wanted = {int(r["id"]): r for r in rows if r["desired_state"] == "running"}

    # أي عملية لم تعد مطلوبة (متوقفة/محذوفة) نوقفها.
    for clone_id in list(_CLONE_PROCS):
        if clone_id not in wanted:
            clone_terminate(clone_id)

    now = time.time()
    for clone_id, row in wanted.items():
        state = _CLONE_STATE.setdefault(clone_id, {"fails": 0, "next_at": 0.0, "started": 0.0})
        if _clone_is_alive(clone_id):
            # البوت يعيد المحاولة داخلياً للأبد مع توكن ملغى: نكشف ذلك من السجل.
            if _CLONE_FATAL_LOG_RE.search(_clone_log_tail(clone_id)):
                clone_terminate(clone_id)
                _clone_db_update(
                    clone_id, desired_state="stopped",
                    last_error="التوكن غير صالح أو تم إلغاؤه من BotFather. أنشئ توكناً جديداً.",
                )
            elif now - state.get("started", 0.0) > _CLONE_QUICK_DEATH_SEC:
                state["fails"] = 0
            continue
        if now < state.get("next_at", 0.0):
            continue
        died_fast = state.get("started", 0.0) and (now - state["started"]) < _CLONE_QUICK_DEATH_SEC
        state["fails"] = state.get("fails", 0) + 1 if died_fast else 0
        state["next_at"] = now + min(_CLONE_BACKOFF_BASE * (2 ** state["fails"]), _CLONE_BACKOFF_MAX)
        if not clone_spawn(row):
            _clone_db_update(clone_id, last_error="تعذّر تشغيل البوت، ستتم إعادة المحاولة تلقائياً.")


def _clone_supervisor_loop() -> None:
    while True:
        try:
            _clone_supervise_once()
        except Exception:
            logger.exception("clone: فشل دورة المشرف")
        time.sleep(_CLONE_CHECK_INTERVAL)


def clone_supervisor_start() -> None:
    """يشغّل مشرف البوتات المستنسخة مرة واحدة (آمن عند إعادة تشغيل main داخلياً)."""
    if clone_is_child():
        return
    with _CLONE_LOCK:
        if _CLONE_SUPERVISOR["started"]:
            return
        _CLONE_SUPERVISOR["started"] = True
    atexit.register(_clone_stop_all)
    threading.Thread(target=_clone_supervisor_loop, name="clone-supervisor", daemon=True).start()
    logger.info("🤖 تم تفعيل مشرف البوتات المستنسخة")


# ────────────────────────────────────────────────────────────
# النصوص والواجهة
# ────────────────────────────────────────────────────────────
def _clone_status_label(row) -> str:
    if row["desired_state"] != "running":
        return "⏹ متوقف"
    if _clone_is_alive(int(row["id"])):
        return "🟢 يعمل"
    return "🟡 قيد التشغيل"


def _clone_title(row) -> str:
    username = (row.get("bot_username") or "").strip()
    return f"@{username}" if username else f"#{row['id']}"


def _clone_intro_text(count: int, limit: int) -> str:
    lines = [
        "🤖 <b>إنشاء بوت كهذا</b>",
        "",
        "احصل على بوت خاص بك مطابق لهذا البوت بالضبط، وتكون أنت مالكه ولك لوحة المالك كاملة فيه.",
        "",
        "📝 <b>الخطوات:</b>",
        "1️⃣ افتح @BotFather وأنشئ بوتاً جديداً بالأمر /newbot",
        "2️⃣ انسخ التوكن الذي يعطيك إياه",
        "3️⃣ اضغط «➕ إنشاء بوتي» وأرسل التوكن هنا",
        "",
        "ℹ️ بوتك له أعضاء وأرصدة وإعدادات مستقلة تماماً عن هذا البوت.",
        "🔒 لا تشارك التوكن مع أحد. سأحذف رسالتك فور قراءته.",
        "",
        f"📊 بوتاتك: {count} من {limit}",
    ]
    return "\n".join(lines)


def _clone_start_kb(count: int, limit: int, total_full: bool) -> InlineKeyboardMarkup:
    rows = []
    if count < limit and not total_full:
        rows.append([InlineKeyboardButton("➕ إنشاء بوتي", callback_data="clone:new")])
    if count:
        rows.append([InlineKeyboardButton(f"🤖 بوتاتي ({count})", callback_data="clone:mine")])
    rows.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


async def clone_show_start(q, user) -> None:
    mine = await asyncio.to_thread(clone_db_list, user.id)
    total = len(await asyncio.to_thread(clone_db_list))
    limit = clone_max_per_user()
    total_full = total >= clone_max_total()
    text = _clone_intro_text(len(mine), limit)
    if total_full and len(mine) < limit:
        text += "\n\n⚠️ وصل البوت إلى الحد الأقصى من البوتات المستنسخة حالياً. حاول لاحقاً."
    await q.edit_message_text(
        text, parse_mode=ParseMode.HTML, reply_markup=_clone_start_kb(len(mine), limit, total_full)
    )


async def _clone_show_mine(q, user) -> None:
    mine = await asyncio.to_thread(clone_db_list, user.id)
    if not mine:
        await clone_show_start(q, user)
        return
    rows = [
        [InlineKeyboardButton(f"{_clone_status_label(r).split(' ')[0]} {_clone_title(r)}", callback_data=f"clone:view:{r['id']}")]
        for r in mine
    ]
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="clone:start")])
    await q.edit_message_text(
        "🤖 <b>بوتاتي</b>\n\nاختر بوتاً لإدارته:", parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows),
    )


def _clone_can_manage(row, user, is_own: bool) -> bool:
    return bool(row) and (is_own or int(row["owner_user_id"]) == int(user.id))


async def _clone_show_view(q, row, is_own: bool, from_panel: bool = False) -> None:
    username = (row.get("bot_username") or "").strip()
    lines = [
        f"🤖 <b>{html.escape(_clone_title(row))}</b>",
        "",
        f"الحالة: {_clone_status_label(row)}",
    ]
    if username:
        lines.append(f"الرابط: https://t.me/{html.escape(username)}")
    if is_own:
        lines.append(f"المالك: <code>{int(row['owner_user_id'])}</code>")
    if row.get("last_error"):
        lines += ["", f"⚠️ {html.escape(row['last_error'])}"]
    lines += ["", "<i>أرسل /start لبوتك لتبدأ إدارته من لوحة المالك.</i>"]
    suffix = ":p" if from_panel else ""
    rows = []
    if row["desired_state"] == "running":
        rows.append([InlineKeyboardButton("⏹ إيقاف", callback_data=f"clone:stop:{row['id']}{suffix}")])
    else:
        rows.append([InlineKeyboardButton("▶️ تشغيل", callback_data=f"clone:run:{row['id']}{suffix}")])
    rows.append([InlineKeyboardButton("🗑 حذف البوت", callback_data=f"clone:del:{row['id']}{suffix}")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="clone:all" if from_panel else "clone:mine")])
    await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))


# ────────────────────────────────────────────────────────────
# إنشاء البوت (استقبال التوكن)
# ────────────────────────────────────────────────────────────
async def _clone_limits_error(user_id: int) -> str:
    """'' إذا مسموح، وإلا نص السبب."""
    mine = await asyncio.to_thread(clone_db_list, user_id)
    if len(mine) >= clone_max_per_user():
        return f"⚠️ وصلت للحد الأقصى من البوتات ({clone_max_per_user()})."
    total = len(await asyncio.to_thread(clone_db_list))
    if total >= clone_max_total():
        return "⚠️ وصل البوت إلى الحد الأقصى من البوتات المستنسخة حالياً. حاول لاحقاً."
    return ""


def _clone_insert(owner_user_id: int, me: dict, token: str) -> int:
    bot_id = int(me["id"])
    with db_conn() as c:
        row = c.execute(
            "INSERT INTO cloned_bots (owner_user_id, bot_id, bot_username, bot_name, token, schema_name) "
            "VALUES (?,?,?,?,?,?) RETURNING id",
            (int(owner_user_id), bot_id, me.get("username") or "", me.get("first_name") or "", token, f"clone_{bot_id}"),
        ).fetchone()
    return int(row["id"])


async def handle_clone_text(update, context, text: str) -> bool:
    """يعالج: توكن العضو (clone_await_token) وحدود المالك (os_await_clone_limits)."""
    user = update.effective_user
    state = context.user_data.get("state", "")
    if user is None:
        return False
    msg = update.message

    # ── حدود المالك: «لكل عضو» ثم «الإجمالي» ──
    if state == CLONE_LIMITS_STATE:
        if user.id != OWNER_ID:
            return False
        numbers = re.findall(r"\d+", (text or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
        if len(numbers) != 2 or any(int(n) > CLONE_LIMIT_CEILING for n in numbers):
            await msg.reply_text(
                f"⚠️ أرسل رقمين فقط (لكل عضو ثم الإجمالي) بحد أقصى {CLONE_LIMIT_CEILING}. مثال: 1 10",
                reply_markup=_clone_back_kb("clone:panel", "❌ إلغاء"),
            )
            return True
        set_setting(CLONE_MAX_PER_USER_KEY, str(int(numbers[0])))
        set_setting(CLONE_MAX_TOTAL_KEY, str(int(numbers[1])))
        context.user_data["state"] = "main_menu"
        await msg.reply_text(
            f"✅ تم الحفظ: {int(numbers[0])} لكل عضو، والإجمالي {int(numbers[1])}.",
            reply_markup=_clone_back_kb("clone:panel", "🤖 لوحة البوتات المستنسخة"),
        )
        return True

    if state != CLONE_TOKEN_STATE:
        return False

    token = (text or "").strip()
    # الرسالة قد تحوي التوكن: نحذفها في كل الأحوال.
    try:
        await msg.delete()
    except Exception:
        pass

    async def reply(message: str, kb=None):
        await update.effective_chat.send_message(message, reply_markup=kb or _clone_back_kb("clone:start", "🔙 رجوع"))

    if clone_is_child() or not clone_is_enabled():
        context.user_data["state"] = "main_menu"
        await reply("⚠️ هذا القسم غير متاح حالياً.")
        return True

    if not _CLONE_TOKEN_RE.fullmatch(token):
        await reply(
            "⚠️ هذا ليس توكن بوت صحيحاً. انسخه كاملاً من @BotFather وأرسله وحده في رسالة واحدة.",
            _clone_back_kb("clone:start", "❌ إلغاء"),
        )
        return True

    error = await _clone_limits_error(user.id)
    if error:
        context.user_data["state"] = "main_menu"
        await reply(error)
        return True

    bot_id = int(token.split(":", 1)[0])
    own_id = BOT_TOKEN.split(":", 1)[0] if BOT_TOKEN else ""
    if own_id and str(bot_id) == own_id:
        await reply("⚠️ هذا توكن البوت الحالي. أنشئ بوتاً جديداً من @BotFather.", _clone_back_kb("clone:start", "❌ إلغاء"))
        return True
    if await asyncio.to_thread(clone_db_get_by_bot_id, bot_id):
        await reply("⚠️ هذا البوت مستخدم مسبقاً. أنشئ بوتاً جديداً من @BotFather.", _clone_back_kb("clone:start", "❌ إلغاء"))
        return True

    checking = await update.effective_chat.send_message("⏳ جاري التحقق من التوكن وتجهيز بوتك...")
    try:
        me = await asyncio.to_thread(_clone_tg_get_me, token)
    except RuntimeError as exc:
        reason = (
            "⚠️ التوكن غير صالح أو ملغى. تأكد منه في @BotFather."
            if str(exc) == "invalid_token" else "⚠️ تعذّر الاتصال بتيليجرام الآن. حاول بعد قليل."
        )
        try:
            await checking.edit_text(reason, reply_markup=_clone_back_kb("clone:start", "🔙 رجوع"))
        except Exception:
            await reply(reason)
        return True
    if int(me.get("id", 0)) != bot_id:
        await checking.edit_text("⚠️ التوكن غير صالح.", reply_markup=_clone_back_kb("clone:start", "🔙 رجوع"))
        return True

    try:
        clone_id = await asyncio.to_thread(_clone_insert, user.id, me, token)
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            await checking.edit_text("⚠️ هذا البوت مستخدم مسبقاً.", reply_markup=_clone_back_kb("clone:start", "🔙 رجوع"))
        else:
            logger.exception("clone: فشل حفظ البوت المستنسخ")
            await checking.edit_text("⚠️ تعذّر إنشاء البوت الآن. حاول لاحقاً.", reply_markup=_clone_back_kb("clone:start", "🔙 رجوع"))
        return True

    await asyncio.to_thread(_clone_tg_delete_webhook, token)
    row = await asyncio.to_thread(clone_db_get, clone_id)
    started = await asyncio.to_thread(clone_spawn, row)
    context.user_data["state"] = "main_menu"

    username = me.get("username") or ""
    done = (
        f"✅ <b>تم إنشاء بوتك!</b>\n\n🤖 @{html.escape(username)}\n"
        f"https://t.me/{html.escape(username)}\n\n"
        "افتحه وأرسل /start وستجد لوحة المالك كاملة لك."
        + ("" if started else "\n\n⚠️ سيبدأ التشغيل خلال لحظات تلقائياً.")
    )
    await checking.edit_text(
        done, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 بوتاتي", callback_data="clone:mine")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
        ]),
    )
    if OWNER_ID:
        try:
            await context.bot.send_message(
                OWNER_ID,
                f"🆕 بوت مستنسخ جديد: @{username}\nالمنشئ: {user.full_name or ''} (<code>{user.id}</code>)",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    return True


# ────────────────────────────────────────────────────────────
# لوحة المالك
# ────────────────────────────────────────────────────────────
def _clone_panel_text() -> str:
    rows = clone_db_list()
    running = sum(1 for r in rows if r["desired_state"] == "running" and _clone_is_alive(int(r["id"])))
    return "\n".join([
        "🤖 <b>البوتات المستنسخة (إنشاء بوت كهذا)</b>",
        "",
        "الزر في القائمة الرئيسية: " + ("ظاهر ✅" if clone_is_enabled() else "مخفي ❌"),
        f"📊 الإجمالي: {len(rows)} | 🟢 يعمل الآن: {running}",
        f"🔢 الحد لكل عضو: {clone_max_per_user()} | الحد الإجمالي: {clone_max_total()}",
        "",
        "<i>كل بوت مستنسخ له قاعدة بيانات مستقلة، ولا يحصل على أي مفتاح أو سرّ من هذا البوت.</i>",
    ])


def _clone_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🙈 إخفاء الزر" if clone_is_enabled() else "👁 إظهار الزر", callback_data="clone:toggle")],
        [InlineKeyboardButton("📋 كل البوتات", callback_data="clone:all")],
        [InlineKeyboardButton("✏️ تعديل الحدود", callback_data="clone:limits")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="owner_settings")],
    ])


async def _clone_show_panel(q) -> None:
    text, kb = await asyncio.to_thread(_clone_panel_text), _clone_panel_kb()
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception as exc:
        if "not modified" not in str(exc).lower():
            await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


# ────────────────────────────────────────────────────────────
# معالج الأزرار
# ────────────────────────────────────────────────────────────
async def handle_clone_callback(update, context, q, data: str, user, is_own: bool) -> bool:
    if not data.startswith("clone:"):
        return False
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    # ── لوحة المالك ──
    if action in ("panel", "toggle", "all", "limits"):
        if not is_own:
            await q.answer("🚫 للمالك فقط.", show_alert=True)
            return True
        if action == "panel":
            context.user_data["state"] = "main_menu"
            await _clone_show_panel(q)
        elif action == "toggle":
            set_setting(CLONE_ENABLED_KEY, "0" if clone_is_enabled() else "1")
            await _clone_show_panel(q)
        elif action == "all":
            rows = await asyncio.to_thread(clone_db_list)
            buttons = [
                [InlineKeyboardButton(f"{_clone_status_label(r).split(' ')[0]} {_clone_title(r)} · {r['owner_user_id']}",
                                      callback_data=f"clone:view:{r['id']}:p")]
                for r in rows[:40]
            ]
            buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="clone:panel")])
            await q.edit_message_text(
                "📋 <b>كل البوتات المستنسخة</b>" + ("" if rows else "\n\nلا توجد بوتات بعد."),
                parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons),
            )
        else:
            context.user_data["state"] = CLONE_LIMITS_STATE
            await q.edit_message_text(
                "✏️ <b>حدود البوتات المستنسخة</b>\n\n"
                f"الحالي: {clone_max_per_user()} لكل عضو، والإجمالي {clone_max_total()}.\n\n"
                "أرسل رقمين: <b>لكل عضو</b> ثم <b>الإجمالي</b>. مثال: <code>1 10</code>",
                parse_mode=ParseMode.HTML, reply_markup=_clone_back_kb("clone:panel", "❌ إلغاء"),
            )
        return True

    # ── العضو ──
    if clone_is_child():
        await q.answer("⚠️ هذا القسم غير متاح هنا.", show_alert=True)
        return True
    if not clone_is_enabled() and not is_own:
        await q.answer("⚠️ هذا القسم غير متاح حالياً.", show_alert=True)
        return True

    if action == "start":
        context.user_data["state"] = "main_menu"
        await clone_show_start(q, user)
        return True

    if action == "new":
        error = await _clone_limits_error(user.id)
        if error:
            await q.answer(error, show_alert=True)
            return True
        context.user_data.pop("raksh_step", None)
        context.user_data["state"] = CLONE_TOKEN_STATE
        await q.edit_message_text(
            "🔐 <b>أرسل توكن بوتك</b>\n\n"
            "من @BotFather انسخ التوكن وأرسله هنا في رسالة واحدة.\n"
            "سأحذف رسالتك فوراً ولن أعرض التوكن.",
            parse_mode=ParseMode.HTML, reply_markup=_clone_back_kb("clone:start", "❌ إلغاء"),
        )
        return True

    if action == "mine":
        context.user_data["state"] = "main_menu"
        await _clone_show_mine(q, user)
        return True

    # ما بعده يخص بوتاً محدداً: clone:<action>:<id>[:p]
    try:
        clone_id = int(parts[2])
    except (IndexError, ValueError):
        return False
    row = await asyncio.to_thread(clone_db_get, clone_id)
    if not _clone_can_manage(row, user, is_own):
        await q.answer("⚠️ البوت غير موجود.", show_alert=True)
        return True
    from_panel = is_own and len(parts) > 3 and parts[3] == "p"

    if action == "view":
        await _clone_show_view(q, row, is_own, from_panel)
        return True

    if action == "stop":
        await asyncio.to_thread(_clone_db_update, clone_id, desired_state="stopped", last_error="")
        await asyncio.to_thread(clone_terminate, clone_id)
        await q.answer("⏹ تم إيقاف البوت.")
        await _clone_show_view(q, await asyncio.to_thread(clone_db_get, clone_id), is_own, from_panel)
        return True

    if action == "run":
        await asyncio.to_thread(_clone_db_update, clone_id, desired_state="running", last_error="")
        _CLONE_STATE.pop(clone_id, None)
        fresh = await asyncio.to_thread(clone_db_get, clone_id)
        await asyncio.to_thread(_clone_tg_delete_webhook, fresh["token"])
        await asyncio.to_thread(clone_spawn, fresh)
        await q.answer("▶️ تم تشغيل البوت.")
        await _clone_show_view(q, await asyncio.to_thread(clone_db_get, clone_id), is_own, from_panel)
        return True

    if action == "del":
        suffix = ":p" if from_panel else ""
        await q.edit_message_text(
            f"🗑 <b>حذف {html.escape(_clone_title(row))}</b>\n\n"
            "⚠️ سيتوقف البوت وتُحذف <b>كل بياناته نهائياً</b> (الأعضاء والأرصدة والإعدادات). لا يمكن التراجع.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ نعم، احذف نهائياً", callback_data=f"clone:delok:{clone_id}{suffix}")],
                [InlineKeyboardButton("❌ إلغاء", callback_data=f"clone:view:{clone_id}{suffix}")],
            ]),
        )
        return True

    if action == "delok":
        await asyncio.to_thread(_clone_db_update, clone_id, desired_state="stopped")
        await asyncio.to_thread(clone_terminate, clone_id)
        try:
            await asyncio.to_thread(_clone_drop_schema, row["schema_name"])
        except Exception:
            logger.exception("clone: فشل حذف مخطط البوت %s", clone_id)
            await q.answer("⚠️ تعذّر حذف البيانات الآن. حاول لاحقاً.", show_alert=True)
            return True
        with db_conn() as c:
            c.execute("DELETE FROM cloned_bots WHERE id=?", (clone_id,))
        _CLONE_STATE.pop(clone_id, None)
        await q.answer("🗑 تم حذف البوت.")
        if from_panel:
            await handle_clone_callback(update, context, q, "clone:all", user, is_own)
        else:
            await _clone_show_mine(q, user)
        return True

    return False
