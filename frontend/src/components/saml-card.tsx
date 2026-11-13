"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldClass } from "@/components/bits";
import { http, qs, type Page } from "@/lib/http";
import { useDirty } from "@/lib/use-dirty";
import { SaveButton } from "@/components/save-button";
import type { User } from "@/lib/types";
import { SamlSetupGuide } from "@/components/saml-setup-guide";
import { SamlConfigTranslator } from "@/components/saml-config-translator";
import { mergeClaims } from "@/lib/saml-config-translator";

type Mapping = { name: string; source: string; filter?: { type: string; value: string }; required?: boolean };
type Preset = { id: string; label: string; mappings: Mapping[] };
type Preview = { name_id: string | null; attributes: { name: string; values: string[] }[]; missing_required: string[]; would_issue: boolean };
type Provider = {
  sp_entity_id: string; acs_url: string; audience: string | null; name_id_format: string; name_id_attribute: string | null; signing: string; attribute_mappings: Mapping[];
  has_sp_cert: boolean; sp_cert: string | null; require_signed_requests: boolean; default_relay_state: string | null; validity_seconds: number;
  idp: { entity_id: string; sso_url: string; metadata_url: string; certificate_fingerprint_sha256: string; certificate_pem: string };
};
type Info = { configured: boolean; provider: Provider | null; idp: { entity_id: string; sso_url: string; metadata_url: string } };
const SOURCES: [string, string][] = [["email", "Email"], ["username", "Username"], ["first_name", "First name"], ["last_name", "Last name"], ["display_name", "Display name"], ["groups", "Groups (multi-valued)"]];
const blank = { sp_entity_id: "", acs_url: "", audience: "", name_id_format: "email", name_id_attribute: "", signing: "both", sp_cert: "", require_signed_requests: false, default_relay_state: "", validity_seconds: 300 };
const DEFAULT_MAPS: Mapping[] = [{ name: "email", source: "email" }, { name: "firstName", source: "first_name" }, { name: "lastName", source: "last_name" }];

