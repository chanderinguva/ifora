"""Session cookie authentication."""

from backend.app.auth.session import Session as AuthSession
from backend.app.users.model import User
from tests.conftest import ORIGIN, STRONG, Api, make_user


def test_login_sets_httponly_cookie_and_hashes_token(db):
    make_user(db, "a@example.com")
    api = Api()
    r = api.login("a@example.com")
    assert r.status_code == 200
    sc = r.headers["set-cookie"]
    assert "identityforge_session=" in sc and "HttpOnly" in sc and "SameSite=lax" in sc
    raw = api.c.cookies.get("identityforge_session")
    stored = db.query(AuthSession).one().token
    assert stored != raw and len(stored) == 64
    assert "password_hash" not in r.text


def test_unknown_user_and_bad_password_are_indistinguishable(db):
    make_user(db, "a@example.com")
    api = Api()
    r1 = api.login("a@example.com", "WrongPassw0rd!!")
    r2 = api.login("nobody@example.com", "WrongPassw0rd!!")
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json()


def test_me_requires_session(anon):
    assert anon.get("/me").status_code == 401


def test_me_returns_user_and_csrf(member):
    d = member.get("/me").json()
    assert d["authenticated"] and d["user"]["email"] == "member@example.com" and d["csrf_token"]


def test_login_rejects_foreign_origin(db):
    make_user(db, "a@example.com")
    api = Api()
    r = api.c.post("/api/v1/login", json={"email": "a@example.com", "password": STRONG}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_logout_needs_csrf_then_revokes(member):
    assert member.post("/logout", csrf=False).status_code == 403
    member.csrf = "bad"
    assert member.post("/logout").status_code == 403
    member.csrf = member.get("/me").json()["csrf_token"]
    cookie = member.c.cookies.get("identityforge_session")
    assert member.post("/logout").status_code == 200
    member.c.cookies.set("identityforge_session", cookie)  # replay the old cookie
    assert member.get("/me").status_code == 401


def test_csrf_token_is_bound_to_session(db):
    make_user(db, "a@example.com")
    a, b = Api(), Api()
    a.login("a@example.com")
    b.login("a@example.com")
    assert a.csrf != b.csrf
    a.csrf = b.csrf
    assert a.post("/logout").status_code == 403


def test_lockout_after_repeated_failures(db):
    make_user(db, "a@example.com")
    api = Api()
    for _ in range(5):
        assert api.login("a@example.com", "WrongPassw0rd!!").status_code == 401
    # Correct password is now refused too, with the same generic response
    r = api.login("a@example.com")
    assert r.status_code == 401 and r.json()["detail"] == "Invalid credentials"


def test_inactive_user_cannot_login(db):
    u = make_user(db, "a@example.com")
    u.status = "inactive"
    db.commit()
    assert Api().login("a@example.com").status_code == 401


def test_session_of_deactivated_user_stops_working(db, member):
    u = db.query(User).filter_by(email="member@example.com").one()
    u.status = "inactive"
    db.commit()
    assert member.get("/me").status_code == 401


def test_bootstrap_requires_key_and_only_once(db):
    api = Api()
    body = {"email": "boss@example.com", "password": STRONG, "first_name": "B", "last_name": "B", "secret_key": "wrong"}
    assert api.c.post("/api/v1/admin/bootstrap", json=body).status_code == 403
    from backend.app.config import settings

    body["secret_key"] = settings.ADMIN_SECRET_KEY
    assert api.c.post("/api/v1/admin/bootstrap", json=body).status_code == 200
    body["email"] = "other@example.com"
    assert api.c.post("/api/v1/admin/bootstrap", json=body).status_code == 409
