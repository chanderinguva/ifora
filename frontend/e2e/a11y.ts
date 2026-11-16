import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, type TestInfo } from "@playwright/test";

/** WCAG 2.1 A and AA rules only. Serious and critical findings fail the test; the rest are attached for the audit table. */
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

export type Finding = { page: string; scheme: string; rule: string; impact: string; help: string; nodes: number; example: string };

export async function audit(page: Page, path: string, scheme: "light" | "dark", info: TestInfo, ready?: () => Promise<unknown>) {
  await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
  await page.goto(path);
  await page.waitForLoadState("networkidle");
  if (ready) await ready();
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const found: Finding[] = results.violations.map((v) => ({
    page: path, scheme, rule: v.id, impact: v.impact ?? "minor", help: v.help, nodes: v.nodes.length, example: v.nodes[0]?.target.join(" ") ?? "",
  }));
  await info.attach(`axe ${path} ${scheme}.json`, { body: JSON.stringify(found, null, 2), contentType: "application/json" });
  return found;
}

/** Fail with the whole list, so one run shows every serious or critical finding instead of the first page's. */
export function expectNoBlocking(all: Finding[]) {
  const blocking = all.filter((f) => f.impact === "serious" || f.impact === "critical");
  expect(blocking, `serious or critical WCAG 2.1 AA violations:\n${blocking.map((f) => `${f.page} [${f.scheme}] ${f.rule} (${f.impact}) x${f.nodes}: ${f.example}`).join("\n")}`).toEqual([]);
}
