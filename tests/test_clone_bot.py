"""اختبارات قسم «إنشاء بوت كهذا» (bot_app/clone_bot.py) بدون Telegram ولا PostgreSQL.

تُحقن نسخة وهمية من shared وقاعدة بيانات في الذاكرة كي يُحمَّل الملف وحده، ثم تُفحص:
عزل الأسرار عن البوت المستنسخ، التحقق من التوكن، الحدود، تدفق الأزرار والنصوص،
ومنطق المشرف (إعادة التشغيل/إيقاف التوكن الملغى).
"""
import asyncio
import html
import importlib.util
import json
import logging
import os
import pathlib
import re
import subprocess
import sys
import time
import types
import unittest
from datetime import datetime, timezone

_SAVED_MODULES = {k: sys.modules.get(k) for k in ("bot_app", "bot_app.shared", "bot_app.clone_bot")}
pkg = types.ModuleType("bot_app")
pkg.__path__ = []
sys.modules["bot_app"] = pkg

# ---- shared وهمي ----
shared = types.ModuleType("bot_app.shared")
import requests  # noqa: E402

shared.os, shared.re, shared.asyncio, shared.time, shared.json, shared.html = os, re, asyncio, time, json, html
shared.requests, shared.subprocess = requests, subprocess
shared.datetime, shared.timezone = datetime, timezone
shared.logger = logging.getLogger("clone_test")
shared.OWNER_ID = 1
shared.BOT_TOKEN = "111111:MAIN_BOT_TOKEN_aaaaaaaaaaaaaaaaaaaaaaaaaaa"


class Btn:
    def __init__(self, text, callback_data=None, url=None):
        self.text, self.callback_data, self.url = text, callback_data, url


class Kb:
    def __init__(self, rows):
        self.inline_keyboard = rows


class PM:
    HTML = "HTML"
    MARKDOWN = "MD"


shared.InlineKeyboardButton, shared.InlineKeyboardMarkup, shared.ParseMode = Btn, Kb, PM

SETTINGS = {}
shared.get_setting = lambda k: SETTINGS.get(k, "")
shared.set_setting = lambda k, v: SETTINGS.__setitem__(k, v)


class Row(dict):
    pass


ROWS: list = []          # جدول cloned_bots في الذاكرة
SQL_LOG: list = []        # أوامر DDL المنفّذة (CREATE/DROP SCHEMA)


class Cur:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class Conn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith(("CREATE SCHEMA", "DROP SCHEMA")):
            SQL_LOG.append(s)
            return Cur()
        if s.startswith("SELECT * FROM cloned_bots WHERE owner_user_id=?"):
            return Cur([r for r in ROWS if r["owner_user_id"] == params[0]])
        if s.startswith("SELECT * FROM cloned_bots WHERE id=?"):
            return Cur([r for r in ROWS if r["id"] == params[0]])
        if s.startswith("SELECT * FROM cloned_bots WHERE bot_id=?"):
            return Cur([r for r in ROWS if r["bot_id"] == params[0]])
        if s.startswith("SELECT * FROM cloned_bots"):
            return Cur(list(ROWS))
        if s.startswith("INSERT INTO cloned_bots"):
            owner, bot_id, username, name, token, schema = params
            if any(r["bot_id"] == bot_id for r in ROWS):
                raise RuntimeError("duplicate key value violates unique constraint")
            row = Row(id=len(ROWS) + 1, owner_user_id=owner, bot_id=bot_id, bot_username=username, bot_name=name,
                      token=token, schema_name=schema, desired_state="running", last_error="")
            ROWS.append(row)
            return Cur([Row(id=row["id"])])
        if s.startswith("UPDATE cloned_bots SET"):
            *values, clone_id = params
            names = re.findall(r"(\w+)=\?", s.split("WHERE")[0])
            for r in ROWS:
                if r["id"] == clone_id:
                    r.update(dict(zip(names, values)))
            return Cur()
        if s.startswith("DELETE FROM cloned_bots"):
            ROWS[:] = [r for r in ROWS if r["id"] != params[0]]
            return Cur()
        raise AssertionError("unexpected sql: " + s)


