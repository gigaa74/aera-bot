"""Reserve owner-created keys, deliver only after verified payment, and read expiry."""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, or_, select, update

from app.db.models import (
    AppSetting,
    ManualAccess,
    PaidLink,
    Plan,
    SaleOrder,
    SupportTicket,
    TrialLink,
    User,
)
from app.services.commerce import utc
from app.services.notifications import enqueue
from app.services.trial_pool import parse_link


async def enabled(db):
    value = await db.get(AppSetting, "paid_pool_enabled")
    return value is not None and value.value == "true"


async def available(db, order):
    if not await enabled(db):
        return True
    return bool(
        await db.scalar(
            select(PaidLink.id)
            .where(
                PaidLink.plan_id == order.plan_id,
                PaidLink.status.in_(["FREE", "RESERVED"]),
                (PaidLink.order_id.is_(None) | (PaidLink.order_id == order.id)),
                PaidLink.checked_at > datetime.now(UTC) - timedelta(minutes=2),
            )
            .limit(1)
        )
    )


async def import_paid_links(db, groups, vault):
    for slug, links in groups.items():
        plan = await db.scalar(select(Plan).where(Plan.slug == slug, Plan.is_active.is_(True)))
        if not plan:
            raise ValueError("Unknown paid plan")
        for raw in links:
            identity, label = parse_link(raw)
            if await db.scalar(select(TrialLink.id).where(TrialLink.client_uuid == identity)):
                raise ValueError("Trial key cannot be sold")
            previous = await db.scalar(select(PaidLink).where(PaidLink.client_uuid == identity))
            if previous:
                if previous.plan_id != plan.id:
                    raise ValueError("Key already belongs to another plan")
                continue
            db.add(
                PaidLink(
                    client_uuid=identity,
                    label=label,
                    plan_id=plan.id,
                    link_encrypted=vault.cipher.encrypt(raw.strip().encode()).decode(),
                )
            )
            await db.flush()
    if groups and not await db.get(AppSetting, "paid_pool_enabled"):
        db.add(AppSetting(key="paid_pool_enabled", value="true"))


async def reserve(db, order):
    """Called during pre-checkout. Never release a key that may have been paid for."""
    previous = await db.scalar(select(PaidLink).where(PaidLink.order_id == order.id))
    if previous:
        return previous
    if not await enabled(db):
        return None
    ticket = await db.get(SupportTicket, order.ticket_id)
    await db.execute(update(User).where(User.id == ticket.user_id).values(is_active=User.is_active))
    previous = await db.scalar(select(PaidLink).where(PaidLink.order_id == order.id))
    if previous:
        return previous
    candidates = await db.scalars(
        select(PaidLink.id)
        .where(
            PaidLink.plan_id == order.plan_id,
            PaidLink.status == "FREE",
            PaidLink.order_id.is_(None),
            PaidLink.checked_at > datetime.now(UTC) - timedelta(minutes=2),
        )
        .order_by(PaidLink.created_at)
        .with_for_update(skip_locked=True)
    )
    for identity in candidates:
        claimed = await db.execute(
            update(PaidLink)
            .where(PaidLink.id == identity, PaidLink.status == "FREE", PaidLink.order_id.is_(None))
            .values(order_id=order.id, user_id=ticket.user_id, status="RESERVED")
        )
        if claimed.rowcount:
            return await db.get(PaidLink, identity, populate_existing=True)
    return None


async def fulfill(db, order, settings):
    if not order.paid_at or not await enabled(db):
        return False
    record = await reserve(db, order)
    ticket = await db.get(SupportTicket, order.ticket_id)
    if record is None:
        for identity in settings.admin_ids:
            admin = await db.scalar(select(User).where(User.telegram_id == identity))
            if admin:
                await enqueue(
                    db,
                    f"paid-no-stock:{order.id}:{identity}",
                    admin.id,
                    "PORTAL",
                    f"⚠️ Оплата получена, но свободного ключа нет. Покупка № {ticket.id[:8]}. "
                    "Пополни запас тарифа в /admin. Бот повторит выдачу автоматически.",
                )
        return False
    if not record.issued_at:
        record.issued_at = datetime.now(UTC)
        record.status = "WAITING" if record.started_at is None else record.status
    ticket.status, ticket.closed_at = "CONNECTED", record.issued_at
    # The queued payload contains only the record ID, never a plaintext VPN key.
    await enqueue(db, "paid-link:" + order.id, ticket.user_id, "ACCESS_READY", record.id)
    return True


