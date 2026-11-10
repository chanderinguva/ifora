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
import { http, qs, type Page } from "@/lib/http";
import { useDirty } from "@/lib/use-dirty";
import { SaveButton } from "@/components/save-button";
import type { Connection, ConnectorInfo } from "@/lib/recipes";
import { ConnectorCatalog, ConnectorConnectionForm, newConnectorDraft, type ConnectorDraft } from "@/components/connectors";
import type { User } from "@/lib/types";

type Kind = Connection["kind"];
type Draft = { id?: number; name: string; kind: Kind; header_name: string; allowed_host: string; paths: string; client_id: string; token_url: string; scope: string; secret: string; allowed_users: number[] };
const empty = (): Draft => ({ name: "", kind: "bearer", header_name: "X-Api-Key", allowed_host: "", paths: "", client_id: "", token_url: "", scope: "", secret: "", allowed_users: [] });
const KIND_LABEL: Record<Kind, string> = { bearer: "Bearer token", header: "Custom header", oauth2_client_credentials: "OAuth2 client credentials", slack_webhook: "Slack webhook", connector: "Pre-built connector" };

export default function ConnectionsPage() {
  const [items, setItems] = useState<Connection[] | null>(null);
  const [available, setAvailable] = useState(true);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [admins, setAdmins] = useState<User[]>([]);
  const [connectors, setConnectors] = useState<ConnectorInfo[]>([]);
  const [cdraft, setCdraft] = useState<ConnectorDraft | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const conn = useDirty(draft, draft !== null);
  const connector = useDirty(cdraft, cdraft !== null);

  const load = useCallback(() => {
    http<{ connections_available: boolean }>("/admin/recipes/status").then((s) => setAvailable(s.connections_available)).catch(() => {});
    http<{ items: ConnectorInfo[] }>("/admin/connectors").then((r) => setConnectors(r.items)).catch(() => {});
    http<{ items: Connection[] }>("/admin/recipe-connections").then((r) => setItems(r.items)).catch((e) => setMsg({ ok: false, text: e.message }));
  }, []);
  useEffect(load, [load]);
  useEffect(() => { http<Page<User>>(`/admin/users${qs({ count: 100 })}`).then((p) => setAdmins(p.Resources.filter((u) => u.is_admin))).catch(() => {}); }, []);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); load(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }

  async function saveConnector(d: ConnectorDraft) {
    const secrets = Object.fromEntries(Object.entries(d.secrets).filter(([, v]) => v.trim() !== ""));
    const body = { name: d.name.trim(), config: d.config, secrets, allowed_users: d.allowed_users };
    await run(async () => {
      if (d.id) await http(`/admin/connectors/${d.connector.id}/connections/${d.id}`, { method: "PUT", body });
      else await http(`/admin/connectors/${d.connector.id}/connections`, { method: "POST", body });
      setCdraft(null);
    }, "Connection saved");
  }

  function editConnector(c: Connection) {
    const con = connectors.find((x) => x.id === c.connector_id);
    if (!con) { setMsg({ ok: false, text: "This connector is no longer available." }); return; }
    setDraft(null);
    setCdraft({ connector: con, id: c.id, name: c.name, config: { ...(c.config ?? {}) }, secrets: {}, allowed_users: c.allowed_users ?? [] });
  }

  async function testConnection(c: Connection) {
    setMsg(null);
    try {
      const r = await http<{ ok: boolean; message: string }>(`/admin/recipe-connections/${c.id}/test`, { method: "POST" });
      setMsg({ ok: r.ok, text: `${c.name}: ${r.message}` });
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Test failed" }); }
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

      {cdraft && <ConnectorConnectionForm dirty={cdraft.id === undefined || connector.dirty} draft={cdraft} setDraft={setCdraft} admins={admins} onSave={() => saveConnector(cdraft)} onCancel={() => setCdraft(null)} />}
      {!cdraft && !draft && <ConnectorCatalog items={connectors} disabled={!available} onConnect={(c) => setCdraft(newConnectorDraft(c))} />}

      {draft && (
        <Card className="mb-6" data-testid="connection-editor"><CardContent className="space-y-3 pt-6">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1"><Label htmlFor="c-name">Name</Label><Input id="c-name" value={draft.name} maxLength={100} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></div>
            {draft.kind !== "slack_webhook" && <div className="space-y-1"><Label htmlFor="c-host">Only send to host</Label><Input id="c-host" placeholder="api.example.com" value={draft.allowed_host} onChange={(e) => setDraft({ ...draft, allowed_host: e.target.value })} /></div>}
            <div className="space-y-1"><Label htmlFor="c-kind">Send the secret as</Label>
              <select id="c-kind" className={fieldClass} value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as Draft["kind"] })}>
                <option value="bearer">Authorization: Bearer …</option><option value="header">A custom header</option>
                <option value="oauth2_client_credentials">OAuth2 (client credentials)</option><option value="slack_webhook">Slack incoming webhook</option>
              </select></div>
            {draft.kind === "header" && <div className="space-y-1"><Label htmlFor="c-header">Header name</Label><Input id="c-header" value={draft.header_name} onChange={(e) => setDraft({ ...draft, header_name: e.target.value })} /></div>}
            {draft.kind === "oauth2_client_credentials" && <>
              <div className="space-y-1"><Label htmlFor="c-client">Client ID</Label><Input id="c-client" value={draft.client_id} onChange={(e) => setDraft({ ...draft, client_id: e.target.value })} /></div>
              <div className="space-y-1"><Label htmlFor="c-scope">Scope (optional)</Label><Input id="c-scope" value={draft.scope} onChange={(e) => setDraft({ ...draft, scope: e.target.value })} /></div>
              <div className="space-y-1 sm:col-span-2"><Label htmlFor="c-token">Token URL (https, on the host above)</Label><Input id="c-token" placeholder="https://api.example.com/oauth/token" value={draft.token_url} onChange={(e) => setDraft({ ...draft, token_url: e.target.value })} /></div>
            </>}
            {draft.kind !== "slack_webhook" && (
              <div className="space-y-1 sm:col-span-2"><Label htmlFor="c-paths">Only these paths (optional, one prefix per line, e.g. /api/v1/)</Label>
                <textarea id="c-paths" rows={3} className={fieldClass} value={draft.paths} onChange={(e) => setDraft({ ...draft, paths: e.target.value })} />
                <p className="text-xs text-muted-foreground">Empty = any path on the host. A prefix matches that path and everything below it.</p></div>
            )}
            <fieldset className="space-y-1 sm:col-span-2" data-testid="connection-acl">
              <legend className="text-sm font-medium">Who can use this connection in recipes</legend>
              <p className="text-xs text-muted-foreground">Nobody ticked = every administrator. Otherwise only the ticked administrators, its creator and super admins can attach it to a recipe step, and only the creator or a super admin can change or delete it.</p>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {admins.map((u) => (
                  <label key={u.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={draft.allowed_users.includes(u.id)}
                      onChange={(e) => setDraft({ ...draft, allowed_users: e.target.checked ? [...draft.allowed_users, u.id] : draft.allowed_users.filter((x) => x !== u.id) })} /> {u.email}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="space-y-1 sm:col-span-2"><Label htmlFor="c-secret">{draft.id ? "New secret (leave empty to keep the current one)" : draft.kind === "slack_webhook" ? "Webhook URL" : draft.kind === "oauth2_client_credentials" ? "Client secret" : "Secret"}</Label>
              <Input id="c-secret" type="password" autoComplete="off" value={draft.secret} onChange={(e) => setDraft({ ...draft, secret: e.target.value })} /></div>
          </div>
          <div className="flex gap-2">
            <SaveButton dirty={!draft.id || conn.dirty} disabled={!draft.name.trim() || (draft.kind !== "slack_webhook" && !draft.allowed_host.trim()) || (!draft.id && !draft.secret)} onClick={() => run(async () => {
              const body = { name: draft.name, kind: draft.kind, header_name: draft.kind === "header" ? draft.header_name : null, allowed_host: draft.allowed_host,
                allowed_paths: draft.kind === "slack_webhook" ? null : draft.paths.split("\n").map((p) => p.trim()).filter(Boolean),
                client_id: draft.kind === "oauth2_client_credentials" ? draft.client_id : null, token_url: draft.kind === "oauth2_client_credentials" ? draft.token_url : null,
                scope: draft.kind === "oauth2_client_credentials" ? draft.scope || null : null, secret: draft.secret || null, allowed_users: draft.allowed_users };
              if (draft.id) await http(`/admin/recipe-connections/${draft.id}`, { method: "PUT", body }); else await http("/admin/recipe-connections", { method: "POST", body });
              setDraft(null);
            }, "Connection saved")}>Save connection</SaveButton>
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
                <td className={td + " font-medium"}>{c.name}{c.restricted && <> <Badge tone="info">restricted</Badge></>}</td><td className={td}>{c.allowed_host}</td>
                <td className={td}>{c.kind === "header" ? c.header_name : c.kind === "connector" ? (connectors.find((x) => x.id === c.connector_id)?.name ?? c.connector_id) : KIND_LABEL[c.kind]}{c.allowed_paths && c.allowed_paths.length > 0 && <div className="text-xs text-muted-foreground">paths: {c.allowed_paths.join(", ")}</div>}</td>
                <td className={td}><Badge tone="good">stored, hidden</Badge></td>
                <td className={td + " space-x-2 whitespace-nowrap text-right"}>
                  {c.kind === "connector" && <Button size="sm" variant="outline" onClick={() => testConnection(c)}>Test</Button>}
                  <Button size="sm" variant="outline" disabled={c.can_manage === false} title={c.can_manage === false ? "Only its creator or a super admin can change this" : ""} onClick={() => c.kind === "connector" ? editConnector(c) : setDraft({ id: c.id, name: c.name, kind: c.kind, header_name: c.header_name ?? "X-Api-Key", allowed_host: c.allowed_host, paths: (c.allowed_paths ?? []).join("\n"), client_id: c.client_id ?? "", token_url: c.token_url ?? "", scope: c.scope ?? "", secret: "", allowed_users: c.allowed_users ?? [] })}>Edit</Button>
                  <Button size="sm" variant="outline" disabled={c.can_manage === false} onClick={() => { if (confirm(`Delete connection "${c.name}"? Recipes using it will fail until updated.`)) run(() => http(`/admin/recipe-connections/${c.id}`, { method: "DELETE" }), "Connection deleted"); }}>Delete</Button>
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
