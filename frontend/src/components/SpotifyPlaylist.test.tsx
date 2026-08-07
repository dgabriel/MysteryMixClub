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
      overflow_youtube_url: null,
      status: "complete",
    });

    render(<SpotifyPlaylist mixId="r1" />);

    const link = await screen.findByRole("link", { name: /open playlist in spotify/i });
    expect(link).toHaveAttribute("href", "https://open.spotify.com/playlist/pl1");
  });

  it("shows a quiet note when no playlist has been generated yet (status null — MYS-258)", async () => {
    mockGetLink.mockResolvedValue({
      playlist_url: null,
      unmatched: [],
      overflow_youtube_url: null,
      status: null,
    });

    render(<SpotifyPlaylist mixId="r1" />);

    await waitFor(() => expect(mockGetLink).toHaveBeenCalledWith("r1"));
    expect(await screen.findByText(/no spotify playlist yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows a quiet note (not an error state) when the job failed (MYS-258)", async () => {
    // Matches this component's existing no-error-state philosophy: a failed
    // background job degrades to the same "not yet" note as no job at all.
    mockGetLink.mockResolvedValue({
      playlist_url: null,
      unmatched: [],
      overflow_youtube_url: null,
      status: "failed",
    });

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

  describe("unmatched tracks (MYS-201/GH-232)", () => {
    it("renders the singular summary line and list item for exactly one unmatched track", async () => {
      mockGetLink.mockResolvedValue({
        playlist_url: null,
        overflow_youtube_url: null,
        status: null,
        unmatched: [
          {
            submission_id: "s1",
            title: "Song One",
            artist: "Artist One",
            reason: "no_catalog_match",
            source: null,
            source_url: null,
          },
        ],
      });

      render(<SpotifyPlaylist mixId="r1" />);

      expect(
        await screen.findByText(/1 song didn't make the spotify playlist:/i),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Song One by Artist One \(not found on spotify\)/),
      ).toBeInTheDocument();
    });

    it("renders the plural summary line for two or more unmatched tracks", async () => {
      mockGetLink.mockResolvedValue({
        playlist_url: null,
        overflow_youtube_url: null,
        status: null,
        unmatched: [
          {
            submission_id: "s1",
            title: "Song One",
            artist: "Artist One",
            reason: "no_catalog_match",
            source: null,
            source_url: null,
          },
          {
            submission_id: "s2",
            title: "Song Two",
            artist: "Artist Two",
            reason: "source_only",
            source: "youtube",
            source_url: "https://youtube.com/watch?v=abc123",
          },
        ],
      });

      render(<SpotifyPlaylist mixId="r1" />);

      expect(
        await screen.findByText(/2 songs didn't make the spotify playlist:/i),
      ).toBeInTheDocument();
    });

    it("renders a listen-on link with the correct href for a source_only track", async () => {
      mockGetLink.mockResolvedValue({
        playlist_url: null,
        overflow_youtube_url: null,
        status: null,
        unmatched: [
          {
            submission_id: "s2",
            title: "Song Two",
            artist: "Artist Two",
            reason: "source_only",
            source: "youtube",
            source_url: "https://youtube.com/watch?v=abc123",
          },
        ],
      });

      render(<SpotifyPlaylist mixId="r1" />);

      expect(
        await screen.findByText(/Song Two by Artist Two \(not on spotify,/),
      ).toBeInTheDocument();
      const link = screen.getByRole("link", { name: /listen on youtube/i });
      expect(link).toHaveAttribute("href", "https://youtube.com/watch?v=abc123");
    });

    it("does not render a listen-on link for a no_catalog_match track with no source_url", async () => {
      mockGetLink.mockResolvedValue({
        playlist_url: null,
        overflow_youtube_url: null,
        status: null,
        unmatched: [
          {
            submission_id: "s1",
            title: "Song One",
            artist: "Artist One",
            reason: "no_catalog_match",
            source: null,
            source_url: null,
          },
        ],
      });

      render(<SpotifyPlaylist mixId="r1" />);

      expect(
        await screen.findByText(/Song One by Artist One \(not found on spotify\)/),
      ).toBeInTheDocument();
      expect(screen.queryByText(/listen on/i)).not.toBeInTheDocument();
      expect(screen.queryByRole("link")).not.toBeInTheDocument();
    });

    it("still renders the unmatched list when a playlist_url is already present", async () => {
      mockGetLink.mockResolvedValue({
        playlist_url: "https://open.spotify.com/playlist/pl1",
        overflow_youtube_url: null,
        status: "complete",
        unmatched: [
          {
            submission_id: "s1",
            title: "Song One",
            artist: "Artist One",
            reason: "no_catalog_match",
            source: null,
            source_url: null,
          },
        ],
      });

      render(<SpotifyPlaylist mixId="r1" />);

      const playlistLink = await screen.findByRole("link", { name: /open playlist in spotify/i });
      expect(playlistLink).toHaveAttribute("href", "https://open.spotify.com/playlist/pl1");
      expect(
        await screen.findByText(/1 song didn't make the spotify playlist:/i),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Song One by Artist One \(not found on spotify\)/),
      ).toBeInTheDocument();
    });

    it("renders the 'hear the rest on youtube' link when overflow_youtube_url is present alongside unmatched tracks", async () => {
      mockGetLink.mockResolvedValue({
        playlist_url: "https://open.spotify.com/playlist/pl1",
        overflow_youtube_url: "https://www.youtube.com/watch_videos?video_ids=abc123",
        status: "complete",
        unmatched: [
          {
            submission_id: "s1",
            title: "Song One",
            artist: "Artist One",
            reason: "no_catalog_match",
            source: null,
            source_url: null,
          },
        ],
      });

      render(<SpotifyPlaylist mixId="r1" />);

      const overflowLink = await screen.findByRole("link", { name: /hear the rest on youtube/i });
      expect(overflowLink).toHaveAttribute(
        "href",
        "https://www.youtube.com/watch_videos?video_ids=abc123",
      );
    });

    it("does not render the 'hear the rest on youtube' link when overflow_youtube_url is null", async () => {
      mockGetLink.mockResolvedValue({
        playlist_url: "https://open.spotify.com/playlist/pl1",
        overflow_youtube_url: null,
        status: "complete",
        unmatched: [
          {
            submission_id: "s1",
            title: "Song One",
            artist: "Artist One",
            reason: "no_catalog_match",
            source: null,
            source_url: null,
          },
        ],
      });

      render(<SpotifyPlaylist mixId="r1" />);

      await screen.findByText(/1 song didn't make the spotify playlist:/i);
      expect(
        screen.queryByRole("link", { name: /hear the rest on youtube/i }),
      ).not.toBeInTheDocument();
    });
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
      mockGetLink.mockResolvedValue({
        playlist_url: null,
        unmatched: [],
        overflow_youtube_url: null,
        status: "queued",
      });

      render(<SpotifyPlaylist mixId="r1" />);

      expect(await screen.findByText(/generating spotify playlist/i)).toBeInTheDocument();
      expect(screen.queryByRole("link")).not.toBeInTheDocument();
      expect(screen.queryByText(/no spotify playlist yet/i)).not.toBeInTheDocument();
    });

    it("polls again and swaps in the link once the job completes", async () => {
      mockGetLink
        .mockResolvedValueOnce({
          playlist_url: null,
          unmatched: [],
          overflow_youtube_url: null,
          status: "queued",
        })
        .mockResolvedValueOnce({
          playlist_url: "https://open.spotify.com/playlist/pl1",
          unmatched: [],
          overflow_youtube_url: null,
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
        .mockResolvedValueOnce({
          playlist_url: null,
          unmatched: [],
          overflow_youtube_url: null,
          status: "running",
        })
        .mockResolvedValueOnce({
          playlist_url: null,
          unmatched: [],
          overflow_youtube_url: null,
          status: "failed",
        });

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
      mockGetLink.mockResolvedValue({
        playlist_url: null,
        unmatched: [],
        overflow_youtube_url: null,
        status: "queued",
      });

      const { unmount } = render(<SpotifyPlaylist mixId="r1" />);
      await screen.findByText(/generating spotify playlist/i);

      unmount();

      expect(clearTimeoutSpy).toHaveBeenCalled();
    });
  });
});
