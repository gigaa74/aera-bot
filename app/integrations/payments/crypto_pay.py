import hashlib
import hmac
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from app.core.exceptions import PaymentError


class CryptoPayProvider:
    """Crypto Bot Crypto Pay, not Telegram Wallet and not arbitrary personal-wallet transfers."""

    def __init__(
        self, token: str, testnet: bool = True, transport: httpx.AsyncBaseTransport | None = None
    ):
        if not token:
            raise PaymentError("Crypto Pay merchant credentials not configured")
        host = "https://testnet-pay.crypt.bot/api/" if testnet else "https://pay.crypt.bot/api/"
        self.http = httpx.AsyncClient(
            base_url=host, headers={"Crypto-Pay-API-Token": token}, timeout=20, transport=transport
        )
        self.key = hashlib.sha256(token.encode()).digest()

    async def request(self, method: str, payload: dict) -> object:
        try:
            response = await self.http.post(method, json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise PaymentError("Crypto Pay unavailable") from None
        if body.get("ok") is not True:
            raise PaymentError("Crypto Pay operation rejected")
        return body["result"]

    async def create_invoice(self, payment_id: str, asset: str, amount: str) -> dict:
        if asset not in {"USDT", "TON", "BTC", "ETH", "LTC", "BNB", "TRX", "USDC"}:
            raise PaymentError("Unsupported crypto asset")
        if Decimal(amount) <= 0:
            raise PaymentError("Invalid crypto amount")
        # Recover an ambiguous create response by looking up the stable payload first.
        recent = await self.request("getInvoices", {"count": 1000})
        existing = next((row for row in recent["items"] if row.get("payload") == payment_id), None)
        if existing:
            return existing
        return await self.request(
            "createInvoice",
            {
                "currency_type": "crypto",
                "asset": asset,
                "amount": amount,
                "payload": payment_id,
                "expires_in": 1800,
                "description": "AERA VPN subscription",
                "allow_comments": False,
            },
        )

    async def verify_payment(self, invoice_id: str) -> dict:
        body = await self.request("getInvoices", {"invoice_ids": invoice_id})
        matching = [row for row in body["items"] if str(row["invoice_id"]) == invoice_id]
        if len(matching) != 1:
            raise PaymentError("Crypto invoice not found")
        return matching[0]

    def verify_webhook(self, raw: bytes, signature: str) -> str:
        expected = hmac.new(self.key, raw, hashlib.sha256).hexdigest()
        if len(raw) > 16384 or not hmac.compare_digest(expected, signature):
            raise PaymentError("Invalid Crypto Pay signature")
        try:
            event = json.loads(raw)
            sent = datetime.fromisoformat(event["request_date"].replace("Z", "+00:00"))
            if (
                sent.tzinfo is None
                or abs((datetime.now(UTC) - sent).total_seconds()) > 300
                or event["update_type"] != "invoice_paid"
            ):
                raise ValueError("Stale or unsupported event")
            return str(event["payload"]["invoice_id"])
        except (KeyError, ValueError, TypeError):
            raise PaymentError("Invalid Crypto Pay event") from None

    async def close(self) -> None:
        await self.http.aclose()
