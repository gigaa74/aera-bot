from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)

if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def sqlite_privacy(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA secure_delete=ON")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


sessions = async_sessionmaker(engine, expire_on_commit=False)
