# ADR 021: Advanced recipe capabilities (formulas, lookup tables, callable recipes, code steps, custom connectors)

- Status: **Proposed** (design only). Builds on ADR 008 (engine) and ADR 020 (editor).
- Owner decisions already given: dnd-kit approved; new editor wanted; formula mode, lookup tables, callable recipes, Python/Ruby/JavaScript code steps with packages, custom API connectors and custom API calls are all wanted.

## Why this needs care
ADR 008 chose "no expression language, no code" on purpose: recipes run with the platform's authority (they add people to groups, set attributes, deactivate users) and a self-editable profile value must never become an instruction (the taint rule). Everything below widens that surface. Each feature therefore comes with the guard that keeps ADR 008's guarantees. Code steps are the dangerous one: they are remote code execution by design, so they get their own isolation boundary and are off by default.

## 1. Formula mode (functions on pills) — IMPLEMENTED
- A field can switch from "text with pills" to **formula**: `{{ upper(trigger.user.last_name) }}`, `{{ trigger.user.email | domain }}`-style helpers are *not* used; one syntax only: function calls over pills and literals.
- Implemented as a **small, closed expression language we parse ourselves** (no `eval`, no Python `ast.literal_eval` tricks): literals, pill paths, `+ - * / %`, comparison, `and/or/not`, `? :`, and a fixed library: text (`upper lower trim split join replace substring contains starts_with ends_with length`), numbers (`round abs min max`), dates (`now today add_days format_date parse_date diff_days`), lists (`first last count contains map_get join`), logic (`if coalesce is_blank`), encoding (`base64 url_encode sha256 hmac_sha256` where the secret is a connection field, never a literal), `json_parse/json_stringify`.
- Pure functions, no I/O, hard limits (expression length 2000, depth 20, 10 000 evaluation steps, output 64 KB).
- **Taint**: the result of a formula is tainted if any pill it reads is tainted. The save-time and run-time checks from ADR 008 already ask "does this field read a tainted pill"; the formula parser reports the pills it reads, so the same check applies unchanged.
- The editor offers autocomplete and a live preview against the test sample.

## 2. Lookup tables
- Tenant-scoped tables (`lookup_tables`, `lookup_rows`): name, typed columns (text, number, boolean, date), up to 20 columns and 50 000 rows, unique key column optional.
- Managed in a new Admin page (grid editor, CSV import/export, audit on every change) and by role: a new area `automation` already exists in the admin-role map, so `app_admin`-style scoping needs no new role.
- Steps: **Lookup row** (by column value, returns the row or "not found" as a branchable output), **Add/Update/Delete row**; formula functions `lookup(table, column, value, return_column)`.
- Values written to tables from tainted data are allowed but stay tainted when read back (rows carry no taint flag in v1, so *reads from a table are treated as tainted unless the table is marked "admin-managed"*; only admins with the automation area can mark that and then only admins can write it).

