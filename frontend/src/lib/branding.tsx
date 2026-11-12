"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { API_URL } from "./api";
import { deploymentTitle } from "./deployment-title";

export type Branding = { display_name: string; custom_name: boolean; primary_color: string | null; tagline: string | null; has_logo: boolean; logo_rev: string | null; environment: string; environment_label: string };
export const DEFAULT_BRANDING: Branding = { display_name: "Ifora", custom_name: false, primary_color: null, tagline: null, has_logo: false, logo_rev: null, environment: "unknown", environment_label: "" };

const Ctx = createContext<{ branding: Branding; reload: () => void }>({ branding: DEFAULT_BRANDING, reload: () => {} });
export const useBranding = () => useContext(Ctx);

export function logoUrl(b: Branding) {
  return `${API_URL}/api/v1/branding/logo?v=${b.logo_rev ?? ""}`;
}

/** '#rrggbb' -> [h, s%, l%] */
function hsl(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => v / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  if (d === 0) return [0, 0, Math.round(l * 100)];
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [Math.round((h * 60 + 360) % 360), Math.round(s * 100), Math.round(l * 100)];
}
function luminance(hex: string) {
  const n = parseInt(hex.slice(1), 16);
  const f = (v: number) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f((n >> 16) & 255) + 0.7152 * f((n >> 8) & 255) + 0.0722 * f(n & 255);
}
const DARK_FG = "222.2 47.4% 11.2%", LIGHT_FG = "210 40% 98%";

/** CSS that recolours the primary action colour. Text on it is whichever of near-black / near-white contrasts more. */
export function themeCss(color: string | null): string {
  if (!color || !/^#[0-9a-fA-F]{6}$/.test(color)) return "";
  const [h, s, l] = hsl(color);
  const fgFor = (hex: string) => (luminance(hex) > 0.179 ? DARK_FG : LIGHT_FG);  // 0.179: the crossover where black and white contrast equally
  const lightFg = fgFor(color);
  // on the dark theme a dark brand colour would vanish into the background, so lift it
  const dl = Math.max(l, 62);
  const darkFg = dl === l ? lightFg : DARK_FG;
  return `:root{--primary:${h} ${s}% ${l}%;--primary-foreground:${lightFg};}.dark{--primary:${h} ${s}% ${dl}%;--primary-foreground:${darkFg};}`;
}

export function BrandingProvider({ children }: { children: React.ReactNode }) {
  const [branding, setBranding] = useState<Branding>(DEFAULT_BRANDING);
  const [n, setN] = useState(0);
  useEffect(() => {
    document.title = deploymentTitle(
      process.env.NEXT_PUBLIC_APP_ENVIRONMENT || branding.environment,
      branding.display_name,
    );
  }, [branding.environment, branding.display_name]);
  useEffect(() => {
    let alive = true;
    fetch(`${API_URL}/api/v1/branding`).then((r) => (r.ok ? r.json() : null)).then((b) => { if (alive && b) setBranding(b); }).catch(() => {});
    return () => { alive = false; };
  }, [n]);
  useEffect(() => {
    let el = document.getElementById("brand-theme") as HTMLStyleElement | null;
    const css = themeCss(branding.primary_color);
    if (!css) { el?.remove(); return; }
    if (!el) { el = document.createElement("style"); el.id = "brand-theme"; document.head.appendChild(el); }
    el.textContent = css;
  }, [branding.primary_color]);
  return <Ctx.Provider value={{ branding, reload: () => setN((x) => x + 1) }}>{children}</Ctx.Provider>;
}

