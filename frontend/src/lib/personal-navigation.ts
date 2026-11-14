/** A presentation choice per route, never an authorization or session-role override. */
export function isPersonalRoute(pathname: string): boolean {
  return pathname === "/dashboard" || pathname === "/settings" || pathname === "/apps" || pathname.startsWith("/apps/");
}
