"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { fieldClass } from "@/components/bits";
import { translateSamlConfig, type ConfigPlan, type SamlDraft, type Claim } from "@/lib/saml-config-translator";

export function SamlConfigTranslator({ current, onApply }: { current: SamlDraft & { claims: Claim[] }; onApply: (plan: ConfigPlan) => void }) {
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<{ key: string; plan: ConfigPlan } | null>(null);
  const [applied, setApplied] = useState(false);
  const key = JSON.stringify(current);
  return <details className="rounded-xl border bg-muted/20 p-4" data-testid="saml-config-translator">
    <summary className="cursor-pointer font-medium">Describe your SAML configuration</summary>
    <div className="mt-4 space-y-3">
      <p className="text-xs text-muted-foreground">Local translator for the explicit sentences below, one per line. It reports unsupported instructions and changes only this draft after review. Do not paste secrets.</p>
      <Label htmlFor="saml-config-request">Configuration requirements</Label>
      <textarea id="saml-config-request" rows={6} maxLength={4000} className={fieldClass + " h-auto"}
        placeholder={"Use persistent Name ID\nSign both\nSend email as User.Email required\nSend groups starting with app- as groups"}
        value={text} onChange={(e) => { setText(e.target.value); setPreview(null); setApplied(false); }} />
      <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">Supported examples</summary>
        <pre className="mt-2 overflow-auto whitespace-pre-wrap">{"Set ACS URL to https://workspace.slack.com/sso/saml\nSet SP entity ID to https://slack.com\nSet audience to https://slack.com\nUse persistent Name ID\nSign both\nSend email as User.Email required\nSend first name as first_name\nSend groups starting with app- as groups"}</pre>
      </details>
      <Button type="button" variant="outline" disabled={!text.trim()} onClick={() => { setPreview({ key, plan: translateSamlConfig(text) }); setApplied(false); }}>Review proposed changes</Button>
      {preview && <div className="space-y-3 rounded-lg border bg-background p-3">
        {preview.plan.errors.map((error) => <p key={error} role="alert" className="text-sm text-destructive">{error}</p>)}
        <h4 className="text-sm font-medium">Draft changes</h4>
        <ul className="list-disc space-y-1 pl-5 text-xs">{preview.plan.changes.map((change) => <li key={change}>{change}</li>)}</ul>
        <details className="text-xs"><summary className="cursor-pointer">Current draft</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(current, null, 2)}</pre></details>
        {preview.key !== key && <p role="status" className="text-xs">The form changed. Review the proposal again before applying.</p>}
        <Button type="button" disabled={applied || preview.key !== key || !!preview.plan.errors.length || !preview.plan.changes.length}
          onClick={() => { onApply(preview.plan); setApplied(true); }}>Apply to draft</Button>
      </div>}
      {applied && <p role="status" className="text-sm">Applied to the form only. Review attributes and save SAML settings when ready.</p>}
    </div>
  </details>;
}
