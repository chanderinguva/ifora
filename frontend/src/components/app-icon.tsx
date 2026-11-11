"use client";

import { useEffect, useState } from "react";
import { API_URL } from "@/lib/api";

/** Tile logo: the uploaded image (fetched with the session cookie, shown from a blob URL) or a neutral initial. */
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

  const box = { width: size, height: size, borderRadius: Math.round(size / 4) };
  if (src) return <img src={src} alt="" aria-hidden style={box} className="object-cover" />;
  return (
    <span aria-hidden style={{ ...box, fontSize: Math.round(size * 0.4) }} className="flex items-center justify-center border bg-secondary font-medium text-secondary-foreground">
      {name.trim().charAt(0).toUpperCase()}
    </span>
  );
}
