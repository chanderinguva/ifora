"""Generic connector engine: input validation, request building, injection resistance, replies (ADR 026). No database, no real network."""

import json

import httpx
import pytest

from backend.app.connectors import engine as ce
from backend.app.connectors import registry
from backend.app.recipes.http_client import EgressPolicy
from tests.recipe_helpers import Remote, public_resolver

GH = registry.get("github")
CONFIG = {"org": "acme"}
SECRETS = {"token": "ghp_SECRET_VALUE_123"}


def act(aid):
    return registry.action_of(GH, aid)


def run(aid, inputs, remote=None, dry=False):
    remote = remote or Remote([httpx.Response(200, json={})])
    res = ce.run_action(GH, act(aid), "gh", CONFIG, SECRETS, inputs, dry=dry, policy=EgressPolicy(), resolver=public_resolver, transport=remote.transport)
    return res, remote


# inputs -------------------------------------------------------------------------------------------------------------------------

def test_inputs_are_validated_and_defaults_applied():
    ok = ce.validate_inputs(act("add_team_member"), {"team": "eng", "username": "octocat"})
    assert ok == {"team": "eng", "username": "octocat", "role": "member"}
    for bad, msg in [
        ({"team": "eng"}, "required"), ({"team": "eng", "username": "a b"}, "invalid format"), ({"team": "eng", "username": "x" * 40}, "longer"),
        ({"team": "eng", "username": "octocat", "role": "owner"}, "one of"), ({"team": "eng", "username": "octocat", "extra": "1"}, "unknown input"),
        ({"team": "Eng!", "username": "octocat"}, "invalid format"), ({"team": "eng", "username": ".."}, "invalid format"),
    ]:
        with pytest.raises(ce.ConnectorError) as e:
            ce.validate_inputs(act("add_team_member"), bad)
        assert msg in e.value.message, (bad, e.value.message)


def test_partial_validation_checks_only_given_values():
    assert ce.validate_inputs(act("add_team_member"), {"team": "eng"}, partial=True) == {"team": "eng"}
    with pytest.raises(ce.ConnectorError):
        ce.validate_inputs(act("add_team_member"), {"team": "NOPE!"}, partial=True)


HOSTILE = ["../admin", "a/b", "a?x=1", "a#f", "a\r\nX-Evil: 1", "a\nb", "%2e%2e", "%2f", "a b", "{org}", "..", ".", "a\x00b", "a\\b", "é", "x" * 500, "", " "]


@pytest.mark.parametrize("aid", [a.id for a in GH.actions])
def test_no_string_input_can_change_the_request_shape(aid):
    """Every string input of every action, fed hostile values: either refused, or encoded into exactly the intended path segment."""
    a = act(aid)
    good = {"team": "eng", "username": "octocat"}
    for inp in a.inputs:
        if inp.type != "string":
            continue
        for bad in HOSTILE:
            raw = {k: v for k, v in good.items() if any(i.key == k for i in a.inputs)}
            raw[inp.key] = bad
            try:
                inputs = ce.validate_inputs(a, raw)
            except ce.ConnectorError:
                continue
            p = ce.build(GH, a, CONFIG, inputs, SECRETS)
            assert p.host == "api.github.com"
            assert p.path_and_query.startswith(p.scope_prefix + "/")
            path = p.path_and_query.split("?", 1)[0]
            assert ".." not in path.split("/") and "\r" not in p.path_and_query and "\n" not in p.path_and_query
            assert all("\r" not in k + v and "\n" not in k + v for k, v in p.headers.items())
            assert path.count("/") == a.path.count("/")   # no extra segments


