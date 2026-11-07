"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fieldClass } from "@/components/bits";
import { JobView, PillInput, RecipeTabs } from "@/components/recipe-bits";
import { http, qs, type Page } from "@/lib/http";
import {
  OPERATOR_LABELS, allSteps, decisionPills, nextStepId, stepPills, stepsBefore,
  type Comparison, type Connection, type Definition, type Job, type Pill, type RecipeMeta, type RecipeSummary, type StepNode,
} from "@/lib/recipes";
import type { Group, User } from "@/lib/types";

type Ctx = {
  meta: RecipeMeta; groups: Group[]; connections: Connection[]; connectionsAvailable: boolean; trigger: string; root: StepNode[]; other?: StepNode[]; handler?: boolean; inLoop?: boolean;
};

const USER_PILL = "{{trigger.user.id}}";

function defaultConfig(type: string, ctx: Ctx): Record<string, any> {
  switch (type) {
    case "add_to_group": case "remove_from_group": return { group_id: ctx.groups[0]?.id ?? null, user: USER_PILL };
    case "set_attribute": return { user: USER_PILL, attribute: ctx.meta.managed_attributes[0]?.key ?? "", value: "" };
    case "activate_user": case "deactivate_user": return { user: USER_PILL };
    case "http_request": return { method: "POST", url: "https://", headers: {}, body: "", connection_id: null };
    case "log": return { message: "" };
    case "condition": return { match: "all", conditions: [{ left: "trigger.event.type", operator: "is_set", value: "" }] };
    case "stop": return { outcome: "success", message: "" };
    case "for_each_member": return { group_id: ctx.groups[0]?.id ?? null, limit: 50 };
    case "approval": return { message: "", timeout_hours: 24 };
    default: return {};
  }
}

function mapSteps(steps: StepNode[], id: string, fn: (s: StepNode) => StepNode | null): StepNode[] {
  return steps.flatMap((s) => {
    if (s.id === id) { const r = fn(s); return r ? [r] : []; }
    return [{ ...s, then: s.then ? mapSteps(s.then, id, fn) : s.then, else: s.else ? mapSteps(s.else, id, fn) : s.else }];
  });
}
function moveIn(steps: StepNode[], id: string, dir: -1 | 1): StepNode[] {
  const i = steps.findIndex((s) => s.id === id);
  if (i >= 0) {
    const j = i + dir;
    if (j < 0 || j >= steps.length) return steps;
    const copy = [...steps];
    [copy[i], copy[j]] = [copy[j], copy[i]];
    return copy;
  }
  return steps.map((s) => ({ ...s, then: s.then ? moveIn(s.then, id, dir) : s.then, else: s.else ? moveIn(s.else, id, dir) : s.else }));
}

function Select({ label, value, onChange, children, className }: { label: string; value: string | number; onChange: (v: string) => void; children: React.ReactNode; className?: string }) {
  return <select aria-label={label} className={fieldClass + (className ? " " + className : "")} value={value} onChange={(e) => onChange(e.target.value)}>{children}</select>;
}

function Comparisons({ items, onChange, pills, payload }: { items: Comparison[]; onChange: (c: Comparison[]) => void; pills: Pill[]; payload: boolean }) {
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

function StepForm({ step, ctx, onChange }: { step: StepNode; ctx: Ctx; onChange: (s: StepNode) => void }) {
  const cfg = step.config;
  const set = (patch: Record<string, any>) => onChange({ ...step, config: { ...cfg, ...patch } });
  const before = stepsBefore(ctx.root, step.id);
  const errorPills: Pill[] = ctx.handler ? [{ path: "error.message", label: "Error message" }, { path: "error.step_id", label: "Failed step" }] : [];
  const loopPills: Pill[] = ctx.inLoop ? [
    { path: "loop.user.id", label: "Current member: id" }, { path: "loop.user.email", label: "Current member: email" },
    { path: "loop.user.username", label: "Current member: username" }, { path: "loop.user.status", label: "Current member: status" },
    { path: "loop.index", label: "Loop: position (1-based)" }, { path: "loop.total", label: "Loop: member count" },
  ] : [];
  const pills = [...(ctx.meta.triggers.find((t) => t.type === ctx.trigger)?.fields ?? []), ...stepPills(ctx.meta, before), ...errorPills, ...loopPills];
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
              <option value="">None (no credentials)</option>{ctx.connections.map((c) => <option key={c.id} value={c.id}>{c.name} → {c.allowed_host}</option>)}
            </Select>
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
    case "approval":
      return (
        <div className="grid gap-3 md:grid-cols-[1fr_12rem]">
          <div className="space-y-1"><Label>Question for the approver</Label><PillInput label="Approval message" value={cfg.message ?? ""} onChange={(v) => set({ message: v })} pills={pills} payload={payload} /></div>
          <div className="space-y-1"><Label>Give up after (hours, 1–168)</Label>
            <Input aria-label="Approval timeout hours" type="number" min={1} max={168} className="h-10" value={cfg.timeout_hours ?? 24} onChange={(e) => set({ timeout_hours: Number(e.target.value) })} />
            <p className="text-xs text-muted-foreground">Approved runs “Then”; denied or timed out runs “Otherwise”.</p></div>
        </div>
      );
    default:
      return null;
  }
}

