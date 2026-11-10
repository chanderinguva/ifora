"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { USER_STATUSES, type UserStatus } from "@/lib/types";

// The statuses and the moves between them, as implemented in backend/app/users/lifecycle.py and users/routes.py.
type Node = { s: UserStatus; x: number; y: number; w: number; tone: "start" | "good" | "block" | "off"; hint: string };
const NODES: Node[] = [
  { s: "staged", x: 20, y: 50, w: 170, tone: "start", hint: "Created, not activated" },
  { s: "provisioned", x: 270, y: 50, w: 170, tone: "start", hint: "Invited, not set up yet" },
  { s: "active", x: 440, y: 180, w: 180, tone: "good", hint: "Can sign in" },
  { s: "suspended", x: 830, y: 20, w: 190, tone: "block", hint: "Blocked; keeps groups" },
  { s: "password_expired", x: 830, y: 110, w: 190, tone: "block", hint: "Must set a new password" },
  { s: "recovery", x: 830, y: 200, w: 190, tone: "block", hint: "Password reset requested" },
  { s: "locked_out", x: 830, y: 290, w: 190, tone: "block", hint: "Too many failed sign-ins" },
  { s: "deprovisioned", x: 440, y: 340, w: 180, tone: "off", hint: "Deactivated; in no groups" },
];
const H = 52;
const TONE: Record<Node["tone"], string> = {
  start: "fill-sky-50 stroke-sky-500 dark:fill-sky-950 dark:stroke-sky-500",
  good: "fill-emerald-50 stroke-emerald-600 dark:fill-emerald-950 dark:stroke-emerald-500",
  block: "fill-amber-50 stroke-amber-500 dark:fill-amber-950 dark:stroke-amber-500",
  off: "fill-rose-50 stroke-rose-500 dark:fill-rose-950 dark:stroke-rose-500",
};

// both = the move works in both directions (an arrowhead at each end); a = text-anchor
const EDGES: { d: string; label: string; lx: number; ly: number; both?: boolean; a?: "start" | "middle" }[] = [
  { d: "M190 76 H270", label: "Send invite", lx: 230, ly: 66 },
  { d: "M440 76 H500 Q530 76 530 106 V180", label: "User sets a password", lx: 545, ly: 132, a: "start" },
  { d: "M105 102 V206 H440", label: "Activate", lx: 270, ly: 198 },
  { d: "M620 196 L830 46", label: "Suspend ⇄ Unsuspend", lx: 722, ly: 114, both: true },
  { d: "M620 200 L830 136", label: "Max age ⇄ New password", lx: 722, ly: 162, both: true },
  { d: "M620 208 L830 226", label: "Reset ⇄ Set password", lx: 722, ly: 210, both: true },
  { d: "M620 216 L830 316", label: "Failed sign-ins ⇄ Unlock", lx: 722, ly: 262, both: true },
  { d: "M530 232 V340", label: "Deactivate ⇄ Reactivate", lx: 542, ly: 292, both: true, a: "start" },
];

const KEY = "users-lifecycle-open";

/** A flow chart of the user statuses. Clicking a status filters the list below it. */
export function UserLifecycle({ onPick, current }: { onPick: (status: string) => void; current: string }) {
  const [open, setOpen] = useState(true);
  useEffect(() => { try { if (localStorage.getItem(KEY) === "0") setOpen(false); } catch { /* storage may be blocked */ } }, []);
  const toggle = () => setOpen((v) => { try { localStorage.setItem(KEY, v ? "0" : "1"); } catch { /* ignore */ } return !v; });
  const info = (s: UserStatus) => USER_STATUSES.find((x) => x.value === s)!;

  return (
    <section className="mb-4 rounded-lg border bg-card" data-testid="lifecycle">
      <button type="button" onClick={toggle} aria-expanded={open} aria-controls="lifecycle-body" data-testid="lifecycle-toggle"
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium">
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />} User lifecycle
        <span className="font-normal text-muted-foreground">how an account moves between statuses; click a status to filter the list</span>
      </button>
      {open && (
        <div id="lifecycle-body" className="border-t px-4 pb-4 pt-2">
          <div className="overflow-x-auto">
            <svg viewBox="0 0 1040 420" role="img" aria-label="User status lifecycle" className="min-w-[840px] w-full text-muted-foreground" data-testid="lifecycle-chart">
              <defs>
                <marker id="lc-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M0 0 L10 5 L0 10 z" fill="currentColor" />
                </marker>
              </defs>
              {EDGES.map((e) => (
                <g key={e.label}>
                  <path d={e.d} fill="none" stroke="currentColor" strokeWidth="1.5"
                    markerEnd="url(#lc-arrow)" markerStart={e.both ? "url(#lc-arrow)" : undefined} />
                  <text x={e.lx} y={e.ly} textAnchor={e.a ?? "middle"} className="fill-muted-foreground text-[11px]" style={{ paintOrder: "stroke", stroke: "hsl(var(--card))", strokeWidth: 5 }}>{e.label}</text>
                </g>
              ))}
              {/* a new account starts here */}
              <circle cx="26" cy="16" r="5" fill="currentColor" />
              <text x="38" y="20" className="fill-muted-foreground text-[11px]">New accounts start Active, or Provisioned when invited</text>
              {NODES.map((n) => {
                const i = info(n.s);
                const w = n.w;
                const on = current === n.s;
                return (
                  <g key={n.s} role="button" tabIndex={0} aria-pressed={on} aria-label={`${i.label}: ${i.hint}. Show these users`} data-testid={`lc-${n.s}`}
                    className="cursor-pointer outline-none focus-visible:[&>rect]:stroke-[3]"
                    onClick={() => onPick(on ? "" : n.s)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(on ? "" : n.s); } }}>
                    <rect x={n.x} y={n.y} width={w} height={H} rx="10" strokeWidth={on ? 3 : 1.5} className={TONE[n.tone]} />
                    <text x={n.x + w / 2} y={n.y + 22} textAnchor="middle" className="fill-foreground text-[13px] font-semibold">{i.label}</text>
                    <text x={n.x + w / 2} y={n.y + 40} textAnchor="middle" className="fill-muted-foreground text-[10px]">{n.hint}</text>
                  </g>
                );
              })}
              <text x="20" y="404" className="fill-muted-foreground text-[11px]">Deactivate works from every status except Deprovisioned.</text>
            </svg>
          </div>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
            <li>Only <strong>Active</strong> users can sign in. Leaving Active ends all of the user&apos;s sessions.</li>
            <li>Deprovisioning removes the user from every group; reactivating does not bring manual memberships back (group rules re-add what they grant).</li>
            <li>Locked out clears by itself after the lockout time, or an admin can unlock it; Password expired needs a new password at the next sign-in.</li>
          </ul>
        </div>
      )}
    </section>
  );
}
