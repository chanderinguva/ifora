"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { fieldClass } from "@/components/bits";
import { http } from "@/lib/http";
import { setStepUpAsker } from "@/lib/stepup";

type Waiter = { resolve: () => void; reject: (e: Error) => void };

/** Mount once around the admin pages. `http()` calls it when the API answers `stepup_required`. */
export function StepUpProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const waiters = useRef<Waiter[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  const ask = useCallback(
    () =>
      new Promise<void>((resolve, reject) => {
        waiters.current.push({ resolve, reject }); // concurrent requests share one prompt
        opener.current = document.activeElement as HTMLElement | null;
        setCode("");
        setError(null);
        setOpen(true);
      }),
    [],
  );
  useEffect(() => {
    setStepUpAsker(ask);
    return () => setStepUpAsker(null);
  }, [ask]);
  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  const close = (ok: boolean) => {
    const list = waiters.current;
    waiters.current = [];
    setOpen(false);
    list.forEach((w) => (ok ? w.resolve() : w.reject(new Error("cancelled"))));
    opener.current?.focus();
  };

  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await http("/me/step-up", { method: "POST", body: { code: code.trim() } });
      close(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not confirm");
      setCode("");
      input.current?.focus();
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {children}
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onKeyDown={(e) => e.key === "Escape" && close(false)}>
          <div role="dialog" aria-modal="true" aria-labelledby="stepup-title" aria-describedby="stepup-desc" className="w-full max-w-sm rounded-lg border bg-card p-5 shadow-lg" data-testid="stepup-dialog">
            <form onSubmit={confirm} className="space-y-3">
              <h2 id="stepup-title" className="text-base font-semibold">Confirm it&apos;s you</h2>
              <p id="stepup-desc" className="text-sm text-muted-foreground">This change affects security settings. Enter a code from your authenticator app (or a recovery code) to continue.</p>
              {error && <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription></Alert>}
              <div className="space-y-1">
                <label htmlFor="stepup-code" className="text-sm font-medium">Authenticator code</label>
                <input ref={input} id="stepup-code" className={fieldClass} value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" inputMode="text" maxLength={64} required />
              </div>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="outline" onClick={() => close(false)}>Cancel</Button>
                <Button type="submit" disabled={busy || !code.trim()} data-testid="stepup-confirm">Confirm</Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
