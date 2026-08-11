import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SongsMaybeMissing } from "./SongsMaybeMissing";
import { getSpotifyPlaylistLink } from "../../services/api";

vi.mock("../../services/api", async () => {
  const actual = await vi.importActual<typeof import("../../services/api")>("../../services/api");
  return { ...actual, getSpotifyPlaylistLink: vi.fn() };
});

const mockLink = vi.mocked(getSpotifyPlaylistLink);

const NONE = { playlist_url: null, unmatched: [], overflow_youtube_url: null, status: null };

function reported(over: Partial<Parameters<typeof mockLink.mockResolvedValue>[0]> = {}) {
  return { ...NONE, ...over };
}

describe("SongsMaybeMissing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLink.mockResolvedValue(NONE);
  });

  it("renders nothing when nothing is known to be missing", async () => {
    const { container } = render(<SongsMaybeMissing mixId="m1" sourceOnly={[]} />);
    // Let the fetch settle before asserting emptiness.
    await vi.waitFor(() => expect(mockLink).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("lists a pick that has no catalog identity at all, straight from the mix", async () => {
    render(
      <SongsMaybeMissing
        mixId="m1"
        sourceOnly={[
          {
            submission_id: "s1",
            title: "Bedroom Demo",
            artist: "Nobody",
            source_url: "https://coolband.bandcamp.com/track/bedroom-demo",
          },
        ]}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: /songs that may not be on all playlists/i }),
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Bedroom Demo" });
    expect(link).toHaveAttribute("href", "https://coolband.bandcamp.com/track/bedroom-demo");
  });

  it("also lists songs a service reported it could not match", async () => {
    mockLink.mockResolvedValue(
      reported({
        playlist_url: "https://open.spotify.com/playlist/p1",
        unmatched: [
          {
            submission_id: "s2",
            title: "Just a Friend",
            artist: "Biz Markie",
            reason: "no_catalog_match",
            source: null,
            source_url: null,
          },
        ],
      }),
    );

    render(<SongsMaybeMissing mixId="m1" sourceOnly={[]} />);

    expect(await screen.findByText(/Just a Friend/)).toBeInTheDocument();
    // No link: we know it is missing, not where to hear it.
    expect(screen.queryByRole("link", { name: "Just a Friend" })).not.toBeInTheDocument();
  });

  it("lists a song once when both sources know about it", async () => {
    // A Bandcamp-only pick is usually ALSO in a service's unmatched list.
    // Listing it twice would imply two different problems.
    mockLink.mockResolvedValue(
      reported({
        unmatched: [
          {
            submission_id: "s1",
            title: "Bedroom Demo",
            artist: "Nobody",
            reason: "source_only",
            source: "bandcamp",
            source_url: "https://coolband.bandcamp.com/track/bedroom-demo",
          },
        ],
      }),
    );

    render(
      <SongsMaybeMissing
        mixId="m1"
        sourceOnly={[
          {
            submission_id: "s1",
            title: "Bedroom Demo",
            artist: "Nobody",
            source_url: "https://coolband.bandcamp.com/track/bedroom-demo",
          },
        ]}
      />,
    );

    expect(await screen.findAllByText(/Bedroom Demo/)).toHaveLength(1);
  });

  it("offers the youtube fallback when one exists, named so it cannot be read as a service row", async () => {
    mockLink.mockResolvedValue(
      reported({
        overflow_youtube_url: "https://www.youtube.com/watch_videos?video_ids=abc",
        unmatched: [
          {
            submission_id: "s2",
            title: "Just a Friend",
            artist: "Biz Markie",
            reason: "no_catalog_match",
            source: null,
            source_url: null,
          },
        ],
      }),
    );

    render(<SongsMaybeMissing mixId="m1" sourceOnly={[]} />);

    const link = await screen.findByRole("link", { name: /missing from spotify/i });
    expect(link).toHaveAttribute("href", "https://www.youtube.com/watch_videos?video_ids=abc");
  });

  it("still lists what the mix itself knows when the lookup fails", async () => {
    // Degrading to less information is correct here: the section is hedged
    // ("may not be"), so a failed lookup makes it less complete, not wrong.
    mockLink.mockRejectedValue(new Error("boom"));

    render(
      <SongsMaybeMissing
        mixId="m1"
        sourceOnly={[
          {
            submission_id: "s1",
            title: "Bedroom Demo",
            artist: "Nobody",
            source_url: "https://coolband.bandcamp.com/track/bedroom-demo",
          },
        ]}
      />,
    );

    expect(await screen.findByText(/Bedroom Demo/)).toBeInTheDocument();
  });
});
