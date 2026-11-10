"""Microsoft Entra ID connector and the OAuth2 client-credentials scheme."""

import copy
import json
from urllib.parse import parse_qs

import httpx
import pytest
import yaml

from backend.app.connectors import engine as ce
from backend.app.connectors import registry
from backend.app.connectors.schema import DefinitionInvalid, validate_connector
from backend.app.recipes.http_client import EgressPolicy
from tests.recipe_helpers import Remote, public_resolver

E = registry.get("entra")
TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CONFIG = {"tenant": TENANT, "client_id": CLIENT}
SECRETS = {"client_secret": "CLIENT~SECRET~VALUE"}
TOKEN = "eyJ.ACCESS.TOKEN"
UID = "99999999-8888-7777-6666-555555555555"
GID = "12345678-1234-1234-1234-123456789012"
GOOD = {"user": "ann@contoso.com", "user_id": UID, "group_id": GID, "email": "ann@contoso.com", "name": "Staff"}


@pytest.fixture(autouse=True)
def _clear():
    ce._token_cache.clear()
    yield
    ce._token_cache.clear()


def tok(**kw):
    return httpx.Response(200, json={"access_token": TOKEN, "expires_in": 3599, "token_type": "Bearer", **kw})


def act(aid):
    return registry.action_of(E, aid)


def required(aid):
    return {i.key: GOOD[i.key] for i in act(aid).inputs if i.required}


def run(aid, inputs, *responses):
    ce._token_cache.clear()
    remote = Remote(list(responses))
    res = ce.run_action(E, act(aid), "entra", CONFIG, SECRETS, inputs, dry=False, policy=EgressPolicy(), resolver=public_resolver, transport=remote.transport)
    return res, remote


def test_token_request_and_graph_call():
    res, remote = run("get_user", required("get_user"), tok(), httpx.Response(200, json={"id": UID, "displayName": "Ann", "accountEnabled": True}))
    t, g = remote.requests
    assert t.method == "POST" and t.headers["host"] == "login.microsoftonline.com" and str(t.url.path) == f"/{TENANT}/oauth2/v2.0/token"
    form = parse_qs(t.content.decode())
    assert form == {"grant_type": ["client_credentials"], "client_id": [CLIENT], "client_secret": ["CLIENT~SECRET~VALUE"], "scope": ["https://graph.microsoft.com/.default"]}
    assert g.headers["host"] == "graph.microsoft.com" and g.headers["authorization"] == f"Bearer {TOKEN}"
    assert str(g.url.path) == "/v1.0/users/ann@contoso.com" and res.outputs["account_enabled"] is True and res.outputs["user_id"] == UID


def test_token_is_cached_and_a_rotated_secret_gets_a_new_one():
    remote = Remote([tok(), httpx.Response(200, json={}), httpx.Response(200, json={}), tok(), httpx.Response(200, json={})])
    kw = dict(dry=False, policy=EgressPolicy(), resolver=public_resolver, transport=remote.transport)
    ce.run_action(E, act("get_user"), "e", CONFIG, SECRETS, required("get_user"), **kw)
    ce.run_action(E, act("get_user"), "e", CONFIG, SECRETS, required("get_user"), **kw)
    assert [r.headers["host"] for r in remote.requests] == ["login.microsoftonline.com", "graph.microsoft.com", "graph.microsoft.com"]
    ce.run_action(E, act("get_user"), "e", CONFIG, {"client_secret": "ROTATED"}, required("get_user"), **kw)
    assert [r.headers["host"] for r in remote.requests][3:] == ["login.microsoftonline.com", "graph.microsoft.com"]


def test_token_failures_do_not_echo_remote_text_and_are_retryable_only_when_transient():
    body = {"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret provided. Trace ID: abc"}
    with pytest.raises(ce.ConnectorError) as e:
        run("get_user", required("get_user"), httpx.Response(401, json=body))
    assert "AADSTS" not in e.value.message and "refused the client id, secret or tenant" in e.value.message and e.value.retryable is False
    for status in (429, 503):
        with pytest.raises(ce.ConnectorError) as e:
            run("add_group_member", required("add_group_member"), httpx.Response(status))
        assert e.value.retryable is True                    # nothing has reached the API yet, so even a non-idempotent action may retry
    for weird in (httpx.Response(200, json={"access_token": "a\r\nb"}), httpx.Response(200, json={}), httpx.Response(200, text="x")):
        with pytest.raises(ce.ConnectorError):
            run("get_user", required("get_user"), weird)


