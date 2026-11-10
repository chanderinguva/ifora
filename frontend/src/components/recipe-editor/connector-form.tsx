"use client";

import Link from "next/link";
import { Label } from "@/components/ui/label";
import { fieldClass } from "@/components/bits";
import { PillInput } from "@/components/recipe-bits";
import type { Connection, ConnectorAction, ConnectorInfo, Pill, RecipeMeta } from "@/lib/recipes";

type Cfg = { connector?: string; connection_id?: number | null; action?: string; inputs?: Record<string, string> };

/** Values to start an action with: defaults for inputs that have one, empty text for the rest (the server asks for what is missing). */
function startingInputs(a: ConnectorAction, keep: Record<string, string> = {}): Record<string, string> {
  const out: Record<string, string> = {};
  for (const i of a.inputs) {
    if (keep[i.key] !== undefined) out[i.key] = keep[i.key];
    else if (i.default !== null && i.default !== undefined) out[i.key] = String(i.default);
  }
  return out;
}

export function connectorStartingConfig(connections: Connection[], meta: RecipeMeta): Cfg {
  const conn = connections.find((c) => c.kind === "connector" && c.can_use !== false);
  const con = meta.connectors?.find((c) => c.id === conn?.connector_id);
  const action = con?.actions[0];
  return { connector: con?.id ?? "", connection_id: conn?.id ?? null, action: action?.id ?? "", inputs: action ? startingInputs(action) : {} };
}

/** The step form for "Run a connector action": pick a connection, an action, and fill the action's declared inputs. */
export function ConnectorActionForm({ cfg, set, connections, meta, pills, payload, available }: {
  cfg: Cfg; set: (patch: Record<string, unknown>) => void; connections: Connection[]; meta: RecipeMeta; pills: Pill[]; payload: boolean; available: boolean;
}) {
  const usable = connections.filter((c) => c.kind === "connector" && (c.can_use !== false || c.id === cfg.connection_id));
  const selected = usable.find((c) => c.id === cfg.connection_id);
  const connector: ConnectorInfo | undefined = meta.connectors?.find((c) => c.id === (selected?.connector_id ?? cfg.connector));
  const action = connector?.actions.find((a) => a.id === cfg.action);
  const inputs = cfg.inputs ?? {};
  const setInput = (key: string, v: string) => {
    const next = { ...inputs };
    if (v === "") delete next[key]; else next[key] = v;
    set({ inputs: next });
  };

  function pickConnection(v: string) {
    const conn = usable.find((c) => c.id === Number(v));
    const con = meta.connectors?.find((c) => c.id === conn?.connector_id);
    if (!conn || !con) { set({ connection_id: null }); return; }
    if (con.id === cfg.connector && con.actions.some((a) => a.id === cfg.action)) { set({ connection_id: conn.id }); return; }
    const first = con.actions[0];
    set({ connection_id: conn.id, connector: con.id, action: first?.id ?? "", inputs: first ? startingInputs(first) : {} });
  }

  return (
    <div className="space-y-3" data-testid="connector-step-form">
      <div className="grid gap-3 md:grid-cols-2">
        <div className="space-y-1"><Label>Connection</Label>
          <select aria-label="Connection" className={fieldClass} value={cfg.connection_id ?? ""} onChange={(e) => pickConnection(e.target.value)}>
            <option value="">Choose a connection…</option>
            {usable.map((c) => <option key={c.id} value={c.id}>{c.name} ({meta.connectors?.find((x) => x.id === c.connector_id)?.name ?? c.connector_id})</option>)}
          </select>
          {usable.length === 0 && (
            <p className="text-xs text-muted-foreground">
              {available ? <>No connector connections yet. <Link className="underline" href="/admin/recipes/connections">Connect GitHub, Jira, Slack, PagerDuty or Entra ID</Link> first.</> : "Connections are unavailable until RECIPE_ENCRYPTION_KEY is configured."}
            </p>
          )}
        </div>
        <div className="space-y-1"><Label>Action</Label>
          <select aria-label="Action" className={fieldClass} value={cfg.action ?? ""} disabled={!connector}
            onChange={(e) => { const a = connector?.actions.find((x) => x.id === e.target.value); if (a) set({ action: a.id, inputs: startingInputs(a, inputs) }); }}>
            {!action && <option value="">Choose an action…</option>}
            {connector?.actions.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
          </select>
        </div>
      </div>

      {action && (
        <>
          {action.description && <p className="text-xs text-muted-foreground">{action.description}</p>}
          <div className="grid gap-3 md:grid-cols-2">
            {action.inputs.map((i) => {
              const label = i.label + (i.required ? " *" : "");
              const v = inputs[i.key] ?? "";
              return (
                <div key={i.key} className={"space-y-1" + (i.multiline ? " md:col-span-2" : "")}><Label>{label}</Label>
                  {i.type === "select" || i.type === "boolean" ? (
                    <select aria-label={i.label} className={fieldClass} value={v} onChange={(e) => setInput(i.key, e.target.value)}>
                      {!i.required && i.default == null && <option value="">(not set)</option>}
                      {(i.type === "boolean" ? ["true", "false"] : i.options).map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : (
                    <PillInput label={i.label} multiline={i.multiline} value={v} onChange={(nv) => setInput(i.key, nv)} pills={pills} payload={payload} />
                  )}
                </div>
              );
            })}
          </div>
          <p className="text-xs text-muted-foreground">
            {action.read_only || action.idempotent ? "Retried automatically if the service is briefly unavailable." : "Not retried automatically, so a change is never applied twice."}
            {" "}Later steps can use: {["status_code", "ok", ...action.outputs.filter((o) => o !== "status_code" && o !== "ok")].join(", ")}.
          </p>
        </>
      )}
    </div>
  );
}
