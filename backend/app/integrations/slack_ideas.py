"""Slack message shortcut ingestion and durable delivery to Ifora Discovery."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db import get_db
from backend.app.integrations.models import SlackIdeaCapture
from backend.app.tenancy import tenant_session

router = APIRouter(prefix="/integrations/slack", tags=["integrations"])
CALLBACK_ID = "send_to_ifora"
MAX_BODY = 256_000
MAX_AGE_SECONDS = 300
_IDEA_NAMESPACE = uuid.UUID("ea921e5f-e668-4c7d-b01a-75be32e313ac")
_SLACK_RESPONSE_HOSTS = {"hooks.slack.com", "hooks.slack-gov.com"}


def verify_slack_signature(body: bytes, timestamp: str, signature: str, now: int | None = None) -> bool:
    """Validate Slack's v0 HMAC and reject replayed requests."""
    if not settings.SLACK_IDEA_SIGNING_SECRET or not timestamp.isdigit() or not signature.startswith("v0="):
        return False
    current = int(time.time()) if now is None else now
    if abs(current - int(timestamp)) > MAX_AGE_SECONDS:
        return False
    base = b"v0:" + timestamp.encode("ascii") + b":" + body
    expected = "v0=" + hmac.new(settings.SLACK_IDEA_SIGNING_SECRET.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _allowed_users() -> set[str]:
    return {value.strip() for value in settings.SLACK_IDEA_ALLOWED_USER_IDS.split(",") if value.strip()}


def _message_link(team_domain: str, channel_id: str, message_ts: str) -> str:
    if not team_domain or not channel_id or not message_ts:
        return ""
    return f"https://{team_domain}.slack.com/archives/{channel_id}/p{message_ts.replace('.', '')}"


def _valid_slack_response_url(value: str) -> bool:
    if not value or len(value) > 2048:
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (parsed.scheme == "https" and parsed.hostname in _SLACK_RESPONSE_HOSTS
            and port in (None, 443) and not parsed.username and not parsed.password)


def _discovery_item_url(idea_id: str) -> str:
    try:
        parsed = urlsplit(settings.IFORA_DISCOVERY_INGEST_URL)
    except ValueError:
        return ""
    if parsed.scheme != "https" or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, "/", urlencode({"idea": idea_id}), ""))


def _post_thread_confirmation(response_url: str, thread_ts: str, idea_id: str) -> None:
    item_url = _discovery_item_url(idea_id)
    if not _valid_slack_response_url(response_url) or not thread_ts or not item_url:
        return
    message = {
        "response_type": "in_channel",
        "replace_original": False,
        "thread_ts": thread_ts,
        "text": f"✅ Queued for Ifora Discovery — <{item_url}|Open idea>",
    }
    try:
        with httpx.Client(timeout=settings.SLACK_IDEA_DELIVERY_TIMEOUT_SECONDS, follow_redirects=False) as client:
            client.post(response_url, json=message)
    except httpx.HTTPError:
        pass


def _capture_payload(payload: dict) -> tuple[str, dict]:
    if payload.get("type") != "message_action" or payload.get("callback_id") != CALLBACK_ID:
        raise HTTPException(status_code=400, detail="Unsupported Slack interaction")
    team = payload.get("team") or {}
    user = payload.get("user") or {}
    channel = payload.get("channel") or {}
    message = payload.get("message") or {}
    team_id, user_id = str(team.get("id", "")), str(user.get("id", ""))
    if not settings.SLACK_IDEA_ALLOWED_TEAM_ID or team_id != settings.SLACK_IDEA_ALLOWED_TEAM_ID:
        raise HTTPException(status_code=403, detail="Slack workspace is not allowed")
    if user_id not in _allowed_users():
        raise HTTPException(status_code=403, detail="Slack user is not allowed")
    channel_id, message_ts = str(channel.get("id", "")), str(message.get("ts", ""))
    text = str(message.get("text", "")).strip()
    if not channel_id or not message_ts or not text:
        raise HTTPException(status_code=422, detail="Slack message is missing text or identity")
    event_key = f"{team_id}:{channel_id}:{message_ts}"
    files = [
        {"id": str(f.get("id", "")), "name": str(f.get("name", "")),
         "mimetype": str(f.get("mimetype", "")), "size": int(f.get("size") or 0)}
        for f in message.get("files", []) if isinstance(f, dict)
    ][:20]
    source_url = _message_link(str(team.get("domain", "")), channel_id, message_ts)
    title = next((line.strip() for line in text.splitlines() if line.strip()), "Slack idea")[:180]
    attachment_lines = [f"- {f['name'] or f['id']} ({f['mimetype'] or 'file'}, {f['size']} bytes)" for f in files]
    raw = text
    if attachment_lines:
        raw += "\n\nSlack attachments:\n" + "\n".join(attachment_lines)
    return event_key, {
        "ideaId": str(uuid.uuid5(_IDEA_NAMESPACE, event_key)), "eventKey": event_key,
        "title": title, "raw": raw, "sourceUrl": source_url, "files": files,
        "slack": {"teamId": team_id, "channelId": channel_id, "messageTs": message_ts,
                  "capturedByUserId": user_id},
    }


