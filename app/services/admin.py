from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.exceptions import AccessDeniedError
from app.core.security import TokenVault
from app.db.models import (
    AuditLog,
    Broadcast,
    BroadcastDelivery,
    Payment,
    ProvisioningJob,
    Subscription,
    SupportMessage,
    SupportTicket,
    User,
    VPNClient,
)
from app.services.commerce import CommerceService, utc


class AdminService:
    def __init__(self, db: AsyncSession, settings: Settings, admin_id: int):
        if admin_id not in settings.admin_ids:
            raise AccessDeniedError("Administrator required")
        self.db, self.settings, self.admin_id = db, settings, admin_id

    def audit(self, action: str, entity_type: str, entity_id: str, **details) -> None:
        self.db.add(
            AuditLog(
                admin_user_id=self.admin_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details,
            )
        )

    async def analytics(self) -> dict:
        result = {}
        for name, model in [
            ("users", User),
            ("subscriptions", Subscription),
            ("payments", Payment),
            ("vpn_clients", VPNClient),
            ("support_tickets", SupportTicket),
        ]:
            result[name] = await self.db.scalar(select(func.count()).select_from(model))
        result["active_subscriptions"] = await self.db.scalar(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.status.in_(["ACTIVE", "EXPIRING", "TRIAL"]))
        )
        result["revenue"] = dict(
            (currency, amount)
            for currency, amount in (
                await self.db.execute(
                    select(Payment.currency, func.sum(Payment.amount_minor))
                    .where(Payment.status == "PAID")
                    .group_by(Payment.currency)
                )
            ).all()
        )
        result["traffic_bytes"] = await self.db.scalar(
            select(func.coalesce(func.sum(VPNClient.traffic_used_bytes), 0))
        )
        return result

    async def change_access(
        self, user_id: str, action: str, confirmed: bool, days: int = 30
    ) -> None:
        if not confirmed:
            raise AccessDeniedError("Explicit operation confirmation required")
        user = await self.db.scalar(select(User).where(User.id == user_id).with_for_update())
        if not user:
            raise ValueError("Unknown user")
        service = CommerceService(self.db, TokenVault(self.settings.app_secret))
        sub, client = await service.subscription(user.id)
        if not sub:
            raise ValueError("No subscription")
        if action == "extend":
            if not 1 <= days <= 3650:
                raise ValueError("Invalid duration")
            sub.expires_at = max(utc(sub.expires_at), datetime.now(UTC)) + timedelta(days=days)
            sub.status = "PENDING_PROVISIONING"
        elif action == "disable":
            user.is_blocked = True
            sub.status = "SUSPENDED"
            if client:
                client.enabled = False
        elif action == "enable":
            user.is_blocked = False
            sub.status = "PENDING_PROVISIONING"
        elif action == "rotate":
            await service.rotate_token(user.id)
        elif action == "revoke":
            await service.rotate_token(user.id, revoke=True)
        else:
            raise ValueError("Unsupported operation")
        if action not in {"rotate", "revoke"}:
            self.db.add(ProvisioningJob(subscription_id=sub.id))
        self.audit(action, "User", user.id, days=days if action == "extend" else None)

    async def reply_ticket(self, ticket_id: str, text: str, close: bool = False) -> str:
        from app.services.notifications import enqueue

        ticket = await self.db.get(SupportTicket, ticket_id)
        if not ticket or not text or len(text) > 3500:
            raise ValueError("Invalid support response")
        if ticket.category == "TARIFF_REQUEST" and ticket.status not in {"OPEN", "IN_PROGRESS"}:
            raise ValueError("Tariff request is closed")
        message = SupportMessage(
            ticket_id=ticket.id, sender_type="ADMIN", sender_id=str(self.admin_id), text=text
        )
        self.db.add(message)
        await self.db.flush()
        ticket.status = "RESOLVED" if close else "IN_PROGRESS"
        if close:
            ticket.closed_at = datetime.now(UTC)
        user = await self.db.get(User, ticket.user_id)
        from app.bot.texts.portal import text as local_text

        await enqueue(
            self.db,
            f"support:{message.id}",
            ticket.user_id,
            "SUPPORT",
            local_text("support_reply", user.language_code) + ":\n\n" + text,
        )
        self.audit("support_reply", "SupportTicket", ticket.id)
        return message.id

    async def broadcast(
        self,
        text: str,
        confirmed: bool,
        image_file_id: str | None = None,
        button_text: str | None = None,
        button_url: str | None = None,
    ) -> Broadcast:
        if not confirmed or not text or len(text) > (1000 if image_file_id else 4000):
            raise ValueError("Confirm valid broadcast before sending")
        if button_url and not button_url.startswith("https://"):
            raise ValueError("HTTPS button URL required")
        users = list(
            await self.db.scalars(
                select(User).where(User.is_active.is_(True), User.is_blocked.is_(False))
            )
        )
        broadcast = Broadcast(
            admin_user_id=self.admin_id,
            text=text,
            image_file_id=image_file_id,
            button_text=button_text,
            button_url=button_url,
            total=len(users),
        )
        self.db.add(broadcast)
        await self.db.flush()
        for user in users:
            self.db.add(BroadcastDelivery(broadcast_id=broadcast.id, user_id=user.id))
        self.audit("broadcast", "Broadcast", broadcast.id, total=len(users))
        return broadcast
