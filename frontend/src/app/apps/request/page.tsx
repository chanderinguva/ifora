"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, PageHeader, fmt } from "@/components/bits";
import { AppIcon } from "@/components/app-icon";
import { http } from "@/lib/http";

type Item = { id: number; name: string; description: string | null; has_icon: boolean; pending: boolean; reason_required: boolean };
type Req = { id: number; application_id: number; application_name: string; reason: string | null; status: string; decision_note: string | null; created_at: string; decided_at: string | null };
const TONE: Record<string, "neutral" | "good" | "bad" | "info"> = { pending: "info", approved: "good", denied: "bad", canceled: "neutral" };

/** Okta-style "add apps": things I could ask for, and where my requests stand. */
export default function RequestAccess() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [reqs, setReqs] = useState<Req[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const started = useRef(false);

  const load = useCallback(async () => {
    try {
      const [c, r] = await Promise.all([http<{ items: Item[] }>("/me/access/catalog"), http<{ items: Req[] }>("/me/access/requests")]);
      setItems(c.items); setReqs(r.items);
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Could not load" }); }
  }, []);
  useEffect(() => { if (started.current) return; started.current = true; load(); }, [load]);

  async function submit(a: Item) {
    setMsg(null);
    try {
      await http("/me/access/requests", { method: "POST", body: { application_id: a.id, reason } });
      setOpen(null); setReason(""); setMsg({ ok: true, text: `Request for ${a.name} sent. You will see it under My apps once it is approved.` });
      await load();
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Could not send the request" }); }
  }
  async function cancel(r: Req) {
    setMsg(null);
    try { await http(`/me/access/requests/${r.id}/cancel`, { method: "POST" }); await load(); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Could not cancel" }); }
  }

  // A denied or canceled request can be sent again with the same reason, if the app can still be requested.
  function again(r: Req) {
    setMsg(null);
    setOpen(r.application_id);
    setReason(r.reason ?? "");
    requestAnimationFrame(() => document.getElementById(`why-${r.application_id}`)?.scrollIntoView({ block: "center" }));
  }
  const requestable = (id: number) => items?.some((a) => a.id === id && !a.pending) ?? false;

  return (
    <div className="max-w-4xl">
      <PageHeader title="Request access" />
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
      {items && items.length === 0 && <p className="mb-6 text-sm text-muted-foreground" data-testid="no-catalog">There is nothing to request right now.</p>}
      <ul className="mb-8 grid gap-3 sm:grid-cols-2" data-testid="catalog">
        {items?.map((a) => (
          <li key={a.id} className="rounded-xl border bg-card p-4 shadow-sm" data-testid={`catalog-${a.id}`}>
            <div className="flex items-center gap-3">
              <AppIcon path={`/me/access/catalog/${a.id}/icon`} name={a.name} hasIcon={a.has_icon} size={40} />
              <div className="min-w-0 flex-1"><div className="truncate font-medium">{a.name}</div>{a.description && <div className="line-clamp-2 text-xs text-muted-foreground">{a.description}</div>}</div>
              {a.pending ? <Badge tone="info">Requested</Badge> : <Button size="sm" variant="outline" aria-label={`Request ${a.name}`} onClick={() => { setOpen(open === a.id ? null : a.id); setReason(""); }}>Request</Button>}
            </div>
            {open === a.id && (
              <form className="mt-3 space-y-2" onSubmit={(e) => { e.preventDefault(); submit(a); }}>
                <label className="text-xs text-muted-foreground" htmlFor={`why-${a.id}`}>Why do you need it?{a.reason_required ? " (required)" : " (optional)"}</label>
                <textarea id={`why-${a.id}`} className="w-full rounded-md border bg-background p-2 text-sm" rows={2} maxLength={500} required={a.reason_required} value={reason} onChange={(e) => setReason(e.target.value)} />
                <Button type="submit" size="sm" data-testid="send-request">Send request</Button>
              </form>
            )}
          </li>
        ))}
      </ul>
      <Card>
        <CardHeader><CardTitle>My requests</CardTitle></CardHeader>
        <CardContent>
          {reqs.length === 0 ? <p className="text-sm text-muted-foreground">You have not asked for anything yet.</p> : (
            <ul className="divide-y text-sm" data-testid="my-requests">
              {reqs.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span><strong>{r.application_name}</strong> <Badge tone={TONE[r.status] ?? "neutral"}>{r.status}</Badge>{r.decision_note ? <span className="ml-2 text-muted-foreground">“{r.decision_note}”</span> : r.status === "denied" ? <span className="ml-2 text-muted-foreground">No reason was given.</span> : null}</span>
                  <span className="flex items-center gap-2 text-muted-foreground">
                    {r.status === "pending" ? `Sent ${fmt(r.created_at)}` : r.decided_at ? `${r.status === "approved" ? "Approved" : r.status === "denied" ? "Denied" : "Closed"} ${fmt(r.decided_at)}` : fmt(r.created_at)}
                    {r.status === "pending" && <Button size="sm" variant="ghost" aria-label={`Cancel request for ${r.application_name}`} onClick={() => cancel(r)}>Cancel</Button>}
                    {(r.status === "denied" || r.status === "canceled") && requestable(r.application_id) && <Button size="sm" variant="outline" aria-label={`Request ${r.application_name} again`} onClick={() => again(r)}>Request again</Button>}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
