import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ProfileRoute } from "./ProfileRoute";
import { AuthedLayout } from "../components/AuthedLayout";
import {
  ApiError,
  exportMyData,
  getClubs,
  getGoogleEnabled,
  getMe,
  setPassword,
  startGoogleLink,
  updateDisplayName,
} from "../services/api";
import type { Club, UserProfile } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock the API module (no network). Keep ApiError real.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    getClubs: vi.fn(),
    getMe: vi.fn(),
    updateDisplayName: vi.fn(),
    exportMyData: vi.fn(),
    getGoogleEnabled: vi.fn(),
    setPassword: vi.fn(),
    startGoogleLink: vi.fn(),
  };
});

vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockGetClubs = vi.mocked(getClubs);
const mockGetMe = vi.mocked(getMe);
const mockUpdateDisplayName = vi.mocked(updateDisplayName);
const mockExportMyData = vi.mocked(exportMyData);
const mockGetGoogleEnabled = vi.mocked(getGoogleEnabled);
const mockSetPassword = vi.mocked(setPassword);
const mockStartGoogleLink = vi.mocked(startGoogleLink);
const mockUseAuth = vi.mocked(useAuth);
const applyDisplayName = vi.fn();
const mockLogoutAll = vi.fn();

function setAuth(displayName: string | null = "Ada") {
  mockUseAuth.mockReturnValue({
    status: "authenticated",
    isAuthenticated: true,
    setAccessToken: vi.fn(),
    clear: vi.fn(),
    logout: vi.fn(),
    logoutAll: mockLogoutAll,
    displayName,
    email: "ada@example.com",
    userId: "user-1",
    isPlatformAdmin: false,
    profileStatus: "ready",
    needsOnboarding: false,
    applyDisplayName,
    preferredService: null,
    tosAccepted: true,
    applyTosAccepted: vi.fn(),
  });
}

function clubWith(overrides: Partial<Club> = {}): Club {
  return {
    id: "club-1",
    name: "Friday Mixtape",
    description: null,
    organizer_id: "org-1",
    total_mixes: 6,
    votes_per_player: 3,
    songs_per_submission: 1,
    current_mix: 6,
    state: "complete",
    default_vibe_mode: false,
    submission_window_hours: 72,
    voting_window_hours: 72,
    created_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-02-01T00:00:00Z",
    ...overrides,
  };
}

function profileWith(
  displayName: string,
  overrides: Partial<Pick<UserProfile, "has_password" | "google_linked">> = {},
): UserProfile {
  return {
    id: "user-1",
    display_name: displayName,
    email: "ada@example.com",
    preferred_service: null,
    is_platform_admin: false,
    tos_accepted: true,
    has_password: false,
    google_linked: false,
    ...overrides,
  };
}

