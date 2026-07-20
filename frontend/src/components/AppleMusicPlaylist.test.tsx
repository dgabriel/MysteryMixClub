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
  mockLink.mockResolvedValue({ playlist_url: null, direct_playlist_url: null, playlist_name: null });
  mockAuthorize.mockResolvedValue("mut-123");
});

describe("AppleMusicPlaylist", () => {
  it("offers to build the playlist, noting the subscription requirement", async () => {
    render(<AppleMusicPlaylist mixId="r1" />);

    expect(
      await screen.findByRole("button", { name: /build this mystery mix in apple music/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/requires apple music subscription/i)).toBeInTheDocument();
  });

  it("shows the personal link when one was already generated (no direct url)", async () => {
    // No direct_playlist_url (e.g. a pre-MYS-214 row): falls back to the
    // library link and "look for it by name" prompt on every platform.
    mockLink.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: null,
      playlist_name: "Mix: Mix 1",
    });

    render(<AppleMusicPlaylist mixId="r1" />);

    // Links the LIBRARY, never the playlist: iOS dead-ends on a library-playlist
    // deep link with "Item Not Available" (MYS-190).
    const link = await screen.findByRole("link", { name: /open apple music library/i });
    expect(link).toHaveAttribute("href", "https://music.apple.com/library");
    // Apple exposes no deep link to a library playlist, so the member makes the
    // last hop by hand and the title is how they find it (MYS-190).
    expect(
      screen.getByText(/go to your Apple Music playlists and look for/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Mix: Mix 1/)).toBeInTheDocument();
  });

  it("still shows a usable link when the name was never recorded", async () => {
    // Rows predating MYS-190 have no stored name; the library link must still work.
    mockLink.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: null,
      playlist_name: null,
    });

    render(<AppleMusicPlaylist mixId="r1" />);

    expect(
      await screen.findByRole("link", { name: /open apple music library/i }),
    ).toHaveAttribute("href", "https://music.apple.com/library");
    expect(screen.getByText(/go to your Apple Music playlists to find it/i)).toBeInTheDocument();
  });

  it("on desktop, links straight to the exact playlist (MYS-214)", async () => {
    // jsdom's default user-agent has no mobile/iPad markers, so the component
    // treats the test environment as desktop.
    mockLink.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: "https://music.apple.com/library/playlist/p.ABC",
      playlist_name: "Mix: Mix 1",
    });

    render(<AppleMusicPlaylist mixId="r1" />);

    const link = await screen.findByRole("link", { name: /open in apple music/i });
    expect(link).toHaveAttribute("href", "https://music.apple.com/library/playlist/p.ABC");
    // No "find it yourself" prompt needed — the link goes straight there.
    expect(screen.queryByText(/go to your Apple Music playlists/i)).not.toBeInTheDocument();
  });

  it("on mobile, ignores the direct link and prompts to find it by name", async () => {
    const uaSpy = vi.spyOn(window.navigator, "userAgent", "get").mockReturnValue(
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15",
    );
    mockLink.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: "https://music.apple.com/library/playlist/p.ABC",
      playlist_name: "Mix: Mix 1",
    });

    render(<AppleMusicPlaylist mixId="r1" />);

    const link = await screen.findByRole("link", { name: /open apple music library/i });
    expect(link).toHaveAttribute("href", "https://music.apple.com/library");
    expect(
      screen.getByText(/go to your Apple Music playlists and look for/i),
    ).toBeInTheDocument();

    uaSpy.mockRestore();
  });

  it("treats a multi-touch \"Macintosh\" as an iPad, not a real desktop", async () => {
    // iPadOS Safari reports as "Macintosh" (Apple dropped the iPad UA marker
    // around iOS 13 to unify with desktop Safari), so a touch-capable "Mac" is
    // the standard tell for a real iPad rather than a desktop machine.
    // jsdom's navigator has no maxTouchPoints property at all (unlike a real
    // browser), so vi.spyOn (which requires an existing property) can't be
    // used here — define it directly and remove it again after.
    const uaSpy = vi
      .spyOn(window.navigator, "userAgent", "get")
      .mockReturnValue(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15",
      );
    Object.defineProperty(window.navigator, "maxTouchPoints", { value: 5, configurable: true });
    mockLink.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: "https://music.apple.com/library/playlist/p.ABC",
      playlist_name: "Mix: Mix 1",
    });

    render(<AppleMusicPlaylist mixId="r1" />);

    const link = await screen.findByRole("link", { name: /open apple music library/i });
    expect(link).toHaveAttribute("href", "https://music.apple.com/library");
    expect(
      screen.getByText(/go to your Apple Music playlists and look for/i),
    ).toBeInTheDocument();

    uaSpy.mockRestore();
    delete (window.navigator as { maxTouchPoints?: number }).maxTouchPoints;
  });

  it("does not treat a non-touch Mac as an iPad", async () => {
    const uaSpy = vi
      .spyOn(window.navigator, "userAgent", "get")
      .mockReturnValue(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15",
      );
    Object.defineProperty(window.navigator, "maxTouchPoints", { value: 0, configurable: true });
    mockLink.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: "https://music.apple.com/library/playlist/p.ABC",
      playlist_name: "Mix: Mix 1",
    });

    render(<AppleMusicPlaylist mixId="r1" />);

    const link = await screen.findByRole("link", { name: /open in apple music/i });
    expect(link).toHaveAttribute("href", "https://music.apple.com/library/playlist/p.ABC");

    uaSpy.mockRestore();
    delete (window.navigator as { maxTouchPoints?: number }).maxTouchPoints;
  });

  it("authorizes then generates, and surfaces the resulting link", async () => {
    mockCreate.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: "https://music.apple.com/library/playlist/p.NEW",
      playlist_name: "Mix: Mix 1",
      track_count: 5,
      total_count: 5,
      unmatched: [],
    });

    render(<AppleMusicPlaylist mixId="r1" />);
    await userEvent.click(
      await screen.findByRole("button", { name: /build this mystery mix in apple music/i }),
    );

    await waitFor(() => expect(mockAuthorize).toHaveBeenCalledWith("dev-token"));
    expect(mockCreate).toHaveBeenCalledWith("r1", "mut-123");
    // Desktop (jsdom default) gets the exact-playlist link straight away.
    expect(
      await screen.findByRole("link", { name: /open in apple music/i }),
    ).toHaveAttribute("href", "https://music.apple.com/library/playlist/p.NEW");
    expect(screen.getByText(/Mix: Mix 1/)).toBeInTheDocument();
  });

  it("asks the user to retry when the apple connection expired", async () => {
    mockCreate.mockRejectedValue(new ApiError(401, "expired"));

    render(<AppleMusicPlaylist mixId="r1" />);
    await userEvent.click(
      await screen.findByRole("button", { name: /build this mystery mix in apple music/i }),
    );

    expect(await screen.findByText(/connection expired/i)).toBeInTheDocument();
    // Still offering the retry, not a dead end.
    expect(
      screen.getByRole("button", { name: /build this mystery mix in apple music/i }),
    ).toBeEnabled();
  });

  it("shows a calm error when generation fails", async () => {
    mockCreate.mockRejectedValue(new Error("boom"));

    render(<AppleMusicPlaylist mixId="r1" />);
    await userEvent.click(
      await screen.findByRole("button", { name: /build this mystery mix in apple music/i }),
    );

    expect(await screen.findByText(/couldn't build the playlist/i)).toBeInTheDocument();
  });

  it("renders nothing when apple music is not configured", async () => {
    mockToken.mockResolvedValue({ token: null });

    const { container } = render(<AppleMusicPlaylist mixId="r1" />);

    await waitFor(() => expect(mockToken).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while still loading", () => {
    mockToken.mockReturnValue(new Promise(() => {}));

    const { container } = render(<AppleMusicPlaylist mixId="r1" />);

    expect(container).toBeEmptyDOMElement();
  });
});
