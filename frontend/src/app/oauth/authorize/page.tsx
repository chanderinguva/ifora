"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, ShieldCheck } from "lucide-react";
import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ApiError, http } from "@/lib/http";

type View = {
  client: { name: string; description: string | null; first_party: boolean };
  scopes: { name: string; description: string }[];
  user: { email: string };
  consent_required: boolean;
  redirect_host: string;
};

export default function AuthorizePage() {
  const router = useRouter();
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [rid, setRid] = useState("");

  const decide = useCallback(async (id: string, approve: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = await http<{ redirect_to: string }>(`/oidc/authorization-requests/${encodeURIComponent(id)}/decision`, { method: "POST", body: { approve } });
      window.location.assign(r.redirect_to);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("request_id") ?? "";
    setRid(id);
    if (!id) { setError("This page needs a sign-in request from an application."); return; }
    http<View>(`/oidc/authorization-requests/${encodeURIComponent(id)}`)
      .then((v) => {
        setView(v);
        if (!v.consent_required) decide(id, true); // trusted application, nothing to ask
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) {
          router.replace(`/login?next=${encodeURIComponent(`/oauth/authorize?request_id=${id}`)}`);
        } else setError(e instanceof Error ? e.message : "Something went wrong");
      });
  }, [decide, router]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md" data-testid="consent-card">
        <CardHeader className="space-y-3">
          <Logo />
          <CardTitle>{view ? `${view.client.name} wants access` : "Sign in"}</CardTitle>
          {view && <CardDescription>Signed in as {view.user.email}</CardDescription>}
        </CardHeader>
        <CardContent className="space-y-4">
          {error && <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription></Alert>}
          {!view && !error && <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</p>}
          {view?.consent_required && (
            <>
              {view.client.description && <p className="text-sm text-muted-foreground">{view.client.description}</p>}
              <div>
                <p className="mb-2 text-sm font-medium">This application will be able to:</p>
                <ul className="space-y-2" data-testid="consent-scopes">
                  {view.scopes.map((s) => (
                    <li key={s.name} className="flex items-start gap-2 text-sm"><ShieldCheck className="mt-0.5 h-4 w-4 text-muted-foreground" />{s.description}</li>
                  ))}
                </ul>
              </div>
              <p className="text-xs text-muted-foreground">You will be sent back to <code>{view.redirect_host}</code>. You can withdraw access later from your account settings.</p>
            </>
          )}
          {view && !view.consent_required && !error && <p className="text-sm text-muted-foreground">Continuing…</p>}
        </CardContent>
        {view?.consent_required && (
          <CardFooter className="gap-2">
            <Button disabled={busy} onClick={() => decide(rid, true)}>Allow</Button>
            <Button variant="outline" disabled={busy} onClick={() => decide(rid, false)}>Deny</Button>
          </CardFooter>
        )}
      </Card>
    </main>
  );
}
