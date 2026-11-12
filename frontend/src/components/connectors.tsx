"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/bits";
import type { ConnectorInfo } from "@/lib/recipes";

export function ConnectorCatalog({ items, disabled, onConnect }: { items: ConnectorInfo[]; disabled: boolean; onConnect: (c: ConnectorInfo) => void }) {
  if (items.length === 0) return null;
  return (
    <section className="mb-6" aria-labelledby="catalog-title" data-testid="connector-catalog">
      <h2 id="catalog-title" className="mb-2 text-sm font-semibold">Pre-built connectors</h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((c) => (
          <Card key={c.id} data-testid={`connector-${c.id}`}><CardContent className="flex h-full flex-col gap-2 pt-6">
            <div className="flex items-center gap-3">
              <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-sm font-semibold text-primary">{c.name.slice(0, 2).toUpperCase()}</span>
              <div className="min-w-0"><div className="font-medium leading-tight">{c.name}</div><Badge tone="neutral">{c.category}</Badge></div>
            </div>
            <p className="flex-1 text-sm text-muted-foreground">{c.description}</p>
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">{c.actions.length} actions</span>
              <Button size="sm" variant="outline" disabled={disabled} onClick={() => onConnect(c)} aria-label={`Connect ${c.name}`}>Connect</Button>
            </div>
          </CardContent></Card>
        ))}
      </div>
    </section>
  );
}
