"""System log: richer filters, the action catalogue, and a CSV export that is safe to open in a spreadsheet."""

import csv
import io
from datetime import datetime, timedelta, timezone

from tests.conftest import make_user


def test_actions_catalogue_lists_every_action(admin):
    items = admin.get("/admin/audit/actions").json()["items"]
    assert "LOGIN_SUCCESS" in items and "USER_STATUS_CHANGED" in items and "AUDIT_EXPORTED" in items


def test_filter_by_target_and_text(db, admin):
    u = make_user(db, "needle.user@example.com")
    admin.post("/admin/users/bulk", {"user_ids": [u.id], "action": "suspend"})
    r = admin.get(f"/admin/audit?target_type=user&target_id={u.id}").json()
    assert r["totalResults"] >= 1 and all(e["target_id"] == str(u.id) for e in r["Resources"])
    by_text = admin.get("/admin/audit?q=suspended").json()
    assert by_text["totalResults"] >= 1
    by_actor = admin.get("/admin/audit?q=admin@example.com").json()
    assert by_actor["totalResults"] >= 1
    assert admin.get("/admin/audit?q=zzzz-no-such-thing").json()["totalResults"] == 0


def test_filter_by_time_window(admin):
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=1)).isoformat()
    past = (now - timedelta(days=1)).isoformat()
    import urllib.parse as up
    assert admin.get("/admin/audit?since=" + up.quote(future)).json()["totalResults"] == 0
    assert admin.get("/admin/audit?since=" + up.quote(past)).json()["totalResults"] >= 1
    assert admin.get("/admin/audit?until=" + up.quote(past)).json()["totalResults"] == 0


def test_filters_reject_bad_input(admin):
    assert admin.get("/admin/audit?target_type=Robert'); DROP TABLE x;--").status_code == 422
    assert admin.get("/admin/audit?since=not-a-date").status_code == 422
    assert admin.get("/admin/audit?action=NOPE").status_code == 422


def test_export_csv_and_it_is_audited(admin):
    r = admin.get("/admin/audit/export?action=LOGIN_SUCCESS")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:3] == ["id", "timestamp", "actor_id"] and len(rows) >= 2
    assert all(row[5] == "LOGIN_SUCCESS" for row in rows[1:])
    logged = admin.get("/admin/audit?action=AUDIT_EXPORTED").json()
    assert logged["totalResults"] == 1 and logged["Resources"][0]["metadata"]["filters"]["action"] == "LOGIN_SUCCESS"


def test_export_neutralises_spreadsheet_formulas():
    from backend.app.audit.routes import _csv_cell

    for evil in ("=1+1", "+1", "-1", "@SUM(A1)", "\tx"):
        assert _csv_cell(evil).startswith("'")
    assert _csv_cell("plain") == "plain" and _csv_cell(None) == ""


def test_audit_endpoints_require_admin(member):
    for path in ("/admin/audit", "/admin/audit/actions", "/admin/audit/export"):
        assert member.get(path).status_code == 403
