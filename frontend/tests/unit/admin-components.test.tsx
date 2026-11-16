import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Users } from "lucide-react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fail, routes } from "./helpers";

const nav = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: nav.push, replace: vi.fn() }), usePathname: () => "/admin/dashboard" }));
vi.mock("@/lib/auth-client", () => ({ ensureCsrfToken: vi.fn(async () => "csrf") }));
vi.mock("@/lib/display", () => ({ setDisplayPrefs: vi.fn(), formatDateTime: (s: string) => `at ${s}` }));
const me = vi.hoisted(() => ({ user: { is_super_admin: true, is_admin: true } }));
vi.mock("@/components/auth-guard", () => ({ useCurrentUser: () => me.user }));

import { CommandPalette } from "@/components/command-palette";
import { SessionsCard } from "@/components/sessions-card";
import { SetupChecklist } from "@/components/setup-checklist";
import AdminDashboard from "@/app/admin/dashboard/page";
import RolesPage from "@/app/admin/roles/page";

beforeEach(() => {
  nav.push.mockReset();
  me.user = { is_super_admin: true, is_admin: true };
});

describe("command palette", () => {
  const nav_ = [{ items: [{ href: "/admin/users", label: "Users", icon: Users }, { href: "/admin/audit", label: "Audit log", icon: Users }] }];
  const open = async () => {
    const u = userEvent.setup();
    render(<CommandPalette nav={nav_} />);
    window.dispatchEvent(new Event("open-command-palette"));
    const box = await screen.findByRole("combobox", { name: "Search" });
    return { u, box };
  };

  it("opens with Ctrl+K, lists tasks and pages, and Escape closes it", async () => {
    routes({ "GET /admin/search": { results: [] } });
    const u = userEvent.setup();
    render(<CommandPalette nav={nav_} />);
    await u.keyboard("{Control>}k{/Control}");
    expect(await screen.findByRole("dialog", { name: "Search" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Add an app/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Users/ })).toBeInTheDocument();
    await u.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("finds a task by what the person means and goes there with Enter", async () => {
    routes({ "GET /admin/search": { results: [] } });
    const { u, box } = await open();
    await u.type(box, "failed sign-in");
    expect(await screen.findByRole("option", { name: /Investigate a login/ })).toHaveAttribute("aria-selected", "true");
    await u.keyboard("{Enter}");
    expect(nav.push).toHaveBeenCalledWith("/admin/audit?action=LOGIN_FAILURE");
  });

  it("searches people and apps on the server and moves through the results with the arrow keys", async () => {
    routes({ "GET /admin/search": { results: [{ kind: "user", id: 7, title: "Ada Lovelace", subtitle: "ada@example.com", href: "/admin/users/7" }] } });
    const { u, box } = await open();
    await u.type(box, "ada");
    const hit = await screen.findByRole("option", { name: /Ada Lovelace/ });
    await u.keyboard("{ArrowDown}{ArrowDown}{ArrowUp}");
    expect(box).toHaveAttribute("aria-activedescendant");
    await u.click(hit);
    expect(nav.push).toHaveBeenCalledWith("/admin/users/7");
  });

  it("Tab stays in the dialog and a failed search shows no matches", async () => {
    routes({ "GET /admin/search": () => fail(500, "boom") });
    const { u, box } = await open();
    await u.type(box, "zzzz");
    expect(await screen.findByText("No matches")).toBeInTheDocument();
    await u.tab();
    expect(box).toHaveFocus();
  });

  it("clicking the backdrop closes it and hands focus back", async () => {
    routes({ "GET /admin/search": { results: [] } });
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    await open();
    fireEvent.mouseDown(screen.getByRole("dialog")); // not userEvent: its default action would move focus to body after the handler ran
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });
});

describe("first-run checklist", () => {
  const items = [
    { id: "branding", title: "Set your branding", description: "Name and colour", href: "/admin/branding", done: false, dismissed: false },
    { id: "application", title: "Add an application", description: "Connect an app", href: "/admin/applications", done: false, dismissed: false },
    { id: "network_zones", title: "Define a network zone", description: "Office ranges", href: "/admin/network-zones", done: true, dismissed: false },
    { id: "people", title: "Add a user or a group", description: "First person", href: "/admin/users", done: false, dismissed: true },
  ];

  it("lists what is left, counts what is done, and hides what was skipped", async () => {
    routes({ "GET /admin/setup-checklist": { items } });
    render(<SetupChecklist />);
    expect(await screen.findByText("Set your branding")).toBeInTheDocument();
    expect(screen.getByTestId("setup-progress")).toHaveTextContent("1 of 4 done");
    expect(screen.queryByText("Define a network zone")).not.toBeInTheDocument(); // done: gone
    expect(screen.queryByText("Add a user or a group")).not.toBeInTheDocument(); // skipped: hidden
    expect(screen.getByRole("link", { name: /Set your branding/ })).toHaveAttribute("href", "/admin/branding");
  });

  it("skipping stores the dismissal and refreshes; skipped items can be shown again", async () => {
    let list = items;
    const r = routes({
      "GET /admin/setup-checklist": () => ({ items: list }),
      "POST /admin/setup-checklist/branding/dismiss": () => { list = list.map((i) => (i.id === "branding" ? { ...i, dismissed: true } : i)); return undefined; },
      "DELETE /admin/setup-checklist/people/dismiss": () => { list = list.map((i) => (i.id === "people" ? { ...i, dismissed: false } : i)); return undefined; },
    });
    const u = userEvent.setup();
    render(<SetupChecklist />);
    await u.click(await screen.findByRole("button", { name: "Skip Set your branding" }));
    await waitFor(() => expect(screen.queryByText("Set your branding")).not.toBeInTheDocument());
    expect(r.calls.some((c) => c.method === "POST" && c.url.endsWith("/branding/dismiss"))).toBe(true);
    await u.click(screen.getByRole("button", { name: /Show 2 skipped/ }));
    await u.click(await screen.findByRole("button", { name: "Show Add a user or a group" }));
    await waitFor(() => expect(r.calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(await screen.findByText("Add a user or a group")).toBeInTheDocument();
  });

  it("shows nothing when everything is done, when the admin may see no item, or when it cannot load", async () => {
    routes({ "GET /admin/setup-checklist": { items: items.map((i) => ({ ...i, done: true })) } });
    const a = render(<SetupChecklist />);
    await waitFor(() => expect(screen.queryByTestId("setup-checklist")).not.toBeInTheDocument());
    a.unmount();
    routes({ "GET /admin/setup-checklist": { items: [] } });
    const b = render(<SetupChecklist />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("setup-checklist")).not.toBeInTheDocument();
    b.unmount();
    routes({ "GET /admin/setup-checklist": () => fail(500, "x") });
    render(<SetupChecklist />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("setup-checklist")).not.toBeInTheDocument();
  });

  it("says so when a dismissal could not be saved", async () => {
    routes({ "GET /admin/setup-checklist": { items }, "POST /admin/setup-checklist/branding/dismiss": () => fail(403, "Read-only") });
    const u = userEvent.setup();
    render(<SetupChecklist />);
    await u.click(await screen.findByRole("button", { name: "Skip Set your branding" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Read-only");
  });
});

describe("where you're signed in", () => {
  const rows = [
    { handle: "h-cur", current: true, device: "Chrome on macOS", ip_address: "10.0.0.1", created_at: "2026-11-01T10:00:00Z", last_activity_at: "2026-11-01T11:00:00Z", expires_at: "2026-11-02T10:00:00Z" },
    { handle: "h-other", current: false, device: "Firefox on Windows", ip_address: null, created_at: "2026-11-01T09:00:00Z", last_activity_at: null, expires_at: "2026-11-02T09:00:00Z" },
  ];

  it("lists the devices, marks this one, and offers sign-out only for the others", async () => {
    routes({ "GET /me/sessions": { items: rows } });
    render(<SessionsCard />);
    const list = await screen.findByTestId("sessions");
    expect(within(list).getAllByTestId("session-row")).toHaveLength(2);
    expect(within(list).getByText("this device")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out Firefox on Windows" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign out Chrome on macOS" })).not.toBeInTheDocument();
    expect(screen.getByText(/unknown IP/)).toBeInTheDocument();
  });

  it("signing one device out asks for the password, then signs it out by its handle", async () => {
    let live = rows;
    const r = routes({
      "GET /me/sessions": () => ({ items: live }),
      "POST /me/sessions/h-other/revoke": () => { live = [rows[0]]; return { revoked: 1 }; },
    });
    const u = userEvent.setup();
    render(<SessionsCard />);
    await u.click(await screen.findByRole("button", { name: "Sign out Firefox on Windows" }));
    const form = screen.getByTestId("session-reauth");
    expect(within(form).getByRole("button", { name: "Sign out" })).toBeDisabled();
    await u.type(within(form).getByLabelText(/Confirm your password/), "hunter2");
    await u.click(within(form).getByRole("button", { name: "Sign out" }));
    expect(await screen.findByTestId("sessions-msg")).toHaveTextContent("That session was signed out.");
    expect(r.calls.find((c) => c.method === "POST")!.body).toEqual({ password: "hunter2" });
    await waitFor(() => expect(screen.getAllByTestId("session-row")).toHaveLength(1));
  });

  it("a wrong password is reported, nothing changes, and the field is cleared", async () => {
    routes({ "GET /me/sessions": { items: rows }, "POST /me/sessions/h-other/revoke": () => fail(403, "Password is incorrect") });
    const u = userEvent.setup();
    render(<SessionsCard />);
    await u.click(await screen.findByRole("button", { name: "Sign out Firefox on Windows" }));
    await u.type(screen.getByLabelText(/Confirm your password/), "nope");
    await u.click(within(screen.getByTestId("session-reauth")).getByRole("button", { name: "Sign out" }));
    expect(await screen.findByTestId("sessions-msg")).toHaveTextContent("Password is incorrect");
    expect(screen.getAllByTestId("session-row")).toHaveLength(2);
    expect(screen.getByLabelText(/Confirm your password/)).toHaveValue("");
  });

  it("sign out all others reports how many, and cancel closes the prompt", async () => {
    routes({ "GET /me/sessions": { items: rows }, "POST /me/sessions/revoke-others": { revoked: 1 } });
    const u = userEvent.setup();
    render(<SessionsCard />);
    await u.click(await screen.findByRole("button", { name: "Sign out all other sessions" }));
    await u.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("session-reauth")).not.toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Sign out all other sessions" }));
    await u.type(screen.getByLabelText(/Confirm your password/), "pw");
    await u.click(within(screen.getByTestId("session-reauth")).getByRole("button", { name: "Sign out" }));
    expect(await screen.findByTestId("sessions-msg")).toHaveTextContent("Signed out 1 other session.");
  });

  it("with only this device there is no sign-out-others button, and a load failure is shown", async () => {
    routes({ "GET /me/sessions": { items: [rows[0]] } });
    const a = render(<SessionsCard />);
    await screen.findByTestId("sessions");
    expect(screen.queryByRole("button", { name: "Sign out all other sessions" })).not.toBeInTheDocument();
    a.unmount();
    routes({ "GET /me/sessions": () => fail(500, "Server error") });
    render(<SessionsCard />);
    expect(await screen.findByTestId("sessions-msg")).toHaveTextContent("Server error");
  });
});

describe("roles page", () => {
  const roles = [
    { id: "org_admin", label: "Organization administrator", description: "Everything", access: { users: "write", audit: "" } },
    { id: "help_desk_admin", label: "Help desk", description: "Resets", access: { users: "read" } },
  ];
  const group = (id: number, name: string, extra = {}) => ({ id, name, member_count: id, is_system_group: false, ...extra });
  const page = (items: unknown[]) => ({ Resources: items, totalResults: items.length, startIndex: 1, itemsPerPage: 100 });

  function api(holders: { group_id: number; name: string; roles: string[] }[], put: (...a: never[]) => unknown = () => ({})) {
    return routes({
      "GET /admin/roles": { items: roles },
      "GET /admin/roles/groups": () => ({ items: holders }),
      "GET /admin/groups": (_i: RequestInit, url: string) => page(url.includes("team") ? [group(1, "Ops"), group(2, "Support"), group(3, "System", { is_system_group: true })] : [group(4, "Admins")]),
      "PUT /admin/roles/groups/1": put,
    });
  }

  it("only super administrators may assign roles", async () => {
    me.user = { is_super_admin: false, is_admin: true };
    api([]);
    render(<RolesPage />);
    expect(await screen.findByTestId("roles-forbidden")).toBeInTheDocument();
  });

  it("shows each role with its access and the groups that hold it", async () => {
    api([{ group_id: 1, name: "Ops", roles: ["org_admin"] }]);
    render(<RolesPage />);
    const card = await screen.findByTestId("role-card-org_admin");
    expect(within(card).getByText("users: write")).toBeInTheDocument();
    expect(within(card).queryByText(/audit/)).not.toBeInTheDocument(); // an empty level is not shown
    expect(within(card).getByRole("link", { name: "Ops" })).toHaveAttribute("href", "/admin/groups/1");
    expect(within(card).getByText("1 member")).toBeInTheDocument();
    expect(screen.getByTestId("role-empty-help_desk_admin")).toBeInTheDocument();
    const choices = within(card).getByLabelText("Add a group to Organization administrator");
    expect(within(choices).queryByText(/Ops/)).not.toBeInTheDocument(); // already holds it
    expect(within(choices).queryByText(/System/)).not.toBeInTheDocument(); // system groups cannot hold roles
  });

  it("adding a group sends the full role list and confirms in words", async () => {
    const r = api([{ group_id: 1, name: "Ops", roles: ["org_admin"] }]);
    const u = userEvent.setup();
    render(<RolesPage />);
    const card = await screen.findByTestId("role-card-help_desk_admin");
    await u.selectOptions(within(card).getByLabelText("Add a group to Help desk"), "1");
    await u.click(within(card).getByRole("button", { name: "Add group to Help desk" }));
    expect(await screen.findByTestId("roles-msg")).toHaveTextContent("Ops now holds Help desk");
    expect(r.calls.find((c) => c.method === "PUT")!.body).toEqual({ roles: ["org_admin", "help_desk_admin"] });
  });

  it("removing asks first; declining changes nothing, accepting removes the role", async () => {
    const r = api([{ group_id: 1, name: "Ops", roles: ["org_admin"] }]);
    const u = userEvent.setup();
    render(<RolesPage />);
    const remove = await screen.findByRole("button", { name: "Remove Ops from Organization administrator" });
    vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    await u.click(remove);
    expect(r.calls.some((c) => c.method === "PUT")).toBe(false);
    vi.spyOn(window, "confirm").mockReturnValueOnce(true);
    await u.click(remove);
    expect(await screen.findByTestId("roles-msg")).toHaveTextContent("Ops no longer holds Organization administrator");
    expect(r.calls.find((c) => c.method === "PUT")!.body).toEqual({ roles: [] });
  });

  it("a refused change is shown as an error", async () => {
    api([{ group_id: 1, name: "Ops", roles: ["org_admin"] }], () => fail(409, "Group cannot hold roles") as never);
    const u = userEvent.setup();
    render(<RolesPage />);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await u.click(await screen.findByRole("button", { name: "Remove Ops from Organization administrator" }));
    expect(await screen.findByTestId("roles-msg")).toHaveTextContent("Group cannot hold roles");
  });

  it("explains when there are no team or role groups yet", async () => {
    routes({ "GET /admin/roles": { items: roles }, "GET /admin/roles/groups": { items: [] }, "GET /admin/groups": page([]) });
    render(<RolesPage />);
    expect(await screen.findByTestId("roles-no-teams")).toBeInTheDocument();
  });
});

describe("admin dashboard", () => {
  const dash = {
    tasks: [{ id: "failed_logins", severity: "high", title: "Failed sign-ins in the last 24 hours", count: 12, href: "/admin/audit?action=LOGIN_FAILURE" }],
    signins: [{ date: "2026-11-14", success: 4, failure: 1 }, { date: "2026-11-15", success: 9, failure: 0 }],
    users_by_status: { active: 5, locked_out: 1 }, apps_by_mode: { oidc: 2, saml: 1 }, apps_total: 3,
  };
  const stats = { users_total: 6, users_active: 5, admins: 2, groups: 3, memberships: 8, failed_logins_24h: 12, recent_events: [{ id: 1, timestamp: "2026-11-15T10:00:00Z", actor_email: null, action: "LOGIN_SUCCESS" }] };

  it("shows tasks, the checklist, quick tasks, charts and recent activity", async () => {
    routes({ "GET /admin/dashboard": dash, "GET /admin/stats": stats, "GET /admin/setup-checklist": { items: [{ id: "branding", title: "Set your branding", description: "d", href: "/admin/branding", done: false, dismissed: false }] } });
    render(<AdminDashboard />);
    expect(await screen.findByTestId("task-failed_logins")).toHaveTextContent("12");
    expect(await screen.findByTestId("setup-checklist")).toBeInTheDocument();
    expect(screen.getByTestId("quick-add-app")).toHaveAttribute("href", "/admin/applications/new");
    expect(await screen.findByTestId("widgets")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Sign-ins per day: 2026-11-14 4 succeeded, 1 failed/ })).toBeInTheDocument();
    expect(await screen.findByText("LOGIN_SUCCESS")).toBeInTheDocument();
    expect(screen.getByText("system")).toBeInTheDocument(); // no actor
  });

  it("says nothing needs attention, and shows no applications, when the install is empty", async () => {
    routes({
      "GET /admin/dashboard": { tasks: [], signins: [{ date: "2026-11-15", success: 0, failure: 0 }], users_by_status: {}, apps_by_mode: {}, apps_total: 0 },
      "GET /admin/stats": { ...stats, recent_events: [] }, "GET /admin/setup-checklist": { items: [] },
    });
    render(<AdminDashboard />);
    expect(await screen.findByTestId("tasks-empty")).toBeInTheDocument();
    expect(await screen.findByText("No applications yet.")).toBeInTheDocument();
    expect(await screen.findByText("No events yet.")).toBeInTheDocument();
  });

  it("shows an error when the numbers cannot be loaded", async () => {
    routes({ "GET /admin/dashboard": () => fail(500, "x"), "GET /admin/stats": () => fail(500, "Stats unavailable"), "GET /admin/setup-checklist": { items: [] } });
    render(<AdminDashboard />);
    expect(await screen.findByText("Stats unavailable")).toBeInTheDocument();
  });
});
