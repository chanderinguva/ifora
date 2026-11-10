/** Types and helpers for the recipe builder (ADR 008). */

export type Comparison = { left: string; operator: string; value: string };

export type StepNode = {
  id: string;
  type: string;
  name?: string | null;
  note?: string | null;
  config: Record<string, any>;
  on_error?: "fail" | "continue";
  max_attempts?: number;
  then?: StepNode[];
  else?: StepNode[];
};

export type Definition = {
  trigger: { type: string; config: Record<string, any>; filter: Comparison[] };
  steps: StepNode[];
  on_error?: StepNode[];
};

export type RecipeSummary = {
  id: number;
  name: string;
  description: string | null;
  enabled: boolean;
  trigger_type: string;
  published_version: number | null;
  published_trigger_type: string | null;
  has_unpublished_changes: boolean;
  webhook_path: string | null;
  webhook_secret_set: boolean;
  last_job: { id: number; status: string; created_at: string } | null;
  created_at: string;
  updated_at: string;
  draft?: Definition;
  webhook_secret?: string;
  owner?: { id: number; email: string } | null;
  editors?: { id: number; email: string }[];
  rate_limit_per_hour?: number | null;
  effective_rate_limit_per_hour?: number;
  throttled_count?: number;
  last_throttled_at?: string | null;
  last_alert_at?: string | null;
  can_edit?: boolean | null;
  can_manage?: boolean | null;
};

export type RecipeHealth = {
  recipe_id: number; name: string; enabled: boolean; total: number; by_status: Record<string, number>;
  failure_rate: number | null; p50_seconds: number | null; p95_seconds: number | null; throttled_count: number;
  alerting: boolean; last_alert_at: string | null;
};
export type Metrics = {
  window_hours: number; items: RecipeHealth[];
  queue: { queued: number; waiting: number; oldest_queued_age_seconds: number | null };
  alert_rule: { min_jobs: number; failure_rate: number; window_minutes: number };
};

export type Pill = { path: string; label: string };
export type RecipeMeta = {
  triggers: { type: string; label: string; description: string; fields: Pill[]; payload_pills: boolean }[];
  steps: { type: string; label: string; kind: "action" | "control"; outputs: string[] }[];
  operators: string[];
  managed_attributes: { key: string; display_name: string; data_type: string; enum_options: string[] | null }[];
  safe_user_fields: string[];
  limits: { max_steps: number; max_nesting: number };
  callable_recipes?: { id: number; name: string; inputs: { name: string; type: string; required: boolean }[]; outputs: string[] }[];
  lookup_tables?: { name: string; columns: { name: string; type: string }[]; key_column: string | null; admin_managed: boolean }[];
  functions?: { name: string; signature: string; description: string; example: string }[];
};

export type JobStep = {
  seq: number;
  step_id: string;
  name: string | null;
  type: string;
  status: string;
  attempt: number;
  input: unknown;
  output: unknown;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
};
export type Job = {
  id: number;
  recipe_id: number;
  recipe_name: string | null;
  version: number | null;
  mode: string;
  status: string;
  trigger_type: string;
  error: string | null;
  executed_steps: number;
  in_handler?: boolean;
  approval?: { message: string; step_id: string; requested_at: string; expires_at?: string; decision: string | null } | null;
  cancel_requested?: boolean;
  rerun_of?: number | null;
  created_at: string;
  finished_at: string | null;
  trigger?: unknown;
  steps?: JobStep[];
};
export type Connection = {
  id: number;
  name: string;
  kind: "bearer" | "header" | "oauth2_client_credentials" | "slack_webhook";
  header_name: string | null;
  allowed_host: string;
  allowed_paths?: string[];
  client_id?: string | null;
  token_url?: string | null;
  scope?: string | null;
  has_secret: boolean;
  restricted?: boolean;
  can_use?: boolean;
  can_manage?: boolean;
  allowed_users?: number[] | null;
};

