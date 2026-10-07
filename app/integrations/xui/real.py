import asyncio
import json
from urllib.parse import quote

import httpx

from app.integrations.xui.exceptions import XUIAuthenticationError, XUIError, XUIUnavailableError
from app.integrations.xui.mapper import client_payload
from app.integrations.xui.schemas import ClientSpec, Traffic


class XUI285Client:
    """Routes and cookie login verified against upstream tag v2.8.5.

    Only VLESS clients are supported in this adapter. No automatic fallback to unknown API versions.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        transport: httpx.AsyncBaseTransport | None = None,
        allow_writes: bool = False,
    ):
        self.http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            timeout=15,
            transport=transport,
            follow_redirects=False,
        )
        self.username, self.password = username, password
        self.authenticated = False
        self.allow_writes = allow_writes
        self.lock = asyncio.Lock()

    async def authenticate(self) -> None:
        async with self.lock:
            try:
                response = await self.http.post(
                    "login", data={"username": self.username, "password": self.password}
                )
                response.raise_for_status()
                if response.json().get("success") is not True:
                    raise XUIAuthenticationError("Panel authentication rejected")
            except (httpx.HTTPError, ValueError):
                raise XUIAuthenticationError("Panel authentication unavailable") from None
            self.authenticated = True

    async def request(self, method: str, route: str, payload: dict | None = None) -> object:
        if method != "GET" and not self.allow_writes:
            raise XUIError("Panel mutations disabled; enable explicitly for test inbound only")
        if not self.authenticated:
            await self.authenticate()
        try:
            response = await self.http.request(method, route, json=payload)
            if response.status_code in {301, 302, 303, 307, 401, 403}:
                self.authenticated = False
                await self.authenticate()
                response = await self.http.request(method, route, json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            # Do not propagate httpx request URLs, panel messages or credential-bearing objects.
            raise XUIUnavailableError("Panel request failed") from None
        if body.get("success") is not True:
            raise XUIError("Panel operation rejected")
        return body.get("obj")

    async def get_inbounds(self) -> list[dict]:
        return await self.request("GET", "panel/api/inbounds/list")

    async def get_inbound(self, inbound_id: int) -> dict:
        return await self.request("GET", f"panel/api/inbounds/get/{inbound_id}")

    async def ensure_client(self, spec: ClientSpec) -> None:
        inbound = await self.get_inbound(spec.inbound_id)
        if inbound.get("protocol") != "vless":
            raise XUIError("This adapter supports VLESS only")
        clients = json.loads(inbound["settings"]).get("clients", [])
        existing = next((c for c in clients if c.get("id") == spec.uuid), None)
        if any(c.get("email") == spec.email and c.get("id") != spec.uuid for c in clients):
            raise XUIError("Client identity conflict")
        desired = client_payload(spec, existing)
        if existing and all(existing.get(k) == v for k, v in desired.items()):
            return
        payload = {"id": spec.inbound_id, "settings": json.dumps({"clients": [desired]})}
        route = (
            f"panel/api/inbounds/updateClient/{quote(spec.uuid, safe='')}"
            if existing
            else "panel/api/inbounds/addClient"
        )
        await self.request("POST", route, payload)

    async def add_client(self, spec: ClientSpec) -> None:
        await self.ensure_client(spec)

    async def update_client(self, spec: ClientSpec) -> None:
        await self.ensure_client(spec)

    async def delete_client(self, inbound_id: int, uuid: str) -> None:
        await self.request(
            "POST", f"panel/api/inbounds/{inbound_id}/delClient/" + quote(uuid, safe="")
        )

    async def get_client_traffic(self, email: str) -> Traffic:
        body = await self.request(
            "GET", "panel/api/inbounds/getClientTraffics/" + quote(email, safe="")
        )
        if not isinstance(body, dict):
            raise XUIError("Traffic response is unavailable")
        return Traffic(int(body.get("up", 0)), int(body.get("down", 0)))

    async def reset_client_traffic(self, inbound_id: int, email: str) -> None:
        await self.request(
            "POST", f"panel/api/inbounds/{inbound_id}/resetClientTraffic/" + quote(email, safe="")
        )

    async def get_server_status(self) -> bool:
        await self.request("GET", "panel/api/server/status")
        return True

    async def close(self) -> None:
        await self.http.aclose()
