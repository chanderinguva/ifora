"""New accounts get a standard username/email; the username never changes; names never drive identifiers."""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.app.config import settings
from backend.app.users import naming
from backend.app.users.model import User
from tests.conftest import STRONG, make_user
from tests.test_provisioning import assign_user, enable, links, make_app, remote, run  # noqa: F401
from tests.recipe_helpers import rkey  # noqa: F401
from tests.test_scim import Scim, mk_token, user_body  # noqa: F401


@pytest.fixture(autouse=True)
def domain(monkeypatch):
    monkeypatch.setattr(settings, "PRIMARY_EMAIL_DOMAIN", "corp.example.com")


def create(admin, first, last, **kw):
    return admin.post("/admin/users", {"first_name": first, "last_name": last, "generate_password": True, **kw})


# ---- the convention ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("first,last,want", [
    ("John", "Smith", "john.smith"),
    ("José", "Müller", "jose.muller"),
    ("Siobhán", "O'Brien", "siobhan.obrien"),
    ("Mary Ann", "van der Berg", "maryann.vanderberg"),
    ("Anne-Marie", "Smith-Jones", "annemarie.smithjones"),
    ("Søren", "Ærø", "soren.aero"),
    ("李", "伟", "user"),
    ("Cher", "", "cher"),
    ("", "", "user"),
])
def test_base_names(first, last, want):
    assert naming.base_username(first, last) == want


def test_long_names_are_cut_to_leave_room_for_a_suffix():
    base = naming.base_username("a" * 100, "b" * 100)
    assert len(base) <= naming.MAX_BASE and not base.endswith(".")


def test_admin_create_without_email_or_username_builds_both(admin):
    r = create(admin, "Jane", "Doe")
    assert r.status_code == 201, r.text
    u = r.json()["user"] if "user" in r.json() else r.json()
    assert u["username"] == "jane.doe" and u["email"] == "jane.doe@corp.example.com"


def test_clashes_get_the_next_free_number_case_insensitively(db, admin):
    make_user(db, "x@other.example.com", username="John.Smith")      # the first name is already taken (any case)
    names = []
    for _ in range(3):
        r = create(admin, "John", "Smith")
        assert r.status_code == 201, r.text
        names.append((r.json().get("user") or r.json())["username"])
    assert names == ["john.smith2", "john.smith3", "john.smith4"]


def test_a_taken_email_also_counts_as_a_clash(db, admin):
    make_user(db, "jane.doe@corp.example.com", username="someone.else")
    r = create(admin, "Jane", "Doe")
    assert (r.json().get("user") or r.json())["username"] == "jane.doe2"


def test_reserved_names_are_never_handed_out(admin):
    r = create(admin, "李", "伟")                      # no Latin letters: falls back to "user", which is reserved, so user2
    assert (r.json().get("user") or r.json())["username"] == "user2"
    assert admin.post("/admin/users", {"first_name": "A", "last_name": "B", "username": "root", "generate_password": True}).status_code == 422


def test_explicit_values_still_win_and_clash_with_409(db, admin):
    r = admin.post("/admin/users", {"first_name": "A", "last_name": "B", "email": "Custom@Else.example.com", "username": "ab.custom", "generate_password": True})
    u = r.json().get("user") or r.json()
    assert r.status_code == 201 and u["email"] == "custom@else.example.com" and u["username"] == "ab.custom"
    again = admin.post("/admin/users", {"first_name": "A", "last_name": "B", "email": "other@else.example.com", "username": "AB.Custom", "generate_password": True})
    assert again.status_code == 409


def test_email_is_required_when_no_domain_is_configured(monkeypatch, admin):
    monkeypatch.setattr(settings, "PRIMARY_EMAIL_DOMAIN", "")
    assert create(admin, "No", "Domain").status_code == 422
    r = create(admin, "No", "Domain", email="nd@x.example.com")
    assert r.status_code == 201 and (r.json().get("user") or r.json())["username"] == "no.domain"


