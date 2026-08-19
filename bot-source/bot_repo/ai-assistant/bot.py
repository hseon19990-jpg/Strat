#!/usr/bin/env python3
"""
مساعد الكود الذكي
بوت تيليجرام يعدّل الملفات على GitHub تلقائياً باستخدام Gemini AI
"""

import os, re, json, base64, logging
import requests
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── إعدادات من متغيرات البيئة ───────────────────────────────────────────────
BOT_TOKEN    = os.environ["ASSISTANT_BOT_TOKEN"]
GEMINI_KEY   = os.environ["GEMINI_API_KEY"]
# Replit exposes the configured GitHub credential as
# GITHUB_PERSONAL_ACCESS_TOKEN. Keep GITHUB_TOKEN as a backwards-compatible
# alias for existing Railway deployments.
GITHUB_TOKEN = (
    os.environ.get("GITHUB_TOKEN")
    or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
)
if not GITHUB_TOKEN:
    raise RuntimeError(
        "Missing GITHUB_TOKEN or GITHUB_PERSONAL_ACCESS_TOKEN"
    )
OWNER_ID     = int(os.environ["OWNER_ID"])
REPO         = os.environ.get("TARGET_REPO",  "hseon19990-jpg/Strat")
FILE_PATH    = os.environ.get("TARGET_FILE",  "telegram-bot/bot.py")

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
)

# ─── GitHub API ───────────────────────────────────────────────────────────────

def gh_get_file(repo: str, path: str) -> tuple[str, str]:
    """يجلب محتوى الملف وSHA الحالي من GitHub."""
    r = requests.get(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["sha"]


def gh_push_file(repo: str, path: str, content: str, sha: str, message: str) -> dict:
    """يرفع محتوى جديد للملف على GitHub."""
    r = requests.put(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        },
        json={
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "sha": sha,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

# ─── Gemini AI ────────────────────────────────────────────────────────────────

def call_gemini(prompt: str) -> str:
    """يرسل طلباً إلى Gemini ويُرجع النص."""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.05,
            "maxOutputTokens": 8192,
        },
    }
    r = requests.post(GEMINI_URL, json=payload, timeout=90)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]

# ─── معالجة الكود ─────────────────────────────────────────────────────────────

def extract_context(code: str, keywords: list[str], window: int = 60) -> str:
    """يستخرج الأسطر المحيطة بكلمات البحث."""
    lines      = code.splitlines()
    kw_lower   = [k.lower() for k in keywords if k.strip()]
    hits: set  = set()

    for i, line in enumerate(lines):
        ll = line.lower()
        if any(k in ll for k in kw_lower):
            for j in range(max(0, i - window), min(len(lines), i + window + 1)):
                hits.add(j)

    if not hits:
        return ""

    sorted_hits = sorted(hits)
    segments: list[tuple[int,int]] = []
    start = prev = sorted_hits[0]
    for n in sorted_hits[1:]:
        if n - prev > 1:
            segments.append((start, prev))
            start = n
        prev = n
    segments.append((start, prev))

    parts = []
    for s, e in segments:
        parts.append(f"# ══ السطر {s+1} – {e+1} ══")
        parts.extend(lines[s : e + 1])
    return "\n".join(parts)


SYSTEM_PROMPT = """\
أنت مساعد برمجي خبير في Python وبوتات تيليجرام.
مهمتك: تعديل الكود بناءً على تعليمة المستخدم.

أخرج JSON فقط (بدون أي نص قبله أو بعده) بهذا الشكل:
{
  "old_string": "النص القديم الدقيق (مع نفس المسافات البادئة تماماً)",
  "new_string": "النص الجديد البديل",
  "commit_message": "وصف مختصر للتغيير"
}

قواعد صارمة:
• old_string يجب أن يكون موجوداً حرفياً في الكود
• أضف 5-10 أسطر سياق حوله لجعله فريداً
• حافظ على نفس المسافات البادئة (indentation) الأصلية
• لا تعدّل أي شيء خارج نطاق التعليمة
• إن استحال التحديد بدقة أرجع: {"error": "السبب"}
"""

# ─── حالة المستخدم ────────────────────────────────────────────────────────────
# pending_edit[user_id] = {"old": ..., "new": ..., "sha": ..., "msg": ...}
pending_edit: dict = {}

