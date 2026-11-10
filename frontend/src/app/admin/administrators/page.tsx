"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fieldClass, fmt, td, th } from "@/components/bits";
import { http } from "@/lib/http";

type Admin = {
  id: number; name: string; email: string; status: string; is_super_admin: boolean; mfa: boolean; last_login_at: string | null; active_api_tokens: number;
  roles: { role: string; sources: { via: string; group_name?: string }[] }[];
};
type Token = {
  id: number; name: string; token_prefix: string; status: string; read_only: boolean; allowed_cidrs: string[]; expires_at: string; last_used_at: string | null;
  last_used_ip: string | null; owner?: { name: string; email: string } | null;
};
type TokenList = { items: Token[]; max_days: number; default_days: number; max_active: number };
const msgOf = (e: unknown) => (e instanceof Error ? e.message : "Failed");

export default function Administrators() {
  const [tab, setTab] = useState<"admins" | "tokens">("admins");
  return (
    <div className="max-w-6xl">
      <PageHeader title="Administrators & API tokens" />
      <div className="mb-4 flex gap-1 border-b" role="tablist">
        {([["admins", "Administrators"], ["tokens", "API tokens"]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} data-testid={`tab-${k}`} onClick={() => setTab(k)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${tab === k ? "border-primary font-medium" : "border-transparent text-muted-foreground hover:text-foreground"}`}>{l}</button>
        ))}
      </div>
      {tab === "admins" ? <Admins /> : <Tokens />}
    </div>
  );
}

function Admins() {
  const [items, setItems] = useState<Admin[] | null>(null);
  const [role, setRole] = useState("");
  const [noMfa, setNoMfa] = useState(false);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    const p = new URLSearchParams();
    if (role) p.set("role", role);
    if (noMfa) p.set("mfa", "none");
    if (q) p.set("q", q);
    http<{ Resources: Admin[] }>(`/admin/administrators?${p}`).then((r) => setItems(r.Resources)).catch((e) => setError(msgOf(e)));
  }, [role, noMfa, q]);
  return (
    <>
      <p className="mb-4 text-sm text-muted-foreground">Everyone who can administer, whether the role is assigned directly or comes from a group.</p>
      {error && <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert>}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input aria-label="Search administrators" placeholder="Search" className="max-w-xs" value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Filter by role" className={fieldClass + " w-56"} value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="">All roles</option>
          <option value="super_admin">Super administrator</option>
          {["org_admin", "read_only_admin", "help_desk_admin", "app_admin", "group_admin", "report_admin"].map((r) => <option key={r} value={r}>{r.replace(/_/g, " ")}</option>)}
        </select>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={noMfa} onChange={(e) => setNoMfa(e.target.checked)} /> Without a second factor</label>
      </div>
      <Card><CardContent className="overflow-x-auto p-0">
        <table className="w-full" data-testid="admins-table">
          <thead className="border-b"><tr><th className={th}>Administrator</th><th className={th}>Roles</th><th className={th}>Second factor</th><th className={th}>Last sign-in</th><th className={th}>API tokens</th></tr></thead>
          <tbody>
            {items?.map((a) => (
              <tr key={a.id} className="border-b last:border-0">
                <td className={td}><Link className="font-medium underline-offset-4 hover:underline" href={`/admin/users/${a.id}`}>{a.name}</Link><div className="text-xs text-muted-foreground">{a.email}{a.status !== "active" && ` · ${a.status}`}</div></td>
                <td className={td}>
                  <div className="flex flex-wrap gap-1">
                    {a.is_super_admin && <Badge tone="info">super administrator</Badge>}
                    {a.roles.map((r) => (
                      <span key={r.role} title={r.sources.map((s) => (s.via === "direct" ? "assigned directly" : `via group ${s.group_name}`)).join("; ")}><Badge>{r.role.replace(/_/g, " ")}</Badge></span>
                    ))}
                    {!a.is_super_admin && a.roles.length === 0 && <span className="text-xs text-muted-foreground">no role</span>}
                  </div>
                </td>
                <td className={td}>{a.mfa ? <Badge tone="good">enrolled</Badge> : <Badge tone="bad">none</Badge>}</td>
                <td className={td}>{a.last_login_at ? fmt(a.last_login_at) : "never"}</td>
                <td className={td}>{a.active_api_tokens}</td>
              </tr>
            ))}
            {items && items.length === 0 && <tr><td className={td} colSpan={5}>No administrators match.</td></tr>}
          </tbody>
        </table>
      </CardContent></Card>
    </>
  );
}

function Tokens() {
  const [data, setData] = useState<TokenList | null>(null);
  const [all, setAll] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [days, setDays] = useState(30);
  const [readOnly, setReadOnly] = useState(false);
  const [cidrs, setCidrs] = useState("");
  const [shown, setShown] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const load = useCallback(() => {
    http<TokenList>(`/admin/api-tokens${all ? "?all=true" : ""}`).then(setData).catch((e) => { setMsg({ ok: false, text: msgOf(e) }); if (all) setAll(false); });
  }, [all]);
  useEffect(load, [load]);

  async function create() {
    try {
      const t = await http<{ token: string }>("/admin/api-tokens", { method: "POST", body: { name, password, expires_in_days: days, read_only: readOnly, allowed_cidrs: cidrs.split("\n").map((x) => x.trim()).filter(Boolean) } });
      setShown(t.token); setCreating(false); setName(""); setPassword(""); setCidrs(""); setMsg(null); load();
    } catch (e) { setMsg({ ok: false, text: msgOf(e) }); }
  }
  async function revoke(t: Token) {
    if (!confirm(`Revoke the token "${t.name}"? Anything using it stops working immediately.`)) return;
    try { await http(`/admin/api-tokens/${t.id}`, { method: "DELETE" }); setMsg({ ok: true, text: "Token revoked" }); load(); } catch (e) { setMsg({ ok: false, text: msgOf(e) }); }
  }
  return (
    <>
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">A token acts as you, with exactly the permissions of your administrator roles at the time of each call. Use it as <code>Authorization: Bearer …</code> on <code>/api/v1/admin/**</code>. Tokens expire (default {data?.default_days ?? 30} days, at most {data?.max_days ?? 90}) and cannot manage tokens.</p>
        <Button onClick={() => { setCreating(true); setShown(null); setMsg(null); }} data-testid="token-new">Create token</Button>
      </div>
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
      {shown && (
        <Alert className="mb-4" data-testid="token-reveal"><AlertDescription>
          <p className="mb-1 font-medium">Copy your token now. It is shown only once.</p>
          <code className="block break-all rounded bg-muted p-2 text-xs" data-testid="token-value">{shown}</code>
          <div className="mt-2 flex gap-2"><Button size="sm" variant="outline" onClick={() => navigator.clipboard?.writeText(shown)}>Copy</Button><Button size="sm" variant="ghost" onClick={() => setShown(null)}>Done</Button></div>
        </AlertDescription></Alert>
      )}
      {creating && (
        <Card className="mb-4" data-testid="token-form"><CardContent className="grid gap-3 pt-6 sm:grid-cols-2">
          <div className="space-y-1"><Label htmlFor="t-name">Name</Label><Input id="t-name" maxLength={100} placeholder="CI pipeline" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="t-days">Expires in (days, max {data?.max_days ?? 90})</Label><Input id="t-days" type="number" min={1} max={data?.max_days ?? 90} value={days} onChange={(e) => setDays(Number(e.target.value))} /></div>
          <div className="space-y-1 sm:col-span-2"><Label htmlFor="t-cidrs">Allowed IP addresses or ranges (one per line, empty = any)</Label><textarea id="t-cidrs" rows={2} className={fieldClass} value={cidrs} onChange={(e) => setCidrs(e.target.value)} /></div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={readOnly} onChange={(e) => setReadOnly(e.target.checked)} /> Read-only (GET requests only)</label>
          <div className="space-y-1"><Label htmlFor="t-pw">Confirm with your password</Label><Input id="t-pw" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></div>
          <div className="flex gap-2 sm:col-span-2"><Button disabled={!name.trim() || !password} onClick={create} data-testid="token-create">Create</Button><Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button></div>
        </CardContent></Card>
      )}
      <label className="mb-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Show everyone&apos;s tokens (super and organization administrators)</label>
      <Card><CardContent className="overflow-x-auto p-0">
        <table className="w-full" data-testid="tokens-table">
          <thead className="border-b"><tr><th className={th}>Name</th><th className={th}>Token</th>{all && <th className={th}>Owner</th>}<th className={th}>Status</th><th className={th}>Expires</th><th className={th}>Last used</th><th className={th}></th></tr></thead>
          <tbody>
            {data?.items.map((t) => (
              <tr key={t.id} className="border-b last:border-0">
                <td className={td + " font-medium"}>{t.name}{t.read_only && <> <Badge>read-only</Badge></>}{t.allowed_cidrs.length > 0 && <> <Badge>{t.allowed_cidrs.length} IP rule(s)</Badge></>}</td>
                <td className={td + " font-mono text-xs"}>{t.token_prefix}…</td>
                {all && <td className={td}>{t.owner?.name ?? "—"}</td>}
                <td className={td}><Badge tone={t.status === "active" ? "good" : "neutral"}>{t.status}</Badge></td>
                <td className={td}>{fmt(t.expires_at)}</td>
                <td className={td}>{t.last_used_at ? `${fmt(t.last_used_at)}${t.last_used_ip ? ` from ${t.last_used_ip}` : ""}` : "never"}</td>
                <td className={td + " text-right"}>{t.status === "active" && <Button size="sm" variant="ghost" aria-label={`Revoke ${t.name}`} onClick={() => revoke(t)}>Revoke</Button>}</td>
              </tr>
            ))}
            {data && data.items.length === 0 && <tr><td className={td} colSpan={all ? 7 : 6}>No API tokens yet.</td></tr>}
          </tbody>
        </table>
      </CardContent></Card>
    </>
  );
}
