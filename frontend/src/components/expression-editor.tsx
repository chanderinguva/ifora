"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { fieldClass } from "@/components/bits";
import { http } from "@/lib/http";

type Fn = { name: string; signature: string; description: string; returns: string; example: string };
type Attr = { name: string; label: string; type: string };
type Help = { functions: Fn[]; operators: { token: string; description: string }[]; attributes: Attr[]; blocked_attributes: { name: string; reason: string }[] };
type Item = { key: string; label: string; insert: string; caret?: number; kind: "attribute" | "function" | "namespace" | "operator"; detail: string; doc?: Fn; hint?: string };
type Check = { ok: boolean; error: string | null; attributes: string[] };

const NAMESPACES = [["String.", "String functions"], ["Arrays.", "List functions"], ["Convert.", "Conversions"]] as const;
const WORD_OPS = ["and", "or", "not", "eq", "ne"];
const EXAMPLES: [string, string][] = [
  ["Department equals Sales", 'user.department == "Sales"'],
  ["Company email addresses", 'String.stringContains(user.email, "@example.com")'],
  ["Everyone except contractors", 'user.userType != "Contractor"'],
  ["Either of two departments", 'user.department == "Sales" || user.department == "Marketing"'],
  ["Case-insensitive match", 'String.toLowerCase(user.department) == "sales"'],
  ["Employee ID prefix", 'String.substring(user.employeeId, 0, 2) == "EU"'],
];

/** Where the caret is and what has been typed of the current word (letters, digits, `.`). */
function currentToken(text: string, caret: number) {
  const m = /[A-Za-z_][\w.]*$|\.$/.exec(text.slice(0, caret));
  const partial = m ? m[0] : "";
  return { partial, start: caret - partial.length };
}

/**
 * Okta Expression Language editor with auto-suggest (Ctrl+Space, or just type): attributes after `user.`, functions after
 * `String.` / `Arrays.` / `Convert.`, operators, with the signature and an example for the highlighted item, and live
 * validation from the server (the same check that runs on save).
 */
