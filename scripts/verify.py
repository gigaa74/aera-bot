"""Repeatable local checks; no Telegram or production XUI network calls."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(*arguments: str, env: dict | None = None) -> None:
    subprocess.run([sys.executable, *arguments], check=True, env=env)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    run("-m", "pip", "check")
    run("-m", "ruff", "check", ".")
    run("-m", "ruff", "format", "--check", ".")
    run("-m", "pytest", "-q")
    with tempfile.TemporaryDirectory(prefix="aera-check-") as directory:
        database = Path(directory) / "migrations.db"
        env = {**os.environ, "DATABASE_URL": "sqlite+aiosqlite:///" + database.as_posix()}
        run("-m", "alembic", "upgrade", "head", env=env)
        run("-m", "alembic", "check", env=env)
        run("-m", "alembic", "downgrade", "base", env=env)
        run("-m", "alembic", "upgrade", "head", env=env)
    env = {**os.environ, "DATABASE_URL": "postgresql+asyncpg://aera:aera@localhost/aera"}
    output = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "CREATE TABLE vpn_clients" in output.stdout
    run("-c", "import app.main, app.bot.runtime, app.workers.run; print('Imports: OK')")
    import yaml

    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    assert {"app", "worker", "redis", "postgres", "reverse-proxy"} <= compose["services"].keys()
    print("Compose YAML structure: OK; Docker CLI validation requires Docker installation")


if __name__ == "__main__":
    main()
