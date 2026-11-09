/** Pure helpers for editing a recipe's step tree (no React). Lanes are addressed by owner step id + branch. */
import type { Definition, StepNode } from "@/lib/recipes";

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

export type Located = { step: StepNode; section: Section; inLoop: boolean };
export function locate(def: Definition, id: string): Located | null {
  const walk = (steps: StepNode[], loop: boolean, section: Section): Located | null => {
    for (const s of steps) {
      if (s.id === id) return { step: s, section, inLoop: loop };
      const inner = loop || s.type === "for_each_member";
      const hit = walk(s.then ?? [], inner, section) ?? walk(s.else ?? [], loop, section);
      if (hit) return hit;
    }
    return null;
  };
  return walk(def.steps, false, "steps") ?? walk(def.on_error ?? [], false, "on_error");
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
