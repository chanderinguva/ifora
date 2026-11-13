"use client";
import { createContext, useContext, useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { fieldClass } from "@/components/bits";
import { PillInput } from "@/components/recipe-bits";
import type { Pill } from "@/lib/recipes";
type Text = { type: "plain_text" | "mrkdwn"; text: string };
export type SlackBlock = { type: string; text?: Text; fields?: Text[]; elements?: Text[] };
type Values = { ok: boolean; value?: unknown; error?: string }[];
export const SlackPreviewContext = createContext<null | { users: { id: number; email: string }[]; userId: string; setUser: (id: string) => void; render: (texts: string[]) => Promise<Values> }>(null);
function parse(value: string): SlackBlock[] {
  const blocks = JSON.parse(value);
  if (!Array.isArray(blocks) || blocks.length < 1 || blocks.length > 50 || new TextEncoder().encode(value).length > 16000) throw Error("Use a JSON array of 1–50 blocks, at most 16000 bytes.");
  for (const b of blocks) {
    if (!b || !["header", "section", "divider", "context"].includes(b.type)) throw Error("Use header, section, divider or context blocks.");
    for (const t of [b.text, ...(b.fields ?? []), ...(b.elements ?? [])].filter(Boolean)) if (!t || !["plain_text", "mrkdwn"].includes(t.type) || typeof t.text !== "string") throw Error("Each text object needs a type and text.");
  }
  return blocks;
}
function content(text: string, markdown: boolean) {
  if (!markdown) return text;
  // React text nodes only: no HTML injection, remote images or automatic mentions.
  return text.split(/(\*[^*\n]+\*|`[^`\n]+`|<https:\/\/[^>|\s]+\|[^>]+>)/g).map((part, i) => {
    if (part.startsWith("*") && part.endsWith("*")) return <strong key={i}>{part.slice(1, -1)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i} className="rounded bg-muted px-1">{part.slice(1, -1)}</code>;
    const link = /^<(https:\/\/[^>|\s]+)\|([^>]+)>$/.exec(part);
    if (link) return <a key={i} href={link[1]} rel="noreferrer noopener" target="_blank" className="text-primary underline">{link[2]}</a>;
    return part;
  });
}
export function SlackBlocksPreview({ blocks }: { blocks: SlackBlock[] }) {
  return <div className="space-y-3 rounded-lg border bg-background p-4" aria-label="Block Kit preview">{blocks.map((b, i) => <div key={i}>
    {b.type === "divider" ? <hr /> : <>
      {b.text && <div className={"whitespace-pre-wrap break-words " + (b.type === "header" ? "text-base font-semibold" : "text-sm")}>{content(b.text.text, b.text.type === "mrkdwn")}</div>}
      {b.fields && <div className="grid grid-cols-2 gap-3">{b.fields.map((t, j) => <div key={j} className="whitespace-pre-wrap break-words text-sm">{content(t.text, t.type === "mrkdwn")}</div>)}</div>}
      {b.elements && <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">{b.elements.map((t, j) => <span key={j} className="whitespace-pre-wrap break-words">{content(t.text, t.type === "mrkdwn")}</span>)}</div>}
    </>}
  </div>)}</div>;
}
const text = (value = "Message", plain = false): Text => ({ type: plain ? "plain_text" : "mrkdwn", text: value });
export function SlackBlocksEditor({ value, onChange, pills, payload }: { value: string; onChange: (v: string) => void; pills: Pill[]; payload: boolean }) {
  const sample = useContext(SlackPreviewContext);
  const [advanced, setAdvanced] = useState(false); const [busy, setBusy] = useState(false); const [note, setNote] = useState("");
  const [rendered, setRendered] = useState<{ key: string; blocks: SlackBlock[] } | null>(null);
  let blocks: SlackBlock[] = [], error = "";
  if (value) { try { blocks = parse(value); } catch (e) { error = e instanceof Error ? e.message : "Invalid block JSON"; } }
  const key = value + ":" + sample?.userId;
  const save = (next: SlackBlock[]) => { onChange(next.length ? JSON.stringify(next) : ""); setNote(""); };
  const update = (index: number, b: SlackBlock) => save(blocks.map((old, i) => i === index ? b : old));
  function field(t: Text, label: string, change: (t: Text) => void, plain = false) {
    return <div className="space-y-1"><Label>{label} (required)</Label><PillInput required label={label} multiline pills={pills} payload={payload} value={t.text} onChange={(v) => change({ ...t, text: v })} />{!plain && <select aria-label={`${label} formatting`} className={fieldClass} value={t.type} onChange={(e) => change({ ...t, type: e.target.value as Text["type"] })}><option value="mrkdwn">Slack formatting</option><option value="plain_text">Plain text</option></select>}</div>;
  }
  return <section className="space-y-3 border-t pt-3" aria-label="Slack message design">
    <Label htmlFor="slack-message-format">Message format</Label><select id="slack-message-format" className={fieldClass} value={value ? "blocks" : "text"} onChange={(e) => { if (e.target.value === "blocks") save([{ type: "section", text: text("Your message") }]); else if (window.confirm("Remove the Block Kit layout? Your fallback message will become the message.")) onChange(""); }}><option value="text">Plain text / Slack formatting</option><option value="blocks">Block Kit layout</option></select>
    <p className="text-xs text-muted-foreground">The Message field above is required fallback text for notifications and screen readers. Include the important information there too.</p>
    {value && <>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />Advanced JSON editor</label>
      {advanced || error ? <div><Label htmlFor="slack-block-json">Blocks JSON</Label><textarea id="slack-block-json" className={fieldClass + " h-64 font-mono"} value={value} maxLength={16000} onChange={(e) => onChange(e.target.value)} /><p className="text-xs text-muted-foreground">Display-only blocks; no interactive elements or images. Datapills belong inside text values.</p></div> : blocks.map((b, i) => <div key={i} className="space-y-2 rounded-md border p-3">
        <div className="flex flex-wrap items-center gap-2"><strong className="mr-auto text-sm">{i + 1}. {b.type === "section" && b.fields ? "Fields" : b.type}</strong><Button type="button" variant="outline" size="sm" disabled={i === 0} aria-label={`Move block ${i + 1} up`} onClick={() => { const next = [...blocks]; [next[i - 1], next[i]] = [next[i], next[i - 1]]; save(next); }}>↑</Button><Button type="button" variant="outline" size="sm" disabled={i === blocks.length - 1} aria-label={`Move block ${i + 1} down`} onClick={() => { const next = [...blocks]; [next[i + 1], next[i]] = [next[i], next[i + 1]]; save(next); }}>↓</Button><Button type="button" variant="ghost" size="sm" aria-label={`Remove block ${i + 1}`} onClick={() => save(blocks.filter((_, n) => n !== i))}>Remove</Button></div>
        {b.text && field(b.text, `Block ${i + 1} text`, (t) => update(i, { ...b, text: t }), b.type === "header")}
        {(b.fields ?? b.elements)?.map((t, j) => <div key={j} className="space-y-1">{field(t, `Block ${i + 1} field ${j + 1}`, (next) => update(i, { ...b, [b.fields ? "fields" : "elements"]: (b.fields ?? b.elements)!.map((v, n) => n === j ? next : v) }))}<Button type="button" variant="ghost" size="sm" disabled={(b.fields ?? b.elements)!.length === 1} onClick={() => update(i, { ...b, [b.fields ? "fields" : "elements"]: (b.fields ?? b.elements)!.filter((_, n) => n !== j) })}>Remove field</Button></div>)}
        {(b.fields || b.elements) && <Button type="button" variant="outline" size="sm" disabled={(b.fields ?? b.elements)!.length >= 10} onClick={() => update(i, { ...b, [b.fields ? "fields" : "elements"]: [...(b.fields ?? b.elements)!, text("New field")] })}>Add field</Button>}
      </div>)}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {!error && <div className="flex flex-wrap gap-2">{["Header", "Section", "Fields", "Divider", "Context"].map((kind) => <Button key={kind} type="button" variant="outline" size="sm" disabled={blocks.length >= 50} onClick={() => save([...blocks, kind === "Header" ? { type: "header", text: text("Alert title", true) } : kind === "Divider" ? { type: "divider" } : kind === "Fields" ? { type: "section", fields: [text("*Label*\nValue")] } : kind === "Context" ? { type: "context", elements: [text("Ifora")] } : { type: "section", text: text() }])}>Add {kind.toLowerCase()}</Button>)}</div>}
      {!error && <><h4 className="text-sm font-medium">Layout preview</h4><SlackBlocksPreview blocks={rendered?.key === key ? rendered.blocks : blocks} /><p className="text-xs text-muted-foreground">Approximate layout; Slack controls final rendering. Previewing never sends a message. Earlier-step output datapills are unavailable in sample preview.</p>
        {sample && <div className="space-y-2"><Label htmlFor="block-sample-user">Sample user for message preview</Label><select id="block-sample-user" className={fieldClass} value={sample.userId} onChange={(e) => sample.setUser(e.target.value)}><option value="">Choose a sample user…</option>{sample.users.map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}</select><Button type="button" disabled={busy} onClick={async () => {
          setBusy(true); setNote("");
          try {
            const texts = blocks.flatMap((b) => [b.text, ...(b.fields ?? []), ...(b.elements ?? [])].filter(Boolean).map((t) => t!.text));
            const result: Values = []; for (let n = 0; n < texts.length; n += 20) result.push(...await sample.render(texts.slice(n, n + 20)));
            if (result.some((r) => !r.ok)) throw Error(result.find((r) => !r.ok)?.error ?? "Preview failed");
            let n = 0; const map = (t: Text) => ({ ...t, text: String(result[n++].value ?? "") });
            const next = blocks.map((b) => ({ ...b, ...(b.text ? { text: map(b.text) } : {}), ...(b.fields ? { fields: b.fields.map(map) } : {}), ...(b.elements ? { elements: b.elements.map(map) } : {}) }));
            setRendered({ key, blocks: next }); setNote("Sample values rendered. No message sent.");
          } catch (e) { setNote(e instanceof Error ? e.message : "Preview failed"); } finally { setBusy(false); }
        }}>{busy ? "Rendering…" : "Preview with sample data"}</Button></div>}
      </>}
      {note && <p role="status" className="text-sm">{note}</p>}
    </>}
  </section>;
}
