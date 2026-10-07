"""Read-only launch checks. No Telegram, payment, XUI or database network requests."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from app.config import Settings


def configuration_checks(values: dict) -> list[tuple[str, bool]]:
    def present(key: str) -> bool:
        return bool(values.get(key))

    def enabled(key: str) -> bool:
        return str(values.get(key, "")).lower() in {"true", "1", "yes", "on"}

    try:
        candidate = {name: field.default for name, field in Settings.model_fields.items()}
        candidate.update({k.lower(): v for k, v in values.items()})
        candidate["app_env"] = "production"
        Settings(_env_file=None, **candidate)
        production_valid = True
    except (ValueError, TypeError):
        production_valid = False
    try:
        credentials = json.loads(values.get("XUI_CREDENTIALS_JSON") or "{}")
        protected = {
            h.strip().lower().rstrip(".")
            for h in (values.get("XUI_PROTECTED_HOSTS") or "").split(",")
            if h.strip()
        }
        credentials_valid = isinstance(credentials, dict) and bool(credentials)
        separate = (
            credentials_valid
            and bool(protected)
            and all(
                (urlsplit(c.get("base_url", "")).hostname or "").lower().rstrip(".")
                not in protected
                for c in credentials.values()
                if isinstance(c, dict)
            )
        )
    except (ValueError, TypeError, AttributeError):
        credentials_valid = separate = False
    return [
        ("Настройки проходят базовую проверку production", production_valid),
        ("Указан токен бота", present("BOT_TOKEN")),
        (
            "Указаны администраторы и ключ admin API",
            present("ADMIN_TELEGRAM_IDS") and present("ADMIN_API_TOKEN"),
        ),
        (
            "База настроена на PostgreSQL",
            str(values.get("DATABASE_URL", "")).startswith("postgresql+asyncpg://"),
        ),
        (
            "Публичный адрес использует HTTPS",
            str(values.get("PUBLIC_BASE_URL", "")).startswith("https://"),
        ),
        ("Имитация VPN отключена", not enabled("XUI_MOCK_MODE") and present("XUI_MOCK_MODE")),
        ("Запись разрешена для новой панели", enabled("XUI_ALLOW_WRITES")),
        ("Указаны учётные данные панели", credentials_valid),
        (
            "Существующая панель внесена в список защиты",
            bool(protected) if credentials_valid else bool(values.get("XUI_PROTECTED_HOSTS")),
        ),
        ("Адреса credentials не указывают на защищённую панель", separate),
        (
            "Stars работают без имитации",
            values.get("PAYMENT_PROVIDER") in {"live", "telegram_stars"},
        ),
        (
            "Карта / СБП: выбран провайдер и указаны ключи",
            values.get("CARD_PROVIDER") == "yookassa"
            and present("YOOKASSA_SHOP_ID")
            and present("YOOKASSA_SECRET_KEY"),
        ),
        (
            "Крипто: выбран провайдер, ключ и основная сеть",
            values.get("CRYPTO_PROVIDER") == "crypto_pay"
            and present("CRYPTO_PAY_TOKEN")
            and present("CRYPTO_PAY_TESTNET")
            and not enabled("CRYPTO_PAY_TESTNET"),
        ),
    ]


def local_catalog_checks(path: Path, values: dict) -> list[tuple[str, bool]]:
    # mode=ro cannot create a database or migrate/modify existing records.
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        plans = db.execute("SELECT stars_price FROM plans WHERE is_active = 1").fetchall()
        servers = db.execute("SELECT xui_base_url FROM servers WHERE is_active = 1").fetchall()
    protected = {
        h.strip().lower().rstrip(".")
        for h in (values.get("XUI_PROTECTED_HOSTS") or "").split(",")
        if h.strip()
    }
    return [
        (
            "Есть активные тарифы с положительными ценами Stars",
            bool(plans) and all(p[0] and p[0] > 0 for p in plans),
        ),
        (
            "Есть активная отдельная HTTPS панель в базе",
            bool(servers)
            and all(
                url.startswith("https://")
                and (urlsplit(url).hostname or "").lower().rstrip(".") not in protected
                for (url,) in servers
            ),
        ),
    ]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--local-db", type=Path, help="Optional read-only SQLite catalog check")
    args = parser.parse_args()
    if not args.env_file.is_file():
        print("НЕ ГОТОВО: приватный файл настроек не найден")
        return 1
    # Deliberately inspect this file only, without inheriting shell overrides.
    values = dict(dotenv_values(args.env_file, interpolate=False))
    checks = configuration_checks(values)
    if args.local_db:
        try:
            checks.extend(local_catalog_checks(args.local_db, values))
        except (sqlite3.Error, OSError, ValueError):
            checks.append(("Локальная база доступна для проверки", False))
    for label, ok in checks:
        print(f"{'OK' if ok else 'НЕ ГОТОВО'}: {label}")
    print("Это проверка настроек. Оплата, VPN, PostgreSQL и Redis по сети не проверялись.")
    print("Цены Stars из тестовой базы требуют отдельного согласования перед продажами.")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
