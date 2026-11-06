"""Operator recovery CLI. Needs shell + database access to the deployment, which is the trust
boundary: it is how a super admin who lost every sign-in factor gets back in.

    python -m backend.cli reset-factors admin@example.com [--yes]

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
from backend.app.db import SessionLocal
from backend.app.users.model import User


def reset_factors(email: str, assume_yes: bool = False, confirm=input, out=print) -> int:
    db = SessionLocal()
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


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("reset-factors", help="remove a user's MFA and passkeys (lost devices)")
    p.add_argument("email")
    p.add_argument("--yes", "-y", action="store_true", help="do not prompt")
    args = parser.parse_args(argv)
    return reset_factors(args.email, args.yes)


if __name__ == "__main__":
    sys.exit(main())
