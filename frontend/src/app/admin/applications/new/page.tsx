"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Bookmark, KeyRound, Server, ShieldCheck, Globe, Smartphone, Layers, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader, fieldClass } from "@/components/bits";
import { http } from "@/lib/http";
import { cn } from "@/lib/utils";
import type { AppSummary, AppTemplate, Template } from "@/lib/applications";
import { CATALOG, type CatalogEntry } from "@/lib/app-catalog";

type Method = "oidc" | "saml" | "swa" | "api" | "bookmark" | "none";
const METHODS: { id: Method; title: string; icon: typeof Globe; text: string }[] = [
  { id: "oidc", title: "OIDC – OpenID Connect", icon: ShieldCheck, text: "Token-based sign-in for web, single-page and native apps." },
  { id: "saml", title: "SAML 2.0", icon: KeyRound, text: "XML assertions for enterprise apps that support SAML single sign-on." },
  { id: "swa", title: "SWA – Secure Web Authentication", icon: Layers, text: "Stores each user's own password for apps that only have a login form." },
  { id: "api", title: "API Services", icon: Server, text: "Machine-to-machine access with client credentials; no user sign-in." },
  { id: "bookmark", title: "Bookmark app", icon: Bookmark, text: "A link on the user's My apps page; no single sign-on." },
  { id: "none", title: "Provisioning only", icon: Layers, text: "No sign-on. Use it to push users to another system." },
];
const OIDC_TYPES: { id: string; icon: typeof Globe }[] = [{ id: "web", icon: Globe }, { id: "spa", icon: Layers }, { id: "native", icon: Smartphone }];

const lines = (v: string) => v.split("\n").map((x) => x.trim()).filter(Boolean);

function Pick({ selected, onClick, icon: Icon, title, text, testid }: { selected: boolean; onClick: () => void; icon: typeof Globe; title: string; text: string; testid: string }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={selected} data-testid={testid}
      className={cn("flex w-full items-start gap-3 rounded-lg border p-4 text-left transition hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", selected && "border-primary bg-accent")}>
      <Icon className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
      <span className="flex-1"><span className="block font-medium">{title}</span><span className="block text-sm text-muted-foreground">{text}</span></span>
      {selected && <Check className="h-4 w-4 shrink-0" aria-hidden />}
    </button>
  );
}

