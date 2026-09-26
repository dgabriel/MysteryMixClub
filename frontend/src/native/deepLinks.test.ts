import { beforeEach, describe, expect, it, vi } from "vitest";

const addListenerMock = vi.fn();
vi.mock("@capacitor/app", () => ({
  App: { addListener: (...args: unknown[]) => addListenerMock(...args) },
}));

describe("registerDeepLinkHandler (MysteryMixClub-4vii.10)", () => {
  beforeEach(() => {
    vi.resetModules();
    addListenerMock.mockReset();
  });

  it("does nothing on a non-native build", async () => {
    vi.doMock("../lib/platform", () => ({ IS_NATIVE_BUILD: false }));
    const { registerDeepLinkHandler } = await import("./deepLinks");

    registerDeepLinkHandler({ navigate: vi.fn() });

    expect(addListenerMock).not.toHaveBeenCalled();
  });

  it("routes a tapped Universal Link into the app router by path + query", async () => {
    vi.doMock("../lib/platform", () => ({ IS_NATIVE_BUILD: true }));
    const { registerDeepLinkHandler } = await import("./deepLinks");
    const navigate = vi.fn();

    registerDeepLinkHandler({ navigate });
    const handler = addListenerMock.mock.calls[0][1] as (event: { url: string }) => void;
    handler({ url: "https://staging.mysterymixclub.com/auth/verify?token=abc123" });

    expect(navigate).toHaveBeenCalledWith("/auth/verify?token=abc123");
  });

  it("routes an invite link the same way", async () => {
    vi.doMock("../lib/platform", () => ({ IS_NATIVE_BUILD: true }));
    const { registerDeepLinkHandler } = await import("./deepLinks");
    const navigate = vi.fn();

    registerDeepLinkHandler({ navigate });
    const handler = addListenerMock.mock.calls[0][1] as (event: { url: string }) => void;
    handler({ url: "https://staging.mysterymixclub.com/invite/xyz789" });

    expect(navigate).toHaveBeenCalledWith("/invite/xyz789");
  });

  it("ignores a malformed URL from the OS rather than throwing", async () => {
    vi.doMock("../lib/platform", () => ({ IS_NATIVE_BUILD: true }));
    const { registerDeepLinkHandler } = await import("./deepLinks");
    const navigate = vi.fn();

    registerDeepLinkHandler({ navigate });
    const handler = addListenerMock.mock.calls[0][1] as (event: { url: string }) => void;

    expect(() => handler({ url: "not-a-url" })).not.toThrow();
    expect(navigate).not.toHaveBeenCalled();
  });
});
