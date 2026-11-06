# ADR 007: SCIM 2.0 server (inbound provisioning)

- Status: **Proposed** (written with the first implementation; the owner should review the decisions marked **REVIEW**)
- Date: 2026-11-06
- Inputs: ADR 005 (tenancy, house style), ADR 006 (group rules), RFC 7642 (concepts), RFC 7643 (schema), RFC 7644 (protocol)

## Context
Customers run Okta, Microsoft Entra ID or another IdP as the source of truth for people and groups. They need to push users and groups into IdentityForge (create, update, deactivate, group membership) without an admin typing them in. This ADR adds a SCIM 2.0 **server**. Outbound provisioning (IdentityForge as SCIM client) is out of scope.

## Research notes and confidence
Sources: RFC 7642/7643/7644 (primary, high confidence), Microsoft's "Known issues and resolutions with SCIM 2.0 protocol compliance of the Microsoft Entra user provisioning service" (primary, but a search-result excerpt, medium), third-party write-ups (WorkOS, SSOJet; low-medium, secondary). No Okta primary documentation was reachable, so Okta claims are low confidence and were not verified against a live Okta tenant. **Nothing here was tested against a real Okta or Entra tenant.**

| Claim | Source | Confidence |
|---|---|---|
| Entra by default sends `active` in PATCH as a string (`"False"`/`"True"`); a feature flag changes this | Microsoft known-issues page | Medium-high |
| Entra sends `op` capitalised (`Replace`, `Add`, `Remove`) by default | Microsoft page, third party | Medium-high |
| Entra and Okta check existence with `GET /Users?filter=userName eq "x"` before creating; empty list means create | third party | Medium |
| Entra uses essentially only `eq` and `and` in filters | third party | Medium |
| Okta deactivates with PATCH, either `path: "active"` or path-less `value: {"active": false}`; some Okta apps use PUT | third party (sources disagree) | Low-medium: accept PATCH (both shapes) and PUT |
| Entra removes group members with `remove` + `path: members[value eq "id"]`, or `remove` + `path: members` + `value: [{value: id}]` | third party, RFC 7644 3.5.2.2 for the first | Medium |
| Entra may send path-less `add`/`replace` whose keys are dotted (`name.givenName`) or full URNs | third party | Low-medium |
| Entra sends `emails[type eq "work"].value`-style filtered paths in PATCH | Microsoft examples, third party | Medium |

Consequence: the server is liberal in what it accepts (case-insensitive `op`, string booleans, both PATCH shapes, URN-prefixed paths) and strict in what it stores (everything is validated against the profile catalog).

## Decisions

### D1. Authentication: admin-issued bearer tokens
- Token format `idf_scim_<43 chars>` (256 bits from `secrets.token_urlsafe`). Shown **once** at creation; only an HMAC-SHA256 (keyed with `SECRET_KEY`) is stored. 256-bit random tokens need no slow hash; the keyed hash also means a database leak alone cannot be used to test guesses. A short non-secret display prefix is stored so admins can tell tokens apart.
- Lookup is by hash (unique index), followed by `hmac.compare_digest` on the stored vs computed digest. The token itself is never compared with `==`.
- Each token belongs to **one tenant** (`tenant_id`). The request's tenant context is taken from the token, never from a header or the body, so a token can only ever see its own tenant (fail closed: a bad token resolves no tenant and gets no session).
- Optional expiry (`expires_at`, at most 3650 days), revocation (`revoked_at`), `last_used_at` (updated at most once a minute to avoid write amplification).
- All failures (missing, malformed, unknown, expired, revoked) return the same `401` with `WWW-Authenticate: Bearer`; the reason is only visible in the audit log (for known tokens) so an attacker learns nothing.
- Rate limits (Redis, fail-open like the rest of the app): failed authentications per client IP (default 20 per 5 min, then 429), and requests per token (default 1200 per minute).
- Creating and revoking tokens: `/api/v1/admin/scim/tokens`, `require_admin`. **REVIEW: creating is super-admin only**, because a SCIM token can create, deactivate and re-attribute every non-admin user in the tenant, which is more power than a normal admin action. Listing is any admin; revoking is any admin (revocation only reduces risk). Every create/revoke/failed-auth for a known token is audited. No PII or token in logs.
- Tokens are scoped to the whole SCIM surface (Users and Groups, read and write). Scoped/read-only tokens are backlog.

