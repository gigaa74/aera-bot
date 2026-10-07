"""WATA settlement is verified using transactions, never payment-link status."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import quote

import httpx

from app.core.exceptions import PaymentError


class WATAProvider:
    def __init__(self, token, terminal_id, transport=None):
        if not token or not terminal_id:
            raise PaymentError("WATA merchant not configured")
        self.terminal_id = terminal_id
        self.http = httpx.AsyncClient(
            base_url="https://api.wata.pro/api/h2h/",
            headers={"Authorization": "Bearer " + token},
            timeout=20,
            transport=transport,
        )

    async def request(self, method, path, **kwargs):
        try:
            response = await self.http.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise PaymentError("WATA provider unavailable") from None

    async def create_payment(self, identity, amount, return_url):
        return await self.request(
            "POST",
            "links/",
            json={
                "orderId": identity,
                "amount": float(Decimal(amount) / 100),
                "currency": "RUB",
                "description": "AERA VPN subscription",
                "type": "OneTime",
                "isArbitraryAmountAllowed": False,
                "successRedirectUrl": return_url,
                "failRedirectUrl": return_url,
                "expirationDateTime": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
            },
        )

    def matches(self, body, identity, amount, link_id=None):
        try:
            return (
                body.get("orderId") == identity
                and Decimal(str(body.get("amount"))) * 100 == amount
                and body.get("currency") == "RUB"
                and body.get("terminalPublicId") == self.terminal_id
                and (link_id is None or body.get("paymentLinkId") == link_id)
            )
        except (ValueError, ArithmeticError):
            return False

    async def paid_transaction(self, identity, amount, link_id):
        # orderId remains usable after the temporary payment link expires.
        params = {
            "orderId": identity,
            "statuses": "Paid",
            "maxResultCount": 100,
            "sorting": "creationTime desc",
        }
        for _ in range(10):
            page = await self.request("GET", "v2/transactions/", params=params)
            for row in page.get("items", []):
                if row.get("kind") != "Payment" or row.get("status") != "Paid":
                    continue
                if not self.matches(row, identity, amount, link_id):
                    continue
                result = await self.request("GET", "transactions/" + quote(row["id"], safe=""))
                if (
                    result.get("status") == "Paid"
                    and result.get("kind") == "Payment"
                    and self.matches(result, identity, amount, link_id)
                ):
                    return result
            if not page.get("hasNextPage"):
                return None
            params.update(cursorId=page["nextCursorId"], cursorDate=page["nextCursorDate"])
        return None

    async def close(self):
        await self.http.aclose()
