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
  groups?: { id: number; name: string }[];
  editable_attributes?: string[];
};

export type Group = {
  id: number;
  name: string;
  description: string | null;
  is_system_group: boolean;
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
  client_type: "public" | "confidential";
  first_party: boolean;
  status: "active" | "disabled";
  redirect_uris: string[];
  post_logout_redirect_uris: string[];
  allowed_scopes: string[];
  grant_types: string[];
  secrets: OidcSecret[];
  client_secret?: string;
};

export type RuleCondition = { attribute: string; operator: string; value: string };
export type GroupRule = {
  id: number;
  name: string;
  status: "active" | "inactive";
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
