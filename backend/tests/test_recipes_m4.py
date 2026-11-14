"""R-M4: allow-listed paths, OAuth2 client-credentials connections, Slack and email steps."""

import json
from urllib.parse import parse_qs

import httpx
import pytest

from backend.app.audit.model import AuditEvent
from backend.app.config import settings
from backend.app import mailer
from backend.app.recipes import actions
from tests.recipe_helpers import (  # noqa: F401
    Remote, definition, install_remote, jobs, make_recipe, new_user, rkey, run_worker, step, steps_of,
)

HOST = "api.partner.com"
CLIENT_SECRET = "cs-very-secret-value"
HOOK = "https://hooks.slack.com/services/T000/B000/XXXXSECRETXXXX"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    actions._token_cache.clear()
    monkeypatch.setattr(mailer, "overrides", {})
    yield
    actions._token_cache.clear()


def conn(admin, **kw):
    body = {"name": "c", "kind": "bearer", "allowed_host": HOST, "secret": "plain-bearer-secret", **kw}
    r = admin.post("/admin/recipe-connections", body)
    assert r.status_code == 201, r.text
    return r.json()


def oauth(admin, **kw):
    return conn(admin, name="oauth", kind="oauth2_client_credentials", secret=CLIENT_SECRET, client_id="cid",
                token_url=f"https://{HOST}/oauth/token", scope="read", **kw)


def http_step(url, cid, method="GET"):
    return step("call", "http_request", {"method": method, "url": url, "connection_id": cid})


def run_manual(admin, steps, name="r"):
    rid = make_recipe(admin, definition("manual", steps), name=name)
    assert admin.post(f"/admin/recipes/{rid}/run", {}).status_code == 202
    run_worker()
    return rid


def last_job(db, rid):
    (j,) = jobs(db, rid)
    return j


# ---- allowed paths --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("url,ok", [
    (f"https://{HOST}/v1/users", True),
    (f"https://{HOST}/v1/users/5?x=1", True),
    (f"https://{HOST}/v1/usersx", False),
    (f"https://{HOST}/v2/users", False),
    (f"https://{HOST}/v1/users/../admin", False),
    (f"https://{HOST}/v1/users/%2e%2e/admin", False),
    (f"https://{HOST}/v1/users%2fx", False),
    (f"https://{HOST}/v1/users//x", False),
    (f"https://{HOST}/", False),
])
def test_allowed_paths_are_enforced(db, admin, rkey, monkeypatch, url, ok):
    remote = Remote()
    install_remote(monkeypatch, remote)
    c = conn(admin, allowed_paths=["/v1/users"])
    rid = run_manual(admin, [http_step(url, c["id"])])
    j = last_job(db, rid)
    assert (j.status == "succeeded") is ok, j.error
    assert len(remote.requests) == (1 if ok else 0)
    if not ok:
        assert "path" in j.error


def test_no_path_list_means_any_path_and_prefix_with_slash(db, admin, rkey, monkeypatch):
    remote = Remote()
    install_remote(monkeypatch, remote)
    c = conn(admin)
    assert last_job(db, run_manual(admin, [http_step(f"https://{HOST}/anything/at/all", c["id"])])).status == "succeeded"
    d = conn(admin, name="d", allowed_paths=["/api/"])
    assert last_job(db, run_manual(admin, [http_step(f"https://{HOST}/api/x", d["id"])], name="r2")).status == "succeeded"


def test_allowed_path_validation(admin, rkey):
    for bad in (["v1"], ["/a b"], ["/a/../b"], ["/a?x=1"], ["/a#f"], ["/a%2fb"], ["/a//b"], ["/" + "x" * 250], ["/x"] * 21):
        r = admin.post("/admin/recipe-connections", {"name": "p", "kind": "bearer", "allowed_host": HOST, "secret": "s", "allowed_paths": bad})
        assert r.status_code == 422, bad
    ok = conn(admin, name="ok", allowed_paths=["/b", "/a", "/a"])
    assert ok["allowed_paths"] == ["/a", "/b"]


# ---- OAuth2 client credentials ----------------------------------------------------------------------------------------

def test_oauth2_fetches_a_token_uses_it_and_caches_it(db, admin, rkey, monkeypatch):
    remote = Remote([httpx.Response(200, json={"access_token": "tok-abc", "expires_in": 3600, "token_type": "Bearer"}),
                     httpx.Response(200, json={"ok": True})])
    install_remote(monkeypatch, remote)
    c = oauth(admin, allowed_paths=["/v1"])
    rid = run_manual(admin, [http_step(f"https://{HOST}/v1/things", c["id"])])
    j = last_job(db, rid)
    assert j.status == "succeeded", j.error
    token_req, api_req = remote.requests
    assert token_req.headers["host"] == HOST and token_req.url.path == "/oauth/token"
    form = {k: v[0] for k, v in parse_qs(token_req.content.decode()).items()}
    assert form == {"grant_type": "client_credentials", "client_id": "cid", "client_secret": CLIENT_SECRET, "scope": "read"}
    assert api_req.headers["authorization"] == "Bearer tok-abc"
    # second job: cached token, no new token request
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    assert len(remote.requests) == 3 and remote.requests[2].headers["authorization"] == "Bearer tok-abc"
    # nothing sensitive reaches history or audit
    blob = json.dumps([[s.input, s.output] for jb in jobs(db, rid) for s in steps_of(db, jb.id)], default=str)
    blob += json.dumps([a.event_metadata for a in db.query(AuditEvent).all()], default=str)
    assert CLIENT_SECRET not in blob and "tok-abc" not in blob