### D2. Mount point and errors
- Mounted at `/scim/v2`, **not** under `/api/v1`, as a separate FastAPI sub-application so its error handlers emit SCIM errors (`schemas: [urn:ietf:params:scim:api:messages:2.0:Error]`, `status` as a string, `scimType` where defined, `detail`) and so cookie-session/CSRF machinery never applies. Responses use `application/scim+json`. Requests are accepted with `application/json` or `application/scim+json`.
- Unexpected exceptions return a generic 500 without internals. Validation errors never echo input values.
- Body size capped at 1 MiB (413); list endpoints cap `count` at 200 (default 100); PATCH at most 500 operations; group PATCH/PUT at most 5000 members.

### D3. Resource mapping: User
| SCIM | IdentityForge | Notes |
|---|---|---|
| `id` | `users.public_id` (UUID) | Not the integer key (no enumeration, matches OIDC `sub`) |
| `userName` | `users.username` | Lower-cased, unique per tenant (409 `uniqueness`). Allowed `[a-z0-9._@+-]`, 2-100 chars. Login still uses email |
| `emails[primary or first work]` | `users.email` | Unique per tenant; if absent and `userName` is a valid email it is used; otherwise 400 `invalidValue`. Only one email is stored |
| `name.givenName` / `name.familyName` | `first_name` / `last_name` | Required (not blank) |
| `displayName` | computed | Read-only; accepted and ignored on write |
| `active` | `status` | `true` -> `active`, `false` -> `inactive` (see D6). Strings `"True"/"False"` (any case) are accepted |
| `externalId` | `scim_links.external_id` | Per tenant and per resource type; unique (409 `uniqueness`) |
| `title`, `locale`, `timezone` | profile `title`, `locale`, `timezone` | Core attributes, types validated by the catalog |
| `phoneNumbers[work]` | profile `phone` | |
| enterprise `department`, `costCenter`, `employeeNumber`, `manager.value` | profile `department`, `cost_center`, `employee_id`, `manager` | Admin-managed attributes. `manager.value` is stored as given (the catalog stores a string); it is not resolved to a user |
| custom extension `urn:identityforge:params:scim:schemas:extension:profile:2.0:User` | any other catalog attribute by key | Lets every attribute in the Profile editor be provisioned |
| `groups` | read-only, computed from memberships | Never writable via the user resource |
| `meta` | `resourceType`, `created`, `lastModified`, `location`, `version` | `version` is a weak ETag |

Attribute rules: every profile value goes through the existing catalog (`profile_catalog.validate_values` / `coerce_value`), so data types (string, number, boolean, enum, timezone, locale) and "unknown attribute" are enforced exactly as in the admin UI. SCIM is an **administrator-class channel** (token issued by an admin), so it may write admin-managed attributes as well as user-editable ones; the user-editable flag does not block SCIM, but unknown or mistyped attributes are rejected with 400 `invalidValue`. Unmapped SCIM attributes in a payload are ignored (RFC 7643 allows a service provider to ignore what it does not support) and the response only reflects what is stored.

### D4. Admin privilege protection (**REVIEW**)
How admin is determined (checked in code): `users.is_admin` / `users.is_super_admin` only (`require_admin`). **Groups do not grant anything today**: no code maps group membership to admin rights, and group rules only create memberships. Therefore SCIM cannot escalate privileges through groups in the current model.
- `is_admin` / `is_super_admin` are never read from a SCIM payload (no mass assignment: the parser reads a fixed set of attributes, anything else is dropped). SCIM-created users are always non-admin.
- SCIM **cannot modify, deactivate, re-email or delete admin or super-admin accounts**: writes to such a user return 403. Reason: changing the email or active state of an admin from a lower-trust channel is an account-takeover/denial vector. They remain readable (so the pre-create `userName eq` lookup is consistent).
- Standing constraint for the future: if group membership ever drives roles or permissions, SCIM-managed groups must be excluded from that mapping unless an admin explicitly opts in per group. This is recorded here so the later change does not open a hole.

### D5. Passwords (**REVIEW**)
- SCIM-created users get a random 32-character password that nobody knows (Argon2id hashed like any other); it is not returned or logged. Such users cannot sign in with a password until an admin sets one, or until SSO (a later milestone) is the way in. The `password` attribute in a payload is **ignored** (never stored, never logged) and `/ServiceProviderConfig` has `changePassword.supported = false`. Rationale: IdPs that provision passwords push them through a channel we would have to protect forever; with SSO as the target sign-in method it is unnecessary.
- Known gap: there is no "invite / set password by email" flow yet, so SCIM users cannot sign in until an admin resets the password or SSO exists.

