"""Combined «بيع وتأجير الحسابات» entry screen for the main menu.

The screen only routes the member to the existing flows:
- «تأجير الحساب»  -> ``contributor_accounts`` (contributor rental flow)
- «بيع حساب»      -> ``buyback:start`` (account buyback flow)
- «فائدة التأجير والبيع» -> an explanation screen comparing the two.

No business logic of the rental or buyback flows lives here, so both flows
keep working unchanged from every other place that links to them.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})
from .buyback import is_buyback_visible, _buyback_price, format_buyback_price, user_has_buyback_offers

SELL_RENT_MENU_ACTION = "sell_rent:menu"
SELL_RENT_INFO_ACTION = "sell_rent:info"
SELL_RENT_MENU_LABEL = "💰 بيع وتأجير الحسابات"


def sell_rent_menu_text() -> str:
    return (
        "💰 *بيع وتأجير الحسابات*\n\n"
        "اختر الطريقة التي تناسبك لحسابك:\n\n"
        "📱 *تأجير الحساب* — يبقى الحساب ملكك وتربح من استخدامه.\n"
        "💰 *بيع حساب* — تبيع الحساب نهائياً وتستلم نقاطك.\n\n"
        "ولست متأكداً أيهما أفضل؟ اضغط «فائدة التأجير والبيع»."
    )


def sell_rent_menu_kb(is_owner: bool = False, user_id: int | None = None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("📱 تأجير الحساب", callback_data="contributor_accounts")]]
    # زر البيع يحترم إعداد المالك لإظهار/إخفاء قسم البيع كما في بقية الشاشات.
    if is_owner or is_buyback_visible():
        rows.append([InlineKeyboardButton("💰 بيع حساب", callback_data="buyback:start")])
    # من قدّم طلب بيع سابقاً يبقى قادراً على متابعة حالته حتى لو أُخفي قسم البيع.
    if user_id is not None and user_has_buyback_offers(user_id):
        rows.append([InlineKeyboardButton("📋 حالة طلبات البيع", callback_data="buyback:my_status")])
    rows.append([InlineKeyboardButton("ℹ️ فائدة التأجير والبيع", callback_data=SELL_RENT_INFO_ACTION)])
    rows.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def sell_rent_info_text(is_owner: bool = False) -> str:
    sell_price = format_buyback_price(_buyback_price())
    restricted_price = format_buyback_price(_buyback_price(restricted=True))
    lines = [
        "ℹ️ *فائدة التأجير والبيع*",
        "",
        "📱 *تأجير الحساب*",
        "• الحساب يبقى ملكك؛ لا يطرد البوت جلساتك ولا يغيّر كلمة مرورك أو إعداداتك.",
        "• يُستخدم حسابك في خدمات الرشق فقط.",
        "• تحصل على *50٪ من نقاط* كل طلب يُنفَّذ بنجاح بحسابك، فالربح يتكرر مع كل استخدام.",
        "• تتحكم في أنواع الخدمات المسموحة وتدير حسابك (الكود والأجهزة).",
        "✅ مناسب لمن يريد دخلاً مستمراً مع الاحتفاظ بحسابه.",
        "",
        "💰 *بيع الحساب*",
        "• تُنقل ملكية الحساب بالكامل: بعد موافقتك النهائية تُلغى الجلسات الأخرى "
        "ويُغيَّر الـ2FA ويُحذف بريد الاسترداد.",
        "• يُحجز الحساب 48 ساعة ويُفحص على مرحلتين (24 و48 ساعة)، ثم تستلم المبلغ دفعة واحدة.",
        f"• السعر: *{sell_price}* للحساب السليم، و*{restricted_price}* للحساب المقيّد بالإرسال.",
        "• لا يعود الحساب إليك بعد البيع.",
        "✅ مناسب لمن لا يحتاج الحساب ويريد نقاطاً دفعة واحدة.",
        "",
        "⚖️ *الخلاصة:* التأجير = ربح متكرر وأنت تحتفظ بحسابك، "
        "والبيع = مبلغ ثابت مرة واحدة وتخسر الحساب.",
    ]
    if not (is_owner or is_buyback_visible()):
        lines += ["", "⚠️ قسم البيع غير متاح حالياً، والتأجير متاح."]
    return "\n".join(lines)


def sell_rent_info_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=SELL_RENT_MENU_ACTION)],
    ])


async def handle_sell_rent_callback(update, context, q, data: str, user, is_owner: bool) -> bool:
    """Handle ``sell_rent:*`` callbacks. Returns True when the data was handled."""
    if data == SELL_RENT_MENU_ACTION:
        context.user_data["state"] = "main_menu"
        await q.edit_message_text(
            sell_rent_menu_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=sell_rent_menu_kb(is_owner, getattr(user, "id", None)),
        )
        return True

    if data == SELL_RENT_INFO_ACTION:
        await q.edit_message_text(
            sell_rent_info_text(is_owner),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=sell_rent_info_kb(),
        )
        return True

    return False