async def retry_fulfillment(db, settings):
    """Recover a paid purchase awaiting stock without issuing a second key."""
    if not await enabled(db):
        return
    orders = list(
        await db.scalars(
            select(SaleOrder)
            .join(SupportTicket, SupportTicket.id == SaleOrder.ticket_id)
            .outerjoin(PaidLink, PaidLink.order_id == SaleOrder.id)
            .where(
                SaleOrder.paid_at.is_not(None),
                PaidLink.issued_at.is_(None),
                or_(PaidLink.id.is_not(None), SupportTicket.status.in_(["OPEN", "IN_PROGRESS"])),
            )
            .order_by(SaleOrder.paid_at)
            .limit(25)
        )
    )
    for order in orders:
        await fulfill(db, order, settings)


def current_access_condition():
    return and_(
        PaidLink.issued_at.is_not(None),
        or_(
            and_(PaidLink.status == "WAITING", PaidLink.expires_at.is_(None)),
            and_(PaidLink.status == "ACTIVE", PaidLink.expires_at > datetime.now(UTC)),
        ),
    )


def current_customer_condition():
    """A paid entitlement, not a historical ticket or an online/offline flag."""
    paid = exists(
        select(PaidLink.id)
        .join(SaleOrder, SaleOrder.id == PaidLink.order_id)
        .where(
            PaidLink.user_id == User.id, SaleOrder.paid_at.is_not(None), current_access_condition()
        )
    )
    legacy = exists(
        select(ManualAccess.id)
        .join(SupportTicket, SupportTicket.user_id == ManualAccess.user_id)
        .join(SaleOrder, SaleOrder.ticket_id == SupportTicket.id)
        .where(
            ManualAccess.user_id == User.id,
            ManualAccess.expires_at > datetime.now(UTC),
            SaleOrder.plan_id == ManualAccess.plan_id,
            SaleOrder.paid_at.is_not(None),
        )
    )
    return or_(paid, legacy)


async def current(db, user_id):
    return await db.scalar(
        select(PaidLink)
        .join(SaleOrder, SaleOrder.id == PaidLink.order_id)
        .where(
            PaidLink.user_id == user_id, SaleOrder.paid_at.is_not(None), current_access_condition()
        )
        .order_by(PaidLink.issued_at.desc(), PaidLink.id.desc())
        .limit(1)
    )


async def apply_paid_snapshot(db, snapshot, settings):
    config = snapshot.get("settings", {})
    if isinstance(config, str):
        config = json.loads(config)
    clients = {c.get("id"): c for c in config.get("clients", [])}
    stats_by_email = {t.get("email"): t for t in snapshot.get("clientStats", [])}
    now = datetime.now(UTC)
    for record in await db.scalars(select(PaidLink)):
        client = clients.get(record.client_uuid)
        if client is None:
            record.status = "UNAVAILABLE"
            continue
        stats = stats_by_email.get(client.get("email"), {})
        expiry_ms = int(stats.get("expiryTime") or client.get("expiryTime", 0))
        on = client.get("enable") is True and stats.get("enable", True) is True
        record.checked_at, record.panel_email = now, client.get("email")
        if record.order_id is None:
            plan = await db.get(Plan, record.plan_id)
            expected = plan.duration_days * 86400000
            # Validate the preconfigured term and IP limit; never change the panel.
            limits_ok = int(client.get("totalGB", 0)) == 0 and int(client.get("limitIp", 0)) == (
                0 if plan.unlimited_devices else plan.device_limit
            )
            valid_duration = expiry_ms == -expected
            record.status = "FREE" if on and limits_ok and valid_duration else "UNAVAILABLE"
            if valid_duration:
                record.duration_ms = -expiry_ms
            continue
        if expiry_ms > 0:
            record.expires_at = datetime.fromtimestamp(expiry_ms / 1000, UTC)
            if record.started_at is None and record.duration_ms:
                record.started_at = record.expires_at - timedelta(milliseconds=record.duration_ms)
            record.status = "ACTIVE" if on and utc(record.expires_at) > now else "EXPIRED"
        elif not on:
            record.status = "EXPIRED"
        elif record.started_at:
            record.status = "UNAVAILABLE"
        else:
            record.status = "WAITING" if record.issued_at else "RESERVED"


async def latest(db, user_id):
    return await db.scalar(
        select(PaidLink)
        .where(PaidLink.user_id == user_id, PaidLink.issued_at.is_not(None))
        .order_by(PaidLink.issued_at.desc(), PaidLink.id.desc())
        .limit(1)
    )
