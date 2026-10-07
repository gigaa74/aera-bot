from html import escape
from urllib.parse import parse_qsl

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.config import get_settings
from app.core.exceptions import PaymentError
from app.core.security import TokenVault
from app.db.session import sessions
from app.integrations.payments.freekassa import EVENT_IPS, FreeKassaProvider
from app.services.freekassa import accept_event

router = APIRouter()


@router.post("/api/v1/payments/freekassa/webhook", response_class=PlainTextResponse)
async def notification(request: Request):
    settings = get_settings()
    if not settings.freekassa_enabled or settings.card_provider != "freekassa":
        raise HTTPException(404)
    # Never trust caller-supplied X-Forwarded-For. Uvicorn must trust only our proxy.
    if not request.client or request.client.host not in EVENT_IPS:
        raise HTTPException(403, "Forbidden")
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        raise HTTPException(415)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 8192:
            raise HTTPException(413)
    try:
        pairs = parse_qsl(
            raw.decode("utf-8"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=40,
            errors="strict",
        )
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError("Duplicate field")
    except (ValueError, UnicodeError):
        raise HTTPException(400) from None
    provider = FreeKassaProvider(
        settings.freekassa_merchant_id, settings.freekassa_secret1, settings.freekassa_secret2
    )
    try:
        async with sessions.begin() as db:
            await accept_event(db, TokenVault(settings.app_secret), provider, fields, settings)
    except PaymentError:
        raise HTTPException(400, "Payment rejected") from None
    # ACK only after commit; do not await panel or Telegram networking here.
    return PlainTextResponse("YES")


def page(title: str, message: str) -> HTMLResponse:
    username = get_settings().bot_username.lstrip("@")
    if not username or not username.replace("_", "").isalnum():
        username = "AERAVPN_BOT"
    html = f"""<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AERA VPN</title>
<style>body{{background:#080b10;color:#f5f7fa;font:18px system-ui;display:grid;
place-items:center;min-height:95vh;margin:0}}main{{max-width:550px;padding:32px}}
h1{{color:#4ed8ff}}p{{line-height:1.6;color:#aeb9c9}}a{{display:inline-block;
background:#4ed8ff;color:#080b10;padding:14px 22px;border-radius:12px;text-decoration:none}}
</style><main><h1>{escape(title)}</h1><p>{escape(message)}</p>
<a href="https://t.me/{escape(username, quote=True)}">Открыть AERA в Telegram</a></main></html>"""
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        },
    )


@router.get("/payments/success", response_class=HTMLResponse)
async def success():
    return page(
        "Проверяем оплату",
        "Вернитесь в бот. После подтверждения платежа "
        "доступ появится в разделе «Моя подписка». Эта страница не подтверждает оплату.",
    )


@router.get("/payments/failure", response_class=HTMLResponse)
async def failure():
    return page(
        "Оплата не завершена",
        "Вернитесь в бот и проверьте статус заказа. "
        "Если деньги списались, не платите повторно: обратитесь в поддержку.",
    )


@router.get("/", response_class=HTMLResponse)
async def home():
    return page("AERA VPN", "Управление подпиской, тарифы и поддержка доступны в Telegram-боте.")
