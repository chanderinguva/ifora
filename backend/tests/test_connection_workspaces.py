"""Connection workspaces/auth: real API, database, worker and mocked external services."""
import base64
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
import httpx
import pytest
from backend.app.audit.model import AuditEvent
from backend.app.config import settings
from backend.app.groups.model import user_group_association
from backend.app.recipes import crypto, http_auth, openbao
from backend.app.recipes.models import RecipeConnection, ConnectionOAuthState
from backend.app.connectors import registry
from backend.app.connectors.scopes import action_available
from tests.conftest import Api, make_user
from tests.recipe_helpers import Remote, definition, dump, install_remote, jobs, make_recipe, new_group, rkey, run_worker, step, steps_of  # noqa: F401 (rkey is a pytest fixture)


def http_connection(admin, auth=None, secrets=None, **extra):
    body = {"name": "Custom", "allowed_host": "api.example.com", "config": auth or {"auth_type": "none"},
            "secrets": secrets or {}, "sharing_scope": "organization", **extra}
    r = admin.post("/admin/recipe-connections/http", body)
    assert r.status_code == 201, r.text
    return r.json()


def http_step(cid, body='{"note":"nonsecret"}', **extra):
    return step("request", "http_request", {"method": "POST", "url": "https://api.example.com/v1/do",
                "headers": {}, "body": body, "connection_id": cid, **extra})


def run_http(admin, db, cid, **extra):
    rid = make_recipe(admin, definition("manual", [http_step(cid, **extra)]))
    assert admin.post(f"/admin/recipes/{rid}/run", {}).status_code == 202
    run_worker()
    return jobs(db, rid)[0]


@pytest.mark.parametrize("auth,secret,header", [
    ({"auth_type": "none"}, {}, None),
    ({"auth_type": "bearer"}, {"token": "TOKEN_SENTINEL_1"}, "Bearer TOKEN_SENTINEL_1"),
    ({"auth_type": "basic"}, {"username": "service-user", "password": "PASSWORD_SENTINEL"}, "Basic " + base64.b64encode(b"service-user:PASSWORD_SENTINEL").decode()),
])
def test_http_authentication_is_encrypted_and_job_history_is_safe(admin, db, rkey, monkeypatch, auth, secret, header):
    remote = Remote([httpx.Response(200, json={"ok": True})])
    install_remote(monkeypatch, remote)
    conn = http_connection(admin, auth, secret)
    row = db.get(RecipeConnection, conn["id"])
    for value in secret.values():
        assert value not in row.secret_enc and value not in dump(conn)
    job = run_http(admin, db, conn["id"])
    assert job.status == "succeeded", job.error
    req = remote.requests[-1]
    assert req.headers.get("authorization") == header
    history = steps_of(db, job.id)[0]
    assert history.input["body"] == "[REDACTED]"
    assert all(value == "[REDACTED]" for value in history.input["headers"].values())
    blob = dump([history.input, history.output, history.error, job.definition, admin.get(f"/admin/recipes/{job.recipe_id}/export").json(),
                 [a.event_metadata for a in db.query(AuditEvent)]])
    for value in secret.values():
        assert value not in blob


@pytest.mark.parametrize("location,name", [("header", "X-Opaque"), ("query", "opaque"), ("json", "opaque"), ("form", "opaque")])
def test_arbitrary_secret_fields_are_injected_but_never_logged(admin, db, rkey, monkeypatch, location, name):
    secret = "credential-SENTINEL-xyz"
    remote = Remote([httpx.Response(200, json={"echo": secret})])
    install_remote(monkeypatch, remote)
    conn = http_connection(admin, {"auth_type": "custom", "bindings": [{"secret_key": "opaque", "location": location, "name": name}]}, {"opaque": secret})
    job = run_http(admin, db, conn["id"], body="note=test" if location == "form" else '{"note":"test"}')
    assert job.status == "succeeded", job.error
    req = remote.requests[-1]
    actual = req.headers[name] if location == "header" else parse_qs(urlsplit(str(req.url)).query)[name][0] if location == "query" else json.loads(req.content)[name] if location == "json" else parse_qs(req.content.decode())[name][0]
    assert actual == secret
    assert secret not in dump([job.definition, [(s.input, s.output, s.error) for s in steps_of(db, job.id)]])


