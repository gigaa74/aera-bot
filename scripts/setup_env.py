import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    print("Existing .env preserved")
else:
    content = (root / ".env.example").read_text(encoding="utf-8")
    content = content.replace(
        "APP_SECRET=development-only-change-before-production",
        "APP_SECRET=" + secrets.token_urlsafe(48),
    )
    content = content.replace(
        "ADMIN_API_TOKEN=\n", "ADMIN_API_TOKEN=" + secrets.token_urlsafe(48) + "\n"
    )
    content = content.replace(
        "MOCK_PAYMENT_SECRET=local-mock-only", "MOCK_PAYMENT_SECRET=" + secrets.token_urlsafe(32)
    )
    content = content.replace(
        "CRYPTO_MOCK_SECRET=local-crypto-test-only",
        "CRYPTO_MOCK_SECRET=" + secrets.token_urlsafe(32),
    )
    password = secrets.token_urlsafe(24)
    content = content.replace("change-this-local-password", password)
    target.write_text(content, encoding="utf-8")
    print("Created private development .env; no secrets printed")
