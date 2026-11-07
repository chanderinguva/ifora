"""Operator recovery CLI. Needs shell + database access to the deployment, which is the trust
boundary: it is how a super admin who lost every sign-in factor gets back in.

    python -m backend.cli reset-factors admin@example.com [--yes]
    python -m backend.cli issue-enrollment-code admin@example.com
    python -m backend.cli recipes-worker [--once] [--interval 2]
    python -m backend.cli purge-oidc
    python -m backend.cli purge-scim
    python -m backend.cli sync-group-rules

Removes the user's authenticator app, recovery codes and passkeys, lifts the passkey-required
policy, clears any lockout, and ends all their sessions. The password is NOT changed or shown.
Every run is written to the audit log (actor empty, metadata via=cli).
"""

import argparse
import sys
from typing import Optional

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth import mfa_service
from backend.app.tenancy import tenant_session
from backend.app.users.model import User


def reset_factors(email: str, assume_yes: bool = False, confirm=input, out=print) -> int:
    db = tenant_session()
    try:
        user = db.query(User).filter(User.email == email.strip().lower()).first()
        if user is None:
            out(f"error: no user with email {email!r}")
            return 1
        role = "super admin" if user.is_super_admin else "admin" if user.is_admin else "user"
        out(f"{user.email} ({role}): authenticator={'yes' if user.mfa else 'no'}, "
            f"passkeys={len(user.passkeys)}, passkey required={'yes' if user.passkey_required else 'no'}")
        if not assume_yes and confirm("Remove all sign-in factors and end all sessions? [y/N] ").strip().lower() != "y":
            out("aborted")
            return 2
        result = mfa_service.reset_all_factors(db, user)
        user.failed_login_attempts = 0
        user.lockout_until = None
        record(db, AuditAction.MFA_RESET, None, None, user.id, "user", {**result, "via": "cli"})
        db.commit()
        out(f"done: {result['passkeys_removed']} passkey(s) removed, {result['sessions_revoked']} session(s) ended. "
            "The user can now sign in with their password.")
        return 0
    finally:
        db.close()


def issue_enrollment_code(email: str, out=print) -> int:
    """One-time code that lets an admin with no second factor enrol their first one."""
    db = tenant_session()
    try:
        user = db.query(User).filter(User.email == email.strip().lower()).first()
        if user is None:
            out(f"error: no user with email {email!r}")
            return 1
        if not user.is_admin:
            out("error: enrolment codes are for administrators")
            return 1
        code = mfa_service.issue_enrollment_code(user)
        record(db, AuditAction.ENROLLMENT_CODE_ISSUED, None, None, user.id, "user",
               {"via": "cli", "expires_in_hours": mfa_service.ENROLLMENT_CODE_HOURS})
        db.commit()
        out(f"Enrolment code for {user.email} (single use, valid {mfa_service.ENROLLMENT_CODE_HOURS}h):")
        out(f"  {code}")
        out("Give it to them out of band. It replaces any earlier code and is not stored in clear.")
        return 0
    finally:
        db.close()


def rotate_signing_key(emergency: bool = False, assume_yes: bool = False, confirm=input, out=print, alg=None) -> int:
    """Rotate the OIDC signing key. --emergency signs with the new key immediately and revokes every old one."""
    from backend.app.oidc import keys

    db = tenant_session()
    try:
        if emergency and not assume_yes and confirm(
            "Emergency rotation revokes ALL current keys; tokens already issued stop verifying. Continue? [y/N] "
        ).strip().lower() != "y":
            out("aborted")
            return 2

        def audit(name, meta=None):
            record(db, AuditAction(name), None, None, None, "signing_key", {**(meta or {}), "via": "cli"})

        try:
            new = keys.rotate(db, emergency=emergency, alg=alg, audit=audit)
        except keys.KeyConfigError as e:
            out(f"error: {e}")
            return 1
        out(f"new key {new.kid} ({new.alg}) status={new.status}, signs from {new.activate_at.isoformat()}")
        return 0
    finally:
        db.close()


