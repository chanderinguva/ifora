"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Badge, PageHeader, td, th } from "@/components/bits";
import { http, qs } from "@/lib/http";
import { SIGN_ON_LABEL, type AppSummary } from "@/lib/applications";

export default function Applications() {
  const router = useRouter();
  const [items, setItems] = useState<AppSummary[] | null>(null);
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(() => {
    http<{ items: AppSummary[] }>(`/admin/applications${qs({ q })}`).then((r) => setItems(r.items)).catch((e) => setMsg(e.message));
  }, [q]);
  useEffect(load, [load]);

  return (
    <div>
      <PageHeader title="Applications">
        <Button onClick={() => router.push("/admin/applications/new")} data-testid="add-app"><Plus className="mr-1 h-4 w-4" /> Create App Integration</Button>
      </PageHeader>
      <p className="mb-4 max-w-2xl text-sm text-muted-foreground">
        One application holds who may use it (users and groups). Attach a sign-on method (a bookmark or an OpenID Connect client) and, optionally, outbound provisioning to it.
      </p>
      {msg && <Alert variant="destructive" className="mb-4" role="status"><AlertDescription>{msg}</AlertDescription></Alert>}

      <div className="mb-3 max-w-xs"><Input aria-label="Search applications" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <Card><CardContent className="overflow-x-auto p-0">
        <table className="w-full" data-testid="apps-table">
          <thead className="border-b"><tr><th className={th}>Name</th><th className={th}>Sign-on</th><th className={th}>Provisioning</th><th className={th}>Assigned</th><th className={th}>Status</th></tr></thead>
          <tbody>
            {items?.map((a) => (
              <tr key={a.id} className="border-b last:border-0">
                <td className={td + " font-medium"}><Link className="underline-offset-4 hover:underline" href={`/admin/applications/${a.id}`}>{a.name}</Link></td>
                <td className={td}>{SIGN_ON_LABEL[a.sign_on_mode]}</td>
                <td className={td}>{a.provisioning ? <Badge tone={a.provisioning.enabled ? "good" : "neutral"}>{a.provisioning.kind.toUpperCase()}{a.provisioning.enabled ? "" : " (off)"}</Badge> : "—"}</td>
                <td className={td}>{a.assigned_users} users, {a.assigned_groups} groups</td>
                <td className={td}><Badge tone={a.status === "active" ? "good" : "neutral"}>{a.status}</Badge></td>
              </tr>
            ))}
            {items && items.length === 0 && <tr><td className={td} colSpan={5}>No applications yet.</td></tr>}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  );
}
