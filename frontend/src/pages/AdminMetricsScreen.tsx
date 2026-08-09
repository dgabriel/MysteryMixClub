import type { ReactNode } from "react";
import type { AdminMetrics, AdminSignupTrend } from "../services/api";
import { Card } from "../components/Card";
import { ConcentricRings } from "../components/ConcentricRings";
import { SignupTrendChart } from "../components/SignupTrendChart";

type AdminMetricsScreenProps = {
  metrics: AdminMetrics | null;
  loading: boolean;
  error?: string | null;
  trend: AdminSignupTrend | null;
  trendLoading: boolean;
  trendError?: string | null;
};

/**
 * Read-only platform snapshot (MysteryMixClub-etz7.3): the aggregate counts from
 * GET /admin/metrics, grouped into four cards, plus the daily signup trend
 * (MysteryMixClub-etz7.4). Content-only — the shared TopNav is rendered by
 * AuthedLayout, so this screen renders no hero mark of its own.
 *
 * **Sibling of AdminScreen (R15).** The stat groups reuse the record-list
 * pattern that screen established: a `Card` surface holding the rows,
 * `hairline-soft` separators between them, mono for every cell, and the
 * `muted-foreground` label / `foreground` value pair. They stay `dl`/`dt`/`dd`
 * rather than `ul`/`li` because a label and its count really are a description
 * list, not a record with a control.
 *
 * **Every row is a number**, which is exactly what the guide's small-label /
 * data-value pairing is for: the term takes the default mono Label
 * (`text-mini`, uppercase, `tracking-mono`, `muted-foreground`) and the count
 * takes the Mono Data value (`text-sm`, normal tracking, `foreground`), so the
 * value is what the eye lands on when seventeen of these stack up.
 *
 * Amber budget (category rule, not a count): none. Nothing on this page is an
 * action or an achievement — it is a read-only snapshot with no controls. The
 * one place amber appears is inside the chart, where `chart-1` *is* `accent`;
 * the style guide names a single-series chart as the sanctioned
 * amber-not-on-action case.
 *
 * The snapshot and the trend are two independent requests, so each carries its
 * own loading and error state and neither section waits on the other.
 */
export function AdminMetricsScreen({
  metrics,
  loading,
  error,
  trend,
  trendLoading,
  trendError,
}: AdminMetricsScreenProps) {
  if (loading && trendLoading) {
    return (
      <main className="flex flex-1 items-center justify-center px-4 sm:px-8">
        <ConcentricRings size={88} spinning className="mx-auto" />
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-lg px-4 pb-16 sm:px-8">
      <h1 className="font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
        metrics
      </h1>
      <p className="mt-4 text-sm leading-[1.72] text-muted-foreground">
        platform totals as of right now.
      </p>

      {loading ? (
        <div className="mt-8 flex justify-center">
          <ConcentricRings size={56} spinning />
        </div>
      ) : error || !metrics ? (
        // A failed fetch is an outcome from the server, not form validation, so
        // it stays ordinary body copy rather than taking ADR 0004's
        // `destructive-text` category — the same call R15 made.
        <p role="alert" className="mt-8 text-sm leading-[1.72] text-foreground">
          {error ?? "couldn't load the metrics."}
        </p>
      ) : (
        <div className="mt-8 space-y-12">
          <StatGroup title="users and clubs">
            <Stat label="users" value={metrics.total_users} />
            <Stat label="clubs" value={metrics.total_clubs} />
            <Stat label="active clubs" value={metrics.active_clubs} />
            <Stat label="complete clubs" value={metrics.complete_clubs} />
            {/* 30+ days old, zero submissions ever — mixes are still cycling
                open/closed on the scheduler with nobody actually using them. */}
            <Stat label="abandoned clubs" value={metrics.abandoned_clubs} />
          </StatGroup>

          <StatGroup title="mystery mixes">
            <Stat label="mixes" value={metrics.total_mixes} />
            <Stat label="pending" value={metrics.pending_mixes} />
            <Stat label="open for submissions" value={metrics.open_submission_mixes} />
            <Stat label="open for voting" value={metrics.open_voting_mixes} />
            <Stat label="closed" value={metrics.closed_mixes} />
          </StatGroup>

          <StatGroup title="submissions and engagement">
            <Stat label="submissions" value={metrics.total_submissions} />
            {/* Averaged over mixes that received at least one submission — every
                club auto-creates all of its mixes up front, so "per mix" would
                mostly measure how far ahead clubs are scheduled. */}
            <Stat
              label="avg per mix with submissions"
              value={metrics.avg_submissions_per_mix.toFixed(1)}
            />
            <Stat label="votes" value={metrics.total_votes} />
            <Stat label="notes" value={metrics.total_notes} />
          </StatGroup>

          <StatGroup title="waitlist">
            <Stat label="on the waitlist" value={metrics.waitlist_total} />
            <Stat label="pending" value={metrics.waitlist_pending} />
            <Stat label="invited" value={metrics.waitlist_invited} />
          </StatGroup>
        </div>
      )}

      <section className="mt-12">
        <h2 className="font-mono text-meta uppercase tracking-mono-wide text-muted-foreground">
          signups
        </h2>
        <p className="mt-2 font-mono uppercase tracking-mono text-mini text-muted-foreground">
          {trend ? `last ${trend.days} days` : "over time"}
        </p>
        <Card className="mt-4">
          {trendLoading ? (
            <div className="flex justify-center py-4">
              <ConcentricRings size={56} spinning />
            </div>
          ) : trendError || !trend ? (
            <p role="alert" className="text-sm leading-[1.72] text-foreground">
              {trendError ?? "couldn't load the signup trend."}
            </p>
          ) : (
            <SignupTrendChart buckets={trend.buckets} />
          )}
        </Card>
      </section>
    </main>
  );
}

function StatGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="font-mono text-meta uppercase tracking-mono-wide text-muted-foreground">
        {title}
      </h2>
      <Card className="mt-4">
        {/* `hairline-soft` is the step the guide names for dividers *within* a
            card, and the rows inset to the card's own padding the way R15's
            record lists do. */}
        <dl className="divide-y divide-hairline-soft">{children}</dl>
      </Card>
    </section>
  );
}

/** One label/count pair. The small mono label against the larger mono value is
 *  the guide's data-value pairing — on a screen whose entire content is
 *  numbers, it is what lets the counts scan down the right edge. */
function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-4 first:pt-0 last:pb-0">
      <dt className="font-mono uppercase tracking-mono text-mini text-muted-foreground">{label}</dt>
      <dd className="font-mono text-sm text-foreground">{value}</dd>
    </div>
  );
}
