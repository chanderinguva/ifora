"""End-user dashboard (ADR 016): sections, favourites, recents, own activity, isolation."""

from tests.conftest import Api, make_user
from tests.test_applications import assign, mkapp

D = "/me/dashboard"


def other_user(db):
    u = make_user(db, "other@example.com")
    a = Api()
    assert a.login(u.email).status_code == 200
    a.user = u
    return a


def test_requires_sign_in(anon):
    assert anon.get(D).status_code == 401
    assert anon.get(D + "/activity").status_code == 401
    assert anon.post(D + "/sections", {"name": "x"}).status_code in (401, 403)


def test_favourite_only_for_entitled_visible_apps(db, super_admin, member):
    a = mkapp(super_admin)
    hidden = mkapp(super_admin, name="Hidden", visible=False)
    assert member.put(f"{D}/apps/{a['id']}", {"favorite": True}).status_code == 404   # not assigned
    assign(super_admin, a, user_id=member.user.id)
    assign(super_admin, hidden, user_id=member.user.id)
    assert member.put(f"{D}/apps/{hidden['id']}", {"favorite": True}).status_code == 404
    assert member.put(f"{D}/apps/99999", {"favorite": True}).status_code == 404
    assert member.put(f"{D}/apps/{a['id']}", {"favorite": True}).json()["favorite"] is True
    assert member.get(D).json()["apps"][str(a["id"])]["favorite"] is True
    assert member.put(f"{D}/apps/{a['id']}", {"favorite": False}).json()["favorite"] is False


def test_losing_entitlement_hides_prefs(db, super_admin, member):
    a = mkapp(super_admin)
    asg = assign(super_admin, a, user_id=member.user.id)
    member.put(f"{D}/apps/{a['id']}", {"favorite": True})
    member.post(f"/me/apps/{a['id']}/launch")
    assert super_admin.delete(f"/admin/applications/{a['id']}/assignments/{asg['id']}").status_code == 200
    d = member.get(D).json()
    assert d["apps"] == {} and d["recent"] == []


def test_launch_records_recents_in_order(db, super_admin, member):
    apps = [mkapp(super_admin, name=n, launch_url=f"https://{n.lower()}.example.com/") for n in ("Aaa", "Bbb", "Ccc")]
    for a in apps:
        assign(super_admin, a, user_id=member.user.id)
    assert member.get(D).json()["recent"] == []
    for a in (apps[0], apps[2], apps[1]):
        assert member.post(f"/me/apps/{a['id']}/launch").status_code == 200
    assert member.get(D).json()["recent"] == [apps[1]["id"], apps[2]["id"], apps[0]["id"]]
    member.post(f"/me/apps/{apps[0]['id']}/launch")
    assert member.get(D).json()["recent"][0] == apps[0]["id"]


def test_failed_launch_records_nothing(db, super_admin, member):
    a = mkapp(super_admin)
    assert member.post(f"/me/apps/{a['id']}/launch").status_code == 404
    assert member.get(D).json()["recent"] == []


def test_recents_capped_at_six(db, super_admin, member):
    for i in range(8):
        a = mkapp(super_admin, name=f"App{i}", launch_url=f"https://a{i}.example.com/")
        assign(super_admin, a, user_id=member.user.id)
        member.post(f"/me/apps/{a['id']}/launch")
    assert len(member.get(D).json()["recent"]) == 6


def test_sections_crud_and_rules(db, member):
    s = member.post(D + "/sections", {"name": "  Work   stuff "})
    assert s.status_code == 201 and s.json()["name"] == "Work stuff"
    assert member.post(D + "/sections", {"name": "Work stuff"}).status_code == 409
    assert member.post(D + "/sections", {"name": "   "}).status_code == 422
    t = member.post(D + "/sections", {"name": "Play"}).json()
    r = member.patch(f"{D}/sections/{t['id']}", {"move": "earlier"})
    assert r.status_code == 200
    names = [x["name"] for x in member.get(D).json()["sections"]]
    assert names == ["Play", "Work stuff"]
    assert member.patch(f"{D}/sections/{t['id']}", {"name": "Work stuff"}).status_code == 409
    assert member.patch(f"{D}/sections/{t['id']}", {"name": "Fun"}).json()["name"] == "Fun"
    assert member.delete(f"{D}/sections/{t['id']}").status_code == 204
    assert member.delete(f"{D}/sections/{t['id']}").status_code == 404


def test_section_limit(db, member):
    for i in range(10):
        assert member.post(D + "/sections", {"name": f"S{i}"}).status_code == 201
    assert member.post(D + "/sections", {"name": "S10"}).status_code == 409


