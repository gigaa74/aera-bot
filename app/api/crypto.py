import hmac
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.core.security import TokenVault
from app.db.models import CryptoMockReceipt
from app.db.session import sessions
from app.integrations.payments.crypto import MockCryptoProvider
from app.services.crypto import create_invoice, reconcile_invoice

router = APIRouter(prefix="/api/v1/payments/crypto/mock", tags=["crypto simulation"])


def enabled() -> None:
    settings = get_settings()
    if settings.app_env == "production" or not settings.crypto_mock_enabled:
        raise HTTPException(404)


def authorize(secret: str) -> None:
    enabled()
    if not hmac.compare_digest(secret, get_settings().crypto_mock_secret):
        raise HTTPException(403)


class InvoiceInput(BaseModel):
    user_id: str
    plan_id: str


class ReceiptInput(BaseModel):
    status: Literal["PENDING", "CONFIRMING", "PAID", "UNDERPAID", "EXPIRED"]
    received_amount: Decimal = Field(ge=0)
    asset: str = "TEST_USDT"
    network: str = "TESTNET"
    paid_at: datetime | None = None


@router.post("/invoices")
async def invoice(payload: InvoiceInput, x_crypto_mock_secret: str = Header(default="")) -> dict:
    authorize(x_crypto_mock_secret)
    async with sessions.begin() as db:
        invoice = await create_invoice(
            db, TokenVault(get_settings().app_secret), payload.user_id, payload.plan_id
        )
    return {
        "invoice_id": invoice.provider_invoice_id,
        "asset": invoice.asset,
        "network": invoice.network,
        "amount": invoice.expected_amount,
        "expires_at": invoice.expires_at,
    }


@router.put("/provider-ledger/{invoice_id}")
async def simulation(
    invoice_id: str, payload: ReceiptInput, x_crypto_mock_secret: str = Header(default="")
) -> dict:
    """Protected test harness representing a provider, never called by user payment buttons."""
    authorize(x_crypto_mock_secret)
    async with sessions.begin() as db:
        receipt = await db.scalar(
            select(CryptoMockReceipt)
            .where(CryptoMockReceipt.provider_invoice_id == invoice_id)
            .with_for_update()
        )
        if not receipt:
            raise HTTPException(404)
        receipt.status, receipt.asset, receipt.network = (
            payload.status,
            payload.asset,
            payload.network,
        )
        receipt.received_amount = str(payload.received_amount)
        receipt.paid_at = payload.paid_at or (
            datetime.now(UTC) if payload.status == "PAID" else None
        )
    return {"ok": True}


@router.post("/webhook")
async def webhook(request: Request, x_crypto_signature: str = Header(default="")) -> dict:
    enabled()
    settings = get_settings()
    provider = MockCryptoProvider(sessions, settings.crypto_mock_secret)
    invoice_id = provider.verify_webhook(await request.body(), x_crypto_signature)
    status = await reconcile_invoice(
        sessions, TokenVault(settings.app_secret), provider, invoice_id
    )
    return {"status": status}
