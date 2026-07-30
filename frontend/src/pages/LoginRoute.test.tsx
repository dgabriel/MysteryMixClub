import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { LoginRoute } from "./LoginRoute";
import {
  ApiError,
  forgotPassword,
  getGoogleEnabled,
  getWaitlistEnabled,
  googleLoginUrl,
  login,
  register,
  requestMagicLink,
} from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock only the API module so no network is touched. ApiError stays real so
// LoginRoute's instanceof-based status mapping works.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ApiError: actual.ApiError,
    PASSWORD_MIN_LENGTH: actual.PASSWORD_MIN_LENGTH,
    PASSWORD_MAX_LENGTH: actual.PASSWORD_MAX_LENGTH,
    requestMagicLink: vi.fn(),
    getWaitlistEnabled: vi.fn(),
    joinWaitlist: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    forgotPassword: vi.fn(),
    googleLoginUrl: vi.fn(),
    getGoogleEnabled: vi.fn(),
  };
});
vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockRequestMagicLink = vi.mocked(requestMagicLink);
const mockGetWaitlistEnabled = vi.mocked(getWaitlistEnabled);
const mockLogin = vi.mocked(login);
const mockRegister = vi.mocked(register);
const mockForgotPassword = vi.mocked(forgotPassword);
const mockGoogleLoginUrl = vi.mocked(googleLoginUrl);
const mockGetGoogleEnabled = vi.mocked(getGoogleEnabled);
const mockUseAuth = vi.mocked(useAuth);
const setAccessToken = vi.fn();

// EmailEntryScreen links to /about (MYS-155), which needs a Router context.
function renderLogin(entry = "/login") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <LoginRoute />
    </MemoryRouter>,
  );
}

/** The password input. */
function passwordInput() {
  return screen.getByLabelText(/^password$/i);
}

/** Surfaces the current query string so URL side effects can be asserted. */
function LocationProbe() {
  return <div data-testid="search">{useLocation().search}</div>;
}

/** Switch to the password tab and return the shared email input. */
async function openPasswordTab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /^password$/i }));
  return screen.getByLabelText(/^email$/i);
}

