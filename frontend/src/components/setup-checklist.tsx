"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Circle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { http } from "@/lib/http";

type Item = { id: string; title: string; description: string; href: string; done: boolean; dismissed: boolean };

/** First-run checklist. Ticks come from the real objects (the server computes them); only "skip" is stored, per administrator. */
export function SetupChecklist() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [showSkipped, setShowSkipped] = useState(false);
  const [note, setNote] = useState("");

  const load = () => http<{ items: Item[] }>("/admin/setup-checklist").then((r) => setItems(r.items)).catch(() => setItems([]));
  useEffect(() => {
    load();
  }, []);

  if (items === null) return null;
  const open = items.filter((i) => !i.done && !i.dismissed);
  const skipped = items.filter((i) => !i.done && i.dismissed);
  const done = items.filter((i) => i.done).length;
  if (items.length === 0 || (open.length === 0 && skipped.length === 0)) return null; // everything real is done: nothing to show

  async function toggle(i: Item) {
    try {
      await http(`/admin/setup-checklist/${i.id}/dismiss`, { method: i.dismissed ? "DELETE" : "POST" });
      setNote(i.dismissed ? `${i.title} is back on the list.` : `${i.title} skipped.`);
      await load();
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Could not update");
    }
  }

  const shown = showSkipped ? [...open, ...skipped] : open;
  return (
    <Card className="mb-6" data-testid="setup-checklist" aria-labelledby="setup-title">
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <CardTitle id="setup-title">Get started</CardTitle>
        <span className="text-sm text-muted-foreground" data-testid="setup-progress">{done} of {items.length} done</span>
      </CardHeader>
      <CardContent>
        <ul className="divide-y">
          {shown.map((i) => (
            <li key={i.id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm" data-testid={`setup-${i.id}`}>
              <Circle className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <Link href={i.href} className="min-w-0 flex-1 underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
                <span className="font-medium">{i.title}</span>
                <span className="block text-xs text-muted-foreground">{i.description}</span>
              </Link>
              <Button variant="ghost" size="sm" onClick={() => toggle(i)} aria-label={`${i.dismissed ? "Show" : "Skip"} ${i.title}`}>
                {i.dismissed ? "Show again" : "Skip"}
              </Button>
            </li>
          ))}
          {open.length === 0 && <li className="py-2.5 text-sm text-muted-foreground">Nothing left to do. Skipped items are hidden.</li>}
        </ul>
        {done > 0 && (
          <p className="mt-2 flex items-center gap-1 text-xs text-muted-foreground"><Check className="h-3.5 w-3.5" aria-hidden />Finished items disappear on their own.</p>
        )}
        {skipped.length > 0 && (
          <Button variant="link" size="sm" className="mt-1 px-0" onClick={() => setShowSkipped((v) => !v)}>
            {showSkipped ? "Hide skipped items" : `Show ${skipped.length} skipped`}
          </Button>
        )}
        <p className="sr-only" role="status" aria-live="polite">{note}</p>
      </CardContent>
    </Card>
  );
}
