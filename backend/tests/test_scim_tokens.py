"""SCIM S3 (token scopes, IP allow-list, rotation with overlap) and S6 (retention policy)."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.app import ratelimit
from backend.app.audit.model import AuditEvent
from backend.app.scim import retention
from backend.app.scim.models import ScimDeprovisioned, ScimToken
from backend.app.users.model import User
from tests.test_scim import Scim, mk, user_body  # noqa: F401


def issue(super_admin, **body):
    r = super_admin.post("/admin/scim/tokens", {"name": "idp", **body})
    assert r.status_code == 201, r.text
    return r.json()


def audit_count(db, action, **meta):
    db.expire_all()
    rows = db.query(AuditEvent).filter(AuditEvent.action == action).all()
    return len([a for a in rows if all((a.event_metadata or {}).get(k) == v for k, v in meta.items())])


# ---- S3: scopes --------------------------------------------------------------------------------------------------

def test_read_only_token_can_read_but_not_write(db, super_admin):
    full = Scim(issue(super_admin)["token"])
    u = mk(full, "reader")
    ro = Scim(issue(super_admin, read_only=True)["token"])
    assert ro.get("/Users").status_code == 200 and ro.get(f"/Users/{u['id']}").status_code == 200 and ro.get("/ServiceProviderConfig").status_code == 200
    r = ro.post("/Users", user_body("nope"))
    assert r.status_code == 403 and r.json()["detail"] == "This token is read-only"
    assert ro.put(f"/Users/{u['id']}", user_body("reader")).status_code == 403
    assert ro.patch(f"/Users/{u['id']}", [{"op": "replace", "path": "active", "value": False}]).status_code == 403
    assert ro.delete(f"/Users/{u['id']}").status_code == 403
    assert full.get(f"/Users/{u['id']}").json()["active"] is True
    assert audit_count(db, "SCIM_AUTH_FAILED", reason="scope") >= 4


def test_users_only_token_cannot_touch_groups(db, super_admin):
    t = Scim(issue(super_admin, users_only=True)["token"])
    assert t.get("/Users").status_code == 200
    for r in (t.get("/Groups"), t.post("/Groups", {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"], "displayName": "x"}), t.get("/Groups/1")):
        assert r.status_code == 403 and "Users" in r.json()["detail"]
    assert t.get("/Schemas").status_code == 200


def test_scopes_combine(db, super_admin):
    t = Scim(issue(super_admin, users_only=True, read_only=True)["token"])
    assert t.get("/Users").status_code == 200 and t.get("/Groups").status_code == 403 and t.post("/Users", user_body("x")).status_code == 403


# ---- S3: IP allow-list ---------------------------------------------------------------------------------------------

def test_ip_allow_list(db, super_admin, monkeypatch):
    raw = issue(super_admin, allowed_cidrs=["203.0.113.0/24", "2001:db8::/32"])["token"]
    t = Scim(raw)
    for ip, ok in (("203.0.113.77", True), ("2001:db8::5", True), ("198.51.100.1", False), ("203.0.114.1", False), ("unknown", False), ("testclient", False)):
        monkeypatch.setattr(ratelimit, "client_ip", lambda request, ip=ip: ip)
        r = t.get("/Users")
        assert (r.status_code == 200) is ok, (ip, r.status_code)
        if not ok:
            assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"       # same answer as a bad token
    assert audit_count(db, "SCIM_AUTH_FAILED", reason="ip_not_allowed") >= 4


def test_no_list_means_any_address(db, super_admin, monkeypatch):
    t = Scim(issue(super_admin)["token"])
    monkeypatch.setattr(ratelimit, "client_ip", lambda request: "198.51.100.9")
    assert t.get("/Users").status_code == 200


# ---- S3: admin API ----------------------------------------------------------------------------------------------------

def test_restriction_api(db, super_admin, admin):
    assert admin.post("/admin/scim/tokens", {"name": "x", "read_only": True}).status_code == 403
    for bad in (["not-an-ip"], ["10.0.0.0/33"], ["1.2.3.4/8/9"]):
        assert super_admin.post("/admin/scim/tokens", {"name": "x", "allowed_cidrs": bad}).status_code == 422, bad
    assert super_admin.post("/admin/scim/tokens", {"name": "x", "hard_delete_after_days": 3}).status_code == 422
    t = issue(super_admin, allowed_cidrs=["203.0.113.5", "203.0.113.5/32"])
    assert t["allowed_cidrs"] == ["203.0.113.5/32"] and t["read_only"] is False
    assert admin.put(f"/admin/scim/tokens/{t['id']}/restrictions", {"read_only": True}).status_code == 403
    r = super_admin.put(f"/admin/scim/tokens/{t['id']}/restrictions", {"read_only": True, "users_only": True, "allowed_cidrs": []})
    assert r.status_code == 200 and r.json()["read_only"] and r.json()["users_only"] and r.json()["allowed_cidrs"] == []
    assert audit_count(db, "SCIM_TOKEN_RESTRICTED") == 1
    assert super_admin.put(f"/admin/scim/tokens/{t['id']}/restrictions", {"hard_delete_after_days": 5}).status_code == 422
    assert super_admin.put("/admin/scim/tokens/99999/restrictions", {"read_only": True}).status_code == 404
    listed = super_admin.get("/admin/scim/tokens").json()["items"][0]
    assert listed["read_only"] is True and "token" not in listed


def test_rotation_keeps_the_old_token_during_the_overlap(db, super_admin, monkeypatch):
    monkeypatch.setattr(ratelimit, "client_ip", lambda request: "198.51.100.1")
    old = issue(super_admin, read_only=True, allowed_cidrs=["198.51.100.0/24"], expires_in_days=30)
    new = super_admin.post(f"/admin/scim/tokens/{old['id']}/rotate", {"overlap_hours": 12}).json()
    assert new["token"] != old["token"] and new["read_only"] is True and new["allowed_cidrs"] == ["198.51.100.0/24"]
    assert new["replaces"]["id"] == old["id"] and new["id"] != old["id"]
    assert Scim(old["token"]).get("/Users").status_code == 200 and Scim(new["token"]).get("/Users").status_code == 200
    db.expire_all()
    o = db.get(ScimToken, old["id"])
    assert o.replaced_by_id == new["id"] and timedelta(hours=11) < o.expires_at - datetime.now(timezone.utc) < timedelta(hours=12, minutes=1)
    # once the overlap is over the old one stops working, the new one carries on
    o.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert Scim(old["token"]).get("/Users").status_code == 401 and Scim(new["token"]).get("/Users").status_code == 200
    assert audit_count(db, "SCIM_TOKEN_ROTATED") == 1


def test_rotation_without_overlap_and_guards(db, super_admin, admin):
    old = issue(super_admin)
    assert admin.post(f"/admin/scim/tokens/{old['id']}/rotate", {}).status_code == 403
    new = super_admin.post(f"/admin/scim/tokens/{old['id']}/rotate", {"overlap_hours": 0}).json()
    assert Scim(old["token"]).get("/Users").status_code == 401 and Scim(new["token"]).get("/Users").status_code == 200
    assert super_admin.post(f"/admin/scim/tokens/{old['id']}/rotate", {}).status_code == 409           # not active any more
    assert super_admin.post(f"/admin/scim/tokens/{new['id']}/rotate", {"overlap_hours": 1}).status_code == 201
    assert super_admin.post(f"/admin/scim/tokens/{new['id']}/rotate", {"overlap_hours": 1}).status_code == 409     # already rotated
    assert super_admin.post("/admin/scim/tokens/9999/rotate", {}).status_code == 404


def test_overlap_never_extends_a_token_past_its_own_expiry(db, super_admin):
    old = issue(super_admin, expires_in_days=1)
    super_admin.post(f"/admin/scim/tokens/{old['id']}/rotate", {"overlap_hours": 700})
    db.expire_all()
    assert db.get(ScimToken, old["id"]).expires_at - datetime.now(timezone.utc) < timedelta(days=1, minutes=1)


# ---- S6: retention -------------------------------------------------------------------------------------------------------

def deprovision(scim, name):
    u = mk(scim, name)
    assert scim.delete(f"/Users/{u['id']}").status_code == 204
    return u


def test_deprovisioned_users_are_deleted_after_the_token_policy(db, super_admin):
    s = Scim(issue(super_admin, hard_delete_after_days=7)["token"])
    u = deprovision(s, "leaver")
    assert db.query(ScimDeprovisioned).count() == 1
    now = datetime.now(timezone.utc)
    assert retention.purge(db, now + timedelta(days=6)) == 0
    assert db.query(User).filter(User.public_id == u["id"]).count() == 1
    assert retention.purge(db, now + timedelta(days=8)) == 1
    assert db.query(User).filter(User.public_id == u["id"]).count() == 0
    assert audit_count(db, "SCIM_USER_PURGED", after_days=7) == 1
    assert s.get(f"/Users/{u['id']}").status_code == 404


def test_patch_deactivation_is_tracked_and_reactivation_clears_it(db, super_admin):
    s = Scim(issue(super_admin, hard_delete_after_days=7)["token"])
    u = mk(s, "flip")
    s.patch(f"/Users/{u['id']}", [{"op": "replace", "path": "active", "value": False}])
    assert db.query(ScimDeprovisioned).count() == 1
    s.patch(f"/Users/{u['id']}", [{"op": "replace", "path": "active", "value": True}])
    db.expire_all()
    assert db.query(ScimDeprovisioned).count() == 0
    assert retention.purge(db, datetime.now(timezone.utc) + timedelta(days=30)) == 0


def test_retention_spares_touched_accounts_and_tokens_without_a_policy(db, super_admin, admin):
    with_policy = Scim(issue(super_admin, hard_delete_after_days=7)["token"])
    without = Scim(issue(super_admin)["token"])
    touched = deprovision(with_policy, "touched")
    plain = deprovision(without, "plain")
    # an administrator edits the deprovisioned account afterwards: it is no longer an untouched leaver
    uid = db.query(User).filter(User.public_id == touched["id"]).one().id
    assert admin.patch(f"/admin/users/{uid}", {"first_name": "Edited"}).status_code == 200
    assert retention.purge(db, datetime.now(timezone.utc) + timedelta(days=30)) == 0
    assert db.query(User).filter(User.public_id.in_([touched["id"], plain["id"]])).count() == 2


def test_cli_purge_runs(db, super_admin, capsys):
    from backend import cli

    assert cli.main(["purge-scim"]) == 0
    assert "purged scim users: 0" in capsys.readouterr().out


# ---- S8: opaque group ids ------------------------------------------------------------------------------------------------

GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"


def test_group_ids_are_opaque_and_integer_ids_still_resolve(db, super_admin, monkeypatch):
    from backend.app.config import settings
    s = Scim(issue(super_admin)["token"])
    r = s.post("/Groups", {"schemas": [GROUP], "displayName": "Ops"})
    assert r.status_code == 201, r.text
    g = r.json()
    assert len(g["id"]) == 36 and g["id"].count("-") == 4 and not g["id"].isdigit()
    assert g["meta"]["location"].endswith(f"/Groups/{g['id']}")
    assert s.get(f"/Groups/{g['id']}").status_code == 200
    legacy = str(db.query(__import__("backend.app.groups.model", fromlist=["Group"]).Group).filter_by(name="Ops").one().id)
    assert s.get(f"/Groups/{legacy}").status_code == 200                       # earlier integer ids keep working ...
    monkeypatch.setattr(settings, "SCIM_ACCEPT_LEGACY_GROUP_IDS", False)
    assert s.get(f"/Groups/{legacy}").status_code == 404                       # ... until the operator turns that off
    assert s.get(f"/Groups/{g['id']}").status_code == 200
    assert s.get('/Groups?filter=id eq "%s"' % g["id"]).json()["totalResults"] == 1
    assert s.get("/Groups/00000000-0000-0000-0000-000000000000").status_code == 404


def test_user_resource_lists_groups_by_opaque_id(db, super_admin):
    s = Scim(issue(super_admin)["token"])
    u = mk(s, "member1")
    g = s.post("/Groups", {"schemas": [GROUP], "displayName": "Team", "members": [{"value": u["id"]}]}).json()
    got = s.get(f"/Users/{u['id']}").json()
    assert got["groups"][0]["value"] == g["id"] and got["groups"][0]["$ref"].endswith(f"/Groups/{g['id']}")
