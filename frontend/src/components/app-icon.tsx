"use client";

import { useEffect, useState } from "react";
import { API_URL } from "@/lib/api";

const HUES = [212, 262, 330, 24, 152, 190, 48, 0];
const hue = (name: string) => HUES[[...name].reduce((a, c) => a + c.charCodeAt(0), 0) % HUES.length];

/** Tile logo: the uploaded image (fetched with the session cookie, shown from a blob URL) or a coloured initial. */
export function AppIcon({ path, name, hasIcon, size = 48 }: { path: string; name: string; hasIcon: boolean; size?: number }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    if (!hasIcon) { setSrc(null); return; }
    let url: string | null = null;
    let alive = true;
    fetch(`${API_URL}/api/v1${path}`, { credentials: "include" })
      .then((r) => (r.ok ? r.blob() : Promise.reject()))
      .then((b) => { if (alive) { url = URL.createObjectURL(b); setSrc(url); } })
      .catch(() => { if (alive) setSrc(null); });
    return () => { alive = false; if (url) URL.revokeObjectURL(url); };
  }, [path, hasIcon]);

  const box = { width: size, height: size };
  if (src) return <img src={src} alt="" aria-hidden style={box} className="rounded-xl object-cover" />;
  return (
    <span aria-hidden style={{ ...box, background: `hsl(${hue(name)} 60% 42%)`, fontSize: size * 0.4 }} className="flex items-center justify-center rounded-xl font-semibold text-white">
      {name.trim().charAt(0).toUpperCase()}
    </span>
  );
}
