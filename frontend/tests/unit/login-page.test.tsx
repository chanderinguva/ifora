import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));
vi.mock("@/lib/branding", () => ({ useBranding: () => ({ branding: { display_name: "Acme", tagline: "Sign in to Acme", environment: "production", environment_label: "" } }) }));
vi.mock("@/components/logo", () => ({ Logo: () => <span>logo</span> }));
vi.mock("@/components/environment-banner", () => ({ EnvironmentIdentity: () => null }));
vi.mock("@/components/theme-toggle", () => ({ ThemeToggle: () => null }));
vi.mock("@/components/password-form", () => ({ ExpiredPasswordForm: (p: { email: string; onDone: () => void }) => <button onClick={p.onDone}>change for {p.email}</button> }));

const auth = vi.hoisted(() => ({
  accessSsoEnabled: vi.fn(async () => false),
  accessSsoSuppressed: vi.fn(() => false),
  clearAccessSsoSuppression: vi.fn(),
  getCurrentUser: vi.fn(async (): Promise<Record<string, unknown>> => ({ is_admin: true, acting_as_user: false, mfa_setup_required: false })),
  login: vi.fn(),
  loginMfa: vi.fn(),
  loginWithAccess: vi.fn(),
  loginWithPasskey: vi.fn(),
}));
vi.mock("@/lib/auth-client", () => auth);

import LoginPage from "@/app/login/page";

