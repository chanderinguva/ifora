"""Users as CSV: export, template, import with a dry run."""

import csv
import io

from backend.app.audit.model import AuditEvent
from backend.app.config import settings
from backend.app.groups.model import Group
from backend.app.users.model import User
from tests.conftest import Api, make_user


def rows_of(text):
    return list(csv.DictReader(io.StringIO(text)))


def imp(a, text, **kw):
    r = a.post("/admin/users/import", {"csv": text, **kw})
    return r


HEAD = "first_name,last_name,username,email,user_type,department,groups\r\n"


def test_template_lists_the_columns_with_samples(admin):
    r = admin.get("/admin/users/import-template.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    rows = rows_of(r.text)
    assert {"username", "email", "first_name", "last_name", "user_type", "groups"} <= set(rows[0]) and len(rows) == 2
    cols = admin.get("/admin/users/import-columns").json()
    assert cols["max_rows"] == 500 and [c["name"] for c in cols["columns"] if c["required"]] == ["first_name", "last_name"]


def test_template_imports_cleanly_as_a_dry_run(admin, db, monkeypatch):
    monkeypatch.setattr(settings, "PRIMARY_EMAIL_DOMAIN", "corp.example.com")
    db.add(Group(name="Team - Platform Engineering"))
    db.add(Group(name="Project - Migration 2027"))
    db.commit()
    r = imp(admin, admin.get("/admin/users/import-template.csv").text).json()
    assert r["dry_run"] is True and r["total"] == 2 and r["invalid"] == 0, r
    assert db.query(User).filter(User.email.like("%lovelace%")).count() == 0       # a dry run writes nothing


def test_export_roundtrip_columns_groups_and_no_secrets(admin, db):
    g = Group(name="Team - Ops")
    db.add(g)
    db.commit()
    u = make_user(db, "ex.one@example.com", first_name="Ex", last_name="One", username="ex.one")
    from sqlalchemy import insert
    from backend.app.groups.model import user_group_association

    db.execute(insert(user_group_association).values(user_id=u.id, group_id=g.id))
    db.commit()
    r = admin.get("/admin/users/export.csv?q=ex.one")
    assert r.status_code == 200
    (row,) = rows_of(r.text)
    assert row["email"] == "ex.one@example.com" and row["groups"] == "Team - Ops" and row["status"] == "active"
    assert "password" not in r.text.lower().split("\r\n")[0] and u.password_hash not in r.text
    assert db.query(AuditEvent).filter(AuditEvent.action == "USERS_EXPORTED").count() == 1


def test_export_neutralises_spreadsheet_formulas_and_import_undoes_it(admin, db):
    make_user(db, "form@example.com", first_name="=HYPERLINK(\"http://evil\")", last_name="Safe", username="form")
    out = admin.get("/admin/users/export.csv?q=form").text
    (row,) = rows_of(out)
    assert row["first_name"].startswith("'=")
    from backend.app.users import csvio

    assert csvio.unsafe(row["first_name"]) == '=HYPERLINK("http://evil")'


def test_import_creates_staged_users_with_attributes_and_groups(admin, db, monkeypatch):
    monkeypatch.setattr(settings, "PRIMARY_EMAIL_DOMAIN", "corp.example.com")
    db.add(Group(name="Team - Data"))
    db.commit()
    text = HEAD + "Ada,Lovelace,,,Employee,Engineering,Team - Data\r\nGrace,Hopper,grace.h,grace@example.com,Intern,Research,\r\n"
    r = imp(admin, text, dry_run=False).json()
    assert r["created"] == 2 and r["outcome"] == "staged", r
    ada = db.query(User).filter(User.email == "ada.lovelace@corp.example.com").one()
    assert ada.username == "ada.lovelace" and ada.status == "staged" and ada.get_profile_attributes()["department"] == "Engineering"
    assert [g.name for g in ada.groups] == ["Team - Data"]
    grace = db.query(User).filter(User.username == "grace.h").one()
    assert grace.get_profile_attributes()["user_type"] == "Intern" and grace.is_admin is False
    assert Api().login("ada.lovelace@corp.example.com", "anything").status_code in (401, 403)     # no usable password
    assert db.query(AuditEvent).filter(AuditEvent.action == "USERS_IMPORTED").count() == 1


def test_a_bad_row_does_not_stop_the_good_ones_and_is_reported_by_line(admin, db, monkeypatch):
    monkeypatch.setattr(settings, "PRIMARY_EMAIL_DOMAIN", "corp.example.com")
    make_user(db, "taken@example.com", username="taken")
    text = (HEAD + "Good,One,,,Employee,,\r\n" + "Bad,Type,,,Wizard,,\r\n" + "Dup,Email,,taken@example.com,Employee,,\r\n"
            + "No,Group,,,Employee,,Nope\r\n" + "Dup,Name,taken,,Employee,,\r\n" + ",Missing,,,Employee,,\r\n")
    r = imp(admin, text, dry_run=False).json()
    assert r["created"] == 1 and r["invalid"] == 5
    by = {x["line"]: x for x in r["results"]}
    assert by[2]["created"] is True and by[2]["username"] == "good.one"
    assert by[3]["errors"] == ["User type must be one of: Employee, Contingent Worker, Intern, Service Account, Test Account, Shared Account, Agent Account"]
    assert "already in use" in by[4]["errors"][0] and "no group named" in by[5]["errors"][0] and "already in use" in by[6]["errors"][0] and by[7]["errors"]


def test_repeats_inside_a_file_and_re_importing_the_same_file_are_refused(admin, monkeypatch):
    monkeypatch.setattr(settings, "PRIMARY_EMAIL_DOMAIN", "corp.example.com")
    text = HEAD + "A,B,a.b,,Employee,,\r\nC,D,a.b,,Employee,,\r\n"
    r = imp(admin, text, dry_run=False).json()
    assert r["created"] == 1 and "repeated in this file" in r["results"][1]["errors"][0]
    again = imp(admin, text, dry_run=False)
    assert again.status_code == 409 and "already imported" in again.json()["detail"]
    assert imp(admin, text, dry_run=True).status_code == 200      # a dry run is always allowed


def test_header_problems_are_rejected_up_front(admin):
    assert imp(admin, "first_name,last_name,password\r\nA,B,x\r\n").status_code == 422
    assert imp(admin, "first_name,last_name,is_admin\r\nA,B,true\r\n").status_code == 422
    assert "Unknown column" in imp(admin, "first_name,last_name,salary\r\nA,B,1\r\n").json()["detail"]
    assert imp(admin, "first_name\r\nA\r\n").status_code == 422
    assert imp(admin, "first_name,last_name\r\n").status_code == 422
    assert imp(admin, "").status_code == 422
    assert imp(admin, "first_name,first_name,last_name\r\nA,B,C\r\n").status_code == 422


def test_row_limit_and_bom_and_read_only_columns(admin, monkeypatch):
    monkeypatch.setattr(settings, "PRIMARY_EMAIL_DOMAIN", "corp.example.com")
    big = "first_name,last_name\r\n" + "A,B\r\n" * 501
    assert imp(admin, big).status_code == 422
    ok = "﻿First Name,Last Name,Status,ID\r\nAnn,Bee,active,12\r\n"       # Excel BOM, spaced headers, exported read-only columns
    r = imp(admin, ok).json()
    assert r["valid"] == 1


def test_permissions(db, member):
    assert member.get("/admin/users/export.csv").status_code == 403
    assert member.post("/admin/users/import", {"csv": HEAD}).status_code == 403
    desk = make_user(db, "hd@example.com", admin=True, roles=["help_desk_admin"])
    a = Api()
    a.login(desk.email)
    assert a.get("/admin/users/export.csv").status_code == 200                # users READ
    assert a.get("/admin/users/import-template.csv").status_code == 200
    assert a.post("/admin/users/import", {"csv": HEAD + "A,B,,,,,\r\n", "dry_run": True}).status_code == 403   # cannot create users
    app = make_user(db, "app@example.com", admin=True, roles=["app_admin"])
    b = Api()
    b.login(app.email)
    assert b.get("/admin/users/export.csv").status_code == 200 and b.post("/admin/users/import", {"csv": HEAD}).status_code == 403
