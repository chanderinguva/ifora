"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Check, Copy, Download, ExternalLink } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageHeader, td, th } from "@/components/bits";
import { API_URL } from "@/lib/api";
import { download, operations, postmanCollection, snippets, tagsOf, type Operation, type Spec } from "@/lib/openapi";

const TABS = [["start", "Getting started"], ["reference", "API reference"], ["postman", "Postman & OpenAPI"], ["sdk", "SDKs"], ["mcp", "MCP"]] as const;
type Tab = (typeof TABS)[number][0];
const SPEC_URL = `${API_URL}/openapi.json`;

const METHOD_TONE: Record<string, string> = {
  GET: "bg-secondary text-foreground",
  POST: "bg-selected text-selected-foreground",
  PUT: "bg-secondary text-warn",
  PATCH: "bg-secondary text-warn",
  DELETE: "bg-secondary text-bad",
};
const Method = ({ m }: { m: string }) => <span className={`inline-block w-16 shrink-0 rounded-md px-2 py-0.5 text-center font-mono text-xs font-medium ${METHOD_TONE[m] ?? ""}`}>{m}</span>;

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button type="button" size="sm" variant="outline" onClick={async () => { try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* clipboard blocked */ } }}>
      {done ? <Check className="mr-1 h-3.5 w-3.5" /> : <Copy className="mr-1 h-3.5 w-3.5" />}{done ? "Copied" : label}
    </Button>
  );
}

function Code({ text, label }: { text: string; label?: string }) {
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-md border bg-muted/40 p-3 pr-20 font-mono text-xs leading-relaxed" aria-label={label}>{text}</pre>
      <div className="absolute right-2 top-2"><CopyButton text={text} /></div>
    </div>
  );
}

function OperationRow({ op, open, onToggle }: { op: Operation; open: boolean; onToggle: () => void }) {
  const [lang, setLang] = useState<"curl" | "python" | "javascript">("curl");
  const code = useMemo(() => (open ? snippets(op, API_URL) : null), [open, op]);
  return (
    <div className="border-b last:border-b-0" data-testid="api-op">
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-accent/40">
        <Method m={op.method} />
        <code className="min-w-0 flex-1 truncate text-sm">{op.path}</code>
        <span className="hidden max-w-sm truncate text-sm text-muted-foreground md:block">{op.summary}</span>
      </button>
      {open && code && (
        <div className="space-y-4 px-3 pb-4 pt-1">
          {op.description && <p className="whitespace-pre-line text-sm text-muted-foreground">{op.description}</p>}
          <p className="text-xs text-muted-foreground">
            {op.tokenOk ? "Accepts an API token (Authorization: Bearer idf_api_…) or a browser session." : "Needs a browser session (cookie plus X-CSRF-Token on changes); API tokens are accepted on /api/v1/admin/** only."}
          </p>
          {op.params.length > 0 && (
            <div><h4 className="mb-1 text-sm font-semibold">Parameters</h4>
              <table className="w-full text-left text-sm"><thead><tr><th className={th}>Name</th><th className={th}>In</th><th className={th}>Type</th><th className={th}>Description</th></tr></thead>
                <tbody>{op.params.map((p) => <tr key={p.in + p.name}><td className={td}><code>{p.name}</code>{p.required && <span className="ml-1 text-xs text-bad">required</span>}</td><td className={td}>{p.in}</td><td className={td}>{p.type}</td><td className={td}>{p.description}</td></tr>)}</tbody></table></div>
          )}
          {op.bodyFields && (
            <div><h4 className="mb-1 text-sm font-semibold">Request body <span className="font-normal text-muted-foreground">{op.bodyContentType}</span></h4>
              {op.bodyFields.length > 0 && <table className="mb-2 w-full text-left text-sm"><thead><tr><th className={th}>Field</th><th className={th}>Type</th><th className={th}>Description</th></tr></thead>
                <tbody>{op.bodyFields.map((f) => <tr key={f.name}><td className={td}><code>{f.name}</code>{f.required && <span className="ml-1 text-xs text-bad">required</span>}</td><td className={td}>{f.type}</td><td className={td}>{f.description}</td></tr>)}</tbody></table>}
            </div>
          )}
          <div><h4 className="mb-1 text-sm font-semibold">Responses</h4>
            <ul className="text-sm">{op.responses.map((r) => <li key={r.code}><code>{r.code}</code> <span className="text-muted-foreground">{r.description}</span></li>)}</ul></div>
          <div>
            <div className="mb-2 flex gap-1" role="tablist" aria-label="Code sample language">
              {(["curl", "python", "javascript"] as const).map((l) => (
                <Button key={l} type="button" size="sm" role="tab" aria-selected={lang === l} variant={lang === l ? "default" : "outline"} onClick={() => setLang(l)}>{l === "javascript" ? "JavaScript" : l === "python" ? "Python" : "cURL"}</Button>
              ))}
            </div>
            <Code text={code[lang]} label={`${lang} example`} />
          </div>
        </div>
      )}
    </div>
  );
}

