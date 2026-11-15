"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { fieldClass } from "@/components/bits";
import { http, qs } from "@/lib/http";

export type DraftPolicy = { require_mfa: boolean; reauth_minutes: number | null; allowed_zone_ids: number[]; blocked_zone_ids: number[] };
type Verdict = { decision: "allow" | "deny" | "reauth"; reason: string; rule: string; explanation: string };
type Result = { user: { id: number; email: string }; stored: Verdict; draft: Verdict | null; changed: boolean };

const SIGN_INS = [
  ["Password only", ["pwd"]],
  ["Password and authenticator code", ["pwd", "otp", "mfa"]],
  ["Passkey", ["hwk", "user", "mfa"]],
] as const;
const LABEL: Record<string, string> = { allow: "Allowed", deny: "Denied", reauth: "Asks the user to sign in again" };

function Verdict({ title, v }: { title: string; v: Verdict }) {
  return (
    <div className="space-y-1" data-testid="sim-verdict">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</p>
      <p className="font-medium" data-decision={v.decision}>{LABEL[v.decision] ?? v.decision}</p>
      <p className="text-muted-foreground">{v.explanation}</p>
      {v.decision !== "allow" && v.reason && v.reason !== "mfa" && v.reason !== "stale" && <p className="text-xs">The user would see: &ldquo;{v.reason}&rdquo;</p>}
    </div>
  );
}

/** "Test this policy": runs the real policy engine for a hypothetical sign-in. Saves nothing and writes no log entries. */
export function PolicySimulator({ appId, draft, dirty }: { appId: number; draft: DraftPolicy; dirty: boolean }) {
  const [email, setEmail] = useState("");
  const [ip, setIp] = useState("");
  const [method, setMethod] = useState(0);
  const [age, setAge] = useState("0");
  const [useDraft, setUseDraft] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<Result | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setRes(null);
    try {
      const found = await http<{ Resources: { id: number; email: string }[] }>(`/admin/users${qs({ filter: `email eq "${email.trim().replace(/"/g, "")}"`, count: 1 })}`);
      const u = found.Resources[0];
      if (!u) throw new Error("No user with that email address");
      const body: Record<string, unknown> = { user_id: u.id, source_ip: ip.trim(), amr: SIGN_INS[method][1], session_age_minutes: Number(age) || 0 };
      if (useDraft && dirty) body.policy = draft;
      setRes(await http<Result>(`/admin/applications/${appId}/policy/simulate`, { method: "POST", body }));
    } catch (x) {
      setErr(x instanceof Error ? x.message : "The test failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="sim-title" className="space-y-3 border-t pt-4" data-testid="policy-simulator">
      <h3 id="sim-title" className="font-medium">Test this policy</h3>
      <p className="text-muted-foreground">See what would happen to a sign-in before you save. Nothing is changed and nothing is logged.</p>
      <form onSubmit={run} className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1"><label htmlFor="sim-email" className="font-medium">User&apos;s email</label>
          <input id="sim-email" type="email" className={fieldClass} value={email} onChange={(e) => setEmail(e.target.value)} required /></div>
        <div className="space-y-1"><label htmlFor="sim-ip" className="font-medium">Sign-in from IP address</label>
          <input id="sim-ip" className={fieldClass} value={ip} onChange={(e) => setIp(e.target.value)} placeholder="203.0.113.9" required /></div>
        <div className="space-y-1"><label htmlFor="sim-method" className="font-medium">Signed in with</label>
          <select id="sim-method" className={fieldClass} value={method} onChange={(e) => setMethod(Number(e.target.value))}>{SIGN_INS.map(([l], i) => <option key={l} value={i}>{l}</option>)}</select></div>
        <div className="space-y-1"><label htmlFor="sim-age" className="font-medium">Signed in how many minutes ago</label>
          <input id="sim-age" type="number" min={0} max={10080} className={fieldClass} value={age} onChange={(e) => setAge(e.target.value)} /></div>
        {dirty && <label className="flex items-center gap-2 sm:col-span-2"><input type="checkbox" checked={useDraft} onChange={(e) => setUseDraft(e.target.checked)} data-testid="sim-draft" /> Test my unsaved changes (compare with the saved policy)</label>}
        <div className="sm:col-span-2"><Button type="submit" variant="outline" disabled={busy} data-testid="sim-run">{busy ? "Testing…" : "Run test"}</Button></div>
      </form>
      <div aria-live="polite" className="space-y-3">
        {err && <Alert variant="destructive" role="alert"><AlertDescription>{err}</AlertDescription></Alert>}
        {res && (
          <div className="grid gap-4 rounded-md border p-3 sm:grid-cols-2" data-testid="sim-result">
            <Verdict title={res.draft ? "Saved policy" : `For ${res.user.email}`} v={res.stored} />
            {res.draft && <Verdict title="With your changes" v={res.draft} />}
            {res.draft && <p className="sm:col-span-2" data-testid="sim-changed">{res.changed ? "Saving these changes would change the outcome of this sign-in." : "Saving these changes would not change the outcome of this sign-in."}</p>}
          </div>
        )}
      </div>
    </section>
  );
}
