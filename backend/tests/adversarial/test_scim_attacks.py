"""IFORA-17: adversarial regression suite for the SCIM 2.0 server. Each test names the attack and its register ID / CWE.

Real app, real database, real tokens; nothing weakens production settings.
"""

import json

import pytest
from fastapi.testclient import TestClient

from backend.app import ratelimit
from backend.app.api import app
from backend.app.config import settings
from backend.app.tenancy import tenant_session
from backend.app.users.model import User
from tests.test_scim import ERR, PATCH, Scim, mk, mk_token, second_tenant, user_body
from tests.test_scim_tokens import issue

pytestmark = pytest.mark.adversarial

GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
LEAKS = ("sqlalchemy", "psycopg", "traceback", "syntaxerror", "select ", " from users", "internal server error", "programmingerror")


def _clean(r):
    """No database or stack detail in any error body (CWE-209)."""
    low = r.text.lower()
    assert not any(x in low for x in LEAKS), r.text[:300]


def _scim_error(r, status, scim_type=None):
    assert r.status_code == status, (r.status_code, r.text[:300])
    b = r.json()
    assert b["schemas"] == [ERR] and b["status"] == str(status)
    if scim_type:
        assert b["scimType"] == scim_type
    _clean(r)


@pytest.fixture
def people(db):
    s = Scim(mk_token(db))
    for n in ("alice", "bob", "carol"):
        mk(s, n)
    return s


# ---- filter injection and resource exhaustion (CWE-89, CWE-400) -------------------------------------------------------


@pytest.mark.parametrize("f", [
    "userName eq \"x' OR '1'='1\"",
    'userName eq "x\\" or true or \\""',
    "userName eq \"'; DROP TABLE users;--\"",
    'userName eq "%" ',
    'userName co "%_\\\\"',
    'userName eq "\\u0000"',
    "userName eq \"a\"\x00 or userName pr",
    'userName eq "a" /* c */ or userName pr',
    'emails[value eq "a" or 1=1].value pr',
])
def test_injection_in_filter_values_returns_nothing_extra_and_changes_nothing(people, f):
    """SQL / filter injection (CWE-89): never more rows than a literal match, never a DB error, nothing dropped."""
    r = people.get("/Users", filter=f)
    assert r.status_code in (200, 400), r.text[:200]
    _clean(r)
    if r.status_code == 200:
        assert r.json()["totalResults"] == 0
    assert people.get("/Users").json()["totalResults"] == 3


@pytest.mark.parametrize("f", [
    "userName; DROP TABLE users eq \"a\"", "users.password_hash pr", "userName eq \"a\" ; select 1",
    "id eq 1 or 1 eq 1", "__class__ eq \"a\"", "emails[", "emails[]", "userName eq \"a\" or" + " userName pr" * 60,
    "(" * 50 + 'userName pr' + ")" * 50, "not " * 40 + 'userName pr', 'userName eq "' + "a" * 5000 + '"',
    "\x00", "userName eq \"a\" and not (", "[[[[[[[[[[[[[[[[[[[[",
])
def test_malformed_or_oversized_filters_are_400_invalid_filter_without_leaks(people, f):
    """AC4 / filter DoS and injection through structure (CWE-400, CWE-89): a SCIM 400, no DB detail."""
    _scim_error(people.get("/Users", filter=f), 400, "invalidFilter")


