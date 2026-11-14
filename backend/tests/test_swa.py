"""Secure Web Authentication (ADR 012): encrypted per-user credentials released only to the signed-in, entitled, recently
authenticated user, and only for posting to the login URL an administrator registered."""

import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

from backend.app.auth.session import Session as AuthSession
from backend.app.config import settings
from backend.app.swa import vault
from backend.app.swa.models import SwaCredential
from tests.conftest import Api, STRONG, make_user
from tests.test_applications import assign

LOGIN = "https://legacy.example.com/login.php"


@pytest.fixture(autouse=True)
def swa_key(monkeypatch):
    monkeypatch.setattr(settings, "SWA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "SWA_ENCRYPTION_KEY_PREVIOUS", "")


def swa_app(sa, name="Legacy", **cfg):
    a = sa.post("/admin/applications", {"name": name, "sign_on_mode": "swa"})
    assert a.status_code == 201, a.text
    body = {"login_url": LOGIN, "username_field": "user", "password_field": "pass", "extra_fields": [{"name": "action", "value": "login"}], **cfg}
    r = sa.put(f"/admin/applications/{a.json()['id']}/swa", body)
    assert r.status_code == 200, r.text
    return a.json()["id"]


def member_with_app(db, sa, email="m@example.com", **cfg):
    app_id = swa_app(sa, **cfg)
    u = make_user(db, email)
    assign(sa, {"id": app_id}, user_id=u.id)
    m = Api()
    assert m.login(email).status_code == 200
    return app_id, u, m


def store(m, app_id, password="legacy-Pass-1", username="jdoe"):
    return m.put(f"/swa/apps/{app_id}/credential", {"username": username, "password": password})


# ---- configuration -------------------------------------------------------------------------------------------------

def test_config_validation(super_admin):
    a = super_admin.post("/admin/applications", {"name": "L", "sign_on_mode": "swa"}).json()["id"]
    put = lambda **o: super_admin.put(f"/admin/applications/{a}/swa", {"login_url": LOGIN, "username_field": "u", "password_field": "p", **o})  # noqa: E731
    assert put(login_url="http://legacy.example.com/login").status_code == 422  # plain http to a remote host
    assert put(login_url="https://user:pw@legacy.example.com/").status_code == 422
    assert put(login_url="javascript:alert(1)").status_code == 422
    assert put(login_url="https://legacy.example.com/#x").status_code == 422
    assert put(password_field="u").status_code == 422  # same as username field
    assert put(username_field="a b").status_code == 422
    assert put(extra_fields=[{"name": "u", "value": "x"}]).status_code == 422  # collides with the username field
    assert put(extra_fields=[{"name": "x"}, {"name": "x"}]).status_code == 422
    assert put(login_url="http://localhost:8080/login").status_code == 200  # loopback http for development
    assert put().status_code == 200


def test_config_requires_swa_mode_and_blocks_mode_change(super_admin):
    b = super_admin.post("/admin/applications", {"name": "B", "sign_on_mode": "bookmark", "launch_url": "https://b.example.com/"}).json()
    assert super_admin.put(f"/admin/applications/{b['id']}/swa", {"login_url": LOGIN, "username_field": "u", "password_field": "p"}).status_code == 409
    a = swa_app(super_admin)
    r = super_admin.put(f"/admin/applications/{a}", {"name": "Legacy", "sign_on_mode": "none"})
    assert r.status_code == 409
    assert super_admin.get(f"/admin/applications/{a}").json()["swa"]["login_url"] == LOGIN


def test_admin_endpoints_are_admin_only(db, super_admin, member):
    a = swa_app(super_admin)
    assert member.get(f"/admin/applications/{a}/swa").status_code == 403
    assert member.put(f"/admin/applications/{a}/swa", {"login_url": LOGIN, "username_field": "u", "password_field": "p"}).status_code == 403
    assert member.get(f"/admin/applications/{a}/swa/credentials").status_code == 403
    assert member.delete(f"/admin/applications/{a}/swa/credentials/1").status_code == 403


# ---- the vault -------------------------------------------------------------------------------------------------------

def test_password_is_encrypted_at_rest_and_bound_to_user_and_app(db, super_admin):
    a = swa_app(super_admin)
    u1, u2 = make_user(db, "one@example.com"), make_user(db, "two@example.com")
    for u in (u1, u2):
        assign(super_admin, {"id": a}, user_id=u.id)
    m1 = Api(); m1.login("one@example.com")
    assert store(m1, a, "PlainSecret-123").status_code == 200
    row = db.query(SwaCredential).filter_by(user_id=u1.id).one()
    assert b"PlainSecret-123" not in bytes(row.secret)
    # copying the ciphertext to another user's row must not decrypt (AAD binds tenant/app/user)
    with pytest.raises(vault.VaultError):
        vault.decrypt(row.secret, row.key_id, u2.tenant_id, a, u2.id)
    with pytest.raises(vault.VaultError):
        vault.decrypt(row.secret, row.key_id, u1.tenant_id, a + 1, u1.id)
    assert vault.decrypt(row.secret, row.key_id, u1.tenant_id, a, u1.id) == "PlainSecret-123"
    # nonce is fresh each time
    blobs = {vault.encrypt("x", 1, 1, 1)[0] for _ in range(5)}
    assert len(blobs) == 5


def test_vault_key_validation_and_rotation(monkeypatch):
    monkeypatch.setattr(settings, "SWA_ENCRYPTION_KEY", "")
    assert not vault.available()
    with pytest.raises(vault.VaultUnavailable):
        vault.encrypt("x", 1, 1, 1)
    monkeypatch.setattr(settings, "SWA_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"short").decode())
    assert not vault.available()
    old = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "SWA_ENCRYPTION_KEY", old)
    blob, kid = vault.encrypt("pw", 1, 2, 3)
    new = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "SWA_ENCRYPTION_KEY", new)
    with pytest.raises(vault.VaultError):
        vault.decrypt(blob, kid, 1, 2, 3)  # old key no longer configured
    monkeypatch.setattr(settings, "SWA_ENCRYPTION_KEY_PREVIOUS", old)
    assert vault.decrypt(blob, kid, 1, 2, 3) == "pw"


