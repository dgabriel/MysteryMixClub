import { Button } from "./Button";
import { RELEASE_NOTES, formatReleaseDate } from "../data/releaseNotes";

/** Small line "×" glyph, matching the 1.25px stroke weight of TopNav's own
 *  local icons (BackIcon/LogoutIcon) — this modal is the first place that
 *  needs a close control, so there's no shared CloseIcon to reuse yet. */
function CloseIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.25"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M3 3l10 10M13 3 3 13" />
    </svg>
  );
}

type ReleaseNotesModalProps = {
  onDismiss: () => void;
};

/**
 * The running "what's new" list (MysteryMixClub, release-notes-on-release
 * request) — shown automatically once per new entry in `releaseNotes.ts`
 * (see `hasUnseenRelease`, wired in `AuthedLayout`), and reachable any time
 * after that from the BETA badge in `TopNav`. Same content either way: this
 * always renders the full history, newest first, dates as group titles.
 *
 * Follows the app's one existing modal precedent (MixDetailRoute's
 * unsaved-changes confirm): a `sheet` (Z4) panel with `shadow-z4` and no
 * `border` (the shadow token carries its own ring), `foreground` body text
 * since `sheet` is the one surface `muted-foreground` fails.
 */
export function ReleaseNotesModal({ onDismiss }: ReleaseNotesModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-floor/80 px-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="release-notes-title"
        className="flex max-h-[80vh] w-full max-w-md flex-col rounded-tile bg-sheet shadow-z4"
      >
        <div className="flex items-center justify-between gap-4 px-6 pt-5">
          <h2
            id="release-notes-title"
            className="font-display text-[1.25rem] font-extrabold uppercase leading-[0.9] tracking-display-snug text-foreground"
          >
            what&apos;s new
          </h2>
          <button
            type="button"
            onClick={onDismiss}
            aria-label="close"
            className="text-foreground transition-colors duration-150 hover:text-accent"
          >
            <CloseIcon />
          </button>
        </div>
        <div className="mt-4 flex-1 space-y-6 overflow-y-auto px-6">
          {RELEASE_NOTES.map((entry) => (
            <div key={entry.date}>
              <h3 className="font-mono uppercase tracking-mono-wide text-meta text-foreground">
                {formatReleaseDate(entry.date)}
              </h3>
              <ul className="mt-2 list-disc space-y-1.5 pl-5">
                {entry.items.map((item) => (
                  <li key={item} className="text-sm leading-[1.72] text-foreground">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="px-6 pb-5 pt-6">
          <Button type="button" onClick={onDismiss} className="w-full">
            got it
          </Button>
        </div>
      </div>
    </div>
  );
}
