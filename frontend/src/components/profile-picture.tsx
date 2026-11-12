"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Avatar, announceAvatar } from "@/components/avatar";
import { http, uploadImage } from "@/lib/http";
import type { User } from "@/lib/types";

const TYPES = ["image/jpeg", "image/png", "image/webp"];
const MAX_BYTES = 2 * 1024 * 1024;

/** Upload or remove your own profile picture. The server re-encodes it, so only the basics are checked here. */
export function ProfilePicture({ user }: { user: User }) {
  const input = useRef<HTMLInputElement>(null);
  const [etag, setEtag] = useState<string | null>(user.avatar_etag ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function pick(file: File | undefined) {
    if (!file) return;
    setError("");
    if (!TYPES.includes(file.type)) return setError("Use a JPEG, PNG or WebP image");
    if (file.size > MAX_BYTES) return setError("That image is larger than 2 MB");
    setBusy(true);
    try {
      const r = await uploadImage<{ avatar_etag: string }>("/me/avatar", file);
      setEtag(r.avatar_etag);
      announceAvatar(user.id, r.avatar_etag);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not upload the picture");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  async function remove() {
    setError("");
    setBusy(true);
    try {
      await http("/me/avatar", { method: "DELETE" });
      setEtag(null);
      announceAvatar(user.id, null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not remove the picture");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-4" data-testid="profile-picture">
      <Avatar user={{ ...user, avatar_etag: etag }} size={64} />
      <div className="space-y-1">
        <div className="flex gap-2">
          <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => input.current?.click()}>
            {etag ? "Change picture" : "Upload picture"}
          </Button>
          {etag && <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={remove}>Remove</Button>}
        </div>
        <input
          ref={input}
          type="file"
          accept={TYPES.join(",")}
          className="sr-only"
          aria-label="Profile picture file"
          data-testid="profile-picture-input"
          onChange={(e) => pick(e.target.files?.[0])}
        />
        <p className="text-xs text-muted-foreground">JPEG, PNG or WebP, up to 2 MB. It is cropped to a square.</p>
        {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
      </div>
    </div>
  );
}
