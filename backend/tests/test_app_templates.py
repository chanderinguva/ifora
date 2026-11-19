"""Golden-path application templates (IFORA-30): loader/schema, atomic create, authorization, protocol defaults."""

import httpx
import pytest

from backend.app.app_templates import registry
from backend.app.applications.models import Application
from backend.app.oidc.models import OIDCClient
from backend.app.provisioning import adapters
from backend.app.provisioning.models import ProvisioningApp
from backend.app.recipes.http_client import EgressPolicy
from tests.conftest import Api, make_user
from tests.recipe_helpers import public_resolver, rkey  # noqa: F401

BASE = "https://app.example.com/scim/v2"


@pytest.fixture(autouse=True)
def _egress(monkeypatch, rkey):
    monkeypatch.setattr(adapters, "http_overrides", {"policy": EgressPolicy(), "resolver": public_resolver, "transport": httpx.MockTransport(lambda r: httpx.Response(200, json={}))})


def raw(**over):
    base = {"key": "x-app", "name": "X", "category": "generic", "description": "d", "sign_on": "none",
            "provisioning": {"preset": "scim-bearer"},
            "fields": [{"key": "base_url", "label": "URL"}, {"key": "secret", "label": "Token", "secret": True}]}
    return {**base, **over}


# ---- loader / schema -------------------------------------------------------------------------------------------

def test_every_shipped_template_validates_and_keys_are_unique():
    ts = registry.all_templates()
    assert {t.key for t in ts} >= {"slack", "github", "jira", "pagerduty", "entra", "oidc-web", "saml-generic", "scim-generic"}
    assert len({t.key for t in ts}) == len(ts)
    assert all(t.connector is None or t.connector == t.key for t in ts)


def test_wildcard_redirect_pattern_fails_the_loader():
    with pytest.raises(registry.TemplateInvalid, match="wildcard"):
        registry.validate_template(raw(sign_on="oidc", oidc={"type": "web"}, provisioning=None,
                                       fields=[{"key": "redirect_uri", "label": "R", "placeholder": "https://*.example.com/cb"}]))


@pytest.mark.parametrize("over,msg", [
    ({"provisioning": {"preset": "nope"}}, "unknown provisioning preset"),
    ({"connector": "nope"}, "unknown connector"),
    ({"provisioning": {"preset": "scim-bearer", "base_url": "http://plain.example.com"}}, "https"),
    ({"fields": [{"key": "base_url", "label": "U"}]}, "missing field"),
    ({"fields": [{"key": "base_url", "label": "U"}, {"key": "secret", "label": "T"}]}, "marked secret"),
    ({"sign_on": "oidc"}, "oidc block"),
    ({"surprise": 1}, ""),
])
def test_invalid_templates_are_rejected(over, msg):
    with pytest.raises(registry.TemplateInvalid, match=msg):
        registry.validate_template(raw(**over))


def test_list_endpoint_returns_templates_without_internals(admin):
    r = admin.get("/admin/application-templates")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len({i["key"] for i in items}) == len(items) >= 8
    assert all(set(i) == {"key", "name", "category", "description", "connector", "sign_on", "oidc_type", "provisioning", "fields", "checklist"} for i in items)


# ---- create ------------------------------------------------------------------------------------------------------

def test_slack_template_creates_disabled_app_and_provisioning(super_admin, db):
    r = super_admin.post("/admin/application-templates/slack/create", {"name": "Slack", "values": {"secret": "xoxp-token"}})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["checklist"] and body["provisioning_app_id"] and "xoxp-token" not in r.text
    app = db.get(Application, body["application_id"])
    assert app.status == "inactive" and app.sign_on_mode == "none"
    p = db.query(ProvisioningApp).filter(ProvisioningApp.application_id == app.id).one()
    assert p.enabled is False and p.base_url == "https://api.slack.com/scim/v2" and p.kind == "scim" and p.tenant_id == app.tenant_id


