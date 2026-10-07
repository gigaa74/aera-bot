"""Check the isolated local API without shell proxies or external network calls."""

import httpx


def main() -> int:
    try:
        response = httpx.get("http://127.0.0.1:8000/ready", timeout=1, trust_env=False)
        return 0 if response.status_code == 200 else 1
    except httpx.HTTPError:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
