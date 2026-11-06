"""Shared helpers for the recipe engine tests."""

import json
from datetime import datetime, timezone

import httpx
import pytest
from cryptography.fernet import Fernet

from backend.app.config import settings
from backend.app.recipes import actions, engine
from backend.app.recipes.http_client import EgressPolicy
from backend.app.recipes.models import RecipeJob, RecipeJobStep, RecipeOutbox

PUBLIC_IP = "93.184.216.34"
T0 = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def public_resolver(host, port):
    return [PUBLIC_IP]


class Remote:
    """Scripted remote server used through an injected httpx transport (no real network)."""

    def __init__(self, responses=None):
        self.responses = list(responses or [httpx.Response(200, json={"ok": True})])
        self.requests = []

    def __call__(self, request: httpx.Request):
        self.requests.append(request)
        r = self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]
        return r

    @property
    def transport(self):
        return httpx.MockTransport(self)


def install_remote(monkeypatch, remote: Remote, resolver=public_resolver):
    monkeypatch.setattr(actions, "http_overrides", {"policy": EgressPolicy(), "resolver": resolver, "transport": remote.transport})


@pytest.fixture
def rkey(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "RECIPE_ENCRYPTION_KEY", key)
    return key


def new_group(admin, name="Team A"):
    r = admin.post("/admin/groups", {"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def new_user(admin, email="new@example.com", **kw):
    r = admin.post("/admin/users", {"email": email, "first_name": "New", "last_name": "Person", "generate_password": True, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def step(sid, typ, config=None, **kw):
    return {"id": sid, "type": typ, "config": config or {}, **kw}


def definition(trigger_type, steps, config=None, flt=None):
    return {"trigger": {"type": trigger_type, "config": config or {}, "filter": flt or []}, "steps": steps}


def make_recipe(admin, defn, name="Recipe 1", publish=True, enable=True):
    r = admin.post("/admin/recipes", {"name": name, "definition": defn})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    if publish:
        p = admin.post(f"/admin/recipes/{rid}/publish")
        assert p.status_code == 200, p.text
    if enable:
        e = admin.post(f"/admin/recipes/{rid}/enable")
        assert e.status_code == 200, e.text
    return rid


def run_worker(now=None):
    return engine.process_once(now)


def jobs(db, recipe_id=None):
    db.expire_all()
    q = db.query(RecipeJob)
    if recipe_id is not None:
        q = q.filter(RecipeJob.recipe_id == recipe_id)
    return q.order_by(RecipeJob.id).all()


def steps_of(db, job_id):
    db.expire_all()
    return db.query(RecipeJobStep).filter(RecipeJobStep.job_id == job_id).order_by(RecipeJobStep.id).all()


def outbox_count(db):
    db.expire_all()
    return db.query(RecipeOutbox).count()


def dump(obj):
    return json.dumps(obj, default=str)
