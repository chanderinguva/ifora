"""Authentication facts recorded on a session: how, and when, the user proved who they are.

These feed OIDC ID tokens (`amr`, `acr`, `auth_time`; ADR 005) and are never client-supplied.
`amr` values follow RFC 8176 where a registered value exists.
"""

from typing import List

# Internal login method -> RFC 8176 `amr` values
_AMR = {
    "password": ["pwd"],
    # discoverable credential with user verification: hardware-bound key + user presence + verification
    "passkey": ["hwk", "user", "mfa"],
    "password+mfa_totp": ["pwd", "otp", "mfa"],
    "password+mfa_recovery": ["pwd", "otp", "mfa"],
}

ACR_SINGLE_FACTOR = "urn:identityforge:acr:1"
ACR_MULTI_FACTOR = "urn:identityforge:acr:2"


def amr_for(method: str) -> List[str]:
    """Fail closed: an unknown method is recorded as password-only rather than inheriting MFA claims."""
    return list(_AMR.get(method, ["pwd"]))


def acr_for(amr: List[str] | None) -> str:
    """Level 2 only when the session was established with multiple factors (incl. a verified passkey)."""
    return ACR_MULTI_FACTOR if amr and "mfa" in amr else ACR_SINGLE_FACTOR
