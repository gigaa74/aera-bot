"""Trial counters distinguish assignments, activation and live subscriptions."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select

from app.db.models import TrialLink, TrialUsage


async def trial_summary(db):
    active = (
        (TrialLink.status == "ACTIVE")
        & (TrialLink.expires_at > datetime.now(UTC))
        & (TrialLink.checked_at > datetime.now(UTC) - timedelta(minutes=2))
    )
    counts = (
        await db.execute(
            select(
                func.count(TrialLink.id),
                func.sum(case((TrialLink.status == "FREE", 1), else_=0)),
                func.sum(case((TrialLink.status == "WAITING", 1), else_=0)),
                func.sum(case((active, 1), else_=0)),
                func.count(TrialLink.started_at),
            )
        )
    ).one()
    issued = await db.scalar(select(func.count()).select_from(TrialUsage))
    activated = await db.scalar(select(func.count(TrialUsage.activated_at)))
    total, free, waiting, live, _ = [int(v or 0) for v in counts]
    return (
        "🎁 ПРОБНЫЕ ПОДПИСКИ\n\n"
        f"📤 Получили пробную: {issued}\n"
        f"🚀 Сейчас активны: {live}\n"
        f"⏳ Ждут первого подключения: {waiting}\n"
        f"💎 Активировали всего: {activated}\n"
        f"✅ Свободных ссылок: {free} / {total}"
    )
