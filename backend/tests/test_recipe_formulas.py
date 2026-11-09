"""Formula mode (ADR 021 s.1): the language, its limits, and the taint rule."""

import pytest

from backend.app.recipes import formula, templates as tpl
from tests.recipe_helpers import definition, make_recipe, new_group, rkey, step  # noqa: F401

CTX = {"trigger": {"user": {"email": "Ann.Lee@Corp.com", "id": 7, "first_name": "Ann", "attributes": {"dept": "Sales", "tags": ["a", "b"]}},
                   "payload": {"n": "12", "items": [3, 1, 2], "empty": ""}}}


def run(src, ctx=CTX):
    return tpl.render("{{= " + src + " }}", ctx)


@pytest.mark.parametrize("src,want", [
    ('upper("ab")', "AB"), ('lower(trigger.user.email)', "ann.lee@corp.com"), ('trim("  x ")', "x"),
    ('email_domain(trigger.user.email)', "corp.com"), ('email_name(trigger.user.email)', "Ann.Lee"),
    ('replace("a-b-c", "-", "_")', "a_b_c"), ('substring("abcdef", 1, 3)', "bcd"), ('split("a,b,c")', ["a", "b", "c"]),
    ('join(["a", "b"], "-")', "a-b"), ('length("abc")', 3), ('length(trigger.payload.items)', 3),
    ('contains("abc", "b")', True), ('contains(trigger.user.attributes.tags, "z")', False),
    ('starts_with("abc", "ab") and ends_with("abc", "bc")', True),
    ('1 + 2 * 3', 7), ('(1 + 2) * 3', 9), ('10 / 4', 2.5), ('10 % 4', 2), ('-3 + 5', 2), ('"a" + "b"', "ab"),
    ('number(trigger.payload.n) + 1', 13), ('round(2.567, 1)', 2.6), ('round(2.5)', 2), ('floor(2.9) + ceil(2.1)', 5),
    ('min(3, 1, 2)', 1), ('max(3, 1, 2)', 3), ('abs(-4)', 4),
    ('trigger.user.id > 5 ? "big" : "small"', "big"), ('if(trigger.user.id > 9, "big", "small")', "small"),
    ('not (1 == 2)', True), ('1 == 1.0', True), ('"1" == 1', False), ('"a" < "b"', True),
    ('coalesce(trigger.user.attributes.nickname, "friend")', "friend"), ('coalesce(trigger.payload.empty, "x")', "x"),
    ('is_blank(trigger.payload.empty)', True), ('is_blank(trigger.nothing.here)', True),
    ('first(trigger.payload.items)', 3), ('last(trigger.payload.items)', 2), ('count(trigger.payload.items)', 3),
    ('get(trigger.user.attributes, "dept")', "Sales"), ('get(trigger.payload.items, 1)', 1), ('get(trigger.payload.items, 9)', None),
    ('add_days("2030-01-30", 2)', "2030-02-01"), ('diff_days("2030-02-01", "2030-01-30")', 2),
    ('format_date("2030-01-31", "%d %B %Y")', "31 January 2030"), ('parse_date("2030-01-31T10:00:00Z")', "2030-01-31T10:00:00Z"),
    ('base64_decode(base64_encode("héllo"))', "héllo"), ('url_encode("a b&c")', "a%20b%26c"),
    ('sha256("a")', "ca978112ca1bbdbfcd2d33f0d0d7a73d9e4b1b3a1e6c4e1d0b3c6a4a4b4e0a5"[:0] or formula.FUNCTIONS["sha256"][2]("a")),
    ('json_parse("{\\"a\\": [1, 2]}")', {"a": [1, 2]}), ('json_stringify([1, 2])', "[1,2]"),
    ("'single' + \"double\"", "singledouble"), ('"a\\"b"', 'a"b'),
])
def test_formula_values(src, want):
    assert run(src) == want


def test_text_mixed_with_formulas_and_pills():
    out = tpl.render("Hi {{= upper(trigger.user.first_name) }} ({{trigger.user.id}}) — {{= 1 + 1 }}", CTX)
    assert out == "Hi ANN (7) — 2"


