import { useCallback, useEffect, useState } from "react";

/**
 * Has this form changed since it was loaded or last saved?
 *
 * Pass everything the form edits as one value (and `ready` once it has loaded). The first ready value becomes the baseline;
 * call `markClean()` right after a save or a reload so the value then in state becomes the new baseline.
 * The comparison is by content (JSON), so editing a field and putting the old text back is not a change.
 */
export function useDirty(value: unknown, ready = true) {
  const snap = JSON.stringify(value);
  const [base, setBase] = useState<string | null>(null);
  useEffect(() => {
    if (!ready) {
      if (base !== null) setBase(null); // the form went away: the next one to open starts from its own baseline
    } else if (base === null) setBase(snap);
  }, [ready, base, snap]);
  const markClean = useCallback(() => setBase(null), []);
  return { dirty: base !== null && snap !== base, markClean };
}

/** A string record without its empty entries, in a stable key order: "" and missing mean the same thing in a form. */
export function compact(record: Record<string, string | undefined | null>): Record<string, string> {
  return Object.fromEntries(Object.entries(record).filter(([, v]) => v !== "" && v != null).sort(([a], [b]) => a.localeCompare(b))) as Record<string, string>;
}
