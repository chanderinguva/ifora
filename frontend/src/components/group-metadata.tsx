"use client";

import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldClass } from "@/components/bits";
import { http, qs, type Page } from "@/lib/http";
import type { Group, User } from "@/lib/types";

export type GroupType = { id: string; label: string; purpose: string; naming: string; requires: string[]; can_carry_admin_roles: boolean };
export type Meta = { type: string; owner: string; sensitivity: string; review_by: string; tags: string; attributes: string };
export const EMPTY_META: Meta = { type: "other", owner: "", sensitivity: "", review_by: "", tags: "", attributes: "" };

export function metaFromGroup(g: Group): Meta {
  return {
    type: g.type, owner: g.owner_user_id ? String(g.owner_user_id) : "", sensitivity: g.sensitivity ?? "", review_by: g.review_by ?? "",
    tags: (g.tags ?? []).join(", "), attributes: Object.entries(g.attributes ?? {}).map(([k, v]) => `${k}=${v}`).join("\n"),
  };
}

/** Request body for create or update (empty text becomes null / empty). */
export function metaBody(m: Meta) {
  const attributes: Record<string, string> = {};
  for (const line of m.attributes.split("\n")) {
    const i = line.indexOf("=");
    if (i > 0) attributes[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return {
    type: m.type, owner_user_id: m.owner ? Number(m.owner) : null, sensitivity: m.sensitivity || null, review_by: m.review_by || null,
    tags: m.tags.split(",").map((t) => t.trim()).filter(Boolean), attributes,
  };
}

/** Group kind and governance metadata (ADR 019). Used by the create form and the group page. */
export function GroupMetadataFields({ value, onChange, disabled = false }: { value: Meta; onChange: (m: Meta) => void; disabled?: boolean }) {
  const [types, setTypes] = useState<GroupType[]>([]);
  const [owners, setOwners] = useState<User[]>([]);
  useEffect(() => {
    http<{ types: GroupType[] }>("/admin/groups/standards").then((d) => setTypes(d.types)).catch(() => {});
    http<Page<User>>(`/admin/users${qs({ count: 100, status: "active" })}`).then((p) => setOwners(p.Resources)).catch(() => {});
  }, []);
  const t = types.find((x) => x.id === value.type);
  const set = (p: Partial<Meta>) => onChange({ ...value, ...p });
  return (
    <div className="grid gap-4 sm:grid-cols-2" data-testid="group-metadata">
      <div className="space-y-2">
        <Label htmlFor="gm-type">Type</Label>
        <select id="gm-type" className={fieldClass} disabled={disabled} value={value.type} onChange={(e) => set({ type: e.target.value })}>
          {types.length === 0 && <option value={value.type}>{value.type}</option>}
          {types.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
        </select>
        {t && <p className="text-xs text-muted-foreground">{t.purpose} Name it: {t.naming}.{t.requires.length > 0 && ` Needs: ${t.requires.join(", ").replace("review_by", "review date")}.`}</p>}
      </div>
      <div className="space-y-2">
        <Label htmlFor="gm-owner">Owner</Label>
        <select id="gm-owner" className={fieldClass} disabled={disabled} value={value.owner} onChange={(e) => set({ owner: e.target.value })}>
          <option value="">No owner</option>
          {owners.map((u) => <option key={u.id} value={u.id}>{u.first_name} {u.last_name} ({u.email})</option>)}
        </select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="gm-sens">Sensitivity</Label>
        <select id="gm-sens" className={fieldClass} disabled={disabled} value={value.sensitivity} onChange={(e) => set({ sensitivity: e.target.value })}>
          <option value="">Not set</option>
          <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
        </select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="gm-review">Review by</Label>
        <Input id="gm-review" type="date" disabled={disabled} value={value.review_by} onChange={(e) => set({ review_by: e.target.value })} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="gm-tags">Tags</Label>
        <Input id="gm-tags" disabled={disabled} placeholder="finance, tier-1" value={value.tags} onChange={(e) => set({ tags: e.target.value })} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="gm-attrs">Attributes (key=value per line)</Label>
        <textarea id="gm-attrs" rows={3} disabled={disabled} className={fieldClass} placeholder="cost_center=CC-100" value={value.attributes} onChange={(e) => set({ attributes: e.target.value })} />
      </div>
    </div>
  );
}
