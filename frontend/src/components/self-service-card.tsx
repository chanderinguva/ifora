"use client";

import { useEffect, useRef, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { http } from "@/lib/http";

type Cfg = { enabled: boolean; reason_required: boolean };

/** Lets people who are not assigned ask for this application; an administrator then approves or denies. */
export function SelfServiceCard({ appId }: { appId: number }) {
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    http<Cfg>(`/admin/applications/${appId}/self-service`).then(setCfg).catch((e) => setMsg({ ok: false, text: e.message }));
  }, [appId]);
  async function save(next: Cfg) {
    setMsg(null);
    const before = cfg;
    setCfg(next);  // optimistic: the box flips at once, and flips back if the server refuses
    try { setCfg(await http<Cfg>(`/admin/applications/${appId}/self-service`, { method: "PUT", body: next })); setMsg({ ok: true, text: "Saved" }); }
    catch (e) { setCfg(before); setMsg({ ok: false, text: e instanceof Error ? e.message : "Could not save" }); }
  }
  if (!cfg) return msg ? <Alert variant="destructive" className="mb-6"><AlertDescription>{msg.text}</AlertDescription></Alert> : null;
  return (
    <Card className="mb-6" data-testid="self-service-card">
      <CardHeader><CardTitle>Self service</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-1" checked={cfg.enabled} onChange={(e) => save({ ...cfg, enabled: e.target.checked })} data-testid="self-service-enabled" />
          <span><strong>Let people request access.</strong> The application then appears under “Request access” for users who are not assigned. Asking grants nothing until an administrator approves.</span>
        </label>
        <label className={"flex items-start gap-2 " + (cfg.enabled ? "" : "opacity-50")}>
          <input type="checkbox" className="mt-1" disabled={!cfg.enabled} checked={cfg.reason_required} onChange={(e) => save({ ...cfg, reason_required: e.target.checked })} data-testid="self-service-reason" />
          <span>Require a reason with each request</span>
        </label>
        {msg && <p role="status" className={msg.ok ? "text-muted-foreground" : "text-destructive"}>{msg.text}</p>}
      </CardContent>
    </Card>
  );
}
