/** Pure helpers for editing a recipe's step tree (no React). Lanes are addressed by owner step id + branch. */
import type { Definition, StepNode } from "@/lib/recipes";

/** Steps that repeat their nested steps: one per group member, or one per list item. */
export const isLoopType = (t: string) => t === "for_each_member" || t === "for_each_item";
export const isLoop = (s: { type: string }) => isLoopType(s.type);

export type Section = "steps" | "on_error";
export type LaneRef = { section: Section; owner: string | null; branch: "then" | "else" | null };

export function laneSteps(def: Definition, ref: LaneRef): StepNode[] {
  const root = (ref.section === "steps" ? def.steps : def.on_error) ?? [];
  if (!ref.owner) return root;
  const owner = find(root, ref.owner);
  return (ref.branch === "else" ? owner?.else : owner?.then) ?? [];
}

function mapLane(steps: StepNode[], ref: LaneRef, fn: (s: StepNode[]) => StepNode[]): StepNode[] {
  if (!ref.owner) return fn(steps);
  return steps.map((s) => {
    if (s.id === ref.owner) {
      const key = ref.branch === "else" ? "else" : "then";
      return { ...s, [key]: fn(s[key] ?? []) };
    }
    return { ...s, then: s.then ? mapLane(s.then, ref, fn) : s.then, else: s.else ? mapLane(s.else, ref, fn) : s.else };
  });
}

export function editLane(def: Definition, ref: LaneRef, fn: (s: StepNode[]) => StepNode[]): Definition {
  return ref.section === "steps"
    ? { ...def, steps: mapLane(def.steps, ref, fn) }
    : { ...def, on_error: mapLane(def.on_error ?? [], ref, fn) };
}

export function find(steps: StepNode[], id: string): StepNode | undefined {
  for (const s of steps) {
    if (s.id === id) return s;
    const hit = find(s.then ?? [], id) ?? find(s.else ?? [], id);
    if (hit) return hit;
  }
  return undefined;
}

export type Located = { step: StepNode; section: Section; inLoop: boolean; inCatch: boolean };
export function locate(def: Definition, id: string): Located | null {
  const walk = (steps: StepNode[], loop: boolean, section: Section, catching: boolean): Located | null => {
    for (const s of steps) {
      if (s.id === id) return { step: s, section, inLoop: loop, inCatch: catching };
      const inner = loop || isLoop(s);
      const hit = walk(s.then ?? [], inner, section, catching) ?? walk(s.else ?? [], loop, section, catching || s.type === "handle_errors");
      if (hit) return hit;
    }
    return null;
  };
  return walk(def.steps, false, "steps", false) ?? walk(def.on_error ?? [], false, "on_error", false);
}

export function replaceStep(def: Definition, next: StepNode): Definition {
  const go = (steps: StepNode[]): StepNode[] =>
    steps.map((s) => (s.id === next.id ? next : { ...s, then: s.then ? go(s.then) : s.then, else: s.else ? go(s.else) : s.else }));
  return { ...def, steps: go(def.steps), on_error: def.on_error ? go(def.on_error) : def.on_error };
}

export function removeStep(def: Definition, id: string): Definition {
  const go = (steps: StepNode[]): StepNode[] =>
    steps.filter((s) => s.id !== id).map((s) => ({ ...s, then: s.then ? go(s.then) : s.then, else: s.else ? go(s.else) : s.else }));
  return { ...def, steps: go(def.steps), on_error: def.on_error ? go(def.on_error) : def.on_error };
}

export function allIds(def: Definition): string[] {
  const out: string[] = [];
  const go = (steps: StepNode[]) => steps.forEach((s) => { out.push(s.id); go(s.then ?? []); go(s.else ?? []); });
  go(def.steps); go(def.on_error ?? []);
  return out;
}

export function newId(taken: string[]): string {
  let n = taken.length + 1;
  while (taken.includes(`s${n}`)) n += 1;
  return `s${n}`;
}

/** A copy with fresh ids all the way down (ids must be unique across the recipe). */
export function cloneStep(step: StepNode, taken: string[]): StepNode {
  const used = [...taken];
  const copy = (s: StepNode): StepNode => {
    const id = newId(used);
    used.push(id);
    return { ...s, id, config: JSON.parse(JSON.stringify(s.config)), then: s.then?.map(copy), else: s.else?.map(copy) };
  };
  return copy(step);
}

/** Insert `step` at `index` of a lane. */
export function insertAt(def: Definition, ref: LaneRef, index: number, step: StepNode): Definition {
  return editLane(def, ref, (list) => [...list.slice(0, index), step, ...list.slice(index)]);
}

export function duplicateStep(def: Definition, id: string): { def: Definition; newId: string | null } {
  let created: string | null = null;
  const go = (steps: StepNode[]): StepNode[] =>
    steps.flatMap((s) => {
      if (s.id === id) {
        const c = cloneStep(s, allIds(def));
        created = c.id;
        return [s, c];
      }
      return [{ ...s, then: s.then ? go(s.then) : s.then, else: s.else ? go(s.else) : s.else }];
    });
  return { def: { ...def, steps: go(def.steps), on_error: def.on_error ? go(def.on_error) : def.on_error }, newId: created };
}

