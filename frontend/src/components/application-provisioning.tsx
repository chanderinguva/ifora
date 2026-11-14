"use client";

import { useEffect, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldClass } from "@/components/bits";
import { useCurrentUser } from "@/components/auth-guard";
import { ProvisioningDetail } from "@/components/provisioning-detail";
import { http } from "@/lib/http";
import { scimSetupBody, type ProvApp } from "@/lib/provisioning";
import type { AppSummary } from "@/lib/applications";

/** Attach provisioning to this Application; never create a second directory application. */
export function ApplicationProvisioning({ app, onChange, onAssignments }: { app: AppSummary; onChange: () => void; onAssignments: () => void }) {
  const me = useCurrentUser();
  const [canWrite, setCanWrite] = useState(me.is_super_admin);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [attached, setAttached] = useState<number | null>(app.provisioning?.id ?? null);
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState("");
  const [auth, setAuth] = useState("bearer");
  const [header, setHeader] = useState("");
  const [tokenUrl, setTokenUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [scope, setScope] = useState("");
  const [updates, setUpdates] = useState("patch");
  useEffect(() => {
    http<{ access: Record<string, string> }>("/me/admin-access").then((r) => setCanWrite(me.is_super_admin || r.access.applications === "write")).catch(() => {});
    http<{ available: boolean }>("/admin/provisioning-apps/presets").then((r) => setAvailable(r.available)).catch((e) => { setAvailable(false); setError(e.message); });
  }, [me.is_super_admin]);
  if (attached) return <ProvisioningDetail key={attached} id={String(attached)} embedded onAssignments={onAssignments} onRemoved={() => { setAttached(null); onChange(); }} />;
  return <Card data-testid="application-provisioning-setup">
    <CardHeader><CardTitle>Set up provisioning</CardTitle></CardHeader>
    <CardContent className="space-y-5">
      <p className="text-sm text-muted-foreground">Add SCIM to {app.name}. Sign-on and provisioning share this application and its assignments. SAML does not imply SCIM support; confirm the service supports SCIM 2.0 and your plan includes it.</p>
      <p className="text-sm">The connection starts off. Test it and review user mappings before turning it on. Enabling it can create or update accounts for existing assignments.</p>
      <details className="rounded-lg border p-3 text-sm"><summary className="cursor-pointer font-medium">Slack SCIM setup</summary>
        <div className="mt-3 space-y-3">
          <p>Slack supports SCIM 2.0 on eligible Business+ and Enterprise plans. Use an authorized OAuth credential with the admin scope, not your message-posting bot token. Confirm its workspace or organization before enabling provisioning.</p>
          {canWrite && <Button type="button" variant="outline" disabled={available !== true} onClick={() => {
            setUrl("https://api.slack.com/scim/v2"); setAuth("bearer"); setUpdates("patch"); setSecret("");
          }}>Use Slack SCIM settings</Button>}
          <a href="https://docs.slack.dev/admins/scim-api/" target="_blank" rel="noopener noreferrer" className="block underline underline-offset-4">Slack SCIM requirements and token setup ↗</a>
        </div>
      </details>
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      {available === false && <p role="status" className="text-sm text-muted-foreground">Provisioning is unavailable. An administrator must enable the server provisioning feature and encrypted credential storage.</p>}
      {!canWrite ? <p className="text-sm text-muted-foreground">You can view this application; an administrator with application-write permission must configure provisioning.</p> :
        <form className="space-y-4" onSubmit={async (e) => {
          e.preventDefault(); setError(""); setBusy(true);
          try {
            const created = await http<ProvApp>("/admin/provisioning-apps", { method: "POST",
              body: scimSetupBody(app.id, app.name, { url, auth, secret, header, tokenUrl, clientId, scope, updates }) });
            setSecret(""); setAttached(created.id); onChange();
          } catch (e) { setError(e instanceof Error ? e.message : "Could not save provisioning"); }
          finally { setBusy(false); }
        }}>
          <fieldset disabled={busy || available !== true} className="grid min-w-0 gap-4 sm:grid-cols-2">
            <div className="space-y-1 sm:col-span-2"><Label htmlFor="p-url">SCIM 2.0 base URL (required)</Label><Input id="p-url" type="url" required placeholder="https://app.example.com/scim/v2" value={url} onChange={(e) => setUrl(e.target.value)} /></div>
            <div className="space-y-1"><Label htmlFor="p-auth">Authentication</Label><select id="p-auth" className={fieldClass} value={auth} onChange={(e) => { setAuth(e.target.value); setSecret(""); }}>
              <option value="bearer">Bearer token</option><option value="basic">Basic (user:password)</option><option value="header">Custom header</option><option value="oauth2">OAuth 2.0 client credentials</option>
            </select></div>
            <div className="space-y-1"><Label htmlFor="p-updates">Profile updates</Label><select id="p-updates" className={fieldClass} value={updates} onChange={(e) => setUpdates(e.target.value)}><option value="patch">PATCH</option><option value="put">PUT (replace)</option></select></div>
            {auth === "header" && <div className="space-y-1"><Label htmlFor="p-header">Header name (required)</Label><Input id="p-header" required value={header} onChange={(e) => setHeader(e.target.value)} /></div>}
            {auth === "oauth2" && <>
              <div className="space-y-1"><Label htmlFor="p-token-url">Token URL (required)</Label><Input id="p-token-url" type="url" required value={tokenUrl} onChange={(e) => setTokenUrl(e.target.value)} /></div>
              <div className="space-y-1"><Label htmlFor="p-client">Client ID (required)</Label><Input id="p-client" required value={clientId} onChange={(e) => setClientId(e.target.value)} /></div>
              <div className="space-y-1"><Label htmlFor="p-scope">Scope (optional)</Label><Input id="p-scope" value={scope} onChange={(e) => setScope(e.target.value)} /></div>
            </>}
            <div className="space-y-1 sm:col-span-2"><Label htmlFor="p-secret">{auth === "basic" ? "user:password" : auth === "oauth2" ? "Client secret" : auth === "header" ? "Header value" : "Token"} (required)</Label><Input id="p-secret" type="password" autoComplete="off" required maxLength={2000} value={secret} onChange={(e) => setSecret(e.target.value)} /></div>
            <p className="text-xs text-muted-foreground sm:col-span-2">Credentials are encrypted by the server and never read back into this form. Group push is off until explicitly configured.</p>
            <Button type="submit" className="sm:col-span-2 sm:justify-self-start" disabled={!url.trim() || !secret || busy || available !== true}>Save provisioning connection</Button>
          </fieldset>
        </form>}
    </CardContent>
  </Card>;
}
