"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { Badge, PageHeader, fieldClass, td, th } from "@/components/bits";
import { RecipeTabs } from "@/components/recipe-bits";
import { http } from "@/lib/http";
import type { Metrics } from "@/lib/recipes";

const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);
const secs = (v: number | null) => (v === null ? "—" : v < 60 ? `${v.toFixed(1)} s` : `${(v / 60).toFixed(1)} min`);

export default function RecipeHealthPage() {
  const [hours, setHours] = useState(24);
  const [m, setM] = useState<Metrics | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    http<Metrics>(`/admin/recipes/metrics?hours=${hours}`).then((r) => { setM(r); setErr(null); }).catch((e) => setErr(e.message));
  }, [hours]);
  useEffect(load, [load]);
  const alerting = m?.items.filter((i) => i.alerting) ?? [];

  return (
    <div>
      <PageHeader title="Recipes" />
      <RecipeTabs />
      {err && <Alert variant="destructive" className="mb-4"><AlertDescription>{err}</AlertDescription></Alert>}
      {alerting.length > 0 && m && (
        <Alert variant="warning" className="mb-4" data-testid="health-alert"><AlertDescription>
          High failure rate (at least {Math.round(m.alert_rule.failure_rate * 100)}% of {m.alert_rule.min_jobs}+ jobs in {m.alert_rule.window_minutes} min):{" "}
          {alerting.map((a) => <Link key={a.recipe_id} className="mr-2 underline underline-offset-4" href={`/admin/recipes/${a.recipe_id}`}>{a.name}</Link>)}
        </AlertDescription></Alert>
      )}
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        <label htmlFor="h-win">Window</label>
        <select id="h-win" className={fieldClass + " !w-36"} value={hours} onChange={(e) => setHours(Number(e.target.value))}>
          {[1, 6, 24, 72, 168].map((h) => <option key={h} value={h}>{h} hour{h > 1 ? "s" : ""}</option>)}
        </select>
        {m && <span className="text-muted-foreground" data-testid="queue-summary">Queue: {m.queue.queued} queued, {m.queue.waiting} waiting for approval{m.queue.oldest_queued_age_seconds !== null ? `, oldest queued ${secs(m.queue.oldest_queued_age_seconds)}` : ""}</span>}
      </div>
      <Card><CardContent className="overflow-x-auto p-0">
        <table className="w-full" data-testid="health-table">
          <thead className="border-b"><tr><th className={th}>Recipe</th><th className={th}>Jobs</th><th className={th}>Succeeded</th><th className={th}>Failed</th><th className={th}>Failure rate</th><th className={th}>Median / p95</th><th className={th}>Dropped (rate limit)</th><th className={th}></th></tr></thead>
          <tbody>
            {m?.items.map((i) => (
              <tr key={i.recipe_id} className="border-b last:border-0">
                <td className={td + " font-medium"}><Link className="underline-offset-4 hover:underline" href={`/admin/recipes/${i.recipe_id}`}>{i.name}</Link>{!i.enabled && <span className="ml-1 text-xs text-muted-foreground">(disabled)</span>}</td>
                <td className={td}>{i.total}</td><td className={td}>{i.by_status.succeeded ?? 0}</td><td className={td}>{i.by_status.failed ?? 0}</td>
                <td className={td}>{pct(i.failure_rate)}</td><td className={td}>{secs(i.p50_seconds)} / {secs(i.p95_seconds)}</td>
                <td className={td}>{i.throttled_count}</td>
                <td className={td}>{i.alerting && <Badge tone="bad">alert</Badge>}</td>
              </tr>
            ))}
            {m && m.items.length === 0 && <tr><td className={td} colSpan={8}>No recipes yet.</td></tr>}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  );
}
