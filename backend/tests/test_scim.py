"""SCIM 2.0 server (ADR 007): auth, tenancy, users, groups, filters, PATCH shapes, safety rails."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.api import app
from backend.app.audit.model import AuditEvent
from backend.app.config import settings
from backend.app.scim import auth as scim_auth
from backend.app.scim import filter as scim_filter
from backend.app.scim.models import ScimToken
from backend.app.tenancy import Tenant, tenant_session, unscoped
from tests.conftest import Api, make_user

ENT = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
PROF = "urn:identityforge:params:scim:schemas:extension:profile:2.0:User"
PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERR = "urn:ietf:params:scim:api:messages:2.0:Error"


def mk_token(db, expires_in=None, revoked=False):
    raw = scim_auth.new_token()
    db.add(ScimToken(
        name="idp", token_hash=scim_auth.hash_token(raw), token_prefix=raw[:13],
        expires_at=datetime.now(timezone.utc) + expires_in if expires_in else None,
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    ))
    db.commit()
    return raw


class Scim:
    def __init__(self, token):
        self.c = TestClient(app, base_url="http://localhost:8000")
        self.h = {"Authorization": f"Bearer {token}", "Content-Type": "application/scim+json"}

    def get(self, path, **params):
        return self.c.get("/scim/v2" + path, params=params, headers=self.h)

    def post(self, path, body):
        return self.c.post("/scim/v2" + path, content=json.dumps(body), headers=self.h)

    def put(self, path, body, **h):
        return self.c.put("/scim/v2" + path, content=json.dumps(body), headers={**self.h, **h})

    def patch(self, path, ops, **h):
        return self.c.patch("/scim/v2" + path, content=json.dumps({"schemas": [PATCH], "Operations": ops}), headers={**self.h, **h})

    def delete(self, path, **h):
        return self.c.delete("/scim/v2" + path, headers={**self.h, **h})


@pytest.fixture
def scim(db):
    return Scim(mk_token(db))


def user_body(name="jdoe", email=None, **kw):
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": name, "name": {"givenName": "Jane", "familyName": "Doe"},
        "emails": [{"value": email or f"{name}@example.com", "type": "work", "primary": True}],
        "active": True, **kw,
    }


def mk(scim, name="jdoe", **kw):
    r = scim.post("/Users", user_body(name, **kw))
    assert r.status_code == 201, r.text
    return r.json()


def stored(db, public_id):
    from backend.app.users.model import User

    db.expire_all()
    return db.query(User).filter(User.public_id == public_id).one()


def second_tenant():
    from backend.app.db import SessionLocal

    s = SessionLocal()
    with unscoped(s):
        t = s.query(Tenant).filter(Tenant.slug == "other").first()
        if t is None:
            t = Tenant(slug="other", name="Other")
            s.add(t)
            s.commit()
        tid = t.id
    s.close()
    return tid


# ---- authentication -----------------------------------------------------------------------------

@pytest.mark.parametrize("header", [None, "Bearer", "Bearer nope", "Basic abc", "Bearer idf_scim_" + "x" * 43])
def test_bad_credentials_are_uniform_401(header):
    c = TestClient(app, base_url="http://localhost:8000")
    r = c.get("/scim/v2/Users", headers={"Authorization": header} if header else {})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.headers["content-type"].startswith("application/scim+json")
    assert r.json() == {"schemas": [ERR], "status": "401", "detail": "Authentication required"}


def test_every_endpoint_requires_a_token():
    c = TestClient(app, base_url="http://localhost:8000")
    for method, path in [("get", "/Users"), ("get", "/Groups"), ("get", "/Users/x"), ("get", "/Schemas"),
                         ("get", "/ServiceProviderConfig"), ("get", "/ResourceTypes"), ("post", "/Users"),
                         ("patch", "/Users/x"), ("delete", "/Groups/1"), ("post", "/Bulk")]:
        assert getattr(c, method)("/scim/v2" + path).status_code == 401, path


def test_session_cookie_does_not_authenticate_scim(admin):
    assert admin.c.get("/scim/v2/Users").status_code == 401


def test_revoked_and_expired_tokens_rejected_and_audited(db):
    revoked, expired = mk_token(db, revoked=True), mk_token(db, expires_in=timedelta(seconds=-5))
    ok = mk_token(db, expires_in=timedelta(days=1))
    assert Scim(ok).get("/Users").status_code == 200
    for t in (revoked, expired):
        assert Scim(t).get("/Users").status_code == 401
    reasons = sorted(e.event_metadata["reason"] for e in db.query(AuditEvent).filter(AuditEvent.action == "SCIM_AUTH_FAILED"))
    assert reasons == ["expired", "revoked"]


def test_token_is_stored_hashed_only(db):
    raw = mk_token(db)
    row = db.query(ScimToken).one()
    assert raw not in (row.token_hash, row.token_prefix) and len(row.token_hash) == 64
    assert row.token_hash == scim_auth.hash_token(raw)


def test_failed_auth_rate_limited(monkeypatch):
    monkeypatch.setattr(settings, "SCIM_RATE_LIMIT_FAILURES", 3)
    c = TestClient(app, base_url="http://localhost:8000")
    codes = [c.get("/scim/v2/Users", headers={"Authorization": "Bearer idf_scim_bad"}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
    assert c.get("/scim/v2/Users").json()["status"] == "429"


def test_per_token_request_rate_limit(db, monkeypatch):
    monkeypatch.setattr(settings, "SCIM_RATE_LIMIT_REQUESTS_PER_MINUTE", 2)
    s = Scim(mk_token(db))
    assert [s.get("/Users").status_code for _ in range(3)] == [200, 200, 429]


# ---- admin token API -------------------------------------------------------------------------------

def test_token_admin_api(super_admin, admin, member, db):
    assert member.get("/admin/scim/tokens").status_code == 403
    assert admin.post("/admin/scim/tokens", {"name": "x"}).status_code in (401, 403)
    r = super_admin.post("/admin/scim/tokens", {"name": "Okta", "expires_in_days": 30})
    assert r.status_code == 201
    body = r.json()
    assert body["token"].startswith("idf_scim_") and body["base_url"].endswith("/scim/v2") and body["expires_at"]
    listing = super_admin.get("/admin/scim/tokens").json()
    assert body["token"] not in json.dumps(listing["items"]) and listing["items"][0]["status"] == "active"
    assert Scim(body["token"]).get("/Users").status_code == 200
    # revocation: any admin; takes effect immediately
    assert super_admin.delete(f"/admin/scim/tokens/{body['id']}").json()["status"] == "revoked"
    assert Scim(body["token"]).get("/Users").status_code == 401
    # audited, and no secret in the audit trail
    events = db.query(AuditEvent).filter(AuditEvent.action.in_(["SCIM_TOKEN_CREATED", "SCIM_TOKEN_REVOKED"])).all()
    assert len(events) == 2 and body["token"] not in json.dumps([e.to_dict() for e in events])


def test_admin_non_super_cannot_create(db):
    u = make_user(db, "plain-admin@example.com", admin=True)
    a = Api()
    assert a.login(u.email).status_code == 200
    assert a.post("/admin/scim/tokens", {"name": "x"}).status_code == 403
    assert a.get("/admin/scim/tokens").status_code == 200


def test_token_validation(super_admin):
    assert super_admin.post("/admin/scim/tokens", {"name": ""}).status_code == 422
    assert super_admin.post("/admin/scim/tokens", {"name": "x", "expires_in_days": 0}).status_code == 422
    assert super_admin.delete("/admin/scim/tokens/9999").status_code == 404


# ---- tenancy ---------------------------------------------------------------------------------------

def test_cross_tenant_isolation(db, scim):
    tid = second_tenant()
    other_db = tenant_session(tid)
    other = Scim(mk_token(other_db))
    mine = mk(scim, "alice")
    assert scim.post("/Groups", {"displayName": "Eng", "members": [{"value": mine["id"]}]}).status_code == 201
    # other tenant sees nothing and cannot touch anything
    assert other.get("/Users").json()["totalResults"] == 0
    assert other.get("/Groups").json()["totalResults"] == 0
    assert other.get(f"/Users/{mine['id']}").status_code == 404
    assert other.patch(f"/Users/{mine['id']}", [{"op": "replace", "path": "active", "value": False}]).status_code == 404
    assert other.delete(f"/Users/{mine['id']}").status_code == 404
    assert other.get("/Users", filter='userName eq "alice"').json()["totalResults"] == 0
    assert other.get("/Groups/1").status_code == 404
    # the same names are free in the other tenant; members must belong to the caller's tenant
    assert other.post("/Users", user_body("alice")).status_code == 201
    assert other.post("/Groups", {"displayName": "Eng", "members": [{"value": mine["id"]}]}).status_code == 400
    assert scim.get("/Users").json()["totalResults"] == 1
    other_db.close()


# ---- users: create / get / list ---------------------------------------------------------------------

def test_create_get_roundtrip(scim, db):
    r = scim.post("/Users", user_body("JDoe", externalId="ext-1", title="Engineer", locale="en-GB",
                                      phoneNumbers=[{"value": "+44 1", "type": "work"}], **{
        ENT: {"department": "Sales", "employeeNumber": "E1", "costCenter": "CC9", "manager": {"value": "boss-1"}}}))
    assert r.status_code == 201
    assert r.headers["content-type"].startswith("application/scim+json")
    u = r.json()
    assert u["userName"] == "jdoe" and u["externalId"] == "ext-1" and u["active"] is True
    assert u["emails"][0]["value"] == "jdoe@example.com" and u["name"]["givenName"] == "Jane"
    assert u[ENT] == {"department": "Sales", "costCenter": "CC9", "employeeNumber": "E1", "manager": {"value": "boss-1"}}
    assert u["title"] == "Engineer" and u["phoneNumbers"][0]["value"] == "+44 1"
    assert u["meta"]["resourceType"] == "User" and u["meta"]["location"].endswith(f"/scim/v2/Users/{u['id']}")
    assert r.headers["etag"] == u["meta"]["version"] and r.headers["location"] == u["meta"]["location"]
    g = scim.get(f"/Users/{u['id']}")
    assert g.status_code == 200 and g.json()["id"] == u["id"] and g.headers["etag"] == r.headers["etag"]
    row = stored(db, u["id"])
    assert row.get_profile_attributes()["department"] == "Sales" and row.get_profile_attributes()["phone"] == "+44 1"
    assert "password" not in json.dumps(u).lower()


def test_created_user_has_no_usable_password_and_ignores_password_attribute(scim, db):
    u = mk(scim, "pw", password="Sup3rSecret!password")
    assert "Sup3rSecret" not in json.dumps(u)
    anon = Api()
    assert anon.login("pw@example.com", "Sup3rSecret!password").status_code == 401
    row = stored(db, u["id"])
    assert not row.verify_password("Sup3rSecret!password")


def test_username_may_be_email_and_supplies_email(scim):
    r = scim.post("/Users", {"userName": "Bob@Example.com", "name": {"givenName": "B", "familyName": "O"}})
    assert r.status_code == 201
    assert r.json()["emails"][0]["value"] == "bob@example.com" and r.json()["userName"] == "bob@example.com"


@pytest.mark.parametrize("mutate,msg", [
    (lambda b: b.pop("userName"), "userName"),
    (lambda b: b.update(userName="a b"), "userName"),
    (lambda b: b.update(name={"givenName": "x"}), "familyName"),
    (lambda b: b.pop("name"), "name"),
    (lambda b: b.update(emails=[{"value": "not-an-email"}]), "Email"),
    (lambda b: b.update(active="maybe"), "active"),
    (lambda b: b.update(timezone="Mars/Base"), "Time zone"),
    (lambda b: b.update(title="x" * 600), "limited"),
    (lambda b: b.update({ENT: {"department": {"a": 1}}}), "simple"),
])
def test_user_validation_errors(scim, mutate, msg):
    b = user_body("vv")
    mutate(b)
    r = scim.post("/Users", b)
    assert r.status_code == 400 and r.json()["scimType"] == "invalidValue" and msg in r.json()["detail"], r.text


def test_uniqueness_conflicts(scim):
    mk(scim, "dup", externalId="e1")
    for body in (user_body("dup", email="other@example.com"),
                 user_body("different", email="dup@example.com"),
                 user_body("third", email="third@example.com", externalId="e1"),
                 user_body("DUP", email="x@example.com")):
        r = scim.post("/Users", body)
        assert r.status_code == 409 and r.json()["scimType"] == "uniqueness", r.text
    other = mk(scim, "someone")
    r = scim.patch(f"/Users/{other['id']}", [{"op": "replace", "path": "userName", "value": "dup"}])
    assert r.status_code == 409 and r.json()["scimType"] == "uniqueness"


def test_entra_lookup_before_create(scim):
    assert scim.get("/Users", filter='userName eq "new.user@example.com"').json() == {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"], "totalResults": 0, "startIndex": 1,
        "itemsPerPage": 0, "Resources": []}
    mk(scim, "new.user@example.com", email="new.user@example.com")
    r = scim.get("/Users", filter='userName eq "NEW.user@example.com"').json()
    assert r["totalResults"] == 1 and r["Resources"][0]["userName"] == "new.user@example.com"


def test_pagination(scim):
    for i in range(7):
        mk(scim, f"user{i}")
    p1 = scim.get("/Users", startIndex=1, count=3).json()
    p3 = scim.get("/Users", startIndex=7, count=3).json()
    assert p1["totalResults"] == 7 and p1["itemsPerPage"] == 3 and p1["startIndex"] == 1
    assert [u["userName"] for u in p1["Resources"]] == ["user0", "user1", "user2"]
    assert [u["userName"] for u in p3["Resources"]] == ["user6"] and p3["startIndex"] == 7
    only_count = scim.get("/Users", count=0).json()
    assert only_count["totalResults"] == 7 and only_count["Resources"] == []
    assert scim.get("/Users", startIndex=-5, count=1).json()["startIndex"] == 1
    assert scim.get("/Users", startIndex=100).json()["Resources"] == []
    assert scim.get("/Users", count=100000).json()["itemsPerPage"] == 7  # capped at 200, 7 exist
    assert scim.get("/Users", count="abc").status_code == 400


# ---- filters ------------------------------------------------------------------------------------------

@pytest.fixture
def people(scim):
    mk(scim, "anna", externalId="x-anna", **{ENT: {"department": "Sales"}})
    b = user_body("bob", email="bob@corp.io")
    b["name"] = {"givenName": "Bob", "familyName": "Stone"}
    b["active"] = False
    assert scim.post("/Users", b).status_code == 201
    mk(scim, "carl")
    return scim


@pytest.mark.parametrize("f,expected", [
    ('userName eq "anna"', {"anna"}),
    ('USERNAME EQ "ANNA"', {"anna"}),
    ('userName ne "anna"', {"bob", "carl"}),
    ('userName co "ar"', {"carl"}),
    ('userName sw "b"', {"bob"}),
    ('userName ew "l"', {"carl"}),
    ('externalId pr', {"anna"}),
    ('externalId eq "x-anna"', {"anna"}),
    ('active eq false', {"bob"}),
    ('active eq true', {"anna", "carl"}),
    ('active eq "False"', {"bob"}),
    ('name.familyName eq "stone"', {"bob"}),
    ('emails.value ew "corp.io"', {"bob"}),
    ('userName eq "anna" or userName eq "bob"', {"anna", "bob"}),
    ('userName sw "a" and active eq true', {"anna"}),
    ('userName eq "bob" or userName sw "a" and active eq false', {"bob"}),  # and binds tighter
    ('(userName eq "bob" or userName sw "a") and active eq true', {"anna"}),
    ('userName co "%"', set()),   # LIKE wildcards are escaped
    ('userName co "_"', set()),
    ("userName eq \"x' OR '1'='1\"", set()),
    ('userName eq "a\\"; DROP TABLE users;--"', set()),
])
def test_filters(people, f, expected):
    r = people.get("/Users", filter=f)
    assert r.status_code == 200, r.text
    assert {u["userName"] for u in r.json()["Resources"]} == expected
    assert people.get("/Users").json()["totalResults"] == 3  # nothing was dropped


@pytest.mark.parametrize("f", [
    'userName xx "a"', 'unknown eq "a"', 'userName eq', 'userName eq "unterminated', '(userName eq "a"',
    'userName eq "a")', 'userName gt 5', 'not userName eq "a"', 'emails[type eq "work"].bogus eq "a"',
    'password eq "x"', 'is_admin eq true', 'userName eq a', '', 'userName eq "a" and', 'and userName eq "a"',
    'active co "t"', "(" * 30 + 'userName eq "a"' + ")" * 30, 'userName eq "' + "a" * 1100 + '"',
    " or ".join(['userName eq "a"'] * 40),
])
def test_malformed_filters_are_400_invalid_filter(people, f):
    r = people.get("/Users", filter=f)
    assert r.status_code == 400 and r.json()["scimType"] == "invalidFilter", (f, r.text)


def test_filter_parser_precedence_and_escapes():
    node = scim_filter.parse('a eq "1" or b eq "2" and c pr')
    assert node[0] == "or" and node[2][0] == "and"
    assert scim_filter.parse('a eq "x\\"y"')[3] == 'x"y'
    assert scim_filter.parse("a eq true")[3] is True


# ---- PATCH ---------------------------------------------------------------------------------------------

def test_okta_deactivate_and_reactivate_path_shapes(scim, db):
    u = mk(scim, "okta")
    assert scim.patch(f"/Users/{u['id']}", [{"op": "replace", "path": "active", "value": False}]).json()["active"] is False
    assert stored(db, u["id"]).status == "inactive"
    assert scim.patch(f"/Users/{u['id']}", [{"op": "replace", "value": {"active": True}}]).json()["active"] is True
    assert stored(db, u["id"]).status == "active"


def test_entra_string_booleans_and_capitalised_ops(scim):
    u = mk(scim, "entra")
    r = scim.patch(f"/Users/{u['id']}", [{"op": "Replace", "path": "active", "value": "False"}])
    assert r.status_code == 200 and r.json()["active"] is False
    r = scim.patch(f"/Users/{u['id']}", [{"op": "Replace", "path": "active", "value": "True"}])
    assert r.json()["active"] is True
    assert scim.patch(f"/Users/{u['id']}", [{"op": "Replace", "path": "active", "value": "banana"}]).status_code == 400


def test_entra_attribute_paths(scim):
    u = mk(scim, "paths")
    ops = [
        {"op": "Replace", "path": "name.givenName", "value": "Janet"},
        {"op": "Add", "path": f"{ENT}:department", "value": "Finance"},
        {"op": "Add", "path": f"{ENT}:manager", "value": "mgr-7"},
        {"op": "Replace", "path": 'emails[type eq "work"].value', "value": "janet@example.com"},
        {"op": "Add", "path": 'phoneNumbers[type eq "work"].value', "value": "555-0100"},
        {"op": "Add", "path": "title", "value": "Lead"},
        {"op": "Add", "path": "addresses[type eq \"work\"].streetAddress", "value": "ignored"},
        {"op": "Add", "path": "password", "value": "ignored"},
    ]
    r = scim.patch(f"/Users/{u['id']}", ops)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["name"]["givenName"] == "Janet" and b[ENT]["department"] == "Finance" and b[ENT]["manager"] == {"value": "mgr-7"}
    assert b["emails"][0]["value"] == "janet@example.com" and b["phoneNumbers"][0]["value"] == "555-0100"
    assert b["title"] == "Lead"
    r = scim.patch(f"/Users/{u['id']}", [{"op": "remove", "path": "title"}, {"op": "remove", "path": f"{ENT}:department"},
                                         {"op": "remove", "path": "phoneNumbers"}])
    b = r.json()
    assert "title" not in b and "department" not in b.get(ENT, {}) and "phoneNumbers" not in b


def test_pathless_patch_with_dotted_urn_and_nested_keys(scim):
    u = mk(scim, "pathless")
    r = scim.patch(f"/Users/{u['id']}", [{"op": "replace", "value": {
        "name.familyName": "Smith", f"{ENT}:costCenter": "CC1", ENT: {"employeeNumber": "42"},
        "title": "T", "id": "ignored", "meta": {"x": 1}, "groups": []}}])
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["name"]["familyName"] == "Smith" and b[ENT]["costCenter"] == "CC1" and b[ENT]["employeeNumber"] == "42"
    assert b["id"] == u["id"]


def test_patch_errors(scim):
    u = mk(scim, "errs")
    p = lambda ops: scim.patch(f"/Users/{u['id']}", ops)  # noqa: E731
    r = p([{"op": "bogus", "path": "title", "value": "x"}])
    assert r.status_code == 400 and r.json()["scimType"] == "invalidSyntax"
    assert p([{"op": "add", "path": "title"}]).json()["scimType"] == "invalidValue"
    assert p([{"op": "remove"}]).json()["scimType"] == "noTarget"
    assert p([{"op": "add", "value": "notobject"}]).json()["scimType"] == "invalidValue"
    assert p([{"op": "replace", "path": "id", "value": "x"}]).json()["scimType"] == "mutability"
    assert p([{"op": "replace", "path": "emails[value eq \"zzz\" or type eq \"q\"].value", "value": "a@b.io"}]).json()["scimType"] == "noTarget"
    assert p([{"op": "replace", "path": "((bad", "value": "x"}]).json()["scimType"] == "invalidPath"
    assert p([]).status_code == 400 and p("nope").status_code == 400
    assert scim.patch(f"/Users/{u['id']}", [{"op": "add", "path": "title", "value": "x"}] * 501).status_code == 413
    # a failed PATCH changes nothing (atomic)
    r = p([{"op": "replace", "path": "title", "value": "half"}, {"op": "replace", "path": "timezone", "value": "Nope"}])
    assert r.status_code == 400 and "title" not in scim.get(f"/Users/{u['id']}").json()


def test_put_replaces_and_clears(scim):
    u = mk(scim, "putter", title="Boss", externalId="e9", **{ENT: {"department": "Ops"}})
    body = user_body("putter")
    body["name"]["givenName"] = "Renamed"
    r = scim.put(f"/Users/{u['id']}", body)
    assert r.status_code == 200
    b = r.json()
    assert b["name"]["givenName"] == "Renamed" and "title" not in b and "externalId" not in b and ENT not in b
    assert b["id"] == u["id"] and b["meta"]["created"] == u["meta"]["created"]


def test_profile_catalog_types_and_unknown_attributes(scim, super_admin):
    assert super_admin.post("/admin/profile-attributes", {"key": "badge", "display_name": "Badge", "data_type": "number"}).status_code == 201
    assert super_admin.post("/admin/profile-attributes", {"key": "remote", "display_name": "Remote", "data_type": "boolean"}).status_code == 201
    assert super_admin.post("/admin/profile-attributes", {"key": "tier", "display_name": "Tier", "data_type": "enum", "enum_options": ["gold", "silver"]}).status_code == 201
    u = mk(scim, "typed", **{PROF: {"badge": "42", "remote": "True", "tier": "gold"}})
    assert u[PROF] == {"badge": 42, "remote": True, "tier": "gold"}  # Entra-style string values coerced by the catalog
    base = f"/Users/{u['id']}"
    assert scim.patch(base, [{"op": "replace", "path": f"{PROF}:tier", "value": "bronze"}]).json()["scimType"] == "invalidValue"
    assert scim.patch(base, [{"op": "replace", "path": f"{PROF}:remote", "value": "False"}]).json()[PROF]["remote"] is False
    assert scim.post("/Users", user_body("unk", **{PROF: {"not_defined": "x"}})).status_code == 400
    # admin-managed attributes are writable through SCIM (it is an administrator-class channel)
    assert mk(scim, "adminattr", **{ENT: {"employeeNumber": "E7"}})[ENT]["employeeNumber"] == "E7"


def test_legacy_profile_values_survive_scim_updates(scim, db):
    u = mk(scim, "legacy")
    row = stored(db, u["id"])
    row.set_profile_attributes({**row.get_profile_attributes(), "old_undefined_key": "keep"})
    db.commit()
    scim.patch(f"/Users/{u['id']}", [{"op": "add", "path": "title", "value": "T"}])
    assert stored(db, u["id"]).get_profile_attributes()["old_undefined_key"] == "keep"


# ---- lifecycle -------------------------------------------------------------------------------------------

def test_deactivation_revokes_sessions_and_blocks_login_and_delete_is_soft(scim, db):
    member_user = make_user(db, "alive@example.com")
    api = Api()
    assert api.login("alive@example.com").status_code == 200
    assert api.c.get("/api/v1/me").status_code == 200
    r = scim.get("/Users", filter='userName eq "alive"')
    uid = r.json()["Resources"][0]["id"]
    assert scim.delete(f"/Users/{uid}").status_code == 204
    assert api.c.get("/api/v1/me").status_code == 401  # session revoked
    assert Api().login("alive@example.com").status_code in (401, 403)
    again = scim.delete(f"/Users/{uid}")
    assert again.status_code == 204  # idempotent
    still = scim.get(f"/Users/{uid}")
    assert still.status_code == 200 and still.json()["active"] is False  # not hard deleted
    assert scim.patch(f"/Users/{uid}", [{"op": "replace", "path": "active", "value": True}]).json()["active"] is True
    assert Api().login("alive@example.com").status_code == 200
    actions = [e.action for e in db.query(AuditEvent).order_by(AuditEvent.id) if e.action.startswith("SCIM_USER")]
    assert actions == ["SCIM_USER_DEACTIVATED", "SCIM_USER_ACTIVATED"]
    assert member_user.id


def test_deactivation_revokes_oidc_refresh_tokens(scim, db):
    from backend.app.oidc.models import RefreshToken

    u = mk(scim, "oidcuser")
    row = stored(db, u["id"])
    from backend.app.oidc.models import OIDCClient

    client = OIDCClient(name="c", client_id="cid1", client_type="public", token_endpoint_auth_method="none",
                        redirect_uris=["https://a.example/cb"], post_logout_redirect_uris=[],
                        allowed_scopes=["openid"], grant_types=["authorization_code"], status="active")
    db.add(client)
    db.commit()
    now = datetime.now(timezone.utc)
    db.add(RefreshToken(token_hash="h" * 64, family_id="f", client_pk=client.id, user_id=row.id, scopes=["openid"],
                        auth_time=now, amr=["pwd"], expires_at=now + timedelta(days=1), absolute_expires_at=now + timedelta(days=2)))
    db.commit()
    assert scim.patch(f"/Users/{u['id']}", [{"op": "replace", "path": "active", "value": False}]).status_code == 200
    db.expire_all()
    assert db.query(RefreshToken).one().revoked_at is not None


def test_reactivation_reruns_group_rules(scim, admin, db):
    gid = admin.post("/admin/groups", {"name": "Sales team"}).json()["id"]
    rid = admin.post("/admin/group-rules", {"name": "r", "match": "all", "group_ids": [gid], "conditions": [
        {"attribute": "department", "operator": "equals", "value": "Sales"}]}).json()["id"]
    assert admin.post(f"/admin/group-rules/{rid}/activate").status_code == 200
    u = mk(scim, "salesperson", **{ENT: {"department": "Sales"}})
    assert [g["display"] for g in u["groups"]] == ["Sales team"]
    off = scim.patch(f"/Users/{u['id']}", [{"op": "replace", "path": "active", "value": False}]).json()
    assert off["groups"] == []
    on = scim.patch(f"/Users/{u['id']}", [{"op": "replace", "path": "active", "value": True}]).json()
    assert [g["display"] for g in on["groups"]] == ["Sales team"]


# ---- privilege protection ------------------------------------------------------------------------------------

def test_scim_never_grants_admin(scim, db):
    body = user_body("sneaky", is_admin=True, isAdmin=True, is_super_admin=True, roles=[{"value": "admin"}],
                     entitlements=[{"value": "admin"}], status="active", tenant_id=99)
    body[ENT] = {"is_admin": True}
    body[PROF] = {"is_admin": True}
    r = scim.post("/Users", body)
    assert r.status_code == 400  # is_admin is a reserved key, not a catalog attribute
    body.pop(PROF)
    u = scim.post("/Users", body).json()
    row = stored(db, u["id"])
    assert row.is_admin is False and row.is_super_admin is False and row.tenant_id != 99
    scim.patch(f"/Users/{u['id']}", [{"op": "add", "path": "is_admin", "value": True},
                                    {"op": "add", "value": {"is_super_admin": True, "isAdmin": True}}])
    scim.put(f"/Users/{u['id']}", {**user_body("sneaky"), "is_admin": True})
    row = stored(db, u["id"])
    assert row.is_admin is False and row.is_super_admin is False


def test_admin_accounts_are_read_only_through_scim(scim, db):
    boss = make_user(db, "boss@example.com", admin=True, username="boss")
    root = make_user(db, "root2@example.com", super_admin=True, username="root2")
    for who in (boss, root):
        r = scim.get(f"/Users/{who.public_id}")
        assert r.status_code == 200  # readable, so lookups stay consistent
        base = f"/Users/{who.public_id}"
        for resp in (
            scim.patch(base, [{"op": "replace", "path": "active", "value": False}]),
            scim.patch(base, [{"op": "replace", "path": 'emails[type eq "work"].value', "value": "evil@x.io"}]),
            scim.put(base, user_body("boss")),
            scim.delete(base),
        ):
            assert resp.status_code == 403, resp.text
        db.expire_all()
        assert db.get(type(who), who.id).status == "active" and db.get(type(who), who.id).email == who.email


def test_group_membership_does_not_grant_admin(scim, db):
    u = mk(scim, "member1")
    g = scim.post("/Groups", {"displayName": "administrators", "members": [{"value": u["id"]}]})
    assert g.status_code == 201
    assert stored(db, u["id"]).is_admin is False
    a = Api()
    a.login("member1@example.com")  # no usable password; and even then:
    assert Api().c.get("/api/v1/admin/users").status_code == 401


# ---- groups --------------------------------------------------------------------------------------------------

def test_group_crud_and_membership_sync(scim, db):
    a, b, c = (mk(scim, n)["id"] for n in ("ua", "ub", "uc"))
    r = scim.post("/Groups", {"displayName": "Eng", "externalId": "g-1", "members": [{"value": a}, {"value": b}]})
    assert r.status_code == 201
    g = r.json()
    gid = g["id"]
    assert {m["value"] for m in g["members"]} == {a, b} and g["externalId"] == "g-1"
    assert g["meta"]["resourceType"] == "Group" and r.headers["etag"]
    base = f"/Groups/{gid}"
    # add (idempotent), remove by filter, remove by value list (Entra), replace
    assert {m["value"] for m in scim.patch(base, [{"op": "add", "path": "members", "value": [{"value": c}, {"value": a}]}]).json()["members"]} == {a, b, c}
    assert {m["value"] for m in scim.patch(base, [{"op": "remove", "path": f'members[value eq "{a}"]'}]).json()["members"]} == {b, c}
    assert {m["value"] for m in scim.patch(base, [{"op": "Remove", "path": "members", "value": [{"value": b}]}]).json()["members"]} == {c}
    assert {m["value"] for m in scim.patch(base, [{"op": "replace", "path": "members", "value": [{"value": a}, {"value": b}]}]).json()["members"]} == {a, b}
    assert scim.patch(base, [{"op": "remove", "path": f'members[value eq "{c}"]'}]).status_code == 200  # not a member: no error
    # pathless add of members, rename, PUT
    assert len(scim.patch(base, [{"op": "add", "value": {"members": [{"value": c}]}}]).json()["members"]) == 3
    assert scim.patch(base, [{"op": "replace", "path": "displayName", "value": "Engineering"}]).json()["displayName"] == "Engineering"
    put = scim.put(base, {"displayName": "Eng2", "members": [{"value": c}]})
    assert put.status_code == 200 and [m["value"] for m in put.json()["members"]] == [c] and "externalId" not in put.json()
    # user resource reflects membership
    assert [x["display"] for x in scim.get(f"/Users/{c}").json()["groups"]] == ["Eng2"]
    assert scim.get(f"/Users/{a}").json()["groups"] == []
    # admin API agrees, member_count in sync
    db.expire_all()
    from backend.app.groups.model import Group

    assert db.query(Group).filter(Group.name == "Eng2").one().member_count == 1
    assert scim.delete(base).status_code == 204 and scim.get(base).status_code == 404
    kinds = {e.action for e in db.query(AuditEvent) if e.action.startswith("SCIM_GROUP")}
    assert {"SCIM_GROUP_CREATED", "SCIM_GROUP_UPDATED", "SCIM_GROUP_DELETED", "SCIM_GROUP_MEMBER_ADDED", "SCIM_GROUP_MEMBER_REMOVED"} <= kinds


def test_group_filters_and_errors(scim):
    u = mk(scim, "gm")["id"]
    scim.post("/Groups", {"displayName": "Alpha", "externalId": "ga", "members": [{"value": u}]})
    scim.post("/Groups", {"displayName": "Beta"})
    f = lambda q: {g["displayName"] for g in scim.get("/Groups", filter=q).json()["Resources"]}  # noqa: E731
    assert f('displayName eq "alpha"') == {"Alpha"}
    assert f('displayName co "et"') == {"Beta"}
    assert f(f'members.value eq "{u}"') == {"Alpha"}
    assert f(f'members.value ne "{u}"') == {"Beta"}
    assert f('externalId pr') == {"Alpha"}
    assert scim.get("/Groups", filter="members pr").status_code == 400
    assert scim.post("/Groups", {"displayName": "ALPHA"}).json()["scimType"] == "uniqueness"
    assert scim.post("/Groups", {"displayName": "New", "externalId": "ga"}).status_code == 409
    assert scim.post("/Groups", {"displayName": "Bad", "members": [{"value": "nope"}]}).json()["scimType"] == "invalidValue"
    assert scim.post("/Groups", {"displayName": ""}).status_code == 400
    assert scim.post("/Groups", {"displayName": "X", "members": "no"}).status_code == 400
    assert scim.get("/Groups/abc").status_code == 404 and scim.get("/Groups/99999").status_code == 404


def test_system_groups_are_invisible_and_immutable(scim, db):
    from backend.app.groups.model import Group

    sg = Group(name="Everyone", is_system_group=True)
    db.add(sg)
    db.commit()
    gid = str(sg.id)
    assert scim.get("/Groups").json()["totalResults"] == 0
    assert scim.get(f"/Groups/{gid}").status_code == 404
    assert scim.patch(f"/Groups/{gid}", [{"op": "replace", "path": "displayName", "value": "x"}]).status_code == 404
    assert scim.delete(f"/Groups/{gid}").status_code == 404
    assert scim.put(f"/Groups/{gid}", {"displayName": "x"}).status_code == 404


def test_rule_managed_memberships_cannot_be_removed(scim, admin, db):
    gid = admin.post("/admin/groups", {"name": "Sales team"}).json()["id"]
    rid = admin.post("/admin/group-rules", {"name": "r", "match": "all", "group_ids": [gid], "conditions": [
        {"attribute": "department", "operator": "equals", "value": "Sales"}]}).json()["id"]
    admin.post(f"/admin/group-rules/{rid}/activate")
    managed = mk(scim, "ruled", **{ENT: {"department": "Sales"}})["id"]
    manual = mk(scim, "manual")["id"]
    base = f"/Groups/{gid}"
    assert scim.patch(base, [{"op": "add", "path": "members", "value": [{"value": manual}]}]).status_code == 200
    for ops in (
        [{"op": "remove", "path": f'members[value eq "{managed}"]'}],
        [{"op": "remove", "path": "members", "value": [{"value": managed}]}],
        [{"op": "remove", "path": "members"}],
        [{"op": "replace", "path": "members", "value": [{"value": manual}]}],
    ):
        r = scim.patch(base, ops)
        assert r.status_code == 409 and r.json()["scimType"] == "mutability", r.text
    assert scim.put(base, {"displayName": "Sales team", "members": []}).status_code == 409
    got = {m["value"] for m in scim.get(base).json()["members"]}
    assert got == {managed, manual}  # nothing was applied
    # the SCIM-added membership is removable; the rule one stays; deleting a rule target is refused
    assert scim.patch(base, [{"op": "remove", "path": f'members[value eq "{manual}"]'}]).status_code == 200
    assert {m["value"] for m in scim.get(base).json()["members"]} == {managed}
    assert scim.delete(base).status_code == 409
    # adding someone who is already rule-managed is a harmless no-op
    assert scim.patch(base, [{"op": "add", "path": "members", "value": [{"value": managed}]}]).status_code == 200


# ---- protocol hygiene --------------------------------------------------------------------------------------------

def test_discovery_documents(scim):
    spc = scim.get("/ServiceProviderConfig").json()
    assert spc["patch"]["supported"] is True and spc["bulk"]["supported"] is False
    assert spc["sort"]["supported"] is False and spc["changePassword"]["supported"] is False
    assert spc["filter"] == {"supported": True, "maxResults": 200} and spc["etag"]["supported"] is True
    assert spc["authenticationSchemes"][0]["type"] == "oauthbearertoken"
    assert {r["id"] for r in scim.get("/ResourceTypes").json()["Resources"]} == {"User", "Group"}
    assert scim.get("/ResourceTypes/User").status_code == 200 and scim.get("/ResourceTypes/Nope").status_code == 404
    schemas = {s["id"] for s in scim.get("/Schemas").json()["Resources"]}
    assert "urn:ietf:params:scim:schemas:core:2.0:User" in schemas and ENT in schemas
    assert scim.get(f"/Schemas/{ENT}").status_code == 200 and scim.get("/Schemas/nope").status_code == 404


def test_unsupported_features_say_so(scim):
    assert scim.post("/Bulk", {}).status_code == 501
    assert scim.get("/Me").status_code == 501
    assert scim.post("/Users/.search", {}).status_code == 501
    assert scim.get("/Nope").json() == {"schemas": [ERR], "status": "404", "detail": "Resource not found"}
    assert scim.get("/Users", sortBy="userName").status_code == 200  # ignored, advertised as unsupported


def test_request_hygiene(scim):
    c = TestClient(app, base_url="http://localhost:8000")
    h = dict(scim.h)
    assert c.post("/scim/v2/Users", content="{not json", headers=h).json()["scimType"] == "invalidSyntax"
    assert c.post("/scim/v2/Users", content="[]", headers=h).status_code == 400
    assert c.post("/scim/v2/Users", content="{}", headers={**h, "Content-Type": "text/plain"}).status_code == 415
    big = json.dumps({"userName": "a" * (1024 * 1024 + 10)})
    r = c.post("/scim/v2/Users", content=big, headers=h)
    assert r.status_code == 413 and r.json()["status"] == "413"
    assert scim.post("/Users", {"userName": "x"}).status_code == 400
    assert scim.c.post("/scim/v2/Users", content=json.dumps(user_body("plainjson")),
                       headers={**h, "Content-Type": "application/json"}).status_code == 201
    # errors never echo input
    r = scim.post("/Users", user_body("echo", title="x" * 600))
    assert "x" * 50 not in r.text


def test_etag_preconditions(scim):
    u = mk(scim, "etagger")
    base = f"/Users/{u['id']}"
    tag = scim.get(base).headers["etag"]
    assert scim.patch(base, [{"op": "add", "path": "title", "value": "a"}], **{"If-Match": 'W/"stale"'}).status_code == 412
    ok = scim.patch(base, [{"op": "add", "path": "title", "value": "a"}], **{"If-Match": tag})
    assert ok.status_code == 200 and ok.headers["etag"] != tag
    assert scim.put(base, user_body("etagger"), **{"If-Match": tag}).status_code == 412
    assert scim.delete(base, **{"If-Match": tag}).status_code == 412
    assert scim.patch(base, [{"op": "add", "path": "title", "value": "b"}], **{"If-Match": "*"}).status_code == 200


def test_audit_trail_has_token_actor_and_no_secrets(scim, db):
    token = scim.h["Authorization"].split()[1]
    u = mk(scim, "audited", password="Sup3rSecret!password")
    scim.patch(f"/Users/{u['id']}", [{"op": "replace", "path": "title", "value": "T"}])
    events = db.query(AuditEvent).filter(AuditEvent.action.like("SCIM_USER%")).order_by(AuditEvent.id).all()
    assert [e.action for e in events] == ["SCIM_USER_CREATED", "SCIM_USER_UPDATED"]
    assert all(e.actor_type == "scim_token" and e.actor_id for e in events)
    dump = json.dumps([e.to_dict() for e in events])
    assert token not in dump and "Sup3rSecret" not in dump
    assert db.query(ScimToken).one().last_used_at is not None


def test_scim_is_not_under_api_v1(scim):
    c = TestClient(app, base_url="http://localhost:8000")
    assert c.get("/api/v1/scim/v2/Users", headers=scim.h).status_code == 404


def test_server_errors_are_generic(scim, monkeypatch):
    from backend.app.scim import routes

    def boom(*a, **k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(routes.mapping, "ingest_user", boom)
    c = TestClient(app, base_url="http://localhost:8000", raise_server_exceptions=False)
    r = c.post("/scim/v2/Users", content=json.dumps(user_body("e")), headers=scim.h)
    assert r.status_code == 500 and "secret internal detail" not in r.text and r.json()["status"] == "500"