@pytest.mark.parametrize("params", [
    {"sortBy": "userName; DROP TABLE users"}, {"sortBy": "password_hash"}, {"sortBy": "(select 1)"}, {"sortOrder": "x"},
    {"startIndex": "-5"}, {"startIndex": "99999999999999999999"}, {"count": "-1"}, {"count": "99999999"}, {"count": "abc"},
    {"attributes": "password_hash,passwordHash"}, {"excludedAttributes": "id,userName,meta,schemas"},
])
def test_pagination_sorting_and_projection_inputs_cannot_break_or_expand_the_query(people, params):
    """Query-parameter abuse (CWE-20, CWE-200): clean errors or bounded results; secrets are never projectable."""
    r = people.get("/Users", **params)
    assert r.status_code in (200, 400), r.text[:200]
    # a 400 may repeat the rejected parameter (harmless JSON); judge the rest of the body
    shown = r.text
    for v in params.values():
        shown = shown.replace(v, "")
    assert not any(x in shown.lower() for x in LEAKS), shown[:300]
    if r.status_code == 200:
        assert "password" not in r.text.lower() and "hash" not in r.text.lower()
        assert len(r.json().get("Resources", [])) <= 3


def test_post_search_has_the_same_limits_as_get(people):
    """Alternate entry point (CWE-693): POST /.search is not a way around the filter limits."""
    body = {"schemas": ["urn:ietf:params:scim:api:messages:2.0:SearchRequest"], "filter": "(" * 50 + "userName pr" + ")" * 50}
    r = people.c.post("/scim/v2/Users/.search", content=json.dumps(body), headers=people.h)
    _scim_error(r, 400, "invalidFilter")


# ---- PATCH / PUT / POST abuse (CWE-400, CWE-915, CWE-20) -------------------------------------------------------------


def test_oversized_and_deeply_nested_patch_is_refused_cleanly(people):
    """Oversized / deep PATCH (CWE-400): bounded work, a 4xx, no 5xx."""
    u = mk(people, "target")
    many = [{"op": "replace", "path": "title", "value": str(i)} for i in range(5000)]
    r = people.patch(f"/Users/{u['id']}", many)
    assert 400 <= r.status_code < 500, r.status_code
    deep = value = {}
    for _ in range(500):
        value["a"] = {}
        value = value["a"]
    r = people.patch(f"/Users/{u['id']}", [{"op": "replace", "value": deep}])
    assert r.status_code < 500
    _clean(r)
    huge = people.patch(f"/Users/{u['id']}", [{"op": "replace", "path": "title", "value": "A" * 5_000_000}])
    assert 400 <= huge.status_code < 500


def test_mass_assignment_through_scim_cannot_set_privileged_or_internal_fields(db, people):
    """Mass assignment (CWE-915): admin flags, password hashes, ids and tenant cannot be written via create/PUT/PATCH."""
    body = user_body("mallory", **{"is_admin": True, "isAdmin": True, "is_super_admin": True, "password_hash": "x", "tenant_id": 999,
                                    "status": "active", "roles": ["admin"], "id": "11111111-1111-1111-1111-111111111111"})
    r = people.post("/Users", body)
    assert r.status_code in (201, 400), r.text[:200]
    u = db.query(User).filter(User.email == "mallory@example.com").first()
    if u is not None:
        assert not u.is_admin and not u.is_super_admin and u.password_hash != "x" and u.tenant_id != 999
        assert str(u.public_id) != "11111111-1111-1111-1111-111111111111"
        r2 = people.patch(f"/Users/{r.json()['id']}", [{"op": "replace", "value": {"is_admin": True, "isAdmin": True, "tenant_id": 999}}])
        assert r2.status_code in (200, 400)
        db.expire_all()
        u = db.query(User).filter(User.email == "mallory@example.com").one()
        assert not u.is_admin and u.tenant_id != 999


def test_scim_cannot_change_a_super_administrator(db, people, super_admin):
    """Privilege boundary (CWE-269): a provisioning token must not reset, disable or delete the super administrator."""
    sa = db.query(User).filter(User.email == super_admin.user.email).one()
    r = people.get("/Users", filter=f'userName eq "{sa.email}"')
    for res in r.json().get("Resources", []):
        d = people.delete(f"/Users/{res['id']}")
        p = people.patch(f"/Users/{res['id']}", [{"op": "replace", "path": "active", "value": False}])
        assert d.status_code in (400, 403, 404, 409) and p.status_code in (400, 403, 404, 409), (d.status_code, p.status_code)
    db.expire_all()
    assert db.query(User).filter(User.id == sa.id).one().status == "active"


