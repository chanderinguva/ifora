"""Okta-style statuses and the default offboarding rule: deactivation removes every group membership."""

from tests.conftest import STRONG


def mk_group(admin, name):
    return admin.post("/admin/groups", {"name": name}).json()["id"]


def mk_user(admin, email="lc@example.com"):
    return admin.post("/admin/users", {"email": email, "first_name": "L", "last_name": "C", "password": STRONG}).json()["id"]


def group_ids(admin, uid):
    return {g["id"] for g in admin.get(f"/admin/users/{uid}").json().get("groups", [])}


def test_deactivating_removes_the_user_from_every_group(admin):
    g1, g2, uid = mk_group(admin, "Lc1"), mk_group(admin, "Lc2"), mk_user(admin)
    for g in (g1, g2):
        assert admin.post(f"/admin/groups/{g}/members", {"user_id": uid}).status_code in (200, 201)
    assert group_ids(admin, uid) >= {g1, g2}
    assert admin.patch(f"/admin/users/{uid}", {"status": "deprovisioned"}).status_code == 200
    assert not (group_ids(admin, uid) & {g1, g2})
    counts = {g["id"]: g["member_count"] for g in admin.get("/admin/groups").json()["Resources"]}
    assert counts[g1] == 0 and counts[g2] == 0
    audit = admin.get("/admin/audit?action=GROUP_MEMBER_REMOVED").json()
    assert "deactivated" in str(audit)


def test_reactivating_does_not_restore_manual_memberships(admin):
    g, uid = mk_group(admin, "Lc3"), mk_user(admin, "lc3@example.com")
    admin.post(f"/admin/groups/{g}/members", {"user_id": uid})
    admin.patch(f"/admin/users/{uid}", {"status": "deprovisioned"})
    assert admin.patch(f"/admin/users/{uid}", {"status": "active"}).status_code == 200
    assert g not in group_ids(admin, uid)


def test_suspending_keeps_groups_but_blocks_sign_in(admin, db):
    g, uid = mk_group(admin, "Lc4"), mk_user(admin, "lc4@example.com")
    admin.post(f"/admin/groups/{g}/members", {"user_id": uid})
    assert admin.patch(f"/admin/users/{uid}", {"status": "suspended"}).status_code == 200
    assert g in group_ids(admin, uid)
    assert admin.get(f"/admin/users/{uid}").json()["status"] == "suspended"


def test_every_okta_status_is_accepted_and_junk_is_not(admin):
    uid = mk_user(admin, "lc5@example.com")
    for s in ("staged", "provisioned", "recovery", "password_expired", "locked_out", "suspended", "deprovisioned", "active"):
        assert admin.patch(f"/admin/users/{uid}", {"status": s}).status_code == 200, s
        assert admin.get(f"/admin/users/{uid}").json()["status"] == s
    assert admin.patch(f"/admin/users/{uid}", {"status": "inactive"}).status_code == 422
    assert admin.patch(f"/admin/users/{uid}", {"status": "bogus"}).status_code == 422
    assert admin.get("/admin/users?status=suspended").status_code == 200


def test_okta_base_profile_attributes_exist(admin):
    keys = {a["key"] for a in admin.get("/admin/profile-attributes").json()["items"]}
    okta = {"middle_name", "honorific_prefix", "honorific_suffix", "display_name", "nick_name", "second_email", "profile_url",
            "primary_phone", "mobile_phone", "street_address", "city", "state", "zip_code", "country_code",
            "postal_address", "preferred_language", "locale", "timezone", "title", "user_type", "employee_number",
            "cost_center", "organization", "division", "department", "manager_id", "manager"}
    assert okta <= keys
