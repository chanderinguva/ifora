"""Support for the studio editor: step notes and restoring a published version into the draft."""

from tests.recipe_helpers import definition, make_recipe, rkey, step  # noqa: F401


def test_step_notes_are_kept_trimmed_and_limited(admin, rkey):
    d = definition("manual", [step("a", "log", {"message": "hi"}, note="  why we do this  ")])
    rid = make_recipe(admin, d, publish=False, enable=False)
    got = admin.get(f"/admin/recipes/{rid}").json()["draft"]["steps"][0]
    assert got["note"] == "why we do this"
    d["steps"][0]["note"] = "x" * 301
    assert admin.put(f"/admin/recipes/{rid}", {"name": "Recipe 1", "definition": d}).status_code == 422
    d["steps"][0]["note"] = "   "
    assert admin.put(f"/admin/recipes/{rid}", {"name": "Recipe 1", "definition": d}).status_code == 200
    assert "note" not in admin.get(f"/admin/recipes/{rid}").json()["draft"]["steps"][0]


def test_notes_do_not_change_what_runs(admin, rkey):
    d = definition("manual", [step("a", "log", {"message": "hi"}, note="{{trigger.user.email}} is not resolved")])
    rid = make_recipe(admin, d, publish=True, enable=False)
    assert admin.get(f"/admin/recipes/{rid}/versions/1").json()["definition"]["steps"][0]["note"].startswith("{{")


def test_restore_copies_a_version_into_the_draft_only(admin, rkey):
    rid = make_recipe(admin, definition("manual", [step("a", "log", {"message": "first"})]), enable=False)
    d2 = definition("manual", [step("a", "log", {"message": "second"})])
    assert admin.put(f"/admin/recipes/{rid}", {"name": "Recipe 1", "definition": d2}).status_code == 200
    assert admin.post(f"/admin/recipes/{rid}/publish").status_code == 200       # v2
    r = admin.post(f"/admin/recipes/{rid}/versions/1/restore")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["draft"]["steps"][0]["config"]["message"] == "first"
    assert body["published_version"] == 2                                         # nothing was published
    assert admin.get(f"/admin/recipes/{rid}/versions/2").json()["definition"]["steps"][0]["config"]["message"] == "second"
    ev = admin.get("/admin/audit?action=RECIPE_UPDATED").json()["items"]
    assert any((e.get("metadata") or {}).get("restored_version") == 1 for e in ev)


def test_restore_needs_edit_rights_and_a_real_version(admin, member, rkey):
    rid = make_recipe(admin, definition("manual", [step("a", "log", {"message": "x"})]), enable=False)
    assert admin.post(f"/admin/recipes/{rid}/versions/9/restore").status_code == 404
    assert member.post(f"/admin/recipes/{rid}/versions/1/restore").status_code == 403
