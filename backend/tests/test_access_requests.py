"""Self-service access requests (ADR 017)."""

from backend.app.applications.models import ApplicationAssignment
from backend.app.audit.model import AuditEvent
from tests.conftest import Api, make_user
from tests.test_applications import assign, mkapp

R = "/me/access"
A = "/admin/access-requests"


def open_app(sa, **kw):
    a = mkapp(sa, **kw)
    assert sa.put(f"/admin/applications/{a['id']}/self-service", {"enabled": True, "reason_required": kw.get("reason", False)}).status_code == 200
    return a


def acts(db, name):
    db.expire_all()
    return [e for e in db.query(AuditEvent).all() if str(getattr(e.action, "value", e.action)) == name]


def user(db, email):
    u = make_user(db, email)
    a = Api()
    assert a.login(email).status_code == 200
    a.user = u
    return a


def test_auth_required(anon):
    assert anon.get(R + "/catalog").status_code == 401
    assert anon.post(R + "/requests", {"application_id": 1}).status_code in (401, 403)
    assert anon.get(A).status_code in (401, 403)


def test_catalog_lists_only_requestable_unassigned_visible_apps(db, super_admin, member):
    ok = open_app(super_admin)
    mine = open_app(super_admin, name="Mine")
    assign(super_admin, mine, user_id=member.user.id)
    mkapp(super_admin, name="Closed")                                 # self-service never enabled
    hidden = open_app(super_admin, name="Hidden", visible=False)
    off = open_app(super_admin, name="Off", status="inactive")
    names = [x["name"] for x in member.get(R + "/catalog").json()["items"]]
    assert names == ["Wiki"], names
    assert hidden and off and ok


def test_request_flow_approve_creates_assignment_and_tile(db, super_admin, member):
    a = open_app(super_admin)
    assert member.get("/me/apps").json()["items"] == []
    r = member.post(R + "/requests", {"application_id": a["id"], "reason": "Need the wiki"})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    assert member.get(R + "/catalog").json()["items"][0]["pending"] is True
    assert member.post(R + "/requests", {"application_id": a["id"]}).status_code == 409   # one pending at a time
    rid = r.json()["id"]
    assert member.get("/me/apps").json()["items"] == []                                   # asking grants nothing
    assert member.post(f"/me/apps/{a['id']}/launch").status_code == 404
    item = super_admin.get(A).json()["items"][0]
    assert item["user_email"] == member.user.email and item["reason"] == "Need the wiki"
    d = super_admin.post(f"{A}/{rid}/approve", {"note": "ok"})
    assert d.status_code == 200 and d.json()["status"] == "approved" and d.json()["decided_by_email"] == super_admin.user.email
    assert [x["name"] for x in member.get("/me/apps").json()["items"]] == ["Wiki"]
    assert member.post(f"/me/apps/{a['id']}/launch").status_code == 200
    assert member.get(R + "/catalog").json()["items"] == []
    assert [x["status"] for x in member.get(R + "/requests").json()["items"]] == ["approved"]
    assert len(acts(db, "ACCESS_REQUESTED")) == 1 and len(acts(db, "ACCESS_REQUEST_APPROVED")) == 1 and len(acts(db, "APPLICATION_ASSIGNMENT_ADDED")) == 1


def test_deny_grants_nothing_and_allows_asking_again(db, super_admin, member):
    a = open_app(super_admin)
    rid = member.post(R + "/requests", {"application_id": a["id"]}).json()["id"]
    d = super_admin.post(f"{A}/{rid}/deny", {"note": "not now"})
    assert d.json()["status"] == "denied"
    assert member.get("/me/apps").json()["items"] == []
    mine = member.get(R + "/requests").json()["items"][0]
    assert mine["status"] == "denied" and mine["decision_note"] == "not now"
    assert member.post(R + "/requests", {"application_id": a["id"]}).status_code == 201
    assert len(acts(db, "ACCESS_REQUEST_DENIED")) == 1


def test_decisions_are_single_use(db, super_admin, member):
    a = open_app(super_admin)
    rid = member.post(R + "/requests", {"application_id": a["id"]}).json()["id"]
    assert super_admin.post(f"{A}/{rid}/approve", {}).status_code == 200
    assert super_admin.post(f"{A}/{rid}/approve", {}).status_code == 409
    assert super_admin.post(f"{A}/{rid}/deny", {}).status_code == 409
    assert super_admin.post(f"{A}/99999/approve", {}).status_code == 404
    assert db.query(ApplicationAssignment).filter(ApplicationAssignment.user_id == member.user.id).count() == 1


def test_cancel_own_only(db, super_admin, member):
    a = open_app(super_admin)
    rid = member.post(R + "/requests", {"application_id": a["id"]}).json()["id"]
    other = user(db, "other@example.com")
    assert other.post(f"{R}/requests/{rid}/cancel").status_code == 404
    assert other.get(R + "/requests").json()["items"] == []
    assert member.post(f"{R}/requests/{rid}/cancel").json()["status"] == "canceled"
    assert member.post(f"{R}/requests/{rid}/cancel").status_code == 409
    assert super_admin.post(f"{A}/{rid}/approve", {}).status_code == 409
    assert len(acts(db, "ACCESS_REQUEST_CANCELED")) == 1


