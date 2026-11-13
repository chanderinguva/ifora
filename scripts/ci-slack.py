"""Best-effort Block Kit notifications: one parent and one thread per build.

Only bot chat:write is needed. No history scopes, message search, or webhook
callbacks: chat.postMessage returns the parent timestamp directly.
"""
import hashlib
import html
import json
import os
import re
import subprocess
from pathlib import Path
import sys
import tempfile
import time
import urllib.error
import urllib.request

PHASES = {
    "preflight": "🔎 Preflight",
    "prepare-test-images": "🧰 Test dependencies",
    "test-backend": "🧪 Backend tests",
    "check-frontend": "🎨 Frontend checks",
    "build-and-push": "📦 Images",
    "deploy-demo": "🌐 Demo deployment",
    "deploy-local": "🔒 Dev deployment",
}
EVENTS = {
    "start": "🚀 Build started",
    "tests": "✅ Backend and frontend checks passed",
    "images": "📦 Images published",
    "demo": "🌐 Demo deployment passed health checks",
    "success": "🎉 Both deployments passed health checks",
    "failure": "❌ Pipeline failed — inspect the failed step",
}


def slack_api(method, payload, token):
    """Bounded retries; never log token, request bodies, or raw response data."""
    for attempt in range(3):
        request = urllib.request.Request(
            f"https://slack.com/api/{method}",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.load(response)
            if not result.get("ok"):
                raise RuntimeError("Slack rejected request; check bot membership and chat:write scope")
            return result
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < 2:
                try:
                    wait = int(error.headers.get("Retry-After", "1"))
                except ValueError:
                    wait = 1
                if wait > 5:
                    raise RuntimeError("Slack rate limited delivery; retry deferred") from None
                time.sleep(max(1, wait))
                continue
            raise RuntimeError(f"Slack HTTP error {error.code}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise RuntimeError("Slack connection failed") from None
            time.sleep(attempt + 1)
    raise RuntimeError("Slack delivery attempts exhausted")


def read_results(directory):
    results = {}
    for phase in PHASES:
        try:
            value = json.loads((directory / f"{phase}.json").read_text())
            if value.get("status") in {"running", "success", "failure"}:
                results[phase] = value
        except (OSError, ValueError):
            pass
    return results


def duration(seconds):
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f"{minutes}m {seconds:02d}s"


def change_summary(env):
    """Use checked-out commit metadata; no new GitHub token or external lookup."""
    message = env.get("DRONE_COMMIT_MESSAGE", "")[:12000]
    sha = env.get("DRONE_COMMIT_SHA", "")
    only_merge = message and all(not line.strip() or line.startswith(("Merge pull request ", "Merge branch ")) for line in message.splitlines())
    if not env.get("IFORA_BUILD_SUMMARY") and (not message or only_merge) and re.fullmatch(r"[a-fA-F0-9]{7,40}", sha):
        try:
            result = subprocess.run(["git", "log", "-1", "--format=%B", sha], capture_output=True, text=True, timeout=3, check=False)
            if result.returncode == 0:
                message = result.stdout[:12000]
        except (OSError, subprocess.TimeoutExpired):
            pass
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    meaningful = [line for line in lines if not line.startswith("Merge pull request ") and not line.startswith("Merge branch ")]
    title = env.get("DRONE_PULL_REQUEST_TITLE") or (meaningful[0] if meaningful else (lines[0] if lines else ""))
    title = " ".join(title.split())[:280]
    # Optional explicit short release note; otherwise the real PR/commit title is the summary.
    summary = " ".join(env.get("IFORA_BUILD_SUMMARY", "").split())[:500] or title
    number = env.get("DRONE_PULL_REQUEST", "")
    if not re.fullmatch(r"[1-9][0-9]{0,8}", number):
        found = re.search(r"Merge pull request #([1-9][0-9]{0,8})\b|\(#([1-9][0-9]{0,8})\)", message)
        number = next((g for g in found.groups() if g), "") if found else ""
    repo = env.get("DRONE_REPO", "")
    url = f"https://github.com/{repo}/pull/{number}" if number and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) else None
    return {"text": summary, "number": number, "url": url}


def blocks(event, env, results):
    number = env.get("DRONE_BUILD_NUMBER", "?")
    status = "❌ Failed" if event == "failure" else "✅ Succeeded" if event == "success" else "⏳ Running"
    esc = lambda value: html.escape(str(value), quote=False).replace("`", "'")
    fields = [
        {"type": "mrkdwn", "text": f"*Repository*\n{esc(env.get('DRONE_REPO', 'ifora'))}"},
        {"type": "mrkdwn", "text": f"*Branch*\n{esc(env.get('DRONE_COMMIT_BRANCH', 'main'))}"},
        {"type": "mrkdwn", "text": f"*Commit*\n`{esc(env.get('DRONE_COMMIT_SHA', '')[:8])}`"},
        {"type": "mrkdwn", "text": f"*Status*\n{status}"},
    ]
    rows = []
    for phase, label in PHASES.items():
        result = results.get(phase)
        if not result:
            state = "Not run / unreported" if event in {"success", "failure"} else "Pending"
            rows.append(f"▫️ {label} — {state}")
            continue
        icon = {"success": "✅", "failure": "❌", "running": "⏳"}[result["status"]]
        rows.append(f"{icon} {label} — {duration(result.get('seconds', 0))}" if result["status"] != "running" else f"{icon} {label} — Running")
    output = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Ifora · Build #{number} · {status}", "emoji": True}},
        {"type": "section", "fields": fields},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(rows)}},
    ]
    change = change_summary(env)
    if change["text"]:
        output.insert(2, {"type": "section", "text": {"type": "plain_text", "text": "📝 What changed\n" + change["text"], "emoji": True}})
    if change["url"]:
        output.insert(3, {"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{change['url']}|Review PR #{change['number']} ↗>"}]})
    if event == "failure":
        output.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "⚠️ Deployments may be partial. No automatic rollback."}]})
    link = env.get("DRONE_BUILD_LINK", "")
    if link.startswith("https://drone.ifora.app/"):
        output.append({"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "View build ↗"}, "url": link, "action_id": "view_build"}]})
    return output


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as temp:
        json.dump(state, temp)
        temporary = temp.name
    os.replace(temporary, path)


def notify(event, env=None, root=Path(".ci"), api=slack_api):
    env = os.environ if env is None else env
    token, channel = env.get("SLACK_BOT_TOKEN"), env.get("SLACK_CHANNEL_ID")
    if not token or not channel:
        raise RuntimeError("Set Drone slack_bot_token and slack_channel_id secrets")
    # Build timestamps can differ between the start and later step environments.
    # Repository + build number identifies the build across every notification step.
    repository, number = env.get("DRONE_REPO"), env.get("DRONE_BUILD_NUMBER")
    if not repository or not number:
        raise RuntimeError("Drone repository and build number are required for thread identity")
    identity = json.dumps([repository, number], separators=(",", ":"))
    state_file = root / "slack" / (hashlib.sha256(identity.encode()).hexdigest()[:24] + ".json")
    try:
        state = json.loads(state_file.read_text())
    except (OSError, ValueError):
        state = {}
    if state.get("channel") != channel:
        state = {}
    if event in state.get("events", []):
        print("Slack event already recorded")
        return
    env = dict(env)
    change = state.get("change") or change_summary(env)
    if change.get("text"):
        env["IFORA_BUILD_SUMMARY"] = change["text"]
    if change.get("number"):
        env["DRONE_PULL_REQUEST"] = change["number"]
    results = read_results(root / "results")
    summary = change["text"]
    text = f"Ifora build #{env.get('DRONE_BUILD_NUMBER', '?')}: {EVENTS[event]}" + (f" · {summary}" if summary else "")
    payload = {"channel": channel, "text": text, "blocks": blocks(event, env, results), "unfurl_links": False, "unfurl_media": False}
    if not state.get("ts"):
        response = api("chat.postMessage", payload, token)
        state = {"channel": channel, "ts": response["ts"], "events": [], "change": change}
        # Persist immediately so a subsequent update failure does not lose the thread.
        save_state(state_file, state)
    else:
        api("chat.update", {**payload, "ts": state["ts"]}, token)
    if event != "start":
        reply = {"channel": channel, "thread_ts": state["ts"], "text": text,
                 "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": EVENTS[event]}}],
                 "unfurl_links": False, "unfurl_media": False}
        api("chat.postMessage", reply, token)
    state["events"].append(event)
    save_state(state_file, state)
    print(f"Slack event delivered: {event}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in EVENTS:
        raise SystemExit("Usage: ci-slack.py start|tests|images|demo|success|failure")
    try:
        notify(sys.argv[1])
    except Exception:
        # No credentials, payloads or raw Slack errors in CI output.
        print("Slack notification unavailable; check secrets, bot membership and network access", file=sys.stderr)
        sys.exit(1)  # Drone failure: ignore makes this non-blocking.
