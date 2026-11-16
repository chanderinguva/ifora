/** Task-oriented entry points (IFORA-42): what an administrator wants to do, not which page it lives on. */
export type AdminTask = { id: string; title: string; hint: string; href: string; keywords: string[] };

export const ADMIN_TASKS: AdminTask[] = [
  { id: "add-app", title: "Add an app", hint: "Connect an application with OpenID Connect, SAML or a bookmark", href: "/admin/applications/new", keywords: ["application", "integration", "sso", "oidc", "saml", "connect"] },
  { id: "onboard-user", title: "Onboard a user", hint: "Create an account and give it access", href: "/admin/users?new=1", keywords: ["user", "invite", "create", "employee", "account", "new"] },
  { id: "investigate-login", title: "Investigate a login", hint: "Failed and unusual sign-ins in the system log", href: "/admin/audit?action=LOGIN_FAILURE", keywords: ["login", "sign-in", "failed", "audit", "log", "suspicious", "security"] },
  { id: "test-policy", title: "Test a sign-on policy", hint: "Simulate a decision for an app before saving it (open an application, then its policy)", href: "/admin/applications", keywords: ["policy", "simulate", "simulation", "what if", "zone", "mfa"] },
];

export function matchTasks(q: string): AdminTask[] {
  const t = q.trim().toLowerCase();
  if (!t) return ADMIN_TASKS;
  return ADMIN_TASKS.filter((x) => x.title.toLowerCase().includes(t) || x.keywords.some((k) => k.includes(t) || t.includes(k)));
}
