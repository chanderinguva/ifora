"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, ShieldAlert, Shield, Users, UserCheck } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { PageHeader, fmt, td, th } from "@/components/bits";
import { useCurrentUser } from "@/components/auth-guard";
import { http } from "@/lib/http";
import { Badge } from "@/components/bits";
import type { Stats } from "@/lib/types";

type Task = { id: string; severity: "high" | "medium" | "info"; title: string; count: number; href: string };
type Dash = { tasks: Task[]; signins: { date: string; success: number; failure: number }[]; users_by_status: Record<string, number>; apps_by_mode: Record<string, number>; apps_total: number };
const SEV_TONE = { high: "bad", medium: "info", info: "neutral" } as const;
const MODE = { oidc: "OpenID Connect", saml: "SAML 2.0", swa: "Secure Web Auth", bookmark: "Bookmark", none: "Provisioning only" } as Record<string, string>;

function Bars({ rows }: { rows: { label: string; value: number }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="space-y-2 text-sm">
      {rows.map((r) => (
        <li key={r.label} className="flex items-center gap-3">
          <span className="w-36 shrink-0 truncate text-muted-foreground">{r.label}</span>
          <span className="h-2 flex-1 rounded bg-secondary" aria-hidden><span className="block h-2 rounded bg-primary" style={{ width: `${(r.value / max) * 100}%` }} /></span>
          <span className="w-8 text-right tabular-nums">{r.value}</span>
        </li>
      ))}
    </ul>
  );
}

function SigninChart({ days }: { days: Dash["signins"] }) {
  const max = Math.max(1, ...days.map((d) => d.success + d.failure));
  return (
    <div>
      <div className="flex h-32 items-end gap-2" role="img" aria-label={`Sign-ins per day: ${days.map((d) => `${d.date} ${d.success} succeeded, ${d.failure} failed`).join("; ")}`}>
        {days.map((d) => (
          <div key={d.date} className="flex h-full flex-1 flex-col justify-end" title={`${d.date}: ${d.success} succeeded, ${d.failure} failed`}>
            <div className="bg-destructive/70" style={{ height: `${(d.failure / max) * 100}%` }} />
            <div className="bg-primary" style={{ height: `${(d.success / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-2 text-[10px] text-muted-foreground">{days.map((d) => <span key={d.date} className="flex-1 text-center">{d.date.slice(5)}</span>)}</div>
      <p className="mt-2 text-xs text-muted-foreground"><span className="mr-1 inline-block h-2 w-2 bg-primary" /> succeeded <span className="ml-3 mr-1 inline-block h-2 w-2 bg-destructive/70" /> failed</p>
    </div>
  );
}

export default function AdminDashboard() {
  const me = useCurrentUser();
  const [stats, setStats] = useState<Stats | null>(null);
  const [dash, setDash] = useState<Dash | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    http<Dash>("/admin/dashboard").then(setDash).catch(() => {});
    http<Stats>("/admin/stats").then(setStats).catch((e) => setError(e.message));
  }, []);

  const tiles = stats
    ? [
        { label: "Users", value: stats.users_total, hint: `${stats.users_active} active`, icon: Users, href: "/admin/users" },
        { label: "Administrators", value: stats.admins, hint: "with admin rights", icon: UserCheck, href: "/admin/users" },
        { label: "Groups", value: stats.groups, hint: `${stats.memberships} memberships`, icon: Shield, href: "/admin/groups" },
        { label: "Active sessions", value: stats.active_sessions, hint: "unexpired, not revoked", icon: Activity, href: "/admin/audit" },
        { label: "Failed logins (24h)", value: stats.failed_logins_24h, hint: "from audit log", icon: ShieldAlert, href: "/admin/audit?action=LOGIN_FAILURE" },
      ]
    : [];

  return (
    <div>
      <PageHeader title="Admin Dashboard" />
      <p className="mb-6 text-sm text-muted-foreground">Welcome, {me.first_name}.</p>

      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card className="mb-6" data-testid="tasks">
        <CardHeader><CardTitle>Tasks</CardTitle></CardHeader>
        <CardContent>
          {dash && dash.tasks.length === 0 && <p className="text-sm text-muted-foreground" data-testid="tasks-empty">Nothing needs your attention.</p>}
          {!dash && <p className="text-sm text-muted-foreground">Loading…</p>}
          <ul className="divide-y">
            {dash?.tasks.map((t) => (
              <li key={t.id}>
                <Link href={t.href} className="flex items-center justify-between gap-3 py-2 text-sm hover:bg-accent/40" data-testid={`task-${t.id}`}>
                  <span className="flex items-center gap-2"><Badge tone={SEV_TONE[t.severity]}>{t.severity}</Badge>{t.title}</span>
                  <span className="font-semibold tabular-nums">{t.count}</span>
                </Link>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" data-testid="stats">
        {tiles.map(({ label, value, hint, icon: Icon, href }) => (
          <Link key={label} href={href}>
            <Card className="transition-colors hover:bg-accent/40">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">{label}</CardTitle>
                <Icon className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold" data-testid={`stat-${label}`}>{value}</div>
                <p className="text-xs text-muted-foreground">{hint}</p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      {dash && (
        <div className="mt-8 grid gap-4 lg:grid-cols-3" data-testid="widgets">
          <Card><CardHeader><CardTitle className="text-base">Sign-ins, last 7 days</CardTitle></CardHeader><CardContent><SigninChart days={dash.signins} /></CardContent></Card>
          <Card><CardHeader><CardTitle className="text-base">Users by status</CardTitle></CardHeader><CardContent>
            <Bars rows={Object.entries(dash.users_by_status).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: k.replace(/_/g, " "), value: v }))} /></CardContent></Card>
          <Card><CardHeader><CardTitle className="text-base">Applications ({dash.apps_total})</CardTitle></CardHeader><CardContent>
            {dash.apps_total === 0 ? <p className="text-sm text-muted-foreground">No applications yet.</p> : <Bars rows={Object.entries(dash.apps_by_mode).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: MODE[k] ?? k, value: v }))} />}</CardContent></Card>
        </div>
      )}

      <Card className="mt-8">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Recent activity</CardTitle>
          <Link href="/admin/audit" className="text-sm underline-offset-4 hover:underline">
            Open system log
          </Link>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full">
            <thead className="border-b">
              <tr>
                <th className={th}>When</th>
                <th className={th}>Actor</th>
                <th className={th}>Action</th>
              </tr>
            </thead>
            <tbody>
              {stats?.recent_events.map((e) => (
                <tr key={e.id} className="border-b last:border-0">
                  <td className={td}>{fmt(e.timestamp)}</td>
                  <td className={td}>{e.actor_email ?? "system"}</td>
                  <td className={td}>{e.action}</td>
                </tr>
              ))}
              {stats && stats.recent_events.length === 0 && (
                <tr>
                  <td className={td} colSpan={3}>No events yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
