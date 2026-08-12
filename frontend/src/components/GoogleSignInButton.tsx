/**
 * Google's official "Sign in with Google" button (dark theme), rendered as a
 * real link because the endpoint 302s to Google's consent screen — a fetch
 * through services/api.ts can't follow a top-level navigation.
 *
 * Google's branding terms forbid restyling the logo, colors, or type, so this is
 * the one component in the app that sits outside the Design System v1.0 token
 * set, and the one place raw hex in a className is correct: these values are
 * Google's brand, not ours to tokenize. A documented standing style-guide
 * exception (ADR 0007). Height is 44px — Google's spec allows it and it clears
 * the touch-target floor.
 *
 * It renders Google's DARK variant, not their light one. That is a choice
 * between two options Google itself publishes rather than a reskin: the light
 * button's white fill was the single brightest object on a near-black page.
 * Every value below is Google's own for the dark theme —
 *
 *   - container `#131314`, stroke `#8E918F`, label `#E3E3E3`
 *   - the state layer: white at 8% on hover, 12% on press
 *
 * — with the 4px radius, Roboto, 14px / 0.25px type, and the unmodified
 * multi-color `G` all carried over untouched from the light button. The state
 * layer is a `before:` overlay rather than a second flat hex precisely so no
 * hover/press color has to be invented; it composites Google's published
 * percentages over Google's published fill. It sits above the mark, which is
 * what Google's own `gsi-material-button-state` element does.
 *
 * The one thing Google does NOT publish for the dark button is a focus-ring
 * color: their implementation reuses the 12% state layer and draws no ring at
 * all. A 12% white veil on a near-black page is not a visible focus indicator,
 * so the ring stays, colored with `#E3E3E3` — the button's own published
 * dark-theme label color, 14.5:1 against the `#131314` fill. That is a value
 * from this same Google spec rather than an invented one or an app token
 * imported into a component that is exempt from app tokens.
 */
export function GoogleSignInButton({ href }: { href: string }) {
  return (
    <a
      href={href}
      className={[
        "relative flex h-11 items-center justify-center gap-[10px] rounded-[4px] px-3",
        "border border-[#8E918F] bg-[#131314] text-[#E3E3E3] no-underline",
        "font-[Roboto,arial,sans-serif] text-[14px] font-medium tracking-[0.25px]",
        "before:pointer-events-none before:absolute before:inset-0 before:rounded-[4px]",
        "before:bg-white before:opacity-0 before:transition-opacity before:duration-150",
        "hover:before:opacity-[0.08] active:before:opacity-[0.12]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#E3E3E3]",
      ].join(" ")}
    >
      <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
        <path
          fill="#EA4335"
          d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
        />
        <path
          fill="#4285F4"
          d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
        />
        <path
          fill="#FBBC05"
          d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
        />
        <path
          fill="#34A853"
          d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
        />
      </svg>
      Sign in with Google
    </a>
  );
}
