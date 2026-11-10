"""Large directories: rule activation is finished by the worker in batches."""

from backend.app.config import settings
from backend.app.groups import rules as svc
from tests.test_group_rules import dept, make_rule, members, new_group


def test_activation_is_queued_in_a_big_directory_and_the_worker_finishes_it(db, admin, monkeypatch):
    monkeypatch.setattr(settings, "GROUP_RULES_SYNC_MAX_USERS", 3)
    monkeypatch.setattr(settings, "GROUP_RULES_BATCH_SIZE", 2)
    gid = new_group(admin)
    for i in range(6):
        dept(db, f"s{i}@example.com", "Sales")
    dept(db, "e@example.com", "Engineering")
    r = admin.post("/admin/group-rules", {"name": "Big", "match": "all", "group_ids": [gid],
                                          "conditions": [{"attribute": "department", "operator": "equals", "value": "Sales"}]})
    rid = r.json()["id"]
    a = admin.post(f"/admin/group-rules/{rid}/activate").json()
    assert a["applied"]["queued"] is True and a["sync_state"] == "pending" and a["status"] == "active"
    assert members(admin, gid) == {}                                  # nothing yet: the request did not scan everyone
    batches = 0
    while admin.get(f"/admin/group-rules/{rid}").json()["sync_state"] == "pending":
        svc.sync_pending_all()
        batches += 1
        assert batches < 10
    assert batches >= 4 and len(members(admin, gid)) == 6
    assert admin.get("/admin/groups").json()["Resources"][0]["member_count"] == 6
    assert svc.sync_pending_all() == 0


def test_small_directories_stay_synchronous(db, admin):
    gid = new_group(admin)
    dept(db, "one@example.com", "Sales")
    rid = make_rule(admin, gid)
    assert admin.get(f"/admin/group-rules/{rid}").json()["sync_state"] == "idle" and len(members(admin, gid)) == 1


def test_deactivating_a_pending_rule_cancels_the_sync(db, admin, monkeypatch):
    monkeypatch.setattr(settings, "GROUP_RULES_SYNC_MAX_USERS", 1)
    gid = new_group(admin)
    for i in range(3):
        dept(db, f"d{i}@example.com", "Sales")
    rid = make_rule(admin, gid)
    assert admin.get(f"/admin/group-rules/{rid}").json()["sync_state"] == "pending"
    admin.post(f"/admin/group-rules/{rid}/deactivate")
    assert admin.get(f"/admin/group-rules/{rid}").json()["sync_state"] == "idle"
    assert svc.sync_pending_all() == 0 and members(admin, gid) == {}
