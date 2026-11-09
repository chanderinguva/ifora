"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Logo } from "@/components/logo";
import { ApiError, http } from "@/lib/http";
import { logout } from "@/lib/auth-client";

// The link carries only a code; the wording is ours, so a crafted link cannot put its own message on this page.
const SAML_ERRORS: Record<string, string> = {
  invalid_request: "The application's sign-in request was not valid. Go back to the application and try again.",
  unknown_sp: "This application is not registered here. Contact your administrator.",
  unavailable: "This application is not available right now.",
  acs: "The application's sign-in request does not match how it is registered. Contact your administrator.",
  signature: "The application's sign-in request could not be verified. Contact your administrator.",
};

type Out = { acs_url: string; saml_response: string; relay_state: string | null };

/** Finishes a SAML sign-in: signs the user in if needed, asks the server for the signed response and posts it to the application. */
export default function SamlContinue() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState<string | null>(null);

  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    const rid = sp.get("request_id");
    const app = sp.get("app");
    if (sp.get("error")) { setError(SAML_ERRORS[sp.get("error")!] ?? SAML_ERRORS.invalid_request); return; }
    if (!rid && !app) { setError("This page needs a sign-in request from an application."); return; }
    const back = `/saml/continue?${rid ? `request_id=${encodeURIComponent(rid)}` : `app=${encodeURIComponent(app!)}`}`;
    const toLogin = () => router.replace(`/login?next=${encodeURIComponent(back)}`);

    (async () => {
      try {
        if (rid) {
          const v = await http<{ application: string; reauth_required: boolean }>(`/saml/requests/${encodeURIComponent(rid)}`);
          if (v.reauth_required) { await logout().catch(() => {}); toLogin(); return; }
          setName(v.application);
        }
        const out = await http<Out>(rid ? `/saml/requests/${encodeURIComponent(rid)}/respond` : `/saml/apps/${encodeURIComponent(app!)}/respond`, { method: "POST" });
        const form = document.createElement("form");
        form.method = "POST";
        form.action = out.acs_url;
        for (const [k, v] of [["SAMLResponse", out.saml_response], ["RelayState", out.relay_state ?? ""]] as const) {
          if (k === "RelayState" && !v) continue;
          const i = document.createElement("input");
          i.type = "hidden"; i.name = k; i.value = v;
          form.appendChild(i);
        }
        document.body.appendChild(form);
        form.submit();
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) { toLogin(); return; }
        if (e instanceof ApiError && e.status === 403 && e.message === "reauthentication_required") { await logout().catch(() => {}); toLogin(); return; }
        setError(e instanceof Error ? e.message : "Something went wrong");
      }
    })();
  }, [router]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md" data-testid="saml-continue">
        <CardHeader className="space-y-3">
          <Logo />
          <CardTitle>{error ? "Could not sign you in" : name ? `Signing you in to ${name}…` : "Signing you in…"}</CardTitle>
          {!error && <CardDescription>You will be sent to the application in a moment.</CardDescription>}
        </CardHeader>
        {error && <CardContent><p role="alert" className="text-sm text-destructive" data-testid="saml-error">{error}</p></CardContent>}
      </Card>
    </main>
  );
}
