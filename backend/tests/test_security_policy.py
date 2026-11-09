"""Organization password, lockout and session policy (ADR 018)."""

from datetime import datetime, timedelta, timezone

from backend.app.audit.model import AuditEvent
from backend.app.auth import password_tokens
from backend.app.auth.session import Session as AuthSession
from backend.app.users.model import User
from tests.conftest import Api, STRONG, make_user

P = "/admin/security-policy"
BASE = {"min_length": 12, "require_mixed_case": True, "require_digit": True, "require_symbol": False, "no_user_info": False, "history_count": 0,
        "max_age_days": 0, "max_failed_attempts": 5, "lockout_minutes": 15, "session_lifetime_hours": 8, "idle_timeout_minutes": 30}


def setp(sa, **over):
    r = sa.put(P, {**BASE, **over})
    assert r.status_code == 200, r.text
    return r.json()


def test_defaults_match_the_old_behaviour(super_admin):
    d = super_admin.get(P).json()
    assert d["policy"] == BASE == d["defaults"]
    assert d["rules"][0] == "At least 12 characters" and d["users_past_max_age"] == 0


def test_only_admins_with_security_access_may_change_it(db, member, super_admin):
    assert member.get(P).status_code == 403 and member.put(P, BASE).status_code == 403
    ro = make_user(db, "ro@example.com", admin=True)
    roa = Api(); assert roa.login(ro.email).status_code == 200
    assert super_admin.put(f"/admin/roles/users/{ro.id}", {"roles": ["read_only_admin"]}).status_code == 200
    assert roa.get(P).status_code == 200 and roa.put(P, BASE).status_code == 403


def test_bounds_and_idle_not_longer_than_lifetime(super_admin):
    for bad in ({"min_length": 7}, {"min_length": 65}, {"history_count": 25}, {"max_age_days": 731}, {"max_failed_attempts": 2},
                {"lockout_minutes": 0}, {"session_lifetime_hours": 0}, {"idle_timeout_minutes": 4}):
        assert super_admin.put(P, {**BASE, **bad}).status_code == 422, bad
    r = super_admin.put(P, {**BASE, "session_lifetime_hours": 1, "idle_timeout_minutes": 61})
    assert r.status_code == 422 and "idle" in r.json()["detail"].lower()


def test_change_is_audited_with_before_and_after(db, super_admin):
    setp(super_admin, min_length=16)
    db.expire_all()
    ev = [e for e in db.query(AuditEvent).all() if str(getattr(e.action, "value", e.action)) == "SECURITY_POLICY_CHANGED"]
    assert len(ev) == 1 and ev[0].event_metadata["changed"] == {"min_length": [12, 16]}


def test_min_length_applies_to_every_password_path(db, super_admin, member):
    setp(super_admin, min_length=16)
    short = "Abcdefgh1234567"   # 15 chars
    ok = "Abcdefgh12345678"      # 16 chars
    assert member.post("/me/password", {"current_password": STRONG, "new_password": short}).status_code == 422
    assert super_admin.post(f"/admin/users/{member.user.id}/password", {"new_password": short}).status_code == 422
    assert super_admin.post("/admin/users", {"email": "n@example.com", "first_name": "N", "last_name": "N", "password": short}).status_code == 422
    assert super_admin.post("/admin/users", {"email": "n@example.com", "first_name": "N", "last_name": "N", "password": ok}).status_code == 201
    assert member.post("/me/password", {"current_password": STRONG, "new_password": ok}).status_code == 200


def test_weak_reset_does_not_burn_the_link(db, super_admin, member):
    setp(super_admin, min_length=16)
    raw = password_tokens.issue(db, member.user, "reset")
    db.commit()
    anon = Api()
    assert anon.post("/auth/reset-password", {"token": raw, "new_password": "Abcdefgh1234567"}).status_code == 422
    assert anon.post("/auth/reset-password", {"token": raw, "new_password": "Abcdefgh12345678"}).status_code == 200   # same link still works


def test_symbol_and_user_info_rules(db, super_admin, member):
    setp(super_admin, require_symbol=True, no_user_info=True)
    mk = lambda pw: member.post("/me/password", {"current_password": STRONG, "new_password": pw}).status_code  # noqa: E731
    assert mk("Abcdefgh12345678") == 422                    # no symbol
    assert mk("Member-Abcdef1234") == 422                   # contains the email's first part
    assert mk("Zebra-Quartz-1234") == 200


def test_generated_passwords_satisfy_the_policy(db, super_admin):
    setp(super_admin, min_length=40, require_symbol=True)
    r = super_admin.post("/admin/users", {"email": "g@example.com", "first_name": "G", "last_name": "G", "generate_password": True})
    assert r.status_code == 201, r.text
    pw = r.json()["temporary_password"]
    assert len(pw) >= 40 and any(not c.isalnum() for c in pw) and any(c.isdigit() for c in pw) and pw != pw.lower() and pw != pw.upper()
    assert Api().login("g@example.com", pw).status_code == 200


