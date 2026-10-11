from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class EncryptionUnavailableError(Exception):
    pass


def _fernet() -> Fernet:
    key = get_settings().integration_encryption_key
    if key is None:
        raise EncryptionUnavailableError(
            "INTEGRATION_ENCRYPTION_KEY is not set; provider credentials cannot be stored."
        )
    try:
        return Fernet(key.get_secret_value().encode())
    except (ValueError, TypeError) as exc:
        raise EncryptionUnavailableError("INTEGRATION_ENCRYPTION_KEY is not a valid Fernet key") from exc


def encryption_available() -> bool:
    try:
        _fernet()
    except EncryptionUnavailableError:
        return False
    return True


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionUnavailableError(
            "stored credential cannot be decrypted with the current key"
        ) from exc
