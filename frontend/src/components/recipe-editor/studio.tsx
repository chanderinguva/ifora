"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { DndContext, DragOverlay, PointerSensor, closestCenter, pointerWithin, useDraggable, useDroppable, useSensor, useSensors, type CollisionDetection, type DragEndEvent } from "@dnd-kit/core";
import { Copy, GripVertical, Plus, Redo2, Trash2, Undo2, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, StepForm, TriggerCard, defaultConfig, pillsFor, type Ctx } from "@/components/recipe-editor/forms";
import { PillFieldsContext, type PillRegistry } from "@/components/recipe-editor/pill-context";
import { PillTray } from "@/components/recipe-editor/pill-tray";
import { allIds, countSteps, duplicateStep, gapKey, insertAt, locate, moveProblem, moveStep, newId, nextGap, parseGap, removeStep, replaceStep, allGaps, type Gap, type LaneRef } from "@/components/recipe-editor/tree";
import { laneSteps } from "@/components/recipe-editor/tree";
import type { Definition, RecipeMeta, StepNode } from "@/lib/recipes";
import type { Group } from "@/lib/types";

type Props = {
  def: Definition; meta: RecipeMeta; ctx: Ctx; groups: Group[]; canEdit: boolean;
  edit: (d: Definition, merge?: boolean) => void; setTrigger: (patch: Partial<Definition["trigger"]>) => void;
  undo: () => void; redo: () => void; canUndo: boolean; canRedo: boolean;
};

function summary(s: StepNode, props: Props): string {
  const c = s.config ?? {};
  const group = (id: unknown) => props.groups.find((g) => g.id === id)?.name ?? "no group chosen";
  switch (s.type) {
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
    case "approval": return c.message ? String(c.message).slice(0, 50) : "Ask for approval";
    default: return "";
  }
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
/** A place a step can be dropped (and where the + button lives). */
function GapSlot({ gap, active, problem, children }: { gap: Gap; active: boolean; problem: string | null; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: gapKey(gap) });
  if (!active) return <div ref={setNodeRef}>{children}</div>;
  const tone = problem ? (isOver ? "border-destructive bg-destructive/10" : "border-transparent opacity-40") : isOver ? "border-primary bg-primary/10" : "border-primary/40";
  return (
    <div ref={setNodeRef} data-testid="drop-slot" data-gap={gapKey(gap)} data-valid={problem ? "no" : "yes"} aria-hidden="true"
      className={"flex h-8 items-center justify-center rounded border-2 border-dashed text-xs " + tone}>
      {isOver ? (problem ?? "Drop here") : ""}
    </div>
  );
}

function DragHandle({ id, label, onKeyMove }: { id: string; label: string; onKeyMove: (dir: -1 | 1) => void }) {
  const { attributes, listeners, setNodeRef } = useDraggable({ id });
  return (
    <button type="button" ref={setNodeRef} {...attributes} {...listeners} data-testid="drag-handle" data-handle-for={id}
      aria-label={`${label}. Drag, or press Alt and the up or down arrow to move it.`}
      className="flex h-7 w-5 shrink-0 cursor-grab touch-none items-center justify-center rounded text-muted-foreground hover:bg-muted active:cursor-grabbing"
      onKeyDown={(e) => { if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); e.stopPropagation(); onKeyMove(e.key === "ArrowUp" ? -1 : 1); } }}>
      <GripVertical className="h-4 w-4" />
    </button>
  );
}

type StepMenuItem = { type: string; label: string; kind: "action" | "control" };

