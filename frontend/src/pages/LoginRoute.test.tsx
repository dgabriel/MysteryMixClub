import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { LoginRoute } from "./LoginRoute";
import { requestMagicLink } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock only the API module so no network is touched.
vi.mock("../services/api", () => ({
  requestMagicLink: vi.fn(),
}));
vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockRequestMagicLink = vi.mocked(requestMagicLink);
const mockUseAuth = vi.mocked(useAuth);

describe("LoginRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: not signed in, so the form renders.
    mockUseAuth.mockReturnValue({ status: "unauthenticated" } as ReturnType<typeof useAuth>);
  });

  it("redirects an already-authenticated user to /home", () => {
    mockUseAuth.mockReturnValue({ status: "authenticated" } as ReturnType<typeof useAuth>);
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginRoute />} />
          <Route path="/home" element={<div>HOME</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("HOME")).toBeInTheDocument();
  });

  it("happy path: submits a trimmed email and shows CheckEmail with that email", async () => {
    mockRequestMagicLink.mockResolvedValue({ devToken: null });
    const user = userEvent.setup();

    render(<LoginRoute />);

    // EmailEntry visible
    expect(
      screen.getByRole("button", { name: /send sign-in link/i }),
    ).toBeInTheDocument();

    const input = screen.getByLabelText(/email/i);
    // Leading/trailing whitespace should be trimmed by the screen before submit.
    await user.type(input, "  Friend@Example.com  ");
    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    expect(mockRequestMagicLink).toHaveBeenCalledTimes(1);
    expect(mockRequestMagicLink).toHaveBeenCalledWith("Friend@Example.com");

    // CheckEmail screen now shown with the submitted email.
    expect(await screen.findByText("check your email")).toBeInTheDocument();
    expect(screen.getByText("Friend@Example.com")).toBeInTheDocument();
  });

  it("error path: when requestMagicLink rejects, shows an error and does NOT show CheckEmail", async () => {
    mockRequestMagicLink.mockRejectedValue(new Error("rate limited"));
    const user = userEvent.setup();

    render(<LoginRoute />);

    await user.type(screen.getByLabelText(/email/i), "user@example.com");
    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    // Error alert is shown.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/that didn.?t work/i);

    // CheckEmail is NOT shown.
    expect(screen.queryByText("check your email")).not.toBeInTheDocument();
    // Still on the email entry form.
    expect(
      screen.getByRole("button", { name: /send sign-in link/i }),
    ).toBeInTheDocument();
  });

  it("edge case: empty input does not call requestMagicLink and stays on the form", async () => {
    const user = userEvent.setup();

    render(<LoginRoute />);

    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    expect(mockRequestMagicLink).not.toHaveBeenCalled();
    expect(screen.queryByText("check your email")).not.toBeInTheDocument();
  });

  it("edge case: whitespace-only input does not submit", async () => {
    const user = userEvent.setup();

    render(<LoginRoute />);

    await user.type(screen.getByLabelText(/email/i), "    ");
    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    expect(mockRequestMagicLink).not.toHaveBeenCalled();
    expect(screen.queryByText("check your email")).not.toBeInTheDocument();
  });

  it("dev/staging: when a dev token is returned, shows a relative sign-in link and NOT CheckEmail", async () => {
    mockRequestMagicLink.mockResolvedValue({ devToken: "tok-123" });
    const user = userEvent.setup();

    render(<LoginRoute />);

    await user.type(screen.getByLabelText(/email/i), "user@example.com");
    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    const link = await screen.findByRole("link", { name: /sign in with this link/i });
    expect(link).toHaveAttribute("href", "/auth/verify?token=tok-123");
    // The "check your email" screen is not shown when the dev link is available.
    expect(screen.queryByText("check your email")).not.toBeInTheDocument();
  });

  it("back affordance on CheckEmail returns to the email entry form", async () => {
    mockRequestMagicLink.mockResolvedValue({ devToken: null });
    const user = userEvent.setup();

    render(<LoginRoute />);

    await user.type(screen.getByLabelText(/email/i), "user@example.com");
    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    await screen.findByText("check your email");
    await user.click(screen.getByRole("button", { name: /use a different email/i }));

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /send sign-in link/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("check your email")).not.toBeInTheDocument();
  });
});
