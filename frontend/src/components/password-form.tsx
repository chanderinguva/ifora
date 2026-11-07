"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Logo } from "@/components/logo";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { API_URL } from "@/lib/api";

async function post(path: string, body: unknown): Promise<{ ok: boolean; data: any }> {
  const r = await fetch(`${API_URL}/api/v1${path}`, {
    method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  let data: any = {};
  try { data = await r.json(); } catch { /* empty body */ }
  if (!r.ok) {
    const d = data?.detail;
    data = { detail: typeof d === "string" ? d : Array.isArray(d) ? d.map((x: any) => x.msg).join(". ") : "Something went wrong" };
  }
  return { ok: r.ok, data };
}

function Shell({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted px-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <Logo size="lg" className="mb-4" />
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">{children}</CardContent>
      </Card>
    </div>
  );
}

/** Ask for a reset email. The answer is the same whether or not the address has an account. */
export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Shell title="Forgot your password?" description="Enter your email address and we will send you a link to choose a new one.">
      {done ? (
        <Alert role="status"><AlertDescription>If an account exists for that address, an email with instructions is on its way. The link expires in 30 minutes.</AlertDescription></Alert>
      ) : (
        <form className="space-y-4" onSubmit={async (e) => {
          e.preventDefault(); setBusy(true); setError(null);
          const r = await post("/auth/forgot-password", { email });
          setBusy(false);
          if (r.ok) setDone(true); else setError(r.data.detail);
        }}>
          {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
          <div className="space-y-2">
            <Label htmlFor="fp-email">Email</Label>
            <Input id="fp-email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <Button type="submit" className="w-full" disabled={busy || !email}>Send reset link</Button>
        </form>
      )}
      <Link href="/login" className="block text-center text-sm underline-offset-4 hover:underline">Back to sign in</Link>
    </Shell>
  );
}

/** Set a password from an emailed link (reset or invitation). The token lives in the URL fragment. */
export function SetPasswordForm({ invite }: { invite: boolean }) {
  const [token, setToken] = useState<string | null>(null);
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const t = new URLSearchParams(window.location.hash.slice(1)).get("token");
    setToken(t ?? "");
    if (t) history.replaceState(null, "", window.location.pathname); // keep the token out of history and screenshots
  }, []);
  const title = invite ? "Welcome to IdentityForge" : "Choose a new password";
  const desc = invite ? "Set a password to activate your account." : "Pick a new password for your account.";
  if (token === null) return <Shell title={title} description={desc}><p className="text-sm text-muted-foreground">Loading…</p></Shell>;
  return (
    <Shell title={title} description={desc}>
      {done ? (
        <>
          <Alert role="status"><AlertDescription>Password set. You can sign in now.</AlertDescription></Alert>
          <Link href="/login"><Button className="w-full">Go to sign in</Button></Link>
        </>
      ) : !token ? (
        <Alert variant="destructive"><AlertDescription>This link is incomplete. Open it again from your email, or request a new one.</AlertDescription></Alert>
      ) : (
        <form className="space-y-4" onSubmit={async (e) => {
          e.preventDefault();
          if (pw !== pw2) { setError("The passwords do not match"); return; }
          setBusy(true); setError(null);
          const r = await post("/auth/reset-password", { token, new_password: pw });
          setBusy(false);
          if (r.ok) setDone(true); else setError(r.data.detail);
        }}>
          {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
          <div className="space-y-2">
            <Label htmlFor="np">New password</Label>
            <Input id="np" type="password" autoComplete="new-password" required value={pw} onChange={(e) => setPw(e.target.value)} />
            <p className="text-xs text-muted-foreground">At least 12 characters, mixing upper and lower case, with a digit.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="np2">Repeat password</Label>
            <Input id="np2" type="password" autoComplete="new-password" required value={pw2} onChange={(e) => setPw2(e.target.value)} />
          </div>
          <Button type="submit" className="w-full" disabled={busy || !pw}>{invite ? "Activate account" : "Set password"}</Button>
        </form>
      )}
      {!done && <Link href="/forgot-password" className="block text-center text-sm underline-offset-4 hover:underline">Request a new link</Link>}
    </Shell>
  );
}

/** Shown after sign-in when an administrator required a password change (status password_expired). */
export function ExpiredPasswordForm({ email, current, onDone }: { email: string; current: string; onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <form className="space-y-4" data-testid="expired-form" onSubmit={async (e) => {
      e.preventDefault();
      if (pw !== pw2) { setError("The passwords do not match"); return; }
      setBusy(true); setError(null);
      const r = await post("/auth/change-expired-password", { email, current_password: current, new_password: pw });
      setBusy(false);
      if (r.ok) onDone(); else setError(r.data.detail);
    }}>
      <Alert><AlertDescription>You must choose a new password before continuing.</AlertDescription></Alert>
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <div className="space-y-2"><Label htmlFor="xp">New password</Label><Input id="xp" type="password" autoComplete="new-password" required value={pw} onChange={(e) => setPw(e.target.value)} /></div>
      <div className="space-y-2"><Label htmlFor="xp2">Repeat password</Label><Input id="xp2" type="password" autoComplete="new-password" required value={pw2} onChange={(e) => setPw2(e.target.value)} /></div>
      <Button type="submit" className="w-full" disabled={busy || !pw}>Change password</Button>
    </form>
  );
}