def test_editing_the_connection_drops_the_cached_token(db, admin, rkey, monkeypatch):
    remote = Remote([httpx.Response(200, json={"access_token": "t1"}), httpx.Response(200, json={}),
                     httpx.Response(200, json={"access_token": "t2"}), httpx.Response(200, json={})])
    install_remote(monkeypatch, remote)
    c = oauth(admin)
    rid = run_manual(admin, [http_step(f"https://{HOST}/v1/x", c["id"])])
    assert admin.put(f"/admin/recipe-connections/{c['id']}", {"name": "oauth", "kind": "oauth2_client_credentials", "allowed_host": HOST,
                     "client_id": "cid", "token_url": f"https://{HOST}/oauth/token", "secret": "rotated"}).status_code == 200
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    assert [r.headers.get("authorization") for r in remote.requests if r.url.path == "/v1/x"] == ["Bearer t1", "Bearer t2"]


def test_oauth2_refused_credentials_fail_without_leaking(db, admin, rkey, monkeypatch):
    remote = Remote([httpx.Response(401, json={"error": "invalid_client", "echo": CLIENT_SECRET})])
    install_remote(monkeypatch, remote)
    c = oauth(admin)
    j = last_job(db, run_manual(admin, [http_step(f"https://{HOST}/v1/x", c["id"])]))
    assert j.status == "failed" and "refused the credentials" in j.error and CLIENT_SECRET not in j.error
    assert len(remote.requests) == 1


def test_oauth2_validation(admin, rkey):
    base = {"name": "o", "kind": "oauth2_client_credentials", "allowed_host": HOST, "secret": "s", "client_id": "cid",
            "token_url": f"https://{HOST}/t"}
    for bad in ({"client_id": None}, {"token_url": None}, {"token_url": f"http://{HOST}/t"}, {"token_url": "https://evil.example/t"},
                {"token_url": f"https://u:p@{HOST}/t"}):
        assert admin.post("/admin/recipe-connections", {**base, **bad}).status_code == 422, bad
    assert admin.post("/admin/recipe-connections", base).status_code == 201


# ---- Slack -------------------------------------------------------------------------------------------------------------

def slack_conn(admin, **kw):
    return conn(admin, name="slack", kind="slack_webhook", secret=HOOK, allowed_host="ignored.example", **kw)


def test_slack_message_is_posted_escaped_and_the_webhook_stays_secret(db, admin, rkey, monkeypatch):
    remote = Remote([httpx.Response(200, text="ok")])
    install_remote(monkeypatch, remote)
    c = slack_conn(admin)
    assert c["allowed_host"] == "hooks.slack.com" and HOOK not in json.dumps(c)
    rid = make_recipe(admin, definition("manual", [step("n", "send_slack", {"connection_id": c["id"], "message": "hi <!channel> & <https://x|click> {{recipe.name}}"})]))
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    j = last_job(db, rid)
    assert j.status == "succeeded", j.error
    (req,) = remote.requests
    assert req.headers["host"] == "hooks.slack.com" and req.url.path == "/services/T000/B000/XXXXSECRETXXXX"
    assert json.loads(req.content)["text"] == "hi &lt;!channel&gt; &amp; &lt;https://x|click&gt; Recipe 1"
    blob = json.dumps([[s.input, s.output] for s in steps_of(db, j.id)], default=str) + json.dumps([a.event_metadata for a in db.query(AuditEvent).all()], default=str)
    assert "SECRET" not in blob


def test_slack_failures(db, admin, rkey, monkeypatch):
    remote = Remote([httpx.Response(404, text="no_service")])
    install_remote(monkeypatch, remote)
    c = slack_conn(admin)
    j = last_job(db, run_manual(admin, [step("n", "send_slack", {"connection_id": c["id"], "message": "x"})]))
    assert j.status == "failed" and "404" in j.error and "XXXXSECRETXXXX" not in j.error


def test_slack_connection_rules(admin, rkey):
    base = {"name": "s", "kind": "slack_webhook", "secret": HOOK}
    assert admin.post("/admin/recipe-connections", {**base, "secret": "https://evil.example/hook"}).status_code == 422
    assert admin.post("/admin/recipe-connections", {**base, "allowed_paths": ["/x"]}).status_code == 422
    c = slack_conn(admin)
    plain = conn(admin, name="plain")
    # the Slack step needs a Slack connection, and a Slack connection cannot be used for arbitrary HTTP
    for steps in ([step("n", "send_slack", {"connection_id": plain["id"], "message": "x"})],
                  [step("n", "http_request", {"method": "POST", "url": "https://hooks.slack.com/services/T/B/x", "connection_id": c["id"]})]):
        r = admin.post("/admin/recipes", {"name": "bad", "definition": definition("manual", steps)})
        assert r.status_code in (201, 422)
        if r.status_code == 201:
            assert admin.post(f"/admin/recipes/{r.json()['id']}/publish").status_code == 422


