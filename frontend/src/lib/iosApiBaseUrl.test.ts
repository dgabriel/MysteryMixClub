import { describe, expect, it } from "vitest";
import { resolveIosApiBaseUrl } from "./iosApiBaseUrl";

describe("resolveIosApiBaseUrl (MysteryMixClub-4vii.12)", () => {
  it("defaults to the real staging HTTPS backend when unset", () => {
    expect(resolveIosApiBaseUrl(undefined)).toBe("https://staging.mysterymixclub.com");
  });

  it("accepts an explicit https:// override", () => {
    expect(resolveIosApiBaseUrl("https://mysterymixclub.com")).toBe("https://mysterymixclub.com");
  });

  it("fails closed on a plain-HTTP override", () => {
    expect(() => resolveIosApiBaseUrl("http://192.168.1.153:8001")).toThrow(/must be an https:\/\/ URL/);
  });

  it("fails closed on an empty override rather than silently defaulting", () => {
    expect(() => resolveIosApiBaseUrl("")).toThrow(/must be an https:\/\/ URL/);
  });
});

describe("local simulator API isolation", () => {
  const context = { localSimulator: "1", configuration: "Debug", platform: "iphonesimulator", action: "build" };

  it("allows explicit Debug simulator loopback origins", () => {
    expect(resolveIosApiBaseUrl(undefined, context)).toBe("http://localhost:8000");
    expect(resolveIosApiBaseUrl("http://127.0.0.1:8000/", context)).toBe("http://127.0.0.1:8000");
    expect(resolveIosApiBaseUrl("http://[::1]:8000", context)).toBe("http://[::1]:8000");
  });

  it.each([
    { configuration: "Release" }, { platform: "iphoneos" }, { action: "install" },
    { localSimulator: "0" }, { configuration: undefined }, { platform: undefined }, { action: undefined },
  ])("rejects unsafe or missing Xcode context: %j", (override) => {
    expect(() => resolveIosApiBaseUrl("http://localhost:8000", { ...context, ...override })).toThrow(/explicit Debug/);
  });

  it.each([
    "http://192.168.1.153:8000", "http://localhost.example.com:8000", "https://staging.mysterymixclub.com",
    "http://user:password@localhost:8000", "http://localhost:8000/api", "http://localhost:8000?x=1",
    "http://localhost:8000#fragment",
  ])("rejects non-loopback origins and URL extras: %s", (url) => {
    expect(() => resolveIosApiBaseUrl(url, context)).toThrow(/loopback HTTP origin/);
  });

  it("does not enable HTTP just because Xcode is building for a simulator", () => {
    expect(() => resolveIosApiBaseUrl("http://localhost:8000", { ...context, localSimulator: undefined })).toThrow(/https/);
  });
});
