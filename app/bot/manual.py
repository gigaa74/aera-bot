from html import escape

from app.bot.keyboards import keyboard
from app.bot.presentation import edit_screen, period_label, price_label
from app.bot.texts import ru
from app.config import get_settings
from app.core.security import TokenVault
from app.db.session import sessions
from app.services.commerce import CommerceService
from app.services.notifications import send_notifications
from app.services.requests import select_tariff


async def submit_selection(call, plan_id):
    settings = get_settings()
    async with sessions.begin() as db:
        service = CommerceService(db, TokenVault(settings.app_secret))
        user = await service.user(
            call.from_user.id,
            username=call.from_user.username,
            first_name=call.from_user.first_name,
        )
        ticket, plan = await select_tariff(db, service, user, plan_id, settings.admin_ids)
        keys = {f"request:{ticket.id}:{admin_id}" for admin_id in settings.admin_ids}
        text = ru.MANUAL_SENT.format(
            plan=escape(plan.name),
            period=period_label(plan),
            price=price_label(plan),
            id=ticket.id[:8],
        )
    # Commit before delivery. The worker retries if Telegram is temporarily unavailable.
    await send_notifications(sessions, call.bot, keys=keys)
    await edit_screen(
        call.message,
        text,
        reply_markup=keyboard(("Как установить Hiddify", "connect"), ("Главное меню", "menu")),
        art="plans",
    )
