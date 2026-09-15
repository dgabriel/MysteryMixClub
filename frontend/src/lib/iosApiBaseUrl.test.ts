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
