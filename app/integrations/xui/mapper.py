from app.integrations.xui.schemas import ClientSpec
from app.services.commerce import utc


def client_payload(spec: ClientSpec, existing: dict | None = None) -> dict:
    # Preserve version-specific fields when updating an existing client.
    return {
        **(existing or {}),
        "id": spec.uuid,
        "email": spec.email,
        "flow": (existing or {}).get("flow", "xtls-rprx-vision"),
        "totalGB": spec.traffic_limit_bytes,
        "expiryTime": int(utc(spec.expires_at).timestamp() * 1000),
        "enable": spec.enabled,
        "limitIp": (existing or {}).get("limitIp", 0),
    }
