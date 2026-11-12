/** Explicit deployment identity; NODE_ENV only describes the rendering mode. */
export function deploymentTitle(environment?: string, name = "Ifora"): string {
  const labels: Record<string, string> = {
    demo: "Demo", development: "Dev", dev: "Dev", production: "Production",
    staging: "Staging", test: "Test",
  };
  const label = labels[(environment || "").toLowerCase()];
  return label ? `${name} ${label}` : name;
}
