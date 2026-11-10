"""Connector definitions: the shipped ones are valid, and the build-time validator rejects unsafe ones (ADR 026)."""

import copy

import pytest
import yaml

from backend.app.connectors import registry
from backend.app.connectors.schema import DefinitionInvalid, validate_connector

with open(registry._DIR + "/github.yaml", encoding="utf-8") as _f:
    BASE = yaml.safe_load(_f)


def mutated(fn):
    d = copy.deepcopy(BASE)
    fn(d)
    return d


def action(d, aid):
    return next(a for a in d["actions"] if a["id"] == aid)


def test_shipped_connectors_load_and_validate():
    ids = [c.id for c in registry.all_connectors()]
    assert "github" in ids
    for c in registry.all_connectors():
        assert c.hosts and all("*" not in h for h in c.hosts)
        for a in c.actions:
            assert a.path.startswith("/") and a.path.split("/")[1] and "{" not in a.path.split("/")[1]


def test_public_view_has_no_secrets_or_credentials():
    v = registry.public_view(registry.get("github"))
    text = str(v).lower()
    assert "authorization" not in text and v["auth"]["scheme"] == "bearer"
    assert {f["key"] for f in v["auth"]["fields"]} == {"token", "org"}


@pytest.mark.parametrize("name,fn,fragment", [
    ("wildcard host", lambda d: d.update(hosts=["*.github.com"]), "invalid host"),
    ("host with port", lambda d: d.update(hosts=["api.github.com:8443"]), "invalid host"),
    ("host without dot", lambda d: d.update(hosts=["localhost"]), "invalid host"),
    ("no hosts", lambda d: d.update(hosts=[]), "hosts"),
    ("unscoped path", lambda d: action(d, "get_user").update(path="/{username}"), "fixed segment"),
    ("root path", lambda d: action(d, "get_user").update(path="/"), "path"),
    ("dot dot in path", lambda d: action(d, "get_user").update(path="/users/../x/{username}"), "path"),
    ("query in path", lambda d: action(d, "get_user").update(path="/users/{username}?x=1"), "path"),
    ("unknown placeholder", lambda d: action(d, "get_user").update(path="/users/{nobody}"), "placeholder"),
    ("secret in path", lambda d: action(d, "get_user").update(path="/users/{token}"), "placeholder"),
    ("string input without pattern", lambda d: action(d, "get_user")["inputs"][0].pop("pattern"), "pattern"),
    ("optional input in path", lambda d: action(d, "get_user")["inputs"][0].update(required=False), "must be required"),
    ("input reuses config key", lambda d: action(d, "get_user")["inputs"][0].update(key="org"), "reuse"),
    ("select without options", lambda d: action(d, "add_team_member")["inputs"][2].update(options=[]), "options"),
    ("bad regex", lambda d: action(d, "get_user")["inputs"][0].update(pattern="("), "pattern"),
    ("get with body", lambda d: action(d, "get_user").update(body={"a": "b"}), "GET"),
    ("bad output path", lambda d: action(d, "get_user")["outputs"].append({"key": "x", "from": "login"}), "from"),
    ("reserved output key", lambda d: action(d, "get_user")["outputs"].append({"key": "ok", "from": "$.ok"}), "reserved"),
    ("output named like a secret", lambda d: action(d, "get_user")["outputs"].append({"key": "token", "from": "$.t"}), "secret"),
    ("duplicate action id", lambda d: d["actions"].append(copy.deepcopy(action(d, "get_user"))), "duplicate"),
    ("config field without pattern", lambda d: d["auth"]["fields"][1].pop("pattern"), "pattern"),
    ("secret field with pattern", lambda d: d["auth"]["fields"][0].update(pattern="^x$"), "pattern"),
    ("scheme missing its secret", lambda d: d["auth"]["fields"].pop(0), "needs a field"),
    ("authorization static header", lambda d: d["headers"].update(Authorization="x"), "header"),
    ("placeholder in static header", lambda d: d["headers"].update({"X-Org": "{org}"}), "header"),
    ("error code out of range", lambda d: action(d, "get_user")["errors"].update({200: "x"}), "error codes"),
    ("unknown field", lambda d: d.update(webhook="https://evil.example"), "extra"),
])
def test_validator_rejects_unsafe_definitions(name, fn, fragment):
    with pytest.raises(DefinitionInvalid) as e:
        validate_connector(mutated(fn))
    assert fragment.lower() in str(e.value).lower(), str(e.value)


def test_host_placeholder_patterns_cannot_add_dots_or_slashes():
    d = mutated(lambda d: (d.update(hosts=["{org}.example.com"]), d["auth"]["fields"][1].update(pattern="^[a-z0-9.-]+$")))
    with pytest.raises(DefinitionInvalid) as e:
        validate_connector(d)
    assert "host" in str(e.value)
    ok = mutated(lambda d: (d.update(hosts=["{org}.example.com"]), d["auth"]["fields"][1].update(pattern="^[a-z0-9-]{1,30}$")))
    assert validate_connector(ok).hosts == ["{org}.example.com"]


def test_basic_and_header_schemes_validate():
    BASE_ACTIONS = [a for a in BASE["actions"] if a["id"] == "list_teams"]   # no input may reuse an auth field key
    basic = mutated(lambda d: d.update(actions=copy.deepcopy(BASE_ACTIONS), auth={"scheme": "basic", "fields": [
        {"key": "username", "label": "Email", "pattern": "^[^\\s]{1,100}$"}, {"key": "password", "label": "API token", "secret": True},
        {"key": "org", "label": "Org", "pattern": "^[a-z]{1,20}$"}]}))
    assert validate_connector(copy.deepcopy(basic)).auth.scheme == "basic"
    bad = copy.deepcopy(basic)
    bad["auth"]["fields"][0]["secret"] = True
    with pytest.raises(DefinitionInvalid):
        validate_connector(bad)
    hdr = mutated(lambda d: d.update(auth={"scheme": "header", "header_name": "X-Api-Key", "fields": [
        {"key": "value", "label": "API key", "secret": True}, {"key": "org", "label": "Org", "pattern": "^[a-z]{1,20}$"}]}))
    assert validate_connector(hdr).auth.header_name == "X-Api-Key"
    nohdr = copy.deepcopy(hdr)
    nohdr["auth"]["header_name"] = "Host"
    with pytest.raises(DefinitionInvalid):
        validate_connector(nohdr)