def test_token_never_leaks_into_results():
    res, _ = run("get_user", required("get_user"), tok(), httpx.Response(200, json={"id": UID, "displayName": TOKEN}))
    assert TOKEN not in json.dumps(res.outputs) and TOKEN not in json.dumps(res.request) and "CLIENT~SECRET" not in json.dumps(res.request)
    dry = ce.run_action(E, act("get_user"), "e", CONFIG, {}, required("get_user"), dry=True, policy=EgressPolicy(), resolver=public_resolver, transport=Remote().transport)
    assert dry.outputs["dry_run"] is True


def test_tenant_cannot_move_the_token_request():
    for bad in ("../x", "a/b", "a?x=1", "a b", "a\nb", "", "x"):
        with pytest.raises(ce.ConnectorError):
            ce.validate_config(E, {**CONFIG, "tenant": bad}, SECRETS)
    ce.validate_config(E, {**CONFIG, "tenant": "contoso.onmicrosoft.com"}, SECRETS)
    remote = Remote([tok(), httpx.Response(200, json={})])
    ce.run_action(E, act("get_user"), "e", {**CONFIG, "tenant": "contoso.onmicrosoft.com"}, SECRETS, required("get_user"), dry=False, policy=EgressPolicy(),
                  resolver=public_resolver, transport=remote.transport)
    assert str(remote.requests[0].url.path) == "/contoso.onmicrosoft.com/oauth2/v2.0/token" and remote.requests[0].headers["host"] == "login.microsoftonline.com"


def test_private_address_for_the_token_host_is_blocked():
    with pytest.raises(ce.ConnectorError) as e:
        ce.run_action(E, act("get_user"), "e", CONFIG, SECRETS, required("get_user"), dry=False, policy=EgressPolicy(), resolver=lambda h, p: ["10.0.0.9"],
                      transport=Remote().transport)
    assert "blocked" in e.value.message


def test_connection_test_is_the_token_request_only():
    remote = Remote([tok()])
    ok, status, _ = ce.check_connection(E, CONFIG, SECRETS, policy=EgressPolicy(), resolver=public_resolver, transport=remote.transport)
    assert ok and status == 200 and len(remote.requests) == 1
    ce._token_cache.clear()
    ok, _, msg = ce.check_connection(E, CONFIG, SECRETS, policy=EgressPolicy(), resolver=public_resolver, transport=Remote([httpx.Response(401, json={"error_description": "AADSTS1"})]).transport)
    assert not ok and "AADSTS" not in msg and "CLIENT~SECRET" not in msg


def test_request_shapes():
    _, r = run("find_user_by_email", required("find_user_by_email"), tok(), httpx.Response(200, json={"value": [{"id": UID}]}))
    assert r.requests[1].url.params["$filter"] == "mail eq 'ann@contoso.com'" and r.requests[1].url.params["$top"] == "5"
    _, r = run("find_group", required("find_group"), tok(), httpx.Response(200, json={"value": [{"id": GID}]}))
    assert r.requests[1].url.params["$filter"] == "displayName eq 'Staff'"
    _, r = run("add_group_member", required("add_group_member"), tok(), httpx.Response(204))
    g = r.requests[1]
    assert g.method == "POST" and str(g.url.path) == f"/v1.0/groups/{GID}/members/$ref" and json.loads(g.content) == {"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{UID}"}
    _, r = run("remove_group_member", required("remove_group_member"), tok(), httpx.Response(204))
    assert r.requests[1].method == "DELETE" and str(r.requests[1].url.path) == f"/v1.0/groups/{GID}/members/{UID}/$ref"
    _, r = run("disable_user", required("disable_user"), tok(), httpx.Response(204))
    assert r.requests[1].method == "PATCH" and json.loads(r.requests[1].content) == {"accountEnabled": False}
    _, r = run("enable_user", required("enable_user"), tok(), httpx.Response(204))
    assert json.loads(r.requests[1].content) == {"accountEnabled": True}
    res, r = run("revoke_sessions", required("revoke_sessions"), tok(), httpx.Response(200, json={"value": True}))
    assert str(r.requests[1].url.path).endswith("/revokeSignInSessions") and res.outputs["revoked"] is True


