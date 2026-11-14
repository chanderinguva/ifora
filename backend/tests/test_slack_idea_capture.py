"""Slack idea shortcut authentication, authorization and duplicate behavior."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from backend.app.config import settings
from backend.app.integrations.models import SlackIdeaCapture


def signed(body: bytes, secret: str, timestamp: int | None = None):
    ts = str(timestamp or int(time.time()))
    signature = "v0=" + hmac.new(secret.encode(), b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": signature,
            "Content-Type": "application/x-www-form-urlencoded"}


def payload(user="UOWNER", team="TIFORA", text="Add passkey recovery analytics"):
    return {"type": "message_action", "callback_id": "send_to_ifora",
            "team": {"id": team, "domain": "inguva"}, "user": {"id": user},
            "channel": {"id": "CIDEAS"},
            "message": {"ts": "1794700800.123456", "text": text,
                        "files": [{"id": "F1", "name": "mockup.png", "mimetype": "image/png", "size": 42}]}}


def post(client, data, secret="test-signing-secret", timestamp=None):
    body = urlencode({"payload": json.dumps(data)}).encode()
    return client.post("/api/v1/integrations/slack/idea-shortcut", content=body,
                       headers=signed(body, secret, timestamp))


def configure(monkeypatch):
    monkeypatch.setattr(settings, "SLACK_IDEA_CAPTURE_ENABLED", True)
    monkeypatch.setattr(settings, "SLACK_IDEA_SIGNING_SECRET", "test-signing-secret")
    monkeypatch.setattr(settings, "SLACK_IDEA_ALLOWED_TEAM_ID", "TIFORA")
    monkeypatch.setattr(settings, "SLACK_IDEA_ALLOWED_USER_IDS", "UOWNER")


def test_valid_shortcut_queues_once(anon, db, monkeypatch):
    configure(monkeypatch)
    first = post(anon.c, payload())
    second = post(anon.c, payload())
    assert first.status_code == 200 and second.status_code == 200
    assert first.content == b"" and second.content == b""
    rows = db.query(SlackIdeaCapture).all()
    assert len(rows) == 1
    assert rows[0].payload["sourceUrl"].endswith("/archives/CIDEAS/p1794700800123456")
    assert "mockup.png" in rows[0].payload["raw"]


def test_rejects_bad_signature_replay_workspace_and_user(anon, monkeypatch):
    configure(monkeypatch)
    assert post(anon.c, payload(), secret="wrong").status_code == 401
    assert post(anon.c, payload(), timestamp=int(time.time()) - 301).status_code == 401
    assert post(anon.c, payload(team="TOTHER")).status_code == 403
    assert post(anon.c, payload(user="UOTHER")).status_code == 403

