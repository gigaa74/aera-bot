import hmac

from app.core.exceptions import PaymentError


class MockPaymentProvider:
    def __init__(self, secret: str):
        self.secret = secret

    async def create_payment(self, payment_id: str, amount_minor: int, currency: str) -> str:
        return payment_id

    async def verify_payment(self, provider_payment_id: str) -> bool:
        return True

    async def process_webhook(self, payload: dict, secret: str) -> str:
        if not hmac.compare_digest(secret, self.secret):
            raise PaymentError("Invalid webhook authentication")
        return str(payload["payment_id"])

    async def refund(self, provider_payment_id: str) -> None:
        return None
