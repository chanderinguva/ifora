"use client";

import { PasswordRules } from "@/components/password-rules";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AttrField, fromApi, toApi } from "@/components/attr-field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fmt } from "@/components/bits";
import { MfaCard } from "@/components/mfa-card";
import { ConnectedAppsCard } from "@/components/connected-apps-card";
import { PasskeyCard } from "@/components/passkey-card";
import { LocaleSelect, TimezoneSelect } from "@/components/pref-selects";
import { setDisplayPrefs } from "@/lib/display";
import { useCurrentUser } from "@/components/auth-guard";
import { inAdminView } from "@/lib/roles";
import { http } from "@/lib/http";
import type { User } from "@/lib/types";

type SessionRow = { id: number; created_at: string; expires_at: string; current: boolean; ip_address: string | null; user_agent: string | null };


type ActivityRow = { timestamp: string; action: string; ip_address: string | null; method: string | null };
const ACTIVITY_LABEL: Record<string, string> = {
  LOGIN_SUCCESS: "Signed in", LOGIN_FAILURE: "Failed sign-in", LOGOUT: "Signed out", USER_PASSWORD_CHANGED: "Password changed",
  MFA_ENABLED: "Authenticator app added", MFA_DISABLED: "Authenticator app removed", MFA_RESET: "Sign-in factors reset",
  MFA_RECOVERY_USED: "Recovery code used", MFA_CHALLENGE_FAILED: "Failed second factor", PASSKEY_REGISTERED: "Passkey added",
  PASSKEY_REMOVED: "Passkey removed", PASSKEY_LOGIN_FAILED: "Failed passkey sign-in", ROLE_SWITCHED: "Switched role view",
};

