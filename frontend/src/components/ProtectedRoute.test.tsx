import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ProtectedRoute } from "./ProtectedRoute";
import { useAuth } from "../hooks/useAuth";

vi.mock("../hooks/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockUseAuth = vi.mocked(useAuth);

type Status = "loading" | "authenticated" | "unauthenticated";
type ProfileStatus = "idle" | "loading" | "ready";

function setStatus(
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
    displayName: status === "authenticated" ? "ada" : null,
    profileStatus,
    needsOnboarding: overrides.needsOnboarding ?? false,
    applyDisplayName: vi.fn(),
  });
}

function renderProtected() {
  return render(
    <MemoryRouter initialEntries={["/home"]}>
      <Routes>
        <Route
          path="/home"
          element={
            <ProtectedRoute>
              <div>PROTECTED CHILD</div>
            </ProtectedRoute>
          }
        />
        <Route path="/login" element={<div>LOGIN CONTENT</div>} />
        <Route path="/onboarding" element={<div>ONBOARDING CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProtectedRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loading: renders the verifying loader, not the child and not a redirect", () => {
    setStatus("loading");
    renderProtected();

    expect(screen.getByText(/verifying/i)).toBeInTheDocument();
    expect(screen.queryByText("PROTECTED CHILD")).not.toBeInTheDocument();
    expect(screen.queryByText("LOGIN CONTENT")).not.toBeInTheDocument();
  });

  it("unauthenticated: redirects to /login", () => {
    setStatus("unauthenticated");
    renderProtected();

    expect(screen.getByText("LOGIN CONTENT")).toBeInTheDocument();
    expect(screen.queryByText("PROTECTED CHILD")).not.toBeInTheDocument();
  });

  it("authenticated: renders the protected child", () => {
    setStatus("authenticated");
    renderProtected();

    expect(screen.getByText("PROTECTED CHILD")).toBeInTheDocument();
    expect(screen.queryByText("LOGIN CONTENT")).not.toBeInTheDocument();
  });

  it("authenticated + profile ready + needsOnboarding false: renders the child", () => {
    setStatus("authenticated", { profileStatus: "ready", needsOnboarding: false });
    renderProtected();

    expect(screen.getByText("PROTECTED CHILD")).toBeInTheDocument();
    expect(screen.queryByText("ONBOARDING CONTENT")).not.toBeInTheDocument();
    expect(screen.queryByText("LOGIN CONTENT")).not.toBeInTheDocument();
  });

  it("authenticated + profile loading: renders the loading motif, not the child, no redirect", () => {
    setStatus("authenticated", { profileStatus: "loading" });
    renderProtected();

    expect(screen.getByText(/verifying/i)).toBeInTheDocument();
    expect(screen.queryByText("PROTECTED CHILD")).not.toBeInTheDocument();
    expect(screen.queryByText("ONBOARDING CONTENT")).not.toBeInTheDocument();
    expect(screen.queryByText("LOGIN CONTENT")).not.toBeInTheDocument();
  });

  it("authenticated + needsOnboarding true: redirects to /onboarding", () => {
    setStatus("authenticated", { profileStatus: "ready", needsOnboarding: true });
    renderProtected();

    expect(screen.getByText("ONBOARDING CONTENT")).toBeInTheDocument();
    expect(screen.queryByText("PROTECTED CHILD")).not.toBeInTheDocument();
    expect(screen.queryByText("LOGIN CONTENT")).not.toBeInTheDocument();
  });
});