def test_history_blocks_reuse_of_recent_passwords(db, super_admin, member):
    setp(super_admin, history_count=3)
    a, b, c = "Aaaaaaaa1111111", "Bbbbbbbb2222222", "Cccccccc3333333"
    a, b, c = a + "x", b + "x", c + "x"
    ch = lambda cur, new: member.post("/me/password", {"current_password": cur, "new_password": new}).status_code  # noqa: E731
    assert ch(STRONG, STRONG) == 422                      # the current password counts
    assert ch(STRONG, a) == 200 and ch(a, b) == 200
    assert ch(b, STRONG) == 422                           # still inside the last 3
    assert ch(b, a) == 422
    assert ch(b, c) == 200
    assert ch(c, STRONG) == 200                           # fell out of the window (c, b, a remembered; STRONG was oldest)


def test_history_off_stores_nothing(db, super_admin, member):
    assert member.post("/me/password", {"current_password": STRONG, "new_password": "Brandnew1234567x"}).status_code == 200
    from backend.app.security_policy.models import PasswordHistory
    assert db.query(PasswordHistory).count() == 0


def test_max_age_forces_a_change_at_next_sign_in(db, super_admin, member):
    setp(super_admin, max_age_days=30)
    u = db.get(User, member.user.id)
    u.password_changed_at = datetime.now(timezone.utc) - timedelta(days=31)
    db.commit()
    assert super_admin.get(P).json()["users_past_max_age"] == 1
    r = Api().login(u.email)
    assert r.status_code == 200 and r.json() == {"success": False, "password_change_required": True}
    db.expire_all()
    assert db.get(User, u.id).status == "password_expired"
    anon = Api()
    new = "Brandnew1234567x"
    assert anon.post("/auth/change-expired-password", {"email": u.email, "current_password": STRONG, "new_password": new}).status_code == 200
    assert Api().login(u.email, new).status_code == 200          # new password is fresh


def test_young_passwords_are_not_expired(db, super_admin, member):
    setp(super_admin, max_age_days=30)
    assert Api().login(member.user.email).status_code == 200


def test_lockout_threshold_and_duration_follow_the_policy(db, super_admin):
    setp(super_admin, max_failed_attempts=3, lockout_minutes=7)
    u = make_user(db, "lock@example.com")
    for _ in range(3):
        assert Api().login(u.email, "wrong-password-1A").status_code == 401
    db.expire_all()
    u = db.get(User, u.id)
    assert u.is_locked_out() is True
    mins = (u.lockout_until - datetime.now(timezone.utc)).total_seconds() / 60
    assert 6 < mins <= 7
    assert Api().login(u.email).status_code == 401              # correct password, still locked


def test_two_wrong_attempts_do_not_lock_when_threshold_is_three(db, super_admin):
    setp(super_admin, max_failed_attempts=3)
    u = make_user(db, "lock2@example.com")
    for _ in range(2):
        Api().login(u.email, "wrong-password-1A")
    assert Api().login(u.email).status_code == 200


def test_idle_timeout_and_lifetime_apply_to_open_sessions(db, super_admin, member):
    assert member.get("/me/profile").status_code == 200
    s = db.query(AuthSession).filter(AuthSession.user_id == member.user.id).first()
    s.last_activity_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db.commit()
    assert member.get("/me/profile").status_code == 200        # default idle is 30 minutes
    setp(super_admin, idle_timeout_minutes=5)
    s = db.query(AuthSession).filter(AuthSession.user_id == member.user.id).first()
    s.last_activity_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db.commit()
    assert member.get("/me/profile").status_code == 401        # tightened policy applies at once


def test_session_lifetime_is_enforced_and_sets_cookie_age(db, super_admin):
    setp(super_admin, session_lifetime_hours=2)
    u = make_user(db, "life@example.com")
    a = Api()
    r = a.login(u.email)
    assert "Max-Age=7200" in r.headers["set-cookie"]
    s = db.query(AuthSession).filter(AuthSession.user_id == u.id).first()
    s.created_at = datetime.now(timezone.utc) - timedelta(hours=3)
    s.last_activity_at = datetime.now(timezone.utc)
    db.commit()
    assert a.get("/me/profile").status_code == 401


def test_public_password_rules_expose_only_the_rules(db, super_admin, anon):
    setp(super_admin, min_length=14, history_count=2, max_age_days=90, max_failed_attempts=3)
    d = anon.get("/password-policy").json()
    assert set(d) == {"rules", "min_length"} and d["min_length"] == 14
    assert "Cannot reuse your last 2 passwords" in d["rules"]
