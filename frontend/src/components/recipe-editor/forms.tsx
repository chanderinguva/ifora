"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldClass } from "@/components/bits";
import { PillInput } from "@/components/recipe-bits";
import { ConnectorActionForm, connectorStartingConfig } from "@/components/recipe-editor/connector-form";
import { OPERATOR_LABELS, decisionPills, stepPills, stepsBefore, type Comparison, type Connection, type Definition, type Pill, type RecipeMeta, type StepNode } from "@/lib/recipes";
import { InlineConnection, AuthorizeConnection } from "@/components/connection-editor";
import type { Group } from "@/lib/types";

// Step and trigger forms used by the studio editor.

export type Ctx = {
  folderId?: number | null; connectionAdded?: (c: Connection) => void;
  meta: RecipeMeta; groups: Group[]; connections: Connection[]; connectionsAvailable: boolean; trigger: string; root: StepNode[]; other?: StepNode[]; handler?: boolean; inLoop?: boolean; callOutputs?: string[];
};

const USER_PILL = "{{trigger.user.id}}";
const USER_EMAIL_PILL = "{{trigger.user.email}}";

export function defaultConfig(type: string, ctx: Ctx): Record<string, any> {
  switch (type) {
    case "add_to_group": case "remove_from_group": return { group_id: ctx.groups[0]?.id ?? null, user: USER_PILL };
    case "set_attribute": return { user: USER_PILL, attribute: ctx.meta.managed_attributes[0]?.key ?? "", value: "" };
    case "activate_user": case "deactivate_user": return { user: USER_PILL };
    case "http_request": return { method: "POST", url: "https://", headers: {}, body: "", connection_id: null };
    case "connector_action": return connectorStartingConfig(ctx.connections, ctx.meta);
    case "log": return { message: "" };
    case "send_slack": return { connection_id: ctx.connections.find((c) => c.kind === "slack_webhook")?.id ?? null, message: "" };
    case "send_email": return { to: USER_EMAIL_PILL, subject: "", body: "" };
    case "condition": return { match: "all", conditions: [{ left: "trigger.event.type", operator: "is_set", value: "" }] };
    case "stop": return { outcome: "success", message: "" };
    case "for_each_item": return { list: "", limit: 50 };
    case "for_each_member": return { group_id: ctx.groups[0]?.id ?? null, limit: 50 };
    case "approval": return { message: "", timeout_hours: 24 };
    case "lookup_row": { const t = ctx.meta.lookup_tables?.[0]; return { table: t?.name ?? "", column: t?.key_column ?? t?.columns[0]?.name ?? "", value: "" }; }
    case "lookup_write": { const t = ctx.meta.lookup_tables?.find((x) => !x.admin_managed); return { table: t?.name ?? "", action: t?.key_column ? "upsert" : "add", values: {}, key: "" }; }
    case "set_variable": return { name: "", value: "" };
    case "wait": return { amount: 5, unit: "minutes" };
    case "call_recipe": return { recipe_id: ctx.meta.callable_recipes?.[0]?.id ?? null, inputs: {} };
    case "return_data": return { values: Object.fromEntries((ctx.callOutputs ?? []).map((n) => [n, ""])) };
    case "throttle": return { max_runs: 10, per_minutes: 60, when_full: "wait" };
    default: return {};
  }
}

export function Select({ label, value, onChange, children, className }: { label: string; value: string | number; onChange: (v: string) => void; children: React.ReactNode; className?: string }) {
  return <select aria-label={label} className={fieldClass + (className ? " " + className : "")} value={value} onChange={(e) => onChange(e.target.value)}>{children}</select>;
}

