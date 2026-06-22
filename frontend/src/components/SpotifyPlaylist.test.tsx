import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SpotifyPlaylist } from "./SpotifyPlaylist";
import {
  ApiError,
  connectSpotify,
  createSpotifyPlaylist,
  getSpotifyStatus,
} from "../services/api";

vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    getSpotifyStatus: vi.fn(),
    connectSpotify: vi.fn(),
    createSpotifyPlaylist: vi.fn(),
  };
});

const mockStatus = vi.mocked(getSpotifyStatus);
const mockConnect = vi.mocked(connectSpotify);
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

  it("offers to connect when configured but not connected, and redirects to consent", async () => {
    mockStatus.mockResolvedValue({ configured: true, connected: false });
    mockConnect.mockResolvedValue({ authorize_url: "https://accounts.spotify.com/authorize?x=1" });
    const assign = vi.fn();
    vi.stubGlobal("location", { assign });

    render(<SpotifyPlaylist roundId="r1" entryCount={3} />);
    const button = await screen.findByRole("button", { name: /connect spotify/i });
    await userEvent.click(button);

    expect(mockConnect).toHaveBeenCalled();
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("https://accounts.spotify.com/authorize?x=1"),
    );
  });

  it("creates a playlist and shows the link plus matched/unmatched counts", async () => {
    mockStatus.mockResolvedValue({ configured: true, connected: true });
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
