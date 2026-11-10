"""Governance metadata on applications: owner, sensitivity, review date, tags, attributes (same vocabulary as groups)."""

from tests.conftest import make_user
from tests.test_applications import mkapp


def test_defaults_are_empty(super_admin):
    a = mkapp(super_admin)
    assert (a["owner_user_id"], a["sensitivity"], a["review_by"], a["tags"], a["attributes"]) == (None, None, None, [], {})


def test_create_with_metadata_and_filters(super_admin, db):
    owner = make_user(db, "app.owner@example.com")
    a = mkapp(super_admin, owner_user_id=owner.id, sensitivity="high", review_by="2027-01-31", tags=["Finance", "tier-1"],
              attributes={"cost_center": "CC-9", "vendor": "Acme"})
    assert (a["owner_user_id"], a["sensitivity"], a["review_by"], a["tags"]) == (owner.id, "high", "2027-01-31", ["finance", "tier-1"])
    assert a["attributes"] == {"cost_center": "CC-9", "vendor": "Acme"}
    mkapp(super_admin, name="Other")
    names = lambda qs: [x["name"] for x in super_admin.get("/admin/applications" + qs).json()["items"]]  # noqa: E731
    assert names(f"?owner_user_id={owner.id}") == ["Wiki"] and names("?sensitivity=high") == ["Wiki"] and names("?tag=FINANCE") == ["Wiki"]
    assert names("?sensitivity=low") == []


def test_update_without_metadata_keeps_it_and_sent_metadata_replaces_it(super_admin, db):
    owner = make_user(db, "app.owner2@example.com")
    a = mkapp(super_admin, owner_user_id=owner.id, sensitivity="medium", tags=["x"], attributes={"k": "v"})
    base = {"name": "Wiki", "sign_on_mode": "bookmark", "launch_url": "https://wiki.example.com/", "description": "renamed"}
    r = super_admin.put(f"/admin/applications/{a['id']}", base)       # an older client sends none of the metadata
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["description"], j["owner_user_id"], j["sensitivity"], j["tags"], j["attributes"]) == ("renamed", owner.id, "medium", ["x"], {"k": "v"})
    r = super_admin.put(f"/admin/applications/{a['id']}", {**base, "owner_user_id": None, "tags": []})   # explicit clear
    j = r.json()
    assert j["owner_user_id"] is None and j["tags"] == [] and j["sensitivity"] == "medium" and j["attributes"] == {"k": "v"}


def test_validation(super_admin):
    for bad in ({"sensitivity": "extreme"}, {"owner_user_id": 999999}, {"tags": ["Bad Tag!"]}, {"attributes": {"Bad Key": "v"}}, {"attributes": {"k": 1}}):
        r = super_admin.post("/admin/applications", {"name": "B", "sign_on_mode": "none", **bad})
        assert r.status_code == 422, (bad, r.text)


def test_owner_deletion_clears_the_owner(super_admin, db):
    owner = make_user(db, "app.owner3@example.com")
    a = mkapp(super_admin, owner_user_id=owner.id)
    super_admin.delete(f"/admin/users/{owner.id}")
    assert super_admin.get(f"/admin/applications/{a['id']}").json()["owner_user_id"] is None
