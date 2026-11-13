"""Tiny API client for scripts/restore-drill.sh. Runs INSIDE a drill backend container: docker exec -i <c> python - <cmd> ...

  bootstrap EMAIL PASSWORD SECRET            create the first administrator (POST /admin/bootstrap)
  seed ADMIN_EMAIL ADMIN_PASSWORD N PASSWORD sign in as the admin; create N users and 3 groups through the admin API
  login EMAIL PASSWORD                       exit 0 only if sign-in succeeds with a session and CSRF token
"""
import sys

import httpx

ORIGIN = "http://localhost:3000"
API = "http://localhost:8000/api/v1"


def client():
    return httpx.Client(base_url=API, headers={"Origin": ORIGIN}, timeout=30)


def sign_in(c, email, password):
    r = c.post("/login", json={"email": email, "password": password})
    if r.status_code != 200 or "csrf_token" not in r.json():
        print(f"sign-in failed for {email}: HTTP {r.status_code} {r.text[:120]}")
        sys.exit(1)
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]


def main(argv):
    cmd, args = argv[0], argv[1:]
    c = client()
    if cmd == "bootstrap":
        email, password, secret = args
        r = c.post("/admin/bootstrap", json={"email": email, "password": password, "first_name": "Drill", "last_name": "Admin", "secret_key": secret})
        print(f"bootstrap: HTTP {r.status_code}")
        sys.exit(0 if r.status_code == 200 else 1)
    if cmd == "seed":
        email, password, n, user_password = args
        sign_in(c, email, password)
        for i in range(int(n)):
            r = c.post("/admin/users", json={"email": f"drill{i}@example.com", "username": f"drill{i}", "first_name": "Drill", "last_name": f"User{i}", "password": user_password})
            if r.status_code not in (200, 201):
                print(f"create user {i}: HTTP {r.status_code} {r.text[:160]}")
                sys.exit(1)
        for g in range(3):
            r = c.post("/admin/groups", json={"name": f"Drill group {g}"})
            if r.status_code not in (200, 201):
                print(f"create group {g}: HTTP {r.status_code} {r.text[:160]}")
                sys.exit(1)
        print(f"seeded {n} users and 3 groups")
        return
    if cmd == "login":
        sign_in(c, *args)
        print(f"signed in as {args[0]}")
        return
    sys.exit(f"unknown command {cmd}")


main(sys.argv[1:])
