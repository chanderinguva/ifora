import Link from "next/link";
import { cn } from "@/lib/utils";

/**
 * IdentityForge mark: an "F" forged from one folded bar, plus the dot of identity ("i").
 * Constructed on a 64-unit grid: bar 9 wide, mitred corners, dot r=6.5. See docs/brand/guidelines.md.
 *
 * It paints with `currentColor`, so it follows the theme through the surrounding text colour
 * (near-black in light, near-white in dark) with no per-theme assets.
 */
export function LogoMark({ className, title }: { className?: string; title?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      fill="none"
      className={cn("h-7 w-7 shrink-0", className)}
      data-testid="logo-mark"
      {...(title ? { role: "img", "aria-label": title } : { "aria-hidden": true })}
    >
      {title && <title>{title}</title>}
      <path d="M48 14H22V52" stroke="currentColor" strokeWidth="9" strokeLinejoin="miter" strokeLinecap="butt" />
      <path d="M22 33H40" stroke="currentColor" strokeWidth="9" strokeLinecap="butt" />
      <circle cx="46" cy="47" r="6.5" fill="currentColor" />
    </svg>
  );
}

/** Mark + wordmark. The wordmark is live text so it stays in Lora (the app font) and follows the theme. */
export function Logo({
  className,
  markClassName,
  size = "md",
  href,
}: {
  className?: string;
  markClassName?: string;
  size?: "md" | "lg";
  /** When set, the whole lockup links home (the web convention for a top-left logo). */
  href?: string;
}) {
  const lockup = (
    <span className={cn("inline-flex items-center gap-2.5 text-foreground", className)} data-testid="logo">
      <LogoMark className={cn(size === "lg" ? "h-10 w-10" : "h-7 w-7", markClassName)} />
      <span data-testid="logo-wordmark" className={cn("font-semibold tracking-tight", size === "lg" ? "text-2xl" : "text-lg")}>
        IdentityForge
      </span>
    </span>
  );
  if (!href) return lockup;
  return (
    <Link href={href} aria-label="IdentityForge home" className="rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {lockup}
    </Link>
  );
}

/** Mark-only link home, for the collapsed rail and the mobile header. */
export function LogoLink({ href, className }: { href: string; className?: string }) {
  return (
    <Link href={href} aria-label="IdentityForge home" className={cn("rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring", className)}>
      <LogoMark />
    </Link>
  );
}
