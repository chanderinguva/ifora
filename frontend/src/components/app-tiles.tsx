"use client";

import { useEffect, useMemo, useState } from "react";
import { ExternalLink, Pin, PinOff, Search } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { http } from "@/lib/http";
import type { MyApp } from "@/lib/applications";

const PIN_KEY = "if.pinned-apps";
const HUES = [212, 262, 330, 24, 152, 190, 48, 0];
const hue = (name: string) => HUES[[...name].reduce((a, c) => a + c.charCodeAt(0), 0) % HUES.length];

function readPins(): number[] {
  try { const v = JSON.parse(localStorage.getItem(PIN_KEY) ?? "[]"); return Array.isArray(v) ? v.filter((x) => typeof x === "number") : []; } catch { return []; }
}
function writePins(p: number[]) { try { localStorage.setItem(PIN_KEY, JSON.stringify(p)); } catch { /* private mode: pins last for this page only */ } }

/** The signed-in user's applications as launch tiles: search, pin favourites, one click to sign in. */
export function AppTiles() {
  const [apps, setApps] = useState<MyApp[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [pins, setPins] = useState<number[]>([]);

  useEffect(() => {
    setPins(readPins());
    http<{ items: MyApp[] }>("/me/apps").then((r) => setApps(r.items)).catch((e) => setErr(e.message));
  }, []);

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    const list = (apps ?? []).filter((a) => !t || a.name.toLowerCase().includes(t) || (a.description ?? "").toLowerCase().includes(t));
    return [...list.filter((a) => pins.includes(a.id)), ...list.filter((a) => !pins.includes(a.id))];
  }, [apps, q, pins]);

  function togglePin(id: number) {
    const next = pins.includes(id) ? pins.filter((x) => x !== id) : [...pins, id];
    setPins(next);
    writePins(next);
  }

  async function launch(a: MyApp) {
    setErr(null);
    const w = window.open("about:blank", "_blank");  // opened synchronously so popup blockers allow it
    try {
      const r = await http<{ url: string }>(`/me/apps/${a.id}/launch`, { method: "POST" });
      if (w) { w.opener = null; w.location.href = r.url; } else window.location.href = r.url;
    } catch (e) {
      w?.close();
      setErr(e instanceof Error ? e.message : "Could not open the application");
    }
  }

  return (
    <div data-testid="app-tiles">
      {err && <Alert variant="destructive" className="mb-4" role="status"><AlertDescription>{err}</AlertDescription></Alert>}
      {apps && apps.length > 0 && (
        <div className="relative mb-4 max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input aria-label="Search my apps" placeholder="Search apps…" className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      )}
      {apps && apps.length === 0 && <p className="text-sm text-muted-foreground" data-testid="no-apps">No applications have been assigned to you yet. When an administrator gives you access, they appear here.</p>}
      {apps && apps.length > 0 && shown.length === 0 && <p className="text-sm text-muted-foreground">No app matches “{q}”.</p>}
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" data-testid="my-apps">
        {shown.map((a) => {
          const pinned = pins.includes(a.id);
          return (
            <li key={a.id} className="group relative">
              <button type="button" disabled={!a.launchable} onClick={() => launch(a)} aria-label={a.launchable ? `Open ${a.name}` : `${a.name} (no launch link)`}
                className="flex h-full w-full flex-col items-center gap-2 rounded-xl border bg-card p-4 text-center shadow-sm transition hover:-translate-y-0.5 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60">
                <span aria-hidden className="flex h-12 w-12 items-center justify-center rounded-xl text-lg font-semibold text-white" style={{ background: `hsl(${hue(a.name)} 60% 42%)` }}>{a.name.trim().charAt(0).toUpperCase()}</span>
                <span className="line-clamp-2 text-sm font-medium">{a.name}</span>
                {a.description && <span className="line-clamp-2 text-xs text-muted-foreground">{a.description}</span>}
                {a.launchable && <ExternalLink aria-hidden className="h-3.5 w-3.5 text-muted-foreground opacity-0 transition group-hover:opacity-100" />}
              </button>
              <button type="button" onClick={() => togglePin(a.id)} aria-pressed={pinned} aria-label={pinned ? `Unpin ${a.name}` : `Pin ${a.name}`}
                className="absolute right-2 top-2 rounded-md p-1 text-muted-foreground opacity-60 hover:bg-muted hover:opacity-100 focus-visible:opacity-100 group-hover:opacity-100">
                {pinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
