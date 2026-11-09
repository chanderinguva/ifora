"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, Plus, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fieldClass, td, th } from "@/components/bits";
import { RecipeTabs } from "@/components/recipe-bits";
import { API_URL } from "@/lib/api";
import { http, qs } from "@/lib/http";

type Column = { name: string; type: "text" | "number" | "boolean" | "date" };
type Table = { id: number; name: string; description: string | null; columns: Column[]; key_column: string | null; admin_managed: boolean; row_count: number; used_by?: string[] };
type Row = { id: number; values: Record<string, unknown> };
type Msg = { ok: boolean; text: string } | null;

const PAGE = 50;
const show = (v: unknown) => (v === null || v === undefined ? "" : typeof v === "boolean" ? (v ? "true" : "false") : String(v));

export default function LookupTablesPage() {
  const [tables, setTables] = useState<Table[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);

  const load = useCallback(() => {
    http<{ items: Table[] }>("/admin/lookup-tables").then((r) => setTables(r.items)).catch((e) => setMsg({ ok: false, text: e.message }));
  }, []);
  useEffect(load, [load]);
  const table = tables?.find((t) => t.id === selected) ?? null;

  return (
    <div>
      <PageHeader title="Recipes">
        <Button onClick={() => { setCreating(true); setSelected(null); }} data-testid="new-table"><Plus className="mr-1 h-4 w-4" /> New lookup table</Button>
      </PageHeader>
      <RecipeTabs />
      <p className="mb-4 max-w-2xl text-sm text-muted-foreground">
        Small tables recipes can read with a <b>Look up a row</b> step, for example department to group, or the users a recipe has already handled.
        An <b>administrator-managed</b> table is only changed here, so decisions can safely be based on it. A table recipes can write to is for
        bookkeeping: what a recipe reads back from it counts as user-editable text.
      </p>
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
        <Card><CardContent className="p-2" data-testid="table-list">
          {tables === null ? <p className="p-3 text-sm text-muted-foreground">Loading…</p> : tables.length === 0 ? <p className="p-3 text-sm text-muted-foreground">No lookup tables yet.</p> : (
            <ul>{tables.map((t) => (
              <li key={t.id}>
                <button type="button" onClick={() => { setSelected(t.id); setCreating(false); setMsg(null); }}
                  className={"w-full rounded-md px-3 py-2 text-left text-sm hover:bg-muted " + (t.id === selected ? "bg-muted font-medium" : "")}>
                  <div className="flex items-center justify-between gap-2"><span className="truncate">{t.name}</span><span className="text-xs text-muted-foreground">{t.row_count}</span></div>
                  {!t.admin_managed && <span className="text-xs text-muted-foreground">recipes can write</span>}
                </button>
              </li>))}</ul>
          )}
        </CardContent></Card>

        <div>
          {creating && <NewTable onDone={(id) => { setCreating(false); load(); if (id) setSelected(id); }} onError={(text) => setMsg({ ok: false, text })} />}
          {table && <TableView key={table.id} table={table} onChanged={load} onDeleted={() => { setSelected(null); load(); }} setMsg={setMsg} />}
          {!creating && !table && <p className="text-sm text-muted-foreground">Choose a table, or create one.</p>}
        </div>
      </div>
    </div>
  );
}

