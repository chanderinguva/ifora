"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/bits";
import { Logo } from "@/components/logo";
import { http } from "@/lib/http";
import { logoUrl, themeCss, useBranding, type Branding } from "@/lib/branding";

export default function BrandingPage() {
  const { branding, reload } = useBranding();
  const [b, setB] = useState<Branding | null>(null);
  const [form, setForm] = useState({ display_name: "", primary_color: "", tagline: "" });
  const [rev, setRev] = useState(0);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const apply = (x: Branding) => { setB(x); setForm({ display_name: x.custom_name ? x.display_name : "", primary_color: x.primary_color ?? "", tagline: x.tagline ?? "" }); };
  const started = useRef(false);  // load once: a second (dev double-effect) response would overwrite what the admin has typed
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    http<Branding>("/admin/branding").then(apply).catch((e) => setMsg({ ok: false, text: e.message }));
  }, []);

  async function save() {
    setMsg(null);
    try { apply(await http<Branding>("/admin/branding", { method: "PUT", body: { display_name: form.display_name || null, primary_color: form.primary_color || null, tagline: form.tagline || null } })); reload(); setMsg({ ok: true, text: "Branding saved" }); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }
  async function upload(f: File) {
    if (f.size > 200 * 1024) { setMsg({ ok: false, text: "The logo must be at most 200 KB" }); return; }
    const bytes = new Uint8Array(await f.arrayBuffer());
    let bin = ""; bytes.forEach((x) => { bin += String.fromCharCode(x); });
    try { apply(await http<Branding>("/admin/branding/logo", { method: "PUT", body: { data: btoa(bin) } })); setRev((n) => n + 1); reload(); setMsg({ ok: true, text: "Logo saved" }); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }
  async function removeLogo() {
    try { apply(await http<Branding>("/admin/branding/logo", { method: "DELETE" })); setRev((n) => n + 1); reload(); setMsg({ ok: true, text: "Logo removed" }); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }

  const colorOk = !form.primary_color || /^#[0-9a-fA-F]{6}$/.test(form.primary_color);
  const preview = themeCss(colorOk ? form.primary_color || null : null).replace(":root", "[data-brand-preview]").replace(".dark{", ".dark [data-brand-preview]{");

  return (
    <div className="max-w-3xl">
      <PageHeader title="Branding" />
      <p className="mb-4 text-sm text-muted-foreground">Your name, logo and colour appear on the sign-in page, the sidebar and in emails. Leave a field empty to use the Ifora default.</p>
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      {!b ? <p className="mb-6 text-sm text-muted-foreground">Loading…</p> : (<>
      <Card className="mb-6"><CardContent className="grid gap-4 pt-6" data-testid="branding-form">
        <div className="space-y-1"><Label htmlFor="b-name">Organization name</Label><Input id="b-name" maxLength={60} placeholder="Ifora" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></div>
        <div className="space-y-1"><Label htmlFor="b-tag">Sign-in page message</Label><Input id="b-tag" maxLength={160} placeholder="Shown above the sign-in form" value={form.tagline} onChange={(e) => setForm({ ...form, tagline: e.target.value })} /></div>
        <div className="space-y-1"><Label htmlFor="b-color">Primary colour</Label>
          <div className="flex items-center gap-2">
            <input type="color" aria-label="Pick a colour" className="h-10 w-12 cursor-pointer rounded border bg-background" value={colorOk && form.primary_color ? form.primary_color : "#0f172a"} onChange={(e) => setForm({ ...form, primary_color: e.target.value })} />
            <Input id="b-color" className="w-40 font-mono" placeholder="#1a73e8" maxLength={7} value={form.primary_color} onChange={(e) => setForm({ ...form, primary_color: e.target.value })} />
            {form.primary_color && <Button variant="ghost" size="sm" onClick={() => setForm({ ...form, primary_color: "" })}>Use default</Button>}
          </div>
          {!colorOk && <p className="text-xs text-destructive">Use a six-digit hex colour such as #1a73e8.</p>}
          <p className="text-xs text-muted-foreground">Buttons and highlights use it. Text on top switches between dark and light automatically; in the dark theme a very dark colour is lightened so it stays visible.</p></div>
        <div><Button onClick={save} disabled={!colorOk} data-testid="branding-save">Save</Button></div>
      </CardContent></Card>

      <Card className="mb-6" data-testid="logo-card">
        <CardHeader><CardTitle>Logo</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap items-center gap-4 text-sm">
          {b?.has_logo
            // eslint-disable-next-line @next/next/no-img-element
            ? <img key={rev} src={`${logoUrl(b)}&r=${rev}`} alt="Current logo" className="h-16 w-16 rounded border object-contain" />
            : <span className="flex h-16 w-16 items-center justify-center rounded border text-xs text-muted-foreground">Default</span>}
          <div className="space-y-2">
            <p className="text-muted-foreground">PNG, JPEG or WebP, at most 200 KB; square works best. SVG is not accepted.</p>
            <div className="flex flex-wrap items-center gap-2">
              <input type="file" aria-label="Upload logo" accept="image/png,image/jpeg,image/webp" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) upload(f); }} />
              {b?.has_logo && <Button size="sm" variant="outline" onClick={removeLogo}>Remove logo</Button>}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card data-testid="branding-preview">
        <CardHeader><CardTitle>Preview</CardTitle></CardHeader>
        <CardContent>
          {preview && <style>{preview}</style>}
          <div data-brand-preview className="space-y-3 rounded-lg border p-4">
            <Logo />
            {form.tagline && <p className="text-sm text-muted-foreground">{form.tagline}</p>}
            <button type="button" className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">Sign In</button>
            <p className="text-xs text-muted-foreground">Name shown now: {branding.display_name}. The preview button uses the colour typed above.</p>
          </div>
        </CardContent>
      </Card>
      </>)}
    </div>
  );
}