export default function AccountSettings() {
  const cu = useCurrentUser();
  const [me, setMe] = useState<User | null>(null);
  const [names, setNames] = useState({ first_name: "", last_name: "" });
  const [attrs, setAttrs] = useState<Record<string, string>>({});
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [activity, setActivity] = useState<ActivityRow[]>([]);
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const apply = (u: User) => {
    setMe(u);
    setDisplayPrefs(u.profile_attributes);
    setNames({ first_name: u.first_name, last_name: u.last_name });
    setAttrs(Object.fromEntries((u.editable_attributes ?? []).map((k) => [k, fromApi(u.profile_attributes?.[k])])));
  };
  const loadSessions = () => http<{ items: SessionRow[] }>("/me/sessions").then((r) => setSessions(r.items)).catch(() => {});

  useEffect(() => {
    http<User>("/me/profile").then(apply).catch((e) => setMsg({ ok: false, text: e.message }));
    loadSessions();
    http<{ items: ActivityRow[] }>("/me/activity").then((r) => setActivity(r.items)).catch(() => {});
    // the factor cards announce changes so the "setup required" banner clears right after enrolling
    const refresh = () => http<User>("/me/profile").then((u) => setMe((m) => (m ? { ...m, mfa_setup_required: u.mfa_setup_required, mfa_enabled: u.mfa_enabled, passkey_count: u.passkey_count } : u))).catch(() => {});
    window.addEventListener("factors-changed", refresh);
    return () => window.removeEventListener("factors-changed", refresh);
  }, []);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: ok });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    }
  }

  const changePassword = () =>
    run(async () => {
      await http("/me/password", { method: "POST", body: pw });
      setPw({ current_password: "", new_password: "" });
      loadSessions();
    }, "Password changed; other sessions were signed out");

  if (!me) return <div className="text-sm text-muted-foreground">{msg ? msg.text : "Loading…"}</div>;

  const schema = me.attribute_schema ?? [];
  const label = (k: string) => schema.find((a) => a.key === k)?.display_name ?? k;
  const general = schema.filter((a) => a.user_editable && a.key !== "timezone" && a.key !== "locale");
  const readOnly = Object.entries(me.profile_attributes ?? {}).filter(([k]) => !(me.editable_attributes ?? []).includes(k));

  return (
    <div className="max-w-3xl">
      <PageHeader title="Account settings">
        {inAdminView(cu) && <Link href="/admin/dashboard" className="text-sm underline-offset-4 hover:underline">Go to administration →</Link>}
      </PageHeader>

      {me.mfa_setup_required && (
        <Alert variant="warning" className="mb-4" data-testid="mfa-required-banner">
          <AlertDescription>
            <strong>Action required:</strong> administrators must protect their account with a passkey or an authenticator app. You need a one-time enrolment code for this: ask a super admin, or the operator (<code>python -m backend.cli issue-enrollment-code &lt;email&gt;</code>). Then set one up under Security below to unlock the admin area.
          </AlertDescription>
        </Alert>
      )}
      {!me.mfa_setup_required && inAdminView(cu) && (
        <p className="mb-4 text-sm"><Link href="/admin/dashboard" className="underline underline-offset-4">Continue to administration →</Link></p>
      )}

      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      <Card className="mb-6">
        <CardHeader><CardTitle>Profile</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">{me.email} · {me.username}</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="pf-first">First name</Label>
              <Input id="pf-first" value={names.first_name} onChange={(e) => setNames({ ...names, first_name: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="pf-last">Last name</Label>
              <Input id="pf-last" value={names.last_name} onChange={(e) => setNames({ ...names, last_name: e.target.value })} />
            </div>
            {general.map((a) => (
              <div key={a.key} className="space-y-2">
                <Label htmlFor={`pf-${a.key}`}>{a.display_name}</Label>
                <AttrField idPrefix="pf" attr={a} value={attrs[a.key] ?? ""} onChange={(v) => setAttrs({ ...attrs, [a.key]: v })} />
              </div>
            ))}
          </div>
          <div className="border-t pt-4">
            <h3 className="mb-3 text-sm font-semibold">Language &amp; region</h3>
            <div className="grid gap-4 sm:grid-cols-2">
              {"timezone" in attrs && (
                <div className="space-y-2">
                  <Label htmlFor="pf-timezone">Time zone</Label>
                  <TimezoneSelect id="pf-timezone" value={attrs.timezone} onChange={(v) => setAttrs({ ...attrs, timezone: v })} />
                </div>
              )}
              {"locale" in attrs && (
                <div className="space-y-2">
                  <Label htmlFor="pf-locale">Locale</Label>
                  <LocaleSelect id="pf-locale" value={attrs.locale} onChange={(v) => setAttrs({ ...attrs, locale: v })} />
                </div>
              )}
            </div>
          </div>
          {readOnly.length > 0 && (
            <div className="text-sm">
              <div className="mb-1 font-medium">Managed by your administrator</div>
              <ul className="text-muted-foreground">
                {readOnly.map(([k, v]) => <li key={k}>{label(k)}: {String(v)}</li>)}
              </ul>
            </div>
          )}
          <Button onClick={() => run(async () => apply(await http<User>("/me/profile", { method: "PATCH", body: { ...names, profile_attributes: Object.fromEntries((me.attribute_schema ?? []).filter((a) => a.user_editable).map((a) => [a.key, toApi(a, attrs[a.key] ?? "")])) } })), "Profile saved")}>
            Save profile
          </Button>
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardHeader><CardTitle>My groups</CardTitle></CardHeader>
        <CardContent>
          {me.groups && me.groups.length > 0 ? (
            <ul className="flex flex-wrap gap-2">{me.groups.map((g) => <li key={g.id}><Badge tone="info">{g.name}</Badge></li>)}</ul>
          ) : (
            <p className="text-sm text-muted-foreground">You are not a member of any group.</p>
          )}
        </CardContent>
      </Card>

      <h2 className="mb-3 mt-8 text-lg font-semibold" id="security">Security</h2>
      <PasskeyCard needsCode={!!me.mfa_setup_required} />
      <MfaCard needsCode={!!me.mfa_setup_required} />

      <Card className="mb-6">
        <CardHeader><CardTitle>Change password</CardTitle></CardHeader>
        <CardContent>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); changePassword(); }}>
          <div className="space-y-2">
            <Label htmlFor="cur">Current password</Label>
            <Input id="cur" type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new">New password</Label>
            <Input id="new" type="password" autoComplete="new-password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} />
            <PasswordRules />
            <p className="text-xs text-muted-foreground">12+ characters, mixed case, with a digit. Other devices are signed out.</p>
          </div>
          <Button type="submit" disabled={!pw.current_password || !pw.new_password}>
            Change password
          </Button>
          </form>
        </CardContent>
      </Card>

      <ConnectedAppsCard />

      <Card className="mb-6">
        <CardHeader><CardTitle>Recent activity</CardTitle></CardHeader>
        <CardContent>
          {activity.length === 0 ? (
            <p className="text-sm text-muted-foreground">No recent activity.</p>
          ) : (
            <ul className="space-y-2 text-sm" data-testid="activity">
              {activity.map((a, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2">
                  <Badge tone={a.action.endsWith("FAILURE") || a.action.endsWith("FAILED") ? "bad" : "neutral"}>{ACTIVITY_LABEL[a.action] ?? a.action}</Badge>
                  <span>{fmt(a.timestamp)}</span>
                  <span className="text-muted-foreground">· {a.ip_address ?? "unknown IP"}{a.method ? ` · ${a.method}` : ""}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-muted-foreground">Don&apos;t recognise something? Change your password; other devices are signed out.</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Active sessions</CardTitle></CardHeader>
        <CardContent>
          <ul className="space-y-2 text-sm" data-testid="sessions">
            {sessions.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-2">
                {s.current && <Badge tone="good">this device</Badge>}
                <span>Signed in {fmt(s.created_at)}</span>
                <span className="text-muted-foreground">· {s.ip_address ?? "unknown IP"} · expires {fmt(s.expires_at)}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
