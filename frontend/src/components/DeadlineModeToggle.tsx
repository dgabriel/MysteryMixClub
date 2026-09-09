type DeadlineModeToggleProps = {
  value: "duration" | "weekly_anchor";
  onChange: (value: "duration" | "weekly_anchor") => void;
  disabled?: boolean;
  onPaper?: boolean;
};

const OPTIONS: { value: "duration" | "weekly_anchor"; label: string }[] = [
  { value: "duration", label: "flexible window" },
  { value: "weekly_anchor", label: "weekly schedule" },
];

/**
 * Which of a club's two deadline schemes is active (ADR 0021) — a real fork
 * that swaps the entire field set beneath it, not a passive refinement like
 * AdminScreen's status filter. That distinction is why this borrows
 * EmailEntryScreen's sign-in-method tab bar instead: full-width tabs with a
 * `border-ink-accent`/`border-accent` underline indicator and a real
 * foreground/muted-foreground contrast shift, not just plain floating text.
 * (MysteryMixClub-ztbx — the original plain-text treatment tested as too
 * easy to miss.)
 */
export function DeadlineModeToggle({
  value,
  onChange,
  disabled,
  onPaper = false,
}: DeadlineModeToggleProps) {
  const tabClass = (active: boolean) =>
    [
      "-mb-px flex-1 border-b-2 py-3 font-mono uppercase tracking-mono-caps text-label transition-colors duration-150",
      "disabled:cursor-not-allowed",
      active
        ? onPaper
          ? "border-ink-accent text-ink"
          : "border-accent text-foreground"
        : onPaper
          ? "border-transparent text-ink-muted hover:text-ink"
          : "border-transparent text-muted-foreground hover:text-foreground",
    ].join(" ");

  return (
    // Deliberately role="group", not "tablist"/"tab" — that WAI-ARIA pattern
    // promises arrow-key roving-tabIndex navigation this doesn't implement,
    // same reasoning as EmailEntryScreen's own toggle.
    <div
      role="group"
      aria-label="deadline schedule"
      className={`flex border-b ${onPaper ? "border-ink-hairline" : "border-hairline"}`}
    >
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          disabled={disabled}
          className={tabClass(value === option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
