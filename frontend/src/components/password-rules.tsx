"use client";

import { useEffect, useState } from "react";
import { API_URL } from "@/lib/api";

/** The organization's current password rules, shown next to any "new password" field. */
export function PasswordRules({ className = "" }: { className?: string }) {
  const [rules, setRules] = useState<string[] | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(`${API_URL}/api/v1/password-policy`, { credentials: "include" }).then((r) => (r.ok ? r.json() : null)).then((d) => { if (alive && d) setRules(d.rules); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  if (!rules) return null;
  return <p className={"text-xs text-muted-foreground " + className} data-testid="password-rules">{rules.join(" · ")}</p>;
}
