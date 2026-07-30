import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AdminMetricsRoute } from "./AdminMetricsRoute";
import { ApiError, adminGetMetrics } from "../services/api";
import type { AdminMetrics } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock the API module (no network). Keep ApiError real.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    adminGetMetrics: vi.fn(),
  };
});

vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockGetMetrics = vi.mocked(adminGetMetrics);
const mockUseAuth = vi.mocked(useAuth);

function setAuth(isPlatformAdmin: boolean) {
  mockUseAuth.mockReturnValue({
    status: "authenticated",
    isAuthenticated: true,
    setAccessToken: vi.fn(),
    clear: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
    displayName: "Ada",
    email: "ada@example.com",
    userId: "admin-1",
    isPlatformAdmin,
    profileStatus: "ready",
    needsOnboarding: false,
    applyDisplayName: vi.fn(),
    preferredService: null,
    tosAccepted: true,
    applyTosAccepted: vi.fn(),
  });
}

/** Every field distinct so an assertion can't pass on a neighbour's value.
 *  `avg_submissions_per_mix` is deliberately un-round to pin the toFixed(1). */
const snapshot: AdminMetrics = {
  total_users: 101,
  total_clubs: 102,
  active_clubs: 103,
  complete_clubs: 104,
  total_mixes: 205,
  pending_mixes: 206,
  open_submission_mixes: 207,
  open_voting_mixes: 208,
  closed_mixes: 209,
  total_submissions: 310,
  avg_submissions_per_mix: 2.46,
  total_votes: 311,
  total_notes: 312,
  waitlist_total: 413,
  waitlist_pending: 414,
  waitlist_invited: 415,
};

