/** First visit after an invitation sign-in: choose a password, then (optionally) add a passkey. */

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { browserSupportsWebAuthn, startRegistration } from "@simplewebauthn/browser";
import { KeyRound } from "lucide-react";
import { Logo } from "@/components/logo";
import { PasswordRules } from "@/components/password-rules";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getCurrentUser } from "@/lib/auth-client";
import { http } from "@/lib/http";

type Step = "loading" | "password" | "passkey";

function friendly(e: unknown): string {
  const name = (e as { name?: string })?.name;
  if (name === "NotAllowedError") return "The passkey prompt was cancelled or timed out.";
  if (name === "InvalidStateError") return "This device already has a passkey for this account.";
  return e instanceof Error ? e.message : "Something went wrong";
}

export default function WelcomePage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("loading");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [canPasskey, setCanPasskey] = useState(true);

  useEffect(() => {
    setCanPasskey(browserSupportsWebAuthn());
    getCurrentUser().then((u) => {
      if (!u) { router.replace("/login"); return; }
      setEmail(u.email ?? "");
      setStep("password");
    });
  }, [router]);

  const done = () => router.push("/dashboard");

  async function savePassword(e: React.FormEvent) {
    e.preventDefault();
    if (pw !== pw2) { setError("The passwords do not match"); return; }
    setBusy(true); setError(null);
    try {
      await http("/me/password/initial", { method: "POST", body: { new_password: pw } });
      if (canPasskey) setStep("passkey"); else done();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not set the password");
    } finally {
      setBusy(false);
    }
  }

  async function addPasskey() {
    setBusy(true); setError(null);
    try {
      // The passkey endpoints ask for the password again; we still have it from the previous step.
      const { ceremony_id, options } = await http<{ ceremony_id: string; options: any }>("/me/passkeys/register/options", {
        method: "POST", body: { password: pw },
      });
      const credential = await startRegistration(options);
      await http("/me/passkeys/register/verify", { method: "POST", body: { ceremony_id, credential, name: "This device" } });
      done();
    } catch (err) {
      setError(friendly(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted px-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <Logo size="lg" className="mb-4" />
          {step === "passkey" ? (
            <>
              <CardTitle>Add a passkey</CardTitle>
              <CardDescription>Sign in next time with your fingerprint, face or device PIN. No password to type.</CardDescription>
            </>
          ) : (
            <>
              <CardTitle>Welcome to Ifora</CardTitle>
              <CardDescription>
                {email ? <>You are signed in as <span className="font-medium text-foreground">{email}</span>. </> : null}
                Choose a password for this account.
              </CardDescription>
            </>
          )}
        </CardHeader>
        <CardContent className="space-y-4">
          {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}

          {step === "loading" && <p className="text-sm text-muted-foreground">Loading…</p>}

          {step === "password" && (
            <form className="space-y-4" onSubmit={savePassword}>
              <div className="space-y-2">
                <Label htmlFor="welcome-pw">New password</Label>
                <Input id="welcome-pw" type="password" autoComplete="new-password" required value={pw}
                  onChange={(e) => setPw(e.target.value)} disabled={busy} />
                <PasswordRules />
              </div>
              <div className="space-y-2">
                <Label htmlFor="welcome-pw2">Repeat password</Label>
                <Input id="welcome-pw2" type="password" autoComplete="new-password" required value={pw2}
                  onChange={(e) => setPw2(e.target.value)} disabled={busy} />
              </div>
              <Button type="submit" className="w-full" disabled={busy || !pw}>Continue</Button>
            </form>
          )}

          {step === "passkey" && (
            <div className="space-y-3">
              <Button type="button" className="w-full" onClick={addPasskey} disabled={busy}>
                <KeyRound className="mr-2 h-4 w-4" /> Add a passkey
              </Button>
              <button type="button" className="w-full text-sm underline-offset-4 hover:underline" onClick={done} disabled={busy}>
                Skip for now
              </button>
              <p className="text-xs text-muted-foreground">You can add or remove passkeys later in Settings.</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
