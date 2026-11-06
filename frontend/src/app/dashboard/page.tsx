"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Circle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, PageHeader } from "@/components/bits";
import { useCurrentUser } from "@/components/auth-guard";
import { inAdminView } from "@/lib/roles";
import { http } from "@/lib/http";
import type { User } from "@/lib/types";

/** End-user home: who am I, what groups am I in, and how well is my account protected. */
export default function UserHome() {
  const cu = useCurrentUser();
  const [me, setMe] = useState<User | null>(null);
  useEffect(() => {
    http<User>("/me/profile").then(setMe).catch(() => {});
  }, []);
  if (!me) return <div className="text-sm text-muted-foreground">Loading…</div>;

  const steps = [
    { done: (me.passkey_count ?? 0) > 0, label: "Add a passkey", hint: "Phishing-resistant sign-in with Touch ID, Windows Hello or a security key." },
    { done: !!me.mfa_enabled, label: "Set up an authenticator app", hint: "Google Authenticator, Microsoft Authenticator, Okta Verify, 1Password…" },
  ];

  return (
    <div className="max-w-3xl">
      <PageHeader title={`Hello, ${me.first_name}`}>
        {inAdminView(cu) && <Link href="/admin/dashboard" className="text-sm underline-offset-4 hover:underline">Go to administration →</Link>}
      </PageHeader>

      <Card className="mb-6" data-testid="security-checklist">
        <CardHeader><CardTitle>Protect your account</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {steps.map((s) => (
            <div key={s.label} className="flex items-start gap-3">
              {s.done ? <CheckCircle2 className="mt-0.5 h-5 w-5 text-green-600 dark:text-green-400" /> : <Circle className="mt-0.5 h-5 w-5 text-muted-foreground" />}
              <div>
                <div className="text-sm font-medium">{s.label} {s.done && <Badge tone="good">done</Badge>}</div>
                <div className="text-xs text-muted-foreground">{s.hint}</div>
              </div>
            </div>
          ))}
          <Link href="/settings#security" className="inline-block text-sm underline-offset-4 hover:underline">Manage in Account settings →</Link>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>My groups</CardTitle></CardHeader>
        <CardContent>
          {me.groups && me.groups.length > 0 ? (
            <ul className="flex flex-wrap gap-2">{me.groups.map((g) => <li key={g.id}><Badge tone="info">{g.name}</Badge></li>)}</ul>
          ) : (
            <p className="text-sm text-muted-foreground">You are not a member of any group.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
