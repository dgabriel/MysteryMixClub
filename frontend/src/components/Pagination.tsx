import { Button } from "./Button";

/**
 * Prev/next pager for a client-side-sliced list (MysteryMixClub-ps1w.4).
 * Renders nothing when everything fits on one page -- callers don't need to
 * gate on `totalPages > 1` themselves.
 */
export function Pagination({
  page,
  totalPages,
  onPageChange,
  onPaper = false,
}: {
  /** 1-indexed current page. */
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  onPaper?: boolean;
}) {
  if (totalPages <= 1) return null;

  return (
    <nav
      aria-label="pagination"
      className="mt-4 flex items-center justify-between gap-4"
    >
      <Button
        type="button"
        variant="ghost"
        onPaper={onPaper}
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        prev
      </Button>
      <span
        className={[
          "font-mono uppercase tracking-mono-caps text-mini",
          onPaper ? "text-ink-muted" : "text-muted-foreground",
        ].join(" ")}
      >
        page {page} of {totalPages}
      </span>
      <Button
        type="button"
        variant="ghost"
        onPaper={onPaper}
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
      >
        next
      </Button>
    </nav>
  );
}
