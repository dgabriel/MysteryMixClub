import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SourceOnlyTracks, type SourceOnlyTrack } from "./SourceOnlyTracks";

const HEADING = "bandcamp or YouTube only tracks that may not appear on your playlists";

const tracks: SourceOnlyTrack[] = [
  {
    submission_id: "s1",
    title: "Ghost Town",
    artist: "The Specials",
    source: "bandcamp",
    source_url: "https://thespecials.bandcamp.com/track/ghost-town",
  },
  {
    submission_id: "s2",
    title: "Deep Cut",
    artist: "Unknown",
    source: "youtube",
    source_url: "https://youtube.com/watch?v=abc",
  },
];

describe("SourceOnlyTracks", () => {
  it("renders nothing when there are no source-only tracks", () => {
    const { container } = render(<SourceOnlyTracks tracks={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the heading and each track as a link to its source", () => {
    render(<SourceOnlyTracks tracks={tracks} />);

    expect(screen.getByText(HEADING)).toBeInTheDocument();

    const first = screen.getByRole("link", { name: "Ghost Town" });
    expect(first).toHaveAttribute("href", "https://thespecials.bandcamp.com/track/ghost-town");
    expect(first).toHaveAttribute("target", "_blank");
    expect(first).toHaveAttribute("rel", "noopener noreferrer");

    const second = screen.getByRole("link", { name: "Deep Cut" });
    expect(second).toHaveAttribute("href", "https://youtube.com/watch?v=abc");
  });

  it("appends the artist next to the title", () => {
    render(<SourceOnlyTracks tracks={[tracks[0]]} />);
    expect(screen.getByText(/· The Specials/)).toBeInTheDocument();
  });
});
