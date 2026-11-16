"""IFORA-42: the first-run checklist is computed from real objects, hides areas the admin cannot read, and is per administrator and per tenant."""

import uuid

from backend.app.setup_checklist.models import ChecklistDismissal
from tests.conftest import STRONG, Api, make_user
from tests.test_tenancy import b_session, tenant_b  # noqa: F401  (fixture)


def by_id(api):
    r = api.get("/admin/setup-checklist")
    assert r.status_code == 200, r.text
    return {i["id"]: i for i in r.json()["items"]}


def signed_in(db, email, role):
    u = make_user(db, email, admin=True, roles=[role])
    a = Api()
    assert a.login(u.email).status_code == 200
    a.user = u
    return a


def test_setup_checklist_reflects_real_state(admin):
    items = by_id(admin)
    assert set(items) == {"branding", "people", "application", "mfa_policy", "network_zones"}
    assert items["application"]["done"] is False and items["network_zones"]["done"] is False and items["branding"]["done"] is False

    assert admin.post("/admin/applications", {"name": "First app", "sign_on_mode": "bookmark", "launch_url": "https://example.com"}).status_code == 201
    assert admin.post("/admin/network-zones", {"name": "Office", "cidrs": ["10.0.0.0/8"]}).status_code in (200, 201)
    assert admin.put("/admin/branding", {"display_name": "Acme"}).status_code == 200
    assert admin.post("/admin/users", {"email": "new@example.com", "first_name": "N", "last_name": "N", "password": STRONG}).status_code in (200, 201)
    items = by_id(admin)
    assert items["application"]["done"] and items["network_zones"]["done"] and items["branding"]["done"] and items["people"]["done"]


def test_a_deleted_object_unticks_the_item(admin):
    r = admin.post("/admin/applications", {"name": "Temp", "sign_on_mode": "bookmark", "launch_url": "https://example.com"})
    assert by_id(admin)["application"]["done"] is True
    assert admin.delete(f"/admin/applications/{r.json()['id']}").status_code in (200, 204)
    assert by_id(admin)["application"]["done"] is False  # nothing is stored: the object is the state


def test_setup_checklist_permissions(db):
    help_desk = signed_in(db, "hd2@example.com", "help_desk_admin")
    assert set(by_id(help_desk)) == {"people", "application"}  # users and applications are readable; branding and security are not even mentioned
    app_admin = signed_in(db, "app2@example.com", "app_admin")
    assert "application" in by_id(app_admin) and "mfa_policy" not in by_id(app_admin) and "branding" not in by_id(app_admin)
    assert Api().get("/admin/setup-checklist").status_code == 401
    make_user(db, "plain2@example.com")
    member = Api()
    member.login("plain2@example.com")
    assert member.get("/admin/setup-checklist").status_code == 403


def test_no_counts_or_secrets_in_the_answer(admin):
    r = admin.get("/admin/setup-checklist")
    for item in r.json()["items"]:
        assert set(item) == {"id", "title", "description", "href", "done", "dismissed"}
    for forbidden in ("count", "total", "token", "secret", "password"):
        assert forbidden not in r.text.lower().replace("password rules", "").replace("sign-in", "")


def test_dismissal_is_per_administrator_and_reversible(db, admin):
    other = signed_in(db, "other-admin@example.com", "org_admin")
    assert admin.post("/admin/setup-checklist/branding/dismiss").status_code == 204
    assert admin.post("/admin/setup-checklist/branding/dismiss").status_code == 204  # idempotent
    assert by_id(admin)["branding"]["dismissed"] is True
    assert by_id(other)["branding"]["dismissed"] is False
    assert admin.delete("/admin/setup-checklist/branding/dismiss").status_code == 204
    assert by_id(admin)["branding"]["dismissed"] is False
    assert admin.post("/admin/setup-checklist/not-an-item/dismiss").status_code == 404


def test_dismiss_needs_csrf_and_write_access(db, admin):
    assert admin.post("/admin/setup-checklist/branding/dismiss", csrf=False).status_code in (401, 403)
    ro = signed_in(db, "ro2@example.com", "read_only_admin")
    assert ro.post("/admin/setup-checklist/branding/dismiss").status_code == 403  # read-only admins read the list; they cannot change state


def test_setup_checklist_tenant_scoped(db, admin, tenant_b):  # noqa: F811
    from backend.app.applications.models import Application

    s = b_session(tenant_b)
    try:
        s.add(Application(public_id=str(uuid.uuid4()), name="Acme app", sign_on_mode="bookmark", launch_url="https://acme.example.com"))
        s.commit()
    finally:
        s.close()
    assert by_id(admin)["application"]["done"] is False  # another tenant's application does not tick this tenant's item
    admin.post("/admin/setup-checklist/application/dismiss")
    s = b_session(tenant_b)
    try:
        assert s.query(ChecklistDismissal).count() == 0
    finally:
        s.close()