function renderMetrics() {
  return render(
    <MemoryRouter initialEntries={["/admin/metrics"]}>
      <Routes>
        <Route path="/admin/metrics" element={<AdminMetricsRoute />} />
        <Route path="/home" element={<div>HOME CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

/** The <section> wrapping a stat group, found by its h2 — labels repeat across
 *  groups ("pending" is both a mix state and a waitlist state). */
function group(title: string): HTMLElement {
  return screen.getByRole("heading", { level: 2, name: title }).closest("section") as HTMLElement;
}

/** The <dd> paired with the <dt> carrying `label` — asserts the value is
 *  attached to the right label, not merely present somewhere on the page. */
function statValue(groupTitle: string, label: string): string {
  const dt = within(group(groupTitle)).getByText(label);
  expect(dt.tagName).toBe("DT");
  const dd = dt.parentElement?.querySelector("dd");
  expect(dd, `no <dd> paired with <dt>${label}</dt>`).not.toBeNull();
  return dd?.textContent ?? "";
}

describe("AdminMetricsRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setAuth(true);
    mockGetMetrics.mockResolvedValue(snapshot);
  });

  it("non-admin: redirects to /home, never renders the page, never calls the API", () => {
    setAuth(false);
    renderMetrics();

    expect(screen.getByText("HOME CONTENT")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1, name: "metrics" })).not.toBeInTheDocument();
    expect(mockGetMetrics).not.toHaveBeenCalled();
  });

  it("admin: fetches the snapshot exactly once", async () => {
    renderMetrics();

    await screen.findByRole("heading", { level: 1, name: "metrics" });
    expect(mockGetMetrics).toHaveBeenCalledTimes(1);
  });

  describe("successful fetch", () => {
    it("renders every users-and-clubs count against its own label", async () => {
      renderMetrics();
      await screen.findByRole("heading", { level: 1, name: "metrics" });

      expect(statValue("users and clubs", "users")).toBe("101");
      expect(statValue("users and clubs", "clubs")).toBe("102");
      expect(statValue("users and clubs", "active clubs")).toBe("103");
      expect(statValue("users and clubs", "complete clubs")).toBe("104");
    });

    it("renders every mystery-mix count against its own label", async () => {
      renderMetrics();
      await screen.findByRole("heading", { level: 1, name: "metrics" });

      expect(statValue("mystery mixes", "mixes")).toBe("205");
      expect(statValue("mystery mixes", "pending")).toBe("206");
      expect(statValue("mystery mixes", "open for submissions")).toBe("207");
      expect(statValue("mystery mixes", "open for voting")).toBe("208");
      expect(statValue("mystery mixes", "closed")).toBe("209");
    });

    it("renders every submissions-and-engagement count, averaging to one decimal", async () => {
      renderMetrics();
      await screen.findByRole("heading", { level: 1, name: "metrics" });

      expect(statValue("submissions and engagement", "submissions")).toBe("310");
      expect(statValue("submissions and engagement", "avg per mix with submissions")).toBe("2.5");
      expect(statValue("submissions and engagement", "votes")).toBe("311");
      expect(statValue("submissions and engagement", "notes")).toBe("312");
    });

    it("renders every waitlist count against its own label", async () => {
      renderMetrics();
      await screen.findByRole("heading", { level: 1, name: "metrics" });

      expect(statValue("waitlist", "on the waitlist")).toBe("413");
      expect(statValue("waitlist", "pending")).toBe("414");
      expect(statValue("waitlist", "invited")).toBe("415");
    });

    it("shows a zeroed snapshot as real zeros, not as an error or a blank", async () => {
      const zeros = Object.fromEntries(
        Object.keys(snapshot).map((k) => [k, 0]),
      ) as unknown as AdminMetrics;
      mockGetMetrics.mockResolvedValue(zeros);

      renderMetrics();
      await screen.findByRole("heading", { level: 1, name: "metrics" });

      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(statValue("users and clubs", "users")).toBe("0");
      expect(statValue("submissions and engagement", "avg per mix with submissions")).toBe("0.0");
      expect(statValue("waitlist", "invited")).toBe("0");
    });

    it("renders no Rust anywhere — nothing on this page is a signal", async () => {
      const { container } = renderMetrics();
      await screen.findByRole("heading", { level: 1, name: "metrics" });

      expect(container.innerHTML).not.toMatch(/rust/i);
    });
  });

  describe("loading", () => {
    it("shows the spinning motif and no stats while the fetch is in flight", () => {
      mockGetMetrics.mockReturnValue(new Promise<AdminMetrics>(() => {}));

      const { container } = renderMetrics();

      expect(container.querySelector(".animate-rotate-rings")).not.toBeNull();
      expect(screen.queryByRole("heading", { level: 1, name: "metrics" })).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("clears the motif once the snapshot arrives", async () => {
      let resolve!: (m: AdminMetrics) => void;
      mockGetMetrics.mockReturnValue(
        new Promise<AdminMetrics>((r) => {
          resolve = r;
        }),
      );

      const { container } = renderMetrics();
      expect(container.querySelector(".animate-rotate-rings")).not.toBeNull();

      resolve(snapshot);

      await screen.findByRole("heading", { level: 1, name: "metrics" });
      expect(container.querySelector(".animate-rotate-rings")).toBeNull();
    });
  });

  describe("error", () => {
    it("surfaces the backend's message in an alert and renders no stats", async () => {
      mockGetMetrics.mockRejectedValue(new ApiError(403, "not authorized"));

      renderMetrics();

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(/not authorized/i);
      expect(screen.queryByRole("heading", { level: 2, name: "waitlist" })).not.toBeInTheDocument();
      // The page frame stays — the user isn't dumped onto a blank screen.
      expect(screen.getByRole("heading", { level: 1, name: "metrics" })).toBeInTheDocument();
    });

    it("falls back to a calm message when the failure isn't an ApiError", async () => {
      mockGetMetrics.mockRejectedValue(new TypeError("Failed to fetch"));

      renderMetrics();

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(/couldn't load the metrics/i);
      expect(alert).not.toHaveTextContent(/failed to fetch/i);
    });

    it("a 500 shows the alert rather than leaving the motif spinning forever", async () => {
      mockGetMetrics.mockRejectedValue(new ApiError(500, "internal server error"));

      const { container } = renderMetrics();

      await screen.findByRole("alert");
      expect(container.querySelector(".animate-rotate-rings")).toBeNull();
    });
  });

  describe("accessibility", () => {
    it("has one main landmark, one h1, and four h2 groups in reading order", async () => {
      renderMetrics();
      await screen.findByRole("heading", { level: 1, name: "metrics" });

      expect(screen.getAllByRole("main")).toHaveLength(1);
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
        "users and clubs",
        "mystery mixes",
        "submissions and engagement",
        "waitlist",
      ]);
    });

    it("pairs every dt with exactly one dd inside a dl", async () => {
      const { container } = renderMetrics();
      await screen.findByRole("heading", { level: 1, name: "metrics" });

      const lists = Array.from(container.querySelectorAll("dl"));
      expect(lists).toHaveLength(4);

      for (const dl of lists) {
        const terms = dl.querySelectorAll("dt");
        const details = dl.querySelectorAll("dd");
        expect(terms.length).toBe(details.length);
        expect(terms.length).toBeGreaterThan(0);
        for (const dt of Array.from(terms)) {
          expect(dt.parentElement?.querySelectorAll("dd")).toHaveLength(1);
        }
      }

      // All 16 stats are accounted for across the four lists.
      expect(container.querySelectorAll("dd")).toHaveLength(16);
    });

    it("announces the failure as an alert, not as ordinary body copy", async () => {
      mockGetMetrics.mockRejectedValue(new ApiError(403, "not authorized"));

      renderMetrics();

      await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(1));
    });
  });
});
