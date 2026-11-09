# ADR 021: Advanced recipe capabilities (formulas, lookup tables, callable recipes, code steps, custom connectors)

- Status: **Proposed** (design only). Builds on ADR 008 (engine) and ADR 020 (editor).
- Owner decisions already given: dnd-kit approved; new editor wanted; formula mode, lookup tables, callable recipes, Python/Ruby/JavaScript code steps with packages, custom API connectors and custom API calls are all wanted.

## Why this needs care
ADR 008 chose "no expression language, no code" on purpose: recipes run with the platform's authority (they add people to groups, set attributes, deactivate users) and a self-editable profile value must never become an instruction (the taint rule). Everything below widens that surface. Each feature therefore comes with the guard that keeps ADR 008's guarantees. Code steps are the dangerous one: they are remote code execution by design, so they get their own isolation boundary and are off by default.

## 1. Formula mode (functions on pills)
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