@pytest.mark.parametrize("auth,sec", [
    ({"auth_type": "basic"}, {"username": "u"}),
    ({"auth_type": "api_key", "bindings": [{"secret_key": "key", "location": "header", "name": "Host"}]}, {"key": "x"}),
    ({"auth_type": "api_key", "bindings": [{"secret_key": "key", "location": "header", "name": "X\r\nInjected"}]}, {"key": "x"}),
    ({"auth_type": "bearer"}, {"token": "x\ny"}),
    ({"auth_type": "none"}, {"undeclared": "secret"}),
    ({"auth_type": "oauth2_client_credentials", "client_id": "x", "token_url": "http://localhost/token"}, {"client_secret": "x"}),
    ({"auth_type": "oauth2_client_credentials", "client_id": "x", "token_url": "https://issuer.example/token?client_secret=x"}, {"client_secret": "x"}),
    ({"auth_type": "oauth2_client_credentials", "client_id": "x", "client_auth": "none", "token_url": "https://issuer.example/token"}, {}),
])
def test_bad_auth_settings_fail_without_echoing_credentials(admin, rkey, auth, sec):
    r = admin.post("/admin/recipe-connections/http", {"name": "bad", "allowed_host": "api.example.com", "config": auth, "secrets": sec})
    assert r.status_code == 422
    assert "client_secret=x" not in r.text and "x\\ny" not in r.text


def test_new_http_recipe_refuses_literal_credentials(admin, rkey):
    c = http_connection(admin)
    for patch in ({"headers": {"Authorization": "RAW_SENTINEL"}}, {"body": '{"password":"RAW_SENTINEL"}'}, {"url": "https://api.example.com/v1?api_key=RAW_SENTINEL"}):
        r = admin.post("/admin/recipes", {"name": "bad", "definition": definition("manual", [http_step(c["id"], **patch)])})
        assert r.status_code == 422 and "RAW_SENTINEL" not in r.text


def test_credential_settings_changes_require_reentry(admin, db, rkey):
    c = http_connection(admin, {"auth_type": "bearer"}, {"token": "secret-1"})
    body = {"name": "Renamed", "allowed_host": "api.example.com", "config": c["config"], "sharing_scope": "organization"}
    before = db.get(RecipeConnection, c["id"]).secret_enc
    assert admin.put(f"/admin/recipe-connections/http/{c['id']}", body).status_code == 200
    assert admin.put(f"/admin/recipe-connections/http/{c['id']}", {**body, "allowed_host": "evil.example.com"}).status_code == 422
    db.expire_all()
    assert crypto.decrypt(db.get(RecipeConnection, c["id"]).secret_enc) == crypto.decrypt(before)


def test_folder_connection_requires_correct_recipe_folder(admin, rkey):
    f = admin.post("/admin/recipe-folders", {"name": "Operations"}).json()
    c = http_connection(admin, sharing_scope="folder", folder_ids=[f["id"]])
    d = definition("manual", [http_step(c["id"])])
    assert admin.post("/admin/recipes", {"name": "outside", "definition": d}).status_code == 422
    r = admin.post("/admin/recipes", {"name": "inside", "definition": d, "folder_id": f["id"]})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert admin.post(f"/admin/recipes/{rid}/publish").status_code == 200
    assert admin.put(f"/admin/recipes/{rid}", {"name": "moved", "folder_id": None}).status_code == 422


def test_group_roles_separate_connection_use_from_management(admin, super_admin, db, rkey):
    gid = new_group(super_admin, "Automation operators")
    user = make_user(db, "operator@example.com", admin=True)
    db.execute(user_group_association.insert().values(user_id=user.id, group_id=gid))
    db.commit()
    c = http_connection(admin, use_group_ids=[gid])
    other = Api()
    assert other.login(user.email).status_code == 200
    conn = next(x for x in other.get("/admin/recipe-connections").json()["items"] if x["id"] == c["id"])
    assert conn["can_use"] and not conn["can_manage"]
    assert other.put(f"/admin/recipe-connections/http/{c['id']}", {"name": "stolen", "allowed_host": c["allowed_host"], "config": c["config"]}).status_code == 403
    outsider = make_user(db, "outsider@example.com", admin=True)
    assert other.post(f"/admin/groups/{gid}/members", {"user_id": outsider.id}).status_code == 403