export function Comparisons({ items, onChange, pills, payload }: { items: Comparison[]; onChange: (c: Comparison[]) => void; pills: Pill[]; payload: boolean }) {
  const set = (i: number, patch: Partial<Comparison>) => onChange(items.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const known = pills.some((p) => items.some((c) => c.left === p.path));
  return (
    <div className="space-y-2">
      {items.map((c, i) => (
        <div key={i} className="grid gap-2 rounded-md border p-2 md:grid-cols-[1.2fr_11rem_1.2fr_auto]" data-testid="comparison-row">
          <div className="flex gap-1">
            <Select label="Field" value={c.left} onChange={(v) => set(i, { left: v })}>
              {!pills.some((p) => p.path === c.left) && <option value={c.left}>{c.left}</option>}
              {pills.map((p) => <option key={p.path} value={p.path}>{p.label}</option>)}
            </Select>
            {payload && <Input aria-label="Payload field" className="h-10 w-32" placeholder="payload.field" onBlur={(e) => e.target.value && set(i, { left: "trigger.payload." + e.target.value.replace(/^payload\./, "") })} />}
          </div>
          <Select label="Operator" value={c.operator} onChange={(v) => set(i, { operator: v })}>
            {Object.entries(OPERATOR_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </Select>
          {c.operator === "is_set" || c.operator === "is_not_set" ? <span /> : <PillInput label="Value" value={c.value} onChange={(v) => set(i, { value: v })} pills={pills} />}
          <Button type="button" variant="outline" size="sm" aria-label="Remove comparison" onClick={() => onChange(items.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>
        </div>
      ))}
      <Button type="button" variant="secondary" size="sm" onClick={() => onChange([...items, { left: pills[0]?.path ?? "trigger.event.type", operator: "equals", value: "" }])}>Add comparison</Button>
      {!known && items.length === 0 && <p className="text-xs text-muted-foreground">No comparisons: it always applies.</p>}
    </div>
  );
}

/** The type of the repeat step that contains the step with this id (null if none). */
function loopKind(steps: StepNode[], id: string, within: string | null = null): string | null {
  for (const s of steps) {
    if (s.id === id) return within;
    const inner = s.type === "for_each_member" || s.type === "for_each_item" ? s.type : within;
    const r = loopKind(s.then ?? [], id, inner) ?? loopKind(s.else ?? [], id, within);
    if (r) return r;
  }
  return null;
}

/** The datapills a step may use: the trigger, earlier steps, the current repeat item, and (in the error steps) the error. */
export function pillsFor(ctx: Ctx, stepId: string): Pill[] {
  const before = stepsBefore(ctx.root, stepId);
  const errorPills: Pill[] = ctx.handler ? [{ path: "error.message", label: "Error message" }, { path: "error.step_id", label: "Failed step" }] : [];
  const kind = ctx.inLoop ? loopKind(ctx.root, stepId) : null;
  const loopPills: Pill[] = kind === "for_each_item" ? [
    { path: "loop.item", label: "Current item" }, { path: "loop.index", label: "Loop: position (1-based)" }, { path: "loop.total", label: "Loop: item count" },
  ] : ctx.inLoop ? [
    { path: "loop.user.id", label: "Current member: id" }, { path: "loop.user.email", label: "Current member: email" },
    { path: "loop.user.username", label: "Current member: username" }, { path: "loop.user.status", label: "Current member: status" },
    { path: "loop.index", label: "Loop: position (1-based)" }, { path: "loop.total", label: "Loop: member count" },
  ] : [];
  const pills = [...(ctx.meta.triggers.find((t) => t.type === ctx.trigger)?.fields ?? []), ...stepPills(ctx.meta, before), ...errorPills, ...loopPills];
  return pills;
}

export function StepForm({ step, ctx, onChange }: { step: StepNode; ctx: Ctx; onChange: (s: StepNode) => void }) {
  const cfg = step.config;
  const set = (patch: Record<string, any>) => onChange({ ...step, config: { ...cfg, ...patch } });
  const before = stepsBefore(ctx.root, step.id);
  const pills = pillsFor(ctx, step.id);
  const payload = ctx.meta.triggers.find((t) => t.type === ctx.trigger)?.payload_pills ?? false;
  const userField = (
    <div className="space-y-1"><Label>Target user</Label><PillInput label="Target user" value={cfg.user ?? ""} onChange={(v) => set({ user: v })} pills={pills} payload={payload} /></div>
  );
  switch (step.type) {
    case "add_to_group": case "remove_from_group":
      return (
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1"><Label>Group</Label>
            <Select label="Group" value={cfg.group_id ?? ""} onChange={(v) => set({ group_id: v ? Number(v) : null })}>
              <option value="">Choose a group…</option>{ctx.groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </Select>
            {ctx.groups.length === 0 && <p className="text-xs text-muted-foreground">Create a group first (system groups are not available).</p>}</div>
          {userField}
        </div>
      );
    case "set_attribute": {
      const attr = ctx.meta.managed_attributes.find((a) => a.key === cfg.attribute);
      return (
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1"><Label>Attribute</Label>
            <Select label="Attribute" value={cfg.attribute ?? ""} onChange={(v) => set({ attribute: v, value: "" })}>
              {ctx.meta.managed_attributes.map((a) => <option key={a.key} value={a.key}>{a.display_name}</option>)}
            </Select>
            <p className="text-xs text-muted-foreground">Only administrator-managed attributes can be set by a recipe.</p></div>
          <div className="space-y-1"><Label>New value</Label>
            {attr?.data_type === "enum" ? (
              <Select label="New value" value={cfg.value ?? ""} onChange={(v) => set({ value: v })}><option value="">(clear)</option>{attr.enum_options?.map((o) => <option key={o} value={o}>{o}</option>)}</Select>
            ) : attr?.data_type === "boolean" ? (
              <Select label="New value" value={cfg.value ?? ""} onChange={(v) => set({ value: v })}><option value="">(clear)</option><option value="true">Yes</option><option value="false">No</option></Select>
            ) : (
              <PillInput label="New value" value={cfg.value ?? ""} onChange={(v) => set({ value: v })} pills={decisionPills(ctx.meta, ctx.trigger, before)} payload={payload} placeholder="Leave empty to clear" />
            )}</div>
          {userField}
        </div>
      );
    }
    case "activate_user": case "deactivate_user":
      return <>{userField}<p className="mt-1 text-xs text-muted-foreground">Administrator accounts are never changed by recipes.</p></>;
    case "http_request": {
      const headers: [string, string][] = Object.entries(cfg.headers ?? {}) as [string, string][];
      const setHeaders = (h: [string, string][]) => set({ headers: Object.fromEntries(h.filter(([k]) => k.trim() !== "")) });
      return (
        <div className="space-y-3">
          <div className="grid gap-3 md:grid-cols-[8rem_1fr]">
            <div className="space-y-1"><Label>Method</Label><Select label="Method" value={cfg.method} onChange={(v) => set({ method: v })}>{["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m}>{m}</option>)}</Select></div>
            <div className="space-y-1"><Label>URL</Label><PillInput label="URL" value={cfg.url ?? ""} onChange={(v) => set({ url: v })} pills={pills} payload={payload} /></div>
          </div>
          <div className="space-y-1"><Label>Connection (credentials)</Label>
            <Select label="Connection" value={cfg.connection_id ?? ""} onChange={(v) => set({ connection_id: v ? Number(v) : null })}>
              <option value="">None (no credentials)</option>{ctx.connections.filter((c) => c.kind !== "slack_webhook" && c.kind !== "connector").map((c) => <option key={c.id} value={c.id}>{c.name} → {c.allowed_host}</option>)}
            </Select>
            <InlineConnection folderId={ctx.folderId} connector="http" onCreated={(c) => { ctx.connectionAdded?.(c); if (c.kind !== "connector" && c.kind !== "slack_webhook") set({ connection_id: c.id }); }} />
            {ctx.connections.filter((c) => c.id === cfg.connection_id).map((c) => <AuthorizeConnection key={c.id} connection={c} onRefresh={ctx.connectionAdded} />)}
            <p className="text-xs text-muted-foreground">Store credentials in the connection, including secret header, query and body fields. Keep only non-secret values below.</p>
            {!ctx.connectionsAvailable && <p className="text-xs text-muted-foreground">Connections are unavailable until RECIPE_ENCRYPTION_KEY is configured.</p>}
            <p className="text-xs text-muted-foreground">The secret is attached by the server and only sent to the connection’s own host. Requests to private or internal addresses are blocked.</p></div>
          <div className="space-y-1"><Label>Headers</Label>
            {headers.map(([k, v], i) => (
              <div key={i} className="flex gap-2">
                <Input aria-label="Header name" className="h-10 w-48" value={k} onChange={(e) => setHeaders(headers.map((h, j) => (j === i ? [e.target.value, h[1]] : h)))} />
                <div className="flex-1"><PillInput label="Header value" value={v} onChange={(nv) => setHeaders(headers.map((h, j) => (j === i ? [h[0], nv] : h)))} pills={pills} payload={payload} /></div>
                <Button type="button" size="sm" variant="outline" aria-label="Remove header" onClick={() => setHeaders(headers.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>
              </div>
            ))}
            <Button type="button" size="sm" variant="secondary" onClick={() => set({ headers: { ...(cfg.headers ?? {}), [`X-Header-${headers.length + 1}`]: "" } })}>Add header</Button></div>
          {cfg.method !== "GET" && <div className="space-y-1"><Label>Body</Label><PillInput label="Body" multiline value={cfg.body ?? ""} onChange={(v) => set({ body: v })} pills={pills} payload={payload} placeholder='{"email": "{{trigger.user.email}}"}' /></div>}
        </div>
      );
    }
    case "connector_action":
      return <ConnectorActionForm cfg={cfg} set={set} connections={ctx.connections} meta={ctx.meta} pills={pills} payload={payload} available={ctx.connectionsAvailable} folderId={ctx.folderId} onCreated={ctx.connectionAdded} />;
    case "send_slack":
      return (
        <div className="space-y-3">
          <div className="space-y-1"><Label>Slack connection</Label>
            <Select label="Slack connection" value={cfg.connection_id ?? ""} onChange={(v) => set({ connection_id: v ? Number(v) : null })}>
              <option value="">Choose a connection…</option>{ctx.connections.filter((c) => c.kind === "slack_webhook").map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </Select>
            {!ctx.connections.some((c) => c.kind === "slack_webhook") && (
              <p className="text-xs text-muted-foreground" data-testid="slack-webhook-hint">
                This step posts through a Slack <em>incoming webhook</em>, which is not the same as a Slack connection with a bot token.{" "}
                {ctx.connections.some((c) => c.kind === "connector" && c.connector_id === "slack")
                  ? <>Your Slack connection works with <strong>Slack → Post a message</strong> in the Add a step menu; use that instead. To keep this step, add a “Slack incoming webhook” under Connections.</>
                  : <>Add a “Slack incoming webhook” under Connections, or connect Slack with a bot token and use <strong>Slack → Post a message</strong>.</>}
              </p>
            )}</div>
          <div className="space-y-1"><Label>Message</Label><PillInput label="Slack message" multiline value={cfg.message ?? ""} onChange={(v) => set({ message: v })} pills={pills} payload={payload} />
            <p className="text-xs text-muted-foreground">Plain text. Mentions and links are neutralised so user-supplied values cannot ping channels.</p></div>
        </div>
      );
    case "send_email":
      return (
        <div className="space-y-3">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1"><Label>To</Label><PillInput label="Email recipient" value={cfg.to ?? ""} onChange={(v) => set({ to: v })} pills={pills} payload={payload} />
              <p className="text-xs text-muted-foreground">One address. It must belong to an active user or to an allowed email domain.</p></div>
            <div className="space-y-1"><Label>Subject</Label><PillInput label="Email subject" value={cfg.subject ?? ""} onChange={(v) => set({ subject: v })} pills={pills} payload={payload} /></div>
          </div>
          <div className="space-y-1"><Label>Message</Label><PillInput label="Email body" multiline value={cfg.body ?? ""} onChange={(v) => set({ body: v })} pills={pills} payload={payload} /></div>
        </div>
      );
    case "log":
      return <div className="space-y-1"><Label>Message</Label><PillInput label="Message" value={cfg.message ?? ""} onChange={(v) => set({ message: v })} pills={pills} payload={payload} /></div>;
    case "condition":
      return (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm"><span>If</span>
            <Select label="Match mode" className="!w-auto" value={cfg.match} onChange={(v) => set({ match: v })}><option value="all">all</option><option value="any">any</option></Select>
            <span>of these are true:</span></div>
          <Comparisons items={cfg.conditions ?? []} onChange={(c) => set({ conditions: c })} pills={decisionPills(ctx.meta, ctx.trigger, before)} payload={payload} />
          <p className="text-xs text-muted-foreground">Fields users can edit themselves (names, phone, title…) are not offered: they cannot drive decisions.</p>
        </div>
      );
    case "stop":
      return (
        <div className="grid gap-3 md:grid-cols-[12rem_1fr]">
          <div className="space-y-1"><Label>Finish as</Label><Select label="Outcome" value={cfg.outcome} onChange={(v) => set({ outcome: v })}><option value="success">Success</option><option value="failed">Failed</option></Select></div>
          <div className="space-y-1"><Label>Message</Label><PillInput label="Stop message" value={cfg.message ?? ""} onChange={(v) => set({ message: v })} pills={pills} payload={payload} /></div>
        </div>
      );
    case "for_each_member":
      return (
        <div className="grid gap-3 md:grid-cols-[1fr_10rem]">
          <div className="space-y-1"><Label>Group</Label>
            <Select label="Loop group" value={cfg.group_id ?? ""} onChange={(v) => set({ group_id: v ? Number(v) : null })}>
              <option value="">Choose a group…</option>{ctx.groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </Select>
            <p className="text-xs text-muted-foreground">The steps below run once per member. Use “Current member” datapills inside. Loops cannot be nested.</p></div>
          <div className="space-y-1"><Label>Max members (1–100)</Label>
            <Input aria-label="Loop limit" type="number" min={1} max={100} className="h-10" value={cfg.limit ?? 50} onChange={(e) => set({ limit: Number(e.target.value) })} /></div>
        </div>
      );
    case "for_each_item":
      return (
        <div className="grid gap-3 md:grid-cols-[1fr_10rem]">
          <div className="space-y-1"><Label>List</Label>
            <PillInput label="Loop list" value={cfg.list ?? ""} onChange={(v) => set({ list: v })} pills={pills} payload={payload} />
            <p className="text-xs text-muted-foreground">One datapill or formula that gives a list, such as {"{{= split(trigger.payload.ids, \",\") }}"}. The steps below run once per item; use “Current item” inside. Too many items fails the step. Loops cannot be nested.</p></div>
          <div className="space-y-1"><Label>Max items (1–100)</Label>
            <Input aria-label="Loop limit" type="number" min={1} max={100} className="h-10" value={cfg.limit ?? 50} onChange={(e) => set({ limit: Number(e.target.value) })} /></div>
        </div>
      );
    case "handle_errors":
      return (
        <p className="text-sm text-muted-foreground" data-testid="handle-errors-help">
          If any step in <strong>Monitored steps</strong> fails for good (after its retries), the rest of those steps are skipped and the <strong>If any of them fails</strong> steps run
          with <code>error.message</code> and <code>error.step_id</code>. The job then carries on after this block and is not marked failed. Errors outside the block still go to the recipe-level handler.
        </p>
      );
    case "approval":
      return (
        <div className="grid gap-3 md:grid-cols-[1fr_12rem]">
          <div className="space-y-1"><Label>Question for the approver</Label><PillInput label="Approval message" value={cfg.message ?? ""} onChange={(v) => set({ message: v })} pills={pills} payload={payload} /></div>
          <div className="space-y-1"><Label>Give up after (hours, 1–168)</Label>
            <Input aria-label="Approval timeout hours" type="number" min={1} max={168} className="h-10" value={cfg.timeout_hours ?? 24} onChange={(e) => set({ timeout_hours: Number(e.target.value) })} />
            <p className="text-xs text-muted-foreground">Approved runs “Then”; denied or timed out runs “Otherwise”.</p></div>
        </div>
      );
    case "lookup_row": {
      const tables = ctx.meta.lookup_tables ?? [];
      const t = tables.find((x) => x.name === cfg.table);
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1"><Label>Table</Label>
            <Select label="Lookup table" value={cfg.table ?? ""} onChange={(v) => { const n = tables.find((x) => x.name === v); set({ table: v, column: n?.key_column ?? n?.columns[0]?.name ?? "" }); }}>
              <option value="">Choose a table…</option>{tables.map((x) => <option key={x.name} value={x.name}>{x.name}</option>)}
            </Select>
            {tables.length === 0 && <p className="text-xs text-muted-foreground">Create a table under Recipes › Lookup tables first.</p>}</div>
          <div className="space-y-1"><Label>Find the row where</Label>
            <Select label="Lookup column" value={cfg.column ?? ""} onChange={(v) => set({ column: v })}>
              {(t?.columns ?? []).map((c) => <option key={c.name} value={c.name}>{c.name}{c.name === t?.key_column ? " (key)" : ""}</option>)}
            </Select></div>
          <div className="space-y-1 sm:col-span-2"><Label>equals</Label>
            <PillInput label="Lookup value" value={cfg.value ?? ""} onChange={(v) => set({ value: v })} pills={decisionPills(ctx.meta, ctx.trigger, before)} payload={payload} />
            <p className="text-xs text-muted-foreground">Outputs: found, count, and the first matching row (<code>row.column</code>). Text the user can edit themselves cannot be the key.
              {t && !t.admin_managed && " This table can be written by recipes, so what it returns cannot be used in decisions or to change accounts."}</p></div>
        </div>
      );
    }
    case "lookup_write": {
      const tables = (ctx.meta.lookup_tables ?? []).filter((x) => !x.admin_managed);
      const t = tables.find((x) => x.name === cfg.table);
      const values: Record<string, string> = cfg.values ?? {};
      const setVal = (col: string, v: string) => { const n = { ...values }; if (v === "") delete n[col]; else n[col] = v; set({ values: n }); };
      return (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1"><Label>Table</Label>
              <Select label="Lookup table" value={cfg.table ?? ""} onChange={(v) => { const n = tables.find((x) => x.name === v); set({ table: v, values: {}, action: n?.key_column ? "upsert" : "add" }); }}>
                <option value="">Choose a table…</option>{tables.map((x) => <option key={x.name} value={x.name}>{x.name}</option>)}
              </Select>
              {tables.length === 0 && <p className="text-xs text-muted-foreground">Only tables set to “Administrators and recipes” can be written by a recipe.</p>}</div>
            <div className="space-y-1"><Label>Action</Label>
              <Select label="Lookup action" value={cfg.action ?? "upsert"} onChange={(v) => set({ action: v })}>
                <option value="add">Add a row</option>{t?.key_column && <option value="upsert">Add or update the row with the same key</option>}{t?.key_column && <option value="delete">Delete the row with this key</option>}
              </Select></div>
          </div>
          {cfg.action === "delete" ? (
            <div className="space-y-1"><Label>Key ({t?.key_column ?? "key"}) of the row to delete</Label>
              <PillInput label="Lookup key" value={cfg.key ?? ""} onChange={(v) => set({ key: v })} pills={pills} payload={payload} /></div>
          ) : (
            <div className="space-y-2">
              {(t?.columns ?? []).map((c) => (
                <div key={c.name} className="space-y-1"><Label>{c.name}{c.name === t?.key_column ? " (key)" : ""} <span className="font-normal text-muted-foreground">{c.type}</span></Label>
                  <PillInput label={`Value for ${c.name}`} value={values[c.name] ?? ""} onChange={(v) => setVal(c.name, v)} pills={pills} payload={payload} placeholder={cfg.action === "upsert" && c.name !== t?.key_column ? "Leave empty to keep the current value" : ""} /></div>))}
              <p className="text-xs text-muted-foreground">Values are converted to the column type. Anything stored here, including text the user typed, is treated as user-editable when read back. A test run writes nothing.</p>
            </div>)}
        </div>
      );
    }
    case "set_variable":
      return (
        <div className="grid gap-3 md:grid-cols-[12rem_1fr]">
          <div className="space-y-1"><Label>Variable name</Label>
            <Input aria-label="Variable name" className="h-10" placeholder="total" value={cfg.name ?? ""} onChange={(e) => set({ name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_").slice(0, 32) })} />
            <p className="text-xs text-muted-foreground">Use it later as <code>{"{{vars." + (cfg.name || "name") + "}}"}</code>. Setting the same name again replaces it.</p></div>
          <div className="space-y-1"><Label>Value</Label>
            <PillInput label="Variable value" value={cfg.value ?? ""} onChange={(v) => set({ value: v })} pills={decisionPills(ctx.meta, ctx.trigger, before)} payload={payload} placeholder="Text, a datapill or {{= formula }}" />
            <p className="text-xs text-muted-foreground">A value that is exactly one formula keeps its type (a number stays a number). Text the user can edit themselves, such as their name, cannot be stored.</p></div>
        </div>
      );
    case "call_recipe": {
      const callee = ctx.meta.callable_recipes?.find((r) => r.id === cfg.recipe_id);
      return (
        <div className="space-y-3">
          <div className="space-y-1"><Label>Recipe to call</Label>
            <Select label="Recipe to call" value={cfg.recipe_id ?? ""} onChange={(v) => set({ recipe_id: v ? Number(v) : null, inputs: {} })}>
              <option value="">Choose a recipe…</option>{(ctx.meta.callable_recipes ?? []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </Select>
            {(ctx.meta.callable_recipes ?? []).length === 0 && <p className="text-xs text-muted-foreground">No callable recipes yet: publish and enable a recipe whose trigger is “Called by another recipe”.</p>}</div>
          {(callee?.inputs ?? []).map((i) => (
            <div key={i.name} className="space-y-1"><Label>{`Input: ${i.name} (${i.type}${i.required ? "" : ", optional"})`}</Label>
              <PillInput label={`Call input ${i.name}`} value={cfg.inputs?.[i.name] ?? ""} onChange={(v) => set({ inputs: { ...(cfg.inputs ?? {}), [i.name]: v } })} pills={pills} payload={payload} /></div>
          ))}
          {callee && <p className="text-xs text-muted-foreground">The job waits for the called recipe, then its returned data ({callee.outputs.join(", ") || "none"}) is available as “Call a recipe” datapills. A recipe cannot call itself, directly or through others, and calls go at most 5 levels deep.</p>}
        </div>
      );
    }
    case "return_data":
      return (
        <div className="space-y-3">
          {(ctx.callOutputs ?? []).map((n) => (
            <div key={n} className="space-y-1"><Label>{`Output: ${n}`}</Label>
              <PillInput label={`Return ${n}`} value={cfg.values?.[n] ?? ""} onChange={(v) => set({ values: { ...(cfg.values ?? {}), [n]: v } })} pills={pills} payload={payload} /></div>
          ))}
          {(ctx.callOutputs ?? []).length === 0 && <p className="text-xs text-muted-foreground">Declare the outputs this recipe returns in its trigger first.</p>}
          <p className="text-xs text-muted-foreground">Gives these values back to the recipe that called this one and ends this job.</p>
        </div>
      );
    case "wait":
      return (
        <div className="grid gap-3 md:grid-cols-[10rem_10rem]">
          <div className="space-y-1"><Label>Wait for</Label>
            <Input aria-label="Wait amount" type="number" min={1} className="h-10" value={cfg.amount ?? 5} onChange={(e) => set({ amount: Number(e.target.value) })} /></div>
          <div className="space-y-1"><Label>Unit</Label>
            <Select label="Wait unit" value={cfg.unit ?? "minutes"} onChange={(v) => set({ unit: v })}><option value="minutes">Minutes</option><option value="hours">Hours</option><option value="days">Days</option></Select></div>
          <p className="text-xs text-muted-foreground md:col-span-2">The job pauses (up to 7 days) and carries on with the next step. A test run never waits. The pause does not count against the job's run-time limit.</p>
        </div>
      );
    case "throttle":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1"><Label>Let through at most</Label>
            <Input aria-label="Throttle max runs" type="number" min={1} max={1000} className="h-10" value={cfg.max_runs ?? 10} onChange={(e) => set({ max_runs: Number(e.target.value) })} /></div>
          <div className="space-y-1"><Label>Per (minutes, 1–1440)</Label>
            <Input aria-label="Throttle window minutes" type="number" min={1} max={1440} className="h-10" value={cfg.per_minutes ?? 60} onChange={(e) => set({ per_minutes: Number(e.target.value) })} /></div>
          <div className="space-y-1 sm:col-span-2"><Label>When the limit is reached</Label>
            <Select label="Throttle when full" value={cfg.when_full ?? "wait"} onChange={(v) => set({ when_full: v })}><option value="wait">Wait for a free slot</option><option value="stop">Drop the job (cancel it)</option></Select></div>
          <p className="text-xs text-muted-foreground sm:col-span-2">Counts every job of this recipe that passed this step in the window. Put it before the steps you want to protect, for example before an email or an HTTP call. A test run is never limited.</p>
        </div>
      );
    default:
      return null;
  }
}

function CallSignature({ cfg, set }: { cfg: Record<string, any>; set: (p: Record<string, any>) => void }) {
  const inputs: { name: string; type: string; required: boolean }[] = cfg.inputs ?? [];
  const upd = (i: number, patch: Record<string, any>) => set({ inputs: inputs.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
  return (
    <div className="space-y-2" data-testid="call-signature">
      <Label>Inputs this recipe accepts</Label>
      {inputs.map((x, i) => (
        <div key={i} className="grid grid-cols-[1fr_8rem_auto_auto] items-center gap-2">
          <Input aria-label={`Input name ${i + 1}`} className="h-10" placeholder="name (lowercase)" value={x.name} onChange={(e) => upd(i, { name: e.target.value })} />
          <Select label={`Input type ${i + 1}`} value={x.type} onChange={(v) => upd(i, { type: v })}>{["text", "number", "boolean", "list", "object"].map((t) => <option key={t} value={t}>{t}</option>)}</Select>
          <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={x.required} onChange={(e) => upd(i, { required: e.target.checked })} />required</label>
          <Button type="button" variant="outline" size="sm" aria-label={`Remove input ${i + 1}`} onClick={() => set({ inputs: inputs.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></Button>
        </div>
      ))}
      <Button type="button" variant="secondary" size="sm" onClick={() => set({ inputs: [...inputs, { name: "", type: "text", required: true }] })}>Add input</Button>
      <div className="space-y-1"><Label htmlFor="call-outputs">Outputs it returns (names, comma separated)</Label>
        <Input id="call-outputs" className="h-10" placeholder="total, user_id" value={(cfg.outputs ?? []).join(", ")}
          onChange={(e) => set({ outputs: e.target.value.split(",").map((n) => n.trim()).filter(Boolean) })} />
        <p className="text-xs text-muted-foreground">Inputs arrive as “payload” datapills. Use a “Return data” step to give the outputs back.</p></div>
    </div>
  );
}

export function TriggerCard({ def, meta, groups, setTrigger }: { def: Definition; meta: RecipeMeta; groups: Group[]; setTrigger: (patch: Partial<Definition["trigger"]>) => void }) {
  const trig = meta.triggers.find((t) => t.type === def.trigger.type)!;
  const tcfg = (patch: Record<string, any>) => setTrigger({ config: { ...def.trigger.config, ...patch } });
  const triggerPills = trig.fields;
  const filterPills = decisionPills(meta, def.trigger.type, []);
  const isGroupTrig = def.trigger.type.startsWith("group.member_");
  return (
    <Card className="border-0 shadow-none" data-testid="trigger-card">
        <CardContent className="space-y-3 p-0">
          <Select label="Trigger" value={def.trigger.type} onChange={(v) => setTrigger({ type: v, config: v === "schedule" ? { interval_minutes: 60 } : v === "call" ? { inputs: [], outputs: [] } : v === "login.failed" ? { min_failures: 3 } : v === "user.attribute_changed" ? { attribute: meta.managed_attributes[0]?.key ?? "" } : {}, filter: [] })}>
            {meta.triggers.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}
          </Select>
          <p className="text-sm text-muted-foreground">{trig.description}</p>
          {isGroupTrig && (
            <div className="space-y-1"><Label>Only for group</Label>
              <Select label="Group filter" value={def.trigger.config.group_id ?? ""} onChange={(v) => tcfg({ group_id: v ? Number(v) : null })}><option value="">Any group</option>{groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</Select></div>
          )}
          {def.trigger.type === "user.attribute_changed" && (
            <div className="space-y-1"><Label>Attribute</Label>
              <Select label="Attribute to watch" value={def.trigger.config.attribute ?? ""} onChange={(v) => tcfg({ attribute: v })}>{meta.managed_attributes.map((a) => <option key={a.key} value={a.key}>{a.display_name}</option>)}</Select>
              <div className="grid gap-3 pt-2 md:grid-cols-2">
                <div className="space-y-1"><Label htmlFor="t-from">Only when it changes from (optional)</Label><Input id="t-from" placeholder="any value" value={def.trigger.config.from_value ?? ""} onChange={(e) => tcfg({ from_value: e.target.value === "" ? null : e.target.value })} /></div>
                <div className="space-y-1"><Label htmlFor="t-to">…to (optional)</Label><Input id="t-to" placeholder="any value" value={def.trigger.config.to_value ?? ""} onChange={(e) => tcfg({ to_value: e.target.value === "" ? null : e.target.value })} /></div>
              </div></div>
          )}
          {def.trigger.type === "call" && <CallSignature cfg={def.trigger.config} set={tcfg} />}
          {def.trigger.type === "login.failed" && (
            <div className="space-y-1"><Label htmlFor="t-min">Minimum consecutive failures</Label><Input id="t-min" type="number" min={1} max={100} className="w-32" value={def.trigger.config.min_failures ?? 1} onChange={(e) => tcfg({ min_failures: Number(e.target.value) })} /></div>
          )}
          {def.trigger.type === "schedule" && (
            <div className="space-y-1"><Label htmlFor="t-int">Run every (minutes, 5 to 1440)</Label><Input id="t-int" type="number" min={5} max={1440} className="w-32" value={def.trigger.config.interval_minutes ?? 60} onChange={(e) => tcfg({ interval_minutes: Number(e.target.value) })} /></div>
          )}
          <details open={def.trigger.filter.length > 0}>
            <summary className="cursor-pointer text-sm text-muted-foreground">Only continue if… (optional filter)</summary>
            <div className="mt-2"><Comparisons items={def.trigger.filter} onChange={(f) => setTrigger({ filter: f })} pills={filterPills} payload={trig.payload_pills} /></div>
          </details>
          {trig.fields.length > 0 && <p className="text-xs text-muted-foreground">Datapills from this trigger: {triggerPills.slice(0, 6).map((p) => p.label).join(", ")}{triggerPills.length > 6 ? ", …" : ""}</p>}
        </CardContent>
      </Card>
  );
}