def test_suggest_previews_without_reserving(db, admin):
    make_user(db, "a@x.example.com", username="ann.lee")
    s = admin.get("/admin/users/suggest-identity", params={"first_name": "Ann", "last_name": "Lee"}).json()
    assert s == {"username": "ann.lee2", "email": "ann.lee2@corp.example.com", "email_domain": "corp.example.com"}
    assert admin.get("/admin/users/suggest-identity", params={"first_name": "Ann", "last_name": "Lee"}).json()["username"] == "ann.lee2"
    assert admin.get("/admin/users/suggest-identity").json()["username"] is None


def test_the_domain_setting_is_validated():
    from backend.app.config import Settings

    assert Settings.model_fields["PRIMARY_EMAIL_DOMAIN"] is not None
    assert Settings._primary_domain("@Corp.Example.COM ") == "corp.example.com"
    with pytest.raises(ValueError):
        Settings._primary_domain("not a domain")


# ---- the username is immutable ----------------------------------------------------------------------------------

def test_orm_refuses_a_username_change(db):
    u = make_user(db, "keep@x.example.com", username="keep.me")
    with pytest.raises(ValueError):
        u.username = "other"
    u.username = "keep.me"            # writing the same value is fine


def test_database_refuses_a_username_change_even_in_raw_sql(db):
    u = make_user(db, "raw@x.example.com", username="raw.user")
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE users SET username = 'changed' WHERE id = :i"), {"i": u.id})
        db.flush()
    db.rollback()


def test_the_admin_api_cannot_change_it_and_names_leave_identifiers_alone(db, admin, member):
    uid, before = member.user.id, dict(member.get("/me").json()["user"])
    r = admin.patch(f"/admin/users/{uid}", {"username": "hijack", "first_name": "Renamed", "last_name": "Person"})
    assert r.status_code in (200, 422), r.text
    now = admin.get(f"/admin/users/{uid}").json()
    now = now.get("user") or now
    assert now["username"] == before["username"] and now["email"] == before["email"]
    if r.status_code == 200:
        assert now["first_name"] == "Renamed" and now["last_name"] == "Person"
        assert member.get("/me").status_code == 200       # their session is untouched
        db.expire_all()
        assert db.get(User, uid).public_id == before.get("public_id", db.get(User, uid).public_id)


# ---- SCIM: an email change never breaks provisioning --------------------------------------------------------------

def test_scim_email_change_with_a_new_username_keeps_the_account(db):
    sc = Scim(mk_token(db))
    r = sc.post("/Users", user_body("pat@old.example.com", "pat@old.example.com"))
    assert r.status_code == 201, r.text
    doc = r.json()
    uid, ext = doc["id"], doc.get("externalId")
    # the IdP mirrors the new email into userName
    moved = {**user_body("pat@new.example.com", "pat@new.example.com"), "id": uid}
    r2 = sc.put(f"/Users/{uid}", moved)
    assert r2.status_code == 200, r2.text
    out = r2.json()
    assert out["id"] == uid and out["userName"] == "pat@old.example.com"         # same account, stored userName kept
    assert out["emails"][0]["value"] == "pat@new.example.com"                      # the email did change
    assert sc.get("/Users", filter='userName eq "pat@old.example.com"').json()["totalResults"] == 1
    # PATCH with a userName replace behaves the same
    r3 = sc.patch(f"/Users/{uid}", [{"op": "replace", "path": "userName", "value": "pat@third.example.com"}])
    assert r3.status_code == 200 and r3.json()["userName"] == "pat@old.example.com"


def test_scim_userName_that_belongs_to_someone_else_is_ignored_not_a_conflict(db):
    sc = Scim(mk_token(db))
    a = sc.post("/Users", user_body("ann", "ann@x.example.com")).json()
    sc.post("/Users", user_body("bob", "bob@x.example.com"))
    r = sc.put(f"/Users/{a['id']}", {**user_body("bob", "ann2@x.example.com"), "id": a["id"]})
    assert r.status_code == 200 and r.json()["userName"] == "ann"


