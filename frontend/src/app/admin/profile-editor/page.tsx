"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fieldClass, td, th } from "@/components/bits";
import { http } from "@/lib/http";
import { useDirty } from "@/lib/use-dirty";
import { SaveButton } from "@/components/save-button";
import type { ProfileAttribute } from "@/lib/types";

const TYPES: [string, string][] = [["string", "Text"], ["number", "Number"], ["boolean", "Yes / No"], ["enum", "Choice list"]];
const typeLabel = (t: string) => ({ string: "Text", number: "Number", boolean: "Yes / No", enum: "Choice list", timezone: "Time zone", locale: "Locale" } as Record<string, string>)[t] ?? t;
const slug = (v: string) => v.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^[0-9_]+/, "").slice(0, 50);
const blank = { key: "", display_name: "", description: "", data_type: "string", options: "", user_editable: false };

export default function ProfileEditorPage() {
  const [items, setItems] = useState<ProfileAttribute[] | null>(null);
  const [draft, setDraft] = useState<typeof blank | null>(null);
  const [edit, setEdit] = useState<{ key: string; display_name: string; description: string; options: string; user_editable: boolean; data_type: string } | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const { dirty, markClean } = useDirty(edit, edit !== null);

  const load = useCallback(() => {
    http<{ items: ProfileAttribute[] }>("/admin/profile-attributes").then((r) => setItems(r.items)).catch((e) => setMsg({ ok: false, text: e.message }));
  }, []);
  useEffect(load, [load]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); load(); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }
  const opts = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

  return (
    <div>
      <PageHeader title="Profile editor">
        <Button onClick={() => { setEdit(null); setDraft({ ...blank }); }}><Plus className="mr-1 h-4 w-4" /> Add attribute</Button>
      </PageHeader>
      <p className="mb-4 max-w-2xl text-sm text-muted-foreground">
        The user profile schema. Attributes that users can edit appear in their Account settings. Attributes only administrators can edit
        are also the ones group rules can use. Built-in attributes can be renamed or re-scoped but not deleted.
      </p>
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      {draft && (
        <Card className="mb-6" data-testid="attr-editor">
          <CardHeader><CardTitle>Add attribute</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2"><Label htmlFor="pa-name">Display name</Label>
                <Input id="pa-name" maxLength={100} value={draft.display_name}
                  onChange={(e) => setDraft({ ...draft, display_name: e.target.value, key: draft.key === slug(draft.display_name) ? slug(e.target.value) : draft.key })} /></div>
              <div className="space-y-2"><Label htmlFor="pa-key">Key</Label>
                <Input id="pa-key" maxLength={50} placeholder="lowercase_with_underscores" value={draft.key} onChange={(e) => setDraft({ ...draft, key: e.target.value.toLowerCase() })} /></div>
              <div className="space-y-2"><Label htmlFor="pa-type">Type</Label>
                <select id="pa-type" className={fieldClass} value={draft.data_type} onChange={(e) => setDraft({ ...draft, data_type: e.target.value })}>
                  {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select></div>
              <div className="space-y-2"><Label htmlFor="pa-desc">Description (optional)</Label>
                <Input id="pa-desc" maxLength={500} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></div>
            </div>
            {draft.data_type === "enum" && (
              <div className="space-y-2"><Label htmlFor="pa-opts">Choices (one per line)</Label>
                <textarea id="pa-opts" rows={4} className={fieldClass} value={draft.options} onChange={(e) => setDraft({ ...draft, options: e.target.value })} /></div>
            )}
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={draft.user_editable} onChange={(e) => setDraft({ ...draft, user_editable: e.target.checked })} />
              Users can edit this in their own Account settings (then group rules cannot use it)
            </label>
            <div className="flex gap-2">
              <Button disabled={!draft.key || !draft.display_name.trim()}
                onClick={() => run(async () => {
                  await http("/admin/profile-attributes", { method: "POST", body: {
                    key: draft.key, display_name: draft.display_name, description: draft.description || null, data_type: draft.data_type,
                    enum_options: draft.data_type === "enum" ? opts(draft.options) : null, user_editable: draft.user_editable } });
                  setDraft(null);
                }, "Attribute added")}>Save attribute</Button>
              <Button variant="ghost" onClick={() => setDraft(null)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {edit && (
        <Card className="mb-6" data-testid="attr-edit">
          <CardHeader><CardTitle>Edit “{edit.key}”</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2"><Label htmlFor="pe-name">Display name</Label>
              <Input id="pe-name" maxLength={100} value={edit.display_name} onChange={(e) => setEdit({ ...edit, display_name: e.target.value })} /></div>
            <div className="space-y-2"><Label htmlFor="pe-desc">Description</Label>
              <Input id="pe-desc" maxLength={500} value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></div>
            {edit.data_type === "enum" && (
              <div className="space-y-2"><Label htmlFor="pe-opts">Choices (one per line)</Label>
                <textarea id="pe-opts" rows={4} className={fieldClass} value={edit.options} onChange={(e) => setEdit({ ...edit, options: e.target.value })} /></div>
            )}
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={edit.user_editable} onChange={(e) => setEdit({ ...edit, user_editable: e.target.checked })} />
              Users can edit this in their own Account settings
            </label>
            <div className="flex gap-2">
              <SaveButton dirty={dirty} onClick={() => run(async () => {
                await http(`/admin/profile-attributes/${edit.key}`, { method: "PATCH", body: {
                  display_name: edit.display_name, description: edit.description, user_editable: edit.user_editable,
                  ...(edit.data_type === "enum" ? { enum_options: opts(edit.options) } : {}) } });
                setEdit(null);
              }, "Attribute updated")}>Save changes</SaveButton>
              <Button variant="ghost" onClick={() => setEdit(null)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full" data-testid="attr-table">
            <thead className="border-b"><tr><th className={th}>Attribute</th><th className={th}>Key</th><th className={th}>Type</th><th className={th}>Who edits</th><th className={th}></th></tr></thead>
            <tbody>
              {items?.map((a) => (
                <tr key={a.key} className="border-b last:border-0 align-top" data-testid={`attr-row-${a.key}`}>
                  <td className={td}><span className="font-medium">{a.display_name}</span>{a.built_in && <span className="ml-2"><Badge tone="neutral">built-in</Badge></span>}
                    {a.description && <div className="text-xs text-muted-foreground">{a.description}</div>}</td>
                  <td className={td + " font-mono text-xs"}>{a.key}</td>
                  <td className={td}>{typeLabel(a.data_type)}{a.enum_options && <div className="text-xs text-muted-foreground">{a.enum_options.join(", ")}</div>}</td>
                  <td className={td}>{a.user_editable ? <Badge tone="neutral">User</Badge> : <Badge tone="good">Admin only · rule-ready</Badge>}</td>
                  <td className={td + " space-x-2 text-right whitespace-nowrap"}>
                    <Button size="sm" variant="outline" onClick={() => { setDraft(null); setEdit({ key: a.key, display_name: a.display_name, description: a.description ?? "", options: (a.enum_options ?? []).join("\n"), user_editable: a.user_editable, data_type: a.data_type }); markClean(); }}>Edit</Button>
                    {!a.built_in && (
                      <Button size="sm" variant="outline" aria-label={`Delete ${a.key}`}
                        onClick={() => { if (confirm(`Delete "${a.display_name}"? The values stored on every user are removed.`)) run(() => http(`/admin/profile-attributes/${a.key}`, { method: "DELETE" }), "Attribute deleted"); }}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
