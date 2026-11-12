"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fieldClass } from "@/components/bits";
import { JobView, RecipeTabs } from "@/components/recipe-bits";
import { Studio } from "@/components/recipe-editor/studio";
import { FunctionsContext } from "@/components/recipe-editor/pill-context";
import { Select, type Ctx } from "@/components/recipe-editor/forms";
import { http, qs, type Page } from "@/lib/http";
import { availableConnection, type Connection, type Definition, type Job, type RecipeMeta, type RecipeSummary, type RecipeFolder } from "@/lib/recipes";
import type { Group, User } from "@/lib/types";


export function RecipeBuilder() {
  const { id } = useParams<{ id: string }>();
  const [recipe, setRecipe] = useState<RecipeSummary | null>(null);
  const [def, setDef] = useState<Definition | null>(null);
  const [name, setName] = useState("");
  const [meta, setMeta] = useState<RecipeMeta | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [folders, setFolders] = useState<RecipeFolder[]>([]);
  const [folderId, setFolderId] = useState<number | null>(null);
  const [connAvail, setConnAvail] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [test, setTest] = useState({ user_id: "", group_id: "", payload: "{}" });
  const [result, setResult] = useState<Job | null>(null);
  const [versions, setVersions] = useState<{ version: number; published_at: string }[]>([]);
  const [recent, setRecent] = useState<Job[]>([]);
  const [hist] = useState({ past: [] as Definition[], future: [] as Definition[], last: 0, rev: 0 });
  const [resultRev, setResultRev] = useState(0);

  const adopt = (r: RecipeSummary) => { setRecipe(r); setName(r.name); setFolderId(r.folder_id ?? null); if (r.draft) setDef(r.draft); setDirty(false); };
  const load = useCallback(() => {
    http<RecipeSummary>(`/admin/recipes/${id}`).then(adopt).catch((e) => setMsg({ ok: false, text: e.message }));
    http<{ items: { version: number; published_at: string }[] }>(`/admin/recipes/${id}/versions`).then((v) => setVersions(v.items)).catch(() => {});
    http<Page<Job>>(`/admin/recipes/jobs${qs({ recipe_id: id, count: 5 })}`).then((j) => setRecent(j.Resources)).catch(() => {});
  }, [id]);
  useEffect(load, [load]);
  useEffect(() => {
    http<RecipeMeta>("/admin/recipes/meta").then(setMeta).catch(() => {});
    http<Page<Group>>(`/admin/groups${qs({ count: 100 })}`).then((r) => setGroups(r.Resources.filter((g) => !g.is_system_group))).catch(() => {});
    http<Page<User>>(`/admin/users${qs({ count: 100 })}`).then((r) => setUsers(r.Resources)).catch(() => {});
    http<{ items: Connection[] }>("/admin/recipe-connections").then((r) => setConnections(r.items)).catch(() => {});
    http<{ items: RecipeFolder[] }>("/admin/recipe-folders").then((r) => setFolders(r.items)).catch(() => {});
    http<{ connections_available: boolean }>("/admin/recipes/status").then((s) => setConnAvail(s.connections_available)).catch(() => {});
  }, []);

  const ctx: Ctx | null = useMemo(() => (meta && def ? { meta, groups, connections: connections.filter((c) => availableConnection(c, folderId)), folderId, connectionAdded: (c: Connection) => setConnections((items) => [...items.filter((x) => x.id !== c.id), c]), connectionsAvailable: connAvail, trigger: def.trigger.type, root: def.steps } : null), [meta, def, groups, connections, connAvail, folderId]);
  if (!recipe || !def || !meta || !ctx) return <div><PageHeader title="Recipe" />{msg && <Alert variant="destructive"><AlertDescription>{msg.text}</AlertDescription></Alert>}</div>;

  const trig = meta.triggers.find((t) => t.type === def.trigger.type)!;
  const edit = (d: Definition, merge = false) => {
    const now = Date.now();
    if (!merge || now - hist.last > 800) { hist.past.push(def); if (hist.past.length > 50) hist.past.shift(); } // typing in a field undoes as one step; structural edits always get their own
    hist.last = now; hist.future = []; hist.rev += 1;
    setDef(d); setDirty(true);
  };
  const undo = () => { const p = hist.past.pop(); if (p) { hist.future.push(def); hist.last = 0; hist.rev += 1; setDef(p); setDirty(true); } };
  const redo = () => { const n = hist.future.pop(); if (n) { hist.past.push(def); hist.last = 0; hist.rev += 1; setDef(n); setDirty(true); } };
  const setTrigger = (patch: Partial<Definition["trigger"]>) => edit({ ...def, trigger: { ...def.trigger, ...patch } }, true);
  const canEdit = recipe.can_edit !== false;
  const canManage = recipe.can_manage !== false;
  const needsUser = !["schedule", "webhook"].includes(def.trigger.type);
  const isGroupTrig = def.trigger.type.startsWith("group.member_");

  async function act(fn: () => Promise<unknown>, ok?: string) {
    setMsg(null);
    try { await fn(); if (ok) setMsg({ ok: true, text: ok }); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }
  const save = async () => { const r = await http<RecipeSummary>(`/admin/recipes/${id}`, { method: "PUT", body: { name, description: recipe.description, definition: def, folder_id: folderId } }); adopt(r); load(); return r; };

  return (
    <FunctionsContext.Provider value={meta.functions ?? []}>
    <div>
      <PageHeader title={recipe.name}>
        <Badge tone={recipe.enabled ? "good" : "neutral"}>{recipe.enabled ? "enabled" : "disabled"}</Badge>
        <Badge tone="info">{recipe.published_version ? `published v${recipe.published_version}` : "not published"}</Badge>
      </PageHeader>
      <RecipeTabs />
      <p className="mb-4 text-sm"><Link className="underline underline-offset-4" href="/admin/recipes">← All recipes</Link></p>
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status" data-testid="builder-msg"><AlertDescription>{msg.text}</AlertDescription></Alert>}
      {secret && (
        <Alert variant="warning" className="mb-4" data-testid="webhook-secret"><AlertDescription>
          Webhook signing secret (shown only once, copy it now): <code className="break-all">{secret}</code>
          <div className="mt-1 text-xs">POST JSON to <code>{recipe.webhook_path}</code> with headers <code>X-Ifora-Timestamp</code> (unix seconds) and <code>X-Ifora-Signature: v1=HMAC_SHA256(secret, timestamp + "." + body)</code> in hex. Requests older than 5 minutes are refused. The earlier <code>X-IdentityForge-*</code> header names still work.</div>
          <Button size="sm" variant="outline" className="mt-2" onClick={() => setSecret(null)}>I have copied it</Button>
        </AlertDescription></Alert>
      )}

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="space-y-1"><Label htmlFor="rb-name">Recipe name</Label><Input id="rb-name" className="w-72" maxLength={100} value={name} onChange={(e) => { setName(e.target.value); setDirty(true); }} /></div>
        <div className="space-y-1"><Label htmlFor="rb-folder">Folder</Label><select id="rb-folder" className={fieldClass} value={folderId ?? ""} disabled={!canManage} onChange={(e) => { setFolderId(e.target.value ? Number(e.target.value) : null); setDirty(true); }}><option value="">Unfiled</option>{folders.filter((f) => f.can_manage || f.id === folderId).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select></div>
        <Button disabled={!dirty || !name.trim() || !canEdit} onClick={() => act(save, "Draft saved")}>Save draft</Button>
        <Button variant="secondary" disabled={def.steps.length === 0 || !canManage} onClick={() => act(async () => { if (dirty) await save(); const r = await http<RecipeSummary>(`/admin/recipes/${id}/publish`, { method: "POST" }); adopt(r); if (r.webhook_secret) setSecret(r.webhook_secret); load(); }, "Published as a new immutable version")}>Publish</Button>
        {recipe.enabled
          ? <Button variant="outline" disabled={!canManage} onClick={() => act(async () => { adopt(await http<RecipeSummary>(`/admin/recipes/${id}/disable`, { method: "POST" })); load(); }, "Recipe disabled")}>Disable</Button>
          : <Button variant="outline" disabled={!recipe.published_version || !canManage} onClick={() => act(async () => { adopt(await http<RecipeSummary>(`/admin/recipes/${id}/enable`, { method: "POST" })); load(); }, "Recipe enabled")}>Enable</Button>}
        {recipe.published_trigger_type === "manual" && recipe.enabled && <Button variant="outline" disabled={!canManage} onClick={() => act(async () => { await http(`/admin/recipes/${id}/run`, { method: "POST", body: { payload: safeJson(test.payload), user_id: test.user_id ? Number(test.user_id) : null } }); load(); }, "Run queued; the worker will pick it up")}>Run now</Button>}
        <Button variant="outline" onClick={() => act(async () => {
          const doc = await http<unknown>(`/admin/recipes/${id}/export`);
          const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" }));
          const a = document.createElement("a");
          a.href = url; a.download = `${name.replace(/[^A-Za-z0-9_-]+/g, "-") || "recipe"}.recipe.json`; a.click();
          URL.revokeObjectURL(url);
        }, "Exported the saved draft (no secrets included)")}>Export</Button>
        {dirty && <span className="text-sm text-warn">Unsaved changes</span>}
        {!dirty && recipe.has_unpublished_changes && recipe.published_version && <span className="text-sm text-warn">Draft differs from the published version</span>}
      </div>

      {!canEdit && <Alert className="mb-4" data-testid="read-only-note"><AlertDescription>Read-only: only the owner ({recipe.owner?.email ?? "unassigned"}), listed editors and super admins can change this recipe.</AlertDescription></Alert>}
      <AccessCard recipe={recipe} admins={users.filter((u) => u.is_admin)} onSaved={(r) => { adopt(r); load(); }} setMsg={setMsg} />

      <div className="mb-6">
        <Studio def={def} meta={meta} ctx={ctx} groups={groups} canEdit={canEdit} edit={edit} setTrigger={setTrigger}
          result={result} stale={resultRev !== hist.rev} previewFormulas={async (templates) => (await http<{ items: { template: string; ok: boolean; value?: unknown; error?: string }[] }>(`/admin/recipes/${id}/formula-preview`, { method: "POST", body: { templates, user_id: test.user_id ? Number(test.user_id) : null, group_id: test.group_id ? Number(test.group_id) : null, payload: safeJson(test.payload) } })).items} undo={undo} redo={redo} canUndo={hist.past.length > 0} canRedo={hist.future.length > 0} />
      </div>

      <Card className="mt-6" id="test-card" data-testid="test-card">
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
            const at = hist.rev;
            setResultRev(at);
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
          {versions.length === 0 ? <span className="text-muted-foreground">Nothing published yet.</span> : <ul className="space-y-1">{versions.map((v) => (
            <li key={v.version} className="flex items-center justify-between gap-2">
              <span>v{v.version} · {new Date(v.published_at).toLocaleString()}</span>
              {canEdit && <Button size="sm" variant="ghost" aria-label={`Restore version ${v.version} to the draft`} onClick={() => act(async () => {
                if (dirty && !window.confirm("This replaces your unsaved changes with version " + v.version + ". Continue?")) return;
                hist.past.push(def); hist.future = []; hist.rev += 1;
                adopt(await http<RecipeSummary>(`/admin/recipes/${id}/versions/${v.version}/restore`, { method: "POST" }));
                load();
              }, `Version ${v.version} copied into the draft. It is not published.`)}>Restore to draft</Button>}
            </li>
          ))}</ul>}
          {recipe.webhook_path && <p className="mt-2 break-all text-xs text-muted-foreground">Webhook: {recipe.webhook_path} {recipe.webhook_secret_set ? "(secret set)" : ""}</p>}
        </CardContent></Card>
      </div>
    </div>
    </FunctionsContext.Provider>
  );
}

function AccessCard({ recipe, admins, onSaved, setMsg }: { recipe: RecipeSummary; admins: User[]; onSaved: (r: RecipeSummary) => void; setMsg: (m: { ok: boolean; text: string } | null) => void }) {
  const [owner, setOwner] = useState<number>(recipe.owner?.id ?? 0);
  const [editors, setEditors] = useState<number[]>((recipe.editors ?? []).map((e) => e.id));
  const [limit, setLimit] = useState<string>(recipe.rate_limit_per_hour == null ? "" : String(recipe.rate_limit_per_hour));
  const can = recipe.can_manage !== false;
  const save = async () => {
    setMsg(null);
    try {
      const body: Record<string, unknown> = { editors, owner_id: owner || null };
      if (limit === "") body.clear_rate_limit = true; else body.rate_limit_per_hour = Number(limit);
      onSaved(await http<RecipeSummary>(`/admin/recipes/${recipe.id}/settings`, { method: "PUT", body }));
      setMsg({ ok: true, text: "Access and limits saved" });
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  };
  return (
    <details className="mb-4 rounded-md border p-3" data-testid="access-card">
      <summary className="cursor-pointer text-sm font-medium">Owner, editors and limits</summary>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <div className="space-y-1"><Label htmlFor="ac-owner">Owner</Label>
          <select id="ac-owner" className={fieldClass} disabled={!can} value={owner} onChange={(e) => setOwner(Number(e.target.value))}>
            {!admins.some((a) => a.id === owner) && <option value={owner}>{recipe.owner?.email ?? "unassigned"}</option>}
            {admins.map((a) => <option key={a.id} value={a.id}>{a.email}</option>)}
          </select>
          <p className="text-xs text-muted-foreground">Owners publish, enable, run, delete and control jobs.</p></div>
        <div className="space-y-1"><Label htmlFor="ac-editors">Editors</Label>
          <select id="ac-editors" multiple size={4} className={fieldClass + " h-auto"} disabled={!can} value={editors.map(String)}
            onChange={(e) => setEditors(Array.from(e.target.selectedOptions).map((o) => Number(o.value)))}>
            {admins.filter((a) => a.id !== owner).map((a) => <option key={a.id} value={a.id}>{a.email}</option>)}
          </select>
          <p className="text-xs text-muted-foreground">Editors change the draft and dry-run it; they cannot publish.</p></div>
        <div className="space-y-1"><Label htmlFor="ac-rate">Max automatic jobs per hour</Label>
          <Input id="ac-rate" type="number" min={0} disabled={!can} placeholder={`server default (${recipe.effective_rate_limit_per_hour || "unlimited"})`} value={limit} onChange={(e) => setLimit(e.target.value)} />
          <p className="text-xs text-muted-foreground">0 = unlimited. Manual runs and re-runs are never limited.{(recipe.throttled_count ?? 0) > 0 ? ` ${recipe.throttled_count} event(s) dropped so far.` : ""}</p></div>
      </div>
      <Button className="mt-3" size="sm" disabled={!can} onClick={save}>Save access and limits</Button>
    </details>
  );
}

function safeJson(s: string): Record<string, unknown> {
  try { const v = JSON.parse(s || "{}"); return v && typeof v === "object" && !Array.isArray(v) ? v : {}; } catch { return {}; }
}
