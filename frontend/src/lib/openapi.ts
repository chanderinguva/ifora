/** Reads the API's own OpenAPI document and derives what the developer page shows: operations, examples, code snippets, a Postman collection. */

/* eslint-disable @typescript-eslint/no-explicit-any */

export type Spec = { info: { title: string; version: string; description?: string }; paths: Record<string, Record<string, any>>; components?: { schemas?: Record<string, any> } };
export type Field = { name: string; type: string; required: boolean; description: string };
export type Operation = {
  key: string;
  method: string;
  path: string;
  summary: string;
  description: string;
  tag: string;
  params: (Field & { in: string })[];
  bodyFields: Field[] | null;
  bodyExample: unknown;
  bodyContentType: string | null;
  responses: { code: string; description: string }[];
  /** /admin/** accepts an API token; everything else needs a browser session. */
  tokenOk: boolean;
};

const METHODS = ["get", "post", "put", "patch", "delete"];

function deref(spec: Spec, s: any, depth = 0): any {
  if (s && typeof s === "object" && s.$ref && depth < 8) return deref(spec, spec.components?.schemas?.[String(s.$ref).split("/").pop() as string], depth + 1);
  return s ?? {};
}

function typeOf(spec: Spec, s: any): string {
  if (s?.$ref) return String(s.$ref).split("/").pop() as string;
  if (!s) return "any";
  if (s.enum) return s.enum.map(String).join(" | ");
  const alt = s.anyOf ?? s.oneOf;
  if (alt) return Array.from(new Set(alt.map((x: any) => typeOf(spec, x)))).join(" | ");
  if (s.allOf) return s.allOf.map((x: any) => typeOf(spec, x)).join(" & ");
  if (s.type === "array") return `${typeOf(spec, s.items ?? {})}[]`;
  if (s.type) return s.format ? `${s.type} (${s.format})` : s.type;
  return "object";
}

function fieldsOf(spec: Spec, schema: any): Field[] {
  const s = deref(spec, schema);
  const merged: Record<string, any> = { ...(s.properties ?? {}) };
  const required: string[] = [...(s.required ?? [])];
  for (const part of s.allOf ?? []) {
    const p = deref(spec, part);
    Object.assign(merged, p.properties ?? {});
    required.push(...(p.required ?? []));
  }
  return Object.entries(merged).map(([name, v]: [string, any]) => ({ name, type: typeOf(spec, v), required: required.includes(name), description: deref(spec, v).description ?? "" }));
}

export function example(spec: Spec, schema: any, depth = 0): unknown {
  const s = deref(spec, schema);
  if (s.example !== undefined) return s.example;
  if (s.default !== undefined && s.default !== null) return s.default;
  if (s.enum?.length) return s.enum[0];
  const alt = s.anyOf ?? s.oneOf;
  if (alt) return example(spec, alt.find((x: any) => x?.type !== "null") ?? alt[0], depth + 1);
  if (s.allOf || s.properties) {
    if (depth > 4) return {};
    const out: Record<string, unknown> = {};
    for (const f of fieldsOf(spec, s)) {
      const src = s.properties?.[f.name] ?? (s.allOf ?? []).map((p: any) => deref(spec, p).properties?.[f.name]).find(Boolean);
      if (f.required || depth === 0) out[f.name] = example(spec, src, depth + 1);
    }
    return out;
  }
  switch (s.type) {
    case "string":
      return s.format === "email" ? "user@example.com" : s.format === "date-time" ? "2026-01-01T00:00:00Z" : s.format === "uri" ? "https://example.com" : "string";
    case "integer":
    case "number":
      return 0;
    case "boolean":
      return false;
    case "array":
      return depth > 4 ? [] : [example(spec, s.items ?? {}, depth + 1)];
    default:
      return {};
  }
}

export function operations(spec: Spec): Operation[] {
  const out: Operation[] = [];
  for (const [path, item] of Object.entries(spec.paths)) {
    for (const method of METHODS) {
      const op = item[method];
      if (!op) continue;
      const params = [...(item.parameters ?? []), ...(op.parameters ?? [])].map((p: any) => ({
        name: p.name, in: p.in, type: typeOf(spec, p.schema), required: !!p.required, description: p.description ?? "",
      }));
      const content = op.requestBody?.content ?? {};
      const ct = content["application/json"] ? "application/json" : Object.keys(content)[0] ?? null;
      const bodySchema = ct ? content[ct]?.schema : null;
      out.push({
        key: `${method} ${path}`,
        method: method.toUpperCase(),
        path,
        summary: op.summary ?? "",
        description: op.description ?? "",
        tag: op.tags?.[0] ?? "other",
        params,
        bodyFields: bodySchema ? fieldsOf(spec, bodySchema) : null,
        bodyExample: bodySchema && ct === "application/json" ? example(spec, bodySchema) : null,
        bodyContentType: ct,
        responses: Object.entries(op.responses ?? {}).map(([code, r]: [string, any]) => ({ code, description: r?.description ?? "" })),
        tokenOk: path.startsWith("/api/v1/admin/"),
      });
    }
  }
  return out;
}

export function tagsOf(ops: Operation[]): { tag: string; count: number }[] {
  const m = new Map<string, number>();
  for (const o of ops) m.set(o.tag, (m.get(o.tag) ?? 0) + 1);
  return Array.from(m, ([tag, count]) => ({ tag, count })).sort((a, b) => a.tag.localeCompare(b.tag));
}

const json = (v: unknown) => JSON.stringify(v, null, 2);
const queryOf = (op: Operation) => {
  const q = op.params.filter((p) => p.in === "query" && p.required).map((p) => `${p.name}=value`);
  return q.length ? `?${q.join("&")}` : "";
};

