"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { DndContext, DragOverlay, PointerSensor, closestCenter, pointerWithin, useDraggable, useDroppable, useSensor, useSensors, type CollisionDetection, type DragEndEvent } from "@dnd-kit/core";
import { Check, Copy, FlaskConical, GripVertical, Minus, Plus, Redo2, ShieldAlert, Trash2, Undo2, X, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, StepForm, TriggerCard, defaultConfig, pillsFor, type Ctx } from "@/components/recipe-editor/forms";
import { PillFieldsContext, type PillRegistry } from "@/components/recipe-editor/pill-context";
import { PillTray } from "@/components/recipe-editor/pill-tray";
import { allIds, countSteps, duplicateStep, gapKey, insertAt, locate, moveProblem, moveStep, newId, nextGap, parseGap, removeStep, replaceStep, allGaps, type Gap, type LaneRef } from "@/components/recipe-editor/tree";
import { isLoop, isLoopType, laneInCatch, laneSteps } from "@/components/recipe-editor/tree";
import { statusTone, type Definition, type Job, type JobStep, type RecipeMeta, type StepNode } from "@/lib/recipes";
import type { Group } from "@/lib/types";

const PANEL_KEY = "recipe-studio-panel-width";
const PANEL_DEFAULT = 448;
const PANEL_MIN = 340;
const clampPanel = (w: number) => Math.round(Math.max(PANEL_MIN, Math.min(w, 960, (typeof window === "undefined" ? 960 : window.innerWidth) - 380)));

/** Drag handle on the panel's left edge: pointer drag, arrow keys, double-click to reset. */
function PanelResizer({ width, onResize }: { width: number; onResize: (w: number, save?: boolean) => number }) {
  const start = useRef<{ x: number; w: number } | null>(null);
  return (
    <div role="separator" aria-orientation="vertical" aria-label="Resize step settings" aria-valuenow={width} aria-valuemin={PANEL_MIN} tabIndex={0} data-testid="panel-resizer"
      className="group absolute -left-3 top-0 z-10 hidden h-full w-3 cursor-col-resize touch-none items-center justify-center focus:outline-none lg:flex"
      onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); start.current = { x: e.clientX, w: width }; }}
      onPointerMove={(e) => { if (start.current) onResize(start.current.w + (start.current.x - e.clientX)); }}
      onPointerUp={(e) => { if (start.current) { onResize(start.current.w + (start.current.x - e.clientX), true); start.current = null; } e.currentTarget.releasePointerCapture(e.pointerId); }}
      onDoubleClick={() => onResize(PANEL_DEFAULT, true)}
      onKeyDown={(e) => {
        const step = e.shiftKey ? 96 : 24;
        if (e.key === "ArrowLeft") { e.preventDefault(); onResize(width + step, true); }
        else if (e.key === "ArrowRight") { e.preventDefault(); onResize(width - step, true); }
        else if (e.key === "Home") { e.preventDefault(); onResize(PANEL_DEFAULT, true); }
      }}>
      <span className="h-12 w-1 rounded-full bg-border transition-colors group-hover:bg-primary group-focus-visible:bg-primary" />
    </div>
  );
}

type Props = {
  def: Definition; meta: RecipeMeta; ctx: Ctx; groups: Group[]; canEdit: boolean;
  edit: (d: Definition, merge?: boolean) => void; setTrigger: (patch: Partial<Definition["trigger"]>) => void;
  result: Job | null; stale: boolean;
  previewFormulas: (templates: string[]) => Promise<PreviewItem[]>;
  undo: () => void; redo: () => void; canUndo: boolean; canRedo: boolean;
};

export type PreviewItem = { template: string; ok: boolean; value?: unknown; error?: string };

function formulasIn(v: unknown): string[] {
  if (typeof v === "string") return v.includes("{{=") ? [v] : [];
  if (Array.isArray(v)) return v.flatMap(formulasIn);
  if (v && typeof v === "object") return Object.values(v).flatMap(formulasIn);
  return [];
}