def test_config_is_validated_and_secrets_are_never_echoed():
    cfg, sec = ce.validate_config(GH, {"org": "acme"}, {"token": "tok"})
    assert cfg == {"org": "acme"} and sec == {"token": "tok"}
    for config, secrets, msg in [
        ({"org": "a/b"}, {"token": "t"}, "invalid format"), ({}, {"token": "t"}, "required"), ({"org": "acme"}, {}, "required"),
        ({"org": "acme", "x": "1"}, {"token": "t"}, "unknown field"), ({"org": "acme"}, {"token": "a\nb"}, "not valid"),
        ({"org": "acme", "token": "t"}, {"token": "t"}, "wrong place"), ({"org": "acme"}, {"token": "t", "org": "o"}, "wrong place"),
    ]:
        with pytest.raises(ce.ConnectorError) as e:
            ce.validate_config(GH, config, secrets)
        assert msg in e.value.message
        assert "ghp_" not in e.value.message and "t" != e.value.message


# request building ---------------------------------------------------------------------------------------------------------------

def test_request_is_built_from_the_definition():
    p = ce.build(GH, act("add_team_member"), CONFIG, {"team": "eng", "username": "octo-cat", "role": "maintainer"}, SECRETS)
    assert (p.method, p.host, p.path_and_query) == ("PUT", "api.github.com", "/orgs/acme/teams/eng/memberships/octo-cat")
    assert json.loads(p.body) == {"role": "maintainer"}
    assert p.headers["Authorization"] == "Bearer ghp_SECRET_VALUE_123" and p.headers["Content-Type"] == "application/json"
    assert p.headers["Accept"] == "application/vnd.github+json"
    q = ce.build(GH, act("list_teams"), CONFIG, {}, SECRETS)
    assert q.path_and_query == "/orgs/acme/teams?per_page=100" and q.body is None


def test_dry_run_sends_nothing_and_builds_without_credentials():
    res, remote = run("add_team_member", {"team": "eng", "username": "octocat"}, dry=True)
    assert remote.requests == [] and res.outputs["dry_run"] is True and res.status is None
    assert "ghp_" not in json.dumps(res.request) and "Authorization" not in json.dumps(res.request)


