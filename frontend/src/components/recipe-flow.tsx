"use client";

import { cn } from "@/lib/utils";
import { isLoop } from "@/components/recipe-editor/tree";
import type { Definition, RecipeMeta, StepNode } from "@/lib/recipes";

const TONE: Record<string, string> = {
  action: "border-blue-300 bg-blue-50 dark:border-blue-800 dark:bg-blue-950",
  control: "border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950",
};

function Arrow() {
  return <div aria-hidden className="mx-auto h-4 w-px bg-border" />;
}

function Node({ step, meta, onSelect }: { step: StepNode; meta: RecipeMeta; onSelect: (id: string) => void }) {
  const info = meta.steps.find((m) => m.type === step.type);
  const kind = info?.kind ?? "action";
  const branches = step.type === "condition" || step.type === "approval" || step.type === "handle_errors";
  const detail = step.type === "log" || step.type === "send_slack" ? step.config.message : step.type === "send_email" ? step.config.subject : step.type === "approval" ? step.config.message : "";
  return (
    <div className={cn("rounded-md border p-2", TONE[kind])} data-testid="flow-node">
      <button type="button" onClick={() => onSelect(step.id)} className="block w-full text-left text-sm" aria-label={`Open step ${step.id}`}>
        <span className="font-medium">{step.name || info?.label || step.type}</span> <code className="text-xs text-muted-foreground">{step.id}</code>
        {detail ? <div className="truncate text-xs text-muted-foreground">{String(detail)}</div> : null}
      </button>
      {branches && (
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          <Lane title={step.type === "approval" ? "Approved" : step.type === "handle_errors" ? "Monitored" : "Then"} steps={step.then ?? []} meta={meta} onSelect={onSelect} />
          <Lane title={step.type === "approval" ? "Denied / no answer" : step.type === "handle_errors" ? "On error" : "Otherwise"} steps={step.else ?? []} meta={meta} onSelect={onSelect} />
        </div>
      )}
      {isLoop(step) && <div className="mt-2"><Lane title={step.type === "for_each_item" ? "For each item" : "For each member"} steps={step.then ?? []} meta={meta} onSelect={onSelect} /></div>}
    </div>
  );
}

function Lane({ title, steps, meta, onSelect }: { title: string; steps: StepNode[]; meta: RecipeMeta; onSelect: (id: string) => void }) {
  return (
    <div className="rounded border border-dashed bg-background/60 p-2">
      <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">{title}</div>
      {steps.length === 0 ? <div className="text-xs text-muted-foreground">nothing</div> : <Sequence steps={steps} meta={meta} onSelect={onSelect} />}
    </div>
  );
}

function Sequence({ steps, meta, onSelect }: { steps: StepNode[]; meta: RecipeMeta; onSelect: (id: string) => void }) {
  return (
    <div>
      {steps.map((s, i) => (
        <div key={s.id}>
          {i > 0 && <Arrow />}
          <Node step={s} meta={meta} onSelect={onSelect} />
        </div>
      ))}
    </div>
  );
}

/** A picture of the recipe: trigger, then the steps with their branches and loops. Click a box to edit that step. */
export function FlowDiagram({ def, meta, onSelect }: { def: Definition; meta: RecipeMeta; onSelect: (id: string) => void }) {
  const trig = meta.triggers.find((t) => t.type === def.trigger.type);
  return (
    <div className="max-w-3xl" data-testid="flow-diagram">
      <div className="rounded-md border border-emerald-300 bg-emerald-50 p-2 text-sm dark:border-emerald-800 dark:bg-emerald-950">
        <span className="font-medium">When: {trig?.label ?? def.trigger.type}</span>
        {def.trigger.filter.length > 0 && <div className="text-xs text-muted-foreground">only if {def.trigger.filter.length} condition(s) match</div>}
      </div>
      {def.steps.length > 0 && <Arrow />}
      <Sequence steps={def.steps} meta={meta} onSelect={onSelect} />
      {def.steps.length === 0 && <p className="mt-2 text-sm text-muted-foreground">No steps yet. Add them in the Steps view.</p>}
      {(def.on_error ?? []).length > 0 && (
        <div className="mt-4"><div className="mb-1 text-sm font-medium">If a step fails</div><Sequence steps={def.on_error ?? []} meta={meta} onSelect={onSelect} /></div>
      )}
    </div>
  );
}
