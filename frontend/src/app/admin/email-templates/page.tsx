"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader, fieldClass } from "@/components/bits";
import { http } from "@/lib/http";

type Tpl = { key: string; label: string; subject: string; body: string; customised: boolean; default_subject: string; default_body: string; variables: Record<string, string> };

export default function EmailTemplates() {
  const [items, setItems] = useState<Tpl[]>([]);
  const [mail, setMail] = useState(false);
  const [key, setKey] = useState("invite");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [preview, setPreview] = useState<{ subject: string; body: string } | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const cur = items.find((t) => t.key === key);

  const load = (select?: string) => http<{ items: Tpl[]; mail_configured: boolean }>("/admin/email-templates").then((r) => {
    setItems(r.items); setMail(r.mail_configured);
    const t = r.items.find((x) => x.key === (select ?? key)) ?? r.items[0];
    if (t) { setKey(t.key); setSubject(t.subject); setBody(t.body); setPreview(null); }
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
      <p className="mb-4 text-sm text-muted-foreground">Edit the emails sent to people. Emails are plain text. Use the variables below; anything else in double braces is rejected.</p>
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
      {!mail && items.length > 0 && <Alert className="mb-4"><AlertDescription>Email is not configured on this server (SMTP_HOST and SMTP_FROM), so these emails are not sent yet and test emails are unavailable.</AlertDescription></Alert>}

      <div role="tablist" aria-label="Template" className="mb-4 flex gap-1 border-b">
        {items.map((t) => (
          <button key={t.key} role="tab" type="button" aria-selected={key === t.key} data-testid={`tpl-${t.key}`} onClick={() => load(t.key)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm ${key === t.key ? "border-primary font-medium" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
            {t.label}{t.customised ? " •" : ""}</button>
        ))}
      </div>

      {cur && (
        <Card><CardContent className="grid gap-4 pt-6" data-testid="tpl-form">
          <div className="space-y-1"><Label htmlFor="t-subject">Subject</Label><Input id="t-subject" maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="t-body">Body</Label>
            <textarea id="t-body" ref={bodyRef} rows={10} maxLength={4000} className={fieldClass + " h-auto font-mono text-xs"} value={body} onChange={(e) => setBody(e.target.value)} /></div>
          <div className="flex flex-wrap gap-2 text-xs" aria-label="Variables">
            {Object.entries(cur.variables).map(([v, d]) => <button key={v} type="button" title={d} onClick={() => insert(v)} className="rounded border px-2 py-1 font-mono hover:bg-accent">{`{{${v}}}`}</button>)}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => run(async () => { await http(`/admin/email-templates/${key}`, { method: "PUT", body: draft }); await load(key); }, "Template saved")} data-testid="tpl-save">Save</Button>
            <Button variant="outline" onClick={async () => { setMsg(null); try { setPreview(await http(`/admin/email-templates/${key}/preview`, { method: "POST", body: draft })); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); } }} data-testid="tpl-preview">Preview</Button>
            <Button variant="outline" disabled={!mail} onClick={() => run(async () => { await http(`/admin/email-templates/${key}/send-test`, { method: "POST", body: draft }); }, "Test email sent to your own address")}>Send me a test</Button>
            {cur.customised && <Button variant="ghost" onClick={() => run(async () => { await http(`/admin/email-templates/${key}`, { method: "DELETE" }); await load(key); }, "Reset to the built-in text")} data-testid="tpl-restore">Reset to default</Button>}
          </div>
          {preview && (
            <div className="rounded-md border bg-muted/40 p-4 text-sm" data-testid="tpl-preview-out">
              <p className="mb-2 font-medium">{preview.subject}</p>
              <pre className="whitespace-pre-wrap font-sans">{preview.body}</pre>
              <p className="mt-2 text-xs text-muted-foreground">Sample data: first name Alex, a placeholder link.</p>
            </div>
          )}
        </CardContent></Card>
      )}
    </div>
  );
}
