"""Session revocation helpers."""

from typing import Optional

from sqlalchemy.orm import Session

from backend.app.auth.session import Session as AuthSession
from backend.app.auth.session import SessionStatus


def revoke_user_sessions(db: Session, user_id: int, except_id: Optional[int] = None) -> int:
    """Revoke all active sessions of a user (optionally keeping one). No commit."""
    q = db.query(AuthSession).filter(
        AuthSession.user_id == user_id, AuthSession.status == SessionStatus.ACTIVE.value
    )
    if except_id is not None:
        q = q.filter(AuthSession.id != except_id)
    return q.update({AuthSession.status: SessionStatus.REVOKED.value}, synchronize_session=False)
