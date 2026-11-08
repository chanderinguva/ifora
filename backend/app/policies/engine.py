"""Decide whether a sign-in to an application is acceptable *now*. One function, called at every point where a token,
assertion or credential would be issued, so the rule cannot be bypassed by picking a different entry point.

Order: network first (a blocked network is refused outright, nothing to step up), then factor strength, then freshness.
Fails closed: an allow-list whose zones were all deleted, or a client address that cannot be parsed, matches nothing.
"""

import ipaddress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.app.policies.models import AppAuthPolicy, NetworkZone

ALLOW, DENY, REAUTH = "allow", "deny", "reauth"


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str = ""


def parse_ip(value: Optional[str]):
    try:
        ip = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None
    return ip.ipv4_mapped if ip.version == 6 and ip.ipv4_mapped else ip


def in_zone(ip, zone: NetworkZone) -> bool:
    if ip is None:
        return False
    for c in zone.cidrs or []:
        try:
            net = ipaddress.ip_network(c, strict=False)
        except ValueError:
            continue
        if ip.version == net.version and ip in net:
            return True
    return False


def get_policy(db: Session, application_id: int) -> Optional[AppAuthPolicy]:
    return db.query(AppAuthPolicy).filter(AppAuthPolicy.application_id == application_id).first()


def _zones(db: Session, ids: List[int]) -> List[NetworkZone]:
    return db.query(NetworkZone).filter(NetworkZone.id.in_(ids)).all() if ids else []


def evaluate(db: Session, application_id: int, user, session, client_ip: Optional[str]) -> Decision:
    pol = get_policy(db, application_id)
    if pol is None:
        return Decision(ALLOW)
    ip = parse_ip(client_ip)
    if any(in_zone(ip, z) for z in _zones(db, pol.blocked_zone_ids or [])):
        return Decision(DENY, "This application cannot be used from your network")
    if pol.allowed_zone_ids:
        if not any(in_zone(ip, z) for z in _zones(db, pol.allowed_zone_ids)):
            return Decision(DENY, "This application can only be used from approved networks")
    if pol.require_mfa and "mfa" not in (session.amr or []):
        if getattr(user, "has_second_factor", False):
            return Decision(REAUTH, "mfa")
        return Decision(DENY, "This application requires multi-factor authentication; set up a second factor in Account settings")
    if pol.reauth_minutes and (datetime.now(timezone.utc) - session.auth_time).total_seconds() > pol.reauth_minutes * 60:
        return Decision(REAUTH, "stale")
    return Decision(ALLOW)


def check(db: Session, request, application_id: Optional[int], user, session) -> Decision:
    """`evaluate` for a live request: takes the client address from the request and audits a denial (caller commits)."""
    if application_id is None:
        return Decision(ALLOW)
    from backend.app import ratelimit
    from backend.app.audit.model import AuditAction
    from backend.app.audit.service import record

    d = evaluate(db, application_id, user, session, ratelimit.client_ip(request))
    if d.kind == DENY:
        record(db, AuditAction.APPLICATION_POLICY_DENIED, request, user, application_id, "application", {"reason": d.reason})
    return d


def wants_reauth(db: Session, request, application_id: Optional[int], user, session) -> bool:
    """Would a sign-in right now need a fresh login? Read-only (no audit), for pages that must tell the user up front."""
    if application_id is None:
        return False
    from backend.app import ratelimit

    return evaluate(db, application_id, user, session, ratelimit.client_ip(request)).kind == REAUTH
