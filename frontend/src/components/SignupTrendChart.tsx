import { useMemo } from "react";
import { extent, line, max, scaleLinear, scaleUtc, utcFormat } from "d3";
import type { SignupBucket } from "../services/api";

type SignupTrendChartProps = {
  /** Ascending oldest-first, zero-filled — exactly what the trend endpoint returns. */
  buckets: SignupBucket[];
};

// The marks are drawn in their own coordinate space and scaled to the container
// by the viewBox, so this is an aspect ratio, not a pixel size.
const VIEW_WIDTH = 400;
const VIEW_HEIGHT = 150;
const MARGIN = { top: 12, right: 6, bottom: 22, left: 34 };
const INNER_WIDTH = VIEW_WIDTH - MARGIN.left - MARGIN.right;
const INNER_HEIGHT = VIEW_HEIGHT - MARGIN.top - MARGIN.bottom;

/** Chart-space x to a percentage of the wrapper's width. */
const pctX = (x: number) => `${(((MARGIN.left + x) / VIEW_WIDTH) * 100).toFixed(3)}%`;
/** Chart-space y to a percentage of the wrapper's height. */
const pctY = (y: number) => `${(((MARGIN.top + y) / VIEW_HEIGHT) * 100).toFixed(3)}%`;
// Value ticks hang in the left gutter, right-aligned 6px short of the axis.
const VALUE_TICK_RIGHT = `${((VIEW_WIDTH - (MARGIN.left - 6)) / VIEW_WIDTH) * 100}%`;

const formatDay = utcFormat("%b %-d");
const TICK_CLASS =
  "absolute whitespace-nowrap font-mono uppercase leading-none tracking-label text-[11px] text-muted";

/**
 * Daily signups over a trailing window (MysteryMixClub-etz7.4) — the app's first
 * chart, so it also sets the pattern: d3 owns the math (scales, shape
 * generators) and React owns the DOM (the SVG is plain JSX, d3 never touches a
 * node React renders into). Pure — the caller fetches the data.
 *
 * Restraint over decoration: one Sage line, one Border baseline, and four tick
 * labels (0, the peak, the first day, the last day). No gridlines, no per-point
 * dots, no area fill, no Rust.
 *
 * The marks scale with the viewBox; the tick labels don't. They're HTML
 * positioned by percentage over the SVG so their size stays a true 11px instead
 * of shrinking under the Label role's 9px floor on a phone-width card.
 */
export function SignupTrendChart({ buckets }: SignupTrendChartProps) {
  const chart = useMemo(() => {
    // Parse as UTC midnight so the axis labels match the backend's UTC calendar
    // days rather than shifting a day in a behind-UTC timezone.
    const points = buckets.map((bucket) => ({
      date: new Date(`${bucket.day}T00:00:00Z`),
      count: bucket.count,
    }));
    if (points.length === 0) return null;

    const x = scaleUtc()
      .domain(extent(points, (point) => point.date) as [Date, Date])
      .range([0, INNER_WIDTH]);
    // A single day gives a degenerate domain; d3 maps it to the middle of the
    // range, which is where we want the lone marker anyway.
    const peak = max(points, (point) => point.count) ?? 0;
    const y = scaleLinear()
      .domain([0, Math.max(peak, 1)])
      .range([INNER_HEIGHT, 0]);

    const path = line<(typeof points)[number]>()
      .x((point) => x(point.date))
      .y((point) => y(point.count))(points);

    return {
      points,
      peak,
      path,
      total: points.reduce((sum, point) => sum + point.count, 0),
      peakY: y(peak),
      first: points[0],
      last: points[points.length - 1],
      markerX: x(points[0].date),
      markerY: y(points[0].count),
    };
  }, [buckets]);

  if (!chart) {
    return <p className="font-mono text-[13px] font-light text-muted">no signups to chart yet.</p>;
  }

  const { points, peak, path, total, peakY, first, last, markerX, markerY } = chart;
  const single = points.length === 1;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        className="block h-auto w-full"
        role="img"
        aria-label={`daily signups from ${formatDay(first.date)} to ${formatDay(last.date)}: ${total} total, ${peak} on the busiest day.`}
      >
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          <line
            x1={0}
            y1={INNER_HEIGHT}
            x2={INNER_WIDTH}
            y2={INNER_HEIGHT}
            className="stroke-border"
            strokeWidth={1}
          />

          {/* d3.line on a single point emits a bare moveto and draws nothing, so a
              one-day window gets a dot instead of an invisible line. */}
          {single ? (
            <circle cx={markerX} cy={markerY} r={2.5} className="fill-sage" />
          ) : (
            <path
              d={path ?? undefined}
              fill="none"
              className="stroke-sage"
              strokeWidth={1.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}
        </g>
      </svg>

      {/* Zero always anchors the scale; the peak label is suppressed when the
          window is all zeros, since it would sit on top of the zero label. */}
      <span
        className={`${TICK_CLASS} -translate-y-1/2`}
        style={{ top: pctY(INNER_HEIGHT), right: VALUE_TICK_RIGHT }}
      >
        0
      </span>
      {peak > 0 ? (
        <span
          className={`${TICK_CLASS} -translate-y-1/2`}
          style={{ top: pctY(peakY), right: VALUE_TICK_RIGHT }}
        >
          {peak}
        </span>
      ) : null}

      {/* Date ticks sit on the wrapper's bottom edge — the viewBox's bottom
          margin reserves that band, so they never overrun the chart. */}
      {single ? (
        <span className={`${TICK_CLASS} bottom-0 -translate-x-1/2`} style={{ left: pctX(markerX) }}>
          {formatDay(first.date)}
        </span>
      ) : (
        <>
          <span className={`${TICK_CLASS} bottom-0`} style={{ left: pctX(0) }}>
            {formatDay(first.date)}
          </span>
          <span
            className={`${TICK_CLASS} bottom-0 -translate-x-full`}
            style={{ left: pctX(INNER_WIDTH) }}
          >
            {formatDay(last.date)}
          </span>
        </>
      )}
    </div>
  );
}