export function Studio(props: Props) {
  const { def, meta, groups, canEdit, edit } = props;
  const [sel, setSel] = useState<string>("trigger");
  const full = countSteps(def) >= meta.limits.max_steps;
  const [dragging, setDragging] = useState<string | null>(null);
  const [dragPill, setDragPill] = useState<string | null>(null);
  const registry = useRef<PillRegistry>({ fields: new Map(), active: { current: null } });
  const [note, setNote] = useState<string | null>(null);
  const focusAfter = useRef<string | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const collide: CollisionDetection = (a) => { const hit = pointerWithin(a); return hit.length || String(a.active.id).startsWith("pill:") ? hit : closestCenter(a); };
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

  const ctxFor = (section: "steps" | "on_error", inLoop = false): Ctx => ({
    ...props.ctx, root: section === "steps" ? def.steps : def.on_error ?? [], other: section === "steps" ? def.on_error ?? [] : def.steps,
    handler: section === "on_error", inLoop,
  });

  const optionsFor = (ref: LaneRef, depth: number): StepMenuItem[] =>
    meta.steps.filter((s) => (s.type !== "condition" && s.type !== "approval") || depth < meta.limits.max_nesting)
      .filter((s) => !(s.type === "for_each_member" && (depth > 0 || ref.section === "on_error")) && !(s.type === "approval" && ref.section === "on_error"));

  function add(ref: LaneRef, index: number, type: string, inLoop: boolean) {
    const n: StepNode = { id: newId(allIds(def)), type, config: defaultConfig(type, ctxFor(ref.section, inLoop)), on_error: "fail", max_attempts: 3 };
    if (type === "condition" || type === "approval") { n.then = []; n.else = []; }
    if (type === "for_each_member") n.then = [];
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
          <div className="py-2"><GapSlot gap={{ ref: lane, index: 0 }} active={!!dragging} problem={problems.get(gapKey({ ref: lane, index: 0 })) ?? null}>
            {adder(0, true) || <span className="text-sm text-muted-foreground">No steps.</span>}</GapSlot></div>
        )}
        {steps.map((s, i) => (
          <div key={s.id}>
            <div className="flex h-5 items-center justify-center"><div className="h-full w-px bg-border" /></div>
            <GapSlot gap={{ ref: lane, index: i }} active={!!dragging} problem={problems.get(gapKey({ ref: lane, index: i })) ?? null}>{adder(i)}</GapSlot>
            <div className="flex h-5 items-center justify-center"><div className="h-full w-px bg-border" /></div>
            {renderCard(s, i, depth, inLoop, lane.section)}
          </div>
        ))}
        {steps.length > 0 && (<><div className="flex h-5 justify-center"><div className="h-full w-px bg-border" /></div>
          <GapSlot gap={{ ref: lane, index: steps.length }} active={!!dragging} problem={problems.get(gapKey({ ref: lane, index: steps.length })) ?? null}>{adder(steps.length)}</GapSlot></>)}
      </div>
    );
  }

  function renderCard(step: StepNode, index: number, depth: number, inLoop: boolean, section: "steps" | "on_error"): JSX.Element {
    const info = meta.steps.find((m) => m.type === step.type);
    const selected = sel === step.id;
    const remove = () => { edit(removeStep(def, step.id)); setSel("trigger"); };
    return (
      <div className={"rounded-lg border bg-card " + (selected ? "ring-2 ring-primary " : "") + (dragging === step.id ? "opacity-40" : "")} data-testid="studio-card" data-step-id={step.id}>
        <div className="flex items-center gap-2 p-3">
          {canEdit && <DragHandle id={step.id} label={`Step ${index + 1}, ${info?.label ?? step.type}`} onKeyMove={(d) => keyMove(step.id, d)} />}
          <button type="button" className="flex min-w-0 flex-1 items-center gap-3 text-left" aria-label={`Open step ${index + 1}: ${info?.label ?? step.type}`}
            aria-pressed={selected} onClick={() => setSel(step.id)}
            onKeyDown={(e) => { if (canEdit && (e.key === "Delete" || e.key === "Backspace")) { e.preventDefault(); remove(); } }}>
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">{index + 1}</span>
            <span className="min-w-0"><span className="block truncate text-sm font-medium">{info?.label ?? step.type}</span>
              <span className="block truncate text-xs text-muted-foreground">{summary(step, props)}</span></span>
          </button>
          {canEdit && (
            <div className="flex shrink-0 gap-1">
              <Button type="button" size="sm" variant="ghost" aria-label="Duplicate step" disabled={full} onClick={() => { const r = duplicateStep(def, step.id); edit(r.def); if (r.newId) setSel(r.newId); }}><Copy className="h-4 w-4" /></Button>
              <Button type="button" size="sm" variant="ghost" aria-label="Delete step" onClick={remove}><Trash2 className="h-4 w-4" /></Button>
            </div>
          )}
        </div>
        {(step.type === "condition" || step.type === "approval") && (
          <div className="space-y-2 border-t p-3">
            <div className="text-xs font-medium uppercase text-muted-foreground">{step.type === "approval" ? "If approved" : "If yes"}</div>
            {renderLane({ section, owner: step.id, branch: "then" }, depth + 1, inLoop)}
            <div className="text-xs font-medium uppercase text-muted-foreground">{step.type === "approval" ? "If denied or no answer" : "Otherwise"}</div>
            {renderLane({ section, owner: step.id, branch: "else" }, depth + 1, inLoop)}
          </div>
        )}
        {step.type === "for_each_member" && (
          <div className="space-y-2 border-t p-3">
            <div className="text-xs font-medium uppercase text-muted-foreground">For each member</div>
            {renderLane({ section, owner: step.id, branch: "then" }, depth + 1, true)}
          </div>
        )}
      </div>
    );
  }

  const located = sel !== "trigger" ? locate(def, sel) : null;
  useEffect(() => { if (sel !== "trigger" && !located) setSel("trigger"); }, [sel, located]);

  const trigInfo = meta.triggers.find((t) => t.type === def.trigger.type);
  const panelCtx = useMemo(() => (located ? ctxFor(located.section, located.inLoop) : null), [located, def, props.ctx]); // eslint-disable-line react-hooks/exhaustive-deps
  const isAction = located ? meta.steps.find((m) => m.type === located.step.type)?.kind === "action" : false;

  return (
    <DndContext sensors={sensors} collisionDetection={collide} onDragStart={(e) => { const id = String(e.active.id); if (id.startsWith("pill:")) { setDragPill(id.slice(5)); return; } setDragging(id); setSel(id); setNote(null); }} onDragEnd={dropOn} onDragCancel={() => { setDragging(null); setDragPill(null); }}>
    <PillFieldsContext.Provider value={registry.current}>
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_26rem]" data-testid="studio"
      onKeyDown={(e) => {
        const t = e.target as HTMLElement;
        if (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? props.redo() : props.undo(); }
      }}>
      <div className="min-w-0">
        <div className="mb-3 flex items-center gap-2">
          <Button type="button" size="sm" variant="outline" aria-label="Undo" disabled={!props.canUndo} onClick={props.undo}><Undo2 className="h-4 w-4" /></Button>
          <Button type="button" size="sm" variant="outline" aria-label="Redo" disabled={!props.canRedo} onClick={props.redo}><Redo2 className="h-4 w-4" /></Button>
          <span className="text-xs text-muted-foreground">{countSteps(def)} of {meta.limits.max_steps} steps</span>
          <span aria-live="polite" data-testid="studio-note" className={"text-xs " + (note?.startsWith("Can't") ? "text-destructive" : "text-muted-foreground")}>{note}</span>
        </div>
        <div className="mx-auto max-w-xl">
          <button type="button" data-testid="studio-trigger" aria-pressed={sel === "trigger"} onClick={() => setSel("trigger")}
            className={"flex w-full items-center gap-3 rounded-lg border bg-card p-3 text-left " + (sel === "trigger" ? "ring-2 ring-primary" : "")}>
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-foreground"><Zap className="h-4 w-4" /></span>
            <span><span className="block text-sm font-medium">When: {trigInfo?.label ?? def.trigger.type}</span><span className="block text-xs text-muted-foreground">Trigger</span></span>
          </button>
          {renderLane({ section: "steps", owner: null, branch: null }, 0, false)}
          <div className="mt-8 border-t pt-4">
            <h3 className="text-sm font-semibold">If a step fails</h3>
            <p className="mb-2 text-xs text-muted-foreground">Optional. Runs after a step fails for good (after its retries); the job is still recorded as failed.</p>
            <div data-testid="error-handler">{renderLane({ section: "on_error", owner: null, branch: null }, 0, false)}</div>
          </div>
        </div>
      </div>

      <aside className="lg:sticky lg:top-4 lg:self-start" aria-label="Step settings" data-testid="studio-panel">
        <fieldset disabled={!canEdit} className="min-w-0 border-0 p-0">
          {sel === "trigger" || !located || !panelCtx ? (
            <TriggerCard def={def} meta={meta} groups={groups} setTrigger={props.setTrigger} />
          ) : (
            <Card>
              <CardHeader className="py-3"><CardTitle className="text-base">{meta.steps.find((m) => m.type === located.step.type)?.label ?? located.step.type}
                <code className="ml-2 text-xs font-normal text-muted-foreground">{located.step.id}</code></CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <StepForm step={located.step} ctx={panelCtx} onChange={(n) => edit(replaceStep(def, n), true)} />
                {canEdit && located.step.type !== "condition" && <PillTray pills={pillsFor(panelCtx, located.step.id)} />}
                {isAction && (
                  <div className="grid gap-3 border-t pt-3">
                    <div className="space-y-1"><Label>If this step fails</Label>
                      <Select label="On error" value={located.step.on_error ?? "fail"} onChange={(v) => edit(replaceStep(def, { ...located.step, on_error: v as "fail" | "continue" }))}><option value="fail">Fail the job</option><option value="continue">Continue with the next step</option></Select></div>
                    <div className="space-y-1"><Label>Attempts (retries use exponential back-off)</Label>
                      <Select label="Attempts" value={located.step.max_attempts ?? 3} onChange={(v) => edit(replaceStep(def, { ...located.step, max_attempts: Number(v) }))}>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}</Select></div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </fieldset>
      </aside>
    </div>
    <DragOverlay>
      {dragging ? <div className="rounded-lg border bg-card px-4 py-3 text-sm font-medium shadow-lg">{label(dragging)}</div>
        : dragPill ? <span className="rounded-full border bg-primary/10 px-2 py-0.5 text-xs shadow-lg">{dragPill}</span> : null}
    </DragOverlay>
    </PillFieldsContext.Provider>
    </DndContext>
  );
}
