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

// EmailEntryScreen links to /about (MYS-155), which needs a Router context.
function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <LoginRoute />
    </MemoryRouter>,
  );
}

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

  it("shows invite-required contact info upfront, before any submission — email revealed only on click", async () => {
    const user = userEvent.setup();
    renderLogin();

    expect(screen.getByText(/no invite yet\?/i)).toBeInTheDocument();
    // The address itself isn't in the DOM until clicked (MYS-182: keeps it
    // out of reach of scrapers that don't simulate interaction).
    expect(screen.queryByText(/info@mysterymixclub\.com/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^email us$/i }));

    expect(screen.getByRole("link", { name: /info@mysterymixclub\.com/i })).toHaveAttribute(
      "href",
      "mailto:info@mysterymixclub.com",
    );
  });

  it("no TopNav on the login screen (unauthenticated)", () => {
    renderLogin();

    // The shared nav is authed-only; none of its links appear here.
    expect(screen.queryByRole("button", { name: /^profile$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^logout$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^home$/i })).not.toBeInTheDocument();
  });

  it("happy path: submits a trimmed email and shows CheckEmail with that email", async () => {
    mockRequestMagicLink.mockResolvedValue({ devToken: null });
    const user = userEvent.setup();

    renderLogin();

    // EmailEntry visible
    expect(
      screen.getByRole("button", { name: /send sign-in link/i }),
    ).toBeInTheDocument();

    const input = screen.getByLabelText(/email/i);
    // Leading/trailing whitespace should be trimmed by the screen before submit.
    await user.type(input, "  Friend@Example.com  ");
    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    expect(mockRequestMagicLink).toHaveBeenCalledTimes(1);
    // No pending invite stashed → the invite token is null (ordinary sign-in).
    expect(mockRequestMagicLink).toHaveBeenCalledWith("Friend@Example.com", null);

    // CheckEmail screen now shown with the submitted email.
    expect(await screen.findByText("check your email")).toBeInTheDocument();
    expect(screen.getByText("Friend@Example.com")).toBeInTheDocument();
    // Same neutral response either way (registered or not) — the invite
    // contact note is shown unconditionally so it never reveals which. The
    // address itself stays hidden until clicked (MYS-182).
    expect(screen.getByText(/new here\?/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^email us$/i }));
    expect(screen.getByRole("link", { name: /info@mysterymixclub\.com/i })).toHaveAttribute(
      "href",
      "mailto:info@mysterymixclub.com",
    );
  });

  it("error path: when requestMagicLink rejects, shows an error and does NOT show CheckEmail", async () => {
    mockRequestMagicLink.mockRejectedValue(new Error("rate limited"));
    const user = userEvent.setup();

    renderLogin();

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

    renderLogin();

    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    expect(mockRequestMagicLink).not.toHaveBeenCalled();
    expect(screen.queryByText("check your email")).not.toBeInTheDocument();
  });

  it("edge case: whitespace-only input does not submit", async () => {
    const user = userEvent.setup();

    renderLogin();

    await user.type(screen.getByLabelText(/email/i), "    ");
    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    expect(mockRequestMagicLink).not.toHaveBeenCalled();
    expect(screen.queryByText("check your email")).not.toBeInTheDocument();
  });

  it("dev/staging: when a dev token is returned, shows a relative sign-in link and NOT CheckEmail", async () => {
    mockRequestMagicLink.mockResolvedValue({ devToken: "tok-123" });
    const user = userEvent.setup();

    renderLogin();

    await user.type(screen.getByLabelText(/email/i), "user@example.com");
    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    const link = await screen.findByRole("link", { name: /sign in with this link/i });
    expect(link).toHaveAttribute("href", "/auth/verify?token=tok-123");
    // The "check your email" screen is not shown when the dev link is available.
    expect(screen.queryByText("check your email")).not.toBeInTheDocument();
  });

  it("invite flow: a stashed pending invite is passed to requestMagicLink and appended to the dev link", async () => {
    localStorage.setItem("pendingInvitePath", "/invite/inv-789");
    mockRequestMagicLink.mockResolvedValue({ devToken: "tok-123" });
    const user = userEvent.setup();

    try {
      renderLogin();

      await user.type(screen.getByLabelText(/email/i), "guest@example.com");
      await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

      expect(mockRequestMagicLink).toHaveBeenCalledWith("guest@example.com", "inv-789");
      const link = await screen.findByRole("link", { name: /sign in with this link/i });
      expect(link).toHaveAttribute("href", "/auth/verify?token=tok-123&invite=inv-789");
    } finally {
      localStorage.clear();
    }
  });

  it("links to the about page (MYS-155)", () => {
    renderLogin();
    expect(screen.getByRole("link", { name: /about mysterymixclub/i })).toHaveAttribute(
      "href",
      "/about",
    );
  });

  it("back affordance on CheckEmail returns to the email entry form", async () => {
    mockRequestMagicLink.mockResolvedValue({ devToken: null });
    const user = userEvent.setup();

    renderLogin();

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
