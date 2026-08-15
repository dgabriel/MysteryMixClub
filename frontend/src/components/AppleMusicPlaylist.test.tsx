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
import { AppleMusicError, authorizeAppleMusic, preloadAppleMusic } from "../services/musickit";

vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    getAppleDeveloperToken: vi.fn(),
    getApplePlaylistLink: vi.fn(),
    createApplePlaylist: vi.fn(),
  };
});

// Stubbed so tests never load Apple's SDK or open a sign-in window. Only the
// two calls are stubbed — AppleMusicError comes through real, because the
// component branches on `instanceof` and a fake class would never match.
vi.mock("../services/musickit", async () => {
  const actual = await vi.importActual<typeof import("../services/musickit")>(
    "../services/musickit",
  );
  return { ...actual, authorizeAppleMusic: vi.fn(), preloadAppleMusic: vi.fn() };
});

const mockToken = vi.mocked(getAppleDeveloperToken);
const mockLink = vi.mocked(getApplePlaylistLink);
const mockCreate = vi.mocked(createApplePlaylist);
const mockAuthorize = vi.mocked(authorizeAppleMusic);
const mockPreload = vi.mocked(preloadAppleMusic);

beforeEach(() => {
  vi.clearAllMocks();
  mockToken.mockResolvedValue({ token: "dev-token" });
  mockLink.mockResolvedValue({
    playlist_url: null,
    direct_playlist_url: null,
    playlist_name: null,
  });
  mockAuthorize.mockResolvedValue("mut-123");
  mockPreload.mockResolvedValue({ authorize: vi.fn() });
});

