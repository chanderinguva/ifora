"""Transport, authentication, errors and pagination for the IFora SDK. The endpoint methods are generated (see _generated.py)."""

from typing import Any, Dict, Iterator, List, Mapping, Optional, Union
from urllib.parse import quote

import httpx

SCIM_ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class IForaError(Exception):
    """An error reply. IFora returns a SCIM Error (RFC 7644 3.12) for every failure."""

    def __init__(self, status: int, detail: str, scim_type: Optional[str] = None, errors: Optional[List[Any]] = None, response: Optional[httpx.Response] = None):
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail
        self.scim_type = scim_type
        self.errors = errors or []   # per-field validation problems on a 422
        self.response = response


class Transport:
    """One HTTP session against an IFora deployment.

    * `token` is an API token (`idf_api_…`), sent as a bearer token. It works on /api/v1/admin/**.
    * Everything else uses a browser-style session: call `login()`, and the cookie and CSRF token are kept for you.
    """

    def __init__(self, base_url: str, token: Optional[str] = None, *, timeout: float = 30.0, verify: Union[bool, str] = True, transport: Optional[httpx.BaseTransport] = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.csrf_token: Optional[str] = None
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, verify=verify, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def login(self, email: str, password: str) -> Dict[str, Any]:
        """Start a session (cookie) and remember its CSRF token. Raises IForaError if the sign-in needs a second factor or is refused."""
        body = self.request("POST", "/api/v1/login", json={"email": email, "password": password})
        if isinstance(body, dict) and body.get("csrf_token"):
            self.csrf_token = body["csrf_token"]
        return body

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        json: Any = None,
        form: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        headers: Dict[str, str] = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.csrf_token and method.upper() not in SAFE_METHODS:
            headers["X-CSRF-Token"] = self.csrf_token
        params = {k: _q(v) for k, v in (query or {}).items() if v is not None}
        data = {k: v for k, v in (form or {}).items() if v is not None} or None
        r = self._http.request(method.upper(), path, params=params or None, json=json, data=data, headers=headers)
        if r.status_code >= 400:
            raise _error(r)
        return _body(r)

    # ---- pagination -------------------------------------------------------------------------------------------------

    @staticmethod
    def paginate(list_method, *, page_size: int = 100, **kwargs) -> Iterator[Dict[str, Any]]:
        """Yield every item of a SCIM list endpoint, page by page.

        >>> for user in Transport.paginate(client.users.list, filter='status eq "active"'): ...
        """
        start = 1
        while True:
            page = list_method(start_index=start, count=page_size, **kwargs)
            items = page.get("Resources", [])
            yield from items
            start += len(items)
            if not items or start > int(page.get("totalResults", 0)):
                return


def _q(v: Any) -> Any:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return [_q(x) for x in v]
    return v


def path_arg(value: Any) -> str:
    """A path parameter, safe for a URL path (no slashes or dots tricks)."""
    return quote(str(value), safe="")


def _body(r: httpx.Response) -> Any:
    if r.status_code == 204 or not r.content:
        return None
    ctype = r.headers.get("content-type", "")
    if "json" in ctype:
        return r.json()
    if ctype.startswith("text/"):
        return r.text
    return r.content


def _error(r: httpx.Response) -> IForaError:
    try:
        body = r.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and SCIM_ERROR in body.get("schemas", []):
        return IForaError(r.status_code, str(body.get("detail", "")), body.get("scimType"), body.get("errors"), r)
    if isinstance(body, dict) and "detail" in body:   # a non-SCIM reply (a proxy, an OAuth endpoint)
        return IForaError(r.status_code, str(body["detail"]), None, None, r)
    return IForaError(r.status_code, (r.text or r.reason_phrase)[:300], None, None, r)