@router.post("/idea-shortcut", include_in_schema=False)
async def idea_shortcut(request: Request, background_tasks: BackgroundTasks,
                        db: Session = Depends(get_db)):
    if not settings.SLACK_IDEA_CAPTURE_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(status_code=413, detail="Slack request is too large")
    timestamp = request.headers.get("x-slack-request-timestamp", "")
    signature = request.headers.get("x-slack-signature", "")
    if not verify_slack_signature(body, timestamp, signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")
    try:
        encoded = parse_qs(body.decode("utf-8"), strict_parsing=True)["payload"][0]
        payload = json.loads(encoded)
    except (KeyError, IndexError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Slack payload") from exc
    event_key, capture = _capture_payload(payload)
    response_url = str(payload.get("response_url", ""))
    message = payload.get("message") or {}
    thread_ts = str(message.get("thread_ts") or message.get("ts") or "")
    row = SlackIdeaCapture(dedupe_key=event_key, payload=capture)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        background_tasks.add_task(
            _post_thread_confirmation, response_url, thread_ts, capture["ideaId"])
        return Response(status_code=200)
    background_tasks.add_task(
        _post_thread_confirmation, response_url, thread_ts, capture["ideaId"])
    return Response(status_code=200)


def _deliver(capture: SlackIdeaCapture) -> None:
    if not settings.IFORA_DISCOVERY_INGEST_URL or not settings.IFORA_DISCOVERY_INGEST_TOKEN:
        raise RuntimeError("Discovery ingestion is not configured")
    headers = {"Authorization": f"Bearer {settings.IFORA_DISCOVERY_INGEST_TOKEN}"}
    if settings.IFORA_DISCOVERY_SITES_AUTH_TOKEN:
        headers["OAI-Sites-Authorization"] = f"Bearer {settings.IFORA_DISCOVERY_SITES_AUTH_TOKEN}"
    with httpx.Client(timeout=settings.SLACK_IDEA_DELIVERY_TIMEOUT_SECONDS, follow_redirects=False) as client:
        response = client.post(settings.IFORA_DISCOVERY_INGEST_URL, json=capture.payload, headers=headers)
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Discovery returned HTTP {response.status_code}")


def process_pending_once(limit: int = 20) -> dict[str, int]:
    """Lease and deliver due captures; safe for multiple worker processes."""
    now = datetime.now(timezone.utc)
    db = tenant_session()
    try:
        rows = (db.query(SlackIdeaCapture)
                .filter(SlackIdeaCapture.status.in_(("pending", "failed", "delivering")))
                .filter((SlackIdeaCapture.next_attempt_at.is_(None)) | (SlackIdeaCapture.next_attempt_at <= now))
                .filter((SlackIdeaCapture.locked_until.is_(None)) | (SlackIdeaCapture.locked_until <= now))
                .order_by(SlackIdeaCapture.created_at, SlackIdeaCapture.id)
                .with_for_update(skip_locked=True).limit(limit).all())
        for row in rows:
            row.status = "delivering"
            row.locked_until = now + timedelta(seconds=60)
        db.commit()
        delivered = failed = 0
        for row in rows:
            try:
                _deliver(row)
                row.status, row.delivered_at, row.last_error = "delivered", datetime.now(timezone.utc), None
                delivered += 1
            except Exception as exc:  # delivery is retried by the durable worker queue
                row.attempts += 1
                row.status = "failed"
                row.last_error = str(exc)[:500]
                row.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=min(3600, 5 * (2 ** min(row.attempts, 9))))
                failed += 1
            row.locked_until = None
            row.updated_at = datetime.now(timezone.utc)
            db.commit()
        return {"claimed": len(rows), "delivered": delivered, "failed": failed}
    finally:
        db.close()

