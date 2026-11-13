"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { http } from "@/lib/http";
import { toBody, type ProvApp } from "@/lib/provisioning";

export function PushGroupsPanel({ app, assignments, links, canEdit, onUpdated, onAssignments }: {
  app: ProvApp; assignments: { id: number; type: string; subject_id: number; name: string }[];
  links: { id: number; type: string; label: string; state: string }[];
  canEdit: boolean; onUpdated: (app: ProvApp) => void; onAssignments?: () => void;
}) {
  const [enabled, setEnabled] = useState(app.options.push_groups);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const groups = assignments.filter((a) => a.type === "group");
  return <Card data-testid="push-groups-panel">
    <CardHeader><CardTitle>Push groups</CardTitle></CardHeader>
    <CardContent className="space-y-4 text-sm">
      <p className="text-muted-foreground">Push assigned groups and memberships to this SCIM application. The target must support SCIM Groups. This uses the application&apos;s shared Assignments list.</p>
      <label className="flex items-center gap-2"><input type="checkbox" disabled={!canEdit || busy} checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Push assigned groups</label>
      <p className="text-xs text-muted-foreground">Saving behavior changes queues a full sync, including users. This never grants administrator roles.</p>
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      {canEdit && <Button type="button" disabled={busy || enabled === app.options.push_groups} onClick={async () => {
        if (!window.confirm("Save group-push behavior and queue synchronization for this application's existing assignments?")) return;
        setBusy(true); setError("");
        try { onUpdated(await http<ProvApp>("/admin/provisioning-apps/" + app.id, { method: "PUT", body: toBody(app, { options: { ...app.options, push_groups: enabled } }) })); }
        catch (e) { setError(e instanceof Error ? e.message : "Could not save group push"); }
        finally { setBusy(false); }
      }}>Save group-push settings</Button>}
      <h3 className="font-medium">Assigned groups ({groups.length})</h3>
      {groups.length ? <ul className="divide-y rounded-md border">{groups.map((g) => <li key={g.id} className="px-3 py-2">{g.name}</li>)}</ul> : <p>No groups assigned yet.</p>}
      {onAssignments && <Button type="button" variant="outline" onClick={onAssignments}>Manage group assignments</Button>}
      <h3 className="font-medium">Recent group provisioning results</h3>
      <p className="text-xs text-muted-foreground">Group entries from the current linked-resource page, not a complete remote inventory.</p>
      {links.some((l) => l.type === "group") ? <ul className="divide-y rounded-md border">{links.filter((l) => l.type === "group").map((l) => <li key={l.id} className="flex flex-wrap justify-between gap-2 px-3 py-2"><span>{l.label}</span><span>{l.state}</span></li>)}</ul> : <p>No group results in the current page.</p>}
    </CardContent>
  </Card>;
}
