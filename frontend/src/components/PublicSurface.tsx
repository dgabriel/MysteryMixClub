import type { ReactNode } from "react";

type PublicSurfaceProps = {
  children: ReactNode;
  className?: string;
};

/**
 * The light page surface, and the only place it is allowed to exist (ADR 0013).
 *
 * Design System v1.0 is a dark system: `body` stays `bg-floor`, every card is
 * `bg-card`, and the whole foreground ramp is derived against near-black. The
 * five public routes — /login, /about, /terms, /privacy, /help — are the one
 * exception, and they opt in by wrapping their page in this component rather
 * than by anything global. That matters: the background was briefly set on
 * `body` during the experiment that led here, which silently applied it to
 * every authed screen too.
 *
 * Inside it, use the `ink-*` ramp (`text-ink`, `text-ink-muted`,
 * `text-ink-accent`, `text-ink-link`, `border-ink-hairline`) — the dark ramp's
 * tokens fail WCAG AA on paper, `foreground` at 1.09:1 and `accent` at 2.62:1.
 * The two ramps must never mix on one surface.
 *
 * `TopNav` is deliberately *not* affected. It carries its own dark fill, so it
 * reads as the app's chrome sitting above a light page rather than as part of
 * it, and it needs no light variant.
 */
export function PublicSurface({ children, className = "" }: PublicSurfaceProps) {
  return (
    <div className={`flex min-h-screen flex-col bg-paper text-ink ${className}`}>{children}</div>
  );
}