shared.db_conn = lambda: Conn()
sys.modules["bot_app.shared"] = shared

spec = importlib.util.spec_from_file_location(
    "bot_app.clone_bot", str(pathlib.Path(__file__).resolve().parents[1] / "bot_app" / "clone_bot.py")
)
m = importlib.util.module_from_spec(spec)
sys.modules["bot_app.clone_bot"] = m
spec.loader.exec_module(m)
for _k, _v in _SAVED_MODULES.items():
    if _v is None:
        sys.modules.pop(_k, None)
    else:
        sys.modules[_k] = _v


REAL_SPAWN, REAL_TERMINATE = m.clone_spawn, m.clone_terminate
REAL_IS_ALIVE, REAL_LOG_TAIL = m._clone_is_alive, m._clone_log_tail


# ---- أدوات المحاكاة ----
class Msg:
    def __init__(self):
        self.sent, self.deleted = [], False

    async def reply_text(self, text, reply_markup=None, **k):
        self.sent.append(text)
        return self

    async def edit_text(self, text, reply_markup=None, **k):
        self.sent[-1] = text

    async def delete(self):
        self.deleted = True


class Chat:
    def __init__(self, msg):
        self.msg = msg

    async def send_message(self, text, reply_markup=None, **k):
        self.msg.sent.append(text)
        return self.msg


class Update:
    def __init__(self, uid, name="Tester"):
        self.effective_user = types.SimpleNamespace(id=uid, full_name=name)
        self.message = Msg()
        self.effective_chat = Chat(self.message)


class Ctx:
    def __init__(self, state=""):
        self.user_data = {"state": state}
        self.owner_msgs = []

        async def send_message(chat_id, text, **k):
            self.owner_msgs.append((chat_id, text))

        self.bot = types.SimpleNamespace(send_message=send_message)


class Query:
    def __init__(self):
        self.text, self.markup, self.alerts = "", None, []
        self.message = Msg()

    async def edit_message_text(self, text, reply_markup=None, **k):
        self.text, self.markup = text, reply_markup

    async def answer(self, text=None, show_alert=False):
        if text:
            self.alerts.append(text)

    def buttons(self):
        return [b.callback_data for row in (self.markup.inline_keyboard if self.markup else []) for b in row]


def run(coro):
    return asyncio.run(coro)


GOOD_TOKEN = "222222:" + "A" * 35


def fake_get_me(token):
    return {"id": int(token.split(":")[0]), "is_bot": True, "username": "my_clone_bot", "first_name": "Clone"}


