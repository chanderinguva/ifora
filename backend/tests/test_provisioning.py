"""Outbound provisioning (ADR 009): SCIM client, REST gateway, entitlement, retries, orphan sweep, permissions."""

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote

import httpx
import pytest

from backend.app.provisioning import adapters, worker
from backend.app.provisioning.models import ProvisioningLink, ProvisioningTask
from backend.app.recipes.http_client import EgressPolicy
from tests.conftest import Api, STRONG, make_user
from tests.recipe_helpers import new_group, new_user, public_resolver, rkey  # noqa: F401

BASE = "https://app.example.com/scim/v2"


class FakeScim:
    """A tiny in-memory SCIM 2.0 server behind an httpx transport."""

    def __init__(self, token="tok"):
        self.token, self.users, self.groups, self.calls, self.n = token, {}, {}, [], 0
        self.script = []  # [(predicate(method, path), Response)] consumed first-match-once

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/scim/v2")
        body = json.loads(req.content) if req.content else None
        self.calls.append((req.method, path, body))
        if req.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"detail": "bad token"})
        for i, (pred, resp) in enumerate(self.script):
            if pred(req.method, path):
                self.script.pop(i)
                return resp
        if path == "/ServiceProviderConfig":
            return httpx.Response(200, json={"patch": {"supported": True}})
        for kind, store in (("Users", self.users), ("Groups", self.groups)):
            if path == f"/{kind}" and req.method == "GET":
                f = parse_qs(req.url.query.decode()).get("filter", [""])[0]
                attr, _, val = f.partition(" eq ")
                val = val.strip('"')
                hits = [r for r in store.values() if r.get(attr) == val]
                return httpx.Response(200, json={"totalResults": len(hits), "Resources": hits})
            if path == f"/{kind}" and req.method == "POST":
                self.n += 1
                rid = f"r{self.n}"
                store[rid] = {**body, "id": rid}
                return httpx.Response(201, json=store[rid])
            if path.startswith(f"/{kind}/"):
                rid = unquote(path.split("/")[2])
                if rid not in store:
                    return httpx.Response(404, json={"detail": "nope"})
                if req.method == "PUT":
                    store[rid] = {**body, "id": rid}
                    return httpx.Response(200, json=store[rid])
                if req.method == "PATCH":
                    for op in body["Operations"]:
                        if op.get("path") == "active":
                            store[rid]["active"] = op["value"]
                        else:
                            store[rid].update(op["value"])
                    return httpx.Response(200, json=store[rid])
                if req.method == "DELETE":
                    del store[rid]
                    return httpx.Response(204)
        return httpx.Response(404, json={"detail": "unknown path"})

    def methods(self, method=None, prefix=""):
        return [c for c in self.calls if (method is None or c[0] == method) and c[1].startswith(prefix)]


@pytest.fixture
def remote(monkeypatch, rkey):
    r = FakeScim()
    monkeypatch.setattr(adapters, "http_overrides", {"policy": EgressPolicy(), "resolver": public_resolver, "transport": httpx.MockTransport(r)})
    return r


def make_app(sa, **over):
    body = {"name": "Acme", "kind": "scim", "base_url": BASE, "auth_type": "bearer", "secret": "tok", **over}
    r = sa.post("/admin/provisioning-apps", body)
    assert r.status_code == 201, r.text
    return r.json()


def body_of(app, **over):
    keys = ("name", "description", "kind", "base_url", "auth_type", "header_name", "options", "mapping", "rest_config")
    return {**{k: app[k] for k in keys}, **over}


def enable(sa, app):
    t = sa.post(f"/admin/provisioning-apps/{app['id']}/test")
    assert t.json()["ok"] is True, t.text
    r = sa.put(f"/admin/provisioning-apps/{app['id']}", body_of(app, enabled=True))
    assert r.status_code == 200, r.text
    return r.json()


def run(at=None):
    return worker.process_once(at)


def later(minutes=60):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def assign_user(sa, app, uid):
    assert sa.post(f"/admin/provisioning-apps/{app['id']}/assignments", {"user_id": uid}).status_code == 201


def links(db, app):
    db.expire_all()
    return db.query(ProvisioningLink).filter(ProvisioningLink.app_id == app["id"]).all()


