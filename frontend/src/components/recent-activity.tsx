"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fmt } from "@/components/bits";
import { http } from "@/lib/http";

type Item = { id: number; action: string; timestamp: string; ip: string | null };
const LABEL: Record<string, string> = {
  LOGIN_SUCCESS: "Signed in", LOGIN_FAILURE: "Failed sign-in attempt", LOGOUT: "Signed out", USER_PASSWORD_CHANGED: "Password changed",
  PASSWORD_RESET_COMPLETED: "Password reset", MFA_ENABLED: "Authenticator app turned on", MFA_DISABLED: "Authenticator app turned off",
  MFA_RESET: "Sign-in factors reset", MFA_RECOVERY_USED: "Recovery code used", PASSKEY_REGISTERED: "Passkey added", PASSKEY_REMOVED: "Passkey removed",
};

/** The person's own recent security events, so an unfamiliar sign-in is easy to spot. */
export function RecentActivity() {
  const [items, setItems] = useState<Item[] | null>(null);
  useEffect(() => { http<{ items: Item[] }>("/me/dashboard/activity").then((r) => setItems(r.items)).catch(() => setItems([])); }, []);
  return (
    <Card className="mb-6" data-testid="recent-activity">
      <CardHeader><CardTitle>Recent activity</CardTitle></CardHeader>
      <CardContent>
        {items && items.length === 0 && <p className="text-sm text-muted-foreground">Nothing to show yet.</p>}
        <ul className="divide-y text-sm">
          {items?.slice(0, 8).map((i) => (
            <li key={i.id} className="flex flex-wrap justify-between gap-2 py-2">
              <span className={i.action === "LOGIN_FAILURE" ? "font-medium text-destructive" : ""}>{LABEL[i.action] ?? i.action}</span>
              <span className="text-muted-foreground">{fmt(i.timestamp)}{i.ip ? ` · ${i.ip}` : ""}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-muted-foreground">Don’t recognise something? Change your password in Account settings.</p>
      </CardContent>
    </Card>
  );
}
