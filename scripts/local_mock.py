"""Disposable development runner: SQLite + fake Redis + mock XUI/payments.

VPN provisioning remains isolated; the dedicated observer maintains only supplied trial keys.
"""

import asyncio
import os
import threading
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.environ["APP_ENV"] = "development"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + (root / "local.db").as_posix()
os.environ["REDIS_URL"] = "redis://127.0.0.1:6389/0"
os.environ["XUI_MOCK_MODE"] = "true"
os.environ["PAYMENT_PROVIDER"] = "mock"
os.environ.setdefault("CARD_PROVIDER", "mock")
os.environ["CRYPTO_PROVIDER"] = "mock"
os.environ.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:8000")


async def run() -> None:
    import uvicorn

    from app.db.session import sessions
    from app.services.seed import seed
    from app.workers.run import main as run_worker

    async with sessions.begin() as db:
        await seed(db)
        from app.config import get_settings
        from scripts.bootstrap_portal import bootstrap

        await bootstrap(db, get_settings())
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=8000, access_log=False)
    server = uvicorn.Server(config)
    worker = asyncio.create_task(run_worker())
    try:
        await server.serve()
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


if __name__ == "__main__":
    from alembic.config import Config
    from fakeredis import TcpFakeServer

    from alembic import command

    os.chdir(root)
    command.upgrade(Config("alembic.ini"), "head")
    cache = TcpFakeServer(("127.0.0.1", 6389), server_type="redis")
    threading.Thread(target=cache.serve_forever, daemon=True).start()
    print("AERA runtime: http://127.0.0.1:8000/docs (SQLite; Stars and trial-only key maintenance)")
    try:
        asyncio.run(run())
    finally:
        cache.shutdown()
        cache.server_close()
