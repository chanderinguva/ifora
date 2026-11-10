"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader, fieldClass, td, th } from "@/components/bits";
import { http } from "@/lib/http";
import { useDirty } from "@/lib/use-dirty";
import { SaveButton } from "@/components/save-button";

type Zone = { id: number; name: string; cidrs: string[] };
const lines = (v: string) => v.split("\n").map((x) => x.trim()).filter(Boolean);

export default function NetworkZones() {
  const [zones, setZones] = useState<Zone[] | null>(null);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [name, setName] = useState("");
  const [cidrs, setCidrs] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const { dirty, markClean } = useDirty({ editing, name, cidrs }, editing !== null);

  const load = useCallback(() => { http<{ items: Zone[] }>("/admin/network-zones").then((r) => setZones(r.items)).catch((e) => setMsg({ ok: false, text: e.message })); }, []);
  useEffect(load, [load]);

  function open(z?: Zone) { setEditing(z ? z.id : "new"); setName(z?.name ?? ""); setCidrs(z?.cidrs.join("\n") ?? ""); setMsg(null); markClean(); }
  async function save() {
    try {
      const body = { name, cidrs: lines(cidrs) };
      if (editing === "new") await http("/admin/network-zones", { method: "POST", body });
      else await http(`/admin/network-zones/${editing}`, { method: "PUT", body });
      setEditing(null); setMsg({ ok: true, text: "Saved" }); load();
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }
  async function remove(z: Zone) {
    if (!confirm(`Delete the zone "${z.name}"?`)) return;
    try { await http(`/admin/network-zones/${z.id}`, { method: "DELETE" }); setMsg({ ok: true, text: "Deleted" }); load(); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }

  return (
    <div className="max-w-4xl">
      <PageHeader title="Network zones"><Button onClick={() => open()} data-testid="zone-new">Add zone</Button></PageHeader>
      <p className="mb-4 text-sm text-muted-foreground">A zone is a named set of IP ranges. Use zones in an application&apos;s authentication policy to allow or block sign-ins by network. The address comes from the connection to the server; behind a reverse proxy, configure the server&apos;s proxy-header handling so it sees real client addresses.</p>
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      {editing !== null && (
        <Card className="mb-6" data-testid="zone-form"><CardContent className="grid gap-3 pt-6">
          <div className="space-y-1"><Label htmlFor="z-name">Name</Label><Input id="z-name" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="z-cidrs">IP addresses or CIDR ranges (one per line)</Label>
            <textarea id="z-cidrs" rows={4} className={fieldClass} placeholder={"203.0.113.0/24\n2001:db8::/32"} value={cidrs} onChange={(e) => setCidrs(e.target.value)} /></div>
          <div className="flex gap-2"><SaveButton dirty={editing === "new" || dirty} disabled={!name.trim() || lines(cidrs).length === 0} onClick={save} data-testid="zone-save">Save</SaveButton><Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button></div>
        </CardContent></Card>
      )}

      <Card><CardContent className="overflow-x-auto p-0">
        <table className="w-full" data-testid="zones-table">
          <thead className="border-b"><tr><th className={th}>Name</th><th className={th}>Ranges</th><th className={th}></th></tr></thead>
          <tbody>
            {zones?.map((z) => (
              <tr key={z.id} className="border-b last:border-0">
                <td className={td + " font-medium"}>{z.name}</td>
                <td className={td + " font-mono text-xs"}>{z.cidrs.join(", ")}</td>
                <td className={td + " space-x-2 text-right"}>
                  <Button size="sm" variant="outline" onClick={() => open(z)}>Edit</Button>
                  <Button size="sm" variant="ghost" aria-label={`Delete ${z.name}`} onClick={() => remove(z)}>Delete</Button>
                </td>
              </tr>
            ))}
            {zones && zones.length === 0 && <tr><td className={td} colSpan={3}>No network zones yet.</td></tr>}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  );
}
