import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


@lru_cache(maxsize=4)
def _fernet(key: str, secret: str) -> Fernet:
    if key:
        return Fernet(key.encode())
    derived = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(derived)


def get_fernet() -> Fernet:
    return _fernet(settings.FERNET_KEY, settings.SECRET_KEY)


def encrypt(value: str) -> str:
    if not value:
        return ""
    return get_fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Cannot decrypt value: FERNET_KEY mismatch") from exc


def mask(value: str, visible: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "*" * len(value)
    return value[:visible] + "*" * 8 + value[-visible:]
