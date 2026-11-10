"""Jira Cloud connector: definition, request shapes, auth, injection resistance (ADR 026)."""

import base64
import json

import httpx
import pytest

from backend.app.connectors import engine as ce
from backend.app.connectors import registry
from backend.app.recipes.http_client import EgressPolicy
from tests.recipe_helpers import Remote, public_resolver

J = registry.get("jira")
CONFIG = {"site": "acme", "username": "bot@example.com"}
SECRETS = {"password": "ATATT_SECRET_TOKEN"}
GOOD = {"email": "a@b.co", "group": "jira-users", "account_id": "712020:abc-123", "issue_key": "OPS-12", "project_key": "OPS",
        "issue_type": "Task", "summary": "Hello", "comment": "Hi\nthere", "transition_id": "31"}


def act(aid):
    return registry.action_of(J, aid)


def run(aid, inputs, remote=None):
    remote = remote or Remote([httpx.Response(200, json={})])
    res = ce.run_action(J, act(aid), "jira", CONFIG, SECRETS, inputs, dry=False, policy=EgressPolicy(), resolver=public_resolver, transport=remote.transport)
    return res, remote


def inputs_for(aid):
    return {i.key: GOOD[i.key] for i in act(aid).inputs if i.required}


def build(aid, extra=None):
    return ce.build(J, act(aid), CONFIG, ce.validate_inputs(act(aid), {**inputs_for(aid), **(extra or {})}), SECRETS)


def test_jira_is_in_the_catalog_with_site_derived_host():
    assert "jira" in [c.id for c in registry.all_connectors()] and ce.resolve_host(J, CONFIG) == "acme.atlassian.net"
    assert "ATATT" not in str(registry.public_view(J))


@pytest.mark.parametrize("site", ["a.b", "a/b", "a:443", "a@evil.com", "-a", "a-", "A", "", "a b", "x" * 64])
def test_site_cannot_redirect_the_host(site):
    with pytest.raises(ce.ConnectorError):
        ce.validate_config(J, {**CONFIG, "site": site}, SECRETS)


def test_basic_auth_header_and_host():
    p = build("get_issue")
    assert p.host == "acme.atlassian.net" and p.headers["Authorization"] == "Basic " + base64.b64encode(b"bot@example.com:ATATT_SECRET_TOKEN").decode()
    assert p.path_and_query == "/rest/api/2/issue/OPS-12?fields=summary,status,assignee"


def test_request_shapes():
    assert build("find_user").path_and_query == "/rest/api/3/user/search?query=a%40b.co"
    p = build("add_user_to_group")
    assert p.method == "POST" and p.path_and_query == "/rest/api/3/group/user?groupname=jira-users" and json.loads(p.body) == {"accountId": "712020:abc-123"}
    assert build("remove_user_from_group").path_and_query == "/rest/api/3/group/user?groupname=jira-users&accountId=712020%3Aabc-123"
    c = build("create_issue")
    assert json.loads(c.body) == {"fields": {"project": {"key": "OPS"}, "issuetype": {"name": "Task"}, "summary": "Hello"}}   # description omitted
    c2 = build("create_issue", {"description": "line1\nline2"})
    assert json.loads(c2.body)["fields"]["description"] == "line1\nline2"
    assert json.loads(build("transition_issue").body) == {"transition": {"id": "31"}}
    assert json.loads(build("add_comment").body) == {"body": "Hi\nthere"}


def test_outputs():
    body = [{"accountId": "712020:abc", "displayName": "Ann", "active": True}]
    res, _ = run("find_user", {"email": "a@b.co"}, Remote([httpx.Response(200, json=body)]))
    assert res.outputs["account_id"] == "712020:abc" and res.outputs["active"] is True
    res, _ = run("get_issue", {"issue_key": "OPS-1"}, Remote([httpx.Response(200, json={"key": "OPS-1", "fields": {"summary": "s", "status": {"name": "Open"}, "assignee": None}})]))
    assert res.outputs["status"] == "Open" and res.outputs["assignee_account_id"] is None
    res, _ = run("list_transitions", {"issue_key": "OPS-1"}, Remote([httpx.Response(200, json={"transitions": [{"id": "11", "name": "Done"}, {"id": "21", "name": "Open"}]})]))
    assert res.outputs["transition_ids"] == ["11", "21"]
    res, _ = run("find_user", {"email": "nobody@b.co"}, Remote([httpx.Response(200, json=[])]))
    assert res.outputs["account_id"] is None


def test_errors_and_retry_rules():
    with pytest.raises(ce.ConnectorError) as e:
        run("get_issue", {"issue_key": "OPS-1"}, Remote([httpx.Response(404)]))
    assert e.value.message == "Issue not found, or the API account cannot see it."
    with pytest.raises(ce.ConnectorError) as e:
        run("create_issue", {"project_key": "OPS", "issue_type": "Task", "summary": "x"}, Remote([httpx.Response(503)]))
    assert e.value.retryable is False                        # create is not idempotent
    with pytest.raises(ce.ConnectorError) as e:
        run("assign_issue", {"issue_key": "OPS-1", "account_id": "abc"}, Remote([httpx.Response(503)]))
    assert e.value.retryable is True


HOSTILE = ["../admin", "a/b", "a?x=1", "a#f", "a\r\nX-Evil: 1", "a\nb", "%2e%2e", "%26x=1", "a&b=c", "a b", "{site}", "..", "a\x00b", "é", "x" * 500, "", " ", "ops-1"]


@pytest.mark.parametrize("aid", [a.id for a in J.actions])
def test_no_string_input_can_change_the_request_shape(aid):
    a = act(aid)
    for inp in a.inputs:
        if inp.type != "string":
            continue
        for bad in HOSTILE:
            raw = {k: v for k, v in GOOD.items() if any(i.key == k for i in a.inputs)}
            raw[inp.key] = bad
            try:
                values = ce.validate_inputs(a, raw)
            except ce.ConnectorError:
                continue
            p = ce.build(J, a, CONFIG, values, SECRETS)
            path, _, query = p.path_and_query.partition("?")
            assert p.host == "acme.atlassian.net" and path.startswith("/rest/") and ".." not in path.split("/")
            assert path.count("/") == a.path.count("/")
            assert "\r" not in p.path_and_query and "\n" not in p.path_and_query
            assert len(query.split("&") if query else []) == len(a.query)   # no extra query parameters
            if p.body:
                json.loads(p.body)                                                                 # still valid JSON, built by serialisation


def test_free_text_goes_into_json_only():
    p = build("add_comment", {"comment": '"}, "evil": {"x": "\\'})
    assert list(json.loads(p.body)) == ["body"]


def test_newlines_are_only_accepted_by_multiline_inputs():
    assert ce.validate_inputs(act("add_comment"), {"issue_key": "OPS-1", "comment": "a\nb\tc"})["comment"] == "a\nb\tc"
    for bad in ("a\x00b", "a\x1bb", "a\x7fb"):
        with pytest.raises(ce.ConnectorError):
            ce.validate_inputs(act("add_comment"), {"issue_key": "OPS-1", "comment": bad})
    with pytest.raises(ce.ConnectorError):
        ce.validate_inputs(act("create_issue"), {"project_key": "OPS", "issue_type": "Task", "summary": "a\nb"})
