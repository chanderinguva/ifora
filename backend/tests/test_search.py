"""Admin global search."""

from tests.conftest import STRONG, make_user


def test_search_finds_each_kind(db, admin):
    make_user(db, "zelda@example.com", first_name="Zelda", last_name="Fitz")
    admin.post("/admin/groups", {"name": "Zelda fans"})
    r = admin.get("/admin/search", params={"q": "zel"})
    assert r.status_code == 200
    kinds = {x["kind"] for x in r.json()["results"]}
    assert {"user", "group"} <= kinds
    u = next(x for x in r.json()["results"] if x["kind"] == "user")
    assert u["subtitle"] == "zelda@example.com" and u["href"].startswith("/admin/users/")


def test_search_is_literal_and_bounded(db, admin):
    for i in range(8):
        make_user(db, f"many{i}@example.com")
    assert len([x for x in admin.get("/admin/search", params={"q": "many"}).json()["results"] if x["kind"] == "user"]) == 5
    assert admin.get("/admin/search", params={"q": "%%"}).json()["results"] == []        # wildcards do not match everything
    assert admin.get("/admin/search", params={"q": "x"}).status_code == 422
    assert admin.get("/admin/search", params={"q": "a" * 101}).status_code == 422


def test_search_needs_admin(member, anon):
    assert member.get("/admin/search", params={"q": "abc"}).status_code == 403
    assert anon.get("/admin/search", params={"q": "abc"}).status_code == 401
