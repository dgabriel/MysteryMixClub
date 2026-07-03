import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
    mockGetLink.mockResolvedValue({ playlist_url: "https://open.spotify.com/playlist/pl1" });

    render(<SpotifyPlaylist roundId="r1" />);

    const link = await screen.findByRole("link", { name: /open playlist in spotify/i });
    expect(link).toHaveAttribute("href", "https://open.spotify.com/playlist/pl1");
  });

  it("shows a quiet note when no playlist has been generated yet", async () => {
    mockGetLink.mockResolvedValue({ playlist_url: null });

    render(<SpotifyPlaylist roundId="r1" />);

    await waitFor(() => expect(mockGetLink).toHaveBeenCalledWith("r1"));
    expect(await screen.findByText(/no spotify playlist yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("degrades to the quiet note when the fetch fails", async () => {
    mockGetLink.mockRejectedValue(new Error("network error"));

    render(<SpotifyPlaylist roundId="r1" />);

    expect(await screen.findByText(/no spotify playlist yet/i)).toBeInTheDocument();
  });

  it("renders nothing while the link is still loading", () => {
    mockGetLink.mockReturnValue(new Promise(() => {})); // never resolves

    const { container } = render(<SpotifyPlaylist roundId="r1" />);

    expect(container).toBeEmptyDOMElement();
  });
});
