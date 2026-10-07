"""Run a complete mock purchase and renewal without Telegram, Redis or a VPS."""

import asyncio
import os
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///demo.db"
os.environ["XUI_MOCK_MODE"] = "true"


async def main() -> None:
    from sqlalchemy import select

    from app.core.security import TokenVault
    from app.db.models import ProvisioningJob
    from app.db.session import engine, sessions
    from app.integrations.xui.mock import MockXUIClient
    from app.services.commerce import CommerceService
    from app.services.provisioning import ProvisioningService
    from app.services.seed import seed

    vault, adapter = TokenVault("demo-only"), MockXUIClient()
    worker = ProvisioningService(sessions, adapter, vault)
    async with sessions.begin() as db:
        await seed(db)
        service = CommerceService(db, vault)
        user = await service.user(100001)
        plan = (await service.plans())[1]
        payment = await service.purchase(user.id, plan.id)
        await service.confirm(payment.id)
        await service.confirm(payment.id)
        await db.flush()
        job_id = await db.scalar(
            select(ProvisioningJob.id).where(ProvisioningJob.payment_id == payment.id)
        )
    assert await worker.run(job_id)
    async with sessions.begin() as db:
        service = CommerceService(db, vault)
        sub, client = await service.subscription(user.id)
        identity = client.uuid
        print(f"Purchase: {plan.name}, {sub.status}, expires {sub.expires_at:%Y-%m-%d}")
        payment = await service.purchase(user.id, plan.id)
        await service.confirm(payment.id)
        await db.flush()
        job_id = await db.scalar(
            select(ProvisioningJob.id).where(ProvisioningJob.payment_id == payment.id)
        )
    assert await worker.run(job_id)
    async with sessions() as db:
        sub, client = await CommerceService(db, vault).subscription(user.id)
        assert client.uuid == identity
        print(f"Renewal: same VPN client, expires {sub.expires_at:%Y-%m-%d}")
    await engine.dispose()


if __name__ == "__main__":
    from alembic.config import Config

    from alembic import command

    os.chdir(Path(__file__).resolve().parents[1])
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(main())
