/** Types for the unified Applications object (ADR 010). */

export type AppSummary = {
  id: number;
  public_id: string;
  name: string;
  description: string | null;
  sign_on_mode: "none" | "bookmark" | "oidc" | "saml" | "swa";
  launch_url: string | null;
  status: "active" | "inactive";
  visible: boolean;
  require_assignment: boolean;
  oidc_client: { id: number; client_id: string; name: string; client_type: string } | null;
  saml: { sp_entity_id: string; acs_url: string } | null;
  swa: { login_url: string } | null;
  provisioning: { id: number; kind: string; enabled: boolean } | null;
  owner_user_id: number | null;
  sensitivity: "low" | "medium" | "high" | null;
  review_by: string | null;
  tags: string[];
  attributes: Record<string, string>;
  has_icon: boolean;
  assigned_users: number;
  assigned_groups: number;
  created_at: string;
  updated_at: string;
};

export type MyApp = { id: number; name: string; description: string | null; sign_on_mode: string; launchable: boolean; has_icon: boolean };

export const SIGN_ON_LABEL: Record<string, string> = { none: "None (provisioning only)", bookmark: "Bookmark", oidc: "OpenID Connect", saml: "SAML 2.0", swa: "Secure Web Authentication (stored password)" };

export function appBody(a: Pick<AppSummary, "name" | "description" | "sign_on_mode" | "launch_url" | "status" | "visible" | "require_assignment"> & Partial<Pick<AppSummary, "owner_user_id" | "sensitivity" | "review_by" | "tags" | "attributes">>) {
  const meta = "tags" in a ? { owner_user_id: a.owner_user_id ?? null, sensitivity: a.sensitivity || null, review_by: a.review_by || null, tags: a.tags ?? [], attributes: a.attributes ?? {} } : {};
  return {
    ...meta,
    name: a.name, description: a.description || null, sign_on_mode: a.sign_on_mode,
    launch_url: a.sign_on_mode === "none" || a.sign_on_mode === "saml" || a.sign_on_mode === "swa" ? null : a.launch_url || null, status: a.status, visible: a.visible, require_assignment: a.require_assignment,
  };
}

export type AppTemplate = { key: string; name: string; category: string; description: string; connector: string | null; sign_on: "oidc" | "saml" | "none"; oidc_type: string | null; provisioning: boolean;
  fields: { key: string; label: string; help: string; placeholder: string; secret: boolean }[]; checklist: string[] };
export type Template = { id: string; label: string; description: string; client_type: string; needs_redirects: boolean; has_secret: boolean };
