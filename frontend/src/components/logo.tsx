import Link from "next/link";
import { cn } from "@/lib/utils";
import { logoUrl, useBranding } from "@/lib/branding";

/**
 * Ifora mark (Gateway, refined): two interlocking corners leave a passage, and a circle (the person) passes through it.
 * Constructed on a 64-unit grid. Colours come from the --ifora-* tokens (light and dark tints in globals.css), so the mark
 * follows the theme with no per-theme assets. See docs/branding/brand-guidelines.md.
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
      <path d="M8.5 8.5H38.5V18.5H18.5V38.5H8.5Z" fill="var(--ifora-1)" stroke="var(--ifora-1)" strokeWidth="3" strokeLinejoin="round" />
      <path d="M25.5 55.5H55.5V25.5H45.5V45.5H25.5Z" fill="var(--ifora-2)" stroke="var(--ifora-2)" strokeWidth="3" strokeLinejoin="round" />
      <circle cx="32" cy="32" r="7.5" fill="var(--ifora-3)" />
    </svg>
  );
}

/** The organization's uploaded logo when there is one, otherwise the Ifora mark. */
function BrandMark({ className }: { className?: string }) {
  const { branding } = useBranding();
  // eslint-disable-next-line @next/next/no-img-element
  if (branding.has_logo) return <img src={logoUrl(branding)} alt="" className={cn("h-7 w-7 shrink-0 rounded object-contain", className)} data-testid="logo-image" />;
  return <LogoMark className={className} />;
}

/** Mark + wordmark. The wordmark is live text so it stays in Lora (the brand font, distinct from the Inter UI font) and follows the theme. */
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
  const { branding } = useBranding();
  const lockup = (
    <span className={cn("inline-flex items-center gap-2.5 text-foreground", className)} data-testid="logo">
      <BrandMark className={cn(size === "lg" ? "h-10 w-10" : "h-7 w-7", markClassName)} />
      <span data-testid="logo-wordmark" className={cn("font-brand font-semibold tracking-tight", size === "lg" ? "text-2xl" : "text-lg")}>
        {branding.display_name}
      </span>
    </span>
  );
  if (!href) return lockup;
  return (
    <Link href={href} aria-label={`${branding.display_name} home`} className="rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {lockup}
    </Link>
  );
}

/** Mark-only link home, for the collapsed rail and the mobile header. */
export function LogoLink({ href, className }: { href: string; className?: string }) {
  const { branding } = useBranding();
  return (
    <Link href={href} aria-label={`${branding.display_name} home`} className={cn("rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring", className)}>
      <BrandMark />
    </Link>
  );
}
