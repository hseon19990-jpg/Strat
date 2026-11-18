"""فحص ملكية البوت للحساب قبل إرسال كود الدخول.

إذا كان للبوت جلسة حيّة على الرقم في المخزون فلا معنى لأن يبيعه أو يؤجّره
شخص آخر، ويجب رفض العملية قبل أن يُرسَل أي كود إلى الرقم.

يُعدّ الحساب «مملوكاً للبوت» عندما:
- السجل غير محذوف،
- فيه جلسة غير فارغة،
- الجلسة لم تُسجَّل كمطرودة/منتهية (last_authorized ليس FALSE)،
- ولم يُبَع لزبون سابقاً (ever_sold)، فالحسابات التي بيعت يبقى بيعها
  للبوت مجدداً ممكناً عبر مسار الشراء المعتاد.
"""

from __future__ import annotations

import logging
import re

from .database import db_conn

logger = logging.getLogger(__name__)

BOT_OWNS_ACCOUNT_SELL_MESSAGE = (
    "⛔ لا يمكن بيع هذا الحساب.\n\n"
    "هذا الحساب موجود في حسابات البوت وللبوت جلسة عليه، لذلك رُفضت العملية "
    "ولم يُرسَل أي كود إلى الرقم."
)
BOT_OWNS_ACCOUNT_RENT_MESSAGE = (
    "⛔ لا يمكن تأجير هذا الحساب.\n\n"
    "هذا الحساب موجود في حسابات البوت وللبوت جلسة عليه، لذلك رُفضت العملية "
    "ولم يُرسَل أي كود إلى الرقم."
)


def bot_holds_live_session(phone: str) -> bool:
    """هل للبوت جلسة حيّة على هذا الرقم؟ يطابق الأرقام فقط بغض النظر عن + والمسافات.

    عند تعذّر قراءة قاعدة البيانات نُرجع False كي لا تتعطل العملية؛ فحوص
    ما بعد تسجيل الدخول تبقى حاجزاً احتياطياً.
    """
    digits = re.sub(r"\D+", "", str(phone or ""))
    if not digits:
        return False
    try:
        with db_conn() as c:
            row = c.execute(
                "SELECT 1 FROM number_stock "
                "WHERE regexp_replace(phone_number, '[^0-9]', '', 'g') = %s "
                "AND deleted_at IS NULL "
                "AND session_string IS NOT NULL AND BTRIM(session_string) <> '' "
                "AND last_authorized IS NOT FALSE "
                "AND ever_sold IS NOT TRUE "
                "LIMIT 1",
                (digits,),
            ).fetchone()
        return bool(row)
    except Exception:
        logger.exception("تعذر فحص ملكية البوت للحساب قبل إرسال الكود")
        return False
