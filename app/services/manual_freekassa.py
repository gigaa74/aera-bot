"""Real SCI checkout for an owned sale order; reserve stock before publishing a link."""
from sqlalchemy import select, update
from app.db.models import User, Plan, Payment, SaleOrder, SupportTicket
from app.integrations.payments.freekassa import FreeKassaProvider

async def checkout(db, settings, order_id, user, method='42'):
    if not settings.freekassa_enabled or settings.card_provider != 'freekassa' or method not in {'4','42'}:
        raise ValueError('FreeKassa unavailable')
    await db.execute(update(User).where(User.id==user.id).values(is_active=User.is_active))
    order=await db.get(SaleOrder,order_id,populate_existing=True)
    ticket=await db.get(SupportTicket,order.ticket_id) if order else None
    if not ticket or ticket.user_id!=user.id or ticket.status not in {'OPEN','IN_PROGRESS'} or order.paid_at or not user.is_active or user.is_blocked or not user.terms_accepted_at:
        raise ValueError('Order unavailable')
    plan=await db.get(Plan,order.plan_id)
    if not plan or not plan.is_active or plan.currency!='RUB':raise ValueError('Plan unavailable')
    payment=await db.get(Payment,order.payment_id,populate_existing=True) if order.payment_id else None
    if payment and (payment.provider!='freekassa' or payment.status!='PENDING'):
        raise ValueError('Another payment exists; cancel the unpaid Stars order first')
    if payment and payment.details.get('checkout_url'):
        provider=FreeKassaProvider(settings.freekassa_merchant_id,settings.freekassa_secret1,settings.freekassa_secret2)
        url=provider.checkout_url(payment.id,payment.amount_minor,'RUB',method=method)
        payment.details={**payment.details,'checkout_url':url,'method':method}
        return url
    from app.services.paid_pool import enabled,reserve
    if not await enabled(db) or await reserve(db,order) is None:return None
    if payment is None:
        payment=Payment(user_id=user.id,plan_id=plan.id,provider='freekassa',amount_minor=order.amount_rub_minor,currency='RUB',details={'manual_order':order.id})
        db.add(payment);await db.flush();order.payment_id=payment.id
        payment.provider_payment_id='fk-order:'+payment.id
    provider=FreeKassaProvider(settings.freekassa_merchant_id,settings.freekassa_secret1,settings.freekassa_secret2)
    url=provider.checkout_url(payment.id,payment.amount_minor,'RUB',method=method)
    payment.details={**payment.details,'checkout_url':url,'external_started':True,'method':method}
    return url
