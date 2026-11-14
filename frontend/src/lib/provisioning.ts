export type ProvOptions = {
  push_new_users: boolean;
  push_updates: boolean;
  push_groups: boolean;
  deactivate: "patch" | "delete" | "none";
  update_style: "put" | "patch";
  user_identifier: "email" | "username";
};

export type ProvApp = {
  id: number;
  public_id: string;
  application_id: number;
  name: string;
  description: string | null;
  kind: "scim" | "rest";
  base_url: string;
  auth_type: "bearer" | "basic" | "header" | "oauth2";
  header_name: string | null;
  token_url: string | null;
  client_id: string | null;
  scope: string | null;
  enabled: boolean;
  created_by: number | null;
  options: ProvOptions;
  mapping: { target: string; source: string }[];
  rest_config: Record<string, unknown> | null;
  last_test: { at: string | null; ok: boolean | null; message: string | null };
  assigned_users: number;
  assigned_groups: number;
  provisioned: number;
  errors: number;
  queued: number;
  failed_tasks: number;
};

/** A provisioning facet of an existing Application, initially disabled. */
export function scimSetupBody(applicationId: number, name: string, connection: {
  url: string; auth: string; secret: string; header: string; tokenUrl: string; clientId: string; scope: string; updates: string;
}) {
  return {
    application_id: applicationId, name, kind: "scim", base_url: connection.url, auth_type: connection.auth, secret: connection.secret,
    header_name: connection.auth === "header" ? connection.header : null,
    ...(connection.auth === "oauth2" ? { token_url: connection.tokenUrl, client_id: connection.clientId, scope: connection.scope || null } : {}),
    options: { ...DEFAULT_OPTIONS, update_style: connection.updates, push_groups: false }, mapping: [], enabled: false,
  };
}

export type ProvPreset = {
  key: string;
  name: string;
  kind: "scim" | "rest";
  auth_type: "bearer" | "basic" | "header" | "oauth2";
  description: string;
  options: Partial<ProvOptions>;
  rest_config?: Record<string, unknown>;
};

export const DEFAULT_OPTIONS: ProvOptions = {
  push_new_users: true,
  push_updates: true,
  push_groups: false,
  deactivate: "patch",
  update_style: "put",
  user_identifier: "email",
};

/** The body the API expects, from an app as the API returned it (the secret is only sent when changed). */
export function toBody(a: ProvApp, over: Record<string, unknown> = {}) {
  return {
    name: a.name, description: a.description, kind: a.kind, base_url: a.base_url, auth_type: a.auth_type,
    header_name: a.header_name, token_url: a.token_url, client_id: a.client_id, scope: a.scope, options: a.options, mapping: a.mapping, rest_config: a.rest_config, ...over,
  };
}

