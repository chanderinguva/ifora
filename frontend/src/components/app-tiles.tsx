"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowUp, ExternalLink, KeyRound, Plus, Search, Settings2, Star, Trash2 } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AppIcon } from "@/components/app-icon";
import { fieldClass } from "@/components/bits";
import { http } from "@/lib/http";
import type { MyApp } from "@/lib/applications";

type Section = { id: number; name: string; position: number };
type Pref = { favorite: boolean; section_id: number | null; position: number; last_launched_at: string | null };
type Overview = { sections: Section[]; apps: Record<string, Pref>; recent: number[] };
const OLD_PINS = "if.pinned-apps";
const NONE: Pref = { favorite: false, section_id: null, position: 0, last_launched_at: null };

/** The signed-in user's applications: favourites, recently used, own sections, search. Preferences live on the server. */
export function AppTiles() {
  const [apps, setApps] = useState<MyApp[] | null>(null);
  const [ov, setOv] = useState<Overview>({ sections: [], apps: {}, recent: [] });
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [organise, setOrganise] = useState(false);
  const [newSection, setNewSection] = useState("");
  const started = useRef(false);

  const loadPrefs = useCallback(() => http<Overview>("/me/dashboard").then(setOv).catch((e) => setErr(e.message)), []);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      try {
        const r = await http<{ items: MyApp[] }>("/me/apps");
        setApps(r.items);
        // one-time move of the old browser-only pins to the account
        try {
          const old = JSON.parse(localStorage.getItem(OLD_PINS) ?? "[]");
          if (Array.isArray(old) && old.length) await http("/me/dashboard/import-favorites", { method: "POST", body: { app_ids: old.filter((x: unknown) => typeof x === "number") } });
          localStorage.removeItem(OLD_PINS);
        } catch { /* storage unavailable or import refused: nothing to move */ }
        await loadPrefs();
      } catch (e) { setErr(e instanceof Error ? e.message : "Could not load your apps"); }
    })();
  }, [loadPrefs]);

  const pref = (id: number) => ov.apps[String(id)] ?? NONE;

  async function act(fn: () => Promise<unknown>) {
    setErr(null);
    try { await fn(); await loadPrefs(); } catch (e) { setErr(e instanceof Error ? e.message : "That did not work"); }
  }
  const put = (id: number, body: object) => act(() => http(`/me/dashboard/apps/${id}`, { method: "PUT", body }));

  const searching = q.trim() !== "";
  const matches = useMemo(() => {
    const t = q.trim().toLowerCase();
    return (apps ?? []).filter((a) => !t || a.name.toLowerCase().includes(t) || (a.description ?? "").toLowerCase().includes(t));
  }, [apps, q]);

  const byOrder = (list: MyApp[]) => [...list].sort((a, b) => pref(a.id).position - pref(b.id).position || a.name.localeCompare(b.name));
  const favourites = byOrder(matches.filter((a) => pref(a.id).favorite));
  const rest = matches.filter((a) => !pref(a.id).favorite);
  const knownSections = new Set(ov.sections.map((s) => s.id));
  const inSection = (sid: number | null) => byOrder(rest.filter((a) => (pref(a.id).section_id && knownSections.has(pref(a.id).section_id!) ? pref(a.id).section_id : null) === sid));
  const recent = ov.recent.map((id) => (apps ?? []).find((a) => a.id === id)).filter((a): a is MyApp => !!a && a.launchable);

  async function launch(a: MyApp) {
    setErr(null);
    const w = window.open("about:blank", "_blank");  // opened synchronously so popup blockers allow it
    try {
      const r = await http<{ url: string }>(`/me/apps/${a.id}/launch`, { method: "POST" });
      if (w) { w.opener = null; w.location.href = r.url; } else window.location.href = r.url;
      loadPrefs();
    } catch (e) {
      w?.close();
      setErr(e instanceof Error ? e.message : "Could not open the application");
    }
  }

  function tile(a: MyApp) {
    const p = pref(a.id);
    return (
      <li key={a.id} className="group relative" data-testid={`tile-${a.id}`}>
        <button type="button" disabled={!a.launchable} onClick={() => launch(a)} aria-label={a.launchable ? `Open ${a.name}` : `${a.name} (no launch link)`}
          title={a.description ?? a.name} className="flex h-full w-full flex-col items-center gap-3 rounded-2xl border border-transparent p-4 text-center transition hover:border-border hover:bg-card hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60">
          <span className="rounded-2xl bg-card p-1.5 shadow-sm ring-1 ring-border"><AppIcon path={`/me/apps/${a.id}/icon`} name={a.name} hasIcon={a.has_icon} size={56} /></span>
          <span className="line-clamp-2 text-sm font-medium">{a.name}</span>
          {a.launchable && !organise && <ExternalLink aria-hidden className="h-3.5 w-3.5 text-muted-foreground opacity-0 transition group-hover:opacity-100" />}
        </button>
        {a.sign_on_mode === "swa" && (
          <a href={`/swa/continue?app=${a.id}&manage=1`} aria-label={`Change saved sign-in for ${a.name}`} title="Change saved sign-in"
            className="absolute left-2 top-2 rounded-md p-1 text-muted-foreground opacity-60 hover:bg-muted hover:opacity-100 focus-visible:opacity-100 group-hover:opacity-100">
            <KeyRound className="h-3.5 w-3.5" />
          </a>
        )}
        <button type="button" onClick={() => put(a.id, { favorite: !p.favorite })} aria-pressed={p.favorite} aria-label={p.favorite ? `Remove ${a.name} from favourites` : `Add ${a.name} to favourites`}
          className="absolute right-2 top-2 rounded-md p-1 text-muted-foreground opacity-60 hover:bg-muted hover:opacity-100 focus-visible:opacity-100 group-hover:opacity-100">
          <Star className={"h-3.5 w-3.5 " + (p.favorite ? "fill-current text-warn" : "")} />
        </button>
        {organise && (
          <div className="mt-1 flex items-center justify-center gap-1">
            <Button type="button" variant="ghost" size="sm" aria-label={`Move ${a.name} earlier`} onClick={() => put(a.id, { move: "earlier" })}><ArrowUp className="h-3.5 w-3.5" /></Button>
            <Button type="button" variant="ghost" size="sm" aria-label={`Move ${a.name} later`} onClick={() => put(a.id, { move: "later" })}><ArrowDown className="h-3.5 w-3.5" /></Button>
            <select aria-label={`Section for ${a.name}`} className={fieldClass + " h-8 w-28 py-0 text-xs"} value={p.section_id ?? ""}
              onChange={(e) => put(a.id, e.target.value ? { section_id: Number(e.target.value) } : { clear_section: true })}>
              <option value="">Other</option>
              {ov.sections.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
        )}
      </li>
    );
  }

  const grid = (list: MyApp[], id: string) => (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5" data-testid={id}>{list.map((a) => tile(a))}{id === "my-apps" && !searching && (
      <li>
        <Link href="/apps/request" data-testid="add-apps-tile" className="flex h-full min-h-[132px] w-full flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed p-4 text-center text-sm text-muted-foreground transition hover:border-primary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <Plus aria-hidden className="h-6 w-6" /> Add apps
        </Link>
      </li>
    )}</ul>
  );

  const hasApps = !!apps && apps.length > 0;
  const otherApps = inSection(null);

  return (
    <div data-testid="app-tiles">
      {err && <Alert variant="destructive" className="mb-4" role="status"><AlertDescription>{err}</AlertDescription></Alert>}
      {hasApps && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="relative max-w-xl flex-1">
            <Search className="pointer-events-none absolute left-4 top-3 h-5 w-5 text-muted-foreground" />
            <Input aria-label="Search my apps" placeholder="Search your apps" className="h-11 rounded-full pl-11 text-base" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <Button type="button" variant={organise ? "default" : "outline"} size="sm" aria-pressed={organise} onClick={() => setOrganise((v) => !v)} data-testid="organise-toggle">
            <Settings2 className="mr-1 h-4 w-4" /> {organise ? "Done" : "Organise"}
          </Button>
        </div>
      )}
      {apps && apps.length === 0 && (
        <div className="rounded-2xl border-2 border-dashed p-8 text-center" data-testid="no-apps">
          <p className="text-sm text-muted-foreground">No applications have been assigned to you yet. When an administrator gives you access, they appear here.</p>
          <Link href="/apps/request" className="mt-3 inline-flex items-center gap-1 text-sm font-medium underline-offset-4 hover:underline"><Plus aria-hidden className="h-4 w-4" /> Request access to an app</Link>
        </div>
      )}
      {hasApps && matches.length === 0 && <p className="text-sm text-muted-foreground">No app matches “{q}”.</p>}

      {!searching && recent.length > 0 && (
        <section className="mb-6" aria-labelledby="recent-h" data-testid="recent-apps">
          <h3 id="recent-h" className="mb-2 text-base font-semibold">Recently used</h3>
          <ul className="flex flex-wrap gap-2">
            {recent.map((a) => (
              <li key={a.id}>
                <button type="button" onClick={() => launch(a)} aria-label={`Recent: ${a.name}`} className="flex items-center gap-2 rounded-full border bg-card px-3 py-1.5 text-sm shadow-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <AppIcon path={`/me/apps/${a.id}/icon`} name={a.name} hasIcon={a.has_icon} size={20} /> {a.name}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {favourites.length > 0 && (
        <section className="mb-6" aria-labelledby="fav-h" data-testid="favourites">
          <h3 id="fav-h" className="mb-2 text-base font-semibold">Favourites</h3>
          {grid(favourites, "fav-apps")}
        </section>
      )}

      {ov.sections.map((s, i) => {
        const list = inSection(s.id);
        if (searching && list.length === 0) return null;
        return (
          <section key={s.id} className="mb-6" aria-labelledby={`sec-${s.id}`} data-testid={`section-${s.id}`}>
            <div className="mb-2 flex items-center gap-1">
              <h3 id={`sec-${s.id}`} className="text-base font-semibold">{s.name}</h3>
              {organise && (
                <>
                  <Button type="button" variant="ghost" size="sm" aria-label={`Move section ${s.name} earlier`} disabled={i === 0} onClick={() => act(() => http(`/me/dashboard/sections/${s.id}`, { method: "PATCH", body: { move: "earlier" } }))}><ArrowUp className="h-3.5 w-3.5" /></Button>
                  <Button type="button" variant="ghost" size="sm" aria-label={`Move section ${s.name} later`} disabled={i === ov.sections.length - 1} onClick={() => act(() => http(`/me/dashboard/sections/${s.id}`, { method: "PATCH", body: { move: "later" } }))}><ArrowDown className="h-3.5 w-3.5" /></Button>
                  <Button type="button" variant="ghost" size="sm" aria-label={`Rename section ${s.name}`} onClick={() => { const n = window.prompt("Section name", s.name); if (n?.trim()) act(() => http(`/me/dashboard/sections/${s.id}`, { method: "PATCH", body: { name: n } })); }}>Rename</Button>
                  <Button type="button" variant="ghost" size="sm" aria-label={`Delete section ${s.name}`} onClick={() => act(() => http(`/me/dashboard/sections/${s.id}`, { method: "DELETE" }))}><Trash2 className="h-3.5 w-3.5" /></Button>
                </>
              )}
            </div>
            {list.length > 0 ? grid(list, `sec-apps-${s.id}`) : <p className="text-xs text-muted-foreground">{organise ? "Empty. Use an app’s Section menu to file it here." : "No apps in this section."}</p>}
          </section>
        );
      })}

      {otherApps.length > 0 && (
        <section className="mb-6" aria-labelledby="other-h" data-testid="other-apps">
          {(ov.sections.length > 0 || favourites.length > 0) && <h3 id="other-h" className="mb-2 text-base font-semibold">{ov.sections.length > 0 ? "Other" : "All apps"}</h3>}
          {grid(otherApps, "my-apps")}
        </section>
      )}

      {organise && (
        <form className="mt-2 flex max-w-sm gap-2" onSubmit={(e) => { e.preventDefault(); const n = newSection.trim(); if (!n) return; setNewSection(""); act(() => http("/me/dashboard/sections", { method: "POST", body: { name: n } })); }}>
          <Input aria-label="New section name" placeholder="New section…" maxLength={40} value={newSection} onChange={(e) => setNewSection(e.target.value)} />
          <Button type="submit" variant="outline" size="sm" data-testid="add-section"><Plus className="mr-1 h-4 w-4" /> Add section</Button>
        </form>
      )}
    </div>
  );
}
