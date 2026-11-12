"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { http } from "@/lib/http";

/** The one-time enrolment code input; when the server can mail the code, offers to send it to the user's own address. */
export function EnrolCodeField({
  id, value, onChange, canEmail,
}: { id: string; value: string; onChange: (v: string) => void; canEmail: boolean }) {
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [error, setError] = useState("");

  async function send() {
    setState("sending");
    setError("");
    try {
      await http("/me/mfa/enrollment-code/email", { method: "POST" });
      setState("sent");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send the code");
      setState("error");
    }
  }

  return (
    <>
      <Label htmlFor={id}>Enrolment code</Label>
      <Input id={id} autoComplete="off" placeholder="XXXX-XXXX-XXXX" value={value} onChange={(e) => onChange(e.target.value)} />
      {canEmail ? (
        <p className="text-xs text-muted-foreground">
          {state === "sent" ? "Code sent to your email. It can take a minute to arrive. " : "Administrators need a one-time code to set up their first sign-in factor. "}
          <button type="button" className="underline underline-offset-4" disabled={state === "sending"} onClick={send}>
            {state === "sent" ? "Send again" : state === "sending" ? "Sending…" : "Email me a code"}
          </button>
          {state === "error" && <span role="alert" className="ml-1 text-destructive">{error}</span>}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">Administrators need a one-time code from a super admin or the operator to set up their first sign-in factor.</p>
      )}
    </>
  );
}