def test_old_key_rows_are_reencrypted_on_use(db, super_admin, monkeypatch):
    app_id, u, m = member_with_app(db, super_admin)
    assert store(m, app_id).status_code == 200
    old = settings.SWA_ENCRYPTION_KEY
    monkeypatch.setattr(settings, "SWA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "SWA_ENCRYPTION_KEY_PREVIOUS", old)
    assert m.post(f"/swa/apps/{app_id}/launch").status_code == 200
    db.expire_all()
    assert db.query(SwaCredential).filter_by(user_id=u.id).one().key_id == vault.current_key_id()
    monkeypatch.setattr(settings, "SWA_ENCRYPTION_KEY_PREVIOUS", "")
    assert m.post(f"/swa/apps/{app_id}/launch").status_code == 200  # works with the new key alone


def test_unreadable_credential_asks_the_user_again(db, super_admin, monkeypatch):
    app_id, u, m = member_with_app(db, super_admin)
    store(m, app_id)
    monkeypatch.setattr(settings, "SWA_ENCRYPTION_KEY", Fernet.generate_key().decode())  # key lost, no previous
    r = m.post(f"/swa/apps/{app_id}/launch")
    assert r.status_code == 409 and r.json()["detail"] == "credential_required"


def test_without_a_key_nothing_is_stored(db, super_admin, monkeypatch):
    app_id, u, m = member_with_app(db, super_admin)
    monkeypatch.setattr(settings, "SWA_ENCRYPTION_KEY", "")
    assert m.get(f"/swa/apps/{app_id}").json()["vault_enabled"] is False
    assert store(m, app_id).status_code == 503
    assert db.query(SwaCredential).count() == 0


# ---- using it --------------------------------------------------------------------------------------------------------

def test_store_launch_roundtrip_and_status_never_shows_the_password(db, super_admin):
    app_id, u, m = member_with_app(db, super_admin)
    s = m.get(f"/swa/apps/{app_id}").json()
    assert s["has_credential"] is False and s["username_source"] == "user" and s["login_host"] == "legacy.example.com"
    assert m.post(f"/swa/apps/{app_id}/launch").status_code == 409
    assert store(m, app_id, "Secret-Legacy-9", "jdoe").status_code == 200
    s = m.get(f"/swa/apps/{app_id}")
    assert s.json()["has_credential"] is True and s.json()["username"] == "jdoe"
    assert "Secret-Legacy-9" not in s.text and s.headers["cache-control"] == "no-store"
    r = m.post(f"/swa/apps/{app_id}/launch")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json() == {"login_url": LOGIN, "fields": [{"name": "action", "value": "login"}, {"name": "user", "value": "jdoe"}, {"name": "pass", "value": "Secret-Legacy-9"}]}
    # updating replaces it
    store(m, app_id, "Another-Pass-2", "jdoe2")
    assert [f["value"] for f in m.post(f"/swa/apps/{app_id}/launch").json()["fields"]][-2:] == ["jdoe2", "Another-Pass-2"]
    assert m.delete(f"/swa/apps/{app_id}/credential").status_code == 200
    assert m.get(f"/swa/apps/{app_id}").json()["has_credential"] is False


@pytest.mark.parametrize("source,expected", [("email", "m@example.com"), ("username", "m")])
def test_username_from_profile(db, super_admin, source, expected):
    app_id, u, m = member_with_app(db, super_admin, username_source=source)
    assert m.put(f"/swa/apps/{app_id}/credential", {"password": "legacy-Pass-1"}).status_code == 200  # no username needed
    assert m.post(f"/swa/apps/{app_id}/launch").json()["fields"][-2]["value"] == expected


def test_username_required_when_user_types_it(db, super_admin):
    app_id, u, m = member_with_app(db, super_admin)
    assert m.put(f"/swa/apps/{app_id}/credential", {"password": "x"}).status_code == 422


def test_idp_password_cannot_be_stored(db, super_admin):
    app_id, u, m = member_with_app(db, super_admin)
    r = store(m, app_id, STRONG)
    assert r.status_code == 422 and "Ifora password" in r.json()["detail"]
    assert db.query(SwaCredential).count() == 0


def test_stale_sign_in_is_refused_until_the_user_signs_in_again(db, super_admin):
    app_id, u, m = member_with_app(db, super_admin)
    store(m, app_id)
    db.query(AuthSession).filter(AuthSession.user_id == u.id).update({"auth_time": datetime.now(timezone.utc) - timedelta(seconds=settings.SWA_FRESH_AUTH_SECONDS + 60)})
    db.commit()
    r = m.post(f"/swa/apps/{app_id}/launch")
    assert r.status_code == 403 and r.json()["detail"] == "reauthentication_required"
    m2 = Api(); m2.login("m@example.com")
    assert m2.post(f"/swa/apps/{app_id}/launch").status_code == 200


def test_requires_login_csrf_and_entitlement(db, super_admin):
    app_id, u, m = member_with_app(db, super_admin)
    store(m, app_id)
    assert Api().post(f"/swa/apps/{app_id}/launch").status_code == 401
    assert m.c.post(f"/api/v1/swa/apps/{app_id}/launch", headers={"Origin": "http://localhost:3000"}).status_code == 403  # no CSRF token
    make_user(db, "x@example.com")
    o = Api(); o.login("x@example.com")
    for r in (o.get(f"/swa/apps/{app_id}"), o.post(f"/swa/apps/{app_id}/launch"), store(o, app_id)):
        assert r.status_code == 404  # unassigned: the same answer as a missing application
    assert o.delete(f"/swa/apps/{app_id}/credential").status_code == 404


def test_credentials_are_per_user(db, super_admin):
    app_id, u, m = member_with_app(db, super_admin)
    u2 = make_user(db, "second@example.com")
    assign(super_admin, {"id": app_id}, user_id=u2.id)
    m2 = Api(); m2.login("second@example.com")
    store(m, app_id, "first-secret-1", "first")
    store(m2, app_id, "second-secret-2", "second")
    assert m.post(f"/swa/apps/{app_id}/launch").json()["fields"][-1]["value"] == "first-secret-1"
    assert m2.post(f"/swa/apps/{app_id}/launch").json()["fields"][-1]["value"] == "second-secret-2"


def test_unassignment_and_inactive_app_stop_launches(db, super_admin):
    app_id, u, m = member_with_app(db, super_admin)
    store(m, app_id)
    asg = [x for x in super_admin.get(f"/admin/applications/{app_id}/assignments").json()["items"] if x["type"] == "user" and x["subject_id"] == u.id][0]
    assert super_admin.delete(f"/admin/applications/{app_id}/assignments/{asg['id']}").status_code == 200
    assert m.post(f"/swa/apps/{app_id}/launch").status_code == 404
    assign(super_admin, {"id": app_id}, user_id=u.id)
    assert m.post(f"/swa/apps/{app_id}/launch").status_code == 200
    a = super_admin.get(f"/admin/applications/{app_id}").json()
    super_admin.put(f"/admin/applications/{app_id}", {"name": a["name"], "sign_on_mode": "swa", "status": "inactive"})
    assert m.post(f"/swa/apps/{app_id}/launch").status_code == 404


def test_changing_the_login_url_clears_stored_passwords(db, super_admin):
    app_id, u, m = member_with_app(db, super_admin)
    store(m, app_id)
    r = super_admin.put(f"/admin/applications/{app_id}/swa", {"login_url": "https://elsewhere.example.com/login", "username_field": "user", "password_field": "pass"})
    assert r.json()["credentials_cleared"] is True
    assert db.query(SwaCredential).count() == 0
    assert m.post(f"/swa/apps/{app_id}/launch").status_code == 409
    # an unchanged URL keeps them
    store(m, app_id)
    super_admin.put(f"/admin/applications/{app_id}/swa", {"login_url": "https://elsewhere.example.com/login", "username_field": "user", "password_field": "pass2"})
    assert db.query(SwaCredential).count() == 1


# ---- administrators ----------------------------------------------------------------------------------------------------

def test_admin_can_list_and_reset_but_never_read(db, super_admin):
    app_id, u, m = member_with_app(db, super_admin)
    store(m, app_id, "Never-Visible-7", "jdoe")
    r = super_admin.get(f"/admin/applications/{app_id}/swa/credentials")
    assert r.json()["items"][0]["email"] == "m@example.com" and "Never-Visible-7" not in r.text
    assert "Never-Visible-7" not in super_admin.get(f"/admin/applications/{app_id}/swa").text
    assert super_admin.get(f"/admin/applications/{app_id}/swa").json()["credentials"] == 1
    assert super_admin.delete(f"/admin/applications/{app_id}/swa/credentials/{u.id}").status_code == 200
    assert super_admin.delete(f"/admin/applications/{app_id}/swa/credentials/{u.id}").status_code == 404
    assert m.post(f"/swa/apps/{app_id}/launch").status_code == 409


def test_removing_the_configuration_removes_the_credentials(db, super_admin):
    app_id, u, m = member_with_app(db, super_admin)
    store(m, app_id)
    assert super_admin.delete(f"/admin/applications/{app_id}/swa").status_code == 200
    assert db.query(SwaCredential).count() == 0
    assert super_admin.delete(f"/admin/applications/{app_id}/swa").status_code == 404


def test_audit_records_actions_without_secrets(db, super_admin):
    from backend.app.audit.model import AuditEvent

    app_id, u, m = member_with_app(db, super_admin)
    store(m, app_id, "Audit-Secret-5", "jdoe-audit")
    m.post(f"/swa/apps/{app_id}/launch")
    super_admin.delete(f"/admin/applications/{app_id}/swa/credentials/{u.id}")
    events = db.query(AuditEvent).filter(AuditEvent.action.like("SWA_%") | AuditEvent.action.like("APPLICATION_SWA_%")).all()
    names = {e.action for e in events}
    assert {"SWA_CREDENTIAL_SET", "SWA_LAUNCH", "SWA_CREDENTIAL_RESET", "APPLICATION_SWA_UPDATED"} <= names
    dump = " ".join(str(e.event_metadata) + str(e.details) for e in events)
    assert "Audit-Secret-5" not in dump and "jdoe-audit" not in dump


def test_my_apps_tile_launches_the_continue_page(db, super_admin):
    app_id, u, m = member_with_app(db, super_admin)
    tile = [t for t in m.get("/me/apps").json()["items"] if t["id"] == app_id][0]
    assert tile["sign_on_mode"] == "swa" and tile["launchable"] is True
    url = m.post(f"/me/apps/{app_id}/launch").json()["url"]
    assert url.endswith(f"/swa/continue?app={app_id}")


def test_swa_app_without_configuration_is_not_launchable(db, super_admin):
    a = super_admin.post("/admin/applications", {"name": "NoCfg", "sign_on_mode": "swa"}).json()["id"]
    u = make_user(db, "n@example.com"); assign(super_admin, {"id": a}, user_id=u.id)
    m = Api(); m.login("n@example.com")
    tile = [t for t in m.get("/me/apps").json()["items"] if t["id"] == a][0]
    assert tile["launchable"] is False
    assert m.post(f"/swa/apps/{a}/launch").status_code == 404


def test_purge_removes_credentials_of_users_who_lost_access(db, super_admin):
    from backend.app.oidc.purge import purge

    app_id, u, m = member_with_app(db, super_admin)
    keep = make_user(db, "keep@example.com"); assign(super_admin, {"id": app_id}, user_id=keep.id)
    k = Api(); k.login("keep@example.com")
    store(m, app_id); store(k, app_id)
    assert purge(db)["swa_credentials"] == 0
    asg = [x for x in super_admin.get(f"/admin/applications/{app_id}/assignments").json()["items"] if x["type"] == "user" and x["subject_id"] == u.id][0]
    super_admin.delete(f"/admin/applications/{app_id}/assignments/{asg['id']}")
    assert purge(db)["swa_credentials"] == 1
    assert [c.user_id for c in db.query(SwaCredential).all()] == [keep.id]