# ─── معالجات Telegram ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text(
        "👋 *مرحباً! أنا مساعدك البرمجي*\n\n"
        "أرسل لي أي تعليمة لتعديل الكود وسأنفذها تلقائياً ورفعها على GitHub.\n\n"
        "مثال:\n"
        "• _أضف زر جديد اسمه 'إحصاءات' في القائمة الرئيسية_\n"
        "• _غيّر نص رسالة الترحيب_\n"
        "• _أضف تحقق من أن المستخدم مشترك قبل الطلب_",
        parse_mode="Markdown",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    try:
        r = requests.get(
            f"https://api.github.com/repos/{REPO}/commits/{FILE_PATH.replace('/', '%2F')}",
            headers={"Authorization": f"token {GITHUB_TOKEN}"},
            timeout=10,
        )
        if r.ok:
            c = r.json()[0] if isinstance(r.json(), list) else r.json()
            msg_txt = c.get("commit", {}).get("message", "—")[:80]
            date    = c.get("commit", {}).get("author", {}).get("date", "—")[:10]
            await update.message.reply_text(
                f"📁 *{REPO}*\n`{FILE_PATH}`\n\n"
                f"🕐 آخر commit: {date}\n📝 {msg_txt}",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("⚠️ تعذّر جلب معلومات الريبو.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != OWNER_ID:
        return

    instruction = update.message.text.strip()
    if not instruction:
        return

    msg = await update.message.reply_text("⏳ جاري المعالجة…")

    try:
        # 1 ── جلب الكود من GitHub
        await msg.edit_text("📥 جاري جلب الكود من GitHub…")
        code, sha = gh_get_file(REPO, FILE_PATH)

        # 2 ── استخراج كلمات البحث من التعليمة
        await msg.edit_text("🔍 جاري تحليل التعليمة…")
        kw_prompt = (
            f"استخرج كلمات البحث المناسبة للعثور على الكود المطلوب تعديله.\n"
            f"التعليمة: {instruction}\n\n"
            f'أرجع JSON فقط: {{"keywords": ["كلمة1", "كلمة2"]}}'
        )
        kw_raw = call_gemini(kw_prompt)
        try:
            kw_json  = json.loads(re.search(r'\{.*?\}', kw_raw, re.DOTALL).group())
            keywords = kw_json.get("keywords", [])
        except Exception:
            keywords = [w for w in instruction.split() if len(w) > 2][:8]

        # 3 ── استخراج المقاطع ذات الصلة
        ctx_code = extract_context(code, keywords, window=60)
        if not ctx_code:
            # إن لم يُعثر على شيء → أول 300 سطر كمرجع عام
            ctx_code = "\n".join(code.splitlines()[:300])

        # 4 ── طلب التعديل من Gemini
        await msg.edit_text("🤖 الذكاء الاصطناعي يحلل ويولّد التعديل…")
        edit_prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"التعليمة: {instruction}\n\n"
            f"أجزاء الكود ذات الصلة:\n```python\n{ctx_code}\n```"
        )
        raw = call_gemini(edit_prompt)

        # 5 ── تحليل رد Gemini
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            await msg.edit_text(
                f"❌ لم أفهم رد الذكاء الاصطناعي:\n<code>{raw[:400]}</code>",
                parse_mode="HTML",
            )
            return

        result = json.loads(json_match.group())

        if "error" in result:
            await msg.edit_text(
                f"⚠️ الذكاء الاصطناعي عجز عن تحديد التعديل:\n{result['error']}"
            )
            return

        old_str    = result["old_string"]
        new_str    = result["new_string"]
        commit_msg = result.get("commit_message", f"تعديل: {instruction[:60]}")

        # 6 ── التحقق من وجود old_string في الكود
        if old_str not in code:
            await msg.edit_text(
                "⚠️ لم يُعثر على النص المحدد في الكود.\n\n"
                "جرّب صياغة التعليمة بشكل أوضح.",
            )
            return

        # 7 ── معاينة التعديل للمستخدم
        old_preview = old_str[:300] + ("…" if len(old_str) > 300 else "")
        new_preview = new_str[:300] + ("…" if len(new_str) > 300 else "")

        pending_edit[user.id] = {
            "old": old_str, "new": new_str,
            "sha": sha, "commit_msg": commit_msg,
        }

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ تأكيد ورفع", callback_data="edit:confirm"),
                InlineKeyboardButton("❌ إلغاء",       callback_data="edit:cancel"),
            ]
        ])
        await msg.edit_text(
            f"📋 <b>معاينة التعديل</b>\n\n"
            f"<b>📝 {commit_msg}</b>\n\n"
            f"➖ <i>القديم:</i>\n<code>{old_preview}</code>\n\n"
            f"➕ <i>الجديد:</i>\n<code>{new_preview}</code>",
            parse_mode="HTML",
            reply_markup=kb,
        )

    except requests.HTTPError as e:
        await msg.edit_text(f"❌ خطأ في الاتصال: {e.response.status_code} {e.response.text[:200]}")
    except Exception as e:
        logger.error("handle_message error", exc_info=True)
        await msg.edit_text(f"❌ خطأ غير متوقع: {str(e)[:300]}")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    if user.id != OWNER_ID:
        await q.answer()
        return

    await q.answer()
    data = q.data

    if data == "edit:cancel":
        pending_edit.pop(user.id, None)
        await q.edit_message_text("❌ تم الإلغاء.")
        return

    if data == "edit:confirm":
        edit = pending_edit.pop(user.id, None)
        if not edit:
            await q.edit_message_text("⚠️ انتهت صلاحية هذا التعديل، أعد الإرسال.")
            return

        await q.edit_message_text("📤 جاري الرفع على GitHub…")
        try:
            # تطبيق التعديل
            code, sha = gh_get_file(REPO, FILE_PATH)
            # نستخدم SHA الجديد في حال تغيّر بين المعاينة والتأكيد
            if edit["old"] not in code:
                await q.edit_message_text("⚠️ تغيّر الكود منذ المعاينة. أعد إرسال التعليمة.")
                return

            new_code = code.replace(edit["old"], edit["new"], 1)
            gh_push_file(REPO, FILE_PATH, new_code, sha, edit["commit_msg"])

            await q.edit_message_text(
                f"✅ <b>تم الرفع بنجاح!</b>\n\n📝 {edit['commit_msg']}",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("confirm error", exc_info=True)
            await q.edit_message_text(f"❌ فشل الرفع: {str(e)[:300]}")


# ─── نقطة الدخول ──────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🤖 المساعد الذكي يعمل...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
