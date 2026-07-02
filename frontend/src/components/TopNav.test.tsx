import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { TopNav } from "./TopNav";
import { useAuth } from "../hooks/useAuth";

vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockUseAuth = vi.mocked(useAuth);
const logout = vi.fn();

function setAuth(isPlatformAdmin: boolean) {
  mockUseAuth.mockReturnValue({
    status: "authenticated",
    isAuthenticated: true,
    setAccessToken: vi.fn(),
    clear: vi.fn(),
    logout,
    logoutAll: vi.fn(),
    displayName: "Ada",
    email: "ada@example.com",
    userId: "user-1",
    isPlatformAdmin,
    profileStatus: "ready",
    needsOnboarding: false,
    applyDisplayName: vi.fn(),
    preferredService: null,
  });
}

function renderNav(ui = <TopNav />, at = "/start") {
  return render(
    <MemoryRouter initialEntries={[at]}>
      <Routes>
        {/* Mount the nav on a neutral route so navigating to /home is observable. */}
        <Route path="/start" element={ui} />
        <Route path="/home" element={<div>HOME CONTENT</div>} />
        <Route path="/profile" element={<div>PROFILE CONTENT</div>} />
        <Route path="/admin" element={<div>ADMIN CONTENT</div>} />
        <Route path="/login" element={<div>LOGIN CONTENT</div>} />
        <Route path="/leagues/:id" element={<div>LEAGUE CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("TopNav", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setAuth(false);
  });

  it("renders home / profile / logout for any authed user, and hides admin for non-admins", () => {
    renderNav();

    // Two home controls: the ring mark (aria-label) and the text link.
    expect(screen.getAllByRole("button", { name: /^home$/i })).toHaveLength(2);
    expect(screen.getByRole("button", { name: /^profile$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^logout$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^admin$/i })).not.toBeInTheDocument();
  });

  it("shows the admin entry for a platform admin and routes to /admin", async () => {
    setAuth(true);
    const user = userEvent.setup();
    renderNav();

    await user.click(screen.getByRole("button", { name: /^admin$/i }));
    expect(await screen.findByText("ADMIN CONTENT")).toBeInTheDocument();
  });

  it("profile link routes to /profile", async () => {
    const user = userEvent.setup();
    renderNav();

    await user.click(screen.getByRole("button", { name: /^profile$/i }));
    expect(await screen.findByText("PROFILE CONTENT")).toBeInTheDocument();
  });

  it("logout invokes useAuth().logout and routes to /login", async () => {
    logout.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderNav();

    await user.click(screen.getByRole("button", { name: /^logout$/i }));

    expect(logout).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("LOGIN CONTENT")).toBeInTheDocument();
  });

  it("the ring mark routes home", async () => {
    const user = userEvent.setup();
    renderNav();

    // The ring mark and the text link both label "home"; the mark is first.
    const homeControls = screen.getAllByRole("button", { name: /^home$/i });
    await user.click(homeControls[0]);
    expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
  });

  it("back affordance, when provided, routes to its target", async () => {
    const user = userEvent.setup();
    renderNav(<TopNav back={{ label: "league", to: "/leagues/lg-1" }} />);

    // The back-arrow is a line icon (aria-hidden); the control's name is its label.
    await user.click(screen.getByRole("button", { name: /^league$/i }));
    expect(await screen.findByText("LEAGUE CONTENT")).toBeInTheDocument();
  });

  it("no back affordance is rendered when none is provided", () => {
    renderNav();
    expect(screen.queryByRole("button", { name: /^league$/i })).not.toBeInTheDocument();
  });
});
