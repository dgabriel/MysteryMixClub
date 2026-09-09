import { TextField } from "./TextField";
import { WarningIcon } from "./WarningIcon";
import { WEEKDAYS } from "../utils/deadlineAnchor";
import type { Weekday } from "../services/api";

// Shared visual language with TextField (underline-only, mono label above),
// since no shared Select primitive exists yet (MysteryMixClub-z845) — a
// `<select>` can't use TextField itself, which renders a plain `<input>`.
function selectClasses(onPaper: boolean, invalid: boolean) {
  const rule = onPaper
    ? invalid
      ? "border-ink-destructive"
      : "border-ink-muted"
    : invalid
      ? "border-destructive-text"
      : "border-muted-foreground";
  const text = onPaper ? "text-ink" : "text-foreground";
  const focus = onPaper ? "focus:border-ink-accent" : "focus:border-accent";
  return [
    `mt-2 w-full bg-transparent font-mono text-sm ${text}`,
    "border-0 border-b rounded-none px-0 py-1",
    rule,
    `focus:outline-none ${focus}`,
  ].join(" ");
}

function selectLabelClasses(onPaper: boolean) {
  return `block font-mono uppercase tracking-mono-caps text-mini ${
    onPaper ? "text-ink-muted" : "text-muted-foreground"
  }`;
}

type DeadlineAnchorFieldProps = {
  idPrefix: string;
  label: string;
  weekday: Weekday | "";
  time: string;
  onWeekdayChange: (value: Weekday) => void;
  onTimeChange: (value: string) => void;
  onBlur?: () => void;
  disabled?: boolean;
  error?: string | null;
  onPaper?: boolean;
};

/**
 * Weekday + time pair for one phase of a weekly-anchor deadline (ADR 0021),
 * the anchor-mode sibling of `DeadlineWindowField`'s days+hours pair. The
 * timezone that gives the time meaning is set once per club, not per phase —
 * see `TimezoneField`.
 */
export function DeadlineAnchorField({
  idPrefix,
  label,
  weekday,
  time,
  onWeekdayChange,
  onTimeChange,
  onBlur,
  disabled,
  error,
  onPaper = false,
}: DeadlineAnchorFieldProps) {
  const invalid = Boolean(error);
  const errorId = error ? `${idPrefix}-error` : undefined;
  return (
    <div>
      <span
        className={`block font-mono uppercase tracking-mono-wide text-meta ${
          onPaper ? "text-ink-muted" : "text-muted-foreground"
        }`}
      >
        {label}
      </span>
      <div className="mt-2 flex items-start gap-6">
        <div className="flex-1">
          <label htmlFor={`${idPrefix}-weekday`} className={selectLabelClasses(onPaper)}>
            day
          </label>
          <select
            id={`${idPrefix}-weekday`}
            name={`${idPrefix}-weekday`}
            value={weekday}
            onChange={(e) => onWeekdayChange(e.target.value as Weekday)}
            onBlur={onBlur}
            disabled={disabled}
            aria-invalid={invalid}
            aria-describedby={errorId}
            className={selectClasses(onPaper, invalid)}
          >
            <option value="" disabled>
              choose a day
            </option>
            {WEEKDAYS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </div>
        <TextField
          id={`${idPrefix}-time`}
          label="time"
          name={`${idPrefix}-time`}
          type="time"
          value={time}
          onChange={(e) => onTimeChange(e.target.value)}
          onBlur={onBlur}
          disabled={disabled}
          invalid={invalid}
          onPaper={onPaper}
          aria-describedby={errorId}
        />
      </div>
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

type TimezoneFieldProps = {
  id: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  disabled?: boolean;
  onPaper?: boolean;
};

/** The single timezone picker for a club's weekly-anchor schedule — one zone
 *  governs both phases (ADR 0021). */
export function TimezoneField({
  id,
  value,
  options,
  onChange,
  disabled,
  onPaper = false,
}: TimezoneFieldProps) {
  return (
    <div>
      <label htmlFor={id} className={selectLabelClasses(onPaper)}>
        timezone
      </label>
      <select
        id={id}
        name={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className={selectClasses(onPaper, false)}
      >
        {options.map((tz) => (
          <option key={tz} value={tz}>
            {tz}
          </option>
        ))}
      </select>
    </div>
  );
}