export function snippets(op: Operation, base: string): { curl: string; python: string; javascript: string } {
  const url = `${base}${op.path}${queryOf(op)}`;
  const hasBody = op.bodyExample !== null && op.bodyExample !== undefined;
  const unsafe = op.method !== "GET";
  const bodyJson = hasBody ? json(op.bodyExample) : "";

  const curlHeaders = [op.tokenOk ? `-H "Authorization: Bearer $IFORA_API_TOKEN"` : `-b cookies.txt`];
  if (!op.tokenOk && unsafe) curlHeaders.push(`-H "X-CSRF-Token: $CSRF_TOKEN"`);
  if (hasBody) curlHeaders.push(`-H "Content-Type: application/json"`);
  const curl = [`curl -X ${op.method} "${url}"`, ...curlHeaders.map((h) => `  ${h}`), ...(hasBody ? [`  -d '${bodyJson.replace(/'/g, "'\\''")}'`] : [])].join(" \\\n");

  const pyHeaders = op.tokenOk ? `{"Authorization": f"Bearer {os.environ['IFORA_API_TOKEN']}"}` : `{"X-CSRF-Token": csrf_token}` ;
  const pyBody = hasBody ? bodyJson.replace(/\btrue\b/g, "True").replace(/\bfalse\b/g, "False").replace(/\bnull\b/g, "None") : "";
  const python = [
    "import os",
    "import requests",
    "",
    ...(op.tokenOk ? [] : ["# Sign in with POST /api/v1/login first; reuse that session's cookies and the csrf_token it returns.", "session = requests.Session()", ""]),
    `r = ${op.tokenOk ? "requests" : "session"}.${op.method.toLowerCase()}(`,
    `    "${url}",`,
    ...(op.tokenOk || unsafe ? [`    headers=${pyHeaders},`] : []),
    ...(hasBody ? [`    json=${pyBody.split("\n").join("\n    ")},`] : []),
    ")",
    "r.raise_for_status()",
    "print(r.json())",
  ].join("\n");

  const jsHeaders = [op.tokenOk ? "Authorization: `Bearer ${process.env.IFORA_API_TOKEN}`" : null, !op.tokenOk && unsafe ? `"X-CSRF-Token": csrfToken` : null, hasBody ? `"Content-Type": "application/json"` : null].filter(Boolean);
  const javascript = [
    ...(op.tokenOk ? [] : ["// In a browser: sign in with POST /api/v1/login (credentials: \"include\") and keep the csrf_token it returns."]),
    `const res = await fetch("${url}", {`,
    `  method: "${op.method}",`,
    ...(op.tokenOk ? [] : [`  credentials: "include",`]),
    ...(jsHeaders.length ? [`  headers: { ${jsHeaders.join(", ")} },`] : []),
    ...(hasBody ? [`  body: JSON.stringify(${bodyJson.split("\n").join("\n  ")}),`] : []),
    "});",
    "if (!res.ok) throw new Error(await res.text());",
    "console.log(await res.json());",
  ].join("\n");

  return { curl, python, javascript };
}

/** Postman Collection v2.1, built from the live spec: one folder per tag, {{baseUrl}} and {{apiToken}} variables. */
export function postmanCollection(spec: Spec, ops: Operation[], base: string): unknown {
  const folders = new Map<string, unknown[]>();
  for (const op of ops) {
    const segments = op.path.split("/").filter(Boolean).map((s) => s.replace(/^\{(.+)\}$/, ":$1"));
    const headers: { key: string; value: string }[] = [];
    if (!op.tokenOk && op.method !== "GET") headers.push({ key: "X-CSRF-Token", value: "{{csrfToken}}" });
    if (op.bodyContentType === "application/json") headers.push({ key: "Content-Type", value: "application/json" });
    const req: Record<string, unknown> = {
      method: op.method,
      header: headers,
      url: {
        raw: `{{baseUrl}}/${segments.join("/")}`,
        host: ["{{baseUrl}}"],
        path: segments,
        variable: op.params.filter((p) => p.in === "path").map((p) => ({ key: p.name, value: "", description: p.description })),
        query: op.params.filter((p) => p.in === "query").map((p) => ({ key: p.name, value: "", description: p.description, disabled: !p.required })),
      },
      description: [op.description || op.summary, op.tokenOk ? "Accepts an API token (Bearer {{apiToken}})." : "Needs a browser session: send POST /api/v1/login first (Postman keeps the cookie), then put the csrf_token it returns in {{csrfToken}}."].filter(Boolean).join("\n\n"),
    };
    if (!op.tokenOk) req.auth = { type: "noauth" };
    if (op.bodyContentType === "application/json" && op.bodyExample !== null) req.body = { mode: "raw", raw: json(op.bodyExample), options: { raw: { language: "json" } } };
    const list = folders.get(op.tag) ?? [];
    list.push({ name: `${op.summary || op.path}`, request: req });
    folders.set(op.tag, list);
  }
  return {
    info: {
      name: `${spec.info.title} ${spec.info.version}`,
      description: "Generated from the live OpenAPI document. Set apiToken (Administrators & API tokens) for /api/v1/admin/** calls.",
      schema: "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    auth: { type: "bearer", bearer: [{ key: "token", value: "{{apiToken}}", type: "string" }] },
    variable: [{ key: "baseUrl", value: base }, { key: "apiToken", value: "" }, { key: "csrfToken", value: "" }],
    item: Array.from(folders, ([name, item]) => ({ name, item })).sort((a, b) => a.name.localeCompare(b.name)),
  };
}

export function download(filename: string, content: string, type = "application/json") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
