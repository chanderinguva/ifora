"""Bulk lifecycle actions and the per-user Applications / Activity views."""

from tests.conftest import make_user


def _status(db, u):
    db.expire_all()
    return db.get(type(u), u.id).status


def test_bulk_suspend_and_unsuspend(db, admin):
    a, b = make_user(db, "a@example.com"), make_user(db, "b@example.com")
    r = admin.post("/admin/users/bulk", {"user_ids": [a.id, b.id], "action": "suspend"})
    assert r.status_code == 200 and r.json()["done"] == 2
    assert _status(db, a) == "suspended" and _status(db, b) == "suspended"
    r = admin.post("/admin/users/bulk", {"user_ids": [a.id, b.id], "action": "unsuspend"})
    assert r.json()["done"] == 2 and _status(db, a) == "active"


def test_bulk_reports_refusals_instead_of_failing(db, admin, super_admin):
    u = make_user(db, "u@example.com")
    r = admin.post("/admin/users/bulk", {"user_ids": [admin.user.id, super_admin.user.id, u.id, 999999], "action": "deactivate"})
    body = r.json()
    assert r.status_code == 200 and body["done"] == 1
    why = {x["user_id"]: x["reason"] for x in body["results"] if not x["ok"]}
    assert "own account" in why[admin.user.id]
    assert "protected" in why[super_admin.user.id]
    assert why[999999] == "not found"
    assert _status(db, u) == "deprovisioned"


def test_bulk_respects_status_transitions(db, admin):
    u = make_user(db, "t@example.com")
    r = admin.post("/admin/users/bulk", {"user_ids": [u.id], "action": "unsuspend"}).json()
    assert r["done"] == 0 and "not allowed" in r["results"][0]["reason"]
    assert _status(db, u) == "active"


def test_plain_admin_cannot_bulk_modify_admins(db, admin):
    other = make_user(db, "other-admin@example.com", admin=True)
    r = admin.post("/admin/users/bulk", {"user_ids": [other.id], "action": "suspend"}).json()
    assert r["done"] == 0 and "super administrator" in r["results"][0]["reason"]


def test_bulk_requires_admin_and_validates(member, admin):
    assert member.post("/admin/users/bulk", {"user_ids": [1], "action": "suspend"}).status_code == 403
    assert admin.post("/admin/users/bulk", {"user_ids": [], "action": "suspend"}).status_code == 422
    assert admin.post("/admin/users/bulk", {"user_ids": [1], "action": "delete"}).status_code == 422
    assert admin.post("/admin/users/bulk", {"user_ids": list(range(1, 102)), "action": "suspend"}).status_code == 422


def test_suspend_ends_sessions(db, admin):
    from tests.conftest import Api

    u = make_user(db, "sess@example.com")
    s = Api()
    assert s.login(u.email).status_code == 200
    assert s.get("/me").status_code == 200
    admin.post("/admin/users/bulk", {"user_ids": [u.id], "action": "suspend"})
    assert s.get("/me").status_code in (401, 403)


def test_user_applications_direct_and_via_group(db, admin):
    u = make_user(db, "apps@example.com")
    g = admin.post("/admin/groups", {"name": "App Team"}).json()
    admin.post(f"/admin/groups/{g['id']}/members", {"user_id": u.id})
    direct = admin.post("/admin/applications", {"name": "Direct App", "sign_on_mode": "bookmark", "launch_url": "https://example.com/"}).json()
    viagrp = admin.post("/admin/applications", {"name": "Group App", "sign_on_mode": "bookmark", "launch_url": "https://example.com/g"}).json()
    admin.post(f"/admin/applications/{direct['id']}/assignments", {"user_id": u.id})
    admin.post(f"/admin/applications/{viagrp['id']}/assignments", {"group_id": g["id"]})
    items = {x["name"]: x for x in admin.get(f"/admin/users/{u.id}/applications").json()["items"]}
    assert items["Direct App"]["direct"] is True and items["Direct App"]["groups"] == []
    assert items["Group App"]["direct"] is False and items["Group App"]["groups"] == ["App Team"]
    assert admin.get("/admin/users/999999/applications").status_code == 404


def test_user_events_shows_target_and_actor(db, admin):
    u = make_user(db, "ev@example.com")
    admin.post("/admin/users/bulk", {"user_ids": [u.id], "action": "suspend"})
    ev = admin.get(f"/admin/users/{u.id}/events").json()["items"]
    assert ev and any(e["target_id"] == str(u.id) for e in ev)
    assert admin.get("/admin/users/999999/events").status_code == 404


def test_new_views_require_admin(member):
    assert member.get("/admin/users/1/applications").status_code == 403
    assert member.get("/admin/users/1/events").status_code == 403