def tasks(db, app, status=None):
    db.expire_all()
    q = db.query(ProvisioningTask).filter(ProvisioningTask.app_id == app["id"])
    return q.filter(ProvisioningTask.status == status).all() if status else q.all()


# ---- configuration and permissions ---------------------------------------------------------------------------

def test_create_validates_and_never_returns_the_secret(super_admin, rkey):
    app = make_app(super_admin)
    assert '"tok"' not in json.dumps(app) and "secret_enc" not in app and app["has_secret"] is True and app["enabled"] is False
    bad = lambda **o: super_admin.post("/admin/provisioning-apps", {"name": "x", "kind": "scim", "base_url": BASE, "auth_type": "bearer", "secret": "t", **o})  # noqa: E731
    assert bad(base_url="http://app.example.com/scim").status_code == 422        # https only
    assert bad(base_url="https://app.example.com/scim?x=1").status_code == 422
    assert bad(base_url="https://127.0.0.1/scim").status_code == 422             # private destination
    assert bad(auth_type="basic", secret="nocolon").status_code == 422
    assert bad(auth_type="header").status_code == 422                            # needs header_name
    assert bad(mapping=[{"target": "title", "source": "password"}]).status_code == 422   # not an allowed source
    assert bad(mapping=[{"target": "userName", "source": "email"}]).status_code == 422   # reserved target
    assert bad(kind="rest").status_code == 422                                   # needs rest_config
    assert super_admin.post("/admin/provisioning-apps", {"name": "Acme", "kind": "scim", "base_url": BASE, "auth_type": "bearer", "secret": "t"}).status_code == 409


def test_only_super_admins_change_apps_but_admins_read_and_assign(super_admin, admin, remote):
    app = make_app(super_admin)
    assert admin.post("/admin/provisioning-apps", {"name": "y", "kind": "scim", "base_url": BASE, "auth_type": "bearer", "secret": "t"}).status_code == 403
    assert admin.put(f"/admin/provisioning-apps/{app['id']}", body_of(app)).status_code == 403
    assert admin.delete(f"/admin/provisioning-apps/{app['id']}").status_code == 403
    assert admin.post(f"/admin/provisioning-apps/{app['id']}/test").status_code == 403
    assert admin.get("/admin/provisioning-apps").status_code == 200
    u = new_user(admin, "assignee@example.com")
    assert admin.post(f"/admin/provisioning-apps/{app['id']}/assignments", {"user_id": u["id"]}).status_code == 201


def test_members_cannot_reach_the_api(super_admin, member, rkey):
    make_app(super_admin)
    assert member.get("/admin/provisioning-apps").status_code == 403


def test_enabling_requires_a_successful_test_and_a_changed_destination_resets_it(super_admin, remote):
    app = make_app(super_admin)
    assert super_admin.put(f"/admin/provisioning-apps/{app['id']}", body_of(app, enabled=True)).status_code == 409
    app = enable(super_admin, app)
    assert app["enabled"] is True and app["last_test"]["ok"] is True
    moved = super_admin.put(f"/admin/provisioning-apps/{app['id']}", body_of(app, base_url="https://other.example.com/scim/v2")).json()
    assert moved["enabled"] is False and moved["last_test"]["ok"] is None


def test_failed_test_reports_without_leaking(super_admin, remote):
    app = make_app(super_admin, secret="wrong-token")
    r = super_admin.post(f"/admin/provisioning-apps/{app['id']}/test").json()
    assert r["ok"] is False and "401" in r["message"] and "wrong-token" not in r["message"]


# ---- user provisioning ----------------------------------------------------------------------------------------

def test_assigned_user_is_created_with_the_mapped_payload(db, admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin))
    u = new_user(admin, "ann@example.com")
    assert admin.patch(f"/admin/users/{u['id']}", {"profile_attributes": {"title": "CTO", "department": "Eng"}}).status_code == 200
    assign_user(admin, app, u["id"])
    run()
    (rec,) = remote.users.values()
    assert rec["userName"] == "ann@example.com" and rec["active"] is True and rec["externalId"]
    assert rec["name"] == {"givenName": "New", "familyName": "Person"} and rec["title"] == "CTO"
    assert rec["urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"]["department"] == "Eng"
    assert "password" not in json.dumps(rec).lower()
    (link,) = links(db, app)
    assert link.state == "synced" and link.remote_id == rec["id"]