function renderProfile(initialPath = "/profile") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        {/* Mirror production: the profile route lives under AuthedLayout, which
            renders the shared TopNav once above the routed content. */}
        <Route element={<AuthedLayout />}>
          <Route path="/profile" element={<ProfileRoute />} />
        </Route>
        <Route path="/home" element={<div>HOME CONTENT</div>} />
        <Route path="/clubs/:id" element={<div>CLUB DETAIL CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProfileRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setAuth("Ada");
    mockGetClubs.mockResolvedValue([]);
    mockGetMe.mockResolvedValue(profileWith("Ada"));
    mockGetGoogleEnabled.mockResolvedValue({ enabled: false });
  });

  it("renders the current display name and only the completed clubs, newest first", async () => {
    mockGetClubs.mockResolvedValue([
      clubWith({ id: "active-1", name: "In Progress", state: "active", completed_at: null }),
      clubWith({ id: "old", name: "Old Mix", completed_at: "2026-01-15T00:00:00Z" }),
      clubWith({ id: "new", name: "New Mix", completed_at: "2026-03-15T00:00:00Z" }),
    ]);

    renderProfile();

    // Active club is excluded from the archive.
    expect(await screen.findByText("archived (2)")).toBeInTheDocument();
    expect(screen.queryByText("In Progress")).not.toBeInTheDocument();

    // Account email shown read-only from the auth context.
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();

    // Name field seeded from the auth context.
    const nameInput = screen.getByLabelText(/^name$/i) as HTMLInputElement;
    expect(nameInput.value).toBe("Ada");

    // Newest-completed appears before the older one.
    const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(titles).toEqual(["New Mix", "Old Mix"]);
  });

  it("empty archive: shows a calm note", async () => {
    mockGetClubs.mockResolvedValue([
      clubWith({ state: "active", completed_at: null }),
    ]);

    renderProfile();

    expect(await screen.findByText(/no completed clubs yet/i)).toBeInTheDocument();
  });

  it("save: a changed name calls updateDisplayName, applies it, and acknowledges", async () => {
    mockUpdateDisplayName.mockResolvedValue(profileWith("Ada Lovelace"));
    const user = userEvent.setup();

    renderProfile();
    await screen.findByText(/archived/i);

    const nameInput = screen.getByLabelText(/^name$/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Ada Lovelace");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(mockUpdateDisplayName).toHaveBeenCalledWith("Ada Lovelace");
    await waitFor(() => expect(applyDisplayName).toHaveBeenCalledWith("Ada Lovelace"));
    expect(await screen.findByText("saved")).toBeInTheDocument();
  });

  it("save: an unchanged name does not call updateDisplayName", async () => {
    const user = userEvent.setup();

    renderProfile();
    await screen.findByText(/archived/i);

    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(mockUpdateDisplayName).not.toHaveBeenCalled();
  });

  it("save: a failure shows a calm retryable error", async () => {
    mockUpdateDisplayName.mockRejectedValue(new ApiError(409, "name taken"));
    const user = userEvent.setup();

    renderProfile();
    await screen.findByText(/archived/i);

    const nameInput = screen.getByLabelText(/^name$/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Taken");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/name taken/i)).toBeInTheDocument();
  });

  it("archived club is linkable to its club home", async () => {
    mockGetClubs.mockResolvedValue([clubWith({ id: "club-9", name: "Click Me" })]);
    const user = userEvent.setup();

    renderProfile();
    await screen.findByText("Click Me");

    await user.click(screen.getByText("Click Me"));

    expect(await screen.findByText("CLUB DETAIL CONTENT")).toBeInTheDocument();
  });

  it("load failure: shows a calm error", async () => {
    mockGetClubs.mockRejectedValue(new ApiError(500, "boom"));

    renderProfile();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("nav: the TopNav home link navigates to /home", async () => {
    const user = userEvent.setup();

    renderProfile();
    await screen.findByText(/archived/i);

    // Two "home" controls in the TopNav (ring mark + text link); either routes home.
    await user.click(screen.getAllByRole("button", { name: /^home$/i })[1]);

    expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
  });

  it("security: log out of all devices button calls logoutAll", async () => {
    mockLogoutAll.mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderProfile();
    await screen.findByText(/archived/i);

    await user.click(screen.getByRole("button", { name: /log out of all devices/i }));

    expect(mockLogoutAll).toHaveBeenCalledOnce();
  });

  it("your data: download my data fetches the export and triggers a file download", async () => {
    mockExportMyData.mockResolvedValue({ profile: { email: "ada@example.com" } });
    const user = userEvent.setup();
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    const createObjectURL = vi.fn(() => "blob:mock-url");
    const revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    try {
      renderProfile();
      await screen.findByText(/archived/i);

      await user.click(screen.getByRole("button", { name: /download my data/i }));

      await waitFor(() => expect(mockExportMyData).toHaveBeenCalledOnce());
      expect(createObjectURL).toHaveBeenCalledOnce();
      expect(clickSpy).toHaveBeenCalledOnce();
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
    } finally {
      clickSpy.mockRestore();
      URL.createObjectURL = originalCreateObjectURL;
      URL.revokeObjectURL = originalRevokeObjectURL;
    }
  });

  it("your data: a failed export shows a calm retryable error", async () => {
    mockExportMyData.mockRejectedValue(new ApiError(500, "boom"));
    const user = userEvent.setup();

    renderProfile();
    await screen.findByText(/archived/i);

    await user.click(screen.getByRole("button", { name: /download my data/i }));

    expect(await screen.findByText(/boom/i)).toBeInTheDocument();
  });

  describe("account settings: set password", () => {
    it("no password yet: submitting the form calls setPassword and swaps in the status line", async () => {
      mockSetPassword.mockResolvedValue({ message: "ok" });
      const user = userEvent.setup();

      renderProfile();
      await screen.findByText(/archived/i);

      await user.type(screen.getByLabelText(/new password/i), "a-strong-password");
      await user.click(screen.getByRole("button", { name: /^set password$/i }));

      expect(mockSetPassword).toHaveBeenCalledWith("a-strong-password");
      expect(await screen.findByText("password set")).toBeInTheDocument();
      expect(screen.queryByLabelText(/new password/i)).not.toBeInTheDocument();
    });

    it("too short: rejects client-side without calling setPassword", async () => {
      const user = userEvent.setup();

      renderProfile();
      await screen.findByText(/archived/i);

      await user.type(screen.getByLabelText(/new password/i), "short");
      await user.click(screen.getByRole("button", { name: /^set password$/i }));

      expect(await screen.findByText(/use at least 8 characters/i)).toBeInTheDocument();
      expect(mockSetPassword).not.toHaveBeenCalled();
    });

    it("password already set: shows the status line, no form", async () => {
      mockGetMe.mockResolvedValue(profileWith("Ada", { has_password: true }));

      renderProfile();
      await screen.findByText(/archived/i);

      expect(screen.getByText("password set")).toBeInTheDocument();
      expect(screen.queryByLabelText(/new password/i)).not.toBeInTheDocument();
    });

    it("a failed save shows a calm retryable error", async () => {
      mockSetPassword.mockRejectedValue(new ApiError(409, "a password is already set"));
      const user = userEvent.setup();

      renderProfile();
      await screen.findByText(/archived/i);

      await user.type(screen.getByLabelText(/new password/i), "a-strong-password");
      await user.click(screen.getByRole("button", { name: /^set password$/i }));

      expect(await screen.findByText(/a password is already set/i)).toBeInTheDocument();
    });
  });

  describe("account settings: link google", () => {
    it("google not configured: the section doesn't render at all", async () => {
      mockGetGoogleEnabled.mockResolvedValue({ enabled: false });

      renderProfile();
      await screen.findByText(/archived/i);

      expect(screen.queryByText(/google account/i)).not.toBeInTheDocument();
    });

    it("not linked: clicking the button starts the link flow and navigates to the authorize url", async () => {
      mockGetGoogleEnabled.mockResolvedValue({ enabled: true });
      mockStartGoogleLink.mockResolvedValue({ authorize_url: "https://accounts.google.com/o/oauth2/authorize" });
      const user = userEvent.setup();
      const originalLocation = window.location;
      // jsdom doesn't implement navigation; stub `location` so the assignment
      // the handler makes (`window.location.href = ...`) is observable instead
      // of throwing/no-oping.
      Object.defineProperty(window, "location", {
        configurable: true,
        value: { ...originalLocation, href: "" },
      });

      try {
        renderProfile();
        await screen.findByText(/archived/i);

        await user.click(screen.getByRole("button", { name: /link google account/i }));

        expect(mockStartGoogleLink).toHaveBeenCalledOnce();
        await waitFor(() =>
          expect(window.location.href).toBe("https://accounts.google.com/o/oauth2/authorize"),
        );
      } finally {
        Object.defineProperty(window, "location", {
          configurable: true,
          value: originalLocation,
        });
      }
    });

    it("already linked: shows the status line, no button", async () => {
      mockGetGoogleEnabled.mockResolvedValue({ enabled: true });
      mockGetMe.mockResolvedValue(profileWith("Ada", { google_linked: true }));

      renderProfile();
      await screen.findByText(/archived/i);

      expect(await screen.findByText("linked")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /link google account/i })).not.toBeInTheDocument();
    });
  });

  describe("account settings: google_link redirect outcome", () => {
    it("linked: shows a success message, re-fetches the profile, and strips the query param", async () => {
      mockGetGoogleEnabled.mockResolvedValue({ enabled: true });
      // First load: not yet linked. The mount-time re-fetch (triggered by
      // ?google_link=linked) resolves with google_linked true.
      mockGetMe
        .mockResolvedValueOnce(profileWith("Ada"))
        .mockResolvedValueOnce(profileWith("Ada", { google_linked: true }));

      renderProfile("/profile?google_link=linked");

      expect(await screen.findByText(/google account linked\./i)).toBeInTheDocument();
      await waitFor(() => expect(mockGetMe).toHaveBeenCalledTimes(2));
      expect(await screen.findByText("linked")).toBeInTheDocument();
    });

    it("already_linked_elsewhere: shows a plain-language explanation, not a generic error", async () => {
      mockGetGoogleEnabled.mockResolvedValue({ enabled: true });

      renderProfile("/profile?google_link=already_linked_elsewhere");

      expect(
        await screen.findByText(/already linked to a different mysterymixclub account/i),
      ).toBeInTheDocument();
      // Only the one profile fetch from the initial load -- "already_linked_elsewhere"
      // doesn't warrant a re-fetch since nothing changed.
      expect(mockGetMe).toHaveBeenCalledOnce();
    });
  });
});
