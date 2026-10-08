import os

# app.db.session builds an engine at import time; keep it away from PostgreSQL defaults.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from datetime import UTC, datetime  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.config import Settings  # noqa: E402
from app.core.security import TokenVault  # noqa: E402
from app.db.models import Base, Plan, User  # noqa: E402


@pytest.fixture
async def sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def vault():
    return TokenVault("development-only-change-before-production")


@pytest.fixture
def settings():
    return Settings(_env_file=None, database_url=os.environ["DATABASE_URL"])


@pytest.fixture
async def plan_id(sessions):
    async with sessions.begin() as db:
        plan = Plan(
            name="Month", slug="month", price_minor=19900, traffic_limit_bytes=0, device_limit=3
        )
        db.add(plan)
        await db.flush()
        return plan.id


async def add_user(db, telegram_id):
    user = User(telegram_id=telegram_id, terms_accepted_at=datetime.now(UTC))
    db.add(user)
    await db.flush()
    return user
