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
  has_icon: boolean;
  assigned_users: number;
  assigned_groups: number;
  created_at: string;
  updated_at: string;
};

export type MyApp = { id: number; name: string; description: string | null; sign_on_mode: string; launchable: boolean; has_icon: boolean };

export const SIGN_ON_LABEL: Record<string, string> = { none: "None (provisioning only)", bookmark: "Bookmark", oidc: "OpenID Connect", saml: "SAML 2.0", swa: "Secure Web Authentication (stored password)" };

export function appBody(a: Pick<AppSummary, "name" | "description" | "sign_on_mode" | "launch_url" | "status" | "visible" | "require_assignment">) {
  return {
    name: a.name, description: a.description || null, sign_on_mode: a.sign_on_mode,
    launch_url: a.sign_on_mode === "none" || a.sign_on_mode === "saml" || a.sign_on_mode === "swa" ? null : a.launch_url || null, status: a.status, visible: a.visible, require_assignment: a.require_assignment,
  };
}

export type Template = { id: string; label: string; description: string; client_type: string; needs_redirects: boolean; has_secret: boolean };
