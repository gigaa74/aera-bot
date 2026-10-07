from aiogram import Bot
from aiogram.types import LabeledPrice

from app.core.exceptions import PaymentError


class TelegramStarsProvider:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def create_payment(
        self, payment_id: str, amount_minor: int, currency: str, *, lang="ru"
    ) -> str:
        if currency != "XTR" or amount_minor <= 0:
            raise PaymentError("Stars payments require positive integer XTR amounts")
        label = {
            "ru": "Подписка AERA",
            "en": "AERA subscription",
            "zh": "AERA 订阅",
            "fa": "اشتراک AERA",
        }.get(lang, "AERA subscription")
        return await self.bot.create_invoice_link(
            title="AERA VPN",
            description=label,
            payload=payment_id,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=label, amount=amount_minor)],
        )

    async def verify_payment(self, provider_payment_id: str) -> bool:
        # A client callback never proves payment. Only successful_payment updates can grant access.
        raise PaymentError("Verify the authenticated Telegram successful_payment update")

    async def process_webhook(self, payload: dict, secret: str) -> str:
        raise PaymentError("Stars updates are processed through authenticated Telegram updates")

    async def refund(self, provider_payment_id: str, telegram_id: int) -> None:
        await self.bot.refund_star_payment(
            user_id=telegram_id, telegram_payment_charge_id=provider_payment_id
        )
