"use client";

import { useEffect, useRef, useState } from "react";
import { useBranding } from "@/lib/branding";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader, fieldClass } from "@/components/bits";
import { http } from "@/lib/http";
import { useDirty } from "@/lib/use-dirty";
import { SaveButton } from "@/components/save-button";

type Tpl = { key: string; label: string; category: string; live: boolean; required: string[]; subject: string; body: string; customised: boolean; default_subject: string; default_body: string; variables: Record<string, string> };

export default function EmailTemplates() {
  const { branding } = useBranding();
  const [items, setItems] = useState<Tpl[]>([]);
  const [mail, setMail] = useState(false);
  const [key, setKey] = useState("invite");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [preview, setPreview] = useState<{ subject: string; body: string; html: string } | null>(null);
  const [view, setView] = useState<"html" | "text">("html");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const cur = items.find((t) => t.key === key);
  const { dirty, markClean } = useDirty({ key, subject, body }, cur !== undefined);

  const load = (select?: string) => http<{ items: Tpl[]; mail_configured: boolean }>("/admin/email-templates").then((r) => {
    setItems(r.items); setMail(r.mail_configured);
    const t = r.items.find((x) => x.key === (select ?? key)) ?? r.items[0];
    if (t) { setKey(t.key); setSubject(t.subject); setBody(t.body); setPreview(null); markClean(); }
  }).catch((e) => setMsg({ ok: false, text: e.message }));
  const started = useRef(false);  // load once, so a duplicate response cannot overwrite a draft being typed
  useEffect(() => { if (started.current) return; started.current = true; load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const run = async (fn: () => Promise<unknown>, ok: string) => { setMsg(null); try { await fn(); setMsg({ ok: true, text: ok }); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); } };
  const draft = { subject, body };
  const insert = (v: string) => {
    const el = bodyRef.current; const tok = `{{${v}}}`;
    if (!el) { setBody(body + tok); return; }
    const a = el.selectionStart ?? body.length, z = el.selectionEnd ?? body.length;
    setBody(body.slice(0, a) + tok + body.slice(z));
  };

  return (
    <div className="max-w-3xl">
      <PageHeader title="Email templates" />
      <p className="mb-4 text-sm text-muted-foreground">Manage tenant-branded transactional identity notifications. Edit the safe plain-text content; Ifora generates matching accessible HTML and attaches your organization logo automatically.</p>
      <p className="mb-4 text-xs text-muted-foreground" data-testid="template-environment">Environment: <strong>{branding.environment_label}</strong>. Non-production notifications are marked in the subject and email header. Templates labeled Available for integration do not send until their identity flow is implemented.</p>
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
      {!mail && items.length > 0 && <Alert className="mb-4"><AlertDescription>Email is not configured on this server (SMTP_HOST and SMTP_FROM), so these emails are not sent yet and test emails are unavailable.</AlertDescription></Alert>}

      <div role="tablist" aria-label="Template" className="mb-4 flex flex-wrap gap-1 border-b">
        {items.map((t) => (
          <button key={t.key} role="tab" type="button" aria-selected={key === t.key} data-testid={`tpl-${t.key}`} onClick={() => load(t.key)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm ${key === t.key ? "border-primary font-medium" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
            {t.label}{t.customised ? " •" : ""}</button>
        ))}
      </div>

      {cur && (
        <Card><CardContent className="grid gap-4 pt-6" data-testid="tpl-form">
          <div className="text-xs text-muted-foreground"><strong>{cur.category}</strong> · {cur.live ? "Connected to a live identity flow" : "Available for integration (not sent automatically)"} · {cur.customised ? "Custom template" : "Built-in default"}</div>
          <div className="space-y-1"><Label htmlFor="t-subject">Subject</Label><Input id="t-subject" maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="t-body">Body</Label>
            <textarea id="t-body" ref={bodyRef} rows={10} maxLength={4000} className={fieldClass + " h-auto font-mono text-xs"} value={body} onChange={(e) => setBody(e.target.value)} /></div>
          <p className="text-xs text-muted-foreground">Required variables: {cur.required.length ? cur.required.map((x) => `{{${x}}}`).join(", ") : "None"}. HTML is always escaped and rendered by the shared email layout.</p>
          <div className="flex flex-wrap gap-2 text-xs" aria-label="Variables">
            {Object.entries(cur.variables).map(([v, d]) => <button key={v} type="button" title={d} onClick={() => insert(v)} className="rounded border px-2 py-1 font-mono hover:bg-accent">{`{{${v}}}`}</button>)}
          </div>
          <div className="flex flex-wrap gap-2">
            <SaveButton dirty={dirty} onClick={() => run(async () => { await http(`/admin/email-templates/${key}`, { method: "PUT", body: draft }); await load(key); }, "Template saved")} data-testid="tpl-save">Save</SaveButton>
            <Button variant="outline" onClick={async () => { setMsg(null); try { setPreview(await http(`/admin/email-templates/${key}/preview`, { method: "POST", body: draft })); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); } }} data-testid="tpl-preview">Preview</Button>
            <Button variant="outline" disabled={!mail} onClick={() => run(async () => { await http(`/admin/email-templates/${key}/send-test`, { method: "POST", body: draft }); }, "Test email sent to your own address")}>Send me a test</Button>
            {cur.customised && <Button variant="ghost" onClick={() => run(async () => { await http(`/admin/email-templates/${key}`, { method: "DELETE" }); await load(key); }, "Reset to the built-in text")} data-testid="tpl-restore">Reset to default</Button>}
          </div>
          {preview && (
            <div className="rounded-md border bg-muted/40 p-4 text-sm" data-testid="tpl-preview-out">
              <p className="mb-2 font-medium">{preview.subject}</p>
              <div className="mb-3 flex gap-2">
                <Button size="sm" variant={view === "html" ? "default" : "outline"} onClick={() => setView("html")}>HTML preview</Button>
                <Button size="sm" variant={view === "text" ? "default" : "outline"} onClick={() => setView("text")}>Plain text</Button>
              </div>
              {view === "html" ? (
                <iframe title="Rendered email preview" sandbox="" srcDoc={preview.html} className="h-[560px] w-full rounded border bg-white" data-testid="tpl-preview-html" />
              ) : (
                <pre className="whitespace-pre-wrap font-sans">{preview.body}</pre>
              )}
              <p className="mt-2 text-xs text-muted-foreground">Sample data only; previews never use live tokens. Email clients use inline-styled tables with a plain-text fallback.</p>
            </div>
          )}
        </CardContent></Card>
      )}
    </div>
  );
}