export function ExpressionEditor({ id, value, onChange, placeholder }: { id: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [help, setHelp] = useState<Help | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [caret, setCaret] = useState(0);
  const [check, setCheck] = useState<Check | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);
  const listId = useId();

  useEffect(() => { http<Help>("/admin/group-rules/expression-help").then(setHelp).catch(() => {}); }, []);

  // live validation, debounced; stale answers are dropped
  useEffect(() => {
    if (!value.trim()) { setCheck(null); return; }
    let alive = true;
    const t = setTimeout(() => {
      http<Check>("/admin/group-rules/validate-expression", { method: "POST", body: { expression: value } }).then((c) => { if (alive) setCheck(c); }).catch(() => {});
    }, 400);
    return () => { alive = false; clearTimeout(t); };
  }, [value]);

  const { partial, start } = useMemo(() => currentToken(value, caret), [value, caret]);

  const items: Item[] = useMemo(() => {
    if (!help) return [];
    const p = partial.toLowerCase();
    const out: Item[] = [];
    const attrItems = (rest: string) => {
      help.attributes.filter((a) => a.name.toLowerCase().startsWith(rest.toLowerCase())).forEach((a) =>
        out.push({ key: `a:${a.name}`, label: `user.${a.name}`, insert: `user.${a.name}`, kind: "attribute", detail: `${a.label} · ${a.type}` }));
      const blocked = help.blocked_attributes.find((b) => b.name.toLowerCase() === rest.toLowerCase() && rest);
      if (blocked) out.push({ key: `b:${blocked.name}`, label: `user.${blocked.name}`, insert: `user.${blocked.name}`, kind: "attribute", detail: "not allowed in rules", hint: `${blocked.name}: ${blocked.reason}, so a rule cannot use it.` });
    };
    if (p.startsWith("user.")) { attrItems(partial.slice(5)); return out; }
    const ns = NAMESPACES.find(([n]) => p.startsWith(n.toLowerCase()));
    if (ns) {
      const rest = p.slice(ns[0].length);
      help.functions.filter((f) => f.name.startsWith(ns[0]) && f.name.slice(ns[0].length).toLowerCase().startsWith(rest)).forEach((f) =>
        out.push({ key: `f:${f.name}`, label: f.name, insert: `${f.name}()`, caret: -1, kind: "function", detail: `→ ${f.returns}`, doc: f }));
      return out;
    }
    if (!partial && !open) return out;
    if ("user.".startsWith(p) || (!p)) out.push({ key: "n:user", label: "user.", insert: "user.", kind: "namespace", detail: "Attributes of the person" });
    NAMESPACES.forEach(([n, d]) => { if (n.toLowerCase().startsWith(p)) out.push({ key: `n:${n}`, label: n, insert: n, kind: "namespace", detail: d }); });
    if (p) {
      WORD_OPS.filter((w) => w.startsWith(p) && w !== p).forEach((w) => out.push({ key: `o:${w}`, label: w, insert: w + " ", kind: "operator", detail: help.operators.find((o) => o.token === w)?.description ?? "" }));
    } else {
      help.operators.filter((o) => !/^[a-z]/.test(o.token)).forEach((o) => out.push({ key: `o:${o.token}`, label: o.token, insert: o.token + " ", kind: "operator", detail: o.description }));
    }
    return out;
  }, [help, partial, open]);

  const showList = open && items.length > 0;
  useEffect(() => { setActive(0); }, [partial, open]);

  const accept = useCallback((it: Item) => {
    const el = ref.current;
    const next = value.slice(0, start) + it.insert + value.slice(caret);
    const pos = start + it.insert.length + (it.caret ?? 0);
    onChange(next);
    // namespaces keep the list open so the next suggestion (attribute / function) appears straight away
    const keepOpen = it.kind === "namespace";
    setOpen(keepOpen);
    requestAnimationFrame(() => { if (el) { el.focus(); el.setSelectionRange(pos, pos); } setCaret(pos); });
  }, [value, start, caret, onChange]);

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.ctrlKey || e.metaKey) && e.code === "Space") { e.preventDefault(); setOpen(true); return; }
    if (!showList) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => (a + 1) % items.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => (a - 1 + items.length) % items.length); }
    else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); accept(items[active]); }
    else if (e.key === "Escape") { e.preventDefault(); setOpen(false); }
  }

  const sync = (el: HTMLTextAreaElement) => setCaret(el.selectionStart ?? el.value.length);
  const doc = showList ? items[active] : null;
  const activeId = showList ? `${listId}-${active}` : undefined;

  return (
    <div className="space-y-2" data-testid="expression-editor">
      <div className="relative">
        <textarea id={id} ref={ref} rows={3} maxLength={1000} spellCheck={false} autoComplete="off" className={fieldClass + " font-mono text-xs"} placeholder={placeholder}
          role="combobox" aria-expanded={showList} aria-controls={listId} aria-autocomplete="list" aria-activedescendant={activeId}
          value={value}
          onChange={(e) => { onChange(e.target.value); sync(e.target); setOpen(true); }}
          onKeyDown={onKeyDown} onKeyUp={(e) => { if (!["ArrowDown", "ArrowUp", "Enter", "Tab", "Escape"].includes(e.key)) sync(e.currentTarget); }}
          onClick={(e) => { sync(e.currentTarget); }} onBlur={() => setTimeout(() => setOpen(false), 120)} />
        {showList && (
          <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md" data-testid="expression-suggestions">
            <ul id={listId} role="listbox" aria-label="Suggestions" className="max-h-48 overflow-auto py-1">
              {items.map((it, i) => (
                <li key={it.key} id={`${listId}-${i}`} role="option" aria-selected={i === active}
                  className={`flex cursor-pointer items-baseline justify-between gap-3 px-3 py-1 text-xs ${i === active ? "bg-accent text-accent-foreground" : ""}`}
                  onMouseDown={(e) => { e.preventDefault(); accept(it); }} onMouseEnter={() => setActive(i)}>
                  <span className="font-mono">{it.label}</span><span className="truncate text-muted-foreground">{it.detail}</span>
                </li>
              ))}
            </ul>
            {doc && (doc.doc || doc.hint) && (
              <div className="border-t bg-muted/40 px-3 py-2 text-xs" data-testid="expression-doc">
                {doc.doc ? (<>
                  <div className="font-mono font-medium">{doc.doc.signature}</div>
                  <div className="text-muted-foreground">{doc.doc.description}</div>
                  <div className="mt-1 font-mono text-muted-foreground">e.g. {doc.doc.example}</div>
                </>) : <div className="text-destructive">{doc.hint}</div>}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <select aria-label="Insert an example" className={fieldClass + " !w-64 !py-1 text-xs"} value="" onChange={(e) => { if (e.target.value) { onChange(e.target.value); setCaret(e.target.value.length); } }}>
          <option value="">Insert an example…</option>
          {EXAMPLES.map(([l, x]) => <option key={l} value={x}>{l}</option>)}
        </select>
        <span className="text-muted-foreground">Type <code>user.</code> or <code>String.</code> for suggestions · Ctrl+Space opens them · ↑ ↓ Enter to pick</span>
      </div>

      <div role="status" aria-live="polite" className="min-h-[1.25rem] text-xs" data-testid="expression-status">
        {check && (check.ok
          ? <span className="text-good">✓ Valid. Reads {check.attributes.length ? check.attributes.map((a) => `user.${a}`).join(", ") : "no attributes"}.</span>
          : <span className="text-destructive">{check.error}</span>)}
      </div>
    </div>
  );
}
