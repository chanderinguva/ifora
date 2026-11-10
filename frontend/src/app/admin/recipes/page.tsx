"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fmt, td, th } from "@/components/bits";
import { RecipeTabs } from "@/components/recipe-bits";
import { ImportCard, TemplatePicker } from "@/components/recipe-starters";
import { http } from "@/lib/http";
import { blankDefinition, statusTone, type RecipeMeta, type RecipeSummary } from "@/lib/recipes";

export default function RecipesPage() {
  const router = useRouter();
  const [items, setItems] = useState<RecipeSummary[] | null>(null);
  const [meta, setMeta] = useState<RecipeMeta | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [name, setName] = useState<string | null>(null);
  const [panel, setPanel] = useState<"template" | "import" | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    http<{ items: RecipeSummary[] }>("/admin/recipes")
      .then((r) => setItems(r.items))
      .catch((e) => { setEnabled(false); setMsg({ ok: false, text: e.message }); });
    http<RecipeMeta>("/admin/recipes/meta").then(setMeta).catch(() => {});
  }, []);
  useEffect(load, [load]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); load(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }
  const trig = (t: string) => meta?.triggers.find((x) => x.type === t)?.label ?? t;

  if (!enabled && items === null) {
    return (
      <div>
        <PageHeader title="Recipes" />
        <Alert><AlertDescription>{msg?.text ?? "Recipes are not enabled for this deployment"} (<code>RECIPES_ENABLED</code>).</AlertDescription></Alert>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Recipes">
        <Button variant="outline" onClick={() => { setPanel("import"); setName(null); }}>Import</Button>
        <Button variant="outline" onClick={() => { setPanel("template"); setName(null); }}>From template</Button>
        <Button onClick={() => { setName(""); setPanel(null); }}><Plus className="mr-1 h-4 w-4" /> New recipe</Button>
      </PageHeader>
      <RecipeTabs />
      <p className="mb-4 max-w-2xl text-sm text-muted-foreground">
        A recipe reacts to something that happens in Ifora (or runs on a schedule, by hand, or from a signed webhook) and then runs
        its steps in order. Only the published version runs; edit the draft freely and publish when it is ready.
      </p>
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      {panel === "template" && <TemplatePicker meta={meta} onCancel={() => setPanel(null)} onError={(t) => setMsg({ ok: false, text: t })} onCreated={(r) => router.push(`/admin/recipes/${r.id}`)} />}
      {panel === "import" && <ImportCard onCancel={() => setPanel(null)} onError={(t) => setMsg({ ok: false, text: t })} onCreated={(r) => router.push(`/admin/recipes/${r.id}`)} />}
      {name !== null && (
        <Card className="mb-6" data-testid="new-recipe"><CardContent className="space-y-3 pt-6">
          <Label htmlFor="rc-name">Recipe name</Label>
          <Input id="rc-name" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          <div className="flex gap-2">
            <Button disabled={!name.trim()} onClick={() => run(async () => {
              const r = await http<RecipeSummary>("/admin/recipes", { method: "POST", body: { name, definition: blankDefinition() } });
              router.push(`/admin/recipes/${r.id}`);
            }, "Created")}>Create and open builder</Button>
            <Button variant="ghost" onClick={() => setName(null)}>Cancel</Button>
          </div>
        </CardContent></Card>
      )}

      <Card><CardContent className="overflow-x-auto p-0">
        <table className="w-full" data-testid="recipes-table">
          <thead className="border-b"><tr><th className={th}>Recipe</th><th className={th}>Owner</th><th className={th}>Trigger</th><th className={th}>Version</th><th className={th}>Last run</th><th className={th}>Status</th><th className={th}></th></tr></thead>
          <tbody>
            {items?.map((r) => (
              <tr key={r.id} className="border-b align-top last:border-0">
                <td className={td + " font-medium"}><Link className="underline-offset-4 hover:underline" href={`/admin/recipes/${r.id}`}>{r.name}</Link></td>
                <td className={td}>{r.owner?.email ?? "—"}{r.last_alert_at && <div><Badge tone="bad">failure alert</Badge></div>}</td>
                <td className={td}>{trig(r.trigger_type)}</td>
                <td className={td}>{r.published_version ? `v${r.published_version}` : "unpublished"}{r.has_unpublished_changes && r.published_version ? <span className="ml-1 text-xs text-amber-600">draft changes</span> : null}</td>
                <td className={td}>{r.last_job ? <><Badge tone={statusTone(r.last_job.status)}>{r.last_job.status}</Badge> <span className="text-xs text-muted-foreground">{fmt(r.last_job.created_at)}</span></> : "—"}</td>
                <td className={td}><Badge tone={r.enabled ? "good" : "neutral"}>{r.enabled ? "enabled" : "disabled"}</Badge></td>
                <td className={td + " space-x-2 whitespace-nowrap text-right"}>
                  {r.enabled ? (
                    <Button size="sm" variant="outline" disabled={!r.can_manage} onClick={() => run(() => http(`/admin/recipes/${r.id}/disable`, { method: "POST" }), "Recipe disabled")}>Disable</Button>
                  ) : (
                    <Button size="sm" disabled={!r.published_version || !r.can_manage} title={r.published_version ? undefined : "Publish first"} onClick={() => run(() => http(`/admin/recipes/${r.id}/enable`, { method: "POST" }), "Recipe enabled")}>Enable</Button>
                  )}
                  <Button size="sm" variant="outline" disabled={!r.can_manage} onClick={() => { if (confirm(`Delete recipe "${r.name}" and its job history?`)) run(() => http(`/admin/recipes/${r.id}`, { method: "DELETE" }), "Recipe deleted"); }}>Delete</Button>
                </td>
              </tr>
            ))}
            {items && items.length === 0 && <tr><td className={td} colSpan={7}>No recipes yet. Create one to automate group membership, attributes or outbound calls.</td></tr>}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  );
}
