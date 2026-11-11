"""Every API error is a SCIM Error (RFC 7644 3.12): schemas, status as a string, detail as a string."""

from backend.app.scim.errors import ERROR_SCHEMA
from tests.conftest import Api, make_user


def assert_scim_error(r, status):
    assert r.status_code == status, r.text
    body = r.json()
    assert body["schemas"] == [ERROR_SCHEMA]
    assert body["status"] == str(status)
    assert isinstance(body["detail"], str) and body["detail"]
    return body


def test_unauthenticated(db):
    assert_scim_error(Api().get("/admin/users"), 401)


def test_unknown_route_and_wrong_method(db):
    api = Api()
    assert_scim_error(api.c.get("/api/v1/does-not-exist"), 404)
    assert_scim_error(api.c.delete("/api/v1/login"), 405)


def test_forbidden_and_not_found(db):
    make_user(db, "plain@example.com")
    u = Api()
    assert u.login("plain@example.com").status_code == 200
    assert_scim_error(u.get("/admin/users"), 403)


def test_validation_error_has_readable_detail_and_field_list(db):
    r = Api().post("/login", {"email": "x"}, csrf=False)
    body = assert_scim_error(r, 422)
    assert body["scimType"] == "invalidValue"
    assert "email" in body["detail"] or "password" in body["detail"]
    assert isinstance(body["errors"], list) and body["errors"]
    assert all("input" not in e and "ctx" not in e for e in body["errors"])   # never echo submitted values
