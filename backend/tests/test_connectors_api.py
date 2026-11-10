"""Connector API and recipe integration (ADR 026): catalog, connections, test button, a real recipe job, and the safety boundaries."""

import httpx
import pytest

from backend.app.audit.model import AuditEvent
from backend.app.recipes.models import RecipeConnection
from tests.recipe_helpers import Remote, definition, dump, install_remote, jobs, make_recipe, rkey, run_worker, step, steps_of  # noqa: F401

TOKEN = "ghp_SUPER_SECRET_TOKEN_123"


@pytest.fixture(autouse=True)
def _remote(monkeypatch, rkey):
    r = Remote([httpx.Response(200, json={"login": "octocat", "id": 7, "name": "Octo"})])
    install_remote(monkeypatch, r)
    return r


def connect(admin, name="gh", **kw):
    body = {"name": name, "config": {"org": "acme"}, "secrets": {"token": TOKEN}, **kw}
    r = admin.post("/admin/connectors/github/connections", body)
    assert r.status_code == 201, r.text
    return r.json()


def test_catalog_lists_github_without_secrets(admin):
    r = admin.get("/admin/connectors")
    assert r.status_code == 200
    (gh,) = [c for c in r.json()["items"] if c["id"] == "github"]
    assert {a["id"] for a in gh["actions"]} >= {"get_user", "add_team_member", "remove_org_member"}
    assert TOKEN not in dump(r.json()) and admin.get("/admin/connectors/github").status_code == 200
    assert admin.get("/admin/connectors/nope").status_code == 404


def test_create_connection_never_returns_or_stores_the_secret_in_clear(admin, db):
    c = connect(admin)
    assert c["connector_id"] == "github" and c["config"] == {"org": "acme"} and c["allowed_host"] == "api.github.com"
    assert TOKEN not in dump(c)
    row = db.get(RecipeConnection, c["id"])
    assert row.kind == "connector" and TOKEN not in row.secret_enc and TOKEN not in dump([c.get("config") for c in [row.__dict__]])
    assert TOKEN not in dump(admin.get("/admin/recipe-connections").json())
    assert TOKEN not in dump([a.event_metadata for a in db.query(AuditEvent).all()])


@pytest.mark.parametrize("config,secrets", [
    ({"org": "a/b"}, {"token": TOKEN}), ({"org": "acme"}, {}), ({}, {"token": TOKEN}), ({"org": "acme", "host": "evil.example"}, {"token": TOKEN}),
    ({"org": "acme"}, {"token": "a\r\nb"}),
])
def test_create_validates_config_and_secrets(admin, config, secrets):
    r = admin.post("/admin/connectors/github/connections", {"name": "x", "config": config, "secrets": secrets})
    assert r.status_code == 422, r.text
    assert TOKEN not in r.text


def test_duplicate_name_is_a_conflict(admin):
    connect(admin)
    r = admin.post("/admin/connectors/github/connections", {"name": "gh", "config": {"org": "acme"}, "secrets": {"token": TOKEN}})
    assert r.status_code == 409


def test_test_button_reports_success_and_failure_and_is_audited(admin, db, _remote):
    c = connect(admin)
    r = admin.post(f"/admin/recipe-connections/{c['id']}/test")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["status_code"] == 200
    (req,) = _remote.requests
    assert str(req.url.path) == "/orgs/acme" and req.headers["authorization"] == f"Bearer {TOKEN}"
    _remote.responses = [httpx.Response(401)]
    r2 = admin.post(f"/admin/recipe-connections/{c['id']}/test")
    assert r2.status_code == 200 and r2.json()["ok"] is False and TOKEN not in r2.text
    rows = db.query(AuditEvent).filter(AuditEvent.action == "RECIPE_CONNECTION_TESTED").all()
    assert len(rows) == 2 and TOKEN not in dump([a.event_metadata for a in rows])


