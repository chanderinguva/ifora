"""IFORA-18: a signed-in admin of tenant A cannot read or change tenant B's identities through the API.

Tenant B's objects are created straight in the database (only one tenant is resolvable per request), then every
route that takes an id is called with B's ids from A's admin session. Each must answer 404 and leave B untouched.
"""

import uuid

import pytest
from sqlalchemy import func, insert, select

from backend.app import tenancy
from backend.app.applications.models import Application
from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.config import settings
from backend.app.db import SessionLocal
from backend.app.groups.model import Group, user_group_association
from backend.app.groups.rules import GroupRule, rule_targets
from backend.app.tenancy import Tenant, unscoped, use_tenant
from backend.app.users.model import User
from tests.conftest import Api, STRONG, make_user
from tests.test_group_rules import dept, rule_body
from tests.test_tenancy import b_session, tenant_b  # noqa: F401  (fixture)

SECRET = "tenant-b-secret-marker"


@pytest.fixture
def world(db, tenant_b, super_admin):
    """Tenant A: super_admin plus a user/group/app/rule of its own. Tenant B: the same, with ids A must never reach."""
    a_user = make_user(db, "a-user@example.com")
    a_group = Group(name="a-group")
    db.add(a_group)
    db.commit()

    s = b_session(tenant_b)
    b_user = make_user(s, "b-user@example.com")
    b_group = Group(name=f"b-group-{SECRET}")
    b_app = Application(public_id=str(uuid.uuid4()), name=f"b-app-{SECRET}", sign_on_mode="none")
    b_rule = GroupRule(name=f"b-rule-{SECRET}", conditions=[{"attribute": "department", "operator": "equals", "value": "x"}])
    s.add_all([b_group, b_app, b_rule])
    s.commit()
    s.execute(insert(user_group_association).values(user_id=b_user.id, group_id=b_group.id))
    s.execute(insert(rule_targets).values(rule_id=b_rule.id, group_id=b_group.id))
    s.add(AuditEvent(AuditAction.LOGIN_SUCCESS, details=SECRET))
    s.commit()
    ids = dict(user=b_user.id, group=b_group.id, app=b_app.id, rule=b_rule.id)
    s.close()
    return dict(admin=super_admin, a_user=a_user.id, a_group=a_group.id, b=ids, b_tenant=tenant_b)


def _b_snapshot():
    s = SessionLocal()
    try:
        with unscoped(s):
            return (
                sorted(u.email for u in s.query(User).filter(User.tenant_id != tenancy.default_tenant_id())),
                sorted(g.name for g in s.query(Group).filter(Group.tenant_id != tenancy.default_tenant_id())),
                sorted(a.name for a in s.query(Application).filter(Application.tenant_id != tenancy.default_tenant_id())),
                sorted(r.name for r in s.query(GroupRule).filter(GroupRule.tenant_id != tenancy.default_tenant_id())),
                s.execute(select(user_group_association.c.user_id, user_group_association.c.group_id)
                          .where(user_group_association.c.tenant_id != tenancy.default_tenant_id())).all(),
            )
    finally:
        s.close()


def _calls(w):
    """(method, path, body) for every id-taking route of users, groups, applications and group rules."""
    b, a_user, a_group = w["b"], w["a_user"], w["a_group"]
    u, g, ap, r = b["user"], b["group"], b["app"], b["rule"]
    app_body = {"name": "renamed", "sign_on_mode": "none"}
    return [
        ("GET", f"/admin/users/{u}", None),
        ("PATCH", f"/admin/users/{u}", {"status": "deprovisioned"}),
        ("POST", f"/admin/users/{u}/password", {"new_password": STRONG}),
        ("POST", f"/admin/users/{u}/send-invite", None),
        ("POST", f"/admin/users/{u}/send-reset", None),
        ("GET", f"/admin/users/{u}/applications", None),
        ("GET", f"/admin/users/{u}/events", None),
        ("DELETE", f"/admin/users/{u}", None),
        ("GET", f"/admin/groups/{g}", None),
        ("PATCH", f"/admin/groups/{g}", {"name": "renamed"}),
        ("POST", f"/admin/groups/{g}/members", {"user_id": a_user}),        # B group, A user
        ("POST", f"/admin/groups/{a_group}/members", {"user_id": u}),       # A group, B user
        ("DELETE", f"/admin/groups/{g}/members/{u}", None),
        ("DELETE", f"/admin/groups/{a_group}/members/{u}", None),
        ("DELETE", f"/admin/groups/{g}", None),
        ("GET", f"/admin/applications/{ap}", None),
        ("PUT", f"/admin/applications/{ap}", app_body),
        ("GET", f"/admin/applications/{ap}/assignments", None),
        ("POST", f"/admin/applications/{ap}/assignments", {"user_id": a_user}),
        ("POST", f"/admin/applications/{ap}/assignments", {"group_id": g}),  # B group onto an A app
        ("DELETE", f"/admin/applications/{ap}/assignments/1", None),
        ("GET", f"/admin/applications/{ap}/icon", None),
        ("DELETE", f"/admin/applications/{ap}/icon", None),
        ("DELETE", f"/admin/applications/{ap}/oidc-client", None),
        ("DELETE", f"/admin/applications/{ap}", None),
        ("GET", f"/admin/group-rules/{r}", None),
        ("PUT", f"/admin/group-rules/{r}", rule_body(a_group, name="renamed")),
        ("POST", f"/admin/group-rules/{r}/activate", None),
        ("POST", f"/admin/group-rules/{r}/deactivate", None),
        ("DELETE", f"/admin/group-rules/{r}", None),
        ("POST", "/admin/group-rules", rule_body(g)),                        # an A rule may not target a B group
    ]