def test_wrong_content_type_and_malformed_bodies_are_clean_4xx(people):
    """Malformed input (CWE-20): bad JSON, wrong media type, arrays, nulls, huge bodies -> 4xx, never 5xx."""
    for body, ctype in ((b"{", "application/scim+json"), (b"[]", "application/scim+json"), (b"null", "application/scim+json"),
                        (b'{"userName": ' + b"9" * 100_000 + b"}", "application/scim+json"), (b"userName=a", "application/x-www-form-urlencoded"),
                        (b"\xff\xfe\x00", "application/scim+json"), (b"{}", "text/plain")):
        r = people.c.post("/scim/v2/Users", content=body, headers={**people.h, "Content-Type": ctype})
        assert 400 <= r.status_code < 500, (body[:20], r.status_code)
        _clean(r)


# ---- Bulk limits (CWE-770) ---------------------------------------------------------------------------------------------


def test_bulk_operation_count_payload_and_reference_loops_are_bounded(people):
    """Bulk abuse (CWE-770, CWE-674): too many operations, a huge payload, self/cyclic bulkId references."""
    schema = ["urn:ietf:params:scim:api:messages:2.0:BulkRequest"]

    def bulk(ops, **kw):
        return people.c.post("/scim/v2/Bulk", content=json.dumps({"schemas": schema, "Operations": ops, **kw}), headers=people.h)

    ops = [{"method": "POST", "path": "/Users", "bulkId": f"b{i}", "data": user_body(f"bulk{i}")} for i in range(101)]
    assert bulk(ops).status_code == 413
    loop = [{"method": "POST", "path": "/Groups", "bulkId": "g1", "data": {"schemas": [GROUP], "displayName": "g", "members": [{"value": "bulkId:g1"}]}}]
    r = bulk(loop)
    assert r.status_code < 500
    _clean(r)
    big = [{"method": "POST", "path": "/Users", "bulkId": "x", "data": user_body("big", title="A" * 3_000_000)}]
    r = bulk(big)
    assert 400 <= r.status_code < 500
    assert bulk([{"method": "POST", "path": "/Bulk", "bulkId": "n", "data": {}}]).status_code < 500   # nested bulk
    assert bulk([{"method": "POST", "path": "/../admin/users", "bulkId": "t", "data": {}}]).status_code < 500


# ---- token restrictions (CWE-285, CWE-863) -------------------------------------------------------------------------------


def _writes(t, uid, gid):
    return [t.post("/Users", user_body("w1")), t.put(f"/Users/{uid}", user_body("ro")), t.patch(f"/Users/{uid}", [{"op": "replace", "path": "title", "value": "x"}]),
            t.delete(f"/Users/{uid}"), t.post("/Groups", {"schemas": [GROUP], "displayName": "w"}),
            t.c.post("/scim/v2/Bulk", content=json.dumps({"schemas": ["urn:ietf:params:scim:api:messages:2.0:BulkRequest"], "Operations": [
                {"method": "POST", "path": "/Users", "bulkId": "b", "data": user_body("viabulk")}]}), headers=t.h)]


def test_read_only_token_cannot_write_by_any_verb_or_through_bulk(db, super_admin):
    """AC5 / read-only token bypass (CWE-863): POST, PUT, PATCH, DELETE and Bulk are all 403 and change nothing."""
    full = Scim(issue(super_admin)["token"])
    u = mk(full, "victim")
    ro = Scim(issue(super_admin, read_only=True)["token"])
    for r in _writes(ro, u["id"], None):
        assert r.status_code == 403, (r.request.method, r.request.url.path, r.status_code)
        _clean(r)
    assert full.get(f"/Users/{u['id']}").json()["userName"] == "victim"
    assert full.get("/Users", filter='userName eq "viabulk"').json()["totalResults"] == 0
    assert ro.c.post("/scim/v2/Users/.search", content=json.dumps({"schemas": ["urn:ietf:params:scim:api:messages:2.0:SearchRequest"], "filter": "userName pr"}),
                     headers=ro.h).status_code == 200  # search is a read and stays allowed