class CloneBotTests(unittest.TestCase):
    def setUp(self):
        ROWS.clear()
        SQL_LOG.clear()
        SETTINGS.clear()
        m._CLONE_PROCS.clear()
        m._CLONE_STATE.clear()
        os.environ.pop("BOT_CLONE_CHILD", None)
        self.spawned = []
        m.clone_spawn = lambda row: self.spawned.append(row["id"]) or True
        m.clone_terminate = lambda cid: None
        m._clone_tg_get_me = fake_get_me
        m._clone_tg_delete_webhook = lambda token: None
        m._clone_is_alive, m._clone_log_tail = REAL_IS_ALIVE, REAL_LOG_TAIL

    # ---------- الزر والإعدادات ----------
    def test_button_visibility(self):
        self.assertEqual(m.clone_button_row(False)[0][0].callback_data, "clone:start")
        SETTINGS["clone_bot_enabled"] = "0"
        self.assertEqual(m.clone_button_row(True), [])
        SETTINGS["clone_bot_enabled"] = ""
        os.environ["BOT_CLONE_CHILD"] = "1"
        try:
            self.assertEqual(m.clone_button_row(True), [])      # البوت المستنسخ لا يعرض القسم
            self.assertTrue(m.clone_is_child())
        finally:
            os.environ.pop("BOT_CLONE_CHILD")

    def test_limits_defaults_and_bounds(self):
        self.assertEqual((m.clone_max_per_user(), m.clone_max_total()), (1, 10))
        SETTINGS["clone_max_per_user"], SETTINGS["clone_max_total"] = "3", "abc"
        self.assertEqual((m.clone_max_per_user(), m.clone_max_total()), (3, 10))
        SETTINGS["clone_max_per_user"] = "99999"
        self.assertEqual(m.clone_max_per_user(), m.CLONE_LIMIT_CEILING)

    # ---------- عزل الأسرار ----------
    def test_child_env_has_no_parent_secrets(self):
        secrets = {
            "API_KEY": "panel1", "JUSTANOTHERPANEL_API_KEY": "panel2", "SMMFOLLOWS_API_KEY": "panel3",
            "OPENAI_API_KEY": "o", "ANTHROPIC_API_KEY": "a", "GROQ_API_KEY": "g", "DEEPSEEK_API_KEY": "d",
            "GEMINI_API_KEY": "gem", "AI_API_KEY": "ai", "GOOGLE_API_KEY": "goog",
            "BOT_TOKEN": "parent-token", "ADMIN_GROUP_ID": "-100", "NUMBERS_GROUP_ID": "-200",
            "RAILWAY_API_TOKEN": "r", "SOME_SECRET": "s", "DB_PASSWORD": "p",
        }
        keep = {"TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": "hash", "DATABASE_URL": "postgres://x/y",
                "PATH": os.environ.get("PATH", "/bin"), "OWNER_ID": "999", "PORT": "8080"}
        saved = {k: os.environ.get(k) for k in list(secrets) + list(keep)}
        os.environ.update(secrets)
        os.environ.update(keep)
        try:
            row = {"token": "222:CHILDTOKEN", "owner_user_id": 42, "schema_name": "clone_222"}
            env = m._clone_child_env(row)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        for name in secrets:
            if name != "BOT_TOKEN":
                self.assertNotIn(name, env, name)
        self.assertNotIn("parent-token", env.values())
        self.assertEqual(env["BOT_TOKEN"], "222:CHILDTOKEN")
        self.assertEqual(env["OWNER_ID"], "42")                 # المنشئ هو المالك، لا مالك الأصل
        self.assertEqual(env["BOT_DB_SCHEMA"], "clone_222")
        self.assertEqual(env["BOT_CLONE_CHILD"], "1")
        self.assertEqual(env["PORT"], "0")                      # لا تعارض منافذ
        self.assertEqual(env["DATABASE_URL"], "postgres://x/y")
        self.assertEqual(env["TELEGRAM_API_ID"], "123")
        self.assertIn("PATH", env)

    def test_schema_name_is_validated(self):
        self.assertEqual(m._clone_quote_schema("clone_123"), '"clone_123"')
        for bad in ("public", "clone_1; DROP TABLE users", 'clone_1"', "", "clone_", "Clone_1"):
            with self.assertRaises(ValueError, msg=bad):
                m._clone_quote_schema(bad)

    # ---------- التوكن والإنشاء ----------
    def test_token_regex(self):
        self.assertTrue(m._CLONE_TOKEN_RE.fullmatch(GOOD_TOKEN))
        for bad in ("hello", "123:short", "abc:" + "A" * 35, GOOD_TOKEN + " x", "", "1" * 20 + ":" + "A" * 35):
            self.assertFalse(m._CLONE_TOKEN_RE.fullmatch(bad), bad)

    def _send_token(self, uid, token, state=None):
        u, c = Update(uid), Ctx(state or m.CLONE_TOKEN_STATE)
        handled = run(m.handle_clone_text(u, c, token))
        return handled, u, c

    def test_create_flow_success(self):
        handled, u, c = self._send_token(5, GOOD_TOKEN)
        self.assertTrue(handled)
        self.assertTrue(u.message.deleted, "يجب حذف رسالة التوكن")
        self.assertEqual(len(ROWS), 1)
        row = ROWS[0]
        self.assertEqual((row["owner_user_id"], row["bot_id"], row["schema_name"]), (5, 222222, "clone_222222"))
        self.assertEqual(self.spawned, [1])
        self.assertEqual(c.user_data["state"], "main_menu")
        self.assertTrue(any("my_clone_bot" in t for t in u.message.sent))
        self.assertFalse(any(GOOD_TOKEN in t for t in u.message.sent), "التوكن لا يظهر في أي رد")
        self.assertEqual(c.owner_msgs[0][0], 1)                    # إشعار للمالك الأصلي
        self.assertNotIn(GOOD_TOKEN, c.owner_msgs[0][1])

    def test_create_rejects_bad_inputs(self):
        _, u, c = self._send_token(5, "not a token")
        self.assertEqual(ROWS, [])
        self.assertTrue(u.message.deleted)
        self.assertEqual(c.user_data["state"], m.CLONE_TOKEN_STATE)  # يبقى بانتظار توكن صحيح

        _, u, _ = self._send_token(5, shared.BOT_TOKEN.split(":")[0] + ":" + "B" * 35)   # آيدي البوت الأصلي
        self.assertEqual(ROWS, [])
        self.assertTrue(any("البوت الحالي" in t for t in u.message.sent))

        def bad(token):
            raise RuntimeError("invalid_token")
        m._clone_tg_get_me = bad
        _, u, _ = self._send_token(5, GOOD_TOKEN)
        self.assertEqual(ROWS, [])
        self.assertTrue(any("غير صالح" in t for t in u.message.sent))

        def down(token):
            raise RuntimeError("network")
        m._clone_tg_get_me = down
        _, u, _ = self._send_token(5, GOOD_TOKEN)
        self.assertEqual(ROWS, [])
        self.assertTrue(any("الاتصال" in t for t in u.message.sent))

    def test_create_enforces_limits_and_duplicates(self):
        self._send_token(5, GOOD_TOKEN)
        self.assertEqual(len(ROWS), 1)
        # نفس العضو تجاوز حده (1)
        _, u, _ = self._send_token(5, "333333:" + "C" * 35)
        self.assertEqual(len(ROWS), 1)
        self.assertTrue(any("الأقصى" in t for t in u.message.sent))
        # عضو آخر بنفس التوكن
        _, u, _ = self._send_token(6, GOOD_TOKEN)
        self.assertEqual(len(ROWS), 1)
        self.assertTrue(any("مستخدم مسبقاً" in t for t in u.message.sent))
        # الحد الإجمالي
        SETTINGS["clone_max_total"] = "1"
        _, u, _ = self._send_token(7, "444444:" + "D" * 35)
        self.assertEqual(len(ROWS), 1)
        self.assertTrue(any("الأقصى" in t for t in u.message.sent))

    def test_text_handler_ignores_other_states(self):
        u, c = Update(5), Ctx("main_menu")
        self.assertFalse(run(m.handle_clone_text(u, c, GOOD_TOKEN)))
        self.assertEqual(ROWS, [])

    def test_disabled_or_child_blocks_creation(self):
        SETTINGS["clone_bot_enabled"] = "0"
        _, u, _ = self._send_token(5, GOOD_TOKEN)
        self.assertEqual(ROWS, [])
        self.assertTrue(u.message.deleted)

    # ---------- حدود المالك ----------
    def test_owner_limits_input(self):
        u, c = Update(1), Ctx(m.CLONE_LIMITS_STATE)
        self.assertTrue(run(m.handle_clone_text(u, c, "٣ 20")))          # أرقام عربية
        self.assertEqual((SETTINGS["clone_max_per_user"], SETTINGS["clone_max_total"]), ("3", "20"))
        for bad in ("5", "1 2 3", "x y", "1 101"):
            u, c = Update(1), Ctx(m.CLONE_LIMITS_STATE)
            run(m.handle_clone_text(u, c, bad))
            self.assertEqual(SETTINGS["clone_max_total"], "20", bad)
        u, c = Update(99), Ctx(m.CLONE_LIMITS_STATE)
        self.assertFalse(run(m.handle_clone_text(u, c, "9 9")))           # غير المالك مرفوض

    # ---------- الأزرار ----------
    def _cb(self, data, uid=5, is_own=False, state="main_menu"):
        q, c = Query(), Ctx(state)
        user = types.SimpleNamespace(id=uid, full_name="T")
        handled = run(m.handle_clone_callback(None, c, q, data, user, is_own))
        return handled, q, c

    def test_member_menu_flow(self):
        handled, q, _ = self._cb("clone:start")
        self.assertTrue(handled)
        self.assertIn("clone:new", q.buttons())
        self.assertNotIn("clone:mine", q.buttons())
        handled, q, c = self._cb("clone:new")
        self.assertEqual(c.user_data["state"], m.CLONE_TOKEN_STATE)
        self._send_token(5, GOOD_TOKEN)
        _, q, _ = self._cb("clone:start")
        self.assertNotIn("clone:new", q.buttons())                           # بلغ حده
        self.assertIn("clone:mine", q.buttons())
        _, q, _ = self._cb("clone:new")
        self.assertTrue(q.alerts and "الأقصى" in q.alerts[0])         # ولا يستطيع البدء
        _, q, _ = self._cb("clone:mine")
        self.assertIn("clone:view:1", q.buttons())

    def test_manage_stop_run_delete(self):
        self._send_token(5, GOOD_TOKEN)
        _, q, _ = self._cb("clone:view:1")
        self.assertIn("clone:stop:1", q.buttons())
        self._cb("clone:stop:1")
        self.assertEqual(ROWS[0]["desired_state"], "stopped")
        _, q, _ = self._cb("clone:view:1")
        self.assertIn("clone:run:1", q.buttons())
        self._cb("clone:run:1")
        self.assertEqual(ROWS[0]["desired_state"], "running")
        _, q, _ = self._cb("clone:del:1")
        self.assertIn("clone:delok:1", q.buttons())
        self.assertEqual(len(ROWS), 1)                                       # لا حذف قبل التأكيد
        self._cb("clone:delok:1")
        self.assertEqual(ROWS, [])
        self.assertTrue(any(s.startswith('DROP SCHEMA IF EXISTS "clone_222222" CASCADE') for s in SQL_LOG))

    def test_authorization(self):
        self._send_token(5, GOOD_TOKEN)
        for action in ("view", "stop", "run", "del", "delok"):
            _, q, _ = self._cb(f"clone:{action}:1", uid=6)                  # عضو آخر
            self.assertTrue(q.alerts, action)
            self.assertEqual(len(ROWS), 1)
            self.assertEqual(ROWS[0]["desired_state"], "running")
        _, q, _ = self._cb("clone:view:1", uid=1, is_own=True)              # المالك يدير الكل
        self.assertIn("🤖", q.text)
        for action in ("panel", "toggle", "all", "limits"):                  # لوحة المالك محمية
            _, q, _ = self._cb(f"clone:{action}", uid=6)
            self.assertTrue(q.alerts, action)

    def test_owner_panel(self):
        self._send_token(5, GOOD_TOKEN)
        _, q, _ = self._cb("clone:panel", uid=1, is_own=True)
        self.assertIn("clone:toggle", q.buttons())
        self._cb("clone:toggle", uid=1, is_own=True)
        self.assertEqual(SETTINGS["clone_bot_enabled"], "0")
        _, q, _ = self._cb("clone:start", uid=7)                             # مخفي عن الأعضاء
        self.assertTrue(q.alerts)
        _, q, _ = self._cb("clone:all", uid=1, is_own=True)
        self.assertIn("clone:view:1:p", q.buttons())
        _, q, _ = self._cb("clone:view:1:p", uid=1, is_own=True)
        self.assertIn("clone:stop:1:p", q.buttons())                         # لاحقة اللوحة تُحمل
        _, q, c = self._cb("clone:limits", uid=1, is_own=True)
        self.assertEqual(c.user_data["state"], m.CLONE_LIMITS_STATE)

    def test_child_refuses_member_actions(self):
        os.environ["BOT_CLONE_CHILD"] = "1"
        try:
            _, q, _ = self._cb("clone:start")
            self.assertTrue(q.alerts)
            self.assertEqual(ROWS, [])
        finally:
            os.environ.pop("BOT_CLONE_CHILD")

    def test_unrelated_callback_not_handled(self):
        handled, _, _ = self._cb("aih:start")
        self.assertFalse(handled)

    # ---------- العمليات والمشرف ----------
    def test_spawn_uses_isolated_env_and_command(self):
        captured = {}

        class FakeProc:
            pid = 4242

            def poll(self):
                return None

        def fake_popen(cmd, **kw):
            captured.update(cmd=cmd, **kw)
            return FakeProc()

        real_subprocess, real_log_dir = m.subprocess, m._CLONE_LOG_DIR
        m.subprocess = types.SimpleNamespace(
            Popen=fake_popen, DEVNULL=subprocess.DEVNULL, STDOUT=subprocess.STDOUT,
            TimeoutExpired=subprocess.TimeoutExpired,
        )
        m._CLONE_LOG_DIR = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "clone_logs_test"
        row = Row(id=9, owner_user_id=42, bot_id=222, bot_username="x", token="222:TOK", schema_name="clone_222")
        try:
            self.assertTrue(REAL_SPAWN(row))
            self.assertEqual(captured["cmd"][1], "bot.py")
            self.assertTrue((pathlib.Path(captured["cwd"]) / "bot.py").exists())
            self.assertEqual(captured["env"]["BOT_DB_SCHEMA"], "clone_222")
            self.assertEqual(captured["env"]["OWNER_ID"], "42")
            self.assertTrue(captured["start_new_session"])
            self.assertIn('CREATE SCHEMA IF NOT EXISTS "clone_222"', SQL_LOG)
            captured.clear()
            self.assertTrue(REAL_SPAWN(row))                                 # لا تشغيل مزدوج
            self.assertEqual(captured, {})
        finally:
            m.subprocess, m._CLONE_LOG_DIR = real_subprocess, real_log_dir
            m._CLONE_PROCS.clear()

    def test_supervisor_restarts_and_backs_off(self):
        ROWS.append(Row(id=1, owner_user_id=5, bot_id=222, bot_username="x", bot_name="", token="t",
                        schema_name="clone_222", desired_state="running", last_error=""))
        alive = {"v": False}
        m._clone_is_alive = lambda cid: alive["v"]
        m._clone_supervise_once()
        self.assertEqual(self.spawned, [1])                                  # مات/غير موجود -> يُشغَّل
        m._clone_supervise_once()
        self.assertEqual(self.spawned, [1], "backoff: لا إعادة فورية")
        m._CLONE_STATE[1]["next_at"] = 0
        m._CLONE_STATE[1]["started"] = time.time() - 5                       # مات بسرعة
        m._clone_supervise_once()
        self.assertEqual(self.spawned, [1, 1])
        self.assertEqual(m._CLONE_STATE[1]["fails"], 1)
        # المتوقفون لا يُشغَّلون
        ROWS[0]["desired_state"] = "stopped"
        m._CLONE_STATE[1]["next_at"] = 0
        m._clone_supervise_once()
        self.assertEqual(self.spawned, [1, 1])

    def test_supervisor_stops_revoked_token(self):
        ROWS.append(Row(id=1, owner_user_id=5, bot_id=222, bot_username="x", bot_name="", token="t",
                        schema_name="clone_222", desired_state="running", last_error=""))
        m._clone_is_alive = lambda cid: True
        m._clone_log_tail = lambda cid, size=4000: "💥 البوت انهار [InvalidToken] بعد 3ث: The token `x` was rejected by the server."
        terminated = []
        m.clone_terminate = lambda cid: terminated.append(cid)
        m._clone_supervise_once()
        self.assertEqual(ROWS[0]["desired_state"], "stopped")
        self.assertEqual(terminated, [1])
        self.assertIn("التوكن", ROWS[0]["last_error"])
        self.assertNotIn("InvalidToken", ROWS[0]["last_error"])              # لا نسرّب نص السجل

    def test_supervisor_terminates_unwanted(self):
        m._CLONE_PROCS[7] = object()
        terminated = []
        m.clone_terminate = lambda cid: terminated.append(cid)
        m._clone_supervise_once()                                            # لا صف 7 في الجدول
        self.assertEqual(terminated, [7])


if __name__ == "__main__":
    unittest.main()
