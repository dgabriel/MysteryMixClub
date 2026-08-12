import { TextField } from "./TextField";
import { WarningIcon } from "./WarningIcon";

type DeadlineWindowFieldProps = {
  idPrefix: string;
  label: string;
  days: string;
  hours: string;
  onDaysChange: (value: string) => void;
  onHoursChange: (value: string) => void;
  onBlur?: () => void;
  disabled?: boolean;
  /** Calm, window-specific validation message, or null/undefined if valid.
   *  Switches both the days and hours underlines to `destructive-text` and
   *  renders once below the pair (ADR 0004) rather than duplicating the
   *  message under each input. */
  error?: string | null;
  /** The field is on the light public/paper surface (ADR 0013). Forwarded to
   *  both `TextField`s, and applied to this component's own group eyebrow and
   *  error message — the dark ramp's `muted-foreground` is 3.23:1 on paper and
   *  `destructive-text` 2.86:1, so neither survives the move. */
  onPaper?: boolean;
};

/**
 * Days + hours pair for a submission/voting window (MYS-160), shared between
 * club creation and the post-creation club settings edit. The API stores
 * a single total-hours value; splitting it into two small inputs reads better
 * than one raw hours field for a duration players think of in days.
 */
export function DeadlineWindowField({
  idPrefix,
  label,
  days,
  hours,
  onDaysChange,
  onHoursChange,
  onBlur,
  disabled,
  error,
  onPaper = false,
}: DeadlineWindowFieldProps) {
  const invalid = Boolean(error);
  const errorId = error ? `${idPrefix}-error` : undefined;
  return (
    <div>
      {/* Group eyebrow over the days/hours pair. `text-meta` at
          `tracking-mono-wide` sits one step above the two TextField labels
          below it (`text-mini`/`tracking-mono-caps`), so the pair reads as one
          field without the group label competing with its own parts. It stays
          `muted-foreground` when the pair is invalid — the message below is
          what carries `destructive-text`, matching TextField's own label. */}
      <span
        className={`block font-mono uppercase tracking-mono-wide text-meta ${
          onPaper ? "text-ink-muted" : "text-muted-foreground"
        }`}
      >
        {label}
      </span>
      <div className="mt-2 flex items-start gap-6">
        <TextField
          id={`${idPrefix}-days`}
          label="days"
          name={`${idPrefix}-days`}
          type="number"
          min={0}
          max={7}
          step={1}
          value={days}
          onChange={(e) => onDaysChange(e.target.value)}
          onBlur={onBlur}
          disabled={disabled}
          invalid={invalid}
          onPaper={onPaper}
          aria-describedby={errorId}
        />
        <TextField
          id={`${idPrefix}-hours`}
          label="hours"
          name={`${idPrefix}-hours`}
          type="number"
          min={0}
          max={23}
          step={1}
          value={hours}
          onChange={(e) => onHoursChange(e.target.value)}
          onBlur={onBlur}
          disabled={disabled}
          invalid={invalid}
          onPaper={onPaper}
          aria-describedby={errorId}
        />
      </div>
      {/* Field-level, not screen-level: this is one logical field's message, so
          it takes TextField's inline-error treatment verbatim rather than
          `FormError` (which is documented for the message that isn't about a
          single field, and has no way to carry the `mt-2` that separates this
          from the inputs above it). */}
      {error ? (
        <p
          id={errorId}
          role="alert"
          className={`mt-2 flex items-center gap-1.5 font-mono text-sm ${
            onPaper ? "text-ink-destructive" : "text-destructive-text"
          }`}
        >
          <WarningIcon className="shrink-0" />
          {error}
        </p>
      ) : null}
    </div>
  );
}