/** SAML 2.0 service-provider settings and the values the SP needs from us (ADR 011). */
export function SamlCard({ appId, onChange }: { appId: number; onChange: () => void }) {
  const [info, setInfo] = useState<Info | null>(null);
  const [f, setF] = useState(blank);
  const [maps, setMaps] = useState<Mapping[]>(DEFAULT_MAPS);
  const [xml, setXml] = useState("");
  const [presets, setPresets] = useState<Preset[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [pvUser, setPvUser] = useState("");
  const [pv, setPv] = useState<Preview | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const { dirty, markClean } = useDirty({ f, maps });   // the blank form is the baseline until saved settings replace it (see load)
  const load = useCallback(() => {
    http<Info>(`/admin/applications/${appId}/saml`).then((i) => {
      setInfo(i);
      const p = i.provider;
      if (p) {
        setF({ sp_entity_id: p.sp_entity_id, acs_url: p.acs_url, audience: p.audience ?? "", name_id_format: p.name_id_format, name_id_attribute: p.name_id_attribute ?? "", signing: p.signing, sp_cert: p.sp_cert ?? "",
          require_signed_requests: p.require_signed_requests, default_relay_state: p.default_relay_state ?? "", validity_seconds: p.validity_seconds });
        setMaps(p.attribute_mappings);
        markClean();   // only when the server's settings replaced the form: otherwise what was already typed must stay "changed"
      }
    }).catch((e) => setMsg({ ok: false, text: e.message }));
  }, [appId, markClean]);
  useEffect(load, [load]);
  useEffect(() => {
    http<{ items: Preset[] }>("/admin/applications/saml/presets").then((r) => setPresets(r.items)).catch(() => {});
    http<Page<User>>(`/admin/users${qs({ count: 100 })}`).then((p) => setUsers(p.Resources)).catch(() => {});
  }, []);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); load(); onChange(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }
  const set = (p: Partial<typeof blank>) => setF({ ...f, ...p });
  const idp = info?.idp;

  return (
    <Card className="mb-6" data-testid="saml-facet">
      <CardHeader><CardTitle>SAML 2.0</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-sm">
        {msg && <Alert variant={msg.ok ? "default" : "destructive"} role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
        {idp && <SamlSetupGuide key={appId} idp={idp} provider={info?.provider ?? null} dirty={dirty} />}
        <SamlConfigTranslator current={{ acs_url: f.acs_url, sp_entity_id: f.sp_entity_id, audience: f.audience, name_id_format: f.name_id_format, signing: f.signing, claims: maps }}
          onApply={(plan) => { setF((old) => ({ ...old, ...plan.fields })); setMaps((old) => mergeClaims(old, plan.claims)); }} />

        {idp && (
          <div className="space-y-1 rounded-md border p-3" data-testid="saml-idp-info">
            <div className="font-medium">Give these to the application (identity provider details)</div>
            <div>Metadata URL: <a className="break-all underline underline-offset-4" href={idp.metadata_url} target="_blank" rel="noopener noreferrer">{idp.metadata_url}</a></div>
            <div>IdP entity ID: <code className="break-all">{idp.entity_id}</code></div>
            <div>Single sign-on URL (Redirect and POST): <code className="break-all">{idp.sso_url}</code></div>
            {info?.provider && <div>Signing certificate SHA-256: <code className="break-all">{info.provider.idp.certificate_fingerprint_sha256}</code></div>}
          </div>
        )}

        <div className="space-y-1">
          <Label htmlFor="s-meta">Import the application&apos;s SAML metadata (paste XML; nothing is fetched)</Label>
          <textarea id="s-meta" rows={3} className={fieldClass} value={xml} onChange={(e) => setXml(e.target.value)} />
          <Button size="sm" variant="outline" disabled={!xml.trim()} onClick={() => run(async () => {
            const m = await http<{ sp_entity_id: string; acs_url: string; sp_cert: string | null; wants_signed_requests: boolean }>("/admin/applications/saml/import-metadata", { method: "POST", body: { xml } });
            setF({ ...f, sp_entity_id: m.sp_entity_id, acs_url: m.acs_url, sp_cert: m.sp_cert ?? f.sp_cert });
            setXml("");
          }, "Metadata read — review the fields below and save")}>Read metadata</Button>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1"><Label htmlFor="s-ent">SP entity ID (issuer)</Label><Input id="s-ent" value={f.sp_entity_id} onChange={(e) => set({ sp_entity_id: e.target.value })} /></div>
          <div className="space-y-1"><Label htmlFor="s-acs">Assertion consumer service (ACS) URL</Label><Input id="s-acs" placeholder="https://app.example.com/saml/acs" value={f.acs_url} onChange={(e) => set({ acs_url: e.target.value })} /></div>
          <div className="space-y-1"><Label htmlFor="s-aud">Audience (optional, defaults to the entity ID)</Label><Input id="s-aud" value={f.audience} onChange={(e) => set({ audience: e.target.value })} /></div>
          <div className="space-y-1"><Label htmlFor="s-nid">Name ID</Label>
            <select id="s-nid" className={fieldClass} value={f.name_id_format} onChange={(e) => set({ name_id_format: e.target.value })}>
              <option value="email">Email address</option><option value="username">Username</option>
              <option value="attribute">A profile attribute…</option><option value="persistent">Persistent (opaque, different for every application)</option>
            </select></div>
          {f.name_id_format === "attribute" && (
            <div className="space-y-1"><Label htmlFor="s-nida">Profile attribute for the Name ID</Label>
              <Input id="s-nida" placeholder="attr:employee_id" value={f.name_id_attribute} onChange={(e) => set({ name_id_attribute: e.target.value })} /></div>
          )}
          <div className="space-y-1"><Label htmlFor="s-sig">Sign</Label>
            <select id="s-sig" className={fieldClass} value={f.signing} onChange={(e) => set({ signing: e.target.value })}>
              <option value="both">Assertion and response</option><option value="assertion">Assertion only</option><option value="response">Response only</option>
            </select></div>
          <div className="space-y-1"><Label htmlFor="s-val">Assertion valid for (seconds)</Label><Input id="s-val" type="number" min={60} max={3600} value={f.validity_seconds} onChange={(e) => set({ validity_seconds: Number(e.target.value) })} /></div>
          <div className="space-y-1 sm:col-span-2"><Label htmlFor="s-relay">Default RelayState (optional)</Label><Input id="s-relay" value={f.default_relay_state} onChange={(e) => set({ default_relay_state: e.target.value })} /></div>
          <div className="space-y-1 sm:col-span-2"><Label htmlFor="s-cert">SP signing certificate (PEM, optional — verifies signed requests)</Label>
            <textarea id="s-cert" rows={3} className={fieldClass} value={f.sp_cert} onChange={(e) => set({ sp_cert: e.target.value })} /></div>
          <label className="flex items-center gap-2 sm:col-span-2"><input type="checkbox" checked={f.require_signed_requests} onChange={(e) => set({ require_signed_requests: e.target.checked })} /> Reject requests that are not signed with that certificate</label>
        </div>

        <fieldset className="space-y-2" data-testid="saml-attributes">
          <legend className="font-medium">Attributes sent in the assertion</legend>
          <p className="text-xs text-muted-foreground">Applications that create accounts on first sign-in (just-in-time) read these. Mark an attribute <em>required</em> to refuse the sign-in, with a clear message, when a user&apos;s profile lacks it, instead of sending an incomplete assertion.</p>
          {presets.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <select aria-label="Start from a preset" className={`${fieldClass} !w-72`} value="" onChange={(e) => { const pr = presets.find((x) => x.id === e.target.value); if (pr) setMaps(pr.mappings.map((m) => ({ ...m }))); }}>
                <option value="">Start from a preset…</option>
                {presets.map((pr) => <option key={pr.id} value={pr.id}>{pr.label}</option>)}
              </select>
            </div>
          )}
          {maps.map((m, i) => {
            const kind = m.source.startsWith("expr:") ? "expr" : m.source.startsWith("attr:") ? "attr" : m.source;
            const upd = (p: Partial<Mapping>) => setMaps(maps.map((x, j) => (j === i ? { ...x, ...p } : x)));
            return (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <Input aria-label={`Attribute name ${i + 1}`} className="!w-48" value={m.name} onChange={(e) => upd({ name: e.target.value })} />
                <select aria-label={`Attribute source ${i + 1}`} className={`${fieldClass} !w-52`} value={kind}
                  onChange={(e) => { const k = e.target.value; const base = { filter: undefined } as Partial<Mapping>; upd({ ...base, source: k === "attr" ? "attr:" : k === "expr" ? "expr:" : k }); }}>
                  {SOURCES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  <option value="attr">Profile attribute…</option><option value="expr">Expression…</option>
                </select>
                {kind === "attr" && <Input aria-label={`Profile attribute key ${i + 1}`} placeholder="department" className="!w-40" value={m.source.slice(5)} onChange={(e) => upd({ source: `attr:${e.target.value}` })} />}
                {kind === "expr" && <Input aria-label={`Expression ${i + 1}`} placeholder={'String.toUpperCase(user.department)'} className="!w-72 font-mono text-xs" value={m.source.slice(5)} onChange={(e) => upd({ source: `expr:${e.target.value}` })} />}
                {kind === "groups" && (<>
                  <select aria-label={`Group filter ${i + 1}`} className={`${fieldClass} !w-40`} value={m.filter?.type ?? ""} onChange={(e) => upd({ filter: e.target.value ? { type: e.target.value, value: m.filter?.value ?? "" } : undefined })}>
                    <option value="">All groups</option><option value="starts_with">Name starts with</option><option value="equals">Name equals</option><option value="contains">Name contains</option>
                  </select>
                  {m.filter && <Input aria-label={`Group filter value ${i + 1}`} className="!w-36" value={m.filter.value} onChange={(e) => upd({ filter: { type: m.filter!.type, value: e.target.value } })} />}
                </>)}
                <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={!!m.required} onChange={(e) => upd({ required: e.target.checked })} /> required</label>
                <Button size="sm" variant="ghost" aria-label={`Remove attribute ${m.name}`} onClick={() => setMaps(maps.filter((_, j) => j !== i))}>Remove</Button>
              </div>
            );
          })}
          <Button size="sm" variant="outline" onClick={() => setMaps([...maps, { name: "", source: "email" }])}>Add attribute</Button>
        </fieldset>

        {info?.configured && (
          <div className="space-y-2 rounded-md border p-3" data-testid="saml-preview">
            <div className="font-medium">Preview what the application receives (save first)</div>
            <div className="flex flex-wrap gap-2">
              <select aria-label="Preview as user" className={`${fieldClass} !w-72`} value={pvUser} onChange={(e) => { setPvUser(e.target.value); setPv(null); }}>
                <option value="">Choose a user…</option>
                {users.map((u) => <option key={u.id} value={u.id}>{u.first_name} {u.last_name} ({u.email})</option>)}
              </select>
              <Button size="sm" variant="outline" disabled={!pvUser} onClick={() => run(async () => { setPv(await http<Preview>(`/admin/applications/${appId}/saml/preview?user_id=${pvUser}`)); }, "Preview ready")}>Preview</Button>
            </div>
            {pv && (
              <div className="space-y-1" data-testid="saml-preview-result">
                <div>Name ID: <code>{pv.name_id ?? "(missing)"}</code> · {pv.would_issue ? "would sign in" : <strong className="text-destructive">would be refused: missing {pv.missing_required.join(", ")}</strong>}</div>
                <ul className="list-disc pl-5">{pv.attributes.map((a) => <li key={a.name}><code>{a.name}</code> = {a.values.join(", ")}</li>)}</ul>
              </div>
            )}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <SaveButton dirty={dirty} disabled={!f.sp_entity_id.trim() || !f.acs_url.trim()} onClick={() => run(() => http(`/admin/applications/${appId}/saml`, { method: "PUT", body: {
            ...f, name_id_attribute: f.name_id_format === "attribute" ? f.name_id_attribute : null, audience: f.audience || null, sp_cert: f.sp_cert || null, default_relay_state: f.default_relay_state || null, attribute_mappings: maps } }), "SAML settings saved")}>Save SAML settings</SaveButton>
          {info?.configured && <Button variant="outline" onClick={() => { if (confirm("Remove the SAML configuration? Users will no longer be able to sign in to this application.")) run(() => http(`/admin/applications/${appId}/saml`, { method: "DELETE" }), "SAML configuration removed"); }}>Remove</Button>}
        </div>
      </CardContent>
    </Card>
  );
}

