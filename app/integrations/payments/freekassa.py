"""FreeKassa SCI: signed hosted checkout and server notifications, no card data."""

import hashlib
import hmac
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from app.core.exceptions import PaymentError

EVENT_IPS = {"168.119.157.136", "168.119.60.227", "178.154.197.79", "51.250.54.238"}
RUB_METHODS = {"4", "8", "12", "36", "42", "44"}


def digest(value: str) -> str:
    # MD5 is the protocol mandated by SCI, not a password storage algorithm.
    return hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()


class FreeKassaProvider:
    def __init__(self, merchant_id: str, secret1: str, secret2: str):
        if not merchant_id.isdigit() or not secret1 or not secret2 or secret1 == secret2:
            raise PaymentError("FreeKassa settings incomplete")
        self.merchant_id, self.secret1, self.secret2 = merchant_id, secret1, secret2

    def checkout_url(self, order_id: str, amount_minor: int, currency: str, method: str = "42") -> str:
        if currency != "RUB" or amount_minor <= 0 or method not in {"4", "42"}:
            raise PaymentError("FreeKassa requires a positive RUB price")
        amount = f"{Decimal(amount_minor) / 100:.2f}"
        signature = digest(f"{self.merchant_id}:{amount}:{self.secret1}:RUB:{order_id}")
        return "https://pay.fk.money/?" + urlencode(
            {
                "m": self.merchant_id,
                "oa": amount,
                "currency": "RUB",
                "o": order_id,
                "s": signature,
                "lang": "ru",
                "i": method,
            }
        )

    def verify_event(self, fields: dict[str, str]) -> tuple[str, str, int]:
        required = {"MERCHANT_ID", "AMOUNT", "MERCHANT_ORDER_ID", "SIGN", "intid", "CUR_ID"}
        if not required.issubset(fields) or fields["MERCHANT_ID"] != self.merchant_id:
            raise PaymentError("Invalid FreeKassa event")
        amount, order, transaction = fields["AMOUNT"], fields["MERCHANT_ORDER_ID"], fields["intid"]
        if (
            not re.fullmatch(r"\d+(?:\.\d{1,2})?", amount)
            or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", order)
            or not re.fullmatch(r"\d{1,32}", transaction)
            or fields["CUR_ID"] not in RUB_METHODS
        ):
            raise PaymentError("Invalid FreeKassa event")
        expected = digest(f"{self.merchant_id}:{amount}:{self.secret2}:{order}")
        if not hmac.compare_digest(expected, fields["SIGN"].lower()):
            raise PaymentError("Invalid FreeKassa signature")
        try:
            minor = int(Decimal(amount) * 100)
        except (ValueError, InvalidOperation):
            raise PaymentError("Invalid amount") from None
        if minor <= 0:
            raise PaymentError("Invalid amount")
        return order, transaction, minor