def test_secret_rotation_keeps_or_replaces_the_stored_secret(admin, db, _remote):
    c = connect(admin)
    before = db.get(RecipeConnection, c["id"]).secret_enc
    r = admin.put(f"/admin/connectors/github/connections/{c['id']}", {"name": "gh2", "config": {"org": "acme2"}})
    assert r.status_code == 200 and r.json()["name"] == "gh2"
    db.expire_all()
    assert db.get(RecipeConnection, c["id"]).secret_enc == before
    admin.post(f"/admin/recipe-connections/{c['id']}/test")
    assert str(_remote.requests[-1].url.path) == "/orgs/acme2" and _remote.requests[-1].headers["authorization"] == f"Bearer {TOKEN}"
    assert admin.put(f"/admin/connectors/github/connections/{c['id']}", {"name": "gh2", "config": {"org": "acme2"}, "secrets": {"token": "NEW_TOKEN_9"}}).status_code == 200
    db.expire_all()
    assert db.get(RecipeConnection, c["id"]).secret_enc != before
    admin.post(f"/admin/recipe-connections/{c['id']}/test")
    assert _remote.requests[-1].headers["authorization"] == "Bearer NEW_TOKEN_9"


def test_generic_connection_endpoints_cannot_edit_connector_connections(admin):
    c = connect(admin)
    r = admin.put(f"/admin/recipe-connections/{c['id']}", {"name": "x", "kind": "bearer", "allowed_host": "evil.example", "secret": "s"})
    assert r.status_code == 409


def go(db, admin, steps):
    rid = make_recipe(admin, definition("manual", steps))
    assert admin.post(f"/admin/recipes/{rid}/run", {}).status_code in (200, 201, 202)
    run_worker()
    (j,) = jobs(db, rid)
    return rid, j, steps_of(db, j.id)


def gh_step(cid, action="get_user", inputs=None, sid="gh"):
    return step(sid, "connector_action", {"connector": "github", "connection_id": cid, "action": action, "inputs": inputs or {"username": "octocat"}})


def test_recipe_runs_a_connector_action_and_later_steps_use_its_outputs(admin, db, _remote):
    c = connect(admin)
    _, j, ss = go(db, admin, [gh_step(c["id"]), step("l", "log", {"message": "login={{steps.gh.output.login}} id={{steps.gh.output.id}}"})])
    assert j.status == "succeeded", j.error
    out = {s.step_id: s.output for s in ss}
    assert out["gh"]["login"] == "octocat" and out["gh"]["status_code"] == 200
    assert out["l"]["message"] == "login=octocat id=7"
    assert TOKEN not in dump([s.output for s in ss]) and TOKEN not in dump([s.input for s in ss if hasattr(s, "input")])
    assert db.query(AuditEvent).filter(AuditEvent.action == "CONNECTOR_ACTION_CALLED").count() == 1
    assert TOKEN not in dump([a.event_metadata for a in db.query(AuditEvent).all()])


def test_a_failing_action_fails_the_step_with_the_definition_message(admin, db, _remote):
    c = connect(admin)
    _remote.responses = [httpx.Response(404, json={"message": "Not Found"})]
    _, j, ss = go(db, admin, [gh_step(c["id"])])
    assert j.status == "failed" and "No GitHub account" in dump([s.error for s in ss])


def test_build_time_checks_reject_bad_connector_steps(admin):
    c = connect(admin)
    bad = {
        "unknown connector": {"connector": "nope", "connection_id": c["id"], "action": "get_user", "inputs": {"username": "o"}},
        "unknown action": {"connector": "github", "connection_id": c["id"], "action": "nope", "inputs": {}},
        "missing connection": {"connector": "github", "connection_id": 99999, "action": "get_user", "inputs": {"username": "o"}},
        "missing required input": {"connector": "github", "connection_id": c["id"], "action": "get_user", "inputs": {}},
        "undeclared input": {"connector": "github", "connection_id": c["id"], "action": "get_user", "inputs": {"username": "o", "url": "x"}},
        "bad literal": {"connector": "github", "connection_id": c["id"], "action": "get_user", "inputs": {"username": "../etc"}},
    }
    for name, cfg in bad.items():
        r = admin.post("/admin/recipes", {"name": name, "definition": definition("manual", [step("gh", "connector_action", cfg)])})
        if r.status_code == 201:
            r = admin.post(f"/admin/recipes/{r.json()['id']}/publish")
        assert r.status_code == 422, (name, r.status_code, r.text)


def test_http_request_refuses_connector_connections(admin):
    c = connect(admin)
    r = admin.post("/admin/recipes", {"name": "h", "definition": definition("manual", [
        step("h", "http_request", {"connection_id": c["id"], "method": "GET", "path": "/orgs/acme"})])})
    if r.status_code == 201:
        r = admin.post(f"/admin/recipes/{r.json()['id']}/publish")
    assert r.status_code == 422, r.text


