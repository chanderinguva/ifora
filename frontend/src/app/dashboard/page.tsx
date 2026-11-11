"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ShieldAlert } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, PageHeader } from "@/components/bits";
import { useCurrentUser } from "@/components/auth-guard";
import { AppTiles } from "@/components/app-tiles";
import { RecentActivity } from "@/components/recent-activity";
import { inAdminView } from "@/lib/roles";
import { http } from "@/lib/http";
import type { User } from "@/lib/types";

/** End-user home, laid out like Okta's dashboard: the apps come first; account upkeep sits in a side rail and only nags when something is missing. */
export default function UserHome() {
  const cu = useCurrentUser();
  const [me, setMe] = useState<User | null>(null);
  useEffect(() => {
    http<User>("/me/profile").then(setMe).catch(() => {});
  }, []);
  if (!me) return <div className="text-sm text-muted-foreground">Loading…</div>;

  const todo = [
    !((me.passkey_count ?? 0) > 0) && "Add a passkey: phishing-resistant sign-in with Touch ID, Windows Hello or a security key.",
    !me.mfa_enabled && "Set up an authenticator app: Google Authenticator, Microsoft Authenticator, Okta Verify, 1Password…",
  ].filter((x): x is string => !!x);

  return (
    <div className="max-w-7xl">
      <PageHeader title={`Hello, ${me.first_name}`}>
        {inAdminView(cu) && <Link href="/admin/dashboard" className="text-sm underline-offset-4 hover:underline">Go to administration →</Link>}
      </PageHeader>

      <div className="grid items-start gap-8 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <section aria-labelledby="my-apps-h">
          <h2 id="my-apps-h" className="mb-4 text-lg font-semibold">My apps</h2>
          <AppTiles />
        </section>

        <aside aria-label="Your account" className="space-y-4">
          {todo.length > 0 && (
            <Card className="border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/30" data-testid="security-checklist">
              <CardHeader><CardTitle className="flex items-center gap-2 text-base"><ShieldAlert className="h-4 w-4 text-amber-600" /> Protect your account</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
                <ul className="list-disc space-y-1 pl-5">{todo.map((t) => <li key={t}>{t}</li>)}</ul>
                <Link href="/settings#security" className="inline-block font-medium underline-offset-4 hover:underline">Set up in Account settings →</Link>
              </CardContent>
            </Card>
          )}

          <RecentActivity />

          <Card>
            <CardHeader><CardTitle className="text-base">My groups</CardTitle></CardHeader>
            <CardContent>
              {me.groups && me.groups.length > 0 ? (
                <ul className="flex flex-wrap gap-2">{me.groups.map((g) => <li key={g.id}><Badge tone="info">{g.name}</Badge></li>)}</ul>
              ) : (
                <p className="text-sm text-muted-foreground">You are not a member of any group.</p>
              )}
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
