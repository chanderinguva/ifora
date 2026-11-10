"use client";

import { useEffect, useState } from "react";
import { Download, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge, td, th } from "@/components/bits";
import { API_URL } from "@/lib/api";
import { http, qs } from "@/lib/http";

type Row = { line: number; name: string; username: string; email: string; ok: boolean; created: boolean; errors: string[] };
type Result = { dry_run: boolean; total: number; valid: number; invalid: number; created: number; results: Row[]; outcome: string };
type Columns = { columns: { name: string; required: boolean; help: string }[]; ignored_on_import: string[]; max_rows: number; email_configured: boolean };

async function download(path: string, fallback: string) {
  const res = await fetch(`${API_URL}/api/v1${path}`, { credentials: "include" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({ detail: "Download failed" }))).detail ?? "Download failed");
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = fallback;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** Export (honours the list's search and status filter), the import template, and the import dialog with a dry run first. */
export function UserCsvButtons({ q, status, onToggleImport, onError }: { q: string; status: string; onToggleImport: () => void; onError: (m: string) => void }) {
  const run = (path: string, name: string) => download(path, name).catch((e) => onError(e.message));
  return (
    <>
      <Button variant="outline" data-testid="export-csv" onClick={() => run(`/admin/users/export.csv${qs({ q, status })}`, "users.csv")}><Download className="mr-1 h-4 w-4" /> Export CSV</Button>
      <Button variant="outline" data-testid="import-csv" onClick={onToggleImport}><Upload className="mr-1 h-4 w-4" /> Import CSV</Button>
    </>
  );
}

export function ImportPanel({ onClose, onImported, onError }: { onClose: () => void; onImported: () => void; onError: (m: string) => void }) {
  const template = () => download("/admin/users/import-template.csv", "users-import-template.csv").catch((e) => onError(e.message));
  const [cols, setCols] = useState<Columns | null>(null);
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [invite, setInvite] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { http<Columns>("/admin/users/import-columns").then(setCols).catch(() => {}); }, []);

  async function pick(f: File | undefined) {
    setResult(null); setError("");
    if (!f) return;
    setFileName(f.name);
    setText(await f.text());
  }
  async function send(dry: boolean) {
    setBusy(true); setError("");
    try {
      const r = await http<Result>("/admin/users/import", { method: "POST", body: { csv: text, dry_run: dry, send_invite: invite } });
      setResult(r);
      if (!dry) onImported();
    } catch (e) { setError(e instanceof Error ? e.message : "Import failed"); } finally { setBusy(false); }
  }
  const failed = result?.results.filter((r) => !r.ok) ?? [];
  return (
    <Card className="mb-6" data-testid="import-panel">
      <CardHeader><CardTitle>Import users from CSV</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">
          Required columns: first_name, last_name. Leave username and email empty to generate them from the naming convention. Existing users are never changed, and passwords and administrator rights cannot be imported.
          Up to {cols?.max_rows ?? 500} rows. <button type="button" className="underline underline-offset-4" onClick={template} data-testid="download-template">Download the template</button>.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <input type="file" accept=".csv,text/csv" aria-label="CSV file" data-testid="csv-file" onChange={(e) => pick(e.target.files?.[0])} />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={invite} disabled={!cols?.email_configured} onChange={(e) => setInvite(e.target.checked)} />
            Email each new user an invitation {!cols?.email_configured && "(email is not configured)"}
          </label>
        </div>
        {!invite && <p className="text-xs text-muted-foreground">Without invitations, new users are created as <b>staged</b>; invite them later from their page.</p>}
        {error && <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription></Alert>}
        <div className="flex gap-2">
          <Button disabled={!text || busy} onClick={() => send(true)} data-testid="csv-check">Check file</Button>
          <Button disabled={!result?.dry_run || result.valid === 0 || busy} onClick={() => send(false)} data-testid="csv-import">
            {result?.dry_run && result.valid > 0 ? `Import ${result.valid} user${result.valid === 1 ? "" : "s"}` : "Import"}
          </Button>
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>
        {result && (
          <div data-testid="csv-result" className="space-y-2">
            <p className="text-sm">
              {fileName}: {result.total} rows, <Badge tone="good">{result.valid} {result.dry_run ? "valid" : "created"}</Badge>{" "}
              {result.invalid > 0 && <Badge tone="bad">{result.invalid} with problems</Badge>}
              {!result.dry_run && ` (${result.outcome})`}
            </p>
            {failed.length > 0 && (
              <div className="max-h-64 overflow-auto rounded border">
                <table className="w-full"><thead className="border-b"><tr><th className={th}>Line</th><th className={th}>Row</th><th className={th}>Problem</th></tr></thead>
                  <tbody>{failed.map((r) => <tr key={r.line} className="border-b last:border-0"><td className={td}>{r.line}</td><td className={td}>{r.name || r.email || "(empty)"}</td><td className={td}>{r.errors.join("; ")}</td></tr>)}</tbody></table>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
