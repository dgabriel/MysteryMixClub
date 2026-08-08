import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { ContactEmail } from "../components/ContactEmail";
import { FormError } from "../components/FormError";
import { GoogleSignInButton } from "../components/GoogleSignInButton";
import { TextField } from "../components/TextField";
import { ConcentricRings } from "../components/ConcentricRings";
import { WaitlistForm } from "../components/WaitlistForm";
import { PASSWORD_MIN_LENGTH, getGoogleEnabled, getWaitlistEnabled } from "../services/api";

/** Which of the three sign-in methods (ADR 0007) the form is showing. The
 *  password method has three states of its own; "signin" is the one the
 *  password tab lands on, unless a pending invite makes "register" the
 *  likelier intent. */
export type LoginMode = "magic" | "signin" | "register" | "forgot";

const SCREEN_ERROR_ID = "login-form-error";

type EmailEntryScreenProps = {
  onSubmit: (email: string) => void;
  submitting: boolean;
  error?: string | null;
  /** Dev/staging only: a relative sign-in link to show below the button. */
  devLink?: string | null;
  mode: LoginMode;
  onModeChange: (mode: LoginMode) => void;
  onPasswordSignIn: (email: string, password: string) => void;
  onRegister: (email: string, password: string) => void;
  onForgotPassword: (email: string) => void;
  /** Whether account creation is reachable at all — true only when a pending
   *  invite token is stashed. Without one, register is guaranteed to fail, so
   *  the affordance is hidden rather than offered as a dead end. */
  canRegister: boolean;
  /** Field-level validation message for the password input — renders in
   *  `destructive-text` with a warning icon (ADR 0004). Form errors are their
   *  own color category and consume nothing from the screen's amber. */
  passwordError?: string | null;
  /** Outcome of a failed Google round-trip (`?google=<outcome>`). Rendered as
   *  plain `foreground` body copy, NOT `destructive-text`: the error color is
   *  reserved for messages that make a claim about the user's own attempt (a
   *  field error, an invite rejection, a rate limit), not for a third party's
   *  outcome. Kept separate from `error` because the two share wording in places
   *  (invite_required, at_capacity, club_full) and the split is by source, not
   *  by text. */
  googleError?: string | null;
  /** Neutral confirmation after a reset request. Says nothing about whether the
   *  address is registered, so it is never phrased as "sent". */
  resetNotice?: string | null;
  /** Dev/staging only: a relative reset link in place of the emailed one. */
  resetDevLink?: string | null;
  googleUrl: string;
};

/** Dev/staging convenience: a clickable link so testers don't need a delivered
 *  email. The eyebrow above it is a mono label; the link itself is an action, so
 *  it takes `accent` — amber is a category rule now, not a per-screen budget,
 *  and a sign-in link is squarely in the action category. The URL sits in mono
 *  at normal tracking, which is the treatment for a value rather than a label. */
function DevLink({ href, label }: { href: string; label: string }) {
  return (
    <div className="mt-8 border-t border-hairline pt-6">
      <p className="font-mono uppercase tracking-mono-wide text-mini text-muted-foreground">
        dev · staging only
      </p>
      <a
        href={href}
        className="mt-3 inline-block font-mono text-xs text-accent underline underline-offset-[3px] break-all"
      >
        {label}
      </a>
    </div>
  );
}

/** Secondary action inside the form. Now the shared Button's "link" variant:
 *  under the old system this was hand-rolled specifically to avoid Rust, but
 *  amber marks action or achievement rather than being rationed one-per-screen,
 *  and every one of these is an action. `py-2` is kept as a passthrough so the
 *  touch target does not shrink to the cap height of `text-label`. */
function InlineAction({ onClick, children }: { onClick: () => void; children: string }) {
  return (
    <Button variant="link" type="button" onClick={onClick} className="py-2">
      {children}
    </Button>
  );
}

