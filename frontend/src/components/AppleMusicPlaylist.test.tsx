import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppleMusicPlaylist } from "./AppleMusicPlaylist";
import {
  ApiError,
  createApplePlaylist,
  getAppleDeveloperToken,
  getApplePlaylistLink,
} from "../services/api";
import { authorizeAppleMusic } from "../services/musickit";

vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    getAppleDeveloperToken: vi.fn(),
    getApplePlaylistLink: vi.fn(),
    createApplePlaylist: vi.fn(),
  };
});

// Stubbed so tests never load Apple's SDK or open a popup.
vi.mock("../services/musickit", () => ({ authorizeAppleMusic: vi.fn() }));

const mockToken = vi.mocked(getAppleDeveloperToken);
const mockLink = vi.mocked(getApplePlaylistLink);
const mockCreate = vi.mocked(createApplePlaylist);
const mockAuthorize = vi.mocked(authorizeAppleMusic);

beforeEach(() => {
  vi.clearAllMocks();
  mockToken.mockResolvedValue({ token: "dev-token" });
  mockLink.mockResolvedValue({ playlist_url: null, playlist_name: null });
  mockAuthorize.mockResolvedValue("mut-123");
});

describe("AppleMusicPlaylist", () => {
  it("offers to build the playlist, noting the subscription requirement", async () => {
    render(<AppleMusicPlaylist roundId="r1" />);

    expect(
      await screen.findByRole("button", { name: /build this round in apple music/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/requires apple music subscription/i)).toBeInTheDocument();
  });

  it("shows the personal link when one was already generated", async () => {
    mockLink.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      playlist_name: "Mix: Round 1",
    });

    render(<AppleMusicPlaylist roundId="r1" />);

    // Links the LIBRARY, never the playlist: iOS dead-ends on a library-playlist
    // deep link with "Item Not Available" (MYS-190).
    const link = await screen.findByRole("link", { name: /open apple music library/i });
    expect(link).toHaveAttribute("href", "https://music.apple.com/library");
    // The playlist is named so it can be found by hand.
    expect(screen.getByText(/Mix: Round 1/)).toBeInTheDocument();
  });

  it("still shows a usable link when the name was never recorded", async () => {
    // Rows predating MYS-190 have no stored name; the library link must still work.
    mockLink.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      playlist_name: null,
    });

    render(<AppleMusicPlaylist roundId="r1" />);

    expect(
      await screen.findByRole("link", { name: /open apple music library/i }),
    ).toHaveAttribute("href", "https://music.apple.com/library");
    expect(screen.getByText(/in your library/i)).toBeInTheDocument();
  });

  it("authorizes then generates, and surfaces the resulting link", async () => {
    mockCreate.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      playlist_name: "Mix: Round 1",
      track_count: 5,
      total_count: 5,
      unmatched: [],
    });

    render(<AppleMusicPlaylist roundId="r1" />);
    await userEvent.click(
      await screen.findByRole("button", { name: /build this round in apple music/i }),
    );

    await waitFor(() => expect(mockAuthorize).toHaveBeenCalledWith("dev-token"));
    expect(mockCreate).toHaveBeenCalledWith("r1", "mut-123");
    expect(
      await screen.findByRole("link", { name: /open apple music library/i }),
    ).toHaveAttribute("href", "https://music.apple.com/library");
    expect(screen.getByText(/Mix: Round 1/)).toBeInTheDocument();
  });

  it("reports how many tracks were not on apple music", async () => {
    mockCreate.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      playlist_name: "Mix: Round 1",
      track_count: 14,
      total_count: 16,
      unmatched: [
        { submission_id: "s1", title: "A", artist: "X" },
        { submission_id: "s2", title: "B", artist: "Y" },
      ],
    });

    render(<AppleMusicPlaylist roundId="r1" />);
    await userEvent.click(
      await screen.findByRole("button", { name: /build this round in apple music/i }),
    );

    expect(await screen.findByText(/2 not on apple music/i)).toBeInTheDocument();
  });

  it("asks the user to retry when the apple connection expired", async () => {
    mockCreate.mockRejectedValue(new ApiError(401, "expired"));

    render(<AppleMusicPlaylist roundId="r1" />);
    await userEvent.click(
      await screen.findByRole("button", { name: /build this round in apple music/i }),
    );

    expect(await screen.findByText(/connection expired/i)).toBeInTheDocument();
    // Still offering the retry, not a dead end.
    expect(
      screen.getByRole("button", { name: /build this round in apple music/i }),
    ).toBeEnabled();
  });

  it("shows a calm error when generation fails", async () => {
    mockCreate.mockRejectedValue(new Error("boom"));

    render(<AppleMusicPlaylist roundId="r1" />);
    await userEvent.click(
      await screen.findByRole("button", { name: /build this round in apple music/i }),
    );

    expect(await screen.findByText(/couldn't build the playlist/i)).toBeInTheDocument();
  });

  it("renders nothing when apple music is not configured", async () => {
    mockToken.mockResolvedValue({ token: null });

    const { container } = render(<AppleMusicPlaylist roundId="r1" />);

    await waitFor(() => expect(mockToken).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while still loading", () => {
    mockToken.mockReturnValue(new Promise(() => {}));

    const { container } = render(<AppleMusicPlaylist roundId="r1" />);

    expect(container).toBeEmptyDOMElement();
  });
});
