import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SongSearchCard } from "./SongSearchCard";
import { ApiError, resolveSong, searchSongs } from "../../services/api";
import type { ResolvedSong, SongSearchResults } from "../../services/api";

// Mock the API module; keep ApiError real so instanceof works.
vi.mock("../../services/api", async () => {
  const actual = await vi.importActual<typeof import("../../services/api")>("../../services/api");
  return { ...actual, resolveSong: vi.fn(), searchSongs: vi.fn() };
});

const mockResolve = vi.mocked(resolveSong);
const mockSearch = vi.mocked(searchSongs);

const SONG: ResolvedSong = {
  title: "bad guy",
  artist: "Billie Eilish",
  album: "When We All Fall Asleep",
  thumbnail_url: "https://img/x.jpg",
  isrc: "USUM71900764",
  source: null,
  source_key: null,
  source_url: null,
  bandcamp_track_id: null,
  platforms: {
    spotify: "https://open.spotify.com/track/2",
    youtube: "https://youtube.com/watch?v=z",
  },
};

function searchResults(overrides: Partial<SongSearchResults> = {}): SongSearchResults {
  return {
    results: [
      {
        id: "id0",
        title: "bad guy",
        artist: "Billie Eilish",
        album: "When We All Fall Asleep",
        thumbnail_url: "https://img/s.jpg",
        isrc: "USUM71900764",
        resolve_url: "https://www.deezer.com/track/id0",
      },
    ],
    too_many_results: false,
    ...overrides,
  };
}

