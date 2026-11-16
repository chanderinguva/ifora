#!/usr/bin/env python3
"""Create (or remove) the synthetic accounts and the OIDC client the k6 scripts use (IFORA-59).

  seed.py up   N   -> creates N users and one public, first-party client; writes the fixture file (mode 0600)
  seed.py down     -> deletes exactly what the fixture lists, then the fixture

Needs an administrator: ADMIN_EMAIL / ADMIN_PASSWORD in the environment (never on the command line). The admin must not
be required to use MFA on the target stack (ADMIN_MFA_REQUIRED=false), which is true of the disposable stack only.
Passwords are random and synthetic; the fixture is gitignored and deleted by `down`.
"""
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

BASE = os.environ.get("BASE_URL", "http://localhost:8310").rstrip("/")
FIXTURE = Path(os.environ.get("FIXTURE", Path(__file__).parent / ".fixture" / "fixture.json"))
REDIRECT_URI = "http://localhost:9/callback"  # loopback http is allowed; k6 never follows it
API = f"{BASE}/api/v1"

jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
csrf = ""


def call(method: str, path: str, body=None, ok=(200, 201, 204)):
    req = urllib.request.Request(API + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-CSRF-Token": csrf})
    try:
        with opener.open(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        if e.code in ok:
            return e.code, None
        raise SystemExit(f"{method} {path} -> {e.code} {e.read().decode()[:200]}")


def sign_in():
    global csrf
    email, password = os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD")
    if not email or not password:
        raise SystemExit("set ADMIN_EMAIL and ADMIN_PASSWORD (an administrator of the disposable stack)")
    _, data = call("POST", "/login", {"email": email, "password": password})
    if not data or "csrf_token" not in data:
        raise SystemExit("administrator sign-in did not finish (is MFA required on this stack?)")
    csrf = data["csrf_token"]


def up(n: int):
    if FIXTURE.exists():
        raise SystemExit(f"{FIXTURE} exists: run `seed.py down` first")
    sign_in()
    run = secrets.token_hex(3)
    _, client = call("POST", "/admin/oidc/clients", {
        "name": f"loadtest-{run}", "client_type": "public", "first_party": True, "redirect_uris": [REDIRECT_URI],
        "allowed_scopes": ["openid", "profile", "email", "offline_access"], "access_token_format": "jwt",
    })
    users = []
    fixture = {"client_pk": client["id"], "client_id": client["client_id"], "redirect_uri": REDIRECT_URI, "users": users}
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    write(fixture)  # written first, so a failure half way still leaves something `down` can clean
    for i in range(n):
        password = secrets.token_urlsafe(18) + "aA1!"
        _, u = call("POST", "/admin/users", {"email": f"loadtest-{run}-{i}@example.com", "first_name": "Load", "last_name": f"Test{i}", "password": password})
        users.append({"id": u["id"], "email": u["email"], "password": password})
        write(fixture)
    print(f"created {n} users and client {client['client_id'][:8]}… -> {FIXTURE}")


def write(data):
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(FIXTURE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)


def down():
    if not FIXTURE.exists():
        print("nothing to clean up")
        return
    data = json.loads(FIXTURE.read_text())
    sign_in()
    for u in data.get("users", []):
        call("DELETE", f"/admin/users/{u['id']}", ok=(200, 204, 404))
    if data.get("client_pk"):
        call("DELETE", f"/admin/oidc/clients/{data['client_pk']}", ok=(200, 204, 404))
    FIXTURE.unlink()
    print(f"removed {len(data.get('users', []))} users and the client")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "up":
        up(int(sys.argv[2]) if len(sys.argv) > 2 else 20)
    elif cmd == "down":
        down()
    else:
        raise SystemExit(__doc__)
