"use client";

import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldClass } from "@/components/bits";
import { http, qs, type Page } from "@/lib/http";
import type { AppSummary } from "@/lib/applications";
import type { User } from "@/lib/types";

type Meta = Pick<AppSummary, "owner_user_id" | "sensitivity" | "review_by" | "tags" | "attributes">;

/** Application governance metadata: owner, sensitivity, review date, tags, attributes (same vocabulary as groups). */
export function AppMetadataFields({ value, onChange }: { value: Meta; onChange: (m: Partial<Meta>) => void }) {
  const [owners, setOwners] = useState<User[]>([]);
  const [attrs, setAttrs] = useState(Object.entries(value.attributes ?? {}).map(([k, v]) => `${k}=${v}`).join("\n"));
  const [tags, setTags] = useState((value.tags ?? []).join(", "));
  useEffect(() => {
    http<Page<User>>(`/admin/users${qs({ count: 100, status: "active" })}`).then((p) => setOwners(p.Resources)).catch(() => {});
  }, []);
  const setAttrText = (text: string) => {
    setAttrs(text);
    const out: Record<string, string> = {};
    for (const line of text.split("\n")) { const i = line.indexOf("="); if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim(); }
    onChange({ attributes: out });
  };
  const setTagText = (text: string) => { setTags(text); onChange({ tags: text.split(",").map((t) => t.trim()).filter(Boolean) }); };
  return (
    <div className="grid gap-3 sm:grid-cols-2" data-testid="app-metadata">
      <div className="space-y-1">
        <Label htmlFor="am-owner">Owner</Label>
        <select id="am-owner" className={fieldClass} value={value.owner_user_id ?? ""} onChange={(e) => onChange({ owner_user_id: e.target.value ? Number(e.target.value) : null })}>
          <option value="">No owner</option>
          {owners.map((u) => <option key={u.id} value={u.id}>{u.first_name} {u.last_name} ({u.email})</option>)}
        </select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="am-sens">Sensitivity</Label>
        <select id="am-sens" className={fieldClass} value={value.sensitivity ?? ""} onChange={(e) => onChange({ sensitivity: (e.target.value || null) as Meta["sensitivity"] })}>
          <option value="">Not set</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
        </select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="am-review">Review by</Label>
        <Input id="am-review" type="date" value={value.review_by ?? ""} onChange={(e) => onChange({ review_by: e.target.value || null })} />
      </div>
      <div className="space-y-1">
        <Label htmlFor="am-tags">Tags</Label>
        <Input id="am-tags" placeholder="finance, tier-1" value={tags} onChange={(e) => setTagText(e.target.value)} />
      </div>
      <div className="space-y-1 sm:col-span-2">
        <Label htmlFor="am-attrs">Attributes (key=value per line)</Label>
        <textarea id="am-attrs" rows={3} className={fieldClass} placeholder={"vendor=Acme\ncost_center=CC-100"} value={attrs} onChange={(e) => setAttrText(e.target.value)} />
      </div>
    </div>
  );
}
