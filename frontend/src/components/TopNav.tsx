import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { ConcentricRings } from "./ConcentricRings";

type TopNavProps = {
  /** Optional back affordance shown on the far left after the ring mark — used by
   *  the round screen to return to its league ("← league"). When omitted no back
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
 * Shared top navigation for every authenticated screen. The ring mark returns
 * home; HOME / PROFILE / LOGOUT are always present, ADMIN only for platform
 * admins. An optional back affordance (e.g. "← league") sits beside the mark on
 * deeper screens. The mark carries its single Rust dot as persistent brand
 * identity — a style-guide exception that does NOT count against a screen's
 * one-Rust budget (see docs/design/style-guide.md). Every nav *link* still stays
 * in the Sage/Ink family, so the chrome never competes with a screen's accent.
 */
export function TopNav({ back }: TopNavProps) {
  const navigate = useNavigate();
  const { isPlatformAdmin, logout } = useAuth();
  const [loggingOut, setLoggingOut] = useState(false);

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await logout();
      navigate("/login", { replace: true });
    } finally {
      setLoggingOut(false);
    }
  }

  const linkClass =
    "font-mono uppercase tracking-ui text-[11px] text-ink transition-colors duration-150 hover:text-sage disabled:opacity-50 disabled:cursor-not-allowed";
  // Links that pair a line icon with their label sit on one baseline.
  const iconLinkClass = `inline-flex items-center gap-1.5 ${linkClass}`;

  return (
    <header className="flex items-center justify-between px-4 py-4 sm:px-8">
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={() => navigate("/home")}
          aria-label="home"
          className="transition-opacity duration-150 hover:opacity-70"
        >
          {/* Brand mark with its Rust dot — persistent brand identity, exempt
              from the one-Rust-per-screen rule (see style guide). */}
          <ConcentricRings size={28} accent />
        </button>
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
