"use client";

/** Server-sourced deployment identity, visible on login and all signed-in pages. */
export function EnvironmentBanner({ environment, label }: { environment: string; label: string }) {
  if (environment === "production" || environment === "unknown") return null;
  const demo = environment === "demo";
  return (
    <div role="status" aria-label={`Environment: ${label}`} data-testid="environment-banner"
      className={`flex flex-wrap items-center justify-center gap-2 border-b px-4 py-2 text-center text-xs font-semibold tracking-wide ${demo ? "border-amber-300 bg-amber-100 text-amber-950" : "border-sky-300 bg-sky-100 text-sky-950"}`}>
      <span>{label} ENVIRONMENT</span>
      <span className="font-normal normal-case tracking-normal">
        {demo ? "This is a demonstration environment. Do not enter production credentials or sensitive information." : "Non-production environment — changes and notifications are not from the production service."}
      </span>
    </div>
  );
}