/** Shows what this step's formulas give for the sample event chosen in the Test section. */
function FormulaPreview({ templates, run }: { templates: string[]; run: (t: string[]) => Promise<PreviewItem[]> }) {
  const [items, setItems] = useState<PreviewItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setItems(null); setErr(null); }, [templates.join("\u0000")]);
  if (templates.length === 0) return null;
  return (
    <div className="space-y-2 border-t pt-3" data-testid="formula-preview">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Formulas</span>
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={async () => {
          setBusy(true); setErr(null);
          try { setItems(await run(templates)); } catch (e) { setItems(null); setErr(e instanceof Error ? e.message : "Preview failed"); } finally { setBusy(false); }
        }}>Preview with the sample</Button>
      </div>
      {err && <p className="text-xs text-destructive">{err}</p>}
      {items?.map((it, i) => (
        <div key={i} className="rounded border p-2 text-xs" data-testid="formula-result" data-ok={it.ok ? "yes" : "no"}>
          <div className="truncate font-mono text-muted-foreground" title={it.template}>{it.template}</div>
          {it.ok ? <pre className="mt-1 whitespace-pre-wrap break-words">{typeof it.value === "string" ? it.value : JSON.stringify(it.value)}</pre> : <p className="mt-1 text-destructive">{it.error}</p>}
        </div>
      ))}
      <p className="text-xs text-muted-foreground">Uses the sample user chosen under Test. Data from earlier steps is not available in a preview; run a test to see it.</p>
    </div>
  );
}

type Outcome = "ok" | "failed" | "skipped" | "other";


function summary(s: StepNode, props: Props): string {
  const c = s.config ?? {};
  const group = (id: unknown) => props.groups.find((g) => g.id === id)?.name ?? "no group chosen";
  switch (s.type) {
    case "handle_errors": return `Catches errors in ${(s.then ?? []).length} step${(s.then ?? []).length === 1 ? "" : "s"}`;
    case "add_to_group": return `Add to ${group(c.group_id)}`;
    case "remove_from_group": return `Remove from ${group(c.group_id)}`;
    case "set_attribute": return c.attribute ? `Set ${c.attribute}` : "Choose an attribute";
    case "http_request": return `${c.method ?? "POST"} ${String(c.url ?? "").replace(/^https?:\/\//, "").slice(0, 40)}`;
    case "log": return c.message ? String(c.message).slice(0, 50) : "Write a log message";
    case "send_email": return c.subject ? `Email: ${String(c.subject).slice(0, 40)}` : "Send an email";
    case "send_slack": return c.message ? `Slack: ${String(c.message).slice(0, 40)}` : "Send a Slack message";
    case "condition": { const n = (c.conditions ?? []).length; return n ? `${c.match === "any" ? "Any" : "All"} of ${n} condition${n > 1 ? "s" : ""}` : "Always applies"; }
    case "stop": return c.outcome === "failed" ? "Stop and fail the job" : "Stop the job";
    case "for_each_member": return `Members of ${group(c.group_id)}`;
    case "for_each_item": return c.list ? `Each item of ${String(c.list).slice(0, 40)}` : "Choose a list";
    case "approval": return c.message ? String(c.message).slice(0, 50) : "Ask for approval";
    case "lookup_row": return c.table ? `Look up ${c.table} where ${c.column}` : "Choose a table";
    case "lookup_write": return c.table ? `${c.action === "delete" ? "Delete from" : c.action === "add" ? "Add to" : "Upsert into"} ${c.table}` : "Choose a table";
    case "set_variable": return c.name ? `Set ${c.name}` : "Name the variable";
    case "call_recipe": return c.recipe_id ? `Call ${props.ctx.meta.callable_recipes?.find((r) => r.id === c.recipe_id)?.name ?? "a recipe"}` : "Choose a recipe to call";
    case "return_data": return `Return ${Object.keys(c.values ?? {}).join(", ") || "data"}`;
    case "wait": return `Wait ${c.amount ?? "?"} ${c.unit ?? "minutes"}`;
    case "throttle": return `${c.max_runs ?? "?"} per ${c.per_minutes ?? "?"} min, then ${c.when_full === "stop" ? "drop" : "wait"}`;
    default: return "";
  }
}

/** What a test run did with one step. A step with no rows in a finished run was on a branch that was not taken. */
function outcomeOf(rows: JobStep[] | undefined, job: Job): { kind: Outcome; text: string } {
  if (!rows || rows.length === 0) {
    return ["queued", "running", "retrying", "waiting"].includes(job.status) ? { kind: "other", text: "not reached yet" } : { kind: "skipped", text: "did not run" };
  }
  if (rows.some((r) => r.status === "failed")) return { kind: "failed", text: "failed" };
  const last = rows[rows.length - 1].status;
  return last === "succeeded" ? { kind: "ok", text: "succeeded" } : { kind: "other", text: last };
}