# ---- email -------------------------------------------------------------------------------------------------------------

@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "overrides", {"send": sent.append})
    monkeypatch.setattr(settings, "SMTP_FROM", "noreply@idp.example")
    monkeypatch.setattr(settings, "SMTP_FROM_NAME", "")   # the stack's own sender name must not leak into the From assertions
    monkeypatch.setattr(settings, "RECIPES_EMAIL_ALLOWED_DOMAINS", "")
    return sent


def mail_step(to, subject="Hello", body="Body text"):
    return step("m", "send_email", {"to": to, "subject": subject, "body": body})


def test_email_to_an_active_user(db, admin, outbox):
    new_user(admin, "pat@example.com")
    j = last_job(db, run_manual(admin, [mail_step("Pat@Example.com", "Welcome {{recipe.name}}")]))
    assert j.status == "succeeded", j.error
    (m,) = outbox
    assert m["To"] == "pat@example.com" and m["Subject"] == "Welcome r" and m["From"] == "noreply@idp.example"
    assert m.get_content().strip() == "Body text"


def test_email_recipient_policy(db, admin, outbox, monkeypatch):
    j = last_job(db, run_manual(admin, [mail_step("outsider@elsewhere.example")]))
    assert j.status == "failed" and "allowed email domain" in j.error and outbox == []
    monkeypatch.setattr(settings, "RECIPES_EMAIL_ALLOWED_DOMAINS", "elsewhere.example, other.example")
    admin.post(f"/admin/recipes/{j.recipe_id}/run", {})
    run_worker()
    assert len(outbox) == 1 and outbox[0]["To"] == "outsider@elsewhere.example"


@pytest.mark.parametrize("to", ["a@b.example, c@d.example", "a@b.example\nBcc: x@y.example", "not-an-address", "a b@c.example", "<a@b.example>"])
def test_email_rejects_malformed_or_multiple_recipients(db, admin, outbox, monkeypatch, to):
    monkeypatch.setattr(settings, "RECIPES_EMAIL_ALLOWED_DOMAINS", "b.example,c.example,d.example")
    j = last_job(db, run_manual(admin, [mail_step(to)]))
    assert j.status == "failed" and outbox == []


def test_email_subject_cannot_inject_headers(db, admin, outbox, monkeypatch):
    new_user(admin, "pat@example.com")
    j = last_job(db, run_manual(admin, [mail_step("pat@example.com", "Hi\nBcc: attacker@evil.example")]))
    assert j.status == "failed" and "one non-empty line" in j.error and outbox == []


def test_email_cap_per_job_and_dry_run_and_unconfigured(db, admin, outbox, monkeypatch):
    new_user(admin, "pat@example.com")
    monkeypatch.setattr(settings, "RECIPES_MAX_EMAILS_PER_JOB", 1)
    steps = [mail_step("pat@example.com"), step("m2", "send_email", {"to": "pat@example.com", "subject": "2", "body": "2"})]
    j = last_job(db, run_manual(admin, steps))
    assert j.status == "failed" and "at most 1 emails" in j.error and len(outbox) == 1
    outbox.clear()
    rid = admin.post("/admin/recipes", {"name": "dry", "definition": definition("manual", [mail_step("pat@example.com")])}).json()["id"]
    r = admin.post(f"/admin/recipes/{rid}/test", {})
    assert r.json()["status"] == "succeeded" and outbox == []
    monkeypatch.setattr(mailer, "overrides", {})
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    assert admin.get("/admin/recipes/status").json()["email_available"] is False
    j2 = last_job(db, run_manual(admin, [mail_step("pat@example.com")], name="r3"))
    assert j2.status == "failed" and "not configured" in j2.error


def test_email_transient_failures_retry(db, admin, outbox, monkeypatch):
    import smtplib
    new_user(admin, "pat@example.com")
    calls = []

    def flaky(msg):
        calls.append(1)
        if len(calls) == 1:
            raise smtplib.SMTPServerDisconnected("boom")
        outbox.append(msg)

    monkeypatch.setattr(mailer, "overrides", {"send": flaky})
    rid = make_recipe(admin, definition("manual", [step("m", "send_email", {"to": "pat@example.com", "subject": "s", "body": "b"}, max_attempts=3)]))
    admin.post(f"/admin/recipes/{rid}/run", {})
    from datetime import timedelta
    from backend.app.recipes import engine
    run_worker()
    run_worker(engine.utcnow() + timedelta(minutes=5))
    assert len(calls) == 2 and len(outbox) == 1