## 3. Callable recipes
- A recipe can be marked **callable** with a declared input schema and output schema (names and types). A **Call recipe** step passes inputs and receives outputs as pills.
- Runs as a **child job** with the caller's job id, depth and idempotency key (`call:<parent job>:<step>`). Limits: depth 5, no recursion (a recipe cannot appear twice in the call chain), shared 500-step budget with the parent, child failure surfaces as the parent step's failure (so the parent's error handling applies).
- Uses the callee's **published** version only; changing a callee shows which recipes call it before publish.
- Permissions: the caller needs read access to the callee (ADR 008 access rules); the child runs with the **callee's** connection grants, not the caller's, so calling is never a way to borrow someone else's connection.

## 4. Code steps (Python, JavaScript, Ruby)
This is arbitrary code execution; the design assumes the code is hostile.

**Who**: only **super administrators** can create or edit a code step; org admins can run recipes that contain them but not change the code. Every save is audited with a hash of the code. Feature flag `RECIPE_CODE_STEPS_ENABLED` defaults to **false**.

**Where it runs**: never inside the API or the recipe worker process. A separate **`code-runner` service** (its own container, no database credentials, no access to the app's secrets, no Docker socket in any app container) that executes each run in a fresh, throwaway sandbox:
- Preferred: `nsjail`/`bubblewrap` inside a locked-down container (read-only root, tmpfs workdir, seccomp allow-list, no capabilities, new PID/net/mount/user namespaces, cgroups limits: 256 MB memory, 1 CPU, 30 s wall time, 1 MB output, no more than 64 processes).
- Stronger on a host that supports it: gVisor (`runsc`) or Firecracker microVMs. The runner interface hides which one is used.
- Network: **none by default**. An optional per-step egress allow-list (hostnames) goes through a proxy that applies the same SSRF rules as `http_request` (ADR 008 R-http). Without it a code step can compute but cannot call out, which also stops data exfiltration.

**Packages ("import anything")**: installing packages at run time from the internet is a supply-chain hole, so packages come from an **approved package list** managed by super admins. Each approved package (name and pinned version, with hashes) is installed into the language image by an image build the admin triggers (or from an internal mirror); a code step may import only what is in the image. Anything else fails with "package not approved". This gives "import packages" without letting a recipe pull arbitrary code. Adding a package is an audited admin action; the build is a separate pipeline, not something the API does live.

**Contract**: the step declares named inputs (pills or formulas, resolved before the call) and the code receives them as one JSON object and returns one JSON object. No access to the job, the database, connections, other steps or environment variables. Secrets from a connection can be passed as an explicit input only by a super admin, and are redacted from history and logs (existing `redact.py`).
- Python: `def main(inputs): ... return {...}`; JavaScript (Node LTS): `export default function main(inputs)`; Ruby: `def main(inputs)`.
- Output is data only (JSON), validated against the declared output schema, size-capped, then treated like any step output.

**Taint**: if any input is tainted the output is tainted (same rule as formulas). Code authored by an admin is trusted, its inputs are not.

**Abuse limits**: per-tenant concurrency 3, per-recipe rate, kill switch (`RECIPE_CODE_STEPS_ENABLED`), per-run audit row (hash of code, duration, exit status, no inputs/outputs unless "save data" is on, as for other steps).

**Honest limits of this design**: a sandbox reduces risk, it does not remove it. Kernel escapes exist; for hosts that run other workloads, use gVisor/Firecracker or run the code-runner on its own VM. We do not claim multi-tenant-safe isolation for hostile tenants until that is chosen and tested; today IdentityForge is single-organisation, so the trust model is "a super admin we trust writes code that may be buggy".

## 5. Custom API connectors and custom API calls
- **Custom API call** step: already partly there (`http_request`). Extend with auth types (none, basic, bearer, API key header/query, OAuth2 client-credentials with token caching, HMAC signing), pagination helpers (offset, cursor, link header), retries from the step settings, response parsing (JSON/XML/text), and a "Test request" button with the sample data.
- **Custom connector** = a saved, reusable definition: base URL, auth type and credential fields (stored encrypted like connections), plus named **actions** (method, path template, params, body template, output sample) and optional **triggers** (polling endpoint with a dedup key, or webhook). Defined from a form, or imported from an **OpenAPI 3** document (we read operations and offer to create actions; nothing is fetched except what the admin uploads or points us to, through the SSRF-safe client).
- Connector actions appear in the **+** picker under their connector name, with typed fields and pills like built-in steps.
- No code in connectors: transformation uses formulas (section 1), or a code step when needed.
- Egress rules, SSRF protection, 1 MB response cap, redaction and audit as for `http_request`.

## 6. Other Workato-style capabilities worth listing
Include in the roadmap, not in this ADR's first cut: recipe **folders/tags/search**, step **notes**, **job retention settings**, **recipe-level alerts** ("job failed" trigger recipes exist already), **environments/promotion** (export/import already covers manual promotion), **API platform** (expose a callable recipe as an authenticated HTTP endpoint), **batch/bulk triggers** (process a list of users in one job), **wait/delay** and **wait for event** steps, **rate-limit/throttle** step, **variables** (set/update/get within a job), **parse/generate CSV/JSON/XML** helpers (as formulas), **file storage** steps. Each is small and can ship once the editor and formula layer exist.

## Order of work (each a PR; editor phases from ADR 020 come first)
1. Editor phases 1-4 (ADR 020).
2. Formula mode (parser, library, tests incl. a fuzz test for the parser and the taint rule).
3. **Done**: variables, wait/delay and throttle (see "Implemented: variables, wait, throttle"). Still open: wait-for-event.
4. **Done** (formula function deferred): lookup tables (models, admin page, steps). See "Implemented: lookup tables".
4a. **Done**: list functions and repeat for each item (see "Implemented: list functions and For each item in a list").
4b. **Done**: callable recipes (see "Implemented: callable recipes").
5. Callable recipes (child jobs, schema, depth/recursion guards).
6. Custom API call upgrades, then custom connectors (+ OpenAPI import).
7. Code-runner service and code steps, off by default, with a documented threat model and a hardening checklist; each language image added separately (Python first).

## Decisions needed from the owner
1. **Sandbox**: nsjail-in-container first (works on any Docker host, weaker) or require gVisor/Firecracker before code steps ship (stronger, host-specific)? Recommendation: build the runner interface, ship nsjail behind the flag, add gVisor as an option.
2. **Packages**: approved-list built into images (recommended) versus live `pip install` at run time (not recommended: supply-chain and exfiltration risk, and needs network).
3. **Who can write code**: super admins only (recommended) or also an `automation` role?
4. **Network from code steps**: none by default with per-step host allow-list (recommended)?
5. **Is IdentityForge single-organisation for the foreseeable future?** If hostile tenants are possible, code steps need microVM isolation before launch.


---

# Implemented: formula mode (reference)

**Syntax.** A formula is written `{{= expression }}` inside any field that accepts datapills (plain `{{path}}` pills keep working and can be mixed with text and formulas in one field: `Hi {{= upper(trigger.user.first_name) }}`). A field that is exactly one formula keeps the value's type (a number stays a number). At most 10 formulas per field.

**Language.** Numbers, `'text'` or `"text"` (escapes `\\ \' \" \n \t`), `true false null`, lists `[1, 2]`, datapill paths, function calls, `+ - * / %` (`+` also joins two texts), `== != < <= > >=`, `and or not`, `cond ? a : b`, parentheses. Missing datapills read as nothing inside a formula (use `coalesce` / `is_blank`); the save-time check still rejects paths that are not available at that step. Dates are ISO text (`2030-01-31` or `2030-01-31T12:00:00Z`, UTC).

**Safety (code: `backend/app/recipes/formula.py`, `templates.py`).**
- We tokenise, parse and evaluate ourselves: no `eval`, no attribute access, names are limited to datapill roots and the function table below; every function is a pure computation (no I/O, no regular expressions, so no ReDoS).
- Limits: 2000 characters, nesting 20, 10 000 evaluation steps, 64 KB text, 5 000 list items, 10 formulas per field.
- **Taint.** The evaluator can only read data through the caller's `read` callback, which runs the same path check and taint check as a plain pill. At save time `pills_in()` reports every path a formula reads, so a formula that reads a user-editable value (first/last name, self-editable attributes, `error.*`) is refused in the same places a plain pill is (state-changing steps, decisions), however it is wrapped.
- A parser fuzz test (random token soups and mutations of valid formulas) must only ever produce a normal error.

**Editor.** Typing `{{=` opens suggestions for functions and datapills (arrows, Enter/Tab, Escape); the step panel lists every function with its example; a formula shows as an `ƒ` chip under the field (red when it reads a path that is not available); **Preview with the sample** evaluates the step's formulas against the sample user chosen under Test (`POST /admin/recipes/{id}/formula-preview`; earlier steps' outputs are not available there, run a test for those).

**Not included yet** (from the original list): `hmac_sha256` (needs a connection-held secret, see section 5), maps over lists, user-defined functions.

**Functions**

| Signature | What it does | Example |
|---|---|---|
| `upper(text)` | Upper case | `upper("Ann") → "ANN"` |
| `lower(text)` | Lower case | `lower("Ann") → "ann"` |
| `trim(text)` | Remove spaces at both ends | `trim("  a ") → "a"` |
| `length(text or list)` | Number of characters or items | `length("abc") → 3` |
| `contains(text or list, value)` | True if the text or list holds the value | `contains("a@b.com", "@") → true` |
| `starts_with(text, prefix)` | True if the text starts with the prefix | `starts_with("abc", "a") → true` |
| `ends_with(text, suffix)` | True if the text ends with the suffix | `ends_with("abc", "c") → true` |
| `replace(text, find, with)` | Replace every occurrence (plain text, not a pattern) | `replace("a-b", "-", "_") → "a_b"` |
| `substring(text, start, length?)` | Part of a text (start at 0) | `substring("abcdef", 1, 3) → "bcd"` |
| `split(text, separator?)` | Split a text into a list (default separator is a comma) | `split("a,b") → ["a","b"]` |
| `join(list, separator?)` | Join a list into one text | `join(["a","b"], "-") → "a-b"` |
| `text(value)` | Turn any value into text | `text(42) → "42"` |
| `email_domain(email)` | The part after the @, lower case | `email_domain("a@Corp.com") → "corp.com"` |
| `email_name(email)` | The part before the @ | `email_name("ann@corp.com") → "ann"` |
| `number(value)` | Turn text into a number | `number("42") → 42` |
| `round(number, digits?)` | Round to a number of decimals (default 0) | `round(2.567, 1) → 2.6` |
| `floor(number)` | Round down | `floor(2.9) → 2` |
| `ceil(number)` | Round up | `ceil(2.1) → 3` |
| `abs(number)` | Absolute value | `abs(-3) → 3` |
| `min(a, b, ...)` | Smallest number | `min(3, 1) → 1` |
| `max(a, b, ...)` | Largest number | `max(3, 1) → 3` |
| `now()` | The current date and time (UTC) | `now()` |
| `today()` | Today's date (UTC) | `today()` |
| `add_days(date, days)` | Add (or subtract) days | `add_days("2030-01-30", 2) → "2030-02-01"` |
| `diff_days(later, earlier)` | Whole days between two dates | `diff_days("2030-02-01", "2030-01-30") → 2` |
| `format_date(date, format)` | Format a date (%Y %m %d %H %M %S %B %b %A %a %e %j %y %Z) | `format_date("2030-01-31", "%d %B %Y") → "31 January 2030"` |
| `parse_date(text)` | Check and normalise a date | `parse_date("2030-01-31") → "2030-01-31"` |
| `first(list)` | First item | `first(["a","b"]) → "a"` |
| `last(list)` | Last item | `last(["a","b"]) → "b"` |
| `count(list)` | Number of items | `count(["a","b"]) → 2` |
| `get(object or list, key or position)` | Read one entry; nothing when it is missing | `get(trigger.payload, "id")` |
| `if(condition, then, otherwise)` | Pick a value (only the chosen one is evaluated) | `if(length(a) > 3, "long", "short")` |
| `coalesce(a, b, ...)` | The first value that is not empty | `coalesce(trigger.user.attributes.nickname, "friend")` |
| `is_blank(value)` | True when the value is missing or empty | `is_blank("") → true` |
| `base64_encode(text)` | Base64 text | `base64_encode("a") → "YQ=="` |
| `base64_decode(text)` | Decode base64 text | `base64_decode("YQ==") → "a"` |
| `url_encode(text)` | Make a text safe for a URL | `url_encode("a b") → "a%20b"` |
| `sha256(text)` | SHA-256 hash as hex | `sha256("a")` |
| `json_parse(text)` | Read JSON text into a value | `json_parse("{\"a\":1}")` |
| `json_stringify(value)` | Write a value as JSON text | `json_stringify([1,2]) → "[1,2]"` |


---

# Implemented: variables, wait, throttle

**Set a variable** (`set_variable`, name `a-z0-9_`, 32 characters at most, value is a template: text, datapills, `{{= formula }}`). Read it with `{{vars.name}}` (or `vars.name` in a formula or condition). A value that is exactly one pill or formula keeps its type. At most 20 variables per recipe, 64 KB in total per job. Setting a name again replaces it. A variable must be set by an earlier step (checked on save, in the editor's pill list and when a step is dragged); the error steps do not see the main flow's variables. **Taint rule:** the value is checked like the input of a state-changing step, so a variable can never carry text the user can edit themselves (first name, last name, self-editable attributes) into a later step or decision. Everything else (email, status, managed attributes, step outputs) is allowed. A variable set only in a branch that did not run is missing later: a plain `{{vars.x}}` then fails the step, a formula sees nothing (`coalesce`).

**Wait** (`wait`, 1 minute to 7 days): the job goes to `waiting` and the worker resumes it when due (same mechanism as approvals, no thread held). The pause is not counted against `RECIPES_MAX_RUNTIME_SECONDS`. A test run never waits. Waiting jobs can be cancelled. Not allowed in the error steps.

**Throttle** (`throttle`, `max_runs` per `per_minutes`, 1 to 1440): counts how many jobs of the recipe passed this step in the window (the history rows of live jobs, so it follows `RECIPES_JOB_RETENTION_DAYS`: keep retention at 1 day or more). One job decides at a time (a Postgres advisory lock held until the step commits), so two jobs cannot take the last slot. When full, `wait` pauses the job until the oldest pass leaves the window (re-checked then; one history row, not one per re-check), `stop` cancels the job with the reason "dropped by the throttle step" (a dropped job is not counted as a pass). Test runs are never limited. Not allowed in the error steps.

Not included: wait for an event or a date, throttling across recipes, per-user throttles, list/map variables with in-place updates (set a new value instead).


---

# Implemented: lookup tables

**Tables** (`lookup_tables`, `lookup_rows`, migration 0048): name (`a-z0-9_`, 40 characters, never renamed), up to 20 typed columns (text, number, yes/no, date), an optional **key column** (values unique, recipes can update or delete by it), up to 50 000 rows (a row at most 4 KB, a text cell 500 characters) and 50 tables per tenant. Managed under **Recipes › Lookup tables** (grid editor, search, CSV import and export) and `/admin/lookup-tables`, area `automation` (so the existing role map applies: read-only roles can read, only write roles change anything). Columns can be added later, not removed or retyped. A table that a recipe (draft or published version) uses cannot be deleted. Every change is audited (`LOOKUP_TABLE_*`, `LOOKUP_ROWS_CHANGED` with the key, never the values; recipe writes as `RECIPE_LOOKUP_WRITE`). CSV import is all or nothing (first five problems listed with line numbers, 5 000 rows per import, append or replace); export neutralises spreadsheet formulas.

**Steps.** *Look up a row* (`lookup_row`): table, column, value. Outputs `found`, `count` and the first matching row (`row.<column>`, empty columns read as nothing). Exact, case-sensitive match on the typed value (so `5.0` finds `5`). *Add, update or delete a lookup row* (`lookup_write`): `add`, `upsert` (by key) or `delete` (by key); values are templates converted to the column types; a bad value fails the step. A test run reads for real and writes nothing.

**Trust (the part that matters).** A table is either
- **administrator-managed** (default): only administrators write it (recipes cannot, refused on save and at run time), so what a recipe reads from it is as trustworthy as the table and can drive decisions and account changes; or
- **recipe-writable**: recipes may write any text into it, including text users typed themselves, so everything read from it is treated like user-editable text: it is refused in conditions, in state-changing steps and in variables (same rule and same error as a user's first name), and allowed in log, http and email steps.

The *key* of a lookup must never be user-editable text, because it picks which admin-written row comes back (a user who could choose the key could choose the group, for example). The rule is applied on save by following which steps read recipe-writable tables, and again at run time from the table's current setting: if an administrator later switches a table from administrator-managed to recipe-writable, published recipes that used it in a decision or account change fail their step instead of acting on data that is no longer trusted (the switch lists the recipes affected and is audited).

**Not included:** a `lookup(...)` formula function (formulas are deliberately free of I/O; use the step and a variable), per-table permissions, row-level history, bulk updates from a recipe, column removal or retyping.

# Implemented: list functions and "For each item in a list"
**Formulas** gained `sum`, `index`, `reverse`, `uniq`, `flatten`, `compact`, `concat`, `pluck`, `smart_join`, and `min`/`max` now take either several values or one list (an empty list gives nothing). They are pure functions on data already in the job; nothing new is reachable.

**Step `for_each_item`** repeats the steps inside it once per item of a list given by one datapill or formula (`list`, plus `limit` 1 to 100, default 50). Inside, `loop.item` (and `loop.item.<field>` for objects), `loop.index` (from 1) and `loop.total` are available; `loop.user.*` stays specific to the group-member loop and `loop.item` to this one. Rules:
- Same placement as the member loop: top level of the main steps only, never nested, never in the error steps.
- The value must be a list; more items than `limit` **fails the step** rather than silently skipping the rest; the list is stored in the job (at most 64 KB of plain data) so a resumed job iterates the same items.
- **Taint**: the list expression is checked like a variable or a lookup key, so a list built from user-editable text (first or last name, self-editable attributes, error text, recipe-writable lookup reads) is refused on save and at run time. Items from a trusted list then need no extra marking.
- Empty list: the body is skipped and the flow continues after the loop.

**Not included:** `while` loops, batches of items, per-iteration error handling, loops over more than 100 items, nested loops.

# Implemented: callable recipes
**Callee.** A recipe whose trigger is **Called by another recipe** (`call`) declares `inputs` (name, type text/number/boolean/list/object, required) and `outputs` (names). Inputs arrive as `trigger.payload.<name>`. The new step **Return data to the caller** (`return_data`, only in such recipes, never in the error steps) must give exactly the declared outputs and ends the job. A callee can be tested on its own with a sample payload.

**Caller.** The step **Call a recipe** (`call_recipe`) names a published, enabled, callable recipe and maps its inputs (pill, formula or text; text typed into a number or yes/no input is converted). The result is available as `steps.<id>.output.result.<output>`.

**How it runs.** The call creates a **child job** (migration 0049: `parent_job_id`, `call_chain`) from the callee's *published* version, with idempotency key `call:<parent job>:<step>:<seq>`, and parks the parent in `waiting` with the child's id (the same mechanism as Wait, so the wait does not count against the parent's run-time limit). A child that finishes wakes its parent at once; a 30-second poll is the fallback. A failed or cancelled child fails the call step with the child's error, so the parent's error steps apply. If a job fails, is cancelled or is dropped, its unfinished children are cancelled. A **test run** runs the callee's published version too, as a dry-run child in its own session, without side effects and without waiting.

**Guards.** Depth 5; a recipe cannot appear twice in a call chain (checked when the call runs; saving only checks that the callee exists, is callable and gets the right inputs); the caller's inputs and the callee's returned values are **taint-checked** like variables, so user-editable text cannot cross a call boundary; inputs are limited to 16 KB and returned data to 64 KB; types are checked at run time. The child runs under its own recipe, so it uses **its own** connections and recipe settings, never the caller's. `GET /admin/recipes/{id}/callers` lists the recipes (draft or published) that call a recipe, and `/meta` lists `callable_recipes`.

**Differences from the first design.** The 500-step budget is per job, not shared with the parent (depth 5 bounds the total at 5 x 500). Access rules between recipes are not enforced beyond "admin who can edit the caller": there is no per-recipe read permission to check yet. The editor shows callers only through the API for now.

**Not included:** asynchronous (fire-and-forget) calls, a "wait for async result" step, recursion, calling from the error steps, callable recipes with per-call connections, a callers panel in the editor.

## Implemented: scoped "Handle errors" block (WP-014)
A `handle_errors` step wraps part of the flow: `then` holds the **monitored steps**, `else` the **on-error steps**.
- **Engine.** `compile_program` emits `head, body…, jump→end, catch…`; the head carries `catch_to`. When a step fails for good (retries used up, per-step "continue" not chosen), the engine finds the innermost block whose monitored range contains the failing step (`_enclosing_block`), stores `_error {message, step_id}`, drops state of loops opened inside the block, and jumps to `catch_to`. After the on-error steps the job carries on after the block and is **not** failed. A failure in the on-error steps is outside the block's range, so it reaches the next outer block, then the recipe-level handler. Errors outside any block behave as before (recipe-level handler, job ends failed). A deliberate Stop step is not an error.
- **Rules.** `error.message` / `error.step_id` only in on-error steps (still untrusted text: the ADR 008 taint rule applies). On-error steps follow the recipe-level handler restrictions (no approvals, loops, waits, throttles, calls). Outputs and variables of the monitored steps are not visible after the block or in the on-error steps (they may not have run); what ran before the block stays visible. Blocks nest within the existing nesting limit; publishing needs at least one monitored step.
- **UI.** Studio only (add menu "Handle errors"; the classic editor does not offer it). Flow diagram shows "Monitored" / "On error".
- Tests: `backend/tests/test_recipe_scoped_errors.py` (7), `frontend/e2e/recipe-studio-scoped-errors.spec.ts`.
