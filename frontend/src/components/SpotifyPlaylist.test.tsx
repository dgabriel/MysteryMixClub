import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { SpotifyPlaylist } from "./SpotifyPlaylist";
import { getSpotifyPlaylistLink } from "../services/api";

vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    getSpotifyPlaylistLink: vi.fn(),
  };
});

const mockGetLink = vi.mocked(getSpotifyPlaylistLink);

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SpotifyPlaylist", () => {
  it("shows the link once an admin has generated a playlist", async () => {
    mockGetLink.mockResolvedValue({
      playlist_url: "https://open.spotify.com/playlist/pl1",
      unmatched: [],
      status: "complete",
    });

    render(<SpotifyPlaylist mixId="r1" />);

    const link = await screen.findByRole("link", { name: /open playlist in spotify/i });
    expect(link).toHaveAttribute("href", "https://open.spotify.com/playlist/pl1");
  });

  it("shows a quiet note when no playlist has been generated yet (status null — MYS-258)", async () => {
    mockGetLink.mockResolvedValue({ playlist_url: null, unmatched: [], status: null });

    render(<SpotifyPlaylist mixId="r1" />);

    await waitFor(() => expect(mockGetLink).toHaveBeenCalledWith("r1"));
    expect(await screen.findByText(/no spotify playlist yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows a quiet note (not an error state) when the job failed (MYS-258)", async () => {
    // Matches this component's existing no-error-state philosophy: a failed
    // background job degrades to the same "not yet" note as no job at all.
    mockGetLink.mockResolvedValue({ playlist_url: null, unmatched: [], status: "failed" });

    render(<SpotifyPlaylist mixId="r1" />);

    expect(await screen.findByText(/no spotify playlist yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/generating/i)).not.toBeInTheDocument();
  });

  it("degrades to the quiet note when the fetch fails", async () => {
    mockGetLink.mockRejectedValue(new Error("network error"));

    render(<SpotifyPlaylist mixId="r1" />);

    expect(await screen.findByText(/no spotify playlist yet/i)).toBeInTheDocument();
  });

  it("renders nothing while the link is still loading", () => {
    mockGetLink.mockReturnValue(new Promise(() => {})); // never resolves

    const { container } = render(<SpotifyPlaylist mixId="r1" />);

    expect(container).toBeEmptyDOMElement();
  });

  describe("polling while a job is queued/running (MYS-258, ADR 0006)", () => {
    beforeEach(() => {
      // shouldAdvanceTime: findByText/waitFor poll via real setTimeout under
      // the hood; without this, fake timers never let that polling progress
      // and every findByText call in this block hangs until vitest's own
      // (real) test timeout.
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("shows a generating note while the job is queued, with no link yet", async () => {
      mockGetLink.mockResolvedValue({ playlist_url: null, unmatched: [], status: "queued" });

      render(<SpotifyPlaylist mixId="r1" />);

      expect(await screen.findByText(/generating spotify playlist/i)).toBeInTheDocument();
      expect(screen.queryByRole("link")).not.toBeInTheDocument();
      expect(screen.queryByText(/no spotify playlist yet/i)).not.toBeInTheDocument();
    });

    it("polls again and swaps in the link once the job completes", async () => {
      mockGetLink
        .mockResolvedValueOnce({ playlist_url: null, unmatched: [], status: "queued" })
        .mockResolvedValueOnce({
          playlist_url: "https://open.spotify.com/playlist/pl1",
          unmatched: [],
          status: "complete",
        });

      render(<SpotifyPlaylist mixId="r1" />);
      expect(await screen.findByText(/generating spotify playlist/i)).toBeInTheDocument();
      expect(mockGetLink).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(7000);
      });

      expect(mockGetLink).toHaveBeenCalledTimes(2);
      const link = await screen.findByRole("link", { name: /open playlist in spotify/i });
      expect(link).toHaveAttribute("href", "https://open.spotify.com/playlist/pl1");
    });

    it("stops polling once the job reaches a terminal status", async () => {
      mockGetLink
        .mockResolvedValueOnce({ playlist_url: null, unmatched: [], status: "running" })
        .mockResolvedValueOnce({ playlist_url: null, unmatched: [], status: "failed" });

      render(<SpotifyPlaylist mixId="r1" />);
      expect(await screen.findByText(/generating spotify playlist/i)).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(7000);
      });
      expect(mockGetLink).toHaveBeenCalledTimes(2);
      expect(await screen.findByText(/no spotify playlist yet/i)).toBeInTheDocument();

      // No further calls scheduled — failed is terminal.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(mockGetLink).toHaveBeenCalledTimes(2);
    });

    it("clears the poll timer on unmount (no state update after unmount)", async () => {
      const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout");
      mockGetLink.mockResolvedValue({ playlist_url: null, unmatched: [], status: "queued" });

      const { unmount } = render(<SpotifyPlaylist mixId="r1" />);
      await screen.findByText(/generating spotify playlist/i);

      unmount();

      expect(clearTimeoutSpy).toHaveBeenCalled();
    });
  });
});
