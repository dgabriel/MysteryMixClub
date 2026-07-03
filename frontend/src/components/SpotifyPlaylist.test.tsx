import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SpotifyPlaylist } from "./SpotifyPlaylist";
import { ApiError, createSpotifyPlaylist, getSpotifyStatus } from "../services/api";

vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    getSpotifyStatus: vi.fn(),
    createSpotifyPlaylist: vi.fn(),
  };
});

const mockStatus = vi.mocked(getSpotifyStatus);
const mockCreate = vi.mocked(createSpotifyPlaylist);

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SpotifyPlaylist", () => {
  it("renders nothing when Spotify is not configured", async () => {
    mockStatus.mockResolvedValue({ configured: false, connected: false });
    const { container } = render(<SpotifyPlaylist roundId="r1" entryCount={3} />);
    await waitFor(() => expect(mockStatus).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when configured but the shared account isn't connected yet", async () => {
    // MYS-169: no per-member connect step — if the shared account isn't wired
    // up, the affordance stays hidden rather than showing a broken button.
    mockStatus.mockResolvedValue({ configured: true, connected: false });
    const { container } = render(<SpotifyPlaylist roundId="r1" entryCount={3} />);
    await waitFor(() => expect(mockStatus).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("creates a playlist and shows the link plus matched/unmatched counts", async () => {
    mockStatus.mockResolvedValue({ configured: true, connected: true });
    const open = vi.fn();
    vi.stubGlobal("open", open);
    mockCreate.mockResolvedValue({
      round_id: "r1",
      playlist_url: "https://open.spotify.com/playlist/pl1",
      track_count: 1,
      total_count: 2,
      unmatched: [{ submission_id: "s2", title: "miss", artist: "A" }],
    });

    render(<SpotifyPlaylist roundId="r1" entryCount={2} />);
    const button = await screen.findByRole("button", { name: /make a spotify playlist/i });
    await userEvent.click(button);

    const link = await screen.findByRole("link", { name: /open playlist in spotify/i });
    expect(link).toHaveAttribute("href", "https://open.spotify.com/playlist/pl1");
    expect(screen.getByText(/1 of 2 on Spotify/i)).toBeInTheDocument();
    expect(screen.getByText(/1 couldn't be matched/i)).toBeInTheDocument();
    // Auto-opened the new playlist (MYS-103).
    expect(open).toHaveBeenCalledWith(
      "https://open.spotify.com/playlist/pl1",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("reports when nothing matched (no playlist created)", async () => {
    mockStatus.mockResolvedValue({ configured: true, connected: true });
    mockCreate.mockResolvedValue({
      round_id: "r1",
      playlist_url: null,
      track_count: 0,
      total_count: 1,
      unmatched: [{ submission_id: "s1", title: "miss", artist: "A" }],
    });

    render(<SpotifyPlaylist roundId="r1" entryCount={1} />);
    await userEvent.click(await screen.findByRole("button", { name: /make a spotify playlist/i }));

    expect(await screen.findByText(/none of these tracks were on Spotify/i)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("surfaces the backend's calm message on failure", async () => {
    mockStatus.mockResolvedValue({ configured: true, connected: true });
    mockCreate.mockRejectedValue(
      new ApiError(409, "your spotify connection expired — reconnect and try again"),
    );

    render(<SpotifyPlaylist roundId="r1" entryCount={1} />);
    await userEvent.click(await screen.findByRole("button", { name: /make a spotify playlist/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/reconnect and try again/i);
  });
});
