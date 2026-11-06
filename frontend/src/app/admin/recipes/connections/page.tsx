"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fieldClass, td, th } from "@/components/bits";
import { RecipeTabs } from "@/components/recipe-bits";
import { http } from "@/lib/http";
import type { Connection } from "@/lib/recipes";

type Draft = { id?: number; name: string; kind: "bearer" | "header"; header_name: string; allowed_host: string; secret: string };
const empty = (): Draft => ({ name: "", kind: "bearer", header_name: "X-Api-Key", allowed_host: "", secret: "" });

export default function ConnectionsPage() {
  const [items, setItems] = useState<Connection[] | null>(null);
  const [available, setAvailable] = useState(true);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    http<{ connections_available: boolean }>("/admin/recipes/status").then((s) => setAvailable(s.connections_available)).catch(() => {});
    http<{ items: Connection[] }>("/admin/recipe-connections").then((r) => setItems(r.items)).catch((e) => setMsg({ ok: false, text: e.message }));
  }, []);
  useEffect(load, [load]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); load(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }

  return (
    <div>
      <PageHeader title="Recipes">
        <Button disabled={!available} onClick={() => setDraft(empty())}><Plus className="mr-1 h-4 w-4" /> Add connection</Button>
      </PageHeader>
      <RecipeTabs />
      <p className="mb-4 max-w-2xl text-sm text-muted-foreground">
        A connection stores a credential for an outside service. It is encrypted, never shown again, and can only be sent to the one host it is
        bound to. Steps refer to a connection by name; the secret is never part of a recipe or its job history.
      </p>
      {!available && <Alert className="mb-4"><AlertDescription>Connections are unavailable: set <code>RECIPE_ENCRYPTION_KEY</code> (a dedicated Fernet key) and restart the API.</AlertDescription></Alert>}
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      {draft && (
        <Card className="mb-6" data-testid="connection-editor"><CardContent className="space-y-3 pt-6">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1"><Label htmlFor="c-name">Name</Label><Input id="c-name" value={draft.name} maxLength={100} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></div>
            <div className="space-y-1"><Label htmlFor="c-host">Only send to host</Label><Input id="c-host" placeholder="api.example.com" value={draft.allowed_host} onChange={(e) => setDraft({ ...draft, allowed_host: e.target.value })} /></div>
            <div className="space-y-1"><Label htmlFor="c-kind">Send the secret as</Label>
              <select id="c-kind" className={fieldClass} value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as Draft["kind"] })}>
                <option value="bearer">Authorization: Bearer …</option><option value="header">A custom header</option>
              </select></div>
            {draft.kind === "header" && <div className="space-y-1"><Label htmlFor="c-header">Header name</Label><Input id="c-header" value={draft.header_name} onChange={(e) => setDraft({ ...draft, header_name: e.target.value })} /></div>}
            <div className="space-y-1 sm:col-span-2"><Label htmlFor="c-secret">{draft.id ? "New secret (leave empty to keep the current one)" : "Secret"}</Label>
              <Input id="c-secret" type="password" autoComplete="off" value={draft.secret} onChange={(e) => setDraft({ ...draft, secret: e.target.value })} /></div>
          </div>
          <div className="flex gap-2">
            <Button disabled={!draft.name.trim() || !draft.allowed_host.trim() || (!draft.id && !draft.secret)} onClick={() => run(async () => {
              const body = { name: draft.name, kind: draft.kind, header_name: draft.kind === "header" ? draft.header_name : null, allowed_host: draft.allowed_host, secret: draft.secret || null };
              if (draft.id) await http(`/admin/recipe-connections/${draft.id}`, { method: "PUT", body }); else await http("/admin/recipe-connections", { method: "POST", body });
              setDraft(null);
            }, "Connection saved")}>Save connection</Button>
            <Button variant="ghost" onClick={() => setDraft(null)}>Cancel</Button>
          </div>
        </CardContent></Card>
      )}

      <Card><CardContent className="overflow-x-auto p-0">
        <table className="w-full" data-testid="connections-table">
          <thead className="border-b"><tr><th className={th}>Name</th><th className={th}>Host</th><th className={th}>Sent as</th><th className={th}>Secret</th><th className={th}></th></tr></thead>
          <tbody>
            {items?.map((c) => (
              <tr key={c.id} className="border-b last:border-0">
                <td className={td + " font-medium"}>{c.name}</td><td className={td}>{c.allowed_host}</td>
                <td className={td}>{c.kind === "bearer" ? "Bearer token" : c.header_name}</td>
                <td className={td}><Badge tone="good">stored, hidden</Badge></td>
                <td className={td + " space-x-2 whitespace-nowrap text-right"}>
                  <Button size="sm" variant="outline" onClick={() => setDraft({ id: c.id, name: c.name, kind: c.kind, header_name: c.header_name ?? "X-Api-Key", allowed_host: c.allowed_host, secret: "" })}>Edit</Button>
                  <Button size="sm" variant="outline" onClick={() => { if (confirm(`Delete connection "${c.name}"? Recipes using it will fail until updated.`)) run(() => http(`/admin/recipe-connections/${c.id}`, { method: "DELETE" }), "Connection deleted"); }}>Delete</Button>
                </td>
              </tr>
            ))}
            {items && items.length === 0 && <tr><td className={td} colSpan={5}>No connections yet.</td></tr>}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  );
}
