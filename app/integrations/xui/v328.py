import json
from urllib.parse import quote
from uuid import UUID

import httpx

from app.integrations.xui.exceptions import XUIAuthenticationError, XUIError, XUIUnavailableError
from app.integrations.xui.mapper import client_payload
from app.integrations.xui.real import XUI285Client
from app.integrations.xui.schemas import ClientSpec, Traffic


class XUI328Client(XUI285Client):
    """Bearer API for upstream v3.2.8, restricted to one configured local inbound.

    No inbound edits, restarts, bulk operations, client deletion or cookie-login fallback.
    Existing AERA identities attached to multiple inbounds are rejected before mutations.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        inbound_id: int,
        transport: httpx.AsyncBaseTransport | None = None,
        allow_writes: bool = False,
    ):
        if not token or inbound_id <= 0:
            raise XUIError("An API token and positive inbound ID are required")
        super().__init__(base_url, "", "", transport, allow_writes)
        self.http.headers["Authorization"] = f"Bearer {token}"
        self.http.headers["X-Requested-With"] = "XMLHttpRequest"
        self.inbound_id = inbound_id

    async def authenticate(self) -> None:
        await self.get_inbound(self.inbound_id)

    async def request(self, method: str, route: str, payload: dict | None = None) -> object:
        if method != "GET":
            if not self.allow_writes:
                raise XUIError("Panel mutations disabled")
            if not (
                method == "POST"
                and (
                    route == "panel/api/clients/add"
                    or route.startswith("panel/api/clients/update/")
                )
            ):
                raise XUIError("Unsupported panel mutation")
        try:
            response = await self.http.request(method, route, json=payload)
            if response.status_code in {301, 302, 303, 307, 308, 401, 403, 404}:
                raise XUIAuthenticationError("Panel token, path or API access rejected")
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise XUIUnavailableError("Panel request failed") from None
        if not isinstance(body, dict) or body.get("success") is not True:
            raise XUIError("Panel operation rejected")
        return body.get("obj")

    @staticmethod
    def identity(uuid: str, email: str) -> None:
        try:
            if str(UUID(uuid)) != uuid or email != f"aera-{uuid}":
                raise ValueError
        except ValueError:
            raise XUIError("Only AERA client identities are supported") from None

    async def get_inbound(self, inbound_id: int) -> dict:
        if inbound_id != self.inbound_id:
            raise XUIError("Inbound outside configured scope")
        body = await super().get_inbound(inbound_id)
        if not isinstance(body, dict) or body.get("id") != inbound_id:
            raise XUIError("Inbound identity mismatch")
        return body

    async def ensure_client(self, spec: ClientSpec) -> None:
        if not self.allow_writes:
            raise XUIError("Panel mutations disabled")
        self.identity(spec.uuid, spec.email)
        inbound = await self.get_inbound(spec.inbound_id)
        if inbound.get("protocol") != "vless" or inbound.get("nodeId") not in {None, 0}:
            raise XUIError("Only a local VLESS inbound is supported")
        settings = inbound.get("settings")
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except ValueError:
                raise XUIError("Invalid inbound settings") from None
        if not isinstance(settings, dict) or not isinstance(settings.get("clients"), list):
            raise XUIError("Invalid inbound client list")
        clients = settings["clients"]
        matches = [c for c in clients if c.get("id") == spec.uuid or c.get("email") == spec.email]
        existing = matches[0] if len(matches) == 1 else None
        if matches and (
            len(matches) != 1
            or existing.get("id") != spec.uuid
            or existing.get("email") != spec.email
        ):
            raise XUIError("Client identity conflict")
        if existing:
            record = await self.request(
                "GET", "panel/api/clients/get/" + quote(spec.email, safe="")
            )
            if not isinstance(record, dict) or record.get("inboundIds") != [self.inbound_id]:
                raise XUIError("Shared client identity cannot be mutated")
            global_client = record.get("client", {})
            if global_client.get("uuid") != spec.uuid or global_client.get("email") != spec.email:
                raise XUIError("Global client identity conflict")
            desired = client_payload(spec, existing)
            if all(existing.get(k) == v for k, v in desired.items()):
                return
            await self.request(
                "POST",
                "panel/api/clients/update/"
                + quote(spec.email, safe="")
                + f"?inboundIds={self.inbound_id}",
                desired,
            )
        elif spec.enabled:
            desired = {**client_payload(spec), "subId": spec.uuid}
            await self.request(
                "POST",
                "panel/api/clients/add",
                {"client": desired, "inboundIds": [self.inbound_id]},
            )
        # v3.2.8 Create forces enable=true. Never create a disabled identity through that route.

    async def get_client_traffic(self, email: str) -> Traffic:
        body = await self.request("GET", "panel/api/clients/traffic/" + quote(email, safe=""))
        if not isinstance(body, dict):
            raise XUIError("Traffic response is unavailable")
        return Traffic(int(body.get("up", 0)), int(body.get("down", 0)))

    async def delete_client(self, inbound_id: int, uuid: str) -> None:
        raise XUIError("Client deletion is disabled; disable the owned client instead")

    async def reset_client_traffic(self, inbound_id: int, email: str) -> None:
        raise XUIError("Traffic reset requires a separately verified policy")
