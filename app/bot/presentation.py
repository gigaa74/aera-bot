"""Branded photo screens and customer-facing tariff formatting."""

from html import escape
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InputMediaPhoto, Message

from app.services.catalog import FAMILIES, family_of

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "ui"
FILES = {
    name: f"{name}-v1.png"
    for name in ("welcome", "plans", "profile", "trial", "referral", "payments")
}
_file_ids = {}


def image_source(message, art):
    path = ASSETS / FILES[art]
    key = (message.bot.id, str(path), path.stat().st_mtime_ns)
    return key, _file_ids.get(key) or FSInputFile(path)


def remember(key, result):
    if isinstance(result, Message) and result.photo:
        _file_ids[key] = result.photo[-1].file_id


async def send_screen(message, text, reply_markup=None, art="welcome"):
    if len(text) > 1024:
        return await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)
    key, source = image_source(message, art)
    result = await message.answer_photo(
        source, caption=text, parse_mode="HTML", reply_markup=reply_markup
    )
    remember(key, result)
    return result


async def edit_screen(message, text, reply_markup=None, art=None):
    try:
        if len(text) > 1024 and message.photo:
            return await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)
        if art and len(text) <= 1024:
            key, source = image_source(message, art)
            if message.photo and isinstance(source, str) and message.photo[-1].file_id == source:
                return await message.edit_caption(
                    caption=text, parse_mode="HTML", reply_markup=reply_markup
                )
            result = await message.edit_media(
                InputMediaPhoto(media=source, caption=text, parse_mode="HTML"),
                reply_markup=reply_markup,
            )
            remember(key, result)
            return result
        if message.photo:
            return await message.edit_caption(
                caption=text, parse_mode="HTML", reply_markup=reply_markup
            )
        return await message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except TelegramBadRequest as error:
        if "message is not modified" not in error.message.lower():
            raise


def devices_label(count, unlimited=False):
    if unlimited:
        return "Безлимит устройств"
    if count == 1:
        return "1 устройство"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return f"{count} устройства"
    return f"{count} устройств"


def traffic_label(limit):
    return "Безлимитный трафик" if limit == 0 else f"Трафик: {limit / 1024**3:g} ГБ"


def period_label(plan):
    return {1: "1 месяц", 6: "6 месяцев"}.get(plan.duration_months, f"{plan.duration_days} дней")


def price_label(plan):
    return f"{plan.price_minor} ⭐" if plan.currency == "XTR" else f"{plan.price_minor / 100:g} ₽"


def plan_caption(plan):
    return (
        f"<b>{escape(plan.name)}</b>\n\n"
        f"{devices_label(plan.device_limit, plan.unlimited_devices)}\n"
        f"{traffic_label(plan.traffic_limit_bytes)}\n\n"
        f"<b>{price_label(plan)} · {period_label(plan)}</b>\n\n"
        "Продление - когда удобно.\nВыбери способ оплаты ниже."
    )


def catalog_caption(plans):
    parts = ["<b>ТАРИФЫ 💰</b>\n"]
    for family, (title, devices, *_rest) in FAMILIES.items():
        items = sorted(
            [p for p in plans if family_of(p) == family], key=lambda p: p.duration_months or 0
        )
        if items:
            prices = " · ".join(f"{price_label(p)} / {period_label(p)}" for p in items)
            parts.append(f"<b>{title}</b> - {devices}\n{prices}")
    parts.append("БЕЗЛИМИТНЫЙ ТРАФИК НА ВСЕХ ТАРИФАХ 🚀🔥\nВыбери свой вариант")
    return "\n\n".join(parts)


def family_caption(family, plans):
    title, devices, *_rest = FAMILIES[family]
    lines = [f"<b>AERA {title}</b>\n\n{devices}\nБезлимитный трафик\n"]
    for p in plans:
        lines.append(f"<b>{period_label(p)}</b> - {price_label(p)}")
    lines.append("\nВыбери срок подключения")
    return "\n".join(lines)


def subscription_caption(plan, sub, client, status):
    traffic = traffic_label(sub.traffic_limit_bytes)
    if sub.traffic_limit_bytes and client:
        traffic += f" · использовано {client.traffic_used_bytes / 1024**3:.1f} ГБ"
    return (
        f"<b>Твоя AERA</b>\n\n{escape(plan.name)}\n{escape(status)}\n"
        f"До {sub.expires_at:%d.%m.%Y}\n\n"
        f"{devices_label(sub.device_limit, sub.unlimited_devices)}\n{traffic}\n\n"
        "Подключи устройство или продли доступ ниже."
    )
