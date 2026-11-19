"use client";

import { useEffect, useRef, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchPending, loadDevice, respond, type DeviceCreds, type PendingRequest } from "@/lib/push-device";

/** Opened from the push notification on a registered browser. No sign-in is needed here: the browser proves itself with its own device secret. */
export default function ApprovePage() {
  const [creds, setCreds] = useState<DeviceCreds | null | undefined>(undefined);
  const [req, setReq] = useState<PendingRequest | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const answered = useRef(false);

  useEffect(() => {
    setCreds(loadDevice());
  }, []);

  useEffect(() => {
    if (!creds) return;
    let stopped = false;
    const poll = async () => {
      try {
        const p = await fetchPending(creds);
        if (!stopped && !answered.current) setReq(p);
      } catch (e) {
        if (!stopped) setError(e instanceof Error ? e.message : "Could not check for requests");
      }
    };
    poll();
    const t = setInterval(poll, 3000);
    return () => {
      stopped = true;
      clearInterval(t);
    };
  }, [creds]);

  const answer = async (number: string | null) => {
    if (!creds || !req) return;
    setBusy(true);
    setError(null);
    try {
      const result = await respond(creds, req.challenge_id, number);
      answered.current = true;
      setReq(null);
      setDone(result === "approved" ? "Approved. You can go back to the sign-in screen." : "Declined. The sign-in was stopped.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send your answer");
      setReq(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center justify-center p-4">
      <Card className="w-full" data-testid="approve-card">
        <CardHeader>
          <CardTitle>Approve sign-in</CardTitle>
          <CardDescription>Only approve if you started this sign-in and the number matches the one on its screen.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
          {creds === null && <p className="text-sm text-muted-foreground" data-testid="not-registered">This browser is not registered for push approval. Sign in and register it under Account settings.</p>}
          {done && <p role="status" className="text-sm" data-testid="approve-done">{done}</p>}
          {creds && !req && !done && <p className="text-sm text-muted-foreground" role="status">No sign-in is waiting for you right now.</p>}
          {req && (
            <div className="space-y-3" data-testid="approve-request">
              <p className="text-sm">A sign-in to your account was requested{req.requested_from ? <> from <span className="font-mono">{req.requested_from}</span></> : null}. Tap the number shown on the sign-in screen:</p>
              <div className="grid grid-cols-3 gap-2">
                {req.choices.map((n) => (
                  <Button key={n} type="button" size="lg" className="h-16 text-2xl tabular-nums" disabled={busy} onClick={() => answer(n)} data-testid={`choice-${n}`}>
                    {n}
                  </Button>
                ))}
              </div>
              <Button type="button" variant="outline" className="w-full" disabled={busy} onClick={() => answer(null)} data-testid="not-me">
                This wasn&apos;t me
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
