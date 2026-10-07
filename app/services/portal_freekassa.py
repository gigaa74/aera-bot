from sqlalchemy import update

from app.core.exceptions import PaymentError
from app.db.models import Payment, SaleOrder, SupportTicket, User
from app.integrations.payments.freekassa import FreeKassaProvider
from app.services.paid_pool import enabled, reserve


async def checkout(db, settings, order_id, user_id):
    if not settings.freekassa_enabled or settings.card_provider != "freekassa":
        return None
    await db.execute(update(User).where(User.id == user_id).values(is_active=User.is_active))
    order = await db.get(SaleOrder, order_id, populate_existing=True)
    ticket = await db.get(SupportTicket, order.ticket_id) if order else None
    user = await db.get(User, user_id)
    if (
        not ticket
        or not user
        or ticket.user_id != user_id
        or order.paid_at
        or ticket.status not in {"OPEN", "IN_PROGRESS"}
        or user.is_blocked
        or not user.is_active
        or not user.terms_accepted_at
    ):
        raise PaymentError("Order unavailable")
    if not await enabled(db) or await reserve(db, order) is None:
        return None
    payment = await db.get(Payment, order.payment_id) if order.payment_id else None
    if payment:
        if payment.provider != "freekassa" or payment.status != "PENDING":
            raise PaymentError("Another payment already exists")
        return payment.details["checkout_url"]
    payment = Payment(
        user_id=user_id,
        plan_id=order.plan_id,
        amount_minor=order.amount_rub_minor,
        currency="RUB",
        provider="freekassa",
        details={"manual_order": order.id},
    )
    db.add(payment)
    await db.flush()
    payment.provider_payment_id = "fk-order:" + payment.id
    provider = FreeKassaProvider(
        settings.freekassa_merchant_id, settings.freekassa_secret1, settings.freekassa_secret2
    )
    url = provider.checkout_url(payment.id, payment.amount_minor, "RUB")
    payment.details = {**payment.details, "checkout_url": url, "provider_ready": True}
    order.payment_id = payment.id
    return url
