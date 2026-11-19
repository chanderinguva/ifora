"""Access request lifecycle (IFORA-37): staged approval, expiry, escalation, SoD baseline, approver scoping and tenant isolation."""

from datetime import datetime, timedelta, timezone

from backend.app.access_requests import service
from backend.app.access_requests.models import AccessRequest
from backend.app.applications.models import Application, ApplicationAssignment
from backend.app.tenancy import Tenant, tenant_session, unscoped
from tests.conftest import Api, make_user
from tests.test_access_requests import A, R, acts, open_app, user
from tests.test_applications import assign, mkapp

M = "/me/approvals"


def policy(sa, app, **body):
    r = sa.put(f"/admin/applications/{app['id']}/approval-policy", body)
    assert r.status_code == 200, r.text
    return r.json()


def group_with(sa, name, *users):
    gid = sa.post("/admin/groups", {"name": name}).json()["id"]
    for u in users:
        assert sa.post(f"/admin/groups/{gid}/members", {"user_id": u.id}).status_code in (200, 201)
    return gid


def ask(who, app, **kw):
    r = who.post(R + "/requests", {"application_id": app["id"], **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def assigned(db, app, u):
    db.expire_all()
    return db.query(ApplicationAssignment).filter(ApplicationAssignment.application_id == app["id"], ApplicationAssignment.user_id == u.id).count() == 1


def test_multi_stage_requires_all_stages(db, super_admin, member):
    owner, approver = user(db, "owner@example.com"), user(db, "second@example.com")
    app = open_app(super_admin, owner_user_id=owner.user.id)
    gid = group_with(super_admin, "Security", approver.user)
    policy(super_admin, app, stages=[{"kind": "owner"}, {"kind": "group", "group_id": gid}])
    rid = ask(member, app)
    assert super_admin.post(f"{A}/{rid}/approve", {}).status_code == 403          # routed: administrators do not shortcut the policy
    assert approver.get(M).json()["items"] == []                                   # stage 2 approver sees nothing yet
    assert [i["id"] for i in owner.get(M).json()["items"]] == [rid]
    assert owner.post(f"{M}/{rid}/approve", {}).json()["stage"] == 2
    assert not assigned(db, app, member.user) and member.get(R + "/requests").json()["items"][0]["status"] == "pending"
    assert owner.post(f"{M}/{rid}/approve", {}).status_code == 404                 # no longer the stage approver
    done = approver.post(f"{M}/{rid}/approve", {})
    assert done.status_code == 200 and done.json()["status"] == "approved"
    assert assigned(db, app, member.user)
    assert len(acts(db, "ACCESS_REQUEST_STAGE_APPROVED")) == 1 and len(acts(db, "ACCESS_REQUEST_APPROVED")) == 1


def test_requester_cannot_approve_any_stage(db, super_admin, member):
    gid = group_with(super_admin, "Approvers", member.user)
    app = open_app(super_admin)
    policy(super_admin, app, stages=[{"kind": "group", "group_id": gid}])
    rid = ask(member, app)
    assert member.post(f"{M}/{rid}/approve", {}).status_code == 403
    assert member.post(f"{M}/{rid}/deny", {}).status_code == 403
    assert len(acts(db, "ACCESS_REQUEST_DECISION_REFUSED")) == 2 and not assigned(db, app, member.user)


def test_same_approver_two_stages_blocked(db, super_admin, member):
    both = user(db, "both@example.com")
    gid = group_with(super_admin, "Also", both.user)
    app = open_app(super_admin, owner_user_id=both.user.id)
    policy(super_admin, app, stages=[{"kind": "owner"}, {"kind": "group", "group_id": gid}])
    rid = ask(member, app)
    assert both.post(f"{M}/{rid}/approve", {}).status_code == 200
    assert both.post(f"{M}/{rid}/approve", {}).status_code == 403
    assert not assigned(db, app, member.user) and len(acts(db, "ACCESS_REQUEST_DECISION_REFUSED")) == 1


def test_manager_stage_uses_the_profile_attribute(db, super_admin, member):
    boss = user(db, "boss@example.com")
    member.user.set_profile_attributes({"manager": "boss@example.com"})
    db.add(member.user)
    db.commit()
    app = open_app(super_admin)
    policy(super_admin, app, stages=[{"kind": "manager"}])
    rid = ask(member, app)
    assert boss.post(f"{M}/{rid}/approve", {}).json()["status"] == "approved" and assigned(db, app, member.user)


def test_missing_manager_or_owner_blocks_the_request_early(db, super_admin, member):
    app = open_app(super_admin)
    policy(super_admin, app, stages=[{"kind": "manager"}])
    assert member.post(R + "/requests", {"application_id": app["id"]}).status_code == 409
    assert super_admin.put(f"/admin/applications/{app['id']}/approval-policy", {"stages": [{"kind": "owner"}]}).status_code == 422  # no owner set


def test_non_approver_forbidden_and_cannot_enumerate(db, super_admin, member):
    owner, stranger = user(db, "owner@example.com"), user(db, "stranger@example.com")
    app = open_app(super_admin, owner_user_id=owner.user.id)
    policy(super_admin, app, stages=[{"kind": "owner"}])
    rid = ask(member, app)
    assert stranger.get(M).json()["items"] == []
    assert stranger.post(f"{M}/{rid}/approve", {}).status_code == 404 and stranger.post(f"{M}/{rid}/deny", {}).status_code == 404
    assert stranger.post(f"{M}/99999/approve", {}).status_code == 404            # same answer as a real request: nothing to enumerate
    assert Api().get(M).status_code == 401
    assert owner.post(f"{M}/{rid}/deny", {"note": "no"}).json()["status"] == "denied" and not assigned(db, app, member.user)


def test_policy_editing_needs_applications_write(db, super_admin, member):
    app = open_app(super_admin)
    assert member.put(f"/admin/applications/{app['id']}/approval-policy", {"stages": []}).status_code == 403
    helpdesk = make_user(db, "help@example.com", admin=True, roles=("help_desk_admin",))
    h = Api()
    assert h.login(helpdesk.email).status_code == 200
    assert h.get(f"/admin/applications/{app['id']}/approval-policy").status_code == 200       # read
    assert h.put(f"/admin/applications/{app['id']}/approval-policy", {"stages": []}).status_code == 403
    assert h.post(A + "/sod-rules", {"app_a_id": 1, "app_b_id": 2}).status_code == 403


def test_legacy_pending_requests_still_decidable(db, super_admin, member):
    app = open_app(super_admin)
    rid = ask(member, app)                                                          # made before any policy exists
    owner = user(db, "owner@example.com")
    super_admin.put(f"/admin/applications/{app['id']}", {"name": "Wiki", "sign_on_mode": "bookmark", "launch_url": "https://wiki.example.com/", "owner_user_id": owner.user.id})
    policy(super_admin, app, stages=[{"kind": "owner"}])
    row = db.query(AccessRequest).filter(AccessRequest.id == rid).one()
    assert row.routed is False and row.stages_total == 1
    assert super_admin.post(f"{A}/{rid}/approve", {}).json()["status"] == "approved" and assigned(db, app, member.user)


def test_durations_are_validated_and_expiry_unassigns_idempotently(db, super_admin, member):
    app = open_app(super_admin)
    policy(super_admin, app, durations=[7, 30])
    assert member.post(R + "/requests", {"application_id": app["id"]}).status_code == 422                  # must pick one
    assert member.post(R + "/requests", {"application_id": app["id"], "duration_days": 5}).status_code == 422
    assert member.get(R + "/catalog").json()["items"][0]["durations"] == [7, 30]
    rid = ask(member, app, duration_days=7)
    d = super_admin.post(f"{A}/{rid}/approve", {}).json()
    exp = datetime.fromisoformat(d["expires_at"])
    assert timedelta(days=6, hours=23) < exp - datetime.now(timezone.utc) < timedelta(days=7, hours=1)
    assert service.expire_due(db, datetime.now(timezone.utc) + timedelta(days=6)) == 0 and assigned(db, app, member.user)
    later = datetime.now(timezone.utc) + timedelta(days=8)
    assert service.expire_due(db, later) == 1
    assert not assigned(db, app, member.user) and member.get("/me/apps").json()["items"] == []
    assert service.expire_due(db, later) == 0                                       # idempotent
    assert member.get(R + "/requests").json()["items"][0]["status"] == "expired"
    assert len(acts(db, "ACCESS_REQUEST_EXPIRED")) == 1
    assert not super_admin.get(f"/admin/applications/{app['id']}/self-service").json()["enabled"] is False  # app itself untouched


def test_sod_conflict_blocks_unless_an_exception_reason_is_audited(db, super_admin, member):
    a, b = open_app(super_admin, name="Payments"), open_app(super_admin, name="Approvals")
    assert super_admin.post(A + "/sod-rules", {"app_a_id": a["id"], "app_b_id": b["id"], "note": "four eyes"}).status_code == 201
    assert super_admin.post(A + "/sod-rules", {"app_a_id": b["id"], "app_b_id": a["id"]}).status_code == 409           # same pair, either order
    assert super_admin.post(A + "/sod-rules", {"app_a_id": a["id"], "app_b_id": a["id"]}).status_code == 422
    assign(super_admin, a, user_id=member.user.id)
    rid = ask(member, b)
    item = super_admin.get(A).json()["items"][0]
    assert item["sod_conflict"] is True and item["sod_apps"] == ["Payments"]
    assert super_admin.post(f"{A}/{rid}/approve", {}).status_code == 422
    assert super_admin.post(f"{A}/{rid}/approve", {"exception_reason": "  "}).status_code == 422
    assert not assigned(db, b, member.user)
    ok = super_admin.post(f"{A}/{rid}/approve", {"exception_reason": "Covering for leave, CFO signed off"})
    assert ok.status_code == 200 and ok.json()["exception_reason"].startswith("Covering")
    ev = acts(db, "ACCESS_REQUEST_SOD_EXCEPTION")
    assert len(ev) == 1 and "Covering for leave" in str(ev[0].event_metadata) and assigned(db, b, member.user)
    rules = super_admin.get(A + "/sod-rules").json()["items"]
    assert len(rules) == 1 and super_admin.delete(f"{A}/sod-rules/{rules[0]['id']}").status_code == 200


def test_pending_timeout_sends_one_reminder_and_marks_escalated(db, super_admin, member, monkeypatch):
    sent = []
    monkeypatch.setattr(service.mailer, "configured", lambda: True)
    monkeypatch.setattr(service.mailer, "send", lambda msg, timeout=10: sent.append(msg["To"]))
    owner = user(db, "owner@example.com")
    app = open_app(super_admin, owner_user_id=owner.user.id)
    policy(super_admin, app, stages=[{"kind": "owner"}], timeout_hours=24)
    rid = ask(member, app)
    assert service.escalate_due(db, datetime.now(timezone.utc) + timedelta(hours=1)) == 0 and sent == []
    soon = datetime.now(timezone.utc) + timedelta(hours=25)
    assert service.escalate_due(db, soon) == 1 and sent == ["owner@example.com"]
    assert service.escalate_due(db, soon + timedelta(days=3)) == 0 and len(sent) == 1               # once only
    row = [i for i in owner.get(M).json()["items"] if i["id"] == rid][0]
    assert row["escalated"] is True and row["status"] == "pending"
    assert len(acts(db, "ACCESS_REQUEST_ESCALATED")) == 1


def test_cross_tenant_request_is_404_for_another_tenants_approver(db, super_admin, member):
    owner = user(db, "owner@example.com")
    with unscoped(db):
        t2 = Tenant(slug="other-gov", name="Other")
        db.add(t2)
        db.commit()
        tid2 = t2.id
    other = tenant_session(tid2)
    try:
        u2 = make_user(other, "req@other.example")
        a2 = Application(public_id="b" * 36, name="Theirs", sign_on_mode="bookmark", launch_url="https://t.example.com/")
        other.add(a2)
        other.flush()
        r2 = AccessRequest(user_id=u2.id, application_id=a2.id, status="pending", routed=True, stage=1, stages_total=1)
        other.add(r2)
        other.commit()
        rid2 = r2.id
    finally:
        other.close()
    assert owner.post(f"{M}/{rid2}/approve", {}).status_code == 404
    assert super_admin.post(f"{A}/{rid2}/approve", {}).status_code == 404
    assert all(i["id"] != rid2 for i in owner.get(M).json()["items"])
