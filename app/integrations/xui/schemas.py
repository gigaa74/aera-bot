from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ClientSpec:
    uuid: str
    email: str
    inbound_id: int
    expires_at: datetime
    traffic_limit_bytes: int
    enabled: bool
    server_id: str = ""


@dataclass(frozen=True)
class Traffic:
    uploaded: int = 0
    downloaded: int = 0
