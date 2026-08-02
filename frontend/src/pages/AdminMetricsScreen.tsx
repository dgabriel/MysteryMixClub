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
 * AuthedLayout. Nothing here is an action or a warning, so the page stays
 * entirely in the Sage/Ink/Muted family and spends no Rust.
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
      <h1 className="font-serif lowercase text-[28px] leading-tight text-ink">metrics</h1>
      <p className="mt-4 font-mono text-[13px] font-light text-muted">
        platform totals as of right now.
      </p>

      {loading ? (
        <div className="mt-8 flex justify-center">
          <ConcentricRings size={56} spinning />
        </div>
      ) : error || !metrics ? (
        <p role="alert" className="mt-8 font-mono text-[13px] font-light text-muted">
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
        <h2 className="font-serif lowercase text-[20px] leading-tight text-ink">signups</h2>
        <p className="mt-2 font-mono uppercase tracking-label text-[9px] text-muted">
          {trend ? `last ${trend.days} days` : "over time"}
        </p>
        <Card className="mt-4">
          {trendLoading ? (
            <div className="flex justify-center py-4">
              <ConcentricRings size={56} spinning />
            </div>
          ) : trendError || !trend ? (
            <p role="alert" className="font-mono text-[13px] font-light text-muted">
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
      <h2 className="font-serif lowercase text-[20px] leading-tight text-ink">{title}</h2>
      <Card className="mt-4">
        <dl className="divide-y divide-border">{children}</dl>
      </Card>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-3 first:pt-0 last:pb-0">
      <dt className="font-mono uppercase tracking-label text-[9px] text-muted">{label}</dt>
      <dd className="font-mono text-[16px] text-ink">{value}</dd>
    </div>
  );
}
