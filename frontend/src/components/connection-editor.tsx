"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Plus, X, LockKeyhole, Globe2, FolderClosed } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldClass } from "@/components/bits";
import { http, qs, type Page } from "@/lib/http";
import type { Connection, ConnectorInfo, RecipeFolder } from "@/lib/recipes";
import type { Group } from "@/lib/types";

export function ConnectionDialog({ children, onClose, title }: { children: React.ReactNode; onClose: () => void; title: string }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => { const d = ref.current; d?.showModal(); return () => d?.close(); }, []);
  return <dialog ref={ref} aria-labelledby={titleId} onCancel={(e) => { e.preventDefault(); onClose(); }}
    className="m-auto max-h-[90dvh] w-[min(54rem,95vw)] overflow-y-auto rounded-xl border bg-background p-0 text-foreground shadow-xl backdrop:bg-black/40">
    <div className="sticky top-0 z-10 flex items-center justify-between border-b bg-background px-6 py-4">
      <h2 id={titleId} className="text-lg font-semibold">{title}</h2><Button type="button" variant="ghost" size="sm" aria-label="Close connection dialog" onClick={onClose}><X className="h-4 w-4" /></Button>
    </div><div className="p-6">{children}</div>
  </dialog>;
}

/** Search-backed group picker: no per-administrator checkboxes or fixed first-100-user limit. */
export function GroupPicker({ label, value, onChange }: { label: string; value: number[]; onChange: (ids: number[]) => void }) {
  const [search, setSearch] = useState("");
  const [found, setFound] = useState<Group[]>([]);
  const [names, setNames] = useState<Record<number, string>>({});
  const [error, setError] = useState("");
  const id = useId();
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      const safe = search.replace(/["\\]/g, "");
      http<Page<Group>>("/admin/groups" + qs({ count: 20, filter: safe ? 'name co "' + safe + '"' : undefined }))
        .then((p) => { if (active) { setFound(p.Resources); setNames((n) => ({ ...n, ...Object.fromEntries(p.Resources.map((g) => [g.id, g.name])) })); setError(""); } })
        .catch(() => { if (active) setError("Group search is unavailable. Try again before saving."); });
    }, 200);
    return () => { active = false; clearTimeout(timer); };
  }, [search]);
  useEffect(() => {
    let active = true;
    for (const gid of value) if (!names[gid]) http<Group>("/admin/groups/" + gid).then((g) => { if (active) setNames((n) => ({ ...n, [g.id]: g.name })); }).catch(() => {});
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.join(",")]);
  return <fieldset className="space-y-2"><legend className="mb-1 text-sm font-medium">{label}</legend>
    <div className="flex flex-wrap gap-2">{value.map((gid) => <Button type="button" variant="secondary" size="sm" key={gid} onClick={() => onChange(value.filter((x) => x !== gid))} aria-label={"Remove " + (names[gid] ?? "group " + gid)}>{names[gid] ?? "Group " + gid}<X className="ml-2 h-3 w-3" /></Button>)}</div>
    <Label htmlFor={id} className="sr-only">Search {label.toLowerCase()}</Label><Input id={id} value={search} placeholder="Search groups…" onChange={(e) => setSearch(e.target.value)} />
    {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : <div className="flex max-h-28 flex-wrap gap-1 overflow-y-auto">{found.filter((g) => !value.includes(g.id)).map((g) =>
      <Button type="button" size="sm" variant="ghost" key={g.id} onClick={() => onChange([...value, g.id])}><Plus className="mr-1 h-3 w-3" />{g.name}</Button>)}
      {found.length === 0 && <p className="text-xs text-muted-foreground">No matching groups.</p>}</div>}
  </fieldset>;
}

export type Sharing = { sharing_scope: "legacy" | "organization" | "folder"; folder_ids: number[]; use_group_ids: number[]; manage_group_ids: number[] };
export const sharingFor = (c?: Connection, folderId?: number | null): Sharing => ({
  sharing_scope: c?.sharing_scope ?? (folderId ? "folder" : "organization"), folder_ids: c?.folder_ids ?? (folderId ? [folderId] : []),
  use_group_ids: c?.use_group_ids ?? [], manage_group_ids: c?.manage_group_ids ?? [],
});