function NewTable({ onDone, onError }: { onDone: (id?: number) => void; onError: (t: string) => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [cols, setCols] = useState<Column[]>([{ name: "code", type: "text" }, { name: "value", type: "text" }]);
  const [key, setKey] = useState("code");
  const [managed, setManaged] = useState(true);
  const setCol = (i: number, p: Partial<Column>) => setCols(cols.map((c, j) => (j === i ? { ...c, ...p } : c)));
  async function save() {
    try {
      const t = await http<Table>("/admin/lookup-tables", { method: "POST", body: { name, description: description || null, columns: cols, key_column: key || null, admin_managed: managed } });
      onDone(t.id);
    } catch (e) { onError(e instanceof Error ? e.message : "Failed"); }
  }
  return (
    <Card className="mb-4" data-testid="table-editor"><CardContent className="space-y-3 pt-6">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1"><Label htmlFor="lt-name">Name</Label><Input id="lt-name" value={name} maxLength={40} placeholder="cost_centres" onChange={(e) => setName(e.target.value)} />
          <p className="text-xs text-muted-foreground">Recipes refer to the table by this name; it cannot be renamed.</p></div>
        <div className="space-y-1"><Label htmlFor="lt-desc">Description</Label><Input id="lt-desc" value={description} maxLength={300} onChange={(e) => setDescription(e.target.value)} /></div>
      </div>
      <div className="space-y-2"><Label>Columns (up to 20)</Label>
        {cols.map((c, i) => (
          <div key={i} className="flex gap-2">
            <Input aria-label={`Column ${i + 1} name`} value={c.name} maxLength={40} onChange={(e) => setCol(i, { name: e.target.value })} />
            <select aria-label={`Column ${i + 1} type`} className={fieldClass + " w-36"} value={c.type} onChange={(e) => setCol(i, { type: e.target.value as Column["type"] })}>
              <option value="text">Text</option><option value="number">Number</option><option value="boolean">Yes / no</option><option value="date">Date</option>
            </select>
            <Button type="button" variant="outline" size="sm" aria-label={`Remove column ${i + 1}`} disabled={cols.length < 2} onClick={() => setCols(cols.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>
          </div>))}
        <Button type="button" variant="secondary" size="sm" disabled={cols.length >= 20} onClick={() => setCols([...cols, { name: "", type: "text" }])}>Add column</Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1"><Label htmlFor="lt-key">Key column</Label>
          <select id="lt-key" className={fieldClass} value={key} onChange={(e) => setKey(e.target.value)}>
            <option value="">None (rows can only be added)</option>{cols.filter((c) => c.name).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
          <p className="text-xs text-muted-foreground">Values are unique, and recipes can update or delete a row by its key.</p></div>
        <div className="space-y-1"><Label htmlFor="lt-managed">Who can change rows</Label>
          <select id="lt-managed" className={fieldClass} value={managed ? "admin" : "recipes"} onChange={(e) => setManaged(e.target.value === "admin")}>
            <option value="admin">Only administrators (safe for decisions)</option><option value="recipes">Administrators and recipes</option>
          </select></div>
      </div>
      <div className="flex gap-2"><Button onClick={save}>Create table</Button><Button variant="outline" onClick={() => onDone()}>Cancel</Button></div>
    </CardContent></Card>
  );
}

function TableView({ table, onChanged, onDeleted, setMsg }: { table: Table; onChanged: () => void; onDeleted: () => void; setMsg: (m: Msg) => void }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState<{ id: number | null; values: Record<string, string> } | null>(null);
  const [importing, setImporting] = useState(false);
  const [csv, setCsv] = useState("");
  const [mode, setMode] = useState<"append" | "replace">("append");

  const load = useCallback(() => {
    http<{ items: Row[]; total: number }>(`/admin/lookup-tables/${table.id}/rows${qs({ q, limit: PAGE, offset })}`).then((r) => { setRows(r.items); setTotal(r.total); }).catch((e) => setMsg({ ok: false, text: e.message }));
  }, [table.id, q, offset, setMsg]);
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); }, [load]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); load(); onChanged(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }
  const startEdit = (r: Row | null) => setEdit({ id: r?.id ?? null, values: Object.fromEntries(table.columns.map((c) => [c.name, r ? show(r.values[c.name]) : ""])) });
  const saveRow = () => edit && run(async () => {
    const body = { values: edit.values };
    if (edit.id === null) await http(`/admin/lookup-tables/${table.id}/rows`, { method: "POST", body });
    else await http(`/admin/lookup-tables/${table.id}/rows/${edit.id}`, { method: "PUT", body });
    setEdit(null);
  }, "Row saved");

  async function exportCsv() {
    const res = await fetch(`${API_URL}/api/v1/admin/lookup-tables/${table.id}/export`, { credentials: "include" });
    if (!res.ok) { setMsg({ ok: false, text: `Export failed (${res.status})` }); return; }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await res.blob());
    a.download = `${table.name}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const input = (c: Column) => {
    const v = edit!.values[c.name] ?? "";
    const set = (x: string) => setEdit({ ...edit!, values: { ...edit!.values, [c.name]: x } });
    if (c.type === "boolean") return <select aria-label={c.name} className={fieldClass} value={v} onChange={(e) => set(e.target.value)}><option value="">(empty)</option><option value="true">yes</option><option value="false">no</option></select>;
    return <Input aria-label={c.name} type={c.type === "date" ? "date" : "text"} inputMode={c.type === "number" ? "decimal" : undefined} value={v} maxLength={500} onChange={(e) => set(e.target.value)} />;
  };

  return (
    <div data-testid="table-view">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold">{table.name}</h2>
        <Badge tone={table.admin_managed ? "good" : "info"}>{table.admin_managed ? "administrators only" : "recipes can write"}</Badge>
        <span className="text-sm text-muted-foreground">{table.row_count} rows · key: {table.key_column ?? "none"}</span>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="outline" onClick={exportCsv}><Download className="mr-1 h-4 w-4" />Export CSV</Button>
          <Button size="sm" variant="outline" onClick={() => setImporting(!importing)}><Upload className="mr-1 h-4 w-4" />Import CSV</Button>
          <Button size="sm" variant="outline" aria-label="Change who can write"
            onClick={() => run(() => http(`/admin/lookup-tables/${table.id}`, { method: "PUT", body: { admin_managed: !table.admin_managed } }), "Updated")}>
            {table.admin_managed ? "Let recipes write" : "Administrators only"}
          </Button>
          <Button size="sm" variant="outline" onClick={() => { if (window.confirm(`Delete the table ${table.name} and its rows?`)) run(async () => { await http(`/admin/lookup-tables/${table.id}`, { method: "DELETE" }); onDeleted(); }, "Table deleted"); }}>Delete</Button>
        </div>
      </div>
      {table.description && <p className="mb-2 text-sm text-muted-foreground">{table.description}</p>}
      {(table.used_by?.length ?? 0) > 0 && <p className="mb-2 text-xs text-muted-foreground">Used by: {table.used_by!.join(", ")}</p>}

      {importing && (
        <Card className="mb-3"><CardContent className="space-y-2 pt-4" data-testid="csv-import">
          <p className="text-xs text-muted-foreground">First line: <code>{table.columns.map((c) => c.name).join(",")}</code>. Dates are YYYY-MM-DD. Nothing is imported if any line is wrong. At most 5,000 rows per import.</p>
          <input type="file" accept=".csv,text/csv" aria-label="CSV file" onChange={async (e) => { const f = e.target.files?.[0]; if (f) setCsv(await f.text()); }} />
          <textarea aria-label="CSV text" className={fieldClass + " h-28 font-mono"} value={csv} onChange={(e) => setCsv(e.target.value)} />
          <div className="flex items-center gap-2">
            <select aria-label="Import mode" className={fieldClass + " w-64"} value={mode} onChange={(e) => setMode(e.target.value as "append" | "replace")}><option value="append">Add to the existing rows</option><option value="replace">Replace all rows</option></select>
            <Button size="sm" disabled={!csv.trim()} onClick={() => run(async () => { await http(`/admin/lookup-tables/${table.id}/import`, { method: "POST", body: { csv, mode } }); setCsv(""); setImporting(false); }, "Imported")}>Import</Button>
          </div>
        </CardContent></Card>)}

      <div className="mb-2 flex items-center gap-2">
        <Input aria-label="Search rows" className="max-w-xs" placeholder="Search…" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
        <Button size="sm" onClick={() => startEdit(null)} data-testid="add-row"><Plus className="mr-1 h-4 w-4" />Add row</Button>
      </div>

      <div className="overflow-x-auto rounded-md border">
        <table className="w-full" data-testid="rows-table">
          <thead className="bg-muted/50"><tr>{table.columns.map((c) => <th key={c.name} className={th}>{c.name}{c.name === table.key_column ? " 🔑" : ""}<span className="ml-1 font-normal normal-case">{c.type}</span></th>)}<th className={th} /></tr></thead>
          <tbody>
            {edit && edit.id === null && <tr className="border-t bg-muted/20" data-testid="row-editor">{table.columns.map((c) => <td key={c.name} className="px-2 py-2">{input(c)}</td>)}
              <td className="whitespace-nowrap px-2 py-2"><Button size="sm" onClick={saveRow}>Save</Button> <Button size="sm" variant="outline" onClick={() => setEdit(null)}>Cancel</Button></td></tr>}
            {rows.map((r) => edit?.id === r.id ? (
              <tr key={r.id} className="border-t bg-muted/20" data-testid="row-editor">{table.columns.map((c) => <td key={c.name} className="px-2 py-2">{input(c)}</td>)}
                <td className="whitespace-nowrap px-2 py-2"><Button size="sm" onClick={saveRow}>Save</Button> <Button size="sm" variant="outline" onClick={() => setEdit(null)}>Cancel</Button></td></tr>
            ) : (
              <tr key={r.id} className="border-t" data-testid="row">{table.columns.map((c) => <td key={c.name} className={td}>{show(r.values[c.name])}</td>)}
                <td className="whitespace-nowrap px-2 py-2 text-right">
                  <Button size="sm" variant="ghost" onClick={() => startEdit(r)}>Edit</Button>
                  <Button size="sm" variant="ghost" aria-label="Delete row" onClick={() => run(() => http(`/admin/lookup-tables/${table.id}/rows/${r.id}`, { method: "DELETE" }), "Row deleted")}><Trash2 className="h-4 w-4" /></Button></td></tr>
            ))}
            {rows.length === 0 && !edit && <tr><td colSpan={table.columns.length + 1} className="px-4 py-6 text-center text-sm text-muted-foreground">No rows.</td></tr>}
          </tbody>
        </table>
      </div>
      {total > PAGE && (
        <div className="mt-2 flex items-center gap-2 text-sm">
          <Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(offset - PAGE, 0))}>Previous</Button>
          <span>{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
          <Button size="sm" variant="outline" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</Button>
        </div>)}
    </div>
  );
}
