"use client";

import { Code2, Sparkles, Info } from "lucide-react";

/** A persistent identity cue; the explanation is available without a page-wide warning. */
export function EnvironmentIdentity({ environment, label }: { environment: string; label: string }) {
  environment = process.env.NEXT_PUBLIC_APP_ENVIRONMENT || environment;
  if (environment === "production" || environment === "unknown") return null;
  const demo = environment === "demo";
  const Icon = demo ? Sparkles : Code2;
  const name = demo ? "Demo" : environment === "development" || environment === "dev" ? "Dev" : label || environment;
  return (
    <details className="group relative shrink-0" data-testid="environment-identity"
      onKeyDown={(event) => { if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary")?.focus(); } }}
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false; }}>
      <summary aria-label={`${name} environment — details`}
        className={`inline-flex cursor-pointer list-none items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden ${demo ? "border-amber-300/70 bg-amber-50 text-amber-900 hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-950/50 dark:text-amber-200 dark:hover:bg-amber-950" : "border-sky-300/70 bg-sky-50 text-sky-900 hover:bg-sky-100 dark:border-sky-700 dark:bg-sky-950/50 dark:text-sky-200 dark:hover:bg-sky-950"}`}>
        <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        {name}
        <Info className="h-3 w-3 opacity-60" aria-hidden="true" />
      </summary>
      <div className="absolute right-0 top-full z-50 mt-2 w-64 max-w-[calc(100vw-2rem)] rounded-xl border bg-popover p-4 text-left text-popover-foreground shadow-lg">
        <p className="text-sm font-semibold">{demo ? "Explore Ifora" : `${name} workspace`}</p>
        <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
          {demo ? "A demonstration environment. Use sample data only; do not enter production credentials or sensitive information." : "A non-production environment for testing changes. Changes and notifications are separate from the production service."}
        </p>
      </div>
    </details>
  );
}

