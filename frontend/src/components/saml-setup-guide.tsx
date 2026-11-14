"use client";

import { useState } from "react";
import { BookOpen, Copy, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { fieldClass } from "@/components/bits";
import { SAML_GUIDES, suggestedSamlGuide } from "@/lib/saml-guides";

type Idp = { entity_id: string; sso_url: string; metadata_url: string };
type Saved = { sp_entity_id: string; acs_url: string; audience: string | null; name_id_format: string; signing: string;
  attribute_mappings: { name: string; source: string; required?: boolean }[];
  idp: Idp & { certificate_pem: string } };

export function SamlSetupGuide({ idp, provider, dirty }: { idp: Idp; provider: Saved | null; dirty: boolean }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const guide = SAML_GUIDES.find((g) => g.id === (selected ?? suggestedSamlGuide(provider?.sp_entity_id ?? "", provider?.acs_url ?? "")))!;
  const values = [
    { label: guide.id === "slack" ? "SAML 2.0 Endpoint URL" : "Identity provider SSO URL", value: idp.sso_url },
    { label: "Identity Provider Issuer URL / Entity ID", value: idp.entity_id },
    { label: "Metadata URL", value: idp.metadata_url },
    { label: guide.id === "slack" ? "Service Provider Issuer URL" : "Saved SP entity ID", value: provider?.sp_entity_id },
    { label: "Saved ACS URL", value: provider?.acs_url },
    { label: "Public X.509 signing certificate (PEM)", value: provider?.idp.certificate_pem },
  ];
  return <details className="rounded-xl border bg-muted/20" data-testid="saml-setup-guide">
    <summary className="flex cursor-pointer items-center gap-2 p-4 font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <BookOpen className="h-4 w-4" aria-hidden /> View setup instructions
    </summary>
    <div className="space-y-5 border-t p-4">
      <div className="space-y-2"><Label htmlFor="saml-guide-vendor">Application guide</Label>
        <select id="saml-guide-vendor" className={fieldClass} value={guide.id} onChange={(e) => { setSelected(e.target.value); setNotice(""); }}>
          {SAML_GUIDES.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
        </select>
        <p className="text-xs text-muted-foreground">Last reviewed {guide.reviewed}. Selecting a guide does not change your application settings.</p>
      </div>
      {(dirty || !provider) && <p role="status" className="rounded-md border border-warn/40 p-3">
        {provider ? "You have unsaved changes. These instructions show saved settings; save before copying values to the application." : "Save your SAML configuration first to obtain the application's signing certificate and saved SP values."}
      </p>}
      <section><h3 className="mb-2 font-semibold">Before you begin</h3><ul className="list-disc space-y-1 pl-5">{guide.prerequisites.map((p) => <li key={p}>{p}</li>)}</ul></section>
      <section><h3 className="mb-2 font-semibold">Configure and test</h3><ol className="list-decimal space-y-3 pl-5">{guide.steps.map((p) => <li key={p}>{p}</li>)}</ol></section>
      {guide.id === "slack" && <div className="overflow-x-auto rounded-md border"><table className="w-full text-left text-xs">
        <caption className="p-3 text-left font-medium">Slack configuration checks against saved settings</caption>
        <thead><tr><th className="p-2">Requirement</th><th className="p-2">Saved value</th></tr></thead>
        <tbody>
          <tr className="border-t"><td className="p-2">Persistent Name ID</td><td className="p-2">{provider?.name_id_format ?? "Not saved"}</td></tr>
          <tr className="border-t"><td className="p-2">Sign response (or both)</td><td className="p-2">{provider?.signing ?? "Not saved"}</td></tr>
          <tr className="border-t"><td className="p-2">Required User.Email ← email</td><td className="p-2">{provider?.attribute_mappings.some((m) => m.name === "User.Email" && m.source === "email" && m.required) ? "Configured" : "Review attribute mapping"}</td></tr>
        </tbody></table></div>}
      <section className="space-y-3"><h3 className="font-semibold">Copy saved configuration</h3>
        {values.map(({ label, value }) => <div key={label} className="min-w-0 space-y-1 rounded-lg border bg-background p-3">
          <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium">{label}</span>
            <Button type="button" variant="outline" size="sm" disabled={!value || dirty} aria-label={"Copy " + label} onClick={async () => {
              try { await navigator.clipboard.writeText(value!); setNotice(label + " copied."); }
              catch { setNotice("Clipboard unavailable. Select and copy the displayed value manually."); }
            }}><Copy className="mr-1 h-3.5 w-3.5" aria-hidden />Copy</Button>
          </div>
          <pre className="max-h-44 overflow-auto whitespace-pre-wrap break-all text-xs">{value || "Available after saving SAML settings"}</pre>
        </div>)}
        <p role="status" aria-live="polite" className="text-xs text-muted-foreground">{notice}</p>
      </section>
      <section><h3 className="mb-2 font-semibold">Troubleshooting</h3>{guide.troubleshooting.map((p) => <p key={p}>{p}</p>)}</section>
      {guide.sources.length > 0 && <section className="space-y-2"><h3 className="font-semibold">Official documentation</h3>{guide.sources.map((s) => <a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 underline underline-offset-4">{s.label}<ExternalLink className="h-3.5 w-3.5" aria-hidden /></a>)}</section>}
    </div>
  </details>;
}
