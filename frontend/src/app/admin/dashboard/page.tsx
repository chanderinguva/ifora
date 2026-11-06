"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, ShieldAlert, Shield, Users, UserCheck, Network } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { PageHeader, fmt, td, th } from "@/components/bits";
import { useCurrentUser } from "@/components/auth-guard";
import { http } from "@/lib/http";
import type { Stats } from "@/lib/types";

export default function AdminDashboard() {
  const me = useCurrentUser();
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    http<Stats>("/admin/stats").then(setStats).catch((e) => setError(e.message));
  }, []);

  const tiles = stats
    ? [
        { label: "Users", value: stats.users_total, hint: `${stats.users_active} active`, icon: Users, href: "/admin/users" },
        { label: "Administrators", value: stats.admins, hint: "with admin rights", icon: UserCheck, href: "/admin/users" },
        { label: "Groups", value: stats.groups, hint: `${stats.memberships} memberships`, icon: Shield, href: "/admin/groups" },
        { label: "Active sessions", value: stats.active_sessions, hint: "unexpired, not revoked", icon: Activity, href: "/admin/audit" },
        { label: "Failed logins (24h)", value: stats.failed_logins_24h, hint: "from audit log", icon: ShieldAlert, href: "/admin/audit?action=LOGIN_FAILURE" },
        { label: "Memberships", value: stats.memberships, hint: "user ↔ group links", icon: Network, href: "/admin/groups" },
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

      <Card className="mt-8">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Recent activity</CardTitle>
          <Link href="/admin/audit" className="text-sm underline-offset-4 hover:underline">
            View all
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
