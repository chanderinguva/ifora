"use client";

import { useEffect, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader, Pager, fieldClass, fmt, td, th } from "@/components/bits";
import { http, qs, type Page } from "@/lib/http";
import type { AuditEvent } from "@/lib/types";

const ACTIONS = [
  "LOGIN_SUCCESS", "LOGIN_FAILURE", "LOGOUT", "ADMIN_BOOTSTRAP",
  "USER_CREATED", "USER_UPDATED", "USER_DEACTIVATED", "USER_ACTIVATED", "USER_PASSWORD_CHANGED", "USER_DELETED", "PROFILE_UPDATED",
  "GROUP_CREATED", "GROUP_UPDATED", "GROUP_DELETED", "GROUP_MEMBER_ADDED", "GROUP_MEMBER_REMOVED",
];
const PAGE_SIZE = 25;

export default function AuditPage() {
  const [data, setData] = useState<Page<AuditEvent> | null>(null);
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get("action");
    if (p && ACTIONS.includes(p)) setAction(p);
  }, []);

  useEffect(() => {
    http<Page<AuditEvent>>(`/admin/audit${qs({ action, page, page_size: PAGE_SIZE })}`).then(setData).catch((e) => setError(e.message));
  }, [action, page]);

  return (
    <div>
      <PageHeader title="Audit log">
        <select aria-label="Filter by action" className={fieldClass + " w-60"} value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }}>
          <option value="">All actions</option>
          {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
      </PageHeader>
      {error && <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert>}
      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full" data-testid="audit-table">
            <thead className="border-b">
              <tr><th className={th}>When</th><th className={th}>Actor</th><th className={th}>Action</th><th className={th}>Target</th><th className={th}>IP</th><th className={th}>Details</th></tr>
            </thead>
            <tbody>
              {data?.items.map((e) => (
                <tr key={e.id} className="border-b align-top last:border-0">
                  <td className={td}>{fmt(e.timestamp)}</td>
                  <td className={td}>{e.actor_email ?? (e.actor_id ? `#${e.actor_id}` : "system")}</td>
                  <td className={td}>{e.action}</td>
                  <td className={td}>{e.target_type ? `${e.target_type} #${e.target_id}` : "—"}</td>
                  <td className={td}>{e.actor_ip_address ?? "—"}</td>
                  <td className={td + " max-w-xs break-words font-mono text-xs"}>{e.metadata ? JSON.stringify(e.metadata) : "—"}</td>
                </tr>
              ))}
              {data && data.items.length === 0 && <tr><td className={td} colSpan={6}>No events.</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>
      {data && <Pager page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />}
    </div>
  );
}
