"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldClass } from "@/components/bits";
import { http, qs, type Page } from "@/lib/http";
import type { Connection, RecipeMeta, RecipeSummary } from "@/lib/recipes";
import type { Group } from "@/lib/types";

type Template = { id: string; name: string; description: string; params: { key: string; label: string; type: string }[] };

/** Pick a starter template, fill in its few parameters, get a draft recipe. */
export function TemplatePicker({ meta, onCreated, onError, onCancel }: { meta: RecipeMeta | null; onCreated: (r: RecipeSummary) => void; onError: (m: string) => void; onCancel: () => void }) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [slack, setSlack] = useState<Connection[]>([]);
  const [sel, setSel] = useState<Template | null>(null);
  const [name, setName] = useState("");
  const [vals, setVals] = useState<Record<string, string>>({});

  useEffect(() => {
    http<{ items: Template[] }>("/admin/recipes/templates").then((r) => setTemplates(r.items)).catch((e) => onError(e.message));
    http<Page<Group>>(`/admin/groups${qs({ count: 100 })}`).then((r) => setGroups(r.Resources.filter((g) => !g.is_system_group))).catch(() => {});
    http<{ items: Connection[] }>("/admin/recipe-connections").then((r) => setSlack(r.items.filter((c) => c.kind === "slack_webhook"))).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const complete = !!sel && name.trim() !== "" && sel.params.every((p) => (vals[p.key] ?? "") !== "");

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
          <div className="space-y-1"><Label htmlFor="tp-name">Recipe name</Label><Input id="tp-name" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} /></div>
          {sel.params.map((p) => (
            <div key={p.key} className="space-y-1"><Label htmlFor={`tp-${p.key}`}>{p.label}</Label>
              {p.type === "group" ? (
                <select id={`tp-${p.key}`} className={fieldClass} value={vals[p.key] ?? ""} onChange={(e) => setVals({ ...vals, [p.key]: e.target.value })}><option value="">Choose…</option>{groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select>
              ) : p.type === "slack_connection" ? (
                <select id={`tp-${p.key}`} className={fieldClass} value={vals[p.key] ?? ""} onChange={(e) => setVals({ ...vals, [p.key]: e.target.value })}><option value="">Choose…</option>{slack.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
              ) : p.type === "attribute" ? (
                <select id={`tp-${p.key}`} className={fieldClass} value={vals[p.key] ?? ""} onChange={(e) => setVals({ ...vals, [p.key]: e.target.value })}><option value="">Choose…</option>{meta?.managed_attributes.map((a) => <option key={a.key} value={a.key}>{a.display_name}</option>)}</select>
              ) : (
                <Input id={`tp-${p.key}`} type={p.type === "number" ? "number" : "text"} value={vals[p.key] ?? ""} onChange={(e) => setVals({ ...vals, [p.key]: e.target.value })} />
              )}
            </div>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <Button disabled={!complete} onClick={async () => {
          try {
            const params: Record<string, unknown> = {};
            for (const p of sel!.params) params[p.key] = ["group", "slack_connection", "number"].includes(p.type) ? Number(vals[p.key]) : vals[p.key];
            onCreated(await http<RecipeSummary>("/admin/recipes/from-template", { method: "POST", body: { template_id: sel!.id, name, params } }));
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
      {doc && <div className="space-y-1"><Label htmlFor="imp-name">Recipe name</Label><Input id="imp-name" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} /></div>}
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
