import base64
import hashlib
import secrets

from cryptography.fernet import Fernet


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenVault:
    def __init__(self, secret: str):
        self.cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))

    def create(self) -> tuple[str, str, str]:
        token = secrets.token_urlsafe(32)
        return token, token_hash(token), self.cipher.encrypt(token.encode()).decode()

    def reveal(self, encrypted: str) -> str:
        return self.cipher.decrypt(encrypted.encode()).decode()
