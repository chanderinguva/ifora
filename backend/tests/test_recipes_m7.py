"""R-M7: session and credential triggers (sign-out, MFA on/off, password changed)."""

from backend.app.recipes.definition import EVENT_TRIGGERS
from tests.conftest import Api, STRONG, make_user
from tests.recipe_helpers import T0, definition, jobs, make_recipe, run_worker, step, steps_of
from tests.recipe_helpers import rkey  # noqa: F401
from tests.test_mfa import enrol

LOG = lambda sid, msg: step(sid, "log", {"message": msg})  # noqa: E731


def messages(db, rid):
    return [steps_of(db, j.id)[0].output["message"] for j in jobs(db, rid)]


def test_new_triggers_are_registered():
    for t in ("session.logout", "mfa.enabled", "mfa.disabled", "password.changed"):
        assert t in EVENT_TRIGGERS


def test_logout_trigger(db, admin):
    rid = make_recipe(admin, definition("session.logout", [LOG("l", "out {{trigger.user.email}}")]))
    u = make_user(db, "leaver@example.com")
    a = Api()
    assert a.login(u.email, STRONG).status_code == 200
    assert a.post("/logout").status_code == 200
    run_worker(T0)
    assert messages(db, rid) == ["out leaver@example.com"]


def test_mfa_enabled_and_disabled_triggers(db, admin):
    on = make_recipe(admin, definition("mfa.enabled", [LOG("l", "on {{trigger.user.email}}")]), name="on")
    off = make_recipe(admin, definition("mfa.disabled", [LOG("l", "off {{trigger.user.email}}")]), name="off")
    u = make_user(db, "twofa@example.com")
    a = Api()
    a.login(u.email, STRONG)
    codes = enrol(a, db, u.email)
    assert a.post("/me/mfa/disable", {"password": STRONG, "code": codes[0]}).status_code == 200
    run_worker(T0)
    assert messages(db, on) == ["on twofa@example.com"]
    assert messages(db, off) == ["off twofa@example.com"]


def test_password_changed_trigger_self_service_and_admin_reset(db, admin):
    rid = make_recipe(admin, definition("password.changed", [LOG("l", "pw {{trigger.user.email}}")]))
    u = make_user(db, "pw@example.com")
    a = Api()
    a.login(u.email, STRONG)
    assert a.post("/me/password", {"current_password": STRONG, "new_password": "Another1Passw0rd"}).status_code == 200
    assert admin.post(f"/admin/users/{u.id}/password", {"new_password": STRONG}).status_code == 200
    run_worker(T0)
    assert messages(db, rid).count("pw pw@example.com") == 2


# ---- connection permissions ----------------------------------------------------------------------------------

def _http_def(cid):
    return definition("manual", [step("h", "http_request", {"method": "GET", "url": "https://api.example.com/x", "connection_id": cid})])


def _conn(admin, **extra):
    r = admin.post("/admin/recipe-connections", {"name": "crm", "kind": "bearer", "allowed_host": "api.example.com", "secret": "s3cret-token", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_open_connection_behaves_as_before(db, admin, rkey, super_admin):
    c = _conn(admin)
    assert c["restricted"] is False and c["can_use"] is True
    other = make_admin_api(db, "other-admin@example.com")
    r = other.post("/admin/recipes", {"name": "r", "definition": _http_def(c["id"])})
    assert r.status_code in (200, 201), r.text


def make_admin_api(db, email):
    u = make_user(db, email, admin=True)
    a = Api()
    assert a.login(u.email, STRONG).status_code == 200
    a.user = u
    return a


def test_restricted_connection_only_usable_by_listed_admins(db, admin, rkey, super_admin):
    listed = make_admin_api(db, "listed@example.com")
    outsider = make_admin_api(db, "outsider@example.com")
    c = _conn(admin, allowed_users=[listed.user.id])
    assert c["restricted"] is True and c["allowed_users"] == [listed.user.id]
    assert listed.post("/admin/recipes", {"name": "ok", "definition": _http_def(c["id"])}).status_code in (200, 201)
    r = outsider.post("/admin/recipes", {"name": "no", "definition": _http_def(c["id"])})
    assert r.status_code == 422 and "not allowed to use" in r.json()["detail"]
    assert admin.post("/admin/recipes", {"name": "creator", "definition": _http_def(c["id"])}).status_code in (200, 201)
    assert super_admin.post("/admin/recipes", {"name": "super", "definition": _http_def(c["id"])}).status_code in (200, 201)
    seen = {i["id"]: i for i in outsider.get("/admin/recipe-connections").json()["items"]}[c["id"]]
    assert seen["can_use"] is False and seen["can_manage"] is False and seen["allowed_users"] is None


def test_only_creator_or_super_admin_manage_a_restricted_connection(db, admin, rkey, super_admin):
    listed = make_admin_api(db, "listed2@example.com")
    c = _conn(admin, allowed_users=[listed.user.id])
    body = {"name": "crm", "kind": "bearer", "allowed_host": "api.example.com"}
    assert listed.put(f"/admin/recipe-connections/{c['id']}", body).status_code == 403
    assert listed.delete(f"/admin/recipe-connections/{c['id']}").status_code == 403
    assert super_admin.put(f"/admin/recipe-connections/{c['id']}", body).status_code == 200
    assert admin.put(f"/admin/recipe-connections/{c['id']}", {**body, "allowed_users": []}).status_code == 200  # lifts it
    assert listed.delete(f"/admin/recipe-connections/{c['id']}").status_code == 200  # open again


def test_allow_list_must_name_administrators(db, admin, rkey):
    plain = make_user(db, "plain@example.com")
    r = admin.post("/admin/recipe-connections", {"name": "x", "kind": "bearer", "allowed_host": "api.example.com", "secret": "abc", "allowed_users": [plain.id]})
    assert r.status_code == 422
