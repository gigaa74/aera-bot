import json
from urllib.parse import urlsplit

from sqlalchemy import select

from app.config import Settings
from app.core.exceptions import ProvisioningError
from app.db.models import Server, VPNClient
from app.integrations.xui.mock import MockXUIClient
from app.integrations.xui.real import XUI285Client
from app.integrations.xui.schemas import ClientSpec, Traffic
from app.integrations.xui.v328 import XUI328Client


class RoutedXUIClient:
    def __init__(self, sessions, settings: Settings):
        if settings.xui_version not in {"2.8.5", "3.2.8"}:
            raise ValueError("Unsupported XUI version")
        self.version = settings.xui_version
        self.sessions = sessions
        self.allow_writes = settings.xui_allow_writes
        self.protected_hosts = {
            host.strip().lower().rstrip(".")
            for host in settings.xui_protected_hosts.split(",")
            if host.strip()
        }
        self.credentials = json.loads(settings.xui_credentials_json)
        self.adapters: dict[str, XUI285Client] = {}

    async def for_server(self, server_id: str) -> XUI285Client:
        async with self.sessions() as db:
            server = await db.get(Server, server_id)
            if not server:
                raise ProvisioningError("Unknown server")
            host = (urlsplit(server.xui_base_url).hostname or "").lower().rstrip(".")
            if self.allow_writes and host in self.protected_hosts:
                raise ProvisioningError("Writes to a protected panel are forbidden")
            credentials = self.credentials.get(server.code)
            if not credentials or not server.xui_base_url.startswith("https://"):
                raise ProvisioningError("Server credentials or HTTPS missing")
            if server.id not in self.adapters:
                if self.version == "3.2.8":
                    self.adapters[server.id] = XUI328Client(
                        server.xui_base_url,
                        credentials.get("api_token", ""),
                        server.inbound_id,
                        allow_writes=self.allow_writes,
                    )
                else:
                    self.adapters[server.id] = XUI285Client(
                        server.xui_base_url,
                        credentials["username"],
                        credentials["password"],
                        allow_writes=self.allow_writes,
                    )
            return self.adapters[server.id]

    async def ensure_client(self, spec: ClientSpec) -> None:
        await (await self.for_server(spec.server_id)).ensure_client(spec)

    async def get_client_traffic(self, email: str) -> Traffic:
        async with self.sessions() as db:
            client = await db.scalar(select(VPNClient).where(VPNClient.email == email))
        return await (await self.for_server(client.server_id)).get_client_traffic(email)

    async def get_server_status(self) -> bool:
        async with self.sessions() as db:
            servers = list(await db.scalars(select(Server).where(Server.is_active.is_(True))))
        for server in servers:
            await (await self.for_server(server.id)).get_server_status()
        return bool(servers)

    async def close(self) -> None:
        for adapter in self.adapters.values():
            await adapter.close()


def create_adapter(sessions, settings: Settings):
    return MockXUIClient() if settings.xui_mock_mode else RoutedXUIClient(sessions, settings)