describe("LoginRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: not signed in, so the form renders.
    mockUseAuth.mockReturnValue({
      status: "unauthenticated",
      setAccessToken,
    } as unknown as ReturnType<typeof useAuth>);
    mockGoogleLoginUrl.mockReturnValue("http://127.0.0.1:8000/api/v1/auth/google/login");
    // Default: Google configured, so the button renders. The unconfigured case
    // is asserted explicitly below.
    mockGetGoogleEnabled.mockResolvedValue({ enabled: true });
    // Default: waitlist off (MYS-215), matching the flag's production-safe
    // default — every existing "email us" assertion in this file relies on
    // this resolving to false.
    mockGetWaitlistEnabled.mockResolvedValue({ enabled: false });
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

    // Waitlist-off check resolves async (MYS-215), so this copy appears a
    // tick after render rather than synchronously.
    await screen.findByText(/no invite yet\?/i);
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
    // address itself stays hidden until clicked (MYS-182). Waitlist-off
    // check resolves async (MYS-215).
    await screen.findByText(/no account yet\?/i);
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

  it("links to the help page (MYS-222)", () => {
    renderLogin();
    expect(screen.getByRole("link", { name: /^help$/i })).toHaveAttribute("href", "/help");
  });

  it("back affordance on CheckEmail returns to the email entry form", async () => {
    mockRequestMagicLink.mockResolvedValue({ devToken: null });
    const user = userEvent.setup();

    renderLogin();

    await user.type(screen.getByLabelText(/email/i), "user@example.com");
    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    await screen.findByText("check your email");
    // The button is conditional on the async waitlist-off check (MYS-215),
    // so wait for it rather than assuming it's already resolved.
    await user.click(await screen.findByRole("button", { name: /use a different email/i }));

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /send sign-in link/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("check your email")).not.toBeInTheDocument();
  });

  it("a stashed invite hides the waitlist block entirely — it's not needed", async () => {
    localStorage.setItem("pendingInvitePath", "/invite/inv-789");
    mockGetWaitlistEnabled.mockResolvedValue({ enabled: true });

    try {
      renderLogin();
      // Something else that resolves on the same async tick, so there's a
      // definite point at which the waitlist check has settled either way.
      await screen.findByRole("button", { name: /send sign-in link/i });

      expect(screen.queryByText(/join the waitlist/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/no invite yet\?/i)).not.toBeInTheDocument();
    } finally {
      localStorage.clear();
    }
  });

  it("a failed login re-shows the waitlist block even with a stashed invite", async () => {
    localStorage.setItem("pendingInvitePath", "/invite/inv-789");
    mockLogin.mockRejectedValue(new ApiError(401, "invalid email or password"));
    const user = userEvent.setup();

    try {
      renderLogin();
      // A stashed invite lands the password tab on register by default —
      // switch back to sign-in, which is the mode a failed login comes from.
      await openPasswordTab(user);
      await user.click(screen.getByRole("button", { name: /back to sign in/i }));
      await user.type(screen.getByLabelText(/^email$/i), "user@example.com");
      await user.type(passwordInput(), "wrong-password");
      await user.click(screen.getByRole("button", { name: /^sign in$/i }));

      await screen.findByText(/no invite yet\?/i);
    } finally {
      localStorage.clear();
    }
  });

  it("waitlist enabled (MYS-215): shows the join-waitlist form instead of email-us copy", async () => {
    mockGetWaitlistEnabled.mockResolvedValue({ enabled: true });
    renderLogin();

    expect(await screen.findByText(/join the waitlist/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^join$/i })).toBeInTheDocument();
    // The old mailto fallback copy/button is gone, not just co-rendered.
    expect(screen.queryByText(/to request one/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^email us$/i })).not.toBeInTheDocument();
  });

  it("waitlist enabled (MYS-215): CheckEmail renders the actual join form, not just a pointer", async () => {
    mockGetWaitlistEnabled.mockResolvedValue({ enabled: true });
    mockRequestMagicLink.mockResolvedValue({ devToken: null });
    const user = userEvent.setup();

    renderLogin();
    await screen.findByText(/join the waitlist/i); // wait out the async flag check

    // Two "email" fields on screen now (sign-in form + waitlist form) — scope
    // to the sign-in form specifically.
    const signInButton = screen.getByRole("button", { name: /send sign-in link/i });
    const signInForm = signInButton.closest("form");
    if (!signInForm) throw new Error("sign-in form not found");
    await user.type(within(signInForm).getByLabelText(/^email$/i), "user@example.com");
    await user.click(signInButton);

    await screen.findByText("check your email");
    // The real form is here now, not just a link back to /login.
    expect(await screen.findByRole("button", { name: /^join$/i })).toBeInTheDocument();
    expect(screen.getByText(/no invite yet\?/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^use a different email$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^email us$/i })).not.toBeInTheDocument();
  });

  // --- password sign-in (ADR 0007) ---------------------------------------- //

  it("password sign-in: happy path stores the returned access token", async () => {
    mockLogin.mockResolvedValue({ access_token: "acc-1" });
    const user = userEvent.setup();

    renderLogin();
    const email = await openPasswordTab(user);

    await user.type(email, "user@example.com");
    await user.type(passwordInput(), "correct-horse");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(mockLogin).toHaveBeenCalledWith("user@example.com", "correct-horse"));
    expect(setAccessToken).toHaveBeenCalledWith("acc-1");
    // Magic link is untouched by the password path.
    expect(mockRequestMagicLink).not.toHaveBeenCalled();
  });

  it("password sign-in: a 401 shows the server's uniform message on the password field", async () => {
    mockLogin.mockRejectedValue(new ApiError(401, "invalid email or password"));
    const user = userEvent.setup();

    renderLogin();
    const email = await openPasswordTab(user);

    // Held onto: once the error renders, the field's accessible name absorbs
    // the inline message, so a /^password$/ lookup would no longer find it.
    const field = passwordInput();
    await user.type(email, "user@example.com");
    await user.type(field, "wrong");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid email or password/i);
    // Field-level invalid state (ADR 0004), not just a loose message.
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(setAccessToken).not.toHaveBeenCalled();
  });

  it("password sign-in: does not submit without a password", async () => {
    const user = userEvent.setup();

    renderLogin();
    const email = await openPasswordTab(user);

    await user.type(email, "user@example.com");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));

    expect(mockLogin).not.toHaveBeenCalled();
  });

  // --- password registration ----------------------------------------------- //

  it("register: passes the stashed invite token and stores the access token", async () => {
    localStorage.setItem("pendingInvitePath", "/invite/inv-789");
    mockRegister.mockResolvedValue({ access_token: "acc-2" });
    const user = userEvent.setup();

    try {
      renderLogin();
      await openPasswordTab(user);

      await user.type(screen.getByLabelText(/^email$/i), "new@example.com");
      await user.type(passwordInput(), "long-enough-pw");
      await user.click(screen.getByRole("button", { name: /^create account$/i }));

      await waitFor(() =>
        expect(mockRegister).toHaveBeenCalledWith("new@example.com", "long-enough-pw", "inv-789"),
      );
      expect(setAccessToken).toHaveBeenCalledWith("acc-2");
    } finally {
      localStorage.clear();
    }
  });

  it("register: with no invite stashed, the affordance is hidden rather than offered as a dead end", async () => {
    const user = userEvent.setup();

    renderLogin();
    await openPasswordTab(user);

    // Register would be guaranteed to fail without an invite, and the waitlist
    // further down the page is the real path, so it isn't offered at all.
    expect(screen.queryByRole("button", { name: /create an account/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^sign in$/i })).toBeInTheDocument();
  });

  it("register: the password tab opens straight on account creation when an invite is stashed", async () => {
    localStorage.setItem("pendingInvitePath", "/invite/inv-789");
    const user = userEvent.setup();

    try {
      renderLogin();
      await openPasswordTab(user);

      // An invited visitor is by definition new.
      expect(screen.getByRole("button", { name: /^create account$/i })).toBeInTheDocument();
      expect(screen.getByText("create account", { selector: "p" })).toBeInTheDocument();
    } finally {
      localStorage.clear();
    }
  });

  it("register: an invite cleared mid-session is caught before any request", async () => {
    localStorage.setItem("pendingInvitePath", "/invite/inv-789");
    const user = userEvent.setup();

    try {
      renderLogin();
      await openPasswordTab(user);
      await user.type(screen.getByLabelText(/^email$/i), "new@example.com");
      await user.type(passwordInput(), "long-enough-pw");

      // e.g. storage cleared in another tab between render and submit.
      localStorage.clear();
      await user.click(screen.getByRole("button", { name: /^create account$/i }));

      expect(mockRegister).not.toHaveBeenCalled();
      expect(await screen.findByRole("alert")).toHaveTextContent(
        /you need an invite to create an account/i,
      );
    } finally {
      localStorage.clear();
    }
  });

  it("register: a short password is caught before any request", async () => {
    localStorage.setItem("pendingInvitePath", "/invite/inv-789");
    const user = userEvent.setup();

    try {
      renderLogin();
      await openPasswordTab(user);

      await user.type(screen.getByLabelText(/^email$/i), "new@example.com");
      await user.type(passwordInput(), "short");
      await user.click(screen.getByRole("button", { name: /^create account$/i }));

      expect(mockRegister).not.toHaveBeenCalled();
      expect(await screen.findByRole("alert")).toHaveTextContent(/at least 8 characters/i);
    } finally {
      localStorage.clear();
    }
  });

  it("register: a 409 surfaces the backend's sign-in-instead message", async () => {
    localStorage.setItem("pendingInvitePath", "/invite/inv-789");
    mockRegister.mockRejectedValue(
      new ApiError(409, "an account already exists for this email — sign in instead"),
    );
    const user = userEvent.setup();

    try {
      renderLogin();
      await openPasswordTab(user);

      await user.type(screen.getByLabelText(/^email$/i), "old@example.com");
      await user.type(passwordInput(), "long-enough-pw");
      await user.click(screen.getByRole("button", { name: /^create account$/i }));

      expect(await screen.findByRole("alert")).toHaveTextContent(/sign in instead/i);
      expect(setAccessToken).not.toHaveBeenCalled();
    } finally {
      localStorage.clear();
    }
  });

  // --- forgot password ------------------------------------------------------ //

  it("forgot password: shows a neutral notice and, in dev, a reset link", async () => {
    mockForgotPassword.mockResolvedValue({ devToken: "reset-tok" });
    const user = userEvent.setup();

    renderLogin();
    await openPasswordTab(user);
    await user.click(screen.getByRole("button", { name: /forgot your password\?/i }));

    // The password field is gone — this step only needs the address.
    expect(screen.queryByLabelText(/^password$/i)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(/^email$/i), "user@example.com");
    await user.click(screen.getByRole("button", { name: /email a reset link/i }));

    await waitFor(() => expect(mockForgotPassword).toHaveBeenCalledWith("user@example.com"));
    // Never phrased as "sent" — a 200 says nothing about the address.
    expect(await screen.findByText(/if that email has a password set/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /set a new password with this link/i })).toHaveAttribute(
      "href",
      "/auth/reset-password?token=reset-tok",
    );
  });

  // --- google (ADR 0007) ---------------------------------------------------- //

  it("google: renders a real link to the redirect endpoint, carrying any stashed invite", async () => {
    localStorage.setItem("pendingInvitePath", "/invite/inv-789");
    mockGoogleLoginUrl.mockReturnValue("http://api.test/api/v1/auth/google/login?invite_token=inv-789");

    try {
      renderLogin();

      expect(mockGoogleLoginUrl).toHaveBeenCalledWith("inv-789");
      expect(await screen.findByRole("link", { name: /sign in with google/i })).toHaveAttribute(
        "href",
        "http://api.test/api/v1/auth/google/login?invite_token=inv-789",
      );
    } finally {
      localStorage.clear();
    }
  });

  it("google: no button at all when the deployment has no Google credentials", async () => {
    mockGetGoogleEnabled.mockResolvedValue({ enabled: false });
    renderLogin();

    // Wait out the async flag check via a sibling that resolves on the same tick.
    await screen.findByText(/no invite yet\?/i);
    expect(screen.queryByRole("link", { name: /sign in with google/i })).not.toBeInTheDocument();
  });

  it("google: a failed enabled-check hides the button too (fail-safe)", async () => {
    mockGetGoogleEnabled.mockRejectedValue(new Error("network down"));
    renderLogin();

    await screen.findByText(/no invite yet\?/i);
    expect(screen.queryByRole("link", { name: /sign in with google/i })).not.toBeInTheDocument();
  });

  it("google: ?google=ok shows no error and still falls through to the authenticated redirect", () => {
    mockUseAuth.mockReturnValue({
      status: "authenticated",
      setAccessToken,
    } as unknown as ReturnType<typeof useAuth>);
    render(
      <MemoryRouter initialEntries={["/login?google=ok"]}>
        <Routes>
          <Route path="/login" element={<LoginRoute />} />
          <Route path="/home" element={<div>HOME</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("HOME")).toBeInTheDocument();
  });

  it("google: ?google=ok on an unresolved session shows the form with no error copy", () => {
    renderLogin("/login?google=ok");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send sign-in link/i })).toBeInTheDocument();
  });

  it("google: ?google=invite_required reuses the same copy as the other sign-up paths", () => {
    renderLogin("/login?google=invite_required");
    expect(screen.getByRole("alert")).toHaveTextContent(
      /you need an invite to create an account/i,
    );
  });

  it("google: ?google=denied and an unknown outcome each get calm copy", () => {
    const { unmount } = renderLogin("/login?google=denied");
    expect(screen.getByRole("alert")).toHaveTextContent(/google sign-in was cancelled/i);
    unmount();

    renderLogin("/login?google=something_new");
    expect(screen.getByRole("alert")).toHaveTextContent(/that sign-in didn't work/i);
  });

  it("google: the outcome param is stripped from the URL once read, but the copy stays", async () => {
    render(
      <MemoryRouter initialEntries={["/login?google=denied"]}>
        <LocationProbe />
        <LoginRoute />
      </MemoryRouter>,
    );

    // Shown to the user...
    expect(screen.getByRole("alert")).toHaveTextContent(/google sign-in was cancelled/i);
    // ...but gone from the URL, so a reload or bookmark can't resurface it.
    await waitFor(() => expect(screen.getByTestId("search")).toHaveTextContent(""));
  });

  it("google: outcome messages are plain Ink, while the same words from a form submit are Rust", async () => {
    localStorage.setItem("pendingInvitePath", "/invite/inv-789");
    mockRegister.mockRejectedValue(
      new ApiError(403, "you need an invite to create an account"),
    );
    const user = userEvent.setup();

    try {
      // Same sentence, arriving from Google's redirect: an external system's
      // outcome, so it stays Ink.
      const { unmount } = renderLogin("/login?google=invite_required");
      expect(screen.getByRole("alert")).toHaveClass("text-ink");
      expect(screen.getByRole("alert")).not.toHaveClass("text-rust");
      unmount();

      // Same sentence, from the user's own register submission: a claim about
      // their attempt, so it gets the Rust validation treatment.
      renderLogin();
      await openPasswordTab(user);
      await user.type(screen.getByLabelText(/^email$/i), "new@example.com");
      await user.type(passwordInput(), "long-enough-pw");
      await user.click(screen.getByRole("button", { name: /^create account$/i }));

      expect(await screen.findByRole("alert")).toHaveClass("text-rust");
    } finally {
      localStorage.clear();
    }
  });

  it("google: the outcome error clears on a mode switch rather than stacking", async () => {
    const user = userEvent.setup();
    renderLogin("/login?google=denied");
    expect(screen.getByRole("alert")).toHaveTextContent(/google sign-in was cancelled/i);

    await openPasswordTab(user);

    expect(screen.queryByText(/google sign-in was cancelled/i)).not.toBeInTheDocument();
  });

  // --- form semantics and validation ---------------------------------------- //

  it("the method switcher is a labelled group of pressed-state buttons, not ARIA tabs", async () => {
    const user = userEvent.setup();
    renderLogin();

    // Not role="tab": that would promise arrow-key navigation this doesn't have.
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: /sign-in method/i })).toBeInTheDocument();

    // Anchored: "send sign-in link" (the submit button) also contains this text.
    const magicButton = screen.getByRole("button", { name: /^sign-in link$/i });
    expect(magicButton).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /^password$/i })).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    await openPasswordTab(user);
    expect(screen.getByRole("button", { name: /^password$/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("re-clicking the already-active password button preserves a half-typed password", async () => {
    const user = userEvent.setup();
    renderLogin();

    await openPasswordTab(user);
    await user.type(passwordInput(), "half-typed");

    await user.click(screen.getByRole("button", { name: /^password$/i }));

    expect(passwordInput()).toHaveValue("half-typed");
  });

  it("re-clicking it preserves the password with an invite stashed too, from either sub-mode", async () => {
    localStorage.setItem("pendingInvitePath", "/invite/inv-789");
    const user = userEvent.setup();

    try {
      renderLogin();
      // An invite means the button opens on register, so a naive
      // register-or-signin target would force-switch out of signin and wipe the
      // field. Walk to signin first, which is where that bug lived.
      await openPasswordTab(user);
      await user.click(screen.getByRole("button", { name: /back to sign in/i }));
      await user.type(passwordInput(), "half-typed");

      await user.click(screen.getByRole("button", { name: /^password$/i }));

      expect(passwordInput()).toHaveValue("half-typed");
      // Still on sign-in, not bounced back to account creation.
      expect(screen.getByRole("button", { name: /^sign in$/i })).toBeInTheDocument();

      // And in register mode the same click is equally inert.
      await user.click(screen.getByRole("button", { name: /create an account/i }));
      await user.type(passwordInput(), "typed-again");
      await user.click(screen.getByRole("button", { name: /^password$/i }));
      expect(passwordInput()).toHaveValue("typed-again");
    } finally {
      localStorage.clear();
    }
  });

  it("moves focus to the field the new mode expects after a mode swap", async () => {
    const user = userEvent.setup();
    renderLogin();

    // magic → signin with email still empty: land on email, not past it —
    // tabbing forward should reach password without a shift-tab back.
    const email = await openPasswordTab(user);
    expect(email).toHaveFocus();

    await user.type(email, "user@example.com");

    // signin → forgot: no password field there, so the address is next.
    await user.click(screen.getByRole("button", { name: /forgot your password\?/i }));
    expect(screen.getByLabelText(/^email$/i)).toHaveFocus();

    // forgot → signin with email already filled: password is next.
    await user.click(screen.getByRole("button", { name: /back to sign in/i }));
    expect(passwordInput()).toHaveFocus();
  });

  it("does not steal focus on arrival", () => {
    renderLogin();
    expect(screen.getByLabelText(/^email$/i)).not.toHaveFocus();
  });

  it("empty email: shows a field error and focuses the field instead of doing nothing", async () => {
    const user = userEvent.setup();
    renderLogin();

    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    expect(mockRequestMagicLink).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(/enter your email/i);
    expect(screen.getByLabelText(/^email/i)).toHaveFocus();
  });

  it("empty password: shows a field error and focuses the field", async () => {
    const user = userEvent.setup();
    renderLogin();

    const email = await openPasswordTab(user);
    await user.type(email, "user@example.com");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));

    expect(mockLogin).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(/enter your password/i);
    expect(passwordInput()).toHaveFocus();
  });

  it("the password can be revealed to check what was typed", async () => {
    const user = userEvent.setup();
    renderLogin();

    await openPasswordTab(user);
    expect(passwordInput()).toHaveAttribute("type", "password");

    await user.click(screen.getByRole("button", { name: /show password/i }));
    expect(passwordInput()).toHaveAttribute("type", "text");
  });
});
