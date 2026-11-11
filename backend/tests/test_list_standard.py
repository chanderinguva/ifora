"""SCIM-style list standard for admin collections (ADR 025)."""

import pytest

from tests.conftest import make_user

LIST_KEYS = {"schemas", "totalResults", "startIndex", "itemsPerPage", "Resources"}   # schemas: the ListResponse URN (scim/envelope.py)


def _people(db):
    for i, (first, last) in enumerate([("Carol", "Zed"), ("alice", "Young"), ("Bob", "Xu"), ("dave", "Wu")]):
        make_user(db, f"p{i}@example.com", first_name=first, last_name=last)


def test_envelope_and_old_names_are_gone(db, admin):
    _people(db)
    r = admin.get("/admin/users?count=2").json()
    assert set(r) == LIST_KEYS
    assert r["itemsPerPage"] == 2 and len(r["Resources"]) == 2 and r["totalResults"] >= 5 and r["startIndex"] == 1
    assert "items" not in r and "total" not in r and "page_size" not in r
    # the old parameter names are ignored, not honoured
    assert admin.get("/admin/users?page_size=1").json()["itemsPerPage"] > 1


def test_paging_is_stable_and_covers_every_row(db, admin):
    _people(db)
    total = admin.get("/admin/users?count=0").json()
    assert total["Resources"] == [] and total["itemsPerPage"] == 0 and total["totalResults"] >= 5
    seen = []
    for start in range(1, total["totalResults"] + 1, 2):
        seen += [u["id"] for u in admin.get(f"/admin/users?startIndex={start}&count=2&sortBy=last_name").json()["Resources"]]
    assert len(seen) == total["totalResults"] and len(set(seen)) == len(seen)
    assert admin.get("/admin/users?startIndex=9999&count=5").json()["Resources"] == []


def test_clamping(db, admin):
    assert admin.get("/admin/users?count=101").json()["itemsPerPage"] <= 100
    assert admin.get("/admin/users?count=-3").json()["itemsPerPage"] == 0
    assert admin.get("/admin/users?startIndex=-4").json()["startIndex"] == 1


def test_sort_is_case_insensitive_and_directional(db, admin):
    _people(db)
    asc = [u["first_name"] for u in admin.get("/admin/users?filter=email co \"@example.com\" and first_name pr&sortBy=first_name&count=100").json()["Resources"]
           if u["email"].startswith("p")]
    assert asc == sorted(asc, key=str.lower)
    desc = [u["first_name"] for u in admin.get("/admin/users?sortBy=first_name&sortOrder=descending&count=100").json()["Resources"]
            if u["email"].startswith("p")]
    assert desc == sorted(desc, key=str.lower, reverse=True)


def test_filter(db, admin):
    _people(db)
    r = admin.get('/admin/users?filter=first_name sw "al"').json()
    assert r["totalResults"] == 1 and r["Resources"][0]["email"] == "p1@example.com"
    r = admin.get('/admin/users?filter=first_name eq "Bob" or first_name eq "dave"').json()
    assert {u["email"] for u in r["Resources"]} == {"p2@example.com", "p3@example.com"}
    assert admin.get('/admin/users?filter=not (status eq "active")&count=100').status_code == 200
    # combined with the domain filters
    assert admin.get('/admin/users?q=p2&filter=first_name eq "Bob"').json()["totalResults"] == 1


@pytest.mark.parametrize("query", [
    "sortBy=password", "sortBy=profile_attributes", "sortOrder=sideways", "filter=password eq \"x\"", "filter=id eq 1",
    "filter=first_name eq", "filter=((((((((((((first_name eq \"a\"))))))))))))", "filter=first_name eq \"a\"; DROP TABLE users",
    "filter=" + "a eq \"b\" and " * 80 + "a pr",
])
def test_hostile_or_unknown_sort_and_filter_are_400(db, admin, query):
    r = admin.get("/admin/users?" + query)
    assert r.status_code in (400, 422), r.text


def test_filter_not_supported_on_python_paged_collection(db, admin):
    assert admin.get('/admin/administrators?filter=email eq "x"').status_code == 400
    r = admin.get("/admin/administrators?sortBy=email&count=1").json()
    assert set(r) == LIST_KEYS and r["itemsPerPage"] == 1


def test_groups_audit_and_jobs_use_the_envelope(db, admin):
    admin.post("/admin/groups", {"name": "Zeta"})
    admin.post("/admin/groups", {"name": "alpha"})
    g = admin.get("/admin/groups?sortBy=name&filter=name pr").json()
    names = [x["name"] for x in g["Resources"]]
    assert g["totalResults"] >= 2 and names == sorted(names, key=str.lower)
    a = admin.get('/admin/audit?filter=action eq "GROUP_CREATED"&count=1').json()
    assert set(a) == LIST_KEYS and a["totalResults"] >= 2
    newest = admin.get("/admin/audit?count=2").json()["Resources"]
    assert newest[0]["timestamp"] >= newest[1]["timestamp"]         # default order is newest first
    assert admin.get("/admin/audit?sortBy=metadata").status_code == 400
    assert set(admin.get("/admin/recipes/jobs?count=5").json()) == LIST_KEYS


def test_requires_admin(db, member):
    assert member.get("/admin/users?count=1").status_code in (401, 403)
