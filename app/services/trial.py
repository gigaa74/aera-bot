from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.exceptions import AccessDeniedError
from app.db.models import Plan, ProvisioningJob, Subscription, User
from app.services.settings import setting


async def activate_trial(db, user_id: str) -> str:
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if (
        await setting(db, "trial_enabled", "false") != "true"
        or user.trial_used
        or user.is_blocked
        or not user.is_active
        or await db.scalar(select(Subscription.id).where(Subscription.user_id == user_id))
    ):
        raise AccessDeniedError("Trial unavailable")
    plan = await db.scalar(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order))
    if not plan:
        raise ValueError("No trial plan")
    days = int(await setting(db, "trial_days", "3"))
    if not 1 <= days <= 30:
        raise ValueError("Invalid trial duration")
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="PENDING_PROVISIONING",
        expires_at=datetime.now(UTC) + timedelta(days=days),
        traffic_limit_bytes=min(plan.traffic_limit_bytes or 10 * 1024**3, 10 * 1024**3),
        device_limit=1,
    )
    db.add(sub)
    await db.flush()
    job = ProvisioningJob(subscription_id=sub.id)
    db.add(job)
    user.trial_used = True
    await db.flush()
    return job.id