### D6. Deprovisioning (**REVIEW**)
`active: false`, and `DELETE /Users/{id}`, both **deactivate** (`status = inactive`), revoke all sessions and OIDC refresh tokens, and keep the row, audit trail and group memberships. `DELETE` returns 204 and is idempotent. Hard delete via SCIM is not implemented; an admin can still delete a user in the admin UI. Reactivation (`active: true`) restores `active` status and re-runs group rules. Rationale: IdPs often send DELETE for "unassign from app", which must be reversible; hard delete destroys the audit link.

### D7. Groups
- `id` = the group's integer id as a string (groups have no public id yet; they are tenant-scoped and token-protected). `displayName` = `groups.name` (case-insensitive unique, 409 `uniqueness`), `externalId` via `scim_links`, `members` = users (`value`, `display`, `$ref`).
- **System groups are invisible to SCIM** (404 on get, absent from lists) and cannot be created, changed or deleted. Groups targeted by a group rule cannot be deleted via SCIM (409).
- Membership sync: add/remove/replace via PATCH, full replace via PUT. A member `value` must be an existing user of the tenant (400 `invalidValue` otherwise). Adding an existing member is a no-op.
- **Rule-managed memberships (ADR 006) cannot be removed via SCIM**: any request that would remove one fails as a whole with 409 `mutability`, nothing is applied. SCIM-created memberships have `rule_id NULL` and `added_by_user_id NULL`.
- `GROUP_MEMBER_*` counts (`member_count`) are kept in sync as in the admin API.
- Admin users may be members of SCIM groups (membership grants no rights, D4).
- Mutations are atomic: one transaction per request.

### D8. Filtering
`GET /Users` and `GET /Groups` support `filter` through a real tokenizer and recursive-descent parser (no `eval`, no SQL text). Operators: `eq ne co sw ew pr`, `and`, `or` (`and` binds tighter), parentheses. Unsupported (`gt ge lt le`, `not`, value-path filters like `emails[...]`) return 400 `invalidFilter`. Attributes are checked against an allow-list and mapped to SQLAlchemy columns with bound parameters; `co/sw/ew` escape `%` and `_`. Limits: 1000 characters, 50 tokens, nesting depth 10. Matching is case-insensitive for strings (all our string attributes are `caseExact=false`). Allow-list for Users: `id, userName, externalId, active, displayName, name.givenName, name.familyName, emails.value, emails (pr only)`; for Groups: `id, displayName, externalId, members.value`.

### D9. PATCH engine (RFC 7644 3.5.2)
The engine renders the resource to its SCIM JSON, applies the operations generically (path grammar: `attr`, `attr.sub`, `attr[filter]`, `attr[filter].sub`, schema-URN prefixed), and then validates the result through the same code path as PUT. Supported: `add`, `replace`, `remove` (op names case-insensitive), path-less `add`/`replace` with an object value (including dotted and URN-prefixed keys), filtered paths on multi-valued attributes, `remove` on a multi-valued attribute with a value list (Entra), `active` as string. Errors: 400 `noTarget` when a filtered path matches nothing (replace/remove), 400 `invalidPath`, 400 `invalidValue`, 400 `invalidSyntax`, 400 `mutability` for read-only attributes (`id`, `meta`, `groups`), except that `groups` and `meta` in a path-less value are ignored since several IdPs echo the whole resource. Atomic per request. `PUT` replaces the mapped attributes; attributes it omits are cleared if the schema allows (profile attributes) and required ones must be present.