export default function NewApplication() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [method, setMethod] = useState<Method | null>(null);
  const [oidcType, setOidcType] = useState("web");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [f, setF] = useState({ name: "", launch_url: "", redirects: "", initiate: "", audiences: "", entity: "", acs: "", login_url: "", user_field: "username", pass_field: "password", access: "assigned" });
  const [created, setCreated] = useState<{ id: number; client_id: string; secret?: string } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"methods" | "catalog" | "templates">("methods");
  const [appTpls, setAppTpls] = useState<AppTemplate[]>([]);
  const [picked, setPicked] = useState<AppTemplate | null>(null);
  const [tname, setTname] = useState("");
  const [tvals, setTvals] = useState<Record<string, string>>({});
  const [tdone, setTdone] = useState<{ application_id: number; checklist: string[]; client_id?: string; client_secret?: string } | null>(null);
  const [cq, setCq] = useState("");
  const pickCatalog = (c: CatalogEntry) => { setMethod("bookmark"); setF((p) => ({ ...p, name: c.name, launch_url: c.url })); setStep(3); };
  const hits = CATALOG.filter((c) => (c.name + " " + c.category).toLowerCase().includes(cq.toLowerCase()));
  const set = (k: keyof typeof f, v: string) => setF((p) => ({ ...p, [k]: v }));

  useEffect(() => { http<{ items: Template[] }>("/admin/applications/templates").then((r) => setTemplates(r.items)).catch(() => {}); }, []);
  useEffect(() => { http<{ items: AppTemplate[] }>("/admin/application-templates").then((r) => setAppTpls(r.items)).catch(() => {}); }, []);

  async function createFromTemplate() {
    if (!picked) return;
    setMsg(null); setBusy(true);
    try {
      const r = await http<{ application_id: number; checklist: string[]; client_id?: string; client_secret?: string }>(`/admin/application-templates/${picked.key}/create`, { method: "POST", body: { name: tname, values: tvals } });
      setTdone(r);
    } catch (e) { setMsg(e instanceof Error ? e.message : "Failed"); } finally { setBusy(false); }
  }
  const tplId = method === "api" ? "service" : method === "oidc" ? oidcType : null;
  const tpl = templates.find((t) => t.id === tplId);
  const needsType = method === "oidc";
  const lastStep = 3;

  const valid =
    !!f.name.trim() &&
    (method !== "bookmark" || !!f.launch_url.trim()) &&
    (method !== "saml" || (!!f.entity.trim() && !!f.acs.trim())) &&
    (method !== "swa" || (!!f.login_url.trim() && !!f.user_field.trim() && !!f.pass_field.trim())) &&
    (!tpl?.needs_redirects || lines(f.redirects).length > 0);

  function next() { setStep((s) => (s === 1 && !needsType ? 3 : s + 1)); }
  function back() { setStep((s) => (s === 3 && !needsType ? 1 : s - 1)); }

  async function create() {
    setMsg(null); setBusy(true);
    const require_assignment = f.access !== "everyone";
    try {
      if (tpl) {
        const c = await http<{ application_id: number; client_id: string; client_secret?: string }>("/admin/applications/from-template", { method: "POST", body: {
          template: tpl.id, name: f.name, launch_url: f.launch_url || null, initiate_login_uri: f.initiate || null,
          redirect_uris: lines(f.redirects), allowed_audiences: lines(f.audiences), require_assignment } });
        setCreated({ id: c.application_id, client_id: c.client_id, secret: c.client_secret });
        return;
      }
      const mode = method === "api" ? "none" : (method as string);
      const a = await http<AppSummary>("/admin/applications", { method: "POST", body: { name: f.name, sign_on_mode: mode, launch_url: mode === "bookmark" ? f.launch_url : null, require_assignment } });
      try {
        if (method === "saml") await http(`/admin/applications/${a.id}/saml`, { method: "PUT", body: { sp_entity_id: f.entity.trim(), acs_url: f.acs.trim() } });
        if (method === "swa") await http(`/admin/applications/${a.id}/swa`, { method: "PUT", body: { login_url: f.login_url.trim(), username_field: f.user_field.trim(), password_field: f.pass_field.trim(), extra_fields: [], username_source: "user" } });
      } catch (e) {
        setMsg(`The application was created but its sign-on settings were rejected: ${e instanceof Error ? e.message : "error"}. Finish them on the next page.`);
        router.push(`/admin/applications/${a.id}`);
        return;
      }
      router.push(`/admin/applications/${a.id}`);
    } catch (e) { setMsg(e instanceof Error ? e.message : "Failed"); } finally { setBusy(false); }
  }

  if (tdone) {
    return (
      <div>
        <PageHeader title="Application created from template" />
        <Alert data-testid="template-created"><AlertDescription className="space-y-3">
          <p>The application is <strong>disabled</strong> until you finish the checklist below.</p>
          {tdone.client_id && <div>Client ID: <code>{tdone.client_id}</code></div>}
          {tdone.client_secret && <div>Client secret (shown only once — copy it now): <code className="break-all" data-testid="new-secret">{tdone.client_secret}</code></div>}
          <ol className="list-decimal space-y-1 pl-5" data-testid="template-checklist">{tdone.checklist.map((c) => <li key={c}>{c}</li>)}</ol>
          <Button size="sm" onClick={() => router.push(`/admin/applications/${tdone.application_id}`)}>Continue to the application</Button>
        </AlertDescription></Alert>
      </div>
    );
  }

  if (created) {
    return (
      <div>
        <PageHeader title="Application created" />
        <Alert data-testid="app-created"><AlertDescription className="space-y-2">
          <div>Client ID: <code>{created.client_id}</code></div>
          {created.secret ? <div>Client secret (shown only once — copy it now): <code className="break-all" data-testid="new-secret">{created.secret}</code></div> : <div>This client has no secret.</div>}
          <Button size="sm" onClick={() => router.push(`/admin/applications/${created.id}`)}>Continue to the application</Button>
        </AlertDescription></Alert>
      </div>
    );
  }

  const stepLabels = needsType ? ["Sign-in method", "Application type", "Settings"] : ["Sign-in method", "Settings"];
  const shown = needsType ? step : step === 1 ? 1 : 2;

  return (
    <div className="max-w-3xl" data-testid="app-wizard">
      <Link href="/admin/applications" className="mb-2 inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline"><ArrowLeft className="h-4 w-4" /> Back to Applications</Link>
      <PageHeader title="Create a new app integration" />
      <ol className="mb-6 flex flex-wrap gap-4 text-sm" aria-label="Progress">
        {stepLabels.map((l, i) => <li key={l} aria-current={shown === i + 1 ? "step" : undefined} className={cn(shown === i + 1 ? "font-semibold" : "text-muted-foreground")}>{i + 1}. {l}</li>)}
      </ol>
      {msg && <Alert variant="destructive" className="mb-4" role="status"><AlertDescription>{msg}</AlertDescription></Alert>}

      {step === 1 && (
        <div role="tablist" aria-label="Start from" className="mb-4 flex gap-1 border-b">
          {([["methods", "Create new app integration"], ["templates", "Start from a template"], ["catalog", "Browse App Catalog"]] as const).map(([k, l]) => (
            <button key={k} role="tab" type="button" aria-selected={view === k} data-testid={`wizard-view-${k}`} onClick={() => setView(k)}
              className={cn("-mb-px border-b-2 px-4 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", view === k ? "border-primary font-medium" : "border-transparent text-muted-foreground hover:text-foreground")}>{l}</button>
          ))}
        </div>
      )}

      {step === 1 && view === "catalog" && (
        <div data-testid="catalog">
          <Input aria-label="Search the catalog" placeholder="Search apps…" className="mb-3 max-w-xs" value={cq} onChange={(e) => setCq(e.target.value)} />
          <p className="mb-3 text-sm text-muted-foreground">Starter entries add a bookmark to the vendor&apos;s sign-in page. Single sign-on needs tenant-specific values, so choose SAML or OIDC under &quot;Create new&quot; for that.</p>
          <ul className="grid gap-3 sm:grid-cols-2">
            {hits.map((c) => (
              <li key={c.id}><button type="button" data-testid={`catalog-${c.id}`} onClick={() => pickCatalog(c)} className="flex w-full items-center gap-3 rounded-lg border p-3 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-secondary font-semibold">{c.name[0]}</span>
                <span><span className="block font-medium">{c.name}</span><span className="block text-xs text-muted-foreground">{c.category}</span></span>
              </button></li>
            ))}
            {hits.length === 0 && <li className="text-sm text-muted-foreground">No matches.</li>}
          </ul>
        </div>
      )}

      {step === 1 && view === "templates" && (
        <div data-testid="templates">
          {!picked ? (
            <>
              <p className="mb-3 text-sm text-muted-foreground">Templates set the sign-on and provisioning defaults for you. The application stays disabled until you finish a short checklist.</p>
              <ul className="grid gap-3 sm:grid-cols-2">
                {appTpls.map((t) => (
                  <li key={t.key}><button type="button" data-testid={`tpl-${t.key}`} onClick={() => { setPicked(t); setTname(t.name); setTvals({}); setMsg(null); }}
                    className="flex w-full items-start gap-3 rounded-lg border p-3 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-secondary font-semibold">{t.name[0]}</span>
                    <span><span className="block font-medium">{t.name}</span><span className="block text-xs text-muted-foreground">{t.description}</span></span>
                  </button></li>
                ))}
              </ul>
            </>
          ) : (
            <Card><CardContent className="grid gap-4 pt-6" data-testid="template-form">
              <div><p className="font-medium">{picked.name}</p><p className="text-sm text-muted-foreground">{picked.description}</p></div>
              <div className="space-y-1"><Label htmlFor="t-name">App integration name</Label><Input id="t-name" maxLength={100} value={tname} onChange={(e) => setTname(e.target.value)} /></div>
              {picked.fields.map((fd) => (
                <div key={fd.key} className="space-y-1"><Label htmlFor={`t-${fd.key}`}>{fd.label}</Label>
                  <Input id={`t-${fd.key}`} type={fd.secret ? "password" : "text"} autoComplete="off" placeholder={fd.placeholder} value={tvals[fd.key] ?? ""} onChange={(e) => setTvals((p) => ({ ...p, [fd.key]: e.target.value }))} />
                  {fd.help && <p className="text-xs text-muted-foreground">{fd.help}</p>}</div>
              ))}
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => { setPicked(null); setMsg(null); }}>Back to templates</Button>
                <Button disabled={busy || !tname.trim() || picked.fields.some((fd) => fd.key !== "launch_url" && !(tvals[fd.key] ?? "").trim())} onClick={createFromTemplate} data-testid="template-create">Create</Button>
              </div>
            </CardContent></Card>
          )}
        </div>
      )}

      {step === 1 && view === "methods" && (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">Choose how people will sign in to the application.</p>
          {METHODS.map((m) => <Pick key={m.id} testid={`method-${m.id}`} selected={method === m.id} onClick={() => setMethod(m.id)} icon={m.icon} title={m.title} text={m.text} />)}
        </div>
      )}

      {step === 2 && needsType && (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">What kind of OIDC application is it?</p>
          {OIDC_TYPES.map(({ id, icon }) => {
            const t = templates.find((x) => x.id === id);
            return t ? <Pick key={id} testid={`type-${id}`} selected={oidcType === id} onClick={() => setOidcType(id)} icon={icon} title={t.label} text={t.description} /> : null;
          })}
        </div>
      )}

      {step === lastStep || (step === 2 && !needsType) ? (
        <Card><CardContent className="grid gap-4 pt-6" data-testid="app-create">
          <div className="space-y-1"><Label htmlFor="a-name">App integration name</Label><Input id="a-name" maxLength={100} value={f.name} onChange={(e) => set("name", e.target.value)} /></div>

          {method === "bookmark" && <div className="space-y-1"><Label htmlFor="a-url">URL</Label><Input id="a-url" placeholder="https://app.example.com/" value={f.launch_url} onChange={(e) => set("launch_url", e.target.value)} /></div>}

          {tpl?.needs_redirects && <div className="space-y-1"><Label htmlFor="a-redirects">Sign-in redirect URIs (one per line)</Label>
            <textarea id="a-redirects" rows={3} className={fieldClass} placeholder="https://app.example.com/callback" value={f.redirects} onChange={(e) => set("redirects", e.target.value)} /></div>}
          {method === "oidc" && <div className="space-y-1"><Label htmlFor="a-init">Initiate login URI (optional)</Label><Input id="a-init" placeholder="https://app.example.com/login" value={f.initiate} onChange={(e) => set("initiate", e.target.value)} />
            <p className="text-xs text-muted-foreground">Lets users start from their My apps tile (IdP-initiated sign-in).</p></div>}
          {method === "api" && <div className="space-y-1"><Label htmlFor="a-aud">Audiences (one per line)</Label><textarea id="a-aud" rows={2} className={fieldClass} placeholder="https://api.example.com" value={f.audiences} onChange={(e) => set("audiences", e.target.value)} /></div>}

          {method === "saml" && (<>
            <div className="space-y-1"><Label htmlFor="a-acs">Single sign-on URL (ACS)</Label><Input id="a-acs" placeholder="https://app.example.com/saml/acs" value={f.acs} onChange={(e) => set("acs", e.target.value)} /></div>
            <div className="space-y-1"><Label htmlFor="a-ent">Audience URI (SP Entity ID)</Label><Input id="a-ent" placeholder="https://app.example.com/saml/metadata" value={f.entity} onChange={(e) => set("entity", e.target.value)} />
              <p className="text-xs text-muted-foreground">Attribute statements, NameID format and signing are set on the next page.</p></div>
          </>)}
          {method === "swa" && (<>
            <div className="space-y-1"><Label htmlFor="a-login">Login page URL</Label><Input id="a-login" placeholder="https://legacy.example.com/login" value={f.login_url} onChange={(e) => set("login_url", e.target.value)} /></div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1"><Label htmlFor="a-uf">Username field name</Label><Input id="a-uf" value={f.user_field} onChange={(e) => set("user_field", e.target.value)} /></div>
              <div className="space-y-1"><Label htmlFor="a-pf">Password field name</Label><Input id="a-pf" value={f.pass_field} onChange={(e) => set("pass_field", e.target.value)} /></div>
            </div>
          </>)}

          {method !== "api" && method !== "none" && (
            <fieldset className="space-y-2"><legend className="mb-1 text-sm font-medium">Controlled access</legend>
              {[["assigned", "Limit access to assigned users and groups"], ["everyone", "Allow everyone in your organization to access"]].map(([v, l]) => (
                <label key={v} className="flex items-center gap-2 text-sm"><input type="radio" name="access" checked={f.access === v} onChange={() => set("access", v)} /> {l}</label>
              ))}
            </fieldset>
          )}
        </CardContent></Card>
      ) : null}

      <div className="mt-6 flex gap-2">
        {step > 1 && <Button variant="outline" onClick={back}>Previous</Button>}
        {step === 1 && (view === "catalog" || view === "templates") ? null : step === 1 || (step === 2 && needsType)
          ? <Button disabled={!method} onClick={next} data-testid="wizard-next">Next</Button>
          : <Button disabled={!valid || busy} onClick={create} data-testid="wizard-create">Done</Button>}
        <Button variant="ghost" onClick={() => router.push("/admin/applications")}>Cancel</Button>
      </div>
    </div>
  );
}
