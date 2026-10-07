from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProvisioningJob, Referral, Subscription, User
from app.services.commerce import utc
from app.services.settings import setting


async def register_referral(db: AsyncSession, user: User, code: str) -> bool:
    referrer = await db.scalar(select(User).where(User.referral_code == code))
    if not referrer or referrer.id == user.id or user.referred_by_id:
        return False
    if (datetime.now(UTC) - utc(user.created_at)).total_seconds() > 60:
        return False
    user.referred_by_id = referrer.id
    db.add(
        Referral(
            referrer_user_id=referrer.id,
            referred_user_id=user.id,
            code=code,
            reward_value=int(await setting(db, "referral_reward_days", "7")),
        )
    )
    return True


async def reward_referrals(db: AsyncSession) -> None:
    referrals = await db.scalars(
        select(Referral).where(Referral.status == "ELIGIBLE").with_for_update(skip_locked=True)
    )
    for referral in referrals:
        sub = await db.scalar(
            select(Subscription)
            .where(Subscription.user_id == referral.referrer_user_id)
            .with_for_update()
        )
        if not sub or sub.status in {"SUSPENDED", "CANCELLED"}:
            continue
        sub.expires_at = max(utc(sub.expires_at), datetime.now(UTC)) + timedelta(
            days=referral.reward_value
        )
        sub.status = "PENDING_PROVISIONING"
        db.add(ProvisioningJob(subscription_id=sub.id))
        referral.status = "REWARDED"
        referral.rewarded_at = datetime.now(UTC)