def test_nothing_is_sent_for_unassigned_users_or_disabled_apps(super_admin, admin, remote):
    app = make_app(super_admin)                       # not enabled
    u = new_user(admin, "quiet@example.com")
    assign_user(admin, app, u["id"])
    run()
    new_user(admin, "other@example.com")
    app = enable(super_admin, app)
    run()
    assert [r["userName"] for r in remote.users.values()] == ["quiet@example.com"]   # enabling queued the assigned user only


def test_profile_change_updates_once_and_unchanged_is_quiet(admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin))
    u = new_user(admin, "bo@example.com")
    assign_user(admin, app, u["id"])
    run()
    remote.calls.clear()
    admin.patch(f"/admin/users/{u['id']}", {"profile_attributes": {"title": "Lead"}})
    run()
    assert [c[0] for c in remote.calls] == ["PUT"] and remote.users["r1"]["title"] == "Lead"
    remote.calls.clear()
    super_admin.post(f"/admin/provisioning-apps/{app['id']}/sync")
    run()
    assert remote.calls == []                          # same payload hash: no call at all


def test_status_changes_deactivate_and_reactivate(db, admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin))
    u = new_user(admin, "cy@example.com")
    assign_user(admin, app, u["id"])
    run()
    assert admin.patch(f"/admin/users/{u['id']}", {"status": "suspended"}).status_code == 200
    run()
    assert remote.users["r1"]["active"] is False and links(db, app)[0].state == "deprovisioned"
    assert admin.patch(f"/admin/users/{u['id']}", {"status": "active"}).status_code == 200
    run()
    assert remote.users["r1"]["active"] is True and links(db, app)[0].state == "synced"


def test_group_assignment_follows_membership(db, admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin))
    gid = new_group(admin, "Engineers")
    assert admin.post(f"/admin/provisioning-apps/{app['id']}/assignments", {"group_id": gid}).status_code == 201
    u = new_user(admin, "dee@example.com")
    run()
    assert remote.users == {}                           # not a member yet
    assert admin.post(f"/admin/groups/{gid}/members", {"user_id": u["id"]}).status_code in (200, 201)
    run()
    assert [r["userName"] for r in remote.users.values()] == ["dee@example.com"]
    assert admin.delete(f"/admin/groups/{gid}/members/{u['id']}").status_code == 200
    run()
    assert remote.users["r1"]["active"] is False


def test_still_entitled_through_another_path_stays_active(admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin))
    gid = new_group(admin, "G")
    u = new_user(admin, "eve@example.com")
    admin.post(f"/admin/groups/{gid}/members", {"user_id": u["id"]})
    admin.post(f"/admin/provisioning-apps/{app['id']}/assignments", {"group_id": gid})
    assign_user(admin, app, u["id"])
    run()
    admin.delete(f"/admin/groups/{gid}/members/{u['id']}")
    run()
    assert remote.users["r1"]["active"] is True


def test_deprovisioned_user_loses_apps_via_group_removal(admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin))
    gid = new_group(admin, "G2")
    u = new_user(admin, "fay@example.com")
    admin.post(f"/admin/groups/{gid}/members", {"user_id": u["id"]})
    admin.post(f"/admin/provisioning-apps/{app['id']}/assignments", {"group_id": gid})
    run()
    assert admin.patch(f"/admin/users/{u['id']}", {"status": "deprovisioned"}).status_code == 200   # also leaves every group
    run()
    assert remote.users["r1"]["active"] is False


def test_delete_policy_removes_the_account(db, admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin, options={"deactivate": "delete"}))
    u = new_user(admin, "gus@example.com")
    assign_user(admin, app, u["id"])
    run()
    rows = admin.get(f"/admin/provisioning-apps/{app['id']}/assignments").json()["items"]
    admin.delete(f"/admin/provisioning-apps/{app['id']}/assignments/{rows[0]['id']}")
    run()
    assert remote.users == {} and links(db, app) == []


def test_existing_remote_account_is_linked_not_duplicated(db, admin, super_admin, remote):
    remote.users["pre"] = {"id": "pre", "userName": "hal@example.com", "active": True}
    app = enable(super_admin, make_app(super_admin))
    u = new_user(admin, "hal@example.com")
    assign_user(admin, app, u["id"])
    run()
    assert list(remote.users) == ["pre"] and links(db, app)[0].remote_id == "pre"
    assert remote.methods("POST", "/Users") == [] and remote.users["pre"]["name"]["givenName"] == "New"


