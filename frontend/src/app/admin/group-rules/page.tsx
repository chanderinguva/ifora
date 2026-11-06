"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fieldClass, td, th } from "@/components/bits";
import { http, qs, type Page } from "@/lib/http";
import type { Group, GroupRule, ProfileAttribute, RuleCondition } from "@/lib/types";

const OPERATORS: [string, string][] = [
  ["equals", "equals"], ["not_equals", "does not equal"], ["starts_with", "starts with"], ["ends_with", "ends with"],
  ["contains", "contains"], ["is_set", "is set"], ["is_not_set", "is not set"],
];
// Built-in account fields, plus administrator-managed attributes from the Profile editor.
type Field = { key: string; label: string; type: string; options?: string[] | null };
const ACCOUNT_FIELDS: Field[] = [
  { key: "email", label: "Email", type: "string" },
  { key: "username", label: "Username", type: "string" },
  { key: "status", label: "Account status", type: "enum", options: ["active", "inactive", "suspended"] },
];
const BOOL_OPS = ["equals", "not_equals", "is_set", "is_not_set"];
const NUM_OPS = ["equals", "not_equals", "is_set", "is_not_set"];
const ENUM_OPS = ["equals", "not_equals", "is_set", "is_not_set"];
const opsFor = (type: string) => (type === "boolean" ? BOOL_OPS : type === "number" ? NUM_OPS : type === "enum" ? ENUM_OPS : OPERATORS.map(([v]) => v));
const blank = (): RuleCondition => ({ attribute: "department", operator: "equals", value: "" });

type Draft = { id?: number; name: string; match: "all" | "any"; conditions: RuleCondition[]; group_ids: number[] };
const emptyDraft = (): Draft => ({ name: "", match: "all", conditions: [blank()], group_ids: [] });