def test_connection_in_use_cannot_be_deleted(admin):
    c = connect(admin)
    make_recipe(admin, definition("manual", [gh_step(c["id"])]), publish=True, enable=False)
    r = admin.delete(f"/admin/recipe-connections/{c['id']}")
    assert r.status_code == 409, r.text
    unused = connect(admin, name="unused")
    assert admin.delete(f"/admin/recipe-connections/{unused['id']}").status_code in (200, 204)


def test_editor_meta_offers_the_step_and_the_connector_catalog(admin):
    r = admin.get("/admin/recipes/meta")
    assert r.status_code == 200, r.text
    assert "connector_action" in [x["type"] for x in r.json()["steps"]]
    ids = {c["id"] for c in r.json()["connectors"]}
    assert {"github", "jira", "slack", "pagerduty", "entra"} <= ids
    gh = next(c for c in r.json()["connectors"] if c["id"] == "github")
    add = next(a for a in gh["actions"] if a["id"] == "add_team_member")
    assert "state" in add["outputs"] and any(i["key"] == "role" and i["type"] == "select" for i in add["inputs"])


def test_jira_connection_uses_basic_auth_against_its_site_host(admin, db, _remote):
    import base64

    r = admin.post("/admin/connectors/jira/connections", {"name": "jira", "config": {"site": "acme", "username": "bot@example.com"}, "secrets": {"password": "ATATT_TOKEN_1"}})
    assert r.status_code == 201, r.text
    assert r.json()["allowed_host"] == "acme.atlassian.net" and "ATATT_TOKEN_1" not in r.text
    assert admin.post(f"/admin/recipe-connections/{r.json()['id']}/test").json()["ok"] is True
    (req,) = _remote.requests
    assert req.headers["host"] == "acme.atlassian.net" and str(req.url.path) == "/rest/api/3/myself"
    assert req.headers["authorization"] == "Basic " + base64.b64encode(b"bot@example.com:ATATT_TOKEN_1").decode()
    assert "ATATT_TOKEN_1" not in dump([a.event_metadata for a in db.query(AuditEvent).all()])
    bad = admin.post("/admin/connectors/jira/connections", {"name": "j2", "config": {"site": "evil.com/x", "username": "bot@example.com"}, "secrets": {"password": "t"}})
    assert bad.status_code == 422


def test_entra_connection_runs_in_a_recipe_with_a_fetched_token(admin, db, monkeypatch):
    from backend.app.connectors import engine as ce

    ce._token_cache.clear()
    tenant, client = "11111111-2222-3333-4444-555555555555", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    remote = Remote([httpx.Response(200, json={"access_token": "GRAPH_ACCESS_TOKEN", "expires_in": 3599}),
                     httpx.Response(200, json={"id": "u1", "displayName": "Ann", "accountEnabled": True})])
    install_remote(monkeypatch, remote)
    r = admin.post("/admin/connectors/entra/connections", {"name": "entra", "config": {"tenant": tenant, "client_id": client}, "secrets": {"client_secret": "CLIENT_SECRET_XYZ"}})
    assert r.status_code == 201, r.text
    assert r.json()["allowed_host"] == "graph.microsoft.com" and "CLIENT_SECRET_XYZ" not in r.text
    bad = admin.post("/admin/connectors/entra/connections", {"name": "e2", "config": {"tenant": "x/../y", "client_id": client}, "secrets": {"client_secret": "s"}})
    assert bad.status_code == 422
    step_cfg = {"connector": "entra", "connection_id": r.json()["id"], "action": "get_user", "inputs": {"user": "ann@contoso.com"}}
    _, j, ss = go(db, admin, [step("e", "connector_action", step_cfg), step("l", "log", {"message": "{{steps.e.output.display_name}}"})])
    assert j.status == "succeeded", j.error
    assert [s.output["message"] for s in ss if s.step_id == "l"] == ["Ann"]
    blob = dump([s.output for s in ss]) + dump([a.event_metadata for a in db.query(AuditEvent).all()])
    assert "GRAPH_ACCESS_TOKEN" not in blob and "CLIENT_SECRET_XYZ" not in blob
    assert [q.headers["host"] for q in remote.requests] == ["login.microsoftonline.com", "graph.microsoft.com"]
    ce._token_cache.clear()


def test_members_cannot_reach_the_connector_api(member):
    assert member.get("/admin/connectors").status_code in (401, 403)
    assert member.post("/admin/connectors/github/connections", {"name": "x", "config": {"org": "acme"}, "secrets": {"token": "t"}}).status_code in (401, 403)