def test_cannot_request_unrequestable_or_owned(db, super_admin, member):
    closed = mkapp(super_admin, name="Closed")
    assert member.post(R + "/requests", {"application_id": closed["id"]}).status_code == 404
    assert member.post(R + "/requests", {"application_id": 99999}).status_code == 404
    off = open_app(super_admin, name="Off")
    super_admin.put(f"/admin/applications/{off['id']}", {"name": "Off", "sign_on_mode": "bookmark", "launch_url": "https://x.example.com/", "status": "inactive"})
    assert member.post(R + "/requests", {"application_id": off["id"]}).status_code == 404
    mine = open_app(super_admin, name="Mine")
    assign(super_admin, mine, user_id=member.user.id)
    assert member.post(R + "/requests", {"application_id": mine["id"]}).status_code == 409


def test_turning_self_service_off_blocks_new_requests(db, super_admin, member):
    a = open_app(super_admin)
    super_admin.put(f"/admin/applications/{a['id']}/self-service", {"enabled": False})
    assert member.post(R + "/requests", {"application_id": a["id"]}).status_code == 404
    assert super_admin.get(f"/admin/applications/{a['id']}/self-service").json() == {"enabled": False, "reason_required": False}
    assert len(acts(db, "APPLICATION_SELF_SERVICE_CHANGED")) == 2


def test_reason_required_and_limits(db, super_admin, member):
    a = open_app(super_admin, reason=True)
    assert member.post(R + "/requests", {"application_id": a["id"]}).status_code == 422
    assert member.post(R + "/requests", {"application_id": a["id"], "reason": "  "}).status_code == 422
    assert member.post(R + "/requests", {"application_id": a["id"], "reason": "x" * 501}).status_code == 422
    assert member.post(R + "/requests", {"application_id": a["id"], "reason": "bad\x00text"}).status_code == 422
    assert member.post(R + "/requests", {"application_id": a["id"], "reason": "because"}).status_code == 201


def test_admin_cannot_approve_own_request(db, super_admin):
    a = open_app(super_admin)
    rid = super_admin.post(R + "/requests", {"application_id": a["id"]}).json()["id"]
    assert super_admin.post(f"{A}/{rid}/approve", {}).status_code == 403
    assert super_admin.post(f"{A}/{rid}/deny", {}).status_code == 403


def test_non_admins_cannot_use_admin_endpoints(db, super_admin, member):
    a = open_app(super_admin)
    rid = member.post(R + "/requests", {"application_id": a["id"]}).json()["id"]
    assert member.get(A).status_code == 403
    assert member.post(f"{A}/{rid}/approve", {}).status_code == 403
    assert member.put(f"/admin/applications/{a['id']}/self-service", {"enabled": True}).status_code == 403
    assert member.get("/me/apps").json()["items"] == []


def test_approving_for_a_deactivated_user_is_refused(db, super_admin, member):
    a = open_app(super_admin)
    rid = member.post(R + "/requests", {"application_id": a["id"]}).json()["id"]
    member.user.status = "deactivated"
    db.commit()
    assert super_admin.post(f"{A}/{rid}/approve", {}).status_code == 409
    assert db.query(ApplicationAssignment).filter(ApplicationAssignment.user_id == member.user.id).count() == 0


def test_role_scoping_app_admin_can_decide_group_admin_cannot(db, super_admin, member):
    a = open_app(super_admin)
    rid = member.post(R + "/requests", {"application_id": a["id"]}).json()["id"]
    ga = make_user(db, "ga@example.com", admin=True)
    gaa = Api(); assert gaa.login(ga.email).status_code == 200
    assert super_admin.put(f"/admin/roles/users/{ga.id}", {"roles": ["group_admin"]}).status_code == 200
    assert gaa.get(A).status_code == 403 and gaa.post(f"{A}/{rid}/approve", {}).status_code == 403
    assert super_admin.put(f"/admin/roles/users/{ga.id}", {"roles": ["app_admin"]}).status_code == 200
    assert gaa.get(A).status_code == 200
    assert gaa.post(f"{A}/{rid}/approve", {}).status_code == 200


def test_dashboard_task_counts_pending(db, super_admin, member):
    a = open_app(super_admin)
    member.post(R + "/requests", {"application_id": a["id"]})
    t = {x["id"]: x for x in super_admin.get("/admin/dashboard").json()["tasks"]}
    assert t["access_requests"]["count"] == 1


def test_catalog_icon_only_for_requestable_apps(db, super_admin, member):
    import base64
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    a = open_app(super_admin)
    closed = mkapp(super_admin, name="Closed")
    for x in (a, closed):
        r = super_admin.put(f"/admin/applications/{x['id']}/icon", {"data": base64.b64encode(png).decode()})
        assert r.status_code == 200, r.text
    assert member.get(f"/me/access/catalog/{a['id']}/icon").status_code == 200
    assert member.get(f"/me/access/catalog/{closed['id']}/icon").status_code == 404
