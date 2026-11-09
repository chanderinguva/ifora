# ADR 020: Recipe editor redesign (drag and drop, Workato-style flow)

- Status: **Accepted**. Phase 1 built (new editor at `/admin/recipes/<id>/studio`, classic editor kept behind a link for one release). Owner approved dnd-kit and the new editor; formula mode, lookup tables, callable recipes, code steps and custom connectors are in ADR 021.
- Written from general knowledge of Workato's recipe editor, not a live comparison. We copy the *interaction model*, not Workato's branding, icons or wording.

## Problem
The current editor (`frontend/src/app/admin/recipes/[id]/page.tsx`, one 520-line page) shows every step's form inline, moves steps with "earlier/later" buttons, and has no overview of the flow. Admins have to read forms to understand a recipe, and reordering or nesting is slow.

## The model: one vertical flow, one side panel
```
┌──────────────────────────────────────────┬───────────────────────┐
│  Recipe name  ● Draft   [Test] [Publish]  │  Step 3 · Add to group │
│  ┌────────────────────────────────────┐  │  ───────────────────── │
│  │ ⚡ 1  When a user is created        │  │  Group   [Engineering▾]│
│  └─────────────┬──────────────────────┘  │  User    [user.id  ⬤] │
│                +                          │  On error [Stop job ▾] │
│  ┌─────────────┴──────────────────────┐  │  Retries  [3]          │
│  │ ⠿ 2  If department = Sales          │  │                        │
│  │   ├ Yes ─ ⠿ 3 Add to group  ✓       │  │  Data from earlier     │
│  │   └ No  ─ + Add a step              │  │  steps (drag a pill    │
│  └─────────────┬──────────────────────┘  │  into any field)       │
│                +                          │  ⬤ trigger.user.email  │
│  ┌─────────────┴──────────────────────┐  │  ⬤ steps.s2.output.id  │
│  │ ⠿ 4  Handle errors ▸ On error ▸ …   │  │                        │
│  └────────────────────────────────────┘  │  [Delete step]         │
└──────────────────────────────────────────┴───────────────────────┘
```
- **Canvas**: a single column of step cards, numbered, with a **+** between every two cards and at the end of every branch. No free-form canvas and no wires: the order is the position, so there is nothing to untangle.
- **Cards are compact** (icon, number, one-line summary, status dot). Clicking a card opens its form in the **right panel**; the canvas never grows with form fields.
- **Drag and drop**: grab the ⠿ handle to move a step anywhere, including into or out of a branch, loop or error block. A drop line shows where it will land. Dropping that would break a rule (depth over 3, a step using data from a step that would now come after it) is refused with a reason. Keyboard: focus a card, Space to lift, arrows to move, Space to drop (so it stays accessible).
- **Data pills**: the panel lists the data available *at that step* (trigger fields, earlier steps' outputs, loop item). Drag a pill into a field, or type `{{` to search. Pills render as chips inside the field; the stored form stays `{{path}}` (ADR 008), so the engine and the taint rule are unchanged.
- **Add a step** (+): a searchable picker grouped as Actions, Logic (If/else, Repeat for each, Stop, Handle errors, Wait for approval), Apps (HTTP, Slack, Email). Each entry has a one-line description.
- **Collapse/expand** any branch; **select a card and press Delete**; **duplicate**; **undo/redo** (Cmd-Z, 50 deep, in memory); **autosave** of the draft after each change (debounced), with a visible "Saved" indicator.
- **Test**: a Test button runs the draft in dry-run mode (ADR 008 D4) against a chosen sample (pick a real user for event triggers) and paints each card with its result (green tick, red cross, grey skipped). Clicking a card then shows that step's input and output in the panel. This replaces reading the job table to debug a draft.
- **Errors inline**: a card with a validation problem gets a red dot and the panel says what is wrong; Publish lists every problem and jumps to the first.

## Workato feature parity
| Workato feature | Today | Plan |
|---|---|---|
| Trigger (events, schedule, webhook, manual) | Done | Same, edited in the panel |
| Actions, data pills, conditions with If/else | Done | Redraw as cards + branches |
| Repeat for each (loop) | Done: `for_each_member` | Card with a nested lane; add "list from a step's output" later |
| Stop job | Done | Card |
| Error handling (monitor, on error, retries 1-5, backoff) | Done: per-step `max_attempts`, `on_error`, recipe-level `on_error` | Show as a **Handle errors** wrapper card (Monitor lane + On error lane) in the UI over the existing model; no engine change |
| Approval step | Done | Card |
| Test with sample data, step input/output | Partial: dry run exists | Paint results on cards; pick a sample user |
| Jobs history, rerun | Done | Link from the editor header |
| Versioning, publish, enable/disable | Done | Keep; add a version dropdown with "restore this version into the draft" |
| Connections (credentials by id) | Done | Picker in the panel |
| Import/export | Done (`portable.py`) | Keep |
| Drag and drop, undo, collapse, duplicate | Missing | This ADR |
| Comments/notes on a step | Missing | Add an optional `note` string on a step (display only) |
| Formula mode (functions on pills: upper, date maths) | Missing, by design (ADR 008: no expression language) | Out of scope here; if wanted later it needs its own ADR because it widens the taint surface |
| Lookup tables | Missing | Out of scope for the editor work; separate feature |
| Callable recipes (call another recipe) | Missing | Out of scope; needs engine work (depth limits, result return) |
| Recipe folders, tags, ownership | Partial: access/owners exist | List page gets search and a tag filter later |
| Real-time collaboration | Missing | Not planned; a lock "being edited by X" instead |

## Technical plan
- **Library**: `@dnd-kit/core` + `@dnd-kit/sortable` (maintained, accessible, keyboard sensor, works with React 18). No flow-chart library: we are a list, and a graph library would add wiring we explicitly do not want.
- **State**: keep the existing `StepNode[]` definition as the single source of truth. A `useReducer` with actions (insert, move, update, delete, duplicate) plus a history stack gives undo/redo. All edits go through pure functions, unit-testable without the DOM.
- **Components** (`frontend/src/components/recipe-editor/`): `Canvas`, `StepCard`, `Lane` (a list of steps with a + between), `AddStepMenu`, `StepPanel` (reuses today's `StepForm` bodies, moved over one at a time), `PillTray`, `PillField`, `TestResults`.
- **Backend**: almost none. Needed: (1) `note` field on a step (validation accepts and ignores it at run time), (2) a dry-run endpoint that returns per-step input/output (check what the current one already returns before adding), (3) draft autosave if the existing PUT is too heavy to call on every edit.
- **Rollout**: ship behind a "Try the new editor" link on the recipe page, keep the old editor for one release, then remove it.
- **Tests**: reducer unit tests (move across lanes, depth limit, pill-order rule), Playwright for add via +, drag to reorder and into a branch, undo, pill drag, test run painting.

## Phases (each a PR)
1. **Done**: canvas, cards, + menu, side panel reusing the existing forms, undo/redo (typing merges, structural edits do not), duplicate, delete. No drag yet.
2. **Done**: drag and drop with the grip handle (`@dnd-kit`; mouse/touch), Alt+Up/Alt+Down on the handle for keyboard users, drop validation (nesting depth, repeat/approval placement, no moving into itself, datapill order, loop/error pills), refusal reason shown on the drop slot and in the status line. Still to do: collapse branches.
3. **Done**: pill tray in the step panel (grouped by source, searchable, click to insert into the last-used field or drag onto any field), `{{` search with keyboard selection in every datapill field, and a chip rendering of the stored text under each field (a pill that is not available at that step is flagged). Chips show below the field rather than inside it: the field stays a plain text input so the stored `{{path}}` form, copy/paste and accessibility are unchanged.
4. Test overlay on cards; Handle errors wrapper card; notes; version restore.

## Risks and open questions
- "Exactly like Workato" cannot be literal (their UI is theirs); this copies the layout and flow that make it easy.
- A drop that moves a step ahead of one whose output it uses must be refused or the pill rewritten; refuse for v1.
- Mobile: the panel becomes a bottom sheet; drag is on the handle only so scrolling still works.
- Decisions for the owner: dnd-kit OK? Keep old editor for one release? Is formula mode wanted (changes the security model)? Are lookup tables or callable recipes needed soon?
