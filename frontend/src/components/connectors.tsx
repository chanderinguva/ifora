"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/bits";
import { SaveButton } from "@/components/save-button";
import type { ConnectorInfo } from "@/lib/recipes";
import type { User } from "@/lib/types";

export type ConnectorDraft = {
  connector: ConnectorInfo; id?: number; name: string; config: Record<string, string>; secrets: Record<string, string>; allowed_users: number[];
};

export const newConnectorDraft = (connector: ConnectorInfo): ConnectorDraft => ({ connector, name: connector.name, config: {}, secrets: {}, allowed_users: [] });

/** Why Save is disabled, or null when the form is complete. Secrets may stay empty only when editing (the stored value is kept). */
export function draftProblem(d: ConnectorDraft): string | null {
  if (!d.name.trim()) return "Give the connection a name.";
  for (const f of d.connector.auth.fields) {
    if (f.secret) { if (!d.id && !(d.secrets[f.key] ?? "").trim()) return `Enter ${f.label.toLowerCase()}.`; }
    else if (!(d.config[f.key] ?? "").trim()) return `Enter ${f.label.toLowerCase()}.`;
  }
  return null;
}

export function ConnectorCatalog({ items, disabled, onConnect }: { items: ConnectorInfo[]; disabled: boolean; onConnect: (c: ConnectorInfo) => void }) {
  if (items.length === 0) return null;
  return (
    <section className="mb-6" aria-labelledby="catalog-title" data-testid="connector-catalog">
      <h2 id="catalog-title" className="mb-2 text-sm font-semibold">Pre-built connectors</h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((c) => (
          <Card key={c.id} data-testid={`connector-${c.id}`}><CardContent className="flex h-full flex-col gap-2 pt-6">
            <div className="flex items-center gap-3">
              <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-sm font-semibold text-primary">{c.name.slice(0, 2).toUpperCase()}</span>
              <div className="min-w-0"><div className="font-medium leading-tight">{c.name}</div><Badge tone="neutral">{c.category}</Badge></div>
            </div>
            <p className="flex-1 text-sm text-muted-foreground">{c.description}</p>
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">{c.actions.length} actions</span>
              <Button size="sm" variant="outline" disabled={disabled} onClick={() => onConnect(c)} aria-label={`Connect ${c.name}`}>Connect</Button>
            </div>
          </CardContent></Card>
        ))}
      </div>
    </section>
  );
}

export function ConnectorConnectionForm({ draft, setDraft, admins, onSave, onCancel, dirty }: {
  draft: ConnectorDraft; setDraft: (d: ConnectorDraft) => void; admins: User[]; onSave: () => void; onCancel: () => void;
  /** Is there something to save? A new connection always is; an existing one only once it was changed. */
  dirty: boolean;
}) {
  const editing = draft.id !== undefined;
  const problem = draftProblem(draft);
  const c = draft.connector;
  return (
    <Card className="mb-6" data-testid="connector-connection-editor"><CardContent className="space-y-3 pt-6">
      <h2 className="text-sm font-semibold">{editing ? `Edit ${c.name} connection` : `Connect ${c.name}`}</h2>
      <p className="text-xs text-muted-foreground">
        Secrets are encrypted, never shown again, and only sent to {c.hosts.length === 1 && !c.hosts[0].includes("{") ? c.hosts[0] : `${c.name}'s own host`}.
        {editing && " Leave a secret empty to keep the stored one."}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1"><Label htmlFor="cc-name">Name</Label><Input id="cc-name" value={draft.name} maxLength={100} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></div>
        {c.auth.fields.filter((f) => !f.secret).map((f) => (
          <div key={f.key} className="space-y-1"><Label htmlFor={`cc-${f.key}`}>{f.label}</Label>
            <Input id={`cc-${f.key}`} value={draft.config[f.key] ?? ""} maxLength={f.max_length} autoComplete="off" onChange={(e) => setDraft({ ...draft, config: { ...draft.config, [f.key]: e.target.value } })} /></div>
        ))}
        {c.auth.fields.filter((f) => f.secret).map((f) => (
          <div key={f.key} className="space-y-1 sm:col-span-2"><Label htmlFor={`cc-${f.key}`}>{f.label}{editing && " (leave empty to keep the current one)"}</Label>
            <Input id={`cc-${f.key}`} type="password" autoComplete="off" value={draft.secrets[f.key] ?? ""} onChange={(e) => setDraft({ ...draft, secrets: { ...draft.secrets, [f.key]: e.target.value } })} /></div>
        ))}
        <fieldset className="space-y-1 sm:col-span-2" data-testid="connector-acl">
          <legend className="text-sm font-medium">Who can use this connection in recipes</legend>
          <p className="text-xs text-muted-foreground">Nobody ticked = every administrator.</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {admins.map((u) => (
              <label key={u.id} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={draft.allowed_users.includes(u.id)}
                  onChange={(e) => setDraft({ ...draft, allowed_users: e.target.checked ? [...draft.allowed_users, u.id] : draft.allowed_users.filter((x) => x !== u.id) })} /> {u.email}
              </label>
            ))}
          </div>
        </fieldset>
      </div>
      {problem && <p className="text-xs text-muted-foreground" data-testid="connector-problem">{problem}</p>}
      <div className="flex gap-2">
        <SaveButton dirty={dirty} disabled={problem !== null} onClick={onSave}>Save connection</SaveButton>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </CardContent></Card>
  );
}
