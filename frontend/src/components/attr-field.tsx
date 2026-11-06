"use client";

import { Input } from "@/components/ui/input";
import { fieldClass } from "@/components/bits";
import { LocaleSelect, TimezoneSelect } from "@/components/pref-selects";
import type { ProfileAttribute } from "@/lib/types";

/** Form state keeps every value as a string; `toApi` converts to the attribute's real type. */
export function toApi(a: ProfileAttribute, v: string): string | number | boolean | null {
  const t = v.trim();
  if (t === "") return null;
  if (a.data_type === "number") return Number(t);
  if (a.data_type === "boolean") return t === "true";
  return t;
}

export const fromApi = (v: unknown): string => (v === null || v === undefined ? "" : String(v));

export function AttrField({ attr, value, onChange, idPrefix = "attr" }: { attr: ProfileAttribute; value: string; onChange: (v: string) => void; idPrefix?: string }) {
  const id = `${idPrefix}-${attr.key}`;
  switch (attr.data_type) {
    case "timezone": return <TimezoneSelect id={id} value={value} onChange={onChange} />;
    case "locale": return <LocaleSelect id={id} value={value} onChange={onChange} />;
    case "boolean":
      return (
        <select id={id} className={fieldClass} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">Not set</option><option value="true">Yes</option><option value="false">No</option>
        </select>
      );
    case "enum":
      return (
        <select id={id} className={fieldClass} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">Not set</option>
          {value && !attr.enum_options?.includes(value) && <option value={value}>{value}</option>}
          {attr.enum_options?.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    case "number": return <Input id={id} type="number" value={value} onChange={(e) => onChange(e.target.value)} />;
    default: return <Input id={id} maxLength={500} value={value} onChange={(e) => onChange(e.target.value)} />;
  }
}
