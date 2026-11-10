"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { logoUrl, useBranding } from "@/lib/branding";

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

/** Average brightness (0-1) of the visible pixels, or null when the browser will not let us read the image. */
function brightness(img: HTMLImageElement): number | null {
  try {
    const c = document.createElement("canvas");
    c.width = c.height = 24;
    const g = c.getContext("2d");
    if (!g) return null;
    g.drawImage(img, 0, 0, 24, 24);
    const d = g.getImageData(0, 0, 24, 24).data;
    let sum = 0, n = 0;
    for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 128) { sum += (0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2]) / 255; n++; }
    return n ? sum / n : null;
  } catch { return null; }   // cross-origin image: unreadable
}

/** The organization's uploaded logo when there is one, otherwise the IdentityForge mark.
 *  A dark logo disappears on the dark theme, so in dark mode it sits on a light backing; light logos are left alone. */
function BrandMark({ className }: { className?: string }) {
  const { branding } = useBranding();
  const [needsBacking, setNeedsBacking] = useState(true);   // unknown = safe: show the backing
  const url = branding.has_logo ? logoUrl(branding) : null;
  useEffect(() => {   // measure with a separate CORS-mode request so the visible image never depends on CORS
    if (!url) return;
    const probe = new Image();
    probe.crossOrigin = "anonymous";
    probe.onload = () => { const b = brightness(probe); setNeedsBacking(b === null || b < 0.55); };
    probe.onerror = () => setNeedsBacking(true);
    probe.src = url;
  }, [url]);
  if (url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={url} alt="" data-testid="logo-image"
        className={cn("h-7 w-7 shrink-0 rounded object-contain", needsBacking && "dark:bg-white dark:p-[3px]", className)} />
    );
  }
  return <LogoMark className={className} />;
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
  const { branding } = useBranding();
  const lockup = (
    <span className={cn("inline-flex items-center gap-2.5 text-foreground", className)} data-testid="logo">
      <BrandMark className={cn(size === "lg" ? "h-10 w-10" : "h-7 w-7", markClassName)} />
      <span data-testid="logo-wordmark" className={cn("font-semibold tracking-tight", size === "lg" ? "text-2xl" : "text-lg")}>
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
