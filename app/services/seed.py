from sqlalchemy import select

from app.db.models import Plan, Server
from app.services.catalog import catalog


async def seed(db, mock: bool = True) -> None:
    if not await db.scalar(select(Plan.id).limit(1)):
        for values in catalog(mock=mock):
            db.add(Plan(**values))
    if mock and not await db.scalar(select(Server.id).limit(1)):
        db.add(Server(name="AERA Test", code="mock-01"))