describe("SongSearchCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the heading and both mode tabs, with search first and selected by default", () => {
    render(<SongSearchCard />);
    expect(screen.getByText("find a song")).toBeInTheDocument();
    // Search leads now: it's the first tab and the one active on load.
    const tabs = screen.getAllByRole("tab");
    expect(tabs[0]).toHaveTextContent(/search by title/i);
    expect(tabs[1]).toHaveTextContent(/paste a link/i);
    expect(screen.getByRole("tab", { name: /search by title/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: /paste a link/i })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("resolves a pasted link and renders the result card with platform links", async () => {
    mockResolve.mockResolvedValue(SONG);
    const user = userEvent.setup();
    render(<SongSearchCard />);

    await user.click(screen.getByRole("tab", { name: /paste a link/i }));
    await user.type(
      screen.getByLabelText(/paste a link/i),
      "https://open.spotify.com/track/2",
    );
    await user.click(screen.getByRole("button", { name: /^resolve$/i }));

    expect(await screen.findByRole("heading", { name: "bad guy" })).toBeInTheDocument();
    expect(screen.getByText("Billie Eilish")).toBeInTheDocument();
    expect(screen.getByText("When We All Fall Asleep")).toBeInTheDocument();

    const spotify = screen.getByRole("link", { name: /open bad guy on Spotify/i });
    expect(spotify).toHaveAttribute("href", "https://open.spotify.com/track/2");
    expect(spotify).toHaveAttribute("target", "_blank");
    expect(spotify).toHaveAttribute("rel", expect.stringContaining("noopener"));

    // Only platforms present in the response are shown.
    expect(screen.getByRole("link", { name: /on YouTube/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /on Deezer/i })).not.toBeInTheDocument();
    expect(mockResolve).toHaveBeenCalledWith({ url: "https://open.spotify.com/track/2" });
  });

  it("hides phantom platform buttons for a source-only track (MYS-201)", async () => {
    mockResolve.mockResolvedValue({
      ...SONG,
      source: "bandcamp",
      source_key: "bandcamp:artist/track",
      source_url: "https://artist.bandcamp.com/track/track",
      platforms: {
        spotify: "https://open.spotify.com/search/bad%20guy",
        appleMusic: "https://music.apple.com/search?term=bad%20guy",
        deezer: "https://www.deezer.com/search/bad%20guy",
        youtube: "https://www.youtube.com/results?search_query=bad%20guy",
        bandcamp: "https://artist.bandcamp.com/track/track",
      },
    });
    const user = userEvent.setup();
    render(<SongSearchCard />);

    await user.click(screen.getByRole("tab", { name: /paste a link/i }));
    await user.type(
      screen.getByLabelText(/paste a link/i),
      "https://artist.bandcamp.com/track/track",
    );
    await user.click(screen.getByRole("button", { name: /^resolve$/i }));

    expect(await screen.findByRole("heading", { name: "bad guy" })).toBeInTheDocument();
    // Bandcamp is the only real link; the other four are search deep-links that
    // look broken if clicked, so they must not render even though they're
    // present (truthy) in the response.
    expect(screen.getByRole("link", { name: /on Bandcamp/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /on Spotify/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /on Apple Music/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /on Deezer/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /on YouTube/i })).not.toBeInTheDocument();
  });

  it("shows a calm inline error when a pasted link can't be resolved", async () => {
    mockResolve.mockRejectedValue(new Error("nope"));
    const user = userEvent.setup();
    render(<SongSearchCard />);

    await user.click(screen.getByRole("tab", { name: /paste a link/i }));
    await user.type(screen.getByLabelText(/paste a link/i), "https://bad/link");
    await user.click(screen.getByRole("button", { name: /^resolve$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We couldn't find that song. Check the link and try again.",
    );
  });

  it("shows a specific message for a Bandcamp custom-domain redirect (MYS-212)", async () => {
    mockResolve.mockRejectedValue(
      new ApiError(
        404,
        "this bandcamp link redirects to a custom domain, which isn't supported "
          + "yet. try a link that stays on bandcamp.com",
      ),
    );
    const user = userEvent.setup();
    render(<SongSearchCard />);

    await user.click(screen.getByRole("tab", { name: /paste a link/i }));
    await user.type(
      screen.getByLabelText(/paste a link/i),
      "https://wrwtfww.bandcamp.com/track/1224-live",
    );
    await user.click(screen.getByRole("button", { name: /^resolve$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This Bandcamp link redirects to a custom domain, which we don't support yet. " +
        "Try a link that stays on bandcamp.com.",
    );
    // The pointless source-only retry never fires for this failure.
    expect(mockResolve).toHaveBeenCalledTimes(1);
  });

  it("search mode: returns rows, and selecting one resolves to the result card", async () => {
    mockSearch.mockResolvedValue(searchResults());
    mockResolve.mockResolvedValue(SONG);
    const user = userEvent.setup();
    render(<SongSearchCard />);

    await user.click(screen.getByRole("tab", { name: /search by title/i }));
    await user.type(screen.getByLabelText(/^song title$/i), "bad guy");
    await user.click(screen.getByRole("button", { name: /^search$/i }));

    const row = await screen.findByRole("button", { name: /bad guy/i });
    expect(mockSearch).toHaveBeenCalledWith("bad guy", "");

    await user.click(row);

    expect(await screen.findByRole("heading", { name: "bad guy" })).toBeInTheDocument();
    // Selection resolves by the track's identity (server assembles the links).
    expect(mockResolve).toHaveBeenCalledWith({
      title: "bad guy",
      artist: "Billie Eilish",
      isrc: "USUM71900764",
      album: "When We All Fall Asleep",
      thumbnail_url: "https://img/s.jpg",
    });
  });

  it("surfaces the too-many-matches nudge", async () => {
    mockSearch.mockResolvedValue(searchResults({ too_many_results: true }));
    const user = userEvent.setup();
    render(<SongSearchCard />);

    await user.click(screen.getByRole("tab", { name: /search by title/i }));
    await user.type(screen.getByLabelText(/^song title$/i), "love");
    await user.click(screen.getByRole("button", { name: /^search$/i }));

    expect(
      await screen.findByText(/too many matches — try adding the artist name/i),
    ).toBeInTheDocument();
  });

  it("announces loading to screen readers while resolving", async () => {
    let release!: (song: ResolvedSong) => void;
    mockResolve.mockReturnValue(
      new Promise<ResolvedSong>((resolve) => {
        release = resolve;
      }),
    );
    const user = userEvent.setup();
    render(<SongSearchCard />);

    await user.click(screen.getByRole("tab", { name: /paste a link/i }));
    await user.type(screen.getByLabelText(/paste a link/i), "https://x/y");
    await user.click(screen.getByRole("button", { name: /^resolve$/i }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/resolving song/i);

    release(SONG);
    expect(await screen.findByRole("heading", { name: "bad guy" })).toBeInTheDocument();
  });

  it("'search again' resets back to the input view", async () => {
    mockResolve.mockResolvedValue(SONG);
    const user = userEvent.setup();
    render(<SongSearchCard />);

    await user.click(screen.getByRole("tab", { name: /paste a link/i }));
    await user.type(screen.getByLabelText(/paste a link/i), "https://x/y");
    await user.click(screen.getByRole("button", { name: /^resolve$/i }));
    await screen.findByRole("heading", { name: "bad guy" });

    await user.click(screen.getByRole("button", { name: /search again/i }));
    expect(screen.getByRole("button", { name: /^resolve$/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "bad guy" })).not.toBeInTheDocument();
  });
});
