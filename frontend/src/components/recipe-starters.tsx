"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldClass } from "@/components/bits";
import { http, qs, type Page } from "@/lib/http";
import type { Connection, RecipeMeta, RecipeSummary } from "@/lib/recipes";
import { availableConnection, type RecipeFolder } from "@/lib/recipes";
import { InlineConnection } from "@/components/connection-editor";
import type { Group } from "@/lib/types";

type Template = { id: string; name: string; description: string; params: { key: string; label: string; type: string }[] };

/** Pick a starter template, fill in its few parameters, get a draft recipe. */
export function TemplatePicker({ meta, onCreated, onError, onCancel }: { meta: RecipeMeta | null; onCreated: (r: RecipeSummary) => void; onError: (m: string) => void; onCancel: () => void }) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [slack, setSlack] = useState<Connection[]>([]);
  const [folders, setFolders] = useState<RecipeFolder[]>([]);
  const [folderId, setFolderId] = useState<number | null>(null);
  const [sel, setSel] = useState<Template | null>(null);
  const [name, setName] = useState("");
  const [vals, setVals] = useState<Record<string, string>>({});

  useEffect(() => {
    http<{ items: Template[] }>("/admin/recipes/templates").then((r) => setTemplates(r.items)).catch((e) => onError(e.message));
    http<Page<Group>>(`/admin/groups${qs({ count: 100 })}`).then((r) => setGroups(r.Resources.filter((g) => !g.is_system_group))).catch(() => {});
    http<{ items: Connection[] }>("/admin/recipe-connections").then((r) => setSlack(r.items.filter((c) => c.kind === "slack_webhook" || c.connector_id === "slack"))).catch(() => {});
    http<{ items: RecipeFolder[] }>("/admin/recipe-folders").then((r) => setFolders(r.items)).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const bot = slack.find((c) => c.id === Number(vals.connection))?.connector_id === "slack";
  const complete = !!sel && name.trim() !== "" && sel.params.every((p) => (vals[p.key] ?? "") !== "") && (!bot || !!vals.channel?.trim());

  return (
    <Card className="mb-6" data-testid="template-picker"><CardContent className="space-y-4 pt-6">
      <div className="grid gap-3 md:grid-cols-2">
        {templates.map((t) => (
          <button key={t.id} type="button" onClick={() => { setSel(t); setVals({}); setName(t.name); }} aria-pressed={sel?.id === t.id}
            className={"rounded-md border p-3 text-left text-sm " + (sel?.id === t.id ? "border-primary bg-muted" : "hover:bg-muted")}>
            <div className="font-medium">{t.name}</div><div className="text-muted-foreground">{t.description}</div>
          </button>
        ))}
      </div>
      {sel && (
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1"><Label htmlFor="tp-name">Recipe name<span aria-hidden="true"> (required)</span></Label><Input id="tp-name" required aria-required="true" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="tp-folder">Recipe folder</Label><select id="tp-folder" className={fieldClass} value={folderId ?? ""} onChange={(e) => { setFolderId(e.target.value ? Number(e.target.value) : null); setVals((v) => ({ ...v, connection: "" })); }}><option value="">Unfiled</option>{folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select></div>
          {sel.params.map((p) => (
            <div key={p.key} className="space-y-1"><Label htmlFor={`tp-${p.key}`}>{p.label}<span aria-hidden="true"> (required)</span></Label>
              {p.type === "group" ? (
                <select id={`tp-${p.key}`} required aria-required="true" className={fieldClass} value={vals[p.key] ?? ""} onChange={(e) => setVals({ ...vals, [p.key]: e.target.value })}><option value="">Choose…</option>{groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select>
              ) : p.type === "slack_connection" ? (
                <><select id={`tp-${p.key}`} required aria-required="true" className={fieldClass} value={vals[p.key] ?? ""} onChange={(e) => setVals({ ...vals, [p.key]: e.target.value })}><option value="">Choose…</option>{slack.filter((c) => availableConnection(c, folderId)).map((c) => <option key={c.id} value={c.id}>{c.name}{c.connector_id === "slack" ? " (bot)" : " (webhook)"}</option>)}</select>
                  <InlineConnection folderId={folderId} connector="slack" onCreated={(c) => { if (c.connector_id === "slack" || c.kind === "slack_webhook") { setSlack((s) => [...s, c]); setVals((v) => ({ ...v, [p.key]: String(c.id) })); } else onError("Connection saved. Choose a Slack connection for this template."); }} />
                  {!slack.some((c) => availableConnection(c, folderId)) && <p className="text-xs text-muted-foreground">No Slack connection is available here. Create one without leaving this template.</p>}</>
              ) : p.type === "attribute" ? (
                <select id={`tp-${p.key}`} required aria-required="true" className={fieldClass} value={vals[p.key] ?? ""} onChange={(e) => setVals({ ...vals, [p.key]: e.target.value })}><option value="">Choose…</option>{meta?.managed_attributes.map((a) => <option key={a.key} value={a.key}>{a.display_name}</option>)}</select>
              ) : (
                <Input id={`tp-${p.key}`} required aria-required="true" type={p.type === "number" ? "number" : "text"} value={vals[p.key] ?? ""} onChange={(e) => setVals({ ...vals, [p.key]: e.target.value })} />
              )}
            </div>
          ))}
          {bot && <div className="space-y-1"><Label htmlFor="tp-channel">Slack channel or user ID<span aria-hidden="true"> (required)</span></Label><Input id="tp-channel" required aria-required="true" value={vals.channel ?? ""} placeholder="C0123456789" onChange={(e) => setVals({ ...vals, channel: e.target.value })} /><p className="text-xs text-muted-foreground">The bot needs chat:write and access to the selected conversation.</p></div>}
        </div>
      )}
      {sel && !complete && <p className="text-xs text-muted-foreground" role="status">Complete the required fields above to create this draft.</p>}
      <div className="flex gap-2">
        <Button disabled={!complete} onClick={async () => {
          try {
            const params: Record<string, unknown> = {};
            for (const p of sel!.params) params[p.key] = ["group", "slack_connection", "number"].includes(p.type) ? Number(vals[p.key]) : vals[p.key];
            if (bot) params.channel = vals.channel.trim();
            onCreated(await http<RecipeSummary>("/admin/recipes/from-template", { method: "POST", body: { template_id: sel!.id, name, params, folder_id: folderId } }));
          } catch (e) { onError(e instanceof Error ? e.message : "Failed"); }
        }}>Create draft from template</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </CardContent></Card>
  );
}

/** Import a recipe file produced by Export. Always lands as a disabled, unpublished draft. */
export function ImportCard({ onCreated, onError, onCancel }: { onCreated: (r: RecipeSummary) => void; onError: (m: string) => void; onCancel: () => void }) {
  const [doc, setDoc] = useState<Record<string, unknown> | null>(null);
  const [name, setName] = useState("");
  return (
    <Card className="mb-6" data-testid="import-card"><CardContent className="space-y-3 pt-6">
      <div className="space-y-1"><Label htmlFor="imp-file">Recipe file (.json)</Label>
        <input id="imp-file" type="file" accept="application/json,.json" className="block text-sm" onChange={async (e) => {
          const f = e.target.files?.[0];
          if (!f) return;
          try {
            const parsed = JSON.parse(await f.text());
            setDoc(parsed); setName(typeof parsed?.name === "string" ? `${parsed.name} (imported)`.slice(0, 100) : "Imported recipe");
          } catch { setDoc(null); onError("That file is not valid JSON"); }
        }} />
        <p className="text-xs text-muted-foreground">Groups and connections are matched by name; create any that are missing first. The recipe arrives disabled and unpublished.</p></div>
      {doc && <div className="space-y-1"><Label htmlFor="imp-name">Recipe name<span aria-hidden="true"> (required)</span></Label><Input id="imp-name" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} /></div>}
      <div className="flex gap-2">
        <Button disabled={!doc || !name.trim()} onClick={async () => {
          try { onCreated(await http<RecipeSummary>("/admin/recipes/import", { method: "POST", body: { document: doc, name } })); }
          catch (e) { onError(e instanceof Error ? e.message : "Failed"); }
        }}>Import as draft</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </CardContent></Card>
  );
}