function StepList({ steps, ctx, onChange, depth }: { steps: StepNode[]; ctx: Ctx; onChange: (s: StepNode[]) => void; depth: number }) {
  const addable = ctx.meta.steps.filter((s) => (s.type !== "condition" && s.type !== "approval") || depth < ctx.meta.limits.max_nesting)
    .filter((s) => !(s.type === "for_each_member" && (depth > 0 || ctx.handler)) && !(s.type === "approval" && ctx.handler));
  const [type, setType] = useState("log");
  const root = ctx.root;
  return (
    <div className={depth > 0 ? "ml-4 space-y-3 border-l-2 pl-4" : "space-y-3"}>
      {steps.map((s, i) => {
        const info = ctx.meta.steps.find((m) => m.type === s.type);
        const isAction = info?.kind === "action";
        const replace = (n: StepNode) => onChange(steps.map((x) => (x.id === s.id ? n : x)));
        return (
          <Card key={s.id} data-testid="step-card">
            <CardHeader className="flex-row items-center justify-between space-y-0 py-3">
              <CardTitle className="text-base">{i + 1}. {info?.label ?? s.type} <code className="ml-1 text-xs font-normal text-muted-foreground">{s.id}</code></CardTitle>
              <div className="flex gap-1">
                <Button type="button" size="sm" variant="ghost" aria-label="Move up" disabled={i === 0} onClick={() => onChange(moveIn(steps, s.id, -1))}><ArrowUp className="h-4 w-4" /></Button>
                <Button type="button" size="sm" variant="ghost" aria-label="Move down" disabled={i === steps.length - 1} onClick={() => onChange(moveIn(steps, s.id, 1))}><ArrowDown className="h-4 w-4" /></Button>
                <Button type="button" size="sm" variant="ghost" aria-label="Delete step" onClick={() => onChange(steps.filter((x) => x.id !== s.id))}><Trash2 className="h-4 w-4" /></Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <StepForm step={s} ctx={ctx} onChange={replace} />
              {isAction && (
                <details className="text-sm">
                  <summary className="cursor-pointer text-muted-foreground">Error handling</summary>
                  <div className="mt-2 grid gap-3 md:grid-cols-2">
                    <div className="space-y-1"><Label>If this step fails</Label>
                      <Select label="On error" value={s.on_error ?? "fail"} onChange={(v) => replace({ ...s, on_error: v as "fail" | "continue" })}><option value="fail">Fail the job</option><option value="continue">Continue with the next step</option></Select></div>
                    <div className="space-y-1"><Label>Attempts (retries use exponential back-off)</Label>
                      <Select label="Attempts" value={s.max_attempts ?? 3} onChange={(v) => replace({ ...s, max_attempts: Number(v) })}>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}</Select></div>
                  </div>
                </details>
              )}
              {(s.type === "condition" || s.type === "approval") && (
                <div className="space-y-3">
                  <div><div className="mb-1 text-sm font-medium">{s.type === "approval" ? "If approved" : "Then"}</div><StepList steps={s.then ?? []} ctx={ctx} depth={depth + 1} onChange={(n) => replace({ ...s, then: n })} /></div>
                  <div><div className="mb-1 text-sm font-medium">{s.type === "approval" ? "If denied or no answer in time" : "Otherwise"}</div><StepList steps={s.else ?? []} ctx={ctx} depth={depth + 1} onChange={(n) => replace({ ...s, else: n })} /></div>
                </div>
              )}
              {s.type === "for_each_member" && (
                <div><div className="mb-1 text-sm font-medium">For each member</div>
                  <StepList steps={s.then ?? []} ctx={{ ...ctx, inLoop: true }} depth={depth + 1} onChange={(n) => replace({ ...s, then: n })} /></div>
              )}
            </CardContent>
          </Card>
        );
      })}
      <div className="flex items-center gap-2">
        <Select label={depth === 0 ? "New step type" : "New branch step type"} className="!w-60" value={type} onChange={setType}>
          <optgroup label="Actions">{addable.filter((m) => m.kind === "action").map((m) => <option key={m.type} value={m.type}>{m.label}</option>)}</optgroup>
          <optgroup label="Control">{addable.filter((m) => m.kind === "control").map((m) => <option key={m.type} value={m.type}>{m.label}</option>)}</optgroup>
        </Select>
        <Button type="button" variant="secondary" size="sm" disabled={allSteps(root).length >= ctx.meta.limits.max_steps}
          onClick={() => { const n: StepNode = { id: nextStepId([...root, ...(ctx.other ?? [])]), type, config: defaultConfig(type, ctx), on_error: "fail", max_attempts: 3 }; if (type === "condition" || type === "approval") { n.then = []; n.else = []; } if (type === "for_each_member") n.then = []; onChange([...steps, n]); }}>
          <Plus className="mr-1 h-4 w-4" /> Add step
        </Button>
      </div>
    </div>
  );
}

