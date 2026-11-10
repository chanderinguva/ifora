"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Logo } from "@/components/logo";
import { ApiError, http } from "@/lib/http";
import { logout } from "@/lib/auth-client";

type Status = { name: string; username_source: string; has_credential: boolean; username: string | null; login_host: string; vault_enabled: boolean };
type Out = { login_url: string; fields: { name: string; value: string }[] };

/** Signs the user in to a legacy application: asks once for their account there, then posts it (never in a URL) to the login page. */
export default function SwaContinue() {
  const router = useRouter();
  const [app, setApp] = useState<string | null>(null);
  const [manage, setManage] = useState(false);
  const [st, setSt] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const started = useRef(false); // dev StrictMode runs effects twice: never post a credential twice

  const toLogin = useCallback((back: string) => router.replace(`/login?next=${encodeURIComponent(back)}`), [router]);

  const launch = useCallback(async (id: string) => {
    const back = `/swa/continue?app=${encodeURIComponent(id)}`;
    try {
      const out = await http<Out>(`/swa/apps/${encodeURIComponent(id)}/launch`, { method: "POST" });
      const form = document.createElement("form");
      form.method = "POST";
      form.action = out.login_url;
      for (const f of out.fields) {
        const i = document.createElement("input");
        i.type = "hidden"; i.name = f.name; i.value = f.value;
        form.appendChild(i);
      }
      document.body.appendChild(form);
      form.submit();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { toLogin(back); return; }
      if (e instanceof ApiError && e.status === 403 && e.message === "reauthentication_required") { await logout().catch(() => {}); toLogin(back); return; }
      if (e instanceof ApiError && e.status === 409) { setManage(true); setSt((s) => (s ? { ...s, has_credential: false } : s)); return; }
      setError(e instanceof Error ? e.message : "Something went wrong");
    }
  }, [toLogin]);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const sp = new URLSearchParams(window.location.search);
    const id = sp.get("app");
    if (!id) { setError("This page needs an application."); return; }
    setApp(id);
    const m = sp.get("manage") === "1";
    (async () => {
      try {
        const s = await http<Status>(`/swa/apps/${encodeURIComponent(id)}`);
        setSt(s);
        setUsername(s.username ?? "");
        if (m || !s.has_credential) { setManage(true); return; }
        await launch(id);
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) { toLogin(`/swa/continue?app=${encodeURIComponent(id)}${m ? "&manage=1" : ""}`); return; }
        setError(e instanceof ApiError && e.status === 404 ? "This application is not available to you." : e instanceof Error ? e.message : "Something went wrong");
      }
    })();
  }, [launch, toLogin]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!app) return;
    setBusy(true); setError(null);
    try {
      await http(`/swa/apps/${encodeURIComponent(app)}/credential`, { method: "PUT", body: { username: st?.username_source === "user" ? username : null, password } });
      setPassword("");
      await launch(app);
    } catch (e2) { setError(e2 instanceof Error ? e2.message : "Could not save"); } finally { setBusy(false); }
  }

  async function forget() {
    if (!app || !confirm("Remove your saved sign-in for this application?")) return;
    try { await http(`/swa/apps/${encodeURIComponent(app)}/credential`, { method: "DELETE" }); router.replace("/apps"); } catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md" data-testid="swa-continue">
        <CardHeader className="space-y-3">
          <Logo />
          <CardTitle>{manage && st ? (st.has_credential ? `Change your sign-in for ${st.name}` : `Connect your ${st.name} account`) : st ? `Signing you in to ${st.name}…` : "Signing you in…"}</CardTitle>
          {manage && st && (
            <CardDescription>
              Enter the account you use at <strong>{st.login_host}</strong>. Ifora stores the password encrypted and sends it only to that site's sign-in page when you open this app.
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {error && <p role="alert" className="text-sm text-destructive" data-testid="swa-error">{error}</p>}
          {manage && st && !st.vault_enabled && <p role="alert" className="text-sm text-destructive">Saving passwords is not enabled on this server. Ask an administrator.</p>}
          {manage && st && st.vault_enabled && (
            <form onSubmit={save} className="space-y-3">
              {st.username_source === "user" && (
                <div className="space-y-1"><Label htmlFor="swa-user">Username at {st.login_host}</Label>
                  <Input id="swa-user" autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} required maxLength={255} /></div>
              )}
              <div className="space-y-1"><Label htmlFor="swa-pass">Password at {st.login_host}</Label>
                <Input id="swa-pass" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required maxLength={256} />
                <p className="text-xs text-muted-foreground">Use the application's own password, not your Ifora password.</p></div>
              <div className="flex gap-2">
                <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save and sign in"}</Button>
                {st.has_credential && <Button type="button" variant="outline" onClick={forget}>Remove saved sign-in</Button>}
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
