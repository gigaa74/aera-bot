from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSetting


async def setting(db: AsyncSession, key: str, default: str = "") -> str:
    record = await db.get(AppSetting, key)
    return record.value if record else default


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    record = await db.get(AppSetting, key)
    if record:
        record.value = value
    else:
        db.add(AppSetting(key=key, value=value))