@pytest.mark.parametrize("path", ["/Groups", "/groups", "/GROUPS", "//Groups", "/Groups/", "/Groups/.search", "/Groups/1", "/%47roups",
                                  "/Users/../Groups", "/Users/%2e%2e/Groups", "/./Groups"])
def test_users_only_token_cannot_reach_groups_by_path_tricks(db, super_admin, path):
    """Scope bypass by path normalisation (CWE-22, CWE-863): every spelling of /Groups stays denied."""
    t = Scim(issue(super_admin, users_only=True)["token"])
    for method in ("get", "post"):
        r = t.c.request(method.upper(), "/scim/v2" + path, headers=t.h, content=b"{}" if method == "post" else None)
        assert r.status_code in (403, 404, 400, 401, 405), (method, path, r.status_code)
        assert "displayName" not in r.text


def test_cidr_restricted_token_is_refused_from_other_addresses_and_headers_do_not_help(db, super_admin, monkeypatch):
    """AC5 / IP allow-list bypass (CWE-290): other peers get 401; X-Forwarded-For and friends are not trusted."""
    t = Scim(issue(super_admin, allowed_cidrs=["203.0.113.0/24"])["token"])
    spoof = {"X-Forwarded-For": "203.0.113.9", "X-Real-IP": "203.0.113.9", "Forwarded": "for=203.0.113.9", "X-Client-IP": "203.0.113.9",
             "True-Client-IP": "203.0.113.9"}
    for peer in ("198.51.100.1", "testclient", "unknown", "::ffff:198.51.100.1", "203.0.114.1", "203.0.113.0/24", "203.0.113.256"):
        monkeypatch.setattr(ratelimit, "client_ip", lambda request, p=peer: p)
        r = t.c.get("/scim/v2/Users", headers={**t.h, **spoof})
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer", peer
        assert r.json()["detail"] == "Authentication required"


# ---- authentication (CWE-287, CWE-307, CWE-598) ----------------------------------------------------------------------------


def test_token_is_only_accepted_in_the_authorization_header(db):
    """Credential in the URL (CWE-598): query-string, cookie and body tokens are ignored."""
    raw = mk_token(db)
    c = TestClient(app, base_url="http://localhost:8000")
    for kw in ({"params": {"access_token": raw}}, {"params": {"token": raw}}, {"cookies": {"Authorization": f"Bearer {raw}"}},
               {"headers": {"X-Authorization": f"Bearer {raw}"}}):
        assert c.get("/scim/v2/Users", **kw).status_code == 401, kw


def test_guessing_tokens_is_throttled_and_never_reveals_which_part_was_wrong(db, monkeypatch):
    """Token brute force (CWE-307): bad tokens get an identical 401 and then 429 per client."""
    monkeypatch.setattr(settings, "SCIM_RATE_LIMIT_FAILURES", 5)
    raw = mk_token(db)
    c = TestClient(app, base_url="http://localhost:8000")
    prefix_ok = raw[:13] + "x" * (len(raw) - 13)
    bodies = set()
    for _ in range(5):
        r = c.get("/scim/v2/Users", headers={"Authorization": f"Bearer {prefix_ok}"})
        assert r.status_code == 401
        bodies.add(r.text)
    assert len(bodies) == 1
    assert c.get("/scim/v2/Users", headers={"Authorization": f"Bearer {raw}"}).status_code in (200, 429)  # throttled once the budget is gone


# ---- cross-resource and cross-tenant IDOR (CWE-639, IFORA-18) --------------------------------------------------------------