export function countSteps(def: Definition): number {
  return allIds({ ...def, on_error: [] }).length;
}

// ---- moving steps (drag and drop, keyboard) ---------------------------------------------------------------------

import { stepsBefore } from "@/lib/recipes";

const BRANCHING = ["condition", "approval", "handle_errors"];
const isBranching = (s: StepNode) => BRANCHING.includes(s.type);

function pathTo(steps: StepNode[], id: string, trail: StepNode[] = []): StepNode[] | null {
  for (const s of steps) {
    if (s.id === id) return [...trail, s];
    const hit = pathTo(s.then ?? [], id, [...trail, s]) ?? pathTo(s.else ?? [], id, [...trail, s]);
    if (hit) return hit;
  }
  return null;
}
const pathOf = (def: Definition, id: string) => pathTo(def.steps, id) ?? pathTo(def.on_error ?? [], id);

/** How deep a lane sits: the top level is 0, a branch of a top-level step is 1, and so on. */
export function laneDepth(def: Definition, ref: LaneRef): number {
  if (!ref.owner) return 0;
  const p = pathOf(def, ref.owner);
  return p ? p.filter((x) => !x.else_if && (isBranching(x) || x.type === "for_each_member")).length : 0;  // an else-if sits at its parent's level
}
/** Is this lane one of a Handle errors block's "on error" lanes, or nested inside one? (Same rules as the recipe-level error steps.) */
export function laneInCatch(def: Definition, ref: LaneRef): boolean {
  if (!ref.owner) return false;
  const p = pathOf(def, ref.owner);
  if (!p) return false;
  if (ref.branch === "else" && p[p.length - 1].type === "handle_errors") return true;
  return p.slice(0, -1).some((x, i) => x.type === "handle_errors" && (x.else ?? []).includes(p[i + 1]));
}
export function laneInLoop(def: Definition, ref: LaneRef): boolean {
  if (!ref.owner) return false;
  return (pathOf(def, ref.owner) ?? []).some((s) => isLoop(s));
}

/** How many levels below this step the deepest if/else or approval sits (0 = the step itself is one; -1 = there is none). */
function branchHeight(s: StepNode): number {
  const kids = [...(s.then ?? []), ...(s.else ?? [])].map((k) => [branchHeight(k), k.else_if ? 0 : 1]).filter(([h]) => h >= 0).map(([h, up]) => h + up);  // an else-if adds no level
  const inner = kids.length ? Math.max(...kids) : -1;
  return isBranching(s) ? Math.max(0, inner) : isLoop(s) ? inner : -1;
}

const text = (s: StepNode) => JSON.stringify(s.config ?? {});
function flat(steps: StepNode[]): StepNode[] { return steps.flatMap((s) => [s, ...flat(s.then ?? []), ...flat(s.else ?? [])]); }

