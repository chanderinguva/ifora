"""PagerDuty connector: Authorization token scheme, the From header taken from the connection, request shapes, injection resistance."""

import copy
import json

import httpx
import pytest
import yaml

from backend.app.connectors import engine as ce
from backend.app.connectors import registry
from backend.app.connectors.schema import DefinitionInvalid, validate_connector
from backend.app.recipes.http_client import EgressPolicy
from tests.recipe_helpers import Remote, public_resolver

P = registry.get("pagerduty")
CONFIG = {"from_email": "ops@example.com"}
SECRETS = {"value": "u+SECRET_API_KEY"}
GOOD = {"email": "a@b.co", "team_id": "PTEAM01", "user_id": "PUSER01", "incident_id": "Q1GXO3ZPYG3XWY", "service_id": "PSERV01",
        "title": "Disk full", "details": "line1\nline2", "note": "checked"}


def act(aid):
    return registry.action_of(P, aid)


def required(aid):
    return {i.key: GOOD[i.key] for i in act(aid).inputs if i.required}


def run(aid, inputs, *responses):
    remote = Remote(list(responses) or [httpx.Response(200, json={})])
    res = ce.run_action(P, act(aid), "pd", CONFIG, SECRETS, inputs, dry=False, policy=EgressPolicy(), resolver=public_resolver, transport=remote.transport)
    return res, remote


def test_headers_come_from_the_definition_and_the_connection():
    _, remote = run("get_incident", required("get_incident"), httpx.Response(200, json={"incident": {"status": "triggered", "title": "t"}}))
    h = remote.requests[0].headers
    assert h["authorization"] == "Token token=u+SECRET_API_KEY" and h["from"] == "ops@example.com"
    assert h["accept"] == "application/vnd.pagerduty+json;version=2" and remote.requests[0].headers["host"] == "api.pagerduty.com"


def test_connection_requires_a_valid_from_email_and_rejects_header_injection():
    assert ce.validate_config(P, CONFIG, SECRETS) == (CONFIG, SECRETS)
    for bad in ("ops", "a@b\r\nX-Evil: 1", "a b@c.d", "", "@x"):
        with pytest.raises(ce.ConnectorError):
            ce.validate_config(P, {"from_email": bad}, SECRETS)


def test_request_shapes_and_outputs():
    res, remote = run("find_user", required("find_user"), httpx.Response(200, json={"users": [{"id": "PU1", "email": "a@b.co"}, {"id": "PU2", "email": "joa@b.co"}]}))
    assert str(remote.requests[0].url).endswith("/users?query=a%40b.co&limit=10")
    assert res.outputs["user_id"] == "PU1" and res.outputs["emails"] == ["a@b.co", "joa@b.co"]
    _, remote = run("add_user_to_team", required("add_user_to_team"))
    r = remote.requests[0]
    assert r.method == "PUT" and str(r.url.path) == "/teams/PTEAM01/users/PUSER01" and json.loads(r.content) == {"role": "responder"}
    _, remote = run("remove_user_from_team", required("remove_user_from_team"))
    assert remote.requests[0].method == "DELETE" and not remote.requests[0].content
    res, remote = run("create_incident", required("create_incident"), httpx.Response(201, json={"incident": {"id": "Q1", "incident_number": 7, "html_url": "https://x.pagerduty.com/i/Q1"}}))
    assert json.loads(remote.requests[0].content) == {"incident": {"type": "incident", "title": "Disk full", "service": {"id": "PSERV01", "type": "service_reference"},
                                                                    "body": {"type": "incident_body", "details": "line1\nline2"}}}
    assert res.outputs["incident_id"] == "Q1" and res.outputs["incident_number"] == 7
    _, remote = run("create_incident", {**required("create_incident"), "urgency": "high", "incident_key": "disk:web1"})
    sent = json.loads(remote.requests[0].content)["incident"]
    assert sent["urgency"] == "high" and sent["incident_key"] == "disk:web1"
    _, remote = run("resolve_incident", required("resolve_incident"))
    assert json.loads(remote.requests[0].content) == {"incident": {"type": "incident_reference", "status": "resolved"}}
    _, remote = run("acknowledge_incident", required("acknowledge_incident"))
    assert json.loads(remote.requests[0].content)["incident"]["status"] == "acknowledged"
    _, remote = run("add_note", required("add_note"))
    assert str(remote.requests[0].url.path) == "/incidents/Q1GXO3ZPYG3XWY/notes" and json.loads(remote.requests[0].content) == {"note": {"content": "checked"}}


def test_errors_and_retries():
    with pytest.raises(ce.ConnectorError) as e:
        run("get_incident", required("get_incident"), httpx.Response(404))
    assert e.value.message == "Incident not found."
    with pytest.raises(ce.ConnectorError) as e:
        run("create_incident", required("create_incident"), httpx.Response(503))
    assert e.value.retryable is False
    with pytest.raises(ce.ConnectorError) as e:
        run("resolve_incident", required("resolve_incident"), httpx.Response(429))
    assert e.value.retryable is True


def test_connection_test_uses_abilities():
    seen = Remote([httpx.Response(200, json={"abilities": []})])
    ok, status, _ = ce.check_connection(P, CONFIG, SECRETS, policy=EgressPolicy(), resolver=public_resolver, transport=seen.transport)
    assert ok and status == 200 and str(seen.requests[0].url.path) == "/abilities" and seen.requests[0].headers["from"] == "ops@example.com"


HOSTILE = ["../x", "a/b", "a?x=1", "a&b=c", "a\r\nX: 1", "a\nb", "%2e%2e", "p01234", "", " ", "{team_id}", "x" * 300, "Q1,Q2", "..", "A.B"]


@pytest.mark.parametrize("aid", [a.id for a in P.actions])
def test_no_input_can_change_the_request_shape(aid):
    a = act(aid)
    for inp in a.inputs:
        if inp.type != "string" or inp.multiline:
            continue
        for bad in HOSTILE:
            raw = {k: v for k, v in GOOD.items() if any(i.key == k for i in a.inputs) and any(i.key == k and i.required for i in a.inputs)}
            raw[inp.key] = bad
            try:
                values = ce.validate_inputs(a, raw)
            except ce.ConnectorError:
                continue
            p = ce.build(P, a, CONFIG, values, SECRETS)
            path, _, query = p.path_and_query.partition("?")
            assert p.host == "api.pagerduty.com" and path.count("/") == a.path.count("/") and ".." not in path.split("/")
            assert len(query.split("&") if query else []) == len(a.query)
            assert all("\r" not in k + v and "\n" not in k + v for k, v in p.headers.items())


# validator ---------------------------------------------------------------------------------------------------------------------

with open(registry._DIR + "/pagerduty.yaml", encoding="utf-8") as _f:
    BASE = yaml.safe_load(_f)


@pytest.mark.parametrize("fn", [
    lambda d: d["config_headers"].update({"Authorization": "{from_email}"}),            # forbidden header
    lambda d: d["config_headers"].update({"Accept": "{from_email}"}),                   # clashes with a static header
    lambda d: d["config_headers"].update({"X-Key": "{value}"}),                         # secret field
    lambda d: d["config_headers"].update({"X-Key": "{nope}"}),                          # unknown field
    lambda d: d["config_headers"].update({"X-Key": "static"}),                          # no placeholder at all
    lambda d: d["config_headers"].update({"Bad Name": "{from_email}"}),
])
def test_validator_rejects_bad_config_headers(fn):
    d = copy.deepcopy(BASE)
    fn(d)
    with pytest.raises(DefinitionInvalid):
        validate_connector(d)
