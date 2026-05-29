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

function setStatus(status: Status) {
  mockUseAuth.mockReturnValue({
    status,
    isAuthenticated: status === "authenticated",
    setAccessToken: vi.fn(),
    clear: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
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
});