export const OPERATOR_LABELS: Record<string, string> = {
  equals: "equals", not_equals: "does not equal", contains: "contains", starts_with: "starts with",
  ends_with: "ends with", is_set: "is set", is_not_set: "is not set", greater_than: "is greater than", less_than: "is less than",
};

export const blankDefinition = (): Definition => ({ trigger: { type: "user.created", config: {}, filter: [] }, steps: [] });

export function allSteps(steps: StepNode[]): StepNode[] {
  const out: StepNode[] = [];
  for (const s of steps) {
    out.push(s);
    out.push(...allSteps(s.then ?? []), ...allSteps(s.else ?? []));
  }
  return out;
}

export function nextStepId(steps: StepNode[]): string {
  const used = new Set(allSteps(steps).map((s) => s.id));
  let n = used.size + 1;
  while (used.has(`s${n}`)) n++;
  return `s${n}`;
}

/** Steps that run before `targetId` (same order as the server uses to validate datapills). */
export function stepsBefore(steps: StepNode[], targetId: string | null): StepNode[] {
  const out: StepNode[] = [];
  let done = false;
  const walk = (list: StepNode[]) => {
    for (const s of list) {
      if (done) return;
      if (s.id === targetId) { done = true; return; }
      out.push(s);
      walk(s.then ?? []);
      walk(s.else ?? []);
    }
  };
  walk(steps);
  return out;
}

/** `forDecision`: leave out what a recipe-writable lookup table returns (the server refuses it in decisions and state changes). */
export function stepPills(meta: RecipeMeta, before: StepNode[], forDecision = false): Pill[] {
  const pills: Pill[] = [];
  for (const s of before) {
    const info = meta.steps.find((m) => m.type === s.type);
    const label = s.name || info?.label || s.type;
    const lt = s.type === "lookup_row" ? meta.lookup_tables?.find((t) => t.name === s.config?.table) : undefined;
    if (s.type === "lookup_row" && forDecision && !(lt?.admin_managed)) continue;
    for (const o of info?.outputs ?? []) pills.push({ path: `steps.${s.id}.output.${o}`, label: `${label} (${s.id}): ${o}` });
    for (const c of lt?.columns ?? []) pills.push({ path: `steps.${s.id}.output.row.${c.name}`, label: `${label} (${s.id}): row ${c.name}` });
    if (s.type === "call_recipe") for (const o of meta.callable_recipes?.find((r) => r.id === s.config?.recipe_id)?.outputs ?? []) pills.push({ path: `steps.${s.id}.output.result.${o}`, label: `${label} (${s.id}): ${o}` });
    if (s.type === "set_variable" && s.config?.name) pills.push({ path: `vars.${s.config.name}`, label: `Variable: ${s.config.name}` });
    if (info?.kind === "action") pills.push({ path: `steps.${s.id}.output.error`, label: `${label} (${s.id}): error (when set to continue)` });
  }
  return pills;
}

/** Datapills that are safe to base a decision on: not editable by the user themselves (mirrors the server rule). */
export function decisionPills(meta: RecipeMeta, triggerType: string, before: StepNode[]): Pill[] {
  const managed = new Set(meta.managed_attributes.map((a) => a.key));
  const safe = new Set(meta.safe_user_fields.map((f) => `trigger.user.${f}`));
  const trig = meta.triggers.find((t) => t.type === triggerType)?.fields ?? [];
  const ok = trig.filter((p) => {
    if (!p.path.startsWith("trigger.user.")) return true;
    if (p.path.startsWith("trigger.user.attributes.")) return managed.has(p.path.slice("trigger.user.attributes.".length));
    return safe.has(p.path);
  });
  return [...ok, ...stepPills(meta, before, true)];
}

export function statusTone(s: string): "good" | "bad" | "info" | "neutral" {
  return s === "succeeded" ? "good" : s === "failed" ? "bad" : s === "running" || s === "queued" || s === "retrying" || s === "waiting" ? "info" : "neutral";
}