def test_generic_oidc_template_is_pkce_exact_redirect_no_implicit(super_admin, db):
    r = super_admin.post("/admin/application-templates/oidc-spa/create", {"name": "SPA", "values": {"redirect_uri": "https://spa.example.com/cb"}})
    assert r.status_code == 201, r.text
    c = db.query(OIDCClient).filter(OIDCClient.client_id == r.json()["client_id"]).one()
    assert c.client_type == "public" and c.redirect_uris == ["https://spa.example.com/cb"] and "implicit" not in " ".join(c.grant_types)
    assert db.get(Application, r.json()["application_id"]).status == "inactive"
    web = super_admin.post("/admin/application-templates/oidc-web/create", {"name": "Web", "values": {"redirect_uri": "https://w.example.com/cb"}})
    assert web.status_code == 201 and web.json()["client_secret"]  # confidential: secret shown once


def test_wildcard_redirect_value_is_refused_and_nothing_persists(super_admin, db):
    r = super_admin.post("/admin/application-templates/oidc-web/create", {"name": "Wild", "values": {"redirect_uri": "https://*.example.com/cb"}})
    assert r.status_code == 422
    assert db.query(Application).filter(Application.name == "Wild").count() == 0 and db.query(OIDCClient).filter(OIDCClient.name == "Wild").count() == 0


def test_saml_template_signs_assertions_and_binds_audience(super_admin, db):
    r = super_admin.post("/admin/application-templates/saml-generic/create",
                         {"name": "Wiki", "values": {"sp_entity_id": "https://wiki.example.com/sp", "acs_url": "https://wiki.example.com/acs"}})
    assert r.status_code == 201, r.text
    p = super_admin.get(f"/admin/applications/{r.json()['application_id']}/saml").json()["provider"]
    assert p["signing"] == "both" and p["audience"] == "https://wiki.example.com/sp" and p["acs_url"] == "https://wiki.example.com/acs"


def test_failure_partway_rolls_everything_back(super_admin, db, monkeypatch):
    from backend.app.provisioning import routes as prov

    def boom(*a, **k):
        raise RuntimeError("injected")

    monkeypatch.setattr(prov.crypto, "encrypt", boom)
    with pytest.raises(RuntimeError):
        super_admin.post("/admin/application-templates/slack/create", {"name": "Half", "values": {"secret": "t"}})
    assert db.query(Application).filter(Application.name == "Half").count() == 0 and db.query(ProvisioningApp).filter(ProvisioningApp.name == "Half").count() == 0


@pytest.mark.parametrize("path,body,code", [
    ("nope", {"name": "A", "values": {}}, 404),
    ("slack", {"name": "A", "values": {}}, 422),                              # missing required field
    ("slack", {"name": "A", "values": {"secret": "t", "extra": "1"}}, 422),   # unknown value
    ("scim-generic", {"name": "A", "values": {"secret": "t", "base_url": "http://insecure.example.com"}}, 422),
])
def test_negative_cases(super_admin, db, path, body, code):
    assert super_admin.post(f"/admin/application-templates/{path}/create", body).status_code == code
    assert db.query(Application).filter(Application.name == "A").count() == 0


def test_duplicate_name_conflicts_without_leaving_rows(super_admin, db):
    ok = {"name": "Dup", "values": {"secret": "t"}}
    assert super_admin.post("/admin/application-templates/slack/create", ok).status_code == 201
    assert super_admin.post("/admin/application-templates/slack/create", ok).status_code == 409
    assert db.query(Application).filter(Application.name == "Dup").count() == 1


def test_admin_without_applications_write_gets_403_and_no_rows(db):
    u = make_user(db, "helpdesk@example.com", admin=True, roles=("help_desk_admin",))
    a = Api()
    assert a.login(u.email).status_code == 200
    assert a.get("/admin/application-templates").status_code == 200  # read is allowed
    r = a.post("/admin/application-templates/slack/create", {"name": "Nope", "values": {"secret": "t"}})
    assert r.status_code == 403
    assert db.query(Application).filter(Application.name == "Nope").count() == 0
    assert Api().get("/admin/application-templates").status_code == 401
