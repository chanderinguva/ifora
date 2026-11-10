export type User = {
  id: number;
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  status: string;
  is_admin: boolean;
  is_super_admin: boolean;
  created_at: string | null;
  last_login_at: string | null;
  profile_attributes: Record<string, string | number | boolean | null>;
  mfa_enabled?: boolean;
  passkey_count?: number;
  passkey_required?: boolean;
  mfa_setup_required?: boolean;
  /** This session has dropped admin powers ("user view"); only present on /me. */
  acting_as_user?: boolean;
  groups?: { id: number; name: string; type?: string }[];
  editable_attributes?: string[];
  attribute_schema?: ProfileAttribute[];
};

export type Group = {
  id: number;
  name: string;
  description: string | null;
  is_system_group: boolean;
  type: string;
  owner_user_id: number | null;
  sensitivity: string | null;
  review_by: string | null;
  tags: string[];
  attributes: Record<string, string>;
  member_count: number;
  created_at: string | null;
  members?: { id: number; email: string; first_name: string; last_name: string; via_rule?: number | null }[];
};

export type OidcSecret = { id: number; hint: string; state: "active" | "expired" | "revoked"; created_at: string; expires_at: string | null; last_used_at: string | null };
export type OidcClient = {
  id: number;
  client_id: string;
  name: string;
  description: string | null;
  client_type: "public" | "confidential" | "service";
  first_party: boolean;
  status: "active" | "disabled";
  redirect_uris: string[];
  post_logout_redirect_uris: string[];
  allowed_scopes: string[];
  allowed_audiences: string[];
  token_endpoint_auth_method: "none" | "client_secret_basic" | "private_key_jwt";
  jwks: { keys: { kid: string; kty: string; alg?: string }[] } | null;
  grant_types: string[];
  access_token_format?: "jwt" | "opaque";
  secrets: OidcSecret[];
  client_secret?: string;
};

export type ScimToken = {
  id: number;
  name: string;
  token_prefix: string;
  status: "active" | "revoked" | "expired";
  created_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  /** Only present in the create response; shown once. */
  token?: string;
  read_only?: boolean;
  users_only?: boolean;
  allowed_cidrs?: string[];
  replaced_by_id?: number | null;
  hard_delete_after_days?: number | null;
};

export type ProfileAttribute = {
  key: string; display_name: string; description: string | null;
  data_type: "string" | "number" | "boolean" | "enum" | "timezone" | "locale";
  enum_options: string[] | null; user_editable: boolean; built_in: boolean;
};
export type RuleCondition = { attribute: string; operator: string; value: string };
export type GroupRule = {
  id: number;
  name: string;
  status: "active" | "inactive";
  kind: "basic" | "expression";
  sync_state?: "idle" | "pending";
  match: "all" | "any";
  conditions: RuleCondition[];
  expression: string;
  groups: { id: number; name: string }[];
};

export type AuditEvent = {
  id: number;
  timestamp: string;
  actor_id: string | null;
  actor_email: string | null;
  action: string;
  event_type: string;
  target_id: string | null;
  target_type: string | null;
  actor_ip_address: string | null;
  metadata: Record<string, unknown> | null;
};

export type Stats = {
  users_total: number;
  users_active: number;
  admins: number;
  groups: number;
  memberships: number;
  active_sessions: number;
  failed_logins_24h: number;
  recent_events: AuditEvent[];
};

// Okta-style lifecycle. Only "active" can sign in; "deprovisioned" (deactivated) also removes every group membership.
export type UserStatus = "staged" | "provisioned" | "active" | "recovery" | "password_expired" | "locked_out" | "suspended" | "deprovisioned";
export const USER_STATUSES: { value: UserStatus; label: string; hint: string }[] = [
  { value: "staged", label: "Staged", hint: "Created, not yet activated" },
  { value: "provisioned", label: "Provisioned", hint: "Activated, user has not finished setup" },
  { value: "active", label: "Active", hint: "Can sign in" },
  { value: "recovery", label: "Recovery", hint: "Password reset requested" },
  { value: "password_expired", label: "Password expired", hint: "Must set a new password" },
  { value: "locked_out", label: "Locked out", hint: "Too many failed sign-ins" },
  { value: "suspended", label: "Suspended", hint: "Temporarily blocked; keeps groups" },
  { value: "deprovisioned", label: "Deprovisioned", hint: "Deactivated; removed from all groups" },
];
export const statusTone = (s: string) => (s === "active" ? "good" : s === "deprovisioned" || s === "locked_out" || s === "suspended" ? "bad" : "neutral");
