/** Login page for IdentityForge. */

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { getCurrentUser, login, loginMfa, loginWithPasskey } from "@/lib/auth-client";
import { KeyRound } from "lucide-react";
import { Logo } from "@/components/logo";
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
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Until React has attached its handlers a native form submit would put the credentials in the
  // URL (GET). Keep the forms inert until hydrated; method="post" is the belt-and-braces fallback.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  });

  const finish = async () => {
    const u = await getCurrentUser();
    router.push(u?.mfa_setup_required ? "/settings#security" : u && inAdminView(u) ? "/admin/dashboard" : "/dashboard");
  };

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
      await loginMfa(mfaToken, code);
      await finish();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed");
      setCode("");
    } finally {
      setIsSubmitting(false);
    }
  };

  const onSubmit = async (data: LoginFormData) => {
    setIsSubmitting(true);
    setError(null);

    try {
      const challenge = await login(data.email, data.password);
      if (challenge) {
        setMfaToken(challenge.mfaToken);
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
    <div className="relative flex min-h-screen items-center justify-center bg-muted">
      <ThemeToggle className="absolute right-4 top-4 bg-background" />
      <Card className="w-full max-w-md">
        <CardHeader>
          <Logo size="lg" className="mb-4" />
          <CardTitle>{mfaToken ? "Two-step verification" : "Sign In"}</CardTitle>
          <CardDescription>
            {mfaToken
              ? "Enter the 6-digit code from your authenticator app, or a recovery code."
              : "Enter your credentials to access IdentityForge"}
          </CardDescription>
        </CardHeader>

        {error && (
          <CardContent>
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          </CardContent>
        )}

        {mfaToken && (
          <CardContent>
            <form method="post" onSubmit={onMfaSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="mfa-code">Verification code</Label>
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
              <button
                type="button"
                className="w-full text-sm underline-offset-4 hover:underline"
                onClick={() => {
                  setMfaToken(null);
                  setCode("");
                  setError(null);
                }}
              >
                Start over
              </button>
            </form>
          </CardContent>
        )}

        <CardContent className={mfaToken ? "hidden" : undefined}>
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
            IdentityForge v0.1.0
          </p>
        </CardFooter>
      </Card>
    </div>
  );
}