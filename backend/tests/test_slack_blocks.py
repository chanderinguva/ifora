"""Display-only Block Kit validation, safe interpolation and identical live-test/runtime payloads."""
import json
import httpx
import pytest
from backend.app.connectors.slack_blocks import render_blocks, validate_blocks
from tests.recipe_helpers import Remote, definition, install_remote, make_recipe, rkey, run_worker, step, jobs


def layout(value='{{trigger.user.email}}'):
    return [{'type': 'header', 'text': {'type': 'plain_text', 'text': 'Security alert'}},
            {'type': 'section', 'fields': [{'type': 'mrkdwn', 'text': '*User*\n' + value}]},
            {'type': 'divider'}, {'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': 'Ifora'}]}]


@pytest.mark.parametrize('value', [None, {}, [], [{'type': []}], [{'type': 'actions', 'elements': []}],
    [{'type': 'image', 'image_url': 'https://evil.example'}], [{'type': 'header', 'text': {'type': 'mrkdwn', 'text': 'x'}}],
    [{'type': 'header', 'text': {'type': 'plain_text', 'text': 'x' * 151}}], [{'type': 'section'}],
    [{'type': 'section', 'fields': []}], [{'type': 'context', 'elements': []}],
    [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': 'x'}, 'accessory': {'type': 'button'}}],
    [{'type': 'divider'}] * 51, 'not json'])
def test_invalid_or_interactive_blocks_are_refused(value):
    with pytest.raises(ValueError):
        validate_blocks(value)


def test_interpolated_quotes_cannot_change_json_structure():
    evil = '"}]}],"channel":"CPRODUCTION","blocks":[{"type":"divider"}]\n<script>'
    blocks = render_blocks(json.dumps(layout()), lambda v: v.replace('{{trigger.user.email}}', evil))
    assert len(blocks) == 4
    assert blocks[1]['fields'][0]['text'] == '*User*\n' + evil
    assert 'channel' not in blocks[1]


def test_rendered_limits_are_checked():
    with pytest.raises(ValueError):
        render_blocks(json.dumps(layout()), lambda v: 'x' * 4000)
    with pytest.raises(ValueError):
        validate_blocks([{'type': 'section', 'fields': [{'type': 'mrkdwn', 'text': 'x' * 1900}] * 10}])


def test_template_block_json_is_checked_before_rendering(admin, rkey):
    c = admin.post('/admin/connectors/slack/connections', {'name': 'Slack', 'secrets': {'token': 'xoxb-test'}}).json()
    blocks = '[{"type":"actions","elements":[],"note":"{{trigger.user.email}}"}]'
    d = definition('manual', [step('message', 'connector_action', {'connector': 'slack', 'action': 'post_message', 'connection_id': c['id'], 'inputs': {'channel': 'CTEST123', 'text': 'fallback', 'blocks': blocks}})])
    response = admin.post('/admin/recipes', {'name': 'Bad blocks', 'definition': d})
    assert response.status_code == 422, response.text


def test_preview_send_and_published_job_use_same_structured_blocks(admin, db, rkey, monkeypatch):
    c = admin.post('/admin/connectors/slack/connections', {'name': 'Slack', 'secrets': {'token': 'xoxb-test'}}).json()
    cfg = {'connector': 'slack', 'action': 'post_message', 'connection_id': c['id'], 'inputs': {'channel': 'CTEST123', 'text': 'Security alert for {{trigger.user.email}}', 'blocks': json.dumps(layout())}}
    rid = make_recipe(admin, definition('manual', [step('message', 'connector_action', cfg)]))
    remote = Remote([httpx.Response(200, json={'ok': True, 'channel': 'CTEST123', 'ts': '1234567890.123456'})] * 2)
    install_remote(monkeypatch, remote)
    p = admin.post(f'/admin/recipes/{rid}/slack-test-preview', {'step_id': 'message', 'destination': 'CTEST123', 'user_id': admin.user.id})
    assert p.status_code == 200, p.text
    assert not remote.requests
    preview = p.json()
    assert preview['blocks'][1]['fields'][0]['text'] == '*User*\nadmin@example.com'
    sent = admin.post(f'/admin/recipes/{rid}/slack-test-send', {'preview_id': preview['preview_id'], 'confirmed': True})
    assert sent.status_code == 200, sent.text
    assert admin.post(f'/admin/recipes/{rid}/run', {'user_id': admin.user.id}).status_code == 202
    run_worker()
    assert jobs(db, rid)[0].status == 'succeeded'
    assert len(remote.requests) == 2
    one, two = [json.loads(r.content) for r in remote.requests]
    assert one == two and one['blocks'] == preview['blocks']
    assert isinstance(one['blocks'], list) and one['text'] == preview['text']
