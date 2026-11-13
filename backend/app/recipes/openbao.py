"""Optional OpenBao Transit provider. No root token, plaintext fallback, or TLS bypass."""
import base64
import re
import ssl
import time
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit
import httpx
from backend.app.config import settings

_lock = Lock()
_cached = None


class VaultUnavailable(RuntimeError):
    pass


def configured():
    u = urlsplit(settings.RECIPE_OPENBAO_URL)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
        raise VaultUnavailable("OpenBao requires a fixed HTTPS origin")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", settings.RECIPE_OPENBAO_KEY):
        raise VaultUnavailable("Invalid OpenBao key name")
    if not settings.RECIPE_OPENBAO_ROLE_ID_FILE or not settings.RECIPE_OPENBAO_SECRET_ID_FILE:
        raise VaultUnavailable("OpenBao AppRole credential files are required")


def _file(path):
    try:
        value = Path(path).read_text().strip()
        if not value or len(value) > 8192:
            raise ValueError()
        return value
    except (OSError, ValueError):
        raise VaultUnavailable("OpenBao credential file is unavailable") from None


def _post(path, body, token=None):
    try:
        context = ssl.create_default_context(cafile=settings.RECIPE_OPENBAO_CA_FILE or None)
        with httpx.Client(verify=context, timeout=5, follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", settings.RECIPE_OPENBAO_URL.rstrip("/") + "/v1/" + path,
                               headers={"X-Vault-Token": token} if token else {}, json=body) as r:
                if r.status_code != 200:
                    raise VaultUnavailable("OpenBao refused the operation")
                data = b""
                for chunk in r.iter_bytes():
                    data += chunk
                    if len(data) > 262144:
                        raise VaultUnavailable("OpenBao response exceeded the limit")
                import json
                return json.loads(data)
    except (httpx.HTTPError, OSError, ValueError, KeyError):
        raise VaultUnavailable("OpenBao is unavailable") from None


def _token():
    global _cached
    with _lock:
        configured()
        role, secret = _file(settings.RECIPE_OPENBAO_ROLE_ID_FILE), _file(settings.RECIPE_OPENBAO_SECRET_ID_FILE)
        key = (settings.RECIPE_OPENBAO_URL, role, secret)
        if _cached and _cached[0] == key and _cached[2] > time.monotonic():
            return _cached[1]
        try:
            auth = _post("auth/approle/login", {"role_id": role, "secret_id": secret})["auth"]
            token, ttl = auth["client_token"], min(int(auth["lease_duration"]), 300)
            if not isinstance(token, str) or ttl < 1:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise VaultUnavailable("OpenBao authentication failed") from None
        _cached = (key, token, time.monotonic() + max(ttl - 15, 0))
        return token


def encrypt(plain):
    configured()
    try:
        token = _post("transit/encrypt/" + settings.RECIPE_OPENBAO_KEY,
                      {"plaintext": base64.b64encode(plain.encode()).decode()}, _token())["data"]["ciphertext"]
        if not isinstance(token, str) or not token.startswith("vault:v"):
            raise ValueError()
        return "openbao:" + token
    except (KeyError, TypeError, ValueError):
        raise VaultUnavailable("OpenBao encryption failed") from None


def decrypt(token):
    configured()
    try:
        value = _post("transit/decrypt/" + settings.RECIPE_OPENBAO_KEY,
                      {"ciphertext": token.removeprefix("openbao:")}, _token())["data"]["plaintext"]
        return base64.b64decode(value, validate=True).decode()
    except (KeyError, TypeError, ValueError):
        raise VaultUnavailable("OpenBao decryption failed") from None
