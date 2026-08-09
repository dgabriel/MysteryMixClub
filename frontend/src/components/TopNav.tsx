import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
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
 * deeper screens. The mark's amber centre label is the brand mark, and the
 * wordmark beside it carries the name. Amber placement is a design decision
 * (ADR 0012); the active nav link is amber too, which is what gives the bar its
 * hierarchy.
 *
 * The header sits on `sunken`, but `sunken` is 1.02:1 against the `floor` page
 * background — the closest pair in the whole ladder — so on its own the band is
 * invisible and exists only by its 1px edge. It therefore carries `shadow-z2`
 * and a `hairline-strong` edge, reading as chrome that floats above the page
 * rather than as a colour that competes with the content surfaces. `relative
 * z-10` is what lets that shadow land on the content instead of under it.
 *
 * Inactive links sit at `subtle-foreground` (5.10:1 on `sunken`) rather than
 * `muted-foreground`, so the amber active item has somewhere to stand out from.
 *
 * TopNav also renders on the public /about page (MYS-155), which has no auth
 * requirement. A signed-out (or still-resolving) visitor must never see the
 * authed-only actions — profile, admin, logout all assume a live session — so
 * anything short of "authenticated" collapses the nav to just the mark and a
 * single LOGIN link, both pointing at /login.
 */
export function TopNav({ back }: TopNavProps) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
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
  // `tracking-mono`. Inactive chrome sits at `subtle-foreground` (5.10:1 on
  // `sunken`, still AA) and hover resolves to `foreground`. It was
  // `muted-foreground` until the active state below existed; with every link at
  // one value there was nothing for an active item to be brighter *than*.
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
  const linkBase =
    "py-1.5 font-mono uppercase tracking-mono text-label transition-colors duration-150";
  const linkClass = `${linkBase} text-subtle-foreground hover:text-foreground disabled:text-subtle-foreground disabled:cursor-not-allowed`;
  // Links that pair a line icon with their label sit on one baseline.
  const iconLinkClass = `inline-flex items-center gap-1.5 ${linkClass}`;

  // Active-route highlight (MysteryMixClub-zche). The DS's own nav carries its
  // entire hierarchy this way — active in `accent`, everything else receding —
  // and without it every link here reads at exactly the same rank.
  //
  // `useLocation` rather than converting these to `NavLink`: the nav is built
  // from `button` + `navigate()`, and swapping in `NavLink` would restructure
  // every control and its tests for a class we can derive in one line.
  //
  // Prefix match so a nested route (`/admin/metrics`) still lights its parent.
  // Guarded with a `/` so `/help` never matches a hypothetical `/helpdesk`.
  const isActive = (to: string) => pathname === to || pathname.startsWith(`${to}/`);
  const navLinkClass = (to: string) =>
    isActive(to) ? `${linkBase} text-accent` : linkClass;

  if (!authed) {
    return (
      <header className="relative z-10 flex items-center justify-between border-b border-hairline-strong bg-sunken px-4 py-4 shadow-z2 sm:px-8">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => navigate("/login")}
            aria-label="login"
            className="transition-opacity duration-150 hover:opacity-70"
          >
            <ConcentricRings size={28} spinning accent wordmark />
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
    <header className="relative z-10 flex items-center justify-between border-b border-hairline-strong bg-sunken px-4 py-4 shadow-z2 sm:px-8">
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={() => navigate("/home")}
          aria-label="home"
          className="transition-opacity duration-150 hover:opacity-70"
        >
          {/* The vinyl disc, amber label with the `mmc` mark printed on it —
              persistent brand identity. At 28px the mark is 4.5px, which is
              detail rather than legible text; that is the point, the way the
              print on a real record label is.

              It turns, continuously, on every screen. The grooves are
              rotationally symmetric, so the `mmc` mark is the only thing that
              makes the motion visible — spinning without `wordmark` would be
              wasted frames. `prefers-reduced-motion` stops it (index.css). */}
          <ConcentricRings size={28} spinning accent wordmark />
        </button>
        {/* The wordmark, giving the bar a second voice — display against the
            mono links — and putting the brand on every screen rather than
            leaving it to a 28px dot. A sibling of the mark rather than inside
            it: folding it into the button would replace that button's
            accessible name ("home" / "login") with the brand text, and the
            destination is the more useful thing to announce. Hidden below `sm`,
            where the bar has no room for it. */}
        <span className="hidden font-display text-[1.2rem] font-extrabold uppercase leading-none tracking-display-snug text-foreground sm:block">
          mystery<span className="text-accent">mix</span>club
        </span>
        <Badge>beta</Badge>
        {back ? (
          <button type="button" onClick={() => navigate(back.to)} className={iconLinkClass}>
            <BackIcon />
            {back.label}
          </button>
        ) : null}
      </div>

      <nav className="flex items-center gap-4">
        <button type="button" onClick={() => navigate("/home")} className={navLinkClass("/home")}>
          home
        </button>
        <button
          type="button"
          onClick={() => navigate("/profile")}
          className={navLinkClass("/profile")}
        >
          profile
        </button>
        <button type="button" onClick={() => navigate("/about")} className={navLinkClass("/about")}>
          about
        </button>
        <button type="button" onClick={() => navigate("/help")} className={navLinkClass("/help")}>
          help
        </button>
        {isPlatformAdmin ? (
          <button
            type="button"
            onClick={() => navigate("/admin")}
            className={navLinkClass("/admin")}
          >
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
