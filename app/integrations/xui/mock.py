from app.integrations.xui.schemas import ClientSpec, Traffic


class MockXUIClient:
    """Test adapter. Mock configurations deliberately cannot connect to a real VPN."""

    def __init__(self) -> None:
        self.clients: dict[str, ClientSpec] = {}
        self.traffic: dict[str, Traffic] = {}
        self.available = True

    async def ensure_client(self, spec: ClientSpec) -> None:
        if not self.available:
            raise ConnectionError("Mock server unavailable")
        self.clients[spec.uuid] = spec

    async def delete_client(self, inbound_id: int, uuid: str) -> None:
        self.clients.pop(uuid, None)

    async def get_client_traffic(self, email: str) -> Traffic:
        return self.traffic.get(email, Traffic())

    async def get_server_status(self) -> bool:
        return self.available
