"use client";

import { useCallback, useEffect, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { Badge, PageHeader, Pager, fieldClass, fmt, td, th } from "@/components/bits";
import { JobView, RecipeTabs } from "@/components/recipe-bits";
import { http, qs, type Page } from "@/lib/http";
import { statusTone, type Job, type RecipeSummary } from "@/lib/recipes";

export default function JobHistoryPage() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [recipeId, setRecipeId] = useState("");
  const [data, setData] = useState<Page<Job> | null>(null);
  const [recipes, setRecipes] = useState<RecipeSummary[]>([]);
  const [open, setOpen] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    http<Page<Job>>(`/admin/recipes/jobs${qs({ page, page_size: 20, status, recipe_id: recipeId })}`)
      .then(setData).catch((e) => setErr(e.message));
  }, [page, status, recipeId]);
  useEffect(load, [load]);
  useEffect(() => { http<{ items: RecipeSummary[] }>("/admin/recipes").then((r) => setRecipes(r.items)).catch(() => {}); }, []);

  return (
    <div>
      <PageHeader title="Recipes" />
      <RecipeTabs />
      <div className="mb-4 flex flex-wrap gap-2">
        <select aria-label="Filter by recipe" className={fieldClass + " !w-56"} value={recipeId} onChange={(e) => { setPage(1); setRecipeId(e.target.value); }}>
          <option value="">All recipes</option>
          {recipes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <select aria-label="Filter by status" className={fieldClass + " !w-44"} value={status} onChange={(e) => { setPage(1); setStatus(e.target.value); }}>
          <option value="">Any status</option>
          {["queued", "running", "succeeded", "failed", "cancelled"].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <button className="rounded border px-3 text-sm" onClick={load}>Refresh</button>
      </div>
      {err && <Alert variant="destructive" className="mb-4"><AlertDescription>{err}</AlertDescription></Alert>}
      <Card><CardContent className="overflow-x-auto p-0">
        <table className="w-full" data-testid="jobs-table">
          <thead className="border-b"><tr><th className={th}>Job</th><th className={th}>Recipe</th><th className={th}>Trigger</th><th className={th}>Status</th><th className={th}>Started</th><th className={th}></th></tr></thead>
          <tbody>
            {data?.items.map((j) => (
              <tr key={j.id} className="border-b last:border-0">
                <td className={td}>#{j.id}{j.mode === "dry_run" ? " (test)" : ""}</td>
                <td className={td}>{j.recipe_name ?? j.recipe_id}{j.version ? ` v${j.version}` : ""}</td>
                <td className={td}>{j.trigger_type}</td>
                <td className={td}><Badge tone={statusTone(j.status)}>{j.status}</Badge></td>
                <td className={td}>{fmt(j.created_at)}</td>
                <td className={td + " text-right"}><button className="underline underline-offset-4" onClick={() => http<Job>(`/admin/recipes/jobs/${j.id}`).then(setOpen).catch((e) => setErr(e.message))}>Details</button></td>
              </tr>
            ))}
            {data && data.items.length === 0 && <tr><td className={td} colSpan={6}>No jobs yet.</td></tr>}
          </tbody>
        </table>
      </CardContent></Card>
      {data && <Pager page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
      {open && (
        <Card className="mt-6"><CardContent className="space-y-3 pt-6">
          <div className="flex items-center justify-between"><h2 className="font-semibold">Job #{open.id} · {open.recipe_name}</h2><button className="text-sm underline" onClick={() => setOpen(null)}>Close</button></div>
          <JobView job={open} />
        </CardContent></Card>
      )}
    </div>
  );
}