def test_revoking_group_use_stops_new_style_published_jobs(admin, super_admin, db, rkey, monkeypatch):
    gid = new_group(super_admin, "Operators")
    user = make_user(db, "operator@example.com", admin=True)
    db.execute(user_group_association.insert().values(user_id=user.id, group_id=gid))
    db.commit()
    c = http_connection(admin, use_group_ids=[gid])
    other = Api()
    assert other.login(user.email).status_code == 200
    rid = make_recipe(other, definition("manual", [http_step(c["id"])]))
    db.execute(user_group_association.delete().where(user_group_association.c.user_id == user.id))
    db.commit()
    remote = Remote()
    install_remote(monkeypatch, remote)
    assert other.post(f"/admin/recipes/{rid}/run", {}).status_code == 202
    run_worker()
    job = jobs(db, rid)[0]
    assert job.status == "failed" and not remote.requests and "permission" in job.error


def test_legacy_acl_is_not_broadened_by_editing(admin, db, rkey):
    c = admin.post("/admin/recipe-connections", {"name": "legacy", "kind": "bearer", "allowed_host": "api.example.com", "secret": "s", "allowed_users": [admin.user.id]}).json()
    assert c["sharing_scope"] == "legacy"
    assert admin.put(f"/admin/recipe-connections/{c['id']}", {"name": "renamed", "kind": "bearer", "allowed_host": "api.example.com"}).status_code == 200
    db.expire_all()
    assert db.get(RecipeConnection, c["id"]).allowed_users == [admin.user.id]


def test_slack_template_accepts_bot_and_requires_channel(admin, rkey):
    c = admin.post("/admin/connectors/slack/connections", {"name": "Slack", "secrets": {"token": "xoxb-sentinel"}}).json()
    body = {"template_id": "failed-login-slack", "name": "Alert", "params": {"connection": c["id"], "min_failures": 3}}
    assert admin.post("/admin/recipes/from-template", body).status_code == 422
    body["params"]["channel"] = "C012345"
    r = admin.post("/admin/recipes/from-template", body)
    assert r.status_code == 201, r.text
    cfg = r.json()["draft"]["steps"][0]["config"]
    assert cfg["action"] == "post_message" and cfg["inputs"]["channel"] == "C012345"


def test_slack_scope_discovery_and_action_permissions(admin, rkey, monkeypatch, db):
    remote = Remote([httpx.Response(200, json={"ok": True}, headers={"x-oauth-scopes": "chat:write,channels:read"})])
    install_remote(monkeypatch, remote)
    c = admin.post("/admin/connectors/slack/connections", {"name": "Slack", "secrets": {"token": "xoxb-sentinel"}}).json()
    assert admin.post(f"/admin/recipe-connections/{c['id']}/test").json()["ok"]
    got = next(x for x in admin.get("/admin/recipe-connections").json()["items"] if x["id"] == c["id"])
    assert got["granted_scopes"] == ["channels:read", "chat:write"]
    denied = step("s", "connector_action", {"connector": "slack", "connection_id": c["id"], "action": "create_channel", "inputs": {"name": "ops"}})
    assert admin.post("/admin/recipes", {"name": "missing scope", "definition": definition("manual", [denied])}).status_code == 422
    a = registry.action_of(registry.get("slack"), "create_channel")
    assert action_available(a, ["groups:write"], {"is_private": "true"})
    assert not action_available(a, [], {})
    assert action_available(a, None, {})  # unknown is explicitly different from verified empty


def test_oauth_start_binds_pkce_and_expires_state(admin, rkey, monkeypatch, db):
    monkeypatch.setattr(settings, "RECIPE_OAUTH_CALLBACK_URL", "https://ifora.example/api/v1/admin/recipe-connections/oauth/callback")
    c = http_connection(admin, {"auth_type": "oauth2_authorization_code", "client_id": "client", "client_auth": "none", "token_url": "https://issuer.example/token", "authorization_url": "https://issuer.example/authorize"})
    r = admin.post(f"/admin/recipe-connections/{c['id']}/oauth/start")
    assert r.status_code == 200, r.text
    q = parse_qs(urlsplit(r.json()["authorization_url"]).query)
    assert q["code_challenge_method"] == ["S256"]
    row = db.query(ConnectionOAuthState).one()
    verifier = crypto.decrypt(row.verifier_enc)
    assert verifier not in r.text and q["state"][0] not in row.id
    import hashlib
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == [challenge]
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert admin.get("/admin/recipe-connections/oauth/callback?state=" + q["state"][0] + "&code=x").status_code == 400