def test_every_route_answers_404_for_the_other_tenants_ids_and_changes_nothing(world):
    admin = world["admin"]
    before = _b_snapshot()
    wrong = []
    for method, path, body in _calls(world):
        r = admin.c.request(method, "/api/v1" + path, json=body, headers=admin._h()) if body is not None else admin.c.request(method, "/api/v1" + path, headers=admin._h())
        if r.status_code not in (404, 422):
            wrong.append((method, path, r.status_code))
        assert SECRET not in r.text, (method, path)
    assert wrong == []
    assert _b_snapshot() == before


def test_lists_and_exports_never_contain_the_other_tenant(world):
    admin = world["admin"]
    for path in ("/admin/users", "/admin/groups", "/admin/applications", "/admin/group-rules", "/admin/audit",
                 "/admin/audit/export", "/admin/groups/analytics", "/admin/stats"):
        r = admin.get(path)
        assert r.status_code == 200, path
        assert SECRET not in r.text and "b-user@example.com" not in r.text, path


def test_stats_count_only_this_tenants_memberships(world, db):
    db.execute(insert(user_group_association).values(user_id=world["a_user"], group_id=world["a_group"]))
    db.commit()
    mine = db.execute(
        select(func.count()).select_from(user_group_association)
        .where(user_group_association.c.tenant_id == tenancy.default_tenant_id())
    ).scalar()
    assert mine == 1  # B also has one, which must not be counted
    assert world["admin"].get("/admin/stats").json()["memberships"] == mine


def test_a_rule_run_reads_and_writes_only_its_own_tenant(world, db):
    """_reconcile for an A rule never touches B's users, groups or memberships (acceptance criterion 2)."""
    admin = world["admin"]
    dept(db, "sales-a@example.com", "Sales")
    sb = b_session(world["b_tenant"])
    sb.query(User).filter(User.email == "b-user@example.com").one().set_profile_attributes({"department": "Sales"})
    sb.commit()
    sb.close()
    before = _b_snapshot()
    r = admin.post("/admin/group-rules", rule_body(world["a_group"]))
    assert r.status_code == 201
    assert admin.post(f"/admin/group-rules/{r.json()['id']}/activate").status_code == 200
    members = {m["email"] for m in admin.get(f"/admin/groups/{world['a_group']}").json()["members"]}
    assert "sales-a@example.com" in members and "b-user@example.com" not in members
    assert _b_snapshot() == before


# --- tenant resolution: unresolvable -> refused, never another tenant --------------------------------------------


@pytest.fixture
def host_mode(monkeypatch):
    monkeypatch.setattr(settings, "TENANT_RESOLUTION", "host")
    monkeypatch.setattr(settings, "TENANT_BASE_DOMAIN", "ifora.test")


def _get(host, headers=None):
    return Api().c.get("/api/v1/admin/users", headers={"Host": host, **(headers or {})})


def test_host_mode_without_a_resolvable_tenant_fails_closed(host_mode, tenant_b):
    for host in ("localhost", "ifora.test", "unknown.ifora.test", "a.b.ifora.test", "evil.com"):
        r = _get(host)
        assert r.status_code == 404 and "email" not in r.text, host


def test_a_tenant_header_from_the_client_is_ignored(host_mode, tenant_b):
    r = _get("localhost", {"X-Tenant-ID": str(tenant_b), "X-Tenant": "acme", "X-Forwarded-Host": "acme.ifora.test"})
    assert r.status_code == 404


def test_host_mode_resolves_a_known_tenant(host_mode, tenant_b):
    assert tenancy.resolve_tenant_id("acme.ifora.test:443") == tenant_b
    assert tenancy.resolve_tenant_id("ACME.ifora.test") == tenant_b
    r = _get("acme.ifora.test")
    assert r.status_code in (401, 403)  # tenant found; the caller just is not signed in


def test_a_resolver_fault_is_a_503_not_a_fallback(monkeypatch):
    def boom(host):
        raise RuntimeError("db down")

    monkeypatch.setattr(tenancy, "resolve_tenant_id", boom)
    r = _get("localhost")
    assert r.status_code == 503 and "email" not in r.text


def test_single_mode_still_uses_the_default_tenant(db):
    assert tenancy.resolve_tenant_id("anything.example") == tenancy.default_tenant_id()
