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
3. Variables, wait/delay, wait-for-event, throttle (small engine additions).
4. Lookup tables (models, admin page, steps, formula function).
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
