"use client";

import { useEffect, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/bits";
import { http } from "@/lib/http";

type Status = { allowed: boolean; mail_configured: boolean; enabled: boolean; pending: boolean; required: boolean; address: string };
type Mode = "idle" | "password" | "code" | "disable";

/** Email verification codes as a sign-in factor: turn on (password, then a code mailed to this account), turn off. Hidden when the organisation has it off. */
export function EmailOtpCard() {
  const [s, setS] = useState<Status | null>(null);
  const [mode, setMode] = useState<Mode>("idle");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => http<Status>("/me/mfa/email").then(setS).catch(() => {});
  useEffect(() => { load(); }, []);
  const reset = () => { setMode("idle"); setPassword(""); setCode(""); };

  async function run(fn: () => Promise<void>, fail: string) {
    setMsg(null); setBusy(true);
    try { await fn(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : fail }); } finally { setBusy(false); }
  }
  const start = () => run(async () => {
    await http("/me/mfa/email/setup", { method: "POST", body: { password } });
    setPassword(""); setMode("code"); setMsg({ ok: true, text: `We sent a 6-digit code to ${s?.address}. It expires in 5 minutes.` });
  }, "Could not send the code");
  const confirm = () => run(async () => {
    await http("/me/mfa/email/enable", { method: "POST", body: { code } });
    reset(); await load(); setMsg({ ok: true, text: "Email codes are on. Other devices were signed out." });
  }, "That code did not work");
  const turnOff = () => run(async () => {
    await http("/me/mfa/email/disable", { method: "POST", body: { password } });
    reset(); await load(); setMsg({ ok: true, text: "Email codes are off." });
  }, "Could not turn it off");

  if (!s || (!s.allowed && !s.enabled)) return null;
  return (
    <Card className="mt-6" data-testid="email-otp-card">
      <CardHeader><CardTitle className="flex items-center gap-2">Email verification codes {s.enabled ? <Badge tone="good">On</Badge> : <Badge tone="neutral">Off</Badge>}{s.required && <Badge tone="info">Required</Badge>}</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">After your password, we email a 6-digit code to {s.address}. It works once and expires in 5 minutes. Anyone who can read your email can use it, so keep an authenticator app or passkey too if you can.</p>
        {msg && <Alert variant={msg.ok ? "default" : "destructive"} role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
        {!s.mail_configured && !s.enabled && <p className="text-destructive">This server cannot send email yet, so email codes cannot be turned on.</p>}
        {mode === "idle" && !s.enabled && s.allowed && s.mail_configured && <Button size="sm" data-testid="email-otp-start" onClick={() => setMode("password")}>Turn on</Button>}
        {mode === "idle" && s.enabled && <Button size="sm" variant="outline" data-testid="email-otp-off" onClick={() => setMode("disable")}>Turn off</Button>}
        {(mode === "password" || mode === "disable") && (
          <form className="max-w-xs space-y-2" onSubmit={(e) => { e.preventDefault(); void (mode === "password" ? start() : turnOff()); }}>
            <Label htmlFor="eo-pw">Confirm your password</Label>
            <Input id="eo-pw" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <div className="flex gap-2"><Button size="sm" type="submit" disabled={busy || !password}>{mode === "password" ? "Send me a code" : "Turn off"}</Button><Button size="sm" type="button" variant="ghost" onClick={reset}>Cancel</Button></div>
          </form>
        )}
        {mode === "code" && (
          <form className="max-w-xs space-y-2" onSubmit={(e) => { e.preventDefault(); void confirm(); }}>
            <Label htmlFor="eo-code">Code from your email</Label>
            <Input id="eo-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
            <div className="flex gap-2"><Button size="sm" type="submit" disabled={busy || code.length !== 6} data-testid="email-otp-confirm">Confirm</Button><Button size="sm" type="button" variant="ghost" onClick={reset}>Cancel</Button></div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