def test_create_conflict_falls_back_to_linking(db, admin, super_admin, remote):
    remote.script.append((lambda m, p: m == "GET" and p == "/Users", httpx.Response(200, json={"Resources": []})))
    remote.users["x1"] = {"id": "x1", "userName": "ida@example.com"}
    remote.script.append((lambda m, p: m == "POST" and p == "/Users", httpx.Response(409, json={"detail": "exists"})))
    app = enable(super_admin, make_app(super_admin))
    u = new_user(admin, "ida@example.com")
    assign_user(admin, app, u["id"])
    run()
    assert links(db, app)[0].remote_id == "x1"


def test_custom_mapping_templates(admin, super_admin, remote):
    rules = [{"target": "displayName", "source": "{{last_name}}, {{first_name}}"}, {"target": "nickName", "source": "username"}]
    app = enable(super_admin, make_app(super_admin, mapping=rules, options={"user_identifier": "username"}))
    u = new_user(admin, "jo@example.com")
    assign_user(admin, app, u["id"])
    run()
    rec = remote.users["r1"]
    assert rec["displayName"] == "Person, New" and rec["nickName"] == "jo" and rec["userName"] == "jo"


def test_patch_update_style(admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin, options={"update_style": "patch"}))
    u = new_user(admin, "kim@example.com")
    assign_user(admin, app, u["id"])
    run()
    remote.calls.clear()
    admin.patch(f"/admin/users/{u['id']}", {"profile_attributes": {"title": "VP"}})
    run()
    assert remote.calls[0][0] == "PATCH" and remote.users["r1"]["title"] == "VP"


# ---- failures -------------------------------------------------------------------------------------------------

def test_server_errors_retry_with_backoff_then_succeed(db, admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin))
    remote.script += [(lambda m, p: m == "GET" and p == "/Users", httpx.Response(503, json={"detail": "busy"}))]
    u = new_user(admin, "lee@example.com")
    assign_user(admin, app, u["id"])
    run()
    (t,) = tasks(db, app)
    assert t.status == "queued" and t.attempts == 1 and "503" in t.last_error
    run()                                               # not due yet: backoff
    assert remote.users == {}
    run(later())
    assert len(remote.users) == 1 and tasks(db, app)[0].status == "succeeded"


def test_429_honours_retry_after(db, admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin))
    remote.script.append((lambda m, p: m == "GET" and p == "/Users", httpx.Response(429, headers={"Retry-After": "1800"}, json={})))
    u = new_user(admin, "mo@example.com")
    assign_user(admin, app, u["id"])
    run()
    t = tasks(db, app)[0]
    assert t.status == "queued" and t.next_run_at > datetime.now(timezone.utc) + timedelta(minutes=29)


def test_permanent_error_fails_marks_the_link_audits_and_can_be_retried(db, admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin))
    u = new_user(admin, "ned@example.com")
    assign_user(admin, app, u["id"])
    run()
    admin.patch(f"/admin/users/{u['id']}", {"profile_attributes": {"title": "X"}})
    remote.script.append((lambda m, p: m == "PUT", httpx.Response(400, json={"detail": "title too short"})))
    run()
    (failed,) = tasks(db, app, "failed")
    assert "400" in failed.last_error and links(db, app)[0].state == "error"
    assert "PROVISIONING_TASK_FAILED" in admin.get("/admin/audit?limit=50").text
    assert admin.post(f"/admin/provisioning-apps/{app['id']}/tasks/{failed.id}/retry").status_code == 403
    assert super_admin.post(f"/admin/provisioning-apps/{app['id']}/tasks/{failed.id}/retry").status_code == 200
    run()
    assert remote.users["r1"]["title"] == "X" and links(db, app)[0].state == "synced"


def test_attempts_are_capped(db, admin, super_admin, remote, monkeypatch):
    from backend.app.config import settings
    monkeypatch.setattr(settings, "PROVISIONING_MAX_ATTEMPTS", 2)
    app = enable(super_admin, make_app(super_admin))
    remote.script += [(lambda m, p: m == "GET", httpx.Response(500, json={}))] * 4
    u = new_user(admin, "oz@example.com")
    assign_user(admin, app, u["id"])
    run()
    run(later())
    assert tasks(db, app)[0].status == "failed"


