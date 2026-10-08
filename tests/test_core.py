import base64
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import InvalidToken
from pydantic import ValidationError

from app.config import Settings
from app.core.exceptions import ProvisioningError
from app.core.security import TokenVault, token_hash
from app.subscription.renderer import render

PRODUCTION = dict(
    app_env="production",
    app_secret="x" * 40,
    xui_mock_mode=False,
    payment_provider="telegram_stars",
    public_base_url="https://aera.example",
    telegram_webhook_secret="w" * 32,
)


def make(**values):
    return Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:", **values)


# ---------- security ----------


def test_token_vault_round_trip_and_hash():
    vault = TokenVault("secret")
    token, digest, encrypted = vault.create()
    assert digest == token_hash(token) and len(digest) == 64
    assert token not in encrypted
    assert vault.reveal(encrypted) == token
    with pytest.raises(InvalidToken):
        TokenVault("other").reveal(encrypted)


# ---------- config ----------


def test_admin_ids_parsing():
    assert make(admin_telegram_ids=" 1, 2,,3 ").admin_ids == {1, 2, 3}
    assert make().admin_ids == set()


def test_valid_production_settings():
    assert make(**PRODUCTION).app_env == "production"


@pytest.mark.parametrize(
    "overrides",
    [
        {"telegram_http_client": "requests"},
        {"payment_provider": "paypal"},
        {"card_provider": "stripe"},
        {"crypto_provider": "binance"},
        {"freekassa_enabled": True, "card_provider": "yookassa"},
        {
            "freekassa_enabled": True,
            "card_provider": "freekassa",
            "freekassa_merchant_id": "1",
            "freekassa_secret1": "same",
            "freekassa_secret2": "same",
        },
        {"xui_mock_mode": False, "xui_version": "1.0"},
    ],
)
def test_rejects_unsupported_settings(overrides):
    with pytest.raises(ValidationError):
        make(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"crypto_provider": "crypto_pay", "crypto_pay_testnet": True},
        {"crypto_mock_enabled": True},
        {"app_secret": "short"},
        {"app_secret": "development-" + "x" * 40},
        {"xui_mock_mode": True},
        {"payment_provider": "mock"},
        {"public_base_url": "http://aera.example"},
        {"telegram_webhook_secret": "short"},
    ],
)
def test_production_guard(overrides):
    with pytest.raises(ValidationError):
        make(**{**PRODUCTION, **overrides})


def test_valid_freekassa_settings():
    settings = make(
        freekassa_enabled=True,
        card_provider="freekassa",
        freekassa_merchant_id="123",
        freekassa_secret1="a",
        freekassa_secret2="b",
    )
    assert settings.freekassa_enabled


# ---------- subscription renderer ----------

CONFIG = {
    "protocol": "vless",
    "security": "reality",
    "host": "vpn.example",
    "port": "443",
    "public_key": "pbk",
    "server_name": "sni.example",
    "short_id": "sid",
}


def decode(rendered):
    assert rendered.endswith("\n")
    return base64.b64decode(rendered).decode()


def test_render_vless_reality_link():
    link = decode(render("uuid-1", "AERA NL", CONFIG))
    parts = urlsplit(link)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert parts.scheme == "vless" and parts.netloc == "uuid-1@vpn.example:443"
    assert parts.fragment == "AERA%20NL"
    assert query == {
        "encryption": "none",
        "type": "tcp",
        "security": "reality",
        "flow": "xtls-rprx-vision",
        "sni": "sni.example",
        "fp": "chrome",
        "pbk": "pbk",
        "sid": "sid",
    }


def test_render_brackets_ipv6_and_honours_overrides():
    link = decode(render("u", "n", {**CONFIG, "host": "2001:db8::1", "fingerprint": "firefox"}))
    assert "@[2001:db8::1]:443?" in link and "fp=firefox" in link


@pytest.mark.parametrize(
    "config",
    [
        {**CONFIG, "protocol": "vmess"},
        {**CONFIG, "security": "tls"},
        {k: v for k, v in CONFIG.items() if k != "public_key"},
    ],
)
def test_render_rejects_unsupported_configs(config):
    with pytest.raises(ProvisioningError):
        render("u", "n", config)
