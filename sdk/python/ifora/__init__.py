"""IFora Python SDK: one method for every API endpoint.

    from ifora import Client

    with Client("https://api.ifora.app", token="idf_api_…") as ifora:
        page = ifora.users.list(count=10, filter='status eq "active"')
        user = ifora.users.get(7)
        for g in ifora.paginate(ifora.groups.list):
            print(g["name"])

API tokens work on /api/v1/admin/**. For everything else (your own profile, MFA, sign-in) call `ifora.login(email, password)` first.
Failures raise `IForaError` (a SCIM Error: `.status`, `.detail`, `.scim_type`, `.errors`).
"""

from typing import Optional, Union

import httpx

from ._client import IForaError, Transport
from ._generated import OPERATIONS, Namespaces

__all__ = ["Client", "IForaError", "OPERATIONS"]
__version__ = "0.1.0"


class Client(Transport, Namespaces):
    """A connection to one IFora deployment. Sections of the API are attributes: `client.users`, `client.groups`, `client.applications`…"""

    def __init__(self, base_url: str, token: Optional[str] = None, *, timeout: float = 30.0, verify: Union[bool, str] = True, transport: Optional[httpx.BaseTransport] = None):
        Transport.__init__(self, base_url, token, timeout=timeout, verify=verify, transport=transport)
        self._attach()