# ---- a name change disturbs nothing downstream ---------------------------------------------------------------------

def test_name_change_updates_the_same_remote_account_and_creates_nothing(db, admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin))
    u = make_user(db, "kim@corp.example.com", username="kim.lee", first_name="Kim", last_name="Lee")
    assign_user(admin, app, u.id)
    run()
    (link,) = links(db, app)
    rid, pid = link.remote_id, u.public_id
    assert remote.n == 1
    remote.calls.clear()
    assert admin.patch(f"/admin/users/{u.id}", {"first_name": "Kim", "last_name": "Park"}).status_code == 200
    run()
    db.expire_all()
    (after,) = links(db, app)
    assert after.remote_id == rid and after.state == "synced"                  # same link, same remote account
    assert [c[0] for c in remote.calls] == ["PUT"] and remote.n == 1           # one update, no create, no lookup
    sent = remote.users[rid]
    assert sent["name"]["familyName"] == "Park" and sent["userName"] == "kim@corp.example.com"   # identifier untouched
    assert db.get(User, u.id).public_id == pid and db.get(User, u.id).username == "kim.lee"


def test_name_change_with_username_as_the_app_identifier_keeps_userName_too(db, admin, super_admin, remote):
    app = enable(super_admin, make_app(super_admin, options={"user_identifier": "username"}))
    u = make_user(db, "lou@corp.example.com", username="lou.gray", first_name="Lou", last_name="Gray")
    assign_user(admin, app, u.id)
    run()
    remote.calls.clear()
    assert admin.patch(f"/admin/users/{u.id}", {"last_name": "Green"}).status_code == 200
    run()
    assert remote.users["r1"]["userName"] == "lou.gray" and remote.users["r1"]["name"]["familyName"] == "Green" and remote.n == 1


def test_scim_name_change_keeps_the_account_group_membership_and_assignment(db, admin, super_admin, remote):
    sc = Scim(mk_token(db))
    d = sc.post("/Users", {**user_body("sam", "sam@corp.example.com"), "name": {"givenName": "Sam", "familyName": "Old"}}).json()
    app = enable(super_admin, make_app(super_admin))
    row = db.query(User).filter(User.public_id == d["id"]).one()
    assign_user(admin, app, row.id)
    run()
    remote.calls.clear()
    r = sc.put(f"/Users/{d['id']}", {**{**user_body("sam", "sam@corp.example.com"), "name": {"givenName": "Sam", "familyName": "New"}}, "id": d["id"]})
    assert r.status_code == 200
    run()
    assert remote.n == 1 and [c[0] for c in remote.calls] == ["PUT"]
    assert db.query(User).filter(User.public_id == d["id"]).count() == 1


# ---- user type is a fixed list ---------------------------------------------------------------------------------------

from backend.app.profiles.catalog import USER_TYPES  # noqa: E402


def test_user_type_is_a_dropdown_with_the_seven_values(admin):
    items = {a["key"]: a for a in admin.get("/admin/profile-attributes").json()["items"]}
    assert items["user_type"]["data_type"] == "enum" and items["user_type"]["enum_options"] == [
        "Employee", "Contingent Worker", "Intern", "Service Account", "Test Account", "Shared Account", "Agent Account"]
    assert items["user_type"]["user_editable"] is False      # admins set it; people cannot promote themselves


def test_a_new_user_is_an_employee_unless_told_otherwise_and_only_listed_types_are_accepted(admin):
    r = create(admin, "Em", "Ployee")
    assert (r.json().get("profile_attributes") or {}).get("user_type") == "Employee", r.text
    for i, t in enumerate(USER_TYPES):
        r = create(admin, "Type", f"Check{i}", profile_attributes={"user_type": t})
        assert r.status_code == 201, (t, r.text)
        assert r.json()["profile_attributes"]["user_type"] == t
    bad = create(admin, "Type", "Bad", profile_attributes={"user_type": "Contractor"})
    assert bad.status_code == 422 and "one of" in bad.text
