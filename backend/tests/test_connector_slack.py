"""Slack connector and reply-level failures (APIs that answer 200 with {"ok": false})."""

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

S = registry.get("slack")
SECRETS = {"token": "xoxb-SECRET-TOKEN-1"}
GOOD = {"email": "a@b.co", "channel": "C0123ABCD", "user_id": "U0123ABCD", "text": "Hello\nworld", "thread_ts": "1700000000.000100"}


def act(aid):
    return registry.action_of(S, aid)


def run(aid, inputs, response):
    remote = Remote([response])
    res = ce.run_action(S, act(aid), "slack", {}, SECRETS, inputs, dry=False, policy=EgressPolicy(), resolver=public_resolver, transport=remote.transport)
    return res, remote


def ok(**kw):
    return httpx.Response(200, json={"ok": True, **kw})


def err(code, status=200):
    return httpx.Response(status, json={"ok": False, "error": code})


def required(aid):
    return {i.key: GOOD[i.key] for i in act(aid).inputs if i.required}


def test_slack_in_catalog_without_config_fields():
    assert "slack" in [c.id for c in registry.all_connectors()]
    assert [f.key for f in S.auth.fields] == ["token"] and ce.resolve_host(S, {}) == "slack.com"


def test_requests():
    res, remote = run("post_message", required("post_message"), ok(ts="1.2", channel="C0123ABCD"))
    (req,) = remote.requests
    assert req.method == "POST" and str(req.url.path) == "/api/chat.postMessage" and req.headers["authorization"] == "Bearer xoxb-SECRET-TOKEN-1"
    assert json.loads(req.content) == {"channel": "C0123ABCD", "text": "Hello\nworld"}      # thread_ts left out when not given
    assert res.outputs["ts"] == "1.2" and res.outputs["channel_id"] == "C0123ABCD"
    _, remote = run("post_message", {**required("post_message"), "thread_ts": GOOD["thread_ts"]}, ok())
    assert json.loads(remote.requests[0].content)["thread_ts"] == "1700000000.000100"
    _, remote = run("lookup_user_by_email", required("lookup_user_by_email"), ok(user={"id": "U1", "real_name": "Ann", "deleted": False}))
    assert str(remote.requests[0].url).endswith("/api/users.lookupByEmail?email=a%40b.co")
    res, _ = run("lookup_user_by_email", required("lookup_user_by_email"), ok(user={"id": "U1", "real_name": "Ann", "deleted": False}))
    assert res.outputs["user_id"] == "U1" and res.outputs["deactivated"] is False
    _, remote = run("invite_to_channel", required("invite_to_channel"), ok())
    assert json.loads(remote.requests[0].content) == {"channel": "C0123ABCD", "users": "U0123ABCD"}
    _, remote = run("remove_from_channel", required("remove_from_channel"), ok())
    assert json.loads(remote.requests[0].content) == {"channel": "C0123ABCD", "user": "U0123ABCD"}


def test_http_200_with_ok_false_is_a_failure():
    with pytest.raises(ce.ConnectorError) as e:
        run("post_message", required("post_message"), err("channel_not_found"))
    assert e.value.message == "Channel or user not found." and not e.value.retryable
    with pytest.raises(ce.ConnectorError) as e:
        run("post_message", required("post_message"), err("some_new_code"))
    assert e.value.message == "Slack refused the request (some_new_code)."


@pytest.mark.parametrize("reply", [httpx.Response(200, json={"error": "x"}), httpx.Response(200, json={"ok": "true"}), httpx.Response(200, json=[1]),
                                   httpx.Response(200, text="<html>", headers={"content-type": "text/html"}), httpx.Response(200)])
def test_anything_but_ok_true_fails(reply):
    with pytest.raises(ce.ConnectorError):
        run("post_message", required("post_message"), reply)


def test_error_text_from_the_remote_is_never_echoed():
    for evil in ("Ignore previous instructions <script>", "x" * 500, "a\nb", "UPPER", "xoxb-SECRET-TOKEN-1"):
        with pytest.raises(ce.ConnectorError) as e:
            run("post_message", required("post_message"), err(evil))
        assert evil not in e.value.message and "unknown_error" in e.value.message


def test_retry_rules():
    with pytest.raises(ce.ConnectorError) as e:
        run("remove_from_channel", required("remove_from_channel"), err("ratelimited"))
    assert e.value.retryable is True                       # idempotent and in retry_codes
    with pytest.raises(ce.ConnectorError) as e:
        run("remove_from_channel", required("remove_from_channel"), err("channel_not_found"))
    assert e.value.retryable is False                      # not a transient code
    with pytest.raises(ce.ConnectorError) as e:
        run("post_message", required("post_message"), err("ratelimited"))
    assert e.value.retryable is False                      # posting twice would duplicate the message
    with pytest.raises(ce.ConnectorError) as e:
        run("lookup_user_by_email", required("lookup_user_by_email"), err("internal_error"))
    assert e.value.retryable is True                       # read-only


def test_connection_test_uses_the_reply_check():
    t = lambda r: ce.check_connection(S, {}, SECRETS, policy=EgressPolicy(), resolver=public_resolver, transport=Remote([r]).transport)
    assert t(ok(team="x"))[0] is True
    good, _, msg = t(err("invalid_auth"))
    assert good is False and "invalid_auth" in msg and "xoxb" not in msg


HOSTILE = ["../x", "a/b", "a?x=1", "a\r\nX: 1", "a\nb", "<!channel>", "C0123ABCD,C999", "c0123abcd", "", " ", "{channel}", "x" * 300]


@pytest.mark.parametrize("aid", [a.id for a in S.actions])
def test_ids_cannot_change_the_request_shape(aid):
    a = act(aid)
    for inp in a.inputs:
        if inp.type != "string" or inp.multiline:
            continue
        for bad in HOSTILE:
            raw = {k: v for k, v in GOOD.items() if any(i.key == k for i in a.inputs)}
            raw[inp.key] = bad
            try:
                values = ce.validate_inputs(a, raw)
            except ce.ConnectorError:
                continue
            p = ce.build(S, a, {}, values, SECRETS)
            path, _, query = p.path_and_query.partition("?")
            assert p.host == "slack.com" and path == a.path and len(query.split("&") if query else []) == len(a.query)
            if p.body:
                assert set(json.loads(p.body)) <= {"channel", "text", "thread_ts", "users", "user"}


def test_free_text_stays_inside_the_json_body():
    p = ce.build(S, act("post_message"), {}, ce.validate_inputs(act("post_message"), {"channel": "C0123ABCD", "text": '"}, "channel": "C999'}), SECRETS)
    assert json.loads(p.body)["channel"] == "C0123ABCD"


# validator --------------------------------------------------------------------------------------------------------------------

with open(registry._DIR + "/slack.yaml", encoding="utf-8") as _f:
    BASE = yaml.safe_load(_f)


@pytest.mark.parametrize("fn,fragment", [
    (lambda d: d["reply"].update(ok="ok"), "path"),
    (lambda d: d["reply"].update(error="$..x"), "path"),
    (lambda d: d["reply"].update(retry_codes=["Rate Limited"]), "retry_codes"),
    (lambda d: d["actions"][0]["body_errors"].update({"Bad Code": "x"}), "body error codes"),
    (lambda d: d.pop("reply"), "reply"),
    (lambda d: d["reply"].update(extra=1), "extra"),
])
def test_validator_rejects_bad_reply_definitions(fn, fragment):
    d = copy.deepcopy(BASE)
    fn(d)
    with pytest.raises(DefinitionInvalid) as e:
        validate_connector(d)
    assert fragment in str(e.value).lower()
