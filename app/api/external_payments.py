from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select

from app.config import get_settings
from app.core.security import TokenVault
from app.db.models import Payment
from app.db.session import sessions
from app.integrations.payments.crypto_pay import CryptoPayProvider
from app.integrations.payments.yookassa import trusted_event_ip
from app.services.checkout import CheckoutService

router = APIRouter(prefix="/api/v1/payments", tags=["external payment events"])


async def reconcile(provider: str, provider_id: str) -> dict:
    async with sessions() as db:
        payment = await db.scalar(
            select(Payment).where(
                Payment.provider == provider, Payment.provider_payment_id == provider_id
            )
        )
    if not payment:
        raise HTTPException(404)
    settings = get_settings()
    status = await CheckoutService(sessions, settings, TokenVault(settings.app_secret)).reconcile(
        payment.id
    )
    return {"status": status}


@router.post("/yookassa/webhook")
async def yookassa_event(request: Request) -> dict:
    # Only trust request.client as configured by a trusted reverse proxy, not arbitrary headers.
    if not request.client or not trusted_event_ip(request.client.host):
        raise HTTPException(403)
    body = await request.json()
    if body.get("type") != "notification" or body.get("event") not in {
        "payment.succeeded",
        "payment.canceled",
    }:
        raise HTTPException(400)
    return await reconcile("yookassa", str(body["object"]["id"]))


@router.post("/crypto-pay/webhook")
async def crypto_event(
    request: Request, crypto_pay_api_signature: str = Header(default="")
) -> dict:
    settings = get_settings()
    adapter = CryptoPayProvider(settings.crypto_pay_token, settings.crypto_pay_testnet)
    try:
        invoice_id = adapter.verify_webhook(await request.body(), crypto_pay_api_signature)
    finally:
        await adapter.close()
    return await reconcile("crypto_pay", invoice_id)