export function SharingFields({ value, setValue, folders, legacy }: { value: Sharing; setValue: (v: Sharing) => void; folders: RecipeFolder[]; legacy?: boolean }) {
  return <section className="space-y-4 rounded-lg border p-4" aria-label="Connection access">
    <div><h3 className="font-medium">Connection access</h3><p className="text-xs text-muted-foreground">Permission to use a connection never reveals its credentials.</p></div>
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="space-y-1"><Label htmlFor="connection-scope">Availability</Label><select id="connection-scope" className={fieldClass} value={value.sharing_scope} onChange={(e) => setValue({ ...value, sharing_scope: e.target.value as Sharing["sharing_scope"], use_group_ids: [] })}>
        {legacy && <option value="legacy">Keep existing restrictions</option>}<option value="organization">Organization</option><option value="folder">Selected folders</option>
      </select></div>
      {value.sharing_scope !== "legacy" && <div className="space-y-1"><Label htmlFor="connection-folders">{value.sharing_scope === "folder" ? "Folders (required)" : "Limit to folders (optional)"}</Label>
        <select multiple id="connection-folders" className={fieldClass} value={value.folder_ids.map(String)} onChange={(e) => setValue({ ...value, folder_ids: Array.from(e.target.selectedOptions, (o) => Number(o.value)) })}>
          {folders.filter((f) => f.can_manage).map((f) => <option value={f.id} key={f.id}>{f.name}</option>)}
        </select><p className="text-xs text-muted-foreground">{value.sharing_scope === "organization" ? "No selection makes it available across the organization." : "Members inherit permission to use it from their folder."}</p>
      </div>}
    </div>
    {value.sharing_scope === "legacy" ? <p className="text-sm text-muted-foreground">Existing restrictions will be preserved. Choose organization or folders to explicitly replace them.</p> : <>
      {value.sharing_scope === "organization" && <><GroupPicker label="Groups that can use this connection" value={value.use_group_ids} onChange={(ids) => setValue({ ...value, use_group_ids: ids })} /><p className="text-xs text-muted-foreground">No groups selected: all administrators with automation access can use it.</p></>}
      <GroupPicker label="Connection manager groups" value={value.manage_group_ids} onChange={(ids) => setValue({ ...value, manage_group_ids: ids })} />
      <p className="text-xs text-muted-foreground">Super administrators retain management access. Organization connections retain their creator; folder connections follow current folder managers. Membership of access groups is protected.</p>
    </>}
  </section>;
}

type Binding = { secret_key: string; location: "header" | "query" | "json" | "form"; name: string };
type AuthConfig = { auth_type: string; bindings: Binding[]; client_id: string; token_url: string; authorization_url: string; scope: string; client_auth: string };
const authDefault = (): AuthConfig => ({ auth_type: "none", bindings: [], client_id: "", token_url: "", authorization_url: "", scope: "", client_auth: "basic" });
const AUTH_LABELS: Record<string, string> = { none: "No authentication", basic: "Basic authentication", bearer: "Bearer token", api_key: "API key", custom: "Custom secret fields", oauth2_client_credentials: "OAuth 2.0 · Client credentials", oauth2_authorization_code: "OAuth 2.0 · Authorization code + PKCE" };

