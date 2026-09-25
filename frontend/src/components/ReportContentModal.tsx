import { useId, useRef, useState } from "react";
import { Button } from "./Button";
import { MODAL_CLOSE, MODAL_PANEL, MODAL_SCRIM } from "./modalSurface";
import { ApiError, type ReportReason } from "../services/api";
import { useFocusTrap } from "../hooks/useFocusTrap";

/** Small line "×" glyph, matching OnboardingGuideModal/ReleaseNotesModal's
 *  own local close icon -- there's still no shared CloseIcon primitive. */
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

const REASONS: { value: ReportReason; label: string }[] = [
  { value: "inappropriate_content", label: "inappropriate content" },
  { value: "harassment", label: "harassment" },
  { value: "spam", label: "spam" },
  { value: "other", label: "other" },
];

type ReportContentModalProps = {
  /** What's being reported, shown for context (e.g. the note's own text). */
  contentPreview: string;
  onSubmit: (reason: ReportReason, detail: string) => Promise<void>;
  onDismiss: () => void;
  /** Optional follow-up offered after a successful report (MysteryMixClub-
   *  4vii.42): blocking the author is Guideline 1.2's other half, and the
   *  moment a member flags someone's text is the moment they're likeliest to
   *  want it. When both props are set the modal owns closing after submit
   *  (the caller's onSubmit must NOT dismiss): it shows "report sent" plus
   *  this offer, and the [done] button calls onDismiss. */
  blockTarget?: { userId: string; displayName: string };
  onBlock?: (userId: string) => Promise<void>;
};

/**
 * Shared "report" dialog for user-generated content (MysteryMixClub-4vii.13)
 * -- currently only wired up for notes, but generic on purpose (contentPreview
 * + onSubmit) so a future content type can reuse it without a rewrite. Same
 * chrome/focus-trap pattern as OnboardingGuideModal: a `sheet` (Z4) panel,
 * Escape-to-dismiss, focus trapping and restoration via useFocusTrap.
 */
export function ReportContentModal({
  contentPreview,
  onSubmit,
  onDismiss,
  blockTarget,
  onBlock,
}: ReportContentModalProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, onDismiss);

  const [reason, setReason] = useState<ReportReason | null>(null);
  const [detail, setDetail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Post-submit block offer state (only reachable when blockTarget+onBlock
  // are set). `sent` switches the dialog from form to confirmation.
  const [sent, setSent] = useState(false);
  const [blocking, setBlocking] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [blockError, setBlockError] = useState<string | null>(null);

  async function submit() {
    if (!reason || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(reason, detail.trim());
      // Callers that passed a blockTarget keep the dialog open for the
      // follow-up offer; everyone else closes from their own onSubmit and
      // never reaches this line.
      if (blockTarget && onBlock) setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "couldn't send your report. try again.");
      setSubmitting(false);
    }
  }

  async function handleBlock() {
    if (!blockTarget || !onBlock) return;
    setBlocking(true);
    setBlockError(null);
    try {
      await onBlock(blockTarget.userId);
      setBlocked(true);
    } catch (err) {
      setBlockError(err instanceof ApiError ? err.message : "couldn't block them. try again.");
    } finally {
      setBlocking(false);
    }
  }

  return (
    <div className={MODAL_SCRIM}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`w-full max-w-md p-6 ${MODAL_PANEL}`}
      >
        <div className="flex items-center justify-between gap-4">
          <h2
            id={titleId}
            className="font-display text-[1.375rem] font-extrabold uppercase leading-none tracking-display-snug text-ink"
          >
            report content
          </h2>
          <button
            type="button"
            onClick={onDismiss}
            aria-label="dismiss report dialog"
            className={MODAL_CLOSE}
          >
            <CloseIcon />
          </button>
        </div>

        {sent && blockTarget && onBlock ? (
          <>
            <p className="mt-3 text-sm leading-[1.6] text-ink-muted">
              report sent. we review every report, and we can remove content or restrict accounts
              from here.
            </p>
            {blocked ? (
              <p className="mt-4 text-sm leading-[1.6] text-ink">
                blocked. {blockTarget.displayName}&rsquo;s notes are hidden from you. they
                aren&rsquo;t told, and nothing changes for them.
              </p>
            ) : (
              <>
                <p className="mt-4 text-sm leading-[1.6] text-ink-muted">
                  stop seeing {blockTarget.displayName}&rsquo;s notes? blocking hides them
                  everywhere in your app. they aren&rsquo;t told, and nothing changes for them.
                </p>
                {blockError ? (
                  <p role="alert" className="mt-3 text-sm text-ink-destructive">
                    {blockError}
                  </p>
                ) : null}
                <div className="mt-4">
                  <Button
                    onPaper
                    variant="ghost"
                    type="button"
                    onClick={() => void handleBlock()}
                    disabled={blocking}
                  >
                    {blocking ? "blocking…" : `block ${blockTarget.displayName}`}
                  </Button>
                </div>
              </>
            )}
            <div className="mt-5 flex items-center justify-end">
              <Button onPaper type="button" onClick={onDismiss}>
                done
              </Button>
            </div>
          </>
        ) : (
          <>
            <p className="mt-3 text-sm leading-[1.6] text-ink-muted">
              &ldquo;{contentPreview}&rdquo;
            </p>

            <fieldset className="mt-5">
              <legend className="font-mono text-mini uppercase tracking-mono-caps text-ink-muted">
                reason
              </legend>
              <div className="mt-2 space-y-2">
                {REASONS.map((r) => (
                  <label key={r.value} className="flex cursor-pointer items-center gap-2.5">
                    <input
                      type="radio"
                      name="report-reason"
                      value={r.value}
                      checked={reason === r.value}
                      onChange={() => setReason(r.value)}
                      className="h-4 w-4 accent-ink-accent"
                    />
                    <span className="text-sm text-ink">{r.label}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <label className="mt-4 block">
              <span className="block font-mono text-mini uppercase tracking-mono-caps text-ink-muted">
                details (optional)
              </span>
              <textarea
                value={detail}
                maxLength={500}
                rows={2}
                onChange={(e) => setDetail(e.target.value)}
                className="mt-2 w-full resize-none rounded-none border-0 border-b border-ink-muted bg-transparent px-0 py-1 font-mono text-sm text-ink placeholder:text-ink-muted focus:border-ink-accent focus:outline-none"
              />
            </label>

            {error ? (
              <p role="alert" className="mt-3 text-sm text-ink-destructive">
                {error}
              </p>
            ) : null}

            <div className="mt-5 flex items-center justify-end gap-4">
              <button
                type="button"
                onClick={onDismiss}
                className="font-mono text-mini uppercase tracking-mono-caps text-ink-muted hover:text-ink"
              >
                cancel
              </button>
              <Button
                onPaper
                type="button"
                onClick={() => void submit()}
                disabled={!reason || submitting}
              >
                {submitting ? "sending…" : "submit report"}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
