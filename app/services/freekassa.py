from sqlalchemy import select, update

from app.core.exceptions import PaymentError
from app.db.models import Payment, SaleOrder, SupportTicket, User
from app.services.commerce import CommerceService


async def accept_event(db, vault, provider, fields, settings=None):
    order, transaction, amount = provider.verify_event(fields)
    owner = await db.scalar(select(Payment.user_id).where(Payment.id == order))
    if owner:
        await db.execute(update(User).where(User.id == owner).values(is_active=User.is_active))
    payment = await db.scalar(select(Payment).where(Payment.id == order).with_for_update().execution_options(populate_existing=True))
    if (
        not payment
        or payment.provider != "freekassa"
        or payment.currency != "RUB"
        or payment.amount_minor != amount
    ):
        raise PaymentError("FreeKassa order mismatch")
    # Namespace external IDs: the schema currently has a global unique constraint.
    provider_id = "fk:" + transaction
    if payment.provider_payment_id not in {"fk-order:" + payment.id, provider_id}:
        raise PaymentError("A different transaction already paid this order")
    duplicate = await db.scalar(
        select(Payment.id).where(
            Payment.provider_payment_id == provider_id, Payment.id != payment.id
        )
    )
    if duplicate:
        raise PaymentError("Transaction already assigned")
    if payment.status not in {"PENDING", "PAID"}:
        raise PaymentError("Payment unavailable")
    if payment.details.get("manual_order"):
        from datetime import UTC, datetime

        from app.services.portal import confirm_order

        sale = await db.scalar(select(SaleOrder).where(SaleOrder.payment_id == payment.id))
        ticket = await db.get(SupportTicket, sale.ticket_id) if sale else None
        if (
            settings is None
            or not sale
            or not ticket
            or sale.id != payment.details["manual_order"]
            or ticket.user_id != payment.user_id
            or sale.plan_id != payment.plan_id
            or sale.amount_rub_minor != payment.amount_minor
        ):
            raise PaymentError("Sale order mismatch")
        payment.provider_payment_id = provider_id
        if not payment.paid_at:
            payment.paid_at = datetime.now(UTC)
        payment.status = "PAID"
        await confirm_order(db, sale, settings)
        from app.services.notifications import enqueue
        from app.bot.texts.portal import text
        from app.db.models import PaidLink
        user = await db.get(User, payment.user_id)
        issued = await db.scalar(select(PaidLink.id).where(PaidLink.order_id == sale.id, PaidLink.issued_at.is_not(None)))
        await enqueue(db, "freekassa-paid:" + payment.id, user.id, "PORTAL", text("paid_ready" if issued else "paid", user.language_code))
        return
    if settings is not None and settings.manual_sales:
        raise PaymentError("Payment fulfillment route mismatch")
    payment.provider_payment_id = provider_id
    await CommerceService(db, vault).confirm(payment.id)
    # confirm creates the durable provisioning job. The worker retries panel failures.