export function EmailEntryScreen({
  onSubmit,
  submitting,
  error,
  devLink,
  mode,
  onModeChange,
  onPasswordSignIn,
  onRegister,
  onForgotPassword,
  canRegister,
  passwordError,
  googleError,
  resetNotice,
  resetDevLink,
  googleUrl,
}: EmailEntryScreenProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  // Empty-field messages this screen raises itself, before any request. Kept
  // apart from the parent's server-driven errors and shown in preference to
  // them, so clearing a field never leaves a stale message contradicting it.
  const [emailRequired, setEmailRequired] = useState<string | null>(null);
  const [passwordRequired, setPasswordRequired] = useState<string | null>(null);
  // undefined = still checking (renders neither form nor fallback copy, to
  // avoid a flash of the wrong one), null = disabled or the check failed —
  // both fall back to today's "email us" copy (fail-safe, MYS-215).
  const [waitlistEnabled, setWaitlistEnabled] = useState<boolean | null | undefined>(undefined);
  // Same tri-state, same fail-safe reasoning: an unconfigured deployment (local
  // dev, and production until credentials land) must render no Google button at
  // all rather than one that 404s on click.
  const [googleEnabled, setGoogleEnabled] = useState<boolean | null | undefined>(undefined);
  // The address a reset was last requested for, so the submit button can be
  // disabled for that exact address without trapping someone who mistyped it.
  const [resetRequestedFor, setResetRequestedFor] = useState<string | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const prevMode = useRef<LoginMode | null>(null);

  useEffect(() => {
    let active = true;
    getWaitlistEnabled()
      .then((r) => {
        if (active) setWaitlistEnabled(r.enabled);
      })
      .catch(() => {
        if (active) setWaitlistEnabled(null);
      });
    getGoogleEnabled()
      .then((r) => {
        if (active) setGoogleEnabled(r.enabled);
      })
      .catch(() => {
        if (active) setGoogleEnabled(null);
      });
    return () => {
      active = false;
    };
  }, []);

  const showsPassword = mode === "signin" || mode === "register";

  // React remounts fields across a mode swap, dropping focus to <body>. Put it
  // on whichever field the new mode expects next. Comparing against the previous
  // mode (rather than a "did mount" flag) means StrictMode's double-invoke can't
  // make this steal focus on arrival at /login.
  useEffect(() => {
    if (prevMode.current !== null && prevMode.current !== mode) {
      // Only skip ahead to the password field once the email above it is
      // already filled — otherwise land there first, so tabbing forward
      // reaches password without needing to shift-tab back for email.
      const target =
        showsPassword && email.trim() ? passwordRef.current : emailRef.current;
      target?.focus();
    }
    prevMode.current = mode;
  }, [mode, showsPassword, email]);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setEmailRequired(null);
    setPasswordRequired(null);

    const trimmed = email.trim();
    if (!trimmed) {
      setEmailRequired("enter your email.");
      emailRef.current?.focus();
      return;
    }
    if (showsPassword && !password) {
      setPasswordRequired("enter your password.");
      passwordRef.current?.focus();
      return;
    }

    if (mode === "magic") onSubmit(trimmed);
    else if (mode === "forgot") {
      setResetRequestedFor(trimmed);
      onForgotPassword(trimmed);
    } else if (mode === "signin") onPasswordSignIn(trimmed, password);
    else onRegister(trimmed, password);
  }

  function switchMode(next: LoginMode) {
    // Re-clicking the active tab is a no-op, not a reset — it must not wipe a
    // password the user is midway through typing.
    if (next === mode) return;
    setPassword("");
    setEmailRequired(null);
    setPasswordRequired(null);
    setResetRequestedFor(null);
    onModeChange(next);
  }

  const onPasswordTab = mode !== "magic";
  // The reset request is neutral and idempotent, so re-sending for the same
  // address accomplishes nothing. Scoped to that address so correcting a typo
  // still re-enables the button.
  const resetAlreadySent =
    mode === "forgot" && Boolean(resetNotice) && resetRequestedFor === email.trim();
  // The submit button's caption is not enough on its own to tell four form
  // states apart, and the tab still reads "password" during a reset.
  const eyebrow =
    mode === "register" ? "create account" : mode === "forgot" ? "reset password" : null;
  const submitLabel = {
    magic: submitting ? "sending…" : "send sign-in link",
    signin: submitting ? "signing in…" : "sign in",
    register: submitting ? "creating…" : "create account",
    forgot: submitting ? "sending…" : "email a reset link",
  }[mode];

  // Mono button type. The selected method carries an `accent` underline — the
  // iconography rule's "accent for selected" — while both labels stay on the
  // foreground ramp, so the amber marks the choice rather than the words.
  const tabClass = (active: boolean) =>
    [
      "-mb-px flex-1 border-b-2 py-3 font-mono uppercase tracking-mono-caps text-label transition-colors duration-150",
      active
        ? "border-accent text-foreground"
        : "border-transparent text-muted-foreground hover:text-foreground",
    ].join(" ");

  // Footer chrome, matching TopNav's link treatment: mono label at
  // `muted-foreground`, resolving to `foreground` on hover.
  const footerLinkClass =
    "py-1 font-mono uppercase tracking-mono text-label text-muted-foreground transition-colors duration-150 hover:text-foreground";

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 sm:px-8">
      <div className="w-full max-w-sm">
        {/* The disc, unaccented. Amber-as-identity is bounded to the shared
            nav's mark plus at most one hero mark per screen, and this screen is
            not one of the ones that carries the hero mark (ADR 0010). */}
        <ConcentricRings size={72} className="mx-auto" />

        <h1 className="mt-8 flex items-center justify-center gap-3 text-center font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
          mysterymixclub
          <Badge>beta</Badge>
        </h1>
        <p className="mt-2 text-center text-sm leading-[1.72] text-muted-foreground">
          invite-only. sign in with your email.
        </p>

        {/* What happened on the way back from Google, as plain `foreground` body
            copy — it reports an external system's outcome rather than judging
            anything the user typed, so it is not a form error (ADR 0004). */}
        {googleError ? (
          <p role="alert" className="mt-6 text-center text-sm leading-[1.72] text-foreground">
            {googleError}
          </p>
        ) : null}

        {/* Deliberately not role="tablist"/"tab": that sets a WAI-ARIA APG
            expectation of arrow-key navigation with a roving tabIndex, which
            this doesn't implement. A labelled group of pressed-state buttons
            promises only what it delivers. */}
        <div
          role="group"
          aria-label="sign-in method"
          className="mt-10 flex border-b border-hairline"
        >
          <button
            type="button"
            aria-pressed={!onPasswordTab}
            onClick={() => switchMode("magic")}
            className={tabClass(!onPasswordTab)}
          >
            sign-in link
          </button>
          <button
            type="button"
            aria-pressed={onPasswordTab}
            // The register/signin default applies only when entering password
            // mode from magic. Already inside a password sub-mode, the target is
            // the current mode, so switchMode's same-mode guard fires and a
            // half-typed password survives a stray click on the active button.
            onClick={() => switchMode(mode === "magic" ? (canRegister ? "register" : "signin") : mode)}
            className={tabClass(onPasswordTab)}
          >
            password
          </button>
        </div>

        <form onSubmit={handleSubmit} noValidate className="mt-6 space-y-8">
          {eyebrow ? (
            <p className="font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
              {eyebrow}
            </p>
          ) : null}

          <TextField
            id="email"
            label="email"
            type="email"
            name="email"
            inputRef={emailRef}
            // In a password mode this is half of a credential pair, so password
            // managers need "username" to store and fill them together.
            autoComplete={showsPassword ? "username" : "email"}
            inputMode="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setEmailRequired(null);
            }}
            disabled={submitting}
            error={emailRequired}
            // Only magic link's own error is about the address; every other
            // screen-level message belongs to the form, not this field.
            invalid={mode === "magic" && Boolean(error)}
            aria-describedby={mode === "magic" && error ? SCREEN_ERROR_ID : undefined}
          />

          {showsPassword ? (
            <div>
              <TextField
                id="password"
                label="password"
                type="password"
                name="password"
                inputRef={passwordRef}
                revealToggle
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setPasswordRequired(null);
                }}
                disabled={submitting}
                error={passwordRequired ?? passwordError}
              />
              {mode === "register" && !(passwordRequired ?? passwordError) ? (
                <p className="mt-2 text-meta leading-[1.6] text-muted-foreground">
                  {PASSWORD_MIN_LENGTH} characters or more.
                </p>
              ) : null}
            </div>
          ) : null}

          {error ? <FormError id={SCREEN_ERROR_ID}>{error}</FormError> : null}

          {resetNotice ? (
            <p role="status" className="text-sm leading-[1.72] text-foreground">
              {resetNotice}
            </p>
          ) : null}

          <Button type="submit" disabled={submitting || resetAlreadySent} className="w-full">
            {submitLabel}
          </Button>
        </form>

        {onPasswordTab ? (
          <div className="mt-4 flex flex-wrap justify-center gap-4">
            {mode === "signin" ? (
              <>
                <InlineAction onClick={() => switchMode("forgot")}>
                  forgot your password?
                </InlineAction>
                {/* Hidden without an invite: registration would be a guaranteed
                    dead end, and the waitlist below is the real path. */}
                {canRegister ? (
                  <InlineAction onClick={() => switchMode("register")}>
                    create an account
                  </InlineAction>
                ) : null}
              </>
            ) : (
              <InlineAction onClick={() => switchMode("signin")}>back to sign in</InlineAction>
            )}
          </div>
        ) : null}

        {devLink && mode === "magic" ? (
          <DevLink href={devLink} label="sign in with this link" />
        ) : null}
        {resetDevLink && mode === "forgot" ? (
          <DevLink href={resetDevLink} label="set a new password with this link" />
        ) : null}

        {googleEnabled ? (
          <>
            <div className="mt-12 flex items-center gap-4">
              <span className="h-px flex-1 bg-hairline" />
              <span className="font-mono uppercase tracking-mono-wide text-mini text-muted-foreground">
                or
              </span>
              <span className="h-px flex-1 bg-hairline" />
            </div>
            <div className="mt-6">
              <GoogleSignInButton href={googleUrl} />
            </div>
          </>
        ) : null}

        {/* Below the sign-in form, not above it (MYS-215) — this is the
            secondary path for someone without an account yet, not the
            primary action on the page. A visitor who already has a working
            invite (canRegister) has no use for it — unless something they
            just tried actually failed (a screen-level error, or a wrong
            password), in which case it's a reasonable fallback regardless of
            invite status. */}
        {!canRegister || Boolean(error) || Boolean(passwordError) ? (
          waitlistEnabled ? (
            <WaitlistForm />
          ) : waitlistEnabled === undefined ? null : (
            <p className="mt-12 text-center text-sm leading-[1.72] text-muted-foreground">
              no invite yet?{" "}
              <ContactEmail
                user="info"
                domain="mysterymixclub.com"
                label="email us"
                className="text-accent underline underline-offset-[3px] hover:text-foreground"
              />{" "}
              to request one.
            </p>
          )
        ) : null}

        <div className="mt-10 flex flex-wrap justify-center gap-4 text-center">
          <Link to="/about" className={footerLinkClass}>
            about mysterymixclub
          </Link>
          <Link to="/help" className={footerLinkClass}>
            help
          </Link>
          <Link to="/terms" className={footerLinkClass}>
            terms
          </Link>
          <Link to="/privacy" className={footerLinkClass}>
            privacy
          </Link>
        </div>
      </div>
    </main>
  );
}