def test_graph_errors():
    with pytest.raises(ce.ConnectorError) as e:
        run("get_user", required("get_user"), tok(), httpx.Response(404, json={"error": {"message": "secret internal text"}}))
    assert e.value.message == "No such user." and "secret internal" not in e.value.message
    with pytest.raises(ce.ConnectorError) as e:
        run("disable_user", required("disable_user"), tok(), httpx.Response(503))
    assert e.value.retryable is True
    with pytest.raises(ce.ConnectorError) as e:
        run("add_group_member", required("add_group_member"), tok(), httpx.Response(503))
    assert e.value.retryable is False


HOSTILE = ["../x", "a/b", "a?x=1", "a&b=c", "a\r\nX: 1", "a\nb", "%2e%2e", "x' or 1 eq 1 or 'a'='a", "a'b@c.d", "", " ", "{user}", "x" * 400, "..", "g,h"]


@pytest.mark.parametrize("aid", [a.id for a in E.actions])
def test_no_input_can_change_the_request_shape_or_the_odata_filter(aid):
    a = act(aid)
    for inp in a.inputs:
        for bad in HOSTILE:
            raw = {k: v for k, v in GOOD.items() if any(i.key == k and i.required for i in a.inputs)}
            raw[inp.key] = bad
            try:
                values = ce.validate_inputs(a, raw)
            except ce.ConnectorError:
                continue
            p = ce.build(E, a, CONFIG, values, {**SECRETS, ce._TOKEN_KEY: TOKEN})
            path, _, query = p.path_and_query.partition("?")
            assert p.host == "graph.microsoft.com" and path.count("/") == a.path.count("/") and ".." not in path.split("/")
            assert len(query.split("&") if query else []) == len(a.query)
            assert "'" not in "".join(values.values()) if aid.startswith("find_") else True


# validator ---------------------------------------------------------------------------------------------------------------------

with open(registry._DIR + "/entra.yaml", encoding="utf-8") as _f:
    BASE = yaml.safe_load(_f)


@pytest.mark.parametrize("fn", [
    lambda d: d["auth"].update(token_host="{tenant}.example.com"),
    lambda d: d["auth"].update(token_host="*.microsoftonline.com"),
    lambda d: d["auth"].update(token_host=None),
    lambda d: d["auth"].update(token_path="/{client_secret}/token"),
    lambda d: d["auth"].update(token_path="/{nobody}/token"),
    lambda d: d["auth"].update(token_path="/{tenant}/../token"),
    lambda d: d["auth"].update(scope="a\nb"),
    lambda d: d["auth"].update(scope=None),
    lambda d: d["auth"]["fields"].pop(1),                                    # client_id missing
    lambda d: d["auth"]["fields"][2].update(secret=False, pattern="^x$"),   # client_secret must be secret
])
def test_validator_rejects_bad_oauth_definitions(fn):
    d = copy.deepcopy(BASE)
    fn(d)
    with pytest.raises(DefinitionInvalid):
        validate_connector(d)


def test_oauth_fields_are_refused_on_other_schemes():
    with open(registry._DIR + "/github.yaml", encoding="utf-8") as f:
        gh = yaml.safe_load(f)
    for patch in ({"token_host": "login.example.com"}, {"scope": "x"}):
        d = copy.deepcopy(gh)
        d["auth"].update(patch)
        with pytest.raises(DefinitionInvalid):
            validate_connector(d)
    d = copy.deepcopy(gh)
    d["test"]["token_only"] = True
    with pytest.raises(DefinitionInvalid):
        validate_connector(d)