export default function RecipeBuilderPage() {
  const { id } = useParams<{ id: string }>();
  const [recipe, setRecipe] = useState<RecipeSummary | null>(null);
  const [def, setDef] = useState<Definition | null>(null);
  const [name, setName] = useState("");
  const [meta, setMeta] = useState<RecipeMeta | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [connAvail, setConnAvail] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [test, setTest] = useState({ user_id: "", group_id: "", payload: "{}" });
  const [result, setResult] = useState<Job | null>(null);
  const [versions, setVersions] = useState<{ version: number; published_at: string }[]>([]);
  const [recent, setRecent] = useState<Job[]>([]);

  const adopt = (r: RecipeSummary) => { setRecipe(r); setName(r.name); if (r.draft) setDef(r.draft); setDirty(false); };
  const load = useCallback(() => {
    http<RecipeSummary>(`/admin/recipes/${id}`).then(adopt).catch((e) => setMsg({ ok: false, text: e.message }));
    http<{ items: { version: number; published_at: string }[] }>(`/admin/recipes/${id}/versions`).then((v) => setVersions(v.items)).catch(() => {});
    http<Page<Job>>(`/admin/recipes/jobs${qs({ recipe_id: id, page_size: 5 })}`).then((j) => setRecent(j.items)).catch(() => {});
  }, [id]);
  useEffect(load, [load]);
  useEffect(() => {
    http<RecipeMeta>("/admin/recipes/meta").then(setMeta).catch(() => {});
    http<Page<Group>>(`/admin/groups${qs({ page: 1, page_size: 100 })}`).then((r) => setGroups(r.items.filter((g) => !g.is_system_group))).catch(() => {});
    http<Page<User>>(`/admin/users${qs({ page: 1, page_size: 100 })}`).then((r) => setUsers(r.items)).catch(() => {});
    http<{ items: Connection[] }>("/admin/recipe-connections").then((r) => setConnections(r.items)).catch(() => {});
    http<{ connections_available: boolean }>("/admin/recipes/status").then((s) => setConnAvail(s.connections_available)).catch(() => {});
  }, []);

  const ctx: Ctx | null = useMemo(() => (meta && def ? { meta, groups, connections, connectionsAvailable: connAvail, trigger: def.trigger.type, root: def.steps } : null), [meta, def, groups, connections, connAvail]);
  if (!recipe || !def || !meta || !ctx) return <div><PageHeader title="Recipe" />{msg && <Alert variant="destructive"><AlertDescription>{msg.text}</AlertDescription></Alert>}</div>;

  const trig = meta.triggers.find((t) => t.type === def.trigger.type)!;
  const edit = (d: Definition) => { setDef(d); setDirty(true); };
  const setTrigger = (patch: Partial<Definition["trigger"]>) => edit({ ...def, trigger: { ...def.trigger, ...patch } });
  const tcfg = (patch: Record<string, any>) => setTrigger({ config: { ...def.trigger.config, ...patch } });
  const triggerPills = trig.fields;
  const filterPills = decisionPills(meta, def.trigger.type, []);
  const needsUser = !["schedule", "webhook"].includes(def.trigger.type);
  const isGroupTrig = def.trigger.type.startsWith("group.member_");

  async function act(fn: () => Promise<unknown>, ok?: string) {
    setMsg(null);
    try { await fn(); if (ok) setMsg({ ok: true, text: ok }); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }
  const save = async () => { const r = await http<RecipeSummary>(`/admin/recipes/${id}`, { method: "PUT", body: { name, description: recipe.description, definition: def } }); adopt(r); load(); return r; };

  return (
    <div>
      <PageHeader title={recipe.name}>
        <Badge tone={recipe.enabled ? "good" : "neutral"}>{recipe.enabled ? "enabled" : "disabled"}</Badge>
        <Badge tone="info">{recipe.published_version ? `published v${recipe.published_version}` : "not published"}</Badge>
      </PageHeader>
      <RecipeTabs />
      <p className="mb-4 text-sm"><Link className="underline underline-offset-4" href="/admin/recipes">← All recipes</Link></p>
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
      {secret && (
        <Alert variant="warning" className="mb-4" data-testid="webhook-secret"><AlertDescription>
          Webhook signing secret (shown only once, copy it now): <code className="break-all">{secret}</code>
          <div className="mt-1 text-xs">POST JSON to <code>{recipe.webhook_path}</code> with headers <code>X-IdentityForge-Timestamp</code> (unix seconds) and <code>X-IdentityForge-Signature: v1=HMAC_SHA256(secret, timestamp + "." + body)</code> in hex. Requests older than 5 minutes are refused.</div>
          <Button size="sm" variant="outline" className="mt-2" onClick={() => setSecret(null)}>I have copied it</Button>
        </AlertDescription></Alert>
      )}

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="space-y-1"><Label htmlFor="rb-name">Recipe name</Label><Input id="rb-name" className="w-72" maxLength={100} value={name} onChange={(e) => { setName(e.target.value); setDirty(true); }} /></div>
        <Button disabled={!dirty || !name.trim()} onClick={() => act(save, "Draft saved")}>Save draft</Button>
        <Button variant="secondary" disabled={def.steps.length === 0} onClick={() => act(async () => { if (dirty) await save(); const r = await http<RecipeSummary>(`/admin/recipes/${id}/publish`, { method: "POST" }); adopt(r); if (r.webhook_secret) setSecret(r.webhook_secret); load(); }, "Published as a new immutable version")}>Publish</Button>
        {recipe.enabled
          ? <Button variant="outline" onClick={() => act(async () => { adopt(await http<RecipeSummary>(`/admin/recipes/${id}/disable`, { method: "POST" })); load(); }, "Recipe disabled")}>Disable</Button>
          : <Button variant="outline" disabled={!recipe.published_version} onClick={() => act(async () => { adopt(await http<RecipeSummary>(`/admin/recipes/${id}/enable`, { method: "POST" })); load(); }, "Recipe enabled")}>Enable</Button>}
        {recipe.published_trigger_type === "manual" && recipe.enabled && <Button variant="outline" onClick={() => act(async () => { await http(`/admin/recipes/${id}/run`, { method: "POST", body: { payload: safeJson(test.payload), user_id: test.user_id ? Number(test.user_id) : null } }); load(); }, "Run queued; the worker will pick it up")}>Run now</Button>}
        {dirty && <span className="text-sm text-amber-600">Unsaved changes</span>}
        {!dirty && recipe.has_unpublished_changes && recipe.published_version && <span className="text-sm text-amber-600">Draft differs from the published version</span>}
      </div>

      <Card className="mb-4" data-testid="trigger-card">
        <CardHeader className="py-3"><CardTitle className="text-base">When this happens (trigger)</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <Select label="Trigger" value={def.trigger.type} onChange={(v) => setTrigger({ type: v, config: v === "schedule" ? { interval_minutes: 60 } : v === "login.failed" ? { min_failures: 3 } : v === "user.attribute_changed" ? { attribute: meta.managed_attributes[0]?.key ?? "" } : {}, filter: [] })}>
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

      <h2 className="mb-2 text-lg font-semibold">Then do these steps</h2>
      <StepList steps={def.steps} ctx={{ ...ctx, other: def.on_error ?? [] }} depth={0} onChange={(s) => edit({ ...def, steps: s })} />

      <h2 className="mb-1 mt-6 text-lg font-semibold">If a step fails</h2>
      <p className="mb-2 text-sm text-muted-foreground">Optional. These steps run after a step fails for good (after its retries), with the error message and failed step as datapills. The job is still recorded as failed.</p>
      <div data-testid="error-handler">
        <StepList steps={def.on_error ?? []} ctx={{ ...ctx, root: def.on_error ?? [], other: def.steps, handler: true }} depth={0} onChange={(s) => edit({ ...def, on_error: s })} />
      </div>

      <Card className="mt-6" data-testid="test-card">
        <CardHeader className="py-3"><CardTitle className="text-base">Test (dry run of the draft)</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">Evaluates conditions and datapills for real and checks every target, but changes nothing and sends no request.</p>
          <div className="grid gap-3 md:grid-cols-3">
            {needsUser && <div className="space-y-1"><Label>Sample user</Label><Select label="Sample user" value={test.user_id} onChange={(v) => setTest({ ...test, user_id: v })}><option value="">Choose a user…</option>{users.map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}</Select></div>}
            {isGroupTrig && <div className="space-y-1"><Label>Sample group</Label><Select label="Sample group" value={test.group_id} onChange={(v) => setTest({ ...test, group_id: v })}><option value="">Choose a group…</option>{groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</Select></div>}
            {trig.payload_pills && <div className="space-y-1 md:col-span-2"><Label htmlFor="t-payload">Sample payload (JSON)</Label><textarea id="t-payload" rows={3} className={fieldClass + " h-auto font-mono"} value={test.payload} onChange={(e) => setTest({ ...test, payload: e.target.value })} /></div>}
          </div>
          <Button disabled={def.steps.length === 0} onClick={() => act(async () => {
            if (dirty) await save();
            setResult(await http<Job>(`/admin/recipes/${id}/test`, { method: "POST", body: { user_id: test.user_id ? Number(test.user_id) : null, group_id: test.group_id ? Number(test.group_id) : null, payload: safeJson(test.payload) } }));
            load();
          })}>Run test</Button>
          {result && <JobView job={result} />}
        </CardContent>
      </Card>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <Card><CardHeader className="py-3"><CardTitle className="text-base">Recent runs</CardTitle></CardHeader><CardContent className="text-sm">
          {recent.length === 0 ? <span className="text-muted-foreground">No runs yet.</span> : <ul className="space-y-1">{recent.map((j) => <li key={j.id}>#{j.id} · {j.status}{j.mode === "dry_run" ? " (test)" : ""}</li>)}</ul>}
          <Link className="mt-2 inline-block underline underline-offset-4" href="/admin/recipes/jobs">Open job history</Link>
        </CardContent></Card>
        <Card><CardHeader className="py-3"><CardTitle className="text-base">Versions</CardTitle></CardHeader><CardContent className="text-sm">
          {versions.length === 0 ? <span className="text-muted-foreground">Nothing published yet.</span> : <ul className="space-y-1">{versions.map((v) => <li key={v.version}>v{v.version} · {new Date(v.published_at).toLocaleString()}</li>)}</ul>}
          {recipe.webhook_path && <p className="mt-2 break-all text-xs text-muted-foreground">Webhook: {recipe.webhook_path} {recipe.webhook_secret_set ? "(secret set)" : ""}</p>}
        </CardContent></Card>
      </div>
    </div>
  );
}

function safeJson(s: string): Record<string, unknown> {
  try { const v = JSON.parse(s || "{}"); return v && typeof v === "object" && !Array.isArray(v) ? v : {}; } catch { return {}; }
}
