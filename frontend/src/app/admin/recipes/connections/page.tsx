"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, FolderClosed, Globe2, LockKeyhole } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge, PageHeader, td, th } from "@/components/bits";
import { RecipeTabs } from "@/components/recipe-bits";
import { ConnectorCatalog } from "@/components/connectors";
import { ConnectionDialog, ConnectionEditor, FolderEditor } from "@/components/connection-editor";
import { http } from "@/lib/http";
import type { Connection, ConnectorInfo, RecipeFolder } from "@/lib/recipes";

export default function ConnectionsPage() {
  const [items, setItems] = useState<Connection[]>([]);
  const [folders, setFolders] = useState<RecipeFolder[]>([]);
  const [catalog, setCatalog] = useState<ConnectorInfo[]>([]);
  const [available, setAvailable] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [editor, setEditor] = useState<{ connection?: Connection; connector?: string } | null>(null);
  const [folderEditor, setFolderEditor] = useState<{ folder?: RecipeFolder } | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const load = useCallback(() => {
    Promise.all([
      http<{ items: Connection[] }>("/admin/recipe-connections"),
      http<{ items: RecipeFolder[] }>("/admin/recipe-folders"),
      http<{ items: ConnectorInfo[] }>("/admin/connectors"),
      http<{ connections_available: boolean }>("/admin/recipes/status"),
    ]).then(([c, f, cat, s]) => { setItems(c.items); setFolders(f.items); setCatalog(cat.items); setAvailable(s.connections_available); setLoaded(true); })
      .catch((e) => setMsg({ ok: false, text: e.message }));
  }, []);
  useEffect(load, [load]);
  async function test(c: Connection) {
    setBusy(c.id); setMsg(null);
    try {
      const r = await http<{ ok: boolean; message: string }>("/admin/recipe-connections/" + c.id + (c.kind === "http" ? "/check" : "/test"), { method: "POST" });
      setMsg({ ok: r.ok, text: c.name + ": " + r.message }); load();
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Test failed" }); }
    finally { setBusy(null); }
  }
  async function authorize(c: Connection) {
    // Open synchronously to preserve browser popup permission; no secret is passed to the browser.
    const tab = window.open("about:blank", "_blank");
    if (tab) tab.opener = null;
    try {
      const r = await http<{ authorization_url: string }>("/admin/recipe-connections/" + c.id + "/oauth/start", { method: "POST" });
      if (tab) tab.location.href = r.authorization_url;
      else setMsg({ ok: false, text: "Allow popups for Ifora and choose Authorize again." });
    } catch (e) { tab?.close(); setMsg({ ok: false, text: e instanceof Error ? e.message : "Could not start authorization" }); }
  }
  return <div>
    <PageHeader title="Recipes"><Button variant="outline" onClick={() => setFolderEditor({})}><FolderClosed className="mr-2 h-4 w-4" />New folder</Button><Button disabled={!available} onClick={() => setEditor({})}><Plus className="mr-1 h-4 w-4" />Add connection</Button></PageHeader>
    <RecipeTabs />
    <div className="mb-5 flex max-w-3xl items-start gap-3"><LockKeyhole className="mt-1 h-5 w-5 shrink-0 text-primary" /><p className="text-sm text-muted-foreground">Connect a service once, then use its actions across recipes. Share through organization or folder permissions. Credentials stay encrypted and are never shown again.</p></div>
    {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
    {loaded && !available && <Alert className="mb-4"><AlertDescription>Secret storage is not configured. Configure the Fernet or OpenBao provider on the server.</AlertDescription></Alert>}
    <ConnectorCatalog items={catalog} disabled={!available} onConnect={(c) => setEditor({ connector: c.id })} />
    <section className="mb-6 rounded-lg border bg-card p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">HTTP / Custom API</h2><p className="text-sm text-muted-foreground">Connect services without a pre-built connector. Basic, bearer, API key, OAuth 2.0 or encrypted custom fields.</p></div><Button variant="outline" disabled={!available} onClick={() => setEditor({ connector: "http" })}>Connect API</Button></div></section>
    <h2 className="mb-3 font-semibold">Saved connections</h2>
    <div className="overflow-x-auto rounded-lg border"><table className="w-full text-sm" data-testid="connections-table"><thead><tr><th className={th}>Connection</th><th className={th}>Service</th><th className={th}>Availability</th><th className={th}>Permissions</th><th className={th}><span className="sr-only">Actions</span></th></tr></thead><tbody>
      {items.map((c) => <tr key={c.id} className="border-t"><td className={td}><div className="font-medium">{c.name}</div><div className="text-xs text-muted-foreground">{c.allowed_host}</div></td>
        <td className={td}>{catalog.find((x) => x.id === c.connector_id)?.name ?? (c.kind === "http" ? "HTTP / Custom API" : c.kind === "slack_webhook" ? "Slack webhook" : c.kind)}</td>
        <td className={td}><Badge tone="neutral">{c.sharing_scope === "folder" ? "Folder" : c.sharing_scope === "organization" ? "Organization" : "Existing restrictions"}</Badge>
          {!!c.folder_ids?.length && <p className="mt-1 text-xs text-muted-foreground">{c.folder_ids.map((id) => folders.find((f) => f.id === id)?.name ?? "Restricted folder").join(", ")}</p>}</td>
        <td className={td}><span className="text-xs">{c.granted_scopes == null ? "Scopes not verified" : c.granted_scopes.length + " verified scopes"}</span><div className="text-xs text-muted-foreground">{c.can_use === false ? "Use restricted" : "Available to use"} · Credentials hidden</div></td>
        <td className={td}><div className="flex flex-wrap justify-end gap-2">
          {(c.kind === "connector" || c.kind === "http") && <Button size="sm" variant="outline" disabled={busy === c.id || c.can_use === false} onClick={() => test(c)}>{busy === c.id ? "Testing…" : "Test"}</Button>}
          {c.kind === "http" && c.config?.auth_type === "oauth2_authorization_code" && c.can_manage && <Button size="sm" variant="outline" onClick={() => authorize(c)}>Authorize</Button>}
          <Button size="sm" variant="outline" disabled={!c.can_manage} onClick={() => setEditor({ connection: c })}>Edit</Button>
          <Button size="sm" variant="outline" disabled={!c.can_manage} onClick={async () => {
            if (!window.confirm("Delete " + c.name + "? Recipes must stop using this connection first.")) return;
            try { await http("/admin/recipe-connections/" + c.id, { method: "DELETE" }); setMsg({ ok: true, text: "Connection deleted" }); load(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Delete failed" }); }
          }}>Delete</Button>
        </div></td></tr>)}
      {loaded && items.length === 0 && <tr><td colSpan={5} className="p-8 text-center text-muted-foreground">No connections yet. Connect a service above, or create one while building a recipe.</td></tr>}
    </tbody></table></div>
    <section className="mt-6"><h2 className="mb-3 font-semibold">Recipe folders</h2><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{folders.map((f) => <div className="flex items-center gap-3 rounded-lg border bg-card p-4" key={f.id}><FolderClosed className="h-5 w-5 text-primary" /><div className="flex-1"><div className="font-medium">{f.name}</div><div className="text-xs text-muted-foreground">{f.use_group_ids.length} editor groups · {f.manage_group_ids.length} manager groups</div></div>{f.can_manage && <Button size="sm" variant="ghost" onClick={() => setFolderEditor({ folder: f })}>Manage</Button>}</div>)}</div>{!folders.length && <p className="text-sm text-muted-foreground">Create a folder to organize recipes and share connections with groups.</p>}</section>
    {editor && <ConnectionDialog title={editor.connection ? "Edit connection" : "Create connection"} onClose={() => setEditor(null)}><ConnectionEditor connection={editor.connection} initialConnector={editor.connector} onCancel={() => setEditor(null)} onSaved={() => { setEditor(null); setMsg({ ok: true, text: "Connection saved. Test it to verify authentication and scopes." }); load(); }} /></ConnectionDialog>}
    {folderEditor && <ConnectionDialog title={folderEditor.folder ? "Manage folder" : "New recipe folder"} onClose={() => setFolderEditor(null)}><FolderEditor folder={folderEditor.folder} onCancel={() => setFolderEditor(null)} onSaved={() => { setFolderEditor(null); load(); }} /></ConnectionDialog>}
  </div>;
}
