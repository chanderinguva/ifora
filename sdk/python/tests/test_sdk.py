import inspect
import json
import os
import re

import httpx
import pytest

from ifora import OPERATIONS, Client, IForaError

ERROR = {"schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"], "status": "404", "detail": "Not found"}


def make(handler, **kw):
    return Client("https://api.test", transport=httpx.MockTransport(handler), **kw)


def ok(request):
    return httpx.Response(200, json={"id": 1})


def resolve(client, dotted):
    ns, name = dotted.split(".")
    return getattr(getattr(client, ns), name)


def test_manifest_has_every_operation():
    assert len(OPERATIONS) >= 266
    assert len({(m, p) for m, p, _ in OPERATIONS}) == len(OPERATIONS)
    assert len({d for _, _, d in OPERATIONS}) == len(OPERATIONS)   # no two operations share a method name


@pytest.mark.parametrize("method,path,dotted", OPERATIONS, ids=[f"{m} {p}" for m, p, _ in OPERATIONS])
def test_each_method_calls_its_endpoint(method, path, dotted):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={})

    c = make(handler)
    fn = resolve(c, dotted)
    args, kwargs = [], {}
    for name, p in inspect.signature(fn).parameters.items():
        if p.kind is inspect.Parameter.KEYWORD_ONLY:
            if p.default is inspect.Parameter.empty:
                kwargs[name] = "x"
        elif p.default is inspect.Parameter.empty:
            args.append({} if name in ("body", "form") else 7)
    fn(*args, **kwargs)
    (req,) = seen
    assert req.method == method
    expected = re.sub(r"\{[^/]+\}", "7", path)
    assert req.url.path == expected


def test_token_is_sent_as_bearer():
    seen = []
    c = make(lambda r: (seen.append(r), ok(r))[1], token="idf_api_abc")
    c.users.list()
    assert seen[0].headers["authorization"] == "Bearer idf_api_abc"


def test_login_remembers_csrf_and_sends_it_on_writes_only():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"csrf_token": "tok123"})
        return httpx.Response(200, json={})

    c = make(handler)
    c.login("a@example.com", "pw")
    assert json.loads(seen[0].content) == {"email": "a@example.com", "password": "pw"}
    c.users.list()
    c.users.create({"email": "n@example.com"})
    assert "x-csrf-token" not in seen[1].headers
    assert seen[2].headers["x-csrf-token"] == "tok123"


def test_query_params_are_renamed_and_none_dropped_and_bools_are_json_style():
    seen = []
    c = make(lambda r: (seen.append(r), ok(r))[1])
    c.users.list(start_index=3, count=50, sort_by="email", filter='status eq "active"')
    q = dict(seen[0].url.params)
    assert q == {"startIndex": "3", "count": "50", "sortBy": "email", "filter": 'status eq "active"'}


def test_path_params_are_escaped():
    seen = []
    c = make(lambda r: (seen.append(r), ok(r))[1])
    c.users.get("a/b c")
    assert seen[0].url.raw_path.decode().endswith("/users/a%2Fb%20c")


def test_scim_error_becomes_iforaerror():
    c = make(lambda r: httpx.Response(404, json=ERROR))
    with pytest.raises(IForaError) as e:
        c.users.get(1)
    assert (e.value.status, e.value.detail, e.value.scim_type) == (404, "Not found", None)


def test_validation_error_keeps_field_list():
    body = {**ERROR, "status": "422", "scimType": "invalidValue", "detail": "email: Field required", "errors": [{"loc": ["body", "email"]}]}
    c = make(lambda r: httpx.Response(422, json=body))
    with pytest.raises(IForaError) as e:
        c.users.create({})
    assert e.value.scim_type == "invalidValue" and e.value.errors[0]["loc"] == ["body", "email"]


def test_non_json_error_still_raises():
    c = make(lambda r: httpx.Response(502, text="bad gateway"))
    with pytest.raises(IForaError) as e:
        c.users.list()
    assert e.value.status == 502 and "bad gateway" in e.value.detail


def test_204_returns_none_and_text_returns_str():
    assert make(lambda r: httpx.Response(204)).users.delete(1) is None
    assert make(lambda r: httpx.Response(200, text="a,b\n1,2", headers={"content-type": "text/csv"})).users_csv.get_export_csv() == "a,b\n1,2"


def test_paginate_walks_every_page():
    data = list(range(1, 8))

    def handler(request):
        q = request.url.params
        start, count = int(q["startIndex"]), int(q["count"])
        page = data[start - 1:start - 1 + count]
        return httpx.Response(200, json={"totalResults": len(data), "startIndex": start, "itemsPerPage": len(page), "Resources": page})

    c = make(handler)
    assert list(c.paginate(c.users.list, page_size=3)) == data
    assert list(c.paginate(c.users.list, page_size=100)) == data


def test_form_body_is_urlencoded():
    seen = []
    c = make(lambda r: (seen.append(r), ok(r))[1])
    c.oidc.token_post(form={"grant_type": "client_credentials"})
    assert seen[0].headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert seen[0].content == b"grant_type=client_credentials"


@pytest.mark.skipif(not os.environ.get("IFORA_OPENAPI"), reason="set IFORA_OPENAPI to a saved openapi.json to check for drift")
def test_sdk_matches_the_live_spec():
    spec = json.load(open(os.environ["IFORA_OPENAPI"]))
    live = {(m.upper(), p) for p, item in spec["paths"].items() for m in item if m in ("get", "post", "put", "patch", "delete")}
    assert live == {(m, p) for m, p, _ in OPERATIONS}
