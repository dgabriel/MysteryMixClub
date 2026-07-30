import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SignupTrendChart } from "./SignupTrendChart";
import type { SignupBucket } from "../services/api";

/** N consecutive UTC days from 2026-07-01, counts supplied per day. */
function window(counts: number[]): SignupBucket[] {
  return counts.map((count, i) => ({
    day: new Date(Date.UTC(2026, 6, 1 + i)).toISOString().slice(0, 10),
    count,
  }));
}

/** A realistic 30-day window: mostly quiet, a few bursts, a clear peak of 12. */
const THIRTY_DAYS = window([
  0, 2, 0, 0, 5, 1, 0, 0, 0, 3, 12, 4, 0, 0, 1, 0, 0, 6, 2, 0, 0, 0, 0, 9, 3, 0, 1, 0, 0, 7,
]);
const THIRTY_DAY_TOTAL = 56;

function svg(container: HTMLElement): SVGSVGElement | null {
  return container.querySelector("svg");
}

/** Tick labels are HTML spans over the SVG — the component renders no other span. */
function ticks(container: HTMLElement): HTMLSpanElement[] {
  return Array.from(container.querySelectorAll("span"));
}

describe("SignupTrendChart", () => {
  describe("no data", () => {
    it("says so in words and draws nothing", () => {
      const { container } = render(<SignupTrendChart buckets={[]} />);

      expect(screen.getByText("no signups to chart yet.")).toBeInTheDocument();
      expect(svg(container)).toBeNull();
      expect(container.querySelector("path")).toBeNull();
      expect(screen.queryByRole("img")).not.toBeInTheDocument();
    });
  });

  describe("a single day", () => {
    it("draws a dot rather than a zero-length line", () => {
      const { container } = render(<SignupTrendChart buckets={window([4])} />);

      // d3.line() on one point emits only a moveto, so a path would be invisible.
      expect(container.querySelector("circle")).not.toBeNull();
      expect(container.querySelector("path")).toBeNull();
    });

    it("labels itself with that day on both ends of the range", () => {
      render(<SignupTrendChart buckets={window([4])} />);

      expect(screen.getByRole("img")).toHaveAccessibleName(
        "daily signups from Jul 1 to Jul 1: 4 total, 4 on the busiest day.",
      );
    });

    it("prints one x tick, not a duplicated first/last pair", () => {
      render(<SignupTrendChart buckets={window([4])} />);

      const dates = screen.getAllByText("Jul 1");
      expect(dates).toHaveLength(1);
      expect(dates[0].tagName.toLowerCase()).toBe("span");
    });

    it("centres that lone date tick over the marker", () => {
      render(<SignupTrendChart buckets={window([4])} />);

      // One day is a degenerate domain, so d3 parks the marker mid-range.
      const tick = screen.getByText("Jul 1");
      expect(parseFloat(tick.style.left)).toBeCloseTo(53.5);
      expect(tick.className).toContain("-translate-x-1/2");
    });
  });

  describe("a full window", () => {
    it("is exposed as one image with the totals in its label", () => {
      render(<SignupTrendChart buckets={THIRTY_DAYS} />);

      const chart = screen.getByRole("img");
      expect(chart.tagName.toLowerCase()).toBe("svg");
      expect(chart).toHaveAccessibleName(
        `daily signups from Jul 1 to Jul 30: ${THIRTY_DAY_TOTAL} total, 12 on the busiest day.`,
      );
    });

    it("draws a line through every day, with no per-point dots", () => {
      const { container } = render(<SignupTrendChart buckets={THIRTY_DAYS} />);

      const path = container.querySelector("path");
      expect(path).not.toBeNull();
      expect(container.querySelectorAll("circle")).toHaveLength(0);

      // One M plus 29 L commands — a vertex per day, nothing dropped or doubled.
      const d = path?.getAttribute("d") ?? "";
      expect(d.match(/[ML]/g)).toHaveLength(THIRTY_DAYS.length);
      expect(d.startsWith("M")).toBe(true);
    });

    it("anchors the y axis at zero and ticks the peak", () => {
      render(<SignupTrendChart buckets={THIRTY_DAYS} />);

      expect(screen.getByText("0")).toBeInTheDocument();
      expect(screen.getByText("12")).toBeInTheDocument();
    });

    it("dates the x axis from the first and last bucket", () => {
      render(<SignupTrendChart buckets={THIRTY_DAYS} />);

      expect(screen.getByText("Jul 1")).toBeInTheDocument();
      expect(screen.getByText("Jul 30")).toBeInTheDocument();
    });

    it("labels the axes with exactly four ticks — zero, peak, first day, last day", () => {
      const { container } = render(<SignupTrendChart buckets={THIRTY_DAYS} />);

      expect(ticks(container).map((tick) => tick.textContent)).toEqual([
        "0",
        "12",
        "Jul 1",
        "Jul 30",
      ]);
    });

    it("stacks the value ticks in the left gutter, peak above zero", () => {
      render(<SignupTrendChart buckets={THIRTY_DAYS} />);

      const zero = screen.getByText("0");
      const peak = screen.getByText("12");
      for (const tick of [zero, peak]) {
        // Positioned as a share of the wrapper, so they track the scaled marks.
        expect(tick.style.top).toMatch(/^[\d.]+%$/);
        expect(tick.style.right).toMatch(/^[\d.]+%$/);
        expect(tick.getAttribute("x")).toBeNull();
        expect(tick.getAttribute("y")).toBeNull();
      }
      expect(parseFloat(peak.style.top)).toBeLessThan(parseFloat(zero.style.top));
    });

    it("pins the date ticks to each end of the plot area", () => {
      render(<SignupTrendChart buckets={THIRTY_DAYS} />);

      const firstDay = screen.getByText("Jul 1");
      const lastDay = screen.getByText("Jul 30");
      expect(parseFloat(firstDay.style.left)).toBeCloseTo(8.5);
      expect(parseFloat(lastDay.style.left)).toBeCloseTo(98.5);
      // Right-hand tick is pulled back inside the plot so it can't overrun.
      expect(lastDay.className).toContain("-translate-x-full");
      for (const tick of [firstDay, lastDay]) {
        expect(tick.className).toContain("bottom-0");
        expect(tick.getAttribute("x")).toBeNull();
      }
    });

    it("reads the day strings as UTC, not local time", () => {
      // A behind-UTC local timezone would shift "2026-07-01" back to Jun 30.
      render(<SignupTrendChart buckets={window([1, 2])} />);

      expect(screen.getByText("Jul 1")).toBeInTheDocument();
      expect(screen.queryByText("Jun 30")).not.toBeInTheDocument();
    });
  });

  describe("an all-zero window", () => {
    const flat = window(Array(30).fill(0));

    it("charts real zeros instead of falling back to the empty state", () => {
      const { container } = render(<SignupTrendChart buckets={flat} />);

      expect(screen.queryByText("no signups to chart yet.")).not.toBeInTheDocument();
      expect(container.querySelector("path")).not.toBeNull();
    });

    it("draws that line flat along the baseline", () => {
      const { container } = render(<SignupTrendChart buckets={flat} />);

      const d = container.querySelector("path")?.getAttribute("d") ?? "";
      const ys = Array.from(d.matchAll(/[ML]([-\d.]+),([-\d.]+)/g)).map((m) => m[2]);
      expect(ys).toHaveLength(flat.length);
      expect(new Set(ys).size).toBe(1);
    });

    it("shows a single zero tick — no peak label stacked on top of it", () => {
      const { container } = render(<SignupTrendChart buckets={flat} />);

      const zeros = screen.getAllByText("0");
      expect(zeros).toHaveLength(1);
      expect(zeros[0].tagName.toLowerCase()).toBe("span");
      // Zero plus the two date ticks — the peak tick is suppressed entirely.
      expect(ticks(container)).toHaveLength(3);
    });
  });

  describe("style guide", () => {
    it("spends no Rust and no Gold — nothing here is a signal or an award", () => {
      const { container } = render(<SignupTrendChart buckets={THIRTY_DAYS} />);

      expect(container.innerHTML).not.toMatch(/rust|gold/i);
    });

    it("draws the series in Sage and the baseline in Border", () => {
      const { container } = render(<SignupTrendChart buckets={THIRTY_DAYS} />);

      expect(container.querySelector("path")?.getAttribute("class")).toContain("stroke-sage");
      expect(container.querySelector("line")?.getAttribute("class")).toContain("stroke-border");
    });

    it("sets tick labels in the mono face at the muted weight", () => {
      const { container } = render(<SignupTrendChart buckets={THIRTY_DAYS} />);

      const labels = ticks(container);
      expect(labels.length).toBeGreaterThan(0);
      for (const tick of labels) {
        expect(tick.className).toContain("font-mono");
        expect(tick.className).toContain("text-muted");
      }
    });

    it("keeps the tick labels at a fixed 11px instead of scaling them", () => {
      const { container } = render(<SignupTrendChart buckets={THIRTY_DAYS} />);

      // The whole point of hoisting ticks out of the SVG: viewBox scaling can't
      // shrink them under the Label role's 9px floor on a phone-width card.
      for (const tick of ticks(container)) {
        expect(tick.className).toContain("text-[11px]");
      }
    });

    it("keeps every tick out of the SVG so none of them scale with the viewBox", () => {
      const { container } = render(<SignupTrendChart buckets={THIRTY_DAYS} />);

      expect(svg(container)?.querySelectorAll("text")).toHaveLength(0);
      expect(svg(container)?.querySelectorAll("span")).toHaveLength(0);
      expect(container.querySelectorAll("text")).toHaveLength(0);
      expect(ticks(container).length).toBeGreaterThan(0);
    });

    it("scales to its container rather than to a fixed pixel size", () => {
      const { container } = render(<SignupTrendChart buckets={THIRTY_DAYS} />);

      const chart = svg(container);
      expect(chart?.getAttribute("viewBox")).toBe("0 0 400 150");
      expect(chart?.getAttribute("width")).toBeNull();
      expect(chart?.getAttribute("class")).toContain("w-full");
    });
  });

  describe("odd input", () => {
    it("survives a window where the peak is the only nonzero day", () => {
      render(<SignupTrendChart buckets={window([0, 0, 0, 1, 0])} />);

      expect(screen.getByRole("img")).toHaveAccessibleName(/1 total, 1 on the busiest day/);
    });

    it("handles a large single-day spike without collapsing the scale", () => {
      const { container } = render(<SignupTrendChart buckets={window([0, 9999, 0])} />);

      expect(screen.getByText("9999")).toBeInTheDocument();
      const d = container.querySelector("path")?.getAttribute("d") ?? "";
      expect(d).not.toMatch(/NaN/);
    });

    it("never emits NaN coordinates for a realistic window", () => {
      const { container } = render(<SignupTrendChart buckets={THIRTY_DAYS} />);

      expect(container.querySelector("path")?.getAttribute("d")).not.toMatch(/NaN/);
    });
  });
});
