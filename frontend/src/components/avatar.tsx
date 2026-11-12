"use client";

import { useState } from "react";
import { API_URL } from "@/lib/api";
import { cn } from "@/lib/utils";

type Who = { id: number; first_name?: string; last_name?: string; email?: string; avatar_etag?: string | null };

export function initialsOf(u: Who): string {
  return (((u.first_name?.[0] ?? "") + (u.last_name?.[0] ?? "")) || (u.email?.[0] ?? "?")).toUpperCase();
}

/** Profile picture, or the person's initials when there is none (or it fails to load). */
export function Avatar({
  user, size = 36, className,
}: { user: Who; size?: number; className?: string }) {
  const [failed, setFailed] = useState<string | null>(null);
  const etag = user.avatar_etag ?? null;
  const show = etag !== null && failed !== etag;
  return (
    <span
      className={cn("inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-muted text-xs font-semibold text-muted-foreground", className)}
      style={{ width: size, height: size, fontSize: Math.max(10, Math.round(size / 3)) }}
    >
      {show ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          alt=""
          width={size}
          height={size}
          className="h-full w-full object-cover"
          src={`${API_URL}/api/v1/avatars/${user.id}?v=${etag}`}
          onError={() => setFailed(etag)}
        />
      ) : (
        <span aria-hidden="true">{initialsOf(user)}</span>
      )}
    </span>
  );
}

/** Tell other parts of the page (the header menu) that this person's picture changed. */
export function announceAvatar(id: number, etag: string | null) {
  window.dispatchEvent(new CustomEvent("avatar-changed", { detail: { id, etag } }));
}
