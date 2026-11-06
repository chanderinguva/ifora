"""Encryption of connection secrets and webhook secrets (separate Fernet key, ADR 008 T2)."""

from cryptography.fernet import Fernet, InvalidToken

from backend.app.config import settings


class RecipeKeyError(RuntimeError):
    """Secrets cannot be stored: key missing, shared with another feature, or malformed."""


def available() -> bool:
    try:
        _fernet()
        return True
    except RecipeKeyError:
        return False


def _fernet() -> Fernet:
    key = settings.RECIPE_ENCRYPTION_KEY
    if not key:
        raise RecipeKeyError("RECIPE_ENCRYPTION_KEY is not set")
    if key in (settings.MFA_ENCRYPTION_KEY, settings.OIDC_KEY_ENCRYPTION_KEY):
        raise RecipeKeyError("RECIPE_ENCRYPTION_KEY must differ from MFA_ENCRYPTION_KEY and OIDC_KEY_ENCRYPTION_KEY")
    try:
        return Fernet(key.encode())
    except ValueError as e:
        raise RecipeKeyError("RECIPE_ENCRYPTION_KEY is not a valid Fernet key") from e


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise RecipeKeyError("stored secret cannot be decrypted with the current key") from e