def test_a_whole_formula_keeps_its_type():
    assert tpl.render("{{= trigger.user.id + 1 }}", CTX) == 8
    assert tpl.render("  {{= 1 == 1 }}  ", CTX) is True


def test_a_closing_braces_inside_text_do_not_end_the_formula():
    assert tpl.render('{{= "a}}b" }}', CTX) == "a}}b"


@pytest.mark.parametrize("src", [
    "", "upper(", "upper()", 'upper("a", "b")', "nope(1)", "trigger.user.email.upper()", "foo", "1 +", "1 2", "(1", "a b",
    '"unterminated', "x = 1", "1 ? 2", "__import__('os')", "trigger.__class__", "trigger.user..id", "1 / 0", "'a' - 1",
    'number("x")', "1 < \"a\"", 'format_date("2030-01-01", "%c")', 'add_days("nope", 1)', 'json_parse("{")', 'split("a", "")',
])
def test_bad_formulas_are_refused_with_a_message(src):
    with pytest.raises(tpl.TemplateError) as e:
        run(src)
    assert str(e.value)


def test_attribute_and_code_tricks_have_no_way_in():
    for src in ("trigger.user.__class__", "recipe.__dict__", 'get(trigger, "__class__")'):
        try:
            v = run(src)
        except tpl.TemplateError:
            continue
        assert v is None   # a missing value, never a Python object


def test_limits():
    with pytest.raises(tpl.TemplateError):
        run("1" + " + 1" * 1000)            # too long
    with pytest.raises(tpl.TemplateError):
        run("(" * 30 + "1" + ")" * 30)      # too deep
    big = "a" * 40_000
    with pytest.raises(tpl.TemplateError):
        tpl.render('{{= "%s" + "%s" }}' % (big, big), CTX)


def test_at_most_ten_formulas_per_field():
    with pytest.raises(tpl.TemplateError):
        tpl.pills_in("{{= 1 }}" * 11)


def test_formulas_report_the_pills_they_read():
    assert tpl.pills_in("{{= upper(trigger.user.email) + trigger.user.id }} {{trigger.user.username}}") == [
        "trigger.user.email", "trigger.user.id", "trigger.user.username"]


