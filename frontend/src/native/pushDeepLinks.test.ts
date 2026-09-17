import { beforeEach, describe, expect, it, vi } from "vitest";

const nativePushAvailableMock = vi.fn();
const initializePushListenersMock = vi.fn();
vi.mock("../ios/push", () => ({
  nativePushAvailable: (...args: unknown[]) => nativePushAvailableMock(...args),
  initializePushListeners: (...args: unknown[]) => initializePushListenersMock(...args),
}));

describe("registerPushDeepLinkHandler (MysteryMixClub-4vii.27, IOS-04)", () => {
  beforeEach(() => {
    vi.resetModules();
    nativePushAvailableMock.mockReset();
    initializePushListenersMock.mockReset();
  });

  it("does nothing on web", async () => {
    nativePushAvailableMock.mockReturnValue(false);
    const { registerPushDeepLinkHandler } = await import("./pushDeepLinks");

    registerPushDeepLinkHandler({ navigate: vi.fn() });

    expect(initializePushListenersMock).not.toHaveBeenCalled();
  });

  it("routes a tapped notification to the club's home screen, not the specific mix", async () => {
    nativePushAvailableMock.mockReturnValue(true);
    const { registerPushDeepLinkHandler } = await import("./pushDeepLinks");
    const navigate = vi.fn();

    registerPushDeepLinkHandler({ navigate });
    const onDeepLink = initializePushListenersMock.mock.calls[0][0] as (
      data: Record<string, string>,
    ) => void;
    onDeepLink({ club_id: "club-1", mix_id: "mix-9", event: "voting_opened" });

    expect(navigate).toHaveBeenCalledWith("/clubs/club-1");
  });

  it("does nothing when the payload carries no club_id", async () => {
    nativePushAvailableMock.mockReturnValue(true);
    const { registerPushDeepLinkHandler } = await import("./pushDeepLinks");
    const navigate = vi.fn();

    registerPushDeepLinkHandler({ navigate });
    const onDeepLink = initializePushListenersMock.mock.calls[0][0] as (
      data: Record<string, string>,
    ) => void;
    onDeepLink({});

    expect(navigate).not.toHaveBeenCalled();
  });
});
