export type Claim = { name: string; source: string; required?: boolean; filter?: { type: string; value: string } };
export type SamlDraft = {
  acs_url: string; sp_entity_id: string; audience: string; name_id_format: string; signing: string;
};
export type ConfigPlan = { fields: Partial<SamlDraft>; claims: Claim[]; changes: string[]; errors: string[] };

/** Bounded, local interpretation. No model, network, secret input or implicit saves.
 * Each line must match a supported sentence; any unsupported line blocks applying.
 */
export function translateSamlConfig(text: string): ConfigPlan {
  const plan: ConfigPlan = { fields: {}, claims: [], changes: [], errors: [] };
  if (!text.trim() || text.length > 4000) { plan.errors.push("Enter 1 to 4000 characters."); return plan; }
  const seen = new Set<string>();
  const error = (n: number, message: string) => plan.errors.push("Line " + n + ": " + message);
  const add = (key: string, n: number, run: () => void) => {
    if (seen.has(key)) error(n, "Conflicting or repeated setting. Keep one instruction for " + key + ".");
    else { seen.add(key); run(); }
  };
  for (const [index, raw] of text.split(/\n|;/).entries()) {
    const line = raw.trim().replace(/\.$/, "");
    if (!line) continue;
    const n = index + 1;
    let match: RegExpMatchArray | null;
    if ((match = line.match(/^set (ACS(?: URL)?|SP entity ID|audience) to (\S+)$/i))) {
      const key = /^acs/i.test(match[1]) ? "acs_url" : /^sp/i.test(match[1]) ? "sp_entity_id" : "audience";
      const value = match[2];
      if (key === "acs_url") {
        try { const url = new URL(value); if (url.protocol !== "https:" || url.username || url.password || url.hash) throw Error(); }
        catch { error(n, "ACS must be an HTTPS URL without credentials or a fragment."); continue; }
      } else if (value.length > 500 || /[<>"']/.test(value)) { error(n, "Use a valid entity identifier."); continue; }
      add(key, n, () => { plan.fields[key] = value; plan.changes.push(match![1] + " → " + value); });
    } else if ((match = line.match(/^(?:use|set) (persistent|email|username) name ?id$/i))) {
      add("name_id_format", n, () => { plan.fields.name_id_format = match![1].toLowerCase(); plan.changes.push("Name ID → " + plan.fields.name_id_format); });
    } else if ((match = line.match(/^sign (both(?: the assertion and response)?|(?:the )?assertion(?: only)?|(?:the )?response(?: only)?)$/i))) {
      const value = /^both/i.test(match[1]) ? "both" : /assertion/i.test(match[1]) ? "assertion" : "response";
      add("signing", n, () => { plan.fields.signing = value; plan.changes.push("Signing → " + value); });
    } else if ((match = line.match(/^send (email|username|first name|last name|display name) as ([A-Za-z][A-Za-z0-9_.:-]{0,99})( required)?$/i))) {
      const sources: Record<string, string> = { email: "email", username: "username", "first name": "first_name", "last name": "last_name", "display name": "display_name" };
      const name = match[2];
      add("claim:" + name, n, () => { plan.claims.push({ name, source: sources[match![1].toLowerCase()], required: !!match![3] }); plan.changes.push("Claim " + name + " ← " + match![1] + (match![3] || "")); });
    } else if ((match = line.match(/^send groups (starting with|containing|equal to) ([A-Za-z0-9_.:@-]{1,100}) as ([A-Za-z][A-Za-z0-9_.:-]{0,99})$/i))) {
      const types: Record<string, string> = { "starting with": "starts_with", containing: "contains", "equal to": "equals" };
      const name = match[3];
      add("claim:" + name, n, () => { plan.claims.push({ name, source: "groups", filter: { type: types[match![1].toLowerCase()], value: match![2] } }); plan.changes.push("Claim " + name + " ← groups " + match![1] + " " + match![2]); });
    } else error(n, "Could not interpret this instruction. Use the examples; nothing will be applied.");
  }
  if (!plan.changes.length && !plan.errors.length) plan.errors.push("No configuration instructions found.");
  return plan;
}

export function mergeClaims(current: Claim[], proposed: Claim[]): Claim[] {
  const replaced = new Set(proposed.map((claim) => claim.name));
  return [...current.filter((claim) => !replaced.has(claim.name)), ...proposed];
}
