#!/bin/bash
# سكريبت لدفع التعديلات إلى GitHub (وبالتالي Railway يعيد النشر تلقائياً)

cd "$(dirname "$0")"

# تأكد من وجود تعديلات
if [ -z "$(git status --porcelain)" ]; then
  echo "✅ لا يوجد تعديلات جديدة"
  exit 0
fi

# اطلب رسالة commit
MSG="${1:-تحديث البوت}"

git add -A
git commit -m "$MSG"
git push origin main

echo ""
echo "✅ تم الدفع! Railway سيعيد تشغيل البوت خلال دقيقة تقريباً."