/** Datapill references that are not allowed where they are. Used to refuse only the moves that make things worse. */
export function pillProblems(def: Definition): string[] {
  const out: string[] = [];
  const check = (root: StepNode[], section: Section) => {
    const walk = (steps: StepNode[], inLoop: boolean, catching = section === "on_error") => {
      for (const s of steps) {
        const t = text(s);
        const earlier = stepsBefore(root, s.id);
        const before = new Set(earlier.map((x) => x.id));
        const vars = new Set(earlier.filter((x) => x.type === "set_variable").map((x) => String(x.config?.name ?? "")));
        for (const m of t.matchAll(/(?:\{\{\s*|")vars\.([a-z][a-z0-9_]*)/g)) if (!vars.has(m[1])) out.push(`${s.id}:vars.${m[1]}`);
        for (const m of t.matchAll(/(?:\{\{\s*|")steps\.([a-z][a-z0-9_]*)/g)) if (!before.has(m[1])) out.push(`${s.id}:steps.${m[1]}`);
        if (/(?:\{\{\s*|")loop\./.test(t) && !inLoop) out.push(`${s.id}:loop`);
        if (/(?:\{\{\s*|")error\./.test(t) && !catching) out.push(`${s.id}:error`);
        walk(s.then ?? [], inLoop || isLoop(s), catching);
        walk(s.else ?? [], inLoop, catching || s.type === "handle_errors");
      }
    };
    walk(root, false);
  };
  check(def.steps, "steps");
  check(def.on_error ?? [], "on_error");
  return out;
}

export function moveProblem(def: Definition, id: string, ref: LaneRef, index: number, maxNesting: number): string | null {
  const me = pathOf(def, id);
  if (!me) return "That step no longer exists";
  const step = me[me.length - 1];
  if (ref.owner && (ref.owner === id || flat([step]).some((s) => s.id === ref.owner))) return "A step cannot be moved inside itself";
  if (step.else_if) return "An else-if belongs to its condition; delete it there instead";
  if (laneSteps(def, ref).some((x) => x.else_if)) return "That lane holds an else-if; add steps inside the else-if instead";
  const d = laneDepth(def, ref);
  const h = branchHeight(step);
  if (h >= 0 && d + h >= maxNesting) return `Steps can be nested ${maxNesting} levels deep at most`;
  if (flat([step]).some((s) => isLoop(s)) && (d > 0 || ref.section === "on_error")) return "A repeat step must sit at the top level of the main steps";
  if ((ref.section === "on_error" || laneInCatch(def, ref)) && flat([step]).some((s) => s.type === "approval" || isLoop(s) || s.type === "wait" || s.type === "throttle" || s.type === "call_recipe" || s.type === "return_data")) return "Approvals, repeats, waits, throttles and recipe calls cannot be used in the error steps";
  const moved = moveStep(def, id, ref, index);
  const before = new Set(pillProblems(def));
  const worse = pillProblems(moved).find((p) => !before.has(p));
  if (worse) {
    const [sid, what] = worse.split(":");
    return what === "loop" ? `Step ${sid} uses data from the current repeat item, so it has to stay inside the repeat`
      : what === "error" ? `Step ${sid} uses the error message, so it has to stay in the error steps`
      : what.startsWith("vars.") ? `Step ${sid} uses the variable ${what.slice(5)}, which would then be set later`
      : `Step ${sid} uses data from ${what.replace("steps.", "step ")}, which would then come later`;
  }
  return null;
}

export function moveStep(def: Definition, id: string, ref: LaneRef, index: number): Definition {
  const p = pathOf(def, id);
  if (!p) return def;
  const step = p[p.length - 1];
  // the gap index is relative to the lane before the step is lifted out of it
  const parent = p.length > 1 ? p[p.length - 2] : null;
  const wasSection: Section = def.steps && pathTo(def.steps, id) ? "steps" : "on_error";
  const before = laneSteps(def, { section: wasSection, owner: parent?.id ?? null, branch: parent ? ((parent.then ?? []).some((s) => s.id === id) ? "then" : "else") : null });
  const from = before.findIndex((s) => s.id === id);
  const sameLane = ref.section === wasSection && (ref.owner ?? null) === (parent?.id ?? null)
    && (!parent || (ref.branch === "then") === (parent.then ?? []).some((s) => s.id === id));
  const target = sameLane && from < index ? index - 1 : index;
  return insertAt(removeStep(def, id), ref, target, step);
}

export type Gap = { ref: LaneRef; index: number };
export const gapKey = (g: Gap) => `${g.ref.section}|${g.ref.owner ?? ""}|${g.ref.branch ?? ""}|${g.index}`;
export function parseGap(key: string): Gap | null {
  const m = key.match(/^(steps|on_error)\|([^|]*)\|([^|]*)\|(\d+)$/);
  return m ? { ref: { section: m[1] as Section, owner: m[2] || null, branch: (m[3] || null) as LaneRef["branch"] }, index: Number(m[4]) } : null;
}

/** Every drop position in the order they appear on screen. */
export function allGaps(def: Definition): Gap[] {
  const out: Gap[] = [];
  const lane = (section: Section, steps: StepNode[], owner: string | null, branch: LaneRef["branch"]) => {
    const ref = { section, owner, branch };
    steps.forEach((s, i) => {
      out.push({ ref, index: i });
      if (isBranching(s) || isLoop(s)) lane(section, s.then ?? [], s.id, "then");
      if (isBranching(s)) lane(section, s.else ?? [], s.id, "else");
    });
    out.push({ ref, index: steps.length });
  };
  lane("steps", def.steps, null, null);
  lane("on_error", def.on_error ?? [], null, null);
  return out;
}

/** Where Alt+Up / Alt+Down would put a step: the next legal drop position in that direction, or null. */
export function nextGap(def: Definition, id: string, dir: -1 | 1, maxNesting: number): Gap | null {
  const gaps = allGaps(def);
  const p = pathOf(def, id);
  if (!p) return null;
  const parent = p.length > 1 ? p[p.length - 2] : null;
  const section: Section = pathTo(def.steps, id) ? "steps" : "on_error";
  const branch: LaneRef["branch"] = parent ? ((parent.then ?? []).some((s) => s.id === id) ? "then" : "else") : null;
  const lane = laneSteps(def, { section, owner: parent?.id ?? null, branch });
  const i = lane.findIndex((s) => s.id === id);
  const same = (g: Gap, k: number) => gapKey({ ref: { section, owner: parent?.id ?? null, branch }, index: k }) === gapKey(g);
  const here = gaps.findIndex((g) => same(g, dir === 1 ? i + 1 : i));
  for (let k = here + dir; k >= 0 && k < gaps.length; k += dir) {
    const g = gaps[k];
    if (same(g, i) || same(g, i + 1)) continue;
    if (!moveProblem(def, id, g.ref, g.index, maxNesting)) return g;
  }
  return null;
}
