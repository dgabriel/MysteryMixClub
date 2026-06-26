import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { OnboardingRoute } from "./OnboardingRoute";
import { ApiError, updateDisplayName } from "../services/api";
import type { UserProfile } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock the API module (no network).
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>(
    "../services/api",
  );
  return {
    ...actual,
    updateDisplayName: vi.fn(),
  };
});

// Mock useAuth so we can drive status/profileStatus/needsOnboarding directly.
vi.mock("../hooks/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockUpdateDisplayName = vi.mocked(updateDisplayName);
const mockUseAuth = vi.mocked(useAuth);
const applyDisplayName = vi.fn();

type Status = "loading" | "authenticated" | "unauthenticated";
type ProfileStatus = "idle" | "loading" | "ready";

function setAuth(
  status: Status,
  overrides: { profileStatus?: ProfileStatus; needsOnboarding?: boolean } = {},
) {
  const profileStatus =
    overrides.profileStatus ?? (status === "authenticated" ? "ready" : "idle");
  mockUseAuth.mockReturnValue({
    status,
    isAuthenticated: status === "authenticated",
    setAccessToken: vi.fn(),
    clear: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
    displayName: overrides.needsOnboarding ? "" : "ada",
    email: status === "authenticated" ? "ada@example.com" : null,
    userId: status === "authenticated" ? "11111111-1111-1111-1111-111111111111" : null,
    isPlatformAdmin: false,
    profileStatus,
    needsOnboarding: overrides.needsOnboarding ?? false,
    applyDisplayName,
  });
}

function profileWith(displayName: string): UserProfile {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    display_name: displayName,
    email: "new@example.com",
    preferred_service: null,
    default_vibe_mode: false,
    is_platform_admin: false,
  };
}

function renderOnboarding() {
  return render(
    <MemoryRouter initialEntries={["/onboarding"]}>
      <Routes>
        <Route path="/onboarding" element={<OnboardingRoute />} />
        <Route path="/home" element={<div>HOME CONTENT</div>} />
        <Route path="/login" element={<div>LOGIN CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("OnboardingRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("needsOnboarding: renders the OnboardingScreen", () => {
    setAuth("authenticated", { needsOnboarding: true });
    renderOnboarding();

    expect(screen.getByText("one more thing")).toBeInTheDocument();
    expect(screen.getByLabelText(/display name/i)).toBeInTheDocument();
    // The shared TopNav is not shown during onboarding.
    expect(screen.queryByRole("button", { name: /^profile$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^logout$/i })).not.toBeInTheDocument();
  });

  it("successful submit: trims the name, calls updateDisplayName + applyDisplayName, navigates to /home", async () => {
    setAuth("authenticated", { needsOnboarding: true });
    mockUpdateDisplayName.mockResolvedValue(profileWith("Alice"));
    const user = userEvent.setup();

    renderOnboarding();

    await user.type(screen.getByLabelText(/display name/i), "  Alice  ");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
    // Trimmed before the API call.
    expect(mockUpdateDisplayName).toHaveBeenCalledTimes(1);
    expect(mockUpdateDisplayName).toHaveBeenCalledWith("Alice");
    // applyDisplayName is fed the name the server returned.
    expect(applyDisplayName).toHaveBeenCalledWith("Alice");
  });

  it("submit failure: shows the calm error and stays on the screen", async () => {
    setAuth("authenticated", { needsOnboarding: true });
    mockUpdateDisplayName.mockRejectedValue(new ApiError(422, "too long"));
    const user = userEvent.setup();

    renderOnboarding();

    await user.type(screen.getByLabelText(/display name/i), "Bob");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "that didn't save. try again.",
    );
    // Still on the onboarding screen — no navigation occurred.
    expect(screen.queryByText("HOME CONTENT")).not.toBeInTheDocument();
    expect(screen.getByText("one more thing")).toBeInTheDocument();
    expect(applyDisplayName).not.toHaveBeenCalled();
  });

  it("guard: unauthenticated redirects to /login (does not render the form)", () => {
    setAuth("unauthenticated");
    renderOnboarding();

    expect(screen.getByText("LOGIN CONTENT")).toBeInTheDocument();
    expect(screen.queryByText("one more thing")).not.toBeInTheDocument();
  });

  it("guard: authenticated but already onboarded redirects to /home", () => {
    setAuth("authenticated", { needsOnboarding: false });
    renderOnboarding();

    expect(screen.getByText("HOME CONTENT")).toBeInTheDocument();
    expect(screen.queryByText("one more thing")).not.toBeInTheDocument();
  });

  it("guard: while the profile is still loading, renders the loading motif (not the form)", () => {
    setAuth("authenticated", { profileStatus: "loading" });
    renderOnboarding();

    expect(screen.getByText(/verifying/i)).toBeInTheDocument();
    expect(screen.queryByText("one more thing")).not.toBeInTheDocument();
    expect(screen.queryByText("HOME CONTENT")).not.toBeInTheDocument();
  });

  it("disables the submit while a save is in flight (busy)", async () => {
    setAuth("authenticated", { needsOnboarding: true });
    let resolve!: (p: UserProfile) => void;
    mockUpdateDisplayName.mockReturnValue(
      new Promise<UserProfile>((r) => {
        resolve = r;
      }),
    );
    const user = userEvent.setup();

    renderOnboarding();

    await user.type(screen.getByLabelText(/display name/i), "Cleo");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /saving/i })).toBeDisabled(),
    );

    // Resolve so the trailing navigation flushes inside act().
    resolve(profileWith("Cleo"));
    expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
  });
});
