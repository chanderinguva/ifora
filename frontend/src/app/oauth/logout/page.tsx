"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { API_URL } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth-client";
import { http } from "@/lib/http";

type Info = { client_name: string | null; will_redirect: boolean; signed_in_as: string | null };
const KEYS = ["id_token_hint", "post_logout_redirect_uri", "state", "client_id"];

/** RP-initiated logout confirmation. The user always confirms here, so another site cannot sign them out silently. */
export default function LogoutPage() {
  const router = useRouter();
  const [info, setInfo] = useState<Info | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [params, setParams] = useState<Record<string, string>>({});

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const p: Record<string, string> = {};
    KEYS.forEach((k) => { const v = q.get(k); if (v) p[k] = v; });
    setParams(p);
    http<Info>(`/oidc/logout-request?${new URLSearchParams(p)}`).then(setInfo).catch((e) => setError(e instanceof Error ? e.message : "Something went wrong"));
  }, []);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const signedIn = !!(await getCurrentUser());
      const out = signedIn
        ? await http<{ redirect_to: string | null }>("/oidc/logout", { method: "POST", body: params })
        : await (await fetch(`${API_URL}/api/v1/oidc/logout`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params) })).json();
      if (out.redirect_to) window.location.assign(out.redirect_to);
      else router.replace("/login");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md" data-testid="logout-card">
        <CardHeader className="space-y-3">
          <Logo />
          <CardTitle>Sign out?</CardTitle>
          <CardDescription>
            {info?.client_name ? `${info.client_name} asked to sign you out of IdentityForge.` : "Sign out of IdentityForge."}
            {info?.signed_in_as ? ` You are signed in as ${info.signed_in_as}.` : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error && <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription></Alert>}
          {!info && !error && <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</p>}
        </CardContent>
        {info && (
          <CardFooter className="gap-2">
            <Button disabled={busy} onClick={confirm}>Sign out</Button>
            <Button variant="outline" disabled={busy} onClick={() => router.replace("/")}>Stay signed in</Button>
          </CardFooter>
        )}
      </Card>
    </main>
  );
}