### D10. Pagination, metadata, discovery
- `startIndex` is 1-based (values < 1 are treated as 1), `count` default 100, max 200, `count=0` returns only `totalResults`. Order is by internal id (stable). Responses: `totalResults`, `startIndex`, `itemsPerPage`, `Resources`.
- `meta.version` is a weak ETag derived from `updated_at` (and, for groups, the member set). `ETag` response header on single resources. `If-Match` on PUT/PATCH/DELETE is honoured (412 on mismatch); `If-None-Match` is not.
- `GET /ServiceProviderConfig`, `/ResourceTypes`, `/Schemas` (+ `/Schemas/{id}`, `/ResourceTypes/{id}`). ServiceProviderConfig says honestly: `patch.supported=true`, `bulk.supported=false`, `filter.supported=true (maxResults=200)`, `changePassword.supported=false`, `sort.supported=false`, `etag.supported=true`, `authenticationSchemes=[oauthbearertoken]`. Discovery endpoints still require the bearer token (they reveal only our schema, but deny by default is simpler; RFC 7644 allows either).
- Not supported, stated in ServiceProviderConfig and answered honestly: `/Bulk`, `/Me` and `POST .../.search` return 501; `sortBy`/`sortOrder` are ignored (`sort.supported=false`, allowed by RFC 7644 3.4.2.3); `attributes`/`excludedAttributes` are ignored (full resources are returned); only one email and one phone number are stored; `password` and `changePassword` are not supported.

### D11. Data model (migration 0016)
`scim_tokens` (tenant-owned: `id, tenant_id, name, token_hash unique, token_prefix, created_by_user_id (SET NULL), created_at, expires_at, revoked_at, last_used_at`) and `scim_links` (tenant-owned: `id, tenant_id, user_id? (CASCADE), group_id? (CASCADE), external_id, created_at`; exactly one of user_id/group_id; unique `(tenant_id, user_id)`, `(tenant_id, group_id)`; partial unique indexes `(tenant_id, external_id)` per kind). Audit actions (plain strings): `SCIM_TOKEN_CREATED/REVOKED/AUTH_FAILED`, `SCIM_USER_CREATED/UPDATED/DEACTIVATED/ACTIVATED`, `SCIM_GROUP_CREATED/UPDATED/DELETED`, `SCIM_GROUP_MEMBER_ADDED/REMOVED`. Actor is recorded as `actor_type="scim_token"`, `actor_id=<token id>`. Audit metadata never contains attribute values beyond the keys changed (no PII beyond what existing audit events log, i.e. email on create).

## Security review (checklist, against RFC 9700-style thinking)
| Threat | Control |
|---|---|
| Token theft from DB | Only keyed hash stored; shown once |
| Token guessing | 256-bit; per-IP failure limit; uniform 401 |
| Token timing | `compare_digest`; lookup by hash of the secret |
| Cross-tenant | Tenant from token only; all queries through the scoped session; tests use two tenants |
| Filter injection | Parser + allow-list + bound parameters; no string SQL, no eval, length/depth limits |
| Mass assignment | Fixed field mapping; `is_admin`, `is_super_admin`, `password`, `status` (except via `active`), `tenant_id` never read |
| Privilege escalation | Admins read-only to SCIM; groups carry no rights today; standing constraint for future mapping (D4) |
| Account takeover by email change | Possible only for non-admin users, which the IdP legitimately owns; email uniqueness enforced. **REVIEW**: an IdP can change a user's email, and email is the login name |
| Enumeration | Token required for everything; 404 vs 409 are inherent to SCIM; admins cannot be written |
| Oversized payloads | 1 MiB body cap, op/member caps, string length from the catalog |
| ReDoS | No regex on user-controlled patterns; tokenizer is linear |
| Log leakage | No bodies, tokens, passwords or emails in logs |
| Replay | Idempotent semantics; ETag preconditions; no nonces (bearer token is the credential, TLS required in production) |

## Implementation backlog
| ID | Milestone | Work | Status |
|---|---|---|---|
| S1 | Core server | Tokens (admin API + UI), Users and Groups CRUD, PATCH, filter, pagination, discovery, audit, tests | **Done** (branch `feature-scim-server`) |
| S2 | Conformance | Run against Entra's SCIM validator and Okta's SCIM test suite (Runscope) and fix deviations; real tenant tests | Not started |
| S3 | Token scopes | Read-only / users-only tokens, token IP allow-list, rotate with overlap | Not started |
| S4 | Sign-in for provisioned users | Invite / set-password email or SSO, "must change password" | Not started (depends on SSO) |
| S5 | Attribute projection | `attributes` / `excludedAttributes`, `valuePath` in filters, `not`, `gt/lt` on `meta.lastModified` | Not started |
| S6 | Hard delete / retention | Optional hard-delete policy per token after N days inactive | Not started |
| S7 | Bulk, `/.search`, sorting | Only if a customer requires it | Not planned |
| S8 | Group public ids | Opaque group ids instead of integers; `groups.external_id` | Not started |
