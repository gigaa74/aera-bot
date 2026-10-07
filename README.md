<div align="center">

# AERA · Telegram Bot

**Управление подписками и подключением в Telegram**

[Бот](https://t.me/AERAVPN_BOT) · [Сайт](https://aera-reserve.duckdns.org) · [Исходники сайта](https://github.com/gigaa74/aera-website)

![Python](https://img.shields.io/badge/Python-3.12%2B-40d5f7) ![Framework](https://img.shields.io/badge/Bot-aiogram_3-40d5f7) ![API](https://img.shields.io/badge/API-FastAPI-40d5f7)

</div>

## Возможности

- Тарифы, подписки, история оплаченных покупок и выдача ссылки подключения.
- Telegram Stars и интеграции платёжных провайдеров.
- Администрирование, пробный доступ, инструкции и реферальные сценарии.
- Общий backend для бота и личного кабинета сайта.
- Тёмный интерфейс и голубые фирменные изображения AERA.

## Быстрый старт для разработки

Требуется Python 3.12+. Команды выполняются из корня репозитория.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python scripts/setup_env.py
python -m scripts.local_mock
```

Локальный API: http://127.0.0.1:8000/docs. Этот режим использует SQLite, тестовый Redis и имитацию платёжных интеграций. Он не подтверждает реальные платежи.

Для проверки Telegram добавьте токен отдельного тестового бота в `.env`, затем в другом терминале с активированным окружением:

```powershell
python -m scripts.local_bot
```

## Структура

| Каталог | Назначение |
| --- | --- |
| `app/bot` | Telegram-интерфейс и обработчики |
| `app/api` | HTTP API и уведомления оплаты |
| `app/services` | Бизнес-логика |
| `app/workers` | Фоновые задачи |
| `app/assets` | Изображения и логотипы |
| `alembic` | Миграции базы |
| `scripts` | Запуск и обслуживание |

## Подключение сайта и production

Сайт находится в [отдельном репозитории](https://github.com/gigaa74/aera-website). Для подключённого кабинета используются общие модели, база и согласованная конфигурация.

Основные процессы: `uvicorn app.main:app`, `python -m app.bot.runtime`, `python -m app.workers.run`. Перед production необходимы PostgreSQL, Redis, HTTPS, миграции и реальные настройки выбранного провайдера. Production-проверки конфигурации находятся в `app/config.py`. Checkout сайта обращается к API бота на локальном порту 8000 с общим `AERA_CHECKOUT_BRIDGE_KEY`.

Публичная копия исходников выгружена 7 октября 2026 года из работающего проекта. Рабочие секреты, базы, журналы, настройки сервера и сторонние установщики исключены. Наличие адаптера в коде не означает, что соответствующий способ оплаты подключён к конкретному магазину.

## Безопасность

См. [SECURITY.md](SECURITY.md). Не используйте токен действующего бота для параллельного локального polling.
