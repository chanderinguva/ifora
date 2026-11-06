"""SSRF-safe outbound HTTP for the `http_request` step (ADR 008 T1).

Order of operations: validate URL -> resolve host ONCE -> require every address to be globally routable ->
connect to the validated IP itself (Host header and TLS SNI keep the original name) -> never follow redirects ->
stream the body under a byte cap and a deadline. Relaxing the policy is only possible by passing an
``EgressPolicy`` in code (tests); no setting turns the private-address block off.
"""

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import urlsplit

import httpx

from backend.app.config import settings

DEFAULT_PORTS = frozenset({80, 443, 8080, 8443})
_FORBIDDEN_HEADERS = {"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer", "expect"}
_EXTRA_BLOCKED = [ipaddress.ip_network(n) for n in ("64:ff9b::/96", "2002::/16", "2001::/32", "100.64.0.0/10")]
MAX_BODY = 65536


class EgressBlocked(Exception):
    """The destination or request is not allowed. Never retried."""


class HttpFailure(Exception):
    """Network-level failure or timeout. Retryable."""


class ResponseTooLarge(Exception):
    """Response exceeded the byte cap. Not retried."""


@dataclass
class EgressPolicy:
    allow_private: bool = False
    allowed_ports: Optional[FrozenSet[int]] = DEFAULT_PORTS  # None = any port
    allowed_hosts: FrozenSet[str] = field(default_factory=frozenset)  # empty = any public host

    @classmethod
    def from_settings(cls) -> "EgressPolicy":
        hosts = frozenset(h.strip().lower() for h in settings.RECIPES_HTTP_ALLOWED_HOSTS.split(",") if h.strip())
        return cls(allowed_hosts=hosts)


@dataclass
class HttpResult:
    status: int
    content_type: str
    body: bytes
    headers: Dict[str, str]


def ip_allowed(ip: str, policy: EgressPolicy) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if policy.allow_private:
        return True
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if not addr.is_global or addr.is_multicast:
        return False
    return not any(addr in n for n in _EXTRA_BLOCKED if n.version == addr.version)


def default_resolver(host: str, port: int) -> List[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise HttpFailure("could not resolve host") from e
    return list(dict.fromkeys(i[4][0] for i in infos))


def validate_url(url: str, policy: EgressPolicy) -> Tuple[str, str, int, str]:
    """Return (scheme, host, port, path_and_query) or raise EgressBlocked. No network access."""
    if not isinstance(url, str) or len(url) > 2000 or any(c in url for c in "\r\n\t "):
        raise EgressBlocked("invalid URL")
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError:
        raise EgressBlocked("invalid URL")
    if p.scheme not in ("http", "https"):
        raise EgressBlocked("only http and https URLs are allowed")
    if p.username is not None or p.password is not None or "@" in (p.netloc or ""):
        raise EgressBlocked("credentials in URLs are not allowed")
    host = (p.hostname or "").lower().rstrip(".")
    if not host:
        raise EgressBlocked("URL has no host")
    port = port or (443 if p.scheme == "https" else 80)
    if policy.allowed_ports is not None and port not in policy.allowed_ports:
        raise EgressBlocked(f"port {port} is not allowed")
    if policy.allowed_hosts and host not in policy.allowed_hosts:
        raise EgressBlocked("host is not in the allowed host list")
    path = p.path or "/"
    if p.query:
        path += "?" + p.query
    return p.scheme, host, port, path


def resolve_safe(host: str, port: int, policy: EgressPolicy, resolver: Callable[[str, int], List[str]]) -> List[str]:
    try:
        ipaddress.ip_address(host)
        ips = [host]
    except ValueError:
        ips = resolver(host, port)
    if not ips:
        raise HttpFailure("could not resolve host")
    bad = [i for i in ips if not ip_allowed(i, policy)]
    if bad:  # any private answer poisons the whole set (no "pick the public one" games)
        raise EgressBlocked("destination resolves to a non-public address")
    return ips


def clean_headers(headers: Optional[Dict[str, str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in (headers or {}).items():
        k, v = str(k).strip(), str(v)
        if not k or not all(c.isalnum() or c in "-_" for c in k):
            raise EgressBlocked("invalid header name")
        if k.lower() in _FORBIDDEN_HEADERS or k.lower().startswith("proxy-"):
            raise EgressBlocked(f"header '{k}' cannot be set")
        if "\r" in v or "\n" in v or len(v) > 2000:
            raise EgressBlocked("invalid header value")
        out[k] = v
    return out


def safe_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[bytes] = None,
    *,
    policy: Optional[EgressPolicy] = None,
    resolver: Optional[Callable[[str, int], List[str]]] = None,
    transport: Optional[httpx.BaseTransport] = None,
    timeout: Optional[float] = None,
    max_bytes: Optional[int] = None,
) -> HttpResult:
    policy = policy or EgressPolicy.from_settings()
    resolver = resolver or default_resolver
    timeout = timeout or settings.RECIPES_HTTP_TIMEOUT_SECONDS
    max_bytes = max_bytes or settings.RECIPES_HTTP_MAX_RESPONSE_BYTES
    method = method.upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        raise EgressBlocked("method not allowed")
    if body is not None and len(body) > MAX_BODY:
        raise EgressBlocked("request body too large")
    hdrs = clean_headers(headers)
    scheme, host, port, path = validate_url(url, policy)
    ips = resolve_safe(host, port, policy, resolver)

    default_port = 443 if scheme == "https" else 80
    hdrs["Host"] = host if port == default_port else f"{host}:{port}"
    deadline = time.monotonic() + timeout
    last: Optional[Exception] = None
    for ip in ips[:3]:
        netloc = f"[{ip}]" if ":" in ip else ip
        target = f"{scheme}://{netloc}:{port}{path}"
        try:
            with httpx.Client(
                transport=transport, timeout=httpx.Timeout(timeout), follow_redirects=False, trust_env=False,
            ) as client:
                with client.stream(
                    method, target, headers=hdrs, content=body, extensions={"sni_hostname": host}
                ) as resp:
                    chunks, size = [], 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise ResponseTooLarge("response too large")
                        chunks.append(chunk)
                        if time.monotonic() > deadline:
                            raise HttpFailure("request timed out")
                    keep = {k.lower(): v for k, v in resp.headers.items() if k.lower() in ("content-type", "location")}
                    return HttpResult(resp.status_code, resp.headers.get("content-type", ""), b"".join(chunks), keep)
        except (ResponseTooLarge, HttpFailure):
            raise
        except httpx.TimeoutException as e:
            raise HttpFailure("request timed out") from e
        except httpx.ConnectError as e:
            last = e
            continue
        except httpx.HTTPError as e:
            raise HttpFailure("network error") from e
    raise HttpFailure("could not connect") from last
