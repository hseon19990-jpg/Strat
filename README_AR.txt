ملفات إصلاح كابتشا التصويت

استبدل الملفات التالية داخل المشروع مع الحفاظ على المسارات:

bot_app/raksh_system/forced_ref_ai.py
  الملف الأساسي المستخدم في إحالة البوت مع التحقق و votes_ai.

tests/test_forced_ref_ai_helpers.py
  اختبار دعم كابتشا الهدف 🎯.

بعد الاستبدال شغّل:
python -m unittest discover -s tests -v
