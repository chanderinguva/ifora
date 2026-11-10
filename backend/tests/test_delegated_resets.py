"""Who may reset an end user's authenticators and password: every administrator role, each against every kind of target."""

import pytest

from tests.conftest import Api, STRONG, make_user
from tests.test_account_recovery import outbox  # noqa: F401
from tests.test_mfa import enrol

NEW = "Brand-new-pass-77"
ROLES = ["org_admin", "help_desk_admin", "read_only_admin", "app_admin", "group_admin", "report_admin"]
MAY_RESET = {"org_admin", "help_desk_admin"}      # the roles with write access to users


def signed_in(db, role, email=None):
    u = make_user(db, email or f"{role}@example.com", admin=True, roles=[role])
    a = Api()
    assert a.login(u.email).status_code == 200
    a.user = u
    return a


def enrolled_user(db, email="victim@example.com"):
    u = make_user(db, email)
    a = Api()
    a.login(u.email)
    enrol(a, db, u.email)
    a.user = u
    return a


@pytest.mark.parametrize("role", ROLES)
def test_reset_authenticators_by_role(db, role):
    actor = signed_in(db, role)
    victim = enrolled_user(db)
    r = actor.post(f"/admin/users/{victim.user.id}/mfa/reset")
    if role in MAY_RESET:
        assert r.status_code == 200, r.text
        assert victim.get("/me").status_code == 401                     # signed out everywhere
        assert Api().login(victim.user.email).json()["success"] is True  # password alone works again
    else:
        assert r.status_code == 403
        assert victim.get("/me").status_code == 200                     # nothing happened


@pytest.mark.parametrize("role", ROLES)
def test_set_password_by_role(db, role):
    actor = signed_in(db, role)
    victim = make_user(db, "pw.victim@example.com")
    v = Api()
    v.login(victim.email)
    r = actor.post(f"/admin/users/{victim.id}/password", {"new_password": NEW, "require_change": True})
    if role in MAY_RESET:
        assert r.status_code == 200, r.text
        assert v.get("/me").status_code == 401
        assert Api().login(victim.email, NEW).status_code == 200
    else:
        assert r.status_code == 403
        assert Api().login(victim.email).status_code == 200


@pytest.mark.parametrize("role", ROLES)
def test_email_reset_link_by_role(db, role, outbox):  # noqa: F811
    actor = signed_in(db, role)
    victim = make_user(db, "link.victim@example.com")
    r = actor.post(f"/admin/users/{victim.id}/send-reset")
    assert (r.status_code == 200 and len(outbox) == 1) if role in MAY_RESET else (r.status_code == 403 and not outbox)


@pytest.mark.parametrize("role", sorted(MAY_RESET))
def test_delegated_admins_cannot_reset_other_administrators(db, role, super_admin, outbox):  # noqa: F811
    actor = signed_in(db, role)
    other = make_user(db, "other.admin@example.com", admin=True, roles=["help_desk_admin"])
    for path, body in ((f"/admin/users/{other.id}/mfa/reset", None), (f"/admin/users/{other.id}/password", {"new_password": NEW}),
                       (f"/admin/users/{other.id}/send-reset", None),
                       (f"/admin/users/{super_admin.user.id}/mfa/reset", None), (f"/admin/users/{super_admin.user.id}/password", {"new_password": NEW}),
                       (f"/admin/users/{super_admin.user.id}/send-reset", None)):
        assert actor.post(path, body).status_code == 403, path
    assert not outbox
    assert Api().login(super_admin.user.email).status_code == 200


def test_a_super_admin_can_reset_an_administrator_but_not_another_super_admin(db, super_admin):
    other = make_user(db, "hd@example.com", admin=True, roles=["help_desk_admin"])
    other_api = Api()
    other_api.login(other.email)
    enrol(other_api, db, other.email)
    assert super_admin.post(f"/admin/users/{other.id}/mfa/reset").status_code == 200
    second = make_user(db, "root2@example.com", super_admin=True)
    assert super_admin.post(f"/admin/users/{second.id}/mfa/reset").status_code == 403
    assert super_admin.post(f"/admin/users/{second.id}/password", {"new_password": NEW}).status_code == 403


def test_nobody_resets_themselves_and_every_reset_is_audited(db):
    actor = signed_in(db, "help_desk_admin")
    assert actor.post(f"/admin/users/{actor.user.id}/mfa/reset").status_code in (400, 403)
    victim = enrolled_user(db)
    actor.post(f"/admin/users/{victim.user.id}/mfa/reset")
    actor.post(f"/admin/users/{victim.user.id}/password", {"new_password": NEW})
    from backend.app.audit.model import AuditEvent

    rows = db.query(AuditEvent).filter(AuditEvent.action.in_(["MFA_RESET", "USER_PASSWORD_CHANGED"])).all()
    assert {r.action for r in rows} == {"MFA_RESET", "USER_PASSWORD_CHANGED"} and all(r.actor_id == str(actor.user.id) for r in rows)


def test_an_api_token_carries_the_same_limits(db):
    actor = signed_in(db, "help_desk_admin")
    t = actor.post("/admin/api-tokens", {"name": "desk", "password": STRONG}).json()["token"]
    victim = enrolled_user(db)
    h = {"Authorization": f"Bearer {t}"}
    assert Api().c.post(f"/api/v1/admin/users/{victim.user.id}/mfa/reset", headers=h).status_code == 200
    ro = actor.post("/admin/api-tokens", {"name": "ro", "password": STRONG, "read_only": True}).json()["token"]
    v2 = enrolled_user(db, "v2@example.com")
    assert Api().c.post(f"/api/v1/admin/users/{v2.user.id}/mfa/reset", headers={"Authorization": f"Bearer {ro}"}).status_code == 403
