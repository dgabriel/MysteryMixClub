import { TextField } from "./TextField";

type DeadlineWindowFieldProps = {
  idPrefix: string;
  label: string;
  days: string;
  hours: string;
  onDaysChange: (value: string) => void;
  onHoursChange: (value: string) => void;
  disabled?: boolean;
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
  disabled,
}: DeadlineWindowFieldProps) {
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
          disabled={disabled}
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
          disabled={disabled}
        />
      </div>
    </div>
  );
}
