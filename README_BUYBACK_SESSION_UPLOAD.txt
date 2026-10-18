تحديث خيار شراء الحساب برفع ملف الجلسة

هذا الأرشيف يحتوي ملفات كاملة للاستبدال، وليس ملف فرق.

طريقة التطبيق:
1. فك الأرشيف من جذر المستودع Strat.
2. وافق على استبدال الملفات الثلاثة الموجودة تحت bot_app/.
3. أضف ملف الاختبار الجديد تحت tests/.
4. شغّل:
   python -m compileall -q bot.py bot_app
   python -m unittest discover -s tests -v

الملفات:
- bot_app/buyback.py
- bot_app/application.py
- bot_app/messages.py
- tests/test_buyback_session_upload.py

التحقق المحلي المنفّذ: compileall واختبارات المستودع، 96 اختباراً ناجحاً.
