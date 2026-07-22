import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ProfileRoute } from "./ProfileRoute";
import { AuthedLayout } from "../components/AuthedLayout";
import { ApiError, exportMyData, getClubs, getMe, updateDisplayName } from "../services/api";
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
  };
});

vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockGetClubs = vi.mocked(getClubs);
const mockGetMe = vi.mocked(getMe);
const mockUpdateDisplayName = vi.mocked(updateDisplayName);
const mockExportMyData = vi.mocked(exportMyData);
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

function profileWith(displayName: string): UserProfile {
  return {
    id: "user-1",
    display_name: displayName,
    email: "ada@example.com",
    preferred_service: null,
    is_platform_admin: false,
    tos_accepted: true,
  };
}

function renderProfile() {
  return render(
    <MemoryRouter initialEntries={["/profile"]}>
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
});
