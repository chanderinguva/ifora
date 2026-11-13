# ruff: noqa: F401, F811 -- imported pytest fixture
"""Only an explicitly previewed Slack message may be sent; no recipe side effects."""
import json
import httpx
import pytest
from backend.app.audit.model import AuditEvent
from backend.app.recipes.models import Recipe, RecipeConnection
from tests.conftest import Api, make_user
from tests.recipe_helpers import Remote, definition, dump, install_remote, make_recipe, rkey, step


def setup_recipe(admin):
    c = admin.post('/admin/connectors/slack/connections', {'name': 'Slack test', 'secrets': {'token': 'xoxb-test-secret'}}).json()
    cfg = {'connector': 'slack', 'connection_id': c['id'], 'action': 'post_message', 'inputs': {'channel': 'CPRODUCTION', 'text': '*Hello* {{trigger.user.email}} :wave:', 'thread_ts': '1234567890.123456'}}
    rid = make_recipe(admin, definition('login.failed', [step('message', 'connector_action', cfg), step('other', 'log', {'message': 'Do not execute'})], {'min_failures': 1}), publish=False, enable=False)
    return rid, c['id']


def preview(admin, rid, **patch):
    return admin.post(f'/admin/recipes/{rid}/slack-test-preview', {'step_id': 'message', 'destination': 'CTEST123', 'user_id': admin.user.id, **patch})


def send(admin, rid, token, confirmed=True):
    return admin.post(f'/admin/recipes/{rid}/slack-test-send', {'preview_id': token, 'confirmed': confirmed})


def test_preview_then_single_send_exact_message_no_other_steps(admin, db, rkey, monkeypatch):
    rid, cid = setup_recipe(admin)
    remote = Remote([httpx.Response(200, json={'ok': True, 'ts': '1234567890.123456', 'channel': 'CTEST123'})])
    install_remote(monkeypatch, remote)
    p = preview(admin, rid)
    assert p.status_code == 200, p.text
    assert remote.requests == []
    assert p.json()['text'] == '*Hello* admin@example.com :wave:'
    token = p.json()['preview_id']
    assert send(admin, rid, token, False).status_code == 422
    result = send(admin, rid, token)
    assert result.status_code == 200, result.text
    assert len(remote.requests) == 1
    body = json.loads(remote.requests[0].content)
    assert body['channel'] == 'CTEST123' and body['text'] == p.json()['text']
    assert not body.get('thread_ts')
    assert send(admin, rid, token).status_code in (409, 429)
    assert len(remote.requests) == 1
    row = db.get(Recipe, rid)
    assert row.published_version is None
    audits = dump([a.event_metadata for a in db.query(AuditEvent)])
    assert 'xoxb-test-secret' not in audits and 'CTEST123' in audits and 'test_message' in audits


@pytest.mark.parametrize('change', ['draft', 'connection', 'permissions', 'expired'])
def test_preview_is_invalidated_by_change(admin, db, rkey, monkeypatch, change):
    from backend.app import ratelimit
    rid, cid = setup_recipe(admin)
    token = preview(admin, rid).json()['preview_id']
    if change == 'draft':
        row = db.get(Recipe, rid); row.draft = {**row.draft, 'steps': []}; db.commit()
    elif change == 'connection':
        row = db.get(RecipeConnection, cid); row.updated_at = row.updated_at.replace(year=2025); db.commit()
    elif change == 'permissions':
        other = make_user(db, 'other-admin@example.com', admin=True)
        row = db.get(RecipeConnection, cid); row.allowed_users = [other.id]; row.created_by = other.id; db.commit()
    else:
        ratelimit._redis().delete(f'recipe-slack-preview:{token}')
    remote = Remote([]); install_remote(monkeypatch, remote)
    assert send(admin, rid, token).status_code in (403, 409)
    assert not remote.requests


def test_rejects_non_message_steps_and_missing_sample(admin, rkey):
    rid, _ = setup_recipe(admin)
    assert preview(admin, rid, step_id='other').status_code == 422
    assert preview(admin, rid, user_id=None).status_code == 422
    assert preview(admin, rid, destination='https://evil.example').status_code == 422


def test_provider_error_consumes_preview_and_does_not_echo_secret(admin, rkey, monkeypatch):
    rid, _ = setup_recipe(admin)
    token = preview(admin, rid).json()['preview_id']
    remote = Remote([httpx.Response(200, json={'ok': False, 'error': 'invalid_auth'})]); install_remote(monkeypatch, remote)
    response = send(admin, rid, token)
    assert response.status_code == 502
    assert 'xoxb-test-secret' not in response.text
    assert send(admin, rid, token).status_code in (409, 429)
    assert len(remote.requests) == 1


def test_another_administrator_cannot_send_or_preview(admin, db, rkey):
    rid, _ = setup_recipe(admin)
    token = preview(admin, rid).json()['preview_id']
    other = make_user(db, 'other@example.com', admin=True)
    api = Api(); assert api.login(other.email).status_code == 200
    assert api.post(f'/admin/recipes/{rid}/slack-test-preview', {'step_id': 'message', 'destination': 'CTEST123', 'user_id': other.id}).status_code == 403
    assert send(api, rid, token).status_code == 403


def test_redis_failure_is_closed_no_send(admin, rkey, monkeypatch):
    from backend.app import ratelimit
    rid, _ = setup_recipe(admin)
    token = preview(admin, rid).json()['preview_id']
    def unavailable():
        raise ConnectionError('unavailable')
    monkeypatch.setattr(ratelimit, '_redis', unavailable)
    assert send(admin, rid, token).status_code == 503