export function ConnectionEditor({ connection, initialConnector, folderId, onSaved, onCancel }: {
  connection?: Connection; initialConnector?: string; folderId?: number | null; onSaved: (c: Connection) => void; onCancel: () => void;
}) {
  const [catalog, setCatalog] = useState<ConnectorInfo[]>([]);
  const [folders, setFolders] = useState<RecipeFolder[]>([]);
  const [type, setType] = useState(connection?.connector_id ?? (connection?.kind === "slack_webhook" ? "slack_webhook" : initialConnector ?? "http"));
  const [name, setName] = useState(connection?.name ?? "");
  const [host, setHost] = useState(connection?.allowed_host ?? "");
  const [paths, setPaths] = useState((connection?.allowed_paths ?? []).join("\n"));
  const [config, setConfig] = useState<Record<string, any>>(connection?.kind === "connector" ? connection.config ?? {} : {});
  const [auth, setAuth] = useState<AuthConfig>(() => ({ ...authDefault(), ...(connection?.kind === "http" ? connection.config : connection && !["connector", "slack_webhook"].includes(connection.kind) ? {
    auth_type: connection.kind === "header" ? "api_key" : connection.kind, client_id: connection.client_id ?? "", token_url: connection.token_url ?? "", scope: connection.scope ?? "",
    bindings: connection.kind === "header" ? [{ secret_key: "api_key", location: "header", name: connection.header_name ?? "X-Api-Key" }] : [],
  } : {}) }));
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [sharing, setSharing] = useState<Sharing>(() => sharingFor(connection, folderId));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selected = catalog.find((c) => c.id === type);
  const editing = !!connection;
  const converting = !!connection && !["http", "connector", "slack_webhook"].includes(connection.kind);
  useEffect(() => {
    http<{ items: ConnectorInfo[] }>("/admin/connectors").then((r) => setCatalog(r.items)).catch(() => setError("Could not load connectors."));
    http<{ items: RecipeFolder[] }>("/admin/recipe-folders").then((r) => setFolders(r.items)).catch(() => setError("Could not load folder permissions."));
  }, []);
  function choose(next: string) { setType(next); setSecrets({}); setConfig({}); setError(""); if (!name) setName(catalog.find((c) => c.id === next)?.name ?? ""); }
  const credentialKeys = type === "slack_webhook" ? ["webhook_url"] : selected ? selected.auth.fields.filter((f) => f.secret).map((f) => f.key) :
    auth.auth_type === "basic" ? ["username", "password"] : auth.auth_type === "bearer" ? ["token"] :
    auth.auth_type.startsWith("oauth2") ? auth.client_auth === "none" ? [] : ["client_secret"] : auth.bindings.map((b) => b.secret_key);
  const labels = Object.fromEntries(selected?.auth.fields.map((f) => [f.key, f.label]) ?? []);
  const setCredential = (key: string, v: string) => setSecrets((s) => ({ ...s, [key]: v }));
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try {
      const supplied = Object.fromEntries(Object.entries(secrets).filter(([, v]) => v !== ""));
      if (converting && credentialKeys.some((k) => !supplied[k])) throw new Error("Re-enter the credentials to migrate this connection.");
      if (sharing.sharing_scope === "folder" && sharing.folder_ids.length === 0) throw new Error("Select at least one folder, or create one on the Connections page.");
      const body: Record<string, unknown> = { name: name.trim(), ...sharing };
      let path: string;
      if (selected) { path = "/admin/connectors/" + selected.id + "/connections"; Object.assign(body, { config, secrets: supplied }); }
      else if (type === "slack_webhook") { path = "/admin/recipe-connections"; Object.assign(body, { kind: "slack_webhook", secret: supplied.webhook_url || null }); }
      else { path = "/admin/recipe-connections/http"; Object.assign(body, { allowed_host: host.trim(), allowed_paths: paths.split("\n").map((p) => p.trim()).filter(Boolean), config: auth, secrets: supplied }); }
      if (connection) path += "/" + connection.id;
      const saved = await http<Connection>(path, { method: editing ? "PUT" : "POST", body });
      setSecrets({}); onSaved(saved);
    } catch (e) { setError(e instanceof Error ? e.message : "Connection could not be saved."); }
    finally { setBusy(false); }
  }
  return <form onSubmit={save} className="space-y-5" data-testid="connection-editor">
    <div className="flex items-start gap-3 rounded-lg bg-muted/50 p-3"><LockKeyhole className="mt-0.5 h-5 w-5 shrink-0 text-primary" /><p className="text-sm text-muted-foreground">Credentials are encrypted and write-only. They are injected when a recipe runs, never copied into its definition. {editing && "Leave credential fields empty to keep their saved values when settings stay the same."}</p></div>
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="space-y-1"><Label htmlFor="new-connection-type">Service</Label><select id="new-connection-type" className={fieldClass} value={type} disabled={editing} onChange={(e) => choose(e.target.value)}>
        <option value="http">HTTP / Custom API</option>{catalog.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}<option value="slack_webhook">Slack incoming webhook</option>
      </select></div>
      <div className="space-y-1"><Label htmlFor="new-connection-name">Connection name<span aria-hidden="true"> (required)</span></Label><Input id="new-connection-name" required maxLength={100} value={name} placeholder="Slack · Operations" onChange={(e) => setName(e.target.value)} /></div>
      {selected?.auth.fields.filter((f) => !f.secret).map((f) => <div key={f.key} className="space-y-1"><Label htmlFor={"conn-config-" + f.key}>{f.label}<span aria-hidden="true"> (required)</span></Label><Input id={"conn-config-" + f.key} required maxLength={f.max_length} value={config[f.key] ?? ""} onChange={(e) => setConfig({ ...config, [f.key]: e.target.value })} /></div>)}
      {type === "http" && <>
        <div className="space-y-1"><Label htmlFor="new-connection-host">Allowed API host<span aria-hidden="true"> (required)</span></Label><Input id="new-connection-host" required placeholder="api.example.com" value={host} onChange={(e) => setHost(e.target.value)} /><p className="text-xs text-muted-foreground">HTTPS only. Credentials cannot be sent to another host.</p></div>
        <div className="space-y-1"><Label htmlFor="new-connection-auth">Authentication</Label><select id="new-connection-auth" className={fieldClass} value={auth.auth_type} onChange={(e) => { const t = e.target.value; setAuth({ ...auth, auth_type: t, bindings: ["api_key", "custom"].includes(t) ? [{ secret_key: "api_key", location: "header", name: "X-Api-Key" }] : [] }); setSecrets({}); }}>{Object.entries(AUTH_LABELS).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></div>
        <div className="space-y-1 sm:col-span-2"><Label htmlFor="new-connection-paths">Allowed path prefixes (optional, one per line)</Label><textarea id="new-connection-paths" className={fieldClass} rows={2} placeholder="/api/v1/" value={paths} onChange={(e) => setPaths(e.target.value)} /></div>
        {auth.auth_type.startsWith("oauth2") && <>
          {[["client_id", "Client ID"], ["token_url", "Token endpoint URL"], ...(auth.auth_type === "oauth2_authorization_code" ? [["authorization_url", "Authorization endpoint URL"]] : []), ["scope", "Requested scopes"]].map(([key, label]) =>
            <div className="space-y-1" key={key}><Label htmlFor={"http-" + key}>{label}<span aria-hidden="true">{key === "scope" ? " (optional)" : " (required)"}</span></Label><Input id={"http-" + key} required={key !== "scope"} value={String(auth[key as keyof AuthConfig])} onChange={(e) => setAuth({ ...auth, [key]: e.target.value })} /></div>)}
          <div className="space-y-1"><Label htmlFor="client-auth">Client authentication</Label><select id="client-auth" className={fieldClass} value={auth.client_auth} onChange={(e) => setAuth({ ...auth, client_auth: e.target.value })}><option value="basic">Basic header</option><option value="post">Form body</option><option value="none">Public client (no client secret)</option></select></div>
          {auth.auth_type === "oauth2_authorization_code" && <p className="text-xs text-muted-foreground sm:col-span-2">Save first, then choose Authorize on the connection. Configure its exact callback URL on the server and in your OAuth application.</p>}
        </>}
      </>}
    </div>
    {type === "http" && ["api_key", "custom"].includes(auth.auth_type) && <section className="space-y-3 rounded-lg border p-4"><h3 className="font-medium">Secret field destinations</h3><p className="text-xs text-muted-foreground">Choose where each encrypted field is sent. JSON body fields are top-level keys. Never paste credentials into recipe headers or bodies.</p>
      {auth.bindings.map((b, i) => <div key={i} className="grid items-end gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]">
        <div><Label htmlFor={"binding-key-" + i}>Secret name<span aria-hidden="true"> (required)</span></Label><Input id={"binding-key-" + i} required pattern="[a-z][a-z0-9_]{0,39}" value={b.secret_key} onChange={(e) => setAuth({ ...auth, bindings: auth.bindings.map((x, j) => j === i ? { ...x, secret_key: e.target.value } : x) })} /></div>
        <div><Label htmlFor={"binding-location-" + i}>Send in</Label><select id={"binding-location-" + i} className={fieldClass} value={b.location} onChange={(e) => setAuth({ ...auth, bindings: auth.bindings.map((x, j) => j === i ? { ...x, location: e.target.value as Binding["location"] } : x) })}><option value="header">Header</option><option value="query">Query parameter</option><option value="json">JSON body</option><option value="form">Form body</option></select></div>
        <div><Label htmlFor={"binding-name-" + i}>Field name<span aria-hidden="true"> (required)</span></Label><Input id={"binding-name-" + i} required value={b.name} onChange={(e) => setAuth({ ...auth, bindings: auth.bindings.map((x, j) => j === i ? { ...x, name: e.target.value } : x) })} /></div>
        <Button type="button" variant="ghost" aria-label={"Remove secret field " + (i + 1)} onClick={() => setAuth({ ...auth, bindings: auth.bindings.filter((_, j) => j !== i) })}><X className="h-4 w-4" /></Button>
      </div>)}
      <Button type="button" size="sm" variant="outline" disabled={auth.bindings.length >= 20} onClick={() => setAuth({ ...auth, bindings: [...auth.bindings, { secret_key: "secret_" + (auth.bindings.length + 1), location: "header", name: "" }] })}>Add secret field</Button>
    </section>}
    {[...new Set(credentialKeys)].map((key) => <div key={key} className="space-y-1"><Label htmlFor={"conn-secret-" + key}>{labels[key] ?? key.replaceAll("_", " ")}{editing && !converting ? " (leave empty to keep)" : " (required)"}</Label>
      <Input aria-label={labels[key] ?? key.replaceAll("_", " ")} id={"conn-secret-" + key} type="password" autoComplete="new-password" spellCheck={false} required={!editing || converting} value={secrets[key] ?? ""} onChange={(e) => setCredential(key, e.target.value)} />
    </div>)}
    {selected && <section className="rounded-lg bg-muted/50 p-3"><h3 className="text-sm font-medium">{selected.actions.length} ready-made actions</h3><p className="mt-1 text-sm text-muted-foreground">{selected.actions.map((a) => a.label).join(" · ")}</p><p className="mt-2 text-xs text-muted-foreground">Test the connection after saving to discover available scopes when the provider supports it.</p></section>}
    <SharingFields value={sharing} setValue={setSharing} folders={folders} legacy={connection?.sharing_scope === "legacy"} />
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div className="flex gap-2 border-t pt-4"><Button type="submit" disabled={busy}>{busy ? "Saving…" : editing ? "Save connection" : "Create connection"}</Button><Button type="button" variant="ghost" disabled={busy} onClick={onCancel}>Cancel</Button></div>
  </form>;
}

