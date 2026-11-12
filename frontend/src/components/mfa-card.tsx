"use client";

import { EnrolCodeField } from "@/components/enrol-code-field";
import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/bits";
import { http } from "@/lib/http";

type Status = { enabled: boolean; pending: boolean; recovery_codes_remaining: number };
type Mode = "idle" | "password" | "scan" | "disable" | "regen";

/** Self-service two-step verification: enrol, disable, regenerate recovery codes. */
export function MfaCard({ needsCode = false, emailCode = false }: { needsCode?: boolean; emailCode?: boolean }) {
  const [enrolCode, setEnrolCode] = useState("");
  const [status, setStatus] = useState<Status | null>(null);
  const [mode, setMode] = useState<Mode>("idle");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = () =>
    http<Status>("/me/mfa")
      .then((d) => { setStatus(d); window.dispatchEvent(new Event("factors-changed")); })
      .catch(() => {});
  useEffect(() => {
    load();
  }, []);

  const reset = () => {
    setMode("idle");
    setPassword("");
    setCode("");
    setSetup(null);
  };

  async function run(fn: () => Promise<void>) {
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    }
  }

  const startSetup = () =>
    run(async () => {
      setSetup(await http("/me/mfa/setup", { method: "POST", body: { password, enrollment_code: needsCode ? enrolCode : undefined } }));
      setPassword("");
      setMode("scan");
    });

  const enable = () =>
    run(async () => {
      const r = await http<{ recovery_codes: string[] }>("/me/mfa/enable", { method: "POST", body: { code } });
      setRecovery(r.recovery_codes);
      reset();
      load();
      setMsg({ ok: true, text: "Two-step verification is on. Other devices were signed out." });
    });

  const disable = () =>
    run(async () => {
      await http("/me/mfa/disable", { method: "POST", body: { password, code } });
      reset();
      load();
      setMsg({ ok: true, text: "Two-step verification is off." });
    });

  const regen = () =>
    run(async () => {
      const r = await http<{ recovery_codes: string[] }>("/me/mfa/recovery-codes", { method: "POST", body: { password, code } });
      setRecovery(r.recovery_codes);
      reset();
      load();
    });

  if (!status) return null;

  return (
    <Card className="mb-6" data-testid="mfa-card">
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>Two-step verification</CardTitle>
        <Badge tone={status.enabled ? "good" : "neutral"}>{status.enabled ? "On" : "Off"}</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        {msg && (
          <Alert variant={msg.ok ? "default" : "destructive"} role="status">
            <AlertDescription>{msg.text}</AlertDescription>
          </Alert>
        )}

        {recovery && (
          <Alert data-testid="recovery-codes">
            <AlertDescription>
              <p className="mb-2 font-medium">Save these recovery codes now. Each works once and they will not be shown again.</p>
              <ul className="grid grid-cols-2 gap-1 font-mono text-sm">
                {recovery.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
              <div className="mt-3 flex gap-2">
                <Button type="button" size="sm" variant="outline" onClick={() => navigator.clipboard?.writeText(recovery.join("\n"))}>
                  Copy
                </Button>
                <Button type="button" size="sm" onClick={() => setRecovery(null)}>
                  I have saved them
                </Button>
              </div>
            </AlertDescription>
          </Alert>
        )}

        {mode === "idle" && !status.enabled && (
          <>
            <p className="text-sm text-muted-foreground">
              Add a second step to sign-in using an authenticator app (Google Authenticator, 1Password, Authy…).
            </p>
            <Button onClick={() => setMode("password")}>Set up</Button>
          </>
        )}

        {mode === "idle" && status.enabled && (
          <>
            <p className="text-sm text-muted-foreground">{status.recovery_codes_remaining} recovery codes remaining.</p>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => setMode("regen")}>New recovery codes</Button>
              <Button variant="outline" onClick={() => setMode("disable")}>Turn off</Button>
            </div>
          </>
        )}

        {mode === "password" && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); startSetup(); }}>
            <Label htmlFor="mfa-pw">Confirm your password to continue</Label>
            <Input id="mfa-pw" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            {needsCode && (
              <EnrolCodeField id="mfa-enrol-code" value={enrolCode} onChange={setEnrolCode} canEmail={emailCode} />
            )}
            <div className="flex gap-2">
              <Button type="submit" disabled={!password}>Continue</Button>
              <Button type="button" variant="ghost" onClick={reset}>Cancel</Button>
            </div>
          </form>
        )}

        {mode === "scan" && setup && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); enable(); }}>
            <p className="text-sm">Scan this QR code with your authenticator app, then enter the 6-digit code it shows.</p>
            <div className="inline-block rounded bg-white p-3">
              <QRCodeSVG value={setup.otpauth_uri} size={168} />
            </div>
            <p className="text-xs text-muted-foreground">
              Can&apos;t scan? Enter this key manually: <code className="font-mono" data-testid="mfa-secret">{setup.secret}</code>
            </p>
            <Label htmlFor="mfa-enable-code">Code from the app</Label>
            <Input id="mfa-enable-code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
            <div className="flex gap-2">
              <Button type="submit" disabled={code.trim().length < 6}>Turn on</Button>
              <Button type="button" variant="ghost" onClick={reset}>Cancel</Button>
            </div>
          </form>
        )}

        {(mode === "disable" || mode === "regen") && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); mode === "disable" ? disable() : regen(); }}>
            <Label htmlFor="mfa-pw2">Password</Label>
            <Input id="mfa-pw2" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <Label htmlFor="mfa-code2">Authenticator or recovery code</Label>
            <Input id="mfa-code2" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
            <div className="flex gap-2">
              <Button type="submit" variant={mode === "disable" ? "destructive" : "default"} disabled={!password || !code}>
                {mode === "disable" ? "Turn off" : "Generate new codes"}
              </Button>
              <Button type="button" variant="ghost" onClick={reset}>Cancel</Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
