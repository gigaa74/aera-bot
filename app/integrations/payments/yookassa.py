from decimal import Decimal
from ipaddress import ip_address, ip_network

import httpx

from app.core.exceptions import PaymentError

NETWORKS = [
    ip_network(value)
    for value in [
        "185.71.76.0/27",
        "185.71.77.0/27",
        "77.75.153.0/25",
        "77.75.156.11/32",
        "77.75.156.35/32",
        "77.75.154.128/25",
        "2a02:5180::/32",
    ]
]


def trusted_event_ip(peer: str) -> bool:
    try:
        address = ip_address(peer)
        return any(address in network for network in NETWORKS)
    except ValueError:
        return False


class YooKassaProvider:
    """Candidate adapter; merchant activation and payment methods require owner's account."""

    def __init__(
        self, shop_id: str, secret: str, transport: httpx.AsyncBaseTransport | None = None
    ):
        if not shop_id or not secret:
            raise PaymentError("YooKassa merchant credentials not configured")
        self.http = httpx.AsyncClient(
            base_url="https://api.yookassa.ru/v3/",
            auth=(shop_id, secret),
            timeout=20,
            transport=transport,
        )

    async def request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = await self.http.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise PaymentError("Card payment provider unavailable") from None

    async def create_payment(
        self,
        payment_id: str,
        amount_minor: int,
        currency: str,
        return_url: str,
        *,
        sbp: bool = False,
    ) -> dict:
        if currency != "RUB":
            raise PaymentError("Card adapter requires RUB")
        payload = {
            "amount": {"value": str(Decimal(amount_minor) / 100), "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": return_url},
            "description": "AERA VPN subscription",
            "metadata": {"payment_id": payment_id},
        }
        if sbp:
            payload["payment_method_data"] = {"type": "sbp"}
        # Hosted checkout exposes payment methods activated for this merchant, including card/SBP.
        return await self.request(
            "POST", "payments", json=payload, headers={"Idempotence-Key": payment_id}
        )

    async def verify_payment(self, provider_payment_id: str) -> dict:
        return await self.request("GET", "payments/" + provider_payment_id)

    async def refund(
        self, provider_payment_id: str, amount_minor: int, currency: str, refund_id: str
    ) -> dict:
        return await self.request(
            "POST",
            "refunds",
            headers={"Idempotence-Key": refund_id},
            json={
                "payment_id": provider_payment_id,
                "amount": {"value": str(Decimal(amount_minor) / 100), "currency": currency},
            },
        )

    async def close(self) -> None:
        await self.http.aclose()
