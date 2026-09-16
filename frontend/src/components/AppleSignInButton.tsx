/**
 * Apple's official "Sign in with Apple" button (black, per Apple's Human
 * Interface Guidelines for a dark page) -- the native-only counterpart to
 * GoogleSignInButton, added so the two sit at equal size and weight on
 * EmailEntryScreen (App Store Guideline 4.8 requires "equivalent placement
 * and prominence", not just presence).
 *
 * Like GoogleSignInButton, this is a documented style-guide exception (ADR
 * 0007): Apple's own Human Interface Guidelines fix the button's colors,
 * type, and mark the same way Google's brand guidelines do, so this is the
 * one other component that sits outside the Design System v1.0 token set on
 * purpose. Height matches GoogleSignInButton's 44px exactly -- Apple's own
 * guidelines set a 44pt *minimum*, but "equivalent prominence" is what 4.8
 * actually asks for, so matching Google's height precisely (not just
 * clearing Apple's own floor) is the deliberate choice here, not a
 * coincidence.
 *
 * Native-only: unlike Google, Apple's sign-in never needs a web `<a href>`
 * variant, since ASAuthorizationController has no browser-based equivalent
 * this app builds (MysteryMixClub-4vii.9 scoped Apple to native iOS only,
 * matching where Guideline 4.8 actually applies).
 */
const APPLE_BUTTON_CLASS = [
  "flex h-11 items-center justify-center gap-2 rounded-[4px] px-3",
  "bg-black text-white",
  "font-[-apple-system,BlinkMacSystemFont,'SF Pro Text',sans-serif] text-[15px] font-medium",
].join(" ");

/** Apple's own glyph (Bootstrap Icons' "apple" mark, MIT-licensed, sourced
 *  from bootstrap-icons@1.11.3 -- a faithful vector rendering of the Apple
 *  logo rather than a hand-drawn approximation, which matters here since
 *  Apple's own guidelines require using their actual mark). */
function AppleMarkAndLabel() {
  return (
    <>
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
        <path d="M11.182.008C11.148-.03 9.923.023 8.857 1.18c-1.066 1.156-.902 2.482-.878 2.516s1.52.087 2.475-1.258.762-2.391.728-2.43m3.314 11.733c-.048-.096-2.325-1.234-2.113-3.422s1.675-2.789 1.698-2.854-.597-.79-1.254-1.157a3.7 3.7 0 0 0-1.563-.434c-.108-.003-.483-.095-1.254.116-.508.139-1.653.589-1.968.607-.316.018-1.256-.522-2.267-.665-.647-.125-1.333.131-1.824.328-.49.196-1.422.754-2.074 2.237-.652 1.482-.311 3.83-.067 4.56s.625 1.924 1.273 2.796c.576.984 1.34 1.667 1.659 1.899s1.219.386 1.843.067c.502-.308 1.408-.485 1.766-.472.357.013 1.061.154 1.782.539.571.197 1.111.115 1.652-.105.541-.221 1.324-1.059 2.238-2.758q.52-1.185.473-1.282" />
      </svg>
      Sign in with Apple
    </>
  );
}

export function AppleSignInButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className={APPLE_BUTTON_CLASS}>
      <AppleMarkAndLabel />
    </button>
  );
}
