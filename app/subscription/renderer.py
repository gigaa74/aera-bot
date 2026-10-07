import base64
from urllib.parse import quote, urlencode

from app.core.exceptions import ProvisioningError


def render(uuid: str, name: str, config: dict) -> str:
    """Render explicitly configured public VLESS / TCP / REALITY parameters only."""
    if config.get("protocol") != "vless" or config.get("security") != "reality":
        raise ProvisioningError("Unsupported public connection configuration")
    required = {"host", "port", "public_key", "server_name", "short_id"}
    if not required <= config.keys():
        raise ProvisioningError("Incomplete public connection configuration")
    query = urlencode(
        {
            "encryption": "none",
            "type": "tcp",
            "security": "reality",
            "flow": config.get("flow", "xtls-rprx-vision"),
            "sni": config["server_name"],
            "fp": config.get("fingerprint", "chrome"),
            "pbk": config["public_key"],
            "sid": config["short_id"],
        }
    )
    host = config["host"]
    if ":" in host:
        host = f"[{host}]"
    link = f"vless://{uuid}@{host}:{int(config['port'])}?{query}#{quote(name)}"
    return base64.b64encode(link.encode()).decode() + "\n"