function Reference({ ops }: { ops: Operation[] }) {
  const tags = useMemo(() => tagsOf(ops), [ops]);
  const [tag, setTag] = useState<string>("all");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return ops.filter((o) => (tag === "all" || o.tag === tag) && (!needle || `${o.method} ${o.path} ${o.summary} ${o.tag}`.toLowerCase().includes(needle)));
  }, [ops, tag, q]);
  return (
    <div className="grid gap-4 md:grid-cols-[14rem_1fr]">
      <nav aria-label="API sections" className="md:sticky md:top-4 md:max-h-[80vh] md:self-start md:overflow-y-auto">
        <ul className="space-y-0.5 text-sm">
          {[{ tag: "all", count: ops.length }, ...tags].map((t) => (
            <li key={t.tag}><button type="button" onClick={() => setTag(t.tag)} aria-current={tag === t.tag} className={`flex w-full justify-between rounded px-2 py-1 text-left hover:bg-accent ${tag === t.tag ? "bg-accent font-medium" : ""}`}>
              <span>{t.tag === "all" ? "All endpoints" : t.tag}</span><span className="text-muted-foreground">{t.count}</span></button></li>
          ))}
        </ul>
      </nav>
      <div className="min-w-0">
        <Input aria-label="Search endpoints" placeholder="Search by path, method or summary" value={q} onChange={(e) => setQ(e.target.value)} className="mb-3" />
        <p className="mb-2 text-xs text-muted-foreground" role="status">{shown.length} of {ops.length} endpoints</p>
        <Card><CardContent className="p-0">
          {shown.length === 0 ? <p className="p-4 text-sm text-muted-foreground">No endpoints match.</p>
            : shown.map((o) => <OperationRow key={o.key} op={o} open={open === o.key} onToggle={() => setOpen(open === o.key ? null : o.key)} />)}
        </CardContent></Card>
      </div>
    </div>
  );
}

const RESOURCE_EXAMPLE = JSON.stringify({
  schemas: ["urn:ifora:params:scim:schemas:2.0:Group"],
  id: 12, name: "Engineering", description: "Product engineering",
  meta: { resourceType: "Group", created: "2026-01-05T09:30:00+00:00", lastModified: "2026-02-01T14:02:11+00:00", location: `${API_URL}/api/v1/admin/groups/12` },
}, null, 2);
const LIST_EXAMPLE = JSON.stringify({
  schemas: ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
  totalResults: 42, startIndex: 1, itemsPerPage: 25,
  Resources: [{ schemas: ["urn:ifora:params:scim:schemas:2.0:Group"], id: 12, name: "Engineering", meta: { resourceType: "Group", location: `${API_URL}/api/v1/admin/groups/12` } }, "…"],
}, null, 2);
const ERROR_EXAMPLE = JSON.stringify({
  schemas: ["urn:ietf:params:scim:api:messages:2.0:Error"],
  status: "422", scimType: "invalidValue", detail: "name: Field required",
  errors: [{ type: "missing", loc: ["body", "name"], msg: "Field required" }],
}, null, 2);

