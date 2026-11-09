# ADR 018: Global password, lockout and session policy

Status: accepted (phase 6b of `docs/project/okta-parity-roadmap.md`)

## Decision
One row per tenant (`org_security_policy`) holds the organization's rules; **no row means the built-in defaults**, which equal the behaviour before this feature (12 characters, mixed case, digit, 5 failures / 15 minutes lockout, 8 h sessions, 30 min idle). Edited under Security > Password & sessions (`/admin/security-policy`, area *security*, so org admins write and read-only admins read).

- **Password:** minimum length (8-64), mixed case, digit, symbol, "no name/email part" (3+ characters), history (0-24), maximum age in days (0 = never).
- **Lockout:** failed attempts (3-20) and lockout minutes (1-1440), used by password login, the MFA challenge and the expired-password change.
- **Session:** maximum lifetime (1-168 h) and idle timeout (5-1440 min); idle may not exceed lifetime.

All password paths call `security_policy/service.py` (`validate_new`, `apply_new`, `set_checked`): self change, admin set, admin create, reset/invite link, expired-password change. The pydantic validator keeps only hard bounds (8-128 characters). Admin-generated temporary passwords are produced to satisfy the current policy.

## Behaviour worth knowing
- **Applies to new passwords only.** Existing passwords are never re-checked.
- **Max age is lazy.** At sign-in, after the correct password is proven, an account whose password is older than the limit (`password_changed_at`, falling back to `created_at`) moves to `password_expired` (audited `PASSWORD_EXPIRED_BY_POLICY`) and uses the existing change-expired flow. The editor shows how many active users are already past the limit before anyone is affected.
- **Session limits are read on every request**, so tightening them ends open sessions at their next request; lengthening cannot revive an already expired session. New sessions get the cookie `Max-Age` from the policy.
- **Reset links are not burned by a weak password:** the policy is checked before the token is claimed.
- **History** stores Argon2id hashes only (the current hash plus up to 24 earlier ones) and is only filled while history is on.
- `GET /api/v1/password-policy` is public and returns only the human-readable rules and the minimum length, so the set-password, forgot-password and settings pages can show them. Lockout, age and session values are not exposed.
- Changes are audited as `SECURITY_POLICY_CHANGED` with before/after of the changed fields only.

## Not done
- First-admin bootstrap still requires only 8 characters (it runs before any policy exists); the account is expected to change it.
- No breached-password (k-anonymity) check, no per-group policies or rule ordering as in Okta, no "MFA at sign-in" rules, no minimum password age, no expiry warning emails.
- Policy changes are not versioned beyond the audit trail.
