"""schemas + meta on every JSON resource and list under /api/v1 (additive; ids and other fields unchanged)."""

import pytest

from backend.app.scim.envelope import LIST_URN, SCHEMA_PREFIX, envelope, resource_type
from tests.conftest import Api, make_user


@pytest.mark.parametrize("template,expected", [
    ("/api/v1/admin/users/{user_id}", "User"),
    ("/api/v1/admin/groups", "Group"),
    ("/api/v1/admin/api-tokens/{token_id}", "ApiToken"),
    ("/api/v1/admin/applications/{app_id}/self-service", "SelfService"),
    ("/api/v1/admin/policies/{pid}", "Policy"),
    ("/api/v1/admin/access", "Access"),
    ("/api/v1/admin/oidc-clients/{cid}", "OidcClient"),
])
def test_resource_type(template, expected):
    assert resource_type(template) == expected


def test_item_keeps_every_field_and_gains_schemas_and_meta():
    doc = {"id": 7, "name": "x", "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-02-01T00:00:00+00:00"}
    out = envelope(dict(doc), "/api/v1/admin/groups/{gid}", "https://api.example/api/v1/admin/groups/7?x=1", True)
    assert {k: out[k] for k in doc} == doc
    assert out["schemas"] == [SCHEMA_PREFIX + "Group"]
    assert out["meta"] == {
        "resourceType": "Group", "location": "https://api.example/api/v1/admin/groups/7",
        "created": "2026-01-01T00:00:00+00:00", "lastModified": "2026-02-01T00:00:00+00:00",
    }


def test_list_gets_the_list_urn_and_each_item_a_location():
    body = {"totalResults": 2, "startIndex": 1, "itemsPerPage": 2, "Resources": [{"id": 1}, {"id": 2}]}
    out = envelope(body, "/api/v1/admin/groups", "https://api.example/api/v1/admin/groups?count=2", False)
    assert out["schemas"] == [LIST_URN]
    assert [r["meta"]["location"] for r in out["Resources"]] == [
        "https://api.example/api/v1/admin/groups/1", "https://api.example/api/v1/admin/groups/2"]


def test_existing_scim_documents_and_non_resources_are_left_alone():
    scim = {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"], "id": "abc", "meta": {"resourceType": "User"}}
    assert envelope(dict(scim), "/api/v1/x/users/{i}", "https://h/api/v1/x/users/abc", True) == scim
    assert envelope({"ok": True}, "/api/v1/logout", "https://h/api/v1/logout", False) == {"ok": True}
    assert envelope([1, 2], "/api/v1/things", "https://h/api/v1/things", False) == [1, 2]


def admin(db):
    make_user(db, "root@example.com", super_admin=True)
    a = Api()
    assert a.login("root@example.com").status_code == 200
    return a


def test_live_list_item_and_create(db):
    a = admin(db)
    r = a.post("/admin/groups", {"name": "Envelope Team", "description": "d"})
    assert r.status_code in (200, 201), r.text
    g = r.json()
    assert g["schemas"] == [SCHEMA_PREFIX + "Group"] and g["meta"]["resourceType"] == "Group"
    assert g["meta"]["location"].endswith(f"/api/v1/admin/groups/{g['id']}")
    assert isinstance(g["id"], int)   # the id keeps its type

    one = a.get(f"/admin/groups/{g['id']}").json()
    assert one["meta"]["location"] == g["meta"]["location"]

    lst = a.get("/admin/groups").json()
    assert lst["schemas"] == [LIST_URN] and lst["totalResults"] >= 1
    assert all(i["schemas"] == [SCHEMA_PREFIX + "Group"] for i in lst["Resources"])