def test_move_app_between_sections_and_deleting_section_keeps_app(db, super_admin, member):
    a = mkapp(super_admin)
    assign(super_admin, a, user_id=member.user.id)
    s = member.post(D + "/sections", {"name": "Work"}).json()
    assert member.put(f"{D}/apps/{a['id']}", {"section_id": s["id"]}).json()["section_id"] == s["id"]
    assert member.get(D).json()["apps"][str(a["id"])]["section_id"] == s["id"]
    assert member.delete(f"{D}/sections/{s['id']}").status_code == 204
    d = member.get(D).json()
    assert d["apps"][str(a["id"])]["section_id"] is None
    assert [x["id"] for x in member.get("/me/apps").json()["items"]] == [a["id"]]
    s2 = member.post(D + "/sections", {"name": "Work"}).json()
    member.put(f"{D}/apps/{a['id']}", {"section_id": s2["id"]})
    assert member.put(f"{D}/apps/{a['id']}", {"clear_section": True}).json()["section_id"] is None


def test_reorder_within_section(db, super_admin, member):
    ids = []
    for n in ("Aaa", "Bbb", "Ccc"):
        a = mkapp(super_admin, name=n, launch_url=f"https://{n}.example.com/")
        assign(super_admin, a, user_id=member.user.id)
        member.put(f"{D}/apps/{a['id']}", {"favorite": False})
        ids.append(a["id"])
    member.put(f"{D}/apps/{ids[2]}", {"move": "earlier"})
    member.put(f"{D}/apps/{ids[2]}", {"move": "earlier"})
    apps = member.get(D).json()["apps"]
    assert apps[str(ids[2])]["position"] == 0 and apps[str(ids[0])]["position"] == 1 and apps[str(ids[1])]["position"] == 2
    member.put(f"{D}/apps/{ids[2]}", {"move": "earlier"})  # already first: no-op
    assert member.get(D).json()["apps"][str(ids[2])]["position"] == 0


def test_users_cannot_touch_each_others_sections_or_prefs(db, super_admin, member):
    other = other_user(db)
    s = member.post(D + "/sections", {"name": "Mine"}).json()
    assert other.patch(f"{D}/sections/{s['id']}", {"name": "Hacked"}).status_code == 404
    assert other.delete(f"{D}/sections/{s['id']}").status_code == 404
    a = mkapp(super_admin)
    assign(super_admin, a, user_id=member.user.id)
    assign(super_admin, a, user_id=other.user.id)
    assert other.put(f"{D}/apps/{a['id']}", {"section_id": s["id"]}).status_code == 404   # cannot file an app into another's section
    member.put(f"{D}/apps/{a['id']}", {"favorite": True})
    member.post(f"/me/apps/{a['id']}/launch")
    od = other.get(D).json()
    assert od["sections"] == [] and od["apps"] == {} and od["recent"] == []
    assert [x["name"] for x in member.get(D).json()["sections"]] == ["Mine"]


def test_import_favourites_skips_unseen_apps(db, super_admin, member):
    a, b = mkapp(super_admin), mkapp(super_admin, name="Secret")
    assign(super_admin, a, user_id=member.user.id)
    r = member.post(D + "/import-favorites", {"app_ids": [a["id"], b["id"], 99999, a["id"]]})
    assert r.json() == {"imported": 1}
    d = member.get(D).json()
    assert d["apps"][str(a["id"])]["favorite"] is True and str(b["id"]) not in d["apps"]
    assert member.post(D + "/import-favorites", {"app_ids": [a["id"]]}).json() == {"imported": 0}


def test_activity_is_only_my_own_events(db, member):
    other = other_user(db)
    member.post("/auth/logout")
    mine = member.get(D + "/activity")
    assert mine.status_code in (200, 401)
    m2 = Api()
    assert m2.login(member.user.email).status_code == 200
    items = m2.get(D + "/activity").json()["items"]
    assert items and all(set(i) == {"id", "action", "timestamp", "ip"} for i in items)
    assert {i["action"] for i in items} <= {"LOGIN_SUCCESS", "LOGOUT", "LOGIN_FAILURE"}
    ids_mine = {i["id"] for i in items}
    oi = other.get(D + "/activity").json()["items"]
    assert not ids_mine & {i["id"] for i in oi}
    assert len(oi) == 1 and oi[0]["action"] == "LOGIN_SUCCESS"


def test_admin_actions_on_me_do_not_leak_into_activity(db, super_admin, member):
    a = mkapp(super_admin)
    assign(super_admin, a, user_id=member.user.id)
    items = member.get(D + "/activity").json()["items"]
    assert all(i["action"] in {"LOGIN_SUCCESS", "LOGIN_FAILURE", "LOGOUT"} for i in items)