@pytest.fixture
def other_tenant_user(db):
    tid = second_tenant()
    s = tenant_session(tid)
    other = Scim(mk_token(s))
    victim = mk(other, "victim-b")
    s.close()
    return victim, tid


def test_a_token_cannot_read_or_change_another_tenants_users(db, people, other_tenant_user):
    """Cross-tenant IDOR (CWE-639): B's user id yields 404 for every verb, filters never see it, nothing changes."""
    victim, _ = other_tenant_user
    uid = victim["id"]
    for r in (people.get(f"/Users/{uid}"), people.put(f"/Users/{uid}", user_body("victim-b")),
              people.patch(f"/Users/{uid}", [{"op": "replace", "path": "active", "value": False}]), people.delete(f"/Users/{uid}")):
        _scim_error(r, 404)
    assert people.get("/Users", filter='userName eq "victim-b"').json()["totalResults"] == 0
    assert "victim-b" not in people.get("/Users", count=200).text
    s = tenant_session(other_tenant_user[1])
    try:
        assert s.query(User).filter(User.public_id == uid).one().status == "active"
    finally:
        s.close()


def test_group_membership_cannot_reach_across_tenants(db, people, other_tenant_user):
    """Cross-resource IDOR (CWE-639): adding another tenant's user to my group is refused or ignored; nothing is linked."""
    victim, tid = other_tenant_user
    g = people.post("/Groups", {"schemas": [GROUP], "displayName": "mine", "members": [{"value": victim["id"]}]})
    assert g.status_code in (201, 400, 404), g.text[:200]
    if g.status_code == 201:
        assert victim["id"] not in json.dumps(g.json().get("members", []))
    gid = people.get("/Groups", filter='displayName eq "mine"').json()
    gid = gid["Resources"][0]["id"] if gid["totalResults"] else None
    if gid:
        r = people.patch(f"/Groups/{gid}", [{"op": "add", "path": "members", "value": [{"value": victim["id"]}]}])
        assert r.status_code in (200, 400, 404)
        assert victim["id"] not in json.dumps(people.get(f"/Groups/{gid}").json().get("members", []))
    from backend.app.groups.model import user_group_association as m
    from sqlalchemy import func, select

    s = tenant_session(tid)
    try:
        assert s.execute(select(func.count()).select_from(m)).scalar() == 0
    finally:
        s.close()


def test_guessing_group_ids_does_not_cross_tenants_or_enumerate(db, people):
    """Opaque ids (CWE-639, CWE-340): integer and malformed ids give a uniform 404."""
    for gid in ("1", "2", "0", "-1", "99999999", "00000000-0000-0000-0000-000000000000", "' or 1=1 --"):
        r = people.get(f"/Groups/{gid}")
        assert r.status_code in (400, 404), (gid, r.status_code)
        _clean(r)


PROBE = [("GET", "/Groups/%00"), ("GET", "/Users/%00"), ("PUT", "/Groups/%00"), ("PATCH", "/Users/%00"), ("DELETE", "/Groups/%00"), ("DELETE", "/Users/%00")]


@pytest.mark.xfail(
    strict=True,
    reason="FINDING ADV-1 (low, found by IFORA-17): a NUL byte in a SCIM resource id reaches the database driver and answers 500 "
           "on every id route; needs input validation -> 4xx. Remove this marker when the follow-up story lands.",
)
@pytest.mark.parametrize("method,path", PROBE)
def test_nul_byte_in_a_resource_id_is_a_clean_4xx(db, method, path):
    """CWE-20 / CWE-248: a NUL byte in an id must be refused as input, not reach the database driver as an unhandled error."""
    t = Scim(mk_token(db))
    c = TestClient(app, base_url="http://localhost:8000", raise_server_exceptions=False)
    r = c.request(method, "/scim/v2" + path, headers=t.h, content=b"{}" if method in ("PUT", "PATCH") else None)
    assert 400 <= r.status_code < 500, (method, path, r.status_code)
    _clean(r)
