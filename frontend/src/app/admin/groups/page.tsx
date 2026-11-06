"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, Pager, td, th } from "@/components/bits";
import { http, qs, type Page } from "@/lib/http";
import type { Group } from "@/lib/types";

const PAGE_SIZE = 15;

export default function GroupsPage() {
  const [data, setData] = useState<Page<Group> | null>(null);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", description: "" });

  const load = useCallback(() => {
    http<Page<Group>>(`/admin/groups${qs({ q, page, page_size: PAGE_SIZE })}`).then(setData).catch((e) => setError(e.message));
  }, [q, page]);
  useEffect(() => {
    const t = setTimeout(load, 200);
    return () => clearTimeout(t);
  }, [load]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await http("/admin/groups", { method: "POST", body: { name: form.name, description: form.description || null } });
      setForm({ name: "", description: "" });
      setCreating(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <div>
      <PageHeader title="Groups">
        <Button onClick={() => setCreating((v) => !v)}><Plus className="mr-1 h-4 w-4" /> New group</Button>
      </PageHeader>

      {error && (
        <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert>
      )}

      {creating && (
        <Card className="mb-6">
          <CardHeader><CardTitle>Create group</CardTitle></CardHeader>
          <CardContent>
            <form onSubmit={create} className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="g-name">Name</Label>
                <Input id="g-name" required maxLength={100} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="g-desc">Description</Label>
                <Input id="g-desc" maxLength={500} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </div>
              <div className="sm:col-span-2"><Button type="submit">Create group</Button></div>
            </form>
          </CardContent>
        </Card>
      )}

      <Input aria-label="Search groups" placeholder="Search groups" className="mb-4 max-w-xs" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />

      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full" data-testid="groups-table">
            <thead className="border-b">
              <tr><th className={th}>Name</th><th className={th}>Description</th><th className={th}>Members</th></tr>
            </thead>
            <tbody>
              {data?.items.map((g) => (
                <tr key={g.id} className="border-b last:border-0 hover:bg-accent/30">
                  <td className={td}>
                    <Link className="font-medium underline-offset-4 hover:underline" href={`/admin/groups/${g.id}`}>{g.name}</Link>{" "}
                    {g.is_system_group && <Badge>system</Badge>}
                  </td>
                  <td className={td}>{g.description ?? "—"}</td>
                  <td className={td}>{g.member_count}</td>
                </tr>
              ))}
              {data && data.items.length === 0 && <tr><td className={td} colSpan={3}>No groups yet.</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>
      {data && <Pager page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />}
    </div>
  );
}
