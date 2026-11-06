// Per-user display preferences (time zone, locale) used by every date/time rendered in the UI.
let prefs: { timeZone?: string; locale?: string } = {};

export function setDisplayPrefs(attrs: Record<string, unknown> | null | undefined) {
  const tz = typeof attrs?.timezone === "string" ? attrs.timezone : undefined;
  const loc = typeof attrs?.locale === "string" ? attrs.locale : undefined;
  prefs = { timeZone: tz || undefined, locale: loc || undefined };
}

export function formatDateTime(ts: string): string {
  const d = new Date(ts);
  try {
    return d.toLocaleString(prefs.locale, { timeZone: prefs.timeZone, timeZoneName: prefs.timeZone ? "short" : undefined });
  } catch {
    return d.toLocaleString(); // unknown zone/locale stored by an older version: fall back to the browser
  }
}

export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/** All IANA zones the browser knows, grouped by region, with a current UTC offset label. */
export function timeZoneGroups(): { region: string; zones: { id: string; label: string }[] }[] {
  const anyIntl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] };
  const ids = anyIntl.supportedValuesOf ? anyIntl.supportedValuesOf("timeZone") : ["UTC"];
  if (!ids.includes("UTC")) ids.push("UTC");
  const now = new Date();
  const groups = new Map<string, { id: string; label: string }[]>();
  for (const id of ids) {
    let offset = "";
    try {
      offset = new Intl.DateTimeFormat("en", { timeZone: id, timeZoneName: "shortOffset" }).formatToParts(now).find((p) => p.type === "timeZoneName")?.value ?? "";
    } catch {}
    const [region, ...rest] = id.includes("/") ? id.split("/") : ["Other", id];
    const name = rest.join(" / ").replace(/_/g, " ") || region;
    (groups.get(region) ?? groups.set(region, []).get(region)!).push({ id, label: `${name} (${offset || "UTC"})` });
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([region, zones]) => ({ region, zones }));
}

export const LOCALES = [
  "en-US", "en-GB", "en-CA", "en-AU", "fr-FR", "fr-CA", "de-DE", "es-ES", "es-MX", "pt-BR", "pt-PT", "it-IT",
  "nl-NL", "sv-SE", "pl-PL", "tr-TR", "ja-JP", "ko-KR", "zh-CN", "zh-TW", "hi-IN", "ar-SA",
];

export function localeName(code: string): string {
  try {
    return new Intl.DisplayNames(["en"], { type: "language", languageDisplay: "standard" }).of(code) ?? code;
  } catch {
    return code;
  }
}