def recipes_worker(interval: float = 2.0, once: bool = False, out=print) -> int:
    """Run the recipe dispatcher/worker loop (ADR 008). Several copies may run at once (SKIP LOCKED)."""
    import time

    from backend.app.recipes import engine

    import os

    beat = os.environ.get("RECIPES_WORKER_HEARTBEAT_FILE")
    last_purge = 0.0
    while True:
        engine.heartbeat(beat)
        stats = engine.process_once()
        try:
            from backend.app.groups import rules as group_rules

            group_rules.sync_pending_all()  # finishes large group-rule activations in batches
        except Exception:  # noqa: BLE001 - never stop the worker for housekeeping
            pass
        if not once and time.monotonic() - last_purge > 3600:  # housekeeping rides on the worker: SCIM retention, hourly
            last_purge = time.monotonic()
            try:
                from backend.app.scim import retention

                retention.purge_all()
            except Exception:  # noqa: BLE001 - never stop the worker for housekeeping
                pass
        if once:
            out(f"recipes: {stats}")
            return 0
        time.sleep(interval)


def purge_oidc(out=print) -> int:
    """Delete expired OIDC pending requests, refresh families and authorization codes (cron-friendly)."""
    from backend.app.oidc import purge

    db = tenant_session()
    try:
        out("purged: " + ", ".join(f"{k}={v}" for k, v in purge.purge(db).items()))
        return 0
    finally:
        db.close()


def purge_scim(out=print) -> int:
    """Apply per-token SCIM retention: delete users a token deactivated more than N days ago (cron-friendly)."""
    from backend.app.scim import retention

    out(f"purged scim users: {retention.purge_all()}")
    return 0


def sync_group_rules(out=print) -> int:
    """Finish every pending group-rule activation now (the worker does this continuously)."""
    from backend.app.groups import rules as group_rules

    total = 0
    while True:
        n = group_rules.sync_pending_all()
        total += n
        if n == 0:
            break
    out(f"group rules synced: {total} users evaluated")
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("reset-factors", help="remove a user's MFA and passkeys (lost devices)")
    p.add_argument("email")
    p.add_argument("--yes", "-y", action="store_true", help="do not prompt")
    e = sub.add_parser("issue-enrollment-code", help="one-time code for an admin to enrol their first factor")
    e.add_argument("email")
    r = sub.add_parser("rotate-signing-key", help="rotate the OIDC token signing key")
    r.add_argument("--emergency", action="store_true", help="revoke all existing keys immediately (suspected compromise)")
    r.add_argument("--yes", "-y", action="store_true", help="do not prompt")
    r.add_argument("--alg", choices=["RS256", "ES256"], help="algorithm of the new key (default: OIDC_SIGNING_ALG)")
    w = sub.add_parser("recipes-worker", help="run the recipe engine worker loop")
    w.add_argument("--once", action="store_true", help="process due work once and exit")
    w.add_argument("--interval", type=float, default=2.0, help="seconds between polls")
    sub.add_parser("sync-group-rules", help="finish pending group-rule activations")
    sub.add_parser("purge-scim", help="delete users deprovisioned through SCIM past their token's retention period")
    sub.add_parser("purge-oidc", help="delete expired OIDC pending requests, refresh tokens and codes")
    args = parser.parse_args(argv)
    if args.cmd == "sync-group-rules":
        return sync_group_rules()
    if args.cmd == "purge-scim":
        return purge_scim()
    if args.cmd == "purge-oidc":
        return purge_oidc()
    if args.cmd == "recipes-worker":
        return recipes_worker(args.interval, args.once)
    if args.cmd == "rotate-signing-key":
        return rotate_signing_key(args.emergency, args.yes, alg=args.alg)
    if args.cmd == "issue-enrollment-code":
        return issue_enrollment_code(args.email)
    return reset_factors(args.email, args.yes)


if __name__ == "__main__":
    sys.exit(main())