function ResultDot({ kind, text }: { kind: Outcome; text: string }) {
  const cls = kind === "ok" ? "bg-green-600 text-white" : kind === "failed" ? "bg-destructive text-destructive-foreground" : "bg-muted text-muted-foreground";
  return (
    <span data-testid="step-result" data-outcome={kind} title={`Test: ${text}`} className={"flex h-5 w-5 shrink-0 items-center justify-center rounded-full " + cls}>
      {kind === "ok" ? <Check className="h-3 w-3" /> : kind === "failed" ? <X className="h-3 w-3" /> : <Minus className="h-3 w-3" />}
      <span className="sr-only">Test result: {text}</span>
    </span>
  );
}

function AddMenu({ options, onPick, disabled, label, empty }: { options: StepMenuItem[]; onPick: (type: string) => void; disabled: boolean; label: string; empty?: boolean }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const shown = options.filter((o) => (o.label + " " + o.type).toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="relative flex justify-center" ref={box}>
      <button type="button" aria-label={label} data-testid="studio-add" disabled={disabled} onClick={() => { setOpen(!open); setQ(""); }}
        className={empty ? "rounded-md border border-dashed px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted disabled:opacity-50" : "flex h-6 w-6 items-center justify-center rounded-full border bg-background text-muted-foreground hover:bg-muted disabled:opacity-40"}>
        {empty ? <span className="flex items-center gap-1"><Plus className="h-4 w-4" /> Add a step</span> : <Plus className="h-3.5 w-3.5" />}
      </button>
      {open && (
        <div role="menu" className="absolute top-8 z-20 w-72 rounded-md border bg-popover p-2 shadow-md" data-testid="studio-menu">
          <input autoFocus aria-label="Search steps" placeholder="Search steps…" value={q} onChange={(e) => setQ(e.target.value)}
            className="mb-2 h-8 w-full rounded border bg-background px-2 text-sm" />
          <div className="max-h-72 overflow-auto">
            {(["action", "control"] as const).map((kind) => {
              const rows = shown.filter((o) => o.kind === kind);
              if (!rows.length) return null;
              return (
                <div key={kind} className="mb-1">
                  <div className="px-2 py-1 text-xs font-medium uppercase text-muted-foreground">{kind === "action" ? "Actions" : "Logic"}</div>
                  {rows.map((o) => (
                    <button key={o.type} role="menuitem" type="button" className="block w-full rounded px-2 py-1.5 text-left text-sm hover:bg-muted"
                      onClick={() => { setOpen(false); onPick(o.type); }}>{o.label}</button>
                  ))}
                </div>
              );
            })}
            {shown.length === 0 && <p className="px-2 py-1 text-sm text-muted-foreground">No step matches.</p>}
          </div>
        </div>
      )}
    </div>
  );
}
/** A place a step can be dropped (and where the + button lives). Never changes size, so nothing jumps while dragging. */
function GapSlot({ gap, active, children }: { gap: Gap; active: boolean; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: gapKey(gap) });
  return (
    <div ref={setNodeRef} data-testid="drop-slot" data-gap={gapKey(gap)} className="relative">
      <div className={active ? "invisible" : ""}>{children}</div>
      {active && (
        <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-1/2 flex -translate-y-1/2 items-center">
          {isOver
            ? <><span className="h-3 w-3 rounded-full bg-primary" /><span className="h-[3px] flex-1 rounded bg-primary" /></>
            : <span className="h-px flex-1 border-t border-dashed border-primary/30" />}
        </div>
      )}
    </div>
  );
}

/** Keyboard handle for a step (the whole header is the mouse/touch grab area). */
function DragHandle({ id, label, onKeyMove }: { id: string; label: string; onKeyMove: (dir: -1 | 1) => void }) {
  return (
    <button type="button" data-testid="drag-handle" data-handle-for={id}
      aria-label={`${label}. Drag, or press Alt and the up or down arrow to move it.`}
      className="flex h-7 w-5 shrink-0 touch-none items-center justify-center rounded text-muted-foreground hover:bg-muted"
      onKeyDown={(e) => { if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); e.stopPropagation(); onKeyMove(e.key === "ArrowUp" ? -1 : 1); } }}>
      <GripVertical className="h-4 w-4" />
    </button>
  );
}

/** The whole card is what moves (its rectangle is what the drag preview copies); the header is what you grab. */
function StepShell({ id, enabled, className, children }: { id: string; enabled: boolean; className: string; children: (grab: Record<string, unknown>) => React.ReactNode }) {
  const { listeners, setNodeRef } = useDraggable({ id, disabled: !enabled });
  return <div ref={setNodeRef} className={className} data-testid="studio-card" data-step-id={id}>{children(listeners ?? {})}</div>;
}

type StepMenuItem = { type: string; label: string; kind: "action" | "control" };

