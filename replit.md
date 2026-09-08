# Strat Telegram Bot

هذا المستودع يشغّل بوت Telegram فقط لإدارة النقاط وخدمات الرشق والعمليات المرتبطة بها.

## Run & Operate

- `python bot.py` — تشغيل نقطة الدخول الأساسية للبوت.
- `python -m compileall -q bot.py bot_app` — فحص الصياغة قبل النشر.
- `python -m unittest discover -s tests -v` — تشغيل الاختبارات الخفيفة.
- Required env: `BOT_TOKEN`, `OWNER_ID`, `DATABASE_URL` and the configured panel/API variables.

## Stack

- Python Telegram bot with `python-telegram-bot` and PostgreSQL.
- The canonical source is the root `bot.py` and `bot_app/` package.
- Nested `bot_repo/`, `bot-source/`, `strat-repo/`, and `strat-work/` directories are archived copies and are not deployment entrypoints.

## Where things live

- `bot.py` — نقطة تشغيل البوت وإعادة التشغيل.
- `bot_app/application.py` — تسجيل أوامر ومعالجات Telegram.
- `bot_app/callback_groups_*.py` — أزرار القوائم، بما فيها لوحة المالك.
- `bot_app/messages.py` — استقبال إدخالات النص وحالات العمليات.
- `bot_app/shared.py` — الإعدادات المشتركة وعزل حالات عمليات المالك.
- `bot_app/services.py` — إعدادات القوائم والخدمات.
- `tests/` — اختبارات وحدات مستقلة عن Telegram وقاعدة البيانات.

## Architecture decisions

- عملية المالك تُعزل عبر `owner_flow` مع حالات مستقلة؛ لا تُستخدم حالة سعر عامة لعمليات النقاط أو الأكواد.
- تغيير السعر أو إضافة خدمة يبقى محصوراً بالمالك عبر فحوص `is_own`.
- PostgreSQL هو مصدر البيانات الدائم، بينما `context.user_data` يحتفظ بخطوات المحادثة المؤقتة فقط.

## Product

- إدارة المستخدمين والنقاط والأكواد الترويجية وأكواد شراء الأرقام.
- إنشاء وتعديل خدمات الرشق وربطها بمواقع SMM.
- تحويل النقاط، الاستبدال، الإحالات، والتحقق وإدارة الحسابات.

## User preferences

- المستودع المطلوب للعمل هو تطبيق البوت نفسه؛ عدّل المصدر الجذري `bot_app/` ولا تعدّل النسخ المؤرشفة.

## Gotchas

- لا تضف منطقاً جديداً إلى `bot.py`؛ ضع الميزة في الوحدة المناسبة داخل `bot_app/`.
- بعد تغيير حالات المحادثة، شغّل فحص الصياغة واختبارات `unittest`.
