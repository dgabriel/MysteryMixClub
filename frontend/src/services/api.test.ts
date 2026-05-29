import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  authenticatedRequest,
  getAccessToken,
  logout,
  logoutAll,
  refresh,
  requestMagicLink,
  setStoredAccessToken,
  verifyToken,
} from "./api";

const API_BASE = "http://localhost:8000";
const AUTH_BASE = `${API_BASE}/api/v1/auth`;

/** Build a Response-like object with a json() body. */
function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function emptyResponse(status: number): Response {
  return new Response(null, { status });
}

describe("api.ts", () => {
  beforeEach(() => {
    // Reset the in-memory token between tests.
    setStoredAccessToken(null);
    vi.restoreAllMocks();
  });

  afterEach(() => {
    setStoredAccessToken(null);
  });

  describe("in-memory token storage", () => {
    it("getAccessToken returns null by default and reflects setStoredAccessToken", () => {
      expect(getAccessToken()).toBeNull();
      setStoredAccessToken("abc123");
      expect(getAccessToken()).toBe("abc123");
      setStoredAccessToken(null);
      expect(getAccessToken()).toBeNull();
    });
  });

  describe("requestMagicLink", () => {
    it("POSTs the email to /auth/request and resolves on 200", async () => {
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(200, { message: "ok" }));

      await expect(requestMagicLink("user@example.com")).resolves.toBeUndefined();

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${AUTH_BASE}/request`);
      expect(init?.method).toBe("POST");
      expect(init?.body).toBe(JSON.stringify({ email: "user@example.com" }));
      expect((init?.headers as Record<string, string>)["Content-Type"]).toBe(
        "application/json",
      );
    });

    it("throws ApiError with the backend detail on a non-2xx response", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(429, { detail: "too many requests" }),
      );

      await expect(requestMagicLink("user@example.com")).rejects.toMatchObject({
        name: "ApiError",
        status: 429,
        message: "too many requests",
      });
    });

    it("throws ApiError with a generic message when the error body is not JSON", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response("nope", { status: 500 }),
      );

      await expect(requestMagicLink("user@example.com")).rejects.toMatchObject({
        status: 500,
        message: "request failed (500)",
      });
    });
  });

  describe("verifyToken", () => {
    it("GETs /auth/verify with credentials include and the encoded token", async () => {
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(200, { access_token: "tok", token_type: "bearer" }));

      const result = await verifyToken("a b/c?d");

      expect(result).toEqual({ access_token: "tok" });
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${AUTH_BASE}/verify?token=${encodeURIComponent("a b/c?d")}`);
      expect(init?.method).toBe("GET");
      expect(init?.credentials).toBe("include");
    });

    it("throws ApiError on a non-2xx verify response", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(400, { detail: "expired or used" }),
      );

      const err = await verifyToken("bad").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({
        status: 400,
        message: "expired or used",
      });
    });
  });

  describe("refresh", () => {
    it("returns the access token on 200", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(200, { access_token: "fresh", token_type: "bearer" }),
      );

      await expect(refresh()).resolves.toEqual({ access_token: "fresh" });
    });

    it("sends credentials include to /auth/refresh", async () => {
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(200, { access_token: "fresh", token_type: "bearer" }));

      await refresh();
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${AUTH_BASE}/refresh`);
      expect(init?.method).toBe("POST");
      expect(init?.credentials).toBe("include");
    });

    it("returns null on a 401 (no valid session)", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(emptyResponse(401));
      await expect(refresh()).resolves.toBeNull();
    });

    it("returns null when fetch itself rejects (network error)", async () => {
      vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network down"));
      await expect(refresh()).resolves.toBeNull();
    });
  });

  describe("logout / logoutAll", () => {
    it("logout POSTs to /auth/logout with credentials include", async () => {
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(emptyResponse(204));

      await logout();
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${AUTH_BASE}/logout`);
      expect(init?.method).toBe("POST");
      expect(init?.credentials).toBe("include");
    });

    it("logoutAll POSTs to /auth/logout-all with credentials include", async () => {
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(emptyResponse(204));

      await logoutAll();
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${AUTH_BASE}/logout-all`);
      expect(init?.method).toBe("POST");
      expect(init?.credentials).toBe("include");
    });
  });

  describe("authenticatedRequest", () => {
    it("attaches Authorization Bearer header when a token is set, and credentials include", async () => {
      setStoredAccessToken("my-token");
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(200, { ok: true }));

      await authenticatedRequest("/api/v1/users/me");

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(`${API_BASE}/api/v1/users/me`);
      expect(init?.credentials).toBe("include");
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer my-token");
    });

    it("omits the Authorization header when no token is set but still sends credentials include", async () => {
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(200, { ok: true }));

      await authenticatedRequest("/api/v1/users/me");

      const [, init] = fetchMock.mock.calls[0];
      expect(init?.credentials).toBe("include");
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBeNull();
    });

    it("on a 401 performs ONE silent refresh and retries with the new token", async () => {
      setStoredAccessToken("stale-token");
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        // 1) original protected request -> 401
        .mockResolvedValueOnce(emptyResponse(401))
        // 2) refresh -> new token
        .mockResolvedValueOnce(
          jsonResponse(200, { access_token: "new-token", token_type: "bearer" }),
        )
        // 3) retry of original request -> 200
        .mockResolvedValueOnce(jsonResponse(200, { ok: true }));

      const res = await authenticatedRequest("/api/v1/users/me");

      expect(res.status).toBe(200);
      expect(fetchMock).toHaveBeenCalledTimes(3);

      // refresh call hit /auth/refresh
      expect(fetchMock.mock.calls[1][0]).toBe(`${AUTH_BASE}/refresh`);

      // retry used the refreshed token
      const retryHeaders = new Headers(fetchMock.mock.calls[2][1]?.headers);
      expect(retryHeaders.get("Authorization")).toBe("Bearer new-token");

      // in-memory token updated to the refreshed value
      expect(getAccessToken()).toBe("new-token");
    });

    it("clears the in-memory token and surfaces the 401 when refresh returns null (no loop)", async () => {
      setStoredAccessToken("stale-token");
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        // 1) original protected request -> 401
        .mockResolvedValueOnce(emptyResponse(401))
        // 2) refresh -> 401 (refresh() resolves null)
        .mockResolvedValueOnce(emptyResponse(401));

      const res = await authenticatedRequest("/api/v1/users/me");

      // surfaces the original 401, does NOT retry again
      expect(res.status).toBe(401);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      // in-memory token cleared
      expect(getAccessToken()).toBeNull();
    });

    it("does not attempt a refresh when retryOnUnauthorized is false", async () => {
      setStoredAccessToken("stale-token");
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(emptyResponse(401));

      const res = await authenticatedRequest("/api/v1/users/me", {
        retryOnUnauthorized: false,
      });

      expect(res.status).toBe(401);
      expect(fetchMock).toHaveBeenCalledTimes(1);
      // token untouched because no refresh was attempted
      expect(getAccessToken()).toBe("stale-token");
    });

    it("returns non-401 responses directly without refreshing", async () => {
      setStoredAccessToken("token");
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(jsonResponse(500, { detail: "boom" }));

      const res = await authenticatedRequest("/api/v1/users/me");
      expect(res.status).toBe(500);
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
  });
});
