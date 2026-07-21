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
    tosAccepted: true,
    applyTosAccepted: vi.fn(),
  });
}

// The About page (MYS-155) renders TopNav for signed-out — or still-resolving
// — visitors too, so the nav must collapse safely for both.
function setUnauthed(status: "unauthenticated" | "loading" = "unauthenticated") {
  mockUseAuth.mockReturnValue({
    status,
    isAuthenticated: false,
    setAccessToken: vi.fn(),
    clear: vi.fn(),
    logout,
    logoutAll: vi.fn(),
    displayName: null,
    email: null,
    userId: null,
    isPlatformAdmin: false,
    profileStatus: "idle",
    needsOnboarding: false,
    applyDisplayName: vi.fn(),
    preferredService: null,
    tosAccepted: true,
    applyTosAccepted: vi.fn(),
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
        <Route path="/about" element={<div>ABOUT CONTENT</div>} />
        <Route path="/faq" element={<div>FAQ CONTENT</div>} />
        <Route path="/admin" element={<div>ADMIN CONTENT</div>} />
        <Route path="/login" element={<div>LOGIN CONTENT</div>} />
        <Route path="/clubs/:id" element={<div>CLUB CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("TopNav", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setAuth(false);
  });

  it("renders home / profile / about / faq / logout for any authed user, and hides admin for non-admins", () => {
    renderNav();

    // Two home controls: the ring mark (aria-label) and the text link.
    expect(screen.getAllByRole("button", { name: /^home$/i })).toHaveLength(2);
    expect(screen.getByRole("button", { name: /^profile$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^about$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^faq$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^logout$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^admin$/i })).not.toBeInTheDocument();
  });

  it("about link routes to /about", async () => {
    const user = userEvent.setup();
    renderNav();

    await user.click(screen.getByRole("button", { name: /^about$/i }));
    expect(await screen.findByText("ABOUT CONTENT")).toBeInTheDocument();
  });

  it("faq link routes to /faq", async () => {
    const user = userEvent.setup();
    renderNav();

    await user.click(screen.getByRole("button", { name: /^faq$/i }));
    expect(await screen.findByText("FAQ CONTENT")).toBeInTheDocument();
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
    renderNav(<TopNav back={{ label: "club", to: "/clubs/lg-1" }} />);

    // The back-arrow is a line icon (aria-hidden); the control's name is its label.
    await user.click(screen.getByRole("button", { name: /^club$/i }));
    expect(await screen.findByText("CLUB CONTENT")).toBeInTheDocument();
  });

  it("no back affordance is rendered when none is provided", () => {
    renderNav();
    expect(screen.queryByRole("button", { name: /^club$/i })).not.toBeInTheDocument();
  });

  describe("signed-out visitor (MYS-155: nav on the public /about page)", () => {
    it("collapses to just a login link, hiding every authed-only action", () => {
      setUnauthed();
      renderNav();

      // Two login controls: the ring mark (aria-label) and the text link.
      expect(screen.getAllByRole("button", { name: /^login$/i })).toHaveLength(2);
      expect(screen.queryByRole("button", { name: /^home$/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^profile$/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^about$/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^faq$/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^admin$/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^logout$/i })).not.toBeInTheDocument();
    });

    it("also collapses while auth status is still resolving", () => {
      setUnauthed("loading");
      renderNav();
      expect(screen.getAllByRole("button", { name: /^login$/i }).length).toBeGreaterThan(0);
      expect(screen.queryByRole("button", { name: /^profile$/i })).not.toBeInTheDocument();
    });

    it("the login text link routes to /login", async () => {
      setUnauthed();
      const user = userEvent.setup();
      renderNav();

      const loginControls = screen.getAllByRole("button", { name: /^login$/i });
      await user.click(loginControls[loginControls.length - 1]);
      expect(await screen.findByText("LOGIN CONTENT")).toBeInTheDocument();
    });
  });
});