def test_private_destinations_and_redirects_are_refused(db, admin, super_admin, rkey, monkeypatch):
    r = FakeScim()
    monkeypatch.setattr(adapters, "http_overrides", {"policy": EgressPolicy(), "resolver": lambda h, p: ["10.0.0.5"], "transport": httpx.MockTransport(r)})
    app = make_app(super_admin)
    res = super_admin.post(f"/admin/provisioning-apps/{app['id']}/test").json()
    assert res["ok"] is False and "not allowed" in res["message"] and r.calls == []
    monkeypatch.setattr(adapters, "http_overrides", {"policy": EgressPolicy(), "resolver": public_resolver,
                                                     "transport": httpx.MockTransport(lambda req: httpx.Response(302, headers={"location": "http://169.254.169.254/"}))})
    res = super_admin.post(f"/admin/provisioning-apps/{app['id']}/test").json()
    assert res["ok"] is False and "302" in res["message"]


def test_secret_is_encrypted_at_rest(db, super_admin, rkey):
    from backend.app.provisioning.models import ProvisioningApp
    app = make_app(super_admin, secret="super-secret-value")
    db.expire_all()
    assert "super-secret-value" not in db.get(ProvisioningApp, app["id"]).secret_enc


# ---- groups, orphans, activity -------------------------------------------------------------------------------

def test_groups_are_pushed_with_member_ids(db, admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin, options={"push_groups": True}))
    gid = new_group(admin, "Ops")
    u = new_user(admin, "pat@example.com")
    admin.post(f"/admin/groups/{gid}/members", {"user_id": u["id"]})
    admin.post(f"/admin/provisioning-apps/{app['id']}/assignments", {"group_id": gid})
    run()
    run()                                               # second pass: the group task queued after the user was linked
    (grp,) = remote.groups.values()
    assert grp["displayName"] == "Ops" and grp["members"] == [{"value": "r1"}]
    admin.delete(f"/admin/groups/{gid}/members/{u['id']}")
    run()
    run()
    assert remote.groups["r2"]["members"] == []


def test_deleting_a_user_deactivates_them_in_the_app(db, admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin))
    u = new_user(admin, "quin@example.com")
    assign_user(admin, app, u["id"])
    run()
    assert admin.delete(f"/admin/users/{u['id']}").status_code == 200
    run()
    run()
    assert remote.users["r1"]["active"] is False and links(db, app) == []


def test_preview_links_and_tasks_endpoints(db, admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin))
    u = new_user(admin, "rae@example.com")
    pv = admin.get(f"/admin/provisioning-apps/{app['id']}/preview?user_id={u['id']}").json()
    assert pv["entitled"] is False and pv["resource"]["userName"] == "rae@example.com"
    assign_user(admin, app, u["id"])
    run()
    got = admin.get(f"/admin/provisioning-apps/{app['id']}/links?q=rae").json()
    assert got["total"] == 1 and got["items"][0]["state"] == "synced"
    assert admin.get(f"/admin/provisioning-apps/{app['id']}/links?q=zzz").json()["total"] == 0
    assert admin.get(f"/admin/provisioning-apps/{app['id']}/tasks?status=succeeded").json()["items"][0]["result"] == "created"
    d = admin.get(f"/admin/provisioning-apps/{app['id']}").json()
    assert d["provisioned"] == 1 and d["assigned_users"] == 1


def test_deleting_an_app_leaves_remote_accounts_alone(db, admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin))
    u = new_user(admin, "sol@example.com")
    assign_user(admin, app, u["id"])
    run()
    assert super_admin.delete(f"/admin/provisioning-apps/{app['id']}").status_code == 200
    assert remote.users["r1"]["active"] is True and links(db, app) == []


# ---- REST gateway ---------------------------------------------------------------------------------------------