async function ready() {
  render(<LoginPage />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Sign In" })).toBeEnabled());
}
const fill = async (email: string, password: string) => {
  const u = userEvent.setup();
  if (email) await u.type(screen.getByLabelText("Email"), email);
  if (password) await u.type(screen.getByLabelText("Password"), password);
  await u.click(screen.getByRole("button", { name: "Sign In" }));
};

beforeEach(() => {
  push.mockReset();
  Object.values(auth).forEach((f) => f.mockClear());
  auth.accessSsoEnabled.mockResolvedValue(false);
  auth.accessSsoSuppressed.mockReturnValue(false);
  auth.getCurrentUser.mockResolvedValue({ is_admin: true, acting_as_user: false, mfa_setup_required: false });
  window.history.pushState({}, "", "/login");
});

describe("sign-in form", () => {
  it("shows the organisation's name and tagline", async () => {
    await ready();
    expect(screen.getByText("Enter your credentials to access Acme")).toBeInTheDocument();
    expect(screen.getByTestId("login-tagline")).toHaveTextContent("Sign in to Acme");
  });

  it("refuses an empty password before calling the server", async () => {
    await ready();
    await fill("a@example.com", "");
    expect(await screen.findByText("Password is required")).toBeInTheDocument();
    expect(auth.login).not.toHaveBeenCalled();
  });

  it("does not submit a malformed email (the browser's own check stops it first)", async () => {
    await ready();
    await fill("not-an-email", "pw");
    expect(auth.login).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("an administrator lands on the admin dashboard, an ordinary user on theirs", async () => {
    auth.login.mockResolvedValue(null);
    await ready();
    await fill("a@example.com", "pw");
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/dashboard"));
  });

  it("an ordinary user goes to their dashboard", async () => {
    auth.login.mockResolvedValue(null);
    auth.getCurrentUser.mockResolvedValue({ is_admin: false, acting_as_user: false });
    await ready();
    await fill("u@example.com", "pw");
    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard"));
  });

  it("an administrator who still has to enrol a factor is sent to account settings", async () => {
    auth.login.mockResolvedValue(null);
    auth.getCurrentUser.mockResolvedValue({ is_admin: true, mfa_setup_required: true });
    await ready();
    await fill("a@example.com", "pw");
    await waitFor(() => expect(push).toHaveBeenCalledWith("/settings#security"));
  });

  it("shows the server's message when sign-in fails, and lets the person try again", async () => {
    auth.login.mockRejectedValue(new Error("Invalid credentials"));
    await ready();
    await fill("a@example.com", "wrong");
    expect(await screen.findByText("Invalid credentials")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign In" })).toBeEnabled();
    expect(push).not.toHaveBeenCalled();
  });

  it("falls back to a generic message for a non-Error failure", async () => {
    auth.login.mockRejectedValue("boom");
    await ready();
    await fill("a@example.com", "x");
    expect(await screen.findByText("Login failed")).toBeInTheDocument();
  });
});

describe("returning to where the person was going", () => {
  it("follows a same-site next path", async () => {
    auth.login.mockResolvedValue(null);
    window.history.pushState({}, "", "/login?next=%2Foauth%2Fauthorize%3Fclient_id%3Dabc");
    await ready();
    await fill("a@example.com", "pw");
    await waitFor(() => expect(push).toHaveBeenCalledWith("/oauth/authorize?client_id=abc"));
  });

  it.each(["//evil.example.com", "/\\evil.example.com", "https://evil.example.com", "javascript:alert(1)"])("ignores an unsafe next (%s)", async (bad) => {
    auth.login.mockResolvedValue(null);
    window.history.pushState({}, "", "/login?next=" + encodeURIComponent(bad));
    await ready();
    await fill("a@example.com", "pw");
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/dashboard"));
  });
});

describe("second step", () => {
  it("asks for a code, sends it, and continues", async () => {
    auth.login.mockResolvedValue({ mfaToken: "challenge" });
    auth.loginMfa.mockResolvedValue(undefined);
    await ready();
    await fill("a@example.com", "pw");
    expect(await screen.findByText("Two-step verification")).toBeInTheDocument();
    const u = userEvent.setup();
    expect(screen.getByRole("button", { name: "Verify" })).toBeDisabled(); // nothing typed yet
    await u.type(screen.getByLabelText("Verification code"), "123456");
    await u.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(auth.loginMfa).toHaveBeenCalledWith("challenge", "123456"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/dashboard"));
  });

  it("a wrong code shows the error and clears the field", async () => {
    auth.login.mockResolvedValue({ mfaToken: "challenge" });
    auth.loginMfa.mockRejectedValue(new Error("Invalid code"));
    await ready();
    await fill("a@example.com", "pw");
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Verification code"), "000000");
    await u.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("Invalid code")).toBeInTheDocument();
    expect(screen.getByLabelText("Verification code")).toHaveValue("");
  });

  it("start over goes back to the password form", async () => {
    auth.login.mockResolvedValue({ mfaToken: "challenge" });
    await ready();
    await fill("a@example.com", "pw");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Start over" }));
    expect(await screen.findByRole("heading", { name: "Sign In" }).catch(() => screen.getByText("Sign In"))).toBeInTheDocument();
    expect(screen.queryByLabelText("Verification code")).not.toBeInTheDocument();
  });
});

describe("other ways in", () => {
  it("an expired password opens the change-password form for that account", async () => {
    auth.login.mockResolvedValue({ passwordChange: true });
    await ready();
    await fill("old@example.com", "pw");
    expect(await screen.findByText("change for old@example.com")).toBeInTheDocument();
    expect(screen.getByText("Change your password")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByText("change for old@example.com"));
    expect(screen.queryByText("change for old@example.com")).not.toBeInTheDocument();
  });

  it("a passkey signs in and continues; a refusal is shown", async () => {
    auth.loginWithPasskey.mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("No passkey found"));
    await ready();
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: /passkey/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/dashboard"));
    await u.click(screen.getByRole("button", { name: /passkey/i }));
    expect(await screen.findByText("No passkey found")).toBeInTheDocument();
  });

  it("an invitation signs a first-time visitor in and sends them to the welcome page", async () => {
    auth.accessSsoEnabled.mockResolvedValue(true);
    auth.loginWithAccess.mockResolvedValue({ firstVisit: true });
    render(<LoginPage />);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/welcome"));
  });

  it("an invitation for a returning visitor signs in and continues", async () => {
    auth.accessSsoEnabled.mockResolvedValue(true);
    auth.loginWithAccess.mockResolvedValue({ firstVisit: false });
    render(<LoginPage />);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/dashboard"));
  });

  it("when the invitation does not sign anyone in, the password form appears", async () => {
    auth.accessSsoEnabled.mockResolvedValue(true);
    auth.loginWithAccess.mockResolvedValue(null);
    await ready();
    expect(screen.queryByTestId("sso-checking")).not.toBeInTheDocument();
  });

  it("right after signing out the person is asked before signing back in through the invitation", async () => {
    auth.accessSsoEnabled.mockResolvedValue(true);
    auth.accessSsoSuppressed.mockReturnValue(true);
    render(<LoginPage />);
    const go = await screen.findByTestId("sso-continue");
    expect(auth.loginWithAccess).not.toHaveBeenCalled();
    auth.loginWithAccess.mockResolvedValue(null);
    await waitFor(() => expect(go).toBeEnabled());
    await userEvent.setup().click(go);
    expect(await screen.findByText(/could not sign you in/)).toBeInTheDocument();
  });
});
