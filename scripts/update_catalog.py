"""Update only the project's local demo database; never imports or calls a panel adapter."""

import asyncio
import os
from pathlib import Path

os.environ["DATABASE_URL"] = (
    "sqlite+aiosqlite:///" + (Path(__file__).resolve().parents[1] / "local.db").as_posix()
)


async def main():
    from sqlalchemy import select

    from app.db.models import Plan
    from app.db.session import engine, sessions
    from app.services.catalog import catalog

    async with sessions.begin() as db:
        old = list(await db.scalars(select(Plan)))
        values = list(catalog(mock=True))
        slugs = {row["slug"] for row in values}
        for plan in old:
            if plan.slug not in slugs:
                plan.is_active = False
        for row in values:
            record = next((plan for plan in old if plan.slug == row["slug"]), None)
            if record is None:
                record = Plan(**row)
                db.add(record)
            else:
                for key, value in row.items():
                    setattr(record, key, value)
        print("Local catalog updated: 3 tariffs, 2 periods each; unlimited traffic")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
