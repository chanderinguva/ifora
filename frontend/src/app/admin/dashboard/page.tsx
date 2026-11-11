"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { PageHeader, fmt, mono, td, th } from "@/components/bits";
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
    <ul className="space-y-3 text-sm">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[minmax(0,9rem)_1fr_2rem] items-center gap-3">
          <span className="truncate capitalize text-muted-foreground">{r.label}</span>
          <span className="h-1 rounded-full bg-secondary" aria-hidden><span className="block h-1 rounded-full bg-foreground/70" style={{ width: `${(r.value / max) * 100}%` }} /></span>
          <span className="text-right font-mono tabular-nums">{r.value}</span>
        </li>
      ))}
    </ul>
  );
}

/** A smooth path through the points with horizontal tangents, so a line never overshoots the data. */
function smooth(pts: [number, number][]) {
  return pts.reduce((d, [x, y], i) => {
    if (i === 0) return `M${x},${y}`;
    const [px, py] = pts[i - 1];
    const mx = (px + x) / 2;
    return `${d} C${mx},${py} ${mx},${y} ${x},${y}`;
  }, "");
}

/**
 * Sign-ins per day. Successes rise above a baseline, failures are mirrored below it on the same scale,
 * and today (the latest point) carries the accent. Coordinates are percentages, so it stretches to its card.
 */
function SigninChart({ days }: { days: Dash["signins"] }) {
  const BASE = 70, UP = 62, DOWN = 24, PAD = 4;
  const maxS = Math.max(1, ...days.map((d) => d.success));
  const maxF = Math.max(0, ...days.map((d) => d.failure));
  const scale = Math.min(UP / maxS, maxF > 0 ? DOWN / maxF : Infinity);
  const x = (i: number) => (days.length < 2 ? 50 : PAD + (i / (days.length - 1)) * (100 - 2 * PAD));
  const up = days.map((d, i): [number, number] => [x(i), BASE - d.success * scale]);
  const down = days.map((d, i): [number, number] => [x(i), BASE + d.failure * scale]);
  const area = (pts: [number, number][]) => pts.length > 1 ? `${smooth(pts)} L${pts[pts.length - 1][0]},${BASE} L${pts[0][0]},${BASE} Z` : "";
  const today = days[days.length - 1];
  const total = days.reduce((n, d) => ({ s: n.s + d.success, f: n.f + d.failure }), { s: 0, f: 0 });
  return (
    <div>
      <p className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-primary" />Succeeded <span className="font-mono tabular-nums text-foreground">{total.s}</span></span>
        <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-bad" />Failed <span className="font-mono tabular-nums text-foreground">{total.f}</span></span>
      </p>
      <div className="relative h-56" role="img" aria-label={`Sign-ins per day: ${days.map((d) => `${d.date} ${d.success} succeeded, ${d.failure} failed`).join("; ")}`}>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden="true">
          {[BASE - UP / 2, BASE + DOWN / 2].map((y) => <line key={y} x1="0" x2="100" y1={y} y2={y} className="stroke-border" strokeWidth="1" vectorEffect="non-scaling-stroke" />)}
          <line x1="0" x2="100" y1={BASE} y2={BASE} className="stroke-muted-foreground/40" strokeWidth="1" vectorEffect="non-scaling-stroke" />
          <path d={area(up)} className="fill-primary/10" />
          <path d={smooth(up)} className="fill-none stroke-primary" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
          <path d={area(down)} className="fill-bad/10" />
          <path d={smooth(down)} className="fill-none stroke-bad/70" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        </svg>
        {today && <span aria-hidden="true" className="absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary ring-4 ring-card" style={{ left: `${x(days.length - 1)}%`, top: `${up[up.length - 1][1]}%` }} />}
        <div className="absolute inset-0 flex">
          {days.map((d) => <div key={d.date} className="h-full flex-1" title={`${d.date}: ${d.success} succeeded, ${d.failure} failed`} />)}
        </div>
      </div>
      <div className="mt-2 flex font-mono text-[11px] text-muted-foreground">
        {days.map((d, i) => <span key={d.date} className={"flex-1 text-center tabular-nums " + (i === days.length - 1 ? "text-foreground" : "")}>{d.date.slice(5)}</span>)}
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [dash, setDash] = useState<Dash | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    http<Dash>("/admin/dashboard").then(setDash).catch(() => {});
    http<Stats>("/admin/stats").then(setStats).catch((e) => setError(e.message));
  }, []);

  const tiles = stats
    ? [
        { label: "Users", value: stats.users_total, hint: `${stats.users_active} active`, href: "/admin/users" },
        { label: "Administrators", value: stats.admins, hint: "with admin rights", href: "/admin/users" },
        { label: "Groups", value: stats.groups, hint: `${stats.memberships} memberships`, href: "/admin/groups" },
        { label: "Active sessions", value: stats.active_sessions, hint: "unexpired, not revoked", href: "/admin/audit" },
        { label: "Failed logins (24h)", value: stats.failed_logins_24h, hint: "from audit log", href: "/admin/audit?action=LOGIN_FAILURE" },
      ]
    : [];

  return (
    <div>
      <PageHeader title="Overview" />

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
                <Link href={t.href} className="flex items-center justify-between gap-3 py-2.5 text-sm transition-colors hover:bg-accent/60" data-testid={`task-${t.id}`}>
                  <span className="flex items-center gap-2"><Badge tone={SEV_TONE[t.severity]}>{t.severity}</Badge>{t.title}</span>
                  <span className="font-mono tabular-nums">{t.count}</span>
                </Link>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5" data-testid="stats">
        {tiles.map(({ label, value, hint, href }) => (
          <Link key={label} href={href} className="rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <Card className="h-full transition-colors hover:bg-accent/60">
              <CardContent className="space-y-1 p-5">
                <p className="text-sm text-muted-foreground">{label}</p>
                <div className="text-2xl font-medium tabular-nums" data-testid={`stat-${label}`}>{value}</div>
                <p className="text-xs text-muted-foreground">{hint}</p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      {dash && (
        <div className="mt-6 grid gap-4 lg:grid-cols-3" data-testid="widgets">
          <Card className="lg:col-span-2"><CardHeader><CardTitle>Sign-ins, last 7 days</CardTitle></CardHeader><CardContent><SigninChart days={dash.signins} /></CardContent></Card>
          <div className="space-y-4">
            <Card><CardHeader><CardTitle>Users by status</CardTitle></CardHeader><CardContent>
              <Bars rows={Object.entries(dash.users_by_status).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: k.replace(/_/g, " "), value: v }))} /></CardContent></Card>
            <Card><CardHeader><CardTitle>Applications <span className={mono}>{dash.apps_total}</span></CardTitle></CardHeader><CardContent>
              {dash.apps_total === 0 ? <p className="text-sm text-muted-foreground">No applications yet.</p> : <Bars rows={Object.entries(dash.apps_by_mode).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: MODE[k] ?? k, value: v }))} />}</CardContent></Card>
          </div>
        </div>
      )}

      <Card className="mt-6">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Recent activity</CardTitle>
          <Link href="/admin/audit" className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
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
                  <td className={td + " " + mono}>{fmt(e.timestamp)}</td>
                  <td className={td}>{e.actor_email ?? "system"}</td>
                  <td className={td + " font-mono text-[13px]"}>{e.action}</td>
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