/** Same dialog is used by templates, HTTP steps and pre-built actions; it never navigates away. */
export function InlineConnection({ folderId, connector, onCreated }: { folderId?: number | null; connector?: string; onCreated: (c: Connection) => void }) {
  const [open, setOpen] = useState(false);
  return <><Button type="button" variant="ghost" size="sm" onClick={() => setOpen(true)}><Plus className="mr-1 h-3 w-3" />Create connection</Button>
    {open && <ConnectionDialog title="Create connection" onClose={() => setOpen(false)}><ConnectionEditor folderId={folderId} initialConnector={connector} onCancel={() => setOpen(false)} onSaved={(c) => { onCreated(c); setOpen(false); }} /></ConnectionDialog>}</>;
}

export function AuthorizeConnection({ connection, onRefresh }: { connection: Connection; onRefresh?: (c: Connection) => void }) {
  const [error, setError] = useState("");
  useEffect(() => {
    if (!onRefresh) return;
    const refresh = () => { http<{ items: Connection[] }>("/admin/recipe-connections").then((r) => { const c = r.items.find((x) => x.id === connection.id); if (c) onRefresh(c); }).catch(() => {}); };
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [connection.id, onRefresh]);
  if (connection.kind !== "http" || connection.config?.auth_type !== "oauth2_authorization_code") return null;
  return <div className="space-y-1"><Button type="button" variant="outline" size="sm" disabled={!connection.can_manage} onClick={async () => {
    setError("");
    const tab = window.open("about:blank", "_blank"); if (tab) tab.opener = null;
    try { const r = await http<{ authorization_url: string }>("/admin/recipe-connections/" + connection.id + "/oauth/start", { method: "POST" }); if (tab) tab.location.href = r.authorization_url; else setError("Allow popups and try again."); }
    catch (e) { tab?.close(); setError(e instanceof Error ? e.message : "Authorization could not start."); }
  }}>{connection.oauth_authorized ? "Reauthorize connection" : "Authorize connection"}</Button>
    {!connection.oauth_authorized && <p className="text-xs text-muted-foreground">Authorize in a new tab before running this action. Your recipe stays open.</p>}
    {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
  </div>;
}

export function FolderEditor({ folder, onSaved, onCancel }: { folder?: RecipeFolder; onSaved: () => void; onCancel: () => void }) {
  const [name, setName] = useState(folder?.name ?? "");
  const [use, setUse] = useState(folder?.use_group_ids ?? []);
  const [manage, setManage] = useState(folder?.manage_group_ids ?? []);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return <form className="space-y-4" onSubmit={async (e) => { e.preventDefault(); setBusy(true); try { await http("/admin/recipe-folders" + (folder ? "/" + folder.id : ""), { method: folder ? "PUT" : "POST", body: { name, use_group_ids: use, manage_group_ids: manage } }); onSaved(); } catch (e) { setError(e instanceof Error ? e.message : "Could not save folder."); } finally { setBusy(false); } }}>
    <div><Label htmlFor="folder-name">Folder name<span aria-hidden="true"> (required)</span></Label><Input id="folder-name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} /></div>
    <GroupPicker label="Recipe editor groups" value={use} onChange={setUse} /><p className="text-xs text-muted-foreground">Members with automation access can edit recipes and use connections assigned to this folder.</p>
    <GroupPicker label="Folder manager groups" value={manage} onChange={setManage} /><p className="text-xs text-muted-foreground">Managers can publish recipes, change folder access and assign connections. The creator and super administrators retain management access.</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}<div className="flex gap-2"><Button disabled={busy}>{busy ? "Saving…" : "Save folder"}</Button><Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button></div>
  </form>;
}
