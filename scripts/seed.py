import asyncio

from app.config import get_settings
from app.db.session import engine, sessions
from app.services.seed import seed


async def main() -> None:
    async with sessions.begin() as db:
        await seed(db, get_settings().xui_mock_mode)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
