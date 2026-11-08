"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { Badge, fmt, td, th } from "@/components/bits";
import { http } from "@/lib/http";

type UserApp = { id: number; name: string; sign_on_mode: string; status: string; direct: boolean; groups: string[] };
type Ev = { id: number; timestamp: string; action: string; actor_email?: string | null; target_id?: string | null; metadata?: Record<string, unknown> | null };

export function UserApplications({ userId }: { userId: number }) {
  const [items, setItems] = useState<UserApp[] | null>(null);
  useEffect(() => { http<{ items: UserApp[] }>(`/admin/users/${userId}/applications`).then((r) => setItems(r.items)).catch(() => setItems([])); }, [userId]);
  return (
    <Card data-testid="user-apps"><CardContent className="overflow-x-auto p-0">
      <table className="w-full"><thead className="border-b"><tr><th className={th}>Application</th><th className={th}>Sign-on</th><th className={th}>Access via</th><th className={th}>Status</th></tr></thead>
        <tbody>
          {items?.map((a) => (
            <tr key={a.id} className="border-b last:border-0">
              <td className={td + " font-medium"}><Link className="underline-offset-4 hover:underline" href={`/admin/applications/${a.id}`}>{a.name}</Link></td>
              <td className={td}>{a.sign_on_mode}</td>
              <td className={td}>{[a.direct ? "Assigned directly" : null, ...a.groups.map((g) => `Group: ${g}`)].filter(Boolean).join(", ")}</td>
              <td className={td}><Badge tone={a.status === "active" ? "good" : "neutral"}>{a.status}</Badge></td>
            </tr>
          ))}
          {items && items.length === 0 && <tr><td className={td} colSpan={4}>This user has no applications.</td></tr>}
          {!items && <tr><td className={td} colSpan={4}>Loading…</td></tr>}
        </tbody></table>
    </CardContent></Card>
  );
}

export function UserActivity({ userId }: { userId: number }) {
  const [items, setItems] = useState<Ev[] | null>(null);
  useEffect(() => { http<{ items: Ev[] }>(`/admin/users/${userId}/events`).then((r) => setItems(r.items)).catch(() => setItems([])); }, [userId]);
  return (
    <Card data-testid="user-activity"><CardContent className="overflow-x-auto p-0">
      <table className="w-full"><thead className="border-b"><tr><th className={th}>When</th><th className={th}>Event</th><th className={th}>By</th></tr></thead>
        <tbody>
          {items?.map((e) => (
            <tr key={e.id} className="border-b last:border-0">
              <td className={td}>{fmt(e.timestamp)}</td>
              <td className={td + " font-medium"}>{e.action.replace(/_/g, " ")}</td>
              <td className={td}>{e.actor_email ?? "—"}</td>
            </tr>
          ))}
          {items && items.length === 0 && <tr><td className={td} colSpan={3}>No activity recorded.</td></tr>}
          {!items && <tr><td className={td} colSpan={3}>Loading…</td></tr>}
        </tbody></table>
    </CardContent></Card>
  );
}
