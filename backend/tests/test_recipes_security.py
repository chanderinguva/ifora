"""Recipe engine security: SSRF, secrets, webhook auth, template resolver (ADR 008 threat model)."""

import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from cryptography.fernet import Fernet

from backend.app.audit.model import AuditEvent
from backend.app.config import settings
from backend.app.recipes import actions, crypto, templates as tpl
from backend.app.recipes.http_client import (
    EgressBlocked, EgressPolicy, HttpFailure, ResponseTooLarge, ip_allowed, safe_request,
)
from backend.app.recipes.models import RecipeConnection
from backend.app.recipes.redact import REDACTED, redact
from backend.app.recipes.routes import sign_webhook
from tests.recipe_helpers import (
    PUBLIC_IP, Remote, definition, dump, install_remote, jobs, make_recipe, new_user, rkey, run_worker, step, steps_of,  # noqa: F401
)

PUB = lambda host, port: [PUBLIC_IP]  # noqa: E731


def req(url, remote=None, resolver=PUB, policy=None, **kw):
    remote = remote or Remote()
    return safe_request("GET", url, policy=policy or EgressPolicy(), resolver=resolver, transport=remote.transport, **kw), remote


# ---- SSRF -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("ip", [
    "127.0.0.1", "127.1.2.3", "10.0.0.5", "172.16.0.1", "172.31.255.255", "192.168.1.1", "169.254.169.254",
    "169.254.0.1", "0.0.0.0", "100.64.0.1", "100.100.100.200", "192.0.0.1", "198.18.0.1", "224.0.0.1", "255.255.255.255",
    "::1", "::", "fe80::1", "fd00::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254",
    "64:ff9b::7f00:1", "2002:7f00:1::", "ff02::1",
])
def test_private_and_special_addresses_blocked(ip):
    assert not ip_allowed(ip, EgressPolicy())
    host = f"[{ip}]" if ":" in ip else ip
    with pytest.raises(EgressBlocked):
        req(f"http://{host}/")


@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_allowed(ip):
    assert ip_allowed(ip, EgressPolicy())


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/", "gopher://example.com/", "javascript:alert(1)", "//example.com/",
    "http://user:pw@example.com/", "http://example.com@127.0.0.1/", "http:///path", "https://", "http://example.com:22/",
    "http://example.com:6379/", "http://exa mple.com/", "http://example.com/\r\nX: y", "",
])
def test_bad_urls_blocked(url):
    with pytest.raises(EgressBlocked):
        req(url)


@pytest.mark.parametrize("resolved", [["127.0.0.1"], ["10.1.2.3"], ["169.254.169.254"], ["::1"], ["93.184.216.34", "10.0.0.1"], ["::ffff:7f00:1"]])
def test_hostname_resolving_to_private_is_blocked(resolved):
    remote = Remote()
    with pytest.raises(EgressBlocked):
        req("http://innocent.example.com/", remote, resolver=lambda h, p: resolved)
    assert remote.requests == []  # nothing was sent


def test_localhost_names_blocked():
    import socket

    for host in ("localhost", "localhost.localdomain"):
        with pytest.raises((EgressBlocked, HttpFailure)):
            safe_request("GET", f"http://{host}/", policy=EgressPolicy(), transport=Remote().transport)


def test_dns_rebinding_connection_is_pinned_to_validated_ip():
    answers = [["93.184.216.34"], ["127.0.0.1"]]  # second lookup would be the rebind
    calls = []

    def resolver(h, p):
        calls.append(h)
        return answers[min(len(calls) - 1, 1)]

    res, remote = req("https://rebind.example.com/x?y=1", resolver=resolver)
    assert len(calls) == 1  # resolved exactly once
    (r,) = remote.requests
    assert r.url.host == "93.184.216.34" and r.headers["host"] == "rebind.example.com"
    assert r.extensions["sni_hostname"] == "rebind.example.com"
    assert str(r.url).endswith("/x?y=1")


def test_ipv6_literal_pinned_and_allowed_only_when_public():
    res, remote = req("http://[2606:4700:4700::1111]/", resolver=lambda h, p: pytest.fail("no DNS for literals"))
    assert remote.requests[0].url.host == "2606:4700:4700::1111"


