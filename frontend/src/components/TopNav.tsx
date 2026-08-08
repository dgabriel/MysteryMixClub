import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { ConcentricRings } from "./ConcentricRings";
import { Badge } from "./Badge";

type TopNavProps = {
  /** Optional back affordance shown on the far left after the ring mark — used by
   *  the mix screen to return to its club ("← club"). When omitted no back
   *  link renders. */
  back?: { label: string; to: string };
};

/** Small line back-arrow — 1.25px stroke, matching the iconography spec. */
function BackIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.25"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M10 3 5 8l5 5" />
    </svg>
  );
}

/** Small line "leave" glyph (door + arrow) for logout — 1.25px stroke. */
function LogoutIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.25"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M6 2.5H3.5A1.5 1.5 0 0 0 2 4v8a1.5 1.5 0 0 0 1.5 1.5H6" />
      <path d="M10 11l3-3-3-3M13 8H6" />
    </svg>
  );
}

/**
 * Shared top navigation. On authenticated screens the ring mark returns home;
 * HOME / PROFILE / ABOUT / HELP / LOGOUT are always present, ADMIN only for
 * platform admins. An optional back affordance (e.g. "← club") sits beside the mark on
 * deeper screens. The mark's amber centre label is the brand mark: identity is a
 * third amber category alongside action and achievement (ADR 0010), and this is
 * one of its two sanctioned placements — persistent chrome, present on every
 * screen, outside any individual screen's reasoning about amber. Every nav
 * *link* stays on the foreground ramp, so the chrome never competes with a
 * screen's accent.
 *
 * The header is chrome below content, so it sits on `sunken` with a `hairline`
 * bottom edge — the style tile's bottom-nav treatment, mirrored for a nav that
 * sits at the top. `sunken` is only one step above the `floor` page background,
 * which is the point: the band reads as chrome via its edge rather than by
 * competing with the content surfaces above `card`.
 *
 * TopNav also renders on the public /about page (MYS-155), which has no auth
 * requirement. A signed-out (or still-resolving) visitor must never see the
 * authed-only actions — profile, admin, logout all assume a live session — so
 * anything short of "authenticated" collapses the nav to just the mark and a
 * single LOGIN link, both pointing at /login.
 */
export function TopNav({ back }: TopNavProps) {
  const navigate = useNavigate();
  const { status, isPlatformAdmin, logout } = useAuth();
  const [loggingOut, setLoggingOut] = useState(false);
  const authed = status === "authenticated";

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await logout();
      navigate("/login", { replace: true });
    } finally {
      setLoggingOut(false);
    }
  }

  // Mono button type per the style guide: `text-label`, uppercase,
  // `tracking-mono`. Inactive chrome sits at `muted-foreground` (6.23:1 on
  // `sunken`) and hover resolves to `foreground`.
  //
  // Disabled follows Button's treatment (R2) rather than the old
  // `disabled:opacity-50`, which put a label at 2.72:1 and, on a near-black
  // page, flattens a control into the background instead of quieting it. A nav
  // link has no fill and no edge to begin with, so the two utilities that strip
  // those (`disabled:bg-transparent` / `disabled:border-transparent`) would be
  // inert here; what carries the state is pinning the label to
  // `muted-foreground` so the only disabled control — logout, mid-request —
  // cannot brighten to `foreground` under `hover:`, plus `cursor-not-allowed`
  // as a supplement (it does not exist on touch, so it is never the signal).
  const linkClass =
    "py-1.5 font-mono uppercase tracking-mono text-label text-muted-foreground transition-colors duration-150 hover:text-foreground disabled:text-muted-foreground disabled:cursor-not-allowed";
  // Links that pair a line icon with their label sit on one baseline.
  const iconLinkClass = `inline-flex items-center gap-1.5 ${linkClass}`;

  if (!authed) {
    return (
      <header className="flex items-center justify-between border-b border-hairline bg-sunken px-4 py-4 sm:px-8">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => navigate("/login")}
            aria-label="login"
            className="transition-opacity duration-150 hover:opacity-70"
          >
            <ConcentricRings size={28} accent />
          </button>
          <Badge>beta</Badge>
        </div>
        <nav className="flex items-center gap-4">
          <button type="button" onClick={() => navigate("/login")} className={linkClass}>
            login
          </button>
        </nav>
      </header>
    );
  }

  return (
    <header className="flex items-center justify-between border-b border-hairline bg-sunken px-4 py-4 sm:px-8">
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={() => navigate("/home")}
          aria-label="home"
          className="transition-opacity duration-150 hover:opacity-70"
        >
          {/* The vinyl disc with its amber centre label — persistent brand
              identity. Identity is amber's third category (ADR 0010), and the
              shared nav's 28px mark is one of its two sanctioned placements. */}
          <ConcentricRings size={28} accent />
        </button>
        <Badge>beta</Badge>
        {back ? (
          <button type="button" onClick={() => navigate(back.to)} className={iconLinkClass}>
            <BackIcon />
            {back.label}
          </button>
        ) : null}
      </div>

      <nav className="flex items-center gap-4">
        <button type="button" onClick={() => navigate("/home")} className={linkClass}>
          home
        </button>
        <button type="button" onClick={() => navigate("/profile")} className={linkClass}>
          profile
        </button>
        <button type="button" onClick={() => navigate("/about")} className={linkClass}>
          about
        </button>
        <button type="button" onClick={() => navigate("/help")} className={linkClass}>
          help
        </button>
        {isPlatformAdmin ? (
          <button type="button" onClick={() => navigate("/admin")} className={linkClass}>
            admin
          </button>
        ) : null}
        <button
          type="button"
          onClick={handleLogout}
          disabled={loggingOut}
          className={iconLinkClass}
        >
          <LogoutIcon />
          {loggingOut ? "logging out…" : "logout"}
        </button>
      </nav>
    </header>
  );
}
