"""Scaffold for the all-posts reactions service.

The service is registered with its own pricing and visibility settings, but
remains hidden until its execution flow is supplied and enabled deliberately.
"""

from .common import *


class AllPostsReactionsService(RakshService):
    """خدمة رشق تفاعلات لكل البوستات — الهيكل الأولي."""

    service_type = "all_posts_reactions"
    label = "✨ رشق تفاعلات لكل البوستات"
    config = ServiceConfig(
        name=label,
        price_points=1,
        points_quantity=1,
        price_stars=1,
        stars_quantity=1,
        has_channel=False,
        has_reaction=True,
        has_ai=False,
        needs_link=False,
        min_delay=3,
        max_delay=3,
    )

    def is_enabled(self) -> bool:
        """تبقى مخفية حتى يكتمل منطقها ويقرر المالك تفعيلها."""
        setting = get_setting(f"raksh_service_enabled_{self.service_type}")
        if setting is None or not str(setting).strip():
            return False
        return super().is_enabled()

    def get_start_message(self) -> str:
        return (
            f"{self.config.name}\n\n"
            "⚠️ هذه الخدمة قيد التجهيز حالياً.\n"
            "سيتم تفعيلها بعد إضافة طريقة التنفيذ."
        )

    async def handle_text(self, update, context, text, user, state, is_own) -> bool:
        await update.message.reply_text(
            "⚠️ هذه الخدمة قيد التجهيز حالياً. أرسل طريقة عملها للمتابعة.",
            reply_markup=self.get_start_keyboard(),
        )
        context.user_data["state"] = "main_menu"
        return True

    async def execute(self, session: Dict, params: Dict, is_first: bool) -> Tuple[bool, str]:
        raise NotImplementedError(
            "لم تتم إضافة طريقة تنفيذ خدمة رشق تفاعلات لكل البوستات بعد"
        )
