"""/metrics: off by default, token protected, aggregate counts only."""

from backend.app.config import settings
from tests.conftest import Api
from tests.recipe_helpers import new_user

TOKEN = "t" * 40


def scrape(token=None):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    return Api().c.get("/metrics", headers=h)


def test_endpoint_does_not_exist_without_a_token_setting(monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "")
    assert scrape(TOKEN).status_code == 404


def test_weak_token_setting_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "short")
    assert scrape("short").status_code == 404


def test_requires_the_exact_bearer_token(monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", TOKEN)
    assert scrape().status_code == 401
    assert scrape("wrong" * 8).status_code == 401
    r = scrape(TOKEN)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")


def test_exposes_counts_without_personal_data(monkeypatch, admin):
    monkeypatch.setattr(settings, "METRICS_TOKEN", TOKEN)
    new_user(admin, "metric.person@example.com")
    body = scrape(TOKEN).text
    assert "# TYPE identityforge_users gauge" in body and 'identityforge_users{status="active"}' in body
    assert "identityforge_recipe_worker_up" in body and "identityforge_active_sessions" in body
    assert "metric.person" not in body and "example.com" not in body
