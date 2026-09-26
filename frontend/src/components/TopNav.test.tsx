import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { TopNav } from "./TopNav";
import { useAuth } from "../hooks/useAuth";

vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

// Mutable so a single test (MysteryMixClub-4vii.41) can flip native mode on;
// vi.hoisted lifts this above vi.mock's own hoisting so the factory below can
// close over it. Every other test leaves it false, matching IS_NATIVE_BUILD's
// real value in this (non-Capacitor) test environment.
const platform = vi.hoisted(() => ({ isNative: false }));
vi.mock("../lib/platform", () => ({
  get IS_NATIVE_BUILD() {
    return platform.isNative;
  },
}));

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
        <Route path="/help" element={<div>HELP CONTENT</div>} />
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
    platform.isNative = false;
    setAuth(false);
  });

  it("renders my clubs / profile / about / help / logout for any authed user, and hides admin for non-admins", () => {
    renderNav();

    // Two "my clubs" controls: the ring mark (aria-label) and the text link.
    expect(screen.getAllByRole("button", { name: /^my clubs$/i })).toHaveLength(2);
    expect(screen.getByRole("button", { name: /^profile$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^about$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^help$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^logout$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^admin$/i })).not.toBeInTheDocument();
  });

  it("about link routes to /about", async () => {
    const user = userEvent.setup();
    renderNav();

    await user.click(screen.getByRole("button", { name: /^about$/i }));
    expect(await screen.findByText("ABOUT CONTENT")).toBeInTheDocument();
  });

  it("help link routes to /help", async () => {
    const user = userEvent.setup();
    renderNav();

    await user.click(screen.getByRole("button", { name: /^help$/i }));
    expect(await screen.findByText("HELP CONTENT")).toBeInTheDocument();
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

    // The ring mark and the text link both label "my clubs"; the mark is first.
    const myClubsControls = screen.getAllByRole("button", { name: /^my clubs$/i });
    await user.click(myClubsControls[0]);
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

  describe("mobile menu (MysteryMixClub-4vii: below `sm`, and the only layout on the iOS app)", () => {
    it("is closed by default -- desktop's inline row is the only nav in the DOM", () => {
      renderNav();
      // Two "my clubs" controls (ring mark + desktop link), not three: the
      // mobile panel's own "my clubs" link isn't rendered until opened.
      expect(screen.getAllByRole("button", { name: /^my clubs$/i })).toHaveLength(2);
      expect(screen.getByRole("button", { name: /^open menu$/i })).toBeInTheDocument();
    });

    it("opens on the hamburger toggle and closes on the same button", async () => {
      const user = userEvent.setup();
      renderNav();

      await user.click(screen.getByRole("button", { name: /^open menu$/i }));
      expect(screen.getAllByRole("button", { name: /^my clubs$/i })).toHaveLength(3);

      await user.click(screen.getByRole("button", { name: /^close menu$/i }));
      expect(screen.getAllByRole("button", { name: /^my clubs$/i })).toHaveLength(2);
    });

    it("closes on tapping the backdrop", async () => {
      const user = userEvent.setup();
      renderNav();

      await user.click(screen.getByRole("button", { name: /^open menu$/i }));
      await user.click(screen.getByRole("button", { name: /^dismiss menu$/i }));
      expect(screen.getAllByRole("button", { name: /^my clubs$/i })).toHaveLength(2);
    });

    it("a mobile link navigates and closes the panel", async () => {
      const user = userEvent.setup();
      renderNav();

      await user.click(screen.getByRole("button", { name: /^open menu$/i }));
      const aboutButtons = screen.getAllByRole("button", { name: /^about$/i });
      // Desktop's (hidden via CSS, not the DOM) and the mobile panel's --
      // the mobile one is the one added last.
      expect(aboutButtons).toHaveLength(2);
      await user.click(aboutButtons[aboutButtons.length - 1]);

      // The test harness's /about route replaces TopNav entirely (it isn't a
      // persistent layout here), so reaching this content is itself proof
      // the mobile link's navigation fired correctly.
      expect(await screen.findByText("ABOUT CONTENT")).toBeInTheDocument();
    });

    it("shows the admin entry in the mobile panel for a platform admin only", async () => {
      setAuth(true);
      const user = userEvent.setup();
      renderNav();

      await user.click(screen.getByRole("button", { name: /^open menu$/i }));
      expect(screen.getAllByRole("button", { name: /^admin$/i })).toHaveLength(2);
    });
  });

  describe("beta badge (MysteryMixClub-4vii.41: Guideline 2.2, no beta label in the App Store build)", () => {
    it("shows the what's new / beta trigger on web, authed", () => {
      renderNav();
      expect(screen.getByRole("button", { name: /^what's new$/i })).toBeInTheDocument();
    });

    it("shows the what's new / beta trigger on web, signed-out", () => {
      setUnauthed();
      renderNav();
      expect(screen.getByRole("button", { name: /^what's new$/i })).toBeInTheDocument();
    });

    it("hides the beta badge entirely on a native build, authed", () => {
      platform.isNative = true;
      renderNav();
      expect(screen.queryByRole("button", { name: /^what's new$/i })).not.toBeInTheDocument();
      expect(screen.queryByText("beta")).not.toBeInTheDocument();
    });

    it("hides the beta badge entirely on a native build, signed-out", () => {
      platform.isNative = true;
      setUnauthed();
      renderNav();
      expect(screen.queryByRole("button", { name: /^what's new$/i })).not.toBeInTheDocument();
      expect(screen.queryByText("beta")).not.toBeInTheDocument();
    });
  });

  describe("signed-out visitor (MYS-155: nav on the public /about page)", () => {
    it("collapses to just a login link, hiding every authed-only action", () => {
      setUnauthed();
      renderNav();

      // Two login controls: the ring mark (aria-label) and the text link.
      expect(screen.getAllByRole("button", { name: /^login$/i })).toHaveLength(2);
      expect(screen.queryByRole("button", { name: /^my clubs$/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^profile$/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^about$/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^help$/i })).not.toBeInTheDocument();
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