export function Studio(props: Props) {
  const { def, meta, groups, canEdit, edit } = props;
  const [sel, setSel] = useState<string>("trigger");
  const full = countSteps(def) >= meta.limits.max_steps;
  const rowsByStep = useMemo(() => {
    const m = new Map<string, JobStep[]>();
    for (const r of props.result?.steps ?? []) m.set(r.step_id, [...(m.get(r.step_id) ?? []), r]);
    return m;
  }, [props.result]);
  const [dragging, setDragging] = useState<string | null>(null);
  const [dragPill, setDragPill] = useState<string | null>(null);
  const [dragWidth, setDragWidth] = useState<number | null>(null);
  const [panelW, setPanelW] = useState<number>(PANEL_DEFAULT);
  useEffect(() => { try { const v = Number(localStorage.getItem(PANEL_KEY)); if (v) setPanelW(clampPanel(v)); } catch { /* storage unavailable */ } }, []);
  const resizePanel = (w: number, save = false) => { const c = clampPanel(w); setPanelW(c); if (save) { try { localStorage.setItem(PANEL_KEY, String(c)); } catch { /* ignore */ } } return c; };
  const registry = useRef<PillRegistry>({ fields: new Map(), active: { current: null } });
  const [note, setNote] = useState<string | null>(null);
  const focusAfter = useRef<string | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  // Steps snap to the nearest *legal* position (by height first, then by how far the pointer is from that lane's column),
  // so a drop never needs aiming at a small target. Datapills need the pointer to be over a field.
  const collide: CollisionDetection = ({ active, pointerCoordinates, droppableRects, droppableContainers }) => {
    if (!pointerCoordinates) return [];
    if (String(active.id).startsWith("pill:")) {
      return droppableContainers.filter((c) => String(c.id).startsWith("field:")).flatMap((c) => {
        const r = droppableRects.get(c.id);
        return r && pointerCoordinates.x >= r.left && pointerCoordinates.x <= r.right && pointerCoordinates.y >= r.top && pointerCoordinates.y <= r.bottom ? [{ id: c.id }] : [];
      });
    }
    let best: { id: string | number; score: number } | null = null;
    for (const c of droppableContainers) {
      const key = String(c.id);
      if (!parseGap(key) || problems.get(key)) continue;
      const r = droppableRects.get(c.id);
      if (!r) continue;
      const dy = Math.abs(pointerCoordinates.y - (r.top + r.height / 2));
      const dx = pointerCoordinates.x < r.left ? r.left - pointerCoordinates.x : pointerCoordinates.x > r.right ? pointerCoordinates.x - r.right : 0;
      const score = dy + dx * 0.6;
      if (!best || score < best.score) best = { id: c.id, score };
    }
    return best ? [{ id: best.id }] : [];
  };
  const max = meta.limits.max_nesting;
  // why each drop position would be refused for the step being dragged (computed only while dragging)
  const problems = useMemo(() => {
    const m = new Map<string, string | null>();
    if (dragging) for (const g of allGaps(def)) m.set(gapKey(g), moveProblem(def, dragging, g.ref, g.index, max));
    return m;
  }, [dragging, def, max]);
  useEffect(() => {
    if (!focusAfter.current) return;
    document.querySelector<HTMLElement>(`[data-handle-for="${focusAfter.current}"]`)?.focus();
    focusAfter.current = null;
  });
  const label = (id: string) => { const l = locate(def, id); return l ? (meta.steps.find((m) => m.type === l.step.type)?.label ?? l.step.type) : id; };
  function dropOn(e: DragEndEvent) {
    setDragging(null); setDragPill(null);
    const id = String(e.active.id);
    if (id.startsWith("pill:")) {   // a datapill dropped on a field
      const over = e.over ? String(e.over.id) : "";
      if (over.startsWith("field:")) registry.current.fields.get(over.slice(6))?.(id.slice(5));
      return;
    }
    const gap = e.over ? parseGap(String(e.over.id)) : null;
    if (!gap) return;
    const why = moveProblem(def, id, gap.ref, gap.index, max);
    if (why) { setNote(`Can't move it there: ${why}.`); return; }
    const next = moveStep(def, id, gap.ref, gap.index);
    if (JSON.stringify(next) === JSON.stringify(def)) return;
    edit(next); setSel(id); setNote(`Moved “${label(id)}”.`);
  }
  function keyMove(id: string, dir: -1 | 1) {
    const g = nextGap(def, id, dir, max);
    if (!g) { setNote(`“${label(id)}” can't move ${dir < 0 ? "up" : "down"} any further.`); return; }
    edit(moveStep(def, id, g.ref, g.index)); setSel(id); focusAfter.current = id; setNote(`Moved “${label(id)}” ${dir < 0 ? "up" : "down"}.`);
  }

  const ctxFor = (section: "steps" | "on_error", inLoop = false, inCatch = false): Ctx => ({
    ...props.ctx, root: section === "steps" ? def.steps : def.on_error ?? [], other: section === "steps" ? def.on_error ?? [] : def.steps,
    handler: section === "on_error" || inCatch, inLoop, callOutputs: def.trigger.config?.outputs ?? [],
  });

  const optionsFor = (ref: LaneRef, depth: number): StepMenuItem[] =>
    meta.steps.filter((s) => (s.type !== "condition" && s.type !== "approval" && s.type !== "handle_errors") || depth < meta.limits.max_nesting)
      .filter((s) => s.type !== "return_data" || (def.trigger.type === "call" && ref.section === "steps"))
      .filter((s) => !(s.type === "call_recipe" && (ref.section === "on_error" || laneInCatch(def, ref))))
      .filter((s) => !(isLoopType(s.type) && (depth > 0 || ref.section === "on_error" || laneInCatch(def, ref))) && !((s.type === "approval" || s.type === "wait" || s.type === "throttle") && (ref.section === "on_error" || laneInCatch(def, ref))));

  function add(ref: LaneRef, index: number, type: string, inLoop: boolean) {
    const n: StepNode = { id: newId(allIds(def)), type, config: defaultConfig(type, ctxFor(ref.section, inLoop, laneInCatch(def, ref))), on_error: "fail", max_attempts: 3 };
    if (type === "condition" || type === "approval" || type === "handle_errors") { n.then = []; n.else = []; }
    if (isLoopType(type)) n.then = [];
    edit(insertAt(def, ref, index, n));
    setSel(n.id);
  }

  function renderLane(lane: LaneRef, depth: number, inLoop: boolean): JSX.Element {
    const steps = laneSteps(def, lane);
    const opts = optionsFor(lane, depth);
    const adder = (i: number, empty = false) => canEdit && (
      <AddMenu options={opts} disabled={full} empty={empty} label={empty ? "Add a step" : `Add a step at position ${i + 1}`} onPick={(t) => add(lane, i, t, inLoop)} />
    );
    return (
      <div className={depth > 0 ? "ml-3 border-l-2 pl-3" : ""}>
        {steps.length === 0 && (
          <div className="py-2"><GapSlot gap={{ ref: lane, index: 0 }} active={!!dragging}>
            {adder(0, true) || <span className="text-sm text-muted-foreground">No steps.</span>}</GapSlot></div>
        )}
        {steps.map((s, i) => (
          <div key={s.id}>
            <div className="flex h-5 items-center justify-center"><div className="h-full w-px bg-border" /></div>
            <GapSlot gap={{ ref: lane, index: i }} active={!!dragging}>{adder(i)}</GapSlot>
            <div className="flex h-5 items-center justify-center"><div className="h-full w-px bg-border" /></div>
            {renderCard(s, i, depth, inLoop, lane.section)}
          </div>
        ))}
        {steps.length > 0 && (<><div className="flex h-5 justify-center"><div className="h-full w-px bg-border" /></div>
          <GapSlot gap={{ ref: lane, index: steps.length }} active={!!dragging}>{adder(steps.length)}</GapSlot></>)}
      </div>
    );
  }

  /** A condition's lanes. An else-if link renders flat under its parent (same depth), so long chains stay readable. */
  function renderCondBody(step: StepNode, depth: number, inLoop: boolean, section: "steps" | "on_error", label: string, links: number): JSX.Element {
    const link = (step.else ?? []).length === 1 && step.else![0].else_if ? step.else![0] : null;
    const elseRef: LaneRef = { section, owner: step.id, branch: "else" };
    const addElseIf = () => {
      const n: StepNode = { id: newId(allIds(def)), type: "condition", config: defaultConfig("condition", ctxFor(section, inLoop, laneInCatch(def, elseRef))), on_error: "fail", max_attempts: 3, then: [], else: [], else_if: true };
      edit(insertAt(def, elseRef, 0, n));
      setSel(n.id);
    };
    return (<>
      <div className="text-xs font-medium uppercase text-muted-foreground">{label}</div>
      {renderLane({ section, owner: step.id, branch: "then" }, depth + 1, inLoop)}
      {link ? (
        <div className="space-y-2 border-t pt-2" data-testid="else-if">
          <div className={"flex items-center gap-2 rounded-md " + (sel === link.id ? "ring-2 ring-primary" : "")}>
            <button type="button" className="flex min-w-0 flex-1 items-baseline gap-2 text-left" aria-pressed={sel === link.id} aria-label="Open else-if condition" onClick={() => setSel(link.id)}>
              <span className="text-xs font-medium uppercase text-muted-foreground">Else if</span>
              <span className="min-w-0 truncate text-xs">{summary(link, props)}</span>
            </button>
            {canEdit && <Button type="button" size="sm" variant="ghost" aria-label="Delete else-if" onClick={() => { edit(removeStep(def, link.id)); setSel("trigger"); }}><Trash2 className="h-4 w-4" /></Button>}
          </div>
          {renderCondBody(link, depth, inLoop, section, "Then", links + 1)}
        </div>
      ) : (<>
        <div className="flex items-center justify-between">
          <div className="text-xs font-medium uppercase text-muted-foreground">Otherwise</div>
          {canEdit && (step.else ?? []).length === 0 && links < 10 && (
            <Button type="button" size="sm" variant="ghost" data-testid="add-else-if" onClick={addElseIf}>+ Else if</Button>
          )}
        </div>
        {renderLane(elseRef, depth + 1, inLoop)}
      </>)}
    </>);
  }

  function renderCard(step: StepNode, index: number, depth: number, inLoop: boolean, section: "steps" | "on_error"): JSX.Element {
    const info = meta.steps.find((m) => m.type === step.type);
    const selected = sel === step.id;
    const remove = () => { edit(removeStep(def, step.id)); setSel("trigger"); };
    return (
      <StepShell id={step.id} enabled={canEdit} className={"rounded-lg border bg-card " + (selected ? "ring-2 ring-primary " : "") + (dragging === step.id ? "opacity-40" : "")}>
       {(grab) => (<>
        <div className="flex items-center gap-2 p-3">
         <div className={"flex min-w-0 flex-1 items-center gap-2 " + (canEdit ? "cursor-grab active:cursor-grabbing" : "")} {...grab}>
          {canEdit && <DragHandle id={step.id} label={`Step ${index + 1}, ${info?.label ?? step.type}`} onKeyMove={(d) => keyMove(step.id, d)} />}
          <button type="button" className="flex min-w-0 flex-1 items-center gap-3 text-left" aria-label={`Open step ${index + 1}: ${info?.label ?? step.type}`}
            aria-pressed={selected} onClick={() => setSel(step.id)}
            onKeyDown={(e) => { if (canEdit && (e.key === "Delete" || e.key === "Backspace")) { e.preventDefault(); remove(); } }}>
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">{index + 1}</span>
            <span className="min-w-0"><span className="block truncate text-sm font-medium">{info?.label ?? step.type}</span>
              <span className="block truncate text-xs text-muted-foreground">{summary(step, props)}</span>
              {step.note && <span className="block truncate text-xs italic text-muted-foreground" data-testid="step-note">{step.note}</span>}</span>
          </button>
         </div>
          {props.result && <ResultDot {...outcomeOf(rowsByStep.get(step.id), props.result)} />}
          {canEdit && (
            <div className="flex shrink-0 gap-1">
              <Button type="button" size="sm" variant="ghost" aria-label="Duplicate step" disabled={full} onClick={() => { const r = duplicateStep(def, step.id); edit(r.def); if (r.newId) setSel(r.newId); }}><Copy className="h-4 w-4" /></Button>
              <Button type="button" size="sm" variant="ghost" aria-label="Delete step" onClick={remove}><Trash2 className="h-4 w-4" /></Button>
            </div>
          )}
        </div>
        {(step.type === "condition" || step.type === "approval" || step.type === "handle_errors") && (
          <div className="space-y-2 border-t p-3">
            {step.type === "condition" ? renderCondBody(step, depth, inLoop, section, "If yes", 0) : (<>
              <div className="text-xs font-medium uppercase text-muted-foreground">{step.type === "approval" ? "If approved" : "Monitored steps"}</div>
              {renderLane({ section, owner: step.id, branch: "then" }, depth + 1, inLoop)}
              <div className="text-xs font-medium uppercase text-muted-foreground">{step.type === "approval" ? "If denied or no answer" : "If any of them fails"}</div>
              {renderLane({ section, owner: step.id, branch: "else" }, depth + 1, inLoop)}
            </>)}
          </div>
        )}
        {isLoop(step) && (
          <div className="space-y-2 border-t p-3">
            <div className="text-xs font-medium uppercase text-muted-foreground">{step.type === "for_each_item" ? "For each item" : "For each member"}</div>
            {renderLane({ section, owner: step.id, branch: "then" }, depth + 1, true)}
          </div>
        )}
       </>)}
      </StepShell>
    );
  }

  const located = sel !== "trigger" ? locate(def, sel) : null;
  useEffect(() => { if (sel !== "trigger" && !located) setSel("trigger"); }, [sel, located]);

  const trigInfo = meta.triggers.find((t) => t.type === def.trigger.type);
  const panelCtx = useMemo(() => (located ? ctxFor(located.section, located.inLoop, located.inCatch) : null), [located, def, props.ctx]); // eslint-disable-line react-hooks/exhaustive-deps
  const isAction = located ? meta.steps.find((m) => m.type === located.step.type)?.kind === "action" : false;

  return (
    <DndContext sensors={sensors} collisionDetection={collide} autoScroll={{ threshold: { x: 0, y: 0.2 }, acceleration: 18 }} onDragStart={(e) => { const id = String(e.active.id); if (id.startsWith("pill:")) { setDragPill(id.slice(5)); return; } setDragging(id); setSel(id); setNote(null); setDragWidth(e.active.rect.current.initial?.width ?? null); }} onDragEnd={dropOn} onDragCancel={() => { setDragging(null); setDragPill(null); }}>
    <PillFieldsContext.Provider value={registry.current}>
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_var(--panel-w)] lg:gap-6" style={{ "--panel-w": `${panelW}px` } as React.CSSProperties} data-testid="studio"
      onKeyDown={(e) => {
        const t = e.target as HTMLElement;
        if (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? props.redo() : props.undo(); }
      }}>
      <div className="min-w-0">
        <div className="mb-3 flex items-center gap-2">
          <Button type="button" size="sm" variant="outline" aria-label="Undo" disabled={!props.canUndo} onClick={props.undo}><Undo2 className="h-4 w-4" /></Button>
          <Button type="button" size="sm" variant="outline" aria-label="Redo" disabled={!props.canRedo} onClick={props.redo}><Redo2 className="h-4 w-4" /></Button>
          <Button type="button" size="sm" variant="outline" onClick={() => document.getElementById("test-card")?.scrollIntoView({ behavior: "smooth", block: "center" })}><FlaskConical className="mr-1 h-4 w-4" /> Test</Button>
          <span className="text-xs text-muted-foreground">{countSteps(def)} of {meta.limits.max_steps} steps</span>
          {props.result && <span className="text-xs text-muted-foreground" data-testid="result-note">{props.stale ? "Test results are from an earlier draft" : `Test ${props.result.status}`}</span>}
          <span aria-live="polite" data-testid="studio-note" className={"text-xs " + (note?.startsWith("Can't") ? "text-destructive" : "text-muted-foreground")}>{note}</span>
        </div>
        <div className="mx-auto max-w-xl">
          <button type="button" data-testid="studio-trigger" aria-pressed={sel === "trigger"} onClick={() => setSel("trigger")}
            className={"flex w-full items-center gap-3 rounded-lg border bg-card p-3 text-left " + (sel === "trigger" ? "ring-2 ring-primary" : "")}>
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-foreground"><Zap className="h-4 w-4" /></span>
            <span><span className="block text-sm font-medium">When: {trigInfo?.label ?? def.trigger.type}</span><span className="block text-xs text-muted-foreground">Trigger</span></span>
          </button>
          {renderLane({ section: "steps", owner: null, branch: null }, 0, false)}
          <div className="mt-8 rounded-lg border border-dashed p-3" data-testid="handle-errors">
            <div className="flex items-center gap-2 text-sm font-semibold"><ShieldAlert className="h-4 w-4" /> Handle errors</div>
            <p className="mb-2 mt-1 text-xs text-muted-foreground">Optional, for the whole recipe. If any step above fails for good (after its retries), these steps run with the error as data, and the job is still recorded as failed. Each step can also be set to carry on after a failure.</p>
            <div data-testid="error-handler">{renderLane({ section: "on_error", owner: null, branch: null }, 0, false)}</div>
          </div>
        </div>
      </div>

      <aside className="relative lg:sticky lg:top-4 lg:self-start" aria-label="Step settings" data-testid="studio-panel">
        <PanelResizer width={panelW} onResize={resizePanel} />
        <div className="flex max-h-[calc(100vh-2rem)] flex-col overflow-hidden rounded-xl border bg-card shadow-sm">
          <header className="flex items-center gap-3 border-b px-4 py-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">{sel === "trigger" || !located ? <Zap className="h-4 w-4" /> : <FlaskConical className="h-4 w-4" />}</span>
            <div className="min-w-0">
              <h2 className="truncate text-sm font-semibold">{sel === "trigger" || !located ? `When: ${trigInfo?.label ?? def.trigger.type}` : (meta.steps.find((m) => m.type === located.step.type)?.label ?? located.step.type)}</h2>
              <p className="text-xs text-muted-foreground">{sel === "trigger" || !located ? "Trigger" : <>Step <code>{located.step.id}</code></>}</p>
            </div>
          </header>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 py-4">
            <fieldset disabled={!canEdit} className="min-w-0 space-y-4 border-0 p-0">
              {sel === "trigger" || !located || !panelCtx ? (
                <TriggerCard def={def} meta={meta} groups={groups} setTrigger={props.setTrigger} />
              ) : (
                <>
                  <section aria-label="Setup" className="space-y-3">
                    <StepForm step={located.step} ctx={panelCtx} onChange={(n) => edit(replaceStep(def, n), true)} />
                    <FormulaPreview templates={formulasIn(located.step.config)} run={props.previewFormulas} />
                  </section>
                  {canEdit && located.step.type !== "condition" && <PillTray pills={pillsFor(panelCtx, located.step.id)} />}
                  <section aria-label="Step options" className="space-y-3 border-t pt-4">
                    <div className="space-y-1"><Label htmlFor="step-note">Note (optional)</Label>
                      <textarea id="step-note" rows={2} maxLength={300} placeholder="Why this step exists. Shown on the card; never used when the recipe runs." value={located.step.note ?? ""}
                        onChange={(e) => edit(replaceStep(def, { ...located.step, note: e.target.value || null }), true)} className="w-full rounded-md border bg-background px-3 py-2 text-sm" /></div>
                    {isAction && (
                      <div className="grid gap-3">
                        <div className="space-y-1"><Label>If this step fails</Label>
                          <Select label="On error" value={located.step.on_error ?? "fail"} onChange={(v) => edit(replaceStep(def, { ...located.step, on_error: v as "fail" | "continue" }))}><option value="fail">Fail the job</option><option value="continue">Continue with the next step</option></Select></div>
                        <div className="space-y-1"><Label>Attempts (retries use exponential back-off)</Label>
                          <Select label="Attempts" value={located.step.max_attempts ?? 3} onChange={(v) => edit(replaceStep(def, { ...located.step, max_attempts: Number(v) }))}>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}</Select></div>
                      </div>
                    )}
                  </section>
                  {props.result && (() => {
                    const rows = rowsByStep.get(located.step.id);
                    const o = outcomeOf(rows, props.result);
                    return (
                      <section aria-label="Test result" className="space-y-2 border-t pt-4" data-testid="step-result-panel">
                        <div className="flex items-center gap-2 text-sm font-medium">Test result <ResultDot {...o} /> <span className="font-normal text-muted-foreground">{o.text}{props.stale ? " (earlier draft)" : ""}</span></div>
                        {(rows ?? []).map((r) => (
                          <div key={`${r.seq}-${r.attempt}`} className="space-y-1 text-xs">
                            {r.error && <p className="text-destructive">{r.error}</p>}
                            <div className="text-muted-foreground">Input (redacted)</div><pre className="max-h-40 overflow-auto rounded bg-muted p-2">{JSON.stringify(r.input, null, 2)}</pre>
                            <div className="text-muted-foreground">Output (redacted)</div><pre className="max-h-40 overflow-auto rounded bg-muted p-2">{JSON.stringify(r.output, null, 2)}</pre>
                          </div>
                        ))}
                      </section>
                    );
                  })()}
                </>
              )}
            </fieldset>
          </div>
        </div>
      </aside>
    </div>
    <DragOverlay dropAnimation={{ duration: 120, easing: "ease-out" }}>
      {dragging ? (() => {
          const l = locate(def, dragging);
          const info = l ? meta.steps.find((m) => m.type === l.step.type) : null;
          return (
            <div className="flex items-center gap-3 rounded-lg border-2 border-primary bg-card/90 p-3 opacity-90 shadow-xl" style={{ width: dragWidth ?? undefined }}>
              <GripVertical className="h-4 w-4 text-muted-foreground" />
              <span className="min-w-0"><span className="block truncate text-sm font-medium">{info?.label ?? dragging}</span>
                <span className="block truncate text-xs text-muted-foreground">{l ? summary(l.step, props) : ""}</span></span>
            </div>
          );
        })()
        : dragPill ? <span className="rounded-full border bg-primary/10 px-2 py-0.5 text-xs shadow-lg">{dragPill}</span> : null}
    </DragOverlay>
    </PillFieldsContext.Provider>
    </DndContext>
  );
}
