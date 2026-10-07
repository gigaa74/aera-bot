import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select

from app.core.exceptions import PaymentError
from app.db.models import CryptoMockReceipt


@dataclass(frozen=True)
class CryptoReceipt:
    invoice_id: str
    status: str
    asset: str
    network: str
    received_amount: Decimal
    paid_at: datetime | None


class CryptoPaymentProvider(Protocol):
    async def get_invoice(self, invoice_id: str) -> CryptoReceipt: ...

    def verify_webhook(self, raw_body: bytes, signature: str) -> str: ...


class MockCryptoProvider:
    """Local simulation only; no addresses, blockchains or real transfers."""

    def __init__(self, sessions, secret: str):
        self.sessions = sessions
        self.key = hashlib.sha256(secret.encode()).digest()

    def sign(self, raw_body: bytes) -> str:
        return hmac.new(self.key, raw_body, hashlib.sha256).hexdigest()

    def verify_webhook(self, raw_body: bytes, signature: str) -> str:
        if len(raw_body) > 16384 or not hmac.compare_digest(self.sign(raw_body), signature):
            raise PaymentError("Invalid crypto event signature")
        try:
            event = json.loads(raw_body)
            sent = datetime.fromisoformat(event["request_date"])
            if sent.tzinfo is None or abs((datetime.now(UTC) - sent).total_seconds()) > 300:
                raise ValueError("Expired event")
            return str(event["invoice_id"])
        except (KeyError, ValueError, TypeError):
            raise PaymentError("Invalid crypto event") from None

    async def get_invoice(self, invoice_id: str) -> CryptoReceipt:
        async with self.sessions() as db:
            receipt = await db.scalar(
                select(CryptoMockReceipt).where(CryptoMockReceipt.provider_invoice_id == invoice_id)
            )
            if not receipt:
                raise PaymentError("Unknown provider invoice")
            return CryptoReceipt(
                invoice_id,
                receipt.status,
                receipt.asset,
                receipt.network,
                Decimal(receipt.received_amount),
                receipt.paid_at,
            )