export default function GroupRulesPage() {
  const [rules, setRules] = useState<GroupRule[] | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [attrs, setAttrs] = useState<ProfileAttribute[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [preview, setPreview] = useState<{ count: number; sample: { email: string }[] } | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    http<{ group_rules: boolean }>("/admin/features").then((f) => {
      setEnabled(f.group_rules);
      if (!f.group_rules) return;
      http<{ items: GroupRule[] }>("/admin/group-rules").then((r) => setRules(r.items)).catch((e) => setMsg({ ok: false, text: e.message }));
      http<{ items: ProfileAttribute[] }>("/admin/profile-attributes").then((r) => setAttrs(r.items)).catch(() => {});
      http<Page<Group>>(`/admin/groups${qs({ page: 1, page_size: 100 })}`).then((r) => setGroups(r.items.filter((g) => !g.is_system_group))).catch(() => {});
    }).catch((e) => setMsg({ ok: false, text: e.message }));
  }, []);
  useEffect(load, [load]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: ok });
      load();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    }
  }

  const setCond = (i: number, patch: Partial<RuleCondition>) =>
    setDraft((d) => d && { ...d, conditions: d.conditions.map((c, j) => (j === i ? { ...c, ...patch } : c)) });

  const managed: Field[] = attrs.filter((a) => !a.user_editable).map((a) => ({ key: a.key, label: a.display_name, type: a.data_type, options: a.enum_options }));
  const selfEdited = attrs.filter((a) => a.user_editable);
  const fields = [...managed, ...ACCOUNT_FIELDS];
  const fieldOf = (key: string): Field => fields.find((f) => f.key === key) ?? { key, label: key, type: "string" };

  if (!enabled) {
    return (
      <div>
        <PageHeader title="Group rules" />
        <Alert><AlertDescription>Group rules are not enabled for this deployment (<code>GROUP_RULES_ENABLED</code>).</AlertDescription></Alert>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Group rules">
        <Button onClick={() => { setDraft(emptyDraft()); setPreview(null); }}><Plus className="mr-1 h-4 w-4" /> Add rule</Button>
      </PageHeader>
      <p className="mb-4 max-w-2xl text-sm text-muted-foreground">
        A rule adds matching active users to one or more groups automatically, and removes them when they stop matching. Rules can use
        only administrator-managed attributes (email, username, status, department, employee ID…), never fields users edit themselves.
        Manually added members are never changed by rules.
      </p>

      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      {draft && (
        <Card className="mb-6" data-testid="rule-editor">
          <CardHeader><CardTitle>{draft.id ? "Edit rule" : "Add rule"}</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="r-name">Rule name</Label>
              <Input id="r-name" maxLength={100} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </div>

            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm">
                <span>If</span>
                <select aria-label="Match mode" className={fieldClass + " !w-auto"} value={draft.match} onChange={(e) => setDraft({ ...draft, match: e.target.value as "all" | "any" })}>
                  <option value="all">all</option>
                  <option value="any">any</option>
                </select>
                <span>of these conditions are true:</span>
              </div>
              {draft.conditions.map((c, i) => {
                const f = fieldOf(c.attribute);
                const needsValue = c.operator !== "is_set" && c.operator !== "is_not_set";
                return (
                  <div key={i} className="grid gap-2 rounded-md border p-2 sm:grid-cols-[1fr_11rem_1fr_auto]" data-testid="condition-row">
                    <select aria-label="Attribute" className={fieldClass} value={c.attribute}
                      onChange={(e) => { const nf = fieldOf(e.target.value); setCond(i, { attribute: e.target.value, operator: opsFor(nf.type).includes(c.operator) ? c.operator : "equals", value: "" }); }}>
                      <optgroup label="Managed profile attributes">
                        {managed.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
                      </optgroup>
                      <optgroup label="Account">
                        {ACCOUNT_FIELDS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
                      </optgroup>
                      {!fields.some((x) => x.key === c.attribute) && <option value={c.attribute}>{c.attribute}</option>}
                    </select>
                    <select aria-label="Operator" className={fieldClass} value={c.operator} onChange={(e) => setCond(i, { operator: e.target.value })}>
                      {OPERATORS.filter(([v]) => opsFor(f.type).includes(v)).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                    {needsValue ? (
                      f.type === "enum" || f.type === "boolean" ? (
                        <select aria-label="Value" className={fieldClass} value={c.value} onChange={(e) => setCond(i, { value: e.target.value })}>
                          <option value="">Choose…</option>
                          {f.type === "boolean" ? [["true", "Yes"], ["false", "No"]].map(([v, l]) => <option key={v} value={v}>{l}</option>) : f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      ) : (
                        <Input aria-label="Value" type={f.type === "number" ? "number" : "text"} value={c.value} onChange={(e) => setCond(i, { value: e.target.value })} />
                      )
                    ) : <span />}
                    <Button type="button" variant="outline" size="sm" aria-label="Remove condition" disabled={draft.conditions.length === 1}
                      onClick={() => setDraft({ ...draft, conditions: draft.conditions.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></Button>
                  </div>
                );
              })}
              <Button type="button" variant="secondary" size="sm" onClick={() => setDraft({ ...draft, conditions: [...draft.conditions, blank()] })}>Add condition</Button>
              {selfEdited.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Not available: {selfEdited.map((a) => a.display_name).join(", ")} — users can edit these themselves. Manage attributes in the{" "}
                  <a className="underline underline-offset-4" href="/admin/profile-editor">Profile editor</a>.
                </p>
              )}
            </div>

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Then assign to</legend>
              {groups.length === 0 && <p className="text-sm text-muted-foreground">Create a group first.</p>}
              <div className="flex flex-wrap gap-3">
                {groups.map((g) => (
                  <label key={g.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={draft.group_ids.includes(g.id)}
                      onChange={(e) => setDraft({ ...draft, group_ids: e.target.checked ? [...draft.group_ids, g.id] : draft.group_ids.filter((x) => x !== g.id) })} />
                    {g.name}
                  </label>
                ))}
              </div>
            </fieldset>

            {preview && (
              <p className="text-sm" data-testid="rule-preview">
                {preview.count} active user{preview.count === 1 ? "" : "s"} match{preview.count === 1 ? "es" : ""} right now
                {preview.sample.length > 0 && <span className="text-muted-foreground"> — e.g. {preview.sample.map((s) => s.email).join(", ")}</span>}
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline"
                onClick={() => run(async () => setPreview(await http("/admin/group-rules/preview", { method: "POST", body: { match: draft.match, conditions: draft.conditions } })), "Preview updated")}>
                Preview matches
              </Button>
              <Button type="button" disabled={!draft.name.trim() || draft.group_ids.length === 0}
                onClick={() => run(async () => {
                  const body = { name: draft.name, match: draft.match, conditions: draft.conditions, group_ids: draft.group_ids };
                  if (draft.id) await http(`/admin/group-rules/${draft.id}`, { method: "PUT", body });
                  else await http("/admin/group-rules", { method: "POST", body });
                  setDraft(null);
                }, "Rule saved. It is inactive until you activate it.")}>
                Save rule
              </Button>
              <Button type="button" variant="ghost" onClick={() => setDraft(null)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full" data-testid="rules-table">
            <thead className="border-b"><tr><th className={th}>Rule</th><th className={th}>Condition</th><th className={th}>Assigns to</th><th className={th}>Status</th><th className={th}></th></tr></thead>
            <tbody>
              {rules?.map((r) => (
                <tr key={r.id} className="border-b last:border-0 align-top">
                  <td className={td + " font-medium"}>{r.name}</td>
                  <td className={td + " font-mono text-xs"}>{r.expression}</td>
                  <td className={td}>{r.groups.map((g) => g.name).join(", ") || "—"}</td>
                  <td className={td}><Badge tone={r.status === "active" ? "good" : "neutral"}>{r.status}</Badge></td>
                  <td className={td + " space-x-2 text-right whitespace-nowrap"}>
                    {r.status === "inactive" ? (
                      <>
                        <Button size="sm" variant="outline" onClick={() => { setPreview(null); setDraft({ id: r.id, name: r.name, match: r.match, conditions: r.conditions, group_ids: r.groups.map((g) => g.id) }); }}>Edit</Button>
                        <Button size="sm" onClick={() => run(() => http(`/admin/group-rules/${r.id}/activate`, { method: "POST" }), "Rule activated; matching users were added")}>Activate</Button>
                      </>
                    ) : (
                      <Button size="sm" variant="outline" onClick={() => { if (confirm("Deactivate this rule? Memberships it created will be removed. Manually added members stay.")) run(() => http(`/admin/group-rules/${r.id}/deactivate`, { method: "POST" }), "Rule deactivated; its memberships were removed"); }}>Deactivate</Button>
                    )}
                    <Button size="sm" variant="outline" onClick={() => { if (confirm(`Delete rule "${r.name}"? Memberships it created will be removed.`)) run(() => http(`/admin/group-rules/${r.id}`, { method: "DELETE" }), "Rule deleted"); }}>Delete</Button>
                  </td>
                </tr>
              ))}
              {rules && rules.length === 0 && <tr><td className={td} colSpan={5}>No rules yet.</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