def test_oauth_callback_is_one_use_and_tokens_stay_encrypted(admin, rkey, monkeypatch, db):
    monkeypatch.setattr(settings, "RECIPE_OAUTH_CALLBACK_URL", "https://ifora.example/api/v1/admin/recipe-connections/oauth/callback")
    c = http_connection(admin, {"auth_type": "oauth2_authorization_code", "client_id": "client", "client_auth": "none", "token_url": "https://issuer.example/token", "authorization_url": "https://issuer.example/authorize"})
    q = parse_qs(urlsplit(admin.post(f"/admin/recipe-connections/{c['id']}/oauth/start").json()["authorization_url"]).query)
    calls = []
    def exchange(config, sec, form, **kwargs):
        calls.append(form)
        return {**sec, "access_token": "ACCESS_SENTINEL", "refresh_token": "REFRESH_SENTINEL", "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}, ["read"]
    monkeypatch.setattr(http_auth, "token_request", exchange)
    callback = "/admin/recipe-connections/oauth/callback?state=" + q["state"][0] + "&code=CODE_SENTINEL"
    r = admin.get(callback)
    assert r.status_code == 200, r.text
    assert admin.get(callback).status_code == 400 and len(calls) == 1
    assert "code_verifier" in calls[0]
    db.expire_all()
    row = db.get(RecipeConnection, c["id"])
    assert "ACCESS_SENTINEL" not in row.secret_enc
    assert "REFRESH_SENTINEL" not in dump([admin.get("/admin/recipe-connections").json(), [a.event_metadata for a in db.query(AuditEvent)]])


def test_openbao_failure_never_falls_back_to_local_encryption(rkey, monkeypatch):
    monkeypatch.setattr(settings, "RECIPE_SECRET_PROVIDER", "openbao")
    def fail(*args, **kwargs):
        raise openbao.VaultUnavailable("upstream secret details must not leak")
    monkeypatch.setattr(openbao, "encrypt", fail)
    with pytest.raises(crypto.RecipeKeyError) as error:
        crypto.encrypt("plaintext")
    assert "upstream" not in str(error.value)


def test_openbao_ciphertext_cannot_be_read_by_fernet_fallback(rkey, monkeypatch):
    def fail(*args, **kwargs):
        raise openbao.VaultUnavailable("unavailable")
    monkeypatch.setattr(openbao, "decrypt", fail)
    with pytest.raises(crypto.RecipeKeyError):
        crypto.decrypt("openbao:vault:v1:opaque")


def test_oauth_client_credentials_uses_separate_pinned_token_host(admin, db, rkey, monkeypatch):
    remote = Remote([httpx.Response(200, json={"access_token": "ACCESS_SENTINEL", "token_type": "Bearer", "expires_in": 3600, "scope": "read"}),
                     httpx.Response(200, json={"echo": "ACCESS_SENTINEL"})])
    install_remote(monkeypatch, remote)
    cfg = {"auth_type": "oauth2_client_credentials", "client_id": "client", "token_url": "https://issuer.example/token", "scope": "read"}
    c = http_connection(admin, cfg, {"client_secret": "CLIENT_SENTINEL"})
    job = run_http(admin, db, c["id"])
    assert job.status == "succeeded", job.error
    assert remote.requests[0].headers["host"] == "issuer.example"
    assert remote.requests[1].headers["authorization"] == "Bearer ACCESS_SENTINEL"
    assert remote.requests[0].headers["authorization"] == "Basic " + base64.b64encode(b"client:CLIENT_SENTINEL").decode()
    assert "CLIENT_SENTINEL" not in remote.requests[0].content.decode()
    blob = dump([(s.input, s.output, s.error) for s in steps_of(db, job.id)])
    assert "ACCESS_SENTINEL" not in blob and "CLIENT_SENTINEL" not in blob


def test_refresh_token_rotation_is_encrypted_and_never_enters_history(admin, db, rkey, monkeypatch):
    c = http_connection(admin, {"auth_type": "oauth2_authorization_code", "client_id": "public", "client_auth": "none",
                               "token_url": "https://issuer.example/token", "authorization_url": "https://issuer.example/authorize"})
    row = db.get(RecipeConnection, c["id"])
    row.secret_enc = crypto.encrypt(json.dumps({"access_token": "EXPIRED_TOKEN", "refresh_token": "OLD_REFRESH",
                                                "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()}))
    db.commit()
    remote = Remote([httpx.Response(200, json={"access_token": "NEW_ACCESS", "refresh_token": "NEW_REFRESH", "token_type": "Bearer", "expires_in": 3600}),
                     httpx.Response(200, json={"echo": "NEW_ACCESS"})])
    install_remote(monkeypatch, remote)
    job = run_http(admin, db, c["id"])
    assert job.status == "succeeded", job.error
    assert parse_qs(remote.requests[0].content.decode())["refresh_token"] == ["OLD_REFRESH"]
    db.expire_all()
    saved = http_auth.values(db.get(RecipeConnection, c["id"]))
    assert saved["refresh_token"] == "NEW_REFRESH"
    assert not any(s in dump([(x.input, x.output, x.error) for x in steps_of(db, job.id)]) for s in ("OLD_REFRESH", "NEW_REFRESH", "NEW_ACCESS"))


def test_http_connections_block_wrong_host_and_plain_http(admin, db, rkey, monkeypatch):
    c = http_connection(admin, {"auth_type": "bearer"}, {"token": "SENTINEL"})
    remote = Remote()
    install_remote(monkeypatch, remote)
    for i, url in enumerate(("https://evil.example/v1", "http://api.example.com/v1", "https://api.example.com:8443/v1")):
        rid = make_recipe(admin, definition("manual", [http_step(c["id"], url=url)]), name="Boundary " + str(i))
        assert admin.post(f"/admin/recipes/{rid}/run", {}).status_code == 202
        run_worker()
        assert jobs(db, rid)[0].status == "failed"
    assert not remote.requests


def test_prebuilt_host_change_cannot_forward_a_saved_credential(admin, rkey):
    r = admin.post("/admin/connectors/jira/connections", {"name": "Jira", "config": {"site": "company", "username": "bot@example.com"}, "secrets": {"password": "SENTINEL"}})
    assert r.status_code == 201
    changed = admin.put(f"/admin/connectors/jira/connections/{r.json()['id']}", {"name": "Jira", "config": {"site": "attacker", "username": "bot@example.com"}})
    assert changed.status_code == 422 and "Re-enter" in changed.text


def test_oauth_state_cannot_be_used_by_another_administrator(admin, db, rkey, monkeypatch):
    monkeypatch.setattr(settings, "RECIPE_OAUTH_CALLBACK_URL", "https://ifora.example/api/v1/admin/recipe-connections/oauth/callback")
    c = http_connection(admin, {"auth_type": "oauth2_authorization_code", "client_id": "public", "client_auth": "none",
                               "token_url": "https://issuer.example/token", "authorization_url": "https://issuer.example/authorize"})
    q = parse_qs(urlsplit(admin.post(f"/admin/recipe-connections/{c['id']}/oauth/start").json()["authorization_url"]).query)
    user = make_user(db, "other-admin@example.com", admin=True)
    other = Api()
    other.login(user.email)
    callback = "/admin/recipe-connections/oauth/callback?state=" + q["state"][0] + "&error=access_denied"
    assert other.get(callback).status_code == 400
    assert db.query(ConnectionOAuthState).count() == 1
    assert admin.get(callback).status_code == 400
    db.expire_all()
    assert db.query(ConnectionOAuthState).count() == 0


def test_oauth_codes_and_state_are_removed_from_access_logs():
    import logging
    from backend.app.recipes.oauth_logs import OAuthAccessFilter
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s %s %s %s %s",
                               ("127.0.0.1", "GET", "/api/v1/admin/recipe-connections/oauth/callback?code=CODE_SECRET&state=STATE_SECRET", "1.1", 200), None)
    OAuthAccessFilter().filter(record)
    assert "CODE_SECRET" not in record.getMessage() and "STATE_SECRET" not in record.getMessage()


def test_folder_connection_management_follows_current_manager_groups(admin, super_admin, db, rkey):
    gid = new_group(super_admin, "Folder managers")
    user = make_user(db, "folder-manager@example.com", admin=True)
    db.execute(user_group_association.insert().values(user_id=user.id, group_id=gid))
    db.commit()
    f = admin.post("/admin/recipe-folders", {"name": "Scoped", "manage_group_ids": [gid]}).json()
    other = Api()
    other.login(user.email)
    c = http_connection(other, sharing_scope="folder", folder_ids=[f["id"]])
    assert next(x for x in other.get("/admin/recipe-connections").json()["items"] if x["id"] == c["id"])["can_manage"]
    db.execute(user_group_association.delete().where(user_group_association.c.user_id == user.id))
    db.commit()
    after = next(x for x in other.get("/admin/recipe-connections").json()["items"] if x["id"] == c["id"])
    assert not after["can_manage"] and not after["can_use"]
    assert other.put(f"/admin/recipe-connections/http/{c['id']}", {"name": "escape", "allowed_host": "api.example.com", "config": c["config"], "sharing_scope": "organization", "folder_ids": []}).status_code == 403