def test_redirects_are_not_followed():
    remote = Remote([httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"}), httpx.Response(200, text="SECRET")])
    res, remote = req("https://example.com/", remote)
    assert res.status == 302 and res.headers["location"].startswith("http://169.254")
    assert len(remote.requests) == 1


def test_oversized_response_rejected_and_small_ok():
    big = Remote([httpx.Response(200, content=b"x" * 5000)])
    with pytest.raises(ResponseTooLarge):
        req("https://example.com/", big, max_bytes=1000)
    ok, _ = req("https://example.com/", Remote([httpx.Response(200, content=b"x" * 900)]), max_bytes=1000)
    assert len(ok.body) == 900


def test_timeout_is_a_retryable_failure_and_request_body_capped():
    def boom(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(HttpFailure):
        safe_request("GET", "https://example.com/", policy=EgressPolicy(), resolver=PUB, transport=httpx.MockTransport(boom))
    with pytest.raises(EgressBlocked):
        req_body = safe_request("POST", "https://example.com/", body=b"x" * 70000, policy=EgressPolicy(), resolver=PUB, transport=Remote().transport)


def test_dangerous_headers_and_methods_refused():
    for h in ({"Host": "evil"}, {"Content-Length": "1"}, {"Transfer-Encoding": "chunked"}, {"Proxy-Authorization": "x"}, {"X": "a\r\nB: c"}, {"bad name": "v"}):
        with pytest.raises(EgressBlocked):
            safe_request("GET", "https://example.com/", h, policy=EgressPolicy(), resolver=PUB, transport=Remote().transport)
    with pytest.raises(EgressBlocked):
        safe_request("CONNECT", "https://example.com/", policy=EgressPolicy(), resolver=PUB, transport=Remote().transport)


def test_allowed_host_list(monkeypatch):
    p = EgressPolicy(allowed_hosts=frozenset({"api.good.com"}))
    req("https://api.good.com/", policy=p)
    with pytest.raises(EgressBlocked):
        req("https://api.evil.com/", policy=p)
    monkeypatch.setattr(settings, "RECIPES_HTTP_ALLOWED_HOSTS", "a.com, b.com")
    assert EgressPolicy.from_settings().allowed_hosts == frozenset({"a.com", "b.com"})


def test_production_policy_cannot_be_relaxed_by_settings():
    p = EgressPolicy.from_settings()
    assert p.allow_private is False and 22 not in p.allowed_ports


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/hello":
            body = b'{"hi": 1}'
            self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)
        elif self.path == "/redir":
            self.send_response(302); self.send_header("location", "http://169.254.169.254/"); self.end_headers()
        elif self.path == "/big":
            self.send_response(200); self.end_headers(); self.wfile.write(b"x" * 300000)
        elif self.path == "/slow":
            time.sleep(2); self.send_response(200); self.end_headers()


@pytest.fixture
def loopback():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def test_real_sockets_against_loopback_only_with_injected_policy(loopback):
    url = f"http://127.0.0.1:{loopback}"
    with pytest.raises(EgressBlocked):  # production policy refuses it
        safe_request("GET", url + "/hello")
    lab = EgressPolicy(allow_private=True, allowed_ports=None)
    assert safe_request("GET", url + "/hello", policy=lab).body == b'{"hi": 1}'
    r = safe_request("GET", url + "/redir", policy=lab)
    assert r.status == 302  # not followed to 169.254.169.254
    with pytest.raises(ResponseTooLarge):
        safe_request("GET", url + "/big", policy=lab, max_bytes=1000)
    with pytest.raises(HttpFailure):
        safe_request("GET", url + "/slow", policy=lab, timeout=0.5)


def test_step_blocks_internal_target_and_records_it(db, admin, monkeypatch):
    install_remote(monkeypatch, Remote(), resolver=lambda h, p: ["169.254.169.254"])
    rid = make_recipe(admin, definition("user.created", [step("call", "http_request", {"method": "GET", "url": "https://metadata.example.com/"})]))
    new_user(admin)
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "failed" and "non-public" in j.error and j.attempt == 0  # not retried


# ---- secrets ------------------------------------------------------------------------------------------------

SECRET = "sk_live_SUPER_SECRET_VALUE_123"


def make_conn(admin, host="api.partner.com", **kw):
    body = {"name": "partner", "kind": "bearer", "allowed_host": host, "secret": SECRET, **kw}
    r = admin.post("/admin/recipe-connections", body)
    assert r.status_code == 201, r.text
    return r.json()


def test_connections_need_their_own_key(admin, monkeypatch):
    assert admin.post("/admin/recipe-connections", {"name": "c", "kind": "bearer", "allowed_host": "a.com", "secret": "x"}).status_code == 409
    assert admin.get("/admin/recipes/status").json()["connections_available"] is False
    monkeypatch.setattr(settings, "RECIPE_ENCRYPTION_KEY", settings.MFA_ENCRYPTION_KEY)
    assert not crypto.available()
    monkeypatch.setattr(settings, "RECIPE_ENCRYPTION_KEY", settings.OIDC_KEY_ENCRYPTION_KEY)
    assert not crypto.available()
    monkeypatch.setattr(settings, "RECIPE_ENCRYPTION_KEY", "not-a-key")
    assert not crypto.available()


def test_secret_never_returned_and_encrypted_at_rest(db, admin, rkey):
    c = make_conn(admin)
    assert SECRET not in dump(c) and c["has_secret"] is True and "secret" not in c
    assert SECRET not in admin.get("/admin/recipe-connections").text
    assert SECRET not in admin.put(f"/admin/recipe-connections/{c['id']}", {"name": "partner", "kind": "bearer", "allowed_host": "api.partner.com"}).text
    db.expire_all()
    row = db.get(RecipeConnection, c["id"])
    assert SECRET not in row.secret_enc and crypto.decrypt(row.secret_enc) == SECRET
    assert Fernet(rkey.encode()).decrypt(row.secret_enc.encode()).decode() == SECRET
    # audit trail has the event but not the secret
    assert SECRET not in dump([a.event_metadata for a in db.query(AuditEvent).all()])
    assert admin.put(f"/admin/recipe-connections/{c['id']}", {"name": "partner", "kind": "bearer", "allowed_host": "api.partner.com", "secret": "rotated"}).status_code == 200
    db.expire_all()
    assert crypto.decrypt(db.get(RecipeConnection, c["id"]).secret_enc) == "rotated"
    assert admin.delete(f"/admin/recipe-connections/{c['id']}").status_code == 200


def test_connection_validation(admin, rkey):
    base = {"name": "c", "kind": "bearer", "allowed_host": "api.a.com", "secret": "x"}
    for bad in ({"allowed_host": "https://api.a.com"}, {"allowed_host": "a.com/path"}, {"allowed_host": "a.com:8080"},
                {"kind": "header"}, {"kind": "header", "header_name": "Host"}, {"secret": "a\nb"}, {"kind": "basic"}):
        assert admin.post("/admin/recipe-connections", {**base, **bad}).status_code == 422, bad


def test_secret_injected_but_never_stored_logged_or_echoed(db, admin, rkey, monkeypatch, capsys):
    c = make_conn(admin)
    remote = Remote([httpx.Response(200, json={"echo": f"Bearer {SECRET}", "access_token": "tok-from-remote", "fine": "yes"})])
    install_remote(monkeypatch, remote)
    refused = admin.post("/admin/recipes", {"name": "No pasted query credentials", "definition": definition("user.created", [
        step("call", "http_request", {"method": "POST", "url": "https://api.partner.com/v1/users?api_key=URLKEY", "connection_id": c["id"]})])})
    assert refused.status_code == 422 and "URLKEY" not in refused.text
    rid = make_recipe(admin, definition("user.created", [
        step("call", "http_request", {"method": "POST", "url": "https://api.partner.com/v1/users?x=1",
                                       "headers": {"Authorization": "literal-token", "X-Trace": "t"}, "body": "{}", "connection_id": c["id"]}),
        step("after", "log", {"message": "fine={{steps.call.output.json.fine}}"}),
    ]))
    new_user(admin)
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "succeeded", j.error
    assert remote.requests[0].headers["authorization"] == f"Bearer {SECRET}"  # it really is sent to the right host
    detail = admin.get(f"/admin/recipes/jobs/{j.id}")
    blob = detail.text + dump([(s.input, s.output, s.error) for s in steps_of(db, j.id)]) + dump(j.step_outputs) + dump(j.trigger) + dump(j.definition)
    for needle in (SECRET, "literal-token", "tok-from-remote", "URLKEY"):
        assert needle not in blob, needle
    body = detail.json()
    assert body["steps"][0]["input"]["headers"]["Authorization"] == REDACTED
    assert body["steps"][0]["input"]["headers"]["X-Trace"] == "t" and body["steps"][1]["output"]["message"] == "fine=yes"
    assert SECRET not in dump([a.event_metadata for a in db.query(AuditEvent).all()])
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err


def test_connection_is_bound_to_its_host(db, admin, rkey, monkeypatch):
    c = make_conn(admin)
    remote = Remote()
    install_remote(monkeypatch, remote)
    rid = make_recipe(admin, definition("user.created", [step("call", "http_request", {"method": "GET", "url": "https://attacker.example.net/", "connection_id": c["id"]})]))
    new_user(admin)
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "failed" and "may only be used for api.partner.com" in j.error
    assert remote.requests == []  # the secret never left


def test_redactor_covers_nested_keys():
    out = redact({"a": {"Authorization": "x", "list": [{"api-key": "y", "ok": 1}], "client_secret": "z", "passwordHash": "p"}})
    assert out["a"]["Authorization"] == REDACTED and out["a"]["list"][0] == {"api-key": REDACTED, "ok": 1}
    assert out["a"]["client_secret"] == REDACTED and out["a"]["passwordHash"] == REDACTED


# ---- templates ---------------------------------------------------------------------------------------------------

CTX = {"trigger": {"user": {"id": 7, "email": "a@b.c", "attributes": {"department": "Sales"}}, "list": ["x", "y"]},
       "steps": {"s1": {"output": {"v": True}}}, "recipe": {"id": 1}, "job": {"id": 9}}


def test_template_substitution_and_types():
    assert tpl.render("mail {{ trigger.user.email }}!", CTX) == "mail a@b.c!"
    assert tpl.render("{{trigger.user.id}}", CTX) == 7  # whole pill keeps its type
    assert tpl.render("id={{trigger.user.id}}", CTX) == "id=7"
    assert tpl.render("{{steps.s1.output.v}}", CTX) is True
    assert tpl.render("{{trigger.list.1}}", CTX) == "y"
    assert tpl.render("{{trigger.user.attributes.department}}", CTX) == "Sales"
    assert tpl.render("plain", CTX) == "plain"


@pytest.mark.parametrize("bad", [
    "{{trigger.__class__}}", "{{trigger.user.__class__.__mro__}}", "{{trigger._private}}", "{{__builtins__}}", "{{os.system}}",
    "{{settings.SECRET_KEY}}", "{{config}}", "{{trigger.user.email|upper}}", "{{ 1+1 }}", "{{trigger.user.email()}}",
    "{{trigger.user['email']}}","{{trigger.user.email", "trigger}}", "{{{{trigger.user.id}}}}", "{{trigger..user}}",
    "{{trigger.user.email;rm}}", "{{trigger.user.id + 1}}", "${trigger.user.id}{{", "{{steps}}", "{{trigger}}x{{}}",
])
def test_templates_cannot_execute_or_escape(bad):
    with pytest.raises(tpl.TemplateError):
        tpl.render(bad, CTX)


def test_other_template_syntaxes_are_just_text():
    assert tpl.render("{% if x %} ${y} #{z}", CTX) == "{% if x %} ${y} #{z}"


def test_resolver_only_walks_data_not_objects():
    class Evil:
        secret = "boom"

    ctx = {"trigger": {"obj": Evil()}}
    with pytest.raises(tpl.TemplateError):
        tpl.render("{{trigger.obj.secret}}", ctx)  # not a dict: no attribute access
    for path in ("trigger.user.nope", "trigger.list.9", "trigger.user.id.real"):
        with pytest.raises(tpl.TemplateError):
            tpl.render("{{%s}}" % path, CTX)
    with pytest.raises(tpl.TemplateError):
        tpl.render("{{secrets.token}}", CTX)  # root not allow-listed


def test_definition_rejects_forward_and_unknown_pills(admin):
    def post(msg, steps=None):
        return admin.post("/admin/recipes", {"name": "n" + str(time.time()), "definition": definition("user.created", steps or [step("s1", "log", {"message": msg})])})

    assert post("{{trigger.user.__class__}}").status_code == 422
    assert post("{{steps.s2.output.x}}").status_code == 422
    assert post("{{steps.s1.output.message}}").status_code == 422  # a step cannot read its own output
    assert post("{{trigger.group.name}}").status_code == 422  # not provided by this trigger
    assert post("{{1+1}}").status_code == 422
    assert post("{{trigger.user.email}}").status_code == 201
    assert post("x", [step("s1", "log", {"message": "a"}), step("s2", "log", {"message": "{{steps.s1.output.message}}"})]).status_code == 201


def test_definition_structure_limits(admin):
    many = [step(f"s{i}", "log", {"message": "x"}) for i in range(31)]
    assert admin.post("/admin/recipes", {"name": "many", "definition": definition("manual", many)}).status_code == 422
    dup = [step("s1", "log", {"message": "x"}), step("s1", "log", {"message": "y"})]
    assert admin.post("/admin/recipes", {"name": "dup", "definition": definition("manual", dup)}).status_code == 422
    nest = step("c4", "log", {"message": "x"})
    for i in (3, 2, 1, 0):
        nest = step(f"c{i}", "condition", {"match": "all", "conditions": [{"left": "trigger.event.type", "operator": "is_set"}]}, then=[nest])
    assert admin.post("/admin/recipes", {"name": "deep", "definition": definition("manual", [nest])}).status_code == 422
    assert admin.post("/admin/recipes", {"name": "extra", "definition": {"trigger": {"type": "manual", "config": {}}, "steps": [], "code": "x"}}).status_code == 422
    assert admin.post("/admin/recipes", {"name": "ev", "definition": definition("manual", [step("s1", "log", {"message": "x", "eval": "1"})])}).status_code == 422


# ---- inbound webhook -----------------------------------------------------------------------------------------------

def hook_recipe(admin, rkey_, steps=None, name="hook"):
    r = admin.post("/admin/recipes", {"name": name, "definition": definition("webhook", steps or [step("l", "log", {"message": "got {{trigger.payload.who}}"})])})
    rid = r.json()["id"]
    p = admin.post(f"/admin/recipes/{rid}/publish")
    assert p.status_code == 200, p.text
    admin.post(f"/admin/recipes/{rid}/enable")
    return rid, p.json()["webhook_secret"], p.json()["webhook_path"]


def post_hook(anon, path, secret, payload, ts=None, sig=None, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    ts = str(int(time.time())) if ts is None else str(ts)
    sig = sig if sig is not None else "v1=" + sign_webhook(secret, ts, body)
    return anon.c.post(path, content=body, headers={"X-IdentityForge-Timestamp": ts, "X-IdentityForge-Signature": sig, "Content-Type": "application/json"})


def test_webhook_accepts_the_new_ifora_headers_and_the_legacy_ones(db, admin, anon, rkey):
    rid, secret, path = hook_recipe(admin, rkey)
    body = json.dumps({"x": 1}).encode()
    ts = str(int(time.time()))
    sig = "v1=" + sign_webhook(secret, ts, body)
    new = anon.c.post(path, content=body, headers={"X-Ifora-Timestamp": ts, "X-Ifora-Signature": sig, "Content-Type": "application/json"})
    assert new.status_code in (200, 202), new.text
    old = anon.c.post(path, content=body, headers={"X-IdentityForge-Timestamp": ts, "X-IdentityForge-Signature": sig, "Content-Type": "application/json"})
    assert old.status_code in (200, 202), old.text
    bad = anon.c.post(path, content=body, headers={"X-Ifora-Timestamp": ts, "X-Ifora-Signature": "v1=" + "0" * 64, "Content-Type": "application/json"})
    assert bad.status_code == 401


def test_webhook_happy_path_and_secret_shown_once(db, admin, anon, rkey):
    rid, secret, path = hook_recipe(admin, rkey)
    assert secret not in admin.get(f"/admin/recipes/{rid}").text and secret not in admin.get("/admin/recipes").text
    r = post_hook(anon, path, secret, {"who": "pager"})
    assert r.status_code == 200 and r.json()["accepted"] is True
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "succeeded" and steps_of(db, j.id)[0].output["message"] == "got pager"
    assert db.query(AuditEvent).filter(AuditEvent.action == "RECIPE_WEBHOOK_RECEIVED").count() == 1
    # the stored secret is encrypted
    from backend.app.recipes.models import Recipe

    db.expire_all()
    assert secret not in db.get(Recipe, rid).webhook_secret_enc
    new = admin.post(f"/admin/recipes/{rid}/webhook-secret").json()["webhook_secret"]
    assert new != secret
    assert post_hook(anon, path, secret, {"who": "old"}).status_code == 401  # rotated away
    assert post_hook(anon, path, new, {"who": "new"}).status_code == 200


def test_webhook_signature_checks(db, admin, anon, rkey, monkeypatch):
    rid, secret, path = hook_recipe(admin, rkey)
    assert post_hook(anon, path, "wrong-secret", {"who": "x"}).status_code == 401
    assert post_hook(anon, path, secret, {"who": "x"}, sig="v1=" + "0" * 64).status_code == 401
    assert post_hook(anon, path, secret, {"who": "x"}, sig="sha256=abc").status_code == 401
    assert anon.c.post(path, content=b"{}").status_code == 401  # no headers
    body = b'{"who": "x"}'
    ts = str(int(time.time()))
    good = "v1=" + sign_webhook(secret, ts, body)
    tampered = anon.c.post(path, content=b'{"who": "y"}', headers={"X-IdentityForge-Timestamp": ts, "X-IdentityForge-Signature": good})
    assert tampered.status_code == 401
    assert post_hook(anon, path, secret, {"who": "x"}, ts=int(time.time()) - 3600).status_code == 401  # stale
    assert post_hook(anon, path, secret, {"who": "x"}, ts=int(time.time()) + 3600).status_code == 401  # future
    assert post_hook(anon, path, secret, None, ts="abc").status_code == 401
    assert jobs(db, rid) == []
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr("backend.app.recipes.routes.hmac.compare_digest", lambda a, b: calls.append(1) or real(a, b))
    post_hook(anon, path, secret, {"who": "x"})
    assert calls  # constant-time comparison is used


def test_webhook_replay_is_deduplicated(db, admin, anon, rkey):
    rid, secret, path = hook_recipe(admin, rkey)
    body = b'{"who": "once"}'
    ts = str(int(time.time()))
    sig = "v1=" + sign_webhook(secret, ts, body)
    h = {"X-IdentityForge-Timestamp": ts, "X-IdentityForge-Signature": sig}
    a, b = anon.c.post(path, content=body, headers=h), anon.c.post(path, content=body, headers=h)
    assert a.status_code == 200 and b.status_code == 200 and b.json()["duplicate"] is True
    run_worker()
    assert len(jobs(db, rid)) == 1


def test_webhook_limits_and_availability(db, admin, anon, rkey):
    rid, secret, path = hook_recipe(admin, rkey)
    big = json.dumps({"who": "x" * 70000}).encode()
    assert post_hook(anon, path, secret, None, raw=big).status_code == 413
    assert post_hook(anon, path, secret, None, raw=b"not json").status_code == 422
    assert post_hook(anon, path, secret, None, raw=b"[1,2]").status_code == 422
    assert post_hook(anon, "/api/v1/hooks/recipes/doesnotexist", secret, {}).status_code == 404
    admin.post(f"/admin/recipes/{rid}/disable")
    assert post_hook(anon, path, secret, {"who": "x"}).status_code == 404
    admin.post(f"/admin/recipes/{rid}/enable")
    assert post_hook(anon, path, secret, {"who": "x"}).status_code == 200
    assert jobs(db, rid)[0].trigger["payload"] == {"who": "x"}


def test_webhook_unavailable_without_key(admin):
    r = admin.post("/admin/recipes", {"name": "h", "definition": definition("webhook", [step("l", "log", {"message": "x"})])}).json()
    assert admin.post(f"/admin/recipes/{r['id']}/publish").status_code == 409


def test_webhook_trigger_filter(db, admin, anon, rkey):
    r = admin.post("/admin/recipes", {"name": "hf", "definition": definition(
        "webhook", [step("l", "log", {"message": "x"})], flt=[{"left": "trigger.payload.env", "operator": "equals", "value": "prod"}])})
    rid = r.json()["id"]
    path = admin.post(f"/admin/recipes/{rid}/publish").json()
    secret, path = path["webhook_secret"], path["webhook_path"]
    admin.post(f"/admin/recipes/{rid}/enable")
    assert post_hook(anon, path, secret, {"env": "dev"}).json() == {"accepted": False}
    assert post_hook(anon, path, secret, {"env": "prod"}).json()["accepted"] is True


def test_job_history_redacts_webhook_payload_keys(db, admin, anon, rkey):
    rid, secret, path = hook_recipe(admin, rkey)
    post_hook(anon, path, secret, {"who": "a", "api_key": "PAYLOAD-KEY"})
    run_worker()
    (j,) = jobs(db, rid)
    assert "PAYLOAD-KEY" not in admin.get(f"/admin/recipes/jobs/{j.id}").text
