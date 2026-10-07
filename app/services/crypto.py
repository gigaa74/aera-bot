from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.exceptions import PaymentError
from app.db.models import CryptoInvoice, CryptoMockReceipt, Payment, uid
from app.integrations.payments.crypto import CryptoPaymentProvider
from app.services.commerce import CommerceService, utc


async def create_invoice(db, vault, user_id: str, plan_id: str) -> CryptoInvoice:
    service = CommerceService(db, vault)
    payment = await service.purchase(user_id, plan_id, provider="crypto_mock")
    if payment.currency != "RUB":
        raise PaymentError("Mock crypto quote requires a RUB test plan")
    # FIXED TEST QUOTE ONLY: 100 test rubles = 1 fictional TEST_USDT. Not a market price.
    amount = Decimal(payment.amount_minor) / Decimal(10000)
    provider_id = uid()
    payment.provider_payment_id = provider_id
    invoice = CryptoInvoice(
        payment_id=payment.id,
        provider_invoice_id=provider_id,
        asset="TEST_USDT",
        network="TESTNET",
        expected_amount=str(amount),
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    db.add(invoice)
    db.add(CryptoMockReceipt(provider_invoice_id=provider_id, asset="TEST_USDT", network="TESTNET"))
    await db.flush()
    return invoice


async def reconcile_invoice(
    sessions, vault, provider: CryptoPaymentProvider, provider_id: str
) -> str:
    # The event is a hint; query the provider's authoritative ledger before granting access.
    receipt = await provider.get_invoice(provider_id)
    async with sessions.begin() as db:
        invoice = await db.scalar(
            select(CryptoInvoice)
            .where(CryptoInvoice.provider_invoice_id == provider_id)
            .with_for_update()
        )
        if not invoice:
            raise PaymentError("Unknown local invoice")
        payment = await db.get(Payment, invoice.payment_id)
        if (
            payment.provider != "crypto_mock"
            or payment.provider_payment_id != provider_id
            or receipt.invoice_id != provider_id
            or receipt.asset != invoice.asset
            or receipt.network != invoice.network
        ):
            raise PaymentError("Crypto invoice identity or currency mismatch")
        if invoice.status == "PAID" and payment.applied_at:
            return "PAID"
        if receipt.status == "PAID":
            if receipt.received_amount != Decimal(invoice.expected_amount):
                invoice.status = (
                    "UNDERPAID"
                    if receipt.received_amount < Decimal(invoice.expected_amount)
                    else "REVIEW"
                )
                return invoice.status
            if not receipt.paid_at or utc(receipt.paid_at) > utc(invoice.expires_at):
                invoice.status = "REVIEW"
                return "REVIEW"
            await CommerceService(db, vault).confirm(payment.id)
            invoice.status = "PAID"
            return "PAID"
        if receipt.status == "UNDERPAID":
            invoice.status = "UNDERPAID"
        elif datetime.now(UTC) >= utc(invoice.expires_at):
            invoice.status = "EXPIRED"
        elif receipt.status == "CONFIRMING":
            invoice.status = "CONFIRMING"
        else:
            invoice.status = "PENDING"
        return invoice.status
