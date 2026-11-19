/** Login page for Ifora. */

"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { accessSsoEnabled, accessSsoSuppressed, clearAccessSsoSuppression, getCurrentUser, login, loginMfa, sendEmailCode, loginWithAccess, loginWithPasskey } from "@/lib/auth-client";
import Link from "next/link";
import { KeyRound } from "lucide-react";
import { ExpiredPasswordForm } from "@/components/password-form";
import { useBranding } from "@/lib/branding";
import { Logo } from "@/components/logo";
import { EnvironmentIdentity } from "@/components/environment-banner";
import { ThemeToggle } from "@/components/theme-toggle";
import { inAdminView } from "@/lib/roles";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Loader2 } from "lucide-react";

const loginSchema = z.object({
  email: z.string().email("Invalid email address"),
  password: z.string().min(1, "Password is required"),
});

type LoginFormData = z.infer<typeof loginSchema>;

export default function LoginPage() {
  const { branding } = useBranding();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Until React has attached its handlers a native form submit would put the credentials in the
  // URL (GET). Keep the forms inert until hydrated; method="post" is the belt-and-braces fallback.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [factors, setFactors] = useState<string[]>([]);
  const [emailSent, setEmailSent] = useState(false);
  const [code, setCode] = useState("");
  const [expired, setExpired] = useState<{ email: string; password: string } | null>(null);
  // Invitation sign-in (Cloudflare Access): "checking" until we know, "offer" shows a button, "off" is the plain form.
  const [sso, setSso] = useState<"checking" | "offer" | "off">("checking");

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  });

  const finish = async () => {
    clearAccessSsoSuppression();
    const u = await getCurrentUser();
    // Return to an in-progress OIDC authorization, but only to a same-site relative path (never an open redirect).
    const next = new URLSearchParams(window.location.search).get("next");
    if (next && /^\/(?![/\\])[A-Za-z0-9\-._~/?=&%]*$/.test(next)) {
      router.push(next);
      return;
    }
    router.push(u?.mfa_setup_required ? "/settings#security" : u && inAdminView(u) ? "/admin/dashboard" : "/dashboard");
  };

  const viaInvitation = async () => {
    setError(null);
    const r = await loginWithAccess();
    if (!r) return false;
    if (r.firstVisit) router.push("/welcome");
    else await finish();
    return true;
  };

  const ssoStarted = useRef(false); // React runs effects twice in development; sign in through the invitation once
  useEffect(() => {
    if (ssoStarted.current) return;
    ssoStarted.current = true;
    (async () => {
      if (!(await accessSsoEnabled())) { setSso("off"); return; }
      if (accessSsoSuppressed()) { setSso("offer"); return; } // just signed out: ask first
      if (!(await viaInvitation())) setSso("off");
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onPasskey = async () => {
    setIsSubmitting(true);
    setError(null);
    try {
      await loginWithPasskey();
      await finish();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Passkey sign-in failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  const onMfaSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!mfaToken) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await loginMfa(mfaToken, code, emailSent ? "email" : undefined);
      await finish();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed");
      setCode("");
    } finally {
      setIsSubmitting(false);
    }
  };

  const onEmailCode = async () => {
    if (!mfaToken) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await sendEmailCode(mfaToken);
      setEmailSent(true);
      setCode("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the code");
    } finally {
      setIsSubmitting(false);
    }
  };

  const onSubmit = async (data: LoginFormData) => {
    setIsSubmitting(true);
    setError(null);

    try {
      const challenge = await login(data.email, data.password);
      if (challenge && "passwordChange" in challenge) {
        setExpired({ email: data.email, password: data.password });
        return;
      }
      if (challenge) {
        setMfaToken(challenge.mfaToken);
        setFactors(challenge.factors ?? ["totp"]);
        setEmailSent(false);
        return;
      }
      await finish();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center bg-muted">
      <ThemeToggle className="absolute right-4 top-4 bg-background" />
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="mb-4 flex items-center justify-between gap-3">
            <Logo size="lg" />
            <EnvironmentIdentity environment={branding.environment} label={branding.environment_label} />
          </div>
          {branding.tagline && <p className="mb-2 text-sm text-muted-foreground" data-testid="login-tagline">{branding.tagline}</p>}
          <CardTitle>{expired ? "Change your password" : mfaToken ? "Two-step verification" : "Sign In"}</CardTitle>
          <CardDescription>
            {mfaToken
              ? "Enter the 6-digit code from your authenticator app, or a recovery code."
              : `Enter your credentials to access ${branding.display_name}`}
          </CardDescription>
        </CardHeader>

        {error && (
          <CardContent>
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          </CardContent>
        )}

        {expired && (
          <CardContent>
            <ExpiredPasswordForm email={expired.email} current={expired.password}
              onDone={() => { setExpired(null); setError(null); }} />
          </CardContent>
        )}

        {mfaToken && !expired && (
          <CardContent>
            <form method="post" onSubmit={onMfaSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="mfa-code">{emailSent ? "Code from your email" : factors.includes("totp") ? "Verification code" : "Verification code (we email it to you)"}</Label>
                <Input
                  id="mfa-code"
                  inputMode="text"
                  autoComplete="one-time-code"
                  autoFocus
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  disabled={isSubmitting}
                />
              </div>
              <Button type="submit" className="w-full" disabled={isSubmitting || !hydrated || !code.trim()}>
                {isSubmitting ? "Verifying..." : "Verify"}
              </Button>
              {factors.includes("email") && (
                <button type="button" data-testid="email-code-send" disabled={isSubmitting} onClick={onEmailCode} className="w-full text-sm underline-offset-4 hover:underline">
                  {emailSent ? "Send a new code" : factors.includes("totp") ? "Email me a code instead" : "Email me a code"}
                </button>
              )}
              <button
                type="button"
                className="w-full text-sm underline-offset-4 hover:underline"
                onClick={() => {
                  setMfaToken(null);
                  setEmailSent(false);
                  setCode("");
                  setError(null);
                }}
              >
                Start over
              </button>
            </form>
          </CardContent>
        )}

        {sso === "checking" && (
          <CardContent>
            <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status" data-testid="sso-checking">
              <Loader2 className="h-4 w-4 animate-spin" /> Signing you in…
            </p>
          </CardContent>
        )}

        {sso === "offer" && !mfaToken && !expired && (
          <CardContent>
            <Button type="button" className="w-full" data-testid="sso-continue" onClick={async () => {
              setIsSubmitting(true);
              if (!(await viaInvitation())) setError("This invitation could not sign you in. Use your password instead.");
              setIsSubmitting(false);
            }} disabled={isSubmitting || !hydrated}>
              Continue with your invitation
            </Button>
          </CardContent>
        )}

        <CardContent className={mfaToken || expired || sso === "checking" ? "hidden" : undefined}>
          <form method="post" onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="admin@identityforge.local"
                {...register("email")}
                autoComplete="email"
                disabled={isSubmitting}
              />
              {errors.email && (
                <p className="text-sm text-destructive">{errors.email.message}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="Your password"
                {...register("password")}
                autoComplete="current-password"
                disabled={isSubmitting}
              />
              {errors.password && (
                <p className="text-sm text-destructive">{errors.password.message}</p>
              )}
              <Link href="/forgot-password" className="inline-block text-xs underline-offset-4 hover:underline">Forgot your password?</Link>
            </div>

            <Button type="submit" className="w-full" disabled={isSubmitting || !hydrated}>
              {isSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Signing in...
                </>
              ) : (
                "Sign In"
              )}
            </Button>

            <div className="relative py-1 text-center text-xs text-muted-foreground">
              <span className="bg-card px-2">or</span>
            </div>
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={onPasskey}
              disabled={isSubmitting || !hydrated}
            >
              <KeyRound className="mr-2 h-4 w-4" />
              Sign in with a passkey
            </Button>
          </form>
        </CardContent>

        <CardFooter className="flex justify-center">
          <p className="text-xs text-muted-foreground">
            Ifora v0.1.0
          </p>
        </CardFooter>
      </Card>
    </div>
  );
}