function GettingStarted() {
  return (
    <div className="space-y-4">
      <Card><CardHeader><CardTitle>Base URL</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">
        <Code text={`${API_URL}/api/v1`} label="Base URL" />
        <p className="text-muted-foreground">JSON over HTTPS. Requests and responses follow SCIM 2.0 conventions (RFC 7643 and 7644): resources carry <code>schemas</code> and <code>meta</code>, lists are a ListResponse, and errors are a SCIM Error. See Responses below.</p>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Responses</CardTitle></CardHeader><CardContent className="space-y-3 text-sm">
        <p><b>A resource</b> keeps its own fields and adds <code>schemas</code> and <code>meta</code> (<code>resourceType</code>, <code>created</code>, <code>lastModified</code>, <code>location</code>). The <code>id</code> is unchanged.</p>
        <Code label="Resource" text={RESOURCE_EXAMPLE} />
        <p><b>A list</b> is a ListResponse. Page with <code>startIndex</code> (1-based) and <code>count</code> (default 25, max 100, 0 returns only the total); sort with <code>sortBy</code> and <code>sortOrder</code> (<code>ascending</code> or <code>descending</code>); narrow with a SCIM <code>filter</code> on a response field, for example <code>/admin/users?filter=email co &quot;@ifora.app&quot; and status eq &quot;active&quot;</code>.</p>
        <Code label="List" text={LIST_EXAMPLE} />
        <p><b>An error</b> is a SCIM Error with the HTTP status repeated as a string. <code>detail</code> is always readable text. Validation errors (422) add <code>scimType</code> and an <code>errors</code> array with one entry per field.</p>
        <Code label="Error" text={ERROR_EXAMPLE} />
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Authentication</CardTitle></CardHeader><CardContent className="space-y-3 text-sm">
        <p><b>API token</b> for scripts and integrations against <code>/api/v1/admin/**</code>. Create one under <Link className="underline" href="/admin/administrators">Administrators &amp; API tokens</Link> (it can be read-only, expire, and be limited to network ranges), then send it as a bearer token. A token carries its owner&apos;s administrator roles, so it can never do more than they can.</p>
        <Code text={`export IFORA_API_TOKEN=idf_api_…\ncurl -H "Authorization: Bearer $IFORA_API_TOKEN" ${API_URL}/api/v1/admin/stats`} />
        <p><b>Browser session</b> for everything else (your own profile, MFA, sign-in): <code>POST /api/v1/login</code> sets an HttpOnly cookie and returns a <code>csrf_token</code>; send that value as <code>X-CSRF-Token</code> on every POST, PUT, PATCH and DELETE.</p>
        <Code text={`curl -c cookies.txt -X POST ${API_URL}/api/v1/login -H "Content-Type: application/json" \\\n  -d '{"email":"you@example.com","password":"…"}'`} />
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Standards endpoints</CardTitle></CardHeader><CardContent className="space-y-1 text-sm">
        <p>OpenID Connect discovery: <a className="underline" href={`${API_URL}/.well-known/openid-configuration`} target="_blank" rel="noreferrer">{API_URL}/.well-known/openid-configuration</a></p>
        <p>SAML metadata: <a className="underline" href={`${API_URL}/saml/metadata`} target="_blank" rel="noreferrer">{API_URL}/saml/metadata</a></p>
        <p>SCIM 2.0 base URL (inbound provisioning): <code>{API_URL}/scim/v2</code> with a token from <Link className="underline" href="/admin/provisioning">Inbound SCIM</Link></p>
      </CardContent></Card>
    </div>
  );
}

function Downloads({ spec, ops }: { spec: Spec; ops: Operation[] }) {
  const collection = () => download("ifora-api.postman_collection.json", JSON.stringify(postmanCollection(spec, ops, API_URL), null, 2));
  return (
    <div className="space-y-4">
      <Card><CardHeader><CardTitle>Postman collection</CardTitle></CardHeader><CardContent className="space-y-3 text-sm">
        <p>Every endpoint, grouped by section, built from the live API so it is never out of date. Import it in Postman (File → Import), then set the <code>apiToken</code> collection variable. Session-only requests use Postman&apos;s cookie jar after you send <code>POST /api/v1/login</code>; copy the returned <code>csrf_token</code> into <code>csrfToken</code>.</p>
        <Button onClick={collection} data-testid="download-postman"><Download className="mr-1 h-4 w-4" /> Download collection ({ops.length} requests)</Button>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>OpenAPI document</CardTitle></CardHeader><CardContent className="space-y-3 text-sm">
        <Code text={SPEC_URL} label="OpenAPI URL" />
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => download("ifora-openapi.json", JSON.stringify(spec, null, 2))}><Download className="mr-1 h-4 w-4" /> Download openapi.json</Button>
          <a href={`${API_URL}/docs`} target="_blank" rel="noreferrer"><Button variant="outline"><ExternalLink className="mr-1 h-4 w-4" /> Swagger UI</Button></a>
          <a href={`${API_URL}/redoc`} target="_blank" rel="noreferrer"><Button variant="outline"><ExternalLink className="mr-1 h-4 w-4" /> ReDoc</Button></a>
        </div>
      </CardContent></Card>
    </div>
  );
}

const TS_CLIENT = `// Minimal typed-ish client for Ifora (Node 18+ or any modern browser).
const BASE = "${API_URL}/api/v1";
const TOKEN = process.env.IFORA_API_TOKEN!;

export async function ifora<T = unknown>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(BASE + path, {
    method: init.method ?? "GET",
    headers: { Authorization: \`Bearer \${TOKEN}\`, ...(init.body ? { "Content-Type": "application/json" } : {}) },
    body: init.body ? JSON.stringify(init.body) : undefined,
  });
  if (!res.ok) throw new Error(\`\${res.status}: \${(await res.json().catch(() => ({}))).detail ?? res.statusText}\`);
  return res.json() as Promise<T>;
}

// const users = await ifora("/admin/users?count=10");`;

const PY_INSTALL = `# from a checkout of the repository
pip install ./sdk/python`;
const PY_SDK = `import os
from ifora import Client, IForaError

with Client("${API_URL}", token=os.environ["IFORA_API_TOKEN"]) as ifora:
    # lists are SCIM ListResponses; paginate() walks every page
    for user in ifora.paginate(ifora.users.list, filter='status eq "active"'):
        print(user["id"], user["email"])

    group = ifora.groups.create({"name": "Engineering"})
    print(group["meta"]["location"])

    try:
        ifora.groups.get(999999)
    except IForaError as e:            # every failure is a SCIM Error
        print(e.status, e.detail)      # 404 Group not found

# Endpoints outside /api/v1/admin (your profile, MFA, sign-in) need a session:
#   ifora.login("you@example.com", "…")`;

function Sdks() {
  const gen = (g: string, out: string) => `npx @openapitools/openapi-generator-cli generate -i ${SPEC_URL} -g ${g} -o ${out}`;
  return (
    <div className="space-y-4">
      <Alert><AlertDescription>The Python SDK covers every endpoint and ships in the repository under sdk/python (it is not on PyPI). For other languages, generate a client from the live OpenAPI document, or start from the small TypeScript client below.</AlertDescription></Alert>
      <Card><CardHeader><CardTitle>Generate a client</CardTitle></CardHeader><CardContent className="space-y-3 text-sm">
        <p>Uses <a className="underline" href="https://openapi-generator.tech" target="_blank" rel="noreferrer">OpenAPI Generator</a>; pick any of its generators.</p>
        <Code text={[gen("typescript-fetch", "./ifora-ts"), gen("python", "./ifora-py"), gen("java", "./ifora-java"), gen("go", "./ifora-go")].join("\n")} label="Generator commands" />
      </CardContent></Card>
      <Card><CardHeader><CardTitle>TypeScript</CardTitle></CardHeader><CardContent><Code text={TS_CLIENT} label="TypeScript client" /></CardContent></Card>
      <Card><CardHeader><CardTitle>Python SDK</CardTitle></CardHeader><CardContent className="space-y-3 text-sm">
        <p>One method per endpoint, grouped by section (<code>ifora.users</code>, <code>ifora.groups</code>, <code>ifora.applications</code>…), with SCIM errors raised as <code>IForaError</code>. The package is generated from this API&apos;s OpenAPI document, so it never lags behind.</p>
        <Code text={PY_INSTALL} label="Install the Python SDK" />
        <Code text={PY_SDK} label="Python SDK example" />
      </CardContent></Card>
    </div>
  );
}

function Mcp() {
  const cmd = `claude mcp add ifora \\\n  --env API_BASE_URL=${API_URL} \\\n  --env OPENAPI_SPEC_PATH=${SPEC_URL} \\\n  --env API_HEADERS="Authorization:Bearer $IFORA_API_TOKEN" \\\n  -- npx -y @ivotoby/openapi-mcp-server`;
  const cfg = JSON.stringify({ mcpServers: { ifora: { command: "npx", args: ["-y", "@ivotoby/openapi-mcp-server"], env: { API_BASE_URL: API_URL, OPENAPI_SPEC_PATH: SPEC_URL, API_HEADERS: "Authorization:Bearer ${IFORA_API_TOKEN}" } } } }, null, 2);
  return (
    <div className="space-y-4">
      <Alert><AlertDescription>Ifora does not ship its own MCP server. The API&apos;s OpenAPI document can be exposed as MCP tools by a generic OpenAPI-to-MCP bridge, so an AI assistant can call the admin API. The bridge below is a third-party package (<code>@ivotoby/openapi-mcp-server</code>); check its README for current options.</AlertDescription></Alert>
      <Alert variant="destructive"><AlertDescription>Use a <b>read-only</b> API token with a short expiry, created for this purpose under <Link className="underline" href="/admin/administrators">Administrators &amp; API tokens</Link>. Anything the token can do, the assistant can do.</AlertDescription></Alert>
      <Card><CardHeader><CardTitle>Claude Code</CardTitle></CardHeader><CardContent><Code text={cmd} label="Claude Code command" /></CardContent></Card>
      <Card><CardHeader><CardTitle>Other MCP clients (JSON config)</CardTitle></CardHeader><CardContent><Code text={cfg} label="MCP JSON config" /></CardContent></Card>
    </div>
  );
}

export default function Developers() {
  const [tab, setTab] = useState<Tab>("start");
  const [spec, setSpec] = useState<Spec | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const fromHash = window.location.hash.slice(1) as Tab;
    if (TABS.some(([k]) => k === fromHash)) setTab(fromHash);
    fetch(SPEC_URL).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))).then(setSpec).catch((e) => setError(`Could not load the API description (${e.message}).`));
  }, []);
  const ops = useMemo(() => (spec ? operations(spec) : []), [spec]);
  const pick = (t: Tab) => { setTab(t); window.history.replaceState(null, "", `#${t}`); };

  return (
    <div>
      <PageHeader title="Developers">{spec && <span className="text-sm text-muted-foreground">{spec.info.title} {spec.info.version} · {ops.length} endpoints</span>}</PageHeader>
      <div className="mb-4 flex flex-wrap gap-1 border-b pb-2" role="tablist" aria-label="Developer sections">
        {TABS.map(([k, label]) => <Button key={k} role="tab" aria-selected={tab === k} variant={tab === k ? "default" : "ghost"} size="sm" onClick={() => pick(k)}>{label}</Button>)}
      </div>
      {error && <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert>}
      {tab === "start" && <GettingStarted />}
      {tab === "sdk" && <Sdks />}
      {tab === "mcp" && <Mcp />}
      {tab === "reference" && (spec ? <Reference ops={ops} /> : !error && <p className="text-sm text-muted-foreground">Loading the API reference…</p>)}
      {tab === "postman" && (spec ? <Downloads spec={spec} ops={ops} /> : !error && <p className="text-sm text-muted-foreground">Loading…</p>)}
    </div>
  );
}
