import type { ReactNode } from "react";

type PaperSurfaceProps = {
  children: ReactNode;
  className?: string;
};

/**
 * The light page surface, and the only way to get one (ADR 0013).
 *
 * Design System v1.0 is a dark system: `body` stays `bg-floor` and the whole
 * foreground ramp is derived against near-black. Named for the *surface* rather
 * than the audience — it began life as `PublicSurface`, covering only the five
 * public routes, and that name stopped being true the moment `/home` adopted it.
 * Where it may be used is a design decision recorded in ADR 0013, not something
 * the component's own name should try to enforce.
 *
 * Pages opt in by wrapping themselves in this rather than by anything global.
 * That distinction is the point: the background was briefly set on `body` during
 * the experiment that led here, which silently repainted every authed screen.
 *
 * Inside it, use the `ink-*` ramp (`text-ink`, `text-ink-muted`,
 * `text-ink-accent`, `text-ink-link`, `border-ink-hairline`) — the dark ramp's
 * tokens fail WCAG AA on paper, `foreground` at 1.09:1 and `accent` at 2.62:1.
 * **The two ramps must never mix on one surface.**
 *
 * Cards are the deliberate exception, and the reason this composes at all: a
 * `bg-card` island inside a paper page is its own dark surface, so everything
 * *within* it correctly keeps the dark ramp. Only chrome sitting directly on the
 * page moves to `ink`. A component that renders on both (`HelpLink`,
 * `TextField`, `Button`, `FormError`, `ConcentricRings`) takes an `onPaper`
 * prop rather than picking a ramp for itself.
 *
 * `TopNav` is deliberately *not* affected. It carries its own dark fill, so it
 * reads as the app's chrome sitting above a light page rather than as part of
 * it, and it needs no light variant.
 */
export function PaperSurface({ children, className = "" }: PaperSurfaceProps) {
  return (
    <div className={`flex min-h-screen flex-col bg-paper text-ink ${className}`}>{children}</div>
  );
}
