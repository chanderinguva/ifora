"use client";

import { useEffect, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/bits";
import { http } from "@/lib/http";
import { forgetDevice, loadDevice, pushSupported, saveDevice, subscribe } from "@/lib/push-device";

type Device = { id: number; name: string; created_at: string | null; last_used_at: string | null };
type Status = { allowed: boolean; configured: boolean; required: boolean; public_key: string | null; max_devices: number; devices: Device[] };
type Mode = { kind: "idle" } | { kind: "add" } | { kind: "remove"; id: number };

/** Push sign-in approval: register this browser, list and remove devices. Hidden when the organisation has it off and nothing is registered. */
export function PushDevicesCard() {
  const [s, setS] = useState<Status | null>(null);
  const [mode, setMode] = useState<Mode>({ kind: "idle" });
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [here, setHere] = useState<number | null>(null);

  const load = () => http<Status>("/me/mfa/push").then(setS).catch(() => {});
  useEffect(() => {
    load();
    setHere(loadDevice()?.id ?? null);
  }, []);
  const reset = () => { setMode({ kind: "idle" }); setPassword(""); setName(""); };

  async function run(fn: () => Promise<void>, fail: string) {
    setMsg(null);
    setBusy(true);
    try { await fn(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : fail }); } finally { setBusy(false); }
  }
  const add = () => run(async () => {
    if (!s?.public_key) throw new Error("Push notifications are not set up on this server");
    const endpoint = await subscribe(s.public_key);
    const d = await http<{ id: number; secret: string }>("/me/mfa/push/devices", { method: "POST", body: { password, name: name.trim() || "This browser", endpoint } });
    saveDevice({ id: d.id, secret: d.secret });
    setHere(d.id);
    reset();
    await load();
    setMsg({ ok: true, text: "This browser can now approve sign-ins. Other devices were signed out." });
  }, "Could not register this browser");
  const remove = (id: number) => run(async () => {
    await http(`/me/mfa/push/devices/${id}/remove`, { method: "POST", body: { password } });
    if (id === here) { forgetDevice(); setHere(null); }
    reset();
    await load();
    setMsg({ ok: true, text: "Device removed." });
  }, "Could not remove the device");

  if (!s || (!s.allowed && s.devices.length === 0)) return null;
  const supported = pushSupported();
  return (
    <Card className="mt-6" data-testid="push-card">
      <CardHeader><CardTitle className="flex items-center gap-2">Approve sign-ins on a device {s.devices.length ? <Badge tone="good">On</Badge> : <Badge tone="neutral">Off</Badge>}{s.required && <Badge tone="info">Required</Badge>}</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">After your password, the sign-in screen shows a two-digit number. You get a notification on a browser you registered here and tap the same number to finish signing in.</p>
        {msg && <Alert variant={msg.ok ? "default" : "destructive"} role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
        {!s.configured && <p className="text-destructive">This server has no push keys yet, so devices cannot be registered.</p>}
        {s.devices.length > 0 && (
          <ul className="divide-y rounded-md border" data-testid="push-devices">
            {s.devices.map((d) => (
              <li key={d.id} className="flex items-center justify-between gap-2 p-2">
                <span>{d.name}{d.id === here && <span className="ml-2"><Badge tone="info">This browser</Badge></span>}<span className="block text-xs text-muted-foreground">Added {d.created_at ? new Date(d.created_at).toLocaleDateString() : "—"}{d.last_used_at ? ` · last used ${new Date(d.last_used_at).toLocaleDateString()}` : ""}</span></span>
                <Button size="sm" variant="outline" onClick={() => setMode({ kind: "remove", id: d.id })}>Remove</Button>
              </li>
            ))}
          </ul>
        )}
        {mode.kind === "idle" && s.allowed && s.configured && s.devices.length < s.max_devices && (
          supported
            ? <Button size="sm" data-testid="push-add" onClick={() => setMode({ kind: "add" })}>Register this browser</Button>
            : <p className="text-muted-foreground">This browser cannot receive push notifications. On an iPhone, add Ifora to the Home Screen first.</p>
        )}
        {mode.kind !== "idle" && (
          <form className="max-w-xs space-y-2" onSubmit={(e) => { e.preventDefault(); void (mode.kind === "add" ? add() : remove(mode.id)); }}>
            {mode.kind === "add" && (<><Label htmlFor="pd-name">Name this device</Label><Input id="pd-name" value={name} maxLength={80} placeholder="Work laptop" onChange={(e) => setName(e.target.value)} /></>)}
            <Label htmlFor="pd-pw">Confirm your password</Label>
            <Input id="pd-pw" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <div className="flex gap-2"><Button size="sm" type="submit" disabled={busy || !password} data-testid="push-confirm">{mode.kind === "add" ? "Register" : "Remove"}</Button><Button size="sm" type="button" variant="ghost" onClick={reset}>Cancel</Button></div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
