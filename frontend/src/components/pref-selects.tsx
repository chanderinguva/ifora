"use client";

import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import { fieldClass } from "@/components/bits";
import { LOCALES, browserTimeZone, localeName, timeZoneGroups } from "@/lib/display";

/** Searchable by typing (native select type-ahead), grouped by region, valid IANA ids only. */
export function TimezoneSelect({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) {
  const groups = useMemo(() => timeZoneGroups(), []);
  const known = useMemo(() => new Set(groups.flatMap((g) => g.zones.map((z) => z.id))), [groups]);
  const detected = typeof window === "undefined" ? "" : browserTimeZone();
  return (
    <div className="space-y-1">
      <div className="flex gap-2">
        <select id={id} className={fieldClass} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">Not set</option>
          {value && !known.has(value) && <option value={value}>{value} (unrecognised; pick a zone)</option>}
          {groups.map((g) => (
            <optgroup key={g.region} label={g.region}>
              {g.zones.map((z) => <option key={z.id} value={z.id}>{z.label}</option>)}
            </optgroup>
          ))}
        </select>
        {detected && detected !== value && (
          <Button type="button" variant="outline" onClick={() => onChange(detected)} title={`Use ${detected}`}>
            Detect
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">Used to show dates and times in your account. Browser zone: {detected || "unknown"}.</p>
    </div>
  );
}

export function LocaleSelect({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) {
  const options = value && !LOCALES.includes(value) ? [value, ...LOCALES] : LOCALES;
  return (
    <div className="space-y-1">
      <select id={id} className={fieldClass} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Browser default</option>
        {options.map((l) => <option key={l} value={l}>{localeName(l)} ({l})</option>)}
      </select>
      <p className="text-xs text-muted-foreground">Controls date and number formats. The interface language is English for now.</p>
    </div>
  );
}
