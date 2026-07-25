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
   *  Marks both the days and hours inputs Rust and renders once below the
   *  pair (ADR 0004) rather than duplicating the message under each input. */
  error?: string | null;
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
}: DeadlineWindowFieldProps) {
  const invalid = Boolean(error);
  const errorId = error ? `${idPrefix}-error` : undefined;
  return (
    <div>
      <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
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
          aria-describedby={errorId}
        />
      </div>
      {error ? (
        <p
          id={errorId}
          role="alert"
          className="mt-2 flex items-center gap-1.5 font-mono text-[13px] text-rust"
        >
          <WarningIcon className="shrink-0" />
          {error}
        </p>
      ) : null}
    </div>
  );
}
