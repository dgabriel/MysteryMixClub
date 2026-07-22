import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { OnboardingRoute } from "./OnboardingRoute";
import { ApiError, acceptTerms } from "../services/api";
import type { UserProfile } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock the API module (no network).
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>(
    "../services/api",
  );
  return {
    ...actual,
    acceptTerms: vi.fn(),
  };
});

// Mock useAuth so we can drive status/profileStatus/needsOnboarding directly.
vi.mock("../hooks/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockAcceptTerms = vi.mocked(acceptTerms);
const mockUseAuth = vi.mocked(useAuth);
const applyDisplayName = vi.fn();
const applyTosAccepted = vi.fn();

type Status = "loading" | "authenticated" | "unauthenticated";
type ProfileStatus = "idle" | "loading" | "ready";

function setAuth(
  status: Status,
  overrides: {
    profileStatus?: ProfileStatus;
    needsOnboarding?: boolean;
    displayName?: string;
    tosAccepted?: boolean;
  } = {},
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
    displayName: overrides.displayName ?? (overrides.needsOnboarding ? "" : "ada"),
    email: status === "authenticated" ? "ada@example.com" : null,
    userId: status === "authenticated" ? "11111111-1111-1111-1111-111111111111" : null,
    isPlatformAdmin: false,
    profileStatus,
    needsOnboarding: overrides.needsOnboarding ?? false,
    applyDisplayName,
    preferredService: null,
    tosAccepted: overrides.tosAccepted ?? true,
    applyTosAccepted,
  });
}

function profileWith(displayName: string): UserProfile {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    display_name: displayName,
    email: "new@example.com",
    preferred_service: null,
    is_platform_admin: false,
    tos_accepted: true,
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

  describe("brand-new user (no display name, no consent)", () => {
    function setBrandNew() {
      setAuth("authenticated", { needsOnboarding: true, displayName: "", tosAccepted: false });
    }

    it("renders the display name field and the consent checkbox", () => {
      setBrandNew();
      renderOnboarding();

      expect(screen.getByText("one more thing")).toBeInTheDocument();
      expect(screen.getByLabelText(/display name/i)).toBeInTheDocument();
      expect(screen.getByRole("checkbox")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /terms of service/i })).toHaveAttribute(
        "href",
        "/terms",
      );
      expect(screen.getByRole("link", { name: /privacy policy/i })).toHaveAttribute(
        "href",
        "/privacy",
      );
      // The shared TopNav is not shown during onboarding.
      expect(screen.queryByRole("button", { name: /^profile$/i })).not.toBeInTheDocument();
    });

    it("keeps submit disabled until both the name is filled and the box is checked", async () => {
      setBrandNew();
      const user = userEvent.setup();
      renderOnboarding();

      const submit = screen.getByRole("button", { name: /continue/i });
      expect(submit).toBeDisabled();

      await user.type(screen.getByLabelText(/display name/i), "Alice");
      expect(submit).toBeDisabled();

      await user.click(screen.getByRole("checkbox"));
      expect(submit).not.toBeDisabled();
    });

    it("submit: trims the name, calls acceptTerms with the name, applies both, navigates home", async () => {
      setBrandNew();
      mockAcceptTerms.mockResolvedValue(profileWith("Alice"));
      const user = userEvent.setup();

      renderOnboarding();

      await user.type(screen.getByLabelText(/display name/i), "  Alice  ");
      await user.click(screen.getByRole("checkbox"));
      await user.click(screen.getByRole("button", { name: /continue/i }));

      expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
      expect(mockAcceptTerms).toHaveBeenCalledTimes(1);
      expect(mockAcceptTerms).toHaveBeenCalledWith("Alice");
      expect(applyDisplayName).toHaveBeenCalledWith("Alice");
      expect(applyTosAccepted).toHaveBeenCalledTimes(1);
    });
  });

  describe("already-onboarded user missing consent only (retroactive gate)", () => {
    function setNeedsConsentOnly() {
      setAuth("authenticated", { needsOnboarding: true, displayName: "ada", tosAccepted: false });
    }

    it("renders only the consent checkbox, no display name field", () => {
      setNeedsConsentOnly();
      renderOnboarding();

      expect(screen.getByText("one more thing before you're back in")).toBeInTheDocument();
      expect(screen.queryByLabelText(/display name/i)).not.toBeInTheDocument();
      expect(screen.getByRole("checkbox")).toBeInTheDocument();
    });

    it("submit: calls acceptTerms with no name, applies consent, navigates home", async () => {
      setNeedsConsentOnly();
      mockAcceptTerms.mockResolvedValue(profileWith("ada"));
      const user = userEvent.setup();

      renderOnboarding();

      const submit = screen.getByRole("button", { name: /continue/i });
      expect(submit).toBeDisabled();

      await user.click(screen.getByRole("checkbox"));
      expect(submit).not.toBeDisabled();
      await user.click(submit);

      expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
      expect(mockAcceptTerms).toHaveBeenCalledTimes(1);
      expect(mockAcceptTerms).toHaveBeenCalledWith(undefined);
      expect(applyTosAccepted).toHaveBeenCalledTimes(1);
    });
  });

  it("submit failure: shows the calm error and stays on the screen", async () => {
    setAuth("authenticated", { needsOnboarding: true, displayName: "", tosAccepted: false });
    mockAcceptTerms.mockRejectedValue(new ApiError(422, "too long"));
    const user = userEvent.setup();

    renderOnboarding();

    await user.type(screen.getByLabelText(/display name/i), "Bob");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "that didn't save. try again.",
    );
    // Still on the onboarding screen — no navigation occurred.
    expect(screen.queryByText("HOME CONTENT")).not.toBeInTheDocument();
    expect(screen.getByText("one more thing")).toBeInTheDocument();
    expect(applyDisplayName).not.toHaveBeenCalled();
    expect(applyTosAccepted).not.toHaveBeenCalled();
  });

  it("guard: unauthenticated redirects to /login (does not render the form)", () => {
    setAuth("unauthenticated");
    renderOnboarding();

    expect(screen.getByText("LOGIN CONTENT")).toBeInTheDocument();
    expect(screen.queryByText("one more thing")).not.toBeInTheDocument();
  });

  it("guard: authenticated, onboarded, and consented redirects to /home", () => {
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
    setAuth("authenticated", { needsOnboarding: true, displayName: "", tosAccepted: false });
    let resolve!: (p: UserProfile) => void;
    mockAcceptTerms.mockReturnValue(
      new Promise<UserProfile>((r) => {
        resolve = r;
      }),
    );
    const user = userEvent.setup();

    renderOnboarding();

    await user.type(screen.getByLabelText(/display name/i), "Cleo");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /saving/i })).toBeDisabled(),
    );

    // Resolve so the trailing navigation flushes inside act().
    resolve(profileWith("Cleo"));
    expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
  });
});