class FakeRest:
    def __init__(self):
        self.calls, self.users = [], {}

    def __call__(self, req):
        body = json.loads(req.content) if req.content else None
        self.calls.append((req.method, req.url.path, body))
        if req.headers.get("x-api-key") != "k":
            return httpx.Response(401, json={"error": "no"})
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/users" and req.method == "GET":
            em = parse_qs(req.url.query.decode()).get("email", [""])[0]
            return httpx.Response(200, json={"items": [u for u in self.users.values() if u["email"] == em]})
        if req.url.path == "/api/users" and req.method == "POST":
            uid = 100 + len(self.users)
            self.users[str(uid)] = {**body, "id": uid}
            return httpx.Response(201, json={"id": uid})
        parts = req.url.path.split("/")
        if len(parts) >= 4 and parts[3] in self.users:
            uid = parts[3]
            if req.method == "PUT":
                self.users[uid].update(body)
            elif req.method == "POST" and parts[-1] == "deactivate":
                self.users[uid]["active"] = False
            elif req.method == "POST" and parts[-1] == "activate":
                self.users[uid]["active"] = True
            elif req.method == "DELETE":
                del self.users[uid]
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"error": "nope"})


def rest_cfg():
    from backend.app.provisioning.presets import REST_EXAMPLE
    cfg = json.loads(json.dumps(REST_EXAMPLE))
    cfg["test"]["path"] = "/api/health"
    for op in cfg.values():
        op["path"] = op["path"].replace("/users", "/api/users")
    return cfg


@pytest.fixture
def rest(monkeypatch, rkey):
    r = FakeRest()
    monkeypatch.setattr(adapters, "http_overrides", {"policy": EgressPolicy(), "resolver": public_resolver, "transport": httpx.MockTransport(r)})
    return r


def make_rest(sa, **over):
    return make_app(sa, name="Legacy", kind="rest", base_url="https://legacy.example.com", auth_type="header", header_name="X-API-Key",
                    secret="k", rest_config=rest_cfg(), **over)


def test_gateway_translates_provisioning_into_rest_calls(db, admin, super_admin, rest):
    app = enable(super_admin, make_rest(super_admin))
    u = new_user(admin, "tess@example.com")
    assign_user(admin, app, u["id"])
    run()
    (rec,) = rest.users.values()
    assert rec["email"] == "tess@example.com" and rec["first_name"] == "New" and rec["active"] is True   # boolean keeps its type
    assert links(db, app)[0].remote_id == "100"
    admin.patch(f"/admin/users/{u['id']}", {"profile_attributes": {"title": "Dir"}})
    run()
    assert rest.users["100"]["title"] == "Dir"
    admin.patch(f"/admin/users/{u['id']}", {"status": "suspended"})
    run()
    assert rest.users["100"]["active"] is False
    admin.patch(f"/admin/users/{u['id']}", {"status": "active"})
    run()
    assert rest.users["100"]["active"] is True and any(c[1].endswith("/activate") for c in rest.calls)


def test_gateway_config_is_validated(super_admin, rkey):
    bad = lambda cfg: super_admin.post("/admin/provisioning-apps", {"name": "g", "kind": "rest", "base_url": "https://x.example.com", "auth_type": "bearer", "secret": "t", "rest_config": cfg})  # noqa: E731
    assert bad({"create_user": {"method": "POST", "path": "/u", "id_path": "id"}}).status_code == 422                    # deactivate missing
    ok = {"create_user": {"method": "POST", "path": "/u", "id_path": "id"}, "deactivate_user": {"method": "POST", "path": "/u/{{id}}/off"}}
    assert bad(ok).status_code == 201
    assert bad({**ok, "delete_user": {"method": "DELETE", "path": "https://evil.example.com/x"}}).status_code == 422     # must stay on the host
    assert bad({**ok, "delete_user": {"method": "DELETE", "path": "/../admin"}}).status_code == 422
    assert bad({**ok, "delete_user": {"method": "TRACE", "path": "/x"}}).status_code == 422
    assert bad({**ok, "drop_db": {"method": "GET", "path": "/x"}}).status_code == 422
    assert bad({"create_user": {"method": "POST", "path": "/u"}, "deactivate_user": ok["deactivate_user"]}).status_code == 422   # id_path


def test_gateway_path_values_are_url_encoded(admin, super_admin, rest):
    app = enable(super_admin, make_rest(super_admin))
    u = new_user(admin, "x.y+z@example.com")
    assign_user(admin, app, u["id"])
    run()
    find = [c for c in rest.calls if c[0] == "GET" and c[1] == "/api/users"]
    assert find and rest.users["100"]["email"] == "x.y+z@example.com"
