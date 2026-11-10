"""Admin API tokens and the administrators list (ADR 024)."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.app import ratelimit
from backend.app.api_tokens.models import ApiToken
from backend.app.api_tokens.service import hash_token
from backend.app.audit.model import AuditEvent
from backend.app.config import settings
from tests.conftest import Api, STRONG, make_user


def mint(a, name="ci", **over):
    r = a.post("/admin/api-tokens", {"name": name, "password": STRONG, **over})
    assert r.status_code == 201, r.text
    return r.json()


def bearer(raw):
    return {"Authorization": f"Bearer {raw}"}


def get(raw, path, client=None):
    return (client or Api()).c.get("/api/v1" + path, headers=bearer(raw))


def send(raw, method, path, json=None):
    return Api().c.request(method, "/api/v1" + path, headers=bearer(raw), json=json)


def test_token_is_shown_once_and_only_a_hash_is_stored(admin, db):
    t = mint(admin)
    assert t["token"].startswith("idf_api_") and t["status"] == "active"
    row = db.query(ApiToken).one()
    assert row.token_hash == hash_token(t["token"]) and row.token_hash != t["token"] and t["token"] not in str(row.__dict__)
    listed = admin.get("/admin/api-tokens").json()["items"]
    assert len(listed) == 1 and "token" not in listed[0] and listed[0]["token_prefix"] == t["token"][:12]
    assert t["token"] not in str([e.metadata_json if hasattr(e, "metadata_json") else e.__dict__ for e in db.query(AuditEvent).all()])


def test_bearer_reads_the_admin_api_without_cookie_or_csrf(admin):
    t = mint(admin)
    r = get(t["token"], "/admin/users")
    assert r.status_code == 200
    assert send(t["token"], "POST", "/admin/groups", {"name": "Via token"}).status_code in (200, 201)   # write works without CSRF


def test_creating_needs_the_password_and_a_valid_lifetime(admin):
    assert admin.post("/admin/api-tokens", {"name": "x", "password": "wrong-password"}).status_code == 403
    assert admin.post("/admin/api-tokens", {"name": "x", "password": STRONG, "expires_in_days": 91}).status_code == 422
    assert admin.post("/admin/api-tokens", {"name": "x", "password": STRONG, "expires_in_days": 0}).status_code == 422
    t = admin.post("/admin/api-tokens", {"name": "x", "password": STRONG}).json()
    days = (datetime.fromisoformat(t["expires_at"]) - datetime.now(timezone.utc)).days
    assert 28 <= days <= 30


def test_read_only_token_cannot_write(admin):
    t = mint(admin, read_only=True)
    assert get(t["token"], "/admin/users").status_code == 200
    r = send(t["token"], "POST", "/admin/groups", {"name": "nope"})
    assert r.status_code == 403 and "read-only" in r.json()["detail"]


def test_token_has_only_its_owners_role(db):
    owner = make_user(db, "hd@example.com", admin=True, roles=["help_desk_admin"])
    a = Api()
    a.login(owner.email)
    t = mint(a)
    assert get(t["token"], "/admin/users").status_code == 200
    assert send(t["token"], "POST", "/admin/applications", {"name": "A", "sign_on_mode": "none"}).status_code == 403
    assert get(t["token"], "/admin/roles").status_code == 403


def test_demoting_or_deactivating_the_owner_takes_effect_at_once(admin, db):
    t = mint(admin)
    assert get(t["token"], "/admin/users").status_code == 200
    from backend.app.admin_roles.models import AdminRoleAssignment

    db.query(AdminRoleAssignment).filter(AdminRoleAssignment.user_id == admin.user.id).delete()
    db.commit()
    assert get(t["token"], "/admin/users").status_code == 403
    admin.user.status = "inactive"
    db.commit()
    assert get(t["token"], "/admin/users").status_code == 401


def test_token_cannot_reach_self_service_or_token_management(admin):
    t = mint(admin)
    assert get(t["token"], "/me").status_code == 403
    assert get(t["token"], "/me/profile").status_code == 403
    assert get(t["token"], "/admin/api-tokens").status_code == 403
    assert send(t["token"], "POST", "/admin/api-tokens", {"name": "child", "password": STRONG}).status_code == 403
    assert send(t["token"], "DELETE", f"/admin/api-tokens/{t['id']}").status_code == 403


def test_bad_tokens_are_refused_and_failures_audited(admin, db):
    t = mint(admin)
    assert get("idf_api_" + "x" * 43, "/admin/users").status_code == 401
    assert get("idf_api_" + "x" * 500, "/admin/users").status_code == 401
    assert get(t["token"][:-1] + ("A" if t["token"][-1] != "A" else "B"), "/admin/users").status_code == 401
    assert send(t["token"], "DELETE", "/admin/users/999999").status_code != 401   # sanity: the real one still works
    assert admin.delete(f"/admin/api-tokens/{t['id']}").status_code == 200
    assert get(t["token"], "/admin/users").status_code == 401
    assert db.query(AuditEvent).filter(AuditEvent.action == "API_TOKEN_AUTH_FAILED").count() >= 1
    assert db.query(AuditEvent).filter(AuditEvent.action == "API_TOKEN_REVOKED").count() == 1


def test_expired_token(admin, db):
    t = mint(admin)
    row = db.query(ApiToken).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert get(t["token"], "/admin/users").status_code == 401


def test_ip_allow_list(admin, monkeypatch):
    t = mint(admin, allowed_cidrs=["10.1.0.0/16"])
    monkeypatch.setattr(ratelimit, "client_ip", lambda request: "10.1.2.3")
    assert get(t["token"], "/admin/users").status_code == 200
    monkeypatch.setattr(ratelimit, "client_ip", lambda request: "192.0.2.9")
    assert get(t["token"], "/admin/users").status_code == 401
    assert admin.post("/admin/api-tokens", {"name": "bad", "password": STRONG, "allowed_cidrs": ["nonsense"]}).status_code == 422


def test_token_needs_an_admin_with_a_second_factor(admin, monkeypatch):
    t = mint(admin)
    monkeypatch.setattr(settings, "ADMIN_MFA_REQUIRED", True)
    r = get(t["token"], "/admin/users")
    assert r.status_code == 403 and "setup required" in r.json()["detail"]


def test_limits_and_unique_names(admin):
    mint(admin, "one")
    assert admin.post("/admin/api-tokens", {"name": "one", "password": STRONG}).status_code == 409
    for i in range(9):
        mint(admin, f"t{i}")
    assert admin.post("/admin/api-tokens", {"name": "eleven", "password": STRONG}).status_code == 409


def test_visibility_and_revocation_rights(db, admin):
    mint(admin, "mine")
    other = make_user(db, "g@example.com", admin=True, roles=["group_admin"])
    o = Api()
    o.login(other.email)
    assert o.get("/admin/api-tokens").json()["items"] == []
    assert o.get("/admin/api-tokens?all=true").status_code == 403
    tid = admin.get("/admin/api-tokens").json()["items"][0]["id"]
    assert o.delete(f"/admin/api-tokens/{tid}").status_code == 404
    assert admin.get("/admin/api-tokens?all=true").json()["items"][0]["owner"]["email"] == "admin@example.com"


def test_a_member_cannot_use_the_token_api(member):
    assert member.get("/admin/api-tokens").status_code == 403
    assert member.post("/admin/api-tokens", {"name": "x", "password": STRONG}).status_code == 403


def test_super_admin_tokens_work_like_any_other(super_admin):
    t = mint(super_admin)
    assert get(t["token"], "/admin/roles").status_code == 200
    ro = mint(super_admin, "ro", read_only=True)
    assert send(ro["token"], "POST", "/admin/groups", {"name": "x"}).status_code == 403


def test_administrators_list(db, admin, super_admin):
    from backend.app.groups.model import Group

    member = make_user(db, "viaGroup@example.com", first_name="Via", last_name="Group")
    g = Group(name="Admins - help desk")
    db.add(g)
    db.commit()
    from backend.app.admin_roles.models import GroupAdminRole

    db.add(GroupAdminRole(group_id=g.id, role="help_desk_admin"))
    from backend.app.groups.model import user_group_association

    db.execute(user_group_association.insert().values(user_id=member.id, group_id=g.id))
    db.commit()
    mint(admin)
    d = super_admin.get("/admin/administrators").json()
    by = {i["email"]: i for i in d["items"]}
    assert {"admin@example.com", "root@example.com", "viagroup@example.com"} <= {e.lower() for e in by}
    via = next(i for e, i in by.items() if e.lower() == "viagroup@example.com")
    assert via["roles"][0]["role"] == "help_desk_admin" and via["roles"][0]["sources"][0]["via"] == "group"
    assert by["admin@example.com"]["active_api_tokens"] == 1 and by["root@example.com"]["is_super_admin"] is True
    assert by["admin@example.com"]["mfa"] is False
    assert [i["email"] for i in super_admin.get("/admin/administrators?role=help_desk_admin").json()["items"]] == [via["email"]]
    assert super_admin.get("/admin/administrators?mfa=none").json()["total"] >= 2


def test_administrators_list_needs_an_admin_who_may_see_security(db, member):
    assert member.get("/admin/administrators").status_code == 403
    u = make_user(db, "app@example.com", admin=True, roles=["app_admin"])
    a = Api()
    a.login(u.email)
    assert a.get("/admin/administrators").status_code == 403
    r = make_user(db, "ro@example.com", admin=True, roles=["read_only_admin"])
    b = Api()
    b.login(r.email)
    assert b.get("/admin/administrators").status_code == 200
