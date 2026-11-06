"use client";

import { useEffect, useState } from "react";
import { browserSupportsWebAuthn, startRegistration } from "@simplewebauthn/browser";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, fmt } from "@/components/bits";
import { http } from "@/lib/http";

type Passkey = { id: number; name: string; device_type: string; backed_up: boolean; created_at: string; last_used_at: string | null };
type Data = { items: Passkey[]; require_passkey: boolean; min_for_policy: number };
type Mode = "idle" | "add" | "remove" | "policy";

function friendly(e: unknown): string {
  const name = (e as { name?: string })?.name;
  if (name === "NotAllowedError") return "The passkey prompt was cancelled or timed out.";
  if (name === "InvalidStateError") return "This authenticator is already registered.";
  return e instanceof Error ? e.message : "Something went wrong";
}

/** Passkeys (WebAuthn): phishing-resistant sign-in. Manage, add, remove, and require them. */
export function PasskeyCard() {
  const [data, setData] = useState<Data | null>(null);
  const [supported, setSupported] = useState(true);
  const [mode, setMode] = useState<Mode>("idle");
  const [target, setTarget] = useState<Passkey | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = () =>
    http<Data>("/me/passkeys")
      .then((d) => { setData(d); window.dispatchEvent(new Event("factors-changed")); })
      .catch(() => {});
  useEffect(() => {
    setSupported(browserSupportsWebAuthn());
    load();
  }, []);

  const reset = () => {
    setMode("idle");
    setTarget(null);
    setName("");
    setPassword("");
  };

  async function run(fn: () => Promise<void>) {
    setMsg(null);
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setMsg({ ok: false, text: friendly(e) });
    } finally {
      setBusy(false);
    }
  }

  const add = () =>
    run(async () => {
      const { ceremony_id, options } = await http<{ ceremony_id: string; options: any }>("/me/passkeys/register/options", {
        method: "POST",
        body: { password },
      });
      const credential = await startRegistration(options);
      await http("/me/passkeys/register/verify", {
        method: "POST",
        body: { ceremony_id, credential, name: name.trim() || "Passkey" },
      });
      reset();
      await load();
      setMsg({ ok: true, text: "Passkey added." });
    });

  const remove = () =>
    run(async () => {
      await http(`/me/passkeys/${target!.id}/remove`, { method: "POST", body: { password } });
      reset();
      await load();
      setMsg({ ok: true, text: "Passkey removed." });
    });

  const setPolicy = (require: boolean) =>
    run(async () => {
      await http("/me/passkeys/policy", { method: "POST", body: { password, require } });
      reset();
      await load();
      setMsg({
        ok: true,
        text: require ? "Passkey required. Passwords can no longer sign in to this account; other devices were signed out." : "Passwords can sign in again.",
      });
    });

  async function rename(p: Passkey) {
    const next = window.prompt("Rename passkey", p.name);
    if (!next || next.trim() === p.name) return;
    await run(async () => {
      await http(`/me/passkeys/${p.id}`, { method: "PATCH", body: { name: next.trim() } });
      await load();
    });
  }

  if (!data) return null;
  const count = data.items.length;

  return (
    <Card className="mb-6" data-testid="passkey-card">
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>Passkeys</CardTitle>
        <Badge tone={data.require_passkey ? "good" : count ? "info" : "neutral"}>
          {data.require_passkey ? "Required" : `${count} registered`}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Passkeys sign you in with Touch ID, Windows Hello, your phone or a security key. They cannot be phished: the browser only releases one to the real site.
        </p>

        {!supported && (
          <Alert variant="warning"><AlertDescription>This browser does not support passkeys.</AlertDescription></Alert>
        )}
        {msg && (
          <Alert variant={msg.ok ? "default" : "destructive"} role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>
        )}

        {count > 0 && (
          <ul className="divide-y rounded-md border" data-testid="passkey-list">
            {data.items.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                <div>
                  <div className="font-medium">{p.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {p.device_type === "multi_device" ? "Synced passkey" : "Device-bound"} · added {fmt(p.created_at)} · last used {fmt(p.last_used_at)}
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="ghost" onClick={() => rename(p)}>Rename</Button>
                  <Button size="sm" variant="outline" onClick={() => { setTarget(p); setMode("remove"); }}>Remove</Button>
                </div>
              </li>
            ))}
          </ul>
        )}

        {mode === "idle" && (
          <div className="flex flex-wrap gap-2">
            <Button disabled={!supported} onClick={() => setMode("add")}>Add a passkey</Button>
            {count >= data.min_for_policy && !data.require_passkey && (
              <Button variant="outline" onClick={() => setMode("policy")}>Require a passkey to sign in</Button>
            )}
            {data.require_passkey && (
              <Button variant="outline" onClick={() => setMode("policy")}>Allow passwords again</Button>
            )}
          </div>
        )}
        {mode === "idle" && count > 0 && count < data.min_for_policy && !data.require_passkey && (
          <p className="text-xs text-muted-foreground">
            Register at least {data.min_for_policy} passkeys to be able to require them (so losing one device cannot lock you out).
          </p>
        )}

        {mode === "add" && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); add(); }}>
            <Label htmlFor="pk-name">Name this passkey</Label>
            <Input id="pk-name" placeholder="e.g. MacBook Touch ID" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
            <Label htmlFor="pk-pw">Confirm your password</Label>
            <Input id="pk-pw" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <div className="flex gap-2">
              <Button type="submit" disabled={!password || busy}>Continue</Button>
              <Button type="button" variant="ghost" onClick={reset}>Cancel</Button>
            </div>
          </form>
        )}

        {mode === "remove" && target && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); remove(); }}>
            <Label htmlFor="pk-pw2">Confirm your password to remove “{target.name}”</Label>
            <Input id="pk-pw2" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <div className="flex gap-2">
              <Button type="submit" variant="destructive" disabled={!password || busy}>Remove passkey</Button>
              <Button type="button" variant="ghost" onClick={reset}>Cancel</Button>
            </div>
          </form>
        )}

        {mode === "policy" && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); setPolicy(!data.require_passkey); }}>
            <p className="text-sm">
              {data.require_passkey
                ? "Passwords will be able to sign in again."
                : "Passwords (even with an authenticator code) will no longer sign in to this account. If you lose all your passkeys, an administrator must reset your account."}
            </p>
            <Label htmlFor="pk-pw3">Confirm your password</Label>
            <Input id="pk-pw3" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <div className="flex gap-2">
              <Button type="submit" disabled={!password || busy}>{data.require_passkey ? "Allow passwords" : "Require passkey"}</Button>
              <Button type="button" variant="ghost" onClick={reset}>Cancel</Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
