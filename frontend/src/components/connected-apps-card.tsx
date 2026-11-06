"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { fmt } from "@/components/bits";
import { http } from "@/lib/http";

type App = { client_pk: number; name: string; description: string | null; scopes: string[]; granted_at: string };

/** Third-party applications the user allowed to sign them in. Withdrawing also ends the app's refresh tokens. */
export function ConnectedAppsCard() {
  const [apps, setApps] = useState<App[] | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const load = useCallback(() => http<{ items: App[] }>("/me/consents").then((r) => setApps(r.items)).catch(() => setApps([])), []);
  useEffect(() => { load(); }, [load]);

  if (!apps || apps.length === 0) return null; // nothing connected: no card to explain
  return (
    <Card className="mb-6" data-testid="connected-apps">
      <CardHeader><CardTitle>Connected applications</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {msg && <Alert variant={msg.ok ? "default" : "destructive"} role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
        <p className="text-sm text-muted-foreground">Applications you allowed to sign you in. Withdrawing access signs them out of your account; they must ask you again.</p>
        <ul className="divide-y">
          {apps.map((a) => (
            <li key={a.client_pk} className="flex flex-wrap items-center justify-between gap-2 py-3">
              <div>
                <div className="font-medium">{a.name}</div>
                <div className="text-xs text-muted-foreground">Allowed {fmt(a.granted_at)} · {a.scopes.filter((s) => s !== "openid").join(", ") || "basic sign-in"}</div>
              </div>
              <Button size="sm" variant="outline" aria-label={`Withdraw access for ${a.name}`}
                onClick={async () => {
                  if (!confirm(`Withdraw ${a.name}'s access to your account?`)) return;
                  try { await http(`/me/consents/${a.client_pk}`, { method: "DELETE" }); setMsg({ ok: true, text: `${a.name} can no longer access your account` }); await load(); }
                  catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
                }}>Withdraw access</Button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
