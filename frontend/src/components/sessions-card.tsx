"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Badge, fmt } from "@/components/bits";
import { http } from "@/lib/http";

type SessionRow = {
  handle: string;
  current: boolean;
  device: string;
  ip_address: string | null;
  created_at: string;
  last_activity_at: string | null;
  expires_at: string;
};

/** The caller's own signed-in devices. Signing one out (or all others) asks for the password again. */
export function SessionsCard({ reloadKey = 0 }: { reloadKey?: number }) {
  const [rows, setRows] = useState<SessionRow[] | null>(null);
  const [asking, setAsking] = useState<string | "others" | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = () =>
    http<{ items: SessionRow[] }>("/me/sessions")
      .then((r) => setRows(r.items))
      .catch((e) => setMsg({ ok: false, text: e instanceof Error ? e.message : "Could not load sessions" }));

  useEffect(() => {
    load();
  }, [reloadKey]);

  const cancel = () => {
    setAsking(null);
    setPassword("");
  };

  async function confirm() {
    if (!asking) return;
    setBusy(true);
    setMsg(null);
    try {
      if (asking === "others") {
        const r = await http<{ revoked: number }>("/me/sessions/revoke-others", { method: "POST", body: { password } });
        setMsg({ ok: true, text: r.revoked === 1 ? "Signed out 1 other session." : `Signed out ${r.revoked} other sessions.` });
      } else {
        await http(`/me/sessions/${encodeURIComponent(asking)}/revoke`, { method: "POST", body: { password } });
        setMsg({ ok: true, text: "That session was signed out." });
      }
      cancel();
      await load();
      window.dispatchEvent(new Event("activity-changed"));
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  const others = (rows ?? []).filter((r) => !r.current).length;

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle>Where you&apos;re signed in</CardTitle>
      </CardHeader>
      <CardContent>
        {msg && (
          <Alert variant={msg.ok ? "success" : "destructive"} className="mb-3" role="status">
            <AlertDescription>{msg.text}</AlertDescription>
          </Alert>
        )}
        {rows === null ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <ul className="space-y-3 text-sm" data-testid="sessions">
            {rows.map((s) => (
              <li key={s.handle} className="flex flex-wrap items-center gap-2" data-testid="session-row">
                <span className="font-medium">{s.device}</span>
                {s.current && <Badge tone="good">this device</Badge>}
                <span className="text-muted-foreground">
                  · {s.ip_address ?? "unknown IP"} · signed in {fmt(s.created_at)}
                  {s.last_activity_at ? ` · last active ${fmt(s.last_activity_at)}` : ""}
                </span>
                {!s.current && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="ml-auto"
                    onClick={() => {
                      setMsg(null);
                      setAsking(s.handle);
                    }}
                    aria-label={`Sign out ${s.device}`}
                  >
                    Sign out
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}

        {others > 0 && asking === null && (
          <Button
            variant="outline"
            size="sm"
            className="mt-4"
            onClick={() => {
              setMsg(null);
              setAsking("others");
            }}
          >
            Sign out all other sessions
          </Button>
        )}

        {asking !== null && (
          <form
            className="mt-4 flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void confirm();
            }}
            data-testid="session-reauth"
          >
            <label className="text-sm">
              <span className="mb-1 block text-muted-foreground">
                {asking === "others" ? "Confirm your password to sign out every other session" : "Confirm your password to sign out this session"}
              </span>
              <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
            </label>
            <Button type="submit" size="sm" disabled={busy || !password}>
              {busy ? "Signing out…" : "Sign out"}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={cancel}>
              Cancel
            </Button>
          </form>
        )}
        <p className="mt-3 text-xs text-muted-foreground">Don&apos;t recognise a device? Sign it out, then change your password.</p>
      </CardContent>
    </Card>
  );
}