describe("AppleMusicPlaylist", () => {
  it("offers to build the playlist, noting the subscription requirement", async () => {
    render(<AppleMusicPlaylist mixId="r1" />);

    expect(
      await screen.findByRole("button", { name: /build this playlist in apple music/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/needs an apple music subscription/i)).toBeInTheDocument();
  });

  it("shows a reassurance modal before authorizing — Apple's own sign-in, password-free, check the url (MYS-254)", async () => {
    render(<AppleMusicPlaylist mixId="r1" />);

    await userEvent.click(
      await screen.findByRole("button", { name: /build this playlist in apple music/i }),
    );

    expect(
      screen.getByText(
        /opens apple's own sign-in\. we never see or store your apple id password\./i,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/check that the page's address reads apple\.com/i)).toBeInTheDocument();
    // Not yet authorized — the modal is an interstitial, not an auto-trigger.
    expect(mockAuthorize).not.toHaveBeenCalled();
  });

  it("cancelling the reassurance modal closes it without authorizing", async () => {
    render(<AppleMusicPlaylist mixId="r1" />);

    await userEvent.click(
      await screen.findByRole("button", { name: /build this playlist in apple music/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(screen.queryByText(/opens apple's own sign-in/i)).not.toBeInTheDocument();
    expect(mockAuthorize).not.toHaveBeenCalled();
  });

  it("continuing from the reassurance modal authorizes and closes it", async () => {
    render(<AppleMusicPlaylist mixId="r1" />);

    await userEvent.click(
      await screen.findByRole("button", { name: /build this playlist in apple music/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue to apple music/i }));

    await waitFor(() => expect(mockAuthorize).toHaveBeenCalledWith("dev-token"));
    expect(screen.queryByText(/opens apple's own sign-in/i)).not.toBeInTheDocument();
  });

  it("shows the personal link when one was already generated (no direct url)", async () => {
    // No direct_playlist_url — a pre-MYS-214 row that never got one recorded.
    // Falls back to the bare library link and a "look for it by name" prompt.
    mockLink.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: null,
      playlist_name: "Mix: Mix 1",
    });

    render(<AppleMusicPlaylist mixId="r1" />);

    const link = await screen.findByRole("link", { name: /open your apple music library/i });
    expect(link).toHaveAttribute("href", "https://music.apple.com/library");
    // Apple exposes no deep link in this fallback case, so the member makes
    // the last hop by hand and the title is how they find it (MYS-190).
    expect(screen.getByText(/find/i)).toBeInTheDocument();
    expect(screen.getByText(/Mix 1/)).toBeInTheDocument();
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
      await screen.findByRole("link", { name: /open your apple music library/i }),
    ).toHaveAttribute("href", "https://music.apple.com/library");
    expect(screen.getByText(/find it in your Apple Music library/i)).toBeInTheDocument();
  });

  // MysteryMixClub-ap25: MYS-190's bare `/library` link and MYS-214/o3r8's
  // direct playlist link were each believed fixed and each failed on a fresh
  // mobile session — the direct link even fails opened via the native Music
  // app's own `music://` scheme, ruling out Safari/session/navigation as the
  // cause. Desktop's web player has resolved the direct link reliably since
  // MYS-214 and is left alone; mobile now always gets Apple Music's home page
  // and finds the playlist by name.
  it("on desktop, links straight to the exact playlist (MYS-214)", async () => {
    // jsdom's default user-agent has no mobile/iPad markers, so the component
    // treats the test environment as desktop.
    mockLink.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: "https://music.apple.com/library/playlist/p.ABC",
      playlist_name: "Mix: Mix 1",
    });

    render(<AppleMusicPlaylist mixId="r1" />);

    const link = await screen.findByRole("link", { name: /open playlist in apple music/i });
    expect(link).toHaveAttribute("href", "https://music.apple.com/library/playlist/p.ABC");
    // No "find it yourself" prompt needed — the link goes straight there.
    expect(screen.queryByText(/find it in your Apple Music library/i)).not.toBeInTheDocument();
  });

  it("on mobile, ignores the direct link and sends the member to apple music's home page", async () => {
    const uaSpy = vi
      .spyOn(window.navigator, "userAgent", "get")
      .mockReturnValue(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15",
      );
    mockLink.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: "https://music.apple.com/library/playlist/p.ABC",
      playlist_name: "Mix: Mix 1",
    });

    render(<AppleMusicPlaylist mixId="r1" />);

    const link = await screen.findByRole("link", { name: /open the apple music app/i });
    expect(link).toHaveAttribute("href", "https://music.apple.com");
    expect(screen.getByText(/find/i)).toBeInTheDocument();
    expect(screen.getByText(/Mix 1/)).toBeInTheDocument();

    uaSpy.mockRestore();
  });

  it('treats a multi-touch "Macintosh" as an iPad, not a real desktop', async () => {
    // iPadOS Safari reports as "Macintosh" (Apple dropped the iPad UA marker
    // around iOS 13 to unify with desktop Safari), so a touch-capable "Mac" is
    // the standard tell for a real iPad rather than a desktop machine.
    // jsdom's navigator has no maxTouchPoints property at all (unlike a real
    // browser), so vi.spyOn (which requires an existing property) can't be
    // used here — define it directly and remove it again after.
    const uaSpy = vi
      .spyOn(window.navigator, "userAgent", "get")
      .mockReturnValue("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15");
    Object.defineProperty(window.navigator, "maxTouchPoints", { value: 5, configurable: true });
    mockLink.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: "https://music.apple.com/library/playlist/p.ABC",
      playlist_name: "Mix: Mix 1",
    });

    render(<AppleMusicPlaylist mixId="r1" />);

    const link = await screen.findByRole("link", { name: /open the apple music app/i });
    expect(link).toHaveAttribute("href", "https://music.apple.com");
    expect(screen.getByText(/find/i)).toBeInTheDocument();

    uaSpy.mockRestore();
    delete (window.navigator as { maxTouchPoints?: number }).maxTouchPoints;
  });

  it("does not treat a non-touch Mac as an iPad", async () => {
    const uaSpy = vi
      .spyOn(window.navigator, "userAgent", "get")
      .mockReturnValue("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15");
    Object.defineProperty(window.navigator, "maxTouchPoints", { value: 0, configurable: true });
    mockLink.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: "https://music.apple.com/library/playlist/p.ABC",
      playlist_name: "Mix: Mix 1",
    });

    render(<AppleMusicPlaylist mixId="r1" />);

    const link = await screen.findByRole("link", { name: /open playlist in apple music/i });
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
      await screen.findByRole("button", { name: /build this playlist in apple music/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue to apple music/i }));

    await waitFor(() => expect(mockAuthorize).toHaveBeenCalledWith("dev-token"));
    expect(mockCreate).toHaveBeenCalledWith("r1", "mut-123");
    // The exact-playlist link comes back straight away.
    expect(
      await screen.findByRole("link", { name: /open playlist in apple music/i }),
    ).toHaveAttribute("href", "https://music.apple.com/library/playlist/p.NEW");
    // No playlist name here, deliberately: the link opens the exact playlist,
    // so naming it was pure confirmation, and the row's status already reports
    // what landed. The name earns its keep only in the no-direct-url fallback
    // case, where Apple exposes no deep link and the title is genuinely how
    // the member finds it (see "shows the personal link…" above).
    expect(screen.queryByText(/Mix 1/)).not.toBeInTheDocument();
  });

  it("asks the user to retry when the apple connection expired", async () => {
    mockCreate.mockRejectedValue(new ApiError(401, "expired"));

    render(<AppleMusicPlaylist mixId="r1" />);
    await userEvent.click(
      await screen.findByRole("button", { name: /build this playlist in apple music/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue to apple music/i }));

    expect(await screen.findByText(/connection expired/i)).toBeInTheDocument();
    // Still offering the retry, not a dead end.
    expect(
      screen.getByRole("button", { name: /build this playlist in apple music/i }),
    ).toBeEnabled();
  });

  it("shows a calm error when generation fails", async () => {
    mockCreate.mockRejectedValue(new Error("boom"));

    render(<AppleMusicPlaylist mixId="r1" />);
    await userEvent.click(
      await screen.findByRole("button", { name: /build this playlist in apple music/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue to apple music/i }));

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

  // MysteryMixClub-sdfd. The read endpoint returns the link and nothing else, so
  // a plain page load cannot know the gap. Claiming completeness there told
  // live users all their songs were on a playlist that was missing three.
  it("does not claim completeness for a playlist it never measured", async () => {
    mockLink.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: "https://music.apple.com/library/playlist/p.ABC",
      playlist_name: "Mix: Mix 1",
    });

    render(<AppleMusicPlaylist mixId="r1" entryCount={12} />);

    expect(await screen.findByText(/in your library/i)).toBeInTheDocument();
    expect(screen.queryByText(/all 12 songs/i)).not.toBeInTheDocument();
    // Nor the count phrasing — we know nothing, not that nothing is missing.
    expect(screen.queryByText(/of 12 songs/i)).not.toBeInTheDocument();
  });

  it("says all N songs only once a build reports the playlist complete", async () => {
    mockCreate.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: "https://music.apple.com/library/playlist/p.NEW",
      playlist_name: "Mix: Mix 1",
      track_count: 12,
      total_count: 12,
      unmatched: [],
    });

    render(<AppleMusicPlaylist mixId="r1" entryCount={12} />);
    await userEvent.click(
      await screen.findByRole("button", { name: /build this playlist in apple music/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue to apple music/i }));

    expect(await screen.findByText(/all 12 songs/i)).toBeInTheDocument();
  });

  // MysteryMixClub-ljl5. On mobile the sign-in window never opened and the row
  // hung on "building…" forever: the SDK was loaded and configured *after* the
  // tap, which cost the user activation Safari requires to open it.
  it("warms the apple sdk while the interstitial is on screen, before the tap", async () => {
    render(<AppleMusicPlaylist mixId="r1" />);

    await userEvent.click(
      await screen.findByRole("button", { name: /build this playlist in apple music/i }),
    );

    // Warmed by the interstitial itself, not by the button that commits.
    await waitFor(() => expect(mockPreload).toHaveBeenCalledWith("dev-token"));
    expect(mockAuthorize).not.toHaveBeenCalled();
  });

  it("does not warm the sdk before the user opens the interstitial", async () => {
    render(<AppleMusicPlaylist mixId="r1" />);

    await screen.findByRole("button", { name: /build this playlist in apple music/i });

    // A member who never touches Apple never pays for the download.
    expect(mockPreload).not.toHaveBeenCalled();
  });

  it("blames the blocker when apple's sdk cannot load, and stays retryable", async () => {
    mockAuthorize.mockRejectedValue(new AppleMusicError("sdk_blocked", "blocked"));

    render(<AppleMusicPlaylist mixId="r1" />);
    await userEvent.click(
      await screen.findByRole("button", { name: /build this playlist in apple music/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue to apple music/i }));

    expect(await screen.findByText(/content or ad blocker may be blocking it/i)).toBeInTheDocument();
    // Never stranded on "building…" — the whole point of the fix.
    expect(
      screen.getByRole("button", { name: /build this playlist in apple music/i }),
    ).toBeEnabled();
  });

  it("offers sign-in advice when apple's authorize never completes", async () => {
    mockAuthorize.mockRejectedValue(new AppleMusicError("authorize_failed", "timed out"));

    render(<AppleMusicPlaylist mixId="r1" />);
    await userEvent.click(
      await screen.findByRole("button", { name: /build this playlist in apple music/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue to apple music/i }));

    expect(await screen.findByText(/apple's sign-in didn't finish/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /build this playlist in apple music/i }),
    ).toBeEnabled();
  });

  it("reports the gap as a count when a build finds songs missing", async () => {
    mockCreate.mockResolvedValue({
      playlist_url: "https://music.apple.com/library",
      direct_playlist_url: "https://music.apple.com/library/playlist/p.NEW",
      playlist_name: "Mix: Mix 1",
      track_count: 9,
      total_count: 12,
      unmatched: [
        {
          submission_id: "s1",
          title: "One",
          artist: "A",
          reason: "source_only",
          source: "bandcamp",
          source_url: "https://a.bandcamp.com/track/one",
        },
        {
          submission_id: "s2",
          title: "Two",
          artist: "B",
          reason: "source_only",
          source: "youtube",
          source_url: "https://youtu.be/xyz",
        },
        {
          submission_id: "s3",
          title: "Three",
          artist: "C",
          reason: "no_catalog_match",
          source: null,
          source_url: null,
        },
      ],
    });

    render(<AppleMusicPlaylist mixId="r1" entryCount={12} />);
    await userEvent.click(
      await screen.findByRole("button", { name: /build this playlist in apple music/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue to apple music/i }));

    expect(await screen.findByText(/9 of 12 songs/i)).toBeInTheDocument();
    expect(screen.queryByText(/all 12 songs/i)).not.toBeInTheDocument();
  });
});
