"""Encryption of connection secrets and webhook secrets (separate Fernet key, ADR 008 T2)."""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from backend.app.config import settings


class RecipeKeyError(RuntimeError):
    """Secrets cannot be stored: key missing, shared with another feature, or malformed."""


def available() -> bool:
    try:
        if settings.RECIPE_SECRET_PROVIDER == "openbao":
            from backend.app.recipes.openbao import configured, VaultUnavailable
            try:
                configured()
                return True
            except VaultUnavailable:
                return False
        _fernet()
        return True
    except RecipeKeyError:
        return False


def _fernet() -> Fernet:
    key = settings.RECIPE_ENCRYPTION_KEY
    if not key:
        raise RecipeKeyError("RECIPE_ENCRYPTION_KEY is not set")
    if key in (settings.MFA_ENCRYPTION_KEY, settings.OIDC_KEY_ENCRYPTION_KEY, settings.SWA_ENCRYPTION_KEY):
        raise RecipeKeyError("RECIPE_ENCRYPTION_KEY must differ from MFA_ENCRYPTION_KEY and OIDC_KEY_ENCRYPTION_KEY")
    try:
        return Fernet(key.encode())
    except ValueError as e:
        raise RecipeKeyError("RECIPE_ENCRYPTION_KEY is not a valid Fernet key") from e


def encrypt(plain: str) -> str:
    if settings.RECIPE_SECRET_PROVIDER == "openbao":
        from backend.app.recipes import openbao
        try:
            return openbao.encrypt(plain)
        except openbao.VaultUnavailable:
            raise RecipeKeyError("Secret storage is unavailable; try again later") from None
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    if token.startswith("openbao:"):
        from backend.app.recipes import openbao
        try:
            return openbao.decrypt(token)
        except openbao.VaultUnavailable:
            raise RecipeKeyError("Secret storage is unavailable; try again later") from None
    try:
        keys = [_fernet()]
        if settings.RECIPE_ENCRYPTION_KEY_PREVIOUS:
            keys.append(Fernet(settings.RECIPE_ENCRYPTION_KEY_PREVIOUS.encode()))
        return MultiFernet(keys).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError, TypeError) as e:
        raise RecipeKeyError("stored secret cannot be decrypted with the current key") from e