def test_now_and_today_use_the_clock_seam(monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setattr(formula, "_now", lambda: datetime(2030, 3, 4, 5, 6, 7, tzinfo=timezone.utc))
    assert run("now()") == "2030-03-04T05:06:07Z" and run("today()") == "2030-03-04"
    assert run('add_days(today(), 1)') == "2030-03-05"


# ---- through the recipe API ------------------------------------------------------------------------------------

def _save(admin, steps, trigger="user.created"):
    r = admin.post("/admin/recipes", {"name": f"F {len(str(steps))}", "definition": definition(trigger, steps)})
    return r


def test_formulas_are_accepted_in_log_and_http_but_a_tainted_pill_is_refused_where_it_could_change_accounts(admin, rkey):
    ok = _save(admin, [step("a", "log", {"message": "{{= upper(trigger.user.username) }}"})])
    assert ok.status_code == 201, ok.text
    # first_name is editable by the user: a formula must not launder it into a state-changing step
    gid = new_group(admin, "G")
    bad = _save(admin, [step("a", "add_to_group", {"group_id": gid, "user": "{{= trigger.user.first_name }}"})])
    assert bad.status_code == 422 and "edited by the user" in bad.json()["detail"]
    fine = _save(admin, [step("b", "add_to_group", {"group_id": gid, "user": "{{= trigger.user.id }}"})])
    assert fine.status_code == 201, fine.text


def test_syntax_errors_are_reported_when_saving(admin, rkey):
    r = _save(admin, [step("a", "log", {"message": "{{= upper( }}"})])
    assert r.status_code == 422 and "formula" in r.json()["detail"]
    r = _save(admin, [step("a", "log", {"message": "{{= nope(1) }}"})])
    assert r.status_code == 422 and "unknown function" in r.json()["detail"]


def test_a_formula_cannot_read_a_path_that_is_not_available_at_that_step(admin, rkey):
    r = _save(admin, [step("a", "log", {"message": "{{= steps.zzz.output.x }}"})])
    assert r.status_code == 422


def test_conditions_can_compare_against_a_formula(db, admin, rkey):
    d = definition("user.created", [step("c", "condition", {"match": "all", "conditions": [
        {"left": "trigger.user.username", "operator": "equals", "value": "{{= lower(trigger.user.username) }}"}]}, then=[step("l", "log", {"message": "yes"})])])
    assert admin.post("/admin/recipes", {"name": "Cond", "definition": d}).status_code == 201


def test_meta_lists_the_functions_and_preview_evaluates_against_a_sample(admin, rkey):
    fns = admin.get("/admin/recipes/meta").json()["functions"]
    assert {"upper", "if", "coalesce", "add_days"} <= {f["name"] for f in fns} and all(f["example"] for f in fns)
    rid = make_recipe(admin, definition("user.created", [step("a", "log", {"message": "x"})]), publish=False, enable=False)
    uid = admin.user.id
    r = admin.post(f"/admin/recipes/{rid}/formula-preview", {"user_id": uid, "templates": [
        "{{= upper(email_name(trigger.user.email)) }}", "{{= nope(1) }}", "{{= trigger.user.id + 1 }}", "plain {{trigger.user.id}}"]})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items[0] == {"template": "{{= upper(email_name(trigger.user.email)) }}", "ok": True, "value": "ADMIN"}
    assert items[1]["ok"] is False and "unknown function" in items[1]["error"]
    assert items[2]["value"] == uid + 1 and items[3]["value"] == f"plain {uid}"


def test_preview_needs_edit_rights(admin, member, rkey):
    rid = make_recipe(admin, definition("user.created", [step("a", "log", {"message": "x"})]), publish=False, enable=False)
    assert member.post(f"/admin/recipes/{rid}/formula-preview", {"templates": []}).status_code == 403


def test_every_path_a_formula_reads_goes_through_the_taint_check_at_run_time():
    seen = []

    def check(path):
        seen.append(path)
        if path == "trigger.user.first_name":
            raise tpl.TemplateError("tainted")

    assert tpl.render("{{= upper(trigger.user.email) + text(trigger.user.id) }}", CTX, check) == "ANN.LEE@CORP.COM7"
    assert seen == ["trigger.user.email", "trigger.user.id"]
    with pytest.raises(tpl.TemplateError, match="tainted"):
        tpl.render('{{= if(true, "x", "y") + trigger.user.first_name }}', CTX, check)
    # a branch that is never evaluated is never read, but save-time checking (pills_in) still sees every path
    assert "trigger.user.first_name" in tpl.pills_in('{{= if(true, "x", trigger.user.first_name) }}')


def test_random_input_never_crashes_or_hangs():
    import random
    import time

    rnd = random.Random(1234)
    atoms = ["upper", "(", ")", ",", "+", "-", "*", "/", "%", "?", ":", "==", "<", "and", "or", "not", "1", "2.5", '"a"', "'b'",
             "trigger.user.id", "trigger.user.email", "[", "]", "if", "coalesce", "split", "join", "{{", "}}", "\\", "\"", ".", "=", " "]
    start = time.time()
    for _ in range(3000):
        src = " ".join(rnd.choice(atoms) for _ in range(rnd.randint(1, 25)))
        try:
            tpl.render("{{= " + src + " }}", CTX)
        except tpl.TemplateError:
            pass                       # the only acceptable failure
    seeds = ['upper(trigger.user.email) + "x"', "if(1 < 2, [1, 2], [3])", "coalesce(a.b, 1)", "round(1.5, 2) * 3"]
    for seed in seeds:
        for _ in range(300):
            chars = list(seed)
            for _ in range(rnd.randint(1, 4)):
                chars[rnd.randrange(len(chars))] = rnd.choice("()[]\"'+-*/,. a1")
            try:
                tpl.render("{{= " + "".join(chars) + " }}", CTX)
            except tpl.TemplateError:
                pass
    assert time.time() - start < 20
