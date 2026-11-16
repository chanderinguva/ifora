import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Users } from "lucide-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ pathname: "/admin/users", replace: vi.fn() }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname, useRouter: () => ({ replace: nav.replace, push: vi.fn() }) }));
const auth = vi.hoisted(() => ({ getCurrentUser: vi.fn() }));
vi.mock("@/lib/auth-client", () => ({ getCurrentUser: auth.getCurrentUser, ensureCsrfToken: vi.fn(async () => "t") }));
vi.mock("@/lib/display", () => ({ setDisplayPrefs: vi.fn(), formatDateTime: (s: string) => `at ${s}` }));

import { AuthGuard, useCurrentUser } from "@/components/auth-guard";
import { Badge, fmt, PageHeader, Pager } from "@/components/bits";
import { PasswordRules } from "@/components/password-rules";
import { SidebarNav } from "@/components/sidebar-nav";
import { StepUpProvider } from "@/components/step-up-dialog";
import { UserRoleBadges } from "@/components/user-role-badges";
import { inAdminView } from "@/lib/roles";
import { ADMIN_TASKS, matchTasks } from "@/lib/admin-tasks";
import { askStepUp } from "@/lib/stepup";

beforeEach(() => {
  nav.pathname = "/admin/users";
  nav.replace.mockReset();
  auth.getCurrentUser.mockReset();
});

describe("roles and tasks", () => {
  it("administrator functions show only in admin view", () => {
    expect(inAdminView({ is_admin: true })).toBe(true);
    expect(inAdminView({ is_admin: true, acting_as_user: true })).toBe(false);
    expect(inAdminView({ is_admin: false })).toBe(false);
  });

  it("task search finds a task by name or by what the person means", () => {
    expect(matchTasks("").length).toBe(ADMIN_TASKS.length);
    expect(matchTasks("add an app").map((t) => t.id)).toEqual(["add-app"]);
    expect(matchTasks("failed sign-in").map((t) => t.id)).toContain("investigate-login");
    expect(matchTasks("simulate").map((t) => t.id)).toContain("test-policy");
    expect(matchTasks("zzzz")).toEqual([]);
    for (const t of ADMIN_TASKS) expect(t.href.startsWith("/admin/")).toBe(true);
  });
});

describe("role badges", () => {
  const base = { is_admin: false, is_super_admin: false };
  it("a super admin", () => {
    render(<UserRoleBadges user={{ ...base, is_admin: true, is_super_admin: true }} />);
    expect(screen.getByText("Super admin")).toBeInTheDocument();
  });
  it("lists each role and says where it came from", () => {
    render(<UserRoleBadges user={{ ...base, is_admin: true, admin_roles: [
      { id: "a", label: "Help desk", sources: ["group"] }, { id: "b", label: "Auditor", sources: ["direct"] }, { id: "c", label: "Both", sources: ["group", "direct"] },
    ] as never }} />);
    expect(screen.getByText("Help desk").closest("span[title]")).toHaveAttribute("title", "Granted through a group");
    expect(screen.getByText("Auditor").closest("span[title]")).toHaveAttribute("title", "Assigned directly");
    expect(screen.getByText("Both").closest("span[title]")).toHaveAttribute("title", "Granted through a group and directly");
  });
  it("an admin with no role, with roles unavailable, and an ordinary user", () => {
    const { rerender } = render(<UserRoleBadges user={{ ...base, is_admin: true, admin_roles: [] as never }} />);
    expect(screen.getByText("Admin (no role assigned)")).toBeInTheDocument();
    rerender(<UserRoleBadges user={{ ...base, is_admin: true }} />);
    expect(screen.getByText("Admin (roles unavailable)")).toBeInTheDocument();
    rerender(<UserRoleBadges user={base} />);
    expect(screen.getByText("User")).toBeInTheDocument();
  });
});

