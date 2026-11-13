"use client";
import { useEffect, useState } from "react";
import { SlackBlocksPreview, type SlackBlock } from "@/components/recipe-editor/slack-blocks-editor";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldClass } from "@/components/bits";
import { http } from "@/lib/http";
import type { Definition } from "@/lib/recipes";
type Preview = { preview_id: string; destination: string; text: string; blocks?: SlackBlock[] | null };
export function SlackMessageTest({ id, definition, sample, allowed, save, onMessage }: {
  id: string; definition: Definition; sample: { user_id: number | null; group_id: number | null; payload: unknown };
  allowed: boolean; save: () => Promise<unknown>; onMessage: (ok: boolean, text: string) => void;
}) {
  const steps = definition.steps.filter((s) => s.type === "connector_action" && s.config.connector === "slack" && s.config.action === "post_message");
  const [step, setStep] = useState(""); const [destination, setDestination] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null); const [confirmed, setConfirmed] = useState(false); const [busy, setBusy] = useState(false);
  const sampleKey = JSON.stringify(sample);
  const definitionKey = JSON.stringify(definition);
  useEffect(() => { setPreview(null); setConfirmed(false); }, [definitionKey, sampleKey, step, destination]);
  if (!steps.length) return null;
  const selected = steps.some((s) => s.id === step) ? step : steps[0].id;
  return <section className="space-y-3 border-t pt-4" aria-label="Live Slack message test">
    <h3 className="font-medium">Send a Slack test message</h3>
    <p className="text-sm text-muted-foreground">Sends only this message step using the sample user above. Other steps and trigger filters do not run. Choose a test channel or Slack user ID the bot can access. Earlier-step datapills are unavailable.</p>
    <div className="grid gap-3 md:grid-cols-2">
      <div><Label htmlFor="slack-test-step">Message step (required)</Label><select id="slack-test-step" className={fieldClass} value={selected} disabled={!allowed || busy} onChange={(e) => setStep(e.target.value)}>{steps.map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}</select></div>
      <div><Label htmlFor="slack-test-destination">Test channel or user ID (required)</Label><Input id="slack-test-destination" required aria-required="true" placeholder="C0123456789 or U0123456789" value={destination} disabled={!allowed || busy} onChange={(e) => setDestination(e.target.value.trim())} /></div>
    </div>
    <Button disabled={!allowed || busy || !/^[CGDUW][A-Z0-9]{2,20}$/.test(destination)} onClick={async () => {
      setBusy(true); setPreview(null); setConfirmed(false);
      try { await save(); setPreview(await http<Preview>(`/admin/recipes/${id}/slack-test-preview`, { method: "POST", body: { ...sample, step_id: selected, destination } })); }
      catch (e) { onMessage(false, e instanceof Error ? e.message : "Preview failed"); } finally { setBusy(false); }
    }}>{busy ? "Working…" : "Preview test message"}</Button>
    {preview && <div className="space-y-3 rounded-md border p-4">
      <p className="text-sm font-medium">Destination: {preview.destination}</p>{preview.blocks && <SlackBlocksPreview blocks={preview.blocks} />}<p className="text-xs text-muted-foreground">Message / notification fallback</p><pre className="whitespace-pre-wrap break-words rounded bg-muted p-3 text-sm">{preview.text}</pre>
      <p className="text-xs text-muted-foreground">Rendered text; Slack applies formatting after delivery. Preview expires in five minutes. No production thread is used.</p>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={confirmed} disabled={busy} onChange={(e) => setConfirmed(e.target.checked)} />I confirm this destination and want to send this real test message.</label>
      <Button disabled={!confirmed || busy || !allowed} onClick={async () => {
        setBusy(true); const token = preview.preview_id; setPreview(null); setConfirmed(false);
        try { await http(`/admin/recipes/${id}/slack-test-send`, { method: "POST", body: { preview_id: token, confirmed: true } }); onMessage(true, `Test message sent to ${preview.destination}`); }
        catch (e) { onMessage(false, e instanceof Error ? e.message : "Delivery not confirmed; check Slack before sending again"); } finally { setBusy(false); }
      }}>Send test message</Button>
    </div>}
    {!allowed && <p className="text-sm text-muted-foreground">Only recipe managers can send live test messages.</p>}
  </section>;
}
