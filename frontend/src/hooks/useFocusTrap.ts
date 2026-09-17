import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Traps Tab/Shift+Tab focus inside `containerRef` for as long as it's
 * mounted, calls `onDismiss` on Escape, and restores focus to whatever had it
 * beforehand on unmount -- the app's first focus trap (the one other modal,
 * ReleaseNotesModal, predates this and is out of scope to retrofit here).
 * Built for the two onboarding guide modals (MysteryMixClub-6eo8) but not
 * specific to them.
 *
 * Reads `onDismiss` through a ref rather than depending on it directly, so
 * the effect runs exactly once per mount: these modals sit under routes that
 * poll (e.g. ClubHomeRoute refreshes every 60s), and a parent re-render
 * creating a new `onDismiss` closure each time must not re-run the initial
 * focus or reattach listeners.
 */
export function useFocusTrap(containerRef: RefObject<HTMLElement | null>, onDismiss: () => void): void {
  const onDismissRef = useRef(onDismiss);
  useEffect(() => {
    onDismissRef.current = onDismiss;
  });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;

    const focusables = () => Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
    focusables()[0]?.focus();

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onDismissRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusables();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus?.();
    };
  }, [containerRef]);
}