describe("navigation", () => {
  const groups = [{ items: [{ href: "/admin/users", label: "Users", icon: Users }, { href: "/admin/groups", label: "Groups", icon: Users }] }, { label: "Security", items: [{ href: "/admin/audit", label: "Audit", icon: Users }] }];

  it("marks the current page and its sub-pages, and nothing else", () => {
    nav.pathname = "/admin/users/12";
    render(<SidebarNav groups={groups} />);
    expect(screen.getByRole("link", { name: "Users" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Groups" })).not.toHaveAttribute("aria-current");
    expect(screen.getByText("Security")).toBeInTheDocument();
  });

  it("collapsed keeps every destination reachable by name", () => {
    render(<SidebarNav groups={groups} collapsed />);
    expect(screen.getByRole("link", { name: "Audit" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });

  it("tells the shell when a link is followed", async () => {
    const done = vi.fn();
    render(<SidebarNav groups={groups} onNavigate={done} />);
    await userEvent.setup().click(screen.getByRole("link", { name: "Groups" }));
    expect(done).toHaveBeenCalled();
  });
});

describe("shared bits", () => {
  it("formats dates and empty values", () => {
    expect(fmt(null)).toBe("—");
    expect(fmt("2026-01-01T00:00:00Z")).toBe("at 2026-01-01T00:00:00Z");
  });
  it("badge and page header render their content", () => {
    render(<PageHeader title="Users"><Badge tone="good">ok</Badge></PageHeader>);
    expect(screen.getByRole("heading", { name: "Users" })).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
  });
  it("pager reports the count and steps through pages", async () => {
    const go = vi.fn();
    const { rerender } = render(<Pager page={1} pageSize={25} total={60} onPage={go} />);
    expect(screen.getByText("60 results")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await userEvent.setup().click(screen.getByRole("button", { name: "Next" }));
    expect(go).toHaveBeenCalledWith(2);
    rerender(<Pager page={3} pageSize={25} total={1} onPage={go} />);
    expect(screen.getByText("1 result")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });
});

describe("password rules", () => {
  it("shows the organisation's rules once loaded, and nothing when they cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ rules: ["12+ characters", "a digit"] }))));
    const { unmount } = render(<PasswordRules />);
    expect(await screen.findByTestId("password-rules")).toHaveTextContent("12+ characters · a digit");
    unmount();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 500 })));
    render(<PasswordRules />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("password-rules")).not.toBeInTheDocument();
  });
  it("ignores a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    render(<PasswordRules />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("password-rules")).not.toBeInTheDocument();
  });
});

describe("auth guard", () => {
  const Who = () => <span>hello {useCurrentUser().email}</span>;
  const me = { email: "a@example.com", is_admin: true, acting_as_user: false, profile_attributes: {} };

  it("shows the page to a signed-in user", async () => {
    auth.getCurrentUser.mockResolvedValue({ ...me, is_admin: false });
    render(<AuthGuard><Who /></AuthGuard>);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("hello a@example.com")).toBeInTheDocument();
  });
  it("sends a signed-out visitor to sign in and back", async () => {
    auth.getCurrentUser.mockResolvedValue(null);
    window.history.pushState({}, "", "/admin/users?x=1");
    render(<AuthGuard><Who /></AuthGuard>);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/login?next=%2Fadmin%2Fusers%3Fx%3D1"));
  });
  it("an administrator without a second factor goes to enrol; a non-admin goes to their dashboard", async () => {
    auth.getCurrentUser.mockResolvedValue({ ...me, mfa_setup_required: true });
    render(<AuthGuard requireAdmin><Who /></AuthGuard>);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/settings#security"));
    auth.getCurrentUser.mockResolvedValue({ ...me, is_admin: false });
    render(<AuthGuard requireAdmin><Who /></AuthGuard>);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/dashboard"));
  });
});

describe("step-up dialog", () => {
  function setup(http: (url: string, init: RequestInit) => Response) {
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => http(url, init)));
    render(<StepUpProvider><button>opener</button></StepUpProvider>);
  }

  it("asks for a code, confirms it with the server, and resolves the waiting request", async () => {
    setup(() => new Response("{}", { status: 200 }));
    const u = userEvent.setup();
    const pending = askStepUp();
    const dialog = await screen.findByTestId("stepup-dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await waitFor(() => expect(screen.getByLabelText("Authenticator code")).toHaveFocus());
    expect(screen.getByTestId("stepup-confirm")).toBeDisabled();
    await u.type(screen.getByLabelText("Authenticator code"), " 123456 ");
    await u.click(screen.getByTestId("stepup-confirm"));
    expect(await pending).toBe(true);
    await waitFor(() => expect(screen.queryByTestId("stepup-dialog")).not.toBeInTheDocument());
    const call = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find((c) => String(c[0]).endsWith("/me/step-up"))!;
    expect(JSON.parse(call[1].body)).toEqual({ code: "123456" });
  });

  it("a wrong code is explained inline, the field is cleared, and the prompt stays", async () => {
    setup((url) => (url.endsWith("/me/step-up") ? new Response(JSON.stringify({ detail: "Invalid or expired code" }), { status: 400 }) : new Response("{}")));
    const u = userEvent.setup();
    askStepUp();
    await u.type(await screen.findByLabelText("Authenticator code"), "000000");
    await u.click(screen.getByTestId("stepup-confirm"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid or expired code");
    expect(screen.getByLabelText("Authenticator code")).toHaveValue("");
    expect(screen.getByTestId("stepup-dialog")).toBeInTheDocument();
  });

  it("cancel and Escape refuse, and several waiting requests share one prompt", async () => {
    setup(() => new Response("{}"));
    const u = userEvent.setup();
    const a = askStepUp();
    const b = askStepUp();
    expect(await screen.findAllByTestId("stepup-dialog")).toHaveLength(1);
    await u.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await Promise.all([a, b])).toEqual([false, false]);
    const c = askStepUp();
    await screen.findByTestId("stepup-dialog");
    await u.keyboard("{Escape}");
    expect(await c).toBe(false);
    await waitFor(() => expect(screen.queryByTestId("stepup-dialog")).not.toBeInTheDocument());
  });
});