def test_basic_and_header_auth_headers():
    import base64
    from backend.app.connectors.schema import validate_connector
    import copy, yaml

    with open(registry._DIR + "/github.yaml", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    raw["actions"] = [a for a in raw["actions"] if a["id"] == "list_teams"]   # no input may reuse an auth field key
    basic = copy.deepcopy(raw)
    basic["auth"] = {"scheme": "basic", "fields": [{"key": "username", "label": "Email", "pattern": "^[^\\s]{1,100}$"},
                                                   {"key": "password", "label": "Token", "secret": True}, {"key": "org", "label": "Org", "pattern": "^[a-z]{1,20}$"}]}
    c = validate_connector(basic)
    p = ce.build(c, c.actions[0], {"username": "me@example.com", "org": "acme"}, {}, {"password": "pw"})
    assert p.headers["Authorization"] == "Basic " + base64.b64encode(b"me@example.com:pw").decode()
    hdr = copy.deepcopy(raw)
    hdr["auth"] = {"scheme": "header", "header_name": "X-Api-Key", "header_prefix": "Token token=", "fields": [
        {"key": "value", "label": "Key", "secret": True}, {"key": "org", "label": "Org", "pattern": "^[a-z]{1,20}$"}]}
    c2 = validate_connector(hdr)
    assert ce.build(c2, c2.actions[0], {"org": "acme"}, {}, {"value": "k"}).headers["X-Api-Key"] == "Token token=k"


# replies --------------------------------------------------------------------------------------------------------------------------

def test_outputs_are_mapped_and_limited():
    body = [{"slug": f"t{i}", "name": f"Team {i}"} for i in range(150)]
    res, remote = run("list_teams", {}, Remote([httpx.Response(200, json=body)]))
    assert res.outputs["status_code"] == 200 and res.outputs["ok"] is True
    assert res.outputs["team_slugs"][:2] == ["t0", "t1"] and len(res.outputs["team_slugs"]) == 100
    res2, _ = run("get_user", {"username": "octocat"}, Remote([httpx.Response(200, json={"login": "octocat", "id": 1, "name": None, "secret": "ignored"})]))
    assert res2.outputs["login"] == "octocat" and res2.outputs["id"] == 1 and res2.outputs["name"] is None and "secret" not in res2.outputs


def test_empty_reply_and_non_json_give_none_outputs():
    res, _ = run("remove_team_member", {"team": "eng", "username": "octocat"}, Remote([httpx.Response(204)]))
    assert res.outputs == {"status_code": 204, "ok": True}
    res2, _ = run("get_user", {"username": "octocat"}, Remote([httpx.Response(200, text="<html>", headers={"content-type": "text/html"})]))
    assert res2.outputs["login"] is None


def test_known_errors_use_the_definition_text_and_others_are_generic():
    with pytest.raises(ce.ConnectorError) as e:
        run("get_user", {"username": "nobody"}, Remote([httpx.Response(404, json={"message": "Not Found"})]))
    assert e.value.message == "No GitHub account with that username." and not e.value.retryable
    with pytest.raises(ce.ConnectorError) as e:
        run("get_user", {"username": "nobody"}, Remote([httpx.Response(418)]))
    assert e.value.message == "GitHub answered 418"
    with pytest.raises(ce.ConnectorError) as e:
        run("get_user", {"username": "nobody"}, Remote([httpx.Response(302, headers={"location": "https://evil.example/"})]))
    assert "redirects are not followed" in e.value.message


def test_retry_only_for_idempotent_or_read_actions():
    for aid, inputs, retry in [("get_user", {"username": "octocat"}, True), ("add_team_member", {"team": "eng", "username": "octocat"}, True),
                               ("list_teams", {}, True)]:
        for status in (429, 503):
            with pytest.raises(ce.ConnectorError) as e:
                run(aid, inputs, Remote([httpx.Response(status)]))
            assert e.value.retryable is retry
    non_idem = registry.action_of(GH, "add_team_member").model_copy(update={"idempotent": False})
    remote = Remote([httpx.Response(503)])
    with pytest.raises(ce.ConnectorError) as e:
        ce.run_action(GH, non_idem, "gh", CONFIG, SECRETS, {"team": "eng", "username": "octocat"}, dry=False, policy=EgressPolicy(),
                      resolver=public_resolver, transport=remote.transport)
    assert e.value.retryable is False


def test_secrets_are_scrubbed_from_outputs_and_the_request_summary():
    body = {"login": "ghp_SECRET_VALUE_123", "id": 1, "name": "x"}
    res, _ = run("get_user", {"username": "octocat"}, Remote([httpx.Response(200, json=body)]))
    assert "ghp_SECRET_VALUE_123" not in json.dumps(res.outputs) and "ghp_SECRET_VALUE_123" not in json.dumps(res.request)


def test_private_addresses_are_blocked_even_when_dns_lies():
    remote = Remote()
    with pytest.raises(ce.ConnectorError) as e:
        ce.run_action(GH, act("get_user"), "gh", CONFIG, SECRETS, {"username": "octocat"}, dry=False, policy=EgressPolicy(),
                      resolver=lambda h, p: ["10.0.0.5"], transport=remote.transport)
    assert "blocked" in e.value.message and remote.requests == []


def test_requests_only_go_to_the_definitions_host_and_https():
    remote = Remote([httpx.Response(200, json={"login": "o"})])
    run("get_user", {"username": "octocat"}, remote)
    (req,) = remote.requests
    assert req.url.scheme == "https" and req.headers["host"] == "api.github.com" and str(req.url.path) == "/users/octocat"
    assert req.headers["authorization"].startswith("Bearer ")


def test_check_connection():
    ok, status, msg = ce.check_connection(GH, CONFIG, SECRETS, policy=EgressPolicy(), resolver=public_resolver, transport=Remote([httpx.Response(200, json={})]).transport)
    assert (ok, status) == (True, 200)
    ok, status, msg = ce.check_connection(GH, CONFIG, SECRETS, policy=EgressPolicy(), resolver=public_resolver, transport=Remote([httpx.Response(401)]).transport)
    assert ok is False and "refused" in msg and "ghp_" not in msg
